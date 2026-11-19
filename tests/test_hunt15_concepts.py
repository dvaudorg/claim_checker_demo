"""Hunt phase 1.5, area `concepts`: every possible bug and note of phases 0 and 1 about codebooks, labels, themes, the
glossary and the concept map, each settled by a test (FIX15.md). A test asserts what ENLENS should do.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from enlens_claims import claimcheck, codebooks, frameworks, ingest, profile, sharing
from enlens_claims.llm import BaselineBackend
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


def _codebook(ws, name="remote", codes=CODES, where="project"):
    cb = codebooks.create(ws, name, "Remote work", where, "fresh")
    st = json.loads(json.dumps(cb))
    st["codes"] = [dict(c, include="", exclude="", examples=[]) for c in codes]
    codebooks.save(ws, name, st)
    return codebooks.load(ws, name)


def _model_label(ws, fw, pid, code):
    lid = profile.label_id(fw, pid, code, "model")
    with ws.connect() as cx:
        cx.execute("INSERT INTO labels(label_id, passage_id, doc_id, framework, code, source, relevance, confidence, "
                   "created_at) VALUES (?,?,?,?,?,'model','main',0.9,?)",
                   (lid, pid, pid.split(":")[0], fw, code, "2026-01-01T00:00:00+00:00"))
    return lid


def _pid(ws, n=0):
    return ws.query("SELECT passage_id FROM passages WHERE section='body' ORDER BY passage_id LIMIT 1 OFFSET ?",
                    (n,))[0][0]


def _merge(ws, name, src, dst):
    st = codebooks.state_of(ws, name)
    uid = {c["code"]: c["uid"] for c in st["codes"]}
    return codebooks.save(ws, name, {**st, "codes": [c for c in st["codes"] if c["code"] != src]},
                          merges=[{"from": uid[src], "into": uid[dst]}])


# ---- item 2 (owner): a merge keeps the person's own decision ---------------------------------------------------------
@pytest.mark.parametrize("on_a,on_b,counts", [
    ("accept", "reject", True),    # the owner's case: A applies, so after the merge B applies
    ("accept", "accept", True),
    ("reject", "accept", True),    # A's rejection was about A: B was accepted
    ("reject", "reject", False),   # neither applies
])
def test_merging_a_code_keeps_the_persons_own_decision_on_the_passage(demo, on_a, on_b, counts):
    """INVENTORY concepts 2 (owner; notes/concepts.md "Not proven" 2): a passage has the AI's labels A and B; the
    person accepted one and rejected the other. Merging A into B left A's label waiting (merged) and B's counting
    as decided, so an accepted A and a rejected B left the passage with no code. The positive decision wins, and
    the codebook's History entry (its research log line) says so."""
    _codebook(demo)
    pid = _pid(demo)
    a = _model_label(demo, "remote", pid, "Commuting")
    b = _model_label(demo, "remote", pid, "Wellbeing")
    profile.set_label(demo, a, on_a)
    profile.set_label(demo, b, on_b)
    out = _merge(demo, "remote", "Commuting", "Wellbeing")
    got = [(r["code"], r["decision"]) for r in profile.effective(demo, "remote", passage_ids=[pid])]
    assert got == ([("Wellbeing", "accept")] if counts else [])
    said = " ".join(out["changes"])
    if (on_a, on_b) == ("accept", "reject"):
        assert "accepted" in said and "Commuting" in said
    else:
        assert "accepted" not in said
    # restoring the codebook from before the merge gives every decision back as it was
    vid = out["version_id"]
    codebooks._restore(demo, "remote", vid)
    back = {r["code"]: r["decision"] for r in profile.effective(demo, "remote", passage_ids=[pid])}
    want = {c: d for c, d in (("Commuting", on_a), ("Wellbeing", on_b)) if d == "accept"}
    assert back == want


def test_merging_a_keyword_label_the_person_accepted_keeps_the_code_on_a_passage_the_ai_has_read(demo):
    """Item 2, sibling: the keyword pass gave the passage A and B; the person accepted A; the AI has read the passage
    since (so an undecided keyword label no longer counts). After merging A into B, the passage had no code."""
    _codebook(demo)
    pid = _pid(demo)
    with demo.connect() as cx:
        for code in ("Commuting", "Wellbeing"):
            cx.execute("INSERT INTO labels(label_id, passage_id, doc_id, framework, code, source, confidence, "
                       "created_at) VALUES (?,?,?,?,?,'keywords',0.9,?)",
                       (profile.label_id("remote", pid, code, "keywords"), pid, pid.split(":")[0], "remote", code,
                        "2026-01-01T00:00:00+00:00"))
        cx.execute("INSERT INTO tasks(task_id, kind, status, payload_json) VALUES (?, 'label', 'done', '{}')",
                   (f"label:remote:{pid}",))
    profile.set_label(demo, profile.label_id("remote", pid, "Commuting", "keywords"), "accept")
    assert [r["code"] for r in profile.effective(demo, "remote", passage_ids=[pid])] == ["Commuting"]
    _merge(demo, "remote", "Commuting", "Wellbeing")
    assert [r["code"] for r in profile.effective(demo, "remote", passage_ids=[pid])] == ["Wellbeing"]


