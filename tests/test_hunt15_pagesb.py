"""Hunt phase 1.5, pages-b: every note and open point of phases 0 and 1 about the page's documents, codebook editor,
notes, concepts and team views, each settled by a test (views run in Node under a fake DOM through tests/_views.py; the
server halves on small real projects).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from _views import needs_node, run_views
from test_shared_projects import Person, anna_and_ben  # noqa: F401  (fixture)
from test_storage_space import _join_new, _round, owner, store_dir, team  # noqa: F401  (fixtures)

ROOT = Path(__file__).resolve().parent.parent

PROBE = r"""
const held = () => { const h = {}; h.promise = new Promise((r) => { h.release = r; }); return h; };

// ---- the Team page -------------------------------------------------------------------------------------------------
const FOLDER = "/api/projects/Study/shared-folder";
const OWNERVIEW = (o) => ({ owner: null, me: "a", is_owner: false, since: null, how: null, role: "member", can_write: true,
  can_set_roles: false, can_claim: false, can_take_over: null, accept_adds: true, people: [], questions: [], offers: [],
  removed: [], clashes: [], refused: [], notices: [], proposals: [], waiting: 0, to_apply: [], documents: {}, later: [], ...o });
function team(t, status, ownerView) {
  t.state({ settings: { your_name: "Anna" } });
  t.answer(`GET ${FOLDER}`, status);
  t.answer("GET /api/projects/Study/sharing", { items: [] });
  t.answer("GET /api/projects/Study/together", { history: [] });
  t.answer("GET /api/projects/Study/sync-poller", t.fail(404, "no poller"));
  t.answer("GET /api/projects/Study/owner", ownerView);
  t.answer("GET /api/projects/Study/owner/codebooks", { team: true, can_set: false,
    share_codebooks: { on: false, set: false, by: null, at: null }, default: null, choices: [], private_mine: [] });
  t.answer("GET /api/projects/Study/owner/providers", { team: true, can_set: false, limit: null, choices: [] });
  t.answer("GET /api/cloud-folders", { folders: [], picker: false });
  t.answer(`GET ${FOLDER}/find`, { found: [] });
  t.answer("GET /api/space/links", { b2_signup: "https://example.org/b2" });
}
const SPACE = { folder: "/space/x", me: { name: "Anna" }, people: [{ name: "Ben", id: "b" }, { name: "Carol", id: "c" }],
  space: { service: "b2", keeper: true, where: "b2://bucket", invites: [], members: [{ name: "Anna", me: true, part: "p1", person: "a", keeper: true },
    { name: "Ben", part: "p2", person: "b" }, { name: "Carol", part: "p3", person: "c" }] } };
const PEOPLE = (ownerId) => [{ id: "a", name: "Anna", me: true, owner: ownerId === "a", role: ownerId === "a" ? "owner" : "member" },
  { id: "b", name: "Ben", me: false, owner: false, role: "member" }, { id: "c", name: "Carol", me: false, owner: ownerId === "c", role: ownerId === "c" ? "owner" : "member" }];
const people = (t) => t.view.querySelector(".team-sec-people");
const peopleOut = (t) => ({ buttons: t.buttons(people(t)).map((b) => b.label), text: t.allText(people(t)),
  menus: people(t).querySelectorAll("details.menu").map((m) => t.allText(m)) });

await scenario("team: a Member whose copy still keeps the storage keys", async (t) => {
  team(t, SPACE, OWNERVIEW({ owner: { id: "c", name: "Carol", me: false }, role: "member", can_write: false, people: PEOPLE("c"), how: "handover" }));
  await t.render("views/team.js", "renderTeam", ["settings"], {});
  return peopleOut(t);
});

await scenario("team: the Owner whose copy keeps the storage keys", async (t) => {
  team(t, SPACE, OWNERVIEW({ owner: { id: "a", name: "Anna", me: true }, is_owner: true, role: "owner", can_write: true, can_set_roles: true, people: PEOPLE("a") }));
  await t.render("views/team.js", "renderTeam", ["settings"], {});
  return peopleOut(t);
});

await scenario("team: a Co-owner whose copy keeps the storage keys", async (t) => {
  const ps = PEOPLE("c"); ps[0].role = "co";
  team(t, SPACE, OWNERVIEW({ owner: { id: "c", name: "Carol", me: false }, role: "co", can_write: true, can_set_roles: false, people: ps }));
  await t.render("views/team.js", "renderTeam", ["settings"], {});
  return peopleOut(t);
});

const OTHER = { ...SPACE, other_computer: { since: "2026-11-10T10:00:00Z" } };
await scenario("team: another computer, Activity", async (t) => {
  team(t, OTHER, OWNERVIEW({ owner: { id: "a", name: "Anna", me: true }, is_owner: true, role: "owner", can_set_roles: true, people: PEOPLE("a") }));
  await t.render("views/team.js", "renderTeam", [], {});
  return t.buttons(t.view).map((b) => b.label).filter((x) => x === "Use both computers…").length;
});
await scenario("team: another computer, People and settings", async (t) => {
  team(t, OTHER, OWNERVIEW({ owner: { id: "a", name: "Anna", me: true }, is_owner: true, role: "owner", can_set_roles: true, people: PEOPLE("a") }));
  await t.render("views/team.js", "renderTeam", ["settings"], {});
  return t.buttons(t.view).map((b) => b.label).filter((x) => x === "Use both computers…").length;
});

