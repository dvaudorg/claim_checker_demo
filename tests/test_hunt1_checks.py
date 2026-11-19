"""Hunt phase 1, area `checks`: checking a hypothesis, its verdict, a person's judgements, and what the results
become. Each test asserts what ENLENS should do and fails today for the reason in its docstring."""
from __future__ import annotations

import asyncio
import csv
import io
import json
from pathlib import Path

import pytest
from helpers_mixed_corpus import use_local_model
from test_local_memory import GB, Watched, _queued_check_answered, mixed  # noqa: F401 (the fixture)

from enlens_claims import claimcheck, home, ingest, people, review


# ---------------------------------------------------------------------------------------------
# a small project and a stand-in model whose judgements the test decides
# ---------------------------------------------------------------------------------------------
BILLS = ("Rooftop solar panels lowered household electricity bills in the survey towns. Families reported savings "
         "every month after the installation, and the utility confirmed lower readings.")
JOBS = ("Rooftop solar panels created no new local jobs in the survey towns. Installers came from the capital and "
        "left after a week, so the towns kept no work from the programme.")
BIRDS = ("Migrating birds rest in the wetlands each spring. Volunteers count the herons and the storks along the "
         "river, and the numbers have stayed stable for a decade.")
HYP = "Rooftop solar panels lower electricity bills and create local jobs in towns."
PART_BILLS = "Rooftop solar panels lower household electricity bills in towns."
PART_JOBS = "Rooftop solar panels create local jobs in towns."


class Scripted:
    """A stand-in for Claude whose judgement of each excerpt the test sets: `rules` maps a word of the claim being
    checked to [(words of an excerpt, verdict)]; the quote is those words."""
    name = "anthropic"

    def __init__(self, rules: dict[str, list[tuple[str, str]]], confidence: float = 0.9):
        self.rules, self.confidence = rules, confidence
        self.calls: list[str] = []

    def complete(self, kind, system, user, model, payload=None):
        self.calls.append(kind)
        if kind not in ("check", "reread"):
            return json.dumps({"terms": ["solar"]})
        claim = (payload or {}).get("claim", "").lower()
        evidence = []
        for i, p in enumerate((payload or {}).get("passages", []), 1):
            for key, pairs in self.rules.items():
                if key not in claim:
                    continue
                for words, verdict in pairs:
                    if words in p["text"]:
                        evidence.append({"passage": i, "verdict": verdict, "confidence": self.confidence,
                                         "quote": words})
        return json.dumps({"evidence": evidence, "rationale": "Scripted."})


RULES = {"bills": [("lowered household electricity bills", "supports")],
         "jobs": [("created no new local jobs", "refutes")]}


def _corpus(folder: Path, docs: dict[str, str] | None = None) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for name, text in (docs or {"bills.txt": f"Bills report\n\n{BILLS}\n", "jobs.txt": f"Jobs report\n\n{JOBS}\n",
                                "birds.txt": f"Birds report\n\n{BIRDS}\n"}).items():
        (folder / name).write_text(text, encoding="utf-8")
    return folder


@pytest.fixture
def solar(tmp_path, monkeypatch):
    """A project in ENLENS_HOME (the connector finds it there) with three short documents."""
    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("ENLENS_LOCAL_ONLY", raising=False)
    ws = home.create_project("Solar")
    ingest.ingest(ws, [_corpus(tmp_path / "corpus")], ai_access="cloud")
    return ws


def _two_part_check(ws, rules=RULES) -> str:
    return claimcheck.check_hypothesis(ws, HYP, Scripted(rules), "claude-opus", parts=[PART_BILLS, PART_JOBS],
                                       expand=False, k=4, per_doc=2)


