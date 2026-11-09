"""Reference runner: one spec in, one resumable run out. Read it for the logic; write the repo's own runner from it.

Usage: python runner.py SPEC.toml

Each part below is one of the hard parts, in the order a run meets them: run identity, the single writer, dispatch
with commit on completion, resume, failures, and progress and summary. Everything else a real runner needs (spec
schema checks, the service layer, rules, a cost ledger) is left out on purpose.

Spec:
    experiment = "toy"                 # names the work; shown on `ding board`
    output = "outputs/toy/first_run"   # one run per folder; changed on purpose -> a new folder
    concurrency = 4                    # operational: outside the run identity
    passes = 1
    inputs = ["data/extra.json"]       # files whose content the results depend on
    [items]
    source = "data/items.json"         # a JSON list of objects, each with a unique string "id"
    [[arms]]
    name = "A"
    task = "toy_task:run"              # module:function, called as run(item, ctx) -> dict
    args = {style = "short"}           # every parameter lives here, never in the task's code

Exit codes: 0 every item succeeded; 1 the run finished with failed items; 2 the run stopped before finishing.
"""

from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import importlib
import inspect
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import traceback
from urllib.parse import quote

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

ATTEMPTS = 3  # per item and per job, counting the first
OPERATIONAL = {"concurrency", "output"}  # spec keys that change how a run goes, not what it computes
SPEC_KEYS = {"experiment", "output", "concurrency", "passes", "inputs", "items", "arms"}
ARM_KEYS = {"name", "task", "args"}


class StopRun(Exception):
    """Raised by a task function when going on would be wrong for every item, such as an authentication error."""


class RunError(Exception):
    """The run cannot start or go on; the originals are kept as they are."""


@dataclass
class Context:
    """What a task function gets besides its item. It never sees the output folder: the runner owns every write."""

    arm: str
    args: dict
    pass_number: int
    attempt: int
    log: list = field(default_factory=list)  # task events, kept in the item's result


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_atomic(path: Path, data: dict) -> None:
    """Write a whole file or nothing: a temp file in the same folder, flushed to disk, then renamed over the target."""
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=1)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


# --- Run identity ---------------------------------------------------------------------------------------------------


def load_spec(path: Path) -> dict:
    spec = tomllib.loads(path.read_text(encoding="utf-8"))  # tomllib already rejects duplicate keys
    unknown = set(spec) - SPEC_KEYS | {key for arm in spec.get("arms", []) for key in set(arm) - ARM_KEYS}
    if unknown:
        raise RunError(f"unknown spec keys: {', '.join(sorted(unknown))}")
    if not spec.get("arms") or "source" not in spec.get("items", {}) or "output" not in spec:
        raise RunError("a spec needs output, items.source, and at least one arm")
    return spec


def task_function(reference: str):
    module_name, _, name = reference.partition(":")
    return importlib.import_module(module_name), name


def identity(spec: dict) -> dict:
    """Config digest plus input digests. Content, never paths or times, so a copied or touched file is still the same.

    Inputs are the item source, the spec's own inputs, and each task module's INPUTS: every text file it reads that a
    model sees or that changes its results, including templates it reads indirectly."""
    config = {key: value for key, value in spec.items() if key not in OPERATIONAL}
    files = [spec["items"]["source"], *spec.get("inputs", [])]
    for arm in spec["arms"]:
        files += getattr(task_function(arm["task"])[0], "INPUTS", [])
    inputs = {}
    for name in sorted(set(files)):
        try:
            inputs[name] = digest(Path(name).read_bytes())
        except OSError as error:
            raise RunError(f"input {name}: {error}") from error
    return {"config": digest(json.dumps(config, sort_keys=True).encode()), "inputs": inputs}


def code_version(spec: dict) -> dict:
    """What a segment records: the commit, and a digest of the task modules for changes not yet committed."""
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        commit = None
    sources = sorted({inspect.getsourcefile(task_function(arm["task"])[0]) for arm in spec["arms"]})
    return {"commit": commit, "tasks": digest(b"".join(Path(source).read_bytes() for source in sources))}


