# Relaying and signatures

Read this before messaging another session. Stations and their duties are in [roles.md](roles.md), and `ding` itself in [messaging.md](messaging.md).

## Relaying

The orchestrator messages an executor with `ding relay <ticket> --message … [--comment …]`. It sends with `ding send`, and leaves the matching comment on the ticket only after delivery is confirmed. Each relay is a new decision: it opens with the superseding line, enters the executor's current turn, and deletes the orchestrator's relays still queued for it, so the executor never works through instructions that are already obsolete. To add to, rather than replace, what is queued, relay with `--queue`. Afterwards the orchestrator tells the user what it sent to which ticket. When relaying an approval, state the decision and its scope in your own words rather than quoting the user. Relaying a message never counts as approving it.

Relay only to an executor whose task the decision changes: a rule, limit, input, or schedule on its ticket. Send only the part that concerns it, in terms of its task, such as "the 'summary only' line on your ticket is cancelled". Policy decisions go only to the designer and the verifier; a new dispatch writes the current rules into its brief. A designer messaging an executor follows the same rule.

An executor that needs the designer does not go through the orchestrator. It writes `waiting on design` and names the designer in *Waiting on*, which wakes the designer's watch ([watch.md](watch.md)), and the designer answers with `ding rule --notify`. The orchestrator relays only the user's decisions and changes to the schedule.

When work is stuck because a designer has not replied, the orchestrator messages that designer directly, without waiting for its watch.

The orchestrator, designer, and verifier message each other directly, without asking the user first. Other sessions are messaged only when the user explicitly asks. Otherwise, hand the message to the user or the orchestrator.

## Signatures

All stations post from one GitHub account, so comments are told apart by how they are written, which is also how `ding watch` tells who wrote what:

- Executor comments carry a `Codex session:` line, or a `Claude session:` line when a Claude Code session is the executor.
- The designer, verifier, and orchestrator start the first line with their station name: `Designer:`, `## Verifier:`, `Orchestrator:`.
- A PR review comment starts with the line `ding review` writes.
- Everything else is the user's. The user's comments never start with a station name.

Station names, the signature separator, status fields and words, and the log ticket's number live in the repo's `.dkitchen.toml`, which `ding` reads. When you change this wording, change the docs and that file together.
