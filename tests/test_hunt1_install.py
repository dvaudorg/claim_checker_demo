"""Hunt phase 1, area `install`: installing and updating ENLENS, starting it, the command line and the connector.

Each test asserts what ENLENS should do and fails today for the reason in its docstring. Nothing here touches a real
Claude Code, Claude app, uv, network or data folder: the conftest guards apply, and the programs ENLENS would start
are stand-ins (a faked subprocess run, a faked page at the app's address).
"""
from __future__ import annotations

import errno
import json
import subprocess
import sys
import types
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from enlens_claims import __version__


# ---------------------------------------------------------------------------------------------
# one running copy, found truthfully
# ---------------------------------------------------------------------------------------------
def _another_enlens_answers(monkeypatch, port: int) -> None:
    """The address answers as an ENLENS app of ANOTHER data folder does: its page, and 401 for any call with a
    token that is not its own."""
    def urlopen(req, timeout=None, *a, **k):
        url = req if isinstance(req, str) else req.full_url
        if url.rstrip("/") == f"http://127.0.0.1:{port}":
            class Page:
                def __enter__(self):
                    return self

                def __exit__(self, *exc):
                    return False

                def read(self, n=-1):
                    return (b'<!doctype html><meta name="enlens-version" content="' + __version__.encode()
                            + b'"><title>ENLENS</title>')
            return Page()
        raise urllib.error.HTTPError(url, 401, "Unauthorized", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)


def test_a_crashed_copys_record_does_not_stop_enlens_from_starting(monkeypatch):
    """ENLENS crashed (or the computer restarted) and left app.json; another ENLENS (another data folder, or another
    account) now has that port. The icon trusts the page alone and says "already running" (launcher.py:54 `running`)."""
    from enlens_claims.gui import launch, launcher, server

    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    gone.wait()  # the process the record names has ended
    info = launcher.info_path()
    info.parent.mkdir(parents=True, exist_ok=True)
    info.write_text(json.dumps({"url": "http://127.0.0.1:8765/", "port": 8765, "pid": gone.pid,
                                "version": __version__, "started": "2026-11-18 09:00:00"}), encoding="utf-8")
    _another_enlens_answers(monkeypatch, 8765)
    started: list = []
    monkeypatch.setattr(server, "serve", lambda *a, **k: started.append((a, k)) or 0)
    monkeypatch.setattr(launcher, "detach", lambda: None)
    monkeypatch.setattr(launcher, "log_to_file", lambda: None)
    monkeypatch.setattr(launcher, "browse", lambda target: None)

    assert launch.main(["--launcher", "--headless"]) == 0
    assert started, "the icon opened another data folder's ENLENS instead of starting this one"


def _outside_quotes(line: str) -> str:
    """What cmd.exe reads outside double quotes in one line of a command file."""
    out, inside = [], False
    for ch in line:
        if ch == '"':
            inside = not inside
        elif not inside:
            out.append(ch)
    return "".join(out)


def test_the_windows_command_file_keeps_a_data_folder_with_an_ampersand_whole(monkeypatch, tmp_path):
    """The icon's last fallback on Windows (no Shell link, no PowerShell) writes ENLENS.cmd with list2cmdline, which
    quotes only spaces: a data folder such as D:\\R&D\\enlens is cut at "&" and cmd runs "D\\enlens" as a command of
    its own (launcher.py:517 `_windows_shortcut`)."""
    from enlens_claims.gui import launcher

    def no_powershell(*a, **k):
        raise OSError("powershell is not on this computer")

    monkeypatch.setattr(launcher, "_com_shortcut", lambda *a, **k: False)
    monkeypatch.setattr(launcher.subprocess, "run", no_powershell)
    data = tmp_path / "R&D" / "enlens"
    made = launcher.make_launcher(str(data), False, [tmp_path / "desk"], python=sys.executable, platform="win32")
    assert made[0].suffix == ".cmd"
    start = [ln for ln in made[0].read_bytes().decode("utf-8").splitlines() if ln.startswith("start ")][0]
    assert "--home" in start
    assert "&" not in _outside_quotes(start).replace("^&", ""), start  # quoted, or escaped as ^&


