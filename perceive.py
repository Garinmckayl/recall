"""PERCEIVE: Ring clip -> keyframes -> one structured JEV event record (Amazon Nova Pro).

The vision model only *observes* (who/what/doing-what, per actor, tracked across frames).
It never decides roles or concern — those are Jev decisions (roles.py), and it never names people.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from PIL import Image
import io

import aws
import config

ACTIONS = [
    "approaches_door", "rings_doorbell", "knocks", "waits_at_door", "leaves", "leaves_immediately",
    "enters_building", "exits_building", "enters_vehicle", "exits_vehicle", "vehicle_arrives",
    "vehicle_departs", "carries_object", "hands_object_to", "places_package", "picks_up_package",
    "walks_by", "lingers", "peers_into_windows", "raises_object", "runs", "opens_gate", "sits", "plays",
]

SYSTEM = (
    "You are the perception module of a home camera memory system. You describe ONLY what is visible, "
    "factually and neutrally. Never guess a person's name or identity. Never claim intent. If an object "
    "in someone's hand could be a weapon, describe it as 'an object consistent with a <type>' and set "
    "possible_weapon=true; when unsure, prefer false. Reply with a single JSON object and nothing else."
)

_PROMPT = """Camera: {camera} (zone: {zone}). Trigger: {kind}. Local time of day: {tod}.
You are given {n} keyframes from ONE short clip, in order, at t = {times} seconds.
Track every distinct actor (person, pet) across the frames and return JSON exactly like:
{{
 "scene": "<one factual sentence: setting, lighting, weather>",
 "lighting": "day|dusk|night",
 "actors": [{{
   "track": "A",
   "kind": "person|pet",
   "label": "<3-6 word noun phrase naming them, e.g. 'man in a blue jacket', 'pug dog'>",
   "description": "<one sentence: who, what they wear/look like, what they do>",
   "appearance": {{"gender_presentation": "man|woman|child|unknown", "age": "child|young adult|adult|older adult|unknown",
                  "top": "<colour + garment>", "bottom": "<colour + garment>", "headwear": "<or none>",
                  "hair": "<colour/length or unknown>", "build": "slim|average|heavy|unknown",
                  "uniform": true/false, "accessories": ["..."]}},
   "carrying": ["<objects held/carried, e.g. pizza box, cardboard package, food bag>"],
   "actions": [<zero or more of: {actions}>],
   "direction": "arriving|leaving|passing|lingering|stationary",
   "first_frame": <1-based>, "last_frame": <1-based>,
   "boxes": [{{"frame": <1-based>, "bbox": [x1, y1, x2, y2]}}]   // one entry for EVERY frame where this actor is visible; whole body; 0-1000 scale of that frame
 }}],
 "objects": [{{"label": "<snake_case e.g. pizza_box, package, food_bag, vehicle, handgun_like_object>", "holder": "<actor track or null>"}}],
 "interactions": [{{"a": "A", "b": "B", "type": "hands_object_to|talks_to|opens_door_for|follows"}}],
 "rings_doorbell": true/false, "knocks": true/false,
 "safety": {{"possible_weapon": true/false, "note": "<neutral description or empty>"}},
 "summary": "<one plain sentence describing the event, e.g. 'A man in a blue jacket delivers a pizza box to the front door and leaves.'>"
}}
Use an empty actors list if nobody/nothing is present. Keep it factual."""


def _run(cmd: list[str]) -> bytes:
    return subprocess.run(cmd, check=True, capture_output=True).stdout


def probe_duration(clip: Path) -> float:
    out = _run(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(clip)])
    return float(json.loads(out)["format"].get("duration", 0) or 0)


def keyframes(clip: Path, n: int | None = None) -> list[tuple[float, bytes]]:
    """n evenly spaced frames, downscaled. Portrait phone video is fine (scale by width)."""
    n = n or config.KEYFRAMES_PER_EVENT
    dur = probe_duration(clip) or 5.0
    frames = []
    for i in range(n):
        t = round(dur * (i + 0.5) / n, 2)
        jpeg = _run(["ffmpeg", "-loglevel", "error", "-ss", str(t), "-i", str(clip), "-frames:v", "1",
                     "-vf", f"scale='min({config.KEYFRAME_MAX_WIDTH},iw)':-2", "-q:v", "4",
                     "-f", "image2pipe", "-vcodec", "mjpeg", "-"])
        if jpeg:
            frames.append((t, jpeg))
    return frames


def time_of_day(ts: float) -> str:
    import datetime as dt
    h = dt.datetime.fromtimestamp(ts).hour
    if 5 <= h < 12:
        return f"morning ({h:02d}:00)"
    if 12 <= h < 17:
        return f"afternoon ({h:02d}:00)"
    if 17 <= h < 21:
        return f"evening ({h:02d}:00)"
    return f"night ({h:02d}:00)"


def save_thumb(event_id: str, frames: list[tuple[float, bytes]]) -> str:
    config.THUMBS_DIR.mkdir(parents=True, exist_ok=True)
    jpeg = frames[len(frames) // 2][1]
    im = Image.open(io.BytesIO(jpeg)).convert("RGB")
    im.thumbnail((360, 360))
    p = config.THUMBS_DIR / f"{event_id}.jpg"
    im.save(p, "JPEG", quality=80)
    return str(p)


def _snake(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(s).lower()).strip("_")


def _boxes(a: dict) -> dict:
    """Per-frame boxes -> {boxes, bbox_frame, bbox}; bbox is the largest box (used for the re-id crop)."""
    boxes = []
    for b in a.get("boxes") or []:
        try:
            bb = [max(0.0, min(1000.0, float(v))) for v in b["bbox"]]
            if len(bb) == 4 and bb[2] > bb[0] and bb[3] > bb[1]:
                boxes.append({"frame": int(b["frame"]), "bbox": bb})
        except (KeyError, TypeError, ValueError):
            continue
    legacy = a.get("bbox") if isinstance(a.get("bbox"), list) and len(a.get("bbox")) == 4 else None
    if not boxes and legacy:
        boxes = [{"frame": int(a.get("bbox_frame") or a.get("first_frame") or 1), "bbox": [float(v) for v in legacy]}]
    best = max(boxes, key=lambda b: (b["bbox"][2] - b["bbox"][0]) * (b["bbox"][3] - b["bbox"][1]), default=None)
    return {"boxes": boxes, "bbox_frame": best["frame"] if best else int(a.get("first_frame") or 1),
            "bbox": best["bbox"] if best else None}


def _norm(rec: dict) -> dict:
    """Coerce the model's JSON into the shape the rest of the pipeline relies on."""
    actors = []
    for i, a in enumerate(rec.get("actors") or []):
        if not isinstance(a, dict):
            continue
        ap = a.get("appearance") or {}
        actors.append({
            "track": str(a.get("track") or chr(65 + i)),
            "kind": "pet" if str(a.get("kind", "person")).lower() in ("pet", "animal", "dog", "cat") else "person",
            "description": str(a.get("description") or "")[:300],
            "appearance": {**{k: (v if not isinstance(v, str) else v.strip()) for k, v in ap.items()},
                           "label": str(a.get("label") or "").strip()[:60]},
            "carrying": [_snake(x) for x in (a.get("carrying") or []) if x],
            "actions": [_snake(x) for x in (a.get("actions") or []) if x],
            "direction": _snake(a.get("direction") or "") or "passing",
            "first_frame": int(a.get("first_frame") or 1),
            "last_frame": int(a.get("last_frame") or 1),
            **_boxes(a),
        })
    objects = [{"label": _snake(o.get("label", "")), "holder": o.get("holder")}
               for o in (rec.get("objects") or []) if isinstance(o, dict) and o.get("label")]
    safety = rec.get("safety") or {}
    return {
        "scene": str(rec.get("scene") or "")[:300],
        "lighting": str(rec.get("lighting") or ""),
        "actors": actors,
        "objects": objects,
        "interactions": [i for i in (rec.get("interactions") or []) if isinstance(i, dict)],
        "rings_doorbell": bool(rec.get("rings_doorbell")),
        "knocks": bool(rec.get("knocks")),
        "safety": {"possible_weapon": bool(safety.get("possible_weapon")),
                   "note": str(safety.get("note") or "")[:200]},
        "summary": str(rec.get("summary") or "")[:300],
    }


def perceive(clip: Path, camera_name: str, zone: str, kind: str, ts: float) -> tuple[dict, list[tuple[float, bytes]]]:
    frames = keyframes(clip)
    if not frames:
        raise RuntimeError(f"no frames decoded from {clip.name}")
    prompt = _PROMPT.format(
        camera=camera_name, zone=zone, kind=("doorbell pressed" if kind == "doorbell" else "motion detected"),
        tod=time_of_day(ts), n=len(frames), times=", ".join(str(t) for t, _ in frames),
        actions=", ".join(ACTIONS))
    rec = aws.vision_json(SYSTEM, prompt, [j for _, j in frames])
    return _norm(rec), frames
