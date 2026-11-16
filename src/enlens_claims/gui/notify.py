"""Notifications from the computer itself (after 0.19.7): work that took a while tells the person it has finished, so the
browser can be closed while a local model works (a closed browser leaves the model more memory).

When a job the person started ends (done, or stopped by a problem; not when they stopped it), and it took at least
`MIN_SECONDS`, `job_ended` sends one notification, as Settings' `notify` says: `away` (the default) only when no tab of
the app is in front of the person (no request from a visible tab with the focus, `App.seen`, in the last `SEEN_WINDOW`
seconds), `always`, or `off`. Work the app started by itself (a round of the shared folder) never notifies.

How each system shows it (`send`):
  macOS    a small app of its own, `<name>.app` in ~/Library/Application Support/<name>/Notifier, made once with the
           system's own tools (osacompile, codesign): macOS shows a notification under the name of the app that sends
           it, and opens that app when the notification is clicked, so the plain `osascript` notification shows as
           "Script Editor" and a click opens Script Editor. This app shows the notes left in its `pending` folder, and
           when it is opened with none there (a click on a notification) it runs `open.sh`, which opens the app in the
           browser as its icon does (enlens-gui --launcher). The first notification asks whether it may send them.
           Without the tools: the plain osascript one.
  Windows  a toast through Windows PowerShell, under the app's own name and icon (its id registered for this account in
           HKCU\\Software\\Classes\\AppUserModelId, as unpackaged apps do); a click opens the app's link in the browser.
           When the toast cannot be shown: a balloon from the notification area.
  Linux    notify-send, else gdbus (the desktop's notification service, org.freedesktop.Notifications).

ENLENS_NO_NOTIFY=1 switches it off for the whole process (tests, tools/dev_server.py): nothing reaches the screen.
"""
from __future__ import annotations

import base64
import hashlib
import os
import plistlib
import shlex
import shutil
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Callable
from xml.sax.saxutils import escape, quoteattr

from ..procs import no_window

MIN_SECONDS = 20     # work shorter than this ends while the person still looks: no notification
SEEN_WINDOW = 20     # seconds: a tab in front asks for the work's state every 2 to 5 s while work runs
CHOICES = ("away", "always", "off")
NOTE_LIMIT = 220     # characters of a notification's text (the systems cut longer ones anyway)

Runner = Callable[..., Any]


def disabled() -> bool:
    return os.environ.get("ENLENS_NO_NOTIFY", "").strip().lower() in ("1", "true", "yes", "on")


def _short(text: str, limit: int = NOTE_LIMIT) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _duration(seconds: float) -> str:
    s = int(round(seconds))
    if s < 90:
        return f"{s} s"
    m = s // 60
    return f"{m} min" if m < 90 else f"{m // 60} h {m % 60:02d} min"


def note_for(job, project_label: str | None = None) -> tuple[str, str]:
    """The title and text of the notification for an ended job."""
    took = _duration((job.finished or time.time()) - job.created)
    where = f" · {project_label or job.project}" if job.project else ""
    if job.state == "error":
        return "Stopped with a problem", _short(f"{job.title}: {job.error or 'see the app'}{where}")
    return "Finished", _short(f"{job.title} (took {took}){where}")


def wanted(job, choice: str, seen: float, now: float | None = None) -> bool:
    """Whether the ended `job` gets a notification, with Settings' `choice` and the last time a tab was in front."""
    now = time.time() if now is None else now
    if choice not in ("away", "always") or job.background or job.state not in ("done", "error"):
        return False
    if (job.finished or now) - job.created < MIN_SECONDS:
        return False
    return choice == "always" or now - seen > SEEN_WINDOW


def job_ended(app, job, send: Callable[..., dict] | None = None) -> bool:
    """The jobs' listener (server.App): a notification for `job` when Settings and the tabs say so. It is sent from a
    thread of its own, so a slow system never holds the job's thread. True when one is on its way."""
    if disabled():
        return False
    try:
        choice = app.settings().get("notify") or "away"
    except Exception:  # noqa: BLE001 - unreadable settings: the default
        choice = "away"
    if not wanted(job, choice, getattr(app, "seen", 0.0)):
        return False
    title, text = note_for(job)
    sender = send or send_note
    url = _app_link(app)

    def go():
        try:
            sender(title, text, url=url)
        except Exception:  # noqa: BLE001 - a notification never stops the app
            traceback.print_exc()

    threading.Thread(target=go, daemon=True, name=f"notify-{job.id}").start()
    return True


def _app_link(app) -> str:
    """The app's link with its token (what a click on a Windows toast opens)."""
    try:
        from .launcher import link

        host = "127.0.0.1" if app.host in ("0.0.0.0", "::", "") else app.host
        return link(f"http://{host}:{app.port}/", app.token) if app.port else ""
    except Exception:  # noqa: BLE001
        return ""