# ---- item 1 (phase 0 P1-7): a folder named like a codebook file in a colleague's codebooks ---------------------------
from test_shared_projects import anna_and_ben  # noqa: E402,F401  (fixture)
from test_shared_folder import pair, shared_dir, _round  # noqa: E402,F401  (fixtures)


def _folder_named_csv(ws, name="x"):
    d = Path(ws.root) / "frameworks" / f"{name}.csv"
    d.mkdir(parents=True)
    (d / "read me.txt").write_text("not a codebook", encoding="utf-8")


@pytest.mark.parametrize("here", ["removed", "live"])
def test_a_folder_named_like_a_codebook_in_a_colleagues_zip_does_not_stop_the_merge(anna_and_ben, here):
    """Phase 0 P1-7 (sync/codebook_merge.py near 99): a FOLDER `x.csv` in the colleague's codebooks folder:
    `_codebook_fp` gives None and `clash_name(name, None)` raised TypeError when a codebook `x` was removed here with
    its labels kept (or one lives here that they had seen), so the whole merge failed. A folder is not a codebook:
    passed over, the rest comes in."""
    anna, ben = anna_and_ben
    with anna:
        frameworks.save(anna.ws, "x", "code,description\nA,Water use of electrolysis\n")
        if here == "removed":
            pid = anna.ws.scalar("SELECT passage_id FROM passages ORDER BY passage_id LIMIT 1")
            profile.add_label(anna.ws, "x", pid, "A")
            codebooks.remove(anna.ws, "x")
    if here == "live":   # Ben had Anna's codebook once, then his file of it became a folder
        ben.bring_in(anna.send())
        with ben:
            for ext in ("csv", "json"):
                (Path(ben.ws.root) / "frameworks" / f"x.{ext}").unlink(missing_ok=True)
        ben.bring_in(anna.send())
        with ben:
            for ext in ("csv", "json"):
                (Path(ben.ws.root) / "frameworks" / f"x.{ext}").unlink(missing_ok=True)
    with ben:
        _folder_named_csv(ben.ws)
        hid = claimcheck.check_hypothesis(ben.ws, "Electrolysers create local jobs.", BaselineBackend(), "baseline",
                                          k=2)
    rep = anna.bring_in(ben.send())
    with anna:
        assert anna.ws.scalar("SELECT 1 FROM hypotheses WHERE hyp_id=?", (hid,))
        assert "x" not in rep["codebooks"].get("new", [])
        assert not [c for c in rep["codebooks"].get("clash", []) if c["of"] == "x"]


def test_a_folder_named_like_a_codebook_does_not_stop_a_shared_folder_round(pair):
    """Phase 0 P1-7, the shared folder: a folder `x.csv` in either copy's codebooks folder; rounds still run and the
    shared codebook still arrives."""
    anna, ben = pair
    with anna:
        codebooks.create(anna.ws, "water", "Water", "project", "csv", {"csv": "code,description\nA,Water use\n"})
        _folder_named_csv(anna.ws)
        sharing.share(anna.ws, [{"kind": "codebook", "key": "water"}])
    with ben:
        _folder_named_csv(ben.ws)
    _round(anna)
    _round(ben)
    _round(anna)
    with ben:
        assert "water" in frameworks.available(ben.ws)
        assert "x" not in frameworks.available(ben.ws)


# ---- item 3 (owner) and item 9: the refusal of a name a removed codebook holds says only what exists ---------------
def _fresh(ws, name, where, desc="Alpha things"):
    cb = codebooks.create(ws, name, "X", where, "fresh")
    st = json.loads(json.dumps(cb))
    st["codes"] = [{"code": "A", "description": desc, "group": "", "keywords": [], "include": "", "exclude": "",
                    "examples": []}]
    codebooks.save(ws, name, st)


def test_the_refusal_of_a_removed_codebooks_name_names_the_way_back_the_app_has(demo):
    """INVENTORY concepts 3: the refusal said "Bring it back from History (Restore)", but a removed codebook has no
    page and so no *History* button: the way back is the research log's entry of its removal (*Compare with before*,
    then *Restore*). It must not promise a way to free the name either (there is none yet: docs/ROADMAP.md)."""
    _fresh(demo, "remote", "project")
    codebooks.remove(demo, "remote", why="starting over")
    with pytest.raises(ValueError) as e:
        codebooks.create(demo, "remote", "Again", "project", "fresh")
    said = str(e.value)
    assert "removed codebook called 'remote'" in said
    assert "Research log" in said and "Compare with before" in said and "Restore" in said
    assert "from History" not in said
    # and the way it names is there: the log's entry has the version to restore
    vid = demo.scalar("SELECT version_id FROM research_log WHERE kind='codebook-removed' AND subject_id='remote'")
    assert vid and codebooks._find_version(demo, "remote", vid)


