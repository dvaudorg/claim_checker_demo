"""Hunt phase 1.5, area `install`: what phases 0 and 1 left as a note, a suspicion or a Windows question about
installing, starting and updating ENLENS, its connector, its command line and its add-ons.

Each test asserts what ENLENS should do (by the manual, the module docstrings and the owner's decisions). The tests
marked for Windows run on the Windows leg of CI only; each has a platform-free twin here where the logic allows it.
Nothing here touches a real Claude Code, Claude app, uv, network or data folder: the conftest guards apply, and the
programs ENLENS would start are stand-ins.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------------
def _tool(tool: str, args: dict):
    """Call one connector tool; returns (is_error, text)."""
    pytest.importorskip("mcp")
    from mcp import Client

    from enlens_claims.mcp_server import build_server

    async def run():
        async with Client(build_server()) as c:
            r = await c.call_tool(tool, args)
            return r.is_error, r.content[0].text

    return asyncio.run(run())


# ---------------------------------------------------------------------------------------------
# 1. who may read new documents with AI: the connector and the command line ask, as the app does
# ---------------------------------------------------------------------------------------------
def test_the_connector_makes_no_project_without_a_choice_of_ai_access(tmp_path, corpus):
    """INSTALL15-1 (owner): `create_project` without `ai_access` on a new project (no default chosen) is refused in
    words that name the option, and leaves no project behind; documents never become Claude-readable by silence."""
    from enlens_claims import home

    err, text = _tool("create_project", {"name": "Demo", "sources_path": str(corpus)})
    assert err, text
    assert "ai_access" in text and "cloud" in text and "local" in text and "none" in text
    assert "Demo" not in home.list_projects()


def test_the_connector_adds_no_sources_without_a_choice_of_ai_access(tmp_path, corpus):
    """INSTALL15-1 (owner): `add_sources` without `ai_access` to a project whose default was never chosen is refused in
    words; nothing is added."""
    from enlens_claims import home

    ws = home.create_project("Demo")
    err, text = _tool("add_sources", {"project": "Demo", "sources_path": str(corpus)})
    assert err, text
    assert "ai_access" in text
    assert ws.scalar("SELECT COUNT(*) FROM documents") == 0


def test_the_connector_applies_a_chosen_default(tmp_path, corpus):
    """INSTALL15-1 (owner): when the project's default was chosen, `add_sources` without `ai_access` applies it."""
    from enlens_claims import access, home

    ws = home.create_project("Demo")
    access.set_default(ws, "local")
    err, text = _tool("add_sources", {"project": "Demo", "sources_path": str(corpus)})
    assert not err, text
    assert json.loads(text)["ai_access"] == "local"
    assert ws.scalar("SELECT COUNT(*) FROM documents") > 0
    assert set(access.levels(ws).values()) == {"local"}
    assert access.default(ws) == "local"


def test_the_connector_with_ai_access_given_adds_as_asked(tmp_path, corpus):
    """INSTALL15-1: an explicit choice still works on a new project, and becomes its default (as the app's first
    Add does)."""
    from enlens_claims import access, home

    err, text = _tool("create_project", {"name": "Demo", "sources_path": str(corpus), "ai_access": "none"})
    assert not err, text
    ws = home.open_project("Demo")
    assert access.default_chosen(ws) and access.default(ws) == "none"
    assert ws.scalar("SELECT COUNT(*) FROM documents") > 0


def test_enlens_ingest_refuses_without_a_choice_of_ai_access(ws, corpus, capsys):
    """INSTALL15-1 (owner): `enlens ingest` on a project whose default was never chosen, without `--ai-access`, exits
    non-zero, names the option, and adds nothing."""
    from enlens_claims import cli

    rc = cli.main(["--ws", str(ws.root), "ingest", str(corpus)])
    out = capsys.readouterr()
    assert rc != 0
    assert "--ai-access" in out.err
    assert ws.scalar("SELECT COUNT(*) FROM documents") == 0


def test_enlens_ingest_takes_ai_access(ws, corpus, capsys):
    """INSTALL15-1 (owner): `enlens ingest --ai-access none` adds the documents for no AI and makes it the default."""
    from enlens_claims import access, cli

    rc = cli.main(["--ws", str(ws.root), "ingest", "--ai-access", "none", str(corpus)])
    assert rc == 0, capsys.readouterr().err
    assert ws.scalar("SELECT COUNT(*) FROM documents") > 0
    assert access.default_chosen(ws) and access.default(ws) == "none"


def test_enlens_ingest_applies_a_chosen_default(ws, corpus, capsys):
    """INSTALL15-1 (owner): with the project's default chosen, `enlens ingest` without the option applies it."""
    from enlens_claims import access, cli

    access.set_default(ws, "local")
    rc = cli.main(["--ws", str(ws.root), "ingest", str(corpus)])
    assert rc == 0, capsys.readouterr().err
    assert ws.scalar("SELECT COUNT(*) FROM documents") > 0
    assert access.default(ws) == "local"


def test_enlens_ingest_refuses_an_unknown_ai_access(ws, corpus, capsys):
    """INSTALL15-1: `--ai-access` takes cloud, local or none only."""
    from enlens_claims import cli

    with pytest.raises(SystemExit) as e:
        cli.main(["--ws", str(ws.root), "ingest", "--ai-access", "everyone", str(corpus)])
    assert e.value.code != 0
    assert ws.scalar("SELECT COUNT(*) FROM documents") == 0


def test_the_connector_checks_the_path_and_the_installation_before_making_a_project(tmp_path, corpus, monkeypatch):
    """INSTALL15-16 (notes "Not proven" 1; owner: the path choice stays as it is): what the connector checks of the
    path and the setting an AI passes. A path that is not there is refused in words; `cloud` on an installation without
    cloud models is refused; neither leaves a project behind."""
    from enlens_claims import home

    err, text = _tool("create_project", {"name": "Typo", "sources_path": str(tmp_path / "nothing-here"),
                                         "ai_access": "cloud"})
    assert err and "Nothing at" in text
    monkeypatch.setenv("ENLENS_LOCAL_ONLY", "1")
    err, text = _tool("create_project", {"name": "Cloudy", "sources_path": str(corpus), "ai_access": "cloud"})
    assert err and "switched off" in text
    assert not {"Typo", "Cloudy"} & set(home.list_projects())
    err, text = _tool("create_project", {"name": "Kept", "sources_path": str(corpus), "ai_access": "local"})
    assert not err, text


# ---------------------------------------------------------------------------------------------
# 2. a broken add-on does not stop ENLENS
# ---------------------------------------------------------------------------------------------
def _addon(name: str, **attrs):
    import types

    mod = types.ModuleType(f"{name}_addon")
    for k, v in attrs.items():
        setattr(mod, k, v)
    return (name, mod)


def _tables(ws) -> set[str]:
    return {r[0] for r in ws.query("SELECT name FROM sqlite_master WHERE type IN ('table', 'index')")}


