"""Hunt phase 1.5, area `pagesa`: what phases 0 and 1 left on the page's shell, results, hypotheses, settings and
set-up. Each test asserts what the page should do; the ledger (.claude/audits/2026-11-19-phase1.5/ledger/pagesa.md)
says, per item, whether the test failed and what was changed. The views run in Node under the fake DOM of
tests/_views.py."""
from __future__ import annotations

import pytest

from _views import needs_node, run_views

PROBE = r"""
// ---- item 1: the first-run page, a model just downloaded ------------------------------------------------------
await scenario("first run: a model just downloaded", async (t) => {
  t.state({ settings: { backend: "auto", threshold: 0.6 }, projects: [] }, { project: null });
  const OLL = { kind: "ollama", url: "http://localhost:11434", version: "0.5", embedding_models: [] };
  let pulled = false;
  t.answer("GET /api/servers", () => ({ servers: [{ ...OLL, chat_models: pulled ? ["qwen3:8b"] : [] }],
    suggested: [{ use: "chat", name: "qwen3:8b", size: "5 GB" }] }));
  t.answer("GET /api/jobs", { jobs: [] });
  t.answer("PUT /api/settings", {});
  t.answer("POST /api/servers/test", { model_available: true });
  t.answer("POST /api/servers/pull", { job: { id: "pl", kind: "model-pull", state: "running", progress: {} } });
  t.answer("GET /api/jobs/pl", () => (pulled ? { id: "pl", kind: "model-pull", state: "done", result: { models: ["qwen3:8b"], url: OLL.url, chosen: "qwen3:8b" } }
    : { id: "pl", kind: "model-pull", state: "running", progress: {} }));
  await t.render("views/setup.js", "renderSetup", []);
  await t.settle(50);
  await t.click(/^Download qwen3:8b/);
  pulled = true;
  await t.settle(2500);
  const sent = t.calls.filter((c) => c.method !== "GET").map((c) => `${c.method} ${c.path}`);
  return { sent, text: t.text(t.view), buttons: t.buttons(t.view), focus: t.focused() };
});

// ---- item 6: a consent dialog when the app could not say whether the project is shared -------------------------
await scenario("consent dialog when the project could not be looked at", async (t) => {
  t.state({ settings: { backend: "claude_code", threshold: 0.6 } });
  t.answer("GET /api/projects/Study", t.fail(500, "database is locked"));
  const S = await t.module("views/settings.js");
  const asked = S.agentConsent("codex");
  await t.settle(50);
  const d = t.dialog();
  const text = d ? t.text(d) : "";
  if (d) await t.click(/^Keep the AI/, { within: d });
  await asked;
  return { text };
});

// ---- item 3: short optional text kept on a failed save -------------------------------------------------------
const TH = "/api/projects/Study/themes";
const THEME = (o) => ({ theme_id: 1, name: "repair · tools", name_source: "terms", size: 10, terms: ["repair", "tools"], passages: [], docs: 1, documents: [], ...o });
async function themeList(t) {
  t.state({ settings: { backend: "baseline" } });
  t.answer(`GET ${TH}`, { runs: [{ run_id: "r1" }], frameworks: [] });
  t.answer(`GET ${TH}/r1?*`, { run: { run_id: "r1", created_at: "2026-11-15T10:00:00Z", passages: 40, mode: "meaning" }, documents: [{ doc_id: "d1" }],
    themes: [THEME(), THEME({ theme_id: 2, name: "cafés · community" })], removed: [] });
  t.answer("GET /api/projects/Study/frameworks", { frameworks: [] });
  t.answer("GET /api/projects/Study/sharing/themes/r1", { shared: false });
  t.answer("GET /api/projects/Study/shared-folder", { folder: null });
  t.answer("GET /api/projects/Study/sync-poller", t.fail(404, "none"));
  t.answer(`PUT ${TH}/r1/edit`, t.fail(500, "database is locked"));
  await t.render("views/themes.js", "renderThemes", [], {});
}
async function themePage(t) {
  t.state({ settings: { backend: "baseline" } });
  t.answer(`GET ${TH}/r1/1?*`, { theme: THEME(), others: [THEME({ theme_id: 2, name: "cafés · community" })], passages: [], total: 0, offset: 0 });
  t.answer("GET /api/projects/Study/sharing/themes/r1", { shared: false });
  t.answer("GET /api/projects/Study/shared-folder", { folder: null });
  t.answer("GET /api/projects/Study/sync-poller", t.fail(404, "none"));
  t.answer(`PUT ${TH}/r1/edit`, t.fail(500, "database is locked"));
  await t.render("views/themes.js", "renderTheme", ["r1", "1"], {});
}
// the dialog (and its words) after a failed save, and how many saves were sent
const afterFail = async (t, field, words, press) => {
  const d = t.dialog();
  const f = d.querySelector(field);
  f.value = words;
  f.dispatchEvent(new Event("input", { bubbles: true }));
  await t.click(press, { within: d });
  await t.settle(50);
  const again = t.dialog();
  return { open: !!again, words: again ? again.querySelector(field).value : null, sent: t.calls.filter((c) => c.method === "PUT").length };
};
await scenario("theme list: rename fails", async (t) => {
  await themeList(t);
  await t.click("Rename", { within: t.view.querySelector(".th-acts") });
  return afterFail(t, "input", "Tools and skills", "Save");
});
await scenario("theme page: rename fails", async (t) => {
  await themePage(t);
  await t.click("Rename");
  return afterFail(t, "input", "Tools and skills", "Save");
});
await scenario("theme page: remove with a reason fails", async (t) => {
  await themePage(t);
  await t.click("Remove…");
  return afterFail(t, "textarea", "boilerplate from the cover pages", "Just remove it");
});

// ---- handed on: what the connector's refusal sends the person to on the Documents page ----------------------------
await scenario("documents page: where a document's AI setting is changed", async (t) => {
  t.state({ settings: {} });
  t.answer(/.*/, {});
  t.answer("GET /api/projects/Study", { search: null, passages: 4, ai_access: { chosen: true, default: "local" } });
  t.answer(/^GET \/api\/projects\/Study\/documents(\?.*)?$/, { documents: [{ doc_id: "d1", title: "Interview 3", file: "i3.pdf", kind: "pdf", ai_access: "local", passages: 4 }],
    ai_access: { chosen: true, default: "local" }, new_reader: 7 });
  t.answer(/^GET \/api\/projects\/Study\/document-roles/, { roles: {}, nonscientific: [] });
  t.answer("GET /api/projects/Study/nonscientific-suggestions", { suggested: {} });
  t.answer("GET /api/projects/Study/map/documents?*", t.fail(404, "no answers yet"));
  await t.render("views/sources.js", "renderSources");
  await t.settle(50);
  const add = t.allText(t.view);
  const toggle = t.view.querySelector(".doc-toggle");
  if (toggle) await t.click(toggle);
  await t.settle(50);
  const acc = t.view.querySelector(".doc-access");
  return { add, access: acc ? [acc.getAttribute("aria-label") || "", ...acc.querySelectorAll("[aria-label]").map((x) => x.getAttribute("aria-label")), t.allText(acc)].join(" | ") : "" };
});

// ---- handed on: Settings › Technical lists the add-ons that could not be loaded ----------------------------------
const TECH = async (t, problems) => {
  t.state({ settings: { backend: "baseline", threshold: 0.6 }, addon_problems: problems });
  t.answer(/.*/, {});
  t.answer("GET /api/servers", { servers: [] });
  t.answer("GET /api/routing", { route: "baseline", route_name: "No AI", rows: [], aliases: [], step_up_below: 0.6, plan: {} });
  await t.render("views/settings.js", "renderSettings", ["installation"]);
  await t.settle(100);
  const card = t.view.querySelector("#s-installation");
  return { text: card ? t.allText(card) : null, lines: card ? card.querySelectorAll(".addon-problem").map((x) => t.allText(x)) : null };
};
await scenario("settings: add-on problems", async (t) => TECH(t, [{ addon: "sdg", error: "No module named 'sdgpack'" },
  { addon: "fieldwork", error: "its columns clash with another add-on", project: "Study" }]));
await scenario("settings: no add-on problems", async (t) => TECH(t, []));

// ---- item 4: phase 0's P-2, P-3, P-5 ------------------------------------------------------------------------------
// P-2: the queue's 5-second look, answered late, after an action whose own redraw came first
await scenario("queue: an older look answered after a newer action", async (t) => {
  t.state({ settings: { backend: "claude_code", threshold: 0.6 } });
  t.answer(/.*/, {});
  t.answer("GET /api/local-status", { same_as_main: true });
  t.answer("GET /api/jobs", { jobs: [] });
  const Q = (held) => ({ waiting: 5, being_answered: 0, order: ["label"], runner: {}, kinds: [{ kind: "label", title: "Labels", waiting: 5, held }] });
  let slow = false, held = false, release = null;
  t.answer("GET /api/projects/Study/queue", () => {
    const now = Q(held);   // what the app says when it is asked
    if (slow) { slow = false; return new Promise((res) => { release = () => res(now); }); }   // the look, answered late
    return now;
  });
  t.answer("POST /api/projects/Study/queue/order", () => { held = true; return {}; });
  const { queueSection } = await t.module("views/queue.js");
  document.getElementById("view").appendChild(queueSection());
  await t.settle(100);
  slow = true;
  await t.settle(5000);            // the look starts and waits for its answer
  await t.click("Hold");           // the person holds the kind: its own look answers at once
  await t.settle(50);
  const after = t.labels(document.querySelector(".queue-section"));
  release();
  await t.settle(50);
  return { after, later: t.labels(document.querySelector(".queue-section")) };
});
// P-3: a first pick whose save fails after a second pick was saved
const SLOW_FAIL = (t) => new Promise((res, rej) => setTimeout(() => rej(new Error("The app is not answering.")), 2000));
await scenario("speed: a failed first pick after a saved second", async (t) => {
  t.state({ settings: { backend: "claude_code" } });
  let n = 0;
  const el = t.LIB.speedPicker("normal", undefined, () => (++n === 1 ? SLOW_FAIL(t) : Promise.resolve({})));
  document.getElementById("view").appendChild(el);
  await t.click("Faster");
  await t.click("Slower");
  await t.settle(2500);
  return { checked: el.querySelector('[aria-checked="true"]') ? t.allText(el.querySelector('[aria-checked="true"]')) : null };
});
await scenario("thought: a failed first pick after a saved second", async (t) => {
  t.state({ settings: { backend: "claude_code" } });
  let n = 0;
  const el = t.LIB.thoughtPicker("balanced", () => (++n === 1 ? SLOW_FAIL(t) : Promise.resolve({})));
  document.getElementById("view").appendChild(el);
  await t.click("Intelligence");
  await t.click("Energy efficient");
  await t.settle(2500);
  return { checked: el.querySelector('[aria-checked="true"]') ? t.allText(el.querySelector('[aria-checked="true"]')) : null };
});
await scenario("settings: sharing the work, a failed first pick after a saved second", async (t) => {
  t.state({ settings: { backend: "claude_code", allow_claude_code: true, restricted_server: "http://localhost:11434", restricted_model: "qwen3:8b", ai_mix: "best", threshold: 0.6 } });
  t.answer(/.*/, {});
  t.answer("GET /api/servers", { servers: [] });
  let n = 0;
  t.answer("PUT /api/settings", (body) => (body.ai_mix && ++n === 1 ? new Promise((res) => setTimeout(() => res(t.fail(500, "The app is not answering.")), 2000)) : { settings: { ...t.LIB.App.state.settings, ...body } }));
  await t.render("views/settings.js", "renderSettings", ["mix"]);
  await t.settle(100);
  const mix = t.view.querySelector("#s-mix");
  if (!mix) return { checked: "no #s-mix" };
  await t.click("Mostly local", { within: mix });
  await t.click("Balanced", { within: mix });
  await t.settle(2500);
  const on = mix.querySelector('[aria-checked="true"]');
  return { checked: on ? t.allText(on) : null };
});
// P-5: a local side waiting for its Start, drawn again (a count changed) before its nudge was due
await scenario("local side drawn again keeps when its wait began", async (t) => {
  t.state({ settings: { backend: "claude_code" } });
  const o = { where: "local", model: "qwen3:8b", noun: "task", count: 3, onStart: () => {} };
  const real = Date.now;
  let now = real();
  Date.now = () => now;   // the page's clock moves with the test's timers
  const wait = async (ms) => { now += ms; await t.settle(ms); };
  try {
    const el = t.LIB.aiSide(o);
    document.getElementById("view").appendChild(el);
    await wait(3000);
    t.LIB.redrawSide(el, { ...o, count: 4 });
    await wait(3000);   // 6 s since the wait began: the nudge (after 5 s) is due
    const b = el.querySelector(".ar-start button");
    return { nudged: !!b && b.classList.contains("ar-nudge") };
  } finally { Date.now = real; }
});

// ---- the result page (as tests/test_hunt1_pagesa.py builds it) ---------------------------------------------------
const TWICE = "Volunteers fix toasters for free. Neighbours also fix toasters at home.";
const PX = (o) => ({ passage_id: "p1", doc_id: "d1", title: "Repair report", text: "Volunteers fix toasters for free.", quote: "Volunteers fix toasters",
  quote_start: 0, quote_end: 23, verdict: "supports", ai_verdict: "supports", confidence: 0.9, counted: true, read_by: "claude-sonnet",
  in_corpus: true, page: 3, round: 1, found_by: "keywords", ...o });
const RESULT = (passages, o = {}, part = {}) => ({ hyp_id: "h1", text: "Repair cafés build community", status: "supported", threshold: 0.6, options: {},
  decomposed: false, model: "claude-sonnet",
  parts: [{ claim_id: "c1", part: 1, claim: "Repair cafés build community", status: "supported", passages, rounds_info: [], model: "claude-sonnet", ...part }], ...o });
const H = "/api/projects/Study/hypotheses/h1";
async function result(t, answer, settings = {}, query = {}, state = {}) {
  t.state({ settings: { threshold: 0.6, ...settings }, ...state });
  t.answer("GET /api/projects/Study/retractions", { by_doc: {} });
  t.answer("GET /api/projects/Study/sharing/check/h1", { shared: false });
  t.answer(/^GET \/api\/projects\/Study\/documents\/[^/]+\/file\?check=1$/, t.fail(404, "no file"));
  t.answer(`GET ${H}/unread`, { documents: [] });
  t.answer("GET /api/servers", { servers: [] });
  t.answer("GET /api/projects/Study/shared-folder", { folder: null });
  t.answer("GET /api/projects/Study/sync-poller", t.fail(404, "none"));
  t.answer("GET /api/local-status", { running: false, models: [] });
  t.answer(`GET ${H}?*`, typeof answer === "function" ? answer : () => answer);
  await t.render("views/result.js", "renderResult", ["h1"], query);
}
const card = (t, id) => t.view.querySelector(`[data-passage="${id}"]`);
// the text node of an excerpt's card that holds `words` after its highlight, and where in it they stand the last time
function lastIn(t, id, words) {
  const nodes = [];
  const walk = (n) => { for (const c of n.childNodes) { if (c.nodeType === 3) nodes.push(c); else walk(c); } };
  walk(card(t, id).querySelector(".passage"));
  const node = nodes.filter((n) => n.data.includes(words)).pop();
  const at = node.data.lastIndexOf(words);
  return [node, at, at + words.length];
}

// ---- item 3: the "Read this again" hint, when the re-read could not be started --------------------------------
await scenario("re-read hint when the re-read fails", async (t) => {
  const puts = [];
  t.answer("PUT /api/projects/Study/claims/c1/judgements/p1", (body) => { puts.push(body); return { moved: null }; });
  t.answer("POST /api/projects/Study/claims/c1/reread/p1", t.fail(500, "database is locked"));
  await result(t, RESULT([PX({ user_verdict: "supports", my_verdict: "supports", reviewed: true })]));
  await t.click("Details", { within: card(t, "p1") });
  await t.click("Read this again…", { within: card(t, "p1") });
  const out = await (async () => {
    const d = t.dialog();
    const f = d.querySelector("#reread-note");
    f.value = "the next sentence says the opposite";
    f.dispatchEvent(new Event("input", { bubbles: true }));
    await t.click("Read it again", { within: d });
    await t.settle(50);
    const again = t.dialog();
    return { open: !!again, words: again ? again.querySelector("#reread-note").value : null };
  })();
  // pressed again: the comment was saved the first time, so only the re-read is asked for again
  if (out.open) { await t.click("Read it again", { within: t.dialog() }); await t.settle(50); }
  out.puts = puts.length;
  out.posts = t.calls.filter((c) => c.method === "POST").length;
  return out;
});

// ---- item 5: the retraction notices of the project just left ------------------------------------------------------
await scenario("retractions of the project just left answered late", async (t) => {
  let release = null;
  t.answer(/^GET \/api\/projects\/Old\//, t.fail(404, "No such hypothesis"));
  t.answer("GET /api/projects/Old/retractions", () => new Promise((res) => { release = () => res({ by_doc: { d1: [{ type: "retraction", checked_at: "2026-11-01T10:00:00+00:00" }] } }); }));
  t.state({ settings: { threshold: 0.6 } }, { project: "Old" });
  const mod = await t.module("views/result.js");
  const left = document.createElement("div");
  mod.renderResult(left, ["h1"], {});   // the result of project Old, opened and left before its notices came
  await t.settle(10);
  t.LIB.App.project = "Study";
  await result(t, RESULT([PX()]));
  release();
  await t.settle(50);
  await t.click("Table");
  return { text: t.text(t.view) };
});

// ---- item 6: failures that only omit something ------------------------------------------------------------------
await scenario("original file: a failed look is asked again", async (t) => {
  let n = 0;
  t.answer(/file\?check=1$/, () => (++n === 1 ? t.fail(500, "database is locked") : { available: true, kind: "pdf", name: "report.pdf" }));
  const mod = await t.module("views/result.js");
  mod.forgetOriginals();
  const first = await mod.originalInfo("Study", "d9");
  const again = await mod.originalInfo("Study", "d9");
  return { first, again, asked: n };
});
await scenario("unread documents: a failed look is asked again", async (t) => {
  let n = 0;
  t.answer(`GET ${H}/unread`, () => (++n === 1 ? t.fail(500, "database is locked") : { checked: true, matching_n: 1, matching: [{ doc_id: "d7", title: "Field notes" }], no_word_n: 0, no_word: [] }));
  const r = RESULT([PX()]);
  t.state({ settings: { threshold: 0.6 } });
  t.answer("GET /api/projects/Study/retractions", { by_doc: {} });
  t.answer("GET /api/projects/Study/sharing/check/h1", { shared: false });
  t.answer(/^GET \/api\/projects\/Study\/documents\/[^/]+\/file\?check=1$/, t.fail(404, "no file"));
  t.answer("GET /api/servers", { servers: [] });
  t.answer("GET /api/projects/Study/shared-folder", { folder: null });
  t.answer("GET /api/projects/Study/sync-poller", t.fail(404, "none"));
  t.answer("GET /api/local-status", { running: false, models: [] });
  t.answer(`GET ${H}?*`, () => r);
  await t.render("views/result.js", "renderResult", ["h1"], {});
  await t.settle(50);
  const before = t.text(t.view).includes("never read in this check");
  await t.click("Table");
  await t.click("Cards");
  await t.settle(50);
  return { before, after: t.text(t.view).includes("never read in this check"), asked: n };
});
await scenario("result: running jobs could not be looked at when the page opened", async (t) => {
  let n = 0;
  const job = { id: "j3", project: "Study", kind: "second-opinion", state: "running", progress: {} };
  t.answer("GET /api/jobs", () => (++n === 1 ? t.fail(500, "database is locked") : { jobs: [job] }));
  t.answer("GET /api/jobs/j3", job);
  await result(t, RESULT([PX()], { excerpts_read: 1 }), { ollama_model: "llama", second_model: "qwen" });
  await t.settle(100);
  const at = !!t.view.querySelector(".ask-jobs");
  await t.settle(6000);
  return { at, later: !!t.view.querySelector(".ask-jobs"), asked: n };
});
await scenario("calibration that could not be worked out", async (t) => {
  t.state({ settings: { threshold: 0.6, backend: "baseline" } });
  t.answer(/.*/, {});
  t.answer("GET /api/projects/Study/calibration", t.fail(500, "database is locked"));
  await t.render("views/settings.js", "renderSettings", ["calibration"]);
  await t.settle(100);
  return { text: t.allText(t.view.querySelector("#s-calibration")) };
});
await scenario("queue: the gated job could not be looked at", async (t) => {
  t.state({ settings: { backend: "claude_code", threshold: 0.6, restricted_model: "qwen3:8b" } });
  t.answer(/.*/, {});
  t.answer("GET /api/local-status", { same_as_main: true });
  t.answer("GET /api/projects/Study/queue", { waiting: 0, being_answered: 2, order: [], runner: { running: true }, kinds: [] });
  let fail = false;
  const job = { id: "jg", project: "Study", kind: "check", state: "running", title: "Repair cafés build community", progress: {}, local: { gate: "wait", waiting: 3, noun: "excerpt", model: "qwen3:8b" } };
  t.answer("GET /api/jobs", () => (fail ? t.fail(500, "database is locked") : { jobs: [job] }));
  const { queueSection } = await t.module("views/queue.js");
  document.getElementById("view").appendChild(queueSection());
  await t.settle(100);
  const first = t.allText(document.querySelector(".queue-section"));
  fail = true;
  await t.settle(5100);
  return { first: first.includes("Repair cafés build community"), later: t.allText(document.querySelector(".queue-section")).includes("Repair cafés build community") };
});

// the Hypotheses page (as tests/test_hunt1_pagesa.py builds it)
const HYP_PAGE = (t, rows = [], frameworks = []) => {
  t.state({ settings: { threshold: 0.6, backend: "baseline" } });
  t.answer("GET /api/projects/Study", { frameworks, passages: 40 });
  t.answer("GET /api/projects/Study/documents", { documents: [{ doc_id: "d1", title: "Report" }] });
  t.answer("GET /api/projects/Study/hypotheses?*", { hypotheses: rows, counts: rows.length ? { supported: rows.length } : {} });
};
const typeIn = async (t, text) => { const ta = t.view.querySelector("#hyp"); ta.value = text; ta.dispatchEvent(new Event("input", { bubbles: true })); await t.settle(700); };
await scenario("hypotheses: suggested codes after a failed look", async (t) => {
  HYP_PAGE(t, [], [{ name: "sdg", title: "SDG targets", label: "target" }]);
  t.answer("GET /api/jobs", { jobs: [] });
  t.answer("POST /api/projects/Study/hypotheses/similar", { similar: [] });
  let n = 0;
  t.answer("GET /api/projects/Study/suggest?*", () => (++n === 1 ? t.fail(500, "database is locked") : { codes: [{ code: "12.5", description: "Reduce waste" }] }));
  await t.render("views/hypotheses.js", "renderHypotheses", [], {});
  await typeIn(t, "Repair cafés reduce waste");
  const before = t.allText(t.view).includes("Suggested:");
  await typeIn(t, "Repair cafés reduce household waste");
  return { before, after: t.allText(t.view).includes("Suggested:"), asked: n };
});
await scenario("hypotheses: the look for similar hypotheses failed", async (t) => {
  HYP_PAGE(t);
  t.answer("GET /api/jobs", { jobs: [] });
  t.answer("POST /api/projects/Study/hypotheses/similar", t.fail(500, "database is locked"));
  t.answer("POST /api/projects/Study/checks", { job: { id: "jc", project: "Study", kind: "check", state: "running", progress: {} } });
  t.answer("GET /api/jobs/jc", { id: "jc", project: "Study", kind: "check", state: "running", progress: {} });
  await t.render("views/hypotheses.js", "renderHypotheses", [], {});
  await typeIn(t, "Repair cafés reduce waste");
  await t.click("Check");
  await t.settle(100);
  return { checks: t.calls.filter((c) => c.method === "POST" && c.path.endsWith("/checks")).length };
});
await scenario("hypotheses: a list checked whose answers could not be listed", async (t) => {
  HYP_PAGE(t);
  t.answer("GET /api/jobs", { jobs: [] });
  t.answer("GET /api/projects/Study/hypotheses?batch=b1", t.fail(500, "database is locked"));
  t.answer("GET /api/jobs/jb", { id: "jb", project: "Study", kind: "batch", state: "done", seconds: 30, progress: {}, result: { batch_id: "b1", checked: [{}, {}], total: 2, errors: [] } });
  await t.render("views/hypotheses.js", "renderHypotheses", [], { job: "jb" });
  await t.settle(600);
  const box = t.view.querySelector(".hyp-summary-card");
  return { text: box ? t.text(box) : "", buttons: box ? t.labels(box) : [] };
});
await scenario("answers: a running check, the jobs could not be looked at", async (t) => {
  HYP_PAGE(t, [{ hyp_id: "h1", text: "Repair cafés build community", status: "supported", created_at: "2026-11-01T10:00:00+00:00", parts: 1, passages_read: 4, supports: 2 }]);
  let fail = false;
  const job = { id: "jr", project: "Study", kind: "check", state: "running", title: "Teleworking lowers car use", progress: {}, seconds: 5 };
  t.answer("GET /api/jobs", () => (fail ? t.fail(500, "database is locked") : { jobs: [job] }));
  t.answer("GET /api/jobs/jr", job);
  await t.render("views/hypotheses.js", "renderHypotheses", [], {});
  await t.settle(100);
  const box = t.view.querySelector(".hyp-answers");
  const first = t.text(box);
  fail = true;
  await t.settle(12000);
  return { first: first.includes("1 still being checked"), later: t.text(t.view.querySelector(".hyp-answers")).includes("1 still being checked"), looks: t.calls.filter((c) => c.path === "/api/jobs").length };
});

// ---- item 7: the window title and the badge of a check not finished --------------------------------------------
await scenario("window title of a check not finished", async (t) => {
  await result(t, RESULT([PX({ verdict: null, ai_verdict: null, counted: false })], { status: "not_checked" }), {}, {},
    { statuses: [{ status: "not_checked", text: "Not finished yet", help: "" }] });
  return { title: document.title, badge: t.text(t.view.querySelector(".answer .status-not_checked")) };
});

// ---- item 8: old data (PAGESA-1): what the page sends now when you choose Anna's verdict, with a sentence
await scenario("a colleague's verdict chosen as yours, with a sentence", async (t) => {
  const puts = [];
  t.answer("PUT /api/projects/Study/claims/c1/judgements/p1", (body) => { puts.push(body); return { moved: null }; });
  await result(t, RESULT([PX({ user_verdict: "refutes", verdict: "refutes", judged_by: "Anna", my_verdict: null, my_note: null, changed: true, reviewed: true })]));
  await t.click("Judge differently…", { within: card(t, "p1") });
  await t.click("Pick from a list", { within: card(t, "p1") });
  card(t, "p1").querySelector(".mark-list select").value = "0";
  await t.click("Use this sentence", { within: card(t, "p1") });
  await t.click("Contradicts", { within: card(t, "p1").querySelector(".judge-panel") });
  await t.settle(50);
  return { puts };
});

// ---- item 9: the look while a check waits for Claude Code, with a cursor left in a comment box ---------------------
await scenario("comment box focused while the check waits", async (t) => {
  let now = RESULT([PX()], { status: "waiting" });
  t.answer("GET /api/projects/Study/queue", { route: "claude_code", can_start: true, waiting: 3, being_answered: 0, runner: {} });
  await result(t, () => now, { backend: "claude_code" });
  await t.click("Judge differently…", { within: card(t, "p1") });
  const input = card(t, "p1").querySelector(".judge-note input");
  input.focus();
  now = RESULT([PX(), PX({ passage_id: "p4", title: "Third report" })], { status: "waiting" });
  await t.settle(5200);
  const looks = t.calls.filter((c) => c.method === "GET" && c.path.startsWith(`${H}?`)).length;
  const out = { looks, focusStays: document.activeElement === input, said: t.text(t.view).includes("New answers"), shownBefore: t.text(t.view).includes("Third report") };
  await t.click("Show them");
  await t.settle(50);
  out.shownAfter = t.text(t.view).includes("Third report");
  return out;
});

await scenario("retraction notices that could not be read", async (t) => {
  t.answer("GET /api/projects/Study/retractions", t.fail(500, "database is locked"));
  t.state({ settings: { threshold: 0.6 } });
  t.answer("GET /api/projects/Study/sharing/check/h1", { shared: false });
  t.answer(/^GET \/api\/projects\/Study\/documents\/[^/]+\/file\?check=1$/, t.fail(404, "no file"));
  t.answer(`GET ${H}/unread`, { documents: [] });
  t.answer("GET /api/servers", { servers: [] });
  t.answer("GET /api/projects/Study/shared-folder", { folder: null });
  t.answer("GET /api/projects/Study/sync-poller", t.fail(404, "none"));
  t.answer("GET /api/local-status", { running: false, models: [] });
  t.answer(`GET ${H}?*`, () => RESULT([PX()]));
  await t.render("views/result.js", "renderResult", ["h1"], {});
  return { toasts: t.toasts() };
});
await scenario("made with an earlier version, in an app built on ENLENS", async (t) => {
  t.state({ settings: {}, brand: { name: "Fieldnotes" }, version: "0.20.3" });
  return { text: t.allText(t.LIB.madeWithFact({ older: true, app_version: true, label: "0.18.0", version: "0.20.3" })) };
});

// ---- item 11: the rest of notes/pagesa.md ("Not proven") ----------------------------------------------------------
// double sends: Agree pressed twice while its save runs
await scenario("agree pressed twice while it saves", async (t) => {
  const puts = [];
  let release = null;
  t.answer("PUT /api/projects/Study/claims/c1/judgements/p1", (body) => { puts.push(body); return new Promise((res) => { release = () => res({ moved: null }); }); });
  await result(t, RESULT([PX()]));
  const agree = card(t, "p1").querySelector(".agree-main");
  agree.click(); agree.click();
  await t.settle(10);
  if (release) release();
  await t.settle(100);
  return { puts: puts.length, toasts: t.toasts().filter((x) => /Saved/.test(x)).length };
});
// a judgement saved, the page's look after it failed
await scenario("judgement saved, the result could not be fetched again", async (t) => {
  let fail = false;
  t.answer("PUT /api/projects/Study/claims/c1/judgements/p1", () => { fail = true; return { moved: null }; });
  await result(t, (b, path) => (fail ? t.fail(500, "database is locked") : RESULT([PX()])));
  await t.click("Not about this", { within: card(t, "p1") });
  await t.settle(100);
  return { toasts: t.toasts() };
});
// "Show the batch after", pressed twice before the first answer
await scenario("see what is sent: the batch after, pressed twice", async (t) => {
  t.state({ settings: { backend: "claude_code" } });
  const starts = [];
  let hold = null;
  t.answer("GET /api/projects/Study/queue/preview?*", (b, path) => {
    const st = Number(new URLSearchParams(path.split("?")[1]).get("start"));
    starts.push(st);
    const r = { title: "Labels", start: st, more: true, waiting: 6, being_answered: 0, tasks: [{ text: "a" }, { text: "b" }] };
    return st ? new Promise((res) => { hold = () => res(r); }) : r;
  });
  t.LIB.showSent("Study", "label");
  await t.settle(50);
  const more = document.querySelector("#sent-more");
  more.click(); more.click();
  await t.settle(10);
  if (hold) hold();
  await t.settle(50);
  return { starts };
});
// a number on a page opened in a German browser
await scenario("numbers in a browser set to German", async (t) => {
  const real = Number.prototype.toLocaleString;
  Number.prototype.toLocaleString = function (loc, o) { return real.call(this, loc || "de-DE", o); };
  try { return { n: t.LIB.fmt.num(1234567), plural: t.LIB.plural(1234, "document") }; } finally { Number.prototype.toLocaleString = real; }
});
// Stop on an AI run whose cancel the app refused
await scenario("stop of an AI run whose cancel failed", async (t) => {
  t.state({ settings: { backend: "claude_code" } });
  t.answer("POST /api/jobs/jx/cancel", t.fail(500, "database is locked"));
  const { aiRun } = await t.module("views/progress.js");
  let stopped = 0;
  const run = aiRun({ title: "Labelling", onStop: () => { stopped += 1; } });
  document.getElementById("view").appendChild(run.el);
  run.update({ id: "jx", state: "running", progress: {} });
  await t.click("Stop", { within: run.el });
  await t.settle(50);
  return { stopped, buttons: t.buttons(run.el) };
});

// ---- item 2: a quote kept where it was selected ------------------------------------------------------------------
// your own judgement exists; you select the SECOND "fix toasters" of the excerpt and press Use it
await scenario("quote selected where its words stand twice", async (t) => {
  const puts = [];
  t.answer("PUT /api/projects/Study/claims/c1/judgements/p1", (body) => { puts.push(body); return { moved: null }; });
  await result(t, RESULT([PX({ text: TWICE, user_verdict: "supports", my_verdict: "supports", reviewed: true })]));
  await t.click("Edit judgement…", { within: card(t, "p1") });
  t.select(...lastIn(t, "p1", "fix toasters"));
  await t.click("Use it", { within: card(t, "p1") });
  return { puts };
});
// no judgement of yours yet: the sentence waits on the card, then goes with the judgement you choose
await scenario("quote selected twice-standing, judgement chosen after", async (t) => {
  const puts = [];
  t.answer("PUT /api/projects/Study/claims/c1/judgements/p1", (body) => { puts.push(body); return { moved: null }; });
  await result(t, RESULT([PX({ text: TWICE })]));
  await t.click("Judge differently…", { within: card(t, "p1") });
  t.select(...lastIn(t, "p1", "fix toasters"));
  await t.click("Use it", { within: card(t, "p1") });
  const m = card(t, "p1").querySelector(".passage mark");
  const before = m && m.previousSibling ? m.previousSibling.textContent : "";   // the highlight shown while it waits
  await t.click("Contradicts", { within: card(t, "p1").querySelector(".judge-panel") });
  await t.settle(50);
  return { puts, before };
});
// a sentence picked from the list that stands twice in the excerpt: the second one
await scenario("sentence picked from the list stands twice", async (t) => {
  const puts = [];
  t.answer("PUT /api/projects/Study/claims/c1/judgements/p1", (body) => { puts.push(body); return { moved: null }; });
  const text = "Cafés fix many toasters. People come back often. Cafés fix many toasters.";
  await result(t, RESULT([PX({ text, quote: "People come back often", quote_start: 25, quote_end: 47, user_verdict: "supports", my_verdict: "supports", reviewed: true })]));
  await t.click("Edit judgement…", { within: card(t, "p1") });
  await t.click("Pick from a list", { within: card(t, "p1") });
  const pick = card(t, "p1").querySelector(".mark-list select");
  pick.value = "2";
  await t.click("Use this sentence", { within: card(t, "p1") });
  return { puts };
});
"""


