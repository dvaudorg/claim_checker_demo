### Changes that can alter your results

- **Reader 7 reads text files, Word files and web pages more faithfully: an interview's repeated question, short
  paragraphs one per line, Word text boxes and Latin-2 text.** In an interview typed with a blank line between turns
  (or a Word file or web page whose paragraphs are one line each), a question the interviewer asked now and then was
  taken for a running head and left out of searches, codes, themes and checks; it now stays. A text file of short
  paragraphs, one per line (survey answers or notes saved by Word as plain text), was read as one paragraph, so every
  quote in it was cited as paragraph 1; each line is now a paragraph. A Word file's text box was read twice (Word
  keeps the box and an older copy of it), glued to the last word of the paragraph that holds it, so searches and code
  counts found its words twice; it is now read once, as a paragraph of its own after that paragraph. A Polish, Czech or
  Slovak text file or web page saved as ISO-8859-2 lost its ą, ś, ź, š and ž (they came out as ±, ¶, Ľ and the like)
  without a word; it now keeps them. PDFs read as before. **Can change results, for documents you move to it**: a
  Word file with a text box counts that box's words once instead of twice, a transcript keeps its repeated question,
  and quotes in a file of short lines are cited by their own paragraph. New documents are read by reader 7; text
  files, Word files and web pages already in a project keep their reading until you choose *Read with the new reader*
  (the preview says whether anything changes). In text copied out of a PDF whose every paragraph is one line, a
  running head that never falls in the middle of a sentence can now stay in the text.

### Safer

- **Adding a newer zip from the same place no longer replaces the originals of documents added from the older one.**
  Both zips were unpacked into one folder, so the first document's original file was overwritten: it was then
  reported as changed since it was added, and could no longer be opened beside its text or read with the new reader.
  Each zip now unpacks into a folder of its own, and the same zip added again does not make a second copy. Documents
  added before keep the files they recorded.
- **Two files in one zip whose names differ only by capital letters or by how an accent is written** ("Report.pdf"
  and "report.pdf") were written to one file on a Mac or a Windows computer, and one document was lost. The second is
  now unpacked as "report (2).pdf".

### Fixed

- **A zip that cannot be opened is named.** A zip cut off in a download was passed over without a word, so the add
  reported nothing and added nothing. It is now listed under the files that could not be read ("damaged zip: copy or
  download it again"), and the other files are added.
- **Documents of a kind ENLENS does not read are named.** An older Word file (.doc), rich text (.rtf, .odt) or slides
  (.pptx) in a folder or zip were passed over without a word. They are now listed under the files that could not be
  read, with what to do (save them as .docx or PDF). Pictures, spreadsheets and other files that are not documents
  are still passed over.
- **A quote is found in text with an invisible right-to-left or left-to-right mark.** Arabic, Hebrew and mixed text
  from Word, web pages and PDFs keeps these marks; a quote of the words as you see them was not found and was
  rejected. Quotes that were found before are found as before.
- **The original of a text file marks a quote of a document read by reader 6** also when the file is saved as
  ISO-8859-2.
