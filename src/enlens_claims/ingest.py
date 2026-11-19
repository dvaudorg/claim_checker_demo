"""Read PDFs, HTML and text into documents and passages with page and character offsets.

All offsets point into the stored document text: one cleaned string per document, pages joined by a
blank line. Quotes, evidence and highlights are resolved against that string.
"""
from __future__ import annotations

import atexit
import bisect
import codecs
import hashlib
import json
import os
import re
import shutil
import sqlite3
import threading
import unicodedata
import weakref
import zipfile
import zlib
from collections import Counter
from concurrent.futures import Future
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

from . import __version__
from .procs import no_window
from .store import Workspace, now
from .textutil import find_dois, split_sentences

SUPPORTED = {".pdf", ".html", ".htm", ".txt", ".md", ".docx"}
# Hunt phase 1: documents of a kind ENLENS does not read, named under `failed` when added (with what to do) rather than
# passed over without a word; any other file (a picture, a spreadsheet) is not a document and is still passed over
_SAVE_AS = "a kind of file ENLENS does not read: save it as PDF or Word (.docx) and add that"
NOT_READ_KINDS = {".doc": "an older Word file, which ENLENS does not read: save it as .docx or PDF and add that",
                  ".rtf": _SAVE_AS, ".odt": _SAVE_AS, ".pages": _SAVE_AS, ".wpd": _SAVE_AS, ".epub": _SAVE_AS,
                  ".ppt": "slides, which ENLENS does not read: save them as PDF and add that",
                  ".pptx": "slides, which ENLENS does not read: save them as PDF and add that",
                  ".odp": "slides, which ENLENS does not read: save them as PDF and add that"}

# 0.15 (roadmap): the reader, which turns a file into the stored text and passages (read_file, assemble, layout,
# make_passages). Each document records the one that read it (documents.reader). A change that gives a document other
# text or passages raises this number: documents already in a project keep the reading they have, so every result in
# them stays where it is, until a person has one read with the new reader (planned with the next reader); only new
# documents get the new reader.
READER = 7  # 1: ENLENS 0.5 to 0.14 (pypdf's page text, cut by sentences); 2: ENLENS 0.15.0 (reader.py);
            # 3: ENLENS 0.15.1 (reader.py with reader3.py: text-only files, books, words run together);
            # 4: ENLENS 0.17.2 (reader4.py: a text file's lines as paragraphs; Word's nested tables read once, and
            #    its content controls read)
            # 5: ENLENS 0.18.1 (reader5.py: tables from their ruled lines, a table over a page joined, figures and
            #    images as blocks of their own; a Word file's or web page's image captions and alternative text)
            # 6: ENLENS 0.19 (reader6.py, PDFs only: text a form crops away left out, a form of words one figure,
            #    publishing details in the first page's footer set aside, a journal's name not the title; and, any
            #    kind of file, languages.py: in a document in two languages, a side-by-side translation, no passage
            #    holds both)
            # 7: reader7.py (text files, Word files and web pages only: a line that comes back in text
            #    whose every line is a paragraph is not a running head, short sentences one per line are paragraphs,
            #    a Word text box read once as paragraphs of its own, ISO-8859-2 files and UTF-16 ones without a
            #    byte-order mark read as written)
REF_HEADING = re.compile(
    r"(?:^|\s)(References|REFERENCES|Bibliography|BIBLIOGRAPHY|Literature [Cc]ited|Works [Cc]ited|Reference [Ll]ist)"
    r"\s*:?\s+(?=\[?\(?\d|[A-Z][A-Za-z'\-]+,?\s+[A-Z]|[A-Z]{2,})"
)


@dataclass
class RawDoc:
    path: Path
    kind: str
    pages: list[str]
    meta_title: str | None = None
    sha1: str = ""
    paginated: bool = True  # False for text without page breaks: passages then carry no page number
    headings: set[str] | None = None  # the heading lines a web page or markdown file marks as such
    ocr_pages: int = 0       # PDF pages without a text layer whose text was recognised (OCR)
    scanned_pages: int = 0   # PDF pages without a text layer (recognised or not)
    line_pos: list | None = None  # PDFs: per page, the (x, y) where each line of its text starts (None: unknown)
    # Word files whose text reader 4 reads otherwise (`_read_docx`): the pages, headings and pagination readers 1 to 3
    # read, so that an older reader number still reads the file byte for byte as it did (`as_read_by`)
    before_4: dict | None = None
    # reader 5 (0.18.1) reads an image's alternative text in Word files and web pages: `figures` are those texts (as
    # `" ".join(text.split())`), which sit in `pages` as paragraphs of their own; `before_5` is the pages, headings and
    # pagination readers 2 to 4 read, when they differ (`as_read_by`)
    before_5: dict | None = None
    figures: set[str] | None = None
    # reader 7 (hunt phase 1) reads a Word file's text boxes once and takes a text or web page saved as ISO-8859-2
    # (`_read_docx`, `decode_text`): `before_7` is what readers 1 to 6 read (its pages, headings, title, pagination,
    # figures and their own `before_5`), when that differs (`as_read_by`)
    before_7: dict | None = None

    def as_read_by(self, reader: int) -> "RawDoc":
        """The file as the given reader reads it: itself, or for readers before 7 the Word text and the decoding of a
        text file or web page they read, for readers before 5 the Word text and web page they read (and for readers
        1 to 3 the Word text of reader 3, as before)."""
        raw = self
        import dataclasses

        if reader < 7 and raw.before_7:
            raw = dataclasses.replace(raw, **raw.before_7, before_7=None)
        if reader < 5 and raw.before_5:
            raw = dataclasses.replace(raw, **raw.before_5, before_5=None)
        if reader < 4 and raw.before_4:
            raw = dataclasses.replace(raw, **raw.before_4, before_4=None)
        return raw
    page_sizes: list | None = None  # PDFs (0.15): per page, (width, height) in points
    # hunt phase 1.5: a text file or web page that names no encoding and is not UTF-8: the one guessed for it
    # ("Windows-1250", …; `_decode`), said in the reading report so a person can see a wrong guess (None: not a guess)
    encoding: str | None = None


@dataclass
class Passage:
    seq: int
    start: int
    end: int
    page: int | None
    section: str


@dataclass
class Document:
    doc_id: str
    raw: RawDoc
    text: str
    page_spans: list[tuple[int, int]]
    title: str
    doi: str | None
    passages: list[Passage] = field(default_factory=list)
    paragraphs: list[int] = field(default_factory=list)  # where each paragraph starts (documents without pages)
    layout: "Layout | None" = None                       # paragraphs (with their page) and headings, all documents


