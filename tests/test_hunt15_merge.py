"""Hunt, phase 1.5 (area `merge`): every note and open point phases 0 and 1 left about how two copies come together,
settled by a test (.claude/audits/2026-11-19-phase1.5/ledger/merge.md says which test settles which item).

A colleague's file is untrusted input: the tests change a real copy's zip with an SQLite tool (as anyone can), as
tests/test_hunt1_merge.py does, or a member writes into their own part of a storage space what their copy would never
write (as tests/test_same_person_sync.py does).
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from enlens_claims import notes, sharing
from enlens_claims.store import now
from test_authorship import _forge
from test_hunt1_merge import _first_doc, _rezip, _words, abc  # noqa: F401  (fixture)
from test_same_person_sync import carols  # noqa: F401  (fixture)
from test_shared_projects import Person, anna_and_ben  # noqa: F401  (fixture)
from test_storage_space import _check, _has, _join_new, _round, owner, store_dir  # noqa: F401  (fixtures)

FAR = "2999-01-01T00:00:00+00:00"


def _note(p: Person, text: str = "Anna's note") -> str:
    doc = _first_doc(p)
    a, z = _words(p, doc)
    with p:
        nid = notes.add(p.ws, doc, a, z, text=text)["note_id"]
        sharing.share(p.ws, [{"kind": "note", "key": nid}])
    return nid


def _state(p: Person, kind: str, key: str) -> str | None:
    with p:
        r = p.ws._conn().execute("SELECT state FROM shares WHERE kind=? AND key=?", (kind, key)).fetchone()
    return r[0] if r else None


# ---- 1. a forged "withdrawn" share mark dated ahead (owner's item 1) -----------------------------------------------
def test_a_withdrawal_dated_ahead_does_not_outlast_its_owners_later_share(abc, tmp_path):
    """Carol's zip says Anna took her shared note back, in Anna's name and dated 2999. Ben, who does not hold the note,
    notes it as taken back. Anna then shares it again (a mark of now): her own later mark must count, so Ben gets the
    note from her file. A mark dated ahead counts as made when it was received (sharing.mark_at)."""
    anna, ben, carol = abc
    nid = _note(anna)
    forged = _forge(carol.send(), tmp_path / "carol-forged.zip",
                    ("INSERT OR REPLACE INTO shares(kind, key, state, owner, by, at, title) VALUES "
                     "('note', ?, 'withdrawn', ?, ?, ?, NULL)", (nid, anna.id, anna.id, FAR)))
    ben.bring_in(forged)
    with ben:
        at = ben.ws.scalar("SELECT at FROM shares WHERE kind='note' AND key=?", (nid,))
    assert at is None or at < "2100", at   # never stored as dated ahead
    with anna:
        sharing.unshare(anna.ws, [{"kind": "note", "key": nid}])
        sharing.share(anna.ws, [{"kind": "note", "key": nid}])
    ben.bring_in(anna.send())
    with ben:
        assert ben.ws.scalar("SELECT person_id FROM notes WHERE note_id=?", (nid,)) == anna.id
    assert _state(ben, "note", nid) == "shared"


def test_a_mark_dated_ahead_is_clamped_when_held_too(abc, tmp_path):
    """The same through `_share_marks` for an item Ben holds: Carol's zip marks Anna's shared note withdrawn in 2999;
    Anna's next share (unshare, share) must count over it."""
    anna, ben, carol = abc
    nid = _note(anna)
    ben.bring_in(anna.send())
    carol.bring_in(anna.send())
    forged = _forge(carol.send(), tmp_path / "carol-forged.zip",
                    ("UPDATE shares SET state='withdrawn', at=?, title=NULL WHERE kind='note' AND key=?", (FAR, nid)))
    ben.bring_in(forged)
    with anna:
        sharing.unshare(anna.ws, [{"kind": "note", "key": nid}])
        sharing.share(anna.ws, [{"kind": "note", "key": nid}])
    ben.bring_in(anna.send())
    assert _state(ben, "note", nid) == "shared"


@pytest.fixture
def trio(owner, tmp_path, monkeypatch):  # noqa: F811
    """Anna (owner, keeper of the storage space), Carol and Dan, each a member from an invite link."""
    anna = owner
    carol, dan = Person(tmp_path, "Carol", monkeypatch), Person(tmp_path, "Dan", monkeypatch)
    for p in (carol, dan):
        with anna:
            inv = space_invite(anna, p.name)
        _join_new(p, inv)
    for p in (anna, carol, dan, anna, carol, dan):
        _round(p)
    return anna, carol, dan


def space_invite(p: Person, label: str) -> str:
    from enlens_claims.sync import space

    return space.invite(p.ws, label)["link"]


def _forge_mark(p: Person, kind: str, key: str, state: str, owner: str, at: str = FAR) -> None:
    """A member writes into their own copy (and so into their own signed part of the space) a mark in another
    member's name."""
    with p:
        with p.ws.connect() as cx:
            cx.execute("INSERT OR REPLACE INTO shares(kind, key, state, owner, by, at, title) VALUES (?,?,?,?,?,?,?)",
                       (kind, key, state, owner, owner, at, None if state == "withdrawn" else "x"))


def test_in_a_storage_space_a_members_withdrawal_counts_only_from_their_own_file(trio):
    """Carol shares a check; Anna writes into her own part a mark, in Carol's name, that Carol took it back. Every file
    in a storage space is signed by its writer (sync/seal.py), so Dan's copy can tell this mark did not come in
    Carol's own file: it must not take it (the check stays shared in Dan's copy, and he passes it on)."""
    anna, carol, dan = trio
    hc = _check(carol, "Hydrogen storage is cheap.")
    with carol:
        sharing.share(carol.ws, [{"kind": "check", "key": hc}])
    for p in (carol, anna, dan):
        _round(p)
    assert _state(dan, "check", hc) == "shared"
    _forge_mark(anna, "check", hc, "withdrawn", carol.id)
    _round(anna)
    _round(dan)
    assert _state(dan, "check", hc) == "shared"


def test_in_a_storage_space_a_members_withdrawal_in_anothers_file_keeps_nothing_out(trio):
    """The same for an item Dan does not hold yet: Carol shares a check, and Anna's part says (in Carol's name, dated
    ahead) that Carol took it back. Dan's round notes withdrawals first (folder._withdrawals_first): Anna's forged one
    kept Carol's check out of Dan's copy for good."""
    anna, carol, dan = trio
    hc = _check(carol, "Hydrogen storage is cheap.")
    with carol:
        sharing.share(carol.ws, [{"kind": "check", "key": hc}])
    _round(carol)
    _round(anna)
    _forge_mark(anna, "check", hc, "withdrawn", carol.id)
    _round(anna)
    _round(dan)
    with dan:
        assert _has(dan.ws, hc)
    assert _state(dan, "check", hc) == "shared"