def test_an_add_on_with_a_bad_schema_is_left_out_and_named(monkeypatch, tmp_path, capsys):
    """INSTALL15-2 (owner): an add-on whose SCHEMA does not run stopped every project from opening, with an SQLite
    error naming no add-on (store._setup_addons). Now its tables are left out (also the ones its script made before
    the faulty statement), the project opens, the other add-ons' tables are there, and `addons.errors()` (and the
    terminal) say which add-on failed and why."""
    from enlens_claims import addons
    from enlens_claims.store import Workspace

    good = _addon("good", SCHEMA="CREATE TABLE IF NOT EXISTS good_notes(id TEXT PRIMARY KEY);",
                  INDEXES="CREATE INDEX IF NOT EXISTS ix_good ON good_notes(id);")
    bad = _addon("broken", SCHEMA="CREATE TABLE IF NOT EXISTS broken_a(id TEXT);\nCREATE TABLEE broken_b(id TEXT);",
                  MIGRATIONS=[("broken_a", "extra", "TEXT")])
    monkeypatch.setattr(addons, "_loaded", [bad, good])
    monkeypatch.setattr(addons, "_errors", [])
    ws = Workspace.create(tmp_path / "project")
    ws = Workspace.open(tmp_path / "project")  # and again: an existing project opens too
    names = _tables(ws)
    assert {"good_notes", "ix_good"} <= names
    assert not {"broken_a", "broken_b"} & names
    errs = addons.errors()
    assert [e["addon"] for e in errs] == ["broken"], errs
    assert "TABLEE" in errs[0]["error"] or "syntax" in errs[0]["error"]
    assert "broken" in capsys.readouterr().err


def test_an_add_on_with_a_bad_column_name_is_left_out_and_named(monkeypatch, tmp_path):
    """INSTALL15-2, sibling (and INSTALL-8's words): a MIGRATIONS name ENLENS cannot add was refused with a ValueError
    that stopped every project from opening; now that add-on is left out, named in `addons.errors()`."""
    from enlens_claims import addons
    from enlens_claims.store import Workspace

    bad = _addon("fieldnotes", SCHEMA="CREATE TABLE IF NOT EXISTS drafts(draft_id TEXT PRIMARY KEY);",
                 MIGRATIONS=[("drafts", "ai_note\n", "TEXT")])
    monkeypatch.setattr(addons, "_loaded", [bad])
    monkeypatch.setattr(addons, "_errors", [])
    ws = Workspace.create(tmp_path / "project")
    assert "drafts" not in _tables(ws)
    errs = addons.errors()
    assert errs and errs[0]["addon"] == "fieldnotes" and "cannot add" in errs[0]["error"]


# ---------------------------------------------------------------------------------------------
# 3 and 5. cmd.exe reads a command file's line, and a command file's command line, again
# ---------------------------------------------------------------------------------------------
# Data folders whose names cmd.exe would read as its own: "&" ends a command, "%NAME%" is expanded, "^" escapes,
# "!" is expanded with delayed expansion on; a space and an accent for good measure.
_ODD_FOLDERS = ["R&D", "100% sure", "%PATH%", "Hi!there", "a^b", "with space", "Kovács (lab)"]
_ENV = {"PATH": r"C:\Windows\system32", "CD": r"C:\Users\Anna", "OS": "Windows_NT"}


def _cmd_vars(name: str, env: dict) -> str | None:
    """%name% as cmd.exe expands it (with the :~start,length form); None when not defined."""
    base, sub, spec = name.partition(":~")
    val = env.get(base.upper())
    if val is None or not sub:
        return val
    a, comma, b = spec.partition(",")
    start = int(a or 0)
    return val[start:start + int(b or 0)] if comma else val[start:]


def _expand_command_line(s: str, env: dict) -> str:
    """cmd.exe's % reading of a command line (not a command file): %NAME% is expanded, an undefined one stays as it
    is, and a % with nothing before the next % stays a % (the next % starts again)."""
    out, i = [], 0
    while i < len(s):
        if s[i] != "%":
            out.append(s[i])
            i += 1
            continue
        j = s.find("%", i + 1)
        if j == -1:
            out.append(s[i:])
            break
        name = s[i + 1:j]
        if not name:
            out.append("%")
            i += 1
            continue
        val = _cmd_vars(name, env)
        out.append(s[i:j + 1] if val is None else val)
        i = j + 1
    return "".join(out)


def _expand_command_file(s: str, env: dict) -> str:
    """cmd.exe's % reading of a line of a command file: %% is %, %NAME% is expanded (undefined: nothing)."""
    out, i = [], 0
    while i < len(s):
        if s[i] != "%":
            out.append(s[i])
            i += 1
        elif s[i + 1:i + 2] == "%":
            out.append("%")
            i += 2
        else:
            j = s.find("%", i + 1)
            out.append(_cmd_vars(s[i + 1:j], env) or "")
            i = j + 1
    return "".join(out)


def _outside_quotes(s: str) -> str:
    """What cmd.exe reads outside double quotes (where & | < > ^ are its own)."""
    out, inside = [], False
    for ch in s:
        if ch == '"':
            inside = not inside
        elif not inside:
            out.append(ch)
    return "".join(out)


