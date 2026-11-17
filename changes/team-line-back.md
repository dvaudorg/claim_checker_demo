### Changed

- **Team is back under the project's name.** The sidebar's *Team* entry in the *Project* group is gone again: as
  before 0.19.7, a small line joined under the project switch says *Team* and, in a project with a team, its state
  (*synced 15:44*, *3 new*, *syncing now…*, *offline*). It works as the entry did: it is always there while a project
  is open, it opens the Team page (the set-up without a team; *Activity* and *People and settings* with one), and it
  turns soft teal while you are on that page. Nothing opens in the right-hand panel, which stays the research log's.

### For developers

- `lib.js` `teamLine({ id })` takes the place of `teamEntry()`; `views/team-entry.js` is now `views/team-line.js`
  (`initTeamLine()`). `index.html` keeps the plain line inside `#project-switch`, and `renderProjectSwitch()` keeps it
  across redraws and hides it while no project is open. The router marks it current like an entry (`setNav`).
  docs/DESIGN.md 5.1 and the design reference page show it under the project switch.
