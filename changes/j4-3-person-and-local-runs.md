### New

- **The validation report: right answers from a real project, labelled by a person.** `enlens validate person
  --project <name>` takes what you decided in one of your projects as the right answers: each excerpt an AI judged
  that you then judged yourself, and each code an AI gave that you accepted, changed or rejected (with the codes you
  added where the AI had labelled). The AI's answers in that project are scored against them, by model, and `enlens
  validate report` shows them beside the invented gold set, labelled as a person's judgements on a real project, with
  how many and the date. Only what you decided counts: an answer you left alone, or a comment without a judgement, is
  not a right answer. No AI is used, and the file holds no document text. Cannot change results.
- **A local model's run beside Claude's.** A validation run answered by a model on this computer is now named after
  that model (not "local model server"), and `enlens validate report --latest` sets the newest run of each route side
  by side before giving each in full.

### For developers

- `validation.collect_person`, `write_person`, `latest_person`, `score_person`, `person_markdown`, `latest_runs` and
  `to_markdown_many`; run files carry `"local"`; person files live in `tools/validation/runs/person/`.

### Not yet done

- No local model's run is recorded yet: the commands are in `docs/DEVELOPING.md` (*The validation report*).