def test_in_a_storage_space_a_members_own_withdrawal_still_counts(trio):
    """The rule keeps the honest route: Carol takes her shared check back; Dan's copy marks it withdrawn."""
    anna, carol, dan = trio
    hc = _check(carol, "Hydrogen storage is cheap.")
    with carol:
        sharing.share(carol.ws, [{"kind": "check", "key": hc}])
    for p in (carol, anna, dan):
        _round(p)
    with carol:
        sharing.unshare(carol.ws, [{"kind": "check", "key": hc}])
    for p in (carol, anna, dan):
        _round(p)
    assert _state(dan, "check", hc) == "withdrawn"


# ---- 2. MERGE-6: two people say they removed one note this copy never held (owner's item 2) ----------------------
def _removed_by(p: Person, kind: str, key: str, who: Person, tmp_path: Path, name: str) -> Path:
    """`p`'s file without the row, with a note of removal of it in `who`'s name (as a changed zip says)."""
    table, col = ("notes", "note_id") if kind == "note" else ("research_log", "entry_id")
    return _forge(p.send(), tmp_path / name, (f"DELETE FROM {table} WHERE {col}=?", (key,)),
                  ("INSERT OR REPLACE INTO sync_removed(kind, key, title, at, person_id) VALUES (?, ?, 'x', ?, ?)",
                   (kind, key, now(), who.id)))


@pytest.mark.parametrize("carol_first", [True, False])
def test_an_authors_removal_keeps_their_note_out_whoever_said_first_they_removed_it(abc, tmp_path, carol_first):
    """Carol's file says she removed Anna's shared note; Anna removes it herself. Ben holds neither the note nor any
    removal. Whichever of the two files reaches Ben first, a relayed copy of the note (Carol's honest next file still
    holds it) must not come in: its author removed it. sync/merge.py kept only the first note of removal
    (`INSERT OR IGNORE`), so with Carol's first, Anna's own was not recorded and the relayed note came in."""
    anna, ben, carol = abc
    nid = _note(anna)
    carol.bring_in(anna.send())
    forged = _removed_by(carol, "note", nid, carol, tmp_path, "carol-forged.zip")
    with anna:
        notes.remove(anna.ws, nid)
    own = anna.send()
    for f in ((forged, own) if carol_first else (own, forged)):
        ben.bring_in(f)
    ben.bring_in(carol.send())   # Carol's own copy still holds Anna's note: it is relayed
    with ben:
        assert not ben.ws.scalar("SELECT 1 FROM notes WHERE note_id=?", (nid,))
    # and Carol's word keeps out nothing of Anna's: a note Anna did not remove still comes, relayed
    nid2 = _note(anna, "Anna's second note")
    carol.bring_in(anna.send())
    ben.bring_in(_removed_by(carol, "note", nid2, carol, tmp_path, "carol-forged-2.zip"))
    ben.bring_in(carol.send())
    with ben:
        assert ben.ws.scalar("SELECT person_id FROM notes WHERE note_id=?", (nid2,)) == anna.id


def test_an_authors_removal_keeps_their_log_entry_out_whoever_said_first_they_removed_it(abc, tmp_path):
    """MERGE-6 for the research log, Carol's word first."""
    from enlens_claims import researchlog

    anna, ben, carol = abc
    with anna:
        eid = researchlog.add(anna.ws, "Why we left the 2019 reports out")["entry_id"]
        sharing.share(anna.ws, [{"kind": "log", "key": eid}])
    carol.bring_in(anna.send())
    ben.bring_in(_removed_by(carol, "log", eid, carol, tmp_path, "carol-forged.zip"))
    with anna:
        researchlog.remove(anna.ws, eid)
    ben.bring_in(anna.send())
    ben.bring_in(carol.send())
    with ben:
        assert not ben.ws.scalar("SELECT 1 FROM research_log WHERE entry_id=?", (eid,))


def test_a_second_removal_note_stays_on_this_computer(abc, tmp_path):
    """The note of removal kept beside the first (sync/common.ALSO_REMOVED) is this copy's record of others' items: a
    zip of what Ben shared does not hold it."""
    import zipfile

    from enlens_claims import bundle

    anna, ben, carol = abc
    nid = _note(anna)
    carol.bring_in(anna.send())
    ben.bring_in(_removed_by(carol, "note", nid, carol, tmp_path, "carol-forged.zip"))
    with anna:
        notes.remove(anna.ws, nid)
    ben.bring_in(anna.send())
    with ben:
        assert ben.ws.scalar("SELECT COUNT(*) FROM sync_removed WHERE kind='note-also'") == 1
        out = tmp_path / "ben-shared.zip"
        bundle.export_project(ben.ws, out, scope="shared")
    work = tmp_path / "ben-unpacked"
    with zipfile.ZipFile(out) as zf:
        zf.extract("enlens.sqlite", work)
    cx = sqlite3.connect(work / "enlens.sqlite")
    try:
        assert not cx.execute("SELECT COUNT(*) FROM sync_removed WHERE kind IN ('note-also', 'log-also')").fetchone()[0]
    finally:
        cx.close()


# ---- 3. theory_codes tasks stay on the computer (owner's item 3) ---------------------------------------------------
def _theory_codes_task(ws) -> str:
    """A finished `theory_codes` task with its answer, as theorycodes.make_ai_tasks and the AI make them."""
    pid, doc = ws.query("SELECT passage_id, doc_id FROM passages LIMIT 1")[0]
    tid = f"theory_codes:{doc}:aaaaaaaaaaaa"
    with ws.connect() as cx:
        cx.execute("INSERT INTO tasks(task_id, kind, model, prompt_version, payload_json, status, attempts, created_at, "
                   "access) VALUES (?, 'theory_codes', 'claude-sonnet-5-5', 'v1', ?, 'done', 1, "
                   "'2026-11-18T00:00:00+00:00', 'cloud')",
                   (tid, json.dumps({"doc_id": doc, "passages": [{"passage_id": pid}],
                                     "hints": ["My secret draft concept"]})))
        cx.execute("INSERT INTO results(task_id, attempt, kind, model, prompt_version, raw_json, valid, errors_json, "
                   "received_at) VALUES (?, 1, 'theory_codes', 'claude-sonnet-5-5', 'v1', ?, 1, '[]', "
                   "'2026-11-18T00:00:00+00:00')",
                   (tid, json.dumps({"concepts": [{"name": "My secret draft concept"}]})))
    return tid


