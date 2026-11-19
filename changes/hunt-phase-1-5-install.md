### Changes that can alter your results

- **Adding documents from a Claude chat or the command line asks who may read them with AI.** The app asks when you
  add documents, with nothing preselected; the connector (`create_project`, `add_sources`) and `enlens ingest` took
  *Claude may read it* when nobody said. Now, until a project's default is chosen, they add nothing without an answer
  and say how to give one: Claude asks you and passes `ai_access` (cloud, local or none), and `enlens ingest` takes
  `--ai-access cloud|local|none`. This holds for every project whose default was never chosen, which includes every
  project made with `enlens ingest` or the connector so far: scripts that add documents to one need `--ai-access`
  now. On a project without documents, the first answer becomes its default; on one whose earlier documents follow a
  default nobody chose, the answer is only the new documents' own, the earlier ones stay as they were, and you are
  told how many there are, so you can choose the default in the app. Once a default is chosen, it applies.
- **Claude cannot open documents wider than you chose.** Through the connector, a setting looser than the project's
  default (*Claude may read it* where you chose *Only a local AI* or *No AI*) is refused in words; the same or a
  stricter one is taken. You can still open a document or the project wider yourself, in the Documents page (or with
  `enlens ingest --ai-access`). Linking a folder made with the command line (`use_folder_as_project`) asks who may
  read its documents first.

### Safer

- **A broken add-on no longer stops every project from opening.** An add-on whose tables could not be set up (a
  mistake in its `SCHEMA`, `INDEXES` or `MIGRATIONS`) made every project fail to open, with a database error that did
  not name the add-on. That add-on is now left out of the project where it failed (what it set up there is taken
  back): the project opens, the add-on's pages there say in words that it is left out, its other projects are not
  affected, and the failure is part of what the app's page reads (`addon_problems`), with the add-on, the project and
  why. An add-on whose SQL manages its own transaction (`BEGIN`, `COMMIT`, `VACUUM`, `PRAGMA journal_mode`) is
  refused, naming the statement: such statements ran before and now cannot.
- **Claude Code installed with npm gets the plugin folder whole on Windows.** Windows runs npm's `claude.cmd` through
  cmd.exe, which read a data folder such as `D:\R&D\enlens` as two commands at the `&`, and a folder name holding
  `%PATH%` as that variable. Every part of the line is now quoted for cmd.exe, for *Set up Claude*, the plugin's repair
  and *Start Claude Code*.
- **The install line works for a Windows user name with brackets.** With a user folder such as `C:\Users\Anna [Lab]`
  (so the temporary folder too), the install stopped at "Cannot find path": PowerShell read the brackets as a pattern.
  Every path in the install script is now taken as written.
- **The icon does not start a second ENLENS beside a busy or starting one.** When the running ENLENS was too busy to
  answer in a second and a half, or was still starting, the icon took its note for a stale one, removed it and
  started a second copy of the same data folder. The note is now removed only when the ENLENS it names has ended;
  while it runs, the icon opens it.
- **A Claude Code run left going is recognised on a computer without `ps`.** On such a computer (a small Linux) a run
  an earlier ENLENS started was forgotten and went on unseen; its command line is now read from `/proc`.
- **Stable updates never offer a release candidate.** A candidate published by mistake as a full release (it happened
  once) was offered on the stable channel; stable now takes the newest full release.

### Privacy

- **A check started from a document is hidden from the AI that may not read that document.** The connector kept such
  a check out of a Claude chat when Claude may not read the document; started for Codex or Antigravity, it asked about
  Claude too. It now asks about the AI the connector answers.

### Fixed

- **On Windows, an update no longer rewrites the Claude Code plugin at the first start after it.** The installer
  names `python.exe`, the app from its icon `pythonw.exe`; each found the other's plugin out of date, so every update
  was followed by a second rewrite and four `claude plugin` commands. The plugin and the Claude app's entry now name
  `python.exe` (the connector talks through its console streams), and both count as this ENLENS.
- **When Claude Code keeps refusing the plugin, ENLENS asks it once a day.** Every start rewrote the plugin and ran up
  to four `claude plugin` commands, two minutes each at most, in the background. ENLENS now waits a day, unless ENLENS
  or Claude Code was updated meanwhile; the installer, *Set up Claude* and `enlens claude-setup` still try at once. An
  answer that the marketplace is already there counts only when Claude Code has it from this data folder; one it
  has from another folder (the data folder moved) is registered again from this one.
- **The command line gives clearer answers.** `enlens --ws Pilot …` with the name of an app's project said to run
  `init`, which would make an empty project in the current folder; it now names the project's folder.
  `enlens --ws P measure` measures P (it was ignored). `enlens prepare` for a copied project folder whose name the data
  folder already uses queued its tasks and then stopped with a traceback; it now says why and queues nothing.
  `reset-corpus` names everything it deletes (hypotheses with their judgements, labels, themes and concepts too).
- **A data folder with `%` in its name keeps it in the Linux menu entry.** The `.desktop` file's command line read
  `%` as one of its own codes.
- **A connector project is no longer left empty on an installation without cloud models.** Asking to add documents
  as *Claude may read it* there made the project and then refused the documents; it is refused before anything is
  made.
