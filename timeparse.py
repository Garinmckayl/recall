"""Deterministic time-expression resolver: 'six days ago', 'last night', 'on Sep 21' -> (start, end) epoch.

Dates are never computed by an LLM: a model extracts the phrase, this module resolves it against `now`.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Optional

_NUM = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
        "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fourteen": 14}
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _day(d: dt.date) -> tuple[float, float]:
    s = dt.datetime.combine(d, dt.time.min)
    return s.timestamp(), (s + dt.timedelta(days=1)).timestamp()


def _n(tok: str) -> Optional[int]:
    tok = tok.lower()
    return int(tok) if tok.isdigit() else _NUM.get(tok)


def resolve(expr: Optional[str], now: Optional[float] = None) -> Optional[tuple[float, float]]:
    """Return (start, end) epoch seconds for the phrase, or None if it is not a time expression."""
    if not expr:
        return None
    t = expr.lower().strip()
    now_dt = dt.datetime.fromtimestamp(now) if now else dt.datetime.now()
    today = now_dt.date()
    now_ts = now_dt.timestamp()

    if re.search(r"\b(right now|just now|a moment ago)\b", t):
        return now_ts - 600, now_ts
    if "tonight" in t:
        s = dt.datetime.combine(today, dt.time(18))
        return s.timestamp(), now_ts + 3600
    if "last night" in t:
        s = dt.datetime.combine(today - dt.timedelta(days=1), dt.time(18))
        return s.timestamp(), dt.datetime.combine(today, dt.time(6)).timestamp()
    if "this morning" in t:
        return dt.datetime.combine(today, dt.time(5)).timestamp(), dt.datetime.combine(today, dt.time(12)).timestamp()
    if "this afternoon" in t:
        return dt.datetime.combine(today, dt.time(12)).timestamp(), dt.datetime.combine(today, dt.time(17)).timestamp()
    if "this evening" in t:
        return dt.datetime.combine(today, dt.time(17)).timestamp(), now_ts + 3600
    if "yesterday" in t:
        return _day(today - dt.timedelta(days=1))
    if re.search(r"\btoday\b", t):
        return _day(today)

    m = re.search(r"(?:in the )?(?:last|past)\s+(\w+)\s+(hour|hours|day|days|week|weeks)", t)
    if m and _n(m.group(1)):
        n = _n(m.group(1))
        unit = 3600 if m.group(2).startswith("hour") else 86400 if m.group(2).startswith("day") else 7 * 86400
        return now_ts - n * unit, now_ts
    if re.search(r"(in the )?(last|past) (hour)\b", t):
        return now_ts - 3600, now_ts
    if re.search(r"\bthis week\b", t):
        return _day(today - dt.timedelta(days=today.weekday()))[0], now_ts
    if re.search(r"\blast week\b", t):
        mon = today - dt.timedelta(days=today.weekday() + 7)
        return _day(mon)[0], _day(mon + dt.timedelta(days=6))[1]

    m = re.search(r"(\w+)\s+(day|days|week|weeks|hour|hours)\s+ago", t)
    if m and _n(m.group(1)):
        n, unit = _n(m.group(1)), m.group(2)
        if unit.startswith("hour"):
            return now_ts - (n + 0.5) * 3600, now_ts - max(n - 0.5, 0) * 3600
        days = n * (7 if unit.startswith("week") else 1)
        return _day(today - dt.timedelta(days=days))

    m = re.search(r"(?:on\s+)?(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})", t)
    if m:
        d = dt.date(today.year, _MONTHS[m.group(1)], int(m.group(2)))
        if d > today:
            d = d.replace(year=d.year - 1)
        return _day(d)
    m = re.search(r"\b(\d{1,2})/(\d{1,2})\b", t)
    if m:
        d = dt.date(today.year, int(m.group(1)), int(m.group(2)))
        if d > today:
            d = d.replace(year=d.year - 1)
        return _day(d)

    for i, name in enumerate(_DAYS):
        if name in t:
            back = (today.weekday() - i) % 7 or 7
            return _day(today - dt.timedelta(days=back))
    return None
