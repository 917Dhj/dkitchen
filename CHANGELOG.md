# Changelog

## Unreleased (develop, 0.6.3.dev1)

- **Claude Code sessions as executors.** `ding` reaches a Claude Code session through a file inbox the session reads with `ding inbox --wait`, kept running as a background task: `send`, `relay`, `rule --notify`, and the exit wake of `launch` deliver there, reporting `inbox_queued` when a waiter runs and `no_listener` (exit 1) when none does. `ding launch` works from a Claude Code session. `ding claim` posts the owner line, `Codex owner:` or the new `Claude owner:`, with a status block, and every ticket lookup reads both. `ding new` asks the session to run `ding claim` instead of writing the owner line by hand, takes `--print` to print the first message without opening a session, and dispatches to `[executor] default` (`codex` or `claude`, overridden by `--executor`); for `claude` it prints the message for whoever opens the session.
- **Seeing Claude Code executors.** `ding board` lists Claude Code sessions that keep a `ding` inbox in the repository, with `waiting` or `no-waiter`, the ticket they claimed, and the first paragraph of their last reply; `read`, `status`, and `info` read a Claude Code session from its inbox record and transcript. The orchestrator's `ding watch` reports an in-progress Claude Code executor whose `ding inbox --wait` has been gone for the new `[watch] executor_listener_minutes` (default 30; 0 disables it).

## 0.6.2

- **`ding launch` no longer leaves tmux sessions behind.** The pane's output goes to `launch-records/<name>-<id>.log`, and the session closes when the job exits, however it exits. The wake-up message and the launch line name the log. A job's name is free again once it exits. Logs untouched for `[launch] keep_days` (default 14) are deleted at the next launch, except those of a session still open; records stay, so `ding board` is unchanged. Sessions left by earlier versions stay until you close them. Run `/setup-dkitchen` or `build-team` again to update `docs/agents/long-running-jobs.md`, which told executors to close panes by hand.

## 0.6.1

- **Words.** The rules, skills, and docs call the orchestrator, designers, verifier, and executors *roles* instead of *stations*: in a kitchen a station is one cook's place on the line, which fits only the executors. Nothing to change in a repo: `.dkitchen.toml` keeps its `[stations]` table, and `ding` its options and output fields. Run `/setup-dkitchen` or `build-team` again to bring the word into your installed rules.

## 0.6.0

Not compatible with 0.5: see *Upgrading* below.

- **Skills.** `/setup-dkitchen` is now the entry: it checks prerequisites, settles the language and what the user needs, and walks through the build skills. `build-team` installs the team rules and can recommend extra design lines; `build-night` installs night orders and the orchestrator log. Each build skill also runs on its own and updates an installed kitchen in place. New everyday skills: `write-ticket` for writing tickets, `/shift-change` for handing a station over to a fresh session, and `/improve-kitchen`, a periodic pass that turns recurring failures into checks, tools, or rules and retires the text they replace. The orchestrator, or `/goodmorning`, reminds the user when the last pass is more than 14 days old.
- **Rules.** The verifier no longer gates dispatch; designers and executors talk directly; every station runs its own watch; PR review, relaying and watches get their own short files; asking the user, known situations, the ticket layout and the gate table are new; run budgets get light, medium and heavy tiers and are estimates, not pause lines. The artifacts module and frozen files are removed. Templates live in `kitchen/team/`, `kitchen/repo/`, `kitchen/runner/` and `kitchen/night/`, and the renderer in `kitchen/render.py`.
- **`ding merge`** no longer reads executor comments: `--ticket`, `--no-ticket` and `[status] pending_merge` are removed. Merges rest on the HEAD, draft, base, `[merge] required_checks` and the `[merge] review_check` status.
- **Repo checks.** `ding check` runs the checks set in a new `[check]` table: layout rules on the files a change adds (areas, top-level files, version copies, ticket numbers in paths, code in docs, test placement, study folders, module docstrings, tracked outputs), Ruff, import-linter and the repo's own check commands on the whole tree, and a `Guard-change:` trailer on any change to the checks. `ding map` lists library modules with their docstrings. The new `build-repo` skill installs `docs/agents/code.md`, the settings, and a CI workflow with `checks` and `tests` jobs. `.dkitchen.toml` also accepts a `[build]` table of notes for the build skills, which `ding` skips.
- **Runner.** The new `build-runner` skill has the agent write one runner into the repo's library for item-by-item work: a run is a spec plus a task function, its identity is the spec's configuration and the content of its inputs, code changes continue as new segments, each item commits atomically under one writer the moment it finishes, failures are retried and recorded without stopping the run, and `progress.json` and `summary.json` are always written. The skill ships a reference runner and the tests every runner must pass, not a library ([ADR 0002](docs/adr/0002-runner-is-a-reference-not-a-library.md)). It installs `docs/agents/runner.md`, and a check that keeps service names out of experiment code when the repo has a service registry. Left for later: checkpoint and canary rules, a cost ledger, pausing in place, and GPU placement.
- **Wording.** `[merge] review_pass` and `review_changes` set the review line `ding review` writes and `ding watch` recognises, and `[watch] handoff` sets the words that hand work to a station. Both default to English.

