"""Cloud providers other than Claude, stage 1 (providers.py): consent per document and per provider.

- R2/R4: a model server that is not on this computer is a cloud provider: a known one by its address (OpenAI, Mistral…)
  or `other`; it may read only the documents that allow it (Anthropic alone by default);
- R3: a project without the new setting means what it meant: "Claude may read it" is Anthropic only;
- R4: the work split and the queue follow the main route's provider; the ledger names the provider;
- R5: in a shared project only Anthropic may read, whatever this copy allows;
- R6: the cloud chat backend (key, HTTPS, quirks, plain errors, no key anywhere it should not be);
- R7: settings and keys.
"""
from __future__ import annotations

import pytest
from helpers_mixed_corpus import mixed_project

from enlens_claims import access, home, llm, tasks


@pytest.fixture
def mixed(tmp_path, monkeypatch):
    monkeypatch.setenv("ENLENS_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("ENLENS_LOCAL_ONLY", raising=False)
    ws = home.create_project("Mixed")
    ids = mixed_project(ws, tmp_path / "corpus")
    pid = {k: ws.scalar("SELECT passage_id FROM passages WHERE doc_id=? ORDER BY seq LIMIT 1", (v,)) for k, v in ids.items()}
    return ws, ids, pid


def _label(pid):
    return {"framework": "sdg", "passage_id": pid, "title": "t", "page": None, "text": "Green hydrogen and water.",
            "candidates": []}


def _insert(ws, tid, payload, kind="label"):
    with tasks.queueing(False):
        with ws.connect() as cx:
            tasks._insert_task(cx, tid, kind, "m", payload)
    return ws.query("SELECT * FROM tasks WHERE task_id=?", (tid,))[0]


# ---------------------------------------------------------------------------------------------
# R2/R4: the hole (written first, seen failing before the fix)
# ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize("url", ["https://api.openai.com/v1", "https://gpu.example.org/v1", "http://192.168.1.20:1234/v1"])
def test_a_cloud_address_in_the_local_server_field_may_not_read_claude_only_documents(mixed, url):
    ws, ids, pid = mixed
    row = _insert(ws, "label:sdg:" + pid["cloud"], _label(pid["cloud"]))
    assert row["access"] == "cloud"   # "Claude may read it": Anthropic only
    with pytest.raises(access.AccessError):
        access.require(llm.LocalBackend(base_url=url), row, ws)
    access.require(llm.LocalBackend(base_url="http://localhost:1234/v1"), row, ws)  # control: this computer
