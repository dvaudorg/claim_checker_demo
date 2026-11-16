"""After 0.19.7: notifications from the computer when work the person started has finished (gui/notify.py).

Nothing here shows a notification on the screen: the systems' programs are stand-ins, except where a test makes the
macOS notifier in a temporary folder (macOS only, never opened) or runs the Windows script without showing anything
(Windows only, ENLENS_NOTE_DRY).
"""
from __future__ import annotations

import base64
import json
import plistlib
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

from enlens_claims.gui import notify
from enlens_claims.gui.api_common import Jobs


def _job(state="done", seconds=60.0, background=False, project="Repair cafés", title="Your local model answers"
         " its share of the queue", error=None):
    now = time.time()
    return SimpleNamespace(id="j1", state=state, created=now - seconds, finished=now, background=background,
                           project=project, title=title, error=error)


def _done(code=0, out="", err=""):
    return subprocess.CompletedProcess([], code, out, err)


# ---------------------------------------------------------------------------------------------
# which work tells the person
# ---------------------------------------------------------------------------------------------
def test_only_long_work_the_person_started_and_did_not_stop_tells_them():
    away = 0.0  # no tab has been in front
    assert notify.wanted(_job(), "away", away)
    assert notify.wanted(_job(state="error"), "away", away)
    assert not notify.wanted(_job(state="cancelled"), "away", away)   # they stopped it themselves
    assert not notify.wanted(_job(seconds=5), "away", away)           # over while they still look
    assert not notify.wanted(_job(background=True), "away", away)     # the shared folder's round
    assert not notify.wanted(_job(), "off", away)


def test_away_means_no_tab_in_front_and_always_means_always():
    now = time.time()
    looking = now - 3
    assert not notify.wanted(_job(), "away", looking, now)
    assert notify.wanted(_job(), "always", looking, now)
    assert notify.wanted(_job(), "away", now - notify.SEEN_WINDOW - 1, now)


def test_the_note_says_what_finished_how_long_it_took_and_where():
    title, text = notify.note_for(_job(seconds=12 * 60 + 5))
    assert title == "Finished" and text == "Your local model answers its share of the queue (took 12 min) · Repair cafés"
    title, text = notify.note_for(_job(state="error", error="The local model ran out of memory.", project=None))
    assert title == "Stopped with a problem" and text.endswith("ran out of memory.")
    assert len(notify.note_for(_job(title="x" * 1000))[1]) <= notify.NOTE_LIMIT


def test_a_job_that_ends_sends_one_note_from_a_thread_of_its_own(monkeypatch):
    monkeypatch.delenv("ENLENS_NO_NOTIFY", raising=False)
    sent, got = [], threading.Event()

    def send(title, text, url=""):
        sent.append((title, text, url))
        got.set()

    app = SimpleNamespace(settings=lambda: {"notify": "away"}, seen=0.0, host="127.0.0.1", port=8765, token="t" * 24)
    jobs = Jobs()
    jobs.ended.append(lambda job: notify.job_ended(app, job, send=send))

    def work(job):
        job.created -= 60   # as if it had run a minute
        return {"ok": True}

    jobs.start("check", "Checking a hypothesis", "Repair cafés", work, uses_model=False)
    assert got.wait(10)
    assert sent == [("Finished", "Checking a hypothesis (took 60 s) · Repair cafés",
                     "http://127.0.0.1:8765/#token=" + "t" * 24)]


def test_switched_off_for_the_process_nothing_is_sent(monkeypatch):
    monkeypatch.setenv("ENLENS_NO_NOTIFY", "1")
    app = SimpleNamespace(settings=lambda: {"notify": "always"}, seen=0.0, host="127.0.0.1", port=1, token="t")
    assert notify.job_ended(app, _job(), send=lambda *a, **k: pytest.fail("sent")) is False


def test_the_setting_takes_only_its_three_values(tmp_path, monkeypatch):
    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    from enlens_claims import home

    assert home.load_settings()["notify"] == "away"
    assert home.update_settings({"notify": "off"})["notify"] == "off"
    with pytest.raises(ValueError, match="notify must be"):
        home.update_settings({"notify": "loud"})


# ---------------------------------------------------------------------------------------------
# the app: a tab in front, and the test button
# ---------------------------------------------------------------------------------------------
@pytest.fixture
def served(tmp_path, monkeypatch):
    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    from enlens_claims.gui.server import make_server

    srv, app = make_server("127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    def call(method, path, headers=None):
        req = urllib.request.Request(f"http://127.0.0.1:{srv.server_address[1]}{path}", method=method,
                                     headers={"X-Enlens-Token": app.token, **(headers or {})})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())

    yield app, call
    srv.shutdown()
    srv.server_close()


