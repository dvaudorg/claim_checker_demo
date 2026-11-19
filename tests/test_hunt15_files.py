"""Hunt phase 1.5 (19 November 2026), area `files`: the project on disk, the data folder and the bibliography. Every
note, "not proven" and open point that phases 0 and 1 left here. Each test states what ENLENS should do; the ledger
(`.claude/audits/2026-11-19-phase1.5/ledger/files.md`) says which failed before a fix and which passed on the code as
it was. The test marked for Windows runs on the Windows leg of CI only; its platform-free twin runs everywhere."""
from __future__ import annotations

import contextlib
import errno
import json
import os
import pathlib
import shutil
import sqlite3
import threading
import time
import zipfile

import pytest

from enlens_claims import bibliography, bundle, sharing, store
from enlens_claims import home as ehome
from enlens_claims.store import Workspace
from test_app import api, home  # noqa: F401  (fixtures)
from test_private_until_shared import _check
from test_shared_projects import CLAIM


def _meta(db: pathlib.Path) -> dict:
    cx = sqlite3.connect(db)
    try:
        return dict(cx.execute("SELECT key, value FROM meta").fetchall())
    finally:
        cx.close()


def _set_meta(db: pathlib.Path, key: str, value: str) -> None:
    cx = sqlite3.connect(db)
    try:
        with cx:
            cx.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, value))
    finally:
        cx.close()


# ---------------------------------------------------------------------------------------------
# 2. old data (FILES-1, FILES-2): a project whose first opening by 0.17 to 0.20.3 was cut off. The data cannot tell it
# apart from a project these versions opened to the end: the same rows stand for both, and the repair would act on both
# ---------------------------------------------------------------------------------------------
def test_old_data_a_project_exchanged_since_with_nothing_shared_by_you_stays_private(loaded):
    """What an interrupted 0.17 upgrade left (a table of shares with no row, no note that a step is due, a colleague
    known) is also what a project of this version looks like when a colleague's work came in and you shared nothing:
    the repair would mark your private check shared and send it at the next round."""
    hid = _check(loaded, CLAIM)
    with loaded.connect() as cx:  # a colleague's file came in; it held no item of theirs to mark
        cx.execute("INSERT INTO sync_log(at, person_id, report_json) VALUES (?, 'p0123456789ab', '{}')", (store.now(),))
        cx.execute("INSERT OR REPLACE INTO people(person_id, name) VALUES ('p0123456789ab', 'Ben')")
    cx = loaded._conn()
    assert sharing.exchanged(cx) and not loaded.scalar("SELECT COUNT(*) FROM shares")
    assert not loaded.scalar("SELECT COUNT(*) FROM meta WHERE key=?", (store.SHARES_UPGRADE_DUE,))
    loaded.close_all()
    ws = Workspace.open(loaded.root)
    assert sharing.state(ws._conn(), "check", hid)["state"] == "private"
    assert not ws.scalar("SELECT COUNT(*) FROM shares")
    ws.close_all()


def test_old_data_a_colleagues_answers_from_before_011_invent_no_ledger_and_no_default(loaded):
    """What an interrupted pre-0.11 upgrade left (the column ai_access, no `ai_access_upgraded`, an answer on Claude's
    route with no record of what was sent) is also what every project made since 0.11 looks like after a colleague's
    answers from an older ENLENS came in (a merge brings tasks without their setting). Running the upgrade there
    would write "Claude may read every document" as a default nobody chose, and records of reads this copy never
    made."""
    pid = loaded.query("SELECT passage_id FROM passages ORDER BY passage_id LIMIT 1")[0][0]
    cfg_before = loaded.config_path.read_bytes()
    with loaded.connect() as cx:
        cx.execute("INSERT INTO tasks(task_id, kind, model, payload_json, status, access) VALUES ('check:theirs', "
                   "'check', 'opus', ?, 'done', NULL)", (json.dumps({"passages": [{"passage_id": pid}]}),))
        cx.execute("INSERT INTO results(task_id, attempt, kind, model, raw_json, valid, received_at, route) VALUES "
                   "('check:theirs', 1, 'check', 'opus', '{}', 1, '2025-01-01T00:00:00+00:00', 'Claude Code')")
        cx.execute("DELETE FROM meta WHERE key IN ('ai_access_upgraded', 'ai_sent_since')")
    loaded.close_all()
    ws = Workspace.open(loaded.root)
    assert not ws.scalar("SELECT COUNT(*) FROM ai_sent WHERE task_id='check:theirs'")
    assert ws.config_path.read_bytes() == cfg_before
    assert ws.meta("ai_access_upgraded") is None
    ws.close_all()


# ---------------------------------------------------------------------------------------------
# 3. a project saved by a newer ENLENS: refused in words, before anything is written
# ---------------------------------------------------------------------------------------------
NEWER = "newer ENLENS"


def _from_the_future(ws: Workspace) -> tuple[bytes, dict, list]:
    """The project as a later ENLENS leaves it when it changes something an older one would read wrongly."""
    ws.close_all()
    _set_meta(ws.db_path, store.PROJECT_NEEDS_KEY, str(store.PROJECT_LEVEL + 1))
    cx = sqlite3.connect(ws.db_path)
    try:
        layout = cx.execute("SELECT name, sql FROM sqlite_master ORDER BY name").fetchall()
        cx.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        cx.close()
    return ws.config_path.read_bytes(), _meta(ws.db_path), layout


