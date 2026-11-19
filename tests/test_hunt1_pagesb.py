"""Hunt phase 1, pages-b: the browser page's views for documents and reading, codebooks, themes, concepts, notes and
log, projects and working in a team. Each test shows one defect a person meets; it fails until the defect is fixed.
"""
from __future__ import annotations

import json

import pytest

from _views import needs_node, run_views

PROBE = r"""
// ---- the codebook editor ------------------------------------------------------------------------------------
const CB = "/api/projects/Study/codebooks";
const CODE = (o) => ({ uid: "u1", code: "Mending", description: "Fixing things", group: "1", include: "", exclude: "", keywords: ["mend"],
  examples: [], ...o });
async function editor(t, codes) {
  t.state({ settings: { backend: "claude_code" } });
  t.answer(`GET ${CB}/repair`, { codebook: { name: "repair", title: "Repair", label: "code", where: "project", editable: true, directional: false,
    used: { labels: 0, checks: 0 }, groups: [{ group: "1", group_name: "Practice" }], codes } });
  t.answer("GET /api/projects/Study/codebooks/repair/offer", { offer: null });
  t.answer("GET /api/projects/Study/sharing/codebook/repair", { shared: false });
  t.answer("GET /api/projects/Study/shared-folder", { folder: null });
  t.answer("GET /api/projects/Study/sync-poller", t.fail(404, "none"));
  await t.render("views/codebooks.js", "renderCodebook", ["repair"]);
}
const held = () => { const h = {}; h.promise = new Promise((r) => { h.release = r; }); return h; };

await scenario("codebook: words typed while a save is under way", async (t) => {
  await editor(t, [CODE()]);
  await t.click(/^Mending/);
  await t.type("Definition", "Fixing things together");
  const put = held();
  t.answer(`PUT ${CB}/repair`, (body) => put.promise.then(() => ({ codebook: { ...body.codebook, editable: true, used: { labels: 0, checks: 0 } },
    changes: ["Mending: its definition changed"] })));
  await t.click("Save");
  await t.type("Definition", "Fixing things together, in a café");   // the save is still on its way
  put.release();
  await t.settle();
  const f = t.field("Definition");
  return { field: f ? f.value : null, unsaved: !t.hidden(t.view.querySelector(".cb-savebar")) };
});

await scenario("codebook: typing while Try it runs", async (t) => {
  await editor(t, [CODE()]);
  await t.click(/^Mending/);
  t.answer(`POST ${CB}/repair/try`, { job: { id: "jt" } });
  let state = "running";
  t.answer("GET /api/jobs/jt", () => ({ id: "jt", state, result: state === "done" ? { passages: 10, codes: { Mending: { passages: 2, documents: 1, examples: [] } } } : null, progress: {} }));
  await t.click("Try it");
  const f = t.field("Definition");
  await t.type(f, "Fixing things toge");                              // typing, the caret in the field
  state = "done";
  await t.settle(1200);
  const now = t.field("Definition");
  return { same: now === f, focused: t.focused(), value: now ? now.value : null, focusedIsField: !!now && document.activeElement === now };
});

// ---- after review (PAGESB-1): new codes keep the ids the save gave them, whatever the server tidied ----------------
// the server's answer as codebooks.save gives it: names tidied ("Repair " is "Repair"), a new code given an id, and
// `uids`, the id of each code sent, in the order sent
const tidy = (x) => x.replace(/\s+/g, " ").trim();
const savedAs = (body, n) => { const codes = body.codebook.codes.map((c, i) => ({ ...c, code: tidy(c.code), uid: c.uid || `new${n}-${i}` }));
  return { codebook: { ...body.codebook, codes, editable: true, used: { labels: 0, checks: 0 } }, changes: ["added a code"], uids: codes.map((c) => c.uid) }; };
async function saveWhileTyping(t, codes, during) {
  await editor(t, codes);
  const put = held();
  let n = 0;
  t.answer(`PUT ${CB}/repair`, (body) => (++n === 1 ? put.promise.then(() => savedAs(body, n)) : savedAs(body, n)));
  await t.click(/^Repair/);
  await t.type("Definition", "Fixing things, by hand");
  await t.click("Save");
  await during();                                                         // the save is still on its way
  put.release();
  await t.settle();
  const unsaved = !t.hidden(t.view.querySelector(".cb-savebar"));
  await t.click("Save");
  await t.settle();
  const puts = t.calls.filter((c) => c.method === "PUT");
  return { unsaved, second: puts.length > 1 ? puts[1].body.codebook.codes.map((c) => [c.uid, c.code]) : null, errors: t.toasts().filter((x) => /refus|name of a code/i.test(String(x))) };
}
await scenario("codebook: a new code whose name the server tidies, edited during the save", async (t) =>
  saveWhileTyping(t, [CODE({ uid: "", code: "Repair " })], () => t.type("Definition", "Fixing things, by hand, together")));
await scenario("codebook: two new codes sent in one save", async (t) =>
  saveWhileTyping(t, [CODE({ uid: "", code: "Repair  café" }), CODE({ uid: "", code: "Reuse " })], () => t.type("Definition", "Fixing things, by hand, together")));
await scenario("codebook: a new code renamed during the save", async (t) =>
  saveWhileTyping(t, [CODE({ uid: "", code: "Repair " })], () => t.type("Name", "Mending")));
await scenario("codebook: a new code removed during the save", async (t) =>
  saveWhileTyping(t, [CODE({ uid: "", code: "Repair " }), CODE({ uid: "u2", code: "Reuse" })], async () => { await t.click("Remove", { within: t.view.querySelector(".cb-open") }); await t.settle(); }));

// ---- the Documents page: adding files ----------------------------------------------------------------------
async function documents(t) {
  t.state({ settings: {} });
  t.answer("GET /api/projects/Study", { search: null, passages: 0, ai_access: { chosen: true, default: "cloud" } });
  t.answer(/^GET \/api\/projects\/Study\/documents(\?.*)?$/, { documents: [], ai_access: {}, new_reader: 7 });
  t.answer(/^GET \/api\/projects\/Study\/document-roles/, { roles: {}, nonscientific: [] });
  t.answer("GET /api/projects/Study/nonscientific-suggestions", { suggested: {} });
  t.answer("GET /api/projects/Study/map/documents?*", t.fail(404, "no answers yet"));
  await t.render("views/sources.js", "renderSources");
}
await scenario("documents: a file removed from the list while the others are copied", async (t) => {
  await documents(t);
  const input = t.view.querySelector("#src-files");
  input.files = [new File(["aaa"], "one.pdf"), new File(["bbbbbb"], "two.pdf")];
  input.dispatchEvent(new Event("change"));
  await t.settle();
  const first = held();
  t.answer(/^POST \/api\/projects\/Study\/uploads/, (b, path) => (path.includes("one.pdf") ? first.promise.then(() => ({})) : {}));
  t.answer("POST /api/projects/Study/ingest", { job: { id: "ji" } });
  t.answer("GET /api/jobs/ji", { id: "ji", state: "running", progress: {} });
  await t.click(/^Add these 2 documents/);
  const listed = t.text(t.view.querySelector(".file-list"));
  const rm = t.find("Remove two.pdf from the list");
  const removable = !!rm && !rm.disabled;
  if (removable) await t.click(rm);
  first.release();
  await t.settle();
  return { listed, removable, sent: t.calls.filter((c) => c.path.includes("/uploads")).map((c) => decodeURIComponent(c.path.split("name=")[1])) };
});

// after review (PAGESB-5): the file being copied right now cannot be taken off the list (the whole batch folder is
// read in, so a file copied there would be added all the same)
await scenario("documents: the file being copied is taken off the list", async (t) => {
  await documents(t);
  const input = t.view.querySelector("#src-files");
  input.files = [new File(["aaa"], "one.pdf"), new File(["bbbbbb"], "two.pdf")];
  input.dispatchEvent(new Event("change"));
  await t.settle();
  const first = held();
  t.answer(/^POST \/api\/projects\/Study\/uploads/, (b, path) => (path.includes("one.pdf") ? first.promise.then(() => ({})) : {}));
  t.answer("POST /api/projects/Study/ingest", { job: { id: "ji" } });
  t.answer("GET /api/jobs/ji", { id: "ji", state: "running", progress: {} });
  await t.click(/^Add these 2 documents/);
  const rm = t.find("Remove one.pdf from the list");
  const removable = !!rm && !rm.disabled;
  const why = rm ? rm.getAttribute("title") : null;
  if (removable) await t.click(rm);
  const listedAfter = t.text(t.view.querySelector(".file-list"));
  first.release();
  await t.settle();
  return { removable, why, listedAfter, uploads: t.calls.filter((c) => c.path.includes("/uploads")).map((c) => decodeURIComponent(c.path.split("name=")[1])) };
});

// the server keeps two files of one name apart now (hunt phase 1, `_free_upload_name`): the page says both were added
await scenario("documents: two files of one name", async (t) => {
  await documents(t);
  const input = t.view.querySelector("#src-files");
  input.files = [new File(["aaa"], "notes.txt"), new File(["bbbbbb"], "notes.txt")];
  input.dispatchEvent(new Event("change"));
  await t.settle();
  let n = 0;
  t.answer(/^POST \/api\/projects\/Study\/uploads/, () => (++n === 1 ? { batch: "b", name: "notes.txt", size: 3 } : { batch: "b", name: "notes (2).txt", size: 6 }));
  t.answer("POST /api/projects/Study/ingest", { job: { id: "ji" } });
  t.answer("GET /api/jobs/ji", { id: "ji", state: "done", progress: {}, result: { added: 2 } });
  t.answer("GET /api/projects/Study/hypotheses", { hypotheses: [] });
  const listed = t.text(t.view.querySelector(".file-list"));
  await t.click(/^Add these 2 documents/);
  await t.settle(3000);
  return { listed, said: t.text(t.view) };
});

// files of kinds it does not read, and a damaged zip, come back in the job's `failed` (hunt phase 1, the server)
await scenario("documents: a damaged zip and a kind it does not read", async (t) => {
  await documents(t);
  const input = t.view.querySelector("#src-files");
  input.files = [new File(["PK"], "interviews.zip")];
  input.dispatchEvent(new Event("change"));
  await t.settle();
  t.answer(/^POST \/api\/projects\/Study\/uploads/, { batch: "b", name: "interviews.zip", size: 2 });
  t.answer("POST /api/projects/Study/ingest", { job: { id: "ji" } });
  t.answer("GET /api/jobs/ji", { id: "ji", state: "done", progress: {}, result: { added: 0,
    failed: ["interviews.zip: damaged zip: copy or download it again", "old.doc: an older Word file, which ENLENS does not read: save it as .docx or PDF and add that"] } });
  await t.click(/^Add this document/);
  await t.settle(3000);
  return t.text(t.view.querySelector(".pb"));
});

// ---- reader 7 offered to a document an earlier reader read ---------------------------------------------------
await scenario("documents: the offer of the new reader to a reader-4 text file", async (t) => {
  t.state({ settings: {} });
  t.answer("GET /api/projects/Study", { search: null, passages: 3, ai_access: { chosen: true, default: "cloud" } });
  t.answer(/^GET \/api\/projects\/Study\/documents(\?.*)?$/, { new_reader: 7, ai_access: { default: "cloud" },
    documents: [{ doc_id: "d1", title: "Interviews", file: "interviews.txt", kind: "text", reader: 4, new_reader_changes: true, ai_access: "cloud" }] });
  t.answer(/^GET \/api\/projects\/Study\/document-roles/, { roles: {}, nonscientific: [] });
  t.answer("GET /api/projects/Study/nonscientific-suggestions", { suggested: {} });
  t.answer("GET /api/projects/Study/map/documents?*", t.fail(404, "no answers yet"));
  await t.render("views/sources.js", "renderSources");
  return t.text(t.view.querySelector(".nr-box"));
});
await scenario("document page: the Reading panel of a reader-4 text file", async (t) => {
  const DOC = "/api/projects/Study/documents/d1";
  t.state({ settings: {} });
  t.answer(`GET ${DOC}?*`, { doc_id: "d1", title: "Interviews", file: "interviews.txt", kind: "text", reader: 4, new_reader: 7, new_reader_changes: true,
    total_blocks: 1, reading: { quality: "good" }, blocks: [{ n: 0, kind: "body", text: "Q: Why do you come here?", start: 0, end: 24 }] });
  t.answer(/^GET \/api\/projects\/Study\/documents\/d1\/role/, { role: null });
  t.answer(`GET ${DOC}/nonscientific-suggestion`, { suggested: false });
  t.answer(`GET ${DOC}/notes`, { notes: [] });
  t.answer(`GET ${DOC}/file?*`, {});
  await t.render("views/doc-page.js", "renderDocument", ["d1"], { tab: "reading" });
  return t.text(t.view.querySelector(".dv-panel"));
});

// ---- a note whose save fails ---------------------------------------------------------------------------------
const typedStill = (words) => document.querySelectorAll("textarea").some((x) => x.value === words && !x.closest("dialog") || x.value === words && x.closest("dialog").open);
await scenario("note: a new note whose save fails", async (t) => {
  const DOC = "/api/projects/Study/documents/d1";
  const text = "Repair cafés make repairing an everyday practice again.";
  t.state({ settings: {} });
  t.answer(`GET ${DOC}?*`, { doc_id: "d1", title: "Field notes", kind: "md", total_blocks: 1, blocks: [{ n: 0, kind: "paragraph", text, start: 0, end: text.length }] });
  t.answer(/^GET \/api\/projects\/Study\/documents\/d1\/role/, { role: null });
  t.answer(`GET ${DOC}/nonscientific-suggestion`, { suggested: false });
  t.answer(`GET ${DOC}/notes`, { notes: [] });
  await t.render("views/doc-page.js", "renderDocument", ["d1"], {});
  const walk = (n) => { for (const c of n.childNodes) { if (c instanceof Text && c.data.includes("everyday")) return c; const f = c.childNodes && walk(c); if (f) return f; } return null; };
  const node = walk(t.view);
  const at = node.data.indexOf("everyday practice");
  t.select(node, at, at + "everyday practice".length);
  node.parentNode.dispatchEvent(new Event("mouseup", { bubbles: true }));
  await t.settle(10);
  await t.click("Note", { within: t.view.querySelector(".dv-selbar") });
  const words = "This is the heart of my second chapter: repair as a habit, not an event.";
  await t.type("Your note", words);
  t.answer("POST /api/projects/Study/notes", t.fail(400, "These words are not in the document's text: select them in the text."));
  await t.click("Keep the note", { within: t.dialog() });
  return { kept: typedStill(words), errors: t.toasts() };
});
await scenario("note: an edit whose save fails", async (t) => {
  t.state({ settings: {} });
  const note = { note_id: "n1", doc_id: "d1", title: "Field notes", present: true, mine: true, start: 0, end: 10, quote: "Repair cafés", text: "first thought", colour: "yellow", created_at: "2026-11-18T10:00:00Z" };
  t.answer("GET /api/projects/Study/notes?*", { notes: [note], total: 1, documents: [{ doc_id: "d1", title: "Field notes", notes: 1, present: true }] });
  t.answer(/^GET \/api\/projects\/Study\/sharing/, { items: [] });
  await t.render("views/notes.js", "renderNotes", [], {});
  await t.click("Edit");
  const words = "first thought, and a long second one I spent ten minutes on";
  await t.type("Note", words);
  t.answer("PUT /api/projects/Study/notes/n1", t.fail(404, "Not found: n1"));   // removed meanwhile by one's other account
  await t.click("Save", { within: t.dialog() });
  return { kept: typedStill(words), errors: t.toasts() };
});
// after review (PAGESB-2): a second press while the save runs is not a second save, in any dialog (lib.js dialog)
await scenario("note: Keep the note pressed twice while the app is slow", async (t) => {
  const DOC = "/api/projects/Study/documents/d1";
  const text = "Repair cafés make repairing an everyday practice again.";
  t.state({ settings: {} });
  t.answer(`GET ${DOC}?*`, { doc_id: "d1", title: "Field notes", kind: "md", total_blocks: 1, blocks: [{ n: 0, kind: "paragraph", text, start: 0, end: text.length }] });
  t.answer(/^GET \/api\/projects\/Study\/documents\/d1\/role/, { role: null });
  t.answer(`GET ${DOC}/nonscientific-suggestion`, { suggested: false });
  t.answer(`GET ${DOC}/notes`, { notes: [] });
  await t.render("views/doc-page.js", "renderDocument", ["d1"], {});
  const walk = (n) => { for (const c of n.childNodes) { if (c instanceof Text && c.data.includes("everyday")) return c; const f = c.childNodes && walk(c); if (f) return f; } return null; };
  const node = walk(t.view);
  const at = node.data.indexOf("everyday practice");
  t.select(node, at, at + "everyday practice".length);
  node.parentNode.dispatchEvent(new Event("mouseup", { bubbles: true }));
  await t.settle(10);
  await t.click("Note", { within: t.view.querySelector(".dv-selbar") });
  await t.type("Your note", "Repair as a habit.");
  const slow = held();
  t.answer("POST /api/projects/Study/notes", () => slow.promise.then(() => ({ note: { note_id: "n1", doc_id: "d1", start: at, end: at + 17, quote: "everyday practice", text: "Repair as a habit.", colour: "yellow", mine: true } })));
  const btn = t.find("Keep the note", { within: t.dialog() });
  await t.click(btn);
  const busy = btn.getAttribute("aria-busy");
  await t.click(btn);                                                     // a double click
  await t.press("Enter", t.field("Your note"), { meta: true });           // and Cmd+Enter
  slow.release();
  await t.settle();
  return { posts: t.calls.filter((c) => c.method === "POST" && c.path.endsWith("/notes")).length, busy, open: t.dialogs().length };
});
await scenario("log: an edit saved again after a failed save", async (t) => {
  t.state({ settings: {} });
  const e = { entry_id: "e1", kind: "entry", group: "entries", mine: true, can_edit: true, at: "2026-11-18T10:00:00Z", text: "Decided to drop the 2019 reports." };
  t.answer("GET /api/projects/Study/log?*", { entries: [e], total: 1, groups: { entries: 1 }, group_names: { entries: "Your entries" } });
  t.answer(/^GET \/api\/projects\/Study\/sharing/, { items: [] });
  await t.render("views/log.js", "renderLog", [], {});
  await t.click(t.view.querySelector(".log-more summary"));
  await t.click(document.querySelector(".log-more [role=menuitem]"));
  await t.type(t.dialog().querySelector("textarea"), "Decided to drop the 2019 reports: their method changed.");
  let n = 0;
  t.answer("PUT /api/projects/Study/log/e1", () => (++n === 1 ? t.fail(401, "no key") : { ok: true }));
  await t.click("Save", { within: t.dialog() });
  const failedOpen = t.dialogs().length;
  const btn = t.find("Save", { within: t.dialog() });
  const usable = !!btn && !btn.disabled && btn.getAttribute("aria-busy") !== "true";
  await t.click(btn);
  await t.settle();
  return { failedOpen, usable, puts: n, open: t.dialogs().length };
});
await scenario("concepts: own words typed while the glossary is made again", async (t) => {
  t.state({ settings: {}, projects: [{ name: "Study", ok: true, documents: 3 }] });
  let own = ["Interviewer"];
  t.answer("GET /api/projects/Study/terms?*", { built: true, total: 0, items: [], offset: 0, terms: 0, concepts: 0, built_at: "2026-11-18T10:00:00Z" });
  t.answer("GET /api/projects/Study/terms/words", () => ({ languages: [], off: [], own, max_own: 500 }));
  t.answer("PUT /api/projects/Study/terms/words", (b) => { own = b.own.filter(Boolean); return { ok: true }; });
  t.answer("POST /api/projects/Study/terms/build", { job: { id: "jg" } });
  let state = "running";
  t.answer("GET /api/jobs/jg", () => ({ id: "jg", state, progress: { done: 1, total: 9 } }));
  await t.render("views/concepts.js", "renderConcepts", [], {});
  await t.click(t.view.querySelector("#left-out > summary"));
  await t.type(document.getElementById("ct-own-words"), "Interviewer\nR1");
  await t.click("Save and update the glossary");
  const field = document.getElementById("ct-own-words");
  await t.type(field, "Interviewer\nR1\nzeg maar");                // the next word, while the glossary is made
  state = "done";
  await t.settle(1500);
  const now = document.getElementById("ct-own-words");
  return { value: now ? now.value : null, same: now === field };
});
await scenario("log: an edit of an entry whose save fails", async (t) => {
  t.state({ settings: {} });
  const e = { entry_id: "e1", kind: "entry", group: "entries", mine: true, can_edit: true, at: "2026-11-18T10:00:00Z", text: "Decided to drop the 2019 reports." };
  t.answer("GET /api/projects/Study/log?*", { entries: [e], total: 1, groups: { entries: 1 }, group_names: { entries: "Your entries" } });
  t.answer(/^GET \/api\/projects\/Study\/sharing/, { items: [] });
  await t.render("views/log.js", "renderLog", [], {});
  await t.click(t.view.querySelector(".log-more summary"));
  await t.click(document.querySelector(".log-more [role=menuitem]"));
  const words = "Decided to drop the 2019 reports: their method changed halfway, so they cannot be compared with the rest.";
  const ta = t.dialog().querySelector("textarea");
  await t.type(ta, words);
  t.answer("PUT /api/projects/Study/log/e1", t.fail(404, "Not found: e1"));     // removed meanwhile by one's other account
  await t.click("Save", { within: t.dialog() });
  return { kept: typedStill(words), errors: t.toasts() };
});

// ---- siblings of PAGESB-2/3 (fixer): other dialogs of these views that took words and saved them after closing ------
const inOpenDialog = (el) => !!el && !!el.closest("dialog") && el.closest("dialog").open && el.isConnected;
await scenario("rename: a document title whose save fails", async (t) => {
  t.state({ settings: {} });
  const m = await t.module("views/doc-shared.js");
  m.renameDocument("Study", { doc_id: "d1", title: "Interviews", file: "interviews.txt", named: false });
  await t.settle();
  await t.type("New title", "Interviews with the volunteers of the Leiden repair café, spring 2026");
  t.answer("PUT /api/projects/Study/documents/d1/title", t.fail(404, "Not found: d1"));
  await t.click("Rename", { within: t.dialog() });
  const f = t.field("New title");
  return { kept: inOpenDialog(f) && f.value === "Interviews with the volunteers of the Leiden repair café, spring 2026", said: t.text(t.dialog()) };
});
await scenario("evidence: a note's comment whose save fails", async (t) => {
  t.state({ settings: {} });
  t.answer("GET /api/projects/Study/hypotheses", { hypotheses: [{ hyp_id: "h1", text: "Repair cafés build a community" }] });
  t.answer("GET /api/projects/Study/hypotheses/h1", { parts: [{ claim_id: "c1", claim: "Repair cafés build a community" }] });
  const m = await t.module("views/notes.js");
  m.useAsEvidence({ note_id: "n1", quote: "Repair cafés" });
  await t.settle();
  await t.type(t.dialog().querySelector("select"), "h1");
  await t.settle();
  const words = "The volunteers say so in four interviews, not only in this one.";
  await t.type("Comment", words);
  t.answer("POST /api/projects/Study/notes/n1/evidence", t.fail(404, "Not found: c1"));   // the check was removed meanwhile
  await t.click("Add as evidence", { within: t.dialog() });
  const f = t.field("Comment");
  return { kept: inOpenDialog(f) && f.value === words, said: t.text(t.dialog()) };
});
const HELD = "A removed codebook called 'remote_work' still has its labels or its earlier versions, kept under that name: a new codebook of the name would take them over. Bring it back from History (Restore), or choose another name.";
await scenario("new codebook: a name a removed codebook still holds", async (t) => {
  t.state({ settings: {} });
  t.answer("GET /api/projects/Study/codebooks", { codebooks: [] });
  t.answer("POST /api/projects/Study/codebooks", t.fail(400, HELD));
  const m = await t.module("views/codebooks.js");
  m.newCodebook();
  await t.settle();
  await t.type("Title", "Remote work");
  await t.click("Create", { within: t.dialog() });
  const f = t.field("Title");
  return { kept: inOpenDialog(f) && f.value === "Remote work", said: t.dialog() ? t.text(t.dialog()) : "", toasts: t.toasts() };
});
await scenario("new codebook from theory: a name a removed codebook still holds", async (t) => {
  t.state({ settings: {} });
  t.answer("GET /api/projects/Study/codebooks", { codebooks: [] });
  t.answer("GET /api/projects/Study/codebook-theory/draft", { draft: null, documents: [{ doc_id: "d1", title: "Practice theory", theory: true }] });
  t.answer("POST /api/projects/Study/codebook-theory/draft", t.fail(400, HELD));
  const m = await t.module("views/codebooks.js");
  m.newCodebook("theory");
  await t.settle();
  await t.type("Title", "Remote work");
  await t.click("Next", { within: t.dialog() });
  const focus = "How do people working from home keep a working day?";
  await t.type(t.dialog().querySelector("textarea"), focus);
  await t.click("Start the draft", { within: t.dialog() });
  const f = t.field("Title");
  const out = { kept: inOpenDialog(f) && f.value === "Remote work", said: t.dialog() ? t.text(t.dialog()) : "" };
  await t.click("Next", { within: t.dialog() });
  const ta = t.dialog() && t.dialog().querySelector("textarea");
  out.focusKept = !!ta && ta.value === focus;
  return out;
});
"""


