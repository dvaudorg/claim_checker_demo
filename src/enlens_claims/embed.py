"""Local embeddings for semantic search: a vector per passage, made by a model on this computer.

Embeddings are optional. When a project has them, a check ranks passages by keyword match (BM25) and by meaning
(cosine similarity of embeddings) and fuses the two rankings, so a source that says "repurposing" is found for a
claim that says "upgrading". Without them, search is keyword-only, as before.

Vectors are made by an embedding model served locally (Ollama: `ollama pull nomic-embed-text`; or any
OpenAI-compatible server such as LM Studio or llama.cpp), stored unit-length as float32 in the project's database
(table `embeddings`, one row per passage and model) and loaded once per corpus state. numpy is used when installed;
without it a pure-Python dot product is used (about half a second per query on 10,000 passages).
"""
from __future__ import annotations

import json
import math
import os
import re
import threading
from array import array
from typing import Callable, Protocol, Sequence

from .llm import BackendError, local_urlopen
from .store import Workspace

# Some embedding models are trained with a prefix that says whether a text is a query or a document.
_PREFIXES = [
    ("nomic-embed", "search_query: ", "search_document: "),
    ("mxbai-embed", "Represent this sentence for searching relevant passages: ", ""),
    ("snowflake-arctic-embed", "Represent this sentence for searching relevant passages: ", ""),
    ("e5", "query: ", "passage: "),
]


def prefixes(model: str) -> tuple[str, str]:
    m = model.lower()
    for key, q, d in _PREFIXES:
        if key in m:
            return q, d
    return "", ""


class Embedder(Protocol):
    model: str

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


