"""QUERY: natural-language question -> reasoning operator over the memory graph -> answer + evidence.

  1. Jev (System One) makes the typed decisions: which operator, which subject, which occurrence.
  2. Nova Lite extracts free-text slots (time phrase, keywords, camera) — dates are resolved by timeparse.py.
  3. A deterministic operator runs over persons/events/actors and returns facts, citations, a timeline
     and human-readable reasoning steps. Numbers (confidence) come from stored posteriors, never an LLM.
  4. Nova narrates the facts. If it fails, a template hint built from the same facts is returned.
"""
from __future__ import annotations

import re
import time
from collections import Counter
from typing import Optional

import aws
import config
import db
import identity
import jev
import roles
import routine
import timeparse
import views
import watch

STOP = set("""a an the and or of to in on at for with by from is are was were be been am do does did done show me my
your our their his her its this that these those who whom whose which what when where why how last first latest recent
ever any anyone someone guy man woman person people please tell find get give see saw seen come came comes coming
day days ago week weeks hour hours night morning evening today yesterday tonight next time i you he she they them him
there here about after before then than into out up down over under again still just not no yes if it""".split())
STOP |= set("""one two three four five six seven eight nine ten eleven twelve fourteen jan feb mar apr may jun jul aug
sep oct nov dec january february march april june july august september october november december monday tuesday
wednesday thursday friday saturday sunday""".split())
ROLE_WORDS = {"delivery", "courier", "driver", "deliveries"}


# -- data access ----------------------------------------------------------------------

def _events(where: str = "", args: tuple = ()) -> list[dict]:
    """Processed events (ascending) with their actors attached."""
    sql = "SELECT * FROM events WHERE status='processed'" + (f" AND {where}" if where else "") + " ORDER BY ts"
    evs = db.q(sql, args)
    if not evs:
        return []
    ids = [e["id"] for e in evs]
    by: dict[str, list[dict]] = {}
    for a in db.q(f"SELECT * FROM actors WHERE event_id IN ({','.join('?' * len(ids))}) ORDER BY idx", ids):
        by.setdefault(a["event_id"], []).append(a)
    cams = {c["id"]: c for c in db.q("SELECT * FROM cameras")}
    for e in evs:
        e["actors"] = by.get(e["id"], [])
        e["camera"] = cams.get(e["camera_id"], {"id": e["camera_id"], "name": e["camera_id"], "zone": "exterior"})
    return evs


def _person(pid: Optional[str]) -> Optional[dict]:
    return db.one("SELECT * FROM persons WHERE id=?", (pid,)) if pid else None


def _pname(p: dict) -> str:
    return p.get("name") or f"the {p.get('label') or 'visitor'}"


def _actor_of(e: dict, pid: Optional[str]) -> Optional[dict]:
    for a in e["actors"]:
        if pid and a.get("person_id") == pid:
            return a
    return e["actors"][0] if e["actors"] else None


def _person_events(pid: str) -> list[dict]:
    return [e for e in _events() if any(a.get("person_id") == pid for a in e["actors"])]


def _tl(e: dict, text: str) -> dict:
    return {"ts": e["ts"], "camera_id": e["camera_id"], "camera_name": e["camera"]["name"], "text": text,
            "event_id": e["id"], "thumb_url": f"/media/thumb/{e['id']}.jpg" if e.get("thumb_path") else None}


def _cite(e: dict, label: str, pid: Optional[str] = None) -> dict:
    return views.citation(e, label, _actor_of(e, pid))


def _brief(e: dict, now: float) -> str:
    return f"{views.fmt_when(e['ts'], now)} — {e['camera']['name']}: {e.get('summary') or 'activity'}"


# -- slot extraction ------------------------------------------------------------------

_SLOT_SYS = ("Extract search slots from a home-camera question. Reply with ONE JSON object only: "
             '{"time_expr": "<verbatim time phrase like \'six days ago\' or null>", '
             '"keywords": ["<concrete objects/events that must appear, e.g. pizza, package, knock>"], '
             '"camera": "<one of the camera names or null>", '
             '"window_start_hour": <0-23 or null>, "window_end_hour": <0-23 or null>}. '
             "window_* only for rules like 'after midnight' (0,6) or 'after 10pm' (22,6).")


def heuristic_slots(q: str) -> dict:
    toks = [t for t in re.findall(r"[a-z]+", q.lower()) if t not in STOP and len(t) > 2]
    sh, eh = None, None
    if re.search(r"after midnight|past midnight|overnight", q.lower()):
        sh, eh = 0, 6
    else:
        m = re.search(r"after\s+(\d{1,2})\s*(am|pm)?", q.lower())
        if m:
            h = int(m.group(1)) % 12 + (12 if (m.group(2) or "pm") == "pm" else 0)
            sh, eh = h, 6
    return {"time_expr": q, "keywords": toks, "camera": None, "window_start_hour": sh, "window_end_hour": eh}