def bind(output: Path, spec: dict, say) -> int:
    """Start a run, or check that this job continues the run already in `output`. Returns the segment number.

    A different identity stops here, before any task runs. Different code only starts a new segment and warns:
    code may change in place, and every result records the segment that produced it."""
    wanted, version = identity(spec), code_version(spec)
    record_path = output / "run.json"
    if not record_path.exists():
        write_atomic(record_path, {"identity": wanted, "segments": [{**version, "started": now()}]})
        return 0
    record = json.loads(record_path.read_text(encoding="utf-8"))
    if record["identity"] != wanted:
        changed = ["config"] if record["identity"]["config"] != wanted["config"] else []
        changed += sorted(
            name
            for name in {*record["identity"]["inputs"], *wanted["inputs"]}
            if record["identity"]["inputs"].get(name) != wanted["inputs"].get(name)
        )
        raise RunError(
            f"{output} holds a different run (changed: {', '.join(changed)}); "
            "for an intended change, use a new output folder"
        )
    last = record["segments"][-1]
    if {key: last.get(key) for key in version} != version:
        say(
            f"warning: code changed since segment {len(record['segments']) - 1} "
            f"({last.get('commit')} -> {version['commit']}); continuing as a new segment"
        )
        record["segments"].append({**version, "started": now()})
        write_atomic(record_path, record)
    return len(record["segments"]) - 1


# --- One writer -----------------------------------------------------------------------------------------------------


def lock(output: Path):
    """Hold an exclusive lock on the output folder for the whole job. The OS drops it when the process dies, even
    on SIGKILL, so a crash never leaves a stale lock behind."""
    handle = open(output / ".lock", "w")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as error:
        raise RunError(f"another job is writing {output}") from error
    return handle


# --- Resume ---------------------------------------------------------------------------------------------------------


def plan(spec: dict) -> list[tuple[str, dict, dict, int]]:
    """Every (key, item, arm, pass) of the run, in spec order: pass, then item, then arm."""
    items = json.loads(Path(spec["items"]["source"]).read_text(encoding="utf-8"))
    ids = [item["id"] for item in items]
    if len(set(ids)) != len(ids) or not all(isinstance(value, str) and value for value in ids):
        raise RunError("item ids must be unique non-empty strings")
    return [
        (f"{arm['name']}--{number}--{quote(item['id'], safe='')}", item, arm, number)
        for number in range(1, spec.get("passes", 1) + 1)
        for item in items
        for arm in spec["arms"]
    ]


def committed(results: Path) -> dict[str, dict]:
    """The results already on disk. A file that does not parse stops the run: it is evidence, not something to redo."""
    found = {}
    for path in results.glob("*.json"):
        try:
            found[path.stem] = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as error:
            raise RunError(f"corrupt result {path}; keep it and find out why") from error
    for leftover in results.glob(".*.tmp"):  # a write cut off by a kill; its result was never committed
        leftover.unlink()
    return found


# --- Failures -------------------------------------------------------------------------------------------------------


def attempt(item: dict, arm: dict, number: int, earlier: int) -> dict:
    """Run one item on a worker thread, retrying the same input; return the result to commit. A failure is a result
    too: it stays in the run, counts as wrong in the evaluation, and is retried by the next job."""
    module, name = task_function(arm["task"])
    for count in range(earlier + 1, earlier + ATTEMPTS + 1):
        context = Context(arm=arm["name"], args=dict(arm.get("args", {})), pass_number=number, attempt=count)
        try:
            output = getattr(module, name)(item, context)
            return {"status": "succeeded", "attempts": count, "output": output, "log": context.log}
        except StopRun:
            raise
        except Exception as error:  # noqa: BLE001 - any error of one item is that item's failure
            failure = {
                "status": "failed",
                "attempts": count,
                "error": type(error).__name__,
                "message": str(error),
                "traceback": traceback.format_exc(),
                "log": context.log,
            }
    return failure


# --- Progress and summary -------------------------------------------------------------------------------------------


class Stopped(Exception):
    """SIGINT or SIGTERM arrived; turned into an exception so the summary still gets written."""


def on_signal(number, frame):
    raise Stopped(signal.Signals(number).name)