def test_the_concepts_the_ai_drafted_from_a_theory_document_stay_but_its_codebook_travels(abc, tmp_path):
    """Anna asks the AI to draft concepts from a theory document (`theory_codes` tasks, theorycodes.make_ai_tasks) and
    makes a codebook of a drafted concept by the route the page takes (`codebooks.create(start="theory")` from
    `theorycodes.ai_drafts`), which she shares. Her zip of what she shared and the shared folder's rows hold no
    `theory_codes` task or answer; Ben, from her zip, gets the codebook with the definition quoted from the theory."""
    import zipfile

    from enlens_claims import bundle, codebooks, frameworks, theorycodes

    anna, ben, carol = abc
    doc = _first_doc(anna)
    with anna:
        tids = theorycodes.make_ai_tasks(anna.ws, doc, "claude-sonnet-5-5")
        payload = json.loads(anna.ws.scalar("SELECT payload_json FROM tasks WHERE task_id=?", (tids[0],)))
        quote = " ".join(payload["passages"][0]["text"].split()[:10])
        answer = {"concepts": [{"name": "Water stress", "reason": "the text defines it",
                                "definition": {"passage": 1, "quote": quote}}]}
        with anna.ws.connect() as cx:
            cx.execute("UPDATE tasks SET status='done', attempts=1 WHERE task_id=?", (tids[0],))
            cx.execute("INSERT INTO results(task_id, attempt, kind, model, prompt_version, raw_json, valid, "
                       "errors_json, received_at) VALUES (?, 1, 'theory_codes', 'claude-sonnet-5-5', 'v1', ?, 1, "
                       "'[]', ?)", (tids[0], json.dumps(answer), now()))
        drafts = theorycodes.ai_drafts(anna.ws, tids, with_examples=False)
        assert [d["term"] for d in drafts] == ["Water stress"]
        codebooks.create(anna.ws, "stress", "Stress codes", start="theory",
                         source={"codes": [drafts[0]["code"]], "doc_id": doc})
        sharing.share(anna.ws, [{"kind": "codebook", "key": "stress"}])
        with anna.ws.connect() as cx:
            sent = {r[2][0] for r in sharing.ProjectRows(cx, anna.ws.root).scan(only=["tasks", "results"])
                    if r[0] in ("tasks", "results")}
        out = tmp_path / "anna-shared.zip"
        bundle.export_project(anna.ws, out, scope="shared")
    assert not set(tids) & sent
    work = tmp_path / "unpacked"
    with zipfile.ZipFile(out) as zf:
        zf.extract("enlens.sqlite", work)
    cx = sqlite3.connect(work / "enlens.sqlite")
    try:
        assert not cx.execute("SELECT COUNT(*) FROM tasks WHERE kind='theory_codes'").fetchone()[0]
        assert not cx.execute("SELECT COUNT(*) FROM results WHERE kind='theory_codes'").fetchone()[0]
    finally:
        cx.close()
    assert "theory_codes" in sharing.LOCAL_TASK_KINDS   # (so sync.folder._leaks refuses one: test_hunt1_merge)
    ben.bring_in(out)
    with ben:
        assert sharing.exists(ben.ws._conn(), ben.ws.root, "codebook", "stress")
        fw = frameworks.get("stress", ben.ws)
        assert quote.split()[3] in fw.codes["Water stress"].description
        assert not ben.ws.scalar("SELECT COUNT(*) FROM tasks WHERE kind='theory_codes'")


def test_a_colleagues_theory_drafts_in_a_whole_project_zip_do_not_come_in(abc, tmp_path):
    """A colleague on an older version sends a whole-project zip that holds their `theory_codes` tasks: a merge does
    not take them."""
    from enlens_claims import bundle

    anna, ben, carol = abc
    with anna:
        tid = _theory_codes_task(anna.ws)
        f = tmp_path / "anna-all.zip"
        bundle.export_project(anna.ws, f, scope="all")
    ben.bring_in(f)
    with ben:
        assert not ben.ws.scalar("SELECT COUNT(*) FROM tasks WHERE task_id=?", (tid,))
        assert not ben.ws.scalar("SELECT COUNT(*) FROM results WHERE task_id=?", (tid,))


# ---- 4. a colleague's removal of a document this copy does not hold ----------------------------------------------
def test_a_members_removal_of_a_document_this_copy_lacks_does_not_keep_it_out(abc, tmp_path):
    """docs/manual/roles.md: a Member's removal is a proposal (*In your copy it goes now; for the project it is a
    proposal to the owner*). Anna (owner) adds a document after Ben's copy was made; Carol (a Member) removes it in her
    copy; Ben brings in Carol's file first (a removal of a document he does not hold), then Anna's: the document is the
    project's, so it comes to Ben (ownership.settle fetches a document of the project that is not here)."""
    from owner_helpers import add_doc, has

    anna, ben, carol = abc
    doc = add_doc(anna, tmp_path, "interview")
    carol.bring_in(anna.send())
    with carol:
        carol.ws.remove_document(doc, why="Not for me")
    ben.bring_in(carol.send())
    assert not has(ben, doc)
    ben.bring_in(anna.send())
    assert has(ben, doc)


def test_the_owners_removal_of_a_document_this_copy_lacks_keeps_it_out(abc, tmp_path):
    """The other side of the rule: the owner's removal is the project's, so a copy that lacks the document does not
    take it from a Member's later file."""
    from owner_helpers import add_doc, has

    anna, ben, carol = abc
    doc = add_doc(anna, tmp_path, "interview")
    carol.bring_in(anna.send())
    with anna:
        anna.ws.remove_document(doc, why="Out of scope")
    ben.bring_in(anna.send())
    ben.bring_in(carol.send())
    assert not has(ben, doc)


def test_a_colleague_who_removed_their_copy_of_your_themes_does_not_keep_them_from_a_third(abc):
    """MERGE-6's shape for a set of themes (checks: test_hunt1_merge): Carol removes her copy of Anna's shared set of
    themes; Ben, who does not hold it, brings Carol's file and then Anna's: the themes come."""
    anna, ben, carol = abc
    with anna:
        run = _theme_run(anna.ws)
        sharing.share(anna.ws, [{"kind": "themes", "key": run}])
    carol.bring_in(anna.send())
    with carol:
        with carol.ws.connect() as cx:
            cx.execute("DELETE FROM theme_runs WHERE run_id=?", (run,))
            cx.execute("INSERT OR REPLACE INTO sync_removed(kind, key, title, at, person_id) VALUES ('themes', ?, 'x', "
                       "?, ?)", (run, now(), carol.id))
    ben.bring_in(carol.send())
    ben.bring_in(anna.send())
    with ben:
        assert ben.ws.scalar("SELECT 1 FROM theme_runs WHERE run_id=?", (run,))


def _theme_run(ws) -> str:
    """A set of themes (a theme run with one theme), as themes.py writes it."""
    import uuid

    run = "r" + uuid.uuid4().hex[:11]
    cols = {r[1] for r in ws._conn().execute("PRAGMA table_info(theme_runs)")}
    row = {"run_id": run, "mode": "kmeans", "k": 1, "seed": 1, "created_at": now(), "passages": 1,
           "run_key": "k" + run, "settings_json": "{}"}
    row = {k: v for k, v in row.items() if k in cols}
    with ws.connect() as cx:
        cx.execute(f"INSERT INTO theme_runs({','.join(row)}) VALUES ({','.join('?' * len(row))})", tuple(row.values()))
        cx.execute("INSERT INTO themes(run_id, theme_id, name, description, terms_json, size, reps_json, name_source) "
                   "VALUES (?, 0, 'Water prices', '', '[]', 1, '[]', 'person')", (run,))
        from enlens_claims import researchlog

        researchlog.record(cx, "themes-found", "Found themes", "themes", run, "Themes")
    return run


