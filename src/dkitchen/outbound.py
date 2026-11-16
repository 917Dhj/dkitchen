"""What the kitchen writes into the code repo in the user's name: PRs and code issues.

`ding pr TICKET --title T --body-file F [--draft]` opens a PR from the current branch, which must already be pushed,
and records `PR: owner/code#N` on the ticket. `ding pr TICKET --ready N` marks it ready for review.
`ding code-issue TICKET --title T --body-file F` opens a code issue and records `Code issue: owner/code#N`.

When the kitchen lives in its own repo, the title and body are scanned first, and nothing is posted when they carry
kitchen internals: role or session signatures, a status block, the kitchen repo's name, or a bare `#N`, which the
code repo would read as one of its own issues (allowed only for the code issues the ticket records).

In a shared code repo, opening a PR that is not a draft, marking one ready, and opening a code issue each need
`--approval URL`: a user decision on the ticket, opening `<role>: user decision` ([outbound] user_decision), or the
night orders open now.

The ticket comment is signed by `--from ROLE`, or else by the caller's executor session, after a status block.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess

from dkitchen import inbox, watch
from dkitchen.config import Config
from dkitchen.orchestrate import call, fail

PR_LINE = re.compile(r"(?m)^PR: ([\w.-]+/[\w.-]+)#(\d+)\b")
ISSUE_LINE = re.compile(r"(?m)^Code issue: ([\w.-]+/[\w.-]+)#(\d+)\b")
COMMENT_URL = re.compile(r"https://github\.com/([\w.-]+/[\w.-]+)/issues/(\d+)#issuecomment-(\d+)")
CREATED_URL = re.compile(r"https://github\.com/([\w.-]+/[\w.-]+)/(pull|issues)/(\d+)")
BARE_NUMBER = re.compile(r"(?<![\w/&#])#(\d+)(?![\w])")
SESSION_MARKERS = ("Codex session:", "Claude session:", "Codex owner:", "Claude owner:", "PR:", "Code issue:")


@dataclass(frozen=True)
class Links:
    prs: frozenset[tuple[str, int]]
    issues: frozenset[tuple[str, int]]


def ticket_texts(config: Config, ticket: int) -> list[str]:
    """The ticket's body and every comment body, from the kitchen repo."""
    repo = config.kitchen_repo()
    result = call(config, "gh", "api", f"repos/{repo}/issues/{ticket}")
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"cannot read {repo}#{ticket}")
    issue = json.loads(result.stdout)
    if "pull_request" in issue:
        raise ValueError(f"#{ticket} is a PR, not a ticket")
    result = call(config, "gh", "api", "--paginate", "--slurp", f"repos/{repo}/issues/{ticket}/comments?per_page=100")
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"cannot read the comments of {repo}#{ticket}")
    return [issue.get("body") or "", *(comment.get("body") or "" for page in json.loads(result.stdout) for comment in page)]


def links(config: Config, ticket: int) -> Links:
    """The PRs and code issues the ticket records."""
    texts = ticket_texts(config, ticket)
    found = {pattern: frozenset((repo, int(number)) for text in texts for repo, number in pattern.findall(text))
             for pattern in (PR_LINE, ISSUE_LINE)}
    return Links(prs=found[PR_LINE], issues=found[ISSUE_LINE])


def leaks(config: Config, text: str, allowed: set[int]) -> list[str]:
    """Where text carries kitchen internals into the code repo; empty for a single-repo kitchen."""
    if not config.split:
        return []
    separator = watch.normalized(config.roles.separator).strip()
    names = {watch.normalized(name) for name in watch.role_names(config) if name != config.roles.user}
    names |= {watch.normalized(alias) for aliases in config.roles.aliases.values() for alias in aliases}
    fields = [watch.normalized(name) for name in config.status.fields]
    kitchen = config.kitchen_repo().lower()
    problems, status_lines = [], []
    for number, raw in enumerate(text.splitlines(), 1):
        line = watch.normalized(raw).strip()
        signed = next((name for name in sorted(names, key=len, reverse=True) if line.startswith(name + separator)), None)
        if signed is not None:
            problems.append(f"line {number} opens with the {signed} signature")
        marker = next((marker for marker in SESSION_MARKERS if line.startswith(marker)), None)
        if marker is not None:
            problems.append(f"line {number} carries the kitchen marker {marker!r}")
        if any(line.startswith(field + separator) for field in fields):
            status_lines.append(number)
        if kitchen in raw.lower():
            problems.append(f"line {number} names the kitchen repo {config.kitchen_repo()}")
        for match in BARE_NUMBER.finditer(raw):
            if int(match.group(1)) not in allowed:
                problems.append(f"line {number} has a bare {match.group()}, which {config.code_repo()} reads as its own "
                                "issue; write the full link, or record the code issue on the ticket first")
    if len(status_lines) >= 2:
        problems.append(f"lines {', '.join(map(str, status_lines))} are a status block")
    return problems


