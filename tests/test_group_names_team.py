"""D1, the last part: the names of the concept map's groups travel with a team (groupnames.merge, sync/merge.py).

A kept name holds its group's concepts, who last changed it and when. On another copy it goes to the group there that
holds most of its concepts (the groups are found from each copy's own counts); one that fits no group is kept, not
drawn. One name changed on two copies: a person's decision beats an AI draft, the later of two decisions wins on
every copy, and the other person's words stay as a name of their own. Two names for one group: the later is shown,
the other beside it. A removed name does not come back, unless it was changed after the removal.
"""
from __future__ import annotations

import json

import pytest

from enlens_claims import groupnames, people, sharing
from enlens_claims.store import Workspace
from enlens_claims.sync import common
from test_shared_projects import anna_and_ben  # noqa: F401  (fixture)

ANNA, BEN, CLARA = "p" + "a" * 12, "p" + "b" * 12, "p" + "c" * 12
T1, T2, T3 = "2026-11-01T09:00:00+00:00", "2026-11-01T10:00:00+00:00", "2026-11-01T11:00:00+00:00"


def row(nid, name, source="person", person=ANNA, at=T1, concepts=("a", "b", "c")):
    return {"name_id": nid, "name": name, "source": source, "model": "claude-haiku-5-5" if source != "person" else None,
            "concepts_json": json.dumps(list(concepts)), "labels_json": json.dumps({c: c.upper() for c in concepts}),
            "filters_json": "{}", "n": 30, "created_at": T1, "updated_at": at, "person_id": person}


@pytest.fixture
def proj(tmp_path, monkeypatch):
    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    w = Workspace.create(tmp_path / "p")
    yield w
    w.close_all()


def put(ws, *rows):
    with ws.connect() as cx:
        for r in rows:
            cx.execute(f"INSERT OR REPLACE INTO concept_group_names({', '.join(groupnames.NAME_COLS)}) VALUES "
                       f"({','.join('?' * len(groupnames.NAME_COLS))})", tuple(r[c] for c in groupnames.NAME_COLS))


def merge(ws, names=(), removed=(), quotes=(), sender=ANNA, me=BEN, doc_here=lambda q: q):
    with ws.connect() as cx:
        return groupnames.merge(cx, list(names), list(quotes), list(removed), sender, me, doc_here)


def names(ws) -> dict[str, tuple]:
    return {r["name_id"]: (r["name"], r["source"], r["person_id"]) for r in
            ws.query("SELECT name_id, name, source, person_id FROM concept_group_names")}


def test_the_tables_travel_and_are_merged_by_their_own_rules():
    for t in ("concept_group_names", "concept_group_quotes"):
        assert t not in common.LOCAL_ONLY and t in common.OWN_RULES and t not in sharing._LOCAL_TABLES
    assert groupnames.KIND in sharing.LOCAL_TASK_KINDS          # the AI's tasks still stay where they were run


def test_the_shared_folder_carries_the_names_and_their_removals(proj):
    with proj.connect() as cx:
        where = {t: w for t, w, _c in sharing.ProjectRows(cx, proj.root).tables()}
    assert where["concept_group_names"] == "1" and where["concept_group_quotes"] == "1"
    assert "'group_name'" in where["sync_removed"]


def test_two_people_change_one_name_the_later_wins_on_both_copies_and_the_other_is_kept(proj, tmp_path):
    """Ben's copy has his rename; Anna's later one comes in. Anna's copy has hers; Ben's earlier one comes in. Both end
    with Anna's name for the group and Ben's words as a name of their own, under the same id."""
    put(proj, row("n1", "Hybrid work", person=BEN, at=T1))
    assert merge(proj, [row("n1", "Remote work", person=ANNA, at=T2)], sender=ANNA, me=BEN) == 2
    bens = names(proj)
    other = Workspace.create(tmp_path / "anna")
    put(other, row("n1", "Remote work", person=ANNA, at=T2))
    merge(other, [row("n1", "Hybrid work", person=BEN, at=T1)], sender=BEN, me=ANNA)
    annas = names(other)
    other.close_all()
    assert bens == annas
    assert bens["n1"] == ("Remote work", "person", ANNA)
    (fork,) = [k for k in bens if k != "n1"]
    assert bens[fork] == ("Hybrid work", "person", BEN)
    # the same file again changes nothing
    assert merge(proj, [row("n1", "Remote work", person=ANNA, at=T2)], sender=ANNA, me=BEN) == 0