# ---- 5. groupnames.merge: a file that says it is yours -------------------------------------------------------------
def _group_name(p: Person) -> str:
    from enlens_claims import groupnames

    with p:
        with p.ws.connect() as cx:
            groupnames._change(cx, "g1", now(), p.id, name="Parking", source="person", concepts_json='["parking"]',
                               labels_json="{}", filters_json="{}", n=1)
    return "g1"


def test_a_file_that_says_it_is_yours_cannot_remove_your_group_name(abc, tmp_path):
    """Carol's zip says it is from Anna and holds a note, in Anna's name, that Anna removed her name of a concept-map
    group (and a renamed version in her name): groupnames.merge took both because the sender was Anna. A row in this
    copy's own name is never taken from a file, as every other table refuses it (MERGE-1)."""
    anna, ben, carol = abc
    nid = _group_name(anna)

    def as_anna(work: Path, cx: sqlite3.Connection, meta: dict) -> None:
        cx.execute("INSERT INTO sync_removed(kind, key, title, at, person_id) VALUES ('group_name', ?, 'Parking', ?, ?)",
                   (nid, now(), anna.id))
        meta["from"] = {"id": anna.id, "name": "Anna"}

    anna.bring_in(_rezip(carol.send(), tmp_path / "carol-as-anna.zip", as_anna))
    with anna:
        assert anna.ws.scalar("SELECT name FROM concept_group_names WHERE name_id=?", (nid,)) == "Parking"
        assert not anna.ws.scalar("SELECT 1 FROM sync_removed WHERE kind='group_name' AND key=?", (nid,))
        cols = [r[1] for r in anna.ws._conn().execute("PRAGMA table_info(concept_group_names)")]
        row = dict(zip(cols, anna.ws._conn().execute("SELECT * FROM concept_group_names WHERE name_id=?",
                                                      (nid,)).fetchone()))

    def renamed(work: Path, cx: sqlite3.Connection, meta: dict) -> None:
        r = {**row, "name": "Car parks", "updated_at": now(), "changed_by": anna.id, "history_json": "[]"}
        cx.execute(f"INSERT OR REPLACE INTO concept_group_names({','.join(r)}) VALUES ({','.join('?' * len(r))})",
                   tuple(r.values()))
        meta["from"] = {"id": anna.id, "name": "Anna"}

    anna.bring_in(_rezip(carol.send(), tmp_path / "carol-as-anna-2.zip", renamed))
    with anna:
        assert anna.ws.scalar("SELECT name FROM concept_group_names WHERE name_id=?", (nid,)) == "Parking"


# ---- 6. joining from an older colleague's whole-project zip --------------------------------------------------------
def test_a_copy_made_from_a_colleagues_whole_zip_keeps_none_of_their_local_drafts(abc, tmp_path):
    """Dan joins from Anna's whole-project zip as an older version wrote it (with her code_definition, theory_frame,
    theory_codes and group_name tasks and their answers): the new copy holds none of them (bundle.import_project
    is not a merge, which skips them)."""
    from enlens_claims import bundle
    from test_hunt1_merge import _private_tasks

    anna, ben, carol = abc
    with anna:
        made = _private_tasks(anna.ws)
        tid = _theory_codes_task(anna.ws)
        with anna.ws.connect() as cx:
            cx.execute("INSERT INTO tasks(task_id, kind, model, prompt_version, payload_json, status, attempts, "
                       "created_at, access) VALUES ('group_name:cccccccccccc', 'group_name', 'm', 'v1', "
                       "'{\"concepts\": [\"secret\"]}', 'done', 1, '2026-11-18T00:00:00+00:00', 'cloud')")
        f = tmp_path / "anna-all.zip"
        bundle.export_project(anna.ws, f, scope="all")
    dan = Person(tmp_path, "Dan", anna.mp)
    with dan:
        dan.ws = bundle.import_project(f, tmp_path / "dan-project")
        local = sharing.LOCAL_TASK_KINDS
        q = ",".join("?" * len(local))
        assert not dan.ws.scalar(f"SELECT COUNT(*) FROM tasks WHERE kind IN ({q})", local)
        assert not dan.ws.scalar(f"SELECT COUNT(*) FROM results WHERE kind IN ({q}) OR task_id IN (?, ?, ?)",
                                 (*local, tid, "theory_frame:aaaaaaaaaaaaaaaa", "code_definition:bbbbbbbbbbbbbbbb"))
        # the rest of her work is there (the glossary concept's search words are a check's kind: they stay)
        assert dan.ws.scalar("SELECT COUNT(*) FROM documents") == 3
    assert made


def test_your_own_backup_keeps_your_local_drafts(abc, tmp_path):
    """The other side: a whole-project zip of Anna's own, opened again by Anna, keeps her drafts."""
    from enlens_claims import bundle

    anna, ben, carol = abc
    with anna:
        tid = _theory_codes_task(anna.ws)
        f = tmp_path / "anna-all.zip"
        bundle.export_project(anna.ws, f, scope="all")
        again = bundle.import_project(f, tmp_path / "anna-again")
        assert again.scalar("SELECT COUNT(*) FROM tasks WHERE task_id=?", (tid,)) == 1
        again.close_all()


# ---- 7. a zip that says it is yours: provider consent ---------------------------------------------------------------
def test_a_zip_that_says_it_is_yours_brings_no_consent_for_a_cloud_provider(abc, tmp_path):
    """Carol's whole-project zip, with `bundle.json` "from" set to Anna and a list that allows OpenAI, a provider Anna
    never allowed: Anna makes a new copy from it. Nothing in a zip proves whose it is, so a list in it may only narrow
    what this copy's own default allows (Anthropic): OpenAI is not allowed, and Anthropic is not either (the list said
    only OpenAI). The person is told in place to tick again (access.PROVIDERS_RESET, "from": "import")."""
    from enlens_claims import access, bundle

    anna, ben, carol = abc
    doc = _first_doc(carol)

    def as_anna(work: Path, cx: sqlite3.Connection, meta: dict) -> None:
        cx.execute("UPDATE documents SET ai_providers=? WHERE doc_id=?", (json.dumps(["openai"]), doc))
        meta["from"] = {"id": anna.id, "name": "Anna"}

    f = _rezip(carol.send(), tmp_path / "carol-as-anna.zip", as_anna)
    with anna:
        ws = bundle.import_project(f, tmp_path / "anna-from-carol")
        try:
            assert json.loads(ws.scalar("SELECT ai_providers FROM documents WHERE doc_id=?", (doc,))) == []
            for prov in ("openai", "anthropic"):
                assert access.levels(ws, [doc], provider=prov) == {doc: "local"}, prov
            assert (ws.meta(access.PROVIDERS_RESET) or {}).get("from") == "import"
            assert access.project_info(ws)["providers_reset"]   # shown, shared or not
        finally:
            ws.close_all()


