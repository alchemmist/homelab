# LMS: background generation of solutions and tests

Cut on **2 November 2026**. The process is local, there is none on the cluster, and the student's workspace does not read its database.

## What this is

A night pass over the course tasks. For a task with public examples, the model writes two independent solutions, proposes extra stdin and four knowingly-wrong programs, then two separate reviewers accept or reject the solutions and tests. Code: `migration/` in the `lms` repository. The queue: `var/notion-pilot/night-run/certify-queue.py`. The artifacts are SHA-256 files in `var/notion-pilot/agent-artifacts`. The state is Postgres on `localhost:55433`, database `migration`, user `migration`, schema `lms_migration.jobs`.

The model: `qwen3.8-27b` via `https://llm.alchemmist.xyz/v1`. The key lives in `~/.config/lms-migrator/litellm-key`. The key has a limit of **one** parallel request. A second worker or a manual trial call gets 429 `max_parallel_requests` while the queue holds the slot.

## Who the queue takes

There are 777 tasks in staging. The queue goes only over those whose statement has a public example with an input: **423** of them. For the **354** without an example it writes `needs_review` to the log and does not send them to the model. One pass, no loop. The `retry_wait` repeat does not start on its own: the same script must be launched again once the current process has exited. While it is alive, do not start a second instance.

`certified` is not "the model wrote something". Both solutions pass the original examples, the solution reviewer accepts both, the test reviewer accepts the set. Otherwise the task becomes `retry_wait` or `needs_review`, and the queue moves on. The reason in the state is often one line: `model unavailable or invalid after bounded attempts`. It hides three different failures: HTTP (429/5xx), a timeout break at 300s, JSON not matching the schema (`ValidationError`). Two failed attempts per call — and the step is dropped.

## Where it stopped

The queue had been alive since the morning of 2 November and was working through block 1. By the time of the note, about 75–80 tasks of 423 were processed. The database looks roughly like this:

| status | meaning | how many |
| --- | --- | --- |
| certified | all automatic gates passed | 4 |
| needs_review | the gates did not pass, nothing can be fixed automatically | a few |
| retry_wait | the model or the response was not accepted, awaits a new pass | about 70 |
| running | the current task | 1, until the process dies |

Certified: **FizzBuzz**, **Popugai** (Parrot), **Obratnyi popugai** (Reverse parrot), **Biletnaya kassa** (Ticket box). In the morning around 09:00 UTC, 56 tasks died on the very first solver_a call within fractions of a second (`HTTPStatusError`, the code never ran). Further the model answers, but a task is more often not certified: invalid JSON, a reviewer timeout or a reviewer rejection. Such a task takes about 15–20 minutes. The whole tail of 423 at this pace is several days, and most will still not become `certified`.

A saved solution text (a draft, not necessarily certified) was found for about **22** tasks. It is exactly they that ended up in the LMS image's `backend/app/data/reference.json`. The rest are empty in the teacher's workspace until the reference is rebuilt and baked into the image. The `migration` database is not connected to the LMS pod.

## input() and sys.stdin

Students before the lesson "Processing collections. Streaming input sys.stdin" write via `input()`, not via `sys.stdin`. This rule was added into the local `migration/pipeline.py`, but **the file is not committed**: it also contains other unfinished test-generation logic. Already-saved solutions, including FizzBuzz, may read `sys.stdin`. A new pass does not rewrite them until the job is retaken and the solver checkpoint is reset.

## What not to do

- Do not raise the key's parallelism while a single certify-task runs: the slot is one anyway.
- Do not commit `migration/pipeline.py` together with the workspace edits.
- Do not consider `retry_wait` a ready reference for a student. In the panel it is a draft, if the text was saved at all.