def test_a_project_saved_by_a_newer_enlens_is_refused_in_words_and_left_as_it_is(ws):
    cfg, meta, layout = _from_the_future(ws)
    with pytest.raises(ValueError) as e:
        Workspace.open(ws.root)
    assert NEWER in str(e.value) and "Update ENLENS" in str(e.value) and "Nothing was changed" in str(e.value)
    assert ws.config_path.read_bytes() == cfg and _meta(ws.db_path) == meta
    cx = sqlite3.connect(ws.db_path)
    try:
        assert cx.execute("SELECT name, sql FROM sqlite_master ORDER BY name").fetchall() == layout
    finally:
        cx.close()


def test_this_version_records_the_level_its_projects_need_and_never_lowers_one(ws):
    assert ws.meta(store.PROJECT_NEEDS_KEY) == store.PROJECT_LEVEL
    ws.close_all()
    _set_meta(ws.db_path, store.PROJECT_NEEDS_KEY, str(store.PROJECT_LEVEL))
    again = Workspace.open(ws.root)
    assert again.meta(store.PROJECT_NEEDS_KEY) == store.PROJECT_LEVEL
    again.close_all()


def test_a_folder_saved_by_a_newer_enlens_is_not_linked_or_cleaned(tmp_path):
    other = Workspace.create(tmp_path / "Fieldwork")
    cfg, meta, _layout = _from_the_future(other)
    with pytest.raises(ValueError) as e:
        ehome.link_existing(str(other.root))
    assert NEWER in str(e.value)
    assert other.config_path.read_bytes() == cfg and _meta(other.db_path) == meta
    assert "Fieldwork" not in ehome.list_projects()


def test_the_projects_page_lists_a_project_of_a_newer_enlens_with_the_words(api):  # noqa: F811
    made = Workspace.create(ehome.home() / "projects" / "From the future")
    _from_the_future(made)
    st, s = api("GET", "/api/state")
    assert st == 200
    p = next(p for p in s["projects"] if p["name"] == "From the future")
    assert p["ok"] is False and NEWER in p["problem"]


# ---------------------------------------------------------------------------------------------
# 1. a Zotero library's id and key checked with `$`, which lets a final newline through (phase 0, as CQ-3)
# ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize("call", [
    lambda: bibliography.zotero_works("user", collection="ABCD1234\n"),
    lambda: bibliography.zotero_works("group-12\n"),
    lambda: bibliography.pull_zotero("user", collection="ABCD1234\n"),
    lambda: bibliography.pull_zotero("user", items=["ABCD1234\n"]),
])
def test_a_zotero_id_with_a_final_newline_is_refused_before_zotero_is_asked(monkeypatch, call):
    asked = []
    monkeypatch.setattr(bibliography, "_get", lambda *a, **kw: asked.append(a) or [])
    with pytest.raises(ValueError):
        call()
    assert not asked


def test_a_zotero_key_with_a_final_newline_is_no_zotero_link():
    """The key read from Zotero's CSV export names the work's Zotero link only when it is a Zotero key."""
    assert not bibliography.KEY_RE.match("ABCD1234\n") and not bibliography.LIBRARY_RE.match("user\n")


# ---------------------------------------------------------------------------------------------
# 4. a project codebook uploaded again: written whole
# ---------------------------------------------------------------------------------------------
def _cut_off(monkeypatch, name):
    real = pathlib.Path.write_text

    def cut(self, data, *a, **kw):
        if self.name == name:
            open(self, "w").close()  # opened for writing (emptied), then the disk is full
            raise OSError(errno.ENOSPC, "No space left on device")
        return real(self, data, *a, **kw)

    monkeypatch.setattr(pathlib.Path, "write_text", cut)
    return real


CODEBOOK = "code,label,description\nA1,Water use,How much water\nA2,Land use,How much land\n"


def test_a_codebook_uploaded_again_on_a_full_disk_keeps_the_codebook_it_had(ws, monkeypatch):
    from enlens_claims import frameworks

    frameworks.save(ws, "habits", CODEBOOK, title="Habits")
    real = _cut_off(monkeypatch, "habits.csv")
    with contextlib.suppress(OSError):
        frameworks.save(ws, "habits", CODEBOOK + "A3,Energy,How much energy\n", title="Habits")
    monkeypatch.setattr(pathlib.Path, "write_text", real)
    fw = frameworks.get("habits", ws)
    assert list(fw.codes)[:2] == ["A1", "A2"]


def test_a_codebooks_title_saved_on_a_full_disk_keeps_its_side_file(ws, monkeypatch):
    from enlens_claims import frameworks

    frameworks.save(ws, "habits", CODEBOOK, title="Habits")
    real = _cut_off(monkeypatch, "habits.json")
    with contextlib.suppress(OSError):
        frameworks.save(ws, "habits", CODEBOOK, title="Habits at home")
    monkeypatch.setattr(pathlib.Path, "write_text", real)
    side = ws.root / "frameworks" / "habits.json"
    assert json.loads(side.read_text(encoding="utf-8"))["title"] in ("Habits", "Habits at home")


