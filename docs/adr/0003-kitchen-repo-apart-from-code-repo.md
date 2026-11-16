# A kitchen can live in its own repo, apart from the code repo

A kitchen used to live in the repo its work lands in: house rules, `.dkitchen.toml`, tickets, labels, and scripts. That cannot work in a code repo other people share, since the team would inherit our rules, tickets, and agent traffic, and anyone who comments would count as the user. A kitchen may therefore live in its own private kitchen repo, paired one to one with a code repo. A single-repo kitchen is the case where the two are the same repo, so `ding` keeps one code path. Standing roles run in the kitchen repo and reach the code repo through a pointer kept on each machine, as in the home repo pattern. Executors run in worktrees of the code repo, and `ding new` hands them a pointer to the kitchen. Into the code repo the kitchen writes only what the user would write: PRs and code issues, shaped by the contribution guide, and `ding` refuses text that carries kitchen internals. A shared code repo always gets a separate kitchen repo.

## Considered options

- **Keep the kitchen only on the local disk**: `ding`'s tickets, watches, rulings, and night orders are GitHub issues, so this means writing a local issue tracker and losing the record across machines.
- **Run every role in the code repo**: standing roles would get their rules only by injection, or by a `CLAUDE.local.md`, which stops Claude Code from reading the code repo's AGENTS.md.
- **Run every role in the kitchen repo, executors too**: an executor's writable sandbox would then include the house rules, which it could change unreviewed, and the code repo's AGENTS.md would reach it only as a line asking it to read the file.
- **Keep one repo and allow-list the user's GitHub login**: settles who counts as the user, but leaves the kitchen's files and tickets in the team's repo.

## Consequences

- Every `ding` command first finds its kitchen: from the working directory, else from a registry on the machine keyed by the code repo. It keeps its state per kitchen, not per repo of the working directory.
- A PR is tied to its ticket by a `PR:` line that `ding` writes on the ticket, not by `#N` in the PR body or `issue<N>` in the branch name.
- In a shared code repo, review verdicts stay on tickets. Marking a PR ready can be approved ahead on the ticket, while code issues and replies to people need the user's approval at the time. The team merges. The code checks run in the executor's worktree before a PR opens, unless the team adopts them as CI.