def test_the_same_time_is_settled_by_the_person_id_on_every_copy(proj):
    put(proj, row("n1", "Hybrid work", person=BEN, at=T2))
    merge(proj, [row("n1", "Remote work", person=CLARA, at=T2)], sender=CLARA, me=BEN)
    assert names(proj)["n1"][0] == "Remote work"            # the larger id: Clara's (pccc… > pbbb…)


@pytest.mark.parametrize("draft_later", [True, False])
def test_a_persons_name_beats_an_ai_draft_whenever_it_was_given(proj, draft_later):
    put(proj, row("n1", "Talk of solar", source="ai_draft", person=BEN, at=T3 if draft_later else T1))
    merge(proj, [row("n1", "Solar parks", person=ANNA, at=T2)])
    assert names(proj) == {"n1": ("Solar parks", "person", ANNA)}   # the draft is not kept beside it
    # and a draft that comes in never replaces a person's name
    put(proj, row("n2", "Grid costs", person=BEN, at=T1))
    merge(proj, [row("n2", "Talk of grids", source="ai_draft", person=ANNA, at=T3)])
    assert names(proj)["n2"] == ("Grid costs", "person", BEN)


def test_an_ai_name_used_by_a_person_counts_as_their_decision(proj):
    put(proj, row("n1", "Talk of solar", source="ai", person=BEN, at=T1))
    merge(proj, [row("n1", "Solar parks", person=ANNA, at=T2)])
    got = names(proj)
    assert got["n1"] == ("Solar parks", "person", ANNA)
    assert ("Talk of solar", "ai", BEN) in got.values()


def test_a_removed_name_stays_removed_unless_changed_after(proj):
    put(proj, row("n1", "Old name", person=BEN, at=T1))
    with proj.connect() as cx:
        cx.execute("DELETE FROM concept_group_names")
        groupnames._note_removed(cx, "n1", "Old name", T2, BEN)
    merge(proj, [row("n1", "Old name", person=ANNA, at=T1)])
    assert names(proj) == {}
    merge(proj, [row("n1", "Renamed since", person=ANNA, at=T3)])      # renamed after the removal: it counts
    assert names(proj) == {"n1": ("Renamed since", "person", ANNA)}
    # a removal that comes in: a name changed here before it goes, one changed after it stays
    put(proj, row("n2", "Gone", person=BEN, at=T1), row("n3", "Kept", person=BEN, at=T3))
    merge(proj, removed=[{"kind": "group_name", "key": k, "title": "x", "at": T2, "person_id": ANNA} for k in ("n2", "n3")])
    assert set(names(proj)) == {"n1", "n3"}
    assert proj.scalar("SELECT COUNT(*) FROM sync_removed WHERE kind='group_name' AND key IN ('n2', 'n3')") == 2


def test_a_name_in_your_own_name_from_someone_elses_file_is_not_taken(proj):
    merge(proj, [row("n1", "Mine?", person=BEN, at=T3)], sender=ANNA, me=BEN)
    assert names(proj) == {}


def test_an_ai_names_quote_comes_in_only_for_a_document_here(proj):
    q = {"name_id": "n1", "doc_id": "d1", "passage_id": "d1:0001", "page": 2, "start": 5, "end": 20, "quote": "solar parks need land"}
    merge(proj, [row("n1", "Solar parks", source="ai", at=T2)], quotes=[q], doc_here=lambda x: None)
    assert proj.scalar("SELECT COUNT(*) FROM concept_group_quotes") == 0
    merge(proj, [row("n2", "Land use", source="ai", at=T2)], quotes=[{**q, "name_id": "n2"}])
    assert proj.scalar("SELECT quote FROM concept_group_quotes WHERE name_id='n2'") == "solar parks need land"


# ---- how a copy shows the names: its own groups -------------------------------------------------------------------
def _attach(ws, members, labels=None):
    labels = labels or {c: c.upper() for g in members for c in g}
    out = {"groups": [{"group": i + 1} for i in range(len(members))]}
    groupnames.attach(ws, out, members, labels, {}, 30, None, settings={})
    return out


