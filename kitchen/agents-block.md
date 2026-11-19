# Blocks for AGENTS.md and CLAUDE.md

Every session loads these lines, so each one is a pointer to a doc under `docs/agents/`, worded by when to reach it. Add the first block to `AGENTS.md`. Add the second to `CLAUDE.md`, which should also import `AGENTS.md`. The renderer keeps only the lines whose `docs/agents/` file is installed; from `.claude/CLAUDE.md`, prefix the links with `../`.

## AGENTS.md

```markdown
- **Roles**: at session start, read [docs/agents/roles.md](docs/agents/roles.md) once.
- **Relaying**: before messaging another session, read [docs/agents/relaying.md](docs/agents/relaying.md).
- **PRs**: before handing over, reviewing, or merging a PR, read [docs/agents/reviewing.md](docs/agents/reviewing.md).
- **Contributing**: before writing a PR<!-- module:split -->, a code issue, or a reply<!-- /module:split --> for the code repo, read [docs/agents/contributing.md](docs/agents/contributing.md).
- **Code**: before writing or changing code, read [docs/agents/code.md](docs/agents/code.md).
- **Runs**: before writing or starting a run, read [docs/agents/runner.md](docs/agents/runner.md).
- **Long-running jobs** (Codex): start every tmux job with `ding launch`; compute and shared services are in [docs/agents/long-running-jobs.md](docs/agents/long-running-jobs.md).
- **GitHub issues** (Codex): append `Codex session: <CODEX_THREAD_ID>` to every issue body or comment you post, using your current session's ID. Open each comment with the status block<!-- module:run-budgets -->, and write run requests<!-- /module:run-budgets -->, as in [docs/agents/issue-tracker.md](docs/agents/issue-tracker.md#executor-comments).
- **Waiting on the user**: before writing it, check the night orders as in [docs/agents/unattended.md](docs/agents/unattended.md#night-orders).
```

## CLAUDE.md

```markdown
@AGENTS.md

- **Watch**: start your role's watch at session start and again after handling each batch, as a background Bash task on its own: no `&`, no output redirection, nothing chained before it (not even `ding review`). Details in [docs/agents/watch.md](docs/agents/watch.md).
- **While the user is away** (orchestrator): move work forward as in [docs/agents/unattended.md](docs/agents/unattended.md).
<!-- module:split -->
- **Code repo**: the work lands in the code repo; `CLAUDE.local.md` names its checkout on this machine. Read its own `AGENTS.md` before changing or judging its code.
<!-- /module:split -->

## Execution boundaries

- **Long jobs** (started with `ding launch`) belong to Codex: `ding` cannot wake a Claude Code session.
- **GPU runs**: Codex runs them unless the user explicitly authorizes otherwise.
```
