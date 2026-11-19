"""Hunt, phase 1 (area `merge`): how two copies of a project come together, and who may do what.

Each test asserts what the product should do and fails today for the reason in its docstring. A colleague's file is
untrusted input: the tests change a real copy's zip with an SQLite tool (as anyone can), the way
tests/test_authorship.py and tests/test_sync_hardening.py do.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from enlens_claims import notes, ownership, people, profile, sharing
from enlens_claims.store import now
from owner_helpers import TEXTS, add_doc, has, proposals, set_role
from owner_more_helpers import join_zip, small_project
from test_authorship import _forge
from test_shared_projects import Person


@pytest.fixture
def abc(tmp_path, monkeypatch):
    """Anna's small project (three text documents; she is its owner); Ben and Carol have copies from her zips."""
    anna = Person(tmp_path, "Anna", monkeypatch)
    small_project(anna, tmp_path / "anna-project")
    ben, carol = Person(tmp_path, "Ben", monkeypatch), Person(tmp_path, "Carol", monkeypatch)
    join_zip(ben, anna, tmp_path / "ben-project")
    join_zip(carol, anna, tmp_path / "carol-project")
    return anna, ben, carol


def _first_doc(p: Person, key: str = "desalination") -> str:
    with p:
        return p.ws.scalar("SELECT doc_id FROM documents WHERE text LIKE ?", (TEXTS[key][:30] + "%",))


def _words(p: Person, doc: str, n: int = 4) -> tuple[int, int]:
    with p:
        text = p.ws.scalar("SELECT text FROM documents WHERE doc_id=?", (doc,))
    w = text.split()
    a = text.index(w[5])
    z = text.index(w[5 + n - 1], a) + len(w[5 + n - 1])
    return a, z


# ---- roles: what only its author may do ---------------------------------------------------------------------------
def test_a_colleagues_file_cannot_take_back_a_third_persons_proposal(abc, tmp_path):
    """Carol (a Member) proposes to remove a document; Ben's file says her proposal was taken back, and the owner's
    copy takes it as taken back: only its maker may (ownership.take_back), sync/owner_merge.py:80 does not ask who."""
    anna, ben, carol = abc
    doc = _first_doc(carol)
    with carol:
        carol.ws.remove_document(doc, why="Out of scope")
    f = carol.send()
    anna.bring_in(f)
    ben.bring_in(f)
    waiting = [p for p in proposals(anna, state="waiting") if p["kind"] == "remove"]
    assert len(waiting) == 1 and waiting[0]["by"]["id"] == carol.id
    pid = waiting[0]["id"]
    forged = _forge(ben.send(), tmp_path / "ben-forged.zip",
                    ("UPDATE proposals SET taken_back_at=? WHERE id=?", (now(), pid)))
    anna.bring_in(forged)
    got = {p["id"]: p for p in proposals(anna)}
    assert got[pid]["state"] == "waiting"


def test_a_colleagues_file_cannot_take_back_your_own_review(abc, tmp_path):
    """Anna accepts a label; Ben's file carries a note that a review was taken back, keyed by Anna's review and without
    its fields: sync/merge.py:868 removes Anna's own review (`forget_reviews(keys=...)`), from every copy after."""
    anna, ben, carol = abc
    doc = _first_doc(anna)
    with anna:
        pid = anna.ws.scalar("SELECT passage_id FROM passages WHERE doc_id=? ORDER BY seq LIMIT 1", (doc,))
        lid = profile.add_label(anna.ws, "sdg", pid, "6.4")
        profile.set_label(anna.ws, lid, "accept")
        row = anna.ws.query("SELECT * FROM reviews WHERE item_kind='label' AND item_id=?", (lid,))[0]
        key = people.review_key(dict(row))
        assert row["person_id"] == anna.id
    forged = _forge(ben.send(), tmp_path / "ben-forged.zip",
                    ("INSERT INTO sync_removed(kind, key, title, at, person_id) VALUES ('review', ?, NULL, ?, ?)",
                     (key, now(), ben.id)))
    anna.bring_in(forged)
    with anna:
        assert anna.ws.scalar("SELECT COUNT(*) FROM reviews WHERE item_kind='label' AND item_id=? AND person_id=?",
                              (lid, anna.id)) == 1