@pytest.fixture(scope="module")
def page(tmp_path_factory):
    return run_views(PROBE, tmp_path_factory.mktemp("pagesb"))


@needs_node
def test_words_typed_in_the_codebook_editor_while_it_saves_are_kept(page):
    """Typing in a code's definition while Save is on its way: the answer redraws the editor from what was sent, so
    the words typed meanwhile vanish and the editor says nothing is unsaved (codebooks.js:949 `save`, fresh() + draw())."""
    r = page["codebook: words typed while a save is under way"]
    assert r["field"] == "Fixing things together, in a café"
    assert r["unsaved"] is True


@needs_node
def test_typing_in_the_codebook_editor_while_try_it_finishes_keeps_the_field_and_its_caret(page):
    """Try it ends while the person types in a code's definition: draw() rebuilds every field, so the field being typed
    in is replaced and the keyboard's focus is lost mid-word (codebooks.js:998 `tryIt` calls draw())."""
    r = page["codebook: typing while Try it runs"]
    assert r["value"] == "Fixing things toge"
    # loosened as the verdict says: the field may be rebuilt, if the focus is back in the (new) Definition field
    assert r["focusedIsField"] is True and r["focused"]["label"] == "Definition", r


@needs_node
def test_a_file_removed_from_the_list_while_the_others_are_copied_is_not_added(page):
    """After Add, the list still offers each file's Remove; a file removed while an earlier one is being copied is
    copied and added all the same (sources.js:52 removes it from `files`, the loop at :197 sends `sent`)."""
    r = page["documents: a file removed from the list while the others are copied"]
    assert "two.pdf" in r["listed"]
    assert r["removable"] is False or r["sent"] == ["one.pdf"]


