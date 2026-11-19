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
  return { same: now === f, focused: t.focused(), value: now ? now.value : null };
});

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
  t.answer("POST /api/projects/Study/notes", t.fail(400, "These words are not in the document's text now."));
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
  t.answer("PUT /api/projects/Study/notes/n1", t.fail(503, "The project is busy: try again in a moment."));
  await t.click("Save", { within: t.dialog() });
  return { kept: typedStill(words), errors: t.toasts() };
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
  t.answer("PUT /api/projects/Study/log/e1", t.fail(503, "The project is busy: try again in a moment."));
  await t.click("Save", { within: t.dialog() });
  return { kept: typedStill(words), errors: t.toasts() };
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
    assert r["same"] is True and r["focused"] is not None


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
    assert [s for s, said in told.items() if "reads text files, Word files and web pages otherwise" not in said] == [], told


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
