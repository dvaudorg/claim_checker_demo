"""Hunt phase 0 (2026-11-18): browser views that kept an old value after a choice or a second action changed it.
Each test names its bug; run in Node under the fake DOM of tests/_views.py."""
from __future__ import annotations

import pytest

from _views import needs_node, run_views

PROBE = r"""
// ---- JS-1: the profile's AI card follows the codebook ------------------------------------------------------------
await scenario("JS-1 profile card follows codebook", async (t) => {
  const FWS = [{ name: "alpha", title: "Alpha (3 codes)", codes: 3, label: "code", groups: 0 },
               { name: "beta", title: "Beta (4 codes)", codes: 4, label: "code", groups: 0 }];
  t.answer("GET /api/projects/Study/documents", { documents: [{ doc_id: "d1", title: "One" }] });
  t.answer("GET /api/projects/Study/profile?*", () => ({ frameworks: FWS, pass1: { done: true, passages: 5 }, stats: {}, grid: { codes: [], documents: [], cells: {} } }));
  t.answer("GET /api/projects/Study/profile/plan?*", () => ({ passages: 5, with_candidates: 5, already_read: 0, to_read: 5, run: {} }));
  t.answer("GET /api/projects/Study/profile/calibration?*", { total: 0, bins: [] });
  t.answer("PUT /api/settings", {});
  t.answer("POST /api/projects/Study/profile/label", { job: { id: "j1" } });
  t.answer("GET /api/jobs/j1", { id: "j1", state: "running", progress: { done: 0, total: 5 } });
  await t.render("views/profile.js", "renderProfile", [], { framework: "alpha" });
  await t.type(t.field(null, { sel: "#pf-fw" }) || document.getElementById("pf-fw"), "beta");
  await t.settle(50);
  await t.click(/^Label 5 passages/);
  await t.settle(50);
  return {
    plans: t.calls.filter((c) => c.path.includes("/profile/plan")).map((c) => c.path.split("framework=")[1].split("&")[0]),
    posts: t.calls.filter((c) => c.method === "POST" && c.path.endsWith("/profile/label")).map((c) => c.body.framework),
  };
});

// ---- JS-2: a second strictness change while a save is under way is not lost --------------------------------------
await scenario("JS-2 strictness second change", async (t) => {
  t.state({ settings: { threshold: 0.6 } }, { project: "Study" });
  const put = [];
  t.answer("PUT /api/settings", (body) => { put.push(body.threshold); return { settings: { threshold: body.threshold }, backend_label: "x" }; });
  t.answer("GET /api/projects/Study/hypotheses?*", async () => { await new Promise((r) => setTimeout(r, 500)); return { hypotheses: [] }; });
  t.answer("GET /api/projects/Study/calibration", { total: 0, bins: [] });
  await t.render("views/settings.js", "renderSettings", ["basics"]);
  const range = document.querySelector("input.range");
  range.value = "0.65"; range.dispatchEvent(new Event("change", { bubbles: true }));
  await t.settle(10);
  range.value = "0.7"; range.dispatchEvent(new Event("change", { bubbles: true }));
  await t.settle(5000);
  return { put, stored: t.LIB.App.settings().threshold };
});

// ---- JS-3: Look before checking, edited while it runs -------------------------------------------------------------
await scenario("JS-3 look then edit", async (t) => {
  const A = "Repair cafés build community among neighbours";
  const B = "Repair cafés reduce the waste of households";
  t.state({ settings: { backend: "claude_code", threshold: 0.6 } });
  let job = { id: "p1", state: "running", progress: {} };
  t.answer("GET /api/projects/Study", { frameworks: [], passages: 40 });
  t.answer("GET /api/projects/Study/documents", { documents: [] });
  t.answer("GET /api/projects/Study/hypotheses?*", { hypotheses: [] });
  t.answer("POST /api/projects/Study/hypotheses/similar", {});
  t.answer("POST /api/projects/Study/prepare", { job: { id: "p1" } });
  t.answer("GET /api/jobs/p1", () => job);
  await t.render("views/hypotheses.js", "renderHypotheses", [], {});
  await t.type("Your hypothesis", A);
  await t.settle(1000);
  await t.click("Look before checking");
  await t.type("Your hypothesis", B);
  await t.settle(1000);
  job = { id: "p1", state: "done", result: { parts: ["Repair cafés build community", "among neighbours"], terms: [[], []], split: true } };
  await t.settle(2000);
  const run = t.buttons().map((b) => b.label).filter((l) => /^Check/.test(l));
  return { run, text: t.text(), prep: t.view.querySelectorAll(".prep-card").filter((x) => !t.hidden(x)).length };
});

// ---- JS-4: the codes panel's list of codes follows the codebook ----------------------------------------------------
await scenario("JS-4 codes list follows codebook", async (t) => {
  const item = { passage_id: "p1", source: "model", label_id: "l1", relevance: "main", confidence: 0.8, quote: "a quote", reason: "why", location: "page 1", provisional: false };
  const prof = (fw) => ({ framework_title: fw, code_label: "code", pass1: { done: true }, passages: 5, n_pages: 2, read_by_model: 1,
    codes: [{ code: "X1", description: "Same code", share: 0.5, passages: 1, main: 1, pages: [1], positions: [10], items: [item] }] });
  t.answer("GET /api/projects/Study/documents/d1/profile?*", (b, path) => prof(decodeURIComponent(path.split("framework=")[1])));
  t.answer("GET /api/projects/Study/frameworks", { frameworks: [{ name: "alpha", title: "Alpha" }, { name: "beta", title: "Beta" }] });
  t.answer("GET /api/projects/Study/frameworks/alpha", { framework: { items: [{ code: "A1", description: "Alpha one" }] } });
  t.answer("GET /api/projects/Study/frameworks/beta", { framework: { items: [{ code: "B1", description: "Beta one" }] } });
  t.answer("GET /api/projects/Study/profile/plan?*", { passages: 5, with_candidates: 5, already_read: 5, to_read: 0, run: {} });
  const m = await t.module("views/doc-codes.js");
  const ctx = { query: { code: "X1" }, docBase: "/api/projects/Study/documents/d1", base: "/api/projects/Study", keepUrl() {}, project: "Study",
    watchers: [], docId: "d1", jumpTo() {}, paint() {}, framework: "alpha", tab: "codes" };
  const panel = m.codesPanel(ctx);
  document.getElementById("view").appendChild(panel.el);
  await t.settle(50);
  await t.click("Another code here");
  await t.click("Cancel");
  await t.type(document.getElementById("dv-fw"), "beta");
  await t.settle(50);
  await t.click(document.querySelector(".dv-code-head"));
  await t.click("Another code here");
  const opts = [...document.querySelectorAll("#dv-code-list option")].map((o) => o.value);
  const place = document.getElementById("dv-add-code").getAttribute("placeholder");
  return { opts, place, gets: t.calls.filter((c) => c.path.includes("/frameworks/")).map((c) => c.path.split("/").pop()) };
});

// ---- JS-5: the code picker when its codebook cannot be loaded -----------------------------------------------------
await scenario("JS-5 picker without its codebook", async (t) => {
  t.answer("GET /api/projects/Study/frameworks/x", t.fail(404, "Unknown framework: x"));
  const m = await t.module("views/options.js");
  const got = await m.pickCode({ project: "Study", framework: "x" });
  await t.settle(50);
  return { got: got === undefined ? "undefined" : got, toasts: t.toasts(), dialogs: t.dialogs().length };
});

// ---- P-1: the Research log's Ctrl+Enter adds an entry once --------------------------------------------------------
await scenario("P-1 log page double Ctrl+Enter", async (t) => {
  const posts = [];
  t.answer("GET /api/projects/Study/log?*", { entries: [], total: 0, groups: {}, group_names: {} });
  t.answer("GET /api/projects/Study/sharing?*", { items: [] });
  t.answer("POST /api/projects/Study/log", async (body) => { posts.push(body.text); await new Promise((r) => setTimeout(r, 300)); return {}; });
  await t.render("views/log.js", "renderLog", [], {});
  const ta = t.field("A new entry");
  ta.value = "We chose the second codebook";
  const key = () => ta.dispatchEvent(new Event("keydown", { key: "Enter", ctrlKey: true, bubbles: true }));
  key(); key();
  await t.settle(1000);
  return { posts };
});
await scenario("P-1 log page text typed while adding", async (t) => {
  t.answer("GET /api/projects/Study/log?*", { entries: [], total: 0, groups: {}, group_names: {} });
  t.answer("GET /api/projects/Study/sharing?*", { items: [] });
  t.answer("POST /api/projects/Study/log", async () => { await new Promise((r) => setTimeout(r, 300)); return {}; });
  await t.render("views/log.js", "renderLog", [], {});
  const ta = t.field("A new entry");
  ta.value = "First entry";
  await t.click("Add to the log");
  ta.value = "First entry, and a second thought";   // typed while the request runs
  await t.settle(1000);
  return { left: ta.value };
});

// ---- P-1 (drawer): the log drawer's Ctrl+Enter adds an entry once ------------------------------------------------
async function drawer(t, hash) {
  const shell = document.createElement("div"); shell.setAttribute("id", "shell"); document.body.appendChild(shell);
  t.state({}, { project: "Study", hash });
  t.answer("GET /api/projects/Study/log?*", { entries: [], total: 0, groups: {}, group_names: {} });
  t.answer("GET /api/projects/Study/documents/d1?*", { title: "Field notes" });
  const m = await t.module("views/logdrawer.js");
  m.initLogDrawer();
  await t.settle(50);
  await t.click("Write in the log");
  await t.settle(50);
  return document.getElementById("logdrawer");
}
await scenario("P-1 drawer double Ctrl+Enter", async (t) => {
  const posts = [];
  t.answer("POST /api/projects/Study/log", async (body) => { posts.push(body); await new Promise((r) => setTimeout(r, 300)); return {}; });
  await drawer(t, "#/doc/d1");
  const ta = document.querySelector(".logdrawer-text");
  ta.value = "A decision about this document";
  const key = () => ta.dispatchEvent(new Event("keydown", { key: "Enter", ctrlKey: true, bubbles: true }));
  key(); key();
  await t.settle(1000);
  return { posts: posts.map((p) => p.text) };
});
await scenario("P-1 drawer text typed while adding", async (t) => {
  t.answer("POST /api/projects/Study/log", async () => { await new Promise((r) => setTimeout(r, 300)); return {}; });
  await drawer(t, "#/hypotheses");
  const ta = document.querySelector(".logdrawer-text");
  ta.value = "First entry";
  await t.click("Add to the log");
  ta.value = "First entry, and a second thought";
  await t.settle(1000);
  return { left: ta.value };
});

// ---- P-4: the theory draft, a second edit waiting while the first is answered 409 ---------------------------------
await scenario("P-4 draft 409 with a waiting edit", async (t) => {
  const BASE = "/api/projects/Study/codebook-theory/draft";
  const C = (o) => ({ group: "", meaning: "", when_to_use: "", when_not: "", keep: true, checked: false, how: "found", sources: [], examples: [], words: [], ai: null, ...o });
  const DRAFT = (rev) => ({ title: "Repair theory", name: "repair", where: "project", doc_ids: ["d1"], focus: "", rev,
    reading: { state: "none", job: null, problems: [] }, left_out: [], groups: [{ key: "g1", name: "Practice", about: "" }],
    concepts: [C({ key: "c1", name: "habitus", group: "g1", meaning: "Lasting dispositions" })] });
  const OFFER = { offered: true, reader: "claude", parts: 1, why: "", documents: [{ doc_id: "d1", title: "Practice theory", level: "cloud", parts: 1, offered: true, why: "" }] };
  let server = 3, gets = 0;
  const revs = [];
  t.state({ settings: { backend: "claude_code" } });
  t.answer(`GET ${BASE}`, async () => { gets++; if (gets > 1) await new Promise((r) => setTimeout(r, 500)); return { draft: DRAFT(server), offer: OFFER, documents: [{ doc_id: "d1", title: "Practice theory" }] }; });
  t.answer(`GET ${BASE}/counts`, { documents: 1, counts: {} });
  t.answer(`PUT ${BASE}`, async (body) => {
    revs.push(body.rev);
    if (revs.length === 1) { await new Promise((r) => setTimeout(r, 1500)); server = 9; }   // changed elsewhere meanwhile
    if (body.rev !== server) return t.fail(409, "The draft changed.");
    server = body.rev + 1;
    return { draft: { rev: server, reading: { stale: false } } };
  });
  await t.render("views/theory-draft.js", "renderTheoryDraft");
  await t.click(/^Habitus /);
  await t.type("Definition", "Ways of acting learnt over a life");
  await t.settle(900);                       // the first save is sent and waits for its answer
  await t.type("Definition", "Ways of acting learnt over a whole life");
  await t.settle(1000);                      // the second is due and waits for the first
  await t.settle(8000);
  return { revs };
});
"""


