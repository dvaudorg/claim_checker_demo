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
    taken = ws.scalar("SELECT COUNT(*) FROM task_claims WHERE taken_by='enlens-labeller in Codex'")
    said = int(re.search(r"Done: (\d+) batch", st["report"]).group(1))
    assert said == taken, (said, taken, st["report"])


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
