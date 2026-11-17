# ENLENS roadmap

What is still to do in ENLENS, and why. Written 6 November 2026; cut back on 16 November 2026, at ENLENS 0.19.13, to
what is left, and cut again on 17 November 2026, at ENLENS 0.19.16: every item from A0 to N5 is built and tested, and what each one does is in `CHANGELOG.md` and the
manual. The full roadmap, with the plan and the review notes behind every built item, is in the git history
(`git show 02c1841:docs/ROADMAP.md`).

The items keep their letters (A to N), so a changelog entry that names one (A1, H3, K1) can still be traced. A letter
missing from a section is not planned for ENLENS.

## The rule: as little AI as possible

ENLENS should be a tool that a few prompts to a chatbot cannot replace: it keeps your corpus, your decisions
and your history; it gives the same answer twice; every step can be traced; and most of it runs on your computer
without any model. So every feature is built at the **lowest level that does the job well**:

| Level | What it means | Examples |
| --- | --- | --- |
| **0 · No AI** | Plain code: rules, statistics, text matching, the document's layout | search, C-value terms, k-means themes, kappa |
| **1 · Local program** | A program or library on this computer, still no language model | Tesseract, GROBID, an embedding model for search by meaning |
| **2 · Local model** | A language model on this computer (Ollama, LM Studio…) | labelling passages when no Claude may read them |
| **3 · Claude** | Only where 0–2 cannot do it well enough, and only for documents Claude may read | a hard check, a second opinion |

Each item below says its level. Where an item has an AI part, the AI part is optional, the rest works without it, and
what the AI says is still quoted, checked against the text and yours to overrule. Online lookups that are not AI
(OpenAlex, Crossref) still send words off the computer: they follow each document's AI setting and are switched off
by `--local-only`.


## Left to build

**D1. The concept map: group names with a team** · Level 0
- The map's group names (0.19.16) stay on the computer they were given on. Shared with a team, a name would need a
  rule for two people naming the same group, and for a group that is not the same on two copies (the groups are found
  from each copy's own counts).
- The AI's link tasks (`link`) do not yet propose the three kinds added in 0.19.16 (*needs*, *shapes*, *clashes
  with*); only the text patterns and a person do.

**I6. Local model tiers, chosen for you** · planned (bench of 16 November 2026, below) · Level 2
- A researcher should never have to pick a model. ENLENS already reads the computer's memory and disk
  (`modeladvice.py`); it picks the tier itself, downloads its model, and sets the context length, reasoning (off for
  local checks: on, one check took 114 s instead of 9 s) and seed without asking. Model names show only under
  *Settings → Technical*.
- The tiers, replacing today's ladder (qwen3:1.7b, 4b, 8b, 14b):

  | Computer | Model | What it does |
  | --- | --- | --- |
  | Small (about 8 GB, or no graphics card) | `ifm/k2-horizon:0.9b` (2 GB) | Explorer only: points at passages, sorts the reading order, marks a possible lean, suggests search words |
  | 16 GB laptop | `qwen3.5:4b` (4 GB file) | Suggestions only, better ones |
  | Larger (about 24 GB or more) | `qwen3.5:9b` | Suggestions only until measured; if it proves well calibrated, its surest answers may be trusted |
  | Documents Claude may read | Claude | Decides, as today |

- **Suggestions only** means a local model never sets a status. Every claim it reads goes to the manual review card
  (*Judge it myself*, *Awaiting manual review*, since 0.19.8), filled in with the model's passages, highlights and
  lean; the researcher decides each passage. No local confidence number is shown. Open design point: whether the
  suggestion shows before or after the researcher's own grade (a pre-filled card invites a quick *Agree*: the bench
  saw a reviewer agree with 25 of 30 judgements, invented quotes included, when it was shown them).
