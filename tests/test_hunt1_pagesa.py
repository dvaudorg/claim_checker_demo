"""Hunt phase 1 (pages-a): the browser page's shell and plumbing, and the views for checking hypotheses, results,
settings and AI set-up. Each test names what a person meets; each fails until its defect is fixed. Run in Node under
the fake DOM of tests/_views.py."""
from __future__ import annotations

import pytest

from _views import needs_node, run_views

PROBE = r"""
// ---- the result page (as tests/test_views_result_and_documents.py builds it) --------------------------------
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

// Your notes, typed while a second opinion (started earlier) ends: the page is drawn again with the result as fetched
await scenario("notes typed while a job ends", async (t) => {
  let job = { id: "j1", project: "Study", kind: "second-opinion", state: "running", progress: {} };
  t.answer("GET /api/jobs", () => ({ jobs: [job] }));
  t.answer("GET /api/jobs/j1", () => job);
  const notes = [];
  t.answer(`PUT ${H}/note`, (body) => { notes.push(body.note); return { saved: true }; });
  await result(t, RESULT([PX()], { note: "" }));
  await t.settle(100);
  const box = document.getElementById("note");
  box.focus();
  box.value = "Check the 2019 report by hand";
  box.dispatchEvent(new Event("input", { bubbles: true }));
  job = { ...job, state: "done", result: {} };   // the job ends before the typing's pause is over
  await t.settle(300);
  await t.settle(2000);
  return { shown: document.getElementById("note").value, saved: notes };
});

// a page looked at with a stricter setting than Settings' (?threshold=0.9): why an excerpt does not count
await scenario("not counted at the page's strictness", async (t) => {
  await result(t, RESULT([PX({ confidence: 0.8, counted: false })], { status: "uncertain" }), {}, { threshold: "0.9" });
  const fact = card(t, "p1").querySelector(".ev-uncounted-fact");
  return { title: fact ? fact.getAttribute("title") : null };
});

// a split hypothesis with one excerpt about it, which counts
await scenario("split: one judgement counts", async (t) => {
  const r = RESULT([PX()], { decomposed: true });
  r.parts.push({ claim_id: "c2", part: 2, claim: "Repair cafés teach skills", status: "no_passages", passages: [], rounds_info: [] });
  await result(t, r);
  return { count: t.text(t.view.querySelector(".ev-count")) };
});

// an app built on ENLENS (brand.json names it): the window's title on a result
await scenario("result window title in a branded app", async (t) => {
  await result(t, RESULT([PX()]), {}, {}, { brand: { name: "Fieldnotes" } });
  return { title: document.title };
});

// a comment typed in an excerpt's card while the check waits for Claude Code: the look every few seconds finds more
await scenario("comment typed while the check waits", async (t) => {
  let now = RESULT([PX()], { status: "waiting" });
  t.answer("GET /api/projects/Study/queue", { route: "claude_code", can_start: true, waiting: 3, being_answered: 0, runner: {} });
  await result(t, () => now, { backend: "claude_code" });
  await t.click("Judge differently…", { within: card(t, "p1") });
  const input = card(t, "p1").querySelector(".judge-note input");
  input.focus();
  input.value = "the next sentence says";
  input.dispatchEvent(new Event("input", { bubbles: true }));
  now = RESULT([PX(), PX({ passage_id: "p4", title: "Third report" })], { status: "waiting" });
  await t.settle(5200);
  const again = card(t, "p1").querySelector(".judge-note input");
  return { focusStays: document.activeElement === again, value: again.value, focus: t.focused() };
});

// a second opinion followed on the result page, whose job the app no longer knows (ENLENS started again meanwhile)
await scenario("second opinion whose job is gone", async (t) => {
  let gone = false;
  t.answer("GET /api/jobs", { jobs: [{ id: "j2", project: "Study", kind: "second-opinion", state: "running", progress: {} }] });
  t.answer("GET /api/jobs/j2", () => (gone ? t.fail(404, "No such job: j2") : { id: "j2", project: "Study", kind: "second-opinion", state: "running", progress: {} }));
  await result(t, RESULT([PX()], { excerpts_read: 1 }), { ollama_model: "llama", second_model: "qwen" });
  await t.settle(600);
  gone = true;
  await t.settle(3000);
  const ask = t.view.querySelector(".ask-card");
  return { buttons: t.buttons(ask), jobs: !!ask.querySelector(".ask-jobs"), toasts: t.toasts() };
});

// the Hypotheses page of one project, opened after a check was started in another project in this tab
await scenario("hypotheses page follows another project's check", async (t) => {
  t.state({ settings: { threshold: 0.6, backend: "baseline" } });
  sessionStorage.setItem("enlens.activeCheck", JSON.stringify("j9"));
  t.answer("GET /api/projects/Study", { frameworks: [], passages: 40 });
  t.answer("GET /api/projects/Study/documents", { documents: [{ doc_id: "d1", title: "Report" }] });
  t.answer("GET /api/projects/Study/hypotheses?*", { hypotheses: [], counts: {} });
  t.answer("GET /api/jobs/j9", { id: "j9", project: "Other", kind: "check", state: "running", title: "Teleworking lowers car use", progress: {} });
  await t.render("views/hypotheses.js", "renderHypotheses", [], {});
  const box = t.view.querySelector(".hyp-progress");
  return { progress: box && !box.hidden ? t.text(box) : "" };
});

// a shared project: Anna's judgement counts in your copy (you have not judged the excerpt); you mark a sentence in it
await scenario("sentence marked on a colleague's judgement", async (t) => {
  const puts = [];
  t.answer("PUT /api/projects/Study/claims/c1/judgements/p1", (body) => { puts.push(body); return { moved: null }; });
  await result(t, RESULT([PX({ user_verdict: "refutes", verdict: "refutes", judged_by: "Anna", my_verdict: null, changed: true, reviewed: true, quote_by: "ai" })]));
  await t.click("Edit judgement…", { within: card(t, "p1") });
  await t.click("Pick from a list", { within: card(t, "p1") });
  const pick = card(t, "p1").querySelector(".mark-list select");
  pick.value = "0";
  await t.click("Use this sentence", { within: card(t, "p1") });
  return { puts };
});

// the evidence map, when the app cannot answer for it
await scenario("map that could not be loaded", async (t) => {
  t.state({ settings: { threshold: 0.6 } });
  t.answer("GET /api/projects/Study/map?*", t.fail(500, "database is locked"));
  await t.render("views/map.js", "renderMap", [], {});
  return { text: t.text(t.view) };
});

// the Hypotheses page, when the app cannot say what the project holds
await scenario("hypotheses page that could not load the project", async (t) => {
  t.state({ settings: { threshold: 0.6, backend: "baseline" } });
  t.answer("GET /api/projects/Study", t.fail(500, "database is locked"));
  t.answer("GET /api/projects/Study/documents", { documents: [{ doc_id: "d1", title: "Report" }] });
  t.answer("GET /api/projects/Study/hypotheses?*", { hypotheses: [], counts: {} });
  await t.render("views/hypotheses.js", "renderHypotheses", [], {});
  return { text: t.text(t.view) };
});
"""

