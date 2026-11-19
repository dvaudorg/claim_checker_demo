"""Hunt phase 1, area `backends`: failing tests for defects in the model backends, routing, scoring and the records of
what made an answer. Each test asserts what ENLENS should do; it fails today for the reason in its docstring."""
from __future__ import annotations

import csv
import json
import shutil
import threading
from http.server import BaseHTTPRequestHandler
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------------------------- helpers
class _Proxy(BaseHTTPRequestHandler):
    """An HTTP proxy on another computer (here on 127.0.0.1 for the test): it records every request it is handed and
    forwards nothing."""

    def log_message(self, *a):
        pass

    def _record(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else b""
        self.server.seen.append((self.command, self.path, body.decode("utf-8", "replace")))
        self.send_response(502)
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_GET = do_POST = _record


def _start_proxy():
    from enlens_claims.gui.server import QuickServer

    srv = QuickServer(("127.0.0.1", 0), _Proxy)
    srv.seen = []
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


# --------------------------------------------------------------------------------------------- privacy
def test_text_for_a_model_on_this_computer_never_goes_through_a_proxy(monkeypatch):
    """A passage sent to a model server on this computer (127.0.0.1) goes through the HTTP proxy the environment names
    (http_proxy), so text of a document marked Only a local AI reaches another computer: llm.py:147 `local_urlopen`
    opens with urllib's default opener, which applies the proxy (bibliography.py and sync/_web.py bypass it)."""
    import fake_servers

    from enlens_claims.llm import LocalBackend

    model_srv, model_url = fake_servers.start("openai")
    proxy, proxy_url = _start_proxy()
    try:
        for k in ("no_proxy", "NO_PROXY", "all_proxy", "ALL_PROXY"):
            monkeypatch.delenv(k, raising=False)
        monkeypatch.setenv("http_proxy", proxy_url)
        monkeypatch.setenv("HTTP_PROXY", proxy_url)
        be = LocalBackend(base_url=model_url + "/v1", api_key="good-key", stall_timeout=20, timeout=60)
        secret = "The confidential interview says the plant pollutes the river."
        payload = {"claim": "The plant pollutes.", "passages": [{"text": secret, "passage_id": "p1"}]}
        try:
            be.complete("expand", "Give search words.", f"Passage: {secret}", fake_servers.FAKE_MODEL, payload)
        except Exception:  # noqa: BLE001 - what matters is where the text went
            pass
        assert proxy.seen == [], f"the proxy received: {proxy.seen[:1]}"
        assert any(secret in json.dumps(r[1]) for r in model_srv.requests)   # it went to the model server itself
    finally:
        model_srv.shutdown()
        proxy.shutdown()


def test_ollama_its_probes_and_its_embeddings_never_go_through_a_proxy(monkeypatch):
    """Siblings of the proxy fix: Ollama's chat, the look for a running Ollama (/api/version, /api/tags, /api/ps),
    a download (/api/pull) and the embedding server, at `localhost` (rewritten to 127.0.0.1) as at 127.0.0.1, all go
    to this computer without the proxy."""
    import fake_servers

    from enlens_claims import embed, llm, ollama_setup

    srv, url = fake_servers.start("ollama")
    proxy, proxy_url = _start_proxy()
    try:
        for k in ("no_proxy", "NO_PROXY", "all_proxy", "ALL_PROXY"):
            monkeypatch.delenv(k, raising=False)
        monkeypatch.setenv("http_proxy", proxy_url)
        monkeypatch.setenv("HTTP_PROXY", proxy_url)
        monkeypatch.setattr(ollama_setup, "wake", lambda *a, **k: True)   # never starts a real Ollama
        at_localhost = url.replace("127.0.0.1", "localhost")
        for u in (url, at_localhost):
            assert llm.ollama_version(u, 2) is not None
            be = llm.OllamaBackend(base_url=u, timeout=30)
            be._woken = True
            assert be.models()
            be.loaded()
            secret = "The confidential interview says the plant pollutes the river."
            be.complete("expand", "Give search words.", f"CLAIM: {secret}", fake_servers.FAKE_MODEL, {"claim": secret})
            assert embed.OllamaEmbedder(fake_servers.FAKE_EMBED, base_url=u).embed([secret])
        assert proxy.seen == [], f"the proxy received: {proxy.seen[:1]}"
    finally:
        srv.shutdown()
        proxy.shutdown()


@pytest.mark.parametrize("url", ["http://localhost.localdomain:1234/v1", "http://lab.localhost:1234/v1",
                                 "http://192.168.1.20:1234/v1", "http://gpu-box.lan:11434"])
def test_a_local_server_at_a_name_the_network_answers_is_another_computer(url):
    """docs/manual/privacy.md: a model server on another computer is any address "not localhost, 127.0.0.1 or ::1",
    and it reads no document marked Only a local AI. providers.on_this_computer also took `localhost.localdomain` and
    any name ending in `.localhost`, names some computers ask the network's name server for, so such a server read
    those documents."""
    from enlens_claims import access, providers
    from enlens_claims.llm import LocalBackend

    assert not providers.on_this_computer(url)
    assert access.backend_levels(LocalBackend(base_url=url)) == {"cloud"}
    for here in ("http://localhost:1234/v1", "http://127.0.0.1:11434", "http://[::1]:8080", "http://127.0.0.2:1"):
        assert access.backend_levels(LocalBackend(base_url=here)) == {"cloud", "local"}


# --------------------------------------------------------------------------------------------- the record of answers
def test_an_answer_from_the_claude_api_is_not_said_to_be_made_at_temperature_0(loaded):
    """The Claude API is sent no temperature, and its answers record none (0.18.1), but *How these results were made*
    still says Temperature 0 for them: runs.py:202 defaults a missing temperature to 0 for every route but Claude Code."""
    from enlens_claims import profile, runs
    from enlens_claims.llm import AnthropicBackend

    class Block:
        type, text = "text", '{"labels": [], "note": "nothing here"}'

    class Msgs:
        def create(self, **kw):
            assert "temperature" not in kw   # what the Claude API is really sent
            return type("M", (), {"content": [Block()]})()

    be = AnthropicBackend(client=type("C", (), {"messages": Msgs()})())
    profile.keyword_pass(loaded, "sdg")
    profile.run_labels(loaded, "sdg", be, "claude-haiku-5-5", limit=1)
    rows = [r for r in runs.provenance_table(loaded, kinds=("label",)) if r.get("Route") == "Claude API"]
    assert rows, runs.provenance_table(loaded, kinds=("label",))
    assert all(r["Temperature"] == "" for r in rows), rows


# --------------------------------------------------------------------------------------------- answers
def test_a_cloud_answer_that_takes_too_long_is_given_up():
    """A provider (or a local server) that keeps sending a token every fraction of a second is never given up at its
    time limit (CloudBackend: "or takes over 10 [minutes], is given up"): llm.py:217-220 `_read_lines` looks at the
    total time only while nothing arrives, and LocalBackend's `on_line` (llm.py:1099) never looks at it."""
    import time

    from enlens_claims.llm import BackendError, CloudBackend

    class Slow:
        """A streamed answer: a token every 0.25 s for about 4 s, then the end."""
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def close(self):
            pass

        def __iter__(self):
            for i in range(16):
                time.sleep(0.25)
                chunk = {"choices": [{"delta": {"reasoning_content": "hmm "}, "finish_reason": None}]}
                yield f"data: {json.dumps(chunk)}\n".encode()
            yield b'data: {"choices": [{"delta": {"content": "{\\"terms\\": [\\"a\\"]}"}, "finish_reason": "stop"}]}\n'
            yield b"data: [DONE]\n"

    be = CloudBackend("openai", "sk-test-key-123456", base_url="https://api.openai.com/v1", timeout=1,
                      stall_timeout=30, opener=lambda req, timeout=None: Slow())
    t0 = time.time()
    with pytest.raises(BackendError):
        be.complete("expand", "Give search words.", "CLAIM: x", "gpt-6-luna", {"claim": "x"})
    assert time.time() - t0 < 3


# --------------------------------------------------------------------------------------------- routing
def test_asking_a_stronger_model_never_goes_to_a_weaker_one():
    """A person who chose Fable for checks (Settings, AI model per task) and presses *Ask a stronger model* gets Opus,
    a weaker model, recorded as the stronger one: routing.py:298-320 `step_up` takes the kind's default step for a
    chosen model that is not on the Haiku-Sonnet-Opus ladder and never compares it with the model chosen."""
    from enlens_claims import routing

    r = routing.from_settings({"backend": "claude_code", "task_models": {"claude": {"check": "fable"}}})
    assert r.first("check") == "fable"
    up = r.step_up("check")
    assert up is None or routing.RANK[up] > routing.RANK["fable"], up


@pytest.mark.parametrize("backend", ["claude_code", "anthropic"])
def test_a_check_chosen_on_opus_steps_up_only_to_fable(backend):
    """Sibling of the Fable case: Opus chosen for checks stepped "up" to the auditor, Opus itself, recorded as the
    stronger model; with *Let the auditor use Fable* on it goes to Fable. A full Claude id ranks as its alias, and a
    model of unknown strength does not step."""
    from enlens_claims import routing

    base = {"backend": backend, "task_models": {"claude": {"check": "opus"}}}
    assert routing.from_settings(base).step_up("check") is None
    fable_on = routing.from_settings({**base, "use_fable": True})
    assert fable_on.first("check") == "opus" and fable_on.step_up("check") == "fable"
    sonnet = routing.from_settings({"backend": backend, "task_models": {"claude": {"check": "sonnet"}}})
    assert sonnet.step_up("check") == "opus"
    full = routing.from_settings({"backend": backend, "task_models": {"claude": {"check": "claude-opus-5-5"}}})
    assert full.step_up("check") is None
    odd = routing.from_settings({"backend": backend, "task_models": {"claude": {"check": "claude-mystery-1"}}})
    assert odd.step_up("check") is None


def test_every_claude_model_has_its_place_on_the_ladder():
    """The ladder is written out (routing.RANK): a model offered in Settings (ALIASES), with an API id, or named by a
    helper, that has no place on it would step sideways (BACKENDS-6), so it fails here instead."""
    from enlens_claims import routing

    assert set(routing.RANK) == set(routing.ALIASES) == set(routing.API_IDS)
    assert all(m in routing.RANK for m in routing.HELPER_MODEL.values())
    assert [routing.RANK[m] for m in routing.LADDER] == sorted(routing.RANK[m] for m in routing.LADDER)
    assert max(routing.RANK, key=routing.RANK.get) == "fable"
    assert len(set(routing.RANK.values())) == len(routing.RANK)   # no two models of the same strength
    for a, full in routing.API_IDS.items():
        assert routing.rank(full) == routing.RANK[a]


def test_the_result_page_says_fable_has_no_stronger_model(monkeypatch, tmp_path, corpus):
    """With Fable chosen for checks, the result page offers no *Ask a stronger model* and says why (not "turn on
    Fable", which it is already), and asking anyway is refused."""
    import urllib.request

    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    for k in ("http_proxy", "HTTP_PROXY", "all_proxy", "ALL_PROXY"):
        monkeypatch.delenv(k, raising=False)
    from enlens_claims import claimcheck, ingest
    from enlens_claims import home as ehome
    from enlens_claims.gui.server import make_server
    from enlens_claims.llm import BaselineBackend

    srv, app = make_server("127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def api(method, path, body=None):
        req = urllib.request.Request(base + path, method=method, data=json.dumps(body).encode() if body is not None
                                     else None, headers={"X-Enlens-Token": app.token,
                                                         "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode() or "{}")

    try:
        st, _ = api("PUT", "/api/settings", {"backend": "claude_code", "embed_backend": "off",
                                             "task_models": {"claude": {"check": "fable"}}})
        assert st == 200
        ws = ehome.create_project("F")
        ingest.ingest(ws, [corpus])
        hid = claimcheck.check_hypothesis(ws, "Green hydrogen can increase water stress.", BaselineBackend(), "m",
                                          k=3, per_doc=2)
        st, h = api("GET", f"/api/projects/F/hypotheses/{hid}")
        assert st == 200 and h["stronger_model"] is None and h["stronger_reason"] == "strongest_model", \
            (h.get("stronger_model"), h.get("stronger_reason"))
        st, r = api("POST", f"/api/projects/F/hypotheses/{hid}/stronger", {})
        assert st == 400 and "no stronger model" in r["error"].lower()
    finally:
        srv.shutdown()
        srv.server_close()


# --------------------------------------------------------------------------------------------- scoring
def test_two_unanswered_checks_are_not_counted_as_the_same_answer_twice():
    """The validation report's repeatability counts a check that got no answer in either pass as answered the same
    twice (validation.py:458-464), so a model that fails a check both times looks more repeatable; the acceptance
    runs leave such a pair out (evaluation.py:405 `_repeatability`), and score_checks never counts "no answer" as
    right."""
    from enlens_claims import validation as v
    from test_validation_report import _check, _pass

    p1 = _pass(checks=[_check("H1", "supported", "supported"), _check("H2", "contested", None, accepted=False)],
               labels=[])
    p2 = _pass(checks=[_check("H1", "supported", "contested"), _check("H2", "contested", None, accepted=False)],
               labels=[])
    r = v.repeatability(p1, p2, ["A", "B", "C"])
    assert r["checks"]["n"] == 1 and r["checks"]["same_status"] == 0.0, r["checks"]


def test_two_unanswered_label_passages_are_not_counted_as_the_same_codes_twice():
    """Sibling for labels: a passage left unanswered in both passes counted as "the same codes" and as agreeing on
    every code decision; one left unanswered in one pass only still counts, as a disagreement."""
    from enlens_claims import validation as v
    from test_validation_report import _label, _pass

    p1 = _pass(checks=[], labels=[_label("1", ["A"], ["A"]), _label("2", ["B"], None), _label("3", ["C"], None)])
    p2 = _pass(checks=[], labels=[_label("1", ["A"], ["B"]), _label("2", ["B"], None), _label("3", ["C"], ["C"])])
    r = v.repeatability(p1, p2, ["A", "B", "C"])["labels"]
    assert r["n"] == 2 and r["same_codes"] == 0.0 and r["unanswered_twice"] == 1, r


def _semicolons(src: Path, dst: Path) -> None:
    with src.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    with dst.open("w", encoding="utf-8-sig", newline="") as f:
        csv.writer(f, delimiter=";").writerows(rows)


def test_a_gold_set_saved_with_semicolons_is_read_as_with_commas(tmp_path):
    """A gold set whose CSV files a spreadsheet saved with semicolons (as Excel does in most of Europe): its codebook.csv
    is read (frameworks.parse_csv takes either), but hypotheses.csv and labels.csv are read with commas only
    (validation.py:98 `_rows`), so `enlens validate` crashes (AttributeError: a row's extra fields are a list)."""
    from enlens_claims import validation as v

    src = ROOT / "tools" / "validation"
    comma, semi = tmp_path / "comma" / "validation", tmp_path / "semi" / "validation"
    for d in (comma, semi):
        (d / "documents").mkdir(parents=True)
    for name in ("codebook.csv", "hypotheses.csv", "labels.csv"):
        shutil.copy(src / name, comma / name)
        _semicolons(src / name, semi / name)
    want = v.load_gold(comma)
    got = v.load_gold(semi)
    assert got["hypotheses"] == want["hypotheses"] and got["labels"] == want["labels"]


def test_a_model_that_answered_no_label_gets_no_label_score(loaded, tmp_path):
    """`enlens acceptance queue --kind label --model haiku` copies the reference project with its own AI labels
    (evaluation.py:80 clears tasks and results, not labels), and scoring reads every AI label in the copy
    (evaluation.py:245), so before Haiku has answered anything it is scored with the reference's labels: the reference
    is scored against itself, and a model that fails its tasks keeps the reference's score."""
    from enlens_claims import evaluation, profile
    from enlens_claims.llm import BaselineBackend

    profile.keyword_pass(loaded, "sdg")
    profile.run_labels(loaded, "sdg", BaselineBackend(), "baseline")   # the reference's own AI labels
    ref = {}
    for pid, code in loaded.query("SELECT passage_id, code FROM labels WHERE framework='sdg' AND source='model'"):
        ref.setdefault(pid, set()).add(code)
    assert ref
    folder = tmp_path / "acceptance"
    folder.mkdir()
    with (folder / "f2_labels.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["passage_id", "codes"])
        w.writeheader()
        for pid, codes in sorted(ref.items())[:10]:   # a person agreed with the reference on these passages
            w.writerow({"passage_id": pid, "codes": ";".join(sorted(codes))})
    evaluation.prepare(loaded, folder, "label", "haiku")
    row = next(r for r in evaluation.score(loaded, folder)["runs"] if r["kind"] == "label" and r["model"] == "haiku")
    assert row["answered"] == 0
    assert row.get("score") is None, row


def test_a_model_that_answered_no_link_gets_no_link_score(loaded, tmp_path):
    """Sibling for links: the copy keeps the reference's AI links (concept_links, source 'model'), and the link score
    read them for pairs the model under test never answered; with a pass mark it passed and `--apply` would make it
    the default."""
    from enlens_claims import acceptance, evaluation, terms

    terms.ensure(loaded)
    ids = [r[0] for r in loaded.query("SELECT term_id FROM terms ORDER BY term_id LIMIT 12")]
    pairs = []
    for a, b in zip(ids[::2], ids[1::2]):
        a, b = sorted((a, b))
        with loaded.connect() as cx:   # the reference's own AI judgement of the pair
            cx.execute("INSERT INTO concept_links(a, b, relation, source, confidence, model) VALUES (?,?,?,?,?,?)",
                       (a, b, "same", "model", 0.9, "opus"))
        pairs.append({"a": a, "b": b, "same": "yes"})
    folder = tmp_path / "acceptance"
    folder.mkdir()
    acceptance._write(folder / "f3_pairs.csv", pairs)
    (folder / "pass_marks.json").write_text(json.dumps({"link": 0.5}))
    p = evaluation.prepare(loaded, folder, "link", "haiku")
    assert p["tasks"] >= 1
    out = evaluation.score(loaded, folder)
    row = next(r for r in out["runs"] if r["kind"] == "link" and r["model"] == "haiku")
    assert row["answered"] == 0
    assert row.get("score") is None and row["passes"] is not True, row
    assert out["chosen"]["link"]["claude"] is None


# --------------------------------------------------------------------------------------------- the AI log
def test_the_ai_log_names_the_model_that_really_read_the_text(loaded):
    """With the Claude API, the router sends a label task to Haiku, but the AI log names the model the task was made
    with (here Opus): tasks.py:152 `_send` records the sending before the call without the model asked
    (`model_for`), so access.record_sent falls back to the task's stored model (access.py:1533)."""
    from enlens_claims import ailog, profile, routing
    from enlens_claims.llm import AnthropicBackend

    asked = []

    class Block:
        type, text = "text", '{"labels": [], "note": "nothing here"}'

    class Msgs:
        def create(self, **kw):
            asked.append(kw["model"])
            return type("M", (), {"content": [Block()]})()

    be = AnthropicBackend(client=type("C", (), {"messages": Msgs()})())
    be.router = routing.from_settings({"backend": "anthropic", "anthropic_model": "claude-opus-5-5"})
    profile.keyword_pass(loaded, "sdg")
    profile.run_labels(loaded, "sdg", be, "claude-opus-5-5", limit=1)
    assert asked == ["claude-haiku-5-5"]
    rows = ailog.entries(loaded)["rows"]
    assert rows and {r["model"] for r in rows} == {"claude-haiku-5-5"}, [(r["model"], r["kind"]) for r in rows]


# --------------------------------------------------------------------------------------------- agent CLIs
def test_the_codex_report_counts_each_batch_once(monkeypatch, corpus):
    """Two Codex helpers of one group at work at once: each, when it ends, counts every batch taken under the shared
    name "enlens-labeller in Codex" since it started (agentcli.py:1168 `_claims_since`, 1194 `taken_by`), its
    colleague's too, so the report says more batches were answered than were taken."""
    import re

    from enlens_claims import agentcli, taskqueue
    from test_agent_cli import CODEX, _project, _wait_done

    monkeypatch.setenv("ENLENS_CODEX", CODEX)
    monkeypatch.setenv("FAKE_CODEX_DELAY", "1")   # both helpers are at work at the same time
    monkeypatch.setattr(agentcli, "POLL", 0.2)
    monkeypatch.setattr(agentcli, "IDLE_ROUNDS", 3)
    # the runner plans for more than one batch of labels, so it starts two labeller helpers at once (as with a larger
    # project); the helpers themselves take batches of the usual size
    monkeypatch.setattr(taskqueue, "BATCH", {**{k: taskqueue.BATCH.get(k) for k in taskqueue.KINDS}, "label": 2})
    agentcli.forget_status()
    ws = _project(corpus, "codex")
    agentcli.start_run("codex", "Q", parallel=2)
    st = _wait_done(agentcli, "codex")
    assert st["exit_code"] == 0, st
    # (each helper names itself apart since hunt phase 1: "enlens-labeller in Codex #2"; the run's label claims)
    taken = ws.scalar("SELECT COUNT(*) FROM task_claims WHERE taken_by LIKE 'enlens-labeller in Codex%'")
    said = int(re.search(r"Done: (\d+) batch", st["report"]).group(1))
    assert said == taken, (said, taken, st["report"])


def test_a_helper_with_nothing_left_for_its_group_is_not_a_failed_helper(monkeypatch, corpus, tmp_path):
    """BACKENDS-7's re-read: a helper that ends having taken nothing counts as failed only when work of its own group
    (kind, model, helper) waits. `_reap` asked whether any task of the kind waited, so a helper of the stepped-up
    labels (Sonnet) that found its batches taken by its colleague counted as failed while first-step labels waited
    for the Haiku helper; three such end the run with "did not answer the queue"."""
    from enlens_claims import agentcli, routing, taskqueue
    from enlens_claims.store import now
    from test_agent_cli import CODEX, _project

    monkeypatch.setenv("ENLENS_CODEX", CODEX)
    agentcli.forget_status()
    ws = _project(corpus, "codex")
    assert taskqueue._waiting_count(ws, "label") > 0   # first-step labels wait, for the Haiku helper

    class Ended:
        pid, returncode = None, 0

        def poll(self):
            return 0

    monkeypatch.setattr(agentcli, "read_outcome", lambda *a: {"ok": True, "limit": "", "signed_out": False,
                                                                "message": "", "refused": []})
    monkeypatch.setattr(agentcli, "_write_record", lambda run: None)
    monkeypatch.setattr(agentcli, "_say", lambda run, line: None)
    out = tmp_path / "helper.out"
    out.write_text("done", encoding="utf-8")
    settings = {"backend": "codex"}
    run = {"route": "codex", "project": "Q", "batches": 0, "refused": [], "failed_in_row": 0,
           "router": routing.from_settings(settings, route="codex"),
           "procs": [{"proc": Ended(), "group": ("label", "sonnet", "enlens-labeller"), "out": out, "since": now(),
                      "taken_by": "enlens-labeller in Codex #2", "model_id": "gpt-6.2-sol", "waited": 1}]}
    assert agentcli._reap(run, ws) is None
    assert run["failed_in_row"] == 0 and run["batches"] == 0, run


def test_a_model_test_on_a_scratch_copy_keeps_the_provider_and_model_in_the_ai_log(monkeypatch, corpus):
    """Sibling of BACKENDS-3: a model test or label comparison answered by Codex on a scratch copy
    (taskqueue.answer_on_copy) carried the copy's ledger rows into the project without their provider, model and
    person, so the AI log named Anthropic (the default of a row without a provider) for text sent to OpenAI."""
    from enlens_claims import ailog, taskqueue
    from test_agent_cli import CODEX, _project

    monkeypatch.setenv("ENLENS_CODEX", CODEX)
    ws = _project(corpus, "codex")
    t = ws.query("SELECT task_id, kind, payload_json FROM tasks WHERE kind='label' AND COALESCE(queued, 0)=1 LIMIT 1")[0]

    def taken_by_codex(copy, task_id, backend, poll=None):   # Codex's helper takes the batch through the connector
        assert taskqueue.next_tasks(copy, "label", route="codex")["claim"]
        return False, []

    monkeypatch.setattr(taskqueue, "wait_for", taken_by_codex)
    be = type("Codex", (), {"name": "codex", "should_stop": None})()
    taskqueue.answer_on_copy(ws, [(t["task_id"], "label", json.loads(t["payload_json"]), "haiku")], be)
    rows = [r for r in ailog.entries(ws)["rows"] if r["kind"].startswith("label (")]
    assert rows, ailog.entries(ws)["rows"]
    assert {(r["provider"], r["model"]) for r in rows} == {("openai", "gpt-6-luna")}, rows


def test_the_ai_log_names_the_model_codex_read_with(monkeypatch, corpus):
    """Codex reads the labels on OpenAI's gpt-6-luna (its answers record it), but the AI log names Claude's alias
    "haiku" for those sendings: taskqueue.py:746 records the batch without the model, so access.record_sent takes the
    task's stored alias (access.py:1533), a Claude model name for text sent to OpenAI."""
    from enlens_claims import agentcli, ailog
    from test_agent_cli import CODEX, _project, _wait_done

    monkeypatch.setenv("ENLENS_CODEX", CODEX)
    monkeypatch.setattr(agentcli, "POLL", 0.2)
    monkeypatch.setattr(agentcli, "IDLE_ROUNDS", 3)
    agentcli.forget_status()
    ws = _project(corpus, "codex")
    agentcli.start_run("codex", "Q")
    assert _wait_done(agentcli, "codex")["exit_code"] == 0
    used = {json.loads(s)["model_id"] for (s,) in ws.query("SELECT settings_json FROM results WHERE valid=1")}
    assert used == {"gpt-6-luna"}
    rows = ailog.entries(ws)["rows"]
    assert rows and all(r["provider"] == "openai" for r in rows)
    assert {r["model"] for r in rows} == {"gpt-6-luna"}, {r["model"] for r in rows}
