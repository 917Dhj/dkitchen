---
name: write-ticket
description: Write a ticket in a dkitchen kitchen — a new GitHub issue, a sub-ticket for one run, or the brief that dispatches an executor. Use whenever a station opens or rewrites a ticket.
---

# Write a ticket

A ticket is the only way work is handed out. The executor that picks it up is a fresh session that knows nothing but the ticket and the repo, so the ticket must let it do the work, and let the designer rule on the result, without asking anyone what was meant.

Write in the repo's language and its ticket layout: the Writing tickets section of the repo's `docs/agents/issue-tracker.md`, with the words from its `.dkitchen.toml`.

## 1. Gather

- **The decision behind it**: the user's words or the designer's ruling, verbatim, with its date and link.
- **The evidence**: each incident or measurement the problem rests on, with its link and its number.
- **The landing points**: the files and functions the change touches, read on the current `main`, not from memory.
- **Neighbouring tickets**: those that must finish first, and those that change the same files and so must run one after the other.

Done when every claim you will make has a link, a number, or a file and line behind it.

## 2. Write each part

- **Title**: what changes, in the repo's own terms, so the change is clear from the title alone.
- **Second line**: the design line that owns the ticket and the reviewer of its PR. Watches and design lines route the ticket by this line.
- **Approval**: the user's words quoted verbatim with their date, when a user decision is the ticket's origin.
- **Depends on**: the tickets that must finish first, and why.
- **Problem**: what goes wrong today, one point per incident, each with its evidence. The problem, not the fix.
- **Do**: the behaviour to reach and where it lands. Write decisions, not options. Write the rules and limits that apply in full, since the executor never sees policy messages sent to other stations. Write model-visible text verbatim. Where the work needs a judgment halfway, write a checkpoint: "explore, then wait for the designer".
- **Leave alone**: what must not change even when it looks related, such as interfaces, running jobs, or other tickets' files.
- **Exit conditions**: each one judged by reading a number or running a command, never by taste: a test that passes, a count against a threshold, an offline replay that matches. The executor turns them into its gate table, row for row and in this order.
- **Footer**: the tier and budget when the ticket runs models, who executes, and the station that answers questions on the ticket.

A parent ticket holds the design, rulings, and summary. Each run gets a sub-ticket (`ding new --parent <ticket>`), written the same way and scoped to that run.

Done when every part the layout names is written, or removed because it does not apply.

## 3. Check and post

Check the draft, and fix what fails:

- every Problem point has its evidence;
- every exit condition is judged by a number or a command;
- Leave alone is written;
- the tier and budget are written when the ticket runs models;
- the station that answers questions is named;
- nothing the work needs lives only in this conversation;
- `ding check-refs <draft.md>` reports no wrong reference.

Then post it with `gh issue create --title … --body-file <draft.md>` and give the link. Change a posted ticket's body with `ding rule <ticket> <draft.md> --edit-body --base <current body>`.

Done when the ticket is posted and every check passed.
