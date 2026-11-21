from datetime import datetime, timedelta, timezone
import contextlib
import fcntl
import hashlib
import json
import re
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from dkitchen import config, ding, night, orchestrate, refs, rule, watch


CHINESE = """
repo = "o/r"

[roles]
orchestrator = "总编排"
designer = "总设计"
verifier = "核查"
executor = "执行者"
user = "用户"
separator = "："

[status]
fields = ["状态", "在等", "关键数字", "下一步"]
in_progress = "进行中"
waiting_on_design = "等设计"
blocked = "阻塞"
done = "完成"
none = "无"

[log]
issue = 246
pending = "待用户决定"
"""


def settings(tmp_path, text=None):
    if text is not None:
        (tmp_path / config.FILE).write_text(text, encoding="utf-8")
    return config.load(tmp_path)


def test_defaults_without_a_config_file(tmp_path):
    loaded = settings(tmp_path)
    assert loaded.root == tmp_path and loaded.repo is None
    assert loaded.status.fields == ("Status", "Waiting on", "Key numbers", "Next")
    assert loaded.roles.signature(loaded.roles.orchestrator) == "Orchestrator: "


def test_config_file_sets_the_vocabulary(tmp_path):
    loaded = settings(tmp_path, CHINESE)
    assert loaded.repository() == "o/r"
    assert loaded.status.fields == ("状态", "在等", "关键数字", "下一步")
    assert loaded.roles.signature(loaded.roles.orchestrator) == "总编排："
    assert loaded.log.issue == 246


BAD_CONFIGS = [
    ("colour = 1", "unknown keys: colour"),
    ("[status]\nfeilds = ['A']", r"unknown keys in \[status\]: feilds"),
    ('[status]\npending_merge = "Pending merge"', r"unknown keys in \[status\]: pending_merge"),
    ("[status]\nfields = []", "nonempty list"),
    ("[log]\nissue = 0", "positive issue number"),
    ("[roles]\ndesigner = ''", "nonempty string"),
    ("repo = 'not a repo'", "owner/name"),
    ("[status", "dkitchen.toml"),
    *((f"[sessions]\nname = {json.dumps(template)}", error) for template, error in [
        ("", "nonempty string"),
        ("{issue} {title}", r"uses \{title\}; use only \{issue\}, \{name\}, \{repo\}"),
        ("{} {name}", r"uses \{\}"),
        ("{name.upper}", r"uses \{name.upper\}"),
        ("{name!r}", "without a conversion"),
        ("{name", "not a valid template"),
        ("{name:d}", "not a valid template"),
        ("{issue:{name}}", "nested field"),
    ]),
    *((f"[merge]\nrequired_checks = {value}", "required_checks must be a list of nonempty check names")
      for value in ['"hca-check"', '[1]', '[""]', '["   "]', 'false']),
    *((f"[merge]\nrefresh = {value}", "refresh must be one command line or an empty string")
      for value in ['1', '"   "', '"a \'b"', '"a\\nb"', '["a"]']),
    *((f"[merge]\nreview_check = {value}", "review_check") for value in ['true', '" "']),
    *((f"[merge]\n{text}", "must be one line holding {sha} once")
      for text in ['review_pass = "Reviewed: pass"', 'review_pass = "{sha}"', 'review_changes = "a {sha} {sha}"',
                   'review_pass = "a\\n{sha}"', 'review_pass = 1']),
    *((text, r"\[night\]") for text in ['[night]\nheading = ""', '[night]\nclosed = "line\\nline"', '[night]\nunknown = "x"']),
    ("[rule]\ntypes = []", "types must be a nonempty list"),
    ("[rule]\nnotify = 'no link'", "holding {url}"),
    ("[rule]\nnotify = '{url} {oops}'", "not a valid template"),
    ("[rule]\nnotify_types = 'actionable'", "notify_types must be a list"),
    ("[rule]\nnotify_types = ['urgent']", "notify_types urgent must be among types"),
    *((f"[rule]\nsignatures = {value}", r"\[rule\] signatures must be a nonempty list")
      for value in ['[]', '[1]', '["Designer: ", false]', '[""]', '["   "]', '"Designer: "']),
    ("[review]\nnotify = '{url}'", "holding {url} and {verdict}"),
    ("[review]\nnotify = '{verdict} {url} {oops}'", "not a valid template"),
    ("[review]\nverdict_pass = ''", "verdict_pass must be one nonempty line"),
    ("[review]\nverdict_changes = 'Verdict: pass'", "must differ"),
    *((f"[launch]\n{text}", error) for text, error in [
        ('preflight = "python check.py"', "argv list"),
        ('preflight = []', "argv list"),
        ('preflight = [""]', "argv list"),
        ('preflight = ["python", 1]', "argv list"),
        ('preflight = ["python", "\\u0000"]', "argv list"),
        ('preflight_timeout = 0', "positive finite"),
        ('preflight_timeout = -1', "positive finite"),
        ('preflight_timeout = true', "positive finite"),
        ('preflight_timeout = "300"', "positive finite"),
        ('preflight_timeout = inf', "positive finite"),
        ('preflight_timeout = nan', "positive finite"),
        ('keep_days = -1', "nonnegative finite"),
        ('keep_days = true', "nonnegative finite"),
        ('keep_days = "14"', "nonnegative finite"),
        ('keep_days = inf', "nonnegative finite"),
        ('prefligth = ["python"]', "unknown keys"),
    ]),
    *((f"[watch]\nidle_minutes = {value}", r"\[watch\] idle_minutes must be a nonnegative finite number")
      for value in ['-1', '"45"', 'true', 'nan', 'inf']),
    *((f"[watch]\n{key} = {value}", key) for key, value in [
        ("design_answer_minutes", "-1"), ("design_answer_minutes", "true"), ("design_answer_minutes", "inf"),
        ("unrouted_wait_minutes", "-1"), ("unrouted_wait_minutes", "nan"), ("unrouted_wait_minutes", "true"),
        ("executor_listener_minutes", "-1"), ("executor_listener_minutes", "true"),
        ("stale_minutes", "-1"), ("stale_minutes", "true"), ("overrun_factor", "-1"), ("overrun_factor", "nan"),
        ("overrun_factor", "0.5"),
    ]),
    *((text, "aliases") for text in ['[roles]\naliases = "wrong"', '[roles.aliases]\nDesigner = []',
                                     '[roles.aliases]\nDesigner = [1]', '[roles.aliases]\nDesigner = [""]',
                                     '[roles.aliases]\n"" = ["D"]']),
    ('code = "org/code"\n', "code needs repo too"),
    ('repo = "me/kitchen"\nshared = true\n', "needs a kitchen repo of its own"),
    ('repo = "o/r"\ncode = "o/r"\nshared = true\n', "needs a kitchen repo of its own"),
    ('repo = "me/kitchen"\ncode = "org/code"\nshared = "yes"\n', "shared must be true or false"),
    ('repo = "me/kitchen"\ncode = "not a repo"\n', "code must look like owner/name"),
]


@pytest.mark.parametrize("text, error", BAD_CONFIGS)
def test_bad_config_is_refused_with_its_key(tmp_path, text, error):
    with pytest.raises(ValueError, match=error):
        settings(tmp_path, text)


def test_session_name_template_defaults_and_fills_names_verbatim(tmp_path):
    assert settings(tmp_path).sessions.session_name(issue=57, name="Fix {x} 100%", repo="o/r") == \
        "【#57】Fix {x} 100%"
    loaded = settings(tmp_path, '[sessions]\nname = "{repo}#{issue:04d} {name}"')
    assert loaded.sessions.session_name(issue=7, name="Plot", repo="o/r") == "o/r#0007 Plot"


def test_board_status_falls_back_to_the_config_fields(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / config.FILE).write_text(CHINESE, encoding="utf-8")
    monkeypatch.delenv("DING_STATUS_FIELDS", raising=False)
    monkeypatch.setattr(ding, "unwrapped_tasks", lambda **kwargs: [])
    seen = {}
    monkeypatch.setattr(ding, "show_board", lambda path, all_threads, status, no_issue_lookup: seen.setdefault("fields", status))
    assert ding.main(["board", "--status"]) == 0
    assert seen["fields"] == ("状态", "在等", "关键数字", "下一步")
    monkeypatch.setenv("DING_STATUS_FIELDS", "A,B")
    seen.clear()
    assert ding.main(["board", "--status"]) == 0
    assert seen["fields"] == ("A", "B")


def test_log_entry_is_signed_with_utc_time_and_pending_line(tmp_path):
    moment = datetime(2026, 10, 14, 17, 5, tzinfo=timezone(timedelta(hours=8)))
    english = settings(tmp_path)
    assert orchestrate.log_body(["Merged PR #1"], [], moment, english) == (
        "Orchestrator: 09:05 UTC\n- Merged PR #1\n- Waiting for the user: none")
    chinese = settings(tmp_path, CHINESE)
    assert orchestrate.log_body(["a", "b"], ["#234 复核", "#215 方向"], moment, chinese).endswith(
        "- b\n- 待用户决定：#234 复核; #215 方向")
    assert orchestrate.signed(" 总编排：已转告", chinese) == "总编排：已转告"
    assert orchestrate.signed("已转告", chinese) == "总编排：已转告"
    assert orchestrate.signed("Passed on.", english) == "Orchestrator: Passed on."


def fake_call(responses, calls):
    def call(settings, *args):
        if args == ("gh", "api", f"repos/{settings.repository()}"):
            return SimpleNamespace(returncode=0, stdout='{"default_branch":"main"}', stderr="")
        calls.append(args)
        returncode, stdout = responses.pop(0)
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr="boom" if returncode else "")
    return call


@pytest.mark.parametrize("sent, comments", [(0, 1), (3, 1), (1, 0)])
def test_relay_comments_only_after_queued_delivery(tmp_path, monkeypatch, capsys, sent, comments):
    loaded = settings(tmp_path, 'repo = "o/r"')
    sends, calls = [], []
    monkeypatch.setattr(orchestrate.ding, "main", lambda argv: sends.append(argv) or sent)
    monkeypatch.setattr(orchestrate, "call", fake_call([(0, "https://comment")], calls))
    args = SimpleNamespace(ticket=42, message="Go ahead with stage 2.", message_file=None, comment=None,
                           no_comment=False, to=None, socket=None)
    assert orchestrate.relay(args, loaded) == (1 if sent == 1 else 0)
    assert sends == [["send", "o/r#42", "--from", "Orchestrator", "--message",
                      "Orchestrator: New decision; it replaces earlier relays not yet carried out.\n"
                      "Go ahead with stage 2.", "--steer", "--supersede"]]
    assert len(calls) == comments
    if comments:
        assert calls[0][:5] == ("gh", "issue", "comment", "42", "--repo")
        assert calls[0][-1] == "Orchestrator: Go ahead with stage 2."
        err = capsys.readouterr().err
        assert ("queued in the inbox of o/r#42" in err and "Do not resend" in err) == (sent == 3)
    else:
        assert "No comment was left" in capsys.readouterr().err


@pytest.mark.parametrize("queue, interrupt, tail", [
    (True, False, []), (False, True, ["--steer", "--supersede", "--interrupt"]),
])
def test_relay_queue_keeps_plain_message_and_interrupt_passes_through(tmp_path, monkeypatch, queue, interrupt, tail):
    loaded = settings(tmp_path, CHINESE + '\n[relay]\nsuperseding = "新决策，取代此前尚未执行的转达"\n')
    sends = []
    monkeypatch.setattr(orchestrate.ding, "main", lambda argv: sends.append(argv) or 0)
    args = SimpleNamespace(ticket=42, message="总编排：放行第 2 阶段。", message_file=None, comment=None,
                           no_comment=True, to=None, socket=None, queue=queue, interrupt=interrupt)
    assert orchestrate.relay(args, loaded) == 0
    text = "总编排：放行第 2 阶段。" if queue else "总编排：新决策，取代此前尚未执行的转达\n放行第 2 阶段。"
    assert sends == [["send", "o/r#42", "--from", "总编排", "--message", text, *tail]]




def view(state="OPEN", head="abc123", draft=False, body=""):
    return 0, json.dumps({"isDraft": draft, "state": state, "headRefOid": head, "mergeCommit": {"oid": "m1"},
                          "body": body, "baseRefName": "main"})


@pytest.mark.parametrize("responses, code, message", [
    ([view(), (0, ""), view("MERGED")], 0, "PR #7 merged as m1"),
    ([view(head="fff999")], 1, "review it again"),
    ([view(draft=True)], 1, "draft"),
    ([view("MERGED")], 1, "already merged"),
    ([view(), (0, ""), view()], 1, "find out why"),
])
def test_merge_only_at_the_reviewed_head(tmp_path, monkeypatch, capsys, responses, code, message):
    loaded = settings(tmp_path, 'repo = "o/r"')
    calls = []
    monkeypatch.setattr(orchestrate, "call", fake_call(responses, calls))
    assert orchestrate.merge(SimpleNamespace(pr=7, sha="abc"), loaded) == code
    captured = capsys.readouterr()
    assert message in captured.out + captured.err
    if len(calls) > 1:
        assert calls[1][-2:] == ("--match-head-commit", "abc123")




SESSION = "Codex session: 00000000-0000-4000-8000-000000000001"














def test_merge_required_checks_defaults_and_exact_names(tmp_path):
    assert settings(tmp_path).merge.required_checks == ()
    assert settings(tmp_path, "[merge]\nrequired_checks = []").merge.required_checks == ()
    assert settings(tmp_path, '[merge]\nrequired_checks = [" CI / test "]').merge.required_checks == (" CI / test ",)


def check_run(state="success", sha="abc123", name="hca-check"):
    return {"name": name, "head_sha": sha, "status": "in_progress" if state == "pending" else "completed",
            "conclusion": None if state == "pending" else state, "html_url": "https://checks/1"}


def commit_status(state="success", name="hca-check"):
    return {"context": name, "state": state, "target_url": "https://statuses/1"}


def check_responses(runs=(), statuses=(), sha="abc123"):
    return [(0, json.dumps([{"check_runs": list(runs)}])),
            (0, json.dumps([{"sha": sha, "statuses": list(statuses)}]))]


@pytest.mark.parametrize("source, state", [
    (source, state) for source, states in (
        ("run", ("success", "failure", "pending", "cancelled", "timed_out", "action_required",
                 "neutral", "skipped", "stale", "startup_failure", None)),
        ("status", ("success", "failure", "pending", "error"))) for state in states
])
def test_merge_requires_success_on_reviewed_head(tmp_path, monkeypatch, capsys, source, state):
    loaded = settings(tmp_path, 'repo = "o/r"\n[merge]\nrequired_checks = ["hca-check"]')
    calls = []
    responses = [view()] + check_responses(
        runs=[check_run(state)] if source == "run" else [],
        statuses=[commit_status(state)] if source == "status" else [])
    if state == "success":
        responses += [(0, ""), view("MERGED")]
    monkeypatch.setattr(orchestrate, "call", fake_call(responses, calls))
    assert orchestrate.merge(SimpleNamespace(pr=7, sha="abc"), loaded) == (0 if state == "success" else 1)
    assert calls[1] == ("gh", "api", "--paginate", "--slurp",
                        "repos/o/r/commits/abc123/check-runs?filter=latest&per_page=100")
    assert calls[2] == ("gh", "api", "--paginate", "--slurp", "repos/o/r/commits/abc123/status?per_page=100")
    if state == "success":
        assert calls[3][-2:] == ("--match-head-commit", "abc123")
    else:
        error = capsys.readouterr().err
        assert "hca-check" in error and "abc123" in error
        assert (state or "pending") in error
        if state == "pending" or state is None:
            assert "has not finished" in error
        if source == "run":
            assert "https://checks/1" in error
        else:
            assert "https://statuses/1" in error
        assert len(calls) == 3
    assert not responses


@pytest.mark.parametrize("runs, statuses, sha", [
    ([], [], "abc123"),
    ([check_run(sha="fff999")], [], "abc123"),
    ([], [commit_status()], "fff999"),
    ([check_run(name="other")], [commit_status(name="other")], "abc123"),
])
def test_merge_missing_or_other_commit_checks_do_not_count(tmp_path, monkeypatch, capsys, runs, statuses, sha):
    loaded = settings(tmp_path, 'repo = "o/r"\n[merge]\nrequired_checks = ["hca-check"]')
    calls = []
    monkeypatch.setattr(orchestrate, "call", fake_call([view()] + check_responses(runs, statuses, sha), calls))
    assert orchestrate.merge(SimpleNamespace(pr=7, sha="abc"), loaded) == 1
    assert "check hca-check has not finished on abc123 (missing)" in capsys.readouterr().err
    assert len(calls) == 3


def test_merge_checks_all_pages_and_both_sources(tmp_path, monkeypatch):
    loaded = settings(tmp_path, 'repo = "o/r"\n[merge]\nrequired_checks = ["hca-check", "deploy"]')
    responses = [view(), (0, json.dumps([{"check_runs": []}, {"check_runs": [check_run()]}])),
                 (0, json.dumps([{"sha": "abc123", "statuses": []},
                                 {"sha": "abc123", "statuses": [commit_status(name="deploy")]}])),
                 (0, ""), view("MERGED")]
    monkeypatch.setattr(orchestrate, "call", fake_call(responses, []))
    assert orchestrate.merge(SimpleNamespace(pr=7, sha="abc"), loaded) == 0
    assert not responses


def test_merge_reports_every_failed_required_check_and_duplicate(tmp_path, monkeypatch, capsys):
    loaded = settings(tmp_path, 'repo = "o/r"\n[merge]\nrequired_checks = ["hca-check", "deploy"]')
    calls = []
    responses = [view()] + check_responses([check_run(), check_run("failure")], [commit_status("error", "deploy")])
    monkeypatch.setattr(orchestrate, "call", fake_call(responses, calls))
    assert orchestrate.merge(SimpleNamespace(pr=7, sha="abc"), loaded) == 1
    error = capsys.readouterr().err
    assert "hca-check is failure" in error and "deploy is error" in error
    assert "https://checks/1" in error and "https://statuses/1" in error
    assert len(calls) == 3


@pytest.mark.parametrize("responses", [
    [(1, "")], [(0, "not json")], [(0, "[{}]")],
    [(0, '{"check_runs": []}')],
    [(0, '[{"check_runs": []}]'), (1, "")],
])
def test_merge_refuses_unreadable_check_data(tmp_path, monkeypatch, capsys, responses):
    loaded = settings(tmp_path, 'repo = "o/r"\n[merge]\nrequired_checks = ["hca-check"]')
    calls = []
    monkeypatch.setattr(orchestrate, "call", fake_call([view()] + responses, calls))
    assert orchestrate.merge(SimpleNamespace(pr=7, sha="abc"), loaded) == 1
    assert "cannot read" in capsys.readouterr().err
    assert not any(call[:3] == ("gh", "pr", "merge") for call in calls)


@pytest.mark.parametrize("pr", [view(draft=True), view(head="fff999")])
def test_merge_existing_gates_run_before_required_checks(tmp_path, monkeypatch, pr):
    loaded = settings(tmp_path, 'repo = "o/r"\n[merge]\nrequired_checks = ["hca-check"]')
    calls = []
    monkeypatch.setattr(orchestrate, "call", fake_call([pr], calls))
    assert orchestrate.merge(SimpleNamespace(pr=7, sha="abc"), loaded) == 1
    assert not any("/commits/" in argument for call in calls for argument in call)


def test_merge_empty_required_checks_keeps_existing_behavior(tmp_path, monkeypatch):
    loaded = settings(tmp_path, 'repo = "o/r"\n[merge]\nrequired_checks = []')
    calls = []
    monkeypatch.setattr(orchestrate, "call", fake_call([view(), (0, ""), view("MERGED")], calls))
    assert orchestrate.merge(SimpleNamespace(pr=7, sha="abc"), loaded) == 0
    assert len(calls) == 3 and calls[1][:3] == ("gh", "pr", "merge")


REFRESH = 'repo = "o/r"\n[merge]\nrequired_checks = ["hca-check"]\nrefresh = "hca-refresh {pr} --head {sha} --base {tip} \'a b\'"'


def tip(sha):
    return 0, json.dumps({"ref": "refs/heads/main", "object": {"sha": sha, "type": "commit"}})


def refresh_calls(calls):
    return [call for call in calls if call[0] == "hca-refresh"]


def test_merge_refresh_failure_refuses_before_merging(tmp_path, monkeypatch, capsys):
    loaded = settings(tmp_path, REFRESH)
    calls = []
    output = "\n".join(f"line {n}" for n in range(30))
    responses = [view(), *check_responses([check_run()]), tip("t1"), (1, output)]
    monkeypatch.setattr(orchestrate, "call", fake_call(responses, calls))
    assert orchestrate.merge(SimpleNamespace(pr=7, sha="abc"), loaded) == 1
    captured = capsys.readouterr()
    error = captured.err
    assert "refresh exited 1 against main t1" in error and "merge refused" in error
    assert "ding: refresh against main t1" in error and "refresh passed" not in error and captured.out == ""
    assert "line 29" in error and "boom" in error and "line 9\n" not in error
    assert calls[3] == ("gh", "api", "repos/o/r/git/ref/heads/main")
    assert not any(call[:3] == ("gh", "pr", "merge") for call in calls)
    assert not responses


def test_merge_refresh_success_substitutes_pr_and_sha_and_rereads_checks(tmp_path, monkeypatch, capsys):
    loaded = settings(tmp_path, REFRESH)
    calls = []
    responses = [view(), *check_responses([check_run()]), tip("t1"), (0, "fresh"),
                 *check_responses([check_run()]), tip("t1"), (0, ""), view("MERGED")]
    monkeypatch.setattr(orchestrate, "call", fake_call(responses, calls))
    assert orchestrate.merge(SimpleNamespace(pr=7, sha="abc"), loaded) == 0
    assert refresh_calls(calls) == [("hca-refresh", "7", "--head", "abc123", "--base", "t1", "a b")]
    assert calls[5][-1].endswith("commits/abc123/check-runs?filter=latest&per_page=100")
    assert calls[-2][:3] == ("gh", "pr", "merge") and calls[-2][-2:] == ("--match-head-commit", "abc123")
    captured = capsys.readouterr()
    assert "ding: refresh against main t1: hca-refresh 7 --head abc123 --base t1 'a b'" in captured.err
    assert "ding: refresh passed: fresh" in captured.err
    assert captured.out == "PR #7 merged as m1\n"
    assert not responses


def test_merge_refresh_runs_without_required_checks(tmp_path, monkeypatch):
    loaded = settings(tmp_path, 'repo = "o/r"\n[merge]\nrefresh = "hca-refresh {pr}"')
    calls = []
    responses = [view(), tip("t1"), (0, ""), tip("t1"), (0, ""), view("MERGED")]
    monkeypatch.setattr(orchestrate, "call", fake_call(responses, calls))
    assert orchestrate.merge(SimpleNamespace(pr=7, sha="abc"), loaded) == 0
    assert refresh_calls(calls) == [("hca-refresh", "7")]
    assert not responses


def test_merge_refresh_that_fails_a_required_check_refuses(tmp_path, monkeypatch, capsys):
    loaded = settings(tmp_path, REFRESH)
    calls = []
    responses = [view(), *check_responses([check_run()]), tip("t1"), (0, ""),
                 *check_responses([], [commit_status("failure")])]
    monkeypatch.setattr(orchestrate, "call", fake_call(responses, calls))
    assert orchestrate.merge(SimpleNamespace(pr=7, sha="abc"), loaded) == 1
    assert "readiness blocks merge after refresh" in capsys.readouterr().err
    assert not any(call[:3] == ("gh", "pr", "merge") for call in calls)
    assert not responses


def test_merge_refresh_runs_again_when_the_tip_moves(tmp_path, monkeypatch):
    loaded = settings(tmp_path, REFRESH)
    calls = []
    responses = [view(), *check_responses([check_run()]), tip("t1"),
                 (0, ""), *check_responses([check_run()]), tip("t2"),
                 (0, ""), *check_responses([check_run()]), tip("t2"), (0, ""), view("MERGED")]
    monkeypatch.setattr(orchestrate, "call", fake_call(responses, calls))
    assert orchestrate.merge(SimpleNamespace(pr=7, sha="abc"), loaded) == 0
    assert [call[5] for call in refresh_calls(calls)] == ["t1", "t2"]
    assert not responses


def test_merge_refresh_refuses_when_the_tip_keeps_moving(tmp_path, monkeypatch, capsys):
    loaded = settings(tmp_path, REFRESH)
    calls = []
    responses = [view(), *check_responses([check_run()]), tip("t0")]
    for n in range(1, 4):
        responses += [(0, ""), *check_responses([check_run()]), tip(f"t{n}")]
    monkeypatch.setattr(orchestrate, "call", fake_call(responses, calls))
    assert orchestrate.merge(SimpleNamespace(pr=7, sha="abc"), loaded) == 1
    assert "main kept moving" in capsys.readouterr().err
    assert [call[5] for call in refresh_calls(calls)] == ["t0", "t1", "t2"]
    assert not any(call[:3] == ("gh", "pr", "merge") for call in calls)
    assert not responses


def test_merge_refresh_that_cannot_start_refuses(tmp_path, monkeypatch, capsys):
    loaded = settings(tmp_path, REFRESH)
    calls = []
    inner = fake_call([view(), *check_responses([check_run()]), tip("t1")], calls)

    def call(settings, *args):
        if args[0] == "hca-refresh":
            raise FileNotFoundError(2, "No such file or directory", "hca-refresh")
        return inner(settings, *args)
    monkeypatch.setattr(orchestrate, "call", call)
    assert orchestrate.merge(SimpleNamespace(pr=7, sha="abc"), loaded) == 1
    assert "refresh could not run (hca-refresh 7 --head abc123 --base t1 'a b')" in capsys.readouterr().err


def test_merge_refresh_does_not_run_when_readiness_already_blocks(tmp_path, monkeypatch):
    loaded = settings(tmp_path, REFRESH)
    calls = []
    monkeypatch.setattr(orchestrate, "call", fake_call([view(), *check_responses([check_run("failure")])], calls))
    assert orchestrate.merge(SimpleNamespace(pr=7, sha="abc"), loaded) == 1
    assert not refresh_calls(calls) and len(calls) == 3


def test_merge_refresh_defaults_to_off(tmp_path):
    assert settings(tmp_path).merge.refresh == ""
    assert settings(tmp_path, '[merge]\nrefresh = ""').merge.refresh == ""


@pytest.mark.parametrize("argv, phrases", [
    ([], ("List sessions", "latest final reply", "status as JSON", "Send a message", "message a session when it exits",
          "new tmux session", "review")),
    (["merge"], ("required_checks", "review_check", "no bypass", "refresh")),
    (["night"], ("open", "show", "close", "[log] issue", "calls no model")),
    (["watch"], ("--for NAME", "executor comments waiting on", "review:<NAME>", "stale/idle", "[roles.aliases]",
                 "[status] paused", "design_answer_minutes", "awaiting-user", "status labels older")),
    (["waits"], ("--for", "--minutes", "--json", "Read-only", "design_answer_minutes")),
    (["review"], ("--body-file", "review_check")),
    (["rule"], ("--reply-to", "--notify", "--no-notify", "notify_types", "--edit-body", "--base", "--force",
                "check-refs", "SendMessage")),
])
def test_help_names_what_agents_look_up(capsys, argv, phrases):
    """Skills send agents to `ding ... --help`, so these phrases are what an agent reads there."""
    with pytest.raises(SystemExit) as exc:
        ding.main([*argv, "--help"])
    assert exc.value.code == 0
    text = " ".join(capsys.readouterr().out.split())
    assert [phrase for phrase in phrases if phrase not in text] == []


@pytest.mark.parametrize("argv, error", [
    (["merge", "7", "abc", "--ticket", "3"], "unrecognized arguments: --ticket"),
    (["merge", "7", "abc", "--no-ticket"], "unrecognized arguments: --no-ticket"),
])
def test_merge_has_no_ticket_gate_options(capsys, argv, error):
    with pytest.raises(SystemExit) as exc:
        ding.main(argv)
    assert exc.value.code == 2
    assert error in capsys.readouterr().err


def test_merge_command_reaches_the_gate(tmp_path, monkeypatch):
    loaded = settings(tmp_path, 'repo = "o/r"')
    monkeypatch.setattr(config, "load", lambda: loaded)
    calls = []
    monkeypatch.setattr(orchestrate, "call", fake_call([view(), (0, ""), view("MERGED")], calls))
    assert ding.main(["merge", "7", "abc"]) == 0
    assert calls[1][:3] == ("gh", "pr", "merge")


def test_log_needs_a_ticket(tmp_path, capsys):
    args = SimpleNamespace(item=["a"], pending=[], issue=None)
    assert orchestrate.log(args, settings(tmp_path)) == 1
    assert "[log] issue" in capsys.readouterr().err


