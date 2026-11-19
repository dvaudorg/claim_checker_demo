"""Bug hunt, phase 1.5 (19 November 2026), area `storage`: every note, "not proven" and open point that phases 0 and 1
left about the shared folder, a team's storage space, the seal and the services under it. Each test states what
ENLENS should do; the ledger (`.claude/audits/2026-11-19-phase1.5/ledger/storage.md`) says which failed before a fix
and which passed on the code as it was."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from enlens_claims.sync import folder, seal, space
from test_app import api, home  # noqa: F401  (fixtures)
from test_same_person_sync import carols  # noqa: F401  (fixture)
from test_shared_projects import Person, anna_and_ben  # noqa: F401  (fixture)
from test_storage_space import (_check, _has, _join_new, _round, _share, owner, store_dir,  # noqa: F401  (fixtures)
                                team)


def _space_dir(p: Person, store: Path) -> Path:
    with p:
        return store / space.configured(p.ws)["prefix"]


def _part_of(p: Person) -> str:
    with p:
        return space.configured(p.ws)["part"]


def _set_aside(p: Person) -> list[dict]:
    with p:
        return folder.status(p.ws)["space"]["set_aside"]


# ---------------------------------------------------------------------------------------------
# 1, 2: every SealProblem a caller can meet, by its code and by the words a person reads (phase 0's mutation run:
# none was asserted anywhere), and read_signed_json's "no sig" OR "no signed_by"
# ---------------------------------------------------------------------------------------------
NOT_SEALED = "A file in the storage space is not one ENLENS sealed."
DAMAGED = "A file in the storage space is damaged."
NEWER = "A file in the storage space was sealed by a newer ENLENS."
NOT_SIGNED_BY_PART = "A file in the storage space is not signed by the colleague whose part it is in."
ELSEWHERE = "A file in the storage space says it belongs elsewhere."
WRITER = "A file in the storage space was written by someone else than the part's member."
NO_KEY = "A file in the storage space is sealed with a key this copy does not hold (yet)."
SIGNED_UNREADABLE = "A signed file of the space cannot be read."
NOT_SIGNED = "A file of the space is not signed."


@pytest.fixture
def sealed():
    """One sealed file, as a colleague's copy writes it, and what opens it."""
    ident, key = seal.Identity.new(), seal.new_key()
    blob = seal.seal(b"hello", path="p0123456789ab/head.json", by="m0123456789ab", epoch=3, key=key, ident=ident)
    return {"ident": ident, "key": key, "blob": blob, "pub": ident.public()["sign"]}


def _problem(fn, *a, **kw) -> tuple[str, str]:
    with pytest.raises(seal.SealProblem) as e:
        fn(*a, **kw)
    return e.value.why, str(e.value)


def _with_header(blob: bytes, header: bytes) -> bytes:
    import struct

    return seal.MAGIC + struct.pack(">I", len(header)) + header + b"\0" * 80


def test_each_problem_of_a_sealed_file_has_its_code_and_its_words(sealed, monkeypatch):
    b, pub, key = sealed["blob"], sealed["pub"], sealed["key"]
    where = {"path": "p0123456789ab/head.json", "by": "m0123456789ab"}
    # what the file says it is
    assert _problem(seal.header, b"PK\x03\x04" + b"\0" * 100) == ("format", NOT_SEALED)
    assert _problem(seal.header, seal.MAGIC + b"\0\0") == ("format", NOT_SEALED)            # (shorter than a seal)
    assert _problem(seal.header, seal.MAGIC + b"\xff\xff\xff\xff" + b"\0" * 80) == ("damaged", DAMAGED)
    assert _problem(seal.header, _with_header(b, b"{not json")) == ("damaged", DAMAGED)
    assert _problem(seal.header, _with_header(b, b'{"path": "x"}')) == ("damaged", DAMAGED)  # (no writer, epoch…)
    newer = json.dumps({"v": 2, "path": "x", "by": "y", "e": 1, "n": seal.b64(b"\0" * 12)}).encode()
    assert _problem(seal.header, _with_header(b, newer)) == ("format", NEWER)
    # whose it is, where it belongs, which key
    other = seal.Identity.new().public()["sign"]
    assert _problem(seal.verify, b, other) == ("signature", NOT_SIGNED_BY_PART)
    assert _problem(seal.open_sealed, b, **{**where, "path": "p0123456789ab/person.json"}, sign_pub=pub,
                    keys={3: key}) == ("place", ELSEWHERE)
    assert _problem(seal.open_sealed, b, **{**where, "by": "m999999999999"}, sign_pub=pub,
                    keys={3: key}) == ("writer", WRITER)
    assert _problem(seal.open_sealed, b, **where, sign_pub=pub, keys={2: key}) == ("key", NO_KEY)
    assert _problem(seal.open_unverified, b, {2: key}) == ("key", NO_KEY)
    # signed and in its place, but sealed with another key of that epoch (or more than ENLENS reads)
    assert _problem(seal.open_sealed, b, **where, sign_pub=pub, keys={3: seal.new_key()}) == ("damaged", DAMAGED)
    assert _problem(seal.open_unverified, b, {3: seal.new_key()}) == ("damaged", DAMAGED)

    class _Huge:
        def __init__(self, _k):
            pass

        def decrypt(self, *_a):
            raise OverflowError("more than 2 GB")

    monkeypatch.setattr(seal, "AESGCM", _Huge)
    assert _problem(seal.open_sealed, b, **where, sign_pub=pub, keys={3: key}) == \
        ("damaged", "A file in the storage space is larger than ENLENS reads.")
    monkeypatch.undo()
    assert seal.open_sealed(b, **where, sign_pub=pub, keys={3: key}) == b"hello"   # (and the whole file opens)


