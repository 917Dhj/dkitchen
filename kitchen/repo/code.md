# Code

Read this before writing or changing code. `ding check` enforces most of it, and CI runs it on every PR.

## Where code goes

The repo is split into areas, set under `[check]` in `.dkitchen.toml`. Every file belongs to one area, and each area holds one kind of thing:

| Area | Paths | What goes there |
| --- | --- | --- |
| Library | <!-- fill: library paths --> | Shared code: one module per concept, named for the concept, in one current version |
| Tools | <!-- fill: tools paths --> | Workflow tools that only make sense in this repo, run from the repo root |
| Experiments | <!-- fill: experiments paths --> | One folder per study, `<study>/`, holding its entry points and configs. A study is a line of work that spans tickets; a ticket continuing a study reuses its folder. Study folders are snake_case and hold an `__init__.py` |
| Tests | <!-- fill: tests paths --> | `<package>/test_<behaviour>.py`, mirroring the code they test |
| Docs | <!-- fill: docs paths --> | Prose only |
| Outputs | <!-- fill: outputs paths --> | Run outputs, kept out of Git, as `<study>/<run>/` where `<run>` names what varies |
| Assets | <!-- fill: assets paths --> | Material that is not code: configs, prompts, data, schemas |
| Vendor | <!-- fill: vendor paths --> | Other people's code, changed only by updating it from its source |

<!-- fill: remove the rows of kinds this repo does not use. -->

A new file goes into an area. A new top-level folder goes into an area under `[check]` first; a new top-level file is one of the usual ones, such as `README.md` or `pyproject.toml`, or listed in `[check] root_files`.

## Change it in place

Name things by what they are. A ticket number goes in the commit message or metadata, never in a path. A concept has one module and one current version: to change what it does, change that module. Find it with `ding map`, which lists every library module with the first line of its docstring, and start every new library module with a docstring whose first line says what it is for.

## Reuse

Shared components live in the library, and are extended there. An experiment imports them and never carries its own copy. <!-- fill: which library module holds which shared component, such as durable writes, progress, or model clients; or remove this sentence. -->

The library imports no experiments, tools, tests, or docs. The import contracts in `pyproject.toml` hold this line.

## Verifying a change

- Pick the smallest check that covers what the change touches: the tests of the files changed, and the paths between modules when the change crosses them. Run the whole suite only when the change crosses packages or the ticket asks for it.
- Reuse a check you already ran while the code, inputs, configuration, and environment it depends on are unchanged; after a later edit, rerun only what that edit affects.
- Report what you ran, its result, and what stayed unchecked.

## Checks

Every PR runs two CI jobs, `checks` (`ding check`) and `tests`, and a merge needs both green. Run `ding check` yourself before handing a PR over.

- The checks hold from the first PR, with no baseline and no exception list. When a check fails, fix the code.
- A change to a check needs a commit trailer `Guard-change: #<ticket> <reason>`. The checks are `[check]` and `[merge]` in `.dkitchen.toml`, `[tool.ruff]` and `[tool.importlinter]` in `pyproject.toml`, the CI workflow, and the repo's own check scripts. The PR's reviewer checks the reason, and loosening a check also needs the designer's reason on the ticket.
- A lesson that keeps coming back becomes a check: a script in the tools area, listed in `[check] commands`. It receives `--base <commit>` and exits nonzero on a violation.

<!-- fill: for a repo with existing violations, which checks stay off until which cleanup ticket lands; or remove this comment. -->
