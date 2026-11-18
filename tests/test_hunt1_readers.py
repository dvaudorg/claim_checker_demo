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
