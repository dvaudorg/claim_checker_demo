"""Hunt phase 1.5, area `readers`: every note and open point of phases 0 and 1 about reading files in, settled.

Each test asserts what ENLENS should do (the manual, the module docstrings, the owner's decisions). The ledger
(.claude/audits/2026-11-19-phase1.5/ledger/readers.md) says for each whether it failed and was fixed, or passed.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import shutil
import sqlite3
import time
import unicodedata
import zipfile
from pathlib import Path

import pytest
from test_adding_and_rereading import _worker_code
from test_reader3 import _sentence

from enlens_claims import bundle, ingest, sources
from enlens_claims.store import Workspace

OFF = ingest.OcrOptions(mode="off")
ROOT = Path(__file__).resolve().parent.parent


def _long(topic: str, n: int = 4, seed: int = 1) -> str:
    rng = random.Random(seed)
    return f"A report on {topic}.\n\n" + "\n\n".join(_sentence(rng) for _ in range(n)) + "\n"


def _folder(tmp_path: Path, names: list[str]) -> Path:
    d = tmp_path / "batch"
    d.mkdir()
    for i, n in enumerate(names):
        (d / n).write_text(_long(n, seed=i), encoding="utf-8")
    return d


# ---- 1. the owner: no doc, comment or page text names a version not made yet --------------------------------------
def test_nothing_names_the_unreleased_version():
    """Reader 7's release is not made now: no doc, comment, page text or test may name it by a coming number."""
    found = []
    for top in ("src", "docs", "tests", "changes", "tools"):
        for p in (ROOT / top).rglob("*"):
            if p.is_file() and p.suffix in (".py", ".md", ".js", ".html", ".css", ".json", ".txt", ".ps1", ".sh"):
                if p.name == Path(__file__).name:
                    continue
                if re.search(r"\b0\.20\.4\b", p.read_text("utf-8", errors="replace")):
                    found.append(str(p.relative_to(ROOT)))
    assert found == []
    table = (ROOT / "docs/manual/how-documents-are-read.md").read_text("utf-8")
    assert "| 7 | the version after 0.20.3 |" in table
    # review wave 4: the owner allowed "the version after 0.20.3" in the manual's table of readers only
    elsewhere = []
    for top in ("src", "docs", "changes", "tools"):
        for p in (ROOT / top).rglob("*"):
            if p.is_file() and p.suffix in (".py", ".md", ".js", ".html"):
                for line in p.read_text("utf-8", errors="replace").splitlines():
                    if re.search(r"after (ENLENS )?0\.20\.3", line) and not line.startswith("| 7 | the version after"):
                        elsewhere.append(str(p.relative_to(ROOT)))
    assert elsewhere == []


# ---- 2. a file that reads but cannot be built --------------------------------------------------------------------
_BAD = ("import os; from enlens_claims import ingest as _i; _b = _i.build_document; "
        "_i.build_document = lambda raw, *a, **k: [][1] if raw.path.name == 'b_bad.txt' else _b(raw, *a, **k)")


@pytest.mark.parametrize("workers", [1, 2])
def test_a_file_that_reads_but_cannot_be_built_is_listed_and_the_others_are_added(tmp_path, monkeypatch, workers):
    """notes/readers.md, Not proven 2: `_ingest_files` raised the exception of a file read but not made into a
    Document ("unbuilt"), so one such file stopped the whole add. It is a line under the files that could not be read."""
    folder = _folder(tmp_path, ["a.txt", "b_bad.txt", "c.txt"])
    if workers == 1:
        real = ingest.build_document

        def build(raw, *a, **k):
            if raw.path.name == "b_bad.txt":
                return [][1]
            return real(raw, *a, **k)

        monkeypatch.setattr(ingest, "build_document", build)
    else:
        _worker_code(monkeypatch, _BAD)
    ws = Workspace.create(tmp_path / "ws")
    stats = ingest.ingest(ws, [folder], ocr=OFF, ai_access="cloud", workers=workers)
    assert stats["added"] == 2
    bad = [f for f in stats.get("failed", []) if f.startswith("b_bad.txt: ")]
    assert len(bad) == 1 and "could not" in bad[0]
    names = {Path(r[0]).name for r in ws.query("SELECT path FROM documents")}
    assert names == {"a.txt", "c.txt"}