# The shell (app.js), booted once per process (as tests/test_hunt1_pagesa.py APP_PROBE does)
SHELL = r"""
  for (const id of ["menu-btn", "topbar-project", "sidebar", "project-switch", "find-btn", "find-key", "nav", "nav-foot", "update-btn", "quit-btn", "theme-btn", "scrim", "main",
  "stopped-banner", "update-banner", "quicklook-banner"]) document.body.appendChild(Object.assign(document.createElement(/btn/.test(id) ? "button" : "div"), { id }));
const team = document.createElement("a"); team.id = "team-line"; document.getElementById("project-switch").appendChild(team);
const area = document.createElement("div"); area.id = "status-area";
for (const id of ["work-indicator", "privacy-indicator"]) area.appendChild(Object.assign(document.createElement("div"), { id }));
document.body.appendChild(area);
globalThis.BroadcastChannel = class { postMessage(m) { if (m && m.ask) setTimeout(() => this.onmessage && this.onmessage({ data: { token: "k".repeat(24) } }), 1); } close() {} };
"""
APP_QUIT = r"""
await scenario("quit when the app could not say what runs", async (t) => {
""" + SHELL + r"""
  t.state({ settings: { backend: "baseline", threshold: 0.6 }, can_quit: true, projects: [{ name: "Study", documents: 3, hypotheses: 1, ok: true }], queue: { waiting: 0 } }, { hash: "#/nowhere" });
  t.answer(/.*/, {});
  t.answer("GET /api/state", () => t.LIB.App.state);
  t.answer("GET /api/whats-new", { changes: null });
  await import(new URL("app.js", STATIC).href);
  await t.settle(1000);
  t.answer("GET /api/jobs", t.fail(500, "database is locked"));
  await t.click(document.getElementById("quit-btn"));
  await t.settle(50);
  const d = t.dialog();
  const out = { text: d ? t.text(d) : "" };
  if (d) await t.click("Cancel", { within: d });
  return out;
});
"""


