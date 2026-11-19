"""Setting up the ENLENS plugin for Claude Code (0.8, G2): `enlens claude-setup`.

The plugin ships inside the ENLENS package (`claude_plugin/`). Set-up writes it, as a one-plugin marketplace, into
ENLENS's own data folder (`<ENLENS_HOME>/claude-plugin`), with the connector started by this very Python and this
data folder, then checks that the connector starts and offers the queue tools.

0.9 (subscription first): when the `claude` program is found, set-up also adds the plugin to Claude Code itself, by
running the same two commands a person would type (`claude plugin marketplace add …`, `claude plugin install …`);
otherwise it prints them. `status()` says what is ready (Claude Code found, signed in, the plugin added), and
`start_run()` starts Claude Code for one project's queue, in the background, when the researcher presses
"Start Claude Code" in the app (`claude -p "/enlens-run:enlens-run <project>"`, allowed only the ENLENS queue tools
and its helpers). ENLENS still never sees the Claude login: Claude Code uses its own.

Layout written:

    claude-plugin/.claude-plugin/marketplace.json         the marketplace "enlens"
    claude-plugin/plugins/enlens-run/.claude-plugin/plugin.json
    claude-plugin/plugins/enlens-run/SKILL.md            /enlens-run (the orchestrator)
    claude-plugin/plugins/enlens-run/agents/*.md         the seven helpers, each with its model and the queue tools only
    claude-plugin/plugins/enlens-run/.mcp.json           the ENLENS connector (enlens-mcp)
    claude-plugin/plugins/enlens-run/README.md
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

from . import __version__
from . import home as core
from .procs import console_python, no_window, program_args, same_python
from .store import now
from .update import semver as _semver

PLUGIN = "enlens-run"        # the plugin's name: its root skill is /enlens-run
MARKETPLACE = "enlens"
SERVER = "enlens"            # the connector's name inside the plugin
# Claude Code names a plugin's MCP tools mcp__plugin_<plugin>_<server>__<tool>
TOOL_PREFIX = f"mcp__plugin_{PLUGIN}_{SERVER}__"
QUEUE_TOOLS = ("queue_status", "next_tasks", "submit_answers", "release")
HELPERS = ("enlens-labeller", "enlens-linker", "enlens-namer", "enlens-reader", "enlens-extractor", "enlens-checker",
           "enlens-auditor")
SOURCE = Path(__file__).with_name("claude_plugin")


def folder() -> Path:
    return core.home() / "claude-plugin"


def plugin_folder() -> Path:
    return folder() / "plugins" / PLUGIN


def commands(where: Path | None = None) -> list[str]:
    where = where or folder()
    return [f'claude plugin marketplace add "{where}"', f"claude plugin install {PLUGIN}@{MARKETPLACE}"]


def mcp_config() -> dict:
    # hunt phase 1.5: the console python.exe, also when the app (pythonw.exe) writes it (`procs.console_python`)
    return {"mcpServers": {SERVER: {"command": console_python(), "args": ["-m", "enlens_claims.mcp_server"],
                                    "env": {"ENLENS_HOME": str(core.home())}}}}


def _fill(text: str) -> str:
    # 0.15: a release candidate's number in semantic-versioning form (0.15.0-rc.1), which a plugin's version is
    return text.replace("{{TOOL_PREFIX}}", TOOL_PREFIX).replace("{{VERSION}}", _semver(__version__))


def write_plugin(target: Path | None = None) -> Path:
    """Write the marketplace with the plugin (replacing an earlier copy). Returns the marketplace folder."""
    if core.local_only():
        raise ValueError("This installation keeps everything on this computer (local only): the Claude Code plugin is "
                         "not available here.")
    root = target or folder()
    plug = root / "plugins" / PLUGIN
    if plug.exists():
        shutil.rmtree(plug)
    (root / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (plug / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (plug / "agents").mkdir(parents=True, exist_ok=True)
    (root / ".claude-plugin" / "marketplace.json").write_text(_fill((SOURCE / "marketplace.json").read_text("utf-8")),
                                                               encoding="utf-8")
    (plug / ".claude-plugin" / "plugin.json").write_text(_fill((SOURCE / "plugin.json").read_text("utf-8")),
                                                          encoding="utf-8")
    for name in ("SKILL.md", "README.md"):
        (plug / name).write_text(_fill((SOURCE / name).read_text("utf-8")), encoding="utf-8")
    for f in sorted((SOURCE / "agents").glob("*.md")):
        (plug / "agents" / f.name).write_text(_fill(f.read_text("utf-8")), encoding="utf-8")
    from . import taskkinds  # 0.13.6: an add-on kind's own helper agent

    for h, f in taskkinds.addon_helpers().items():
        (plug / "agents" / f"{h}.md").write_text(_fill(Path(f).read_text("utf-8")), encoding="utf-8")
    (plug / ".mcp.json").write_text(json.dumps(mcp_config(), indent=2), encoding="utf-8")
    return root


def frontmatter(path: Path) -> dict:
    """The YAML front matter of a skill or agent file, read as `key: value` lines (all this plugin uses)."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end < 0:  # never closed: no front matter (check_files then lists what is missing instead of failing)
        return {}
    head = text[4:end]
    out = {}
    for line in head.splitlines():
        if ":" in line and not line.startswith(" "):
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip().strip('"')
    return out


