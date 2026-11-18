### Changes that can alter your results

- **The codebook you choose on the Codes page is the one the AI uses.** *Let the AI read the passages* kept the first
  codebook after you chose another, so Start labelled the passages with the earlier one. If you switched codebooks
  on that page and then started the AI, look at which codebook those labels went to. Changing the codebook while the
  AI is labelling no longer hides the run either.
- **A second change of strictness is no longer lost.** Two quick changes (two presses of an arrow key on the slider,
  or *Back to normal* during a save) stored the first value while the slider showed the second. Results were then
  counted at the stored value. Look at Settings → Basics once to see that it shows the strictness you mean.

### Safer

- **A file brought in by hand can no longer change your own notes or research-log entries by naming your other
  account as its sender.** Only your private sync between your own accounts may do that.
- **A Word file with a document type declaration is refused.** Such a file of a few hundred bytes could grow to
  gigabytes of text while it was read. Word never writes one, so your documents read as before.

### Fixed

- **Moving a team to Cloudflare R2 with a token that reaches several accounts.** The move said it was done without
  moving anything, listed every colleague twice (which dropped them from the team), and after an error could remove
  the owner's keys for the storage space. It now asks which account to use and moves there. A first set-up at R2
  with such a token failed before it could ask; it asks now.
- **A hypothesis the AI could not split is checked as written.** The check used to fail and the hypothesis was
  removed.
- **Look before checking** drops its parts when you changed the hypothesis or an option while the AI was looking,
  and says so. It used to show the parts of the old wording and then check without them.
- **Add my label** on a document offers the codes of the codebook you chose, also after you change it, and asks
  again when the codes could not be loaded.
- **Choose a code…** says when the codebook cannot be loaded; it used to do nothing.
- **The research log** adds an entry once when Ctrl+Enter is pressed twice, and keeps what you typed while an entry
  was being saved. The same holds for a code's examples and the reason for a codebook change.
- **A theory draft that changed elsewhere** is saved again with the new version, not once more with the old one.
- **Plain messages in place of errors:** *Try again* for a drive on a project with no storage space, a new codebook
  as a copy with no codebook named, and a profile asked for with an empty codebook name. The storage space set-up
  asks for its help links again after a failed try.

### Reading

- **Reader 6 needs pdfminer.six 20250506 or newer, and ENLENS now asks for it.** With an older one its rule for text
  a form crops away could not run, and PDFs were read without it and without a word. A normal install already has a
  newer one.

### For developers

- Model evaluation: a link pair no AI may read is no longer counted as a task (`evaluation.prepare`).
- The first tool sweep of the bug hunt (ruff's bug rules, pyright, semgrep, eslint, `tsc --checkJs`, coverage): 21
  faults, each fixed with a test that failed first.

### Tests

- `tests/test_views_stale_state.py`: views whose state went stale after a select changed or while a request ran.
