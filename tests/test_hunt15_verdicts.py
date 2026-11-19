"""Hunt phase 1.5, area `checks`, item 1: direct tests of `verdicts.py`.

Phase 0's mutation run left 133 mutants of this module with no result (the test process crashed; see
.claude/audits/2026-11-18-phase0/mutation/verdicts-unsettled.txt): `set_aside`, `effective`, `changed_by_person`,
`first_reading`, `stronger_eligible`, `_before_stronger`, `_graded`, `balance`, `who_says_what`, `_queued_open` and
`_status_of_rounds`. Each function is called here directly, on small rows, with each branch and each boundary pinned
by exact values (a key or a word changed, a comparison turned, a number moved, a default dropped, a value replaced by
None: each changes an asserted value or raises). Pure functions: no project, nothing written.
"""
from __future__ import annotations

import json

import pytest

from enlens_claims import verdicts as V
from enlens_claims.verdicts import (GRADES, PERSON, SET_ASIDE, _before_stronger, _graded, _queued_open,
                                    _status_of_rounds, balance, changed_by_person, effective, first_reading,
                                    set_aside, stronger_eligible, who_says_what)


def row(verdict="supports", confidence=0.9, doc="d1", **kw) -> dict:
    return {"verdict": verdict, "confidence": confidence, "doc_id": doc, "model": "claude-opus",
            "user_verdict": None, "passage_id": "p1", **kw}


# ---------------------------------------------------------------------------------------------
# set_aside
# ---------------------------------------------------------------------------------------------
def test_set_aside_with_no_documents_gives_the_rows_back_as_a_new_list():
    vs = (row(), row(doc="d2"))
    got = set_aside(vs, set())
    assert got == [vs[0], vs[1]] and isinstance(got, list)
    assert set_aside(vs, None) == list(vs)


def test_set_aside_turns_a_non_scientific_documents_row_into_one_read_and_not_about_it():
    a, b = row(doc="news", quote="q", user_verdict="refutes"), row(doc="paper")
    got = set_aside([a, b], {"news"})
    assert got[0] == {"verdict": "not_enough_info", "confidence": None, "doc_id": "news", "model": SET_ASIDE,
                      "user_verdict": None, "passage_id": "p1", "quote": "q", "set_aside": True}
    assert got[1] is b
    assert a["verdict"] == "supports" and a["user_verdict"] == "refutes"   # the row given is not changed
    assert SET_ASIDE == "non-scientific"


def test_set_aside_leaves_a_row_that_waits_for_the_person_as_it_is():
    waiting = row(verdict="not_enough_info", confidence=None, doc="news", model=PERSON)
    judged = row(verdict="not_enough_info", confidence=None, doc="news", model=PERSON, user_verdict="supports")
    got = set_aside([waiting, judged], {"news"})
    assert got[0] is waiting
    assert got[1]["set_aside"] is True and got[1]["model"] == SET_ASIDE and got[1]["user_verdict"] is None


# ---------------------------------------------------------------------------------------------
# effective
# ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize("uv", ["supports", "partially_supports", "refutes"])
def test_a_persons_grade_replaces_the_ais_with_full_confidence(uv):
    v = row(verdict="refutes", confidence=0.3, user_verdict=uv)
    got = effective(v)
    assert (got["verdict"], got["confidence"]) == (uv, 1.0)
    assert got is not v and v["verdict"] == "refutes" and v["confidence"] == 0.3


def test_not_about_it_from_a_person_is_no_grade():
    got = effective(row(user_verdict="not_relevant"))
    assert (got["verdict"], got["confidence"]) == ("not_enough_info", None)


def test_a_suggestion_nobody_judged_counts_as_nothing_and_a_judged_one_as_the_persons():
    sugg = row(suggestion_json=json.dumps({"form": "check", "lean": "supports"}))
    assert (effective(sugg)["verdict"], effective(sugg)["confidence"]) == ("not_enough_info", None)
    judged = {**sugg, "user_verdict": "refutes"}
    assert (effective(judged)["verdict"], effective(judged)["confidence"]) == ("refutes", 1.0)
    noted = {**sugg, "user_verdict": "not_relevant"}
    assert (effective(noted)["verdict"], effective(noted)["confidence"]) == ("not_enough_info", None)


def test_a_row_without_a_persons_verdict_is_the_ais():
    for v in (row(), row(user_verdict=""), row(user_verdict="maybe"), row(suggestion_json=None)):
        assert effective(v) == v
    assert effective(row(suggestion_json="")) == row(suggestion_json="")


