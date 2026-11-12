"""File inboxes for Claude Code sessions.

`ding` cannot push a message into a Claude Code session, so the session pulls: it keeps `ding inbox --wait` running
as a background task, and Claude Code wakes the session when that task exits. Senders append to the session's inbox
file; the waiter prints unread messages, marks them read, and exits.

Each session has, under ``$XDG_STATE_HOME/ding/inbox`` (default ``~/.local/state/ding/inbox``):

- ``<id>.jsonl``: append-only events: ``message``, ``read`` (ids the waiter printed), ``withdrawn`` (ids a sender
  superseded before they were read).
- ``<id>.lock``: held with ``flock`` by the live waiter, so liveness needs no pid check.
- ``<id>.waiter.json``: what the latest waiter recorded: pid, transcript id, working directory, start time.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID, uuid4

PREFIX = "claude:"
ACTIVE_MINUTES = 30  # a Claude owner without a waiter still counts as working this long after its last read
SESSION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")


def state_root() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "ding/inbox"


def valid_id(value: str) -> bool:
    return bool(SESSION_ID.fullmatch(value))


def current_session(environ: dict | None = None) -> tuple[str, str] | None:
    """The calling session as (kind, id): ("codex", thread id) or ("claude", session id); None outside both."""
    environ = os.environ if environ is None else environ
    try:
        return "codex", str(UUID(environ.get("CODEX_THREAD_ID", "")))
    except ValueError:
        pass
    for key in ("CLAUDE_CODE_HOST_SESSION_ID", "CLAUDE_CODE_SESSION_ID"):
        value = environ.get(key, "").strip()
        if value and valid_id(value):
            return "claude", value
    return None


def is_target(value: object) -> bool:
    return isinstance(value, str) and value.startswith(PREFIX)


def target(session_id: str) -> str:
    if not valid_id(session_id):
        raise ValueError(f"not a Claude Code session id: {session_id!r}")
    return PREFIX + session_id


def bare(value: str) -> str:
    return value[len(PREFIX):] if is_target(value) else value


def paths(session_id: str, root: Path | None = None) -> tuple[Path, Path, Path]:
    root = root or state_root()
    session_id = bare(session_id)
    if not valid_id(session_id):
        raise ValueError(f"not a Claude Code session id: {session_id!r}")
    return root / f"{session_id}.jsonl", root / f"{session_id}.lock", root / f"{session_id}.waiter.json"


def _ensure(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True, mode=0o700)


@contextmanager
def _locked(path: Path) -> Iterator[None]:
    """Serialize readers and writers of one inbox file."""
    _ensure(path.parent)
    with os.fdopen(os.open(f"{path}.mutex", os.O_CREAT | os.O_RDWR, 0o600), "r+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield


def _append(path: Path, event: dict) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    path.chmod(0o600)


def events(path: Path) -> list[dict]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    found = []
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            found.append(event)
    return found


def unread(path: Path) -> list[dict]:
    """Messages neither read nor withdrawn, oldest first."""
    found = events(path)
    closed = {item for event in found if event.get("event") in {"read", "withdrawn"}
              for item in event.get("ids", [])}
    return [event for event in found if event.get("event") == "message" and event.get("id") not in closed]


def listener(session_id: str, root: Path | None = None) -> dict | None:
    """What the live waiter recorded, or None when no waiter holds the lock."""
    _, lock, info = paths(session_id, root)
    if not lock.exists():
        return None
    with os.fdopen(os.open(lock, os.O_RDWR), "r+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            try:
                recorded = json.loads(info.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                recorded = {}
            return recorded if isinstance(recorded, dict) else {}
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return None


def deliver(session_id: str, text: str, sender: str | None, *, message_id: str | None = None,
            supersede: bool = False, root: Path | None = None) -> dict:
    """Append a message; report whether a waiter is there to read it."""
    inbox, _, _ = paths(session_id, root)
    message_id = message_id or str(uuid4())
    result = {"outcome": "failed", "error": None, "inbox": str(inbox), "message_id": message_id, "withdrawn": []}
    with _locked(inbox):
        if supersede:
            earlier = [event["id"] for event in unread(inbox) if event.get("sender") == sender and sender is not None]
            if earlier:
                _append(inbox, {"event": "withdrawn", "ids": earlier, "by": sender, "time_ns": time.time_ns()})
                result["withdrawn"] = earlier
        _append(inbox, {"event": "message", "id": message_id, "sender": sender, "text": text,
                        "time_ns": time.time_ns()})
    alive = listener(session_id, root)
    if alive is None:
        result.update(outcome="no_listener",
                      error="no `ding inbox --wait` is running for this session; the message waits in its inbox")
    else:
        result.update(outcome="inbox_queued", listener_pid=alive.get("pid"))
    return result


def take(session_id: str, root: Path | None = None) -> list[dict]:
    """Return unread messages and mark them read."""
    found = pending(session_id, root)
    mark_read(session_id, [event["id"] for event in found], root)
    return found


def pending(session_id: str, root: Path | None = None) -> list[dict]:
    inbox, _, _ = paths(session_id, root)
    with _locked(inbox):
        return unread(inbox)


def mark_read(session_id: str, ids: list[str], root: Path | None = None) -> None:
    if not ids:
        return
    inbox, _, _ = paths(session_id, root)
    with _locked(inbox):
        _append(inbox, {"event": "read", "ids": ids, "time_ns": time.time_ns()})


def show(session_id: str, messages: list[dict], out, root: Path | None = None) -> None:
    """Print, then mark read: a waiter killed in between repeats the messages rather than losing them."""
    print(render(messages), file=out)
    out.flush()
    mark_read(session_id, [event["id"] for event in messages], root)


def active(session_id: str, root: Path | None = None, minutes: float = ACTIVE_MINUTES) -> bool:
    """A waiter runs now, or one started or delivered messages within the last `minutes`."""
    if listener(session_id, root) is not None:
        return True
    _, _, info = paths(session_id, root)
    stamps = [last_read(session_id, root) or 0]
    try:
        recorded = json.loads(info.read_text(encoding="utf-8"))
        stamps += [recorded.get("started_ns") or 0, recorded.get("claimed_ns") or 0]
    except (OSError, ValueError, AttributeError):
        pass
    return time.time_ns() - max(stamps) < minutes * 60e9


def note_claim(session_id: str, root: Path | None = None) -> None:
    """Record a claim, so the session counts as working before its first waiter starts."""
    _, _, info = paths(session_id, root)
    _ensure(info.parent)
    try:
        recorded = json.loads(info.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        recorded = {}
    if not isinstance(recorded, dict):
        recorded = {}
    recorded["claimed_ns"] = time.time_ns()
    temporary = info.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(recorded, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, info)


def by_transcript(transcript_id: str, root: Path | None = None) -> str | None:
    """The session whose waiter recorded this transcript id, newest first."""
    root = root or state_root()
    found = []
    for info in root.glob("*.waiter.json"):
        try:
            recorded = json.loads(info.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(recorded, dict) and recorded.get("transcript_id") == transcript_id:
            found.append((recorded.get("started_ns") or 0, info.name.removesuffix(".waiter.json")))
    return max(found)[1] if found else None


def last_read(session_id: str, root: Path | None = None) -> int | None:
    inbox, _, _ = paths(session_id, root)
    stamps = [event.get("time_ns") for event in events(inbox) if event.get("event") == "read"]
    return stamps[-1] if stamps else None


def render(messages: list[dict]) -> str:
    blocks = []
    for event in messages:
        sender = event.get("sender")
        when = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(event.get("time_ns", 0) / 1e9))
        head = f"--- message {event.get('id')} at {when}" + (f" from {sender}" if sender else "")
        blocks.append(f"{head}\n{event.get('text', '')}".rstrip())
    return "\n\n".join(blocks)


def wait(session_id: str, *, block: bool = True, show_all: bool = False, poll: float = 1.0,
         root: Path | None = None, out=None, environ: dict | None = None) -> int:
    """Print unread messages and mark them read; with block, first wait until one arrives."""
    out = out or sys.stdout
    environ = os.environ if environ is None else environ
    inbox, lock, info = paths(session_id, root)
    _ensure(inbox.parent)
    if show_all:
        messages = [event for event in events(inbox) if event.get("event") == "message"]
        print(render(messages) or "no messages", file=out)
        return 0
    if not block:
        messages = pending(session_id, root)
        if messages:
            show(session_id, messages, out, root)
        else:
            print("no unread messages", file=out)
        return 0
    with os.fdopen(os.open(lock, os.O_CREAT | os.O_RDWR, 0o600), "r+") as handle:
        deadline = time.monotonic() + 2
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                # A sender's liveness probe holds the lock for an instant; only a waiter holds it for long.
                if time.monotonic() >= deadline:
                    print(f"ding: another `ding inbox --wait` already runs for {bare(session_id)}", file=sys.stderr)
                    return 1
                time.sleep(0.05)
        try:
            claimed = json.loads(info.read_text(encoding="utf-8")).get("claimed_ns")
        except (OSError, ValueError, AttributeError):
            claimed = None
        record = {"pid": os.getpid(), "transcript_id": environ.get("CLAUDE_CODE_SESSION_ID"),
                  "cwd": os.getcwd(), "started_ns": time.time_ns(), "claimed_ns": claimed}
        temporary = info.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(record, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, info)
        try:
            seen = None
            while True:
                try:
                    stat = inbox.stat()
                    size = (stat.st_size, stat.st_mtime_ns)
                except FileNotFoundError:
                    size = None
                if size != seen:
                    seen = size
                    messages = pending(session_id, root)
                    if messages:
                        show(session_id, messages, out, root)
                        return 0
                time.sleep(poll)
        except KeyboardInterrupt:
            return 130