# ---------------------------------------------------------------------------------------------
# 1. the connector's get_check answers for the hypothesis that list_checks lists
# ---------------------------------------------------------------------------------------------
def test_the_connector_gives_a_hypothesis_in_parts_the_same_answer_in_get_check_as_in_list_checks(solar):
    """list_checks lists a hypothesis in parts by its first part's claim id with the combined answer (contradicted);
    get_check with that id answers for the first part alone (supported). mcp_server.py:498 and :207 `_summary`."""
    pytest.importorskip("mcp")
    from mcp import Client

    from enlens_claims.mcp_server import build_server

    hid = _two_part_check(solar)
    res = claimcheck.hypothesis_result(solar, hid)
    assert [p["status"] for p in res["parts"]] == ["supported", "contradicted"]
    assert res["status"] == "contradicted"

    async def run():
        async with Client(build_server()) as c:
            listed = json.loads((await c.call_tool("list_checks", {"project": "Solar"})).content[0].text)["checks"]
            row = next(x for x in listed if x["claim"] == HYP)
            got = json.loads((await c.call_tool("get_check", {"check_id": row["check_id"]})).content[0].text)
            return row, got

    row, got = asyncio.run(run())
    assert row["status"] == "contradicted"
    assert got["status"] == row["status"], (got["status"], row["status"])


# ---------------------------------------------------------------------------------------------
# 2. the reviewer queue read back from a spreadsheet saved with semicolons
# ---------------------------------------------------------------------------------------------
def test_the_reviewer_queue_reads_back_decisions_from_a_spreadsheet_saved_with_semicolons(ws, tmp_path):
    """Excel in most European languages saves a CSV with ";" between cells; `read_csv_rows` reads only commas, so
    every decision is skipped and nothing is applied. review.py:159 `read_csv_rows`, :162 `import_decisions`."""
    with ws.connect() as cx:
        cx.execute("INSERT INTO documents(doc_id, path, sha1, title) VALUES ('d1', '/x', 's', 'T')")
        cx.execute("INSERT INTO passages(passage_id, doc_id, seq, page, text) VALUES ('d1:0001', 'd1', 1, 1, 't')")
        cx.execute("INSERT INTO claims(claim_id, task_id, doc_id, passage_id, claim, status) VALUES "
                   "('c1', 't', 'd1', 'd1:0001', 'Hydrogen creates jobs', 'needs_review')")
    path = tmp_path / "queue.csv"
    review.export(ws, path, include_vca=False)
    rows = review.read_csv_rows(path)
    rows[0]["decision"] = "accept"
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0]), delimiter=";")
    w.writeheader()
    w.writerows(rows)
    path.write_bytes(("﻿" + buf.getvalue()).encode("utf-8"))  # as Excel saves "CSV UTF-8" with ";" cells
    out = review.import_decisions(ws, path)
    assert out["applied"] == 1, out
    assert ws.scalar("SELECT status FROM claims WHERE claim_id='c1'") == "accepted"


# ---------------------------------------------------------------------------------------------
# 3. a person's judgement survives "Judge it myself" → "Let the local model read them" → "Judge it myself"
# ---------------------------------------------------------------------------------------------
def _local_items(res: dict, doc_id: str) -> list[dict]:
    return [{**x, "claim_id": part["claim_id"]} for part in res["parts"] for x in part["passages"]
            if x["doc_id"] == doc_id]


def test_a_judgement_made_by_hand_survives_changing_ones_mind_twice(mixed, monkeypatch):
    """After Judge it myself, a judgement, Let the local model read them, and Judge it myself again, `_to_person`
    writes the excerpt's row again (INSERT OR REPLACE) without the person's judgement. claimcheck.py:266, :343."""
    ws, ids = mixed
    use_local_model(monkeypatch, Watched(need=4 * GB, free=64 * GB))
    hid = _queued_check_answered(ws)
    claimcheck.judge_local_yourself(ws, hid)
    judged = _local_items(claimcheck.hypothesis_result(ws, hid), ids["local"])[0]
    claimcheck.set_judgement(ws, judged["claim_id"], judged["passage_id"], "supports")
    assert claimcheck.local_again(ws, hid)
    claimcheck.judge_local_yourself(ws, hid)   # changed my mind again: I judge them myself after all
    after = {x["passage_id"]: x for x in _local_items(claimcheck.hypothesis_result(ws, hid), ids["local"])}
    assert after[judged["passage_id"]]["user_verdict"] == "supports"
    assert after[judged["passage_id"]]["counted"]


