---
name: build-team
description: Build or change the team of a dkitchen kitchen in this repo — its roles, design lines, tickets, PR review, watches, run budgets, and model-visible text rules. Use when the user asks to set up the kitchen's team, add or split a designer, or change how the roles work together.
---

# Build the team

Install the kitchen's team into the kitchen: the house rules under `docs/agents/` from [kitchen/team/](../../kitchen/team/), the pointer blocks, the team's keys in `.dkitchen.toml`, the repo scripts under `scripts/`, and the status labels. The kitchen is the current repo, or, when its `.dkitchen.toml` sets `code`, a kitchen repo of its own, where all of these go ([Installing](../../kitchen/README.md#installing)). Tailor each rule to what this repo really does rather than copying it.

Follow [Installing](../../kitchen/README.md#installing) for the prerequisites, language, rendering, updating in place, pointer blocks, and approval. When `/setup-dkitchen` brought you here, the prerequisites and the language are already settled: skip them.

## Sources

- **Templates**: [kitchen/team/](../../kitchen/team/), mapped to their installed paths in [kitchen/README.md](../../kitchen/README.md#layout).
- **Reference repo scripts**: [scripts/](scripts/) in this skill. Each starts with a comment listing what to adapt.
- **`ding`**: `ding --help`, and [docs/ding.md](../../docs/ding.md), including the `.dkitchen.toml` keys.

## 1. Explore

- **Prerequisites and language**, unless already settled.
- **Installed team**: `docs/agents/` and `.dkitchen.toml`, read in full when present, since this run then updates them.
- **The work**: the README, the main code, how tests run (CI files, `pyproject.toml`, `package.json`, `Makefile`), and the CI check names a merge should require.
- **Design areas**: the distinct kinds of design the work needs, such as evaluation and training, or a model and the product around it. Each needs its own context, decisions, and tickets.
- **Module signals**:
  - `run-budgets`: GPU training or evaluation scripts, API keys or clients for model providers, cost or token accounting.
  - `model-text`: prompt files or folders, request templates, tool or function schemas, code that renders chat messages.
- **How the code repo takes contributions**: its `CONTRIBUTING.md`, `.github/pull_request_template.md`, and issue templates, and its last ten merged PRs (`gh pr list --repo <code repo> --state merged --limit 10 --json title,body,headRefName`): title format, body sections, how a PR links what it fixes, and branch names.
- **Resources**: `nvidia-smi` or the equivalent, other hosts mentioned in docs or SSH config, shared services such as model servers and the tunnels to them.

Done when you can name, with evidence, every existing file you would touch, the repo's test command, the design areas, and a recommendation for each module.

## 2. Present the findings

Summarize what is present and what is missing in a short list, ending with your recommendations for the sections below.

## 3. Settle each section

Ask the sections as rounds, as [Installing](../../kitchen/README.md#installing) says, and skip any section that exploration already settled. B's details for each extra line wait for B's answer, and E and F wait for D, since the modules chosen decide which gaps and scripts exist.

**A. Roles.** The kitchen has an orchestrator, a designer, a verifier, and executors. Ask which model each Claude Code role runs; the defaults are the strongest available model for the orchestrator and designer and a cheaper one for the verifier.

**B. Design lines.** One designer holds every design area in one context. When the areas from exploration would crowd that context, recommend a separate design line for each area that has its own decisions and tickets, such as "a training designer owns the training data, training configs, and the evaluation of trained models". When the user agrees, settle for each extra line:

- its role name and signature, and any alias executors may write;
- which tickets are its own: a parent ticket and everything under it, or a `Design: <line>` second line;
- what it decides, and what it asks the other lines for.

With one designer, say so and move on.

**C. What stays with the user.** The roles template's list is generic: the project's direction, what the work is judged against, and what is claimed or shipped in the user's name. Propose it in this repo's terms from exploration, such as the research direction, how datasets are used, and what the paper claims for a research repo, or the product roadmap, the acceptance tests, and what is released for a product, and ask what to add or remove. The answer fills that gap in `roles.md`, and the night shift's hard stops point at it.

**D. Modules.** One question per module, each recommended from its signals:

| Module | Recommend when |
| --- | --- |
| `run-budgets` | The repo runs models on GPUs or calls paid APIs |
| `model-text` | The repo studies or depends on what models are told: prompts, tool definitions, request templates |

**E. Resources.** Fill the `<!-- fill: … -->` gaps of the chosen templates: hosts and GPUs and how to tell one is free, shared services with their owners and tunnels, the tier limits and timezone for `run-budgets` (defaults: 50 light-tier calls, 500 pre-approved calls), where prompts live for `model-text`. Propose values from exploration and let the user correct them.

**F. Repo scripts.** Propose how `scripts/review_pr.py` runs this repo's tests and prepares a trial-merge worktree, and which module scripts to install: `check_requests.py` and `check_prompt_in_issue.py` for `model-text`. For `run-budgets`, a ledger script only if the repo already saves per-request receipts; otherwise drop the ledger section.

**G. Contributing.** Propose the conventions for `contributing.md` from what exploration found, and only those: a convention the code repo does not have stays out. In a kitchen of its own, also settle which PRs may go ready on a ticket's advance approval when the code repo is shared.

Done when every section has an answer from the user, or was settled by exploration and you said so.

## 4. Draft and confirm

Show the user:

- the files to create or change, with the full text of each new `docs/agents/` file and a diff for each existing file;
- the team's `.dkitchen.toml` keys: the vocabulary, including `[merge] review_pass`, `review_changes`, `[review] verdict_pass`, `verdict_changes`, `notify`, `[watch] handoff`, and `[outbound] user_decision` for a language other than English; each design line's name in `[roles.aliases]` and `[rule] signatures`; `[merge] review_check = "review"`, so that merges need the reviewer's verdict; and `[merge] required_checks` with the CI checks a merge needs. A shared code repo needs neither `[merge]` key: its verdicts go on tickets and its team merges;
- the adapted repo scripts;
- the GitHub changes: the four `status:*` labels from [issue-tracker.md](../../kitchen/team/issue-tracker.md), in the kitchen repo;
- an optional `.claude/settings.json` allow list for the commands the roles run all day: `ding *`, `gh issue *`, `gh pr *`, and the repo scripts.

Done when the user approves the draft, including each GitHub change by name.

## 5. Write

Apply exactly the approved draft.

- **Rules**: render with `--templates team` and the chosen modules, plus `split` and `shared` as [Installing](../../kitchen/README.md#installing) says, then fill and translate. Write each design line into the Design lines section of `roles.md` and a row per line into the table in `watch.md`; with one designer, remove that section.
- **Pointer blocks**, **settings**, and **scripts**: write them as approved.
- **GitHub**: create the labels with `gh label create` in the kitchen repo.

Done when every approved file exists with its approved content and every approved GitHub change is made.

## 6. Verify

Run the checks in [Installing](../../kitchen/README.md#installing), then:

- `ding board --status` runs in the repo, and `ding watch --help` prints help.
- Each installed script runs with `--help`, and `scripts/review_pr.py` imports cleanly.
- `gh label list --search status:` shows the four labels.

Done when every check passes, or the user has been told exactly which one fails and why.

## 7. Hand over

Tell the user, briefly:

1. which sessions to open: the orchestrator, each designer line, and the verifier in Claude Code; executors in Codex, one per ticket, each in its own worktree. In a kitchen of its own, the Claude Code roles open in the kitchen's checkout and executors in worktrees of the code repo;
2. that the first session in each role runs `ding role take <role>` before starting its watch, so peers find it with `ding role <role>`; the session names can go into the table at the top of `docs/agents/roles.md` for people to read;
3. that each Claude Code role starts its watch at session start, as `docs/agents/watch.md` says;
4. how to start: describe the first piece of work to the designer, who writes it as a ticket with `write-ticket`;
5. that `/shift-change` hands a role over to a fresh session when its context fills up.
