"""Wait for GitHub activity the orchestrator must handle, print it, and exit; read-only, no model calls.

Wakes on:
- executor comments whose status is not "in progress", or whose "waiting on" names a role or the user;
- idle executors still marked "in progress", after [watch] idle_minutes with no running job;
- Claude Code executors still marked "in progress" whose `ding inbox --wait` has been gone for
  [watch] executor_listener_minutes, once per executor comment;
- unanswered designer/verifier requests older than [watch] design_answer_minutes, once per executor comment;
- comments from the user (no role signature);
- a ticket finishing (an executor `done` status, or closed) while another open ticket's latest executor status
  names it as `#N` in its waiting field, once per waiting ticket and finished ticket;
- status labels being added, and newly opened PRs;
- stalled lines, at most once a day each: open draft PRs, and in-progress tickets whose status names no wait,
  not updated for --stalled-hours;
- stale tickets: no newer status label, last comment an executor "in progress" older than --stale-hours,
  no running `ding run` for the ticket, and no live tmux job whose session name holds issue<N>.
On tickets labelled awaiting-user, executor comments wake only for blocked, done, and waiting on design,
or when their "waiting on" names the orchestrator, designer, or verifier.
In orchestrator mode, a verifier comment wakes only when it carries the `changes` verdict line of
`ding review --ticket`; other verifier comments are listed in the next batch for reference.
The state file keeps the time already reported, so rerunning the same command loses nothing.
One watch runs per state file; a second one exits at once.
With --for NAME, executor requests and explicit handoffs to that role wake; designer rulings do not.
Aliases and width-normalized names share the longest-name match. Configured paused executors never wake --for.
Awaiting-user labels always suppress idle/stale checks; other status labels suppress only when newer than the comment.
Role names, status words, and labels come from .dkitchen.toml.
When `ding role take` recorded a holder for the watched role (the orchestrator without --for), a watch from another
session refuses to start, and a running one exits once another session takes the role.
"""
from __future__ import annotations

from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import unicodedata
from urllib.parse import quote

from dkitchen import inbox, truncate
from dkitchen.config import Config, Sessions

SHELLS = {"bash", "sh", "zsh", "dash", "fish"}
PR_NAMED = re.compile(r"(?<![A-Za-z])PR\s*#?\s*(\d+)|https://github\.com/([\w.-]+/[\w.-]+)/pull/(\d+)"
                      r"|(?<![A-Za-z])PR\s+([\w.-]+/[\w.-]+)#(\d+)")
VIEWER: list[str] = []  # the gh login, read once: in a split kitchen, the user's and the agents' code repo account
STALLED_EVERY_HOURS = 24  # the orchestrator's watch reports each stalled item at most once a day
WAITER_LOOKBACK_DAYS = 7  # older inbox records are not rechecked; a silent executor was reported long before
TICKET_NAMED = re.compile(r"(?<![\w/#])#([1-9][0-9]*)\b")
RECENT: ContextVar[dict[tuple, list[dict]] | None] = ContextVar("RECENT", default=None)
# newer() results shared by the checks of one poll; set only while a watch runs


def gh(path: str) -> list[dict]:
    result = subprocess.run(["gh", "api", path], capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"gh api {path} failed")
    return json.loads(result.stdout)


def newer(path: str, field: str, since: str, pages: int = 3) -> list[dict]:
    """Pages of a newest-first listing until an item is older than `since`."""
    key = (path, field, since, pages)
    shared = RECENT.get()
    if shared is not None and key in shared:
        return shared[key]
    items = []
    for page in range(1, pages + 1):
        batch = gh(f"{path}&per_page=100&page={page}")
        items.extend(item for item in batch if item[field] >= since)
        if len(batch) < 100 or batch[-1][field] < since:
            break
    if shared is not None:
        shared[key] = items
    return items


def recent_comments(repo: str, since: str) -> list[dict]:
    return newer(f"repos/{repo}/issues/comments?since={since}&sort=updated&direction=desc", "updated_at", since)


def recent_events(repo: str, since: str) -> list[dict]:
    return newer(f"repos/{repo}/issues/events?", "created_at", since)


def viewer() -> str:
    """The login gh posts as; the kitchen's PRs and code issues are opened under it."""
    if not VIEWER:
        VIEWER.append(gh("user")["login"])
    return VIEWER[0]


def outside_comments(config: Config, since: str) -> list[tuple[str, str, bool]]:
    """Comments by other people, since `since`, on code repo PRs and issues the kitchen's account opened.

    They wake the orchestrator; they never count as the user's words, even when they come from the user's login."""
    code, me, targets = config.code_repo(), viewer(), {}
    items = newer(f"repos/{code}/issues/comments?since={since}&sort=updated&direction=desc", "updated_at", since)
    items += newer(f"repos/{code}/pulls/comments?since={since}&sort=updated&direction=desc", "updated_at", since)
    found = []
    for comment in items:
        author = (comment.get("user") or {}).get("login", "")
        if author == me:
            continue
        number = issue_number(comment.get("issue_url") or comment.get("pull_request_url"))
        if number not in targets:
            targets[number] = gh(f"repos/{code}/issues/{number}")
        if (targets[number].get("user") or {}).get("login") != me:
            continue
        edited = " (edited)" if comment["created_at"] < since else ""
        first = next((line.strip() for line in (comment.get("body") or "").splitlines() if line.strip()), "")
        found.append((comment["updated_at"], f"{code}#{number} code repo comment by @{author}{edited}: "
                      f"{truncate(first, 120)} {comment['html_url']}", True))
    return found


def stamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def now() -> str:
    return stamp(datetime.now(timezone.utc))


def issue_number(url: str) -> int:
    return int(url.rstrip("/").rsplit("/", 1)[1])