# ---------------------------------------------------------------------------------------------
# changed_by_person
# ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize("ai, uv, changed", [
    ("supports", "supports", False), ("supports", "refutes", True), ("supports", "partially_supports", True),
    ("partially_supports", "partially_supports", False), ("refutes", "refutes", False),
    ("refutes", "not_relevant", True), ("not_enough_info", "not_relevant", False),
    ("not_enough_info", "supports", True), (None, "not_relevant", False), ("contradicts", "not_relevant", False),
])
def test_a_change_is_a_persons_verdict_other_than_the_ais(ai, uv, changed):
    assert changed_by_person(row(verdict=ai, user_verdict=uv)) is changed


def test_no_verdict_of_the_person_or_no_ai_reading_is_no_change():
    assert changed_by_person(row(verdict="supports", user_verdict=None)) is False
    assert changed_by_person(row(verdict="supports", user_verdict="")) is False
    assert changed_by_person(row(verdict="not_enough_info", model=PERSON, user_verdict="supports")) is False


def test_judging_an_excerpt_the_local_model_only_pointed_at_is_no_change():
    point = json.dumps({"form": "point"})
    assert changed_by_person(row(verdict="not_enough_info", user_verdict="supports", suggestion_json=point)) is False
    check = json.dumps({"form": "check"})
    assert changed_by_person(row(verdict="refutes", user_verdict="supports", suggestion_json=check)) is True
    assert changed_by_person(row(verdict="supports", user_verdict="supports", suggestion_json=check)) is False
    # no form: a check; a reading that is not an object, or not JSON: compared as any row
    assert changed_by_person(row(verdict="refutes", user_verdict="supports", suggestion_json="{}")) is True
    assert changed_by_person(row(verdict="refutes", user_verdict="supports", suggestion_json="[1]")) is True
    assert changed_by_person(row(verdict="refutes", user_verdict="supports", suggestion_json="{not json")) is True
    assert changed_by_person(row(verdict="supports", user_verdict="supports", suggestion_json="[1]")) is False


def test_changed_by_person_leaves_the_row_as_it_is():
    v = row(verdict="supports", user_verdict="refutes", suggestion_json=json.dumps({"form": "check"}))
    before = dict(v)
    assert changed_by_person(v) is True
    assert v == before


# ---------------------------------------------------------------------------------------------
# first_reading
# ---------------------------------------------------------------------------------------------
def test_no_first_reading_without_a_stronger_models_reading():
    assert first_reading(row()) is None
    assert first_reading(row(ai_history_json=None)) is None
    assert first_reading(row(ai_history_json="[]")) is None
    assert first_reading(row(ai_history_json=json.dumps([{"why": "read again", "verdict": "refutes"}]))) is None


def test_the_first_reading_is_the_one_before_the_stronger_model():
    hist = [{"why": "read again", "verdict": "refutes", "confidence": 0.5, "model": "haiku"},
            {"why": "stepped up", "verdict": "partially_supports", "confidence": 0.7, "model": "sonnet",
             "suggestion": None},
            {"why": "stepped up", "verdict": "refutes", "confidence": 0.8, "model": "opus"}]
    v = row(verdict="supports", confidence=0.95, model="opus", user_verdict="refutes", ai_history_json=json.dumps(hist))
    got = first_reading(v)
    assert got == {**v, "verdict": "partially_supports", "confidence": 0.7, "model": "sonnet", "suggestion_json": None}
    assert v["verdict"] == "supports" and v["model"] == "opus"   # the row given is not changed
    assert got["user_verdict"] == "refutes"                      # a person's own judgement is kept


@pytest.mark.parametrize("before", ["not_enough_info", None, "contradicts"])
def test_a_first_reading_that_judged_nothing_has_no_grade(before):
    hist = [{"why": "stepped up", "verdict": before, "confidence": 0.9, "model": "sonnet"}]
    got = first_reading(row(ai_history_json=json.dumps(hist)))
    assert (got["verdict"], got["confidence"], got["model"]) == ("not_enough_info", None, "sonnet")


@pytest.mark.parametrize("grade", GRADES)
def test_a_first_reading_that_graded_keeps_its_grade(grade):
    hist = [{"why": "stepped up", "verdict": grade, "confidence": 0.61}]
    got = first_reading(row(model="opus", ai_history_json=json.dumps(hist)))
    assert (got["verdict"], got["confidence"], got["model"]) == (grade, 0.61, "opus")   # no model said: the row's


