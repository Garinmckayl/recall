"""Ring sandbox: a local stand-in for the Ring Partner API (api.amazonvision.com).

It implements the wire formats from the Ring Partner API documentation — JSON:API devices with
included status/capabilities, `history-events` with epoch-millisecond start/end and `links.next` cursors,
POST media downloads (`timestamp`/`duration`/`components`, 200 or 206, snapshots via 303 + pre-signed URL),
429 + Retry-After — and delivers *signed* Webhook v1.1 payloads (`X-Signature: sha256=...`) including the
device lifecycle events, so the whole ingest path — signature check, idempotency, clip fetch — is the production path.
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

ACCOUNT_ID = "ava1.ring.account.RECALLSANDBOX"
DEFAULT_DEVICES = [
    {"id": "ava1.ring.device.SANDBOXFRONTDOOR", "name": "Front Door", "zone": "entry", "model": "Ring Video Doorbell", "online": True},
    {"id": "ava1.ring.device.SANDBOXDRIVEWAY", "name": "Driveway", "zone": "exterior", "model": "Ring Spotlight Cam", "online": True},
    {"id": "ava1.ring.device.SANDBOXGARAGE", "name": "Garage", "zone": "entry", "model": "Ring Stick Up Cam", "online": True},
    {"id": "ava1.ring.device.SANDBOXBACKYARD", "name": "Backyard", "zone": "exterior", "model": "Ring Floodlight Cam", "online": True},
]
CLIP_MS = 20_000

_SEARCH = lambda: [config.DEMO_CLIPS_DIR, config.MEDIA_DIR / "raw", config.DATA_DIR / "uploads"]  # noqa: E731


# -- state ----------------------------------------------------------------------------

def _state_path() -> Path:
    config.SANDBOX_DIR.mkdir(parents=True, exist_ok=True)
    return config.SANDBOX_DIR / "state.json"


def load_state() -> dict:
    with _lock:
        p = _state_path()
        if p.exists():
            st = json.loads(p.read_text())
            if all("start_ms" in e for e in st.get("events", [])) and all("online" in d for d in st.get("devices", [])):
                return st
            st = {"devices": DEFAULT_DEVICES, "events": []}      # state written by an older sandbox format
            p.write_text(json.dumps(st, indent=1))
            return st
        st = {"devices": DEFAULT_DEVICES, "events": []}
        p.write_text(json.dumps(st, indent=1))
        return st


def save_state(st: dict) -> None:
    with _lock:
        _state_path().write_text(json.dumps(st, indent=1))


def reset_state() -> None:
    save_state({"devices": DEFAULT_DEVICES, "events": []})


ALLOWED_CLIP_SUFFIXES = {".mp4", ".mov"}


def resolve_clip(name: str) -> Optional[Path]:
    """A clip is a bare filename of a video that sits directly in one of the clip folders. Anything with a
    path component (../, absolute paths, subfolders) or a non-video suffix is refused — the name arrives from
    an unauthenticated demo endpoint and is later served back as the event's media."""
    if not name or name != Path(name).name or Path(name).suffix.lower() not in ALLOWED_CLIP_SUFFIXES:
        return None
    for d in _SEARCH():
        p = (d / name).resolve()
        if p.parent == d.resolve() and p.is_file():
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
    when = occurred_at or time.time()
    ev = {
        "id": "hist_" + uuid.uuid4().hex[:16],
        "type": "button_press" if kind == "doorbell" else "motion_detected",
        "device_id": device_id,
        "sub_type": "" if kind == "doorbell" else sub_type,
        "start_ms": ring_api.ms(when),
        "end_ms": ring_api.ms(when) + CLIP_MS,
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


def _envelope(data: dict) -> dict:
    return {"meta": {"version": "1.1", "time": time.strftime("%Y-%m-%dT%H:%M:%S.000000000Z", time.gmtime()),
                     "request_id": str(uuid.uuid4()), "account_id": ACCOUNT_ID}, "data": data}


def _webhook_resource(ev: dict) -> dict:
    """Webhook v1.1 `data` for motion_detected / button_press."""
    word = "ding" if ev["type"] == "button_press" else "motion"
    attrs = {"source": ev["device_id"], "source_type": "devices", "timestamp": ev["start_ms"]}
    if ev["type"] == "motion_detected":
        attrs.update(timestamp_readable=time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(ev["start_ms"] / 1000)),
                     sub_type=ev.get("sub_type") or "motion", component_ids=["0"])
    return {"id": f"{ev['device_id']}_{word}_{ev['start_ms']}", "type": ev["type"], "attributes": attrs,
            "relationships": {"devices": {"links": {"self": f"/v1/devices/{ev['device_id']}"}}}}


def _post_signed(payload: dict, url: Optional[str]) -> dict:
    raw = json.dumps(payload, separators=(",", ":")).encode()
    target = url or f"{config.SERVER_URL.rstrip('/')}/ring/webhook"
    try:
        r = httpx.post(target, content=raw, timeout=8.0, headers={
            "Content-Type": "application/json", "X-Signature": ring_api.sign(raw)})
        return {"url": target, "status": r.status_code, "request_id": payload["meta"]["request_id"]}
    except Exception as e:
        return {"url": target, "error": str(e)}


