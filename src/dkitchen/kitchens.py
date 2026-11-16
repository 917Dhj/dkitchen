"""Where each code repo's kitchen lives on this machine.

A kitchen kept in its own kitchen repo is found from the code repo through a registry on each machine,
``$XDG_CONFIG_HOME/dkitchen/kitchens.toml`` (default ``~/.config/dkitchen/kitchens.toml``), keyed by the code repo:

    [kitchens."owner/code"]
    kitchen = "/home/me/kitchens/code"     # the kitchen repo's checkout
    code = "/home/me/projects/code"        # the code repo's main checkout

`ding kitchen link CODE_PATH`, run in the kitchen's checkout, writes the entry. `config.load` reads it when the
working directory belongs to a registered code repo, such as an executor's worktree.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess
import sys

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

REPO = re.compile(r"[\w.-]+/[\w.-]+")
REMOTE = re.compile(r"[:/]([\w.-]+)/([\w.-]+?)(?:\.git)?/*$")


@dataclass(frozen=True)
class Entry:
    kitchen: Path
    code: Path


def registry_path() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "dkitchen/kitchens.toml"


def repo_of_remote(url: str) -> str | None:
    """owner/name from a GitHub remote URL in any of git's forms, or None."""
    match = REMOTE.search(url.strip())
    return f"{match.group(1)}/{match.group(2)}" if match else None


def origin(root: Path) -> str | None:
    """The owner/name of the checkout's origin remote, read locally, or None."""
    result = subprocess.run(["git", "-C", str(root), "remote", "get-url", "origin"],
                            capture_output=True, text=True, timeout=10, check=False)
    return repo_of_remote(result.stdout) if result.returncode == 0 else None


def main_checkout(path: Path) -> Path:
    """The main checkout of the repository holding path, also when path is inside one of its worktrees."""
    result = subprocess.run(["git", "-C", str(path), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                            capture_output=True, text=True, timeout=10, check=False)
    if result.returncode or not result.stdout.strip():
        raise ValueError(f"{path} is not inside a Git checkout")
    common = Path(result.stdout.strip())
    return common.parent if common.name == ".git" else common


def entries(path: Path | None = None) -> dict[str, Entry]:
    path = path or registry_path()
    if not path.exists():
        return {}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"{path}: {exc}") from exc
    table = data.get("kitchens", {})
    if set(data) - {"kitchens"} or not isinstance(table, dict):
        raise ValueError(f"{path}: holds only a [kitchens.\"owner/name\"] table per code repo")
    found = {}
    for repo, values in table.items():
        if (not REPO.fullmatch(repo) or not isinstance(values, dict) or set(values) != {"kitchen", "code"}
                or not all(isinstance(value, str) and os.path.isabs(value) for value in values.values())):
            raise ValueError(f"{path}: [kitchens.\"{repo}\"] must be a code repo owner/name holding absolute "
                             "paths kitchen and code; run `ding kitchen link` again to rewrite it")
        found[repo] = Entry(kitchen=Path(values["kitchen"]), code=Path(values["code"]))
    return found


def lookup(root: Path, path: Path | None = None) -> tuple[str, Entry] | None:
    """The code repo whose checkout holds root and its registered kitchen, or None.

    Costs nothing on a machine without a registry, so single-repo kitchens run no extra git command."""
    path = path or registry_path()
    if not path.exists():
        return None
    known = entries(path)
    repo = origin(root) if known else None
    return (repo, known[repo]) if repo in known else None


def write(found: dict[str, Entry], path: Path | None = None) -> None:
    path = path or registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for repo in sorted(found):
        entry = found[repo]
        lines += [f"[kitchens.{json.dumps(repo)}]", f"kitchen = {json.dumps(str(entry.kitchen))}",
                  f"code = {json.dumps(str(entry.code))}", ""]
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text("\n".join(lines), encoding="utf-8")
    os.replace(temporary, path)


def show(settings, here: Path) -> int:
    """Print which kitchen this directory belongs to and how it was found."""
    print(f"kitchen: {settings.root}")
    for label, value in (("kitchen repo", settings.kitchen_repo), ("code repo", settings.code_repo)):
        try:
            print(f"{label}: {value()}")
        except ValueError as exc:
            print(f"{label}: unknown ({exc})")
    if settings.split:
        print(f"code checkout: {settings.code_root or 'not linked on this machine; run `ding kitchen link`'}")
    print(f"shared: {'yes' if settings.shared else 'no'}")
    print("found: " + ("through " + str(registry_path()) if settings.root != here else "in this checkout"))
    return 0


def link(settings, code_path: str, here: Path) -> int:
    """Register this kitchen checkout for its code repo, whose checkout is at code_path, on this machine."""
    from dkitchen import config

    if settings.root != here or not (here / config.FILE).exists():
        raise ValueError(f"run `ding kitchen link` in the kitchen repo's checkout, beside its {config.FILE}")
    if not settings.split:
        raise ValueError(f"{config.FILE} names no separate code repo; set code = \"owner/name\" (and repo) first")
    code = main_checkout(Path(code_path).expanduser().resolve())
    found = origin(code)
    if found != settings.code:
        raise ValueError(f"{code} is a checkout of {found or 'no GitHub origin'}, not {settings.code}")
    known = entries()
    known[settings.code] = Entry(kitchen=here, code=code)
    write(known)
    print(f"linked {settings.code}: kitchen {here}, code {code} ({registry_path()})")
    return 0