@needs_node
def test_the_new_reader_offered_to_a_reader_4_text_file_says_what_reader_7_changes(page):
    """A text file read by reader 4 is offered reader 7 (it reads text files otherwise), but the Documents notice and
    the Reading panel tell it reader 5's news (tables, figures from PDFs; "Other text reads the same")
    (sources.js:801, doc-reading.js:64)."""
    told = {scen: page[scen] for scen in ("documents: the offer of the new reader to a reader-4 text file",
                                          "document page: the Reading panel of a reader-4 text file")}
    # loosened as the verdict says (it pinned one sentence of READER_7_NEWS): not reader 5's "Other text reads the same",
    # and what reader 7 changes for text files (a line that comes back in an interview, one paragraph per line)
    assert [s for s, said in told.items() if "Other text reads the same" in said
            or not ("interview" in said and "one per line" in said)] == [], told


@needs_node
def test_a_note_whose_save_fails_keeps_the_words_typed(page):
    """Note (on a document's selected words) and Edit (on the Notes page): the dialog closes before the save, so when
    the app refuses it the words typed are gone and only an error toast remains (doc-page.js:488 `noteDialog`,
    notes.js:38 `editNote`)."""
    got = {scen: page[scen] for scen in ("note: a new note whose save fails", "note: an edit whose save fails")}
    assert [s for s, r in got.items() if r["kept"] is not True] == [], got


