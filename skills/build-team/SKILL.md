---
name: build-team
description: Build or change the team of a dkitchen kitchen in this repo — its roles, design lines, tickets, PR review, watches, run budgets, and model-visible text rules. Use when the user asks to set up the kitchen's team, add or split a designer, or change how the roles work together.
---

# Build the team

Install the kitchen's team into the current repo: the house rules under `docs/agents/` from [kitchen/team/](../../kitchen/team/), the pointer blocks, the team's keys in `.dkitchen.toml`, the repo scripts under `scripts/`, and the status labels. Tailor each rule to what this repo really does rather than copying it.

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
- **Resources**: `nvidia-smi` or the equivalent, other hosts mentioned in docs or SSH config, shared services such as model servers and the tunnels to them.

Done when you can name, with evidence, every existing file you would touch, the repo's test command, the design areas, and a recommendation for each module.

## 2. Present the findings

Summarize what is present and what is missing in a short list, ending with your recommendations for the sections below.

## 3. Settle each section

One section, one answer, then the next. Lead each with your recommendation so the user can accept it in a word, and skip any section that exploration already settled.

**A. Roles.** The kitchen has an orchestrator, a designer, a verifier, and executors. Ask which model each Claude Code role runs; the defaults are the strongest available model for the orchestrator and designer and a cheaper one for the verifier.

**B. Design lines.** One designer holds every design area in one context. When the areas from exploration would crowd that context, recommend a separate design line for each area that has its own decisions and tickets, such as "a training designer owns the training data, training configs, and the evaluation of trained models". When the user agrees, settle for each extra line:

- its role name and signature, and any alias executors may write;
- which tickets are its own: a parent ticket and everything under it, or a `Design: <line>` second line;
- what it decides, and what it asks the other lines for.

With one designer, say so and move on.

**C. What stays with the user.** Show the default list from the roles template (research direction, how datasets are used, what the paper claims, spending beyond a ticket's budget) and ask what to add or remove. For a repo that is not a research project, rewrite the first three in the repo's own terms.

**D. Modules.** Recommend each from its signals, as a multi-select:

| Module | Recommend when |
| --- | --- |
| `run-budgets` | The repo runs models on GPUs or calls paid APIs |
| `model-text` | The repo studies or depends on what models are told: prompts, tool definitions, request templates |

**E. Resources.** Fill the `<!-- fill: … -->` gaps of the chosen templates: hosts and GPUs and how to tell one is free, shared services with their owners and tunnels, the tier limits and timezone for `run-budgets` (defaults: 50 light-tier calls, 500 pre-approved calls), where prompts live for `model-text`. Propose values from exploration and let the user correct them.

**F. Repo scripts.** Propose how `scripts/review_pr.py` runs this repo's tests and prepares a trial-merge worktree, and which module scripts to install: `check_requests.py` and `check_prompt_in_issue.py` for `model-text`. For `run-budgets`, a ledger script only if the repo already saves per-request receipts; otherwise drop the ledger section.

Done when every section has an answer from the user, or was settled by exploration and you said so.

## 4. Draft and confirm

Show the user:

- the files to create or change, with the full text of each new `docs/agents/` file and a diff for each existing file;
- the team's `.dkitchen.toml` keys: the vocabulary, including `[merge] review_pass`, `review_changes`, and `[watch] handoff` for a language other than English; each design line's name in `[stations.aliases]` and `[rule] signatures`; `[merge] review_check = "review"`, so that merges need the reviewer's verdict; and `[merge] required_checks` with the CI checks a merge needs;
- the adapted repo scripts;
- the GitHub changes: the four `status:*` labels from [issue-tracker.md](../../kitchen/team/issue-tracker.md);
- an optional `.claude/settings.json` allow list for the commands the roles run all day: `ding *`, `gh issue *`, `gh pr *`, and the repo scripts.

Done when the user approves the draft, including each GitHub change by name.

## 5. Write

Apply exactly the approved draft.

- **Rules**: render with `--templates team` and the chosen modules, as [Installing](../../kitchen/README.md#installing) says, then fill and translate. Write each design line into the Design lines section of `roles.md` and a row per line into the table in `watch.md`; with one designer, remove that section.
- **Pointer blocks**, **settings**, and **scripts**: write them as approved.
- **GitHub**: create the labels with `gh label create`.

Done when every approved file exists with its approved content and every approved GitHub change is made.

## 6. Verify

Run the checks in [Installing](../../kitchen/README.md#installing), then:

- `ding board --status` runs in the repo, and `ding watch --help` prints help.
- Each installed script runs with `--help`, and `scripts/review_pr.py` imports cleanly.
- `gh label list --search status:` shows the four labels.

Done when every check passes, or the user has been told exactly which one fails and why.

## 7. Hand over

Tell the user, briefly:

1. which sessions to open: the orchestrator, each designer line, and the verifier in Claude Code; executors in Codex, one per ticket, each in its own worktree;
2. to put those session names into the table at the top of `docs/agents/roles.md`;
3. that each Claude Code role starts its watch at session start, as `docs/agents/watch.md` says;
4. how to start: describe the first piece of work to the designer, who writes it as a ticket with `write-ticket`;
5. that `/shift-change` hands a role over to a fresh session when its context fills up.