# ---------------------------------------------------------------------------------------------
# 4. a theory document added after a check is no new evidence in the list either
# ---------------------------------------------------------------------------------------------
def test_a_theory_document_added_after_a_check_is_not_counted_as_added_since_in_the_list(solar, tmp_path):
    """The Results list counts every document added after the check (`history`, claimcheck.py:1852), the result
    page only evidence documents (`new_documents`, check_results.py:771): a theory document added since shows
    "1 document added since" in the list and the Excel summary says 0."""
    import time

    from enlens_claims import docrole

    hid = _two_part_check(solar)
    time.sleep(1.1)   # added a second later than the check (times are kept to the second)
    more = tmp_path / "more"
    _corpus(more, {"theory.txt": "A theory of energy transitions\n\n" + "Rooftop solar panels and local jobs in "
                   "towns are read here through the lens of diffusion theory and household electricity bills.\n"})
    ingest.ingest(solar, [more], ai_access="cloud")
    theory = solar.scalar("SELECT doc_id FROM documents WHERE path LIKE '%theory.txt'")
    docrole.set_role(solar, theory, "theory")
    page = claimcheck.hypothesis_result(solar, hid)["docs_added_since"]
    row = next(h for h in claimcheck.history(solar) if h["hyp_id"] == hid)
    assert page == []
    assert row["docs_added_since"] == len(page), row["docs_added_since"]


# ---------------------------------------------------------------------------------------------
# 5. a chat's first answer rejected once is not "the check did not work"
# ---------------------------------------------------------------------------------------------
def test_a_check_whose_first_answer_was_rejected_once_is_not_shown_as_failed(solar):
    """A Claude chat's grades refused once (two tries left, "fix exactly these problems") put the round in "retry",
    and `_status_of_rounds` (verdicts.py:337) reads "retry" as failed: the app, the list and get_check say "The
    check did not work", which STATUS_HELP explains as "even after three tries"."""
    r = claimcheck.open_check(solar, PART_BILLS, terms=["bills"], k=3, per_doc=1)
    cid = r["check_id"]
    bad = claimcheck.submit_grades(solar, cid, [{"passage": 1, "verdict": "supports", "confidence": 0.9,
                                                 "quote": "words that are not in the excerpt at all"}], "x")
    assert bad["accepted"] is False and bad["attempts_left"] == 2
    res = claimcheck.result(solar, cid)
    row = next(h for h in claimcheck.history(solar) if h["hyp_id"] == cid)
    assert res["status"] != "failed", res["status"]
    assert row["status"] != "failed", row["status"]


# ---------------------------------------------------------------------------------------------
# 6. a removed check takes its judgements with it
# ---------------------------------------------------------------------------------------------
def test_a_removed_check_no_longer_counts_in_how_often_you_and_a_colleague_agreed(tmp_path, monkeypatch, loaded):
    """`delete_claim` (judgements.py:220) removes the excerpts' rows but leaves every person's judgements of them in
    `judgements`, so "how often you and Anna agreed" (people.agreement) still counts the excerpts of a check removed."""
    from test_shared_projects import _claim, _excerpts

    anna, ben = _pair(loaded, tmp_path, monkeypatch)   # as test_shared_projects' anna_and_ben
    with anna:
        ex = _excerpts(anna.ws, anna.hid)[0]
        claimcheck.set_judgement(anna.ws, _claim(anna.ws, anna.hid), ex["passage_id"], "refutes")
    ben.bring_in(anna.send())
    with ben:
        claimcheck.set_judgement(ben.ws, _claim(ben.ws, anna.hid), ex["passage_id"], "supports")
        assert people.agreement(ben.ws)[0]["both"] == 1
        claimcheck.delete_hypothesis(ben.ws, anna.hid, why="not our question")
        assert not ben.ws.scalar("SELECT 1 FROM hypotheses WHERE hyp_id=?", (anna.hid,))
        left = people.agreement(ben.ws)
        assert sum(a["both"] for a in left) == 0, left


def _pair(loaded, tmp_path, monkeypatch):
    from test_shared_projects import CLAIM, Person

    from enlens_claims import bundle
    from enlens_claims.llm import BaselineBackend

    anna, ben = Person(tmp_path, "Anna", monkeypatch), Person(tmp_path, "Ben", monkeypatch)
    anna.ws = loaded
    with anna:
        anna.hid = claimcheck.check_hypothesis(loaded, CLAIM, BaselineBackend(), "baseline", k=3)
    first = anna.send()
    with ben:
        ben.ws = bundle.import_project(first, tmp_path / "ben-project")
    return anna, ben


