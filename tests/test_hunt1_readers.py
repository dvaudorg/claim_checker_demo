"""Phase 1 reading hunt, area `readers`: files into documents and passages, and reading a document again.

Each test asserts what ENLENS should do and fails today for the reason in its docstring.
"""
from __future__ import annotations

import random
import zipfile
from pathlib import Path

from helpers import make_pdf
from test_reader3 import _sentence

from enlens_claims import ingest, measure, sources, textutil
from enlens_claims.store import Workspace

OFF = ingest.OcrOptions(mode="off")

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_NS = (f'xmlns:w="{_W}" '
       'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
       'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
       'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
       'xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape" '
       'xmlns:v="urn:schemas-microsoft-com:vml"')


def _p(text: str) -> str:
    return f'<w:p><w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:p>'


def _word(path: Path, body: str) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml",
                   f'<?xml version="1.0" encoding="UTF-8"?><w:document {_NS}><w:body>{body}</w:body></w:document>')
    return path


def _text_box(words: str) -> str:
    """A text box as Word saves it: the shape (mc:Choice) and its older VML copy (mc:Fallback), both with the words."""
    inner = f"<w:txbxContent>{_p(words)}</w:txbxContent>"
    return ("<w:p><w:r><w:t>The paragraph that holds the box.</w:t></w:r><w:r><mc:AlternateContent>"
            '<mc:Choice Requires="wps"><w:drawing><wp:anchor><wp:docPr id="1" name="Text Box 1"/><a:graphic>'
            f"<a:graphicData><wps:wsp><wps:txbx>{inner}</wps:txbx></wps:wsp></a:graphicData></a:graphic></wp:anchor>"
            "</w:drawing></mc:Choice>"
            f"<mc:Fallback><w:pict><v:shape><v:textbox>{inner}</v:textbox></v:shape></w:pict></mc:Fallback>"
            "</mc:AlternateContent></w:r></w:p>")


def test_a_word_text_box_is_not_read_twice(tmp_path):
    """Word keeps a text box twice (the shape and its VML fallback); `para_text` walks every descendant of the
    paragraph (`p.iter()`, ingest.py:419), so the box's words are read twice (the manual says text boxes are not read)."""
    rng = random.Random(1)
    body = "".join(_p(_sentence(rng)) for _ in range(6)) + _text_box("Forty wells ran dry in the boxed summary.") \
        + "".join(_p(_sentence(rng)) for _ in range(6))
    path = _word(tmp_path / "boxed.docx", body)
    doc = ingest.read_document(path)
    assert doc.text.count("Forty wells ran dry") <= 1


def _transcript() -> tuple[str, str, int]:
    """An interview typed with a blank line between turns, the interviewer asking the same follow-up question now and
    then: (the text, the question, how often it is asked)."""
    rng = random.Random(7)
    q = "I: Could you tell me a little more about that?"
    turns, asked = [], 0
    for i in range(90):
        turns.append(f"{'I' if i % 2 == 0 else 'R'}: {_sentence(rng)}")
        if i in (14, 31, 45, 62, 80):
            turns.append(q)
            asked += 1
    return "\n\n".join(turns) + "\n", q, asked


def test_an_interviewers_repeated_question_stays_in_the_text(tmp_path):
    """A transcript with a blank line between turns: every line is next to a blank line, so a question asked five times
    is taken for a running head (reader3.text_furniture, reader3.py:131-140) and left out of the passages."""
    text, q, asked = _transcript()
    path = tmp_path / "interview_03.txt"
    path.write_text(text, encoding="utf-8")
    doc = ingest.read_document(path)
    assert measure.body_text(doc).count(q) == asked


def test_a_text_file_with_short_paragraphs_one_per_line_has_a_paragraph_per_line(tmp_path):
    """Word's "plain text" of a document whose paragraphs are under 160 characters (survey answers, notes): no wrap
    width and no long lines (reader4.paragraph_lines, reader4.py:30-32), so the file is one paragraph, every quote
    cited as paragraph 1."""
    rng = random.Random(5)
    lines = []
    for i in range(40):
        s = f"Answer {i + 1}: " + _sentence(rng)
        lines.append(s[:150].rsplit(" ", 1)[0].rstrip(",.") + "." if len(s) > 150 else s)
    path = tmp_path / "survey_answers.txt"
    path.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
    ws = Workspace.create(tmp_path / "ws")
    ingest.ingest(ws, [path], ocr=OFF)
    n = ws.query("SELECT COUNT(*) FROM paragraphs")[0][0]
    assert n >= len(lines) - 2


