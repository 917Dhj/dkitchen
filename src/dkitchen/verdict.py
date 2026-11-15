"""Post the verifier's verdict on a ticket's run stage, then tell the ticket's executor.

`ding review --ticket N pass|changes --body-file FILE`: the draft's line 1 must open with the verifier's signature.
The comment is the draft with a verdict line (`[review] verdict_pass` or `verdict_changes`) after line 1; a `changes`
verdict also hands the ticket to its design line, so the orchestrator's watch and that designer's watch wake.
Then `[review] notify` goes to '#N' with `ding send`; `no_listener` counts as queued, and a failed notification
exits 1 but leaves the comment.
"""
from __future__ import annotations

import json
import re

from dkitchen import rule, truncate, watch
from dkitchen.config import Config
from dkitchen.orchestrate import call, fail

FIRST_LINES = 3  # where a ticket names its design line: the second line of the layout, after an optional parent line


def comment_body(draft: str, verdict: str, config: Config, design: str | None) -> str:
    """The draft with the verdict line, and on `changes` the handoff to the design line, after line 1."""
    first, _, rest = draft.partition("\n")
    lines = [first, config.review.verdict(verdict)]
    if design is not None:
        lines.append(f"{config.watch.handoff[0]}{design}")
    return "\n".join(lines) + ("\n" + rest if rest else "\n")


def named_designer(text: str, config: Config) -> str | None:
    """The design line named first in `text`, by its name or an alias."""
    designers = watch.designer_roles(config)
    variants = {variant: name for name in designers for variant in watch.role_variants(name, config)}
    others = {variant for name in watch.role_names(config) for variant in watch.role_variants(name, config)}
    pattern = "|".join(map(re.escape, sorted(set(variants) | others, key=len, reverse=True)))
    for match in re.finditer(pattern, watch.normalized(text)):
        if match.group() in variants:
            return variants[match.group()]
    return None


def read_issue(config: Config, repo: str, ticket: int) -> dict:
    result = call(config, "gh", "api", f"repos/{repo}/issues/{ticket}")
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"cannot read {repo}#{ticket}")
    return json.loads(result.stdout)


def design_line(config: Config, repo: str, issue: dict) -> str:
    """The design line that owns the ticket: named in its first lines, else in its parent's, else the designer."""
    parent = re.compile(re.escape(config.sessions.parent).replace(re.escape("{parent}"), r"#?(\d+)"))
    for _ in range(2):
        lines = [line for line in (issue.get("body") or "").splitlines() if line.strip()][:FIRST_LINES]
        found = named_designer("\n".join(lines), config)
        if found is not None:
            return found
        up = parent.match(lines[0].strip()) if lines else None
        if up is None:
            break
        issue = read_issue(config, repo, int(up.group(1)))
    return config.roles.designer


def review_ticket(args, config: Config) -> int:
    ticket, verdict = args.ticket, args.verdict
    signature = config.roles.signature(config.roles.verifier)
    try:
        draft = args.body_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        return fail(str(error))
    if not draft.strip():
        return fail(f"{args.body_file} is empty")
    if not draft.startswith(signature):
        return fail(f"{args.body_file}: line 1 must start with {signature!r}, not "
                    f"{truncate(draft.split(chr(10))[0], 40)!r}. Nothing posted")
    try:
        repo = config.repository()
        issue = read_issue(config, repo, ticket)
        if "pull_request" in issue:
            return fail(f"#{ticket} is a PR, not a ticket; review a PR with `ding review {ticket} <SHA> {verdict} "
                        "--body-file FILE`, which also writes the commit status the merge needs. Nothing posted")
        design = design_line(config, repo, issue) if verdict == "changes" else None
    except (RuntimeError, ValueError, KeyError, TypeError) as error:
        return fail(f"{error}. Nothing posted")
    body = comment_body(draft, verdict, config, design)
    result = call(config, "gh", "issue", "comment", str(ticket), "--repo", repo, "--body", body)
    url = result.stdout.strip()
    if result.returncode:
        return fail(f"comment failed: {result.stderr.strip()}")
    if not rule.COMMENT_URL.match(url):
        return fail(f"gh did not print a comment link (got {url!r}); look at the ticket before posting again")
    print(url)
    template, line = config.review.notify, config.review.verdict(verdict)
    message = template.format(ticket=ticket, url=url, verdict=line, first_line=rule.first_line(draft))
    if "{first_line}" not in template:
        message += "\n" + rule.first_line(draft)
    return rule.deliver(f"#{ticket}", config.roles.verifier, message, url)
