"""WATCH: standing rules evaluated on every new event. SEE -> REMEMBER -> UNDERSTAND -> ANSWER -> WATCH -> ACT.

Rules are created from conversation ("tell me next time this person comes") and fire a real push
notification (ntfy) plus a live feed alert in the UI.
"""
from __future__ import annotations

import time
from typing import Optional

import httpx

import config
import db
import views

COOLDOWN_SEC = 60


def in_window(hour: int, start: int, end: int) -> bool:
    """Hour-of-day window that may wrap midnight (22 -> 5)."""
    return start <= hour < end if start < end else (hour >= start or hour < end)


def create_rule(kind: str, person_id: Optional[str], params: dict, text: str) -> dict:
    rid = db.insert("watch_rules", text=text, kind=kind, person_id=person_id, params=params, active=1,
                    created=time.time())
    return db.one("SELECT * FROM watch_rules WHERE id=?", (rid,))


def _who(actor: dict) -> str:
    p = db.one("SELECT name, label FROM persons WHERE id=?", (actor["person_id"],)) or {}
    return p.get("name") or ("the " + (p.get("label") or "visitor"))


def _match(rule: dict, actors: list[dict], event: dict, cam: dict) -> Optional[dict]:
    import datetime as dt
    hour = dt.datetime.fromtimestamp(event["ts"]).hour
    params = rule.get("params") or {}
    for a in actors:
        if rule["kind"] == "person_arrives" and a["person_id"] == rule["person_id"]:
            return a
        if rule["kind"] == "role_arrives":
            if (a.get("role_probs") or {}).get(params.get("role", ""), 0) >= 0.5:
                return a
        if rule["kind"] == "person_departs_window" and a["person_id"] == rule["person_id"]:
            departs = (set(a.get("actions") or []) & views.DEPARTURE_ACTIONS) or a.get("direction") == "leaving"
            if departs and in_window(hour, int(params.get("start", 0)), int(params.get("end", 6))):
                return a
        if rule["kind"] == "unknown_at_night" and (hour >= 20 or hour < 6):
            p = db.one("SELECT name, is_resident FROM persons WHERE id=?", (a["person_id"],)) or {}
            if not p.get("name") and not p.get("is_resident") and a.get("kind") == "person":
                return a
    return None


def notify(message: str) -> bool:
    try:
        r = httpx.post(f"https://ntfy.sh/{config.NTFY_TOPIC}", timeout=10.0, json={
            "message": message, "title": "Recall", "tags": ["eyes"], "priority": "high"})
        return r.status_code in (200, 202)
    except Exception:
        return False


def evaluate(event_id: str) -> list[dict]:
    e = db.one("SELECT * FROM events WHERE id=?", (event_id,))
    if not e or e["status"] != "processed":
        return []
    # a rule can only fire for events that are new: never for history back-filled from days ago
    if time.time() - e["ts"] > 15 * 60:
        return []
    cam = db.one("SELECT * FROM cameras WHERE id=?", (e["camera_id"],))
    actors = db.q("SELECT * FROM actors WHERE event_id=?", (event_id,))
    fired = []
    for rule in db.q("SELECT * FROM watch_rules WHERE active=1"):
        if rule.get("last_fired") and time.time() - rule["last_fired"] < COOLDOWN_SEC:
            continue
        a = _match(rule, actors, e, cam)
        if not a:
            continue
        msg = f"{_who(a).capitalize()} — {cam['name']}, {views.clock(e['ts'])}: {e.get('summary') or 'activity detected'}"
        delivered = notify(msg)
        aid = db.insert("alerts", rule_id=rule["id"], event_id=event_id, ts=time.time(), message=msg,
                        delivered=1 if delivered else 0)
        db.update("watch_rules", "id", rule["id"], last_fired=time.time())
        db.feed("alert", msg, {"alert_id": aid, "rule_id": rule["id"], "event_id": event_id, "rule": rule["text"]})
        fired.append({"alert_id": aid, "message": msg})
    return fired
