"""Hunt phase 1.5, area `checks`: what phases 0 and 1 left about checks, verdicts, a person's judgements and what the
results become. Each test asserts what ENLENS should do; the ledger (.claude/audits/2026-11-19-phase1.5/ledger/
checks.md) says, per item, whether the test failed and what was changed."""
from __future__ import annotations

from enlens_claims import claimcheck, people
from enlens_claims.llm import BaselineBackend
from enlens_claims.store import Workspace

COLLEAGUE = "p0000000000aa"


def _checked(ws) -> tuple[str, str, str]:
    """A check of the loaded project, and the claim and one excerpt of it: (hyp_id, claim_id, passage_id)."""
    from test_shared_projects import CLAIM, _claim, _excerpts

    hid = claimcheck.check_hypothesis(ws, CLAIM, BaselineBackend(), "baseline", k=3)
    return hid, _claim(ws, hid), _excerpts(ws, hid)[0]["passage_id"]


# ---------------------------------------------------------------------------------------------
# 2. the owner's: old data, repaired once when a project opens
# ---------------------------------------------------------------------------------------------
def test_judgements_of_a_check_removed_by_an_earlier_version_stop_counting_when_the_project_opens(loaded):
    """CHECKS-7, old data: before hunt phase 1 removing a check left every person's judgements of its excerpts in
    `judgements`, where "how often you agreed" (people.agreement) still counts them. A judgement whose check no longer
    exists is reliably such a leftover: opening the project removes it."""
    hid, cid, pid = _checked(loaded)
    claimcheck.set_judgement(loaded, cid, pid, "supports")
    with loaded.connect() as cx:
        people.record(cx, cid, pid, COLLEAGUE, "refutes", None, None)
    assert people.agreement(loaded)[0]["both"] == 1
    kept = [dict(r) for r in loaded.query("SELECT * FROM judgements")]
    claimcheck.delete_hypothesis(loaded, hid)
    with loaded.connect() as cx:   # as an earlier version removed it: the judgements stayed
        for r in kept:
            cx.execute(f"INSERT INTO judgements({','.join(r)}) VALUES ({','.join('?' * len(r))})", tuple(r.values()))
    assert sum(a["both"] for a in people.agreement(loaded)) == 1
    loaded.close_all()
    again = Workspace.open(loaded.root)
    assert people.agreement(again) == []
    assert not again.scalar("SELECT COUNT(*) FROM judgements")


def test_a_judgement_wiped_from_its_excerpt_by_an_earlier_version_comes_back_when_the_project_opens(loaded):
    """CHECKS-2, old data: the earlier "Judge it myself" pressed twice wrote the excerpt's row again without the
    person's judgement, which stayed in `judgements`. An excerpt's row with no person's fields beside a judgement of it
    is reliably such a row: opening the project puts the judgement in force again (people.refresh's rule)."""
    hid, cid, pid = _checked(loaded)
    claimcheck.set_judgement(loaded, cid, pid, "refutes")
    before = {x["passage_id"]: x for p in claimcheck.hypothesis_result(loaded, hid)["parts"] for x in p["passages"]}
    assert before[pid]["user_verdict"] == "refutes"
    with loaded.connect() as cx:   # as the earlier version left it
        cx.execute("UPDATE verifications SET user_verdict=NULL, user_note=NULL, user_at=NULL, user_quote=NULL, "
                   "user_start=NULL, user_end=NULL, user_by=NULL WHERE subject_id=? AND passage_id=?", (cid, pid))
    loaded.close_all()
    again = Workspace.open(loaded.root)
    after = {x["passage_id"]: x for p in claimcheck.hypothesis_result(again, hid)["parts"] for x in p["passages"]}
    assert after[pid]["user_verdict"] == "refutes"
    assert again.scalar("SELECT user_by FROM verifications WHERE subject_id=? AND passage_id=?", (cid, pid)) == \
        people.me()


def test_the_repair_leaves_a_judgement_from_before_names_were_kept_and_a_taken_back_one_as_they_are(loaded):
    """The repair's limits: a judgement from before 0.14 (on the excerpt's row, no person, no `judgements` row) is
    not touched, nor an excerpt whose judgement was taken back (a `judgements` row without verdict or note)."""
    hid, cid, pid = _checked(loaded)
    others = [x["passage_id"] for p in claimcheck.hypothesis_result(loaded, hid)["parts"] for x in p["passages"]
              if x["passage_id"] != pid]
    with loaded.connect() as cx:
        cx.execute("UPDATE verifications SET user_verdict='supports' WHERE subject_id=? AND passage_id=?", (cid, pid))
        if others:
            people.record(cx, cid, others[0], people.me(), None, None, None)   # taken back
    loaded.close_all()
    again = Workspace.open(loaded.root)
    row = again.query("SELECT user_verdict, user_by FROM verifications WHERE subject_id=? AND passage_id=?",
                      (cid, pid))[0]
    assert (row["user_verdict"], row["user_by"]) == ("supports", None)
    if others:
        assert again.scalar("SELECT user_verdict FROM verifications WHERE subject_id=? AND passage_id=?",
                            (cid, others[0])) is None
        assert again.scalar("SELECT COUNT(*) FROM judgements WHERE claim_id=?", (cid,)) == 1