@pytest.fixture
def night_log(tmp_path, monkeypatch):
    class Clock(datetime):
        moment = datetime(2026, 10, 30, 20, tzinfo=timezone.utc)

        @classmethod
        def now(cls, tz=None):
            return cls.moment

    monkeypatch.setattr(night, "datetime", Clock)
    monkeypatch.chdir(tmp_path)
    loaded = settings(tmp_path, CHINESE + '\n[night]\nheading = "总编排：用户裁定（夜令"\nclosed = "总编排：夜令结束"')
    draft = tmp_path / "orders.md"
    draft.write_text('User reply, verbatim:\n全部同意，除了 3。\n\n1. Service A may start.\n', encoding="utf-8")
    state = SimpleNamespace(config=loaded, clock=Clock, comments=[], calls=[], draft=draft, post_codes=[])

    def call(settings, *args):
        state.calls.append(args)
        if args[:3] == ("gh", "api", "graphql"):
            assert f"number={loaded.log.issue}" in args and "owner=o" in args and "name=r" in args
            payload = {"data": {"repository": {"issue": {"comments": {
                "nodes": state.comments, "pageInfo": {"hasPreviousPage": False, "startCursor": None}}}}}}
            return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")
        assert args[:4] == ("gh", "issue", "comment", "246")
        code = state.post_codes.pop(0) if state.post_codes else 0
        url = f"https://github.com/o/r/issues/246#issuecomment-{len(state.comments) + 1}"
        if not code:
            state.comments.append({"body": args[-1], "url": url})
        return SimpleNamespace(returncode=code, stdout=url, stderr="post failed" if code else "")

    monkeypatch.setattr(night, "call", call)
    monkeypatch.setattr(orchestrate, "call", call)
    state.open = lambda *options: ding.main(["night", "open", "--until", "2026-10-31T16:00:00+08:00",
                                           "--body-file", str(draft), *options])
    return state


def test_night_open_preserves_reply_and_refuses_duplicate_without_replace(night_log, capsys):
    ticket = night_log
    assert ticket.open() == 0
    assert ticket.comments[0]["body"] == (
        "总编排：用户裁定（夜令, until 2026-10-31T08:00:00Z)\n\n" + ticket.draft.read_text(encoding="utf-8"))
    assert capsys.readouterr().out.strip() == ticket.comments[0]["url"]
    assert ticket.open() == 1
    assert "already open" in capsys.readouterr().err
    assert len(ticket.comments) == 1
    assert ticket.open("--replace") == 0
    assert ticket.comments[1]["body"] == "总编排：夜令结束 at 2026-10-30T20:00:00Z"
    assert ticket.comments[2]["body"] == ticket.comments[0]["body"]


def test_night_show_and_close_use_log_comments_only(night_log, capsys):
    ticket = night_log
    assert ticket.open() == 0
    capsys.readouterr()
    ticket.comments.append({"body": "总编排：21:00 UTC\n- #42 followed order 1", "url": "https://log"})
    assert ding.main(["night", "show"]) == 0
    assert capsys.readouterr().out == ticket.comments[0]["body"] + "\n" + ticket.comments[0]["url"] + "\n"
    assert len(ticket.calls) == 3  # open reads and posts; show reads once
    assert ding.main(["night", "close"]) == 0
    assert ticket.comments[-1]["body"] == "总编排：夜令结束 at 2026-10-30T20:00:00Z"
    capsys.readouterr()
    assert ding.main(["night", "show"]) == 0
    assert capsys.readouterr().out == "no night orders open\n"
    assert ding.main(["night", "close"]) == 0
    assert len(ticket.comments) == 3


@pytest.mark.parametrize("moment", ["2026-10-31T08:00:00+00:00", "2026-10-31T09:00:00+00:00"])
def test_night_orders_expire_without_a_closing_comment(night_log, capsys, moment):
    ticket = night_log
    assert ticket.open() == 0
    ticket.clock.moment = datetime.fromisoformat(moment)
    capsys.readouterr()
    assert ding.main(["night", "show"]) == 0
    assert capsys.readouterr().out == "no night orders open\n"
    assert len(ticket.comments) == 1
    ticket.clock.moment += timedelta(hours=1)
    assert ding.main(["night", "open", "--until", "2026-11-01T08:00:00Z", "--body-file", str(ticket.draft)]) == 0
    assert len(ticket.comments) == 2


def test_night_without_orders_exits_zero(night_log, capsys):
    assert ding.main(["night", "show"]) == 0
    assert capsys.readouterr().out == "no night orders open\n"


def test_night_commands_work_without_a_night_config_section(night_log, capsys):
    settings(night_log.config.root, 'repo = "o/r"\n[log]\nissue = 246')
    assert night_log.open() == 0
    assert night_log.comments[0]["body"].startswith("Orchestrator: user decision (night orders, until ")
    assert ding.main(["night", "close"]) == 0
    assert night_log.comments[-1]["body"].startswith("Orchestrator: night orders closed at ")
    capsys.readouterr()
    assert ding.main(["night", "show"]) == 0
    assert capsys.readouterr().out == "no night orders open\n"


def test_expired_newer_orders_do_not_revive_older_orders(night_log, capsys):
    assert night_log.open() == 0
    newer = {**night_log.comments[0], "body": night_log.comments[0]["body"].replace(
        "2026-10-31T08:00:00Z", "2026-10-30T21:00:00Z")}
    night_log.comments.append(newer)
    night_log.clock.moment += timedelta(hours=2)
    capsys.readouterr()
    assert ding.main(["night", "show"]) == 0
    assert capsys.readouterr().out == "no night orders open\n"


@pytest.mark.parametrize("until, error", [
    ("tomorrow", "ISO time with timezone"),
    ("2026-10-31", "ISO time with timezone"),
    ("2026-10-31T08:00:00", "ISO time with timezone"),
    ("2026-10-30T20:00:00Z", "must be in the future"),
])
def test_night_rejects_invalid_or_expired_window_before_any_api_call(night_log, capsys, until, error):
    assert ding.main(["night", "open", "--until", until, "--body-file", str(night_log.draft)]) == 1
    assert error in capsys.readouterr().err
    assert night_log.calls == []


@pytest.mark.parametrize("body", [None, " \n"])
def test_night_rejects_missing_or_empty_body_before_any_api_call(night_log, body):
    if body is None:
        night_log.draft.unlink()
    else:
        night_log.draft.write_text(body)
    assert night_log.open() == 1
    assert night_log.calls == []


@pytest.mark.parametrize("codes, posted", [([1], 1), ([0, 1], 2)])
def test_night_replace_reports_post_failure_and_stops(night_log, capsys, codes, posted):
    assert night_log.open() == 0
    capsys.readouterr()
    night_log.post_codes = codes
    assert night_log.open("--replace") == 1
    assert "post failed" in capsys.readouterr().err
    assert len(night_log.comments) == posted


def test_night_searches_backwards_only_until_latest_marker(night_log, monkeypatch, capsys):
    assert night_log.open() == 0
    orders = night_log.comments[0]
    calls = []
    pages = [([{"body": "routine log", "url": "https://log"}] * 100, True, "older"), ([orders], True, "oldest")]

    def read(settings, *args):
        calls.append(args)
        nodes, previous, cursor = pages.pop(0)
        return SimpleNamespace(returncode=0, stdout=json.dumps({"data": {"repository": {"issue": {"comments": {
            "nodes": nodes, "pageInfo": {"hasPreviousPage": previous, "startCursor": cursor}}}}}}))

    monkeypatch.setattr(night, "call", read)
    capsys.readouterr()
    assert ding.main(["night", "show"]) == 0
    assert orders["url"] in capsys.readouterr().out
    assert len(calls) == 2 and "before=older" in calls[1]
    assert all(args[:3] == ("gh", "api", "graphql") for args in calls)


@pytest.mark.parametrize("payload, code", [({}, 1), ({"errors": ["denied"]}, 0), ({"data": {"repository": None}}, 0)])
def test_night_read_errors_are_not_treated_as_no_orders(night_log, monkeypatch, capsys, payload, code):
    monkeypatch.setattr(night, "call", lambda *args: SimpleNamespace(returncode=code, stdout=json.dumps(payload), stderr="denied"))
    assert night_log.open() == 1
    assert "cannot read night orders" in capsys.readouterr().err
    assert night_log.comments == []


def test_malformed_order_time_does_not_allow_a_duplicate_open(night_log, capsys):
    assert night_log.open() == 0
    night_log.comments[0]["body"] = night_log.comments[0]["body"].replace("2026-10-31T08:00:00Z", "tomorrow")
    assert night_log.open() == 1
    assert "cannot read night orders" in capsys.readouterr().err
    assert len(night_log.comments) == 1


