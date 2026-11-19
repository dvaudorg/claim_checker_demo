### Changes that can alter your results

- **Judgements of checks removed by an earlier version stop counting in "how often you agreed".** Removing a check
  used to leave every person's judgements of its excerpts behind; the agreement with a colleague still counted
  them. When a project opens, judgements of checks that no longer exist are now removed. Can change the agreement
  figures.
- **A judgement lost by pressing *Judge it myself* twice comes back.** An earlier version wrote the excerpt again
  without your judgement, though ENLENS still had it. When a project opens, such an excerpt gets its judgement back,
  and it counts in the answer again. Can change results.
- **The excerpts of a round whose AI answers failed can be judged.** The result says that such an excerpt counts
  once you judge it yourself, and that the excerpts the local model could not read can be judged by you, but saving
  the judgement was refused. It is saved now, and counts. Can change results, once you judge them.
- **A document added since a check is read for every part.** When *Read it* failed for one part of a hypothesis
  while you judged an excerpt of another part, that part's reading was kept, and the document then no longer counted
  as added since: the part whose reading failed never got it. It now stays listed until every part has read it. The
  same holds when *Read more excerpts* on one part read a new document: *Read it* still reads it for the others.

### Fixed

- **A check left half-done can be finished from its result.** When the app was closed while it was checking, or a
  Claude chat stopped answering after its grades were refused (or never sent any), the check said *The check did
  not work* or *Not finished yet* for good, and *Read more excerpts* refused to start ("still has excerpts waiting to
  be judged"). After 30 minutes without an answer such a reading has ended: the check says it did not work, and
  *Read more excerpts* reads its excerpts again in the app. What you judged in it stays.
- **"N of M hypotheses brought up to date" counts only those brought up to date.** After *Read the new documents*
  for several hypotheses, one whose reading did not work was counted among them as well as in "1 could not be read".
- **A colleague's sentence is no longer called yours.** Where a colleague's judgement counts on an excerpt and they
  chose its sentence, the result and Excel's *Quote chosen by* said it was yours. They now name the colleague.
- **Check several reads ENLENS's own spreadsheet back as written.** A hypothesis starting with "+", "-", "=" or "@"
  came back with the apostrophe ENLENS puts before such a cell so that a spreadsheet does not run it as a formula.
- **An unfinished *Look before checking* is not offered as an earlier check.** A look stopped half-way could show up
  as "checked before" beside a hypothesis close to it.
- **Claude's report of a check counts a kept document's grades as the app does.** For a document you keep on this
  computer, Claude was told every grade as counting in the answer, those below your strictness too; these are now
  given apart (`not_counted`).
