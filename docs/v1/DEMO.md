# 3-Minute Demo Script — Jev HomeGuard

Lead with the money shot. Judges may stop watching at 3:00.

## 0:00–0:25 — Cold open (the money shot, no intro)
Screen already on the UI. Click **▶ Run real footage**. Video plays at real speed.
Narrate over it, one line:

> "This is my home's camera. Jev is watching it — and every decision it makes, it makes in 130 milliseconds."

Point at the timeline filling: 👀 SEE cards appear, 🧠 amber anomaly on the night scene, ⚡ **the phone buzzes on camera** (real ntfy push, pre-recorded phone in frame or picture-in-picture).

## 0:25–0:55 — The brain is Jev (System One split)
Show one decision live:

> "There's no giant LLM reasoning here. DeepSeek's flash vision model only *describes* what it sees. Then Jev — TypeSafe's System One model on the Decisions API — makes every decision: who is this, what are they doing, how concerning, should I act. Typed answers, full probability distributions, ~130 milliseconds, five hundredths of a cent."

Show a `identity: stranger @ 0.97` probability blob from a Jev call (terminal or the evidence drawer).

## 0:55–1:30 — The killer query
Type: **"Show me the last time my father was seen."**
Answer appears with citations. **Click the citation** — the video *jumps* to the moment and stamps **📍 Dad · 21:29** over the footage.

> "Persistent memory, natural-language forensics, and it takes you to the exact second of footage."

## 1:30–2:00 — Ring + Alexa (the tracks)
1. Click **🔔 Ring motion** — narrate: "A Ring motion event just hit our webhook — the same pipeline a Ring Alexa routine would trigger. The agent grabbed the frame, understood it, and would act on it."
2. Terminal: MCP `tools/call` → `ask_home("where was dad last seen?")` → JSON answer.

> "This is a real MCP server — Streamable HTTP, spec 2025-11-25. An Alexa+ agent can call `ask_home` exactly like this today."

## 2:00–2:30 — It's alive (live mode)
Click **🎥 Go live**. Webcam comes on; Jev starts deciding on YOU, live, ~2s cadence.

> "Same brain, live camera, real time. It just understood me in 140 milliseconds."

## 2:30–3:00 — Close on the caretaking story
> "Sixty-five million homes have a camera watching their door and it does... nothing. This one watches over the people you love: it knows your family by enrollment, ignores the honest courier, and when someone lingers in the dark at 00:40 — your phone buzzes, and the agent already looked up the non-emergency police line. Jev decides. You sleep."

---

### Shooting notes
- Pre-warm: run once before recording so the timeline is hot; the first run includes model warm-up.
- The phone push is real: ntfy topic subscription — record the phone receiving it in frame.
- Keep a terminal pane with the last Jev response JSON visible for the 0:25–0:55 segment.
- If live-webcam panics, cut it — 2:00–2:30 can be the multi-camera append instead ("＋ Second angle" button).
