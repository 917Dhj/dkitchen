---
name: shift-change
description: Hand a dkitchen role over to a fresh session. Run it in the outgoing session to write the handover note, then in the incoming session with "take over <note>" to pick up from it.
argument-hint: "take over <note path>, or what the next shift should focus on"
disable-model-invocation: true
---

# Shift change

A role's session gets replaced when its context fills up or the user wants a fresh one. The outgoing chef writes a handover note and leaves the role in order; the incoming chef takes over from the note and the sources it points to.

Run without an argument, or with what the next shift should focus on, to **hand over**. Run with `take over <note path>` to **take over**.

An executor does not use this skill: its ticket already holds the whole story, and a new executor takes the ticket with `ding new --issue <ticket> --replace`.

## Handing over

### 1. Gather

From the sources, not from memory:

- your role, and the peer roles: `ding role` lists each role with the id of the session holding it;
- `ding board`, and the open tickets you own or that wait on you (`gh issue list`, the `status:*` labels);
- your watch's command and state file, your other background tasks, and jobs you started;
- open night orders: `ding night show`;
- decisions the user made in this conversation, and instructions the user gave you here that no file records.

Done when you can name every open ticket that needs your role, everything you have running, and every user decision from this conversation.

### 2. Put on the tickets what belongs there

A user decision given only in this conversation goes on its ticket now, verbatim, as the Asking the user section of `docs/agents/roles.md` says. The note then links to it rather than carrying it.

Done when every user decision from step 1 is on a ticket or listed for the note's own section below.

### 3. Write the note

Write it to `/tmp/dkitchen-handoff/<repo name>/<role>-<UTC time>.md`, outside the repo. Link to what tickets, commits, and docs already hold rather than copying it, and leave out secrets such as keys and passwords. The note holds:

- **Role**: the role, the repo, and the focus the user gave, if any.
- **Peers**: the peer roles by name, not session names or ids. The incoming session finds each holder with `ding role <peer>` when it needs it.
- **Open work**: one line per ticket: its link, its state, the next step, and who takes it.
- **Running**: the watch command, background tasks, and jobs, each with how to check it.
- **Night orders**: the link to open orders, or "none".
- **Not yet in the rules**: standing instructions the user gave in this conversation, verbatim with their date. Suggest that the user make them rules, for example with `/improve-kitchen`.
- **Watch out**: what you learned the hard way that no file records.
- **Skills**: the skills the next shift should load.

### 4. Leave the role

Stop your watch, since only one watch runs per state file and the incoming session must start its own. If it is still running when the incoming session takes the role, it exits on its own at its next poll. Then give the user the note's path and one line: open a new session and run `/shift-change take over <path>` in it.

Done when the note exists, your watch is stopped, and the user has the path.

## Taking over

1. **Read** the note, then `docs/agents/roles.md` and the files it points to for your role. The note is a snapshot: before acting on a ticket it lists, read that ticket's latest comments.
2. **Sign in**: run `ding role take <role>` in this session, before starting your watch. It records this session's id as the role's holder; the previous holder's watch, if still running, exits on its own. Peers find you with `ding role <role>`, so there is nothing to tell them.
3. **Start your watch** as `docs/agents/watch.md` says, and check `ding night show`. If it says another watch is using its state file, the previous holder's watch has not reached its next poll yet; start yours again after it exits.
   To message a peer role, run `ding role <peer> --to` and send with `SendMessage`, `to` set to what it prints. Look it up again for each send, and reply to an incoming message's `from`. Never use a session name or an address from the note.
4. **Pick up the open work** in the note's order, each ticket from its latest comment.

Done when `ding role <role>` prints your session's id, your watch runs, and you have read the latest state of every ticket the note lists.
