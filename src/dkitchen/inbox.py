"""File inboxes for Claude Code sessions.

`ding` cannot push a message into a Claude Code session, so the session pulls: it keeps `ding inbox --wait` running
as a background task, and Claude Code wakes the session when that task exits. Senders append to the session's inbox
file; the waiter prints unread messages, marks them read, and exits.

Each session has, under ``$XDG_STATE_HOME/ding/inbox`` (default ``~/.local/state/ding/inbox``):

- ``<id>.jsonl``: append-only events: ``message``, ``read`` (ids the waiter printed), ``withdrawn`` (ids a sender
  superseded before they were read).
- ``<id>.lock``: held with ``flock`` by the live waiter, so liveness needs no pid check.
- ``<id>.waiter.json``: what the session recorded: the ticket it claimed and when, and its latest waiter's pid,
  transcript id, working directory, start, last heartbeat, and stop.
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
HEARTBEAT_SECONDS = 60  # how often a live waiter stamps its record, so a killed waiter's last moment is known
STAMPS = ("claimed_ns", "started_ns", "seen_ns", "stopped_ns")  # moments the session had, or took, a waiter
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
    """A waiter runs now, or the session claimed, had a waiter, or read messages within the last `minutes`."""
    if listener(session_id, root) is not None:
        return True
    return time.time_ns() - session(session_id, root)["last_activity_ns"] < minutes * 60e9


def recorded(session_id: str, root: Path | None = None) -> dict:
    """What claims and waiters recorded for the session, or {}."""
    _, _, info = paths(session_id, root)
    try:
        value = json.loads(info.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _record(session_id: str, root: Path | None = None, **fields) -> None:
    """Merge fields into the session's record; claims and the waiter's heartbeat must not overwrite each other."""
    _, _, info = paths(session_id, root)
    with _locked(info):
        value = {**recorded(session_id, root), **fields}
        temporary = info.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, info)


def known(session_id: str, root: Path | None = None) -> bool:
    """Whether ding has an inbox or a record for this session."""
    inbox, _, info = paths(session_id, root)
    return inbox.exists() or info.exists()


def note_claim(session_id: str, root: Path | None = None, *, ticket: str | None = None,
               cwd: str | None = None) -> None:
    """Record a claim, so the session counts as working before its first waiter starts, and which ticket it owns."""
    fields = {key: value for key, value in (("ticket", ticket), ("cwd", cwd)) if value}
    _record(session_id, root, claimed_ns=time.time_ns(), **fields)


def session(session_id: str, root: Path | None = None) -> dict:
    """The session's record plus its id, whether a waiter listens, its last read, and its last activity."""
    value = recorded(session_id, root)
    read = last_read(session_id, root)
    activity = max([read or 0, *(value.get(key) or 0 for key in STAMPS)])
    return {**value, "id": session_id, "listening": listener(session_id, root) is not None,
            "last_read_ns": read, "last_activity_ns": activity}


def sessions(root: Path | None = None) -> list[dict]:
    """Every session with a record, newest activity first."""
    root = root or state_root()
    found = [session(path.name.removesuffix(".waiter.json"), root) for path in root.glob("*.waiter.json")
             if valid_id(path.name.removesuffix(".waiter.json"))]
    return sorted(found, key=lambda item: item["last_activity_ns"], reverse=True)


def silent_minutes(entry: dict, now_ns: int | None = None) -> float | None:
    """Minutes since the session last had a waiter (or claimed), or None while a waiter runs or nothing is known."""
    if entry.get("listening"):
        return None
    since = max(entry.get(key) or 0 for key in STAMPS)
    return ((now_ns or time.time_ns()) - since) / 60e9 if since else None


def _iso(stamp_ns: int | None) -> str | None:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(stamp_ns / 1e9)) if stamp_ns else None


def status(entry: dict, now_ns: int | None = None) -> dict:
    """What `ding status` prints for a Claude Code session."""
    value = {"type": "waiting" if entry.get("listening") else "no-waiter"}
    if entry.get("listening"):
        value["waiter_pid"] = entry.get("pid")
    minutes = silent_minutes(entry, now_ns)
    if minutes is not None:
        value["minutes_without_waiter"] = round(minutes, 1)
    value["last_read"] = _iso(entry.get("last_read_ns"))
    return value


def describe(entry: dict, now_ns: int | None = None) -> dict:
    """What `ding info` prints for a Claude Code session; `name` is None, since ding cannot see the title."""
    return {"id": target(entry["id"]), "name": None, "cwd": entry.get("cwd"), "status": status(entry, now_ns),
            "ticket": entry.get("ticket"), "transcript_id": entry.get("transcript_id")}


def transcript(transcript_id: str, home: Path | None = None) -> Path | None:
    """The Claude Code transcript file for this id, wherever its project folder is."""
    if not transcript_id or not valid_id(transcript_id):
        return None
    base = home or Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    found = sorted((base / "projects").glob(f"*/{transcript_id}.jsonl"), key=lambda path: path.stat().st_mtime)
    return found[-1] if found else None


def _lines_backwards(path: Path, chunk: int = 1 << 16) -> Iterator[bytes]:
    """The file's lines, last first, read from the end in chunks: transcripts grow to many megabytes."""
    with path.open("rb") as handle:
        position = handle.seek(0, os.SEEK_END)
        rest = b""
        while position > 0:
            step = min(chunk, position)
            position -= step
            handle.seek(position)
            lines = (handle.read(step) + rest).split(b"\n")
            rest = lines.pop(0)
            yield from reversed(lines)
        yield rest


def last_reply(transcript_id: str, home: Path | None = None) -> str | None:
    """The text of the transcript's last assistant message that has text, leaving out subagent (sidechain) turns."""
    path = transcript(transcript_id, home)
    if path is None:
        return None
    for line in _lines_backwards(path):
        if b'"assistant"' not in line:
            continue
        try:
            event = json.loads(line.decode("utf-8", errors="replace"))
        except ValueError:
            continue
        message = event.get("message") if isinstance(event, dict) else None
        if event.get("type") != "assistant" or event.get("isSidechain") or not isinstance(message, dict):
            continue
        content = message.get("content")
        texts = ([content] if isinstance(content, str) else
                 [item.get("text", "") for item in content or [] if isinstance(item, dict) and item.get("type") == "text"])
        text = "\n".join(part for part in texts if part.strip())
        if text.strip():
            return text
    return None


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
    inbox, lock, _ = paths(session_id, root)
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
        _record(session_id, root, pid=os.getpid(), transcript_id=environ.get("CLAUDE_CODE_SESSION_ID"),
                cwd=os.getcwd(), started_ns=time.time_ns(), stopped_ns=None)
        try:
            seen, beat = None, time.monotonic()
            while True:
                if time.monotonic() - beat >= HEARTBEAT_SECONDS:
                    beat = time.monotonic()
                    _record(session_id, root, seen_ns=time.time_ns())
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
        finally:
            _record(session_id, root, stopped_ns=time.time_ns())
