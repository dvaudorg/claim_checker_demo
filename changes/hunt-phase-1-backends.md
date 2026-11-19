### Changes that can alter your results

- **A model you chose for checks steps up only to a stronger one.** With Fable chosen for checks (or Opus, with *Let
  the auditor use Fable* off), *Ask a stronger model* and an unsure answer read the check again on Opus, a weaker
  model or the same one, and recorded that reading as the stronger model's. Fable now has no stronger model, nor has
  Opus while the Fable switch is off: the result page says so, and nothing is read again. If you chose Fable or Opus
  for checks, a result marked as read again by a stronger model may rest on Opus's reading.
- **An acceptance run scores only what the model under test answered.** `enlens acceptance score` scored the
  reference project's own AI labels, links, theme names and chains wherever the model had not answered (not run yet,
  failed or rejected), so a model that answered nothing got the reference's score and could pass, and `--apply` could
  make it a default. A run with nothing answered now has no score and never passes. Score your acceptance runs
  again if you used them to choose models.
- **The validation report's repeatability leaves out a check or a passage unanswered in both passes**, as the
  acceptance runs do, and says how many it left out. Two failures counted as the same answer twice, so a model that
  failed looked more repeatable.

### Privacy

- **Text for a model on your computer never goes through a proxy.** With a web proxy set on the computer (the
  `http_proxy` setting, or a proxy in the system's network settings without an exception for 127.0.0.1), every
  request to Ollama, LM Studio or another model or embedding server on this computer, with the passages of documents
  marked *Only a local AI*, went to the proxy, another computer. ENLENS now opens this computer's addresses without a
  proxy, as it already did for Zotero and the team's storage space.
- **Only `localhost` and loopback addresses count as this computer.** A local server typed as
  `localhost.localdomain` or as a name ending in `.localhost` counted as this computer, though some computers ask the
  network's name server for such names. It is now a server on another computer, as the privacy page says: it reads
  only documents you allow it. If you used such an address, type `localhost` or `127.0.0.1` instead.
- **The AI log names the model that really read the text.** With the Claude API it named the model the task was made
  for (Opus) where Haiku read it, or the first model after a step up; with Codex and Antigravity it named Claude's
  "haiku" for text sent to OpenAI or Google. It now names the model asked: on Codex and Antigravity the model on the
  command line ENLENS started the helper with (the same in each answer's record), Claude's own name for Claude Code.
  Where you start the helpers yourself in Codex or Antigravity, the model is that program's own choice, and the log
  says it is not known rather than guess. A model test or label comparison answered by Codex or Antigravity
  is no longer recorded as sent to Anthropic.

### Fixed

- ***How these results were made* no longer says Temperature 0** for answers from the Claude API, Codex, Antigravity
  or a cloud model that refused a temperature: none was sent, and none is shown. Answers that recorded one keep it.
- **A cloud provider or local server that keeps streaming is given up at its time limit** (10 minutes for a cloud
  provider), as an answer that goes silent already was.
- **Codex and Antigravity runs count each helper's batches once.** With two helpers of one kind at work, the report
  counted each other's batches too ("Done: 2 batches" for one), and a helper that found its colleague had taken the
  work, or one that took nothing, was counted wrongly as working or as failed. "Batches answered" now counts only
  batches with an answer stored, not those given back or left to lapse.
- **Settings › Repeatable results says what is really sent**: a seed and temperature 0 to a model on your computer
  (and to a cloud provider's API that takes them), neither to Claude Code, the Claude API, Codex or Antigravity.
- **A gold set saved with semicolons** (as Excel does in most of Europe) is read as one saved with commas; a row
  with more cells than its header is said plainly instead of stopping `enlens validate` with an error.
