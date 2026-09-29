# Recall

**Amazon Developer Hackathon — Ring track (caretaking) · AWS Builder mini challenge · Open Source mini challenge · Alexa+ MCP server**

Ring finds videos. **Recall answers questions about what happened — and proves the answer with the exact clip.**

It turns a Ring camera archive into a persistent, queryable memory of the physical world:

> *"Which guy is the delivery guy?"* → the man in the blue jacket — in 4 events he arrived carrying food/packages, went to the door, and left. **[Sep 26 · pizza] [Sep 21 · food] [Sep 17 · package]** → click a citation, the clip opens at the right second.
> *"Where was my father last seen?"* → Backyard → Garage → Driveway, then no further detections.
> *"Did anyone enter after Dad left?"* · *"Who knocked six days ago?"* · *"Tell me next time this person comes."*

That is cross-event inference over an identity graph, not search.

```
Ring API / webhook ─► PERCEIVE ─► ROLES ─► IDENTITY ─► MEMORY ─► QUERY ─► answer + evidence
  (signed, HMAC)      Nova Pro     Jev      Titan      SQLite     Jev +      Nova Lite narrates
                      keyframes→   per-actor re-id →    graph      operators  only from facts
                      structured   role +    person_NN                                 │
                      event        concern   nodes                          WATCH ◄─────┘
                                                                     "tell me next time…" → push + live alert
```

## What is real

| Layer | Implementation |
|---|---|
| **Ring** | `ring_api.py` is a client for the Ring Partner API (`api.amazonvision.com`, OAuth bearer, JSON:API): device discovery, event history, clip + snapshot download; `POST /ring/webhook` verifies `X-Signature: sha256=` (HMAC-SHA256 over the raw body), dedupes on `meta.request_id`, ACKs immediately and processes async. With `RING_ACCESS_TOKEN` it talks to the live platform; without it, to `ring_sim.py` — a local sandbox that serves the same endpoints and sends *signed* webhooks. Same code path either way. |
| **Perception (AWS)** | Amazon Nova Pro (Bedrock Converse, multi-image): 6 keyframes → one structured record: actors tracked across frames, appearance, carried objects, actions, interactions, bounding box, hedged safety observation. It observes only; it never names people or decides roles. |
| **Decisions** | Every classification is a typed, calibrated choice from TypeSafe's Jev model via the Decisions API: each actor's role and concern, the query operator, the subject, the watch-rule kind (~130 ms per call). Generative models only observe and narrate. |
| **Re-identification (AWS)** | Titan image embedding of the body crop + Titan text embedding of appearance + attribute overlap → a blended score against stored exemplars; `person_NN` nodes persist across events, days and cameras. Appearance-based, **not face recognition**. |
| **Roles across events** | A person's role is the evidence-weighted posterior over all their events, shrunk toward "unknown". "86%" is that number, not an LLM's opinion. |
| **Reasoning** | `query.py` operators: `identify_person`, `find_events`, `last_seen`, `trajectory`, `after_departure`, `security_incident`, `describe_person`, `count`, `watch_request`. Dates are resolved by `timeparse.py`, never by a model. Every answer carries citations, a timeline and human-readable reasoning steps. |
| **Evidence you can see** | Perception returns a body box for every keyframe; the UI interpolates it over the clip so a citation shows *who* it is talking about, not just a timestamp. |
| **Routine (caretaking)** | `routine.py` learns each person's usual time of day from their own sightings (median ± MAD, needs 3+ days and 60% regularity) and flags a named person who is missing or unusually early/late. Statistics only — explainable and tested. Ask "Is Mom's day normal today?" or see it in the Today card. |
| **Corrections** | "That's not him": move a sighting to another person or split it into a new one, or merge two people. Every sighting stores its own embedding, so identities are rebuilt from the sightings that remain and future matching improves. |
| **Watch** | Standing rules from conversation (`person_arrives`, `person_departs_window`, `role_arrives`, `unknown_at_night`) evaluated on every new event → ntfy push + live alert. |
| **Alexa+** | `POST /mcp` — Streamable HTTP, JSON-RPC 2.0, protocol `2025-11-25`, Origin validation, optional bearer (`MCP_TOKEN`). Tools: `ask_home`, `last_seen`, `get_timeline`, `list_people`, `watch_for`. |

## Run it

```bash
pip install -r requirements.txt
cp .env.example .env            # OPENROUTER_API_KEY (Jev), AWS creds via the standard AWS chain
python3 -m uvicorn server:app --host 127.0.0.1 --port 8000     # UI at http://localhost:8000
python3 rehearse.py             # optional: check what perception sees in your staged clips before recording
python3 seed.py                 # back-fill a multi-day history through the Ring sandbox + full pipeline (~30 s)
python3 -m pytest tests -q      # 29 offline tests (Jev/Nova/network stubbed)
```

In the UI, ask the suggested questions, then open **Demo** to emit a live Ring event (goes through the signed-webhook path) and watch a standing rule fire.

`rehearse.py` runs perception + role decisions on each clip without touching the memory and checks the `expect` block in the manifest (actions, carried objects, role, flags), so you know a staged shot will support its demo question.

`seed.py` uses `demo_clips/manifest.json` if present (your staged footage — see `demo_clips/README.md` for the shot list), otherwise a small sample manifest over stock clips in `media/raw/`.

### Going live with real Ring
Set `RING_ACCESS_TOKEN` (and `RING_HMAC_KEY` for webhook verification), expose `/ring/webhook` over HTTPS, then `POST /api/ring/sync` to back-fill history. Requires Ring Developer early-access credentials and at least one Ring device.

## Honest limitations
- Re-identification is appearance-based (clothing, build, colour). Someone who changes clothes becomes a new person until named; two people dressed alike can merge. Thresholds (`REID_MATCH`) were calibrated on a small clip set — see `FRICTION_LOG.md`.
- **Security flags are unverified observations**, phrased as such ("appears to raise an object consistent with a handgun"); the clip is the ground truth. This is a demo of memory and retrieval, not a weapon detector.
- Demo history is seeded; only the ingest path is real. The sample footage is stock video, not a real household.
- Frames are processed by Amazon Bedrock; memory (SQLite, clips, thumbnails) stays in `data/` on your machine.
- No auth on the UI/API (demo deployment); MCP supports an optional bearer token.

## Layout
`server.py` API+UI+webhook+MCP · `ring_api.py` client/HMAC · `ring_sim.py` sandbox · `pipeline.py` ingest · `perceive.py` Nova · `identity.py` re-id · `roles.py` Jev roles · `query.py` operators · `watch.py` rules · `timeparse.py` · `aws.py` Bedrock · `jev.py` Decisions API + question sets · `db.py`/`views.py` · `static/index.html` UI · `seed.py` · `tests/`.
`docs/v1/` holds the earlier HomeGuard prototype docs; the flat legacy modules (`agent.py`, `state.py`, `forensics.py`, `vision.py`, `enroll.py`, `main.py`, `scenarios/`) belong to that prototype and are not used by Recall.

Sample footage in `demo_clips/` is stock video from [Mixkit](https://mixkit.co/license/#videoFree) (Mixkit Free License); it stands in for a real household.

MIT licensed. Built during the hackathon window (Aug 31 – Oct 23, 2026); the HomeGuard prototype it grew from is described in `docs/v1/`.