@pytest.fixture(scope="module")
def page(tmp_path_factory):
    return run_views(PROBE, tmp_path_factory.mktemp("stale"))


@needs_node
def test_js1_profile_ai_card_follows_the_codebook(page):
    r = page["JS-1 profile card follows codebook"]
    assert "beta" in r["plans"]
    assert r["posts"][-1] == "beta"


@needs_node
def test_js2_a_second_strictness_change_during_a_save_is_kept(page):
    r = page["JS-2 strictness second change"]
    assert r["put"][-1] == 0.7 and r["stored"] == 0.7


@needs_node
def test_js3_a_look_taken_before_an_edit_is_not_shown_as_what_will_be_checked(page):
    r = page["JS-3 look then edit"]
    assert not any("parts" in x for x in r["run"]), r["run"]
    assert r["prep"] == 0 and "among neighbours" not in r["text"]


@needs_node
def test_js4_the_codes_to_pick_from_are_the_chosen_codebooks(page):
    r = page["JS-4 codes list follows codebook"]
    assert "beta" in r["gets"]
    assert r["opts"] == ["B1"] and r["place"] == "e.g. B1"


@needs_node
def test_js5_a_codebook_that_cannot_be_loaded_is_told_to_the_person(page):
    r = page["JS-5 picker without its codebook"]
    assert r["got"] == "undefined" and r["dialogs"] == 0
    assert any("Unknown framework: x" in x for x in r["toasts"]), r["toasts"]


@needs_node
def test_p1_ctrl_enter_twice_adds_one_entry_on_the_log_page(page):
    assert page["P-1 log page double Ctrl+Enter"]["posts"] == ["We chose the second codebook"]


@needs_node
def test_p1_text_typed_while_an_entry_is_added_is_kept_on_the_log_page(page):
    assert page["P-1 log page text typed while adding"]["left"] == "First entry, and a second thought"


@needs_node
def test_p1_ctrl_enter_twice_adds_one_entry_in_the_drawer(page):
    assert page["P-1 drawer double Ctrl+Enter"]["posts"] == ["A decision about this document"]


@needs_node
def test_p1_text_typed_while_an_entry_is_added_is_kept_in_the_drawer(page):
    assert page["P-1 drawer text typed while adding"]["left"] == "First entry, and a second thought"


@needs_node
def test_p4_a_waiting_save_does_not_send_the_old_revision_during_the_reload(page):
    r = page["P-4 draft 409 with a waiting edit"]
    # the second request after the 409 must carry the revision the reload brought (9), not the old one (3): the old
    # one would be answered 409 again, with a second "changed elsewhere" toast
    assert r["revs"] == [3, 9], r
