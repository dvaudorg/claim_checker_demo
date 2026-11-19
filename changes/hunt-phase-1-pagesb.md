### Changes that can alter your results

- **A label you give to selected words lands on those words.** Where the same words stand twice in a passage and you
  selected the second place, *Label it with a code* put the label on the first: the reading view marked the wrong
  words, and the REFI-QDA export (.qdpx) coded them there. The label now goes where you selected. It counts for the
  same passage and code as before, so the counts do not change; labels given this way before keep their place, so
  look again at any you gave to words that occur twice in their passage.

### Fixed

- **A note, a log entry or a title you write is not lost when it cannot be saved.** *Add a note*, editing a note,
  editing your research-log entry or its *Why?*, renaming a document and the comment of *Use as evidence* closed their
  dialog first and saved after: when the save was refused (the note was removed from your other account, the words
  are no longer in the document's text, ENLENS had started again), what you had written was gone and only a message
  was left. The dialog now stays open with your words and says why, and closes once the save worked.
- **New codebook stays open when its name is refused.** A name a removed codebook still holds (its labels and versions
  are kept under it), a CSV file that cannot be read and the like came back as a message after the dialog had gone,
  so the title and choices had to be made again. The dialog now opens again with everything as you left it and the
  reason in it, also after the theory documents step of *From theory documents* (with the question you typed there).
- **What you type in the codebook editor while it saves stays.** Words typed in a code's fields after you pressed
  *Save* vanished when the save answered, and the editor said nothing was unsaved. They now stay, and the bar still
  says there are unsaved changes. When *Try it* or a save ends while you type, the field keeps the focus and the
  cursor instead of the next keys going nowhere.
- **Fields stay as you typed them when a page is drawn again after work in the background.** Your own words under
  *Words the glossary leaves out* while the glossary is made; a short name, title or question in a theory framework
  draft when the AI's reading of the theory ends; a note and choice under a label's *Change how it applies* when the
  codes of a document are read again; a filter of the Bibliography's lists when a check for retractions ends. Each
  was emptied or reset; each now keeps what you typed, and the focus.
- **A file you take off the list while the others are copied is not added.** After *Add*, its × removed it from the
  list, but it was copied and read in all the same, with the AI setting chosen for the others. It is now left out; a
  file already copied shows its × switched off. When two files of one name are added together, both are added and the
  summary says under which name the second one was kept.
- **The offer of the new reader says what it changes for that kind of file.** A text file read by reader 4 was told
  reader 5's news (tables and figures in PDFs, "Other text reads the same") although the offer is there because reader
  7 reads text files otherwise. The notice on Documents and the *Reading* panel now give the news of every reader since
  the document's that changes its kind of file.
- **The Concepts page names the app as the app is called** in its window title and two sentences.
