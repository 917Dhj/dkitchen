"""Which session holds each role of a kitchen, by session id, on this host.

- role take NAME: record the calling session (Claude Code host session id, or Codex thread id) as NAME's holder,
  with the previous holder; refuses outside a session, and for a name other than the orchestrator, a designer line,
  or the verifier (aliases included).
- role [NAME]: list every role with a holder, or print only NAME's holder id (exit 1 when nobody holds it).
Records go to ``$XDG_STATE_HOME/ding/roles/OWNER-REPO.jsonl``, appended under a lock; the latest record per role wins.
"""
from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import sys

from dkitchen import ding, inbox
from dkitchen.config import Config
from dkitchen.watch import designer_stations, station_variants


def registry(repo: str) -> Path:
    state = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
    return state / "ding/roles" / f"{repo.replace('/', '-')}.jsonl"


def standing(config: Config) -> list[str]:
    """The roles one session holds: the orchestrator, each designer line, and the verifier.

    Executors are one per ticket and found by their claim lines; the user is not a session.
    """
    stations = config.stations
    return [stations.orchestrator, *designer_stations(config), stations.verifier]


def canonical(name: str, config: Config) -> str | None:
    """The standing role NAME stands for, aliases and width normalization included; None when it names none."""
    variants = station_variants(name, config)
    return next((known for known in standing(config) if station_variants(known, config) & variants), None)


def holders(repo: str) -> dict[str, dict]:
    """The latest record per role."""
    latest = {}
    for record in inbox.events(registry(repo)):
        if isinstance(record.get("role"), str) and isinstance(record.get("id"), str):
            latest[record["role"]] = record
    return latest


def holder(role: str, repo: str) -> dict | None:
    return holders(repo).get(role)


def take(name: str, config: Config) -> int:
    role = canonical(name, config)
    if role is None:
        raise ValueError(f"{name!r} is not a role here; choose one of: {', '.join(standing(config))}")
    caller = inbox.current_session()
    if caller is None:
        raise ValueError("role take runs inside the session that takes the role; "
                         "no Claude Code or Codex session id is set here")
    kind, session = caller
    path = registry(config.repository())
    with ding.writer(path, blocking=True):
        before = holders(config.repository()).get(role)
        previous = ({"kind": before["kind"], "id": before["id"], "taken_at": before["taken_at"]}
                    if before is not None else None)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        ding.append_jsonl(path, {"role": role, "kind": kind, "id": session, "taken_at": stamp, "previous": previous})
    print(f"{role} is now held by {kind} session {session}")
    if previous is None:
        print("no previous holder")
    elif previous["id"] == session:
        print("this session already held it")
    else:
        print(f"previous holder: {previous['kind']} session {previous['id']} since {previous['taken_at']}")
    return 0


def show(name: str | None, config: Config) -> int:
    found = holders(config.repository())
    if name is None:
        for role, record in found.items():
            print(f"{role}\t{record.get('kind')}\t{record['id']}\t{record.get('taken_at')}")
        return 0
    role = canonical(name, config)
    if role is None:
        raise ValueError(f"{name!r} is not a role here; choose one of: {', '.join(standing(config))}")
    if role not in found:
        print(f"ding: nobody has taken {role}; its session runs `ding role take {role}`", file=sys.stderr)
        return 1
    print(found[role]["id"])
    return 0


def role(args, config: Config) -> int:
    words = args.words
    if words and words[0] == "take":
        if len(words) != 2:
            raise ValueError("usage: ding role take NAME")
        return take(words[1], config)
    if len(words) > 1:
        raise ValueError("usage: ding role [NAME] | ding role take NAME")
    return show(words[0] if words else None, config)