def extract_slots(q: str, cameras: list[str]) -> dict:
    base = heuristic_slots(q)
    try:
        out = aws.text_json(_SLOT_SYS, f"Cameras: {cameras}\nQuestion: {q}", 250)
        return {
            "time_expr": out.get("time_expr") or base["time_expr"],
            "keywords": [k.lower() for k in (out.get("keywords") or []) if isinstance(k, str)] or base["keywords"],
            "camera": out.get("camera") if out.get("camera") in cameras else None,
            "window_start_hour": out.get("window_start_hour") if isinstance(out.get("window_start_hour"), int) else base["window_start_hour"],
            "window_end_hour": out.get("window_end_hour") if isinstance(out.get("window_end_hour"), int) else base["window_end_hour"],
        }
    except Exception:
        return base


def heuristic_operator(q: str) -> tuple[str, str]:
    t = q.lower()
    ordinal = "first" if re.search(r"\bfirst\b", t) else "all" if re.search(r"\b(all|every|list)\b", t) else "last"
    if re.search(r"\b(gun|weapon|knife|armed|pistol|handgun|break.?in|forced entry)\b", t):
        return "security_incident", ordinal
    if re.search(r"\b(tell me|notify|alert me|let me know|warn me|watch for)\b", t):
        return "watch_request", ordinal
    if re.search(r"\bafter\b.*\b(left|leave|leaves|gone|departed)\b|\bwhat happened after\b", t):
        return "after_departure", ordinal
    if re.search(r"\bwhich\b.*\b(guy|man|woman|person|one)\b|\bwho is the\b|\bwho'?s the\b", t):
        return "identify_person", ordinal
    if re.search(r"\b(path|route|trajectory|where did .* go|movements)\b", t):
        return "trajectory", ordinal
    if re.search(r"\b(where|when)\b.*\b(last seen|was .* seen)\b|\blast seen\b|\bwhere was\b", t):
        return "last_seen", "last"
    if re.search(r"\b(routine|usual|usually|unusual|typical|as always)\b|\bnormal (for|today)\b|\b(day|today)\b.*\bnormal\b|\bnormal\b.*\b(day|today)\b", t):
        return "routine_check", ordinal
    if re.search(r"\bhow many\b|\bhow often\b", t):
        return "count", "all"
    if re.search(r"\bwhat does .* look like\b|\bdescribe\b", t):
        return "describe_person", ordinal
    return "find_events", ordinal


# -- operators ------------------------------------------------------------------------

def op_identify_person(role: str, now: float, **_) -> dict:
    people = [p for p in db.q("SELECT * FROM persons WHERE kind='person'") if not p.get("is_resident")]
    n_events = len(_events())
    steps = [{"title": "Candidate people",
              "detail": f"{len(people)} distinct non-resident people appear across {n_events} recorded events."}]
    scored = sorted(((roles.role_posterior_for(p, role), p) for p in people), key=lambda x: -x[0])
    scored = [(s, p) for s, p in scored if s >= 0.15]
    if not scored:
        return {"facts": {"found": False, "role": role}, "hint": f"No one in the recorded events looks like a {role.replace('_', ' ')}.",
                "steps": steps, "confidence": 0.0}
    top_s, top = scored[0]
    evs = _person_events(top["id"])
    agree = [e for e in evs if (_actor_of(e, top["id"]) or {}).get("role") == role]
    carried = Counter(c for e in evs for a in e["actors"] if a.get("person_id") == top["id"] for c in (a.get("carrying") or []))
    acts = Counter(x for e in evs for a in e["actors"] if a.get("person_id") == top["id"] for x in (a.get("actions") or []))
    steps.append({"title": "Events per candidate",
                  "detail": "; ".join(f"{_pname(p)}: {p.get('n_obs') or 0} events" for _, p in scored[:4])})
    steps.append({"title": "Cross-event consistency",
                  "detail": f"{_pname(top)} looks like a {role.replace('_', ' ')} in {len(agree)} of {len(evs)} events"
                            + (f"; usually carrying {', '.join(c.replace('_', ' ') for c, _ in carried.most_common(2))}" if carried else "")
                            + (f"; typical actions: {', '.join(a.replace('_', ' ') for a, _ in acts.most_common(3))}" if acts else "")})
    if len(scored) > 1:
        margin = f"{top_s:.0%} vs {scored[1][0]:.0%} for {_pname(scored[1][1])}"
    else:
        margin = f"{top_s:.0%}, no competing candidate"
    steps.append({"title": "Ranking", "detail": f"{_pname(top)} ranks first ({margin})."})
    ev_ids = {x["event_id"] for x in (top.get("role_evidence") or [])}
    proof = [e for e in reversed(evs) if e["id"] in ev_ids][:4] or list(reversed(evs))[:4]
    return {
        "facts": {"found": True, "role": role, "person": views.person_dict(top), "events_seen": len(evs),
                  "events_matching_role": len(agree), "posterior": round(top_s, 3),
                  "carried": [c for c, _ in carried.most_common(3)],
                  "actions": [a for a, _ in acts.most_common(4)],
                  "dates": [views.fmt_when(e["ts"], now) for e in proof],
                  "alternatives": [{"who": _pname(p), "score": round(s, 3)} for s, p in scored[1:3]]},
        "hint": f"{_pname(top).capitalize()} ({top.get('label')}) — appears in {len(evs)} events, {len(agree)} consistent with a {role.replace('_', ' ')}.",
        "citations": [_cite(e, f"{views.fmt_when(e['ts'], now)} · {e['camera']['name']}", top["id"]) for e in proof],
        "people": [top["id"]], "focus": top["id"], "steps": steps, "confidence": top_s,
    }


