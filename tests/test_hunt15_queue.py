"""Hunt phase 1.5, area `queue`: the AI task queue, the tasks, and the guard on what an AI may read.

Every note and open point phases 0 and 1 left in this area, settled: each test states what ENLENS should do (the
ledger, .claude/audits/2026-11-19-phase1.5/ledger/queue.md, says which failed and were fixed, and which passed on the
code as it was)."""
from __future__ import annotations

import json

import pytest

from enlens_claims import profile, taskqueue, tasks


def _label_tasks(ws, n=3) -> set[str]:
    pids = [r[0] for r in ws.query("SELECT passage_id FROM passages WHERE section='body' ORDER BY passage_id LIMIT ?",
                                   (n,))]
    with tasks.queueing():
        profile.make_label_tasks(ws, "sdg", pids, "haiku")
    ids = {r[0] for r in ws.query("SELECT task_id FROM tasks WHERE kind='label' AND queued=1")}
    assert ids
    return ids


# ---------------------------------------------------------------------------------------------
# item 1 (the owner's): Hold means no task of that kind is handed out, to anyone, until released
# ---------------------------------------------------------------------------------------------
def test_a_helper_that_names_a_kind_on_hold_is_handed_none_of_it(loaded):
    """A helper started before the person pressed *Hold* keeps asking for its kind by name: `next_tasks(kind=…)`
    handed it out all the same."""
    ids = _label_tasks(loaded)
    taskqueue.set_order(loaded, "label", "hold")
    for kw in ({}, {"model": "haiku"}, {"helper": "enlens-labeller"}):
        got = taskqueue.next_tasks(loaded, "label", **kw)
        assert got["claim"] is None and not got.get("tasks"), got
        assert "hold" in got["note"].lower(), got["note"]
    assert taskqueue.next_tasks(loaded)["claim"] is None   # nor without a kind named
    assert not loaded.scalar("SELECT COUNT(*) FROM tasks WHERE claimed_by IS NOT NULL AND claimed_by != ''")
    assert not loaded.scalar("SELECT COUNT(*) FROM ai_sent")   # nothing left the computer
    taskqueue.set_order(loaded, "label", "go")
    got = taskqueue.next_tasks(loaded, "label")
    assert got["claim"] and {t["task_id"] for t in got["tasks"]} <= ids


def test_what_is_sent_shows_nothing_of_a_kind_on_hold(loaded):
    """*See what is sent* named the kind: it showed the batch as about to be sent though Hold keeps it back."""
    _label_tasks(loaded)
    taskqueue.set_order(loaded, "label", "hold")
    pv = taskqueue.preview(loaded, "label")
    assert not pv.get("tasks"), pv
    assert "hold" in pv["note"].lower()


def test_a_job_waiting_on_a_kind_on_hold_says_it_is_held(loaded):
    """The line a waiting job shows said "Waiting for Claude Code: 3 passages to label" for a kind no helper is
    handed while it is on Hold."""
    _label_tasks(loaded)
    taskqueue.set_order(loaded, "label", "hold")
    info = taskqueue.queue_info(loaded, "label")
    assert "hold" in info["text"].lower() and "Go on" in info["text"], info["text"]
    assert info["held"] is True
    taskqueue.set_order(loaded, "label", "go")
    info = taskqueue.queue_info(loaded, "label")
    assert info["text"].startswith("Waiting for Claude Code") and info["held"] is False


def test_the_command_line_hands_out_no_task_of_a_kind_on_hold(loaded):
    """`enlens export-tasks` and `enlens run` named the kind and handed its tasks to a file or a model whatever the
    queue's Hold said."""
    from helpers_mixed_corpus import Local

    ids = _label_tasks(loaded)
    taskqueue.set_order(loaded, "label", "hold")
    with pytest.raises(ValueError, match="on Hold"):
        tasks.export(loaded, "label")
    with pytest.raises(ValueError, match="on Hold"):
        tasks.run(loaded, "label", Local(), model="m")
    assert {r[0] for r in loaded.query("SELECT task_id FROM tasks WHERE kind='label' AND status='pending'")} >= ids
    assert not loaded.scalar("SELECT COUNT(*) FROM results")
    taskqueue.set_order(loaded, "label", "go")
    assert tasks.export(loaded, "label")


