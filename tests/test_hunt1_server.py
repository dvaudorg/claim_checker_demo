"""Hunt phase 1, area `server`: the local web server, its endpoints, its background jobs and uploads.

Each test asserts what the server should do; each fails today for the reason in its docstring."""
import json
import threading

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