def test_a_first_reading_that_was_a_suggestion_stays_one():
    sugg = {"form": "check", "lean": "supports"}
    hist = [{"why": "stepped up", "verdict": "supports", "confidence": 0.9, "model": "qwen", "suggestion": sugg}]
    got = first_reading(row(ai_history_json=json.dumps(hist), suggestion_json=None))
    assert got["suggestion_json"] == sugg
    assert effective(got)["verdict"] == "not_enough_info"


# ---------------------------------------------------------------------------------------------
# stronger_eligible
# ---------------------------------------------------------------------------------------------
def rd(**kw) -> dict:
    return {"status": "done", "task_id": "check:c1", "parts": [], "stepped_up": False, "stronger_waiting": False,
            "waiting": False, **kw}


def test_a_search_a_model_answered_can_be_read_by_a_stronger_one():
    assert stronger_eligible(rd()) is True
    assert stronger_eligible({"status": "done", "task_id": "check:c1"}) is True        # no parts at all
    assert stronger_eligible(rd(parts=None)) is True


@pytest.mark.parametrize("change", [{"status": "failed"}, {"status": "pending"}, {"status": None},
                                    {"stepped_up": True}, {"stronger_waiting": True}, {"waiting": True}])
def test_a_search_not_answered_or_already_stepped_up_cannot(change):
    assert stronger_eligible(rd(**change)) is False


@pytest.mark.parametrize("read_by, ok", [("you", False), ("waiting", False), ("claude", True), ("local", True),
                                         (None, True)])
def test_who_read_the_main_part_decides(read_by, ok):
    parts = [{"task_id": "check:c1:local", "read_by": "you"}, {"task_id": "check:c1", "read_by": read_by}]
    assert stronger_eligible(rd(parts=parts)) is ok


def test_only_the_main_part_decides():
    parts = [{"task_id": "check:c1:person", "read_by": "you"}, {"task_id": "check:c1:local", "read_by": "waiting"}]
    assert stronger_eligible(rd(parts=parts)) is True
    # a part of another round with the main part's id elsewhere is not this round's main part
    assert stronger_eligible(rd(task_id="check:c1:r2", parts=[{"task_id": "check:c1", "read_by": "you"}])) is True
    assert stronger_eligible(rd(task_id="check:c1:r2", parts=[{"task_id": "check:c1:r2", "read_by": "you"}])) is False


# ---------------------------------------------------------------------------------------------
# _before_stronger
# ---------------------------------------------------------------------------------------------
def stepped(verdict, confidence, first_verdict, first_conf, model="opus", first_model="sonnet", **kw):
    return row(verdict=verdict, confidence=confidence, model=model,
               ai_history_json=json.dumps([{"why": "stepped up", "verdict": first_verdict, "confidence": first_conf,
                                            "model": first_model}]), **kw)


def test_nothing_before_a_stronger_model_when_none_read_again():
    assert _before_stronger([]) == (None, {})
    assert _before_stronger([row(), row(verdict="refutes")]) == (None, {})


def test_the_judgements_as_they_were_and_what_the_stronger_model_changed():
    plain = row(verdict="refutes", confidence=0.8, passage_id="p0")
    same = stepped("supports", 0.9, "supports", 0.7, passage_id="p1")
    other = stepped("refutes", 0.9, "supports", 0.6, passage_id="p2", first_model="haiku")
    none_to = stepped("supports", 0.9, "not_enough_info", None, passage_id="p3", model="fable")
    mine = stepped("supports", 0.9, "refutes", 0.9, passage_id="p4", user_verdict="partially_supports")
    vs, info = _before_stronger([plain, same, other, none_to, mine])
    assert info == {"excerpts": 4, "changed": 3, "first_models": ["haiku", "sonnet"], "models": ["fable", "opus"]}
    assert [(v["verdict"], v["confidence"]) for v in vs] == [
        ("refutes", 0.8), ("supports", 0.7), ("supports", 0.6), ("not_enough_info", None),
        ("partially_supports", 1.0)]   # a person's judgement counts either way (effective)


def test_a_change_between_two_readings_that_judged_nothing_is_no_change():
    a = stepped("not_enough_info", None, "contradicts", 0.9, passage_id="p1")
    b = stepped("not_enough_info", 0.2, "not_enough_info", None, passage_id="p2", model=None, first_model=None)
    vs, info = _before_stronger([a, b])
    assert info["changed"] == 0 and info["excerpts"] == 2
    assert info["models"] == ["opus"] and info["first_models"] == ["sonnet"]


