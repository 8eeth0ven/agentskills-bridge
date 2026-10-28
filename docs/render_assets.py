#!/usr/bin/env python3
"""Render README SVGs for visual review (optional Playwright dependency).

    python3 -m pip install playwright
    python3 -m playwright install chromium
    python3 docs/render_assets.py --out out/asset-previews

The SVGs themselves have no runtime dependencies and render directly on GitHub.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="Directory for PNG review copies")
    args = parser.parse_args()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        parser.error(f"Optional renderer unavailable: {error}. Install playwright and its chromium browser.")
    assets = Path(__file__).resolve().parent / "assets"
    args.out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        with playwright.chromium.launch() as browser:
            for source in sorted(assets.glob("*.svg")):
                svg = source.read_text(encoding="utf-8")
                size = re.search(r'viewBox="\d+ \d+ (\d+) (\d+)"', svg)
                if not size:
                    raise ValueError(f"Missing integer viewBox dimensions: {source}")
                width, height = map(int, size.groups())
                page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
                page.goto(source.resolve().as_uri(), wait_until="load")
                page.screenshot(path=str(args.out / f"{source.stem}.png"), omit_background=True)
                page.close()
                print(args.out / f"{source.stem}.png")


if __name__ == "__main__":
    main()