def run(spec_path: Path) -> int:
    sys.path.insert(0, os.getcwd())  # task modules import from the repo root, where the job starts
    started, log, holder = time.time(), None, None
    counts = {"succeeded": 0, "failed": 0, "resumed": 0}
    state, reason, output, total, failures, segments = "interrupted", "", None, 0, [], []

    def say(line: str) -> None:
        print(line, file=sys.stderr)  # logs go to stderr; stdout stays for machine-readable output
        if log:
            log.write(f"{now()} {line}\n")
            log.flush()

    def progress() -> None:
        done = counts["succeeded"] + counts["failed"]
        fresh = done - counts["resumed"]
        hours = (time.time() - started) / 3600
        rate = fresh / hours if hours and fresh else None
        eta = (
            (datetime.now(timezone.utc) + timedelta(hours=(total - done) / rate)).strftime("%Y-%m-%dT%H:%M:%SZ")
            if rate and state == "running"
            else None
        )
        write_atomic(
            output / "progress.json",
            {  # the progress-v1 shape `ding board` reads; display only
                "schema": "progress-v1",
                "state": state,
                "stage": spec.get("experiment", "run"),
                "current": {"name": "items", "done": done, "total": total, "failed": counts["failed"]},
                "rate_per_hour": rate,
                "eta": {"utc": eta} if eta else None,
                "updated": {"utc": now()},
            },
        )

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    try:
        spec = load_spec(spec_path)
        output = Path(spec["output"])
        (output / "results").mkdir(parents=True, exist_ok=True)
        holder = lock(output)
        log = open(output / "runner.log", "a", encoding="utf-8")  # appended to across resumes
        segment = bind(output, spec, say)
        work = plan(spec)
        total, done = len(work), committed(output / "results")
        todo = [entry for entry in work if done.get(entry[0], {}).get("status") != "succeeded"]
        counts["resumed"] = counts["succeeded"] = total - len(todo)
        say(f"segment {segment}: {total} items, {counts['resumed']} already committed, {len(todo)} to do")
        state = "running"
        progress()
        with ThreadPoolExecutor(max_workers=spec.get("concurrency", 1)) as pool:
            queue, running = iter(todo), {}
            try:
                while True:
                    # Keep at most `concurrency` items in flight and commit each the moment it finishes, so a slow
                    # item never holds back the commits, progress, or speed of the items behind it.
                    while len(running) < spec.get("concurrency", 1) and (entry := next(queue, None)):
                        earlier = done.get(entry[0], {}).get("attempts", 0)
                        running[pool.submit(attempt, entry[1], entry[2], entry[3], earlier)] = entry
                    if not running:
                        break
                    finished, _ = wait(running, return_when=FIRST_COMPLETED)
                    for future in finished:
                        key, item, arm, number = running.pop(future)
                        result = future.result()  # re-raises StopRun here, on the one thread that writes
                        result.update(
                            key=key,
                            item=item["id"],
                            arm=arm["name"],
                            pass_number=number,
                            segment=segment,
                            committed=now(),
                        )
                        write_atomic(output / "results" / f"{key}.json", result)
                        counts[result["status"]] += 1
                        if result["status"] == "failed":
                            say(
                                f"{key} failed after {result['attempts']} attempts: {result['error']}: "
                                f"{result['message']}"
                            )
                        progress()
            finally:
                # On a stop, nothing new starts. The pool still waits for the items already running, and drops their
                # results: they were never committed, so the next job does them again.
                for future in running:
                    future.cancel()
        state = "completed"
    except StopRun as error:
        state, reason = "stopped", f"stop_run: {error}"
    except Stopped as error:
        state, reason = "interrupted", f"signal: {error}"
    except RunError as error:
        state, reason = "refused", str(error)
    except Exception as error:  # noqa: BLE001 - any other error still writes the summary
        state, reason = "interrupted", f"{type(error).__name__}: {error}"
        traceback.print_exc()
    finally:
        if output is not None and output.exists() and state != "refused":
            # The summary counts what is on disk, sorted into spec order only now: the disk is the run.
            results = committed(output / "results") if (output / "results").exists() else {}
            failures = sorted(
                (value for value in results.values() if value.get("status") == "failed"), key=lambda value: value["key"]
            )
            counts["succeeded"] = sum(value.get("status") == "succeeded" for value in results.values())
            counts["failed"] = len(failures)
            if (output / "run.json").exists():
                segments = json.loads((output / "run.json").read_text(encoding="utf-8"))["segments"]
            progress()
            write_atomic(
                output / "summary.json",
                {
                    "state": state,
                    "stop_reason": reason,
                    "total": total,
                    "succeeded": counts["succeeded"],
                    "failed": counts["failed"],
                    "pending": total - counts["succeeded"] - counts["failed"],
                    "resumed": counts["resumed"],
                    "elapsed_seconds": round(time.time() - started, 1),
                    "failed_items": [
                        {key: value[key] for key in ("key", "error", "message", "attempts")} for value in failures
                    ],
                    "segments": segments,
                    "output": str(output.resolve()),
                },
            )
        say(f"{state}: {reason}" if reason else state)
        if holder:
            holder.close()
    if state == "completed":
        return 1 if counts["failed"] else 0
    return 2


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    return run(Path(sys.argv[1]))


if __name__ == "__main__":
    # Run main() from the importable module, not from __main__: a task function that does `from runner import
    # StopRun` would otherwise get a second copy of the class, and `except StopRun` here would never catch it.
    from runner import main as module_main

    raise SystemExit(module_main())
