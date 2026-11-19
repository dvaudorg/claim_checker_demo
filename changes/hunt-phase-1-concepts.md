### Changes that can alter your results

- **A new codebook no longer takes over the work of a removed one of the same name.** Removing a codebook keeps its
  labels, the passages the AI read for it and its earlier versions under its name, so it can be brought back from
  History. A new codebook made under that name counted the old labels, listed them under *Removed codes* (which then
  blocked those code names), skipped every passage the old one's AI had read, and showed the old versions as its own.
  Now the name is refused while that work remains, with a sentence saying to restore the codebook from History or to
  choose another name. This holds for every way of making a codebook (fresh, copy, CSV, .qdc, themes, theory), for
  one kept with all projects (another project's removed codebook of the name counts too, and the message names that
  project; a project's own codebook still in use there does not), and for a colleague's
  codebook that arrives under such a name: it comes in beside yours, marked as their version. A codebook made before
  this version under a removed one's name keeps what it took over. Can change results.
- **An answer to a label task that waited while you changed the codebook is no longer lost.** The AI answers with the
  code names its task showed; after a rename the answer was refused three times and the passage was never labelled,
  after a merge likewise, and after removing a code the whole answer (the passage's other codes too) was refused.
  Now the label lands on the renamed code, on the code it was merged into, or under *Removed codes*. Tasks that failed
  this way before, or while their codebook was removed, are asked again by the next labelling run. A task knows which
  changes it already showed, so a change made in the same second, or a colleague's dated by a clock that is off, never
  sends a label to the wrong code; for a task made before this version, an answer that could mean two codes is
  refused, as before. Can change results.
- **A label task asked before a code was reworded counts as labelled with the earlier wording.** The code shows
  *earlier wording* and *Label them again* reaches those passages too.
- **Label them again reads every passage it names.** After a run that read every passage, a passage the AI labelled
  without a keyword candidate was not read again (its task was taken back all the same), and the AI was not shown the
  reworded code. Now it is read, with the code's new wording among its candidates, and the message after the run says
  how many passages were really read. Can change results.
- **Try it leaves out theory documents, as the keyword pass and the labels do.** Its counts, examples and shares now
  match what the Profile shows; working documents stay in.
- **Making the keyword pass again leaves out a document marked as theory since.** The earlier pass's candidates in it
  stayed and counted on the Profile page. A candidate you accepted or changed stays.
- **A rename made in another project reaches every page of this one at once.** For a codebook kept with all projects,
  Search by code, the concept map, the themes' code grid and the reading view found none of a renamed code's labels
  until the Profile or Codebooks page had been opened. Labels now follow when the project is opened in the app, by the
  connector or by the command line.

### Fixed

- **A codebook file saved with old Mac line endings no longer breaks every page.** Excel for Mac's "CSV (Macintosh)"
  ends lines with a carriage return alone; listing the codebooks then answered "Unexpected problem" on every page.
  Such a file is now read (its download too), and a CSV that still cannot be read is listed with its reason.
- **Moving a codebook keeps its history when the other place holds old versions of that name.** Its versions went
  one folder down and vanished from History. They now join the folder there; versions moved that way before are
  found again, and restore to the right place.
- **Two codes, groups or imported names that differ only in how an accent is written are one name.** "Kő" typed and
  "Kő" from a Mac file (the accent as a separate character) are refused as two codes in the editor and a CSV import,
  named apart in a .qdc import and in a merge with a colleague's codebook, and found by the AI's answers either way.
  Names stay as written. A codebook's name keeps the letter of an accented one ("kőzet" is "kozet"), however written.
  "Maße" and "Masse" stay two names. A codebook saved before with such a pair still saves any other change; only
  adding or renaming a code into such a pair is refused.
- **A colleague's version of a codebook with a long name is listed.** When both changed a codebook whose name had 35
  characters or more, their version came in under a name too long to be listed, so it could not be opened.