def _ms_argv(s: str) -> list[str]:
    """A command line split as a Windows program (the Microsoft C rules, which Python and Node use) splits it."""
    args, i, n = [], 0, len(s)
    while True:
        while i < n and s[i] in " \t":
            i += 1
        if i >= n:
            return args
        cur, inside = [], False
        while i < n:
            c = s[i]
            if c == "\\":
                k = i
                while k < n and s[k] == "\\":
                    k += 1
                if k < n and s[k] == '"':
                    cur.append("\\" * ((k - i) // 2))
                    if (k - i) % 2:
                        cur.append('"')
                        k += 1
                else:
                    cur.append("\\" * (k - i))
                i = k
                continue
            if c == '"':
                if inside and s[i + 1:i + 2] == '"':
                    cur.append('"')
                    i += 2
                    continue
                inside = not inside
                i += 1
                continue
            if c in " \t" and not inside:
                break
            cur.append(c)
            i += 1
        args.append("".join(cur))


def _as_on_windows(monkeypatch, procs) -> None:
    """procs.program_args as on Windows (where a .cmd or .bat runs through cmd.exe); os.name itself stays."""
    monkeypatch.setattr(procs, "is_command_file", lambda program: str(program).lower().endswith((".cmd", ".bat")))


@pytest.mark.parametrize("odd", _ODD_FOLDERS)
def test_a_command_files_command_line_brings_each_argument_whole(odd, monkeypatch):
    """INSTALL15-5, platform-free twin: `procs.program_args` for a command file (npm's claude.cmd) gives cmd.exe a
    line that, read the way cmd.exe reads it (% expanded, outer quotes taken off, & | < > ^ only outside quotes) and
    passed on by the shim's %* to the program, gives the program each argument as it was."""
    from enlens_claims import procs

    _as_on_windows(monkeypatch, procs)
    folder = rf"D:\{odd}\enlens\claude-plugin"
    argv = [r"C:\Users\Anna\AppData\Roaming\npm\claude.cmd", "plugin", "marketplace", "add", folder,
            '/enlens-run:enlens-run "Pilot"', "ends in a backslash\\"]
    line = procs.program_args(argv)
    assert isinstance(line, str)
    assert line.startswith('"') and " /d /v:off /s /c \"" in line
    after_c = _expand_command_line(line.split(" /s /c ", 1)[1], _ENV)
    assert after_c[0] == '"' and after_c[-1] == '"'
    inner = after_c[1:-1]  # /s: the first and the last quote are taken off
    assert not set(_outside_quotes(inner)) & set("&|<>^"), inner
    assert _ms_argv(inner) == argv


def test_a_program_that_is_not_a_command_file_starts_as_before(monkeypatch):
    """INSTALL15-5: an .exe (and anything on macOS and Linux) is handed to subprocess unchanged."""
    from enlens_claims import procs

    argv = [r"C:\Users\Anna\.local\bin\claude.exe", "plugin", "add", r"D:\R&D\enlens"]
    assert procs.program_args(argv) == argv
    _as_on_windows(monkeypatch, procs)
    assert procs.program_args(argv) == argv
    with pytest.raises(ValueError):
        procs.program_args([r"C:\npm\claude.cmd", "a\nb"])


@pytest.mark.parametrize("odd", _ODD_FOLDERS)
def test_the_icons_command_file_brings_the_data_folder_whole(odd, monkeypatch, tmp_path):
    """INSTALL15-3, platform-free twin of the Windows test below: ENLENS.cmd's start line, read as cmd.exe reads a
    command file (%% is %, & | < > ^ only outside quotes, ! literal under DisableDelayedExpansion), gives ENLENS the
    data folder whole."""
    from enlens_claims.gui import launcher

    monkeypatch.setattr(launcher, "_com_shortcut", lambda *a, **k: False)
    monkeypatch.setattr(launcher.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError("no PowerShell")))
    data = rf"D:\{odd}\enlens"
    args = ["-m", "enlens_claims.gui.launch", "--launcher", "--home", data]
    made = launcher._windows_shortcut(tmp_path, r"C:\Python\python.exe", args)
    assert made.suffix == ".cmd"
    text = made.read_bytes().decode("utf-8")
    assert "DisableDelayedExpansion" in text
    start = [ln for ln in text.split("\r\n") if ln.startswith("start ")][0]
    line = _expand_command_file(start, _ENV)
    assert not set(_outside_quotes(line)) & set("&|<>^"), line
    got = _ms_argv(line[len('start "" '):])
    assert got[1:] == args and got[0] == r"C:\Python\python.exe"


_RECORDER = """import json, sys
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps(sys.argv[2:]), encoding="utf-8")
"""


@pytest.mark.skipif(os.name != "nt", reason="cmd.exe runs only on Windows (the Windows CI leg)")
@pytest.mark.parametrize("odd", _ODD_FOLDERS)
def test_windows_the_icons_command_file_brings_the_data_folder_whole(odd, monkeypatch, tmp_path):
    """INSTALL15-3 (owner, Windows CI): ENLENS.cmd for a data folder such as ...\\R&D\\enlens, written when neither the
    Shell link nor PowerShell can make the icon, run through cmd.exe: the program it starts (a stand-in that records
    its arguments) gets the data folder whole."""
    import subprocess
    import time

    from enlens_claims.gui import launcher

    rec = tmp_path / "recorder.py"
    rec.write_text(_RECORDER, encoding="utf-8")
    out = tmp_path / "argv.json"
    data = str(tmp_path / odd / "enlens")
    args = [str(rec), str(out), "--launcher", "--home", data]
    with monkeypatch.context() as m:
        m.setattr(launcher, "_com_shortcut", lambda *a, **k: False)
        m.setattr(launcher.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError("no PowerShell")))
        made = launcher._windows_shortcut(tmp_path, sys.executable, args)
    assert made.suffix == ".cmd"
    subprocess.run(["cmd.exe", "/d", "/c", str(made)], timeout=60, capture_output=True)
    t0 = time.time()
    while not out.exists() and time.time() - t0 < 60:  # `start` does not wait for the program
        time.sleep(0.2)
    assert json.loads(out.read_text(encoding="utf-8")) == ["--launcher", "--home", data]


def _fake_cmd(tmp_path: Path, name: str = "claude.cmd") -> tuple[Path, Path]:
    """A command file that passes its arguments on with %*, as npm's shims do, to a stand-in that records them."""
    rec = tmp_path / "recorder.py"
    rec.write_text(_RECORDER, encoding="utf-8")
    out = tmp_path / "argv.json"
    shim = tmp_path / "npm" / name
    shim.parent.mkdir(parents=True, exist_ok=True)
    shim.write_text(f'@echo off\r\n"{sys.executable}" "{rec}" "{out}" %*\r\n', encoding="utf-8", newline="")
    return shim, out


@pytest.mark.skipif(os.name != "nt", reason="cmd.exe runs only on Windows (the Windows CI leg)")
@pytest.mark.parametrize("odd", _ODD_FOLDERS)
def test_windows_claude_cmd_gets_the_plugin_folder_whole(odd, tmp_path):
    """INSTALL15-5 (owner, Windows CI): npm's claude.cmd is started through cmd.exe; `claude plugin marketplace add
    <data folder>\\claude-plugin` with a data folder ...\\R&D\\enlens or one holding %PATH% reaches Claude Code whole
    (claude_setup._run, the route of Set up Claude Code)."""
    from enlens_claims import claude_setup

    shim, out = _fake_cmd(tmp_path)
    folder = str(tmp_path / odd / "enlens" / "claude-plugin")
    code, text = claude_setup._run([str(shim), "plugin", "marketplace", "add", folder], timeout=60)
    assert code == 0, text
    assert json.loads(out.read_text(encoding="utf-8")) == ["plugin", "marketplace", "add", folder]


@pytest.mark.skipif(os.name != "nt", reason="cmd.exe runs only on Windows (the Windows CI leg)")
def test_windows_a_run_started_through_claude_cmd_gets_its_prompt_whole(tmp_path):
    """INSTALL15-5, sibling (Windows CI): the headless run's prompt (`/enlens-run:enlens-run "Pilot"` and its options)
    reaches a claude.cmd whole through `procs.program_args`, as start_run starts it."""
    import subprocess

    from enlens_claims import procs

    shim, out = _fake_cmd(tmp_path)
    argv = [str(shim), "-p", '/enlens-run:enlens-run "Pilot 2026" --parallel 2', "--allowedTools", "Agent"]
    subprocess.run(procs.program_args(argv), timeout=60, capture_output=True, **procs.no_window())
    assert json.loads(out.read_text(encoding="utf-8")) == argv[1:]


@pytest.mark.parametrize("odd", ["R&D", "%PATH%"])
def test_claude_setup_hands_a_claude_cmd_its_arguments_for_cmd_exe(odd, monkeypatch):
    """INSTALL15-5, platform-free twin: what claude_setup._run hands subprocess for npm's claude.cmd, read as Windows
    reads it (cmd.exe /c with the line), gives Claude Code the plugin folder whole. It handed the list, which
    list2cmdline quotes for spaces only: "&" ended the command and %PATH% was expanded."""
    import subprocess

    from enlens_claims import claude_setup, procs

    _as_on_windows(monkeypatch, procs)
    seen: list = []

    def run(args, **kw):
        seen.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(claude_setup.subprocess, "run", run)
    folder = rf"D:\{odd}\enlens\claude-plugin"
    argv = [r"C:\Users\Anna\AppData\Roaming\npm\claude.cmd", "plugin", "marketplace", "add", folder]
    claude_setup._run(argv)
    got = seen[0]
    if isinstance(got, list):  # CreateProcess runs a command file as cmd.exe /c <list2cmdline of the list>
        line = _expand_command_line(subprocess.list2cmdline(got), _ENV)
    else:
        after_c = _expand_command_line(got.split(" /s /c ", 1)[1], _ENV)
        line = after_c[1:-1]
    assert not set(_outside_quotes(line)) & set("&|<>^"), line
    assert _ms_argv(line) == argv