def test_a_request_from_a_tab_in_front_marks_the_person_as_looking(served):
    app, call = served
    call("GET", "/api/jobs")
    assert app.seen == 0.0                       # a hidden tab, or a script
    call("GET", "/api/jobs", {"X-Enlens-Seen": "1"})
    assert time.time() - app.seen < 5


def test_the_test_button_answers_even_when_notes_are_off_here(served):
    _, call = served
    r = call("POST", "/api/notify/test")         # ENLENS_NO_NOTIFY (conftest): nothing reaches the screen
    assert r["sent"] is False and "ENLENS_NO_NOTIFY" in r["problem"] and r["note"]


def test_the_page_says_when_it_is_in_front_and_settings_offer_the_choice():
    static = Path(notify.__file__).with_name("static")
    assert '"X-Enlens-Seen"' in (static / "lib.js").read_text(encoding="utf-8")
    js = (static / "views" / "settings.js").read_text(encoding="utf-8")
    assert "function notifySection" in js and '"/api/notify/test"' in js and "notify: \"basics\"" in js


# ---------------------------------------------------------------------------------------------
# macOS
# ---------------------------------------------------------------------------------------------
def _fake_mac_tools(monkeypatch, calls, fail=()):
    monkeypatch.setattr(notify.shutil, "which", lambda tool: f"/usr/bin/{tool}")

    def run(cmd, **kw):
        calls.append(cmd)
        tool = Path(cmd[0]).name
        if tool in fail:
            return _done(1, err=f"{tool} failed")
        if tool == "osacompile":
            out = Path(cmd[cmd.index("-o") + 1])
            (out / "Contents" / "Resources").mkdir(parents=True)
            with open(out / "Contents" / "Info.plist", "wb") as f:
                plistlib.dump({"CFBundleExecutable": "applet", "CFBundleIconName": "applet"}, f)
        return _done()
    return run


def test_mac_the_notifier_is_made_once_and_each_note_waits_in_its_folder(tmp_path, monkeypatch):
    calls = []
    run = _fake_mac_tools(monkeypatch, calls)
    r = notify.send_note("Finished", "Checking (took 2 min)", platform="darwin", run=run, folder=tmp_path)
    assert r == {"sent": True, "how": "app", "problem": ""}
    tools = [Path(c[0]).name for c in calls]
    assert tools[0] == "osacompile" and tools[1] == "codesign" and tools[-1] == "open"
    app = tmp_path / "ENLENS.app"
    with open(app / "Contents" / "Info.plist", "rb") as f:
        plist = plistlib.load(f)
    assert plist["CFBundleName"] == "ENLENS" and plist["LSUIElement"] is True
    assert plist["CFBundleIdentifier"] == "org.enlens.notifier.enlens" and plist["CFBundleVersion"] == notify.MAC_STAMP
    assert plist.get("CFBundleIconFile") == "ENLENS" and "CFBundleIconName" not in plist
    notes = list((tmp_path / "pending").glob("*.note"))
    assert len(notes) == 1 and notes[0].read_text(encoding="utf-8") == "Finished\nChecking (took 2 min)\n"
    assert calls[-1] == ["open", "-g", str(app)]
    assert "enlens_claims.gui.launch --launcher --home" in (tmp_path / "open.sh").read_text(encoding="utf-8")
    calls.clear()
    notify.send_note("Finished", "Again", platform="darwin", run=run, folder=tmp_path)
    assert [Path(c[0]).name for c in calls] == ["open"]           # made once: only opened now


def test_mac_without_its_own_notifier_the_plain_notification_still_comes(tmp_path, monkeypatch):
    calls = []
    run = _fake_mac_tools(monkeypatch, calls, fail=("codesign",))
    r = notify.send_note("Finished", 'A "quoted" title', platform="darwin", run=run, folder=tmp_path)
    assert r["sent"] is True and r["how"] == "osascript" and "codesign failed" in r["problem"]
    assert calls[-1][:2] == ["osascript", "-e"] and '\\"quoted\\"' in calls[-1][2]
    assert not (tmp_path / "ENLENS.app").exists()


