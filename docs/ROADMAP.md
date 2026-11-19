# ENLENS roadmap

What is still to do in ENLENS, and why. Written 6 November 2026; cut back on 16 November 2026, at ENLENS 0.19.13, to
what is left, and cut again on 17 November 2026, at ENLENS 0.19.16: every item from A0 to N5 is built and tested, and
what each one does is in `CHANGELOG.md` and the manual. Brought up to date on 18 November 2026, at ENLENS 0.20.1, when
D1's last part, I6 and I7's third stage were built: what is left of them is below. The full roadmap, with the plan and
the review notes behind every built item, is in the git history (`git show 02c1841:docs/ROADMAP.md`).

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

**I6. Local model tiers, chosen for you** · Level 2 · built in 0.20.1 (the tier chosen from the computer, suggestions
only, K2's `point` form, the memory guard, the engine named with every local answer: `CHANGELOG.md`)

| Computer | Model | What it does |
| --- | --- | --- |
| Small (about 8 GB, or no graphics card) | `ifm/k2-horizon:0.9b` (1.1 GB) | Explorer only: points at sentences (`point` form), sorts the reading order |
| 16 GB laptop | `qwen3.5:4b` (3.7 GB file) | Suggestions only, better ones |
| Larger (about 24 GB or more) | `qwen3.5:9b` | Suggestions only until measured |
| Documents Claude may read | Claude | Decides, as today |

- **Plain words in the AI run panel.** It still names the local model (*Start qwen3.5:4b*, *Stop qwen3.5:4b*, its
  *Model* row), the one place a model's name shows outside *Settings → Technical*; the sidebar's plain *Start* for the
  local side looks like Claude Code's (0.19.15). Both should say what starts in plain words, the name under Technical.
- **K2's lean**, off for now (`pointing.LEAN`): turned on once its threshold is set (*Left to try*, below).
- **A stronger role than suggestions only**, for the large tier first, only by measurement on the bench below.

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

**I7. Cloud providers other than Claude** · Level 3 · stages 1 to 3 built (API keys and consent per provider in
0.19.19; Codex and Antigravity in 0.20.0; each person's own provider in a shared project, the owner's limit and the AI
log in 0.20.1)
- **Measured defaults.** Each provider's three tiers come from its own advice (`providers.LINEUP`); they should come
  from the validation run (J4.3) and the agreement with Claude (I5). Until then Settings marks a provider *not yet
  measured*.
- **Plan detection** for Codex (its sign-in does not say the plan) and Antigravity (from the models `agy models`
  lists).
- **The AI mix (I1) from every route.** It lends work to the local model only from an agent route (Claude Code, Codex,
  Antigravity), not from the Claude API or another provider's API key (`routing.MIX_ROUTES`).

**Signed share marks** · Level 0 · hunt phase 1.5, 19 November 2026 (the owner's item; feature freeze)
- What is signed today: in a storage space every file a member writes in their own part (`sync/seal.py`: Ed25519, the
  member's own key, checked against the roster the keeper signs). So a copy knows which member wrote each bundle, and
  since this hunt a withdrawal (*Unshare*), or any change of a mark held here, in a member's name counts only from that
  member's own file (`sharing.signers`, `sharing.trusted`); a member's own part always carries their marks. A relayed
  *Share* of an item new to a copy is still taken (so an honestly relayed item is never lost), and while a copy cannot
  read the space's list of members no relayed mark is taken but those.
- What it cannot cover: a zip brought by hand and a plain shared folder carry no signature, and the people who use only
  them have no keys (keys exist per storage space, in its members' keychains). There a mark is data relayed by design:
  a colleague's file can still say, in an item's owner's name, that the owner took it back, or relay a *Share* of an
  item its owner keeps private. Since this hunt a mark dated ahead counts as made when it arrived (`sharing.mark_at`,
  on import and once in every project held), so the owner's own next mark counts over it; but a forged withdrawal
  dated between the owner's latest real mark and now wins whenever it arrives, before or after the owner's own mark,
  until the owner marks the item again. A member who has left the space is no longer among the signers: marks in
  their name are again taken from anyone's file (refusing them would lose their honest marks made while they were a
  member, which after they leave reach a copy only through others). Nor can a mark relayed in a storage space in the
  name of someone who is not a member (a colleague who sends zips only) be checked.
- To build: each person a signing key of their own (not one per space), the public keys known to the team (in the
  project, by the owner's word), and every mark signed by its maker, with its item, state and time, so it can be
  checked whichever file carries it. The same keys would sign the owner's settings (*Open decisions*).

**Delete a removed codebook for good** · Level 0 · hunt phase 1.5, 19 November 2026 (the owner's item; feature freeze)
- What is there today: *Remove the codebook* takes its files away and keeps everything made with it under its name (its
  labels, the passages the AI read for it, its earlier versions), so it can come back from the research log (the entry
  of its removal: *Compare with before*, then *Restore*). While any of these remain, a new codebook cannot take the name
  (`codebooks.held_where`): it would take them over. A codebook kept with all projects keeps its versions with all
  projects, so its name stays taken in every project, also after the project it was removed in is gone. The refusal
  says so and names the way back only where it exists.
- To build: a *Delete for good* beside the removal's entry (and for a name refused this way), which says what goes (the
  labels and the AI's reading in each project that holds them, the versions, the done label tasks), asks *Why?* for the
  research log, and frees the name. Labels are results: a check or a theme set that used them, and a colleague's copy
  that holds them, need a word on what they keep.

## Small things left

Known gaps of built features, gathered on 18 November 2026 from the *Not yet done* lists of the changelog (the
release that left each one in brackets). None of them loses work; each is small.

- **The AI run panel and the sidebar.** With both seats waiting, the panel's head says *Waiting for Claude Code…*
  (0.19.13). A local seat short of memory may say *Waits for you* for a while before *Needs you* while Claude Code
  works on other tasks (0.19.13). The sidebar offers the local model's *Start* only while no
  other job runs, otherwise only on the job's own page; work that asks the local model one request at a time
  (comparing the routes, following references) says "1 task waits" before its *Start*, whatever the number (0.20.1).
- **See what is sent** does not refresh while it is open (0.19.18).
- **Stop on a check's first reading** leaves its local excerpts waiting under the local model's *Start*; a first
  reading whose documents were switched to *Claude may read it* meanwhile is still offered to the local model only
  (0.19.17).
- **The concept map.** The links found in the text are English only; the downloaded picture is always light
  (0.19.16).
- **A team.** A codebook or a link between terms removed on one computer is not removed on the other (0.19.11).

## Left to try with real accounts and a real team

**I7. Cloud providers with real keys, and in a real team**
- Built against stand-ins that follow each provider's documents. To try: OpenAI's reasoning models
  (`max_completion_tokens`, temperature), Mistral's `random_seed` and structured output, Gemini's error shape and
  model ids, Azure's `/openai/v1` address with the `api-key` header, OpenRouter's structured output, the words of a
  refused key and a reached limit, and the macOS keychain. The recommended line-ups against each key's model list.
- Codex: `codex login status`'s words, MCP settings given with `-c` (dotted keys) and approved under
  `approval_policy="never"`, how a reached limit shows in `--json`, the models a ChatGPT plan offers.
- Antigravity: the one sign-in window, whether `agy -p` loads the work folder's `.agents/mcp_config.json` and needs
  the folder trusted, the `mcp(enlens/*)` permission line, `agy models` on a free and a paid account, a reached limit.
  ENLENS's own Antigravity home (`agy-home`): tried on Windows with agy 1.5.11 (the sign-in is kept, a file outside
  the work folder is refused); still to try a whole ENLENS run in it, on macOS (the linked `Library/Keychains`) and
  Linux (one more sign-in?), the name of the *Enable Telemetry* key so ENLENS can write it off itself, and "no AI
  credits spent" on an account that has bought some.
- Stage 3 in a real team: two people on different providers (Claude Code and Codex) on one shared project through a
  real storage space or shared folder; the owner's limit reaching a member and holding their work; the AI log filling
  with both people's rows. Tested only with two copies exchanging files on one computer.

Built and tested against stand-ins that follow each service's documents; not yet tried for real.

**I6. Local model tiers with real models** (each needs a model loaded)
1. Bench `qwen3.5:4b-q4_K_M` (and `9b-q4_K_M`) against the nvfp4 numbers before pinning the GGUF tags
   (`modeladvice.MEDIUM_MODEL`, `LARGE_MODEL`: one line each); and whether the `qwen3.5` tags pull MLX or GGUF on
   Windows.
2. Run `tools/localbench/handhold_lp.py` with opposites written by K2 to set the lean's threshold (0.10 rests on 15
   passages that matter); then turn the lean on (`pointing.LEAN`, with the small `opposite` step).
3. Check once on Ollama 0.40.16 that an unload frees the MLX runner's memory (Activity Monitor; ollama/ollama#17792).
4. Check whether `maxItems`/`maxLength` bound the answer on the MLX path, with one `expand` task.

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
- The concept map's group names (D1): their sync end to end through a real shared folder or storage space (tested
  with the same merge as a project file), and how often two copies find a group differently enough that a colleague's
  name lands under *names kept for groups that are not on this map* rather than on its group.

## Open decisions

- **Signing the owner's settings** (I7 stage 3, 18 November 2026). The owner's settings that travel as rows of
  `team_settings` (the providers the team may use, the codebook settings) and the roles are not signed: a changed app
  could write one in the owner's name, which other copies follow until the owner's copy answers it at its next round.
  When such a row came in someone else's file, the research log names the person it says and the person whose file it
  came in. Decided for now: keep this trust model and say so (the manual's *Roles*); signing the rows with the keys a
  storage space already has is the way to close it, if a team needs it.

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
- **Search by meaning starts its embedding model by itself** (17 November 2026, the owner's choice). The rule that no
  AI model starts without its own *Start* (0.19.15, kept for work that is all the local model's since 0.20.1) is for
  language models; the small embedding model that search by meaning needs loads when a search or an index needs it.
- **An AI's wording of the assessment** (N4). The assessment in words stays made by rules. If an AI's wording is ever
  wanted, it is a separate draft sentence marked as the AI's, never mixed into the sentences made by rules.
- **Ways of working together not chosen** (L, 12 November 2026): an ENLENS server, also one set up at a cloud host with
  one click (it costs money and needs someone to keep it secure for years); OneDrive or Google Drive through their own
  programming interfaces (an app registered with Microsoft or Google, which an institution's administrators often
  refuse); a GitHub repository (accounts, size limits, not meant for storage); free servers such as Oracle's (a card,
  servers taken back when idle, still a server to keep up); one member's computer as the team's host (colleagues
  cannot reach a laptop behind most networks, and the team stops when it sleeps).
