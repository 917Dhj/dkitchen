# The kitchen

These are the house rules of dkitchen, as templates. The build skills install them into a repo's `docs/agents/` and adapt them to that repo; you can also read them here to see how the kitchen runs.

## Layout

Each build skill installs one folder. [render.py](render.py) renders a folder with `--templates team`, `repo`, `runner`, or `night`.

| Template | Installed by | Installed as | What it covers |
| --- | --- | --- | --- |
| [agents-block.md](agents-block.md) | every build skill | blocks in `AGENTS.md` and `CLAUDE.md` | The pointers every session reads, for the files installed |
| [team/roles.md](team/roles.md) | `build-team` | `docs/agents/roles.md` | Roles, design lines, who decides what, the verifier, known situations, results, designer replies, asking the user |
| [team/relaying.md](team/relaying.md) | `build-team` | `docs/agents/relaying.md` | Messaging another session, and comment signatures |
| [team/watch.md](team/watch.md) | `build-team` | `docs/agents/watch.md` | Each role's `ding watch`, and what wakes it |
| [team/reviewing.md](team/reviewing.md) | `build-team` | `docs/agents/reviewing.md` | Handing over, reviewing, and merging PRs |
| [team/issue-tracker.md](team/issue-tracker.md) | `build-team` | `docs/agents/issue-tracker.md` | The ticket layout, executor comments, the status block, labels, result reports |
| [team/messaging.md](team/messaging.md) | `build-team` | `docs/agents/messaging.md` | Messaging sessions with `ding` |
| [team/long-running-jobs.md](team/long-running-jobs.md) | `build-team` | `docs/agents/long-running-jobs.md` | `ding launch`, resumable jobs, compute and shared services |
| [team/run-budgets.md](team/run-budgets.md) | `build-team`, module | `docs/agents/run-budgets.md` | Run tiers, run requests, ticket budgets, what needs the user's approval |
| [team/model-text.md](team/model-text.md) | `build-team`, module | `docs/agents/model-text.md` | Prompts and other text a model sees, owned by the designer |
| [repo/code.md](repo/code.md) | `build-repo` | `docs/agents/code.md` | Areas, changing code in place, reuse, verifying a change, and the checks |
| [runner/runner.md](runner/runner.md) | `build-runner` | `docs/agents/runner.md` | The one runner, specs, task functions, run identity, resuming, exit states |
| [night/unattended.md](night/unattended.md) | `build-night` | `docs/agents/unattended.md` | Night orders, what the orchestrator moves forward while the user is away, the orchestrator log |

A module is optional within its skill. Every other file of a folder is installed whenever its skill runs.

## Installing

Every build skill installs its templates the same way. The skill's own file says which templates, questions, and checks are its own; this section holds what they share.