# ---------------------------------------------------------------------------------------------
# items 2 and 3: words of documents in *Name the groups*, and what the guard sees of them
# ---------------------------------------------------------------------------------------------
from test_concept_group_names import FakeModel as _GroupModel, project  # noqa: E402,F401  (fixture)

from enlens_claims import access, groupnames, terms  # noqa: E402
from enlens_claims.conceptmap import Filters  # noqa: E402


def _storage_docs(ws) -> tuple[list[str], list[str]]:
    docs = {r[1]: r[0] for r in ws.query("SELECT doc_id, title FROM documents")}
    storage = [docs["Storage review"], docs["Storage outlook"]]
    return storage, [d for d in docs.values() if d not in storage]


class _BatteryNamer(_GroupModel):
    """Names every group "Battery prices talk": words that occur only in the two storage documents."""

    def complete(self, kind, system, user, model, payload):
        out = json.loads(super().complete(kind, system, user, model, payload))
        return json.dumps({**out, "name": "Battery prices talk"})


def test_naming_the_groups_again_sends_no_earlier_name_drawn_from_documents_now_marked_no_ai(project):  # noqa: F811
    """*Name the groups again* sends the name the AI drafted before ("give another than this one"). Drafted while
    the storage documents were open to Claude, it holds their words; once they are marked No AI it still went."""
    storage, _others = _storage_docs(project)
    first = _BatteryNamer()
    got = groupnames.name_groups(project, Filters(), 30, "unnamed", first, "claude-haiku-5-5")
    assert got["named"] and any("battery" in p.lower() for p in first.prompts)   # the storage documents were read
    access.set_documents(project, storage, "none")
    again = _GroupModel()
    groupnames.name_groups(project, Filters(), 30, "again", again, "claude-haiku-5-5")
    assert again.prompts   # groups found in the other documents are still named
    leaked = [p for p in again.prompts if "battery" in p.lower()]
    assert not leaked, leaked[0]


def test_a_task_naming_a_group_again_leaves_the_queue_when_the_earlier_names_documents_become_no_ai(project):  # noqa: F811
    """The same while the task waits for Claude Code: the earlier name is words of the documents it was drafted from,
    so marking them No AI takes the task out of the queue (as for the concepts it names)."""
    storage, _others = _storage_docs(project)
    groupnames.name_groups(project, Filters(), 30, "unnamed", _BatteryNamer(), "claude-haiku-5-5")
    allowed = {"cloud"}
    made = groupnames.payloads(project, Filters(), 30, "again", allowed)["tasks"]
    with_before = [p for _g, p in made if p.get("before")]
    assert with_before and all(p["before"] == "Battery prices talk" for p in with_before)
    with project.connect() as cx:
        for p in with_before:
            assert set(storage) & set(p[access.WORDS_KEY].get("docs") or []), p[access.WORDS_KEY]
            assert access.label_payload(cx, p, provider=access.ANTHROPIC) == "cloud"
    access.set_documents(project, storage, "none")
    with project.connect() as cx:
        for p in with_before:
            assert access.label_payload(cx, p, provider=access.ANTHROPIC) != "cloud"