def test_a_name_held_by_a_codebook_removed_in_a_project_since_removed_points_nowhere_that_is_gone(tmp_path):
    """Item 9 (reviews/reading.md note on `name_held`): a codebook kept with all projects, removed in project A; A
    itself removed since. The versions kept with all projects still hold the name in B, and the refusal must not send
    the person to A, nor to a research log entry B does not have."""
    from enlens_claims import home

    a, b = home.create_project("A"), home.create_project("B")
    _fresh(a, "w", "home")
    codebooks.remove(a, "w")
    home.remove_project("A")
    for where in ("project", "home"):
        with pytest.raises(ValueError) as e:
            codebooks.create(b, "w", "W", where, "fresh")
        said = str(e.value)
        assert "removed codebook called 'w'" in said
        assert "'A'" not in said and "Restore" not in said and "Research log" not in said
        assert "choose another name" in said.lower()


def test_a_name_held_in_another_project_says_to_bring_it_back_there(tmp_path):
    """Item 9, the other side: project A still holds its removed codebook "gone"; the refusal in B names A and the way
    back there."""
    from enlens_claims import home

    a, b = home.create_project("A"), home.create_project("B")
    _fresh(a, "gone", "project")
    codebooks.remove(a, "gone")
    with pytest.raises(ValueError) as e:
        codebooks.create(b, "gone", "Gone", "home", "fresh")
    said = str(e.value)
    assert "in the project 'A'" in said and "Research log" in said and "Restore" in said


# ---- item 4: a move to all projects gets the name check ----------------------------------------------------------
def test_keeping_a_codebook_with_all_projects_is_refused_where_another_project_holds_a_removed_one_of_its_name(
        tmp_path):
    """INVENTORY concepts 4: project A removed its own codebook "w" (its labels and versions kept under the name);
    project B's own, live "w" is moved to all projects with *Keep it with all my projects*: it then showed in A and took
    A's removed codebook's labels and versions over. Making a new one there is refused (CONCEPTS-1); the move is too,
    and B's codebook stays where it was."""
    from enlens_claims import home

    a, b = home.create_project("A"), home.create_project("B")
    _fresh(a, "w", "project", "A's, removed")
    codebooks.remove(a, "w")
    _fresh(b, "w", "project", "B's own")
    with pytest.raises(ValueError, match="in the project 'A'"):
        codebooks.move(b, "w", "home")
    assert codebooks.locate(b, "w")[0] == "project"
    assert "w" not in frameworks.available(a)


def test_keeping_a_codebook_with_all_projects_is_allowed_when_no_other_project_holds_the_name(tmp_path):
    """Item 4, control: B's own codebook with its own versions moves to all projects (its own history goes with it)."""
    from enlens_claims import home

    home.create_project("A")
    b = home.create_project("B")
    _fresh(b, "w", "project", "B's own")
    codebooks.move(b, "w", "home")
    assert codebooks.locate(b, "w")[0] == "home"
    codebooks.move(b, "w", "project")
    assert codebooks.locate(b, "w")[0] == "project"


# ---- item 6: "labelled with an earlier wording" by what the task was shown, not by clocks ---------------------------
def _waiting(demo):
    _codebook(demo)
    pid, text = demo.query("SELECT passage_id, text FROM passages WHERE section='body' AND text LIKE '%commut%' "
                           "ORDER BY passage_id LIMIT 1")[0]
    profile.make_label_tasks(demo, "remote", [pid], "m", all_passages=True)
    return pid, " ".join(text.split()[:6])


def _answer(demo, pid, quote, *codes):
    from enlens_claims import tasks

    return tasks.ingest_result(demo, f"label:remote:{pid}", {"labels": [
        {"code": c, "relevance": "main", "confidence": 0.9, "quote": quote, "reason": "it says so"} for c in codes]},
        model="m")


def _reword(demo, code="Commuting", words="Any trip between home and work, by any means, and what it costs."):
    st = codebooks.state_of(demo, "remote")
    next(c for c in st["codes"] if c["code"] == code)["description"] = words
    codebooks.save(demo, "remote", st)