# ---------------------------------------------------------------------------------------------
# 5. a damaged quicklook.json or benchmarks.json, set aside: nothing a person relies on is said wrongly or lost
# ---------------------------------------------------------------------------------------------
def test_a_damaged_list_of_quick_looks_keeps_every_quick_look_and_promises_no_trash(api):  # noqa: F811
    """The list only says which quick looks go to the trash after a week. Set aside, every quick look on it stays a
    project, listed as one, and no page says it will be moved: what the pages show is still true, and nothing waits
    for the person to do (the owner's rule: only a note that needs the person shows by itself)."""
    ql = ehome.create_quicklook("Interview 6.pdf")
    name = ql.root.name
    ql.close_all()
    p = ehome.home() / "quicklook.json"
    p.write_text(p.read_text(encoding="utf-8")[:-3], encoding="utf-8")
    ehome.mark_temporary("Another look")  # the next change sets the damaged list aside
    assert p.with_name("quicklook.json.damaged").exists()
    ehome.cleanup_quicklooks(now_=time.time() + 8 * 86400)
    st, s = api("GET", "/api/state")
    row = next(r for r in s["projects"] if r["name"] == name)
    assert row["ok"] and row["temporary"] is None


def test_a_damaged_file_of_model_speeds_only_leaves_the_estimates_without_them():
    """benchmarks.json holds the model test's median seconds per task, used only to estimate how long a long run
    takes; set aside, the estimate falls back as for a model never tested, and the next test writes it again."""
    ehome.record_benchmark("model-a", {"check": {"seconds_median": 2.0}})
    p = ehome.home() / "benchmarks.json"
    p.write_text(p.read_text(encoding="utf-8")[:-3], encoding="utf-8")
    assert ehome.benchmark_medians() == {}
    ehome.record_benchmark("model-a", {"check": {"seconds_median": 2.5}})
    assert ehome.benchmark_medians() == {"model-a": {"check": 2.5}}


# ---------------------------------------------------------------------------------------------
# 6. a colleague's codebook copy: a side file that does not parse is not counted as empty
# ---------------------------------------------------------------------------------------------
def test_a_damaged_side_file_of_a_colleagues_codebook_copy_is_not_written_over(ws):
    from types import SimpleNamespace

    from enlens_claims.sync.codebook_merge import CodebookRules

    side = ws.root / "frameworks" / "habits_ann.json"
    side.parent.mkdir(exist_ok=True)
    damaged = '{"title": "Habits", "ids": {"a": "u1"}, "groups": [{"name": "G"'
    side.write_text(damaged, encoding="utf-8")
    with contextlib.suppress(ValueError):
        CodebookRules._mark_codebook_title(SimpleNamespace(ws=ws, sender={"name": "Ann"}), "habits_ann", "Habits")
    assert side.read_text(encoding="utf-8") == damaged


# ---------------------------------------------------------------------------------------------
# 7. an evaluation copy claims its name, as every other new project does
# ---------------------------------------------------------------------------------------------
def test_an_evaluation_copy_named_as_a_vanished_quick_look_is_not_sent_to_the_trash(ws):
    from enlens_claims import evaluation

    name = evaluation.eval_name(ws, "label", "opus")
    ql = ehome.create_quicklook(f"{name}.pdf")
    assert ql.root.name == name
    ql.close_all()
    shutil.rmtree(ql.root)  # gone outside ENLENS
    copy = evaluation._copy(ws, name)
    copy.close_all()
    ehome.cleanup_quicklooks(now_=time.time() + 8 * 86400)
    assert name in ehome.list_projects()


def test_an_evaluation_copy_is_not_made_under_the_name_of_a_linked_project(ws, tmp_path):
    from enlens_claims import evaluation

    name = evaluation.eval_name(ws, "label", "opus")
    other = Workspace.create(tmp_path / "elsewhere")
    other.close_all()
    ehome.link_existing(str(other.root), name=name)
    with pytest.raises(ValueError):
        evaluation._copy(ws, name)
    assert ehome.project_path(name) == other.root.resolve()


# ---------------------------------------------------------------------------------------------
# 8. a damaged config.json (the owner: refused, never written over): the Projects page shows it with what to do
# ---------------------------------------------------------------------------------------------
def test_the_projects_page_lists_a_project_with_a_damaged_settings_file_and_says_what_to_do(api):  # noqa: F811
    assert api("POST", "/api/projects", {"name": "Fieldwork"})[0] == 200
    cfg = ehome.project_path("Fieldwork") / "config.json"
    cfg.write_text('{"thresholds": {"support_confidence": 0.7}, "ai_acc', encoding="utf-8")
    st, s = api("GET", "/api/state")
    assert st == 200
    p = next(p for p in s["projects"] if p["name"] == "Fieldwork")
    assert p["ok"] is False
    assert "config.json" in p["problem"] and "backup" in p["problem"] and "move config.json out" in p["problem"]
    st, r = api("GET", "/api/projects/Fieldwork/documents")
    assert st == 400 and "config.json" in r["error"]
    assert cfg.read_text(encoding="utf-8").endswith('"ai_acc')  # never written over


