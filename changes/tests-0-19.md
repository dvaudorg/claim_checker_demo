### Tests

- **A fixed test for each of four 0.19.0 sync defects, and views run in Node.** The sync defects have a test that pins their fix, and the 0.19 features are tried across two copies of a project. A small helper (`tests/_views.py`) runs the front end's views and `lib.js` in Node, so the 0.19 pages, the AI run panel and the local model's panel are tested as a person sees them. New tests also cover the 0.19 routes, local-only documents and the theory framework draft; stale skips and assertions that could not fail were removed.