def test_a_reword_in_the_same_second_a_task_was_asked_marks_its_label_as_made_with_the_earlier_wording(
        demo, monkeypatch):
    """INVENTORY concepts 6: `stale` compared the task's time with the reword's, to the second: a reword in the same
    second the task was asked counted as before it, so a label the AI made from the earlier wording was not marked and
    *Label them again* could not reach it."""
    pid, quote = _waiting(demo)
    asked = demo.scalar("SELECT created_at FROM tasks WHERE task_id=?", (f"label:remote:{pid}",))
    monkeypatch.setattr(codebooks, "now", lambda: asked)   # the reword in that same second
    _reword(demo)
    monkeypatch.undo()
    ok, errs = _answer(demo, pid, quote, "Commuting")
    assert ok, errs
    assert codebooks.stale(demo, "remote").get("Commuting", {}).get("passages") == 1
    assert codebooks.relabel_passages(demo, "remote", "Commuting") == [pid]


def test_a_task_asked_after_a_reword_in_the_same_second_is_not_marked_as_made_with_the_earlier_wording(
        demo, monkeypatch):
    """Item 6, the other way: the reword first, then the task, both in one second: the task showed the new wording."""
    _codebook(demo)
    pid, text = demo.query("SELECT passage_id, text FROM passages WHERE section='body' AND text LIKE '%commut%' "
                           "ORDER BY passage_id LIMIT 1")[0]
    from enlens_claims import store

    t = store.now()
    monkeypatch.setattr(codebooks, "now", lambda: t)
    _reword(demo)
    monkeypatch.undo()
    profile.make_label_tasks(demo, "remote", [pid], "m", all_passages=True)
    with demo.connect() as cx:
        cx.execute("UPDATE tasks SET created_at=? WHERE task_id=?", (t, f"label:remote:{pid}"))
    ok, errs = _answer(demo, pid, " ".join(text.split()[:6]), "Commuting")
    assert ok, errs
    assert codebooks.stale(demo, "remote") == {}
    assert codebooks.relabel_passages(demo, "remote", "Commuting") == []


# ---- item 10: a task made before phase 1 (no record of the codebook's changes) ---------------------------------------
def test_a_task_from_before_phase_1_answered_with_a_name_changed_in_its_second_is_refused_then_asked_again(
        demo, monkeypatch):
    """INVENTORY concepts 10 (phase 1 fixer): a task made before `codebook_events` were kept, whose code was renamed in
    the same second it was asked, cannot tell whether it showed the old name or the new: its answer naming the old
    name must be refused (never guessed), and once it has failed it is asked again, as the codebook is now, by the
    next run. It was stored instead as the label of a REMOVED code "Commuting", which no code would ever bring back."""
    from enlens_claims import tasks

    pid, quote = _waiting(demo)
    tid = f"label:remote:{pid}"
    with demo.connect() as cx:   # as made before phase 1
        p = json.loads(cx.execute("SELECT payload_json FROM tasks WHERE task_id=?", (tid,)).fetchone()[0])
        p.pop("codebook_events", None)
        p.pop("codebook_rewords", None)
        cx.execute("UPDATE tasks SET payload_json=? WHERE task_id=?", (json.dumps(p), tid))
    asked = demo.scalar("SELECT created_at FROM tasks WHERE task_id=?", (tid,))
    st = codebooks.state_of(demo, "remote")
    st["codes"][0]["code"] = "Travel"
    monkeypatch.setattr(codebooks, "now", lambda: asked)
    codebooks.save(demo, "remote", st)
    monkeypatch.undo()
    for _ in range(tasks.MAX_ATTEMPTS):
        ok, errs = _answer(demo, pid, quote, "Commuting")
        assert not ok and any("'Commuting'" in e and "cannot say which code" in e for e in errs)
    assert not demo.query("SELECT 1 FROM labels WHERE passage_id=? AND source='model'", (pid,))
    assert demo.scalar("SELECT status FROM tasks WHERE task_id=?", (tid,)) == "failed"
    assert profile.make_label_tasks(demo, "remote", [pid], "m", all_passages=True) == 1
    assert demo.scalar("SELECT status FROM tasks WHERE task_id=?", (tid,)) == "pending"
    p = json.loads(demo.scalar("SELECT payload_json FROM tasks WHERE task_id=?", (tid,)))
    assert "Travel" in [c["code"] for c in p["candidates"]]


