"""PIPELINE: Ring event -> clip -> PERCEIVE (Nova) -> ROLES (Jev) -> IDENTITY (Titan) -> memory -> WATCH.

Entry points: accept() for a webhook/history event, sync() to pull Ring event history.
Perception runs in a small pool; the identity stage is serialized so two concurrent events
can never mint duplicate person nodes.
"""
from __future__ import annotations

import io
import re
import subprocess
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from PIL import Image

import aws
import config
import db
import identity
import perceive
import ring_api
import roles
import watch

_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="recall")
_id_lock = threading.Lock()
_futures: list[Future] = []


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "camera"


def event_id_for(ring_event_id: str) -> str:
    return "evt_" + ring_event_id.removeprefix("evt_")


# -- devices --------------------------------------------------------------------------

def sync_devices() -> list[dict]:
    devs = ring_api.client().list_devices()
    for d in devs:
        db.upsert_camera(_slug(d["name"]), d["name"], d["id"], d.get("zone") or "exterior")
    return devs


# -- accept + sync --------------------------------------------------------------------

def accept(ev: ring_api.RingEvent, source: Optional[str] = None) -> Optional[str]:
    """Register a Ring event and schedule processing. Idempotent per ring_event_id."""
    cam = db.camera_by_device(ev.device_id)
    if cam is None:
        sync_devices()
        cam = db.camera_by_device(ev.device_id)
    if cam is None:
        db.feed("error", f"event for unknown Ring device {ev.device_id}")
        return None
    eid = event_id_for(ev.ring_event_id)
    if db.one("SELECT 1 FROM events WHERE id=?", (eid,)):
        return eid
    db.insert("events", id=eid, ring_event_id=ev.ring_event_id, camera_id=cam["id"], ts=ev.occurred_at,
              kind=ev.kind, sub_type=ev.sub_type, status="queued", raw=ev.raw or {},
              source=source or ("ring" if ring_api.mode() == "live" else "ring_sandbox"))
    _futures.append(_pool.submit(process, eid))
    return eid


def sync() -> dict:
    """Pull event history for every Ring device and ingest what we have not seen."""
    devs = sync_devices()
    accepted = 0
    for d in devs:
        for ev in ring_api.client().device_events(d["id"]):
            if not db.one("SELECT 1 FROM events WHERE ring_event_id=?", (ev.ring_event_id,)):
                accepted += 1
            accept(ev)
    return {"devices": len(devs), "new_events": accepted}


def drain(timeout: float = 600.0) -> bool:
    """Block until every queued event is processed (seeding / tests)."""
    end = time.time() + timeout
    while time.time() < end:
        pending = [f for f in _futures if not f.done()]
        if not pending:
            _futures.clear()
            return True
        time.sleep(0.25)
    return False


# -- clip handling --------------------------------------------------------------------

def _probe_codec(p: Path) -> str:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=codec_name", "-of", "csv=p=0", str(p)], capture_output=True, text=True)
    return out.stdout.strip()


def _make_web_playable(src: Path, dst: Path) -> None:
    """Browsers only play H.264 reliably; remux (fast) or transcode (phone HEVC) with faststart."""
    if _probe_codec(src) == "h264":
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-c", "copy", "-movflags", "+faststart", str(dst)]
    else:
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-vf", "scale='min(1280,iw)':-2",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-movflags", "+faststart", str(dst)]
    subprocess.run(cmd, check=True, capture_output=True)


def _fetch_clip(e: dict, cam: dict) -> Path:
    dst = config.CLIPS_DIR / f"{e['id']}.mp4"
    if dst.exists() and dst.stat().st_size > 0:
        return dst
    config.CLIPS_DIR.mkdir(parents=True, exist_ok=True)
    ev = ring_api.RingEvent(ring_event_id=e["ring_event_id"], device_id=cam["ring_device_id"],
                            type="button_press" if e["kind"] == "doorbell" else "motion_detected",
                            occurred_at=e["ts"], component_ids=(e.get("raw") or {}).get("attributes", {})
                            .get("component_ids", [0]))
    raw = ring_api.client().download_clip(ev)
    tmp = config.CLIPS_DIR / f"{e['id']}.src"
    tmp.write_bytes(raw)
    try:
        _make_web_playable(tmp, dst)
    finally:
        tmp.unlink(missing_ok=True)
    return dst


# -- the per-event brain --------------------------------------------------------------