def app_name() -> str:
    try:
        from .. import addons

        return str(addons.brand().get("name") or "ENLENS")
    except Exception:  # noqa: BLE001
        return "ENLENS"


def _slug(name: str) -> str:
    return "".join(c for c in name.lower() if c.isalnum()) or "enlens"


# ---------------------------------------------------------------------------------------------
# sending
# ---------------------------------------------------------------------------------------------
def send_note(title: str, text: str, url: str = "", platform: str | None = None, run: Runner = subprocess.run,
              folder: Path | None = None) -> dict:
    """Show one notification on this computer. → {"sent": bool, "how": what showed it, "problem": why not}.
    `platform`, `run` and `folder` (where the macOS notifier lives) are for tests."""
    platform = platform or sys.platform
    name = app_name()
    try:
        if platform == "darwin":
            return _mac(name, title, text, run, folder)
        if platform.startswith("win"):
            return _windows(name, title, text, url, run)
        return _linux(name, title, text, run)
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        return {"sent": False, "how": "", "problem": str(e)}


SEND_LOCK = threading.Lock()   # one notifier made (macOS) or note sent at a time


# -- macOS -------------------------------------------------------------------------------------
# The notifier's script. It reads its notes from the folder it sits in (nothing of a path is written into it, so a
# folder with any letters in its name works), shows each, and with none there opens the app (a notification clicked).
MAC_SCRIPT = r'''-- Shows the notifications of the app beside it, and opens the app when one is clicked.
property shownSome : false

on run
	tellPerson()
end run

on reopen
	tellPerson()
end reopen

on tellPerson()
	set shownSome to false
	try
		set here to do shell script "cd " & quoted form of (POSIX path of (path to me)) & "/.. && pwd -P"
	on error
		return
	end try
	try
		repeat 20 times
			set names to paragraphs of (do shell script "ls " & quoted form of (here & "/pending") & " 2>/dev/null | grep '[.]note$' || true")
			if names is {} or names is {""} then exit repeat
			repeat with n in names
				set f to here & "/pending/" & n
				try
					set t to do shell script "cat " & quoted form of f & "; rm -f " & quoted form of f
					if (count of paragraphs of t) > 1 then
						display notification (paragraph 2 of t) with title (paragraph 1 of t)
					else
						display notification t
					end if
					set shownSome to true
				end try
			end repeat
		end repeat
		if shownSome then
			delay 1
		else
			do shell script "/bin/sh " & quoted form of (here & "/open.sh") & " >/dev/null 2>&1 &"
		end if
	end try
end tellPerson
'''
MAC_STAMP = hashlib.sha256(MAC_SCRIPT.encode("utf-8")).hexdigest()[:12]
LSREGISTER = ("/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/"
              "lsregister")


def mac_folder(name: str | None = None) -> Path:
    """Where the notifier lives: one for this account, outside the data folder (a data folder can be anywhere, or
    several), so macOS knows one app of that name."""
    name = name or app_name()
    return Path.home() / "Library" / "Application Support" / name / "Notifier"