def test_night_defaults_and_missing_log_issue(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    loaded = settings(tmp_path)
    assert loaded.night.heading == "Orchestrator: user decision (night orders"
    assert loaded.night.closed == "Orchestrator: night orders closed"
    assert ding.main(["night", "show"]) == 1
    assert "[log] issue" in capsys.readouterr().err


def test_live_tmux_jobs_count_as_running_but_shells_and_dead_panes_do_not():
    panes = ("ding-issue235-r3-8|0|python\n"
             "ding-issue193-B008-audit|1|sh\n"
             "issue209-stage1-concurrency8-r2|0|bash\n"
             "ding-issue272-a-v2-xhigh-full|0|python\n"
             "download_model|0|python\n")
    assert watch.tmux_issues(panes, config.Config(root=Path("/r"))) == {235, 272}


LAUNCHER = "claude:local_11111111-2222-4333-8444-555555555555"
LAUNCH_PANES = "ding-t1-sweep|0|python|{pid}\n"


def init_checkout(path):
    path.mkdir(parents=True)
    run_git(path, "init", "-q", "-b", "main")
    run_git(path, "commit", "-q", "--allow-empty", "-m", "first")
    return path


@pytest.fixture
def kitchen(tmp_path):
    return init_checkout(tmp_path / "kitchen")


@pytest.fixture
def launched_job(tmp_path, monkeypatch, kitchen):
    """Starts a running `ding run` registered by LAUNCHER in a directory, as `ding launch` execs it in its tmux pane,
    and returns the tmux panes listing that shows it."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    comment = {"issue_url": "https://api.github.com/repos/o/r/issues/26", "created_at": "2026-10-28T10:00:00Z",
               "body": f"In progress\n\nClaude owner: {LAUNCHER.removeprefix('claude:')}\n"}
    old = {**comment, "issue_url": "https://api.github.com/repos/o/r/issues/9",
           "body": "Claude owner: local_99999999-2222-4333-8444-555555555555\n"}
    issues = [{"number": 26, "body": "", "created_at": "2026-10-28T09:00:00Z"},
              {"number": 9, "body": "", "created_at": "2026-10-20T09:00:00Z"}]
    monkeypatch.setattr(ding, "gh_records", lambda resource: issues if "/issues?" in resource else [old, comment])
    lookups = []
    real = ding.issue_map
    monkeypatch.setattr(ding, "issue_map", lambda repo=None: lookups.append(repo) or real(repo))
    stack = contextlib.ExitStack()

    def start(cwd=kitchen):
        monkeypatch.chdir(cwd)
        stack.enter_context(ding.registered_run(LAUNCHER, tmp_path / "exit.jsonl"))
        return LAUNCH_PANES.format(pid=os.getpid())

    start.lookups = lookups
    with stack:
        yield start


def test_launch_job_without_issue_in_its_name_belongs_to_the_ticket_its_session_owns(launched_job, kitchen):
    assert watch.tmux_issues(launched_job(), config.Config(root=kitchen), "o/r") == {26}


def test_launch_job_from_a_worktree_of_the_kitchen_checkout_belongs_to_the_kitchen(launched_job, kitchen, tmp_path):
    run_git(kitchen, "worktree", "add", "-q", str(tmp_path / "wt"))
    assert watch.tmux_issues(launched_job(tmp_path / "wt"), config.Config(root=kitchen), "o/r") == {26}


def test_launch_job_from_the_code_checkout_of_a_split_kitchen_belongs_to_the_kitchen(launched_job, kitchen, tmp_path):
    code = init_checkout(tmp_path / "code")
    run_git(code, "worktree", "add", "-q", str(tmp_path / "code-wt"))
    loaded = config.Config(root=kitchen, code_root=code)
    assert watch.tmux_issues(launched_job(tmp_path / "code-wt"), loaded, "o/r") == {26}


def test_another_projects_live_job_adds_no_ticket_and_costs_no_lookup(launched_job, kitchen, tmp_path):
    other = init_checkout(tmp_path / "other")
    assert watch.tmux_issues(launched_job(other), config.Config(root=kitchen), "o/r") == set()
    assert launched_job.lookups == []


def test_job_started_outside_any_checkout_is_not_the_kitchens(launched_job, kitchen, tmp_path):
    (tmp_path / "plain").mkdir()
    assert watch.tmux_issues(launched_job(tmp_path / "plain"), config.Config(root=kitchen), "o/r") == set()
    assert launched_job.lookups == []


def test_launch_job_name_with_issue_wins_and_needs_no_lookup(launched_job, kitchen):
    pane = launched_job().replace("t1-sweep", "t1-issue9-sweep")
    assert watch.tmux_issues(pane, config.Config(root=kitchen), "o/r") == {9}
    assert launched_job.lookups == []


def test_named_pane_whose_run_is_another_kitchens_is_not_counted(launched_job, kitchen, tmp_path):
    other = init_checkout(tmp_path / "other")
    pane = launched_job(other).replace("t1-sweep", "train-issue43-x")
    assert watch.tmux_issues(pane, config.Config(root=kitchen), "o/r") == set()


def test_named_pane_without_a_run_still_counts(launched_job, kitchen):
    pane = LAUNCH_PANES.format(pid=os.getpid() + 1).replace("t1-sweep", "train-issue43-x")
    assert watch.tmux_issues(pane, config.Config(root=kitchen), "o/r") == {43}


def test_pane_matching_no_live_run_is_not_attributed(launched_job, kitchen):
    launched_job()
    assert watch.tmux_issues(LAUNCH_PANES.format(pid=os.getpid() + 1), config.Config(root=kitchen), "o/r") == set()


def test_registered_run_that_has_ended_is_not_attributed(monkeypatch, launched_job, kitchen):
    pane = launched_job()
    monkeypatch.setattr(ding, "run_state", lambda run: "lost")
    assert watch.tmux_issues(pane, config.Config(root=kitchen), "o/r") == set()


def test_stale_sees_a_launched_job_by_its_session_not_its_name(idle_ticket, launched_job, kitchen):
    ticket = idle_ticket
    ticket.clock.moment += timedelta(hours=6)
    ticket.config = config.Config(root=kitchen, repo="o/r")
    ticket.panes = launched_job()
    assert watch.stale(ticket.config, "o/r", ticket.config.root, 6, set(), set()) == []


def test_board_running_reads_only_the_session_table():
    output = ("NAME\tCWD\tSTATUS\tISSUE\tHEAD\tRUN\n"
              "a\t/r\tactive\t#3,#5\thead\trunning\n"
              "b\t/r\tidle\t#4\thead\texited(0)\n"
              "\nUNWRAPPED_PID\tCPU%\tAGE_SECONDS\tTMUX_SESSION\tissue9\trunning\n")
    assert watch.board_running(output) == {3, 5}


def test_second_watch_on_the_same_state_exits(tmp_path):
    state = tmp_path / "watch.json"
    args = SimpleNamespace(state=state, checkout=None, since=None, skip_issue=[])
    with (tmp_path / "watch.lock").open("w") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert watch.watch(args, settings(tmp_path, 'repo = "o/r"')) == 3
    assert not state.exists()


def comment(number, body):
    return {"issue_url": f"https://api.github.com/repos/o/r/issues/{number}", "body": body,
            "created_at": "2026-10-14T09:00:00Z", "updated_at": "2026-10-14T09:00:00Z", "html_url": f"u{number}"}


@pytest.mark.parametrize("text, verifier, user", [
    (None, "## Verifier: checked before the run\npass", "I filled in the review"),
    (CHINESE, "## 核查：运行前核对\n通过", "我填好了复核"),
])
def test_verifier_comments_are_listed_without_waking(tmp_path, monkeypatch, text, verifier, user):
    loaded = settings(tmp_path, text)
    comments = [comment(272, verifier), comment(234, user)]
    monkeypatch.setattr(watch, "gh", lambda path: comments if "/issues/comments" in path and "page=1" in path else [])
    found = watch.collect(loaded, "o/r", "2026-10-14T08:00:00Z", "2026-10-14T08:00:00Z", set(), set())
    roles = loaded.roles
    assert [(line.split(":")[0].split(" (")[0], wakes) for _, line, wakes in found] == [
        (f"#234 {roles.user} comment", True), (f"#272 {roles.verifier} comment", False)]


def executor(block):
    return block + "\n\nCodex session: 00000000-0000-4000-8000-000000000001"


@pytest.mark.parametrize("block, waiting_user, wakes", [
    ("Status: in progress\nWaiting on: none\nKey numbers: 1\nNext: run", False, False),
    ("Status: in progress\nWaiting on: Designer, for the prompt\nKey numbers: 1\nNext: wait", False, True),
    ("Status: done\nWaiting on: none\nKey numbers: 1\nNext: merge", False, True),
    ("Status: waiting on user\nWaiting on: User\nKey numbers: 1\nNext: wait", True, False),
    ("Status: waiting on user\nWaiting on: User to approve; Orchestrator to merge PR #3\nKey numbers: 1\nNext: merge",
     True, True),
    ("Status: blocked\nWaiting on: none\nKey numbers: 1\nNext: fix", True, True),
])
def test_executor_comments_wake_by_status_and_waiting_on(tmp_path, block, waiting_user, wakes):
    loaded = settings(tmp_path)
    assert watch.signer(executor(block), loaded) == "Executor"
    assert watch.executor_wakes(executor(block), waiting_user, loaded) is wakes


def test_chinese_status_words_and_full_width_colons(tmp_path):
    loaded = settings(tmp_path, CHINESE)
    body = executor("状态：进行中\n在等：总设计，要提示词\n关键数字：1\n下一步：等")
    assert watch.executor_wakes(body, False, loaded)
    assert watch.summary(body, loaded) == "状态：进行中; 在等：总设计，要提示词"
    assert not watch.executor_wakes(executor("状态: 进行中\n在等: 无\n关键数字: 1\n下一步: 跑"), False, loaded)


def test_an_awaiting_user_ticket_wakes_when_the_comment_also_waits_on_the_kitchen(tmp_path):
    # #209 issuecomment-6179869282: still waiting on the user, but also asking the orchestrator to merge
    loaded = settings(tmp_path, CHINESE)
    body = executor("状态: 等用户\n在等: 用户批准说话人 1,329 次单次作答；总编排重审合入 PR #314\n关键数字: 0\n下一步: 合入")
    assert watch.executor_wakes(body, True, loaded)
    assert not watch.executor_wakes(executor("状态: 等用户\n在等: 用户批准\n关键数字: 0\n下一步: 等"), True, loaded)


@pytest.fixture
def tree(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "work.py").write_text("import os\n\n\ndef reserve(key):\n    if key:\n        raise ValueError(key)\n\n\nclass Ledger:\n    pass\n")
    return tmp_path


def check(draft, tree, tolerance=0):
    return refs.check(draft, refs.Source("HEAD", tree), tolerance)


def test_line_reference_must_hold_the_name_beside_it(tree):
    findings, notes, checked = check("`pkg/work.py:9` holds `Ledger`; `pkg/work.py:6` holds `Ledger`", tree)
    assert checked == 2 and notes == []
    assert len(findings) == 1 and findings[0].startswith("line 1 `pkg/work.py:6`") and "`Ledger`" in findings[0]
    assert check("`pkg/work.py:5-6` uses `key`", tree)[0] == []


def test_name_of_the_enclosing_function_counts_and_tolerance_widens(tree):
    assert check("`pkg/work.py:6` in `reserve` refuses", tree)[0] == []
    assert check("`pkg/work.py:5` has `raise`", tree)[0] != []
    assert check("`pkg/work.py:5` has `raise`", tree, tolerance=1)[0] == []


def test_reference_beyond_the_file_or_to_a_missing_file(tree):
    findings, notes, checked = check("`pkg/work.py:99` and `pkg/gone.py:1`", tree)
    assert findings == ["line 1 `pkg/work.py:99`: beyond the end of the file (10 lines)"]
    assert notes == ["line 1 `pkg/gone.py:1`: no such file, or several files share the name; not checked"]
    assert checked == 1


def test_names_far_from_the_reference_and_times_in_prose_are_ignored(tree):
    assert check("`pkg/work.py:9` was there before 07:47, see also the notes on `Missing`", tree) == ([], [], 1)


def test_sha256_prefix_and_suffix_are_checked_against_the_cited_file(tree):
    digest = hashlib.sha256((tree / "pkg" / "work.py").read_bytes()).hexdigest()
    assert check(f"`pkg/work.py` sha256 `{digest[:8]}…{digest[-4:]}`", tree)[0] == []
    findings, _, checked = check(f"`pkg/work.py` sha256 `{digest[:7]}0`", tree)
    assert checked == 1 and findings and "sha256" in findings[0]
    findings, notes, checked = check(f"sha256 `{digest[:8]}`", tree)
    assert (findings, checked) == ([], 0) and len(notes) == 1


def test_check_refs_command_reports_and_exits_nonzero_on_findings(tree, capsys):
    draft = tree / "draft.md"
    draft.write_text("`pkg/work.py:6` holds `Ledger`\n")
    assert ding.main(["check-refs", str(draft), "--root", str(tree)]) == 1
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert {key: report[key] for key in ("checked", "findings", "unchecked", "by_kind")} == {
        "checked": 1, "findings": 1, "unchecked": 0, "by_kind": {"file:line": 1}}
    assert report["wrong"][0].startswith("line 1 `pkg/work.py:6`")
    assert "checked 1 references (1 file:line): 1 wrong, 0 not checked" in captured.err


GITHUB = {
    "repos/o/r/issues/433": {"number": 433},
    "repos/o/r/issues/543": {"number": 543, "pull_request": {}},
    "repos/o/r/issues/comments/111": {"issue_url": "https://api.github.com/repos/o/r/issues/433"},
    "repos/o/r/issues/comments/222": {"issue_url": "https://api.github.com/repos/o/r/issues/535"},
}


def fake_github(path):
    if path == "repos/o/r/issues/9":
        raise RuntimeError("HTTP 502")
    return GITHUB.get(path)


def test_tickets_prs_and_comment_links_are_checked_against_github(tree):
    github = refs.GitHub("o/r", fake_github)
    counts = {}
    draft = ("见 #433 和 PR#543；#544 不存在，PR #433 不是 PR\n"
             "https://github.com/o/r/issues/433#issuecomment-111 https://github.com/o/r/issues/433#issuecomment-222\n"
             "https://github.com/o/r/pull/543 https://github.com/o/r/issues/543 #9")
    findings, notes, checked = refs.check(draft, refs.Source("HEAD", tree), 0, github, counts)
    assert findings == [
        "line 1 ticket #544: o/r#544 does not exist",
        "line 1 PR PR #433: o/r#433 is an issue, not a PR",
        "line 2 comment link https://github.com/o/r/issues/433#issuecomment-222: comment issuecomment-222 "
        "belongs to #535, not #433",
        "line 3 ticket link https://github.com/o/r/issues/543: o/r#543 is a PR; its link is /pull/543",
    ]
    assert notes == ["line 3 ticket #9: not checked (HTTP 502)"]
    assert counts == {"ticket": 2, "PR": 2, "comment link": 2, "PR link": 1, "ticket link": 1}
    assert checked == 8


def test_bare_line_references_are_checked_and_offline_lists_tickets(tree):
    findings, notes, checked = refs.check("pkg/work.py:99 改了；见 #433", refs.Source("HEAD", tree), 0)
    assert findings == ["line 1 `pkg/work.py:99`: beyond the end of the file (10 lines)"]
    assert notes == ["line 1 ticket #433: not checked (GitHub checks are off (--offline))"]
    assert checked == 1


def test_log_issue_must_be_positive(capsys):
    with pytest.raises(SystemExit) as exc:
        ding.main(["log", "--item", "a", "--issue", "0"])
    assert exc.value.code == 2


@pytest.mark.parametrize("text", [None, CHINESE])
def test_a_quoted_session_signature_signs_nothing(tmp_path, text):
    loaded = settings(tmp_path, text)
    roles = loaded.roles
    verifier = (f"## {roles.verifier}{roles.separator}#272 run request check\n\n"
                "| request body | ok: it starts with the status block and contains `Codex session:` |\n")
    assert watch.signer(verifier, loaded) == roles.verifier
    assert watch.signer("I checked it; the body has `Codex session:` in it.", loaded) == roles.user
    assert watch.signer("Quoting `Claude session:` signs nothing.", loaded) == roles.user
    assert watch.signer("Status: done\nWaiting on: none\n\nClaude session: impl", loaded) == roles.executor
    assert watch.signer(executor("Status: done\nWaiting on: none\nKey numbers: 1\nNext: merge"), loaded) == roles.executor


RULING = CHINESE + """
[rule]
type_label = "类型"
types = ["可执行", "方案，等用户", "记录"]
notify = "#{ticket} 已答复，见票 {url}"
"""
REPLY = "总设计：结论\n类型：可执行\n\n正文 见 `pkg/work.py:9` holds `Ledger`\n"
URL = "https://github.com/o/r/issues/42#issuecomment-900"


def comment_pages(*bodies):
    return 0, json.dumps([[{"id": 100 + index, "body": body, "created_at": f"2026-10-28T0{index}:00:00Z",
                            "html_url": f"https://github.com/o/r/issues/42#issuecomment-{100 + index}"}
                           for index, body in enumerate(bodies)]])


@pytest.fixture
def ruling(tree, tmp_path, monkeypatch):
    """`ding rule` run offline in a Chinese-vocabulary repo whose gh and ding send are doubles."""
    (tmp_path / config.FILE).write_text(RULING, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    state = SimpleNamespace(calls=[], sends=[], sent_after=[], send_code=0, draft=tmp_path / "draft.md")
    state.draft.write_text(REPLY, encoding="utf-8")

    def run(responses, *options, text=None):
        if text is not None:
            state.draft.write_text(text, encoding="utf-8")
        monkeypatch.setattr(rule, "call", fake_call(list(responses), state.calls))
        return real_main(["rule", "42", str(state.draft), "--root", str(tree), "--offline", *options])

    real_main = ding.main

    def main(argv):
        if argv[0] != "send":
            return real_main(argv)
        state.sends.append(argv)
        state.sent_after.append(len(state.calls))
        print("started")
        return state.send_code

    monkeypatch.setattr(ding, "main", main)

    state.run = run
    return state


def test_rule_posts_and_prints_only_the_url(ruling, capsys):
    assert ruling.run([comment_pages("用户：请裁定", "核查：通过"), (0, URL + "\n")], "--reply-to", "101",
                      "--no-notify") == 0
    captured = capsys.readouterr()
    assert captured.out == URL + "\n"
    assert "latest comment" not in captured.err
    assert ruling.calls[0][:4] == ("gh", "api", "--paginate", "--slurp")
    assert ruling.calls[1] == ("gh", "issue", "comment", "42", "--repo", "o/r", "--body-file", str(ruling.draft))
    assert ruling.sends == []


DEFAULT_SEND = ["send", "#42", "--from", "总设计", "--message", f"#42 已答复，见票 {URL}\n总设计：结论"]


def test_an_actionable_ruling_tells_the_ticket_executor_after_posting(ruling, capsys):
    assert ruling.run([comment_pages("用户：请裁定"), (0, URL)]) == 0
    captured = capsys.readouterr()
    assert captured.out == URL + "\n" and "started" in captured.err
    assert ruling.sends == [DEFAULT_SEND] and ruling.sent_after == [2]
    assert ruling.calls[1][:3] == ("gh", "issue", "comment")


def test_no_notify_tells_nobody(ruling, capsys):
    assert ruling.run([comment_pages("用户：请裁定"), (0, URL)], "--no-notify") == 0
    assert capsys.readouterr().out == URL + "\n" and ruling.sends == []


def test_a_failed_default_notification_keeps_the_comment_and_names_no_notify(ruling, capsys):
    ruling.send_code = 1
    assert ruling.run([comment_pages("用户：请裁定"), (0, URL)]) == 1
    captured = capsys.readouterr()
    assert captured.out == URL + "\n" and ruling.sends == [DEFAULT_SEND]
    assert f"posted {URL}, but the notification to #42 failed" in captured.err
    assert "the comment stays" in captured.err and "--no-notify" in captured.err and "by hand" not in captured.err


@pytest.mark.parametrize("options", [[], ["--notify", "#42"]])
def test_a_ruling_queued_without_a_waiter_succeeds_and_says_not_to_resend(ruling, capsys, options):
    ruling.send_code = ding.NO_LISTENER_EXIT
    assert ruling.run([comment_pages("用户：请裁定"), (0, URL)], *options) == 0
    captured = capsys.readouterr()
    assert captured.out == URL + "\n" and ruling.sends == [DEFAULT_SEND]
    assert f"posted {URL}; queued in the inbox of #42" in captured.err and "Do not resend" in captured.err
    assert "failed" not in captured.err


def test_rule_without_reply_to_shows_the_latest_comment(ruling, capsys):
    assert ruling.run([comment_pages("用户：请裁定", "核查：通过\n第二行"), (0, URL)]) == 0
    captured = capsys.readouterr()
    assert captured.out == URL + "\n"
    assert "latest comment on #42: 2026-10-28T01:00:00Z '核查：通过'" in captured.err


@pytest.mark.parametrize("text, message", [
    ("核查：结论\n类型：可执行\n", "line 1 must start with '总设计：'"),
    ("总设计：结论\n", "line 2 must start with '类型：'"),
    ("总设计：结论\n正文\n类型：可执行\n", "line 2 must start with '类型：'"),
    ("总设计：结论\n类型：大概可以\n", "must be one of: 可执行, 方案，等用户, 记录"),
])
def test_rule_stops_when_the_first_two_lines_are_wrong(ruling, capsys, text, message):
    assert ruling.run([], text=text) == 1
    assert message in capsys.readouterr().err
    assert ruling.calls == [] and ruling.sends == []


def test_rule_accepts_each_type(ruling, capsys):
    for kind in ("方案，等用户", "记录"):
        assert ruling.run([comment_pages("用户：问"), (0, URL)], text=f"总设计：结论\n类型：{kind}\n") == 0
    assert ruling.sends == []


@pytest.mark.parametrize("setting, kind, sends", [
    ("notify_types = []", "可执行", 0),
    ('notify_types = ["记录"]', "记录", 1),
    ('notify_types = ["记录"]', "可执行", 0),
    ('notify_types = ["可执行", "方案，等用户"]', "方案，等用户", 1),
])
def test_notify_types_choose_which_rulings_tell_the_executor(ruling, tmp_path, capsys, setting, kind, sends):
    (tmp_path / config.FILE).write_text(RULING + setting + "\n", encoding="utf-8")
    assert ruling.run([comment_pages("用户：问"), (0, URL)], text=f"总设计：结论\n类型：{kind}\n") == 0
    assert len(ruling.sends) == sends and all(send[1] == "#42" for send in ruling.sends)


def test_rule_stops_on_a_wrong_reference_and_posts_nothing(ruling, capsys):
    assert ruling.run([], text="总设计：结论\n类型：可执行\n`pkg/work.py:6` holds `Ledger`\n") == 1
    captured = capsys.readouterr()
    assert "wrong: line 3 `pkg/work.py:6`" in captured.err and "Nothing posted" in captured.err
    assert captured.out == "" and ruling.calls == [] and ruling.sends == []


def test_rule_stops_when_a_comment_came_after_the_one_answered(ruling, capsys):
    pages = comment_pages("用户：请裁定", "用户：补充一点", "核查：新数字")
    link = "https://github.com/o/r/issues/42#issuecomment-100"
    assert ruling.run([pages], "--reply-to", link, "--notify", "#42") == 1
    captured = capsys.readouterr()
    assert captured.out == "" and len(ruling.calls) == 1 and ruling.sends == []
    assert "newer: https://github.com/o/r/issues/42#issuecomment-101 '用户：补充一点'" in captured.err
    assert "newer: https://github.com/o/r/issues/42#issuecomment-102 '核查：新数字'" in captured.err
    assert "--force" in captured.err


def test_rule_force_posts_despite_newer_comments(ruling, capsys):
    assert ruling.run([comment_pages("用户：请裁定", "用户：补充一点"), (0, URL)], "--reply-to", "100", "--force") == 0
    captured = capsys.readouterr()
    assert captured.out == URL + "\n" and "posting anyway" in captured.err


@pytest.mark.parametrize("reply_to, message", [
    ("999", "comment 999 is not among"),
    ("https://github.com/o/r/issues/43#issuecomment-100", "is not on o/r#42"),
    ("https://github.com/o/r/issues/42", "not an issue comment link"),
])
def test_rule_refuses_a_reply_target_that_is_not_on_the_ticket(ruling, capsys, reply_to, message):
    assert ruling.run([comment_pages("用户：请裁定")], "--reply-to", reply_to) == 1
    assert message in capsys.readouterr().err and len(ruling.calls) <= 1


def test_rule_reports_a_failed_notification_but_keeps_the_comment(ruling, capsys):
    ruling.send_code = 1
    assert ruling.run([comment_pages("用户：请裁定"), (0, URL)], "--reply-to", "100", "--notify", "#42") == 1
    captured = capsys.readouterr()
    assert captured.out == URL + "\n"
    assert "the comment stays" in captured.err and "failed" in captured.err
    assert ruling.sends == [["send", "#42", "--from", "总设计", "--message", f"#42 已答复，见票 {URL}\n总设计：结论"]]
    assert [call[:3] for call in ruling.calls] == [("gh", "api", "--paginate"), ("gh", "issue", "comment")]


def test_rule_notifies_a_codex_session_and_keeps_stdout_clean(ruling, capsys):
    assert ruling.run([comment_pages("用户：请裁定"), (0, URL)], "--notify", "00000000-0000-4000-8000-000000000001") == 0
    captured = capsys.readouterr()
    assert captured.out == URL + "\n" and "started" in captured.err
    assert [send[:2] for send in ruling.sends] == [["send", "00000000-0000-4000-8000-000000000001"]]


def test_rule_refuses_a_claude_session_before_posting(ruling, capsys):
    assert ruling.run([], "--notify", "uds:/tmp/cc-socks/1.sock") == 1
    assert "SendMessage address" in capsys.readouterr().err
    assert ruling.calls == [] and ruling.sends == []


def test_rule_reports_a_failed_post_and_a_non_url_answer(ruling, capsys):
    assert ruling.run([comment_pages("用户：问"), (1, "")]) == 1
    assert "comment failed: boom" in capsys.readouterr().err
    assert ruling.run([comment_pages("用户：问"), (0, "created\n")], "--notify", "#42") == 1
    assert "did not print a comment link" in capsys.readouterr().err and ruling.sends == []


BODY = "票面\n第二行\n"


def test_edit_body_writes_only_over_the_baseline_and_verifies(ruling, tmp_path, capsys):
    base = tmp_path / "base.md"
    base.write_text(BODY, encoding="utf-8")
    new = "新票面 `pkg/work.py:9` holds `Ledger`\n"
    responses = [(0, BODY.replace("\n", "\r\n") + "\n"), (0, "https://github.com/o/r/issues/42\n"), (0, new)]
    assert ruling.run(responses, "--edit-body", "--base", str(base), text=new) == 0
    assert capsys.readouterr().out == "https://github.com/o/r/issues/42\n"
    assert ruling.sends == []
    assert ruling.calls[0] == ("gh", "api", "repos/o/r/issues/42", "--jq", ".body")
    assert ruling.calls[1] == ("gh", "issue", "edit", "42", "--repo", "o/r", "--body-file", str(ruling.draft))


def test_edit_body_tells_only_an_explicit_notify(ruling, tmp_path, capsys):
    base = tmp_path / "base.md"
    base.write_text(BODY, encoding="utf-8")
    new = REPLY
    for options, sends in ((["--no-notify"], []), (["--notify", "#42"], ["#42"])):
        ruling.sends.clear()
        responses = [(0, BODY), (0, "https://github.com/o/r/issues/42\n"), (0, new)]
        assert ruling.run(responses, "--edit-body", "--base", str(base), *options, text=new) == 0
        assert [send[1] for send in ruling.sends] == sends
    ruling.sends.clear()
    responses = [(0, BODY), (0, "https://github.com/o/r/issues/42\n"), (0, new)]
    assert ruling.run(responses, "--edit-body", "--base", str(base), text=new) == 0
    assert ruling.sends == []


def test_edit_body_stops_when_the_body_changed(ruling, tmp_path, capsys):
    base = tmp_path / "base.md"
    base.write_text(BODY, encoding="utf-8")
    assert ruling.run([(0, "票面\n别人改了\n")], "--edit-body", "--base", str(base), text="新票面\n") == 1
    captured = capsys.readouterr()
    assert "+别人改了" in captured.err and "Nothing edited" in captured.err and len(ruling.calls) == 1


def test_edit_body_reports_a_body_that_reads_back_differently(ruling, tmp_path, capsys):
    base = tmp_path / "base.md"
    base.write_text(BODY, encoding="utf-8")
    responses = [(0, BODY), (0, "https://github.com/o/r/issues/42\n"), (0, "新票面 被改了\n")]
    assert ruling.run(responses, "--edit-body", "--base", str(base), text="新票面\n") == 1
    captured = capsys.readouterr()
    assert captured.out == "" and "read back differs" in captured.err


@pytest.mark.parametrize("options, error", [
    (["--edit-body"], "--edit-body and --base go together"),
    (["--base", "x"], "--edit-body and --base go together"),
    (["--edit-body", "--base", "x", "--reply-to", "1"], "belong to comments"),
    (["--force"], "--force goes with --reply-to"),
    (["--notify", "#42", "--no-notify"], "not allowed with argument --notify"),
])
def test_rule_option_combinations(capsys, options, error):
    with pytest.raises(SystemExit) as exc:
        ding.main(["rule", "42", "draft.md", *options])
    assert exc.value.code == 2 and error in capsys.readouterr().err


def test_check_refs_reports_each_draft_and_fails_when_any_is_wrong(tree, capsys):
    good, bad = tree / "good.md", tree / "bad.md"
    good.write_text("`pkg/work.py:9` holds `Ledger`\n")
    bad.write_text("`pkg/work.py:6` holds `Ledger`\n")
    assert ding.main(["check-refs", str(good), "--root", str(tree)]) == 0
    assert "draft" not in json.loads(capsys.readouterr().out)
    assert ding.main(["check-refs", str(good), str(bad), str(good), "--root", str(tree)]) == 1
    captured = capsys.readouterr()
    reports = [json.loads(line) for line in captured.out.splitlines()]
    assert [(r["draft"], r["findings"]) for r in reports] == [(str(good), 0), (str(bad), 1), (str(good), 0)]
    assert f"wrong: {bad}: line 1 `pkg/work.py:6`" in captured.err
    assert f"{good}: checked 1 references (1 file:line): 0 wrong" in captured.err


def test_check_refs_keeps_going_past_an_unreadable_draft(tree, capsys):
    good = tree / "good.md"
    good.write_text("`pkg/work.py:9` holds `Ledger`\n")
    assert ding.main(["check-refs", str(tree / "missing.md"), str(good), "--root", str(tree)]) == 2
    captured = capsys.readouterr()
    assert "missing.md" in captured.err and json.loads(captured.out)["draft"] == str(good)


def test_rule_notify_types_may_name_any_listed_type(tmp_path):
    loaded = settings(tmp_path, "[rule]\nnotify_types = ['record']\ntypes = ['actionable', 'record']")
    assert loaded.rule.default_notify_types == ("record",)


def test_rule_defaults_are_english(tmp_path):
    loaded = settings(tmp_path)
    assert loaded.rule.type_label == "Type" and "actionable" in loaded.rule.types
    assert loaded.rule.default_notify_types == ("actionable",)
    assert rule.format_problem("Designer: x\nType: record\n", loaded) is None


def test_launch_config_preserves_argv_and_defaults(tmp_path):
    assert settings(tmp_path).launch == config.Launch()
    loaded = settings(tmp_path, '[launch]\npreflight = ["python", "", "two words"]')
    assert loaded.launch.preflight == ("python", "", "two words")
    assert loaded.launch.preflight_timeout == 300
    assert loaded.launch.keep_days == 14
    assert settings(tmp_path, "[launch]\nkeep_days = 0").launch.keep_days == 0


@pytest.mark.parametrize("text", [None, CHINESE])
def test_default_designer_signature_is_shared_and_requires_separator(tmp_path, text):
    loaded = settings(tmp_path, text)
    roles = loaded.roles
    signature = roles.signature(roles.designer)
    assert loaded.designer_signatures == (signature,)
    assert rule.format_problem(f"{signature}decision\nType{roles.separator}record\n", loaded) is None
    assert watch.signer(f"## {signature}decision", loaded) == roles.designer
    for prefix in (roles.designer, roles.designer + " (other): "):
        assert rule.format_problem(f"{prefix}\nType{roles.separator}record\n", loaded) is not None
        assert watch.signer(prefix, loaded) == roles.user
    assert watch.signer(roles.verifier + " report", loaded) == roles.verifier
    assert watch.signer(roles.orchestrator + " update", loaded) == roles.orchestrator


@pytest.mark.parametrize("prefix", ["总设计：", "总设计（训练）："])
def test_rule_and_watch_share_configured_designer_signatures(tmp_path, prefix):
    loaded = settings(tmp_path, RULING + 'signatures = ["总设计：", "总设计（训练）："]\n')
    assert rule.format_problem(f"{prefix}结论\n类型：可执行\n", loaded) is None
    assert watch.signer(f"{prefix}结论", loaded) == loaded.roles.designer
    problem = rule.format_problem("其他设计：结论\n类型：可执行\n", loaded)
    assert "'总设计：'" in problem and "'总设计（训练）：'" in problem
    assert watch.signer("其他设计：结论", loaded) == loaded.roles.user


def test_explicit_signatures_replace_default_and_preserve_spaces(tmp_path):
    loaded = settings(tmp_path, '[rule]\nsignatures = ["Training designer: "]')
    assert loaded.rule.signatures == ("Training designer: ",)
    assert rule.format_problem("Training designer: decision\nType: record", loaded) is None
    assert watch.signer("Training designer: decision", loaded) == loaded.roles.designer
    for prefix in ("Training designer:", "Designer: decision"):
        assert rule.format_problem(f"{prefix}\nType: record", loaded) is not None
        assert watch.signer(prefix, loaded) == loaded.roles.user


@pytest.mark.parametrize("prefix", ["总设计：", "总设计（训练）："])
def test_rule_command_accepts_each_configured_signature(ruling, tmp_path, prefix):
    (tmp_path / config.FILE).write_text(RULING + 'signatures = ["总设计：", "总设计（训练）："]\n')
    assert ruling.run([comment_pages("用户：问"), (0, URL)], text=f"{prefix}结论\n类型：可执行\n") == 0
    assert len(ruling.calls) == 2


def test_rule_command_refuses_unlisted_signature_before_posting(ruling, tmp_path, capsys):
    (tmp_path / config.FILE).write_text(RULING + 'signatures = ["总设计：", "总设计（训练）："]\n')
    assert ruling.run([], text="总设计（其他）：结论\n类型：可执行\n") == 1
    error = capsys.readouterr().err
    assert "'总设计：'" in error and "'总设计（训练）：'" in error
    assert ruling.calls == [] and ruling.sends == []


@pytest.mark.parametrize("signature", ["  Design: ", "# Design: "])
def test_configured_signature_is_matched_before_watch_markdown_normalization(tmp_path, signature):
    loaded = settings(tmp_path, f"[rule]\nsignatures = {json.dumps([signature])}")
    body = f"{signature}decision\nType: record"
    assert rule.format_problem(body, loaded) is None
    assert watch.signer(body, loaded) == loaded.roles.designer


def test_watch_does_not_report_a_configured_designer_as_user(tmp_path, monkeypatch):
    loaded = settings(tmp_path, RULING + 'signatures = ["总设计：", "总设计（训练）："]\n')
    comments = [comment(24, "总设计（训练）：结论"), comment(25, "总设计（其他）：提问")]
    monkeypatch.setattr(watch, "gh", lambda path: comments if "/issues/comments" in path and "page=1" in path else [])
    found = watch.collect(loaded, "o/r", "2026-10-14T08:00:00Z", "2026-10-14T08:00:00Z", set(), set())
    assert len(found) == 1
    assert "#25 用户 comment" in found[0][1] and found[0][2] is True


def test_watch_reports_future_stamped_items_once_across_batches(tmp_path, monkeypatch, capsys):
    loaded = config.Config(root=tmp_path, repo="o/r")
    monkeypatch.setattr(config, "load", lambda: loaded)
    monkeypatch.setattr(watch, "stale", lambda *args: [])
    monkeypatch.setattr(watch.time, "sleep", lambda seconds: None)
    state = tmp_path / "watch.json"
    state.write_text(json.dumps({"since": "2026-10-14T08:00:00Z", "seen": [], "stale": []}))
    comments = []
    monkeypatch.setattr(watch, "gh", lambda path: comments if "/issues/comments?" in path else [])

    def batch(number):
        comments.append({**comment(number, f"User question {number}"), "created_at": "2999-01-01T00:00:00Z",
                         "updated_at": "2999-01-01T00:00:00Z"})
        assert ding.main(["watch", "--state", str(state), "--interval", "0", "--settle", "0"]) == 0
        return capsys.readouterr().out

    assert "#26 User comment" in batch(26)
    assert "#26 User comment" not in batch(27)
    third = batch(28)
    assert "#28 User comment" in third and "#26 User comment" not in third and "#27 User comment" not in third


def test_watch_reads_seen_list_from_older_state(tmp_path, monkeypatch, capsys):
    loaded = config.Config(root=tmp_path, repo="o/r")
    monkeypatch.setattr(config, "load", lambda: loaded)
    monkeypatch.setattr(watch, "stale", lambda *args: [])
    monkeypatch.setattr(watch.time, "sleep", lambda seconds: None)
    old, new = comment(26, "User question"), comment(27, "User question")
    monkeypatch.setattr(watch, "gh", lambda path: [old, new] if "/issues/comments?" in path else [])
    line = watch.collect(loaded, "o/r", "2026-10-14T08:00:00Z", "2026-10-14T08:00:00Z", set(), set())[0][1]
    state = tmp_path / "watch.json"
    state.write_text(json.dumps({"since": "2026-10-14T08:00:00Z", "seen": [line], "stale": []}))
    assert ding.main(["watch", "--state", str(state), "--interval", "0", "--settle", "0"]) == 0
    out = capsys.readouterr().out
    assert "#27 User comment" in out and "#26 User comment" not in out


@pytest.mark.parametrize("recover", [True, False])
def test_watch_post_settle_timeout_is_retried_without_losing_batch(tmp_path, monkeypatch, capsys, recover):
    import subprocess
    loaded = config.Config(root=tmp_path, repo="o/r")
    monkeypatch.setattr(config, "load", lambda: loaded)
    monkeypatch.setattr(watch, "stale", lambda *args: [])
    monkeypatch.setattr(watch.time, "sleep", lambda seconds: None)
    pulls = []
    original_since = "2026-10-14T08:00:00Z"
    state = tmp_path / "watch.json"
    state.write_text(json.dumps({"since": original_since, "seen": [], "stale": []}))
    original = state.read_bytes()

    def gh(path):
        assert state.read_bytes() == original
        if "/issues/comments?" in path:
            return [comment(26, "User question")]
        if "/pulls?state=all" in path:  # the new-PR listing; the stalled scan lists open PRs
            pulls.append(path)
            if len(pulls) % 2 == 0 and (not recover or len(pulls) == 2):
                raise subprocess.TimeoutExpired(["gh", "api", path], 60)
        return []

    monkeypatch.setattr(watch, "gh", gh)
    result = ding.main(["watch", "--state", str(state), "--interval", "0", "--settle", "0", "--max-errors", "2"])
    assert result == (0 if recover else 2)
    captured = capsys.readouterr()
    assert "poll failed 1/2" in captured.err
    assert len(pulls) == 4
    if recover:
        assert captured.out.count("#26 User comment") == 1
        assert json.loads(state.read_text())["since"] != original_since
    else:
        assert state.read_bytes() == original
        assert "#26 User comment" not in captured.out


@pytest.fixture
def idle_ticket(tmp_path, monkeypatch):
    class Clock(datetime):
        moment = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)

        @classmethod
        def now(cls, tz=None):
            return cls.moment

    monkeypatch.setattr(watch, "datetime", Clock)
    loaded = config.Config(root=tmp_path, repo="o/r")
    last = {"id": 2601, "body": executor("Status: in progress\nWaiting on: none\nKey numbers: 1\nNext: check"),
            "created_at": "2026-10-28T10:00:00Z", "updated_at": "2026-10-28T10:00:00Z",
            "html_url": "https://github.com/o/r/issues/26#issuecomment-2601"}
    issue = {"number": 26, "comments": 1, "labels": [], "updated_at": last["updated_at"]}
    state = SimpleNamespace(config=loaded, clock=Clock, last=last, issues=[issue], comments=[last],
                            board="NAME\tCWD\tSTATUS\tISSUE\tHEAD\tRUN\n【#26】worker\t/r\tidle\t#26\thead\t\n", panes="", pulls=[])
    calls = []

    def gh(path):
        calls.append(path)
        if "/issues/26/comments?" in path:
            return state.comments
        if "/issues?state=open&per_page=100" in path:
            return state.issues
        if "/pulls?state=open&sort=updated" in path:
            return state.pulls
        raise AssertionError(path)

    monkeypatch.setattr(watch, "gh", gh)
    monkeypatch.setattr(watch, "finished_waits", lambda *args: [])
    state.board_reader = watch.board_output
    monkeypatch.setattr(watch, "board_output", lambda checkout: state.board)
    monkeypatch.setattr(watch, "tmux_panes", lambda: state.panes)
    state.calls = calls
    return state


def check_idle(ticket, observed=None, reported=None, skip=None):
    return watch.idle(ticket.config, "o/r", ticket.config.root,
                      observed or {}, reported or set(), skip or set())


def test_idle_executor_wakes_after_threshold_and_reports_comment_summary(idle_ticket):
    ticket = idle_ticket
    found, observed = check_idle(ticket)
    assert found == []
    assert observed == {"26": {"comment_id": 2601, "since": "2026-10-28T12:00:00Z"}}
    ticket.clock.moment += timedelta(minutes=46)
    found, observed = check_idle(ticket, observed)
    assert len(found) == 1 and found[0][2] == 2601
    assert "#26 executor idle for 46 minutes while still in progress" in found[0][1]
    assert "no running ding run or tmux job" in found[0][1]
    assert "Status: in progress; Waiting on: none" in found[0][1]
    assert ticket.last["html_url"] in found[0][1]


@pytest.mark.parametrize("condition", ["active", "unknown", "run", "tmux", "no_session", "done", "label", "skip"])
def test_idle_wake_requires_every_condition_and_resets_observation(idle_ticket, condition):
    ticket = idle_ticket
    _, observed = check_idle(ticket)
    ticket.clock.moment += timedelta(hours=1)
    skip = set()
    if condition in {"active", "unknown"}:
        ticket.board += f"【#26】other\t/r\t{condition}\t#26\thead\t\n"
    elif condition == "run":
        ticket.board = ticket.board.replace("head\t\n", "head\trunning\n")
    elif condition == "tmux":
        ticket.panes = "ding-issue26-job|0|python\n"
    elif condition == "no_session":
        ticket.board = ticket.board.replace("#26", "#27")
    elif condition == "done":
        ticket.last["body"] = ticket.last["body"].replace("in progress", "done")
    elif condition == "label":
        ticket.issues[0]["labels"] = [{"name": "status:awaiting-user"}]
    elif condition == "skip":
        skip = {26}
    found, pending = check_idle(ticket, observed, skip=skip)
    assert found == [] and pending == {}


@pytest.mark.parametrize("minutes", [44, 45])
def test_idle_threshold_must_be_exceeded(idle_ticket, minutes):
    _, observed = check_idle(idle_ticket)
    idle_ticket.clock.moment += timedelta(minutes=minutes)
    assert check_idle(idle_ticket, observed)[0] == []


def test_idle_accepts_not_loaded_sessions_and_ignores_shell_or_dead_tmux(idle_ticket):
    ticket = idle_ticket
    ticket.board += "【#26】other\t/r\tnotLoaded\t#26\thead\t\n"
    ticket.panes = "ding-issue26-shell|0|bash\nding-issue26-done|1|python\n"
    _, observed = check_idle(ticket)
    ticket.clock.moment += timedelta(hours=1)
    assert len(check_idle(ticket, observed)[0]) == 1


def test_idle_reports_once_per_comment_and_new_comment_starts_a_new_period(idle_ticket):
    ticket = idle_ticket
    _, observed = check_idle(ticket)
    ticket.clock.moment += timedelta(hours=1)
    found, observed = check_idle(ticket, observed)
    assert len(found) == 1
    reported = {found[0][2]}
    assert check_idle(ticket, observed, reported)[0] == []
    ticket.last.update(id=2602, created_at="2026-10-28T13:00:00Z", updated_at="2026-10-28T13:00:00Z")
    found, observed = check_idle(ticket, observed, reported)
    assert found == [] and observed["26"]["comment_id"] == 2602
    ticket.clock.moment += timedelta(minutes=46)
    assert check_idle(ticket, observed, reported)[0][0][2] == 2602


def test_idle_uses_latest_executor_comment_even_after_a_user_reply(idle_ticket):
    ticket = idle_ticket
    ticket.comments.append({"id": 2602, "body": "User followup"})
    ticket.issues[0]["comments"] = 2
    _, observed = check_idle(ticket)
    ticket.clock.moment += timedelta(hours=1)
    assert check_idle(ticket, observed)[0][0][2] == 2601


def test_idle_never_ages_before_the_latest_executor_comment_update(idle_ticket):
    ticket = idle_ticket
    _, observed = check_idle(ticket)
    ticket.clock.moment += timedelta(hours=1)
    ticket.last["updated_at"] = "2026-10-28T12:50:00Z"
    assert check_idle(ticket, observed)[0] == []


def test_idle_disabled_does_not_query_github_board_or_tmux(tmp_path, monkeypatch):
    loaded = settings(tmp_path, '[watch]\nidle_minutes = 0')
    def unexpected(*args):
        pytest.fail("disabled idle check must not query")
    for name in ("gh", "board_output", "tmux_panes"):
        monkeypatch.setattr(watch, name, unexpected)
    assert watch.idle(loaded, "o/r", tmp_path, {}, set(), set()) == ([], {})


def test_watch_config_defaults_and_unknown_keys(tmp_path):
    assert settings(tmp_path).watch.idle_minutes == 45
    assert settings(tmp_path, '[watch]\nidle_minutes = 0.5').watch.idle_minutes == 0.5
    with pytest.raises(ValueError, match=r"unknown keys in \[watch\]: idle_minute"):
        settings(tmp_path, '[watch]\nidle_minute = 1')


def test_idle_observation_survives_restart_without_advancing_since(idle_ticket, monkeypatch, capsys):
    ticket = idle_ticket
    monkeypatch.setattr(config, "load", lambda: ticket.config)
    monkeypatch.setattr(watch, "stale", lambda *args: [])
    monkeypatch.setattr(watch.time, "sleep", lambda seconds: None)
    calls = []

    def collect(*args):
        calls.append(None)
        if len(calls) > 1:
            raise RuntimeError("offline")
        return []

    monkeypatch.setattr(watch, "collect", collect)
    path = ticket.config.root / "watch.json"
    arguments = ["watch", "--state", str(path), "--since", "2026-10-28T10:00:00Z",
                 "--interval", "0", "--settle", "0", "--stale-every", "0", "--max-errors", "1"]
    assert ding.main(arguments) == 2
    state = json.loads(path.read_text())
    assert state["since"] == "2026-10-28T10:00:00Z"
    assert state["idle_observed"]["26"]["since"] == "2026-10-28T12:00:00Z"
    assert state["labels_since"] == "2026-10-28T10:00:00Z"
    def resumed_collect(config, repo, since, labels_since, seen, skip):
        assert since == labels_since == "2026-10-28T10:00:00Z"
        return []
    monkeypatch.setattr(watch, "collect", resumed_collect)
    ticket.clock.moment += timedelta(hours=1)
    assert ding.main(arguments) == 0
    state = json.loads(path.read_text())
    assert state["idle_reported"] == [2601]
    assert "labels_since" not in state
    assert state["stale"] == []
    assert capsys.readouterr().out.count("#26 executor idle") == 1
    assert check_idle(ticket, state["idle_observed"], set(state["idle_reported"]))[0] == []


@pytest.mark.parametrize("stage", ["collect", "stale", "idle"])
@pytest.mark.parametrize("recover", [True, False])
def test_watch_bounds_errors_in_every_poll_phase(tmp_path, monkeypatch, capsys, stage, recover):
    import subprocess
    loaded = config.Config(root=tmp_path, repo="o/r")
    monkeypatch.setattr(config, "load", lambda: loaded)
    monkeypatch.setattr(watch.time, "sleep", lambda seconds: None)
    item = ("2026-10-28T12:00:00Z", "#26 recovered", True)
    monkeypatch.setattr(watch, "collect", lambda *args: [item] if stage == "collect" else [])
    monkeypatch.setattr(watch, "stale", lambda *args: [])
    monkeypatch.setattr(watch, "idle", lambda *args: ([], {}))
    monkeypatch.setattr(watch, "unanswered_design", lambda *args: [])
    monkeypatch.setattr(watch, "finished_waits", lambda *args: [])
    monkeypatch.setattr(watch, "unrouted_waits", lambda *args: [])
    monkeypatch.setattr(watch, "stalled", lambda *args: [])
    attempts = []

    def fail_then_recover(*args):
        attempts.append(None)
        if len(attempts) == 1 or not recover:
            if stage == "stale":
                raise RuntimeError("gh api failed")
            raise subprocess.TimeoutExpired(["gh", "api"], 60)
        if stage == "collect":
            return [item]
        return [(item[0], item[1], 2601)] if stage == "stale" else ([(item[0], item[1], 2601)], {})

    monkeypatch.setattr(watch, stage, fail_then_recover)
    path = tmp_path / "watch.json"
    result = ding.main(["watch", "--state", str(path), "--interval", "0", "--settle", "0", "--max-errors", "2"])
    assert result == (0 if recover else 2)
    captured = capsys.readouterr()
    assert "poll failed 1/2" in captured.err
    if recover:
        assert captured.out.count("#26 recovered") == 1
        assert path.exists()
    else:
        assert len(attempts) == 2
        assert "poll failed 2/2" in captured.err
        assert not path.exists()


def test_idle_paginates_back_to_the_latest_executor_comment(idle_ticket, monkeypatch):
    ticket = idle_ticket
    ticket.issues[0]["comments"] = 101
    gh = watch.gh
    pages = []
    def comments(path):
        if "/issues/26/comments?" in path:
            pages.append(path)
            return [{"body": "User followup"}] if path.endswith("page=2") else [ticket.last]
        return gh(path)
    monkeypatch.setattr(watch, "gh", comments)
    _, observed = check_idle(ticket)
    ticket.clock.moment += timedelta(hours=1)
    assert check_idle(ticket, observed)[0][0][2] == 2601
    assert len(pages) == 4


def test_idle_wake_skips_log_issue(idle_ticket, monkeypatch, capsys):
    from dataclasses import replace
    ticket = idle_ticket
    ticket.config = replace(ticket.config, log=config.Log(issue=26))
    monkeypatch.setattr(config, "load", lambda: ticket.config)
    monkeypatch.setattr(watch.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(watch, "stale", lambda *args: [])
    calls = []
    def collect(*args):
        calls.append(None)
        if len(calls) > 1:
            return [("2026-10-28T12:00:00Z", "other event", True)]
        return []
    monkeypatch.setattr(watch, "collect", collect)
    path = ticket.config.root / "watch.json"
    assert ding.main(["watch", "--state", str(path), "--interval", "0", "--settle", "0"]) == 0
    assert json.loads(path.read_text())["idle_observed"] == {}
    assert "#26 executor idle" not in capsys.readouterr().out


def test_stale_keeps_its_existing_silence_rule_and_comment_deduplication(idle_ticket):
    ticket = idle_ticket
    ticket.clock.moment += timedelta(hours=6)
    found = watch.stale(ticket.config, "o/r", ticket.config.root, 6, set(), set())
    assert len(found) == 1 and found[0][2] == 2601
    assert "executor silent for over 6 hours" in found[0][1]
    assert watch.stale(ticket.config, "o/r", ticket.config.root, 6, {2601}, set()) == []
    ticket.panes = "ding-issue26-job|0|python\n"
    assert watch.stale(ticket.config, "o/r", ticket.config.root, 6, set(), set()) == []


def test_idle_and_stale_use_template_names_with_an_empty_issue_column(idle_ticket):
    ticket = idle_ticket
    ticket.board = "NAME\tCWD\tSTATUS\tISSUE\tHEAD\tRUN\n【#26】worker\t/r\tidle\t\thead\t\n"
    _, observed = check_idle(ticket)
    ticket.clock.moment += timedelta(hours=1)
    assert check_idle(ticket, observed)[0][0][2] == 2601
    ticket.clock.moment += timedelta(hours=5)
    ticket.board = ticket.board.replace("head\t\n", "head\trunning\n")
    assert watch.stale(ticket.config, "o/r", ticket.config.root, 6, set(), set()) == []


@pytest.mark.parametrize("code", [0, 1])
def test_watch_board_skips_lookup_and_checks_exit_code(tmp_path, monkeypatch, code):
    output = "NAME\tCWD\tSTATUS\tISSUE\tHEAD\tRUN\nworker\t/r\tidle\t\thead\t\n"
    def board(argv, **kwargs):
        assert argv[-2:] == ["board", "--no-issue-lookup"]
        return SimpleNamespace(returncode=code, stdout=output, stderr="board failed" if code else "")
    monkeypatch.setattr(watch.subprocess, "run", board)
    if code:
        with pytest.raises(RuntimeError, match="board failed"):
            watch.board_output(tmp_path)
    else:
        assert watch.board_output(tmp_path) == output


def test_idle_schedule_is_independent_of_hourly_stale_check(idle_ticket, monkeypatch, capsys):
    from dataclasses import replace
    ticket = idle_ticket
    ticket.config = replace(ticket.config, watch=config.Watch(idle_minutes=15))
    monkeypatch.setattr(config, "load", lambda: ticket.config)
    monkeypatch.setattr(watch, "collect", lambda *args: [])
    start = ticket.clock.moment
    monkeypatch.setattr(watch.time, "monotonic", lambda: (ticket.clock.moment - start).total_seconds())
    monkeypatch.setattr(watch.time, "sleep", lambda seconds: setattr(
        ticket.clock, "moment", ticket.clock.moment + timedelta(seconds=seconds)))
    stale_checks = []
    monkeypatch.setattr(watch, "stale", lambda *args: stale_checks.append(ticket.clock.moment) or [])
    result = ding.main(["watch", "--state", str(ticket.config.root / "watch.json"),
                        "--interval", "7200", "--stale-every", "3600", "--settle", "0"])
    assert result == 0
    assert ticket.clock.moment - start == timedelta(minutes=20)
    assert stale_checks == [start]
    assert "#26 executor idle" in capsys.readouterr().out


@pytest.mark.parametrize("template, name, repo, expected", [
    ("【#{issue}】{name}", "【#868】worker", "", 868),
    ("【#{issue}】{name}", "【#868】two\nlines", "", 868),
    ("【#{issue}】{name}", "【#0】worker", "", None),
    ("【#{issue}】{name}", "【# 】worker", "", None),
    ("【#{issue}】{name}", "Legacy worker", "", None),
    ("{repo}#{issue:04d} {name}", "o/r#0868 Plot", "o/r", 868),
    ("{repo}#{issue:04d} {name}", "other/repo#0868 Plot", "o/r", None),
    ("{{x}} {issue:^6d} :: {name}", "{x}   26   :: Plot", "", 26),
    ("{name} #{issue}", "Worker #868", "", 868),
    ("#{issue} {name} #{issue}", "#26 Worker #26", "", 26),
    ("#{issue}", "#26", "", 26),
    ("{name}", "Worker #868", "", None),
    ("{issue}{name}", "868worker", "", None),
])
def test_session_template_ticket_parsing(template, name, repo, expected):
    assert config.Sessions(name=template).issue_number(name, repo) == expected


@pytest.mark.parametrize("phase", ["stale", "idle"])
def test_board_error_is_a_failed_poll_in_both_checks(idle_ticket, monkeypatch, capsys, phase):
    ticket = idle_ticket
    ticket.clock.moment += timedelta(hours=6)
    monkeypatch.setattr(config, "load", lambda: ticket.config)
    monkeypatch.setattr(watch, "collect", lambda *args: [])
    if phase == "idle":
        monkeypatch.setattr(watch, "stale", lambda *args: [])
    monkeypatch.setattr(watch.time, "sleep", lambda seconds: None)
    def board_failure(*args):
        raise RuntimeError("ding board failed: App Server unavailable")
    monkeypatch.setattr(watch, "board_output", board_failure)
    path = ticket.config.root / "watch.json"
    assert ding.main(["watch", "--state", str(path), "--interval", "0", "--max-errors", "2"]) == 2
    assert not path.exists()
    output = capsys.readouterr()
    assert "poll failed 1/2" in output.err and "poll failed 2/2" in output.err
    assert "#26 executor" not in output.out


@pytest.mark.parametrize("minutes, every", [(3, 60), (45, 900), (120, 900)])
def test_idle_cadence_is_capped_independently_of_poll_interval(idle_ticket, monkeypatch, minutes, every):
    from dataclasses import replace
    ticket = idle_ticket
    ticket.config = replace(ticket.config, watch=config.Watch(idle_minutes=minutes))
    monkeypatch.setattr(config, "load", lambda: ticket.config)
    monkeypatch.setattr(watch, "collect", lambda *args: [])
    monkeypatch.setattr(watch, "stale", lambda *args: [])
    start = ticket.clock.moment
    monkeypatch.setattr(watch.time, "monotonic", lambda: (ticket.clock.moment - start).total_seconds())
    monkeypatch.setattr(watch.time, "sleep", lambda seconds: setattr(
        ticket.clock, "moment", ticket.clock.moment + timedelta(seconds=seconds)))
    checks = []
    def idle(*args):
        checks.append((ticket.clock.moment - start).total_seconds())
        found = [(watch.now(), "idle wake", 2601)] if len(checks) == 3 else []
        return found, {}
    monkeypatch.setattr(watch, "idle", idle)
    assert ding.main(["watch", "--state", str(ticket.config.root / "watch.json"),
                      "--interval", "7200", "--stale-every", "3600"]) == 0
    assert checks == [0, every, 2 * every]


@pytest.mark.parametrize("unmatched_status", ["idle", "active"])
def test_watch_mixed_session_names_skip_failing_repository_scan(idle_ticket, monkeypatch, capsys, unmatched_status):
    import contextlib
    import io
    import subprocess
    ticket = idle_ticket
    root = ticket.config.root
    monkeypatch.setattr(config, "load", lambda: ticket.config)
    monkeypatch.setattr(watch, "collect", lambda *args: [])
    monkeypatch.setattr(watch, "stale", lambda *args: [])
    monkeypatch.setattr(watch, "board_output", ticket.board_reader)
    monkeypatch.setattr(ding, "repository_roots", lambda: [root])
    monkeypatch.setattr(ding, "latest_runs", lambda: {})
    monkeypatch.setattr(ding, "unwrapped_tasks", lambda **kwargs: [])
    threads = [{"id": str(index), "name": name, "cwd": str(root), "status": {"type": "idle"}}
               for index, name in enumerate(["【#26】worker", "检查 gml_10 系统盘"])]
    threads[1]["status"]["type"] = unmatched_status
    @contextlib.contextmanager
    def server(path):
        yield lambda *args: {}
    monkeypatch.setattr(ding, "app_server", server)
    monkeypatch.setattr(ding, "socket_path", lambda path: "/mock.sock")
    monkeypatch.setattr(ding, "board_threads", lambda *args: threads)
    monkeypatch.setattr(ding, "read_reply", lambda *args: "")
    lookups = []
    def failing_scan():
        lookups.append(None)
        raise subprocess.TimeoutExpired(["gh", "api", "repository-wide scan"], 60)
    monkeypatch.setattr(ding, "issue_map", failing_scan)
    def board(argv, **kwargs):
        assert argv[:4] == [watch.sys.executable, "-m", "dkitchen.ding", "board"]
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = ding.main(argv[3:])
        if code == 0:
            rows = [line.split("\t") for line in stdout.getvalue().splitlines()[1:]]
            assert [row[3] for row in rows] == ["#26", ""]
        return SimpleNamespace(returncode=code, stdout=stdout.getvalue(), stderr=stderr.getvalue())
    monkeypatch.setattr(watch.subprocess, "run", board)
    path = root / "watch.json"
    path.write_text(json.dumps({"since": "2026-10-28T10:00:00Z", "seen": [], "stale": [],
                               "idle_observed": {"26": {"comment_id": 2601, "since": "2026-10-28T11:00:00Z"}}}))
    assert ding.main(["watch", "--state", str(path), "--max-errors", "1"]) == 0
    assert lookups == []
    output = capsys.readouterr()
    assert "#26 executor idle" in output.out
    assert "poll failed" not in output.err
    assert json.loads(path.read_text())["idle_reported"] == [2601]


@pytest.mark.parametrize("template", ["#{ticket} 已答复，见票 {url}", "#{ticket} {first_line} {url}"])
def test_rule_notify_preserves_the_complete_178_character_first_line(ruling, tmp_path, template):
    first = "总设计：" + "结" * 174
    assert len(first) == 178
    configured = RULING.replace('notify = "#{ticket} 已答复，见票 {url}"', f"notify = {json.dumps(template)}")
    (tmp_path / config.FILE).write_text(configured)
    assert ruling.run([comment_pages("用户：问"), (0, URL)], "--notify", "#42",
                      text=first + "  \n类型：可执行\n正文\n") == 0
    expected = template.format(ticket=42, first_line=first, url=URL)
    if "{first_line}" not in template:
        expected += "\n" + first
    assert ruling.sends == [["send", "#42", "--from", "总设计", "--message", expected]]


def test_rule_first_line_is_complete_stripped_and_skips_empty_lines():
    first = "结" * 178
    assert rule.first_line("\n  \n " + first + "  \nnext") == first
    assert rule.first_line("\n \n") == ""


@pytest.mark.parametrize("mode", ["latest", "newer"])
def test_rule_long_comment_hints_add_ellipsis(ruling, capsys, mode):
    first = "结" * 178
    if mode == "latest":
        assert ruling.run([comment_pages(first + "\nnext"), (0, URL)]) == 0
    else:
        assert ruling.run([comment_pages("问", first + "\nnext")], "--reply-to", "100") == 1
    error = capsys.readouterr().err
    assert repr(first[:100] + "…") in error
    assert first not in error


@pytest.mark.parametrize("length", [0, 39, 40, 80, 100, 101, 160, 178])
def test_display_truncation_only_marks_shortened_text(length):
    from dkitchen import truncate
    text = "结" * length
    assert truncate(text, 100) == (text if length <= 100 else text[:100] + "…")


@pytest.mark.parametrize("body", ["short", "结" * 160, "结" * 178,
                                   "Status: " + "x" * 100 + "\nWaiting on: " + "y" * 100])
def test_watch_summary_marks_truncation_only_when_needed(tmp_path, body):
    full = body.replace("\n", "; ")
    expected = full[:160] + "…" if len(full) > 160 else full
    assert watch.summary(body, settings(tmp_path)) == expected


@pytest.mark.parametrize("length", [79, 80, 81])
def test_watch_pr_title_marks_truncation(tmp_path, monkeypatch, length):
    title = "题" * length
    pull = {"number": 29, "title": title, "created_at": "2026-10-29T00:00:00Z", "html_url": "https://github.com/o/r/pull/29"}
    monkeypatch.setattr(watch, "gh", lambda path: [pull] if "/pulls?" in path else [])
    result = watch.collect(settings(tmp_path), "o/r", "2026-10-28T00:00:00Z", "2026-10-28T00:00:00Z", set(), set())
    shown = title[:80] + "…" if length > 80 else title
    assert result == [(pull["created_at"], f"PR #29 opened: {shown} {pull['html_url']}", True)]


def test_diagnostic_excerpt_truncations_are_marked(tmp_path, monkeypatch):
    loaded = settings(tmp_path)
    assert repr("x" * 40 + "…") in rule.format_problem("x" * 41, loaded)
    assert repr("x" * 40 + "…") in rule.format_problem("Designer: decision\n" + "x" * 41, loaded)
    monkeypatch.setattr(watch.subprocess, "run", lambda *args, **kwargs:
                        SimpleNamespace(returncode=1, stderr="x" * 201))
    with pytest.raises(RuntimeError, match="x{200}…$"):
        watch.board_output(tmp_path)


def test_reference_display_excerpts_are_marked(tree):
    (tree / "pkg/long.py").write_text("x" * 81 + "\n")
    findings, _, _ = refs.check("`pkg/long.py:1` holds `Ledger`", refs.Source("HEAD", tree), 0)
    assert findings[0].endswith(repr("x" * 80 + "…"))
    def offline(*args):
        raise RuntimeError("x" * 121)
    github = SimpleNamespace(repo="o/r", problem=offline)
    _, notes, _ = refs.check("see #42", refs.Source("HEAD", tree), 0, github)
    assert notes == [f"line 1 ticket #42: not checked ({'x' * 120}…)"]


def test_rule_baseline_diff_marks_omitted_lines(ruling, tmp_path, capsys):
    base = tmp_path / "base.md"
    base.write_text("\n".join(f"old {index}" for index in range(10)))
    current = "\n".join(f"new {index}" for index in range(10))
    assert ruling.run([(0, current)], "--edit-body", "--base", str(base), text="new body\n") == 1
    error = capsys.readouterr().err
    assert "-old 5\n…\n" in error
    assert "-old 6" not in error


@pytest.fixture
def role_settings(tmp_path):
    return settings(tmp_path, RULING + 'signatures = ["总设计：", "总设计（训练）："]\n')


@pytest.mark.parametrize("role, waiting, signed, expected", [
    ("总设计", "总设计", True, True),
    ("总设计", "总设计（训练）", True, False),
    ("总设计（训练）", "总设计（训练）", True, True),
    ("总设计", "核查", True, False),
    ("总设计", "无", True, False),
    ("总设计", "总设计", False, False),
    ("总设计", "总设计（训练）和总设计", True, True),
    ("总设计", "总设计和总设计（训练）", True, True),
])
def test_role_collect_wakes_only_matching_executor_comments(role_settings, monkeypatch,
                                                           role, waiting, signed, expected):
    body = f"状态：进行中\n在等：{waiting}\n关键数字：1\n下一步：等"
    if signed:
        body = executor(body)
    calls = []
    def gh(path):
        calls.append(path)
        assert "/issues/comments?" in path, "role watches must not query labels, PRs or ticket lists"
        return [comment(30, body)]
    monkeypatch.setattr(watch, "gh", gh)
    result = watch.collect(role_settings, "o/r", "2026-10-14T08:00:00Z", "2026-10-14T08:00:00Z",
                           set(), set(), role=role)
    assert bool(result) is expected
    assert len(calls) == 1
    if expected:
        assert result[0][2] is True and "#30 执行者 comment" in result[0][1]


def test_role_match_uses_all_role_names_and_strips_signature_separators(role_settings):
    from dataclasses import replace
    loaded = replace(role_settings, roles=replace(role_settings.roles, verifier="总设计（审稿）"))
    for longer in ("总设计（训练）", "总设计（审稿）"):
        body = executor(f"状态：进行中\n在等：{longer}\n关键数字：1\n下一步：等")
        assert not watch.waiting_for(body, "总设计", loaded)
        assert watch.waiting_for(body, longer, loaded)
    english = config.Config(root=loaded.root, rule=config.Rule(signatures=("Design+Ops: ", "Design+Ops (training): ")))
    body = executor("Status: in progress\nWaiting on: Design+Ops (training)\nKey numbers: 1\nNext: wait")
    assert not watch.waiting_for(body, "Design+Ops", english)
    assert watch.waiting_for(body, "Design+Ops (training)", english)


@pytest.mark.parametrize("state", ["进行中", "等用户", "完成"])
def test_role_watch_matching_comment_wakes_even_on_awaiting_user_ticket(role_settings, monkeypatch, state):
    item = comment(30, executor(f"状态：{state}\n在等：总设计\n关键数字：1\n下一步：等"))
    item["issue"] = {"labels": [{"name": role_settings.labels.awaiting_user}]}
    def gh(path):
        assert "/issues/comments?" in path
        return [item]
    monkeypatch.setattr(watch, "gh", gh)
    assert watch.collect(role_settings, "o/r", "2026-10-14T08:00:00Z", "2026-10-14T08:00:00Z",
                         set(), set(), role="总设计")[0][2] is True


def test_role_watch_skips_other_triggers_and_honors_settle(role_settings, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(config, "load", lambda: role_settings)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    calls, sleeps = [], []
    items = [comment(30, executor("状态：进行中\n在等：总设计\n关键数字：1\n下一步：等")),
             comment(31, "核查：报告"), comment(32, "用户问题")]
    def gh(path):
        calls.append(path)
        assert "/issues/comments?" in path
        return items
    monkeypatch.setattr(watch, "gh", gh)
    def forbidden(*args, **kwargs):
        pytest.fail("role watch must not consult stale, idle, board or tmux")
    for name in ("stale", "idle", "board_output", "tmux_panes"):
        monkeypatch.setattr(watch, name, forbidden)
    monkeypatch.setattr(watch.time, "sleep", lambda seconds: sleeps.append(seconds))
    assert ding.main(["watch", "--for", "总设计", "--settle", "7",
                      "--since", "2026-10-14T08:00:00Z"]) == 0
    assert len(calls) == 2 and sleeps == [7]
    output = capsys.readouterr().out
    assert output.count("#30 执行者 comment") == 1
    assert "#31" not in output and "#32" not in output
    assert watch.default_state("o/r", "总设计").exists()
    assert not watch.default_state("o/r").exists()


def test_role_watch_retains_skip_issue_and_seen_filters(role_settings, monkeypatch):
    body = executor("状态：进行中\n在等：总设计\n关键数字：1\n下一步：等")
    monkeypatch.setattr(watch, "gh", lambda path: [comment(30, body)])
    args = (role_settings, "o/r", "2026-10-14T08:00:00Z", "2026-10-14T08:00:00Z")
    item = watch.collect(*args, set(), set(), role="总设计")[0]
    assert watch.collect(*args, {item[1]}, set(), role="总设计") == []
    assert watch.collect(*args, set(), {30}, role="总设计") == []


def test_role_and_orchestrator_watches_run_concurrently_with_separate_default_states(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    loaded = config.Config(root=tmp_path, repo="o/r")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    barrier = Barrier(2)
    def collect(*args, **kwargs):
        barrier.wait(timeout=5)
        return [(watch.now(), "matching comment", True)]
    monkeypatch.setattr(watch, "collect", collect)
    monkeypatch.setattr(watch, "stale", lambda *args: [])
    monkeypatch.setattr(watch, "idle", lambda *args: ([], {}))
    monkeypatch.setattr(watch, "unanswered_design", lambda *args: [])
    monkeypatch.setattr(watch, "unrouted_waits", lambda *args: [])
    monkeypatch.setattr(watch, "stalled", lambda *args: [])
    monkeypatch.setattr(watch, "finished_waits", lambda *args: [])
    monkeypatch.setattr(watch.time, "sleep", lambda seconds: None)
    def run(role):
        args = SimpleNamespace(state=None, checkout=None, since=None, skip_issue=[], role=role,
                               interval=90, settle=0, stale_hours=6, stale_every=3600, max_errors=2,
                               stalled_hours=48)
        return watch.watch(args, loaded)
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(run, [None, "Designer"])) == [0, 0]
    default, designer = watch.default_state("o/r"), watch.default_state("o/r", "Designer")
    assert default != designer
    assert default.exists() and designer.exists()
    assert default.with_suffix(".lock") != designer.with_suffix(".lock")


def test_role_default_state_name_stays_inside_watch_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    path = watch.default_state("o/r", "../../Designer/训练")
    assert path.parent == tmp_path / "ding/watch"
    assert path != watch.default_state("o/r")
    assert watch.default_state("o/r", "Designer A") != watch.default_state("o/r", "Designer/A")


def test_role_watch_explicit_state_keeps_the_existing_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "load", lambda: config.Config(root=tmp_path, repo="o/r"))
    state = tmp_path / "shared.json"
    with state.with_suffix(".lock").open("w") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert ding.main(["watch", "--for", "Designer", "--state", str(state)]) == 3
    assert not state.exists()


@pytest.mark.parametrize("arguments", [["--for"], ["--for", ""], ["--for", "   "]])
def test_role_watch_requires_a_nonempty_name(arguments):
    with pytest.raises(SystemExit) as error:
        ding.main(["watch", *arguments])
    assert error.value.code == 2


def test_role_watch_retries_post_settle_timeout_without_duplicate_output(role_settings, monkeypatch, tmp_path, capsys):
    import subprocess
    monkeypatch.setattr(config, "load", lambda: role_settings)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(watch.time, "sleep", lambda seconds: None)
    calls = []
    def gh(path):
        assert "/issues/comments?" in path
        calls.append(path)
        if len(calls) == 2:
            raise subprocess.TimeoutExpired(["gh", "api", path], 60)
        return [comment(30, executor("状态：进行中\n在等：总设计\n关键数字：1\n下一步：等"))]
    monkeypatch.setattr(watch, "gh", gh)
    assert ding.main(["watch", "--for", "总设计", "--since", "2026-10-14T08:00:00Z",
                      "--interval", "0", "--settle", "0", "--max-errors", "2"]) == 0
    output = capsys.readouterr()
    assert len(calls) == 4
    assert "poll failed 1/2" in output.err
    assert output.out.count("#30 执行者 comment") == 1


@pytest.mark.parametrize("prefix", ["核查：", "总设计：", "总编排：", "用户："])
def test_role_watch_ignores_non_executor_roles_even_when_waiting_on_target(role_settings, monkeypatch, prefix):
    body = prefix + "报告\n在等：总设计\n关键数字：1\n下一步：等"
    monkeypatch.setattr(watch, "gh", lambda path: [comment(30, body)])
    assert watch.collect(role_settings, "o/r", "2026-10-14T08:00:00Z", "2026-10-14T08:00:00Z",
                         set(), set(), role="总设计") == []


@pytest.fixture
def routed_settings(tmp_path):
    return settings(tmp_path, RULING.replace('[status]\n', '[status]\npaused = "暂停"\n') + '''
signatures = ["总设计：", "总设计（训练）："]
[roles.aliases]
"总设计（训练）" = ["训练设计"]
[watch]
handoff = ["交"]
''')


@pytest.mark.parametrize("body, training, general", [
    (executor("状态: 进行中\n在等: 核查和训练设计裁定…\n关键数字: 1\n下一步: 等"), True, False),
    (executor("状态: 进行中\n在等: 总设计(训练)\n关键数字: 1\n下一步: 等"), True, False),
    (executor("状态: 暂停\n在等: 用户/训练设计重新排期\n关键数字: 1\n下一步: 交总设计"), False, False),
    (executor("状态: 等设计\n在等: 裁定 X\n关键数字: 1\n下一步: 等"), False, True),
    (executor("状态: 进行中\n在等: 无\n关键数字: 1\n下一步: 交总设计决定"), False, True),
    ("核查：结论\n交总设计决定", False, True),
    ("总编排：请求\n@总设计 请裁定", False, True),
    ("用户请求\n总设计：请裁定", False, True),
    ("用户请求\n@训练设计 请裁定", True, False),
    ("总设计：自己的裁定\n交总设计", False, False),
    ("总设计(训练):自己的裁定\n@训练设计", False, False),
])
def test_issue32_mention_replays(routed_settings, body, training, general):
    assert watch.role_wakes(body, "总设计（训练）", routed_settings) is training
    assert watch.role_wakes(body, "总设计", routed_settings) is general


def test_alias_matching_is_shared_with_orchestrator_and_normalizes_width(routed_settings):
    body = executor("状态: 进行中\n在等: 训练设计师\n关键数字: 1\n下一步: 等")
    assert watch.waiting_for(body, "总设计（训练）", routed_settings)
    assert watch.waiting_for(body, "训练设计", routed_settings)
    assert not watch.waiting_for(body, "总设计", routed_settings)
    assert watch.executor_wakes(body, False, routed_settings)
    paused = body.replace("进行中", "暂停")
    assert watch.executor_wakes(paused, False, routed_settings)  # Same waiting-name test as in progress.
    assert not watch.executor_wakes(executor("状态: 暂停\n在等: 无"), False, routed_settings)


@pytest.mark.parametrize("kind", ["idle", "stale"])
@pytest.mark.parametrize("after", [False, True])
def test_status_label_only_suppresses_when_added_after_executor(idle_ticket, monkeypatch, kind, after):
    ticket = idle_ticket
    ticket.issues[0]["labels"] = [{"name": "status:blocked"}]
    original = watch.gh
    def gh(path):
        if "/events?" in path:
            return [{"event": "labeled", "label": {"name": "status:blocked"},
                     "created_at": "2026-10-28T11:00:00Z" if after else "2026-10-28T09:00:00Z"}]
        return original(path)
    monkeypatch.setattr(watch, "gh", gh)
    if kind == "idle":
        _, observed = check_idle(ticket)
        ticket.clock.moment += timedelta(hours=1)
        result, _ = check_idle(ticket, observed)
    else:
        ticket.clock.moment += timedelta(hours=6)
        result = watch.stale(ticket.config, "o/r", ticket.config.root, 6, set(), set())
    assert bool(result) is not after


@pytest.fixture
def unanswered_ticket(idle_ticket, routed_settings):
    ticket = idle_ticket
    ticket.config = routed_settings
    ticket.last.update(created_at="2026-10-28T11:29:00Z", updated_at="2026-10-28T11:29:00Z",
                       body=executor("状态: 等设计\n在等: 裁定 X\n关键数字: 1\n下一步: 等"))
    return ticket


@pytest.fixture
def verifier_wait(idle_ticket, routed_settings, monkeypatch):
    ticket = idle_ticket
    ticket.config = routed_settings
    ticket.last.update(created_at="2026-10-28T11:15:00Z", updated_at="2026-10-28T11:15:00Z",
                       body=executor("状态: 进行中\n在等: 核查\n关键数字: 1\n下一步: 等"))
    monkeypatch.setattr(config, "load", lambda: ticket.config)
    return ticket


def test_waits_lists_verifier_wait_until_verifier_replies(verifier_wait, capsys):
    ticket = verifier_wait
    assert ding.main(["waits"]) == 0
    output = capsys.readouterr().out
    assert "#26 waiting on 核查 for 45 minutes" in output
    assert "状态: 进行中; 在等: 核查" in output and ticket.last["html_url"] in output
    ticket.comments.append({"id": 2602, "body": "核查：已核对"})
    ticket.issues[0]["comments"] = 2
    assert ding.main(["waits", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == []


@pytest.mark.parametrize("latest", ["状态: 进行中\n在等: 无", "状态: 暂停\n在等: 核查"])
def test_waits_ignores_superseded_and_paused_waits(verifier_wait, capsys, latest):
    ticket = verifier_wait
    ticket.comments.append({**ticket.last, "id": 2602, "body": executor(latest), "created_at": "2026-10-28T11:20:00Z"})
    ticket.issues[0]["comments"] = 2
    assert ding.main(["waits"]) == 0
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("requested, reply", [
    ("总编排", "总编排：已安排"), ("用户", "同意"), ("训练设计", "总设计(训练): 已答复"),
])
def test_waits_requires_a_reply_from_the_requested_role(verifier_wait, capsys, requested, reply):
    ticket = verifier_wait
    ticket.last["body"] = executor(f"状态: 进行中\n在等: {requested}\n关键数字: 1\n下一步: 等")
    ticket.comments.append({"id": 2602, "body": "核查：其他工作已核对"})
    ticket.issues[0]["comments"] = 2
    assert ding.main(["waits", "--json"]) == 0
    assert len(json.loads(capsys.readouterr().out)) == 1
    ticket.comments.append({"id": 2603, "body": reply})
    ticket.issues[0]["comments"] = 3
    assert ding.main(["waits", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == []


@pytest.mark.parametrize("target, matches", [("总设计（训练）", True), ("总设计(训练)", True), ("训练设计", True), ("总设计", False)])
def test_waits_for_uses_aliases_width_and_longest_name(verifier_wait, capsys, target, matches):
    ticket = verifier_wait
    ticket.last["body"] = executor("状态：进行中\n在等：训练设计师\n关键数字：1\n下一步：等")
    ticket.comments.append({"id": 2602, "body": "总设计：另一个岗位的答复"})
    ticket.issues[0]["comments"] = 2
    assert ding.main(["waits", "--for", target, "--json"]) == 0
    found = json.loads(capsys.readouterr().out)
    assert bool(found) is matches
    if matches:
        assert found[0]["role"] == "总设计（训练）" and found[0]["minutes"] == 45


def test_waits_reports_unanswered_targets_independently(verifier_wait, capsys):
    ticket = verifier_wait
    ticket.last["body"] = executor("状态: 进行中\n在等: 核查、总设计\n关键数字: 1\n下一步: 等")
    ticket.comments.append({"id": 2602, "body": "核查：答复"})
    ticket.issues[0]["comments"] = 2
    assert ding.main(["waits", "--json"]) == 0
    assert [item["role"] for item in json.loads(capsys.readouterr().out)] == ["总设计"]


def test_designer_reply_does_not_hide_an_older_verifier_wait(verifier_wait, monkeypatch):
    ticket = verifier_wait
    ticket.issues[0]["comments"] = 201
    original = watch.gh
    pages = []
    def gh(path):
        if "/comments?" in path:
            pages.append(path)
            if path.endswith("page=3"):
                return [{"id": 2602, "body": "总设计：其他工作已答复"}]
            assert path.endswith("page=2")
            return [ticket.last]
        return original(path)
    monkeypatch.setattr(watch, "gh", gh)
    found = watch.unanswered_design(ticket.config, "o/r", set(), set())
    assert len(found) == 1 and "waiting on 核查 for 45 minutes" in found[0][1]
    assert len(pages) == 2


def test_waits_default_zero_lists_waits_without_enabling_backstop(verifier_wait, capsys):
    from dataclasses import replace
    ticket = verifier_wait
    ticket.config = replace(ticket.config, watch=config.Watch(design_answer_minutes=0))
    assert ding.main(["waits", "--json"]) == 0
    assert len(json.loads(capsys.readouterr().out)) == 1
    assert watch.unanswered_design(ticket.config, "o/r", set(), set()) == []


def test_waits_query_failure_is_not_an_empty_success(verifier_wait, monkeypatch, capsys):
    def failed(path):
        raise RuntimeError("GitHub unavailable")
    monkeypatch.setattr(watch, "gh", failed)
    assert ding.main(["waits", "--json"]) == 1
    output = capsys.readouterr()
    assert output.out == "" and "GitHub unavailable" in output.err


def test_waits_sorts_oldest_first_and_ignores_prs(verifier_wait, monkeypatch, capsys):
    ticket = verifier_wait
    older = {**ticket.last, "id": 2701, "created_at": "2026-10-28T11:00:00Z", "html_url": "https://github.com/o/r/issues/27#issuecomment-2701"}
    ticket.issues += [{"number": 27, "comments": 1, "labels": [], "updated_at": older["created_at"]},
                      {"number": 28, "comments": 1, "pull_request": {}}]
    original = watch.gh
    monkeypatch.setattr(watch, "gh", lambda path: [older] if "/issues/27/comments?" in path else original(path))
    assert ding.main(["waits", "--json"]) == 0
    found = json.loads(capsys.readouterr().out)
    assert [item["ticket"] for item in found] == [27, 26]
    assert found[0] == {"ticket": 27, "role": "核查", "station": "核查", "minutes": 60, "summary": "状态: 进行中; 在等: 核查",
                        "url": older["html_url"], "comment_id": 2701, "created_at": older["created_at"]}


@pytest.mark.parametrize("minutes, count", [(None, 1), ("45", 0), ("46", 0), ("0", 1)])
def test_waits_threshold_and_default(verifier_wait, capsys, minutes, count):
    options = ["--minutes", minutes] if minutes is not None else []
    assert ding.main(["waits", "--json", *options]) == 0
    assert len(json.loads(capsys.readouterr().out)) == count


@pytest.mark.parametrize("options", [["--minutes", "-1"], ["--minutes", "nan"], ["--minutes", "inf"], ["--for", " "]])
def test_waits_rejects_invalid_options(capsys, options):
    with pytest.raises(SystemExit) as error:
        ding.main(["waits", *options])
    assert error.value.code == 2


@pytest.mark.parametrize("sink, exists", [("null", False), ("null", True), ("pipe", False), ("file", False)])
def test_watch_refuses_null_stdout_before_polling_or_touching_state(tmp_path, sink, exists):
    import subprocess
    import sys
    path = tmp_path / "state" / "watch.json"
    initial = '{"since": "2026-10-28T10:00:00Z", "seen": [], "stale": []}'
    if exists:
        path.parent.mkdir()
        path.write_text(initial)
    script = '''
from pathlib import Path
import sys
from dkitchen import config, ding, watch
config.load = lambda: config.Config(root=Path.cwd(), repo="o/r")
def collect(*args, **kwargs):
    Path("polled").write_text("yes")
    return [(watch.now(), "fixture wait", True)]
watch.collect = collect
watch.idle = lambda *args: ([], {})
watch.stale = watch.unanswered_design = watch.unrouted_waits = watch.stalled = watch.finished_waits = lambda *args: []
sys.exit(ding.main(["watch", "--state", sys.argv[1], "--settle", "0"]))
'''
    output_path = tmp_path / "output.txt"
    if sink == "pipe":
        result = subprocess.run([sys.executable, "-c", script, str(path)], cwd=tmp_path, capture_output=True, text=True, timeout=10)
        output = result.stdout
    else:
        with (Path("/dev/null") if sink == "null" else output_path).open("w") as destination:
            result = subprocess.run([sys.executable, "-c", script, str(path)], cwd=tmp_path, stdout=destination,
                                    stderr=subprocess.PIPE, text=True, timeout=10)
        output = output_path.read_text() if sink == "file" else ""
    if sink == "null":
        assert result.returncode == 3 and "stdout is /dev/null" in result.stderr
        assert not (tmp_path / "polled").exists() and not path.with_suffix(".lock").exists()
        if exists:
            assert path.read_text() == initial
        else:
            assert not path.parent.exists()
    else:
        assert result.returncode == 0 and "fixture wait" in output
        assert path.exists() and (tmp_path / "polled").exists()


def test_unanswered_design_reports_default_and_alias_targets_once(unanswered_ticket):
    ticket = unanswered_ticket
    found = watch.unanswered_design(ticket.config, "o/r", set(), set())
    assert len(found) == 1 and found[0][2] == 2601
    assert "waiting on 总设计 for 31 minutes with no designer reply" in found[0][1]
    assert watch.unanswered_design(ticket.config, "o/r", {2601}, set()) == []
    ticket.last["body"] = executor("状态: 进行中\n在等: 训练设计\n关键数字: 1\n下一步: 等")
    found = watch.unanswered_design(ticket.config, "o/r", set(), set())
    assert "waiting on 总设计（训练）" in found[0][1]


@pytest.mark.parametrize("reply", ["总设计：答复", "总设计（训练）：答复", "总设计(训练):答复", "训练设计：答复"])
def test_designer_reply_prevents_backstop(unanswered_ticket, reply):
    ticket = unanswered_ticket
    ticket.comments.append({"id": 2602, "body": reply, "created_at": "2026-10-28T11:40:00Z"})
    ticket.issues[0]["comments"] = 2
    assert watch.unanswered_design(ticket.config, "o/r", set(), set()) == []


def test_unanswered_design_does_not_report_paused_or_premature_request(unanswered_ticket):
    ticket = unanswered_ticket
    ticket.last["created_at"] = "2026-10-28T11:30:00Z"
    assert watch.unanswered_design(ticket.config, "o/r", set(), set()) == []
    ticket.last.update(created_at="2026-10-28T11:00:00Z", body=executor("状态: 暂停\n在等: 训练设计"))
    assert watch.unanswered_design(ticket.config, "o/r", set(), set()) == []


@pytest.mark.parametrize("body, created_at, reported, expected", [
    ("状态: 进行中\n在等: 无", "2026-10-28T11:29:00Z", set(), []),
    ("状态: 暂停\n在等: 训练设计", "2026-10-28T11:29:00Z", set(), []),
    ("状态: 等设计\n在等: 裁定 X", "2026-10-28T11:40:00Z", set(), []),
    ("状态: 等设计\n在等: 裁定 X", "2026-10-28T11:29:00Z", {2602}, []),
    ("状态: 等设计\n在等: 裁定 X", "2026-10-28T11:29:00Z", set(), [2602]),
])
def test_backstop_only_considers_latest_executor_comment(unanswered_ticket, body, created_at, reported, expected):
    ticket = unanswered_ticket
    ticket.last["created_at"] = "2026-10-28T11:00:00Z"
    ticket.comments.append({**ticket.last, "id": 2602, "body": executor(body), "created_at": created_at})
    ticket.issues[0]["comments"] = 2
    found = watch.unanswered_design(ticket.config, "o/r", reported, set())
    assert [item[2] for item in found] == expected


def test_verifier_handoff_wakes_role_but_remains_reference_for_orchestrator(routed_settings, monkeypatch):
    item = comment(32, "核查：结论\n交总设计决定")
    def gh(path):
        return [item] if "/issues/comments?" in path else []
    monkeypatch.setattr(watch, "gh", gh)
    args = (routed_settings, "o/r", "2026-10-14T08:00:00Z", "2026-10-14T08:00:00Z", set(), set())
    role = watch.collect(*args, role="总设计")
    orchestrator = watch.collect(*args)
    assert role[0][2] is True and "for reference" not in role[0][1]
    assert orchestrator[0][2] is False and "for reference" in orchestrator[0][1]


@pytest.mark.parametrize("target", [None, "核查"])
def test_backstop_persists_ids_and_does_not_repeat_after_restart(unanswered_ticket, monkeypatch, capsys, target):
    ticket = unanswered_ticket
    if target:
        ticket.last["body"] = executor(f"状态: 进行中\n在等: {target}\n关键数字: 1\n下一步: 等")
    monkeypatch.setattr(config, "load", lambda: ticket.config)
    monkeypatch.setattr(watch, "collect", lambda *args: [])
    monkeypatch.setattr(watch, "stale", lambda *args: [])
    monkeypatch.setattr(watch, "idle", lambda *args: ([], {}))
    monkeypatch.setattr(watch.time, "sleep", lambda seconds: None)
    path = ticket.config.root / "backstop.json"
    args = ["watch", "--state", str(path), "--since", "2026-10-28T10:00:00Z", "--settle", "0"]
    assert ding.main(args) == 0
    assert json.loads(path.read_text())["design_reported"] == [2601]
    monkeypatch.setattr(watch, "collect", lambda *args: [(watch.now(), "other activity", True)])
    assert ding.main(args) == 0
    output = capsys.readouterr().out
    assert output.count("no role reply" if target else "no designer reply") == 1
    assert "other activity" in output


def test_backstop_runs_on_idle_cadence_instead_of_each_poll(unanswered_ticket, monkeypatch):
    ticket = unanswered_ticket
    ticket.last["created_at"] = "2026-10-28T12:00:00Z"
    monkeypatch.setattr(config, "load", lambda: ticket.config)
    monkeypatch.setattr(watch, "collect", lambda *args: [])
    monkeypatch.setattr(watch, "stale", lambda *args: [])
    monkeypatch.setattr(watch, "idle", lambda *args: ([], {}))
    start = ticket.clock.moment
    monkeypatch.setattr(watch.time, "monotonic", lambda: (ticket.clock.moment - start).total_seconds())
    monkeypatch.setattr(watch.time, "sleep", lambda seconds: setattr(
        ticket.clock, "moment", ticket.clock.moment + timedelta(seconds=seconds)))
    check = watch.unanswered_design
    checks = []
    def traced(*args):
        checks.append((ticket.clock.moment - start).total_seconds())
        return check(*args)
    monkeypatch.setattr(watch, "unanswered_design", traced)
    assert ding.main(["watch", "--state", str(ticket.config.root / "cadence.json"),
                      "--interval", "60", "--settle", "0"]) == 0
    assert checks == [0, 900, 1800, 2700]


def test_for_watch_never_runs_design_backstop(routed_settings, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "load", lambda: routed_settings)
    monkeypatch.setattr(watch, "gh", lambda path: [comment(32, executor("状态: 进行中\n在等: 训练设计"))])
    def forbidden(*args):
        pytest.fail("--for must not consult periodic checks")
    for name in ("unanswered_design", "finished_waits", "idle", "stale", "board_output", "tmux_panes"):
        monkeypatch.setattr(watch, name, forbidden)
    monkeypatch.setattr(watch.time, "sleep", lambda seconds: None)
    assert ding.main(["watch", "--for", "总设计（训练）", "--state", str(tmp_path / "role.json"),
                      "--since", "2026-10-14T08:00:00Z", "--settle", "0"]) == 0


def test_backstop_can_be_disabled_and_does_not_depend_on_idle_enabled(unanswered_ticket, monkeypatch):
    from dataclasses import replace
    ticket = unanswered_ticket
    disabled = replace(ticket.config, watch=config.Watch(design_answer_minutes=0))
    original = watch.gh
    def forbidden(*args):
        pytest.fail("disabled backstop must not query GitHub")
    monkeypatch.setattr(watch, "gh", forbidden)
    assert watch.unanswered_design(disabled, "o/r", set(), set()) == []
    monkeypatch.setattr(watch, "gh", original)
    ticket.config = replace(ticket.config, watch=config.Watch(idle_minutes=0))
    monkeypatch.setattr(config, "load", lambda: ticket.config)
    monkeypatch.setattr(watch, "collect", lambda *args: [])
    monkeypatch.setattr(watch, "stale", lambda *args: [])
    assert ding.main(["watch", "--state", str(ticket.config.root / "idle-off.json")]) == 0


def test_backstop_reads_only_latest_page_when_all_watched_roles_replied(unanswered_ticket, monkeypatch):
    ticket = unanswered_ticket
    ticket.issues[0]["comments"] = 202
    original = watch.gh
    pages = []
    def gh(path):
        if "/comments?" in path:
            pages.append(path)
            assert path.endswith("page=3")
            return [{"id": 2602, "body": "总设计：已答复"}, {"id": 2603, "body": "核查：已答复"}]
        return original(path)
    monkeypatch.setattr(watch, "gh", gh)
    assert watch.unanswered_design(ticket.config, "o/r", set(), set()) == []
    assert len(pages) == 1


@pytest.mark.parametrize("phase", ["idle", "stale"])
def test_label_history_failure_retries_without_advancing_state(idle_ticket, monkeypatch, phase):
    import subprocess
    ticket = idle_ticket
    ticket.clock.moment += timedelta(hours=6)
    ticket.issues[0]["labels"] = [{"name": "status:blocked"}]
    monkeypatch.setattr(config, "load", lambda: ticket.config)
    monkeypatch.setattr(watch, "collect", lambda *args: [])
    if phase == "idle":
        monkeypatch.setattr(watch, "stale", lambda *args: [])
    original = watch.gh
    def gh(path):
        if "/events?" in path:
            raise subprocess.TimeoutExpired(["gh", "api", path], 60)
        return original(path)
    monkeypatch.setattr(watch, "gh", gh)
    monkeypatch.setattr(watch.time, "sleep", lambda seconds: None)
    path = ticket.config.root / "errors.json"
    assert ding.main(["watch", "--state", str(path), "--max-errors", "2", "--interval", "0"]) == 2
    assert not path.exists()


def test_backstop_api_failure_uses_bounded_retry_and_preserves_state(unanswered_ticket, monkeypatch):
    import subprocess
    ticket = unanswered_ticket
    monkeypatch.setattr(config, "load", lambda: ticket.config)
    monkeypatch.setattr(watch, "collect", lambda *args: [])
    monkeypatch.setattr(watch, "stale", lambda *args: [])
    monkeypatch.setattr(watch, "idle", lambda *args: ([], {}))
    original = watch.gh
    def gh(path):
        if "/comments?" in path:
            raise subprocess.TimeoutExpired(["gh", "api", path], 60)
        return original(path)
    monkeypatch.setattr(watch, "gh", gh)
    monkeypatch.setattr(watch.time, "sleep", lambda seconds: None)
    path = ticket.config.root / "backstop-errors.json"
    initial = json.dumps({"since": "2026-10-28T10:00:00Z", "seen": [], "stale": [], "design_reported": []})
    path.write_text(initial)
    assert ding.main(["watch", "--state", str(path), "--max-errors", "2", "--interval", "0"]) == 2
    assert path.read_text() == initial


def test_open_issue_pagination_reaches_older_tickets_without_duplicates(monkeypatch):
    paths = []
    def gh(path):
        paths.append(path)
        return [{"number": number} for number in range(1, 101)] if path.endswith("page=1") else [{"number": 100}, {"number": 318}]
    monkeypatch.setattr(watch, "gh", gh)
    assert [issue["number"] for issue in watch.open_issues("o/r")] == [*range(1, 101), 318]
    assert len(paths) == 2


def test_optional_config_defaults_are_backward_compatible(tmp_path):
    loaded = settings(tmp_path)
    assert loaded.roles.aliases == {}
    assert loaded.status.paused is None
    assert loaded.watch.design_answer_minutes == 30
    assert settings(tmp_path, '[watch]\ndesign_answer_minutes = 0').watch.design_answer_minutes == 0


def test_backstop_reports_new_requests_after_a_previous_designer_reply(unanswered_ticket):
    ticket = unanswered_ticket
    older_reply = {"id": 2600, "body": "总设计：之前已答复", "created_at": "2026-10-28T11:00:00Z"}
    ticket.comments.insert(0, older_reply)
    ticket.issues[0]["comments"] = 2
    assert watch.unanswered_design(ticket.config, "o/r", set(), set())[0][2] == 2601
    assert watch.unanswered_design(ticket.config, "o/r", set(), {26}) == []


def test_label_history_uses_latest_addition_and_requires_a_newer_event(idle_ticket, monkeypatch):
    ticket = idle_ticket
    issue = ticket.issues[0]
    issue["labels"] = [{"name": "status:blocked"}]
    events = [{"event": "labeled", "label": {"name": "status:blocked"}, "created_at": "2026-10-28T09:00:00Z"},
              {"event": "unlabeled", "label": {"name": "status:blocked"}, "created_at": "2026-10-28T09:30:00Z"},
              {"event": "labeled", "label": {"name": "status:blocked"}, "created_at": "2026-10-28T11:00:00Z"}]
    monkeypatch.setattr(watch, "gh", lambda path: events)
    assert watch.label_suppresses(ticket.config, "o/r", issue, ticket.last)
    events.clear()
    assert not watch.label_suppresses(ticket.config, "o/r", issue, ticket.last)


@pytest.mark.parametrize('verdict, expected', [('pass', 'success'), ('changes', 'failure')])
def test_review_posts_comment_and_status_on_full_head(tmp_path, monkeypatch, capsys, verdict, expected):
    loaded = settings(tmp_path, 'repo="o/r"\n[merge]\nreview_check="review"')
    monkeypatch.setattr(config, 'load', lambda: loaded)
    body = tmp_path / 'review.md'
    body.write_text('Reviewed tests.')
    calls = []
    sha = 'abcdef0123456789'
    monkeypatch.setattr(orchestrate, 'call', fake_call([
        (0, json.dumps({'headRefOid': sha})), (0, '{"html_url":"https://review"}'), (0, '{}')], calls))
    assert ding.main(['review', '7', sha[:8], verdict, '--body-file', str(body)]) == 0
    line = 'pass' if verdict == 'pass' else 'changes requested, see below'
    assert calls[1][-1].startswith(f'body=Reviewed {sha[:8]}: {line}\n\n') and 'Reviewed tests.' in calls[1][-1]
    assert calls[2] == ('gh', 'api', f'repos/o/r/statuses/{sha}', '-f', f'state={expected}',
                        '-f', 'context=review', '-f', 'target_url=https://review')


@pytest.mark.parametrize('stage, message, count', [('head', 'HEAD is now', 1),
    ('comment', 'review comment failed', 2), ('status', 'review status failed', 3)])
def test_review_refuses_stale_sha_and_reports_partial_failure(tmp_path, monkeypatch, capsys, stage, message, count):
    loaded = settings(tmp_path, 'repo="o/r"\n[merge]\nreview_check="review"')
    body = tmp_path / 'review.md'
    body.write_text('details')
    calls = []
    responses = [(0, '{"headRefOid":"abc123"}'),
                 (1, '') if stage == 'comment' else (0, '{"html_url":"https://review"}'), (1, '')]
    monkeypatch.setattr(orchestrate, 'call', fake_call(responses, calls))
    assert orchestrate.review(SimpleNamespace(pr=7, sha='old' if stage == 'head' else 'abc',
                                             verdict='pass', body_file=body), loaded) == 1
    assert message in capsys.readouterr().err
    assert len(calls) == count


@pytest.mark.parametrize('change, state, missing, reason', [
    ({'isDraft': True}, 'success', False, 'draft'),
    ({'state': 'CLOSED'}, 'success', False, 'CLOSED'),
    ({'baseRefName': 'stacked'}, 'success', False, 'stacked, not repository default branch main'),
    ({}, 'failure', False, 'failure'), ({}, 'pending', False, 'pending'),
    ({}, 'success', True, 'missing'), ({}, 'success', False, ''),
])
def test_shared_readiness_reasons(tmp_path, monkeypatch, change, state, missing, reason):
    loaded = settings(tmp_path, 'repo="o/r"\n[merge]\nreview_check="review"')
    pr = json.loads(view()[1]) | change
    monkeypatch.setattr(orchestrate, 'call', fake_call(check_responses(
        statuses=[] if missing else [commit_status(state, 'review')]), []))
    result = orchestrate.readiness(loaded, 'o/r', pr, 'main')
    assert result['ready'] == (not reason)
    assert reason in '; '.join(result['reasons'])


@pytest.mark.parametrize('ticket_body', ['', 'Claude session: worker'])
@pytest.mark.parametrize('head', ['abc123', 'new123'])
def test_review_gate_needs_no_executor_comment_and_expires_on_push(tmp_path, monkeypatch, capsys, ticket_body, head):
    loaded = settings(tmp_path, 'repo="o/r"\n[merge]\nreview_check="review"')
    calls = []
    responses = [view(head=head, body=ticket_body)] + check_responses(
        statuses=[commit_status('success', 'review')], sha='abc123')
    if head == 'abc123':
        responses += [(0, ''), view('MERGED')]
    monkeypatch.setattr(orchestrate, 'call', fake_call(responses, calls))
    assert orchestrate.merge(SimpleNamespace(pr=7, sha=head), loaded) == (head != 'abc123')
    assert not any('/issues/' in str(call) for call in calls)


def test_merge_refuses_wrong_base_without_review_check(tmp_path, monkeypatch, capsys):
    loaded = settings(tmp_path, 'repo="o/r"')
    pr = json.loads(view()[1]) | {'baseRefName': 'stacked'}
    calls = []
    monkeypatch.setattr(orchestrate, 'call', fake_call([(0, json.dumps(pr))], calls))
    assert orchestrate.merge(SimpleNamespace(pr=7, sha='abc'), loaded) == 1
    assert 'stacked, not repository default branch main' in capsys.readouterr().err
    assert len(calls) == 1


@pytest.fixture
def review_pr(idle_ticket, monkeypatch):
    from dataclasses import replace
    ticket = idle_ticket
    ticket.config = replace(ticket.config, merge=config.Merge(required_checks=('ci',), review_check='review'))
    ticket.pull = {'number': 7, 'state': 'open', 'draft': False, 'base': {'ref': 'main'},
                   'head': {'sha': 'abc123'}, 'labels': [], 'updated_at': '2026-10-28T10:00:00Z',
                   'html_url': 'https://github.com/o/r/pull/7'}
    ticket.review = None
    ticket.ci = 'success'
    ticket.api_calls = []
    def call(settings, *args):
        ticket.api_calls.append(args)
        assert args[:3] == ('gh', 'api', 'graphql')
        pull = ticket.pull
        contexts = [{'name': 'ci', 'status': 'COMPLETED' if ticket.ci != 'pending' else 'IN_PROGRESS',
                     'conclusion': ticket.ci.upper() if ticket.ci != 'pending' else None, 'detailsUrl': 'https://ci'}]
        if ticket.review:
            contexts.append({'context': 'review', 'state': ticket.review.upper(), 'targetUrl': 'https://review'})
        pr = {'number': pull['number'], 'state': 'OPEN', 'isDraft': pull['draft'],
              'baseRefName': pull['base']['ref'], 'headRefOid': pull['head']['sha'],
              'updatedAt': pull['updated_at'], 'url': pull['html_url'],
              'labels': {'nodes': pull['labels'], 'pageInfo': {'hasNextPage': False}},
              'commits': {'nodes': [{'commit': {'oid': pull['head']['sha'], 'statusCheckRollup':
                  {'contexts': {'nodes': contexts, 'pageInfo': {'hasNextPage': False}}}}}]}}
        nodes = [dict(pr, number=n) for n in range(1, 17)] if getattr(ticket, 'sixteen', False) else [pr]
        data = [{'data': {'repository': {'defaultBranchRef': {'name': 'main'},
                'pullRequests': {'nodes': nodes, 'pageInfo': {'hasNextPage': False, 'endCursor': None}}}}}]
        return SimpleNamespace(returncode=0, stdout=json.dumps(data), stderr='')
    monkeypatch.setattr(orchestrate, 'call', call)
    monkeypatch.setattr(config, 'load', lambda: ticket.config)
    return ticket


@pytest.mark.parametrize('review, label, target, expected', [
    (None, None, 'Verifier', 'review-missing'), (None, 'Guest reviewer', 'Guest reviewer', 'review-missing'),
    ('failure', None, None, 'review-failed'), ('success', None, None, 'ready')])
def test_pr_watch_persists_deduplication_and_new_head_wakes(review_pr, monkeypatch, capsys, review, label, target, expected):
    ticket = review_pr
    ticket.review = review
    if label:
        ticket.pull['labels'] = [{'name': f'review:{label}'}]
    monkeypatch.setattr(watch, 'collect', lambda *args, **kwargs: [])
    monkeypatch.setattr(watch, 'stale', lambda *args: [])
    monkeypatch.setattr(watch, 'idle', lambda *args: ([], {}))
    monkeypatch.setattr(watch.time, 'sleep', lambda seconds: None)
    path = ticket.config.root / 'prs.json'
    args = ['watch', '--state', str(path), '--settle', '0'] + (['--for', target] if target else [])
    assert ding.main(args) == 0
    assert json.loads(path.read_text())['pr_reported'] == [f'7:abc123:{expected}']
    monkeypatch.setattr(watch, 'collect', lambda *args, **kwargs: [(watch.now(), 'other event', True)])
    assert ding.main(args) == 0
    assert capsys.readouterr().out.count(f'PR #7 {expected}') == 1
    ticket.pull['head']['sha'] = 'new123'
    assert ding.main(args) == 0
    assert f'7:new123:{expected}' in json.loads(path.read_text())['pr_reported']


@pytest.mark.parametrize('review', [None, 'success'])
def test_pr_backstop_survives_restart_and_metadata_changes(review_pr, monkeypatch, review):
    ticket = review_pr
    ticket.review = review
    ticket.pull['labels'] = [{'name': 'review:Unknown session'}]
    first, pending = watch.pr_wakes(ticket.config, 'o/r', None, set(), {}, set())
    reported = {key for _, _, key in first}
    ticket.clock.moment += timedelta(minutes=31)
    ticket.pull['updated_at'] = watch.now()
    found, _ = watch.pr_wakes(ticket.config, 'o/r', None, reported, json.loads(json.dumps(pending)), set())
    assert len(found) == 1 and 'overdue for 31 minutes' in found[0][1]
    assert watch.pr_wakes(ticket.config, 'o/r', None, reported | {found[0][2]}, pending, set())[0] == []


def test_waits_uses_readiness_and_routes_unconfigured_label(review_pr, capsys):
    review_pr.pull['labels'] = [{'name': 'review:Guest'}]
    assert ding.main(['waits', '--for', 'Guest', '--json']) == 0
    item, = json.loads(capsys.readouterr().out)
    assert item['kind'] == 'review-missing' and item['head'] == 'abc123'
    assert item['role'] == 'Guest' and 'missing' in item['summary']
    review_pr.review = 'success'
    review_pr.ci = 'failure'
    assert ding.main(['waits', '--json']) == 0
    item, = json.loads(capsys.readouterr().out)
    assert item['kind'] == 'blocked' and 'ci is failure' in item['summary']


@pytest.mark.parametrize('condition', ['quiet', 'running', 'tmux', 'newer', 'early', 'known', 'none', 'done', 'skip'])
def test_unrouted_wait_backstop(idle_ticket, condition):
    ticket = idle_ticket
    ticket.last['body'] = executor('Status: in progress\nWaiting on: Guest session\nKey numbers: 0\nNext: wait')
    if condition == 'running':
        ticket.board = ticket.board.rstrip('\n') + 'running\n'
    elif condition == 'tmux':
        ticket.panes = 'issue26|0|python'
    elif condition == 'newer':
        ticket.comments.append({'body': 'User: looking', 'created_at': '2026-10-28T11:45:00Z'})
        ticket.issues[0]['comments'] = 2
    elif condition == 'early':
        ticket.last['updated_at'] = '2026-10-28T11:45:00Z'
    elif condition in {'known', 'none'}:
        ticket.last['body'] = ticket.last['body'].replace('Guest session', 'Verifier' if condition == 'known' else 'none')
    elif condition == 'done':
        ticket.last['body'] = ticket.last['body'].replace('in progress', 'done')
    skip = {26} if condition == 'skip' else set()
    found = watch.unrouted_waits(ticket.config, 'o/r', ticket.config.root, set(), skip)
    assert bool(found) == (condition == 'quiet')
    if found:
        assert watch.unrouted_waits(ticket.config, 'o/r', ticket.config.root, {2601}, skip) == []


def test_unrouted_watch_persists_once_per_comment(idle_ticket, monkeypatch, capsys):
    ticket = idle_ticket
    ticket.last['body'] = executor('Status: in progress\nWaiting on: Guest session\nKey numbers: 0\nNext: wait')
    monkeypatch.setattr(config, 'load', lambda: ticket.config)
    monkeypatch.setattr(watch, 'collect', lambda *args: [])
    monkeypatch.setattr(watch, 'stale', lambda *args: [])
    monkeypatch.setattr(watch, 'idle', lambda *args: ([], {}))
    monkeypatch.setattr(watch.time, 'sleep', lambda seconds: None)
    path = ticket.config.root / 'unrouted.json'
    args = ['watch', '--state', str(path), '--settle', '0']
    assert ding.main(args) == 0
    assert json.loads(path.read_text())['unrouted_reported'] == [2601]
    monkeypatch.setattr(watch, 'collect', lambda *args: [(watch.now(), 'other', True)])
    assert ding.main(args) == 0
    assert capsys.readouterr().out.count('unrouted wait') == 1
    ticket.last['id'] = 2602
    assert ding.main(args) == 0
    assert json.loads(path.read_text())['unrouted_reported'] == [2601, 2602]


def test_pr_backstop_timer_is_saved_without_advancing_comment_cursor(review_pr, monkeypatch):
    ticket = review_pr
    monkeypatch.setattr(watch, 'stale', lambda *args: [])
    monkeypatch.setattr(watch, 'idle', lambda *args: ([], {}))
    monkeypatch.setattr(watch.time, 'sleep', lambda seconds: None)
    calls = []
    def collect(*args):
        calls.append(1)
        if len(calls) > 1:
            raise RuntimeError('offline')
        return []
    monkeypatch.setattr(watch, 'collect', collect)
    path = ticket.config.root / 'timer.json'
    args = ['watch', '--state', str(path), '--since', '2026-10-28T09:00:00Z', '--max-errors', '1', '--settle', '0']
    assert ding.main(args) == 2
    state = json.loads(path.read_text())
    assert state['since'] == '2026-10-28T09:00:00Z'
    assert state['pr_observed'] == {'7:abc123:review-missing': '2026-10-28T12:00:00Z'}
    ticket.clock.moment += timedelta(minutes=31)
    monkeypatch.setattr(watch, 'collect', lambda *args: [])
    assert ding.main(args) == 0
    assert json.loads(path.read_text())['pr_reported'] == ['7:abc123:review-missing:overdue']


def test_pr_poll_failure_does_not_consume_events_or_state(review_pr, monkeypatch, capsys):
    path = review_pr.config.root / 'error.json'
    initial = json.dumps({'since': '2026-10-28T09:00:00Z', 'seen': [], 'pr_reported': []})
    path.write_text(initial)
    monkeypatch.setattr(watch, 'collect', lambda *args: [(watch.now(), 'do not consume', True)])
    monkeypatch.setattr(orchestrate, 'call', lambda *args: SimpleNamespace(returncode=1, stderr='offline', stdout=''))
    assert ding.main(['watch', '--state', str(path), '--max-errors', '1']) == 2
    assert path.read_text() == initial
    assert 'do not consume' not in capsys.readouterr().out


@pytest.mark.parametrize('payload', ['{}', 'not json', '{"default_branch":""}'])
def test_merge_refuses_missing_default_branch(tmp_path, monkeypatch, payload):
    loaded = settings(tmp_path, 'repo="o/r"')
    responses = [view()[1], payload]
    calls = []
    def call(config, *args):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout=responses.pop(0), stderr='')
    monkeypatch.setattr(orchestrate, 'call', call)
    assert orchestrate.merge(SimpleNamespace(pr=7, sha='abc'), loaded) == 1
    assert calls[-1] == ('gh', 'api', 'repos/o/r')


@pytest.mark.parametrize('stage', ['head', 'comment'])
def test_review_rejects_malformed_api_response(tmp_path, monkeypatch, capsys, stage):
    loaded = settings(tmp_path, 'repo="o/r"\n[merge]\nreview_check="review"')
    body = tmp_path / 'review.md'
    body.write_text('details')
    calls = []
    responses = [(0, '{}')] if stage == 'head' else [(0, '{"headRefOid":"abc123"}'), (0, '{}')]
    monkeypatch.setattr(orchestrate, 'call', fake_call(responses, calls))
    assert orchestrate.review(SimpleNamespace(pr=7, sha='abc', verdict='pass', body_file=body), loaded) == 1
    assert 'cannot read' in capsys.readouterr().err
    assert not any('/statuses/' in str(call) for call in calls)


def test_review_requires_config_before_any_call(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(orchestrate, 'call', lambda *args: pytest.fail('no gh call without review_check'))
    assert orchestrate.review(SimpleNamespace(), settings(tmp_path)) == 1
    assert 'requires [merge] review_check' in capsys.readouterr().err


@pytest.mark.parametrize('target', ['Orchestrator', 'Boss'])
def test_orchestrator_for_runs_all_backstops_and_collects_as_bare(review_pr, monkeypatch, target):
    from dataclasses import replace
    ticket = review_pr
    ticket.config = replace(ticket.config, roles=replace(ticket.config.roles, aliases={'Orchestrator': ('Boss',)}))
    ticket.review = 'failure'
    phases = []
    def collect(*args, **kwargs):
        assert not kwargs
        return []
    monkeypatch.setattr(watch, 'collect', collect)
    for name in ('stale', 'unanswered_design', 'unrouted_waits'):
        monkeypatch.setattr(watch, name, lambda *args, name=name: phases.append(name) or [])
    monkeypatch.setattr(watch, 'idle', lambda *args: (phases.append('idle') or [], {}))
    assert ding.main(['watch', '--for', target, '--state', str(ticket.config.root / 'boss.json')]) == 0
    assert set(phases) == {'stale', 'idle', 'unanswered_design', 'unrouted_waits'}
    assert '7:abc123:review-failed' in json.loads((ticket.config.root / 'boss.json').read_text())['pr_reported']


@pytest.mark.parametrize('condition', ['failed', 'base', 'pending'])
def test_reviewed_blocked_pr_wakes_or_waits_for_backstop(review_pr, condition):
    ticket = review_pr
    ticket.review = 'success'
    ticket.ci = 'pending' if condition == 'pending' else 'failure' if condition == 'failed' else 'success'
    if condition == 'base':
        ticket.pull['base']['ref'] = 'stacked'
    found, observed = watch.pr_wakes(ticket.config, 'o/r', None, set(), {}, set())
    assert bool(found) == (condition != 'pending')
    reported = {key for _, _, key in found}
    assert watch.pr_wakes(ticket.config, 'o/r', None, reported, observed, set())[0] == []
    ticket.clock.moment += timedelta(minutes=31)
    overdue, _ = watch.pr_wakes(ticket.config, 'o/r', None, reported, observed, set())
    assert len(overdue) == 1
    if condition == 'base':
        assert 'stacked' in overdue[0][1]


def test_sixteen_pr_poll_uses_at_most_three_gh_calls(review_pr):
    review_pr.sixteen = True
    assert len(watch.pr_waits(review_pr.config, 'o/r', set())) == 16
    assert len(review_pr.api_calls) <= 3
    assert '--paginate' in review_pr.api_calls[0]


@pytest.mark.parametrize('review', [None, 'success', 'failure'])
def test_waits_excludes_drafts_except_failed_review(review_pr, capsys, review):
    review_pr.pull['draft'] = True
    review_pr.review = review
    assert ding.main(['waits', '--json']) == 0
    assert bool(json.loads(capsys.readouterr().out)) == (review == 'failure')


@pytest.mark.parametrize('enabled', [False, True])
def test_review_comment_is_verifier_only_with_review_check(tmp_path, enabled):
    loaded = settings(tmp_path, 'repo="o/r"\n[merge]\nreview_check=' + ('"review"' if enabled else '""'))
    expected = loaded.roles.verifier if enabled else loaded.roles.user
    assert watch.signer('Reviewed e7870cd7: pass\n\nchecked', loaded) == expected
    assert watch.signer('Reviewed e7870cd7: changes requested, see below\n\nfindings', loaded) == expected
    assert watch.signer('Reviewed it: pass', loaded) == loaded.roles.user


def test_review_lines_follow_the_configured_wording(tmp_path, monkeypatch):
    loaded = settings(tmp_path, 'repo="o/r"\n[merge]\nreview_check="review"\n'
                                'review_pass="审过 {sha}：通过"\nreview_changes="审过 {sha}：有出入，见下"')
    assert watch.signer('审过 e7870cd7：通过\n\nchecked', loaded) == loaded.roles.verifier
    assert watch.signer('审过 e7870cd7:有出入,见下', loaded) == loaded.roles.verifier
    assert watch.signer('Reviewed e7870cd7: pass', loaded) == loaded.roles.user
    body = tmp_path / 'review.md'
    body.write_text('details')
    calls = []
    monkeypatch.setattr(orchestrate, 'call', fake_call([
        (0, '{"headRefOid":"abcdef0123"}'), (0, '{"html_url":"https://review"}'), (0, '{}')], calls))
    assert orchestrate.review(SimpleNamespace(pr=7, sha='abcdef01', verdict='changes', body_file=body), loaded) == 0
    assert calls[1][-1] == 'body=审过 abcdef01：有出入，见下\n\ndetails'


def test_handoff_words_default_to_english_and_are_configurable(tmp_path):
    english = settings(tmp_path, 'repo="o/r"')
    assert watch.role_wakes("Orchestrator: done\nhand to Designer", "Designer", english)
    assert not watch.role_wakes("Orchestrator: done\n交Designer", "Designer", english)
    chinese = settings(tmp_path, 'repo="o/r"\n[watch]\nhandoff = ["交"]')
    assert watch.role_wakes("Orchestrator: done\n交Designer", "Designer", chinese)
    with pytest.raises(ValueError, match="handoff must be a nonempty list"):
        settings(tmp_path, '[watch]\nhandoff = []')


def pr_states(monkeypatch, prs):
    """Answer `repos/o/r/pulls/N` from `prs`; a missing number is a 404."""
    original = watch.gh

    def gh(path):
        if path.startswith("repos/o/r/pulls/"):
            number = int(path.rsplit("/", 1)[1])
            if number not in prs:
                raise RuntimeError("gh: Not Found (HTTP 404)")
            return prs[number]
        return original(path)
    monkeypatch.setattr(watch, "gh", gh)


MERGED = {"state": "closed", "merged_at": "2026-11-02T00:00:00Z", "labels": [], "body": "Closes #26",
          "head": {"ref": "fix"}}
OTHER = {**MERGED, "body": "Closes #25"}  # another ticket's PR


@pytest.mark.parametrize("waiting, prs, roles", [
    ("核查、总编排、用户, PR #31", {31: MERGED}, ["用户"]),
    ("核查审 PR＃31，总编排合入", {31: {**MERGED, "merged_at": None}}, []),
    ("核查、总编排 https://github.com/o/r/pull/31", {31: MERGED}, []),
    ("核查审查PR31当前HEAD；总编排合入", {31: MERGED}, []),
    ("核查、总编排 PR #31", {31: {**MERGED, "body": "修复#26的问题"}}, []),
    ("核查、总编排 PR #31", {31: {**MERGED, "body": "see https://github.com/o/r/issues/26"}}, []),
    ("核查、总编排 PR #31", {31: {**MERGED, "body": "", "head": {"ref": "codex/issue26-fix"}}}, []),
    ("核查、总编排 PR #31", {31: {**MERGED, "body": "Closes #260"}}, ["核查", "总编排"]),
    ("核查、总编排 PR #31", {31: {"state": "open", "labels": []}}, ["核查", "总编排"]),
    ("核查、总编排 PR #31 PR #32", {31: MERGED, 32: {"state": "open", "labels": []}}, ["核查", "总编排"]),
    ("核查、总编排 https://github.com/x/y/pull/31", {}, ["核查", "总编排"]),
    ("核查、总编排 PR #33", {}, ["核查", "总编排"]),
    ("总设计审 PR #31", {31: {**MERGED, "labels": [{"name": "review:总设计"}]}}, []),
    ("总设计审 PR #31", {31: MERGED}, ["总设计"]),
    ("核查、总编排", {}, ["核查", "总编排"]),
])
def test_waits_drop_review_and_merge_rows_once_the_tickets_own_pr_is_finished(verifier_wait, monkeypatch, capsys,
                                                                             waiting, prs, roles):
    verifier_wait.last["body"] = executor(f"状态: 进行中\n在等: {waiting}\n关键数字: 1\n下一步: 等")
    pr_states(monkeypatch, prs)
    assert ding.main(["waits", "--json"]) == 0
    assert sorted(item["role"] for item in json.loads(capsys.readouterr().out)) == sorted(roles)


def test_a_wait_on_another_tickets_merged_pr_keeps_its_rows_and_says_so(verifier_wait, monkeypatch, capsys):
    # Human-centric-agents#1902: blocked on #1888's PR #1900 merging, asking the orchestrator to tell it.
    verifier_wait.last["body"] = executor("状态: 阻塞\n在等: #25（PR #31）合入 main；合入后请总编排告诉我\n关键数字: 0\n下一步: 等")
    pr_states(monkeypatch, {31: OTHER})
    assert ding.main(["waits", "--json"]) == 0
    [row] = json.loads(capsys.readouterr().out)
    assert row["role"] == "总编排" and row["summary"].endswith("(PR #31 merged)")


@pytest.mark.parametrize("prs, kept", [({31: MERGED}, False), ({31: OTHER}, True)])
def test_a_finished_pr_also_quiets_the_watch_backstop(verifier_wait, monkeypatch, prs, kept):
    verifier_wait.last["body"] = executor("状态: 进行中\n在等: 核查审 PR #31\n关键数字: 1\n下一步: 等")
    pr_states(monkeypatch, prs)
    assert bool(watch.unanswered_design(verifier_wait.config, "o/r", set(), set())) is kept


def pull(number, updated, draft=True, title="WIP"):
    return {"number": number, "draft": draft, "updated_at": updated, "title": title,
            "html_url": f"https://github.com/o/r/pull/{number}"}


@pytest.fixture
def stalled_line(verifier_wait):
    """Ticket #26 in progress with no wait, last touched 50 hours before the clock; drafts on either side of 48 h."""
    ticket = verifier_wait
    old = "2026-10-26T10:00:00Z"
    ticket.last.update(created_at=old, updated_at=old, body=executor("状态: 进行中\n在等: 无\n关键数字: 1\n下一步: 跑"))
    ticket.issues[0]["updated_at"] = old
    ticket.pulls = [pull(1350, "2026-10-25T12:00:00Z"), pull(1351, old, draft=False),
                    pull(1352, "2026-10-28T06:00:00Z")]
    return ticket


def test_waits_lists_stalled_drafts_and_tickets_that_name_no_wait(stalled_line, capsys):
    assert ding.main(["waits"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "stalled:",
        "PR #1350 stalled, not updated for 72 hours: draft: WIP https://github.com/o/r/pull/1350",
        f"#26 stalled, not updated for 50 hours: 状态: 进行中; 在等: 无 {stalled_line.last['html_url']}",
    ]
    assert ding.main(["waits", "--json"]) == 0
    found = json.loads(capsys.readouterr().out)
    assert [(item["kind"], item["pr"], item["ticket"], item["role"]) for item in found] == [
        ("stalled", True, 1350, "总编排"), ("stalled", False, 26, "总编排")]


@pytest.mark.parametrize("options, change", [
    (["--stalled-hours", "0"], None),
    (["--for", "核查"], None),
    (["--stalled-hours", "61"], None),
    ([], "在等: 核查"),
    ([], "状态: 阻塞\n在等: 无"),
    ([], "awaiting"),
])
def test_stalled_skips_waits_other_states_and_other_roles(stalled_line, capsys, options, change):
    ticket = stalled_line
    ticket.pulls = []
    if change == "awaiting":
        ticket.issues[0]["labels"] = [{"name": ticket.config.labels.awaiting_user}]
    elif change:
        ticket.last["body"] = executor(f"状态: 进行中\n{change}\n关键数字: 1\n下一步: 跑".replace("状态: 进行中\n状态", "状态"))
    assert ding.main(["waits", *options]) == 0
    assert "stalled" not in capsys.readouterr().out


@pytest.mark.parametrize("board, panes", [
    ("NAME\tCWD\tSTATUS\tISSUE\tHEAD\tRUN\n【#26】worker\t/r\tactive\t#26\thead\trunning\n", ""),
    ("NAME\tCWD\tSTATUS\tISSUE\tHEAD\tRUN\n", "issue26-occupy|0|python\n"),
])
def test_a_ticket_with_a_running_job_is_not_stalled(stalled_line, capsys, board, panes):
    # Human-centric-agents#1451: a resident job, quiet for 198 hours by design.
    stalled_line.pulls, stalled_line.board, stalled_line.panes = [], board, panes
    assert ding.main(["waits"]) == 0
    assert capsys.readouterr().out == ""


def test_the_orchestrator_hears_of_each_stalled_item_once_a_day(stalled_line, monkeypatch, capsys):
    ticket = stalled_line
    monkeypatch.setattr(watch.time, "sleep", lambda seconds: None)
    for name in ("collect",):
        monkeypatch.setattr(watch, name, lambda *args, **kwargs: [])
    for name in ("stale", "unanswered_design", "unrouted_waits", "missing_waiters"):
        monkeypatch.setattr(watch, name, lambda *args: [])
    monkeypatch.setattr(watch, "idle", lambda *args: ([], {}))
    path = ticket.config.root / "watch.json"
    arguments = ["watch", "--state", str(path), "--interval", "0", "--settle", "0"]
    assert ding.main(arguments) == 0
    assert capsys.readouterr().out.count("stalled, not updated") == 2
    assert json.loads(path.read_text())["stalled_reported"] == {"#26": "2026-10-28T12:00:00Z",
                                                                "PR #1350": "2026-10-28T12:00:00Z"}
    ticket.clock.moment += timedelta(hours=23)
    found, current = watch.stalled_wakes(ticket.config, "o/r", ticket.config.root, 48, json.loads(path.read_text())["stalled_reported"], set())
    assert found == [] and current == {"#26", "PR #1350"}
    ticket.clock.moment += timedelta(hours=2)
    assert ding.main(arguments) == 0
    assert capsys.readouterr().out.count("stalled, not updated") == 2


def test_watch_and_waits_take_stalled_hours(capsys):
    for command in ("watch", "waits"):
        with pytest.raises(SystemExit):
            ding.main([command, "--help"])
        assert "--stalled-hours" in capsys.readouterr().out
        with pytest.raises(SystemExit) as error:
            ding.main([command, "--stalled-hours", "-1"])
        assert error.value.code == 2


TWO_LINES = """repo = "o/r"
[roles.aliases]
"Training designer" = ["Training"]
[rule]
signatures = ["Designer: ", "Training designer: "]
"""
VERDICT = "Verifier: first batch matches the gates\n\n| gate | ok |\n"
STAGE_URL = "https://github.com/o/r/issues/42#issuecomment-901"


@pytest.fixture
def verdict(tmp_path, monkeypatch):
    """`ding review --ticket 42` offline: gh and `ding send` are doubles."""
    (tmp_path / config.FILE).write_text(TWO_LINES, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    state = SimpleNamespace(calls=[], sends=[], send_code=0, draft=tmp_path / "verdict.md")
    state.draft.write_text(VERDICT, encoding="utf-8")
    real_main = ding.main

    def run(word, responses, text=None):
        if text is not None:
            state.draft.write_text(text, encoding="utf-8")
        from dkitchen import verdict as module
        monkeypatch.setattr(module, "call", fake_call(list(responses), state.calls))
        return real_main(["review", "--ticket", "42", word, "--body-file", str(state.draft)])

    def main(argv):
        if argv[0] != "send":
            return real_main(argv)
        state.sends.append(argv)
        return state.send_code

    monkeypatch.setattr(ding, "main", main)
    state.run = run
    return state


def issue(body):
    return 0, json.dumps({"number": 42, "body": body})


def test_a_passing_stage_verdict_is_posted_and_told_to_the_executor(verdict, capsys):
    assert verdict.run("pass", [issue("Design: Designer"), (0, STAGE_URL + "\n")]) == 0
    assert capsys.readouterr().out == STAGE_URL + "\n"
    assert verdict.calls[0] == ("gh", "api", "repos/o/r/issues/42")
    posted = verdict.calls[1]
    assert posted[:6] == ("gh", "issue", "comment", "42", "--repo", "o/r")
    assert posted[7] == "Verifier: first batch matches the gates\nVerdict: pass\n\n| gate | ok |\n"
    assert verdict.sends == [["send", "#42", "--from", "Verifier", "--message",
                              f"#42 Verdict: pass, see the ticket {STAGE_URL}\nVerifier: first batch matches the gates"]]


@pytest.mark.parametrize("bodies, design", [
    ([issue("Design: Training designer; reviewer: Designer\n\n## Problem")], "Training designer"),
    ([issue("Parent: #40\n"), issue("Design: Training; reviewer: Verifier\n")], "Training designer"),
    ([issue("## Problem\nno line named")], "Designer"),
])
def test_changes_hand_the_ticket_to_its_design_line(verdict, capsys, bodies, design):
    assert verdict.run("changes", [*bodies, (0, STAGE_URL)]) == 0
    reads = verdict.calls[:-1]
    assert [call[2] for call in reads] == ["repos/o/r/issues/42", "repos/o/r/issues/40"][:len(reads)]
    body = verdict.calls[-1][7]
    assert body.split("\n")[:3] == ["Verifier: first batch matches the gates", "Verdict: changes requested",
                                    f"hand to {design}"]
    loaded = config.load()
    assert watch.changes_verdict(body, loaded)
    for name in watch.designer_roles(loaded):
        assert watch.role_wakes(body, name, loaded) is (name == design)
    assert verdict.sends[0][-1].startswith(f"#42 Verdict: changes requested, see the ticket {STAGE_URL}")


def test_the_orchestrator_wakes_on_changes_and_only_lists_a_pass(tmp_path, monkeypatch):
    loaded = settings(tmp_path, TWO_LINES)
    passed = "Verifier: ok\nVerdict: pass\n\ndetails"
    changed = "Verifier: gate 2 fails\nVerdict: changes requested\nhand to Designer\n\ndetails"
    comments = [comment(41, passed), comment(42, changed)]
    monkeypatch.setattr(watch, "gh", lambda path: comments if "/issues/comments" in path and "page=1" in path else [])
    found = watch.collect(loaded, "o/r", "2026-10-14T08:00:00Z", "2026-10-14T08:00:00Z", set(), set())
    assert [(line.split(":")[0], wakes) for _, line, wakes in found] == [
        ("#41 Verifier comment (verifier reports separately; for reference)", False),
        ("#42 Verifier comment (Verdict", True)]
    assert not watch.changes_verdict("User: x\nVerdict: changes requested", loaded)


@pytest.mark.parametrize("text, message", [
    ("Designer: x\n", "line 1 must start with 'Verifier: '"),
    ("  \n", "is empty"),
])
def test_a_stage_verdict_without_the_verifier_signature_posts_nothing(verdict, capsys, text, message):
    assert verdict.run("pass", [], text=text) == 1
    assert message in capsys.readouterr().err and verdict.calls == [] and verdict.sends == []


@pytest.mark.parametrize("code, exit_code, words", [
    (ding.NO_LISTENER_EXIT, 0, ["queued in the inbox of #42", "Do not resend"]),
    (1, 1, ["the notification to #42 failed", "the comment stays"]),
])
def test_a_stage_verdict_notification_outcome(verdict, capsys, code, exit_code, words):
    verdict.send_code = code
    assert verdict.run("pass", [issue(""), (0, STAGE_URL)]) == exit_code
    captured = capsys.readouterr()
    assert captured.out == STAGE_URL + "\n" and all(word in captured.err for word in words)


@pytest.mark.parametrize("argv", [
    ["review", "7", "pass"],
    ["review", "--ticket", "42", "ok"],
    ["review", "x", "abc", "pass"],
])
def test_review_arguments_must_fit_one_shape(argv, tmp_path, capsys):
    with pytest.raises(SystemExit):
        ding.main([*argv, "--body-file", str(tmp_path / "b.md")])
    assert "review" in capsys.readouterr().err


@pytest.mark.parametrize("word", ["pass", "changes"])
def test_a_stage_verdict_on_a_pr_number_posts_nothing_and_names_the_pr_form(verdict, capsys, word):
    pr = (0, json.dumps({"number": 42, "body": "Closes #40", "pull_request": {"url": "u"}}))
    assert verdict.run(word, [pr]) == 1
    error = capsys.readouterr().err
    assert "#42 is a PR, not a ticket" in error and f"ding review 42 <SHA> {word}" in error
    assert len(verdict.calls) == 1 and verdict.sends == []


ROLE_CONFIG = 'repo = "o/r"\n[roles]\ndesigner = "总设计师"\n[roles.aliases]\n"总设计师" = ["总设计"]\n'
FIRST, SECOND = "local_11111111-aaaa", "local_22222222-bbbb"


def as_session(monkeypatch, session):
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    if session is None:
        monkeypatch.delenv("CLAUDE_CODE_HOST_SESSION_ID", raising=False)
    else:
        monkeypatch.setenv("CLAUDE_CODE_HOST_SESSION_ID", session)


def role_main(tmp_path, monkeypatch, *words, text=ROLE_CONFIG):
    loaded = settings(tmp_path, text)
    monkeypatch.setattr(config, "load", lambda *args: loaded)
    return ding.main(["role", *words])


def test_role_take_records_the_caller_and_resolves_aliases(tmp_path, monkeypatch, capsys):
    as_session(monkeypatch, FIRST)
    assert role_main(tmp_path, monkeypatch, "take", "总设计") == 0
    assert "no previous holder" in capsys.readouterr().out
    for name in ("总设计师", "总设计"):
        assert role_main(tmp_path, monkeypatch, name) == 0
        assert capsys.readouterr().out == f"{FIRST}\n"
    assert role_main(tmp_path, monkeypatch) == 0
    assert capsys.readouterr().out.startswith(f"总设计师\tclaude\t{FIRST}\t")


def test_second_take_replaces_the_holder_and_keeps_the_first_as_previous(tmp_path, monkeypatch, capsys):
    as_session(monkeypatch, FIRST)
    assert role_main(tmp_path, monkeypatch, "take", "总设计师") == 0
    as_session(monkeypatch, SECOND)
    assert role_main(tmp_path, monkeypatch, "take", "总设计") == 0
    assert f"previous holder: claude session {FIRST}" in capsys.readouterr().out
    from dkitchen import roles
    records = [json.loads(line) for line in roles.registry("o/r").read_text().splitlines()]
    assert [record["id"] for record in records] == [FIRST, SECOND]
    assert records[1]["previous"]["id"] == FIRST and records[1]["role"] == "总设计师"
    assert role_main(tmp_path, monkeypatch, "总设计") == 0
    assert capsys.readouterr().out == f"{SECOND}\n"


@pytest.mark.parametrize("session, name", [(None, "总设计师"), (FIRST, "nobody-here"), (FIRST, "Executor"), (FIRST, "User")])
def test_role_take_refuses_without_a_session_or_an_unknown_name(tmp_path, monkeypatch, capsys, session, name):
    as_session(monkeypatch, session)
    assert role_main(tmp_path, monkeypatch, "take", name) == 1
    from dkitchen import roles
    assert not roles.registry("o/r").exists()
    if session:
        assert "choose one of: Orchestrator, 总设计师, Verifier" in capsys.readouterr().err


@pytest.mark.parametrize("name", ["Executor", "User"])
def test_role_lookup_refuses_the_executor_and_the_user(tmp_path, monkeypatch, capsys, name):
    assert role_main(tmp_path, monkeypatch, name) == 1
    assert "is not a role here" in capsys.readouterr().err


def test_role_nobody_has_taken_exits_nonzero(tmp_path, monkeypatch, capsys):
    assert role_main(tmp_path, monkeypatch, "Verifier") == 1
    assert "nobody has taken Verifier" in capsys.readouterr().err


def test_two_repositories_keep_separate_registries(tmp_path, monkeypatch, capsys):
    as_session(monkeypatch, FIRST)
    def run(repo, *words):
        loaded = config.Config(root=tmp_path, repo=repo)
        monkeypatch.setattr(config, "load", lambda *args: loaded)
        return ding.main(["role", *words])
    assert run("o/one", "take", "Verifier") == 0
    assert run("o/two", "Verifier") == 1
    assert run("o/one", "Verifier") == 0


def role_watch(tmp_path, monkeypatch, collect=lambda *args, **kwargs: [(watch.now(), "matching comment", True)]):
    loaded = settings(tmp_path, ROLE_CONFIG)
    monkeypatch.setattr(watch, "collect", collect)
    monkeypatch.setattr(watch, "pr_wakes", lambda *args: ([], {}))
    monkeypatch.setattr(watch.time, "sleep", lambda seconds: None)
    args = SimpleNamespace(state=None, checkout=None, since=None, skip_issue=[], role="总设计",
                           interval=90, settle=0, stale_hours=6, stale_every=3600, max_errors=2, stalled_hours=48)
    return watch.watch(args, loaded)


def take_role(tmp_path, monkeypatch, session):
    as_session(monkeypatch, session)
    assert role_main(tmp_path, monkeypatch, "take", "总设计师") == 0


def test_watch_from_a_non_holder_refuses_to_start(tmp_path, monkeypatch, capsys):
    take_role(tmp_path, monkeypatch, FIRST)
    as_session(monkeypatch, SECOND)
    assert role_watch(tmp_path, monkeypatch, collect=lambda *args, **kwargs: pytest.fail("polled")) == 3
    assert f"role 总设计师 is held by {FIRST} since" in capsys.readouterr().err
    assert not watch.default_state("o/r", "总设计").exists()


def test_watch_from_the_holder_runs_and_exits_once_another_session_takes_the_role(tmp_path, monkeypatch, capsys):
    take_role(tmp_path, monkeypatch, FIRST)
    assert role_watch(tmp_path, monkeypatch) == 0
    assert "matching comment" in capsys.readouterr().out
    polls = []
    def collect(*args, **kwargs):
        if not polls:
            as_session(monkeypatch, SECOND)
            take_role(tmp_path, monkeypatch, SECOND)
            as_session(monkeypatch, FIRST)
        polls.append(1)
        return []
    assert role_watch(tmp_path, monkeypatch, collect=collect) == 3
    assert f"role 总设计师 is held by {SECOND} since" in capsys.readouterr().out
    assert len(polls) == 1


@pytest.mark.parametrize("session", [None, FIRST])
def test_watch_without_a_holder_or_session_runs_and_warns_once(tmp_path, monkeypatch, capsys, session):
    as_session(monkeypatch, session)
    calls = []
    def collect(*args, **kwargs):
        calls.append(1)
        return [(watch.now(), "matching comment", True)] if len(calls) > 3 else []
    assert role_watch(tmp_path, monkeypatch, collect=collect) == 0
    err = capsys.readouterr().err
    assert err.count("nobody has taken 总设计师" if session else "no Claude Code or Codex session id") == 1


ROLES_TOML = '[{}]\ndesigner = "总设计师"\nverifier = "核查"\nseparator = "："\n[{}.aliases]\n"总设计师" = ["总设计"]\n'


def test_a_stations_section_reads_as_roles_and_warns_once_per_command(tmp_path, monkeypatch, capsys):
    import subprocess
    current, old = tmp_path / "current", tmp_path / "old"
    for root, section in ((current, "roles"), (old, "stations")):
        root.mkdir()
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        (root / config.FILE).write_text('repo = "o/r"\n' + ROLES_TOML.format(section, section), encoding="utf-8")
    assert config.load(old).roles == config.load(current).roles
    assert capsys.readouterr().err.count("[stations] is now [roles]") == 1
    monkeypatch.chdir(old)
    monkeypatch.setattr(config, "RENAME_WARNED", set())
    monkeypatch.setenv("CLAUDE_CODE_HOST_SESSION_ID", "local_1")
    assert ding.main(["role", "take", "总设计"]) == 0
    assert ding.main(["role", "总设计师"]) == 0
    captured = capsys.readouterr()
    assert captured.out.endswith("local_1\n")
    assert captured.err == ".dkitchen.toml: [stations] is now [roles]; rename the section\n"


def test_stations_and_roles_together_are_refused(tmp_path):
    (tmp_path / config.FILE).write_text(ROLES_TOML.format("roles", "roles") + '[stations]\nuser = "用户"\n',
                                        encoding="utf-8")
    with pytest.raises(ValueError, match=r"\[stations\] and \[roles\]"):
        config.load(tmp_path)


def fake_process(tmp_path, monkeypatch, pid, start, *, session=FIRST, record_start=None, socket=True):
    """A Claude Code process record for `session`, and a /proc entry for `pid` started at `start` (None: not running)."""
    from dkitchen import roles
    proc = tmp_path / "proc"
    monkeypatch.setattr(roles, "PROC", proc)
    if start is not None:
        (proc / str(pid)).mkdir(parents=True)
        (proc / str(pid) / "stat").write_text(f"{pid} (claude code) S " + " ".join(["0"] * 18 + [start] + ["0"] * 5))
    sessions = Path(os.environ["CLAUDE_CONFIG_DIR"]) / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    path = tmp_path / f"{pid}.sock"
    if socket:
        path.touch()
    (sessions / f"{pid}.json").write_text(json.dumps({
        "pid": pid, "procStart": record_start or start or "1", "hostSessionId": session,
        "messagingSocketPath": str(path)}))
    return f"uds:{path}"


def test_role_to_prints_the_socket_of_the_one_live_process(tmp_path, monkeypatch, capsys):
    take_role(tmp_path, monkeypatch, FIRST)
    fake_process(tmp_path, monkeypatch, 11, None)
    fake_process(tmp_path, monkeypatch, 12, "500", record_start="400")
    live = fake_process(tmp_path, monkeypatch, 13, "600")
    fake_process(tmp_path, monkeypatch, 14, "700", session=SECOND)
    capsys.readouterr()
    assert role_main(tmp_path, monkeypatch, "总设计", "--to") == 0
    assert capsys.readouterr().out == f"{live}\n"
    assert role_main(tmp_path, monkeypatch, "总设计") == 0
    assert capsys.readouterr().out == f"{FIRST}\n"


@pytest.mark.parametrize("live", [0, 2])
def test_role_to_refuses_without_exactly_one_live_process(tmp_path, monkeypatch, capsys, live):
    take_role(tmp_path, monkeypatch, FIRST)
    fake_process(tmp_path, monkeypatch, 20, None)
    addresses = [fake_process(tmp_path, monkeypatch, 21 + index, str(900 + index)) for index in range(live)]
    capsys.readouterr()
    assert role_main(tmp_path, monkeypatch, "总设计师", "--to") == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    if live:
        assert "2 live Claude Code processes" in captured.err and all(item in captured.err for item in addresses)
    else:
        assert f"总设计师 is held by {FIRST}, but no live Claude Code process has it on this host" in captured.err


def test_role_to_refuses_a_live_process_without_its_socket(tmp_path, monkeypatch, capsys):
    take_role(tmp_path, monkeypatch, FIRST)
    fake_process(tmp_path, monkeypatch, 30, "100", socket=False)
    assert role_main(tmp_path, monkeypatch, "总设计", "--to") == 1
    assert "has no socket" in capsys.readouterr().err


def test_role_to_prints_a_codex_holders_thread_id(tmp_path, monkeypatch, capsys):
    thread = "019a0000-0000-7000-8000-000000000001"
    as_session(monkeypatch, None)
    monkeypatch.setenv("CODEX_THREAD_ID", thread)
    assert role_main(tmp_path, monkeypatch, "take", "总设计") == 0
    capsys.readouterr()
    assert role_main(tmp_path, monkeypatch, "总设计", "--to") == 0
    assert capsys.readouterr().out == f"{thread}\n"


def test_role_to_without_a_holder_exits_nonzero(tmp_path, monkeypatch, capsys):
    assert role_main(tmp_path, monkeypatch, "Verifier", "--to") == 1
    assert "nobody has taken Verifier" in capsys.readouterr().err


# A kitchen in its own repo, apart from the code repo

def run_git(root, *args):
    import subprocess
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args], cwd=root,
                          check=True, capture_output=True, text=True).stdout.strip()


def checkout(path, remote):
    path.mkdir(parents=True)
    run_git(path, "init", "-q", "-b", "main")
    run_git(path, "remote", "add", "origin", remote)
    return path.resolve()


def split_pair(tmp_path, kitchen_text='repo = "me/kitchen"\ncode = "org/code"\n'):
    kitchen = checkout(tmp_path / "kitchen", "git@github.com:me/kitchen.git")
    (kitchen / config.FILE).write_text(kitchen_text, encoding="utf-8")
    code = checkout(tmp_path / "code", "https://github.com/org/code.git")
    (code / "README.md").write_text("code\n", encoding="utf-8")
    run_git(code, "add", "README.md")
    run_git(code, "commit", "-q", "-m", "first")
    return kitchen, code


def test_split_kitchen_names_both_repos(tmp_path):
    loaded = settings(tmp_path, 'repo = "me/kitchen"\ncode = "org/code"\nshared = true\n')
    assert loaded.split and loaded.shared
    assert (loaded.kitchen_repo(), loaded.code_repo(), loaded.repository()) == ("me/kitchen", "org/code", "me/kitchen")


def test_single_repo_kitchen_uses_one_repo_for_both(tmp_path):
    loaded = settings(tmp_path, 'repo = "o/r"\n')
    assert not loaded.split and not loaded.shared
    assert loaded.code_repo() == loaded.kitchen_repo() == "o/r"
    assert not settings(tmp_path, 'repo = "o/r"\ncode = "o/r"\n').split


@pytest.mark.parametrize("url", ["git@github.com:org/code.git", "https://github.com/org/code", "https://github.com/org/code.git/",
                                 "ssh://git@github.com/org/code.git", "work-alias:org/code.git"])
def test_remote_urls_name_their_repo(url):
    from dkitchen import kitchens
    assert kitchens.repo_of_remote(url) == "org/code"


def test_link_lets_a_code_worktree_find_its_kitchen(tmp_path, monkeypatch, capsys):
    kitchen, code = split_pair(tmp_path)
    run_git(code, "worktree", "add", "-q", str(tmp_path / "wt"), "-b", "issue12")
    monkeypatch.chdir(kitchen)
    assert ding.main(["kitchen", "link", str(tmp_path / "wt")]) == 0
    assert "linked org/code" in capsys.readouterr().out
    for where in (code, tmp_path / "wt", code / "README.md"):
        loaded = config.load(where if where.is_dir() else where.parent)
        assert (loaded.root, loaded.code_root, loaded.code_repo()) == (kitchen, code, "org/code")
    assert config.load(kitchen).code_root == code
    monkeypatch.chdir(tmp_path / "wt")
    assert ding.main(["kitchen"]) == 0
    shown = capsys.readouterr().out
    assert f"kitchen: {kitchen}" in shown and "code repo: org/code" in shown and "found: through" in shown


def test_link_refuses_a_checkout_of_another_repo(tmp_path, monkeypatch, capsys):
    kitchen, _ = split_pair(tmp_path)
    other = checkout(tmp_path / "other", "git@github.com:org/other.git")
    monkeypatch.chdir(kitchen)
    assert ding.main(["kitchen", "link", str(other)]) == 1
    assert "is a checkout of org/other, not org/code" in capsys.readouterr().err


def test_link_needs_a_split_kitchen(tmp_path, monkeypatch, capsys):
    kitchen, code = split_pair(tmp_path, 'repo = "me/kitchen"\n')
    monkeypatch.chdir(kitchen)
    assert ding.main(["kitchen", "link", str(code)]) == 1
    assert "names no separate code repo" in capsys.readouterr().err
    monkeypatch.chdir(code)
    assert ding.main(["kitchen", "link", str(code)]) == 1
    assert "run `ding kitchen link` in the kitchen repo's checkout" in capsys.readouterr().err


def test_registry_overrides_a_code_repos_own_kitchen_file(tmp_path, monkeypatch, capsys):
    from dkitchen import kitchens
    kitchen, code = split_pair(tmp_path)
    (code / config.FILE).write_text('repo = "org/code"\n', encoding="utf-8")
    kitchens.write({"org/code": kitchens.Entry(kitchen=kitchen, code=code)})
    assert config.load(code).root == kitchen
    assert "is ignored: org/code is linked to the kitchen" in capsys.readouterr().err


def test_registry_entry_must_match_the_kitchens_code_repo(tmp_path):
    from dkitchen import kitchens
    kitchen, code = split_pair(tmp_path, 'repo = "me/kitchen"\ncode = "org/elsewhere"\n')
    kitchens.write({"org/code": kitchens.Entry(kitchen=kitchen, code=code)})
    with pytest.raises(ValueError, match="sets code = 'org/elsewhere'"):
        config.load(code)


def test_ticket_lookups_use_the_kitchen_repo_without_asking_gh(tmp_path, monkeypatch):
    from dkitchen import kitchens
    kitchen, code = split_pair(tmp_path)
    kitchens.write({"org/code": kitchens.Entry(kitchen=kitchen, code=code)})
    monkeypatch.setattr(ding, "gh_json", lambda *_: pytest.fail("must not ask gh"))
    monkeypatch.chdir(code)
    assert ding.github_repository() == "me/kitchen"


# Writing into the code repo: PR routes, verdicts, and outbound text

SHARED = 'repo = "me/kitchen"\ncode = "org/code"\nshared = true\n'
TICKET_WITH_PR = json.dumps([[{"body": "Status: in progress\n\nPR: org/code#7\n\nCodex session: t"},
                              {"body": "Code issue: org/code#5\nmore"}]])


def gh_router(monkeypatch, routes, calls):
    """Fake `call` everywhere: the first route whose words all appear in the command answers it."""
    from dkitchen import outbound, verdict

    def call(settings, *args):
        calls.append(args)
        joined = " ".join(args)
        for words, answer in routes:
            if all(word in joined for word in words):
                code, stdout = answer if isinstance(answer, tuple) else (0, answer)
                return SimpleNamespace(returncode=code, stdout=stdout, stderr="boom" if code else "")
        pytest.fail(f"unexpected call: {args}")
    for module in (orchestrate, verdict, outbound, night):
        monkeypatch.setattr(module, "call", call)


def test_merge_by_defaults_to_the_team_in_a_shared_code_repo(tmp_path, capsys):
    loaded = settings(tmp_path, SHARED)
    assert loaded.merger == "team"
    assert orchestrate.merge(SimpleNamespace(pr=7, sha="abc"), loaded) == 1
    assert "the team merges PRs in org/code" in capsys.readouterr().err
    assert settings(tmp_path, 'repo = "o/r"\n').merger == "orchestrator"
    assert settings(tmp_path, SHARED + '[merge]\nby = "orchestrator"\n').merger == "orchestrator"
    with pytest.raises(ValueError, match="by must be one of"):
        settings(tmp_path, '[merge]\nby = "anyone"\n')


def test_merge_reads_the_pr_from_the_code_repo(tmp_path, monkeypatch):
    loaded = settings(tmp_path, 'repo = "me/kitchen"\ncode = "org/code"\n')
    calls = []
    gh_router(monkeypatch, [(("pr", "view"), (1, ""))], calls)
    assert orchestrate.merge(SimpleNamespace(pr=7, sha="abc"), loaded) == 1
    assert calls[0][:6] == ("gh", "pr", "view", "7", "--repo", "org/code")


def shared_review(tmp_path, monkeypatch, comments=TICKET_WITH_PR):
    loaded = settings(tmp_path, SHARED)
    draft = tmp_path / "review.md"
    draft.write_text("Verifier: the change holds\n\ndetails\n", encoding="utf-8")
    calls, sent = [], []
    gh_router(monkeypatch, [
        (("pr", "view", "org/code"), json.dumps({"headRefOid": "abcdef1234567"})),
        (("--paginate", "me/kitchen/issues/42/comments"), comments),
        (("repos/me/kitchen/issues/42",), json.dumps({"body": "Goal"})),
        (("issue", "comment", "42", "me/kitchen"), "https://github.com/me/kitchen/issues/42#issuecomment-1"),
    ], calls)
    monkeypatch.setattr(rule, "deliver", lambda *args, **kw: sent.append(args) or 0)
    args = SimpleNamespace(pr=7, sha="abcdef", verdict="pass", ticket=42, body_file=draft)
    return loaded, args, calls, sent


def test_shared_pr_verdict_goes_on_the_ticket(tmp_path, monkeypatch):
    loaded, args, calls, sent = shared_review(tmp_path, monkeypatch)
    assert orchestrate.review(args, loaded) == 0
    body = next(call[-1] for call in calls if call[:3] == ("gh", "issue", "comment"))
    assert body.startswith("Verifier: the change holds\nVerdict: pass\nReviewed abcdef12: pass (org/code#7)\n")
    assert not any("statuses" in " ".join(call) for call in calls)
    assert sent and sent[0][0] == "#42"


def test_shared_pr_verdict_needs_the_tickets_pr_line(tmp_path, monkeypatch, capsys):
    loaded, args, calls, _ = shared_review(tmp_path, monkeypatch, comments=json.dumps([[{"body": "nothing"}]]))
    assert orchestrate.review(args, loaded) == 1
    assert "has no PR line for org/code#7" in capsys.readouterr().err
    assert not any(call[:3] == ("gh", "issue", "comment") for call in calls)


def test_pr_verdict_ticket_flag_follows_whether_the_repo_is_shared(tmp_path, capsys):
    shared = settings(tmp_path, SHARED)
    assert orchestrate.review(SimpleNamespace(pr=7, sha="a", verdict="pass", ticket=None, body_file=None), shared) == 1
    assert "add --ticket N" in capsys.readouterr().err
    own = settings(tmp_path, 'repo = "o/r"\n[merge]\nreview_check = "review"\n')
    assert orchestrate.review(SimpleNamespace(pr=7, sha="a", verdict="pass", ticket=42, body_file=None), own) == 1
    assert "drop --ticket" in capsys.readouterr().err


@pytest.mark.parametrize(("text", "found"), [
    ("Fix the loader\n\nDesigner: please look", "opens with the Designer signature"),
    ("Fix\n\nCodex session: 019a", "kitchen marker 'Codex session:'"),
    ("Fix\nStatus: done\nWaiting on: none\n", "are a status block"),
    ("Fix, see https://github.com/me/kitchen/issues/3", "names the kitchen repo me/kitchen"),
    ("Fixes #12", "bare #12"),
])
def test_outbound_text_with_kitchen_internals_is_refused(tmp_path, text, found):
    from dkitchen import outbound
    problems = outbound.leaks(settings(tmp_path, SHARED), text, {5})
    assert any(found in problem for problem in problems), problems


def test_outbound_text_without_kitchen_internals_passes(tmp_path):
    from dkitchen import outbound
    text = "Fix the loader\n\nStatus: green in CI\nFixes #5, see org/code#12 and https://github.com/org/code/pull/3\n"
    assert outbound.leaks(settings(tmp_path, SHARED), text, {5}) == []
    assert outbound.leaks(settings(tmp_path, 'repo = "o/r"\n'), "Designer: #12", set()) == []


def open_pr(tmp_path, monkeypatch, text=SHARED, *extra, body="Fix the loader.\n", routes=()):
    from dkitchen import inbox, outbound
    (tmp_path / config.FILE).write_text(text, encoding="utf-8")
    loaded = config.read(tmp_path / config.FILE, tmp_path)  # config.load may be patched by an earlier call
    (tmp_path / "body.md").write_text(body, encoding="utf-8")
    calls = []
    gh_router(monkeypatch, [
        *routes,
        (("--paginate", "me/kitchen/issues/42/comments"), TICKET_WITH_PR),
        (("repos/me/kitchen/issues/42",), json.dumps({"body": "Goal"})),
        (("pr", "create"), "https://github.com/org/code/pull/45\n"),
        (("pr", "ready"), ""),
        (("issue", "create"), "https://github.com/org/code/issues/6\n"),
        (("issue", "comment", "42", "me/kitchen"), "https://github.com/me/kitchen/issues/42#issuecomment-2"),
    ], calls)
    monkeypatch.setattr(outbound, "pushed_branch", lambda: "fix-loader")
    monkeypatch.setattr(inbox, "current_session", lambda environ=None: ("codex", "019a-thread"))
    monkeypatch.setattr(config, "load", lambda cwd=None: loaded)
    code = ding.main(["pr", "42", "--title", "Fix the loader", "--body-file", str(tmp_path / "body.md"), *extra])
    return code, calls


def test_pr_opens_a_draft_and_records_it_on_the_ticket(tmp_path, monkeypatch, capsys):
    code, calls = open_pr(tmp_path, monkeypatch, SHARED, "--draft")
    assert code == 0
    create = next(call for call in calls if call[:3] == ("gh", "pr", "create"))
    assert ("--repo", "org/code") == create[3:5] and "--draft" in create and "fix-loader" in create
    comment = next(call for call in calls if call[:3] == ("gh", "issue", "comment"))[-1]
    assert comment.startswith("Status: in progress\n") and "\n\nPR: org/code#45\n\nCodex session: 019a-thread\n" in comment
    assert capsys.readouterr().out.strip() == "https://github.com/org/code/pull/45"


def test_shared_pr_ready_for_review_needs_approval(tmp_path, monkeypatch, capsys):
    code, calls = open_pr(tmp_path, monkeypatch, SHARED)
    assert code == 1 and "needs the user's approval" in capsys.readouterr().err
    assert not any(call[:3] == ("gh", "pr", "create") for call in calls)


def test_user_decision_on_the_ticket_approves_a_ready_pr(tmp_path, monkeypatch):
    approval = "https://github.com/me/kitchen/issues/42#issuecomment-99"
    decision = (("issues/comments/99",), json.dumps({"body": "Orchestrator: user decision\nOpen it for review."}))
    code, calls = open_pr(tmp_path, monkeypatch, SHARED, "--approval", approval, routes=[decision])
    assert code == 0
    assert "--draft" not in next(call for call in calls if call[:3] == ("gh", "pr", "create"))


@pytest.mark.parametrize(("url", "body", "found"), [
    ("https://github.com/me/kitchen/issues/41#issuecomment-99", "Orchestrator: user decision", "not a user decision on #42"),
    ("https://github.com/me/kitchen/issues/42#issuecomment-99", "Designer: I think so", "not a user decision on #42"),
    ("https://github.com/org/code/issues/42#issuecomment-99", "Orchestrator: user decision", "in the kitchen repo"),
    ("https://example.com/x", "", "must link an issue comment"),
])
def test_approval_must_be_a_user_decision_on_the_ticket(tmp_path, monkeypatch, capsys, url, body, found):
    route = (("issues/comments/99",), json.dumps({"body": body}))
    code, calls = open_pr(tmp_path, monkeypatch, SHARED, "--approval", url, routes=[route])
    assert code == 1 and found in capsys.readouterr().err
    assert not any(call[:3] == ("gh", "pr", "create") for call in calls)


def test_pr_with_kitchen_internals_posts_nothing(tmp_path, monkeypatch, capsys):
    code, calls = open_pr(tmp_path, monkeypatch, SHARED, "--draft", body="Designer: done\nSee #42\n")
    err = capsys.readouterr().err
    assert code == 1 and "carries kitchen internals" in err and "bare #42" in err
    assert not any(call[:3] in {("gh", "pr", "create"), ("gh", "issue", "comment")} for call in calls)


def test_pr_ready_marks_only_the_tickets_own_pr(tmp_path, monkeypatch, capsys):
    from dkitchen import outbound
    loaded = settings(tmp_path, 'repo = "me/kitchen"\ncode = "org/code"\n')
    calls = []
    gh_router(monkeypatch, [(("--paginate",), TICKET_WITH_PR), (("repos/me/kitchen/issues/42",), json.dumps({"body": ""})),
                            (("pr", "ready", "7"), "")], calls)
    args = SimpleNamespace(ticket=42, ready=7, approval=None, sender="Orchestrator")
    assert outbound.pr(args, loaded) == 0
    assert ("gh", "pr", "ready", "7", "--repo", "org/code") in calls
    assert outbound.pr(SimpleNamespace(ticket=42, ready=8, approval=None, sender="Orchestrator"), loaded) == 1
    assert "no PR line for org/code#8" in capsys.readouterr().err


def test_code_issue_needs_approval_when_shared_and_is_signed_by_its_role(tmp_path, monkeypatch, capsys):
    from dkitchen import outbound
    loaded = settings(tmp_path, SHARED)
    (tmp_path / "issue.md").write_text("The loader drops rows.\n", encoding="utf-8")
    calls = []
    gh_router(monkeypatch, [
        (("issues/comments/99",), json.dumps({"body": "Designer: user decision\nFile it."})),
        (("--paginate",), TICKET_WITH_PR), (("repos/me/kitchen/issues/42",), json.dumps({"body": ""})),
        (("issue", "create", "org/code"), "https://github.com/org/code/issues/6\n"),
        (("issue", "comment", "42"), "https://github.com/me/kitchen/issues/42#issuecomment-3"),
    ], calls)
    args = SimpleNamespace(ticket=42, title="Loader drops rows", body_file=tmp_path / "issue.md", approval=None,
                           sender="Designer")
    assert outbound.code_issue(args, loaded) == 1
    assert "needs the user's approval" in capsys.readouterr().err
    args.approval = "https://github.com/me/kitchen/issues/42#issuecomment-99"
    assert outbound.code_issue(args, loaded) == 0
    comment = next(call for call in calls if call[:3] == ("gh", "issue", "comment"))[-1]
    assert comment == ("Designer: https://github.com/org/code/issues/6\nCode issue: org/code#6\n"
                       "Approval: https://github.com/me/kitchen/issues/42#issuecomment-99\n")


def test_a_user_decision_approves_one_code_issue(tmp_path, monkeypatch, capsys):
    from dkitchen import outbound
    loaded = settings(tmp_path, SHARED)
    (tmp_path / "issue.md").write_text("The loader drops rows.\n", encoding="utf-8")
    approval = "https://github.com/me/kitchen/issues/42#issuecomment-99"
    spent = json.dumps([[{"body": f"Designer: https://github.com/org/code/issues/6\nCode issue: org/code#6\n"
                                  f"Approval: {approval}\n"}]])
    calls = []
    gh_router(monkeypatch, [
        (("issues/comments/99",), json.dumps({"body": "Designer: user decision\nFile it."})),
        (("--paginate",), spent), (("repos/me/kitchen/issues/42",), json.dumps({"body": ""})),
    ], calls)
    args = SimpleNamespace(ticket=42, title="Loader drops rows", body_file=tmp_path / "issue.md", approval=approval,
                           sender="Designer")
    assert outbound.code_issue(args, loaded) == 1
    assert "already approved a code issue" in capsys.readouterr().err
    assert not any(call[:3] == ("gh", "issue", "create") for call in calls)


def test_pr_cli_takes_one_shape(tmp_path, capsys):
    with pytest.raises(SystemExit):
        ding.main(["pr", "42", "--title", "x"])
    with pytest.raises(SystemExit):
        ding.main(["pr", "42", "--ready", "7", "--title", "x", "--body-file", str(tmp_path / "b.md")])
    assert "pr takes" in capsys.readouterr().err


# Watching a kitchen kept in its own repo

SPLIT = 'repo = "me/kitchen"\ncode = "org/code"\n'
SINCE = "2026-11-16T08:00:00Z"


def fake_watch_github(monkeypatch, routes):
    """Fake watch.gh: the first route whose fragments all appear in the path answers it; unknown paths are empty."""
    asked = []

    def gh(path):
        asked.append(path)
        for fragments, answer in routes:
            if all(fragment in path for fragment in fragments):
                return answer
        return []
    monkeypatch.setattr(watch, "gh", gh)
    monkeypatch.setattr(watch, "VIEWER", ["me"])
    return asked


def code_comment(number, body, *, login="me", created=SINCE, repo="me/kitchen", pull=False):
    target = {"pull_request_url": f"https://api.github.com/repos/{repo}/pulls/{number}"} if pull else {
        "issue_url": f"https://api.github.com/repos/{repo}/issues/{number}"}
    return {**target, "body": body, "user": {"login": login}, "created_at": created, "updated_at": created,
            "html_url": f"https://github.com/{repo}/issues/{number}#issuecomment-1", "id": 1}


def test_a_pr_line_on_a_ticket_tells_the_orchestrator_a_pr_opened(tmp_path, monkeypatch):
    loaded = settings(tmp_path, SPLIT)
    pr_line = code_comment(42, "Status: in progress\nWaiting on: none\n\nPR: org/code#45\n\nCodex session: t")
    fake_watch_github(monkeypatch, [(("me/kitchen/issues/comments",), [pr_line])])
    lines = [line for _, line, wakes in watch.collect(loaded, "me/kitchen", SINCE, SINCE, set(), set()) if wakes]
    assert lines == ["PR org/code#45 opened, recorded on #42 https://github.com/me/kitchen/issues/42#issuecomment-1"]


def test_outside_comments_on_the_kitchens_own_code_repo_work_wake_the_orchestrator(tmp_path, monkeypatch):
    loaded = settings(tmp_path, SPLIT)
    fake_watch_github(monkeypatch, [
        (("org/code/issues/comments",), [code_comment(45, "Please split this.", login="alice", repo="org/code"),
                                         code_comment(45, "Done.", repo="org/code"),
                                         code_comment(46, "Not ours.", login="alice", repo="org/code")]),
        (("org/code/pulls/comments",), [code_comment(45, "nit: name", login="bob", repo="org/code", pull=True)]),
        (("org/code/issues/45",), {"user": {"login": "me"}}),
        (("org/code/issues/46",), {"user": {"login": "carol"}}),
    ])
    lines = [line for _, line, wakes in watch.collect(loaded, "me/kitchen", SINCE, SINCE, set(), set()) if wakes]
    assert [line.split(":")[0] for line in lines] == ["org/code#45 code repo comment by @alice",
                                                       "org/code#45 code repo comment by @bob"]
    assert not any("User" in line for line in lines)


def test_a_single_repo_kitchen_does_not_read_a_code_repo(tmp_path, monkeypatch):
    asked = fake_watch_github(monkeypatch, [])
    watch.collect(settings(tmp_path, 'repo = "o/r"\n'), "o/r", SINCE, SINCE, set(), set())
    assert not any("pulls/comments" in path for path in asked)


def test_waits_name_code_repo_prs_and_finish_with_the_tickets_own(tmp_path, monkeypatch):
    loaded = settings(tmp_path, SPLIT)
    assert watch.named_prs("Verifier, PR org/code#45 and PR other/x#3", "org/code") == {45}
    fake_watch_github(monkeypatch, [
        (("org/code/pulls/45",), {"state": "closed", "merged_at": "x", "labels": []}),
        (("org/code/pulls/46",), {"state": "closed", "merged_at": "x", "labels": []}),
        (("me/kitchen/issues/42/comments",), [{"body": "PR: org/code#45"}]),
        (("me/kitchen/issues/42",), {"number": 42, "body": "Goal", "comments": 1}),
    ])
    roles, note = watch.finished_prs("Verifier (PR org/code#45)", 42, loaded, "me/kitchen", {})
    assert loaded.roles.verifier in roles and note == ""
    roles, note = watch.finished_prs("Verifier (PR org/code#46)", 42, loaded, "me/kitchen", {})
    assert roles == set() and note == "PR #46 merged"


def test_a_shared_code_repo_has_no_pr_readiness_waits(tmp_path):
    loaded = settings(tmp_path, SHARED + '[merge]\nreview_check = "review"\n')
    assert watch.pr_waits(loaded, "org/code", set()) == []


def test_stalled_drafts_in_a_split_kitchen_are_its_own_code_repo_drafts(tmp_path, monkeypatch):
    loaded = settings(tmp_path, SPLIT)
    old = "2026-01-01T00:00:00Z"
    draft = lambda number, login: {"number": number, "draft": True, "updated_at": old, "title": "t", "user": {"login": login},
                                   "html_url": f"https://github.com/org/code/pull/{number}"}
    asked = fake_watch_github(monkeypatch, [(("org/code/pulls?state=open",), [draft(1, "me"), draft(2, "alice")])])
    found = watch.stalled(loaded, "me/kitchen", tmp_path, 48, {1})
    assert [item["ref"] for item in found] == ["org/code#1"]
    assert watch.stalled_line(found[0]).startswith("PR org/code#1 stalled")
    assert not any("me/kitchen/pulls" in path for path in asked)


def test_board_covers_both_checkouts_of_a_split_kitchen(tmp_path, monkeypatch):
    from dkitchen import kitchens
    kitchen, code = split_pair(tmp_path)
    run_git(code, "worktree", "add", "-q", str(tmp_path / "wt"), "-b", "issue12")
    kitchens.write({"org/code": kitchens.Entry(kitchen=kitchen, code=code)})
    for where in (kitchen, tmp_path / "wt"):
        monkeypatch.chdir(where)
        assert set(ding.repository_roots()) == {kitchen, code, (tmp_path / "wt").resolve()}


# Dispatch and checks in a kitchen kept in its own repo

def linked_pair(tmp_path, kitchen_text=SPLIT):
    from dkitchen import kitchens
    kitchen, code = split_pair(tmp_path, kitchen_text)
    run_git(code, "worktree", "add", "-q", str(tmp_path / "wt"), "-b", "issue12")
    kitchens.write({"org/code": kitchens.Entry(kitchen=kitchen, code=code)})
    return kitchen, code, (tmp_path / "wt").resolve()


def recorded_server(monkeypatch, requests):
    from contextlib import contextmanager
    thread = "00000000-0000-4000-8000-0000000000ab"

    def call(method, params):
        requests.append((method, params))
        return {"thread/start": {"thread": {"id": thread}}, "thread/name/set": {},
                "turn/start": {"turn": {"id": "turn-1", "status": "inProgress"}}}[method]

    @contextmanager
    def server(path):
        yield call
    monkeypatch.setattr(ding, "app_server", server)


def test_new_gives_a_codex_executor_its_kitchen_in_developer_instructions(tmp_path, monkeypatch, capsys):
    kitchen, _, worktree = linked_pair(tmp_path)
    requests = []
    recorded_server(monkeypatch, requests)
    assert ding.main(["new", "--cwd", str(worktree), "--name", "Run", "--message", "Brief", "--socket", "/s"]) == 0
    start = requests[0][1]
    assert start["cwd"] == str(worktree)
    assert f"read {kitchen / 'AGENTS.md'} before anything else" in start["developerInstructions"]
    assert "Tickets are issues in me/kitchen" in start["developerInstructions"]
    assert requests[2][1]["input"][0]["text"] == "Brief"


def test_new_refuses_an_executor_outside_the_code_repo(tmp_path, monkeypatch, capsys):
    kitchen, _, _ = linked_pair(tmp_path)
    monkeypatch.setattr(ding, "app_server", lambda path: pytest.fail("must not connect"))
    assert ding.main(["new", "--cwd", str(kitchen), "--name", "Run", "--message", "Brief"]) == 1
    assert "is not a checkout of the code repo org/code" in capsys.readouterr().err


def test_new_prints_the_kitchen_pointer_for_a_claude_executor(tmp_path, capsys):
    kitchen, _, worktree = linked_pair(tmp_path)
    assert ding.main(["new", "--executor", "claude", "--cwd", str(worktree), "--message", "Brief"]) == 0
    captured = capsys.readouterr()
    assert captured.out.startswith("This session works for a dkitchen kitchen") and captured.out.endswith("\n\nBrief\n")
    assert "--add-dir" in captured.err


CHECKED = SPLIT + '[check]\nlibrary = ["src"]\nruff = false\nimports = false\n'


def test_check_runs_on_the_code_worktree_with_the_kitchens_rules(tmp_path, monkeypatch, capsys):
    from dkitchen import check
    kitchen, _, worktree = linked_pair(tmp_path, CHECKED)
    monkeypatch.chdir(worktree)
    (worktree / "src").mkdir()
    (worktree / "src/loader.py").write_text('"""Loads rows."""\n', encoding="utf-8")
    assert check.check(SimpleNamespace(base="HEAD", json=False), config.load(worktree)) == 0
    (worktree / "src/loader_issue12.py").write_text('"""Loads rows again."""\n', encoding="utf-8")
    assert check.check(SimpleNamespace(base="HEAD", json=False), config.load(worktree)) == 1
    assert f"rules in {kitchen / 'docs/agents/code.md'}" in capsys.readouterr().out
    assert check.module_map(SimpleNamespace(paths=[]), config.load(worktree)) == 0
    assert "src/loader.py: Loads rows." in capsys.readouterr().out


def test_check_refuses_to_run_outside_the_code_repo(tmp_path, capsys):
    from dkitchen import check
    kitchen, _, _ = linked_pair(tmp_path, CHECKED)
    assert check.check(SimpleNamespace(base="HEAD", json=False), config.load(kitchen)) == 2
    assert "is not a checkout of the code repo org/code" in capsys.readouterr().err


def test_check_refs_from_the_kitchen_read_the_code_repo(tmp_path, monkeypatch, capsys):
    kitchen, code, _ = linked_pair(tmp_path)
    monkeypatch.chdir(kitchen)
    assert refs.code_repository() == code
    assert refs.Source("main", None, code).read("README.md") == b"code\n"
    monkeypatch.chdir(code)
    assert refs.code_repository() is None


def test_check_refs_from_an_unlinked_kitchen_say_so(tmp_path, monkeypatch, capsys):
    kitchen, _ = split_pair(tmp_path)
    (tmp_path / "draft.md").write_text("Verifier: `README.md:1`\n", encoding="utf-8")
    monkeypatch.chdir(kitchen)
    assert ding.main(["check-refs", str(tmp_path / "draft.md"), "--offline"]) == 2
    assert "run `ding kitchen link`" in capsys.readouterr().err


def test_shared_pr_runs_the_checks_first(tmp_path, monkeypatch, capsys):
    from dkitchen import outbound
    ran = []
    monkeypatch.setattr(outbound, "checks_pass", lambda settings, base: ran.append(base) or False)
    code, calls = open_pr(tmp_path, monkeypatch, SHARED + '[check]\nlibrary = ["src"]\n', "--draft", "--base", "dev")
    assert code == 1 and ran == ["dev"] and "`ding check` did not pass" in capsys.readouterr().err
    assert not any(call[:3] == ("gh", "pr", "create") for call in calls)
    ran.clear()
    (tmp_path / "plain").mkdir()
    code, _ = open_pr(tmp_path / "plain", monkeypatch, SHARED, "--draft")
    assert code == 0 and ran == []


@pytest.fixture
def waiting_board(tmp_path, monkeypatch):
    """A kitchen repo o/r with tickets #28 and #30 open; #30's executor waits on #28."""
    loaded = config.Config(root=tmp_path, repo="o/r")
    state = SimpleNamespace(config=loaded, comments={28: [], 30: []}, open=[28, 30], recent=[], events=[], calls=[])

    def post(number, status, waiting="none"):
        item = {"id": 1000 + sum(map(len, state.comments.values())),
                "issue_url": f"https://api.github.com/repos/o/r/issues/{number}",
                "body": executor(f"Status: {status}\nWaiting on: {waiting}\nKey numbers: 1\nNext: go"),
                "created_at": "2026-10-14T09:00:00Z", "updated_at": "2026-10-14T09:00:00Z"}
        item["html_url"] = f"https://github.com/o/r/issues/{number}#issuecomment-{item['id']}"
        state.comments[number].append(item)
        state.recent.append(item)

    def close(number, reason="completed"):
        state.open.remove(number)
        state.events.append({"id": 77, "event": "closed", "state_reason": reason, "created_at": "2026-10-14T09:00:00Z",
                             "issue": {"number": number, "html_url": f"https://github.com/o/r/issues/{number}"}})

    def gh(path):
        state.calls.append(path)
        if "/issues/comments?since" in path:
            return state.recent if "page=1" in path else []
        if "/issues/events?" in path:
            return state.events if "page=1" in path else []
        if "/issues?state=open" in path:
            return [{"number": n, "comments": len(state.comments[n]), "labels": [], "updated_at": "2026-10-14T09:00:00Z"}
                    for n in state.open]
        if match := re.search(r"/issues/(\d+)/comments\?", path):
            return list(state.comments[int(match[1])])
        return []

    monkeypatch.setattr(watch, "gh", gh)
    state.post, state.close = post, close
    post(30, "in progress", "#28 for the schema")
    state.recent.clear()
    return state


SINCE = "2026-10-14T08:00:00Z"


def finished(waiting_board, reported=(), checked=None):
    return watch.finished_waits(waiting_board.config, "o/r", SINCE, set(reported),
                                set() if checked is None else checked, set())


def run_watch(waiting_board, state, monkeypatch, capsys):
    monkeypatch.setattr(config, "load", lambda: waiting_board.config)
    monkeypatch.setattr(watch.time, "sleep", lambda seconds: None)
    for name in ("stale", "unanswered_design", "unrouted_waits", "missing_waiters", "stalled"):
        monkeypatch.setattr(watch, name, lambda *args: [])
    monkeypatch.setattr(watch, "idle", lambda *args: ([], {}))
    assert ding.main(["watch", "--state", str(state), "--since", SINCE, "--interval", "0", "--settle", "0"]) == 0
    return capsys.readouterr().out


def test_a_done_status_on_the_awaited_ticket_wakes_with_one_event(waiting_board):
    waiting_board.post(28, "done")
    [(_, line, key)] = finished(waiting_board)
    assert line == ("#30 is waiting on #28, which just finished "
                    f"https://github.com/o/r/issues/28#issuecomment-{waiting_board.comments[28][0]['id']}")
    assert key == "30>28"


def test_closing_the_awaited_ticket_wakes_with_one_event(waiting_board):
    waiting_board.close(28)
    [(_, line, key)] = finished(waiting_board)
    assert line == "#30 is waiting on #28, which just finished https://github.com/o/r/issues/28" and key == "30>28"


def test_done_and_closed_together_are_one_event(waiting_board):
    waiting_board.post(28, "done")
    waiting_board.close(28)
    assert len(finished(waiting_board)) == 1


def test_a_reported_pair_does_not_fire_again(waiting_board):
    waiting_board.post(28, "done")
    assert finished(waiting_board, reported={"30>28"}) == []


def test_a_restarted_watch_does_not_repeat_a_saved_pair(waiting_board, tmp_path, monkeypatch, capsys):
    waiting_board.post(28, "done")
    state = tmp_path / "watch.json"
    out = run_watch(waiting_board, state, monkeypatch, capsys)
    assert out.count("#30 is waiting on #28, which just finished") == 1
    saved = json.loads(state.read_text())
    assert saved["wait_reported"] == ["30>28"]
    state.write_text(json.dumps({**saved, "since": SINCE, "seen": []}))
    assert "is waiting on" not in run_watch(waiting_board, state, monkeypatch, capsys)


def test_a_ticket_nobody_awaits_is_scanned_once(waiting_board):
    waiting_board.post(30, "done")
    checked = set()
    assert finished(waiting_board, checked=checked) == []
    waiting_board.calls.clear()
    assert finished(waiting_board, checked=checked) == []
    assert not any("/issues?state=open" in call for call in waiting_board.calls)


def test_a_waiter_whose_latest_status_no_longer_waits_gets_nothing(waiting_board):
    waiting_board.post(30, "in progress", "none")
    waiting_board.post(28, "done")
    assert finished(waiting_board) == []


def test_only_the_latest_executor_status_counts(waiting_board):
    waiting_board.post(30, "in progress", "none")
    waiting_board.comments[30].append({**waiting_board.comments[30][0], "id": 5, "body": "Designer: the ruling is #28"})
    waiting_board.post(28, "done")
    assert finished(waiting_board) == []


@pytest.mark.parametrize("waiting", ["the user", "PR #28", "o/code#28", "https://github.com/o/r/pull/28",
                                     "ticket 28", "none"])
def test_a_wait_that_names_no_ticket_gets_nothing(waiting_board, waiting):
    waiting_board.post(30, "in progress", waiting)
    waiting_board.post(28, "done")
    assert finished(waiting_board) == []


@pytest.mark.parametrize("waiting", ["等#28的结果", "#28的结果", "#28 的结果、GPU", "在等 #28", "等待（#28）完成"])
def test_a_ticket_next_to_cjk_text_is_found(waiting_board, waiting):
    waiting_board.post(30, "in progress", waiting)
    waiting_board.post(28, "done")
    assert [key for _, _, key in finished(waiting_board)] == ["30>28"]


@pytest.mark.parametrize("waiting", ["#280", "a#28", "等o/r#28的结果"])
def test_a_different_number_or_prefixed_ref_is_not_the_ticket(waiting_board, waiting):
    waiting_board.post(30, "in progress", waiting)
    waiting_board.post(28, "done")
    assert finished(waiting_board) == []


def test_a_localized_status_block_is_read_by_its_configured_names(waiting_board):
    waiting_board.config = settings(waiting_board.config.root, 'repo = "o/r"\n[status]\n'
                                    'fields = ["状态", "等待", "关键数字", "下一步"]\ndone = "完成"\nnone = "无"')

    def localized(number, state, waiting):
        waiting_board.post(number, "x")
        waiting_board.comments[number][-1]["body"] = executor(f"状态：{state}\n等待：{waiting}\n关键数字：1\n下一步：继续")

    localized(30, "进行中", "等#28的结果")
    localized(28, "完成", "无")
    assert [key for _, _, key in finished(waiting_board)] == ["30>28"]


def test_a_waiter_that_is_done_gets_nothing(waiting_board):
    waiting_board.post(30, "done", "#28")
    waiting_board.post(28, "done")
    assert finished(waiting_board) == []


def test_a_blocked_waiter_still_gets_the_event(waiting_board):
    waiting_board.post(30, "blocked", "#28")
    waiting_board.post(28, "done")
    assert [key for _, _, key in finished(waiting_board)] == ["30>28"]


@pytest.mark.parametrize("reason, wording", [("not_planned", "was closed as not planned"),
                                             ("duplicate", "was closed as a duplicate"),
                                             ("completed", "just finished")])
def test_the_close_reason_words_the_event(waiting_board, reason, wording):
    waiting_board.close(28, reason)
    [(_, line, _)] = finished(waiting_board)
    assert line == f"#30 is waiting on #28, which {wording} https://github.com/o/r/issues/28"


def test_a_done_status_wins_over_a_not_planned_close(waiting_board):
    waiting_board.post(28, "done")
    waiting_board.close(28, "not_planned")
    [(_, line, _)] = finished(waiting_board)
    assert "which just finished" in line


def test_a_paused_executor_gets_nothing(waiting_board):
    waiting_board.config = settings(waiting_board.config.root, 'repo = "o/r"\n[status]\npaused = "paused"')
    waiting_board.post(30, "paused", "#28")
    waiting_board.post(28, "done")
    assert finished(waiting_board) == []


def test_a_ticket_waiting_on_itself_gets_nothing(waiting_board):
    waiting_board.post(30, "in progress", "#30")
    waiting_board.close(30)
    assert finished(waiting_board) == []


def test_two_waiters_each_get_one_event(waiting_board):
    waiting_board.comments[31], waiting_board.open = [], [*waiting_board.open, 31]
    waiting_board.post(31, "blocked", "#28 and #30")
    waiting_board.post(28, "done")
    assert sorted(key for _, _, key in finished(waiting_board)) == ["30>28", "31>28"]


def test_a_split_kitchen_reads_ticket_numbers_from_the_kitchen_repo(waiting_board):
    waiting_board.config = config.Config(root=waiting_board.config.root, repo="o/r", code="o/code")
    waiting_board.post(30, "in progress", "#28, then PR o/code#5")
    waiting_board.post(28, "done")
    assert [key for _, _, key in finished(waiting_board)] == ["30>28"]
    assert all("o/code" not in call for call in waiting_board.calls)


def test_the_comment_and_event_listings_are_fetched_once_per_poll(waiting_board):
    waiting_board.post(28, "done")
    token = watch.RECENT.set({})
    try:
        watch.collect(waiting_board.config, "o/r", SINCE, SINCE, set(), set())
        assert len(finished(waiting_board)) == 1
    finally:
        watch.RECENT.reset(token)
    assert len([call for call in waiting_board.calls
                if "/issues/comments?since" in call or "/issues/events?" in call]) == 2


THREAD = "00000000-0000-4000-8000-000000000001"
T0 = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc).timestamp()


