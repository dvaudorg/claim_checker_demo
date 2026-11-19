### Fixed

- **Settings › This installation says truthfully what goes online.** The Network line still said "This computer only ·
  nothing is loaded from the internet", which stopped being true long ago. It now says who can open the app (only
  this computer, unless it was started with `--host`) and lists what ENLENS reaches over the internet: GitHub for
  updates, the cloud AI you choose (left out under local-only), your team storage space (Backblaze B2, Cloudflare R2,
  WebDAV), Crossref when you look up retractions, and ollama.com or Anthropic's installer when you press their
  buttons. Does not change results.
