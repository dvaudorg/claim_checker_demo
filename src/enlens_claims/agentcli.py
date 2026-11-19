"""Agent CLIs of other providers on the person's own plan (stage 2 of other cloud providers): Codex (OpenAI, `codex`)
and Antigravity (Google, `agy`), set up and started from ENLENS as Claude Code is (claude_setup.py).

What each adapter does, behind one interface (the app's Settings → AI and its Start buttons use it):

- `find(route)`, `status(route, refresh)`: is the program here, which version, is it signed in (True, False, or None
  when it does not say), which account it names, which models the plan offers (`agy models`), and whether ENLENS is
  added to it. Cached for half a minute, like claude_setup.status. Only probes that start no model are run.
- `installer_command(route)`, `install_cli(route)`: the provider's own installer, run after the person confirmed it.
- `open_sign_in(route)`: Codex signs in with `codex login`, which opens the browser by itself (started in the
  background, no window); Antigravity signs in on its first interactive start, so a terminal window opens running `agy`
  in an empty folder of ENLENS (as Claude Code's sign-in window).
- `set_up(route)`: adds ENLENS to the CLI: Codex gets the ENLENS connector (`codex mcp add enlens ...`), the skill
  `$enlens-run` and the helpers as Codex subagents; Antigravity gets the ENLENS plugin (`agy plugin install`), so the
  person can type /enlens-run in it, and ENLENS's own Antigravity home is prepared (below). Nothing else of the
  person's is changed. `repair()` writes them again when ENLENS's version, Python or data folder changed.

The runner (`start_run`): neither CLI's headless mode is documented to run skills or subagents, so ENLENS does what
Claude Code's /enlens-run does itself: it asks the queue for the groups and how many helpers to start for each
(taskqueue.run_status), starts one CLI process per helper, on the group's model in the provider's own name
(routing.Router.api_id) and with the effort of the chosen thought, waits, and asks again, until nothing is left to
start or the person presses Stop. Each process's prompt is the helper's own instructions (the body of
claude_plugin/agents/<helper>.md, the same as Claude Code's) and the batch to take. The CLI only answers: ENLENS
checks every quote, as for Claude Code.

Boxing each run in: Codex starts in an empty folder, with the person's own Codex settings left out
(`--ignore-user-config`), read-only, without its shell, web search and image tools, with the ENLENS connector given on
the command line (`-c mcp_servers.enlens...`) and only its three queue tools enabled. Antigravity has no switch for
its own tools: it starts in ENLENS's own empty work folder, in its sandbox, without slash commands, and with its
default "ask first" for every tool, which nobody can answer in a background run, so every tool but ENLENS's is refused.

Antigravity runs in a home folder of its own (`agy_home()`, HOME and USERPROFILE pointed there): the person's own
Antigravity settings never reach ENLENS's runs (their allow rules, "always proceed", connectors, AI credits), and
ENLENS writes the settings there before each run: the one allow rule `mcp(enlens/*)`, its work folder as trusted,
nothing that spends AI credits (agy deletes `useG1Credits: false` on every start, so "off" can only be "absent").
Tested with agy 1.5.11 on Windows (18 Nov 2026): the sign-in is kept outside the home folder there (Credential
Manager), so none is needed again. On macOS the login keychain is found through $HOME/Library/Keychains, so ENLENS's
home links that folder to the person's. Where a CLI keeps its sign-in in the home folder, ENLENS's Antigravity asks for
its own sign-in once (the set-up's sign-in step runs in ENLENS's home too). A tool Antigravity refused (its JSON's
`denied_actions`) is written in the run's log: a helper has no reason to use one, so text in a passage may have asked it
to.

Run records (process ids) are kept under <ENLENS_HOME>/claude-runs/ as `<route>-<project>.run.json`, so Stop, Quit
and a restarted app find the helpers of a run an earlier app started, as for Claude Code.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import __version__, providers
from . import home as core
from .claude_setup import _cmd, _end_process, _open_window, _run_key, _said, frontmatter
from .procs import console_python, no_window, program_args, same_python
from .store import now
from .update import semver as _semver

ROUTES = tuple(providers.AGENT_CLIS)          # codex, antigravity
SERVER = "enlens"                              # the connector's name in each CLI
QUEUE_TOOLS = ("next_tasks", "submit_answers", "release")
MARKER = "[ENLENS queue helper]"               # the first words of every helper's prompt: how its process is known
SOURCE = Path(__file__).with_name("agent_plugins")
AGENTS = Path(__file__).with_name("claude_plugin") / "agents"
PERMISSION = f"mcp({SERVER}/*)"                # the one allow rule written into Antigravity's settings
BATCHES = 5                                    # batches one helper process takes before it ends
POLL = 2.0                                     # seconds between two looks of the runner
IDLE_ROUNDS = 5                                # looks with nothing at work and nothing to start before a run ends
MAX_FAILED = 3                                 # helper processes in a row that did nothing before a run gives up

INSTALLERS = {
    "codex": {"unix": "curl -fsSL https://chatgpt.com/codex/install.sh | sh",
              "windows": 'powershell -ExecutionPolicy ByPass -c "irm https://chatgpt.com/codex/install.ps1 | iex"',
              "docs": "https://github.com/openai/codex", "env": "ENLENS_CODEX_INSTALLER"},
    "antigravity": {"unix": "curl -fsSL https://antigravity.google/cli/install.sh | bash",
                    "windows": "irm https://antigravity.google/cli/install.ps1 | iex",
                    "docs": "https://antigravity.google/docs/getting-started", "env": "ENLENS_AGY_INSTALLER"},
}
PROGRAM_ENV = {"codex": "ENLENS_CODEX", "antigravity": "ENLENS_AGY"}
SIGN_IN_DOCS = {"codex": "https://learn.chatgpt.com/docs/auth", "antigravity": "https://antigravity.google/docs/getting-started"}

LIMIT_WORDS = re.compile(r"usage limit|rate limit|quota|limit reached|hit your (?:usage )?limit|too many requests|"
                         r"resource.?exhausted", re.I)
# hunt phase 1.5: whole words (`sign ?in` found "design in", and a helper that said so ended the run as signed out)
SIGNED_OUT_WORDS = re.compile(r"\b(?:not logged in|not signed in|log ?in first|sign ?in|authenticat\w*|"
                              r"unauthori[sz]ed|401)\b", re.I)
RESETS_WORDS = re.compile(r"(?:try again|resets?|available again)\s+(?:at|in|on)?\s*([^\n.;|\"]{1,40})", re.I)


def cli(route: str) -> providers.AgentCli:
    a = providers.AGENT_CLIS.get(route)
    if a is None:
        raise ValueError(f"Unknown agent CLI {route!r}: choose {' or '.join(ROUTES)}.")
    return a


def _off() -> None:
    if core.local_only():
        raise ValueError("Cloud models are switched off on this computer: the agent CLIs are not available.")


def user_home() -> Path:
    """The person's home folder, where each CLI keeps its own settings (ENLENS_AGENT_HOME in the tests)."""
    return Path(os.environ.get("ENLENS_AGENT_HOME") or Path.home())


def codex_home() -> Path:
    if os.environ.get("ENLENS_AGENT_HOME"):
        return user_home() / ".codex"
    return Path(os.environ.get("CODEX_HOME") or (user_home() / ".codex"))


def agy_settings_path() -> Path:
    """The person's own Antigravity settings (ENLENS no longer writes them: see own_agy_leftovers)."""
    return user_home() / ".gemini" / "antigravity-cli" / "settings.json"


def agy_home() -> Path:
    """ENLENS's own home folder for Antigravity: its runs, its status and its sign-in window start with HOME (and
    USERPROFILE) pointed here, so they read ENLENS's settings, never the person's."""
    return core.home() / "agy-home"


def enlens_agy_settings_path() -> Path:
    return agy_home() / ".gemini" / "antigravity-cli" / "settings.json"


AGY_ENV_PREFIXES = ("GEMINI_", "GOOGLE_", "AGY_", "ANTIGRAVITY_", "CLOUDSDK_", "VERTEX")


def agy_env() -> dict[str, str | None]:
    """What changes in the environment of every Antigravity process ENLENS starts (None: left out): its home is
    ENLENS's own, and a person's XDG folders, which would lead back to their own settings, are left out."""
    h = str(agy_home())
    env: dict[str, str | None] = {"HOME": h, "USERPROFILE": h}
    for k in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
        env[k] = None
    # a key or project of the person's own (GEMINI_API_KEY, GOOGLE_APPLICATION_CREDENTIALS, a settings path...) would
    # bill ENLENS's runs to it or lead back to their settings: only the sign-in Antigravity keeps for itself is used
    for k in os.environ:
        if k.upper().startswith(AGY_ENV_PREFIXES):
            env[k] = None
    return env


def _environ(env: dict | None) -> dict[str, str]:
    merged = {**os.environ, **(env or {})}
    return {k: v for k, v in merged.items() if v is not None}


def runs_folder() -> Path:
    d = core.home() / "claude-runs"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------------------------
