"""ROUTINE: learn each person's usual times from their own history and flag deviations (caretaking).

A person has a routine when, over the days their sightings span, they reliably appear around the same time of
day. Pure statistics (median + MAD) over stored sightings — no model, so it is explainable and testable.
Only named people trigger digest deviations: the owner cares whether Dad is up, not whether a courier is late.
"""
from __future__ import annotations

import datetime as dt
import statistics
import time
from typing import Optional

import db
import views
import watch

MIN_DAYS = 3            # distinct past days needed before we claim a routine
MIN_REGULARITY = 0.6    # share of days in the span with a sighting near the usual time
MIN_TOLERANCE = 45      # minutes


def _min_of_day(ts: float) -> int:
    t = dt.datetime.fromtimestamp(ts)
    return t.hour * 60 + t.minute


def _fmt(m: int) -> str:
    return dt.datetime(2000, 1, 1, int(m) // 60 % 24, int(m) % 60).strftime("%-I:%M %p")


def _circ(a: float, b: float) -> float:
    d = abs(a - b) % 1440
    return min(d, 1440 - d)


def profile(person_id: str, now: Optional[float] = None) -> Optional[dict]:
    """The person's usual time of day, or None if there is no reliable routine."""
    now = now or time.time()
    today = dt.datetime.fromtimestamp(now).date()
    rows = db.q("SELECT e.ts FROM actors a JOIN events e ON e.id=a.event_id WHERE a.person_id=? AND e.status='processed' ORDER BY e.ts",
                (person_id,))
    by_day: dict[dt.date, list[float]] = {}
    for r in rows:
        d = dt.datetime.fromtimestamp(r["ts"]).date()
        if d < today:
            by_day.setdefault(d, []).append(r["ts"])
    if len(by_day) < MIN_DAYS:
        return None
    firsts = [_min_of_day(min(v)) for v in by_day.values()]
    # unwrap around midnight so 23:50 and 00:10 average sensibly
    ref = firsts[0]
    unwrapped = [ref + ((m - ref + 720) % 1440 - 720) for m in firsts]
    med = statistics.median(unwrapped)
    mad = statistics.median(abs(u - med) for u in unwrapped)
    tol = max(MIN_TOLERANCE, 3 * 1.4826 * mad)
    near = sum(1 for u in unwrapped if abs(u - med) <= tol)
    span_days = (max(by_day) - min(by_day)).days + 1
    regularity = near / max(span_days, len(by_day))
    if regularity < MIN_REGULARITY:
        return None
    return {"usual_min": int(med) % 1440, "usual": _fmt(int(med)), "tolerance_min": int(tol), "days_seen": len(by_day),
            "days_span": span_days, "near_days": near, "regularity": round(regularity, 2)}


def check(person_id: str, now: Optional[float] = None) -> Optional[dict]:
    """Today's status against the routine: on_track | missing | unusual_time | no_routine."""
    now = now or time.time()
    p = db.one("SELECT * FROM persons WHERE id=?", (person_id,))
    prof = profile(person_id, now)
    if not p or not prof:
        return {"person_id": person_id, "status": "no_routine"}
    name = p.get("name") or f"the {p.get('label')}"
    midnight = dt.datetime.combine(dt.datetime.fromtimestamp(now).date(), dt.time.min).timestamp()
    todays = db.q("SELECT e.ts FROM actors a JOIN events e ON e.id=a.event_id WHERE a.person_id=? AND e.ts>=? ORDER BY e.ts",
                  (person_id, midnight))
    basis = f"{prof['near_days']} of the last {prof['days_span']} days"
    base = {"person_id": person_id, "name": name, "profile": prof, "basis": basis}
    if not todays:
        overdue = _min_of_day(now) - prof["usual_min"] - prof["tolerance_min"]
        if overdue > 0:
            return {**base, "status": "missing",
                    "text": f"{name} usually appears around {prof['usual']} ({basis}). Nothing yet today."}
        return {**base, "status": "on_track", "text": f"{name} usually appears around {prof['usual']}; it isn't time yet."}
    first = _min_of_day(todays[0]["ts"])
    if _circ(first, prof["usual_min"]) > prof["tolerance_min"] * 1.5:
        return {**base, "status": "unusual_time", "ts": todays[0]["ts"],
                "text": f"{name} showed up at {_fmt(first)} today; usually around {prof['usual']} ({basis})."}
    return {**base, "status": "on_track", "text": f"{name} appeared at {_fmt(first)}, in line with the usual {prof['usual']}."}


def deviations(now: Optional[float] = None) -> list[dict]:
    """Named people whose day differs from their routine (for the digest)."""
    out = []
    for p in db.q("SELECT id FROM persons WHERE name IS NOT NULL AND name!='' AND kind='person'"):
        c = check(p["id"], now)
        if c and c["status"] in ("missing", "unusual_time"):
            out.append(c)
    return out


def notify_overdue(now: Optional[float] = None) -> list[dict]:
    """Recall does not wait to be asked: when a named person is overdue (or turns up at a very unusual time),
    push one check-in alert per person per day (ntfy + live feed)."""
    now = now or time.time()
    day = dt.datetime.fromtimestamp(now).strftime("%Y-%m-%d")
    fired = []
    for d in deviations(now):
        key = f"routine_alert:{d['person_id']}:{day}"
        if db.kv_get(key):
            continue
        db.kv_set(key, str(now))
        msg = f"Check-in: {d['text']}"
        delivered = watch.notify(msg)
        aid = db.insert("alerts", rule_id=None, event_id=None, ts=now, message=msg, delivered=1 if delivered else 0)
        db.feed("alert", msg, {"alert_id": aid, "kind": "routine", "person_id": d["person_id"], "rule": "Routine check-in"})
        fired.append({"alert_id": aid, "message": msg})
    return fired