- **Prerequisites.** The kitchen runs on GitHub issues: `git remote -v` and `gh repo view` must show a GitHub remote, and `gh auth status` must pass. A repo without one stops here; tell the user, and offer to continue once one exists. `ding --version` must report 0.6.0 or later; when it is missing or older, offer `pipx install dkitchen` or `pipx upgrade dkitchen`. The kitchen needs both Claude Code (`claude --version`) for the orchestrator, designer, and verifier, and Codex (`codex --version`, an App Server socket under `/tmp/codex-daemon-$(id -u)`) for executors, plus `tmux -V`.
- **Templates.** The `kitchen/` folder of the dkitchen repository, `../../kitchen/` from a skill's base directory. If the folder is missing because a skill was copied on its own, clone `https://github.com/917Dhj/dkitchen` at the tag matching `ding --version` (for example `v0.6.0`) into a temporary directory and use its `kitchen/`.
- **Language.** The installed rules are written in the user's language. For any language other than English, translate the [vocabulary](#vocabulary) once, show it as a table, and get it confirmed: it is used word for word in the rules and in `.dkitchen.toml`, and scripts match these words exactly. A kitchen that already has a `.dkitchen.toml` keeps its vocabulary.
- **Rendering.** `python <kitchen>/render.py --templates <folder> [--modules …] --out docs/agents` writes the folder's files. Then fill every `<!-- fill: … -->` from the user's answers; where a gap does not apply, remove the sentence or section around it and reword what still mentions it. Translate every file for a language other than English.
- **Updating in place.** A `<!-- dkitchen:start -->` block or a `.dkitchen.toml` means dkitchen is already installed, and this run updates it. Before rendering over an installed file, read it: carry over its filled gaps, its wording, and everything added since it was installed, such as rows of known situations and standing rules, and show the user the diff. A file from another setup, such as an issue-tracker doc from Matt Pocock's skills, is merged: keep its sections dkitchen does not cover, and replace or add dkitchen's.
- **Pointer blocks.** `render.py` prints the two blocks for every file installed in `docs/agents/`, whichever skill installed it. Wrap each in `<!-- dkitchen:start -->` and `<!-- dkitchen:end -->`, replacing the existing block in place. The first goes in `AGENTS.md`, created if needed, because Codex reads `AGENTS.md`. The second goes in the `CLAUDE.md` Claude Code already loads, at the root or in `.claude/`, or a new root `CLAUDE.md`; it imports `AGENTS.md` (`@AGENTS.md`, or `@../AGENTS.md` and `../`-prefixed links from `.claude/`).
- **Settings.** `.dkitchen.toml` holds only keys that differ from the defaults ([the keys](../docs/ding.md#dkitchentoml)). Each skill writes its own keys and keeps the rest.
- **Approval.** Nothing is written or posted before the user approves the draft, including each GitHub change by name.
- **Checks every skill runs.** `grep -rn '<!-- module:\|<!-- /module:\|<!-- fill:' docs/agents AGENTS.md CLAUDE.md .claude/CLAUDE.md` finds nothing, and every relative link in the installed files resolves to an existing file.

## Template markers

- `<!-- module:NAME -->` … `<!-- /module:NAME -->` wraps text that belongs to module `NAME`. When the module is installed, keep the text and drop the markers. When it is not, drop the text too.
- `<!-- fill: … -->` marks a gap the build skill fills from the repo and the user's answers, such as hosts, GPUs, or shared services.

## Vocabulary

The rules and the `ding` commands share one vocabulary. The defaults are below. A kitchen in another language changes these words in the rules and in the repo's [`.dkitchen.toml`](../docs/ding.md#dkitchentoml) together, so that people, agents, and scripts keep agreeing.

| Word | Default | Read by |
| --- | --- | --- |
| Role names | Orchestrator, Designer, Verifier, Executor | Everyone |
| Signatures | A comment's first line starts with `Orchestrator:`, `Designer:`, or `Verifier:` (Markdown heading marks allowed). Executor comments carry a `Codex session:` line (`Claude session:` for a Claude Code executor). Anything else is the user's. | `ding watch`, `ding relay`, `ding log` |
| Owner line | `Codex owner: <session id>` | `ding` targets |
| Status fields | `Status`, `Waiting on`, `Key numbers`, `Next` | `ding board --status`, `ding watch` |
| Status values | `in progress`, `waiting on design`, `waiting on user`, `blocked`, `done` | `ding watch` |
| Nobody to wait on | `none` | `ding watch` |
| Handing to a role | `hand to <role>`, also `@<role>` | `ding watch --for` |
| Designer reply type | `Type: actionable`, `Type: proposal, awaiting user`, `Type: record` | Orchestrator, executors, `ding rule` |
| Review lines | `Reviewed <sha>: pass`, `Reviewed <sha>: changes requested, see below` | `ding review`, `ding watch` |
| Status labels | `status:awaiting-design`, `status:awaiting-user`, `status:blocked`, `status:done` | `ding watch`, `gh issue list` |
| Night-order markers | `Orchestrator: user decision (night orders`, `Orchestrator: night orders closed` | `ding night`, all roles |

## Tools the rules call

Two layers:

- **`ding` commands** do the same thing in every repo and are installed with `pipx install dkitchen`: `ding relay`, `ding review`, `ding merge`, `ding log`, `ding night`, `ding watch`, `ding waits`, `ding check-refs`, `ding rule`, and the messaging commands in [the ding guide](../docs/ding.md).
- **Repo scripts** depend on the repo, so `build-team` writes them into the repo's `scripts/`, starting from the reference versions in [its scripts folder](../skills/build-team/scripts/): `review_pr.py` for PR hand-over and review, and the checks the `model-text` module uses.
