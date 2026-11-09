# Reviewing and merging PRs

Each PR has one reviewer: the verifier, unless the ticket names another role. Then the orchestrator labels the PR `review:<role>`, and that role's watch picks it up.

## Handing over: the executor

Open PRs as drafts. Before marking one ready, run `scripts/review_pr.py <PR> [test files…]`, fix what it reports, and paste its output inside `<details>` in the hand-over comment, so broken existing tests show up before review rather than during it. Every push to a non-draft PR asks for a new review.

`review_pr.py` trial-merges the PR and runs the given tests. It reports the reviewed HEAD, whether the PR is a draft, names the PR deletes that are still referenced, tests that did not actually run, hard-coded paths it adds, and tickets the merge will close.

## Reviewing: the reviewer

Publish the verdict with `ding review <PR> <sha> pass|changes --body-file <file>`. It posts the review comment and writes the review status on that exact commit. When the HEAD moves, read the new commits and publish again, even when the only change is a merge from main. A role taking over as reviewer inherits the verdicts already published rather than reviewing again.

Run the full test suite only when the change crosses packages, such as a change to a shared interface; otherwise run the tests the change touches.<!-- module:model-text --> When the ticket gives prompt text, also run `scripts/check_prompt_in_issue.py` ([model-text.md](model-text.md)).<!-- /module:model-text -->

## Merging: the orchestrator

When the published verdict covers the current HEAD, the orchestrator runs `scripts/review_pr.py` once more on that HEAD and merges with `ding merge <PR> <reviewed HEAD>`. It does not wait for the user, including for PRs that change rules or process files. The merge gate checks the HEAD, the draft state, the target branch, the required CI checks, and the review status on that exact commit, and refuses when any of them fails. When it refuses, wait for the reviewer to publish on the current HEAD and for the checks to pass. There is no way around the gate.

`ding merge` prints the merge commit only after the merge has really happened, and logs and notices go by that line. To hold a PR back, mark it draft.
