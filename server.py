"""Recall server: UI + REST API + signed Ring webhook + MCP (Alexa+) + Ring sandbox.

    python3 -m uvicorn server:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
import threading
import time
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response

import aws
import config
import db
import digest
import identity
import jev
import pipeline
import query
import ring_api
import ring_sim
import roles
import views

@asynccontextmanager
async def _lifespan(_: FastAPI):
    db.conn()

    def warm() -> None:
        for _ in range(30):  # the sandbox lives in this same process: wait until we are serving
            try:
                pipeline.sync_devices()
                return
            except Exception:
                time.sleep(1.0)

    threading.Thread(target=warm, daemon=True, name="ring-device-sync").start()
    yield


app = FastAPI(title="Recall", lifespan=_lifespan)
app.include_router(ring_sim.router)


# -- UI + media -----------------------------------------------------------------------

@app.get("/")
def index():
    return FileResponse(config.STATIC_DIR / "index.html", media_type="text/html")


@app.get("/health")
def health():
    return {"ok": True}


def _file(path: Optional[str], media_type: str) -> FileResponse:
    if not path or not os.path.exists(path):
        raise HTTPException(404)
    return FileResponse(path, media_type=media_type)


@app.get("/media/clip/{event_id}.mp4")
def media_clip(event_id: str):
    e = db.one("SELECT clip_path FROM events WHERE id=?", (event_id,))
    return _file(e and e["clip_path"], "video/mp4")


@app.get("/media/thumb/{event_id}.jpg")
def media_thumb(event_id: str):
    e = db.one("SELECT thumb_path FROM events WHERE id=?", (event_id,))
    return _file(e and e["thumb_path"], "image/jpeg")


@app.get("/media/person/{person_id}.jpg")
def media_person(person_id: str):
    p = db.one("SELECT thumb_path FROM persons WHERE id=?", (person_id,))
    return _file(p and p["thumb_path"], "image/jpeg")


# -- state / cameras / events / people ------------------------------------------------

@app.get("/api/state")
def api_state():
    eng = aws.engine_report()
    c = lambda t: (db.one(f"SELECT COUNT(*) AS n FROM {t}") or {"n": 0})["n"]  # noqa: E731
    return {
        "ring": {"mode": ring_api.mode(), "base": ring_api.api_base()},
        "engines": {"vision": eng.get("vision", f"Amazon Nova Pro ({config.NOVA_VISION_MODEL})"),
                    "embed": eng.get("embed_image", f"Titan ({config.TITAN_IMAGE_EMBED})"),
                    "decide": jev.client().engine_name, "narrate": eng.get("text", f"Amazon Nova Lite ({config.NOVA_TEXT_MODEL})")},
        "counts": {"events": c("events"), "people": c("persons"),
                   "rules": (db.one("SELECT COUNT(*) AS n FROM watch_rules WHERE active=1") or {"n": 0})["n"],
                   "alerts": c("alerts")},
        "now": time.time(),
    }


@app.get("/api/digest")
def api_digest():
    return digest.build()


@app.get("/api/cameras")
def api_cameras():
    out = []
    for cam in db.q("SELECT * FROM cameras ORDER BY name"):
        s = db.one("SELECT COUNT(*) AS n, MAX(ts) AS last FROM events WHERE camera_id=?", (cam["id"],))
        out.append({"id": cam["id"], "name": cam["name"], "zone": cam["zone"],
                    "event_count": s["n"], "last_event_ts": s["last"]})
    return out


@app.get("/api/events")
def api_events(camera: Optional[str] = None, limit: int = 60, offset: int = 0):
    sql, args = "SELECT * FROM events", []
    if camera:
        sql += " WHERE camera_id=?"
        args.append(camera)
    sql += " ORDER BY ts DESC LIMIT ? OFFSET ?"
    return [views.event_dict(e) for e in db.q(sql, args + [min(limit, 200), offset])]


@app.get("/api/events/{event_id}")
def api_event(event_id: str):
    e = db.one("SELECT * FROM events WHERE id=?", (event_id,))
    if not e:
        raise HTTPException(404, "no such event")
    return views.event_dict(e, full=True)


@app.get("/api/people")
def api_people():
    return [views.person_dict(p) for p in db.q("SELECT * FROM persons ORDER BY last_ts DESC")]


@app.get("/api/people/{person_id}")
def api_person(person_id: str):
    p = db.one("SELECT * FROM persons WHERE id=?", (person_id,))
    if not p:
        raise HTTPException(404)
    rows = db.q("SELECT DISTINCT e.* FROM events e JOIN actors a ON a.event_id=e.id WHERE a.person_id=? ORDER BY e.ts DESC", (person_id,))
    return {**views.person_dict(p), "events": [views.event_dict(e) for e in rows]}


@app.post("/api/people/{person_id}/name")
def api_name_person(person_id: str, payload: dict):
    if not db.one("SELECT 1 FROM persons WHERE id=?", (person_id,)):
        raise HTTPException(404)
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "name required")
    identity.name_person(person_id, name, payload.get("relation") or "", payload.get("is_resident"))
    roles.aggregate(person_id)
    return views.person_dict(db.one("SELECT * FROM persons WHERE id=?", (person_id,)))


@app.post("/api/people/{person_id}/merge")
def api_merge_person(person_id: str, payload: dict):
    """Owner correction: this person and `into` are the same individual."""
    try:
        merged = identity.merge_persons(person_id, payload.get("into") or "")
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.feed("info", f"Merged {person_id} into {merged['id']}", {"person_id": merged["id"]})
    return views.person_dict(merged)


@app.post("/api/actors/{actor_id}/reassign")
def api_reassign_actor(actor_id: int, payload: dict):
    """Owner correction: this sighting is someone else (an existing person, or a new one when person_id is null)."""
    try:
        out = identity.reassign_actor(actor_id, payload.get("person_id"))
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.feed("info", "Sighting reassigned", {"person_id": (out["to"] or {}).get("id")})
    return {"from": views.person_dict(out["from"]), "to": views.person_dict(out["to"])}


@app.get("/api/graph")
def api_graph():
    """The persistent memory graph: people <-> cameras / objects / roles."""
    nodes, edges = [], []
    for c in db.q("SELECT * FROM cameras"):
        nodes.append({"id": c["id"], "type": "camera", "label": c["name"]})
    for p in db.q("SELECT * FROM persons"):
        nodes.append({"id": p["id"], "type": "person", "label": p.get("name") or p.get("label"), "role": p.get("role")})
        for r in db.q("SELECT e.camera_id, COUNT(*) AS n FROM actors a JOIN events e ON e.id=a.event_id "
                      "WHERE a.person_id=? GROUP BY e.camera_id", (p["id"],)):
            edges.append({"source": p["id"], "target": r["camera_id"], "type": "appeared_at", "weight": r["n"]})
        for r in db.q("SELECT carrying FROM actors WHERE person_id=?", (p["id"],)):
            for obj in r["carrying"] or []:
                nid = f"obj:{obj}"
                if not any(n["id"] == nid for n in nodes):
                    nodes.append({"id": nid, "type": "object", "label": obj.replace("_", " ")})
                edges.append({"source": p["id"], "target": nid, "type": "carried", "weight": 1})
    return {"nodes": nodes, "edges": edges}


# -- ask / rules / alerts / feed ------------------------------------------------------

@app.post("/api/ask")
def api_ask(payload: dict):
    q = (payload.get("q") or "").strip()
    if not q:
        raise HTTPException(400, "empty question")
    return query.ask(q, payload.get("context") or {})


@app.get("/api/rules")
def api_rules():
    return db.q("SELECT id, text, kind, person_id, active, created, last_fired FROM watch_rules WHERE active=1 ORDER BY id DESC")


@app.delete("/api/rules/{rule_id}")
def api_delete_rule(rule_id: int):
    db.update("watch_rules", "id", rule_id, active=0)
    return {"deleted": rule_id}


@app.get("/api/alerts")
def api_alerts(limit: int = 30):
    return db.q("SELECT id, ts, message, event_id, rule_id FROM alerts ORDER BY id DESC LIMIT ?", (limit,))


@app.get("/api/feed")
def api_feed(after: int = 0):
    return [{"id": r["id"], "ts": r["ts"], "type": r["type"], "message": r["message"], "data": r["data"]}
            for r in db.feed_after(after)]


# -- Ring: webhook + sync -------------------------------------------------------------

@app.post("/ring/webhook")
async def ring_webhook(request: Request):
    """Ring webhook receiver: verify X-Signature over the RAW body, dedupe on meta.request_id,
    acknowledge immediately (Ring requires HTTP 200 within 5s) and process asynchronously."""
    raw = await request.body()
    if not ring_api.verify_signature(raw, request.headers.get("x-signature")):
        raise HTTPException(401, "invalid webhook signature")
    try:
        payload = json.loads(raw)
    except ValueError:
        raise HTTPException(400, "invalid JSON")
    rid = str((payload.get("meta") or {}).get("request_id") or "")
    if rid:
        if db.one("SELECT 1 FROM webhooks_seen WHERE request_id=?", (rid,)):
            return {"status": "duplicate", "request_id": rid}
        db.insert("webhooks_seen", request_id=rid, ts=time.time())
    accepted = []
    for ev in ring_api.parse_webhook(payload):
        eid = pipeline.accept(ev)
        if eid:
            accepted.append(eid)
    return {"status": "accepted", "events": accepted}


@app.post("/api/ring/sync")
def api_ring_sync():
    try:
        return pipeline.sync()
    except Exception as e:
        raise HTTPException(502, f"Ring sync failed: {e}")


# -- demo controls --------------------------------------------------------------------

@app.get("/api/demo/clips")
def api_demo_clips():
    return ring_sim.list_clips()


@app.post("/api/demo/emit")
def api_demo_emit(payload: dict):
    cam = db.one("SELECT * FROM cameras WHERE id=? OR name=?", (payload.get("camera"), payload.get("camera")))
    if not cam:
        raise HTTPException(400, "unknown camera")
    if not payload.get("clip"):
        raise HTTPException(400, "clip required")
    return ring_sim.emit(cam["ring_device_id"], payload["clip"], payload.get("kind") or "motion")


@app.post("/api/demo/seed")
def api_demo_seed(payload: Optional[dict] = None):
    import seed
    threading.Thread(target=seed.run, kwargs={"reset": bool((payload or {}).get("reset", True))},
                     daemon=True, name="seed").start()
    return {"started": True}


# -- MCP (Alexa+): Streamable HTTP, JSON-RPC 2.0, protocol 2025-11-25 ------------------

MCP_PROTOCOL = "2025-11-25"
MCP_SERVER = {"name": "recall", "title": "Recall", "version": "2.0.0"}


def _mcp_ask(args: dict) -> dict:
    q = (args.get("question") or "").strip()
    if not q:
        raise ValueError("question required")
    r = query.ask(q, {"focus_person_id": args.get("focus_person_id")})
    return {"answer": r["answer"], "operator": r["operator"], "confidence": r["confidence"],
            "citations": [{"when": c["ts"], "camera": c["camera_name"], "label": c["label"],
                           "clip_url": c["clip_url"], "t_offset": c["t_offset"]} for c in r["citations"]],
            "watch_rule": r["watch_rule"], "focus_person_id": r["focus"]["person_id"]}


def _mcp_last_seen(args: dict) -> dict:
    who = (args.get("person") or "").strip()
    if not who:
        raise ValueError("person required")
    return _mcp_ask({"question": f"Where was {who} last seen?"})


def _mcp_timeline(args: dict) -> dict:
    n = min(int(args.get("limit", 10)), 50)
    evs = db.q("SELECT * FROM events WHERE status='processed' ORDER BY ts DESC LIMIT ?", (n,))
    return {"events": [{"when": views.fmt_when(e["ts"]), "camera": views.event_dict(e)["camera_name"],
                        "summary": e["summary"], "flags": views.flags_for(e)} for e in evs]}


def _mcp_watch(args: dict) -> dict:
    req = (args.get("request") or "").strip()
    if not req:
        raise ValueError("request required")
    return _mcp_ask({"question": req, "focus_person_id": args.get("focus_person_id")})


def _mcp_people(_: dict) -> dict:
    return {"people": [{"id": p["id"], "name": p["name"], "label": p["label"], "role": p["role"],
                        "role_conf": p["role_conf"], "sightings": p["n_events"]}
                       for p in (views.person_dict(x) for x in db.q("SELECT * FROM persons ORDER BY last_ts DESC"))]}


_RO = {"readOnlyHint": True, "openWorldHint": False}
MCP_TOOLS = {
    "ask_home": {
        "description": ("Ask the home's persistent camera memory a question in plain language: 'which guy is the "
                        "delivery guy', 'where was my father last seen', 'did anyone enter after Dad left', "
                        "'who knocked six days ago'. Returns an answer plus evidence clips."),
        "inputSchema": {"type": "object", "properties": {
            "question": {"type": "string"}, "focus_person_id": {"type": "string", "description": "person from a previous answer, so 'this person' resolves"}},
            "required": ["question"]}, "annotations": _RO, "fn": _mcp_ask},
    "last_seen": {
        "description": "When and where a named person or pet was last seen, with their path across cameras.",
        "inputSchema": {"type": "object", "properties": {"person": {"type": "string"}}, "required": ["person"]},
        "annotations": _RO, "fn": _mcp_last_seen},
    "get_timeline": {
        "description": "The most recent events the home cameras recorded.",
        "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 50}}},
        "annotations": _RO, "fn": _mcp_timeline},
    "list_people": {
        "description": "People and pets the home has learned to recognise, with inferred roles.",
        "inputSchema": {"type": "object", "properties": {}}, "annotations": _RO, "fn": _mcp_people},
    "watch_for": {
        "description": "Create a standing watch: 'tell me next time this person comes', 'tell me if Dad leaves after midnight'.",
        "inputSchema": {"type": "object", "properties": {
            "request": {"type": "string"}, "focus_person_id": {"type": "string"}}, "required": ["request"]},
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
        "fn": _mcp_watch},
}


def _origin_ok(request: Request) -> bool:
    """DNS-rebinding guard from the MCP transport spec: reject browser Origins we don't allow."""
    origin = request.headers.get("origin")
    if not origin:
        return True
    allowed = {o.strip() for o in os.getenv("MCP_ALLOWED_ORIGINS", "").split(",") if o.strip()}
    return origin in allowed or origin.startswith(("http://localhost", "http://127.0.0.1"))


