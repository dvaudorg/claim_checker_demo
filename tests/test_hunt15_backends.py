"""Hunt phase 1.5, area `backends`: every item phase 0 and phase 1 left open in the model backends, the agent CLIs,
routing, scoring and the records of what made an answer, settled by a test (ledger:
.claude/audits/2026-11-19-phase1.5/ledger/backends.md). Tests that need Windows' cmd.exe or PowerShell run on the
CI machines that have them; each has a twin here that runs everywhere."""
from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler
from pathlib import Path

import pytest

from addon_fixtures import addon  # noqa: F401 - a fixture
from test_task_kinds import addon_tag_task, notes  # noqa: F401 - a fixture

WINDOWS = os.name == "nt"
NASTY = 'a & echo pwned > x.txt & b'


def _pwsh() -> str | None:
    return shutil.which("pwsh") or shutil.which("powershell")


# --------------------------------------------------------------------------------------------- 1: evaluation copies
def test_an_evaluation_or_model_test_copy_carries_no_team_settings(loaded, tmp_path):
    """Owner: `evaluation._copy` copied config.json whole, so a copy for an acceptance run or a model test held the
    original's shared folder and storage space: a round run in it would act in the team's place with the same keys.
    The copy keeps every other setting."""
    from enlens_claims import evaluation, store
    from enlens_claims.sync import folder, space

    store.change_config(loaded.config_path, {folder.FOLDER: str(tmp_path / "team"), folder.KEEP_OUT: True,
                                             space.CONFIG: {"id": "s1", "kind": "b2", "bucket": "b"},
                                             "ai_access_default": "local"})
    loaded._config_cache = None
    copy = evaluation._copy(loaded, "ws eval label haiku")
    cfg = json.loads(copy.config_path.read_text(encoding="utf-8"))
    assert folder.FOLDER not in cfg and space.CONFIG not in cfg, cfg
    assert cfg["ai_access_default"] == "local"
    assert folder.chosen(copy) is None and space.configured(copy) is None
    ref = json.loads(loaded.config_path.read_text(encoding="utf-8"))
    assert ref[space.CONFIG]["id"] == "s1" and ref[folder.FOLDER]   # the original keeps them


# --------------------------------------------------------------------------------------------- 2: codex.cmd
_NPM_SHIM = ('@ECHO off\r\nGOTO start\r\n:find_dp0\r\nSET dp0=%~dp0\r\nEXIT /b\r\n:start\r\nSETLOCAL\r\nCALL :find_dp0\r\n'
             '\r\nIF EXIST "%dp0%\\node.exe" (\r\n  SET "_prog=%dp0%\\node.exe"\r\n) ELSE (\r\n  SET "_prog=node"\r\n'
             '  SET PATHEXT=%PATHEXT:;.JS;=;%\r\n)\r\n\r\nendLocal & goto #_undefined_# 2>NUL || title %COMSPEC% & '
             '"%_prog%"  "%dp0%\\node_modules\\{pkg}\\bin\\{name}.js" %*\r\n')


def _npm_install(where: Path, name: str, script: str = "", node_beside: bool = True) -> tuple[Path, Path]:
    """A program installed the way `npm i -g` does on Windows: <name>.cmd (npm's cmd-shim) and the script it starts."""
    pkg = "@openai\\codex" if name == "codex" else "fake-agy"
    target = where / "node_modules" / Path(pkg.replace("\\", "/")) / "bin" / f"{name}.js"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(script or "// the CLI", encoding="utf-8")
    shim = where / f"{name}.cmd"
    shim.write_text(_NPM_SHIM.replace("{pkg}", pkg).replace("{name}", name), encoding="utf-8")
    if node_beside:
        (where / "node.exe").write_bytes(b"")
    return shim, target


def _prompt(route="codex"):
    from enlens_claims import agentcli

    p = agentcli.helper_prompt(route, NASTY + ' "100%" <x> | %PATH% ^', "label", "haiku", "enlens-labeller",
                               "enlens-labeller in Codex #1")
    assert "\n" in p and '"' in p and "&" in p and "%PATH%" in p
    return p


def test_a_helpers_prompt_is_never_handed_to_cmd_exe(monkeypatch, tmp_path):
    """Owner, the platform-free half: npm installs Codex as `codex.cmd`, which Windows starts through cmd.exe, and
    cmd.exe reads the line again (it stops at the first line break, runs `& echo pwned` from a project's name, and
    expands %PATH%). On Windows the helper's command now starts the program the command file starts (node and the
    script), so the prompt reaches it whole; a command file ENLENS cannot see through is refused for a helper."""
    from enlens_claims import agentcli

    monkeypatch.setattr(agentcli, "_windows", lambda: True)
    shim, script = _npm_install(tmp_path / "npm", "codex")
    prompt = _prompt()
    args = agentcli.run_args("codex", str(shim), prompt, "gpt-6-luna", None, tmp_path, options={"-c", "-m", "--json"})
    assert args[:2] == [str(tmp_path / "npm" / "node.exe"), str(script)]
    assert args[-1] == prompt and not any(str(a).lower().endswith((".cmd", ".bat")) for a in args)
    # Antigravity installed the same way
    agy, agy_script = _npm_install(tmp_path / "npm2", "agy")
    a = agentcli.run_args("antigravity", str(agy), prompt, "gemini-4-argon", None, tmp_path,
                          options={"-p", "--sandbox", "--model"})
    assert a[:2] == [str(tmp_path / "npm2" / "node.exe"), str(agy_script)] and a[a.index("-p") + 1] == prompt
    # a command file of another kind: no helper is started through it, in words
    other = tmp_path / "other" / "codex.bat"
    other.parent.mkdir()
    other.write_text('@"C:\\Python\\python.exe" "%~dp0rec.py" %*\r\n', encoding="utf-8")
    with pytest.raises(ValueError, match="command file"):
        agentcli.run_args("codex", str(other), prompt, "gpt-6-luna", None, tmp_path, options={"-c"})
    # and Start says so before anything runs
    monkeypatch.setattr(agentcli, "find", lambda route: str(other))
    with pytest.raises(ValueError, match="installer"):
        agentcli.start_run("codex", "Q")
    # elsewhere (and for a program that is no command file) nothing changes
    monkeypatch.setattr(agentcli, "_windows", lambda: False)
    assert agentcli.run_args("codex", str(shim), prompt, "m", None, tmp_path, options={"-c"})[0] == str(shim)