def _post(opener, url: str, body: dict, timeout: float, headers: dict | None = None) -> dict:
    from urllib.error import HTTPError, URLError
    from urllib.request import Request

    req = Request(url, data=json.dumps(body).encode(), method="POST",
                  headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with opener(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode() or "{}")
    except HTTPError as e:
        detail = ""
        try:
            detail = json.loads(e.read().decode()).get("error", "")
            if isinstance(detail, dict):
                detail = detail.get("message", "")
        except Exception:
            pass
        raise BackendError(f"The embedding server returned an error ({e.code}): {detail or e.reason}") from e
    except (URLError, ConnectionError, TimeoutError, OSError) as e:
        raise BackendError(f"Could not reach the embedding server at {url}.") from e


class OllamaEmbedder:
    """An embedding model in Ollama, for example nomic-embed-text, mxbai-embed-large or bge-m3 (multilingual)."""

    def __init__(self, model: str, base_url: str | None = None, timeout: float = 300, opener=None):
        url = (base_url or os.environ.get("OLLAMA_HOST") or "http://localhost:11434").rstrip("/")
        if not url.startswith("http"):
            url = "http://" + url
        self.base_url = url[:-3] if url.endswith("/v1") else url
        self.model, self.timeout = model, timeout
        if opener is None:
            opener = local_urlopen   # 0.19.10: 127.0.0.1 before ::1 (Windows)
        self.opener = opener
        self._woken = False

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        if not self._woken and self.opener is local_urlopen:
            # 0.19.15: ENLENS no longer starts Ollama when it opens; search by meaning starts it when it needs it (once
            # it answers: a start that failed is tried again at the next request)
            from .llm import _WAKE_LOCK
            from .ollama_setup import wake

            with _WAKE_LOCK:
                if not self._woken:
                    self._woken = wake(self.base_url)
        if self.opener is local_urlopen:
            from .llm import note_used

            note_used(self.base_url, self.model)   # 0.19.15: its job's Stop lets go of it
        try:
            out = _post(self.opener, f"{self.base_url}/api/embed", {"model": self.model, "input": list(texts),
                                                                    "truncate": True}, self.timeout)
            vecs = out.get("embeddings") or []
        except BackendError as e:
            if "(404)" in str(e) and "model" in str(e).lower():
                raise BackendError(f"Ollama has no embedding model {self.model!r}. Install it with: "
                                   f"ollama pull {self.model}") from e
            raise
        if len(vecs) != len(texts):
            raise BackendError(f"{self.model} returned {len(vecs)} vectors for {len(texts)} texts.")
        return vecs


class OpenAIEmbedder:
    """An embedding model behind an OpenAI-compatible /v1/embeddings endpoint (LM Studio, llama.cpp, vLLM...)."""

    def __init__(self, model: str, base_url: str, api_key: str | None = None, timeout: float = 300, opener=None):
        self.base_url = base_url.rstrip("/")
        if not self.base_url.endswith("/v1"):
            self.base_url += "/v1"
        self.model, self.timeout = model, timeout
        self.api_key = api_key or os.environ.get("ENLENS_LOCAL_KEY", "local")
        if opener is None:
            opener = local_urlopen   # 0.19.10: 127.0.0.1 before ::1 (Windows)
        self.opener = opener

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        out = _post(self.opener, f"{self.base_url}/embeddings", {"model": self.model, "input": list(texts)},
                    self.timeout, {"Authorization": f"Bearer {self.api_key}"})
        data = sorted(out.get("data") or [], key=lambda d: d.get("index", 0))
        if len(data) != len(texts):
            raise BackendError(f"{self.model} returned {len(data)} vectors for {len(texts)} texts.")
        return [d["embedding"] for d in data]


def make_embedder(kind: str, model: str, base_url: str | None = None) -> Embedder:
    if not model:
        raise BackendError("Choose an embedding model first (for example: ollama pull nomic-embed-text).")
    if kind == "ollama":
        return OllamaEmbedder(model, base_url)
    if kind in ("openai", "local"):
        return OpenAIEmbedder(model, base_url or "http://localhost:1234/v1")
    raise BackendError(f"Unknown embedding server kind {kind!r}; use 'ollama' or 'openai'.")


# ---------------------------------------------------------------------------------------------
# vectors on disk and in memory
# ---------------------------------------------------------------------------------------------
def _unit(v: Sequence[float]) -> array:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return array("f", (x / n for x in v))


def _restricted_docs(ws: Workspace, embedder=None) -> set[str]:
    """The documents an embedder on another computer may not read: not `cloud`, or `cloud` without its provider (the
    provider of its address: OpenAI's for an OpenAI address, `other` for a lab's server; providers.py)."""
    from . import access, providers

    url = getattr(embedder, "base_url", "") or "" if embedder is not None else ""
    # (an embedder without an address, a stand-in of a test, keeps the rule of 0.11: only `cloud` documents)
    prov = providers.of_url(url) if url else None
    return {d for d, lv in access.levels(ws, provider=prov).items() if lv != "cloud"}


QUOTE_WORDS = 6   # words in a row that make a code's text a quote of a document (`withheld_codes`)
# a quotation with its source, as a codebook made from theory documents writes each definition ("“…” (Title, p. 3)",
# theorycodes._draft_code, theoryframe._description): how a codebook made before its theory documents were recorded
# is still recognised
QUOTED_WITH_SOURCE = re.compile(r"[“\"][^”\"]{12,}[”\"]\s*\([^)]{1,300}\)")


def _runs(text: str) -> list[int]:
    words = re.findall(r"\w+", (text or "").lower())
    return [hash(tuple(words[i:i + QUOTE_WORDS])) for i in range(len(words) - QUOTE_WORDS + 1)]


def _theory_held(ws: Workspace, meta: dict, prov: str | None, restricted: set[str]) -> bool | None:
    """Whether a codebook's theory documents keep its text from an embedder of provider `prov` (None: no record).
    In the project they are in, by their settings now (`restricted`: those this embedder may not read); elsewhere by
    what they allowed when the codebook was made. An earlier record of this version (`theory_level`) counts too."""
    rec = meta.get("theory")
    if isinstance(rec, dict):
        docs = [d for d in rec.get("docs") or [] if isinstance(d, str)]
        try:
            here = rec.get("project") == ws.project_uid() and docs and all(
                ws.scalar("SELECT 1 FROM documents WHERE doc_id=?", (d,)) for d in docs)
        except Exception:  # noqa: BLE001 - not known: judged by the record
            here = False
        if here:
            return any(d in restricted for d in docs)
        allowed = rec.get("providers") if isinstance(rec.get("providers"), list) else []
        return rec.get("level") != "cloud" or (prov or "") not in allowed
    if meta.get("theory_level") in ("local", "none", "cloud"):
        return meta["theory_level"] != "cloud"
    return None


def _made_from_theory(ws: Workspace, name: str) -> bool:
    """Whether this project's research log says the codebook was made from theory documents (`codebooks.create`)."""
    try:
        for (data,) in ws.query("SELECT data_json FROM research_log WHERE kind='codebook-added' AND subject_id=?",
                                (name,)):
            try:
                got = json.loads(data or "{}")
            except ValueError:
                continue
            if isinstance(got, dict) and got.get("start") == "theory":
                return True
    except Exception:  # noqa: BLE001 - an older project: nothing said
        return False
    return False


_HELD_MEMO: dict[tuple, set[str]] = {}


def withheld_codes(ws: Workspace, fw, embedder, texts: list[tuple[str, str]]) -> set[str]:
    """Of `texts` ([(code, the text to embed)]), the codes whose text an embedding server on another computer is not
    sent (none for one on this computer). Hunt phase 1.5: search by meaning embedded every code's text with whatever
    embedder was set up, and a code's text can hold words of documents that server may not read. Withheld:
    - every code of a codebook made from theory documents that server may not read (`codebooks._theory_record`:
      judged by their settings now where they are, else by what they allowed when it was made); a codebook made from
      theory before that record, when this project's research log says so; and, of one with no such sign, each code
      quoting with its source as theory codebooks do (unknown counts as restricted);
    - a code still holding the AI's draft of its definition (`drafted`), the AI's reading of documents;
    - a code quoting six words in a row of a document of this project that server may not read.
    Such a code is matched by its words only, as a restricted passage is searched by its words (`build`). The
    passages are read one at a time against the codes' own runs of words, and the answer is kept until the codes,
    the documents or their settings change (review: it held every run of every restricted passage, again each pass)."""
    if not texts or not remote(embedder):
        return set()
    from . import providers

    meta = getattr(fw, "meta", None) or {}
    restricted = _restricted_docs(ws, embedder)
    prov = providers.of_url(getattr(embedder, "base_url", "") or "")
    theory = _theory_held(ws, meta, prov, restricted)
    if theory is None and _made_from_theory(ws, getattr(fw, "name", "")):
        theory = True
    if theory:
        return {c for c, _t in texts}
    drafted = meta.get("drafted") if isinstance(meta.get("drafted"), dict) else {}
    ids = meta.get("ids") if isinstance(meta.get("ids"), dict) else {}
    out = {c for c, _t in texts if ids.get(c) in drafted}
    if theory is None:   # no sign either way: a quotation with its source is taken for a theory's
        out |= {c for c, t in texts if QUOTED_WITH_SOURCE.search(t or "")}
    rest = {c: set(_runs(t)) for c, t in texts if c not in out}
    rest = {c: r for c, r in rest.items() if r}
    if not rest or not restricted:
        return out
    docs = sorted(restricted)
    n = sum(int(ws.scalar(f"SELECT COUNT(*) FROM passages WHERE doc_id IN ({','.join('?' * len(part))})", part) or 0)
            for part in (docs[i:i + 500] for i in range(0, len(docs), 500)))
    key = (str(ws.db_path), prov, tuple(docs), n, tuple(sorted((c, tuple(sorted(r))) for c, r in rest.items())))
    if key in _HELD_MEMO:
        return out | _HELD_MEMO[key]
    owner: dict[int, set[str]] = {}
    for c, r in rest.items():
        for h in r:
            owner.setdefault(h, set()).add(c)
    found: set[str] = set()
    for i in range(0, len(docs), 500):
        part = docs[i:i + 500]
        cur = ws._conn().execute(f"SELECT text FROM passages WHERE doc_id IN ({','.join('?' * len(part))})", part)
        for (text,) in cur:
            for h in _runs(text):
                if h in owner:
                    found |= owner[h]
            if len(found) == len(rest):
                break
        cur.close()
        if len(found) == len(rest):
            break
    if len(_HELD_MEMO) > 64:
        _HELD_MEMO.clear()
    _HELD_MEMO[key] = found
    return out | found


def remote(embedder) -> bool:
    """Whether an embedder sends the text to another computer (0.11: then restricted passages are not embedded)."""
    from . import access

    return not access.on_this_computer(getattr(embedder, "base_url", "") or "")


def status(ws: Workspace, model: str | None, embedder=None) -> dict:
    """How many readable passages have a vector from this model. 0.11: with an embedder on another computer, the
    passages of documents marked Only a local AI or No AI are not embedded (meaning search finds them by their words),
    and are not counted as missing."""
    total = int(ws.scalar("SELECT COUNT(*) FROM passages WHERE section='body'") or 0)
    done = int(ws.scalar("SELECT COUNT(*) FROM embeddings e JOIN passages p ON p.passage_id=e.passage_id "
                         "WHERE e.model=? AND p.section='body'", (model or "",)) or 0) if model else 0
    models = [r[0] for r in ws.query("SELECT DISTINCT model FROM embeddings")]
    skipped = 0
    if embedder is not None and remote(embedder):
        docs = _restricted_docs(ws, embedder)
        if docs:
            skipped = int(ws.scalar(f"SELECT COUNT(*) FROM passages WHERE section='body' AND doc_id IN "
                                    f"({','.join('?' * len(docs))}) AND passage_id NOT IN (SELECT passage_id FROM "
                                    f"embeddings WHERE model=?)", [*docs, model or ""]) or 0)
    total -= skipped
    return {"model": model or "", "passages": total, "embedded": done, "complete": bool(model) and total > 0 and done >= total,
            "models": models, **({"restricted_not_embedded": skipped} if skipped else {})}


def build(ws: Workspace, embedder: Embedder, batch: int = 32, progress: Callable[[int, int], None] | None = None,
          should_stop: Callable[[], bool] | None = None) -> dict:
    """Embed every readable passage that has no vector from this model yet. Safe to stop and resume."""
    todo = ws.query("SELECT p.passage_id, p.text, d.title, p.doc_id FROM passages p JOIN documents d ON d.doc_id=p.doc_id "
                    "WHERE p.section='body' AND p.passage_id NOT IN (SELECT passage_id FROM embeddings WHERE model=?) "
                    "ORDER BY p.passage_id", (embedder.model,))
    if remote(embedder):  # 0.11: restricted passages are embedded only by an embedder on this computer
        restricted = _restricted_docs(ws, embedder)
        todo = [r for r in todo if r["doc_id"] not in restricted]
    _q, dprefix = prefixes(embedder.model)
    done = 0
    for i in range(0, len(todo), batch):
        if should_stop and should_stop():
            break
        chunk = todo[i:i + batch]
        vecs = embedder.embed([dprefix + r["text"] for r in chunk])
        with ws.connect() as cx:
            cx.executemany("INSERT OR REPLACE INTO embeddings VALUES (?,?,?)",
                           [(embedder.model, r["passage_id"], _unit(v).tobytes()) for r, v in zip(chunk, vecs)])
        done += len(chunk)
        if progress:
            progress(done, len(todo))
    _VECTORS.pop((str(ws.db_path.resolve()), embedder.model), None)
    return {**status(ws, embedder.model, embedder), "added": done, "remaining": len(todo) - done}


class Vectors:
    """All vectors of one model in a project, as one matrix (numpy) or a list of float arrays."""

    def __init__(self, ids: list[str], blobs: list[bytes]):
        self.ids = ids
        self.pos = {pid: i for i, pid in enumerate(ids)}
        try:
            import numpy as np

            self.np = np
            self.matrix = (np.frombuffer(b"".join(blobs), dtype=np.float32).reshape(len(ids), -1)
                           if ids else np.zeros((0, 0), dtype=np.float32))
            self.rows = None
        except ImportError:  # pure Python fallback
            self.np = None
            self.rows = [array("f", b) for b in blobs]

    def similarities(self, query: Sequence[float]) -> list[float]:
        q = _unit(query)
        if self.np is not None:
            if not self.ids:
                return []
            if self.matrix.shape[1] != len(q):
                raise BackendError("The query vector and the stored vectors have different sizes: the embedding model "
                                   "changed. Rebuild the semantic index.")
            return (self.matrix @ self.np.asarray(q, dtype=self.np.float32)).tolist()
        from operator import mul

        return [sum(map(mul, r, q)) for r in self.rows]


_VECTORS: dict[tuple, tuple[int, Vectors]] = {}
_VLOCK = threading.Lock()


def vectors(ws: Workspace, model: str) -> Vectors | None:
    """The project's vectors for this model (cached until the corpus or the vectors change), or None."""
    key = (str(ws.db_path.resolve()), model)
    stamp = hash((ws.corpus_version(), ws.scalar("SELECT COUNT(*) FROM embeddings WHERE model=?", (model,))))
    with _VLOCK:
        hit = _VECTORS.get(key)
        if hit and hit[0] == stamp:
            return hit[1]
    rows = ws.query("SELECT e.passage_id, e.vec FROM embeddings e JOIN passages p ON p.passage_id=e.passage_id "
                    "WHERE e.model=? AND p.section='body' ORDER BY e.passage_id", (model,))
    if not rows:
        return None
    vs = Vectors([r[0] for r in rows], [r[1] for r in rows])
    with _VLOCK:
        _VECTORS[key] = (stamp, vs)
        while len(_VECTORS) > 4:
            _VECTORS.pop(next(iter(_VECTORS)))
    return vs


def query_vector(embedder: Embedder, text: str) -> list[float]:
    qprefix, _d = prefixes(embedder.model)
    return embedder.embed([qprefix + text])[0]