def op_find_events(q: str, subject: dict, ordinal: str, slots: dict, now: float, **_) -> dict:
    steps = []
    window = timeparse.resolve(slots.get("time_expr"), now) or timeparse.resolve(q, now)
    evs = _events()
    if window:
        evs = [e for e in evs if window[0] <= e["ts"] < window[1]]
        steps.append({"title": "Resolve the time",
                      "detail": f"'{slots.get('time_expr') or q}' → {views.fmt_when(window[0], now)} to {views.fmt_when(window[1] - 1, now)}"})
    if slots.get("camera"):
        evs = [e for e in evs if e["camera"]["name"] == slots["camera"]]
    person, role = subject.get("person"), subject.get("role")
    if person:
        evs = [e for e in evs if any(a.get("person_id") == person["id"] for a in e["actors"])]
        steps.append({"title": "Filter by person", "detail": f"Events involving {_pname(person)}."})
    if role:
        evs = [e for e in evs if any((a.get("role_probs") or {}).get(role, 0) >= 0.4 for a in e["actors"])]
        steps.append({"title": "Filter by role", "detail": f"Events where someone looks like a {role.replace('_', ' ')}."})

    soft = False
    kws = [k for k in slots.get("keywords", []) if k not in STOP and not (role and k in ROLE_WORDS)]
    t = q.lower()
    want_knock = bool(re.search(r"\b(knock|knocked|knocking|rang|ring|rings|doorbell)\b", t))
    if want_knock:
        explicit = [e for e in evs if {"knocks", "rings_doorbell"} & set(e.get("flags") or [])
                    or {"knocks", "rings_doorbell"} & {x for a in e["actors"] for x in (a.get("actions") or [])}]
        kws = [k for k in kws if not re.match(r"(knock|ring|rang|doorbell)", k)]
        if explicit:
            evs = explicit
            steps.append({"title": "Match the action", "detail": "Events with a knock or doorbell press."})
        else:
            door = [e for e in evs if e["camera"].get("zone") == "entry"
                    and {"approaches_door", "waits_at_door"} & {x for a in e["actors"] for x in (a.get("actions") or [])}]
            steps.append({"title": "Match the action", "detail": "No explicit knock or doorbell press was detected"
                          + (f"; showing {len(door)} visitor(s) who came to the door instead." if door else ".")})
            evs, soft = door, True

    scored: list[tuple[float, dict]] = []
    if kws:
        for e in evs:
            blob = " ".join([e.get("summary") or ""] + [o["label"] for o in db.q("SELECT label FROM objects WHERE event_id=?", (e["id"],))]
                            + [x for a in e["actors"] for x in (a.get("actions") or []) + (a.get("carrying") or [])]).lower().replace("_", " ")
            hit = sum(1 for k in kws if (k[:5] if len(k) > 5 else k) in blob)
            if hit:
                scored.append((hit / len(kws), e))
        if scored:
            best = max(s for s, _ in scored)
            scored = [(s, e) for s, e in scored if s >= best - 1e-9]
            steps.append({"title": "Match the content", "detail": f"Keywords {kws}: {len(scored)} matching event(s)."})
        else:
            qv = aws.embed_text(" ".join(kws))
            sem = [(aws.cosine(qv, e.get("summary_embedding")), e) for e in evs]
            scored = [(s, e) for s, e in sem if s >= 0.30]
            steps.append({"title": "Semantic match", "detail": f"No exact keyword hits; nearest by meaning: {len(scored)} event(s)."})
    else:
        scored = [(0.8, e) for e in evs]

    scored.sort(key=lambda x: x[1]["ts"])
    if ordinal == "first":
        picked = scored[:1]
    elif ordinal == "last":
        picked = scored[-1:]
    else:
        picked = scored[-8:]
    if not picked:
        return {"facts": {"found": False, "window": bool(window)}, "hint": "I found no matching event in the recorded history.",
                "steps": steps, "confidence": 0.0}
    picked = list(reversed(picked))
    conf = max(0.5, min(0.95, 0.6 + 0.4 * max(s for s, _ in picked)))
    if soft:
        conf = min(conf, 0.6)
    pids = [a["person_id"] for _, e in picked for a in e["actors"] if a.get("person_id")]
    focus = pids[0] if pids else None
    visitors = []
    for pid in dict.fromkeys(pids):
        p = _person(pid)
        hist = _person_events(pid)
        visitors.append({"who": _pname(p), "label": p.get("label"), "role": p.get("role"),
                         "role_conf": p.get("role_conf"), "total_events": len(hist)})
    if want_knock and visitors:
        steps.append({"title": "Identify the visitor", "detail": "Linked to the identity graph: " +
                      "; ".join(f"{v['who']} ({v['total_events']} events on record)" for v in visitors)})
    return {
        "facts": {"found": True, "count": len(scored), "no_explicit_knock_detected": soft, "events": [
            {"when": views.fmt_when(e["ts"], now), "camera": e["camera"]["name"], "summary": e.get("summary")} for _, e in picked],
            "visitors": visitors},
        "hint": "; ".join(_brief(e, now) for _, e in picked[:2]),
        "citations": [_cite(e, f"{views.fmt_when(e['ts'], now)} · {e['camera']['name']}", focus) for _, e in picked],
        "people": list(dict.fromkeys(pids))[:3], "focus": focus, "steps": steps, "confidence": conf,
        "count_total": len(scored),
    }