def test_a_zip_added_again_with_new_files_keeps_the_first_documents_original(tmp_path):
    """sources.zip added, then a newer sources.zip at the same place: both unpack into one folder of `inputs/`
    (ingest.discover, ingest.py:1266-1268), so the first document's original is overwritten and reported as changed."""
    ws = Workspace.create(tmp_path / "ws")
    z = tmp_path / "sources.zip"
    pdf = tmp_path / "report.pdf"
    make_pdf(pdf, ["The first report says the reservoir held water through the whole dry season of the year. " * 3])
    with zipfile.ZipFile(z, "w") as zf:
        zf.write(pdf, "report.pdf")
    ingest.ingest(ws, [z], ocr=OFF)
    first = ws.query("SELECT doc_id FROM documents")[0][0]
    assert sources.original_file(ws, first)["available"]
    make_pdf(pdf, ["The second report, a year later, says the reservoir ran dry before the end of summer. " * 3])
    with zipfile.ZipFile(z, "w") as zf:
        zf.write(pdf, "report.pdf")
    ingest.ingest(ws, [z], ocr=OFF)
    assert ws.query("SELECT COUNT(*) FROM documents")[0][0] == 2
    assert sources.original_file(ws, first)["available"]


def test_a_damaged_zip_is_reported_by_name(tmp_path):
    """A zip cut off in a download (no central directory) is not a zip to `zipfile.is_zipfile` and not a supported
    file either: `discover` (ingest.py:1262-1288) passes it over without a word, so the add says nothing about it."""
    good = tmp_path / "good.zip"
    pdf = tmp_path / "a.pdf"
    make_pdf(pdf, ["Text of a report on water use in the valley, long enough to be a document of its own. " * 3])
    with zipfile.ZipFile(good, "w") as zf:
        zf.write(pdf, "a.pdf")
        zf.writestr("b.txt", "A note on the valley's farms and their wells, long enough to be stored as text. " * 3)
    cut = tmp_path / "sources.zip"
    cut.write_bytes(good.read_bytes()[:-60])
    assert not zipfile.is_zipfile(cut)
    ws = Workspace.create(tmp_path / "ws")
    stats = ingest.ingest(ws, [cut], ocr=OFF)
    assert any("sources.zip" in f for f in stats.get("failed", []))


def test_a_polish_text_file_in_latin_2_keeps_its_letters(tmp_path):
    """A .txt saved as ISO-8859-2 (Latin-2) is read as Windows-1250 or -1252 only (`_single_byte`, ingest.py:249):
    ą, ś and ź come out as ±, ¶ and Ľ, and the words cannot be found."""
    text = ("Wartość ścieków w źródłach wody pitnej rośnie. Ślady zanieczyszczeń w każdej próbce, ąę, były "
            "wyraźne i świeże. Mieszkańcy wsi zgłaszali, że woda ma dziwny zapach.\n") * 3
    path = tmp_path / "raport.txt"
    path.write_bytes(text.encode("iso8859-2"))
    doc = ingest.read_document(path)
    assert "Wartość ścieków w źródłach" in doc.text


def test_a_quote_is_found_in_text_with_a_right_to_left_mark(tmp_path):
    """Text with an invisible left-to-right or right-to-left mark (U+200E, U+200F; Arabic, Hebrew and mixed text from
    PDFs and Word): the mark is not dropped by normalisation (textutil._CHAR_MAP, textutil.py:11-18), so a quote of the
    words as a person or a model reads them is not found."""
    hay = "The survey of 2024 shows that costs rose by ‏15 percent in the northern districts."
    assert textutil.find_quote(hay, "costs rose by 15 percent") is not None


