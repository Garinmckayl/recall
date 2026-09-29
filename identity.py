"""IDENTITY: cross-event re-identification -> the persistent person graph.

Each actor sighting gets (a) a Titan image embedding of its body crop, (b) a Titan text embedding of
its appearance attributes, (c) a token-set attribute vector (garment colours etc.). A sighting joins
an existing person when the blended similarity to any stored exemplar clears REID_MATCH, otherwise a
new person_NN node is created. Appearance-based, not face recognition: it answers "the man in the
blue jacket", and it is deliberately conservative about merging.
"""
from __future__ import annotations

import io
import re
import time
from collections import Counter
from typing import Optional

from PIL import Image

import aws
import config
import db

FAMILY_RELATIONS = {"father", "dad", "mother", "mom", "son", "daughter", "brother", "sister", "grandfather",
                    "grandmother", "grandpa", "grandma", "wife", "husband", "partner", "spouse", "family", "self"}

_STOP = {"a", "an", "the", "and", "with", "of", "in", "on", "unknown", "none", "n", "a"}
_ATTR_KEYS = ("gender_presentation", "top", "bottom", "headwear", "hair", "build")


def crop_actor(frames: list[tuple[float, bytes]], actor: dict) -> Optional[bytes]:
    """Body crop from the actor's clearest frame (bbox is 0-1000 normalized); None if unusable."""
    bb = actor.get("bbox")
    idx = min(max(int(actor.get("bbox_frame", 1)) - 1, 0), len(frames) - 1)
    jpeg = frames[idx][1]
    if not bb:
        return None
    try:
        x1, y1, x2, y2 = [float(v) for v in bb]
        im = Image.open(io.BytesIO(jpeg)).convert("RGB")
        w, h = im.size
        x1, x2 = sorted((x1, x2))
        y1, y2 = sorted((y1, y2))
        pad_x, pad_y = (x2 - x1) * 0.05, (y2 - y1) * 0.03
        box = (max(0, (x1 - pad_x) / 1000 * w), max(0, (y1 - pad_y) / 1000 * h),
               min(w, (x2 + pad_x) / 1000 * w), min(h, (y2 + pad_y) / 1000 * h))
        if box[2] - box[0] < 24 or box[3] - box[1] < 24:
            return None
        out = io.BytesIO()
        im.crop(tuple(int(v) for v in box)).save(out, "JPEG", quality=88)
        return out.getvalue()
    except Exception:
        return None


def attr_tokens(appearance: dict) -> set[str]:
    toks: set[str] = set()
    for k in _ATTR_KEYS:
        v = appearance.get(k)
        if isinstance(v, str):
            for t in re.findall(r"[a-z]+", v.lower()):
                if t not in _STOP:
                    toks.add(f"{k[:2]}:{t}")
    return toks