# ---------------------------------------------------------------------------------------------
# 3. a round nobody will answer any more: the person can act on it from the result page
# ---------------------------------------------------------------------------------------------
from test_hunt1_checks import HYP, PART_BILLS, PART_JOBS, RULES, Scripted, Unusable, _corpus, solar  # noqa: E402,F401
from test_local_memory import mixed  # noqa: E402,F401 (the fixture)


def _claim_of(ws, hid: str) -> str:
    return ws.scalar("SELECT claim_id FROM user_claims WHERE hyp_id=? ORDER BY part, rowid", (hid,))


def _main_task(ws, cid: str) -> str:
    return ws.scalar("SELECT task_id FROM tasks WHERE kind='check' AND task_id LIKE ? AND task_id NOT LIKE '%:local' "
                     "AND task_id NOT LIKE '%:person' ORDER BY created_at DESC, rowid DESC LIMIT 1", (f"check:{cid}%",))


def _age(ws, task_id: str, hours: float = 2) -> None:
    """As if the part was made, and last answered, `hours` ago."""
    import datetime as dt

    at = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)).replace(microsecond=0).isoformat()
    with ws.connect() as cx:
        cx.execute("UPDATE tasks SET created_at=? WHERE task_id=?", (at, task_id))
        cx.execute("UPDATE results SET received_at=? WHERE task_id=?", (at, task_id))


def test_a_check_the_app_left_between_two_tries_can_be_read_again_from_its_result(solar):
    """CHECKS-5: the app closed between two tries leaves the round at "retry": the result says "The check did not
    work" (try again), yet *Read more excerpts* refused ("still has excerpts waiting to be judged"), so the check
    could only be removed and made again."""
    hid = claimcheck.check_hypothesis(solar, PART_BILLS, Unusable({}), "claude-opus", expand=False, k=4, per_doc=2)
    cid = _claim_of(solar, hid)
    with solar.connect() as cx:   # as the app left it when it was closed after the first refused answer
        cx.execute("UPDATE tasks SET status='retry', attempts=1 WHERE task_id=?", (_main_task(solar, cid),))
    assert claimcheck.hypothesis_result(solar, hid)["status"] == "failed"
    assert claimcheck.further_round_waits(solar, hid) is None
    r = claimcheck.continue_check(solar, cid, Scripted(RULES), "claude-opus", k=4)
    assert r["passages"] and r["ok"]
    assert claimcheck.hypothesis_result(solar, hid)["status"] == "supported"


def test_a_round_the_app_made_and_never_started_ends_and_can_be_read_again(solar):
    """CHECKS-5, the plain left-open round: a round made and never tried (the app closed at once) read "Not finished
    yet" for good and *Read more excerpts* refused it. Made before this program started, and asked by no job of it
    now, it has ended (review wave 3: by that sign, not by time)."""
    from enlens_claims import taskqueue

    hid = claimcheck.check_hypothesis(solar, PART_BILLS, Unusable({}), "claude-opus", expand=False, k=4, per_doc=2)
    cid = _claim_of(solar, hid)
    tid = _main_task(solar, cid)
    with solar.connect() as cx:
        cx.execute("DELETE FROM results WHERE task_id=?", (tid,))
        cx.execute("UPDATE tasks SET status='pending', attempts=0 WHERE task_id=?", (tid,))
    assert claimcheck.further_round_waits(solar, hid) is not None   # it may be being read right now
    _age(solar, tid, hours=taskqueue.CLAIM_MINUTES / 60 + 1)
    assert claimcheck.hypothesis_result(solar, hid)["status"] != "not_checked"
    assert claimcheck.further_round_waits(solar, hid) is None
    r = claimcheck.continue_check(solar, cid, Scripted(RULES), "claude-opus", k=4)
    assert r["passages"] and r["ok"]
    assert claimcheck.hypothesis_result(solar, hid)["status"] == "supported"


def test_a_chat_refused_once_and_then_abandoned_ends_and_can_be_read_in_the_app(solar):
    """CHECKS-5 (review of phase 1): a Claude chat whose grades were refused once and that never came back read
    "Not finished yet" for good. Its round ends as a queue claim lapses; the result then lets the app read it."""
    from enlens_claims import judgements

    r = claimcheck.open_check(solar, PART_BILLS, terms=["bills"], k=3, per_doc=1)
    cid = r["check_id"]
    bad = claimcheck.submit_grades(solar, cid, [{"passage": 1, "verdict": "supports", "confidence": 0.9,
                                                 "quote": "words that are not in the excerpt at all"}], "x")
    assert bad["attempts_left"] == 2
    assert claimcheck.result(solar, cid)["status"] == "not_checked"           # the chat is still fixing them
    try:
        claimcheck.continue_check(solar, cid, Scripted(RULES), "claude-opus", k=3)
        raise AssertionError("a further round started while the chat could still answer")
    except ValueError as e:
        assert str(e) == claimcheck.ROUND_WAITS
    _age(solar, _main_task(solar, cid))
    res = claimcheck.result(solar, cid)
    assert res["status"] != "not_checked", res["status"]
    row = next(h for h in claimcheck.history(solar) if h["hyp_id"] == cid)
    assert row["status"] == res["status"]
    assert judgements.more_available(solar, cid)                      # Read more excerpts is offered
    out = claimcheck.continue_check(solar, cid, Scripted(RULES), "claude-opus", k=3)
    assert out["passages"] and out["ok"]
    assert claimcheck.result(solar, cid)["status"] == "supported"