def test_a_concept_named_by_none_of_its_wordings_carries_no_words_of_a_document_no_ai_may_read(project):  # noqa: F811
    """A concept joined by an abbreviation is named "long form (SHORT)", which is none of its wordings; the guard
    looked at the concept's map id (its first wording) alone. When the long form is written only in documents
    marked No AI, its words must stay out of *Name the groups* and out of the task's guard."""
    storage, _others = _storage_docs(project)
    ids = {r[1]: r[0] for r in project.query("SELECT term_id, label FROM terms")}
    short, long = ids["storage"], ids["battery prices"]   # "storage" in every storage and solar document
    assert short < long   # the map shows the concept by its first wording's id: the short form's, open to Claude
    # "battery prices (S)": an abbreviation whose long form only the storage documents write
    with project.connect() as cx:
        cx.execute("INSERT OR REPLACE INTO concept_links VALUES (?,?,?,?,?,?,?,?,?)",
                   (short, long, "same", "abbreviation", 1.0, "battery prices (S)", "S", None, "2026-01-01T00:00:00"))
    terms.rebuild_concepts(project)
    assert project.scalar("SELECT label FROM concepts") == "battery prices (S)"
    access.set_documents(project, storage, "none")
    model = _GroupModel()
    groupnames.name_groups(project, Filters(), 30, "unnamed", model, "claude-haiku-5-5")
    leaked = [p for p in model.prompts if "battery" in p.lower()]
    assert not leaked, leaked[0]
    made = groupnames.payloads(project, Filters(), 30, "unnamed", {"cloud"})["tasks"]
    with project.connect() as cx:
        for _g, p in made:
            if any("battery" in c.lower() for c in p["concepts"]):
                assert access.label_payload(cx, p, provider=access.ANTHROPIC) != "cloud"
        # a task made before `words_of` (an earlier version), naming the concept by its map id alone
        old = {"concepts": ["battery prices (S)"], "concept_ids": [short], "map_groups": [[short]], "passages": []}
        assert access.label_payload(cx, old, provider=access.ANTHROPIC) == "none"


# ---------------------------------------------------------------------------------------------
# item 4: a definition the local model drafted, once kept, goes with every label task (docs/PRIVACY.md says so)
# ---------------------------------------------------------------------------------------------
def test_a_kept_definition_drafted_by_the_local_model_goes_with_label_tasks_and_the_editor_said_so(tmp_path,
                                                                                                     monkeypatch):
    """docs/PRIVACY.md: "a definition the local model drafted from documents marked *Only a local AI* does too once it
    is kept, so the editor says to rewrite it". What a label task of another document carries, and what the draft
    the editor receives says about who read it (the line under the draft is shown for reader "local")."""
    import test_code_definition_ai as tcd

    from enlens_claims import codebooks
    from enlens_claims import home as ehome

    gen = tcd.project.__wrapped__(tmp_path, monkeypatch)
    ws, a, b = next(gen)
    try:
        access.set_documents(ws, [a], "local")
        local = tcd.FakeModel(local=True)
        ehome.save_settings({**ehome.load_settings(), "restricted_server": "ollama", "restricted_model": "big"})
        monkeypatch.setattr(ehome, "make_restricted_backend", lambda settings: (local, "big"))
        r = tcd._draft(ws, tcd.FakeModel())
        assert r["ok"] and r["reader"] == "local" and local.calls == 1   # the editor's line under the draft shows
        d = r["draft"]
        cb = codebooks.create(ws, "waits", "Waits")
        code = {"uid": "", "code": "Waiting", "description": d["description"], "group": "", "include": d["include"],
                "exclude": d["exclude"], "keywords": ["waited", "wait"], "examples": [],
                "ai_draft": {"model": d["model"], "at": "2026-11-19", "description": d["description"]}}
        codebooks.save(ws, "waits", {**cb, "codes": [code]})
        pid = ws.scalar("SELECT passage_id FROM passages WHERE doc_id=? AND text LIKE '%meal%'", (b,))
        profile.make_label_tasks(ws, "waits", [pid], "haiku", all_passages=True)
        rows = ws.query("SELECT payload_json, access FROM tasks WHERE kind='label'")
        assert rows and rows[0]["access"] == "cloud"   # the other document is Claude's to read
        cands = json.loads(rows[0]["payload_json"])["candidates"]
        assert any(c.get("description") == d["description"] for c in cands), cands
    finally:
        next(gen, None)
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "src/enlens_claims/gui/static/views/codebooks.js").read_text(
        encoding="utf-8")
    assert "reader: got.reader" in src   # the job's answer carries who read the passages to the draft panel
    assert 'd.reader === "local"' in src and "Words you keep go with the code to every later label task" in src


