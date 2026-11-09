---
name: improve-kitchen
description: Periodic pass over a dkitchen kitchen's recent failures and friction. Turns each recurring one into a lesson, places it where it is hardest to ignore, retires the text that placement replaces, and brings proposals to the user for approval.
disable-model-invocation: true
---

# Improve the kitchen

Rules that live only as text get skipped under pressure. This pass reads what went wrong or cost too much since the last pass, and moves each _lesson_ up the _ladder_ until the failure is hard to repeat.

The repo keeps two files for this skill, both under `docs/agents/`: `improve-kitchen.md` for what is specific to this repo (extra evidence sources, where each rung lands, conventions), and `improve-kitchen-history.md` for past passes. The first pass drafts them in step 0.

The scope is how people and agents work: tickets, reviews, merges, launches, code layout, tools. Lessons about the work's content (design, model-visible text, experiment protocol, results) go to the designers as one line each, outside this pass.

## The ladder

Place each lesson on the highest rung that can hold it.

1. **Remove the cause.** Delete the mechanism that makes the failure possible.
2. **Check.** A lint, test, CI check, or merge gate fails on the mistake.
3. **Tool.** A command does the step correctly, so nobody does it by hand, or hands over information the agent could not reach.
4. **Text.** A rule, skill edit, or navigation pointer, only for what needs judgement or wayfinding. It states the behaviour to follow and cites the failure that taught it. A judgement rule goes where reviewers read it: a reviewer holds one diff, an implementer holds the whole search. Always-loaded files take pointers only.

A rule that already exists and was skipped goes up a rung. Restating it louder is the rung it already failed on.

## Steps

### 0. Find the repo's files

Read `docs/agents/improve-kitchen.md` and `docs/agents/improve-kitchen-history.md`. When either is missing, this is the first pass: draft the missing file in the scratchpad from the templates below, and propose it in step 8 with the rest. Nothing is written to the repo before then.

