# 3-Minute Demo Script — Recall

Judges may stop at 3:00. Lead with the timeline, land three "wait, it reasoned" moments, close on the watch loop.
Record the screen with the UI at 1440×900. Pre-run `python3 seed.py`, then ask each question once to warm the models.
Every clip below comes from `demo_clips/` (see the shot list there) — replace the sample footage with your staged shots first.

| Time | On screen | Say |
|---|---|---|
| 0:00–0:15 | Timeline with dozens of events, the counts in the top bar | "Security cameras remember everything. Humans still have to find it. What if your home could remember?" |
| 0:15–0:40 | Ask **"Show me the last pizza delivery."** → click the citation, clip opens at the moment | "One exact event, with proof. That's the baseline." |
| 0:40–1:05 | **"Which guy is the delivery guy?"** → the reasoning steps animate: candidates → events → consistency → ranking. Click two citations. | "Not search. It looked at every person in every event, scored the role from what they carried and did, and checked it across days. The confidence is a stored posterior, not a language model's guess." |
| 1:05–1:35 | **"Where was my father last seen?"** → Path lanes light up Backyard → Garage → Driveway, dashed "no subsequent detections" | "Three cameras, one path. This is caretaking: I didn't search a clip, I asked where he went." |
| 1:35–1:55 | **"Did anyone enter after he left?"** → answer + the interval events | "It reasons over identity, ordering and location across events — and tells me exactly what the cameras did and didn't record." |
| 1:55–2:15 | **"Who pulled a gun at my door?"** → flagged event first (⚠ possible weapon, unverified), then the same visitor's other appearances | "Careful language: 'appears to', unverified, the clip is ground truth. Then it re-identifies that visitor across every other event." (Staged; clearly a prop.) |
| 2:15–2:35 | Architecture: Ring signed webhook → Nova → Jev → Titan → graph → operators → evidence. Show the Reasoning stepper + Demo drawer | "Ring API in, Amazon Nova for vision, Titan for re-identification, typed decision models for roles and intent. Alexa+ can call it today over MCP." (Optionally one `curl` to `/mcp`.) |
| 2:35–3:00 | Ask **"Tell me next time this person comes."** → rule card. Then **Demo → Emit Ring event** → toast alert + phone push | "See, remember, understand, answer, watch, act. Ring records what happened. Recall remembers what it means. Ask your home anything." |

### Notes
- Show the phone receiving the ntfy push in a corner (subscribe to your `NTFY_TOPIC`).
- Do not use unlicensed music. Demo video must show the app running against the Ring sandbox/simulator or a device — say so on screen ("Ring sandbox, signed webhook").
- Keep the security question hedged and clearly staged; never imply a real accusation.
- Answers take ~1.5 s (Jev + Nova). If one stalls on camera, cut to a pre-recorded take.