# ---------------------------------------------------------------------------------------------
# 7. Check several: a spreadsheet of one column, "hypothesis"
# ---------------------------------------------------------------------------------------------
def test_check_several_reads_a_one_column_spreadsheet_by_its_header(tmp_path):
    """A CSV with the one column *hypothesis* (as a spreadsheet saves it: a cell with a comma in quotes) is read as
    plain lines, since its header has no separator (claimcheck.py:1909): the header becomes a hypothesis and the
    quoted cell keeps its quotes."""
    text = ("﻿hypothesis\r\n\"Green hydrogen, made in arid regions, raises water stress.\"\r\n"
            "Rooftop solar panels lower household electricity bills.\r\n")
    items = claimcheck.parse_batch(text)
    assert [x["text"] for x in items] == ["Green hydrogen, made in arid regions, raises water stress.",
                                          "Rooftop solar panels lower household electricity bills."]


# ---------------------------------------------------------------------------------------------
# 8. judging an excerpt the small local model only pointed at is no change of an AI judgement, in the list too
# ---------------------------------------------------------------------------------------------
def test_judging_an_excerpt_the_local_model_only_pointed_at_is_not_counted_as_changed_in_the_list(loaded):
    """The result page counts no "changed by you" for an excerpt the small local model only pointed at
    (check_results.py:289, it judged nothing); the Results list counts it as changed (`changed_by_person` in
    `history`, claimcheck.py:1758), so the list says "1 changed by you" and the Excel summary 0."""
    from test_local_tiers import CLAIM as WATER, K2, LocalStandIn

    cid = claimcheck.check_claim(loaded, WATER, LocalStandIn(), K2, k=3, expand=False)
    res = claimcheck.hypothesis_result(loaded, cid)
    x = next(x for x in res["parts"][0]["passages"] if x["suggestion"] and x["suggestion"]["form"] == "point")
    claimcheck.set_judgement(loaded, cid, x["passage_id"], "supports")
    res = claimcheck.hypothesis_result(loaded, cid)
    row = next(h for h in claimcheck.history(loaded) if h["hyp_id"] == cid)
    assert res["corrected"] == 0 and res["reviewed"] == 1
    assert row["corrected"] == res["corrected"], (row["corrected"], res["corrected"])


# ---------------------------------------------------------------------------------------------
# 9. reading the documents added since, when the AI's answers for them fail
# ---------------------------------------------------------------------------------------------
class Unusable(Scripted):
    """Claude whose judging answers never pass the quote check."""

    def complete(self, kind, system, user, model, payload=None):
        self.calls.append(kind)
        return json.dumps({"evidence": [{"passage": 1, "verdict": "supports", "confidence": 0.9,
                                         "quote": "words that are nowhere in the excerpt"}]})


def test_documents_added_since_whose_reading_failed_can_be_read_again(solar, tmp_path):
    """*Read it* on the documents added since: when the AI's answers for them fail three times, the failed round
    stays, its excerpts count nowhere, and the documents are no longer "added since" (claimcheck.py:1533 marks them
    looked at; `new_documents` and `more_passages` skip every excerpt any round showed). The answer is shown as
    whole and the new documents can never be read for this check."""
    import time

    hid = _two_part_check(solar)
    time.sleep(1.1)
    more = tmp_path / "more"
    _corpus(more, {"bills2.txt": "Second bills study\n\nRooftop solar panels lowered household electricity bills "
                   "again in a second survey of towns, with savings each month.\n"})
    ingest.ingest(solar, [more], ai_access="cloud")
    assert [d["matching"] for d in claimcheck.new_documents(solar, hid)] == [True]
    out = claimcheck.read_new_documents(solar, hid, Unusable({}), "claude-opus", k=4)
    assert out["passages"] and not any(r["ok"] for r in out["rounds"])
    res = claimcheck.hypothesis_result(solar, hid)
    assert res["docs_added_since"] or res["incomplete"], (res["docs_added_since"], res["incomplete"])