# ------------------------------------------------------------------------------------------
# reading
# ------------------------------------------------------------------------------------------
class _TextOnly(HTMLParser):
    BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "article", "table", "td"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0
        self.title: str | None = None
        self._in_title = False
        self.headings: set[str] = set()
        self._heading: list[str] | None = None
        # reader 5: the same text with each image's alternative text as a paragraph of its own
        self.parts5: list[str] = []
        self.alts: set[str] = set()

    def _emit(self, s: str) -> None:
        self.parts.append(s)
        self.parts5.append(s)

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "nav", "footer", "noscript"):
            self.skip += 1
        if tag == "title":
            self._in_title = True
        if tag in self.BLOCK:
            self._emit("\n")
        if tag == "img" and not self.skip:
            alt = " ".join((dict(attrs).get("alt") or "").split())
            if alt:
                self.parts5.append("\n\n" + alt + "\n\n")  # a paragraph of its own
                self.alts.add(alt)
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._heading = []

    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav", "footer", "noscript") and self.skip:
            self.skip -= 1
        if tag == "title":
            self._in_title = False
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6") and self._heading is not None:
            t = " ".join("".join(self._heading).split())
            if t:
                self.headings.add(t)
            self._heading = None
        if tag in self.BLOCK:
            self._emit("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title = (self.title or "") + data
        elif not self.skip:
            self._emit(data)
            if self._heading is not None:
                self._heading.append(data)


def _sha1(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:  # streamed: a large PDF is never held in memory for its checksum
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class Stopped(Exception):
    """The person pressed Stop while a file was being read (OCR of a long scanned PDF checks before each page)."""


def read_file(path: Path, ocr: "OcrOptions | None" = None, should_stop=None) -> RawDoc:
    ext = path.suffix.lower()
    if ext == ".pdf":
        sha1 = _sha1(path)
        sizes: list = []
        pages, title, done, scanned, pos = _read_pdf(path, ocr, should_stop, sizes)
        return RawDoc(path, "pdf", pages, title, sha1, ocr_pages=done, scanned_pages=scanned, line_pos=pos,
                      page_sizes=sizes or None)
    if ext == ".docx":
        sha1 = _sha1(path)
        pages, title, heads, before, before5, figs, before7 = _read_docx(path)
        return RawDoc(path, "docx", pages, title, sha1, paginated=len(pages) > 1, headings=heads, before_4=before,
                      before_5=before5, figures=figs or None, before_7=before7)
    data = path.read_bytes()
    sha1 = hashlib.sha1(data).hexdigest()
    html = ext in (".html", ".htm")
    decoded, guess = _decode(data, html=html)
    raw = _text_raw(path, ext, decoded, sha1)
    raw.encoding = guess
    # reader 7 takes a file saved as ISO-8859-2 (Latin-2); readers 1 to 6 read it as Windows-1250 or -1252
    before, guess6 = _decode(data, html=html, reader=6)
    if before != decoded:
        old = _text_raw(path, ext, before, sha1)
        raw.before_7 = {"pages": old.pages, "meta_title": old.meta_title, "paginated": old.paginated,
                        "headings": old.headings, "before_5": old.before_5, "figures": old.figures,
                        "encoding": guess6}
    return raw


def _text_raw(path: Path, ext: str, text: str, sha1: str) -> RawDoc:
    """A web page, text or Markdown file read from its decoded text."""
    if ext in (".html", ".htm"):
        p = _TextOnly()
        p.feed(text)
        text5, text = "".join(p.parts5), "".join(p.parts)
        return RawDoc(path, "html", [text5], (p.title or "").strip() or None, sha1, paginated=False,
                      headings=p.headings, before_5={"pages": [text]} if text5 != text else None,
                      figures=p.alts or None)
    heads = None
    if ext == ".md":
        heads = markdown_headings(text)
        text = strip_markdown(text)
    pages = text.split("\f") if "\f" in text else [text]
    return RawDoc(path, "text", pages, None, sha1, paginated="\f" in text, headings=heads)


# ------------------------------------------------------------------------------------------
# 0.14.3: the encoding of a text or web page file. Before, everything was read as UTF-8 and other bytes became "�":
# a Hungarian text saved by Notepad (Windows-1250) or an old Latin-1 page lost its accented letters, its passages
# were marked unreadable and its accented words could not be searched.
# ------------------------------------------------------------------------------------------
_BOMS = ((b"\xef\xbb\xbf", "utf-8"), (b"\xff\xfe\x00\x00", "utf-32-le"), (b"\x00\x00\xfe\xff", "utf-32-be"),
         (b"\xff\xfe", "utf-16-le"), (b"\xfe\xff", "utf-16-be"))
_DECLARED = (re.compile(rb"<meta[^>]*?charset\s*=\s*[\"']?\s*([A-Za-z0-9_.:\-]+)", re.I),
             re.compile(rb"<\?xml[^>]*?encoding\s*=\s*[\"']([A-Za-z0-9_.:\-]+)", re.I))
# the accented letters of the languages written in Windows-1250 (Central Europe) and Windows-1252 (Western Europe):
# of the two readings of a file, the one whose accented letters belong together in one language is taken
_ALPHABETS = ("áéíóöőúüű", "áčďéěíňóřšťúůýž", "áäčďéíĺľňóôŕšťúýž", "ąćęłńóśźż", "čćđšž", "ăâîșşțţ", "äöüß",
              "àâæçéèêëîïôœùûüÿ", "áéíñóúü", "àáâãçéêíóôõú", "àèéìíîòóùú", "áéèëïóöü", "åäöæøéðþáíóúý",
              "àçèéíïòóúü")


def _fits(text: str) -> float:
    """The largest share of the accented letters of `text` that one language's alphabet holds (1.0: no accents)."""
    letters = Counter(c.lower() for c in text if ord(c) > 127 and c.isalpha())
    total = sum(letters.values())
    if not total:
        return 1.0
    return max(sum(n for c, n in letters.items() if c in a) for a in _ALPHABETS) / total


def _letters(text: str) -> float:
    """The share of the characters beyond ASCII that are letters (ą, ł, ż read as Windows-1252 are ¹, ³, ¿)."""
    high = [c for c in text if ord(c) > 127]
    return sum(c.isalpha() for c in high) / len(high) if high else 1.0


def _single_byte(data: bytes, reader: int | None = None) -> str:
    """Text that is not UTF-8 and names no encoding: Windows-1250 or Windows-1252, whichever reads as one language
    (on a tie, the one whose characters beyond ASCII are letters). Reader 7: or ISO-8859-2 (see `_latin2`)."""
    read = []
    for enc in ("cp1252", "cp1250"):
        try:
            read.append(data.decode(enc))
        except UnicodeDecodeError:
            pass
    if not read:
        return data.decode("cp1252", errors="replace")
    if len(read) == 1 or read[0] == read[1]:
        best = read[0]
    else:
        best = read[1] if (_fits(read[1]), _letters(read[1])) > (_fits(read[0]), _letters(read[0])) else read[0]
    if (reader or READER) >= 7:
        return _latin2(data, best)
    return best


# Hunt phase 1 (READERS-5), reader 7: a Polish, Czech or Slovak text saved as ISO-8859-2 (Latin-2, by older Unix and
# Linux tools and corpora) was read as Windows-1250, which puts other letters at 0xA1 to 0xBF: "Wartość ścieków"
# came out "Warto¶ć ¶cieków", with no warning, and those words could not be searched or quoted. Latin-2 is taken only
# when it reads clearly better. A byte in 0x80 to 0x9F rules it out (control characters there; Windows-1250 puts
# š, ś, ž, ź and quotation marks there). Then Latin-2 is taken when its letters fit one language strictly better
# than the Windows reading's, "µ", "ª" and "º" not counted as letters there (after review: "µ" is a letter of no
# alphabet, so a Western text whose one sign beyond ASCII was "µ" read as Slovak, "5 ľg", and a French one with it
# "trčs bon ŕ Genčve"); or when, where the two readings differ, the Windows reading shows signs rather than letters
# at most places, two of them inside words ("Warto¶æ", "by³a": a short Polish text whose other letters fit Danish as
# well). On a tie the Windows reading stays: an English text with "©" or "µ", a French, German or Spanish one,
# Hungarian (the same in both).
_C1 = re.compile(rb"[\x80-\x9f]")
_NOT_LETTERS = "µªº"   # letters to Python, signs in a Western text: of no alphabet
_NO_SIGNS = str.maketrans("", "", _NOT_LETTERS)


def _latin2(data: bytes, best: str) -> str:
    """`best` (the Windows-1250 or -1252 reading), or the ISO-8859-2 reading when, where the two differ, it fits one
    language strictly better or the Windows reading shows signs inside words, and no byte rules it out."""
    if _C1.search(data):
        return best
    l2 = data.decode("iso8859-2")
    if l2 == best or len(l2) != len(best):
        return best
    if _fits(l2) > _fits(best.translate(_NO_SIGNS)):
        return l2
    diff = [i for i, (a, b) in enumerate(zip(best, l2)) if a != b]

    def letter(i: int) -> bool:
        return 0 <= i < len(best) and best[i].isalpha()

    # (a letter of a word, not a mark Latin-2 puts there, such as "ˇ", which Python counts as a letter: Catalan
    # "col·lecció" in Windows-1252 has "·" between letters, which Latin-2 reads "ˇ")
    lettered = [i for i in diff if unicodedata.category(l2[i]) in ("Lu", "Ll")]
    signs = [i for i in lettered if not best[i].isalpha() or best[i] in _NOT_LETTERS]
    inside = [i for i in signs if not best[i].isalpha() and letter(i - 1) and letter(i + 1)]
    return l2 if len(inside) >= 2 and len(signs) > 0.5 * len(lettered) else best


def _utf16_without_bom(data: bytes) -> str | None:
    """Hunt phase 1.5, reader 7: UTF-16 text saved without a byte-order mark (rare: Windows writes one). Text in a
    Latin alphabet then has a zero byte beside nearly every letter, all on one side, which no UTF-8 or single-byte text
    has; it was read as UTF-8 (plain-ASCII UTF-16 is valid UTF-8) with a NUL between letters, and could not be searched
    or quoted. None when it is not that."""
    n = len(data) // 2
    if n < 8 or len(data) % 2:
        return None
    even, odd = data[0::2].count(0), data[1::2].count(0)
    enc = "utf-16-le" if odd >= 0.4 * n and even <= 0.01 * n else "utf-16-be" if even >= 0.4 * n and odd <= 0.01 * n \
        else None
    if enc is None:
        return None
    try:
        return data.decode(enc)
    except UnicodeDecodeError:
        return None


def _mostly_utf8(data: bytes) -> str | None:
    """UTF-8 with a few damaged bytes (a cut-off letter, a stray byte in scraped text): read as UTF-8, the damaged
    bytes as "�", rather than the whole file as another encoding. None when it does not look like UTF-8: in text
    saved as Windows-1250 or -1252 nearly every accented letter is an invalid UTF-8 byte."""
    text = data.decode("utf-8", errors="replace")
    bad = text.count("�")
    good = sum(1 for c in text if ord(c) > 127 and c != "�")
    return text if good and bad <= max(1, good // 10) else None


def decode_text(data: bytes, html: bool = False, reader: int | None = None) -> str:
    """The text of a .txt, .md or web page file: by its byte-order mark (UTF-8, UTF-16, UTF-32); UTF-8 (also with a few
    damaged bytes); for a web page, the encoding it declares (`<meta charset>`, `<?xml encoding>`); else Windows-1250
    or -1252, and from reader 7 (`reader`, default the current one) ISO-8859-2 (see _single_byte)."""
    return _decode(data, html, reader)[0]


# the single-byte encodings `_single_byte` chooses between, by the names a person knows them by
_GUESSES = (("cp1252", "Windows-1252"), ("cp1250", "Windows-1250"), ("iso8859-2", "ISO-8859-2"))


def _decode(data: bytes, html: bool = False, reader: int | None = None) -> tuple[str, str | None]:
    """`decode_text`, and the encoding guessed when the file names none and is not UTF-8 (None when nothing was
    guessed). Hunt phase 1.5: the guess is said in the reading report, so a person can see a wrong one."""
    for bom, enc in _BOMS:
        if data.startswith(bom):
            return data[len(bom):].decode(enc, errors="replace"), None
    if (reader or READER) >= 7:
        text = _utf16_without_bom(data)
        if text is not None:
            return text, "UTF-16"
    try:
        return data.decode("utf-8"), None
    except UnicodeDecodeError:
        pass
    text = _mostly_utf8(data)
    if text is not None:
        return text, None
    if html:
        head = data[:4096]
        for rx in _DECLARED:
            m = rx.search(head)
            if not m:
                continue
            try:
                enc = codecs.lookup(m.group(1).decode("ascii", "ignore")).name
            except LookupError:
                break
            if enc.startswith("utf"):
                break  # declared UTF-8, but it is not: read below
            # as browsers do, a page declared Latin-1 or ASCII is read as Windows-1252
            for e in (("cp1252", "latin-1") if enc in ("latin-1", "iso8859-1", "ascii") else (enc,)):
                try:
                    return data.decode(e), None
                except UnicodeDecodeError:
                    pass
            break
    text = _single_byte(data, reader)
    for codec, name in _GUESSES:
        if data.decode(codec, errors="replace") == text:
            return text, name
    return text, "Windows-1252"


_W ="{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"   # reader 5: an image's docPr
_MC_FALLBACK = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"   # reader 7: a box's copy
DOCX_MAX = 200 * 1024 ** 2   # bytes of XML read from one Word file (a zip): a bound against zip bombs
DOCX_CORE_MAX = 1024 ** 2    # bytes of a Word file's document properties (where its title is): the same, for them


def _read_docx(path: Path) -> tuple[list[str], str | None, set[str], dict | None, dict | None, set[str], dict | None]:
    """A Word file (.docx: a zip of XML) with the standard library: its paragraphs (separated by a blank line, as in a
    text file), its headings (paragraph styles Title and Heading 1 to 9), its pages where Word marked them (a page
    break, or where Word last laid out a new page), and its title (document properties). Tables are read row by row;
    footnotes and comments are left out. Readers 1 to 6 read a text box's words twice (Word keeps the box and an
    older copy of it) and joined them to the paragraph that holds it; reader 7 reads it once, as paragraphs of its own
    after that paragraph: the seventh value is what readers 1 to 6 read (for `RawDoc.before_7`) when that differs.

    Reader 4 reads text inside content controls and custom XML around paragraphs and tables (readers 1 to 3 dropped
    it), and a table inside a table's cell once, its rows after the row that holds it (readers 1 to 3 read it three
    times). The fourth value is what readers 1 to 3 read ({"pages", "headings", "paginated"}, for `RawDoc.before_4`)
    when that differs from reader 4's, else None.

    Reader 5 also keeps an image's alternative text (the `descr` or `title` of its `wp:docPr`) as a paragraph of its own
    after the paragraph that holds the image: the fifth value is what readers 2 to 4 read (for `RawDoc.before_5`) when
    that differs, the sixth the alternative texts."""
    import xml.etree.ElementTree as ET

    class _NoDoctype(ET.TreeBuilder):   # (a Word file has no DOCTYPE; entities declared in one could swell a few
        def doctype(self, *_a):         # hundred bytes into megabytes: the same guard as sync/_xml.py)
            raise ET.ParseError("a DOCTYPE, which no Word file has")

    def parse(data: bytes):
        parser = ET.XMLParser(target=_NoDoctype())
        try:
            parser.feed(data)
            return parser.close()
        except ET.ParseError:
            raise
        except Exception as e:  # noqa: BLE001 - whatever the hook raised, through expat, is a refusal
            raise ET.ParseError(str(e)) from None

    try:
        zf = zipfile.ZipFile(path)
    except zipfile.BadZipFile as e:  # 0.11.1: listed under failed like any other unreadable file, not a crash
        raise ValueError("not a Word file (not a .docx package)") from e
    with zf:
        try:
            info = zf.getinfo("word/document.xml")
        except KeyError as e:
            raise ValueError("not a Word file (no document inside)") from e
        if info.file_size > DOCX_MAX:
            raise ValueError("The Word file's text is too large to read.")
        try:
            root = parse(zf.read(info))
        except ET.ParseError as e:
            raise ValueError(f"the Word file's text could not be read ({e})") from e
        title = None
        try:
            core_info = zf.getinfo("docProps/core.xml")
            if core_info.file_size > DOCX_CORE_MAX:  # a title is a few words: anything this large is not one
                raise KeyError("docProps/core.xml")
            core = parse(zf.read(core_info))
            t = core.find("{http://purl.org/dc/elements/1.1/}title")
            title = (t.text or "").strip() or None if t is not None else None
        except (KeyError, ET.ParseError, *ZIP_ERRORS):  # 0.14.3: damaged properties: the text is read all the same
            title = None
    body = root.find(f"{_W}body")
    pages3, heads3 = _docx_text(body, 3)
    pages4, heads4 = _docx_text(body, 4)
    figs5: set[str] = set()
    pages5, heads5 = _docx_text(body, 5, figs5)
    figs: set[str] = set()
    pages, heads = _docx_text(body, 7, figs)
    before = None
    if pages3 != pages4 or heads3 != heads4:
        before = {"pages": pages3, "headings": heads3, "paginated": len(pages3) > 1}
    before5 = None
    if pages4 != pages5 or heads4 != heads5:
        before5 = {"pages": pages4, "headings": heads4, "paginated": len(pages4) > 1}
    before7 = None
    if pages5 != pages or heads5 != heads or figs5 != figs:
        before7 = {"pages": pages5, "headings": heads5, "paginated": len(pages5) > 1, "figures": figs5 or None}
    return pages, title, heads, before, before5, figs, before7


# block-level elements that only wrap other block-level elements: a content control (its content) and custom XML
_DOCX_WRAPPERS = {f"{_W}sdt", f"{_W}customXml"}


def _docx_blocks(el):
    """The paragraphs and tables directly in a body, a table cell or a content control's content, with those inside
    content controls and custom XML taken out of them in their place (reader 4)."""
    for child in el:
        if child.tag in _DOCX_WRAPPERS:
            inner = child.find(f"{_W}sdtContent") if child.tag == f"{_W}sdt" else child
            if inner is not None:
                yield from _docx_blocks(inner)
        elif child.tag in (f"{_W}p", f"{_W}tbl"):
            yield child


def _docx_children(el, tag: str):
    """The rows of a table or the cells of a row, also those inside content controls and custom XML (reader 4)."""
    for child in el:
        if child.tag in _DOCX_WRAPPERS:
            inner = child.find(f"{_W}sdtContent") if child.tag == f"{_W}sdt" else child
            if inner is not None:
                yield from _docx_children(inner, tag)
        elif child.tag == tag:
            yield child


def _docx_text(body, version: int, figs: set[str] | None = None) -> tuple[list[str], set[str]]:
    """The pages and headings of a Word file's body, as reader `version` reads them (see `_read_docx`). From version 5
    the alternative text of the images (added to `figs`) is a paragraph of its own after the paragraph that holds
    them."""
    pages: list[list[str]] = [[]]
    heads: set[str] = set()

    def walk(el, boxes: list):
        """Reader 7: the paragraph's own elements, in order. Word keeps a text box twice, as the shape (mc:Choice)
        and as an older copy for programs that do not know shapes (mc:Fallback): the copy is skipped, and a box's
        content (w:txbxContent) is put in `boxes`, to be read as paragraphs of its own after this one."""
        yield el
        for c in el:
            if c.tag == _MC_FALLBACK:
                continue
            if c.tag == f"{_W}txbxContent":
                boxes.append(c)
                continue
            yield from walk(c, boxes)

    def para_text(p, boxes: list | None = None) -> tuple[str, bool]:
        """The paragraph's text, and whether a new page starts in it (before its text). With `boxes` (reader 7), the
        text boxes in it are not read into it but put there."""
        out, new_page = [], False
        for el in (p.iter() if boxes is None else walk(p, boxes)):
            tag = el.tag
            if tag == f"{_W}t":
                out.append(el.text or "")
            elif tag == f"{_W}tab":
                out.append("\t")
            elif tag in (f"{_W}br", f"{_W}cr"):
                if el.get(f"{_W}type") == "page":
                    if "".join(out).strip():
                        out.append("\f")
                    else:
                        new_page = True
                else:
                    out.append("\n")
            elif tag == f"{_W}lastRenderedPageBreak":
                if "".join(out).strip():
                    out.append("\f")
                else:
                    new_page = True
            elif tag in (f"{_W}noBreakHyphen",):
                out.append("-")
        return "".join(out), new_page

    def style(p) -> str:
        ps = p.find(f"{_W}pPr/{_W}pStyle")
        return (ps.get(f"{_W}val") or "") if ps is not None else ""

    def add(text: str, new_page: bool, heading: bool) -> None:
        if new_page and any(x.strip() for x in pages[-1]):
            pages.append([])
        for k, piece in enumerate(text.split("\f")):
            if k and any(x.strip() for x in pages[-1]):
                pages.append([])
            piece = piece.strip()
            if piece:
                pages[-1].append(piece)
                if heading:
                    heads.add(" ".join(piece.split()))

    v7 = version >= 7

    def paragraph(p, in_box: bool = False) -> None:
        boxes: list | None = [] if v7 else None
        text, new_page = para_text(p, boxes)
        if in_box:   # (a box does not start a page of the document)
            text, new_page = text.replace("\f", " "), False
        st = style(p).lower().replace(" ", "")
        add(text, new_page, st == "title" or bool(re.fullmatch(r"heading[1-9]", st)))
        if version >= 5 and figs is not None:
            for d in p.iter(f"{_WP}docPr"):
                alt = " ".join((d.get("descr") or d.get("title") or "").split())
                if alt and alt != d.get("name") and alt not in figs:
                    figs.add(alt)
                    add(alt, False, False)
        for box in boxes or []:   # reader 7: a text box's paragraphs and tables, after the paragraph that holds it
            for b in _docx_blocks(box):
                if b.tag == f"{_W}p":
                    paragraph(b, True)
                else:
                    table(b)

    def flat(el) -> str:
        """Reader 7: the words of a text box in a table's cell, once, its own boxes after their paragraph."""
        parts = []
        for b in _docx_blocks(el):
            if b.tag == f"{_W}p":
                boxes: list = []
                parts.append(para_text(b, boxes)[0].replace("\f", " ").strip())
                parts += [flat(x) for x in boxes]
            else:
                parts += [flat(cell) for row in _docx_children(b, f"{_W}tr")
                          for cell in _docx_children(row, f"{_W}tc")]
        return " ".join(x for x in parts if x)

    def table(tbl) -> None:
        # reader 4: each row once, its cells' own paragraphs; a table in a cell comes after the row that holds it
        for row in _docx_children(tbl, f"{_W}tr"):
            cells, inner = [], []
            for cell in _docx_children(row, f"{_W}tc"):
                parts = []
                for b in _docx_blocks(cell):
                    if b.tag == f"{_W}tbl":
                        inner.append(b)
                    elif v7:   # a text box in the cell: its words once, after its paragraph's, in the cell
                        boxes: list = []
                        parts.append(para_text(b, boxes)[0].replace("\f", " ").strip())
                        parts += [flat(x) for x in boxes]
                    else:
                        parts.append(para_text(b)[0].replace("\f", " ").strip())
                cells.append(" ".join(x for x in parts if x).strip() if v7 else " ".join(parts).strip())
            add(" | ".join(c for c in cells if c), False, False)
            for t in inner:
                table(t)

    if version < 4:
        for child in list(body) if body is not None else []:
            if child.tag == f"{_W}p":
                paragraph(child)
            elif child.tag == f"{_W}tbl":
                for row in child.iter(f"{_W}tr"):
                    cells = []
                    for cell in row.iter(f"{_W}tc"):
                        cells.append(" ".join(para_text(p)[0].replace("\f", " ").strip()
                                              for p in cell.iter(f"{_W}p")).strip())
                    add(" | ".join(c for c in cells if c), False, False)
    else:
        for child in _docx_blocks(body) if body is not None else []:
            if child.tag == f"{_W}p":
                paragraph(child)
            else:
                table(child)
    out = ["\n\n".join(pg) for pg in pages if any(x.strip() for x in pg)]
    return out or [""], heads


def _md_line(ln: str) -> str:
    ln = re.sub(r"^\s{0,3}#{1,6}\s+", "", ln)
    return re.sub(r"\s*\|\s*", " ", ln)


def strip_markdown(text: str) -> str:
    """Remove markdown table rules, cell bars and heading marks so table text reads as plain words."""
    lines = []
    for ln in text.split("\n"):
        if re.fullmatch(r"[\s|:\-]*\|[\s|:\-]*", ln) and "-" in ln:
            continue  # table separator row
        lines.append(_md_line(ln))
    return "\n".join(lines)


def markdown_headings(text: str) -> set[str]:
    """The heading lines of a markdown file (# …), as `strip_markdown` leaves them."""
    return {" ".join(_md_line(ln).split()) for ln in text.split("\n") if re.match(r"^\s{0,3}#{1,6}\s+\S", ln)}


# ------------------------------------------------------------------------------------------
# OCR of scanned PDF pages (optional: `pip install 'enlens-claims[ocr]'` and the program tesseract)
# ------------------------------------------------------------------------------------------
SCANNED_CHARS = 30   # a PDF page with less text than this is taken to be a scan
OCR_DPI = 200


@dataclass
class OcrOptions:
    mode: str = "auto"   # auto: recognise the text of scanned pages when OCR is installed; off: never
    lang: str = "eng"    # Tesseract languages, e.g. "eng+nld"


_OCR_STATUS: list = [0.0, None]
TESSERACT_PLACES = ["/opt/homebrew/bin/tesseract", "/usr/local/bin/tesseract", "/opt/local/bin/tesseract"]


def find_tesseract() -> str:
    """The tesseract program: the PATH, or where its installers put it (0.10). An app started from its icon has a
    short PATH (on macOS without Homebrew's folder), and the Windows installer does not add itself to the PATH."""
    import os

    found = shutil.which("tesseract")
    if found:
        return found
    candidates = [Path(p) for p in TESSERACT_PLACES]
    for var in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        base = os.environ.get(var)
        if base:
            candidates += [Path(base) / "Tesseract-OCR" / "tesseract.exe", Path(base) / "Programs" / "Tesseract-OCR" / "tesseract.exe"]
    for c in candidates:
        if c.is_file():
            return str(c)
    return ""


# How to get Tesseract on each system (shown by the app when a scanned page stayed without text)
TESSERACT_HELP = {
    "mac": {"text": "With Homebrew (brew.sh), type this in Terminal:", "command": "brew install tesseract",
            "link": "https://tesseract-ocr.github.io/tessdoc/Installation.html", "link_text": "Other ways to install it"},
    "windows": {"text": "Download and run the Tesseract installer for Windows (from the University of Mannheim, "
                        "which the Tesseract project links to).", "command": "",
                "link": "https://github.com/UB-Mannheim/tesseract/wiki", "link_text": "Tesseract installer for Windows"},
    "linux": {"text": "Install it with your system's packages, for example:", "command": "sudo apt install tesseract-ocr",
              "link": "https://tesseract-ocr.github.io/tessdoc/Installation.html", "link_text": "Other systems"},
}


def ocr_status(max_age: float = 60.0) -> dict:
    """Whether scanned pages can be read here: {"available": bool, "missing": [...], "languages": [...]}.
    Checked again after a minute, so installing Tesseract while the app runs is noticed."""
    import importlib.util
    import time

    if _OCR_STATUS[1] is not None and time.time() - _OCR_STATUS[0] < max_age:
        return dict(_OCR_STATUS[1])

    missing = [m for m, mod in (("pypdfium2", "pypdfium2"), ("pillow", "PIL")) if importlib.util.find_spec(mod) is None]
    exe = find_tesseract()
    if not exe:
        missing.append("tesseract")
    langs: list[str] = []
    if exe:
        try:
            import subprocess

            r = subprocess.run([exe, "--list-langs"], capture_output=True, text=True, timeout=10, **no_window())
            langs = [ln.strip() for ln in (r.stdout or "").splitlines()[1:] if ln.strip() and ln.strip() != "osd"]
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    from .installation import system

    _OCR_STATUS[:] = [time.time(), {"available": not missing, "missing": missing, "languages": langs,
                                    "install": TESSERACT_HELP[system()] if "tesseract" in missing else None}]
    return dict(_OCR_STATUS[1])


def _low_priority() -> None:  # runs in the OCR child process before tesseract starts (POSIX)
    import os

    try:
        os.nice(10)
    except OSError:
        pass


def _ocr_pages(path: Path, numbers: list[int], lang: str, should_stop=None) -> dict[int, str]:
    """The text of the given pages (0-based), recognised one page at a time at low priority on one thread, so a
    local model working at the same time keeps the computer's resources. Each page image is freed at once.
    0.14.3: Stop (`should_stop`) is seen before each page (raises Stopped): a 400-page scan could not be stopped."""
    import io
    import os
    import subprocess

    import pypdfium2 as pdfium

    exe = find_tesseract()
    if not exe or not re.fullmatch(r"[A-Za-z_]{2,}(\+[A-Za-z_]{2,})*", lang or ""):
        return {}
    env = {**os.environ, "OMP_THREAD_LIMIT": "1"}
    out: dict[int, str] = {}
    pdf = pdfium.PdfDocument(str(path))
    try:
        for i in numbers:
            if should_stop and should_stop():
                raise Stopped()
            if i >= len(pdf):
                continue
            page = pdf[i]
            try:
                bitmap = page.render(scale=OCR_DPI / 72, grayscale=True)
                image = bitmap.to_pil()
                buf = io.BytesIO()
                image.save(buf, format="PNG")
                del image, bitmap
                png = buf.getvalue()
                buf.close()
            finally:
                page.close()
            try:
                r = subprocess.run([exe, "stdin", "stdout", "-l", lang], input=png, capture_output=True, env=env,
                                   timeout=300, preexec_fn=_low_priority if os.name == "posix" else None,
                                   **no_window())  # 0.15.3: a window for each page
            except (OSError, subprocess.SubprocessError):
                continue
            finally:
                del png
            if r.returncode == 0:
                out[i] = r.stdout.decode("utf-8", errors="replace")
    finally:
        pdf.close()
    return out


class _LineSpots:
    """Collects where each line of a page's extracted text starts on the page, during the same extraction (pypdf's
    text visitor sees the text exactly as it is returned), so paragraph gaps and indents can be seen later."""

    def __init__(self):
        self.line = 0
        self.spots: dict[int, tuple[float, float]] = {}

    def __call__(self, text, cm, tm, _font, _size):
        if not text:
            return
        try:
            x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
            y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
        except (TypeError, IndexError):
            x = y = None
        for k, piece in enumerate(text.split("\n")):
            if k:
                self.line += 1
            if piece.strip() and self.line not in self.spots and x is not None:
                self.spots[self.line] = (float(x), float(y))

    def lines(self, text: str) -> list[tuple[float, float] | None]:
        return [self.spots.get(i) for i in range(text.count("\n") + 1)]


PROTECTED_PDF = "password-protected: save a copy without the password (or print it to a new PDF) and add that"


def _locked(reader) -> bool:
    """0.14.3: whether a PDF needs a password to be read (one with only an owner's password opens without one)."""
    try:
        if not reader.is_encrypted:
            return False
        return not reader.decrypt("")
    except Exception:  # noqa: BLE001 - an encryption pypdf cannot undo here: the text cannot be read either
        return True


def _read_pdf(path: Path, ocr: OcrOptions | None = None,
              should_stop=None, sizes: list | None = None) -> tuple[list[str], str | None, int, int, list | None]:
    """The text of each page, the title from the metadata, (pages recognised by OCR, scanned pages), and where each
    line starts on its page (for the layout; None for pages read another way). A PDF that needs a password raises
    ValueError (0.14.3: it was reported as a file without text)."""
    pages: list[str] = []
    pos: list | None = []
    title = None
    locked = False
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        locked = _locked(reader)
        try:
            meta = reader.metadata if not locked else None
            title = (meta.title if meta else None) or None
        except Exception:
            title = None
        for pg in reader.pages if not locked else []:
            if sizes is not None:
                try:
                    sizes.append((float(pg.mediabox.width), float(pg.mediabox.height)))
                except Exception:  # noqa: BLE001 - a page without a usable box: no positions for it
                    sizes.append((0.0, 0.0))
            spots = _LineSpots()
            try:
                t = pg.extract_text(visitor_text=spots) or ""
                pages.append(t)
                pos.append(spots.lines(t))
            except Exception:
                pages.append("")
                pos.append(None)
    except Exception:
        pages, pos = [], []
    if locked:
        raise ValueError(PROTECTED_PDF)
    n_pdf = len(pages)
    if sum(len(p.strip()) for p in pages) < 200:
        try:  # optional fallback
            from pdfminer.high_level import extract_text

            alt = extract_text(str(path)) or ""
            if len(alt.strip()) > sum(len(p.strip()) for p in pages):
                # pdfminer ends every page with a form feed: without taking the last one off there was one page too
                # many, so the scanned pages were not found and never recognised (0.14.3)
                pages = (alt[:-1] if alt.endswith("\f") else alt).split("\f")
                pos = None
        except Exception:
            pass
    if title and (len(title) < 8 or re.search(r"microsoft|untitled|\.docx?$|\.pdf$", title, re.I)):
        title = None
    scanned = [i for i, p in enumerate(pages) if len(p.strip()) < SCANNED_CHARS] if len(pages) == n_pdf else []
    done = 0
    if scanned and ocr is not None and ocr.mode != "off" and ocr_status()["available"]:
        for i, t in _ocr_pages(path, scanned, ocr.lang, should_stop).items():
            if len(t.strip()) > len(pages[i].strip()):
                pages[i] = t
                if pos is not None:
                    pos[i] = None
                done += 1
    return pages, title, done, len(scanned), pos


# ------------------------------------------------------------------------------------------
# cleaning and segmentation
# ------------------------------------------------------------------------------------------
def clean_page(text: str) -> str:
    t = text.replace("\r", "\n")
    t = re.sub(r"(?<=[a-z])-\n(?=[a-z])", "", t)  # hyphenation at line ends
    t = re.sub(r"[ \t\f\v]+", " ", t)
    t = re.sub(r"\s*\n\s*", " ", t)  # line breaks inside a page become spaces
    return t.strip()


def assemble(pages: list[str]) -> tuple[str, list[tuple[int, int]]]:
    text_parts: list[str] = []
    spans: list[tuple[int, int]] = []
    pos = 0
    for i, p in enumerate(pages):
        c = clean_page(p)
        if i:
            text_parts.append("\n\n")
            pos += 2
        spans.append((pos, pos + len(c)))
        text_parts.append(c)
        pos += len(c)
    return "".join(text_parts), spans


# ------------------------------------------------------------------------------------------
# layout: paragraphs and headings, found in the raw page text (the stored text keeps no line breaks)
# ------------------------------------------------------------------------------------------
_P, _H, _E = "\x02", "\x03", "\x04"          # markers: paragraph start, heading start, heading end
_ENDS_SENTENCE = re.compile(r"[.!?:][\"'”’)\]]*$")
_STARTS_UPPER = re.compile(r"[\"'“‘(\[]*[A-ZÀ-ÖØ-Þ]")


@dataclass
class Layout:
    paragraphs: list[tuple[int | None, int]] = field(default_factory=list)  # (page or None, document offset)
    headings: list[tuple[int, int, str]] = field(default_factory=list)       # (start, end, text)


def _is_heading(t: str, prev: str | None, nxt: str | None, short: float, known: set[str] | None = None) -> bool:
    """A short line with no closing punctuation, after the end of a sentence (or a blank line), followed by text:
    "Summary", "3. Discussion", "Results and implications". Web pages and markdown say which lines are headings
    (`known`: h1–h6 elements, # lines); for them only those count."""
    if known is not None:
        return " ".join(t.split()) in known
    if not (2 <= len(t) <= 80) or len(t) > short or nxt is None:
        return False
    if t[-1] in ".,;:!?-–—/" or not re.match(r"[A-ZÀ-ÖØ-Þ0-9]", t):
        return False
    if len(re.findall(r"[^\W\d_]", t)) < 2 or re.fullmatch(r"(page\s*)?\d+(\s*(of|/)\s*\d+)?", t, re.I):
        return False
    return prev is None or prev == "" or bool(_ENDS_SENTENCE.search(prev))


_SECTION_NO = re.compile(r"(\d{1,2}(\.\d{1,2})*\.?|[IVX]{1,4}\.)\s+[A-ZÀ-ÖØ-Þ]")


def _pdf_breaks(lines: list[str], spots: list | None) -> set[int]:
    """Lines of a PDF page that start a paragraph by their position: after a vertical gap clearly larger than the
    line spacing, or indented from the left margin after a line that ends a sentence."""
    if not spots or len(spots) != len(lines):
        return set()
    seq = [(i, spots[i]) for i, ln in enumerate(lines) if ln.strip() and spots[i] is not None]
    gaps = [a[1][1] - b[1][1] for a, b in zip(seq, seq[1:]) if 0 < a[1][1] - b[1][1] < 200]
    if len(gaps) < 3:
        return set()
    step = sorted(gaps)[len(gaps) // 4]  # the line spacing: the commonest small gap (paragraph gaps are larger)
    xs = sorted(p[0] for _i, p in seq)
    margin = xs[len(xs) // 4]  # the left margin: most lines start there
    out = set()
    for (i0, p0), (i1, p1) in zip(seq, seq[1:]):
        gap = p0[1] - p1[1]
        if gap > 1.45 * step:
            out.add(i1)
        elif (0 < gap and p1[0] - margin >= max(6.0, 0.6 * step) and p0[0] - margin < 0.3 * step
              and _ENDS_SENTENCE.search(lines[i0].strip())):
            out.add(i1)
    return out


def _page_layout(page: str, pdf: bool, known: set[str] | None = None,
                 spots: list | None = None) -> tuple[str, list[int], list[tuple[int, int]]] | None:
    """Mark paragraph and heading lines of one raw page, clean it as `clean_page` does, and return
    (cleaned text, paragraph offsets, heading spans) in the cleaned page. None when the page cannot be mapped."""
    if any(c in page for c in (_P, _H, _E)):
        return None
    if "\r" in page:
        spots = None
    lines = page.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    stripped = [ln.strip() for ln in lines]
    filled = [len(s) for s in stripped if s]
    if not filled:
        return None
    median = sorted(filled)[len(filled) // 2]
    short = 0.8 * median if pdf and median > 40 else 80.0   # wrapped PDF lines: a heading is clearly shorter
    nonblank = [i for i, s in enumerate(stripped) if s]
    first = nonblank[0]
    out = list(lines)
    placed = _pdf_breaks(lines, spots) if pdf else set()
    for j, i in enumerate(nonblank):
        t = stripped[i]
        prev = stripped[i - 1] if i > 0 else None
        nxt = stripped[nonblank[j + 1]] if j + 1 < len(nonblank) else None
        block_start = i == first or prev == ""
        heading = _is_heading(t, prev if i > first else None, nxt, short, known)
        lead = len(lines[i]) - len(lines[i].lstrip())
        body = lines[i].rstrip()
        para = block_start or (pdf and (heading or i in placed))
        if pdf and not para and prev and _ENDS_SENTENCE.search(prev):
            # a short line that ends a sentence, then a capital; or a numbered section ("2. Results", "IV. Data")
            para = (len(prev) < 0.8 * median and bool(_STARTS_UPPER.match(t))) or bool(_SECTION_NO.match(t))
        if heading:
            out[i] = body[:lead] + (_P if para else "") + _H + body[lead:] + _E + lines[i][len(body):]
        elif para:
            out[i] = lines[i][:lead] + _P + lines[i][lead:]
    marked = clean_page("\n".join(out))
    text, paras, heads, h_at = [], [], [], None
    for ch in marked:
        if ch == _P:
            paras.append(len(text))
        elif ch == _H:
            h_at = len(text)
        elif ch == _E:
            if h_at is not None:
                heads.append((h_at, len(text)))
            h_at = None
        else:
            text.append(ch)
    cleaned = "".join(text)
    if cleaned != clean_page(page):  # the markers changed how the page was cleaned: do not guess
        return None
    return cleaned, sorted(set(paras)), heads


def layout(raw: "RawDoc", text: str, spans: list[tuple[int, int]]) -> Layout:
    """Paragraphs and headings of a document, as offsets into its stored text (which is not changed).

    - text files and web pages: a paragraph is a block between blank lines, as 0.5.1 counted them;
    - PDFs: every page starts a paragraph (they are numbered per page: "page 2, paragraph 3"), and so does a line
      after a vertical gap, an indented line after the end of a sentence, a line after a short line that ends a
      sentence when it starts with a capital, a numbered section ("2. Results") and a heading;
    - headings (any kind): see `_is_heading`. A heading and the text that follows it without a break are one
      paragraph, so a reader counts "the paragraph under Results" as one.
    """
    out = Layout()
    pdf = raw.kind == "pdf"
    for n, (page, (s0, e0)) in enumerate(zip(raw.pages, spans), 1):
        spots = raw.line_pos[n - 1] if raw.line_pos and n - 1 < len(raw.line_pos) else None
        got = _page_layout(page, pdf, raw.headings, spots)
        pg = n if raw.paginated else None
        if got is None or got[0] != text[s0:e0]:
            if raw.paginated and e0 > s0:
                out.paragraphs.append((pg, s0))  # at least the page itself
            continue
        _cleaned, paras, heads = got
        if raw.paginated and e0 > s0 and (not paras or paras[0] > 0):
            paras = [0] + paras
        out.paragraphs += [(pg, s0 + p) for p in paras if s0 + p < e0]
        out.headings += [(s0 + a, s0 + b, text[s0 + a:s0 + b]) for a, b in heads if b > a]
    if not raw.paginated and not out.paragraphs and text:
        out.paragraphs = [(None, s) for s in paragraph_starts(raw.pages, text)]
    return out


def paragraph_starts(pages: list[str], text: str) -> list[int]:
    """Where each paragraph of the source (blocks separated by a blank line) starts in the cleaned text, so a quote
    in a text or web page can be cited as "paragraph 7". Cleaning joins lines, so the breaks are found in the source."""
    out: list[int] = []
    cursor = 0
    for page in pages:
        for para in re.split(r"\n[ \t]*\n", page.replace("\r\n", "\n").replace("\r", "\n")):
            key = clean_page(para)[:60]
            if not key:
                continue
            pos = text.find(key, cursor)
            if pos < 0:
                continue
            out.append(pos)
            cursor = pos + len(key)
    return out


def page_of(offset: int, spans: list[tuple[int, int]], ends: list[int] | None = None) -> int:
    """1-based page number for a document offset (the blank line after a page counts as that page).

    `ends` (each span's end + 2, precomputed by the caller) makes the lookup a binary search.
    """
    if ends is None:
        ends = [e + 2 for _s, e in spans]
    i = bisect.bisect_right(ends, offset)
    return i + 1 if i < len(spans) else max(1, len(spans))


def references_start(text: str) -> int | None:
    """Offset where the reference list begins, if a heading is found in the last 60% of the text."""
    floor = int(len(text) * 0.4)
    best = None
    for m in REF_HEADING.finditer(text):
        if m.start(1) >= floor:
            best = m.start(1)
            break
    return best


def reference_like(s: str) -> bool:
    """True for passages that read like bibliography entries rather than prose."""
    years = len(re.findall(r"\b(19|20)\d{2}[a-z]?\b", s))
    dois = len(re.findall(r"10\.\d{4,9}/", s))
    etal = len(re.findall(r"\bet al\.?", s))
    vols = len(re.findall(r"\b\d+\s*\(\d+\)\s*[:,]\s*\d+", s)) + len(re.findall(r"\bpp?\.\s*\d+", s))
    words = max(1, len(s.split()))
    return dois >= 2 or (years + etal + vols) / words > 0.08


CID_RE = re.compile(r"\(cid:\d+\)")
_WORD_RE = re.compile(r"[^\W\d_]{2,}")
# function words of the languages the corpus may contain; prose has many, glyph-code garble has none
_FUNCTION_WORDS = frozenset(
    "the of and to in for is on that by with as are from be this or an at which it can will not has have was "
    "de la le les et des du en el los las y que con por para del una un se al lo es da do dos das em os ao "
    "der die das und von mit den dem ist im zu het een van voor op te zijn niet "
    # 0.14.3: Hungarian, Italian, Polish, Czech and Slovak, the Nordic languages, Finnish, Romanian, Croatian: prose in
    # them had too few of the words above and was marked unreadable (none of these is a glyph-shifted English word)
    "az és hogy nem egy van meg ez mint csak vagy már még ahol amely ami azt ezt kell lehet szerint között után "
    "il di che per non sono della nel gli alla delle anche nie się na jest że od po jak oraz je pro jako ve ale "
    "och att det är som på för med av ett og er til ikke af ja on että ei și în cu pe care din sunt su za".split())


def unreadable(s: str) -> bool:
    """True when a PDF text layer has no usable character map.

    Two forms occur: '(cid:53)(cid:72)...' codes, and fonts whose glyph codes come out as shifted
    letters and control characters ('5HQHZDEOH DQG ...' for 'Renewable and ...').
    """
    n = max(1, len(s))
    if len(CID_RE.findall(s)) * 8 > 0.2 * n:
        return True
    ctrl = sum(1 for c in s if (ord(c) < 32 and c not in "\n\t") or c == "�" or 0xE000 <= ord(c) <= 0xF8FF)
    if ctrl > 0.05 * n:
        return True
    words = _WORD_RE.findall(s.lower())
    numbers = len(re.findall(r"(?<![^\s(])\d[\d.,%]*(?![^\s),;:])", s))  # tables and charts are mostly numbers
    return (len(words) >= 30 and numbers < 0.1 * len(words)
            and sum(w in _FUNCTION_WORDS for w in words) < 0.02 * len(words))


def make_passages(text: str, spans: list[tuple[int, int]], max_chars: int = 1100, min_chars: int = 200) -> list[Passage]:
    ref_at = references_start(text)
    sents: list[tuple[int, int]] = []
    for s, e in spans:
        for a, b in split_sentences(text[s:e], offset=s):
            # break very long "sentences" (tables, run-on extraction) at whitespace
            while b - a > max_chars:
                cut = text.rfind(" ", a + min_chars, a + max_chars)
                forced = cut <= a
                cut = cut if not forced else a + max_chars
                sents.append((a, cut))
                a = cut if forced else cut + 1  # a forced cut lands on a character, not a space (0.11.1)
            if b > a:
                sents.append((a, b))
    out: list[Passage] = []
    cur: list[tuple[int, int]] = []
    ends = [e + 2 for _s, e in spans]

    def flush():
        if not cur:
            return
        a, b = cur[0][0], cur[-1][1]
        pg = page_of(a, spans, ends)
        if ref_at is not None and a >= ref_at:
            section = "references"
        elif unreadable(text[a:b]):
            section = "unreadable"
        elif reference_like(text[a:b]):
            section = "reference_like"
        else:
            section = "body"
        out.append(Passage(len(out), a, b, pg, section))
        cur.clear()

    for a, b in sents:
        crosses_refs = ref_at is not None and cur and cur[0][0] < ref_at <= a
        new_page = cur and page_of(a, spans, ends) != page_of(cur[0][0], spans, ends)
        if cur and ((b - cur[0][0] > max_chars) or crosses_refs or (new_page and cur[-1][1] - cur[0][0] >= min_chars)):
            flush()
        cur.append((a, b))
    flush()
    return out


def guess_title(raw: RawDoc, text: str) -> str:
    if raw.meta_title:
        return re.sub(r"\s+", " ", raw.meta_title).strip()[:300]
    if raw.kind in ("text", "docx") and raw.pages:  # a text file's title is its first line (cleaning joins the lines)
        first = next((ln.strip() for ln in raw.pages[0].splitlines() if ln.strip()), "")
        if 10 <= len(first) <= 250:
            return first
    head = text[:400]
    first = re.split(r"(?<=[.!?])\s", head)[0]
    return (first or raw.path.stem)[:200]


def guess_doi(raw: RawDoc, text: str, spans: list[tuple[int, int]]) -> str | None:
    """The paper's own DOI: from the file name, else the most frequent DOI before the references."""
    stem = raw.path.stem.replace("_", "/").replace("%2F", "/")
    from_name = find_dois(stem)
    if from_name:
        return from_name[0]
    cut = references_start(text) or len(text)
    counts: Counter[str] = Counter()
    first_seen: dict[str, int] = {}
    for s, e in spans[:4]:
        for d in find_dois(text[s:min(e, cut)]):
            counts[d] += 1
            first_seen.setdefault(d, s)
    if not counts:
        return None
    return sorted(counts, key=lambda d: (-counts[d], first_seen[d]))[0]


def read_document(path: Path, reader: int | None = None, ocr: "OcrOptions | None" = None, max_chars: int = 1100,
                  min_chars: int = 200, should_stop=None) -> Document:
    """0.15: a file read into a Document by the given reader (default: the current one, READER). Nothing is stored:
    `ingest` stores what this returns, `enlens measure` compares readers, and *Read with the new reader* reads a
    document of a project again with it. Passages whose section is 'body' are the ones features use."""
    raw = read_file(Path(path), ocr if ocr is not None else OcrOptions(mode="off"), should_stop)
    return build_document(raw, max_chars, min_chars, reader)


def build_document(raw: RawDoc, max_chars: int = 1100, min_chars: int = 200, reader: int | None = None) -> Document:
    raw = raw.as_read_by(reader or READER)
    if (reader or READER) >= 2:
        from . import reader as reader2

        return reader2.build_document(raw, max_chars, min_chars, min(reader or READER, reader2.READER))
    return _build_document_1(raw, max_chars, min_chars)


def _build_document_1(raw: RawDoc, max_chars: int = 1100, min_chars: int = 200) -> Document:
    """Reader 1 (ENLENS 0.5 to 0.14): the page text as pypdf gives it, cleaned, cut into passages by sentences."""
    text, spans = assemble(raw.pages)
    doc = Document("d" + raw.sha1[:10], raw, text, spans, guess_title(raw, text), guess_doi(raw, text, spans))
    doc.passages = make_passages(text, spans, max_chars, min_chars)
    doc.layout = layout(raw, text, spans)
    if not raw.paginated:
        for p in doc.passages:
            p.page = None
        doc.paragraphs = [s0 for _pg, s0 in doc.layout.paragraphs]
    return doc


# ------------------------------------------------------------------------------------------
# input discovery
# ------------------------------------------------------------------------------------------
MAX_UNPACKED = 8 * 1024 ** 3   # bytes written from the zips of one ingest, nested ones included (zip bombs)


def zip_name(info: zipfile.ZipInfo) -> str:
    """The name of a file in a zip. Zips that do not mark their names as UTF-8 (Finder's Compress, for one) are read
    by Python as code page 437, which garbles accented names ("másolat" became "ma╠üsolat"): they are read again as
    UTF-8 when they are that."""
    name = info.filename
    if not info.flag_bits & 0x800:
        try:
            name = name.encode("cp437").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return name


# 0.14.3: what reading a file out of a zip raises when the zip is damaged (a bad checksum, a cut-off file) or
# password-protected (RuntimeError "… is encrypted, password required"; NotImplementedError for AES encryption)
ZIP_ERRORS = (zipfile.BadZipFile, zlib.error, EOFError, RuntimeError)


def zip_problem(e: BaseException) -> str:
    """What went wrong with a zip, in words."""
    msg = str(e).lower()
    if isinstance(e, NotImplementedError):
        return "a kind of zip this program cannot unpack (perhaps password-protected): save it again as an ordinary zip"
    if isinstance(e, RuntimeError) and ("encrypted" in msg or "password" in msg):
        return "password-protected zip: save a copy without the password and add that"
    if isinstance(e, (zipfile.BadZipFile, zlib.error, EOFError)):
        return "damaged zip: copy or download it again"
    return str(e) or type(e).__name__


def _read_problem(e: BaseException) -> str:
    """Why a file could not be read, in words (a Word file is a zip inside)."""
    if isinstance(e, (zipfile.BadZipFile, zlib.error, EOFError)):
        return "damaged file: copy or download it again"
    if isinstance(e, ZIP_ERRORS) and not isinstance(e, NotImplementedError) and "password" in str(e).lower():
        return "password-protected: save a copy without the password and add that"
    return str(e) or type(e).__name__


def unpack_names(names: list[str]) -> list[str]:
    """The names to unpack a zip's files under, one per name in order: each as it is, except a name that is another's
    but for its case or the form of its accents ("Report.pdf" and "report.pdf"; "másolat.pdf" written with "á" or
    with "a" and its accent apart), which gets " (2)" (" (3)", …) before its extension. Hunt phase 1: a disk that does
    not tell such names apart (macOS's and Windows's, as they come) wrote the two files to one place, so the first
    document was read with the second's words and the second was then a duplicate: one of them was lost without a
    word. The plan is the same on every computer, so a zip unpacks to the same names everywhere."""
    seen: set[str] = set()
    out = []
    for name in names:
        key = unicodedata.normalize("NFC", name).casefold()
        if key in seen:
            head, slash, base = name.rpartition("/")
            stem, dot, ext = base.rpartition(".") if "." in base.lstrip(".") else (base, "", "")
            k = 2
            while True:
                new = f"{head}{slash}{stem} ({k}){dot}{ext}"
                key = unicodedata.normalize("NFC", new).casefold()
                if key not in seen:
                    name = new
                    break
                k += 1
        seen.add(key)
        out.append(name)
    return out


def _members(zf, strip: str = "") -> list[tuple[zipfile.ZipInfo, str]]:
    """The files `_safe_extract` unpacks, with their names in the zip (without `strip`)."""
    members = []
    for info in zf.infolist():
        name = zip_name(info)
        if info.is_dir() or name.startswith("__MACOSX") or Path(name).name.startswith("._"):
            continue
        if strip:
            if not name.startswith(strip) or name == strip:
                continue
            name = name[len(strip):]
        members.append((info, name))
    return members


def unpacked_names(zf, strip: str = "") -> dict[str, str]:
    """Hunt phase 1.5: {name in the zip (without `strip`): the name `_safe_extract(..., distinct=True)` unpacks it
    under}, for the names it changes only (`unpack_names`)."""
    names = [n for _i, n in _members(zf, strip)]
    return {a: b for a, b in zip(names, unpack_names(names)) if a != b}


def _safe_extract(zf: zipfile.ZipFile, dest: Path, budget: list[int] | None = None, strip: str = "",
                  problems: list[tuple[str, str]] | None = None, distinct: bool = False) -> list[Path]:
    """Unpack `zf` into `dest`. With `strip` (a folder in the zip, ending in "/"), only what is in that folder is
    unpacked, without the folder itself. 0.14.3: with `problems`, a file of the zip that cannot be unpacked (damaged,
    password-protected) is left out and noted there as (name, what went wrong); without it, that stops the unpacking
    (a project zip must come whole). With `distinct` (sources), two names that differ only by case or by the form
    of their accents are kept apart (`unpack_names`)."""
    out = []
    root = dest.resolve()
    budget = budget if budget is not None else [MAX_UNPACKED]
    members = _members(zf, strip)
    planned = unpack_names([n for _i, n in members]) if distinct else [n for _i, n in members]
    for (info, _name), name in zip(members, planned):
        if info.file_size > budget[0]:
            break  # the rest would exceed the budget: stop unpacking
        budget[0] -= info.file_size
        target = (dest / name).resolve()
        if not target.is_relative_to(root) or target == root:
            continue  # zip-slip guard (a string prefix test would let '../x_evil/...' through for a folder 'x')
        # never half a file in place of a whole one: unpacked beside it under a short name, then put in place
        part = target.with_name(f".{hashlib.sha1(name.encode('utf-8')).hexdigest()[:10]}.part")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(part, "wb") as dst:
                shutil.copyfileobj(src, dst)
            part.replace(target)
        except (*ZIP_ERRORS, OSError) as e:
            part.unlink(missing_ok=True)
            if problems is None:
                raise
            problems.append((name, zip_problem(e)))
            continue
        except BaseException:
            part.unlink(missing_ok=True)
            raise
        out.append(target)
    return out


def read_manifests(files: list[Path]) -> dict[str, dict]:
    """manifest.csv files (columns file, reference, doi; 0.11: optional ai_access and ai_note) say which references
    each file is, and who may read it with AI.

    Several rows may point at the same file (one work cited in several ways). Keyed by file name. Files saved
    by a spreadsheet are read whether they are UTF-8 (with or without a byte-order mark) or Windows-1252.
    """
    from .review import read_csv_rows

    out: dict[str, dict] = {}
    for m in files:
        if m.name.lower() != "manifest.csv":
            continue
        for row in read_csv_rows(m):
            names = set()
            for col in ("file", "markdown_file", "text_file"):
                pth = Path((row.get(col) or "").strip().replace("\\", "/"))
                if pth.name:
                    names |= {pth.name, "stem:" + pth.stem}  # a converted copy (.txt) keeps the stem
            for name in filter(None, names):
                e = out.setdefault(name, {"references": [], "doi": ""})
                ref = (row.get("reference") or "").strip()
                if ref and ref not in e["references"]:
                    e["references"].append(ref)
                if (row.get("doi") or "").strip() and not e["doi"]:
                    e["doi"] = row["doi"].strip()
                if (row.get("ai_access") or "").strip() and not e.get("ai_access"):
                    e["ai_access"] = row["ai_access"].strip()
                if (row.get("ai_note") or "").strip() and not e.get("ai_note"):
                    e["ai_note"] = row["ai_note"].strip()
    return out


# notes that travel with a corpus but are not sources
NOT_SOURCES = {"problems.txt", "readme.txt", "readme.md", "license.txt", "notes.txt", "worker_guide.md", "system.md"}


def _zip_failures(zname: str, problems: list[tuple[str, str]]) -> list[str]:
    """One line per kind of problem of a zip: "sources.zip: password-protected zip: … (report.pdf, notes.txt)"."""
    by: dict[str, list[str]] = {}
    for member, why in problems:
        by.setdefault(why, []).append(Path(member).name)
    return [f"{zname}: {why} ({', '.join(names[:3])}{f' and {len(names) - 3} more' if len(names) > 3 else ''})"
            for why, names in by.items()]


def discover(inputs: list[str | Path], unpack_dir: Path, manifests: list[Path] | None = None,
             failed: list[str] | None = None) -> list[Path]:
    """The source files among `inputs` (folders are searched, zips unpacked into `unpack_dir`, up to two levels
    deep). 0.14.3: with `failed`, a zip (or a file in it) that cannot be unpacked is noted there and the rest go on;
    before, one password-protected or damaged zip stopped the whole add."""
    files: list[Path] = []
    queue = [Path(p) for p in inputs]
    depth: dict[Path, int] = {}
    budget = [MAX_UNPACKED]  # shared by every zip of this call, nested ones included
    while queue:
        p = queue.pop(0)
        if p.is_dir():
            queue.extend(sorted(x for x in p.rglob("*") if x.is_file()))
        elif p.suffix.lower() == ".zip" and zipfile.is_zipfile(p):
            if depth.get(p, 0) > 2:
                continue
            # one folder per zip file: two zips with the same name (from different folders) must not mix. Hunt phase 1
            # (READERS-1): nor a zip and a newer one put at the same place later: the folder was named by the zip's
            # path only, so the newer zip unpacked over the first, and a document added from the first lost its
            # original (reported as changed, no longer opened or read again). Named by the path and the content, a
            # newer zip gets a folder of its own, and the same zip added again unpacks onto its own identical copy.
            # Documents added before keep the paths they recorded.
            try:
                content = _sha1(p)
            except OSError as e:
                if failed is None:
                    raise
                failed.append(f"{p.name}: {e.strerror or e}")
                continue
            tag = hashlib.sha1(f"{p.resolve()}\0{content}".encode()).hexdigest()[:8]
            stem = re.sub(r"[^A-Za-z0-9_-]", "_", p.stem).strip("_")[:60] or "zip"  # no dots: '...zip' cannot be '..'
            dest = unpack_dir / f"{stem}-{tag}"
            if not dest.resolve().is_relative_to(unpack_dir.resolve()):
                continue
            problems: list[tuple[str, str]] | None = [] if failed is not None else None
            try:
                with zipfile.ZipFile(p) as zf:
                    got = _safe_extract(zf, dest, budget, problems=problems, distinct=True)
            except (*ZIP_ERRORS, OSError) as e:
                if failed is None:
                    raise
                failed.append(f"{p.name}: {zip_problem(e)}")
                continue
            if problems:
                failed.extend(_zip_failures(p.name, problems))
            for x in got:
                depth[x] = depth.get(p, 0) + 1
                queue.append(x)
        elif p.suffix.lower() == ".zip" and p.is_file():
            # Hunt phase 1 (READERS-6): a zip cut off in a download has no list of its files at the end, so
            # `is_zipfile` says no, and it was passed over without a word: the add reported nothing about it
            if failed is not None:
                failed.append(f"{p.name}: {zip_problem(zipfile.BadZipFile())}")
        elif p.suffix.lower() in SUPPORTED and p.is_file() and p.name.lower() not in NOT_SOURCES:
            files.append(p)
        elif p.name.lower() == "manifest.csv" and manifests is not None:
            manifests.append(p)
        elif (failed is not None and p.suffix.lower() in NOT_READ_KINDS and p.is_file()
              and not p.name.startswith((".", "~$"))):
            # Hunt phase 1: a document of a kind ENLENS does not read (an older Word file, rich text, slides) was
            # passed over without a word, so a folder of .doc files added nothing and said nothing. It is named
            # under the files that could not be read, with what to do; other files (pictures, spreadsheets, notes)
            # are still passed over, as they are not documents to read
            failed.append(f"{p.name}: {NOT_READ_KINDS[p.suffix.lower()]}")
    return files


# ------------------------------------------------------------------------------------------
# 0.16 (H3): files read at once when documents are added. Reading a file is pure Python and parsing a PDF takes
# seconds, so several are read side by side, each in a process of its own (`readworker.py`). What is stored is taken
# in the order of the files, exactly as reading them one after the other stores it: only the waiting is shorter.
# ------------------------------------------------------------------------------------------
READ_WORKERS = 3                 # at most this many files read at once
POOL_MIN_BYTES = 512 * 1024      # a smaller batch is read in this process (starting the readers costs more)
WORKER_MEMORY = 600 * 1024 ** 2  # free memory each reader is given room for (a long PDF's layout is large)


def read_workers(files: list[Path]) -> int:
    """How many files to read at once: 1 for one file or a small batch, else up to READ_WORKERS, one less than the
    computer's processors and what its free memory allows. `ENLENS_READ_WORKERS` sets it (1: one at a time)."""
    env = os.environ.get("ENLENS_READ_WORKERS")
    if env is not None:
        try:
            return max(1, min(int(env), len(files)))
        except ValueError:
            return 1
    if len(files) < 2:
        return 1
    size = 0
    for f in files:
        try:
            size += f.stat().st_size
        except OSError:
            pass
    if size < POOL_MIN_BYTES:
        return 1
    n = min(READ_WORKERS, (os.cpu_count() or 2) - 1, len(files))
    try:
        from .llm import free_memory

        free = free_memory()
    except Exception:  # noqa: BLE001 - not known: the processors decide
        free = None
    if free is not None:
        n = min(n, free // WORKER_MEMORY)
    return max(1, int(n))


def _read_whole(f: Path, ocr: OcrOptions, max_chars: int, min_chars: int, should_stop=None,
                known: frozenset | set = frozenset()) -> tuple:
    """A file read and made into a Document, as `ingest` does it: ("ok", raw, doc); ("failed", the problem in words);
    ("stopped",) for Stop during OCR; ("unbuilt", raw, the exception) when the Document could not be made, which
    `ingest` lists under `failed` for a file that is not a duplicate (hunt phase 1.5: it raised it). A file whose checksum is in `known` (a
    duplicate) is not read at all: ("ok", a RawDoc with its checksum and no text, None), as `ingest` only counts a
    duplicate. What storing never reads (each line of the layout, the pages' raw text) is let go (`_lighten`)."""
    if known:
        cs = _checksum(f)
        if cs is not None and cs in known:  # a file already stored: parsing it (or recognising its scans) is wasted
            return ("ok", _duplicate(f, cs), None)
    try:
        raw = read_file(f, ocr, should_stop)
    except Stopped:
        return ("stopped",)
    except Exception as e:  # noqa: BLE001 - one unreadable file should not stop the others
        return ("failed", _read_problem(e))
    if raw.sha1 in known:
        return ("ok", _lighten_raw(raw), None)
    try:
        return ("ok", raw, _lighten(build_document(raw, max_chars, min_chars)))
    except Exception as e:  # noqa: BLE001 - listed by `ingest` once it knows the file is new
        return ("unbuilt", raw, e)


def _checksum(f: Path) -> str | None:
    """The checksum `read_file` gives a file (None when it cannot be read now: reading it says why)."""
    try:
        if f.suffix.lower() in (".pdf", ".docx"):
            return _sha1(f)
        return hashlib.sha1(f.read_bytes()).hexdigest()
    except OSError:
        return None


def _duplicate(f: Path, sha1: str) -> RawDoc:
    """What `ingest` needs of a file it already has: its checksum (the kind as `read_file` names it)."""
    ext = f.suffix.lower()
    kind = {".pdf": "pdf", ".docx": "docx", ".html": "html", ".htm": "html"}.get(ext, "text")
    return RawDoc(f, kind, [], None, sha1)


def _lighten_raw(raw: RawDoc) -> RawDoc:
    raw.pages = []        # the text is the Document's now; storing reads the page spans, not this
    raw.line_pos = None   # where each line starts: only the reader reads it
    return raw


def _lighten(doc: "Document") -> "Document":
    """A Document as storing it needs it: each block's box kept (it is worked out from the block's lines, so one line
    with that box stands for them), every other line, each block's own copy of its words (storing reads the
    Document's text) and the raw page text let go. A reading process sends far less back, and a reading kept for
    later holds less memory. What is stored does not change: a block whose box would come out otherwise keeps its
    lines."""
    for b in getattr(doc, "blocks", None) or []:
        b.text = ""
        lines = b.lines
        if len(lines) <= 1:
            continue
        box = b.bbox
        if box is None:
            b.lines = []
        else:
            from .reader import Line

            b.lines = [Line(lines[0].page, "", x0=box[0], top=box[1], x1=box[2], bottom=box[3])]
        if b.bbox != box:  # a box of zero width or height at the page's edge reads otherwise from one line
            b.lines = lines
    _lighten_raw(doc.raw)
    return doc


# a file read whose passages could not be made (`_ingest_files`, "unbuilt"): said under `failed`
UNBUILT = "it was read, but ENLENS could not make its passages (a fault in ENLENS: please report this file)"
# a file whose reading ended its reading process (`_Readings._away`): said under `failed`
CRASHED = ("reading it stopped the reading program (the file may be damaged, or too large to read with the memory "
           "this computer has free)")
_LIVE: "weakref.WeakSet" = weakref.WeakSet()  # every reading process started and not yet ended
_LIVE_LOCK = threading.Lock()
_ENDING = False  # set by end_reading_processes: no reading process is started after it


def end_reading_processes() -> None:
    """End every reading process this program started, at once (a file half read is simply not added), and start no
    other: the files still to read are read here. Run when ENLENS exits (atexit), and by the app before it becomes
    its new version (`os.execv` runs no exit handlers, and keeps the process number the readers watch)."""
    global _ENDING
    with _LIVE_LOCK:
        _ENDING = True
        procs = list(_LIVE)
    for p in procs:
        try:
            if p.poll() is None:
                p.kill()
        except OSError:
            pass


atexit.register(end_reading_processes)


class _Readings:
    """The readings of a batch of files, in their order. With `workers` above 1, files are read ahead in that many
    reading processes (`readworker.py`, each kept busy by a thread of its own); with 1, or for a file whose reading in
    a process went wrong (the process could not start, or its answer could not come back), here, the way `ingest`
    read every file before 0.16. Hunt phase 1.5: with Stop to obey (`should_stop`), in a reading process also with 1,
    so that Stop ends a file whose reading never ends; only when no reading process can start, or a file's reading
    failed in two processes one after the other, or its answer could not come back, is it read here. A file that ends
    its reading process (a crash, the memory used up) is listed as one that could not be read, and is not read here
    again. The threads are daemon threads and the processes end when ENLENS
    does (`end_reading_processes`), so neither Quit nor an update waits for a file being read; a reading process also
    ends by itself when the program that started it is gone."""

    def __init__(self, files: list[Path], ocr: OcrOptions, max_chars: int, min_chars: int, should_stop=None,
                 workers: int = 1, known: set | None = None):
        self.files, self.ocr, self.max_chars, self.min_chars = files, ocr, max_chars, min_chars
        self.should_stop = should_stop
        self.workers = workers
        self.known = known if known is not None else set()  # the checksums stored so far: `ingest`'s own set
        self.tasks = None  # the queue the reading threads take files from
        self.futures: dict[int, Future] = {}
        self.local = threading.local()
        self.lock = threading.Lock()
        self.procs: list = []
        self.closed = False
        self.stop_dir: str | None = None
        self.stop_file = ""
        self.parallel = False  # whether reading processes were used
        # hunt phase 1.5: with Stop to obey (`should_stop`: the app's jobs), every file is read in a reading process,
        # also a small batch read one at a time: a reading that hangs in this process could not be ended, and Stop
        # waited for it for ever. `ENLENS_READ_HERE=1` reads here (the tests, so that their stand-ins are what reads)
        self.away = should_stop is not None and os.environ.get("ENLENS_READ_HERE") != "1"

    def here(self, i: int) -> tuple:
        return _read_whole(self.files[i], self.ocr, self.max_chars, self.min_chars, self.should_stop, self.known)

    def _start(self) -> None:
        import queue
        import tempfile

        self.stop_dir = tempfile.mkdtemp(prefix="enlens-read-")
        self.stop_file = os.path.join(self.stop_dir, "stop")
        tasks: queue.Queue = queue.Queue()
        started = 0
        for n in range(self.workers):
            try:
                threading.Thread(target=self._serve, args=(tasks,), name=f"enlens-read-{n}", daemon=True).start()
            except RuntimeError:  # no more threads to be had: as many as started (none: one at a time, here)
                break
            started += 1
        if not started:
            shutil.rmtree(self.stop_dir, ignore_errors=True)
            raise RuntimeError("no reading thread could start")
        self.workers, self.tasks = started, tasks
        self.parallel = True

    def _serve(self, tasks) -> None:
        """A reading thread: the files put in the queue, each read by this thread's process, until None comes."""
        while True:
            item = tasks.get()
            if item is None:
                break
            j, fut = item
            if not fut.set_running_or_notify_cancel():
                continue
            try:
                fut.set_result(self._away(j))
            except BaseException as e:  # noqa: BLE001 - handed to the waiting `get`, which reads the file here
                fut.set_exception(e)
        p = getattr(self.local, "proc", None)
        if p is not None:
            try:
                p.stdin.close()  # an idle reading process ends when its input closes
            except OSError:
                pass

    def _process(self):
        """This thread's reading process, started when it has none or its last one ended: the same Python, finding
        its modules exactly where this program finds them (its `sys.path`), told which program to outlive."""
        import subprocess
        import sys

        p = getattr(self.local, "proc", None)
        if p is not None and p.poll() is None:
            return p
        code = (f"import sys; sys.path[:] = {sys.path!r}; "
                "from enlens_claims.readworker import main; sys.exit(main())")
        cmd = [sys.executable] + (["-X", "utf8"] if sys.flags.utf8_mode else []) + ["-c", code]
        env = {**os.environ, "ENLENS_READ_PARENT": str(os.getpid())}
        with self.lock, _LIVE_LOCK:
            if self.closed or _ENDING:
                raise ChildProcessError("the batch is over, or ENLENS is ending")
            p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                 env=env, **no_window())
            self.procs.append(p)
            _LIVE.add(p)
        self.local.proc = p
        return p

    def _away(self, i: int) -> tuple:
        """File i read by this thread's reading process (in a reading thread). A file already stored is not sent: only
        its checksum is needed. A process that ends while it reads the file (a crash, or the computer's memory used
        up) leaves that file unread, listed as one that could not be read: read here, it could take the app with it.
        The next file gets a new process."""
        from . import readworker

        f = self.files[i]
        cs = _checksum(f) if self.known else None  # a new project has no duplicate to look for
        if cs is not None and cs in self.known:
            return ("ok", _duplicate(f, cs), None)
        for attempt in (0, 1):
            p = self._process()
            try:
                readworker.send(p.stdin, (f, self.ocr, self.max_chars, self.min_chars, self.stop_file, frozenset()))
            except Exception:  # noqa: BLE001 - it had ended before it got the file: a new process takes it
                self._ended(p)
                if attempt:
                    raise ChildProcessError("the reading process ended") from None
                continue
            try:
                got = readworker.receive(p.stdout)
            except Exception:  # noqa: BLE001 - the pipe broke: as when the process ended
                got = None
            if got is not None:
                return got
            code = self._ended(p)
            ours = self.closed or _ENDING  # ended on purpose (the batch is over, or ENLENS is ending)
            if code not in (None, 0) and not ours:
                return ("failed", CRASHED)
            raise ChildProcessError("the reading process ended")
        raise ChildProcessError("the reading process ended")

    @staticmethod
    def _ended(p) -> int | None:
        """How a reading process that stopped answering ended: its exit code (a crash: not 0; ended by a signal: below
        0 on POSIX), or None when it was still running and is ended here."""
        try:
            return p.wait(timeout=2)
        except Exception:  # noqa: BLE001 - still running (its answer was garbled): ended here
            try:
                p.kill()
            except OSError:
                pass
            return None

    def get(self, i: int) -> tuple:
        if (self.workers > 1 or self.away) and self.tasks is None:
            try:
                self._start()
            except Exception:  # noqa: BLE001 - no threads or no temporary folder: one at a time, here
                self.workers, self.away = 1, False
        if self.tasks is None:
            return self.here(i)
        try:
            for j in range(i, min(len(self.files), i + self.workers + 1)):  # this file and the next ones
                if j not in self.futures:
                    fut: Future = Future()
                    self.futures[j] = fut
                    self.tasks.put((j, fut))
            got = self._wait(i, self.futures.pop(i))
        except Exception:  # noqa: BLE001 - this file's reading did not come back
            if not self.away:
                return self.here(i)  # read it here, the old way
            # hunt phase 1.5: once more in a new reading process, where Stop still reaches it; only a second failure
            # reads it here (as before: a process that ends on its own while it reads leaves the file to be read)
            try:
                fut = Future()
                self.tasks.put((i, fut))
                got = self._wait(i, fut)
            except Exception:  # noqa: BLE001
                return self.here(i)
        if got is None:
            return ("stopped",)
        if got[0] == "redo":
            return self.here(i)  # read already, in a process: only its answer could not come back
        if got[0] == "ok" and got[2] is None and got[1].sha1 not in self.known:
            return self.here(i)  # not built as a duplicate, but no longer one (cannot happen: the checksums only grow)
        return got

    def _wait(self, i: int, fut: Future):
        """The reading of file i, waited for while Stop is looked at every quarter second: None for Stop (this file is
        not added, as when Stop comes during the text recognition of a file read here; the batch ends and `close`
        ends the process still reading it)."""
        from concurrent.futures import TimeoutError as FutureTimeout

        while True:
            try:
                return fut.result(timeout=0.25)
            except FutureTimeout:
                if self.should_stop and self.should_stop():
                    self._stop()
                    self.futures[i] = fut  # still being read: `close` ends its process at once
                    return None

    def _stop(self) -> None:
        if self.stop_file and not os.path.exists(self.stop_file):
            try:
                Path(self.stop_file).touch()
            except OSError:
                pass

    def close(self) -> None:
        """Every reading process ended (those still reading a file the batch no longer needs, at once), the threads
        let go, the stop file's folder removed."""
        if self.tasks is None:
            return
        with self.lock:
            self.closed = True
            procs, self.procs = self.procs, []
        self._stop()
        busy = any(not f.done() for f in self.futures.values())
        for fut in self.futures.values():
            fut.cancel()
        self.futures.clear()
        for _ in range(self.workers):
            self.tasks.put(None)
        for p in procs:
            if busy and p.poll() is None:
                try:
                    p.kill()
                except OSError:
                    pass
        for p in procs:
            try:
                p.wait(timeout=5)
            except Exception:  # noqa: BLE001 - it ends by itself once its input closes
                pass
        self.tasks = None
        if self.stop_dir:
            shutil.rmtree(self.stop_dir, ignore_errors=True)


class AccessChoice(ValueError):
    """Hunt phase 1.5: why documents cannot be added with the AI setting asked for (`adding_access`). `kind`:
    "missing" (no setting given, and the project's default was never chosen) or "looser" (an AI asked for more than
    the project's chosen default); `default`: the project's default then."""

    def __init__(self, kind: str, default: str | None, message: str):
        super().__init__(message)
        self.kind, self.default = kind, default


def adding_access(ws: Workspace, ai_access: str | None, by_ai: bool = False) -> dict:
    """Hunt phase 1.5: THE rule for who may read documents being added, for every route that adds them (the connector,
    the command line; the app's routes should call it too). Returns {"ai_access": the setting to pass to `ingest`,
    "set_default": whether this answer becomes the project's default, "earlier": how many documents of the project
    follow a default nobody chose}. Raises AccessChoice:
    - no setting given while the project's default was never chosen ("missing": documents never become readable by an
      AI through silence; with a chosen default, it applies);
    - `by_ai` (the connector) and a setting looser than the project's chosen default ("looser": an AI does not open
      documents wider than the person chose; the person can, in the app's Documents page or the command line).
    A given setting becomes the project's default only when no document follows an unchosen default (a project
    without documents, as the app's first Add); otherwise it is the new documents' own, and the earlier ones keep
    following the default nobody chose: one answer about new files must not change who may read the others."""
    from . import access

    chosen = access.default_chosen(ws)
    dflt = access.default(ws) if chosen else None
    if ai_access is None:
        if not chosen:
            raise AccessChoice("missing", None, "Say who may read these documents with AI: cloud (a cloud model such "
                               "as Claude), local (only a local AI on this computer) or none (no AI). This project "
                               "has no default yet, so nothing was added.")
        return {"ai_access": None, "set_default": False, "earlier": 0}
    v = access.clean(ai_access)
    if v == "cloud" and access._local_only():
        raise ValueError("Cloud models are switched off on this computer: documents can be read by a local AI or by "
                         "you only.")
    if chosen:
        if by_ai and access.RANK[v] < access.RANK[dflt]:
            raise AccessChoice("looser", dflt, f"This project's documents are set to \"{access.LABEL[dflt]}\", "
                               f"and \"{access.LABEL[v]}\" would let more AI read the new ones. Nothing was added. "
                               "Add them with that setting or a stricter one; the person can change it for a "
                               "document or for the project in the app's Documents page.")
        return {"ai_access": v, "set_default": False, "earlier": 0}
    earlier = int(ws.scalar("SELECT COUNT(*) FROM documents WHERE ai_access IS NULL") or 0)
    return {"ai_access": v, "set_default": earlier == 0, "earlier": earlier}


def earlier_words(ws: Workspace, n: int) -> str:
    """What to say when `n` earlier documents still follow a default nobody chose (`adding_access`)."""
    from . import access

    if not n:
        return ""
    return (f"{n} earlier document{'s' if n != 1 else ''} of this project still follow{'s' if n == 1 else ''} a "
            f"default nobody chose (\"{access.LABEL[access.default(ws)]}\" until it is chosen). The new documents "
            "have their own setting. Choose the project's default in the app: its Documents page asks.")


def ingest(ws: Workspace, inputs: list[str | Path], exclude: list[str] | None = None,
           progress=None, should_stop=None, ocr: OcrOptions | None = None, ai_access: str | None = None,
           ai_note: str | None = None, workers: int | None = None, set_default: bool = True) -> dict:
    """Add documents. `exclude` holds file-name patterns (e.g. 'A_18_*') to leave out, such as a wrong download.

    `progress(done, total, file_name)` is called before each file is read (for a progress bar). Each document is
    stored in its own transaction; a file that cannot be read is listed under `failed` and the rest go on (0.14.3:
    and so is a zip, or a file in a zip, that cannot be unpacked; Stop is also seen between the pages of OCR).
    `ocr` (default: automatic, English) recognises the text of scanned PDF pages when OCR is installed; scanned
    files that stay without text are listed under `scanned_no_text`.

    0.11: `ai_access` is who may read the new documents with AI (cloud, local, none; None: the project's default);
    a project whose default is not chosen yet takes it as its default. An `ai_access` column in a manifest.csv sets
    it per file (and `ai_note` the reason), which wins over the one answer for all.

    0.16: `workers` files are read at once, each in a process of its own (None: as `read_workers` decides), and stored
    in the order of the files, as reading them one after the other stores them; `read_at_once` in the result says so.
    """
    from fnmatch import fnmatch

    from . import access

    if ai_access is not None:
        ai_access = access.clean(ai_access)
        if ai_access == "cloud" and access._local_only():
            raise ValueError("Cloud models are switched off on this computer: documents can be read by a local AI or "
                             "by you only.")
        if not access.default_chosen(ws) and set_default:  # (hunt phase 1.5: `set_default` False, from
            access.set_default(ws, ai_access)                # `adding_access`: the earlier documents keep theirs)
        if access.default_chosen(ws) and ai_access == access.default(ws):
            ai_access = None  # follows the project's default

    cfg = ws.config["passages"]
    manifest_files: list[Path] = []
    unpack_failed: list[str] = []
    files = discover(inputs, ws.root / "inputs", manifest_files, unpack_failed)
    skipped = [f for f in files if any(fnmatch(f.name, pat) for pat in exclude or [])]
    skip = set(skipped)
    files = [f for f in files if f not in skip]
    declared = read_manifests(manifest_files)
    stats = {"files": len(files), "added": 0, "duplicates": 0, "empty": 0, "passages": 0, "declared": 0}
    if unpack_failed:
        stats["failed"] = list(unpack_failed)
    if exclude:
        stats["excluded"] = [f.name for f in skipped]
    known = {r[0] for r in ws.query("SELECT sha1 FROM documents")}
    # 0.16: read ahead in several processes when the batch is large (`read_workers`), taken here in file order
    readings = _Readings(files, ocr if ocr is not None else OcrOptions(), cfg["max_chars"], cfg["min_chars"],
                         should_stop, read_workers(files) if workers is None else max(1, int(workers)), known)
    added: list[tuple[str, str]] = []
    try:
        _ingest_files(ws, files, readings, known, declared, stats, progress, should_stop, ai_access, ai_note, added)
    finally:
        readings.close()
        if added:
            _log_added(ws, added)
    if readings.parallel and readings.workers > 1:
        stats["read_at_once"] = readings.workers
    if progress:
        progress(len(files), len(files), "")
    return stats


def _log_added(ws: Workspace, added: list[tuple[str, str]]) -> None:
    """0.16: the research log notes the documents added, in one entry per batch."""
    from . import researchlog

    names = "; ".join(researchlog.quoted(t, 80) for _d, t in added[:5]) + (f"; and {len(added) - 5} more"
                                                                           if len(added) > 5 else "")
    with ws.connect() as cx:
        researchlog.record(cx, "documents-added", f"Added {len(added)} document{'s' if len(added) != 1 else ''}: "
                                                  f"{names}.", "document" if len(added) == 1 else "documents",
                           added[0][0] if len(added) == 1 else None, added[0][1] if len(added) == 1 else None,
                           data={"documents": [{"doc_id": d, "title": t} for d, t in added]})


def _ingest_files(ws: Workspace, files: list[Path], readings: _Readings, known: set, declared: dict, stats: dict,
                  progress, should_stop, ai_access: str | None, ai_note: str | None,
                  added: list | None = None) -> None:
    """Each file of the batch, in order: its reading (`readings`), then stored, counted or listed as `ingest` says."""
    from . import access
    from .textutil import clean_doi

    for i, f in enumerate(files):
        if should_stop and should_stop():
            stats["stopped"] = True
            stats["not_added"] = len(files) - i
            break
        if progress:
            progress(i, len(files), f.name)
        got = readings.get(i)
        if got[0] == "stopped":  # 0.14.3: Stop during the text recognition of a scanned PDF: that file is not added
            # hunt phase 1.5: which file was being read (one whose reading never ends is waited for until Stop), and
            # how many were not added, so the page can say so and the person can add them again without that one
            stats.update(stopped=True, stopped_at=f.name, not_added=len(files) - i)
            break
        if got[0] == "failed":  # one unreadable file should not stop the others (0.14.3: whatever it raises: a
            # damaged Word file gave a zip or XML error that stopped the whole add)
            stats.setdefault("failed", []).append(f"{f.name}: {got[1]}")
            continue
        raw = got[1]
        if raw.sha1 in known:
            stats["duplicates"] += 1
            continue
        if got[0] == "unbuilt":
            # hunt phase 1.5: a file read but not made into passages (a fault of the reader) raised here, so one such
            # file stopped the whole add; it is listed as one that could not be read, and the others go on
            stats.setdefault("failed", []).append(f"{f.name}: {UNBUILT} ({_read_problem(got[2])[:200]})")
            continue
        doc = got[2]
        if raw.ocr_pages:
            stats.setdefault("ocr", []).append(f.name)
        if raw.scanned_pages > raw.ocr_pages:
            stats.setdefault("scanned_no_text", []).append(f.name)
        if len(doc.text.strip()) < 100:
            stats["empty"] += 1
            stats.setdefault("empty_files", []).append(f.name)
            continue
        known.add(raw.sha1)
        dec = declared.get(f.name) or declared.get("stem:" + f.stem) or {}
        if dec:
            stats["declared"] += 1
            doc.doi = clean_doi(dec.get("doi")) or doc.doi
            if dec["references"]:
                doc.title = re.sub(r"https?://\S+", "", dec["references"][0]).strip(" ,.")[:250]
        elif declared:
            stats.setdefault("not_in_manifest", []).append(f.name)
        level = ai_access
        if dec.get("ai_access"):
            try:
                level = access.clean(dec["ai_access"])
            except ValueError:
                stats.setdefault("manifest_problems", []).append(f"{f.name}: ai_access {dec['ai_access']!r} is not "
                                                                 "cloud, local or none; the answer for all applies")
            if level == "cloud" and access._local_only():
                level = "local"
        try:
            _store_document(ws, doc, raw, f, dec, level, (dec.get("ai_note") or ai_note or None))
        except sqlite3.IntegrityError:  # the same file, added meanwhile by another ingest
            stats["duplicates"] += 1
            continue
        stats["added"] += 1
        if added is not None:
            added.append((doc.doc_id, doc.title or f.name))
        stats["passages"] += len(doc.passages)
        bad = sum(1 for p in doc.passages if p.section == "unreadable")
        if bad > 0.3 * max(1, len(doc.passages)):
            stats.setdefault("mostly_unreadable", []).append(f.name)


def _store_document(ws: Workspace, doc: "Document", raw: RawDoc, f: Path, dec: dict, ai_access: str | None = None,
                    ai_note: str | None = None) -> None:
    """One document with its pages and passages, in one transaction (other work is not blocked for long)."""
    with ws.connect() as cx:
        cx.execute("INSERT INTO documents(doc_id, path, sha1, title, doi, kind, n_pages, n_chars, text, added_at, "
                   "declared_ref, ocr_pages, scanned_pages, ai_access, ai_note, reader, app_version) "
                   "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (doc.doc_id, str(f), raw.sha1, doc.title, doc.doi, raw.kind,
                    len(doc.page_spans) if raw.paginated else None,
                    len(doc.text), doc.text, now(), json.dumps(dec["references"], ensure_ascii=False) if dec else None,
                    raw.ocr_pages if raw.kind == "pdf" else None, raw.scanned_pages if raw.kind == "pdf" else None,
                    ai_access, (ai_note or "")[:300] or None, READER, __version__))
        # 0.14: the file added again on purpose: a colleague's copy of it may come in again
        cx.execute("DELETE FROM sync_removed WHERE kind='document' AND key=?", (doc.doc_id,))
        try:  # 0.18: a document a colleague keeps out of the shared folder is as strict here as in their copy, at once
            from .sync.folder import hold_settings

            hold_settings(ws, cx, [doc.doc_id])
        except ImportError:  # an app without `sync`
            pass
        store_reading(cx, doc)
        ws.bump_corpus(cx)


def store_reading(cx, doc: "Document", doc_id: str | None = None) -> None:
    """A document's reading: its pages, paragraphs, headings and passages, then (reader 2) its blocks, tables and
    reading report with a person's corrections applied again. `doc_id` stores it under that id (0.15: *Read with the
    new reader* stores a new reading of a document under the id it has, which a sync-clash copy's file does not give)."""
    did = doc_id or doc.doc_id
    if doc.raw.paginated:
        cx.executemany("INSERT INTO pages VALUES (?,?,?,?)", [(did, n + 1, s, e) for n, (s, e) in enumerate(doc.page_spans)])
    lay = doc.layout or Layout([(None, s0) for s0 in doc.paragraphs])
    if lay.paragraphs:
        cx.executemany("INSERT INTO paragraphs(doc_id, n, start, page) VALUES (?,?,?,?)",
                       [(did, n + 1, s0, pg) for n, (pg, s0) in enumerate(lay.paragraphs)])
    if lay.headings:
        cx.executemany("INSERT INTO headings(doc_id, start, end, text) VALUES (?,?,?,?)",
                       [(did, a, b, t) for a, b, t in lay.headings])
    cx.executemany(
        "INSERT INTO passages(passage_id, doc_id, seq, page, start, end, text, section, block) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        [(f"{did}:{p.seq:04d}", did, p.seq, p.page, p.start, p.end, doc.text[p.start:p.end], p.section,
          getattr(p, "block", None)) for p in doc.passages])
    store_blocks(cx, doc, did)


def store_blocks(cx, doc: "Document", doc_id: str | None = None) -> None:
    """0.15: a document's blocks, tables and reading report (reader 2), then a person's earlier corrections of its
    blocks applied again (see reader.apply_choices)."""
    blocks = getattr(doc, "blocks", None)
    if blocks is None:
        return
    from . import reader as reader2

    did = doc_id or doc.doc_id
    rows, tables = [], []
    for b in blocks:
        box = b.bbox
        rows.append((did, b.n, b.page + 1 if doc.raw.paginated else None, b.start, b.end, b.kind,
                     1 if b.included else 0, *(box or (None, None, None, None))))
        if b.kind == "table" and b.rows:
            tables.append((did, len(tables) + 1, b.n, b.page + 1 if doc.raw.paginated else None, b.start, b.end,
                           b.caption, json.dumps(b.rows, ensure_ascii=False)))
    cx.executemany("INSERT INTO blocks(doc_id, n, page, start, end, kind, included, x0, y0, x1, y1) "
                   "VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
    if tables:
        cx.executemany("INSERT INTO doc_tables(doc_id, n, block, page, start, end, caption, rows_json) "
                       "VALUES (?,?,?,?,?,?,?,?)", tables)
    cx.execute("UPDATE documents SET reading_json=? WHERE doc_id=?",
               (json.dumps(getattr(doc, "reading", None) or {}, ensure_ascii=False), did))
    reader2.apply_choices(cx, did)