# ---------------------------------------------------------------------------------------------
# _graded
# ---------------------------------------------------------------------------------------------
def test_graded_keeps_grades_at_or_above_the_threshold_by_side():
    s, s_low, s_at = row("supports", 0.9), row("supports", 0.59), row("supports", 0.6)
    p, r, n, none = row("partially_supports", 0.6), row("refutes", 0.61), row("not_enough_info", 0.9), \
        row("supports", None)
    assert _graded([s, s_low, s_at, p, r, n, none], 0.6) == ([s, s_at], [p], [r])
    assert _graded([], 0.6) == ([], [], [])
    assert _graded([row("refutes", 0.0)], 0.0) == ([], [], [row("refutes", 0.0)])


# ---------------------------------------------------------------------------------------------
# balance
# ---------------------------------------------------------------------------------------------
def test_balance_of_nothing():
    assert balance([], 0.6) == {"docs_supporting": 0, "docs_partly": 0, "docs_refuting": 0, "docs_both": 0,
                                "docs_counted": 0, "excerpts_uncounted": 0, "lean": None}


def test_balance_counts_each_document_once_per_side_with_its_strongest_grade():
    vs = [row("supports", 0.7, "a"), row("supports", 0.9, "a"), row("partially_supports", 0.8, "a"),
          row("partially_supports", 0.8, "b"), row("refutes", 0.6, "c"), row("refutes", 0.95, "a"),
          row("not_enough_info", 0.99, "d"), row("supports", 0.59, "e"), row("refutes", None, "e"),
          row("not_enough_info", None, "f"), row("not_enough_info", 0.1, "g")]
    got = balance(vs, 0.6)
    # pos: a 0.9 + half of b 0.8 (a's partial is not counted again) = 1.3; neg: a 0.95 + c 0.6 = 1.55
    assert got == {"docs_supporting": 1, "docs_partly": 1, "docs_refuting": 2, "docs_both": 1, "docs_counted": 3,
                   "excerpts_uncounted": 2, "lean": round((1.3 - 1.55) / (1.3 + 1.55), 2)}
    assert got["lean"] == -0.09


def test_balance_at_the_threshold_counts_and_below_it_does_not():
    assert balance([row("supports", 0.6, "a")], 0.6)["docs_supporting"] == 1
    assert balance([row("supports", 0.6, "a")], 0.6)["excerpts_uncounted"] == 0
    below = balance([row("supports", 0.5999, "a")], 0.6)
    assert (below["docs_supporting"], below["excerpts_uncounted"], below["lean"]) == (0, 1, None)


def test_balance_leans_from_minus_one_to_plus_one():
    assert balance([row("supports", 0.8, "a")], 0.6)["lean"] == 1.0
    assert balance([row("refutes", 0.8, "a")], 0.6)["lean"] == -1.0
    assert balance([row("partially_supports", 0.8, "a")], 0.6)["lean"] == 1.0
    # a partial grade weighs half: 0.4 against 0.8
    assert balance([row("partially_supports", 0.8, "a"), row("refutes", 0.8, "b")], 0.6)["lean"] == -0.33
    got = balance([row("partially_supports", 0.8, "a"), row("supports", 0.7, "b")], 0.6)
    assert (got["docs_supporting"], got["docs_partly"], got["docs_counted"], got["lean"]) == (1, 1, 2, 1.0)


def test_balance_takes_a_confidence_given_as_an_integer():
    got = balance([row("supports", 1, "a"), row("refutes", 1, "b")], 0.6)
    assert got["lean"] == 0.0 and got["docs_both"] == 0 and got["docs_counted"] == 2


# ---------------------------------------------------------------------------------------------
# who_says_what
# ---------------------------------------------------------------------------------------------
def item(doc, verdict, counted=True, location="page 1", title=None):
    return {"doc_id": doc, "title": title or doc.upper(), "verdict": verdict, "counted": counted, "location": location}


def test_who_says_what_lists_only_counted_grades():
    assert who_says_what([]) == []
    assert who_says_what([item("a", "supports", counted=False), item("b", "not_enough_info"),
                          item("c", None), {"doc_id": "d", "title": "D", "verdict": "supports"}]) == []


def test_a_document_supporting_and_partly_supporting_is_listed_as_supporting():
    got = who_says_what([item("a", "partially_supports", location="page 2"), item("a", "supports", location="page 1")])
    assert got == [{"doc_id": "a", "title": "A", "side": "supports", "excerpts": 1, "locations": ["page 1"],
                    "both_sides": False}]


