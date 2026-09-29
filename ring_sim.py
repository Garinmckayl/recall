"""Ring sandbox: a local stand-in for the Ring Partner API (api.amazonvision.com).

It serves the same endpoints the real RingClient calls (devices, event history, clip/snapshot
download) as JSON:API, and can deliver *signed* webhooks (`X-Signature: sha256=...`) to the app,
so the whole ingest path — signature check, idempotency, clip fetch — is the production path.
Mounted by server.py at /ring-sandbox. Clips come from demo_clips/ (your staged footage) or media/raw.
"""
from __future__ import annotations

import json
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import Response

import config
import ring_api

router = APIRouter(prefix="/ring-sandbox")
_lock = threading.RLock()

DEFAULT_DEVICES = [
    {"id": "dev_front_door", "name": "Front Door", "zone": "entry", "model": "Ring Video Doorbell"},
    {"id": "dev_driveway", "name": "Driveway", "zone": "exterior", "model": "Ring Spotlight Cam"},
    {"id": "dev_garage", "name": "Garage", "zone": "entry", "model": "Ring Stick Up Cam"},
    {"id": "dev_backyard", "name": "Backyard", "zone": "exterior", "model": "Ring Floodlight Cam"},
]

_SEARCH = lambda: [config.DEMO_CLIPS_DIR, config.MEDIA_DIR / "raw", config.DATA_DIR / "uploads"]  # noqa: E731


# -- state ----------------------------------------------------------------------------

def _state_path() -> Path:
    config.SANDBOX_DIR.mkdir(parents=True, exist_ok=True)
    return config.SANDBOX_DIR / "state.json"


def load_state() -> dict:
    with _lock:
        p = _state_path()
        if p.exists():
            return json.loads(p.read_text())
        st = {"devices": DEFAULT_DEVICES, "events": []}
        p.write_text(json.dumps(st, indent=1))
        return st


def save_state(st: dict) -> None:
    with _lock:
        _state_path().write_text(json.dumps(st, indent=1))


def reset_state() -> None:
    save_state({"devices": DEFAULT_DEVICES, "events": []})


def resolve_clip(name: str) -> Optional[Path]:
    for d in _SEARCH():
        p = d / name
        if p.exists():
            return p
    return None


def list_clips() -> list[dict]:
    """Clips available to emit (demo_clips/ manifest labels win over filenames)."""
    labels: dict[str, str] = {}
    man = config.DEMO_CLIPS_DIR / "manifest.json"
    if man.exists():
        try:
            for e in json.loads(man.read_text()).get("events", []):
                if e.get("label"):
                    labels[e["clip"]] = e["label"]
        except ValueError:
            pass
    seen, out = set(), []
    for d in _SEARCH():
        if d.exists():
            for p in sorted(d.glob("*.mp4")) + sorted(d.glob("*.mov")):
                if p.name not in seen:
                    seen.add(p.name)
                    out.append({"name": p.name, "label": labels.get(p.name, p.name)})
    return out


# -- emitting events ------------------------------------------------------------------

def emit(device_id: str, clip: str, kind: str = "motion", occurred_at: Optional[float] = None,
         sub_type: str = "human", deliver: bool = True, webhook_url: Optional[str] = None) -> dict:
    """Record an event in the sandbox history and (optionally) deliver the signed webhook."""
    if resolve_clip(clip) is None:
        raise HTTPException(404, f"clip {clip} not found in demo_clips/ or media/raw/")
    st = load_state()
    if device_id not in {d["id"] for d in st["devices"]}:
        raise HTTPException(404, f"unknown device {device_id}")
    ev = {
        "id": "evt_" + uuid.uuid4().hex[:12],
        "type": "button_press" if kind == "doorbell" else "motion_detected",
        "device_id": device_id,
        "sub_type": "" if kind == "doorbell" else sub_type,
        "occurred_at": occurred_at or time.time(),
        "clip": clip,
    }
    with _lock:
        st = load_state()
        st["events"].append(ev)
        save_state(st)
    result = {"event": ev, "webhook": None}
    if deliver:
        result["webhook"] = deliver_webhook(ev, webhook_url)
    return result