@pytest.fixture(scope="module")
def page(tmp_path_factory):
    return run_views(PROBE, tmp_path_factory.mktemp("pagesa15"))


# ---------------------------------------------------------------------------------------------
# 1. the owner's: no model without a click
# ---------------------------------------------------------------------------------------------
@needs_node
def test_a_model_just_downloaded_on_the_first_run_page_waits_for_its_own_start(page):
    """Item 1: after a download on the first-run page, the page saved the settings and POSTed /api/servers/test at once
    (setup.js `if (opts.test) testBtn.click()`), which loads the model with no Start of its own. It must show the test
    button, ready, and say the model is there; nothing loads until the person presses it."""
    r = page["first run: a model just downloaded"]
    assert "POST /api/servers/test" not in r["sent"] and "PUT /api/settings" not in r["sent"], r["sent"]
    assert {"label": "Save and test", "disabled": False} in r["buttons"]
    assert "qwen3:8b is downloaded" in r["text"] and r["focus"]["label"] == "Save and test"


# ---------------------------------------------------------------------------------------------
# 2. the owner's: a quote kept where it was selected
# ---------------------------------------------------------------------------------------------
SECOND = "Volunteers fix toasters for free. Neighbours also fix toasters at home.".rindex("fix toasters")


@needs_node
def test_a_quote_selected_where_its_words_stand_twice_is_sent_with_where_it_was_selected(page):
    """Item 2: the result page sent only the words, so the server placed them at their first occurrence; it sends
    `quote_start` (code points in the excerpt's text) where the person selected them."""
    puts = page["quote selected where its words stand twice"]["puts"]
    assert puts == [puts[0]] and puts[0]["quote"] == "fix toasters" and puts[0]["quote_start"] == SECOND, puts
    assert puts[0]["verdict"] == "supports"