# ---------------------------------------------------------------------------------------------
# item 7: the quote check reads "10³" and "103" alike; what an add-on's store function is handed
# ---------------------------------------------------------------------------------------------
def test_an_addon_store_function_is_handed_the_passages_own_words_not_a_number_the_model_flattened(loaded):
    """The quote check normalises (NFKC): "103 tonnes" is found in "10³ tonnes". ENLENS's own kinds store the
    passage's own slice; an add-on's store function was handed the model's quote as written, a different number."""
    from enlens_claims import taskkinds

    got: list = []

    def store(cx, t, payload, answer, model):
        got.append(answer)
        return True, []

    kind = taskkinds.register(taskkinds.TaskKind(
        name="x_numbers", prompt_version="x-numbers-v1", system=lambda: "s", user=lambda p: p["text"],
        quote_from=lambda p: p["text"], quote_fields=("quote", "evidence"), store=store))
    try:
        text = "Output rose to 10³ tonnes in 2024, and 10⁶ users signed up."
        answer = {"tags": [{"quote": "rose to 103 tonnes", "claim": "103 tonnes"}],
                  "more": {"evidence": "106 users signed up"}}
        t = {"kind": "x_numbers", "task_id": "x_numbers:1"}
        with loaded.connect() as cx:
            ok, problems = tasks._store_answer(cx, t, {"text": text}, answer, "m")
        assert ok and not problems
        assert got[0]["tags"][0]["quote"] == "rose to 10³ tonnes", got[0]
        assert got[0]["more"]["evidence"] == "10⁶ users signed up", got[0]
        assert got[0]["tags"][0]["claim"] == "103 tonnes"   # a field that is no quote is the model's own
    finally:
        taskkinds.unregister(kind.name)


# ---------------------------------------------------------------------------------------------
# item 5: tasks made before phase 1, as the phase 1 fixer stated them
# ---------------------------------------------------------------------------------------------
def test_an_old_wordings_task_counts_a_member_wording_as_sent_when_its_text_is_anywhere_in_the_prompt(project):  # noqa: F811
    """Stated by the phase 1 fixer: an *Other wordings* task made before `words_of` is judged strictly: a wording of
    the concept counts as sent when its text appears anywhere in the prompt (here "grid", inside "grid storage"), and
    one that does not appear is not counted."""
    ids = {r[1]: r[0] for r in project.query("SELECT term_id, label FROM terms")}
    gs, grid, battery = ids["grid storage"], ids["grid"], ids["battery prices"]
    with project.connect() as cx:   # one concept of three wordings, joined by the person
        for a, b in ((gs, grid), (gs, battery)):
            a, b = sorted((a, b))
            cx.execute("INSERT OR REPLACE INTO concept_links VALUES (?,?,?,?,?,?,?,?,?)",
                       (a, b, "same", "person", 1.0, None, None, None, "2026-01-01T00:00:00"))
    terms.rebuild_concepts(project)
    old = {"concept": gs, "claim": "the concept: grid storage"}   # as an earlier version made it
    with project.connect() as cx:
        got = access._words_before(cx, old)
    assert sorted(got["terms"]) == sorted([gs, grid])   # "grid" counted, "battery prices" not
    storage, _others = _storage_docs(project)
    access.set_documents(project, storage, "none")
    with project.connect() as cx:   # grid storage and grid are also in the solar documents: it may still go
        assert access.label_payload(cx, old, provider=access.ANTHROPIC) == "cloud"