# ------------------------------------------------------------------------------------------------------------------
# The fixes: reader 7 (READERS-2 to -5), what it keeps, and what readers 3 to 6 still read
# ------------------------------------------------------------------------------------------------------------------
import json  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402
import textwrap  # noqa: E402

import pytest  # noqa: E402

from _fakedom import NODE  # noqa: E402

from enlens_claims import languages, reader  # noqa: E402

Q = "I: Could you tell me a little more about that?"


def _build(path: Path, version: int):
    return reader.build_document(ingest.read_file(path), version=version)


def _turns() -> list[str]:
    rng = random.Random(7)
    out = []
    for i in range(90):
        out.append(f"{'I' if i % 2 == 0 else 'R'}: {_sentence(rng)}")
        if i in (14, 31, 45, 62, 80):
            out.append(Q)
    return out


def test_reader_7_is_the_current_reader_and_reader_6_still_sets_the_question_aside(tmp_path):
    """Readers 3 to 6 read exactly as before (a document keeps its reading until it is moved): reader 6 still sets the
    interviewer's question aside, reader 7 keeps it."""
    assert reader.READER == ingest.READER == 7
    text, q, asked = _transcript()
    path = tmp_path / "interview_03.txt"
    path.write_text(text, encoding="utf-8")
    assert measure.body_text(_build(path, 6)).count(q) == 0
    assert measure.body_text(_build(path, 7)).count(q) == asked


@pytest.mark.parametrize("kind", ["docx", "html"])
def test_a_question_that_comes_back_in_a_word_file_or_web_page_stays_in_the_text(tmp_path, kind):
    """Sibling of READERS-2: a Word file's and a web page's paragraphs are separated by blank lines too, so an
    interview typed in Word lost its repeated question the same way (reader 6 still does; reader 7 keeps it)."""
    turns = _turns()
    if kind == "docx":
        path = _word(tmp_path / "interview.docx", "".join(_p(t) for t in turns))
    else:
        path = tmp_path / "interview.html"
        path.write_text("<html><body>" + "".join(f"<p>{t}</p>" for t in turns) + "</body></html>", encoding="utf-8")
    assert measure.body_text(_build(path, 6)).count(Q) == 0
    assert measure.body_text(_build(path, 7)).count(Q) == 5


def _converter_copy(folder: Path, wrapped: bool) -> tuple[Path, str]:
    """Text copied out of a journal's PDF, a blank line between paragraphs, the running head between pages; `wrapped`:
    each paragraph hard-wrapped to 80 characters, else one line each (and three pages turn in mid-sentence)."""
    rng = random.Random(11)
    head = "Journal of Water Studies {n} (2020) 1-20"
    out: list[str] = []
    carried = None
    for pg in range(1, 9):
        out.append(head.format(n=pg))
        paras = [" ".join(_sentence(rng) for _ in range(3)) for _ in range(5 if wrapped else 15)]
        if carried:   # the rest of the sentence the page turned in, after the head
            paras.insert(0, carried)
            carried = None
        if pg in (2, 4, 6):   # the page turns in the middle of a sentence: the head stands between its halves
            words = _sentence(rng).split()
            paras[-1] = paras[-1] + " " + " ".join(words[:7])
            carried = " ".join(words[7:])
        for para in paras:
            out += textwrap.wrap(para, 80) if wrapped else [para]
    text = "\n\n".join(x for x in out) if not wrapped else "\n".join(out)
    if wrapped:   # a blank line between paragraphs and around the head, not between the lines of a paragraph
        text = re.sub(r"(\.)\n", r"\1\n\n", text)
    path = folder / f"journal_{'wrapped' if wrapped else 'lines'}.txt"
    path.write_text(text + "\n", encoding="utf-8")
    return path, "Journal of Water Studies"


@pytest.mark.parametrize("wrapped", [True, False])
def test_reader_7_still_finds_running_heads_of_text_copied_out_of_a_pdf(tmp_path, wrapped):
    """READERS-2's fix must not lose real running heads: in converter text with blank lines between paragraphs
    (wrapped, or one line each with pages that turn in mid-sentence) the journal's head is still set aside."""
    path, head = _converter_copy(tmp_path, wrapped)
    for v in (6, 7):
        doc = _build(path, v)
        assert head not in measure.body_text(doc), v
        assert sum(1 for b in doc.blocks if b.kind == "furniture" and head in b.text) >= 7, v


