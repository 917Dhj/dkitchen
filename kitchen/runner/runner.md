# Runs

Read this before writing or starting a run: an evaluation, batch inference, or any work done item by item.

## One runner

Every new run goes through the runner: <!-- fill: the runner's command, such as `python -m pkg.runner <spec>` -->. A run is a spec plus a task function; changing a parameter changes only the spec. Start it with `ding launch`, passing `--progress <output>/progress.json` so `ding board` shows it ([long-running-jobs.md](long-running-jobs.md)).

When the runner cannot express the work, say in the ticket what it is missing, and extend the runner; a second runner needs the designer's ruling on the ticket. Scripts written before the runner keep working as they are.

## The spec

<!-- fill: the spec fields this repo's runner takes, one line each, with an example spec; the spec format, such as TOML. -->

Every parameter lives in the spec: items, arms, model and generation settings, thresholds. The task function reads them from `ctx.args`, never from its own constants. The spec goes in the study's folder, `<study>/`, next to its task functions.

## Task functions

`run(item, ctx) -> dict` does one item of one arm and returns its result. It:

- declares in `INPUTS` every file it reads whose content changes its results, such as a prompt template, including files it reads indirectly;
- leaves every write under the output folder to the runner;
- raises on a failed item, so the runner can retry and record it; it raises `StopRun` only when going on would be wrong for every item, such as an authentication error.

<!-- fill: how a task function reaches a model or service, such as ctx.client(name), and where the registry of services lives; or remove this paragraph. Model and service names appear only in that registry: the check `<check script>` fails an experiment file that names one. -->

## Run identity

A run's identity is its spec's configuration and the content of its inputs. Concurrency and the output folder stay outside it<!-- fill: any other field this repo's runner leaves outside identity; or remove -->.

- **A changed identity** stops the job before any item starts, and the output stays as it was. For an intended change, use a new output folder, `<study>/<run>/`, where `<run>` names what varies.
- **Changed code** does not stop it: the job continues as a new segment in `run.json` and warns in the log. Every result records its segment, so the report can list the items each commit produced.

## Resuming

Rerun the original command. The runner skips committed items and does the rest, including the failed ones.

- An item has up to 3 attempts per job. One that still fails is recorded with its error and traceback, and the run goes on. A failed item counts as wrong and stays in the denominator; report it separately.
- `summary.json` is written however the run ends. It lists the counts, the failed items by error, the segments, and why the run stopped.

| Ending | `state` | Exit code |
| --- | --- | --- |
| Every item committed | `completed` | 0, or 1 with failed items |
| A task raised `StopRun` | `stopped` | 2 |
| A signal or an unexpected error | `interrupted` | 2 |
| Another run's output, a corrupt result, or another job writing | `refused`, with no summary | 2 |

A refused or stopped run is reported on the ticket with its reason, as `blocked`. A corrupt result file is kept and investigated, never deleted to make the run pass.