def test_a_chat_that_never_answered_ends_too(solar):
    """CHECKS-5: the same for a chat that opened a check and never sent grades."""
    r = claimcheck.open_check(solar, PART_BILLS, terms=["bills"], k=3, per_doc=1)
    cid = r["check_id"]
    _age(solar, _main_task(solar, cid))
    assert claimcheck.result(solar, cid)["status"] != "not_checked"
    out = claimcheck.continue_check(solar, cid, Scripted(RULES), "claude-opus", k=3)
    assert out["ok"] and claimcheck.result(solar, cid)["status"] == "supported"


# ---------------------------------------------------------------------------------------------
# 4. Read the new documents for several: the count says how many were brought up to date
# ---------------------------------------------------------------------------------------------
class FailsFor(Scripted):
    """Scripted, except that its answers for a claim with `word` never pass the quote check."""

    def __init__(self, rules, word: str, before=None):
        super().__init__(rules)
        self.word, self.before = word, before

    def complete(self, kind, system, user, model, payload=None):
        if kind in ("check", "reread") and self.word in (payload or {}).get("claim", "").lower():
            if self.before:
                self.before()
            self.calls.append(kind)
            return '{"evidence": [{"passage": 1, "verdict": "supports", "confidence": 0.9, "quote": "nowhere at all"}]}'
        return super().complete(kind, system, user, model, payload)


def _add_later(ws, tmp_path, name="both.txt"):
    import time

    from enlens_claims import ingest

    time.sleep(1.1)   # added a second later than the checks (times are kept to the second)
    more = tmp_path / f"more-{name}"
    _corpus(more, {name: f"A second solar study ({name})\n\nRooftop solar panels lowered household electricity bills again in "
                         "a second survey of towns. Rooftop solar panels created no new local jobs in the survey towns "
                         "either.\n"})
    ingest.ingest(ws, [more], ai_access="cloud")
    return ws.scalar("SELECT doc_id FROM documents WHERE path LIKE ?", (f"%{name}",))


def test_reading_the_new_documents_for_several_counts_only_those_brought_up_to_date(solar, tmp_path):
    """The Results page after *Read the new documents* for two hypotheses, one of whose reading failed, said "2 of 2
    hypotheses brought up to date · 1 could not be read": the count of the job's result (`checked`, as for Check
    several) took in the one that failed."""
    from enlens_claims.gui.server import make_server

    bills = claimcheck.check_hypothesis(solar, PART_BILLS, Scripted(RULES), "claude-opus", expand=False, k=4)
    jobs = claimcheck.check_hypothesis(solar, PART_JOBS, Scripted(RULES), "claude-opus", expand=False, k=4)
    _add_later(solar, tmp_path)
    srv, app = make_server("127.0.0.1", 0)
    try:
        app.backend = lambda **kw: (FailsFor(RULES, "jobs"), "claude-opus")
        job = app.start_read_new("Solar", [bills, jobs])
        import time
        t0 = time.monotonic()
        while job.state in ("queued", "running") and time.monotonic() - t0 < 60:
            time.sleep(0.02)
        assert job.state == "done", (job.state, getattr(job, "error", None))
        res = job.result
        assert [h["failed"] for h in res["hypotheses"]] == [False, True]
        assert res["checked"] == [bills] and res["total"] == 2
    finally:
        srv.server_close()


# ---------------------------------------------------------------------------------------------
# 5. CHECKS-3, the gap left: a part judged meanwhile keeps its round, and a sibling part still gets the documents
# ---------------------------------------------------------------------------------------------
def test_a_part_whose_reading_failed_still_gets_the_new_documents_when_its_sibling_was_judged_meanwhile(solar, tmp_path):
    """*Read it* for a hypothesis in two parts: the bills part reads the new document and the person judges one of
    its excerpts meanwhile; the jobs part's answers fail. The judged round stays (as it must), and the document then
    counted as read for every part, so the jobs part never got it: it was no longer *added since*."""
    hid = claimcheck.check_hypothesis(solar, HYP, Scripted(RULES), "claude-opus", parts=[PART_BILLS, PART_JOBS],
                                      expand=False, k=4, per_doc=2)
    new = _add_later(solar, tmp_path)
    bills_cid, jobs_cid = [r[0] for r in solar.query("SELECT claim_id FROM user_claims WHERE hyp_id=? ORDER BY part",
                                                     (hid,))]

    def judge_meanwhile():
        x = next(x for p in claimcheck.hypothesis_result(solar, hid)["parts"] if p["claim_id"] == bills_cid
                 for x in p["passages"] if x["doc_id"] == new)
        claimcheck.set_judgement(solar, bills_cid, x["passage_id"], "supports")

    out = claimcheck.read_new_documents(solar, hid, FailsFor(RULES, "jobs", judge_meanwhile), "claude-opus", k=4)
    assert out["failed"]
    assert new in [d["doc_id"] for d in claimcheck.new_documents(solar, hid)]
    assert new in [d["doc_id"] for d in claimcheck.hypothesis_result(solar, hid)["docs_added_since"]]
    row = next(h for h in claimcheck.history(solar) if h["hyp_id"] == hid)
    assert row["docs_added_since"] == 1
    again = claimcheck.read_new_documents(solar, hid, Scripted(RULES), "claude-opus", k=4)
    assert not again["failed"]
    jobs_part = next(p for p in claimcheck.hypothesis_result(solar, hid)["parts"] if p["claim_id"] == jobs_cid)
    assert any(x["doc_id"] == new and x["counted"] for x in jobs_part["passages"])
    assert claimcheck.new_documents(solar, hid) == []