# ---------------------------------------------------------------------------------------------
# siblings found by the fixer
# ---------------------------------------------------------------------------------------------
def test_documents_never_read_whose_reading_failed_can_be_read_again(solar):
    """CHECKS-3's sibling, *Read these* (roadmap N5): a round whose AI answers fail three times showed its excerpts,
    so `_unread_split` counted its documents as read in this check, though nothing of them counted, and *Read these*
    could never read them again."""
    hid = claimcheck.check_hypothesis(solar, PART_BILLS, Scripted(RULES), "claude-opus", expand=False, k=1, per_doc=1)
    before = claimcheck.unread_documents(solar, hid)
    assert before["matching_n"] >= 1, before
    out = claimcheck.read_unread_documents(solar, hid, Unusable({}), "claude-opus", k=4)
    assert out["failed"] and not any(r["ok"] for r in out["rounds"]), out
    assert claimcheck.unread_documents(solar, hid)["matching_n"] == before["matching_n"]


def test_a_failed_reading_of_new_documents_is_said_and_leaves_them_waiting(solar, tmp_path):
    """CHECKS-3, what the job says: the documents stay *added since* (not marked as looked at) and the job's result
    says the reading did not work, so the page can say so."""
    import time

    hid = _two_part_check(solar)
    time.sleep(1.1)
    more = tmp_path / "more"
    _corpus(more, {"bills2.txt": "Second bills study\n\nRooftop solar panels lowered household electricity bills "
                   "again in a second survey of towns, with savings each month.\n"})
    ingest.ingest(solar, [more], ai_access="cloud")
    checked = solar.scalar("SELECT docs_checked_at FROM hypotheses WHERE hyp_id=?", (hid,))
    out = claimcheck.read_new_documents(solar, hid, Unusable({}), "claude-opus", k=4)
    assert out["failed"] and not any(r["ok"] for r in out["rounds"])
    assert solar.scalar("SELECT docs_checked_at FROM hypotheses WHERE hyp_id=?", (hid,)) == checked
    assert [d["matching"] for d in claimcheck.new_documents(solar, hid)] == [True]
    row = next(h for h in claimcheck.history(solar) if h["hyp_id"] == hid)
    assert row["docs_added_since"] == 1
    # and Read it again, with an AI whose answers pass, reads them
    again = claimcheck.read_new_documents(solar, hid, Scripted(RULES), "claude-opus", k=4)
    assert not again["failed"] and again["passages"]
    assert claimcheck.new_documents(solar, hid) == []


def test_get_check_of_a_hypothesis_in_parts_gives_every_part_and_its_evidence(solar):
    """CHECKS-1, the rest of the answer: each part with its own status and check_id (the key for more_passages), and
    the evidence of both parts, not the first part's alone."""
    pytest.importorskip("mcp")
    from mcp import Client

    from enlens_claims.mcp_server import build_server

    hid = _two_part_check(solar)
    res = claimcheck.hypothesis_result(solar, hid)

    async def run():
        async with Client(build_server()) as c:
            return json.loads((await c.call_tool("get_check", {"check_id": res["parts"][0]["claim_id"]})).content[0].text)

    got = asyncio.run(run())
    assert got["claim"] == HYP
    assert [(p["check_id"], p["status"]) for p in got["parts"]] == [(p["claim_id"], p["status"]) for p in res["parts"]]
    assert {e["part"] for e in got["evidence"]} == {1, 2}
    assert got["passages_read"] == res["excerpts_read"]


def test_removing_every_document_takes_every_judgement_with_the_checks(loaded):
    """CHECKS-7's sibling: *Remove every document* (`reset_corpus`) removes every check but left the people's
    judgements of their excerpts in `judgements`, where "how often you agreed" still counted them."""
    from enlens_claims.llm import BaselineBackend
    from test_shared_projects import CLAIM, _claim, _excerpts

    hid = claimcheck.check_hypothesis(loaded, CLAIM, BaselineBackend(), "baseline", k=3)
    ex = _excerpts(loaded, hid)[0]
    claimcheck.set_judgement(loaded, _claim(loaded, hid), ex["passage_id"], "supports")
    assert loaded.scalar("SELECT COUNT(*) FROM judgements")
    loaded.reset_corpus()
    assert not loaded.scalar("SELECT COUNT(*) FROM hypotheses")
    assert loaded.scalar("SELECT COUNT(*) FROM judgements") == 0