// item 1: the owner's reason dialog saves from its own button
await scenario("team: a hand-over refused keeps the reason typed", async (t) => {
  team(t, SPACE, OWNERVIEW({ owner: { id: "a", name: "Anna", me: true }, is_owner: true, role: "owner", can_set_roles: true, people: PEOPLE("a") }));
  t.answer("POST /api/projects/Study/owner/hand-over", t.fail(409, "Ben's copy has not sent anything yet: try again after a round."));
  await t.render("views/team.js", "renderTeam", ["settings"], {});
  await t.click(t.view.querySelector("#owner-more-b-btn"));
  await t.click("Make owner…");
  await t.type("Reason (optional)", "I am leaving the project in December");
  await t.click("Hand it over", { within: t.dialog() });
  await t.settle();
  const d = t.dialog();
  const f = d && d.querySelector("#owner-dlg-reason");
  return { open: !!d, reason: f ? f.value : null, said: d ? t.text(d.querySelector(".field-error")) : null,
    posts: t.calls.filter((c) => c.method === "POST").map((c) => c.body) };
});

await scenario("team: a hand-over that works closes its dialog and says so", async (t) => {
  team(t, SPACE, OWNERVIEW({ owner: { id: "a", name: "Anna", me: true }, is_owner: true, role: "owner", can_set_roles: true, people: PEOPLE("a") }));
  t.answer("POST /api/projects/Study/owner/hand-over", { ok: true });
  await t.render("views/team.js", "renderTeam", ["settings"], {});
  await t.click(t.view.querySelector("#owner-more-b-btn"));
  await t.click("Make owner…");
  await t.type("Reason (optional)", "I am leaving");
  await t.click("Hand it over", { within: t.dialog() });
  await t.settle();
  return { open: t.dialogs().length, toasts: t.toasts(), posts: t.calls.filter((c) => c.method === "POST").map((c) => c.body) };
});

// ---- askWhy: a removal's why ----------------------------------------------------------------------------------------
const DOC1 = { doc_id: "d1", title: "Repair report", file: "repair.pdf", ai_access: "cloud", reader: 7, kind: "pdf", added_at: "2026-11-01T10:00:00Z", passages: 4, n_pages: 2 };
async function documents(t, docs = [DOC1], o = {}) {
  t.state({ settings: {} });
  t.answer("GET /api/projects/Study", { search: null, passages: 0, ai_access: { chosen: true, default: "cloud" } });
  t.answer(/^GET \/api\/projects\/Study\/documents(\?.*)?$/, typeof docs === "function" ? docs : { documents: docs, ai_access: { chosen: true, default: "cloud" }, new_reader: 7 });
  t.answer(/^GET \/api\/projects\/Study\/document-roles/, { roles: {}, nonscientific: [] });
  t.answer("GET /api/projects/Study/nonscientific-suggestions", { suggested: {} });
  t.answer("GET /api/projects/Study/map/documents?*", t.fail(404, "no answers yet"));
  t.answer("GET /api/projects/Study/owner", OWNERVIEW({}));
  t.answer("GET /api/jobs", o.jobs || { jobs: [] });
  t.answer("GET /api/projects/Study/hypotheses", { hypotheses: [] });
  if (o.before) o.before();
  await t.render("views/sources.js", "renderSources");
}
await scenario("documents: a removal refused keeps the why typed", async (t) => {
  await documents(t);
  t.answer("DELETE /api/projects/Study/documents/d1?*", t.fail(404, "No such document in this project: it was removed meanwhile."));
  await t.click(t.view.querySelector(".doc-toggle"));
  await t.click("Remove…");
  await t.type("Why? (optional, kept in the research log)", "the wrong version");
  await t.click("Remove", { within: t.dialog() });
  await t.settle();
  const d = t.dialog();
  return { open: !!d, why: d ? d.querySelector("textarea").value : null, said: d ? t.text(d.querySelector(".field-error")) : null };
});

await scenario("codebook: a removal refused keeps the why typed", async (t) => {
  const CB = "/api/projects/Study/codebooks";
  t.state({ settings: { backend: "claude_code" } });
  t.answer(`GET ${CB}/repair`, { codebook: { name: "repair", title: "Repair", label: "code", where: "project", editable: true, directional: false,
    used: { labels: 0, checks: 0 }, groups: [{ group: "1", group_name: "Practice" }], codes: [{ uid: "u1", code: "Mending", description: "Fixing things", group: "1", include: "", exclude: "", keywords: [], examples: [] }] } });
  t.answer(`GET ${CB}/repair/offer`, { offer: null });
  t.answer("GET /api/projects/Study/sharing/codebook/repair", { shared: false });
  t.answer("GET /api/projects/Study/shared-folder", { folder: null });
  t.answer("GET /api/projects/Study/sync-poller", t.fail(404, "none"));
  t.answer(`DELETE ${CB}/repair?*`, t.fail(400, "ENLENS has restarted: reload the page."));
  await t.render("views/codebooks.js", "renderCodebook", ["repair"]);
  await t.click("More");
  await t.click("Remove the codebook");
  await t.type("Why? (optional, kept in the research log)", "made by mistake");
  await t.click("Remove", { within: t.dialog() });
  await t.settle();
  const d = t.dialog();
  return { open: !!d, why: d ? d.querySelector("textarea").value : null, said: d ? t.text(d.querySelector(".field-error")) : null, hash: location.hash };
});

await scenario("share: an unshare refused keeps the why typed", async (t) => {
  t.state({ settings: {} });
  t.answer("POST /api/projects/Study/sharing/unshare", t.fail(404, "Not found: h1"));
  const m = await t.module("views/share.js");
  const p = m.unshareItem({ kind: "check", key: "h1", title: "Repair cafés cut waste" });
  await t.settle();
  await t.type("Why? (optional, kept in the research log)", "not ready yet");
  await t.click("Unshare", { within: t.dialog() });
  await t.settle();
  const d = t.dialog();
  return { open: !!d, why: d ? d.querySelector("textarea").value : null, said: d ? t.text(d.querySelector(".field-error")) : null };
});

