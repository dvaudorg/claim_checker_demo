### Safer

- **A button pressed twice starts its work once, also from two tabs.** Labelling passages, finding themes, naming the
  themes, naming the groups of the concept map, reading one excerpt again and reading documents with the new reader
  now give the work already under way back to a second press; other work of the same kind that would clash with it
  (the same codebook labelled with other choices, other themes, the same excerpt with another note, a document
  already being read) is refused with a sentence saying to wait for it. Installing Claude Code, downloading a model
  and answering a move zip's question were likewise started twice by two presses at the same moment.
- **Removing a project waits a moment for a round of the shared folder.** A round the app started by itself cannot
  be stopped by you, so *Remove* (and a quick look's *Discard now*) waits a few seconds for it to end; if it is still
  running, it says the project is being brought up to date with your team and to try again in a moment. For work you
  can stop, it says which work and to stop it in the sidebar, as before.
- **A request whose body stops coming no longer holds the app.** A connection waits two minutes at most for a
  client, and a body sent in chunks, without its length, is refused in words instead of being stored as an empty
  file.

### Privacy

- **A quick look's document is for a local AI only.** Nobody is asked who may read the one document of a quick look,
  so no cloud AI may: it is marked *Only a local AI*, and the Claude connector cannot read its text. Keep it as a
  project and ENLENS asks who may read it, as for a new project.
- **Documents are never added for Claude without anyone choosing.** A request to add documents (or the
  bibliography's files) to a project whose AI setting was never chosen, without saying who may read them, took
  *Claude may read it*; it now adds nothing and says to choose. The Documents page always asked first, so adding
  documents there is unchanged. When earlier documents follow a setting nobody chose, the answer is the new
  documents' own, and the result says how many still follow it.
- **Notifications name no document marked *Only a local AI* or *No AI*.** A notification shows on the lock screen,
  and its text could hold such a document's title (reading it with the new reader, drafting its concepts), a person
  named in it (following references) or its file name (in a problem's message, or as the name of a quick look). It
  now says "a document" (or "a quick look") instead. A hypothesis's text is still shown.

### Fixed

- **A hypothesis removed while its check waited says so.** The check ended with the hypothesis's bare id as its
  problem.
- **Downloaded file names stay whole.** A hypothesis exported from a colleague's copy, whose id holds a quote, or a
  name ending in a backslash, lost its name in some browsers.
- **A second computer is not named "['Anna']".** *Use both computers* took a name sent as a list (or a number) as
  the name; such a request is now refused in words.
