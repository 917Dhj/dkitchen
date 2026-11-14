"""Claude Code sessions as executors: file inbox, claim, owner lines, dispatch, and task-exit wakes."""

import fcntl
import json
import os
import subprocess
import threading
import time
from types import SimpleNamespace

import pytest

from dkitchen import ding, inbox

THREAD_ID = "00000000-0000-4000-8000-000000000001"
CLAUDE_ID = "local_11111111-2222-4333-8444-555555555555"
TRANSCRIPT_ID = "99999999-8888-4777-8666-555555555555"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ding, "app_server", lambda *a, **k: pytest.fail("must not connect to App Server"))


class Waiter:
    """Hold a session's listener lock the way `ding inbox --wait` does."""

    def __init__(self, session_id):
        _, lock, info = inbox.paths(session_id)
        lock.parent.mkdir(parents=True, exist_ok=True)
        self.handle = open(lock, "a+")  # noqa: SIM115 - held until close(), like a running waiter
        fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX)
        info.write_text(json.dumps({"pid": os.getpid(), "transcript_id": TRANSCRIPT_ID, "cwd": "/w"}))

    def close(self):
        self.handle.close()


@pytest.fixture
def waiter():
    held = []
    yield lambda session_id=CLAUDE_ID: held.append(Waiter(session_id)) or held[-1]
    for item in held:
        item.close()


def test_identity_prefers_codex_then_desktop_then_transcript():
    assert inbox.current_session({"CODEX_THREAD_ID": THREAD_ID, "CLAUDE_CODE_SESSION_ID": TRANSCRIPT_ID}) == (
        "codex", THREAD_ID)
    assert inbox.current_session({"CLAUDE_CODE_HOST_SESSION_ID": CLAUDE_ID,
                                  "CLAUDE_CODE_SESSION_ID": TRANSCRIPT_ID}) == ("claude", CLAUDE_ID)
    assert inbox.current_session({"CLAUDE_CODE_SESSION_ID": TRANSCRIPT_ID}) == ("claude", TRANSCRIPT_ID)
    assert inbox.current_session({"CODEX_THREAD_ID": "invalid", "CLAUDE_CODE_SESSION_ID": "bad id"}) is None
    assert inbox.current_session({}) is None


def test_deliver_reports_no_listener_and_keeps_the_message():
    result = inbox.deliver(CLAUDE_ID, "hello", "Orchestrator")
    assert result["outcome"] == "no_listener"
    assert [event["text"] for event in inbox.unread(inbox.paths(CLAUDE_ID)[0])] == ["hello"]


def test_deliver_with_live_waiter_is_queued(waiter):
    waiter()
    result = inbox.deliver(CLAUDE_ID, "hello", "Orchestrator")
    assert result["outcome"] == "inbox_queued" and result["listener_pid"] == os.getpid()


def test_take_marks_read_and_supersede_withdraws_only_that_senders_unread():
    inbox.deliver(CLAUDE_ID, "old relay", "Orchestrator")
    inbox.deliver(CLAUDE_ID, "designer note", "Designer")
    result = inbox.deliver(CLAUDE_ID, "new relay", "Orchestrator", supersede=True)
    assert len(result["withdrawn"]) == 1
    assert [event["text"] for event in inbox.take(CLAUDE_ID)] == ["designer note", "new relay"]
    assert inbox.take(CLAUDE_ID) == []
    assert inbox.last_read(CLAUDE_ID) is not None


def test_one_waiter_per_session(waiter, capsys):
    waiter()
    assert inbox.wait(CLAUDE_ID, block=True, poll=0.01) == 1
    assert "already runs" in capsys.readouterr().err


def test_wait_blocks_until_a_message_arrives_and_records_itself(capsys):
    results = []
    worker = threading.Thread(target=lambda: results.append(
        inbox.wait(CLAUDE_ID, block=True, poll=0.02, environ={"CLAUDE_CODE_SESSION_ID": TRANSCRIPT_ID})))
    worker.start()
    deadline = time.monotonic() + 5
    while inbox.listener(CLAUDE_ID) is None and time.monotonic() < deadline:
        time.sleep(0.01)
    recorded = inbox.listener(CLAUDE_ID)
    assert recorded["transcript_id"] == TRANSCRIPT_ID and recorded["pid"] == os.getpid()
    assert inbox.deliver(CLAUDE_ID, "wake up", "Orchestrator")["outcome"] == "inbox_queued"
    worker.join(5)
    assert results == [0]
    out = capsys.readouterr().out
    assert "wake up" in out and "from Orchestrator" in out
    assert inbox.listener(CLAUDE_ID) is None


