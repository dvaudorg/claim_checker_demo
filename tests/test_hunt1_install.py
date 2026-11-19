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


# ---------------------------------------------------------------------------------------------
# fixer's tests (hunt phase 1, install): siblings of the claims above
# ---------------------------------------------------------------------------------------------
_CLAIM = "Green hydrogen production can increase water stress in arid regions."


def _graded_check(monkeypatch, tmp_path, corpus, grades):
    """A project made through the connector and one check graded there; `grades` is a list of (verdict, confidence),
    one per passage shown (fewer passages: the rest are left out). Returns (check_id, workspace)."""
    import asyncio

    from mcp import Client

    from enlens_claims import home
    from enlens_claims.mcp_server import build_server

    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    home.update_settings({"threshold": 0.8})  # off its default (0.6)

    async def run():
        async with Client(build_server()) as c:
            made = await c.call_tool("create_project", {"name": "Demo", "sources_path": str(corpus), "ai_access": "cloud"})
            assert not made.is_error, made.content[0].text
            start = json.loads((await c.call_tool("start_check", {
                "claim": _CLAIM, "passages": 6, "per_document": 2,
                "search_terms": ["freshwater", "water scarcity", "jobs", "birds"]})).content[0].text)
            sent = [{"passage": n, "verdict": v, "confidence": conf,
                     "quote": " ".join(p["text"].split()[:6])}
                    for n, (p, (v, conf)) in enumerate(zip(start["passages"], grades), 1)]
            r = await c.call_tool("submit_grades", {"check_id": start["check_id"], "summary": "Read.", "grades": sent})
            assert json.loads(r.content[0].text)["accepted"] is True, r.content[0].text
            return start["check_id"]

    check_id = asyncio.run(run())
    return check_id, home.open_project("Demo")


def _connector(tool, args):
    import asyncio

    from mcp import Client

    from enlens_claims.mcp_server import build_server

    async def run():
        async with Client(build_server()) as c:
            r = await c.call_tool(tool, args)
            assert not r.is_error, r.content[0].text
            return json.loads(r.content[0].text)

    return asyncio.run(run())


def test_the_connector_and_the_app_report_one_check_alike(monkeypatch, tmp_path, corpus):
    """INSTALL-1, field by field: with Strictness off its default, what get_check and list_checks tell Claude about one
    check is what the app's result page (api_checks.get_hypothesis: `hypothesis_result` at Settings' strictness)
    shows: status, status at any confidence, the strictness, which excerpts count, the excerpts of a document marked
    non-scientific (shown, never counted) and those of a document kept on this computer (counts only)."""
    pytest.importorskip("mcp")
    from enlens_claims import claimcheck, docrole, home

    grades = [("supports", 0.7), ("supports", 0.9), ("refutes", 0.65), ("partially_supports", 0.85),
              ("supports", 0.95), ("refutes", 0.9)]
    check_id, ws = _graded_check(monkeypatch, tmp_path, corpus, grades)
    hyp = ws.scalar("SELECT hyp_id FROM user_claims WHERE claim_id=?", (check_id,))
    docs = list(dict.fromkeys(p["doc_id"] for p in claimcheck.result(ws, check_id)["passages"] if p["verdict"]))
    assert len(docs) >= 2
    docrole.set_nonscientific(ws, docs[0], True)
    with ws.connect() as cx:  # the person keeps another document on this computer (Only a local AI)
        cx.execute("UPDATE documents SET ai_access='local' WHERE doc_id=?", (docs[1],))

    app = claimcheck.hypothesis_result(ws, hyp, home.load_settings()["threshold"])  # api_checks.get_hypothesis
    got = _connector("get_check", {"check_id": check_id})
    listed = {c["check_id"]: c for c in _connector("list_checks", {"project": "Demo"})["checks"]}
    assert got["confidence_threshold"] == app["threshold"] == 0.8
    assert got["status"] == app["status"] == listed[check_id]["status"], (got["status"], app["status"])
    assert got["status_at_any_confidence"] == app["status_any"]
    items = [x for x in app["parts"][0]["passages"] if x["verdict"]]
    shown = sorted((x["quote"], x["verdict"], x["counted"], bool(x["nonscientific"])) for x in items
                   if x["access"] == "cloud")
    assert sorted((e["quote"], e["grade"], e["counted"], bool(e.get("non_scientific"))) for e in got["evidence"]) == shown
    kept = {}
    for x in items:
        if x["access"] != "cloud" and not x["nonscientific"]:
            kept[x["verdict"]] = kept.get(x["verdict"], 0) + 1
    assert got.get("restricted_evidence", {}) == kept
    if any(x["nonscientific"] for x in items):
        assert got["status_counting_non_scientific"] == app["status_all_sources"]