# ---------------------------------------------------------------------------------------------
# 7. whose sentence it is, when a colleague's judgement is in force
# ---------------------------------------------------------------------------------------------
def test_a_colleagues_sentence_in_force_is_not_called_yours(tmp_path, monkeypatch, loaded):
    """`quote_by` said "you" for the sentence of a colleague's judgement in force (check_results.py): the page now
    names the colleague by `judged_by`, but the field (and Excel's "Quote chosen by") still said it was yours."""
    from test_hunt1_checks import _pair
    from test_shared_projects import _claim, _excerpts

    anna, ben = _pair(loaded, tmp_path, monkeypatch)
    with anna:
        ex = _excerpts(anna.ws, anna.hid)[0]
        words = " ".join(ex["text"].split()[:6])
        claimcheck.set_judgement(anna.ws, _claim(anna.ws, anna.hid), ex["passage_id"], "refutes", quote=words)
    ben.bring_in(anna.send())
    with ben:
        got = next(x for x in _excerpts(ben.ws, anna.hid) if x["passage_id"] == ex["passage_id"])
        assert got["judged_by"] == "Anna" and got["quote"] == words
        # a fixed word the page tests, and the name apart (review wave 3)
        assert (got["quote_by"], got["quote_by_name"]) == ("colleague", "Anna"), got["quote_by"]
    with anna:   # in Anna's own copy it is hers
        mine = next(x for x in _excerpts(anna.ws, anna.hid) if x["passage_id"] == ex["passage_id"])
        assert (mine["quote_by"], mine["quote_by_name"]) == ("you", None)


def test_a_colleague_who_calls_themselves_you_is_still_a_colleague(tmp_path, monkeypatch, loaded):
    """Review wave 3 (CHECKS15-11): with the colleague's name in `quote_by`, a colleague named "you" (or "the AI")
    made the page take their sentence for yours (Undo, *Remove my sentence*) or for the AI's."""
    from test_shared_projects import CLAIM, Person, _claim, _excerpts

    from enlens_claims import bundle
    from enlens_claims.llm import BaselineBackend

    them, me = Person(tmp_path, "you", monkeypatch), Person(tmp_path, "Ben", monkeypatch)
    them.ws = loaded
    with them:
        hid = claimcheck.check_hypothesis(loaded, CLAIM, BaselineBackend(), "baseline", k=3)
        ex = _excerpts(loaded, hid)[0]
        words = " ".join(ex["text"].split()[:6])
        claimcheck.set_judgement(loaded, _claim(loaded, hid), ex["passage_id"], "refutes", quote=words)
        sent = them.send()
    with me:
        me.ws = bundle.import_project(sent, tmp_path / "ben-project")
        got = next(x for x in _excerpts(me.ws, hid) if x["passage_id"] == ex["passage_id"])
        assert (got["quote_by"], got["quote_by_name"], got["quote"]) == ("colleague", "you", words)


def test_a_colleagues_sentence_on_a_kept_excerpt_is_highlighted_at_their_words():
    """Review wave 3, must fix (CHECKS15-11): on an excerpt kept from an earlier reading of its document, `_place_kept`
    chose the person's sentence only for `quote_by == "you"`; with a colleague's judgement in force it highlighted the
    AI's words (or nothing) and took `doc_start` from the AI's offset."""
    from enlens_claims.check_results import _place_kept

    text = "Costs rose in the first year. Emissions fell by a third after the plant opened."
    v = {"quote": "Costs rose in the first year", "start": 1000, "user_quote": "Emissions fell by a third",
         "user_start": 1030, "user_verdict": "supports", "user_by": "p0000000000aa"}
    for by in ("you", "colleague"):
        item = {"quote_by": by, "in_corpus": True, "quote": v["user_quote"]}
        _place_kept(item, {"text": text}, v)
        assert text[item["quote_start"]:item["quote_end"]] == "Emissions fell by a third", by
        assert item["doc_start"] == 1030 - text.index("Emissions")
    item = {"quote_by": "the AI", "in_corpus": True, "quote": v["quote"]}
    _place_kept(item, {"text": text}, v)
    assert text[item["quote_start"]:item["quote_end"]] == "Costs rose in the first year"