def _person_thumb(pid: str, actor: dict, frames: list[tuple[float, bytes]]) -> None:
    p = db.one("SELECT thumb_path FROM persons WHERE id=?", (pid,))
    if p and p.get("thumb_path"):
        return
    jpeg = identity.crop_actor(frames, actor) or frames[min(max(actor.get("bbox_frame", 1) - 1, 0), len(frames) - 1)][1]
    im = Image.open(io.BytesIO(jpeg)).convert("RGB")
    im.thumbnail((240, 240))
    config.THUMBS_DIR.mkdir(parents=True, exist_ok=True)
    path = config.THUMBS_DIR / f"{pid}.jpg"
    im.save(path, "JPEG", quality=82)
    db.update("persons", "id", pid, thumb_path=str(path))


def process(event_id: str) -> None:
    e = db.one("SELECT * FROM events WHERE id=?", (event_id,))
    if not e or e["status"] == "processed":
        return
    cam = db.one("SELECT * FROM cameras WHERE id=?", (e["camera_id"],))
    db.update("events", "id", event_id, status="processing", error=None)
    db.feed("ingest_started", f"Processing {cam['name']} event", {"event_id": event_id})
    try:
        clip = _fetch_clip(e, cam)
        rec, frames = perceive.perceive(clip, cam["name"], cam["zone"], e["kind"], e["ts"])
        times = [t for t, _ in frames]
        thumb = perceive.save_thumb(event_id, frames)

        # roles first (independent of identity, network-bound) — outside the identity lock
        decided = []
        for a in rec["actors"]:
            others = [o for o in rec["actors"] if o is not a]
            decided.append(roles.decide_actor(a, others, cam, e["ts"], rec["summary"], rec["objects"], rec["safety"]))

        db.execute("DELETE FROM actors WHERE event_id=?", (event_id,))
        db.execute("DELETE FROM objects WHERE event_id=?", (event_id,))
        touched: list[str] = []
        with _id_lock:
            used: set[str] = set()
            for i, (a, d) in enumerate(zip(rec["actors"], decided)):
                pid, score, _created, exemplar = identity.assign(a, frames, e["ts"], used, thumb)
                used.add(pid)
                touched.append(pid)
                fi = min(max(a["first_frame"] - 1, 0), len(times) - 1)
                li = min(max(a["last_frame"] - 1, 0), len(times) - 1)
                db.insert("actors", event_id=event_id, person_id=pid, idx=i, track=a["track"], kind=a["kind"],
                          description=a["description"], attrs=a["appearance"], carrying=a["carrying"],
                          actions=a["actions"], direction=a["direction"], bbox=a["bbox"] or [],
                          boxes=[{"t": times[min(max(b["frame"] - 1, 0), len(times) - 1)], "bbox": b["bbox"]} for b in a.get("boxes", [])],
                          emb=exemplar,
                          t_first=times[fi], t_last=times[li], match_score=1.0 if _created else round(score, 3),
                          role_probs=d["role_probs"], role=d["role"], role_conf=d["role_conf"],
                          concern=d["concern"], concern_probs=d["concern_probs"])
                _person_thumb(pid, a, frames)
            for pid in dict.fromkeys(touched):
                identity.refresh_label(pid)
                roles.aggregate(pid)

        for o in rec["objects"]:
            db.insert("objects", event_id=event_id, label=o["label"], holder_track=o.get("holder"), note="")

        flags = []
        if rec["safety"]["possible_weapon"]:
            flags.append("possible_weapon")
        if rec["knocks"]:
            flags.append("knocks")
        if rec["rings_doorbell"] or e["kind"] == "doorbell":
            flags.append("rings_doorbell")
        for d in decided:
            if d["concern"] == "suspicious" and "concern_suspicious" not in flags:
                flags.append("concern_suspicious")
            if d["concern"] == "emergency" and "concern_emergency" not in flags:
                flags.append("concern_emergency")

        blob = " ".join([rec["summary"]] + [o["label"].replace("_", " ") for o in rec["objects"]] +
                        [x.replace("_", " ") for a in rec["actors"] for x in a["actions"] + a["carrying"]])
        db.update("events", "id", event_id, status="processed", scene=rec["scene"], summary=rec["summary"],
                  summary_embedding=aws.embed_text(blob), flags=flags, interactions=rec["interactions"],
                  clip_path=str(clip), thumb_path=thumb, duration=perceive.probe_duration(clip),
                  raw={**(e.get("raw") or {}), "perception": rec})
        db.feed("ingest_done", f"{cam['name']}: {rec['summary'] or 'processed'}", {"event_id": event_id})
        try:
            watch.evaluate(event_id)
        except Exception as we:  # a watch failure must never lose the event
            db.feed("error", f"watch rules: {we}")
    except Exception as ex:
        db.update("events", "id", event_id, status="failed", error=str(ex)[:400])
        db.feed("error", f"{cam['name']}: {str(ex)[:200]}", {"event_id": event_id})
