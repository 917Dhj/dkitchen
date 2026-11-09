# Blocks for AGENTS.md and CLAUDE.md

Every session loads these lines, so each one is a pointer to a doc under `docs/agents/`, worded by when to reach it. Add the first block to `AGENTS.md`. Add the second to `CLAUDE.md`, which should also import `AGENTS.md`. The renderer keeps only the lines whose `docs/agents/` file is installed; from `.claude/CLAUDE.md`, prefix the links with `../`.

## AGENTS.md

```markdown
- **Roles**: at session start, read [docs/agents/roles.md](docs/agents/roles.md) once.
- **Relaying**: before messaging another session, read [docs/agents/relaying.md](docs/agents/relaying.md).
- **PRs**: before handing over, reviewing, or merging a PR, read [docs/agents/reviewing.md](docs/agents/reviewing.md).
- **Long-running jobs** (Codex): start every tmux job with `ding launch`; compute and shared services are in [docs/agents/long-running-jobs.md](docs/agents/long-running-jobs.md).
- **GitHub issues** (Codex): append `Codex session: <CODEX_THREAD_ID>` to every issue body or comment you post, using your current session's ID. Open each comment with the status block<!-- module:run-budgets -->, and write run requests<!-- /module:run-budgets -->, as in [docs/agents/issue-tracker.md](docs/agents/issue-tracker.md#executor-comments).
- **Waiting on the user**: before writing it, check the night orders as in [docs/agents/unattended.md](docs/agents/unattended.md#night-orders).
```

## CLAUDE.md

```markdown
@AGENTS.md

- **Watch**: at session start, start your station's watch as in [docs/agents/watch.md](docs/agents/watch.md).
- **While the user is away** (orchestrator): move work forward as in [docs/agents/unattended.md](docs/agents/unattended.md).

## Execution boundaries

- **Long jobs** (started with `ding launch`) belong to Codex: `ding` cannot wake a Claude Code session.
- **GPU runs**: Codex runs them unless the user explicitly authorizes otherwise.
```