# ---- item 5: a codebook removed while its label tasks wait -----------------------------------------------------------
@pytest.mark.parametrize("status", ["pending", "retry", "exported"])
def test_removing_a_codebook_takes_back_its_waiting_label_tasks(demo, status):
    """INVENTORY concepts 5: label tasks waiting for Claude Code when their codebook is removed were still handed out,
    answered, and refused three times each (wasted AI work), then asked again after Restore. They are taken back at
    the removal, and the research log says how many; a task already answered stays (its labels are results)."""
    pid, quote = _waiting(demo)
    done = demo.query("SELECT passage_id FROM passages WHERE section='body' AND passage_id != ? ORDER BY passage_id "
                      "LIMIT 1", (pid,))[0][0]
    profile.make_label_tasks(demo, "remote", [done], "m", all_passages=True)
    with demo.connect() as cx:
        cx.execute("UPDATE tasks SET status=? WHERE task_id=?", (status, f"label:remote:{pid}"))
        cx.execute("UPDATE tasks SET status='done' WHERE task_id=?", (f"label:remote:{done}",))
    codebooks.remove(demo, "remote")
    left = {r[0]: r[1] for r in demo.query("SELECT task_id, status FROM tasks WHERE kind='label'")}
    assert left == {f"label:remote:{done}": "done"}
    entry = demo.scalar("SELECT text FROM research_log WHERE kind='codebook-removed'")
    assert "1 label task" in entry
    # brought back, a run asks the passage again
    vid = demo.scalar("SELECT version_id FROM research_log WHERE kind='codebook-removed'")
    codebooks._restore(demo, "remote", vid)
    assert profile.make_label_tasks(demo, "remote", [pid], "m", all_passages=True) == 1


def test_removing_a_codebook_kept_with_all_projects_takes_back_its_waiting_label_tasks_in_every_project(tmp_path):
    """Item 5, a codebook kept with all projects: removed from A, it is gone from B too, and B's waiting tasks were
    answered and refused there. B's own copy of the name keeps its tasks."""
    from enlens_claims import home

    a, b, c = home.create_project("A"), home.create_project("B"), home.create_project("C")
    for p in (b, c):
        ingest.ingest(p, [DEMO])
    _fresh(a, "w", "home")
    codebooks.copy_here(c, "w")
    for p in (b, c):
        pid = p.query("SELECT passage_id FROM passages WHERE section='body' LIMIT 1")[0][0]
        profile.make_label_tasks(p, "w", [pid], "m", all_passages=True)
    codebooks.remove(a, "w")
    assert b.scalar("SELECT COUNT(*) FROM tasks WHERE kind='label'") == 0
    assert c.scalar("SELECT COUNT(*) FROM tasks WHERE kind='label'") == 1


# ---- item 7: groups whose names differ only by case or by accent form ------------------------------------------------
def _code(code, group="", desc="Some definition."):
    return {"code": code, "description": desc, "group": group, "keywords": [], "include": "", "exclude": "",
            "examples": []}


def test_two_groups_whose_names_differ_only_by_case_stay_two_groups_as_the_editor_shows_them(ws):
    """INVENTORY concepts 7: a save folded a group written "water" into a group "Water" when the groups were not
    listed as they are (a CSV's codes, an older page or an API caller), changing the group of the codes moved without
    a word. The editor shows "Water" and "water" as two groups (its list is keyed by the group as written), so both are
    kept as written. Only an accent written another way (composed or decomposed: they look the same) is one group."""
    import unicodedata

    cb = codebooks.create(ws, "g", "Groups", "project", "fresh")
    st = json.loads(json.dumps(cb))
    nfc, nfd = unicodedata.normalize("NFC", "Kő"), unicodedata.normalize("NFD", "Kő")
    st["codes"] = [_code("A", "Water"), _code("B", "water"), _code("C", nfc), _code("D", nfd)]
    st.pop("groups", None)
    codebooks.save(ws, "g", st)
    got = codebooks.state_of(ws, "g")
    assert {c["code"]: c["group"] for c in got["codes"]} == {"A": "Water", "B": "water", "C": nfc, "D": nfc}
    # the next save from the editor (its groups listed) changes nothing of that
    got["codes"][0]["description"] = "Another definition."
    codebooks.save(ws, "g", got)
    assert {c["code"]: c["group"] for c in codebooks.state_of(ws, "g")["codes"]} == \
        {"A": "Water", "B": "water", "C": nfc, "D": nfc}


def test_a_csv_with_groups_differing_only_by_case_keeps_both_through_a_save(ws):
    """Item 7 through a CSV file: made from it, then saved in the editor."""
    cb = codebooks.create(ws, "h", "", "project", "csv",
                          {"csv": "code,description,group\nA,Alpha,Water\nB,Beta,water\n"})
    assert {c["code"]: c["group"] for c in cb["codes"]} == {"A": "Water", "B": "water"}
    st = codebooks.state_of(ws, "h")
    st["codes"][1]["description"] = "Beta, said again."
    codebooks.save(ws, "h", st)
    assert {c["code"]: c["group"] for c in codebooks.state_of(ws, "h")["codes"]} == {"A": "Water", "B": "water"}


