### Changes that can alter your results

- **The validation report never counts a passage without an answer as a right code decision.** A passage the model
  left unanswered was read as "no code", so it was right for every code the gold set does not give it, as an
  unfinished check never is. Its decisions now count as "no answer"; a model that fails passages scores lower, and
  repeatability no longer counts an unanswered passage as agreeing with an empty one.
- **An acceptance theme sheet written before the model answered is not scored.** A `g6_theme_names_<model>.csv`
  written by an earlier version before the model had named its themes holds the reference project's own names; your
  "fitting" for those was scored as the model's. Only rows holding the model's own name count, and `acceptance score`
  says when a sheet holds other names (move it away and score again: it is written anew).
- **A graphics card too small for the larger local models no longer puts them on the processor.** A PC with, say, a
  4 GB card and 32 GB of memory was offered the larger model running on the processor, minutes a check. It now gets
  the largest model its card holds (on a 4 GB card the small one), as a computer without a card does; the others stay
  under *Settings › Technical*.

### Safer

- **Codex or Antigravity installed with npm on Windows gets the helper's instructions whole.** npm installs them as
  `.cmd` files, which Windows runs through its command line: it cut the instructions at the first line break, and a
  project named with `&` could run a command. ENLENS now starts the program the `.cmd` file starts; a command file of
  another kind is refused at *Start*, with a line saying to use the maker's installer.
- **The Antigravity sign-in line works pasted into PowerShell.** It set the home folder inside double quotes, which
  PowerShell fills in before the line runs, so Antigravity signed in under your own home folder instead of ENLENS's.
  The line now runs the sign-in window's own script, and reads the same in PowerShell and in the Command Prompt.
- **A copy made for an acceptance run or a model test leaves the team's settings behind.** It carried the project's
  shared folder and storage space, so a round run in it would have acted in the team's place.
- **Quit ends a Codex sign-in still waiting for the browser.** It went on running after ENLENS had closed.

### Privacy

- **A codebook's text that may carry words of documents marked *Only a local AI* stays off an embedding server on
  another computer.** Search by meaning sent every code's text to the embedding server set up, wherever it was: a
  codebook made from theory documents marked *Only a local AI* or *No AI* quotes them, and an AI's draft of a
  definition is its reading of documents. Such codes, and any definition quoting six words in a row of a document
  that server may not read, are now matched by their words only. A server on this computer still gets them all.

### Fixed

- **A local model typed as `ollama.localhost` or `localhost.localdomain` says how to fix it.** Such an address counts
  as another computer, so documents marked *Only a local AI* waited with only "is another computer" said. The local
  panel and *Settings › AI* now add: type `localhost` or `127.0.0.1` instead.
- ***How these results were made* says "not recorded" for an answer from before ENLENS recorded how answers were
  made**, instead of a blank that read as "no temperature sent".
- **A Codex or Antigravity helper whose message says "design in" no longer ends the run as "not signed in".**
- **A helper started before you put its kind on *Hold* is not counted as failing**, so three of them no longer end
  the run with "did not answer the queue".
- **A refused Antigravity helper is said in plain words** in the run's report, without Python's name for the error,
  and takes no helper number.
- **A local server's answer piece of an unexpected shape is skipped**, as an unreadable line is: Ollama's stopped the
  task with an internal error, and an OpenAI-compatible server's was said as "Could not reach the local server".