# ---------------------------------------------------------------------------------------------
# 9. a project replaced while open, then removed (NEEDS WINDOWS in notes/files.md)
# ---------------------------------------------------------------------------------------------
def _use_in_a_thread(name: str) -> None:
    """A request thread reads the project and ends, leaving its connection (as the app's threads do)."""
    t = threading.Thread(target=lambda: ehome.open_project(name).scalar("SELECT COUNT(*) FROM documents"))
    t.start()
    t.join(30)


def _fds_on(files: list[pathlib.Path]) -> set[int]:
    """The file descriptors of this process open on these files (POSIX: /proc/self/fd on Linux, /dev/fd on macOS)."""
    ids = set()
    for f in files:
        with contextlib.suppress(OSError):
            st = os.stat(f)
            ids.add((st.st_dev, st.st_ino))
    where = "/proc/self/fd" if os.path.isdir("/proc/self/fd") else "/dev/fd"
    out = set()
    for name in os.listdir(where):
        with contextlib.suppress(OSError, ValueError):
            st = os.fstat(int(name))
            if (st.st_dev, st.st_ino) in ids:
                out.add(int(name))
    return out


@pytest.mark.skipif(os.name == "nt", reason="Windows refuses to replace a database file that is open: the test below")
def test_a_project_whose_database_was_replaced_closes_the_connections_to_the_old_one():
    """The platform-free half: `open_project` keeps one project per folder and its database's file id. When the
    database is another file (the folder replaced), the one kept is dropped: its connections, in every thread, are
    closed then, not left to the garbage collector (on Windows an open database keeps its folder from moving).

    (After CI, Linux on Python 3.10: the rule is asserted on the files themselves, not on `Workspace._all`. That set
    holds weak references; there the connection of a thread that has ended was already freed, and so closed, when the
    thread ended, while newer Pythons keep it until the garbage collector runs. Either way nothing may stay open.)"""
    ws = ehome.create_project("Fieldwork")
    ws.close_all()
    _use_in_a_thread("Fieldwork")   # a request thread that has ended (its connection freed or not, by the Python)
    old = ehome.open_project("Fieldwork")
    old.scalar("SELECT COUNT(*) FROM documents")  # and one still in use by this thread, on every Python
    db = old.db_path
    files = [db, db.with_name(db.name + "-wal"), db.with_name(db.name + "-shm")]
    held = _fds_on(files)
    assert held  # (the setting holds: the old database is open)
    old_copy = db.with_name("copy.sqlite")
    shutil.copyfile(db, old_copy)
    for f in files:
        f.unlink(missing_ok=True)
    os.replace(old_copy, db)  # another file in its place
    new = ehome.open_project("Fieldwork")
    assert new is not old
    # every descriptor that was on the old files is closed, or (its number taken again) on a file still linked: an
    # open descriptor on one of the old, now unlinked, files has no link left
    for fd in held:
        with contextlib.suppress(OSError):
            assert os.fstat(fd).st_nlink > 0, "a connection to the replaced database is still open"
    new.close_all()


@pytest.mark.skipif(os.name != "nt", reason="Windows keeps a folder whose database is open from moving")
def test_on_windows_a_project_brought_in_again_over_its_name_can_be_removed(api, tmp_path):  # noqa: F811
    """notes/files.md, NEEDS WINDOWS: open a project in the app, bring in a project zip that replaces it, then remove
    the project. Every connection to the folder must be closed by then, or Windows says the folder is in use."""
    assert api("POST", "/api/projects", {"name": "Fieldwork"})[0] == 200
    _use_in_a_thread("Fieldwork")
    st, z = api("GET", f"/api/projects/Fieldwork/export.zip?token={api.token}", token=False)
    assert st == 200 and z[:2] == b"PK"
    assert api("DELETE", "/api/projects/Fieldwork", {"confirm": "Fieldwork"})[0] == 200
    st, r = api("POST", "/api/projects/import?name=Fieldwork", raw=z, headers={"Content-Type": "application/zip"})
    assert st == 200, r
    _use_in_a_thread("Fieldwork")
    assert api("GET", "/api/state")[0] == 200
    st, r = api("DELETE", "/api/projects/Fieldwork", {"confirm": "Fieldwork"})
    assert st == 200, r
    assert not (ehome.home() / "projects" / "Fieldwork").exists()


def test_a_project_brought_in_again_over_its_name_can_be_removed(api, tmp_path):  # noqa: F811
    """The same steps on every platform: removed, brought in under its name, removed again."""
    assert api("POST", "/api/projects", {"name": "Fieldwork"})[0] == 200
    _use_in_a_thread("Fieldwork")
    st, z = api("GET", f"/api/projects/Fieldwork/export.zip?token={api.token}", token=False)
    assert st == 200
    assert api("DELETE", "/api/projects/Fieldwork", {"confirm": "Fieldwork"})[0] == 200
    assert api("POST", "/api/projects/import?name=Fieldwork", raw=z, headers={"Content-Type": "application/zip"})[0] == 200
    _use_in_a_thread("Fieldwork")
    assert api("DELETE", "/api/projects/Fieldwork", {"confirm": "Fieldwork"})[0] == 200
    assert "Fieldwork" not in ehome.list_projects()


