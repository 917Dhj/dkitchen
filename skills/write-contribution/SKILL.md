---
name: write-contribution
description: Write what a dkitchen kitchen puts into the code repo in the user's name — a PR's title and body, a code issue, or a reply to someone commenting there. Use whenever a role opens a PR, marks one ready, files a code issue, or answers a person in the code repo.
---

# Write a contribution

Everything the kitchen puts into the code repo goes out under the user's GitHub account and is read by people who know nothing of the kitchen: no roles, no tickets, no status blocks. It must read as the user's own work, written the way that repo writes, and say what it needs to without the ticket behind it.

The rules are in the kitchen's `docs/agents/contributing.md`: the code repo's own conventions, and, in a kitchen kept in its own repo, what never leaves the kitchen and what needs the user's approval. Read it first.

## 1. Gather

- **What it is for**: the change, or the question, in the code repo's terms. Take it from the ticket, but write no ticket number and no link into the kitchen repo.
- **The repo's conventions**: the PR or issue template and title format from `contributing.md`. Where it leaves something open, look at two or three recent merged PRs of the code repo.
- **What it refers to**: issues of the code repo the change fixes or relates to, as recorded on the ticket's `Code issue:` lines, and files and functions on the PR's branch.
- **The approval**, in a shared code repo: the link to the user's decision on the ticket, or to the night orders open now, for anything beyond a draft PR.

Done when you can say what the text is for without pointing at the ticket, and know which conventions it follows.

## 2. Write

- **A PR**: the title in the repo's format; the body in the template's sections, saying what changes, why, and how it was tested, with the numbers a reviewer needs. Link only code repo issues, and only those the ticket records.
- **A code issue**: what happens, what should happen, and how to see it, in the repo's issue template when it has one.
- **A reply**: an answer to the person's point, in plain words, with what was changed and where. Write it as a draft on the ticket first, for the user to approve when the code repo is shared.

Done when the draft follows the repo's conventions and carries nothing of the kitchen.

## 3. Check and post

Check the draft, and fix what fails:

- no role or session signature, status block, ticket number, or kitchen link;
- every `#N` is an issue of the code repo that the ticket records;
- in a shared code repo, the approval link is in hand for anything beyond a draft PR.

Then post it: `ding pr <ticket> --title … --body-file <draft.md> --draft` for a PR, `ding pr <ticket> --ready <PR>` to hand it over, `ding code-issue <ticket> --title … --body-file <draft.md>` for a code issue, each with `--approval <link>` when needed, and `gh pr comment` or `gh issue comment` on the code repo for an approved reply. When `ding` refuses the text, fix the text; never work around the check.

Done when it is posted, or `ding` refused it and you fixed the text and posted again.
