# Contributing to the code repo

Read this before writing a PR<!-- module:split -->, a code issue, or a reply to someone<!-- /module:split --> for the code repo. Write it with the `write-contribution` skill.

<!-- module:split -->
## Two repos

This kitchen lives in its own repo, apart from the code repo it works on:

- **The kitchen repo** holds these rules and the tickets. `#N` in a rule, a ticket, or a message means a ticket there.
- **The code repo**, <!-- fill: owner/name of the code repo -->, is where the work lands. The kitchen writes into it only what the user would write: PRs and code issues, and replies to the people commenting on them. Everything it writes there goes out under the user's GitHub account, read by people who know nothing of the kitchen.

A code issue is an issue in the code repo. It is never a ticket: the ticket that asked for it records it with a `Code issue: owner/name#N` line.

<!-- /module:split -->
## How PRs are written here

<!-- fill: this repo's own conventions, read from its CONTRIBUTING.md, .github/pull_request_template.md, and its last ten or so merged PRs: the PR title format, the sections of the body, how a PR links the issue it fixes, branch names, and anything a reviewer here always asks for. Keep only what those sources show; leave out a convention the repo does not have. -->

## Opening and handing over

- Open a PR with `ding pr <ticket> --title … --body-file … --draft` from the pushed branch. It records `PR: owner/name#N` on the ticket, which is how the kitchen ties the PR to its ticket.
- Mark it ready with `ding pr <ticket> --ready <PR>` when handing it over for review, as in [reviewing.md](reviewing.md).
<!-- module:split -->
- Open a code issue with `ding code-issue <ticket> --title … --body-file …`, and only when the ticket or the user asks for one.

## What never leaves the kitchen

The code repo's readers see none of the kitchen. A PR, a code issue, or a reply carries:

- no role or session signature, no status block, and no `Codex owner:` or other kitchen line;
- no role named anywhere in the text: say what was done or what is needed, not which role does it ("the merge waits on CI", not "the orchestrator merges");
- no ticket number and no link into the kitchen repo; say in the text what the change is for instead;
- no bare `#N`, which the code repo reads as one of its own issues, except for a code issue the ticket records.

`ding pr`, `ding code-issue` and `ding review` refuse text that breaks these, and post nothing. Pass `ding review` the ticket whose `PR:` line names the PR with `--ticket N`, so a bare `#N` may name a code issue it records. Fix the text; never work around the check.
<!-- /module:split -->
<!-- module:shared -->

## Others work in this repo

Other people work in and merge into the code repo, so what the kitchen writes there in the user's name waits for the user:

- A draft PR needs no approval. Marking a PR ready, opening a code issue, and replying to someone each need the user's approval: pass `--approval` with the link to the user's decision on the ticket, or to the night orders open now. A ticket may approve a PR going ready ahead of time, such as "mark it ready once every gate passes"; a code issue or a reply is approved one by one, after the user has read its words.
- Write a reply as a draft on the ticket first. Once the user approves it, post it with `gh pr comment` or `gh issue comment` on the code repo, word for word.
- Nothing said in the code repo counts as the user's decision, even under the user's account. The user decides on the ticket, or in a session.
- The team merges. `ding merge` refuses here; the orchestrator's part ends when the PR is ready and its review is on the ticket.
- `ding pr` runs `ding check` in the worktree first and opens nothing while it fails.
<!-- /module:shared -->