# ---------------------------------------------------------------------------------------------
# 6. a failed "Read more excerpts" round keeps its excerpts, for the person to judge (0.14.3)
# ---------------------------------------------------------------------------------------------
def test_a_failed_further_round_keeps_its_excerpts_and_a_persons_judgement_of_them_counts(solar):
    """The 0.14.3 design (privacy.md *When the AI's own answers failed*; `_counting`): the excerpts of a further
    round whose AI answers failed stay on the result, none of the AI's judgements of them count, and a person's own
    judgement of one counts, since another round of the check was answered."""
    hid = claimcheck.check_hypothesis(solar, PART_BILLS, Scripted(RULES), "claude-opus", expand=False, k=1, per_doc=1)
    cid = _claim_of(solar, hid)
    out = claimcheck.continue_check(solar, cid, Unusable({}), "claude-opus", k=4)
    assert out["passages"] and out["ok"] is False
    res = claimcheck.hypothesis_result(solar, hid)
    later = [x for x in res["parts"][0]["passages"] if x["round"] == 2]
    assert later and not any(x["counted"] for x in later)
    claimcheck.set_judgement(solar, cid, later[0]["passage_id"], "supports")
    res = claimcheck.hypothesis_result(solar, hid)
    judged = next(x for x in res["parts"][0]["passages"] if x["passage_id"] == later[0]["passage_id"])
    assert judged["counted"] and judged["verdict"] == "supports"


# ---------------------------------------------------------------------------------------------
# 8. the SDG pack's VCA claim statuses, as sdg-pack.md defines them; and the rest of the hunter's notes
# ---------------------------------------------------------------------------------------------
def test_a_vca_claim_with_support_and_contradiction_is_supported_as_the_pack_documents():
    """docs/manual/sdg-pack.md *Reading the report*: supported = a passage states the effect; contradicted = a passage
    states the opposite "and none supports it, fully or partly". The pack has no "contested"; a check of the app has."""
    from enlens_claims.analysis import _status
    from enlens_claims.verdicts import claim_status

    sup, part, ref = ({"verdict": v, "confidence": 0.9} for v in ("supports", "partially_supports", "refutes"))
    assert _status([sup, ref], 0.6) == "supported"
    assert _status([part, ref], 0.6) == "partially_supported"
    assert _status([ref], 0.6) == "contradicted"
    assert _status([{"verdict": "refutes", "confidence": 0.3}], 0.6) == "unsupported"
    assert _status([], 0.6) == "not_checked"
    assert claim_status([sup, ref], 0.6) == "contested"   # the app's own checks


def _twice(solar, tmp_path):
    """A check of a document in which the person's sentence stands twice: (hid, claim, excerpt, words)."""
    from enlens_claims import ingest

    twice = "Rooftop solar panels lowered household electricity bills"
    more = tmp_path / "twice"
    _corpus(more, {"twice.txt": f"Twice report\n\n{twice} in the first town. Families saved money every month. "
                                f"{twice} in the second town as well.\n"})
    ingest.ingest(solar, [more], ai_access="cloud")
    doc = solar.scalar("SELECT doc_id FROM documents WHERE path LIKE '%twice.txt'")
    hid = claimcheck.check_hypothesis(solar, PART_BILLS, Scripted(RULES), "claude-opus", expand=False, k=6,
                                      per_doc=2, doc_ids=[doc])
    x = next(x for x in claimcheck.hypothesis_result(solar, hid)["parts"][0]["passages"] if x["text"].count(twice) == 2)
    return hid, _claim_of(solar, hid), x, twice


def test_a_persons_sentence_that_occurs_twice_is_kept_where_it_was_selected(solar, tmp_path):
    """notes/checks.md, not proven 1 (owner: fix): the sentence a person selected is saved, highlighted and placed in
    the document where they selected it (`quote_start` of the judgement endpoint, in the excerpt's text), not at the
    first place its words stand."""
    from test_app import Api

    from enlens_claims.gui.server import make_server

    hid, cid, x, twice = _twice(solar, tmp_path)
    second = x["text"].index(twice, x["text"].index(twice) + 1)
    srv, app = make_server("127.0.0.1", 0)
    import threading
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        api = Api(f"http://127.0.0.1:{srv.server_address[1]}", app.token)
        st, got = api("PUT", f"/api/projects/Solar/claims/{cid}/judgements/{x['passage_id']}",
                      {"verdict": "supports", "quote": twice, "quote_start": second})
        assert st == 200, got
        st, res = api("GET", f"/api/projects/Solar/hypotheses/{hid}")
        item = next(y for y in res["parts"][0]["passages"] if y["passage_id"] == x["passage_id"])
        assert (item["quote"], item["quote_start"], item["quote_end"]) == (twice, second, second + len(twice))
        start = solar.scalar("SELECT start FROM passages WHERE passage_id=?", (x["passage_id"],))
        assert solar.scalar("SELECT user_start FROM verifications WHERE subject_id=? AND passage_id=?",
                            (cid, x["passage_id"])) == start + second
        st, bad = api("PUT", f"/api/projects/Solar/claims/{cid}/judgements/{x['passage_id']}",
                      {"verdict": "supports", "quote": twice, "quote_start": "late"})
        assert st == 400 and "quote_start" in bad["error"]
    finally:
        srv.shutdown()
        srv.server_close()


def test_without_where_it_was_selected_a_sentence_is_kept_at_its_first_place_as_before(solar, tmp_path):
    """An older page and the connector send no `quote_start`: the words are kept at their first place, as before."""
    hid, cid, x, twice = _twice(solar, tmp_path)
    claimcheck.set_judgement(solar, cid, x["passage_id"], "supports", quote=twice)
    got = next(y for y in claimcheck.hypothesis_result(solar, hid)["parts"][0]["passages"]
               if y["passage_id"] == x["passage_id"])
    first = x["text"].index(twice)
    assert (got["quote"], got["quote_start"]) == (twice, first)