// ---- the concept map: renaming a group --------------------------------------------------------------------------------
const CM = "/api/projects/Study/concept-map";
const G = (o) => ({ name_source: "concepts", name_id: null, model: null, quote: null, changed: null, naming_failed: null, ...o });
const MAP = { built: true, n: 60, filters: {}, nodes: [
    { id: "a", label: "repair", passages: 20, group: 1, x: 0.2, y: 0.3 }, { id: "b", label: "community", passages: 12, group: 1, x: 0.3, y: 0.45 },
    { id: "c", label: "waste", passages: 8, group: 2, x: 0.8, y: 0.2 }, { id: "e", label: "landfill", passages: 4, group: 2, x: 0.9, y: 0.6 }],
  edges: [{ a: "a", b: "b", together: 6, pmi: 1.5 }], links: [],
  groups: [G({ group: 1, size: 2, concepts: ["a", "b"], name: "Mending together", name_source: "person", name_id: "n1" }),
    G({ group: 2, size: 2, concepts: ["c", "e"], name: "Waste", name_id: null })],
  names_elsewhere: [], can_name: { offered: true, why: null, reader: "claude" }, passages: 120, concepts_in_scope: 40, links_off_map: 0 };
async function conceptMap(t, jobs = { jobs: [] }) {
  t.state({ settings: { backend: "claude_code" }, version: "0.20.3" });
  t.answer(`GET ${CM}/options`, { documents: [], themes: { run_id: "r1", themes: [] }, codebooks: [], years: [] });
  t.answer(`GET ${CM}?*`, MAP);
  t.answer("GET /api/jobs", jobs);
  await t.render("views/concept-map.js", "renderConceptMap", [], {});
}
await scenario("concept map: a group's new name refused stays in its dialog", async (t) => {
  t.answer(`POST ${CM}/names`, t.fail(400, "Give the group a shorter name: 60 characters at most."));
  await conceptMap(t);
  await t.click("Rename the group “Mending together”");
  await t.type(t.dialog().querySelector("input"), "Repair cafés and their neighbours");
  await t.click("Save", { within: t.dialog() });
  await t.settle();
  const d = t.dialog();
  return { open: !!d, name: d ? d.querySelector("input").value : null, said: d ? t.text(d.querySelector(".field-error")) : null };
});
await scenario("concept map: a group's new name saved closes the dialog", async (t) => {
  t.answer(`POST ${CM}/names`, { record: {} });
  await conceptMap(t);
  await t.click("Rename the group “Mending together”");
  await t.type(t.dialog().querySelector("input"), "Repair cafés");
  await t.click("Save", { within: t.dialog() });
  await t.settle();
  return { open: t.dialogs().length, sent: t.calls.filter((c) => c.path === `${CM}/names`).map((c) => c.body.name), toasts: t.toasts() };
});

// handed on: a second press of "Name the groups" gets the job already running back
await scenario("concept map: the names job given back to a second press is followed once", async (t) => {
  t.answer(`POST ${CM}/name-groups?*`, { job: { id: "jg", kind: "group-names" } });
  let state = "running";
  t.answer("GET /api/jobs/jg", () => ({ id: "jg", kind: "group-names", state, progress: { done: 1, total: 2 }, result: state === "done" ? { named: 2, failed: 0, groups: 2 } : null }));
  await conceptMap(t, { jobs: [{ id: "jg", kind: "group-names", project: "Study", state: "running" }] });   // another tab started it
  const busy = t.view.querySelector(".cm-groups-ask button").getAttribute("aria-busy");
  state = "done";
  await t.settle(3000);
  return { busy, posts: t.calls.filter((c) => c.path.includes("name-groups")).length, toasts: t.toasts() };
});

// ---- the concept card: accepting a proposed relation --------------------------------------------------------------
await scenario("concepts: accepting a proposed relation says which one", async (t) => {
  const BASE = "/api/projects/Study";
  const lk = { term_id: "t2", label: "spare parts", relation: "needs", source: "pattern", state: "proposed", confidence: null,
    quote_a: null, quote_b: null, a: "t1", b: "t2", decision: null, this_term: "t1" };
  t.answer(`GET ${BASE}/concepts/t1?*`, { term_id: "t1", label: "repair", mentions: 5, passages: 4, documents: [], wordings: [{ term_id: "t1", label: "repair", mentions: 5, documents: 1, joins: [] }],
    lines: [], related: { links: [lk], together: [] }, suggested_wordings: [], stale: false });
  t.answer(`GET ${BASE}/sharing?*`, { items: [] });
  t.answer(`PUT ${BASE}/concepts/links`, {});
  await t.render("views/concepts.js", "renderConcept", ["t1"], {});
  await t.click("Yes, right");
  return t.calls.filter((c) => c.method === "PUT").map((c) => c.body);
});

