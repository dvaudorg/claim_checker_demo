### Settings

- **Settings has a tab for everyday things: General.** Notifications, updates (your version, *Check for updates*,
  *What's new*, which new versions to offer, *Quit ENLENS*), your data (the data folder, your projects, the list of
  what was sent to Claude) and help (*Copy technical details*, *Report a problem*) moved there from *Checking* and
  *Technical*. *Exploring* joined *Documents*. Old links to a section still open it.
- **Every change saves as you make it, and the page says so once.** The Save buttons and the "Saved as soon as you
  change something" lines are gone: a choice saves when you make it, a field when you leave it, and the right end of
  the tabs says *Saving…*, then *Saved*.
- **Shorter help.** Each setting has at most one short line under it; the longer explanation is behind the (?) beside
  its label.
- **Technical is a list of what is set.** Each card is one line, its name and its current value (*Seed 42*, *The
  recommended models*), until you open it; *AI model per task* is a table again on a computer screen, and search by
  meaning's server and model have their own card there, while *Documents* keeps its on/off switch and the download.
  Nothing about how checks run changes.
- **Which new versions to offer** is now *Stable* or *Early*.

### For developers

- `field()`, `switchControl()` and `rangeControl()` take `about: [title, text]`: a help mark beside the label
  (`.setting-head`). A table of a few short columns can be `.table-responsive-sm` (stacks under 600 px of its frame).
