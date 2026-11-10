<p align="center">
  <img src="https://raw.githubusercontent.com/917Dhj/dkitchen/main/docs/assets/dkitchen.png" width="240" alt="Two pixel-art robot chefs: the big one rings a service bell, the small one answers with a pan">
</p>

<h1 align="center">dkitchen</h1>

<p align="center">
  <b>English</b> | <a href="https://github.com/917Dhj/dkitchen/blob/main/README.zh-CN.md">简体中文</a>
</p>

<p align="center">
  <b>You decide what to cook. Your agents run the kitchen.</b> 🧑‍🍳
</p>

<p align="center">
  <a href="https://pypi.org/project/dkitchen/"><img src="https://img.shields.io/pypi/v/dkitchen" alt="PyPI"></a>
  <a href="https://pypi.org/project/dkitchen/"><img src="https://img.shields.io/pypi/pyversions/dkitchen" alt="Python"></a>
  <a href="https://github.com/917Dhj/dkitchen/actions/workflows/tests.yml"><img src="https://github.com/917Dhj/dkitchen/actions/workflows/tests.yml/badge.svg" alt="Tests"></a>
  <a href="https://github.com/917Dhj/dkitchen/blob/main/LICENSE"><img src="https://img.shields.io/github/license/917Dhj/dkitchen" alt="License"></a>
  <a href="https://x.com/dahuoji09"><img src="https://img.shields.io/badge/follow-%40dahuoji09-000000?logo=x" alt="X: @dahuoji09"></a>
</p>

dkitchen is the multi-agent workflow I use every day to run my research repo. It gives a set of Claude Code and Codex sessions fixed roles, a shared way to hand off work through GitHub issues, clear rules for when to stop and ask you, and the tools that tie it together. You keep the decisions only you can make: what to research, what to try, what to spend.

## 🍽️ Why a kitchen

AI agents made execution cheap. The bottleneck moved to you.

With one agent, you supervise every step. With several, you become the message bus: copying context between sessions, checking whether a job finished, remembering which session owns which task, approving small things all day. Your GPUs sit idle between runs because nobody noticed the last one ended. By evening you have touched everything and thought about nothing.

A Michelin kitchen solves the same problem. The head chef designs the menu and tastes the dishes. Everyone else has a station, every order is a ticket, and a bell rings when a dish is ready. The head chef never chops onions, and never loses track of the kitchen.

dkitchen sets up your agents the same way. You are the head chef.

## 🧑‍🍳 The kitchen

<p align="center">
  <img src="https://raw.githubusercontent.com/917Dhj/dkitchen/main/docs/assets/kitchen.webp" width="100%" alt="A pixel-art kitchen: you agree a plan with the designer, the orchestrator rings the bell to start a Codex executor on free GPUs, an executor asks the designer directly, the verifier reviews a PR and the orchestrator merges it; then you go to bed, the kitchen keeps cooking on your night orders, and in the morning it brings you one decision">
</p>

| Role | In a kitchen | What it does | Runs on |
| --- | --- | --- | --- |
| 👑 **You** | Head chef | Choose the direction, approve designs and budgets, decide what the results mean for your paper. | You |
| 🤖 **Orchestrator** | Sous chef at the pass | Schedules tickets, GPUs, and concurrency. Merges PRs, closes tickets, reports facts to you. | Claude Code · Claude Opus 5.5 |
| 🤔 **Designer** | Recipe developer | Writes tickets, designs methods and every piece of text a model will see, interprets results. | Claude Code · Claude Opus 5.5 |
| 🔍 **Verifier** | Taster | Spot-checks finished runs and outputs against code and data, and reviews PRs. Reports what it found and never makes the call. | Claude Code · Claude Sonnet 5.5 |
| 🔪 **Executors** | Line cooks | One fresh session per ticket, in its own worktree. Implements, runs, and reports on the ticket. | Codex · GPT-6.1 Sol |

Each role has written rules for what it owns, what it hands off, and when it must stop. When something fits no role, the agents ask you.

## 🎫 How a ticket moves through the kitchen

