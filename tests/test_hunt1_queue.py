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
    assert "Claude Code: 2" not in info["text"], info["text"]   # it may say the local model's share is waiting


def test_a_batch_says_still_waiting_only_for_what_claude_code_will_be_handed(mixed):  # noqa: F811
    """Sibling of QUEUE-3: `next_tasks`' "still_waiting" (and the preview's, and the app's helper runs, which end a
    helper as failed while it says tasks wait) counted the AI mix's local share (`_waiting_count`)."""
    ws, _s = mixed
    for _ in range(3):
        _check_task(ws)
    with ws.connect() as cx:   # one stepped up to Claude: Claude Code's to take
        cx.execute("UPDATE tasks SET step=1 WHERE task_id=(SELECT MIN(task_id) FROM tasks WHERE kind='check')")
    st = taskqueue.status(ws, "p")
    assert (st["waiting"], st["for_local"]) == (1, 2)
    got = taskqueue.next_tasks(ws, "check")
    assert len(got["tasks"]) == 1
    assert got["still_waiting"] == taskqueue.status(ws, "p")["waiting"] == 0


def test_the_sidebar_counts_no_task_of_the_local_models_share(mixed, monkeypatch):  # noqa: F811
    """Sibling of QUEUE-3: the sidebar's and the Overview's count (`/api/state` queue, server._queue_summary) counted
    every task in the queue, also the AI mix's local share that Claude Code is never handed."""
    from enlens_claims.gui import server

    ws, _s = mixed
    _check_task(ws)
    _check_task(ws)
    st = taskqueue.status(ws, "p")
    assert st["for_local"] == 2
    monkeypatch.setattr(server.home, "open_project", lambda name: ws)
    got = server.App._queue_summary(server.App.__new__(server.App), "p")
    assert got == {"waiting": st["waiting"] + st["being_answered"]} == {"waiting": 0}


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


def test_the_command_line_says_how_many_tasks_it_left_to_the_helper(loaded):
    """QUEUE-5 and -6, what a person is told: `export-tasks` and `run` say how many tasks they left to the helper that
    holds them, and the tasks of the kind no claim holds are still written and asked."""
    from helpers_mixed_corpus import Local

    pids = [r[0] for r in loaded.query("SELECT passage_id FROM passages WHERE section='body' ORDER BY passage_id "
                                       "LIMIT 5")]
    with tasks.queueing():
        profile.make_label_tasks(loaded, "sdg", pids, "haiku")
    held = {t["task_id"] for t in taskqueue.next_tasks(loaded, "label", n=2)["tasks"]}
    free = {r[0] for r in loaded.query("SELECT task_id FROM tasks WHERE kind='label' AND status='pending'")} - held
    assert len(held) == 2 and free
    report: dict = {}
    files = tasks.export(loaded, "label", report=report)
    written = {json.loads(line)["task_id"] for f in files for line in f.read_text(encoding="utf-8").splitlines()}
    assert report == {"held": len(held)} and written == free
    with loaded.connect() as cx:   # the written ones back, to be asked here
        cx.execute("UPDATE tasks SET status='pending' WHERE status='exported'")
    stats = tasks.run(loaded, "label", Local(), model="m")
    assert stats["left_to_the_helper_answering_them"] == len(held)
    asked = {r[0] for r in loaded.query("SELECT DISTINCT task_id FROM results")}
    assert free <= asked and not (held & asked)
    assert not loaded.scalar("SELECT COUNT(*) FROM tasks WHERE claimed_by LIKE 'here-%'")   # this run let go of them


def test_a_framework_task_keeps_no_title_of_an_evidence_document_marked_no_ai_since(tmp_path, monkeypatch):
    """Sibling of QUEUE-2 (the hunter's suspicion, theoryframe._evidence_titles): the framework task names the titles
    of the researcher's own documents with no id beside them, so marking one of them No AI after the task was made
    never makes the task stricter: waiting in Claude Code's queue, it is still handed out with that title."""
    import test_theory_framework as ttf

    from enlens_claims import theoryframe

    gen = ttf.project.__wrapped__(tmp_path, monkeypatch)
    ws, meadows, practice, evidence = next(gen)
    try:
        ttf._started(ws, meadows, practice)
        r = theoryframe.read(ws, ttf.FakeModel(), "claude-sonnet-5-5")
        tid = r["frame_task"]
        payload = json.loads(ws.scalar("SELECT payload_json FROM tasks WHERE task_id=?", (tid,)))
        title = ws.scalar("SELECT title FROM documents WHERE doc_id=?", (evidence,))
        assert title in payload["evidence_titles"]
        with ws.connect() as cx:
            assert access.label_payload(cx, payload, provider=access.ANTHROPIC) == "cloud"
        access.set_documents(ws, [evidence], "none")
        with ws.connect() as cx:   # the setting such a task gets now, waiting or asked again
            assert access.label_payload(cx, payload, provider=access.ANTHROPIC) != "cloud"
    finally:
        next(gen, None)


