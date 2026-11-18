"""Bug hunt, phase 1 (18 November 2026), area `storage`: the shared folder, a team's storage space and the services
under it. Each test asserts what ENLENS should do, and fails today for the reason in its docstring."""
from __future__ import annotations

import json
from pathlib import Path

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
        space.join_new_project(inv["link"])   # (or refused: either way the first project must go on working)
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
    out = _round(anna, ok_kinds=("documents", "set_aside"))
    assert not [x for x in out["problems"] if (x.get("person") or {}).get("id") == carol.id]