def check_files(root: Path | None = None) -> list[str]:
    """Problems with the written plugin (empty when every file is as Claude Code expects)."""
    root = root or folder()
    plug = root / "plugins" / PLUGIN
    problems = []
    for p in (root / ".claude-plugin" / "marketplace.json", plug / ".claude-plugin" / "plugin.json", plug / ".mcp.json"):
        try:
            json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            problems.append(f"{p.name}: {e}")
    skill = frontmatter(plug / "SKILL.md") if (plug / "SKILL.md").exists() else {}
    if skill.get("name") != PLUGIN:
        problems.append("SKILL.md: the skill must be named enlens-run")
    allowed = set(TOOL_PREFIX + t for t in QUEUE_TOOLS)
    from . import taskkinds

    for h in list(HELPERS) + list(taskkinds.addon_helpers()):  # 0.13.6: and an add-on kind's own helper
        f = plug / "agents" / f"{h}.md"
        if not f.exists():
            problems.append(f"agents/{h}.md is missing")
            continue
        fm = frontmatter(f)
        for key in ("name", "description", "model", "tools"):
            if not fm.get(key):
                problems.append(f"agents/{h}.md has no {key}")
        tools = {t.strip() for t in fm.get("tools", "").split(",") if t.strip()}
        if tools - allowed:
            problems.append(f"agents/{h}.md may use more than the ENLENS queue tools: {sorted(tools - allowed)}")
    return problems


def check_connector(timeout: float = 60) -> dict:
    """Start the connector as Claude Code will (this Python, `-m enlens_claims.mcp_server`) and list its tools."""
    import asyncio

    try:
        from mcp import Client, StdioServerParameters  # noqa: F401
    except ImportError:
        return {"ok": False, "error": "The connector needs the MCP package: pip install 'enlens-claims[connector]'"}
    cfg = mcp_config()["mcpServers"][SERVER]

    async def run():
        from mcp import Client, StdioServerParameters

        params = StdioServerParameters(command=cfg["command"], args=cfg["args"], env={**cfg["env"]})
        async with Client(params) as c:
            return sorted(t.name for t in (await c.list_tools()).tools)

    try:
        names = asyncio.run(asyncio.wait_for(run(), timeout))
    except Exception as e:  # noqa: BLE001 - report it plainly
        return {"ok": False, "error": f"The connector did not start: {type(e).__name__}: {e}"}
    missing = [t for t in QUEUE_TOOLS if t not in names]
    return {"ok": not missing, "tools": names, "missing": missing}