@needs_node
def test_a_waiting_sentence_keeps_where_it_was_selected_and_goes_with_the_judgement_chosen_after(page):
    """Item 2, the pending path: the sentence waits on the card (highlighted where selected), and is sent with its
    `quote_start` when the judgement is chosen."""
    r = page["quote selected twice-standing, judgement chosen after"]
    assert r["before"] == "Volunteers fix toasters for free. Neighbours also "
    puts = r["puts"]
    assert len(puts) == 1 and puts[0]["verdict"] == "refutes" and puts[0]["quote"] == "fix toasters" and puts[0]["quote_start"] == SECOND, puts


@needs_node
def test_a_sentence_picked_from_the_list_is_sent_with_where_it_stands(page):
    """Item 2, the keyboard path: the third sentence repeats the first; picking it sends its own place."""
    puts = page["sentence picked from the list stands twice"]["puts"]
    text = "Cafés fix many toasters. People come back often. Cafés fix many toasters."
    assert len(puts) == 1 and puts[0]["quote"] == "Cafés fix many toasters." and puts[0]["quote_start"] == text.rindex("Cafés"), puts


APP_QUEUE = r"""
await scenario("sidebar when the queue could not be looked at", async (t) => {
""" + SHELL + r"""
  t.state({ settings: { backend: "claude_code", threshold: 0.6 }, projects: [{ name: "Study", documents: 3, hypotheses: 1, ok: true }], queue: { waiting: 4 } }, { hash: "#/nowhere" });
  t.answer(/.*/, {});
  t.answer("GET /api/state", () => t.LIB.App.state);
  t.answer("GET /api/whats-new", { changes: null });
  t.answer("GET /api/claude-setup", { status: { found: true, signed_in: true, ready: true } });
  let fail = false;
  t.answer("GET /api/projects/Study/queue", () => (fail ? t.fail(500, "database is locked") : { route: "claude_code", can_start: true, waiting: 4, being_answered: 0, runner: {} }));
  await import(new URL("app.js", STATIC).href);
  await t.settle(1000);
  const box = document.getElementById("work-indicator");
  const first = { hidden: box.hidden, text: t.text(box) };
  fail = true;
  t.LIB.App.state = { ...t.LIB.App.state };   // a look of the sidebar's own
  window.dispatchEvent(new Event("focus"));
  await t.settle(16000);
  return { first, later: { hidden: box.hidden, text: t.text(box) }, looks: t.calls.filter((c) => c.path === "/api/projects/Study/queue").length };
});
"""