def _session(evs: list[dict]) -> list[dict]:
    """Trailing run of events with gaps <= SESSION_GAP_SEC (one 'outing')."""
    if not evs:
        return []
    out = [evs[-1]]
    for e in reversed(evs[:-1]):
        if out[0]["ts"] - e["ts"] <= config.SESSION_GAP_SEC:
            out.insert(0, e)
        else:
            break
    return out


def _path_items(evs: list[dict], pid: str, person: dict) -> list[dict]:
    items = []
    for e in evs:
        a = _actor_of(e, pid)
        items.append(_tl(e, f"{_pname(person).capitalize()} {views.humanize_actions((a or {}).get('actions') or [], (a or {}).get('carrying'))}"))
    return items


def op_last_seen(person: Optional[dict], now: float, **_) -> dict:
    if not person:
        return _need_person()
    evs = _person_events(person["id"])
    if not evs:
        return {"facts": {"found": False, "person": _pname(person)}, "hint": f"{_pname(person).capitalize()} has not been seen on any camera.",
                "steps": [], "confidence": 0.0, "focus": person["id"], "people": [person["id"]]}
    sess = _session(evs)
    last = evs[-1]
    a = _actor_of(last, person["id"])
    ms = min((x.get("match_score") or 1.0) for e in sess for x in e["actors"] if x.get("person_id") == person["id"])
    steps = [
        {"title": "Resolve the person", "detail": f"'{_pname(person)}' → {person['id']} ({person.get('label')}), {len(evs)} sightings."},
        {"title": "Sort sightings by time", "detail": f"Most recent: {views.fmt_when(last['ts'], now)} on {last['camera']['name']}."},
        {"title": "Cross-camera trajectory", "detail": f"{len(sess)} linked sighting(s) across {len({e['camera_id'] for e in sess})} camera(s) in the latest outing."},
        {"title": "Last reliable observation", "detail": f"Weakest re-identification in this outing: {ms:.0%} similarity. No later detections."},
    ]
    return {
        "facts": {"found": True, "person": views.person_dict(person), "last_seen": views.fmt_when(last["ts"], now),
                  "camera": last["camera"]["name"], "doing": views.humanize_actions((a or {}).get("actions") or [], (a or {}).get("carrying")),
                  "path": [f"{views.clock(e['ts'])} {e['camera']['name']}: " + views.humanize_actions((_actor_of(e, person['id']) or {}).get('actions') or []) for e in sess],
                  "no_subsequent_detections": True},
        "hint": f"{_pname(person).capitalize()} was last seen {views.fmt_when(last['ts'], now)} on the {last['camera']['name']} camera.",
        "citations": [_cite(e, f"{views.clock(e['ts'])} · {e['camera']['name']}", person["id"]) for e in reversed(sess)],
        "timeline": _path_items(sess, person["id"], person), "people": [person["id"]], "focus": person["id"],
        "steps": steps, "confidence": min(0.97, 0.55 + 0.45 * float(ms)), "no_subsequent": True,
    }