def _resource(ev: dict) -> dict:
    return {
        "type": ev["type"], "id": ev["id"],
        "attributes": {"sub_type": ev.get("sub_type", ""), "occurred_at": ring_api.iso(ev["occurred_at"]),
                       "component_ids": [0]},
        "relationships": {"device": {"data": {"type": "device", "id": ev["device_id"]}}},
    }


def deliver_webhook(ev: dict, url: Optional[str] = None) -> dict:
    """POST the Webhook-v1.1-shaped payload, HMAC-signed over the raw body bytes."""
    payload = {"meta": {"request_id": "req_" + uuid.uuid4().hex[:16], "version": "1.1",
                        "timestamp": ring_api.iso(time.time())},
               "data": _resource(ev)}
    raw = json.dumps(payload, separators=(",", ":")).encode()
    target = url or f"{config.SERVER_URL.rstrip('/')}/ring/webhook"
    try:
        r = httpx.post(target, content=raw, timeout=8.0, headers={
            "Content-Type": "application/json", "X-Signature": ring_api.sign(raw)})
        return {"url": target, "status": r.status_code, "request_id": payload["meta"]["request_id"]}
    except Exception as e:
        return {"url": target, "error": str(e)}


# -- auth + endpoints -----------------------------------------------------------------

def _auth(authorization: Optional[str]) -> None:
    ok = {ring_api.SANDBOX_TOKEN, config.RING_ACCESS_TOKEN} - {""}
    if not authorization or authorization.removeprefix("Bearer ").strip() not in ok:
        raise HTTPException(401, "invalid or missing bearer access token")


def _device_resource(d: dict) -> dict:
    return {"type": "device", "id": d["id"],
            "attributes": {"name": d["name"], "zone": d["zone"], "model": d["model"]},
            "links": {"self": f"/v1/devices/{d['id']}"}}


@router.get("/v1/devices")
def devices(authorization: Optional[str] = Header(None)):
    _auth(authorization)
    return {"data": [_device_resource(d) for d in load_state()["devices"]]}


@router.get("/v1/devices/{device_id}")
def device(device_id: str, authorization: Optional[str] = Header(None)):
    _auth(authorization)
    for d in load_state()["devices"]:
        if d["id"] == device_id:
            return {"data": _device_resource(d)}
    raise HTTPException(404, "device not found")


@router.get("/v1/history/devices/{device_id}/events")
def history(device_id: str, since: Optional[str] = None, authorization: Optional[str] = Header(None)):
    _auth(authorization)
    floor = ring_api._epoch(since) if since else 0.0
    evs = [e for e in load_state()["events"] if e["device_id"] == device_id and e["occurred_at"] > floor]
    evs.sort(key=lambda e: e["occurred_at"])
    return {"data": [_resource(e) for e in evs]}


def _event_for(device_id: str, body: dict) -> dict:
    evs = [e for e in load_state()["events"] if e["device_id"] == device_id]
    if body.get("event_id"):
        for e in evs:
            if e["id"] == body["event_id"]:
                return e
        raise HTTPException(404, "no such event on this device")
    if not evs:
        raise HTTPException(404, "no recorded events on this device")
    want = ring_api._epoch(body.get("start_time") or body.get("time"))
    return min(evs, key=lambda e: abs(e["occurred_at"] - want))


@router.post("/v1/devices/{device_id}/media/video/download")
async def video_download(device_id: str, request: Request, authorization: Optional[str] = Header(None)):
    _auth(authorization)
    ev = _event_for(device_id, await request.json())
    p = resolve_clip(ev["clip"])
    if not p:
        raise HTTPException(404, "clip missing")
    return Response(p.read_bytes(), media_type="video/mp4")


@router.post("/v1/devices/{device_id}/media/image/download")
async def image_download(device_id: str, request: Request, authorization: Optional[str] = Header(None)):
    _auth(authorization)
    ev = _event_for(device_id, await request.json())
    p = resolve_clip(ev["clip"])
    if not p:
        raise HTTPException(404, "clip missing")
    out = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-ss", "1", "-i", str(p), "-frames:v", "1", "-f", "image2pipe",
         "-vcodec", "mjpeg", "-"], capture_output=True, check=True)
    return Response(out.stdout, media_type="image/jpeg")