APP_ADDRESS = r"""
await scenario("an address typed with a bare percent sign", async (t) => {
""" + SHELL + r"""
  t.state({ settings: { backend: "baseline", threshold: 0.6 }, projects: [{ name: "Study", documents: 3, hypotheses: 1, ok: true }], queue: { waiting: 0 } }, { hash: "#/h/50%" });
  t.answer(/.*/, {});
  t.answer("GET /api/state", () => t.LIB.App.state);
  t.answer("GET /api/whats-new", { changes: null });
  t.answer(/^GET \/api\/projects\/Study\/hypotheses\/50%25/, t.fail(404, "No such hypothesis"));
  await import(new URL("app.js", STATIC).href);
  await t.settle(1000);
  const main = document.getElementById("view") || document.getElementById("main");
  return { busy: main.getAttribute("aria-busy"), text: t.text(main), asked: t.calls.filter((c) => c.path.includes("/hypotheses/")).map((c) => c.path) };
});
"""


# ---------------------------------------------------------------------------------------------
# 6. failures that only omit something: the two that matter most
# ---------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def quit_shell(tmp_path_factory):
    return run_views(APP_QUIT, tmp_path_factory.mktemp("pagesa15-quit"))


@needs_node
def test_a_failed_look_at_the_jobs_does_not_drop_the_warning_before_quitting(quit_shell):
    """Item 6: `runningJobs()` (app.js) took a failed GET /api/jobs as 0, so the dialog before quitting, updating or
    restarting said nothing of work that may be running. A failed look must say it could not be checked."""
    text = quit_shell["quit when the app could not say what runs"]["text"]
    assert "could not be checked" in text and "stops it" in text, text


