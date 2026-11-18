[Manual](../MANUAL.md) › Codex and Antigravity

# Codex and Antigravity, on your own plan

> **In short**
> - If you have a ChatGPT plan or a Google account, **Codex** or **Antigravity** can answer ENLENS's work, as Claude Code
>   does. No API key.
> - ENLENS installs it, opens its sign-in and adds itself to it. Then press *Start Codex* or *Start Antigravity*
>   wherever work waits.
> - Neither is tried with real accounts yet, and neither is measured with ENLENS: check their answers before you rely
>   on them.

## Which one

*Settings → AI → Subscription* offers three agents. Each answers on a plan you already pay for, and only the passages
inside its tasks go to its company.

| Agent | Whose | Your plan | Where the passages go |
| --- | --- | --- | --- |
| [Claude Code](claude-code.md) | Anthropic | A Claude plan (Pro, Max, Team) | Anthropic |
| **Codex** | OpenAI | A ChatGPT plan (Plus, Pro, Business, Edu or Enterprise) | OpenAI |
| **Antigravity** | Google | A personal Google account, free or paid | Google |

Claude Code stays the recommendation. Antigravity is the one to take without a paid plan: on a free Google account it
offers Gemini 3.8 Flash only, so every task uses it ([Which model does what](models.md#the-recommended-models-of-each-provider)).
A ChatGPT plan pays for Codex, not for an OpenAI API key; for that, see [Another cloud
provider](settings.md#another-cloud-provider-with-an-api-key).

> [!NOTE]
> Codex and Antigravity are built against stand-in programs that follow their documentation. They are **not yet tried
> with real accounts**, and **not yet measured with ENLENS**: its models and settings were measured with Claude only.
> Settings says so beside each.

## Set it up once

Choose the agent in *Settings → AI → Subscription*. The first time, ENLENS asks, naming the company: *Let Codex read the
excerpts, on your ChatGPT plan?* Answer *Use Codex* and press **Set up Codex** (or *Set up Antigravity*). A window of
guided steps opens at the first step not done yet:

1. **Install.** ENLENS shows the maker's own installer line and runs it when you press *Install Codex*. It puts the
   program in your user folder and needs no administrator rights. Prefer to do it yourself? The step links the maker's
   page ([Codex](https://github.com/openai/codex), [Antigravity](https://antigravity.google/docs/getting-started)) and
   moves on by itself once the program is found.
2. **Sign in.** The button opens the sign-in. Codex opens your browser by itself, with no terminal
   ([its sign-in page](https://learn.chatgpt.com/docs/auth)). Antigravity opens one terminal window, as Claude Code
   does: sign in there and in the browser page it opens. The step moves on by itself when it sees you are signed in;
   *I have signed in* checks now. ENLENS never sees your login: the agent keeps it.
3. **Add ENLENS.** The button adds the ENLENS connector (with its three queue tools), the skill and the helpers.
   For Antigravity it also adds one permission line, `mcp(enlens/*)`, and ENLENS's own empty work folder as a trusted
   place. Nothing else in the agent is changed.

The last step says *Start Codex wherever work waits*. A new ENLENS, or a moved one, writes these again by itself. The
card in *Settings → AI* shows the same three ticks (found, signed in, ENLENS added) and the models in use, which you
may change per tier.

## Start it

Press an AI button, and the page says what waits, with **Start Codex** or **Start Antigravity**. It works exactly as
[Start Claude Code](claude-code.md#start-claude-code) does: ENLENS starts the agent's helpers in the background, each on
its own model, checks every quote, and stops them with *Stop* or when you quit. *How much thought* and *Helpers at once*
work the same, and so do the choices at a plan's limit
([Which model does what](models.md#how-much-thought)). Nothing runs until you press it.

You can also type the run yourself in the agent, opened anywhere:

```text
$enlens-run Pilot       # in Codex
/enlens-run Pilot       # in Antigravity
```

## What it may read

Each document says which companies may read it. A task goes only to the agent whose company every document it names
allows: a document that allows OpenAI but not Anthropic reaches Codex and never Claude Code, and the reverse. Every
document allows Anthropic only until you tick OpenAI or Google for it ([Privacy](privacy.md#other-cloud-providers)).
*What was sent* records the company and the agent for each passage.

## How each agent is closed in

Each agent ENLENS starts works in a box, as far as the agent allows, so a passage that tries to give it instructions can
do nothing else.

| Agent | How it is closed in |
| --- | --- |
| **Claude Code** | An empty folder, no file, shell or web tools, only ENLENS's plugin ([Privacy](privacy.md#how-it-is-enforced)). |
| **Codex** | Starts in an empty folder, read-only, with your own Codex settings left out. Its command, web search and image tools are off, and only ENLENS's three queue tools are given to it (take a batch, send the answers, give a batch back). |
| **Antigravity** | Its own tools cannot be switched off from outside. So ENLENS starts it in an empty folder of its own, in its sandbox, without slash commands, and it asks before every tool except ENLENS's. ENLENS adds one permission line, `mcp(enlens/*)`, to Antigravity's settings, after keeping a copy of them, and changes nothing else. **ENLENS refuses to start it while it is set to run every tool without asking** (`always-proceed`): the page says how to change that ([Troubleshooting](troubleshooting.md#codex-and-antigravity)). |

These limits are built against stand-ins that follow the makers' own documentation ([Codex](https://github.com/openai/codex),
[Antigravity](https://antigravity.google/docs/getting-started)), not yet against a real account.

## If something stops

Not found, not signed in, a reached plan limit, or Antigravity refusing to start:
[Troubleshooting](troubleshooting.md#codex-and-antigravity).

---

Next: [A model on your own computer →](local-models.md)
