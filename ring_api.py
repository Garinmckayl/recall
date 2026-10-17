"""Ring Partner API client + webhook plumbing, written against the Ring Partner API documentation.

Talks to https://api.amazonvision.com (JSON:API, OAuth2 bearer) when Ring credentials are configured,
and to the local sandbox (ring_sim.py, which implements the same documented wire formats) otherwise.
Both go through the exact same code below, so the pipeline never knows which one it is on.

Endpoints used (developer.amazon.com/docs/ring/api-documentation.html):
  POST https://oauth.ring.com/oauth/token                        refresh_token grant (proactive + on 401)
  GET  /v1/users/me                                              account id (webhook correlation)
  GET  /v1/devices?include=status,capabilities,location          discovery + camera-module components
  GET  /v1/devices/{id}/status                                   online / offline
  GET  /v1/history/devices/{id}/events?event_types=&page[key]=   history-events, cursor pagination
  POST /v1/devices/{id}/media/video/download                     {timestamp, duration, components:[{component_id}]} -> 200 / 206 MP4
  POST /v1/devices/{id}/media/image/download                     {type: at_timestamp, ...} -> 303 -> pre-signed GET
Webhooks v1.1: `X-Signature: sha256=<hex HMAC-SHA256 of the raw body>`; motion_detected, button_press and the
device lifecycle events; idempotency via meta.request_id; HTTP 200 within 5 seconds.
Rate limits: 100 TPS per client_id; HTTP 429 + Retry-After -> exponential backoff.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx

import config

LIVE_BASE = "https://api.amazonvision.com"
OAUTH_URL = "https://oauth.ring.com/oauth/token"
SANDBOX_TOKEN = "sandbox-token"

LIFECYCLE_EVENTS = ("device_added", "device_removed", "device_online", "device_offline")
MEDIA_EVENTS = ("motion_detected", "button_press")


def mode() -> str:
    return "live" if (config.RING_ACCESS_TOKEN or config.RING_REFRESH_TOKEN) else "sandbox"


def api_base() -> str:
    if config.RING_API_BASE:
        return config.RING_API_BASE.rstrip("/")
    if mode() == "live":
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
    if key is None and mode() == "live" and config.RING_HMAC_KEY == "sandbox-hmac-key":
        return False                                  # live platform + the published default key = anyone could forge events
    return hmac.compare_digest(sign(raw, key), header.strip())


# -- time -----------------------------------------------------------------------------

def _epoch(v: Any) -> float:
    """Ring sends epoch *milliseconds* (webhooks, history) or ISO 8601; return epoch seconds."""
    if isinstance(v, (int, float)):
        return float(v) / 1000.0 if v > 1e11 else float(v)
    if isinstance(v, str) and v:
        try:
            return _epoch(float(v))
        except ValueError:
            pass
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    return time.time()


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ms(ts: float) -> int:
    return int(round(ts * 1000))


# -- normalized events ----------------------------------------------------------------

@dataclass
class RingEvent:
    ring_event_id: str
    device_id: str
    type: str                     # motion_detected | button_press
    occurred_at: float            # epoch seconds
    sub_type: str = ""
    component_ids: list[str] = field(default_factory=list)
    request_id: str = ""
    account_id: str = ""
    duration_ms: int = 0          # known for history events (end - start)
    raw: dict = field(default_factory=dict)

    @property
    def kind(self) -> str:
        return "doorbell" if self.type == "button_press" else "motion"


@dataclass
class DeviceEvent:
    """Device lifecycle webhook: device_added / device_removed / device_online / device_offline."""
    type: str
    device_id: str
    occurred_at: float
    request_id: str = ""
    account_id: str = ""

    @property
    def status(self) -> str:
        return {"device_online": "online", "device_offline": "offline", "device_removed": "removed"}.get(self.type, "added")


def _device_id_from(obj: dict) -> str:
    attrs = obj.get("attributes") or {}
    if attrs.get("source"):
        return str(attrs["source"])
    rel = obj.get("relationships") or {}
    for key in ("devices", "device", "source"):
        r = rel.get(key) or {}
        if (r.get("data") or {}).get("id"):
            return str(r["data"]["id"])
        self_link = (r.get("links") or {}).get("self", "")
        if "/devices/" in self_link:
            return self_link.rsplit("/devices/", 1)[1].split("/")[0]
    return str(attrs.get("device_id") or obj.get("device_id") or "")


def parse_event(obj: dict, meta: Optional[dict] = None) -> RingEvent:
    """One motion/button webhook `data` resource (v1.1) or one `history-events` resource -> RingEvent."""
    attrs = obj.get("attributes") or {}
    meta = meta or {}
    etype = obj.get("type") or ""
    if etype == "history-events":
        hist = {"motion": "motion_detected", "ding": "button_press"}.get(attrs.get("event_type", ""), attrs.get("event_type", ""))
        start = _epoch(attrs.get("start"))
        end = _epoch(attrs.get("end")) if attrs.get("end") else start
        return RingEvent(ring_event_id=str(obj.get("id") or ""), device_id=_device_id_from(obj), type=hist,
                         occurred_at=start, sub_type=str(attrs.get("sub_type") or ""),
                         duration_ms=max(0, int((end - start) * 1000)), raw=obj)
    return RingEvent(
        ring_event_id=str(obj.get("id") or ""),
        device_id=_device_id_from(obj),
        type=etype or "motion_detected",
        occurred_at=_epoch(attrs.get("timestamp") or attrs.get("occurred_at")),
        sub_type=str(attrs.get("sub_type") or ""),
        component_ids=[str(c) for c in (attrs.get("component_ids") or [])],
        request_id=str(meta.get("request_id") or ""),
        account_id=str(meta.get("account_id") or ""),
        raw=obj,
    )


def _items(payload: dict) -> list[dict]:
    data = payload.get("data", payload)
    return [i for i in (data if isinstance(data, list) else [data]) if isinstance(i, dict)]


def parse_webhook(payload: dict) -> list[RingEvent]:
    """Webhook v1.1: {"meta": {version, time, request_id, account_id}, "data": <event resource>}."""
    meta = payload.get("meta") or {}
    out = [parse_event(i, meta) for i in _items(payload)]
    return [e for e in out if e.type in MEDIA_EVENTS and e.device_id]


def parse_lifecycle(payload: dict) -> list[DeviceEvent]:
    meta = payload.get("meta") or {}
    out = []
    for i in _items(payload):
        if i.get("type") in LIFECYCLE_EVENTS and _device_id_from(i):
            out.append(DeviceEvent(i["type"], _device_id_from(i), _epoch((i.get("attributes") or {}).get("timestamp")),
                                   str(meta.get("request_id") or ""), str(meta.get("account_id") or "")))
    return out


# -- OAuth ----------------------------------------------------------------------------

class TokenManager:
    """Access tokens live ~4 h, refresh tokens ~30 d and rotate on every refresh, so the newest pair is persisted.
    Refresh proactively from expires_in, and reactively on a 401."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.access = config.RING_ACCESS_TOKEN
        self.refresh = config.RING_REFRESH_TOKEN
        self.expires_at = 0.0 if self.refresh else float("inf")
        p = self._path()
        if self.refresh and p.exists():
            try:
                saved = json.loads(p.read_text())
                self.access, self.refresh, self.expires_at = saved["access"], saved["refresh"], saved["expires_at"]
            except (ValueError, KeyError):
                pass

    @staticmethod
    def _path() -> Path:
        return config.DATA_DIR / "ring_tokens.json"

    def can_refresh(self) -> bool:
        return bool(self.refresh and config.RING_CLIENT_ID and config.RING_CLIENT_SECRET)

    def token(self) -> str:
        with self._lock:
            if self.can_refresh() and time.time() > self.expires_at - 300:
                self._refresh()
            return self.access

    def force_refresh(self) -> bool:
        with self._lock:
            if not self.can_refresh():
                return False
            self._refresh()
            return True

    def _refresh(self) -> None:
        r = httpx.post(OAUTH_URL, timeout=30, data={
            "grant_type": "refresh_token", "refresh_token": self.refresh,
            "client_id": config.RING_CLIENT_ID, "client_secret": config.RING_CLIENT_SECRET})
        if r.status_code >= 400:
            raise RingError(f"token refresh failed: HTTP {r.status_code} (an expired refresh token needs the user to re-link in the Ring app)")
        t = r.json()
        self.access = t["access_token"]
        self.refresh = t.get("refresh_token", self.refresh)
        self.expires_at = time.time() + float(t.get("expires_in", 14400))
        p = self._path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"access": self.access, "refresh": self.refresh, "expires_at": self.expires_at}))
        p.chmod(0o600)


