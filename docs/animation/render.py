#!/usr/bin/env python3
"""Render kitchen.html into animated WebPs and MP4s, in two layouts and two languages.

Usage: render.py [--out DIR] [--variants wide-en,wide-zh,tall-en,tall-zh] [--fps 12] [--ffmpeg PATH] [--img2webp PATH]

Needs Playwright with Chromium (`pip install playwright && playwright install chromium`), an ffmpeg
with libx264, and img2webp from libwebp. For each variant it writes into --out:

  wide-en  kitchen.webp and kitchen.mp4           960x540 lossless WebP for the README, 1920x1080 MP4
  wide-zh  kitchen-zh.webp and kitchen-zh.mp4     the same in Chinese, for README.zh-CN.md
  tall-en  kitchen-tall.mp4                       1080x1440 (3:4) for phone-first platforms
  tall-zh  kitchen-tall-zh.mp4

The wide MP4s are scaled 2x with nearest-neighbour, so the pixels stay sharp. The WebPs keep every
frame's exact colours and are smaller than a GIF. Copy them to docs/assets/ to publish them.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import tempfile

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
SIZES = {"wide": (960, 540), "tall": (1080, 1440)}


def frames(folder: Path, layout: str, lang: str, fps: float) -> None:
    width, height = SIZES[layout]
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": height})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto((HERE / "kitchen.html").as_uri() + f"?t=0&layout={layout}&lang={lang}")
        page.wait_for_selector("body[data-ready='1']", timeout=30000)
        canvas = page.locator("#kitchen")
        for i in range(int(page.evaluate("DURATION") * fps)):
            page.evaluate(f"renderAt({i / fps})")
            canvas.screenshot(path=str(folder / f"f{i:04d}.png"))
        browser.close()
    if errors:
        raise SystemExit("kitchen.html: " + "; ".join(errors))


def render(variant: str, out: Path, fps: float, ffmpeg: str, img2webp: str) -> list[Path]:
    layout, lang = variant.split("-")
    stem = "kitchen" + ("-tall" if layout == "tall" else "") + ("-zh" if lang == "zh" else "")
    written = []
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        frames(folder, layout, lang, fps)
        source = ["-framerate", str(fps), "-i", str(folder / "f%04d.png")]
        run = lambda *more: subprocess.run([ffmpeg, "-y", "-loglevel", "error", *source, *more], check=True)
        scale = "scale=1920:1080:flags=neighbor," if layout == "wide" else ""
        run("-vf", f"{scale}fps=24", "-c:v", "libx264", "-crf", "16", "-preset", "slow",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out / f"{stem}.mp4"))
        written.append(out / f"{stem}.mp4")
        if layout == "wide":
            pngs = sorted(str(path) for path in folder.glob("f*.png"))
            subprocess.run([img2webp, "-loop", "0", "-lossless", "-m", "4", "-d", str(round(1000 / fps)),
                            *pngs, "-o", str(out / f"{stem}.webp")], check=True, stdout=subprocess.DEVNULL)
            written.append(out / f"{stem}.webp")
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=Path("."), help="folder for the WebPs and MP4s")
    parser.add_argument("--variants", default="wide-en,wide-zh,tall-en,tall-zh")
    parser.add_argument("--fps", type=float, default=12)
    parser.add_argument("--ffmpeg", default="ffmpeg", help="an ffmpeg built with libx264")
    parser.add_argument("--img2webp", default="img2webp", help="img2webp from libwebp")
    args = parser.parse_args()
    variants = [v.strip() for v in args.variants.split(",") if v.strip()]
    unknown = [v for v in variants if v not in {"wide-en", "wide-zh", "tall-en", "tall-zh"}]
    if unknown:
        parser.error(f"unknown variants: {', '.join(unknown)}")
    args.out.mkdir(parents=True, exist_ok=True)
    for variant in variants:
        for path in render(variant, args.out, args.fps, args.ffmpeg, args.img2webp):
            print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