# ---------------------------------------------------------------------------------------------
# updating
# ---------------------------------------------------------------------------------------------
def test_the_handover_sees_an_app_started_from_a_terminal_come_back(tmp_path):
    """On Windows, an app started with `enlens-gui` (not the icon) is updated by the hand-over, which starts it again
    without --launcher; that app never writes app.json, so the hand-over says it did not come back and opens the
    PowerShell window that installs ENLENS again (handover.py:180 `_came_back`, server.py:2459)."""
    import os
    import signal
    import socket
    import time

    from enlens_claims import handover
    from enlens_claims.gui import launcher, server

    with socket.socket() as sk:
        sk.bind(("127.0.0.1", 0))
        port = sk.getsockname()[1]
    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    gone.wait()  # the app that pressed Update has quit
    job = {"from": "0.0.1", "version": __version__, "folder": str(tmp_path), "pids": [gone.pid], "env_dir": "",
           "install": [sys.executable, "-c", "pass"], "env": {}, "post": [],
           "start": server.restart_command("127.0.0.1", port, False),  # what handover_command gives such an app
           "info": str(launcher.info_path()), "result": str(tmp_path / "result.json"),
           "log": str(tmp_path / "update.log"), "install_url": "", "wait": 5, "free_wait": 0, "tries": 1,
           "retry_after": 0, "settle": 0, "come_back": 20}
    try:
        r = handover.run(job)
        t0 = time.time()
        while launcher.read_token(port) is None and time.time() - t0 < 20:
            time.sleep(0.2)
        assert launcher.read_token(port), "the app did not start at all (not the defect this test is about)"
        assert r["installed"] is True
        assert r["restarted"] is True, r  # it did come back: no rescue window, no second install
    finally:
        try:
            pid = json.loads(launcher.token_path(port).read_text(encoding="utf-8"))["pid"]
            os.kill(pid, signal.SIGTERM)
        except (OSError, ValueError, KeyError):
            pass


# ---------------------------------------------------------------------------------------------
# set-up of what is outside ENLENS
# ---------------------------------------------------------------------------------------------
def test_post_install_does_not_say_claude_code_uses_a_plugin_it_refused(monkeypatch, capsys, tmp_path):
    """After an install or update, the plugin is written again and Claude Code refuses to add it; post-install still
    prints "The Claude Code plugin now uses this installation." (installation.py:169, claude_setup.py:740 `repair`)."""
    from enlens_claims import claude_setup, cli, mcp_server

    claude_setup.write_plugin()
    pj = claude_setup.plugin_folder() / ".claude-plugin" / "plugin.json"
    pj.write_text(json.dumps({**json.loads(pj.read_text(encoding="utf-8")), "version": "0.13.0"}), encoding="utf-8")
    assert claude_setup.stale()  # written by an older ENLENS: post-install writes it again and re-adds it

    calls: list = []

    def run(args, timeout=60):
        calls.append(args[1:])
        if args[1:3] == ["plugin", "marketplace"]:
            return 1, "Error: Failed to add marketplace: EACCES: permission denied"
        return 0, ""

    monkeypatch.setattr(claude_setup, "find_claude", lambda: "/opt/claude/bin/claude")
    monkeypatch.setattr(claude_setup, "_run", run)
    monkeypatch.setattr(mcp_server, "desktop_config_path", lambda: tmp_path / "no-claude-app" / "config.json")

    cli.main(["post-install", "--by", "none", "--no-icon"])
    out = capsys.readouterr()
    assert calls and calls[0][:3] == ["plugin", "marketplace", "add"]  # Claude Code was asked, and said no
    assert "now uses this installation" not in out.out + out.err


def test_a_full_disk_while_the_connector_is_added_keeps_the_claude_apps_other_connectors(monkeypatch, tmp_path):
    """`enlens-mcp --install-claude-desktop` (and repair_desktop at every start) writes claude_desktop_config.json in
    place: a full disk or a crash mid-write leaves it cut short, and the Claude app loses every connector
    (mcp_server.py:702 `install_desktop`)."""
    from enlens_claims import mcp_server

    cfg = tmp_path / "Claude" / "claude_desktop_config.json"
    cfg.parent.mkdir()
    theirs = {"mcpServers": {"filesystem": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem"]},
                             "notes": {"command": "/usr/local/bin/notes-mcp"}},
              "globalShortcut": "Ctrl+Space"}
    cfg.write_text(json.dumps(theirs, indent=2), encoding="utf-8")
    real = Path.write_text

    def disk_full(self, data, *a, **k):
        if Path(self) == cfg:  # the file is opened for writing (emptied), part is written, then the disk is full
            with open(self, "w", encoding="utf-8") as f:
                f.write(data[:12])
            raise OSError(errno.ENOSPC, "No space left on device")
        return real(self, data, *a, **k)

    monkeypatch.setattr(Path, "write_text", disk_full)
    try:
        mcp_server.install_desktop(cfg)
    except OSError:
        pass  # the failure itself may be reported; the person's file must survive it
    monkeypatch.setattr(Path, "write_text", real)
    kept = json.loads(cfg.read_text(encoding="utf-8"))
    assert kept["mcpServers"]["filesystem"] == theirs["mcpServers"]["filesystem"]
    assert kept["mcpServers"]["notes"] == theirs["mcpServers"]["notes"] and kept["globalShortcut"] == "Ctrl+Space"


