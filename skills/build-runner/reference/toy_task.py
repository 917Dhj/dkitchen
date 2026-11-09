"""A toy task function for trying a runner: it fills a template per item, and sleeps or fails when the item asks."""

from __future__ import annotations

from pathlib import Path
import time

INPUTS = ["template.txt"]  # a text file a model would see: its content is part of the run identity


def run(item: dict, ctx) -> dict:
    time.sleep(item.get("sleep", 0))
    if item.get("fail"):
        raise ValueError(f"item {item['id']} fails on purpose")
    if item.get("stop"):
        from runner import StopRun

        raise StopRun("the service refused our key")
    text = Path("template.txt").read_text(encoding="utf-8").format(id=item["id"], **ctx.args)
    ctx.log.append({"event": "filled", "length": len(text)})
    return {"text": text, "correct": item.get("answer") == text}