def test_reader_7_reads_the_journal_copy_of_reader_3s_test_as_reader_6(tmp_path):
    rng = random.Random(4)
    out = []
    for pg in range(1, 9):
        out.append(f"Frontiers in Neurology {pg:02d} frontiersin.org")
        out += textwrap.wrap(" ".join(_sentence(rng) for _ in range(14)), 80)
        out.append(str(pg))
        out.append("")
    p = tmp_path / "journal.txt"
    p.write_text("\n".join(out), encoding="utf-8")
    assert measure.fingerprint(_build(p, 7)) == measure.fingerprint(_build(p, 6))


def test_hard_wrapped_text_reads_as_before_with_reader_7(tmp_path):
    """READERS-4's rule is for lines that nearly all end a sentence: text hard-wrapped to one width reads as by
    reader 6."""
    rng = random.Random(9)
    lines = []
    for _ in range(12):
        lines += textwrap.wrap(" ".join(_sentence(rng) for _ in range(4)), 72)
    path = tmp_path / "wrapped.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert measure.fingerprint(_build(path, 7)) == measure.fingerprint(_build(path, 6))


def test_short_paragraphs_one_per_line_read_by_reader_6_as_before(tmp_path):
    rng = random.Random(5)
    lines = [f"Answer {i + 1}: " + _sentence(rng)[:120].rsplit(" ", 1)[0] + "." for i in range(40)]
    path = tmp_path / "survey.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    n6 = len(_build(path, 6).layout.paragraphs) if _build(path, 6).layout else 0
    d7 = _build(path, 7)
    assert n6 <= 3 and len([b for b in d7.blocks if b.kind == "body"]) >= len(lines) - 2


def test_a_word_text_box_is_a_paragraph_of_its_own_after_the_one_that_holds_it(tmp_path):
    rng = random.Random(1)
    body = "".join(_p(_sentence(rng)) for _ in range(3)) + _text_box("Forty wells ran dry in the boxed summary.") \
        + "".join(_p(_sentence(rng)) for _ in range(3))
    path = _word(tmp_path / "boxed.docx", body)
    raw = ingest.read_file(path)
    paras = raw.pages[0].split("\n\n")
    i = paras.index("The paragraph that holds the box.")
    assert paras[i + 1] == "Forty wells ran dry in the boxed summary."
    # readers 1 to 6 read it as before: twice, joined to the paragraph that holds it
    assert _build(path, 6).text.count("Forty wells ran dry") == 2
    assert ingest.read_document(path, reader=6).text.count("box.Forty wells") == 1


def test_a_text_box_in_a_table_cell_or_without_its_shape_is_read_once(tmp_path):
    """Siblings of READERS-3: a box inside a table's cell (read with the cell, once) and an older file's box that has
    only the VML copy (no mc:AlternateContent) is read once too."""
    cell_box = _text_box("Boxed words in a cell.").replace("<w:p>", "", 1)[:-len("</w:p>")]
    table = (f"<w:tbl><w:tr><w:tc><w:p>{cell_box}</w:p></w:tc><w:tc>{_p('Second cell')}</w:tc></w:tr></w:tbl>")
    vml = ("<w:p><w:r><w:t>Holder.</w:t></w:r><w:r><w:pict><v:shape><v:textbox><w:txbxContent>"
           f"{_p('Only the old copy of a box.')}</w:txbxContent></v:textbox></v:shape></w:pict></w:r></w:p>")
    rng = random.Random(2)
    body = "".join(_p(_sentence(rng)) for _ in range(3)) + table + vml
    path = _word(tmp_path / "cells.docx", body)
    text = ingest.read_document(path).text
    assert text.count("Boxed words in a cell.") == 1 and text.count("Only the old copy of a box.") == 1
    assert "Holder.Only" not in text and "box.Boxed" not in text