# ---- 3. a project zip's names that differ only by case or accent form --------------------------------------------
def _sha(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()


def _project_with_two(tmp_path: Path) -> tuple[Workspace, dict]:
    """A project whose two documents sit in one folder of it as A.txt and B.txt: {name: doc_id}."""
    ws = Workspace.create(tmp_path / "proj")
    up = ws.root / "uploads" / "b1"
    up.mkdir(parents=True)
    (up / "A.txt").write_text(_long("the valley's wells", seed=3), encoding="utf-8")
    (up / "B.txt").write_text(_long("the river's fish", seed=4), encoding="utf-8")
    ingest.ingest(ws, [up], ocr=OFF, ai_access="cloud")
    return ws, {Path(p).name: d for d, p in ws.query("SELECT doc_id, path FROM documents")}


def _renamed_zip(src: Path, out: Path, rename: dict[str, str], prefix: str = "", db_paths: dict | None = None,
                 meta: bool = True) -> Path:
    """`src` written again to `out` with its files renamed (`rename`: name in the zip -> new name), the map of files
    in bundle.json following, everything under `prefix`; `db_paths` sets documents' recorded paths in its database."""
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(out, "w") as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename == "bundle.json":
                if not meta:
                    continue
                m = json.loads(data)
                m["files"] = {k: rename.get(v, v) for k, v in m.get("files", {}).items()}
                data = json.dumps(m).encode()
            if info.filename == "enlens.sqlite" and db_paths:
                tmp = out.with_suffix(".sqlite")
                tmp.write_bytes(data)
                cx = sqlite3.connect(tmp)
                with cx:
                    for d, p in db_paths.items():
                        cx.execute("UPDATE documents SET path=? WHERE doc_id=?", (p, d))
                cx.close()
                data = tmp.read_bytes()
                tmp.unlink()
            zout.writestr(prefix + rename.get(info.filename, info.filename), data)
    return out


@pytest.mark.parametrize("other", ["a.txt", unicodedata.normalize("NFD", "á.txt")])
def test_two_documents_whose_names_differ_only_by_case_or_accent_form_keep_their_own_files(tmp_path, other):
    """Fixer of phase 1 left: a project zip's import (`bundle.import_project`) unpacked without the name planning of
    `ingest.unpack_names`, so in a zip made on Linux two files "uploads/b1/A.txt" and "uploads/b1/a.txt" (or "á.txt"
    written composed and decomposed) became one file on macOS and Windows: one document opened the other's original."""
    ws, docs = _project_with_two(tmp_path)
    first = "A.txt" if other == "a.txt" else unicodedata.normalize("NFC", "á.txt")
    exported = tmp_path / "export.zip"
    bundle.export_project(ws, exported)
    sha = dict(ws.query("SELECT doc_id, sha1 FROM documents"))
    rename = {"uploads/b1/A.txt": f"uploads/b1/{first}", "uploads/b1/B.txt": f"uploads/b1/{other}"}
    z = _renamed_zip(exported, tmp_path / "linux.zip", rename)
    new = bundle.import_project(z, tmp_path / "imported")
    got = dict(new.query("SELECT doc_id, path FROM documents"))
    assert got[docs["A.txt"]] != got[docs["B.txt"]]
    for d in docs.values():
        assert _sha(Path(got[d])) == sha[d]
        assert sources.original_file(new, d)["available"]


@pytest.mark.parametrize("old, sep", [("/home/someone/Study", "/"), ("C:\\Users\\Dávid\\Study", "\\")])
def test_a_project_folder_zipped_by_hand_keeps_both_files_apart(tmp_path, old, sep):
    """The same, for a project folder zipped by hand (no map of files: the recorded paths are followed). Review wave 4
    (Windows CI): the paths a folder zipped on a Mac or Linux records are POSIX ones, which Windows does not take for
    absolute, so they were left as they were and no document found its file; the same the other way round (a Windows
    PC's "C:\\Users\\…" read on a Mac). Both kinds are followed on every computer."""
    ws, docs = _project_with_two(tmp_path)
    exported = tmp_path / "export.zip"
    bundle.export_project(ws, exported)
    sha = dict(ws.query("SELECT doc_id, sha1 FROM documents"))
    z = _renamed_zip(exported, tmp_path / "byhand.zip", {"uploads/b1/A.txt": "uploads/b1/Report.txt",
                                                          "uploads/b1/B.txt": "uploads/b1/report.txt"},
                     prefix="Study/", meta=False,
                     db_paths={docs["A.txt"]: sep.join([old, "uploads", "b1", "Report.txt"]),
                               docs["B.txt"]: sep.join([old, "uploads", "b1", "report.txt"])})
    new = bundle.import_project(z, tmp_path / "imported")
    got = dict(new.query("SELECT doc_id, path FROM documents"))
    assert got[docs["A.txt"]] != got[docs["B.txt"]]
    for d in docs.values():
        assert _sha(Path(got[d])) == sha[d]


# ---- 4. a reading that hangs in its reading process -----------------------------------------------------------------
_HANGS = ("import time; from enlens_claims import ingest as _i; _r = _i._read_whole; "
          "_i._read_whole = lambda f, *a, **k: time.sleep(600) if f.name == 'b_hangs.txt' else _r(f, *a, **k)")


def test_a_reading_that_hangs_is_named_ended_by_stop_and_the_other_files_can_still_be_added(tmp_path, monkeypatch):
    """notes/readers.md, Not proven 1: a file whose reading never ends is waited for until the person presses Stop
    (no time limit: honest OCR can take long). While it waits the progress names the file; Stop ends its process at
    once; the files before it stay added; the result says which file it was and how many were not added, so that
    adding the same files again, that one left out, adds the others."""
    folder = _folder(tmp_path, ["a.txt", "b_hangs.txt", "c.txt"])
    started = _worker_code(monkeypatch, _HANGS)
    named: list[tuple[str, float]] = []
    ws = Workspace.create(tmp_path / "ws")
    t0 = time.monotonic()
    stats = ingest.ingest(ws, [folder], ocr=OFF, ai_access="cloud", workers=2,
                          progress=lambda i, n, name: named.append((name, time.monotonic())),
                          should_stop=lambda: any(n == "b_hangs.txt" and time.monotonic() - at > 1.0 for n, at in named))
    assert time.monotonic() - t0 < 20
    assert ("b_hangs.txt" in [n for n, _at in named])     # the page's "Reading b_hangs.txt (2 of 3)" while it waits
    assert stats["stopped"] is True and stats["added"] == 1
    assert stats.get("stopped_at") == "b_hangs.txt" and stats.get("not_added") == 2
    assert started and all(p.poll() is not None for p in started)
    again = ingest.ingest(ws, [folder], ocr=OFF, exclude=["b_hangs.txt"], workers=2)
    assert again["added"] == 1 and again["duplicates"] == 1 and not again.get("stopped")
    assert {Path(r[0]).name for r in ws.query("SELECT path FROM documents")} == {"a.txt", "c.txt"}


# ---- 5. a quote is stored and shown in the passage's own characters ----------------------------------------------
TEXT5 = ("The plant’s water use rose to 10³ litres a day in the dry season, the report on the valley says, and "
         "the farmers near the plant fear that the wells will run dry within ten years of its opening.\n")


def test_a_persons_label_keeps_the_passages_own_characters(tmp_path):
    """Hunter's note (queue, kept with textutil): a quote is matched loosely (case, quote marks, superscripts), so
    every place that stores a quote must store the passage's own characters, never the words as typed."""
    from enlens_claims import profile

    f = tmp_path / "valley.txt"
    f.write_text(TEXT5 * 2, encoding="utf-8")
    ws = Workspace.create(tmp_path / "ws")
    ingest.ingest(ws, [f], ocr=OFF, ai_access="cloud")
    pid = ws.scalar("SELECT passage_id FROM passages ORDER BY start LIMIT 1")
    profile.add_label(ws, "sdg", pid, "6.4", quote="THE PLANT'S WATER USE rose to 10³")
    assert ws.scalar("SELECT quote FROM labels WHERE passage_id=?", (pid,)) == "The plant’s water use rose to 10³"


def test_an_ais_link_keeps_the_quotes_in_the_passages_own_characters(tmp_path):
    """Sibling: a link task's two quotes were stored as the AI wrote them (`tasks._store_link`), not as the passages
    hold them, so the Concepts page showed words the documents do not hold (another case, straight quote marks)."""
    from enlens_claims import tasks

    payload = {"terms": [
        {"n": 1, "term_id": "t1", "label": "water use",
         "snippets": [{"passage_id": "d1:0001", "title": "Report", "text": TEXT5}]},
        {"n": 2, "term_id": "t2", "label": "wells",
         "snippets": [{"passage_id": "d1:0002", "title": "Report", "text": "Their “wells will run dry” soon."}]}]}
    answer = {"relations": [{"a": 1, "b": 2, "relation": "shapes", "confidence": 0.8,
                             "quote_a": "the plant's water use ROSE", "quote_b": '"wells will run dry"'}]}
    ws = Workspace.create(tmp_path / "ws")
    with ws.connect() as cx:
        ok, errors = tasks._store_link(cx, None, payload, answer, "m")
        stored = cx.execute("SELECT quote_a, quote_b FROM concept_links").fetchone()
    assert ok and errors == []
    assert tuple(stored) == ("The plant’s water use rose", "“wells will run dry”")


# ---- 6. reader 7's documented limit: a real running head in a transcript with a blank line between turns ----------
def _header_transcript() -> str:
    head = "Interview 3 - confidential draft"
    turns = []
    for i in range(72):
        if i % 12 == 0:
            turns.append(head)
        turns.append(f"Speaker {i % 2}: We answered the question number {i} as well as we could at the time.")
    return "\n\n".join(turns) + "\n"


def test_a_running_head_in_a_transcript_with_blank_lines_stays_in_the_text_as_the_manual_says(tmp_path):
    """Fixer of phase 1 left, review note (reading.md): reader 7 keeps a real running head of a transcript with a
    blank line between turns when it never falls mid-sentence (reader 6 set it aside). The documented limit: the
    manual's paragraph on reader 7 and the changelog say so."""
    from enlens_claims import measure

    p = tmp_path / "header_transcript.txt"
    p.write_text(_header_transcript(), encoding="utf-8")
    raw = ingest.read_file(p, OFF)
    d6 = ingest.build_document(ingest.read_file(p, OFF), reader=6)
    d7 = ingest.build_document(raw, reader=7)
    head = "Interview 3 - confidential draft"
    assert measure.body_text(d6).count(head) == 0 and measure.body_text(d7).count(head) == 6
    manual = " ".join((ROOT / "docs/manual/how-documents-are-read.md").read_text("utf-8").split())
    assert ("a running head that never falls in the middle of a sentence can now stay in the text, and so can a "
            "header line repeated in an interview typed with a blank line between turns") in manual


# ---- 7. a zip first added before phase 1, added again ---------------------------------------------------------------
def test_a_zip_first_added_before_its_folder_was_named_by_content_is_unpacked_once_more_and_adds_nothing(tmp_path):
    """Fixer of phase 1 left, review note: the unpack folder is now named by the zip's path and content, so a zip
    first added before (folder named by its path alone) is unpacked once more when added again; its documents are
    not added twice and keep their originals, as the changelog says."""
    ws = Workspace.create(tmp_path / "ws")
    z = tmp_path / "sources.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("report.txt", _long("the reservoir", seed=8))
        zf.writestr("wells.txt", _long("the wells", seed=9))
    ingest.ingest(ws, [z], ocr=OFF, ai_access="cloud")
    # as an earlier version left it: the folder named by the zip's path only, the documents pointing into it
    inputs = ws.root / "inputs"
    (new_dir,) = [p for p in inputs.iterdir() if p.is_dir()]
    old_dir = inputs / f"sources-{hashlib.sha1(str(z.resolve()).encode()).hexdigest()[:8]}"
    new_dir.rename(old_dir)
    with ws.connect() as cx:
        for d, path in cx.execute("SELECT doc_id, path FROM documents").fetchall():
            cx.execute("UPDATE documents SET path=? WHERE doc_id=?", (str(old_dir / Path(path).name), d))
    again = ingest.ingest(ws, [z], ocr=OFF)
    assert again["added"] == 0 and again["duplicates"] == 2
    assert len([p for p in inputs.iterdir() if p.is_dir()]) == 2     # one more unpacked copy, as said
    assert ws.scalar("SELECT COUNT(*) FROM documents") == 2
    for (d,) in ws.query("SELECT doc_id FROM documents"):
        assert sources.original_file(ws, d)["available"]
    assert "A zip first added with an earlier version is unpacked once more" in " ".join(
        (ROOT / "CHANGELOG.md").read_text("utf-8").split())


# ---- 8. a guessed encoding is shown --------------------------------------------------------------------------------
SHORT_PL = "Wartość ścieków w źródłach była niska."


def test_a_short_polish_latin_2_text_is_read_right_and_the_guess_is_in_the_reading_report(tmp_path):
    """Review note (reading.md): a short Polish Latin-2 text with no ę, ń or ą read as Windows-1252 under the first
    reader 7 (fixed after review). The manual says the encoding is a guess; the reading report now says which
    encoding was taken, so a person can see a wrong guess."""
    assert ingest.decode_text(SHORT_PL.encode("iso8859-2")) == SHORT_PL
    p = tmp_path / "raport.txt"
    p.write_bytes((SHORT_PL + " " + _long("the river", n=3, seed=2)).encode("iso8859-2"))
    doc = ingest.read_document(p)
    assert doc.reading.get("encoding_guess") == "ISO-8859-2"
    u = tmp_path / "utf8.txt"
    u.write_text(SHORT_PL + " " + _long("the river", n=3, seed=2), encoding="utf-8")
    assert "encoding_guess" not in ingest.read_document(u).reading       # UTF-8: nothing guessed
    w = tmp_path / "western.txt"
    w.write_bytes(("Le café était très bon à Genève. " * 8).encode("cp1252"))
    assert ingest.read_document(w).reading.get("encoding_guess") == "Windows-1252"
    manual = " ".join((ROOT / "docs/manual/how-documents-are-read.md").read_text("utf-8").split())
    assert "A file names no encoding, so this is a guess" in manual
    assert "The document's Reading says which encoding was taken" in manual


def test_reader_6_reading_of_a_latin_2_file_reports_its_own_guess(tmp_path):
    p = tmp_path / "raport.txt"
    p.write_bytes(("Wartość ścieków w źródłach wody pitnej rośnie. " * 6).encode("iso8859-2"))
    raw = ingest.read_file(p, OFF)
    assert ingest.build_document(raw, reader=7).reading["encoding_guess"] == "ISO-8859-2"
    six = ingest.build_document(ingest.read_file(p, OFF), reader=6)
    guess = six.reading["encoding_guess"]    # what readers 1 to 6 took it for (the Windows reading), said as such
    assert guess in ("Windows-1250", "Windows-1252")
    assert p.read_bytes().decode({"Windows-1250": "cp1250", "Windows-1252": "cp1252"}[guess]).startswith(six.text[:20])


# ---- 9. the offer of reader 7: the preview says when nothing changes ------------------------------------------------
def test_the_preview_of_the_move_says_whether_the_document_reads_otherwise(tmp_path, monkeypatch):
    """Review note (reading.md): every reader-6 text, Word and web document is offered reader 7 (the owner accepted
    it); the manual says "the preview of the move says what changes". A plain Word file reads exactly as before, a
    Word file with a text box does not: the preview says which."""
    from test_hunt1_readers import _p, _text_box, _word

    from enlens_claims import reread

    rng = random.Random(3)
    boxed = _word(tmp_path / "boxed.docx", "".join(_p(_sentence(rng)) for _ in range(4))
                  + _text_box("Forty wells ran dry in the boxed summary.") + "".join(_p(_sentence(rng)) for _ in range(4)))
    plain = _word(tmp_path / "plain.docx", "".join(_p(_sentence(rng)) for _ in range(8)))
    ws = Workspace.create(tmp_path / "ws")
    with monkeypatch.context() as mp:
        mp.setattr(ingest, "READER", 6)
        ingest.ingest(ws, [boxed, plain], ocr=OFF, ai_access="cloud")
    docs = {Path(r[1]).name: r[0] for r in ws.query("SELECT doc_id, path FROM documents")}
    assert reread.preview(ws, docs["plain.docx"])["same_reading"] is True
    assert reread.preview(ws, docs["boxed.docx"])["same_reading"] is False


# ---- notes/readers.md: the rest ---------------------------------------------------------------------------------------
def test_a_utf_16_text_without_a_byte_order_mark_keeps_its_letters(tmp_path):
    """notes/readers.md, Not proven: UTF-16 without a byte-order mark was read as UTF-8 with a NUL between letters
    (plain-ASCII UTF-16 is valid UTF-8). Reader 7 (unreleased) reads it as UTF-16; readers 1 to 6 as before."""
    text = "Wartość ścieków w źródłach była niska. The reservoir held water through the dry season. " * 4
    for enc in ("utf-16-le", "utf-16-be"):
        data = text.encode(enc)
        assert ingest.decode_text(data) == text, enc
        # readers 1 to 6 read it as before: with a NUL beside every letter (review wave 4: this line compared reader 6
        # with itself)
        assert ingest.decode_text(data, reader=6).count("\x00") >= len(text) // 2, enc
        plain = "The reservoir held water through the dry season. " * 4   # (ASCII: exactly the UTF-8 reading)
        assert ingest.decode_text(plain.encode(enc), reader=6) == plain.encode(enc).decode("utf-8"), enc
        p = tmp_path / f"{enc}.txt"
        p.write_bytes(data)
        raw = ingest.read_file(p, OFF)
        assert "\x00" not in ingest.build_document(raw, reader=7).text
        old = ingest.build_document(ingest.read_file(p, OFF), reader=6).text
        assert old == ingest.build_document(raw.as_read_by(6), reader=6).text
    assert ingest.decode_text("plain words".encode("utf-8")) == "plain words"


def test_reader_1_keeps_a_hyphen_before_an_accented_letter_and_the_current_reader_joins_it(tmp_path):
    """notes/readers.md, Not proven: reader 1 (`clean_page`) joins a word cut at a line end only before ASCII a-z
    ("fejlő-\\ndés" stays apart). Reader 1 is frozen (documents it read keep their reading); the current reader joins
    such words, so a document moved to it is read right."""
    line = ("A gazdasági fejlő-\ndés lassú volt, és a régió vízkészlete csökkent az évek során, mondja a jelentés.\n"
            "A fejlődés azóta gyorsabb.\n")
    p = tmp_path / "hu.txt"
    p.write_text(line * 6, encoding="utf-8")
    raw = ingest.read_file(p, OFF)
    assert "fejlődés lassú" not in ingest.build_document(raw, reader=1).text
    assert "fejlődés lassú" in ingest.build_document(ingest.read_file(p, OFF), reader=7).text


def test_word_footnotes_and_comments_are_left_out_as_the_manual_says(tmp_path):
    """notes/readers.md, Not proven: footnotes, endnotes, headers and comments of a Word file are not read: the
    manual says so ("Footnotes and comments are not read"), so a decision, not a fault."""
    from test_hunt1_readers import _NS, _p

    rng = random.Random(5)
    body = "".join(_p(_sentence(rng)) for _ in range(6))
    path = tmp_path / "notes.docx"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", f'<?xml version="1.0"?><w:document {_NS}><w:body>{body}</w:body></w:document>')
        z.writestr("word/footnotes.xml", f'<w:footnotes {_NS}><w:footnote w:id="1">{_p("A footnote on the wells.")}'
                                         "</w:footnote></w:footnotes>")
        z.writestr("word/comments.xml", f'<w:comments {_NS}><w:comment w:id="0">{_p("A reviewer comment.")}'
                                        "</w:comment></w:comments>")
    text = ingest.read_document(path).text
    assert "footnote on the wells" not in text and "reviewer comment" not in text
    manual = (ROOT / "docs/manual/how-documents-are-read.md").read_text("utf-8")
    assert "Footnotes and comments are not read." in manual


def _finder_zip(path: Path, name: str, data: bytes) -> Path:
    """A zip as macOS Finder's Compress writes it: the name decomposed (NFD), in UTF-8 without the UTF-8 flag (Python
    sets the flag for any name beyond ASCII, so the zip is written under a stand-in name of as many bytes, swapped)."""
    raw = unicodedata.normalize("NFD", name).encode("utf-8")
    stand_in = b"X" * (len(raw) - 4) + b".txt"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(stand_in.decode("ascii"), data)
    blob = path.read_bytes()
    assert blob.count(stand_in) == 2
    path.write_bytes(blob.replace(stand_in, raw))
    with zipfile.ZipFile(path) as z:
        assert not z.infolist()[0].flag_bits & 0x800
    return path


def test_a_finder_zip_with_an_accented_name_added_by_path_keeps_an_original_that_opens(tmp_path):
    """notes/readers.md, NEEDS WINDOWS: a zip made by Finder holding "Ábel Gergő.txt", added by its path: the document's
    original opens (`sources.original_file`). Platform-free; the next test runs it on Windows in an accented folder."""
    z = _finder_zip(tmp_path / "forrás.zip", "Ábel Gergő.txt", _long("a falu kútjai", seed=6).encode("utf-8"))
    ws = Workspace.create(tmp_path / "ws")
    stats = ingest.ingest(ws, [z], ocr=OFF, ai_access="cloud")
    assert stats["added"] == 1
    d, path = ws.query("SELECT doc_id, path FROM documents")[0]
    assert unicodedata.normalize("NFC", Path(path).name) == "Ábel Gergő.txt"
    got = sources.original_file(ws, d)
    assert got["available"] and Path(got["path"]).is_file()


@pytest.mark.skipif(os.name != "nt", reason="Windows: an accented user folder, as on the owner's PC")
def test_a_finder_zip_with_an_accented_name_opens_on_windows_in_an_accented_folder(tmp_path):
    home = tmp_path / "Ábel Gergő"
    home.mkdir()
    z = _finder_zip(home / "forrás.zip", "Ábel Gergő.txt", _long("a falu kútjai", seed=6).encode("utf-8"))
    ws = Workspace.create(home / "projekt")
    assert ingest.ingest(ws, [str(z)], ocr=OFF, ai_access="cloud")["added"] == 1
    d = ws.query("SELECT doc_id FROM documents")[0][0]
    got = sources.original_file(ws, d)
    assert got["available"] and Path(got["path"]).read_bytes() == _long("a falu kútjai", seed=6).encode("utf-8")
    ws.close_all()


# ---- the page: what the fixes above say to a person -----------------------------------------------------------------
PROBE = r"""
async function documents(t) {
  t.state({ settings: {} });
  t.answer("GET /api/projects/Study", { search: null, passages: 0, ai_access: { chosen: true, default: "cloud" } });
  t.answer(/^GET \/api\/projects\/Study\/documents(\?.*)?$/, { documents: [], ai_access: {}, new_reader: 7 });
  t.answer(/^GET \/api\/projects\/Study\/document-roles/, { roles: {}, nonscientific: [] });
  t.answer("GET /api/projects/Study/nonscientific-suggestions", { suggested: {} });
  t.answer("GET /api/projects/Study/map/documents?*", t.fail(404, "no answers yet"));
  t.answer("GET /api/projects/Study/hypotheses", { hypotheses: [] });
  await t.render("views/sources.js", "renderSources");
}
await scenario("documents: an add stopped while a file's reading hung", async (t) => {
  await documents(t);
  const input = t.view.querySelector("#src-files");
  input.files = [new File(["a"], "a.txt"), new File(["b"], "b_hangs.txt"), new File(["c"], "c.txt")];
  input.dispatchEvent(new Event("change"));
  await t.settle();
  t.answer(/^POST \/api\/projects\/Study\/uploads/, (b, path) => ({ batch: "b", name: decodeURIComponent(path.split("name=")[1]), size: 1 }));
  t.answer("POST /api/projects/Study/ingest", { job: { id: "ji" } });
  let state = "running";
  t.answer("GET /api/jobs/ji", () => (state === "running" ? { id: "ji", state, progress: { done: 1, total: 3, file: "b_hangs.txt" } }
    : { id: "ji", state, progress: {}, result: { added: 1, duplicates: 0, stopped: true, stopped_at: "b_hangs.txt", not_added: 2 } }));
  await t.click(/^Add these 3 documents/);
  await t.settle(3000);
  const waiting = t.text(t.view.querySelector(".pb"));
  state = "done";
  await t.settle(3000);
  return { waiting, after: t.text(t.view.querySelector(".pb")), all: t.text(t.view) };
});
const DOC = "/api/projects/Study/documents/d1";
async function docPage(t, d) {
  t.state({ settings: {} });
  t.answer(`GET ${DOC}?*`, { doc_id: "d1", title: "Raport", file: "raport.txt", kind: "text", total_blocks: 1,
    blocks: [{ n: 0, kind: "body", text: "Wartość ścieków w źródłach była niska.", start: 0, end: 38 }], ...d });
  t.answer(/^GET \/api\/projects\/Study\/documents\/d1\/role/, { role: null });
  t.answer(`GET ${DOC}/nonscientific-suggestion`, { suggested: false });
  t.answer(`GET ${DOC}/notes`, { notes: [] });
  t.answer(`GET ${DOC}/file?*`, {});
  await t.render("views/doc-page.js", "renderDocument", ["d1"], { tab: "reading" });
}
await scenario("document page: the encoding guessed for a text file", async (t) => {
  await docPage(t, { reader: 7, new_reader: 7, reading: { reader: 7, quality: "good", encoding_guess: "ISO-8859-2" } });
  return t.text(t.view.querySelector(".dv-panel"));
});
for (const same of [true, false]) {
  await scenario(`document page: the preview of the move, read the same: ${same}`, async (t) => {
    await docPage(t, { kind: "docx", file: "plain.docx", reader: 6, new_reader: 7, new_reader_changes: true, reading: { reader: 6, quality: "good" } });
    t.answer(`GET ${DOC}/reread`, { ok: true, counts: {}, not_placed: [], left_out: [], warnings: [], same_reading: same,
      reading: { quality: "good", body_passages: 3, warnings: [] } });
    await t.click("Read with the new reader");
    await t.settle();
    return t.text(t.view.querySelector(".dv-reread"));
  });
}
"""


@pytest.fixture(scope="module")
def views(tmp_path_factory):
    from _views import NODE, run_views

    if not NODE:
        pytest.skip("node is not installed")
    return run_views(PROBE, tmp_path_factory.mktemp("readers15"))


def test_the_page_names_the_file_being_read_and_after_stop_says_how_to_add_the_others(views):
    r = views["documents: an add stopped while a file's reading hung"]
    assert "Reading b_hangs.txt (2 of 3)" in r["waiting"]
    assert "Stopped while reading b_hangs.txt: it and 1 more file were not added." in r["after"]
    assert "add the same files again" in r["after"] and "Leave out files whose name matches" in r["after"]
    assert "Stopped\n" in r["all"] and "Documents added" not in r["all"]


def test_the_reading_panel_says_which_encoding_was_guessed(views):
    assert "Read as: ISO-8859-2, a guess" in views["document page: the encoding guessed for a text file"]


def test_the_preview_of_the_move_says_when_nothing_would_change(views):
    assert "reads this document exactly as before" in views["document page: the preview of the move, read the same: true"]
    other = views["document page: the preview of the move, read the same: false"]
    assert "otherwise than before" in other and "exactly as before" not in other


# ---- review wave 4 (READERS15-5): every kind of store that writes a quote keeps the passage's own characters -------
SPECIAL = ("Patients took the ﬁnal dose of 10³ mg each morning, as the protocol of the trial in the valley "
           "required, and the nurses wrote down every dose they gave in the ward book.")
TYPED = "THE FINAL dose of 10³ mg each"                      # case, the ligature and the space typed otherwise
OWN = SPECIAL[SPECIAL.index("the ﬁnal"):SPECIAL.index(" each") + 5]   # what the passage holds there


@pytest.fixture
def special(tmp_path):
    """A project of one document of one passage whose text holds a ligature, a superscript digit and a non-breaking
    space (written in after reading: the reader puts ligatures and odd spaces right, while text from an earlier
    reading, a kept excerpt or a colleague's copy may still hold them). -> (ws, doc_id, passage_id)."""
    plain = SPECIAL.replace("ﬁ", "fi").replace(" ", " ")
    f = tmp_path / "trial.txt"
    f.write_text(plain + "\n", encoding="utf-8")
    ws = Workspace.create(tmp_path / "ws")
    ingest.ingest(ws, [f], ocr=OFF, ai_access="cloud")
    d = ws.scalar("SELECT doc_id FROM documents")
    (pid,) = [r[0] for r in ws.query("SELECT passage_id FROM passages")]
    with ws.connect() as cx:
        cx.execute("UPDATE documents SET text=?, n_chars=? WHERE doc_id=?", (SPECIAL, len(SPECIAL), d))
        cx.execute("UPDATE passages SET text=?, start=0, end=? WHERE passage_id=?", (SPECIAL, len(SPECIAL), pid))
        cx.execute("UPDATE blocks SET end=? WHERE doc_id=? AND end>=?", (len(SPECIAL), d, len(plain)))
    yield ws, d, pid
    ws.close_all()


def _task(ws, task_id: str, kind: str, payload: dict, answer: dict) -> None:
    """A task answered and accepted, as the queue leaves it (for the stores that read the answer back)."""
    with ws.connect() as cx:
        cx.execute("INSERT INTO tasks(task_id, kind, model, prompt_version, payload_json, status, created_at) "
                   "VALUES (?,?,?,?,?,?,?)", (task_id, kind, "m", "v1", json.dumps(payload), "done", "2026-11-19"))
        cx.execute("INSERT INTO results(task_id, attempt, kind, model, prompt_version, raw_json, valid, errors_json, "
                   "received_at) VALUES (?,?,?,?,?,?,?,?,?)", (task_id, 1, kind, "m", "v1", json.dumps(answer), 1,
                                                               "[]", "2026-11-19"))


T1 = {"task_id": "t1", "prompt_version": "v1", "status": "pending", "created_at": "2026-11-19 10:00:00"}


def test_a_verification_keeps_the_passages_own_characters(special):
    from enlens_claims import tasks

    ws, d, pid = special
    payload = {"text": SPECIAL, "passage_id": pid, "doc_id": d, "subject_kind": "vca_claim", "subject_id": "v1"}
    with ws.connect() as cx:
        ok, errors = tasks._store_verify(cx, T1, payload, {"verdict": "supports", "confidence": 0.9, "quote": TYPED}, "m")
    assert ok, errors
    assert ws.scalar("SELECT quote FROM verifications") == OWN


def test_a_checks_grade_keeps_the_passages_own_characters(special):
    from enlens_claims import tasks

    ws, d, pid = special
    payload = {"subject_kind": "user_claim", "subject_id": "c1",
               "passages": [{"passage_id": pid, "doc_id": d, "text": SPECIAL, "page": None}]}
    with ws.connect() as cx:
        ok, errors = tasks._store_verify_set(cx, T1, payload, {"evidence": [
            {"passage": 1, "verdict": "supports", "confidence": 0.9, "quote": TYPED}]}, "m")
    assert ok, errors
    assert ws.scalar("SELECT quote FROM verifications") == OWN


def test_a_label_by_the_ai_keeps_the_passages_own_characters(special):
    from enlens_claims import profile

    ws, d, pid = special
    payload = {"framework": "sdg", "text": SPECIAL, "passage_id": pid, "doc_id": d}
    with ws.connect() as cx:
        ok, errors = profile.store_labels(cx, T1, payload, {"labels": [
            {"code": "3.5", "relevance": "main", "confidence": 0.9, "quote": TYPED, "reason": "a dose"}]}, "m")
    assert ok, errors
    assert ws.scalar("SELECT quote FROM labels") == OWN


def test_a_themes_quotes_keep_the_passages_own_characters(special):
    from enlens_claims import themes

    ws, d, pid = special
    with ws.connect() as cx:
        cx.execute("INSERT INTO themes(run_id, theme_id, name, size) VALUES ('r', 1, 'Theme 1', 1)")
        ok, errors = themes.store_theme(cx, T1, {"run_id": "r", "theme_id": 1, "passages": [
            {"passage_id": pid, "text": SPECIAL}]}, {"name": "Doses", "name_quote": {"passage": 1, "quote": TYPED},
                                                    "description": "How patients took their doses each day.",
                                                    "description_quote": {"passage": 1, "quote": TYPED}}, "m")
    assert ok, errors
    q = json.loads(ws.scalar("SELECT quotes_json FROM themes"))
    assert {v["quote"] for v in q.values()} == {OWN}


def test_a_theory_codes_definition_quote_keeps_the_passages_own_characters(special):
    from enlens_claims import theorycodes

    ws, d, pid = special
    _task(ws, "tc1", "theory_codes", {"doc_id": d, "part": 1, "passages": [{"passage_id": pid, "text": SPECIAL}]},
          {"concepts": [{"name": "Dosing", "reason": "said", "definition": {"passage": 1, "quote": TYPED}}]})
    (c,) = theorycodes._part_concepts(ws, "tc1")
    assert c["definition"]["quote"] == OWN


def test_a_code_definitions_examples_keep_the_passages_own_characters(special):
    from enlens_claims import codedefine

    ws, d, pid = special
    _task(ws, "cd1", "code_definition", {"code": "Dosing", "passages": [{"passage_id": pid, "text": SPECIAL}]},
          {"definition": "Patients taking the doses they were given.", "definition_quote": {"passage": 1, "quote": TYPED},
           "when_to_use": "When a dose is taken.", "when_to_use_quote": {"passage": 1, "quote": TYPED},
           "when_not_to_use": "", "note": None})
    got = codedefine.draft_of(ws, "cd1")
    assert {v["quote"] for v in got["quotes"].values()} == {OWN}


def test_a_group_names_quote_keeps_the_passages_own_characters(special):
    from enlens_claims import groupnames

    ws, d, pid = special
    _task(ws, "gn1", "group_name", {"passages": [{"passage_id": pid, "text": SPECIAL}], "concept_ids": ["a", "b"],
                                    "labels": {}}, {"name": "Daily doses", "name_quote": {"passage": 1, "quote": TYPED}})
    groupnames.apply(ws, "gn1")
    assert ws.scalar("SELECT quote FROM concept_group_quotes") == OWN


def test_a_references_mention_keeps_the_passages_own_characters(special):
    from enlens_claims import references

    ws, d, pid = special
    payload = {"doc_id": d, "passages": [{"n": 1, "passage_id": pid, "text": SPECIAL}]}
    with ws.connect() as cx:
        ok, errors = references.store_resolve(cx, T1, payload, {"chains": [{"name": "the dose", "mentions": [
            {"passage": 1, "span": TYPED, "mention": "FINAL dose of 10³ mg", "named": True},
            {"passage": 1, "span": "every dose they gave", "mention": "every dose"}]}]}, "m")   # (a chain needs two)
    assert ok, errors
    assert ws.scalar("SELECT text FROM mentions ORDER BY start LIMIT 1") == OWN[4:-5]   # "ﬁnal dose of 10³ mg"


@pytest.mark.parametrize("words", ["A note on the dose.", ""])   # a note, and a highlight (no words)
def test_a_note_or_highlight_keeps_the_documents_own_characters(special, words):
    from enlens_claims import notes

    ws, d, pid = special
    a = SPECIAL.index(OWN)
    notes.add(ws, d, a, a + len(OWN), quote=TYPED, text=words)
    assert ws.scalar("SELECT quote FROM notes") == OWN


def test_a_judgements_sentence_keeps_the_passages_own_characters(special):
    from enlens_claims import judgements

    ws, d, pid = special
    with ws.connect() as cx:
        cx.execute("INSERT INTO verifications(ver_id, subject_kind, subject_id, passage_id, doc_id, verdict, confidence, "
                   "quote) VALUES ('v9', 'user_claim', 'c1', ?, ?, 'supports', 0.9, ?)", (pid, d, OWN))
    judgements.set_judgement(ws, "c1", pid, "supports", quote=TYPED)
    assert ws.scalar("SELECT quote FROM judgements") == OWN


def test_a_quote_on_one_line_keeps_every_character_but_its_line_breaks():
    """The helper the stores above share (also the theory framework's quotes, the text patterns' quotes, a theory
    document's examples and the notes' Markdown export): line breaks become one space, nothing else changes."""
    from enlens_claims import textutil

    assert textutil.one_line("the ﬁnal dose\n  of 10³ mg  each \r\n") == "the ﬁnal dose of 10³ mg each"


def test_same_reading_counts_each_passages_section_and_what_its_blocks_let_searches_read():
    """Review wave 4 (READERS15-9): `same_reading` compared text and passage places only, so a passage turned from a
    running head (left out) into body at the same offsets was "exactly as before". A made-up pair of readings."""
    from enlens_claims.reread import same_reading

    text = "Interview 3\\n\\nQ: Why?\\n\\nA: Because."
    passages = [(0, 11, None, "left_out"), (13, 20, None, "body"), (22, 32, None, "body")]
    blocks = [(0, 11, 0), (13, 20, 1), (22, 32, 1)]
    assert same_reading(text, passages, blocks, text, list(passages), list(blocks))
    flipped = [(0, 11, None, "body")] + passages[1:]
    assert not same_reading(text, passages, blocks, text, flipped, blocks)
    assert not same_reading(text, passages, blocks, text, passages, [(0, 11, 1)] + blocks[1:])
    assert not same_reading(text, passages, blocks, text + " ", passages, blocks)
    # with a person's choices the stored sections hold them and the new ones not yet: the blocks decide
    assert same_reading(text, passages, blocks, text, flipped, blocks, choices=True)
    assert not same_reading(text, passages, blocks, text, flipped, [(0, 11, 1)] + blocks[1:], choices=True)


# ---- review wave 4 (READERS15-4): Stop reaches a hung reading on every route of the app ---------------------------
def _hangs_here(monkeypatch, seconds: float = 30) -> None:
    """The same stand-in reader in this process: a reading here would hang `seconds` (the old route of a small batch)."""
    real = ingest._read_whole

    def read(f, *a, **k):
        if f.name == "b_hangs.txt":
            time.sleep(seconds)
        return real(f, *a, **k)

    monkeypatch.setattr(ingest, "_read_whole", read)


def _stopped_after(named: list, seconds: float = 1.0):
    return lambda: any(n == "b_hangs.txt" and time.monotonic() - at > seconds for n, at in named)


def test_stop_ends_a_hung_reading_in_a_small_batch_read_one_at_a_time(tmp_path, monkeypatch):
    """A batch under 512 KB is read one file at a time (the common case). It was read in the app's own process, where
    Stop is seen only between files and between OCR pages, so a reading that hung was waited for for ever. With Stop to
    obey, it is read in a reading process too, and Stop ends it."""
    monkeypatch.delenv("ENLENS_READ_HERE", raising=False)   # as the app reads (the tests read here otherwise)
    folder = _folder(tmp_path, ["a.txt", "b_hangs.txt", "c.txt"])
    started = _worker_code(monkeypatch, _HANGS)
    _hangs_here(monkeypatch)
    named: list = []
    ws = Workspace.create(tmp_path / "ws")
    assert ingest.read_workers(sorted(folder.iterdir())) == 1
    t0 = time.monotonic()
    stats = ingest.ingest(ws, [folder], ocr=OFF, ai_access="cloud",
                          progress=lambda i, n, name: named.append((name, time.monotonic())),
                          should_stop=_stopped_after(named))
    assert time.monotonic() - t0 < 15
    assert stats["stopped"] is True and stats["added"] == 1 and stats.get("stopped_at") == "b_hangs.txt"
    assert "read_at_once" not in stats
    assert started and all(p.poll() is not None for p in started)


_QUITS_THEN_HANGS = ("import os, time; from enlens_claims import ingest as _i; _r = _i._read_whole; "
                     "_i._read_whole = lambda f, *a, **k: ((os._exit(0) if not os.path.exists(str(f) + '.tried') and "
                     "not open(str(f) + '.tried', 'w').close() else time.sleep(600)) if f.name == 'b_hangs.txt' "
                     "else _r(f, *a, **k))")


def test_stop_ends_a_hung_reading_after_its_first_reading_process_ended_on_its_own(tmp_path, monkeypatch):
    """A file whose reading process ended on its own was read here, where Stop could not end it. It is read once more
    in a new reading process, where Stop reaches it."""
    monkeypatch.delenv("ENLENS_READ_HERE", raising=False)
    folder = _folder(tmp_path, ["a.txt", "b_hangs.txt", "c.txt"])
    started = _worker_code(monkeypatch, _QUITS_THEN_HANGS)
    _hangs_here(monkeypatch)
    named: list = []
    ws = Workspace.create(tmp_path / "ws")
    t0 = time.monotonic()
    stats = ingest.ingest(ws, [folder], ocr=OFF, ai_access="cloud", workers=2,
                          progress=lambda i, n, name: named.append((name, time.monotonic())),
                          should_stop=_stopped_after(named))
    assert time.monotonic() - t0 < 15
    assert (folder / "b_hangs.txt.tried").exists()        # its first reading process ended on its own
    assert stats["stopped"] is True and stats.get("stopped_at") == "b_hangs.txt"
    assert all(p.poll() is not None for p in started)


def test_without_stop_a_small_batch_is_still_read_here(tmp_path, monkeypatch):
    """The command line and the connector have no Stop: a small batch is read here, as before (no process started)."""
    monkeypatch.delenv("ENLENS_READ_HERE", raising=False)
    folder = _folder(tmp_path, ["a.txt", "c.txt"])
    started = _worker_code(monkeypatch, "pass")
    ws = Workspace.create(tmp_path / "ws")
    assert ingest.ingest(ws, [folder], ocr=OFF, ai_access="cloud")["added"] == 2 and started == []
