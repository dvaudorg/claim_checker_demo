"""Hunt phase 1, area `concepts` (codebooks and labels, themes, theory documents, the glossary and the concept map).

Each test asserts what ENLENS should do and fails today for the reason its docstring gives.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from enlens_claims import codebooks, frameworks, ingest, profile
from enlens_claims.store import Workspace

DEMO = Path(__file__).resolve().parents[1] / "tools" / "demo_corpus"
CODES = [{"code": "Commuting", "description": "Travel between home and the office, and its emissions.", "group": "t",
          "keywords": ["commute", "commuting", "travel"]},
         {"code": "Wellbeing", "description": "How workers feel: stress, loneliness, life satisfaction.", "group": "w",
          "keywords": ["wellbeing", "loneliness"]}]


@pytest.fixture
def demo(tmp_path) -> Workspace:
    ws = Workspace.create(tmp_path / "ws")
    ingest.ingest(ws, [DEMO])
    return ws


def _codebook(ws, name="remote", codes=CODES):
    cb = codebooks.create(ws, name, "Remote work", "project", "fresh")
    st = json.loads(json.dumps(cb))
    st["codes"] = [dict(c, include="", exclude="", examples=[]) for c in codes]
    codebooks.save(ws, name, st)
    return codebooks.load(ws, name)


def _ai_labelled(ws, fw, pids, code):
    """The AI read these passages with codebook `fw` (their label tasks are done) and labelled them with `code`."""
    profile.make_label_tasks(ws, fw, pids, "m", all_passages=True)
    with ws.connect() as cx:
        for pid in pids:
            cx.execute("UPDATE tasks SET status='done' WHERE task_id=?", (f"label:{fw}:{pid}",))
            cx.execute("INSERT INTO labels(label_id, passage_id, doc_id, framework, code, source, task_id, created_at) "
                       "VALUES (?,?,?,?,?,'model',?,?)", (profile.label_id(fw, pid, code, "model"), pid,
                                                         pid.split(":")[0], fw, code, f"label:{fw}:{pid}",
                                                         "2026-01-01T00:00:00+00:00"))


# ---- rule 1: a codebook's name is a key; a new codebook of a removed one's name starts clean -------------------------
def test_a_new_codebook_named_like_a_removed_one_does_not_inherit_its_labels_and_reading(demo):
    """Removing a codebook leaves its labels and its done `label:<name>:…` tasks; a new codebook made later under the
    same name takes them over: it counts the old labels and the AI never reads those passages for it
    (codebooks.py:1042 `remove`, codebooks.py:906 `_free_name`, profile.py:309 `label_plan`)."""
    _codebook(demo)
    pids = [r[0] for r in demo.query("SELECT passage_id FROM passages WHERE section='body' ORDER BY passage_id LIMIT 4")]
    _ai_labelled(demo, "remote", pids, "Commuting")
    codebooks.remove(demo, "remote", why="starting over")
    try:
        cb = codebooks.create(demo, "remote", "Remote work, second try", "project", "fresh")
    except ValueError:
        return   # refused in words: the name still holds the removed codebook's work
    st = json.loads(json.dumps(cb))
    st["codes"] = [dict(CODES[0], code="Travel", description="Any trip a worker makes for work, by any means.",
                        include="", exclude="", examples=[])]
    codebooks.save(demo, "remote", st)
    cb = codebooks.load(demo, "remote")
    assert cb["used"]["labels"] == 0 and cb["removed"] == []
    assert profile.effective(demo, "remote") == []
    plan = profile.label_plan(demo, "remote", all_passages=True)
    assert plan["already_read"] == 0 and set(pids) <= set(plan["passage_ids"])


# ---- rule 3: a malformed codebook file is refused in words, never a crash ------------------------------------------
def test_a_codebook_file_with_old_mac_line_endings_does_not_break_every_page(ws):
    """A CSV saved with carriage returns only (Excel for Mac's "CSV (Macintosh)") put in the codebooks folder makes
    `frameworks.available` raise `_csv.Error`, which is not a ValueError: every page that lists codebooks answers
    500 (frameworks.py:268 `parse_csv`, frameworks.py:323 `_load_file` catches only ValueError and OSError)."""
    folder = ws.root / "frameworks"
    folder.mkdir(exist_ok=True)
    (folder / "mac.csv").write_bytes(b"code,description\rA,Alpha things\rB,Beta things\r")
    got = frameworks.available(ws)
    assert "sdg" in got
    assert "mac" in got or any(p["file"] == "mac.csv" for p in frameworks.problems(ws))


def _fresh(ws, name, where, desc):
    cb = codebooks.create(ws, name, "X", where, "fresh")
    st = json.loads(json.dumps(cb))
    st["codes"] = [{"code": "A", "description": desc, "group": "", "keywords": [], "include": "", "exclude": "",
                    "examples": []}]
    codebooks.save(ws, name, st)


def test_moving_a_codebook_keeps_its_versions_when_the_other_place_has_old_ones_of_that_name(tmp_path):
    """A codebook kept with all projects is removed (its versions stay in `history/x`) while a project's own copy of it
    lives on; that copy is moved there: `shutil.move` puts its whole history folder INSIDE the existing one
    (`history/x/x/`), and its versions are gone from its history (codebooks.py:1081 `move`).

    (Fix round: the route is a project's own copy made earlier, as the verdict names it: a NEW project codebook under
    a removed one's name is refused since CONCEPTS-1.)"""
    a, b = Workspace.create(tmp_path / "a"), Workspace.create(tmp_path / "b")
    _fresh(a, "x", "home", "the first one")
    codebooks.copy_here(a, "x")                      # project a's own copy, to change there alone
    st = codebooks.state_of(a, "x")
    st["codes"][0]["description"] = "the first one, reworded in a"
    codebooks.save(a, "x", st)
    st["codes"][0]["description"] = "the first one, reworded again in a"
    codebooks.save(a, "x", st)
    mine = {p.stem for p in (a.root / "frameworks" / "history" / "x").glob("c*.json")}
    assert len(mine) == 2
    codebooks.remove(b, "x")                         # removed from all projects, in project b: its versions stay
    codebooks.move(a, "x", "home")
    assert mine <= {p.stem for p in codebooks._version_files(a, "x")}


def test_moving_a_codebook_into_a_project_keeps_its_versions_when_the_project_has_old_ones_of_that_name(ws):
    """The other way (sibling of CONCEPTS-3): a project's own copy is removed (its versions stay in the project's
    `history/y`); the codebook kept with all projects is then moved into that project: its versions went one folder
    down too."""
    _fresh(ws, "y", "home", "for all projects")
    codebooks.copy_here(ws, "y")
    st = codebooks.state_of(ws, "y")
    st["codes"][0]["description"] = "this project's own wording"
    codebooks.save(ws, "y", st)
    codebooks.remove(ws, "y")                        # the project's own copy goes; the one for all projects stays
    assert codebooks.locate(ws, "y")[0] == "home"
    st = codebooks.state_of(ws, "y")
    st["codes"][0]["description"] = "for all projects, reworded"
    codebooks.save(ws, "y", st)
    mine = {p.stem for p in (codebooks._home_folder() / "history" / "y").glob("c*.json")}
    assert mine
    codebooks.move(ws, "y", "project")
    assert mine <= {p.stem for p in codebooks._version_files(ws, "y")}


def test_versions_moved_one_folder_down_before_the_fix_are_found_and_restored_where_they_belong(ws):
    """Data on disk (CONCEPTS-3): a history moved by the earlier `move` lies in `history/<name>/<name>/`: it is listed
    again, and restoring a removed codebook from such a version writes it beside its history, not inside it."""
    _fresh(ws, "z", "project", "kept one folder down")
    d = ws.root / "frameworks" / "history" / "z"
    codebooks.remove(ws, "z")
    nested = d / "z"
    nested.mkdir()
    for p in list(d.glob("c*.json")):
        p.rename(nested / p.name)
    got = codebooks._versions(ws, "z")
    assert got
    from enlens_claims import history

    history.restore(ws, "codebook", "z", got[0]["version_id"])
    assert (ws.root / "frameworks" / "z.csv").is_file() and codebooks.locate(ws, "z")[0] == "project"


# ---- rule 1: a rename while the AI's label tasks wait in the queue ---------------------------------------------------
def test_an_answer_with_the_code_name_it_was_asked_with_lands_on_the_renamed_code(demo):
    """A label task holds the codebook's code names as they were when it was made (a queue for Claude Code can wait
    hours). The person renames a code meanwhile; the AI answers with the name it was shown, and the answer is refused
    as an unknown code: the passage is never labelled, and the task's payload is never brought up to date
    (profile.py:375 `store_labels`, profile.py:354 `make_label_tasks` keeps a task as it was made)."""
    from enlens_claims import tasks

    _codebook(demo)
    pid, text = demo.query("SELECT passage_id, text FROM passages WHERE section='body' AND text LIKE '%commut%' "
                           "ORDER BY passage_id LIMIT 1")[0]
    profile.make_label_tasks(demo, "remote", [pid], "m", all_passages=True)
    payload = json.loads(demo.scalar("SELECT payload_json FROM tasks WHERE task_id=?", (f"label:remote:{pid}",)))
    assert "Commuting" in [c["code"] for c in payload["candidates"]]
    st = codebooks.state_of(demo, "remote")
    st["codes"][0]["code"] = "Travel"
    codebooks.save(demo, "remote", st)
    quote = " ".join(text.split()[:6])
    ok, errs = tasks.ingest_result(demo, f"label:remote:{pid}", {"labels": [
        {"code": "Commuting", "relevance": "main", "confidence": 0.9, "quote": quote, "reason": "travel to work"}]},
        model="m")
    assert ok, errs
    assert demo.query("SELECT code FROM labels WHERE framework='remote' AND passage_id=? AND source='model'",
                      (pid,))[0][0] == "Travel"


# ---- rule 2: "Label again" after a code's wording changed reads every passage it names ---------------------------------
def test_labelling_again_after_a_reword_reads_the_passages_the_ai_labelled_without_a_keyword_candidate(demo):
    """The AI read every passage (*all passages*) and labelled one the keyword pass had no candidate for. The code's
    wording changes; *Label again* takes back that passage's task (`relabel_passages`) but starts the run without
    `all_passages`, so `label_plan` keeps only passages with keyword candidates: the passage is never read again, its
    task is gone, and the code stays marked as labelled with its earlier wording (gui/api_record.py:245,
    profile.py:307 `label_plan`, codebooks.py:1364 `relabel_passages`)."""
    _codebook(demo)
    profile.keyword_pass(demo, "remote")
    pid = demo.scalar("SELECT passage_id FROM passages WHERE section='body' AND passage_id NOT IN (SELECT passage_id "
                      "FROM labels WHERE framework='remote') ORDER BY passage_id LIMIT 1")
    assert pid
    _ai_labelled(demo, "remote", [pid], "Wellbeing")
    st = codebooks.state_of(demo, "remote")
    st["codes"][1]["description"] = "How workers feel at work and at home: stress, isolation, satisfaction."
    codebooks.save(demo, "remote", st)
    assert codebooks.stale(demo, "remote")["Wellbeing"]["passages"] == 1
    pids = codebooks.relabel_passages(demo, "remote", "Wellbeing")
    assert pids == [pid]
    # (fix round) what the endpoint starts, as `start_labels` starts it: run_labels with `passage_ids` and without
    # `all_passages`; the passage is read, and shown the reworded code with its new wording
    be = _Asked()
    out = profile.run_labels(demo, "remote", be, "m", passage_ids=pids)
    asked = [p for p in be.payloads if p["passage_id"] == pid]
    assert out["read"] == 1 and asked
    assert {"code": "Wellbeing", "description": st["codes"][1]["description"]} in asked[0]["candidates"]
    assert "Wellbeing" not in codebooks.stale(demo, "remote")


class _Asked:
    """A model that answers every label task with no label, and keeps what it was asked."""
    name = "anthropic"

    def __init__(self):
        self.payloads: list[dict] = []

    def complete(self, kind, system, user, model, payload=None):
        self.payloads.append(payload or {})
        return json.dumps({"labels": []})


# ---- rule 5: a theory document is never labelled; *Try it* says what the keyword pass would pick --------------------
def test_try_it_leaves_out_theory_documents_as_the_keyword_pass_does(demo):
    """*Try it* (`try_codes`) promises "the same rules as the Profile page's keyword pass", but counts the passages of
    documents marked as theory, which the keyword pass (and every label) leaves out: a code that only a theory book
    talks about looks well matched in the editor and labels nothing (codebooks.py:1338 `try_codes`, against
    profile.py:211 `keyword_pass`)."""
    from enlens_claims import docrole

    cb = _codebook(demo)
    docs = [r[0] for r in demo.query("SELECT doc_id FROM documents ORDER BY doc_id")]
    docrole.set_role(demo, docs[0], "theory")
    profile.keyword_pass(demo, "remote")
    picked = {r[0]: r[1] for r in demo.query("SELECT code, COUNT(DISTINCT passage_id) FROM labels WHERE "
                                             "framework='remote' GROUP BY code")}
    tried = codebooks.try_codes(demo, cb)["codes"]
    assert {c: v["passages"] for c, v in tried.items() if v["passages"]} == picked
    assert all(x["doc_id"] != docs[0] for v in tried.values() for x in v["examples"])


# ---- rule 8: names that differ only by composed or decomposed accents are one name ---------------------------------
def test_two_codes_whose_names_differ_only_in_how_an_accent_is_written_are_refused(ws):
    """The editor refuses two codes whose names differ only by case ("Two codes are called …"), but takes "Kő" written
    composed (NFC, as typed) and "Kő" written decomposed (NFD, as macOS writes file names and many Mac exports): two
    codes that look the same, whose labels never meet (codebooks.py:381 `_clean_state` compares `code.lower()`)."""
    import unicodedata

    cb = codebooks.create(ws, "hu", "Hungarian", "project", "fresh")
    st = json.loads(json.dumps(cb))
    nfc, nfd = unicodedata.normalize("NFC", "Kő"), unicodedata.normalize("NFD", "Kő")
    assert nfc != nfd and nfc.lower() != nfd.lower()
    st["codes"] = [{"code": nfc, "description": "Stone, as typed.", "group": "", "keywords": [], "include": "",
                    "exclude": "", "examples": []},
                   {"code": nfd, "description": "Stone, from a Mac file.", "group": "", "keywords": [], "include": "",
                    "exclude": "", "examples": []}]
    with pytest.raises(ValueError, match="Two codes are called"):
        codebooks.save(ws, "hu", st)


# ---- rule 1: a codebook kept with all projects, renamed in one project, seen from another ---------------------------
def test_a_code_renamed_in_one_project_finds_its_passages_in_another_before_its_profile_page_is_opened(tmp_path):
    """A codebook kept with all projects; project B labelled passages with "Commuting"; project A renames the code to
    "Travel". B's labels follow only when B opens the Profile or Codebooks page (`codebooks.follow`); until then every
    other view of B reads `profile.effective`, which drops labels whose code is not in the codebook: Search by code,
    the concept map's code filter, the themes' code grid and the reading view find nothing for "Travel"
    (profile.py:654 `passages_with_code`, profile.py:641 `effective`; follow is called only in api_explore.py:117/175,
    api_record.py:107, mcp_server.py:554, qdpx.py:367)."""
    from enlens_claims import home

    a, b = home.create_project("A"), home.create_project("B")   # (fix round: projects the app can open)
    ingest.ingest(a, [DEMO])
    ingest.ingest(b, [DEMO])
    cb = codebooks.create(a, "remote", "Remote work", "home", "fresh")
    st = json.loads(json.dumps(cb))
    st["codes"] = [dict(c, include="", exclude="", examples=[]) for c in CODES]
    codebooks.save(a, "remote", st)
    pids = [r[0] for r in b.query("SELECT passage_id FROM passages WHERE section='body' AND text LIKE '%commut%' "
                                  "ORDER BY passage_id LIMIT 3")]
    _ai_labelled(b, "remote", pids, "Commuting")
    assert profile.passages_with_code(b, "remote", "Commuting") == set(pids)
    st = codebooks.state_of(a, "remote")
    st["codes"][0]["code"] = "Travel"
    codebooks.save(a, "remote", st)
    b = home.open_project("B")   # (fix round) project B opened again, as the app and the connector open it
    assert profile.passages_with_code(b, "remote", "Travel") == set(pids)


# =====================================================================================================================
# Fix round: siblings of the claims above, each failing before its fix
# =====================================================================================================================
from test_shared_projects import anna_and_ben  # noqa: E402,F401  (fixtures)
from test_codebook_merge import shared_codebook  # noqa: E402,F401  (fixture)


def _removed_after_labelling(ws):
    _codebook(ws)
    pids = [r[0] for r in ws.query("SELECT passage_id FROM passages WHERE section='body' ORDER BY passage_id LIMIT 4")]
    _ai_labelled(ws, "remote", pids, "Commuting")
    codebooks.remove(ws, "remote", why="starting over")
    return pids


QDC = ('<?xml version="1.0" encoding="utf-8"?><CodeBook xmlns="urn:QDA-XML:codebook:1.0" origin="NVivo 14"><Codes>'
       '<Code guid="9b0f6f1c-1d1a-4c55-9b51-1d1a1d1a1d1a" name="A" isCodable="true"><Description>Alpha things'
       '</Description></Code></Codes></CodeBook>')


@pytest.mark.parametrize("start,source", [
    ("copy", {"of": "sdg_goals"}),
    ("csv", {"csv": "code,description\nA,Alpha things\n"}),
    ("qdc", {"qdc": QDC}),
    ("themes", {"codes": [{"code": "A", "description": "Alpha things"}]}),
    ("theory", {"codes": [{"code": "A", "description": "Alpha things"}], "doc_ids": []}),
])
def test_every_way_of_making_a_codebook_refuses_a_removed_ones_name(demo, start, source):
    """CONCEPTS-1, every way a codebook gets a name in *New codebook*: a copy, a CSV file, a REFI-QDA file, the themes,
    a theory document: each took over the removed codebook's labels, read passages and versions."""
    _removed_after_labelling(demo)
    with pytest.raises(ValueError, match="removed codebook called 'remote'"):
        codebooks.create(demo, "remote", "Second try", "project", start, source)


def test_a_codebook_added_from_csv_elsewhere_refuses_a_removed_ones_name(demo):
    """CONCEPTS-1 sibling: `frameworks.save` (the API's POST .../frameworks) wrote a new codebook under the name."""
    _removed_after_labelling(demo)
    with pytest.raises(ValueError, match="removed codebook called 'remote'"):
        frameworks.save(demo, "remote", "code,description\nA,Alpha things\n")


def test_a_codebook_for_all_projects_refuses_a_name_another_project_removed(tmp_path):
    """CONCEPTS-1 sibling: a project codebook removed in project A keeps its versions (and labels) there; a codebook kept
    with all projects made under its name from project B shows in A too, and took them over there."""
    from enlens_claims import home

    a, b = home.create_project("A"), home.create_project("B")
    _fresh(a, "w", "project", "made in A")
    codebooks.remove(a, "w")
    with pytest.raises(ValueError, match="removed codebook called 'w'"):
        codebooks.create(b, "w", "W", "home", "fresh")
    codebooks.create(b, "w", "W", "project", "fresh")   # B's own codebook of the name is B's alone: allowed


def test_a_colleagues_codebook_named_like_one_removed_here_comes_in_beside_it(anna_and_ben):
    """CONCEPTS-1, a team codebook arriving: Ben labelled with his codebook "mycb" and removed it; Anna's own "mycb"
    (never exchanged with his) came in under the name and took over his labels and versions."""
    anna, ben = anna_and_ben
    with ben:
        frameworks.save(ben.ws, "mycb", "code,description\nA,Water use of electrolysis\nB,Jobs\n")
        pid = ben.ws.scalar("SELECT passage_id FROM passages ORDER BY passage_id LIMIT 1")
        profile.add_label(ben.ws, "mycb", pid, "A")
        codebooks.remove(ben.ws, "mycb")
    with anna:
        frameworks.save(anna.ws, "mycb", "code,description\nZ,Something else entirely\n")
    rep = ben.bring_in(anna.send())
    assert [c["of"] for c in rep["codebooks"]["clash"]] == ["mycb"]
    with ben:
        assert "mycb" not in frameworks.available(ben.ws)
        assert [tuple(r) for r in ben.ws.query("SELECT framework, code FROM labels WHERE source='person'")] == \
            [("mycb", "A")]


def test_the_export_of_a_codebook_file_with_old_mac_line_endings_reads_it(ws):
    """CONCEPTS-2 sibling: the codebook's CSV download (`csv_of`, `_protected_csv`) read the file with the csv module
    as the list did, and raised `_csv.Error`; a quoted cell over several lines (the examples) still reads whole."""
    folder = ws.root / "frameworks"
    folder.mkdir(exist_ok=True)
    (folder / "mac.csv").write_bytes(b"code,description\rA,Alpha things\rB,Beta things\r")
    _name, body = codebooks.csv_of(ws, "mac")
    assert body.decode("utf-8").splitlines() == ["code,description", "A,Alpha things", "B,Beta things"]
    codes = frameworks.parse_csv('code,description,examples\r\nA,Alpha,"one\r\ntwo"\r\n', extra=True)
    assert codes["A"].examples == ("one", "two")


def _waiting(demo):
    """A label task made for a passage about commuting, showing Commuting (and the passage's words)."""
    _codebook(demo)
    pid, text = demo.query("SELECT passage_id, text FROM passages WHERE section='body' AND text LIKE '%commut%' "
                           "ORDER BY passage_id LIMIT 1")[0]
    profile.make_label_tasks(demo, "remote", [pid], "m", all_passages=True)
    payload = json.loads(demo.scalar("SELECT payload_json FROM tasks WHERE task_id=?", (f"label:remote:{pid}",)))
    assert "Commuting" in [c["code"] for c in payload["candidates"]]
    return pid, " ".join(text.split()[:6])


def _answer(demo, pid, quote, *codes):
    from enlens_claims import tasks

    return tasks.ingest_result(demo, f"label:remote:{pid}", {"labels": [
        {"code": c, "relevance": "main", "confidence": 0.9, "quote": quote, "reason": "it says so"} for c in codes]},
        model="m")


def test_an_answer_naming_a_code_merged_while_the_task_waited_lands_on_the_code_it_went_into(demo):
    """CONCEPTS-4, a merge while the task waits: the answer was refused (unknown code) and, after three, the task
    failed for good. Now the label goes where the merge took that code's labels: into Wellbeing, marked as merged;
    beside a Wellbeing label of the same answer it stays under its own name, as a merge leaves it."""
    pid, quote = _waiting(demo)
    st = codebooks.state_of(demo, "remote")
    uid = {c["code"]: c["uid"] for c in st["codes"]}
    codebooks.save(demo, "remote", {**st, "codes": [c for c in st["codes"] if c["code"] != "Commuting"]},
                   merges=[{"from": uid["Commuting"], "into": uid["Wellbeing"]}])
    ok, errs = _answer(demo, pid, quote, "Commuting")
    assert ok, errs
    assert [tuple(r) for r in demo.query("SELECT code, merged_from FROM labels WHERE passage_id=? AND source='model'",
                                         (pid,))] == [("Wellbeing", "Commuting")]
    ok, errs = _answer(demo, pid, quote, "Commuting", "Wellbeing")
    assert ok, errs
    assert sorted(tuple(r) for r in demo.query("SELECT code, merged_from FROM labels WHERE passage_id=? AND "
                                               "source='model'", (pid,))) == [("Commuting", "Commuting"),
                                                                             ("Wellbeing", None)]


def test_an_answer_naming_a_code_removed_while_the_task_waited_keeps_its_other_labels(demo):
    """CONCEPTS-4, a code removed while the task waits: the whole answer was refused, the passage's other codes with
    it, and the task failed for good. Now the removed code's label waits under Removed codes, as its other labels do,
    and the other codes are stored."""
    pid, quote = _waiting(demo)
    st = codebooks.state_of(demo, "remote")
    codebooks.save(demo, "remote", {**st, "codes": [c for c in st["codes"] if c["code"] != "Commuting"]})
    ok, errs = _answer(demo, pid, quote, "Commuting", "Wellbeing")
    assert ok, errs
    assert sorted(r[0] for r in demo.query("SELECT code FROM labels WHERE passage_id=? AND source='model'", (pid,))) == \
        ["Commuting", "Wellbeing"]
    assert [r["code"] for r in codebooks.removed_codes(demo, "remote")] == ["Commuting"]


def test_a_task_that_failed_on_a_code_the_codebook_did_not_know_is_asked_again_by_the_next_run(demo):
    """CONCEPTS-4, tasks that failed before the fix (or while their codebook was removed): a failed task was never
    asked again by a later run (`_insert_task` leaves it, `run_one` stops on it), so the passage was never labelled.
    Now the next run gives it the codebook as it is and asks again."""
    from enlens_claims import history

    pid, quote = _waiting(demo)
    for _ in range(3):
        _answer(demo, pid, quote, "Commuting by train")   # refused: a code the codebook does not know
    tid = f"label:remote:{pid}"
    assert demo.scalar("SELECT status FROM tasks WHERE task_id=?", (tid,)) == "failed"
    profile.make_label_tasks(demo, "remote", [pid], "m", all_passages=True)
    assert demo.scalar("SELECT status || '/' || attempts FROM tasks WHERE task_id=?", (tid,)) == "pending/0"
    # the codebook removed while the task waits: (hunt phase 1.5) the waiting task is taken back at the removal, no
    # longer answered and refused three times; brought back from History, the next run asks it again
    codebooks.remove(demo, "remote")
    assert demo.scalar("SELECT status FROM tasks WHERE task_id=?", (tid,)) is None
    history.restore(demo, "codebook", "remote", codebooks._versions(demo, "remote")[0]["version_id"])
    profile.make_label_tasks(demo, "remote", [pid], "m", all_passages=True)
    assert demo.scalar("SELECT status FROM tasks WHERE task_id=?", (tid,)) == "pending"
    ok, errs = _answer(demo, pid, quote, "Commuting")
    assert ok, errs


def test_an_answer_to_a_task_asked_before_a_reword_is_marked_as_made_with_the_earlier_wording(demo):
    """CONCEPTS-4, a code reworded while the task waits: the AI read the earlier wording (its task holds it), but its
    label was made after the change, so the code was never marked *labelled with an earlier wording* and *Label them
    again* could not reach it (`stale` compared the label's time, not the question's)."""
    pid, quote = _waiting(demo)
    with demo.connect() as cx:   # asked a while ago (a queue for Claude Code waits for hours)
        cx.execute("UPDATE tasks SET created_at='2026-01-01T00:00:00+00:00' WHERE task_id=?", (f"label:remote:{pid}",))
    st = codebooks.state_of(demo, "remote")
    st["codes"][0]["description"] = "Any trip between home and work, by any means, and what it costs."
    codebooks.save(demo, "remote", st)
    ok, errs = _answer(demo, pid, quote, "Commuting")
    assert ok, errs
    assert codebooks.stale(demo, "remote").get("Commuting", {}).get("passages") == 1
    assert codebooks.relabel_passages(demo, "remote", "Commuting") == [pid]


def test_the_keyword_pass_made_again_leaves_out_a_document_marked_as_theory_since(demo):
    """CONCEPTS-7 sibling: a document marked as theory after a keyword pass kept that pass's candidates when the pass
    was made again (only the passages read were replaced), so the Profile still counted the theory document, "made
    again without it" as docrole.impact offers. A candidate a person accepted stays: it is theirs."""
    from enlens_claims import docrole

    _codebook(demo)
    profile.keyword_pass(demo, "remote")
    doc = demo.scalar("SELECT doc_id FROM labels WHERE framework='remote' GROUP BY doc_id ORDER BY COUNT(*) DESC LIMIT 1")
    kept = demo.scalar("SELECT label_id FROM labels WHERE framework='remote' AND doc_id=? LIMIT 1", (doc,))
    profile.set_label(demo, kept, "accept")
    docrole.set_role(demo, doc, "theory")
    profile.keyword_pass(demo, "remote")
    assert [r[0] for r in demo.query("SELECT label_id FROM labels WHERE framework='remote' AND doc_id=?", (doc,))] == \
        [kept]


def _code(name, desc="Something.", group=""):
    return {"code": name, "description": desc, "group": group, "keywords": [], "include": "", "exclude": "",
            "examples": []}


def test_names_written_with_composed_or_decomposed_accents_are_one_name_everywhere_they_meet(ws, tmp_path):
    """CONCEPTS-8 siblings: a group in the editor, a CSV and a .qdc import, the AI's answer (`Framework.normalise`), and
    a code taking the name of one removed in the same change: each compared names as written, so "Kő" composed and
    "Kő" decomposed were two names there. Each name is kept as written."""
    import unicodedata

    from enlens_claims import qdc_import

    nfc, nfd = unicodedata.normalize("NFC", "Kő"), unicodedata.normalize("NFD", "Kő")
    cb = codebooks.create(ws, "hu", "Hungarian", "project", "fresh")
    st = json.loads(json.dumps(cb))
    st["codes"] = [_code("A", group=nfc), _code("B", group=nfd)]
    codebooks.save(ws, "hu", st)
    got = codebooks.state_of(ws, "hu")
    assert [g["group"] for g in got["groups"]] == [nfc] and {c["group"] for c in got["codes"]} == {nfc}
    assert frameworks.get("hu", ws).normalise(unicodedata.normalize("NFD", "a")) == "A"
    st = codebooks.state_of(ws, "hu")
    st["codes"] = [dict(st["codes"][0], code=nfc)]
    codebooks.save(ws, "hu", st)
    st = codebooks.state_of(ws, "hu")
    assert frameworks.get("hu", ws).normalise(nfd) == nfc
    with pytest.raises(ValueError, match="remove or merge in this same change"):
        codebooks.save(ws, "hu", {**st, "codes": [_code(nfd)]})
    with pytest.raises(ValueError, match="Two codes are called"):
        codebooks.create(ws, "hu2", "", "project", "csv", {"csv": f"code,description\n{nfc},Typed\n{nfd},From a Mac\n"})
    xml = QDC.replace('name="A"', f'name="{nfc}"').replace(
        "</Codes>", f'<Code guid="9b0f6f1c-1d1a-4c55-9b51-1d1a1d1a1d1b" name="{nfd}" isCodable="true">'
                    '<Description>From a Mac</Description></Code></Codes>')
    got = codebooks.create(ws, "hu3", "", "project", "qdc", {"qdc": xml})
    assert sorted(c["code"] for c in got["codes"]) == sorted([nfc, f"{nfd} (2)"])
    assert qdc_import  # (the import names the second one apart, as it does for "kő" and "Kő")


def test_a_codebook_name_never_differs_from_another_only_by_case_or_accent_form(ws):
    """CONCEPTS-8, a codebook's NAME (it becomes a file name, and macOS and Windows take "Remote.csv" and "remote.csv",
    or a composed and a decomposed "ő", for one file): every way a name is given folds it to lower-case ASCII
    (`NAME_RE`), so two names that differ only so are one name and the second is refused. Case held before the fix;
    an accent did not: typed (composed) "kőzet" became "kzet", decomposed it became "kozet", two codebooks."""
    import unicodedata

    codebooks.create(ws, "remote", "Remote work", "project", "fresh")
    for other in ("Remote", "REMOTE", " remote "):
        with pytest.raises(ValueError, match="exists already"):
            codebooks.create(ws, other, "", "project", "fresh")
    a = codebooks.create(ws, unicodedata.normalize("NFC", "kőzet"), "", "project", "fresh")["name"]
    with pytest.raises(ValueError, match="exists already"):
        codebooks.create(ws, unicodedata.normalize("NFD", "kőzet"), "", "project", "fresh")
    assert frameworks.NAME_RE.match(a)


def test_a_colleagues_new_code_named_like_mine_but_for_its_accent_form_comes_in_under_a_name_of_its_own(
        shared_codebook):
    """CONCEPTS-8, the merge of a codebook both changed (sync/codebook_merge.py): a code each added under one name took
    a name of its own only when the names were equal ignoring case; "Kő" composed and decomposed stayed two codes that
    look the same."""
    import unicodedata

    from test_codebook_merge import _edit

    anna, ben = shared_codebook
    nfc, nfd = unicodedata.normalize("NFC", "Kő"), unicodedata.normalize("NFD", "Kő")
    with anna:
        _edit(anna.ws, "water", lambda codes: codes.append(_code(nfd, "Stone, from Anna's Mac")))
    with ben:
        _edit(ben.ws, "water", lambda codes: codes.append(_code(nfc, "Stone, as Ben typed it")))
    ben.bring_in(anna.send())
    with ben:
        names = [c.code for c in frameworks.get("water", ben.ws).codes.values()]
        assert len({frameworks.name_key(n) for n in names}) == len(names), names


# =====================================================================================================================
# After review (reviews/reading.md): CONCEPTS-4 by the changes a task knows, not by the clock; CONCEPTS-1 and a live
# codebook elsewhere; CONCEPTS-8 without casefold; a clash copy's name within 40 characters
# =====================================================================================================================
def test_a_task_made_in_the_same_second_as_a_rename_chain_reads_its_answer_as_the_codebook_it_showed(demo, monkeypatch):
    """Review, must fix: one save renames Commuting to Travel and gives Wellbeing the name Commuting; a task made in that
    second shows the codebook after the save. Its answer "Commuting" means the former Wellbeing, and was stored under
    Travel (the save's events counted as "since" by their time, to the second)."""
    from enlens_claims import store, tasks

    fixed = "2026-11-19T10:00:05+00:00"
    for mod in (store, codebooks, profile, tasks):
        monkeypatch.setattr(mod, "now", lambda: fixed, raising=False)
    _codebook(demo)
    st = codebooks.state_of(demo, "remote")
    st["codes"][0]["code"], st["codes"][1]["code"] = "Travel", "Commuting"
    codebooks.save(demo, "remote", st)
    pid, text = demo.query("SELECT passage_id, text FROM passages WHERE section='body' AND text LIKE '%commut%' "
                           "ORDER BY passage_id LIMIT 1")[0]
    profile.make_label_tasks(demo, "remote", [pid], "m", all_passages=True)
    payload = json.loads(demo.scalar("SELECT payload_json FROM tasks WHERE task_id=?", (f"label:remote:{pid}",)))
    if "Commuting" not in [c["code"] for c in payload["candidates"]]:
        payload["candidates"].append({"code": "Commuting", "description": "How workers feel."})
        with demo.connect() as cx:
            cx.execute("UPDATE tasks SET payload_json=? WHERE task_id=?", (json.dumps(payload), f"label:remote:{pid}"))
    ok, errs = _answer(demo, pid, " ".join(text.split()[:6]), "Commuting")
    assert ok, errs
    assert [r[0] for r in demo.query("SELECT code FROM labels WHERE passage_id=? AND source='model'", (pid,))] == \
        ["Commuting"]


def test_a_colleagues_rename_dated_before_the_task_but_unknown_to_it_still_maps_the_answer(demo):
    """Review: a colleague's events keep their own computer's time; one dated before the task was made but arriving
    after it is a change the task never showed, and its answer follows it."""
    pid, quote = _waiting(demo)
    st = codebooks.state_of(demo, "remote")
    st["codes"][0]["code"] = "Travel"
    codebooks.save(demo, "remote", st)
    side = demo.root / "frameworks" / "remote.json"
    meta = json.loads(side.read_text(encoding="utf-8"))
    for e in meta["events"]:
        e["at"] = "2020-01-01T00:00:00+00:00"   # their clock: long before the task
    side.write_text(json.dumps(meta), encoding="utf-8")
    ok, errs = _answer(demo, pid, quote, "Commuting")
    assert ok, errs
    assert [r[0] for r in demo.query("SELECT code FROM labels WHERE passage_id=? AND source='model'", (pid,))] == \
        ["Travel"]


def test_a_task_made_before_the_fix_is_mapped_only_by_later_changes_and_never_guessed(demo):
    """Review: a task without the record of the changes it knows (made before this fix) maps an answer only through
    changes dated strictly after it, and refuses it, as before, when the name is a code's name now as well."""
    pid, quote = _waiting(demo)
    tid = f"label:remote:{pid}"
    payload = json.loads(demo.scalar("SELECT payload_json FROM tasks WHERE task_id=?", (tid,)))
    payload.pop("codebook_events")
    with demo.connect() as cx:
        cx.execute("UPDATE tasks SET payload_json=?, created_at='2026-01-01T00:00:00+00:00' WHERE task_id=?",
                   (json.dumps(payload), tid))
    st = codebooks.state_of(demo, "remote")
    st["codes"][0]["code"] = "Travel"
    codebooks.save(demo, "remote", st)
    ok, errs = _answer(demo, pid, quote, "Commuting")
    assert ok, errs
    assert [r[0] for r in demo.query("SELECT code FROM labels WHERE passage_id=? AND source='model'", (pid,))] == \
        ["Travel"]
    st = codebooks.state_of(demo, "remote")
    st["codes"][1]["code"] = "Commuting"           # Wellbeing now takes the old name
    codebooks.save(demo, "remote", st)
    ok, errs = _answer(demo, pid, quote, "Commuting")
    assert not ok and "renamed or merged since this task was made" in errs[0]


def test_a_live_codebook_of_another_project_does_not_hold_the_name_and_an_unreadable_project_is_passed_over(
        tmp_path, monkeypatch):
    """Review, should fix: project A's own live codebook "interviews" has versions; B's new "interviews" kept with all
    projects was refused as "removed". A removed one is named with its project; a project that cannot be read is
    passed over."""
    from enlens_claims import home

    a, b = home.create_project("A"), home.create_project("B")
    _fresh(a, "interviews", "project", "A's own")
    assert (a.root / "frameworks" / "history" / "interviews").is_dir()
    codebooks.create(b, "interviews", "Interviews", "home", "fresh")
    _fresh(a, "gone", "project", "A's, removed")
    codebooks.remove(a, "gone")
    with pytest.raises(ValueError, match="in the project 'A'"):
        codebooks.create(b, "gone", "Gone", "home", "fresh")
    real = home.project_path

    def unplugged(name):
        if name == "A":
            raise OSError("the drive is not plugged in")
        return real(name)

    monkeypatch.setattr(home, "project_path", unplugged)
    assert codebooks.create(b, "other", "Other", "home", "fresh")["name"] == "other"


def test_masse_and_masse_with_sharp_s_stay_two_names(ws):
    """Review, should fix: `casefold` made "Maße" and "Masse" one name."""
    cb = codebooks.create(ws, "de", "Deutsch", "project", "fresh")
    st = json.loads(json.dumps(cb))
    st["codes"] = [_code("Masse", "Mass"), _code("Maße", "Dimensions")]
    codebooks.save(ws, "de", st)
    assert sorted(frameworks.get("de", ws).codes) == ["Masse", "Maße"]
    assert frameworks.get("de", ws).normalise("MASSE") == "Masse"


def test_a_codebook_saved_with_two_names_that_now_count_as_one_still_saves_other_changes(ws):
    """Review: a codebook on disk from before the check, with "Kő" composed and decomposed (a CSV of before), opens and
    saves for any other change; adding a code under such a name, or renaming one into it, is refused."""
    import unicodedata

    nfc, nfd = unicodedata.normalize("NFC", "Kő"), unicodedata.normalize("NFD", "Kő")
    folder = ws.root / "frameworks"
    folder.mkdir(exist_ok=True)
    (folder / "old.csv").write_text(f"code,description\n{nfc},Typed\n{nfd},From a Mac\nB,Bee\n", encoding="utf-8")
    st = codebooks.load(ws, "old")
    assert len(st["codes"]) == 3
    st["codes"][-1]["description"] = "A bee, reworded"
    codebooks.save(ws, "old", st)
    st = codebooks.state_of(ws, "old")
    assert sorted(c["code"] for c in st["codes"]) == sorted([nfc, nfd, "B"])
    with pytest.raises(ValueError, match="Two codes are called"):
        codebooks.save(ws, "old", {**st, "codes": st["codes"] + [_code(nfc.lower())]})
    renamed = [dict(c, code=nfc.lower()) if c["code"] == "B" else c for c in st["codes"]]
    with pytest.raises(ValueError, match="Two codes are called"):
        codebooks.save(ws, "old", {**st, "codes": renamed})


def test_a_colleagues_version_of_a_codebook_with_a_long_name_comes_in_listed(anna_and_ben):
    """Notes: the clash copy "<name>-<6 characters>" of a codebook named with 35 characters or more went past the 40 a
    name may have, came in as files and was never listed."""
    anna, ben = anna_and_ben
    long = "a" * 38
    with anna:
        frameworks.save(anna.ws, long, "code,description\nA,Water use of electrolysis\n")
    with ben:
        frameworks.save(ben.ws, long, "code,description\nA,Water\n")
    rep = ben.bring_in(anna.send())
    copy = rep["codebooks"]["clash"][0]["name"]
    assert len(copy) <= 40
    with ben:
        assert copy in frameworks.available(ben.ws)
    from enlens_claims.sync.codebook_merge import clash_name

    assert len(clash_name("b" * 40, "0123456789")) == 40
