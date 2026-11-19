### Changes that can alter your results

- **A sentence you mark is kept where you marked it.** On a result page, a sentence (or words) you selected to quote
  that stands more than once in the excerpt was saved at its first place, which could be another sentence of the
  excerpt. The page now sends where you selected it, and the sentence is kept there; the same holds for a sentence
  picked from the list. Can change results only where such words stand twice in one excerpt.

### Safer

- **A model just downloaded on the first page waits for its own Start.** After *Download …* on the first-run page,
  the model was tested at once, which loaded it without a press of yours. The page now says the model is there, and
  *Save and test* loads it when you press it.
- **The warning before quitting, updating or restarting is not dropped when the app cannot say what runs.** When the
  look at the work in progress failed, the dialog said nothing of a check or an add that might be running. It now says
  that this could not be checked, and that quitting or restarting stops whatever runs.
- **A consent dialog in a shared project keeps its line about the team.** When the project could not be looked at,
  the dialog that lets a cloud AI read the excerpts left out that the project is shared with a team. It now says it
  could not check, and what holds if the project is shared.

### Fixed

- **A short text typed in a dialog is kept when its save fails.** Renaming a theme (in the list and on the theme's
  page), the *Why?* of removing one, and the hint of *Read this again…* closed their dialog before saving, so a failed
  save lost what you had typed. The dialog now stays open with your words, and a hint saved as your comment on a first
  try is not saved twice.
- **A failed choice no longer undoes a later one.** The speed of Claude Code, how much thought it gives the tasks, and
  in Settings *Sharing the work* and *At your plan's usage limit*: a first choice whose save failed after a second
  choice was saved put the control back to the value before both. It now goes back only to what was saved last.
- **The queue in Settings shows the newest state.** A look at the work waiting, answered late, could draw over what
  *Hold*, *Go on* or *Do first* had just shown, for a few seconds. And a failed look no longer takes away the start of
  your local model's part of a check.
- **The start of a local model is nudged again after a few seconds**, also on a panel drawn again meanwhile (the queue
  looks every few seconds, and the nudge started over each time).
- **A result page does not show another project's retraction notices**, and says so when the notices of retracted or
  corrected works could not be read (no excerpt was marked, without a word).
- **Failures that left something out now say so, or try again.** The result page asks again for the link to an
  original file after a passing failure, and looks again for a second opinion or another reading still running when
  its first look failed. *How often you agree* in Settings says when it could not be worked out. The sidebar keeps the
  work waiting for Claude Code when one look at it failed.
- **New answers while you write.** While a check waits for Claude Code, a cursor left in a comment box stopped the
  page from looking for new answers. The page now goes on looking, says *New answers came in* with *Show them*, and
  draws them when you ask, without taking your field.
- **A judgement is saved once and said to be saved.** A double click on *Agree*, *Not about this* or a judgement sent
  it twice; and when the page could not be drawn again after a save, only the error showed, though the judgement was
  saved. The toast now says it was saved, and that the page could not show it yet.
- **Stop that was refused is not taken as stopped.** When the app refused to stop an AI run, the panel acted as if it
  had stopped.
- **Numbers are written in English** (1,234), as dates are, whatever the browser's language.
- **One wording for a check not finished.** The window's title said *Not finished* beside a badge saying *Not
  finished yet*; it now uses the badge's words.
- **An address typed with a bare % opens a page.** It left an empty page.
- **Settings › Technical › This installation lists the add-ons that could not be loaded**, one line each, with the
  project when it is one project's.
- **The connector's refusal of a looser AI setting names what the Documents page offers**: adding the documents there
  with another setting, and changing one document's setting in its details (it promised a change for the whole
  project that the page does not offer).
