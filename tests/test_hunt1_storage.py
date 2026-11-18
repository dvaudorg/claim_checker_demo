"""Bug hunt, phase 1 (18 November 2026), area `storage`: the shared folder, a team's storage space and the services
under it. Each test asserts what ENLENS should do, and fails today for the reason in its docstring."""
from __future__ import annotations

import contextlib
import json
from pathlib import Path

import pytest

from enlens_claims.sync import folder, space
from test_app import api, home  # noqa: F401  (fixtures)
from test_shared_folder import _check as _check_folder, _round as _round_folder, pair, shared_dir  # noqa: F401
from test_shared_projects import Person, anna_and_ben  # noqa: F401  (fixture)
from test_storage_space import (_check, _has, _join_new, _round, _share, owner, store_dir,  # noqa: F401  (fixtures)
                                team)


def _space_dir(p: Person, store: Path) -> Path:
    with p:
        return store / space.configured(p.ws)["prefix"]


def _part_of(p: Person) -> str:
    with p:
        return space.configured(p.ws)["part"]


def test_an_old_person_file_put_back_does_not_turn_a_colleagues_keep_out_switch_off(team, store_dir):
    """A colleague's person.json put back in the space (the storage, or a member who can write there) is taken although
    it is older than the one read before: their "keep documents out" switch reads as off again (space.py:1306, only
    head.json is checked for age), so this copy writes words the team agreed to keep out."""
    anna, carol = team
    for p in (anna, carol, anna, carol):
        _round(p)
    f = _space_dir(carol, store_dir) / "parts" / _part_of(carol) / "m" / "person.json"
    old = f.read_bytes()                 # Carol's person.json while her switch was off
    with carol:
        folder.set_keep_out(carol.ws, True)
    _round(carol)
    _round(anna)
    with anna:
        team_dir = space.mirror_of(anna.ws) / folder.team_name(anna.ws)
        assert folder.keep_out_state(anna.ws, team_dir)["in_force"]   # Anna's copy saw Carol turn it on
    f.write_bytes(old)                   # the older file, signed by Carol, put back
    _round(anna)
    with anna:
        st = folder.keep_out_state(anna.ws, team_dir)
    assert st["in_force"] and st["colleagues"] == ["Carol"]


def test_the_owner_trying_their_own_invite_link_keeps_their_team_working(team):
    """The owner pastes an invite link of their own team under Join a team on their own computer: the new project's
    keys replace the owner's own in the keychain (space.py:997, named by the space alone), so the owner's first project
    signs with keys nobody knows and the colleague sets all its new work aside."""
    anna, carol = team
    for p in (anna, carol, anna, carol):
        _round(p)
    with anna:
        inv = space.invite(anna.ws, "test")
        with contextlib.suppress(space.SpaceProblem):   # (or refused: either way the first project must go on working)
            space.join_new_project(inv["link"])
    h = _check(anna, "Fuel cells need platinum.")
    _share(anna, "check", h)
    _round(anna, ok_kinds=("documents", "set_aside"))
    _round(carol, ok_kinds=("documents", "set_aside"))
    with carol:
        assert _has(carol.ws, h)


def _rewrite_bundle_json(f: Path, change) -> None:
    """A colleague's bundle with its description changed (as a damaged or odd copy might write it)."""
    import zipfile

    with zipfile.ZipFile(f) as zf:
        members = {n: zf.read(n) for n in zf.namelist()}
    meta = json.loads(members["bundle.json"])
    change(meta)
    members["bundle.json"] = json.dumps(meta).encode()
    with zipfile.ZipFile(f, "w", zipfile.ZIP_DEFLATED) as zf:
        for n, data in members.items():
            zf.writestr(n, data)


def test_a_colleagues_bundle_with_an_odd_description_stops_only_their_stream(pair, shared_dir):  # noqa: F811
    """A colleague's bundle whose description names its writer as plain text instead of {"id", "name"} raises
    AttributeError in folder._bundle_meta (folder.py:1680); `_withdrawals_first` and `status` catch only _Stop, so every
    round and the Team tab of every copy fail instead of leaving that one bundle aside."""
    from enlens_claims import sharing

    anna, ben = pair
    with anna:
        h = _check_folder(anna.ws, "Electrolysers create local jobs.")
        sharing.share(anna.ws, [{"kind": "check", "key": h}])
    seq = _round_folder(anna)["wrote"]["seq"]
    f = next(shared_dir.glob("ENLENS-*")) / anna.id / "bundles" / f"{seq:06d}.zip"
    _rewrite_bundle_json(f, lambda m: m.update({"from": "Anna"}))
    with ben:
        out = folder.sync_now(ben.ws)            # must not raise
        st = folder.status(ben.ws)               # the Team tab must open
    assert [(x["kind"], x["person"]["id"]) for x in out["problems"]] == [("damaged", anna.id)]
    assert st["people"]