def test_central_european_and_western_files_read_as_before_with_reader_7(tmp_path):
    """READERS-5: Latin-2 only where it fits clearly better; Windows-1250 Hungarian, Polish and Czech and a
    Windows-1252 English text with "©" read as before, by reader 7 as by reader 6."""
    cases = {
        "hu.txt": ("Árvíztűrő tükörfúrógép. A fejlődés üteme lassú, de az őszi esők után a víz szintje nőtt.\n" * 4,
                   "cp1250"),
        "pl.txt": ("Wartość ścieków w źródłach wody pitnej rośnie. Ślady zanieczyszczeń były wyraźne.\n" * 4, "cp1250"),
        "pl_no_s.txt": ("Woda płynęła wąską rzeką przez łąkę. Żaba i ćma były obok.\n" * 4, "cp1250"),
        "cz.txt": ("Příliš žluťoučký kůň úpěl ďábelské ódy. Šťastný řidič jel přes most.\n" * 4, "cp1250"),
        "en.txt": ("Copyright © 2020 The Authors. The reservoir held water through the dry season.\n" * 4, "cp1252"),
    }
    for name, (text, enc) in cases.items():
        path = tmp_path / name
        path.write_bytes(text.encode(enc))
        assert text.split(".")[0] in ingest.read_document(path).text, name
        assert ingest.decode_text(path.read_bytes()) == text, name
        assert ingest.decode_text(path.read_bytes(), reader=6) == text, name


def test_a_czech_latin_2_file_keeps_its_letters_and_reader_6_reads_it_as_before(tmp_path):
    text = "Příliš žluťoučký kůň úpěl ďábelské ódy. Šťastný řidič jel přes most.\n" * 4
    path = tmp_path / "cz.txt"
    path.write_bytes(text.encode("iso8859-2"))
    assert ingest.decode_text(path.read_bytes()) == text
    old = ingest.decode_text(path.read_bytes(), reader=6)
    assert old != text and _build(path, 6).text.count("žluťoučký") == 0
    assert _build(path, 7).text.count("žluťoučký") == 4
    # a byte that Latin-2 does not use for text (0x80 to 0x9F) rules it out
    assert ingest.decode_text(text.encode("iso8859-2") + b"\x96") == ingest.decode_text(
        text.encode("iso8859-2") + b"\x96", reader=6)


def test_a_latin_2_web_page_without_a_declared_encoding_keeps_its_letters(tmp_path):
    pl = "Wartość ścieków w źródłach wody pitnej rośnie. Ślady zanieczyszczeń były wyraźne. " * 3
    path = tmp_path / "raport.html"
    path.write_bytes(f"<html><head><title>Raport źródła</title></head><body><p>{pl}</p></body></html>"
                     .encode("iso8859-2"))
    raw = ingest.read_file(path)
    assert raw.meta_title == "Raport źródła" and "Wartość ścieków" in raw.pages[0]
    assert "Wartość ścieków" not in raw.as_read_by(6).pages[0] and raw.as_read_by(6).meta_title != "Raport źródła"


def test_reader_7_is_offered_to_text_word_and_web_documents_of_reader_6_not_to_its_pdfs():
    for kind in ("text", "docx", "html"):
        assert languages.new_reader_changes(6, None, kind)
    assert not languages.new_reader_changes(6, None, "pdf") and not languages.new_reader_changes(7, None, "text")
    for r in (1, 2, 3, 4, 5):
        for kind in ("pdf", "text", "docx", "html"):
            assert languages.new_reader_changes(r, None, kind), (r, kind)
    # reader 6's own rule, while it was the newest, is unchanged
    assert not languages.new_reader_changes(5, None, "text", latest=6)


