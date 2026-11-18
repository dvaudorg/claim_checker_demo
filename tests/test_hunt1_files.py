"""Hunt phase 1, area `files`: the project on disk, the app's data folder, earlier versions, and what goes out to and
comes in from other programs. Each test asserts what ENLENS should do and fails today for the reason in its
docstring."""
from __future__ import annotations

import contextlib
import errno
import json
import pathlib

from enlens_claims import access, bibliography, home, sharing, store
from enlens_claims.store import Workspace
from test_private_until_shared import _as_before_018, _check
from test_shared_projects import CLAIM


# --- a project from an earlier version, opened for the first time ---------------------------------------------------
def test_an_interrupted_first_opening_still_counts_an_exchanged_project_as_shared(loaded, monkeypatch):
    """A 0.17 project exchanged with a colleague counts as shared when 0.18 first opens it, but only if that opening
    runs to its end: `shares` is made (and saved) first and is the only sign of an old project (store.py:851, 865),
    so an opening interrupted after it never marks anything shared again, and the colleague gets nothing."""
    hid = _check(loaded, CLAIM)
    _as_before_018(loaded)
    with loaded.connect() as cx:  # a colleague's work was brought in once: it was exchanged
        cx.execute("INSERT INTO sync_log(at, person_id, report_json) VALUES ('2026-11-01', 'p0123456789ab', '{}')")
    loaded.close_all()

    def interrupted(cx):  # the app quits (or the computer stops) late in the first opening
        raise RuntimeError("interrupted")

    real = store._setup_addons
    monkeypatch.setattr(store, "_setup_addons", interrupted)
    with contextlib.suppress(RuntimeError):
        Workspace.open(loaded.root)
    monkeypatch.setattr(store, "_setup_addons", real)
    ws = Workspace.open(loaded.root)  # opened again, to its end
    assert sharing.state(ws._conn(), "check", hid)["state"] == "shared"
    ws.close_all()


def test_an_interrupted_first_opening_still_records_what_claude_read_before_011(loaded, monkeypatch):
    """A project from before 0.11 gets its ledger of what Claude read (from the answers on Claude's routes) when it
    is first opened, but only if `before_011` (no column ai_access, store.py:850) is still true: the column is added
    and saved first and the upgrade runs after `_setup` (store.py:874), so an opening interrupted in between never
    writes the ledger: the AI log and the share-of-a-document cap then count nothing Claude read before."""
    pid, doc = loaded.query("SELECT passage_id, doc_id FROM passages ORDER BY passage_id LIMIT 1")[0]
    with loaded.connect() as cx:
        cx.execute("INSERT INTO tasks(task_id, kind, model, payload_json, status) VALUES ('check:old', 'check', "
                   "'opus', ?, 'done')", (json.dumps({"passages": [{"passage_id": pid}]}),))
        cx.execute("INSERT INTO results(task_id, attempt, kind, model, raw_json, valid, received_at, route) VALUES "
                   "('check:old', 1, 'check', 'opus', '{}', 1, '2025-01-01T00:00:00+00:00', 'Claude Code')")
        cx.execute("DELETE FROM ai_sent")
        cx.execute("DELETE FROM meta WHERE key IN ('ai_access_upgraded', 'ai_sent_since')")
        cx.execute("ALTER TABLE documents DROP COLUMN ai_access")  # the project as 0.10 left it
    loaded.close_all()

    def interrupted(cx):
        raise RuntimeError("interrupted")

    real = store._setup_addons
    monkeypatch.setattr(store, "_setup_addons", interrupted)
    with contextlib.suppress(RuntimeError):
        Workspace.open(loaded.root)
    monkeypatch.setattr(store, "_setup_addons", real)
    ws = Workspace.open(loaded.root)
    assert ws.scalar("SELECT COUNT(*) FROM ai_sent WHERE passage_id=? AND doc_id=?", (pid, doc)) == 1
    ws.close_all()


