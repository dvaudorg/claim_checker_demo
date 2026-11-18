### Privacy

- **An old file put back in the storage space no longer turns a colleague's *Keep … out* switch off.** When a
  colleague turned on *Keep documents marked Only a local AI or No AI out*, an older copy of their description put
  back in the space (by the storage service, a member who can write there, or a drive's version history) made the
  switch read as off again, and the other copies wrote the kept-out documents' words into the space once more. Each
  copy now remembers the latest description it took of each colleague and sets an older one aside; the Team tab lists
  it, as it already did for work that went back. A colleague who really turns the switch off still turns it off.

### Safer

- **Trying your own invite link on your own computer no longer breaks your team.** *Join a team* with a link for a
  storage space that another project on the computer already works in replaced that project's keys, so its new work
  was set aside by every colleague and it could no longer let anyone in. Such a join is now refused, in both *Join a
  team* routes, and ENLENS names the project to open instead. Where two projects on one computer already share a
  space, *Stop using the storage space here* in one of them no longer deletes the keys the other still uses.
- **A colleague's work from before they started afresh, put back in the storage space, is set aside.** Every copy
  used to wait for "work number 1" that had long gone, until that colleague wrote again.

### Fixed

- **One colleague's odd file no longer stops everyone's rounds.** A bundle whose description named its writer as plain
  text, held a number where a list belongs, or said it needs a format of 1e999; a head or roster file with such a
  number; a database without a column ENLENS reads; or a note on what a colleague waits for with a number in place of
  its list: each made every copy's round (and, for some, the Team tab) fail with an error. Now such a bundle is set
  aside as damaged and stops that colleague's work only, and the other files are read as saying nothing. No results
  change.
- **An invite link of an unexpected shape is refused in words.** A link that was whole but lacked the project's id,
  or named its sender in an odd way, answered "Not found: 'uid'" or failed; it now says the link is cut off, damaged
  or made by a newer ENLENS.
- **A drive whose sharing answer has an unexpected shape** gives a message in words instead of an error.
