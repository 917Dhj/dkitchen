# Watches

The orchestrator, every designer, and the verifier each keep a watch running in the background. `ding watch` reads GitHub, `ding board`, and tmux, and calls no model. It exits when something needs its role, and its exit wakes the session. Start yours at session start. After handling a batch, start it again: that is the last step of every round.

| Role | Command |
| --- | --- |
| Orchestrator | `ding watch` |
| Designer | `ding watch --for Designer` |
| Verifier | `ding watch --for Verifier` |

<!-- fill: one more row per extra design line, with its role name. -->

Start the watch as a background task, on its own: no `&`, no output redirection, and nothing chained before it. Otherwise the batch it prints is lost while its state file still moves forward. When woken, handle every item in the batch before starting the watch again. If a batch was lost anyway, `ding waits` lists the waits still unanswered.

A closed session or a host reboot stops a watch silently. When the user is back, each role's background tasks show whether its watch still runs.

## What wakes the orchestrator

The watch exits about 5 minutes after the first of these appears, so related changes arrive as one batch:

- an executor comment whose Status is not `in progress`, or whose *Waiting on* names a role or the user;
- a comment from the user;
- a `status:*` label being added;
- a new PR, a PR ready to merge, or a PR whose review failed;
- an executor gone quiet: `in progress` for over 6 hours without a comment, with no running `ding run` and no live tmux job whose session name contains `issue<ticket number>`;
- a request to a designer or the verifier left unanswered for 30 minutes (`[watch] design_answer_minutes`). The orchestrator then sends that role one line, "#N is waiting on you, see <link>", without restating the request or answering it.

It skips the orchestrator log ticket set in `.dkitchen.toml`. One watch runs per state file; a second exits at once. `ding watch --help` lists the timing options.

## What wakes a designer or the verifier

- An executor comment whose *Waiting on* names the role or one of its aliases, or whose *Next* says "hand to <role>".
- An executor in `waiting on design` that names no designer, which wakes the main designer.
- A comment from the verifier, the orchestrator, or the user that writes `@<role>` or "hand to <role>", or has a line starting with the role's signature.
- For the reviewer of a PR: a non-draft PR whose current HEAD has no review yet ([reviewing.md](reviewing.md)).

A role watch ignores labels, new PRs, and quiet executors. Requests for the verifier go from the executor straight to it; the orchestrator does not forward them.
