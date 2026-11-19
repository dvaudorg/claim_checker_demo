### Changes that can alter your results

- **Reader 7 also reads a text file saved as UTF-16 without its mark.** Such a file (rare: Windows writes the mark)
  was read with an empty character between every two letters, so none of its words could be searched or quoted.
  Reader 7 reads it as UTF-16. Documents already in a project keep their reading until you choose *Read with the new
  reader*.

### Safer

- **One file that cannot be made into passages no longer stops the whole add.** A file that was read but whose
  passages could not be made (a fault in ENLENS) stopped every file after it. It is now listed under the files that
  could not be read, and the others are added.
- **A project zip keeps two files whose names differ only by capital letters or by how an accent is written.** A zip
  made on Linux could hold "Report.pdf" and "report.pdf"; opened on a Mac or a Windows computer, one overwrote the
  other, and one document then showed the other's original. The second is now unpacked as "report (2).pdf", and its
  document points at it.

### Fixed

- **Stop while a file is being read says which file it was.** A file whose reading never ends is waited for until
  you press *Stop* (a long scanned book can rightly take a long time). The list then said only how many documents were
  added. It now says that the add was stopped, which file was being read, how many were not added, and how to add
  them again leaving that file out.
- **The reading of a text file that names no encoding says which one was guessed** (*Read as: Windows-1250, a
  guess*), so a wrong guess can be seen and the file saved as UTF-8.
- **The preview of *Read with the new reader* says whether anything changes.** Reader 7 is offered to every text,
  Word and web document reader 6 read, because whether one reads otherwise is known only by reading it again. The
  preview now says when the new reader reads a document exactly as before, so moving it changes nothing but the
  reader's number.
- **An AI's link between two concepts keeps the documents' own words.** Its two quotes were stored as the AI wrote
  them (another case, straight quotation marks), so the Concepts page could show words the documents do not hold.