# finding the program, asking it
# ---------------------------------------------------------------------------------------------
def find(route: str) -> str:
    """The CLI's program: ENLENS_CODEX / ENLENS_AGY, the PATH, or where its installers put it. "" when not found."""
    a = cli(route)
    env = os.environ.get(PROGRAM_ENV[route], "").strip()
    if env:
        return env if Path(env).exists() else ""
    found = shutil.which(a.program)
    if found and not _command_file(found):
        return found
    h = Path.home()
    exe = ".exe" if _windows() else ""
    if route == "codex":
        cands = [h / ".local" / "bin" / f"codex{exe}", Path("/opt/homebrew/bin/codex"), Path("/usr/local/bin/codex"),
                 h / ".npm-global" / "bin" / "codex", h / "AppData" / "Roaming" / "npm" / "codex.cmd",
                 h / ".codex" / "bin" / f"codex{exe}"]
    else:
        local = Path(os.environ.get("LOCALAPPDATA") or (h / "AppData" / "Local"))
        cands = [h / ".local" / "bin" / f"agy{exe}", local / "agy" / "bin" / "agy.exe", Path("/opt/homebrew/bin/agy"),
                 Path("/usr/local/bin/agy")]
    # hunt phase 1.5: a real program before a command file (npm's codex.cmd first on the PATH would otherwise keep
    # being found after the person installed the maker's own program, as `_cmd_refused` asks)
    real = shutil.which(f"{a.program}.exe") if _windows() else None
    for c in ([Path(real)] if real else []) + cands:
        if c.exists() and not _command_file(str(c)):
            return str(c)
    if found:
        return found
    for c in cands:
        if c.exists():
            return str(c)
    return ""


def _windows() -> bool:
    return os.name == "nt"


# Hunt phase 1.5: Codex installed with npm is `codex.cmd`, a command file, and Windows starts a command file through
# cmd.exe, which reads the whole line again: a helper's prompt (several lines, the project's name, quotes, & | < > %)
# was cut at its first line break, and `a & echo pwned > x.txt & b` in a project's name ran as a command. A helper's
# prompt never goes through cmd.exe: npm's command file is read for the program it starts (node and its script) and
# that is started instead; a command file of another kind is refused for a helper (`run_args`). Calls without free
# text (the version, the help, `login`) go through `procs.program_args`, which quotes each argument for cmd.exe.
_SHIM_TARGET = re.compile(r'"%~?dp0%?\\?([^"%\r\n]+)"\s*%\*')


def _shim_target(path: str) -> list[str] | None:
    """The program npm's command file (cmd-shim: `"%_prog%" "%dp0%\\node_modules\\…\\codex.js" %*`) starts, as an
    argument list without cmd.exe: [node, the script], node beside the file (`node.exe`, as the shim prefers it) or on
    the PATH; [the program] when it starts an .exe. None when the file is not such a shim or its target is missing."""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = _SHIM_TARGET.search(text)
    if not m:
        return None
    here = Path(path).parent
    target = here / m.group(1).replace("\\", os.sep)
    if not target.is_file():
        return None
    if target.suffix.lower() == ".exe":
        return [str(target)]
    if target.suffix.lower() not in (".js", ".cjs", ".mjs"):
        return None
    node = here / "node.exe"
    node_path = str(node) if node.is_file() else shutil.which("node")
    if node_path and _command_file(node_path):
        # hunt phase 1.5 (review): a Node version manager may put node.cmd first on the PATH, which brings cmd.exe
        # back; only a real program is taken (the first node.exe on the PATH), else none
        node_path = shutil.which("node.exe")
        if node_path and _command_file(node_path):
            node_path = None
    return [node_path, str(target)] if node_path else None


def _command_file(path: str) -> bool:
    return _windows() and str(path).lower().endswith((".cmd", ".bat"))


def _program(path: str) -> list[str]:
    """How to start the CLI found at `path` (claude_setup._cmd), npm's command file read for its program on Windows."""
    if _command_file(path):
        target = _shim_target(path)
        if target:
            return target
    return _cmd(path)


_CMD_WORDS = ("This {title} is started by a command file ({path}) that ENLENS cannot see through (or that starts node "
              "through another command file), and a helper's instructions cannot pass through Windows' command line "
              "whole. Install {title} with its own installer (Settings → AI), then press Start again. If this stays "
              "after that, remove the other {title} (for one installed with npm: npm uninstall -g), or put its folder "
              "after the installer's on your PATH.")


def _cmd_refused(route: str, path: str) -> str:
    """Why a helper of this CLI cannot be started ("" when it can): a command file ENLENS cannot read through."""
    if not _command_file(path) or _shim_target(path):
        return ""
    return _CMD_WORDS.format(title=cli(route).title, path=path)


def _run(args: list[str], timeout: float = 60, cwd: Path | None = None, env: dict | None = None) -> tuple[int, str]:
    """Run the CLI and return its exit code and what it wrote (UTF-8, without a window on Windows). `env`: what
    changes in the environment (a None value leaves that variable out)."""
    args = _program(args[0]) + list(args[1:])
    try:  # (a command file that is not npm's goes through cmd.exe, each argument quoted for it: procs.program_args)
        r = subprocess.run(program_args(args), capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, cwd=str(cwd or core.home()), stdin=subprocess.DEVNULL,
                           env=_environ(env), **no_window())
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        return 1, f"{type(e).__name__}: {e}"
    return r.returncode, _plain(((r.stdout or "") + (r.stderr or "")).strip())