// ---- the label run's card -------------------------------------------------------------------------------------------
const PLAN = (o) => ({ passages: 10, with_candidates: 6, already_read: 0, to_read: 6, run: { now: { model: "haiku" }, changed: [] }, ...o });
await scenario("profile: a label run found running while its start answers is followed once", async (t) => {
  t.state({ settings: { backend: "claude_code" } });
  t.answer("GET /api/projects/Study/profile/plan?*", PLAN({}));
  let state = "running";
  t.answer("POST /api/projects/Study/profile/label", { job: { id: "jl" } });
  t.answer("GET /api/jobs/jl", () => ({ id: "jl", kind: "label", state, progress: { done: 1, total: 6 }, result: state === "done" ? { read: 6, changes: {} } : null }));
  const m = await t.module("views/profile.js");
  let ends = 0;
  const card = m.aiLabelCard({ project: "Study", framework: "sdg", watchers: [], onEnd: () => { ends += 1; } });
  document.getElementById("view").appendChild(card.el);
  await t.settle(10);
  await t.click(/^Label 6 passages/);
  card.follow("jl");                         // the page's own look for a run under way finds the same one
  state = "done";
  await t.settle(3000);
  return { ends, toasts: t.toasts().filter((x) => x.startsWith("The AI read")).length };
});

await scenario("profile: a second labelling with the same codebook refused in words", async (t) => {
  t.state({ settings: { backend: "claude_code" } });
  t.answer("GET /api/projects/Study/profile/plan?*", PLAN({}));
  t.answer("POST /api/projects/Study/profile/label", t.fail(409, "The AI labels passages with the codebook sdg already: wait until it has finished, or stop it in the sidebar, then start this one."));
  const m = await t.module("views/profile.js");
  const card = m.aiLabelCard({ project: "Study", framework: "sdg", watchers: [] });
  document.getElementById("view").appendChild(card.el);
  await t.settle(10);
  await t.click(/^Label 6 passages/);
  await t.settle();
  return { toasts: t.toasts(), again: !t.find(/^Label 6 passages/).disabled };
});

await scenario("profile: Read at most keeps the focus and what is typed when a comparison ends", async (t) => {
  t.state({ settings: { backend: "claude_code" } });
  t.answer("GET /api/projects/Study/profile/plan?*", PLAN({ already_read: 2, to_read: 4, run: { now: { model: "haiku" }, last: { started_at: "2026-11-10T10:00:00Z" },
    changed: [{ field: "model", was: "sonnet", now: "haiku" }] } }));
  t.answer("POST /api/projects/Study/profile/compare", { job: { id: "jc" } });
  let state = "running";
  t.answer("GET /api/jobs/jc", () => ({ id: "jc", kind: "label_compare", state, progress: { done: 1, total: 5 }, result: state === "done" ? { compared: 5, kappa: 0.8, same_codes: 0.8 } : null }));
  const m = await t.module("views/profile.js");
  const card = m.aiLabelCard({ project: "Study", framework: "sdg", watchers: [] });
  document.getElementById("view").appendChild(card.el);
  await t.settle(10);
  await t.click("Label a sample of up to 50 again first");
  await t.click(card.el.querySelector(".pf-ai-opts > summary"));
  const f = card.el.querySelector(".pf-limit");
  f.focus(); f.value = "3";                 // typed, not yet left (no change event)
  state = "done";
  await t.settle(2000);
  const now = card.el.querySelector(".pf-limit");
  return { value: now ? now.value : null, focused: !!now && document.activeElement === now };
});

// ---- the Documents page ---------------------------------------------------------------------------------------------
await scenario("documents: the summary of an add gives the server's note", async (t) => {
  await documents(t, [DOC1], { jobs: { jobs: [{ id: "ji", kind: "ingest", project: "Study", state: "running" }] }, before: () => {
    t.answer("GET /api/jobs/ji", { id: "ji", kind: "ingest", state: "done", progress: {}, result: { added: 1, duplicates: 0,
      note: "3 earlier documents of this project still follow a default nobody chose (\"Claude may read it\" until it is chosen). The new documents have their own setting. Choose the project's default in the app: its Documents page asks." } });
  } });
  await t.settle(1500);
  return t.text(t.view);
});

await scenario("documents: a tick keeps the focus when the list is drawn again after an add", async (t) => {
  let state = "running";
  await documents(t, [DOC1, { ...DOC1, doc_id: "d2", title: "Interviews", file: "interviews.pdf" }], { jobs: { jobs: [{ id: "ji", kind: "ingest", project: "Study", state: "running" }] },
    before: () => t.answer("GET /api/jobs/ji", () => ({ id: "ji", kind: "ingest", state, progress: {}, result: state === "done" ? { added: 1, duplicates: 0 } : null })) });
  const tick = t.view.querySelectorAll(".doc-tick")[1];
  await t.click(tick);
  tick.focus();
  state = "done";
  await t.settle(1500);
  const f = document.activeElement;
  return { tick: !!f && f.classList.contains("doc-tick") && f.value, checked: !!f && f.checked, same: f === tick };
});