# The shell (app.js) booted on a page with the sidebar of index.html: one scenario, as app.js boots once per process.
APP_PROBE = r"""
await scenario("sidebar while Claude Code answers a job whose local part waits", async (t) => {
  for (const id of ["menu-btn", "topbar-project", "sidebar", "project-switch", "find-btn", "find-key", "nav", "nav-foot", "update-btn", "quit-btn", "theme-btn", "scrim", "main",
    "stopped-banner", "update-banner", "quicklook-banner"]) document.body.appendChild(Object.assign(document.createElement(/btn/.test(id) ? "button" : "div"), { id }));
  const team = document.createElement("a"); team.id = "team-line"; document.getElementById("project-switch").appendChild(team);
  const area = document.createElement("div"); area.id = "status-area";
  for (const id of ["work-indicator", "privacy-indicator"]) area.appendChild(Object.assign(document.createElement("div"), { id }));
  document.body.appendChild(area);
  // another ENLENS tab of this browser hands over the key (lib.js ensureToken)
  globalThis.BroadcastChannel = class { postMessage(m) { if (m && m.ask) setTimeout(() => this.onmessage && this.onmessage({ data: { token: "k".repeat(24) } }), 1); } close() {} };
  t.state({ settings: { backend: "claude_code", threshold: 0.6 }, projects: [{ name: "Study", documents: 3, hypotheses: 1, ok: true }], queue: { waiting: 0 } }, { hash: "#/nowhere" });
  t.answer(/.*/, {});
  t.answer("GET /api/state", () => t.LIB.App.state);
  t.answer("GET /api/jobs", { jobs: [{ id: "j1", project: "Study", kind: "check", state: "running", title: "Repair cafés build community", seconds: 12,
    queue: { text: "Claude Code reads the excerpts" }, local: { gate: "wait", waiting: 3, noun: "excerpt", model: "qwen3.5:9b" } }] });
  t.answer("GET /api/projects/Study/queue", { route: "claude_code", can_start: true, waiting: 0, being_answered: 4, runner: { running: true, seconds: 30 } });
  t.answer("GET /api/claude-setup", { status: { found: true, signed_in: true, ready: true } });
  t.answer("GET /api/whats-new", { changes: null });
  await import(new URL("app.js", STATIC).href);
  await t.settle(1000);
  const box = document.getElementById("work-indicator");
  const main = box.querySelector(".work-main");
  return { text: t.text(box), tip: main ? main.getAttribute("title") : null, hidden: box.hidden };
});
"""


