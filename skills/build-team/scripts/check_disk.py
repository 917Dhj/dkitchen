#!/usr/bin/env python3
"""Refuse a launch that would fill a disk or write results into a checkout: the `[launch] preflight` for storage.

Usage: scripts/check_disk.py --reserve-gb GB [--outputs DIR] [PATH...]

Each PATH, the launch directory by default, must sit on a filesystem with at least GB free. With --outputs,
the repo's outputs folder must be missing or a symlink, so results land in the host's runs root and not in the
worktree. Exits 1 when a check fails. Under `ding launch`, the readings go to $DING_PREFLIGHT_RECEIPT.
"""
# dkitchen reference script for the storage rules in long-running-jobs.md. Adapt when installing:
# - the reserve for each host, passed in [launch] preflight in .dkitchen.toml;
# - the outputs folder's name, when the repo has one.
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess

GB = 1024 ** 3


def repo_root(cwd: Path) -> Path:
    result = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=cwd, capture_output=True, text=True)
    return Path(result.stdout.strip()) if result.returncode == 0 and result.stdout.strip() else cwd


def disk_problems(paths: list[Path], reserve_gb: float) -> tuple[list[dict], list[str]]:
    readings, problems = [], []
    for path in paths:
        free_gb = shutil.disk_usage(path).free / GB
        readings.append({"path": str(path), "free_gb": round(free_gb, 1), "reserve_gb": reserve_gb})
        if free_gb < reserve_gb:
            problems.append(f"{path}: {free_gb:.0f} GB free, below the {reserve_gb:g} GB reserve; free space first "
                            "(docs/agents/long-running-jobs.md, Storage)")
    return readings, problems


def outputs_problem(root: Path, outputs: str) -> str | None:
    folder = root / outputs
    if folder.exists() and not folder.is_symlink():
        return (f"{folder} is a real folder; make it a symlink to the host's runs root and move its contents there "
                "(docs/agents/long-running-jobs.md, Storage)")
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reserve-gb", type=float, required=True, help="free space each path's disk must keep")
    parser.add_argument("--outputs", help="the repo's outputs folder, relative to the repo root")
    parser.add_argument("paths", nargs="*", type=Path, help="paths to check; the launch directory by default")
    args = parser.parse_args(argv)
    cwd = Path(os.environ.get("DING_LAUNCH_CWD") or Path.cwd())
    readings, problems = disk_problems(args.paths or [cwd], args.reserve_gb)
    if args.outputs and (problem := outputs_problem(repo_root(cwd), args.outputs)):
        problems.append(problem)
    for reading in readings:
        print(f"check_disk: {reading['path']}: {reading['free_gb']:.0f} GB free, reserve {reading['reserve_gb']:g} GB")
    for problem in problems:
        print(f"check_disk: refused: {problem}")
    if receipt := os.environ.get("DING_PREFLIGHT_RECEIPT"):
        Path(receipt).write_text(json.dumps({"disks": readings, "problems": problems}, indent=2) + "\n")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