# ---------------------------------------------------------------------------------------------
# 10. the notes of a one-time step still due stay with the copy that has to do it
# ---------------------------------------------------------------------------------------------
DUE = (store.SHARES_UPGRADE_DUE, store.AI_ACCESS_UPGRADE_DUE)


@pytest.mark.parametrize("scope", ["all", "shared"])
def test_a_project_zip_carries_no_note_of_a_step_still_due(tmp_path, scope):
    ws = ehome.create_project("Fieldwork")
    ws.close_all()
    ehome.close_project(ws.root)
    for k in DUE:  # an opening cut off before the steps were done
        _set_meta(ws.db_path, k, "1")
    opened = ehome.open_project("Fieldwork")  # the app opens the project to make its zip: the steps are done then
    out = tmp_path / f"{scope}.zip"
    bundle.export_project(opened, out, scope=scope)
    with zipfile.ZipFile(out) as zf:
        (tmp_path / "x").mkdir()
        zf.extract("enlens.sqlite", tmp_path / "x")
    assert not set(DUE) & set(_meta(tmp_path / "x" / "enlens.sqlite"))


def test_a_merge_takes_no_note_of_a_step_still_due_from_a_colleagues_file(loaded, tmp_path):
    """A colleague's database that still holds such a note (a folder zipped by hand while its opening was cut off)
    does its step in the copy the merge reads, not in this project: nothing of it lands here."""
    from enlens_claims import sync

    hid = _check(loaded, CLAIM)
    out = tmp_path / "theirs.zip"
    bundle.export_project(loaded, out, scope="all")
    unpacked = tmp_path / "theirs"
    with zipfile.ZipFile(out) as zf:
        zf.extractall(unpacked)
    for k in DUE:
        _set_meta(unpacked / "enlens.sqlite", k, "1")
    hand = tmp_path / "hand.zip"
    with zipfile.ZipFile(hand, "w") as zf:
        for f in unpacked.rglob("*"):
            if f.is_file():
                zf.write(f, f.relative_to(unpacked).as_posix())
    mine = bundle.import_project(out, tmp_path / "mine")
    before = dict(mine.query("SELECT kind || ':' || key, state FROM shares"))
    with contextlib.suppress(ValueError):  # (a file of the very same copy may be refused in words: either is fine)
        sync.bring_in(mine, hand, anyway=True)
    assert not set(DUE) & set(_meta(mine.db_path))
    after = dict(mine.query("SELECT kind || ':' || key, state FROM shares"))
    assert after.get(f"check:{hid}") == before.get(f"check:{hid}")
    mine.close_all()


def test_one_project_of_a_newer_enlens_does_not_stop_the_connector_for_the_others():
    """The sibling of phase 1's damaged settings file (`mcp_server._projects`): a project refused as too new is
    passed over, named as one that could not be opened."""
    from enlens_claims import mcp_server

    ehome.create_project("Sound").close_all()
    made = Workspace.create(ehome.home() / "projects" / "From the future")
    _from_the_future(made)
    seen, unreadable = [], []
    assert mcp_server._projects(lambda name, ws: seen.append(name) and None, unreadable) is None
    assert "Sound" in seen and unreadable == ["From the future"]


# ---------------------------------------------------------------------------------------------
# review notes (reviews/reading.md): every opening follows the codebooks kept with all projects
# ---------------------------------------------------------------------------------------------
def test_opening_a_project_writes_nothing_when_no_codebook_changed_and_never_fails_for_one(monkeypatch):
    """`home.open_project` runs `codebooks.follow` at every opening: with nothing new it takes no write lock (a
    request would otherwise wait behind a sync round's long transaction), and a codebook that fails never stops the
    opening."""
    from enlens_claims import codebooks

    ws = ehome.create_project("Fieldwork")
    ws.close_all()
    ehome.close_project(ws.root)
    ehome.open_project("Fieldwork")
    watcher = sqlite3.connect(ws.db_path)
    try:
        before = watcher.execute("PRAGMA data_version").fetchone()[0]
        held = sqlite3.connect(ws.db_path, timeout=0)
        held.execute("BEGIN IMMEDIATE")  # another program holds the write lock all the while
        try:
            ehome.open_project("Fieldwork")
        finally:
            held.rollback()
            held.close()
        assert watcher.execute("PRAGMA data_version").fetchone()[0] == before

        def broken(_ws):
            raise RuntimeError("a codebook that cannot be followed")

        monkeypatch.setattr(codebooks, "follow", broken)
        assert ehome.open_project("Fieldwork") is not None
    finally:
        watcher.close()


