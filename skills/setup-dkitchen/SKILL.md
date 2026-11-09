---
name: setup-dkitchen
description: Install the dkitchen multi-agent workflow into this repo. Finds out what the repo and the user need, then walks through each build skill in turn. Run once per repo, or again to change the setup.
disable-model-invocation: true
---

# Set up dkitchen

Install the kitchen into the current repo. The user is the head chef: every rule you install exists to keep their attention on direction and decisions. This skill is the entry: it checks the prerequisites, settles the language and what the user needs, then walks through each build skill the user needs. Each build skill settles, drafts, and writes its own part. You verify and hand over at the end.

Shared install steps, such as prerequisites, language, rendering, and pointer blocks, are in [kitchen/README.md](../../kitchen/README.md#installing). Read it first.

## 1. Explore

Read the repo's starting state; assume nothing.

- **Prerequisites**: each one in [Installing](../../kitchen/README.md#installing).
- **Existing setup**: `AGENTS.md`, `CLAUDE.md`, `.claude/CLAUDE.md`, `docs/agents/`, `.dkitchen.toml`, `.claude/settings.json`. Note which build skills already ran: `docs/agents/roles.md` for `build-team`, `docs/agents/unattended.md` for `build-night`.
- **The work**: the README, the main code, how tests run, and whether there are long jobs, several parallel workstreams, or a user who wants progress while away.
- **Language**: the language the user writes to you in, and the language of the repo's docs.

Done when you can name, with evidence, each prerequisite's state, which build skills already ran, and a recommendation for each need in step 3.

## 2. Present the findings

Summarize what is present and what is missing in a short list. Missing prerequisites come first, each with the command that fixes it. When Claude Code or Codex is unavailable, say plainly that this version of dkitchen needs both, and ask whether to stop or to install the rules anyway.

## 3. Settle the language and the needs

One question at a time. Lead each with your recommendation so the user can accept it in a word, and skip any that exploration already settled.

**Language.** Recommend the language the user writes to you in, and settle the vocabulary as [Installing](../../kitchen/README.md#installing) says. The build skills reuse this answer and do not ask again.

**Needs.** Ask each as a yes or no:

| Need | Recommend | Build skill |
| --- | --- | --- |
| A team of agents: stations, tickets, PR review | Always yes; every other part builds on it | [build-team](../build-team/SKILL.md) |
| Work that keeps moving while the user is away | Yes when the repo has long jobs or several parallel workstreams, or the user asks for it | [build-night](../build-night/SKILL.md) |

Done when the language is settled and every need has an answer.

## 4. Build each part

Take the chosen build skills in the table's order: open each one's `SKILL.md` and follow it from its first step to its write step, carrying the settled language into it. A build skill already installed is updated in place. Finish one before starting the next, since each later skill builds on the earlier ones' files.

Done when every chosen build skill has written its approved draft.

## 5. Verify

Run the checks in [Installing](../../kitchen/README.md#installing), then each chosen build skill's own verify step. Fix what fails.

Done when every check passes, or the user has been told exactly which one fails and why.

## 6. Hand over

Give the user each build skill's hand-over points in one short list, in the table's order. End with: the rules are theirs to edit; each build skill can be run again on its own to change its part; and `/setup-dkitchen` runs the whole setup again.