def _rpc_error(mid, code: int, msg: str) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": msg}}


def _handle_rpc(msg: dict) -> Optional[dict]:
    method, mid = msg.get("method", ""), msg.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": MCP_PROTOCOL, "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": MCP_SERVER,
            "instructions": "Query a home's Ring camera memory. Answers include evidence citations; treat security flags as unverified."}}
    if method.startswith("notifications/"):
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": [
            {"name": n, "title": n.replace("_", " ").title(), "description": t["description"],
             "inputSchema": t["inputSchema"], "annotations": t["annotations"]} for n, t in MCP_TOOLS.items()]}}
    if method == "tools/call":
        params = msg.get("params") or {}
        tool = MCP_TOOLS.get(params.get("name", ""))
        if not tool:
            return _rpc_error(mid, -32602, f"unknown tool {params.get('name')}")
        try:
            out = tool["fn"](params.get("arguments") or {})
            return {"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text", "text": json.dumps(out, default=str)}], "structuredContent": out, "isError": False}}
        except Exception as e:
            return {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": f"error: {e}"}], "isError": True}}
    return _rpc_error(mid, -32601, f"method {method} not supported")


@app.post("/mcp")
async def mcp(request: Request):
    if not _origin_ok(request):
        raise HTTPException(403, "origin not allowed")
    token = os.getenv("MCP_TOKEN", "")
    if token and request.headers.get("authorization") != f"Bearer {token}":
        raise HTTPException(401, "bearer token required")
    try:
        body = await request.json()
    except ValueError:
        return JSONResponse(_rpc_error(None, -32700, "parse error"), status_code=400)
    if isinstance(body, list):
        outs = [r for r in (_handle_rpc(m) for m in body if isinstance(m, dict)) if r is not None]
        return JSONResponse(outs) if outs else Response(status_code=202)
    out = _handle_rpc(body if isinstance(body, dict) else {})
    if out is None:
        return Response(status_code=202)
    return JSONResponse(out)


@app.get("/mcp")
def mcp_get():
    # Streamable HTTP servers may decline the optional SSE stream with 405.
    return Response(status_code=405, headers={"Allow": "POST"})
