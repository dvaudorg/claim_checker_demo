### Fixed

- **Once Claude Code has answered its part, nothing asks for Claude Code again.** Reading more excerpts of a check
  that also has excerpts marked Only a local AI: Claude Code answered its part in seconds, then the local model read
  its own for a few minutes. All that time the AI run panel still said one task waited for Claude Code and offered
  Start Claude Code. The sidebar could offer it too, until the local model began. Each press started a run that found
  nothing to do. The cause: the job's last "waiting for Claude Code" report stayed its newest word. The wait in the
  queue now says when it is over, and the panel lets the project's queue decide whether anything still waits for
  Claude Code.
  Tests: `tests/test_answered_queue_not_asked_again.py` (the panel runs in Node).
