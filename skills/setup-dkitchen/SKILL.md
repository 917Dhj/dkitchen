---
name: setup-dkitchen
description: Install the dkitchen multi-agent workflow for this repo, in the repo itself or in a private kitchen repo of its own. Finds out what the repo and the user need, then walks through each build skill in turn. Run once per repo, or again to change the setup.
disable-model-invocation: true
---

# Set up dkitchen

Install the kitchen into the current repo. The user is the head chef: every rule you install exists to keep their attention on direction and decisions. This skill is the entry: it checks the prerequisites, settles the language and what the user needs, then walks through each build skill the user needs. Each build skill settles, drafts, and writes its own part. You verify and hand over at the end.

Shared install steps, such as prerequisites, language, rendering, and pointer blocks, are in [kitchen/README.md](../../kitchen/README.md#installing). Read it first.

## 1. Explore

Read the repo's starting state; assume nothing.

- **Prerequisites**: each one in [Installing](../../kitchen/README.md#installing).
- **Existing setup**: `AGENTS.md`, `CLAUDE.md`, `.claude/CLAUDE.md`, `docs/agents/`, `.dkitchen.toml`, `.claude/settings.json`, and `ding kitchen`, which names a kitchen kept in its own repo and linked on this machine; when there is one, read the existing setup in its checkout. Note which build skills already ran: `docs/agents/roles.md` for `build-team`, `docs/agents/code.md` for `build-repo`, `docs/agents/runner.md` for `build-runner`, `docs/agents/unattended.md` for `build-night`.
- **The work**: the README, the main code, how tests run, whether scripts loop over items, and whether there are long jobs, several parallel workstreams, or a user who wants progress while away.
- **Language**: the language the user writes to you in, and the language of the repo's docs.
- **Who else works here**: the other authors in the last six months (`git shortlog -sne --since=6.months HEAD`), open PRs by other people, an organization owner, branch protection, and a `CODEOWNERS` file. Any of these makes the repo shared.

Done when you can name, with evidence, each prerequisite's state, which build skills already ran, whether the repo is shared, and a recommendation for each need in step 3.

## 2. Present the findings

Summarize what is present and what is missing in a short list. Missing prerequisites come first, each with the command that fixes it. When Claude Code or Codex is unavailable, say plainly that this version of dkitchen needs both, and ask whether to stop or to install the rules anyway.

Then lay out the road ahead, so the user knows what each later question is for: the steps below in one line each, and for each build skill in step 3's table, one line on what it installs and what the user gets from it. Mark the ones exploration found already installed.

## 3. Settle the language and the needs

Ask these as rounds, as [Installing](../../kitchen/README.md#installing) says, and skip any that exploration already settled. The language, where the kitchen lives, and each need do not hang on one another, so they make the first round. The second holds what those answers open: the vocabulary for a language other than English, and the name and checkout path of a kitchen of its own.

**Language.** Recommend the language the user writes to you in, and settle the vocabulary as [Installing](../../kitchen/README.md#installing) says. The build skills reuse this answer and do not ask again.

**Where the kitchen lives.** In this repo, or in a private kitchen repo of its own, with only PRs and code issues reaching this one. Recommend its own repo when the repo is shared, and say that a shared repo always gets one: otherwise the team inherits the kitchen's rules and tickets, and anyone who comments counts as the user. Recommend this repo when the user alone works in it, since one repo is simpler; an own repo is still fine when the user wants the repo free of kitchen files. For its own repo, also settle its name (default `<owner>/<repo>-kitchen`, private), where its checkout goes on this machine (default beside this checkout), and whether this repo is shared.

**Needs.** One question per need, each a yes or no, saying what the build skill would install and what the kitchen lacks without it:

| Need | Recommend | Build skill |
| --- | --- | --- |
| A team of agents: roles, tickets, PR review | Always yes; every other part builds on it | [build-team](../build-team/SKILL.md) |
| Code the agents write and change | Yes for any repo with code the agents change; the reference checks need Python | [build-repo](../build-repo/SKILL.md) |
| Work done item by item: evaluations, batch inference, data processing | Yes when the repo has scripts that loop over items; needs `build-repo` | [build-runner](../build-runner/SKILL.md) |
| Work that keeps moving while the user is away | Yes when the repo has long jobs or several parallel workstreams, or the user asks for it | [build-night](../build-night/SKILL.md) |

Done when the language is settled, where the kitchen lives is settled, and every need has an answer.

## 4. Make the kitchen repo

Only for a kitchen of its own; skip this step for a kitchen in this repo. Show the user these changes and make them once approved, each GitHub change by name:

1. `gh repo create <owner>/<name> --private`, cloned to the settled path.
2. In it, a `.dkitchen.toml` with `repo = "<owner>/<name>"`, `code = "<this repo>"`, and `shared = true` when this repo is shared, and a `.gitignore` listing `CLAUDE.local.md` and `.claude/settings.local.json`. Commit and push them.
3. `ding kitchen link <this checkout>`, run in the kitchen's checkout; `ding kitchen` there then names both.
4. The files that tie this machine's sessions to the code repo, kept out of Git: `CLAUDE.local.md` with one line, "The code repo, `<this repo>`, is checked out at `<this checkout>`.", and `.claude/settings.local.json` with `{"permissions": {"additionalDirectories": ["<this checkout>"]}}`, so the standing roles read and search the code repo without asking.

From here on, every path a build skill names is in the kitchen's checkout, and its `ding` and `gh` commands run there, as [Installing](../../kitchen/README.md#installing) says. Another machine that runs sessions repeats steps 3 and 4 with its own paths.

Done when `ding kitchen`, run in the kitchen's checkout, shows the kitchen repo, the code repo, and this checkout.

## 5. Build each part

Take the chosen build skills in the table's order: open each one's `SKILL.md` and follow it from its first step to its write step, carrying the settled language and the question numbering into it. Start each with one line on where the setup stands: which part this is, what it installs, and which parts come after. A build skill already installed is updated in place. Finish one before starting the next, since each later skill builds on the earlier ones' files.

Done when every chosen build skill has written its approved draft.

## 6. Verify

Run the checks in [Installing](../../kitchen/README.md#installing), then each chosen build skill's own verify step. Fix what fails.

Done when every check passes, or the user has been told exactly which one fails and why.

## 7. Hand over

Give the user each build skill's hand-over points in one short list, in the table's order. For a kitchen of its own, add where sessions run: the orchestrator, designers, and verifier in the kitchen's checkout; executors in worktrees of this repo, which `ding new` gives the kitchen's location. End with: the rules are theirs to edit, and `/improve-kitchen`, run every couple of weeks, turns what keeps going wrong into checks, tools, or rules; each build skill can be run again on its own to change its part; and `/setup-dkitchen` runs the whole setup again.
