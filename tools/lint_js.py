"""Lints the page's JavaScript for two faults no test sees until a person meets them (bug hunt, phase 0, 2026-11-18):

- a name that is defined nowhere (`no-undef`): a misspelt helper, a forgotten import;
- an async function as a Promise's executor (`no-async-promise-executor`): what it throws vanishes, as in the code
  picker that did nothing when its codebook could not be loaded.

Both had no finding left when the rules were added, so a finding is a new fault. CI runs this on Linux beside ruff.
Here: `python tools/lint_js.py` (or with a folder to lint). It needs Node's npm and the network: eslint is installed,
at the versions pinned below, into a temporary folder that is removed afterwards. Nothing is added to the repository.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "src" / "enlens_claims" / "gui" / "static"
PACKAGES = ("eslint@9.15.0", "globals@15.12.0")   # pinned: a new eslint must not fail a run by itself
RULES = {"no-undef": "error", "no-async-promise-executor": "error"}
CONFIG = """import globals from "globals";
export default [{
  languageOptions: { ecmaVersion: "latest", sourceType: "module", globals: { ...globals.browser } },
  linterOptions: { reportUnusedDisableDirectives: "off" },
  rules: %s,
}];
"""


def lint(folder: Path = STATIC) -> int:
    """0 when `folder` has no finding, 1 when it has, 2 when eslint could not run."""
    npm = shutil.which("npm")
    if not npm:
        print("npm is not installed: the page's JavaScript was not linted.")
        return 2
    with tempfile.TemporaryDirectory(prefix="enlens-eslint-") as tmp:
        got = subprocess.run([npm, "install", "--no-audit", "--no-fund", "--silent", "--prefix", tmp, *PACKAGES],
                             capture_output=True, text=True, timeout=300, check=False)
        if got.returncode != 0:
            print("eslint could not be installed:\n" + (got.stderr or got.stdout).strip()[-2000:])
            return 2
        config = Path(tmp) / "eslint.config.mjs"   # beside node_modules: its import of `globals` is found there
        config.write_text(CONFIG % json.dumps(RULES), encoding="utf-8")
        eslint = Path(tmp) / "node_modules" / ".bin" / ("eslint.cmd" if os.name == "nt" else "eslint")
        # run from the folder itself: eslint only lints files under its base path
        ran = subprocess.run([str(eslint), "-c", str(config), "."], cwd=folder, timeout=600, check=False)
        return ran.returncode if ran.returncode in (0, 1) else 2


if __name__ == "__main__":
    sys.exit(lint(Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else STATIC))
