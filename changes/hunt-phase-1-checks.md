### Changes that can alter your results

- **A judgement you made by hand survives changing your mind twice.** After *Judge it myself*, a judgement, *Let the
  local model read them* and *Judge it myself* again, the excerpt lost your judgement and no longer counted in the
  answer. It now keeps it. If you went back and forth like this before, look at those excerpts once and judge again
  any that shows no judgement of yours. Can change results.
- **Documents added since a check whose reading did not work can be read again.** When the AI's answers for them
  could not be used (three tries), *Read it* marked them as looked at: they left the card, the answer did not say it
  was incomplete, and they could never be read for that check. Now nothing of such a reading is kept, the page says
  that the reading did not work, and the documents stay listed for *Read it* again. *Read these* (documents with the
  search words never read) does the same. Can change results, once the documents are read.
- **A removed check no longer counts in "how often you agreed".** Removing a check (or every document) left every
  person's judgements of its excerpts behind, and the agreement with a colleague still counted them. Can change the
  agreement figures; judgements of checks removed before this version still count there.

### Fixed

- **The connector's `get_check` answers for the whole hypothesis that `list_checks` lists.** For a hypothesis the
  app checked in parts, `list_checks` gave the combined answer (say, *contradicted*) and `get_check` with the same id
  answered for the first part alone (*supported*, with that part's evidence only). It now gives the combined answer,
  each part with its own answer, and every part's evidence. A check made in a chat is answered as before.
- **A Claude chat whose grades were refused once is *Not finished yet*, not *The check did not work*.** The chat
  still had two tries to fix them; the app, the Results list and `get_check` said the check had failed.
- **The Results list counts documents added since a check as the result page does.** A theory or working document
  added after a check showed as *1 document added since* in the list, and *Read the new documents* picked that
  hypothesis, while the result page and the Excel summary said none.
- **"Changed by you" in the Results list matches the result page and Excel.** Judging an excerpt the small local
  model only pointed at (it judged nothing) counted as a change of an AI judgement in the list only.
- **The review spreadsheet is read back when Excel saved it with semicolons.** Excel in most European languages puts
  ";" between cells; `review-import` then applied no decision and reported every row as skipped.
- ***Check several* reads a spreadsheet with the one column `hypothesis`.** The word "hypothesis" became a
  hypothesis to check, and a hypothesis with a comma kept the spreadsheet's quotes.