# -- client ---------------------------------------------------------------------------

class RingError(RuntimeError):
    pass


class RingClient:
    MAX_RETRIES = 4

    def __init__(self, base: Optional[str] = None, token: Optional[str] = None) -> None:
        self.base = (base or api_base()).rstrip("/")
        self._fixed = token
        self.tokens = None if (token or mode() == "sandbox") else TokenManager()
        self._http = httpx.Client(timeout=60.0, follow_redirects=False)
        self._multicam: dict[str, list[str]] = {}

    def _bearer(self) -> str:
        if self._fixed:
            return self._fixed
        return self.tokens.token() if self.tokens else SANDBOX_TOKEN

    def _req(self, method: str, path: str, **kw) -> httpx.Response:
        refreshed = False
        for attempt in range(self.MAX_RETRIES + 1):
            r = self._http.request(method, f"{self.base}{path}", headers={"Authorization": f"Bearer {self._bearer()}"}, **kw)
            if r.status_code == 401 and self.tokens and not refreshed and self.tokens.force_refresh():
                refreshed = True
                continue
            if r.status_code == 429 and attempt < self.MAX_RETRIES:
                time.sleep(min(30.0, float(r.headers.get("Retry-After") or 2 ** attempt)))
                continue
            if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                return r
            if r.status_code >= 400:
                raise RingError(f"{method} {path} -> HTTP {r.status_code}: {r.text[:200]}")
            return r
        raise RingError(f"{method} {path} -> HTTP 429 after {self.MAX_RETRIES} retries")

    def _follow(self, r: httpx.Response) -> httpx.Response:
        """Redirects: media may be served by another host, and image downloads answer 303 with a pre-signed URL
        (which must not receive our bearer token)."""
        for _ in range(4):
            if r.status_code not in (301, 302, 303, 307, 308):
                return r
            r = self._http.get(httpx.URL(self.base).join(r.headers["location"]))
            if r.status_code >= 400:
                raise RingError(f"redirected download -> HTTP {r.status_code}")
        return r

    # -- account + devices --

    def me(self) -> dict:
        return self._req("GET", "/v1/users/me").json().get("data", {})

    def list_devices(self) -> list[dict]:
        """Devices normalized to {id, name, zone, model, online, components}. Zone/model are not in the documented
        device resource; they are read if present and otherwise left to defaults."""
        body = self._req("GET", "/v1/devices", params={"include": "status,capabilities,location"}).json()
        included = {(i.get("type"), i.get("id")): i for i in body.get("included", [])}
        out = []
        for d in body.get("data", []):
            a = d.get("attributes") or {}
            rel = d.get("relationships") or {}

            def inc(name: str) -> dict:
                ref = (rel.get(name) or {}).get("data") or {}
                return (included.get((ref.get("type"), ref.get("id"))) or {}).get("attributes") or {}

            status = inc("status")
            caps = inc("capabilities")
            comps = [str(c.get("component_id") or c.get("id")) for c in (caps.get("components") or {}).get("items", [])
                     if isinstance(c, dict)]
            if len(comps) > 1:
                self._multicam[d["id"]] = comps
            state = str(status.get("status") or status.get("state") or "").lower()
            out.append({
                "id": d["id"],
                "name": a.get("name") or a.get("label") or d["id"],
                "zone": a.get("zone") or "exterior",
                "model": a.get("model") or "",
                "online": None if not state else state == "online",
                "components": comps,
            })
        return out

    def device_status(self, device_id: str) -> dict:
        return self._req("GET", f"/v1/devices/{device_id}/status").json().get("data", {}).get("attributes", {})

    # -- history --

    def device_events(self, device_id: str, since: float = 0.0, event_types: str = "motion,ding",
                      max_pages: int = 20) -> list[RingEvent]:
        """History, newest first, following links.next. History events are device-level, so they carry no
        component ids and no sub_type unless filtered (event_types=motion.human)."""
        evs: list[RingEvent] = []
        path, params = f"/v1/history/devices/{device_id}/events", {"event_types": event_types}
        for _ in range(max_pages):
            body = self._req("GET", path, params=params).json()
            page = [parse_event(e) for e in body.get("data", []) if e.get("type", "history-events") == "history-events"]
            for e in page:
                e.device_id = e.device_id or device_id
            evs += page
            nxt = (body.get("links") or {}).get("next")
            if not page or not nxt or (since and page[-1].occurred_at <= since):
                break
            path, params = nxt, None
        return sorted((e for e in evs if e.occurred_at > since and e.type in MEDIA_EVENTS), key=lambda e: e.occurred_at)

    # -- media --

    def _components(self, ev: RingEvent) -> list[dict]:
        """Multi-camera devices (e.g. Ring Elite) need exactly one {component_id}; single-camera devices send none."""
        if ev.device_id not in self._multicam:
            return []
        cid = ev.component_ids[0] if ev.component_ids else self._multicam[ev.device_id][0]
        return [{"component_id": str(cid)}]

    def download_clip(self, ev: RingEvent, seconds: float = 20.0, pre_roll: float = 0.0) -> bytes:
        body: dict[str, Any] = {"timestamp": ms(ev.occurred_at - pre_roll),
                                "duration": min(900_000, int(seconds * 1000) if not ev.duration_ms else max(ev.duration_ms, 5000))}
        comps = self._components(ev)
        if comps:
            body["components"] = comps
        r = self._follow(self._req("POST", f"/v1/devices/{ev.device_id}/media/video/download", json=body))
        return r.content                              # 200 = full clip, 206 = partial (device was offline / past the recording edge)

    def download_snapshot(self, ev: RingEvent) -> bytes:
        body: dict[str, Any] = {"type": "at_timestamp", "timestamp": ms(ev.occurred_at), "image_options": {"format": "jpeg"}}
        comps = self._components(ev)
        if comps:
            body["components"] = comps
        return self._follow(self._req("POST", f"/v1/devices/{ev.device_id}/media/image/download", json=body)).content


_client: Optional[RingClient] = None


def client() -> RingClient:
    global _client
    if _client is None or _client.base != api_base():
        _client = RingClient()
    return _client
