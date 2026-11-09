---
name: build-repo
description: Build or change the code rules and checks of a dkitchen kitchen in this repo — the areas code goes in, changing modules in place, reuse, and the ding check gates in CI. Use when the user asks to set up repo rules, add or change a check, or stop the repo from filling up with copies.
---

# Build the repo rules

Install the rules that keep the repo from filling up with copies: `docs/agents/code.md` from [kitchen/repo/](../../kitchen/repo/), its pointer line, the `[check]` table in `.dkitchen.toml`, the Ruff and import-linter settings in `pyproject.toml`, and a CI workflow that runs `ding check` and the tests on every PR. An executor is a fresh session every time; when it cannot find the module to change, it writes a new copy. These rules make changing the module in place the only path that passes, from the first PR.

The checks are preventive: they hold from the first PR, with no baseline and no exception list. Layout rules look only at what a PR adds, so existing files never turn CI red. Ruff and the import contracts look at the whole tree, so the existing violations they find are cleaned up first, in a ticket of their own, before those checks are switched on.

Follow [Installing](../../kitchen/README.md#installing) for the prerequisites, language, rendering, updating in place, pointer blocks, and approval. When `/setup-dkitchen` brought you here, the prerequisites and the language are already settled: skip them. The checks themselves are `ding check` and `ding map` ([docs/ding.md](../../docs/ding.md#repo-checks)).

## Sources

- **Template**: [kitchen/repo/code.md](../../kitchen/repo/code.md).
- **Reference files**: [templates/](templates/) in this skill: the CI workflow and the `pyproject.toml` tables. Each starts with a comment listing what to adapt.

## 1. Explore

- **The team**: `docs/agents/roles.md` and `docs/agents/reviewing.md` must exist, since the guard-change rule relies on the PR reviewer. When they are missing, stop and offer [build-team](../build-team/SKILL.md) first.
- **Python**: the reference checks need a Python repo (`pyproject.toml`, `setup.py`, or Python packages). For another language, install only `code.md` and the layout checks (`[check]` with `ruff = false` and `imports = false`), and tell the user that lint and import contracts need their language's own tools.
- **Installed rules**: `docs/agents/code.md`, `[check]` and `[merge]` in `.dkitchen.toml`, `[tool.ruff]` and `[tool.importlinter]` in `pyproject.toml`, and `.github/workflows/`, read in full when present.
- **Layout**: every top-level folder and file; where the packages live (a flat or a `src/` layout); test files and where they sit; output folders and whether `.gitignore` covers them; third-party code and submodules.
- **Commands**: how the repo installs and runs its tests, and the Python version it targets.
- **Existing violations**, counted without changing anything:
  - `ruff check --select F,E9,B006,B008,B011,B012,B018,B023,PGH004 .` and `ruff format --check .`;
  - `lint-imports --config <a scratch file>` with the contract drafted in section B;
  - the layout rules on files already in the repo: version copies (`_v2`), ticket numbers in paths, code in docs, misplaced tests. These never fail a PR, but a cleanup ticket can clear them.

Done when every top-level folder has a proposed area, and you can name the test command, the Python version, and the count of each kind of existing violation.

## 2. Present the findings

Summarize the layout, the proposed areas, and the existing violations by kind, with a few examples of each.

## 3. Settle each section

One section, one answer, then the next. Lead each with your recommendation.

**A. Areas.** Show each top-level folder with its proposed area, as a table: library, tools, experiments, tests, docs, outputs, assets, or vendor. Every folder gets one; there is no "other". A folder whose contents are mixed goes to the area most of it belongs to, and the rest becomes part of the cleanup. List the top-level files the usual names do not cover ([the usual names](../../docs/ding.md#repo-checks)); each one is either listed in `root_files` or moved.

**B. Import contract.** Recommend one forbidden contract: the library packages import no experiment, tool, test, or doc packages. Offer more layers only when the library already has a clear one, such as a core package the rest builds on.

**C. Existing violations.** For each check with violations, recommend one of two paths: fix them in this run when they are few and mechanical, such as a one-time `ruff format`; otherwise switch that check off (`ruff = false` or `imports = false`) and open a cleanup ticket with `write-ticket`, which switches it on when it lands. Never write an exception list.

**D. Reuse.** Ask which library module holds each shared component, such as durable writes, progress bars, or model clients, so `code.md` can point executors at it.

**E. CI.** Propose the Python version, the install command, and the test command for the workflow, and the `[merge] required_checks` entries: `checks` and `tests`.

Done when every section has an answer.

## 4. Draft and confirm

Show the user:

- the full text of `docs/agents/code.md` (a diff when updating), and the new pointer blocks;
- `[check]` and `[merge] required_checks` for `.dkitchen.toml`;
- the `pyproject.toml` tables, adapted from the reference, and `ruff` and `import-linter` added to the dev dependencies;
- the CI workflow, adapted from the reference, as `.github/workflows/dkitchen.yml`;
- the fixes made in this run, and the GitHub change by name: each cleanup ticket.

Done when the user approves the draft, including each cleanup ticket.

## 5. Write

Render with `--templates repo`, as [Installing](../../kitchen/README.md#installing) says, then fill and translate. Rewrite both pointer blocks from what `render.py` prints. Write the settings, the `pyproject.toml` tables, and the workflow; make the approved fixes; open the cleanup tickets.

When the repo already had `[check]`, the change is a guard change: the commit carries `Guard-change: #<ticket> <reason>`.

Done when every approved file exists with its approved content and every cleanup ticket is open.

## 6. Verify

Run the checks in [Installing](../../kitchen/README.md#installing), then:

- `ding check --base HEAD` passes on the working tree, with the switches as approved.
- `ding map` lists the library modules.
- A scratch file `<library>/scratch_v2.py` makes `ding check --base HEAD` fail with `version-copy`; delete it afterwards.

Done when every check passes, or the user has been told exactly which one fails and why.

## 7. Hand over

Tell the user, briefly: every PR now runs `checks` and `tests`, and a merge needs both; executors run `ding check` before handing over; `ding map` finds the module to change; a change to a check carries a `Guard-change:` trailer; and a lesson that keeps coming back can become a check of its own, a script listed in `[check] commands`.
