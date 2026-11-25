### Fixed

- **Repeatable results no longer offers a test that asks nothing on Claude Code, Codex or Antigravity.** These tools
  take no seed and no temperature, so the button answered at once with the same box each time, which looked like
  nothing happened, and on Antigravity it named Claude Code and "sonnet". Settings › Technical › Repeatable results
  now says plainly that their answers are not guaranteed to repeat, names the tool, and points to Test a model before
  trusting it, which does send tasks to them. Does not change results.
