---
name: shift-change
description: Hand a dkitchen station over to a fresh session. Run it in the outgoing session to write the handover note, then in the incoming session with "take over <note>" to pick up from it.
argument-hint: "take over <note path>, or what the next shift should focus on"
disable-model-invocation: true
---

# Shift change

A station's session gets replaced when its context fills up or the user wants a fresh one. The outgoing chef writes a handover note and leaves the station clean; the incoming chef takes over from the note and the sources it points to.

Run without an argument, or with what the next shift should focus on, to **hand over**. Run with `take over <note path>` to **take over**.

An executor does not use this skill: its ticket already holds the whole story, and a new executor takes the ticket with `ding new --issue <ticket> --replace`.

## Handing over

### 1. Gather

From the sources, not from memory:

- your station, from the Current sessions table in `docs/agents/roles.md`, and the peers' session names;
- `ding board`, and the open tickets you own or that wait on you (`gh issue list`, the `status:*` labels);
- your watch's command and state file, your other background tasks, and jobs you started;
- open night orders: `ding night show`;
- decisions the user made in this conversation, and instructions the user gave you here that no file records.

Done when you can name every open ticket that needs your station, everything you have running, and every user decision from this conversation.

### 2. Put on the tickets what belongs there

A user decision given only in this conversation goes on its ticket now, verbatim, as the Asking the user section of `docs/agents/roles.md` says. The note then links to it rather than carrying it.

Done when every user decision from step 1 is on a ticket or listed for the note's own section below.

### 3. Write the note

Write it to `/tmp/dkitchen-handoff/<repo name>/<station>-<UTC time>.md`, outside the repo. Link to what tickets, commits, and docs already hold rather than copying it, and leave out secrets such as keys and passwords. The note holds:

- **Station**: the station, the repo, and the focus the user gave, if any.
- **Peers**: each peer station's session name and how to message it.
- **Open work**: one line per ticket: its link, its state, the next step, and who takes it.
- **Running**: the watch command, background tasks, and jobs, each with how to check it.
- **Night orders**: the link to open orders, or "none".
- **Not yet in the rules**: standing instructions the user gave in this conversation, verbatim with their date. Suggest that the user make them rules, for example with `/improve-kitchen`.
- **Watch out**: what you learned the hard way that no file records.
- **Skills**: the skills the next shift should load.

### 4. Leave the station

Stop your watch, since only one watch runs per state file and the incoming session must start its own. Then give the user the note's path and one line: open a new session and run `/shift-change take over <path>` in it.

Done when the note exists, your watch is stopped, and the user has the path.

## Taking over

1. **Read** the note, then `docs/agents/roles.md` and the files it points to for your station. The note is a snapshot: before acting on a ticket it lists, read that ticket's latest comments.
2. **Sign in**: put your session name in your station's row of the Current sessions table in `docs/agents/roles.md`, the way this repo changes its rules. Tell each peer station your session name in one line.
3. **Start your watch** as `docs/agents/watch.md` says, and check `ding night show`.
4. **Pick up the open work** in the note's order, each ticket from its latest comment.

Done when the table names your session, your watch runs, and you have read the latest state of every ticket the note lists.
