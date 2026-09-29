"""Ring Partner API client + webhook plumbing.

Talks to https://api.amazonvision.com (JSON:API, OAuth2 bearer) when RING_ACCESS_TOKEN is set,
and to the local sandbox (ring_sim.py, same endpoints) otherwise. Both go through the exact same
code path below, so the pipeline never knows which one it is on.

Endpoints used (from developer.amazon.com/docs/ring/api-documentation.html):
  GET  /v1/devices?include=status,capabilities,location
  GET  /v1/history/devices/{device_id}/events
  POST /v1/devices/{device_id}/media/video/download      -> MP4
  POST /v1/devices/{device_id}/media/image/download      -> JPEG
Webhooks: `X-Signature: sha256=<hex HMAC-SHA256 of the raw body>`, events motion_detected /
button_press, idempotency via meta.request_id, HTTP 200 within 5 seconds.

NOTE: the docs page we could read truncated the Webhook v1.1 payload and the media-download
request schemas. Parsing below is deliberately tolerant; see FRICTION_LOG.md.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

import config

LIVE_BASE = "https://api.amazonvision.com"
SANDBOX_TOKEN = "sandbox-token"


def mode() -> str:
    return "live" if config.RING_ACCESS_TOKEN else "sandbox"


def api_base() -> str:
    if config.RING_API_BASE:
        return config.RING_API_BASE.rstrip("/")
    if config.RING_ACCESS_TOKEN:
        return LIVE_BASE
    return f"{config.SERVER_URL.rstrip('/')}/ring-sandbox"


# -- signatures -----------------------------------------------------------------------

def sign(raw: bytes, key: str | None = None) -> str:
    key = key or config.RING_HMAC_KEY
    return "sha256=" + hmac.new(key.encode(), raw, hashlib.sha256).hexdigest()


def verify_signature(raw: bytes, header: Optional[str], key: str | None = None) -> bool:
    """Constant-time check of X-Signature against the RAW request body."""
    if not header:
        return False
    return hmac.compare_digest(sign(raw, key), header.strip())


# -- normalized events ----------------------------------------------------------------

@dataclass
class RingEvent:
    ring_event_id: str
    device_id: str
    type: str                     # motion_detected | button_press
    occurred_at: float            # epoch seconds
    sub_type: str = ""
    component_ids: list[int] = field(default_factory=list)
    request_id: str = ""
    raw: dict = field(default_factory=dict)

    @property
    def kind(self) -> str:
        return "doorbell" if self.type == "button_press" else "motion"


def _epoch(v: Any) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str) and v:
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    return time.time()


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_event(obj: dict, meta: Optional[dict] = None) -> RingEvent:
    """One JSON:API event resource (history item or webhook `data`) -> RingEvent."""
    attrs = obj.get("attributes") or {}
    rel = (obj.get("relationships") or {}).get("device", {}).get("data", {}) or {}
    device_id = rel.get("id") or attrs.get("device_id") or obj.get("device_id") or ""
    etype = obj.get("type") or attrs.get("type") or "motion_detected"
    return RingEvent(
        ring_event_id=str(obj.get("id") or attrs.get("event_id") or ""),
        device_id=str(device_id),
        type=etype,
        occurred_at=_epoch(attrs.get("occurred_at") or attrs.get("timestamp") or obj.get("occurred_at")),
        sub_type=str(attrs.get("sub_type") or ""),
        component_ids=list(attrs.get("component_ids") or []),
        request_id=str((meta or {}).get("request_id") or ""),
        raw=obj,
    )


def parse_webhook(payload: dict) -> list[RingEvent]:
    """Webhook v1.1: {"meta": {...request_id...}, "data": <event resource | [resources]>}."""
    meta = payload.get("meta") or {}
    data = payload.get("data", payload)
    items = data if isinstance(data, list) else [data]
    out = [parse_event(i, meta) for i in items if isinstance(i, dict)]
    return [e for e in out if e.type in ("motion_detected", "button_press") and e.device_id]


# -- client ---------------------------------------------------------------------------

class RingError(RuntimeError):
    pass


class RingClient:
    def __init__(self, base: Optional[str] = None, token: Optional[str] = None) -> None:
        self.base = (base or api_base()).rstrip("/")
        self.token = token or config.RING_ACCESS_TOKEN or SANDBOX_TOKEN
        self._http = httpx.Client(timeout=60.0, headers={"Authorization": f"Bearer {self.token}"})

    def _req(self, method: str, path: str, **kw) -> httpx.Response:
        r = self._http.request(method, f"{self.base}{path}", **kw)
        if r.status_code >= 400:
            raise RingError(f"{method} {path} -> HTTP {r.status_code}: {r.text[:200]}")
        return r

    def list_devices(self) -> list[dict]:
        """Devices (cameras/doorbells), normalized to {id, name, zone, model}."""
        body = self._req("GET", "/v1/devices", params={"include": "status,capabilities,location"}).json()
        out = []
        for d in body.get("data", []):
            a = d.get("attributes") or {}
            out.append({
                "id": d["id"],
                "name": a.get("name") or a.get("label") or d["id"],
                "zone": a.get("zone") or (a.get("location") or {}).get("zone") or "exterior",
                "model": a.get("model") or a.get("device_type") or "",
            })
        return out

    def device_events(self, device_id: str, since: float = 0.0) -> list[RingEvent]:
        params = {"since": iso(since)} if since else {}
        body = self._req("GET", f"/v1/history/devices/{device_id}/events", params=params).json()
        evs = [parse_event(e) for e in body.get("data", [])]
        for e in evs:
            e.device_id = e.device_id or device_id
        return [e for e in evs if e.occurred_at > since]

    def download_clip(self, ev: RingEvent, seconds: float = 20.0) -> bytes:
        body = {"components": ev.component_ids or [0], "event_id": ev.ring_event_id,
                "start_time": iso(ev.occurred_at), "end_time": iso(ev.occurred_at + seconds)}
        return self._req("POST", f"/v1/devices/{ev.device_id}/media/video/download", json=body).content

    def download_snapshot(self, ev: RingEvent) -> bytes:
        body = {"components": ev.component_ids or [0], "event_id": ev.ring_event_id,
                "time": iso(ev.occurred_at), "format": "jpeg"}
        return self._req("POST", f"/v1/devices/{ev.device_id}/media/image/download", json=body).content


_client: Optional[RingClient] = None


def client() -> RingClient:
    global _client
    if _client is None or _client.base != api_base():
        _client = RingClient()
    return _client
