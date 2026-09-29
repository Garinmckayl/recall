"""Rehearse staged clips before recording the demo: run perception + role decisions on each manifest
clip WITHOUT touching the memory, and check what the demo question will need (`expect` in the manifest).

    python3 rehearse.py                 # every clip in demo_clips/manifest.json
    python3 rehearse.py knock.mp4 ...   # just these clips

Example expectations (manifest event):
    "expect": {"actions": ["enters_vehicle"], "carrying": ["pizza"], "role": "delivery_driver",
               "flag": "possible_weapon", "min_actors": 1}
"""
from __future__ import annotations

import sys

import config
import perceive
import ring_sim
import roles
import seed


def check_expect(expect: dict, rec: dict, decided: list[dict]) -> list[tuple[str, bool, str]]:
    """Pure: compare an expectation block with what perception/roles produced."""
    out = []
    actors = rec.get("actors", [])
    acts = {x for a in actors for x in a.get("actions", [])}
    carried = " ".join(c for a in actors for c in a.get("carrying", [])) + " " + " ".join(o["label"] for o in rec.get("objects", []))
    if "min_actors" in expect:
        out.append(("actors", len(actors) >= expect["min_actors"], f"{len(actors)} seen, want >= {expect['min_actors']}"))
    for want in expect.get("actions", []):
        out.append((f"action {want}", want in acts, f"saw {sorted(acts) or 'none'}"))
    for want in expect.get("carrying", []):
        out.append((f"carrying {want}", want.lower() in carried.lower(), f"saw '{carried.strip()[:60]}'"))
    if "role" in expect:
        best = max((d["role_probs"].get(expect["role"], 0.0) for d in decided), default=0.0)
        out.append((f"role {expect['role']}", best >= 0.5, f"best probability {best:.0%}"))
    if "flag" in expect:
        got = {"possible_weapon": rec.get("safety", {}).get("possible_weapon"),
               "knocks": rec.get("knocks"), "rings_doorbell": rec.get("rings_doorbell")}.get(expect["flag"])
        if expect["flag"] in ("concern_suspicious", "concern_emergency"):
            got = any(d["concern"] == expect["flag"].removeprefix("concern_") for d in decided)
        out.append((f"flag {expect['flag']}", bool(got), "raised" if got else "NOT raised"))
    return out


def rehearse(entry: dict) -> dict:
    clip = ring_sim.resolve_clip(entry["clip"])
    if clip is None:
        return {"clip": entry["clip"], "error": "clip not found"}
    dev = next((d for d in ring_sim.DEFAULT_DEVICES if d["name"] == entry["camera"]), ring_sim.DEFAULT_DEVICES[0])
    ts = seed._when(entry["days_ago"], entry["time"])
    rec, _ = perceive.perceive(clip, dev["name"], dev["zone"], entry.get("kind", "motion"), ts)
    cam = {"name": dev["name"], "zone": dev["zone"]}
    decided = [roles.decide_actor(a, [o for o in rec["actors"] if o is not a], cam, ts, rec["summary"], rec["objects"], rec["safety"])
               for a in rec["actors"]]
    return {"clip": entry["clip"], "rec": rec, "decided": decided,
            "checks": check_expect(entry.get("expect", {}), rec, decided)}


def main(argv: list[str]) -> int:
    entries = [e for e in seed.load_manifest()["events"] if not argv or e["clip"] in argv]
    seen, bad = set(), 0
    for e in entries:
        key = (e["clip"], e["camera"])
        if key in seen:
            continue
        seen.add(key)
        r = rehearse(e)
        print(f"\n== {e['clip']}  ({e['camera']}, {e.get('label', '')})")
        if r.get("error"):
            print("   ", r["error"]); bad += 1; continue
        rec = r["rec"]
        print("   summary:", rec["summary"])
        for a, d in zip(rec["actors"], r["decided"]):
            print(f"   - {a['appearance'].get('label') or a['description'][:40]:<32} actions={a['actions']} carrying={a['carrying']} "
                  f"role={d['role']} ({d['role_probs'].get(d['role'], 0):.0%}) concern={d['concern']}")
        print("   flags: weapon=%s knocks=%s doorbell=%s" % (rec["safety"]["possible_weapon"], rec["knocks"], rec["rings_doorbell"]),
              rec["safety"]["note"])
        for name, ok, detail in r["checks"]:
            print(f"   [{'PASS' if ok else 'MISS'}] {name}: {detail}")
            bad += 0 if ok else 1
    print(f"\n{'All expectations met.' if not bad else f'{bad} expectation(s) missed — re-shoot or adjust the demo question.'}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
