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

    def interrupted(cx, root):  # the app quits (or the computer stops) in the middle of the one-time step itself
        raise RuntimeError("interrupted")

    # (fix review: interrupted inside the gated step, not before it, so a fix that only moves the step earlier in
    # `_setup` cannot pass without closing the window between the sign and the work)
    real = sharing.upgrade
    monkeypatch.setattr(sharing, "upgrade", interrupted)
    with contextlib.suppress(RuntimeError):
        Workspace.open(loaded.root)
    monkeypatch.setattr(sharing, "upgrade", real)
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

    def interrupted(ws):  # (fix review: inside the gated step itself, see the test above)
        raise RuntimeError("interrupted")

    real = access.upgrade
    monkeypatch.setattr(access, "upgrade", interrupted)
    with contextlib.suppress(RuntimeError):
        Workspace.open(loaded.root)
    monkeypatch.setattr(access, "upgrade", real)
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
    # (fix review: read as ENLENS reads it, so a design that recovers on reading would pass too)
    assert ws.config["thresholds"]["support_confidence"] == 0.7


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
    # (fix review: refused, kept, or set aside as links.json.damaged: A's link is still somewhere a person can find it)
    kept = [f.read_text(encoding="utf-8") for f in (links, links.with_name("links.json.damaged")) if f.exists()]
    assert any(str(a.root.resolve()) in t for t in kept)


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


# --- fix sweep (hunt phase 1, files): the same shapes beside the six claims -----------------------------------------
def _cut_off(monkeypatch, name):
    """A write in place of the file `name` cut off as the FILES-3 test cuts it: emptied, then the disk is full."""
    real = pathlib.Path.write_text

    def cut(self, data, *a, **kw):
        if self.name == name:
            open(self, "w").close()
            raise OSError(errno.ENOSPC, "No space left on device")
        return real(self, data, *a, **kw)

    monkeypatch.setattr(pathlib.Path, "write_text", cut)
    return real


def test_a_full_disk_while_the_shared_folder_is_noted_keeps_the_projects_other_settings(ws, monkeypatch):
    """The shared folder's record is written into config.json by sync/folder.py `_set_config`, in place as
    access.py's was: cut off, every setting of the project went with it."""
    from enlens_claims.sync import folder

    cfg = json.loads(ws.config_path.read_text())
    cfg["thresholds"]["support_confidence"] = 0.7
    ws.config_path.write_text(json.dumps(cfg, indent=2))
    real = _cut_off(monkeypatch, "config.json")
    with contextlib.suppress(OSError):
        folder._set_config(ws, **{folder.KEEP_OUT: True})
    monkeypatch.setattr(pathlib.Path, "write_text", real)
    ws._config_cache = None
    assert ws.config["thresholds"]["support_confidence"] == 0.7


def test_a_damaged_config_json_is_not_written_over_by_a_setting(ws):
    """A config.json that does not parse counted as empty (access.py `_write_config`, sync/folder.py `_set_config`):
    saving one setting wrote a file holding that one alone over whatever the damaged file still held."""
    from enlens_claims.sync import folder

    damaged = '{"thresholds": {"support_confidence": 0.7}, "ai_access_default": "clo'
    ws.config_path.write_text(damaged, encoding="utf-8")
    for change in (lambda: folder._set_config(ws, **{folder.KEEP_OUT: True}), lambda: access.set_default(ws, "local")):
        try:
            change()
        except ValueError as e:
            assert "config.json" in str(e)  # said in words
        assert ws.config_path.read_text(encoding="utf-8") == damaged


def test_a_damaged_list_of_quick_looks_is_set_aside_not_written_over():
    """quicklook.json that does not parse counted as empty when read to be changed (`_read_dict`), so noting one more
    quick look wrote a list with it alone: the others were never cleared up and the list was lost for good."""
    a = home.create_quicklook("Interview 1.pdf")
    a.close_all()
    ql = home.home() / "quicklook.json"
    ql.write_text(ql.read_text(encoding="utf-8")[:-3], encoding="utf-8")
    b = home.create_quicklook("Interview 2.pdf")
    b.close_all()
    aside = ql.with_name("quicklook.json.damaged")
    assert aside.exists() and a.root.name in aside.read_text(encoding="utf-8")
    assert home.is_temporary(b.root.name)  # the change still made, on a new list


