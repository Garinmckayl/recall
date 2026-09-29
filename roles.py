"""ROLES: Jev decides each actor's role per event; roles are then aggregated ACROSS events per person.

"Which guy is the delivery guy?" is not a similarity search: a person's role is the evidence-weighted
posterior over every event they appear in, shrunk toward 'unknown' so a single sighting never yields
certainty. Every number shown to the user comes from here, never from an LLM.
"""
from __future__ import annotations

import datetime as dt
from typing import Optional

import config
import db
import jev


def _probs(d: jev.Decision, name: str) -> dict[str, float]:
    p = d.probabilities(name)
    if p:
        return p
    # LLM-fallback path returns no distribution: spread the residual mass evenly.
    choice, conf = d.choice(name), max(min(d.conf(name), 0.99), 0.34)
    opts = list(jev.ROLES) if name == "role" else list(jev.Q_FRAME["concern"]["criteria"])
    rest = (1 - conf) / max(len(opts) - 1, 1)
    return {o: (conf if o == choice else rest) for o in opts}


def decide_actor(actor: dict, others: list[dict], camera: dict, ts: float, summary: str,
                 objects: list[dict], safety: dict) -> dict:
    hour = dt.datetime.fromtimestamp(ts).hour
    state = {
        "camera": camera.get("name"), "camera_zone": camera.get("zone"),
        "hour": hour, "night": hour >= 20 or hour < 6,
        "event_summary": summary,
        "actor": {"description": actor.get("description"), "appearance": actor.get("appearance"),
                  "carrying": actor.get("carrying"), "actions": actor.get("actions"),
                  "direction": actor.get("direction")},
        "other_actors": [{"description": o.get("description"), "actions": o.get("actions")} for o in others],
        "objects_in_scene": [o.get("label") for o in objects],
        "safety_observation": safety,
    }
    d = jev.client().ask({**jev.Q_ROLE}, state)
    return {
        "role": d.choice("role"), "role_conf": d.conf("role"), "role_probs": _probs(d, "role"),
        "concern": d.choice("concern"), "concern_score": d.score01("concern_score"),
        "concern_probs": _probs(d, "concern"), "engine": d.engine, "latency_ms": d.latency_ms,
    }


def aggregate(person_id: str) -> Optional[dict]:
    """Evidence-weighted role posterior for one person across all their events."""
    p = db.one("SELECT * FROM persons WHERE id=?", (person_id,))
    if not p:
        return None
    rows = db.q("SELECT a.event_id, a.role_probs, e.ts FROM actors a JOIN events e ON e.id=a.event_id "
                "WHERE a.person_id=? AND a.role_probs IS NOT NULL ORDER BY e.ts", (person_id,))
    n = len(rows)
    if p.get("is_resident"):
        probs = {"resident_family": 1.0}
        res = {"role": "resident_family", "role_conf": 1.0, "role_probs": probs, "role_evidence": []}
        db.update("persons", "id", person_id, **res)
        return res
    if n == 0:
        return None
    mass = config.ROLE_PRIOR_MASS
    score = {r: 0.0 for r in jev.ROLES}
    for r in rows:
        for role, pr in (r["role_probs"] or {}).items():
            if role in score:
                score[role] += pr
    score["unknown"] += mass
    total = n + mass
    post = {r: round(v / total, 4) for r, v in score.items()}
    top = max(post, key=post.get)
    ranked = sorted(rows, key=lambda r: (r["role_probs"] or {}).get(top, 0), reverse=True)
    evidence = [{"event_id": r["event_id"], "ts": r["ts"], "p": round((r["role_probs"] or {}).get(top, 0), 3)}
                for r in ranked[:8]]
    res = {"role": top, "role_conf": post[top], "role_probs": post, "role_evidence": evidence}
    db.update("persons", "id", person_id, **res)
    return res


def role_posterior_for(person: dict, role: str) -> float:
    return float((person.get("role_probs") or {}).get(role, 0.0))
