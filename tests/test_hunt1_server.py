"""Hunt phase 1, area `server`: the local web server, its endpoints, its background jobs and uploads.

Each test asserts what the server should do; each fails today for the reason in its docstring."""
import json
import re
import threading
import time

import pytest

from test_app import CLAIM, Api, home  # noqa: F401  (fixtures)


@pytest.fixture
def served(home):  # noqa: F811
    """The app's server on a free port, with its App (to look at jobs)."""
    from enlens_claims.gui.server import make_server

    srv, app = make_server("127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield Api(f"http://127.0.0.1:{srv.server_address[1]}", app.token), app
    srv.shutdown()
    srv.server_close()


def _project(api, name="P", docs=()):
    assert api("PUT", "/api/settings", {"backend": "baseline", "embed_backend": "off"})[0] == 200
    assert api("POST", "/api/projects", {"name": name})[0] == 200
    if docs:
        for i, text in enumerate(docs):
            assert api("POST", f"/api/projects/{name}/uploads?batch=b0&name=d{i}.txt", raw=text.encode())[0] == 200
        st, r = api("POST", f"/api/projects/{name}/ingest", {"batch": "b0"})
        assert st == 200, r
        assert api.wait(r["job"]["id"])["state"] == "done"


def _doc_text(topic: str) -> str:
    return f"This report is about {topic}. " + f"The {topic} programme was studied in three regions over five years. " * 25


def test_two_files_of_the_same_name_in_one_upload_are_both_added(served):
    """Two files called report.txt (from two folders) in one batch: the second upload overwrites the first in the
    batch folder, so only one document is added (gui/api_documents.py:351 `post_upload`, `target = folder / fname`)."""
    api, _app = served
    _project(api)
    a, b = _doc_text("wind energy"), _doc_text("water management")
    assert api("POST", "/api/projects/P/uploads?batch=b1&name=report.txt", raw=a.encode())[0] == 200
    assert api("POST", "/api/projects/P/uploads?batch=b1&name=report.txt", raw=b.encode())[0] == 200
    st, r = api("POST", "/api/projects/P/ingest", {"batch": "b1"})
    job = api.wait(r["job"]["id"])
    assert job["state"] == "done", job["error"]
    assert job["result"]["added"] == 2
    assert len(api("GET", "/api/projects/P/documents")[1]["documents"]) == 2


def _name_key(name: str) -> str:
    """How macOS and Windows compare file names: case and composed or decomposed accents do not count."""
    import unicodedata

    return unicodedata.normalize("NFC", name).casefold()


@pytest.mark.parametrize("first,second", [
    ("Report.txt", "report.txt"),                                        # case: one file on macOS and Windows
    ("caf\u00e9.txt", "cafe\u0301.txt"),                                 # é composed and decomposed (macOS NFD)
    ("a:b.txt", "a_b.txt"),                                              # equal once ':' is cleaned to '_'
    ("what?.txt", "what*.txt"),                                          # '?' and '*' both become '_'
])
def test_two_files_whose_names_are_one_file_name_are_both_kept(served, first, second):
    """Sibling of the same-name upload: names that differ only by case or by composed/decomposed accents name one
    file on macOS and Windows, and names that become equal once ':', '?', '*' are cleaned name one file everywhere.
    The second must get a name of its own in the batch folder (and say so), on every platform: today the response
    gives back the same name (gui/api_documents.py `post_upload`)."""
    api, _app = served
    _project(api)
    from urllib.parse import quote

    st1, r1 = api("POST", f"/api/projects/P/uploads?batch=b1&name={quote(first)}", raw=_doc_text("wind energy").encode())
    st2, r2 = api("POST", f"/api/projects/P/uploads?batch=b1&name={quote(second)}", raw=_doc_text("rivers").encode())
    assert st1 == st2 == 200, (r1, r2)
    assert _name_key(r1["name"]) != _name_key(r2["name"]), (r1, r2)
    st, r = api("POST", "/api/projects/P/ingest", {"batch": "b1"})
    job = api.wait(r["job"]["id"])
    assert job["state"] == "done" and job["result"]["added"] == 2, job


def test_a_second_upload_of_a_name_that_is_cut_off_leaves_the_first_file(served):
    """Sibling: a cut-off upload removes its file; when it had the name of a file already in the batch, it removed
    that complete file (`_save_body` unlinks the target it shared with the first)."""
    import http.client

    api, _app = served
    _project(api)
    assert api("POST", "/api/projects/P/uploads?batch=b1&name=report.txt", raw=_doc_text("wind energy").encode())[0] == 200
    host, port = api.base.rsplit("/", 1)[-1].split(":")
    conn = http.client.HTTPConnection(host, int(port), timeout=10)
    conn.putrequest("POST", "/api/projects/P/uploads?batch=b1&name=report.txt")
    conn.putheader("X-Enlens-Token", api.token)
    conn.putheader("Content-Length", "100000")
    conn.endheaders()
    conn.send(b"half a file")
    conn.sock.shutdown(1)   # the client stops sending: the server reads to the end and finds the body cut off
    assert conn.getresponse().status == 400
    conn.close()
    st, r = api("POST", "/api/projects/P/ingest", {"batch": "b1"})
    job = api.wait(r["job"]["id"])
    assert job["state"] == "done" and job["result"]["added"] == 1, job


def test_an_upload_named_like_a_windows_device_is_kept_under_another_name(served):
    """Sibling (the hunter's NEEDS WINDOWS lead): CON, NUL, COM1 … name devices on Windows whatever the extension, so
    "CON.txt" written into the batch folder goes to the console there. The name is changed on every platform, so a
    project moved to Windows has no such file either; today it is kept as it came."""
    api, _app = served
    _project(api)
    for raw in ("CON.txt", "nul.pdf", "com1.txt", "Lpt9.md"):
        st, r = api("POST", f"/api/projects/P/uploads?batch=b1&name={raw}", raw=b"x")
        assert st == 200, r
        stem = r["name"].split(".")[0].strip().upper()
        assert stem not in {"CON", "PRN", "AUX", "NUL"} and not re.fullmatch(r"(COM|LPT)[0-9]", stem), r


def test_an_upload_with_a_name_too_long_for_the_disk_is_kept_shortened(served):
    """Sibling: a name over 255 bytes (or one that the "(2)" of a taken name pushes over) raised OSError "File name
    too long", a 500; it is shortened, keeping its extension."""
    from urllib.parse import quote

    api, _app = served
    _project(api)
    long = quote("\u00e1" * 200 + ".txt")   # 404 bytes in UTF-8
    st, r = api("POST", f"/api/projects/P/uploads?batch=b1&name={long}", raw=_doc_text("forests").encode())
    assert st == 200, r
    assert r["name"].endswith(".txt") and len(r["name"].encode()) <= 255
    st, r2 = api("POST", f"/api/projects/P/uploads?batch=b1&name={long}", raw=_doc_text("rivers").encode())
    assert st == 200 and r2["name"] != r["name"] and len(r2["name"].encode()) <= 255, r2


def test_documents_of_a_removed_project_never_land_in_a_new_project_of_its_name(served, tmp_path, monkeypatch):
    """A project is removed while documents are being added to it (from a folder), and a new project of the same name
    is made: the running job goes on writing the old project's documents into the new one (gui/api_documents.py:41
    `delete_project` neither refuses nor stops the project's jobs; the job's Workspace reopens the path)."""
    from enlens_claims import ingest

    api, _app = served
    _project(api)
    src = tmp_path / "folder"
    src.mkdir()
    for i in range(3):
        (src / f"d{i}.txt").write_text(_doc_text(f"topic number {i}"))
    at_second, go_on = threading.Event(), threading.Event()
    real = ingest.ingest

    def slow_reader(ws, inputs, progress=None, **kw):   # the second file takes a while to read
        def prog(i, n, f):
            if i == 1:
                at_second.set()
                go_on.wait(20)
            if progress:
                progress(i, n, f)
        return real(ws, inputs, progress=prog, **kw)

    monkeypatch.setattr(ingest, "ingest", slow_reader)
    st, r = api("POST", "/api/projects/P/ingest", {"path": str(src)})
    assert st == 200, r
    assert at_second.wait(20)
    removed = api("DELETE", "/api/projects/P", {"confirm": "P"})[0]
    made = api("POST", "/api/projects", {"name": "P"})[0] if removed == 200 else None
    go_on.set()
    api.wait(r["job"]["id"])
    if removed == 200 and made == 200:   # (a server that refuses to remove a busy project keeps it whole: fine)
        assert api("GET", "/api/projects/P/documents")[1]["documents"] == []


def _held_ingest(api, monkeypatch, tmp_path, project="P"):
    """Documents from a folder are being added to `project`, the reader held at the second file: (job id, go_on)."""
    from enlens_claims import ingest

    src = tmp_path / f"folder-{project}"
    src.mkdir()
    for i in range(3):
        (src / f"d{i}.txt").write_text(_doc_text(f"topic number {i}"))
    at_second, go_on = threading.Event(), threading.Event()
    real = ingest.ingest

    def slow_reader(ws, inputs, progress=None, **kw):
        def prog(i, n, f):
            if i == 1:
                at_second.set()
                go_on.wait(20)
            if progress:
                progress(i, n, f)
        return real(ws, inputs, progress=prog, **kw)

    monkeypatch.setattr(ingest, "ingest", slow_reader)
    st, r = api("POST", f"/api/projects/{project}/ingest", {"path": str(src)})
    assert st == 200, r
    assert at_second.wait(20)
    return r["job"]["id"], go_on


def test_removing_a_project_while_its_job_runs_is_refused_in_words(served, tmp_path, monkeypatch):
    """SERVER-1, the decision: removal is refused (409) while a job of the project is queued or running, in words that
    name the job and say to stop it or wait; the project stays whole, and once the job has ended it can be removed."""
    api, _app = served
    _project(api)
    job_id, go_on = _held_ingest(api, monkeypatch, tmp_path)
    try:
        st, r = api("DELETE", "/api/projects/P", {"confirm": "P"})
        assert st == 409 and r["kind"] == "busy", r
        assert "Adding sources" in r["error"] and "Stop" in r["error"], r
        assert "P" in [p["name"] for p in api("GET", "/api/projects")[1]["projects"]]
    finally:
        go_on.set()
    assert api.wait(job_id)["state"] == "done"
    assert api("DELETE", "/api/projects/P", {"confirm": "P"})[0] == 200


def test_a_quick_look_whose_job_runs_is_not_cleared_away_when_its_week_is_up(served, tmp_path, monkeypatch):
    """Sibling of SERVER-1: every GET /api/state moves quick looks older than a week to the trash (home.py
    `cleanup_quicklooks`), also one whose job still runs (a check waiting days for Claude Code, documents being added
    as the week ends). The job goes on through its Workspace, and a new quick look of the same file gets the same name
    (`create_quicklook`), so the old job writes into it, as in SERVER-1."""
    import json as _json

    from enlens_claims import home as _home

    api, _app = served
    _project(api)
    ws = _home.create_quicklook("report.pdf")
    name = ws.root.name
    job_id, go_on = _held_ingest(api, monkeypatch, tmp_path, project=name)
    try:
        f = _home.home() / "quicklook.json"
        data = _json.loads(f.read_text())
        data[name]["created_at"] -= 8 * 86400   # a week and a day ago
        f.write_text(_json.dumps(data))
        assert api("GET", "/api/state")[0] == 200
        assert name in [p["name"] for p in api("GET", "/api/projects")[1]["projects"]]
    finally:
        go_on.set()
    api.wait(job_id)
    api("GET", "/api/state")   # once the job has ended, it goes as before
    assert name not in [p["name"] for p in api("GET", "/api/projects")[1]["projects"]]


def test_numbers_too_large_and_fields_of_the_wrong_type_are_answered_in_words(served):
    """A number like 1e400 (JSON Infinity, or ?limit=1e400) or a field of the wrong type (a list or an object where text is
    expected) gives a 500 "Unexpected problem" instead of a 400: `_route` (gui/server.py:2171-2186) maps ValueError
    and KeyError, but not the OverflowError of int(inf) or the TypeError of a wrong type."""
    api, _app = served
    _project(api, docs=[_doc_text("solar power")])
    doc = api("GET", "/api/projects/P/documents")[1]["documents"][0]["doc_id"]
    raw = lambda obj: json.dumps(obj).encode()  # noqa: E731 - json.dumps writes 1e400 as Infinity
    asks = [("GET", "/api/projects/P/hypotheses?limit=1e400", None),
            ("GET", f"/api/projects/P/documents/{doc}?offset=1e400", None),
            ("GET", "/api/projects/P/log?limit=1e400", None),
            ("GET", "/api/projects/P/search?q=solar&limit=1e400", None),
            ("PUT", "/api/settings", raw({"k": 1e400})),
            ("POST", "/api/projects/P/batches", raw({"items": 5})),
            ("POST", "/api/projects/P/log", raw({"text": "a field note", "subject_id": ["h1"]})),
            ("POST", "/api/projects/P/codebooks/example", raw({"quote": "solar power", "doc_id": {"a": 1}}))]
    answers = {f"{m} {p}": api(m, p, raw=b) for m, p, b in asks}
    bad = {k: v for k, v in answers.items() if v[0] >= 500}
    assert not bad, bad


def test_a_token_with_an_accented_letter_is_refused_with_401(served):
    """A wrong token that holds a letter outside ASCII makes `secrets.compare_digest` raise TypeError: the request
    gets a 500 "Unexpected problem" instead of the 401 that tells how to open ENLENS (gui/server.py:2156)."""
    api, _app = served
    st, body = api("GET", "/api/state", token=False, headers={"X-Enlens-Token": "jelszó"})
    assert st == 401, body


def test_stop_pressed_after_a_job_has_finished_does_not_mark_it_stopped(served):
    """Stop that reaches the server just after a job ended (a second tab, or a click as it ends) sets the job's
    cancel flag anyway, so the finished job's view says "stopped": true from then on and the pages treat its whole
    result as stopped (gui/api_checks.py:428 `post_cancel`, gui/api_common.py:78 `view`)."""
    api, _app = served
    _project(api)
    assert api("POST", "/api/projects/P/uploads?batch=b1&name=a.txt", raw=_doc_text("forests").encode())[0] == 200
    st, r = api("POST", "/api/projects/P/ingest", {"batch": "b1"})
    job = api.wait(r["job"]["id"])
    assert job["state"] == "done" and job["stopped"] is False
    api("POST", f"/api/jobs/{job['id']}/cancel")
    after = api("GET", f"/api/jobs/{job['id']}")[1]
    assert after["state"] == "done" and after["stopped"] is False


def test_a_join_proof_with_an_accented_letter_is_refused_not_an_error():
    """Sibling of the token above: a colleague's first file in the shared folder carries a join proof, compared with
    `hmac.compare_digest` as two str; one holding a letter outside ASCII (a forged or damaged file) raised TypeError in
    the round instead of being refused (sync/seal.py `check_join_proof`)."""
    from enlens_claims.sync import seal

    assert seal.check_join_proof(b"k" * 32, "p1", "anna", {"sign": "s", "box": "b"}, "jelszó") is False


# ---------------------------------------------------------------------------------------------------------------------
# The sweep (SERVER-3): every route of the route table, each field it reads given a value of the wrong kind; never 500
# ---------------------------------------------------------------------------------------------------------------------
# Routes the sweep leaves alone: they quit or restart the app, install or download, open a window or a terminal, start
# Claude Code or a model, reach the network, or remove the project the sweep works in (the API key routes are
# swept: the keychain is the file one in the sweep's home, which the test checks). Each is a
# decision about a side effect, not about input (their input readers are the shared ones the sweep does reach).
SWEEP_SKIP = {
    "post_quit", "post_restart", "post_update", "get_update",                        # the app itself
    "post_ollama_install", "post_ollama_start", "post_pull", "post_test", "get_servers", "get_ollama",
    "get_local_status", "post_benchmark", "post_repeatable", "get_provider_models",   # a local model or a server
    "post_install_claude_code", "post_claude_sign_in", "post_agent_install", "post_agent_sign_in", "post_agent_tidy",
    "post_claude_code_start", "post_claude_code_stop", "post_queue_run",              # Claude Code or an agent
    "post_choose_folder", "post_notify_test",                                         # a window, a notification
    "get_zotero", "get_zotero_collections", "get_zotero_works", "post_bibliography", "post_bibliography_files",
    "post_references", "post_retractions_check",                                      # Zotero, Crossref
    "post_join_team", "post_space_peek", "post_space_b2", "post_space_r2", "post_space_webdav", "post_space_join",
    "post_space_move", "post_space_drive_retry", "put_space_drive_password",          # storage on the network
    "delete_project", "post_move", "post_second_computer",                            # the sweep's own project
}
BODY_KEY = r"""(?:body|b|data)\.get\(\s*["'](\w+)["']|(?:body|b|data)\[["'](\w+)["']\]|["'](\w+)["'] in (?:body|b|data)\b|_body_int\(\s*\w+,\s*["'](\w+)["']"""
QUERY_KEY = r"""_(?:str|int|float|bool|list)\(\s*q,\s*["'](\w+)["']|\bq\.get\(\s*["'](\w+)["']"""
BAD_BODY = {"number": 7, "list": ["x", [1]], "null": None, "object": {"a": {"b": [1]}}, "long": "x" * 200_000,
            "true": True}
BAD_QUERY = {"word": "x", "huge": "1e400", "nan": "nan", "minus": "-inf", "long": "x" * 20_000}


def _sweep_routes():
    from enlens_claims.gui import server

    return [(m, rx.pattern[1:-1], h) for m, rx, h in server.ROUTES if h not in SWEEP_SKIP]


def _keys_of(handler: str) -> tuple[set[str], set[str]]:
    """The body and query keys a handler reads: in its own source, and one call deeper (self._helper, self.app.method)."""
    import inspect
    import re

    from enlens_claims.gui import server

    def source(obj, name):
        f = getattr(obj, name, None)
        try:
            return inspect.getsource(f) if callable(f) else ""
        except (OSError, TypeError):
            return ""

    src = source(server.Handler, handler)
    more = [source(server.Handler, n) for n in set(re.findall(r"self\.(_?\w+)\(", src)) if n != handler]
    more += [source(server.App, n) for n in set(re.findall(r"self\.app\.(\w+)\(", src))]
    text = "\n".join([src, *more])
    body = {k for t in re.findall(BODY_KEY, text) for k in t if k}
    query = {k for t in re.findall(QUERY_KEY, text) for k in t if k}
    return body, query


def _sweep_docs() -> list[str]:
    """Eight documents that share glossary terms, enough for a set of themes."""
    terms = ["renewable energy", "water management", "climate adaptation", "public transport", "soil erosion",
             "local government"]
    out = []
    for i in range(8):
        a, b = terms[i % 6], terms[(i + 2) % 6]
        out.append("\n\n".join(f"Section {k}. The {a} programme and the {b} plan were studied in region {k}. "
                                f"Officials said {a} needs {b} and that {a} improved over five years. " * 6
                                for k in range(6)))
    return out


@pytest.fixture(scope="module")
def swept(tmp_path_factory):
    """One app for the whole sweep: a project P with a document, a check and its ids, in a home of its own; the
    server's working folder is a temporary one (a path field given "xxx…" lands there)."""
    from enlens_claims.gui.server import make_server

    root = tmp_path_factory.mktemp("sweep")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("ENLENS_HOME", str(root / "home"))
        mp.delenv("ANTHROPIC_API_KEY", raising=False)
        # what conftest's own fixtures set for each test, also for the setting up and for jobs still running between
        # two tests: no real Claude Code, Codex or agy, no keychain, no notification
        for k, v in {"ENLENS_CLAUDE": str(root / "no-claude-here"), "ENLENS_CODEX": str(root / "no-codex-here"),
                     "ENLENS_AGY": str(root / "no-agy-here"), "ENLENS_AGENT_HOME": str(root / "agent-home"),
                     "ENLENS_KEYCHAIN": "file", "ENLENS_NO_NOTIFY": "1", "ENLENS_READ_WORKERS": "1"}.items():
            mp.setenv(k, v)
        mp.chdir(root)
        srv, app = make_server("127.0.0.1", 0)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        api = Api(f"http://127.0.0.1:{srv.server_address[1]}", app.token)
        _project(api, docs=_sweep_docs())
        st, r = api("POST", "/api/projects/P/checks", {"text": "Renewable energy improved over five years."})
        assert st == 200, r
        api.wait(r["job"]["id"])
        docs = api("GET", "/api/projects/P/documents")[1]["documents"]
        doc = docs[0]["doc_id"]
        hyp = api("GET", "/api/projects/P/hypotheses")[1]["hypotheses"][0]["hyp_id"]
        passage = app.ws("P").scalar("SELECT passage_id FROM passages LIMIT 1")
        ids = {"projects": "P", "documents": doc, "passages": passage, "hypotheses": hyp, "jobs": r["job"]["id"],
               "judgements": passage, "codebooks": "sdg", "frameworks": "sdg"}
        st, out = api("POST", "/api/projects/P/log", {"text": "A field note for the sweep."})
        ids["log"] = out["entry"]["entry_id"] if st == 200 else "x"
        st, out = api("POST", "/api/projects/P/notes", {"doc_id": doc, "start": 0, "end": 11, "text": "a note"})
        ids["notes"] = out["note"]["note_id"] if st == 200 else "x"
        st, out = api("POST", "/api/projects/P/themes", {})
        run = api.wait(out["job"]["id"]) if st == 200 else {}
        ids["themes"] = (run.get("result") or {}).get("run_id") or "x"
        assert "x" not in ids.values(), ids   # (a sweep of unknown ids would stop at the 404 and test nothing more)
        yield api, app, ids, root
        for job in app.jobs.all():
            app.jobs.cancel(job)
        for job in app.jobs.all():
            t0 = time.monotonic()
            while job.state in ("queued", "running") and time.monotonic() - t0 < 30:
                time.sleep(0.05)
        srv.shutdown()
        srv.server_close()


def _fill(pattern: str, ids: dict) -> str:
    """The route's path with its parts filled in: an id of the sweep's project where the segment before names one."""
    import re

    segs = pattern.replace("([^/]+)", "\0").split("/")
    out = []
    for i, seg in enumerate(segs):
        if seg == "\0":
            seg = ids.get(segs[i - 1], "x")
        elif seg.startswith("(m[0-9a-f]"):
            seg = "m" + "0" * 12
        else:   # (themes|check|codebook), name\.(csv|xlsx), *\.png: the first choice
            seg = re.sub(r"\(([^)|]+)(\|[^)]*)?\)", r"\1", seg.replace("\0", "x")).replace("\\.", ".")
        out.append(seg)
    return "/".join(out)


@pytest.mark.parametrize("method,pattern,handler", _sweep_routes(), ids=lambda v: v if isinstance(v, str) and
                         not v.startswith("/") else None)
def test_no_route_answers_500_to_a_field_of_the_wrong_kind(swept, method, pattern, handler, monkeypatch):
    """Every route, every field it reads given a number, a list, null, a nested object, a very long text or true (and
    a query value of a word, 1e400, nan, -inf or a very long text): a request a person or a script gets wrong is answered
    in words (4xx), never with 500 "Unexpected problem" (the hunter's sweep found 21 such answers)."""
    from urllib.parse import quote

    api, _app, ids, root = swept
    monkeypatch.setenv("ENLENS_HOME", str(root / "home"))   # (conftest gives every test a home of its own)
    from enlens_claims import keychain

    assert keychain.backend() == "file"   # the API key routes are swept: never the system's keychain
    monkeypatch.chdir(root)
    path = _fill(pattern, ids)
    body_keys, query_keys = _keys_of(handler)
    asks: list[tuple[str, bytes | None]] = []
    if method == "GET":
        for k in sorted(query_keys):
            for v in BAD_QUERY.values():
                asks.append((f"{path}?{k}={quote(v)}", None))
    else:
        for k in sorted(body_keys):
            for v in BAD_BODY.values():
                asks.append((path, json.dumps({k: v}).encode()))
        for v in BAD_BODY.values():   # every key the handler reads at once, as the hunter's sweep did
            asks.append((path, json.dumps(dict.fromkeys(body_keys, v)).encode()))
        asks.append((path, b'{"k": Infinity, "n": NaN, "m": 1e400}'))
        for k in sorted(query_keys):
            for v in BAD_QUERY.values():
                asks.append((f"{path}?{k}={quote(v)}", b"{}"))
    if not asks:
        asks.append((path, None if method == "GET" else b"{}"))
    bad = []
    for p, raw in asks:
        st, out = api(method, p, raw=raw)
        assert not (st == 404 and isinstance(out, dict) and out.get("error") == "No such API endpoint."), p
        if st >= 500:
            short = lambda t: re.sub(r"x{12,}", "x…", str(t))[:160]  # noqa: E731
            bad.append(f"{method} {short(p)} {short((raw or b'').decode())} -> {st} "
                       f"{short(out.get('error') if isinstance(out, dict) else out)}")
    assert not bad, "\n".join(bad)


# ---------------------------------------------------------------------------------------------------------------------
# The hunter's lead: "Read the new documents" pressed twice
# ---------------------------------------------------------------------------------------------------------------------
def _new_document_by_queue(api, app, tmp_path, monkeypatch):
    """A check made with the stand-in model, a document added after it, then Claude Code's queue as the AI: (hyp_id)."""
    from test_app import _SkewedDatetime

    from enlens_claims import store

    _project(api, docs=[_doc_text("solar power"), _doc_text("wind energy")])
    st, r = api("POST", "/api/projects/P/checks", {"text": "The solar power programme was studied in regions."})
    hid = api.wait(r["job"]["id"])["result"]["hyp_id"]
    monkeypatch.setattr(store, "_dt", _SkewedDatetime(2))   # stored times have whole seconds
    (tmp_path / "late").mkdir()
    (tmp_path / "late" / "late.txt").write_text(_doc_text("solar power") + " A late study.")
    assert api.wait(api("POST", "/api/projects/P/ingest", {"path": str(tmp_path / "late")})[1]["job"]["id"])["state"] == "done"
    assert api("GET", f"/api/projects/P/hypotheses/{hid}")[1]["docs_added_since"]
    assert api("PUT", "/api/settings", {"backend": "claude_code"})[0] == 200 and app.queue_mode()
    return hid


@pytest.mark.parametrize("second", ["one", "all"])
def test_read_the_new_documents_pressed_twice_by_queue_starts_one_round(served, tmp_path, monkeypatch, second):
    """By Claude Code's queue a job does not hold the model's turn, so a second press of "Read the new documents" (or
    "Read the new documents" for all hypotheses beside it) started a second job beside the first: it found the first
    one's round waiting and ended in error with "Grade the passages already shown first (submit_grades)", words meant
    for the connector; pressed at the same moment, both could make a round of the same documents. As "read unread"
    does, a second press gives back the job already at it (gui/api_checks.py `post_read_new_one`, `post_read_new`)."""
    api, app = served
    hid = _new_document_by_queue(api, app, tmp_path, monkeypatch)
    st, a = api("POST", f"/api/projects/P/hypotheses/{hid}/read-new", {})
    assert st == 200, a
    path = f"/api/projects/P/hypotheses/{hid}/read-new" if second == "one" else "/api/projects/P/read-new"
    st, b = api("POST", path, {})
    try:
        assert st in (200, 409), b
        if st == 200:
            assert b["job"]["id"] == a["job"]["id"], (a["job"], b["job"])
        t0 = time.monotonic()
        while time.monotonic() - t0 < 1.5:   # (the second job, had one started, fails within this time)
            time.sleep(0.1)
        errors = [j for j in app.jobs.all() if j.kind == "read-new" and j.state == "error"]
        assert not errors, [j.error for j in errors]
    finally:
        for j in app.jobs.all():
            app.jobs.cancel(j)
        for j in app.jobs.all():
            t0 = time.monotonic()
            while j.state in ("queued", "running") and time.monotonic() - t0 < 20:
                time.sleep(0.05)


# ---------------------------------------------------------------------------------------------------------------------
# After review (SERVER-1 and the leads): a removal does not hold every job up; the words fit the button
# ---------------------------------------------------------------------------------------------------------------------
def _in_thread(fn):
    """Run fn() in a thread: (thread, box) with box["out"] once it has answered."""
    box = {}
    t = threading.Thread(target=lambda: box.update(out=fn()), daemon=True)
    t.start()
    return t, box


def test_a_slow_removal_holds_no_other_project_up_and_nothing_starts_in_the_one_removed(served, monkeypatch):
    """The removal looked for a running job and moved the folder under the jobs' lock: while the move took (home.LOCK
    held by the connector, Windows retrying a held file for 5 s, a copy to another disk) the job list, every job start
    and every finishing job waited, so every page with jobs froze. The project is now marked as being removed under
    the lock and moved after it: the job list and a job in another project go on, and a job in the project being
    removed is refused in words."""
    from enlens_claims import home as _home

    api, _app = served
    _project(api, "Q")
    _project(api)
    assert api("POST", "/api/projects/Q/uploads?batch=b1&name=a.txt", raw=_doc_text("forests").encode())[0] == 200
    assert api("POST", "/api/projects/P/uploads?batch=b1&name=a.txt", raw=_doc_text("rivers").encode())[0] == 200
    moving, go_on = threading.Event(), threading.Event()
    real = _home.remove_project

    def slow_remove(name):
        moving.set()
        go_on.wait(20)
        return real(name)

    monkeypatch.setattr(_home, "remove_project", slow_remove)
    remover, removed = _in_thread(lambda: api("DELETE", "/api/projects/P", {"confirm": "P"}))
    try:
        assert moving.wait(10)
        lister, listed = _in_thread(lambda: api("GET", "/api/jobs"))
        starter, started = _in_thread(lambda: api("POST", "/api/projects/Q/ingest", {"batch": "b1"}))
        refused, refusal = _in_thread(lambda: api("POST", "/api/projects/P/ingest", {"batch": "b1"}))
        for t in (lister, starter, refused):
            t.join(5)
        assert listed.get("out", (None,))[0] == 200, "the job list waited for the removal"
        assert started.get("out", (None,))[0] == 200, "a job in another project waited for the removal"
        st, r = refusal.get("out", (None, None))
        assert st == 409 and "being removed" in r["error"], r
    finally:
        go_on.set()
        remover.join(20)
    assert removed["out"][0] == 200, removed
    api.wait(started["out"][1]["job"]["id"])


def test_discarding_a_busy_quick_look_says_discard(served, tmp_path, monkeypatch):
    """The refusal named the wrong button for a quick look: "… then remove the project"; its button is Discard."""
    from enlens_claims import home as _home

    api, _app = served
    _project(api)
    name = _home.create_quicklook("report.pdf").root.name
    job_id, go_on = _held_ingest(api, monkeypatch, tmp_path, project=name)
    try:
        st, r = api("DELETE", f"/api/projects/{name}", {"confirm": name})
        assert st == 409 and "discard" in r["error"].lower() and "remove the project" not in r["error"], r
    finally:
        go_on.set()
    api.wait(job_id)


def test_the_state_answers_when_the_list_of_linked_projects_is_damaged(served):
    """A quick look whose week is up is moved to the trash at GET /api/state; with links.json damaged the removal
    raised home.Damaged (a ValueError), which the state request did not catch: the whole page answered 500. The person
    is told about the damaged file by the action that needs the list."""
    import json as _json

    from enlens_claims import home as _home

    api, _app = served
    _project(api)
    name = _home.create_quicklook("report.pdf").root.name
    f = _home.home() / "quicklook.json"
    data = _json.loads(f.read_text())
    data[name]["created_at"] -= 8 * 86400
    f.write_text(_json.dumps(data))
    (_home.home() / "links.json").write_text("{ not json")
    st, r = api("GET", "/api/state")
    assert st == 200, r


def test_a_slow_look_for_unread_documents_holds_no_other_project_up(served, monkeypatch):
    """`post_read_unread` held the app's one ONE_START lock across its search for unread documents, so a press in any
    other project that looks for its own job first (Read the new documents, a new theme, the new reader) waited behind
    it. The lock now belongs to the project."""
    from enlens_claims import claimcheck

    api, _app = served
    hids = {}
    for p in ("Q", "P"):
        _project(api, p, docs=[_doc_text("solar power"), _doc_text("wind energy")])
        st, r = api("POST", f"/api/projects/{p}/checks", {"text": "The solar power programme was studied in regions."})
        hids[p] = api.wait(r["job"]["id"])["result"]["hyp_id"]
    searching, go_on = threading.Event(), threading.Event()
    real = claimcheck.unread_documents

    def slow(ws, hyp_id, *a, **kw):
        if hyp_id == hids["P"]:
            searching.set()
            go_on.wait(20)
        return real(ws, hyp_id, *a, **kw)

    monkeypatch.setattr(claimcheck, "unread_documents", slow)
    first, _ = _in_thread(lambda: api("POST", f"/api/projects/P/hypotheses/{hids['P']}/read-unread", {}))
    try:
        assert searching.wait(10)
        other, answer = _in_thread(lambda: api("POST", f"/api/projects/Q/hypotheses/{hids['Q']}/read-new", {}))
        other.join(5)
        assert answer.get("out", (None,))[0] == 200, "a press in another project waited for the search"
    finally:
        go_on.set()
        first.join(20)
    api.wait(answer["out"][1]["job"]["id"])


@pytest.mark.parametrize("path", ["/api/settings/key", "/api/settings/provider-key"])
def test_an_api_key_that_is_not_text_is_refused_in_words(served, path):
    """A list or an object as the key went through str() and was kept as the key ("['x']")."""
    api, _app = served
    for bad in (["sk-x"], {"a": 1}, 7):
        st, r = api("POST", path, {"key": bad, "provider": "openai", "remember": True})
        assert st == 400 and "key" in r["error"].lower(), (bad, r)