def attr_similarity(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def appearance_text(actor: dict) -> str:
    ap = actor.get("appearance") or {}
    parts = [ap.get("gender_presentation"), ap.get("age"), ap.get("top"), ap.get("bottom"),
             ap.get("headwear"), ap.get("hair"), ap.get("build")]
    text = ", ".join(str(p) for p in parts if p and str(p).lower() not in ("unknown", "none"))
    return text or actor.get("description", "")[:120] or "person"


def blended(img_sim: Optional[float], txt_sim: float, attr_sim: float) -> float:
    if img_sim is None:
        return 0.55 * txt_sim + 0.45 * attr_sim
    return 0.35 * img_sim + 0.25 * txt_sim + 0.40 * attr_sim


def _score_against(person: dict, img: Optional[list[float]], txt: list[float], attrs: set[str]) -> float:
    best = 0.0
    for ex in person.get("exemplars") or []:
        i = aws.cosine(img, ex.get("img")) if (img and ex.get("img")) else None
        s = blended(i, aws.cosine(txt, ex.get("txt")), attr_similarity(attrs, set(ex.get("attrs") or [])))
        best = max(best, s)
    return best


def _next_person_id() -> str:
    r = db.one("SELECT COUNT(*) AS n FROM persons")
    n = (r["n"] if r else 0) + 1
    while db.one("SELECT 1 FROM persons WHERE id=?", (f"person_{n:02d}",)):
        n += 1
    return f"person_{n:02d}"


def assign(actor: dict, frames: list[tuple[float, bytes]], ts: float, exclude: set[str],
           thumb_path: Optional[str] = None) -> tuple[str, float, bool, dict]:
    """Match a sighting to a person node (creating one if needed). Returns (person_id, score, created)."""
    kind = actor.get("kind", "person")
    crop = crop_actor(frames, actor) if kind == "person" else None
    img = aws.embed_image(crop) if crop else None
    txt = aws.embed_text(appearance_text(actor))
    attrs = attr_tokens(actor.get("appearance") or {})

    best_id, best = None, 0.0
    for p in db.q("SELECT * FROM persons WHERE kind=?", (kind,)):
        if p["id"] in exclude:
            continue
        s = _score_against(p, img, txt, attrs)
        if s > best:
            best_id, best = p["id"], s

    exemplar = {"img": img, "txt": txt, "attrs": sorted(attrs), "ts": ts}
    if best_id and best >= config.REID_MATCH:
        p = db.one("SELECT * FROM persons WHERE id=?", (best_id,))
        ex = (p.get("exemplars") or []) + [exemplar]
        if len(ex) > config.REID_MAX_EXEMPLARS:          # keep the most recent, always keep the first
            ex = [ex[0]] + ex[-(config.REID_MAX_EXEMPLARS - 1):]
        db.update("persons", "id", best_id, exemplars=ex, n_obs=(p["n_obs"] or 0) + 1,
                  first_ts=min(p["first_ts"] or ts, ts), last_ts=max(p["last_ts"] or ts, ts))
        return best_id, best, False, exemplar

    pid = _next_person_id()
    db.insert("persons", id=pid, kind=kind, exemplars=[exemplar], text_embedding=txt, n_obs=1,
              first_ts=ts, last_ts=ts, thumb_path=thumb_path, created=time.time(),
              is_resident=0, aliases=[])
    return pid, best, True, exemplar


# -- labels / naming ------------------------------------------------------------------

def _mode(vals: list[str]) -> str:
    vals = [v.strip().lower() for v in vals if v and v.strip().lower() not in ("unknown", "none", "")]
    return Counter(vals).most_common(1)[0][0] if vals else ""


def refresh_label(person_id: str) -> str:
    """Display label: the most common short label the perceiver gave this person ('man in a blue jacket')."""
    rows = db.q("SELECT attrs, kind, description FROM actors WHERE person_id=?", (person_id,))
    if not rows:
        return "person"
    ap = [(r["attrs"] or {}) for r in rows]
    label = _mode([a.get("label", "") for a in ap])
    if not label:
        if rows[0]["kind"] == "pet":
            label = "pet"
        else:
            who = _mode([a.get("gender_presentation", "") for a in ap])
            who = who if who and who != "unknown" else "person"
            top = _mode([a.get("top", "") for a in ap])
            label = who + (f" in {top}" if top else "")
    db.update("persons", "id", person_id, label=label)
    return label


def name_person(person_id: str, name: str, relation: str = "", is_resident: Optional[bool] = None) -> dict:
    """Owner enrollment: 'this is Dad'. Names become query vocabulary (name, relation, aliases)."""
    name = name.strip()
    relation = (relation or "").strip().lower()
    aliases = sorted({a for a in (name.lower(), relation) if a})
    if relation in ("father", "dad"):
        aliases += ["father", "dad", "my father", "my dad"]
    if relation in ("mother", "mom"):
        aliases += ["mother", "mom", "my mother", "my mom"]
    res = is_resident if is_resident is not None else (relation in FAMILY_RELATIONS)
    db.update("persons", "id", person_id, name=name, relation=relation, aliases=sorted(set(aliases)),
              is_resident=1 if res else 0)
    return db.one("SELECT * FROM persons WHERE id=?", (person_id,))


def roster() -> dict[str, str]:
    """name -> description for the Jev subject question."""
    out = {}
    for p in db.q("SELECT * FROM persons WHERE name IS NOT NULL AND name != ''"):
        rel = f" ({p['relation']})" if p.get("relation") else ""
        out[p["name"]] = f"the person the owner calls {p['name']}{rel}"
    return out


def find_by_alias(text_: str) -> Optional[dict]:
    t = text_.lower()
    for p in db.q("SELECT * FROM persons WHERE name IS NOT NULL AND name != ''"):
        if any(a and a in t for a in (p.get("aliases") or [])) or p["name"].lower() in t:
            return p
    return None


# -- owner corrections ("that's not him") ---------------------------------------------
# Sightings carry their own embeddings, so a person's exemplar set can always be rebuilt from the
# sightings currently assigned to it. Merging/splitting therefore teaches future matching: the
# merged person matches either appearance, a split-off sighting seeds its own person.

def rebuild_person(person_id: str) -> Optional[dict]:
    """Recompute exemplars, counts, span, label and role from the person's current sightings."""
    import roles
    rows = db.q("SELECT a.emb, e.ts FROM actors a JOIN events e ON e.id=a.event_id WHERE a.person_id=? ORDER BY e.ts",
                (person_id,))
    if not rows:
        db.execute("DELETE FROM persons WHERE id=?", (person_id,))
        return None
    ex = [r["emb"] for r in rows if r.get("emb")]
    if len(ex) > config.REID_MAX_EXEMPLARS:
        ex = [ex[0]] + ex[-(config.REID_MAX_EXEMPLARS - 1):]
    db.update("persons", "id", person_id, exemplars=ex, n_obs=len(rows), first_ts=rows[0]["ts"], last_ts=rows[-1]["ts"])
    refresh_label(person_id)
    roles.aggregate(person_id)
    return db.one("SELECT * FROM persons WHERE id=?", (person_id,))


def merge_persons(src: str, dst: str) -> dict:
    """Owner says src and dst are the same person."""
    a, b = db.one("SELECT * FROM persons WHERE id=?", (src,)), db.one("SELECT * FROM persons WHERE id=?", (dst,))
    if not a or not b:
        raise ValueError("unknown person")
    if src == dst:
        raise ValueError("cannot merge a person into themselves")
    if a["kind"] != b["kind"]:
        raise ValueError("cannot merge a person with a pet")
    if not b.get("name") and a.get("name"):
        db.update("persons", "id", dst, name=a["name"], relation=a.get("relation"), aliases=a.get("aliases") or [],
                  is_resident=a.get("is_resident") or 0)
    if not b.get("thumb_path") and a.get("thumb_path"):
        db.update("persons", "id", dst, thumb_path=a["thumb_path"])
    db.execute("UPDATE actors SET person_id=? WHERE person_id=?", (dst, src))
    db.execute("UPDATE watch_rules SET person_id=? WHERE person_id=?", (dst, src))
    db.execute("DELETE FROM persons WHERE id=?", (src,))
    return rebuild_person(dst)


def reassign_actor(actor_id: int, to_person: Optional[str] = None) -> dict:
    """Owner says this sighting is someone else: move it to an existing person, or split it into a new one."""
    a = db.one("SELECT a.*, e.thumb_path AS ethumb, e.ts AS ets FROM actors a JOIN events e ON e.id=a.event_id WHERE a.id=?",
               (actor_id,))
    if not a:
        raise ValueError("unknown sighting")
    src = a["person_id"]
    if to_person:
        tgt = db.one("SELECT * FROM persons WHERE id=?", (to_person,))
        if not tgt:
            raise ValueError("unknown target person")
        if tgt["kind"] != a["kind"]:
            raise ValueError("person/pet mismatch")
        dst = to_person
    else:
        dst = _next_person_id()
        db.insert("persons", id=dst, kind=a["kind"], exemplars=[a["emb"]] if a.get("emb") else [], n_obs=1,
                  first_ts=a["ets"], last_ts=a["ets"], thumb_path=a.get("ethumb"), created=time.time(),
                  is_resident=0, aliases=[])
    if dst == src:
        raise ValueError("sighting is already assigned to that person")
    db.update("actors", "id", actor_id, person_id=dst, match_score=1.0)
    out = {"from": rebuild_person(src) if src else None, "to": rebuild_person(dst)}
    return out