def deliver_webhook(ev: dict, url: Optional[str] = None) -> dict:
    return _post_signed(_envelope(_webhook_resource(ev)), url)


def set_device_online(device_id: str, online: bool, deliver: bool = True, at: Optional[float] = None,
                      webhook_url: Optional[str] = None) -> dict:
    """Flip a sandbox camera on/offline and deliver the device_online / device_offline lifecycle webhook."""
    with _lock:
        st = load_state()
        dev = next((d for d in st["devices"] if d["id"] == device_id), None)
        if dev is None:
            raise HTTPException(404, f"unknown device {device_id}")
        dev["online"] = online
        save_state(st)
    etype = "device_online" if online else "device_offline"
    stamp = ring_api.ms(at or time.time())
    data = {"id": f"{device_id}_{etype}_{stamp}", "type": etype,
            "attributes": {"source": device_id, "source_type": "devices", "timestamp": stamp},
            "relationships": {"devices": {"links": {"self": f"/v1/devices/{device_id}"}}}}
    return {"device": device_id, "online": online, "webhook": _post_signed(_envelope(data), webhook_url) if deliver else None}


# -- auth + endpoints -----------------------------------------------------------------

_hits: dict[str, list[float]] = {}
RATE_LIMIT = 100                                       # the documented 100 TPS per client_id


def _auth(authorization: Optional[str], request: Optional[Request] = None) -> None:
    if request is not None and (request.headers.get("cf-connecting-ip") or request.headers.get("x-forwarded-for")):
        raise HTTPException(404, "not found")          # the sandbox is for the app itself, not for the public internet
    ok = {ring_api.SANDBOX_TOKEN, config.RING_ACCESS_TOKEN} - {""}
    token = (authorization or "").removeprefix("Bearer ").strip()
    if token not in ok:
        raise HTTPException(401, "invalid or missing bearer access token")
    now = time.time()
    recent = [t for t in _hits.get(token, []) if now - t < 1.0]
    if len(recent) >= RATE_LIMIT:
        raise HTTPException(429, "rate limit exceeded", headers={"Retry-After": "1"})
    recent.append(now)
    _hits[token] = recent


def _device_resource(d: dict) -> dict:
    i = d["id"]
    rel = {k: {"data": {"type": f"device-{k}", "id": f"{i}.{k}"}, "links": {"related": f"/v1/devices/{i}/{k}"}}
           for k in ("status", "capabilities", "configurations", "location")}
    return {"type": "devices", "id": i, "attributes": {"name": d["name"], "zone": d["zone"], "model": d["model"]},
            "relationships": rel, "links": {"self": f"/v1/devices/{i}"}}


def _status_resource(d: dict) -> dict:
    return {"type": "device-status", "id": f"{d['id']}.status",
            "attributes": {"status": "online" if d.get("online", True) else "offline"}}


def _capabilities_resource(d: dict) -> dict:
    return {"type": "device-capabilities", "id": f"{d['id']}.capabilities",
            "attributes": {"components": {"items": [{"component_id": "0"}]}, "motion_detection": {"supported": True}}}


def _find_device(device_id: str) -> dict:
    for d in load_state()["devices"]:
        if d["id"] == device_id:
            return d
    raise HTTPException(404, "device not found")


@router.get("/v1/users/me")
def users_me(request: Request, authorization: Optional[str] = Header(None)):
    _auth(authorization, request)
    return {"data": {"type": "users", "id": ACCOUNT_ID, "attributes": {"account_id": ACCOUNT_ID}}}


@router.get("/v1/devices")
def devices(request: Request, include: str = "", authorization: Optional[str] = Header(None)):
    _auth(authorization, request)
    ds = load_state()["devices"]
    body: dict = {"meta": {"time": ring_api.iso(time.time())}, "data": [_device_resource(d) for d in ds]}
    want = {x.strip() for x in include.split(",")}
    inc = []
    for d in ds:
        if "status" in want:
            inc.append(_status_resource(d))
        if "capabilities" in want:
            inc.append(_capabilities_resource(d))
    if inc:
        body["included"] = inc
    return body


@router.get("/v1/devices/{device_id}")
def device(device_id: str, request: Request, authorization: Optional[str] = Header(None)):
    _auth(authorization, request)
    return {"data": _device_resource(_find_device(device_id))}


@router.get("/v1/devices/{device_id}/status")
def device_status(device_id: str, request: Request, authorization: Optional[str] = Header(None)):
    _auth(authorization, request)
    return {"data": _status_resource(_find_device(device_id))}


@router.get("/v1/devices/{device_id}/capabilities")
def device_capabilities(device_id: str, request: Request, authorization: Optional[str] = Header(None)):
    _auth(authorization, request)
    return {"data": _capabilities_resource(_find_device(device_id))}