# ---------------------------------------------------------------------------------------------
# notes/files.md, "Not proven"
# ---------------------------------------------------------------------------------------------
def test_two_programs_changing_a_projects_settings_at_once_both_keep_their_change(ws, monkeypatch):
    """Not proven 2: the app and the connector (or the command line) each read config.json, change it and write it
    back; with only a lock inside one program, the second write put back what it had read and the first change was
    gone. Another program changes it while this one is between its read and its write."""
    import subprocess
    import sys

    src = pathlib.Path(store.__file__).resolve().parents[1]
    env = {**os.environ, "PYTHONPATH": str(src)}
    script = ("import sys\nfrom enlens_claims import store\nprint('ready', flush=True)\n"
              "store.change_config(sys.argv[1], {'from_the_other_program': 1})\n")
    real = store.write_config
    other: list = []

    def slow(path, cfg):
        if not other:
            p = subprocess.Popen([sys.executable, "-c", script, str(path)], env=env, stdout=subprocess.PIPE, text=True)
            other.append(p)
            assert p.stdout.readline().strip() == "ready"
            with contextlib.suppress(subprocess.TimeoutExpired):
                p.wait(3)  # it waits for this program's change when the change is held across programs
        real(path, cfg)

    monkeypatch.setattr(store, "write_config", slow)
    store.change_config(ws.config_path, {"from_this_program": 1})
    assert other[0].wait(60) == 0
    cfg = json.loads(ws.config_path.read_text(encoding="utf-8"))
    assert cfg.get("from_this_program") == 1 and cfg.get("from_the_other_program") == 1


def test_a_reply_titled_after_the_work_is_not_taken_for_the_work(monkeypatch):
    """Not proven 4: Crossref's record of "Reply to: <the work's title>" by the same authors passed `accepts` for a
    long title (90+ characters), so the work and its reply were two matches and the work was checked by neither."""
    from enlens_claims import retractions

    title = ("Water use of electrolytic hydrogen production in arid regions: a life cycle assessment of three plants")
    work = {"title": title, "family": "Smith", "year": 2020}

    def item(doi, t):
        return {"DOI": doi, "title": [t], "author": [{"family": "Smith", "given": "Jane"}],
                "issued": {"date-parts": [[2020]]}}

    found = {"message": {"items": [item("10.1/work", title), item("10.1/reply", f"Reply to: {title}"),
                                   item("10.1/comment", f"Comment on “{title}”")]}}
    monkeypatch.setattr(retractions, "_get", lambda url: found)
    ok, _n = retractions.find_by_title("https://api.crossref.example", work)
    assert [c["doi"] for c in ok] == ["10.1/work"]
    # a work whose own title starts so is still found
    own = {"title": "Response to drought in smallholder farming", "family": "Smith", "year": 2020}
    found2 = {"message": {"items": [item("10.1/own", own["title"])]}}
    monkeypatch.setattr(retractions, "_get", lambda url: found2)
    assert [c["doi"] for c in retractions.find_by_title("https://api.crossref.example", own)[0]] == ["10.1/own"]


def test_a_decision_follows_a_work_whose_key_changed_only_to_that_work(loaded):
    """Not proven 5: a person's decision about a work whose key changed (another source for the same library) followed
    it by title and year alone; two works of one title and year (an annual report of two bodies) both took the
    decisions of either, so a document was confirmed as the other body's report."""
    from enlens_claims import bibliography as bib

    docs = [r[0] for r in loaded.query("SELECT doc_id FROM documents ORDER BY doc_id")][:2]

    def bibtex(k1, k2):
        return (f"@techreport{{{k1},\n  title = {{Annual report}},\n  author = {{{{Water Board North}}}},\n"
                f"  year = {{2023}}\n}}\n@techreport{{{k2},\n  title = {{Annual report}},\n"
                f"  author = {{{{Water Board South}}}},\n  year = {{2023}}\n}}\n")

    _f, first = bib.parse_file("a.bib", bibtex("north2023", "south2023"))
    bib.save(loaded, first, {"kind": "file", "name": "a.bib"})
    north, south = (w["key"] for w in first)
    with loaded.connect() as cx:
        cx.execute("DELETE FROM bib_links")
        cx.executemany("INSERT INTO bib_links(item_key, doc_id, status, method, score, evidence_json, decided_at) "
                       "VALUES (?,?,'confirmed','person',1,'{}',?)", [(north, docs[0], store.now()),
                                                                      (south, docs[1], store.now())])
    _f, second = bib.parse_file("b.bib", bibtex("WBN-2023", "WBS-2023"))
    assert {w["key"] for w in second}.isdisjoint({north, south})
    bib.save(loaded, second, {"kind": "file", "name": "b.bib"})
    by_key = {w["key"]: w for w in second}
    got = {(r[0], r[1]) for r in loaded.query("SELECT item_key, doc_id FROM bib_links WHERE status='confirmed'")}
    for key, doc in got:
        body = by_key[key]["creators"][0].get("name") or by_key[key]["creators"][0].get("last")
        assert ("North" in body) == (doc == docs[0]), (body, doc)


def test_a_highlighted_pdfs_note_says_a_non_scientific_documents_judgement_is_not_counted(loaded):
    """Not proven 6: the note written beside a judgement in the highlighted file said nothing for a document marked
    Non-scientific, whose judgements never count in the answer (unless the hypothesis counts them)."""
    from enlens_claims import annotate, docrole

    _check(loaded, CLAIM)
    doc = loaded.scalar("SELECT v.doc_id FROM verifications v WHERE v.subject_kind='user_claim' AND v.quote IS NOT "
                        "NULL AND v.verdict IN ('supports', 'partially_supports', 'contradicts') LIMIT 1")
    assert doc
    docrole.set_nonscientific(loaded, doc, True)
    marks = annotate.collect(loaded, doc, threshold=0.0)
    assert marks and all("not counted" in m.note and "Non-scientific" in m.note for m in marks)


