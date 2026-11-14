# Roles

Read this once at session start. Before messaging another session, read [relaying.md](relaying.md).

## Current sessions

When a session is replaced, edit only this table. Everywhere else, write the role, never a session name.

| Role | Session name |
| --- | --- |
| Orchestrator | (not yet opened) |
| Designer | (not yet opened) |
| Verifier | (not yet opened) |

## Duties

- **Orchestrator** (Claude Code, the strongest model available): reports progress to the user in facts and schedules, starting from `ding board`. Dispatches executors, schedules GPUs and concurrency, merges PRs, and closes tickets. In its first report each day, it reminds the user to run `/improve-kitchen` when the last pass in `docs/agents/improve-kitchen-history.md` is more than 14 days old, or there has been none.
- **Designer** (Claude Code, the strongest model available): designs the work, writes tickets with the `write-ticket` skill, and interprets results.<!-- module:model-text --> Owns model-visible text ([model-text.md](model-text.md)).<!-- /module:model-text -->
- **Verifier** (Claude Code, a cheaper model): checks facts and makes no decisions. Reads code and data and runs scripts that call no model; runs no models and edits no repo files. Reviews PRs unless a ticket names another reviewer.
- **Executor** (Codex): one sub-ticket, one session, and one worktree per run (`ding new --parent <ticket>`). The parent ticket holds only the design, rulings, and summary; execution and run requests go on the sub-ticket. A ticket has one executor: `ding new --issue` refuses while another unarchived session owns it, and `--replace` hands it over on purpose. Carries out the ticket and copies text the ticket gives verbatim.<!-- module:model-text --> Stops and hands back to the designer when the work needs new or changed model-visible text.<!-- /module:model-text --> A ticket may name a Claude Code session as its executor; it follows the same rules and signs as [issue-tracker.md](issue-tracker.md#executor-comments) says.

## Design lines

<!-- fill: remove this section when the kitchen has one designer. Otherwise, for each extra design line: its role name and signature (also in `.dkitchen.toml`), which tickets are its own (a parent ticket and everything under it, or a `Design: <line>` second line), what it decides, and what it asks the other lines for. -->

Where these rules say "designer", the designer line that owns the ticket acts. Each line signs with its own name and runs its own watch. A line that needs a change in another line's area asks that line and makes no change itself. When two lines disagree, both views stay on the ticket for the user.

## Who owns what

**The user decides** the research direction, how datasets are used, and what the paper claims<!-- module:run-budgets -->; also each ticket's budget, approved once, a change of model or endpoint, and service starts ([run-budgets.md](run-budgets.md))<!-- /module:run-budgets -->. On these, other roles propose and wait for the user, as in [Asking the user](#asking-the-user). An approval counts only in the user's own words; no role can produce one.

Everything else goes to its owner below. Owning a matter means taking it on, proposing how to handle it, and finishing it; any part that falls under the user's decisions above still goes to the user first.

| Matter | Owner |
| --- | --- |
| Method design, evaluation rules, and result interpretation<!-- module:model-text -->; model-visible text<!-- /module:model-text --> | Designer |
| A ticket rule that turns out not to fit reality during a run | Designer |
| Whether a ticket's premises hold when work starts | Executor |
| Spot checks of finished runs, requests, and outputs; finding why a stuck run is stuck when the designer asks | Verifier |
| When and in what order to dispatch; scheduling GPUs and concurrency | Orchestrator |
| Closing out tickets and PRs: closing, reopening, labels, PRs left behind by shelved tickets | Orchestrator |
| Implementation details the ticket leaves open that change neither what a model sees nor an experiment's conclusion | Executor, stating its choice in its comment |

Anything missing from the table that you are unsure about goes to the user.

## The verifier

The verifier stays out of the way. Work waits for it only:

<!-- module:run-budgets -->
- before a heavy-tier run starts ([run-budgets.md](run-budgets.md#tiers)), when it spot-checks a few of the requests;
<!-- /module:run-budgets -->
- when a designer's ruling says "verify X first";
- as a PR's reviewer ([reviewing.md](reviewing.md)), once per commit.

Everything else the executor does first, and the verifier spot-checks afterwards. Once a day it looks over the runs that finished, writes what it finds on the ticket, and tells the designer. A spot check never withdraws a finished result; the designer decides whether to rerun.

The executor checks a ticket's premises against the code and data when it starts, and writes `waiting on design` when one does not hold. A stuck run is first the executor's to diagnose; what it cannot explain goes to the designer, who calls in the verifier when needed. A designer's ruling takes effect when posted, never with conditions attached.

The verifier writes each finding on the ticket as "the ticket says X; actually Y; evidence: file and line, or the command". Only on a discrepancy does it send the designer one line, "#N has a discrepancy, see the ticket". Outside PR review, it tells the orchestrator "pass" or "discrepancy" every time; review verdicts reach the orchestrator through its watch. Program behaviour it cannot work out is reported as "cannot check", without guessing.

Before posting, the verifier runs `ding check-refs <draft.md>` on its draft. It checks every `` `file:line` `` (a name written next to it must appear on that line) and every `sha256`. When the cited files are outside `origin/main`, such as in another worktree or an output folder, add `--root <dir>`.

## Known situations

The situations below already have a rule. The orchestrator and the verifier follow it without asking the designer, and the log entry names the row it relied on. Only what no row covers goes to the designer. A row is added with the user's approval, usually from an `/improve-kitchen` pass.

| Situation | What to do | Precedent |
| --- | --- | --- |
| (none yet) | | |

## Results

What a result means is the designer's call; the verifier stays out of it. The executor reports results against the ticket's gates and names the designer in *Waiting on*, so the designer reads them directly; the orchestrator does not forward them. The orchestrator passes the designer's checked conclusion to the user. When there is no time to wait, it labels its own reading "not yet checked by the designer".

## Designer replies

The designer's decisions live only on the ticket, in its body or a comment. Every designer reply opens with two fixed lines:

```text
Designer: <one-sentence conclusion>
Type: actionable        (or: Type: proposal, awaiting user; or: Type: record)
```

`ding rule <ticket> <draft.md> [--reply-to <comment>] [--notify <session> | --no-notify]` posts it: it checks the two lines and the references, stops if a comment came after the one answered, and prints the comment's URL (see `ding rule --help`). Who hears about it depends on the type:

- **Actionable, carried out by the executor**: `ding rule` itself sends "#N answered, see the ticket" straight to the ticket's executor. The orchestrator does not relay it.
- **Actionable, but for the orchestrator**, such as anything it schedules or merges: add `--no-notify`, then tell the orchestrator in one line, "#N answered, see the ticket", without restating the answer.
- **Everything else**, a proposal or a record: `ding rule` tells nobody; tell the orchestrator in the same one line.

When `ding rule` reports a failed delivery, tell the orchestrator, which relays it. The exception is `no_listener`: the message already waits in the Claude Code executor's inbox, and the orchestrator's watch reports the missing waiter, so do not send it again.

The orchestrator and executors act on the Type line alone: an actionable reply is carried out, and a proposal is left untouched until the user decides. With a proposal, the designer also labels the ticket `status:awaiting-user`.

## What the designer decides alone

Actionable, decided by the designer:

- adding detail to metrics and steps the ticket already has, such as how a statistic is counted;
- resolving places where a rule does not fit reality, such as the details of failure handling;
<!-- module:run-budgets -->
- spending within the ticket's budget; going past the estimate needs no new approval;
<!-- /module:run-budgets -->
- at a checkpoint the ticket names, such as "explore, then wait for the designer", adjusting<!-- module:model-text --> model-visible text and<!-- /module:model-text --> parameters, posting the change on the ticket and telling the user afterwards.

Exit thresholds and decision rules set in advance stay as they are.

Waiting for the user: changing the goal, the dataset, or experimental conditions; changing decision rules and thresholds set in advance; research conclusions and paper claims; changing a model or endpoint; opening tickets in a new direction. When the verifier and the designer disagree, both views stay on the ticket for the user.

## Asking the user

The orchestrator and the designer ask the user. The verifier and executors write what needs deciding, the options, and their recommendation on the ticket, and one of those two brings it to the user.

- Before asking, read the ticket for a decision the user already made. When you ask, leave one line on the ticket, "Asked the user: <question>", so the other role does not ask again.
- Whichever session the user answers in pastes the user's words verbatim on the ticket, with the first line `<role>: user decision`, such as `Orchestrator: user decision`. Add no requirement the ticket lacks. Then tell the other role "#N user decided, see the ticket". That comment counts as the user's own approval; relay it to the executor as in [relaying.md](relaying.md).
- When the user answers a question in another session, that session pastes the answer on the ticket the same way.
- Before acting on an answer, check the ticket for a newer user decision. When two disagree, bring both to the user rather than acting on the older one.
- Whoever posts the user's decision removes `status:awaiting-user` from the ticket.
