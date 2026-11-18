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


def test_moving_a_codebook_keeps_its_versions_when_the_other_place_has_old_ones_of_that_name(ws):
    """A codebook kept with all projects is removed (its versions stay in `history/x`); a project codebook made later
    under the same name is moved there: `shutil.move` puts its whole history folder INSIDE the existing one
    (`history/x/x/`), and its versions are gone from its history (codebooks.py:1081 `move`)."""
    _fresh(ws, "x", "home", "the first one")
    codebooks.remove(ws, "x")
    _fresh(ws, "x", "project", "the second one")
    st = codebooks.state_of(ws, "x")
    st["codes"][0]["description"] = "the second one, reworded"
    codebooks.save(ws, "x", st)
    mine = {p.stem for p in (ws.root / "frameworks" / "history" / "x").glob("c*.json")}
    assert len(mine) == 2
    codebooks.move(ws, "x", "home")
    assert mine <= {p.stem for p in codebooks._version_files(ws, "x")}


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
    # what the endpoint starts: run_labels(ws, "remote", ..., all_passages=False, passage_ids=pids) plans this
    plan = profile.label_plan(demo, "remote", None, False, None, pids)
    assert plan["passage_ids"] == [pid]


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
    a, b = Workspace.create(tmp_path / "a"), Workspace.create(tmp_path / "b")
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
    assert profile.passages_with_code(b, "remote", "Travel") == set(pids)
