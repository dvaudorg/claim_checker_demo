"""Hunt phase 1, area `queue`: the AI task queue, the tasks, and the guards on what an AI may read.

Each test asserts what ENLENS should do and fails today for the reason its docstring gives (claims/queue.md)."""
from __future__ import annotations

import asyncio
import json
import threading
import time

import pytest
from test_ai_mix import MIX, _check_task, mixed  # noqa: F401  (fixture)
from test_concept_group_names import FakeModel, project  # noqa: F401  (fixture)

from enlens_claims import access, claimcheck, groupnames, home, profile, taskqueue, tasks, terms
from enlens_claims.conceptmap import Filters
from enlens_claims.llm import BackendError, ClaudeCodeBackend


def _texts(ws, doc_ids) -> str:
    q = ",".join("?" * len(doc_ids))
    return " ".join(r[0] for r in ws.query(f"SELECT text FROM passages WHERE doc_id IN ({q})", list(doc_ids))).lower()


def _no_ai_storage(ws) -> tuple[list[str], list[str]]:
    """The two storage documents of the concept corpus marked No AI; the word "battery" is in them only."""
    docs = {r[1]: r[0] for r in ws.query("SELECT doc_id, title FROM documents")}
    none = [docs["Storage review"], docs["Storage outlook"]]
    access.set_documents(ws, none, "none")
    others = [d for d in docs.values() if d not in none]
    assert "battery" in _texts(ws, none) and "battery" not in _texts(ws, others)
    return none, others


# ---------------------------------------------------------------------------------------------
# rule 2: the document's AI setting is a wall
# ---------------------------------------------------------------------------------------------
def test_naming_a_concept_group_sends_no_concept_found_only_in_documents_marked_no_ai(project):
    """The group_name task lists every concept of the group, also one found only in documents marked No AI
    (groupnames.py:789 `payloads`, "concepts"; prompts.py:529 puts them in the prompt)."""
    _no_ai_storage(project)
    model = FakeModel()
    groupnames.name_groups(project, Filters(), 30, "unnamed", model, "claude-haiku-5-5")
    assert model.prompts  # groups were named from the documents the AI may read
    leaked = [p for p in model.prompts if "battery" in p.lower()]
    assert not leaked, leaked[0]


def test_other_wordings_of_a_concept_leave_the_queue_when_its_documents_are_set_to_no_ai(project):
    """*Other wordings* (an expand task for a concept) waits in Claude Code's queue; its documents are then set to
    No AI, yet the concept's words are still handed out: the payload names no document (terms.py:1743), so relabel
    never restricts it (access.py:612)."""
    tid_term = terms.find_term(project, "battery")
    assert tid_term
    be = ClaudeCodeBackend()
    errors: list[BaseException] = []

    def ask():
        try:
            terms.propose_wordings(project, tid_term, be, "sonnet")
        except BackendError:
            pass  # stopped below
        except BaseException as e:  # noqa: BLE001
            errors.append(e)
        finally:
            project.close()

    th = threading.Thread(target=ask, daemon=True)
    th.start()
    try:
        t0 = time.time()
        while not project.scalar("SELECT 1 FROM tasks WHERE kind='expand' AND queued=1"):
            assert time.time() - t0 < 20 and not errors, errors
            time.sleep(0.05)
        _no_ai_storage(project)   # the concept's documents: now No AI, while the task waits for Claude Code
        got = taskqueue.next_tasks(project, "expand")
        sent = [t["prompt"] for t in got.get("tasks") or []]
    finally:
        be.should_stop = lambda: True
        th.join(10)
    assert not errors, errors
    assert not any("battery" in p.lower() for p in sent), sent


# ---------------------------------------------------------------------------------------------
# rule 6: what the queue says waits is what waits
# ---------------------------------------------------------------------------------------------
def test_a_jobs_waiting_line_counts_only_the_tasks_claude_code_will_take(mixed):  # noqa: F811
    """With the AI mix, tasks the local model answers first are listed apart on the queue page (for_local), but the
    line a waiting job shows counts them as waiting for Claude Code (taskqueue.py:1217 `queue_info`)."""
    ws, _s = mixed
    _check_task(ws)
    _check_task(ws)
    st = taskqueue.status(ws, "p")
    assert st["for_local"] == 2 and st["waiting"] == 0
    info = taskqueue.queue_info(ws, "check")
    assert info["waiting"] == st["waiting"], info["text"]


