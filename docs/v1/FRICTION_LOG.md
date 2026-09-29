# Friction Log — Jev HomeGuard

Honest friction encountered while building on the hackathon stack. Severity: 🔴 blocker, 🟡 annoying, 🟢 minor.

## TypeSafe Jev (System One decisions — the core of our architecture)

| # | Severity | What happened |
|---|---|---|
| 1 | 🔴→✅ | **`typesafe/jev-latest` was not a valid model ID** on OpenRouter (key valid, catalog 404, no waitlist hint — just `400 invalid model`). **Workaround:** found the OpenRouter × TypeSafe cookbook, which revealed Jev lives on a *different endpoint*: `POST /api/alpha/decisions` with model `typesafe/jev-1.13`. Suggestion: surface a pointer to the Decisions API in the 400 response for Jev slugs. |
| 2 | 🟡 | **The Decisions API is undocumented in the main API docs** (only discoverable via a cookbook recipe). The request schema is lovely — `state` in, typed `choice`/`score` questions out — but `score` questions require `criteria` as an *array of anchors* while `choice` uses a *label map*; the zod 400 doesn't say that. Suggestion: one reference page for `/api/alpha/decisions` with both shapes. |
| 3 | 🟢 | `score` answers return an **anchor index** (e.g. `score: 2` of 3 anchors), not a 0–1 value — we normalize by `score / (anchors-1)`. Documented now, surprising at first. |
| 4 | 🟢 | The model id in responses is a **dated build** (`typesafe/jev-1.13-20260917`) — great for reproducibility, but pinning docs should mention it. |

**Verdict: build with Jev again, immediately.** 70–300ms typed decisions with calibrated probability distributions for ~$0.00002/call changed our architecture: the LLM only perceives and narrates; every branch in our code is a Jev decision.

## Ring (primary track)

| # | Severity | What happened |
|---|---|---|
| 5 | 🟡 | **Neighbors web is a JS shell** (~900 bytes server-rendered) — clip URLs can't be fetched programmatically; the Ring/Neighbors apps allow in-app save/share but there's no public download API for demo footage. **Workaround:** free-licensed Mixkit clips composed into a realistic "Ring day," plus our own `/ring/webhook` simulator accepting Ring-style motion/ding payloads. Suggestion: a first-party "sample footage pack" for hackathoners would remove an hour of workaround per team. |
| 6 | 🟢 | No public sandbox for the Ring simulator — the track rules generously allow simulators, which we built (`/ring/webhook`), but a canonical Ring event-payload sample to code against would help. |

## OpenRouter (transport for Jev + flash models)

| # | Severity | What happened |
|---|---|---|
| 7 | 🟢 | OpenRouter's `typesafe/jev-latest` landing page returns HTTP 200 while the API 404s the slug — spend a few confused minutes before realizing the slug simply wasn't provisioned. |
| 8 | 🟢 | Model aliasing (`~openai/gpt-luna-latest`) is shown in cookbooks but not on the models list page; we hand-pinned flash models instead (`deepseek-v4-flash-vision-exp` for eyes at $0.22/MTok, `z-ai/glm-5.3-flash` for narration at $0.09/MTok). |

## Alexa+ / MCP

| # | Severity | What happened |
|---|---|---|
| 9 | 🟢 | MCP Streamable HTTP (spec 2025-11-25) is straightforward — JSON-RPC over POST; our server implements `initialize` / `tools/list` / `tools/call`. The only gap: no local Alexa+ test harness to point at a tunnel URL from the docs we found; we validated with raw JSON-RPC + MCP inspector-style curls. A "test your MCP server" page in the Alexa console would be the single biggest onboarding win. |

## AWS (Bedrock, AWS Builder mini challenge)

| # | Severity | What happened |
|---|---|---|
| 10 | 🟡 | Bedrock's **Nova message schema** (`schemaVersion`, `messages[].content[].text`) differs from every LLM chat API — fine once wired, but the error messages for a malformed body are terse. Suggestion: an `invoke_model` validator in the console/CLI. |

---
*Every item above was hit in real integration during the hackathon window; workarounds are all in the repo.*