def test_a_run_started_through_claude_cmd_is_recognised_as_its_projects(monkeypatch):
    """INSTALL15-5, sibling: a run started through cmd.exe shows its prompt's quotes doubled
    (`/enlens-run:enlens-run ""Pilot""`); it is still recognised as that project's run (and not another's), so Stop
    and the record of a run left going find it."""
    from enlens_claims import claude_setup, procs

    _as_on_windows(monkeypatch, procs)
    argv = [r"C:\npm\claude.cmd", "-p", f'{claude_setup.SLASH} "Pilot" --parallel 2', "--output-format", "text"]
    line = procs.program_args(argv)
    assert claude_setup._runs_this(line, "Pilot")
    assert not claude_setup._runs_this(line, "Pilot 2")
    assert not claude_setup._runs_this(line, "Pil")


# ---------------------------------------------------------------------------------------------
# 4. install.ps1 with [ or ] in the temporary folder (a user name such as "Anna [Lab]")
# ---------------------------------------------------------------------------------------------
_PS1 = Path(__file__).resolve().parent.parent / "install" / "install.ps1"


def _pwsh() -> str:
    import shutil

    found = shutil.which("pwsh") or shutil.which("powershell")
    if not found:
        pytest.skip("no PowerShell here (GitHub's Linux and Windows machines have it)")
    return found


def _fake_uv(tmp_path: Path) -> tuple[Path, Path]:
    """A stand-in for uv on the PATH that records each call's arguments (one JSON list per line) and does nothing."""
    rec = tmp_path / "uvrec.py"
    rec.write_text("import json, sys\nwith open(sys.argv[1], 'a', encoding='utf-8') as f:\n"
                   "    f.write(json.dumps(sys.argv[2:]) + '\\n')\n", encoding="utf-8")
    log = tmp_path / "uv-calls.jsonl"
    folder = tmp_path / "fakebin"
    folder.mkdir()
    if os.name == "nt":
        (folder / "uv.cmd").write_text(f'@echo off\r\n"{sys.executable}" "{rec}" "{log}" %*\r\n', encoding="utf-8",
                                       newline="")
    else:
        sh = folder / "uv"
        sh.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{rec}" "{log}" "$@"\n', encoding="utf-8")
        sh.chmod(0o755)
    return folder, log


def test_install_ps1_takes_every_path_literally():
    """INSTALL15-4 (owner), platform-free: install.ps1 hands its paths to PowerShell literally: a path holding [ or ]
    (a user folder "Anna [Lab]", so %TEMP% too) is a wildcard pattern to -Path, Resolve-Path and Get-FileHash."""
    import re

    text = "\n".join(ln for ln in _PS1.read_text(encoding="utf-8").splitlines() if not ln.lstrip().startswith("#"))
    for cmdlet in ("Resolve-Path", "Get-FileHash", "Test-Path", "Copy-Item", "Remove-Item", "Get-Content"):
        for m in re.finditer(rf"{cmdlet}\b[^\n|;)]*", text):
            assert "-LiteralPath" in m.group(0), m.group(0)
    assert "-OutFile" not in text  # Windows PowerShell 5.1 reads -OutFile as a pattern too, and has no literal form


@pytest.mark.skipif(os.name != "nt", reason="install.ps1 installs on Windows only (install.sh elsewhere): the Windows CI "
                    "leg runs it whole")
def test_install_ps1_installs_from_a_temporary_folder_with_brackets(tmp_path):
    """INSTALL15-4 (owner; Windows CI): the whole install.ps1 with
    %TEMP% under "Anna [Lab]" and the package in a folder with brackets, uv a stand-in: it reaches uv's install with
    the package's address (step 3), and cleans its temporary folder up. Before, Resolve-Path, Get-FileHash and the
    clean-up took the brackets as a pattern ("Cannot find path")."""
    import subprocess

    pwsh = _pwsh()
    temp = tmp_path / "Anna [Lab]" / "Temp"
    temp.mkdir(parents=True)
    pkgs = tmp_path / "builds [x]"
    pkgs.mkdir()
    wheel = pkgs / "enlens_claims-9.9.9-py3-none-any.whl"
    wheel.write_bytes(b"not a real package")
    fakebin, log = _fake_uv(tmp_path)
    profile = tmp_path / "Anna [Lab]" / "profile"
    profile.mkdir()
    env = {**os.environ, "TEMP": str(temp), "TMP": str(temp), "TMPDIR": str(temp),
           "PATH": str(fakebin) + os.pathsep + os.environ.get("PATH", ""), "ENLENS_WHEEL": str(wheel),
           "ENLENS_VERSION": "9.9.9", "ENLENS_NO_OPEN": "1", "ENLENS_FREE_WAIT": "0", "USERPROFILE": str(profile),
           "APPDATA": str(profile / "AppData"), "UV_TOOL_DIR": str(profile / "tools"),
           "UV_TOOL_BIN_DIR": str(profile / "bin"), "HOME": str(profile)}
    r = subprocess.run([pwsh, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(_PS1)],
                       capture_output=True, text=True, errors="replace", env=env, timeout=180)
    said = r.stdout + r.stderr
    assert "Cannot find path" not in said and "wildcard" not in said.lower(), said
    calls = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []
    installs = [c for c in calls if c[:2] == ["tool", "install"]]
    assert installs, said
    assert installs[0][-1].startswith("enlens-claims[") and "@ file:" in installs[0][-1], installs
    assert installs[0][-1].endswith(wheel.name), installs
    assert not [p for p in temp.iterdir() if p.name.startswith("enlens-")], said  # the clean-up found its folder


def test_install_ps1_downloads_into_a_folder_with_brackets(tmp_path):
    """INSTALL15-4, the download route (runs where PowerShell is): Save-Download writes the package and SHA256SUMS
    into a folder with [ and ] byte for byte (from a stand-in server on this computer: no network)."""
    import http.server
    import subprocess
    import threading

    pwsh = _pwsh()
    served = tmp_path / "served"
    served.mkdir()
    body = bytes(range(256)) * 64
    (served / "pkg.whl").write_bytes(body)

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(served), **k)

        def log_message(self, *a):
            pass

    from enlens_claims.gui.server import QuickServer

    srv = QuickServer(("127.0.0.1", 0), Quiet)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        dest = tmp_path / "Anna [Lab]" / "Temp"
        dest.mkdir(parents=True)
        load = ("$ast = [System.Management.Automation.Language.Parser]::ParseFile($env:T_PS1, [ref]$null, [ref]$null); "
                "$f = $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] "
                "-and $n.Name -eq 'Save-Download' }, $true); "
                "if (@($f).Count -ne 1) { throw 'Save-Download is not in install.ps1' }; "
                "Invoke-Expression @($f)[0].Extent.Text; ")
        body_ps = "Save-Download $env:T_URL (Join-Path $env:T_DEST 'pkg.whl')"
        r = subprocess.run([pwsh, "-NoProfile", "-NonInteractive", "-Command", load + body_ps], capture_output=True,
                           text=True, errors="replace", timeout=120,
                           env={**os.environ, "T_PS1": str(_PS1), "T_DEST": str(dest),
                                "T_URL": f"http://127.0.0.1:{srv.server_address[1]}/pkg.whl",
                                "NO_PROXY": "127.0.0.1", "no_proxy": "127.0.0.1"})
        assert r.returncode == 0, r.stdout + r.stderr
        assert (dest / "pkg.whl").read_bytes() == body
    finally:
        srv.shutdown()
        srv.server_close()