def test_the_connector_counts_only_grades_that_count_among_a_restricted_documents_evidence(loaded):
    """notes/checks.md, not proven: `restricted_evidence` counted every grade of a document the user keeps on this
    computer, those below the strictness too, beside the note "their grades count in the status"."""
    from enlens_claims import mcp_server

    hid, cid, _pid = _checked(loaded)
    rows = loaded.query("SELECT v.passage_id, v.doc_id FROM verifications v WHERE v.subject_id=? AND "
                        "v.verdict IN ('supports', 'partially_supports', 'refutes')", (cid,))
    assert rows
    doc = rows[0]["doc_id"]
    with loaded.connect() as cx:
        cx.execute("UPDATE verifications SET confidence=0.2 WHERE subject_id=? AND doc_id=?", (cid, doc))
        cx.execute("UPDATE documents SET ai_access='none' WHERE doc_id=?", (doc,))
    got = mcp_server._summary(loaded, cid, threshold=0.6)
    counted = {k: v for k, v in (got.get("restricted_evidence") or {}).items()
               if k in ("supports", "partially_supports", "refutes")}
    assert counted == {}, got.get("restricted_evidence")


def test_a_look_before_checking_left_unfinished_is_not_offered_as_checked_before(loaded):
    """notes/checks.md, not proven: `nearduplicates.checked_before` offered the `prep…` hypothesis an interrupted
    *Look before checking* leaves (the Results list hides it: it is no check)."""
    from enlens_claims import nearduplicates
    from test_shared_projects import CLAIM

    claimcheck.new_hypothesis(loaded, CLAIM, None, None, {"prepare": True}, None, hyp_id="prep0123456789")
    found = nearduplicates.checked_before(loaded, [CLAIM])[0]
    assert [f["hyp_id"] for f in found if f["hyp_id"].startswith("prep")] == []


def test_reading_again_an_excerpt_of_a_failed_round_keeps_it_out_of_the_answer(solar):
    """notes/checks.md, not proven: *Read again* on an excerpt of a round whose AI answers failed stores the new
    reading, but the excerpt stays out of the answer: the round did not work, and none of its AI judgements count
    (privacy.md *When the AI's own answers failed*; `_counting`)."""
    from enlens_claims import judgements

    hid = claimcheck.check_hypothesis(solar, PART_BILLS, Scripted(RULES), "claude-opus", expand=False, k=1, per_doc=1)
    cid = _claim_of(solar, hid)
    claimcheck.continue_check(solar, cid, Unusable({}), "claude-opus", k=4)
    later = [x for x in claimcheck.hypothesis_result(solar, hid)["parts"][0]["passages"] if x["round"] == 2]
    target = next((x for x in later if "lowered household electricity bills" in x["text"]), later[0])
    judgements.reread_excerpt(solar, cid, target["passage_id"], Scripted(RULES), "claude-opus")
    got = next(x for x in claimcheck.hypothesis_result(solar, hid)["parts"][0]["passages"]
               if x["passage_id"] == target["passage_id"])
    assert not got["counted"]


def test_a_quote_of_a_document_removed_before_the_grades_came_is_placed_where_it_was_found(solar):
    """notes/checks.md, not proven: a document removed between showing its excerpt and the grades: the quote's place
    is stored inside the excerpt (`doc_span(missing=0)`), and the result places it by its words. Both find the same
    first occurrence of the same words, so they agree."""
    r = claimcheck.open_check(solar, PART_BILLS, terms=["bills"], k=3, per_doc=1)
    cid = r["check_id"]
    n, shown = next((i, p) for i, p in enumerate(r["passages"], 1) if "lowered household electricity bills" in p["text"])
    doc = solar.scalar("SELECT doc_id FROM documents WHERE path LIKE '%bills.txt'")
    solar.remove_document(doc)
    ok = claimcheck.submit_grades(solar, cid, [{"passage": n, "verdict": "supports", "confidence": 0.9,
                                                "quote": "lowered household electricity bills"}], "x")
    assert ok["accepted"], ok
    got = next(x for x in claimcheck.result(solar, cid)["passages"] if x["doc_id"] == doc)
    i = shown["text"].index("lowered household electricity bills")
    assert (got["quote_start"], got["quote_end"]) == (i, i + len("lowered household electricity bills"))


def test_check_several_reads_back_enlenss_own_csv_without_its_formula_apostrophes():
    """notes/checks.md, not proven: ENLENS's own CSV puts an apostrophe before a cell that a spreadsheet could take
    for a formula (`review.csv_cell`); pasted back into *Check several*, the hypothesis kept it ("'+20% …")."""
    import csv as _csv
    import io as _io

    from enlens_claims.review import csv_cell

    texts = ["+20% more rooftop solar lowers household bills.", "-Rooftop solar creates local jobs.",
             "Rooftop solar lowers bills."]
    buf = _io.StringIO()
    w = _csv.writer(buf)
    w.writerow(["hypothesis", "status"])
    for t in texts:
        w.writerow([csv_cell(t), "supported"])
    assert "'+20%" in buf.getvalue()
    assert [x["text"] for x in claimcheck.parse_batch(buf.getvalue())] == texts