def test_a_task_made_before_the_update_leaves_the_queue_too(project):
    """QUEUE-1 and -2 for data already on disk: an *Other wordings* task and a *Name the groups* task made by an
    earlier version (no `words_of` in their payloads) wait in the queue; the documents their words come from are set
    to No AI: neither is handed out any more."""
    tid_term = terms.find_term(project, "battery")
    grid = terms.find_term(project, "grid")
    with project.connect() as cx, tasks.queueing(True):
        tasks._insert_task(cx, "expand:concept:old:1", "expand", "sonnet",
                           {"concept": tid_term, "claim": "the concept: battery"})
        pid = cx.execute("SELECT passage_id FROM passages p JOIN documents d ON d.doc_id=p.doc_id "
                         "WHERE d.title='Solar report' LIMIT 1").fetchone()[0]
        tasks._insert_task(cx, "group_name:old", "group_name", "haiku",
                           {"concepts": ["grid", "battery"], "concept_ids": [grid, tid_term],
                            "labels": {grid: "grid", tid_term: "battery"}, "map_groups": [[grid, tid_term]],
                            "group_index": 0, "passages": [{"n": 1, "passage_id": pid, "page": 1, "text": "x",
                                                            "concepts": ["grid"]}]})
    assert project.scalar("SELECT COUNT(*) FROM tasks WHERE queued=1 AND access='cloud'") == 2
    _no_ai_storage(project)
    for kind in ("expand", "group_name"):
        got = taskqueue.next_tasks(project, kind)
        assert not got.get("tasks"), got


def _old_words_level(cx, term: str) -> str:
    """`words_floor`'s answer for one term as first written: every mention, joined to its passage's document."""
    docs = {r[0] for r in cx.execute("SELECT DISTINCT p.doc_id FROM term_mentions m JOIN passages p ON "
                                     "p.passage_id=m.passage_id WHERE m.term_id=?", (term,))}
    lv = access.levels(cx, docs, budget=False) if docs else {}
    return min((lv.get(d, "none") for d in docs), key=access.RANK.__getitem__, default="none")


def test_the_guard_on_words_reads_each_term_once_per_relabel_whatever_the_number_of_tasks(project):
    """Review of hunt phase 1: `words_floor` read every mention of every term of each waiting group-name or
    other-wordings task, for each task, on every relabel (under the write lock). The work is bounded now: a term is
    looked at once per relabel however many tasks name it, one seek per document at most, stopping at the first
    document Claude may read; and the answer is the one the full reading gave."""
    terms_all = [r[0] for r in project.query("SELECT term_id FROM terms ORDER BY tf DESC LIMIT 8")]
    terms_all = list(dict.fromkeys(terms_all + [terms.find_term(project, "battery")]))   # in No AI documents only
    n_docs = project.scalar("SELECT COUNT(*) FROM documents")
    none, others = _no_ai_storage(project)
    access.set_documents(project, others[:1], "local")

    def tasks_of(n):
        with project.connect() as cx:
            cx.execute("DELETE FROM tasks WHERE kind='group_name'")
            for i in range(n):
                tasks._insert_task(cx, f"group_name:cost{i}", "group_name", "haiku",
                                   {"concepts": [], "concept_ids": terms_all, "passages": [],
                                    access.WORDS_KEY: {"terms": terms_all}})

    def reads():
        seen: list[str] = []
        cx = project._conn()
        cx.set_trace_callback(lambda sql: seen.append(sql) if "term_mentions" in sql else None)
        try:
            with project.connect() as c:
                access.relabel(c)
        finally:
            cx.set_trace_callback(None)
        return len(seen)

    tasks_of(3)
    few = reads()
    tasks_of(30)
    many = reads()
    assert 0 < few == many <= len(terms_all) * n_docs, (few, many)
    got = set()
    with project.connect() as cx:   # the same answer as reading every mention
        for t in terms_all:
            with access.reading_for(None):
                lv = access.words_floor(cx, {access.WORDS_KEY: {"terms": [t]}})
                assert lv == _old_words_level(cx, t), t
                got.add(lv)
    assert {"cloud", "none"} <= got


