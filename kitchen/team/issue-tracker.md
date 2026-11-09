# Tickets: GitHub issues

Every piece of work is a ticket: a GitHub issue in this repo, handled with `gh`. The ticket holds the whole story: the task, decisions, requests, and results. Anything said elsewhere that matters is written back to the ticket.

## Writing tickets

Write tickets with the `write-ticket` skill. A ticket in this repo is laid out like this:

```text
<title: what changes, in a few words>

Design: <the designer line that owns it>; reviewer: <role>
> <the user's approval in their own words, with its date, when the ticket comes from a user decision>
Depends on: <tickets that must finish first, or leave the line out>

## Problem
## Do
## Leave alone
## Exit conditions

<the tier and budget, who executes, and the role that answers questions on the ticket>
```

## Executor comments

When you take over a ticket, post a comment with the line `Codex owner: <CODEX_THREAD_ID>`. `ding` delivers messages for the ticket to the latest owner line, so a new executor taking over posts its own.

Every comment you post carries `Codex session: <CODEX_THREAD_ID>`, with your current session's ID.

A Claude Code session working as the executor signs with `Claude session: <its session name>` instead, and posts no `Codex owner:` line, since `ding` cannot message a Claude Code session. Everything else here applies to it unchanged. When Claude Code and Codex sessions take turns on one ticket, the latest executor comment of either kind is the one that counts.

Open every comment with the status block, and put the details after it inside `<details>`:

```text
Status: in progress | waiting on design | waiting on user | blocked | done
Waiting on: <who, for what; or none>
Key numbers: <the numbers the reader needs, on one line>
Next: <what happens next, and who does it>
```

Each field takes one line. Digests, process IDs, and paths go inside `<details>`. Outside `<details>`, the comment fits on one screen.

When you need the designer, write `waiting on design` and name the designer line exactly in *Waiting on*. That wakes the designer directly; the orchestrator does not relay it. When Status is `waiting on design` or `waiting on user`, the first sentences after the block, before `<details>`, say in plain words what needs deciding, the options, and the one you recommend.

A designer reply marked `Type: proposal, awaiting user` waits for the user: act on it only after the user decides.

### When to comment

Comment only when the state changes: starting work or a run (one line), `waiting on design`, `waiting on user`, `blocked`, `done`. Progress is not a comment: `ding board` and the job's own progress file show it.

`in progress` means something is running. When you end a turn with no `ding run` or tmux job of yours still running, Status cannot be `in progress`: if you wait on no one, keep working; if you wait on someone, write who and set the label.

When you stop, set the label that matches Status and remove the previous one. When you resume, remove it. `gh issue list --label <label>` then shows who is waiting on whom.

| Status | Label | Meaning |
| --- | --- | --- |
| waiting on design | `status:awaiting-design` | Needs a design answer<!-- module:model-text --> or model-visible text<!-- /module:model-text --> from the designer |
| waiting on user | `status:awaiting-user` | Needs the user's approval or manual review |
| blocked | `status:blocked` | Stopped on a failure or another ticket |
| done | `status:done` | Work finished; PR open or merged |

### Reporting results

A comment that reports results against the ticket's gates (a finished stage, a check, the final result) puts this table right after the status block, one row per gate the ticket names, in the ticket's order:

```text
| Gate | Result | Evidence |
| --- | --- | --- |
| <the gate as the ticket words it> | pass / fail / cannot check: <the number> | <link to the report line, file, or comment> |
```

The designer rules on this table alone, so a gate that fails or cannot be checked says why in its Result cell. The full account, such as the method, per-item numbers, and logs, goes into a report file in your PR or the run's output folder, linked from Evidence.

Originals, such as the run's records, summaries, and progress files, stay in the output folder. The comment gives their paths and sha256 inside `<details>`, not their contents; a reader who needs them reads the files.

### PRs

Open PRs as drafts, and mark one ready only when handing it over for review, as in [reviewing.md](reviewing.md).
<!-- module:run-budgets -->

### Run requests

A comment asking to run models adds the run request fields from [run-budgets.md](run-budgets.md) right after the status block.
<!-- /module:run-budgets -->

## Failures you fix yourself

A failure that involves no model call and leaves committed results untouched, such as a wrong path, a missing package, or a tool version: fix it, rerun, and note it in one line of your next comment.

Stop and wait when the fix<!-- module:model-text --> changes model-visible text,<!-- /module:model-text --> needs model calls or cost beyond the ticket, or changes the ticket's scope.
