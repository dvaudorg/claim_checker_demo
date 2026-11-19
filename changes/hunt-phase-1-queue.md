### Safer

- **`enlens export-tasks` and `enlens run` leave alone the tasks a Claude Code helper is answering.** Both took every
  waiting task of the kind, also those a helper had just taken, so the same task was asked twice and the helper's
  answer was then refused as "already answered". They now leave those tasks to the helper and say how many they left
  (`left_to_the_helper_answering_them`). `run` still answers tasks that were never in the queue, as before. Answers
  already stored are not changed.

### Privacy

- **Naming the groups of the concept map sends no concept found only in documents the AI may not read.** The task
  listed every concept of a group, also a word found only in documents marked *No AI* or *Only a local AI*. It now
  names only the concepts found in documents its reader may read; a group with none is left for you to name.
- **A document made stricter while an AI task waits takes the task away from the AI, also when the task names a
  concept or a title rather than a passage.** *Other wordings* of a concept, *Name the groups* and a framework from
  theory documents (the titles of your own documents) kept such words in tasks waiting for Claude Code after you
  marked their documents *No AI*. Such a task now leaves the queue, as a task of passages always did, including tasks
  made by an earlier version that are still waiting. The answers AI gave before are not changed.

### Fixed

- **The line of a job waiting for Claude Code counts only what Claude Code will be handed.** With the AI mix, the
  tasks the local model answers first were counted as "Waiting for Claude Code"; the line now leaves them out, and
  says "Waiting for your local model" when only those wait. The same holds for the app's own count of what waits, for `/enlens-run` without a project (it no longer lists a project where only the local model's tasks wait),
  and for the "still waiting" a Claude Code helper is told after a batch (an app's helper run no longer ends a helper
  as failed because of tasks it was never meant to take). Results are not changed.
- **`enlens run <kind> --limit N` answers N tasks a helper is not answering.** When a Claude Code helper held the
  first N tasks, the run stopped with nothing done. On the Claude API it now names the model in the AI log and the
  answers' records as the app's own runs do ("claude-haiku-5-5", not "haiku"); the model asked is the same.
- **Changing a document's AI setting stays quick with many waiting *Name the groups* tasks.** The check of their
  concepts read every place each concept occurs, once per task, while the project was locked for writing; it now
  looks at each concept once, and stops at the first document the AI may read.
