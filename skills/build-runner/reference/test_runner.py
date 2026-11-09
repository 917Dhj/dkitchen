"""The five behaviours every runner must keep, run against the reference runner with the toy task function.

A repo's own runner gets the same tests in its tests area, pointed at its own entry point."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
RUNNER = HERE / "runner.py"


def kitchen(tmp_path: Path, items: list[dict], concurrency: int = 2, args: str = 'style = "short"') -> Path:
    """A scratch repo root with the toy task, its template, the items, and a spec."""
    shutil.copy(HERE / "toy_task.py", tmp_path / "toy_task.py")
    (tmp_path / "template.txt").write_text("{id} in {style} form\n", encoding="utf-8")
    (tmp_path / "items.json").write_text(json.dumps(items), encoding="utf-8")
    spec = tmp_path / "spec.toml"
    spec.write_text(
        f'experiment = "toy"\noutput = "outputs/toy/run"\nconcurrency = {concurrency}\n'
        f'[items]\nsource = "items.json"\n[[arms]]\nname = "A"\ntask = "toy_task:run"\nargs = {{{args}}}\n',
        encoding="utf-8",
    )
    return spec


def start(spec: Path) -> subprocess.Popen:
    # Run with `python runner.py`, not `-m`, so its own folder is on the path for `from runner import StopRun`.
    return subprocess.Popen(
        [sys.executable, str(RUNNER), spec.name],
        cwd=spec.parent,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={"PYTHONPATH": str(HERE), "PATH": "/usr/bin:/bin"},
    )


def finish(spec: Path) -> subprocess.CompletedProcess:
    job = start(spec)
    stdout, stderr = job.communicate(timeout=60)
    return subprocess.CompletedProcess(job.args, job.returncode, stdout, stderr)


def results(spec: Path) -> dict[str, dict]:
    folder = spec.parent / "outputs/toy/run/results"
    return {path.stem: json.loads(path.read_text()) for path in folder.glob("*.json")}


def summary(spec: Path) -> dict:
    return json.loads((spec.parent / "outputs/toy/run/summary.json").read_text())


def test_a_killed_run_resumes_without_losing_or_repeating_items(tmp_path):
    spec = kitchen(tmp_path, [{"id": str(number), "sleep": 0.3} for number in range(12)])
    job = start(spec)
    deadline = time.time() + 30
    while len(results(spec)) < 3 and time.time() < deadline:
        time.sleep(0.05)
    job.send_signal(signal.SIGKILL)
    job.wait()
    before = results(spec)
    assert 3 <= len(before) < 12

    done = finish(spec)

    assert done.returncode == 0, done.stderr
    after = results(spec)
    assert len(after) == 12 and all(value["status"] == "succeeded" for value in after.values())
    assert all(after[key] == value for key, value in before.items()), "a committed result was redone"
    assert summary(spec)["resumed"] == len(before) and summary(spec)["succeeded"] == 12


def test_a_changed_parameter_stops_before_dispatch_and_keeps_the_originals(tmp_path):
    spec = kitchen(tmp_path, [{"id": "a"}, {"id": "b"}])
    assert finish(spec).returncode == 0
    output = tmp_path / "outputs/toy/run"
    before = {path: path.read_bytes() for path in output.rglob("*.json")}
    spec.write_text(spec.read_text().replace('style = "short"', 'style = "long"'))

    done = finish(spec)

    assert done.returncode == 2 and "different run (changed: config)" in done.stderr
    assert {path: path.read_bytes() for path in output.rglob("*.json")} == before


def test_a_changed_input_file_stops_before_dispatch(tmp_path):
    spec = kitchen(tmp_path, [{"id": "a"}])
    assert finish(spec).returncode == 0
    (tmp_path / "template.txt").write_text("{id}, reworded for {style}\n")

    done = finish(spec)

    assert done.returncode == 2 and "changed: template.txt" in done.stderr


def test_changed_code_resumes_as_a_new_segment_with_a_warning(tmp_path):
    spec = kitchen(tmp_path, [{"id": str(number)} for number in range(4)])
    assert finish(spec).returncode == 0
    (tmp_path / "outputs/toy/run/results/A--1--3.json").unlink()  # one item left to do
    task = tmp_path / "toy_task.py"
    task.write_text(task.read_text() + "\n# a bug fix that changes nothing a model sees\n")

    done = finish(spec)

    assert done.returncode == 0, done.stderr
    assert "warning: code changed since segment 0" in done.stderr
    assert "warning: code changed" in (tmp_path / "outputs/toy/run/runner.log").read_text()
    assert len(json.loads((tmp_path / "outputs/toy/run/run.json").read_text())["segments"]) == 2
    assert results(spec)["A--1--3"]["segment"] == 1 and results(spec)["A--1--0"]["segment"] == 0


def test_a_failing_item_is_recorded_and_the_run_finishes(tmp_path):
    spec = kitchen(tmp_path, [{"id": "a"}, {"id": "b", "fail": True}, {"id": "c"}])

    done = finish(spec)

    assert done.returncode == 1
    record = summary(spec)
    assert record["state"] == "completed" and record["succeeded"] == 2 and record["failed"] == 1
    assert record["failed_items"] == [
        {"key": "A--1--b", "error": "ValueError", "message": "item b fails on purpose", "attempts": 3}
    ]
    assert "Traceback" in results(spec)["A--1--b"]["traceback"]
    assert finish(spec).returncode == 1 and results(spec)["A--1--b"]["attempts"] == 6  # a rerun retries it


def test_a_slow_item_does_not_hold_back_the_commits_behind_it(tmp_path):
    spec = kitchen(tmp_path, [{"id": "slow", "sleep": 2}, *({"id": str(number)} for number in range(8))])
    assert finish(spec).returncode == 0
    found = results(spec)
    assert sum(value["committed"] < found["A--1--slow"]["committed"] for value in found.values()) == 8


def test_stop_run_stops_everything_and_the_summary_says_why(tmp_path):
    spec = kitchen(
        tmp_path, [{"id": "a"}, {"id": "b", "stop": True}, *({"id": str(n), "sleep": 0.5} for n in range(6))]
    )

    done = finish(spec)

    assert done.returncode == 2
    record = summary(spec)
    assert record["state"] == "stopped" and "the service refused our key" in record["stop_reason"]
    assert record["pending"] > 0


def test_sigterm_still_writes_the_summary(tmp_path):
    spec = kitchen(tmp_path, [{"id": str(number), "sleep": 0.5} for number in range(6)], concurrency=1)
    job = start(spec)
    deadline = time.time() + 30
    while not results(spec) and time.time() < deadline:
        time.sleep(0.05)
    job.send_signal(signal.SIGTERM)
    job.wait(timeout=30)
    assert job.returncode == 2
    record = summary(spec)
    assert record["state"] == "interrupted" and record["stop_reason"] == "signal: SIGTERM"
    progress = json.loads((tmp_path / "outputs/toy/run/progress.json").read_text())
    assert progress["schema"] == "progress-v1" and progress["state"] == "interrupted"


def test_a_second_job_on_the_same_output_is_refused(tmp_path):
    spec = kitchen(tmp_path, [{"id": str(number), "sleep": 0.5} for number in range(4)], concurrency=1)
    first = start(spec)
    deadline = time.time() + 30
    while not (tmp_path / "outputs/toy/run/run.json").exists() and time.time() < deadline:
        time.sleep(0.05)
    second = finish(spec)
    first.communicate(timeout=60)
    assert second.returncode == 2 and "another job is writing" in second.stderr
    assert first.returncode == 0