def test_send_to_claude_target(waiter, capsys):
    assert ding.main(["send", CLAUDE_ID, "--from", "Orchestrator", "--message", "first"]) == ding.NO_LISTENER_EXIT == 3
    assert "no_listener" in capsys.readouterr().err
    waiter()
    assert ding.main(["send", f"claude:{CLAUDE_ID}", "--from", "Orchestrator", "--message", "second",
                      "--steer", "--supersede"]) == 0
    err = capsys.readouterr().err
    assert "inbox_queued" in err and "withdrew 1" in err
    assert [event["text"] for event in inbox.take(CLAUDE_ID)] == ["[from Orchestrator]\nsecond"]
    assert ding.main(["send", CLAUDE_ID, "--message", "x", "--interrupt"]) == 1
    assert "--interrupt" in capsys.readouterr().err
    sent = [json.loads(line) for line in (ding.run_registry().parent / "sent.jsonl").read_text().splitlines()]
    assert [event["outcome"] for event in sent if event["event"] == "send_result"] == ["no_listener", "inbox_queued"]


def test_bare_uuid_is_claude_only_after_a_waiter_ran(waiter):
    assert ding.resolve_target(TRANSCRIPT_ID, None, None) == TRANSCRIPT_ID
    waiter(TRANSCRIPT_ID)
    assert ding.resolve_target(TRANSCRIPT_ID, None, None) == f"claude:{TRANSCRIPT_ID}"


def test_owner_lines_of_both_kinds(monkeypatch):
    comments = [{"body": f"Codex owner: {THREAD_ID}"}, {"body": f"Status: in progress\n\nClaude owner: `{CLAUDE_ID}`"}]

    def gh(arguments):
        if arguments[0] == "repo":
            return {"nameWithOwner": "example/project"}
        if "--paginate" not in arguments:
            return {"body": "ticket"}
        return [comments]

    monkeypatch.setattr(ding, "gh_json", gh)
    assert ding.issue_session(42, repo="example/project") == f"claude:{CLAUDE_ID}"
    assert ding.ticket_owners("example/project", 42) == [THREAD_ID, f"claude:{CLAUDE_ID}"]
    comments.append({"body": f"Codex owner: {THREAD_ID}"})
    assert ding.issue_session(42, repo="example/project") == THREAD_ID


def test_live_owners_count_a_claude_owner_only_with_a_waiter(monkeypatch, waiter):
    monkeypatch.setattr(ding, "ticket_owners", lambda repo, number: [f"claude:{CLAUDE_ID}"])
    assert ding.live_ticket_owners("example/project", 42, None) == []
    waiter()
    assert [owner["id"] for owner in ding.live_ticket_owners("example/project", 42, None)] == [f"claude:{CLAUDE_ID}"]


