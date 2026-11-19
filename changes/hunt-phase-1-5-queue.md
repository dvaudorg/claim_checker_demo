### Safer

- **Hold keeps a kind of task back from everyone.** A Claude Code helper started before you pressed *Hold* went on
  asking for its kind by name and was handed it all the same. A kind on Hold is now handed to no helper, read by
  your local model neither as its share of the AI mix nor by *Answer them here instead*, shown as about to be sent
  by none of *See what is sent*, written to no file by `enlens export-tasks` and asked of no model by `enlens run` or
  `enlens queue run` until you press *Go on*; a page that waits on such a task says it is on Hold.
- **A task given a new text while a helper held it is taken from that helper.** The helper had been given the old
  text, and its answer was checked against the new one: its quotes were refused and its attempts used up. The task
  is handed out again with its new text.
- **An answer from the file queue no longer lands beside a helper's.** `enlens import-results` stored a late file
  answer for a task put back with `enlens requeue` that a Claude Code helper was answering, whose answer was then
  refused; it is now left to the helper, and the command says how many it did not store and to import the file
  again if the helper gives them back. `enlens refresh` leaves tasks still out in
  the file queue as they are, so their answers are recorded under the instructions written beside their files.

### Privacy

- **"Name the groups again" no longer sends an earlier name made from documents the AI may not read now.** The name
  the AI drafted before goes with the request ("give another"), and it holds words of the documents it was drafted
  from: it now goes only when the AI may still read every one of them, and a document made stricter while the request
  waits takes the request out of Claude Code's queue. A colleague's draft name, whose documents this copy cannot
  tell, is not sent.
- **A concept named after an abbreviation goes to the AI only when all its wordings may.** Such a concept is named
  "long form (SHORT)", none of its wordings, and *Name the groups* judged the name by one wording alone: the long form,
  written only in documents marked *No AI*, could be sent.

### Fixed

- **An add-on's kind of task is handed each quote as the passage writes it.** The quote check reads "10³ tonnes" and
  "103 tonnes" alike; ENLENS's own kinds always kept the passage's own words, an add-on's store function was handed
  the model's, a different number.
- **Reading further while a round waits to be judged says what to do.** *Read the new documents* and *Read more
  passages* on a check whose excerpts still wait to be judged ended in words meant for a Claude chat ("Grade the
  passages already shown first (submit_grades)"); they now say to read further once the excerpts are judged.
- **Answering the queue here with a local model counts each second reading once.** A task waiting for the stronger
  model was counted as answered before any model read it, and again when it was read after the run.
