"""Repo checks: layout rules on what a change adds, then whole-tree tools and the repo's own checks.

- check: compare --base with the working tree (tracked files, plus untracked ones Git does not ignore). Layout rules
  apply to added files only; Ruff, the import contracts, and the repo's own commands look at the whole tree; a change
  to a check needs a Guard-change trailer. Exits 1 on any problem, 2 when the check cannot run.
- map: each Python module under an area, with the first line of its docstring.
The areas and switches come from the [check] table of .dkitchen.toml.
"""
from __future__ import annotations

import ast
from fnmatch import fnmatch
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from dkitchen.config import FILE, Check, Config

ROOT_FILES = ("README*", "LICENSE*", "COPYING*", "NOTICE*", "CHANGELOG*", "CONTRIBUTING*", "CODE_OF_CONDUCT*",
              "SECURITY*", "CITATION*", "AGENTS.md", "CLAUDE.md", "GLOSSARY.md", "GLOSSARY-MAP.md", "pyproject.toml",
              "setup.py", "setup.cfg", "MANIFEST.in", "requirements*.txt", "*.lock", "Makefile", "Dockerfile",
              "environment.yml", "tox.ini", "noxfile.py", "conftest.py")
CODE = {".py", ".pyi", ".ipynb", ".sh", ".bash", ".zsh", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".c", ".cc",
        ".cpp", ".h", ".hpp", ".rs", ".go", ".java", ".r", ".jl", ".lua", ".pl", ".rb"}
