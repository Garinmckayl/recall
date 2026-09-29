# Recall — 3-minute demo video v2: the caregiver cut (for approval)

**Positioning (use verbatim, on screen and in the submission):**
> Not security AI. Not video search. Not facial recognition.
> **Persistent visual memory for caretaking and safety.**

Why this rewrite: Ring lists *caretaking* as a priority category, and every judge has a parent. "Which guy is the delivery guy?" shows a feature; "Dad isn't answering his phone" shows a reason. The hook is now the fear a family member feels, resolved by the most impressive thing the product does — reconstructing where someone went across three cameras, in two seconds.

Target **2:56**, 1920×1080 (mastered from 4K screen captures so zooms stay sharp), 30 fps. Voice: **Adam** (narrator), **Bill** (old, warm) for Dad's one line. Score, SFX: ElevenLabs. Motion graphics: HyperFrames. Screen footage: the real product on the Ring sandbox.

## Beat sheet

### ACT 1 — HOOK · 0:00–0:13 (the gut punch, then the payoff)
| t | Picture | Voice-over / sound |
|---|---|---|
| 0:00 | Black. A phone buzzes on a table (sound only). Tiny corner tag: *Dramatization*. | **phone vibrate**, low drone |
| 0:01 | Lock-screen close-up: **"Dad — Missed call"** stacking: ×2 … ×3 … ×4. Time reads **8:20 PM**. Desaturated stock B-roll cuts in for one beat each: an older man alone at a window; an empty chair. | VO, low and slow: *"It's eight-twenty. Your father is eighty-one. He lives alone. He's not answering."* — heartbeat begins on "alone" |
| 0:07 | Cut to Recall, full frame. The son types — fast, shaky: **"Where was Dad last seen?"** Enter. | keys, one riser |
| 0:09 | **Answer lands in 2 seconds** with a bass hit: *"Dad was last seen at 8:13 PM in the Backyard."* Camera punches in 2.2× as the **path lights up: Driveway → Front Door → Backyard**, a box locking onto him in each clip, ending on a dashed line: **"No later detections."** | VO: *"Three cameras. One answer."* — heartbeat stops |
| 0:13 | Slam to black. **RECALL** — *"Persistent visual memory for caretaking and safety."* | hit, one beat of silence |

> The "eighty-one / lives alone" line is the dramatization; the footage, answer, times and path on screen are the real product output on sample footage.

### ACT 2 — WHY IT MATTERS · 0:13–0:40
| t | Picture | Voice-over / sound |
|---|---|---|
| 0:13 | Three stat cards slam in, each with its source in small type: **75%** of adults 50+ want to stay in their own home *(AARP, 2024)* · **1 in 4** older adults falls every year — over 14 million *(CDC)* · **30%** of over-90s who fall lie on the floor for an hour or more *(BMJ cohort study)* | *"Three out of four older adults want to stay in their own homes. One in four falls every year. And when it happens, minutes matter."* |
| 0:24 | Camera wall: dozens of Ring-style tiles scrolling; alerts stacking ("Motion detected"). Then Ring's help page, two lines highlighted: **"Specific people or characteristics"** · **"Searches phrased as questions"**. | *"The cameras are already there. They saw everything. But when it matters, you're left scrubbing clips, hoping. Even Ring's own help page says video search can come back empty for specific people, and for searches phrased as questions."* |
| 0:37 | Cut to black. One line: **"A camera shows you a video. A caregiver needs an answer."** | silence → riser |