@needs_node
def test_own_words_typed_while_the_glossary_is_made_again_are_kept(page):
    """Save and update the glossary, then type one more of your own words while it is made: when the job ends the
    section is drawn anew from the saved list, and the word typed meanwhile is gone (concepts.js:76 calls drawWords(),
    which rebuilds the field at :197)."""
    r = page["concepts: own words typed while the glossary is made again"]
    assert r["value"] == "Interviewer\nR1\nzeg maar", r


@needs_node
def test_a_research_log_entry_whose_edit_fails_keeps_the_words_typed(page):
    """Edit of one's own entry in the research log: the dialog closes, then the save is sent; when it fails the
    rewritten entry is lost (log.js:191 `editEntry`, the same in `editWhy`)."""
    r = page["log: an edit of an entry whose save fails"]
    assert r["kept"] is True, r


# ---- a label on selected words: the page and the app together ------------------------------------------------
LABEL_PROBE = r"""
await scenario("label the second of two alike phrases", async (t) => {
  const DOC = `/api/projects/Study/documents/${REAL.doc_id}`;
  t.state({ settings: {} });
  t.answer(/^GET /, {});
  t.answer(`GET ${DOC}?*`, REAL.doc);
  t.answer(new RegExp(`^GET ${DOC.replace(/[.*+?^${}()|[\]\\/]/g, "\\$&")}/role`), { role: null });
  t.answer(`GET ${DOC}/nonscientific-suggestion`, { suggested: false });
  t.answer(`GET ${DOC}/notes`, { notes: [] });
  t.answer(`GET ${DOC}/profile?*`, REAL.profile);
  t.answer("GET /api/projects/Study/frameworks", REAL.frameworks);
  t.answer("GET /api/projects/Study/frameworks/sdg", REAL.sdg);
  t.answer("GET /api/projects/Study/search?*", REAL.search);
  t.answer("GET /api/jobs", { jobs: [] });
  let sent = null;
  t.answer("POST /api/projects/Study/labels", (b) => { sent = b; return { label_id: "x" }; });
  await t.render("views/doc-page.js", "renderDocument", [REAL.doc_id], {});
  const walk = (n) => { for (const c of n.childNodes) { if (c instanceof Text && c.data.includes(REAL.second)) return c; const f = c.childNodes && walk(c); if (f) return f; } return null; };
  const node = walk(t.view.querySelector(".dv-text"));                 // the document's text (its title repeats it)
  const at = node.data.indexOf(REAL.second);
  t.select(node, at, at + REAL.words.length);
  node.parentNode.dispatchEvent(new Event("mouseup", { bubbles: true }));
  await t.settle(10);
  await t.click("Label it with a code", { within: t.view.querySelector(".dv-selbar") });
  await t.settle(10);
  await t.type(document.getElementById("dv-add-code"), "6.4");
  await t.click("Add my label");
  return sent;
});
"""