# ---- item 8: the hunter's "Not proven" -------------------------------------------------------------------------------
def test_a_codebook_made_from_a_csv_keeps_the_files_order_and_a_round_trip_keeps_the_editors(ws):
    """notes/concepts.md "Not proven" 4: *New codebook* › *From a CSV file* sorted the codes by name, so a codebook
    downloaded as CSV and brought back in lost the order the person gave it in the editor."""
    cb = codebooks.create(ws, "o", "", "project", "csv",
                          {"csv": "code,description\nZeta,Last letter\nAlpha,First letter\nMu,Middle letter\n"})
    assert [c["code"] for c in cb["codes"]] == ["Zeta", "Alpha", "Mu"]
    st = codebooks.state_of(ws, "o")
    st["codes"] = [st["codes"][2], st["codes"][0], st["codes"][1]]
    codebooks.save(ws, "o", st)
    _name, body = codebooks.csv_of(ws, "o")
    back = codebooks.create(ws, "o2", "", "project", "csv", {"csv": body.decode("utf-8-sig")})
    assert [c["code"] for c in back["codes"]] == ["Mu", "Zeta", "Alpha"]


def test_removing_a_codebook_through_the_api_keeps_a_version_and_says_so_in_the_research_log(demo):
    """notes/concepts.md "Not proven" 7: `frameworks.delete` (DELETE /api/projects/<p>/frameworks/<name>) deleted a
    project codebook with no version kept and no research log entry, unlike the editor's *Remove*: a removal nobody
    could see or undo, its labels left under the name. It now removes as the editor does."""
    _fresh(demo, "apiremoved", "project")
    frameworks.delete(demo, "apiremoved")
    assert "apiremoved" not in frameworks.available(demo)
    vid = demo.scalar("SELECT version_id FROM research_log WHERE kind='codebook-removed' AND subject_id='apiremoved'")
    assert vid
    codebooks._restore(demo, "apiremoved", vid)
    assert "apiremoved" in frameworks.available(demo)
    with pytest.raises(KeyError):
        frameworks.delete(demo, "not_there")


def test_a_themes_size_is_the_same_on_its_own_page_when_a_member_names_a_passage_this_copy_lacks(demo):
    """notes/concepts.md "Not proven" 6: `_members_of_one` (a theme's own page) counted a theme's members without
    joining `passages`, where the whole view joins them: a run whose members name a passage this copy does not hold (a
    colleague's run naming a document of theirs not here) showed one size on the themes page and another on the
    theme's own."""
    from enlens_claims import themes

    run = themes.run(demo, k=3, seed=0, mode="words")
    first = demo.scalar("SELECT theme_id FROM theme_members WHERE run_id=? ORDER BY theme_id LIMIT 1", (run,))
    with demo.connect() as cx:
        cx.execute("INSERT INTO theme_members(run_id, theme_id, passage_id, similarity) VALUES (?,?,?,?)",
                   (run, first, "notheredoc0:0001", 0.5))
    whole = {t["theme_id"]: t["size"] for t in themes.view(demo, run)["themes"]}
    for tid, size in whole.items():
        part = {t["theme_id"]: t["size"] for t in themes.view(demo, run, only=tid)["themes"]}
        assert part == whole


def test_a_theory_concept_whose_definition_is_the_ais_when_to_use_is_marked_as_the_ais_draft(demo):
    """notes/concepts.md "Not proven" 5 (theoryframe.make): a kept concept with no source quote and no meaning (its
    sources removed, its meaning cleared) gets the AI's *when to use it* as its definition, and the definition was not
    marked *AI draft*, so the AI's words read as the person's."""
    from enlens_claims import theoryframe

    doc = demo.scalar("SELECT doc_id FROM documents ORDER BY doc_id LIMIT 1")
    draft = theoryframe.start(demo, "Theory", "fromtheory", "project", [doc])
    ai = {"model": "m", "meaning": "What the AI said it means.", "when_to_use": "When a passage speaks of trust.",
          "when_not": ""}
    draft["concepts"] = [theoryframe._concept("Trust", "ai", True, [], meaning="", when_to_use=ai["when_to_use"],
                                              ai=ai)]
    draft["groups"] = []
    theoryframe._write(demo, draft)
    cb = theoryframe.make(demo)
    code = next(c for c in cb["codes"] if c["code"] == "Trust")
    assert code["description"] == ai["when_to_use"]
    assert (code.get("ai_draft") or {}).get("description") == ai["when_to_use"]


