"""Seed a multi-day Ring history and run it through the REAL pipeline.

Events are written into the Ring sandbox (same API the live client uses), then pulled with
pipeline.sync() -> clip download -> Nova perception -> Titan re-id -> Jev roles. Nothing is
pre-labelled except optional owner enrollment ("name") — exactly what a user does in the People tab.

Footage comes from demo_clips/manifest.json (your staged shots; see demo_clips/README.md). Without one,
a sample manifest over the bundled stock clips is used so the system runs end to end.

    python3 seed.py            # asks the running server (localhost:8000) to seed
"""
from __future__ import annotations

import datetime as dt
import json
import shutil
import sys
import time

import config
import db
import identity
import pipeline
import ring_sim

SAMPLE = {"events": [
    {"clip": "31155.mp4", "camera": "Front Door", "kind": "doorbell", "days_ago": 12, "time": "18:42", "label": "Courier at the door"},
    {"clip": "31155.mp4", "camera": "Front Door", "kind": "doorbell", "days_ago": 8, "time": "12:15", "label": "Courier at the door"},
    {"clip": "51522.mp4", "camera": "Front Door", "kind": "doorbell", "days_ago": 5, "time": "20:15", "label": "Guests arrive"},
    {"clip": "31155.mp4", "camera": "Front Door", "kind": "doorbell", "days_ago": 3, "time": "19:05", "label": "Courier at the door"},
    {"clip": "23438.mp4", "camera": "Driveway", "kind": "motion", "days_ago": 2, "time": "21:29", "label": "Dad arrives", "name": "Dad", "relation": "father"},
    {"clip": "27591.mp4", "camera": "Front Door", "kind": "motion", "days_ago": 1, "time": "07:30", "label": "Mom leaves", "name": "Mom", "relation": "mother"},
    {"clip": "45843.mp4", "camera": "Backyard", "kind": "motion", "days_ago": 1, "time": "14:10", "label": "Dog in the yard"},
    {"clip": "31375.mp4", "camera": "Front Door", "kind": "motion", "days_ago": 0, "time": "00:40", "label": "Night visitor"},
]}


def load_manifest() -> dict:
    p = config.DEMO_CLIPS_DIR / "manifest.json"
    if p.exists():
        return json.loads(p.read_text())
    return SAMPLE


def _when(days_ago: int, hhmm: str) -> float:
    h, m = (int(x) for x in hhmm.split(":"))
    d = dt.datetime.now().date() - dt.timedelta(days=days_ago)
    return min(dt.datetime.combine(d, dt.time(h, m)).timestamp(), time.time() - 120)


def run(reset: bool = True) -> dict:
    if reset:
        db.reset_all()
        ring_sim.reset_state()
        for d in (config.CLIPS_DIR, config.THUMBS_DIR):
            shutil.rmtree(d, ignore_errors=True)
    db.feed("info", "Seeding demo history through the Ring API…")
    pipeline.sync_devices()
    st = ring_sim.load_state()
    dev = {d["name"]: d["id"] for d in st["devices"]}
    man = load_manifest()
    entries = sorted(man["events"], key=lambda e: (-e["days_ago"], e["time"]))
    ids = []
    for e in entries:
        res = ring_sim.emit(dev[e["camera"]], e["clip"], e.get("kind", "motion"),
                            occurred_at=_when(e["days_ago"], e["time"]), sub_type="human", deliver=False)
        ids.append((res["event"]["id"], e))
    out = pipeline.sync()
    pipeline.drain()

    named = 0
    for rid, e in ids:
        if e.get("name"):
            row = db.one("SELECT id FROM events WHERE ring_event_id=?", (rid,))
            actor = db.one("SELECT person_id FROM actors WHERE event_id=? AND person_id IS NOT NULL ORDER BY idx LIMIT 1", (row["id"],)) if row else None
            if actor:
                identity.name_person(actor["person_id"], e["name"], e.get("relation", ""))
                import roles
                roles.aggregate(actor["person_id"])
                named += 1
    failed = db.q("SELECT id, error FROM events WHERE status='failed'")
    db.feed("info", f"Seed complete: {len(ids)} events, {named} people enrolled, {len(failed)} failed.")
    return {"events": len(ids), "synced": out, "named": named, "failed": failed}


if __name__ == "__main__":
    import httpx
    r = httpx.post(f"{config.SERVER_URL}/api/demo/seed", json={"reset": "--no-reset" not in sys.argv}, timeout=30)
    print(r.status_code, r.text, "\nWatch progress in the UI feed (or GET /api/feed).")