def test_a_label_of_a_kind_this_version_does_not_know_does_not_stop_the_flexiconc_file(loaded, tmp_path):
    """Not proven 7: `_RANK[r["source"]]` raised KeyError for a label whose source is none of the five known (a label
    from a colleague's newer ENLENS), so the whole export failed."""
    from enlens_claims import flexiconc_export

    pid, doc = loaded.query("SELECT passage_id, doc_id FROM passages ORDER BY passage_id LIMIT 1")[0]
    with loaded.connect() as cx:
        for i, source in enumerate(("future", "model")):
            cx.execute("INSERT INTO labels(label_id, passage_id, doc_id, framework, code, relevance, confidence, quote, "
                       "start, end, source, created_at) VALUES (?,?,?,'sdg','6.4','high',0.9,'x',0,5,?,?)",
                       (f"lx{i}", pid, doc, source, store.now()))
    flexiconc_export.export(loaded, tmp_path / "out.sqlite", embeddings=False)
    assert (tmp_path / "out.sqlite").exists()


def test_a_label_of_a_kind_this_version_does_not_know_does_not_stop_the_codes_pages(loaded):
    """The sibling in `profile.effective` (every page of labels, the profile, search by code): the same KeyError."""
    from enlens_claims import profile

    pid, doc = loaded.query("SELECT passage_id, doc_id FROM passages ORDER BY passage_id LIMIT 1")[0]
    with loaded.connect() as cx:
        for i, source in enumerate(("future", "person")):
            cx.execute("INSERT INTO labels(label_id, passage_id, doc_id, framework, code, relevance, confidence, quote, "
                       "start, end, source, created_at) VALUES (?,?,?,'sdg','6.4','high',0.9,'x',0,5,?,?)",
                       (f"ly{i}", pid, doc, source, store.now()))
    got = [r for r in profile.effective(loaded, "sdg") if r["passage_id"] == pid and r["code"] == "6.4"]
    assert [r["source"] for r in got] == ["person"]


# ---------------------------------------------------------------------------------------------
# 1, the sweep: other rules of the `^…$` shape in src/ (each in another area's file: settled here by a test, not changed)
# ---------------------------------------------------------------------------------------------
def test_sweep_a_time_with_a_final_newline_reaches_the_qdpx_file_without_it():
    """qdpx.py `_stamp`: `$` with `.match`, but on the time stripped first, so no line break can pass into the file."""
    from enlens_claims import qdpx

    assert qdpx._stamp("2026-11-19T10:00:00+00:00\n") == "2026-11-19T10:00:00+00:00"
    assert qdpx._stamp("2026-11-19T10:00:00+00:00\nx") is None


def test_sweep_an_address_with_an_encoded_line_break_is_no_route_or_project(api):  # noqa: F811
    """gui/server.py ROUTES (and add-ons' routes, addons.py): `"^" + p + "$"` is matched on the path as it came, where
    a line break can only stand encoded (`%0A`: a raw one ends the request line); the name it gives after decoding
    is no project, said as such."""
    assert api("POST", "/api/projects", {"name": "Fieldwork"})[0] == 200
    st, r = api("GET", "/api/projects/Fieldwork%0A/documents")
    assert st == 404 and "error" in r
    assert api("GET", "/api/state%0A")[0] == 404


def test_sweep_a_kept_excerpts_id_with_a_final_newline_is_no_kept_excerpt():
    """reread.py `_TOMB` (`$` with `.search`) tells ENLENS's own ids apart: the ids it is asked about are made by
    `tombstone` and `passage_range` (never with a line break) and come from ENLENS's own task payloads, never from a
    person or a file, so the final-newline case cannot arise."""
    from enlens_claims import reread

    made = reread.tombstone("d1:0005", 1)
    assert "\n" not in made and reread.is_tombstone(made) and not reread.is_tombstone("d1:0005")


# ---------------------------------------------------------------------------------------------
# 3, after review: the level a project needs is THIS copy's own. What leaves never carries it (a file of the sync says
# what it needs by its own `sync_needs`, sync/formats.py), and a merge never sets, raises or lowers it here
# ---------------------------------------------------------------------------------------------
def _zip_meta(zpath: pathlib.Path, member: str, tmp: pathlib.Path) -> dict:
    db = tmp / f"{zpath.stem}-{member.replace('/', '_')}"
    with zipfile.ZipFile(zpath) as zf:
        db.write_bytes(zf.read(member))
    return _meta(db)


@pytest.mark.parametrize("scope", ["shared", "all"])
def test_a_project_zip_carries_no_level_of_its_own_and_the_copy_it_becomes_records_its_own(loaded, tmp_path, scope):
    assert loaded.meta(store.PROJECT_NEEDS_KEY) == store.PROJECT_LEVEL
    out = tmp_path / f"{scope}.zip"
    bundle.export_project(loaded, out, scope=scope)
    assert store.PROJECT_NEEDS_KEY not in _zip_meta(out, "enlens.sqlite", tmp_path)
    copy = bundle.import_project(out, tmp_path / "copy")
    assert copy.meta(store.PROJECT_NEEDS_KEY) == store.PROJECT_LEVEL
    copy.close_all()