def test_a_relayed_review_never_overrules_the_authors_own(abc, tmp_path):
    """Anna accepts a label and Ben has her review from her own file; Carol's file relays a later review "in Anna's
    name" that rejects it. In Ben's copy the relayed one now counts as Anna's word and the label is gone
    (sync/merge.py:883 adds it; profile._decisions takes the latest), though a relayed row never replaces the author's
    own (docs/manual/how-two-copies-come-together.md, "Work of a third person"; judgements keep to it)."""
    anna, ben, carol = abc
    doc = _first_doc(anna)
    with anna:
        pid = anna.ws.scalar("SELECT passage_id FROM passages WHERE doc_id=? ORDER BY seq LIMIT 1", (doc,))
        lid = profile.add_label(anna.ws, "sdg", pid, "6.4")
        profile.set_label(anna.ws, lid, "accept")
    ben.bring_in(anna.send())

    def counts(p: Person) -> bool:
        with p:
            return lid in {r["label_id"] for r in profile.effective(p.ws, "sdg", doc_ids=[doc])}

    assert counts(ben)
    forged = _forge(carol.send(), tmp_path / "carol-forged.zip",
                    ("INSERT INTO reviews(item_kind, item_id, field, decision, person_id, decided_at) VALUES "
                     "('label', ?, 'label', 'reject', ?, '2999-01-01T00:00:00+00:00')", (lid, anna.id)))
    ben.bring_in(forged)
    assert counts(ben)


def test_a_colleague_cannot_keep_a_third_persons_note_out_by_saying_they_removed_it(abc, tmp_path):
    """Carol's file says she removed a note that is Anna's; Ben does not hold it yet, so he notes it as removed
    (sync/merge.py:985) and Anna's own file never brings it to him: only its author removes a note."""
    anna, ben, carol = abc
    doc = _first_doc(anna)
    a, z = _words(anna, doc)
    with anna:
        nid = notes.add(anna.ws, doc, a, z, text="Anna's note")["note_id"]
        sharing.share(anna.ws, [{"kind": "note", "key": nid}])
    forged = _forge(carol.send(), tmp_path / "carol-forged.zip",
                    ("INSERT INTO sync_removed(kind, key, title, at, person_id) VALUES ('note', ?, 'x', ?, ?)",
                     (nid, now(), carol.id)))
    ben.bring_in(forged)
    ben.bring_in(anna.send())  # (without Carol's file first, Anna's note comes in: test_sync_hardening.py:268)
    with ben:
        assert ben.ws.scalar("SELECT person_id FROM notes WHERE note_id=?", (nid,)) == anna.id


# ---- paths built from a colleague's ids ---------------------------------------------------------------------------
def _rezip(src: Path, out: Path, change) -> Path:
    """`src` unpacked, changed by `change(folder, db, meta)`, and zipped again (any zip tool does this)."""
    work = out.with_suffix("")
    work.mkdir()
    with zipfile.ZipFile(src) as zf:
        zf.extractall(work)
    meta = json.loads((work / "bundle.json").read_text(encoding="utf-8"))
    cx = sqlite3.connect(work / "enlens.sqlite")
    change(work, cx, meta)
    cx.commit()
    cx.close()
    (work / "bundle.json").write_text(json.dumps(meta), encoding="utf-8")
    with zipfile.ZipFile(out, "w") as zf:
        for p in sorted(work.rglob("*")):
            if p.is_file():
                zf.write(p, p.relative_to(work).as_posix())
    return out