def test_your_own_backup_keeps_a_document_kept_from_anthropic_kept_from_it(abc, tmp_path):
    """The review's case (wave 2): Anna allows only OpenAI for a document (she works through Codex and does not want
    Anthropic to read it), makes a zip of her own project and opens it. The first fix cleared the list, which meant
    the project default, Anthropic: the document became readable by Claude. It must stay kept from Anthropic."""
    from enlens_claims import access, bundle

    anna, ben, carol = abc
    doc = _first_doc(anna)
    with anna:
        access.set_documents(anna.ws, [doc], setting="cloud", allow=["openai"])
        before = access.levels(anna.ws, [doc], provider="anthropic")
        nid = notes.add(anna.ws, doc, *_words(anna, doc), text="Mine")["note_id"]
        f = tmp_path / "anna-all.zip"
        bundle.export_project(anna.ws, f, scope="all")
        ws = bundle.import_project(f, tmp_path / "anna-again")
        try:
            assert before == {doc: "local"}
            assert access.levels(ws, [doc], provider="anthropic") == before
            assert access.levels(ws, [doc], provider="openai") == {doc: "local"}   # narrowed: tick it again
            info = access.project_info(ws)
            assert info["providers_reset"] and info["providers_reset"]["documents"] == 1
            assert ws.scalar("SELECT person_id FROM notes WHERE note_id=?", (nid,)) == anna.id
        finally:
            ws.close_all()


def test_a_move_keeps_what_each_document_allowed_within_this_copys_default(abc, tmp_path, monkeypatch):
    """*Move ENLENS to another computer* opens each project with `import_project` under the same person: a document
    that allowed Anthropic and OpenAI keeps Anthropic (this copy's default) and loses only OpenAI, to tick again; one
    that followed a project default of OpenAI only (dropped with the zip's config) is kept from Anthropic too."""
    from enlens_claims import access, bundle, home

    anna, ben, carol = abc
    with anna:
        docs = [r[0] for r in anna.ws.query("SELECT doc_id FROM documents ORDER BY doc_id")]
        two, by_default = docs[0], docs[1]
        access.set_documents(anna.ws, [two], setting="cloud", allow=["anthropic", "openai"])
        access.set_documents(anna.ws, [by_default], setting="cloud")
        access.set_providers_default(anna.ws, ["openai"])
        assert access.levels(anna.ws, [by_default], provider="anthropic") == {by_default: "local"}
        f = tmp_path / "anna-all.zip"
        bundle.export_project(anna.ws, f, scope="all")
    moved = Person(tmp_path, "Anna moved", monkeypatch)
    with moved:
        home.update_settings({"person_id": anna.id})   # (moving: the person's id comes first)
        ws = bundle.import_project(f, tmp_path / "anna-moved")
        try:
            assert access.levels(ws, [two], provider="anthropic") == {two: "cloud"}
            assert access.levels(ws, [two], provider="openai") == {two: "local"}
            assert access.levels(ws, [by_default], provider="anthropic") == {by_default: "local"}
        finally:
            ws.close_all()