@pytest.fixture
def gh_comments(monkeypatch):
    posted = []
    run = subprocess.run

    def fake_run(argv, *args, **kwargs):
        if argv[:3] == ["gh", "issue", "comment"]:
            posted.append({"argv": argv, "body": kwargs.get("input")})
            return subprocess.CompletedProcess(argv, 0, "https://github.com/example/project/issues/42#issuecomment-1\n", "")
        return run(argv, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", fake_run)
    return posted


@pytest.mark.parametrize("environment,label,session_id,next_step", [
    ({"CODEX_THREAD_ID": THREAD_ID}, "Codex", THREAD_ID, "nothing"),
    ({"CLAUDE_CODE_HOST_SESSION_ID": CLAUDE_ID}, "Claude", CLAUDE_ID, "ding inbox --wait"),
])
def test_claim_posts_owner_line_with_status_block(monkeypatch, gh_comments, capsys,
                                                  environment, label, session_id, next_step):
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(ding, "live_ticket_owners", lambda *a: [])
    assert ding.main(["claim", "example/project#42"]) == 0
    body = gh_comments[0]["body"]
    assert body.startswith("Status: in progress\nWaiting on: none\n")
    assert f"{label} owner: {session_id}" in body and f"{label} session: {session_id}" in body
    assert gh_comments[0]["argv"][3:6] == ["42", "--repo", "example/project"]
    assert next_step in capsys.readouterr().out


def test_claim_refuses_another_working_owner_unless_replace(monkeypatch, gh_comments, capsys):
    monkeypatch.setenv("CLAUDE_CODE_HOST_SESSION_ID", CLAUDE_ID)
    monkeypatch.setattr(ding, "live_ticket_owners", lambda *a: [{"id": THREAD_ID, "name": "Run"}])
    assert ding.main(["claim", "example/project#42"]) == 1
    assert "still working" in capsys.readouterr().err and gh_comments == []
    assert ding.main(["claim", "example/project#42", "--replace"]) == 0
    monkeypatch.setattr(ding, "live_ticket_owners", lambda *a: [{"id": f"claude:{CLAUDE_ID}", "name": "me"}])
    assert ding.main(["claim", "example/project#42"]) == 0


def test_claim_outside_a_session_refuses(capsys):
    assert ding.main(["claim", "example/project#42"]) == 1
    assert "inside the executor's own session" in capsys.readouterr().err


@pytest.fixture
def kitchen(tmp_path, monkeypatch):
    def write(default=None):
        text = 'repo = "example/project"\n'
        if default:
            text += f'[executor]\ndefault = "{default}"\n'
        (tmp_path / ".dkitchen.toml").write_text(text)
    monkeypatch.setattr(ding, "live_ticket_owners", lambda *a: [])
    return write


def test_new_with_claude_default_prints_the_message_and_opens_nothing(kitchen, capsys, tmp_path):
    kitchen("claude")
    brief = tmp_path / "brief.md"
    brief.write_text("Do the work.")
    assert ding.main(["new", "--issue", "42", "--message-file", str(brief)]) == 0
    captured = capsys.readouterr()
    assert captured.out == ("You own ticket example/project#42. Before anything else, run "
                            "`ding claim example/project#42` and do what it prints.\n\nDo the work.\n")
    assert "Claude Code session" in captured.err


def test_new_print_overrides_and_executor_flag(kitchen, capsys, tmp_path):
    kitchen()
    assert ding.main(["new", "--issue", "42", "--message", "Go", "--print", "--cwd", str(tmp_path)]) == 0
    assert f"Work in {tmp_path}." in capsys.readouterr().out
    assert ding.main(["new", "--issue", "42", "--message", "Go", "--executor", "claude"]) == 0
    assert "Claude Code session" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        ding.main(["new", "--issue", "42", "--message", "Go"])
    assert "--cwd is required" in capsys.readouterr().err


def test_new_refuses_a_working_owner_before_printing(kitchen, monkeypatch, capsys):
    kitchen("claude")
    monkeypatch.setattr(ding, "live_ticket_owners", lambda *a: [{"id": f"claude:{CLAUDE_ID}", "name": "x"}])
    assert ding.main(["new", "--issue", "42", "--message", "Go"]) == 1
    captured = capsys.readouterr()
    assert captured.out == "" and "still working" in captured.err


def test_executor_default_is_validated(tmp_path):
    from dkitchen import config
    (tmp_path / ".dkitchen.toml").write_text('[executor]\ndefault = "gemini"\n')
    with pytest.raises(ValueError, match="executor"):
        config.load(tmp_path)


def test_task_exit_wakes_a_claude_session_through_its_inbox(waiter, tmp_path):
    waiter()
    args = SimpleNamespace(record=str(tmp_path / "exit.jsonl"), thread_id=f"claude:{CLAUDE_ID}",
                           message="Task job exited", socket=None, progress=None)
    assert ding.run_task(args, ["true"]) == 0
    records = [json.loads(line) for line in (tmp_path / "exit.jsonl").read_text().splitlines()]
    assert records[-1]["event"] == "notification" and records[-1]["outcome"] == "inbox_queued"
    assert [event["text"] for event in inbox.take(CLAUDE_ID)] == ["Task job exited"]


def test_launch_from_claude_session_records_it_as_the_wake_target(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_CODE_HOST_SESSION_ID", CLAUDE_ID)
    started = []
    real_run = subprocess.run

    def fake_run(argv, *args, **kwargs):
        if argv and str(argv[0]).endswith("tmux"):
            started.append(argv)
            return subprocess.CompletedProcess(argv, 0, "ding-job\tjob\n", "")
        return real_run(argv, *args, **kwargs)

    monkeypatch.setattr(ding.shutil, "which", lambda name: "/usr/bin/tmux")
    monkeypatch.setattr(subprocess, "run", fake_run)
    assert ding.main(["launch", "job", "--", "true"]) == 0
    argv = started[0]
    assert not any(value.startswith("CODEX_THREAD_ID=") for value in argv)
    assert f"run claude:{CLAUDE_ID}" in argv[-1]


def transcript(tmp_path, *replies):
    """Write a Claude Code transcript whose assistant messages carry these texts."""
    path = tmp_path / "claude" / "projects" / "-w" / f"{TRANSCRIPT_ID}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [{"type": "user", "message": {"role": "user", "content": "go"}}]
    for reply in replies:
        lines.append({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "Bash", "input": {}}, {"type": "text", "text": reply}]}})
        lines.append({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "Bash", "input": {}}]}})
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\nnot json\n")
    return path