# ---------------------------------------------------------------------------------------------
# 6. pythonw.exe (the icon's app) and python.exe (the installer) are one ENLENS
# ---------------------------------------------------------------------------------------------
def _windows_env(tmp_path: Path) -> tuple[Path, Path]:
    scripts = tmp_path / "uv" / "tools" / "enlens-claims" / "Scripts"
    scripts.mkdir(parents=True)
    for n in ("python.exe", "pythonw.exe"):
        (scripts / n).write_bytes(b"")
    return scripts / "python.exe", scripts / "pythonw.exe"


def test_the_plugin_names_the_console_python_and_is_not_stale_for_its_pythonw(monkeypatch, tmp_path):
    """INSTALL15-6 (NEEDS WINDOWS 5), platform-free: the icon's app runs pythonw.exe, the installer python.exe; the
    plugin compared its command with sys.executable, so after every update the app's first start rewrote it and ran
    `claude plugin ...` again. The plugin names the console python.exe of the environment (the connector talks over
    stdio), whichever of the two writes it, and neither finds it stale."""
    from enlens_claims import claude_setup

    console, gui = _windows_env(tmp_path)
    monkeypatch.setattr(claude_setup.sys, "executable", str(console))
    claude_setup.write_plugin()
    assert claude_setup.stale() == "" and claude_setup.setup_info()["ready"]
    monkeypatch.setattr(claude_setup.sys, "executable", str(gui))  # the app, started from the icon
    assert claude_setup.stale() == "", claude_setup.stale()
    assert claude_setup.setup_info()["ready"]
    claude_setup.write_plugin()
    cfg = json.loads((claude_setup.plugin_folder() / ".mcp.json").read_text(encoding="utf-8"))
    assert cfg["mcpServers"][claude_setup.SERVER]["command"] == str(console)


def test_a_plugin_of_another_environment_is_still_stale(monkeypatch, tmp_path):
    """INSTALL15-6: only the two interpreters of ONE environment count as the same; another folder's Python is stale."""
    from enlens_claims import claude_setup

    console, gui = _windows_env(tmp_path)
    other = tmp_path / "old" / "Scripts" / "python.exe"
    other.parent.mkdir(parents=True)
    other.write_bytes(b"")
    monkeypatch.setattr(claude_setup.sys, "executable", str(other))
    claude_setup.write_plugin()
    monkeypatch.setattr(claude_setup.sys, "executable", str(gui))
    assert "starts the connector with" in claude_setup.stale()


def test_the_claude_apps_entry_names_the_console_python(monkeypatch, tmp_path):
    """INSTALL15-6, sibling: the Claude desktop app's entry (mcp_server.config_block, also written by the start-up
    repair) names python.exe when the app runs pythonw.exe, and the repair leaves an entry of the same environment."""
    from enlens_claims import mcp_server

    console, gui = _windows_env(tmp_path)
    monkeypatch.setattr(mcp_server.sys, "executable", str(gui))
    assert mcp_server.config_block()["command"] == str(console)