// ---- the Bibliography: the Zotero chooser while a retraction check ends -----------------------------------------------
await scenario("bibliography: the Zotero chooser keeps its search and ticks when a retraction check ends", async (t) => {
  t.state({ settings: {} });
  const W = (key, title) => ({ key, title, authors: "Ostrom", year: 1990, cite: "Ostrom 1990", type: "article", notices: [] });
  t.answer("GET /api/projects/Study/bibliography", { bibliography: { kind: "zotero", library: "user", library_name: "My Library", collection: "C1", collection_name: "Commons", pulled_at: "2026-11-18T10:00:00Z" },
    counts: { works: 1, to_find: 1, linked: 0, confirm: 0, not_in: 0 }, to_find: [W("zotero:user:a", "Governing the commons")], linked: [], confirm: [], not_in: [], retractions: {}, ai_access: { chosen: true, default: "cloud" } });
  t.answer("GET /api/zotero", { state: "ready", libraries: [{ id: "user", name: "My Library" }] });
  t.answer("GET /api/zotero/collections?*", { collections: [{ key: "C1", name: "Commons", items: 3 }] });
  t.answer("GET /api/zotero/works?*", { works: [{ key: "K1", title: "Governing the commons", sub: "Ostrom 1990" }, { key: "K2", title: "The craftsman", sub: "Sennett 2008" }] });
  let state = "running";
  t.answer("POST /api/projects/Study/retractions/check", { job: { id: "jx" } });
  t.answer("GET /api/jobs/jx", () => ({ id: "jx", state, progress: { done: 1, total: 3 }, result: state === "done" ? { looked_up: 3, notices: 0 } : null }));
  await t.render("views/bibliography.js", "renderBibliography");
  await t.click("Check for retractions");
  await t.click("Use another collection or file");
  await t.settle(50);
  const card0 = t.view.querySelector(".bib-pick");
  const one = t.view.querySelector("#bib-one");
  if (one && !one.checked) await t.click(one);
  await t.settle(50);
  const search = t.view.querySelector(".bib-pick input[type=search]");
  await t.type(search, "craft", { wait: 600 });
  search.focus();
  state = "done";
  await t.settle(1500);
  const card1 = t.view.querySelector(".bib-pick");
  const s1 = t.view.querySelector(".bib-pick input[type=search]");
  return { same: card0 === card1, search: s1 ? s1.value : null, focused: !!s1 && document.activeElement === s1,
    one: !!t.view.querySelector("#bib-one") && t.view.querySelector("#bib-one").checked,
    zoteroAsked: t.calls.filter((c) => c.path === "/api/zotero").length };
});

// ---- New codebook from the themes, after a refusal ------------------------------------------------------------------
await scenario("codebooks: the themes ticked and the names chosen stay after a refusal", async (t) => {
  const CB = "/api/projects/Study/codebooks";
  t.state({ settings: {} });
  t.answer(`GET ${CB}`, { codebooks: [] });
  t.answer(`GET ${CB}/sources`, () => ({ runs: [{ here: true, project: "Study", created_at: "2026-11-10T10:00:00Z", themes: [
    { name: "Repair of bicycles", size: 9, names: ["Repair", "Repair of bicycles"], pick: 0, sure: true, code: { code: "Repair", description: "", described: false, keywords: ["repair"] } },
    { name: "Waste", size: 5, names: ["Waste"], pick: 0, sure: true, code: { code: "Waste", description: "", described: false, keywords: ["waste"] } }] }] }));
  let n = 0;
  t.answer(`POST ${CB}`, () => { n += 1; return n === 1 ? t.fail(400, "A removed codebook called 'repair' still has its labels: choose another name.") : { codebook: { name: "repair2", imported: null } }; });
  const m = await t.module("views/codebooks.js");
  m.newCodebook("themes");
  await t.settle();
  await t.type("Title", "Repair");
  await t.click("Next", { within: t.dialog() });
  await t.settle();
  const boxes = () => t.dialog().querySelectorAll(".cb-theme input[type=checkbox]");
  await t.click(boxes()[1]);                                               // Waste left out (every theme starts ticked)
  await t.click("Repair of bicycles: more specific name");                 // the longer name for the first
  await t.click("Make the codebook", { within: t.dialog() });
  await t.settle();
  const said = t.text(t.dialog().querySelector(".field-error"));
  await t.click("Next", { within: t.dialog() });                            // after the refusal, the themes again
  await t.settle();
  const again = { ticks: boxes().map((b) => b.checked), names: t.dialog().querySelectorAll(".cb-theme-code").map((x) => t.text(x)) };
  return { said, again, sent: t.calls.filter((c) => c.method === "POST").map((c) => c.body.source.codes.map((x) => x.code)) };
});

// ---- item 9: removing a project while a background round brings it up to date --------------------------------------
await scenario("projects: removing a project during a background round", async (t) => {
  t.state({ settings: {}, projects: [{ name: "Study", ok: true, documents: 1, hypotheses: 0, path: "/data/Study", temporary: { expires_at: 1800000000 } }] });
  t.answer("DELETE /api/projects/Study", t.fail(409, "“Study” is being brought up to date with your team: try again in a moment.", { kind: "busy", job_id: "j9" }));
  await t.render("views/projects.js", "renderProjects");
  const rms = t.view.querySelectorAll("button").filter((b) => t.text(b) === "Remove");
  await t.click(rms.find((b) => !b.disabled) || rms[0]);
  const typed = t.dialog().querySelector("input");
  if (typed) await t.type(typed, typed.getAttribute("aria-label").replace(/^Type (.*) to confirm$/, "$1"));
  await t.click(t.dialog().querySelector("#dlg-confirm"));
  await t.settle();
  return { note: t.text(t.view.querySelector(".pj-busy")), toasts: t.toasts() };
});

// ---- item 10: the rest of notes/pagesb.md ("Not proven") ----------------------------------------------------------
await scenario("owner: the section's heading counts the cards shown, the team line what waits", async (t) => {
  const st = await t.module("views/owner-state.js");
  const v = { owner: { id: "a", name: "Anna" }, is_owner: true, role: "owner", can_write: true, proposals: [], refused: [], clashes: [], offers: [],
    questions: [{ id: "q1", kind: "other", seq: 2, owner: "c", by: "c", now: null }] };
  const box = st.inbox(v, new Set(["q1"]));        // the question put off with Not now
  return { heading: st.heading(v, box.cards), count: st.tabCount(v, new Set(["q1"])), fresh: st.tabCount(v, new Set()) };
});