def test_a_group_name_task_from_before_the_update_is_asked_once_again_then_reused(project):  # noqa: F811
    """Stated by the phase 1 fixer: a group-name task now holds only the concepts its reader may read in each
    passage, so a task made by an earlier version (every concept listed) has another id: the group is asked once
    again after the update. Asked for again with the same input, the new task is the same one (no second asking)."""
    storage, _others = _storage_docs(project)
    access.set_documents(project, storage, "local")
    made = groupnames.payloads(project, Filters(), 30, "unnamed", {"cloud"})["tasks"]
    assert made
    _g, p = made[0]
    tid = groupnames.make_task(project, p, "claude-haiku-5-5")
    assert groupnames.make_task(project, p, "claude-haiku-5-5") == tid   # the same input: the same task
    old = json.loads(json.dumps(p))
    lab = p["labels"]
    for q in old["passages"]:   # as an earlier version listed them: every concept of the group
        q["concepts"] = [lab[t] for t in p["concept_ids"]][:8]
    if old["passages"] != p["passages"]:
        assert groupnames.make_task(project, old, "claude-haiku-5-5") != tid
    model = _GroupModel()
    groupnames.name_groups(project, Filters(), 30, "unnamed", model, "claude-haiku-5-5")
    n = model.calls
    assert n >= 1
    with project.connect() as cx:   # the names gone again (as if never applied): the kept answers are used
        cx.execute("DELETE FROM concept_group_names")
    groupnames.name_groups(project, Filters(), 30, "unnamed", model, "claude-haiku-5-5")
    assert model.calls == n


# ---------------------------------------------------------------------------------------------
# item 6 and QUEUE-5's untested half: exported, and no file
# ---------------------------------------------------------------------------------------------
def test_tasks_exported_with_no_file_come_back_with_requeue_and_a_waiting_job_then_ends(loaded, capsys):
    """A kill between the commit that marks tasks `exported` and the files leaves them exported with no file. The
    way back is `enlens requeue KIND` (the manual's troubleshooting table names it); a job of the app that waits on
    such a task (`wait_for`) then ends when the helper answers it."""
    import threading
    from pathlib import Path

    from enlens_claims import cli

    ids = _label_tasks(loaded, 2)
    tid = sorted(ids)[0]

    class Waiter:
        should_stop = None
        progress = None

    out: dict = {}
    th = threading.Thread(target=lambda: out.update(r=taskqueue.wait_for(loaded, tid, Waiter(), poll=0.05)),
                          daemon=True)
    th.start()
    with loaded.connect() as cx:   # the export's commit, then the kill: no file
        cx.execute("UPDATE tasks SET status='exported' WHERE kind='label'")
    assert taskqueue.next_tasks(loaded, "label")["claim"] is None   # exported: no helper is handed it
    assert cli.main(["--ws", str(loaded.root), "requeue", "label"]) == 0
    assert '"requeued": 2' in capsys.readouterr().out
    got = taskqueue.next_tasks(loaded, "label")
    assert {t["task_id"] for t in got["tasks"]} == ids
    r = taskqueue.submit(loaded, got["claim"], [{"task_id": t["task_id"], "answer": {"labels": [], "note": "none"}}
                                                for t in got["tasks"]])
    assert r["stored"] == 2, r
    th.join(10)
    assert out.get("r") == (True, [])
    manual = (Path(__file__).resolve().parent.parent / "docs/manual/troubleshooting.md").read_text(encoding="utf-8")
    assert "Tasks stuck as `exported`" in manual and "enlens requeue KIND" in manual


def test_a_job_waiting_on_a_task_written_to_the_file_queue_ends_when_its_file_answer_is_imported(loaded):
    """QUEUE-5's half the phase 1 hunter did not test: a task an app job waits on is exported (the file queue); the
    wait must end once the file's answer is imported, not run for ever."""
    import threading

    ids = _label_tasks(loaded, 1)
    tid = next(iter(ids))

    class Waiter:
        should_stop = None
        progress = None

    out: dict = {}
    th = threading.Thread(target=lambda: out.update(r=taskqueue.wait_for(loaded, tid, Waiter(), poll=0.05)),
                          daemon=True)
    th.start()
    files = tasks.export(loaded, "label")
    assert files and loaded.scalar("SELECT status FROM tasks WHERE task_id=?", (tid,)) == "exported"
    res = loaded.root / "results" / "label" / files[0].name
    res.write_text(json.dumps({"task_id": tid, "model": "m", "output": {"labels": [], "note": "none"}}) + "\n",
                   encoding="utf-8")
    assert tasks.import_results(loaded, [res])["ok"] == 1
    th.join(10)
    assert out.get("r") == (True, [])