@pytest.mark.skipif(os.name != "nt", reason="pythonw.exe and python.exe are Windows' (the Windows CI leg)")
def test_windows_the_connector_answers_initialize_with_the_plugins_python(tmp_path):
    """INSTALL15-6 (owner, Windows CI): the connector, started with the interpreter the plugin names (as Claude Code
    starts it, over stdio), answers `initialize`."""
    pytest.importorskip("mcp")
    import subprocess

    from enlens_claims import claude_setup

    claude_setup.write_plugin()
    cfg = json.loads((claude_setup.plugin_folder() / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"][
        claude_setup.SERVER]
    assert Path(cfg["command"]).name.lower() == "python.exe"
    msg = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
           "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                      "clientInfo": {"name": "test", "version": "0"}}}
    p = subprocess.Popen([cfg["command"], *cfg["args"]], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, env={**os.environ, **cfg["env"]})
    try:
        p.stdin.write((json.dumps(msg) + "\n").encode())
        p.stdin.flush()
        line = p.stdout.readline()
    finally:
        p.kill()
        p.wait(30)
    got = json.loads(line)
    assert got["id"] == 1 and "serverInfo" in got["result"], got


# ---------------------------------------------------------------------------------------------
# 7. the hand-over is proven by the token file, never by a process number alone
# ---------------------------------------------------------------------------------------------
def test_the_handover_does_not_count_a_reused_process_number_as_a_copy_that_came_back(monkeypatch, tmp_path):
    """INSTALL15-7 (NEEDS WINDOWS 4): app.json and a token file left by a copy that ended name a process number that
    another program now has (here: this very process, which runs). The hand-over counts neither as ENLENS come back
    (so the rescue window opens on Windows); only a token the app at that address accepts proves it. Faked: the
    process table (the numbers are of running processes) and the address, which answers nothing."""
    from enlens_claims import handover

    home = tmp_path / "enlens"
    home.mkdir()
    reused = os.getpid()  # a running process that is not ENLENS
    (home / "app.json").write_text(json.dumps({"url": "http://127.0.0.1:8799/", "port": 8799, "pid": reused}),
                                   encoding="utf-8")
    (home / "app-token-8799.json").write_text(json.dumps({"url": "http://127.0.0.1:8799/", "port": 8799,
                                                          "pid": reused, "token": "t" * 22, "home": str(home)}),
                                              encoding="utf-8")
    asked: list = []
    monkeypatch.setattr(handover, "_local_get", lambda url, token: asked.append(url) or False)
    job = {"info": str(home / "app.json"), "token_dir": str(home), "home": str(home)}
    assert handover._came_back(job, before=reused + 1, seconds=1.2) is False
    assert asked  # the address was asked, the number alone was not taken as proof
    monkeypatch.setattr(handover, "_local_get", lambda url, token: True)  # the app at that address accepts it
    assert handover._came_back(job, before=reused + 1, seconds=1.2) is True


# ---------------------------------------------------------------------------------------------
# 9. token files of data folders outside the profile (Windows: one folder for all of them)
# ---------------------------------------------------------------------------------------------
def _two_folders_write_tokens(monkeypatch, tmp_path, token_dir=None):
    from enlens_claims.gui import launcher

    if token_dir:
        monkeypatch.setattr(launcher, "token_dir", token_dir)
    a, b = tmp_path / "D" / "enlens-a", tmp_path / "D" / "enlens-b"
    monkeypatch.setenv("ENLENS_HOME", str(a))
    pa = launcher.write_token("http://127.0.0.1:9001/", 9001, "a" * 22)
    monkeypatch.setenv("ENLENS_HOME", str(b))
    pb = launcher.write_token("http://127.0.0.1:9002/", 9002, "b" * 22)
    seen_b = (launcher.read_token(9001), launcher.read_token(9002))
    monkeypatch.setenv("ENLENS_HOME", str(a))
    seen_a = (launcher.read_token(9001), launcher.read_token(9002))
    return pa, pb, seen_a, seen_b


def test_token_files_of_two_data_folders_in_one_folder_are_told_apart(monkeypatch, tmp_path):
    """INSTALL15-9, platform-free twin: as on Windows for data folders outside the profile, both token files go to one
    folder (LOCALAPPDATA\\ENLENS); each data folder reads only its own."""
    from enlens_claims.gui import launcher

    real = launcher.token_dir
    profile, local = tmp_path / "profile", tmp_path / "local"
    pa, pb, seen_a, seen_b = _two_folders_write_tokens(
        monkeypatch, tmp_path,
        lambda h: real(h, windows=True, profile=str(profile), local_appdata=str(local)))
    assert pa.parent == pb.parent == local / "ENLENS"
    assert seen_a == ("a" * 22, None) and seen_b == (None, "b" * 22)


@pytest.mark.skipif(os.name != "nt", reason="token files move to LOCALAPPDATA only on Windows (the Windows CI leg)")
def test_windows_token_files_of_two_data_folders_outside_the_profile(monkeypatch, tmp_path):
    """INSTALL15-9 (Windows CI): with the real environment of Windows (USERPROFILE, LOCALAPPDATA), two data folders
    outside the profile write their token files to one folder, and each is told apart."""
    profile, local = tmp_path / "profile", tmp_path / "local"
    profile.mkdir()
    monkeypatch.setenv("USERPROFILE", str(profile))
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    pa, pb, seen_a, seen_b = _two_folders_write_tokens(monkeypatch, tmp_path)
    assert pa.parent == pb.parent == local / "ENLENS"
    assert seen_a == ("a" * 22, None) and seen_b == (None, "b" * 22)


# ---------------------------------------------------------------------------------------------
# 10. a Claude Code run left going is recognised by its command line, on every system
# ---------------------------------------------------------------------------------------------
def _sleeper(*extra: str):
    import subprocess

    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", *extra])


def test_a_run_left_going_is_recognised_by_its_command_line():
    """INSTALL15-10 (runs on every leg of CI, Windows included: by NtQueryInformationProcess there, ps here): a
    process whose command line holds the run's slash command and project is that project's run; another project's
    is not; an ended one is not."""
    from enlens_claims import claude_setup

    p = _sleeper("-p", f'{claude_setup.SLASH} "Pilot 2026" --parallel 2')
    try:
        t0 = __import__("time").time()
        while not claude_setup._pid_runs_enlens(p.pid, "Pilot 2026") and __import__("time").time() - t0 < 20:
            __import__("time").sleep(0.2)
        assert claude_setup._pid_runs_enlens(p.pid, "Pilot 2026")
        assert claude_setup._pid_runs_enlens(p.pid)
        assert not claude_setup._pid_runs_enlens(p.pid, "Pilot")
    finally:
        p.kill()
        p.wait(30)
    assert not claude_setup._pid_runs_enlens(p.pid, "Pilot 2026")


def test_without_ps_a_run_left_going_is_still_recognised(monkeypatch, tmp_path):
    """INSTALL15-10: on a computer without `ps` (a small Linux), a run an earlier app started was forgotten
    (`_pid_runs_enlens` False) and went on unseen. The command line is read from /proc there (faked here: a /proc
    with this process's cmdline, and `ps` missing)."""
    import subprocess

    from enlens_claims import claude_setup, procs

    me = os.getpid()
    fake = tmp_path / "proc" / str(me)
    fake.mkdir(parents=True)
    (fake / "cmdline").write_bytes(b"node\0/usr/bin/claude\0-p\0" + f'{claude_setup.SLASH} "Pilot"'.encode() + b"\0")
    monkeypatch.setattr(procs, "PROC", tmp_path / "proc", raising=False)

    def no_ps(*a, **k):
        raise FileNotFoundError("ps")

    monkeypatch.setattr(subprocess, "run", no_ps)
    if os.name == "nt":
        pytest.skip("Windows reads command lines by its own interface")
    assert claude_setup._pid_runs_enlens(me, "Pilot")
    assert not claude_setup._pid_runs_enlens(me, "Other")


# ---------------------------------------------------------------------------------------------
# 11. a check started from a document is kept from the provider that asks, not from Anthropic alone
# ---------------------------------------------------------------------------------------------
def test_the_checks_of_a_document_are_kept_from_the_provider_that_asks(monkeypatch, ws, corpus):
    """INSTALL15-11 (notes "Not proven" 3): `docrole.kept_here` asked only whether Anthropic may read the document a
    check was started from. A connector started for Codex (ENLENS_ROUTE=codex: OpenAI reads) would show a check whose
    words come from a document that allows Anthropic only (the default). It now asks about the connector's reader."""
    from enlens_claims import access, claimcheck, docrole, ingest

    ingest.ingest(ws, [corpus], ai_access="cloud")
    doc = ws.scalar("SELECT doc_id FROM documents ORDER BY doc_id LIMIT 1")
    hid = claimcheck.create_hypothesis(ws, "Electrolyser plants create local jobs.", origin=docrole.ORIGIN,
                                       origin_id=doc)
    monkeypatch.delenv("ENLENS_ROUTE", raising=False)
    assert hid not in docrole.kept_here(ws)  # Claude may read it: shown in a Claude chat
    monkeypatch.setenv("ENLENS_ROUTE", "codex")
    assert hid in docrole.kept_here(ws) and hid in access.hidden_hypotheses(ws)
    access.set_providers_default(ws, ["anthropic", "openai"])  # the person allows OpenAI too
    assert hid not in docrole.kept_here(ws)


# ---------------------------------------------------------------------------------------------
# 12. a busy app is not a stale record
# ---------------------------------------------------------------------------------------------
def _silent_port():
    """A port that accepts connections and never answers (an app busy past any timeout)."""
    import socket

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(8)
    return s, s.getsockname()[1]


def _app_record(port: int, pid: int) -> dict:
    from enlens_claims import __version__
    from enlens_claims.gui import launcher

    info = {"url": f"http://127.0.0.1:{port}/", "port": port, "pid": pid, "version": __version__,
            "started": "2026-11-19 09:00:00"}
    launcher.info_path().parent.mkdir(parents=True, exist_ok=True)
    launcher.info_path().write_text(json.dumps(info), encoding="utf-8")
    p = launcher.token_path(port)
    p.write_text(json.dumps({"url": info["url"], "port": port, "pid": pid, "token": "T" * 30,
                             "home": str(launcher.info_path().parent)}), encoding="utf-8")
    return info


def test_a_busy_app_is_not_taken_for_a_stale_record():
    """INSTALL15-12 (review note): `launcher.running()` deleted app.json whenever the proof failed, a timeout of a busy
    app included; the icon then started a second copy of the same data folder on the next port. A timeout proves
    nothing: it asks again, and when the record's process is still an ENLENS app, the app is busy, not gone: the
    record stays and the icon opens it."""
    from enlens_claims.gui import launcher

    srv, port = _silent_port()
    app = _sleeper("enlens_claims.gui.launch", "--launcher")  # an ENLENS app by its command line
    try:
        info = _app_record(port, app.pid)
        got = launcher.running(timeout=0.3)
        assert got is not None and got["pid"] == info["pid"] and got.get("busy") is True, got
        assert launcher.info_path().exists()
    finally:
        app.kill()
        app.wait(30)
        srv.close()


def test_a_timeout_with_no_enlens_behind_the_record_is_still_stale():
    """INSTALL15-12, the other side: the address keeps silent and the record's process is no ENLENS app (it ended):
    the record is stale and removed, as before."""
    import subprocess

    from enlens_claims.gui import launcher

    srv, port = _silent_port()
    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    gone.wait()
    try:
        _app_record(port, gone.pid)
        assert launcher.running(timeout=0.3) is None
        assert not launcher.info_path().exists()
    finally:
        srv.close()


# ---------------------------------------------------------------------------------------------
# 13. while Claude Code keeps refusing the plugin, the app's start tries again once a day (or after an update)
# ---------------------------------------------------------------------------------------------
def _claude_code(monkeypatch, refuse: bool, version: str = "2.1.0 (Claude Code)") -> list:
    from enlens_claims import claude_setup

    calls: list = []

    def run(args, timeout=60):
        calls.append(args[1:])
        if args[1:] == ["--version"]:
            return 0, version
        return (1, "Error: EACCES: permission denied") if refuse else (0, "")

    monkeypatch.setattr(claude_setup, "find_claude", lambda: "/opt/claude/bin/claude")
    monkeypatch.setattr(claude_setup, "_run", run)
    return calls


def _older_plugin():
    """A plugin written by an older ENLENS (so stale)."""
    from enlens_claims import claude_setup

    if not (claude_setup.plugin_folder() / ".mcp.json").exists():
        claude_setup.write_plugin()
    pj = claude_setup.plugin_folder() / ".claude-plugin" / "plugin.json"
    pj.write_text(json.dumps({**json.loads(pj.read_text(encoding="utf-8")), "version": "0.13.0"}), encoding="utf-8")


def _refused_once(monkeypatch):
    from enlens_claims import claude_setup

    _older_plugin()
    _claude_code(monkeypatch, refuse=True)
    assert claude_setup.repair(patient=True)["refused"]


def _plugin_calls(calls: list) -> list:
    return [c for c in calls if c[:1] == ["plugin"]]


def test_the_apps_start_does_not_ask_claude_code_again_the_same_day(monkeypatch):
    """INSTALL15-13 (review note): while Claude Code kept refusing, EVERY app start rewrote the plugin and ran up to
    four `claude plugin` commands (120 s each). The app's start (patient) now waits a day, unless ENLENS or Claude
    Code changed; it still says the plugin was refused, and stale() still says so."""
    from enlens_claims import claude_setup

    _refused_once(monkeypatch)
    calls = _claude_code(monkeypatch, refuse=True)
    r = claude_setup.repair(patient=True)
    assert _plugin_calls(calls) == [], calls
    assert r["repaired"] is False and r["refused"] and r.get("waiting")
    assert claude_setup.refused_words(r) and claude_setup.stale()


@pytest.mark.parametrize("changed", ["a day later", "ENLENS updated", "Claude Code updated", "asked by a person"])
def test_claude_code_is_asked_again_after_a_day_or_an_update(monkeypatch, changed):
    """INSTALL15-13: a day after the refusal, after ENLENS's or Claude Code's version changed, or when the installer
    (post-install: not patient) asks, the plugin is offered to Claude Code again."""
    from enlens_claims import claude_setup

    _refused_once(monkeypatch)
    note = json.loads(claude_setup._refused_path().read_text(encoding="utf-8"))
    if changed == "a day later":
        note["t"] = note["t"] - 25 * 3600
    if changed == "ENLENS updated":
        note["version"] = "0.1.0"
    claude_setup._refused_path().write_text(json.dumps(note), encoding="utf-8")
    calls = _claude_code(monkeypatch, refuse=False,
                         version="2.2.0 (Claude Code)" if changed == "Claude Code updated" else "2.1.0 (Claude Code)")
    r = claude_setup.repair(patient=changed != "asked by a person")
    assert _plugin_calls(calls)[:1] == [["plugin", "marketplace", "add", str(claude_setup.folder())]], calls
    assert r["repaired"] is True


# ---------------------------------------------------------------------------------------------
# 14. the phase 1 fixer's decisions, pinned
# ---------------------------------------------------------------------------------------------
def test_post_install_exits_0_and_says_so_when_claude_code_refuses(monkeypatch, capsys, tmp_path):
    """INSTALL15-14 (phase 1 fixer's decision): `enlens post-install` ends the install or update with exit 0 when
    Claude Code refuses the plugin (the update must not fail for it), and says the plugin was not taken."""
    from enlens_claims import cli, mcp_server

    _older_plugin()  # written by an older ENLENS: post-install writes it again and offers it; Claude Code refuses
    _claude_code(monkeypatch, refuse=True)
    monkeypatch.setattr(mcp_server, "desktop_config_path", lambda: tmp_path / "no-claude-app" / "config.json")
    rc = cli.main(["post-install", "--by", "none", "--no-icon"])
    out = capsys.readouterr()
    assert rc == 0
    assert "Claude Code did not take the ENLENS plugin" in out.out + out.err
    assert "now uses this installation" not in out.out + out.err


# ---------------------------------------------------------------------------------------------
# 16. the rest of the phase 1 notes
# ---------------------------------------------------------------------------------------------
def test_claude_code_answering_already_added_counts_as_taken(monkeypatch):
    """INSTALL15-16 (notes "Not proven": `plugin marketplace add` twice): repair() and set-up assume Claude Code's add
    and install may be run again. Should Claude Code answer a second add with an error that says it is already
    there, the plugin is not "refused": the refresh that follows brings the new files."""
    from enlens_claims import claude_setup

    _older_plugin()
    monkeypatch.setattr(claude_setup, "find_claude", lambda: "/opt/claude/bin/claude")
    calls: list = []

    def run(args, timeout=60):
        calls.append(args[1:])
        if args[1:3] == ["plugin", "marketplace"] and args[3] == "add":
            return 1, "Error: Marketplace 'enlens-local' is already installed."
        if args[1:3] == ["plugin", "install"]:
            return 1, "Plugin 'enlens-run@enlens-local' is already installed"
        return (0, "2.1.0 (Claude Code)") if args[1:] == ["--version"] else (0, "")

    monkeypatch.setattr(claude_setup, "_run", run)
    r = claude_setup.repair()
    assert r["repaired"] is True, r
    assert ["plugin", "marketplace", "update", claude_setup.MARKETPLACE] in calls  # the files reach Claude Code
    steps = claude_setup.install()["steps"]
    assert all(s["ok"] for s in steps), steps


def test_prepare_queues_nothing_for_a_folder_claude_code_cannot_reach(monkeypatch, tmp_path, capsys, corpus):
    """INSTALL15-16 (notes "Not proven" 5, `_project_name`): `enlens --ws <copy of a project> prepare check ...` where
    the data folder already has a project of the folder's name: the tasks were queued, then a traceback; Claude Code
    could never reach them. Now it says why in words before anything is queued."""
    from enlens_claims import cli, home, ingest
    from enlens_claims.store import Workspace

    home.create_project("Pilot")
    copy = Workspace.create(tmp_path / "elsewhere" / "Pilot")
    ingest.ingest(copy, [corpus], ai_access="cloud")
    rc = cli.main(["--ws", str(copy.root), "prepare", "check", "Electrolysers need fresh water."])
    out = capsys.readouterr()
    assert rc == 1, out
    assert "Pilot" in out.err and "Traceback" not in out.err
    assert copy.scalar("SELECT COUNT(*) FROM hypotheses") == 0
    assert copy.scalar("SELECT COUNT(*) FROM tasks") == 0


def test_measure_takes_the_ws_given_before_it(monkeypatch, tmp_path):
    """INSTALL15-16 (notes "Not proven" 6): `enlens --ws P measure` ignored P (measure has its own --ws); P is the
    project to measure, as `enlens measure --ws P`."""
    from enlens_claims import cli, measure
    from enlens_claims.store import Workspace

    ws = Workspace.create(tmp_path / "P")
    seen: list = []
    monkeypatch.setattr(measure, "run", lambda **k: seen.append(k) or {})
    monkeypatch.setattr(measure, "to_markdown", lambda r: "")
    cli.main(["--ws", str(ws.root), "measure"])
    cli.main(["measure", "--ws", str(ws.root)])
    cli.main(["measure"])
    assert [s["project"] for s in seen] == [str(ws.root), str(ws.root), None]


def test_a_project_name_given_as_ws_is_not_told_to_init_beside_it(monkeypatch, tmp_path, capsys):
    """INSTALL15-16 (notes "Not proven" 6 and 7): `enlens --ws Pilot history` (or `enlens retractions Pilot`) with the
    app's project name said "Run `enlens --ws Pilot init` first", which makes an empty workspace in the current folder
    beside the app's project. It now names the project's folder to use, and makes nothing."""
    from enlens_claims import cli, home

    ws = home.create_project("Pilot")
    monkeypatch.chdir(tmp_path)
    for argv in (["--ws", "Pilot", "history"], ["retractions", "Pilot"]):
        rc = cli.main(argv)
        err = capsys.readouterr().err
        assert rc == 1
        assert "init" not in err and str(ws.root) in err, err
    assert not (tmp_path / "Pilot").exists()


def test_reset_corpus_says_everything_it_deletes(ws, capsys):
    """INSTALL15-16 (notes "Not proven" 9): `reset-corpus` also deletes every hypothesis, a person's labels and
    judgements; its prompt named only "documents, passages, claims, verifications and their tasks"."""
    from enlens_claims import cli

    assert cli.main(["--ws", str(ws.root), "reset-corpus"]) == 1
    said = capsys.readouterr().out
    for word in ("hypotheses", "judgements", "labels", "themes"):
        assert word in said, said


def test_stable_is_never_offered_a_release_candidate(monkeypatch):
    """INSTALL15-16 (notes "Not proven" 10): the stable channel took GitHub's /releases/latest as it came; a release
    candidate published without the pre-release flag (it happened once: v0.19.16) was offered to everyone. Stable
    now takes the highest published release that is no candidate."""
    from enlens_claims import update

    rels = [{"tag_name": "v0.21.0rc1", "prerelease": False, "draft": False, "assets": []},
            {"tag_name": "v0.20.3", "prerelease": False, "draft": False, "assets": [
                {"name": "enlens_claims-0.20.3-py3-none-any.whl", "browser_download_url": "w", "url": "a"}]},
            {"tag_name": "v0.20.2", "prerelease": False, "draft": False, "assets": []}]

    def fetch(url):
        return json.dumps(rels[0] if url.endswith("/latest") else rels).encode()

    got = update.latest_release(fetch, channel="stable")
    assert got["version"] == "0.20.3" and got["wheel"].startswith("enlens_claims-0.20.3"), got
    assert update.latest_release(fetch, channel="early")["version"] == "0.21.0rc1"


@pytest.mark.parametrize("content", ["﻿{\"mcpServers\": {\"other\": {\"command\": \"x\"}}}", "[1, 2]",
                                     "{\"mcpServers\": null}"])
def test_enlens_mcp_install_claude_desktop_on_odd_configs(monkeypatch, tmp_path, capsys, content):
    """INSTALL15-16 (notes "Not proven" 11): a config with a byte order mark is read (and its other connector kept);
    one that is a list, or whose "mcpServers" is null, is left untouched with words and exit 1, never a traceback."""
    from enlens_claims import mcp_server

    cfg = tmp_path / "Claude" / "claude_desktop_config.json"
    cfg.parent.mkdir()
    cfg.write_text(content, encoding="utf-8")
    monkeypatch.setattr(mcp_server, "desktop_config_path", lambda: cfg)
    rc = mcp_server.main(["--install-claude-desktop"])
    out = capsys.readouterr()
    if content.startswith("﻿"):
        assert rc == 0, out.err
        servers = json.loads(cfg.read_text(encoding="utf-8"))["mcpServers"]
        assert set(servers) == {"other", "enlens"}
    else:
        assert rc == 1 and "Problem:" in out.err and "Traceback" not in out.err
        assert cfg.read_text(encoding="utf-8") == content


def test_the_linux_desktop_entry_keeps_a_percent_sign(tmp_path):
    """INSTALL15-16 (notes "Not proven" 12): the freedesktop Exec key reads % as a field code (%f, %u...), so a data
    folder "100% sure" must be written %% there."""
    from enlens_claims.gui import launcher

    data = str(tmp_path / "100% sure")
    made = launcher._desktop_entry(tmp_path / "enlens.desktop", "/usr/bin/python3", ["-m", "x", "--home", data])
    line = [ln for ln in made.read_text(encoding="utf-8").splitlines() if ln.startswith("Exec=")][0]
    assert "100%% sure" in line and "100% sure" not in line.replace("%%", "")


def test_check_several_from_the_command_line_reads_a_one_column_csv_by_its_header(ws, tmp_path):
    """INSTALL15-16 (notes "Not proven" 13, passed to the checks area: CHECKS-8): the command line's `prepare check
    --file` and `batch` read hypotheses with the same `claimcheck.parse_batch`, which reads a one-column CSV headed
    "hypothesis" by its header."""
    from enlens_claims import claimcheck

    items = claimcheck.parse_batch('hypothesis\n"Water, and land, are scarce."\nJobs grow.\n')
    assert [i["text"] for i in items] == ["Water, and land, are scarce.", "Jobs grow."]


def test_the_command_line_counts_at_settings_strictness_and_threshold_wins(monkeypatch, ws, corpus, capsys):
    """INSTALL15-16 (review note, surface.md: the command line now uses the data folder's Strictness, also for a --ws
    project kept elsewhere; --threshold still wins): both, for one project outside the data folder."""
    from enlens_claims import cli, home, ingest

    home.update_settings({"threshold": 0.8})
    ingest.ingest(ws, [corpus], ai_access="cloud")
    claim = "Green hydrogen production can increase water stress in arid regions."
    assert cli.main(["--ws", str(ws.root), "check", claim, "--backend", "baseline", "--no-expand"]) == 0
    assert json.loads(capsys.readouterr().out)["confidence_threshold"] == 0.8
    assert cli.main(["--ws", str(ws.root), "check", claim, "--backend", "baseline", "--no-expand",
                     "--threshold", "0.5"]) == 0
    assert json.loads(capsys.readouterr().out)["confidence_threshold"] == 0.5