def setup_info() -> dict:
    """For the app: whether the plugin is written for this installation, and the lines to type."""
    plug = plugin_folder()
    ready = False
    try:
        cfg = json.loads((plug / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"][SERVER]
        ready = same_python(cfg.get("command"), sys.executable) and (plug / "SKILL.md").exists()
    except (OSError, ValueError, KeyError):
        ready = False
    return {"folder": str(folder()), "ready": ready, "commands": commands(), "terminal": "enlens claude-setup",
            "installer": installer_command()["line"], "docs": INSTALL_DOCS,
            "in_claude_code": [f'/plugin marketplace add "{folder()}"', f"/plugin install {PLUGIN}@{MARKETPLACE}"],
            "local_only": core.local_only()}


# ---------------------------------------------------------------------------------------------
# 0.9: finding Claude Code, adding the plugin to it, and starting it for a project's queue
# ---------------------------------------------------------------------------------------------
SLASH = f"/{PLUGIN}:{PLUGIN}"   # how Claude Code names the plugin's skill (typing /enlens-run offers it)


def find_claude() -> str:
    """The `claude` program: ENLENS_CLAUDE, the PATH, or where its installers put it. "" when not found."""
    env = os.environ.get("ENLENS_CLAUDE", "").strip()
    if env:
        return env if Path(env).exists() else ""
    found = shutil.which("claude")
    if found:
        return found
    h = Path.home()
    for c in (h / ".claude" / "local" / "claude", h / ".local" / "bin" / "claude", h / ".local" / "bin" / "claude.exe",
              Path("/opt/homebrew/bin/claude"),
              Path("/usr/local/bin/claude"), h / ".npm-global" / "bin" / "claude",
              h / "AppData" / "Roaming" / "npm" / "claude.cmd"):
        if c.exists():
            return str(c)
    return ""


def _cmd(path: str) -> list[str]:
    """How to call the program found: a Python script (the tests' and dev server's stand-in) runs with this Python."""
    return [sys.executable, path] if path.endswith(".py") else [path]


def _run(args: list[str], timeout: float = 60) -> tuple[int, str]:
    """Run Claude Code and return its exit code and what it wrote. 0.15.2: what it writes is UTF-8 (on Windows too),
    and is read as such: in this Python's code page a path like C:\\Users\\Ábel came back garbled, or stopped the
    status with an error (the second byte of "Á" is no letter in Windows-1252). 0.15.3: without a window on
    Windows: the app's status ran it three times every half minute, and each run flashed a console window."""
    args = _cmd(args[0]) + list(args[1:])
    try:  # hunt phase 1.5: npm's claude.cmd runs through cmd.exe, which reads the line again (`program_args`)
        r = subprocess.run(program_args(args), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                           cwd=str(core.home()), stdin=subprocess.DEVNULL, **no_window())
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        return 1, f"{type(e).__name__}: {e}"
    return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()


_STATUS: dict = {"at": 0.0, "value": None}


def _said(value, limit: int = 200) -> str:
    """A text Claude Code reported, made safe to show: a string, on one line, without control characters, not too long."""
    if not isinstance(value, str):
        return ""
    return re.sub(r"[\x00-\x1f\x7f]+", " ", value).strip()[:limit]


def account_words(st: dict) -> str:
    """0.13.4: which account Claude Code is signed in to, in one line ("you@uni.nl, Team plan (Uni)"), or "" when it
    is not signed in or does not say. The organisation is named only on a Team or Enterprise plan: on Pro and Max it
    is usually Claude's own "…'s Organization"."""
    if not st.get("signed_in"):
        return ""
    plan = str(st.get("plan") or "")
    words = [st.get("email") or ""]
    if plan:
        org = st.get("org_name") if plan in ("team", "enterprise") else ""
        words.append(f"{plan.capitalize()} plan" + (f" ({org})" if org else ""))
    elif str(st.get("auth_method") or "").lower() in ("api_key", "console"):
        words.append("a Claude Console account")
    return ", ".join(w for w in words if w)


def note_plan(plan: str) -> str:
    """0.13.10: keep the tier of the plan Claude Code is signed in with (Settings' claude_plan_detected), so the
    recommended model of each task follows it everywhere, also in the connector Claude Code starts. Written only when
    it changed; a signed-out Claude Code says nothing and changes nothing. Returns the tier."""
    from . import routing

    tier = routing.plan_tier(plan)
    try:
        if core.load_settings().get("claude_plan_detected", "") != tier:
            core.update_settings({"claude_plan_detected": tier})
    except (ValueError, OSError):  # e.g. a settings file that cannot be written: the recommendations stay as they were
        pass
    return tier


def status(refresh: bool = False) -> dict:
    """What is ready for Claude Code, for the app's set-up checklist (cached for half a minute):
    `found` (and `path`, `version`), `signed_in` (True, False, or None when Claude Code does not say), the plugin
    `written` for this installation and `installed` in Claude Code (None when that could not be read), and `ready`
    (found and installed: the app can start Claude Code)."""
    if not refresh and _STATUS["value"] is not None and time.time() - _STATUS["at"] < 30:
        return _STATUS["value"]
    info = setup_info()
    out = {"found": False, "path": "", "version": "", "signed_in": None, "written": info["ready"], "installed": None,
           "plugin_version": "", "ready": False, "local_only": core.local_only(), "email": "", "org_name": "",
           "auth_method": ""}
    path = "" if out["local_only"] else find_claude()
    if path:
        out.update(found=True, path=path)
        code, text = _run([path, "--version"], timeout=20)
        if code == 0:
            out["version"] = text.splitlines()[0].strip() if text else ""
        code, text = _run([path, "auth", "status"], timeout=20)
        try:
            auth = json.loads(text[text.index("{"):])
            out["signed_in"] = bool(auth.get("loggedIn"))
            # 0.11: the kind of plan, when Claude Code says it (for "What happens to the text Claude reads")
            plan = str(auth.get("subscriptionType") or auth.get("subscription") or auth.get("plan") or "").lower()
            out["account"] = ("personal" if plan in ("pro", "max", "free") else
                              "commercial" if plan in ("team", "enterprise") else
                              "commercial" if str(auth.get("authMethod") or "").lower() in ("api_key", "console") else "")
            out["plan"] = plan
            if out["signed_in"]:
                note_plan(plan)
            # 0.13.4: which account Claude Code is signed in to, for the sidebar and Settings → AI. Only what Claude
            # Code itself reports (the address and the organisation); the login stays with Claude Code.
            if out["signed_in"]:
                out.update(email=_said(auth.get("email") or auth.get("emailAddress")),
                           org_name=_said(auth.get("orgName") or auth.get("organizationName")),
                           auth_method=_said(auth.get("authMethod"), 40))
        except (ValueError, AttributeError):
            out["signed_in"] = None
        code, text = _run([path, "plugin", "list", "--json"], timeout=30)
        try:
            plugins = json.loads(text[text.index("["):])
            mine = [p for p in plugins if p.get("id") == f"{PLUGIN}@{MARKETPLACE}"]
            out["installed"] = bool(mine and mine[0].get("enabled", True))
            out["plugin_version"] = (mine[0].get("folderVersion") or mine[0].get("version") or "") if mine else ""
        except (ValueError, AttributeError):
            out["installed"] = None
    out["ready"] = bool(out["found"] and out["written"] and out["installed"] is not False)
    _STATUS.update(at=time.time(), value=out)
    return out


def install(check: bool = False) -> dict:
    """Prepare the plugin and, when Claude Code is found, add it to Claude Code (the two commands of `commands()`).
    Returns {"steps": [{"step", "ok", "text"}], "status": status(), "commands": [...]}; never raises for Claude Code's
    own problems (they are reported in the steps)."""
    steps = []
    root = write_plugin()
    problems = check_files(root)
    steps.append({"step": "Prepare the ENLENS plugin", "ok": not problems,
                  "text": "; ".join(problems) or f"Written to {root}"})
    if check:
        r = check_connector()
        steps.append({"step": "Start the ENLENS connector", "ok": r["ok"],
                      "text": r.get("error") or ("Offers the queue tools." if r["ok"] else
                                                 "Missing: " + ", ".join(r.get("missing", [])))})
    path = find_claude()
    if not path:
        steps.append({"step": "Add the plugin to Claude Code", "ok": False,
                      "text": "Claude Code was not found on this computer. Install it from claude.com/claude-code, "
                              "then press Set up again (or type the two lines below in a terminal)."})
    else:
        again = False
        for line, args in zip(commands(root), ([path, "plugin", "marketplace", "add", str(root)],
                                               [path, "plugin", "install", f"{PLUGIN}@{MARKETPLACE}"])):
            code, text = _run(args, timeout=120)
            ok = _took(code, text)
            again |= ok and code != 0
            steps.append({"step": line, "ok": ok, "text": re.sub(r"\x1b\[[0-9;]*m", "", text)[-600:]})
            if not ok:
                break
        if again and all(x["ok"] for x in steps):  # already there: the files just written reach it by the refresh
            for s in refresh_in_claude_code(path):
                steps.append({"step": "claude " + " ".join(s["args"]), "ok": s["ok"], "text": s["text"]})
    if path and all(x["ok"] for x in steps):
        _forget_refused()  # (INSTALL-5: Claude Code took the plugin; nothing to try again at the next start)
    _STATUS["value"] = None
    return {"steps": steps, "status": status(refresh=True), "commands": commands(root)}


# -- starting Claude Code for one project's queue (the "Start Claude Code" button) ------------------------
_RUNS: dict[str, dict] = {}
_RUNS_LOCK = threading.Lock()


# 0.11: the built-in tools a headless run may not use. --allowedTools only pre-approves tools; read-only tools such as
# Read and Grep need no approval inside the working folder, so the run is denied every tool that reads, writes or
# fetches files or runs commands (deny rules hold for the helper agents too), and it starts in an empty folder
# (`work_folder`), away from the projects' databases, which hold every document's text.
DENIED_TOOLS = ("Bash", "BashOutput", "KillShell", "Read", "Write", "Edit", "MultiEdit", "NotebookEdit", "NotebookRead",
                "Glob", "Grep", "LS", "WebFetch", "WebSearch")


def _run_key(project: str) -> str:
    """A file-name-safe name of one project, different for every project name ("a b" and "a_b" stay apart)."""
    import hashlib

    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", project).strip("_") or "project"
    return f"{slug[:40]}-{hashlib.sha1(project.encode('utf-8')).hexdigest()[:6]}"


def work_folder(project: str = "") -> Path:
    """The empty folder a headless run starts in (anything found in it is removed first). 0.14.3: one for each project,
    so starting Claude Code on a second project never empties the folder the first one's run works in."""
    d = core.home() / "claude-runs" / "work" / (_run_key(project) if project else "shared")
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True, exist_ok=True)
    return d


# The box: Claude Code started by ENLENS needs nothing from the computer but the passages in its tasks, which reach it
# through the ENLENS connector. With a Claude Code that knows these options (they are read from `claude --help`):
# --tools Agent       the only built-in tool is the one that starts the helpers: no tool that reads, writes or searches
#                     files, runs commands or browses exists in the run at all (a list of tools to deny misses the ones
#                     a later Claude Code adds);
# --restricted        Claude Code ignores the person's own Claude Code settings, hooks and CLAUDE.md files, so nothing
#                     of theirs is read into the run or sent with it, and only ENLENS's plugin is loaded;
# --plugin-dir        the plugin as ENLENS wrote it, for this run only (the person's other plugins stay out);
# ENABLE_CLAUDEAI_MCP_SERVERS=false   the connectors of the person's claude.ai account stay out as well.
# An older Claude Code that lacks them runs as before: denied the tools in DENIED_TOOLS, in an empty folder.
BOX_ENV = {"ENABLE_CLAUDEAI_MCP_SERVERS": "false"}
_OPTIONS: dict = {}


def known_options(claude: str) -> set[str]:
    """The long options this Claude Code knows, from `claude --help` (read once per program file, which an update
    replaces). Empty when its help cannot be read: then nothing new is passed to it."""
    try:
        st = Path(claude).stat()
        key = (claude, st.st_size, st.st_mtime_ns)
    except OSError:
        return set()
    if key not in _OPTIONS:
        code, text = _run([claude, "--help"], timeout=30)
        _OPTIONS[key] = set(re.findall(r"(?<![\w-])--[A-Za-z][A-Za-z-]+", text)) if code == 0 else set()
    return _OPTIONS[key]


def box_args(claude: str, run: bool = True, options: set[str] | None = None) -> list[str]:
    """The options that close Claude Code in (see above). `run`: a headless run of the queue, which also loads the
    ENLENS plugin alone; otherwise the sign-in window, which needs no plugin."""
    opts = known_options(claude) if options is None else options
    args = ["--tools", "Agent"] if "--tools" in opts else ["--disallowedTools", ",".join(DENIED_TOOLS)]
    if run and {"--restricted", "--plugin-dir"} <= opts and (plugin_folder() / ".mcp.json").exists():
        args += ["--restricted", "--plugin-dir", str(plugin_folder())]
    return args


def run_args(project: str, claude: str = "", plan: dict | None = None, options: set[str] | None = None) -> list[str]:
    """The command that answers one project's queue headless, allowed only the ENLENS queue tools and the helpers, and
    without any built-in tool that reads files, runs commands or fetches pages (box_args). `plan`
    (taskqueue.run_plan): how many helpers at once, and which (0.13.10). `options`: what this Claude Code knows
    (known_options, read when not given)."""
    from . import taskqueue

    claude = claude or find_claude() or "claude"
    tools = ["Agent"] + [TOOL_PREFIX + t for t in QUEUE_TOOLS]
    quoted = '"' + project.replace('"', "") + '"'
    prompt = f"{SLASH} {quoted}"
    if plan:
        prompt += f" --parallel {int(plan['parallel'])}"
        if plan.get("helpers"):
            prompt += f" --helpers {taskqueue.helpers_arg(plan['helpers'])}"
    return _cmd(claude) + ["-p", prompt, "--output-format", "text", *box_args(claude, options=options),
                           "--allowedTools", *tools]


def _log_path(project: str) -> Path:
    d = core.home() / "claude-runs"
    d.mkdir(parents=True, exist_ok=True)
    # named as the run's record and its work folder are (`_run_key`): two projects whose names differ only in
    # accented letters or punctuation ("Előadás", "El ad s") shared one log, and one run's start emptied the other's
    return d / f"{_run_key(project)}.log"


# 0.14.3: every run's process id is written under the data folder (claude-runs/<project>.run.json), because _RUNS
# lives only in this app's memory: a run goes on (in its own session) when the app quits or restarts, and the app
# that starts next must know it still works on the project's queue: show it as running, be able to stop it, and not
# start a second one beside it.
def _record_path(project: str) -> Path:
    return core.home() / "claude-runs" / f"{_run_key(project)}.run.json"


def _write_record(project: str, pid: int, started_at: str, t0: float, plan: dict | None) -> None:
    try:
        _record_path(project).parent.mkdir(parents=True, exist_ok=True)
        _record_path(project).write_text(json.dumps({"project": project, "pid": pid, "started_at": started_at,
                                                     "t0": t0, "plan": plan or {}}), encoding="utf-8")
    except OSError:
        pass


def _read_record(project: str) -> dict:
    try:
        rec = json.loads(_record_path(project).read_text(encoding="utf-8"))
        return rec if isinstance(rec, dict) and isinstance(rec.get("pid"), int) else {}
    except (OSError, ValueError):
        return {}


def _forget_record(project: str, pid: int | None = None) -> None:
    rec = _read_record(project)
    if pid is None or rec.get("pid") == pid:
        try:
            _record_path(project).unlink()
        except OSError:
            pass


def _runs_this(cmd: str, project: str | None) -> bool:
    """Whether a command line is a Claude Code run of ENLENS, and with `project` the run of that project (run_args puts
    its name in quotes after the slash command; Windows shows those quotes as \\", and a run started through cmd.exe
    for npm's claude.cmd as "", `procs.batch_arg`)."""
    if SLASH not in cmd:
        return False
    if project is None:
        return True
    name = project.replace('"', "")
    return (f'{SLASH} "{name}"' in cmd or f'{SLASH} \\"{name}\\"' in cmd
            or f'{SLASH} ""{name}""' in cmd)


def _pid_runs_enlens(pid: int, project: str | None = None) -> bool:
    """Whether process `pid` is alive and is a Claude Code run of ENLENS (not another program that was given the number
    since), and with `project`, that project's run. Hunt phase 1 (INSTALL-2's sweep): a record whose number another
    project's run was given since counted as this project's, so Stop ended that other run; and without `ps` the
    number alone counted, so Stop could end any program: a number proves nothing, only the command line does."""
    if pid <= 0:
        return False
    # 0.15.7: on Windows by its command line too (it was the number alone, from tasklist). Hunt phase 1.5: one reader
    # for every system (`procs.command_line`: Windows' interface, ps, then /proc where there is no ps)
    from .procs import command_line

    cmd = command_line(pid)
    return bool(cmd) and _runs_this(cmd, project)


def _end_process(pid: int, proc=None, wait: float = 10.0, alive=None) -> None:
    """End a run: its whole process group (the helpers it started too) on Mac and Linux, the process tree on Windows.
    `alive(pid)`: whether the process is still the run's (stage 2: an agent CLI's helper, agentcli.py), when there is
    no `proc` to ask."""
    def gone() -> bool:
        if proc is not None:
            return proc.poll() is not None
        return not (alive or _pid_runs_enlens)(pid)

    if os.name == "nt":
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=30, **no_window())
        except (OSError, subprocess.SubprocessError):
            pass
        # 2026-11-12: taskkill returns before the process has ended; on a busy computer Stop then still reported the
        # run as working. Wait for it, as below on macOS and Linux.
        t0 = time.time()
        while time.time() - t0 < wait and not gone():
            time.sleep(0.1)
        return
    import signal

    def send(sig) -> None:
        try:
            try:
                if os.getpgid(pid) == pid:  # started in its own session (start_run): the group is the run
                    os.killpg(pid, sig)
                    return
            except OSError:
                pass
            os.kill(pid, sig)
        except OSError:
            pass

    send(signal.SIGTERM)
    t0 = time.time()
    while time.time() - t0 < wait:
        if gone():
            return
        time.sleep(0.1)
    send(signal.SIGKILL)
    t0 = time.time()
    while time.time() - t0 < 3 and not gone():
        time.sleep(0.1)


