# While the user is away

When the user is away, the orchestrator's watch wakes it ([watch.md](watch.md)), and it moves forward only what existing approvals already cover. The test for every step: **if anyone would do it the same way, do it. If there are several reasonable ways and the choice affects results, cost, or direction, stop and wait for the user.** Approvals come only from the user's own words; the watch, the orchestrator, and the designer never produce one.

## Night orders

The user invokes `/goodnight` in the orchestrator session before leaving. The orchestrator asks every designer for its line's stops, reads the board and jobs, and traces the window until every running job and every ready ticket either keeps running past the window or reaches a named stop. Each stop is settled as an approval, an observable decision rule, or parked work. The list also gives the fill order for free cards and the hard stops. The user answers once, and the orchestrator posts that reply verbatim with the numbered list using `ding night open --until <time> --body-file <file>` on the log ticket. The headings follow `[night]` in `.dkitchen.toml`; the time includes its timezone.

Night orders count as the user's own words, within the scope of the user's reply and before the orders' end time.

When asked for night orders, each designer replies under its signature within 10 minutes. It gives approvals with their scope and limits, rules of the form "if <observable>, then <action>; otherwise <action>", or "park until morning", plus its hard stops. A line whose designer has not replied by the deadline is parked.

Before writing `waiting on user`, or stopping to wait for the user, **every station runs `ding night show`**. If an open order covers the case, it acts within that order's scope and limits and names the order number in its comment. Otherwise it waits for the user. An order ends when closed or when its end time passes. During the night, every `ding log --item` the orchestrator writes names the order number it relied on, or the standing approval covering the action.

Night orders never lift the hard stops: changing the goal, a dataset, the experimental conditions, or decision thresholds set in advance; touching a held-out test set; changing model-visible text; top-ups; runaway spend. <!-- fill: rewrite this list in the repo's own terms when it is not a research repo. -->

When the user returns, they invoke `/goodmorning` in the orchestrator session. The orchestrator closes the orders with `ding night close`, then reports decisions for the user, stalls and their idle card-hours (marking estimates), orders used or unused, progress, and orders worth making standing. An order becomes a standing rule only on the user's approval, and is then written into these rules.

## What the orchestrator moves forward

- **Next stage**: an executor reports a stage done, and the ticket already approves the next stage with no "wait for the designer" checkpoint: tell it to continue. With a checkpoint, the executor waits on the designer itself.
- **Known situations**: a run stopped in a situation [roles.md](roles.md#known-situations) lists: follow that row.
- **Stuck or quiet executor**: the executor diagnoses first; what it cannot explain goes to the designer, as in [roles.md](roles.md#the-verifier).
- **Results**: the executor names the designer in *Waiting on*, and the designer reads them directly; the orchestrator does not forward them.
- **Unanswered designer**: when the watch reports a request to a designer unanswered for 30 minutes, send that designer one line with the link, as in [watch.md](watch.md).
- **New PR**: review and merge it as in [reviewing.md](reviewing.md), including PRs that change `docs/agents/`, rules, or process files. A PR that changes code a running job depends on waits for the user or the designer.
- **Finished tickets**: label and close them. Tickets whose exit conditions include something for the user, or whose results the designer has yet to interpret, stay open.
- **Host reboot**: reopen tunnels and have executors resume with their original commands.

## The log

After each batch, the orchestrator records it on the pinned "Orchestrator log" ticket:

```bash
ding log --item '#42 told the executor to start stage 2; approved in the ticket budget' --pending '#57 needs a dataset choice'
```

The time is filled in, in UTC. Each automatic action gets one `--item`: the ticket, what was done, and which approval covered it. Each matter waiting for the user gets one `--pending`; leave it out when there are none.