# ---- 8. a removed reading that shares its original file with another ----------------------------------------------
def test_archiving_a_reading_that_shares_its_file_leaves_the_file_to_the_other(abc, tmp_path):
    """A second reading of a file this copy holds (a sync-clash reading, or a colleague's reading of the same file)
    points at the file that is here (sync/merge.py `_document_files`). When a colleague's word removes that reading,
    removed.archive moved the shared file into the archive (deleted after 30 days) and the document that stays lost
    its original."""
    from enlens_claims import removed

    anna, ben, carol = abc
    doc = _first_doc(ben)
    with ben:
        path = Path(ben.ws.scalar("SELECT path FROM documents WHERE doc_id=?", (doc,)))
        assert path.is_file() and path.parent.name == doc
        other = f"{doc}-0f1e2d"
        cols = [r[1] for r in ben.ws._conn().execute("PRAGMA table_info(documents)")]
        with ben.ws.connect() as cx:
            row = dict(zip(cols, cx.execute("SELECT * FROM documents WHERE doc_id=?", (doc,)).fetchone()))
            row.update(doc_id=other, title=(row.get("title") or "") + " (sync clash)", sha1=f"{row['sha1']}~2")
            cx.execute(f"INSERT INTO documents({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                       [row[c] for c in cols])
        with ben.ws.connect() as cx:
            removed.archive(ben.ws, cx, other, anna.id, "Removed by the owner", "removed")
            ben.ws.remove_document(other, why="Removed by the owner")
        assert path.is_file()
        assert Path(ben.ws.scalar("SELECT path FROM documents WHERE doc_id=?", (doc,))) == path
        removed.prune(ben.ws)
        assert path.is_file()


def test_archiving_a_reading_of_its_own_file_still_moves_it(abc):
    """The honest route stays: a document with a file of its own is archived with its file."""
    from enlens_claims import removed

    anna, ben, carol = abc
    doc = _first_doc(ben)
    with ben:
        path = Path(ben.ws.scalar("SELECT path FROM documents WHERE doc_id=?", (doc,)))
        with ben.ws.connect() as cx:
            removed.archive(ben.ws, cx, doc, anna.id, "Removed by the owner", "removed")
        assert not path.exists()
        assert any(removed._folder(ben.ws).rglob(path.name))


# ---- 10. MERGE-3 and a person's own other account (same-person sync) ----------------------------------------------
def test_your_other_account_gets_your_codebook_with_its_drafted_definition(carols):
    """docs/manual/together.md (same-person sync): private work goes between one person's two accounts. The AI's
    draft definition a code took is kept in the codebook's side file (`drafted`): the laptop gets the private codebook
    with that mark. The task and its answer (the passages the AI read) stay on the computer that asked, as for every
    colleague (sharing.LOCAL_TASK_KINDS): the decision taken here is the conservative one, nothing more goes than
    before, and the laptop asks again only on the person's own click."""
    from enlens_claims import codebooks
    from test_same_person_sync import _active_pair

    from enlens_claims import teamcodebooks

    anna, carol, laptop = carols
    with anna:   # (the owner's setting that shares every new codebook with the team: off, so this one is private)
        teamcodebooks.set_share(anna.ws, False)
    for p in (anna, carol, laptop):
        _round(p)
    _active_pair(carol, laptop)
    with carol:
        cb = codebooks.create(carol.ws, "waits", "Waits")
        words = "Residents kept waiting by the home, as the AI drafted it."
        codes = [{"uid": "", "code": "Waiting", "description": words, "group": "", "include": "", "exclude": "",
                  "keywords": [], "examples": [], "ai_draft": {"model": "claude-sonnet-5-5", "at": "2026-11-14",
                                                               "description": words}}]
        codebooks.save(carol.ws, "waits", {**cb, "codes": codes})
        assert sharing.state(carol.ws._conn(), "codebook", "waits")["state"] == "private"
        assert codebooks.drafted_codes(carol.ws, "waits") == 1
        with carol.ws.connect() as cx:
            cx.execute("INSERT INTO tasks(task_id, kind, model, prompt_version, payload_json, status, attempts, "
                       "created_at, access) VALUES ('code_definition:dddddddddddddddd', 'code_definition', 'm', 'v1', "
                       "'{\"code\": \"Waiting\"}', 'done', 1, '2026-11-18T00:00:00+00:00', 'cloud')")
    for p in (carol, laptop, carol, laptop):
        _round(p)
    with laptop:
        assert sharing.exists(laptop.ws._conn(), laptop.ws.root, "codebook", "waits")
        assert codebooks.drafted_codes(laptop.ws, "waits") == 1
        assert not laptop.ws.scalar("SELECT COUNT(*) FROM tasks WHERE kind='code_definition'")
    with anna:
        assert not sharing.exists(anna.ws._conn(), anna.ws.root, "codebook", "waits")


# ---- 11. mixed versions and relays, deterministic (review note on the randomised role tests) ----------------------
@pytest.mark.parametrize("relay_first", [True, False])
def test_proposal_states_agree_in_every_copy_after_a_relayed_take_back(abc, relay_first):
    """Carol proposes to remove a document and takes it back; Ben relays her take-back. Whichever reaches the owner
    first, once everyone has everyone's files, every copy says the same of the proposal: taken back."""
    from test_hunt1_merge import _carol_takes_back

    anna, ben, carol = abc
    pid, own = _carol_takes_back(anna, ben, carol)
    for f in ((ben.send(), own) if relay_first else (own, ben.send())):
        anna.bring_in(f)
    for p, q in ((ben, anna), (carol, anna), (ben, carol), (carol, ben), (anna, ben), (anna, carol)):
        p.bring_in(q.send())
    states = {}
    for p in (anna, ben, carol):
        with p:
            states[p.name] = {x["id"]: x for x in proposals_of(p)}[pid]["state"]
    assert set(states.values()) == {"taken_back"}, states


def proposals_of(p: Person) -> list[dict]:
    from owner_helpers import proposals

    return proposals(p)


def test_a_zip_from_the_version_before_this_hunt_merges_without_loss(abc, tmp_path):
    """Carol's copy runs the version before the hunt: her whole-project zip still holds her `code_definition` task,
    a note of removal she recorded for a third person's note (Anna's, under Carol's own name, as that version noted
    it), and her own shared check. Ben brings it in: her check and her note come; her draft does not; Anna's note,
    which Anna never removed, still reaches Ben from Anna's own file."""
    from owner_helpers import check

    anna, ben, carol = abc
    nid = _note(anna)
    hc = check(carol, "Desalination raises the price of water")
    cnote = _note(carol, "Carol's note")
    with carol:
        sharing.share(carol.ws, [{"kind": "check", "key": hc}])
    f = _forge(carol.send(), tmp_path / "carol-old.zip",
               ("INSERT INTO tasks(task_id, kind, model, prompt_version, payload_json, status, attempts, created_at, "
                "access) VALUES ('code_definition:eeeeeeeeeeeeeeee', 'code_definition', 'm', 'v1', "
                "'{\"code\": \"Mine\"}', 'done', 1, '2026-11-18T00:00:00+00:00', 'cloud')", ()),
               ("INSERT OR REPLACE INTO sync_removed(kind, key, title, at, person_id) VALUES ('note', ?, 'x', ?, ?)",
                (nid, now(), carol.id)))
    ben.bring_in(f)
    ben.bring_in(anna.send())
    with ben:
        assert ben.ws.scalar("SELECT 1 FROM hypotheses WHERE hyp_id=?", (hc,))
        assert ben.ws.scalar("SELECT person_id FROM notes WHERE note_id=?", (cnote,)) == carol.id
        assert ben.ws.scalar("SELECT person_id FROM notes WHERE note_id=?", (nid,)) == anna.id
        assert not ben.ws.scalar("SELECT COUNT(*) FROM tasks WHERE kind='code_definition'")


def test_a_person_file_without_its_counter_from_an_older_copy_is_read_and_a_later_one_too(trio, store_dir):
    """A member on the version before the hunt writes `person.json` without "n" (the counter of its writes). Every
    copy reads it; once that member updates and turns *Keep documents out* on, the new file (with "n") is taken, not
    set aside as older."""
    from enlens_claims.sync import folder, space

    anna, carol, dan = trio
    with carol:
        mine = space.mirror_of(carol.ws) / folder.team_name(carol.ws) / carol.id / "person.json"
        pj = json.loads(mine.read_text(encoding="utf-8"))
        pj.pop("n", None)
        mine.write_text(json.dumps(pj), encoding="utf-8")
    _round(carol)
    _round(anna)
    with carol:
        folder.set_keep_out(carol.ws, True)
    _round(carol)
    _round(anna)
    with anna:
        team = space.mirror_of(anna.ws) / folder.team_name(anna.ws)
        st = folder.keep_out_state(anna.ws, team)
    assert st["in_force"] and "Carol" in st["colleagues"]


# ---- 12. the trade-offs phase 1 made, each stated --------------------------------------------------------------
def test_your_own_old_backup_with_a_removal_you_no_longer_hold_is_refused_and_says_what_to_do(abc, tmp_path):
    """Anna (owner) removes a document and adds it back; then she brings in her own older backup, which still holds
    her note of the removal. The note is not taken (MERGE-1: a file cannot act in your name), and the Team tab lists it
    with words that say what to do (ownership.refused): the document stays, and to remove it she uses its menu."""
    from enlens_claims import ownership
    from owner_helpers import add_doc, has

    anna, ben, carol = abc
    doc = add_doc(anna, tmp_path, "interview")
    with anna:
        anna.ws.remove_document(doc, why="Out of scope")
    backup = anna.send()
    (tmp_path / "again").mkdir()
    assert add_doc(anna, tmp_path / "again", "interview") == doc   # added again: the same document
    anna.bring_in(backup)
    assert has(anna, doc)
    with anna:
        rows = [r for r in ownership.refused(anna.ws._conn()) if r["kind"] == "removal"]
    assert rows, "the refused removal is listed"
    text = rows[0]["text"]
    assert "Documents" in text and "remove" in text.lower(), text
    assert "You did not" not in text, text   # (it may well be the person's own earlier word)


def test_a_genuine_relayed_take_back_is_not_shown_as_a_problem(abc):
    """Ben relays Carol's genuine take-back before her own file reaches the owner: it waits for her file, and the
    Team tab lists nothing refused (it is not a change in the owner's name, nor a problem)."""
    from enlens_claims import ownership
    from test_hunt1_merge import _carol_takes_back

    anna, ben, carol = abc
    pid, own = _carol_takes_back(anna, ben, carol)
    anna.bring_in(ben.send())
    with anna:
        v = ownership.view(anna.ws)
    assert not v["refused"] and not v["notices"]
    assert pid not in {p["id"] for p in v["proposals"] if p["state"] == "waiting" and p["can_decide"]}


def test_a_genuine_relayed_review_comes_and_is_not_shown_as_a_problem(abc):
    """Anna accepts a label; Carol has it from Anna's file and relays it to Ben: it comes into Ben's copy (labelled as
    relayed until Anna's own file) and nothing is listed as refused."""
    from enlens_claims import ownership, profile

    anna, ben, carol = abc
    doc = _first_doc(anna)
    with anna:
        pid = anna.ws.scalar("SELECT passage_id FROM passages WHERE doc_id=? ORDER BY seq LIMIT 1", (doc,))
        lid = profile.add_label(anna.ws, "sdg", pid, "6.4")
        profile.set_label(anna.ws, lid, "accept")
    carol.bring_in(anna.send())
    ben.bring_in(carol.send())
    with ben:
        assert ben.ws.scalar("SELECT COUNT(*) FROM reviews WHERE item_kind='label' AND item_id=? AND person_id=?",
                             (lid, anna.id)) == 1
        assert not ownership.view(ben.ws)["refused"]


def test_the_team_tab_says_what_to_do_about_a_refused_removal(tmp_path):
    """The card the Team tab draws for that refused removal (owner-state.js `refusedWords`): it said only "held a
    change in your name. It was not taken, and your own word was sent again"; it now says which document, that it
    stays, and how to remove it."""
    import os
    import shutil
    import subprocess

    if shutil.which("node") is None:
        pytest.skip("Node is not installed")
    static = Path(__file__).resolve().parents[1] / "src" / "enlens_claims" / "gui" / "static" / "views"
    (tmp_path / "package.json").write_text('{"type": "module"}')
    for f in ("owner-state.js", "team-state.js"):
        (tmp_path / f).write_text((static / f).read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "run.mjs").write_text(
        'import * as O from "./owner-state.js";\n'
        'const v = { me: "panna", people: [{ id: "panna", name: "Anna", me: true }] };\n'
        'const say = (kind, held) => O.refusedWords({ kind: "removal", key: kind + "|k1", via: "panna", '
        'what: { kind, key: "k1", title: "Interview", held } }, v).text;\n'
        'console.log(JSON.stringify({ doc: say("document", true), check: say("check", true), '
        'themes: say("themes", true), gone: say("check", false) }));\n', encoding="utf-8")
    out = subprocess.run([shutil.which("node"), str(tmp_path / "run.mjs")], capture_output=True, text=True,
                         env={**os.environ, "TZ": "Europe/Amsterdam"}, timeout=60)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)
    assert "the document “Interview”" in got["doc"] and "menu on Documents" in got["doc"] and "stays" in got["doc"]
    assert "the check “Interview”" in got["check"] and "Delete on its result page" in got["check"]
    assert "Documents" not in got["check"]
    assert "the set of themes" in got["themes"] and "Delete on the Themes page" in got["themes"]
    # (review, wave 2) an item not held here: never "in your copy now"
    assert "in your copy now" not in got["gone"] and "nothing was removed here" in got["gone"], got
    assert all("your own word was sent again" not in t for t in got.values())