def test_an_invite_link_of_an_unexpected_shape_is_refused_in_words(api):  # noqa: F811
    """An invite link that is whole but lacks the project's id (made by another version, or edited) passes
    `space.parse_link` and then raises KeyError in `_join_unlocked` (space.py:967): Join a team answers 404 "Not found:
    'uid'" instead of saying the link is damaged or from a newer ENLENS."""
    payload = {"v": 1, "space": {"id": "0123456789abcdef", "service": "dir", "dir": "/nowhere", "prefix": "enlens/x/"},
               "part": "m0123456789ab", "access": {}, "join": "AAAA", "keys": {"names": "AAAA", "epochs": {"1": "AAAA"}},
               "keeper": {"part": "m0123456789ab", "sign": "AAAA"}, "project": {"name": "Theirs"}}
    st, r = api("POST", "/api/join-team", {"link": space._link(payload)})
    assert st == 400 and "invite link" in r["error"]


def test_an_old_head_from_before_a_colleague_started_afresh_put_back_is_set_aside(team, store_dir):
    """A colleague's head.json from before they started afresh (another epoch), put back in the space, is taken: the
    age check compares only heads of the same epoch (space.py:1332 `_older_head`), so every copy waits for bundles that
    were removed long ago, and keeps waiting until that colleague writes again."""
    from enlens_claims import sharing

    anna, carol = team
    for p in (anna, carol, anna, carol):
        _round(p)
    hc = _check(carol, "Hydrogen storage is cheap.")
    _share(carol, "check", hc)
    _round(carol)
    _round(anna)
    f = _space_dir(carol, store_dir) / "parts" / _part_of(carol) / "m" / "head.json"
    old = f.read_bytes()                       # Carol's head before she starts afresh
    with carol:
        sharing.unshare(carol.ws, [{"kind": "check", "key": hc}])   # taken back: her copy starts afresh (a new epoch)
    _round(carol)
    _round(anna)
    with anna:
        assert anna.ws.scalar("SELECT epoch FROM sync_folder_read WHERE person_id=?", (carol.id,))
    f.write_bytes(old)                         # the old head, signed by Carol, put back
    with anna:
        out = folder.sync_now(anna.ws)         # (the last line says what is wrong, not `_round`'s own check)
    assert not [x for x in out["problems"] if (x.get("person") or {}).get("id") == carol.id]


# ---------------------------------------------------------------------------------------------
# siblings found while fixing (each failed before its fix)
# ---------------------------------------------------------------------------------------------
def test_joining_a_space_another_project_here_works_in_is_refused_in_words(team):
    """STORAGE-2, both *Join a team* routes: a new project for the link, and a project of this computer that is not the
    one in the space. Refused before anything is written, naming the project to open instead; the owner's own keys stay
    as they were."""
    from enlens_claims import home, keychain

    anna, _carol = team
    with anna:
        sid = space.configured(anna.ws)["id"]
        mine = keychain.get(space._secret_name(sid, "me"))
        inv = space.invite(anna.ws, "test")
        before = home.list_projects()
        with pytest.raises(space.SpaceProblem) as e:
            space.join_new_project(inv["link"])
        assert "Open that project" in str(e.value) and Path(anna.ws.root).name in str(e.value)
        assert home.list_projects() == before                      # no project was made for it
        other = home.create_project("Another project")
        with pytest.raises(space.SpaceProblem):
            space.join(other, inv["link"])
        assert space.configured(other) is None
        assert keychain.get(space._secret_name(sid, "me")) == mine


def test_leaving_the_space_in_one_project_keeps_the_keys_another_project_here_uses(team):
    """STORAGE-2: two projects of one computer that came to share a space before the refusal: *Stop using the storage
    space* in one must not delete the keychain entries the other still works with."""
    from enlens_claims import home, keychain

    anna, carol = team
    with anna:
        desc = space.configured(anna.ws)
        twin = home.create_project("Twin")
        folder._set_config(twin, **{space.CONFIG: desc})
        space.leave(twin)
        assert keychain.get(space._secret_name(desc["id"], "me")) is not None
    for p in (anna, carol, anna):
        _round(p)