# --- config.json ----------------------------------------------------------------------------------------------------
def test_a_full_disk_while_a_project_setting_is_saved_keeps_the_projects_other_settings(ws, monkeypatch):
    """config.json is written in place (access.py:335 `_write_config`, also bundle.py:416, sync/folder.py:229): a
    full disk (or a crash) during the write leaves it empty, and every setting of the project is gone; the project's
    settings then cannot even be read (store.py:935)."""
    cfg = json.loads(ws.config_path.read_text())
    cfg["thresholds"]["support_confidence"] = 0.7
    cfg["ai_access_default"] = "cloud"
    ws.config_path.write_text(json.dumps(cfg, indent=2))
    real = pathlib.Path.write_text

    def disk_full(self, data, *a, **kw):
        if self.name == "config.json":
            open(self, "w").close()  # the file is opened for writing (emptied), then the disk is full
            raise OSError(errno.ENOSPC, "No space left on device")
        return real(self, data, *a, **kw)

    monkeypatch.setattr(pathlib.Path, "write_text", disk_full)
    with contextlib.suppress(OSError):
        access.set_default(ws, "local")
    monkeypatch.setattr(pathlib.Path, "write_text", real)
    ws._config_cache = None
    kept = json.loads(ws.config_path.read_text() or "{}")
    assert kept.get("thresholds", {}).get("support_confidence") == 0.7


# --- the data folder: links.json -------------------------------------------------------------------------------------
def test_a_damaged_list_of_linked_projects_is_not_overwritten_by_linking_another(tmp_path):
    """links.json that does not parse (cut short) counts as empty even when read to be changed (home.py:276
    `_read_dict`), so linking one more project writes a list with only that one: every other linked project is
    dropped from the list for good."""
    a = Workspace.create(tmp_path / "Fieldwork A")
    b = Workspace.create(tmp_path / "Fieldwork B")
    a.close_all()
    b.close_all()
    home.link_existing(str(a.root))
    links = home.home() / "links.json"
    whole = links.read_text(encoding="utf-8")
    links.write_text(whole[:-3], encoding="utf-8")  # cut short (a crash as it was written, a sync tool)
    with contextlib.suppress(Exception):
        home.link_existing(str(b.root))
    assert str(a.root.resolve()) in links.read_text(encoding="utf-8")


def test_a_project_made_with_the_name_of_a_vanished_quick_look_is_not_sent_to_the_trash():
    """A quick look whose folder went (removed in the Finder, say) stays on the list of temporary projects; a real
    project made later under that name is not taken off it (home.py:1039 `create_project`), so the next clean-up
    (home.py:1280 `cleanup_quicklooks`, at every start of the app) moves the person's project to the trash."""
    import shutil
    import time

    ql = home.create_quicklook("Interview 3.pdf")
    name = ql.root.name
    ql.close_all()
    shutil.rmtree(ql.root)  # gone outside ENLENS
    real = home.create_project(name)  # the person's own project, by that name
    with real.connect() as cx:
        cx.execute("INSERT INTO meta VALUES ('mine', '1')")
    real.close_all()
    home.cleanup_quicklooks(now_=time.time() + 8 * 86400)
    assert name in home.list_projects()


# --- bibliography ---------------------------------------------------------------------------------------------------
def test_a_bibtex_doi_with_an_escaped_underscore_is_the_works_doi():
    """BibTeX writes an underscore as `\\_`; the doi field is read raw (bibliography.py:638 `_bib_work`), so the work
    keeps a DOI with a backslash: it never matches its document by DOI, and the retraction lookup asks Crossref for
    a DOI that does not exist and shows the work as checked, with no notice."""
    text = ("@article{smith2020,\n  title = {Water use of electrolytic hydrogen in arid regions},\n"
            "  author = {Smith, Jane},\n  year = {2020},\n  doi = {10.1016/j.wat\\_res.2020.115\\_678}\n}\n")
    _fmt, works = bibliography.parse_file("refs.bib", text)
    assert works[0]["doi"] == "10.1016/j.wat_res.2020.115_678"