def test_a_framework_task_made_before_the_update_keeps_no_title_of_a_document_marked_no_ai_since(tmp_path,
                                                                                                    monkeypatch):
    """Review of hunt phase 1: a framework task waiting across the update has no `words_of`, so the titles of the
    researcher's own documents in it stayed unguarded. `_words_before` finds their documents by title."""
    import test_theory_framework as ttf

    from enlens_claims import theoryframe

    gen = ttf.project.__wrapped__(tmp_path, monkeypatch)
    ws, meadows, practice, evidence = next(gen)
    try:
        ttf._started(ws, meadows, practice)
        r = theoryframe.read(ws, ttf.FakeModel(), "claude-sonnet-5-5")
        payload = json.loads(ws.scalar("SELECT payload_json FROM tasks WHERE task_id=?", (r["frame_task"],)))
        payload.pop(access.WORDS_KEY)   # as an earlier version made it
        with ws.connect() as cx:
            assert access.label_payload(cx, payload, provider=access.ANTHROPIC) == "cloud"
        access.set_documents(ws, [evidence], "none")
        with ws.connect() as cx:
            assert access.label_payload(cx, payload, provider=access.ANTHROPIC) == "none"
    finally:
        next(gen, None)


def test_a_limited_run_answers_free_tasks_when_a_helper_holds_the_first_ones(loaded):
    """Review of hunt phase 1 (QUEUE-6): `enlens run <kind> --limit N` took the first N pending tasks; when a helper
    held all of them, the run did nothing though free tasks remained."""
    from helpers_mixed_corpus import Local

    pids = [r[0] for r in loaded.query("SELECT passage_id FROM passages WHERE section='body' ORDER BY passage_id "
                                       "LIMIT 5")]
    with tasks.queueing():
        profile.make_label_tasks(loaded, "sdg", pids, "haiku")
    held = {t["task_id"] for t in taskqueue.next_tasks(loaded, "label", n=2)["tasks"]}
    assert held == set(sorted(r[0] for r in loaded.query("SELECT task_id FROM tasks WHERE kind='label'"))[:2])
    stats = tasks.run(loaded, "label", Local(), limit=2, model="m")
    asked = {r[0] for r in loaded.query("SELECT DISTINCT task_id FROM results")}
    assert len(asked) == 2 and not (asked & held), (asked, held)
    assert stats["left_to_the_helper_answering_them"] == 2


def test_run_names_the_model_in_the_ai_log_as_the_apps_own_runs_do(loaded):
    """Review of hunt phase 1: `enlens run` on the Claude API asked and logged the task's alias ("haiku") where the
    app's runs (`run_one`) send and log the API id: one model spelled two ways in the AI log."""
    from enlens_claims import ailog, routing
    from enlens_claims.llm import AnthropicBackend

    asked = []

    class Block:
        type, text = "text", '{"labels": [], "note": "nothing here"}'

    class Msgs:
        def create(self, **kw):
            asked.append(kw["model"])
            return type("M", (), {"content": [Block()]})()

    be = AnthropicBackend(client=type("C", (), {"messages": Msgs()})())
    be.router = routing.from_settings({"backend": "anthropic", "anthropic_model": "claude-opus-5-5"})
    pid = loaded.scalar("SELECT passage_id FROM passages WHERE section='body' ORDER BY passage_id LIMIT 1")
    profile.make_label_tasks(loaded, "sdg", [pid], "haiku")
    tasks.run(loaded, "label", be)
    assert asked == ["claude-haiku-5-5"]
    rows = ailog.entries(loaded)["rows"]
    assert rows and {r["model"] for r in rows} == {"claude-haiku-5-5"}, [r["model"] for r in rows]
    assert {r[0] for r in loaded.query("SELECT model FROM results")} == {"claude-haiku-5-5"}