def run_state(project: str) -> dict:
    """Whether Claude Code, started from the app, is working on this project's queue; the end of its report."""
    from . import taskqueue

    with _RUNS_LOCK:
        r = _RUNS.get(project)
    if not r:
        rec = _read_record(project)  # 0.14.3: a run an earlier app started and that still works
        if not rec:
            return {"running": False}
        if not _pid_runs_enlens(rec["pid"], project):
            _forget_record(project, rec["pid"])
            return {"running": False}
        plan = rec.get("plan") or {}
        return {"running": True, "started_at": rec.get("started_at", ""),
                "seconds": int(time.time() - float(rec.get("t0") or time.time())), "exit_code": None, "report": "",
                "stopped": False, "parallel": plan.get("parallel"),
                "helpers": {taskqueue.short_helper(h): n for h, n in (plan.get("helpers") or {}).items() if n} or None}
    code = r["proc"].poll()
    if code is not None:
        _forget_record(project, getattr(r["proc"], "pid", None))
    tail = ""
    try:
        tail = r["log"].read_text(encoding="utf-8", errors="replace")[-1200:].strip()
    except OSError:
        pass
    plan = r.get("plan") or {}
    return {"running": code is None, "started_at": r["started_at"], "seconds": int(time.time() - r["t0"]),
            "exit_code": code, "report": tail if code is not None else "", "stopped": r.get("stopped", False),
            "parallel": plan.get("parallel"),
            "helpers": {taskqueue.short_helper(h): n for h, n in (plan.get("helpers") or {}).items() if n} or None}