await scenario("concepts: an older glossary request that fails late does not draw over a newer one", async (t) => {
  t.state({ settings: {}, projects: [{ name: "Study", ok: true, documents: 3 }] });
  const late = held();
  const ok = { built: true, total: 0, items: [], offset: 0, terms: 4, concepts: 0, built_at: "2026-11-18T10:00:00Z" };
  t.answer("GET /api/projects/Study/terms?*", (b, path) => (path.includes("sort=mentions") ? late.promise.then(() => t.fail(404, "Not found: Study")) : ok));
  t.answer("GET /api/projects/Study/terms/words", { languages: [], off: [], own: [], max_own: 500 });
  await t.render("views/concepts.js", "renderConcepts", [], {});
  const sel = t.field("Sort the concepts");
  await t.type(sel, "mentions");                   // asked, answers late
  await t.type(sel, "name");                       // asked after, answers at once
  late.release();
  await t.settle(50);
  return t.text(t.view);
});

await scenario("concept map: the number of concepts keeps the zoom", async (t) => {
  await conceptMap(t);
  const svg = () => t.view.querySelector("svg.cm-svg");
  const whole = svg().getAttribute("viewBox");
  await t.click("Zoom in");
  const zoomed = svg().getAttribute("viewBox");
  await t.type(t.field("Concepts on the map"), "100");
  await t.settle(50);
  return { whole, zoomed, after: svg().getAttribute("viewBox"), maps: t.calls.filter((c) => c.path.startsWith(`${CM}?`)).length };
});

await scenario("documents: two files of one name and size from two folders are both listed", async (t) => {
  await documents(t, []);
  const input = t.view.querySelector("#src-files");
  input.files = [new File(["aaa"], "notes.pdf", { lastModified: 1700000000000 }), new File(["bbb"], "notes.pdf", { lastModified: 1760000000000 })];
  input.dispatchEvent(new Event("change"));
  await t.settle();
  const two = t.view.querySelectorAll(".file-list li").length;
  input.files = [new File(["aaa"], "notes.pdf", { lastModified: 1700000000000 })];   // the same file picked again
  input.dispatchEvent(new Event("change"));
  await t.settle();
  return { two, again: t.view.querySelectorAll(".file-list li").length };
});

const DOCV = { doc_id: "d1", title: "Repair", file: "r.txt", kind: "txt", n_pages: 1, blocks: [{ start: 0, end: 10, text: "Repair it.", kind: "p", page: 1 }],
  total_blocks: 1, offset: 0, text_length: 10, ai_access: "cloud" };
