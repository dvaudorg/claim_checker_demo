# ENLENS roadmap

What is still to do in ENLENS, and why. Written 6 November 2026; cut back on 16 November 2026, at ENLENS 0.19.13, to
what is left: every item from A0 to N5 is built and tested, and what each one does is in `CHANGELOG.md` and the
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

**D1. The concept map: the rest** · Level 0, Level 2 or 3 optional
- Links that say a concept *needs*, *shapes* or *clashes with* another. ENLENS's links today are those of D2 and the
  concept card (*is part of*, *leads to*, *is used instead of*, *is related to*); these would come with new link
  types.
- Clusters named (optionally by the AI, marked as its draft) and kept between visits; today they are found again each
  time and have no name.
- The map exported as a picture (SVG or PNG).

**N3. Working documents: the role in the bulk bar** · Level 0
- Set the role (evidence, theory or working document) for many documents at once from the Documents list's bulk bar,
  which today only changes who may read them with AI. Today it is one document at a time, from its panel or its page.

**J4.3. The validation report: the rest** · Level 2
- A recorded run on a local model, scored by `enlens validate` against the gold set in `tools/validation/`, beside the
  run on Claude (13 November 2026).
- Right answers from a real project, labelled by a person, beside the invented gold set.

**I5. Agreement between routes, kept** · Level 0
- The agreement between the local model and Claude is shown once and not kept between visits: keep it, dated, so a
  later sample can be compared with it.

**B5. Retractions without a DOI** · Level 0 (online lookup, not AI)
- Retractions and corrections are found only for works with a DOI. Works without one would need a lookup by title,
  authors and year, following each document's AI setting and `--local-only` as B5 does.

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