@pytest.fixture(scope="module")
def page(tmp_path_factory):
    return run_views(PROBE, tmp_path_factory.mktemp("pagesa"))


@pytest.fixture(scope="module")
def shell(tmp_path_factory):
    return run_views(APP_PROBE, tmp_path_factory.mktemp("pagesa-app"))


@needs_node
def test_notes_typed_on_a_result_stay_in_the_box_when_a_job_ends(page):
    """A follow-up job ending redraws the result page and rebuilds the notes box from the fetched result: what was
    just typed vanishes from the box (views/result.js:1185 `draw(fresh)`, noteCard at :2190)."""
    r = page["notes typed while a job ends"]
    assert r["shown"] == "Check the 2019 report by hand"


@needs_node
def test_an_uncounted_excerpt_gives_the_reason_at_the_strictness_the_page_shows(page):
    """On a result seen at another strictness (?threshold=0.9), an 80% judgement is below it, but its card says the
    round of reading did not finish: the reason is worked out from Settings' strictness (views/result.js:1687)."""
    title = page["not counted at the page's strictness"]["title"]
    assert "below your strictness" in title


@needs_node
def test_one_judgement_of_a_split_hypothesis_is_counted_in_the_singular(page):
    """A split hypothesis with one excerpt about it says "1 of 1 judgements counts across the parts"
    (views/result.js:1462)."""
    assert page["split: one judgement counts"]["count"].startswith("1 of 1 judgement counts")


@needs_node
def test_a_comment_being_typed_keeps_the_focus_when_the_waiting_check_looks_again(page):
    """While a check waits for Claude Code the page looks again every 5 s and redraws when more came in; the guard
    protects only the notes box, so a comment being typed in an excerpt's card loses the focus (views/result.js:283)."""
    r = page["comment typed while the check waits"]
    assert r["focusStays"] is True


@needs_node
def test_the_window_title_of_a_result_names_the_app_as_brand_json_does(page):
    """The result page writes "· ENLENS" into the window title, though page code names the app with appName()
    (views/result.js:487, rule at lib.js:746)."""
    assert page["result window title in a branded app"]["title"].endswith("· Fieldnotes")


@needs_node
def test_an_evidence_map_that_could_not_be_loaded_says_so_not_nothing_to_map(page):
    """A failed GET of the map is a toast that fades, and the page then says "Nothing to map yet. Check a hypothesis"
    (views/map.js:23); a failed load is said in the page (lib.js:549 failedLoad)."""
    text = page["map that could not be loaded"]["text"]
    assert "Nothing to map yet" not in text and "database is locked" in text


@needs_node
def test_the_hypotheses_page_does_not_say_there_are_no_documents_when_it_could_not_ask(page):
    """When GET /api/projects/<p> fails, the page takes 0 passages and says "Add documents first ... there are none
    yet" in a project with documents (views/hypotheses.js:37 and :92)."""
    assert "there are none yet" not in page["hypotheses page that could not load the project"]["text"]


@needs_node
def test_a_follow_up_job_that_is_gone_does_not_leave_its_button_disabled(page):
    """A second opinion followed on the result page whose job the app no longer knows (404, after a restart): the
    watcher fails with a toast, but nothing is drawn again, so "Get a second opinion" stays disabled and the job's
    panel stays (views/result.js:1186)."""
    r = page["second opinion whose job is gone"]
    assert {"label": "Get a second opinion", "disabled": False} in r["buttons"] and not r["jobs"]


@needs_node
def test_the_hypotheses_page_does_not_follow_a_check_of_another_project(page):
    """A check started in project Other, then project Study opened in the same tab: Study's Hypotheses page shows
    "Checking" with Other's hypothesis and, when it ends, goes to its result (views/hypotheses.js:652-666)."""
    assert "Teleworking lowers car use" not in page["hypotheses page follows another project's check"]["progress"]


@needs_node
def test_marking_a_sentence_does_not_make_a_colleagues_judgement_your_own(page):
    """Where Anna's judgement counts in your copy, marking a sentence saves it with her verdict as your judgement
    (views/result.js:2057 puts `current`, the judgement in force, not `p.my_verdict`): you never judged the excerpt."""
    puts = page["sentence marked on a colleague's judgement"]["puts"]
    assert not any(p.get("verdict") == "refutes" for p in puts)