async function docPage(t, project) {
  t.state({ settings: {} }, { project });
  t.answer(/^GET /, {});
  t.answer(`GET /api/projects/${encodeURIComponent(project)}/documents/d1?*`, DOCV);
  await t.render("views/doc-page.js", "renderDocument", ["d1"], {});
  await t.settle(50);
}
await scenario("documents: a place kept for a document is not used in a copy of its project", async (t) => {
  const sh = await t.module("views/doc-shared.js");
  t.state({ settings: {} });
  sh.keep.place = { project: "Study", doc: "d1", y: 500, tab: "reading", focus: "dv-read-h" };
  await docPage(t, "Copy of Study");
  const other = { scrolls: t.scrolls.filter((x) => x.to && x.to[1] === 500).length, left: sh.keep.place };
  sh.keep.place = { project: "Study", doc: "d1", y: 500, tab: "reading", focus: "dv-read-h" };
  await docPage(t, "Study");
  return { other, same: t.scrolls.filter((x) => x.to && x.to[1] === 500).length };
});
"""


@pytest.fixture(scope="module")
def page(tmp_path_factory):
    return run_views(PROBE, tmp_path_factory.mktemp("pagesb15"))


# ---- item 2 (the owner's): Remove… after a hand-over -----------------------------------------------------------------
@needs_node
def test_a_member_whose_copy_still_keeps_the_storage_keys_is_not_offered_remove(page):
    """docs/manual/roles.md: only the Owner (or a Co-owner) removes people. After a hand-over the old owner is a Member
    whose copy keeps the storage space's keys until its next round hands them on: no Remove there, and a line says
    where the keys go."""
    m = page["team: a Member whose copy still keeps the storage keys"]
    assert "Remove…" not in m["buttons"] and not any("Remove from the team" in x for x in m["menus"]), m
    assert "still keeps the storage space’s keys" in m["text"] and "Carol’s copy" in m["text"], m["text"]


@needs_node
def test_the_owner_and_a_co_owner_whose_copy_keeps_the_keys_are_offered_remove(page):
    o = page["team: the Owner whose copy keeps the storage keys"]
    assert sum("Remove from the team…" in x for x in o["menus"]) == 2, o          # Ben and Carol, in the More menu
    assert "still keeps the storage space" not in o["text"]
    c = page["team: a Co-owner whose copy keeps the storage keys"]
    assert c["buttons"].count("Remove…") == 2, c                                  # Remove… alone (no More menu)


def test_a_member_whose_copy_keeps_the_storage_keys_cannot_remove_a_colleague(team, tmp_path, monkeypatch):
    """The server, not only the page: after Anna hands the project to Carol and before her next round, Anna's copy
    still keeps the keys; a removal from it is refused in words, and nothing is removed. The round hands the keys to
    Carol (storage-space.md: "the keys go to the new owner's copy by themselves"), who can then remove."""
    from enlens_claims import ownership
    from enlens_claims.sync import folder, space

    anna, carol = team
    dave = Person(tmp_path, "Dave", monkeypatch)
    with anna:
        inv = space.invite(anna.ws)
    _join_new(dave, inv["link"])
    for p in (anna, carol, dave, anna, carol, dave):
        _round(p)
    with anna:
        dave_part = next(m["part"] for m in folder.status(anna.ws)["space"]["members"] if m["name"] == "Dave")
        ownership.hand_over(anna.ws, carol.id)
        assert folder.status(anna.ws)["space"]["keeper"]              # the keys have not gone yet
        with pytest.raises(space.SpaceProblem) as e:
            space.remove_member(anna.ws, dave_part)
        assert e.value.kind == "not_owner" and "only its owner (or a Co-owner) removes a colleague" in str(e.value)
        assert not any(m["removed"] for m in folder.status(anna.ws)["space"]["members"])
    _round(anna)
    with anna:
        assert not folder.status(anna.ws)["space"]["keeper"]          # handed on at the round
    _round(carol)
    with carol:
        assert folder.status(carol.ws)["space"]["keeper"]
        space.remove_member(carol.ws, dave_part)
        assert [m["name"] for m in folder.status(carol.ws)["space"]["members"] if m["removed"]] == ["Dave"]


# ---- item 3 (phase 0 P-7): "Use both computers…" ----------------------------------------------------------------------
@needs_node
def test_use_both_computers_is_offered_on_both_views_of_the_team_page(page):
    """Phase 0 P-7: `secondComputer` was never drawn. Both offers were there all the same (Activity's notice, and a
    copy of the function inline in People); the People one now uses the function."""
    assert page["team: another computer, Activity"] == 1
    assert page["team: another computer, People and settings"] == 1


# ---- item 1 (the owner's): short text lost on a failed save -----------------------------------------------------------
@needs_node
def test_a_hand_over_refused_keeps_the_reason_in_its_dialog(page):
    r = page["team: a hand-over refused keeps the reason typed"]
    assert r["open"] and r["reason"] == "I am leaving the project in December", r
    assert "has not sent anything yet" in r["said"], r
    assert r["posts"] == [{"to": "b", "why": "I am leaving the project in December"}]
    ok = page["team: a hand-over that works closes its dialog and says so"]
    assert ok["open"] == 0 and any("Ben is the owner now" in x for x in ok["toasts"]), ok
    assert ok["posts"] == [{"to": "b", "why": "I am leaving"}]


@needs_node
def test_a_document_removal_refused_keeps_the_why_in_its_dialog(page):
    r = page["documents: a removal refused keeps the why typed"]
    assert r["open"] and r["why"] == "the wrong version" and "removed meanwhile" in r["said"], r


@needs_node
def test_a_codebook_removal_refused_keeps_the_why_in_its_dialog(page):
    r = page["codebook: a removal refused keeps the why typed"]
    assert r["open"] and r["why"] == "made by mistake" and "restarted" in r["said"], r


@needs_node
def test_an_unshare_refused_keeps_the_why_in_its_dialog(page):
    r = page["share: an unshare refused keeps the why typed"]
    assert r["open"] and r["why"] == "not ready yet" and "Not found" in r["said"], r


@needs_node
def test_a_groups_new_name_refused_stays_in_its_dialog(page):
    r = page["concept map: a group's new name refused stays in its dialog"]
    assert r["open"] and r["name"] == "Repair cafés and their neighbours" and "shorter name" in r["said"], r
    ok = page["concept map: a group's new name saved closes the dialog"]
    assert ok["open"] == 0 and ok["sent"] == ["Repair cafés"] and any(x.startswith("Group renamed.") for x in ok["toasts"]), ok


# ---- handed on ------------------------------------------------------------------------------------------------------
@needs_node
def test_accepting_a_proposed_relation_sends_which_relation_the_card_showed(page):
    """The server records the relation accepted only when the page names the row's source (`terms.set_link`)."""
    assert page["concepts: accepting a proposed relation says which one"] == [
        {"a": "t1", "b": "t2", "decision": "accept", "source": "pattern"}]


@needs_node
def test_a_label_run_given_back_to_a_second_look_is_followed_once(page):
    r = page["profile: a label run found running while its start answers is followed once"]
    assert r == {"ends": 1, "toasts": 1}, r


@needs_node
def test_a_clashing_label_run_is_refused_in_the_servers_words(page):
    r = page["profile: a second labelling with the same codebook refused in words"]
    assert any("labels passages with the codebook sdg already" in x for x in r["toasts"]) and r["again"], r


@needs_node
def test_the_group_names_job_already_running_is_followed_not_started_again(page):
    """NOT A BUG: a names job found running (another tab's, or the one the server gives back to a second press) is
    followed, and the button stays busy, so no second press and no second panel."""
    r = page["concept map: the names job given back to a second press is followed once"]
    assert r["busy"] == "true" and r["posts"] == 0, r
    assert sum(x.startswith("The AI drafted names") for x in r["toasts"]) == 1, r


@needs_node
def test_the_summary_of_an_add_gives_the_servers_note_on_earlier_documents(page):
    text = page["documents: the summary of an add gives the server's note"]
    assert "3 earlier documents of this project still follow a default nobody chose" in text, text


# ---- item 4: redraws that take the focus or the choices ---------------------------------------------------------------
@needs_node
def test_a_tick_keeps_the_focus_when_the_documents_list_is_drawn_again(page):
    r = page["documents: a tick keeps the focus when the list is drawn again after an add"]
    assert r["tick"] == "d2" and r["checked"], r


@needs_node
def test_read_at_most_keeps_its_focus_and_words_when_the_card_is_drawn_again(page):
    r = page["profile: Read at most keeps the focus and what is typed when a comparison ends"]
    assert r == {"value": "3", "focused": True}, r