def test_the_databases_bundles_are_made_in_record_no_level(tmp_path):
    """Every bundle of the shared folder, of a storage space and of one person's private sync is written from a
    scratch copy (`Workspace.create(..., scratch=True)`, a copy of the empty database): neither holds the level."""
    scratch = Workspace.create(tmp_path / "work", scratch=True)
    assert scratch.meta(store.PROJECT_NEEDS_KEY) is None
    scratch.close_all()
    own = Workspace.create(tmp_path / "own")  # (made from the same empty database: records its own at once)
    assert own.meta(store.PROJECT_NEEDS_KEY) == store.PROJECT_LEVEL
    own.close_all()


def test_a_shared_folder_bundle_carries_no_level(loaded, tmp_path):
    from enlens_claims.sync import folder

    _check(loaded, CLAIM)
    team = tmp_path / "team"
    team.mkdir()
    folder.set_folder(loaded, str(team))
    folder.write(loaded)
    bundles = sorted(team.rglob("bundles/*.zip"))
    assert bundles
    for b in bundles:
        assert store.PROJECT_NEEDS_KEY not in _zip_meta(b, "rows.sqlite", tmp_path)


@pytest.mark.parametrize("theirs", ["0", "2"])
def test_a_merge_never_changes_this_copys_level_from_a_file(loaded, tmp_path, theirs):
    """No zip ENLENS writes carries a level; a colleague's folder zipped by hand may (its database's own). One at or
    below this version's is merged by the sync's own rules; one above it is a database a newer ENLENS changed, which
    this version would read wrongly: refused in words before anything is merged (as opening it is). Either way this
    copy's level is its own and stays as it was."""
    from enlens_claims import sync

    out = tmp_path / "theirs.zip"
    bundle.export_project(loaded, out, scope="all")
    unpacked = tmp_path / "theirs"
    with zipfile.ZipFile(out) as zf:
        zf.extractall(unpacked)
    _set_meta(unpacked / "enlens.sqlite", store.PROJECT_NEEDS_KEY, theirs)
    hand = tmp_path / "hand.zip"
    with zipfile.ZipFile(hand, "w") as zf:
        for f in unpacked.rglob("*"):
            if f.is_file():
                zf.write(f, f.relative_to(unpacked).as_posix())
    mine = bundle.import_project(out, tmp_path / "mine")
    before = mine.scalar("SELECT COUNT(*) FROM sync_log")
    if int(theirs) > store.PROJECT_LEVEL:
        with pytest.raises(store.ProjectTooNew):
            sync.bring_in(mine, hand, anyway=True)
        assert mine.scalar("SELECT COUNT(*) FROM sync_log") == before  # nothing merged
    else:
        sync.bring_in(mine, hand, anyway=True)
    assert mine.meta(store.PROJECT_NEEDS_KEY) == store.PROJECT_LEVEL
    mine.close_all()


# ---------------------------------------------------------------------------------------------
# 3, after the review of wave 3: no zip carries the level a project needs, so an older ENLENS's only guard for a zip is
# the zip's `sync_needs`. The two rise together
# ---------------------------------------------------------------------------------------------
# what a zip needed while level 1 was the only project level (sync/formats.py when the level was made)
ZIP_NEEDS_AT_LEVEL_1, OWNED_ZIP_NEEDS_AT_LEVEL_1 = 1, 4


def test_a_higher_project_level_comes_with_a_higher_need_of_every_zip():
    from enlens_claims.sync import formats

    if store.PROJECT_LEVEL == 1:
        return  # (nothing to keep in step yet)
    assert formats.ZIP_NEEDS > ZIP_NEEDS_AT_LEVEL_1 and formats.OWNED_ZIP_NEEDS > OWNED_ZIP_NEEDS_AT_LEVEL_1, (
        f"store.PROJECT_LEVEL is {store.PROJECT_LEVEL}, but a project zip still needs only sync format "
        f"{formats.ZIP_NEEDS} (with an owner {formats.OWNED_ZIP_NEEDS}): no zip carries the project level "
        "(bundle.export_project, sharing.strip), so an older ENLENS would open it unwarned. Raise sync/formats.py "
        "FORMAT, ZIP_NEEDS and OWNED_ZIP_NEEDS to the new format (and describe it in that module's list), then pin "
        "the values that go with the new level here.")
    assert formats.FORMAT >= max(formats.ZIP_NEEDS, formats.OWNED_ZIP_NEEDS)


def test_a_zip_says_the_need_an_older_enlens_checks(loaded, tmp_path):
    """The guard the test above keeps in step is the one a zip really carries: `bundle.json`'s `sync_needs` is
    `formats.zip_needs` of the project, and a copy whose format is lower refuses it in words."""
    from enlens_claims.sync import formats

    out = tmp_path / "all.zip"
    bundle.export_project(loaded, out, scope="all")
    with zipfile.ZipFile(out) as zf:
        meta = json.loads(zf.read("bundle.json"))
    assert meta["sync_needs"] == formats.zip_needs(loaded._conn())
    older = dict(meta, sync_needs=formats.FORMAT + 1)
    assert "newer ENLENS" in (formats.problem(older) or "")