- `improve-kitchen.md`: a heading per section of [This repo's file](#this-repos-file), filled from the repo: evidence sources the kitchen has beyond the [general ones](#evidence-sources), or "none"; the rule files and checks for step 6; the target of each rung; the repo's conventions, such as the language to report in.
- `improve-kitchen-history.md`: one line, "Pass history: newest last. Each pass records its window, adopted changes with their PR or ticket links and the failure each targets, and rejected items with the reason."

**Done when** both files are read, or drafted in the scratchpad.

### 1. Set the window

Read the last entry of the history. The window starts at its date; with no entry, use the last 14 days. List that entry's adopted changes for step 4.

A problem the user names gets searched back to its origin, past the window's start.

**Done when** the window's start date and the list of changes to re-check are written down.

### 2. Collect incidents

Work through every [evidence source](#evidence-sources) and every extra source in `improve-kitchen.md`, across the whole window. An incident is one concrete event where work was wrong, redone, stalled, or corrected, recorded with its link, copied from what the tool returned.

_Friction_ counts too: work that finished right at a cost nobody reported, such as repeated reads, failed commands, or a long search. Session records hold it, and they are too large to read. Scan them with a script in the scratchpad, bring only the totals into context, and search the one spot behind a number that stands out. A friction incident is that spot, recorded with its session file and command.

Save the raw list in the scratchpad. It stays out of the repo.

**Done when** every source is either read for the whole window or named as unread with the reason.

### 3. Group into lessons

Merge incidents with one cause into a _lesson_. Name the cause, which is usually earlier than the symptom: why the wrong path was the easy one.

Keep a lesson when one of these holds:
- it happened on at least two different tickets or PRs, or for friction, sessions;
- one occurrence was expensive: paid spend wasted, a result or data lost, a wrong merge, a line stalled for half a day or more.

The rest are one-offs. Report only how many there were.

A count is a lead. Keep a friction lesson once its cause is confirmed at the spots behind the count.

**Done when** each kept lesson has a cause and links to every incident behind it, and every incident is in a lesson or counted as a one-off.

### 4. Check earlier changes

For each change from step 1, search this window's incidents for the failure it targeted, and give one verdict:
- **gone**: the situation came up and the failure did not;
- **recurred**: the failure happened again, with links. The change becomes a lesson and moves up the ladder;
- **not exercised**: the situation did not come up. It carries forward to the next pass.

**Done when** each change has a verdict with evidence.

### 5. Place each lesson

Pick the highest rung that holds, and name the exact file, check, or ticket it lands in, from the rung targets in `improve-kitchen.md`. Before proposing, read the current target, including open PRs and open tickets that may already cover it, so the proposal fits what is there. A check that already exists but runs too late, only warns, or is broken is the finding: propose wiring it.

A check or tool any kitchen could use belongs in `ding`. Propose it as a draft issue for the dkitchen repository, which the user files or drops; this pass writes nothing to another repository.

**Done when** each lesson has one rung, one target, and, for rung 4, a line saying why rungs 1–3 cannot hold it.

### 6. Subtract

Go through the rule files and checks named in `improve-kitchen.md`, and list:
- text that a check now enforces, or that a proposal from step 5 would replace;
- text naming a file, command, or process that no longer exists;
- text that never bore on any incident and states what agents do anyway;
- a check that fails on good code, or whose failure can no longer happen.

Pair each lesson's addition with what it retires whenever one exists.

**Done when** the list is written, with file and line for each item. An empty list states which files were read.

### 7. Tune this skill

Note which sources gave nothing, which steps took effort without changing a proposal, and which rung labels or thresholds misled you. Turn each into a proposed edit to `improve-kitchen.md`, or, for this file, a draft issue for the dkitchen repository, with the same evidence standard as any lesson.

**Done when** there are proposed edits, or a line saying this pass found none.

### 8. Report and stop

Send the user the report in the repo's language, in the shape below, with proposals ordered by what the failure cost: spend, lost results, and stalled lines rank above how often or how loudly it came up. Then stop and wait. Everything up to here changes nothing in the repository.

Approval covers exactly the numbered items the user names.

```text
Window: <start date> to <today>; N incidents, M one-offs; unread sources: <none, or the list>

Earlier changes
- <change>: <gone / recurred / not exercised>, <links>

Proposals
1. <the lesson in one sentence>
   Evidence: <links…>
   Lands in: <rung>, <file, check, or ticket>
   Retires: <the text it replaces, or "none">

Subtract only
N. <file:line>: <why it can go>

This skill
N. <what to change>, <evidence>

First pass only
N. docs/agents/improve-kitchen.md and docs/agents/improve-kitchen-history.md, as drafted
```

### 9. Apply what was approved

- Text in rule and skill files, and the two files of step 0: one PR.
- Code, checks, and tools: one ticket each, written with `write-ticket`, with the incidents as its background. Implementation follows the kitchen's normal route.
- Append this pass to the history in the same PR, including rejected items and the reason, so the next pass does not propose them again.

**Done when** each approved item has a PR or ticket link in the history.

## Evidence sources

Run from the repo root. `SINCE` is the window's start, as `YYYY-MM-DDT00:00:00Z`. The station names, signatures, status words, review lines, and the log ticket come from the repo's `.dkitchen.toml`, or `ding`'s defaults where it sets none.

1. **Ticket and PR comments**: `gh api "repos/<owner>/<repo>/issues/comments?since=$SINCE&per_page=100" --paginate --slurp`. `since` filters on the update time, so older comments come back too; compare `created_at` with the window. Every station posts under one GitHub account, so tell authors apart by signature. Look for reviews that did not pass, `blocked` statuses, reruns, reverted decisions, and repeated requests.
2. **The orchestrator log**, when `[log] issue` is set: the same comments, filtered to that ticket. Look for missed waits, wrong releases, and stalled cards.
3. **The user's own corrections**, the strongest signal: user messages in the Claude Code transcripts of the repo and its worktrees, `~/.claude/projects/<the path with every / replaced by ->/*.jsonl`, in files changed since the window's start. Take records with `type: user` and a string `message.content`. Skip content that is command or cross-session wrapping, such as text starting with `<`. Deduplicate by text, since the same message recurs across forked transcripts.
4. **Memory**: `type: feedback` files in that project's `memory/` folder changed since the window's start. Each one is a correction somebody chose to keep.
5. **Current waits**: `ding waits --minutes 60`. It reads every open ticket and can take minutes; give it a long timeout or run it in the background.
6. **Review-to-merge gaps**: for PRs merged in the window, the time from the last passing review comment to `mergedAt`. Long gaps are stalled merges; check the log before counting one, since some are deliberate holds.
7. **Check noise**, when the repo runs `ding check`: failed runs of its CI workflow in the window (`gh run list --workflow <file> --status failure --created ">=<date>" --json headBranch,url,createdAt`), and `git log --since=<date> --grep 'Guard-change:'`. Look for failures on correct code, and for checks that were loosened.
8. **Session records**, for friction. Scan every file changed since the window's start with a script:
   - Codex: `~/.codex/sessions/**/*.jsonl` whose working directory is the repo or one of its worktrees. A `payload.type` of `custom_tool_call` holds the commands; `custom_tool_call_output` holds their exit codes and output sizes, in the same order, and says when output was truncated. Pair the n-th exit code with the n-th command of the same call.
   - Claude Code: the transcripts of source 3: assistant `tool_use` items, and user `tool_result` items with `is_error`. Leave out errors the host app produced rather than the repo, such as hook timeouts.
   - Count per session: reads of the same file, non-zero exits other than searches, diffs, and test runs, truncated outputs, missing paths, and output size by command.
   - Pattern matches on output also hit text that was merely printed, so split a count by module or path before trusting it.
9. **Blocked waits by category**: from source 1, take the executor status blocks marked `blocked` in the window and count their *Waiting on* by category: review, merge, the user, design, a job or run. A large review-or-merge share points at work waiting on PRs.

## This repo's file

`docs/agents/improve-kitchen.md` holds these sections:

- **Extra evidence sources**: anything else that records what went wrong in this repo, with the command that reads it, such as run summaries or a cost ledger.
- **Rule files and checks for step 6**: `AGENTS.md`, `CLAUDE.md`, the files in `docs/agents/`, and the checks in `[check]` of `.dkitchen.toml`, plus any guards in the repo's own code that stop runs.
- **Where each rung lands**:

  | Rung | Target |
  | --- | --- |
  | Check | a script in the tools area, listed in `[check] commands`; a merge gate in `[merge]` |
  | Tool | a command in the tools area; `ding`, through a dkitchen issue, when any kitchen could use it |
  | Text | judgement on code: `docs/agents/reviewing.md`; a recurring situation: a row of known situations in `docs/agents/roles.md`; otherwise the `docs/agents/` file that owns the topic; `AGENTS.md` and `CLAUDE.md` take pointers only |

- **Conventions**: the language to report in, who approves merging rule files, and anything else the user set for these passes.

## Fixed rules

- Every proposal, including edits to this skill, carries links to real incidents and waits for the user's approval.
- This section, the evidence requirement, and step 8's stop change only when the user asks for that change in words.