def normalized(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def signature_name(prefix: str, config: Config) -> str:
    return prefix.rstrip().removesuffix(config.roles.separator.rstrip()).strip()


def designer_roles(config: Config) -> list[str]:
    names = [config.roles.designer]
    names += [signature_name(signature, config) for signature in config.designer_signatures]
    unique = {}
    for name in names:
        if name:
            unique.setdefault(normalized(name), name)
    return list(unique.values())


def role_variants(role: str, config: Config) -> set[str]:
    target = normalized(role)
    result = {target}
    for name, aliases in config.roles.aliases.items():
        group = {normalized(name), *(normalized(alias) for alias in aliases)}
        if target in group:
            result.update(group)
    return result


def role_names(config: Config) -> list[str]:
    roles = config.roles
    names = [roles.orchestrator, *designer_roles(config), roles.verifier, roles.executor,
             roles.user, *roles.aliases]
    return list({normalized(name): name for name in names}.values())


def named(text: str, role: str, config: Config, *, markers: tuple[str, ...] = (), signature: bool = False) -> bool:
    text = normalized(text)
    targets = role_variants(role, config)
    roles = config.roles
    names = role_names(config)
    choices = targets | {variant for name in names for variant in role_variants(name, config)}
    pattern = "|".join(map(re.escape, sorted(choices, key=len, reverse=True)))
    for match in re.finditer(pattern, text):
        if match.group() not in targets:
            continue
        if not markers and not signature:
            return True
        before = text[:match.start()]
        if markers and before.endswith(markers):
            return True
        if (signature and not before.rsplit("\n", 1)[-1].strip()
                and text[match.end():].startswith(normalized(roles.separator).rstrip())):
            return True
    return False


def review_line(template: str) -> str:
    """A pattern for a review comment's first line, with {sha} standing for the reviewed commit's first 8 digits."""
    return "[0-9a-fA-F]{8}".join(re.escape(part) for part in normalized(template).strip().split("{sha}"))


def signer(body: str, config: Config) -> str:
    """The role named at the start of the first line; otherwise the executor by a line starting with its
    session signature (`Codex session:`, or `Claude session:` for an executor run in Claude Code); else the user.
    A session signature quoted inside a line signs nothing."""
    roles = config.roles
    first_line = next((line for line in body.splitlines() if line.strip()), "")
    first_line = normalized(first_line)
    if config.merge.review_check and any(re.fullmatch(review_line(line), first_line.strip())
                                         for line in (config.merge.review_pass, config.merge.review_changes)):
        return roles.verifier
    first = re.sub(r"^[\s#*>]+", "", first_line)
    if (any(first_line.startswith(normalized(prefix)) or first.startswith(normalized(prefix))
            for prefix in config.designer_signatures)
            or any(first.startswith(variant + normalized(roles.separator))
                   for prefix in config.designer_signatures
                   for variant in role_variants(signature_name(prefix, config), config))):
        return roles.designer
    signed = next((name for name in (roles.verifier, roles.orchestrator)
                   if any(first.startswith(variant) for variant in role_variants(name, config))), None)
    if signed:
        return signed
    return roles.executor if re.search(r"(?m)^[ \t]*(?:Codex|Claude) session:", body) else roles.user


def changes_verdict(body: str, config: Config) -> bool:
    """Whether a verifier comment carries the `changes` verdict line that `ding review --ticket` writes as line 2."""
    lines = [line for line in body.splitlines() if line.strip()]
    return (len(lines) > 1 and signer(body, config) == config.roles.verifier
            and normalized(lines[1]).strip() == normalized(config.review.verdict_changes).strip())


def fields(body: str, config: Config) -> dict[str, str]:
    """The status block's fields, with half- or full-width colons."""
    count = len(config.status.fields)
    pairs = (re.split(r"[:：]", line, maxsplit=1) for line in body.splitlines()[:count])
    return {pair[0].strip(): pair[1].strip() for pair in pairs if len(pair) == 2}


def state_and_waiting(body: str, config: Config) -> tuple[str, str]:
    block, names = fields(body, config), config.status.fields
    return block.get(names[0], ""), block.get(names[1], "") if len(names) > 1 else ""


def executor_wakes(body: str, waiting_user: bool, config: Config) -> bool:
    state, waiting = state_and_waiting(body, config)
    status, roles = config.status, config.roles
    names = lambda *who: any(waiting_for(body, name, config) for name in who)
    kitchen = (roles.orchestrator, *designer_roles(config), roles.verifier)
    if waiting_user:
        return state in {status.blocked, status.done, status.waiting_on_design} or names(*kitchen)
    return state not in {status.in_progress, status.paused} or names(*kitchen, roles.user)


def waiting_for(body: str, role: str, config: Config) -> bool:
    _, waiting = state_and_waiting(body, config)
    if waiting.startswith(config.status.none):
        return False
    return named(waiting, role, config)


def design_request(body: str, config: Config) -> list[str]:
    state, _ = state_and_waiting(body, config)
    if state == config.status.paused:
        return []
    designers = [name for name in designer_roles(config) if waiting_for(body, name, config)]
    return designers or ([config.roles.designer] if state == config.status.waiting_on_design else [])


def role_wakes(body: str, role: str, config: Config) -> bool:
    who = signer(body, config)
    if who == config.roles.designer:
        return False
    if who == config.roles.executor:
        state, _ = state_and_waiting(body, config)
        if state == config.status.paused:
            return False
        if waiting_for(body, role, config):
            return True
        if (state == config.status.waiting_on_design
                and not any(waiting_for(body, name, config) for name in designer_roles(config))
                and role_variants(role, config) & role_variants(config.roles.designer, config)):
            return True
        next_step = fields(body, config).get(config.status.fields[3], "") if len(config.status.fields) > 3 else ""
        return named(next_step, role, config, markers=handoff(config))
    return named(body, role, config, markers=("@", *handoff(config)), signature=True)


def handoff(config: Config) -> tuple[str, ...]:
    return tuple(normalized(marker) for marker in config.watch.handoff)


def summary(body: str, config: Config) -> str:
    """The status block's first two lines, or the first line when there is no block."""
    count, names = len(config.status.fields), config.status.fields[:2]
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    picked = [line for line in lines[:count] if line.startswith(names)] or lines[:1]
    return truncate("; ".join(picked), 160)


def collect(config: Config, repo: str, since: str, labels_since: str, seen: set[str],
            skip: set[int], role: str | None = None) -> list[tuple[str, str, bool]]:
    """(time, line, wakes) for every item after the given times; comment and PR times use `since`."""
    awaiting = config.labels.awaiting_user
    waiting = ({issue["number"] for issue in gh(f"repos/{repo}/issues?state=open&labels={awaiting}&per_page=100")}
               if role is None else set())
    verifier, user, executor = config.roles.verifier, config.roles.user, config.roles.executor
    found = []
    for comment in recent_comments(repo, since):
        number, body = issue_number(comment["issue_url"]), comment["body"]
        who = signer(body, config)
        if number in skip:
            continue
        if role is None and config.split and comment["created_at"] >= since:
            from dkitchen.outbound import PR_LINE
            for code, pull in PR_LINE.findall(body):
                found.append((comment["updated_at"], f"PR {code}#{pull} opened, recorded on #{number} "
                              f"{comment['html_url']}", True))
        if role is not None:
            if not role_wakes(body, role, config):
                continue
        elif not (who in {verifier, user} or (who == executor and executor_wakes(body, number in waiting, config))):
            continue
        kind = f"{who} comment" if comment["created_at"] >= since else f"{who} edited a comment"
        listed = who == verifier and role is None
        changes = listed and changes_verdict(body, config)
        note = (f" ({config.review.verdict_changes})" if changes else
                f" ({verifier.lower()} reports separately; for reference)" if listed else "")
        found.append((comment["updated_at"], f"#{number} {kind}{note}: {summary(body, config)} {comment['html_url']}",
                      changes or not listed))
    if role is None:
        for event in recent_events(repo, labels_since):
            label = (event.get("label") or {}).get("name", "")
            if event["event"] == "labeled" and label.startswith(config.labels.prefix) and event["issue"]["number"] not in skip:
                found.append((event["created_at"], f"#{event['issue']['number']} label +{label} {event['issue']['html_url']}", True))
        for pull in newer(f"repos/{repo}/pulls?state=all&sort=created&direction=desc", "created_at", since, pages=1):
            found.append((pull["created_at"], f"PR #{pull['number']} opened: {truncate(pull['title'], 80)} {pull['html_url']}", True))
        if config.split:
            found += outside_comments(config, since)
    # Times have one-second resolution: the boundary second is rechecked and its reported lines skipped.
    return sorted({item for item in found if item[1] not in seen})


def board_tickets(cells: list[str], sessions: Sessions, repo: str) -> set[int]:
    name = json.loads('"' + cells[0] + '"')
    number = sessions.issue_number(name, repo)
    return {number} if number is not None else {int(value) for value in re.findall(r"#(\d+)", cells[3])}


def board_running(output: str, sessions: Sessions = Sessions(), repo: str = "") -> set[int]:
    """Tickets with a running `ding run`, using template names before the board ISSUE column."""
    running = set()
    for line in output.splitlines():
        if not line.strip():
            break  # the unwrapped-process table follows a blank line
        cells = line.split("\t")
        if len(cells) >= 6 and cells[5] == "running":
            running.update(board_tickets(cells, sessions, repo))
    return running


def board_output(checkout: Path) -> str:
    # The ISSUE column is filled only for sessions of the repository in the current directory.
    result = subprocess.run([sys.executable, "-m", "dkitchen.ding", "board", "--no-issue-lookup"],
                            capture_output=True, text=True,
                            timeout=120, cwd=checkout)
    if result.returncode:
        raise RuntimeError(f"ding board failed: {truncate(result.stderr.strip(), 200)}")
    return result.stdout


def running_issues(checkout: Path, sessions: Sessions = Sessions(), repo: str = "") -> set[int]:
    return board_running(board_output(checkout), sessions, repo)


def tmux_issues(panes: str, repo: str = "") -> set[int]:
    """Tickets with a live tmux job: a pane still running something other than a shell. The ticket comes from
    issue<N> in the session name; a pane without it is a `ding launch` job, tied through its pid to the run registry
    and so to the launching session, whose tickets are those whose latest owner line names it."""
    running, unnamed = set(), set()
    for line in panes.splitlines():
        name, dead, command, pid = (line.split("|") + ["", "", ""])[:4]
        if dead != "0" or command in SHELLS:
            continue
        match = re.search(r"issue(\d+)", name)
        if match:
            running.add(int(match.group(1)))
        elif pid.isdigit():
            unnamed.add(int(pid))
    if unnamed:
        from dkitchen import ding
        sessions = {run["pid"]: run for run in ding.registered_runs() if run["pid"] in unnamed}
        threads = {run["thread_id"] for run in sessions.values() if ding.run_state(run) == "running"}
        if threads:
            owned = ding.issue_map(repo or None)
            for thread in threads:
                running |= owned.get(thread, set())
    return running


def tmux_panes() -> str:
    """`tmux list-panes` for all sessions; empty when no tmux server is running."""
    try:
        result = subprocess.run(["tmux", "list-panes", "-a", "-F",
                                 "#{session_name}|#{pane_dead}|#{pane_current_command}|#{pane_pid}"],
                                capture_output=True, text=True, timeout=30)
    except FileNotFoundError:
        return ""
    return result.stdout if result.returncode == 0 else ""


def open_issues(repo: str):
    page, seen = 1, set()
    while True:
        issues = gh(f"repos/{repo}/issues?state=open&per_page=100&page={page}")
        for issue in issues:
            if issue["number"] not in seen:
                seen.add(issue["number"])
                yield issue
        if len(issues) < 100:
            return
        page += 1


def comments_backwards(repo: str, issue: dict):
    for page in range((issue["comments"] + 99) // 100, 0, -1):
        yield from reversed(gh(f"repos/{repo}/issues/{issue['number']}/comments?per_page=100&page={page}"))


def label_suppresses(config: Config, repo: str, issue: dict, comment: dict) -> bool:
    labels = {label["name"] for label in issue["labels"] if label["name"].startswith(config.labels.prefix)}
    if config.labels.awaiting_user in {label["name"] for label in issue["labels"]}:
        return True
    if not labels:
        return False
    added = {}
    page = 1
    while True:
        events = gh(f"repos/{repo}/issues/{issue['number']}/events?per_page=100&page={page}")
        for event in events:
            name = (event.get("label") or {}).get("name")
            if event["event"] == "labeled" and name in labels:
                added[name] = max(added.get(name, ""), event["created_at"])
        if len(events) < 100:
            break
        page += 1
    return any(added.get(name, "") > comment["created_at"] for name in labels)


def answered_by(body: str, role: str, config: Config) -> bool:
    who = signer(body, config)
    first = normalized(next((line for line in body.splitlines() if line.strip()), ""))
    first = re.sub(r"^[\s#*>]+", "", first)
    if who == config.roles.designer:
        for prefix in sorted(config.designer_signatures, key=len, reverse=True):
            if first.startswith(normalized(prefix)):
                return bool(role_variants(role, config) & role_variants(signature_name(prefix, config), config))
    elif role_variants(role, config) & role_variants(who, config):
        return True
    return named(first, role, config, signature=True)


def named_prs(waiting: str, repo: str) -> set[int]:
    """The PRs of this repository a wait field names, as `PR #N`, `PRN`, `PR owner/name#N`, or a /pull/ link."""
    numbers = set()
    for match in PR_NAMED.finditer(normalized(waiting)):
        if match.group(1):
            numbers.add(int(match.group(1)))
        elif match.group(2) and match.group(2).lower() == repo.lower():
            numbers.add(int(match.group(3)))
        elif match.group(4) and match.group(4).lower() == repo.lower():
            numbers.add(int(match.group(5)))
    return numbers


def ticket_prs(config: Config, ticket: int, cache: dict) -> set[int]:
    """The code repo PRs the ticket's `PR:` lines record, read once per cache."""
    key = ("links", ticket)
    if key not in cache:
        from dkitchen.outbound import PR_LINE
        kitchen, code = config.kitchen_repo(), config.code_repo()
        issue = gh(f"repos/{kitchen}/issues/{ticket}")
        texts = [issue.get("body") or "", *(comment["body"] or "" for comment in comments_backwards(kitchen, issue))]
        cache[key] = {int(number) for text in texts for repo, number in PR_LINE.findall(text) if repo == code}
    return cache[key]


def own_pr(pr: dict, ticket: int) -> bool:
    """Whether the PR is the ticket's own: its body cites `#ticket` or the ticket's link, or its branch holds
    `issue<ticket>`."""
    body = pr.get("body") or ""
    branch = (pr.get("head") or {}).get("ref") or ""
    return bool(re.search(rf"(?<![0-9A-Za-z])#{ticket}(?!\d)|/issues/{ticket}(?!\d)", body)
                or re.search(rf"issue-?{ticket}(?!\d)", branch, re.IGNORECASE))


def finished_prs(waiting: str, ticket: int, config: Config, repo: str,
                 cache: dict[int, dict]) -> tuple[set[str], str]:
    """For a wait naming PRs: the roles whose rows it no longer needs, and a note for the rows it keeps.

    When every PR named is merged or closed and is the ticket's own, the review and merge are over: the orchestrator,
    the verifier, and each PR's `review:<NAME>` reviewer are dropped. When a finished PR belongs to another ticket,
    the wait is a dependency that is now ready, so every row stays, noted with what happened to that PR."""
    repo = config.code_repo()
    numbers = sorted(named_prs(waiting, repo))
    if not numbers:
        return set(), ""
    for number in numbers:
        if number not in cache:
            try:
                cache[number] = gh(f"repos/{repo}/pulls/{number}")
            except RuntimeError as error:
                if "404" not in str(error):
                    raise
                cache[number] = {"state": "open"}  # `PR #N` naming no PR: keep the wait as written
    prs = {number: cache[number] for number in numbers}
    finished = {number: pr for number, pr in prs.items() if pr.get("state") != "open"}
    own = ((lambda number, pr: number in ticket_prs(config, ticket, cache)) if config.split
           else (lambda number, pr: own_pr(pr, ticket)))
    if len(finished) == len(prs) and all(own(number, pr) for number, pr in prs.items()):
        roles = {config.roles.orchestrator, config.roles.verifier}
        for pr in prs.values():
            roles.update(label["name"][7:].strip() for label in pr.get("labels", [])
                         if label["name"].startswith("review:") and label["name"][7:].strip())
        return roles, ""
    return set(), "; ".join(f"PR #{number} {'merged' if pr.get('merged_at') else 'closed'}"
                            for number, pr in finished.items())


def unanswered_waits(config: Config, repo: str, minutes: float, skip: set[int], *,
                     roles: list[str] | None = None, design_fallback: bool = False) -> list[dict]:
    names = role_names(config) if roles is None else roles
    moment = datetime.now(timezone.utc)
    found, prs = [], {}
    for issue in open_issues(repo):
        if "pull_request" in issue or issue["number"] in skip or not issue["comments"]:
            continue
        answered = set()
        for comment in comments_backwards(repo, issue):
            who = signer(comment["body"], config)
            if who != config.roles.executor:
                answered.update(name for name in names if answered_by(comment["body"], name, config))
                if design_fallback and who == config.roles.designer:
                    # Existing watch reminders accept a reply from any designer role.
                    answered.update(set(names) & set(designer_roles(config)))
                if len(answered) == len(names):
                    break
                continue
            if state_and_waiting(comment["body"], config)[0] == config.status.paused:
                break
            implicit = design_request(comment["body"], config) if design_fallback else []
            elapsed = (moment - datetime.fromisoformat(comment["created_at"].replace("Z", "+00:00"))).total_seconds() / 60
            if elapsed > minutes:
                waiting = [name for name in names
                           if name not in answered and (waiting_for(comment["body"], name, config) or name in implicit)]
                done, note = (finished_prs(state_and_waiting(comment["body"], config)[1], issue["number"], config,
                                           repo, prs) if waiting else (set(), ""))
                for name in waiting:
                    if not any(role_variants(name, config) & role_variants(other, config) for other in done):
                        found.append({"ticket": issue["number"], "role": name, "minutes": elapsed,
                                      "summary": summary(comment["body"], config) + (f" ({note})" if note else ""),
                                      "url": comment["html_url"],
                                      "comment_id": comment["id"], "created_at": comment["created_at"]})
            break
    return sorted(found, key=lambda item: (item["created_at"], item["ticket"], item["role"]))


def pr_waits(config: Config, repo: str, skip: set[int]) -> list[dict]:
    """Open PRs of the code repo `repo` waiting on a review or a merge, judged by [merge] review_check.

    A shared code repo has none: its verdicts go on tickets and its team merges, so the tickets' own waits route it."""
    if config.shared or not config.merge.review_check:
        return []
    from dkitchen import orchestrate
    owner, name = repo.split("/", 1)
    query = """query($owner:String!, $name:String!, $endCursor:String) {
      repository(owner:$owner, name:$name) {
        defaultBranchRef { name }
        pullRequests(states:OPEN, first:100, after:$endCursor) {
          pageInfo { hasNextPage endCursor }
          nodes { number state isDraft baseRefName headRefOid updatedAt url
            labels(first:100) { nodes { name } pageInfo { hasNextPage } }
            commits(last:1) { nodes { commit { oid statusCheckRollup {
              contexts(first:100) { pageInfo { hasNextPage } nodes {
                ... on CheckRun { name status conclusion detailsUrl }
                ... on StatusContext { context state targetUrl }
              } }
            } } } }
          }
        }
      }
    }"""
    response = orchestrate.call(config, "gh", "api", "graphql", "--paginate", "--slurp",
                                "-f", f"query={query}", "-f", f"owner={owner}", "-f", f"name={name}")
    if response.returncode:
        raise RuntimeError(f"cannot read PR readiness: {response.stderr.strip()}")
    found = []
    for page in json.loads(response.stdout):
        if page.get("errors"):
            raise RuntimeError(f"cannot read PR readiness: {page['errors']}")
        repository = page["data"]["repository"]
        branch = repository["defaultBranchRef"]["name"]
        for pr in repository["pullRequests"]["nodes"]:
            if pr["number"] in skip:
                continue
            commit = pr["commits"]["nodes"][-1]["commit"]
            checks = {}
            if commit["oid"] != pr["headRefOid"]:
                raise RuntimeError(f"PR #{pr['number']} HEAD moved during readiness query")
            rollup = commit["statusCheckRollup"]
            contexts = rollup["contexts"] if rollup else {"nodes": [], "pageInfo": {"hasNextPage": False}}
            if contexts["pageInfo"]["hasNextPage"]:
                checks = orchestrate.head_checks(config, repo, pr["headRefOid"])
            else:
                for check in contexts["nodes"]:
                    if "context" in check:
                        key, state, url = check["context"], check["state"].lower(), check["targetUrl"]
                    else:
                        key, url = check["name"], check["detailsUrl"]
                        state = (check["conclusion"] or "pending").lower() if check["status"] == "COMPLETED" else "pending"
                    checks.setdefault(key, []).append((state, url))
            result = orchestrate.readiness(config, repo, pr, branch, checks)
            if pr["isDraft"] and result["review"] != "failure":
                continue
            if pr["labels"]["pageInfo"]["hasNextPage"]:
                raise RuntimeError(f"PR #{pr['number']} has too many labels to route its review safely")
            reviewers = [label["name"][7:].strip() for label in pr["labels"]["nodes"]
                         if label["name"].startswith("review:") and label["name"][7:].strip()]
            reviewer = reviewers[0] if reviewers else config.roles.verifier
            kind = "blocked"
            if result["ready"]:
                kind = "ready"
            elif result["review"] == "failure":
                kind = "review-failed"
            elif result["review"] in {"missing", "pending"}:
                kind = "review-missing"
            elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(pr["updatedAt"].replace("Z", "+00:00"))).total_seconds() / 60
            found.append({"ticket": pr["number"], "head": pr["headRefOid"], "kind": kind,
                          "role": reviewer if kind == "review-missing" else config.roles.orchestrator,
                          "minutes": elapsed, "created_at": pr["updatedAt"], "url": pr["url"],
                          "summary": kind + (": " + "; ".join(result["reasons"]) if result["reasons"] else ""),
                          "pending_only": result["pending_only"], "reasons": result["reasons"]})
    return found


def pr_wakes(config: Config, repo: str, role: str | None, reported: set[str], observed: dict,
             skip: set[int]) -> tuple[list[tuple[str, str, str]], dict]:
    found, pending = [], {}
    moment = now()
    target = role or config.roles.orchestrator
    orchestrator = bool(role_variants(target, config) & role_variants(config.roles.orchestrator, config))
    for item in pr_waits(config, repo, skip):
        kind = item["kind"]
        key = f"{item['ticket']}:{item['head']}:{kind}"
        since = observed.get(key, moment)
        pending[key] = since
        line = f"PR #{item['ticket']} {item['summary']}; waiting on {item['role']} {item['url']}"
        if (not (kind == "blocked" and item["pending_only"]) and key not in reported and
                role_variants(target, config) & role_variants(item["role"], config)):
            found.append((moment, line, key))
        elapsed = (datetime.fromisoformat(moment.replace("Z", "+00:00")) -
                   datetime.fromisoformat(since.replace("Z", "+00:00"))).total_seconds() / 60
        backstop = key + ":overdue"
        if (orchestrator and kind in {"ready", "review-missing", "blocked"} and config.watch.design_answer_minutes
                and elapsed > config.watch.design_answer_minutes and backstop not in reported):
            found.append((moment, line + f"; overdue for {elapsed:.0f} minutes", backstop))
    return found, pending


def unrouted_waits(config: Config, repo: str, checkout: Path, reported: set[int],
                   skip: set[int]) -> list[tuple[str, str, int]]:
    if not config.watch.unrouted_wait_minutes:
        return []
    cutoff = stamp(datetime.now(timezone.utc) - timedelta(minutes=config.watch.unrouted_wait_minutes))
    candidates = []
    for issue in open_issues(repo):
        if "pull_request" in issue or issue["number"] in skip or not issue["comments"]:
            continue
        latest = None
        for comment in comments_backwards(repo, issue):
            latest = latest or comment
            if signer(comment["body"], config) != config.roles.executor:
                continue
            state, waiting = state_and_waiting(comment["body"], config)
            if (state == config.status.in_progress and waiting and not waiting.startswith(config.status.none)
                    and not any(named(waiting, name, config) for name in role_names(config))
                    and comment["id"] not in reported
                    and max(latest.get("updated_at", latest["created_at"]),
                            comment.get("updated_at", comment["created_at"])) < cutoff):
                candidates.append((issue, comment))
            break
    running = running_issues(checkout, config.sessions, repo) | tmux_issues(tmux_panes(), repo) if candidates else set()
    return [(comment["created_at"], f"#{issue['number']} unrouted wait for over "
             f"{config.watch.unrouted_wait_minutes:g} minutes, with no running ding run or tmux job: "
             f"{summary(comment['body'], config)} {comment['html_url']}", comment["id"])
            for issue, comment in candidates if issue["number"] not in running]


def stalled(config: Config, repo: str, checkout: Path, hours: float, skip: set[int]) -> list[dict]:
    """Lines that name no wait yet have not moved for `hours`: open draft PRs not updated, and open tickets whose
    latest executor status is in progress with no wait, that nobody has updated since, and that have no running
    `ding run` or live tmux job (the same test as stale checks; a long job is quiet by design). Oldest first."""
    if not hours:
        return []
    moment = datetime.now(timezone.utc)
    cutoff = stamp(moment - timedelta(hours=hours))
    age = lambda updated: (moment - datetime.fromisoformat(updated.replace("Z", "+00:00"))).total_seconds() / 60
    found = []
    page = 1
    # In a split kitchen the drafts are the code repo's, and only those the kitchen's account opened; ticket numbers
    # to skip name kitchen issues, not code repo PRs.
    code, mine = config.code_repo(), viewer() if config.split else None
    pr_skip = set() if config.split else skip
    while True:
        batch = gh(f"repos/{code}/pulls?state=open&sort=updated&direction=asc&per_page=100&page={page}")
        pulls = batch if mine is None else [pull for pull in batch if (pull.get("user") or {}).get("login") == mine]
        found += [{"ticket": pull["number"], "pr": True, "kind": "stalled", "role": config.roles.orchestrator,
                   "minutes": age(pull["updated_at"]), "created_at": pull["updated_at"], "url": pull["html_url"],
                   "summary": f"draft: {truncate(pull['title'], 120)}",
                   **({"ref": f"{code}#{pull['number']}"} if config.split else {})}
                  for pull in pulls if pull["updated_at"] < cutoff and pull.get("draft") and pull["number"] not in pr_skip]
        if any(pull["updated_at"] >= cutoff for pull in batch) or len(batch) < 100:
            break
        page += 1
    candidates = [issue for issue in open_issues(repo)
                  if "pull_request" not in issue and issue["number"] not in skip and issue["comments"]
                  and issue["updated_at"] < cutoff
                  and not any(label["name"] == config.labels.awaiting_user for label in issue["labels"])]
    running = running_issues(checkout, config.sessions, repo) | tmux_issues(tmux_panes(), repo) if candidates else set()
    for issue in candidates:
        if issue["number"] in running:
            continue
        last = next((comment for comment in comments_backwards(repo, issue)
                     if signer(comment["body"], config) == config.roles.executor), None)
        if last is None:
            continue
        state, waiting = state_and_waiting(last["body"], config)
        if state == config.status.in_progress and (not waiting or waiting.startswith(config.status.none)):
            found.append({"ticket": issue["number"], "pr": False, "kind": "stalled",
                          "role": config.roles.orchestrator, "minutes": age(issue["updated_at"]),
                          "created_at": issue["updated_at"], "url": last["html_url"],
                          "summary": summary(last["body"], config)})
    return sorted(found, key=lambda item: (item["created_at"], item["ticket"]))


def stalled_line(item: dict) -> str:
    return (f"{'PR ' if item['pr'] else ''}{item.get('ref', '#' + str(item['ticket']))} stalled, not updated for {item['minutes'] / 60:.0f} hours: "
            f"{item['summary']} {item['url']}")


def waits(args, config: Config) -> int:
    names = role_names(config)
    if args.role is not None:
        names = [name for name in names if role_variants(name, config) & role_variants(args.role, config)]
    minutes = config.watch.design_answer_minutes if args.minutes is None else args.minutes
    found = unanswered_waits(config, config.repository(), minutes, set(), roles=names) if names else []
    found += [item for item in pr_waits(config, config.code_repo(), set())
              if item["minutes"] > minutes and (args.role is None or
                 role_variants(args.role, config) & role_variants(item["role"], config))]
    found.sort(key=lambda item: (item["created_at"], item["ticket"], item["role"]))
    quiet = (stalled(config, config.repository(), config.root, args.stalled_hours, set())
             if args.role is None or role_variants(args.role, config)
             & role_variants(config.roles.orchestrator, config) else [])
    if args.json:
        print(json.dumps([{**item, "station": item["role"]} for item in found + quiet], ensure_ascii=False))
    else:
        for item in found:
            print(f"{'PR ' if 'head' in item else ''}#{item['ticket']} waiting on {item['role']} for {item['minutes']:.0f} minutes: "
                  f"{item['summary']} {item['url']}")
        if quiet:
            print("stalled:")
            for item in quiet:
                print(stalled_line(item))
    return 0


def unanswered_design(config: Config, repo: str, reported: set[int], skip: set[int]) -> list[tuple[str, str, int]]:
    if config.watch.design_answer_minutes == 0:
        return []
    designers = designer_roles(config)
    found = {}
    for item in unanswered_waits(config, repo, config.watch.design_answer_minutes, skip,
                                 roles=[*designers, config.roles.verifier], design_fallback=True):
        if item["comment_id"] not in reported:
            found.setdefault(item["comment_id"], (item, []))[1].append(item["role"])
    return [(item["created_at"], f"#{item['ticket']} waiting on {', '.join(names)} for {item['minutes']:.0f} minutes "
             f"with no {'designer' if all(name in designers for name in names) else 'role'} reply: "
             f"{item['summary']} {item['url']}", item["comment_id"]) for item, names in found.values()]


def stale(config: Config, repo: str, checkout: Path, hours: float, reported: set[int],
          skip: set[int]) -> list[tuple[str, str, int]]:
    """(time, line, comment id) for in-progress tickets whose executor has gone quiet."""
    cutoff = stamp(datetime.now(timezone.utc) - timedelta(hours=hours))
    candidates = [issue for issue in open_issues(repo)
                  if "pull_request" not in issue and issue["number"] not in skip and issue["comments"]
                  and issue["updated_at"] < cutoff
                  and not any(label["name"] == config.labels.awaiting_user for label in issue["labels"])]
    running = running_issues(checkout, config.sessions, repo) | tmux_issues(tmux_panes(), repo) if candidates else set()
    found = []
    for issue in candidates:
        if issue["number"] in running:
            continue
        last = gh(f"repos/{repo}/issues/{issue['number']}/comments?per_page=1&page={issue['comments']}")[-1]
        if (last["id"] not in reported and signer(last["body"], config) == config.roles.executor
                and state_and_waiting(last["body"], config)[0] == config.status.in_progress
                and not label_suppresses(config, repo, issue, last)):
            found.append((last["created_at"], f"#{issue['number']} executor silent for over {hours:g} hours, with no "
                                              f"running ding run or tmux job: {summary(last['body'], config)} "
                                              f"{last['html_url']}", last["id"]))
    return found


def idle(config: Config, repo: str, checkout: Path, observed: dict, reported: set[int],
         skip: set[int]) -> tuple[list[tuple[str, str, int]], dict]:
    """Idle in-progress executors, and first-observation times when board has no session update time."""
    if config.watch.idle_minutes == 0:
        return [], {}
    issues = [issue for issue in open_issues(repo)
              if "pull_request" not in issue and issue["number"] not in skip and issue["comments"]
              and not any(label["name"] == config.labels.awaiting_user for label in issue["labels"])]
    if not issues:
        return [], {}
    output = board_output(checkout)
    sessions = {}
    for line in output.splitlines()[1:]:
        if not line.strip():
            break
        cells = line.split("\t")
        if len(cells) >= 6:
            for number in board_tickets(cells, config.sessions, repo):
                sessions.setdefault(number, []).append(cells[2])
    running = board_running(output, config.sessions, repo) | tmux_issues(tmux_panes(), repo)
    moment = datetime.now(timezone.utc)
    found, pending = [], {}
    for issue in issues:
        number = issue["number"]
        if (number in running or not sessions.get(number)
                or any(status not in {"idle", "notLoaded"} for status in sessions[number])):
            continue
        last = next((comment for comment in comments_backwards(repo, issue)
                     if signer(comment["body"], config) == config.roles.executor), None)
        if (last is None or last["id"] in reported
                or state_and_waiting(last["body"], config)[0] != config.status.in_progress
                or label_suppresses(config, repo, issue, last)):
            continue
        previous = observed.get(str(number), {})
        since = previous.get("since") if previous.get("comment_id") == last["id"] else None
        # Board exposes no session update time; persist when all idle conditions were first observed.
        since = since or stamp(moment)
        pending[str(number)] = {"comment_id": last["id"], "since": since}
        began = max(datetime.fromisoformat(since.replace("Z", "+00:00")),
                    datetime.fromisoformat(last.get("updated_at", last["created_at"]).replace("Z", "+00:00")))
        minutes = (moment - began).total_seconds() / 60
        if minutes > config.watch.idle_minutes:
            found.append((stamp(moment), f"#{number} executor idle for {minutes:.0f} minutes while still in progress, "
                                        f"with no running ding run or tmux job: {summary(last['body'], config)} "
                                        f"{last['html_url']}", last["id"]))
    return found, pending


def missing_waiters(config: Config, repo: str, reported: set[int], skip: set[int]) -> list[tuple[str, str, int]]:
    """In-progress tickets whose latest owner is a Claude Code session that has kept no inbox waiter for a while.

    Without a waiter, ding messages wait unread and task-exit wakes reach no one. Only sessions that claimed a ticket
    on this host are checked, through the ticket `ding claim` recorded; the watch cannot see waiters elsewhere.
    """
    if not config.watch.executor_listener_minutes:
        return []
    from dkitchen.ding import owner_references
    moment = time.time_ns()
    found = []
    for entry in inbox.sessions():
        minutes = inbox.silent_minutes(entry, moment)
        ticket = re.fullmatch(r"(.+)#([1-9][0-9]*)", entry.get("ticket") or "")
        if (minutes is None or not config.watch.executor_listener_minutes < minutes <= WAITER_LOOKBACK_DAYS * 1440
                or not ticket or ticket[1].lower() != repo.lower() or int(ticket[2]) in skip):
            continue
        try:
            issue = gh(f"repos/{repo}/issues/{ticket[2]}")
            if (issue.get("state") != "open" or "pull_request" in issue or not issue["comments"]
                    or any(label["name"] == config.labels.awaiting_user for label in issue["labels"])):
                continue
            last, owner = None, None
            for comment in comments_backwards(repo, issue):
                if last is None and signer(comment["body"], config) == config.roles.executor:
                    last = comment
                owner = owner or next(reversed(owner_references(comment["body"])), None)
                if last is not None and owner is not None:
                    break
        except (RuntimeError, ValueError, KeyError, subprocess.TimeoutExpired) as error:
            # One unreadable ticket in an old record must not stop the watch.
            print(f"ding: could not check #{ticket[2]} for Claude Code session {entry['id']}: {error}", file=sys.stderr)
            continue
        owner = owner or next(reversed(owner_references(issue.get("body"))), None)
        if (last is None or owner != inbox.target(entry["id"]) or last["id"] in reported
                or state_and_waiting(last["body"], config)[0] != config.status.in_progress
                or label_suppresses(config, repo, issue, last)):
            continue
        line = (f"#{issue['number']} Claude Code executor {entry['id']} has run no `ding inbox --wait` for "
                f"{minutes:.0f} minutes while in progress, so ding messages and task-exit wakes cannot reach it "
                f"until it starts one: {summary(last['body'], config)} {last['html_url']}")
        found.append((now(), line, last["id"]))
    return found


def finished_tickets(config: Config, repo: str, since: str, skip: set[int]) -> dict[int, tuple[str, str, set[str]]]:
    """Tickets that got an executor `done` status or were closed since `since`: number -> (time, link, trigger ids).

    Reads the comment and event listings the poll's `collect` already fetched."""
    found: dict[int, tuple[str, str, set[str]]] = {}

    def add(number: int, moment: str, url: str, trigger: str):
        old = found.get(number, (moment, url, set()))
        found[number] = (min(old[0], moment), old[1], old[2] | {trigger})

    for comment in recent_comments(repo, since):
        number, body = issue_number(comment["issue_url"]), comment["body"]
        if (number not in skip and signer(body, config) == config.roles.executor
                and state_and_waiting(body, config)[0] == config.status.done):
            add(number, comment["updated_at"], comment["html_url"], f"comment {comment['id']}")
    for event in recent_events(repo, since):
        issue = event.get("issue") or {}
        if event["event"] == "closed" and "pull_request" not in issue and issue.get("number") not in skip:
            add(issue["number"], event["created_at"], issue["html_url"], f"event {event['id']}")
    return found


def waiting_tickets(waiting: str) -> set[int]:
    """The tickets a Waiting on field names as `#N`; a PR (`PR #N`, a pull URL) or another repo's `repo#N` is not one."""
    return {int(number) for number in TICKET_NAMED.findall(PR_NAMED.sub(" ", waiting))}


def waiters(config: Config, repo: str, targets: set[int], skip: set[int]) -> list[tuple[int, int]]:
    """(waiting ticket, awaited ticket) for open tickets whose latest executor status waits on one of `targets`."""
    found = []
    for issue in open_issues(repo):
        if "pull_request" in issue or issue["number"] in skip or not issue["comments"]:
            continue
        last = next((comment for comment in comments_backwards(repo, issue)
                     if signer(comment["body"], config) == config.roles.executor), None)
        if last is None:
            continue
        state, waiting = state_and_waiting(last["body"], config)
        if state == config.status.paused or waiting.startswith(config.status.none):
            continue
        found += [(issue["number"], number) for number in sorted(waiting_tickets(waiting) & targets - {issue["number"]})]
    return found


def finished_waits(config: Config, repo: str, since: str, reported: set[str], checked: set[str],
                   skip: set[int]) -> list[tuple[str, str, str]]:
    """(time, line, "M>N") for each open ticket M whose latest executor status waits on #N, once #N is done or closed.

    The open tickets are read only for a finished ticket not yet in `checked`; one that no one waited on is added
    to `checked`, so the open tickets are not read again for it. A pair in `reported` is not found again."""
    finished = {number: item for number, item in finished_tickets(config, repo, since, skip).items()
                if not item[2] <= checked}
    if not finished:
        return []
    found = [(finished[number][0], f"#{waiting} is waiting on #{number}, which just finished {finished[number][1]}",
              f"{waiting}>{number}")
             for waiting, number in waiters(config, repo, set(finished), skip) if f"{waiting}>{number}" not in reported]
    named = {int(key.split(">")[1]) for _, _, key in found}
    for number, (_, _, triggers) in finished.items():
        if number not in named:
            checked |= triggers
    return found


def job_label(run: dict) -> str:
    return f"{Path(run['progress']).parent.name}/{Path(run['progress']).name}" if "progress" in run else f"run {run['run_id'][:8]}"


def job_tickets(runs: list[dict], repo: str) -> dict[str, str]:
    """Ticket text for each run's thread, from the registry's launching session and the tickets it owns, as
    `tmux_issues` ties them. One GitHub read, made only when a job is being reported."""
    from dkitchen import ding
    owned = ding.issue_map(repo or None)
    return {run["run_id"]: ", ".join(f"#{number}" for number in sorted(owned.get(run["thread_id"], set())))
            or "no ticket found" for run in runs}


def live_runs(runs: list[dict]) -> list[dict]:
    from dkitchen import ding
    alive = []
    for run in runs:
        try:
            os.kill(run["pid"], 0)
        except ProcessLookupError:
            continue
        except PermissionError:
            pass
        if ding.run_state(run) == "running":
            alive.append(run)
    return alive


def stalled_jobs(config: Config, repo: str, reported: set[str], moment: float) -> list[tuple[str, str, str]]:
    """(time, line, "run_id@updated") for each running `ding launch --progress` job whose progress file, still
    `running`, has not changed for [watch] stale_minutes (and for the board's STALE time). The key holds the file's
    update time, so a job that moves and stalls again is a new stall. Reads local files only; GitHub is read only
    to name the ticket of a job being reported."""
    from dkitchen import ding
    if config.watch.stale_minutes == 0:
        return []
    limit = max(config.watch.stale_minutes * 60, ding.STALE_PROGRESS)
    found = []
    for run in ding.registered_runs():
        if "progress" not in run:
            continue
        try:
            data = json.loads(Path(run["progress"]).read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError):
            continue
        if not isinstance(data, dict) or data.get("state") != "running":
            continue
        age = ding.progress_age(data, moment)
        key = f"{run['run_id']}@{data['updated']['utc']}" if age is not None else ""
        if age is None or age <= limit or key in reported:
            continue
        found.append((run, key, age, ding.progress_summary(run["progress"], moment)))
    live = {run["run_id"] for run in live_runs([item[0] for item in found])}
    found = [item for item in found if item[0]["run_id"] in live]
    tickets = job_tickets([item[0] for item in found], repo) if found else {}
    return [(stamp(datetime.fromtimestamp(moment, timezone.utc)),
             f"{tickets[run['run_id']]}: job {job_label(run)} has made no progress for {int(age // 60)} minutes "
             f"(threshold {config.watch.stale_minutes:g}): {summary}", key)
            for run, key, age, summary in found]


def overrun_jobs(config: Config, repo: str, reported: set[str], moment: float) -> list[tuple[str, str, str]]:
    """(time, line, run_id) for each running `ding launch --expect-hours H` job that has run past
    [watch] overrun_factor x H, once. Reads local files only; GitHub is read only to name the ticket."""
    from dkitchen import ding
    if config.watch.overrun_factor == 0:
        return []
    found = []
    for run in ding.registered_runs():
        if "expect_hours" not in run or run["run_id"] in reported:
            continue
        hours = moment / 3600 - run["started_ns"] / 3.6e12
        if hours > config.watch.overrun_factor * run["expect_hours"]:
            found.append((run, hours))
    live = {run["run_id"] for run in live_runs([item[0] for item in found])}
    found = [item for item in found if item[0]["run_id"] in live]
    tickets = job_tickets([item[0] for item in found], repo) if found else {}
    return [(stamp(datetime.fromtimestamp(moment, timezone.utc)),
             f"{tickets[run['run_id']]}: job {job_label(run)} has run {hours:.1f} hours against its estimate of "
             f"{run['expect_hours']:g} (threshold {config.watch.overrun_factor:g}x); last progress: "
             f"{ding.progress_summary(run['progress'], moment) if 'progress' in run else 'none'}", run["run_id"])
            for run, hours in found]


def stalled_wakes(config: Config, repo: str, checkout: Path, hours: float, reported: dict[str, str],
                  skip: set[int]) -> tuple[list[tuple[str, str, str]], set[str]]:
    """Stalled items not reported in the last STALLED_EVERY_HOURS, and the keys of every item stalled now."""
    cutoff = stamp(datetime.now(timezone.utc) - timedelta(hours=STALLED_EVERY_HOURS))
    found, current = [], set()
    for item in stalled(config, repo, checkout, hours, skip):
        key = f"{'PR ' if item['pr'] else ''}{item.get('ref', '#' + str(item['ticket']))}"
        current.add(key)
        if reported.get(key, "") < cutoff:
            found.append((item["created_at"], stalled_line(item), key))
    return found, current


def default_state(repo: str, role: str | None = None) -> Path:
    state = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
    suffix = ".for-" + quote(role, safe="") if role is not None else ""
    return state / "ding/watch" / f"{repo.replace('/', '-')}{suffix}.json"


def holder_check(config: Config, repo: str, watched: str | None):
    """A check that returns why the calling session must not watch this role, or None; warns once when it can't tell.

    A watch belongs to the session that took the role with `ding role take`. Nothing is checked for a NAME that is
    not a standing role (the orchestrator, a designer line, or the verifier).
    """
    from dkitchen import roles
    role = roles.canonical(watched if watched is not None else config.roles.orchestrator, config)
    caller = inbox.current_session()
    if role is None:
        return lambda: None
    if caller is None:
        print(f"ding: no Claude Code or Codex session id here, so the holder of {role} is not checked",
              file=sys.stderr)
        return lambda: None
    warned = False

    def moved() -> str | None:
        nonlocal warned
        record = roles.holder(role, repo)
        if record is None:
            if not warned:
                print(f"ding: nobody has taken {role}; its session runs `ding role take {role}`", file=sys.stderr)
                warned = True
            return None
        if (record.get("kind"), record["id"]) == caller:
            return None
        return f"role {role} is held by {record['id']} since {record.get('taken_at')}"
    return moved


def watch(args, config: Config) -> int:
    token = RECENT.set({})
    try:
        return watch_until_wake(args, config)
    finally:
        RECENT.reset(token)


def watch_until_wake(args, config: Config) -> int:
    try:
        discarded = os.path.samestat(os.fstat(sys.stdout.fileno()), os.stat(os.devnull))
    except (AttributeError, OSError, ValueError):
        discarded = False
    if discarded:
        print("ding: watch stdout is /dev/null; use a pipe or a file so its batch is not lost", file=sys.stderr)
        return 3
    repo = config.repository()
    role = getattr(args, "role", None)
    if role is not None and role_variants(role, config) & role_variants(config.roles.orchestrator, config):
        role = None
    collect_options = {"role": role} if role is not None else {}
    moved = holder_check(config, repo, role)
    if message := moved():
        print(f"ding: {message}; this watch is not started", file=sys.stderr)
        return 3
    path = args.state or default_state(repo, role)
    checkout = args.checkout or config.root
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_suffix(".lock").open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(f"ding: another watch is using {path}; stop it before starting a new one", file=sys.stderr)
        return 3
    started = now()
    state = (json.loads(path.read_text()) if path.exists()
             else {"since": args.since or started, "seen": [], "stale": []})
    since, seen, reported = state["since"], state["seen"], set(state.get("stale", []))
    seen = seen if isinstance(seen, dict) else dict.fromkeys(seen, since)
    observed, idle_reported = state.get("idle_observed", {}), set(state.get("idle_reported", []))
    design_reported = set(state.get("design_reported", []))
    unrouted_reported = set(state.get("unrouted_reported", []))
    waiter_reported = set(state.get("waiter_reported", []))
    wait_reported, wait_checked = set(state.get("wait_reported", [])), set()
    pr_reported, pr_observed = set(state.get("pr_reported", [])), state.get("pr_observed", {})
    stalled_reported = state.get("stalled_reported", {})
    job_stall_reported, job_overrun_reported = set(state.get("job_stall_reported", [])), set(state.get("job_overrun_reported", []))
    skip = set(args.skip_issue) | ({config.log.issue} if config.log.issue else set())
    # Label changes made while the orchestrator was handling the last batch are its own; skip them.
    labels_since = state.get("labels_since", max(since, started) if path.exists() else since)
    detail = (f"comments and PRs since {since}, labels since {labels_since}" if role is None
              else f"requests and handoffs to {role!r} since {since}")
    print(f"Watching {repo}{f' and its code repo {config.code_repo()}' if config.split else ''}: {detail}",
          file=sys.stderr)
    errors = 0
    next_stale = next_idle = 0.0 if role is None else float("inf")
    threshold = (config.watch.idle_minutes or config.watch.design_answer_minutes or config.watch.unrouted_wait_minutes
                 or config.watch.executor_listener_minutes)
    idle_every = min(threshold * 20, 900) if role is None and threshold else float("inf")
    while True:
        if message := moved():
            print(f"{message}; this watch exits without advancing its state")
            return 3
        polled = now()
        RECENT.get().clear()
        try:
            found = collect(config, repo, since, labels_since, seen, skip, **collect_options)
            pr_found, pr_pending = pr_wakes(config, config.code_repo(), role, pr_reported, pr_observed,
                                            set() if config.split else skip)
            quiet, idle_found, design_found, pending, stale_ids = [], [], [], observed, set()
            wait_found = finished_waits(config, repo, since, wait_reported, wait_checked, skip) if role is None else []
            moment = time.time()
            job_stall_found = stalled_jobs(config, repo, job_stall_reported, moment) if role is None else []
            job_overrun_found = overrun_jobs(config, repo, job_overrun_reported, moment) if role is None else []
            unrouted_found, waiter_found, stalled_found, stalled_current = [], [], [], None
            checked_at = time.monotonic()
            checked_stale, checked_idle = checked_at >= next_stale, checked_at >= next_idle
            if checked_stale:
                quiet = stale(config, repo, checkout, args.stale_hours, reported, skip)
                stale_ids = {id_ for _, _, id_ in quiet}
                stalled_found, stalled_current = stalled_wakes(config, repo, checkout, args.stalled_hours, stalled_reported, skip)
                quiet += stalled_found
            if checked_idle:
                idle_found, pending = idle(config, repo, checkout, observed, idle_reported, skip)
                design_found = unanswered_design(config, repo, design_reported, skip)
                quiet += [item for item in idle_found if item[2] not in {entry[2] for entry in quiet}]
                quiet += design_found
                unrouted_found = unrouted_waits(config, repo, checkout, unrouted_reported, skip)
                quiet += unrouted_found
                waiter_found = missing_waiters(config, repo, waiter_reported, skip)
                quiet += waiter_found
            quiet += pr_found + wait_found + job_stall_found + job_overrun_found
            if any(wakes for _, _, wakes in found) or quiet:
                if found:
                    time.sleep(args.settle)
                    polled = now()
                    RECENT.get().clear()
                    found = collect(config, repo, since, labels_since, seen, skip, **collect_options)
            errors = 0
        except (RuntimeError, OSError, ValueError, KeyError, subprocess.TimeoutExpired) as error:
            errors += 1
            print(f"{polled} poll failed {errors}/{args.max_errors}: {error}", file=sys.stderr)
            if errors >= args.max_errors:
                print(f"{errors} polls failed in a row; the watch exits without advancing its state. "
                      "Rerun the same command once fixed.")
                return 2
            time.sleep(min(args.interval, idle_every))
            continue
        if checked_stale:
            next_stale = time.monotonic() + args.stale_every
        if checked_idle:
            next_idle = checked_at + idle_every
        wakes = any(wakes for _, _, wakes in found) or bool(quiet)
        if stalled_current is not None:
            # Items no longer stalled are forgotten, so one that stalls again is reported at once.
            stalled_now = {key: stalled_reported[key] for key in stalled_current if key in stalled_reported}
            stalled_now.update({key: polled for _, _, key in stalled_found})  # any found item makes this poll wake
        else:
            stalled_now = stalled_reported
        changed = pending != observed or pr_pending != pr_observed or stalled_now != stalled_reported
        stalled_reported = stalled_now
        observed, pr_observed = pending, pr_pending
        if wakes:
            for _, line in sorted([(time_, line) for time_, line, _ in found] + [(time_, line) for time_, line, _ in quiet]):
                print(line)
            print(f"{len(found) + len(quiet)} items ({since} to {polled}). "
                  "After handling them, start the watch again with the same command.")
            state.pop("labels_since", None)
            # A line stamped after the poll stays in the next query window, so it stays seen until the clock passes it.
            lines = {**seen, **{line: time_ for time_, line, _ in found}}
            state.update(since=polled, seen={line: time_ for line, time_ in lines.items() if time_ >= polled},
                         stale=sorted(reported | stale_ids),
                         idle_reported=sorted(idle_reported | {id_ for _, _, id_ in idle_found}),
                         design_reported=sorted(design_reported | {id_ for _, _, id_ in design_found}),
                         unrouted_reported=sorted(unrouted_reported | {id_ for _, _, id_ in unrouted_found}),
                         waiter_reported=sorted(waiter_reported | {id_ for _, _, id_ in waiter_found}),
                         wait_reported=sorted(wait_reported | {key for _, _, key in wait_found}),
                         pr_reported=sorted(pr_reported | {key for _, _, key in pr_found}),
                         job_stall_reported=sorted(job_stall_reported | {key for _, _, key in job_stall_found}),
                         job_overrun_reported=sorted(job_overrun_reported | {key for _, _, key in job_overrun_found}))
        if changed and not wakes:
            state["labels_since"] = labels_since
        if wakes or changed:
            state["idle_observed"] = observed
            state["pr_observed"] = pr_observed
            state["stalled_reported"] = stalled_reported
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(state, ensure_ascii=False))
            tmp.replace(path)
        if wakes:
            return 0
        time.sleep(min(args.interval, max(0, next_stale - time.monotonic()),
                       max(0, next_idle - time.monotonic())))
