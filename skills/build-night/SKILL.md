---
name: build-night
description: Build or change how a dkitchen kitchen keeps working while the user is away — night orders, what the orchestrator moves forward on its own, and the orchestrator log. Use when the user asks for the kitchen to keep moving overnight or while they are away.
---

# Build the night shift

Install what lets the kitchen keep moving while the user is away: `docs/agents/unattended.md` from [kitchen/night/](../../kitchen/night/), the pointer lines that point at it, the `[log]` and `[night]` keys in `.dkitchen.toml`, and a pinned orchestrator log ticket. The user then runs `/goodnight` before leaving and `/goodmorning` on return.

Follow [Installing](../../kitchen/README.md#installing) for the prerequisites, language, rendering, updating in place, pointer blocks, and approval. When `/setup-dkitchen` brought you here, the prerequisites and the language are already settled: skip them.

## 1. Explore

- **The team**: `docs/agents/roles.md` must exist, since these rules build on the team's. When it is missing, stop and offer [build-team](../build-team/SKILL.md) first.
- **Installed night shift**: `docs/agents/unattended.md`, and `[log]` and `[night]` in `.dkitchen.toml`, read in full when present.
- **The work**: long jobs, several parallel workstreams, and what in this repo must never move without the user.

Done when you know whether the team is installed, whether this run is an update, and the repo's own hard stops.

## 2. Settle each section

One section, one answer. Lead each with your recommendation.

**A. Hard stops.** Show the default list in the template (changing the goal, a dataset, the experimental conditions, or thresholds set in advance; touching a held-out test set; changing model-visible text; top-ups; runaway spend). Ask what to add or remove. For a repo that is not a research project, rewrite it in the repo's own terms.

**B. The log ticket.** Recommend a new pinned ticket titled "Orchestrator log", in the settled language. Keep an existing one if `[log] issue` already names it.

Done when both sections have an answer.

## 3. Draft and confirm

Show the user the full text of `docs/agents/unattended.md` (a diff when updating), the new pointer blocks, the `[log]` and `[night]` keys in `.dkitchen.toml` (the `[night]` headings translated with the vocabulary), and the GitHub change by name: create and pin the log ticket.

Done when the user approves the draft, including the GitHub change.

## 4. Write

Render with `--templates night`, as [Installing](../../kitchen/README.md#installing) says, then fill and translate. Rewrite both pointer blocks from what `render.py` prints. Create the log ticket with `gh issue create` and `gh issue pin`, and write its number into `[log] issue`.

Done when every approved file exists with its approved content and the log ticket is pinned.

## 5. Verify

Run the checks in [Installing](../../kitchen/README.md#installing), then:

- `ding night show` runs and reports no open night orders.
- `ding log --help` prints help, and `gh issue view <log ticket>` shows the pinned ticket.

Done when every check passes, or the user has been told exactly which one fails and why.

## 6. Hand over

Tell the user, briefly: run `/goodnight` in the orchestrator session before leaving, and `/goodmorning` on return; the orchestrator keeps its watch running and logs every automatic action on the log ticket; orders used often can become standing rules on the user's approval.