### ACT 3 — THE SOLUTION, IN DETAIL · 0:40–1:58
| t | Picture | Voice-over / sound |
|---|---|---|
| 0:40 | The four negations strike through one by one — *not security AI · not video search · not facial recognition* — leaving **"visual memory."** Then the pipeline draws itself over a live feed of events: **Ring signed webhook ✔ → Amazon Nova sees → decision model classifies → Titan recognizes the same person → memory graph**. Real UI: an event arrives, "Processing…", person nodes merge. | *"Recall isn't security AI. It isn't video search. It isn't facial recognition. It's memory. Every Ring event becomes knowledge: who was there, what they did, where they went. Amazon Nova watches. Titan recognizes the same person across cameras, and across days."* |
| 0:57 | **Hero deep dive.** Re-run "Where was Dad last seen?" slowly. Top-down **home map** (illustrative layout) with four camera icons; Dad's path draws itself Driveway → Front Door → Backyard with timestamps; cut to each clip with the tracking box; reasoning steps tick; "no later detections" terminator. | *"Not three matching videos — one reconstructed answer. Driveway. Front door. Back door. And then nothing. Every step is one click from proof: the exact clip, the exact second, the exact person."* |
| 1:20 | **"Recall doesn't wait to be asked."** Phone mock-up slides in with the real alert text: *"Check-in: Mom usually appears around 7:30 AM (6 of the last 6 days). Nothing yet today."* Cut to the Today card, amber clock pulsing → click **Ask about this** → *"Mom was last seen yesterday at 7:30 AM at the Front Door."* | *"And Recall doesn't wait to be asked. Mom is up by seven-thirty, six mornings out of six. This morning she isn't. Recall notices what didn't happen, and tells you first."* |
| 1:42 | Trust montage (~14 s): a wrong match → **"Not them?"** → merge/split animation → *"Recall will recognise them next time."* Then the night-visitor flag: **"Suspicious behavior — unverified. The clip is the ground truth."** A slow caption: *No face templates. No face recognition.* | *"You stay in control. Correct a mistake and Recall learns. Anything risky is flagged as unverified, and the clip is always the ground truth."* |

### ACT 4 — BUSINESS & ENTERPRISE · 1:58–2:30
| t | Picture | Voice-over / sound |
|---|---|---|
| 1:58 | Zoom out from one house to a **map of many**: a grid of homes/sites, each with a tiny status ring (green/amber). Four cards flip: **Family caregivers** · **Home-care agencies** · **Senior-living operators** · **Insurers & claims** — each with one real query ("Has anyone been in the east wing after 9 PM?"). | *"This is bigger than one family. Three-quarters of older adults want to age at home. Home-care agencies, senior-living operators and insurers all need the same thing: to know someone is safe without a human watching a screen. Recall turns cameras that are already installed into a system of record — with proof in every answer."* |
| 2:16 | Architecture strip + enterprise ticks: **Ring Partner API · Amazon Bedrock (Nova + Titan) · MCP for Alexa+** · signed & idempotent webhooks · rate-limited · human-in-the-loop safety flags · owner corrections · deployable in your own AWS account · open source (MIT) | *"Built on Amazon Bedrock and Ring's APIs. Signed, idempotent webhooks. Human-in-the-loop safety. An MCP server, so Alexa+ and any agent can ask your home a question. Open source, and deployable in your own AWS account."* |

### ACT 5 — OUTRO · 2:30–2:56 (a callback, not a slogan)
| t | Picture | Voice-over / sound |
|---|---|---|
| 2:30 | Back to the son's phone, same table, same 8:20 PM light. He reads the answer, stands, walks toward the back of the house *(B-roll: a hand pushing open a door; hold on the light spilling out)*. | score drops to a single warm note |
| 2:37 | Phone rings. **"Dad — calling."** He picks up. Dad (Bill): *"Hey, son. Sorry — I was out back."* | **Bill's line**, room tone |
| 2:43 | Cut to black. Big type, one line at a time: **Don't scrub.** … **Ask.** | VO: *"Next time someone you love goes quiet… don't scrub. Ask."* — final chord swells |
| 2:49 | **RECALL** — *Persistent visual memory for caretaking and safety.* Footer: github.com/Garinmckayl/recall · *Ring · AWS Builder · Open Source · Alexa+ MCP* · *Dramatization · Ring sandbox · licensed stock footage* | last hit, tail fade |