@needs_node
def test_a_consent_dialog_keeps_the_shared_project_line_when_the_project_could_not_be_looked_at(page):
    """Item 6: `projectShared()` (settings.js) took a failed look as {shared: false}, and the consent dialog of a provider
    lost its "this project is shared" line without a word."""
    text = page["consent dialog when the project could not be looked at"]["text"]
    assert "shared with a team could not be checked" in text, text


# ---------------------------------------------------------------------------------------------
# 3. the owner's: short optional text kept on a failed save
# ---------------------------------------------------------------------------------------------
@needs_node
@pytest.mark.parametrize("name", ["theme list: rename fails", "theme page: rename fails", "theme page: remove with a reason fails"])
def test_a_failed_theme_edit_keeps_its_dialog_open_with_the_words(page, name):
    """Item 3: renaming a theme (themes.js, the list and the theme's page) and the "Why?" of removing one were saved
    after the dialog had closed: a failed save lost what was typed. Saved from the dialog's own button, a failure keeps
    the dialog open with the words (lib.js dialog(): onClick returning false)."""
    r = page[name]
    assert r["open"] and r["words"] in ("Tools and skills", "boilerplate from the cover pages") and r["sent"] == 1, r


@needs_node
def test_the_hint_of_read_this_again_stays_in_its_dialog_when_the_re_read_could_not_start(page):
    """Item 3: the "Read this again" dialog closed before its requests: a failed start lost the hint (and the hint had
    been saved as the comment first). It is sent from the dialog's own button, kept on failure, and the comment is not
    saved twice when pressed again."""
    r = page["re-read hint when the re-read fails"]
    assert r["open"] and r["words"] == "the next sentence says the opposite", r
    assert r["puts"] == 1 and r["posts"] == 2, r


