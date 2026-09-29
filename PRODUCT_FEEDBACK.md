# Product feedback — Recall

Per tool, API and SDK used in this submission: what we used, what worked, what needs work, onboarding, and whether we'd build with it again. A chronological log with severities is in [`FRICTION_LOG.md`](FRICTION_LOG.md).

## Ring Partner API and developer docs — Ring track
**Used:** a client for device discovery, event history, and clip/snapshot download (`ring_api.py`); a webhook receiver that verifies `X-Signature: sha256=` (HMAC-SHA256 over the raw body), de-duplicates on `meta.request_id` and acknowledges immediately (`server.py`); a local sandbox (`ring_sim.py`) that serves the same endpoints and sends signed webhooks. The same client code runs against the sandbox and, with `RING_ACCESS_TOKEN`, the live platform.
**What worked:** JSON:API resources are predictable; the webhook guidance (raw-body HMAC, idempotency key, 200 within 5 s, process asynchronously) is exactly the right shape and easy to implement correctly; event types (`motion_detected`, `button_press`) map cleanly onto a memory model.
**What needs work:** (1) the sandbox is mentioned but no URL, credentials or sample payloads are published, so a team without a device cannot call anything — we built our own; (2) the parts of the API reference we could retrieve were truncated before the Webhook v1.1 payload, the event-history response and the media-download request bodies, so our parsing is tolerant and unvalidated against the live service; (3) the "Ring Appstore MCP server" is a documentation server (`search_docs`, `get_doc`), not a device-data server, which the track brief makes easy to misread; (4) testing webhooks needs a public HTTPS endpoint and the docs do not mention tunnels; (5) it is unclear whether indoor cameras appear in device discovery, which matters for caretaking.
**Onboarding:** early-access credentials, a government-ID check and a physical Ring device are prerequisites for the live API — a real barrier for a hackathon.
**Build with it again?** Yes — events + clips + signed webhooks are the right primitives. What is missing for memory-style products is a supported place to store and query derived per-event intelligence next to the video; every developer will rebuild the event → identity → query stack.

## Amazon Bedrock — Nova Pro and Nova Lite (AWS Builder challenge)
**Used:** Nova Pro (`us.amazon.nova-pro-v1:0`, Converse API, multi-image) turns six keyframes of a clip into one structured event record — actors tracked across frames, appearance, carried objects, actions, interactions, a body box per keyframe and a hedged safety observation (`perceive.py`, `aws.py`). Nova Lite extracts query slots (time phrase, keywords, camera) and narrates answers strictly from a facts JSON (`query.py`). Roughly 20 events are perceived per seed run, each in a single call.
**What worked:** multi-image Converse is exactly the right primitive for "a clip is a short sequence"; the structured output was consistent enough to build a whole pipeline on; latency (a few seconds per six-frame clip) and cost are low enough that every Ring event can be perceived. Nova Lite is fast and follows a "use only these facts" instruction well.
**What needs work:** (1) on-demand use requires **inference profile IDs** (`us.…`), and the error for the bare model ID does not mention profiles; (2) bounding boxes come back on a 0–1000 scale only if the prompt says so — the coordinate system is otherwise unspecified; (3) a reference for the recommended prompt pattern for structured JSON from vision would save every team an hour.
**Onboarding:** smooth once model access and the inference-profile idea are clear; IAM for cross-region profiles needs permissions on both the profile and foundation models in every routable region (`FRICTION_LOG.md` #6, #17).
**Build with it again?** Yes.

## Amazon Titan embeddings — image (`amazon.titan-embed-image-v1`) and text v2 (`amazon.titan-embed-text-v2:0`)
**Used:** person re-identification — Titan image embeddings (384-d) of the body crop from each sighting, and Titan text embeddings (256-d) of the appearance attributes, blended with an attribute-overlap score against stored exemplars (`identity.py`). Titan text embeddings also rank events semantically when keywords do not match.
**What worked:** fast (about 0.3 s per image), simple to call, stable dimensions; on our clip set the same person scored 0.81–0.95 against their earlier sightings and different people 0.33–0.50, so a single threshold separates them.
**What needs work:** the image embedding is a general-purpose vector, not a person re-identification embedding — background and framing leak into it, which is why we blend three signals. The calibration set is small (3 repeated and 8 distinct sightings) and is not a benchmark. A person-re-id-oriented embedding on Bedrock would be a big unlock for camera products.
**Build with it again?** Yes, with a larger calibration set.

## TypeSafe Jev — Decisions API (via OpenRouter)
**Used:** every classification in the system is a typed, calibrated Jev decision: each actor's role and concern, the reasoning operator and subject for a question, the watch-rule type. The role distributions feed a cross-event posterior directly.
**What worked:** typed `choice` and `score` answers with probabilities in about 130 ms and negligible cost; per-user dynamic `criteria` (the household's names) work with no schema change; keeping generative models out of the decision path made the system testable and explainable.
**What needs work:** the Decisions endpoint (`/api/alpha/decisions`, `typesafe/jev-1.13`) is not in the main OpenRouter docs and `typesafe/jev-latest` fails on chat completions with no pointer to it; the 400 for a wrong `criteria` shape does not say which shape is wanted.
**Build with it again?** Yes, immediately.

## Model Context Protocol / Alexa+ integration
**Used:** a Streamable HTTP MCP server (protocol `2025-11-25`) exposing `ask_home`, `last_seen`, `get_timeline`, `list_people` and `watch_for`, with Origin validation, optional bearer token, batching and correct `notifications/*` → 202 and `GET` → 405 behaviour.
**What worked:** the protocol is small and pleasant to implement; tool annotations (`readOnlyHint`) map well onto a memory that is mostly read-only.
**What needs work:** there is no Alexa+ test harness we could point at a tunnel URL, so we validated with raw JSON-RPC rather than a real Alexa+ device. A "test your MCP server" page in the Alexa developer console would be the biggest onboarding win.
**Build with it again?** Yes.

## Tools used to make the demo video (not hackathon technologies)
- **ElevenLabs** (text-to-speech with character timestamps, music, sound effects): excellent and quick; the word timestamps made it possible to align a replacement voice phrase-by-phrase to scenes already timed to another narrator. Sound-effect loudness varies a lot between generations, so a compressed, ducked SFX bus was needed.
- **HyperFrames** (HTML → video): a strong fit for motion graphics plus real screen footage; `check` catches layout and lint problems early. Note that a composition whose timelines never move is reported as "Timeline did not advance", which is confusing for placeholder scenes.
