"""Hunt phase 1.5, area `server`: what phases 0 and 1 left about the local web server, its endpoints, jobs, uploads
and notifications. Each test asserts what the server should do (ledger: .claude/audits/2026-11-19-phase1.5/ledger/
server.md); the ones that failed on the code as it was are fixed, the others are kept as proof of "not a bug"."""
import json
import os
import socket
import threading
import time
from pathlib import Path

import pytest

from test_app import Api, home  # noqa: F401  (fixtures)


@pytest.fixture
def served(home):  # noqa: F811
    """The app's server on a free port, with its App (to look at jobs)."""
    from enlens_claims.gui.server import make_server

    srv, app = make_server("127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield Api(f"http://127.0.0.1:{srv.server_address[1]}", app.token), app
    srv.shutdown()
    srv.server_close()


def _doc_text(topic: str) -> str:
    return f"This report is about {topic}. " + f"The {topic} programme was studied in three regions over five years. " * 25


def _project(api, name="P", docs=(), ai_access="cloud"):
    """A project whose AI setting was chosen (the Documents page asks before the first Add)."""
    assert api("PUT", "/api/settings", {"backend": "baseline", "embed_backend": "off"})[0] == 200
    assert api("POST", "/api/projects", {"name": name})[0] == 200
    if docs:
        _add(api, name, docs, ai_access=ai_access)


def _add(api, name, docs, batch="b0", ai_access="cloud", names=None):
    from urllib.parse import quote

    for i, text in enumerate(docs):
        fname = names[i] if names else f"{batch}-d{i}.txt"
        assert api("POST", f"/api/projects/{name}/uploads?batch={batch}&name={quote(fname)}", raw=text.encode())[0] == 200
    body = {"batch": batch}
    if ai_access is not None:
        body["ai_access"] = ai_access
    st, r = api("POST", f"/api/projects/{name}/ingest", body)
    assert st == 200, r
    job = api.wait(r["job"]["id"])
    assert job["state"] == "done", job
    return job


def _ws(name):
    from enlens_claims import home as h

    return h.open_project(name)


# ---------------------------------------------------------------------------------------------------------------------
# Handed on during the round: documents never become readable by a cloud AI without anyone choosing
# ---------------------------------------------------------------------------------------------------------------------
def test_an_ingest_without_a_setting_in_a_project_without_a_chosen_default_adds_nothing(served):
    """`/api/projects/P/ingest` without `ai_access`, in a project whose default was never chosen: the app took "Claude
    may read it" (gui/server.py `start_ingest`). The rule (`ingest.adding_access`): a 400 that names the choice, and
    nothing added."""
    api, _app = served
    _project(api)
    assert api("POST", "/api/projects/P/uploads?batch=b1&name=a.txt", raw=_doc_text("wind").encode())[0] == 200
    st, r = api("POST", "/api/projects/P/ingest", {"batch": "b1"})
    assert st == 400, r
    assert "cloud" in r["error"] and "local" in r["error"] and "none" in r["error"]
    from enlens_claims import access

    ws = _ws("P")
    assert not access.default_chosen(ws)
    assert ws.scalar("SELECT COUNT(*) FROM documents") == 0


def test_an_ingest_with_a_chosen_default_needs_no_setting(served):
    api, _app = served
    _project(api, docs=[_doc_text("wind")], ai_access="none")
    job = _add(api, "P", [_doc_text("water")], batch="b2", ai_access=None)
    assert job["result"]["added"] == 1
    from enlens_claims import access

    ws = _ws("P")
    assert set(access.levels(ws, provider=None).values()) == {"none"}


def test_an_ingest_beside_documents_that_follow_an_unchosen_default_says_so_and_keeps_theirs(served):
    """Documents that follow a default nobody chose (an older project, or a quick look kept): a later Add with a
    setting gives the new documents their own and says how many earlier ones still follow the unchosen default; it
    does not make the answer the project's default (one answer about new files must not change the others)."""
    api, _app = served
    _project(api)
    from enlens_claims import access, ingest

    ws = _ws("P")
    src = Path(ws.root) / "old.txt"
    src.write_text(_doc_text("old records"), encoding="utf-8")
    ingest.ingest(ws, [src], set_default=False)  # as before 0.11: no setting, the default never chosen
    assert not access.default_chosen(ws)
    job = _add(api, "P", [_doc_text("water")], batch="b2", ai_access="none")
    assert job["result"]["added"] == 1
    assert not access.default_chosen(ws)
    assert "1 earlier document" in (job["result"].get("note") or ""), job["result"]
    lv = access.levels(ws, provider=None)
    assert sorted(lv.values()) == ["cloud", "none"]


def test_zoteros_files_without_a_setting_in_a_project_without_a_chosen_default_add_nothing(served, monkeypatch):
    """Sibling route: the bibliography's files (`start_bibliography_files` → `start_ingest`)."""
    api, app = served
    _project(api)
    from enlens_claims import bibliography

    f = Path(app.ws("P").root) / "zotero.txt"
    f.write_text(_doc_text("zotero"), encoding="utf-8")
    monkeypatch.setattr(bibliography, "files_to_add", lambda ws, keys=None: [f])
    st, r = api("POST", "/api/projects/P/bibliography/files", {})
    assert st == 400 and "none" in r["error"], r
    assert _ws("P").scalar("SELECT COUNT(*) FROM documents") == 0


def _quick_look(api):
    text = ("Interview with Anna Kovacs about the village water committee. " * 30).encode()
    st, r = api("POST", "/api/quicklook?name=Kovacs%20interview.txt", raw=text)
    assert st == 200, r
    job = api.wait(r["job"]["id"])
    assert job["state"] == "done", job
    return r["project"]["name"]


def test_a_quick_looks_document_is_for_a_local_ai_only_and_keeping_it_asks(served):
    """A quick look is for reading without AI; nobody is asked who may read its document, so no cloud AI may: its
    document gets its own setting "Only a local AI", the project's default stays unchosen, and keeping it asks."""
    api, _app = served
    assert api("PUT", "/api/settings", {"backend": "baseline", "embed_backend": "off"})[0] == 200
    name = _quick_look(api)
    from enlens_claims import access

    ws = _ws(name)
    assert not access.default_chosen(ws)
    assert set(access.levels(ws, provider=None).values()) == {"local"}
    from urllib.parse import quote

    assert api("POST", f"/api/projects/{quote(name)}/keep", {})[0] == 200
    info = api("GET", f"/api/projects/{quote(name)}/documents")[1]["ai_access"]
    assert info["chosen"] is False and info["ask"] is True


def test_the_connector_cannot_read_a_quick_looks_text(served, monkeypatch):
    pytest.importorskip("mcp")
    import asyncio

    from mcp import Client

    api, _app = served
    assert api("PUT", "/api/settings", {"backend": "baseline", "embed_backend": "off"})[0] == 200
    name = _quick_look(api)
    from enlens_claims.mcp_server import build_server

    async def go():
        async with Client(build_server()) as c:
            r = await c.call_tool("search_corpus", {"project": name, "query": "committee"})
            return json.loads(r.content[0].text)

    s = asyncio.run(go())
    assert s["lines"] == [] and s["restricted_hits"] == s["hits"] > 0, s


# ---------------------------------------------------------------------------------------------------------------------
# Item 2 (owner): a notification names no document marked "Only a local AI" or "No AI"
# ---------------------------------------------------------------------------------------------------------------------
SECRET = "Kovacs family interview"


def _secret_project(api, level):
    """A project with one document whose title (and file name) names a person, marked `level`."""
    _project(api)
    text = f"{SECRET}\n\n" + _doc_text("the village water committee")
    _add(api, "P", [text], batch="s1", ai_access=level, names=[f"{SECRET}.txt"])
    ws = _ws("P")
    doc_id, title = ws.query("SELECT doc_id, title FROM documents")[0]
    assert SECRET in title or SECRET in Path(ws.scalar("SELECT path FROM documents")).name
    return doc_id


def _notification(app, job, monkeypatch):
    """The notification the app sends when `job` ends after a long while (Settings: always)."""
    from enlens_claims import home as h
    from enlens_claims.gui import notify

    monkeypatch.delenv("ENLENS_NO_NOTIFY", raising=False)
    h.update_settings({"notify": "always"})
    t0 = time.time()
    while job.state in ("queued", "running"):
        assert time.time() - t0 < 30, "the job did not end"
        time.sleep(0.02)
    job.started = (job.finished or time.time()) - 120   # it took two minutes
    sent, ev = [], threading.Event()

    def send(title, text, url=""):
        sent.append((title, text))
        ev.set()

    assert notify.job_ended(app, job, send=send)
    assert ev.wait(10)
    return " ".join(sent[0])


def _shown(level):
    return level == "cloud"


LEVELS = ["cloud", "local", "none"]


@pytest.mark.parametrize("level", LEVELS)
def test_reading_one_document_with_the_new_reader_names_it_only_when_a_cloud_ai_may_read_it(served, monkeypatch, level):
    api, app = served
    doc_id = _secret_project(api, level)
    from enlens_claims import reread

    monkeypatch.setattr(reread, "move", lambda ws, d, person, **kw: {"counts": {}})
    job = app.start_new_reader("P", doc_id, "me")
    text = _notification(app, job, monkeypatch)
    assert (SECRET in text) is _shown(level), text


@pytest.mark.parametrize("level", LEVELS)
def test_following_references_names_the_person_only_when_a_cloud_ai_may_read_the_document(served, monkeypatch, level):
    api, app = served
    doc_id = _secret_project(api, level)
    from enlens_claims import references

    monkeypatch.setattr(references, "windows", lambda ws, d, who: [1])
    monkeypatch.setattr(references, "resolve_document", lambda *a, **k: {})
    job = app.start_resolve("P", doc_id, {"name": "Kovacs"})
    text = _notification(app, job, monkeypatch)
    assert ("Kovacs" in text) is _shown(level), text


@pytest.mark.parametrize("level", LEVELS)
def test_drafting_a_theorys_concepts_names_the_document_only_when_a_cloud_ai_may_read_it(served, monkeypatch, level):
    api, app = served
    doc_id = _secret_project(api, level)
    from enlens_claims import theorycodes

    monkeypatch.setattr(theorycodes, "ai_offer", lambda *a, **k: {"offered": True})
    monkeypatch.setattr(theorycodes, "draft_with_ai", lambda *a, **k: {"drafts": []})
    st, r = api("POST", f"/api/projects/P/codebook-theory/{doc_id}/ai", {})
    assert st == 200, r
    text = _notification(app, app.jobs.get(r["job"]["id"]), monkeypatch)
    assert (SECRET in text) is _shown(level), text


@pytest.mark.parametrize("level", LEVELS)
def test_an_error_that_names_a_document_names_it_only_when_a_cloud_ai_may_read_it(served, monkeypatch, level):
    """A check whose error names a document (a reader's or a model's message quoting a title)."""
    api, app = served
    doc_id = _secret_project(api, level)
    from enlens_claims import claimcheck

    title = _ws("P").scalar("SELECT title FROM documents WHERE doc_id=?", (doc_id,))

    def fail(*a, **k):
        raise ValueError(f"The excerpts of “{title}” could not be read.")

    monkeypatch.setattr(claimcheck, "check_hypothesis", fail)
    st, r = api("POST", "/api/projects/P/checks", {"text": "Water committees improve village water supply."})
    assert st == 200, r
    job = app.jobs.get(r["job"]["id"])
    text = _notification(app, job, monkeypatch)
    assert job.state == "error"
    assert (SECRET in text) is _shown(level), text
    assert "Water committees improve" in text   # the hypothesis's text stays


@pytest.mark.parametrize("level", LEVELS)
def test_adding_documents_that_fails_names_the_file_only_when_a_cloud_ai_may_read_it(served, monkeypatch, level):
    api, app = served
    _project(api, docs=[_doc_text("wind")])
    from enlens_claims import ingest

    def fail(ws, inputs, **kw):
        raise ValueError(f"{SECRET}.txt could not be read.")

    monkeypatch.setattr(ingest, "ingest", fail)
    assert api("POST", f"/api/projects/P/uploads?batch=s2&name={SECRET.replace(' ', '%20')}.txt",
               raw=b"x" * 50)[0] == 200
    st, r = api("POST", "/api/projects/P/ingest", {"batch": "s2", "ai_access": level})
    assert st == 200, r
    job = app.jobs.get(r["job"]["id"])
    text = _notification(app, job, monkeypatch)
    assert job.state == "error"
    assert (SECRET in text) is _shown(level), text


def test_a_quick_looks_notification_does_not_name_its_file(served, monkeypatch):
    """A quick look is named after its file, and its document is for a local AI only: the notification says "a quick
    look", not the project's name."""
    api, app = served
    assert api("PUT", "/api/settings", {"backend": "baseline", "embed_backend": "off"})[0] == 200
    text = ("Interview with Anna Kovacs about the village water committee. " * 30).encode()
    st, r = api("POST", "/api/quicklook?name=Kovacs%20interview.txt", raw=text)
    assert st == 200, r
    note = _notification(app, app.jobs.get(r["job"]["id"]), monkeypatch)
    assert "Kovacs" not in note, note


# ---------------------------------------------------------------------------------------------------------------------
# Item 3 (owner, decision 8): removing a project while a job of it runs
# ---------------------------------------------------------------------------------------------------------------------
def _round(app, name, gate):
    """A round of the shared folder the app started by itself (the poller's): the person cannot stop it."""
    from enlens_claims.sync import folder

    return app.jobs.start(folder.JOB, "Working together: the shared folder", name, lambda job: gate.wait(30),
                          uses_model=False, unique=True, background=True)


def test_removing_a_project_waits_briefly_for_a_background_round_of_the_shared_folder(served):
    api, app = served
    _project(api)
    gate = threading.Event()
    job = _round(app, "P", gate)
    threading.Timer(1.0, gate.set).start()
    t0 = time.time()
    st, r = api("DELETE", "/api/projects/P", {"confirm": "P"})
    assert st == 200, r
    assert time.time() - t0 >= 0.9 and job.state == "done"
    assert "P" not in [p["name"] for p in api("GET", "/api/state")[1]["projects"]]


def test_a_round_that_goes_on_says_try_again_in_a_moment(served, monkeypatch):
    api, app = served
    _project(api)
    from enlens_claims.gui import api_documents

    monkeypatch.setattr(api_documents, "ROUND_WAIT", 0.5)
    gate = threading.Event()
    _round(app, "P", gate)
    try:
        st, r = api("DELETE", "/api/projects/P", {"confirm": "P"})
        assert st == 409, r
        assert "brought up to date with your team" in r["error"] and "try again in a moment" in r["error"], r
        assert "Stop it" not in r["error"]   # the person cannot stop a round
    finally:
        gate.set()
    assert "P" in [p["name"] for p in api("GET", "/api/state")[1]["projects"]]


def test_a_job_the_person_can_stop_is_named_with_how_to_stop_it(served):
    """ALREADY FIXED in phase 1 (SERVER-1, `busy_with`): the 409 names the job and the sidebar's Stop."""
    api, app = served
    _project(api)
    gate = threading.Event()
    app.jobs.start("keywords", "Codes by keywords and meaning (sdg)", "P", lambda job: gate.wait(30), uses_model=False)
    try:
        st, r = api("DELETE", "/api/projects/P", {"confirm": "P"})
        assert st == 409 and "Codes by keywords" in r["error"] and "Stop it in the sidebar" in r["error"], r
    finally:
        gate.set()


def test_discarding_a_quick_look_waits_for_a_round_too(served):
    api, app = served
    assert api("PUT", "/api/settings", {"backend": "baseline", "embed_backend": "off"})[0] == 200
    name = _quick_look(api)
    from urllib.parse import quote

    gate = threading.Event()
    _round(app, name, gate)
    threading.Timer(0.8, gate.set).start()
    st, r = api("DELETE", f"/api/projects/{quote(name)}", {"confirm": name})
    assert st == 200, r


# ---------------------------------------------------------------------------------------------------------------------
# Item 1 (owner): the server guards against a double start (not only the page's buttons)
# ---------------------------------------------------------------------------------------------------------------------
@pytest.fixture
def gate():
    g = threading.Event()
    yield g
    g.set()


def _two(api, path, first, second=None):
    """Two presses: the second while the first job still runs. Returns both answers."""
    a = api("POST", path, first)
    b = api("POST", path, first if second is None else second)
    return a, b


def test_a_label_run_pressed_twice_is_one_job(served, monkeypatch, gate):
    api, app = served
    _project(api, docs=[_doc_text("wind"), _doc_text("water")])
    from enlens_claims import profile

    monkeypatch.setattr(profile, "pass1_status", lambda ws, fw: {"done": True})
    monkeypatch.setattr(profile, "run_labels", lambda *a, **k: gate.wait(30) and {})
    (s1, r1), (s2, r2) = _two(api, "/api/projects/P/profile/label", {"framework": "sdg"})
    assert s1 == s2 == 200, (r1, r2)
    assert r1["job"]["id"] == r2["job"]["id"]
    doc = _ws("P").scalar("SELECT doc_id FROM documents LIMIT 1")
    st, r = api("POST", "/api/projects/P/profile/label", {"framework": "sdg", "doc_ids": [doc]})
    assert st == 409 and "labels" in r["error"].lower(), r
    assert sum(j.kind == "label" for j in app.jobs.all()) == 1


def test_themes_pressed_twice_are_one_job(served, monkeypatch, gate):
    api, app = served
    _project(api, docs=[_doc_text("wind")])
    from enlens_claims import themes

    monkeypatch.setattr(themes, "choose_mode", lambda *a, **k: "terms")
    monkeypatch.setattr(themes, "run", lambda *a, **k: gate.wait(30) and "r1")
    (s1, r1), (s2, r2) = _two(api, "/api/projects/P/themes", {"k": 5})
    assert s1 == s2 == 200 and r1["job"]["id"] == r2["job"]["id"], (r1, r2)
    st, r = api("POST", "/api/projects/P/themes", {"k": 8})
    assert st == 409 and "themes" in r["error"].lower(), r
    assert sum(j.kind == "themes" for j in app.jobs.all()) == 1


def test_naming_the_themes_pressed_twice_is_one_job(served, monkeypatch, gate):
    api, app = served
    _project(api, docs=[_doc_text("wind")])
    ws = _ws("P")
    with ws.connect() as cx:
        cx.execute("INSERT INTO theme_runs(run_id) VALUES ('r1')")
    from enlens_claims import themes

    monkeypatch.setattr(themes, "name_with_model", lambda *a, **k: gate.wait(30) and {})
    (s1, r1), (s2, r2) = _two(api, "/api/projects/P/themes/r1/name", {})
    assert s1 == s2 == 200 and r1["job"]["id"] == r2["job"]["id"], (r1, r2)
    assert sum(j.kind == "theme-names" for j in app.jobs.all()) == 1


def test_naming_the_groups_of_the_concept_map_pressed_twice_is_one_job(served, monkeypatch, gate):
    api, app = served
    _project(api, docs=[_doc_text("wind")])
    from enlens_claims import conceptmap, groupnames

    monkeypatch.setattr(conceptmap, "concept_map", lambda *a, **k: {"groups": [{"id": 1}],
                                                                     "can_name": {"offered": True, "why": None}})
    monkeypatch.setattr(groupnames, "name_groups", lambda *a, **k: gate.wait(30) and {})
    (s1, r1), (s2, r2) = _two(api, "/api/projects/P/concept-map/name-groups", {"which": "unnamed"})
    assert s1 == s2 == 200 and r1["job"]["id"] == r2["job"]["id"], (r1, r2)
    st, r = api("POST", "/api/projects/P/concept-map/name-groups", {"which": "again"})
    assert st == 409 and "groups" in r["error"], r
    assert sum(j.kind == "group-names" for j in app.jobs.all()) == 1


def _checked(api):
    """A project with a check whose excerpts were read (the baseline reader)."""
    _project(api, docs=[_doc_text("wind energy"), _doc_text("water management")])
    st, r = api("POST", "/api/projects/P/checks", {"text": "The wind energy programme was studied in three regions."})
    assert st == 200, r
    job = api.wait(r["job"]["id"])
    assert job["state"] == "done", job
    h = api("GET", f"/api/projects/P/hypotheses/{job['result']['hyp_id']}")[1]
    part = next(p for p in h["parts"] if p["passages"])
    return part["claim_id"], part["passages"][0]["passage_id"]


def test_reading_one_excerpt_again_pressed_twice_is_one_job(served, monkeypatch, gate):
    api, app = served
    cid, pid = _checked(api)
    from enlens_claims import claimcheck

    monkeypatch.setattr(claimcheck, "reread_excerpt", lambda *a, **k: gate.wait(30) and {})
    (s1, r1), (s2, r2) = _two(api, f"/api/projects/P/claims/{cid}/reread/{pid}", {"note": "It says the opposite."})
    assert s1 == s2 == 200 and r1["job"]["id"] == r2["job"]["id"], (r1, r2)
    st, r = api("POST", f"/api/projects/P/claims/{cid}/reread/{pid}", {"note": "Another reason."})
    assert st == 409 and "again" in r["error"], r
    assert sum(j.kind == "reread" for j in app.jobs.all()) == 1


def test_reading_documents_with_the_new_reader_twice_is_one_job(served, monkeypatch, gate):
    api, app = served
    _project(api, docs=[_doc_text("wind"), _doc_text("water"), _doc_text("soil")])
    ids = [r[0] for r in _ws("P").query("SELECT doc_id FROM documents ORDER BY doc_id")]
    from enlens_claims import reread
    from enlens_claims.gui import api_documents

    monkeypatch.setattr(api_documents, "_older", lambda ws: list(ids))
    monkeypatch.setattr(reread, "move", lambda *a, **k: gate.wait(30) and {"counts": {}})
    (s1, r1), (s2, r2) = _two(api, "/api/projects/P/new-reader", {"doc_ids": ids[:2]})
    assert s1 == s2 == 200 and r1["job"]["id"] == r2["job"]["id"], (r1, r2)
    # others, even with one of them, wait their turn in the reader's lane (0.18 M6, tests/test_job_queue.py
    # `test_the_new_reader_for_several_documents_waits_instead_of_being_refused`: the later move says what was moved)
    st, r = api("POST", "/api/projects/P/new-reader", {"doc_ids": ids[1:]})
    assert st == 200 and r["job"]["id"] != r1["job"]["id"] and r["job"]["state"] == "queued", r
    monkeypatch.setattr(reread, "check", lambda ws, d: {"ok": True})
    (s1, a), (s2, b) = _two(api, f"/api/projects/P/documents/{ids[0]}/reread", {})
    assert s1 == s2 == 200 and a["job"]["id"] == b["job"]["id"], (a, b)


def test_two_presses_at_the_same_moment_start_one_job(served, monkeypatch, gate):
    """The look for a job already there and the start are one step (per project): two requests at once."""
    api, app = served
    _project(api, docs=[_doc_text("wind")])
    from enlens_claims import themes

    monkeypatch.setattr(themes, "choose_mode", lambda *a, **k: "terms")
    monkeypatch.setattr(themes, "run", lambda *a, **k: gate.wait(30) and "r1")
    out = []
    ts = [threading.Thread(target=lambda: out.append(api("POST", "/api/projects/P/themes", {"k": 5})))
          for _ in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(30)
    assert len({r["job"]["id"] for st, r in out}) == 1, out


# ---------------------------------------------------------------------------------------------------------------------
# Item 4: no endpoint passes the connector's words ("submit_grades", "more_passages") to the page
# ---------------------------------------------------------------------------------------------------------------------
TOOL_WORDS = ("submit_grades", "more_passages", "next_tasks", "start_check")


def _no_tool_words(api, answer):
    st, r = answer
    text = json.dumps(r)
    if st == 200 and "job" in r:
        text = json.dumps(api.wait(r["job"]["id"]))
    assert not any(w in text for w in TOOL_WORDS), text


def test_reading_further_while_a_round_waits_never_answers_in_the_connectors_words(served):
    api, _app = served
    cid, pid = _checked(api)
    ws = _ws("P")
    hyp = ws.scalar("SELECT hyp_id FROM user_claims WHERE claim_id=?", (cid,))
    with ws.connect() as cx:   # the round waits for its answers (a Claude chat, the queue)
        cx.execute("UPDATE tasks SET status='pending'")
    _add(api, "P", [_doc_text("wind energy in the hills")], batch="late")
    _no_tool_words(api, api("POST", f"/api/projects/P/claims/{cid}/more", {"k": 4}))
    _no_tool_words(api, api("POST", f"/api/projects/P/hypotheses/{hyp}/read-new", {}))
    _no_tool_words(api, api("POST", "/api/projects/P/read-new", {}))
    _no_tool_words(api, api("POST", f"/api/projects/P/hypotheses/{hyp}/read-unread", {}))
    _no_tool_words(api, api("POST", f"/api/projects/P/claims/{cid}/reread/{pid}", {}))


# ---------------------------------------------------------------------------------------------------------------------
# Item 5: an upload named after a device Windows keeps (CON.txt) is stored and read in, on Windows itself
# ---------------------------------------------------------------------------------------------------------------------
@pytest.mark.skipif(os.name != "nt", reason="Windows keeps CON, NUL, COM1… for devices; elsewhere they are names")
@pytest.mark.parametrize("fname", ["CON.txt", "nul.txt", "com1.txt", "Aux.md"])
def test_on_windows_an_upload_named_like_a_device_is_stored_and_added(served, fname):
    api, _app = served
    _project(api)
    st, r = api("POST", f"/api/projects/P/uploads?batch=dev&name={fname}", raw=_doc_text("devices").encode())
    assert st == 200 and r["name"] != fname and r["name"].endswith(fname), r
    st, r = api("POST", "/api/projects/P/ingest", {"batch": "dev", "ai_access": "cloud"})
    job = api.wait(r["job"]["id"])
    assert job["state"] == "done" and job["result"]["added"] == 1, job


def test_an_upload_named_like_a_device_is_stored_and_added_everywhere(served):
    """The platform-free half: the renamed file is in the batch folder and is read in."""
    api, _app = served
    _project(api)
    st, r = api("POST", "/api/projects/P/uploads?batch=dev&name=CON.txt", raw=_doc_text("devices").encode())
    assert st == 200 and r["name"] == "_CON.txt", r
    st, r = api("POST", "/api/projects/P/ingest", {"batch": "dev", "ai_access": "cloud"})
    job = api.wait(r["job"]["id"])
    assert job["state"] == "done" and job["result"]["added"] == 1, job


# ---------------------------------------------------------------------------------------------------------------------
# Item 6: the route sweep's skipped routes, each with its reason; and wrongly typed requests that would last
# ---------------------------------------------------------------------------------------------------------------------
SKIP_WHY = {
    "post_quit": "stops the app the sweep talks to",
    "post_restart": "restarts the app the sweep talks to",
    "post_update": "installs another version",
    "get_update": "asks GitHub for the latest version (network)",
    "post_ollama_install": "downloads and installs Ollama (network, installer)",
    "post_ollama_start": "starts a local model server",
    "post_pull": "downloads a model into Ollama (network)",
    "post_test": "asks a local model server to answer",
    "get_servers": "looks for local model servers on their ports",
    "get_ollama": "asks Ollama on its port",
    "get_local_status": "asks the local model server for its memory",
    "post_benchmark": "runs a model on a reference project",
    "post_repeatable": "runs a model several times",
    "get_provider_models": "asks a provider's API for its models (network)",
    "post_install_claude_code": "runs Anthropic's installer (network)",
    "post_claude_sign_in": "opens Claude Code's sign-in",
    "post_agent_install": "runs an agent CLI's installer (network)",
    "post_agent_sign_in": "opens an agent CLI's sign-in",
    "post_agent_tidy": "changes an agent CLI's own settings on this computer",
    "post_claude_code_start": "starts Claude Code",
    "post_claude_code_stop": "stops Claude Code processes",
    "post_queue_run": "starts helpers in Claude Code",
    "post_choose_folder": "opens a folder window on the screen",
    "post_notify_test": "shows a notification on the screen",
    "get_zotero": "asks Zotero on its port",
    "get_zotero_collections": "asks Zotero on its port",
    "get_zotero_works": "asks Zotero on its port",
    "post_bibliography": "brings a bibliography in from Zotero",
    "post_bibliography_files": "reads Zotero's files from their places (typed: test_zoteros_files_without_a_setting…)",
    "post_references": "follows references with the AI",
    "post_retractions_check": "asks Crossref (network)",
    "post_join_team": "joins a storage space (network)",
    "post_space_peek": "reads an invite link's storage space (network)",
    "post_space_b2": "sets up storage at Backblaze (network)",
    "post_space_r2": "sets up storage at Cloudflare (network)",
    "post_space_webdav": "sets up storage in a WebDAV drive (network)",
    "post_space_join": "joins a storage space (network)",
    "post_space_move": "moves the team to another storage space (network)",
    "post_space_drive_retry": "asks the drive again (network)",
    "put_space_drive_password": "checks the password with the drive (network)",
    "delete_project": "removes the sweep's own project (typed: test_wrongly_typed_requests_that_would_last…)",
    "post_move": "brings everything in from a move zip (typed: test_wrongly_typed_requests_that_would_last…)",
    "post_second_computer": "gives this computer a new person id (typed: test_wrongly_typed_requests_that_would_last…)",
}


def test_every_route_the_sweep_skips_says_why():
    from test_hunt1_server import SWEEP_SKIP

    assert set(SWEEP_SKIP) == set(SKIP_WHY), set(SWEEP_SKIP) ^ set(SKIP_WHY)


def test_wrongly_typed_requests_that_would_last_are_refused_in_words(served):
    """Of the skipped routes, those a wrong type could harm for good: a new person id named "['Anna']", a project
    removed on a confirmation that is a list, a move zip brought in with a mode that is not a word."""
    api, _app = served
    _project(api)
    from enlens_claims import home as h

    before = h.load_settings().get("person_id")
    for bad in (["Anna"], {"a": 1}, 7, True):
        st, r = api("POST", "/api/second-computer", {"name": bad})
        assert st == 400, (bad, r)
    assert h.load_settings().get("person_id") == before
    for bad in (["P"], {"P": 1}, 7):
        assert api("DELETE", "/api/projects/P", {"confirm": bad})[0] == 400
    assert "P" in [p["name"] for p in api("GET", "/api/state")[1]["projects"]]
    from enlens_claims.gui import api_checks

    src = Path(_ws("P").root) / "m.zip"
    src.write_bytes(b"PK\x05\x06" + b"\0" * 18)
    token = api_checks._MOVES._keep(src)
    for bad in (["both"], {"m": 1}, 7):
        st, r = api("POST", "/api/move", {"token": token, "mode": bad})
        assert st == 400, (bad, r)


# ---------------------------------------------------------------------------------------------------------------------
# Item 8: the rest of notes/server.md ("Not proven")
# ---------------------------------------------------------------------------------------------------------------------
def _barrier_on_look(monkeypatch, app, n=2):
    """Two presses that both look for a running job before either starts one (the window between the look and the
    start, held open)."""
    real = app.jobs.all
    barrier = threading.Barrier(n, timeout=5)
    calls = {"n": 0}
    lock = threading.Lock()

    def look():
        out = real()
        with lock:
            calls["n"] += 1
            mine = calls["n"] <= n
        if mine:
            try:
                barrier.wait()
            except threading.BrokenBarrierError:
                pass
        return out

    monkeypatch.setattr(app.jobs, "all", look)


def test_installing_claude_code_from_two_tabs_at_once_is_one_install(served, monkeypatch, gate):
    api, app = served
    from enlens_claims import claude_setup, home as h

    monkeypatch.setattr(h, "local_only", lambda: False)
    monkeypatch.setattr(claude_setup, "find_claude", lambda *a, **k: None)
    runs = []
    monkeypatch.setattr(claude_setup, "install_claude_code", lambda: runs.append(1) or gate.wait(30) and {"ok": True})
    _barrier_on_look(monkeypatch, app)
    out = []
    ts = [threading.Thread(target=lambda: out.append(api("POST", "/api/claude-setup/claude-code", {})))
          for _ in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(20)
    assert [st for st, _r in out] == [200, 200], out
    assert len({r["job"]["id"] for _st, r in out}) == 1, out


def test_downloading_models_from_two_tabs_at_once_is_one_download(served, monkeypatch, gate):
    api, app = served
    from enlens_claims import llm

    monkeypatch.setattr(llm.OllamaBackend, "pull", lambda self, m, on_progress=None, should_stop=None:
                        gate.wait(30) and "stopped")
    _barrier_on_look(monkeypatch, app)
    out = []
    ts = [threading.Thread(target=lambda: out.append(app.pull_models(["qwen3:8b"], "http://127.0.0.1:9")))
          for _ in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(20)
    assert len({j.id for j in out}) == 1, out


def test_a_move_zip_answered_twice_at_once_is_brought_in_once(served, monkeypatch):
    api, _app = served
    _project(api)
    from enlens_claims import bundle
    from enlens_claims.gui import api_checks

    src = Path(_ws("P").root) / "m.zip"
    src.write_bytes(b"zip")
    token = api_checks._MOVES._keep(src)
    calls = []

    def slow(path, mode, **kw):
        calls.append(mode)
        time.sleep(1.0)
        return {"current": None, "projects": []}

    monkeypatch.setattr(bundle, "import_all", slow)
    out = []
    ts = [threading.Thread(target=lambda: out.append(api("POST", "/api/move", {"token": token, "mode": "both"})))
          for _ in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(20)
    assert len(calls) == 1, (calls, out)
    assert sorted(st for st, _r in out) in ([200, 409], [200, 410]), out


def test_a_hypothesis_removed_while_its_check_waits_for_the_queue_says_so_in_words(served, monkeypatch):
    """The follow loop ended, `hypothesis_result` raised KeyError and the job's error was the bare hypothesis id."""
    api, app = served
    _project(api, docs=[_doc_text("wind energy")])
    from enlens_claims import claimcheck

    def removed(job, ws, hyp_ids, tracker, poll=None):
        for hid in hyp_ids:
            claimcheck.delete_hypothesis(ws, hid)

    monkeypatch.setattr(app, "queue_mode", lambda: True)
    monkeypatch.setattr(app, "_follow_queued", removed)
    st, r = api("POST", "/api/projects/P/checks", {"text": "The wind energy programme was studied in three regions."})
    assert st == 200, r
    job = api.wait(r["job"]["id"])
    assert job["state"] == "error"
    assert " " in job["error"] and "removed" in job["error"], job["error"]


def _disposition_filename(header: str) -> str:
    """The `filename="…"` part as a browser reads it: a quoted string, where a backslash escapes the next character."""
    import re

    m = re.search(r'filename="((?:[^"\\]|\\.)*)"(;|$)', header)
    assert m, header
    return re.sub(r"\\(.)", r"\1", m.group(1))


def test_an_exported_hypothesis_of_an_odd_id_gets_a_whole_file_name(served, monkeypatch):
    """`get_hypothesis_export` wrote `filename="hypothesis_{hyp_id}.csv"` itself: an id with a quote (from a colleague's
    database) cut the name off."""
    api, _app = served
    _project(api)
    from enlens_claims import claimcheck

    monkeypatch.setattr(claimcheck, "hypothesis_result", lambda ws, hid, thr=None: {"hyp_id": hid, "text": "x"})
    monkeypatch.setattr(claimcheck, "hypothesis_rows", lambda res: [])
    import urllib.request

    req = urllib.request.Request(api.base + "/api/projects/P/hypotheses/h%22x/export.csv",
                                 headers={"X-Enlens-Token": api.token})
    with urllib.request.urlopen(req, timeout=30) as r:
        header = r.headers["Content-Disposition"]
    assert _disposition_filename(header).endswith(".csv"), header


@pytest.mark.parametrize("name", ["notes\\", "a\\b.txt", 'quote".txt'])
def test_a_download_name_with_a_backslash_keeps_its_closing_quote(name):
    from enlens_claims.gui.api_common import _disposition

    h = _disposition(name)
    got = _disposition_filename(h)
    assert "\\" not in got and '"' not in got, h
    assert "filename*=UTF-8''" in h


def _raw(api, data: bytes, wait=5.0) -> bytes:
    from urllib.parse import urlparse

    u = urlparse(api.base)
    s = socket.create_connection((u.hostname, u.port), timeout=wait)
    try:
        s.sendall(data)
        out = b""
        while True:
            try:
                chunk = s.recv(65536)
            except socket.timeout:
                break
            if not chunk:
                break
            out += chunk
        return out
    finally:
        s.close()


def _head(api, method, path, extra):
    from urllib.parse import urlparse

    u = urlparse(api.base)
    return (f"{method} {path} HTTP/1.1\r\nHost: {u.hostname}:{u.port}\r\nX-Enlens-Token: {api.token}\r\n"
            + "".join(f"{k}: {v}\r\n" for k, v in extra.items()) + "\r\n").encode()


def test_a_chunked_upload_is_refused_not_stored_empty(served):
    """Without Content-Length (Transfer-Encoding: chunked) the body was not read: the upload was stored as 0 bytes
    with 200, and the chunks were read as the next request."""
    api, _app = served
    _project(api)
    body = b"5\r\nhello\r\n0\r\n\r\n"
    out = _raw(api, _head(api, "POST", "/api/projects/P/uploads?batch=ch&name=a.txt",
                          {"Transfer-Encoding": "chunked"}) + body)
    first = out.split(b"\r\n", 1)[0]
    assert first.startswith(b"HTTP/1.1 411"), out[:300]
    assert out.count(b"HTTP/1.1 ") == 1, out   # the chunks were not taken for a second request
    folder = Path(_ws("P").root) / "uploads" / "ch"
    assert not folder.exists() or not any(folder.iterdir())


def test_a_body_shorter_than_its_length_does_not_hold_the_connection_for_ever(served, monkeypatch):
    api, _app = served
    _project(api)
    from enlens_claims.gui import server

    monkeypatch.setattr(server.Handler, "timeout", 1)
    t0 = time.time()
    out = _raw(api, _head(api, "POST", "/api/projects/P/notes", {"Content-Length": "100",
                                                                  "Content-Type": "application/json"}) + b'{"a": ',
               wait=10)
    assert time.time() - t0 < 8, "the server waited for the rest of the body"
    assert b"500" not in out.split(b"\r\n", 1)[0], out[:300]