def test_two_names_for_one_group_the_later_is_shown_and_the_other_beside_it(proj):
    with proj.connect() as cx:
        people.remember(cx, ANNA, "Anna")
        people.remember(cx, CLARA, "Clara")
    put(proj, row("n1", "Hybrid work", person=CLARA, at=T1, concepts=("a", "b", "c")),
        row("n2", "Remote work", person=ANNA, at=T2, concepts=("a", "b", "d")),
        row("n3", "Talk of offices", source="ai_draft", person=ANNA, at=T3, concepts=("a", "b")))
    g = _attach(proj, [["a", "b", "c", "d"], ["e", "f"]])["groups"][0]
    assert (g["name"], g["by"]) == ("Remote work", "Anna")
    assert [(x["name"], x["by"], x["at"]) for x in g["also_named"]] == [("Hybrid work", "Clara", T1)]   # no draft
    assert _attach(proj, [["a", "b", "c", "d"], ["e", "f"]])["names_elsewhere"] == []


def test_a_group_that_differs_between_copies_takes_the_name_whose_concepts_it_mostly_holds(proj):
    put(proj, row("n1", "Energy prices", at=T1, concepts=("a", "b", "c", "d")))
    # this copy found other groups: most of the name's concepts are in its second
    out = _attach(proj, [["x", "d"], ["a", "b", "c", "y"]])
    assert [g["name_source"] for g in out["groups"]] == ["concepts", "person"]
    assert out["groups"][1]["name"] == "Energy prices"
    # split half and half: no group holds most of them; the name is kept, listed apart, not drawn
    out = _attach(proj, [["a", "b", "x"], ["c", "d", "y"]])
    assert [g["name_source"] for g in out["groups"]] == ["concepts", "concepts"]
    assert [x["name"] for x in out["names_elsewhere"]] == ["Energy prices"]


def test_a_name_that_fits_no_group_here_is_kept_and_not_drawn(proj):
    merge(proj, [row("n1", "Water stress", at=T2, concepts=("w", "v"))])
    out = _attach(proj, [["a", "b"], ["c", "d"]])
    assert all(g["name_source"] == "concepts" for g in out["groups"])
    assert [x["name"] for x in out["names_elsewhere"]] == ["Water stress"]
    assert names(proj) == {"n1": ("Water stress", "person", ANNA)}


# ---- through a colleague's file (sync.bring_in) ---------------------------------------------------------------------
def test_a_name_and_its_change_travel_both_ways_through_a_file(anna_and_ben):  # noqa: F811
    anna, ben = anna_and_ben
    cs = ["t1", "t2", "t3"]
    with anna:
        r = groupnames.save(anna.ws, "rename", {"name": "Water and arid land", "concepts": cs,
                                                "labels": {c: c for c in cs}, "filters": {}, "n": 30})["record"]
        nid = r["name_id"]
        with anna.ws.connect() as cx:
            cx.execute("UPDATE concept_group_names SET updated_at=? WHERE name_id=?", (T1, nid))
    rep = ben.bring_in(anna.send())
    assert rep["group_names"] == 1 and any("names of the concept map" in x or "name of the concept map" in x
                                           for x in rep["lines"])
    with ben:
        got = ben.ws.query("SELECT name, person_id FROM concept_group_names WHERE name_id=?", (nid,))[0]
        assert (got["name"], got["person_id"]) == ("Water and arid land", anna.id)
        groupnames.save(ben.ws, "rename", {"name_id": nid, "name": "Arid regions", "concepts": cs,
                                           "labels": {c: c for c in cs}, "filters": {}, "n": 30})
        with ben.ws.connect() as cx:
            cx.execute("UPDATE concept_group_names SET updated_at=? WHERE name_id=?", (T2, nid))
    anna.bring_in(ben.send())
    with anna:
        rows = {r["name"]: r["person_id"] for r in anna.ws.query("SELECT name, person_id FROM concept_group_names")}
    assert rows == {"Arid regions": ben.id, "Water and arid land": anna.id}   # hers kept beside his, nothing lost
    # Ben forgets his: the removal travels
    with ben:
        groupnames.save(ben.ws, "forget", {"name_id": nid})
    anna.bring_in(ben.send())
    with anna:
        assert [r["name"] for r in anna.ws.query("SELECT name FROM concept_group_names")] == ["Water and arid land"]