- The validation gold set (17 November 2026, `tools/validation/runs/`) agrees: Qwen 3.5 4B got 47% of verdicts right
  (26 of 30 checks finished), K2 Horizon 0.9B finished none (its whole-sentence quotes for every passage ran past the
  answer's length limit): a K2 tier needs its own, shorter answer form, or the length limit raised for it.
- To handle when built: with Ollama's MLX runner, `qwen3.5:4b` grew from 5.2 GB to 12.7 GB of memory over a long run
  (the advice reckons size plus context, so it needs more margin or a restart between batches); and temperature 0
  with a fixed seed did not repeat answers word for word (62%), which the results' version note should say.

*The bench (16 November 2026).* 45 checks from the green hydrogen pilot (30 real VCA claims, 15 planted controls: a
hidden supporting sentence, a claim turned into its opposite, unrelated passages), each answered 7 times by each
local model through the app's own prompt and Ollama; Opus 5.5 and Sonnet 5.5 answered blind twice each. The first
gold (two blind Opus passes) proved strict on *partly supports*; the reference became Fable 5.2's review of the 30
real claims (three rounds; it kept its reading after seeing another reviewer's). Gemini, grading from scratch, is
kept for comparison only.

| Against the Fable reference (30 claims) | Qwen 3.5 4B | K2 Horizon 0.9B | Opus 5.5 | Sonnet 5.5 |
| --- | --- | --- | --- | --- |
| Right status | 57% | 27% | 52% | 35% |
| Grades it counts (0.6 or more) that are right | 68% | 49% | 100% | 100% |
| Its stated confidence on those | 79% | 73% | 66% | 69% |
| Passages that matter, found | 58% | 73% | 29% | 13% |
| Seconds per check (M4, 16 GB) | 7 | 7 | 4 (cloud) | 2 (cloud) |
| Memory | 5.2 → 12.7 GB | 2 GB | – | – |
| Same status in 5 runs | 60% | 56% | – | – |

- Claude is precise but leaves out most partial evidence; Qwen finds more and is overconfident; K2 guesses (it called
  38 of 45 claims supported, and 60% of its answers quoted words not in the passage).
- Trusting only a model's surest answers does not help a small model: K2's grades at 0.8 or more were right 67% of
  the time, and Qwen's at 0.9 or more 73% (8% of passages). Their mistakes are confident ones.
- Hand-holding K2: small structured questions made it faster, not better (it never answers "neither"). Reading its
  probability of "yes" to *does the passage say the claim / its opposite* told support from contradiction for 13 of
  15 passages that matter, with a naturally worded opposite ("It is not true that …" broke it), but not which
  passages matter (0.58, where 0.5 is chance): a lean to show, not a decision.
- Where the line falls between *nothing*, *partly* and *supports* moved the ranking more than the choice of model.
  The rules as written are the reference; widening *supports* would need the prompts and the bench redone.

*Benching another model later* (details in `tools/localbench/README.md`): pull it with Ollama, run
`python tools/localbench/localbench.py run --model <name>` (one model at a time; `monitor.py` follows heat, memory and
progress), then `review.py score` scores it against the Fable reference and `viz.py` adds it to the visualiser. A new
reviewer grades `review.py packet`'s claims from scratch and counts only after passing its hidden controls and quote
check. A model earns a stronger role than *suggestions only* only by measurement on this bench.

## Left to try with real accounts and a real team

Built and tested against stand-ins that follow each service's documents; not yet tried for real.

**L5 and L7. A shared folder**
- Between two computers through a real OneDrive, Dropbox and network drive, and on a real Windows PC. The first try on
  OneDrive (12 November 2026) found the set-up clunky, which L6 and L7 answered; the answer itself is untried.

**L6a. Backblaze B2**
- Its v4 calls, and a key limited to a name prefix (one writer per part).
- Whether a key ENLENS makes may make keys (if not, the master key is kept, with a warning).
- What *Caps & Alerts* shows for an account without a card, what such an account does at the free tier's limit, and
  Backblaze's exact words for caps and maintenance.
- A script that plays the whole set-up on a test account (sign in, own key, bucket, test file, a colleague's keys, a
  refused write outside their part, clean-up) was written on 12 November 2026 and has not been run.

**L6b. Cloudflare R2**
- The token link with the right to make tokens (`api_tokens`).
- Whether the page after *Create Token* also shows the S3 access values, which would save ENLENS a step.

**WebDAV (SURFdrive, SURF Research Drive, Nextcloud)**
- Whether SURFdrive's `nonshib-webdav` address offers the OCS Share API, where shares land, and the exact refusals.

**J4.3. Right answers from a real project**
- `enlens validate person` (0.19.16) scores the AI against a person's own grades and code decisions in a real
  project. It waits for a project where a person has judged enough of the AI's answers; the report then shows it beside
  the invented gold set.

**A team on real computers**
- Owner, Co-owner and Member roles, invites, a hand-over and removing a colleague, used by a real team over days.

## Parked or decided against

Kept so the same question is not opened again without a reason.

- **GROBID or Docling** (A1, A3) · Level 1. Optional local programs for hard cases (sections, references, tables the
  rules cannot rebuild, tables in scanned pages). Not built: GROBID needs Java and Docling downloads several GB of
  models, heavy on a 16 GB Mac. Parked until the rule-based reader's figures (`enlens measure`) show a need.
- **Stored image files and reading the text inside pictures** (A6). Both heavy for a large corpus: a figure is drawn
  from the original PDF when shown, and never stored or read by OCR.
- **A citation file or DOI** (J4.1). Dropped on 8 November 2026, by choice: the README's *How to cite ENLENS* gives the
  repository's address and the version used.
- **A published manual site** (J2.4, MkDocs on GitHub Pages). Not made: the manual stays in the repository.
- **An AI's wording of the assessment** (N4). The assessment in words stays made by rules. If an AI's wording is ever
  wanted, it is a separate draft sentence marked as the AI's, never mixed into the sentences made by rules.
- **Ways of working together not chosen** (L, 12 November 2026): an ENLENS server, also one set up at a cloud host with
  one click (it costs money and needs someone to keep it secure for years); OneDrive or Google Drive through their own
  programming interfaces (an app registered with Microsoft or Google, which an institution's administrators often
  refuse); a GitHub repository (accounts, size limits, not meant for storage); free servers such as Oracle's (a card,
  servers taken back when idle, still a server to keep up); one member's computer as the team's host (colleagues
  cannot reach a laptop behind most networks, and the team stops when it sleeps).