def test_a_document_on_both_sides_is_listed_on_both():
    got = who_says_what([item("a", "supports"), item("a", "refutes", location="page 4")])
    assert got == [{"doc_id": "a", "title": "A", "side": "supports", "excerpts": 1, "locations": ["page 1"],
                    "both_sides": True},
                   {"doc_id": "a", "title": "A", "side": "refutes", "excerpts": 1, "locations": ["page 4"],
                    "both_sides": True}]
    got = who_says_what([item("b", "partially_supports"), item("b", "refutes")])
    assert [(e["side"], e["both_sides"]) for e in got] == [("partly", True), ("refutes", True)]
    only = who_says_what([item("c", "refutes"), item("c", "refutes", location="page 1")])
    assert only == [{"doc_id": "c", "title": "C", "side": "refutes", "excerpts": 2, "locations": ["page 1"],
                     "both_sides": False}]


def test_locations_are_listed_once_in_order_and_empty_ones_are_left_out():
    got = who_says_what([item("a", "supports", location="page 3"), item("a", "supports", location=None),
                         item("a", "supports", location=""), item("a", "supports", location="page 1"),
                         item("a", "supports", location="page 3")])
    assert got[0]["excerpts"] == 5 and got[0]["locations"] == ["page 3", "page 1"]


def test_who_says_what_is_ordered_by_side_then_most_excerpts_then_title():
    got = who_says_what([item("r", "refutes", title="Alpha"), item("p", "partially_supports", title="Alpha"),
                         item("s1", "supports", title="Zeta"), item("s2", "supports", title="Beta"),
                         item("s3", "supports", title="Omega"), item("s3", "supports", title="Omega")])
    assert [(e["side"], e["title"]) for e in got] == [("supports", "Omega"), ("supports", "Beta"),
                                                      ("supports", "Zeta"), ("partly", "Alpha"),
                                                      ("refutes", "Alpha")]


# ---------------------------------------------------------------------------------------------
# _queued_open
# ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize("queued, status, ok", [(1, "pending", True), (1, "retry", True), (1, "done", False),
                                                (1, "failed", False), (0, "pending", False), (None, "retry", False),
                                                (True, "pending", True)])
def test_a_round_waits_in_the_queue_when_queued_and_open(queued, status, ok):
    assert _queued_open({"queued": queued, "status": status}) is ok


def test_a_row_without_the_queue_columns_is_not_queued():
    assert _queued_open({"status": "pending"}) is False
    assert _queued_open({"queued": 1}) is False

    class Row:   # as sqlite3.Row: a missing column is an IndexError
        def __getitem__(self, k):
            raise IndexError(k)

    assert _queued_open(Row()) is False


# ---------------------------------------------------------------------------------------------
# _status_of_rounds
# ---------------------------------------------------------------------------------------------
SUP = [row("supports", 0.9)]


@pytest.mark.parametrize("stage", ["terms", "rank", "judge"])
def test_a_part_still_choosing_or_judging_waits(stage):
    assert _status_of_rounds(["done"], SUP, 0.6, stage) == "waiting"
    assert _status_of_rounds([], [], 0.6, stage) == "waiting"


def test_a_round_waiting_in_the_queue_waits():
    assert _status_of_rounds(["done"], SUP, 0.6, None, True) == "waiting"
    assert _status_of_rounds(["done"], SUP, 0.6, "done", False) == "supported"
    assert _status_of_rounds(["done"], SUP, 0.6) == "supported"


def test_no_round_means_nothing_matched():
    assert _status_of_rounds([], SUP, 0.6) == "no_passages"
    assert _status_of_rounds([], [], 0.6, "done") == "no_passages"


def test_a_done_round_gives_the_status_of_its_grades():
    assert _status_of_rounds(["failed", "done"], SUP, 0.6) == "supported"
    assert _status_of_rounds(["done", "failed"], [row("refutes", 0.9)], 0.6) == "contradicted"
    assert _status_of_rounds(["done", "pending"], [row("supports", 0.5)], 0.6) == "uncertain"
    assert _status_of_rounds(["done"], [], 0.6) == "not_checked"


@pytest.mark.parametrize("rounds, status", [(["failed"], "failed"), (["retry"], "failed"),
                                            (["pending"], "not_checked"), (["failed", "pending"], "not_checked"),
                                            (["pending", "failed"], "failed"), (["pending", "retry"], "failed"),
                                            (["exported"], "not_checked")])
def test_without_a_done_round_the_last_round_decides(rounds, status):
    assert _status_of_rounds(rounds, SUP, 0.6) == status


def test_the_status_words_of_the_statuses_these_give():
    for s in ("failed", "not_checked", "no_passages", "waiting", "supported", "contradicted", "uncertain"):
        assert V.STATUS_TEXT[s] and V.STATUS_HELP[s]