def op_trajectory(person: Optional[dict], slots: dict, q: str, now: float, **_) -> dict:
    if not person:
        return _need_person()
    evs = _person_events(person["id"])
    window = timeparse.resolve(slots.get("time_expr"), now) or timeparse.resolve(q, now)
    sess = [e for e in evs if window[0] <= e["ts"] < window[1]] if window else _session(evs)
    if not sess:
        return {"facts": {"found": False}, "hint": f"No sightings of {_pname(person)} in that period.", "steps": [], "confidence": 0.0,
                "focus": person["id"], "people": [person["id"]]}
    return {
        "facts": {"found": True, "person": views.person_dict(person),
                  "path": [f"{views.fmt_when(e['ts'], now)} {e['camera']['name']}: " + views.humanize_actions((_actor_of(e, person['id']) or {}).get('actions') or []) for e in sess]},
        "hint": f"{len(sess)} sighting(s) of {_pname(person)}, from {views.fmt_when(sess[0]['ts'], now)} to {views.fmt_when(sess[-1]['ts'], now)}.",
        "citations": [_cite(e, f"{views.clock(e['ts'])} · {e['camera']['name']}", person["id"]) for e in reversed(sess)][:8],
        "timeline": _path_items(sess, person["id"], person), "people": [person["id"]], "focus": person["id"],
        "steps": [{"title": "Collect sightings", "detail": f"{len(sess)} events linked to {person['id']}."},
                  {"title": "Order across cameras", "detail": " → ".join(e["camera"]["name"] for e in sess)}],
        "confidence": 0.85, "no_subsequent": sess[-1] is evs[-1],
    }


def op_after_departure(person: Optional[dict], now: float, **_) -> dict:
    if not person:
        return _need_person()
    evs = _person_events(person["id"])
    if not evs:
        return {"facts": {"found": False}, "hint": f"{_pname(person).capitalize()} has not been seen.", "steps": [], "confidence": 0.0}
    dep = next((e for e in reversed(evs) if (set(x for a in e["actors"] if a.get("person_id") == person["id"] for x in (a.get("actions") or [])) & views.DEPARTURE_ACTIONS)
                or any(a.get("person_id") == person["id"] and a.get("direction") == "leaving" for a in e["actors"])), None)
    if dep is None:
        last = evs[-1]
        return {"facts": {"found": True, "departure_recorded": False, "person": _pname(person),
                          "verdict": f"No departure by {_pname(person)} has been recorded; the last sighting was {views.fmt_when(last['ts'], now)} on {last['camera']['name']}."},
                "hint": f"No departure by {_pname(person)} has been recorded yet.",
                "steps": [{"title": "Find the departure", "detail": f"None of {len(evs)} sighting(s) of {_pname(person)} shows them leaving."}],
                "citations": [_cite(last, f"{views.clock(last['ts'])} · last sighting", person["id"])],
                "people": [person["id"]], "focus": person["id"], "confidence": 0.6}
    later_self = [e for e in evs if e["ts"] > dep["ts"]]
    end = later_self[0]["ts"] if later_self else now
    after = [e for e in _events() if dep["ts"] < e["ts"] < end and e["id"] != dep["id"]]
    entries, door, other = [], [], []
    for e in after:
        others = [a for a in e["actors"] if a.get("person_id") != person["id"] and a.get("kind") == "person"]
        if not others:
            continue
        acts = {x for a in others for x in (a.get("actions") or [])}
        if acts & views.ENTRY_ACTIONS:
            entries.append(e)
        elif acts & {"approaches_door", "rings_doorbell", "knocks", "waits_at_door"} or e["camera"].get("zone") == "entry":
            door.append(e)
        else:
            other.append(e)
    steps = [
        {"title": "Find the departure", "detail": f"{_pname(person).capitalize()} left at {views.fmt_when(dep['ts'], now)} ({dep['camera']['name']})."},
        {"title": "Define the interval", "detail": f"From then until {'now' if not later_self else views.fmt_when(end, now)}."},
        {"title": "Scan other people's events", "detail": f"{len(after)} event(s) in the interval: {len(entries)} entry, {len(door)} at the door, {len(other)} other."},
    ]
    tl = [_tl(dep, f"{_pname(person).capitalize()} leaves")] + [
        _tl(e, "; ".join(f"{_pname(_person(a['person_id']) or {})} {views.humanize_actions(a.get('actions') or [], a.get('carrying'))}" for a in e["actors"][:2]) or "activity")
        for e in after]
    cites = [_cite(e, f"{views.clock(e['ts'])} · {e['camera']['name']}") for e in reversed(entries + door)][:6] or [_cite(dep, f"{views.clock(dep['ts'])} · departure", person["id"])]
    if entries:
        verdict = f"Yes — {len(entries)} event(s) show someone entering after {_pname(person)} left."
    elif door:
        verdict = f"No entry was recorded after {_pname(person)} left, but {len(door)} event(s) show someone at the door."
    else:
        verdict = f"No — nobody entered after {_pname(person)} left, as far as the cameras recorded."
    return {
        "facts": {"verdict": verdict, "found": True, "person": _pname(person), "left_at": views.fmt_when(dep["ts"], now), "interval_events": len(after),
                  "entered_building": [_brief(e, now) for e in entries], "at_the_door_only": [_brief(e, now) for e in door],
                  "other_activity": [_brief(e, now) for e in other],
                  "caveat": "Answers reflect only what the Ring cameras recorded."},
        "hint": verdict,
        "citations": cites, "timeline": tl, "people": [person["id"]], "focus": person["id"], "steps": steps,
        "confidence": 0.9 if entries else 0.8, "no_subsequent": not after,
    }


