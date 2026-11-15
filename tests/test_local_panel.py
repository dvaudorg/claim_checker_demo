"""0.19.4: the local model gets its own panel, and labelling no longer stops when it cannot start.

Found in a user test: on the Codes page with Claude Code as the AI, two documents fell back to the project's default
"Only a local AI". "Let the AI label 25 passages" read two passages, then the whole job stopped with "qwen3.5:9b was
not started: it needs about 8.1 GB of memory…", although Claude could have read every other passage, and the page had
said only "Claude, on your plan, reads the passages it labels". Now the local model's passages wait (with Start it
anyway), Claude's are read, and the page knows the local model, its memory and what this computer has free.
"""
from __future__ import annotations

import pytest
from helpers_mixed_corpus import Cloud, mixed_project, use_local_model
from test_local_memory import GB, Watched, _Opener

from enlens_claims import access, home, llm, profile
from enlens_claims.llm import OllamaBackend


@pytest.fixture
def mixed(tmp_path, monkeypatch):
    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("ENLENS_LOCAL_ONLY", raising=False)
    ws = home.create_project("Mixed")
    ids = mixed_project(ws, tmp_path / "corpus")
    profile.ensure_pass1(ws, "sdg")
    return ws, ids


def _labelled(ws, doc_id: str) -> int:
    return int(ws.scalar("SELECT COUNT(*) FROM tasks t JOIN passages p ON t.task_id = 'label:sdg:' || p.passage_id "
                         "WHERE t.kind='label' AND t.status='done' AND p.doc_id=?", (doc_id,)) or 0)


def test_no_room_for_the_local_model_claude_still_labels_the_rest(mixed, monkeypatch):
    ws, ids = mixed
    local = Watched(need=8 * GB, free=2 * GB)
    use_local_model(monkeypatch, local)
    cloud = Cloud()
    res = profile.run_labels(ws, "sdg", cloud, "claude-haiku", all_passages=True)
    # the job ends normally: Claude read its passages, the local model's wait, and the result says why
    assert cloud.sent and _labelled(ws, ids["cloud"]) > 0
    assert local.sent == [] and _labelled(ws, ids["local"]) == 0
    assert res["local_waiting"] > 0 and res["local_read"] == 0 and res["local_model"] == "local-model"
    assert res["memory_short"].startswith("local-model was not started: it needs about 8.0 GB")
    assert res["local_problem"] is None
    # "Start it anyway": only the waiting passages are left, and the local model reads them
    again = profile.run_labels(ws, "sdg", cloud, "claude-haiku", all_passages=True, force=True)
    assert local.sent and _labelled(ws, ids["local"]) > 0
    assert again["local_waiting"] == 0 and again["memory_short"] is None and again["local_read"] > 0


def test_the_local_model_reads_first(mixed, monkeypatch):
    """Its passages come first, so it reads here while Claude Code answers its own from the queue."""
    ws, ids = mixed
    order: list[str] = []
    local = Watched(free=64 * GB)
    cloud = Cloud()
    for who, be in (("local", local), ("cloud", cloud)):
        orig = be.complete
        be.complete = lambda *a, _w=who, _o=orig, **k: (order.append(_w), _o(*a, **k))[1]
    use_local_model(monkeypatch, local)
    res = profile.run_labels(ws, "sdg", cloud, "claude-haiku", all_passages=True)
    assert "local" in order and "cloud" in order
    assert order.index("cloud") > max(i for i, w in enumerate(order) if w == "local")
    assert res["local_waiting"] == 0 and res["local_read"] > 0


def test_a_local_model_that_cannot_be_reached_leaves_its_passages_waiting(mixed, monkeypatch):
    ws, ids = mixed

    class Down(Watched):
        def complete(self, *a, **k):
            raise llm.BackendError("The model server at http://localhost:11434 is not answering.")

    use_local_model(monkeypatch, Down(free=64 * GB))
    cloud = Cloud()
    res = profile.run_labels(ws, "sdg", cloud, "claude-haiku", all_passages=True)
    assert _labelled(ws, ids["cloud"]) > 0 and res["local_waiting"] > 0
    assert res["memory_short"] is None and "not answering" in res["local_problem"]


def test_memory_status_says_need_and_free(monkeypatch):
    opener = _Opener({"qwen3.5:9b": int(7.6e9)})
    be = OllamaBackend("http://localhost:11434", num_ctx=16384, opener=opener, think=False)
    monkeypatch.setattr(llm, "free_memory", lambda: int(6.2 * GB))
    st = be.memory_status("qwen3.5:9b")
    assert st["short"] is True and st["loaded"] is False
    assert st["need"] == int(7.6e9) + 16384 * llm.KV_BYTES_PER_TOKEN and st["free"] == int(6.2 * GB)
    monkeypatch.setattr(llm, "free_memory", lambda: 16 * GB)
    assert be.memory_status("qwen3.5:9b")["short"] is False
    opener.loaded = ["qwen3.5:9b"]
    assert be.memory_status("qwen3.5:9b") == {"loaded": True, "short": False}
    opener.loaded = []
    monkeypatch.setattr(llm, "free_memory", lambda: None)
    assert be.memory_status("qwen3.5:9b") is None   # the computer does not say: nothing is claimed
    assert "/api/chat" not in opener.paths           # nothing was loaded to find out


def test_local_status_for_the_panel(monkeypatch):
    s = {**home.DEFAULTS, "backend": "claude_code"}
    use_local_model(monkeypatch, None)
    assert access.local_status(s)["model"] is None and "Settings" in access.local_status(s)["problem"]
    local = Watched(need=8 * GB, free=2 * GB)
    local.memory_status = lambda m: {"loaded": False, "need": 8 * GB, "free": 2 * GB, "short": True}
    use_local_model(monkeypatch, local)
    st = access.local_status(s)
    assert st["model"] == "local-model" and st["memory"]["short"] is True

    def missing(_s):
        raise llm.BackendError("The local model for restricted documents, qwen3.5:9b, is not installed.")

    monkeypatch.setattr(home, "make_restricted_backend", missing)
    st = access.local_status(s)
    assert st["model"] == "local-model" and "not installed" in st["problem"]
