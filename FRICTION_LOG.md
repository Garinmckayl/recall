# Friction Log — Recall

Honest friction from building on the hackathon stack. 🔴 blocker · 🟡 annoying · 🟢 minor.

## Ring (primary track)

| # | Sev | What happened | Suggestion |
|---|---|---|---|
| 1 | 🔴→✅ | Real Ring API access needs Early Access credentials, a government-ID check, and at least one physical Ring device. A hackathon team with none of those can't call `api.amazonvision.com`. The docs mention a sandbox with synthetic devices/events but describe no URL, credentials or payloads. **Workaround:** `ring_sim.py`, a local sandbox serving the same endpoints (`/v1/devices`, `/v1/history/devices/{id}/events`, media download) with JSON:API shapes and HMAC-signed webhooks; the client code path is identical for live and sandbox. | Publish the sandbox base URL + a hackathon token + sample event payloads. This is the single biggest onboarding win for a no-device track. |
| 2 | 🟡 | The API reference page I could retrieve was truncated before the **Webhook v1.1 payload**, **Event History** response and **media download request body** sections (I got the endpoint paths, `X-Signature: sha256=<hex>`, event types and `meta.request_id` idempotency). `ring_api.parse_event` is therefore tolerant and the download bodies are best-effort (`components`, `event_id`, `start_time`, `end_time`). Not validated against the live service. | Ship the payload examples inline (or as an OpenAPI file) rather than in collapsible sections. |
| 3 | 🟡 | The "Ring MCP Server" is a **documentation knowledge server** (`search_docs`, `get_doc`), not a device-data server. Reading the track brief, I expected it to expose events/video. Worth stating up front. | Name it "Ring docs MCP" or add device tools. |
| 4 | 🟡 | Webhooks require a public HTTPS endpoint. Local development needs a tunnel, which the docs don't mention. | A "test webhook" button in the console that replays a sample event to any URL. |
| 5 | 🟢 | No public sample footage. Stock clips + your own filming are the only options; `demo_clips/README.md` has our shot list. | A small sample-clip pack. |

## AWS (AWS Builder mini challenge)

| # | Sev | What happened |
|---|---|---|
| 6 | 🟡 | Nova models require **inference profile IDs** (`us.amazon.nova-pro-v1:0`), not the bare model id, for on-demand Converse. The plain id returns a validation error that doesn't mention profiles. `ListInferenceProfiles` shows them. |
| 7 | 🟢 | Nova Pro returns bounding boxes on a **0–1000 scale** but only if the prompt asks for that scale; otherwise the coordinate system is unspecified. |
| 8 | 🟡 | **Titan Multimodal image embeddings are generic**, not person re-id. Same-clothing crops score high, but background and framing leak into the vector, so we blend it with a text embedding of appearance attributes and a token-overlap score (`identity.blended`). On our small set: same person across events scored 0.81–0.95, different people 0.33–0.50; `REID_MATCH=0.70`. That is 3 repeated + 8 distinct sightings — not a benchmark. |
| 9 | 🟢 | Bedrock `Converse` with several `image` blocks works well for keyframe sequences (6 frames, ~1 s). Latency to a full structured record is dominated by the model call, not the frames. |
| 10 | 🟢 | Region came from `AWS_REGION` in the environment (us-west-2 here); the code defaults to it via `config.AWS_REGION`, so inference profiles must exist there. |

## TypeSafe Jev (System One decisions)

| # | Sev | What happened |
|---|---|---|
| 11 | 🟡 | The **Decisions API** (`POST /api/alpha/decisions`, model `typesafe/jev-1.13`) is not in the main OpenRouter docs; found via a cookbook. `typesafe/jev-latest` 404s on chat completions with no pointer to the Decisions endpoint. |
| 12 | 🟡 | `score` questions need `criteria` as an **array of anchors**; `choice` needs a label map. The 400 doesn't say which. |
| 13 | 🟢 | `score` answers are anchor indices, not 0–1; we normalise. |
| 14 | 🟢 | Dynamic `criteria` (our subject question lists the household's enrolled names) works without any schema change — a nice property for per-user vocabularies. |

**Verdict on Jev:** every branch in the system that is a *classification* (role, concern, operator, subject, rule kind) is a Jev decision with a calibrated distribution; those distributions feed the cross-event role posterior directly. The LLMs only observe and narrate.

## Alexa+ / MCP

| # | Sev | What happened |
|---|---|---|
| 15 | 🟡 | No local Alexa+ harness to point at a tunnel URL; we validated the Streamable HTTP endpoint (2025-11-25) with raw JSON-RPC, including `notifications/*` → 202, `GET` → 405, Origin rejection, batch requests. |

## Product feedback we'd give Amazon
Ring's platform is the right primitive layer (events + clips + webhooks). What's missing for *memory* products is a supported way to store and query derived per-event intelligence next to the video — every developer will rebuild the event → identity → query stack in this repo.
