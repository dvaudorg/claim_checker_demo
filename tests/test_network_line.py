"""Settings › This installation › Network says what the app reaches over the internet. The 0.8.2 line ("This
computer only · nothing is loaded from the internet") stopped being true with update checks, team storage (Backblaze
B2, Cloudflare R2, WebDAV), cloud AI and Crossref lookups."""
from __future__ import annotations

from test_app import api, home  # noqa: F401  (fixtures)
from _views import needs_node, run_views


def test_the_state_says_whether_other_computers_can_open_the_app(api):  # noqa: F811
    code, st = api("GET", "/api/state")
    assert code == 200 and st["any_host"] is False


PROBE = r"""
async function network(t, state) {
  t.state({ settings: { backend: "claude_code" }, ...state });
  t.answer("GET /api/servers", { servers: [], suggested: [] });
  t.answer("GET /api/claude-setup", {});
  t.answer("GET /api/local-status", {});
  t.answer("GET /api/routing", { route: "claude_code", route_name: "Claude Code", rows: [], aliases: [], step_up_below: 0.6, plan: {} });
  t.answer("GET /api/whats-new", {});
  t.answer("GET /api/projects/Study/queue", { kinds: [], waiting: 0 });
  t.answer(/^GET \/api\/projects\/Study\/agreement\/plan/, { kinds: [], problem: null, kept: [], plan: {} });
  await t.render("views/settings.js", "renderSettings", ["installation"]);
  await t.settle(1000);
  const row = [...document.querySelectorAll(".kv")].find((k) => t.text(k.querySelector("dt")) === "Network");
  return { text: t.text(row.querySelector("dd")), items: row.querySelectorAll("li").map((x) => t.text(x)), wide: row.className };
}
await scenario("cloud allowed", (t) => network(t, {}));
await scenario("local only", (t) => network(t, { local_only: true }));
await scenario("open to the network", (t) => network(t, { any_host: true }));
"""


@needs_node
def test_the_network_line_names_what_goes_online(tmp_path):
    out = run_views(PROBE, tmp_path)
    cloud, local, wide = out["cloud allowed"], out["local only"], out["open to the network"]
    assert "nothing is loaded from the internet" not in cloud["text"]
    assert cloud["text"].startswith("Only this computer can open the app.")
    assert any("GitHub" in i for i in cloud["items"])
    assert any("Backblaze B2" in i for i in cloud["items"])
    assert any(i.startswith("the cloud AI you choose") for i in cloud["items"])
    assert any("Crossref" in i for i in cloud["items"])
    assert "kv-wide" in cloud["wide"]
    # under local-only no cloud AI is listed, and the line says it is switched off
    assert not any("cloud AI" in i for i in local["items"]) and "Cloud AI is switched off on this computer." in local["text"]
    assert wide["text"].startswith("Other computers on your network can open the app")


PRIVACY = r"""
async function where(t, providers) {
  t.state({ settings: { backend: "ollama", ollama_model: "qwen3:8b" }, providers });
  const { App } = await t.module("lib.js");
  return App.privacy();
}
await scenario("on this computer", (t) => where(t, { route_address: null }));
await scenario("on another computer", (t) => where(t, { route_address: "http://10.0.0.5:11434" }));
"""


@needs_node
def test_the_privacy_note_says_when_the_model_is_on_another_computer(tmp_path):
    out = run_views(PRIVACY, tmp_path)
    here, far = out["on this computer"], out["on another computer"]
    assert here["plain"] == "The AI runs on this computer. Your documents never leave it."
    assert far["label"] == "A model on another computer" and "never leave" not in far["plain"]
    assert far["where"] == "local"   # still the local route: no Claude Code queue
