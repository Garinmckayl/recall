# Staged footage for the demo

Drop your own clips here (`.mp4`/`.mov`, 5–20 s each, phone video is fine — HEVC is transcoded automatically)
and describe them in `manifest.json` (copy `manifest.example.json`). `python3 seed.py` then pushes them through
the Ring sandbox and the full pipeline. Without a manifest the bundled stock clips are used.

`manifest.json` fields per event: `clip`, `camera` (Front Door | Driveway | Garage | Backyard),
`kind` (`motion` | `doorbell`), `days_ago`, `time` (HH:MM), optional `label`, and optional
`name` + `relation` to enroll a person the way the owner would ("this is Dad").

## Shot list (what the 3-minute demo needs)

Use the **same person in the same clothes** wherever the same "person" must recur. Film in daylight/evening.

| # | Camera | Scene | days_ago | Notes |
|---|--------|-------|----------|-------|
| 1 | Front Door | **Delivery guy** (blue jacket) rings, hands over a **pizza box**, leaves | 12 | doorbell |
| 2 | Front Door | Same delivery guy with a **food bag** | 8 | doorbell |
| 3 | Front Door | Same guy with a **cardboard package**, leaves it, walks off | 3 | doorbell |
| 4 | Front Door | Same guy with a **pizza box** again (this is "the last pizza delivery") | 1 | doorbell |
| 5 | Front Door | 2–3 *other* visitors: a neighbour chatting, a flyer/salesperson, a friend let in | 10, 6, 2 | so "which guy?" is a real choice |
| 6 | Front Door | **Someone knocks** (not the doorbell), a person you can name | 6 | for "who knocked six days ago" |
| 7 | Backyard | **Dad** walks toward the garage | 0 (18:37) | |
| 8 | Garage | Dad enters the garage, gets in the car | 0 (18:42) | |
| 9 | Driveway | The car leaves the driveway | 0 (18:45) | Dad last seen here |
| 10 | Front Door | Optional: a *different* person walks up **after** Dad left | 0 (19:10) | for "did anyone enter after Dad left?" (film someone entering, or not, both are valid answers) |
| 11 | Front Door | **Staged** visitor briefly raises an obvious **prop** (e.g. a toy, clearly fake) | 4 | for the security query; use a prop, never a realistic replica |

Enroll Dad on clip 7 (`"name": "Dad", "relation": "father"`) and, if you like, name the delivery guy afterwards
in the People tab. Keep every clip's audio free of music you don't own (the demo video must not use unlicensed music).

## Footage in this folder
- `dad_old_driveway.mp4`, `dad_old_frontdoor.mp4`, `dad_old_backyard.mp4` — **AI-generated** with Amazon Nova Reel 1.1 (one multi-shot generation of the same older man, see `video/generate_reel.py`), trimmed before the model's face drift, converted to grayscale night-camera style. Used by the default `manifest.json`.
- `dad_driveway.mp4`, `dad_frontdoor.mp4`, `dad_backyard.mp4` — three cuts of one stock homecoming clip; used by `manifest_soldier.json` (the later scenes of the demo video were recorded with it).
- `manifest_hook.json` — the default events with fixed clock times (8:03 / 8:08 / 8:13 PM) used to record the video's opening; seed it after 8:13 PM on the day you record: `RECALL_MANIFEST=demo_clips/manifest_hook.json`.
- Everything else is stock footage from Mixkit (Mixkit Free License).
