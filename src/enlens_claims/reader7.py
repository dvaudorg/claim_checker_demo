"""Reader 7: text files, Word files and web pages read otherwise than by reader 6.

`reader.read_blocks(raw, version=7)` calls the rules here; `version=6` and below still read exactly as before. PDFs
read as by reader 6. No model is used. Five things change (found by the bug hunts of November 2026):

1. **A line that comes back in text whose every line is a paragraph** (`lone_lines`, in `reader3.text_furniture`).
   Reader 3 takes a line that comes back about once a page for a running head when it stands next to a page break or
   a blank line most times. In an interview typed with a blank line between turns (or a Word file, or a web page,
   whose paragraphs are each one line) every line stands next to a blank line, so the test meant nothing, and the
   interviewer's question asked five times was set aside as a running head, out of the passages that searches,
   codes, themes and checks read. Where a blank line stands between nearly every two lines, a blank line is no
   longer a sign of a page edge: such a line is a running head only when it stands at a page break most times, or
   when the text runs on across it at least once (the line before it does not end a sentence, the line after it
   starts in lower case), as a running head between two pages does in the middle of a sentence
   (`runs_across`). Text whose paragraphs run over several lines, with blank lines between them (most text copied
   out of a PDF), reads as before.
2. **A text file whose lines are short sentences, one per line** (`paragraph_lines`). Reader 4 takes each line of a
   text file without blank lines as a paragraph only when long lines (over 160 characters) hold most of its text, so
   Word's "plain text" of short paragraphs (survey answers, notes) was one paragraph, every quote cited as paragraph
   1. Reader 7 also takes each line as a paragraph when the file has (nearly) no blank lines, and nearly every line
   that runs straight on into the next ends a sentence and the next starts with a capital, whatever the line length;
   in text hard-wrapped to one width few lines end a sentence, and text written one sentence per line with blank
   lines between its paragraphs has its paragraphs, so both read as before.
3. **A Word file's text box** (`ingest._read_docx`): read once, as paragraphs of its own after the paragraph that
   holds it. Word keeps a text box twice (the shape and an older copy of it); readers 1 to 6 read both, joined to the
   holding paragraph's last word.
4. **A text file or web page saved as ISO-8859-2** (Latin-2; `ingest.decode_text`): Polish, Czech and Slovak letters
   (ą, ś, ź, š, ž, ť, ľ) came out as other characters (±, ¶, Ľ), as Windows-1250 puts them elsewhere. Latin-2 is taken
   when no byte rules it out and it fits one language strictly better ("µ" not counted as a letter), or the Windows
   reading shows signs inside words (`ingest._latin2`); Windows-1250 and -1252 files read as before.
5. **A text file or web page saved as UTF-16 without a byte-order mark** (hunt phase 1.5; `ingest._utf16_without_bom`):
   read as UTF-8 by readers 1 to 6, with a NUL between letters, so its words could not be searched or quoted.
"""
from __future__ import annotations

from .reader3 import _ENDS_SENTENCE, _STARTS_UPPER

# a blank line stands between at least this share of the lines that follow another on their page
LONE_SHARE = 0.8
# at least this many lines run straight on into the next, and at least this share of them end a sentence before a
# capital, for a text file to be one paragraph per line by rule 2
SENTENCE_LINES_MIN = 8
SENTENCE_SHARE = 0.9
# ... and at most this share of the lines that follow another on their page have a blank line before them
BLANK_SHARE_MAX = 0.05


def lone_lines(seq) -> bool:
    """Whether a blank line stands between nearly every two lines of `seq` (lines without positions, in order): each
    line is a paragraph of its own, so a blank line beside a line says nothing of a page edge."""
    after = [b for a, b in zip(seq, seq[1:]) if a.page == b.page]
    return len(after) >= 20 and sum(1 for b in after if b.blank_before) >= LONE_SHARE * len(after)


def runs_across(seq, idx: list[int], marked: set[int]) -> bool:
    """Whether the text runs on across one of the lines `idx` of `seq` at least once: the nearest line before it
    (lines already set aside skipped) does not end a sentence, and the nearest line after it starts in lower case."""
    n = len(seq)
    for i in idx:
        j = i - 1
        while j >= 0 and (j in marked or seq[j].furniture):
            j -= 1
        k = i + 1
        while k < n and (k in marked or seq[k].furniture or k in idx):
            k += 1
        if j >= 0 and k < n and not _ENDS_SENTENCE.search(seq[j].text.strip()) and seq[k].text.strip()[:1].islower():
            return True
    return False


def paragraph_lines(pages) -> bool:
    """Reader 4's rule (`reader4.paragraph_lines`), or rule 2: in a text file whose lines nearly all end a sentence
    and are followed by a capital, every line starts a paragraph (`Line.blank_before`). Returns whether it is one."""
    from . import reader4

    if reader4.paragraph_lines(pages):
        return True
    every = [(a, b) for p in pages for a, b in zip(p, p[1:])
             if a.top is None and b.top is None and not a.furniture and not b.furniture
             and a.text.strip() and b.text.strip()]
    # (after review) only in a file without blank lines between its paragraphs: text written one sentence per line
    # with a blank line between paragraphs (Markdown so written, corpora stored a sentence a line) has its paragraphs
    # already, and making each of its lines one lost them
    if sum(1 for _a, b in every if b.blank_before) > BLANK_SHARE_MAX * len(every):
        return False
    pairs = [(a.text.strip(), b.text.strip()) for a, b in every if not b.blank_before]
    if len(pairs) < SENTENCE_LINES_MIN:
        return False
    ends = sum(1 for a, b in pairs if _ENDS_SENTENCE.search(a) and _STARTS_UPPER.match(b))
    if ends < SENTENCE_SHARE * len(pairs):
        return False
    for p in pages:
        for ln in p:
            if ln.top is None and not ln.furniture and ln.text.strip():
                ln.blank_before = True
    return True
