#!/usr/bin/env python3
"""Create .env from .env.example with a fresh random API token, and seed the demo sandbox.

Safe to re-run: an existing .env is never overwritten.
"""

from __future__ import annotations

import os
import secrets
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    env, example = ROOT / ".env", ROOT / ".env.example"
    if env.exists():
        print(".env already exists - leaving it untouched.")
    else:
        token = secrets.token_urlsafe(32)
        content = example.read_text(encoding="utf-8").replace("STARK_API_TOKEN=", f"STARK_API_TOKEN={token}", 1)
        fd = os.open(env, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)  # never world-readable, even briefly
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        print("Created .env with a new random STARK_API_TOKEN (file permissions 600).")
        print("Paste this token into the dashboard's Connect screen:\n")
        print(f"    {token}\n")
    seed = ROOT / "sandbox"
    guide = seed / "brand-guidelines.md"
    if not guide.exists():
        seed.mkdir(parents=True, exist_ok=True)
        guide.write_text(
            "# Brand guidelines (example - replace with your own)\n\n"
            "- Voice: warm, plain-spoken, confident. No slang, no hype words like 'revolutionary'.\n"
            "- Audience: indie makers and small teams.\n"
            "- Always: alt text on images, #ad on sponsored posts, link rules for any giveaway.\n"
            "- Never: comment on politics or tragedies, mock competitors, promise results.\n"
            "- Platforms: Bluesky and Mastodon (live), LinkedIn (weekly), Instagram (visual).\n")
        print("Seeded sandbox/brand-guidelines.md (edit it: every agent can read it).")
    demo = seed / "test-folder"
    if not demo.exists():
        demo.mkdir(parents=True)
        files = {
            "launch-notes.md": "# Launch week\n- Teaser Monday\n- Launch post Wednesday\n- Recap Friday\n",
            "content-calendar.csv": "date,platform,topic\n2026-11-02,bluesky,teaser\n2026-11-04,linkedin,launch\n",
            "hero-shot.jpg": "(placeholder image bytes for the organisation demo)\n",
            "media-kit.pdf": "(placeholder PDF for the organisation demo)\n",
            "teaser-cut.mp4": "(placeholder video for the organisation demo)\n",
            "old-assets.zip": "(placeholder archive)\n",
            "post-ideas.txt": "behind the scenes\ncustomer story\npoll: this or that\n",
        }
        for name, body in files.items():
            (demo / name).write_text(body)
        print(f"Seeded demo files in {demo.relative_to(ROOT)}/")
    arch = seed / "architecture.md"
    if not arch.exists() and (ROOT / "docs" / "ARCHITECTURE.md").exists():
        shutil.copy(ROOT / "docs" / "ARCHITECTURE.md", arch)
        print("Copied docs/ARCHITECTURE.md into the sandbox for the Ultron critique demo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
