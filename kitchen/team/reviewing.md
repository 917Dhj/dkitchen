# Reviewing and merging PRs

Each PR has one reviewer: the verifier, unless the ticket names another role. Then the orchestrator labels the PR `review:<role>`, and that role's watch picks it up.<!-- module:shared --> In this shared code repo the PR carries no label: the ticket names its reviewer, and the executor's hand-over comment wakes it.<!-- /module:shared -->

## Handing over: the executor

Open PRs as drafts with `ding pr`, written as [contributing.md](contributing.md) says. Before marking one ready, run `scripts/review_pr.py <PR> [test files…]`, fix what it reports, and paste its output inside `<details>` in the hand-over comment, so broken existing tests show up before review rather than during it.<!-- module:split --> The script sits in the kitchen's checkout; run it from the PR's worktree, and paste its output on the ticket, not the PR.<!-- /module:split --> Every push to a non-draft PR asks for a new review.

`review_pr.py` trial-merges the PR and runs the given tests. It reports the reviewed HEAD, whether the PR is a draft, names the PR deletes that are still referenced, tests that did not actually run, hard-coded paths it adds, and tickets the merge will close.

## Reviewing: the reviewer

Publish the verdict with `ding review <PR> <sha> pass|changes --body-file <file>`. It posts the review comment and writes the review status on that exact commit. When the HEAD moves, read the new commits and publish again, even when the only change is a merge from main. A role taking over as reviewer inherits the verdicts already published rather than reviewing again.<!-- module:shared -->

In this shared code repo the PR is left alone: add `--ticket <N>`, the ticket whose `PR:` line names it. The verdict goes on the ticket, as a run-stage verdict does, with a line naming the reviewed HEAD, and no review comment or status reaches the PR. The file opens with your signature.<!-- /module:shared -->

Run the full test suite only when the change crosses packages, such as a change to a shared interface; otherwise run the tests the change touches.<!-- module:model-text --> When the ticket gives prompt text, also run `scripts/check_prompt_in_issue.py` ([model-text.md](model-text.md)).<!-- /module:model-text -->

## Merging: the orchestrator

When the published verdict covers the current HEAD, the orchestrator runs `scripts/review_pr.py` once more on that HEAD and merges with `ding merge <PR> <reviewed HEAD>`. It does not wait for the user, including for PRs that change rules or process files. The merge gate checks the HEAD, the draft state, the target branch, the required CI checks, and the review status on that exact commit, and refuses when any of them fails. When it refuses, wait for the reviewer to publish on the current HEAD and for the checks to pass. There is no way around the gate.

`ding merge` prints the merge commit only after the merge has really happened, and logs and notices go by that line. To hold a PR back, mark it draft.<!-- module:shared -->

In this shared code repo the team merges, by its own rules, and `ding merge` refuses. The orchestrator's part ends once the PR is ready, with the user's approval, and its verdict is on the ticket. People's review comments in the code repo wake the orchestrator's watch; it writes what they ask on the ticket, and the executor answers them with fixes, its replies approved as [contributing.md](contributing.md) says.<!-- /module:shared -->