def test_a_colleagues_document_whose_id_differs_only_by_case_does_not_overwrite_your_original(abc, tmp_path):
    """A document in Anna's file whose id is one of Ben's in capitals (another text, a file of the same name) is
    copied to originals/<ID>/, which on macOS and Windows is Ben's originals/<id>/: his original file is replaced
    (sync/merge.py:396 and :205; common.DOC_ID allows capitals)."""
    anna, ben, carol = abc
    doc = _first_doc(ben)
    with ben:
        mine = Path(ben.ws.scalar("SELECT path FROM documents WHERE doc_id=?", (doc,)))
    before = mine.read_bytes()
    assert mine.parent.name == doc and mine.parent.parent.name == "originals"
    other = doc.upper()
    body = b"Another report altogether.\n\nIt says nothing about desalination at all, and its words are other words.\n"

    def change(work: Path, cx: sqlite3.Connection, meta: dict) -> None:
        arc = meta["files"].pop(doc)
        (work / arc).unlink()
        (work / "originals" / doc).rmdir()
        (work / "originals" / other).mkdir()
        (work / "originals" / other / mine.name).write_bytes(body)
        meta["files"][other] = f"originals/{other}/{mine.name}"
        cols = [r[1] for r in cx.execute("PRAGMA table_info(documents)")]
        row = dict(zip(cols, cx.execute("SELECT * FROM documents WHERE doc_id=?", (doc,)).fetchone()))
        row.update(doc_id=other, text=body.decode(), text_fp=None, sha1=hashlib.sha1(body).hexdigest(), title="Other")
        cx.execute(f"INSERT INTO documents({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                   [row[c] for c in cols])

    ben.bring_in(_rezip(anna.send(), tmp_path / "anna-forged.zip", change))
    assert mine.read_bytes() == before
    # on any file system (also one that heeds case, as on Linux): no two documents' originals folders are the same
    # folder when case is ignored
    with ben:
        ids = [r["doc_id"] for r in ben.ws.query("SELECT doc_id FROM documents")]
    assert len({i.casefold() for i in ids}) == len(ids), ids


# ---- private until shared ------------------------------------------------------------------------------------------
def test_a_zip_of_what_you_shared_holds_no_ai_draft_of_a_code_of_your_private_codebook(tmp_path, monkeypatch):
    """Anna asks the AI to draft a definition of a code of her codebook, which she never shared; the zip of what she
    shared still holds that task, with the code's name, its group and her example passages (sharing.strip and
    rows_of leave `code_definition` tasks in; sync/merge.py:446 then brings them into a colleague's copy)."""
    from enlens_claims import bundle, codedefine, frameworks, home as ehome
    from test_code_definition_ai import DOC_A, DOC_B, EXAMPLES, FakeModel

    anna = Person(tmp_path, "Anna", monkeypatch)
    with anna:
        ehome.save_settings({**ehome.load_settings(), "backend": "anthropic", "allow_cloud": True,
                             "embed_backend": "off"})
        ws = ehome.create_project("Care")
        d = tmp_path / "docs"
        d.mkdir()
        (d / "a.txt").write_text(DOC_A, encoding="utf-8")
        (d / "b.txt").write_text(DOC_B, encoding="utf-8")
        from enlens_claims import ingest

        ingest.ingest(ws, [d])
        frameworks.save(ws, "secretcodes", "code,description\nResidents kept waiting,Waiting for staff\n",
                        title="My private codes")
        assert sharing.state(ws._conn(), "codebook", "secretcodes")["state"] == "private"
        got = codedefine.draft(ws, "secretcodes", "Residents kept waiting", "Daily life", list(EXAMPLES), FakeModel(),
                               "claude-sonnet-5-5", title="My private codes")
        assert got["ok"]
        out = tmp_path / "anna-shared.zip"
        bundle.export_project(ws, out, scope="shared")
        ws.close_all()
    work = tmp_path / "unpacked"
    with zipfile.ZipFile(out) as zf:
        zf.extract("enlens.sqlite", work)
    cx = sqlite3.connect(work / "enlens.sqlite")
    try:
        left = cx.execute("SELECT task_id, payload_json FROM tasks WHERE kind='code_definition'").fetchall()
        answers = cx.execute("SELECT COUNT(*) FROM results WHERE task_id=?", (got["task_id"],)).fetchone()[0]
    finally:
        cx.close()
    assert not [t for t, p in left if "Residents kept waiting" in (p or "")]
    assert answers == 0


# ---- a file that says it is this person's own ------------------------------------------------------------------
def test_a_file_that_says_it_is_your_own_cannot_remove_a_document_in_your_name(abc, tmp_path):
    """Carol (a Member) removes a Co-owner's document and sends her file to the Owner saying it is from the Owner
    (bundle.json `from`, unproven in a zip) with her note of removal in the Owner's name: sync/merge.py:1023 then
    takes the note, and the project loses the document in every copy, by the Owner's word she never gave."""
    anna, ben, carol = abc
    anna.bring_in(ben.send())  # (Anna's copy knows Ben)
    set_role(anna, ben, "co")
    f = anna.send()
    ben.bring_in(f)
    carol.bring_in(f)
    doc = add_doc(ben, tmp_path, "interview")  # a Co-owner adds a document: the project's at once
    carol.bring_in(ben.send())
    assert has(carol, doc) and not has(anna, doc)
    with carol:
        carol.ws.remove_document(doc, why="Not mine to keep")

    def as_anna(work: Path, cx: sqlite3.Connection, meta: dict) -> None:
        cx.execute("UPDATE sync_removed SET person_id=? WHERE kind='document' AND key=?", (anna.id, doc))
        meta["from"] = {"id": anna.id, "name": "Anna"}

    anna.bring_in(_rezip(carol.send(), tmp_path / "carol-as-anna.zip", as_anna))
    anna.bring_in(ben.send())
    ben.bring_in(anna.send())
    with ben:
        k = ownership.canon(ben.ws._conn()).get(doc)
    assert k is not None and k["state"] == "in"
    assert has(ben, doc) and has(anna, doc)


# ---- siblings found while fixing (hunt phase 1, the fixer's sweep) -------------------------------------------------
def test_a_file_that_says_it_is_your_own_cannot_take_back_your_review(abc, tmp_path):
    """MERGE-2's and MERGE-1's shape together: Carol's file says it is from Anna and carries a note, in Anna's name and
    with her review's fields, that Anna took her review back. Anna's own review must stay: her reviews are taken back
    in her copy, by her, never by a file."""
    anna, ben, carol = abc
    doc = _first_doc(anna)
    with anna:
        pid = anna.ws.scalar("SELECT passage_id FROM passages WHERE doc_id=? ORDER BY seq LIMIT 1", (doc,))
        lid = profile.add_label(anna.ws, "sdg", pid, "6.4")
        profile.set_label(anna.ws, lid, "accept")
        row = dict(anna.ws.query("SELECT * FROM reviews WHERE item_kind='label' AND item_id=?", (lid,))[0])
    f = {c: row.get(c) for c in people.REVIEW_KEY}

    def as_anna(work: Path, cx: sqlite3.Connection, meta: dict) -> None:
        cx.execute("INSERT INTO sync_removed(kind, key, title, at, person_id) VALUES ('review', ?, ?, ?, ?)",
                   (people.review_key(f), json.dumps(f), now(), anna.id))
        meta["from"] = {"id": anna.id, "name": "Anna"}

    anna.bring_in(_rezip(carol.send(), tmp_path / "carol-as-anna.zip", as_anna))
    with anna:
        assert anna.ws.scalar("SELECT COUNT(*) FROM reviews WHERE item_kind='label' AND item_id=? AND person_id=?",
                              (lid, anna.id)) == 1


def test_a_file_that_says_it_is_your_own_cannot_remove_your_note_from_your_colleagues(abc, tmp_path):
    """MERGE-1's shape for notes: Carol's file says it is from Anna and that Anna removed her shared note. Anna's copy
    noted the removal as her own, and her next file removed the note from every colleague's copy."""
    anna, ben, carol = abc
    doc = _first_doc(anna)
    a, z = _words(anna, doc)
    with anna:
        nid = notes.add(anna.ws, doc, a, z, text="Anna's note")["note_id"]
        sharing.share(anna.ws, [{"kind": "note", "key": nid}])
    ben.bring_in(anna.send())

    def as_anna(work: Path, cx: sqlite3.Connection, meta: dict) -> None:
        cx.execute("INSERT INTO sync_removed(kind, key, title, at, person_id) VALUES ('note', ?, 'x', ?, ?)",
                   (nid, now(), anna.id))
        meta["from"] = {"id": anna.id, "name": "Anna"}

    anna.bring_in(_rezip(carol.send(), tmp_path / "carol-as-anna.zip", as_anna))
    with anna:
        assert not anna.ws.scalar("SELECT 1 FROM sync_removed WHERE kind='note' AND key=?", (nid,))
    ben.bring_in(anna.send())
    with ben:
        assert ben.ws.scalar("SELECT person_id FROM notes WHERE note_id=?", (nid,)) == anna.id


def test_the_authors_own_file_ends_a_relayed_review_in_their_name(abc, tmp_path):
    """MERGE-5, the other order: Carol's file relays Anna's accept and a later "reject" in Anna's name before Ben has
    anything of Anna's own. Anna's own file, which holds only her accept, ends the relayed reject (as the author's own
    judgement takes the place of a relayed one)."""
    anna, ben, carol = abc
    doc = _first_doc(anna)
    with anna:
        pid = anna.ws.scalar("SELECT passage_id FROM passages WHERE doc_id=? ORDER BY seq LIMIT 1", (doc,))
        lid = profile.add_label(anna.ws, "sdg", pid, "6.4")
        profile.set_label(anna.ws, lid, "accept")
    carol.bring_in(anna.send())

    def counts(p: Person) -> bool:
        with p:
            return lid in {r["label_id"] for r in profile.effective(p.ws, "sdg", doc_ids=[doc])}

    forged = _forge(carol.send(), tmp_path / "carol-forged.zip",
                    ("INSERT INTO reviews(item_kind, item_id, field, decision, person_id, decided_at) VALUES "
                     "('label', ?, 'label', 'reject', ?, '2999-01-01T00:00:00+00:00')", (lid, anna.id)))
    ben.bring_in(forged)
    ben.bring_in(anna.send())
    assert counts(ben)
    with ben:
        assert ben.ws.scalar("SELECT COUNT(*) FROM reviews WHERE item_kind='label' AND item_id=? AND decision='reject'",
                             (lid,)) == 0


def test_a_relayed_take_back_of_a_proposal_new_here_is_held_back(abc, tmp_path):
    """MERGE-4 for a proposal the owner's copy does not hold yet: Ben's file brings Carol's proposal already marked
    taken back. It is not taken as taken back (after review: nor as waiting, so the owner cannot accept a proposal its
    maker withdrew): it waits for Carol's own file, which (she never took it back) brings it waiting."""
    anna, ben, carol = abc
    doc = _first_doc(carol)
    with carol:
        carol.ws.remove_document(doc, why="Out of scope")
    f = carol.send()
    ben.bring_in(f)
    with ben:
        pid = ben.ws.scalar("SELECT id FROM proposals WHERE by=? AND kind='remove'", (carol.id,))
    assert pid
    forged = _forge(ben.send(), tmp_path / "ben-forged.zip",
                    ("UPDATE proposals SET taken_back_at=? WHERE id=?", (now(), pid)))
    anna.bring_in(forged)
    assert {p["id"]: p for p in proposals(anna)}.get(pid, {}).get("state") != "taken_back"
    anna.bring_in(f)
    assert {p["id"]: p for p in proposals(anna)}[pid]["state"] == "waiting"


def test_a_colleague_cannot_keep_a_third_persons_log_entry_out_by_saying_they_removed_it(abc, tmp_path):
    """MERGE-6 for the research log: Carol's file says she removed an entry that is Anna's."""
    from enlens_claims import researchlog

    anna, ben, carol = abc
    with anna:
        eid = researchlog.add(anna.ws, "Why we left the 2019 reports out")["entry_id"]
        sharing.share(anna.ws, [{"kind": "log", "key": eid}])
    forged = _forge(carol.send(), tmp_path / "carol-forged.zip",
                    ("INSERT INTO sync_removed(kind, key, title, at, person_id) VALUES ('log', ?, 'x', ?, ?)",
                     (eid, now(), carol.id)))
    ben.bring_in(forged)
    ben.bring_in(anna.send())
    with ben:
        assert ben.ws.scalar("SELECT person_id FROM research_log WHERE entry_id=?", (eid,)) == anna.id


def _private_tasks(ws) -> dict[str, str]:
    """A finished task, with its answer, of each kind that is this person's own work and no item's: the framework the
    AI drafted from theory documents (with the person's focus), a code's draft definition, and the search words asked
    for a concept of the glossary. {task_id: words that must not leave}."""
    pid, doc = ws.query("SELECT passage_id, doc_id FROM passages LIMIT 1")[0]
    made = {"theory_frame:aaaaaaaaaaaaaaaa": ("theory_frame", {"focus": "My secret focus on burnout", "documents": [
                {"doc_id": doc}], "drafts": [{"n": 1, "doc_id": doc, "passage_id": pid, "name": "Agency"}]}),
            "code_definition:bbbbbbbbbbbbbbbb": ("code_definition", {"code": "My secret code", "group": "G",
                                                                     "passages": [{"passage_id": pid}]}),
            "expand:concept:t123:1": ("expand", {"concept": "t123", "claim": "the concept: my secret concept"})}
    with ws.connect() as cx:
        for tid, (kind, payload) in made.items():
            cx.execute("INSERT INTO tasks(task_id, kind, model, prompt_version, payload_json, status, attempts, "
                       "created_at, access) VALUES (?,?,?,?,?,'done',1,'2026-11-18T00:00:00+00:00','cloud')",
                       (tid, kind, "claude-sonnet-5-5", "v1", json.dumps(payload)))
            cx.execute("INSERT INTO results(task_id, attempt, kind, model, prompt_version, raw_json, valid, "
                       "errors_json, received_at) VALUES (?,1,?,?,?,?,1,'[]','2026-11-18T00:00:00+00:00')",
                       (tid, kind, "claude-sonnet-5-5", "v1", json.dumps({"note": "my secret answer"})))
    return {tid: "secret" for tid in made}


def test_a_zip_of_what_you_shared_holds_none_of_your_own_ai_drafts(abc, tmp_path):
    """MERGE-3's sweep over the task kinds: `theory_frame` (the person's focus, the draft framework) and the search
    words of a glossary concept (`expand:concept:…`, a check's kind that no check holds) stayed in a zip of what was
    shared, task and answer; the shared folder never wrote them."""
    from enlens_claims import bundle

    anna, ben, carol = abc
    with anna:
        made = _private_tasks(anna.ws)
        out = tmp_path / "anna-shared.zip"
        bundle.export_project(anna.ws, out, scope="shared")
    work = tmp_path / "unpacked"
    with zipfile.ZipFile(out) as zf:
        zf.extract("enlens.sqlite", work)
    cx = sqlite3.connect(work / "enlens.sqlite")
    try:
        q = ",".join("?" * len(made))
        tasks_left = [r[0] for r in cx.execute(f"SELECT task_id FROM tasks WHERE task_id IN ({q})", list(made))]
        results_left = [r[0] for r in cx.execute(f"SELECT task_id FROM results WHERE task_id IN ({q})", list(made))]
        said = [r[0] for r in cx.execute("SELECT payload_json FROM tasks") if "secret" in (r[0] or "")]
    finally:
        cx.close()
    assert not tasks_left and not results_left and not said


def test_the_shared_folder_writes_none_of_your_own_ai_drafts_and_its_last_look_refuses_them(abc, tmp_path):
    """MERGE-3 for the shared folder: its rows (sharing.ProjectRows) hold no `code_definition` or `theory_frame` task
    or answer, and its last look before a bundle is written (sync.folder._leaks) refuses one."""
    from enlens_claims import bundle
    from enlens_claims.sync import folder

    anna, ben, carol = abc
    with anna:
        made = _private_tasks(anna.ws)
        with anna.ws.connect() as cx:
            rows = sharing.ProjectRows(cx, anna.ws.root)
            sent = {r[2][0] for r in rows.scan(only=["tasks", "results"]) if r[0] in ("tasks", "results")}
        out = tmp_path / "anna-shared.zip"
        bundle.export_project(anna.ws, out, scope="shared")
    assert not set(made) & sent, set(made) & sent
    work = tmp_path / "unpacked"
    with zipfile.ZipFile(out) as zf:
        zf.extract("enlens.sqlite", work)
    cx = sqlite3.connect(work / "enlens.sqlite")
    try:
        items = [{"kind": k, "key": key, "state": st} for k, key, st in cx.execute("SELECT kind, key, state FROM shares")]
        assert folder._leaks(cx, items) is None  # (the zip of what was shared passes the last look)
        for kind in sharing.LOCAL_TASK_KINDS:
            cx.execute("INSERT INTO tasks(task_id, kind, status) VALUES (?, ?, 'done')", (f"{kind}:zz", kind))
            assert folder._leaks(cx, items), kind
            cx.execute("DELETE FROM tasks WHERE task_id=?", (f"{kind}:zz",))
    finally:
        cx.close()


def test_a_colleagues_own_ai_drafts_do_not_come_in(abc, tmp_path):
    """A colleague on an older version sends their `code_definition` and `theory_frame` tasks (a whole-project zip
    holds them): they do not come into this copy."""
    from enlens_claims import bundle

    anna, ben, carol = abc
    with anna:
        made = _private_tasks(anna.ws)
        f = tmp_path / "anna-all.zip"
        bundle.export_project(anna.ws, f, scope="all")
    ben.bring_in(f)
    local = [t for t in made if not t.startswith("expand:")]
    with ben:
        q = ",".join("?" * len(local))
        assert not ben.ws.scalar(f"SELECT COUNT(*) FROM tasks WHERE task_id IN ({q})", local)
        assert not ben.ws.scalar(f"SELECT COUNT(*) FROM results WHERE task_id IN ({q})", local)


def test_a_colleague_who_removed_their_copy_of_your_check_does_not_keep_it_from_a_third(abc):
    """MERGE-6's shape for checks (no changed file needed): Carol removes her copy of Anna's shared check; Ben, who does
    not hold it yet, brings Carol's file, then Anna's own: the check never came, though a colleague who removes their
    copy of someone else's item decides nothing about it (sync/share_merge.py, `_removed_by_owner`)."""
    from enlens_claims.judgements import delete_hypothesis
    from owner_helpers import check

    anna, ben, carol = abc
    hid = check(anna, "Desalination raises the price of water")
    with anna:
        sharing.share(anna.ws, [{"kind": "check", "key": hid}])
    carol.bring_in(anna.send())
    with carol:
        assert carol.ws.scalar("SELECT 1 FROM hypotheses WHERE hyp_id=?", (hid,))
        delete_hypothesis(carol.ws, hid, why="Not for my chapter")
    ben.bring_in(carol.send())
    ben.bring_in(anna.send())
    with ben:
        assert ben.ws.scalar("SELECT 1 FROM hypotheses WHERE hyp_id=?", (hid,))


# ---- after review (reviews/sync.md): a relayed take-back must not bring a withdrawn proposal back as new ------------
def _carol_takes_back(anna, ben, carol):
    """Carol proposes to remove a document, Ben brings that in, Carol takes it back; Ben then has her take-back."""
    doc = _first_doc(carol)
    with carol:
        carol.ws.remove_document(doc, why="Out of scope")
    ben.bring_in(carol.send())
    with carol:
        pid = carol.ws.scalar("SELECT id FROM proposals WHERE by=? AND kind='remove'", (carol.id,))
        ownership.take_back(carol.ws, pid)
    own = carol.send()
    ben.bring_in(own)
    with ben:
        assert ben.ws.scalar("SELECT taken_back_at FROM proposals WHERE id=?", (pid,))
    return pid, own


def test_a_take_back_relayed_first_does_not_bring_the_proposal_to_the_owner_as_new(abc):
    """Ben's file reaches the owner before Carol's own: the proposal Carol withdrew must not wait for the owner nor be
    reported as new, and the held take-back is said once, not with every file of Ben's."""
    anna, ben, carol = abc
    pid, own = _carol_takes_back(anna, ben, carol)
    r1 = anna.bring_in(ben.send())
    assert not [p for p in r1["proposals"]["new"] if p["id"] == pid]
    assert pid not in {p["id"] for p in proposals(anna, state="waiting")}
    r2 = anna.bring_in(ben.send())
    assert not r2["proposals"].get("taken_back_held") and not r2["proposals"]["new"]
    anna.bring_in(own)
    assert {p["id"]: p for p in proposals(anna)}[pid]["state"] == "taken_back"


def test_a_take_back_from_its_maker_first_stays_taken_back(abc):
    """The other order: Carol's own file first, then Ben's relaying the same take-back."""
    anna, ben, carol = abc
    pid, own = _carol_takes_back(anna, ben, carol)
    anna.bring_in(own)
    r = anna.bring_in(ben.send())
    assert {p["id"]: p for p in proposals(anna)}[pid]["state"] == "taken_back"
    assert not r["proposals"].get("taken_back_held") and not r["proposals"]["new"]


def test_a_relayed_take_back_of_a_waiting_proposal_is_said_once(abc, tmp_path):
    """MERGE-4's own case, counted once per proposal: the forged take-back is held back with each of Ben's files, and
    the report says so the first time only."""
    anna, ben, carol = abc
    doc = _first_doc(carol)
    with carol:
        carol.ws.remove_document(doc, why="Out of scope")
    f = carol.send()
    anna.bring_in(f)
    ben.bring_in(f)
    pid = [p for p in proposals(anna, state="waiting") if p["kind"] == "remove"][0]["id"]
    forged = _forge(ben.send(), tmp_path / "ben-forged.zip",
                    ("UPDATE proposals SET taken_back_at=? WHERE id=?", (now(), pid)))
    assert anna.bring_in(forged)["proposals"].get("taken_back_held") == 1
    assert not anna.bring_in(forged)["proposals"].get("taken_back_held")
    assert {p["id"]: p for p in proposals(anna)}[pid]["state"] == "waiting"


def test_a_removal_note_by_key_alone_is_applied_once_the_review_is_here(abc, tmp_path):
    """After review (MERGE-2): a note naming a review by its key alone, for a review this copy does not hold, takes
    nothing back and is not noted. The review then comes relayed; the remover's next file, still carrying the note,
    takes it back here (the remover is its author)."""
    anna, ben, carol = abc
    doc = _first_doc(anna)
    with anna:
        pid = anna.ws.scalar("SELECT passage_id FROM passages WHERE doc_id=? ORDER BY seq LIMIT 1", (doc,))
        lid = profile.add_label(anna.ws, "sdg", pid, "6.4")
        profile.set_label(anna.ws, lid, "accept")
        key = people.review_key(dict(anna.ws.query("SELECT * FROM reviews WHERE item_kind='label' AND item_id=?",
                                                   (lid,))[0]))
    carol.bring_in(anna.send())
    took_back = (("DELETE FROM reviews WHERE item_kind='label' AND item_id=?", (lid,)),
                 ("INSERT INTO sync_removed(kind, key, title, at, person_id) VALUES ('review', ?, NULL, ?, ?)",
                  (key, now(), anna.id)))
    ben.bring_in(_forge(anna.send(), tmp_path / "anna-1.zip", *took_back))
    ben.bring_in(carol.send())  # the review comes relayed
    with ben:
        assert ben.ws.scalar("SELECT COUNT(*) FROM reviews WHERE item_kind='label' AND item_id=?", (lid,)) == 1
    ben.bring_in(_forge(anna.send(), tmp_path / "anna-2.zip", *took_back))
    with ben:
        assert ben.ws.scalar("SELECT COUNT(*) FROM reviews WHERE item_kind='label' AND item_id=?", (lid,)) == 0
