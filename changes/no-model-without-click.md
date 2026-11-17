### Fixed

- **No AI model starts, or even loads, until you press its Start.** ENLENS no longer starts Ollama when it opens,
  and the *Settings → AI* card no longer starts it by itself when it is drawn: *Start Ollama* does, and so does the
  first Start of a local model, which starts Ollama first when it is not running. Search by meaning still starts
  Ollama when it needs it. Results do not change.
- **Stop frees the model's memory at once.** A job's *Stop* lets go of the local models it loaded, and *Stop* on the
  local side lets go of the local model once the item in hand is done, instead of Ollama keeping them in memory for
  15 more minutes. Only models Ollama holds are let go of; nothing is loaded to be unloaded. A job that ends by itself
  keeps its model, so the next one starts quickly.

### For developers

- `ollama_setup.wake(url)` starts Ollama for model work a person asked for; `OllamaBackend.wake()` and
  `OllamaEmbedder.embed` call it once, only on the real connection. `llm.USED` is the job's set of local models
  asked (`note_used`), `llm.let_go(models)` unloads those Ollama holds. `launcher.start_ollama` is gone;
  `--no-start-ollama` is still accepted and does nothing. Tests never start the real Ollama (`conftest.py`).
