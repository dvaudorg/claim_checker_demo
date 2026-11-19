### Changes that can alter your results

- **A decision about a work in the bibliography follows only that work.** When the bibliography is brought in again
  from another source (a BibTeX file in place of Zotero, say), a work whose key changed keeps what you confirmed or
  rejected about it, found by its title and year. Two works of the same title and year (the annual reports of two
  bodies) both took the decisions of either, so a document could be confirmed as the other body's report. The first
  author's name now counts too, and a decision that still names more than one work is not carried over: that work is
  matched again for you to decide.
- **Retractions looked up by title no longer stumble on a reply.** A reply or comment titled after the work ("Reply
  to: …", "Comment on …") by the same authors counted as the work itself for long titles, so the work had two matches
  and was looked up by neither. Such a record is no longer taken for the work.

### Safer

- **A project saved by a newer ENLENS is not opened.** An older ENLENS opened a project a newer one had changed (a
  folder you share, or going back from an early version) and wrote to it. From now on a project says which ENLENS it
  needs; one that needs a newer version is shown on the Projects page as *cannot be opened*, with what to do (update
  ENLENS), and nothing in it is changed. Projects made so far open as before.
- **A project's settings are changed by one program at a time.** The app, Claude Code's connection to ENLENS and the
  command line could each change a project's settings at the same moment, and one change was then lost. They now
  take turns.
- **A codebook uploaded again is written whole**, as its other files are: a save cut off by a crash or a full disk
  could leave the codebook empty and unreadable. A colleague's version of a codebook whose details file arrived
  damaged is kept as it came rather than written over.

### Fixed

- **The Projects page says why a project cannot be opened.** A project whose settings file (`config.json`) is damaged
  was listed as if all was well, and every page of it then failed. It is now marked *cannot be opened*, with what to
  do: put back a copy from a backup, or move `config.json` out of the folder to start again from ENLENS's own
  settings. ENLENS still never writes over the damaged file.
- **The highlighted PDF of a document marked Non-scientific says that its judgements are not counted** (unless the
  hypothesis counts such documents), as the evidence map does.
- **A label that a colleague's newer ENLENS made no longer stops the codes pages or the FlexiConc file.** A label of a
  kind this version does not know made them fail; it now ranks after the kinds it knows.
- **An evaluation copy is no longer made under the name of a linked project, or trashed as a vanished quick look of
  the same name.**
- **A Zotero library or key that ends in a line break is refused** before Zotero is asked.
- **Removing a project whose folder was replaced** closes ENLENS's connections to the old database first, so Windows
  does not say the folder is still in use.