_START_LOCKS: dict[str, threading.Lock] = {}


def _start_lock(project: str) -> threading.Lock:
    with _RUNS_LOCK:
        return _START_LOCKS.setdefault(project, threading.Lock())


def start_run(project: str, parallel=None, helpers=None) -> dict:
    """Start Claude Code (headless, signed in with its own login) on the project's queue. One run per project.
    `parallel`, `helpers`: how many helpers at once, and which, for this run (taskqueue.run_plan; 0.13.10): with
    neither, the speed chosen in Settings. 0.14.3: the check "is one running?" and the start are one step under the
    project's lock (a second press, from this tab or another, gets the running state back), and the run starts in a
    folder of its own."""
    from . import taskqueue

    if core.local_only():
        raise ValueError("Cloud models are switched off on this computer: Claude Code is not available.")
    with _start_lock(project):
        st = run_state(project)
        if st.get("running"):
            return st
        plan = taskqueue.run_plan(parallel, helpers)
        path = find_claude()
        if not path:
            raise ValueError("Claude Code was not found on this computer. Install it (claude.com/claude-code), or type "
                             f"{SLASH.split(':')[0]} {project} in Claude Code yourself.")
        if not setup_info()["ready"] or status().get("installed") is False:
            install()  # the plugin is prepared and added on the first start: no separate set-up needed
        log = _log_path(project)
        fh = open(log, "w", encoding="utf-8")
        try:
            proc = subprocess.Popen(program_args(run_args(project, path, plan)), cwd=str(work_folder(project)), stdout=fh,
                                    stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env={**os.environ, **BOX_ENV},
                                    start_new_session=os.name != "nt", **no_window())
        finally:
            fh.close()
        t0, started = time.time(), now()
        with _RUNS_LOCK:
            _RUNS[project] = {"proc": proc, "log": log, "t0": t0, "started_at": started, "plan": plan}
        if isinstance(getattr(proc, "pid", None), int):
            _write_record(project, proc.pid, started, t0, plan)
        return run_state(project)