# ---- notes/merge.md "Not proven" 5: a note or entry with no author ------------------------------------------------
def test_a_colleagues_note_or_entry_without_an_author_is_shown_as_a_colleagues_and_is_nobodys_to_change(abc, tmp_path):
    """A note and a research-log entry from a colleague's file with no `person_id` (from before 0.14, or a changed
    file) come in, are shown as "a colleague"'s, and Ben can neither change nor remove them; they replace nothing of
    his."""
    from enlens_claims import researchlog

    anna, ben, carol = abc
    doc = _first_doc(carol)
    a, z = _words(carol, doc)
    with ben:
        mine = notes.add(ben.ws, doc, a, z, text="Ben's own")["note_id"]
    forged = _forge(carol.send(), tmp_path / "carol-anon.zip",
                    ("INSERT INTO notes(note_id, doc_id, start, \"end\", quote, text, person_id, created_at) VALUES "
                     "('n00000000000000aa', ?, ?, ?, 'x', 'No author', NULL, ?)", (doc, a, z, now())),
                    ("INSERT INTO notes(note_id, doc_id, start, \"end\", quote, text, person_id, created_at) VALUES "
                     "(?, ?, ?, ?, 'x', 'Taken over', NULL, ?)", (mine, doc, a, z, now())),
                    ("INSERT INTO research_log(entry_id, at, kind, text, person_id) VALUES ('e00000000000000aa', ?, "
                     "'entry', 'No author', NULL)", (now(),)))
    ben.bring_in(forged)
    with ben:
        got = notes.get(ben.ws, "n00000000000000aa")
        assert not got["mine"] and got.get("who") in ("a colleague", None)
        with pytest.raises(PermissionError):
            notes.update(ben.ws, "n00000000000000aa", text="mine now")
        with pytest.raises(PermissionError):
            researchlog.update(ben.ws, "e00000000000000aa", text="mine now")
        assert ben.ws.scalar("SELECT text FROM notes WHERE note_id=?", (mine,)) == "Ben's own"
        assert ben.ws.scalar("SELECT person_id FROM notes WHERE note_id=?", (mine,)) == ben.id


# ---- review of hunt phase 1.5, wave 2 ---------------------------------------------------------------------------
def test_a_copy_made_from_a_zip_with_a_withdrawal_dated_ahead_takes_its_owners_later_share(abc, tmp_path, monkeypatch):
    """The review's case (MERGE15-1): Dan makes his copy from Carol's zip, whose marks say Anna took her shared note
    back in 2999. `import_project` kept the date, so Anna's later re-share never counted in Dan's copy."""
    from enlens_claims import bundle

    anna, ben, carol = abc
    nid = _note(anna)
    carol.bring_in(anna.send())
    forged = _forge(carol.send(), tmp_path / "carol-forged.zip",
                    ("UPDATE shares SET state='withdrawn', at=?, title=NULL WHERE kind='note' AND key=?", (FAR, nid)))
    dan = Person(tmp_path, "Dan", monkeypatch)
    with dan:
        dan.ws = bundle.import_project(forged, tmp_path / "dan-project")
        assert dan.ws.scalar("SELECT at FROM shares WHERE kind='note' AND key=?", (nid,)) < "2100"
    with anna:
        sharing.unshare(anna.ws, [{"kind": "note", "key": nid}])
        sharing.share(anna.ws, [{"kind": "note", "key": nid}])
    dan.bring_in(anna.send())
    assert _state(dan, "note", nid) == "shared"


def test_a_project_that_already_holds_a_mark_dated_ahead_is_mended_once_when_opened(abc):
    """A copy that took a mark dated 2999 before this version: opening the project clamps it (store.py
    `_clamp_share_dates`), so Anna's later share counts."""
    from enlens_claims.store import Workspace

    anna, ben, carol = abc
    nid = _note(anna)
    ben.bring_in(anna.send())
    with ben:
        with ben.ws.connect() as cx:   # as an earlier version left it
            cx.execute("UPDATE shares SET state='withdrawn', at=? WHERE kind='note' AND key=?", (FAR, nid))
        root = ben.ws.root
        ben.ws.close_all()
        ben.ws = Workspace.open(root)
        assert ben.ws.scalar("SELECT at FROM shares WHERE kind='note' AND key=?", (nid,)) < "2100"
    with anna:
        sharing.unshare(anna.ws, [{"kind": "note", "key": nid}])
        sharing.share(anna.ws, [{"kind": "note", "key": nid}])
    ben.bring_in(anna.send())
    assert _state(ben, "note", nid) == "shared"


def _check_of(p: Person, text: str) -> str:
    from owner_helpers import check

    return check(p, text)