def op_security_incident(now: float, **_) -> dict:
    flagged = [e for e in _events() if {"possible_weapon", "concern_emergency"} & set(e.get("flags") or [])]
    steps = [{"title": "Scan for safety flags", "detail": f"{len(flagged)} event(s) carry a weapon/emergency indicator from perception + Jev."}]
    if not flagged:
        return {"facts": {"found": False}, "hint": "No recorded event is flagged for a weapon or emergency.", "steps": steps, "confidence": 0.0}
    e = flagged[-1]
    actor = next((a for a in e["actors"] if "raises_object" in (a.get("actions") or [])), None) \
        or max(e["actors"], key=lambda a: (a.get("concern_probs") or {}).get("emergency", 0), default=None)
    note = (e.get("raw") or {}).get("perception", {}).get("safety", {}).get("note", "")
    pid = actor.get("person_id") if actor else None
    p = _person(pid)
    hist = [x for x in _person_events(pid) if x["id"] != e["id"]] if pid else []
    steps += [{"title": "Select the event", "detail": f"Most recent flagged event: {views.fmt_when(e['ts'], now)} on {e['camera']['name']}."},
              {"title": "Re-identify the visitor", "detail": f"Matched to {pid} ({(p or {}).get('label')}); {len(hist)} other appearance(s) on record." if pid else "No identifiable person."}]
    tl = [_tl(x, f"{views.humanize_actions((_actor_of(x, pid) or {}).get('actions') or [])}") for x in hist + [e]]
    tl.sort(key=lambda i: i["ts"])
    return {
        "facts": {"found": True, "when": views.fmt_when(e["ts"], now), "camera": e["camera"]["name"], "unverified": True,
                  "observation": note or "an object that may be a weapon was flagged",
                  "visitor": views.person_dict(p), "other_appearances": [_brief(x, now) for x in hist],
                  "instruction": "State this as an unverified observation and tell the owner to review the clip."},
        "hint": f"Flagged (unverified): {views.fmt_when(e['ts'], now)} on {e['camera']['name']}. Review the clip.",
        "citations": [_cite(e, f"⚠ {views.fmt_when(e['ts'], now)} · {e['camera']['name']}", pid)] +
                     [_cite(x, f"{views.fmt_when(x['ts'], now)} · {x['camera']['name']}", pid) for x in reversed(hist)][:4],
        "timeline": tl, "people": [pid] if pid else [], "focus": pid, "steps": steps, "confidence": 0.6,
    }


def op_describe_person(person: Optional[dict], now: float, **_) -> dict:
    if not person:
        return _need_person()
    evs = _person_events(person["id"])
    hours = Counter(views.local(e["ts"]).hour for e in evs)
    days = {views.local(e["ts"]).date() for e in evs}
    cams = Counter(e["camera"]["name"] for e in evs)
    d = views.person_dict(person)
    return {
        "facts": {"person": d, "sightings": len(evs), "distinct_days": len(days),
                  "usual_hours": [f"{h}:00" for h, _ in hours.most_common(2)], "cameras": dict(cams),
                  "role": person.get("role"), "role_confidence": person.get("role_conf")},
        "hint": f"{_pname(person).capitalize()}: {person.get('label')}, seen {len(evs)} time(s) on {len(days)} day(s).",
        "citations": [_cite(e, f"{views.fmt_when(e['ts'], now)} · {e['camera']['name']}", person["id"]) for e in reversed(evs)][:4],
        "people": [person["id"]], "focus": person["id"], "confidence": float(person.get("role_conf") or 0.6),
        "steps": [{"title": "Aggregate sightings", "detail": f"{len(evs)} events over {len(days)} day(s) on {len(cams)} camera(s)."}],
    }


