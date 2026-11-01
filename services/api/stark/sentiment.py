"""Fast, offline sentiment for mentions and messages: no AI call, no data leaves the computer.

A small weighted word list (English, plus common emoji) with negation and intensifier handling. It is meant for
sorting an inbox (what needs attention first), not for fine-grained opinion mining.
"""

from __future__ import annotations

import re

POSITIVE = {
    "love": 3, "loved": 3, "loving": 3, "amazing": 3, "awesome": 3, "excellent": 3, "fantastic": 3, "brilliant": 3,
    "perfect": 3, "great": 2, "good": 1, "nice": 1, "cool": 1, "helpful": 2, "useful": 2, "thanks": 2, "thank": 2,
    "thx": 1, "recommend": 2, "recommended": 2, "impressive": 2, "beautiful": 2, "happy": 2, "glad": 2, "wow": 2,
    "fast": 1, "easy": 1, "smooth": 1, "works": 1, "fixed": 1, "best": 2, "favorite": 2, "favourite": 2, "solid": 1,
    "congrats": 2, "congratulations": 2, "excited": 2, "enjoy": 2, "enjoyed": 2, "win": 1, "clean": 1,
}
NEGATIVE = {
    "hate": -3, "terrible": -3, "awful": -3, "horrible": -3, "worst": -3, "scam": -3, "useless": -3, "garbage": -3,
    "trash": -3, "broken": -2, "bad": -2, "bug": -1, "buggy": -2, "crash": -2, "crashes": -2, "crashed": -2,
    "error": -1, "fail": -2, "fails": -2, "failed": -2, "slow": -1, "annoying": -2, "disappointed": -2,
    "disappointing": -2, "refund": -2, "angry": -2, "frustrating": -2, "frustrated": -2, "problem": -1, "issue": -1,
    "doesnt": -1, "cant": -1, "wont": -1, "spam": -2, "misleading": -2, "fake": -2, "poor": -2, "unusable": -3,
    "ripoff": -3, "lag": -1, "laggy": -2, "confusing": -1, "sucks": -3, "stopped": -1, "lost": -1, "down": -1,
}
EMOJI = {"❤": 2, "😍": 3, "🔥": 2, "👏": 2, "🙌": 2, "😊": 2, "🎉": 2, "👍": 1, "💯": 2, "🚀": 1,
         "😡": -3, "🤬": -3, "😠": -2, "👎": -2, "😞": -2, "😢": -1, "💩": -3, "🙄": -1}
NEGATORS = {"not", "no", "never", "dont", "don't", "isnt", "isn't", "wasnt", "wasn't", "hardly", "without"}
BOOST = {"very": 1.5, "really": 1.4, "so": 1.3, "extremely": 1.8, "super": 1.5, "totally": 1.4}
WORD = re.compile(r"[a-z']+")


def analyze(text: str) -> tuple[str, float]:
    """(label, score) with score in -1 … 1. Neutral when nothing scoring is found."""
    words = [w.replace("'", "") for w in WORD.findall((text or "").lower())]
    total = 0.0
    hits = 0
    for i, w in enumerate(words):
        value = POSITIVE.get(w) or NEGATIVE.get(w)
        if not value:
            continue
        prev = words[max(0, i - 3):i]
        if any(p in NEGATORS or p.replace("'", "") in NEGATORS for p in prev):
            value = -value * 0.8
        if i and words[i - 1] in BOOST:
            value *= BOOST[words[i - 1]]
        total += value
        hits += 1
    for ch, value in EMOJI.items():
        n = (text or "").count(ch)
        if n:
            total += value * min(n, 3)
            hits += 1
    if (text or "").count("!") >= 2 and total:
        total *= 1.2
    if not hits:
        return "neutral", 0.0
    score = max(-1.0, min(1.0, total / (4 + abs(total))))  # squashes into -1 … 1
    label = "positive" if score >= 0.15 else "negative" if score <= -0.15 else "neutral"
    return label, round(score, 3)