def stop_run(project: str) -> dict:
    """Stop Claude Code started from the app (also one an earlier copy of the app started: 0.14.3). Batches it had
    taken return to the queue (claims lapse)."""
    with _RUNS_LOCK:
        r = _RUNS.get(project)
    if r:
        if r["proc"].poll() is None:
            r["stopped"] = True
            if isinstance(getattr(r["proc"], "pid", None), int):
                _end_process(r["proc"].pid, r["proc"])
            else:
                r["proc"].terminate()
    else:
        rec = _read_record(project)
        if rec and _pid_runs_enlens(rec["pid"], project):
            _end_process(rec["pid"], alive=lambda p: _pid_runs_enlens(p, project))
        if rec:
            _forget_record(project, rec["pid"])
    return run_state(project)


def stop_all_runs() -> list[dict]:
    """0.14.3: stop every run, the ones this app started and the ones an earlier copy started and that still work
    (Quit ENLENS and "Update and restart" call it: a run left behind keeps using the researcher's Claude plan, and the
    next app could not stop it). Returns [{"project", "started_at"}] of the runs that were working."""
    with _RUNS_LOCK:
        names = set(_RUNS)
    try:
        for f in (core.home() / "claude-runs").glob("*.run.json"):
            try:
                names.add(str(json.loads(f.read_text(encoding="utf-8")).get("project") or ""))
            except (OSError, ValueError, AttributeError):
                pass
    except OSError:
        pass
    stopped = []
    for name in sorted(n for n in names if n):
        before = run_state(name)
        if before.get("running"):
            stop_run(name)
            stopped.append({"project": name, "started_at": before.get("started_at", "")})
    return stopped


# ---------------------------------------------------------------------------------------------
# 0.10: the plugin follows the installation; "Set up Claude" installs Claude Code and opens the sign-in
# ---------------------------------------------------------------------------------------------
def _refused_path() -> Path:
    """Hunt phase 1 (INSTALL-5): the note that Claude Code refused the plugin last time ENLENS rewrote it (beside the
    data folder's plugin folder, not in it: Claude Code copies that folder)."""
    return core.home() / "claude-plugin-refused.json"


# Hunt phase 1.5: `plugin marketplace add` and `plugin install` are run again at every repair and set-up. Should
# Claude Code answer the second time that the marketplace or the plugin is already there, that is no refusal: the
# refresh (`refresh_in_claude_code`) then brings the new files.
_ALREADY = re.compile(r"\balready\b.{0,40}\b(installed|exists|added|present|registered)\b|"
                      r"\balready (been )?(installed|exists|added|present|registered)\b", re.I)


def _took(code: int, text: str) -> bool:
    """Whether Claude Code took an add or install step: it succeeded, or said the thing is already there."""
    return code == 0 or bool(_ALREADY.search(text or ""))


def _claude_version(path: str) -> str:
    code, text = _run([path, "--version"], timeout=20)
    return text.splitlines()[0].strip() if code == 0 and text else ""


def _note_refused(why: str, steps: list[dict], claude: str = "") -> None:
    failed = next((x for x in steps if not x["ok"]), None)
    try:
        core._write_whole(_refused_path(), json.dumps({
            "version": __version__, "python": sys.executable, "reason": why, "t": time.time(), "claude": claude,
            "step": " ".join(failed["args"]) if failed else "", "text": failed["text"] if failed else "",
            "at": time.strftime("%Y-%m-%d %H:%M:%S")}, indent=2))
    except OSError:
        pass  # (then the next start cannot know: the words of this run still say it)


def _forget_refused() -> None:
    try:
        _refused_path().unlink(missing_ok=True)
    except OSError:
        pass


def refused_words(r: dict) -> str:
    """What to tell the person when Claude Code refused a rewritten plugin (r: what repair() returned), or ""."""
    if not r.get("refused"):
        return ""
    said = " ".join(str(r.get("refused_text") or "").split())[-200:]
    return ("Claude Code did not take the ENLENS plugin written for this installation"
            + (f" (it answered: {said})" if said else "") + ", so it still uses the earlier one. ENLENS tries again "
            "at a start a day later, or after ENLENS or Claude Code is updated; or press Set up Claude in Settings → "
            "AI, or run `enlens claude-setup`.")


_REFUSED_WHY = "Claude Code refused it last time"


def _still_waiting(path: str) -> dict | None:
    """Hunt phase 1.5 (INSTALL-5's review note): the note of a refusal when the app's start should not ask Claude Code
    again yet: made less than a day ago, by this ENLENS, for this Claude Code, with the plugin's files otherwise
    fitting. While Claude Code kept refusing, every start rewrote the plugin and ran up to four `claude plugin`
    commands (120 s each). None: ask again."""
    try:
        note = json.loads(_refused_path().read_text(encoding="utf-8"))
        t = float(note.get("t") or 0)
    except (OSError, ValueError, TypeError, AttributeError):
        return None
    if not isinstance(note, dict) or note.get("version") != __version__ or not 0 <= time.time() - t < 86400:
        return None
    if _stale_files():  # something else changed too (another Python, another data folder): ask now
        return None
    if not note.get("claude") or _claude_version(path) != note.get("claude"):
        return None
    return note