def _plain(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", text or "")


_OPTIONS: dict = {}


def known_options(route: str, path: str) -> set[str]:
    """The options this CLI's headless mode knows, from its help (`codex exec --help`, `agy --help`), read once per
    program file. Empty when the help cannot be read: then only what is needed is passed."""
    try:
        st = Path(path).stat()
        key = (route, path, st.st_size, st.st_mtime_ns)
    except OSError:
        return set()
    if key not in _OPTIONS:
        code, text = (_run([path, "exec", "--help"], timeout=30) if route == "codex"
                      else _run([path, "--help"], timeout=30, env=agy_env()))
        _OPTIONS[key] = (set(re.findall(r"(?<![\w-])--[A-Za-z][A-Za-z-]+", text))
                         | set(re.findall(r"(?<![\w-])-[A-Za-z](?![\w-])", text))) if code == 0 else set()
    return _OPTIONS[key]


def _json_in(text: str, opener: str = "{"):
    """The JSON value in a CLI's output that may carry other lines around it (None when there is none)."""
    closer = "}" if opener == "{" else "]"
    i, j = text.find(opener), text.rfind(closer)
    if i < 0 or j < i:
        return None
    try:
        return json.loads(text[i:j + 1])
    except ValueError:
        return None


MODEL_LINE = re.compile(r"^\s*([a-z0-9][a-z0-9._-]*[a-z0-9])(?:\s{2,}|\t|\s*$)", re.I)


def parse_models(text: str) -> list[str]:
    """The model slugs `agy models` lists, one per line ("gemini-4-carbon-high   Gemini 4 Carbon (High)")."""
    out = []
    for line in (text or "").splitlines():
        m = MODEL_LINE.match(line)
        if m and "-" in m.group(1) and m.group(1).lower() not in out:
            out.append(m.group(1).lower())
    return out


# ---------------------------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------------------------
_STATUS: dict[str, dict] = {}


def status(route: str, refresh: bool = False) -> dict:
    """What is ready for this CLI, for the set-up checklist (cached half a minute): {found, path, version, signed_in
    (True/False/None), account, models_available, connector (ENLENS added: True/False/None), ready, can_start,
    local_only, problem}. `ready`: found, not known to be signed out, and ENLENS added (the set-up is finished).
    `can_start`: found and not known to be signed out (the app can start it; ENLENS is added on the first start when
    it is not yet)."""
    cli(route)
    c = _STATUS.get(route)
    if not refresh and c and time.time() - c["at"] < 30:
        return c["value"]
    started = time.time()
    out = {"found": False, "path": "", "version": "", "signed_in": None, "account": "", "models_available": [],
           "connector": None, "ready": False, "can_start": False, "local_only": core.local_only(),
           "problem": ""}
    path = "" if out["local_only"] else find(route)
    if path:
        out.update(found=True, path=path)
        code, text = _run([path, "--version"], timeout=20, env=agy_env() if route == "antigravity" else None)
        if code == 0 and text:
            out["version"] = _said(text.splitlines()[0])
        (_codex_status if route == "codex" else _agy_status)(path, out)
    out["can_start"] = bool(out["found"] and out["signed_in"] is not False)
    out["ready"] = bool(out["can_start"] and out["connector"] is True)
    # only the newest answer is kept: a slow look begun before an install or a sign-in finished must not put back
    # "not found" over the answer of a look begun after it (the queue then said "Antigravity was not found")
    now_c = _STATUS.get(route)
    if now_c is None or now_c.get("began", 0) <= started:
        _STATUS[route] = {"at": time.time(), "began": started, "value": out}
    return out


def _codex_status(path: str, out: dict) -> None:
    code, text = _run([path, "login", "status"], timeout=20)
    if code == 0 and not re.search(r"not logged in|not signed in", text, re.I):
        out["signed_in"] = True
        # "Logged in using ChatGPT (you@uni.nl)" → "ChatGPT (you@uni.nl)": the app writes "Signed in with …"
        first = text.splitlines()[0] if text else ""
        out["account"] = _said(re.sub(r"^\s*(?:logged|signed) in (?:using|with|as)\s+", "", first, flags=re.I))
    elif re.search(r"not logged in|not signed in|logged out|no credentials", text, re.I) or code != 0 and text:
        out["signed_in"] = False
    out["connector"] = codex_connector(path)


def codex_connector(path: str) -> bool | None:
    """Whether the ENLENS connector is in Codex (`codex mcp list --json`, else its config.toml) and ENLENS's skill is
    written. None when that cannot be read."""
    code, text = _run([path, "mcp", "list", "--json"], timeout=30)
    have = None
    data = _json_in(text, "[") if code == 0 else None
    if data is None and code == 0:
        data = _json_in(text, "{")
    if isinstance(data, list):
        have = any(isinstance(x, dict) and (x.get("name") or x.get("id")) == SERVER for x in data)
    elif isinstance(data, dict):
        servers = data.get("mcp_servers") or data.get("servers") or data
        have = isinstance(servers, dict) and SERVER in servers
    if have is None:
        try:
            have = bool(re.search(rf"^\s*\[mcp_servers\.{SERVER}\]", (codex_home() / "config.toml").read_text("utf-8"),
                                  re.M))
        except OSError:
            return None
    return bool(have and codex_skill_path().exists())


def _agy_status(path: str, out: dict) -> None:
    # signed in, and which models: asked in ENLENS's own home, where its runs start (its own sign-in where a CLI keeps
    # it in the home folder); the plugin: in the person's own Antigravity, where they type /enlens-run
    try:
        prepare_agy_home()
    except (OSError, ValueError) as e:
        out["problem"] = f"ENLENS's own Antigravity settings could not be written: {e}"
    code, text = _run([path, "models"], timeout=30, env=agy_env())
    if code == 0:
        out["signed_in"] = True
        out["models_available"] = parse_models(text)
    elif SIGNED_OUT_WORDS.search(text):
        out["signed_in"] = False
    else:
        out["problem"] = _said(text, 300)
    code, text = _run([path, "plugin", "list", "--json"], timeout=30)
    data = _json_in(text, "[") if code == 0 else None
    if isinstance(data, list):
        out["connector"] = any(isinstance(p, dict) and p.get("name") == "enlens-run" and p.get("enabled", True)
                               for p in data)


def forget_status(route: str | None = None) -> None:
    if route:
        _STATUS.pop(route, None)
    else:
        _STATUS.clear()


# ---------------------------------------------------------------------------------------------
# installing, signing in
# ---------------------------------------------------------------------------------------------
def installer_command(route: str, sys_name: str | None = None) -> dict:
    """The provider's own installer: the line shown to the person ({line, args, docs}) and the program ENLENS runs
    after they confirm. ENLENS_CODEX_INSTALLER / ENLENS_AGY_INSTALLER replace the program (tests, dev server)."""
    from .installation import system

    cli(route)
    i = INSTALLERS[route]
    windows = (sys_name or system()) == "windows"
    line = i["windows"] if windows else i["unix"]
    if windows:
        inner = line.split('"')[1] if line.startswith("powershell") else line
        args = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", inner]
    else:
        args = ["/bin/sh" if line.endswith("| sh") else "/bin/bash", "-c", line]
    stand_in = os.environ.get(i["env"], "").strip()
    if stand_in:
        args = _cmd(stand_in)
    return {"line": line, "args": args, "docs": i["docs"]}


def install_cli(route: str, timeout: float = 900) -> dict:
    """Run the installer (the person confirmed it in the app). Returns {"ok", "text", "status"}."""
    _off()
    cmd = installer_command(route)
    env = {**os.environ, "ENLENS_INSTALLING": route}
    if route == "codex":
        env["CODEX_NON_INTERACTIVE"] = "1"   # the installer's questions skipped (its documented switch)
    try:
        r = subprocess.run(cmd["args"], capture_output=True, text=True, errors="replace", timeout=timeout,
                           stdin=subprocess.DEVNULL, cwd=str(Path.home()), env=env, **no_window())
        code, text = r.returncode, (r.stdout or "") + (r.stderr or "")
    except (OSError, subprocess.SubprocessError) as e:
        code, text = 1, f"{type(e).__name__}: {e}"
    text = _plain(text).strip()
    st = status(route, refresh=True)
    if code == 0 and not st["found"]:
        text = (text + "\n" if text else "") + (f"The installer finished, but ENLENS cannot find the "
                                                f"{cli(route).program} program yet.")
    return {"ok": code == 0 and st["found"], "text": text[-1500:], "status": st}


_LOGIN: dict[str, subprocess.Popen] = {}


def sign_in_folder(route: str) -> Path:
    """The empty folder Antigravity's sign-in window starts in (anything in it removed first)."""
    d = runs_folder() / f"{route}-sign-in"
    d.mkdir(parents=True, exist_ok=True)
    for child in d.iterdir():
        try:
            shutil.rmtree(child, ignore_errors=True) if child.is_dir() and not child.is_symlink() else child.unlink()
        except OSError:
            pass
    return d


def _sign_in_script(route: str, path: str, work: Path, windows: bool | None = None) -> Path:
    """The sign-in window's script: PowerShell on Windows (`windows`; this computer's by default), else sh."""
    title = cli(route).title
    if _windows() if windows is None else windows:
        from .gui.launcher import _ps_quote

        q = lambda s: _ps_quote(str(s))  # noqa: E731 - a PowerShell string
        p = runs_folder() / f"{route}-sign-in.ps1"
        home = str(agy_home())
        p.write_text(f"Write-Host 'ENLENS: sign in to {title} with your Google account.'\r\n"
                     "Write-Host 'Follow the steps below; when it shows its prompt, close this window.'\r\n"
                     "Write-Host 'It runs in an empty folder of ENLENS, with ENLENS own Antigravity settings.'\r\n"
                     f"$env:USERPROFILE = {q(home)}\r\n$env:HOME = {q(home)}\r\n"
                     f"Set-Location -LiteralPath {q(work)}\r\n"
                     f"& {' '.join(q(x) for x in _program(path))}\r\n", encoding="utf-8-sig", newline="")
        return p
    import shlex

    p = runs_folder() / f"{route}-sign-in.command"
    p.write_text("#!/bin/sh\n"
                 f"echo 'ENLENS: sign in to {title} with your Google account.'\n"
                 "echo 'Follow the steps below; when it shows its prompt, close this window.'\n"
                 "echo \"It runs in an empty folder of ENLENS, with ENLENS's own Antigravity settings.\"\n"
                 "echo\n"
                 f"cd {shlex.quote(str(work))} || exit 1\n"
                 "unset XDG_CONFIG_HOME XDG_DATA_HOME XDG_STATE_HOME XDG_CACHE_HOME\n"
                 f"HOME={shlex.quote(str(agy_home()))} exec {' '.join(shlex.quote(x) for x in _cmd(path))}\n",
                 encoding="utf-8")
    p.chmod(0o755)
    return p


def open_sign_in(route: str) -> dict:
    """Start the CLI's own sign-in. Codex: `codex login` in the background (it opens the browser itself; no window).
    Antigravity: a terminal window running `agy` in an empty folder of ENLENS. ENLENS never sees the login; the app
    asks `status()` until it says signed in. Returns {opened, window ("" for Codex), command}."""
    _off()
    path = find(route)
    title = cli(route).title
    if not path:
        raise ValueError(f"{title} is not on this computer yet: install it first.")
    forget_status(route)
    if route == "codex":
        running = _LOGIN.get(route)
        if running is None or running.poll() is not None:
            log = open(runs_folder() / "codex-login.log", "w", encoding="utf-8")
            try:
                _LOGIN[route] = subprocess.Popen(program_args(_program(path) + ["login"]), cwd=str(core.home()),
                                                 stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                                 start_new_session=os.name != "nt", **no_window())
            except OSError as e:
                raise ValueError(f"Codex's sign-in could not start: {e}") from e
            finally:
                log.close()
        return {"opened": True, "window": "", "command": "codex login"}
    work = sign_in_folder(route)
    prepare_agy_home()
    script = _sign_in_script(route, path, work)
    window = _open_window(script)
    import shlex

    home = str(agy_home())
    if not _windows():
        line = (f"cd {shlex.quote(str(work))} && env -u XDG_CONFIG_HOME -u XDG_DATA_HOME -u XDG_STATE_HOME "
                f"-u XDG_CACHE_HOME HOME={shlex.quote(home)} agy")
    else:
        line = windows_sign_in_line(path, work)
    return {"opened": bool(window), "window": window, "command": line, "folder": str(work)}


def sign_in_commands(path: str, work: Path) -> str:
    """The PowerShell commands of the sign-in on Windows: ENLENS's home for agy, its empty folder, agy started."""
    from .gui.launcher import _ps_quote

    home = _ps_quote(str(agy_home()))
    return (f"$env:USERPROFILE = {home}; $env:HOME = {home}; Set-Location -LiteralPath {_ps_quote(str(work))}; "
            f"& {' '.join(_ps_quote(str(x)) for x in _program(path))}")


def windows_sign_in_line(path: str, work: Path) -> str:
    """The line the page shows to type on Windows when no window opened: the sign-in's commands, run by a child
    PowerShell (so the person's own session keeps its home folder). Hunt phase 1.5: the line was `powershell -Command
    "…; $env:USERPROFILE='…'; $env:HOME='…'; agy"`, and PowerShell, Windows Terminal's shell, expands $env:… inside
    double quotes before the child starts: agy ran in the person's own home. The commands now go as -EncodedCommand,
    which neither PowerShell nor cmd.exe reads into, whatever the folders' names hold; and, unlike a script file, an
    execution policy of the organisation (AllSigned) does not stop them (review)."""
    import base64

    enc = base64.b64encode(sign_in_commands(path, work).encode("utf-16-le")).decode("ascii")
    return f"powershell -NoProfile -EncodedCommand {enc}"


# ---------------------------------------------------------------------------------------------
# adding ENLENS to the CLI
# ---------------------------------------------------------------------------------------------
def _fill(text: str, route: str) -> str:
    return (text.replace("{{VERSION}}", _semver(__version__)).replace("{{TITLE}}", cli(route).title)
            .replace("{{TOOL_PREFIX}}", ""))


def helper_files() -> dict[str, Path]:
    """Every helper's instruction file: ENLENS's own seven and an add-on kind's (taskkinds.addon_helpers)."""
    from . import taskkinds

    out = {f.stem: f for f in sorted(AGENTS.glob("*.md"))}
    out.update({h: Path(f) for h, f in taskkinds.addon_helpers().items()})
    return out


def helper_body(helper: str) -> str:
    """The instructions of a helper (the body of its agent file, without the front matter)."""
    f = helper_files().get(helper) or AGENTS / f"{helper}.md"
    text = f.read_text(encoding="utf-8")
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end >= 0:
            text = text[end + 4:]
    return _fill(text, "codex").strip()


def connector_env(route: str) -> dict[str, str]:
    return {"ENLENS_HOME": str(core.home()), "ENLENS_ROUTE": route}


def connector_command() -> list[str]:
    """This Python running the connector (as claude_setup.mcp_config)."""
    # hunt phase 1.5: the console python.exe beside pythonw.exe (the icon's), as claude_setup names it (`procs`)
    return [console_python(), "-m", "enlens_claims.mcp_server"]


def toml_str(s: str) -> str:
    """A TOML basic string (JSON's escapes are TOML's)."""
    return json.dumps(str(s), ensure_ascii=False)


def toml_list(xs) -> str:
    return "[" + ", ".join(toml_str(x) for x in xs) + "]"


def toml_table(d: dict) -> str:
    return "{" + ", ".join(f"{k}={toml_str(v)}" for k, v in d.items()) + "}"


def _lineup(route: str) -> dict:
    from . import routing

    available = status(route).get("models_available") if route == "antigravity" else None
    return routing.lineup_for(core.load_settings(), route, available or None)


def codex_skill_path() -> Path:
    return user_home() / ".agents" / "skills" / "enlens-run" / "SKILL.md"


def write_codex_files() -> list[Path]:
    """The skill $enlens-run and the helpers as Codex subagents (~/.codex/agents/enlens-<helper>.toml), each on the
    model of the line-up its alias stands for."""
    from . import routing

    lineup = _lineup("codex")
    written = []
    skill = codex_skill_path()
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text(_fill((SOURCE / "codex-SKILL.md").read_text("utf-8"), "codex"), encoding="utf-8")
    written.append(skill)
    agents = codex_home() / "agents"
    agents.mkdir(parents=True, exist_ok=True)
    for h, f in helper_files().items():
        fm = frontmatter(f)
        alias = routing.HELPER_MODEL.get(h) or fm.get("model") or "sonnet"
        model = lineup.get(providers.ALIAS_TIER.get(alias, "middle")) or ""
        lines = [f"name = {toml_str(h)}", f"description = {toml_str(fm.get('description') or h)}",
                 f"developer_instructions = {toml_str(helper_body(h))}"]
        if model:
            lines.append(f"model = {toml_str(model)}")
        p = agents / f"{h}.toml"
        p.write_text("# Written by ENLENS (Settings → AI → Codex); written again when ENLENS changes.\n"
                     + "\n".join(lines) + "\n", encoding="utf-8")
        written.append(p)
    return written


def agy_plugin_folder() -> Path:
    return core.home() / "agy-plugin" / "enlens-run"


def agy_work_folder() -> Path:
    """ENLENS's own folder Antigravity starts in (trusted, empty but for its connector settings)."""
    return runs_folder() / "agy-work"


def agy_mcp_config(route: str = "antigravity") -> dict:
    """The connector as Antigravity loads it. Its runs start with ENLENS's own home (agy_env), so the person's Python
    user folder is named (PYTHONUSERBASE): an ENLENS installed there is still found."""
    import site

    cmd = connector_command()
    env = {**connector_env(route), "PYTHONUSERBASE": site.getuserbase()}
    return {"mcpServers": {SERVER: {"command": cmd[0], "args": cmd[1:], "env": env,
                                    "enabledTools": list(QUEUE_TOOLS), "timeoutSeconds": 600}}}


def write_agy_plugin() -> Path:
    """The plugin folder: plugin.json, the skill, the helpers (flash for the small ones, pro for the others) and the
    connector's settings."""
    from . import routing

    root = agy_plugin_folder()
    if root.exists():
        shutil.rmtree(root)
    (root / "skills" / "enlens-run").mkdir(parents=True)
    (root / "agents").mkdir()
    src = SOURCE / "antigravity"
    (root / "plugin.json").write_text(_fill((src / "plugin.json").read_text("utf-8"), "antigravity"), encoding="utf-8")
    (root / "skills" / "enlens-run" / "SKILL.md").write_text(_fill((src / "SKILL.md").read_text("utf-8"), "antigravity"),
                                                             encoding="utf-8")
    for h, f in helper_files().items():
        fm = frontmatter(f)
        alias = routing.HELPER_MODEL.get(h) or fm.get("model") or "sonnet"
        model = "flash" if alias == "haiku" else "pro"
        desc = (fm.get("description") or h).replace('"', "'")
        (root / "agents" / f"{h}.md").write_text(
            f"---\nname: {h}\ndescription: \"{desc}\"\ntools: {', '.join(QUEUE_TOOLS)}\nmodel: {model}\n---\n\n"
            f"{helper_body(h)}\n", encoding="utf-8")
    (root / "mcp_config.json").write_text(json.dumps(agy_mcp_config(), indent=2), encoding="utf-8")
    return root


def prepare_agy_work_folder() -> Path:
    """Empty ENLENS's Antigravity work folder but for `.agents/mcp_config.json`, the connector it loads there."""
    d = agy_work_folder()
    d.mkdir(parents=True, exist_ok=True)
    for child in d.iterdir():
        if child.name == ".agents":
            continue
        try:
            shutil.rmtree(child, ignore_errors=True) if child.is_dir() and not child.is_symlink() else child.unlink()
        except OSError:
            pass
    _write_agy_connector(d)
    return d


def _write_agy_connector(work: Path) -> None:
    """The work folder's `.agents/` holds ENLENS's connector settings and nothing else (anything a helper might have
    left there is removed)."""
    a = work / ".agents"
    a.mkdir(parents=True, exist_ok=True)
    for child in a.iterdir():
        if child.name == "mcp_config.json":
            continue
        try:
            shutil.rmtree(child, ignore_errors=True) if child.is_dir() and not child.is_symlink() else child.unlink()
        except OSError:
            pass
    _write_json(a / "mcp_config.json", agy_mcp_config())


def _read_json(p: Path) -> dict:
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json(p: Path, data: dict, private: bool = False) -> None:
    """Written whole (home._write_whole: a reader never finds half of it; on Windows a moment's lock is waited out)."""
    p.parent.mkdir(parents=True, exist_ok=True)
    core._write_whole(p, json.dumps(data, indent=2, ensure_ascii=False) + "\n", private=private)


def agy_settings() -> dict:
    """The person's own Antigravity settings ({} when there are none or they cannot be read)."""
    return _read_json(agy_settings_path())


# keys about what Google may keep or use: only an "off" of the person's own is carried into ENLENS's settings
PRIVACY_KEY = re.compile(r"telemetry|usage.?stat|feedback|analytics|crash.?report|improve", re.I)
# keys never kept in ENLENS's settings, whoever wrote them (agy itself, or the person in the sign-in window): what lets
# a tool run unasked or reach further, connectors and hooks, and AI credits. Its own two (permissions,
# trustedWorkspaces) are written by ENLENS.
UNSAFE_KEY = re.compile(r"permission|approv|auto.?accept|yolo|proceed|allow|trust|sandbox|mcp|hook|plugin|extension|"
                        r"credit|exclude.?tools|core.?tools|tools?$", re.I)
_OFF = (False, "off", "false", "disabled", "never")


def _is_off(v) -> bool:
    return v in _OFF or (isinstance(v, str) and v.strip().lower() in _OFF)


def _privacy_off(key: str, value):
    """The "off" of a privacy key ({"enabled": false} of an object), or None when the value turns nothing off: an
    "on", an endpoint or a file to log prompts to is never carried."""
    if isinstance(value, dict):
        return {"enabled": False} if _is_off(value.get("enabled")) else None
    return value if _is_off(value) else None


def prepare_agy_home() -> Path:
    """ENLENS's own Antigravity home, written again before every helper, sign-in and look: its settings allow only
    ENLENS's connector (`permissions` is exactly {"allow": ["mcp(enlens/*)"]}), trust only ENLENS's work folder, and
    hold no key that lets a tool run unasked, adds a connector or hook, or spends AI credits (UNSAFE_KEY). Other keys
    Antigravity keeps there (its sign-in's own) stay; a privacy key (PRIVACY_KEY) stays only as an "off" (a telemetry
    object keeps only its `enabled: false`), and an "off" of the person's own settings wins over an "on" in ENLENS's,
    on every call. On macOS Library/Keychains links to the person's, where the login keychain is. A settings file
    that cannot be read (agy writing it this moment) is left for the next call rather than written from nothing."""
    h = agy_home()
    h.mkdir(parents=True, exist_ok=True)
    if sys.platform == "darwin":
        link = h / "Library" / "Keychains"
        if not link.is_symlink() and not link.exists():
            try:
                link.parent.mkdir(parents=True, exist_ok=True)
                link.symlink_to(user_home() / "Library" / "Keychains", target_is_directory=True)
            except OSError:
                pass
    p = enlens_agy_settings_path()
    raw = None
    if p.exists():
        try:
            raw = json.loads(p.read_text(encoding="utf-8") or "{}")
        except (OSError, ValueError):
            return h   # half written by agy, or not JSON: the next call writes it
    before = raw if isinstance(raw, dict) else {}
    data: dict = {}
    for k, v in before.items():
        if UNSAFE_KEY.search(k):
            continue
        if PRIVACY_KEY.search(k):
            v = _privacy_off(k, v)
            if v is None:
                continue
        data[k] = v
    for k, v in agy_settings().items():
        if PRIVACY_KEY.search(k) and not UNSAFE_KEY.search(k):
            off = _privacy_off(k, v)
            if off is not None:
                data[k] = off
    data["permissions"] = {"allow": [PERMISSION]}
    data["trustedWorkspaces"] = [str(agy_work_folder())]
    if data != raw:
        _write_json(p, data)
    return h


def always_proceeds() -> bool:
    """Whether ENLENS's own Antigravity is set to run every tool without asking (top-level toolPermission
    "always-proceed"): never after prepare_agy_home; checked again just before a run starts."""
    return str(_read_json(enlens_agy_settings_path()).get("toolPermission") or "").strip().lower() == "always-proceed"


ALWAYS_PROCEED = ("ENLENS's own Antigravity settings ({path}) say to run every tool without asking, and ENLENS could "
                  "not write them back. Press Start Antigravity again; if it says this again, delete that file.")


def _is_enlens_work(entry) -> bool:
    """A trusted workspace an earlier ENLENS added to the person's own settings (any data folder's agy-work)."""
    try:
        parts = Path(str(entry)).parts
    except (TypeError, ValueError):
        return False
    return len(parts) >= 2 and tuple(parts[-2:]) == ("claude-runs", "agy-work")


def own_agy_leftovers() -> list[str]:
    """What an earlier ENLENS (0.20.0–0.20.1) wrote into the person's own Antigravity settings and no longer needs: the
    allow rule `mcp(enlens/*)` (which also let the person's own Antigravity use ENLENS's tools unasked) and ENLENS's
    work folders as trusted workspaces. [] when there is nothing."""
    data = agy_settings()
    out = []
    perms = data.get("permissions")
    if isinstance(perms, dict) and isinstance(perms.get("allow"), list) and PERMISSION in perms["allow"]:
        out.append(f'the permission line "{PERMISSION}"')
    trusted = data.get("trustedWorkspaces")
    if isinstance(trusted, list):
        out += [f'the trusted workspace "{t}"' for t in trusted if _is_enlens_work(t)]
    return out


def tidy_own_agy_settings() -> dict:
    """Take out of the person's own Antigravity settings what an earlier ENLENS added (own_agy_leftovers), keeping
    every other key and the file's permissions; a copy of the file as it was is kept as settings.json.enlens-tidy.bak
    first (the person pressed *Remove them*). Returns {"removed": [...]}. Raises ValueError when the file is there but is not JSON (left as it is)."""
    p = agy_settings_path()
    if not p.exists():
        return {"removed": []}
    try:
        data = json.loads(p.read_text(encoding="utf-8") or "{}")
    except (OSError, ValueError) as e:
        raise ValueError(f"Antigravity's settings ({p}) could not be read as JSON, so ENLENS left them as they "
                         f"are: {e}") from e
    if not isinstance(data, dict):
        raise ValueError(f"Antigravity's settings ({p}) are not a JSON object, so ENLENS left them as they are.")
    removed = own_agy_leftovers()
    if not removed:
        return {"removed": []}
    perms = data.get("permissions")
    if isinstance(perms, dict) and isinstance(perms.get("allow"), list):
        perms["allow"] = [x for x in perms["allow"] if x != PERMISSION]
        if not perms["allow"]:
            del perms["allow"]
        if not perms:
            del data["permissions"]
    if isinstance(data.get("trustedWorkspaces"), list):
        data["trustedWorkspaces"] = [t for t in data["trustedWorkspaces"] if not _is_enlens_work(t)]
        if not data["trustedWorkspaces"]:
            del data["trustedWorkspaces"]
    real = p.resolve()   # a settings file linked from elsewhere (dotfiles) is written where it really is
    mode = real.stat().st_mode & 0o777
    shutil.copy2(real, p.with_name(p.name + ".enlens-tidy.bak"))   # the 0.20.0 .bak (before ENLENS) stays as it is
    _write_json(real, data)
    try:
        os.chmod(real, mode)   # a file kept private (it may hold connector tokens) stays so
    except OSError:
        pass
    return {"removed": removed}


def _record_setup(route: str) -> None:
    p = core.home() / "agent-clis.json"
    data = _record_json(p) or {}
    data[route] = {"version": __version__, "python": console_python(), "home": str(core.home()), "at": now()}
    try:   # hunt phase 1.5: written whole, as the run record (another process's `stale` reads it)
        core._write_whole(p, json.dumps(data, indent=2))
    except OSError:
        pass


def _setup_record() -> dict:
    return _record_json(core.home() / "agent-clis.json") or {}


# Hunt phase 1.5 (CI, Windows): the runner rewrites its run record while a helper's connector reads it. Written whole
# (beside, then put in place), a reader on macOS and Linux finds the old file or the new one; on Windows the file system
# gives no such read: a reader that opens it at the moment of the swap is refused (PermissionError), and the writer is
# refused while a reader holds it. Neither side may take that moment for the answer: the writer waits it out
# (`home._write_whole`), and the reader tries again a few times, a few milliseconds apart, before it concludes there
# is no record (`home._read_json`). A short retry is the right design here, and only here: it is the file system's
# own moment, not a wait for something to happen.
def _record_json(p: Path) -> dict | None:
    """A small record of this module (the run record, the set-up record) as a dict: None when there is none, or when
    it stayed unreadable or did not parse after the retries of `home._read_json`."""
    try:
        got = core._read_json(p)
    except (OSError, ValueError):
        return None
    return got if isinstance(got, dict) else None


def set_up(route: str) -> dict:
    """Add ENLENS to the CLI (the person pressed *Add ENLENS to Codex*). Returns {"steps": [{step, ok, text}],
    "status"}; never raises for the CLI's own problems (they are in the steps)."""
    _off()
    title = cli(route).title
    steps: list[dict] = []
    path = find(route)
    if not path:
        steps.append({"step": f"Add ENLENS to {title}", "ok": False,
                      "text": f"{title} was not found on this computer: install it first."})
        return {"steps": steps, "status": status(route, refresh=True)}
    if route == "codex":
        try:
            files = write_codex_files()
            steps.append({"step": "Write the skill $enlens-run and its helpers", "ok": True,
                          "text": f"{files[0]} and {len(files) - 1} helpers in {files[1].parent}"})
        except OSError as e:
            steps.append({"step": "Write the skill $enlens-run and its helpers", "ok": False, "text": str(e)})
        cmd = connector_command()
        env_args = [x for k, v in connector_env(route).items() for x in ("--env", f"{k}={v}")]
        add = [path, "mcp", "add", SERVER, *env_args, "--", *cmd]
        code, text = _run(add, timeout=120)
        if code != 0 and re.search(r"exist", text, re.I):   # an earlier ENLENS's: replaced by this one
            _run([path, "mcp", "remove", SERVER], timeout=60)
            code, text = _run(add, timeout=120)
        steps.append({"step": "Add the ENLENS connector to Codex", "ok": code == 0,
                      "text": text[-600:] or ("Added." if code == 0 else "Codex did not say why.")})
    else:
        try:
            root = write_agy_plugin()
            prepare_agy_work_folder()
            steps.append({"step": "Write the ENLENS plugin", "ok": True, "text": f"Written to {root}"})
        except OSError as e:
            steps.append({"step": "Write the ENLENS plugin", "ok": False, "text": str(e)})
            return {"steps": steps, "status": status(route, refresh=True)}
        code, text = _run([path, "plugin", "install", str(root)], timeout=120)
        steps.append({"step": "Add the plugin to Antigravity", "ok": code == 0,
                      "text": text[-600:] or ("Added." if code == 0 else "Antigravity did not say why.")})
        try:
            steps.append({"step": "Prepare ENLENS's own Antigravity settings", "ok": True,
                          "text": f"Written to {enlens_agy_settings_path()}; your own settings are not changed."})
            prepare_agy_home()
        except OSError as e:
            steps[-1].update(ok=False, text=str(e))
    if all(s["ok"] for s in steps):
        _record_setup(route)
    forget_status(route)
    return {"steps": steps, "status": status(route, refresh=True)}


def stale(route: str) -> str:
    """Why what ENLENS added to the CLI no longer fits this installation ("" when it fits, or when nothing was
    added): another version of ENLENS, another Python or another data folder."""
    rec = _setup_record().get(route)
    if not isinstance(rec, dict):
        return ""
    # hunt phase 1.5: pythonw.exe (the icon's app) and python.exe (a terminal's) of one environment are one Python:
    # started alternately, the connector was set up again at each start
    if not same_python(rec.get("python"), sys.executable):
        return f"it starts the connector with {rec.get('python')}, not with this ENLENS ({sys.executable})"
    if rec.get("home") != str(core.home()):
        return "it uses another data folder"
    if rec.get("version") != __version__:
        return f"it was written by ENLENS {rec.get('version')}, and this is ENLENS {__version__}"
    return ""


def repair() -> dict:
    """Add ENLENS to each CLI again where what was added no longer fits (stale), quietly: run when the app starts, as
    claude_setup.repair. Nothing happens for a CLI ENLENS was never added to, or on a local-only installation."""
    out: dict = {}
    if core.local_only():
        return out
    for route in ROUTES:
        why = stale(route)
        if not why:
            continue
        try:
            r = set_up(route)
            out[route] = {"repaired": all(s["ok"] for s in r["steps"]), "reason": why, "steps": r["steps"]}
        except (OSError, ValueError) as e:
            out[route] = {"repaired": False, "reason": why, "error": str(e)}
    return out


def manual_lines(route: str) -> list[str]:
    """What a person types to add ENLENS by hand (shown under "Prefer to do it yourself?")."""
    cmd = " ".join(f'"{x}"' if " " in x else x for x in connector_command())
    if route == "codex":
        env = " ".join(f'--env {k}="{v}"' for k, v in connector_env(route).items())
        return [f"codex mcp add {SERVER} {env} -- {cmd}"]
    return [f'agy plugin install "{agy_plugin_folder()}"']


# ---------------------------------------------------------------------------------------------
# the runner
# ---------------------------------------------------------------------------------------------
_RUNS: dict[tuple[str, str], dict] = {}
_RUNS_LOCK = threading.Lock()
_START_LOCKS: dict[tuple[str, str], threading.Lock] = {}


def _key(route: str, project: str) -> str:
    return f"{route}-{_run_key(project)}"


def _record_path(route: str, project: str) -> Path:
    return runs_folder() / f"{_key(route, project)}.run.json"


def _log_path(route: str, project: str) -> Path:
    return runs_folder() / f"{_key(route, project)}.log"


def work_folder(route: str, project: str) -> Path:
    """The folder a run's helpers start in: Codex an empty one per project; Antigravity ENLENS's trusted one."""
    if route == "antigravity":
        return prepare_agy_work_folder()
    d = runs_folder() / "work" / _key(route, project)
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_record(run: dict) -> bool:
    """Write the run's record; False when it could not be written (`home._write_whole` waits out a reader that holds
    it on Windows a few times first)."""
    pids = [p["proc"].pid for p in run["procs"] if p["proc"].poll() is None and isinstance(p["proc"].pid, int)]
    try:
        # hunt phase 1: with the project's folder and the model on each helper's command line, by the name it takes
        # batches under (`models`), for the queue to record the model that really read a batch (`started_model`).
        # Hunt phase 1.5: written whole (home._write_whole). Written in place, the file was empty for a moment each
        # time the runner rewrote it (right after a helper starts, and every round), and a helper taking its first
        # batch just then had its batch logged as "not known" in the AI log (seen on CI, Linux, Python 3.10)
        core._write_whole(_record_path(run["route"], run["project"]), json.dumps(
            {"project": run["project"], "route": run["route"], "pid": pids[0] if pids else 0, "pids": pids,
             "started_at": run["started_at"], "t0": run["t0"], "plan": run["plan"] or {},
             "root": run.get("root") or "", "models": run.get("models") or {}}))
        return True
    except OSError:
        return False


def started_model(route: str, root: Path, taken_by: str | None) -> tuple[bool, str | None]:
    """The model on the command line of the helper that takes batches as `taken_by` in the project at `root`, from
    the run records of the runs ENLENS started (each helper has a name of its own, `_spawn`): (True, model), (True,
    None) when ENLENS started it without naming a model (the CLI's own choice), (False, None) when ENLENS did not
    start it (a person's own $enlens-run or /enlens-run: the CLI chose the model, ENLENS cannot tell which)."""
    if not taken_by or route not in ROUTES:
        return False, None
    want = str(Path(root).resolve())
    for attempt in range(3):
        unread = False
        for f in runs_folder().glob(f"{route}-*.run.json"):
            rec = _record_json(f)
            if rec is None:   # listed, then not there or not readable this moment (Windows, the swap): look again
                unread = True
                continue
            models = rec.get("models")
            if isinstance(models, dict) and rec.get("root") == want and taken_by in models:
                m = models[taken_by]
                return True, (str(m) if m else None)
        if not unread:
            break
        time.sleep(0.01 * (attempt + 1))
    return False, None


def _model_on_line(args: list[str]) -> str | None:
    """The model a helper's command names (-m / --model), None when it names none."""
    for i, a in enumerate(args[:-1]):
        if a in ("-m", "--model"):
            return args[i + 1]
    return None


def _read_record(route: str, project: str) -> dict:
    rec = _record_json(_record_path(route, project)) or {}   # (retried while Windows refuses it: `_record_json`)
    return rec if isinstance(rec.get("pids"), list) else {}


def _forget_record(route: str, project: str) -> None:
    try:
        _record_path(route, project).unlink()
    except OSError:
        pass


def _pid_is_helper(pid: int) -> bool:
    """Whether process `pid` is alive and is a helper ENLENS started (its command line holds MARKER)."""
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == "nt":
        from .procs import windows_command_line

        try:
            cmd = windows_command_line(pid)
        except (OSError, AttributeError, ValueError):
            return False
        return cmd is not None and MARKER in cmd
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:
        r = subprocess.run(["ps", "-ww", "-o", "command=", "-p", str(pid)], capture_output=True, text=True,
                           timeout=15)  # console: not on Windows
    except (OSError, subprocess.SubprocessError):
        return True
    return r.returncode == 0 and MARKER in (r.stdout or "")


def _resolve_agy_model(model_id: str, effort: str | None, available: list[str]) -> tuple[str, str | None]:
    """The slug Antigravity takes for a line-up id, and the effort still to pass as --effort (None when the slug
    carries it: `agy models` lists "gemini-4-carbon-high", "…-low")."""
    if not available or model_id in available:
        return model_id, effort
    cands = [a for a in available if a.startswith(model_id + "-")]
    if not cands:
        return model_id, effort
    for suffix in (effort or "medium", "medium", "high", "low"):
        if f"{model_id}-{suffix}" in cands:
            return f"{model_id}-{suffix}", None
    return cands[0], None


def helper_prompt(route: str, project: str, kind: str, model: str, helper: str, taken_by: str | None = None) -> str:
    """One helper process's prompt: MARKER, the helper's own instructions, the batch to take. `taken_by`: the name
    its batches are taken under (`_spawn`: one per helper process, so the run counts each helper's own)."""
    title = cli(route).title
    q = json.dumps
    call = (f"next_tasks(project={q(project, ensure_ascii=False)}, kind={q(kind)}, model={q(model)}, "
            f"helper={q(helper)}, taken_by={q(taken_by or f'{helper} in {title}', ensure_ascii=False)})")
    return (f"{MARKER} You are a helper of ENLENS, started by the ENLENS app to answer its task queue.\n\n"
            f"{helper_body(helper)}\n\n"
            f"Project: {project}. Kind: {kind}. Model: {model}. Helper: {helper}.\n"
            f"Take batches with the ENLENS tool\n{call}\n"
            f"and answer them as your instructions say, until next_tasks returns no claim or you have finished "
            f"{BATCHES} batches. Use only the ENLENS tools next_tasks, submit_answers and release: do not run "
            "commands, read or write files, or search the web. Then report in one line how many tasks you stored and "
            "how many still had problems.")


# The switches without which a helper process is not closed in: ENLENS refuses to start the CLI rather than start it
# without one (a CLI update that renamed one would otherwise quietly open the run up). Each entry: (any of these
# names, what it does, in the refusal's words).
REQUIRED = {
    "antigravity": [(("-p", "--print"), "its headless mode (-p)"),
                    (("--sandbox",), "its sandbox (--sandbox), which keeps its terminal closed")],
}


def missing_switches(route: str, opts: set[str]) -> str:
    """Why this CLI cannot be started closed in ("" when it can): the switches its help does not list."""
    title = cli(route).title
    if not opts:
        return (f"ENLENS could not read the options of this {title} (its --help said nothing ENLENS knows), so it "
                f"cannot tell whether {title} would run closed in. Update {title}, then press Start {title} again.")
    lacking = [words for names, words in REQUIRED.get(route, []) if not set(names) & opts]
    if not lacking:
        return ""
    return (f"This {title} does not offer " + " or ".join(lacking) + f", without which ENLENS does not start it: "
            f"update {title}, then press Start {title} again.")


def run_args(route: str, path: str, prompt: str, model_id: str, effort: str | None, work: Path,
             options: set[str] | None = None, available: list[str] | None = None) -> list[str]:
    """The command of one helper process (only the options this CLI's help lists; never through a shell)."""
    opts = known_options(route, path) if options is None else options
    refused = _cmd_refused(route, path)   # hunt phase 1.5: the prompt never goes through cmd.exe (`_program`)
    if refused:
        raise ValueError(refused)
    if _command_file(_program(path)[0]):   # (review: whatever the shim named, free text never follows a command file)
        raise ValueError(_CMD_WORDS.format(title=cli(route).title, path=path))

    def has(*names):
        return any(n in opts for n in names)

    if route == "codex":
        if not has("-c", "--config"):
            raise ValueError("This Codex does not take settings on its command line (-c), which ENLENS needs to give "
                             "it the ENLENS connector: update Codex, then press Start Codex again.")
        c = "-c" if "-c" in opts else "--config"
        cmd = connector_command()
        args = _program(path) + ["exec"]
        for flag in ("--skip-git-repo-check", "--ephemeral", "--ignore-user-config"):
            if flag in opts:
                args.append(flag)
        if has("-C", "--cd"):
            args += ["-C" if "-C" in opts else "--cd", str(work)]
        if has("-s", "--sandbox"):
            args += ["-s" if "-s" in opts else "--sandbox", "read-only"]
        if model_id and has("-m", "--model"):
            args += ["-m" if "-m" in opts else "--model", model_id]
        settings = []
        if effort:
            settings.append(f"model_reasoning_effort={toml_str(effort)}")
        settings += ['approval_policy="never"', "features.shell_tool=false", 'web_search="disabled"',
                     "features.view_image=false",
                     f"mcp_servers.{SERVER}.command={toml_str(cmd[0])}",
                     f"mcp_servers.{SERVER}.args={toml_list(cmd[1:])}",
                     f"mcp_servers.{SERVER}.env={toml_table(connector_env(route))}",
                     f"mcp_servers.{SERVER}.enabled_tools={toml_list(QUEUE_TOOLS)}",
                     f'mcp_servers.{SERVER}.default_tools_approval_mode="approve"',
                     f"mcp_servers.{SERVER}.tool_timeout_sec=600"]
        for s in settings:
            args += [c, s]
        if "--json" in opts:
            args.append("--json")
        return args + [prompt]
    slug, eff = _resolve_agy_model(model_id, effort, available or [])
    args = _program(path) + ["-p", prompt]
    if "--output-format" in opts:
        args += ["--output-format", "json"]
    if slug and "--model" in opts:
        args += ["--model", slug]
    if eff and "--effort" in opts:
        args += ["--effort", eff]
    for flag in ("--sandbox", "--disable-slash-commands"):
        if flag in opts:
            args.append(flag)
    return args


def read_outcome(route: str, text: str, code: int | None) -> dict:
    """What a finished helper process said: {"ok", "limit" (the sentence, or ""), "signed_out", "message", "refused"
    (the tools the CLI refused it, by name: a helper never needs one)}."""
    title = cli(route).title
    messages: list[str] = []
    refused: list[str] = []
    failed = code not in (0, None)
    if route == "codex":
        for line in (text or "").splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if not isinstance(ev, dict):
                continue
            if ev.get("type") in ("turn.failed", "error"):
                failed = True
                err = ev.get("error")
                msg = (err.get("message") if isinstance(err, dict) else err) or ev.get("message") or ""
                if msg:
                    messages.append(str(msg))
            elif ev.get("type") == "item.completed" and isinstance(ev.get("item"), dict) \
                    and ev["item"].get("type") == "agent_message":
                messages.append(str(ev["item"].get("text") or ""))
    else:
        env = _json_in(text or "", "{")
        if isinstance(env, dict) and env.get("status"):
            if str(env["status"]).upper() != "SUCCESS":
                failed = True
                err = env.get("error")
                messages.append(str((err.get("message") if isinstance(err, dict) else err) or env.get("message") or ""))
            else:
                messages.append(str(env.get("result") or env.get("response") or ""))
            denied = env.get("denied_actions")
            for d in denied if isinstance(denied, list) else []:
                name = (d.get("display_name") or d.get("action")) if isinstance(d, dict) else d
                name = _said(str(name), 60) if isinstance(name, (str, int)) and str(name).strip() else ""
                if name and name not in refused:
                    refused.append(name)
    if not messages and failed:
        messages.append(_said(text or "", 400))
    said = " ".join(m for m in messages if m).strip()
    limit = ""
    if failed and LIMIT_WORDS.search(said):
        m = RESETS_WORDS.search(said)
        limit = f"{title} reached your plan's usage limit" + (f" (it resets {m.group(1).strip()})" if m else "") + "."
    signed_out = bool(failed and not limit and SIGNED_OUT_WORDS.search(said))
    return {"ok": not failed, "limit": limit, "signed_out": signed_out, "message": _said(said, 400),
            "refused": refused}


def _say(run: dict, line: str) -> None:
    try:
        with open(run["log"], "a", encoding="utf-8") as fh:
            fh.write(line.rstrip() + "\n")
    except OSError:
        pass


def _claims_since(ws, taken_by: str, since: str, answered: bool = False) -> int:
    """The batches one helper process took (its own `taken_by`, `_spawn`); with `answered`, those of them with at
    least one answer stored (hunt phase 1: the report said "answered" for batches taken, given back or lapsed too)."""
    return int(ws.scalar("SELECT COUNT(*) FROM task_claims WHERE taken_by=? AND claimed_at >= ?"
                         + (" AND COALESCE(stored, 0) > 0" if answered else ""), (taken_by, since)) or 0)


def _group_waits(run: dict, ws, group: tuple) -> bool:
    """Whether work of a helper's own group (kind, model, helper) still waits for the queue, as next_tasks would hand
    it to that helper. Hunt phase 1: `_reap` asked whether any task of the kind waited, so a helper of one group (the
    stepped-up labels on the middle model) that found its batches taken by its colleague counted as a failed helper
    while the first-step labels waited for another helper."""
    from .taskqueue import (PAGE, _lent, _waiting_count, _waiting_rows, effective_helper, effective_model, mix_kinds,
                            order)

    kind, model, helper = group
    # hunt phase 1.5: a kind the person put on Hold waits for no helper: one that found nothing to take after the Hold
    # did its part, and three such helpers ended the run with "did not answer the queue"
    if kind in order(ws)[1] or _waiting_count(ws, kind) <= 0:
        return False
    r, lent = run.get("router"), mix_kinds()
    if r is None:
        return True

    def mine(rows):
        return any(effective_model(t, r) == model and effective_helper(t, r) == helper and not _lent(t, lent)
                   for t in rows)
    rows = _waiting_rows(ws, kind, PAGE)
    return mine(rows) or (len(rows) >= PAGE and mine(_waiting_rows(ws, kind)))


def _spawn(run: dict, g: dict, path: str, opts: set[str], work: Path, ws) -> None:
    route, project = run["route"], run["project"]
    r = run["router"]
    model_id = r.api_id(g["model"]) or g["model"]
    effort = r.effort(g["kind"])
    if route == "antigravity":   # enforced for every helper, not once a run: a run starts them for hours
        prepare_agy_home()
        _write_agy_connector(work)
        if always_proceeds():
            raise ValueError(ALWAYS_PROCEED.format(path=enlens_agy_settings_path()))
    # hunt phase 1: each helper process takes its batches under a name of its own, so the run counts each helper's
    # batches once: under the group's shared name, two helpers at work at once each counted the other's too (the
    # report said more batches than were taken, and a helper that took nothing did not count as failed). Hunt phase
    # 1.5: the number is taken only by a helper that starts (a refused one skipped a number in the report)
    taken_by = f"{g['helper']} in {cli(route).title} #{run['n'] + 1}"
    prompt = helper_prompt(route, project, g["kind"], g["model"], g["helper"], taken_by)
    args = run_args(route, path, prompt, model_id, effort, work, opts, run["available"])
    run["n"] += 1
    # hunt phase 1: the model on this helper's command line (Antigravity's slug as resolved against `agy models`;
    # none when the CLI takes no --model), written to the run record before it starts, so the queue names it in the
    # AI log and in each answer's record (taskqueue.next_tasks, submit)
    run.setdefault("models", {})[taken_by] = _model_on_line(args)
    if not _write_record(run):
        # hunt phase 1.5: a helper is never started without its model on record (the AI log would say "not known")
        run["n"] -= 1
        raise ValueError("ENLENS could not write its record of this run (another program holds the file in "
                         f"{runs_folder()}). Press Start {cli(route).title} again in a moment.")
    out = runs_folder() / f"{_key(route, project)}-{run['n']}.out"
    fh = open(out, "w", encoding="utf-8")
    try:
        proc = subprocess.Popen(args, cwd=str(work), stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                env=_environ({**connector_env(route), **(agy_env() if route == "antigravity" else {})}),
                                start_new_session=os.name != "nt", **no_window())
    finally:
        fh.close()
    run["procs"].append({"proc": proc, "group": (g["kind"], g["model"], g["helper"]), "out": out, "since": now(),
                         "taken_by": taken_by, "model_id": model_id, "waited": g.get("waiting", 0)})
    run["started"] += 1
    _say(run, f"Started the {g['helper'].removeprefix('enlens-')} helper on {model_id}"
              f"{f' ({effort} effort)' if effort else ''} for {g['kind']}.")
    _write_record(run)


def _reap(run: dict, ws) -> dict | None:
    """Look at the helper processes that ended. Returns {"limit"} or {"fatal"} when the run must end. Without `ws`
    (the run is ending) they are only cleared away."""
    end = None
    for p in [x for x in run["procs"] if x["proc"].poll() is not None]:
        run["procs"].remove(p)
        try:
            text = p["out"].read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        try:
            p["out"].unlink()
        except OSError:
            pass
        if ws is None:
            continue
        o = read_outcome(run["route"], text, p["proc"].returncode)
        took = _claims_since(ws, p["taken_by"], p["since"])
        answered = _claims_since(ws, p["taken_by"], p["since"], answered=True)
        run["batches"] += answered   # the report's "Done: N batches answered"
        if o["refused"]:
            run["refused"].append({"helper": p["taken_by"], "tools": o["refused"], "at": now()})
            _say(run, f"{p['taken_by']} tried to use {', '.join(o['refused'])}, and {cli(run['route']).title} refused "
                      "it. A helper only needs ENLENS's own tools, so text in a passage it read may have told it to "
                      "(look at that batch's passages). It did not run.")
        if o["limit"]:
            end = {"limit": o["limit"]}
            _say(run, o["limit"])
        elif o["signed_out"]:
            end = {"fatal": f"{cli(run['route']).title} is not signed in: sign in once from Settings → AI, then press "
                            f"Start {cli(run['route']).title} again. ({o['message']})"}
        elif not o["ok"] or (took == 0 and _group_waits(run, ws, p["group"])):
            run["failed_in_row"] += 1
            why = o["message"] or "it ended without taking a batch"
            _say(run, f"A helper ended without answering ({p['taken_by']}): {why}")
            if run["failed_in_row"] >= MAX_FAILED:
                end = {"fatal": f"{cli(run['route']).title} did not answer the queue: {MAX_FAILED} helpers in a row "
                                f"ended without taking a batch. The last one said: {why}"}
        else:
            run["failed_in_row"] = 0
            _say(run, f"{p['taken_by']} finished: {answered} batch{'es' if answered != 1 else ''} answered"
                      f"{f' of {took} taken' if answered != took else ''}. {o['message']}".strip())
    _write_record(run)
    return end


def _orchestrate(run: dict) -> None:
    from . import routing, taskqueue

    route, project = run["route"], run["project"]
    title = cli(route).title
    path, opts, work = run["path"], run["options"], run["work"]
    idle = 0
    code = 0
    try:
        while not run["stop"].is_set():
            ws = core.open_project(project)
            end = _reap(run, ws)
            if end:
                code = 1
                if end.get("limit"):
                    run["limit"] = end["limit"]
                else:
                    _say(run, end["fatal"])
                break
            settings = core.load_settings()
            run["router"] = routing.from_settings(settings, route=route)
            run["router"].lineup = routing.lineup_for(settings, route, run["available"] or None)
            st = taskqueue.run_status(ws, project, None, run["plan"]["parallel"], run["plan"]["helpers"], route=route)
            if st.get("local_only"):
                _say(run, "This installation keeps everything on this computer: nothing is handed out.")
                break
            alive = [p for p in run["procs"] if p["proc"].poll() is None]
            per: dict[tuple, int] = {}
            for p in alive:
                per[p["group"]] = per.get(p["group"], 0) + 1
            room = run["plan"]["parallel"] - len(alive)
            started = 0
            for g in st["groups"]:
                want = int(g.get("start") or 0) - per.get((g["kind"], g["model"], g["helper"]), 0)
                while want > 0 and room > 0 and not run["stop"].is_set():
                    _spawn(run, g, path, opts, work, ws)
                    want -= 1
                    room -= 1
                    started += 1
            if not alive and not started:
                idle += 1
                if idle >= IDLE_ROUNDS:
                    break
            else:
                idle = 0
            run["stop"].wait(POLL)
    except ValueError as e:   # a refusal in words (`_spawn`, `run_args`): said as it is, without Python's name for it
        code = 1
        _say(run, f"The run stopped: {e}")
    except Exception as e:  # noqa: BLE001 - the run ends with what happened, the app goes on
        code = 1
        _say(run, f"The run stopped: {type(e).__name__}: {e}")
    finally:
        for p in list(run["procs"]):
            if p["proc"].poll() is None:
                _end_process(p["proc"].pid, p["proc"], wait=5.0)
        try:
            _reap(run, None)
        except Exception:  # noqa: BLE001
            pass
        if run["stop"].is_set():
            run["stopped"] = True
            _say(run, f"{title} stopped. What it had not answered waits again.")
        elif not code:
            _say(run, f"Done: {run['batches']} batch{'es' if run['batches'] != 1 else ''} answered by {title} for "
                      f"{project}, with {run['started']} helper run{'s' if run['started'] != 1 else ''}. The results "
                      "are in the ENLENS app.")
        run["exit_code"] = 1 if code else 0
        run["ended"] = time.time()
        _forget_record(route, project)


def run_state(route: str, project: str) -> dict:
    """Whether the CLI, started from the app, works on this project's queue; the end of its report (the shapes of
    claude_setup.run_state, with `title`, `route` and, at a usage limit, `limit`)."""
    from . import taskqueue

    title = cli(route).title
    with _RUNS_LOCK:
        run = _RUNS.get((route, project))
    if not run:
        rec = _read_record(route, project)
        if not rec:
            return {"running": False, "title": title, "route": route}
        alive = [p for p in rec.get("pids") or [] if _pid_is_helper(p)]
        if not alive:
            _forget_record(route, project)
            return {"running": False, "title": title, "route": route}
        plan = rec.get("plan") or {}
        return {"running": True, "started_at": rec.get("started_at", ""), "title": title, "route": route,
                "seconds": int(time.time() - float(rec.get("t0") or time.time())), "exit_code": None, "report": "",
                "stopped": False, "parallel": plan.get("parallel"),
                "helpers": {taskqueue.short_helper(h): n for h, n in (plan.get("helpers") or {}).items() if n} or None}
    running = run["exit_code"] is None
    tail = ""
    if not running:
        try:
            tail = run["log"].read_text(encoding="utf-8", errors="replace")[-1200:].strip()
        except OSError:
            pass
    plan = run.get("plan") or {}
    out = {"running": running, "started_at": run["started_at"], "seconds": int(time.time() - run["t0"]),
           "exit_code": run["exit_code"], "report": tail, "stopped": run.get("stopped", False), "title": title,
           "route": route, "parallel": plan.get("parallel"),
           "helpers": {taskqueue.short_helper(h): n for h, n in (plan.get("helpers") or {}).items() if n} or None,
           "helpers_running": sum(1 for p in run["procs"] if p["proc"].poll() is None)}
    if run.get("refused"):
        out["refused"] = list(run["refused"])
    if run.get("limit") and not running:
        out["limit"] = run["limit"]
    return out


def _start_lock(route: str, project: str) -> threading.Lock:
    with _RUNS_LOCK:
        return _START_LOCKS.setdefault((route, project), threading.Lock())


def start_run(route: str, project: str, parallel=None, helpers=None) -> dict:
    """Start the CLI on the project's queue (the person pressed *Start Codex*): one runner per project and route.
    `parallel`, `helpers`: the run's plan (taskqueue.run_plan; the speed of Settings without them). Raises ValueError
    with a plain reason when it cannot start."""
    from . import taskqueue

    _off()
    a = cli(route)
    with _start_lock(route, project):
        st = run_state(route, project)
        if st.get("running"):
            return st
        plan = taskqueue.run_plan(parallel, helpers)
        path = find(route)
        if not path:
            raise ValueError(f"{a.title} was not found on this computer. Set it up in Settings → AI.")
        if _cmd_refused(route, path):   # said at Start, not by the first helper
            raise ValueError(_cmd_refused(route, path))
        info = status(route)
        if info.get("signed_in") is False:
            info = status(route, refresh=True)
            if info.get("signed_in") is False:
                raise ValueError(f"{a.title} is not signed in yet: sign in once from Settings → AI, then press "
                                 f"Start {a.title} again.")
        if info.get("connector") is False or stale(route) or (route == "antigravity" and not agy_plugin_folder().exists()):
            set_up(route)   # ENLENS is added on the first start, as Claude Code's plugin is
        if route == "antigravity":
            prepare_agy_home()
            if always_proceeds():
                raise ValueError(ALWAYS_PROCEED.format(path=enlens_agy_settings_path()))
        opts = known_options(route, path)
        if route == "codex" and not ({"-c", "--config"} & opts):
            raise ValueError("This Codex does not take settings on its command line (-c), which ENLENS needs to give "
                             "it the ENLENS connector: update Codex, then press Start Codex again.")
        missing = missing_switches(route, opts)
        if missing:
            raise ValueError(missing)
        log = _log_path(route, project)
        log.write_text("", encoding="utf-8")
        run = {"route": route, "project": project, "plan": plan, "path": path, "options": opts,
               "work": work_folder(route, project), "available": list(info.get("models_available") or []),
               "procs": [], "stop": threading.Event(), "log": log, "t0": time.time(), "started_at": now(),
               "exit_code": None, "stopped": False, "limit": None, "n": 0, "started": 0, "batches": 0,
               "failed_in_row": 0, "router": None, "refused": [],
               "root": str(core.project_path(project).resolve()), "models": {}}
        with _RUNS_LOCK:
            _RUNS[(route, project)] = run
        _write_record(run)
        run["thread"] = threading.Thread(target=_orchestrate, args=(run,), daemon=True,
                                         name=f"enlens-{route}-{_run_key(project)}")
        run["thread"].start()
        return run_state(route, project)


def stop_run(route: str, project: str) -> dict:
    """Stop the CLI started from the app (also the helpers an earlier copy of the app started). Batches it had taken
    return to the queue (the caller releases them; claims lapse otherwise)."""
    with _RUNS_LOCK:
        run = _RUNS.get((route, project))
    if run:
        if run["exit_code"] is None:
            run["stop"].set()
            for p in list(run["procs"]):
                if p["proc"].poll() is None:
                    _end_process(p["proc"].pid, p["proc"], wait=5.0)
            t = run.get("thread")
            if t is not None:
                t.join(30)
    else:
        rec = _read_record(route, project)
        for pid in rec.get("pids") or []:
            if _pid_is_helper(pid):
                _end_process(pid, wait=5.0, alive=_pid_is_helper)
        if rec:
            _forget_record(route, project)
    return run_state(route, project)


def stop_all_runs() -> list[dict]:
    """Stop every run of every agent CLI, this app's and an earlier one's (Quit, Update and restart). Returns
    [{"project", "started_at", "route"}] of the runs that were working."""
    with _RUNS_LOCK:
        keys = set(_RUNS)
    try:
        for f in runs_folder().glob("*.run.json"):
            rec = _record_json(f)
            if isinstance(rec, dict) and rec.get("route") in ROUTES and rec.get("project"):
                keys.add((rec["route"], str(rec["project"])))
    except OSError:
        pass
    stopped = []
    for route, name in sorted(keys):
        before = run_state(route, name)
        if before.get("running"):
            stop_run(route, name)
            stopped.append({"project": name, "started_at": before.get("started_at", ""), "route": route})
    # hunt phase 1.5: a `codex login` still waiting for the browser is this app's too: it does not outlive Quit (the
    # person presses Sign in again after the next start)
    for route, p in list(_LOGIN.items()):
        if p.poll() is None:
            _end_process(p.pid, p, wait=5.0)
        _LOGIN.pop(route, None)
    return stopped


def any_running(project: str) -> dict | None:
    """The state of a run of any agent CLI working on this project now, or None."""
    for route in ROUTES:
        st = run_state(route, project)
        if st.get("running"):
            return st
    return None


def reset_for_tests() -> None:
    """Stop and forget every run and cached answer (the tests' clean slate)."""
    with _RUNS_LOCK:
        runs = list(_RUNS.values())
        _RUNS.clear()
        _START_LOCKS.clear()
    for run in runs:
        run["stop"].set()
        for p in list(run["procs"]):
            if p["proc"].poll() is None:
                _end_process(p["proc"].pid, p["proc"], wait=5.0)
        t = run.get("thread")
        if t is not None:
            t.join(10)
    for p in _LOGIN.values():
        if p.poll() is None:
            _end_process(p.pid, p, wait=5.0)
    _LOGIN.clear()
    _STATUS.clear()
    _OPTIONS.clear()
