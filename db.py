"""JEV memory store: SQLite. Events, actors, persons (the identity graph), watch rules.

One structured record per Ring event; the graph is the join of persons <-> actors <-> events.
JSON-valued columns are stored as TEXT and decoded by `row()`.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from typing import Any, Iterable, Optional

import config

_lock = threading.RLock()
_conn: Optional[sqlite3.Connection] = None

_JSON_COLS = {
    "raw", "attrs", "carrying", "actions", "bbox", "embedding", "role_probs", "exemplars",
    "text_embedding", "role_evidence", "params", "data", "aliases", "flags", "summary_embedding",
    "interactions", "concern_probs", "boxes", "emb",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS cameras (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    ring_device_id TEXT,
    zone TEXT DEFAULT 'exterior'          -- entry | exterior | interior
);
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,                  -- evt_<ring event id>
    ring_event_id TEXT UNIQUE,
    camera_id TEXT NOT NULL,
    ts REAL NOT NULL,                     -- epoch seconds (event start)
    kind TEXT NOT NULL,                   -- motion | doorbell
    sub_type TEXT,                        -- human | package | ... (Ring motion sub_type)
    status TEXT DEFAULT 'queued',         -- queued | processing | processed | failed
    source TEXT DEFAULT 'ring',           -- ring | ring_sandbox
    clip_path TEXT,
    thumb_path TEXT,
    duration REAL,
    scene TEXT,
    summary TEXT,
    summary_embedding TEXT,
    flags TEXT,                           -- json list of safety flags
    interactions TEXT,
    error TEXT,
    raw TEXT
);
CREATE INDEX IF NOT EXISTS ix_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS ix_events_cam ON events(camera_id, ts);
CREATE TABLE IF NOT EXISTS persons (
    id TEXT PRIMARY KEY,                  -- person_07
    kind TEXT DEFAULT 'person',           -- person | pet
    name TEXT,
    relation TEXT,
    aliases TEXT,
    is_resident INTEGER DEFAULT 0,
    label TEXT,                           -- "man in a blue jacket"
    exemplars TEXT,                       -- json [{img:[..], txt:[..]}]
    text_embedding TEXT,
    n_obs INTEGER DEFAULT 0,
    first_ts REAL,
    last_ts REAL,
    role TEXT,
    role_conf REAL,
    role_probs TEXT,
    role_evidence TEXT,
    thumb_path TEXT,
    created REAL
);
CREATE TABLE IF NOT EXISTS actors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL,
    person_id TEXT,
    idx INTEGER,
    track TEXT,
    kind TEXT DEFAULT 'person',
    description TEXT,
    attrs TEXT,
    carrying TEXT,
    actions TEXT,
    direction TEXT,
    bbox TEXT,
    t_first REAL,
    t_last REAL,
    match_score REAL,
    role_probs TEXT,
    role TEXT,
    role_conf REAL,
    concern TEXT,
    concern_probs TEXT
);
CREATE INDEX IF NOT EXISTS ix_actors_event ON actors(event_id);
CREATE INDEX IF NOT EXISTS ix_actors_person ON actors(person_id);
CREATE TABLE IF NOT EXISTS objects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL,
    label TEXT,
    holder_track TEXT,
    note TEXT
);
CREATE INDEX IF NOT EXISTS ix_objects_event ON objects(event_id);
CREATE TABLE IF NOT EXISTS watch_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT,
    kind TEXT,                            -- person_arrives | person_departs_window | role_arrives | unknown_at_night
    person_id TEXT,
    params TEXT,
    active INTEGER DEFAULT 1,
    created REAL,
    last_fired REAL
);
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_id INTEGER,
    event_id TEXT,
    ts REAL,
    message TEXT,
    delivered INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS webhooks_seen (
    request_id TEXT PRIMARY KEY,
    ts REAL
);
CREATE TABLE IF NOT EXISTS feed (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL,
    type TEXT,
    message TEXT,
    data TEXT
);
CREATE TABLE IF NOT EXISTS kv (
    k TEXT PRIMARY KEY,
    v TEXT
);
"""