# ---------------------------------------------------------------------------------------------
# notes/queue.md "Not proven"
# ---------------------------------------------------------------------------------------------
def test_a_task_given_a_new_text_while_a_helper_holds_it_is_taken_from_that_helper(loaded):
    """`replace_task` gave a held task a new payload and kept the claim (when the new setting stays cloud): the helper
    answered the old text, and its answer was checked against the new one (quotes rejected, attempts used up)."""
    ids = _label_tasks(loaded, 1)
    tid = next(iter(ids))
    got = taskqueue.next_tasks(loaded, "label")
    assert [t["task_id"] for t in got["tasks"]] == [tid]
    payload = json.loads(loaded.scalar("SELECT payload_json FROM tasks WHERE task_id=?", (tid,)))
    new = {**payload, "context": "Another passage before this one."}
    with loaded.connect() as cx:
        assert tasks.replace_task(cx, tid, "label", "haiku", new)
    r = taskqueue.submit(loaded, got["claim"], [{"task_id": tid, "answer": {"labels": [], "note": "old text"}}])
    assert r["stored"] == 0 and "lapsed" in r["results"][0]["problems"][0], r
    assert loaded.scalar("SELECT attempts FROM tasks WHERE task_id=?", (tid,)) == 0
    again = taskqueue.next_tasks(loaded, "label")   # handed out again, with its new text
    assert [t["task_id"] for t in again["tasks"]] == [tid] and "Another passage before" in again["tasks"][0]["prompt"]
    # the same payload given again changes nothing for the helper that holds it
    with loaded.connect() as cx:
        tasks.replace_task(cx, tid, "label", "haiku", new)
    r = taskqueue.submit(loaded, again["claim"], [{"task_id": tid, "answer": {"labels": [], "note": "fine"}}])
    assert r["stored"] == 1, r


def test_refresh_while_a_helper_holds_a_task_stores_its_answer_under_the_instructions_it_was_given(loaded):
    """`enlens refresh` resets tasks a claim may hold, under the prompt version of now. The helper was given the
    task's text as rendered now (the version of now), so its answer is recorded under that version: right."""
    from enlens_claims import prompts

    ids = _label_tasks(loaded, 1)
    tid = next(iter(ids))
    with loaded.connect() as cx:   # made by an earlier version
        cx.execute("UPDATE tasks SET prompt_version='label-old' WHERE task_id=?", (tid,))
    got = taskqueue.next_tasks(loaded, "label")
    assert tasks.refresh(loaded, "label") == 1
    r = taskqueue.submit(loaded, got["claim"], [{"task_id": tid, "answer": {"labels": [], "note": "none"}}])
    assert r["stored"] == 1, r
    assert loaded.scalar("SELECT prompt_version FROM results WHERE task_id=?", (tid,)) == prompts.VERSIONS["label"]


def test_an_answer_from_the_file_queue_is_kept_under_the_instructions_written_beside_its_file(loaded, monkeypatch):
    """`import_results` stored an answer for any task not done: after an update and `enlens refresh`, an answer to the
    file's old instructions was recorded under the new version."""
    from enlens_claims import prompts

    ids = _label_tasks(loaded, 1)
    tid = next(iter(ids))
    files = tasks.export(loaded, "label")
    written = prompts.VERSIONS["label"]
    monkeypatch.setitem(prompts.VERSIONS, "label", "label-next")   # an update since
    tasks.refresh(loaded, "label")
    res = loaded.root / "results" / "label" / files[0].name
    res.write_text(json.dumps({"task_id": tid, "model": "m", "output": {"labels": [], "note": "none"}}) + "\n",
                   encoding="utf-8")
    assert tasks.import_results(loaded, [res])["ok"] == 1
    assert loaded.scalar("SELECT prompt_version FROM results WHERE task_id=?", (tid,)) == written


