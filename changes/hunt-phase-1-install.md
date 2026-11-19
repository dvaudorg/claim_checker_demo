### Changes that can alter your results

- **A check made in a Claude chat is reported at your Strictness.** The connector (`get_check`, `submit_grades`,
  `list_checks`) counted a judgement from 60%, the value in the project's own file, while the app used the Strictness
  you set in Settings. With Strictness at 80% and a grade 70% sure, the app showed *Only uncertain evidence* and Claude
  told you the claim was supported. The connector now reads your Strictness at every call, as the app does, and says
  which value it used (`confidence_threshold`). Can change results: the status Claude reports for a check, when your
  Strictness is not 60% (or a project came from a colleague with another value in its file).
- **The command line counts at your Strictness too.** `enlens check`, `batch`, `history` and `annotate` used the
  project file's value; they now use the Strictness of Settings (`--threshold` still sets another), and the first
  three print the value used. The SDG pack's pipeline (`report`, `evaluate`) keeps the project file's value, as its
  manual says. Can change results: the statuses these commands print.

### Safer

- **The ENLENS icon opens only this data folder's ENLENS.** After ENLENS ended without *Quit* (a crash, a logout or a
  restart), the icon trusted the address it had noted, so when another account's ENLENS (or the one of another data
  folder) had taken that address meanwhile, it opened that one and never started yours. The icon now asks the app
  there to prove it is yours (with your own access token); a note that proves nothing is removed, and ENLENS starts.
  An older ENLENS still running is quit only when it proves the same.
- **Stop ends only this project's Claude Code run.** A run an earlier ENLENS started is recognised by its command
  line, and now by the project named in it: a run of another project that had been given the same process number was
  stopped too, and on a computer without `ps` the number alone was enough to end any program.
- **The Claude app's settings file survives a full disk.** Adding the connector (`enlens-mcp --install-claude-desktop`,
  or the repair at a start after ENLENS moved) wrote `claude_desktop_config.json` in place: a full disk or a stop part
  way left it cut short, and the Claude app lost every connector in it. It is now written beside and put in place
  whole (the `.bak` copy is still kept), keeps every setting ENLENS does not know, and a file that is not valid JSON
  is left as it is, with a message that says so (it was a traceback). A file saved with a byte order mark is read.
- **The Windows command file keeps a data folder whole.** When neither the Shell nor PowerShell could make the ENLENS
  icon, the command file ENLENS.cmd cut a data folder such as `D:\R&D\enlens` at the `&`: the icon started ENLENS on
  an empty `D:\R` and ran the rest as a command. Every part of the line is now quoted for cmd.exe (`%` and `!` too).

### Fixed

- **After an update on Windows, ENLENS started from a terminal is seen coming back.** The update recognised only a
  copy started from the icon, so about 90 seconds after a terminal-started ENLENS had come back, a PowerShell window
  said it had not and installed ENLENS again over it. Every copy is now recognised by its own access token.
- **"The Claude Code plugin now uses this installation" only when it does.** After an install or update, the line
  was printed (and the app's log said "brought up to date") although Claude Code had refused the new plugin and kept
  the old one; nothing tried again. It now says that Claude Code refused, with its answer, and ENLENS tries again at
  its next start (*Set up Claude* or `enlens claude-setup` try at once). `enlens claude-setup` ends with an error
  when Claude Code refuses.
- **The command line says when something failed.** `enlens ingest` with a path that does not exist printed
  `{"files": 0, …}` and ended as a success; it now names the path and adds nothing. `measure --folder` / `--ws` with
  a missing folder, `annotate` and `resolve` with an unknown document, and refusals such as an unknown kind of task
  for `queue first` ended in a traceback or as a success; they now end with a message and an error code.
- **An add-on's column is added once.** A column name ending in a line break, or written in other capitals than the
  table's own (`AI_Note` beside `ai_note`), made every later opening of a project fail with "duplicate column name";
  the first is refused with a message that names the add-on, the second is recognised as the same column.