def test_the_connector_lists_no_project_whose_waiting_tasks_are_all_for_the_local_model(tmp_path, monkeypatch):
    """queue_status without a project lists a project as having work although the project's own queue_status says
    nothing waits: the tasks are the AI mix's, for the local model (mcp_server.py:636 counts every WAITING task)."""
    pytest.importorskip("mcp")
    from mcp import Client

    from enlens_claims.mcp_server import build_server

    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    s = {**home.load_settings(), **MIX}
    monkeypatch.setattr(home, "load_settings", lambda strict=False: dict(s))
    from concept_corpus import write

    from enlens_claims import ingest

    ws = home.create_project("Mixwork")
    ingest.ingest(ws, [write(tmp_path / "docs")["solar"].parent])
    cid = claimcheck.new_claim(ws, "Grid storage absorbs what solar panels make.")
    picked = [dict(r) for r in ws.query("SELECT p.passage_id, p.doc_id, d.title, p.page, p.text FROM passages p "
                                        "JOIN documents d ON d.doc_id=p.doc_id ORDER BY p.passage_id LIMIT 2")]
    with ws.connect() as cx, tasks.queueing(True):
        tasks._insert_task(cx, f"check:{cid}", "check", "sonnet",
                           claimcheck._payload(ws, cid, "Grid storage absorbs what solar panels make.", None, None,
                                               picked))
    assert taskqueue.status(ws, "Mixwork")["for_local"] == 1

    async def go():
        async with Client(build_server()) as c:
            async def call(args):
                r = await c.call_tool("queue_status", args)
                assert not r.is_error, r.content[0].text
                return json.loads(r.content[0].text)
            return await call({}), await call({"project": "Mixwork"})

    every, one = asyncio.run(go())
    ws.close_all()
    assert one["waiting"] == 0
    assert [p for p in every["projects_with_work"] if p["project"] == "Mixwork"] == []


# ---------------------------------------------------------------------------------------------
# rule 3: a task is asked once
# ---------------------------------------------------------------------------------------------
def _label_batch(ws, n=3):
    pids = [r[0] for r in ws.query("SELECT passage_id FROM passages WHERE section='body' ORDER BY passage_id LIMIT ?",
                                   (n,))]
    with tasks.queueing():
        profile.make_label_tasks(ws, "sdg", pids, "haiku")
    got = taskqueue.next_tasks(ws, "label")
    assert got["claim"] and got["tasks"]
    return got


def test_the_file_queue_does_not_hand_out_a_task_claude_code_is_answering(loaded):
    """`export` writes every pending task of the kind to a file, also those a Claude Code batch holds now
    (tasks.py:1845): two outside AIs get the same task, and Claude Code's answer is then refused as "already answered"."""
    got = _label_batch(loaded)
    held = {t["task_id"] for t in got["tasks"]}
    files = tasks.export(loaded, "label")
    written = {json.loads(line)["task_id"] for f in files for line in f.read_text(encoding="utf-8").splitlines()}
    assert not (held & written), sorted(held & written)


def test_answering_a_kind_here_leaves_the_tasks_claude_code_is_answering(loaded):
    """`enlens run <kind>` (tasks.run) asks the model every pending task of the kind, also those a Claude Code batch
    holds (tasks.py:1790 `pending` ignores claims), so the same task is asked twice."""
    from helpers_mixed_corpus import Local

    got = _label_batch(loaded)
    held = {t["task_id"] for t in got["tasks"]}
    local = Local()
    tasks.run(loaded, "label", local, model="m")
    answered_here = {r[0] for r in loaded.query(
        f"SELECT task_id FROM results WHERE task_id IN ({','.join('?' * len(held))})", list(held))}
    assert not answered_here, sorted(answered_here)