class Stop(Exception):
    pass


def stop_sleeping(seconds):
    raise Stop


@pytest.fixture
def jobs(tmp_path, monkeypatch):
    """A temp run registry with a fake clock; ticket #26 is owned by THREAD, and nothing reaches GitHub."""
    from contextlib import ExitStack
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    asks = []
    monkeypatch.setattr(ding, "issue_map", lambda repo=None, raise_errors=False: asks.append(repo) or {THREAD: {26}})
    state = SimpleNamespace(config=config.Config(root=tmp_path, repo="o/r"), clock=T0, asks=asks, tmp=tmp_path,
                            stack=ExitStack())

    def move(path, updated, run="running"):
        moment = datetime.fromtimestamp(state.clock + updated, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        path.write_text(json.dumps({"schema": "progress-v1", "state": run, "stage": "answer",
                                    "current": {"name": "answer", "done": 137, "total": 500},
                                    "updated": {"utc": moment}}))

    def start(name="train", progress=True, expect_hours=None):
        path = tmp_path / name / "progress.json"
        if progress:
            path.parent.mkdir(exist_ok=True)
            move(path, 0)
        run_id = state.stack.enter_context(ding.registered_run(
            THREAD, tmp_path / f"{name}.jsonl", path if progress else None, expect_hours))
        registry = ding.run_registry()
        rows = [json.loads(line) for line in registry.read_text().splitlines()]
        rows[-1]["started_ns"] = int(state.clock * 1e9)
        registry.write_text("".join(json.dumps(row) + "\n" for row in rows))
        return run_id, path

    def watching(**options):
        return config.Config(root=tmp_path, repo="o/r", watch=config.Watch(**options))

    state.start, state.move = start, move
    state.stalls = lambda reported=(), **options: watch.stalled_jobs(
        watching(**options) if options else state.config, "o/r", ding.registered_runs(), set(reported), state.clock)
    state.overruns = lambda reported=(), **options: watch.overrun_jobs(
        watching(**options) if options else state.config, "o/r", ding.registered_runs(), set(reported), state.clock)
    yield state
    state.stack.close()


def test_a_stalled_job_gives_one_event_naming_ticket_and_last_progress(jobs):
    jobs.start()
    jobs.clock += 31 * 60
    [(_, line, key)] = jobs.stalls()
    assert line.startswith("#26: job train/progress.json has made no progress for 31 minutes")
    assert "answer 137/500" in line
    assert jobs.stalls({key}) == []


def test_a_job_stale_for_less_than_the_threshold_gives_no_stall(jobs):
    jobs.start()
    jobs.clock += 29 * 60
    assert jobs.stalls() == []
    assert jobs.asks == []


def test_progress_resuming_then_stalling_again_is_a_new_stall(jobs):
    _, path = jobs.start()
    jobs.clock += 31 * 60
    [(_, _, first)] = jobs.stalls()
    jobs.move(path, 0)
    assert jobs.stalls({first}) == []
    jobs.clock += 31 * 60
    [(_, _, second)] = jobs.stalls({first})
    assert second != first


def test_stale_minutes_zero_disables_the_stall_event(jobs):
    jobs.start()
    jobs.clock += 5 * 3600
    assert jobs.stalls(stale_minutes=0) == []
    assert len(jobs.stalls()) == 1


def test_a_task_without_progress_gives_no_stall_event(jobs):
    jobs.start(progress=False)
    jobs.clock += 5 * 3600
    assert jobs.stalls() == []


def test_a_finished_progress_file_or_an_ended_run_gives_no_stall(jobs):
    _, path = jobs.start()
    jobs.start("other")
    jobs.clock += 2 * 3600
    jobs.move(path, -2 * 3600, run="done")
    [(_, line, _)] = jobs.stalls()
    assert "other/progress.json" in line
    jobs.stack.close()
    assert jobs.stalls() == []


def test_a_failed_ticket_lookup_reports_nothing_and_the_next_poll_retries(jobs, monkeypatch, capsys):
    jobs.start(expect_hours=1)
    jobs.clock += 2 * 3600

    def fail(repo=None, raise_errors=False):
        raise OSError("gh down")

    monkeypatch.setattr(ding, "issue_map", fail)
    assert jobs.stalls() == [] and jobs.overruns() == []
    assert "ticket lookup failed" in capsys.readouterr().err
    monkeypatch.setattr(ding, "issue_map", lambda repo=None, raise_errors=False: {THREAD: {26}})
    assert len(jobs.stalls()) == 1 and len(jobs.overruns()) == 1


def test_issue_map_raises_on_a_gh_failure_only_when_asked(monkeypatch, capsys):
    def fail(path):
        raise OSError("gh down")

    monkeypatch.setattr(ding, "gh_records", fail)
    assert ding.issue_map("o/r") == {}
    assert "issue lookup failed" in capsys.readouterr().err
    with pytest.raises(OSError):
        ding.issue_map("o/r", raise_errors=True)


@pytest.mark.parametrize("updated", [None, "not a time", 5])
def test_a_running_file_without_a_usable_update_time_ages_by_its_mtime(jobs, updated):
    _, path = jobs.start()
    data = json.loads(path.read_text())
    if updated is None:
        del data["updated"]
    else:
        data["updated"] = {"utc": updated}
    path.write_text(json.dumps(data))
    os.utime(path, (jobs.clock, jobs.clock))
    assert jobs.stalls() == []
    jobs.clock += 31 * 60
    [(_, line, key)] = jobs.stalls()
    assert "no progress for 31 minutes" in line
    assert jobs.stalls({key}) == []


def test_a_running_file_whose_process_is_gone_gives_no_stall_or_overrun(jobs):
    jobs.start(expect_hours=1)
    jobs.clock += 5 * 3600
    jobs.stack.close()
    assert jobs.stalls() == [] and jobs.overruns() == []


def test_a_job_over_one_and_a_half_times_its_estimate_gives_one_overrun_event(jobs):
    jobs.start(expect_hours=2)
    jobs.clock += 2.9 * 3600
    assert jobs.overruns() == []
    jobs.clock += 0.2 * 3600
    [(_, line, key)] = jobs.overruns()
    assert line.startswith("#26: job train/progress.json has run 3.1 hours against its estimate of 2")
    assert "answer 137/500" in line
    assert jobs.overruns({key}) == []


def test_overrun_factor_is_configurable_and_zero_disables(jobs):
    jobs.start(expect_hours=2)
    jobs.clock += 2.5 * 3600
    assert len(jobs.overruns(overrun_factor=1.2)) == 1
    assert jobs.overruns(overrun_factor=0) == []


def test_a_run_without_an_estimate_or_already_ended_gives_no_overrun(jobs):
    jobs.start("plain")
    jobs.start("done", expect_hours=1)
    jobs.clock += 10 * 3600
    assert [line for _, line, _ in jobs.overruns() if "done" in line]
    jobs.stack.close()
    assert jobs.overruns() == []


def test_the_watch_reports_each_job_once_and_not_again_after_a_restart(jobs, monkeypatch, capsys):
    _, path = jobs.start(expect_hours=1)
    jobs.clock += 2 * 3600
    jobs.move(path, -2 * 3600)
    monkeypatch.setattr(config, "load", lambda: jobs.config)
    monkeypatch.setattr(watch.time, "time", lambda: jobs.clock)
    monkeypatch.setattr(watch, "collect", lambda *args, **kwargs: [])
    monkeypatch.setattr(watch, "pr_wakes", lambda *args: ([], {}))
    monkeypatch.setattr(watch, "idle", lambda *args: ([], {}))
    for name in ("stale", "unanswered_design", "unrouted_waits", "missing_waiters", "stalled", "finished_waits"):
        monkeypatch.setattr(watch, name, lambda *args: [])
    state = jobs.tmp / "watch.json"
    arguments = ["watch", "--state", str(state), "--interval", "0", "--settle", "0"]

    assert ding.main(arguments) == 0
    out = capsys.readouterr().out
    assert out.count("has made no progress") == 1 and out.count("against its estimate") == 1
    saved = json.loads(state.read_text())
    assert len(saved["job_stall_reported"]) == 1 and len(saved["job_overrun_reported"]) == 1

    monkeypatch.setattr(watch.time, "sleep", stop_sleeping)
    with pytest.raises(Stop):
        ding.main(arguments)
    assert "no progress" not in capsys.readouterr().out
    assert len(jobs.asks) == 2


def test_a_role_watch_never_checks_jobs(jobs, monkeypatch):
    seen = []
    monkeypatch.setattr(watch, "stalled_jobs", lambda *args: seen.append(1) or [])
    monkeypatch.setattr(watch, "overrun_jobs", lambda *args: seen.append(1) or [])
    monkeypatch.setattr(watch, "collect", lambda *args, **kwargs: [])
    monkeypatch.setattr(watch, "pr_wakes", lambda *args: ([], {}))
    monkeypatch.setattr(config, "load", lambda: jobs.config)
    monkeypatch.setattr(watch.time, "sleep", stop_sleeping)
    with pytest.raises(Stop):
        ding.main(["watch", "--for", "Designer", "--state", str(jobs.tmp / "role.json"), "--interval", "0"])
    assert seen == []


def test_the_estimate_is_recorded_in_the_registry_and_must_be_positive(jobs):
    jobs.start(expect_hours=1.5)
    assert [run["expect_hours"] for run in ding.registered_runs()] == [1.5]
    with pytest.raises(SystemExit):
        ding.main(["launch", "x", "--expect-hours", "0", "--", "true"])