def test_each_problem_of_a_signed_list_or_a_sealed_key_has_its_code_and_its_words(sealed, monkeypatch):
    ident = sealed["ident"]
    good = seal.signed_json(ident, {"seq": 4, "members": {}}, "m0123456789ab")
    obj, by, sig = seal.read_signed_json(good)
    assert by == "m0123456789ab" and seal.check_signed(obj, sig, sealed["pub"])
    assert _problem(seal.read_signed_json, b"{cut off") == ("damaged", SIGNED_UNREADABLE)
    whole = json.loads(good)
    # phase 0: the "or" between "no sig" and "no signed_by" could be "and" with no test failing
    assert _problem(seal.read_signed_json, json.dumps({k: v for k, v in whole.items() if k != "sig"}).encode()) == \
        ("signature", NOT_SIGNED)
    assert _problem(seal.read_signed_json, json.dumps({k: v for k, v in whole.items() if k != "signed_by"}).encode()) \
        == ("signature", NOT_SIGNED)
    assert _problem(seal.read_signed_json, json.dumps({**whole, "sig": 5}).encode()) == ("signature", NOT_SIGNED)
    assert _problem(seal.read_signed_json, json.dumps({**whole, "signed_by": None}).encode()) == \
        ("signature", NOT_SIGNED)
    assert _problem(seal.read_signed_json, b"[1, 2]") == ("signature", NOT_SIGNED)
    # a key sealed to someone else, a public key ENLENS cannot use
    for_other = seal.seal_key(seal.Identity.new().public()["box"], b"k" * 32, "space S epoch 1 part P")
    assert _problem(seal.open_key, ident, for_other, "space S epoch 1 part P") == \
        ("key", "A key sealed for this copy cannot be opened.")
    mine = seal.seal_key(ident.public()["box"], b"k" * 32, "space S epoch 1 part P")
    assert _problem(seal.open_key, ident, mine, "space S epoch 2 part P")[0] == "key"     # (bound to its place)
    assert seal.open_key(ident, mine, "space S epoch 1 part P") == b"k" * 32
    assert _problem(seal.sign_public, "AAAA") == ("key", "A member's public key is not one ENLENS can use.")
    # a file larger than ENLENS sends
    monkeypatch.setattr(seal, "MAX_SEALED", 2 * 1024 ** 2)
    assert _problem(seal.seal, b"x" * (2 * 1024 ** 2 + 1), path="p0123456789ab/files/big.pdf", by="m0123456789ab",
                    epoch=1, key=seal.new_key(), ident=ident) == \
        ("too_large", "big.pdf is larger than ENLENS sends to a storage space (2 MB).")


def test_a_private_file_of_ones_other_account_has_its_codes_and_words():
    """selfsync's own wrapper (a private file between one person's two accounts) says what is wrong in words too."""
    from enlens_claims.sync import selfsync

    class Ctx:
        pass

    other = {"sign": seal.Identity.new().public()["sign"], "part": "m0123456789ab", "person": "p0123456789ab"}
    assert _problem(selfsync._open, Ctx(), b"junk", other, "0123456789ab", 1) == \
        ("format", "A private file in the storage space is not one ENLENS sealed.")
    assert _problem(selfsync._open, Ctx(), selfsync.MAGIC + b"\xff\xff\xff\xff", other, "0123456789ab", 1) == \
        ("damaged", "A private file in the storage space is damaged.")
    head = b'{"no": "key"}'
    assert _problem(selfsync._open, Ctx(), selfsync.MAGIC + len(head).to_bytes(4, "big") + head, other,
                    "0123456789ab", 1) == ("damaged", "A private file in the storage space is damaged.")


def test_a_person_reads_on_the_team_tab_why_a_colleagues_file_was_set_aside(team, store_dir):
    """The route a person meets them by: a file in a colleague's part that is not sealed, and one sealed by somebody
    else, are each listed on the Team tab with their code and their words, and the round goes on."""
    anna, carol = team
    for p in (anna, carol, anna, carol):
        _round(p)
    d = _space_dir(anna, store_dir) / "parts" / _part_of(carol)
    (d / "b").mkdir(exist_ok=True)
    (d / "b" / "000097").write_bytes(b"PK\x03\x04 not sealed at all")
    with carol:
        desc = space.configured(carol.ws)
        names, epochs = space._keys(desc["id"])
    stranger = seal.Identity.new()
    (d / "b" / "000098").write_bytes(seal.seal(b"x", path=f"{carol.id}/bundles/000098.zip", by=desc["part"],
                                              epoch=max(epochs), key=epochs[max(epochs)], ident=stranger))
    _round(anna)
    got = sorted((x["why"], x["message"]) for x in _set_aside(anna))
    assert got == [("format", NOT_SEALED), ("signature", NOT_SIGNED_BY_PART)]


@pytest.mark.parametrize("drop", ["sig", "signed_by"])
def test_a_roster_lacking_only_its_signature_or_its_signer_is_set_aside_in_words(team, store_dir, drop):
    """Item 2 by the route a person meets: the storage service (which needs no key) replaces the team's list of members
    by one that lacks only "sig" or only "signed_by". It is set aside with the roster's words, the round goes on, and
    the list read last stays."""
    anna, carol = team
    for p in (anna, carol, anna):
        _round(p)
    f = _space_dir(anna, store_dir) / "space" / "roster.json"
    obj = json.loads(f.read_bytes())
    obj["seq"] = obj["seq"] + 5
    f.write_text(json.dumps({k: v for k, v in obj.items() if k != drop}))
    out = _round(anna, ok_kinds=("documents", "set_aside"))
    assert [x["message"] for x in out["problems"] if x["kind"] == "set_aside"] == [
        "The list of the team's members in the storage space is not signed by the owner who keeps it, or is damaged. "
        "It was set aside; ENLENS goes on with the list it read last."]
    with anna:
        assert sorted(m["name"] for m in folder.status(anna.ws)["space"]["members"]) == ["Anna", "Carol"]


