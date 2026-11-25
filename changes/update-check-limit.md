### Fixed

- **The update check no longer runs into GitHub's hourly limit on the Early channel.** With *Early* chosen, ENLENS
  asked GitHub's API for release candidates every two minutes, and GitHub answers only 60 such questions an hour
  from one internet connection: two computers at home were enough to use them up, and Settings said *Could not look
  for updates … rate limit exceeded. Are you online?* Now ENLENS looks for release candidates only when you press
  *Check for updates*; its own look every two minutes finds new stable versions, through GitHub's release page,
  which the limit does not count. A candidate you found stays offered.
- **A failed update check says what went wrong.** GitHub's hourly limit now reads as that, with the time to check
  again; a problem on GitHub's side says so; only a missing connection asks whether you are online.
