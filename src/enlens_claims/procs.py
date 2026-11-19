"""0.15.3: other programs start without a window on Windows.

The app runs without a console on Windows: its icon starts it with pythonw.exe, and the connector that Claude Code
starts is written for the same Python. A console program started from a process without a console is given a console
window of its own, which opens, takes the focus from what the person is doing and closes again. While a task queue
page was open, the app's check of Claude Code ran `claude` three times every half minute, and each run flashed a
window; Tesseract flashed one for each scanned page and git and uv for each update.

So every program ENLENS starts goes through `no_window()` (a test holds every call in the package to it). The program
still has a console, one that is never shown, so what it writes can be read as before. On macOS and Linux nothing
changes."""
from __future__ import annotations

import os
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000  # subprocess.CREATE_NO_WINDOW, which only Windows' Python has


def no_window() -> dict:
    """The keyword arguments for subprocess.run and subprocess.Popen that start a console program without a window
    on Windows; none elsewhere."""
    return {"creationflags": CREATE_NO_WINDOW} if os.name == "nt" else {}


# 0.15.7: a Claude Code run left going is recognised on Windows by its command line, as on macOS and Linux (`ps`).
# Before, Windows checked the process number alone (tasklist), so a record whose number Windows had since given to
# another program counted as a run, and Stop could end that program; the test run on Windows stopped part way for the
# same reason (a test recording its own number had pytest ended).
GONE = None  # windows_command_line: the process has ended, or is not this user's to look into


