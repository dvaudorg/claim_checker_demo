"""Reader 8: PDFs whose columns do not share their baselines.

`reader.read_blocks(raw, version=8)` calls the rule here; `version=7` and below still read exactly as before. Text
files, Word files and web pages read as by reader 7. No model is used. One thing changes:

1. **Two columns whose lines stand at other heights** (`beside`, in `reader._gutters`). Readers 2 to 7 split a page
   into columns where lines of prose stand on both sides of a vertical gap at the same height, and took "the same
   height" to be the same baseline, give or take about four points. Where the two columns' lines fall between each
   other, as on a book's two facing pages printed side by side on one PDF page (a thesis's "spread", one page's lines
   half a line lower than the other's), or two columns set in other leadings, no line had a partner, no gap was found,
   and the page was read line by line across both columns: each sentence of one column interleaved with the other's.
   Reader 8 also takes two lines to stand side by side when their boxes overlap in height (by at least a point). A
   gap must still have lines of prose beside each other on both sides and few lines crossing it, so a page in one
   column (whose lines cross the middle) and a title or an abstract over two columns read as before.
"""
from __future__ import annotations

import math


def _rows(ln) -> range:
    """The whole points of the page's height that a line's box covers, inside its edges."""
    bottom = ln.bottom if ln.bottom is not None else ln.top + (ln.size or 10.0)
    return range(math.floor(ln.top) + 1, math.ceil(bottom))


def covered(lines) -> set[int]:
    """Every whole point of the page's height a box of `lines` covers (`_rows`)."""
    out: set[int] = set()
    for ln in lines:
        out.update(_rows(ln))
    return out


def beside(ln, cover: set[int]) -> bool:
    """Whether a line's box overlaps in height the boxes whose points are `cover` (`covered`)."""
    return any(y in cover for y in _rows(ln))
