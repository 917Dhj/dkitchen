# Long-running jobs

Start every CPU, GPU, or API job that runs in tmux with `ding launch`, however short you expect it to be. It opens tmux session `ding-NAME`, reads the session's `CODEX_THREAD_ID`, and wraps the job with `ding run`; when the job exits, it wakes the session that launched it.

```bash
ding launch issue42-stage1 --message "$message" --record /absolute/path/task-exit.jsonl -- env OMP_NUM_THREADS=8 bash /absolute/path/task.sh
```

After launching, end your turn: the job's exit wakes you. Look at progress only when the user asks.

Add `--progress /absolute/path/progress.json` so a hung job shows on the board and wakes the orchestrator once its progress stops moving for `[watch] stale_minutes` (default 30), and `--expect-hours H` so a job running past `[watch] overrun_factor` × H (default 1.5) wakes it once. Both wake the orchestrator, not you, and a job with neither is never reported while it runs.

- **Environment**: tmux carries over only `PATH`, `HOME`, `PYTHONPATH`, `XDG_STATE_HOME`, and the session ID. Pass anything else the job needs as `env K=V` in the command.
- **After exit**: the tmux session closes itself, however the job ended. Its output and errors are in the log the wake-up names; read it there.
- **Unwrapped jobs**: the end of `ding board` lists tmux jobs on this host that have run for over 10 minutes without `ding`. The orchestrator asks the executor that owns one to relaunch it with `ding launch`.
- **Missed wake-ups**: the wrapper killed with SIGKILL, a host reboot, or a job that hangs. The wake-up comes once, when the job exits, so follow-up messages are never queued in advance.
- **Several App Servers**: add `--socket PATH` before the `--`. For another host, SSH there first.

## Resumable jobs

Every long job is resumable: rerunning the original command continues it. This is what lets the kitchen recover from a crash or reboot without asking anyone.

- A result counts only once it is durably on disk, written atomically. A killed job loses no committed result and counts none twice.
- On resume, the job first checks that its inputs and config still match the existing outputs. On a mismatch or corrupt output, it keeps the originals and stops with a clear error. Otherwise it skips committed results and redoes only unfinished work.
- A clear failure of one sample is final: record it, move on, and keep it in the evaluation's denominator. Service, environment, resource, and unknown failures are retried a bounded number of times, then the job pauses with the work left pending, ready for a rerun.

## Compute

<!-- fill: the hosts and GPUs this repo may use, how to tell a GPU is free on each, and which GPUs belong to other people. -->

Other users' processes are never touched. Processes under our own account are ours, but before stopping one, confirm it is not another ticket's job.

## Storage

Every host the repo uses has the same roots, so where a file goes is never an agent's choice. A worktree holds code only.

| Root | What goes there | Rule |
| --- | --- | --- |
| `models/` | Weights: downloaded models, and adapters or merged weights kept as baselines | One copy per host. Code and configs point here; nothing copies weights into a checkout or a run |
| `datasets/` | Raw data and derived formats, such as a trainer's prepared cache | A derived format is a named dataset with the command that builds it, built once per host and shared by every ticket |
| `envs/` | Environments | One per purpose, shared |
| `code/<repo>@<commit>/` | Code on a host where runs start without a worktree | Unpacked read-only from a commit and shared by every ticket at that commit |
| `runs/<study>/<run>/` | Results kept after the ticket: predictions, scores, summaries, small adapters | Named for what varies, never for the ticket. The repo's outputs folder in every checkout and worktree is a symlink to this root |
| `scratch/<ticket>/` | Everything else a run writes: staging, checkpoints, model caches, `TMPDIR` | Deleted in full when the ticket closes |

<!-- fill: the absolute path of each root on each host, and the free space each host keeps in reserve. -->

- **Starting a run** sets `TMPDIR`, the model hub's cache, and the run's scratch folder to `scratch/<ticket>/`, and reads weights only from `models/`. A training run deletes its resume checkpoints when it finishes successfully; only the final weights stay, in `runs/`.
- **Another host**: a run on a host without its own worktrees goes through one wrapper script. The wrapper unpacks the commit into `code/`, points outputs at `runs/` and caches at `scratch/<ticket>/`, maps model and data paths to that host's roots, and refuses to start when the host's free space is below the run request's Disk line plus the reserve. Agents never create checkouts or clones on another host. <!-- fill: the wrapper and how to call it, or remove this item when the repo uses one host. -->
- **Disk gate**: the `[launch] preflight` in `.dkitchen.toml` refuses a local launch when the host's free space is below the reserve.
- **Closing a ticket**: before the ticket closes, its executor posts one storage line per host, listing each worktree, scratch folder, and run folder the ticket left with its size, and what happens to it: kept in `runs/`, promoted to `models/` or `datasets/`, or deleted. Scratch and the worktree are always deleted; deleting a run folder is the designer's call. The orchestrator closes the ticket only once that line is carried out.

## Shared services

<!-- fill: a table of shared services (model servers, databases, tunnels) with columns Service | Where | Owner, and the command that checks their load, if the repo has one. -->

- **Restarts and parameter changes** of shared services are the user's. Before one, the clients are told to stop at a checkpoint with SIGINT; afterwards they resume with their original commands.
- **Tunnels**: when a tunnel is down, the orchestrator, or the executor that needs it, reopens it. <!-- fill: where tunnels run and the command for each. -->
- **A host reboot** takes the tmux jobs and tunnels with it, and `ding run` has no chance to write exit records: the job's exit record is empty and its process is gone. Reopen the tunnels first, then have each ticket resume with its original command.