def windows_command_line(pid: int) -> str | None:
    """The command line process `pid` was started with, on Windows (NtQueryInformationProcess with
    ProcessCommandLineInformation, Windows 8.1 and later). None when it has ended or is not ours to read; "" when it
    runs but its command line cannot be read."""
    import ctypes
    from ctypes import wintypes

    class UnicodeString(ctypes.Structure):
        _fields_ = [("Length", wintypes.USHORT), ("MaximumLength", wintypes.USHORT), ("Buffer", ctypes.c_void_p)]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll")
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    ntdll.NtQueryInformationProcess.restype = ctypes.c_long
    ntdll.NtQueryInformationProcess.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong,
                                                ctypes.POINTER(ctypes.c_ulong)]
    handle = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return GONE  # no such process (87), or another user's (5)
    try:
        code = wintypes.DWORD()
        if k32.GetExitCodeProcess(handle, ctypes.byref(code)) and code.value != 259:  # STILL_ACTIVE
            return GONE  # ended; a handle someone still holds keeps its number taken
        size = ctypes.c_ulong(0)
        ntdll.NtQueryInformationProcess(handle, 60, None, 0, ctypes.byref(size))  # 60: ProcessCommandLineInformation
        if not size.value:
            return ""
        buf = ctypes.create_string_buffer(size.value)
        if ntdll.NtQueryInformationProcess(handle, 60, buf, size, ctypes.byref(size)) != 0:
            return ""
        s = UnicodeString.from_buffer(buf)
        return ctypes.wstring_at(s.Buffer, s.Length // 2) if s.Buffer and s.Length else ""
    finally:
        k32.CloseHandle(handle)


# Hunt phase 1 (INSTALL-7): a line of a command file (.cmd, .bat) is read by cmd.exe, not passed to CreateProcess, so
# subprocess.list2cmdline's quoting (spaces and tabs only) does not hold there: in `start "" python … --home
# D:\R&D\enlens` cmd.exe ended the line at "&", started ENLENS on the data folder D:\R and ran "D\enlens" as a command.
# Every argument written into a command file goes through `cmd_quote`, and the file holds the line CMD_LITERAL_BANG
# before any line that uses one.
CMD_LITERAL_BANG = "setlocal DisableDelayedExpansion\r\n"  # "!" stays a "!" (no delayed expansion)


def cmd_quote(arg: str) -> str:
    """`arg` as one argument on a line of a command file: always in double quotes, so cmd.exe reads & | < > ^ ( ) and
    spaces in it as themselves; % doubled (a command file expands %NAME% even inside quotes); a " inside written as
    "" (cmd.exe stays inside the quotes, and the program's own reading, the Microsoft C rules Python uses, gives one
    "); backslashes before a " or at the end doubled, so a folder ending in \\ does not swallow the closing quote. A
    line break cannot be written on one line: refused. ! is left alone: the file switches delayed expansion off
    (CMD_LITERAL_BANG)."""
    arg = str(arg)
    if "\r" in arg or "\n" in arg or "\0" in arg:
        raise ValueError(f"A command file cannot hold this argument on one line: {arg!r}")
    out: list[str] = []
    slashes = 0
    for ch in arg:
        if ch == "\\":
            slashes += 1
            continue
        if ch == '"':
            out.append("\\" * (slashes * 2) + '""')
        else:
            out.append("\\" * slashes + ch)
        slashes = 0
    out.append("\\" * (slashes * 2))
    return '"' + "".join(out).replace("%", "%%") + '"'


# Hunt phase 1.5 (INSTALL-5's Windows question): Windows starts a command file (.cmd, .bat; npm's `claude.cmd`, and
# `codex.cmd`) through cmd.exe, which reads the whole command line again, so subprocess's list2cmdline quoting (spaces
# and tabs only) does not hold: `claude.cmd plugin marketplace add D:\R&D\enlens\claude-plugin` ended at "&", and
# %PATH% in a folder's name was expanded. `program_args` gives subprocess a cmd.exe line in which every argument is
# quoted for that reading (`batch_arg`), as Rust's standard library does since its "BatBadBut" fix.
def batch_arg(arg: str) -> str:
    """`arg` as one argument on cmd.exe's command line (not inside a command file: that is `cmd_quote`): in double
    quotes, so & | < > ^ ( ) and spaces are themselves; a " inside written as "" (cmd.exe stays inside the quotes; the
    program's reading, the Microsoft C rules, gives one "); backslashes before a " or at the end doubled; each % as
    %%cd:~,% (on a command line % cannot be doubled; cmd.exe reads %cd:~,% as nothing and keeps the first %). A line
    break cannot be passed through cmd.exe: refused. ! is left alone: `program_args` switches delayed expansion off."""
    arg = str(arg)
    if "\r" in arg or "\n" in arg or "\0" in arg:
        raise ValueError(f"cmd.exe cannot pass this argument on: {arg!r}")
    out: list[str] = []
    slashes = 0
    for ch in arg:
        if ch == "\\":
            slashes += 1
            continue
        if ch == '"':
            out.append("\\" * (slashes * 2) + '""')
        else:
            out.append("\\" * slashes + ("%%cd:~,%" if ch == "%" else ch))
        slashes = 0
    out.append("\\" * (slashes * 2))
    return '"' + "".join(out) + '"'


def is_command_file(program: str) -> bool:
    """Whether Windows would start `program` through cmd.exe (a .cmd or .bat file)."""
    return os.name == "nt" and str(program).lower().endswith((".cmd", ".bat"))


def program_args(argv: list[str]) -> list[str] | str:
    """What to hand subprocess.run or subprocess.Popen to start `argv` so that each argument reaches the program whole:
    `argv` itself, except on Windows when its program is a command file (.cmd, .bat), then one command line (a str)
    for cmd.exe: AutoRun off (/d), delayed expansion off (/v:off, so ! stays), the outer quotes taken off as written
    (/s), and every part quoted by `batch_arg`. Use it wherever the program may be a command file (npm installs
    `claude.cmd` and `codex.cmd`). Raises ValueError for an argument cmd.exe cannot pass (a line break)."""
    argv = [str(a) for a in argv]
    if not argv or not is_command_file(argv[0]):
        return argv
    comspec = os.environ.get("ComSpec") or "cmd.exe"
    return f'"{comspec}" /d /v:off /s /c "' + " ".join(batch_arg(a) for a in argv) + '"'


# Hunt phase 1.5 (NEEDS WINDOWS 5): on Windows one environment has two Pythons: pythonw.exe (no console; the icon
# starts the app with it) and python.exe (the installer and the hand-over run post-install with it). The plugin and the
# Claude app's entry named whichever wrote them, and compared that with sys.executable, so after every update the app's
# first start found the plugin "stale", rewrote it and ran `claude plugin ...` again. A connector talks over stdio,
# which only the console python.exe is sure to have: it is the one named, and the two count as one.
def console_python(exe: str | None = None) -> str:
    """The Python to name for a program that talks over stdio (the connector): `exe` (default: this one), except
    pythonw.exe, for which the python.exe beside it."""
    import sys
    from pathlib import Path

    exe = str(exe or sys.executable)
    p = Path(exe)
    if p.name.lower() == "pythonw.exe" and p.with_name("python.exe").exists():
        return str(p.with_name("python.exe"))
    return exe


def same_python(a: str | None, b: str | None) -> bool:
    """Whether two interpreter paths are the same Python: equal, or python.exe and pythonw.exe of one folder."""
    if not a or not b:
        return False
    if a == b:
        return True
    from pathlib import PurePath

    pa, pb = PurePath(a), PurePath(b)
    both = {pa.name.lower(), pb.name.lower()}
    return both <= {"python.exe", "pythonw.exe"} and str(pa.parent).lower() == str(pb.parent).lower()


# Hunt phase 1.5 (INSTALL15-10): a process's command line on every system, one way. macOS and Linux asked `ps`
# alone; on a computer without it (a small Linux) a Claude Code run an earlier app started counted as gone, was
# forgotten rather than stopped, and went on unseen. Linux's /proc has the same line.
PROC = Path("/proc")


def command_line(pid: int) -> str | None:
    """The command line of process `pid` when it runs and is this account's; None when it has ended (or is a zombie),
    is another account's, or cannot be asked; "" when it runs but its line cannot be read (Windows). Windows:
    `windows_command_line`; elsewhere `ps`, then /proc."""
    import subprocess

    if not isinstance(pid, int) or pid <= 0:
        return None
    if os.name == "nt":
        try:
            return windows_command_line(pid)
        except (OSError, AttributeError, ValueError):
            return None
    try:
        os.kill(pid, 0)
    except OSError:  # gone, or another account's (PermissionError): not ours
        return None
    try:
        # 0.14.4: -ww, the whole line (Linux cuts it at 80 characters in a pipe)
        r = subprocess.run(["ps", "-ww", "-o", "command=", "-p", str(pid)], capture_output=True, text=True,
                           timeout=15)  # console: not on Windows
        return r.stdout if r.returncode == 0 and r.stdout.strip() else None  # (not listed: gone, or a zombie)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        raw = (PROC / str(pid) / "cmdline").read_bytes()
    except OSError:
        return None  # neither ps nor /proc: a number alone is no proof
    return raw.replace(b"\0", b" ").decode("utf-8", errors="replace").strip() or None  # (empty: a zombie)
