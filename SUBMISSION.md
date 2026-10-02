# Devpost submission — Recall

Paste each block into the matching Devpost field. Two placeholders remain: `[[VIDEO URL]]` and `[[LIVE DEMO URL]]`.

---

## Project name
Recall

## Elevator pitch (181 characters)
Persistent visual memory for caretaking and safety: ask your Ring cameras where Dad was last seen and get one reconstructed answer with proof, plus a heads-up when a routine breaks.

## Tracks and challenges entered
- **Ring** (primary) — caretaking
- **AWS Builder** mini challenge
- **Open Source** mini challenge
- **Alexa+** — an MCP server is included as an integration surface (not entered as a separate track project)

## Links
- **Code:** https://github.com/Garinmckayl/recall (public, MIT license)
- **Demo video (2:56):** [[VIDEO URL]]
- **Try it live:** [[LIVE DEMO URL]]
- **Product feedback:** [`PRODUCT_FEEDBACK.md`](https://github.com/Garinmckayl/recall/blob/main/PRODUCT_FEEDBACK.md) · **Friction log:** [`FRICTION_LOG.md`](https://github.com/Garinmckayl/recall/blob/main/FRICTION_LOG.md)

---

## Inspiration
It's 8:20 PM. Your father is 81 and lives alone. He isn't answering his phone.

The cameras have already seen everything. But today you still have to know where to look — and scrub through hours of clips while your pulse climbs. Three out of four adults over 50 want to stay in their own homes as they age ([AARP, 2024](https://www.aarp.org/home-living/home-community-preferences-survey-2024/)). One in four older adults falls every year — over 14 million people ([CDC](https://www.cdc.gov/falls/data-research/facts-stats/index.html)) — and in a cohort of people over 90, 30% of those who fell lay on the floor for an hour or more, which was strongly associated with serious injury, hospital admission and moves into long-term care ([BMJ, 2008](https://pmc.ncbi.nlm.nih.gov/articles/PMC2590903/)). Even Ring's own help page says video search may not return results for "specific people or characteristics" or "searches phrased as questions" ([Ring](https://ring.com/support/articles/4l5lb/smart-video-search)) — exactly how a worried family member asks. A camera shows you a video. A caregiver needs an answer.

## What it does
Not security AI. Not video search. Not facial recognition. **Persistent visual memory for caretaking and safety.**

Ask **"Where was Dad last seen?"** and instead of "3 matching videos" Recall gives one reconstructed answer: *Dad was last seen today at 8:13 PM in the Backyard* — with the path (Driveway 8:03 → Front Door 8:08 → Backyard 8:13), a box on him in every clip, the exact second to jump to, and a plain "no later detections."

- **It reasons across cameras and time.** The same person is recognised across cameras and days; each answer is assembled from many events, and every step (who, when, where, how sure) is shown.
- **It doesn't wait to be asked.** Recall learns each named person's routine from their own history and pushes a check-in when the day breaks pattern: *"Mom usually appears around 7:30 AM (6 of the last 6 days). Nothing yet today."* It notices what *didn't* happen.
- **It watches on request.** "Tell me next time this person comes" creates a standing rule; every new Ring event is checked and a match sends a push notification.
- **You stay in control.** "That's not him" — move a sighting, split a person, merge two — and identity improves. Safety observations are always labelled *unverified*; the clip is the ground truth. Recall does no face recognition and keeps no face templates.
- **Agents can use it.** An MCP server (Streamable HTTP, spec 2025-11-25) exposes `ask_home`, `last_seen`, `get_timeline`, `list_people` and `watch_for`, so Alexa+ and any MCP agent can ask a home a question.

The same memory answers "which guy is the delivery guy?" or "who knocked six days ago?" — but caretaking is the point.

## How we built it
`Ring event → Perceive → Decide → Re-identify → Memory graph → Reason → Answer + evidence → Watch`

- **Ring (repo calls Ring at runtime):** `ring_api.py` is a client for the Ring Partner API (device discovery, event history, clip and snapshot download); `server.py` receives Ring webhooks, verifying `X-Signature` (HMAC-SHA256 over the raw body), de-duplicating on `meta.request_id` and acknowledging immediately; `pipeline.py` pulls clips through the client and ingests them. With credentials it talks to the live platform; without them, to a local sandbox (`ring_sim.py`) that serves the same endpoints and sends signed webhooks — one code path either way.
- **Amazon Bedrock (AWS Builder):** Amazon **Nova Pro** reads six keyframes per clip in one Converse call and returns a structured event record (actors, appearance, carried objects, actions, interactions, a body box per keyframe, hedged safety observations). Amazon **Nova Lite** extracts query slots and narrates strictly from evidence. Amazon **Titan** embeddings (body-crop images and appearance text) drive person re-identification and semantic event retrieval. Integration details, what worked and what needs work are in `PRODUCT_FEEDBACK.md`.
- **Decisions:** every classification — an actor's role and concern, the question's reasoning operator, the subject, the watch-rule type — is a typed, calibrated choice from TypeSafe's Jev model through the Decisions API. Generative models observe and narrate; they never decide.
- **Reasoning:** deterministic operators over a SQLite memory graph (identify a role, find events, last seen, trajectory, after-departure, security incident, routine check, count, watch). Dates are resolved by code, not a model. A routine engine (median ± MAD) learns usual times; a background loop pushes check-ins.
- **UI:** a single-file light interface — timeline, chat, evidence panel with video overlays, reasoning steps, People, and a "Needs attention" digest.
- **Quality and safety:** 34 offline tests; a rehearsal tool that checks staged clips will support their demo question; rate limits and an admin token for public deployment.

## Challenges we ran into
- **Real Ring access.** The live platform needs early-access credentials, an ID check and a device. We built a faithful sandbox and kept one client code path for both. Parts of the docs we could read were truncated (webhook payload, download bodies), so parsing is deliberately tolerant — documented in the friction log.
- **Re-identification without faces.** Generic image embeddings leak background and framing. We blend image, text and attribute similarity and keep exemplar sets that can be rebuilt after owner corrections.
- **Honest answers.** An early version narrated "Yes" while its own facts said "no entry recorded". A computed verdict is now the first sentence of every answer, with tests to keep it that way.
- **Trust.** No accusatory language for safety events; they are flagged as unverified observations.

## Accomplishments that we're proud of
- A hero answer that reads like a person and comes with **proof you can click** — a three-camera path with a box on the person in every clip.
- A real memory: the same person recognised across cameras and days in seconds.
- A working **live loop**: signed webhook → ingest → re-identify → rule fires → push notification.
- **Proactive** caretaking: Recall pushes a check-in when a routine breaks — the case no clip search can find, because nothing happened.

## What we learned
Search finds videos; memory answers questions. The biggest gains came from separating what a model *sees* from what the system *decides*, storing small structured records instead of re-watching video, and making every number traceable to stored evidence.

## What's next
Live event history and subscriptions on real Ring accounts, multi-site dashboards for care teams, an incident-report export, tighter re-identification with owner feedback at scale, and Alexa+ voice: "Alexa, where was Dad last seen?"

## Business value
The need is the same whether one family or a thousand residents are involved: know that someone is safe without putting a human in front of a screen.
- **Family caregivers:** the everyday product — ask, get proof, get pinged when a routine breaks.
- **Home-care agencies:** remote check-ins between visits, an evidence trail for incident review, fewer unnecessary welfare visits.
- **Senior-living operators:** the same memory across many cameras and sites — "has anyone been in the east wing after 9 PM?" answered in a sentence.
- **Insurers and claims:** timestamped, clip-backed evidence for aging-in-place programs and incident reports.

Structured event records mean reasoning over rows instead of re-processing video, so answers are fast and cheap. Ingestion is signed and idempotent, safety flags are human-in-the-loop, corrections are owner-controlled, there is no face recognition, and it can be deployed in the customer's own AWS account. (These are use cases we designed for — not customers or pilots.)

## Built with
Ring Partner API (client, signed webhooks, sandbox) · Amazon Bedrock (Nova Pro, Nova Lite, Nova Reel, Titan embeddings) · TypeSafe Jev (Decisions API via OpenRouter) · Model Context Protocol (Alexa+) · Python · FastAPI · SQLite · ffmpeg · Playwright · HyperFrames · ElevenLabs

---

## Track-specific evidence (for reviewers)
- **Ring:** the repository calls Ring technology at runtime — `ring_api.RingClient` (devices, event history, clip and snapshot download), the `/ring/webhook` receiver with HMAC verification, and `pipeline.sync()`. The demo video shows Recall running on the Ring **sandbox** (same endpoints, signed webhooks), labelled on screen. Priority area: **caretaking**.
- **AWS Builder:** Amazon Bedrock — Nova Pro (perception, Converse multi-image), Nova Lite (slot extraction and narration), Titan image and text embeddings (re-identification, retrieval), and Nova Reel 1.1 (generated the older-man footage in the demo's opening, via S3 and the async API; `video/generate_reel.py`). The integrations, what worked and what needs work are documented in [`PRODUCT_FEEDBACK.md`](https://github.com/Garinmckayl/recall/blob/main/PRODUCT_FEEDBACK.md).
- **Open Source:** new project, MIT licensed. Repository: https://github.com/Garinmckayl/recall · GitHub username: **Garinmckayl** · Contribution: a complete, documented memory layer for Ring events — signed-webhook ingestion, a Ring Partner API client and sandbox, person re-identification without faces, routine learning and proactive check-ins, an MCP server, 34 tests, deploy scripts and the demo-video source.
- **Alexa+:** `POST /mcp` — Streamable HTTP, JSON-RPC 2.0, protocol 2025-11-25; tools `ask_home`, `last_seen`, `get_timeline`, `list_people`, `watch_for`. Validated with raw JSON-RPC (no Alexa+ device harness was available — see the friction log).

## Testing instructions
- **Live:** [[LIVE DEMO URL]] — open it, click **Where was Dad last seen?**, then **Is Mom's day normal today?**, then **Demo → Emit Ring event**. No login required. (Rate-limited to protect the demo.)
- **Locally:** `pip install -r requirements.txt`, `cp .env.example .env` (OpenRouter key; AWS credentials with Bedrock access), `python3 -m uvicorn server:app`, `python3 seed.py`. The 34 tests run offline with `python3 -m pytest tests -q`. A 3-minute tour is in the README.

## What was built during the submission period
Everything in the repository was built between Aug 31 and Oct 23, 2026. The project grew from an earlier prototype ("HomeGuard", docs in `docs/v1/`) started in the same period; Recall replaced its analysis pipeline with the memory graph, Ring client and sandbox, re-identification, reasoning operators, routines and check-ins, corrections, the MCP server, deployment scripts and the demo-video source.

## Notes for reviewers
- The video opens and closes with a short **dramatization** (labelled on screen). Everything else is the real product running on the Ring sandbox. The footage is licensed stock (Mixkit Free License) plus **AI-generated clips of an older man made with Amazon Nova Reel** (used for "Dad" in the opening and in the default demo data), labelled on screen and on the end card. No real household footage or personal data is used.
- Statistics in the video carry their sources on screen; the "412 clips this month" counter is captioned illustrative; business examples are tagged as example queries.