def mac_notifier(name: str, folder: Path, run: Runner = subprocess.run, register: bool = True) -> Path:
    """The notifier app `<folder>/<name>.app`, made when missing or made by an older script (its CFBundleVersion).
    `register`: tell Launch Services about it at once (tests that make one in a temporary folder do not)."""
    app = folder / f"{name}.app"
    info = app / "Contents" / "Info.plist"
    try:
        with open(info, "rb") as f:
            if plistlib.load(f).get("CFBundleVersion") == MAC_STAMP:
                return app
    except (OSError, plistlib.InvalidFileException, ValueError):
        pass
    for tool in ("osacompile", "codesign"):
        if not shutil.which(tool):
            raise OSError(f"{tool} is not on this Mac.")
    folder.mkdir(parents=True, exist_ok=True)
    src = folder / "notifier.applescript"
    src.write_text(MAC_SCRIPT, encoding="utf-8")
    part = folder / f"{name}-new.app"
    shutil.rmtree(part, ignore_errors=True)
    r = run(["osacompile", "-o", str(part), str(src)], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise OSError(f"osacompile: {(r.stderr or '').strip()[:300]}")
    pinfo = part / "Contents" / "Info.plist"
    with open(pinfo, "rb") as f:
        plist = plistlib.load(f)
    plist.update({"CFBundleIdentifier": f"org.enlens.notifier.{_slug(name)}", "CFBundleName": name,
                  "CFBundleDisplayName": name, "CFBundleVersion": MAC_STAMP, "CFBundleShortVersionString": "1",
                  "LSUIElement": True})  # no Dock icon, no menu bar of its own
    from .launcher import _put_icon

    if _put_icon(part / "Contents" / "Resources" / "ENLENS.icns", "icns"):
        plist.pop("CFBundleIconName", None)   # the script icon of the asset catalogue would win over the file
        plist["CFBundleIconFile"] = "ENLENS"
    with open(pinfo, "wb") as f:
        plistlib.dump(plist, f)
    # the Info.plist changed after osacompile signed it: signed again for this computer (Apple silicon runs nothing
    # unsigned, and macOS ties the notification permission to the app's signature)
    r = run(["codesign", "--force", "--sign", "-", str(part)], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise OSError(f"codesign: {(r.stderr or '').strip()[:300]}")
    shutil.rmtree(app, ignore_errors=True)
    part.rename(app)
    src.unlink(missing_ok=True)
    if register and os.path.exists(LSREGISTER):
        run([LSREGISTER, "-f", str(app)], capture_output=True, text=True, timeout=60)
    return app


def _open_command() -> list[str]:
    """What a click on a notification runs: the app's icon command (opens the running app, or starts it)."""
    from .. import home

    cmd = [sys.executable, "-m", "enlens_claims.gui.launch", "--launcher", "--home", str(home.home().resolve())]
    if home.local_only():
        cmd.append("--local-only")
    return cmd


def _write_if_changed(path: Path, text: str) -> None:
    try:
        if path.read_text(encoding="utf-8") == text:
            return
    except OSError:
        pass
    path.write_text(text, encoding="utf-8")


def _mac(name: str, title: str, text: str, run: Runner, folder: Path | None) -> dict:
    folder = folder or mac_folder(name)
    title, text = _short(title, 120), _short(text)
    with SEND_LOCK:
        try:
            app = mac_notifier(name, folder, run)
        except (OSError, subprocess.SubprocessError, ValueError, plistlib.InvalidFileException) as e:
            return _osascript(name, title, text, run, problem=str(e))
        _write_if_changed(folder / "open.sh", "#!/bin/sh\n# Opens the app (a notification was clicked).\nexec "
                          + " ".join(shlex.quote(x) for x in _open_command()) + "\n")
        pending = folder / "pending"
        pending.mkdir(exist_ok=True)
        stem = f"{time.time_ns()}-{os.getpid()}"
        part = pending / f"{stem}.part"
        part.write_text(f"{title}\n{text}\n", encoding="utf-8")
        part.replace(pending / f"{stem}.note")   # whole, or not there: the notifier never reads half a note
        r = run(["open", "-g", str(app)], capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            (pending / f"{stem}.note").unlink(missing_ok=True)
            return _osascript(name, title, text, run, problem=f"open: {(r.stderr or '').strip()[:300]}")
    return {"sent": True, "how": "app", "problem": ""}


def _as_text(s: str) -> str:
    """An AppleScript string literal."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _osascript(name: str, title: str, text: str, run: Runner, problem: str = "") -> dict:
    """The plain notification (shown as Script Editor's): when the notifier cannot be made."""
    if not shutil.which("osascript"):
        return {"sent": False, "how": "", "problem": problem or "osascript is not on this Mac."}
    script = f"display notification {_as_text(text)} with title {_as_text(name)} subtitle {_as_text(title)}"
    r = run(["osascript", "-e", script], capture_output=True, text=True, timeout=30)
    ok = r.returncode == 0
    return {"sent": ok, "how": "osascript" if ok else "", "problem": problem if ok else
            (problem + "; " if problem else "") + f"osascript: {(r.stderr or '').strip()[:300]}"}


# -- Windows -----------------------------------------------------------------------------------
# Windows PowerShell 5.1 (on every Windows 10 and 11; PowerShell 7 cannot load these Windows types). What it shows
# comes in environment variables, so no text is ever part of the script. ENLENS_NOTE_DRY=1: everything but showing
# it and writing the registry (tests on Windows).
WIN_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
$dry = $env:ENLENS_NOTE_DRY -eq '1'
$id = $env:ENLENS_NOTE_ID
try {
  if (-not $dry) {
    $key = "HKCU:\Software\Classes\AppUserModelId\$id"
    if (-not (Test-Path $key)) { New-Item -Path $key -Force | Out-Null }
    New-ItemProperty -Path $key -Name DisplayName -Value $env:ENLENS_NOTE_NAME -PropertyType String -Force | Out-Null
    if ($env:ENLENS_NOTE_ICON) {
      New-ItemProperty -Path $key -Name IconUri -Value $env:ENLENS_NOTE_ICON -PropertyType String -Force | Out-Null
    }
  }
} catch { $id = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe' }
try {
  [void][Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
  [void][Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime]
  $x = New-Object Windows.Data.Xml.Dom.XmlDocument
  $x.LoadXml($env:ENLENS_NOTE_XML)
  $t = New-Object Windows.UI.Notifications.ToastNotification $x
  if ($dry) { Write-Output 'toast-ready'; exit 0 }
  [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($id).Show($t)
  Write-Output 'toast'
} catch {
  Add-Type -AssemblyName System.Windows.Forms
  Add-Type -AssemblyName System.Drawing
  if ($dry) { Write-Output 'balloon-ready'; exit 0 }
  $n = New-Object System.Windows.Forms.NotifyIcon
  $n.Icon = [System.Drawing.SystemIcons]::Information
  $n.Text = $env:ENLENS_NOTE_NAME
  $n.Visible = $true
  $n.ShowBalloonTip(10000, $env:ENLENS_NOTE_TITLE, $env:ENLENS_NOTE_TEXT, [System.Windows.Forms.ToolTipIcon]::Info)
  Start-Sleep -Seconds 8
  $n.Dispose()
  Write-Output 'balloon'
}
'''


def toast_xml(title: str, text: str, url: str = "") -> str:
    """The toast: its title and text; a click opens `url` (the app's link) in the browser."""
    launch = f' activationType="protocol" launch={quoteattr(url)}' if url else ""
    return (f'<toast{launch}><visual><binding template="ToastGeneric"><text>{escape(title)}</text>'
            f'<text>{escape(text)}</text></binding></visual></toast>')


def win_command(script: str = WIN_SCRIPT) -> list[str]:
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded]


def win_env(name: str, title: str, text: str, url: str = "", icon: str = "", dry: bool = False) -> dict:
    env = dict(os.environ)
    env.update({"ENLENS_NOTE_ID": f"ENLENS.Notifications.{_slug(name)}", "ENLENS_NOTE_NAME": name,
                "ENLENS_NOTE_ICON": icon, "ENLENS_NOTE_TITLE": f"{name}: {title}", "ENLENS_NOTE_TEXT": text,
                "ENLENS_NOTE_XML": toast_xml(title, text, url), "ENLENS_NOTE_DRY": "1" if dry else ""})
    return env


def _win_icon() -> str:
    from .. import home
    from .launcher import _put_icon

    ico = home.home() / "ENLENS.ico"   # the one the Desktop icon uses too
    return str(ico) if ico.is_file() or _put_icon(ico, "ico") else ""


def _windows(name: str, title: str, text: str, url: str, run: Runner) -> dict:
    title, text = _short(title, 120), _short(text)
    with SEND_LOCK:
        r = run(win_command(), env=win_env(name, title, text, url, _win_icon()), capture_output=True, text=True,
                errors="replace", timeout=60, **no_window())
    how = (r.stdout or "").strip().splitlines()[-1:] or [""]
    ok = r.returncode == 0 and how[0] in ("toast", "balloon")
    return {"sent": ok, "how": how[0] if ok else "", "problem": "" if ok else
            f"PowerShell: {((r.stderr or '') or (r.stdout or '')).strip()[:300] or 'no answer'}"}


# -- Linux and the rest ------------------------------------------------------------------------
def _linux(name: str, title: str, text: str, run: Runner) -> dict:
    title, text = _short(title, 120), _short(text)
    icon = str(Path(__file__).with_name("static") / "logo.svg")
    problems = []
    if shutil.which("notify-send"):
        r = run(["notify-send", f"--app-name={name}", f"--icon={icon}", f"{name}: {title}", text],
                capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            return {"sent": True, "how": "notify-send", "problem": ""}
        problems.append(f"notify-send: {(r.stderr or '').strip()[:200]}")
    if shutil.which("gdbus"):
        r = run(["gdbus", "call", "--session", "--dest", "org.freedesktop.Notifications", "--object-path",
                 "/org/freedesktop/Notifications", "--method", "org.freedesktop.Notifications.Notify", name, "0",
                 icon, f"{name}: {title}", text, "[]", "{}", "10000"], capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            return {"sent": True, "how": "gdbus", "problem": ""}
        problems.append(f"gdbus: {(r.stderr or '').strip()[:200]}")
    return {"sent": False, "how": "", "problem": "; ".join(problems) or
            "Neither notify-send nor gdbus is on this computer (install libnotify-bin, or your desktop's "
            "notification service)."}


def where_to_allow(platform: str | None = None) -> str:
    """Where the person allows or stops them on this system, in words (Settings' test)."""
    platform = platform or sys.platform
    name = app_name()
    if platform == "darwin":
        return (f"The first time, macOS asks whether {name} may send notifications: choose Allow. You can change "
                f"it later in System Settings › Notifications › {name}.")
    if platform.startswith("win"):
        return (f"If nothing appeared, look in Windows Settings › System › Notifications (is {name} on, and Do not "
                "disturb off?).")
    return "If nothing appeared, your desktop may have notifications switched off, or Do not disturb on."
