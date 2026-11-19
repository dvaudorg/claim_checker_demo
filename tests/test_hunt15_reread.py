"""Hunt phase 1.5, area `reread`: *Read with the new reader* keeps the person's work (reread.py, never tested by a
hunt before). The rule it keeps (the phase 1 brief):

    Reading again with a newer reader keeps the person's work. Judgements, labels, notes, highlights, blocks left out
    and quotes are carried to the new reading where the words still exist, at the right place (also when the same
    words occur twice); where they no longer exist this is reported, never silently dropped or attached to other
    words. A re-read that fails or is stopped half-way leaves the old reading whole. Moving back to the earlier
    reading is possible and loses nothing. Reading again twice equals once.

Each kind of work is probed (a) on words the new reader keeps, (b) on words said several times, (c) where the passages
change (one becomes several, several become one), (d) where the words are gone; then the preview against the move, a
move that fails or is stopped, the same move twice, a move while a label run or a check of the document is under way,
a document in a team (a colleague's other reading, and moving back to the earlier reading), and a block left out
whose text the new reader changes. The ledger (.claude/audits/2026-11-19-phase1.5/ledger/reread.md) says for each
whether it failed and was fixed, or passed.
"""
from __future__ import annotations

import json
import random
import re
from pathlib import Path

import pytest
from test_old_readings import paper_shared  # noqa: F401  (a fixture)
from test_read_with_new_reader import (HEAD, Q_DESAL, Q_JUDGE, Q_WATER, SITES, _add, _check, _dump, _occurrence,
                                       _pid_with, _same, paper)  # noqa: F401  (paper: a fixture)
from test_reader3 import _sentence

from enlens_claims import claimcheck, ingest, notes, profile, reread
from enlens_claims import reader as reader2
from enlens_claims.store import Workspace

OFF = ingest.OcrOptions(mode="off")
REPEAT = "fear that the long-term supply of water will fall"   # in every paragraph of the paper


def _text(ws: Workspace, doc: str | None = None) -> str:
    if doc is None:
        return ws.scalar("SELECT text FROM documents")
    return ws.scalar("SELECT text FROM documents WHERE doc_id=?", (doc,))


def _bad_words(text: str) -> str:
    """Words of reader 1's text that run across its running head and page number: no reader after it has them in
    that order (test_read_with_new_reader's way)."""
    i = text.index(HEAD, 10)
    bad = text[i + len(HEAD) - 5:i + len(HEAD) + 22].strip()
    bad = bad[:bad.rfind(" ")]
    assert re.search(r"45-67 \d ", bad), bad
    return bad


def _shown(ws: Workspace, cid: str) -> list[str]:
    return [p["passage_id"] for p in claimcheck.result(ws, cid)["passages"]]


def _work(ws: Workspace, doc: str, words: dict[str, tuple[str, int]]) -> dict:
    """The person's work of every kind on the words given ({kind: (words, offset in the document)}): a judgement with
    its sentence, a label of their own with its quote, a note, a highlight. Returns their ids."""
    text = _text(ws, doc)
    out = {}
    cid = _check(ws, [(Q_WATER, "supports")])[0]
    out["cid"] = cid
    w, at = words["judgement"]
    pid = ws.scalar("SELECT passage_id FROM passages WHERE doc_id=? AND start<=? AND end>?", (doc, at, at))
    assert pid in _shown(ws, cid), "the check must show the passage to judge"
    p_start = ws.scalar("SELECT start FROM passages WHERE passage_id=?", (pid,))
    claimcheck.set_judgement(ws, cid, pid, "refutes", "Not here.", quote=w, quote_start=at - p_start)
    out["judgement_pid"] = pid
    w, at = words["label"]
    pid = ws.scalar("SELECT passage_id FROM passages WHERE doc_id=? AND start<=? AND end>?", (doc, at, at))
    out["label"] = profile.add_label(ws, "sdg", pid, "6.4", quote=w, start=at)
    w, at = words["note"]
    out["note"] = notes.add(ws, doc, at, at + len(w), w, text="Ask about this.")["note_id"]
    w, at = words["highlight"]
    out["highlight"] = notes.add(ws, doc, at, at + len(w), w)["note_id"]
    assert text == _text(ws, doc)
    return out


def _where(ws: Workspace, ids: dict) -> dict[str, tuple[int | None, int | None, str]]:
    """Where each piece of work is in the document now: (start, end, its words)."""
    j = ws.query("SELECT start, end, quote FROM judgements WHERE claim_id=?", (ids["cid"],))[0]
    lab = ws.query("SELECT start, end, quote FROM labels WHERE source='person'")[0]
    n = ws.query("SELECT start, end, quote FROM notes WHERE note_id=?", (ids["note"],))[0]
    h = ws.query("SELECT start, end, quote FROM notes WHERE note_id=?", (ids["highlight"],))[0]
    return {"judgement": tuple(j), "label": tuple(lab), "note": tuple(n), "highlight": tuple(h)}


# ---- (a) words the new reader keeps --------------------------------------------------------------------------------
def test_each_kind_of_work_on_words_the_new_reader_keeps_lands_on_the_same_words(paper):
    ws, doc = paper
    text = _text(ws)
    words = {"judgement": Q_JUDGE, "label": f"desalination at {SITES[10]} will cover",
             "note": f"Farmers near {SITES[30]} fear", "highlight": f"draw {120 + 7 * 33} cubic metres"}
    ids = _work(ws, doc, {k: (w, text.index(w)) for k, w in words.items()})
    rep = reread.move(ws, doc)
    new = _text(ws)
    assert not rep["not_placed"], rep["not_placed"]
    for kind, (a, b, q) in _where(ws, ids).items():
        assert a is not None and _same(new[a:b], words[kind]), kind
    v = ws.query("SELECT start, end FROM verifications WHERE quote=?", (Q_WATER,))[0]   # the check's own quote
    assert _same(new[v["start"]:v["end"]], Q_WATER)
    # the judgement and the label sit in the passage that holds their words
    j = ws.query("SELECT passage_id, start FROM judgements")[0]
    assert ws.scalar("SELECT COUNT(*) FROM passages WHERE passage_id=? AND start<=? AND end>?",
                     (j[0], j[1], j[1])) == 1
    lab = ws.query("SELECT passage_id, start FROM labels WHERE source='person'")[0]
    assert ws.scalar("SELECT COUNT(*) FROM passages WHERE passage_id=? AND start<=? AND end>?",
                     (lab[0], lab[1], lab[1])) == 1


# ---- (b) words said several times ----------------------------------------------------------------------------------
def test_each_kind_of_work_on_words_said_many_times_lands_on_the_same_occurrence(paper):
    """Every paragraph of the paper says REPEAT: each piece of work is on one occurrence in the middle of the
    document, and must land on that occurrence, not the first nearby."""
    ws, doc = paper
    text = _text(ws)
    hits = [m.start() for m in re.finditer(re.escape(REPEAT), text)]
    assert len(hits) >= 30
    # the judgement's passage must be one the check shows (the check shows those with "Farmers near ...")
    pick = {"judgement": hits[20], "label": hits[22], "note": hits[25], "highlight": hits[27]}
    ids = _work(ws, doc, {k: (REPEAT, at) for k, at in pick.items()})
    before = {k: _occurrence(text, REPEAT, a) for k, (a, _b, _q) in _where(ws, ids).items()}
    assert before == {k: hits.index(at) + 1 for k, at in pick.items()}
    rep = reread.move(ws, doc)
    new = _text(ws)
    assert not rep["not_placed"], rep["not_placed"]
    after = {k: _occurrence(new, new[a:b], a) for k, (a, b, _q) in _where(ws, ids).items()}
    assert after == before