def test_an_answer_from_the_file_queue_is_not_stored_for_a_task_a_helper_holds(loaded):
    """`import_results` stored an answer for a task requeued and taken by a Claude Code helper since: two answers for
    one task, and the helper's then refused."""
    ids = _label_tasks(loaded, 1)
    tid = next(iter(ids))
    files = tasks.export(loaded, "label")
    tasks.requeue(loaded, "label")
    got = taskqueue.next_tasks(loaded, "label")
    assert [t["task_id"] for t in got["tasks"]] == [tid]
    res = loaded.root / "results" / "label" / files[0].name
    res.write_text(json.dumps({"task_id": tid, "model": "m", "output": {"labels": [], "note": "late"}}) + "\n",
                   encoding="utf-8")
    stats = tasks.import_results(loaded, [res])
    assert stats["ok"] == 0 and stats.get("held_by_a_helper") == 1, stats
    r = taskqueue.submit(loaded, got["claim"], [{"task_id": tid, "answer": {"labels": [], "note": "helper"}}])
    assert r["stored"] == 1, r
    # a task never exported and in no helper's hands (the SDG pack's) is still taken from a file, as before
    with loaded.connect() as cx:
        cx.execute("UPDATE tasks SET status='pending', queued=0, claimed_by=NULL WHERE task_id=?", (tid,))
    res.write_text(json.dumps({"task_id": tid, "model": "m", "output": {"labels": [], "note": "file"}}) + "\n",
                   encoding="utf-8")
    assert tasks.import_results(loaded, [res])["ok"] == 1


def test_answering_the_queue_here_counts_a_second_reading_once_when_it_is_read(loaded):
    """`run_here` with a local server: a task answered and waiting for the stronger model was counted "answered" at
    once (run_one returns at once for it), then read again after the run and counted once more as stepped up."""
    from helpers_mixed_corpus import Local

    from enlens_claims import routing

    ids = _label_tasks(loaded, 2)
    first, second = sorted(ids)
    with loaded.connect() as cx:   # the first: answered, and to be read again by the stronger model
        cx.execute("UPDATE tasks SET status='done', again=1, step=1, attempts=1 WHERE task_id=?", (first,))
        cx.execute("INSERT INTO results(task_id, attempt, kind, model, prompt_version, raw_json, valid, errors_json, "
                   "received_at) VALUES (?, 1, 'label', 'tiny', 'x', '{\"labels\": []}', 1, '[]', '2026-01-01')",
                   (first,))
    be = Local()
    be.router = routing.Router(route="local", large="big", small="tiny")
    out = taskqueue.run_here(loaded, be, kinds=["label"])
    assert out["answered"] + out["failed"] == 1, out           # the one asked in the run
    assert out["stepped_up"]["stepped_up"] + out["stepped_up"]["kept_first"] == 1, out
    assert second


# ---------------------------------------------------------------------------------------------
# review notes (reviews/sync.md) and the rest of notes/queue.md
# ---------------------------------------------------------------------------------------------
def test_a_job_line_counts_claude_codes_whole_share_waiting_and_being_answered(loaded):
    """notes/queue.md QUEUE-3, the part not claimed: `queue_info`'s "waiting" holds the tasks a helper is answering
    too, where `status` lists them apart. Its docstring says so: the job's line is Claude Code's whole share."""
    _label_tasks(loaded, 4)
    taskqueue.next_tasks(loaded, "label", n=1)
    st = next(k for k in taskqueue.status(loaded, "p")["kinds"] if k["kind"] == "label")
    info = taskqueue.queue_info(loaded, "label")
    assert (st["waiting"], st["being_answered"]) == (3, 1)
    assert info["waiting"] == 4 and info["being_answered"] == 1