def test_the_command_line_history_counts_at_the_persons_strictness(monkeypatch, tmp_path, corpus, capsys):
    """INSTALL-1's sibling on the command line: `enlens history` listed the statuses at the project file's 0.6, the
    app at the person's Strictness; it now uses Settings (as the manual says) and names the value it used."""
    pytest.importorskip("mcp")
    from enlens_claims import claimcheck, cli, home

    check_id, ws = _graded_check(monkeypatch, tmp_path, corpus, [("supports", 0.7)])
    hyp = ws.scalar("SELECT hyp_id FROM user_claims WHERE claim_id=?", (check_id,))
    in_the_app = claimcheck.hypothesis_result(ws, hyp, home.load_settings()["threshold"])["status"]
    assert in_the_app != "supported"
    capsys.readouterr()
    assert cli.main(["--ws", str(ws.root), "history"]) == 0
    rows = json.loads(capsys.readouterr().out)
    row = next(r for r in rows if r["hyp_id"] == hyp)
    assert row["status"] == in_the_app and row["confidence_threshold"] == 0.8


def test_the_command_line_check_counts_at_the_persons_strictness_and_says_so(monkeypatch, tmp_path, ws, corpus, capsys):
    """INSTALL-1's sibling: `enlens check` (offline demo backend) prints the strictness it counted at, Settings' one."""
    from enlens_claims import cli, home, ingest

    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    home.update_settings({"threshold": 0.8})
    ingest.ingest(ws, [corpus])
    assert cli.main(["--ws", str(ws.root), "check", _CLAIM, "--backend", "baseline", "--no-expand"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["confidence_threshold"] == 0.8


def test_the_command_lines_annotated_copy_counts_at_the_persons_strictness(monkeypatch, tmp_path, ws, corpus):
    """INSTALL-1's sibling: `enlens annotate` wrote "not counted at this strictness" by the project file's 0.6; the app's
    own copy (api_explore) passes Settings' strictness."""
    from enlens_claims import annotate, cli, home, ingest

    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    home.update_settings({"threshold": 0.8})
    ingest.ingest(ws, [corpus])
    doc = ws.scalar("SELECT doc_id FROM documents ORDER BY doc_id")
    seen = {}

    def fake(ws_, doc, hyp, layers, framework, concept, use_pdfminer=True, threshold=None):
        seen["threshold"] = threshold
        return {"body": b"", "content_type": "application/pdf", "marks": 0, "placed": 0, "method": "", "missing": 0}

    monkeypatch.setattr(annotate, "annotate_document", fake)
    cli.main(["--ws", str(ws.root), "annotate", doc, "--out", str(tmp_path / "out.pdf")])
    assert seen["threshold"] == 0.8


def test_an_add_on_column_named_in_another_case_is_added_once(monkeypatch, tmp_path):
    """INSTALL-8's sibling: SQLite names know no case, `_add_columns` compared them with case, so an add-on's
    ("drafts", "AI_Note") beside a SCHEMA column "ai_note" was added again at every opening ("duplicate column name")."""
    from enlens_claims import addons
    from enlens_claims.store import Workspace

    mod = types.ModuleType("fieldnotes_addon")
    mod.SCHEMA = "CREATE TABLE IF NOT EXISTS drafts(draft_id TEXT PRIMARY KEY, ai_note TEXT);"
    mod.MIGRATIONS = [("Drafts", "AI_Note", "TEXT"), ("drafts", "Title", "TEXT"), ("DRAFTS", "title", "TEXT")]
    monkeypatch.setattr(addons, "_loaded", [("fieldnotes", mod)])
    ws = Workspace.create(tmp_path / "project")
    Workspace.open(ws.root)  # a second opening adds nothing
    cols = [r[1].lower() for r in ws.query("PRAGMA table_info(drafts)")]
    assert cols.count("ai_note") == 1 and cols.count("title") == 1


@pytest.mark.parametrize("mg", [("drafts\n", "ai_note", "TEXT"), ("drafts", "ai_note", "TEXT\n"),
                                ("drafts", "ai note", "TEXT"), ("drafts", 5, "TEXT")])
def test_an_add_on_table_or_type_with_a_stray_character_is_refused_in_words(monkeypatch, tmp_path, mg):
    """INSTALL-8's sibling: the table and the type were matched with `$` too; any name that is not plain is refused,
    naming the add-on."""
    from enlens_claims import addons
    from enlens_claims.store import Workspace

    mod = types.ModuleType("fieldnotes_addon")
    mod.SCHEMA = "CREATE TABLE IF NOT EXISTS drafts(draft_id TEXT PRIMARY KEY);"
    mod.MIGRATIONS = [mg]
    monkeypatch.setattr(addons, "_loaded", [("fieldnotes", mod)])
    with pytest.raises(ValueError, match="fieldnotes names a column ENLENS cannot add"):
        Workspace.create(tmp_path / "project")


# INSTALL-6's sweep: every command of `enlens`, given something that fails (an unknown project, a missing file, an
# unknown id, a refused action), exits non-zero. ({ws}: a real empty project; {tmp}: a temporary folder.)
_FAILING_COMMANDS = [
    ["--ws", "{tmp}/no-such-project", "status"],                      # an unknown project
    ["--ws", "{ws}", "ingest", "{tmp}/missing"],                      # INSTALL-6 itself
    ["--ws", "{ws}", "ingest", "{tmp}/missing", "{tmp}/corpus-empty"],  # one missing among several
    ["--ws", "{ws}", "load-vca", "{tmp}/missing.xlsx"],
    ["--ws", "{ws}", "import-results", "{tmp}/missing.jsonl"],
    ["--ws", "{ws}", "check-results", "{tmp}/missing.jsonl"],
    ["--ws", "{ws}", "review-import", "{tmp}/missing.csv"],
    ["--ws", "{ws}", "batch", "{tmp}/missing.txt", "--backend", "baseline"],
    ["--ws", "{ws}", "prepare", "check", "--file", "{tmp}/missing.txt"],
    ["--ws", "{ws}", "import-qdc", "{tmp}/missing.qdc"],
    ["--ws", "{ws}", "export-qdc", "--framework", "no-such-codebook", "--out", "{tmp}/x.qdc"],
    ["--ws", "{ws}", "concept", "no such concept at all"],
    ["--ws", "{ws}", "annotate", "no-such-document", "--out", "{tmp}/x.pdf"],
    ["--ws", "{ws}", "concept-map", "--theme", "nonsense"],
    ["--ws", "{ws}", "reset-corpus"],                                 # refused without --yes
    ["--ws", "{ws}", "make-tasks", "audit-vca"],                      # refused without --model
    ["--ws", "{ws}", "measure", "--folder", "{tmp}/missing"],
    ["--ws", "{ws}", "measure", "--ws", "{tmp}/missing"],
    ["--ws", "{ws}", "resolve", "no-such-document", "--backend", "baseline"],
    ["--ws", "{ws}", "search", "water", "--out", "{tmp}/no-folder/x.csv"],
    ["--ws", "{ws}", "queue", "first", "no-such-kind"],
    ["--ws", "{ws}", "retractions", "{tmp}/no-such-project"],
    ["--ws", "{ws}", "import-project", "{tmp}/missing.zip"],
    ["--ws", "{ws}", "import-all", "{tmp}/missing.zip", "--moving"],
    ["--ws", "{ws}", "bring-in", "{tmp}/missing.zip"],
    ["--ws", "{ws}", "validate", "score", "--project", "No such project"],
    ["--ws", "{ws}", "history", "--csv", "{tmp}/no-folder/x.csv"],
    ["--ws", "{ws}", "export-project", "{tmp}/no-folder/x.zip"],
]


@pytest.mark.parametrize("argv", _FAILING_COMMANDS, ids=[" ".join(a[2:4]) for a in _FAILING_COMMANDS])
def test_every_command_that_fails_exits_non_zero(monkeypatch, tmp_path, ws, argv, capsys):
    from enlens_claims import cli

    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    (tmp_path / "corpus-empty").mkdir()
    args = [x.replace("{ws}", str(ws.root)).replace("{tmp}", str(tmp_path)) for x in argv]
    try:
        rc = cli.main(args)
    except SystemExit as e:  # argparse, or a command that stops with words
        rc = e.code if isinstance(e.code, int) else 1
    except Exception as e:  # noqa: BLE001: a traceback ends `enlens` with 1 too, but says nothing a person can act on
        pytest.fail(f"{argv[2:]} ended in a traceback: {type(e).__name__}: {e}")
    assert rc not in (0, None), (argv[2:], capsys.readouterr())


def _program_reads(arg: str) -> str:
    """The one argument a program reads from `arg` (the Microsoft C rules Python follows on Windows, 2008 and later)."""
    out, i, inside = [], 0, False
    while i < len(arg):
        c = arg[i]
        if c == "\\":
            j = i
            while j < len(arg) and arg[j] == "\\":
                j += 1
            n = j - i
            if j < len(arg) and arg[j] == '"':
                out.append("\\" * (n // 2))
                if n % 2:
                    out.append('"')
                    j += 1
            else:
                out.append("\\" * n)
            i = j
        elif c == '"':
            if inside and arg[i + 1:i + 2] == '"':
                out.append('"')
                i += 2
            else:
                inside = not inside
                i += 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


@pytest.mark.parametrize("arg", [
    r"C:\Program Files\ENLENS\python.exe", r"D:\R&D\enlens", "a|b", "a<b>c", "caret^here", "100%", "%PATH%",
    "%%", "wow!", "it's", r"C:\data\\", "C:\\data\\", 'say "hi"', 'back\\"slash', "(paren)", r"C:\Users\Kovács Ábel",
    "--home", "", "tab\there"])
def test_an_argument_quoted_for_a_command_file_reads_back_whole(arg):
    """INSTALL-7's helper, table-driven: cmd.exe sees nothing of the argument outside double quotes (so & | < > ^ are
    themselves), every % is doubled (a command file expands %NAME% even in quotes), and the program reads back exactly
    the argument (a trailing backslash does not swallow the closing quote; a " stays a ")."""
    from enlens_claims.procs import cmd_quote

    q = cmd_quote(arg)
    assert _outside_quotes(q) == "", q
    assert "%" not in q.replace("%%", ""), q
    assert _program_reads(q.replace("%%", "%")) == arg, q


def test_an_argument_with_a_line_break_is_refused_for_a_command_file():
    from enlens_claims.procs import cmd_quote

    with pytest.raises(ValueError):
        cmd_quote("one\ntwo")


def test_the_windows_command_file_quotes_every_argument_for_cmd(monkeypatch, tmp_path):
    """INSTALL-7, the whole line: a % and a ! in the data folder reach ENLENS as they are."""
    from enlens_claims.gui import launcher

    def no_powershell(*a, **k):
        raise OSError("powershell is not on this computer")

    monkeypatch.setattr(launcher, "_com_shortcut", lambda *a, **k: False)
    monkeypatch.setattr(launcher.subprocess, "run", no_powershell)
    data = tmp_path / "100% sure!" / "R&D"
    made = launcher.make_launcher(str(data), False, [tmp_path / "desk"], python=sys.executable, platform="win32")
    text = made[0].read_bytes().decode("utf-8")
    start = [ln for ln in text.splitlines() if ln.startswith("start ")][0]
    assert "setlocal DisableDelayedExpansion" in text.split("start ")[0]
    assert _outside_quotes(start).replace(" ", "") == "start", start  # every argument inside quotes
    assert "100%% sure!" in start


@pytest.mark.parametrize("text", ['{"mcpServers": {"notes": {"command": "x"}},', '[1, 2]', '{"mcpServers": null}',
                                  '{"mcpServers": ["x"]}'])
def test_a_claude_app_config_enlens_cannot_read_is_left_alone_and_said(monkeypatch, tmp_path, capsys, text):
    """INSTALL-4's sibling: a config that does not parse, or is not the settings object ENLENS knows, ended
    `enlens-mcp --install-claude-desktop` in a traceback; it is left exactly as it was, and the words say so."""
    from enlens_claims import mcp_server

    cfg = tmp_path / "Claude" / "claude_desktop_config.json"
    cfg.parent.mkdir()
    cfg.write_text(text, encoding="utf-8")
    monkeypatch.setattr(mcp_server, "desktop_config_path", lambda: cfg)
    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    assert mcp_server.main(["--install-claude-desktop"]) == 1
    assert cfg.read_text(encoding="utf-8") == text
    assert "left it as it is" in capsys.readouterr().err


def test_a_claude_app_config_with_a_byte_order_mark_keeps_its_other_keys(monkeypatch, tmp_path):
    """INSTALL-4's sibling: a config saved with a byte order mark (Notepad) is read, and every key ENLENS does not
    know is kept; the file's permissions too."""
    import os
    import stat

    from enlens_claims import mcp_server

    cfg = tmp_path / "claude_desktop_config.json"
    theirs = {"mcpServers": {"notes": {"command": "n", "unknown": [1]}}, "theme": "dark", "x": {"y": None}}
    cfg.write_bytes(b"\xef\xbb\xbf" + json.dumps(theirs).encode())
    os.chmod(cfg, 0o640)
    mcp_server.install_desktop(cfg)
    got = json.loads(cfg.read_text(encoding="utf-8"))
    assert got["mcpServers"]["notes"] == theirs["mcpServers"]["notes"] and got["theme"] == "dark" and got["x"] == {"y": None}
    assert "enlens" in got["mcpServers"] and cfg.with_suffix(".json.bak").read_bytes().startswith(b"\xef\xbb\xbf")
    if os.name != "nt":
        assert stat.S_IMODE(cfg.stat().st_mode) == 0o640
    assert [p.name for p in tmp_path.iterdir() if p.name.endswith(".part")] == []


def test_a_claude_app_config_that_is_a_link_stays_a_link(tmp_path):
    """INSTALL-4's sibling: written beside and put in place, a config kept elsewhere through a link (a dotfiles
    folder) must be changed where it is, not replaced by a file of its own."""
    import os

    from enlens_claims import mcp_server

    if os.name == "nt":
        pytest.skip("links need rights on Windows")
    real = tmp_path / "dotfiles" / "claude.json"
    real.parent.mkdir()
    real.write_text('{"keep": 1}', encoding="utf-8")
    cfg = tmp_path / "Claude" / "claude_desktop_config.json"
    cfg.parent.mkdir()
    cfg.symlink_to(real)
    mcp_server.install_desktop(cfg)
    assert cfg.is_symlink() and json.loads(real.read_text(encoding="utf-8"))["keep"] == 1
    assert "enlens" in json.loads(real.read_text(encoding="utf-8"))["mcpServers"]


def _claude_code_answers(monkeypatch, refuse: tuple[str, ...]):
    """Claude Code as a stand-in: every `claude plugin …` call whose words start with one of `refuse` fails."""
    from enlens_claims import claude_setup

    calls: list = []

    def run(args, timeout=60):
        calls.append(args[1:])
        if any(" ".join(args[1:]).startswith(r) for r in refuse):
            return 1, "Error: EACCES: permission denied"
        return 0, ""

    monkeypatch.setattr(claude_setup, "find_claude", lambda: "/opt/claude/bin/claude")
    monkeypatch.setattr(claude_setup, "_run", run)
    return calls


def _older_plugin():
    from enlens_claims import claude_setup

    claude_setup.write_plugin()
    pj = claude_setup.plugin_folder() / ".claude-plugin" / "plugin.json"
    pj.write_text(json.dumps({**json.loads(pj.read_text(encoding="utf-8")), "version": "0.13.0"}), encoding="utf-8")
    assert claude_setup.stale()


@pytest.mark.parametrize("refuse", ["plugin marketplace add", "plugin install", "plugin marketplace update",
                                    "plugin update"])
def test_a_plugin_claude_code_refused_is_tried_again_at_the_next_start(monkeypatch, refuse):
    """INSTALL-5: whichever of Claude Code's steps refuses (the refresh too: without it Claude Code keeps its old copy),
    repair() is not "repaired", says why, and the next start sees it (stale) and tries again; once Claude Code takes
    it, nothing is left to do."""
    from enlens_claims import claude_setup

    _older_plugin()
    _claude_code_answers(monkeypatch, (refuse,))
    r = claude_setup.repair()
    assert r["repaired"] is False and r["refused"] and "EACCES" in claude_setup.refused_words(r)
    assert claude_setup.stale(), "the next start must see that Claude Code still has the old plugin"
    calls = _claude_code_answers(monkeypatch, ())
    r = claude_setup.repair()
    assert r["repaired"] is True and calls[0][:3] == ["plugin", "marketplace", "add"]
    assert claude_setup.stale() == "" and claude_setup.repair()["repaired"] is False


def test_the_apps_start_does_not_say_the_plugin_was_brought_up_to_date_when_claude_code_refused(monkeypatch, capsys):
    """INSTALL-5's sibling: the app's start-up repair printed "was brought up to date" on the same flag."""
    from enlens_claims import agentcli
    from enlens_claims.gui import server

    _older_plugin()
    _claude_code_answers(monkeypatch, ("plugin marketplace add",))
    monkeypatch.setattr(agentcli, "repair", lambda *a, **k: {})
    server._repair_plugin()
    out = capsys.readouterr()
    assert "brought up to date" not in out.out + out.err
    assert "Claude Code did not take the ENLENS plugin" in out.err


def test_claude_setup_exits_non_zero_when_claude_code_refuses(monkeypatch, capsys):
    """INSTALL-6's sweep: `enlens claude-setup` printed the two lines to type and exited 0 when Claude Code was found
    and refused the plugin."""
    from enlens_claims import claude_setup, cli

    _claude_code_answers(monkeypatch, ("plugin marketplace add",))
    monkeypatch.setattr(claude_setup, "status", lambda refresh=False: {})
    assert cli.main(["claude-setup", "--no-check"]) == 1
    assert "claude plugin marketplace add" in capsys.readouterr().out


@pytest.mark.parametrize("table", ["another project's run", "no ps"])
def test_stop_ends_no_process_that_is_not_this_projects_run(monkeypatch, table):
    """INSTALL-2's sweep, the process numbers ENLENS reads from a file and ends (claude_setup.stop_run, a run an earlier
    app started): a record whose number now belongs to another project's run counted as this one's (only the slash
    command was looked for), and without `ps` the number alone counted. A faked process table; nothing is ended."""
    import os

    from enlens_claims import claude_setup

    if os.name == "nt":
        pytest.skip("the process table is faked through ps")
    me = os.getpid()  # a number that runs, so only the command line can tell
    claude_setup._write_record("Mine", me, "2026-11-18 09:00", 0.0, None)

    def ps(args, *a, **k):
        if args[:1] != ["ps"]:
            raise AssertionError(f"unexpected program: {args}")
        if table == "no ps":
            raise FileNotFoundError("ps")
        return subprocess.CompletedProcess(args, 0, '/opt/claude -p /enlens-run:enlens-run "Other" --parallel 2\n', "")

    ended: list = []
    monkeypatch.setattr(claude_setup.subprocess, "run", ps)
    monkeypatch.setattr(claude_setup, "_end_process", lambda pid, *a, **k: ended.append(pid))
    claude_setup.stop_run("Mine")
    assert ended == [], "Stop would have ended a process that is not this project's run"
    assert claude_setup.run_state("Mine") == {"running": False}


def test_stop_still_ends_this_projects_run_found_by_its_command_line(monkeypatch):
    """The other side: the record of this project's run, whose command line says so, is ended."""
    import os

    from enlens_claims import claude_setup

    if os.name == "nt":
        pytest.skip("the process table is faked through ps")
    me = os.getpid()
    claude_setup._write_record("Mine", me, "2026-11-18 09:00", 0.0, None)
    monkeypatch.setattr(claude_setup.subprocess, "run", lambda args, *a, **k: subprocess.CompletedProcess(
        args, 0, '/opt/claude -p /enlens-run:enlens-run "Mine" --parallel 2\n', ""))
    ended: list = []
    monkeypatch.setattr(claude_setup, "_end_process", lambda pid, *a, **k: ended.append(pid))
    claude_setup.stop_run("Mine")
    assert ended == [me]


class _FakeEnlens:
    """An ENLENS app on this computer as far as the icon and the hand-over can see: its page, and /api/jobs for its
    own token only (401 otherwise). `page_token`: shown on the page, as copies before 0.17.2 did."""

    def __init__(self, token: str, page_token: str | None = None):
        import http.server
        import socketserver
        import threading

        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                outer.asked.append((self.path, self.headers.get("X-Enlens-Token")))
                if self.path == "/":
                    body = (b'<meta name="enlens-version" content="' + __version__.encode() + b'">'
                            + (f'<meta name="enlens-token" content="{page_token}">'.encode() if page_token else b""))
                    code = 200
                elif self.path == "/api/jobs" and self.headers.get("X-Enlens-Token") == token:
                    body, code = b'{"jobs": []}', 200
                else:
                    body, code = b'{"error": "Missing or wrong token."}', 401
                self.send_response(code)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.asked: list = []
        from enlens_claims.gui.server import QuickServer   # (no look-up of this computer's name)

        self.srv = QuickServer(("127.0.0.1", 0), H)
        self.port = self.srv.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}/"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


def _record(launcher, url, port, pid):
    info = {"url": url, "port": port, "pid": pid, "version": __version__, "started": "2026-11-18 09:00:00"}
    launcher.info_path().parent.mkdir(parents=True, exist_ok=True)
    launcher.info_path().write_text(json.dumps(info), encoding="utf-8")
    return info


def test_the_icon_finds_this_folders_enlens_through_a_proxy_setting(monkeypatch):
    """Hunt phase 1 (proxies): with HTTP_PROXY set, the icon's look for a running ENLENS went to the proxy (a dead
    address here), so the copy that runs looked gone and a second one was started beside it."""
    from enlens_claims.gui import launcher

    app = _FakeEnlens("T" * 40)
    try:
        monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
        monkeypatch.setenv("http_proxy", "http://127.0.0.1:9")
        monkeypatch.delenv("NO_PROXY", raising=False)
        monkeypatch.delenv("no_proxy", raising=False)
        launcher.write_token(app.url, app.port, "T" * 40)
        info = _record(launcher, app.url, app.port, 1)
        assert launcher.running() == info
        assert ("/api/jobs", "T" * 40) in app.asked  # proven with this folder's token
    finally:
        app.close()


def test_a_record_another_enlens_answers_for_is_stale_and_removed(monkeypatch):
    """INSTALL-2: this folder's token file (left by its crashed copy) and app.json name a port where another ENLENS
    now answers: it refuses the token, so the record proves nothing; it is removed, and nothing is quit."""
    from enlens_claims.gui import launcher

    other = _FakeEnlens("O" * 40)
    try:
        launcher.write_token(other.url, other.port, "S" * 40)
        _record(launcher, other.url, other.port, 1)
        assert launcher.running() is None
        assert not launcher.info_path().exists()
        assert not any(p == "/api/quit" for p, _t in other.asked)
    finally:
        other.close()


def test_a_token_file_of_another_data_folder_is_not_this_ones(monkeypatch, tmp_path):
    """INSTALL-2's sibling: on Windows the token files of every data folder outside the profile share one folder,
    by port; a file another data folder's copy wrote for this port is not this data folder's token."""
    from enlens_claims.gui import launcher

    p = launcher.token_path(8799)
    p.write_text(json.dumps({"url": "http://127.0.0.1:8799/", "port": 8799, "pid": 1, "token": "A" * 40,
                             "home": str(tmp_path / "another-data-folder")}), encoding="utf-8")
    assert launcher.read_token(8799) is None
    p.write_text(json.dumps({"url": "http://127.0.0.1:8799/", "port": 8799, "pid": 1, "token": "A" * 40}),
                 encoding="utf-8")
    assert launcher.read_token(8799) == "A" * 40  # a file of before (no data folder named): as it was


@pytest.mark.parametrize("cmdline", ["/usr/bin/vim notes.txt", None])
def test_an_older_copys_page_token_counts_only_beside_its_own_process(monkeypatch, cmdline):
    """INSTALL-2, copies before 0.17.2 (no token file, the token on the page): the page alone proves nothing (any
    such copy, of any data folder or account, shows its token); the record's process must be an ENLENS app of this
    account by its command line. A number another program has (or none that runs) does not count."""
    import os

    from enlens_claims.gui import launcher

    app = _FakeEnlens("P" * 40, page_token="P" * 40)
    try:
        info = _record(launcher, app.url, app.port, os.getpid())
        out = subprocess.CompletedProcess([], 0 if cmdline else 1, cmdline or "", "")
        monkeypatch.setattr(launcher.subprocess, "run", lambda *a, **k: out)
        if os.name == "nt":
            monkeypatch.setattr("enlens_claims.procs.windows_command_line", lambda pid: cmdline)
        assert launcher.running() is None
        out = subprocess.CompletedProcess([], 0, f"{sys.executable} -m enlens_claims.gui.launch --launcher", "")
        if os.name == "nt":
            monkeypatch.setattr("enlens_claims.procs.windows_command_line", lambda pid: out.stdout)
        _record(launcher, app.url, app.port, os.getpid())
        assert launcher.running() == info
    finally:
        app.close()


def test_the_handover_does_not_count_a_stale_record_naming_another_program(tmp_path):
    """INSTALL-3's side case: app.json left by an icon copy names a number another program runs under now; the
    hand-over counted that as the app come back (no rescue although ENLENS did not start)."""
    import os

    from enlens_claims import handover
    from enlens_claims.gui import launcher

    _record(launcher, "http://127.0.0.1:9/", 9, os.getpid())  # a number that runs: this test's own
    job = {"info": str(launcher.info_path()), "token_dir": str(launcher.token_dir(launcher.info_path().parent)),
           "home": str(launcher.info_path().parent)}
    assert handover._came_back(job, 12345, 1.0) is False


def test_the_handover_counts_only_this_folders_copy_that_answers(tmp_path, monkeypatch):
    """INSTALL-3: a token file of another data folder, or one whose app does not take its token, is no copy come back;
    this folder's copy answering its token is (also with HTTP_PROXY set: never through a proxy)."""
    from enlens_claims import handover, home
    from enlens_claims.gui import launcher

    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:9")
    app = _FakeEnlens("N" * 40)
    try:
        job = {"info": str(launcher.info_path()), "token_dir": str(launcher.token_dir(home.home())),
               "home": str(home.home())}
        p = launcher.token_path(app.port)
        p.write_text(json.dumps({"url": app.url, "port": app.port, "pid": 777, "token": "N" * 40,
                                 "home": str(tmp_path / "another")}), encoding="utf-8")
        assert handover._came_back(job, 1, 1.0) is False
        p.write_text(json.dumps({"url": app.url, "port": app.port, "pid": 777, "token": "X" * 40,
                                 "home": str(home.home())}), encoding="utf-8")
        assert handover._came_back(job, 1, 1.0) is False
        p.write_text(json.dumps({"url": app.url, "port": app.port, "pid": 777, "token": "N" * 40,
                                 "home": str(home.home())}), encoding="utf-8")
        assert handover._came_back(job, 777, 1.0) is False  # the copy that was updated is not the one come back
        assert handover._came_back(job, 1, 1.0) is True
    finally:
        app.close()


def test_the_handover_job_carries_where_the_app_proves_it_came_back():
    from enlens_claims import home, update
    from enlens_claims.gui import launcher

    job = update.handover_job({"version": "9.9.9"}, "0.0.1", Path("."), ["uv"], ["python"])
    assert job["token_dir"] == str(launcher.token_dir(home.home())) and job["home"] == str(home.home())