def stale() -> str:
    """Why the written plugin no longer fits this installation ("" when it fits, or when none was written): the
    connector it starts is another Python (ENLENS moved, or another copy wrote it) or another data folder. Hunt phase
    1 (INSTALL-5): also when Claude Code refused the plugin last time it was rewritten (its own copy is the old one,
    though the files here are new), so a later start tries again."""
    plug = plugin_folder()
    if not (plug / ".mcp.json").exists():
        return ""
    try:
        refused = json.loads(_refused_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        refused = None
    if isinstance(refused, dict):
        return _REFUSED_WHY + (f" ({refused.get('reason')})" if refused.get("reason") else "")
    return _stale_files()


def _stale_files() -> str:
    """stale() without the note of a refusal: what in the written files no longer fits ("" when they fit)."""
    plug = plugin_folder()
    if not (plug / ".mcp.json").exists():
        return ""
    try:
        cfg = json.loads((plug / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"][SERVER]
    except (OSError, ValueError, KeyError, TypeError):
        return "the plugin's connector settings cannot be read"
    if not same_python(cfg.get("command"), sys.executable):  # (python.exe and pythonw.exe of one environment: one)
        return f"it starts the connector with {cfg.get('command')}, not with this ENLENS ({sys.executable})"
    if (cfg.get("env") or {}).get("ENLENS_HOME") != str(core.home()):
        return "it uses another data folder"
    if not (plug / "SKILL.md").exists():
        return "files of the plugin are missing"
    # 0.14.3: the plugin's own texts (the skill, the helpers) change with a version: a plugin written by an older
    # ENLENS is written again, so a one-line-install update (which runs repair(), never write_plugin() alone) and
    # the install line run again both bring them along
    try:
        written = json.loads((plug / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")).get("version")
    except (OSError, ValueError, AttributeError):
        return "the plugin's version cannot be read"
    if written not in (__version__, _semver(__version__)):
        return f"it was written by ENLENS {written}, and this is ENLENS {__version__}"
    return ""


def refresh_in_claude_code(path: str) -> list[dict]:
    """0.14.3: make Claude Code take the plugin files just written. `marketplace add` and `install` keep a copy of the
    plugin, so a rewritten plugin reaches Claude Code only when its marketplace and the plugin are updated (both are
    idempotent: nothing changes when the copy is current). Never raises; a failure is in the steps and is not fatal
    (the plugin stays as it was)."""
    steps = []
    for args in ([path, "plugin", "marketplace", "update", MARKETPLACE],
                 [path, "plugin", "update", f"{PLUGIN}@{MARKETPLACE}"]):
        code, text = _run(args, timeout=120)
        steps.append({"args": args[1:], "ok": code == 0, "text": re.sub(r"\x1b\[[0-9;]*m", "", text)[-300:]})
    return steps


def repair(run_claude: bool = True, patient: bool = False) -> dict:
    """Write the plugin again when it no longer fits this installation (see stale()), and add it to Claude Code again
    with the same two commands as set-up (both idempotent), quietly. Nothing happens when no plugin was set up, or
    on a local-only installation. Run when the app starts and after an installer or an update. `patient` (the app's
    start): after a refusal, Claude Code is asked again only a day later or once ENLENS or Claude Code changed
    (`_still_waiting`); the installer and the update ask every time."""
    if core.local_only():
        return {"repaired": False}
    why = stale()
    if not why:
        return {"repaired": False}
    if patient and run_claude and why.startswith(_REFUSED_WHY):
        path = find_claude()
        note = _still_waiting(path) if path else None
        if note:
            return {"repaired": False, "refused": True, "waiting": True, "reason": why,
                    "refused_step": note.get("step", ""), "refused_text": note.get("text", "")}
    out: dict = {"repaired": True, "reason": why, "steps": []}
    try:
        root = write_plugin()
    except (OSError, ValueError) as e:
        return {"repaired": False, "reason": why, "error": str(e)}
    path = find_claude() if run_claude else ""
    if path:
        for args in ([path, "plugin", "marketplace", "add", str(root)], [path, "plugin", "install", f"{PLUGIN}@{MARKETPLACE}"]):
            code, text = _run(args, timeout=120)
            ok = _took(code, text)
            out["steps"].append({"args": args[1:], "ok": ok, "text": re.sub(r"\x1b\[[0-9;]*m", "", text)[-300:]})
            if not ok:
                break
        else:
            out["refreshed"] = refresh_in_claude_code(path)
        # hunt phase 1 (INSTALL-5): repaired only when Claude Code took it (as agentcli.repair says it): the files
        # were rewritten whatever Claude Code answered, and "now uses this installation" was said after a refusal
        # while Claude Code kept its own, older copy. A refusal is noted, so stale() sees it and a later start tries
        # again; the words say what happened (refused_words).
        done = out["steps"] + out.get("refreshed", [])
        if all(x["ok"] for x in done):
            _forget_refused()
        else:
            bad = next(x for x in done if not x["ok"])
            out.update(repaired=False, refused=True, refused_step=" ".join(bad["args"]), refused_text=bad["text"])
            _note_refused(why, done, _claude_version(path))
    elif run_claude:
        _forget_refused()  # no Claude Code on this computer any more: nothing to try again
    _STATUS["value"] = None
    try:
        from . import mcp_server

        out["desktop"] = mcp_server.repair_desktop()
    except Exception:  # noqa: BLE001 - the Claude desktop app's config is a nicety here
        pass
    return out


INSTALL_DOCS = "https://code.claude.com/docs/en/setup"


def installer_command(sys_name: str | None = None) -> dict:
    """Anthropic's native installer for Claude Code (no Node.js; it lands in ~/.local/bin, where find_claude() looks):
    the line shown to the person, and the program the app runs after they confirm. ENLENS_CLAUDE_INSTALLER replaces
    the program (for the tests and the dev server)."""
    from .installation import system

    name = sys_name or system()
    if name == "windows":
        line = "irm https://claude.ai/install.ps1 | iex"
        args = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", line]
    else:
        line = "curl -fsSL https://claude.ai/install.sh | bash"
        args = ["/bin/bash", "-c", line]
    stand_in = os.environ.get("ENLENS_CLAUDE_INSTALLER", "").strip()
    if stand_in:
        args = _cmd(stand_in)
    return {"line": line, "args": args, "docs": INSTALL_DOCS}


def install_claude_code(timeout: float = 900) -> dict:
    """Run the installer (the person confirmed it in the app). Returns {"ok", "text", "status"}."""
    if core.local_only():
        raise ValueError("Cloud models are switched off on this computer: Claude Code is not available.")
    cmd = installer_command()
    try:
        r = subprocess.run(cmd["args"], capture_output=True, text=True, errors="replace", timeout=timeout,
                           stdin=subprocess.DEVNULL, cwd=str(Path.home()), **no_window())
        code, text = r.returncode, ((r.stdout or "") + (r.stderr or ""))
    except (OSError, subprocess.SubprocessError) as e:
        code, text = 1, f"{type(e).__name__}: {e}"
    text = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", text).strip()
    _STATUS["value"] = None
    st = status(refresh=True)
    ok = code == 0 and st["found"]
    if code == 0 and not st["found"]:
        text = (text + "\n" if text else "") + "The installer finished, but ENLENS cannot find the claude program yet."
    return {"ok": ok, "text": text[-1500:], "status": st}


# Where the claude program is installed does not limit what it can read: what it may open is set by the folder it
# starts in (Read, Grep and Glob need no approval inside it) and by its permission rules. So the sign-in window, like
# the headless runs, starts Claude Code in an empty folder of ENLENS's own without the tools that read, write or fetch
# files or run commands (box_args). Before, it started in the home folder, where Claude Code could read every file of
# the person without asking.
def sign_in_folder() -> Path:
    """The empty folder the sign-in window starts Claude Code in. Anything found in it is removed first, but the folder
    itself stays, so a sign-in window still open from an earlier press keeps a folder to work in."""
    d = core.home() / "claude-runs" / "sign-in"
    d.mkdir(parents=True, exist_ok=True)
    for child in d.iterdir():
        try:
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink()
        except OSError:
            pass
    return d


def sign_in_line(folder: Path, windows: bool | None = None) -> str:
    """The line a person types to sign in by hand (when no window can be opened): go to the empty folder first."""
    windows = os.name == "nt" if windows is None else windows
    if windows:   # PowerShell 5.1 has no &&
        from .gui.launcher import _ps_quote

        return f"cd {_ps_quote(str(folder))}; claude"
    import shlex

    return f"cd {shlex.quote(str(folder))} && claude"


def _sign_in_script(claude: str, work: Path | None = None, options: set[str] | None = None) -> Path:
    d = core.home() / "claude-runs"
    d.mkdir(parents=True, exist_ok=True)
    work = work or sign_in_folder()
    box = box_args(claude, run=False, options=options)
    if os.name == "nt":
        from .gui.launcher import _ps_quote

        q = lambda s: _ps_quote(str(s))  # noqa: E731 - a PowerShell string
        p = d / "sign-in.ps1"
        p.write_text("Write-Host 'ENLENS: sign in to Claude Code with your Claude plan.'\r\n"
                     "Write-Host 'Follow the steps below; when Claude Code shows its prompt, close this window.'\r\n"
                     "Write-Host 'It runs in an empty folder of ENLENS and cannot open your files.'\r\n"
                     f"Set-Location -LiteralPath {q(work)}\r\n"
                     f"& {' '.join(q(x) for x in [claude, *box])}\r\n",
                     encoding="utf-8-sig", newline="")  # 0.14.3: Windows PowerShell 5.1 reads a file without a BOM
        # as ANSI; 0.15.7: newline="" keeps "\r\n" as written (Windows made it "\r\r\n")
        return p
    import shlex

    p = d / "sign-in.command"   # .command: macOS opens it in Terminal
    p.write_text("#!/bin/sh\n"
                 "echo 'ENLENS: sign in to Claude Code with your Claude plan.'\n"
                 "echo 'Follow the steps below; when Claude Code shows its prompt, close this window.'\n"
                 "echo 'It runs in an empty folder of ENLENS and cannot open your files.'\n"
                 "echo\n"
                 f"cd {shlex.quote(str(work))} || exit 1\n"
                 f"exec {' '.join(shlex.quote(x) for x in _cmd(claude) + box)}\n",
                 encoding="utf-8")
    p.chmod(0o755)
    return p


def _open_window(script: Path) -> str:
    """Open a terminal window running the sign-in script. Returns the window's name, or "" when none could open."""
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-a", "Terminal", str(script)])  # console: macOS
            return "Terminal"
        if os.name == "nt":
            from .gui.launcher import _ps_quote

            # 0.15.2: Windows PowerShell's Start-Process joins these with spaces and quotes none of them, so the
            # script's path is quoted here (C:\\Users\\Ábel Gergő\\enlens\\... was cut at the space)
            subprocess.Popen(["powershell", "-NoProfile", "-Command",
                              f"Start-Process powershell -ArgumentList '-NoExit','-ExecutionPolicy','Bypass','-File',"
                              f"{_ps_quote(chr(34) + str(script) + chr(34))}"],
                             **no_window())  # the window it opens is Start-Process's own
            return "PowerShell"
        for term, flag in (("x-terminal-emulator", "-e"), ("gnome-terminal", "--"), ("konsole", "-e"),
                           ("xfce4-terminal", "-x"), ("xterm", "-e")):
            exe = shutil.which(term)
            if exe:
                subprocess.Popen([exe, flag, str(script)], start_new_session=True)  # console: Linux
                return term
    except OSError:
        return ""
    return ""


def open_sign_in() -> dict:
    """Open a terminal window already running `claude`, for the one-time sign-in with the person's Claude plan.
    ENLENS never sees the login: Claude Code keeps it. The app checks `status()` until it says signed in."""
    if core.local_only():
        raise ValueError("Cloud models are switched off on this computer: Claude Code is not available.")
    path = find_claude()
    if not path:
        raise ValueError("Claude Code is not on this computer yet: install it first.")
    work = sign_in_folder()
    window = _open_window(_sign_in_script(path, work))
    _STATUS["value"] = None
    return {"opened": bool(window), "window": window, "command": sign_in_line(work), "folder": str(work)}