@pytest.mark.skipif(sys.platform != "darwin" or not shutil.which("osacompile"), reason="macOS only")
def test_mac_the_real_notifier_is_signed_and_carries_the_name(tmp_path):
    app = notify.mac_notifier("ENLENS", tmp_path, register=False)   # made, never opened: nothing on the screen
    assert subprocess.run(["codesign", "--verify", str(app)], capture_output=True).returncode == 0
    with open(app / "Contents" / "Info.plist", "rb") as f:
        plist = plistlib.load(f)
    assert plist["CFBundleName"] == "ENLENS" and plist["CFBundleVersion"] == notify.MAC_STAMP
    assert (app / "Contents" / "Resources" / "ENLENS.icns").is_file()
    before = (app / "Contents" / "Info.plist").stat().st_mtime_ns
    assert notify.mac_notifier("ENLENS", tmp_path, register=False) == app
    assert (app / "Contents" / "Info.plist").stat().st_mtime_ns == before


# ---------------------------------------------------------------------------------------------
# Windows
# ---------------------------------------------------------------------------------------------
def test_windows_the_toast_is_escaped_and_a_click_opens_the_link():
    from xml.dom import minidom

    toast = notify.toast_xml("Finished", "Sources & <notes> from \"Ábel\"", "http://127.0.0.1:8765/#token=abc&x")
    assert 'launch="http://127.0.0.1:8765/#token=abc&amp;x"' in toast and 'activationType="protocol"' in toast
    assert "Sources &amp; &lt;notes&gt; from \"Ábel\"" in toast
    assert minidom.parseString(toast).documentElement.tagName == "toast"  # well formed
    assert 'launch=' not in notify.toast_xml("Finished", "x")


def test_windows_the_text_goes_in_the_environment_never_in_the_script(monkeypatch):
    calls = []

    def run(cmd, env=None, **kw):
        calls.append((cmd, env))
        return _done(0, "toast\n")
    monkeypatch.setattr(notify, "_win_icon", lambda: "")
    r = notify.send_note("Finished", "Kovács; $(rm -rf /) `x`", url="http://127.0.0.1:1/", platform="win32", run=run)
    assert r == {"sent": True, "how": "toast", "problem": ""}
    cmd, env = calls[0]
    assert cmd[:2] == ["powershell", "-NoProfile"] and "-EncodedCommand" in cmd
    script = base64.b64decode(cmd[-1]).decode("utf-16-le")
    assert script == notify.WIN_SCRIPT and "Kovács" not in script
    assert env["ENLENS_NOTE_TEXT"] == "Kovács; $(rm -rf /) `x`" and env["ENLENS_NOTE_NAME"] == "ENLENS"
    assert env["ENLENS_NOTE_ID"] == "ENLENS.Notifications.enlens" and env["ENLENS_NOTE_DRY"] == ""


def test_windows_a_failed_script_says_why():
    r = notify.send_note("Finished", "x", platform="win32", run=lambda *a, **k: _done(1, "", "Access denied"))
    assert r["sent"] is False and "Access denied" in r["problem"]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_windows_the_real_script_builds_its_toast_without_showing_it():
    env = notify.win_env("ENLENS", "Finished", "Kovács Ábel: 3 documents (took 2 min)", "http://127.0.0.1:8765/",
                         dry=True)
    r = subprocess.run(notify.win_command(), env=env, capture_output=True, text=True, errors="replace", timeout=120)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip().splitlines()[-1] in ("toast-ready", "balloon-ready"), r.stdout + r.stderr


# ---------------------------------------------------------------------------------------------
# Linux and the rest
# ---------------------------------------------------------------------------------------------
def test_linux_notify_send_first_then_gdbus(monkeypatch):
    monkeypatch.setattr(notify.shutil, "which", lambda tool: f"/usr/bin/{tool}")
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        return _done(1, err="no service") if cmd[0] == "notify-send" else _done()
    r = notify.send_note("Finished", "Checking", platform="linux", run=run)
    assert r == {"sent": True, "how": "gdbus", "problem": ""}
    assert calls[0][0] == "notify-send" and "--app-name=ENLENS" in calls[0] and calls[0][-2:] == ["ENLENS: Finished",
                                                                                                    "Checking"]
    assert calls[1][:3] == ["gdbus", "call", "--session"]


def test_linux_without_either_program_it_says_what_to_install(monkeypatch):
    monkeypatch.setattr(notify.shutil, "which", lambda tool: None)
    r = notify.send_note("Finished", "x", platform="linux", run=lambda *a, **k: pytest.fail("ran"))
    assert r["sent"] is False and "notify-send" in r["problem"]


def test_each_system_says_where_to_allow_them():
    assert "System Settings" in notify.where_to_allow("darwin")
    assert "Windows Settings" in notify.where_to_allow("win32")
    assert "Do not disturb" in notify.where_to_allow("linux")