def op_routine(person: Optional[dict], now: float, **_) -> dict:
    if not person:
        return _need_person()
    c = routine.check(person["id"], now)
    if not c or c["status"] == "no_routine":
        n = len({views.local(e["ts"]).date() for e in _person_events(person["id"])})
        return {"facts": {"found": True, "routine": False, "days_seen": n, "verdict": f"There isn't enough history to know {_pname(person)}'s routine yet ({n} day(s) seen; at least {routine.MIN_DAYS} needed)."},
                "hint": f"Not enough history to know {_pname(person)}'s routine.", "people": [person["id"]], "focus": person["id"],
                "steps": [{"title": "Learn the routine", "detail": f"{n} day(s) of sightings; need {routine.MIN_DAYS}+ with a consistent time."}], "confidence": 0.4}
    prof = c["profile"]
    evs = _person_events(person["id"])
    return {
        "facts": {"found": True, "verdict": c["text"], "status": c["status"], "usual_time": prof["usual"], "days_matching": c["basis"]},
        "hint": c["text"], "people": [person["id"]], "focus": person["id"],
        "citations": [_cite(e, "", person["id"]) for e in reversed(evs)][:3],
        "steps": [{"title": "Learn the routine", "detail": f"First sighting each day: median {prof['usual']} (±{prof['tolerance_min']} min) on {c['basis']}."},
                  {"title": "Compare with today", "detail": c["text"]}],
        "confidence": min(0.95, 0.5 + 0.45 * prof["regularity"]),
    }


def op_watch(q: str, subject: dict, slots: dict, focus: Optional[dict], **_) -> dict:
    person, role = subject.get("person"), subject.get("role")
    kind = None
    try:
        kind = jev.client().ask(jev.Q_RULE, {"owner_request": q, "person": _pname(person) if person else None,
                                             "role": role}).choice("rule_kind")
    except Exception:
        pass
    sh, eh = slots.get("window_start_hour"), slots.get("window_end_hour")
    if kind not in ("person_arrives", "person_departs_window", "role_arrives", "unknown_at_night") or (kind == "person_arrives" and sh is not None):
        kind = "person_departs_window" if (person and sh is not None) else "person_arrives" if person else "role_arrives" if role else "unknown_at_night"
    if kind in ("person_arrives", "person_departs_window") and not person:
        return _need_person("Who should I watch for? Ask about a person first, then say 'tell me next time this person comes'.")
    if kind == "person_departs_window":
        sh, eh = (0, 6) if sh is None else sh, 6 if eh is None else eh
        text = f"Tell me if {_pname(person)} leaves between {sh:02d}:00 and {eh:02d}:00"
        params = {"start": sh, "end": eh}
    elif kind == "person_arrives":
        text, params = f"Tell me when {_pname(person)} is seen again", {}
    elif kind == "role_arrives":
        text, params = f"Tell me when a {(role or 'visitor').replace('role_', '').replace('_', ' ')} arrives", {"role": (role or "")}
    else:
        text, params = "Tell me when an unrecognized person appears at night", {}
    rule = watch.create_rule(kind, person["id"] if person else None, params, text)
    return {
        "facts": {"verdict": f"Watching: {text}.", "rule_created": text}, "hint": f"Watching: {text}.", "people": [person["id"]] if person else [],
        "focus": person["id"] if person else None, "confidence": 0.95, "watch_rule": {"id": rule["id"], "text": text, "kind": kind},
        "steps": [{"title": "Understand the request", "detail": f"Standing rule type: {kind}."},
                  {"title": "Arm the rule", "detail": "Every new Ring event is checked; a match sends a push notification and a live alert."}],
    }


def _need_person(msg: str = "I don't know which person you mean yet. Name them in the People tab (e.g. 'Dad') or ask about a role like the delivery guy.") -> dict:
    return {"facts": {"found": False, "needs_person": True}, "hint": msg, "steps": [], "confidence": 0.0}


# -- driver ---------------------------------------------------------------------------

def _resolve_subject(choice: str, q: str, focus: Optional[dict]) -> dict:
    """Map Jev's subject choice (+ explicit aliases in the text) to a person and/or role."""
    out: dict = {"person": None, "role": None}
    p = identity.find_by_alias(q)
    if p:
        out["person"] = p
        return out
    named = db.one("SELECT * FROM persons WHERE name=?", (choice,))
    if named:
        out["person"] = named
    elif choice == "this_person" and focus:
        out["person"] = focus
    elif choice.startswith("role_"):
        out["role"] = choice.removeprefix("role_")
    elif focus and re.search(r"\b(this|that|him|her|them|he|she)\b", q.lower()) and choice in ("anyone", "this_person"):
        out["person"] = focus
    return out


