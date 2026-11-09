#!/usr/bin/env python3
"""Render kitchen templates into a repo's rule folder.

Usage: render.py --templates team[,night] [--modules run-budgets,model-text] --out docs/agents [--kitchen DIR]

Each build skill renders its own templates: `team` for build-team, `night` for build-night. Writes each chosen
template, plus the chosen modules' files, into --out, keeping each chosen module's marked text and dropping the
others', with every module marker removed. Then prints the AGENTS.md and CLAUDE.md pointer blocks, keeping only the
pointers whose `docs/agents/` file exists in --out, so the blocks always match what is installed, whichever skill
ran last. `<!-- fill: … -->` gaps are left in place for the skill to fill.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys

TEMPLATES = {"team": ("roles.md", "issue-tracker.md", "messaging.md", "long-running-jobs.md"),
             "night": ("unattended.md",)}
MODULES = {"run-budgets": ("team", "run-budgets.md"), "model-text": ("team", "model-text.md"),
           "artifacts": ("team", "artifacts.md")}
LINKED = {"unattended": "night"}   # marker names that follow a template set rather than a module
SECTION = re.compile(r"<!-- module:([\w-]+) -->(.*?)<!-- /module:\1 -->", re.S)
POINTER = re.compile(r"\(docs/agents/([\w.-]+\.md)(?:#[\w-]+)?\)")


def render(text: str, modules: set[str]) -> str:
    unknown = {name for name, _ in SECTION.findall(text)} - set(MODULES) - set(LINKED)
    if unknown:
        raise ValueError(f"unknown module markers: {', '.join(sorted(unknown))}")
    text = re.sub(r"^[ \t]*(<!-- /?module:[\w-]+ -->)[ \t]*\n", r"\1", text, flags=re.M)  # a marker line leaves no line
    text = SECTION.sub(lambda match: match.group(2) if match.group(1) in modules else "", text)
    if "<!-- module:" in text or "<!-- /module:" in text:
        raise ValueError("unbalanced module markers")
    return re.sub(r"\n{3,}", "\n\n", text)


def blocks(text: str, installed: set[str] | None = None) -> dict[str, str]:
    """The fenced Markdown blocks of agents-block.md, keyed by the heading above each.

    With `installed`, a line pointing at a `docs/agents/` file outside that set is dropped."""
    found = {heading: body.strip("\n") for heading, body in
             re.findall(r"^## (\S+)\n\n```markdown\n(.*?)^```", text, flags=re.S | re.M)}
    if installed is None:
        return found
    return {heading: "\n".join(line for line in body.splitlines()
                               if all(name in installed for name in POINTER.findall(line)))
            for heading, body in found.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--templates", required=True, help=f"comma-separated, from: {', '.join(TEMPLATES)}")
    parser.add_argument("--modules", default="", help=f"comma-separated, from: {', '.join(MODULES)}")
    parser.add_argument("--out", type=Path, required=True, help="folder for the rendered rules, such as docs/agents")
    parser.add_argument("--kitchen", type=Path, default=Path(__file__).resolve().parent,
                        help="the dkitchen kitchen/ folder (default: the one holding this script)")
    args = parser.parse_args()
    templates = {name.strip() for name in args.templates.split(",") if name.strip()}
    modules = {name.strip() for name in args.modules.split(",") if name.strip()}
    if not templates or templates - set(TEMPLATES):
        parser.error(f"--templates takes one or more of: {', '.join(TEMPLATES)}")
    if modules - set(MODULES):
        parser.error(f"unknown modules: {', '.join(sorted(modules - set(MODULES)))}")
    if {MODULES[name][0] for name in modules} - templates:
        parser.error("a module needs its template set: " + ", ".join(f"{name} needs {MODULES[name][0]}" for name in sorted(modules)))
    kept = modules | {marker for marker, owner in LINKED.items() if owner in templates}
    try:
        sources = [args.kitchen / group / name for group in TEMPLATES if group in templates for name in TEMPLATES[group]]
        sources += [args.kitchen / group / name for module, (group, name) in MODULES.items() if module in modules]
        args.out.mkdir(parents=True, exist_ok=True)
        for source in sources:
            (args.out / source.name).write_text(render(source.read_text(encoding="utf-8"), kept), encoding="utf-8")
            print(f"wrote {args.out / source.name}", file=sys.stderr)
        installed = {path.name for path in args.out.glob("*.md")}
        present = {module for module, (_, name) in MODULES.items() if name in installed}
        present |= {marker for marker, owner in LINKED.items() if set(TEMPLATES[owner]) <= installed}
        pointers = blocks(render((args.kitchen / "agents-block.md").read_text(encoding="utf-8"), present), installed)
        for heading, body in pointers.items():
            print(f"## {heading}\n\n{body}\n")
    except (OSError, ValueError) as error:
        print(f"render.py: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
