### Privacy

- **Antigravity runs with a home folder and settings of its own.** ENLENS starts Antigravity with its own settings, in
  its data folder, never with yours: a permission you gave your own Antigravity, "run every tool without asking", your
  connectors and your AI credits no longer reach ENLENS's runs, and ENLENS no longer writes into your own Antigravity
  settings. Its settings allow only ENLENS's connector, and your telemetry choice is carried over. The set-up lists
  the permission line and work folder ENLENS 0.20.0–0.20.1 wrote into your own settings and offers **Remove them**
  (a copy is kept). On a Mac the sign-in is found where it is; where Antigravity keeps it in the home folder, it asks
  for one sign-in for ENLENS. Cannot change results.
- **ENLENS refuses to start an Antigravity without its sandbox switch** (or whose options it cannot read), rather than
  start it less closed in, and says so.
- **A tool Antigravity refused a helper is written in the run's report.** A helper only needs ENLENS's own tools, so
  an attempt to read a file or run a command suggests that text in a passage told it to (prompt injection). It did not
  run, and the run goes on.

### Not yet done

- The separate Antigravity home is tried on Windows only; a whole run in it, macOS, Linux and an account with bought
  AI credits are still to try.