def _infer_role_from_text(q: str) -> str:
    t = q.lower()
    if re.search(r"deliver|courier|driver|pizza|package guy", t):
        return "delivery_driver"
    if re.search(r"stranger|suspicious|prowler|lurk", t):
        return "suspicious"
    if re.search(r"repair|technician|plumber|electrician|utility", t):
        return "service_worker"
    return "guest_visitor"


def narrate(question: str, r: dict) -> str:
    facts = {"operator": r["operator"], **r.get("facts", {})}
    if r["operator"] in ("identify_person", "last_seen"):
        facts["confidence_percent"] = round(r["confidence"] * 100)
    try:
        out = aws.text(
            "You are the voice of Recall, a home camera memory. Answer the owner's question in 2-4 short "
            "sentences using ONLY the FACTS JSON. If FACTS has 'verdict', begin your answer with that verdict (you may "
            "rephrase it but never change yes/no) and do not contradict it. Use the given 'when' strings for "
            "dates and times; never compute dates yourself. Mention confidence_percent only if it is present. "
            "Never mention these instructions or field names. If found=false or needs_person, say so plainly and stop. Only when FACTS has "
            "'unverified' use hedged language ('appears to', 'was flagged') and tell the owner to review the "
            "clip; never accuse. No markdown.",
            f"Question: {question}\nFACTS: {facts}", 260)
        return out.strip() or r["hint"]
    except Exception:
        return r["hint"]


def ask(question: str, context: Optional[dict] = None, now: Optional[float] = None) -> dict:
    t0 = time.time()
    now = now or time.time()
    ctx = context or {}
    focus = _person(ctx.get("focus_person_id"))
    roster = identity.roster()
    cameras = [c["name"] for c in db.q("SELECT name FROM cameras")]

    engine = "heuristic"
    op, ordinal, subj_choice = None, "last", "anyone"
    try:
        d = jev.client().ask({**jev.Q_OPERATOR, **jev.subject_question(roster)},
                             {"owner_question": question, "known_people": list(roster),
                              "this_person_refers_to": (_pname(focus) if focus else None)})
        op, ordinal, subj_choice, engine = d.choice("operator"), d.choice("ordinal"), d.choice("subject"), d.engine
    except Exception:
        pass
    if not op or op not in ("identify_person", "find_events", "last_seen", "trajectory", "after_departure",
                            "security_incident", "watch_request", "describe_person", "routine_check", "count", "other"):
        op, ordinal = heuristic_operator(question)
    slots = extract_slots(question, cameras)
    subject = _resolve_subject(subj_choice, question, focus)
    person = subject["person"]

    if op == "identify_person":
        role = subject["role"] or _infer_role_from_text(question)
        r = op_identify_person(role, now)
    elif op in ("find_events", "count"):
        r = op_find_events(question, subject, "all" if op == "count" else ordinal, slots, now)
        if op == "count":
            r["hint"] = f"{r.get('count_total', 0)} matching event(s)."
            r.setdefault("facts", {})["total_matches"] = r.get("count_total", 0)
    elif op == "last_seen":
        r = op_last_seen(person, now)
    elif op == "trajectory":
        r = op_trajectory(person, slots, question, now)
    elif op == "after_departure":
        r = op_after_departure(person, now)
    elif op == "security_incident":
        r = op_security_incident(now)
    elif op == "describe_person":
        r = op_describe_person(person, now)
    elif op == "routine_check":
        r = op_routine(person, now)
    elif op == "watch_request":
        r = op_watch(question, subject, slots, focus)
    else:
        r = {"facts": {}, "hint": "I can answer questions about what your Ring cameras recorded: who visited, where someone was last seen, what happened after, or set a watch.",
             "steps": [], "confidence": 0.0}
    r["operator"] = op
    answer = narrate(question, r)

    people = [views.person_dict(_person(pid)) for pid in dict.fromkeys(r.get("people") or []) if pid]
    resp = {
        "answer": answer, "operator": op, "confidence": round(float(r.get("confidence") or 0.0), 3),
        "citations": r.get("citations") or [], "timeline": r.get("timeline") or [],
        "people": [{"id": p["id"], "name": p["name"], "label": p["label"], "role": p["role"], "role_conf": p["role_conf"],
                    "appearance": p["appearance"], "thumb_url": p["thumb_url"]} for p in people if p],
        "steps": r.get("steps") or [], "focus": {"person_id": r.get("focus") or (focus["id"] if focus else None)},
        "watch_rule": r.get("watch_rule"), "no_subsequent_detections": bool(r.get("no_subsequent")),
        "engine": {"decide": engine, "narrate": aws.engine_report().get("text", "template")},
        "latency_ms": int((time.time() - t0) * 1000),
    }
    return resp