def test_a_damaged_file_of_model_speeds_is_set_aside_not_written_over():
    """benchmarks.json, the same: `record_benchmark` wrote the one model's speeds over a file that did not parse."""
    home.record_benchmark("model-a", {"check": {"seconds_median": 2.0}})
    p = home.home() / "benchmarks.json"
    p.write_text(p.read_text(encoding="utf-8")[:-3], encoding="utf-8")
    home.record_benchmark("model-b", {"check": {"seconds_median": 3.0}})
    aside = p.with_name("benchmarks.json.damaged")
    assert aside.exists() and "model-a" in aside.read_text(encoding="utf-8")


def test_a_folder_linked_with_the_name_of_a_vanished_quick_look_is_not_unlinked(tmp_path):
    """Linking claims a name as making a project does (`link_existing`): the clean-up of a vanished quick look of that
    name unlinked the person's linked project."""
    import shutil
    import time

    ql = home.create_quicklook("Interview 4.pdf")
    name = ql.root.name
    ql.close_all()
    shutil.rmtree(ql.root)
    other = Workspace.create(tmp_path / "Fieldwork")
    other.close_all()
    home.link_existing(str(other.root), name=name)
    home.cleanup_quicklooks(now_=time.time() + 8 * 86400)
    assert name in home.list_projects()


def test_a_project_brought_in_with_the_name_of_a_vanished_quick_look_is_not_sent_to_the_trash(loaded, tmp_path):
    """Bringing a project in from a zip claims its name too (`bundle.import_project`)."""
    import shutil
    import time

    from enlens_claims import bundle

    out = tmp_path / "p.zip"
    bundle.export_project(loaded, out)
    ql = home.create_quicklook("Interview 5.pdf")
    name = ql.root.name
    ql.close_all()
    shutil.rmtree(ql.root)
    got = bundle.import_project(out, home.home() / "projects" / name)
    got.close_all()
    home.cleanup_quicklooks(now_=time.time() + 8 * 86400)
    assert name in home.list_projects()


def test_a_bibtex_doi_and_url_in_mendeleys_braced_escape_are_read_whole():
    """Mendeley writes an underscore as `{\\_}`; the url's own unescaping left `{_}` in it, and the doi kept it all."""
    text = ("@article{smith2020,\n  title = {Water use},\n  author = {Smith, Jane},\n  year = {2020},\n"
            "  doi = {10.1016/j.wat{\\_}res.2020.115{\\_}678},\n"
            "  url = {https://example.org/a{\\_}b}\n}\n")
    _fmt, works = bibliography.parse_file("refs.bib", text)
    assert works[0]["doi"] == "10.1016/j.wat_res.2020.115_678"
    assert works[0]["url"] == "https://example.org/a_b"


def test_a_bibtex_doi_in_the_note_with_an_escaped_underscore_is_the_works_doi():
    """A doi given only in the note field (`doi: 10.…`) was read raw too, backslash and all."""
    text = ("@misc{smith2020,\n  title = {Water use},\n  author = {Smith, Jane},\n  year = {2020},\n"
            "  note = {doi: 10.1016/j.wat\\_res.2020.115\\_678}\n}\n")
    _fmt, works = bibliography.parse_file("refs.bib", text)
    assert works[0]["doi"] == "10.1016/j.wat_res.2020.115_678"


def test_a_cut_off_title_of_a_colleagues_codebook_version_keeps_the_codebook(ws, monkeypatch):
    """A colleague's version of a codebook that clashed with yours is kept beside it, its title saying whose it is
    (sync/codebook_merge.py `_mark_codebook_title`): the codebook's side file (its codes' ids, groups and history) was
    written in place, and a cut-off write left it empty."""
    from types import SimpleNamespace

    from enlens_claims.sync.codebook_merge import CodebookRules

    side = ws.root / "frameworks" / "habits_ann.json"
    side.parent.mkdir(exist_ok=True)
    side.write_text(json.dumps({"title": "Habits", "ids": {"a": "u1"}, "groups": [{"name": "G"}]}), encoding="utf-8")
    real = _cut_off(monkeypatch, "habits_ann.json")
    with contextlib.suppress(OSError):
        CodebookRules._mark_codebook_title(SimpleNamespace(ws=ws, sender={"name": "Ann"}), "habits_ann", "Habits")
    monkeypatch.setattr(pathlib.Path, "write_text", real)
    assert json.loads(side.read_text(encoding="utf-8"))["ids"] == {"a": "u1"}