# ---------------------------------------------------------------------------------------------
# 3: the keys handed to a new keeper, with an invite list of an odd shape
# ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize("invites,secrets", [(5, ["x"]), ("abc", "abc"), ({"m0123456789ab": 1}, {"m0123456789ab": 5}),
                                             ([{"part": "m0123456789ab"}], None)])
def test_a_keeper_handover_with_an_odd_invite_list_is_taken(team, monkeypatch, invites, secrets):
    """The keys sealed to the project's new owner (`space/keeper.json`, written by the old keeper's copy, perhaps of
    another version) hold "invites" and "invite_secrets" of a shape this version does not write. `_read_keeper_handover`
    iterated them unchecked: the round's pull stopped at that step with a "set_aside" problem, every round, and the
    new owner never became the keeper."""
    from enlens_claims import ownership

    anna, carol = team
    for p in (anna, carol, anna, carol):
        _round(p)
    real = seal.seal_key

    def odd(box, secret, context):
        if " keeper " in context:
            s = json.loads(secret)
            s["invites"], s["invite_secrets"] = invites, secrets
            secret = json.dumps(s).encode()
        return real(box, secret, context)

    monkeypatch.setattr(seal, "seal_key", odd)
    with anna:
        ownership.hand_over(anna.ws, carol.id)
    _round(anna)
    monkeypatch.setattr(seal, "seal_key", real)
    _round(carol)                                 # (no "set_aside" problem)
    with carol:
        st = folder.status(carol.ws)["space"]
    assert st["keeper"] and st["invites"] == ([{"part": "m0123456789ab", "made_at": None, "label": None}]
                                              if isinstance(invites, list) else [])