def test_accepting_a_proposed_relation_does_not_accept_another_one_the_pair_gets_later(tmp_path):
    """notes/concepts.md "Not proven" 3 (textrelations.find; terms.links): a person's decision on a proposed link is
    kept by the pair, and the glossary made again may give the pair another relation (the one its sentences state most
    often): the acceptance then confirmed a relation the person never saw. An acceptance holds for the relation
    accepted; the same relation proposed again stays accepted."""
    from enlens_claims import terms
    from test_text_relations import TEXT

    ws = Workspace.create(tmp_path / "p")
    d = tmp_path / "docs"
    d.mkdir()
    (d / "heating.txt").write_text(TEXT, encoding="utf-8")
    (d / "heating2.txt").write_text(TEXT.replace("Heating in cold regions", "Heating in warm regions"), encoding="utf-8")
    ingest.ingest(ws, [d])
    terms.build(ws)
    hp, gb = terms.find_term(ws, "heat pumps"), terms.find_term(ws, "gas boilers")
    a, b = sorted((hp, gb))

    def link():
        return next(x for x in terms.links(ws) if (x["a"], x["b"]) == (a, b) and x["source"] == "pattern")

    first = link()["relation"]
    terms.set_link(ws, a, b, "accept")
    assert link()["confirmed"]
    terms.build(ws)
    assert link()["relation"] == first and link()["confirmed"]
    more = tmp_path / "more"
    more.mkdir()
    (more / "needs.txt").write_text("Needs of heating\n\n" + " ".join(
        ["Heat pumps need gas boilers in winter."] * 2 + ["Heat pumps require gas boilers on cold days."] * 4) + "\n",
        encoding="utf-8")
    ingest.ingest(ws, [more])
    terms.build(ws)
    lk = link()
    assert lk["relation"] != first
    assert not lk["confirmed"] and lk["decision"] is None
    ws.close_all()


def test_a_persons_name_for_a_two_concept_group_stays_when_a_concepts_wording_on_the_map_changes(tmp_path,
                                                                                                monkeypatch):
    """notes/concepts.md "Not proven" 1 (groupnames.match_all, conceptpaths `_Graph.term`): a map node's id is the
    wording that names its concept (the most frequent one). A person names a group of two concepts; later a wording of
    one of them changes (linked as the same as a more frequent wording, or new documents make another wording the most
    frequent): the node's id changes, the name's concept is no longer on the map, and with only one of its two
    concepts left the name went to *names elsewhere* for good."""
    from enlens_claims import conceptmap, groupnames, home as ehome, terms
    from enlens_claims.conceptmap import Filters
    from concept_corpus import write

    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    ehome.save_settings({**ehome.load_settings(), "embed_backend": "off"})
    ws = ehome.create_project("T")
    ingest.ingest(ws, [write(tmp_path / "docs")["solar"].parent])
    terms.build(ws)
    ids = {r["label"]: r["term_id"] for r in ws.query("SELECT term_id, label FROM terms")}
    m = conceptmap.concept_map(ws, Filters(), 30)
    lab = {x["id"]: x["label"] for x in m["nodes"]}
    g = next(g for g in m["groups"] if ids["discuss the budget"] in g["concepts"])
    assert ids["budget for roads"] in g["concepts"] and ids["Members asked"] in g["concepts"]
    two = [ids["discuss the budget"], ids["budget for roads"]]
    groupnames.save(ws, "rename", {"name_id": g["name_id"], "name": "Money for roads", "concepts": two,
                                   "labels": {t: lab[t] for t in two}, "filters": m["filters"], "n": m["n"]})
    named = lambda mm: [x["name"] for x in mm["groups"] if x["name_source"] == "person"]  # noqa: E731
    assert named(conceptmap.concept_map(ws, Filters(), 30)) == ["Money for roads"]
    # "discuss the budget" is the same as the more frequent "Members asked": that concept's node is now the latter's
    terms.set_link(ws, ids["discuss the budget"], ids["Members asked"], "add", relation="same")
    m2 = conceptmap.concept_map(ws, Filters(), 30)
    assert ids["discuss the budget"] not in {x["id"] for x in m2["nodes"]}
    assert named(m2) == ["Money for roads"] and m2["names_elsewhere"] == []
    ws.close_all()


# ---- notes/concepts.md "NEEDS WINDOWS": a codebook file named with capitals ----------------------------------------
def _case_sensitive(monkeypatch):
    """This computer's file system as Linux's: a name differing only by case is another file."""
    import os

    real = Path.is_file

    def is_file(self):
        return real(self) and self.name in os.listdir(self.parent)

    monkeypatch.setattr(Path, "is_file", is_file)