def conn() -> sqlite3.Connection:
    global _conn
    with _lock:
        if _conn is None:
            config.DATA_DIR.mkdir(parents=True, exist_ok=True)
            _conn = sqlite3.connect(str(config.DB_PATH), check_same_thread=False, timeout=30)
            _conn.row_factory = sqlite3.Row
            _conn.execute("PRAGMA journal_mode=WAL")
            _conn.executescript(SCHEMA)
            for col in ("boxes", "emb"):        # added after v1: per-frame boxes, per-sighting embeddings
                have = {r["name"] for r in _conn.execute("PRAGMA table_info(actors)")}
                if col not in have:
                    _conn.execute(f"ALTER TABLE actors ADD COLUMN {col} TEXT")
            _conn.commit()
        return _conn


def close() -> None:
    """Drop the shared connection (tests point config.DB_PATH at a temp file)."""
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None


def _decode(d: dict) -> dict:
    for k in list(d):
        if k in _JSON_COLS and isinstance(d[k], str):
            try:
                d[k] = json.loads(d[k])
            except ValueError:
                pass
    return d


def row(r: Optional[sqlite3.Row]) -> Optional[dict]:
    return _decode(dict(r)) if r is not None else None


def q(sql: str, args: Iterable[Any] = ()) -> list[dict]:
    with _lock:
        return [_decode(dict(r)) for r in conn().execute(sql, tuple(args)).fetchall()]


def one(sql: str, args: Iterable[Any] = ()) -> Optional[dict]:
    with _lock:
        return row(conn().execute(sql, tuple(args)).fetchone())


def _enc(v: Any) -> Any:
    return json.dumps(v) if isinstance(v, (dict, list)) else v


def execute(sql: str, args: Iterable[Any] = ()) -> int:
    with _lock:
        c = conn()
        cur = c.execute(sql, tuple(_enc(a) for a in args))
        c.commit()
        return cur.lastrowid or 0


def insert(table: str, **cols: Any) -> int:
    keys = list(cols)
    sql = f"INSERT INTO {table} ({','.join(keys)}) VALUES ({','.join('?' * len(keys))})"
    return execute(sql, [cols[k] for k in keys])


def update(table: str, key: str, key_val: Any, **cols: Any) -> None:
    if not cols:
        return
    sets = ",".join(f"{k}=?" for k in cols)
    execute(f"UPDATE {table} SET {sets} WHERE {key}=?", [cols[k] for k in cols] + [key_val])


# -- feed (UI activity stream) --------------------------------------------------------

def feed(type_: str, message: str, data: Optional[dict] = None) -> int:
    return insert("feed", ts=time.time(), type=type_, message=message, data=json.dumps(data or {}))


def feed_after(after: int, limit: int = 100) -> list[dict]:
    return q("SELECT * FROM feed WHERE id>? ORDER BY id LIMIT ?", (after, limit))


# -- small kv ------------------------------------------------------------------------

def kv_get(k: str, default: Optional[str] = None) -> Optional[str]:
    r = one("SELECT v FROM kv WHERE k=?", (k,))
    return r["v"] if r else default


def kv_set(k: str, v: str) -> None:
    execute("INSERT INTO kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, v))


# -- camera registry -----------------------------------------------------------------

def upsert_camera(cam_id: str, name: str, ring_device_id: str, zone: str = "exterior") -> None:
    execute(
        "INSERT INTO cameras(id,name,ring_device_id,zone) VALUES(?,?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET name=excluded.name, ring_device_id=excluded.ring_device_id, zone=excluded.zone",
        (cam_id, name, ring_device_id, zone))


def camera_by_device(device_id: str) -> Optional[dict]:
    return one("SELECT * FROM cameras WHERE ring_device_id=?", (device_id,))


def reset_all() -> None:
    """Wipe the memory (used by the demo seeder)."""
    with _lock:
        c = conn()
        for t in ("events", "actors", "objects", "persons", "watch_rules", "alerts", "webhooks_seen", "feed"):
            c.execute(f"DELETE FROM {t}")
        c.commit()