# ---------------------------------------------------------------------------------------------
# 4: `.space-state.json` written whole everywhere
# ---------------------------------------------------------------------------------------------
def test_withdrawing_an_invite_never_leaves_the_state_of_the_space_cut_off(team, store_dir, monkeypatch):
    """Withdrawing an invite whose key file was set aside rewrote `.space-state.json` in place (space.py near 936). A
    write cut off there (the disk full, the computer off) left half a file: the next round reads it as nothing, and
    the copy forgets the team's list of members, what it took of each colleague (an older file put back would be
    taken again) and what it set aside."""
    anna, carol = team
    for p in (anna, carol, anna, carol):
        _round(p)
    with anna:
        inv = space.invite(anna.ws, "Dave")
    m = _space_dir(anna, store_dir) / "parts" / inv["part"] / "m"
    m.mkdir(parents=True, exist_ok=True)
    (m / "key.json").write_bytes(b"not a key file")
    _round(anna, ok_kinds=("documents", "set_aside"))
    with anna:
        state = space.mirror_of(anna.ws) / ".space-state.json"
    assert json.loads(state.read_text())["aside"] and json.loads(state.read_text())["taken"]
    real_text, real_bytes = Path.write_text, Path.write_bytes

    def cut_text(self, data, *a, **kw):
        if self.name.startswith(".space-state.json"):
            real_text(self, data[:len(data) // 2], *a, **kw)
            raise OSError(28, "No space left on device")
        return real_text(self, data, *a, **kw)

    def cut_bytes(self, data, *a, **kw):
        if self.name.startswith(".space-state.json"):
            real_bytes(self, data[:len(data) // 2], *a, **kw)
            raise OSError(28, "No space left on device")
        return real_bytes(self, data, *a, **kw)

    monkeypatch.setattr(Path, "write_text", cut_text)
    monkeypatch.setattr(Path, "write_bytes", cut_bytes)
    with anna:
        space.cancel_invite(anna.ws, inv["part"])
    monkeypatch.setattr(Path, "write_text", real_text)
    monkeypatch.setattr(Path, "write_bytes", real_bytes)
    st = json.loads(state.read_text())            # whole: as before, or as after
    assert st["roster"]["members"] and st["taken"]


# ---------------------------------------------------------------------------------------------
# 5: choosing a shared folder never deletes a storage space's keys by a side door
# ---------------------------------------------------------------------------------------------
def test_choosing_a_shared_folder_while_a_storage_space_is_in_use_is_refused_in_words(api, home, tmp_path):  # noqa: F811
    """PUT …/shared-folder in a project with a storage space called `space.leave`, which deletes the keeper's keys
    (the B2 master key, the Cloudflare token) with no way back. The page never offers it; the API must not do it by a
    side door: it is refused, in words, and the keys stay. The page's own *Stop using the storage space here*
    (DELETE …/shared-folder, after the page asks) still leaves the space."""
    from enlens_claims import keychain

    assert api("POST", "/api/projects", {"name": "Demo"})[0] == 200
    ws = home.open_project("Demo")
    (tmp_path / "bucket").mkdir()
    space.setup_dir(ws, tmp_path / "bucket")
    sid = space.configured(ws)["id"]
    mine = keychain.get(space._secret_name(sid, "me"))
    other = tmp_path / "Shared"
    other.mkdir()
    with pytest.raises(folder.FolderProblem) as e:
        folder.set_folder(ws, str(other))
    assert "Stop using the storage space here" in str(e.value)
    st, r = api("PUT", "/api/projects/Demo/shared-folder", {"path": str(other)})
    assert st == 400 and "Stop using the storage space here" in r["error"]
    assert space.configured(ws) is not None and keychain.get(space._secret_name(sid, "me")) == mine
    st, r = api("DELETE", "/api/projects/Demo/shared-folder", {})
    assert st == 200 and space.configured(ws) is None and keychain.get(space._secret_name(sid, "me")) is None
    st, r = api("PUT", "/api/projects/Demo/shared-folder", {"path": str(other)})   # (and then a folder can be chosen)
    assert st == 200 and r["folder"] == str(other.resolve())


# ---------------------------------------------------------------------------------------------
# 6: two projects that came to share one space on one computer before phase 1's refusal
# ---------------------------------------------------------------------------------------------
def test_two_projects_in_one_space_on_one_computer_say_what_to_do_and_spoil_nothing(team, monkeypatch):
    """Before phase 1, a second project here could join the space (the owner trying their own invite link): it
    replaced this computer's keys for the space, and both projects share one copy of the space and one state file.
    Each round of either must spoil nothing (the colleague sets nothing aside, the shared state is not mixed) and say
    plainly what to do."""
    from enlens_claims import home as enlens_home

    anna, carol = team
    for p in (anna, carol, anna, carol):
        _round(p)
    with anna:   # (Anna's project, kept outside the data folder, is in her list of projects)
        enlens_home._save_links({**enlens_home._links(), "Study": str(Path(anna.ws.root).resolve())})
        orig_name = "Study"
    real = space._others_using
    monkeypatch.setattr(space, "_others_using", lambda *_a: [])   # (as an ENLENS before the refusal let it)
    with anna:
        inv = space.invite(anna.ws, "me again")
        twin_name = space.join_new_project(inv["link"])
        twin = enlens_home.open_project(twin_name)
    monkeypatch.setattr(space, "_others_using", real)
    h = _check(anna, "Fuel cells need platinum.")
    _share(anna, "check", h)
    with anna:
        o1, t1 = folder.sync_now(anna.ws), folder.sync_now(twin)
        o2, t2 = folder.sync_now(anna.ws), folder.sync_now(twin)
    for out, other in ((o1, twin_name), (o2, twin_name), (t1, orig_name), (t2, orig_name)):
        said = [x["message"] for x in out["problems"] if x["kind"] == "other_project_here"]
        assert said and other in said[0] and "Stop using the storage space here" in said[0], out["problems"]
    _round(carol)
    assert _set_aside(carol) == []                 # nothing signed with keys the team does not know
    with carol:
        assert sorted(m["name"] for m in folder.status(carol.ws)["space"]["members"]) == ["Anna", "Carol"]


# ---------------------------------------------------------------------------------------------
# 7: a broader replay: everything of a colleague's from before a take-back put back in the space
# ---------------------------------------------------------------------------------------------
def _state(p: Person, h: str) -> str | None:
    """The check's sharing state in p's copy ("shared", "withdrawn", …), None when p does not hold it."""
    from enlens_claims import sharing

    with p:
        return sharing.state(p.ws._conn(), "check", h)["state"] if _has(p.ws, h) else None


def _part_files(p: Person, store: Path) -> dict[Path, bytes]:
    d = _space_dir(p, store) / "parts" / _part_of(p)
    return {f.relative_to(d): f.read_bytes() for f in d.rglob("*") if f.is_file()}


def _put_back(p: Person, store: Path, files: dict[Path, bytes]) -> None:
    d = _space_dir(p, store) / "parts" / _part_of(p)
    for rel, data in files.items():
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / rel).write_bytes(data)


def test_old_bundles_put_back_with_their_old_head_bring_nothing_back(team, store_dir):
    """Carol shares a check and takes it back (her copy starts afresh, her old bundles go from the space); Anna's
    copy keeps it, marked as withdrawn by Carol (docs/manual/together.md, *Unshare*). Every file of her part from
    before, bundles, readings, head.json and person.json, is put back (the storage, a drive's version history, a
    member who can write there): the check must not become shared again in Anna's copy, and Carol's later work still
    arrives."""
    from enlens_claims import sharing

    anna, carol = team
    for p in (anna, carol, anna, carol):
        _round(p)
    hc = _check(carol, "Hydrogen storage is cheap.")
    _share(carol, "check", hc)
    _round(carol)
    _round(anna)
    assert _state(anna, hc) == "shared"
    before = _part_files(carol, store_dir)
    with carol:
        sharing.unshare(carol.ws, [{"kind": "check", "key": hc}])
    _round(carol)
    _round(anna)
    assert _state(anna, hc) == "withdrawn"
    _put_back(carol, store_dir, before)
    for deep in (False, True):
        with anna:
            out = folder.sync_now(anna.ws) if not deep else space.sync_now(anna.ws, deep=True)
        assert not [x for x in out["problems"] if (x.get("person") or {}).get("id") == carol.id], out["problems"]
        assert _state(anna, hc) == "withdrawn"
    h2 = _check(carol, "Fuel cells need platinum.")
    _share(carol, "check", h2)
    _round(carol)
    _round(anna)
    assert _state(anna, h2) == "shared" and _state(anna, hc) == "withdrawn"


# ---------------------------------------------------------------------------------------------
# 8: a colleague still on an older ENLENS: person.json without "n", its time whatever their clock says
# ---------------------------------------------------------------------------------------------
def _sealed_into_space(p: Person, store: Path, leaf: str, obj: dict) -> None:
    """A small file written into p's part of the space, sealed and signed by p (as a copy of another version might)."""
    with p:
        desc = space.configured(p.ws)
        data = space._Ctx(p.ws, desc).sealed(json.dumps(obj).encode(), f"{p.id}/{leaf}")
    (store / desc["prefix"] / "parts" / desc["part"] / "m" / leaf).write_bytes(data)


def _later(at: str, minutes: int) -> str:
    from datetime import datetime, timedelta

    return (datetime.fromisoformat(at) + timedelta(minutes=minutes)).isoformat()


def _never_counted(anna: Person, carol: Person, team_dir: Path, old: dict) -> None:
    """Anna's copy as if Carol had only ever run an older ENLENS: no file of hers with "n" taken (the record of what
    was taken, and the mirror's copy, hold her file without it)."""
    with anna:
        f = space.mirror_of(anna.ws) / ".space-state.json"
    st = json.loads(f.read_text())
    st["taken"][_part_of(carol)].pop("person", None)
    f.write_text(json.dumps(st))
    (team_dir / carol.id / "person.json").write_text(json.dumps(old))


def test_a_colleague_on_an_older_enlens_whose_clock_went_back_still_keeps_documents_out(team, store_dir):
    """An older ENLENS writes person.json without "n", and with whatever time its computer's clock says. Carol's clock
    is put back an hour, then she turns on *Keep documents marked Only a local AI or No AI out*: her new file reads as
    older than the one taken before, and was set aside, so every copy went on writing those documents' words into the
    space. The stricter switch wins (folder.py's docstring: once anyone has it on, those documents stay out); her own
    older file with the switch off, put back, still changes nothing."""
    anna, carol = team
    for p in (anna, carol, anna, carol):
        _round(p)
    with anna:
        team_dir = space.mirror_of(anna.ws) / folder.team_name(anna.ws)
    pj = json.loads((team_dir / carol.id / "person.json").read_text())
    t = pj["updated_at"]
    old = {k: v for k, v in pj.items() if k != "n"}                  # (as an ENLENS before "n" writes it)
    _never_counted(anna, carol, team_dir, old)
    _sealed_into_space(carol, store_dir, "person.json", {**old, "keep_out": False, "updated_at": _later(t, 60)})
    _round(anna)
    _sealed_into_space(carol, store_dir, "person.json", {**old, "keep_out": True, "updated_at": _later(t, 30)})
    _round(anna)
    with anna:
        st = folder.keep_out_state(anna.ws, team_dir)
    assert st["in_force"] and st["colleagues"] == ["Carol"]
    _sealed_into_space(carol, store_dir, "person.json", {**old, "keep_out": False, "updated_at": _later(t, -60)})
    _round(anna)
    with anna:
        assert folder.keep_out_state(anna.ws, team_dir)["in_force"]
    # her switch turned off later by her own clock is taken (a copy never goes back, but it goes on)
    _sealed_into_space(carol, store_dir, "person.json", {**old, "keep_out": False, "updated_at": _later(t, 90)})
    _round(anna)
    with anna:
        assert not folder.keep_out_state(anna.ws, team_dir)["in_force"]


# ---------------------------------------------------------------------------------------------
# 9: three people in a space; one starts afresh twice, another's clock is wrong
# ---------------------------------------------------------------------------------------------
def test_three_people_one_starting_afresh_twice_one_with_a_wrong_clock_end_alike(team, tmp_path, monkeypatch):
    """The storage space's own records (`_older`/`_taken`, "taken" in `.space-state.json`, `.space-project.json`) in
    one deterministic run the randomised tests do not make: Anna (the owner), Carol, who takes back what she shared
    twice (her copy starts afresh twice), and Dave, whose clock is two days behind. In the end every copy holds the
    same shared work, and what Carol took back is withdrawn in each colleague's copy."""
    from enlens_claims import sharing

    anna, carol = team
    dave = Person(tmp_path, "Dave", monkeypatch)
    with anna:
        inv = space.invite(anna.ws, "Dave")
    _join_new(dave, inv["link"])
    real_folder_now, real_space_now = folder.now, space.now

    def as_dave(fn):
        from datetime import datetime, timedelta, timezone

        behind = lambda: (datetime.now(timezone.utc) - timedelta(days=2)).replace(microsecond=0).isoformat()  # noqa
        monkeypatch.setattr(folder, "now", behind)
        monkeypatch.setattr(space, "now", behind)
        try:
            return fn()
        finally:
            monkeypatch.setattr(folder, "now", real_folder_now)
            monkeypatch.setattr(space, "now", real_space_now)

    def everyone():
        for p in (anna, carol, dave):
            if p is dave:
                as_dave(lambda: _round(dave))
            else:
                _round(p)

    everyone()
    everyone()
    ha = _check(anna, "Electrolysers create local jobs.")
    _share(anna, "check", ha)
    hd = _check(dave, "Hydrogen valleys share pipelines.")
    as_dave(lambda: _share(dave, "check", hd))
    carols = []
    for text in ("Hydrogen storage is cheap.", "Fuel cells need platinum.", "Green steel needs hydrogen."):
        h = _check(carol, text)
        carols.append(h)
        _share(carol, "check", h)
        everyone()
        if len(carols) < 3:
            with carol:
                sharing.unshare(carol.ws, [{"kind": "check", "key": h}])   # taken back: her copy starts afresh
            everyone()
    everyone()
    everyone()
    # what Carol took back is marked as withdrawn in every copy, hers too (docs/manual/together.md, *Unshare*)
    want = {ha: "shared", hd: "shared", carols[2]: "shared", carols[0]: "withdrawn", carols[1]: "withdrawn"}
    for p in (anna, carol, dave):
        assert {h: _state(p, h) for h in want} == want, p.name
    for p in (anna, carol, dave):
        with p:
            members = sorted(m["name"] for m in folder.status(p.ws)["space"]["members"])
        assert members == ["Anna", "Carol", "Dave"], (p.name, members)


# ---------------------------------------------------------------------------------------------
# 10: one person's two accounts: a statement whose "last" is not a number
# ---------------------------------------------------------------------------------------------
def test_an_odd_number_in_the_other_accounts_statement_stops_no_shared_work(carols, store_dir):
    """`selfsync`: `int(read.get("last"))` on a statement whose "last" is not a number raises; the round must carry
    on with the team's shared work, and say the private exchange's problem in words."""
    from enlens_claims.sync import selfsync

    anna, carol, laptop = carols
    selfsync_on = (lambda p, o: selfsync.turn_on(p.ws, o.id))
    for p, o in ((carol, laptop), (laptop, carol)):
        with p:
            selfsync_on(p, o)
    for p in (carol, laptop, carol, laptop):
        _round(p)
    with carol:
        stmt = json.loads((space.mirror_of(carol.ws) / folder.team_name(carol.ws) / carol.id / selfsync.FILE)
                          .read_text())
    with laptop:   # (the stream the laptop writes, as its own statement says)
        laptop_stream = json.loads((space.mirror_of(laptop.ws) / folder.team_name(laptop.ws) / laptop.id /
                                    selfsync.FILE).read_text())["stream"]
    for last in ("five", float("inf")):
        stmt = {**stmt, "seq": stmt["seq"] + 1, "read": {"stream": laptop_stream, "last": last}}
        _sealed_into_space(carol, store_dir, selfsync.FILE, stmt)
        ha = _check(anna, f"Electrolysers create local jobs ({last}).")
        _share(anna, "check", ha)
        _round(anna)
        out = _round(laptop, ok_kinds=("documents", "self_sync"))
        with laptop:
            assert _has(laptop.ws, ha)                    # the team's shared work came in
        said = [x["message"] for x in out["problems"] if x["kind"] == "self_sync"]
        assert said and "tried again at the next round" in said[0], out["problems"]


# ---------------------------------------------------------------------------------------------
# 11: Windows: a colleague's file in the copy of the space held open (the Team tab's status) while a round replaces it
# ---------------------------------------------------------------------------------------------
def _new_head_from_carol(anna: Person, carol: Person) -> tuple[str, Path]:
    for p in (anna, carol, anna, carol):
        _round(p)
    hc = _check(carol, "Hydrogen storage is cheap.")
    _share(carol, "check", hc)
    _round(carol)
    with anna:
        return hc, space.mirror_of(anna.ws) / folder.team_name(anna.ws) / carol.id / "head.json"


@pytest.mark.parametrize("refusals", [3, 10 ** 6])
def test_a_round_waits_for_a_file_held_open_a_moment_or_says_so_in_words(team, monkeypatch, refusals):
    """Platform-free, the same logic as the Windows test below: replacing a file in the copy of the space raises
    PermissionError while another reader holds it (Windows). `_mirror_put` tried once, and the round failed with
    PermissionError, which no part of it caught. Now a replace waits a moment and tries again; a file held all along
    is a problem in words, the round goes on, and the next round takes the file."""
    anna, carol = team
    hc, head = _new_head_from_carol(anna, carol)
    real, left = os.replace, [refusals]

    def held(src, dst, *a, **kw):
        if Path(dst) == head and left[0] > 0:
            left[0] -= 1
            raise PermissionError(13, "The process cannot access the file because it is being used by another process")
        return real(src, dst, *a, **kw)

    monkeypatch.setattr(os, "replace", held)
    with anna:
        out = folder.sync_now(anna.ws)           # must not raise
    monkeypatch.setattr(os, "replace", real)
    busy = [x["message"] for x in out["problems"] if x["kind"] == "busy"]
    if refusals == 3:
        assert not busy
        with anna:
            assert _has(anna.ws, hc)
    else:
        assert busy and "tries again on the next round" in busy[0] and "files open" in busy[0]
        _round(anna)
        with anna:
            assert _has(anna.ws, hc)


@pytest.mark.skipif(os.name != "nt", reason="Windows: a file another reader holds open cannot be replaced")
@pytest.mark.parametrize("held_for", [0.3, None])
def test_windows_a_round_while_the_team_tab_holds_a_colleagues_file_open(team, held_for):
    """NEEDS WINDOWS (notes/storage.md): the Team tab's status reads a colleague's head.json in the copy of the space
    at the moment a round replaces it. Held for a moment: the round waits and takes it. Held all along: the round ends
    with a problem in words, not PermissionError, and the next round takes it."""
    import threading

    anna, carol = team
    hc, head = _new_head_from_carol(anna, carol)
    f = open(head, "rb")   # noqa: SIM115  (held as a reader holds it)
    if held_for is not None:
        threading.Timer(held_for, f.close).start()
    try:
        with anna:
            out = folder.sync_now(anna.ws)       # must not raise
    finally:
        f.close()
    busy = [x["message"] for x in out["problems"] if x["kind"] == "busy"]
    if held_for is not None:
        assert not busy
    else:
        assert busy and "files open" in busy[0]
        _round(anna)
    with anna:
        assert _has(anna.ws, hc)


# ---------------------------------------------------------------------------------------------
# notes/storage.md, "Not proven"
# ---------------------------------------------------------------------------------------------
def test_an_older_roster_put_back_after_a_removal_is_written_over_by_the_keeper(team, store_dir, tmp_path,
                                                                               monkeypatch):
    """Not proven 1: after Dave is removed, the list of members from before (Dave still in it, signed by the keeper)
    is put back in the space (a member who can write there, a drive's version history). Copies that read the newer
    list ignore it, but the keeper never wrote its own again, so a colleague who joins later took the old list and
    read the removed member's part until the keeper let them in."""
    anna, carol = team
    dave, eve = Person(tmp_path, "Dave", monkeypatch), Person(tmp_path, "Eve", monkeypatch)
    with anna:
        inv = space.invite(anna.ws, "Dave")
    _join_new(dave, inv["link"])
    for p in (anna, carol, dave, anna, carol, dave):
        _round(p)
    roster = _space_dir(anna, store_dir) / "space" / "roster.json"
    old = roster.read_bytes()
    with anna:
        dave_part = next(m["part"] for m in folder.status(anna.ws)["space"]["members"] if m["person"] == dave.id)
        space.remove_member(anna.ws, dave_part)
        inv = space.invite(anna.ws, "Eve")
    _round(anna)
    roster.write_bytes(old)                      # the list from before the removal, put back
    _round(anna)                                 # the keeper's round
    _join_new(eve, inv["link"])
    _round(eve)                                  # before the keeper has let Eve in
    with eve:
        active = [m["person"] for m in folder.status(eve.ws)["space"]["members"] if not m["removed"]]
    assert dave.id not in active and anna.id in active


def test_an_invite_whose_secret_is_gone_from_the_keychain_lets_nobody_in(owner, store_dir):
    """Not proven 2: when an invite's secret is no longer in the keychain, the proof a key file must carry was checked
    against an HMAC with an empty key, which anyone who holds the project's key (any member) can make. Such a key file
    is set aside, saying what to do."""
    from enlens_claims import keychain

    with owner:
        inv = space.invite(owner.ws)
        desc = space.configured(owner.ws)
        keychain.delete(space._secret_name(desc["id"], f"invite:{inv['part']}"))
    payload = space.parse_link(inv["link"])
    payload["join"] = ""                         # (a proof made with an empty secret)
    k = seal.unb64(payload["keys"]["epochs"]["1"])
    blob = space._key_file(seal.Identity.new(), payload, "p0123456789ab", 1, k)
    m = store_dir / desc["prefix"] / "parts" / payload["part"] / "m"
    m.mkdir(parents=True)
    (m / "key.json").write_bytes(blob)
    _round(owner)
    with owner:
        st = folder.status(owner.ws)["space"]
    assert [mm["name"] for mm in st["members"]] == ["Anna"]
    assert [x["why"] for x in st["set_aside"]] == ["join"]
    assert "Withdraw the invite" in st["set_aside"][0]["message"]


def test_removing_a_colleague_whose_list_cannot_be_written_can_be_tried_again(team, monkeypatch):
    """Not proven 3: `_remove_member_unlocked` deletes the colleague's storage keys before it writes the list of
    members. When that write fails, the removal says so in words, and trying again ends with the colleague removed."""
    from enlens_claims.sync.storage import DirStorage, StorageProblem

    anna, carol = team
    for p in (anna, carol, anna, carol):
        _round(p)
    real, failed = DirStorage.put, []

    def put(self, name, data):
        if name == "space/roster.json" and not failed:
            failed.append(name)
            raise StorageProblem("The storage space did not answer.")
        return real(self, name, data)

    monkeypatch.setattr(DirStorage, "put", put)
    with anna:
        part = next(m["part"] for m in folder.status(anna.ws)["space"]["members"] if m["person"] == carol.id)
        with pytest.raises(space.SpaceProblem) as e:
            space.remove_member(anna.ws, part)
        assert "could not reach the storage space" in str(e.value)
        st = space.remove_member(anna.ws, part)
    assert [m["removed"] is not None for m in st["members"] if m["person"] == carol.id] == [True]
    _round(anna)


def test_an_invite_at_backblaze_whose_second_key_fails_says_why_not_the_cleanup(monkeypatch):
    """Not proven 4: making a colleague's read key fails; deleting the write key just made fails too. The B2Problem
    of the deletion escaped (not a SpaceProblem), hiding why the invite failed."""
    from enlens_claims.sync import b2

    made = []

    def create_key(acc, name, caps, **kw):
        made.append(name)
        if len(made) == 2:
            raise b2.B2Problem("Backblaze refused to make a key for the colleague.", "denied")
        return "w1", "secret"

    def delete_key(acc, key_id):
        raise b2.B2Problem("Backblaze cannot be reached.", "unreachable")

    monkeypatch.setattr(b2, "authorize", lambda *_a: object())
    monkeypatch.setattr(b2, "create_key", create_key)
    monkeypatch.setattr(b2, "delete_key", delete_key)
    desc = {"service": "b2", "prefix": "enlens/0123456789abcdef/", "bucket_id": "b"}
    with pytest.raises(space.SpaceProblem) as e:
        space._member_access(desc, {"key_id": "k", "app_key": "a"}, "m0123456789ab")
    assert str(e.value) == "Backblaze refused to make a key for the colleague."


def test_choosing_a_folder_that_is_refused_with_the_switch_on_keeps_the_switch_on(api, home):  # noqa: F811
    """Not proven 6: PUT …/shared-folder with "keep_out": true turns the switch on before the folder is chosen (so no
    round runs with it off); a refused folder leaves it on. That is what the person asked for, and the stricter
    setting: no document's words can go anywhere because of it."""
    assert api("POST", "/api/projects", {"name": "Demo"})[0] == 200
    st, r = api("PUT", "/api/projects/Demo/shared-folder", {"path": "/no/such/folder", "keep_out": True})
    assert st == 400
    assert home.open_project("Demo").config.get(folder.KEEP_OUT) is True


def test_a_change_brings_a_round_of_a_storage_space_soon_though_it_is_looked_at_every_ten_minutes():
    """Not proven 7: with a storage space the poller looks every 10 minutes at most, and a change made in the project
    still brings a round about 20 seconds later (docs/API.md: "a space is looked at every 10 minutes at most, and
    about 20 s after a change")."""
    from types import SimpleNamespace

    from enlens_claims.gui.poller import Poller

    t = [1000.0]
    app = SimpleNamespace(settings=lambda: {}, jobs=SimpleNamespace(ended=[]))
    pl = Poller(app, clock=lambda: t[0], start_delay=15, debounce=20)
    p = pl._project("P")
    p.min_every, p.last_end = float(space.MIN_EVERY), 1000.0
    assert pl._due(p) == 1000.0 + space.MIN_EVERY
    p.touched = 1100.0
    assert pl._due(p) == 1120.0


# ---------------------------------------------------------------------------------------------
# the review of 19 November 2026 (reviews/wave2.md)
# ---------------------------------------------------------------------------------------------
def test_a_project_folder_duplicated_by_hand_does_not_round_into_the_same_space(team, store_dir):
    """STORAGE15-6, review: a project folder duplicated by hand in the data folder (Finder's Duplicate) carries the
    same part and works with the same keys as the original, so the keys rule let both round into one copy of the space
    and push as one part with diverging work numbers. Only the project that last connected to the space here runs; the
    copy stops, in words."""
    import shutil

    from enlens_claims import claimcheck, sharing
    from enlens_claims import home as enlens_home
    from enlens_claims.llm import BaselineBackend

    anna, carol = team
    for p in (anna, carol, anna, carol):
        _round(p)
    with anna:
        anna.ws.close_all()
        shutil.copytree(anna.ws.root, enlens_home.home() / "projects" / "Study copy")
        dup = enlens_home.open_project("Study copy")
        assert space.configured(dup)["part"] == space.configured(anna.ws)["part"]
    hd = _check(anna, "Fuel cells need platinum.")
    with anna:   # (work in the copy too, which it would send as the same part)
        dup_h = claimcheck.check_hypothesis(dup, "Hydrogen valleys share pipelines.", BaselineBackend(), "baseline", k=2)
        sharing.share(dup, [{"kind": "check", "key": dup_h}])
    _share(anna, "check", hd)
    with anna:
        d1 = folder.sync_now(dup)
        o1 = folder.sync_now(anna.ws)
        d2 = folder.sync_now(dup)
    for out in (d1, d2):
        said = [x["message"] for x in out["problems"] if x["kind"] == "other_project_here"]
        assert said and "Stop using the storage space here" in said[0], out["problems"]
    assert not [x for x in o1["problems"] if x["kind"] == "other_project_here"], o1["problems"]
    _round(carol)
    assert _set_aside(carol) == []
    with carol:
        assert _has(carol.ws, hd) and not _has(carol.ws, dup_h)


def test_an_old_file_without_a_count_put_back_does_not_turn_a_newer_colleagues_switch_on(team, store_dir):
    """Review note: once this copy took a person.json WITH "n" from a colleague (they run this version), a file
    WITHOUT "n" from that colleague is older by definition: one from when they ran an older version, put back with the
    switch on and a later time, must not turn the switch on again after they turned it off."""
    anna, carol = team
    for p in (anna, carol, anna, carol):
        _round(p)
    with carol:
        folder.set_keep_out(carol.ws, True)
    _round(carol)
    with carol:
        folder.set_keep_out(carol.ws, False)
    _round(carol)
    _round(anna)
    with anna:
        team_dir = space.mirror_of(anna.ws) / folder.team_name(anna.ws)
    pj = json.loads((team_dir / carol.id / "person.json").read_text())
    assert pj.get("n") and not pj["keep_out"]
    old = {**{k: v for k, v in pj.items() if k != "n"}, "keep_out": True, "updated_at": _later(pj["updated_at"], 600)}
    _sealed_into_space(carol, store_dir, "person.json", old)
    _round(anna)
    with anna:
        assert not folder.keep_out_state(anna.ws, team_dir)["in_force"]


def test_a_keychain_that_does_not_answer_for_a_moment_is_said_as_such_and_the_join_goes_through_later(
        owner, tmp_path, monkeypatch):
    """Review note: when the keychain answers nothing for a moment (locked, unavailable), the invite's secret reads as
    missing; the keeper was told to withdraw a valid invite. The words say the keychain did not answer, and the next
    round lets the colleague in."""
    from enlens_claims import keychain

    anna = owner
    dave = Person(tmp_path, "Dave", monkeypatch)
    with anna:
        inv = space.invite(anna.ws, "Dave")
    _join_new(dave, inv["link"])
    real_init, real_get, down = space._Ctx.__init__, keychain._file_get, []

    def init(self, *a, **kw):
        real_init(self, *a, **kw)
        down.append(True)                 # (the keychain stops answering once the round has its own keys)

    monkeypatch.setattr(space._Ctx, "__init__", init)
    monkeypatch.setattr(keychain, "_file_get", lambda name: None if down else real_get(name))
    _round(anna)
    monkeypatch.setattr(space._Ctx, "__init__", real_init)
    monkeypatch.setattr(keychain, "_file_get", real_get)
    with anna:
        st = folder.status(anna.ws)["space"]
    said = [x["message"] for x in st["set_aside"] if x["why"] == "join"]
    assert said and "keychain" in said[0] and "did not answer" in said[0] and "Withdraw" not in said[0]
    assert [i["part"] for i in st["invites"]] == [inv["part"]]
    _round(anna)
    with anna:
        st = folder.status(anna.ws)["space"]
    assert dave.id in [m["person"] for m in st["members"]] and st["set_aside"] == []
