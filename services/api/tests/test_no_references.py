"""House rule: the project text names only the services STARK OS actually connects to. Names of other products
and websites (competitors, inspirations, third-party apps used only as examples) are not allowed anywhere.

The blocked names are stored as hashes so this file does not mention them either. Words are compared in lower
case, alone and in pairs, so "Some Product" and "some.product" are both caught."""

from __future__ import annotations

import hashlib
import re
import subprocess

from stark.config import REPO_ROOT

BLOCKED = {
    "021a150783874d5b", "15dd0e4f84441007", "18356f2ba555c78d", "1a9656a40206b8de", "32f2ddec15bcdab3",
    "3cab3406e6cf9c51", "3d36ac3f3d6f241b", "40c57bb53c07338b", "42e6192aa2bb9564", "4ec8b0dd356098dd",
    "55f430c031f1f2f7", "636396f02b6571e4", "645ac5e69146d2a2", "6714ac9b8f4cd047", "691351fd94f25a49",
    "6e15c2e9bc23ebaf", "738e22f0acab814c", "795b104abe3e4134", "7f909b6b8f9ca6cd", "84b6f03ebe1a7594",
    "867714c871ab0b42", "8a72266588ef612e", "8f74ecab43053394", "91b6da07adf530f8", "995945426cf67659",
    "b18317a46cb36484", "bb56ce64d6ccc4a6", "bc1e6f988876d73c", "bcdd9220f8626357", "d21800cafd9b39d7",
    "d8b396c9cc79cbe4", "d90d9a8b308f63f5", "e473f24d4325d51a", "e63da6f93be1070d", "eb8f1ec0404dcb51",
    "ec53b05ca72354dd", "fc8932c70118a71e",
}
SKIP = re.compile(r"(\.(png|gif|jpe?g|ico|webp|woff2?|bundle)|package-lock\.json)$")
WORD = re.compile(r"[a-z0-9]+(?:\.[a-z0-9]+)*")


def _h(w: str) -> str:
    return hashlib.sha256(w.encode()).hexdigest()[:16]


def _files() -> list[str]:
    try:
        out = subprocess.run(["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return []
    return [f for f in out.splitlines() if not SKIP.search(f)]


def test_no_third_party_references():
    found = []
    for f in _files():
        try:
            text = (REPO_ROOT / f).read_text(encoding="utf-8").lower()
        except (OSError, UnicodeDecodeError):
            continue
        for n, line in enumerate(text.splitlines(), 1):
            words = WORD.findall(line)
            pairs = [f"{a} {b}" for a, b in zip(words, words[1:], strict=False)]
            if any(_h(w) in BLOCKED for w in (*words, *pairs)):
                found.append(f"{f}:{n}")
    assert not found, "Remove references to other products or websites: " + ", ".join(found[:20])