## Voice-over (clean read, ~400 words)
> It's eight-twenty. Your father is eighty-one. He lives alone. He's not answering.
> *Where was Dad last seen?* — Three cameras. One answer.
>
> Three out of four older adults want to stay in their own homes. One in four falls every year. And when it happens, minutes matter. The cameras are already there. They saw everything. But when it matters, you're left scrubbing clips, hoping. Even Ring's own help page says video search can come back empty for specific people, and for searches phrased as questions.
>
> Recall isn't security AI. It isn't video search. It isn't facial recognition. It's memory. Every Ring event becomes knowledge: who was there, what they did, where they went. Amazon Nova watches. Titan recognizes the same person across cameras, and across days.
>
> Not three matching videos — one reconstructed answer. Driveway. Front door. Back door. And then nothing. Every step is one click from proof: the exact clip, the exact second, the exact person.
>
> And Recall doesn't wait to be asked. Mom is up by seven-thirty, six mornings out of six. This morning she isn't. Recall notices what didn't happen, and tells you first.
>
> You stay in control. Correct a mistake and Recall learns. Anything risky is flagged as unverified, and the clip is always the ground truth.
>
> This is bigger than one family. Three-quarters of older adults want to age at home. Home-care agencies, senior-living operators and insurers all need the same thing: to know someone is safe without a human watching a screen. Recall turns cameras that are already installed into a system of record, with proof in every answer. Built on Amazon Bedrock and Ring's APIs. Signed, idempotent webhooks. Human-in-the-loop safety. An MCP server, so Alexa+ and any agent can ask your home a question. Open source, and deployable in your own AWS account.
>
> Next time someone you love goes quiet… don't scrub. Ask.

## Sources shown on screen (all verified)
- AARP 2024 Home & Community Preferences: 75% of adults 50+ want to remain in their current homes — aarp.org/home-living/home-community-preferences-survey-2024
- CDC, *Facts About Older Adult Falls*: over 14 million (1 in 4) older adults report falling every year; falls are the leading cause of injury death for 65+ — cdc.gov/falls/data-research/facts-stats
- Prospective cohort of people over 90: 30% of those who fell lay on the floor for an hour or more, strongly associated with serious injury, hospital admission and long-term care — BMJ 2008 (PMC2590903)
- Ring, *Getting started with Video Search*: lists "Specific people or characteristics" and "Searches phrased as questions" as searches that may not return results — ring.com/support/articles/4l5lb/smart-video-search

## Production notes
- **Screen footage** is recorded from the real UI (isolated capture database): the hero question, the path lanes, boxes tracking Dad across three clips, the reasoning steps, the proactive check-in, corrections. Nothing on screen is mocked except the phone frames, which show the *real* alert text, and the home-map graphic, which is labelled illustrative.
- **B-roll** (older man at a window, empty chair, door) is licensed stock, used only in dramatized cutaways.
- **Score** (ElevenLabs Music): heartbeat pulse → held tension under the problem → warm, rising build under the solution → confident peak in the business section → a single warm note for the callback → resolving chord. 
- **SFX**: phone vibrate/ring, heartbeat, typing, riser, bass hits, box lock-on, lane energise, notification, card flips, ticks, room tone.
- **Honest guardrails**: "Dramatization" and "Ring sandbox · licensed stock footage" are on screen; statistics carry sources; no customer claims; no facial-recognition claims.

## Decisions for you
1. **Outro callback** ("Sorry — I was out back"): warm and human, and it reuses the back-door answer. It's a dramatization, labelled. Keep, or end on the slogan alone?
2. **"Eighty-one, lives alone"** is the fictional setup line. OK, or make it less specific ("Your father lives alone")?
3. **Business framing**: four segments (family, home-care agencies, senior-living operators, insurers). Any you'd cut or add?
