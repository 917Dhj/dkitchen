"""The orchestrator's routine GitHub writes, each checked step by step.

- review: post a review comment on the PR and write its verdict as the review_check status on the reviewed HEAD.
- merge: merge a reviewed PR at the reviewed HEAD and print the merge commit; refuses drafts, moved HEADs,
  wrong bases, and unsuccessful required or review checks. With [merge] refresh, the repo's refresh command runs
  first, against the default-branch tip, and a nonzero exit refuses.
- relay: send a message to a ticket's executor with `ding send`, then leave the matching ticket comment. By default
  the message goes into the executor's current turn and replaces the orchestrator's relays still queued for it.
- log: post one entry to the orchestrator log, stamped with the current UTC time.
Relay and log comments carry the orchestrator signature; review comments identify the reviewed commit.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import json
import re
import shlex
import subprocess
import sys

from dkitchen import ding, watch
from dkitchen.config import Config


def signed(text: str, config: Config) -> str:
    signature = config.roles.signature(config.roles.orchestrator)
    text = text.strip()
    return text if text.startswith(signature.rstrip()) else signature + text


def log_body(items: list[str], pending: list[str], moment: datetime, config: Config) -> str:
    roles = config.roles
    lines = [f"{roles.signature(roles.orchestrator)}{moment.astimezone(timezone.utc):%H:%M} UTC",
             *(f"- {item}" for item in items),
             f"- {config.log.pending}{roles.separator}{'; '.join(pending) or config.status.none}"]
    return "\n".join(lines)


def call(config: Config, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=config.root, text=True, capture_output=True)


def fail(message: str) -> int:
    print(f"ding: {message}", file=sys.stderr)
    return 1


def comment(config: Config, repo: str, issue: int, body: str) -> int:
    result = call(config, "gh", "issue", "comment", str(issue), "--repo", repo, "--body", body)
    if result.returncode:
        return fail(f"comment failed: {result.stderr.strip()}")
    print(result.stdout.strip())
    return 0


def head_checks(config: Config, repo: str, sha: str) -> dict:
    """Read the latest check runs and statuses on the exact reviewed commit, without polling."""
    if not (config.merge.required_checks or config.merge.review_check):
        return {}
    checks = {}
    for endpoint in ("check-runs?filter=latest&per_page=100", "status?per_page=100"):
        result = call(config, "gh", "api", "--paginate", "--slurp", f"repos/{repo}/commits/{sha}/{endpoint}")
        if result.returncode:
            raise RuntimeError(f"cannot read required checks on {sha}: {result.stderr.strip()}")
        for page in json.loads(result.stdout):
            if endpoint.startswith("check-runs"):
                for run in page["check_runs"]:
                    if run["head_sha"] == sha:
                        conclusion = run["conclusion"] if run["status"] == "completed" else "pending"
                        checks.setdefault(run["name"], []).append((conclusion, run["html_url"]))
            elif page["sha"] == sha:
                for status in page["statuses"]:
                    checks.setdefault(status["context"], []).append((status["state"], status["target_url"]))
    return checks


def default_branch(config: Config, repo: str) -> str:
    result = call(config, "gh", "api", f"repos/{repo}")
    if result.returncode:
        raise RuntimeError(f"cannot read default branch: {result.stderr.strip()}")
    branch = json.loads(result.stdout)["default_branch"]
    if not isinstance(branch, str) or not branch:
        raise ValueError("repository has no default branch")
    return branch


def readiness(config: Config, repo: str, pr: dict, branch: str, checks: dict | None = None) -> dict:
    """GitHub facts on this HEAD, shared by merge, watch and waits."""
    reasons = []
    if pr["state"] != "OPEN":
        reasons.append(f"PR is {pr['state']}")
    if pr["isDraft"]:
        reasons.append("PR is a draft")
    if pr["baseRefName"] != branch:
        reasons.append(f"PR base is {pr['baseRefName']}, not repository default branch {branch}")
    pending_only = not reasons
    sha = pr["headRefOid"]
    checks = head_checks(config, repo, sha) if checks is None else checks
    required = config.merge.required_checks + ((config.merge.review_check,) if config.merge.review_check else ())
    for name in dict.fromkeys(required):
        for state, url in checks.get(name, [("missing", None)]):
            if state in {"pending", "missing", None}:
                reasons.append(f"check {name} has not finished on {sha} ({state or 'pending'})"
                               + (f": {url}" if url else ""))
            elif state != "success":
                pending_only = False
                reasons.append(f"check {name} is {state} on {sha}" + (f": {url}" if url else ""))
    review = [state for state, _ in checks.get(config.merge.review_check, [])]
    review_state = "missing"
    if review:
        review_state = "success" if all(state == "success" for state in review) else "pending"
        if "failure" in review:
            review_state = "failure"
    return {"ready": not reasons, "reasons": reasons, "review": review_state,
            "pending_only": bool(reasons) and pending_only}


def review(args, config: Config) -> int:
    """Record a verdict on a PR HEAD: as a PR comment and commit status, or, in a shared code repo, on its ticket."""
    if config.shared and getattr(args, "ticket", None) is None:
        return fail(f"{config.code_repo()} is shared, so a PR verdict goes on its ticket, not the PR: "
                    "add --ticket N, the ticket whose PR line names it")
    if not config.shared and not config.split and getattr(args, "ticket", None) is not None:
        return fail(f"{config.code_repo()} is not shared, so a PR verdict goes on the PR; drop --ticket")
    if not config.shared and not config.merge.review_check:
        return fail("ding review requires [merge] review_check")
    repo = config.code_repo()
    result = call(config, "gh", "pr", "view", str(args.pr), "--repo", repo, "--json", "headRefOid")
    if result.returncode:
        return fail(f"cannot read PR HEAD: {result.stderr.strip()}")
    try:
        sha = json.loads(result.stdout)["headRefOid"]
        if not isinstance(sha, str) or not sha:
            raise ValueError("missing HEAD")
    except (ValueError, KeyError, TypeError) as error:
        return fail(f"cannot read PR HEAD: {error}")
    if not args.sha or not sha.startswith(args.sha):
        return fail(f"PR #{args.pr} HEAD is now {sha}, not the reviewed {args.sha}; review it again")
    line = config.merge.review_pass if args.verdict == "pass" else config.merge.review_changes
    if config.shared:
        from dkitchen import outbound, verdict

        try:
            linked = outbound.links(config, args.ticket).prs
        except (RuntimeError, ValueError, KeyError, TypeError) as error:
            return fail(f"cannot read #{args.ticket}: {error}. Nothing posted")
        if (repo, args.pr) not in linked:
            return fail(f"#{args.ticket} has no PR line for {repo}#{args.pr}; `ding pr` writes one when it opens "
                        "the PR. Nothing posted")
        return verdict.review_ticket(args, config, f"{line.replace('{sha}', sha[:8])} ({repo}#{args.pr})")
    body = f"{line.replace('{sha}', sha[:8])}\n\n{Path(args.body_file).read_text(encoding='utf-8')}"
    if config.split:
        from dkitchen import outbound

        try:
            found = outbound.links(config, args.ticket) if args.ticket is not None else None
            if found is not None and (repo, args.pr) not in found.prs:
                return fail(f"#{args.ticket} has no PR line for {repo}#{args.pr}; `ding pr` writes one when it opens "
                            "the PR. No comment, no status")
            outbound.refuse_leaks(config, body, found)
        except (RuntimeError, ValueError, KeyError, TypeError) as error:
            return fail(f"{error}. No comment, no status")
    result = call(config, "gh", "api", f"repos/{repo}/issues/{args.pr}/comments", "-f", f"body={body}")
    if result.returncode:
        return fail(f"review comment failed: {result.stderr.strip()}; no status written")
    try:
        url = json.loads(result.stdout)["html_url"]
        if not isinstance(url, str) or not url:
            raise ValueError("missing comment URL")
    except (ValueError, KeyError, TypeError) as error:
        return fail(f"cannot read review comment response: {error}; inspect PR #{args.pr} before retrying; no status written")
    result = call(config, "gh", "api", f"repos/{repo}/statuses/{sha}",
                  "-f", f"state={'success' if args.verdict == 'pass' else 'failure'}",
                  "-f", f"context={config.merge.review_check}", "-f", f"target_url={url}")
    if result.returncode:
        return fail(f"review status failed: {result.stderr.strip()}; comment exists at {url}")
    print(f"{url}\n{config.merge.review_check}: {args.verdict} on {sha}")
    return 0


REFRESH_RUNS = 3
REFRESH_LINES = 20


def branch_tip(config: Config, repo: str, branch: str) -> str:
    result = call(config, "gh", "api", f"repos/{repo}/git/ref/heads/{branch}")
    if result.returncode:
        raise RuntimeError(f"cannot read the tip of {branch}: {result.stderr.strip()}")
    sha = json.loads(result.stdout)["object"]["sha"]
    if not isinstance(sha, str) or not sha:
        raise ValueError(f"{branch} has no tip commit")
    return sha


def refresh(config: Config, repo: str, number: int, pr: dict, branch: str) -> str | None:
    """Run [merge] refresh until the default-branch tip holds still across a run; return why the merge is refused.

    Each run gets the tip it must validate against as {tip}; the merge is safe only if that same tip is still the
    tip afterwards. The command may replace a status on the HEAD, so the required checks are read again after each run.
    """
    if config.split and config.code_root is None:
        return f"{repo}'s checkout is not linked on this machine, so refresh cannot run; run `ding kitchen link` first"
    sha = pr["headRefOid"]
    tip = branch_tip(config, repo, branch)
    for _ in range(REFRESH_RUNS):
        argv = config.merge.refresh_argv(number, sha, tip)
        print(f"ding: refresh against {branch} {tip[:8]}: {shlex.join(argv)}", file=sys.stderr, flush=True)
        try:
            # The refresh command validates the code, so it runs in the code repo's checkout.
            result = call(replace(config, root=config.code_root) if config.split else config, *argv)
        except OSError as error:
            return f"refresh could not run ({shlex.join(argv)}): {error}; merge refused"
        if result.returncode:
            lines = "\n".join((result.stdout + result.stderr).strip().splitlines()[-REFRESH_LINES:])
            return (f"refresh exited {result.returncode} against {branch} {tip[:8]} ({shlex.join(argv)}); merge refused"
                    + (f"\n{lines}" if lines else ""))
        last = result.stdout.strip().splitlines()[-1:]
        print(f"ding: refresh passed{': ' + last[0] if last else ''}", file=sys.stderr, flush=True)
        failures = readiness(config, repo, pr, branch)["reasons"]
        if failures:
            return "PR readiness blocks merge after refresh:\n" + "\n".join(failures)
        latest = branch_tip(config, repo, branch)
        if latest == tip:
            return None
        tip = latest
    return f"{branch} kept moving: its tip changed during each of {REFRESH_RUNS} refresh runs; merge refused, try again later"


def merge(args, config: Config) -> int:
    repo = config.code_repo()
    if config.merger == "team":
        return fail(f"the team merges PRs in {repo} ([merge] by = team{'' if config.merge.by else ', the default for a shared code repo'}); "
                    "nothing done")

    def view() -> dict:
        result = call(config, "gh", "pr", "view", str(args.pr), "--repo", repo, "--json", "isDraft,state,headRefOid,mergeCommit,body,baseRefName")
        if result.returncode:
            raise RuntimeError(result.stderr.strip())
        return json.loads(result.stdout)

    try:
        pr = view()
        if pr["state"] == "MERGED":
            return fail(f"PR #{args.pr} was already merged as {pr['mergeCommit']['oid']}; nothing done")
        if not args.sha or not pr["headRefOid"].startswith(args.sha):
            return fail(f"PR #{args.pr} HEAD is now {pr['headRefOid']}, not the reviewed {args.sha}; review it again")
        if pr["isDraft"]:
            return fail(f"PR #{args.pr} is a draft and cannot be merged; its author marks it ready with gh pr ready first")
        if pr["state"] != "OPEN":
            return fail(f"PR #{args.pr} is {pr['state']} and cannot be merged")
        branch = default_branch(config, repo)
        if pr["baseRefName"] != branch:
            return fail(f"PR base is {pr['baseRefName']}, not repository default branch {branch}")
        failures = readiness(config, repo, pr, branch)["reasons"]
        if failures:
            return fail("PR readiness blocks merge:\n" + "\n".join(failures))
        if config.merge.refresh:
            refused = refresh(config, repo, args.pr, pr, branch)
            if refused:
                return fail(refused)
        result = call(config, "gh", "pr", "merge", str(args.pr), "--repo", repo, "--merge",
                      "--match-head-commit", pr["headRefOid"])
        if result.returncode:
            return fail(f"merge failed: {(result.stderr or result.stdout).strip()}")
        pr = view()
    except (RuntimeError, ValueError, KeyError, TypeError) as error:
        return fail(f"cannot read PR #{args.pr}: {error}")
    if pr["state"] != "MERGED":
        return fail(f"the merge command succeeded, but PR #{args.pr} is {pr['state']}; find out why before logging it")
    print(f"PR #{args.pr} merged as {pr['mergeCommit']['oid']}")
    return 0


def relay(args, config: Config) -> int:
    repo = config.repository()
    message = ding.message_text(args.message, args.message_file, None)
    target = args.to or f"{repo}#{args.ticket}"
    queue = getattr(args, "queue", False)
    text = signed(message, config)
    if not queue:
        signature = config.roles.signature(config.roles.orchestrator)
        text = f"{signature}{config.relay.superseding}\n{text[len(signature.rstrip()):].lstrip()}"
    send = ["send", target, "--from", config.roles.orchestrator, "--message", text]
    if not queue:
        send += ["--steer", "--supersede"]
    if getattr(args, "interrupt", False):
        send += ["--interrupt"]
    if args.socket:
        send += ["--socket", args.socket]
    code = ding.main(send)
    if code == ding.NO_LISTENER_EXIT:
        print(f"ding: {ding.no_listener_note(target)}", file=sys.stderr)
    elif code:
        return fail("ding send did not confirm delivery; check ~/.local/state/ding/sent.jsonl before sending again. "
                    "No comment was left.")
    if args.no_comment:
        return 0
    return comment(config, repo, args.ticket, signed(args.comment or message, config))


def log_is_empty(items: list[str], pending: list[str], config: Config) -> bool:
    """True when the entry says nothing: no item with text and no pending matter besides the "none" word."""
    return not any(item.strip() for item in items) and all(
        not matter.strip() or matter.strip() == config.status.none for matter in pending)


def log(args, config: Config) -> int:
    issue = args.issue or config.log.issue
    if issue is None:
        return fail("no orchestrator log ticket; set [log] issue in .dkitchen.toml or pass --issue")
    if config.log.issue is not None and issue != config.log.issue and not getattr(args, "force", False):
        return fail(f"#{issue} is not the orchestrator log ticket (#{config.log.issue}). Use `gh issue comment` for a "
                    f"note on a work ticket, or `ding relay --comment` when its executor should hear it too; or pass --force "
                    "to log here anyway")
    if log_is_empty(args.item, args.pending, config):
        print("ding: log entry is empty (no items, nothing pending); nothing posted", file=sys.stderr)
        return 0
    return comment(config, config.repository(), issue, log_body(args.item, args.pending, datetime.now(timezone.utc), config))