def test_get_check_with_a_later_parts_id_answers_for_the_whole_hypothesis(solar):
    """reviews/sync.md, note on CHECKS-1: get_check with any part's own check_id answers for the whole hypothesis
    (no call returns one part alone); each part is listed inside the answer with its own status and check_id, the
    key for more_passages. As the verdict on CHECKS-1 asked."""
    import asyncio
    import json as _json

    import pytest
    pytest.importorskip("mcp")
    from mcp import Client

    from enlens_claims.mcp_server import build_server

    hid = claimcheck.check_hypothesis(solar, HYP, Scripted(RULES), "claude-opus", parts=[PART_BILLS, PART_JOBS],
                                      expand=False, k=4, per_doc=2)
    res = claimcheck.hypothesis_result(solar, hid)

    async def run():
        async with Client(build_server()) as c:
            return _json.loads((await c.call_tool("get_check", {"check_id": res["parts"][1]["claim_id"]})).content[0].text)

    got = asyncio.run(run())
    assert got["claim"] == HYP and got["status"] == res["status"]
    assert [(p["check_id"], p["status"]) for p in got["parts"]] == [(p["claim_id"], p["status"]) for p in res["parts"]]


def test_an_excerpt_whose_local_reading_failed_can_be_judged_by_the_person(mixed, monkeypatch):  # noqa: F811
    """Item 6's sibling: the result says of a local part whose answers could not be used "they are shown without a
    judgement ... or judge them yourself", but such an excerpt had no row of its own, so judging it was refused."""
    from helpers_mixed_corpus import use_local_model
    from test_local_memory import GB, Watched, _queued_check_answered

    ws, ids = mixed
    use_local_model(monkeypatch, Watched(need=4 * GB, free=64 * GB))
    hid = _queued_check_answered(ws)
    tid = claimcheck.local_waiting(ws, [hid])[0]["task_id"]
    cid = ws.scalar("SELECT json_extract(payload_json, '$.subject_id') FROM tasks WHERE task_id=?", (tid,))
    pid = ws.scalar("SELECT json_extract(payload_json, '$.passages[0].passage_id') FROM tasks WHERE task_id=?", (tid,))
    with ws.connect() as cx:   # as three refused answers of the local model leave it
        cx.execute("UPDATE tasks SET status='failed', attempts=3 WHERE task_id=?", (tid,))
    res = claimcheck.hypothesis_result(ws, hid)
    assert any(p.get("local_failed") for p in res["parts"])
    claimcheck.set_judgement(ws, cid, pid, "supports")
    got = next(x for p in claimcheck.hypothesis_result(ws, hid)["parts"] for x in p["passages"] if x["passage_id"] == pid)
    assert got["user_verdict"] == "supports" and got["counted"]


# ---------------------------------------------------------------------------------------------
# review wave 3: a round that waits by design never ends by time; the chat's grades only for its own round
# ---------------------------------------------------------------------------------------------
def test_a_round_held_out_of_the_queue_for_its_provider_is_not_ended_after_30_minutes(solar):
    """Review wave 3 (CHECKS15-5/-6): a check by queue whose round waits, out of the queue, until the person allows
    its provider (`_add_round(hold=True)`: not queued, pending, stage `judge`) counted as ended 30 minutes after it was
    made: *Read more excerpts* and *Read the new documents* went through and `continue_check` deleted the round. So
    does a part whose documents no longer allow the cloud (it waits for a model that may read it)."""
    for stage, access_ in (("judge", "cloud"), (None, "local")):
        hid = claimcheck.check_hypothesis(solar, PART_BILLS, Unusable({}), "claude-opus", expand=False, k=4)
        cid = _claim_of(solar, hid)
        tid = _main_task(solar, cid)
        with solar.connect() as cx:
            cx.execute("DELETE FROM results WHERE task_id=?", (tid,))
            cx.execute("UPDATE tasks SET status='pending', attempts=0, queued=0, access=? WHERE task_id=?",
                       (access_, tid))
            cx.execute("UPDATE user_claims SET stage=? WHERE claim_id=?", (stage, cid))
        _age(solar, tid, hours=3)
        t = next(t for t in claimcheck._check_tasks(solar, cid) if t["task_id"] == tid)
        assert not claimcheck._left(t), (stage, access_)
        assert claimcheck.further_round_waits(solar, hid) == claimcheck.ROUND_WAITS
        try:
            claimcheck.continue_check(solar, cid, Scripted(RULES), "claude-opus", k=4)
            raise AssertionError("a further round started over a round that waits")
        except ValueError as e:
            assert str(e) == claimcheck.ROUND_WAITS
        assert solar.scalar("SELECT status FROM tasks WHERE task_id=?", (tid,)) == "pending"


class SlowReader(Scripted):
    """Scripted, but each judging call is a long one: it looks at the check while it reads."""

    def __init__(self, ws, rules):
        super().__init__(rules)
        self.ws, self.seen = ws, []

    def complete(self, kind, system, user, model, payload=None):
        if kind == "check":
            cid = (payload or {}).get("subject_id")
            hid = self.ws.scalar("SELECT COALESCE(hyp_id, claim_id) FROM user_claims WHERE claim_id=?", (cid,))
            self.seen.append((claimcheck.hypothesis_result(self.ws, hid)["status"],
                              claimcheck.further_round_waits(self.ws, hid)))
        return super().complete(kind, system, user, model, payload)


