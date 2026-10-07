"""Capture the README screenshots and replay GIF from a running dashboard.

Needs the server running with at least one finished run, plus:

    .venv/bin/pip install playwright pillow
    .venv/bin/python -m playwright install chromium
    .venv/bin/python scripts/screenshots.py            # latest finished run
    .venv/bin/python scripts/screenshots.py --run ID --trial ID
"""

from __future__ import annotations

import argparse
import io
import json
import re
import time
import urllib.request
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent.parent / "docs"
VIEWPORT = {"width": 1280, "height": 860}


def get(base: str, path: str):
    with urllib.request.urlopen(base + path) as resp:
        return json.load(resp)


def pick_trial(run: dict) -> str:
    """A passing trial with a few steps makes the most readable replay."""
    trials = [t for t in run["trials"] if t["steps"]]
    passing = [t for t in trials if t["status"] == "PASS" and 2 <= t["steps"] <= 8]
    pool = passing or trials
    return max(pool, key=lambda t: t["steps"])["id"]


def record_replay(page, path: Path, width: int = 1000) -> None:
    page.get_by_role("button", name="⟲ Replay").click()
    frames, times = [], []
    deadline = time.time() + 90
    while time.time() < deadline:
        times.append(time.time())
        png = page.screenshot()
        frame = Image.open(io.BytesIO(png)).convert("RGB")
        frame = frame.resize((width, int(frame.height * width / frame.width)), Image.LANCZOS)
        frames.append(frame.quantize(colors=128, method=Image.Quantize.MEDIANCUT))
        position = page.locator("text=/^\\d+\\/\\d+$/").first.inner_text()
        done, total = (int(x) for x in position.split("/"))
        if done == total:
            break
        time.sleep(0.15)
    # Each frame lasts as long as it really did, so the GIF plays at replay speed.
    durations = [int(1000 * (b - a)) for a, b in zip(times, times[1:])] + [2500]  # hold the last frame
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=durations, loop=0, optimize=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--run", help="run id (default: latest finished run)")
    parser.add_argument("--trial", help="trial id for the trial page and replay")
    args = parser.parse_args()

    run_id = args.run or next(r["id"] for r in get(args.base, "/api/runs") if r["status"] == "done")
    trial_id = args.trial or pick_trial(get(args.base, f"/api/runs/{run_id}"))
    OUT.mkdir(exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport=VIEWPORT, device_scale_factor=2, color_scheme="dark")

        page.goto(f"{args.base}/#/runs/{run_id}")
        page.wait_for_selector("text=Pass rate")
        page.screenshot(path=OUT / "run.png", full_page=True)

        page.goto(f"{args.base}/#/trials/{trial_id}")
        page.wait_for_selector("text=Trajectory")
        page.screenshot(path=OUT / "trial.png")

        small = browser.new_page(viewport=VIEWPORT, device_scale_factor=1, color_scheme="dark")
        small.goto(f"{args.base}/#/trials/{trial_id}")
        small.wait_for_selector("text=Trajectory")
        record_replay(small, OUT / "replay.gif")
        browser.close()

    for name in ("run.png", "trial.png", "replay.gif"):
        size = (OUT / name).stat().st_size
        print(f"docs/{name}: {size / 1024:.0f} KB")
    print(f"run {run_id}, trial {trial_id}")


if __name__ == "__main__":
    main()