@pytest.mark.parametrize("linux", [False, True])
def test_a_codebook_file_named_with_capitals_opens_in_the_editor_on_every_system(ws, monkeypatch, linux):
    """notes/concepts.md "NEEDS WINDOWS": a file `Mine.csv` put in the codebooks folder lists as "mine" (`_load_file`
    names a codebook by its file's name in lower case), but `codebooks.locate` looked for `mine.csv` exactly: on a
    case-sensitive file system (Linux) the editor answered 404 for a codebook the list showed. It opens, saves and is
    listed once."""
    if linux:
        _case_sensitive(monkeypatch)
    folder = ws.root / "frameworks"
    folder.mkdir(exist_ok=True)
    (folder / "Mine.csv").write_text("code,description\nA,Alpha things\n", encoding="utf-8")
    assert "mine" in frameworks.available(ws)
    st = codebooks.state_of(ws, "mine")
    st["codes"][0]["description"] = "Alpha things, said again."
    codebooks.save(ws, "mine", st)
    assert frameworks.get("mine", ws).codes["A"].description == "Alpha things, said again."
    assert [p.name.lower() for p in folder.glob("*.csv")] == ["mine.csv"]


# ---- reviews/surface.md note: a person's label on words selected mid-word, where the words stand twice --------------
def test_a_label_on_a_selection_that_cuts_a_word_is_placed_where_it_was_selected(tmp_path):
    """reviews/surface.md note (profile.add_label): `notes.find` was said to match whole words only, so a selection
    that cuts a word missed the search near where it was made and fell back to the words' first place in the passage."""
    ws = Workspace.create(tmp_path / "p")
    d = tmp_path / "docs"
    d.mkdir()
    (d / "pumps.txt").write_text("Pumps\n\nIn spring the heat pumps were cheap to run for most households. In winter "
                                 "the heat pumps were cheap to run only with the new tariff.\n", encoding="utf-8")
    ingest.ingest(ws, [d])
    _codebook(ws, "cb", CODES)
    p = ws.query("SELECT passage_id, start, text FROM passages WHERE text LIKE '%winter%' LIMIT 1")[0]
    second = p["text"].index("heat pumps", p["text"].index("winter"))
    lid = profile.add_label(ws, "cb", p["passage_id"], "Commuting", quote="eat pumps were chea",
                            start=p["start"] + second + 1)
    row = ws.query("SELECT start, end, quote FROM labels WHERE label_id=?", (lid,))[0]
    assert row["start"] == p["start"] + second and row["quote"] == "heat pumps were cheap"
    ws.close_all()


# ---- reviews/reading.md note: following a codebook's changes at every opening of a project ---------------------------
def test_opening_a_project_with_nothing_new_to_follow_takes_no_write_lock_and_a_failure_opens_it_all_the_same(
        tmp_path, monkeypatch):
    """reviews/reading.md note on `home.open_project` → `codebooks.follow`: run at every opening, it should take the
    write lock only when a codebook has changes this project has not followed (a sync merge may hold that lock), and a
    failure in it must not stop the project from opening."""
    from enlens_claims import home

    ws = home.create_project("A")
    _fresh(ws, "w", "project")
    st = codebooks.state_of(ws, "w")
    st["codes"][0]["code"] = "B"
    codebooks.save(ws, "w", st)   # a rename: followed here at once
    calls = []
    real = Workspace.connect
    monkeypatch.setattr(Workspace, "connect", lambda self, *a, **k: calls.append(1) or real(self, *a, **k))
    assert codebooks.follow(ws) == 0 and calls == []
    monkeypatch.setattr(codebooks, "follow", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("broken")))
    home._follow_codebooks(ws)   # (what opening does: it swallows the failure)


def test_a_csv_has_no_place_for_a_codebooks_title_so_the_new_codebook_dialog_gives_it(ws):
    """notes/concepts.md "Not proven" 4, its last point: the title, what a code is called and *directional* are not in
    the CSV (a format limit): a codebook made from a CSV takes the title typed in *New codebook*, and the editor sets
    the rest."""
    cb = codebooks.create(ws, "t", "Interviews of 2026", "project", "csv", {"csv": "code,description\nA,Alpha\n"})
    assert cb["title"] == "Interviews of 2026" and cb["label"] == "code"


def test_a_merge_made_in_another_project_keeps_the_persons_decision_here_and_the_log_says_so(tmp_path):
    """Item 2 in another project: a codebook kept with all projects, merged in A; B follows on opening, keeps its
    person's acceptance, and B's research log says so."""
    from enlens_claims import home

    a, b = home.create_project("A"), home.create_project("B")
    ingest.ingest(b, [DEMO])
    _codebook(a, "shared", CODES, where="home")
    pid = _pid(b)
    ca = _model_label(b, "shared", pid, "Commuting")
    cb = _model_label(b, "shared", pid, "Wellbeing")
    profile.set_label(b, ca, "accept")
    profile.set_label(b, cb, "reject")
    _merge(a, "shared", "Commuting", "Wellbeing")
    codebooks.follow(b)
    assert [(r["code"], r["decision"]) for r in profile.effective(b, "shared", passage_ids=[pid])] == \
        [("Wellbeing", "accept")]
    assert b.scalar("SELECT 1 FROM research_log WHERE kind='codebook-changed' AND text LIKE '%accepted as%'")
