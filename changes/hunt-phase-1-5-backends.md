### Changes that can alter your results

- **The validation report never counts a passage without an answer as a right code decision.** A passage the model
  left unanswered was read as "no code", so it was right for every code the gold set does not give it, as an
  unfinished check never is. Its decisions now count as "no answer"; a model that fails passages scores lower, and
  repeatability no longer counts an unanswered passage as agreeing with an empty one.
- **An acceptance theme sheet written before the model answered is not scored.** A `g6_theme_names_<model>.csv`
  written by an earlier version before the model had named its themes holds the reference project's own names; your
  "fitting" for those was scored as the model's. Only rows holding the model's own name count, and `acceptance score`
  says when a sheet holds other names (move it away and score again: it is written anew).

### Safer

- **Codex or Antigravity installed with npm on Windows gets the helper's instructions whole.** npm installs them as
  `.cmd` files, which Windows runs through its command line: it cut the instructions at the first line break, and a
  project named with `&` could run a command. ENLENS now starts the program the `.cmd` file starts (a real `node.exe`,
  never a `node.cmd` a version manager put first); a command file of another kind is refused at *Start*, with a line
  saying to use the maker's installer. Where both are on the computer, the maker's program is used.
- **The Antigravity sign-in line works pasted into PowerShell.** It set the home folder inside double quotes, which
  PowerShell fills in before the line runs, so Antigravity signed in under your own home folder instead of ENLENS's.
  The line now carries its commands encoded, so it reads the same in PowerShell and in the Command Prompt, whatever
  your folders are called.
- **A copy made for an acceptance run or a model test leaves the team's settings behind.** It carried the project's
  shared folder and storage space, so a round run in it would have acted in the team's place.
- **Quit ends a Codex sign-in still waiting for the browser.** It went on running after ENLENS had closed.

### Privacy

- **A codebook's text that may carry words of documents an embedding server on another computer may not read stays
  off it.** Search by meaning sent every code's text to the embedding server set up, wherever it was: a codebook made
  from theory documents marked *Only a local AI* or *No AI* (or not allowed to that server) quotes them, and an AI's
  draft of a definition is its reading of documents. Such codes, and any definition quoting six words in a row of a
  document that server may not read, are now matched by their words only, judged by the documents' settings now. A
  codebook made from theory before this version is recognised by its research-log entry in its own project, and
  elsewhere by its definitions' quotations with their source; a definition you have reworded without its quotation
  is sent as your own words. A server on this computer still gets them all.

### Fixed

- **A local model typed as `ollama.localhost` or `localhost.localdomain` says how to fix it.** Such an address counts
  as another computer, so documents marked *Only a local AI* waited with only "is another computer" said. The local
  panel and *Settings › AI* now add: type `localhost` or `127.0.0.1` instead.
- ***How these results were made* says "not recorded" for an answer from before ENLENS recorded how answers were
  made**, instead of a blank that read as "no temperature sent".
- **A Codex or Antigravity helper whose message says "design in" no longer ends the run as "not signed in".**
- **The AI log names the model of a Codex or Antigravity helper ENLENS started, every time.** A helper that took
  its first batch at the moment ENLENS rewrote its record of the run was logged as "not known (its own choice)".
- **A helper started before you put its kind on *Hold* is not counted as failing**, so three of them no longer end
  the run with "did not answer the queue".
- **A refused Antigravity helper is said in plain words** in the run's report, without Python's name for the error,
  and takes no helper number.
- **A local server's answer piece of an unexpected shape is skipped**, as an unreadable line is: Ollama's stopped the
  task with an internal error, and an OpenAI-compatible server's was said as "Could not reach the local server".