@needs_node
def test_the_zotero_chooser_keeps_its_search_and_ticks_when_a_retraction_check_ends(page):
    r = page["bibliography: the Zotero chooser keeps its search and ticks when a retraction check ends"]
    assert r["same"] and r["search"] == "craft" and r["focused"] and r["one"], r
    assert r["zoteroAsked"] == 1, r


# ---- item 5: New codebook "From the themes" after a refusal -----------------------------------------------------------
@needs_node
def test_new_codebook_from_the_themes_keeps_the_ticks_and_names_after_a_refusal(page):
    r = page["codebooks: the themes ticked and the names chosen stay after a refusal"]
    assert "choose another name" in r["said"], r
    assert r["again"] == {"ticks": [True, False], "names": ["Repair of bicycles", "Waste"]}, r
    assert r["sent"] == [["Repair of bicycles"]], r


# ---- item 9: the page side of this round's server changes -----------------------------------------------------------
@needs_node
def test_removing_a_project_during_a_background_round_says_to_try_again_in_a_moment(page):
    r = page["projects: removing a project during a background round"]
    assert "try again in a moment" in r["note"], r


# ---- item 10: the rest of notes/pagesb.md ------------------------------------------------------------------------
@needs_node
def test_the_owner_sections_heading_counts_the_cards_and_the_team_line_what_waits(page):
    """NOT A BUG (notes "Not proven" 2): owner-state.js `tabCount` says a question put off with *Not now* no longer
    counts on the team line, while its card still shows in the section, whose heading counts the cards shown."""
    r = page["owner: the section's heading counts the cards shown, the team line what waits"]
    assert r == {"heading": "Waiting for your word (1)", "count": 0, "fresh": 1}, r


@needs_node
def test_an_older_glossary_request_failing_late_does_not_draw_over_a_newer_one(page):
    text = page["concepts: an older glossary request that fails late does not draw over a newer one"]
    assert "Not found" not in text and "0 concepts." in text, text


@needs_node
def test_the_number_of_concepts_on_the_map_keeps_the_zoom(page):
    """NOT A BUG (notes "Not proven" 7): concept-map.js says the zoom stays "until Whole map, or a map of other
    filters"; the number of concepts is how many of the same map are drawn, so the part zoomed into stays in view."""
    r = page["concept map: the number of concepts keeps the zoom"]
    assert r["zoomed"] != r["whole"] and r["after"] == r["zoomed"] and r["maps"] == 2, r


@needs_node
def test_two_files_of_one_name_and_size_from_two_folders_are_both_listed(page):
    r = page["documents: two files of one name and size from two folders are both listed"]
    assert r == {"two": 2, "again": 2}, r


@needs_node
def test_a_place_kept_for_a_document_is_not_used_in_a_copy_of_its_project(page):
    """notes "Not proven" 9: `keep.place` was keyed by the document's id alone, and a copy of a project has the same
    ids: the page of the copy took the scroll, tab and focus kept for the original."""
    r = page["documents: a place kept for a document is not used in a copy of its project"]
    assert r == {"other": {"scrolls": 0, "left": None}, "same": 1}, r


# ---- item 6: old labels -------------------------------------------------------------------------------------------
def test_the_changelog_tells_people_to_look_again_at_labels_given_before_the_fix():
    """OLD DATA: NOTE KEPT. A label stores only its span; nothing records where the person had selected, so a label
    on the first of two places cannot be told from one meant there."""
    text = (ROOT / "changes" / "hunt-phase-1-pagesb.md").read_text(encoding="utf-8")
    assert "labels given this way before keep their place" in " ".join(text.split())


# ---- item 7: a label on a selection that cuts a word ------------------------------------------------------------------
TEXT = ("At the start of repair work the volunteers met in the hall. "
        "Later they spoke at length about the art of repair itself and what it asks.")


def _one_passage(tmp_path):
    from enlens_claims import home, ingest

    ws = home.create_project("Study")
    src = tmp_path / "hall.txt"
    src.write_text(TEXT, encoding="utf-8")
    ingest.ingest(ws, [src])
    p = next(r for r in ws.query("SELECT passage_id, doc_id, start, text FROM passages") if "start of repair" in r["text"])
    return ws, p


def test_a_label_on_a_selection_cutting_a_word_lands_where_it_was_selected(tmp_path):
    """reviews/surface.md note: the search near the selection matched whole words only. "art of repair" selected inside
    "start of repair" (the first sentence), with "art of repair" standing whole later in the passage: the label went
    to the later place."""
    from enlens_claims import profile

    ws, p = _one_passage(tmp_path)
    at = p["start"] + p["text"].index("start of repair") + 2           # "art of repair", cut out of "start"
    profile.add_label(ws, "sdg", p["passage_id"], "12.5", quote="art of repair", start=at)
    got = ws.query("SELECT start, end, quote FROM labels WHERE source='person'")
    want = p["start"] + p["text"].index("start of repair")
    assert [(r["start"], r["end"]) for r in got] == [(want, want + len("start of repair"))], [dict(r) for r in got]


def test_a_note_on_a_selection_cutting_a_word_lands_where_it_was_selected(tmp_path):
    """The sibling: a note sends its place too (notes.add) and met the same search."""
    from enlens_claims import notes

    ws, p = _one_passage(tmp_path)
    doc_text = ws.scalar("SELECT text FROM documents WHERE doc_id=?", (p["doc_id"],))
    at = doc_text.index("start of repair") + 2
    n = notes.add(ws, p["doc_id"], at, at + len("art of repair"), quote="art of repair", text="the start, not the art")
    assert (n["start"], n["end"]) == (at - 2, at - 2 + len("start of repair")), n
