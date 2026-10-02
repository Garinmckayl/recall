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
| 16 | 🟡 | An existing EC2 instance has **no Bedrock access until an instance profile is attached** — there is no one-click "let this instance call Bedrock". Deploying meant creating a role, an instance profile and associating it (`deploy/aws_setup.py` does it idempotently). |
| 17 | 🟢 | The `us.` cross-region inference profiles need `bedrock:InvokeModel` on the *inference profile* **and** on foundation models in every region the profile can route to (`arn:aws:bedrock:*::foundation-model/*`); a region-scoped policy fails at call time, not at policy creation. |
| 18 | 🟡 | **Nova Reel ignores lighting and camera instructions.** "Dusk" / "twilight" produced golden-hour sun; "static security camera, everything in focus" still came out cinematic with blurred foreground. What worked: asking for *grayscale infrared night-vision CCTV* (a look the model knows), then grading the footage ourselves. |
| 19 | 🟡 | **Generated people drift.** A man walking toward the camera changed face about five seconds into a shot; gait often looks off; outfit consistency across multi-shot sequences depends on the seed. We tested every candidate through Recall's own re-identification before choosing one (scores 0.63–0.92 across attempts) and trimmed before the drift. |
| 20 | 🟢 | `StartAsyncInvoke` with an S3 *prefix* fails with "does not point to a bucket or a directory"; the bucket root works (Nova Reel then creates its own job folder). |
| 21 | 🟡 | **Credits vs third-party Bedrock models.** On our account promotional credits fully offset Amazon-built services (EC2, Nova, AgentCore…) but applied to none of the third-party models on Bedrock (Claude; Luma Ray 2 would be the same), which are separate "(Amazon Bedrock Edition)" line items. We kept the video generation on Amazon Nova Reel for that reason. |

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
