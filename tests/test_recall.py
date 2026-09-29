"""Recall tests. Offline: Jev/Nova/network are stubbed; the memory graph is hand-built."""
from __future__ import annotations

import datetime as dt
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import aws
import config
import db
import jev
import query
import ring_api
import roles
import timeparse
import watch

NOW = dt.datetime(2026, 9, 29, 20, 0).timestamp()


def at(days_ago: int, hhmm: str) -> float:
    h, m = (int(x) for x in hhmm.split(":"))
    d = dt.datetime.fromtimestamp(NOW).date() - dt.timedelta(days=days_ago)
    return dt.datetime.combine(d, dt.time(h, m)).timestamp()


@pytest.fixture
def mem(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    db.close()
    db.conn()
    monkeypatch.setattr(aws, "available", lambda: False)

    def boom(*a, **k):
        raise RuntimeError("network stubbed")
    monkeypatch.setattr(aws, "text", boom)
    monkeypatch.setattr(aws, "text_json", boom)

    class NoJev:
        engine_name = "stub"

        def ask(self, *a, **k):
            raise jev.JevError("stubbed")
    monkeypatch.setattr(jev, "client", lambda: NoJev())
    for cid, name, zone in [("front_door", "Front Door", "entry"), ("backyard", "Backyard", "exterior"),
                            ("garage", "Garage", "entry"), ("driveway", "Driveway", "exterior")]:
        db.upsert_camera(cid, name, f"dev_{cid}", zone)
    yield
    db.close()


def add_person(pid, label, name=None, relation="", resident=0, kind="person"):
    db.insert("persons", id=pid, kind=kind, name=name, relation=relation, label=label, is_resident=resident,
              aliases=[a for a in (name and name.lower(), relation) if a], n_obs=0, created=time.time())


def add_event(eid, cam, ts, summary, actors, flags=(), kind="motion"):
    db.insert("events", id=eid, ring_event_id=eid, camera_id=cam, ts=ts, kind=kind, status="processed",
              summary=summary, summary_embedding=aws.embed_text(summary), flags=list(flags), clip_path=f"/x/{eid}.mp4")
    for i, a in enumerate(actors):
        db.insert("actors", event_id=eid, person_id=a["pid"], idx=i, kind=a.get("kind", "person"),
                  description=a.get("desc", ""), attrs={"label": a.get("label", "")}, carrying=a.get("carry", []),
                  actions=a.get("actions", []), direction=a.get("dir", "passing"), t_first=1.0, t_last=4.0,
                  match_score=a.get("score", 1.0), role_probs=a.get("roles", {}), role=a.get("role", "unknown"),
                  role_conf=0.9, concern=a.get("concern", "normal"), concern_probs={"emergency": a.get("emerg", 0.0)})
        db.execute("UPDATE persons SET n_obs=n_obs+1, first_ts=COALESCE(MIN(first_ts,?),?), last_ts=MAX(COALESCE(last_ts,0),?) WHERE id=?",
                   (ts, ts, ts, a["pid"]))


DELIVERY = {"delivery_driver": 0.9, "unknown": 0.1}


def build_home():
    add_person("person_01", "man in a blue jacket")
    add_person("person_02", "woman in a red coat")
    add_person("person_03", "man in a grey hoodie")
    add_person("person_04", "man in a checked shirt", name="Dad", relation="father", resident=1)
    for eid, d, t, obj in [("e1", 12, "18:42", "pizza_box"), ("e2", 8, "12:15", "food_bag"), ("e3", 3, "19:05", "package")]:
        add_event(eid, "front_door", at(d, t), f"A man in a blue jacket delivers a {obj.replace('_', ' ')} and leaves.",
                  [{"pid": "person_01", "label": "man in a blue jacket", "carry": [obj], "roles": DELIVERY,
                    "actions": ["approaches_door", "hands_object_to", "leaves_immediately"], "role": "delivery_driver"}],
                  flags=["rings_doorbell"], kind="doorbell")
    add_event("e4", "front_door", at(1, "18:55"), "A man in a blue jacket delivers a pizza box.",
              [{"pid": "person_01", "carry": ["pizza_box"], "roles": DELIVERY, "actions": ["hands_object_to", "leaves"], "role": "delivery_driver"}],
              flags=["rings_doorbell"], kind="doorbell")
    add_event("e5", "front_door", at(6, "17:30"), "A woman in a red coat knocks on the door.",
              [{"pid": "person_02", "roles": {"guest_visitor": 0.8, "unknown": 0.2}, "actions": ["knocks", "waits_at_door"], "role": "guest_visitor"}],
              flags=["knocks"])
    add_event("e6", "backyard", at(0, "18:37"), "A man walks toward the garage.",
              [{"pid": "person_04", "actions": ["walks_by"]}])
    add_event("e7", "garage", at(0, "18:42"), "A man enters the garage and gets into a car.",
              [{"pid": "person_04", "actions": ["enters_building", "enters_vehicle"]}])
    add_event("e8", "driveway", at(0, "18:45"), "A car leaves the driveway.",
              [{"pid": "person_04", "actions": ["vehicle_departs"], "dir": "leaving"}])
    for pid in ("person_01", "person_02", "person_03", "person_04"):
        roles.aggregate(pid)


# -- time -----------------------------------------------------------------------------

def test_timeparse_days_ago():
    s, e = timeparse.resolve("who knocked six days ago", NOW)
    assert dt.datetime.fromtimestamp(s).date() == dt.date(2026, 9, 23) and e - s == 86400


def test_timeparse_last_night_and_dates():
    s, e = timeparse.resolve("last night", NOW)
    assert dt.datetime.fromtimestamp(s).hour == 18 and dt.datetime.fromtimestamp(e).hour == 6
    s, _ = timeparse.resolve("on Sep 21", NOW)
    assert dt.datetime.fromtimestamp(s).date() == dt.date(2026, 9, 21)
    assert timeparse.resolve("show me the pizza delivery", NOW) is None


# -- Ring plumbing --------------------------------------------------------------------

def test_signature_roundtrip_and_tamper():
    raw = b'{"meta":{"request_id":"r1"}}'
    sig = ring_api.sign(raw, "k")
    assert sig.startswith("sha256=") and ring_api.verify_signature(raw, sig, "k")
    assert not ring_api.verify_signature(raw + b" ", sig, "k")
    assert not ring_api.verify_signature(raw, None, "k")
    assert not ring_api.verify_signature(raw, sig, "other")


def test_parse_webhook_motion_and_button():
    payload = {"meta": {"request_id": "r9"}, "data": {
        "type": "button_press", "id": "evt_1", "attributes": {"occurred_at": "2026-09-28T19:42:13Z"},
        "relationships": {"device": {"data": {"type": "device", "id": "dev_front_door"}}}}}
    (ev,) = ring_api.parse_webhook(payload)
    assert ev.kind == "doorbell" and ev.device_id == "dev_front_door" and ev.request_id == "r9"
    assert ring_api.parse_webhook({"data": {"type": "device_online", "id": "x"}}) == []


def test_webhook_endpoint_signature_and_idempotency(mem, monkeypatch):
    from fastapi.testclient import TestClient
    import pipeline
    import server
    seen = []
    monkeypatch.setattr(pipeline, "accept", lambda ev, source=None: seen.append(ev.ring_event_id) or "evt_x")
    c = TestClient(server.app)
    body = json.dumps({"meta": {"request_id": "rq1"}, "data": {
        "type": "motion_detected", "id": "evt_a", "attributes": {"sub_type": "human", "occurred_at": "2026-09-28T19:42:13Z"},
        "relationships": {"device": {"data": {"id": "dev_front_door"}}}}}).encode()
    assert c.post("/ring/webhook", content=body).status_code == 401
    assert c.post("/ring/webhook", content=body, headers={"X-Signature": "sha256=bad"}).status_code == 401
    ok = {"X-Signature": ring_api.sign(body)}
    assert c.post("/ring/webhook", content=body, headers=ok).json()["status"] == "accepted"
    assert c.post("/ring/webhook", content=body, headers=ok).json()["status"] == "duplicate"
    assert seen == ["evt_a"]


# -- roles ----------------------------------------------------------------------------

def test_role_aggregation_is_evidence_weighted(mem):
    build_home()
    p1 = db.one("SELECT * FROM persons WHERE id='person_01'")
    assert p1["role"] == "delivery_driver" and 0.7 < p1["role_conf"] < 1.0
    # one sighting must never reach the confidence of four
    add_person("person_09", "x")
    add_event("e9", "front_door", at(2, "10:00"), "x", [{"pid": "person_09", "roles": DELIVERY}])
    one = roles.aggregate("person_09")
    assert one["role_conf"] < p1["role_conf"]
    # residents are certain by definition
    assert db.one("SELECT role, role_conf FROM persons WHERE id='person_04'")["role"] == "resident_family"


def test_watch_window_wraps_midnight():
    assert watch.in_window(0, 0, 6) and watch.in_window(23, 22, 5) and watch.in_window(3, 22, 5)
    assert not watch.in_window(12, 22, 5)


# -- query operators ------------------------------------------------------------------

def test_identify_delivery_guy(mem):
    build_home()
    r = query.ask("Which guy is the delivery guy?", now=NOW)
    assert r["operator"] == "identify_person" and r["focus"]["person_id"] == "person_01"
    assert len(r["citations"]) >= 3 and r["confidence"] > 0.7
    assert any(s["title"] == "Cross-event consistency" for s in r["steps"])


def test_last_pizza_delivery_is_one_exact_event(mem):
    build_home()
    r = query.ask("Show me the last pizza delivery", now=NOW)
    assert [c["event_id"] for c in r["citations"]] == ["e4"]


def test_who_knocked_six_days_ago_resolves_the_date(mem):
    build_home()
    r = query.ask("Who knocked six days ago?", now=NOW)
    assert [c["event_id"] for c in r["citations"]] == ["e5"] and r["focus"]["person_id"] == "person_02"


def test_last_seen_builds_cross_camera_path(mem):
    build_home()
    r = query.ask("Where was my father last seen?", now=NOW)
    assert r["operator"] == "last_seen" and r["focus"]["person_id"] == "person_04"
    assert [t["camera_id"] for t in r["timeline"]] == ["backyard", "garage", "driveway"]
    assert r["no_subsequent_detections"] is True


def test_after_departure_says_no_when_nobody_entered(mem):
    build_home()
    r = query.ask("Did anyone enter after Dad left?", now=NOW)
    assert r["operator"] == "after_departure" and r["answer"].startswith("No")


def test_after_departure_says_yes_with_evidence(mem):
    build_home()
    add_event("e10", "front_door", at(0, "19:10"), "A man walks into the house.",
              [{"pid": "person_03", "actions": ["approaches_door", "enters_building"]}])
    r = query.ask("Did anyone enter after Dad left?", now=NOW)
    assert r["answer"].startswith("Yes") and r["citations"][0]["event_id"] == "e10"


def test_after_departure_without_recorded_departure(mem):
    add_person("person_04", "man", name="Dad", relation="father", resident=1)
    add_event("e1", "driveway", at(0, "18:00"), "A man arrives.", [{"pid": "person_04", "actions": ["approaches_door"], "dir": "arriving"}])
    r = query.ask("What happened after Dad left?", now=NOW)
    assert "No departure" in r["answer"]


def test_security_incident_is_flagged_and_hedged(mem):
    build_home()
    add_event("e11", "front_door", at(4, "21:10"), "A man raises an object at the door.",
              [{"pid": "person_03", "actions": ["raises_object"], "emerg": 0.8}], flags=["possible_weapon"])
    db.update("events", "id", "e11", raw={"perception": {"safety": {"note": "object consistent with a handgun"}}})
    r = query.ask("Who pulled a gun at my door?", now=NOW)
    assert r["operator"] == "security_incident" and r["citations"][0]["event_id"] == "e11"
    assert r["citations"][0]["label"].startswith("⚠") and "unverified" in r["answer"].lower()
    r2 = query.ask("Who pulled a gun at my door?", now=NOW + 1)
    assert r2["focus"]["person_id"] == "person_03"


def test_watch_rule_created_from_conversation_and_fires(mem, monkeypatch):
    build_home()
    monkeypatch.setattr(watch, "notify", lambda m: True)
    r = query.ask("Tell me next time this person comes", {"focus_person_id": "person_01"}, now=NOW)
    assert r["watch_rule"] and r["watch_rule"]["kind"] == "person_arrives"
    ts = time.time() - 30
    add_event("live1", "front_door", ts, "The man in the blue jacket is back.",
              [{"pid": "person_01", "actions": ["approaches_door"], "roles": DELIVERY}])
    fired = watch.evaluate("live1")
    assert len(fired) == 1 and "Front Door" in fired[0]["message"]
    assert watch.evaluate("live1") == []   # cooldown


def test_watch_departure_window_rule(mem, monkeypatch):
    build_home()
    monkeypatch.setattr(watch, "notify", lambda m: True)
    r = query.ask("Tell me if Dad leaves after midnight", now=NOW)
    assert r["watch_rule"]["kind"] == "person_departs_window"
    rule = db.one("SELECT * FROM watch_rules WHERE id=?", (r["watch_rule"]["id"],))
    assert rule["params"] == {"start": 0, "end": 6}


def test_unknown_person_asks_for_enrollment(mem):
    r = query.ask("Where was my father last seen?", now=NOW)
    assert r["confidence"] == 0.0 and "Name" in r["answer"]


# -- MCP (Alexa+) ---------------------------------------------------------------------

def test_mcp_protocol(mem):
    from fastapi.testclient import TestClient
    import server
    c = TestClient(server.app)
    init = c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}).json()
    assert init["result"]["protocolVersion"] == "2025-11-25"
    tools = c.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}).json()["result"]["tools"]
    assert {"ask_home", "last_seen", "get_timeline", "list_people", "watch_for"} <= {t["name"] for t in tools}
    assert c.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}).status_code == 202
    bad = c.post("/mcp", json={"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "nope"}}).json()
    assert bad["error"]["code"] == -32602
    assert c.post("/mcp", json={"jsonrpc": "2.0", "id": 4, "method": "ping"}, headers={"Origin": "https://evil.example"}).status_code == 403
    assert c.get("/mcp").status_code == 405


def test_mcp_ask_home_returns_structured_answer(mem):
    from fastapi.testclient import TestClient
    import server
    build_home()
    c = TestClient(server.app)
    r = c.post("/mcp", json={"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {
        "name": "ask_home", "arguments": {"question": "Which guy is the delivery guy?"}}}).json()["result"]
    assert r["isError"] is False and r["structuredContent"]["operator"] == "identify_person"
    assert r["structuredContent"]["citations"]


# -- digest ---------------------------------------------------------------------------

def test_digest_surfaces_flags_night_and_unnamed_regulars(mem):
    import digest
    build_home()
    add_event("e12", "front_door", at(4, "21:10"), "A man raises an object at the door.",
              [{"pid": "person_03", "actions": ["raises_object"]}], flags=["possible_weapon"])
    add_event("e13", "front_door", at(1, "23:30"), "A man in a grey hoodie stands at the door.",
              [{"pid": "person_03", "actions": ["waits_at_door"]}])
    d = digest.build(NOW)
    kinds = [i["kind"] for i in d["attention"]]
    assert kinds[0] == "flag" and "unverified" in d["attention"][0]["text"]
    assert "night_unknown" in kinds and "unnamed_regular" in kinds     # person_01 has 4 events, unnamed
    assert d["headline"].endswith("to look at")
    assert set(d["stats"]) == {"events_today", "people_today"}


# -- rehearsal / routine / corrections / boxes ----------------------------------------

def test_rehearse_expectations():
    import rehearse
    rec = {"actors": [{"actions": ["knocks"], "carrying": ["pizza_box"]}], "objects": [{"label": "pizza_box"}],
           "safety": {"possible_weapon": False}, "knocks": True, "rings_doorbell": False}
    dec = [{"role_probs": {"delivery_driver": 0.9}, "concern": "normal"}]
    res = {n: ok for n, ok, _ in rehearse.check_expect(
        {"actions": ["knocks", "enters_vehicle"], "carrying": ["pizza"], "role": "delivery_driver", "flag": "possible_weapon", "min_actors": 1}, rec, dec)}
    assert res["action knocks"] and not res["action enters_vehicle"] and res["carrying pizza"]
    assert res["role delivery_driver"] and not res["flag possible_weapon"] and res["actors"]


def _routine_home(days=(1, 2, 3, 4, 5), hhmm="07:30"):
    add_person("person_20", "woman in a white top", name="Mom", relation="mother", resident=1)
    for i, d in enumerate(days):
        add_event(f"m{i}", "front_door", at(d, hhmm), "A woman leaves the house.", [{"pid": "person_20", "actions": ["leaves"]}])


def test_routine_flags_missing_person(mem):
    import routine
    _routine_home()
    prof = routine.profile("person_20", NOW)
    assert prof and prof["usual"] == "7:30 AM" and prof["days_seen"] == 5
    c = routine.check("person_20", NOW)               # NOW is 8 PM, nothing today
    assert c["status"] == "missing" and "usually appears around 7:30 AM" in c["text"]
    r = query.ask("Is Mom's day normal today?", now=NOW)
    assert r["operator"] == "routine_check" and "Nothing yet today" in r["answer"]


def test_routine_on_track_unusual_and_insufficient(mem):
    import routine
    _routine_home()
    add_event("today1", "front_door", at(0, "07:40"), "A woman leaves.", [{"pid": "person_20", "actions": ["leaves"]}])
    assert routine.check("person_20", NOW)["status"] == "on_track"
    db.execute("DELETE FROM actors WHERE event_id='today1'"); db.execute("DELETE FROM events WHERE id='today1'")
    add_event("today2", "front_door", at(0, "03:10"), "A woman leaves.", [{"pid": "person_20", "actions": ["leaves"]}])
    assert routine.check("person_20", NOW)["status"] == "unusual_time"
    add_person("person_21", "man", name="Sam")
    add_event("s1", "front_door", at(1, "09:00"), "x", [{"pid": "person_21"}])
    assert routine.check("person_21", NOW)["status"] == "no_routine"


def test_digest_reports_routine_deviation(mem):
    import digest
    _routine_home()
    kinds = [i["kind"] for i in digest.build(NOW)["attention"]]
    assert "routine" in kinds


def test_merge_persons_transfers_sightings_name_and_rules(mem):
    import identity
    build_home()
    add_person("person_30", "man in a blue jacket (again)")
    add_event("dup1", "front_door", at(2, "10:00"), "x", [{"pid": "person_30"}])
    identity.name_person("person_30", "Sam", "friend")
    r = identity.merge_persons("person_30", "person_01")
    assert r["id"] == "person_01" and r["name"] == "Sam" and r["n_obs"] == 5
    assert db.one("SELECT 1 FROM persons WHERE id='person_30'") is None
    assert db.one("SELECT person_id FROM actors WHERE event_id='dup1'")["person_id"] == "person_01"
    with pytest.raises(ValueError):
        identity.merge_persons("person_01", "person_01")


def test_reassign_actor_splits_into_new_person(mem):
    import identity
    build_home()
    aid = db.one("SELECT id FROM actors WHERE event_id='e4'")["id"]
    out = identity.reassign_actor(aid, None)
    assert out["to"]["id"] != "person_01" and out["to"]["n_obs"] == 1 and out["from"]["n_obs"] == 3
    out2 = identity.reassign_actor(aid, "person_01")
    assert out2["to"]["n_obs"] == 4 and db.one("SELECT 1 FROM persons WHERE id=?", (out["to"]["id"],)) is None


def test_perception_boxes_normalised_and_largest_used_for_crop():
    import perceive
    a = perceive._norm({"actors": [{"track": "A", "boxes": [
        {"frame": 1, "bbox": [100, 100, 200, 300]}, {"frame": 2, "bbox": [100, 100, 500, 900]},
        {"frame": 3, "bbox": [5, 5, 1, 1]}, {"frame": "x"}]}]})["actors"][0]
    assert len(a["boxes"]) == 2 and a["bbox_frame"] == 2 and a["bbox"] == [100, 100, 500, 900]


def test_citation_carries_boxes(mem):
    build_home()
    aid = db.one("SELECT id FROM actors WHERE event_id='e4'")["id"]
    db.update("actors", "id", aid, boxes=[{"t": 1.0, "bbox": [10, 10, 500, 900]}])
    r = query.ask("Show me the last pizza delivery", now=NOW)
    assert r["citations"][0]["boxes"] == [{"t": 1.0, "bbox": [10, 10, 500, 900]}]