TICKET = re.compile(r"(?i)(?:^|[^a-z])(?:issue|ticket)[-_]?\d+")
VERSION = re.compile(r"(?i)(?:^|[_-])v\d+(?=$|[_.-])")
SNAKE = re.compile(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*")
TRAILER = re.compile(r"#?\d+\s+\S")
STANDARD = "docs/agents/code.md"


class CheckError(RuntimeError):
    """The check could not run."""


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-c", "core.quotePath=false", *args], cwd=root, capture_output=True, text=True)
    if result.returncode:
        raise CheckError(f"git {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout


def paths(output: str) -> list[str]:
    return sorted(filter(None, output.split("\0")))


def untracked(root: Path) -> list[str]:
    return paths(git(root, "ls-files", "--others", "--exclude-standard", "-z"))


def finding(path: str, rule: str, message: str, line: int | None = None) -> dict:
    return {"file": path, "line": line, "rule": rule, "message": message}


def area_of(path: str, areas: dict[str, str]) -> str | None:
    """The longest area path that holds `path`."""
    holding = [area for area in areas if path == area or path.startswith(area + "/")]
    return max(holding, key=len) if holding else None


def is_test(name: str) -> bool:
    return name.endswith(".py") and (name.startswith("test_") or name.endswith("_test.py"))


def docstring_line(source: str) -> str | None:
    """The first line of a module's docstring; None when it has none or does not parse."""
    try:
        docstring = ast.get_docstring(ast.parse(source))
    except SyntaxError:
        return None
    return docstring.strip().splitlines()[0].strip() if docstring and docstring.strip() else None


def layout(root: Path, base: str, check: Check) -> list[dict]:
    """Layout rules on every file the working tree adds against `base`."""
    added = sorted(set(paths(git(root, "diff", "--name-only", "-z", "--no-renames", "--diff-filter=A", base, "--")))
                   | set(untracked(root)))
    areas = check.areas()
    tops = {area.split("/")[0] for area in areas}
    allowed = ROOT_FILES + check.root_files
    base_dirs = set(git(root, "ls-tree", "-r", "-d", "--name-only", base).splitlines())
    tree = set(paths(git(root, "ls-files", "-z"))) | set(untracked(root))
    findings, studies = [], set()
    for path in added:
        parts = PurePosixPath(path).parts
        name = parts[-1]
        if parts[0].startswith("."):
            continue
        if len(parts) == 1:
            if not any(fnmatch(name, pattern) for pattern in allowed):
                findings.append(finding(path, "root-file", "a new top-level file; put it in an area, or list it in "
                                        f"[check] root_files"))
            continue
        area = area_of(path, areas)
        if area is None:
            if parts[0] not in tops:
                findings.append(finding(path, "top-level-dir", f"{parts[0]}/ is in no area; use an existing area, or "
                                        f"add the folder to one in [check]"))
            else:
                findings.append(finding(path, "no-area", "in no area; move it into one, or add its folder to an area "
                                        "in [check]"))
            continue
        kind = areas[area]
        relative = PurePosixPath(path).relative_to(area).parts
        suffix = PurePosixPath(name).suffix.lower()
        if kind == "vendor":
            continue
        if kind == "outputs":
            findings.append(finding(path, "output-tracked", "outputs stay out of Git; add the folder to .gitignore"))
            continue
        if TICKET.search(path):
            findings.append(finding(path, "ticket-in-path", "name it for what it is; the ticket number goes in the "
                                    "commit message or metadata"))
        if kind in {"library", "tools"} and VERSION.search(PurePosixPath(name).stem):
            findings.append(finding(path, "version-copy", "change the existing module instead of adding a version "
                                    "copy"))
        if kind in {"docs", "assets"} and suffix in CODE:
            findings.append(finding(path, "code-in-docs", f"{kind} holds no code; move it into the library, tools, "
                                    "or experiments area"))
        if is_test(name) and (kind != "tests" or len(relative) < 2 or not re.fullmatch(r"test_\w+\.py", name)):
            tests = check.tests[0] if check.tests else "tests"
            findings.append(finding(path, "test-placement", f"tests go in {tests}/<package>/test_<behaviour>.py, "
                                    "mirroring the code they test"))
        if kind == "experiments" and len(relative) >= 2 and relative[0] not in studies:
            study = relative[0]
            studies.add(study)
            if f"{area}/{study}" not in base_dirs and (
                    not SNAKE.fullmatch(study) or f"{area}/{study}/__init__.py" not in tree):
                findings.append(finding(f"{area}/{study}", "study-layout", "a new study folder is snake_case and "
                                        "holds an __init__.py"))
        if kind == "library" and suffix == ".py":
            source = (root / path).read_text(encoding="utf-8", errors="replace")
            if source.strip() and docstring_line(source) is None:
                findings.append(finding(path, "module-docstring", "start the module with a docstring whose first "
                                        "line says what it is for", 1))
    return findings


def toml_at(root: Path, revision: str | None, name: str) -> dict:
    """A TOML file at a revision, or in the working tree when revision is None; empty when it is missing."""
    if revision is None:
        path = root / name
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
    else:
        result = subprocess.run(["git", "show", f"{revision}:{name}"], cwd=root, capture_output=True, text=True)
        text = result.stdout if result.returncode == 0 else ""
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise CheckError(f"{name} at {revision or 'the working tree'}: {exc}") from exc


def guard_changes(root: Path, base: str, check: Check) -> list[str]:
    """What this change does to the checks: their settings, CI, and the repo's own check scripts."""
    before, after = toml_at(root, base, FILE), toml_at(root, None, FILE)
    if "check" not in before:
        return []  # the checks are being installed
    changes = [f"{FILE} [{name}]" for name in ("check", "merge") if before.get(name) != after.get(name)]
    old, new = toml_at(root, base, "pyproject.toml"), toml_at(root, None, "pyproject.toml")
    changes += [f"pyproject.toml [tool.{name}]" for name in ("ruff", "importlinter")
                if old.get("tool", {}).get(name) != new.get("tool", {}).get(name)]
    changed = set(paths(git(root, "diff", "--name-only", "-z", "--no-renames", base, "--"))) | set(untracked(root))
    scripts = {item for argv in check.commands for item in argv if (root / item).is_file()}
    changes += sorted(path for path in changed if path.startswith(".github/workflows/") or path in scripts)
    return changes


def guard_trailers(root: Path, base: str) -> list[str]:
    """The valid Guard-change trailers on the commits after `base`."""
    log = git(root, "log", "--format=%(trailers:key=Guard-change,valueonly,separator=%x00)%x00", f"{base}..HEAD", "--")
    return [value.strip() for value in log.split("\0") if TRAILER.match(value.strip())]


def run_tool(root: Path, rule: str, argv: list[str]) -> dict | None:
    if shutil.which(argv[0]) is None:
        return finding(".", rule, f"{argv[0]} is not installed; install it, or turn {rule} off in [check]")
    result = subprocess.run(argv, cwd=root, capture_output=True, text=True)
    if result.returncode:
        output = (result.stdout + result.stderr).strip()
        return finding(".", rule, f"`{' '.join(argv)}` failed:\n{output}")
    return None


def check(args, config: Config) -> int:
    settings = config.check
    if settings is None:
        print(f"ding check: {FILE} has no [check] table; the build-repo skill sets it up", file=sys.stderr)
        return 2
    root = config.root
    try:
        base = git(root, "rev-parse", "--verify", "--end-of-options", f"{args.base}^{{commit}}").strip()
        findings = layout(root, base, settings)
        excluded = ",".join(settings.vendor + settings.outputs)
        exclude = ["--extend-exclude", excluded] if excluded else []
        tools = []
        if settings.ruff:
            tools += [("ruff", ["ruff", "check", "--quiet", *exclude, "."]),
                      ("format", ["ruff", "format", "--check", "--quiet", *exclude, "."])]
        if settings.imports:
            tools.append(("imports", ["lint-imports"]))
        tools += [("command", [*argv, "--base", base]) for argv in settings.commands]
        findings += [item for rule, argv in tools if (item := run_tool(root, rule, argv))]
        changes, trailers = guard_changes(root, base, settings), guard_trailers(root, base)
        if changes and not trailers:
            findings.append(finding(".", "guard-change", "this change touches the checks (" + ", ".join(changes) +
                                    "); add a commit trailer `Guard-change: #<ticket> <reason>`"))
    except (CheckError, OSError) as error:
        print(f"ding check: {error}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps({"base": base, "findings": findings, "guard_changes": changes, "trailers": trailers},
                         ensure_ascii=False, indent=2))
    else:
        for item in findings:
            location = item["file"] + (f":{item['line']}" if item["line"] else "")
            print(f"{location}: {item['rule']}: {item['message']}")
        for trailer in trailers:
            print(f"Guard-change: {trailer}")
        print(f"ding check: {len(findings)} problem(s); rules in {STANDARD}" if findings else "ding check: passed")
    return int(bool(findings))


def module_map(args, config: Config) -> int:
    settings = config.check
    if settings is None and not args.paths:
        print(f"ding map: {FILE} has no [check] table; name the folders to map", file=sys.stderr)
        return 2
    folders = [path.strip("/") for path in args.paths] or list(settings.library)
    try:
        files = set(paths(git(config.root, "ls-files", "-z", "--", *folders))) | {
            path for path in untracked(config.root) if area_of(path, dict.fromkeys(folders, "")) is not None}
    except CheckError as error:
        print(f"ding map: {error}", file=sys.stderr)
        return 2
    for path in sorted(path for path in files if path.endswith(".py")):
        source = (config.root / path).read_text(encoding="utf-8", errors="replace")
        print(f"{path}: {docstring_line(source) or '(no docstring)'}")
    return 0
