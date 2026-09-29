"""Views: DB rows -> the JSON shapes the UI and MCP tools consume (one place, so they never drift)."""
from __future__ import annotations

import datetime as dt
import time
from typing import Optional

import db

DISPLAY_FLAGS = {
    "possible_weapon": "possible weapon (unverified)",
    "knocks": "knocking",
    "rings_doorbell": "doorbell",
    "concern_suspicious": "suspicious behavior",
    "concern_emergency": "emergency indicators",
}
DEPARTURE_ACTIONS = {"exits_building", "leaves", "leaves_immediately", "vehicle_departs", "enters_vehicle"}
ENTRY_ACTIONS = {"enters_building", "opens_gate"}


def local(ts: float) -> dt.datetime:
    return dt.datetime.fromtimestamp(ts)


def clock(ts: float) -> str:
    t = local(ts)
    return t.strftime("%-I:%M %p")


def fmt_when(ts: float, now: Optional[float] = None) -> str:
    """'today 7:42 PM' / 'yesterday 7:42 PM' / 'Sep 21, 7:42 PM (Monday)'."""
    now = now or time.time()
    d, n = local(ts).date(), local(now).date()
    if d == n:
        return f"today {clock(ts)}"
    if (n - d).days == 1:
        return f"yesterday {clock(ts)}"
    return f"{local(ts).strftime('%b %-d')}, {clock(ts)} ({local(ts).strftime('%A')})"


def person_dict(p: Optional[dict]) -> Optional[dict]:
    if not p:
        return None
    cams = db.q("SELECT DISTINCT c.name FROM actors a JOIN events e ON e.id=a.event_id "
                "JOIN cameras c ON c.id=e.camera_id WHERE a.person_id=?", (p["id"],))
    return {
        "id": p["id"], "name": p.get("name"), "relation": p.get("relation"), "kind": p.get("kind"),
        "label": p.get("label") or "person", "role": p.get("role"), "role_conf": p.get("role_conf"),
        "n_events": p.get("n_obs") or 0, "first_ts": p.get("first_ts"), "last_ts": p.get("last_ts"),
        "cameras": [c["name"] for c in cams], "is_resident": bool(p.get("is_resident")),
        "thumb_url": f"/media/person/{p['id']}.jpg" if p.get("thumb_path") else None,
        "appearance": _appearance(p["id"]),
    }


def _appearance(person_id: str) -> str:
    rows = db.q("SELECT attrs FROM actors WHERE person_id=? ORDER BY id DESC LIMIT 1", (person_id,))
    if not rows or not rows[0]["attrs"]:
        return ""
    a = rows[0]["attrs"]
    bits = [a.get("top"), a.get("bottom"), a.get("headwear"), a.get("hair")]
    return ", ".join(str(b) for b in bits if b and str(b).lower() not in ("unknown", "none"))


def flags_for(e: dict) -> list[str]:
    return [DISPLAY_FLAGS[f] for f in (e.get("flags") or []) if f in DISPLAY_FLAGS]


def actor_dict(a: dict, persons: dict[str, dict]) -> dict:
    p = persons.get(a.get("person_id") or "") or {}
    return {
        "actor_id": a.get("id"), "boxes": a.get("boxes") or [],
        "person_id": a.get("person_id"), "label": p.get("label") or a.get("description", "")[:40],
        "name": p.get("name"), "role": "resident_family" if p.get("is_resident") else a.get("role"),
        "role_conf": 1.0 if p.get("is_resident") else a.get("role_conf"),
        "actions": a.get("actions") or [], "carrying": a.get("carrying") or [],
        "t_first": a.get("t_first"), "kind": a.get("kind"), "description": a.get("description"),
        "concern": a.get("concern"),
    }


def event_dict(e: dict, full: bool = False) -> dict:
    cam = db.one("SELECT * FROM cameras WHERE id=?", (e["camera_id"],)) or {}
    actors = db.q("SELECT * FROM actors WHERE event_id=? ORDER BY idx", (e["id"],))
    pids = {a["person_id"] for a in actors if a.get("person_id")}
    persons = {p["id"]: p for p in db.q(f"SELECT * FROM persons WHERE id IN ({','.join('?' * len(pids))})",
                                        list(pids))} if pids else {}
    out = {
        "id": e["id"], "camera_id": e["camera_id"], "camera_name": cam.get("name", e["camera_id"]),
        "ts": e["ts"], "kind": e["kind"], "sub_type": e.get("sub_type"), "summary": e.get("summary") or "",
        "thumb_url": f"/media/thumb/{e['id']}.jpg" if e.get("thumb_path") else None,
        "clip_url": f"/media/clip/{e['id']}.mp4" if e.get("clip_path") else None,
        "duration": e.get("duration"), "status": e.get("status"), "source": e.get("source"),
        "flags": flags_for(e), "actors": [actor_dict(a, persons) for a in actors],
    }
    if full:
        objs = db.q("SELECT label, note FROM objects WHERE event_id=?", (e["id"],))
        out.update({"objects": objs, "scene": e.get("scene"), "raw": e.get("raw"), "error": e.get("error")})
    return out


def short(text: str, n: int = 46) -> str:
    text = (text or "").strip().rstrip(".")
    return text if len(text) <= n else text[:n].rsplit(" ", 1)[0] + "…"


def citation(e: dict, label: str, actor: Optional[dict] = None) -> dict:
    """The UI already prefixes date + camera, so the label is only a short description of the event."""
    cam = db.one("SELECT * FROM cameras WHERE id=?", (e["camera_id"],)) or {}
    label = ("⚠ " if label.startswith("⚠") else "") + (short(e.get("summary") or "") or "activity")
    return {
        "event_id": e["id"], "ts": e["ts"], "camera_id": e["camera_id"],
        "camera_name": cam.get("name", e["camera_id"]), "label": label,
        "clip_url": f"/media/clip/{e['id']}.mp4" if e.get("clip_path") else None,
        "thumb_url": f"/media/thumb/{e['id']}.jpg" if e.get("thumb_path") else None,
        "t_offset": max(0.0, float((actor or {}).get("t_first") or 0.0) - 0.3),
        "person_id": (actor or {}).get("person_id"), "boxes": (actor or {}).get("boxes") or [],
    }


def humanize_actions(actions: list[str], carrying: Optional[list[str]] = None) -> str:
    verbs = {
        "approaches_door": "approaches the door", "rings_doorbell": "rings the doorbell", "knocks": "knocks",
        "waits_at_door": "waits at the door", "leaves": "leaves", "leaves_immediately": "leaves right away",
        "enters_building": "enters the building", "exits_building": "exits the building",
        "enters_vehicle": "gets into a vehicle", "exits_vehicle": "gets out of a vehicle",
        "vehicle_arrives": "arrives by vehicle", "vehicle_departs": "drives away",
        "carries_object": "carries something", "hands_object_to": "hands something over",
        "places_package": "leaves a package", "picks_up_package": "picks up a package",
        "walks_by": "walks by", "lingers": "lingers", "peers_into_windows": "looks into windows",
        "raises_object": "raises an object", "runs": "runs", "opens_gate": "opens the gate",
        "sits": "sits", "plays": "plays",
    }
    parts = [verbs.get(a, a.replace("_", " ")) for a in actions[:3]]
    text = ", ".join(parts) if parts else "appears"
    if carrying:
        text += f" (carrying {', '.join(c.replace('_', ' ') for c in carrying[:2])})"
    return text
