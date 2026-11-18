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
    finally:
        cx.close()
    assert not [t for t, p in left if "Residents kept waiting" in (p or "")]


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
