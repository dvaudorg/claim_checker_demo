"""Reader 8 (`reader8.py`): two columns whose lines stand at other heights are read column by column.

A thesis printed as spreads has two facing book pages on one PDF page; where one page's lines sit half a line lower
than the other's, readers 2 to 7 found no gap between them and read the page straight across, one line of each in turn
(reported on a thesis's page 30, November 2026). Readers before 8 still read so; reader 8 reads one column, then the
other. Two columns that share their baselines, and a page in one column, read as before.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from _fakedom import NODE

from enlens_claims import ingest, languages, measure, pdfmake, reader

VIEWS = Path(__file__).resolve().parents[1] / "src" / "enlens_claims" / "gui" / "static" / "views"

LEFT = ("Stimulating physical and social activities seems typically a task of professionals as well as informal "
        "caregivers. However, due to time restraints, caregivers are often unable to provide this service well. "
        "As carers also pointed out again and again in this study, even the interns feel the pressure of the day. "
        "Self-help is a beautiful concept, but self-help requires time that the nursing home does not have.")
RIGHT = ("In the current study, we focus on the social environment, to reveal its enabling and inhibiting factors "
         "concerning the level of physical activity of the residents. By focussing on the social interactions, we "
         "do not consider the external factors of time or the influence of relatives. This study aims to answer "
         "one research question about the residents who are living with dementia in the nursing home.")


def _column(page: pdfmake.Page, text: str, x: float, top: float, step: float = 16.0) -> None:
    y = top
    for ln in pdfmake.wrap(text, 290, "Times-Roman", 10):
        page.text(ln, x, y, "Times-Roman", 10)
        y -= step


def _pdf(path: Path, offset: float, width: float = 964.0) -> Path:
    """One PDF page with two columns (a book's two facing pages); the right one's lines `offset` points lower."""
    pg = pdfmake.Page(width=width, height=680.0)
    _column(pg, LEFT, 130, 600)
    _column(pg, RIGHT, 546, 600 - offset)
    pdfmake.write([pg], path, "Spread")
    return path


def _words(s: str) -> str:
    return " ".join(s.split())


@pytest.fixture(scope="module")
def spread(tmp_path_factory) -> Path:
    return _pdf(tmp_path_factory.mktemp("reader8") / "spread.pdf", offset=8.0)


def test_reader_8_is_current():
    assert reader.READER == ingest.READER == 8


def test_two_facing_pages_with_lines_at_other_heights_are_read_column_by_column(spread):
    old = _words(ingest.read_document(spread, reader=7).text)
    new = _words(ingest.read_document(spread, reader=8).text)
    # reader 7: the two columns, line by line in turn (neither column's text whole)
    assert _words(LEFT) not in old and _words(RIGHT) not in old
    # reader 8: the left column, then the right one
    assert _words(LEFT) in new and _words(RIGHT) in new
    assert new.index(_words(LEFT)) < new.index(_words(RIGHT))


def test_the_paragraphs_of_each_column_stay_apart(spread):
    doc = ingest.read_document(spread, reader=8)
    body = [_words(doc.text[b.start:b.end]) for b in doc.blocks if b.kind == "body"]
    assert any(_words(LEFT) in t for t in body)
    assert not any("caregivers" in t and "relatives" in t for t in body)   # no block holds both columns


@pytest.mark.parametrize("offset", [0.0, 1.5])
def test_columns_that_share_their_baselines_read_as_by_reader_7(tmp_path, offset):
    path = _pdf(tmp_path / f"aligned-{offset}.pdf", offset=offset)
    old, new = ingest.read_document(path, reader=7), ingest.read_document(path, reader=8)
    assert measure.fingerprint(old) == measure.fingerprint(new)
    assert _words(LEFT) in _words(new.text)


def test_a_page_in_one_column_reads_as_by_reader_7(tmp_path):
    pg = pdfmake.Page()
    y = 780.0
    for ln in pdfmake.wrap(LEFT + " " + RIGHT, 470, "Times-Roman", 10):
        pg.text(ln, 60, y, "Times-Roman", 10)
        y -= 13
    path = tmp_path / "one.pdf"
    pdfmake.write([pg], path, "One column")
    old, new = ingest.read_document(path, reader=7), ingest.read_document(path, reader=8)
    assert measure.fingerprint(old) == measure.fingerprint(new)


def test_reader_8_is_offered_to_pdfs_reader_7_read_and_to_everything_reader_6_read():
    assert languages.new_reader_changes(7, None, "pdf", latest=8)
    for kind in ("docx", "text", "html"):
        assert not languages.new_reader_changes(7, None, kind, latest=8)
    for kind in ("pdf", "docx", "text", "html"):
        assert languages.new_reader_changes(6, None, kind, latest=8)
    assert not languages.new_reader_changes(8, None, "pdf", latest=8)
    # with reader 7 newest, as before
    assert not languages.new_reader_changes(6, None, "pdf", latest=7)
    assert languages.new_reader_changes(6, None, "docx", latest=7)


@pytest.mark.skipif(not NODE, reason="node is not installed")
def test_the_page_offers_reader_8_as_the_server_does_and_says_its_news(tmp_path):
    src = (VIEWS / "doc-shared.js").read_text(encoding="utf-8")
    assert re.search(r"^export const reader = \{ latest: 8 \};", src, re.M)
    m = re.search(r"^export function newReaderFor\(d, latest\) \{.*?^\}", src, re.S | re.M)
    docs = [{"reader": r, "kind": k} for r in (5, 6, 7, 8) for k in ("pdf", "html", "text", "docx")]
    probe = tmp_path / "probe.mjs"
    probe.write_text(m.group(0) + f"\nconsole.log(JSON.stringify({json.dumps(docs)}.map((d) => newReaderFor(d, 8))));\n",
                     encoding="utf-8")
    r = subprocess.run([NODE, str(probe)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    offered = {(d["reader"], d["kind"]) for d, yes in zip(docs, json.loads(r.stdout)) if yes}
    assert offered == {(r, k) for r in (5, 6) for k in ("pdf", "html", "text", "docx")} | {(7, "pdf")}
    assert offered == {(d["reader"], d["kind"]) for d in docs
                       if languages.new_reader_changes(d["reader"], None, d["kind"], 8)}
    # the news of a move: reader 8's alone for a PDF of reader 7 or 6 (reader 7 changed no PDF), reader 7's alone for
    # a reader-6 Word file (reader 8 changes PDFs only), and both, without their last words, for the two together
    from _views import run_views

    probe = """await scenario("news", async (t) => {
  const m = await t.module("views/doc-shared.js");
  return [m.readerNews([{ reader: 7, kind: "pdf" }], 8) === m.READER_8_NEWS,
          m.readerNews([{ reader: 6, kind: "pdf" }], 8) === m.READER_8_NEWS,
          m.readerNews([{ reader: 6, kind: "docx" }], 8) === m.READER_7_NEWS,
          m.readerNews([{ reader: 6, kind: "docx" }, { reader: 7, kind: "pdf" }], 8)];
});"""
    *same, both = run_views(probe, tmp_path)["news"]
    assert same == [True, True, True]
    assert "Word file's text box" in both and "one column, then the other" in both and "read the same" not in both
    assert "one column, then the other" in both and "Other documents read the same" not in both