def test_an_old_person_file_put_back_after_the_file_went_is_still_set_aside(team, store_dir):
    """STORAGE-1: the copy of a colleague's person.json in the mirror goes when the file goes from the space; an older
    one put back afterwards must still be known as older (the record of what was taken is kept apart)."""
    anna, carol = team
    for p in (anna, carol, anna, carol):
        _round(p)
    f = _space_dir(carol, store_dir) / "parts" / _part_of(carol) / "m" / "person.json"
    old = f.read_bytes()
    with carol:
        folder.set_keep_out(carol.ws, True)
    _round(carol)
    _round(anna)
    f.unlink()                           # the file goes from the space ...
    _round(anna)
    f.write_bytes(old)                   # ... and the older one comes back
    _round(anna)
    with anna:
        team_dir = space.mirror_of(anna.ws) / folder.team_name(anna.ws)
        st = folder.keep_out_state(anna.ws, team_dir)
    assert st["in_force"] and st["colleagues"] == ["Carol"]


def _sealed_into_space(p: Person, store: Path, leaf: str, obj: dict) -> None:
    """A small file written into p's part of the space, sealed and signed by p (as a copy of another version might)."""
    with p:
        desc = space.configured(p.ws)
        ctx = space._Ctx(p.ws, desc)
        data = ctx.sealed(json.dumps(obj).encode(), f"{p.id}/{leaf}")
    (store / desc["prefix"] / "parts" / desc["part"] / "m" / leaf).write_bytes(data)


def test_a_colleagues_head_with_an_endless_number_stops_nothing(team, store_dir):
    """STORAGE-3: a colleague's head.json whose number is 1e999 (JSON reads it as infinity) raised OverflowError in
    `_older_head` (int(inf)), which no round catches: every copy's round failed."""
    anna, carol = team
    for p in (anna, carol, anna, carol):
        _round(p)
    with carol:
        head = json.loads((space.mirror_of(carol.ws) / folder.team_name(carol.ws) / carol.id / "head.json").read_text())
    _sealed_into_space(carol, store_dir, "head.json", {**head, "last": float("inf")})
    with anna:
        folder.sync_now(anna.ws)          # must not raise
        assert folder.status(anna.ws)["people"] is not None


def test_a_roster_with_an_endless_number_put_in_the_space_stops_nothing(team, store_dir):
    """STORAGE-3: the storage service (no key needed) puts a roster whose number is 1e999: `_read_roster` raised
    OverflowError before its signature was checked, and the round failed. It is set aside like any roster that is not
    the keeper's."""
    anna, _carol = team
    _round(anna)
    f = _space_dir(anna, store_dir) / "space" / "roster.json"
    f.write_text(json.dumps({"seq": float("inf"), "sig": "x", "signed_by": "y", "members": {}}))
    _round(anna, ok_kinds=("documents", "set_aside"))


def _shared_bundle(anna: Person, shared_dir: Path) -> Path:
    from enlens_claims import sharing

    with anna:
        h = _check_folder(anna.ws, "Electrolysers create local jobs.")
        sharing.share(anna.ws, [{"kind": "check", "key": h}])
    seq = _round_folder(anna)["wrote"]["seq"]
    return next(shared_dir.glob("ENLENS-*")) / anna.id / "bundles" / f"{seq:06d}.zip"


def test_a_colleagues_bundle_needing_an_endless_format_stops_only_their_stream(pair, shared_dir):  # noqa: F811
    """STORAGE-3: "sync_needs": 1e999 in a bundle's description raised OverflowError in formats.of, through
    `_withdrawals_first`, so the whole round failed."""
    anna, ben = pair
    f = _shared_bundle(anna, shared_dir)
    _rewrite_bundle_json(f, lambda m: m.update({"sync_needs": float("inf")}))
    with ben:
        out = folder.sync_now(ben.ws)
        st = folder.status(ben.ws)
    assert [(x["kind"], x["person"]["id"]) for x in out["problems"]] == [("damaged", anna.id)]
    assert st["people"]


def test_a_colleagues_bundle_with_a_number_for_its_documents_is_damaged(pair, shared_dir):  # noqa: F811
    """STORAGE-3: "documents": 5 (not a list) failed later, as an error of the merge; it is a damaged bundle."""
    anna, ben = pair
    f = _shared_bundle(anna, shared_dir)
    _rewrite_bundle_json(f, lambda m: m.update({"documents": 5}))
    with ben:
        out = folder.sync_now(ben.ws)
    assert [(x["kind"], x["person"]["id"]) for x in out["problems"]] == [("damaged", anna.id)]