@pytest.mark.parametrize("held", [True, False])
def test_a_refused_removal_of_a_check_is_worded_for_a_check(abc, tmp_path, held):
    """MERGE15-17 after review: a file that says it is Anna's own holds her note that she removed a check. Its words
    name a check and where a check is deleted, and say "in your copy now" only when the check is here."""
    from enlens_claims import ownership

    anna, ben, carol = abc
    hid = _check_of(anna, "Desalination raises the price of water")
    if not held:
        with anna:
            with anna.ws.connect() as cx:
                cx.execute("DELETE FROM hypotheses WHERE hyp_id=?", (hid,))

    def as_anna(work: Path, cx: sqlite3.Connection, meta: dict) -> None:
        cx.execute("INSERT OR REPLACE INTO sync_removed(kind, key, title, at, person_id) VALUES ('check', ?, "
                   "'Desalination raises the price of water', ?, ?)", (hid, now(), anna.id))
        meta["from"] = {"id": anna.id, "name": "Anna"}

    anna.bring_in(_rezip(carol.send(), tmp_path / "carol-as-anna.zip", as_anna))
    with anna:
        rows = [r for r in ownership.refused(anna.ws._conn()) if r["kind"] == "removal"]
    assert rows
    text = rows[0]["text"]
    assert "the check" in text and "Documents" not in text, text
    if held:
        assert "in your copy now" in text and "Delete on its result page" in text, text
    else:
        assert "in your copy now" not in text and "nothing was removed here" in text, text


def test_a_member_who_left_the_space_is_no_longer_a_signer_and_their_marks_are_relayed(trio):
    """MERGE15-3 after review (the removed-member case, settled): once Anna removes Dan, Dan is no longer among the
    space's signers, and a mark in his name is taken from anyone's file again. Refusing it would be unsound: his
    honest marks made while he was a member reach a copy that had not read them only through others now (his part is
    no longer read), so refusing them would lose an item he shared or bring one he took back."""
    from enlens_claims.sync import space

    anna, carol, dan = trio
    with dan:
        part = space.configured(dan.ws)["part"]
    with carol:
        assert dan.id in sharing.signers(carol.ws)
    with anna:
        space.remove_member(anna.ws, part)
    for p in (anna, carol):
        _round(p, ok_kinds=("documents", "set_aside"))
    with carol:
        signed = sharing.signers(carol.ws)
        assert dan.id not in signed and anna.id in signed
        with carol.ws.connect() as cx:
            got = sharing.receive(cx, "check", "hdan00000001", {"state": "withdrawn", "owner": dan.id, "by": dan.id,
                                                                "at": now(), "title": None},
                                  carol.id, False, had=False, sender=anna.id, first_hand=True, signed=signed)
    assert got == "withdrawn"


def test_an_item_relayed_in_a_storage_space_before_its_owner_wrote_it_there_arrives_shared(trio, tmp_path):
    """Note 6a of the review: Dan shares a check and gives it to Anna in a zip, but never writes it in the space; Anna's
    round relays it. Carol's copy kept it as Dan's private placeholder, which only Dan's own file could lift: lost for
    good once Dan is removed. A relayed Share of an item new to a copy is taken."""
    from enlens_claims import bundle
    from enlens_claims.sync import space

    anna, carol, dan = trio
    hd = _check(dan, "Hydrogen storage is cheap.")
    with dan:
        sharing.share(dan.ws, [{"kind": "check", "key": hd}])
        part = space.configured(dan.ws)["part"]
        f = tmp_path / "dan-shared.zip"
        bundle.export_project(dan.ws, f, scope="shared")
    anna.bring_in(f)
    with anna:
        space.remove_member(anna.ws, part)
    for p in (anna, carol):
        _round(p, ok_kinds=("documents", "set_aside"))
    with carol:
        assert _has(carol.ws, hd)
    assert _state(carol, "check", hd) == "shared"


def test_a_zip_brought_by_hand_in_a_space_project_says_why_a_members_unshare_waits(trio, tmp_path):
    """Note 6b of the review: in a project with a storage space a zip brought by hand is not signed, so a member's
    Unshare in it waits for that member's own signed file; the bring-in report says so (it said nothing), and the next
    round of the space brings it."""
    from enlens_claims.sync import report

    anna, carol, dan = trio
    hd = _check(dan, "Hydrogen storage is cheap.")
    with dan:
        sharing.share(dan.ws, [{"kind": "check", "key": hd}])
    for p in (dan, anna):
        _round(p)
    assert _state(anna, "check", hd) == "shared"
    with dan:
        sharing.unshare(dan.ws, [{"kind": "check", "key": hd}])
    r = anna.bring_in(dan.send())
    assert _state(anna, "check", hd) == "shared"
    assert r["shares"].get("unsigned") == 1
    assert any("signed files" in line for line in report.summary(r)), report.summary(r)
    for p in (dan, anna):
        _round(p)
    assert _state(anna, "check", hd) == "withdrawn"


def test_an_unreadable_record_of_the_spaces_members_takes_no_relayed_mark(trio):
    """Note 6c of the review: `sharing.signers` failed open (an unreadable `.space-state.json` gave the plain relay
    rules). It fails closed: everyone counts as a signer until the record reads again."""
    from enlens_claims.sync import space

    anna, carol, dan = trio
    with carol:
        f = space.mirror_of(carol.ws) / ".space-state.json"
        good = f.read_bytes()
        f.write_text("{ not json", encoding="utf-8")
        try:
            signed = sharing.signers(carol.ws)
            assert dan.id in signed and "anyone" in signed and signed
            assert not sharing.trusted(dan.id, anna.id, True, signed)
            assert sharing.trusted(dan.id, dan.id, True, signed)
        finally:
            f.write_bytes(good)
        assert sharing.signers(carol.ws) == {anna.id, carol.id, dan.id}


def test_archiving_in_a_large_project_resolves_only_paths_of_the_same_file_name(abc, monkeypatch):
    """Note 6d of the review: `removed._used_by_another` resolved every other document's path for each document
    archived (quadratic in a bulk removal, inside the write transaction). With 300 other documents it resolves at
    most the paths that share the file's name."""
    from enlens_claims import removed

    anna, ben, carol = abc
    doc = _first_doc(ben)
    with ben:
        cols = [r[1] for r in ben.ws._conn().execute("PRAGMA table_info(documents)")]
        with ben.ws.connect() as cx:
            row = dict(zip(cols, cx.execute("SELECT * FROM documents WHERE doc_id=?", (doc,)).fetchone()))
            for i in range(300):
                r = {**row, "doc_id": f"dz{i:09d}", "sha1": f"{i:040x}", "path": f"/nowhere/other-{i}.txt"}
                cx.execute(f"INSERT INTO documents({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                           [r[c] for c in cols])
        calls = []
        real = Path.resolve

        def counting(self, *a, **k):
            calls.append(str(self))
            return real(self, *a, **k)

        monkeypatch.setattr(Path, "resolve", counting)
        with ben.ws.connect() as cx:
            assert not removed._used_by_another(cx, doc, Path(row["path"]))
        monkeypatch.setattr(Path, "resolve", real)
    assert len(calls) <= 3, len(calls)