PAGE_SIZE = 25


def _history_resource(e: dict) -> dict:
    hist = "ding" if e["type"] == "button_press" else "motion"
    return {"type": "history-events", "id": e["id"],
            "attributes": {"event_type": hist, "is_third_party_reviewed": False, "start": e["start_ms"], "end": e["end_ms"]},
            "relationships": {"source": {"data": {"type": "devices", "id": e["device_id"]}}}}


@router.get("/v1/history/devices/{device_id}/events")
def history(device_id: str, request: Request, event_types: str = "", authorization: Optional[str] = Header(None)):
    _auth(authorization, request)
    _find_device(device_id)
    want = {t.strip().split(".")[0] for t in event_types.split(",") if t.strip()}
    cursor = request.query_params.get("page[key]")
    before = ring_api._epoch(cursor) * 1000 if cursor else float("inf")
    evs = [e for e in load_state()["events"] if e["device_id"] == device_id and e["start_ms"] < before
           and (not want or ("ding" if e["type"] == "button_press" else "motion") in want)]
    evs.sort(key=lambda e: e["start_ms"], reverse=True)          # newest first, as documented
    page = evs[:PAGE_SIZE]
    body: dict = {"data": [_history_resource(e) for e in page], "links": {}}
    if len(evs) > PAGE_SIZE:
        nxt = f"/v1/history/devices/{device_id}/events?page[key]={ring_api.iso(page[-1]['start_ms'] / 1000)}"
        if event_types:
            nxt += f"&event_types={event_types}"
        body["links"]["next"] = nxt
    return body


def _event_at(device_id: str, ts_ms: int) -> dict:
    """The recorded event whose window covers the requested instant (the nearest one otherwise)."""
    evs = [e for e in load_state()["events"] if e["device_id"] == device_id]
    if not evs:
        raise HTTPException(404, "no recorded footage on this device")
    for e in evs:
        if e["start_ms"] - 1000 <= ts_ms <= e["end_ms"]:
            return e
    return min(evs, key=lambda e: abs(e["start_ms"] - ts_ms))


@router.post("/v1/devices/{device_id}/media/video/download")
async def video_download(device_id: str, request: Request, authorization: Optional[str] = Header(None)):
    _auth(authorization, request)
    _find_device(device_id)
    body = await request.json()
    if not isinstance(body.get("timestamp"), int) or not isinstance(body.get("duration"), int):
        raise HTTPException(400, "timestamp and duration (epoch milliseconds) are required")
    if body["timestamp"] > ring_api.ms(time.time()) + 1000 or body["duration"] > 900_000:
        raise HTTPException(400, "timestamp must be <= now and duration <= 900000 ms")
    if len(body.get("components") or []) > 1:
        raise HTTPException(400, "components takes exactly one entry")
    ev = _event_at(device_id, body["timestamp"])
    p = resolve_clip(ev["clip"])
    if not p:
        raise HTTPException(404, "clip missing")
    partial = body["timestamp"] + body["duration"] > ev["end_ms"] or body["timestamp"] < ev["start_ms"] - 1000
    return Response(p.read_bytes(), status_code=206 if partial else 200, media_type="video/mp4",
                    headers={"X-Media-Timestamp": str(max(body["timestamp"], ev["start_ms"])),
                             "X-Media-Length": str(min(body["duration"], ev["end_ms"] - ev["start_ms"]))})


_signed: dict[str, tuple[str, float]] = {}


@router.post("/v1/devices/{device_id}/media/image/download")
async def image_download(device_id: str, request: Request, authorization: Optional[str] = Header(None)):
    """Documented two-step flow: 303 See Other with a pre-signed, time-limited Location, then GET it."""
    _auth(authorization, request)
    _find_device(device_id)
    body = await request.json()
    if body.get("type") not in ("at_timestamp", "latest_in_range"):
        raise HTTPException(400, "type must be at_timestamp or latest_in_range")
    ts = body.get("timestamp") or body.get("end_timestamp") or ring_api.ms(time.time())
    ev = _event_at(device_id, int(ts))
    tok = uuid.uuid4().hex
    _signed[tok] = (ev["clip"], time.time() + 60)
    return Response(status_code=303, headers={"Location": f"{config.SERVER_URL.rstrip('/')}/ring-sandbox/signed/{tok}"})


@router.get("/signed/{token}")
def signed_image(token: str, request: Request):
    if request.headers.get("cf-connecting-ip") or request.headers.get("x-forwarded-for"):
        raise HTTPException(404, "not found")
    clip, exp = _signed.pop(token, ("", 0))
    p = resolve_clip(clip) if clip and exp > time.time() else None
    if not p:
        raise HTTPException(404, "expired or unknown")
    out = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-ss", "1", "-i", str(p), "-frames:v", "1", "-f", "image2pipe",
         "-vcodec", "mjpeg", "-"], capture_output=True, check=True, stdin=subprocess.DEVNULL)
    return Response(out.stdout, media_type="image/jpeg")