1. **You and the designer agree on what to do.** The designer writes it up as a GitHub issue: the goal, the exact steps, a gate table that says when the work is done, and an estimate of what it will spend.
2. **The orchestrator dispatches it** to a new executor session and picks free GPUs.
3. **The executor checks the ticket's premises** against the code and data before it starts, and hands the ticket back to the designer when one does not hold.
4. **The executor works and reports on the ticket.** Every comment opens with the same four lines: status, who it is waiting on, the key numbers, and what happens next. Long jobs start with `ding launch`; when the job exits, `ding` wakes the executor so it can read the output and continue.
5. **Results go straight to the designer** for interpretation. The verifier reviews the PR, commit by commit; once the review and CI pass, the orchestrator merges it.
6. **You read a short report** and make the next call.

Every decision, request, and result lives on a ticket, so any session (or you, a week later) can pick up the story from GitHub.

## ✋ What stays with you

The rules write down which calls belong to the head chef:

- the research direction, how datasets are used, and what the paper claims;
- with the run-budgets module, each ticket's budget, approved once; a change of model or endpoint; and service starts.

Agents propose on these and wait. An approval only counts when it is in your own words. Neither the orchestrator nor the designer can approve on your behalf.

Everything else the kitchen handles on its own, by one rule: **if anyone would do it the same way, the agents do it. If the choice changes the results, the cost, or the direction, they stop and wait for you.**

This is what lets you walk away. While you are in class, asleep, or reading papers, each role's watch wakes it when work reaches it: an executor finishes a stage, gets stuck, or goes quiet; you leave a comment; a PR is ready. Before you leave, `/goodnight` collects the approvals the night may need; the orchestrator moves forward what they cover, and `/goodmorning` brings you the decisions that are left.

## ⚖️ One pool of resources

A research repo has more resources than any single agent sees: GPUs on several servers, a shared model server, CPU time, an API budget, tokens, and hours in the day. In dkitchen the orchestrator, running on the strongest model you have, manages them as one pool.

- 🖥️ **Compute.** It schedules tickets across free GPUs and checks the shared model server's load before raising concurrency.
- 💰 **Money.** Each ticket that runs models carries one approved estimate for calls, cost, and GPU hours. Runs report against it and warn once when the projection passes 1.5 times the estimate; only runaway spend stops a run.
- 🪙 **Tokens.** One session per ticket keeps each context small, and fact-checking runs on a cheaper model.
- ⏱️ **Time.** Jobs wake their owner when they exit, so nothing waits for someone to look.

## 🧰 The tools

### 🛎️ `ding`, the bell

`ding` passes messages between agent sessions and wakes a session when its long job ends.

```bash
ding new --cwd . --issue 42 --name 'Ablation' --message-file brief.md   # start a Codex session for #42; prints its UUID
ding board                                            # who is working on what, in this repo
ding send '#42' --from orchestrator --message-file note.md
ding launch train -- python train.py                  # run in tmux, wake me when it exits
```

You can address a session by its UUID, its name, or a GitHub issue such as `'#42'`; `ding` finds the session that owns that ticket. On Linux, `ding board` also lists long-running processes that were started without `ding`, so you can spot jobs nobody will be woken for.

