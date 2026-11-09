# dkitchen

dkitchen runs a repo's work through a team of agent sessions coordinated on GitHub issues, with the user as head chef. These are the words its rules, skills, and `ding` share.

## The team

**Kitchen**:
The installed set of house rules, settings, and repo scripts that lets a team of agent sessions work on one repo.
_Avoid_: Workflow, setup

**Station**:
A role in the kitchen, filled by one agent session at a time: the orchestrator, a designer, the verifier, or an executor.
_Avoid_: Agent, role, seat

**Design line**:
One designer station and the tickets it owns, when a kitchen splits design between several designers.
_Avoid_: Sub-designer, design track

**Verifier**:
The station that checks a ticket's facts against the code and data, and reviews PRs by default, without making decisions.
_Avoid_: Checker, reviewer (when the station is meant)

**Shift change**:
Replacing the session that fills a station with a fresh one, carried over by a handover note.
_Avoid_: Handoff (Matt Pocock's skill of that name is general-purpose)

## Work

**Ticket**:
A GitHub issue that holds one piece of work: its task, decisions, requests, and results.
_Avoid_: Task, job, issue (when the unit of work is meant)

**Gate**:
An exit condition of a ticket, judged by a number or a command and reported as one row of the gate table.
_Avoid_: Criterion, acceptance check

**Night orders**:
The user's approvals for a stretch of time away, posted on the orchestrator log ticket and valid only until they end.
_Avoid_: Overnight approvals, standing orders

**Known situation**:
A recurring situation with a recorded rule that the orchestrator and verifier follow without asking the designer.
_Avoid_: Precedent, playbook entry

## Guarding the repo

**Check**:
An automated gate in code or CI that a change must pass, such as a layout rule, a lint, or the tests.
_Avoid_: Verification, validation (verification is the verifier's work)

**Area**:
A set of repo paths that hold one kind of thing — library, tools, experiments, tests, docs, outputs, assets, or vendor — and so follow that kind's rules.
_Avoid_: Category, folder type, zone

**Guard change**:
A change to a check, its configuration, or CI, which must say why in a `Guard-change:` commit trailer.
_Avoid_: Check tweak

## Skills

**Build skill**:
A skill that installs or changes one part of the kitchen and can run again to update it in place.
_Avoid_: Setup skill (that name belongs to the entry, `setup-dkitchen`)

**Everyday skill**:
A skill the stations use while the kitchen runs, such as writing a ticket or a shift change.
_Avoid_: Runtime skill
