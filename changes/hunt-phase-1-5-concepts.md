### Changes that can alter your results

- **Merging two codes keeps your own decision on a passage.** Where a passage had both codes and you had accepted the
  code you merged away but rejected the other (or the other was a keyword label the AI had read past), the merge left
  the passage with no code at all. Your acceptance now goes with the merge, so the passage keeps the code it merged
  into; the research log entry of the change says how many passages, and restoring the codebook from before the merge
  takes it back. This holds in every project that uses a codebook kept with all projects, when it is opened.
- **"Earlier wording" no longer depends on the clock.** A code reworded in the same second a label task was asked
  was not marked as labelled with its earlier wording, so *Label them again* could not reach the passage. Tasks asked
  from now on remember which wordings they showed.
- **Accepting a proposed relation between two terms accepts that relation only.** When the glossary was made again
  and the sentences now stated another relation for the pair (new documents), your acceptance confirmed the new one,
  which you never saw. It is proposed again instead.
- **Groups whose names differ only in capitals stay two groups.** A save could fold "water" into "Water" and move its
  codes without a word. Only a name whose accents are written another way (the same on screen) is one group.

### Safer

- **A codebook removed while its label tasks wait takes them back.** The AI answered them, each answer was refused
  three times, and the work was wasted. The removal takes back the tasks still waiting, in every project for a
  codebook kept with all projects, and the research log says how many; after bringing the codebook back, a labelling
  run asks them again.
- **Keeping a codebook with all your projects checks its name first.** If another project keeps a removed codebook's
  labels or versions under that name, the move is refused, as making a new codebook of that name already was:
  otherwise it took that work over there.
- **A removal through the API is a removal like the editor's.** `DELETE /api/projects/<project>/frameworks/<name>`
  deleted a codebook with no version kept and no research log entry. It now keeps both, so it can be brought back.

### Fixed

- **The refusal of a removed codebook's name says how to bring it back, and only where that is possible.** It sent
  you to the codebook's *History*, which a removed codebook does not have. It now names the research log entry of the
  removal (*Compare with before*, then *Restore*), and says only *choose another name* when that entry or its project
  is gone. There is no way yet to delete a removed codebook for good (it is on the roadmap).
- **A folder named like a codebook file in a colleague's project no longer stops bringing in their work.**
- **A codebook made from a CSV file keeps the file's order of codes.** A codebook downloaded as CSV and brought back
  in came back sorted by name.
- **A group name you gave stays with its group when one of its concepts is named by another wording** (new documents,
  or two wordings linked as the same). A name of a group of two concepts went to *Names elsewhere* for good.
- **A theme's own page shows the size the themes page shows** when the run names a passage this copy does not have.
- **A codebook drafted from theory marks a definition taken from the AI's *when to use it* as the AI's draft.**
- **A codebook file named with capitals (`Mine.csv`) opens in the editor on Linux too.**
- **An old label task whose code was renamed in the second it was asked is asked again.** Its answer was stored
  under the old name as a removed code's label, which no code could bring back.
