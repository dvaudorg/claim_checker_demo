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