@pytest.fixture
def claude_home(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    return tmp_path


def test_read_status_and_info_of_a_claude_session(waiter, claude_home, capsys):
    transcript(claude_home, "older", "Done: PR opened.\n\nDetails follow.")
    waiter()
    inbox.note_claim(CLAUDE_ID, ticket="example/project#42")
    assert ding.main(["read", f"claude:{CLAUDE_ID}"]) == 0
    assert capsys.readouterr().out == "Done: PR opened.\n\nDetails follow.\n"
    assert ding.main(["read", "--head", f"claude:{CLAUDE_ID}"]) == 0
    assert capsys.readouterr().out == "Done: PR opened.\n"
    assert ding.main(["status", f"claude:{CLAUDE_ID}"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["type"] == "waiting" and status["waiter_pid"] == os.getpid()
    assert ding.main(["info", f"claude:{CLAUDE_ID}"]) == 0
    info = json.loads(capsys.readouterr().out)
    assert info == {"id": f"claude:{CLAUDE_ID}", "name": None, "cwd": "/w", "status": info["status"],
                    "ticket": "example/project#42", "transcript_id": TRANSCRIPT_ID}


def test_read_of_a_claude_session_without_transcript_and_rename_refuse(capsys):
    inbox.note_claim(CLAUDE_ID)
    assert ding.main(["read", f"claude:{CLAUDE_ID}"]) == 1
    assert "no transcript recorded" in capsys.readouterr().err
    assert ding.main(["rename", f"claude:{CLAUDE_ID}", "--name", "x"]) == 1
    assert "rename works on Codex sessions only" in capsys.readouterr().err
    assert ding.main(["status", f"claude:{CLAUDE_ID}"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["type"] == "no-waiter" and status["minutes_without_waiter"] < 1


def test_waiter_records_its_stop_and_heartbeat(monkeypatch, capsys):
    monkeypatch.setattr(inbox, "HEARTBEAT_SECONDS", 0)
    threading.Timer(0.1, inbox.deliver, (CLAUDE_ID, "hi", "Orchestrator")).start()
    assert inbox.wait(CLAUDE_ID, poll=0.01) == 0
    record = inbox.recorded(CLAUDE_ID)
    assert record["seen_ns"] >= record["started_ns"] and record["stopped_ns"] >= record["seen_ns"]
    entry = inbox.session(CLAUDE_ID)
    assert not entry["listening"] and inbox.silent_minutes(entry, record["stopped_ns"] + 120e9) == 2


def test_board_lists_claude_sessions_under_the_repository(waiter, claude_home, monkeypatch, capsys):
    transcript(claude_home, "Working on the tests.\n\nMore.")
    waiter()
    inbox.note_claim(CLAUDE_ID, ticket="example/project#42")
    other = "local_aaaaaaaa-2222-4333-8444-555555555555"
    inbox.note_claim(other, ticket="example/project#7", cwd="/elsewhere")
    stale = "local_bbbbbbbb-2222-4333-8444-555555555555"
    inbox.note_claim(stale, ticket="example/project#8", cwd="/w")
    inbox._record(stale, claimed_ns=time.time_ns() - int(ding.CLAUDE_BOARD_HOURS * 3600e9) - 1)
    (claude_home / ".dkitchen.toml").write_text('repo = "example/project"\n')
    monkeypatch.setattr(ding, "repository_roots", lambda: [inbox.Path("/w")])
    monkeypatch.setattr(ding, "socket_path", lambda path: (_ for _ in ()).throw(ValueError("no socket")))
    monkeypatch.setattr(ding, "unwrapped_tasks", lambda **kwargs: [])
    assert ding.main(["board", "--no-issue-lookup"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[1].split("\t") == [f"claude:{CLAUDE_ID}", "/w", "waiting", "#42", "Working on the tests.", ""]
    assert len(lines) == 2


def test_board_without_app_server_or_claude_sessions_still_fails(monkeypatch, capsys):
    monkeypatch.setattr(ding, "repository_roots", lambda: [inbox.Path("/w")])
    monkeypatch.setattr(ding, "socket_path", lambda path: (_ for _ in ()).throw(ValueError("no socket")))
    monkeypatch.setattr(ding, "unwrapped_tasks", lambda **kwargs: [])
    assert ding.main(["board"]) == 1


def test_a_claude_owner_stays_working_between_waits(monkeypatch):
    monkeypatch.setattr(ding, "ticket_owners", lambda repo, number: [f"claude:{CLAUDE_ID}"])
    inbox.deliver(CLAUDE_ID, "relay", "Orchestrator")
    inbox.take(CLAUDE_ID)
    assert [owner["id"] for owner in ding.live_ticket_owners("example/project", 42, None)] == [f"claude:{CLAUDE_ID}"]
    assert not inbox.active(CLAUDE_ID, minutes=0)


def test_codex_owners_are_warned_about_when_app_server_is_missing(monkeypatch, capsys):
    monkeypatch.setattr(ding, "ticket_owners", lambda repo, number: [THREAD_ID])
    monkeypatch.setattr(ding, "socket_path", lambda path: (_ for _ in ()).throw(ValueError("no socket")))
    assert ding.live_ticket_owners("example/project", 42, None) == []
    assert "could not check the ticket's Codex owners" in capsys.readouterr().err


def test_messages_stay_unread_if_printing_fails():
    inbox.deliver(CLAUDE_ID, "keep me", "Orchestrator")

    class Broken:
        def write(self, text):
            raise BrokenPipeError

        def flush(self):
            pass

    with pytest.raises(BrokenPipeError):
        inbox.wait(CLAUDE_ID, block=False, out=Broken())
    assert [event["text"] for event in inbox.pending(CLAUDE_ID)] == ["keep me"]


def test_waiter_survives_a_momentary_liveness_probe(capsys):
    _, lock, _ = inbox.paths(CLAUDE_ID)
    lock.parent.mkdir(parents=True, exist_ok=True)
    probe = open(lock, "a+")  # noqa: SIM115 - released by the timer below
    fcntl.flock(probe.fileno(), fcntl.LOCK_EX)
    threading.Timer(0.2, probe.close).start()
    inbox.deliver(CLAUDE_ID, "hi", "Orchestrator")
    assert inbox.wait(CLAUDE_ID, block=True, poll=0.01) == 0
    assert "hi" in capsys.readouterr().out


def test_transcript_uuid_resolves_to_its_desktop_session(waiter):
    waiter()
    assert ding.resolve_target(TRANSCRIPT_ID, None, None) == f"claude:{CLAUDE_ID}"


def test_a_claim_counts_as_working_before_the_first_waiter():
    assert not inbox.active(CLAUDE_ID)
    inbox.note_claim(CLAUDE_ID)
    assert inbox.active(CLAUDE_ID)


def test_new_with_replace_tells_the_session_to_claim_with_replace(kitchen, capsys):
    kitchen("claude")
    assert ding.main(["new", "--issue", "42", "--message", "Go", "--replace"]) == 0
    assert "`ding claim example/project#42 --replace`" in capsys.readouterr().out


def test_run_registry_accepts_a_claude_session(tmp_path, capsys):
    record = tmp_path / "exit.jsonl"
    with ding.registered_run(f"claude:{CLAUDE_ID}", record):
        runs = ding.latest_runs()
    assert list(runs) == [f"claude:{CLAUDE_ID}"]
    assert "invalid run registry row" not in capsys.readouterr().err


@pytest.mark.parametrize("listening,state", [(True, "exited(0)"), (False, "notify_failed")])
def test_board_reads_a_claude_task_exit(waiter, tmp_path, capsys, listening, state):
    if listening:
        waiter()
    args = SimpleNamespace(record=str(tmp_path / "exit.jsonl"), thread_id=f"claude:{CLAUDE_ID}",
                           message="Task job exited", socket=None, progress=None)
    ding.run_task(args, ["true"])
    run = ding.latest_runs()[f"claude:{CLAUDE_ID}"]
    assert ding.run_state(run) == state
    assert "run evidence unavailable" not in capsys.readouterr().err


@pytest.fixture
def silent_owner(monkeypatch, tmp_path):
    """A ticket an in-progress Claude executor claimed 40 minutes ago, with no waiter since."""
    from dkitchen import config, watch
    inbox.note_claim(CLAUDE_ID, ticket="o/r#26", cwd="/w")
    inbox._record(CLAUDE_ID, claimed_ns=time.time_ns() - int(40 * 60e9))
    claim = {"id": 2600, "body": f"Status: in progress\nWaiting on: none\n\nClaude owner: {CLAUDE_ID}\n\n"
                                 f"Claude session: {CLAUDE_ID}\n", "created_at": "2026-11-12T10:00:00Z",
             "html_url": "https://github.com/o/r/issues/26#issuecomment-2600"}
    state = SimpleNamespace(issue={"number": 26, "state": "open", "comments": 1, "labels": [], "body": "Task"},
                            comments=[claim], config=config.Config(root=tmp_path, repo="o/r"))

    def gh(path):
        if path == "repos/o/r/issues/26":
            return state.issue
        if "/issues/26/comments?" in path:
            return state.comments
        raise AssertionError(path)

    monkeypatch.setattr(watch, "gh", gh)
    state.check = lambda reported=(), skip=(): watch.missing_waiters(state.config, "o/r", set(reported), set(skip))
    return state


def test_watch_reports_a_claude_executor_without_a_waiter(silent_owner):
    found = silent_owner.check()
    assert len(found) == 1 and found[0][2] == 2600
    assert f"#26 Claude Code executor {CLAUDE_ID} has run no `ding inbox --wait` for 40 minutes" in found[0][1]
    assert silent_owner.check(reported={2600}) == []
    assert silent_owner.check(skip={26}) == []


@pytest.mark.parametrize("change", ["listening", "recent", "done", "other_owner", "closed", "disabled", "repo"])
def test_watch_waiter_report_needs_every_condition(silent_owner, waiter, change):
    if change == "listening":
        waiter()
    elif change == "recent":
        inbox.note_claim(CLAUDE_ID)
    elif change == "done":
        silent_owner.comments[0]["body"] = silent_owner.comments[0]["body"].replace("in progress", "done")
    elif change == "other_owner":
        silent_owner.comments.append({"id": 2602, "body": f"Codex owner: {THREAD_ID}\n", "created_at": "x"})
    elif change == "closed":
        silent_owner.issue["state"] = "closed"
    elif change == "disabled":
        silent_owner.config = type(silent_owner.config)(root=silent_owner.config.root, repo="o/r",
                                                        watch=type(silent_owner.config.watch)(executor_listener_minutes=0))
    elif change == "repo":
        inbox.note_claim(CLAUDE_ID, ticket="o/other#26")
        inbox._record(CLAUDE_ID, claimed_ns=time.time_ns() - int(40 * 60e9))
    assert silent_owner.check() == []


def test_last_reply_reads_backwards_across_chunks_and_skips_sidechains(claude_home):
    path = transcript(claude_home, "first", "Final answer.")
    with path.open("a") as handle:
        handle.write(json.dumps({"type": "assistant", "isSidechain": True, "message": {
            "role": "assistant", "content": [{"type": "text", "text": "subagent report"}]}}) + "\n")
    assert inbox.last_reply(TRANSCRIPT_ID) == "Final answer."
    lines = path.read_bytes().split(b"\n")
    assert list(inbox._lines_backwards(path, chunk=7)) == lines[::-1]


def test_status_of_an_unknown_claude_session_is_an_error(capsys):
    assert ding.main(["status", f"claude:{CLAUDE_ID}"]) == 1
    assert "no inbox or record" in capsys.readouterr().err


def test_record_updates_merge_instead_of_overwriting():
    inbox.note_claim(CLAUDE_ID, ticket="o/r#26", cwd="/w")
    inbox._record(CLAUDE_ID, seen_ns=5)
    inbox.note_claim(CLAUDE_ID)
    record = inbox.recorded(CLAUDE_ID)
    assert record["ticket"] == "o/r#26" and record["cwd"] == "/w" and record["seen_ns"] == 5


def test_watch_skips_an_unreadable_ticket_and_old_records(silent_owner, monkeypatch, capsys):
    from dkitchen import watch
    monkeypatch.setattr(watch, "gh", lambda path: (_ for _ in ()).throw(RuntimeError("HTTP 404")))
    assert silent_owner.check() == []
    assert "could not check #26" in capsys.readouterr().err
    inbox._record(CLAUDE_ID, claimed_ns=time.time_ns() - int((watch.WAITER_LOOKBACK_DAYS * 1440 + 1) * 60e9))
    monkeypatch.setattr(watch, "gh", lambda path: pytest.fail("old records are not rechecked"))
    assert silent_owner.check() == []