def decision_heads(config: Config) -> list[str]:
    """The first lines a user decision may open with: the orchestrator's or a designer's signature, then the marker."""
    signatures = [config.roles.signature(config.roles.orchestrator), *config.designer_signatures]
    return [watch.normalized(signature + config.outbound.user_decision) for signature in signatures]


def approval_problem(config: Config, url: str | None, ticket: int) -> str | None:
    """Why url is not an approval for this ticket, or None when it is one."""
    if not url:
        return (f"{config.code_repo()} is shared, so this needs the user's approval: pass --approval with the link to "
                f"a user decision on #{ticket}, or to the night orders open now")
    match = COMMENT_URL.fullmatch(url.strip())
    if match is None:
        return f"--approval must link an issue comment (…/issues/N#issuecomment-ID), not {url!r}"
    repo, number, ident = match.group(1), int(match.group(2)), match.group(3)
    if repo.lower() != config.kitchen_repo().lower():
        return f"--approval must link a comment in the kitchen repo {config.kitchen_repo()}, not {repo}"
    result = call(config, "gh", "api", f"repos/{repo}/issues/comments/{ident}")
    if result.returncode:
        return f"cannot read the approval {url}: {result.stderr.strip()}"
    body = json.loads(result.stdout).get("body") or ""
    first = watch.normalized(body.split("\n", 1)[0]).strip()
    if number == ticket and any(first.startswith(head) for head in decision_heads(config)):
        return None
    if config.log.issue is not None and number == config.log.issue:
        from dkitchen import night

        orders = night.open_orders(config, repo, datetime.now(timezone.utc))
        if orders is not None and orders.get("url") == url.strip():
            return None
        return f"{url} is not the night orders open now"
    return (f"{url} is not a user decision on #{ticket}: its first line must open with "
            f"{config.roles.signature(config.roles.orchestrator) + config.outbound.user_decision!r} or a designer's")


def signer(config: Config, role: str | None) -> str:
    """Who signs the ticket comment: `ROLE: ` for --from, else the caller's executor session line."""
    if role is not None:
        known = {watch.normalized(name): name for name in watch.role_names(config) if name != config.roles.user}
        name = known.get(watch.normalized(role))
        if name is None:
            raise ValueError(f"--from must name a role: {', '.join(known.values())}")
        return config.roles.signature(name)
    caller = inbox.current_session()
    if caller is None:
        raise ValueError("run this inside the executor's session, or name the role posting it with --from ROLE")
    kind, session_id = caller
    return f"{'Codex' if kind == 'codex' else 'Claude'} session: {session_id}"


