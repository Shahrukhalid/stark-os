"""RFC 5545 output of the posting-schedule calendar feed (escaping, folding, CRLF, UTC)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def _unfold(ics: str) -> list[str]:
    return ics.replace("\r\n ", "").split("\r\n")


def test_ics_uses_crlf_utc_times_and_one_uid_per_post():
    from stark.ics import build_calendar

    when = datetime(2026, 11, 3, 15, 30, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    items = [{"id": "abc123", "platform": "bluesky", "text": "Hello", "scheduled_for": when.isoformat()},
             {"id": "def456", "platform": "mastodon", "text": "Again", "scheduled_for": "2026-11-04T09:00:00"}]
    ics = build_calendar(items, now=datetime(2026, 10, 27, 8, 0, tzinfo=timezone.utc))
    assert ics.startswith("BEGIN:VCALENDAR\r\n") and ics.endswith("END:VCALENDAR\r\n")
    assert "\n" not in ics.replace("\r\n", "")
    lines = _unfold(ics)
    assert "UID:abc123@stark-os" in lines and "UID:def456@stark-os" in lines
    assert "DTSTART:20261103T100000Z" in lines  # converted from +05:30
    assert "DTSTART:20261104T090000Z" in lines  # naive treated as UTC
    assert lines.count("DTSTAMP:20261027T080000Z") == 2
    assert "SUMMARY:Bluesky: Hello" in lines


def test_ics_escapes_special_characters():
    from stark.ics import build_calendar, escape_text

    assert escape_text("a,b;c\\d\ne\r\nf") == "a\\,b\\;c\\\\d\\ne\\nf"
    ics = build_calendar([{"id": "x", "platform": "bluesky", "text": "one, two; three\nline\\2",
                           "scheduled_for": "2026-11-03T10:00:00+00:00"}])
    assert "DESCRIPTION:one\\, two\\; three\\nline\\\\2\r\n" in ics


def test_ics_folds_long_lines_at_75_octets_without_splitting_characters():
    from stark.ics import build_calendar

    text = "é" * 200 + " " + "word " * 80
    ics = build_calendar([{"id": "x", "platform": "bluesky", "text": text, "scheduled_for": "2026-11-03T10:00:00+00:00"}])
    physical = ics.split("\r\n")[:-1]
    assert all(len(p.encode("utf-8")) <= 75 for p in physical)
    assert any(p.startswith(" ") for p in physical)
    desc = [ln for ln in _unfold(ics) if ln.startswith("DESCRIPTION:")][0]
    assert desc == "DESCRIPTION:" + text.replace(",", "\\,")
    ics.encode("utf-8").decode("utf-8")


def test_ics_summary_truncates_to_60_characters():
    from stark.ics import event_summary

    s = event_summary("bluesky", "x" * 100)
    assert s == "Bluesky: " + "x" * 60 + "…"
    assert event_summary("mastodon", "two\nlines  here") == "Mastodon: two lines here"