def test_a_colleagues_head_with_an_endless_number_in_a_shared_folder_stops_nothing(pair, shared_dir):  # noqa: F811
    """STORAGE-3: the same head.json in a plain shared folder raised OverflowError in `_withdrawals_first`."""
    anna, ben = pair
    _shared_bundle(anna, shared_dir)
    f = next(shared_dir.glob("ENLENS-*")) / anna.id / "head.json"
    f.write_text(json.dumps({**json.loads(f.read_text()), "last": float("inf")}))
    with ben:
        folder.sync_now(ben.ws)           # must not raise
        assert folder.status(ben.ws)["people"]


def test_a_colleagues_bundle_whose_shares_table_lacks_a_column_stops_nothing(pair, shared_dir, tmp_path):  # noqa: F811
    """STORAGE-3 (the hunter's note): a bundle's rows.sqlite whose `shares` has no "kind" column raised KeyError in
    `_withdrawals_first`, which catches only _Stop, OSError and sqlite3.Error: every round failed."""
    import sqlite3
    import zipfile

    anna, ben = pair
    f = _shared_bundle(anna, shared_dir)
    with zipfile.ZipFile(f) as zf:
        members = {n: zf.read(n) for n in zf.namelist()}
    db = tmp_path / "rows.sqlite"
    db.write_bytes(members["rows.sqlite"])
    cx = sqlite3.connect(db)
    cx.execute("ALTER TABLE shares RENAME COLUMN kind TO sort")
    cx.commit()
    cx.close()
    members["rows.sqlite"] = db.read_bytes()
    with zipfile.ZipFile(f, "w", zipfile.ZIP_DEFLATED) as zf:
        for n, data in members.items():
            zf.writestr(n, data)
    with ben:
        folder.sync_now(ben.ws)           # must not raise
        assert folder.status(ben.ws)["people"]



@pytest.mark.parametrize("seq", [1, 0])   # (1: the bundle is whole, `_asked_to_begin_again`; 0: `_mend_readings`)
def test_a_colleagues_waiting_note_with_a_number_for_its_readings_stops_nothing(pair, shared_dir, seq):  # noqa: F811
    """STORAGE-3: a colleague's waiting.json whose "readings" is a number, not a list, raised TypeError in the writer's
    own round (`_asked_to_begin_again`, `_mend_readings`): the writer could no longer write anything."""
    anna, ben = pair
    f = _shared_bundle(anna, shared_dir)
    team = f.parents[2]
    head = json.loads((team / anna.id / "head.json").read_text())
    (team / ben.id).mkdir(exist_ok=True)
    (team / ben.id / "waiting.json").write_text(json.dumps(
        {anna.id: {"seq": head["last"] if seq else 0, "kind": "documents", "epoch": head["epoch"], "readings": 5}}))
    with anna:
        folder.sync_now(anna.ws)          # must not raise


def test_an_invite_link_whose_sender_is_plain_text_is_refused_in_words():
    """STORAGE-5: "from" as plain text passed `parse_link`; `peek` (what the dialog shows before joining) then raised
    AttributeError."""
    payload = {"v": 1, "space": {"id": "0123456789abcdef", "service": "dir", "dir": "/nowhere", "prefix": "enlens/x/"},
               "part": "m0123456789ab", "access": {}, "join": "AAAA", "keys": {"names": "AAAA", "epochs": {"1": "AAAA"}},
               "keeper": {"part": "m0123456789ab", "sign": "AAAA"}, "project": {"uid": "u", "name": "Theirs"},
               "from": "Anna"}
    with pytest.raises(space.SpaceProblem):
        space.peek(space._link(payload))


def test_a_drive_answering_sharing_in_an_odd_shape_is_a_problem_in_words(monkeypatch):
    """STORAGE-3 (the hunter's note): a drive whose sharing answer holds "meta" as text raised AttributeError in
    `webdav._ocs` instead of saying the answer was not understood."""
    from enlens_claims.sync import _web, webdav

    monkeypatch.setattr(_web, "send_retrying", lambda *a, **k: _web.Reply(200, {}, b'{"ocs": {"meta": "x"}}'))
    with pytest.raises(webdav.WebDAVProblem):
        webdav.unshare("https://drive.example.org/remote.php/dav/files/anna/", "anna", "pw", "7")
