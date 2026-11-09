---
name: build-runner
description: Build or change the experiment runner of a dkitchen kitchen in this repo — one resumable entry point for work done item by item (evaluations, batch inference, data processing), with run identity and per-item commits. Use when the user asks to set up a runner, make runs resumable, or stop writing one script per experiment.
---

# Build the runner

Give the repo one runner for its item-by-item work, written by you in the repo's library and shaped to what the repo runs, plus `docs/agents/runner.md` from [kitchen/runner/](../../kitchen/runner/), its pointer line, and tests that keep the runner honest. Without a runner, every experiment carries its own loop with its parameters in code, and every fix to the loop is a copy; with one, an experiment is a spec and a task function.

You write the runner; this skill gives you a reference to read, not code to copy. [reference/runner.py](reference/runner.py) shows the hard parts working in one file; [The core logic](#the-core-logic) says what each must guarantee and where it goes wrong. The repo's runner keeps every guarantee and takes the shape the repo needs.

Follow [Installing](../../kitchen/README.md#installing) for the prerequisites, language, rendering, updating in place, pointer blocks, and approval. When `/setup-dkitchen` brought you here, the prerequisites and the language are already settled: skip them.

## Sources

- **Template**: [kitchen/runner/runner.md](../../kitchen/runner/runner.md).
- **Reference**: [reference/](reference/): `runner.py`, the toy task function `toy_task.py`, and `test_runner.py`, the behaviours every runner must keep.

## 1. Explore

- **Earlier skills**: `docs/agents/code.md` and `[check]` in `.dkitchen.toml` must exist, since the runner goes in the library area and its checks run under `ding check`. When they are missing, stop and offer [build-repo](../build-repo/SKILL.md) first. The runner is Python only, as `build-repo`'s checks are.
- **Installed runner**: `docs/agents/runner.md`, and any runner module already in the library, read in full when present.
- **The work**: every script that runs items in a loop: what it reads, which parameters sit in its code, what it calls (a hosted API, a local server, only CPU), how it writes results, and whether rerunning it resumes. Name the scripts that fit item-by-item work, and the ones that do not, such as training.
- **Services**: where model and service names appear, counted by file, and whether the repo already has one module that reaches them.
- **Formats**: the config format the repo already uses, and its Python version.

Done when you can name, with evidence, the work the runner would carry, the services it calls, and the config format.

## 2. Present the findings

Summarize the scripts that fit and those that do not, how each handles resuming and failures today, and where service names appear. When nothing in the repo runs item by item, say so and recommend not installing the runner.

## 3. Settle each section

One section, one answer, then the next. Lead each with your recommendation.

**A. Scope.** The runner carries new item-by-item runs. Recommend leaving existing scripts as they are: they move to the runner when a ticket changes them.

**B. The spec.** Propose the fields from the work found: items, arms with a task function and its arguments, passes, concurrency, output, inputs, and what the repo's runs add, such as models and generation settings. Recommend the repo's config format; with none, TOML.

**C. Services.** When runs call models or services, propose one registry module in the library that holds every name, address, and client setting, and one way in for task functions, such as `ctx.client(name)`. Recommend the service-name check below. A repo that calls no services has neither.

**D. Place and command.** The runner's module in the library, and its command, such as `python -m <package>.runner <spec>`.

**E. Identity.** Recommend that only concurrency and the output folder stay outside the run identity. Anything else left out is the user's choice, with the reason.

Done when every section has an answer.

## 4. Draft and confirm

Show the user:

- the runner module, the registry when there is one, and their tests;
- the full text of `docs/agents/runner.md` (a diff when updating), and the new pointer blocks;
- the service-name check and its line for `[check] commands`, when there is a registry;
- the line for `code.md`'s reuse sentence naming the runner and the registry.

Done when the user approves the draft.

## 5. Write

Render with `--templates runner`, as [Installing](../../kitchen/README.md#installing) says, then fill and translate. Rewrite both pointer blocks from what `render.py` prints. Write the runner, the registry, the tests, and the check. Adding to `[check] commands` is a guard change: the commit carries `Guard-change: #<ticket> <reason>`.

Done when every approved file exists with its approved content.

## 6. Verify

Run the checks in [Installing](../../kitchen/README.md#installing), then:

- the runner's tests pass, each behaviour of [test_runner.py](reference/test_runner.py) included;
- `ding check --base HEAD` passes;
- a toy spec started with `ding launch --progress <output>/progress.json` shows its progress on `ding board`.

Done when every check passes, or the user has been told exactly which one fails and why.

## 7. Hand over

Tell the user, briefly: new runs are a spec and a task function, started with the runner's command under `ding launch`; rerunning the command resumes; changing the spec or an input needs a new output folder, and changing code does not; `summary.json` says how every run ended; and what the runner leaves out (below) is theirs to add when a run needs it.

## The core logic

Each part below is one guarantee. Keep all six; shape the code to the repo.

### Run identity

The identity is a digest of the spec without its operational fields, plus a content digest of every input: the item source, the spec's input files, and each task module's `INPUTS`. `run.json` holds it, written when the run starts.

- Every later job compares before starting any item. On a mismatch, stop and name what changed; the output stays as it was.
- Code is outside the identity. A job on different code appends a segment to `run.json` (commit, and a digest of the task modules for uncommitted edits), warns in the log, and goes on. Each result records its segment. This is what lets code change in place: no copies to keep old runs reproducible.
- Pitfalls: digest content, never paths or modification times; `INPUTS` misses files a task reads indirectly, such as a template included by another; excluding a field from identity is a decision, not a convenience.

### One writer

One job writes an output folder: an exclusive `flock` on a file in it, held for the whole job. The OS releases it when the process dies, even on SIGKILL, so no stale lock is left. Inside the job, only the main thread writes.

### Commit on completion

Each (item, arm, pass) is one file, written atomically: a temp file in the same folder, flushed and fsynced, then `os.replace`. The main thread keeps at most `concurrency` items in flight and commits each the moment it finishes.

- Pitfalls: committing in spec order lets one slow item hold back every commit, the progress, and the disk counts behind it; appending results to one shared file loses atomicity; a temp file in another folder makes `os.replace` a copy across filesystems.
- Threads fit work that waits on services. For CPU-heavy items, use worker processes that only compute, and keep the commits in the main process.

### Resume

The original command resumes. After the identity check, load every committed result, skip the succeeded ones, and redo the rest. A result that does not parse stops the job: it is evidence of a bug, kept and investigated. A leftover temp file is a write that never committed, and is removed.

### Failures

A failure of one item never stops the run. Retry the same input a bounded number of times (3 in the reference), then commit the item as failed, with its error kind, message, and traceback, and go on. A failed item counts as wrong and stays in the denominator; the next job retries it.

- Only an error that makes every item wrong stops the run: the task function raises `StopRun`, such as on an authentication error.
- Pitfall: when the runner is started as `python -m pkg.runner`, the module runs as `__main__`, and a task function's `from pkg.runner import StopRun` gets a second class that `except StopRun` never catches. Keep `StopRun` in a module that is never `__main__`, or have `__main__` call into the imported module, as the reference does.

### Progress and summary

- `progress.json` uses the `progress-v1` shape `ding board` reads: `schema`, `state`, `stage`, `current` with `done`, `total`, and `failed`, `rate_per_hour`, `eta`, `updated`. It is display only, never read back as state.
- `summary.json` is written however the job ends: SIGINT and SIGTERM become exceptions so the `finally` runs. It holds the state, the stop reason, counts from what is on disk, the failed items, and the segments. Exit 0 when every item succeeded, 1 when the run finished with failures, 2 when it stopped.
- Logs go to stderr and to a log file in the output folder, appended to on every resume.

### The service-name check

With a registry, write a check script in the tools area and list it in `[check] commands`. It reads every model and service name from the registry, takes the lines `git diff <base>` adds under the experiments area (`ding check` passes `--base <commit>`), and fails, with file and line, on a string that equals a registered name. Lines already in the repo are left alone, so the check holds from the first PR with no exception list.

### Left out on purpose

The reference leaves out spec schema checks beyond unknown keys, the service layer, checkpoint and canary rules, a cost ledger, pausing in place to recheck a service or disk, and GPU placement. Add one when a run needs it, keeping the six guarantees.