def test_tasks_a_run_held_when_it_stopped_are_handed_out_once_its_time_is_up(loaded):
    """reviews/sync.md: the QUEUE-5/-6 tasks are released when the claim lapses (30 minutes) or by the answer. A
    command-line run stopped hard leaves its 'here-' mark: the task is free again after CLAIM_MINUTES."""
    ids = _label_tasks(loaded, 1)
    tid = next(iter(ids))
    with loaded.connect() as cx:
        cx.execute("UPDATE tasks SET claimed_by='here-dead', claimed_at=? WHERE task_id=?",
                   (taskqueue.now(), tid))
    assert taskqueue.next_tasks(loaded, "label")["claim"] is None
    with loaded.connect() as cx:
        cx.execute("UPDATE tasks SET claimed_at='2000-01-01T00:00:00+00:00' WHERE task_id=?", (tid,))
    assert [t["task_id"] for t in taskqueue.next_tasks(loaded, "label")["tasks"]] == [tid]


def test_the_count_of_the_local_models_share_stays_quick_on_a_big_queue(mixed):  # noqa: F811
    """reviews/sync.md: with the AI mix on, `local_share` makes the sidebar's count and `queue_info` read each
    waiting row ("a few ms on 20,000 tasks: acceptable"). Measured here on 20,000 waiting tasks."""
    import time

    ws, _s = mixed
    rows = [(f"check:big{i:05d}", "check", "sonnet", "check-v5", "{}", "pending", 0, "2026-01-01", 1, "2026-01-01",
             "cloud") for i in range(20000)]
    with ws.connect() as cx:
        cx.executemany("INSERT INTO tasks(task_id, kind, model, prompt_version, payload_json, status, attempts, "
                       "created_at, queued, queued_at, access) VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
    t0 = time.perf_counter()
    info = taskqueue.queue_info(ws, "check")
    took = time.perf_counter() - t0
    assert info["for_local"] == 20000 and info["waiting"] == 0
    assert took < 1.0, took


from test_ai_mix import mixed  # noqa: E402,F401  (fixture)


# ---------------------------------------------------------------------------------------------
# item 8: a connector's words reaching a person in the app
# ---------------------------------------------------------------------------------------------
def test_reading_further_while_a_round_waits_says_what_the_person_can_do_not_the_connectors_words(loaded):
    """A check whose round waits to be judged (by a Claude chat, a helper of the queue, or the person): *Read the new
    documents* and *Read more passages* in the app ended in the connector's words, "Grade the passages already shown
    first (submit_grades)", a tool the person never sees."""
    from helpers_mixed_corpus import Local

    from enlens_claims import claimcheck

    r = claimcheck.open_check(loaded, "Green hydrogen raises water stress", terms=["water", "hydrogen"])
    cid = r["check_id"]
    with pytest.raises(ValueError) as e:
        claimcheck.continue_check(loaded, cid, Local(), "m")
    assert "submit_grades" not in str(e.value) and "judged" in str(e.value), str(e.value)
    hyp = loaded.scalar("SELECT hyp_id FROM user_claims WHERE claim_id=?", (cid,))
    with pytest.raises(ValueError) as e:   # the same words as *Read these* (further_round_waits)
        claimcheck.read_new_documents(loaded, hyp, Local(), "m") if claimcheck.new_documents(loaded, hyp) else \
            claimcheck.continue_check(loaded, cid, Local(), "m", doc_ids=[])
    assert str(e.value) == claimcheck.further_round_waits(loaded, hyp)
    # the connector keeps its own words: they tell Claude which tool to call
    with pytest.raises(ValueError, match="submit_grades"):
        claimcheck.more_passages(loaded, cid)


def test_a_wording_found_in_no_document_any_more_keeps_its_task_from_every_ai(project):  # noqa: F811
    """reviews/sync.md: "a term with no mentions left makes its task none (safe)". A waiting task naming a wording
    whose documents were all removed goes to no AI."""
    tid = terms.find_term(project, "battery prices")
    payload = {"concept": tid, "claim": "the concept: battery prices", access.WORDS_KEY: {"terms": [tid]}}
    with project.connect() as cx:
        assert access.label_payload(cx, payload, provider=access.ANTHROPIC) == "cloud"
        cx.execute("DELETE FROM term_mentions WHERE term_id=?", (tid,))
        assert access.label_payload(cx, payload, provider=access.ANTHROPIC) == "none"