# ---------------------------------------------------------------------------------------------
# handed on: the connector's refusal of a looser AI setting names what the Documents page offers
# ---------------------------------------------------------------------------------------------
@needs_node
def test_the_documents_page_offers_what_the_connectors_refusal_names(page, loaded):
    """Handed on (pagesa): the connector refuses an ai_access looser than the project's chosen default and sends the
    person to the app's Documents page. The page offers a document's own setting (in its details) and the setting of
    documents being added; it offers no control for the project's default once chosen, so the refusal must not promise
    one (it said "for the document or for the project")."""
    from enlens_claims import access, ingest

    r = page["documents page: where a document's AI setting is changed"]
    assert "Who may read these documents with AI?" in r["add"]
    assert "Who may read Interview 3 with AI" in r["access"] and "Claude may read it" in r["access"], r["access"]
    access.set_default(loaded, "local")
    with pytest.raises(ingest.AccessChoice) as e:
        ingest.adding_access(loaded, "cloud", by_ai=True)
    text = str(e.value)
    assert "Documents page" in text and "for the project" not in text
    assert "Who may read these documents with AI?" in text and "details" in text


# ---------------------------------------------------------------------------------------------
# handed on: GET /api/state has `addon_problems`; Settings › Technical draws one line per entry
# ---------------------------------------------------------------------------------------------
@needs_node
def test_settings_technical_draws_one_line_per_add_on_problem(page):
    """Handed on (pagesa): each entry of `addon_problems` is one line "addon: error", with " (project P)" when it is one
    project's; nothing when the list is empty."""
    r = page["settings: add-on problems"]
    assert r["lines"] == ["sdg: No module named 'sdgpack'", "fieldwork: its columns clash with another add-on (project Study)"], r
    empty = page["settings: no add-on problems"]
    assert empty["lines"] == [] and "add-on" not in empty["text"].lower(), empty


# ---------------------------------------------------------------------------------------------
# 4. phase 0's leftovers: P-2, P-3, P-5
# ---------------------------------------------------------------------------------------------
@needs_node
def test_an_older_look_at_the_queue_does_not_draw_over_a_newer_actions_answer(page):
    """P-2 (queue.js `draw()`): the 5-second look, answered after Hold's own look, drew the kind as not held again
    (for 5 s, until the next look)."""
    r = page["queue: an older look answered after a newer action"]
    assert "Go on" in r["after"], r
    assert "Go on" in r["later"] and "Hold" not in r["later"], r


@needs_node
@pytest.mark.parametrize("name,want", [("speed: a failed first pick after a saved second", "Slower"),
                                       ("thought: a failed first pick after a saved second", "Energy efficient"),
                                       ("settings: sharing the work, a failed first pick after a saved second", "Balanced")])
def test_a_failed_first_pick_does_not_reset_the_control_over_a_saved_second(page, name, want):
    """P-3 (lib.js speedPicker/thoughtPicker, settings.js "Sharing the work"): a first pick whose save failed after a
    second pick was saved put the control back to the value before both, though the second is the one saved."""
    assert want in (page[name]["checked"] or ""), page[name]


@needs_node
def test_a_local_side_drawn_again_keeps_when_its_wait_began(page):
    """P-5 (lib.js `LOCAL_WAIT_SINCE` unused): a local side drawn without `o.since` started its 5 s nudge again at every
    redraw, so a side redrawn every few seconds (the queue's look) never nudged."""
    assert page["local side drawn again keeps when its wait began"]["nudged"] is True


# ---------------------------------------------------------------------------------------------
# 5. result.js's module-level `retractedDocs`
# ---------------------------------------------------------------------------------------------
@needs_node
def test_the_retraction_notices_of_the_project_just_left_do_not_mark_this_ones_documents(page):
    """Item 5: `retractedDocs` was one module-level object filled by each render; a slow answer for the project just
    left landed after this one's and marked its documents (by doc id) as retracted."""
    assert "work retracted" not in page["retractions of the project just left answered late"]["text"]


# ---------------------------------------------------------------------------------------------
# 6. failures that only omit something: the rest, each decided by a test
# ---------------------------------------------------------------------------------------------
@needs_node
def test_a_failed_look_at_an_original_file_is_asked_again(page):
    """Item 6 (result.js, the original-file check): a failed look was kept for the page's life, so the link to the
    original never came back after a passing hiccup. A failure is now forgotten: the next draw asks again."""
    r = page["original file: a failed look is asked again"]
    assert r["first"] is None and r["again"]["available"] is True and r["asked"] == 2, r


@needs_node
def test_the_unread_documents_card_comes_back_after_a_failed_look(page):
    """Item 6 (result.js, unread documents): a failed look draws no card (an offer, not an answer) and is asked again
    at the next draw. Not a bug: nothing is said that is untrue, and nothing is lost."""
    r = page["unread documents: a failed look is asked again"]
    assert r["before"] is False and r["after"] is True and r["asked"] == 2, r


@needs_node
def test_a_running_follow_up_job_is_adopted_after_a_failed_look(page):
    """Item 6 (result.js, adopting running jobs): when GET /api/jobs failed as the page opened, a second opinion that
    runs was never shown (its button stayed pressable beside it). The page looks again a few seconds later."""
    r = page["result: running jobs could not be looked at when the page opened"]
    assert r["at"] is False and r["later"] is True, r


@needs_node
def test_calibration_that_could_not_be_worked_out_says_so(page):
    """Item 6 (settings.js): a failed calibration emptied its block without a word (a link to #/settings/calibration
    then showed nothing)."""
    assert "could not be worked out" in page["calibration that could not be worked out"]["text"]


@needs_node
def test_the_queue_keeps_the_local_part_waiting_when_the_jobs_could_not_be_looked_at(page):
    """Item 6 (queue.js): a failed GET /api/jobs took the job whose local part waits for its Start as gone, and its side
    (with its Start) left the panel until the next look."""
    r = page["queue: the gated job could not be looked at"]
    assert r["first"] and r["later"], r


@pytest.fixture(scope="module")
def queue_shell(tmp_path_factory):
    return run_views(APP_QUEUE, tmp_path_factory.mktemp("pagesa15-queue"))


@needs_node
def test_the_sidebar_keeps_the_work_waiting_when_the_queue_could_not_be_looked_at(queue_shell):
    """Item 6 (app.js `/queue` → null): a failed look at the queue read as "nothing waits": the sidebar's work box
    went away until the next look."""
    r = queue_shell["sidebar when the queue could not be looked at"]
    assert not r["first"]["hidden"] and "4" in r["first"]["text"], r
    assert r["looks"] >= 2 and not r["later"]["hidden"] and r["later"]["text"] == r["first"]["text"], r


@needs_node
def test_suggested_codes_come_after_a_failed_look(page):
    """Item 6 (hypotheses.js, suggestions): a failed look shows no suggested codes (an offer) and the next typing asks
    again. Not a bug: nothing untrue is said, the code can still be picked by hand."""
    r = page["hypotheses: suggested codes after a failed look"]
    assert r["before"] is False and r["after"] is True and r["asked"] == 2, r


@needs_node
def test_a_failed_look_for_similar_hypotheses_does_not_stop_the_check(page):
    """Item 6 (hypotheses.js, similar hypotheses): the look is an offer only (its comment: "Check never waits for
    them"); a failed one lets Check go on. Not a bug: the check is the person's, the offer is not a guard."""
    assert page["hypotheses: the look for similar hypotheses failed"]["checks"] == 1


@needs_node
def test_a_list_whose_answers_could_not_be_listed_still_offers_them(page):
    """Item 6 (hypotheses.js, batch rows): when the list's answers could not be listed in the summary, the summary
    still says how many were checked and offers "Show only these answers". Not a bug: nothing is lost or misstated."""
    r = page["hypotheses: a list checked whose answers could not be listed"]
    assert "2 of 2" in r["text"] and "Show only these answers" in r["buttons"], r


