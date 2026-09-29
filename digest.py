"""DIGEST: what needs the owner's attention, computed from memory (no model in the loop).

Three kinds of item: flagged events (weapon / suspicious / emergency indicators), unfamiliar people at night,
and unnamed regulars ("seen 4 times — name them?"), which is how the owner enrolls family and known visitors.
"""
from __future__ import annotations

import datetime as dt
import time
from typing import Optional

import db
import routine
import views

ROLE_PHRASE = {"resident_family": "family member", "guest_visitor": "visitor", "delivery_driver": "delivery driver",
               "service_worker": "service worker", "solicitor": "salesperson", "passerby": "passer-by"}
WINDOW_DAYS = 7
MAX_ITEMS = 6


def _cam(e: dict) -> str:
    return (db.one("SELECT name FROM cameras WHERE id=?", (e["camera_id"],)) or {}).get("name", e["camera_id"])


def build(now: Optional[float] = None) -> dict:
    now = now or time.time()
    midnight = dt.datetime.combine(dt.datetime.fromtimestamp(now).date(), dt.time.min).timestamp()
    today = db.q("SELECT id FROM events WHERE status='processed' AND ts>=?", (midnight,))
    today_people = db.q("SELECT DISTINCT a.person_id FROM actors a JOIN events e ON e.id=a.event_id "
                        "WHERE e.ts>=? AND a.person_id IS NOT NULL", (midnight,))
    recent = db.q("SELECT * FROM events WHERE status='processed' AND ts>=? ORDER BY ts DESC",
                  (now - WINDOW_DAYS * 86400,))

    flags, night, regulars, seen_events = [], [], [], set()
    night_seen: set = set()
    for e in recent:
        f = set(e.get("flags") or [])
        when = f"{_cam(e)}, {views.fmt_when(e['ts'], now)}"
        actors = db.q("SELECT * FROM actors WHERE event_id=?", (e["id"],))
        if "possible_weapon" in f:
            flags.append({"kind": "flag", "text": f"Possible weapon (unverified) — {when}. Review the clip.",
                          "event_id": e["id"], "person_id": None, "ts": e["ts"], "sev": 0})
            seen_events.add(e["id"])
        elif f & {"concern_emergency", "concern_suspicious"}:
            what = "Emergency indicators" if "concern_emergency" in f else "Suspicious behavior"
            flags.append({"kind": "flag", "text": f"{what} — {when}: {e.get('summary') or 'see clip'}",
                          "event_id": e["id"], "person_id": None, "ts": e["ts"], "sev": 1})
            seen_events.add(e["id"])
        hour = dt.datetime.fromtimestamp(e["ts"]).hour
        if (hour >= 20 or hour < 6) and e["id"] not in seen_events and (now - e["ts"]) < 3 * 86400:
            people = [db.one("SELECT * FROM persons WHERE id=?", (a["person_id"],)) for a in actors if a.get("person_id")]
            if any(p and (p.get("name") or p.get("is_resident")) for p in people):
                continue                                    # arrived with someone the owner knows
            for a in actors:
                p = db.one("SELECT * FROM persons WHERE id=?", (a["person_id"],)) if a.get("person_id") else None
                if p and p["id"] in night_seen:
                    continue
                if p and p["kind"] == "person" and not p.get("name") and not p.get("is_resident"):
                    night_seen.add(p["id"])
                    night.append({"kind": "night_unknown", "text": f"Unfamiliar person at night — {when}: the {p['label']}.",
                                  "event_id": e["id"], "person_id": p["id"], "ts": e["ts"], "sev": 2})
                    break

    for p in db.q("SELECT * FROM persons WHERE kind='person' AND (name IS NULL OR name='') AND is_resident=0 "
                  "AND n_obs>=3 ORDER BY n_obs DESC"):
        role = ROLE_PHRASE.get(p.get("role") or "unknown", (p.get("role") or "").replace("_", " "))
        hint = f" (looks like a {role})" if p.get("role") not in (None, "unknown") else ""
        regulars.append({"kind": "unnamed_regular", "text": f"The {p['label']} has appeared {p['n_obs']} times{hint}. Name them?",
                         "event_id": None, "person_id": p["id"], "ts": p.get("last_ts"), "sev": 3})

    devs = [{"kind": "routine", "text": d["text"], "event_id": None, "person_id": d["person_id"], "ts": d.get("ts"), "sev": 0.5}
            for d in routine.deviations(now)]
    items = (devs + sorted(flags, key=lambda i: (i["sev"], -i["ts"]))
             + sorted(night, key=lambda i: -i["ts"]) + regulars)
    items = items[:MAX_ITEMS]
    for i in items:
        i.pop("sev", None)
    n_flag = sum(1 for i in items if i["kind"] in ("flag", "night_unknown", "routine"))
    if n_flag:
        headline = f"{n_flag} thing{'s' if n_flag != 1 else ''} to look at"
    elif items:
        headline = "Nothing urgent — a couple of people to name"
    else:
        headline = "All quiet"
    return {"headline": headline,
            "stats": {"events_today": len(today), "people_today": len(today_people)},
            "attention": items}
