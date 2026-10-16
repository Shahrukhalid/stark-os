"""Detect which agent a command addresses ("Friday, run diagnostics", "Hey JARVIS ...")."""

from __future__ import annotations

import re

ALIASES = {
    "jarvis": ["jarvis", "j.a.r.v.i.s.", "j.a.r.v.i.s", "j a r v i s"],
    "friday": ["friday", "f.r.i.d.a.y.", "f.r.i.d.a.y"],
    "edith": ["edith", "e.d.i.t.h.", "e.d.i.t.h"],
    "ultron": ["ultron"],
    "jocasta": ["jocasta", "jocaster"],
    "dum_e": ["dum-e", "dum-e.", "d.u.m.-e.", "d.u.m.-e", "dumb-e", "dummy", "dum e", "dumbie"],
    "u": ["u"],
}
_PREFIX = re.compile(r"^\s*(?:hey|ok|okay|hi|yo)?\s*,?\s*", re.I)


def parse_address(text: str) -> tuple[str | None, str]:
    """Return (agent_id, remaining_text). Requires the name to lead the utterance."""
    stripped = _PREFIX.sub("", text, count=1)
    lower = stripped.lower()
    best: tuple[str, int] | None = None
    for agent_id, names in ALIASES.items():
        for name in names:
            if not lower.startswith(name):
                continue
            rest = stripped[len(name):]
            # the name must end at a word boundary; the bare "u" additionally needs a separator
            if rest and rest[0].isalnum():
                continue
            if agent_id == "u" and not re.match(r"^\s*[,:]", rest):
                continue
            if best is None or len(name) > best[1]:
                best = (agent_id, len(name))
    if best is None:
        return None, text.strip()
    remaining = stripped[best[1]:].lstrip(" ,:;.!-").strip()
    return best[0], remaining or text.strip()