@pytest.mark.skipif(not NODE, reason="node is not installed")
def test_the_page_offers_reader_7_as_the_server_does(tmp_path):
    views = Path(__file__).resolve().parents[1] / "src" / "enlens_claims" / "gui" / "static" / "views"
    src = (views / "doc-shared.js").read_text(encoding="utf-8")
    m = re.search(r"^export function newReaderFor\(d, latest\) \{.*?^\}", src, re.S | re.M)
    docs = [{"reader": r, "kind": k} for r in (5, 6, 7) for k in ("pdf", "html", "text", "docx")]
    probe = tmp_path / "probe.mjs"
    probe.write_text(m.group(0) + f"\nconsole.log(JSON.stringify({json.dumps(docs)}.map((d) => newReaderFor(d, 7))));\n",
                     encoding="utf-8")
    r = subprocess.run([NODE, str(probe)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    offered = {(d["reader"], d["kind"]) for d, yes in zip(docs, json.loads(r.stdout)) if yes}
    assert offered == {(5, k) for k in ("pdf", "html", "text", "docx")} | {(6, "html"), (6, "text"), (6, "docx")}
    assert offered == {(d["reader"], d["kind"]) for d in docs
                       if languages.new_reader_changes(d["reader"], None, d["kind"], 7)}
    assert re.search(r"^export const reader = \{ latest: 7 \};", src, re.M) and "export const READER_7_NEWS = " in src
    page = (views / "doc-reading.js").read_text(encoding="utf-8") + (views / "sources.js").read_text(encoding="utf-8")
    assert "`Read by the reader of ENLENS 0.19.0rc2 to 0.20.3. ${READER_7_NEWS}`" in page and ": READER_7_NEWS)" in page


# ---- READERS-1 and READERS-6: zips and files of other kinds ---------------------------------------------------------
def test_the_same_zip_added_again_unpacks_into_its_own_folder(tmp_path):
    ws = Workspace.create(tmp_path / "ws")
    z = tmp_path / "sources.zip"
    pdf = tmp_path / "report.pdf"
    make_pdf(pdf, ["The first report says the reservoir held water through the whole dry season of the year. " * 3])
    with zipfile.ZipFile(z, "w") as zf:
        zf.write(pdf, "report.pdf")
    ingest.ingest(ws, [z], ocr=OFF)
    ingest.ingest(ws, [z], ocr=OFF)
    assert len([p for p in (ws.root / "inputs").iterdir() if p.is_dir()]) == 1
    doc = ws.query("SELECT doc_id FROM documents")[0][0]
    assert sources.original_file(ws, doc)["available"]


def test_two_names_that_differ_only_by_case_or_accent_form_are_unpacked_apart(tmp_path):
    """On a disk that does not tell them apart (macOS, Windows), "Report.pdf" and "report.pdf", or "másolat.pdf"
    written with "á" and with "a" and its accent apart, were written to one file: one document was lost. The names
    planned are apart on every computer."""
    names = ["Report.pdf", "report.pdf", "docs/másolat.pdf", "docs/másolat.pdf", "docs/MÁSOLAT.pdf",
             "notes", "Notes"]
    planned = ingest.unpack_names(names)
    assert planned[0] == "Report.pdf" and planned[2] == "docs/másolat.pdf"
    import unicodedata

    assert len({unicodedata.normalize("NFC", n).casefold() for n in planned}) == len(names)
    assert planned[1] == "report (2).pdf" and planned[6] == "Notes (2)"
    # in an add: both documents are there
    ws = Workspace.create(tmp_path / "ws")
    z = tmp_path / "two.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("Report.txt", "The upper-case report on the valley's wells and their water, long enough. " * 3)
        zf.writestr("report.txt", "The lower-case report on the river's fish and their numbers, long enough. " * 3)
    stats = ingest.ingest(ws, [z], ocr=OFF)
    assert stats["added"] == 2 and ws.query("SELECT COUNT(*) FROM documents")[0][0] == 2


def test_documents_of_a_kind_enlens_does_not_read_are_named(tmp_path):
    folder = tmp_path / "corpus"
    folder.mkdir()
    (folder / "old.doc").write_bytes(b"\xd0\xcf\x11\xe0 an old Word file")
    (folder / "slides.pptx").write_bytes(b"PK not really")
    (folder / "photo.png").write_bytes(b"\x89PNG")
    (folder / "~$lock.doc").write_bytes(b"lock")
    (folder / "note.txt").write_text("A note on the valley's wells, long enough to be stored as a document. " * 3,
                                     encoding="utf-8")
    ws = Workspace.create(tmp_path / "ws")
    stats = ingest.ingest(ws, [folder], ocr=OFF)
    failed = stats.get("failed", [])
    assert stats["added"] == 1
    assert any(f.startswith("old.doc:") and ".docx" in f for f in failed)
    assert any(f.startswith("slides.pptx:") and "PDF" in f for f in failed)
    assert not any("photo.png" in f or "~$lock" in f for f in failed)


# ---- READERS-7 ------------------------------------------------------------------------------------------------------
def test_every_directional_mark_is_left_out_of_quote_matching_but_not_of_0_4s():
    for mark in ("‎", "‏", "‪", "‫", "‬", "‭", "‮", "⁦", "⁧",
                 "⁨", "⁩"):
        hay = f"costs rose by {mark}15 percent{mark} in the north"
        hit = textutil.find_quote(hay, "rose by 15 percent in")
        assert hit is not None and hay[hit[0]:hit[1]].startswith("rose by"), repr(mark)
        assert mark in textutil.normalise_v1(hay)   # 0.4's normalisation stays exactly as it was
    assert textutil.fast_normalise("a‏b") == "ab"
    assert textutil.normalise("a‍b") == "a‍b"   # joiners change how a word is written: kept


def test_the_original_text_file_marks_a_quote_of_either_reading(tmp_path):
    """Sibling of READERS-5: the original of a text file is shown with its quote marked, decoded as the document was
    read; a document reader 6 read from a Latin-2 file keeps its quotes in that reading, a new one in reader 7's."""
    from enlens_claims.gui.api_common import _text_with_quote

    text = "Wartość ścieków w źródłach wody pitnej rośnie. Ślady zanieczyszczeń były wyraźne.\n" * 3
    path = tmp_path / "raport.txt"
    path.write_bytes(text.encode("iso8859-2"))
    old = ingest.decode_text(path.read_bytes(), reader=6)
    assert _text_with_quote(path, "Wartość ścieków w źródłach", "raport.txt") is not None
    assert _text_with_quote(path, old[:24], "raport.txt") is not None


def test_word_and_text_files_of_reader_6_move_to_reader_7(tmp_path, monkeypatch):
    """The offer leads somewhere: a Word file with a text box and a plain one, and a Latin-2 text file, read by reader
    6, move to reader 7; the box is then read once and the letters are kept, the plain file reads the same."""
    from enlens_claims import reread

    rng = random.Random(3)
    boxed = _word(tmp_path / "boxed.docx", "".join(_p(_sentence(rng)) for _ in range(4))
                  + _text_box("Forty wells ran dry in the boxed summary.") + "".join(_p(_sentence(rng)) for _ in range(4)))
    plain = _word(tmp_path / "plain.docx", "".join(_p(_sentence(rng)) for _ in range(8)))
    latin2 = tmp_path / "raport.txt"
    latin2.write_bytes(("Wartość ścieków w źródłach wody pitnej rośnie. Ślady zanieczyszczeń były wyraźne. " * 4)
                       .encode("iso8859-2"))
    ws = Workspace.create(tmp_path / "ws")
    try:
        with monkeypatch.context() as mp:
            mp.setattr(ingest, "READER", 6)
            ingest.ingest(ws, [boxed, plain, latin2], ocr=OFF, ai_access="cloud")
        docs = {Path(r[1]).name: r[0] for r in ws.query("SELECT doc_id, path FROM documents")}
        assert set(ws.query("SELECT DISTINCT reader FROM documents")[0]) == {6}
        before = ws.scalar("SELECT text FROM documents WHERE doc_id=?", (docs["plain.docx"],))
        assert ws.scalar("SELECT text FROM documents WHERE doc_id=?", (docs["boxed.docx"],)).count("Forty wells") == 2
        for name, doc in docs.items():
            assert reread.check(ws, doc)["ok"], name
            reread.move(ws, doc)
        text = {n: ws.scalar("SELECT text FROM documents WHERE doc_id=?", (d,)) for n, d in docs.items()}
        assert dict(ws.query("SELECT doc_id, reader FROM documents")) == {d: 7 for d in docs.values()}
        assert text["boxed.docx"].count("Forty wells") == 1 and text["plain.docx"] == before
        assert "Wartość ścieków" in text["raport.txt"]
    finally:
        ws.close_all()
