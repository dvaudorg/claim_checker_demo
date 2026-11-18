### Safer

- **A project is not removed while work of it runs.** Removing a project while documents were being added to it, and
  then making a new project of the same name, put the old project's remaining documents into the new one. *Remove*
  (and a quick look's *Discard now*) now says which work is still running or waiting in that project and asks you to
  stop it in the sidebar or wait until it has finished. A quick look whose week is up also stays until its work has
  ended. Cannot change results.
- **"Read the new documents" pressed twice reads them once.** With Claude Code answering (or while the local model
  waited for its Start), a second press started a second job that ended in an error meant for Claude Code's chat
  ("Grade the passages already shown first"), and two presses at the same moment could read the same documents
  twice. A second press now follows the job already at it.

### Fixed

- **Two files of the same name added in one go are both added.** Two different files called `report.txt` (chosen in
  two folders) became one document, and the summary counted one. The second now gets a name of its own
  (`report (2).txt`), as it does when the names differ only by capital letters or accents, or by a `:`, `?` or `*`
  that cannot be in a file name. A file called like a Windows device (`CON.txt`) gets a `_` in front, and a name too
  long for the disk is shortened. Can change results: documents that were missing are added.
- **Stop pressed just after work has finished no longer marks it as stopped.** A finished result (a drafted code
  definition, for example) was then put aside as if you had stopped it.
- **Odd requests are answered in words.** A number such as `1e400` in the page's address (`?offset=1e400`), a value of
  the wrong kind sent by a script, a path too long for any disk, or a token with an accented letter got "Unexpected
  problem" from the app; it now says what was wrong (or, for the token, how to open ENLENS).