def test_a_part_a_slow_model_is_reading_now_has_not_ended(solar, monkeypatch):
    """Review wave 3: an in-app part read by a slow model showed "The check did not work" 30 minutes after it was made,
    while its job was visibly running, and a further round could start over it. (As if hours had passed: every part
    counts as made before this program started.)"""
    import datetime as dt

    later = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=3)).replace(microsecond=0).isoformat()
    monkeypatch.setattr(claimcheck, "_STARTED", later)
    hid = claimcheck.check_hypothesis(solar, PART_BILLS, Scripted(RULES), "claude-opus", expand=False, k=1, per_doc=1)
    cid = _claim_of(solar, hid)
    slow = SlowReader(solar, RULES)
    out = claimcheck.continue_check(solar, cid, slow, "claude-opus", k=4)
    assert out["ok"] and slow.seen
    for status, waits in slow.seen:
        assert status != "failed" and waits == claimcheck.ROUND_WAITS, (status, waits)


def test_a_chats_grades_for_a_round_the_app_has_read_again_are_refused_in_words(solar):
    """Review wave 3 note (CHECKS15-5/-6): a chat that sent its grades after its round lapsed and the app read it again
    had them stored in the app's new round while that was still pending (`submit_grades` took the latest round)."""
    r = claimcheck.open_check(solar, PART_BILLS, terms=["bills"], k=3, per_doc=1)
    cid = r["check_id"]
    _age(solar, _main_task(solar, cid))
    claimcheck.continue_check(solar, cid, Scripted(RULES), "claude-opus", k=3)
    app_round = _main_task(solar, cid)
    with solar.connect() as cx:   # as while the app is still reading it
        cx.execute("DELETE FROM verifications WHERE subject_id=? AND model != 'person'", (cid,))
        cx.execute("DELETE FROM results WHERE task_id=?", (app_round,))
        cx.execute("UPDATE tasks SET status='pending', attempts=0 WHERE task_id=?", (app_round,))
    n = next(i for i, p in enumerate(r["passages"], 1) if "lowered household electricity bills" in p["text"])
    try:
        claimcheck.submit_grades(solar, cid, [{"passage": n, "verdict": "supports", "confidence": 0.9,
                                               "quote": "lowered household electricity bills"}], "x")
        raise AssertionError("the chat's grades were taken for the app's round")
    except ValueError as e:
        assert "get_check" in str(e) and "more_passages" in str(e), str(e)
    assert solar.scalar("SELECT status FROM tasks WHERE task_id=?", (app_round,)) == "pending"
    assert not solar.scalar("SELECT COUNT(*) FROM results WHERE task_id=?", (app_round,))


def test_a_split_hypothesis_from_before_shows_no_wave_of_new_documents(solar, tmp_path):
    """Review wave 3 note (CHECKS15-8): with "read by every part", a part with no round at all (its search found
    nothing) made every document a sibling read since count as new, and a part that searched only after documents were
    added (a check by queue ranks later) made the documents it saw and passed over count as new for the others."""
    import time

    hid = claimcheck.check_hypothesis(solar, HYP, Scripted(RULES), "claude-opus", expand=False, k=2, per_doc=1,
                                      parts=[PART_BILLS, "Quantum zebras juggle xylophones beneath glaciers."])
    bills, nothing = [r[0] for r in solar.query("SELECT claim_id FROM user_claims WHERE hyp_id=? ORDER BY part",
                                                (hid,))]
    assert not claimcheck._check_tasks(solar, nothing)   # its search found nothing: no round
    new = _add_later(solar, tmp_path)
    out = claimcheck.continue_check(solar, bills, Scripted(RULES), "claude-opus", k=8)
    assert any(p.get("document") for p in out["passages"]) or out["passages"]
    assert new in {x["doc_id"] for p in claimcheck.hypothesis_result(solar, hid)["parts"] for x in p["passages"]}
    assert claimcheck.new_documents(solar, hid) == []
    assert claimcheck.hypothesis_result(solar, hid)["docs_added_since"] == []
    assert next(h for h in claimcheck.history(solar) if h["hyp_id"] == hid)["docs_added_since"] == 0

    # a check in two parts, the second of which searched after a document was added (as a check by queue ranks later)
    hid2 = claimcheck.check_hypothesis(solar, HYP, Scripted(RULES), "claude-opus", expand=False, k=2, per_doc=1,
                                       parts=[PART_BILLS, PART_JOBS])
    first, second = [r[0] for r in solar.query("SELECT claim_id FROM user_claims WHERE hyp_id=? ORDER BY part",
                                               (hid2,))]
    newer = _add_later(solar, tmp_path, "newer.txt")
    time.sleep(1.1)
    with solar.connect() as cx:   # the second part searched only now: it saw the newer document and passed it over
        cx.execute("UPDATE tasks SET created_at=? WHERE task_id LIKE ?", (claimcheck.now(), f"check:{second}%"))
    claimcheck.continue_check(solar, first, Scripted(RULES), "claude-opus", k=8)
    assert newer in {x["doc_id"] for p in claimcheck.hypothesis_result(solar, hid2)["parts"] for x in p["passages"]}
    assert newer not in [d["doc_id"] for d in claimcheck.new_documents(solar, hid2)]
