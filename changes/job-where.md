### Fixed

- **The sidebar no longer says "Claude" for work that runs on this computer.** While ENLENS checked where your results
  would go before a new reading, the work box in the sidebar showed Claude's cloud icon, though nothing was sent to
  Anthropic. It now says *This computer*, as it does for the reading itself. The same was wrong for adding documents,
  the glossary, themes, codes by keywords, trying a codebook, bringing in the bibliography and work done by your local
  model. *Check for retractions* now says *Crossref*, where only the DOIs go, and installs and downloads show neither.
  Does not change results.

### For developers

- A job's view carries `where` (`here`, `crossref`, `none`, or `null` for the AI of Settings), from `WHERE_OF_KIND` and
  `job_where()` in `gui/api_common.py`; the sidebar follows it instead of its own list of kinds. A new job that never
  sends text to the AI should be named there.