`ding` talks to Codex sessions through the Codex App Server. The full guide is in [docs/ding.md](https://github.com/917Dhj/dkitchen/blob/main/docs/ding.md).

### 📋 The kitchen's routines

The roles' everyday steps are `ding` commands too, so they run the same careful way every time:

- `ding relay` sends a message to a ticket's executor, and records it on the ticket only once delivery is confirmed.
- `ding review` records a verdict on the current PR HEAD. With `[merge] review_check`, `ding merge`, `ding watch`, and `ding waits` share PR readiness checks; every merge requires the default target branch. See [the review and merge guide](docs/ding.md).
- `ding watch` waits in each role's background and wakes it when a ticket needs it.
- `ding waits` lists overdue unanswered waits, including ones still pending after a prior watch batch.
- `ding log` keeps the orchestrator's log of what it did while you were away.
- `ding night` opens, shows, and closes time-limited night orders on that log. Run `/goodnight` and `/goodmorning` in the orchestrator session to collect the orders and report their use.
- `ding check-refs` checks every file, line, and digest the verifier cites.
- `ding check` runs the repo's checks on every PR, and `ding map` lists the library's modules, so a change goes to the module that already exists.

### 📜 The house rules

The rules every role follows live in [kitchen/](https://github.com/917Dhj/dkitchen/blob/main/kitchen/README.md), one folder per part of the kitchen: the team (who owns what, tickets, reviews, when to stop and ask, with optional modules for run budgets and model prompts), the repo's code rules and checks, the runner, and the night shift for when you are away. The rules guard what comes next rather than clean up the past, and a change to a check says why in a `Guard-change:` commit trailer.

### 🧩 The skills

The plugin installs ten skills. The build skills set up one part of the kitchen each and can run again to update it:

| Skill | What it does |
| --- | --- |
| `/setup-dkitchen` | The entry: checks the prerequisites, settles the language and what you need, and walks through the build skills below |
| `build-team` | The roles, tickets, PR review, and watches; it can suggest extra design lines for a repo with several kinds of work |
| `build-repo` | Where code goes, changing modules in place, and the `ding check` gates in CI (Python repos) |
| `build-runner` | One resumable runner for work done item by item, such as evaluations and batch inference (Python repos) |
| `build-night` | Night orders and the orchestrator's log, so work keeps moving while you are away |

The everyday skills run while the kitchen works:

| Skill | When |
| --- | --- |
| `write-ticket` | Every time a role writes a ticket; the model reaches for it on its own |
| `/shift-change` | When a role's session is replaced by a fresh one |
| `/improve-kitchen` | Every couple of weeks: turns what keeps going wrong into checks, tools, or rules, and retires the text they replace |
| `/goodnight`, `/goodmorning` | Before you leave and when you are back |

## 🚀 Get started

### Requirements

- Linux or another POSIX system, with `tmux`
- Python 3.10 or later
- A GitHub repo and the `gh` CLI
- Claude Code, and Codex with its App Server running under the same user

### 1. Install `ding`

```bash
pipx install dkitchen
```

### 2. Add the skills to Claude Code

```bash
claude plugin marketplace add 917Dhj/dkitchen
claude plugin install dkitchen@dkitchen
```

### 3. Set up your kitchen

In Claude Code, inside your repo, run:

```text
/setup-dkitchen
```

The skill reads your repo to learn what you work on and what you already have: agent instructions, tests, GPUs, model calls, long jobs. It checks the prerequisites, settles the language, and asks which parts you need: the team, the code rules, the runner, the night shift. Then it walks through each part's build skill, which asks its own questions one at a time and shows you every rule, script, and GitHub change before writing anything. Run it again any time to change the setup.

Upgrading from 0.5? Read *Upgrading* in the [changelog](https://github.com/917Dhj/dkitchen/blob/main/CHANGELOG.md) first.

## ❓ FAQ

**Is it safe to let agents run unattended?**
They stop for anything that changes direction, results, or spending, and approvals only come from your own words on a ticket. Every action is a comment or a PR on GitHub, so you can audit the night's work over coffee.

**Will it fit my repo?**
The rules were written for computational research, and most of them carry over to any repo with long-running jobs. The setup skill adapts them to your repo. The team and the night shift fit a repo in any programming language; the code checks and the runner are for Python repos.

**Do I need both Claude Code and Codex?**
For now, yes. That is the combination I run every day.

**My repo already has plenty of code that breaks the rules. Will CI turn red?**
No. The layout checks look only at the files a PR adds, so existing code never fails them. Ruff and the import rules look at the whole tree, so for each one with existing violations, `build-repo` either fixes them in the same run, when they are few and mechanical, or leaves that check off and opens a cleanup ticket that switches it on. There is no baseline and no exception list: both only grow.

**Isn't this too much process for a small project?**
The orchestrator, designer, and verifier always come together; the code rules, the runner, and the night shift are each optional. The rules cover only what every kitchen needs, and `/improve-kitchen` grows the rest from what actually goes wrong in yours.

## 💡 About

The *d* is my mark. dkitchen is how I run my own kitchen, written down so you can run yours. It started in my research repo, which moved 171 issues and 111 merged PRs through this workflow in its first four weeks.

The Michelin kitchen metaphor comes from Lauren Tan, known online as [Poteto](https://github.com/poteto). Poteto's way of running agents inspired much of this workflow. The way tickets live on GitHub issues started from the issue tracker setup in [Matt Pocock's skills](https://github.com/mattpocock/skills). Thank you both. 🙏

## License

[MIT](https://github.com/917Dhj/dkitchen/blob/main/LICENSE)