# ---------------------------------------------------------------------------------------------
# the connector
# ---------------------------------------------------------------------------------------------
def test_the_connector_reports_a_check_at_the_persons_strictness(monkeypatch, tmp_path, corpus):
    """The person set Strictness to 80% ("applies to every result", settings.md). A grade made 70% sure does not count
    in the app, but get_check tells Claude the check is supported: the connector reads the project file's 0.6, never
    the setting (mcp_server.py:208 `_summary`, check_results.py:25 `_threshold`)."""
    pytest.importorskip("mcp")
    import asyncio

    from mcp import Client

    from enlens_claims import claimcheck, home
    from enlens_claims.mcp_server import build_server

    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    home.update_settings({"threshold": 0.8})
    claim = "Green hydrogen production can increase water stress in arid regions."

    async def run():
        async with Client(build_server()) as c:
            made = await c.call_tool("create_project", {"name": "Demo", "sources_path": str(corpus),
                                                        "ai_access": "cloud"})
            assert not made.is_error, made.content[0].text
            start = json.loads((await c.call_tool("start_check", {"claim": claim, "passages": 2,
                                                                  "search_terms": ["freshwater", "water scarcity"]})
                                ).content[0].text)
            quote = " ".join(start["passages"][0]["text"].split()[:6])
            sent = await c.call_tool("submit_grades", {"check_id": start["check_id"], "summary": "Stated in P1.",
                                                       "grades": [{"passage": 1, "verdict": "supports",
                                                                   "confidence": 0.7, "quote": quote}]})
            assert json.loads(sent.content[0].text)["accepted"] is True
            got = json.loads((await c.call_tool("get_check", {"check_id": start["check_id"]})).content[0].text)
            return start["check_id"], got

    check_id, got = asyncio.run(run())
    ws = home.open_project("Demo")
    hyp = ws.scalar("SELECT hyp_id FROM user_claims WHERE claim_id=?", (check_id,))
    in_the_app = claimcheck.hypothesis_result(ws, hyp, home.load_settings()["threshold"])["status"]  # server.py:1024
    assert in_the_app != "supported"  # 70% sure, strictness 80%: not counted
    assert got["status"] == in_the_app, (got["status"], in_the_app)


# ---------------------------------------------------------------------------------------------
# the command line tells the truth
# ---------------------------------------------------------------------------------------------
def test_ingest_of_a_path_that_does_not_exist_fails_in_words(ws, tmp_path, capsys):
    """`enlens --ws P ingest ~/Reports/typo` adds nothing, prints {"files": 0, ...} and exits 0: a mistyped path looks
    like a folder without documents (cli.py:582, ingest.py:1258 `discover`). The connector refuses it in words."""
    from enlens_claims import cli

    missing = tmp_path / "Reports" / "hydrogen_sources_2026"
    rc = cli.main(["--ws", str(ws.root), "ingest", str(missing)])
    out = capsys.readouterr()
    assert rc != 0
    assert str(missing) in out.err or missing.name in out.err


# ---------------------------------------------------------------------------------------------
# add-ons
# ---------------------------------------------------------------------------------------------
def test_an_add_on_column_name_ending_in_a_newline_is_refused_in_words(monkeypatch, tmp_path):
    """addons.py:208 `_NAME` ends in `$`, so ("drafts", "ai_note\\n", "TEXT") passes the check; the first opening adds
    "ai_note", every later one adds it again and fails with "duplicate column name": no project opens or is made."""
    from enlens_claims import addons
    from enlens_claims.store import Workspace

    mod = types.ModuleType("fieldnotes_addon")
    mod.SCHEMA = "CREATE TABLE IF NOT EXISTS drafts(draft_id TEXT PRIMARY KEY, title TEXT);"
    mod.MIGRATIONS = [("drafts", "ai_note\n", "TEXT")]
    monkeypatch.setattr(addons, "_loaded", [("fieldnotes", mod)])

    with pytest.raises(ValueError, match="cannot add"):
        Workspace.create(tmp_path / "project")