### Upgrading from 0.5

- Delete `pending_merge` from `[status]` in `.dkitchen.toml`; `ding` now refuses the key.
- Set `[merge] review_check = "review"` if it is not set, so merges need the reviewer's verdict.
- A kitchen in another language sets `review_pass`, `review_changes` and `handoff` to its own words, for example `review_pass = "审过 {sha}：通过"`, `review_changes = "审过 {sha}：有出入，见下"` and `handoff = ["交"]`, which were the hard-coded words before.
- Run `/setup-dkitchen` or `build-team` again to bring `docs/agents/` up to the new rules.

## 0.5.15

- `ding watch` keeps every reported line whose GitHub time is at or after the new `since`, so items stamped ahead of the clock are reported once. The state file now stores `seen` as line-to-time; older list states still load.

## 0.5.13

- `ding merge` supports optional `[merge] required_checks`, defaulting to `[]`. Every required name must succeed on the reviewed HEAD across the latest check runs and commit statuses. Missing, pending, failed, neutral and skipped results refuse immediately with no bypass; API/read errors also refuse.

## 0.5.12

- `ding waits` lists overdue unanswered waits on all configured stations and the user, with station/alias filtering, a minute threshold, and JSON output.
- The orchestrator's watch also reminds once per executor comment about unanswered verifier waits, using the shared waits query.
- `ding watch` refuses stdout redirected to `/dev/null` with exit 3 before polling or touching its state; pipes and files remain supported.

## 0.5.11

- `ding night open|show|close` records time-limited night orders on the orchestrator log ticket, with configurable headings and explicit replacement of open orders.
- User-invoked `goodnight` and `goodmorning` skills collect approvals for the offline window and report their use when the user returns.
- Unattended-work templates require stations to check night orders before waiting on the user and name the order behind each automatic action in the log.

## 0.5.10

- Watch name matching supports `[stations.aliases]` and width-normalized brackets/colons, with longest configured-name precedence.
- Station watches recognize Next-field handoffs, explicit mentions from non-designers, and default-designer requests. Configured `[status] paused` executors do not wake them.
- Older status labels no longer hide idle or stale executor comments; awaiting-user labels continue to suppress these checks.
- The orchestrator reports unanswered designer requests after `[watch] design_answer_minutes`, default 30, with persistent per-comment deduplication. Set 0 to disable it.

## 0.5.9

- `ding watch --for NAME` watches only executor comments waiting on that station, with longest configured-name matching and separate default state files.
- Station watches skip label/PR queries and stale/idle checks, including board and tmux calls.

## 0.5.8

- `ding rule --notify` sends the complete stripped first nonempty line, including through `{first_line}` templates.
- Shortened terminal hints, watch summaries, PR titles, and diagnostic excerpts end with `…`.

## 0.5.7

- `ding watch` reports idle executors still marked in progress after `[watch] idle_minutes`, default 45 minutes. Idle checks run every third of the threshold, capped at 15 minutes, independently of stale checks. First-observation times survive restarts; setting 0 disables the new wake.
- Watch uses `ding board --no-issue-lookup` to attribute sessions only by `[sessions] name`, without a whole-repository scan. Non-template session names remain unattributed. Plain board retains its GitHub fallback; watch retries nonzero board exits.
- GitHub errors during post-settle collection and stale/idle checks count toward `--max-errors` without advancing the reporting cursor or printing partial batches.

## 0.5.6

- `[rule] signatures` configures the designer prefixes shared by `ding rule` and `ding watch`.
- Without `signatures`, `ding watch` now requires the designer name plus the configured separator, rather than the bare designer name. Verifier and orchestrator matching is unchanged.