@needs_node
def test_the_answers_keep_a_running_check_when_the_jobs_could_not_be_looked_at(page):
    """Item 6 (history.js `runningChecks`): a failed look keeps the list it had (the running check's row stays), which
    is the right reading of "not known now". Not a bug."""
    r = page["answers: a running check, the jobs could not be looked at"]
    assert r["first"] and r["later"] and r["looks"] >= 2, r


# ---------------------------------------------------------------------------------------------
# 7. one wording for a check not finished
# ---------------------------------------------------------------------------------------------
@needs_node
def test_the_window_title_says_what_the_badge_says(page):
    """Item 7: a result not finished had "Not finished" in the window title and "Not finished yet" on its badge."""
    r = page["window title of a check not finished"]
    assert r["badge"].strip() == "Not finished yet" and r["title"].startswith("Not finished yet · "), r


# ---------------------------------------------------------------------------------------------
# 8. old data (PAGESA-1): can the rows saved with a colleague's verdict be found again?
# ---------------------------------------------------------------------------------------------
def test_a_row_saved_by_the_old_slip_is_the_same_as_a_deliberate_choice_of_that_verdict(page, loaded):
    """Item 8 (OLD DATA: NOTE KEPT): before hunt phase 1, marking a sentence where Anna's judgement counted sent
    {verdict: Anna's, quote}. Since the fix, choosing Anna's verdict as your own with a sentence sends the same
    request (plus `quote_start`), and the two leave the same `judgements` row and the same history: nothing in the
    data says which version or which press wrote a row, and a check's history keeps only your own judgements, not
    the colleague's verdict in force at that moment. So the slip's rows cannot be told apart reliably."""
    from enlens_claims import claimcheck, people
    from enlens_claims.llm import BaselineBackend
    from test_shared_projects import CLAIM, _claim, _excerpts

    now = page["a colleague's verdict chosen as yours, with a sentence"]["puts"]
    assert len(now) == 1 and now[0]["verdict"] == "refutes" and now[0].get("quote")

    hid = claimcheck.check_hypothesis(loaded, CLAIM, BaselineBackend(), "baseline", k=3)
    cid, ex = _claim(loaded, hid), _excerpts(loaded, hid)[0]
    pid, sentence = ex["passage_id"], " ".join(ex["text"].split()[:5])
    with loaded.connect() as cx:
        people.record(cx, cid, pid, "p0000000000aa", "refutes", None, "2026-11-01T10:00:00+00:00")
    me = people.me()

    def made_by(body: dict) -> tuple:
        claimcheck.set_judgement(loaded, cid, pid, body["verdict"], body.get("note"), quote=body["quote"],
                                 quote_start=body.get("quote_start"))
        row = loaded.query("SELECT verdict, note, quote, start, end FROM judgements WHERE claim_id=? AND "
                           "passage_id=? AND person_id=?", (cid, pid, me))[0]
        versions = loaded.scalar("SELECT COUNT(*) FROM versions")
        with loaded.connect() as cx:   # back to before, for the other route
            cx.execute("DELETE FROM judgements WHERE claim_id=? AND passage_id=? AND person_id=?", (cid, pid, me))
            cx.execute("DELETE FROM versions")
            people.refresh(cx, [cid])
        return tuple(row), versions

    slip = made_by({"verdict": "refutes", "note": None, "quote": sentence})
    chosen = made_by({"verdict": "refutes", "note": None, "quote": sentence, "quote_start": 0})
    assert slip == chosen


# ---------------------------------------------------------------------------------------------
# 9. review note (surface.md): hold the redraw, not the look
# ---------------------------------------------------------------------------------------------
@needs_node
def test_a_cursor_left_in_a_comment_box_holds_the_redraw_not_the_look(page):
    """Item 9: while a check waits for Claude Code, the 5-second look was held as long as any text field had focus (a
    cursor left in a comment box stopped updates). The look goes on; new answers are said ("New answers… Show them")
    and drawn when the person asks, without taking the field."""
    r = page["comment box focused while the check waits"]
    assert r["looks"] >= 2 and r["focusStays"] and r["said"] and not r["shownBefore"] and r["shownAfter"], r


# ---------------------------------------------------------------------------------------------
# 11. the rest of notes/pagesa.md ("Not proven")
# ---------------------------------------------------------------------------------------------
@needs_node
def test_agree_pressed_twice_while_it_saves_is_sent_once(page):
    """Not proven 2: "Agree", "Not about this" and the judgement choice were not held while their PUT ran: a double
    click sent two PUTs and gave two toasts."""
    r = page["agree pressed twice while it saves"]
    assert r["puts"] == 1 and r["toasts"] == 1, r


@needs_node
def test_a_judgement_saved_says_so_when_the_page_could_not_be_fetched_again(page):
    """Not proven 6: when the PUT succeeded but the following GET failed, the card showed only the GET's error and no
    "Saved", though the judgement was saved."""
    toasts = page["judgement saved, the result could not be fetched again"]["toasts"]
    assert any(t.startswith("Saved") for t in toasts), toasts


@needs_node
def test_show_the_batch_after_pressed_twice_skips_no_batch(page):
    """Not proven 5: "Show the batch after" pressed twice before the first answer added the count twice and skipped
    a batch. Already fixed: since hunt phase 1 (52e272b9) a dialog's button acts once while its work runs."""
    assert page["see what is sent: the batch after, pressed twice"]["starts"] == [0, 2]


@needs_node
def test_numbers_are_written_in_english_whatever_the_browsers_language(page):
    """Not proven 7: fmt.num used the browser's own language ("1.234.567" on a German browser) while dates are fixed
    to en-GB (lib.js, 0.12): the page is in English."""
    r = page["numbers in a browser set to German"]
    assert r["n"] == "1,234,567" and r["plural"] == "1,234 documents", r


@needs_node
def test_stop_whose_cancel_failed_keeps_the_run(page):
    """Not proven 8: AiRun.stop() called onStop (the page's "it stopped") even when the cancel failed."""
    r = page["stop of an AI run whose cancel failed"]
    assert r["stopped"] == 0 and {"label": "Stop", "disabled": False} in r["buttons"], r


@pytest.fixture(scope="module")
def address_shell(tmp_path_factory):
    return run_views(APP_ADDRESS, tmp_path_factory.mktemp("pagesa15-address"))


@needs_node
def test_an_address_typed_with_a_bare_percent_sign_opens_a_page(address_shell):
    """Not proven 4: app.js decoded the address's parts outside its try: "#/h/50%" threw, and the page stayed empty
    with aria-busy."""
    r = address_shell["an address typed with a bare percent sign"]
    assert r["busy"] == "false" and r["text"].strip(), r


@needs_node
def test_retraction_notices_that_could_not_be_read_are_said_not_taken_as_none(page):
    """Item 6 (result.js, retractions): a failed read of the notices was taken as "no work retracted", so an excerpt
    of a retracted work showed no mark and nothing said why."""
    toasts = page["retraction notices that could not be read"]["toasts"]
    assert any("retracted" in t and "could not be read" in t for t in toasts), toasts


@needs_node
def test_the_made_with_mark_names_the_engine_version_in_an_app_built_on_enlens(page):
    """notes/pagesa.md (PAGESA-11's note): lib.js `madeWithFact` writes "ENLENS 0.18.0" also in an app that brand.json
    names otherwise. Not a bug: the number is ENLENS's own version (Settings › Technical › This installation names it
    "ENLENS <version>" the same way), not the app's name, which appName() gives everywhere else."""
    assert "ENLENS 0.18.0" in page["made with an earlier version, in an app built on ENLENS"]["text"]