@needs_node
def test_a_label_given_to_selected_words_lands_on_those_words(tmp_path):
    """Select the second of two places where the same words stand in a passage and choose Label it with a code: the
    page sends only the words, not where they are, and the label is placed on their first occurrence
    (doc-codes.js:293 `labelSelection` / :276; profile.py `add_label` finds the quote from the passage's start)."""
    import threading
    import urllib.parse
    import urllib.request

    from enlens_claims import home, ingest
    from enlens_claims.gui.server import make_server

    ws = home.create_project("Study")
    text = ("In spring the water was clean and the town was proud of its river. "
            "By the autumn the water was dirty and nobody in the town drank it any more.")
    src = tmp_path / "river.txt"
    src.write_text(text, encoding="utf-8")
    ingest.ingest(ws, [src])
    srv, app = make_server("127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def call(method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(base + path, data=data, method=method,
                                     headers={"X-Enlens-Token": app.token, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())

    try:
        doc_id = call("GET", "/api/projects/Study/documents")["documents"][0]["doc_id"]
        words, second = "water was", "water was dirty"
        real = {
            "doc_id": doc_id, "words": words, "second": second,
            "doc": call("GET", f"/api/projects/Study/documents/{doc_id}?view=blocks&offset=0&limit=500"),
            "profile": call("GET", f"/api/projects/Study/documents/{doc_id}/profile?framework=sdg"),
            "frameworks": call("GET", "/api/projects/Study/frameworks"),
            "sdg": call("GET", "/api/projects/Study/frameworks/sdg"),
            "search": call("GET", "/api/projects/Study/search?" + urllib.parse.urlencode(
                {"q": f'"{words}"', "docs": doc_id, "mode": "phrase", "limit": "200", "width": "20"})),
        }
        block = next(b for b in real["doc"]["blocks"] if second in b["text"])
        want = block["start"] + block["text"].index(second)
        sent = run_views(f"const REAL = {json.dumps(real)};\n" + LABEL_PROBE, tmp_path)["label the second of two alike phrases"]
        assert sent and sent.get("quote") == words, sent
        call("POST", "/api/projects/Study/labels", sent)
        got = ws.query("SELECT start, end FROM labels WHERE source='person'")
        assert [(r["start"], r["end"]) for r in got] == [(want, want + len(words))]
    finally:
        srv.shutdown()
        srv.server_close()


# ---- siblings found by the fixer -----------------------------------------------------------------------------------
@needs_node
def test_a_document_title_whose_save_fails_keeps_the_words_typed(page):
    """Sibling of PAGESB-2 (doc-shared.js `renameDocument`): the dialog closed, then the title was sent; a refusal
    left a toast and lost the title typed."""
    r = page["rename: a document title whose save fails"]
    assert r["kept"] is True and "Not found: d1" in r["said"], r


@needs_node
def test_a_comment_given_with_a_note_as_evidence_is_kept_when_the_save_fails(page):
    """Sibling of PAGESB-2 (notes.js `useAsEvidence`): the comment typed beside the judgement was sent after the dialog
    had closed, and lost when the save failed."""
    r = page["evidence: a note's comment whose save fails"]
    assert r["kept"] is True and "Not found: c1" in r["said"], r


@needs_node
def test_new_codebook_refused_for_a_removed_codebooks_name_stays_open_with_what_was_typed(page):
    """The page side of CONCEPTS-1 (codebooks.js `newCodebook`): the server refuses a name a removed codebook still
    holds; the dialog had closed, so the refusal was a toast and the title had to be typed again."""
    r = page["new codebook: a name a removed codebook still holds"]
    assert r["kept"] is True and "removed codebook called 'remote_work'" in r["said"], r


@needs_node
def test_new_codebook_from_theory_refused_for_a_removed_codebooks_name_keeps_what_was_typed(page):
    """The same through *From theory documents* (`startTheoryDraft`): the refusal comes after the theory step; the
    first dialog comes back with the title and the reason, and the theory step keeps the question typed in it."""
    r = page["new codebook from theory: a name a removed codebook still holds"]
    assert r["kept"] is True and "removed codebook called 'remote_work'" in r["said"] and r["focusKept"] is True, r


@needs_node
def test_two_files_of_one_name_are_both_said_to_be_added(page):
    """The page side of the server's fix (two files called notes.txt from two folders: the second was written over the
    first): both are listed, both are sent, and the summary says the second was added under its own name."""
    r = page["documents: two files of one name"]
    assert r["listed"].count("notes.txt") == 2, r
    assert "2 documents added" in r["said"] and "notes.txt as “notes (2).txt”" in r["said"], r["said"]


@needs_node
def test_the_news_of_a_move_names_every_reader_since_that_changes_the_file(tmp_path):
    """Sibling of PAGESB-8: the chain told a reader-3 Word file reader 4's news alone (reader 5 and 7 change Word files
    again), and a reader-4 PDF reader 5's alone (reader 6 changes PDFs). Each now hears every reader that changes its
    kind, without the "reads the same" lines that one reader's news says of the others."""
    from test_reader5_reading_view import _news

    got = _news(tmp_path, [[[{"reader": 3, "kind": "docx"}], 7], [[{"reader": 4, "kind": "pdf"}], 7], [[{"reader": 6, "kind": "html"}], 7],
                           [[{"reader": 4, "kind": "text"}, {"reader": 5, "kind": "pdf"}], 7]])
    word, pdf, page, both = got
    assert "content controls" in word and "ruled lines" in word and "text box is read once" in word, word
    assert "ruled lines" in pdf and "hides behind a figure" in pdf and "text box" not in pdf, pdf
    assert page == "7"
    assert "hides behind a figure" in both and "one per line" in both and "ruled lines" not in both, both
    assert not any("reads the same" in x or "read the same" in x for x in (word, pdf, both)), got


def test_a_label_given_with_its_quote_alone_lands_on_the_first_place_as_before(tmp_path):
    """PAGESB-4, the server's half: `profile.add_label` places the quote nearest `start` when the page says where the
    words were selected, and a call with the quote alone (other callers, an older page) keeps the first place."""
    from enlens_claims import home, ingest, profile

    ws = home.create_project("Study")
    text = ("In spring the water was clean and the town was proud of its river. "
            "By the autumn the water was dirty and nobody in the town drank it any more.")
    src = tmp_path / "river.txt"
    src.write_text(text, encoding="utf-8")
    ingest.ingest(ws, [src])
    p = next(r for r in ws.query("SELECT passage_id, start, text FROM passages") if r["text"].count("water was") == 2)
    first = p["start"] + p["text"].index("water was")
    second = p["start"] + p["text"].index("water was dirty")
    profile.add_label(ws, "sdg", p["passage_id"], "6.4", quote="water was")
    assert [(r["start"], r["end"]) for r in ws.query("SELECT start, end FROM labels WHERE source='person'")] == [(first, first + 9)]
    profile.add_label(ws, "sdg", p["passage_id"], "6.4", quote="water was", start=second)   # the same label id: replaced
    assert [(r["start"], r["end"]) for r in ws.query("SELECT start, end FROM labels WHERE source='person'")] == [(second, second + 9)]
    profile.add_label(ws, "sdg", p["passage_id"], "6.4", quote="water was", start="nonsense")   # a bad start: as before
    assert [r["start"] for r in ws.query("SELECT start FROM labels WHERE source='person'")] == [first]


# ---- the redraw sweep (fixer): the framework draft page when the theory's reading ends ------------------------------
THEORY_PROBE = r"""
const BASE = "/api/projects/Study/codebook-theory/draft";
const DRAFT = (o = {}) => ({ title: "Repair theory", name: "repair", where: "project", doc_ids: ["d1"], focus: "", rev: 3,
  reading: { state: "none", job: null, problems: [] }, left_out: [], groups: [{ key: "g1", name: "Practice", about: "" }],
  concepts: [{ key: "c1", name: "habitus", group: "g1", meaning: "Lasting dispositions", when_to_use: "", when_not: "", keep: true,
    checked: false, how: "found", sources: [], examples: [], words: [], ai: null }], ...o });
await scenario("theory draft: settings typed while the theory is read", async (t) => {
  let state = "running";
  t.state({ settings: { backend: "claude_code" } });
  const offer = { offered: true, reader: "claude", parts: 1, why: "", documents: [{ doc_id: "d1", title: "Practice theory", level: "cloud", parts: 1, offered: true, why: "" }] };
  t.answer(`GET ${BASE}`, () => ({ draft: state === "running" ? DRAFT({ reading: { state: "running", job: "jr", problems: [] } })
    : DRAFT({ rev: 5, reading: { state: "read", job: null, problems: [] } }), offer, documents: [{ doc_id: "d1", title: "Practice theory" }] }));
  t.answer(`GET ${BASE}/counts`, { documents: 1, counts: {} });
  t.answer(`PUT ${BASE}`, (body) => ({ draft: { rev: (body.rev || 0) + 1, reading: { stale: false } } }));
  t.answer("GET /api/jobs/jr", () => ({ id: "jr", state, progress: { done: 1, total: 3 }, result: state === "done" ? { ok: true, concepts: 1, groups: 1 } : null }));
  await t.render("views/theory-draft.js", "renderTheoryDraft");
  await t.click(t.view.querySelector("details.cb-settings > summary"));
  await t.type("Short name", "repair_theory");          // not sent while the AI reads: only the title and the question are
  await t.type("Title", "Repair theory, revised");      // sent 800 ms after the last key
  state = "done";
  await t.settle(600);                                   // the reading ends (the job is asked every 500 ms)
  const now = { name: (t.field("Short name") || {}).value, title: (t.field("Title") || {}).value, focused: t.focused() };
  await t.settle(1500);
  const last = t.calls.filter((c) => c.method === "PUT").pop();
  return { ...now, sent: last ? { name: last.body.name, title: last.body.title } : null };
});

// the Codes panel of a document: a note typed in a label's "Change how it applies" when the codes are read again (the AI's
// labelling of the document ends, or the keyword pass: both call load(); `live` is the same load)
await scenario("codes panel: a label's note typed when the codes are read again", async (t) => {
  t.state({ settings: {} });
  const item = { passage_id: "p1", source: "model", label_id: "l1", relevance: "main", confidence: 0.8, quote: "a quote", reason: "why", location: "page 1", provisional: false };
  t.answer("GET /api/projects/Study/documents/d1/profile?*", { framework_title: "B", code_label: "code", pass1: { done: true }, passages: 5, n_pages: 2, read_by_model: 1,
    codes: [{ code: "X1", description: "Same code", share: 0.5, passages: 1, main: 1, pages: [1], positions: [10], items: [item] }] });
  t.answer("GET /api/projects/Study/frameworks", { frameworks: [{ name: "B", title: "B" }] });
  t.answer("GET /api/projects/Study/profile/plan?*", { passages: 5, with_candidates: 5, already_read: 5, to_read: 0, run: {} });
  t.answer(/^GET \/api\/projects\/Study\/search/, { lines: [] });
  const m = await t.module("views/doc-codes.js");
  const ctx = { query: { code: "X1" }, docBase: "/api/projects/Study/documents/d1", base: "/api/projects/Study", keepUrl() {}, project: "Study",
    watchers: [], docId: "d1", jumpTo() {}, paint() {}, framework: "B", tab: "codes" };
  const panel = m.codesPanel(ctx);
  document.getElementById("view").appendChild(panel.el);
  await t.settle(50);
  await t.click(document.querySelector(".judge-diff > summary"));
  await t.click(document.querySelector('.judge-diff input[value="mentioned"]'));
  await t.type("Your note on this label", "only in passing, in the last sentence");
  await panel.live();
  await t.settle(50);
  const f = t.field("Your note on this label");
  const r = document.querySelector('.judge-diff input[value="mentioned"]');
  return { note: f ? f.value : null, mentioned: !!r && r.checked, focused: t.focused() };
});

// the Bibliography: a list's filter typed while the check for retractions runs; its end draws the page again
await scenario("bibliography: a filter typed while the retractions are checked", async (t) => {
  t.state({ settings: {} });
  const W = (key, title, authors, year) => ({ key, title, authors, year, cite: `${authors} ${year}`, type: "article", notices: [] });
  t.answer("GET /api/projects/Study/bibliography", { bibliography: { kind: "file", name: "refs.ris", pulled_at: "2026-11-18T10:00:00Z" },
    counts: { works: 3, to_find: 3, linked: 0, confirm: 0, not_in: 0 }, to_find: [W("a", "Governing the commons", "Ostrom", 1990), W("b", "Repair cafés", "Charter", 2018), W("c", "The craftsman", "Sennett", 2008)],
    linked: [], confirm: [], not_in: [], retractions: {}, ai_access: { chosen: true, default: "cloud" } });
  let state = "running";
  t.answer("POST /api/projects/Study/retractions/check", { job: { id: "jx" } });
  t.answer("GET /api/jobs/jx", () => ({ id: "jx", state, progress: { done: 1, total: 3 }, result: state === "done" ? { looked_up: 3, notices: 0 } : null }));
  await t.render("views/bibliography.js", "renderBibliography");
  await t.click("Check for retractions");
  await t.type("Filter by title, author or year", "ostrom");
  state = "done";
  await t.settle(1200);
  const f = t.field("Filter by title, author or year");
  return { filter: f ? f.value : null, rows: t.view.querySelectorAll(".bib-table tbody tr").length, focused: t.focused() };
});
"""


@needs_node
def test_settings_typed_in_a_framework_draft_while_the_theory_is_read_are_kept(tmp_path):
    """The redraw sweep, theory-draft.js `reload` (the hunter's suspicion, proven): the reading's end loads the draft
    again and drew every field from it, so a short name typed while the AI read (never sent while it reads) and a title
    typed in the last 800 ms were gone, and the field in use lost the keyboard's focus."""
    r = run_views(THEORY_PROBE, tmp_path)["theory draft: settings typed while the theory is read"]
    assert r["name"] == "repair_theory" and r["title"] == "Repair theory, revised", r
    assert r["focused"] and r["focused"]["label"] == "Title", r
    assert r["sent"] == {"name": "repair_theory", "title": "Repair theory, revised"}, r



@needs_node
def test_a_note_typed_on_a_label_is_kept_when_the_codes_are_read_again(tmp_path):
    """The redraw sweep, doc-codes.js `draw`: the codes are read again when the AI's labelling of the document or the
    keyword pass ends, and the list was drawn anew: a label's open *Change how it applies* closed, with the note typed
    in it and the choice made, and the field lost the keyboard's focus."""
    r = run_views(THEORY_PROBE, tmp_path)["codes panel: a label's note typed when the codes are read again"]
    assert r["note"] == "only in passing, in the last sentence" and r["mentioned"] is True, r
    assert r["focused"] and r["focused"]["label"] == "Your note on this label", r



@needs_node
def test_a_bibliography_filter_typed_while_a_check_runs_is_kept(tmp_path):
    """The redraw sweep, bibliography.js: the end of a job it follows (retractions, bringing in, Zotero's files) draws
    the whole page again, so the filter typed meanwhile was emptied, the list showed every work again and the field
    lost the keyboard's focus."""
    r = run_views(THEORY_PROBE, tmp_path)["bibliography: a filter typed while the retractions are checked"]
    assert r["filter"] == "ostrom" and r["rows"] == 1, r
    assert r["focused"] and r["focused"]["label"] == "Filter by title, author or year", r



@needs_node
def test_files_it_cannot_read_are_listed_under_these_could_not_be_read(page):
    """The page side of the server's fix: a damaged zip and a file of a kind ENLENS does not read (an older .doc inside
    a zip or a folder) come back in the job's `failed`, and the summary lists them under "These could not be read"."""
    said = page["documents: a damaged zip and a kind it does not read"]
    assert "No new document was added" in said and "These could not be read" in said, said
    assert "interviews.zip: damaged zip" in said and "old.doc: an older Word file" in said, said



@needs_node
def test_new_codes_keep_the_ids_the_save_gave_them_when_edited_during_the_save(page):
    """After review, PAGESB-1: the new codes of a save during which the person typed on were matched to their ids by
    the name sent; the server tidies names ("Repair " is saved "Repair"), so the code kept no id and the next Save was
    refused (a code removed and one added under its name). The page now takes the ids from the answer's `uids`, in
    the order sent: also for two new codes, one renamed and one removed while the save was on its way."""
    one = page["codebook: a new code whose name the server tidies, edited during the save"]
    assert one["unsaved"] is True and one["second"] == [["new1-0", "Repair "]], one
    two = page["codebook: two new codes sent in one save"]
    assert two["second"] == [["new1-0", "Repair  café"], ["new1-1", "Reuse "]], two
    renamed = page["codebook: a new code renamed during the save"]
    assert renamed["unsaved"] is True and renamed["second"] == [["new1-0", "Mending"]], renamed
    removed = page["codebook: a new code removed during the save"]
    assert removed["unsaved"] is True and removed["second"] == [["u2", "Reuse"]], removed


def test_a_codebook_save_answers_the_id_of_each_code_sent(tmp_path):
    """After review, PAGESB-1, the server's half: `codebooks.save` answers `uids`, the id each code sent has now in the
    order sent, a new code's included, whatever it tidied in the name; the page's next save with them goes through."""
    import copy

    from enlens_claims import codebooks, home

    ws = home.create_project("Study")
    cb = codebooks.create(ws, "cbx", "Cbx")
    new = lambda name: {"uid": "", "code": name, "description": "Fixing things.", "group": "", "include": "", "exclude": "",  # noqa: E731
                        "keywords": [], "examples": []}
    st = {**copy.deepcopy(cb), "codes": [new("Repair "), new("Reuse  of  parts")]}
    r = codebooks.save(ws, "cbx", copy.deepcopy(st))
    by_uid = {c["uid"]: c["code"] for c in r["codebook"]["codes"]}
    assert [by_uid[u] for u in r["uids"]] == ["Repair", "Reuse of parts"], r["uids"]
    for c, u in zip(st["codes"], r["uids"]):
        c["uid"] = u
    st["codes"][0]["description"] = "Fixing things together, in a café."   # typed while the save was on its way
    again = codebooks.save(ws, "cbx", {**r["codebook"], "codes": st["codes"]})
    assert again["uids"] == r["uids"] and again["changes"], again["changes"]
    ws.close_all()



@needs_node
def test_the_file_being_copied_cannot_be_taken_off_the_list(page):
    """After review, PAGESB-5: the x of the file whose upload was under way stayed on; the file left the list and was
    read in all the same (the ingest reads the whole batch folder), with the batch's AI setting. Its x is now off from
    the moment its copy starts, and says why."""
    r = page["documents: the file being copied is taken off the list"]
    assert r["removable"] is False and r["why"] and "copied" in r["why"], r
    assert "one.pdf" in r["listedAfter"] and r["uploads"] == ["one.pdf", "two.pdf"], r



@needs_node
def test_a_second_press_of_a_dialogs_button_while_it_saves_saves_once(page):
    """After review, PAGESB-2: the note is saved from inside its dialog now, and the button stayed live while the save
    ran, so a double click or Cmd+Enter twice on a slow app made two notes on the same words. `dialog()` now ignores a
    press of an action whose work is still running, and marks it busy, for every dialog."""
    r = page["note: Keep the note pressed twice while the app is slow"]
    assert r["posts"] == 1 and r["busy"] == "true" and r["open"] == 0, r


@needs_node
def test_a_dialogs_button_is_usable_again_after_a_failed_save(page):
    """The guard ends with the work: after a failed save the same button saves again (the research log's edit)."""
    r = page["log: an edit saved again after a failed save"]
    assert r == {"failedOpen": 1, "usable": True, "puts": 2, "open": 0}, r
