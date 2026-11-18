### Changes that can alter your results

- **A project's settings survive a crash while one of them is saved.** The project's settings file (`config.json`)
  was written in place, so if the app was quit, the computer went off or the disk was full during a save (who may
  read new documents with AI, the banner, a shared folder, a project brought in), the file could be left empty. The
  next save then kept only its own change: the project's strictness, AI default, models and shared folder went back
  to ENLENS's defaults, which can change results. The file is now written whole or not at all. A settings file that
  cannot be read is no longer written over: ENLENS says so in words, and you can put back a copy from a backup or
  move the file out of the project folder to start from ENLENS's own settings.
- **Opening a project from an earlier version finishes its one-time update even when the first opening was cut
  off.** If ENLENS was quit or the computer stopped while it first opened a project from before 0.18 that you had
  exchanged with a colleague, the project counted as never sent from then on: every check, note and codebook was
  private, and the colleague got none of them. A project from before 0.11 likewise lost its record of what Claude
  had read before (the AI log, and the share of a document Claude may read). The next opening now does the update.
  A project already caught this way cannot be told apart from one that was never exchanged: if your colleague stopped
  getting your work after you updated to 0.18, share those items again (*Shared with your team* under a check's or
  codebook's title, *Share* in a note's card).

### Safer

- **A damaged list of linked projects is set aside, not written over.** If `links.json` in ENLENS's data folder was
  cut short (a power cut, a sync or backup tool), linking, making or removing one project saved a list with that
  one alone, and every other linked project was dropped for good. ENLENS now keeps the damaged file as
  `links.json.damaged`, says so, and starts a new list when you try again. The projects themselves were never
  touched. The list of quick looks and the model test's speeds are set aside the same way.

### Fixed

- **A project made with the name of a quick look you deleted outside ENLENS is no longer moved to the trash.** A
  quick look whose folder you removed in the Finder or Explorer stayed on the list of quick looks for its week; a
  project you made, linked or brought in under that name in that week went to the trash in its place. If a project
  went missing this way, it is in the `trash` folder of ENLENS's data folder.
- **A BibTeX DOI with an escaped underscore is read as the DOI.** `10.1016/j.wat\_res…` (and Mendeley's
  `{\_}`) kept the backslash: the work was not linked to its document by DOI, and Retractions looked up a DOI that
  does not exist and showed the work as checked with no notice. Bring the BibTeX file in again (*Use an exported
  file instead*) to correct such works. A DOI in the note field and links in the url field are read the same way.
- **A colleague's version of a codebook kept beside yours** is written whole: a cut-off write could leave its codes'
  ids, groups and history empty.