@pytest.mark.skipif(not WINDOWS or not shutil.which("node"), reason="cmd.exe and npm's command files: Windows CI")
def test_codex_cmd_from_npm_gets_the_prompt_whole_on_windows(tmp_path, monkeypatch):
    """Owner, on Windows: a codex.cmd as npm writes it, whose script records the arguments it was given. The helper's
    command (run_args) is started as `_spawn` starts it: the prompt with its line breaks, quotes, & and %PATH%, and a
    project named `a & echo pwned > x.txt & b`, arrives whole, and no stray file appears. Review: a version manager's
    node.cmd first on the PATH is passed over for the real node.exe."""
    from enlens_claims import agentcli

    manager = tmp_path / "nvm"
    manager.mkdir()
    (manager / "node.cmd").write_text("@echo node.cmd must not run & exit /b 3\r\n", encoding="utf-8")
    monkeypatch.setenv("PATH", f"{manager}{os.pathsep}{os.environ['PATH']}")
    out = tmp_path / "argv.json"
    rec = "require('fs').writeFileSync(process.env.REC_OUT, JSON.stringify(process.argv.slice(2)));\n"
    shim, _script = _npm_install(tmp_path / "npm", "codex", rec, node_beside=False)
    prompt = _prompt()
    args = agentcli.run_args("codex", str(shim), prompt, "gpt-6-luna", None, tmp_path, options={"-c", "-m"})
    assert args[0].lower().endswith("node.exe"), args[0]
    r = subprocess.run(args, cwd=str(tmp_path), env={**os.environ, "REC_OUT": str(out)}, capture_output=True,
                       text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    got = json.loads(out.read_text(encoding="utf-8"))
    assert got[-1] == prompt and got[0] == "exec", got
    assert not list(tmp_path.rglob("x.txt"))


@pytest.mark.skipif(not WINDOWS, reason="cmd.exe: Windows CI")
def test_a_command_file_of_another_kind_gets_safe_arguments_whole_and_no_prompt_on_windows(tmp_path, monkeypatch):
    """Owner, on Windows: a codex.cmd that hands its arguments to a Python script. The calls without free text (the
    version, the help, `login`) go through cmd.exe with each argument quoted for it (`procs.program_args`), so even
    `&` and %PATH% arrive whole; a helper's prompt is never put on its line (refused in words)."""
    from enlens_claims import agentcli, home

    out = tmp_path / "argv.json"
    (tmp_path / "rec.py").write_text("import json, os, sys\n"
                                     "open(os.environ['REC_OUT'], 'w', encoding='utf-8').write(json.dumps(sys.argv[1:]))\n",
                                     encoding="utf-8")
    cmd = tmp_path / "codex.cmd"
    cmd.write_text(f'@"{sys.executable}" "%~dp0rec.py" %*\r\n', encoding="utf-8")
    monkeypatch.setenv("REC_OUT", str(out))
    code, said = agentcli._run([str(cmd), "exec", NASTY, "%PATH%", 'say "hi"', "100%"], timeout=120)
    assert code == 0, said
    assert json.loads(out.read_text(encoding="utf-8")) == ["exec", NASTY, "%PATH%", 'say "hi"', "100%"]
    assert not list(tmp_path.rglob("x.txt")) and not list(home.home().rglob("x.txt"))
    with pytest.raises(ValueError, match="command file"):
        agentcli.run_args("codex", str(cmd), _prompt(), "m", None, tmp_path, options={"-c"})


# --------------------------------------------------------------------------------------------- 3: the sign-in line
def test_the_antigravity_sign_in_line_holds_nothing_a_shell_reads_into(tmp_path):
    """Owner, the platform-free half: the Windows line was `powershell -Command "…; $env:USERPROFILE='…'; …; agy"`, and
    PowerShell expands $env:… inside double quotes before the child starts, so agy ran in the person's own home. The
    line now carries the commands as -EncodedCommand: nothing in it is read by PowerShell or cmd.exe, whatever the
    folders' names hold, and no script file is run (review: an execution policy of AllSigned stops a script, not
    this)."""
    from enlens_claims import agentcli

    home = str(agentcli.agy_home())
    for work in (tmp_path / "Ábel Gergő" / "work", tmp_path / "A$b%PATH%`x" / "work"):
        line = agentcli.windows_sign_in_line(str(tmp_path / "agy.exe"), work)
        head, enc = line.rsplit(" ", 1)
        assert head == "powershell -NoProfile -EncodedCommand" and set(enc) <= set(
            "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/="), line
        body = base64.b64decode(enc).decode("utf-16-le")
        assert body == agentcli.sign_in_commands(str(tmp_path / "agy.exe"), work)
        assert f"$env:USERPROFILE = '{home}'" in body and f"$env:HOME = '{home}'" in body
        assert f"Set-Location -LiteralPath '{work}'" in body and body.endswith(f"& '{tmp_path / 'agy.exe'}'")


@pytest.mark.skipif(_pwsh() is None, reason="PowerShell: GitHub's Windows and Linux machines have it, this Mac does not")
def test_the_antigravity_sign_in_line_runs_agy_in_enlens_home_when_pasted(tmp_path, monkeypatch):
    """Owner, where PowerShell exists: the line the page shows, typed into PowerShell (and, on Windows, into cmd.exe),
    starts a stand-in agy that records its home folder: it is ENLENS's own, not the person's."""
    from enlens_claims import agentcli

    out = tmp_path / "agy-home.json"
    fake = tmp_path / "fake_agy.py"
    fake.write_text("import json, os\n"
                    "open(os.environ['REC_OUT'], 'w', encoding='utf-8').write(json.dumps({'HOME': os.environ.get("
                    "'HOME'), 'USERPROFILE': os.environ.get('USERPROFILE'), 'cwd': os.getcwd()}))\n", encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir()
    line = agentcli.windows_sign_in_line(str(fake), work)
    (tmp_path / "own-home").mkdir()   # the person's own home folder, which agy must not run in
    env = {**os.environ, "REC_OUT": str(out), "HOME": str(tmp_path / "own-home"),
           "USERPROFILE": str(tmp_path / "own-home")}
    if not WINDOWS:   # the line names Windows PowerShell; here pwsh stands in for it
        bindir = tmp_path / "bin"
        bindir.mkdir()
        (bindir / "powershell").symlink_to(_pwsh())
        env["PATH"] = f"{bindir}{os.pathsep}{env['PATH']}"
    shells = [[_pwsh(), "-NoProfile", "-NonInteractive", "-Command", line]]
    if WINDOWS:
        shells.append(line)   # shell=True: cmd.exe /c, as typed into a Command Prompt
    home = str(agentcli.agy_home())
    for sh in shells:
        out.unlink(missing_ok=True)
        r = subprocess.run(sh, shell=isinstance(sh, str), env=env, capture_output=True, text=True, timeout=180,
                           stdin=subprocess.DEVNULL)
        assert out.exists(), (sh, r.returncode, r.stdout[-2000:], r.stderr[-2000:])
        got = json.loads(out.read_text(encoding="utf-8"))
        assert got["HOME"] == home and got["USERPROFILE"] == home, (sh, got)
        assert Path(got["cwd"]).resolve() == work.resolve()


# --------------------------------------------------------------------------------------------- 4, 5: Antigravity runs
def _agy_run(monkeypatch, corpus):
    from enlens_claims import agentcli
    from test_agent_cli import AGY, _project

    monkeypatch.setenv("ENLENS_AGY", AGY)
    monkeypatch.setenv("FAKE_AGY_PLAN", "pro")
    monkeypatch.setattr(agentcli, "POLL", 0.2)
    monkeypatch.setattr(agentcli, "IDLE_ROUNDS", 3)
    agentcli.forget_status()
    return _project(corpus, "antigravity")


def test_a_refused_antigravity_helper_says_why_and_takes_no_number(monkeypatch, corpus):
    """Surface review: `run["n"]` was raised before Antigravity's always-proceed refusal, so a refused helper took a
    number; and the run report said the refusal as "The run stopped: ValueError: …". The report says the refusal in
    its own words and numbers only helpers that started."""
    from enlens_claims import agentcli
    from test_agent_cli import _wait_done

    _agy_run(monkeypatch, corpus)
    calls = []

    def proceeds():   # the check at Start passes; the settings say "always proceed" by the first helper's start
        calls.append(1)
        return len(calls) > 1

    monkeypatch.setattr(agentcli, "always_proceeds", proceeds)
    agentcli.start_run("antigravity", "Q")
    st = _wait_done(agentcli, "antigravity")
    run = agentcli._RUNS[("antigravity", "Q")]
    assert st["exit_code"] == 1 and run["n"] == run["started"] == 0, (run["n"], run["started"])
    assert "say to run every tool without asking" in st["report"] and "ValueError" not in st["report"], st["report"]


# --------------------------------------------------------------------------------------------- 6: theme sheets
def test_a_theme_sheet_written_before_the_model_answered_does_not_score_the_reference(ws, tmp_path):
    """Fixer left: an older version wrote g6_theme_names_<model>.csv from every named theme of the copy, the
    reference's names included, when it scored before the model answered. A person's "fitting" on those names was then
    scored as the model's. Only rows holding the name the model gave count."""
    from enlens_claims import evaluation
    from enlens_claims.acceptance import _write

    with ws.connect() as cx:
        for tid, name in ((1, "Water scarcity near plants"), (2, "Jobs in export regions")):
            cx.execute("INSERT INTO themes(run_id, theme_id, name, description, name_source) VALUES "
                       "('r1', ?, ?, '', 'model')", (tid, name))
    folder = tmp_path / "acceptance"
    sheet = folder / "g6_theme_names_haiku.csv"
    _write(sheet, [{"theme_id": 1, "name": "Reference name one", "description": "", "fitting": "yes", "note": ""},
                   {"theme_id": 2, "name": "Reference name two", "description": "", "fitting": "yes", "note": ""}])
    done = {"theme:r1:1", "theme:r1:2"}
    s = evaluation._score_theme(ws, folder, "haiku", done)
    assert s.get("score") is None and "other names" in s["note"], s
    _write(sheet, [{"theme_id": 1, "name": "Water scarcity near plants", "description": "", "fitting": "no", "note": ""},
                   {"theme_id": 2, "name": "Reference name two", "description": "", "fitting": "yes", "note": ""}])
    s = evaluation._score_theme(ws, folder, "haiku", done)
    assert s["score"] == 0.0 and s["themes"] == 1 and s["names_not_the_models"] == 1, s


# --------------------------------------------------------------------------------------------- 7: embedding server
class _FarEmbedder:
    """An embedding server on another computer that records what it is sent."""
    model = "far-embed"

    def __init__(self, base_url="http://10.20.30.40:11434"):
        self.base_url = base_url
        self.sent: list[str] = []

    def embed(self, texts):
        self.sent += list(texts)
        return [[1.0, float(len(t) % 7), 0.5] for t in texts]


def _local_doc_quote(ws) -> tuple[str, str]:
    from enlens_claims import access

    doc_id, text = ws.query("SELECT doc_id, text FROM passages WHERE section='body' AND length(text) > 200 "
                            "ORDER BY doc_id LIMIT 1")[0]
    access.set_documents(ws, [doc_id], "local")
    return doc_id, " ".join(text.split()[2:14])


def test_codebook_text_quoting_a_local_only_document_never_reaches_a_far_embedder(loaded, tmp_path):
    """Hunter's strongest suspicion: search by meaning embedded every code's text with whatever embedder was set up,
    so a codebook made from a theory document marked Only a local AI (its definitions quote it) went to an embedding
    server on another computer, which the privacy page does not say. Such text stays here, in this project and in
    another one; an embedder on this computer still gets it; a code in a person's own words still goes."""
    from enlens_claims import codebooks, frameworks, home, profile
    from enlens_claims.store import Workspace

    doc_id, quote = _local_doc_quote(loaded)
    codebooks.create(loaded, "lens", "A theory lens", "home", "theory",
                          {"doc_ids": [doc_id], "codes": [{"code": "Repair", "description": f"Meaning. “{quote}”",
                                                           "source_docs": [doc_id]}]})
    fw = frameworks.get("lens", loaded)
    far = _FarEmbedder()
    profile.code_vectors(loaded, fw, far)
    assert not any(quote in t for t in far.sent), far.sent
    other = Workspace.create(tmp_path / "other")   # the home codebook in a project without that document
    far2 = _FarEmbedder()
    profile.code_vectors(other, frameworks.get("lens", other), far2)
    assert not any(quote in t for t in far2.sent), far2.sent
    near = _FarEmbedder("http://127.0.0.1:11434")
    profile.code_vectors(other, frameworks.get("lens", other), near)
    assert any(quote in t for t in near.sent)
    # a codebook made before this mark existed, quoting the document in this project; an AI's draft of a definition;
    # and a person's own words
    own = frameworks.Framework("mine", "Mine", "code", {
        "Quoted": frameworks.Code("Quoted", f"As the report says, {quote}."),
        "Drafted": frameworks.Code("Drafted", "Repair keeps things in use longer than buying new ones."),
        "Own": frameworks.Code("Own", "Fixing broken things together at a community event.")},
        source="home", meta={"ids": {"Quoted": "u1", "Drafted": "u2", "Own": "u3"},
                             "drafted": {"u2": {"model": "local", "at": "", "description": "Repair keeps things"}}})
    far3 = _FarEmbedder()
    got = profile.code_vectors(loaded, own, far3)
    assert [t for t in far3.sent if "Own:" in t] and not [t for t in far3.sent if "Quoted:" in t or "Drafted:" in t]
    assert set(got) == {"Own"}
    assert home.home()   # (the data folder of the test)


# --------------------------------------------------------------------------------------------- 8: add-ons, temperature
def test_the_documented_addon_api_still_records_the_model_in_the_ai_log(notes, monkeypatch):  # noqa: F811
    """Surface review: `access.record_sent` now requires `model=`, so an add-on calling it without would fail. It is
    not part of the documented add-on API (docs/EXTENDING.md, docs/ADDON_API.md): an add-on's task kind is queued,
    handed out and recorded by ENLENS itself, which names the model (the ledger has a row per passage a payload
    names; this stand-in's notes are none)."""
    from enlens_claims import access, taskqueue, tasks

    root = Path(__file__).resolve().parents[1]
    for doc in ("docs/EXTENDING.md", "docs/ADDON_API.md", "docs/ADDON_MANUAL.md"):
        assert "record_sent" not in (root / doc).read_text(encoding="utf-8"), doc
    ws = notes
    with tasks.queueing(True), ws.connect() as cx:
        addon_tag_task(cx)
    seen = []
    real = access.record_sent

    def record(*a, **kw):
        seen.append(kw.get("model"))
        return real(*a, **kw)

    monkeypatch.setattr(access, "record_sent", record)
    batch = taskqueue.next_tasks(ws, kind="fake_tag")
    assert batch["claim"] and seen == [batch["model"]] == ["haiku"], seen


def test_how_results_were_made_says_what_is_true_of_an_old_answers_temperature(loaded):
    """Surface review: an answer that recorded no temperature showed "" (none sent) where it showed 0. Before 0.8.2
    nothing was recorded, and the route is not known either (the Claude API then sent none, a local server 0): it
    says "not recorded"; a record of a local server lacking one says 0 (always sent); none sent stays ""."""
    from enlens_claims import runs

    rows = [("t1", None), ("t2", json.dumps({"backend": "ollama", "route": "local model server"})),
            ("t3", json.dumps({"backend": "anthropic", "route": "Claude API"})),
            ("t4", json.dumps({"backend": "ollama", "temperature": 0}))]
    with loaded.connect() as cx:
        for i, (tid, settings) in enumerate(rows):
            cx.execute("INSERT INTO results(task_id, attempt, kind, model, prompt_version, raw_json, valid, received_at, "
                       "settings_json) VALUES (?, 0, 'label', ?, 'label-v1', '{}', 1, ?, ?)",
                       (tid, f"m{i}", f"2026-01-0{i + 1}", settings))
    temp = {r["AI model"]: r["Temperature"] for r in runs.provenance_table(loaded, task_ids=[t for t, _s in rows])
            if "AI model" in r}
    assert temp == {"m0": "not recorded", "m1": 0, "m2": "", "m3": 0}, temp


# --------------------------------------------------------------------------------------------- 9: *.localhost
def test_a_local_model_at_a_localhost_name_says_to_type_localhost(monkeypatch):
    """Fixer left: since phase 1 `*.localhost` and `localhost.localdomain` are another computer, so documents marked
    Only a local AI wait when the local model is set there. The person is told why and the way out, in the
    changelog's words (type localhost or 127.0.0.1)."""
    from enlens_claims import access, home, providers
    from enlens_claims.gui.server import App
    from enlens_claims.llm import BackendError

    s = {"backend": "claude_code", "restricted_server": "ollama", "restricted_model": "qwen3.5:4b",
         "ollama_url": "http://ollama.localhost:11434"}
    with pytest.raises(BackendError, match="type localhost or 127.0.0.1 instead"):
        home.make_restricted_backend(s)
    assert "type localhost or 127.0.0.1" in access.local_status(s)["problem"]
    far = {**s, "ollama_url": "http://10.0.0.5:11434"}
    with pytest.raises(BackendError) as e:
        home.make_restricted_backend(far)
    assert "localhost" not in str(e.value)   # a real other computer: no hint
    assert providers.looks_local("http://localhost.localdomain:1234/v1") and not providers.looks_local("http://lab:1")
    # the main route at such an address: the Settings line names the way out too
    st = App.providers_state(App.__new__(App), {"backend": "ollama", "ollama_url": "http://box.localhost:11434"})
    assert st["route_address"] and "type localhost" in st["route_address_note"]
    st = App.providers_state(App.__new__(App), {"backend": "ollama", "ollama_url": "http://10.0.0.5:11434"})
    assert st["route_address_note"] == ""


# --------------------------------------------------------------------------------------------- 10: Hold
def test_a_helper_that_found_its_kind_on_hold_is_not_a_failed_helper(monkeypatch, corpus, tmp_path):
    """Hunter's note: a helper started before the person put its kind on Hold takes nothing (the queue hands nothing
    of a held kind out); it counted as a failed helper, and three such ended the run with "did not answer the
    queue"."""
    from enlens_claims import agentcli, routing, taskqueue
    from enlens_claims.store import now
    from test_agent_cli import CODEX, _project

    monkeypatch.setenv("ENLENS_CODEX", CODEX)
    agentcli.forget_status()
    ws = _project(corpus, "codex")
    assert taskqueue._waiting_count(ws, "label") > 0
    taskqueue.set_order(ws, "label", "hold")

    class Ended:
        pid, returncode = None, 0

        def poll(self):
            return 0

    said = []
    monkeypatch.setattr(agentcli, "read_outcome", lambda *a: {"ok": True, "limit": "", "signed_out": False,
                                                                "message": "", "refused": []})
    monkeypatch.setattr(agentcli, "_write_record", lambda run: None)
    monkeypatch.setattr(agentcli, "_say", lambda run, line: said.append(line))
    procs = []
    for i in range(agentcli.MAX_FAILED):
        out = tmp_path / f"helper{i}.out"
        out.write_text("done", encoding="utf-8")
        procs.append({"proc": Ended(), "group": ("label", "haiku", "enlens-labeller"), "out": out, "since": now(),
                      "taken_by": f"enlens-labeller in Codex #{i + 1}", "model_id": "gpt-6-luna", "waited": 1})
    run = {"route": "codex", "project": "Q", "batches": 0, "refused": [], "failed_in_row": 0,
           "router": routing.from_settings({"backend": "codex"}, route="codex"), "procs": procs}
    assert agentcli._reap(run, ws) is None
    assert run["failed_in_row"] == 0 and not any("without answering" in s for s in said), said


# --------------------------------------------------------------------------------------------- 11: odd stream chunks
class _Stream(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(n)
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        for line in self.server.lines:
            self.wfile.write((line + "\n").encode())
            self.wfile.flush()


def _serve(lines):
    from enlens_claims.gui.server import QuickServer

    srv = QuickServer(("127.0.0.1", 0), _Stream)
    srv.lines = lines
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def test_a_stream_chunk_of_another_shape_is_skipped_not_a_crash():
    """Hunter's note: Ollama's reader did `chunk.get("message") or {}` then `.get`, so a chunk whose "message" is a
    string raised AttributeError out of `complete` (no handler catches it); the OpenAI-compatible reader said "Could
    not reach the local server" for the same. A chunk of another shape is skipped, as a line that does not parse is."""
    import time

    from enlens_claims.llm import LocalBackend, OllamaBackend

    srv, url = _serve(['{"message": "odd"}', '{"message": {"content": 5}}', '[1, 2]',
                       '{"message": {"content": "{\\"ok\\": true}"}}', '{"done": true, "eval_count": 3}'])
    try:
        be = OllamaBackend(base_url=url, timeout=30, stall_timeout=10)
        info = {"task": "check", "model": "m", "phase": "waiting", "prompt_tokens": 1, "thinking_tokens": 0,
                "answer_tokens": 0, "seconds": 0.0, "first_token_after": None, "rate": None, "tail": "", "cap": 100,
                "thinks": False, "budget": None, "budget_reached": False, "memory_freed": None}
        content, final = be._stream({"model": "m"}, "m", info, time.time(), 0)
        assert "".join(content) == '{"ok": true}' and final.get("done")
    finally:
        srv.shutdown()
    srv, url = _serve(['data: [1, 2]', 'data: {"choices": "odd"}', 'data: {"choices": [{"delta": "odd"}]}',
                       'data: {"choices": [{"delta": {"content": 7}}]}',
                       'data: {"choices": [{"delta": {"content": "{\\"ok\\": 1}"}, "finish_reason": "stop"}]}',
                       "data: [DONE]"])
    try:
        assert LocalBackend(base_url=url, timeout=30, stall_timeout=10)._run("check", "m", {}, 1, 100) == '{"ok": 1}'
    finally:
        srv.shutdown()


# --------------------------------------------------------------------------------------------- 12: signed-out words
def test_design_in_a_helpers_message_is_not_a_sign_in_problem():
    """Hunter's note: SIGNED_OUT_WORDS had `sign ?in`, which matched "design in": a helper that failed saying so ended
    the run as "not signed in". Real sign-in messages still count."""
    from enlens_claims import agentcli

    def failed(msg):
        return json.dumps({"type": "turn.failed", "error": {"message": msg}})

    assert not agentcli.read_outcome("codex", failed("The design in passage 3 broke the schema"), 1)["signed_out"]
    for msg in ("Not logged in. Run codex login.", "Please sign in again", "401 Unauthorized",
                "authentication_error: invalid token"):
        assert agentcli.read_outcome("codex", failed(msg), 1)["signed_out"], msg


# --------------------------------------------------------------------------------------------- 13: a small card
def test_a_small_graphics_card_beside_much_memory_gets_the_tier_the_memory_allows_and_says_it_is_slow():
    """Hunter's note (a design question): a PC with a 4 GB NVIDIA card and 32 GB of memory is offered the larger
    model on the processor. That is the rule written in docs/manual/local-models.md's tier table (small only for
    about 8 GB "or no graphics card"; "about 24 GB or more": the larger model), so it stays; the advice says honestly
    that it runs on the processor and is slow, and offers the smaller ones."""
    from enlens_claims import modeladvice

    GB = 1 << 30
    facts = {"memory": 32 * GB, "disk_free": 200 * GB, "system": "windows", "unified": False, "gpu": 4 * GB}
    chat = modeladvice.advise(facts)["chat"]
    assert chat["pick"]["name"] == modeladvice.LARGE_MODEL and chat["pick"]["speed"] == "slow"
    assert "processor" in chat["pick"]["speed_text"] and chat["smaller"]["name"] == modeladvice.MEDIUM_MODEL


# --------------------------------------------------------------------------------------------- 14: codex login
def test_quit_ends_a_codex_sign_in_still_waiting_for_the_browser(monkeypatch):
    """Hunter's note: `codex login` (started by Sign in, waiting for the browser) was not stopped at Quit: only the
    tests' reset ended it, so it outlived the app."""
    from enlens_claims import agentcli
    from test_agent_cli import CODEX

    monkeypatch.setenv("ENLENS_CODEX", CODEX)
    monkeypatch.setenv("FAKE_CODEX_LOGIN_DELAY", "60")
    agentcli.forget_status()
    agentcli.open_sign_in("codex")
    proc = agentcli._LOGIN["codex"]
    assert proc.poll() is None
    agentcli.stop_all_runs()
    assert proc.wait(timeout=15) is not None and "codex" not in agentcli._LOGIN


# --------------------------------------------------------------------------------------------- 15: validation labels
def test_an_unanswered_passage_is_never_a_right_code_decision():
    """Hunter's note: score_labels read a passage with no answer as "no code", so it was right for every code the gold
    set does not give it (two right of three here), as an unfinished check never is (`score_checks`). Its decisions
    are now "no answer", never right; a passage unanswered in one pass of repeatability agrees on no code."""
    from enlens_claims import validation as v
    from test_validation_report import _label, _pass

    s = v.score_labels([_label("1", ["A"], ["A"]), _label("2", [], None)], ["A", "B", "C"])
    assert s["code_decisions"] == 6 and s["code_accuracy"] == 0.5 and s["same_codes"] == 0.5, s
    p1 = _pass(checks=[], labels=[_label("1", [], None)])
    p2 = _pass(checks=[], labels=[_label("1", [], [])])
    r = v.repeatability(p1, p2, ["A", "B"])["labels"]
    assert r["code_agreement"] == 0.0 and r["same_codes"] == 0.0, r


# --------------------------------------------------------------------------------------------- the run record (CI)
def test_a_helper_reading_the_run_record_while_the_runner_rewrites_it_always_finds_its_model(tmp_path):
    """CI, Linux on Python 3.10: the AI log said "not known (Antigravity's own choice)" for a helper ENLENS started
    with --model, while its answers named the model. The runner rewrites its record right after a helper starts and
    every round; written in place, the file was empty for a moment, and a helper taking its first batch just then
    found no record (`started_model`). The record is written whole: a reader finds the old one or the new one."""
    from enlens_claims import agentcli, home

    root = home.home() / "projects" / "Q"
    root.mkdir(parents=True)
    run = {"route": "antigravity", "project": "Q", "procs": [], "started_at": "", "t0": 0.0, "plan": {},
           "root": str(root.resolve()), "models": {"enlens-labeller in Antigravity #1": "gemini-4-hydrogen-high"}}
    agentcli._write_record(run)
    stop = threading.Event()

    def rewrite():
        while not stop.is_set():
            agentcli._write_record(run)

    t = threading.Thread(target=rewrite, daemon=True)
    t.start()
    try:
        misses = sum(agentcli.started_model("antigravity", root, "enlens-labeller in Antigravity #1")
                     != (True, "gemini-4-hydrogen-high") for _ in range(3000))
    finally:
        stop.set()
        t.join(10)
    assert misses == 0, misses


# --------------------------------------------------------------------------------------------- review of wave 1
def test_a_node_cmd_first_on_the_path_never_starts_a_helper(monkeypatch, tmp_path):
    """Review (BACKENDS15-2), platform-free twin: npm's shim names `node`, and a Node version manager may put a
    node.cmd first on the PATH, which brings cmd.exe back. Only a real node.exe is taken; with none, the helper is
    refused in words, and no helper's command starts with a command file."""
    from enlens_claims import agentcli

    monkeypatch.setattr(agentcli, "_windows", lambda: True)
    shim, script = _npm_install(tmp_path / "npm", "codex", node_beside=False)
    manager = tmp_path / "nvm" / "node.cmd"
    real = tmp_path / "nodejs" / "node.exe"
    for f in (manager, real):
        f.parent.mkdir(parents=True)
        f.write_text("", encoding="utf-8")
    on_path = {"node": str(manager), "node.exe": str(real)}
    monkeypatch.setattr(agentcli.shutil, "which", lambda name, *a, **k: on_path.get(name))
    args = agentcli.run_args("codex", str(shim), _prompt(), "m", None, tmp_path, options={"-c"})
    assert args[:2] == [str(real), str(script)]
    del on_path["node.exe"]   # only the version manager's command file
    with pytest.raises(ValueError, match="command file"):
        agentcli.run_args("codex", str(shim), _prompt(), "m", None, tmp_path, options={"-c"})


def test_the_makers_program_is_found_before_npms_command_file(monkeypatch, tmp_path):
    """Review note (BACKENDS15-2): the refusal says to install with the maker's installer, but `find` took npm's
    codex.cmd first on the PATH, so the refusal stayed after the person did. A real program wins wherever both are;
    the words say what to do if it stays."""
    from enlens_claims import agentcli

    monkeypatch.delenv("ENLENS_CODEX", raising=False)
    monkeypatch.setattr(agentcli, "_windows", lambda: True)
    npm = tmp_path / "npm" / "codex.cmd"
    exe = tmp_path / "bin" / "codex.exe"
    for f in (npm, exe):
        f.parent.mkdir(parents=True)
        f.write_text("", encoding="utf-8")
    on_path = {"codex": str(npm), "codex.exe": str(exe)}
    monkeypatch.setattr(agentcli.shutil, "which", lambda name, *a, **k: on_path.get(name))
    assert agentcli.find("codex") == str(exe)
    del on_path["codex.exe"]
    assert agentcli.find("codex") == str(npm)   # (the only one: npm's, started through its shim or refused)
    assert "npm uninstall -g" in agentcli._cmd_refused("codex", str(npm))


def test_the_icons_python_and_a_terminals_are_one_python_for_codex_and_antigravity(monkeypatch):
    """Review note: the twin of the install area's pythonw.exe item. `agentcli.stale` compared the recorded Python
    with sys.executable, so starting the app from the icon (pythonw.exe) and from a terminal (python.exe) in turn set
    Codex's and Antigravity's connector up again at each start; the connector names the console python.exe."""
    import json as _json

    from enlens_claims import agentcli, home

    monkeypatch.setattr(sys, "executable", "/env/Scripts/pythonw.exe")
    agentcli._record_setup("codex")
    rec = _json.loads((home.home() / "agent-clis.json").read_text(encoding="utf-8"))["codex"]
    assert rec["python"] == "/env/Scripts/pythonw.exe" or rec["python"].endswith("python.exe")
    monkeypatch.setattr(sys, "executable", "/env/Scripts/python.exe")
    assert agentcli.stale("codex") == ""
    monkeypatch.setattr(sys, "executable", "/other/Scripts/python.exe")
    assert "starts the connector with" in agentcli.stale("codex")


def _theory_book(ws, doc_id, quote, where="home", name="lens"):
    from enlens_claims import codebooks

    codebooks.create(ws, name, "A theory lens", where, "theory",
                     {"doc_ids": [doc_id], "codes": [{"code": "Repair", "description": f"Meaning. “{quote}” (Report, "
                                                                                       "p. 2)", "source_docs": [doc_id]}]})


def _sent(ws, name, embedder):
    from enlens_claims import frameworks, profile

    profile.code_vectors(ws, frameworks.get(name, ws), embedder)
    return embedder.sent


def test_an_old_theory_codebook_made_in_one_project_never_reaches_a_far_embedder_from_another(loaded, tmp_path):
    """Review, MUST FIX (a): a theory codebook made before this version (no record of its documents) and kept with
    all projects, from a document marked Only a local AI in project A, was sent from project B, where the six-word
    check finds nothing. In A its research-log entry says it came from theory; in B its quotations with their
    source do."""
    import json as _json

    from enlens_claims import codebooks, frameworks
    from enlens_claims.store import Workspace

    doc_id, quote = _local_doc_quote(loaded)
    _theory_book(loaded, doc_id, quote)
    side = codebooks._home_folder() / "lens.json"
    meta = _json.loads(side.read_text(encoding="utf-8"))
    meta.pop("theory", None)   # as a codebook made before this version
    meta.pop("theory_level", None)
    side.write_text(_json.dumps(meta), encoding="utf-8")
    assert "theory" not in (frameworks.get("lens", loaded).meta or {})
    other = Workspace.create(tmp_path / "B")
    assert not any(quote in t for t in _sent(other, "lens", _FarEmbedder()))
    assert not any(quote in t for t in _sent(loaded, "lens", _FarEmbedder()))


def test_a_theory_codebook_whose_documents_do_not_allow_the_embedders_provider_stays_here(loaded, tmp_path):
    """Review, MUST FIX (b): theory documents marked Claude may read it, but allowing Anthropic only: nothing was
    recorded (the level was taken without a provider), so an embedding server of another company got the quotes. It
    does not, in the project and outside it; a server of a company they allow does."""
    from enlens_claims import access
    from enlens_claims.store import Workspace

    doc_id, text = loaded.query("SELECT doc_id, text FROM passages WHERE section='body' AND length(text) > 200 "
                                "ORDER BY doc_id LIMIT 1")[0]
    quote = " ".join(text.split()[2:14])
    access.set_providers_default(loaded, ["anthropic"])
    _theory_book(loaded, doc_id, quote)
    assert not any(quote in t for t in _sent(loaded, "lens", _FarEmbedder()))
    other = Workspace.create(tmp_path / "B")
    assert not any(quote in t for t in _sent(other, "lens", _FarEmbedder()))
    access.set_providers_default(loaded, ["anthropic", "openai"])
    assert any(quote in t for t in _sent(loaded, "lens", _FarEmbedder("https://api.openai.com/v1")))


def test_a_theory_codebook_is_judged_by_its_documents_settings_now(loaded):
    """Review, MUST FIX (c): the level was fixed when the codebook was made, so a document made stricter afterwards
    did not keep its quotes from a far embedder. In its own project the documents are judged as they are now."""
    from enlens_claims import access, profile, frameworks

    doc_id, text = loaded.query("SELECT doc_id, text FROM passages WHERE section='body' AND length(text) > 200 "
                                "ORDER BY doc_id LIMIT 1")[0]
    quote = " ".join(text.split()[2:14])
    access.set_providers_default(loaded, ["anthropic", "other"])
    _theory_book(loaded, doc_id, quote, where="project", name="lens2")
    far = _FarEmbedder()
    assert any(quote in t for t in _sent(loaded, "lens2", far))   # allowed now: sent
    access.set_documents(loaded, [doc_id], "local")
    got = profile.code_vectors(loaded, frameworks.get("lens2", loaded), _FarEmbedder())
    assert "Repair" not in got   # withheld now, and its earlier vector is not used


def test_the_embed_guard_reads_restricted_passages_once_and_stops_when_every_code_is_decided(loaded, monkeypatch):
    """Review, SHOULD FIX: the guard kept every six-word run of every restricted passage, again on each pass while a
    code was withheld. It now reads the passages one at a time against the codes' own runs, stops once every code is
    decided, and reads nothing again while nothing changed (the work is bounded; the memory holds the codes' runs)."""
    from enlens_claims import access, embed, frameworks

    docs = [r[0] for r in loaded.query("SELECT DISTINCT doc_id FROM passages")]
    access.set_documents(loaded, docs, "local")
    docs = sorted(docs)
    first = loaded._conn().execute(f"SELECT text FROM passages WHERE doc_id IN ({','.join('?' * len(docs))})",
                                   docs).fetchone()[0]   # the passage the guard reads first
    n = loaded.scalar("SELECT COUNT(*) FROM passages")
    assert n > 2
    read = []
    real = embed._runs
    monkeypatch.setattr(embed, "_runs", lambda t: (read.append(t), real(t))[1])
    fw = frameworks.Framework("mine", "Mine", "code", {"Q": frameworks.Code("Q", first)}, source="home")
    texts = [("Q", f"code Q: {first}")]
    embed._HELD_MEMO.clear()
    assert embed.withheld_codes(loaded, fw, _FarEmbedder(), texts) == {"Q"}
    passages_read = len(read) - 1          # (one for the code's own text)
    assert passages_read < n, (passages_read, n)
    read.clear()
    assert embed.withheld_codes(loaded, fw, _FarEmbedder(), texts) == {"Q"}
    assert len(read) == 1                  # the code's text only: no passage read again


def test_a_code_whose_text_changed_is_never_matched_by_its_old_vector(loaded):
    """Review note: `code_vectors` returned every cached vector, so a code whose text changed and was now withheld was
    matched by the meaning of its old text."""
    from enlens_claims import frameworks, profile

    _doc, quote = _local_doc_quote(loaded)
    old = frameworks.Framework("mine", "Mine", "code", {"Q": frameworks.Code("Q", "Fixing things together.")},
                               source="home")
    assert "Q" in profile.code_vectors(loaded, old, _FarEmbedder())
    new = frameworks.Framework("mine", "Mine", "code", {"Q": frameworks.Code("Q", f"As said: {quote}.")},
                               source="home")
    assert "Q" not in profile.code_vectors(loaded, new, _FarEmbedder())