def git(*args: str) -> str:
    result = subprocess.run(["git", *args], capture_output=True, text=True, timeout=60, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout.strip()


def pushed_branch() -> str:
    """The current branch, refused unless origin has exactly its HEAD."""
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    if branch == "HEAD":
        raise ValueError("HEAD is detached; check out the PR's branch first")
    head = git("rev-parse", "HEAD")
    remote = git("ls-remote", "origin", f"refs/heads/{branch}").split("\t", 1)[0]
    if remote != head:
        raise ValueError(f"origin's {branch} is {remote[:8] or 'missing'}, not HEAD {head[:8]}; push the branch first")
    return branch


def created(output: str, kind: str) -> tuple[str, int, str]:
    lines = output.strip().splitlines()
    match = CREATED_URL.fullmatch(lines[-1].strip()) if lines else None
    if match is None or match.group(2) != kind:
        raise ValueError(f"gh did not print the new {'PR' if kind == 'pull' else 'issue'}'s link (got {output.strip()!r})")
    return match.group(1), int(match.group(3)), match.group()


def record(config: Config, ticket: int, sign: str, line: str, url: str) -> int:
    """Leave the link line on the ticket: after the role's signature, or between a status block and the session line."""
    if sign.endswith(config.roles.separator):
        body = f"{sign}{url}\n{line}\n"
    else:
        from dkitchen.ding import status_block

        body = f"{status_block(config)}\n\n{line}\n\n{sign}\n"
    result = call(config, "gh", "issue", "comment", str(ticket), "--repo", config.kitchen_repo(), "--body", body)
    if result.returncode:
        return fail(f"recording `{line}` on #{ticket} failed: {result.stderr.strip()}; add it to the ticket by hand")
    return 0


def read_text(args) -> tuple[str, str]:
    title = (args.title or "").strip()
    if not title:
        raise ValueError("--title must not be empty")
    body = Path(args.body_file).read_text(encoding="utf-8")
    if not body.strip():
        raise ValueError(f"{args.body_file} is empty")
    return title, body


def checked(config: Config, ticket: int, title: str, body: str) -> Links:
    """The ticket's links, after refusing text that carries kitchen internals."""
    found = links(config, ticket)
    allowed = {number for repo, number in found.issues if repo == config.code_repo()}
    problems = leaks(config, f"{title}\n{body}", allowed)
    if problems:
        raise ValueError("the text carries kitchen internals into the code repo; nothing posted (line 1 is the title):\n"
                         + "\n".join(f"- {problem}" for problem in problems))
    return found


def pr(args, config: Config) -> int:
    try:
        sign = signer(config, args.sender)
        repo = config.code_repo()
        if args.ready is not None:
            if (repo, args.ready) not in links(config, args.ticket).prs:
                return fail(f"#{args.ticket} has no PR line for {repo}#{args.ready}; nothing done")
            if config.shared and (problem := approval_problem(config, args.approval, args.ticket)):
                return fail(f"{problem}; nothing done")
            result = call(config, "gh", "pr", "ready", str(args.ready), "--repo", repo)
            if result.returncode:
                return fail(f"gh pr ready failed: {result.stderr.strip()}")
            print(f"{repo}#{args.ready} is ready for review")
            return 0
        title, body = read_text(args)
        checked(config, args.ticket, title, body)
        if config.shared and not args.draft and (problem := approval_problem(config, args.approval, args.ticket)):
            return fail(f"{problem}; or open it with --draft. Nothing posted")
        branch = pushed_branch()
        command = ["gh", "pr", "create", "--repo", repo, "--head", branch, "--title", title,
                   "--body-file", str(Path(args.body_file).resolve())]
        command += ["--draft"] * args.draft + (["--base", args.base] if args.base else [])
        result = call(config, *command)
        if result.returncode:
            return fail(f"gh pr create failed: {result.stderr.strip()}")
        _, number, url = created(result.stdout, "pull")
    except (OSError, UnicodeDecodeError, RuntimeError, ValueError, KeyError, TypeError) as error:
        return fail(str(error))
    print(url)
    return record(config, args.ticket, sign, f"PR: {repo}#{number}", url)


def code_issue(args, config: Config) -> int:
    try:
        sign = signer(config, args.sender)
        title, body = read_text(args)
        checked(config, args.ticket, title, body)
        if config.shared and (problem := approval_problem(config, args.approval, args.ticket)):
            return fail(f"{problem}. Nothing posted")
        repo = config.code_repo()
        result = call(config, "gh", "issue", "create", "--repo", repo, "--title", title,
                      "--body-file", str(Path(args.body_file).resolve()))
        if result.returncode:
            return fail(f"gh issue create failed: {result.stderr.strip()}")
        _, number, url = created(result.stdout, "issues")
    except (OSError, UnicodeDecodeError, RuntimeError, ValueError, KeyError, TypeError) as error:
        return fail(str(error))
    print(url)
    return record(config, args.ticket, sign, f"Code issue: {repo}#{number}", url)
