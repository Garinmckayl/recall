# Jev HomeGuard 🏠

**Amazon Developer Hackathon — Ring track (caretaking) + AWS Builder & Open Source mini challenges**

A home security agent that *understands* the people at your door: it watches
Ring-style footage, **enrolls your family**, ignores the honest courier, and when
someone lingers in the dark at 00:40 — **your phone buzzes** with a real
notification while the agent already looked up the non-emergency police line.

Then you ask it: *"Show me the last time my father was seen"* — and it takes you
to the exact second of footage.

```
frames ──► 👀 SEE (DeepSeek flash vision describes) ──► 🧠 UNDERSTAND (JEV decides: who/what/concern/act)
                                                                        │
        ⚡ ACT (ntfy push + web action) ◄── trigger ◄────────────────────┘
        🔮 ASK (Jev-typed intent → deterministic forensics → narrated answer + video jump)
```

## The System One architecture (why Jev is the brain)

LLMs perceive and narrate; **every decision is a TypeSafe Jev call** on the
Decisions API (`typesafe/jev-1.13`):

- per-frame: `kind` / `identity` / `activity` / `concern` (choice) + `concern_score` (score)
- proactive trigger: `act` / `urgency` / `web_action` / **`routine`** (the gate that keeps honest couriers from tripping the prowler alarm)
- forensic queries: `intent` / `subject` / `output` ("show me" → the UI jumps the video)

Every answer is typed with a **calibrated probability distribution** and lands in
**70–300 ms** at **~$0.00002/call**. Security stance is encoded in the questions,
not the prompt: *unconfirmed people are strangers, not residents*.

Eyes: `deepseek/deepseek-v4-flash-vision-exp` ($0.22/MTok). Mouth: `z-ai/glm-5.3-flash`
($0.09/MTok) — or **Amazon Nova via Bedrock** when AWS creds are present.

## Hackathon tracks

| Track | How we comply |
|---|---|
| **Ring (primary)** — caretaking | `/ring/webhook` accepts Ring-style motion/ding event payloads (simulator, per track rules); the event wakes the agent → frame → full pipeline. Real "Ring day" footage + upload for your own clips. |
| **AWS Builder (mini)** | `bedrock.py` — narration/notification text on **Amazon Nova** (`us.amazon.nova-lite-v1:0`) via boto3 `bedrock-runtime`, auto-detected when AWS creds exist. See `FRICTION_LOG.md` for the Bedrock schema friction. |
| **Open Source (mini)** | This repo — MIT licensed, built during the hackathon window. |
| **Alexa+ (credibility)** | A real **MCP server** at `POST /mcp` (JSON-RPC 2.0, Streamable HTTP, spec 2025-11-25) with `ask_home` / `get_timeline` / `last_seen` tools — exactly what an Alexa+ agent would call. |

## Run it

```bash
pip install -r requirements.txt
python3 -m uvicorn main:app --reload     # http://localhost:8000
```

1. **▶ Run real footage** — a free-licensed "Ring day": Mom leaves, courier
   delivers, the dog roams, Dad (enrolled) comes home, and a night prowler
   triggers a **real push notification** (ntfy; scan `/notify-qr` to subscribe your phone).
2. Ask **"Show me the last time my father was seen"** — click the citation → the
   video jumps and stamps the moment.
3. **🔔 Ring motion** — fire a simulated Ring event at the agent.
4. **＋ Second angle** — append another clip *without wiping memory* (multi-camera day).
5. **🎥 Go live** — webcam → Jev decides on you in real time.
6. MCP: `curl -X POST $BASE/mcp -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"ask_home","arguments":{"question":"where was dad last seen?"}}}'`

## Architecture

| File | Role |
|---|---|
| `vision.py` | 👀 perception: structured per-subject descriptions (people separate, animals, packages, overlay text) |
| `jev.py` | 🧠 the System One decision layer: typed question sets + the Decisions API client + LLM fallback |
| `state.py` | persistent world: identity hysteresis, append-only event timeline (JSONL) |
| `enroll.py` | Ring-style resident enrollment (reference appearance descriptions) |
| `agent.py` | orchestrator: batch + single-frame (live/webhook) modes, routine-gated ACT |
| `actions.py` | ⚡ ntfy push + web action (Exa or marked simulation) |
| `forensics.py` | 🔮 Jev-typed intent → deterministic executors → citations → narration |
| `bedrock.py` | Amazon Nova narration (AWS Builder mini challenge) |
| `main.py` | FastAPI: UI, `/ring/webhook`, `/live/frame`, `/mcp`, `/ask` |
| `scenarios/` | synthetic + real-footage "Ring day" composers (ffmpeg, Mixkit License) |
| `FRICTION_LOG.md` | honest integration friction (Jev, Ring, Bedrock, MCP) |
| `DEMO.md` | the 3-minute video script |

## Notes
- `.env` holds keys (OpenRouter, optional EXA/AWS/ntfy topic). The ntfy topic is the push secret.
- Tests: `python3 -m pytest tests/ -q` (12 passing, network mocked).
- No auth, no billing — it's a demo, deliberately.
