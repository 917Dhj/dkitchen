# The kitchen

These are the house rules of dkitchen, as templates. The build skills install them into a repo's `docs/agents/` and adapt them to that repo; you can also read them here to see how the kitchen runs.

## Layout

Each build skill installs one folder. [render.py](render.py) renders a folder with `--templates team` or `--templates night`.

| Template | Installed by | Installed as | What it covers |
| --- | --- | --- | --- |
| [agents-block.md](agents-block.md) | every build skill | blocks in `AGENTS.md` and `CLAUDE.md` | The pointers every session reads, for the files installed |
| [team/roles.md](team/roles.md) | `build-team` | `docs/agents/roles.md` | Stations, design lines, who decides what, the verifier, known situations, results, designer replies, asking the user |
| [team/relaying.md](team/relaying.md) | `build-team` | `docs/agents/relaying.md` | Messaging another session, and comment signatures |
| [team/watch.md](team/watch.md) | `build-team` | `docs/agents/watch.md` | Each station's `ding watch`, and what wakes it |
| [team/reviewing.md](team/reviewing.md) | `build-team` | `docs/agents/reviewing.md` | Handing over, reviewing, and merging PRs |
| [team/issue-tracker.md](team/issue-tracker.md) | `build-team` | `docs/agents/issue-tracker.md` | The ticket layout, executor comments, the status block, labels, result reports |
| [team/messaging.md](team/messaging.md) | `build-team` | `docs/agents/messaging.md` | Messaging sessions with `ding` |
| [team/long-running-jobs.md](team/long-running-jobs.md) | `build-team` | `docs/agents/long-running-jobs.md` | `ding launch`, resumable jobs, compute and shared services |
| [team/run-budgets.md](team/run-budgets.md) | `build-team`, module | `docs/agents/run-budgets.md` | Run tiers, run requests, ticket budgets, what needs the user's approval |
| [team/model-text.md](team/model-text.md) | `build-team`, module | `docs/agents/model-text.md` | Prompts and other text a model sees, owned by the designer |
| [night/unattended.md](night/unattended.md) | `build-night` | `docs/agents/unattended.md` | Night orders, what the orchestrator moves forward while the user is away, the orchestrator log |

A module is optional within its skill. Every other file of a folder is installed whenever its skill runs.

## Template markers

- `<!-- module:NAME -->` … `<!-- /module:NAME -->` wraps text that belongs to module `NAME`. When the module is installed, keep the text and drop the markers. When it is not, drop the text too.
- `<!-- fill: … -->` marks a gap the build skill fills from the repo and the user's answers, such as hosts, GPUs, or shared services.

## Vocabulary

The rules and the `ding` commands share one vocabulary. The defaults are below. A kitchen in another language changes these words in the rules and in the repo's [`.dkitchen.toml`](../docs/ding.md#dkitchentoml) together, so that people, agents, and scripts keep agreeing.

| Word | Default | Read by |
| --- | --- | --- |
| Station names | Orchestrator, Designer, Verifier, Executor | Everyone |
| Signatures | A comment's first line starts with `Orchestrator:`, `Designer:`, or `Verifier:` (Markdown heading marks allowed). Executor comments carry a `Codex session:` line (`Claude session:` for a Claude Code executor). Anything else is the user's. | `ding watch`, `ding relay`, `ding log` |
| Owner line | `Codex owner: <session id>` | `ding` targets |
| Status fields | `Status`, `Waiting on`, `Key numbers`, `Next` | `ding board --status`, `ding watch` |
| Status values | `in progress`, `waiting on design`, `waiting on user`, `blocked`, `done` | `ding watch` |
| Nobody to wait on | `none` | `ding watch` |
| Handing to a station | `hand to <station>`, also `@<station>` | `ding watch --for` |
| Designer reply type | `Type: actionable`, `Type: proposal, awaiting user`, `Type: record` | Orchestrator, executors, `ding rule` |
| Review lines | `Reviewed <sha>: pass`, `Reviewed <sha>: changes requested, see below` | `ding review`, `ding watch` |
| Status labels | `status:awaiting-design`, `status:awaiting-user`, `status:blocked`, `status:done` | `ding watch`, `gh issue list` |
| Night-order markers | `Orchestrator: user decision (night orders`, `Orchestrator: night orders closed` | `ding night`, all stations |

## Tools the rules call

Two layers:

- **`ding` commands** do the same thing in every repo and are installed with `pipx install dkitchen`: `ding relay`, `ding review`, `ding merge`, `ding log`, `ding night`, `ding watch`, `ding waits`, `ding check-refs`, `ding rule`, and the messaging commands in [the ding guide](../docs/ding.md).
- **Repo scripts** depend on the repo, so `build-team` writes them into the repo's `scripts/`, starting from the reference versions in [its scripts folder](../skills/build-team/scripts/): `review_pr.py` for PR hand-over and review, and the checks the `model-text` module uses.
