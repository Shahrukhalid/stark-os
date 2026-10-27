"""Minimal RFC 5545 iCalendar writer for the posting schedule (no third-party dependency)."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

PRODID = "-//STARK OS//Posting schedule//EN"
EVENT_MINUTES = 15
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def escape_text(value: str) -> str:
    """Escape a TEXT value: backslash, semicolon, comma and newlines (RFC 5545 section 3.3.11)."""
    value = _CTRL.sub("", value.replace("\r\n", "\n").replace("\r", "\n"))
    return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def fold_line(line: str, limit: int = 75) -> str:
    """Fold to at most `limit` octets per physical line (continuations start with one space),
    never splitting a multi-byte UTF-8 character."""
    if len(line.encode("utf-8")) <= limit:
        return line
    parts: list[str] = []
    cur, size, room = "", 0, limit
    for ch in line:
        n = len(ch.encode("utf-8"))
        if size + n > room:
            parts.append(cur)
            cur, size, room = "", 0, limit - 1  # the leading space counts toward the limit
        cur += ch
        size += n
    parts.append(cur)
    return "\r\n ".join(parts)


def utc_stamp(when: datetime) -> str:
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def event_summary(platform: str, text: str, width: int = 60) -> str:
    short = " ".join((text or "").split())
    if len(short) > width:
        short = short[:width].rstrip() + "…"
    return f"{platform.capitalize()}: {short}" if short else platform.capitalize()


def build_calendar(items: list[dict[str, Any]], now: datetime | None = None) -> str:
    """Build a VCALENDAR with one VEVENT per item that has a scheduled_for time."""
    stamp = utc_stamp(now or datetime.now(timezone.utc))
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:{PRODID}", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
             "X-WR-CALNAME:STARK OS posting schedule"]
    for it in items:
        raw = it.get("scheduled_for")
        if not raw:
            continue
        start = raw if isinstance(raw, datetime) else datetime.fromisoformat(raw)
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        text = it.get("text") or ""
        thread = [t for t in (it.get("thread") or []) if isinstance(t, str)]
        if thread:
            text = "\n\n".join([text, *thread])
        lines += [
            "BEGIN:VEVENT",
            f"UID:{escape_text(str(it['id']))}@stark-os",
            f"DTSTAMP:{stamp}",
            f"DTSTART:{utc_stamp(start)}",
            f"DTEND:{utc_stamp(start + timedelta(minutes=EVENT_MINUTES))}",
            f"SUMMARY:{escape_text(event_summary(str(it.get('platform') or 'post'), it.get('text') or ''))}",
            f"DESCRIPTION:{escape_text(text)}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "".join(fold_line(line) + "\r\n" for line in lines)