# ---- (c) passages that change ------------------------------------------------------------------------------------
def _survey(folder: Path, name: str = "survey.txt", n: int = 40, seed: int = 5) -> Path:
    """Short answers, one per line, no blank lines: reader 6 reads them as one paragraph cut into a few long
    passages, reader 7 as a paragraph per line (several passages for each of reader 6's)."""
    rng = random.Random(seed)
    lines = []
    for i in range(n):
        s = f"Answer {i + 1}: " + _sentence(rng)
        lines.append(s[:150].rsplit(" ", 1)[0].rstrip(",.") + "." if len(s) > 150 else s)
    path = folder / name
    # bytes, so the file is the same on every system (write_text would make "\r\n" into "\r\r\n" on Windows)
    path.write_bytes(("\r\n".join(lines) + "\r\n").encode("utf-8"))
    return path


@pytest.fixture
def survey(tmp_path, monkeypatch):
    ws = Workspace.create(tmp_path / "ws")
    doc = _add(ws, monkeypatch, _survey(tmp_path), reader=6)
    return ws, doc


def test_work_across_passages_that_split_lands_on_the_same_words(survey):
    """Reader 6 to reader 7 for a text file of short answers one per line: each of reader 6's passages becomes three
    or four of reader 7's. A note spanning two of reader 6's passages, a label and a judgement in the middle of one,
    land on the same words, in the new passage that holds them."""
    ws, doc = survey
    text = _text(ws)
    old = ws.query("SELECT start, end FROM passages WHERE doc_id=? ORDER BY seq", (doc,))
    assert len(old) <= 8
    # a note across the boundary of the first two passages
    a, b = old[0]["end"] - 30, old[1]["start"] + 30
    a = text.rindex(" ", 0, a) + 1
    b = text.index(" ", b)
    span = text[a:b]
    n = notes.add(ws, doc, a, b, span, text="Across two passages.")["note_id"]
    mid = text[old[1]["start"]:old[1]["end"]]
    lw = mid[len(mid) // 2:][mid[len(mid) // 2:].index("Answer"):]
    lw = lw[:lw.index(".") + 1]
    lab = profile.add_label(ws, "sdg", f"{doc}:0001", "6.4", quote=lw, start=text.index(lw))
    pv = reread.preview(ws, doc)
    assert pv["passages"]["after"] >= 2 * pv["passages"]["before"], pv["passages"]
    rep = reread.move(ws, doc)
    assert not rep["not_placed"], rep["not_placed"]
    new = _text(ws)
    row = ws.query("SELECT start, end FROM notes WHERE note_id=?", (n,))[0]
    assert _same(new[row["start"]:row["end"]], span)
    lr = ws.query("SELECT * FROM labels WHERE source='person'")[0]
    assert _same(new[lr["start"]:lr["end"]], lw)
    p = ws.query("SELECT start, end FROM passages WHERE passage_id=?", (lr["passage_id"],))[0]
    assert p["start"] <= lr["start"] and lr["end"] <= p["end"] + 1
    assert lr["label_id"] == profile.label_id("sdg", lr["passage_id"], "6.4", "person") and lab != lr["label_id"]


def test_work_on_passages_that_become_one_lands_on_the_same_words_or_is_reported(survey, tmp_path):
    """Several passages become one: reader 7's reading of the answers placed back on reader 6's (a colleague still on
    reader 6: sync/readings.place_on, the way reread.py moves results). A note and two labels of different codes on
    two of reader 7's passages land on their words in reader 6's one passage; the same code on both can stand once on
    it, and the second is listed with its reason (never dropped without a word)."""
    import shutil

    from enlens_claims.sync import readings

    ws6, doc = survey
    ws6.close()
    shutil.copytree(ws6.root, tmp_path / "ws7")
    ws7 = Workspace(tmp_path / "ws7")
    reread.move(ws7, doc)
    text = _text(ws7)
    ps = ws7.query("SELECT passage_id, start, end, text FROM passages WHERE doc_id=? ORDER BY seq", (doc,))
    one, two = ps[1], ps[2]   # in one passage of reader 6's (its first holds answers 1 to 7 or so)
    q1, q2 = one["text"].split(".")[0] + ".", two["text"].split(".")[0] + "."
    profile.add_label(ws7, "sdg", one["passage_id"], "6.4", quote=q1, start=one["start"])
    profile.add_label(ws7, "sdg", two["passage_id"], "7.2", quote=q2, start=two["start"])
    profile.add_label(ws7, "sdg", one["passage_id"], "13.1", quote=q1, start=one["start"])
    profile.add_label(ws7, "sdg", two["passage_id"], "13.1", quote=q2, start=two["start"])
    a = text.index(q2)
    nid = notes.add(ws7, doc, a, a + len(q2), q2, text="Second answer.")["note_id"]
    # a note across the two passages (the end of the one, the start of the other): one passage of reader 6's
    s, e = text.rindex(" ", 0, one["end"] - 20) + 1, text.index(" ", two["start"] + 20)
    across = text[s:e]
    nid2 = notes.add(ws7, doc, s, e, across)["note_id"]
    ws7.close()
    with ws6.connect() as cx6, ws7.connect() as cx7:
        got = readings.place_on(ws7, cx7, doc, readings._Reading(cx6, doc, doc))
    old = _text(ws6)
    rows = {r["code"]: r for r in ws7.query("SELECT * FROM labels WHERE source='person'")}
    assert _same(old[rows["6.4"]["start"]:rows["6.4"]["end"]], q1) and _same(old[rows["7.2"]["start"]:rows["7.2"]["end"]], q2)
    assert rows["6.4"]["passage_id"] == rows["7.2"]["passage_id"]   # one passage now
    n = ws7.query("SELECT start, end FROM notes WHERE note_id=?", (nid,))[0]
    assert _same(old[n["start"]:n["end"]], q2) and got["notes_lost"] == 0
    n2 = ws7.query("SELECT start, end FROM notes WHERE note_id=?", (nid2,))[0]
    assert _same(old[n2["start"]:n2["end"]], across)
    assert ws6.scalar("SELECT COUNT(*) FROM passages WHERE doc_id=? AND start<=? AND end>=?",
                      (doc, n2["start"], n2["end"])) == 1   # in one passage now
    shared = ws7.query("SELECT * FROM labels WHERE code='13.1' ORDER BY start")
    assert len(shared) == 2 and sum(reread.is_tombstone(r["passage_id"]) for r in shared) == 1
    assert got["not_placed"] == 1   # listed: "Its passage now holds the same label already."


# ---- (d) words that are gone -------------------------------------------------------------------------------------
def test_work_on_words_the_new_reader_does_not_have_is_reported_and_points_at_no_other_words(paper):
    """A judgement's sentence, a label's quote, a note and a highlight on words that run across reader 1's running
    head and page number: no later reader has them in that order. Each is reported by the preview and by the move
    (none silently dropped), and none is attached to other words."""
    ws, doc = paper
    text = _text(ws)
    bad = _bad_words(text)
    at = text.index(bad)
    # the check must show that passage: grade it with its own words
    ids = {}
    cid = _check(ws, [(Q_WATER, "supports"), (bad, "supports")])[0]
    ids["cid"] = cid
    pid = ws.scalar("SELECT passage_id FROM passages WHERE start<=? AND end>?", (at, at))
    claimcheck.set_judgement(ws, cid, pid, "refutes", "Not here.", quote=bad)
    ids["label"] = profile.add_label(ws, "sdg", pid, "6.4", quote=bad, start=at)
    ids["note"] = notes.add(ws, doc, at, at + len(bad), bad, text="Odd words.")["note_id"]
    ids["highlight"] = notes.add(ws, doc, at, at + len(bad), bad, colour="green")["note_id"]
    pv = reread.preview(ws, doc)
    kinds = sorted(e["kind"] for e in pv["not_placed"])
    assert kinds.count("label") == 1 and kinds.count("check") == 1, kinds
    assert kinds.count("note") == 2, kinds   # the note and the highlight are the person's work too
    rep = reread.move(ws, doc)
    assert sorted(e["kind"] for e in rep["not_placed"]) == kinds
    assert rep["counts"]["note"] == {"moved": 0, "not_placed": 2, "left_out": 0}
    new = _text(ws)
    lab = ws.query("SELECT * FROM labels WHERE source='person'")[0]
    assert reread.is_tombstone(lab["passage_id"]) and lab["start"] is None
    j = ws.query("SELECT * FROM judgements")[0]
    assert j["start"] is None and j["verdict"] == "refutes" and j["note"] == "Not here."
    for nid in (ids["note"], ids["highlight"]):
        got = notes.get(ws, nid)
        assert got["lost"] and got["quote"] == bad
        assert not _same(new[got["start"]:got["end"]], bad)


def _note_ws(tmp_path, old_text: str) -> tuple[Workspace, str]:
    ws = Workspace.create(tmp_path / "ws")
    with ws.connect() as cx:
        cx.execute("INSERT INTO documents(doc_id, title, text, n_chars, reader) VALUES ('dn', 'Notes', ?, ?, 1)",
                   (old_text, len(old_text)))
    return ws, "dn"


_PARA = [f"Sentence number {w} of the report talks about hydrogen and water in a dry place." for w in
         ("one", "two", "three", "four", "five", "six", "seven", "eight")]
_WORDS = "the plant will double its output"


def test_a_note_whose_words_are_gone_from_their_place_is_not_attached_to_the_same_words_elsewhere(tmp_path):
    """A passage reader 1 garbled ("Qzx vbn the plant will double its output qwp zzx"): the new reading has none of
    it there, and says the same words only in a summary at the end. The note on them has no place (as a check's quote
    has none: `_Map.place`), and is never put on the summary's words: neither by the move nor when shown later
    (notes._placed looked near its old place and then ANYWHERE in the text)."""
    old_text = " ".join(_PARA[:4]) + f" Qzx vbn {_WORDS} qwp zzx. " + " ".join(_PARA[4:])
    far = " ".join(_PARA) + " " + "Filler sentence about something else entirely, said again. " * 80
    new_text = far + f"In the summary, {_WORDS} by the end of the decade."
    a = old_text.index(_WORDS)
    assert new_text.index(_WORDS) - a > 3500
    cut = len(" ".join(_PARA[:4])) + 1
    old = [reread._P("dn:0000", 0, 0, cut - 1, old_text[:cut - 1], "body", None),
           reread._P("dn:0001", 1, cut, cut + 50, old_text[cut:cut + 50], "body", None),
           reread._P("dn:0002", 2, cut + 51, len(old_text), old_text[cut + 51:], "body", None)]
    m = reread._Map(old_text, old, new_text, [reread._P("dn:0000", 0, 0, len(new_text), new_text, "body", None)],
                    [(0, len(new_text))], True)
    p = m.old_at(a)
    assert p.pid == "dn:0001" and m.place(_WORDS, a, p.pid) is None   # what `_plan` gives the note: no place
    ws, doc = _note_ws(tmp_path, old_text)
    nid = notes.add(ws, doc, a, a + len(_WORDS), _WORDS, text="Where?")["note_id"]
    with ws.connect() as cx:
        moved = notes.move(cx, doc, new_text, placed={nid: None})
        cx.execute("UPDATE documents SET text=? WHERE doc_id=?", (new_text, doc))
    assert moved == {"moved": 0, "lost": 1}
    got = notes.get(ws, nid)   # shown later: still without a place, not found again elsewhere
    assert got["lost"] and got["quote"] == _WORDS and got["text"] == "Where?"
    assert ws.scalar("SELECT start FROM notes WHERE note_id=?", (nid,)) != new_text.index(_WORDS)


def test_a_note_shown_after_its_text_changed_is_looked_for_near_its_place_only(tmp_path):
    """notes._placed (every list of notes) finds a note's words again when the text under it changed: near its place,
    then anywhere. A note whose words went from there was put on the same words far away, in the summary."""
    old_text = " ".join(_PARA[:4]) + f" Qzx vbn {_WORDS} qwp zzx. " + " ".join(_PARA[4:])
    new_text = (" ".join(_PARA) + " " + "Filler sentence about something else entirely, said again. " * 80
                + f"In the summary, {_WORDS} by the end of the decade.")
    ws, doc = _note_ws(tmp_path, old_text)
    a = old_text.index(_WORDS)
    nid = notes.add(ws, doc, a, a + len(_WORDS), _WORDS)["note_id"]
    with ws.connect() as cx:   # the text changes under the note (a note kept from before its words moved)
        cx.execute("UPDATE documents SET text=? WHERE doc_id=?", (new_text, doc))
    got = notes.get(ws, nid)
    assert got["lost"] and got["start"] == a


# ---- the preview against the move ----------------------------------------------------------------------------------
def test_the_preview_says_what_the_move_then_does(paper):
    ws, doc = paper
    text = _text(ws)
    bad = _bad_words(text)
    words = {"judgement": Q_JUDGE, "label": f"desalination at {SITES[10]} will cover",
             "note": f"Farmers near {SITES[30]} fear", "highlight": bad}
    _work(ws, doc, {k: (w, text.index(w)) for k, w in words.items()})
    pv = reread.preview(ws, doc)
    rep = reread.move(ws, doc)
    assert rep["counts"] == pv["counts"]
    assert [(e["kind"], e["quote"]) for e in rep["not_placed"]] == [(e["kind"], e["quote"]) for e in pv["not_placed"]]
    assert rep["tasks"] == pv["tasks"] and rep["passages"] == pv["passages"]
    assert pv["counts"]["note"] == {"moved": 1, "not_placed": 1, "left_out": 0}
    # what the log says matches
    log = ws.meta(f"read_again:{doc}")[-1]
    assert log["not_placed"] == len(rep["not_placed"]) and log["counts"] == rep["counts"]


# ---- failing, stopping, twice -------------------------------------------------------------------------------------
def test_a_move_stopped_while_the_file_is_read_leaves_the_old_reading_whole(paper):
    ws, doc = paper
    text = _text(ws)
    _work(ws, doc, {"judgement": (Q_JUDGE, text.index(Q_JUDGE)), "label": (Q_DESAL, text.index(Q_DESAL)),
                    "note": (Q_WATER, text.index(Q_WATER)), "highlight": (REPEAT, text.index(REPEAT))})
    reread._READINGS.clear()
    before = _dump(ws)
    asked = []

    def stop() -> bool:   # Stop pressed once the file has been read (a text layer: no page is recognised)
        asked.append(1)
        return True

    with pytest.raises(ingest.Stopped):
        reread.move(ws, doc, should_stop=stop)
    assert asked and _dump(ws) == before
    assert ws.scalar("SELECT reader FROM documents") == 1


def test_a_move_that_fails_after_the_notes_moved_leaves_the_old_reading_whole(paper, monkeypatch):
    ws, doc = paper
    text = _text(ws)
    _work(ws, doc, {"judgement": (Q_JUDGE, text.index(Q_JUDGE)), "label": (Q_DESAL, text.index(Q_DESAL)),
                    "note": (Q_WATER, text.index(Q_WATER)), "highlight": (REPEAT, text.index(REPEAT))})
    before = _dump(ws)
    from enlens_claims import researchlog

    def broken(*a, **k):
        raise RuntimeError("the disk is full")

    monkeypatch.setattr(researchlog, "record", broken)   # the very last write of the move
    with pytest.raises(RuntimeError, match="disk is full"):
        reread.move(ws, doc)
    assert _dump(ws) == before


def test_the_same_move_twice_equals_once(paper):
    ws, doc = paper
    text = _text(ws)
    ids = _work(ws, doc, {"judgement": (Q_JUDGE, text.index(Q_JUDGE)), "label": (Q_DESAL, text.index(Q_DESAL)),
                          "note": (Q_WATER, text.index(Q_WATER)), "highlight": (REPEAT, text.index(REPEAT))})
    reread.move(ws, doc)
    once = _dump(ws)
    where = _where(ws, ids)
    assert not reread.check(ws, doc)["ok"]
    with pytest.raises(ValueError, match="current reader already"):
        reread.move(ws, doc)
    assert not reread.preview(ws, doc)["ok"]
    assert _dump(ws) == once and _where(ws, ids) == where


# ---- a run of the document under way ---------------------------------------------------------------------------------
def test_a_label_run_under_way_when_the_document_is_moved_ends_well_and_labels_the_right_words(paper):
    """A run of labels by a cloud model holds no claim on its tasks while the model reads (only the local model and
    Claude Code claim theirs), so a move can come in between (a round of the shared folder moves an accepted reading
    while the run goes on). The run must not fail on the tasks the move asked again, and no label of the run may name
    a passage of the new reading with words other than those it was given."""
    from enlens_claims.llm import BaselineBackend

    ws, doc = paper
    pids = [r[0] for r in ws.query("SELECT passage_id FROM passages WHERE doc_id=? AND section='body' ORDER BY seq "
                                   "LIMIT 6", (doc,))]
    shown: dict[str, str] = {}

    class MovesMidway(BaselineBackend):
        moved = False

        def complete(self, kind, system, user, model, payload):
            if kind == "label":
                shown[payload["passage_id"]] = payload["text"]
            if kind == "label" and not self.moved:
                self.moved = True
                reread.move(ws, doc)
            return super().complete(kind, system, user, model, payload)

    out = profile.run_labels(ws, "sdg", MovesMidway(), "baseline", passage_ids=pids, all_passages=True)
    assert ws.scalar("SELECT reader FROM documents") == ingest.READER
    for lab in ws.query("SELECT * FROM labels WHERE source='model'"):
        p = ws.query("SELECT text FROM passages WHERE passage_id=?", (lab["passage_id"],))
        if not p:
            assert reread.is_tombstone(lab["passage_id"])
            continue
        if lab["quote"]:   # its quote is words of the passage it names now, at its offsets
            assert reread._packed(lab["quote"]) in reread._packed(p[0][0])
            if lab["start"] is not None:
                assert _same(_text(ws)[lab["start"]:lab["end"]], lab["quote"])
    assert out["read"] + out["failed"] + out["skipped_restricted"] <= len(pids)


def _moving_backend(ws: Workspace, doc: str, kind: str):
    """The offline model, which moves the document to the new reader while it reads its first task of `kind`."""
    from enlens_claims.llm import BaselineBackend

    class MovesMidway(BaselineBackend):
        moved = False

        def complete(self, k, system, user, model, payload):
            if k == kind and not self.moved:
                self.moved = True
                reread.move(ws, doc)
            return super().complete(k, system, user, model, payload)

    return MovesMidway()


def test_an_excerpt_read_again_while_its_document_is_moved_says_so_in_words(paper):
    """Sibling of the label run: *Read again* of one excerpt (judgements.reread_excerpt) whose document is moved while
    the AI reads it. Its task names the old passage, and the move asks it again: the AI's answer must not be stored
    for the old passage id, and the person is told what happened, in words (not "unknown task …")."""
    from enlens_claims import judgements

    ws, doc = paper
    cid, at = _check(ws, [(Q_WATER, "supports")])
    pid = at[Q_WATER]
    before = ws.query("SELECT verdict, quote FROM verifications WHERE subject_id=? AND quote=?", (cid, Q_WATER))
    with pytest.raises(ValueError, match="new reader"):
        judgements.reread_excerpt(ws, cid, pid, _moving_backend(ws, doc, "reread"), "baseline")
    assert ws.scalar("SELECT reader FROM documents") == ingest.READER
    after = ws.query("SELECT verdict, quote FROM verifications WHERE subject_id=? AND quote=?", (cid, Q_WATER))
    assert [tuple(r) for r in after] == [tuple(r) for r in before]   # the judgement moved, unchanged
    assert not ws.query("SELECT 1 FROM tasks WHERE kind='reread' AND task_id LIKE ?", (f"reread:{cid}:{pid}:%",))


def test_following_references_while_the_document_is_moved_ends_without_failing(paper):
    """Sibling: following a document's references window by window (references.resolve_document) while it is moved:
    the windows' tasks are asked again by the move; the run ends and says how many it read."""
    from enlens_claims import references

    ws, doc = paper
    out = references.resolve_document(ws, doc, _moving_backend(ws, doc, "resolve"), "baseline")
    assert ws.scalar("SELECT reader FROM documents") == ingest.READER
    assert out["doc_id"] == doc and out["read_again_meanwhile"] == out["windows"] - out["already_read"] - out["read"] \
        - out["failed"] and out["read_again_meanwhile"] >= 1
    # nothing of the reading before is left to name a window of the new one
    assert not ws.query("SELECT 1 FROM mentions WHERE doc_id=?", (doc,))


def test_a_checks_answer_that_arrives_after_the_move_is_placed_on_the_same_words(paper):
    """A check's round sent to a model before the move, answered after it (the task holds no claim while a cloud
    model reads): its quote lands on the words the model quoted, in the new text."""
    from enlens_claims import tasks

    ws, doc = paper
    r = claimcheck.open_check(ws, "Hydrogen plants need water in arid regions", terms=["hydrogen", "water"], k=60,
                              per_doc=60)
    tid = f"check:{r['check_id']}"
    pay = json.loads(ws.scalar("SELECT payload_json FROM tasks WHERE task_id=?", (tid,)))["passages"]
    n = next(i for i, p in enumerate(pay, 1) if Q_WATER in p["text"])
    reread.move(ws, doc)   # meanwhile
    ok, errs = tasks.ingest_result(ws, tid, {"evidence": [{"passage": n, "verdict": "supports", "confidence": 0.9,
                                                           "quote": Q_WATER}], "rationale": "Read."}, model="m")
    assert ok, errs
    v = ws.query("SELECT * FROM verifications WHERE quote=?", (Q_WATER,))[0]
    new = _text(ws)
    assert v["start"] is not None and _same(new[v["start"]:v["end"]], Q_WATER)
    # what the person sees: the excerpt as it was shown, the highlight on the quote, the way into the document on
    # the quoted words, on their page
    it = next(x for x in claimcheck.result(ws, r["check_id"])["passages"] if x["quote"] == Q_WATER)
    assert it["text"][it["quote_start"]:it["quote_end"]] == Q_WATER and it["counted"]
    assert _same(new[it["doc_start"] + it["quote_start"]:it["doc_start"] + it["quote_end"]], Q_WATER)
    spans = [(r_[0], r_[1]) for r_ in ws.query("SELECT start, end FROM pages WHERE doc_id=? ORDER BY page", (doc,))]
    assert it["location"].startswith(f"page {ingest.page_of(v['start'], spans)}"), it["location"]


# ---- a document in a team; moving back --------------------------------------------------------------------------------
def test_a_colleagues_work_on_the_newer_reading_lands_on_the_older_one_and_moving_forward_again_equals_theirs(
        paper_shared):
    """Moving back: Ben moves the paper to the new reader and works on it (a judgement, a label, a note on a page);
    Anna still has reader 1's reading. On her copy everything of his lands on the same words of her older reading,
    nothing lost, the note on its page there. When Anna then moves to the new reader herself, each lands where it is
    in Ben's copy."""
    anna, ben = paper_shared
    with ben:
        reread.move(ben.ws, anna.doc)
        text = _text(ben.ws, anna.doc)
        cid2, _ = _check(ben.ws, [(Q_DESAL, "refutes")])
        lab = profile.add_label(ben.ws, "sdg", _pid_with(ben.ws, Q_JUDGE), "6.4", quote=Q_JUDGE,
                                start=text.index(Q_JUDGE))
        a = [m.start() for m in re.finditer(re.escape(REPEAT), text)][-3]   # late in the paper, a page after the first
        nid = notes.add(ben.ws, anna.doc, a, a + len(REPEAT), text="His note.")["note_id"]
        bn = ben.ws.query("SELECT start, end, page, quote FROM notes WHERE note_id=?", (nid,))[0]
        assert bn["page"] and bn["page"] > 1
        b_lab = ben.ws.query("SELECT start, end FROM labels WHERE label_id=?", (lab,))[0]
        b_ver = ben.ws.query("SELECT start, end FROM verifications WHERE quote=?", (Q_DESAL,))[0]
    rep = anna.bring_in(ben.send())
    other = rep["documents"]["other_reading"]
    # (excerpts a check showed and nobody graded: several of the new reading's fall in one of reader 1's longer
    # passages, and one passage holds one excerpt of a check: the others are kept as records, as reread.py keeps them)
    assert len(other) == 1 and other[0]["notes_lost"] == 0, other
    with anna:
        old = _text(anna.ws, anna.doc)
        assert anna.ws.scalar("SELECT reader FROM documents") == 1
        n = anna.ws.query("SELECT start, end, page, quote FROM notes WHERE note_id=?", (nid,))[0]
        assert _same(old[n["start"]:n["end"]], bn["quote"])
        page = ingest.page_of(n["start"], [(r[0], r[1]) for r in anna.ws.query(
            "SELECT start, end FROM pages WHERE doc_id=? ORDER BY page", (anna.doc,))])
        assert n["page"] == page, (n["page"], page)
        lr = anna.ws.query("SELECT * FROM labels WHERE source='person'")
        assert len(lr) == 1 and _same(old[lr[0]["start"]:lr[0]["end"]], Q_JUDGE)
        v = anna.ws.query("SELECT * FROM verifications WHERE quote=?", (Q_DESAL,))[0]
        assert _same(old[v["start"]:v["end"]], Q_DESAL)
        # forward again, on Anna's copy: the same places as Ben's
        reread.move(anna.ws, anna.doc)
        assert _text(anna.ws, anna.doc) == text
        n2 = anna.ws.query("SELECT start, end, page FROM notes WHERE note_id=?", (nid,))[0]
        assert (n2["start"], n2["end"], n2["page"]) == (bn["start"], bn["end"], bn["page"])
        lr2 = anna.ws.query("SELECT start, end FROM labels WHERE source='person'")[0]
        assert tuple(lr2) == tuple(b_lab)
        v2 = anna.ws.query("SELECT start, end FROM verifications WHERE quote=?", (Q_DESAL,))[0]
        assert tuple(v2) == tuple(b_ver)


def test_a_colleagues_note_on_their_older_reading_lands_on_your_newer_reading_with_its_page(paper_shared):
    anna, ben = paper_shared
    with ben:
        reread.move(ben.ws, anna.doc)
        new = _text(ben.ws, anna.doc)
    with anna:
        old = _text(anna.ws, anna.doc)
        a = [m.start() for m in re.finditer(re.escape(REPEAT), old)][-3]
        nid = notes.add(anna.ws, anna.doc, a, a + len(REPEAT), text="Her note.")["note_id"]
    ben.bring_in(anna.send())
    with ben:
        n = ben.ws.query("SELECT start, end, page, quote FROM notes WHERE note_id=?", (nid,))[0]
        assert _same(new[n["start"]:n["end"]], n["quote"])
        page = ingest.page_of(n["start"], [(r[0], r[1]) for r in ben.ws.query(
            "SELECT start, end FROM pages WHERE doc_id=? ORDER BY page", (anna.doc,))])
        assert page and n["page"] == page, (n["page"], page)


# ---- blocks left out ----------------------------------------------------------------------------------------------
def _leave_out(ws: Workspace, doc: str, n: int) -> None:
    """*Leave out* on block n, as the app keeps it (gui/server.py set_block: by the block's words)."""
    text = _text(ws, doc)
    s, e, kind = ws.query("SELECT start, end, kind FROM blocks WHERE doc_id=? AND n=?", (doc, n))[0]
    with ws.connect() as cx:
        cx.execute("INSERT OR REPLACE INTO block_choices(doc_id, fp, included, kind, person_id, at) VALUES "
                   "(?,?,0,?,'me','x')", (doc, reader2.block_fp(text[s:e]), kind))
        reader2.apply_choices(cx, doc)


def test_a_block_left_out_whose_text_the_new_reader_cuts_otherwise_stays_left_out(survey):
    """Reader 6 read the answers as one block; the person left it out (*Leave out*: kept by the block's words). Reader
    7 reads each answer as a block of its own: none has the old block's words, so the choice applied to nothing and
    the answers counted again, without a word. Each block of the old one's text stays left out (or is reported)."""
    ws, doc = survey
    blocks = ws.query("SELECT n, start, end, kind, included FROM blocks WHERE doc_id=? ORDER BY n", (doc,))
    big = max(blocks, key=lambda b: b["end"] - b["start"])
    _leave_out(ws, doc, big["n"])
    assert ws.scalar("SELECT COUNT(*) FROM passages WHERE doc_id=? AND section='body'", (doc,)) == 0 or \
        ws.scalar("SELECT included FROM blocks WHERE doc_id=? AND n=?", (doc, big["n"])) == 0
    old_text = _text(ws)
    words = old_text[big["start"]:big["end"]]
    pv = reread.preview(ws, doc)
    rep = reread.move(ws, doc)
    new = _text(ws)
    inside = [b for b in ws.query("SELECT * FROM blocks WHERE doc_id=? ORDER BY n", (doc,))
              if reread._packed(new[b["start"]:b["end"]]) in reread._packed(words)]
    assert len(inside) >= 10
    left = [b["included"] for b in inside]
    reported = [e for e in rep["not_placed"] if e["kind"] == "block"]
    assert all(x == 0 for x in left) or reported, left
    assert [e["kind"] for e in pv["not_placed"]] == [e["kind"] for e in rep["not_placed"]]


def test_a_block_left_out_whose_words_the_new_reader_changes_stays_left_out_or_is_reported(tmp_path, monkeypatch):
    """A Word paragraph holding a text box: reader 6 read the box twice, joined to the paragraph's last word; reader 7
    reads it once, as a paragraph of its own. The person left that paragraph out: its words change, so no block of
    the new reading has them. The paragraph and the box stay left out, or the choice is reported."""
    from test_hunt1_readers import _p, _text_box, _word

    rng = random.Random(3)
    path = _word(tmp_path / "boxed.docx", "".join(_p(_sentence(rng)) for _ in range(4))
                 + _text_box("Forty wells ran dry in the boxed summary of the year.")
                 + "".join(_p(_sentence(rng)) for _ in range(4)))
    ws = Workspace.create(tmp_path / "ws")
    doc = _add(ws, monkeypatch, path, reader=6)
    text = _text(ws)
    n = next(r["n"] for r in ws.query("SELECT n, start, end FROM blocks WHERE doc_id=? ORDER BY n", (doc,))
             if "holds the box" in text[r["start"]:r["end"]])
    _leave_out(ws, doc, n)
    pv = reread.preview(ws, doc)
    rep = reread.move(ws, doc)
    new = _text(ws)
    held = [b for b in ws.query("SELECT * FROM blocks WHERE doc_id=? ORDER BY n", (doc,))
            if "holds the box" in new[b["start"]:b["end"]] or "Forty wells" in new[b["start"]:b["end"]]]
    assert held
    reported = [e for e in rep["not_placed"] if e["kind"] == "block"]
    assert all(b["included"] == 0 for b in held) or reported, [(new[b["start"]:b["end"]], b["included"]) for b in held]
    assert pv["counts"].get("block") == rep["counts"].get("block") == {"moved": 1, "not_placed": 0, "left_out": 0}


def test_a_text_starts_here_mark_on_a_block_the_new_reader_cuts_otherwise_holds(survey):
    """*Text starts here* is kept by its block's words too: on a block the new reader cuts into several, the mark
    found no block and everything before it counted again."""
    ws, doc = survey
    # reader 6 reads the survey as two blocks (its first line, then the rest): the text starts at the second
    blocks = ws.query("SELECT n, start, end FROM blocks WHERE doc_id=? ORDER BY n", (doc,))
    assert len(blocks) == 2
    text = _text(ws)
    fps = [reader2.block_fp(text[b["start"]:b["end"]]) for b in blocks]
    i = len(blocks) - 1
    with ws.connect() as cx:
        cx.execute("INSERT INTO block_choices(doc_id, fp, included, kind, person_id, at) VALUES (?,?,0,'bound','me','x')",
                   (doc, reader2.bound_key("start", fps, i)))
        reader2.apply_choices(cx, doc)
    first = blocks[i]["start"]
    before_out = [b["n"] for b in ws.query("SELECT n, included, end FROM blocks WHERE doc_id=? ORDER BY n", (doc,))
                  if not b["included"]]
    rep = reread.move(ws, doc)
    new = _text(ws)
    head = reread._packed(text[:first])
    after = ws.query("SELECT n, start, end, included FROM blocks WHERE doc_id=? ORDER BY n", (doc,))
    out_now = [b for b in after if reread._packed(new[b["start"]:b["end"]]) and
               reread._packed(new[b["start"]:b["end"]]) in head]
    reported = [e for e in rep["not_placed"] if e["kind"] == "block"]
    assert before_out and (all(not b["included"] for b in out_now) or reported)


# ---- round 2: Windows CI, and the review of wave 5 -------------------------------------------------------------------
def _shapes() -> dict[str, str]:
    """Text files of the shapes the readers' line rules look at: short answers one per line (readers 4 and 7), long
    paragraphs between blank lines, text wrapped at 70 characters (reader 3), an interview with a line that comes back
    (readers 3 and 7), sentences one per line with blank lines between paragraphs."""
    import textwrap

    rng = random.Random(5)
    lines = []
    for i in range(40):
        s = f"Answer {i + 1}: " + _sentence(rng)
        lines.append(s[:150].rsplit(" ", 1)[0].rstrip(",.") + "." if len(s) > 150 else s)
    paras = [" ".join(_sentence(rng) for _ in range(5)) for _ in range(8)]
    turns = []
    for i in range(60):
        if i % 12 == 0:
            turns.append("Interview 3 - confidential draft")
        turns.append(f"Speaker {i % 2}: We answered the question number {i} as well as we could at the time.")
    return {"lines": "\n".join(lines) + "\n", "paras": "\n\n".join(paras) + "\n",
            "wrapped": "\n\n".join("\n".join(textwrap.wrap(p, 70)) for p in paras) + "\n",
            "interview": "\n\n".join(turns) + "\n",
            "sentence_lines": "\n\n".join("\n".join(_sentence(rng) for _ in range(4)) for _ in range(6)) + "\n"}


@pytest.mark.parametrize("reader", [1, 2, 3, 4, 5, 6, 7])
def test_a_text_file_with_windows_line_ends_reads_as_the_same_file_with_unix_ones(tmp_path, reader):
    """Windows CI cut the survey into other blocks than macOS: was ENLENS reading a text file made on Windows (line
    ends "\\r\\n") otherwise than the same text with "\\n"? Every reader, every shape of text, written as bytes: the
    same text, paragraphs, blocks and passages with "\\n", "\\r\\n" and "\\r" (old Mac files). (The CI difference was the
    test's own: `write_text` of "\\r\\n" writes "\\r\\r\\n" on Windows, a blank line between every two lines.)"""
    for name, text in _shapes().items():
        got = {}
        for eol in ("\n", "\r\n", "\r"):
            p = tmp_path / f"{name}.txt"
            p.write_bytes(text.replace("\n", eol).encode("utf-8"))
            d = ingest.read_document(p, reader=reader, ocr=OFF)
            got[eol] = (d.text, [(q.start, q.end, q.section) for q in d.passages],
                        [(b.start, b.end, b.kind) for b in (getattr(d, "blocks", None) or [])])
        assert got["\r\n"] == got["\n"] == got["\r"], (name, reader)


def test_a_failure_inside_read_again_leaves_no_half_answered_task(paper, monkeypatch):
    """Review wave 5 (REREAD15-21): a KeyError from inside `tasks.run_one` while the task is still there skipped the
    clean-up, leaving `reread:<claim>:<passage>:1` behind; the next *Read again* numbered itself 2 beside it."""
    from enlens_claims import judgements, tasks
    from enlens_claims.llm import BaselineBackend

    ws, doc = paper
    cid, at = _check(ws, [(Q_WATER, "supports")])
    pid = at[Q_WATER]

    def broken(*a, **k):
        raise KeyError("a lookup inside the run")

    with monkeypatch.context() as mp:
        mp.setattr(tasks, "run_one", broken)
        with pytest.raises(KeyError, match="lookup inside"):
            judgements.reread_excerpt(ws, cid, pid, BaselineBackend(), "baseline")
    assert not ws.query("SELECT 1 FROM tasks WHERE task_id LIKE ?", (f"reread:{cid}:{pid}:%",))
    judgements.reread_excerpt(ws, cid, pid, BaselineBackend(), "baseline")
    assert [r[0] for r in ws.query("SELECT task_id FROM tasks WHERE task_id LIKE ?", (f"reread:{cid}:{pid}:%",))] \
        == [f"reread:{cid}:{pid}:1"]


def test_the_earlier_reading_is_kept_as_the_manual_says_and_no_way_back_is_promised(paper):
    """Review wave 5 (REREAD15-17): the rule's "moving back to the earlier reading" against the documents. Nothing
    offers it: the manual says a copy keeps the reading it has, a colleague's copy keeps theirs, and an owner's
    accept taken back leaves a new reading that "cannot go back" in the copy that made it. What it says is kept: the
    earlier reading's fingerprint (so a colleague still on it is known as the same document) and each check's
    excerpt as it was shown."""
    from enlens_claims.sync import text_fp

    root = Path(__file__).resolve().parent.parent
    manual = {n: " ".join((root / "docs/manual" / n).read_text("utf-8").split())
              for n in ("reading.md", "roles.md", "how-two-copies-come-together.md")}
    assert "A document read by an older reader keeps that reading" in manual["reading.md"]
    assert "each copy keeps the reading it has" in manual["reading.md"]
    assert "A new reading that cannot go back stays in the copy that made it" in manual["roles.md"]
    assert "Each of you keeps the reading you have" in manual["how-two-copies-come-together.md"]
    ws, doc = paper
    old = _text(ws)
    cid = _check(ws, [(Q_WATER, "supports")])[0]
    reread.move(ws, doc)
    assert text_fp(old) in json.loads(ws.scalar("SELECT old_fps FROM documents"))
    it = next(x for x in claimcheck.result(ws, cid)["passages"] if x["quote"] == Q_WATER)
    assert it["earlier_reading"] and it["earlier_reader"] == 1 and it["text"] in old
    c = reread.check(ws, doc)
    assert not c["ok"] and "already" in c["reason"]   # the only move is forward


def _block_plan(tmp_path, old_text: str, old_cuts: list[tuple[int, int]], new_text: str,
                new_cuts: list[tuple[int, int]], left: int):
    """`_carry_choices` on a made-up pair of readings: blocks (and a passage each) at `old_cuts` and `new_cuts`, the
    person's *Leave out* on old block `left`."""
    from types import SimpleNamespace

    ws = Workspace.create(tmp_path / "wsb")
    with ws.connect() as cx:
        cx.execute("INSERT INTO documents(doc_id, title, text, n_chars, reader) VALUES ('db', 'B', ?, ?, 6)",
                   (old_text, len(old_text)))
        for n, (a, b) in enumerate(old_cuts):
            cx.execute("INSERT INTO blocks(doc_id, n, start, end, kind, included) VALUES ('db', ?, ?, ?, 'body', ?)",
                       (n, a, b, 0 if n == left else 1))
        a, b = old_cuts[left]
        cx.execute("INSERT INTO block_choices(doc_id, fp, included, kind, person_id, at) VALUES ('db', ?, 0, 'body', "
                   "'me', 'x')", (reader2.block_fp(old_text[a:b]),))
    old = [reread._P(f"db:{n:04d}", n, a, b, old_text[a:b], "body", None) for n, (a, b) in enumerate(old_cuts)]
    new = [reread._P(f"db:{n:04d}", n, a, b, new_text[a:b], "body", None) for n, (a, b) in enumerate(new_cuts)]
    m = reread._Map(old_text, old, new_text, new, [], False)
    plan, choices = reread._Plan(), {r[0]: r[1] for r in ws.query("SELECT fp, included FROM block_choices")}
    blocks = [SimpleNamespace(start=a, end=b, kind="body") for a, b in new_cuts]
    reread._carry_choices(ws._conn(), "db", m, new_text, blocks, choices, plan, lambda *a: None)
    out = [choices.get(reader2.block_fp(new_text[a:b])) for a, b in new_cuts]
    return plan, out


def _joined(parts: list[str]) -> tuple[str, list[tuple[int, int]]]:
    text, cuts = "", []
    for p in parts:
        cuts.append((len(text), len(text) + len(p)))
        text += p + "\n\n"
    return text, cuts


def test_a_left_out_block_whose_sentence_moved_far_does_not_leave_out_the_blocks_between(tmp_path):
    """Review wave 5 note (a): a left-out block whose words are not found whole took the span from its first to its
    last sentence found; one sentence now far away (a box the new reader puts at the end) stretched it over every
    block between, all then left out."""
    s = [f"The left out paragraph says sentence number {w} about the wells in the dry valley." for w in
         ("one", "two", "three", "four")]
    others = [f"Another paragraph, number {i}, talks about the harvest and the market in the town." for i in range(8)]
    old_text, old_cuts = _joined(others[:2] + [" ".join(s)] + others[2:])
    new_text, new_cuts = _joined(others[:2] + [" ".join(s[:3]) + " Plus words the old reader did not have."]
                                 + others[2:] + [s[3]])
    plan, out = _block_plan(tmp_path, old_text, old_cuts, new_text, new_cuts, left=2)
    assert out[2] == 0                       # the paragraph that holds most of it stays left out
    assert all(x is None for x in out[3:9])  # the blocks between are not touched
    assert not plan.not_placed


def test_a_left_out_block_whose_text_the_new_reader_no_longer_has_is_settled_not_lost(tmp_path):
    """Review wave 5 note (b): a *Leave out* of text the new reading does not have at all left nothing to leave out,
    yet counted as a result with no place, so *Move the ones that move cleanly* kept the document back."""
    others = [f"Another paragraph, number {i}, talks about the harvest and the market in the town." for i in range(6)]
    gone = "Zqx vbn wqp mmr lkj the garbled block an older reader made of a figure's labels, nnz."
    old_text, old_cuts = _joined(others[:3] + [gone] + others[3:])
    new_text, new_cuts = _joined(others)
    plan, out = _block_plan(tmp_path, old_text, old_cuts, new_text, new_cuts, left=3)
    assert not plan.not_placed and plan.counts["block"].get("settled") == 1
    assert all(x is None for x in out)


def test_a_note_without_a_place_cites_no_page_in_the_exports(paper):
    """Review wave 5 note (d): a note the move left without a place kept the earlier reading's page, and the notes
    export cited it as this reading's."""
    ws, doc = paper
    text = _text(ws)
    bad = _bad_words(text)
    at = text.index(bad)
    nid = notes.add(ws, doc, at, at + len(bad), bad, text="Odd words.")["note_id"]
    assert ws.scalar("SELECT page FROM notes WHERE note_id=?", (nid,)) == 2
    reread.move(ws, doc)
    assert ws.scalar("SELECT page FROM notes WHERE note_id=?", (nid,)) is None
    md = notes.markdown(ws, "Study")
    line = next(x for x in md.splitlines() if x.startswith("- ") and "45-67" in x)
    assert line.startswith("- (place lost) >") and "p. 2" not in line
    row = next(r for r in notes.table(ws) if r["Words"] == bad)
    assert row["Page"] == "" and row["Found in the text now"] == "no"


VIEWS = r"""
await scenario("profile: a label run that met a document read again says so", async (t) => {
  t.state({ settings: { backend: "claude_code" } });
  t.answer("GET /api/projects/Study/profile/plan?*", { passages: 10, with_candidates: 6, already_read: 0, to_read: 6, run: { now: { model: "haiku" }, changed: [] } });
  t.answer("GET /api/jobs/jl", { id: "jl", kind: "label", state: "done", progress: {}, result: { read: 4, changes: {}, read_again_meanwhile: 2 } });
  const m = await t.module("views/profile.js");
  const card = m.aiLabelCard({ project: "Study", framework: "sdg", watchers: [] });
  document.getElementById("view").appendChild(card.el);
  await t.settle(10);
  card.follow("jl");
  await t.settle(3000);
  return t.toasts().filter((x) => x.startsWith("The AI read"));
});
await scenario("references: a run that met a document read again says so", async (t) => {
  t.state({ settings: { backend: "claude_code" } });
  t.answer("GET /api/projects/Study/documents/d1/references", { status: { windows_total: 5, windows_read: 0 }, chains: [] });
  t.answer("POST /api/projects/Study/documents/d1/references", { job: { id: "jr" } });
  t.answer("GET /api/jobs/jr", { id: "jr", state: "done", progress: {}, result: { windows: 5, read: 1, failed: 0, already_read: 0, chains: 0, read_again_meanwhile: 4 } });
  const m = await t.module("views/doc-lookup.js");
  const panel = m.refsPanel({ docBase: "/api/projects/Study/documents/d1", paint: () => {}, project: "Study", docId: "d1", watchers: [], jumpTo: () => {}, tab: "refs" });
  document.getElementById("view").appendChild(panel.el || panel);
  await t.settle(10);
  await t.click("Follow the references in this document");
  await t.settle(3000);
  return t.toasts().filter((x) => x.startsWith("The AI read"));
});
const DOC = "/api/projects/Study/documents/d1";
await scenario("document page: the preview and the toast name notes and blocks as what they are", async (t) => {
  t.state({ settings: {} });
  t.answer(`GET ${DOC}?*`, { doc_id: "d1", title: "Report", file: "report.txt", kind: "text", total_blocks: 1, reader: 6, new_reader: 7,
    new_reader_changes: true, reading: { reader: 6, quality: "good" },
    blocks: [{ n: 0, kind: "body", text: "The wells ran dry in the summer.", start: 0, end: 32 }] });
  t.answer(/^GET \/api\/projects\/Study\/documents\/d1\/role/, { role: null });
  t.answer(`GET ${DOC}/nonscientific-suggestion`, { suggested: false });
  t.answer(`GET ${DOC}/notes`, { notes: [] });
  t.answer(`GET ${DOC}/file?*`, {});
  await t.render("views/doc-page.js", "renderDocument", ["d1"], { tab: "reading" });
  const rep = { ok: true, counts: { check: { moved: 3, not_placed: 0 }, note: { moved: 2, not_placed: 1 }, block: { moved: 1, not_placed: 0 } },
    not_placed: [{ kind: "note", kind_text: "a note or highlight on the text", quote: "45-67 2 The", why: "Its words are not in the new reading where they were." }],
    left_out: [], warnings: [], same_reading: false, reading: { quality: "good", body_passages: 3, warnings: [] } };
  t.answer(`GET ${DOC}/reread`, rep);
  t.answer(`POST ${DOC}/reread`, { job: { id: "jm" } });
  t.answer("GET /api/jobs/jm", { id: "jm", state: "done", progress: {}, result: { report: { ...rep, moved: true } } });
  t.answer(/^GET \/api\/jobs\/jm/, { id: "jm", state: "done", progress: {}, result: { report: { ...rep, moved: true } } });
  await t.click("Read with the new reader");
  await t.settle();
  const preview = t.text(t.view.querySelector(".dv-reread p"));
  await t.click("Move it to the new reader");
  await t.settle(3000);
  return { preview, toasts: t.toasts().filter((x) => x.startsWith("Read with the new reader")) };
});
"""


@pytest.fixture(scope="module")
def views(tmp_path_factory):
    from _views import NODE, run_views

    if not NODE:
        pytest.skip("node is not installed")
    return run_views(VIEWS, tmp_path_factory.mktemp("reread15"))


def test_a_label_run_that_met_a_moved_document_says_so_on_the_page(views):
    """Review wave 5 note (c): the run's result counted the passages not read (`read_again_meanwhile`), no page said
    it."""
    (line,) = views["profile: a label run that met a document read again says so"]
    assert "2 passages were not read: their document was read with the new reader meanwhile" in line


def test_a_references_run_that_met_a_moved_document_says_so_on_the_page(views):
    (line,) = views["references: a run that met a document read again says so"]
    assert "4 stretches not read: the document was read with the new reader meanwhile" in line


def test_the_preview_and_the_toast_count_notes_and_blocks_as_what_they_are(views):
    """Review wave 5 note (e): notes and block choices were counted as "results"."""
    got = views["document page: the preview and the toast name notes and blocks as what they are"]
    assert got["preview"].startswith("3 results find their place in the new reading."), got
    assert "2 notes and highlights find their place, 1 does not." in got["preview"]
    assert "1 block you left out or restored finds its place." in got["preview"]
    (toast,) = got["toasts"]
    assert toast.startswith("Read with the new reader: 3 results moved.") and "2 notes and highlights" in toast
