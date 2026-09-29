# Recall — 3-minute demo · shared scene spec (all scene builders read this first)

Canvas **1920×1080 @ 30 fps**, total **176 s**. Positioning line (verbatim wherever used):
**Persistent visual memory for caretaking and safety.** Never call it security AI / video search / facial recognition except in the "Not …" negation beat.
Full narrative: `../PLAN.md`. Narration timings: `vo_meta.json` (word-level, seconds within each clip) + `vo_timeline.json` (absolute start/end of each clip on the final timeline).

## Timeline (absolute seconds) — each scene is one sub-composition file
| id (= file = composition-id) | window | narration inside it |
|---|---|---|
| `s01-hook` | 0.0–14.4 | v01_hook 1.00–6.85 · v02_answer 10.20–12.15 |
| `s02-problem` | 14.4–43.0 | v03_stats 14.50–23.74 · v04_problem 24.50–39.27 |
| `s03-memory` | 43.0–64.0 | v05_memory 43.00–63.16 |
| `s04-hero` | 64.0–80.0 | v06_hero 64.50–78.99 |
| `s05-routine` | 80.0–94.5 | v07_routine 81.00–93.31 |
| `s06-trust` | 94.5–106.5 | v08_trust 95.00–105.08 |
| `s07-business` | 106.5–131.5 | v09_biz 107.00–130.87 |
| `s08-stack` | 131.5–149.0 | v10_stack 132.00–147.84 |
| `s09-outro` | 149.0–176.0 | v12_dad 154.00–156.69 · v11_outro 158.00–162.18 |

Inside a scene use **scene-local time** (0 = the scene's first frame): local = absolute − window start. Word times: absolute = clip start (`vo_timeline.json`) + word `s`/`e` (`vo_meta.json`). Sync key words on screen to the spoken words to within ~0.1 s. The narration is already in the soundtrack — **do not add `<audio>` in scenes**.

## Design system
- Ink `#0d1117` · paper `#f6f5f1` · card `#ffffff` · hairline `#e4e1d8` · accent blue `#0f7fb8` (on light) / `#39b7ee` (on dark) · warm amber `#f0a81a` (caution, routine) · red `#e5484d` ONLY for security/unverified flags · green `#1f9d6b` (confidence, checks).
- Type: **Sora** 800 for headlines/numerals (tight, `letter-spacing:-0.02em`), **Inter** 400–800 for everything else. Fonts are shipped: put this inside your template `<style>` (URLs are relative to `index.html`):
  ```css
  @font-face{font-family:"Inter";src:url("assets/fonts/Inter-400.woff2") format("woff2");font-weight:100 900;font-display:block}
  @font-face{font-family:"Sora";src:url("assets/fonts/Sora-800.woff2") format("woff2");font-weight:100 900;font-display:block}
  ```
- Mood by act: hook + problem = dark cinematic (`#05070b`, vignette, faint film grain via a CSS noise/gradient layer — no video needed); solution = the light "Recall world" (paper background, white cards, soft shadow `0 20px 60px rgba(13,17,23,.18)`, 14 px radii); business = deep navy `#0a1626` → paper; outro = warm dark `#0e0b09`.
- Motion: confident and snappy. Entrances 0.4–0.7 s, `power3.out`/`expo.out`; hits (title slams) 0.25 s with a tiny overshoot and a 2–3 px shake settle; numbers count up; lines draw with stroke-dashoffset. Everything on ONE paused GSAP timeline, seek-safe, no `repeat:-1`, no `Math.random()` without a seed, no timers. Hold readable text ≥ 1.2 s.
- Legibility: on-screen text ≥ 34 px except tiny source citations (≥ 22 px). High contrast. **Keep the bottom 60 px of the left 60% of the frame clear** (a global disclosure line is overlaid there by the root).
- Do not use Ring logos/marks or copy Ring's UI. Quotes from Ring's help page are plain text cards with a source line.

## Screen footage (real product, captured at 3840×2160, 1920×1080 CSS layout at 2× density)
Files in `assets/cap/`: `t_hero.mp4` (17.6 s: the question is typed, the answer lands, path across 3 cameras, clips play with tracking boxes) · `t_reason.mp4` (14.1 s: reasoning steps, "How I got this", video) · `t_routine.mp4` (11.9 s: overdue check-in toast lands, "Ask about this" answer) · `t_trust.mp4` (9.9 s: Dad's event, "Not them?" popover, night-visitor flag) · `t_people.mp4` (8.0 s: People tab scrolling) · `t_pipeline.mp4` (14.2 s: Demo drawer → emit a Ring event → "Processing Front Door event").
UI geometry in 1920×1080 CSS px: left panel x 0–330 (Needs-attention card ≈ x 15–315, y 240–740; event cards below), chat x 355–1520 (answer cards start ≈ y 180), right evidence panel x 1533–1905 (video pane top ≈ y 118–330; reasoning/path below it). **Measure key moments yourself** with `ffmpeg -ss T -i assets/cap/X.mp4 -frames:v 1 -vf scale=960:-1 out.png` contact sheets (the recordings start ~1.3 s before typing/interaction).
Show footage as full-bleed or as a floating "app window" card (white 14 px-radius card, soft shadow). For **zoom/punch-in** never scale the `<video>` clip element itself: put the `<video>` (sized 1920×1080, `object-fit:cover`) inside a wrapper `div` (`overflow:hidden`) and animate an inner wrapper's `scale` + `x`/`y` (`transformOrigin:"0 0"`, compute x,y = −focus·scale). Source is 2× density so ≤ 3× zoom stays sharp. Use `data-media-start` to choose the source moment and (optionally) `data-playback-rate` 1–1.25 to tighten waits. Video must be `muted playsinline`, timed via `data-start`/`data-duration` with `class="clip"`, unique ids (prefix with your scene id), and NO ancestor that also has `data-start` (lint `video_nested_in_timed_element`) — put timing on the video itself and animate the wrappers only.
Other assets: `assets/broll/` (49020 older man at a window · 33681 woman in a wheelchair at a window · 12866 man rising from a chair in pain · 48790 hands on a cane · 17217 older man walking a beach · 12533 older man with a cane on a field path; all 1080p, no audio, licensed stock — dramatization cutaways only; grade them: desaturate/cool for the hook, warm for the outro) · `assets/thumbs/*.jpg` (event + person thumbnails from the real product) · `assets/people/` (empty).

## The data on screen (must match the real UI — do not invent alternatives)
Question: **"Where was Dad last seen?"** Answer: *Dad was last seen today at 8:13 PM in the Backyard, approaching the door and hugging someone.* Confidence 88%. Path: **Driveway 8:03 PM → Front Door 8:08 PM → Backyard 8:13 PM**, then "No subsequent detections". 20 events, 18 people. Routine: *Mom usually appears around 7:30 AM (6 of the last 6 days). Nothing yet today.* Push text: *Check-in: Mom usually appears around 7:30 AM (6 of the last 6 days). Nothing yet today.* Night visitor flag: *Suspicious behavior — Front Door, 12:40 AM* (unverified). Phone in the hook: contact **"Dad"**, "Missed call", clock **8:20**.

## SFX cues (you write them; the mixer places them)
Write `compositions/cues/<scene-id>.json` — an array of `{"t": <ABSOLUTE seconds>, "sfx": "<name>", "gain": 0.0–1.2, "dur": <optional trim seconds>, "fade": <optional tail fade>}` aligned to your visual hits (title slams, card lands, clicks, lock-ons, alerts). Available `sfx` names (files in `../audio/sfx/`): `phone_vibrate` 3s · `heartbeat` 6s · `typing` 3s · `riser` 3s · `bass_hit` 3s · `box_lock` 1s · `notify` 1.5s · `ping_stack` 3s · `needle_stop` 1.5s · `tape_scrub` 2.5s · `data_stream` 3.5s · `node_pop` 0.8s · `whoosh` 1.2s · `tick` 0.6s · `card_flip` 0.9s · `phone_ring` 4s · `room_tone` 8s · `door_open` 3s · `sting_low` 2.5s · `clock_tick` 3s · `lane_sweep` 1.5s · `swoosh_in` 0.8s. Be tasteful: hits on the big beats, ticks/pops on small ones; don't stack SFX on the loudest narration words unless it is a title hit. Score is already in the mix (heartbeat/pulse → tension 13–40 s → build from 40 s → peak 118–148 s → hush 150 s → final chord ~168 s).

## Conventions & verification (every scene builder)
- You write ONLY `compositions/<your-scene>.html` (+ `compositions/cues/<scene>.json`). Never edit `index.html`, other scenes, assets, or the project config. If you need a derived asset (e.g., a cropped PNG/thumbnail), create it under `assets/<your-scene>/`.
- File shape: `<template>` containing `<style>` (root styled by `#root` only), `<div id="root" data-composition-id="<scene-id>" data-width="1920" data-height="1080">…`, and the `<script>` registering `window.__timelines["<scene-id>"]` (one paused timeline; `data-composition-id` = filename = host id). Root fill: put full-bleed backgrounds on a child layer, not on `#root`. Unique element ids prefixed `<scene-id>-`.
- Your scene renders as a slot at its window: the scene's local time 0 = its window start. Test with `npx hyperframes check` and `npx hyperframes snapshot --at <ABSOLUTE times inside your window>` from the project directory (`/home/ubuntu/amazonhackhaton/video/recall-demo`), view the PNGs, fix layout/overlap/legibility. `check` must report 0 findings for your scene (other scenes are stubs — ignore their content). Other builders work in parallel in the same project; only touch your files.
- Don't render MP4s. Report back in ≤ 6 lines: what the scene shows beat by beat, cues written, anything you need changed in the audio/timing.

## Per-scene direction
(See each scene's brief in the dispatch message; the beat sheet in `../PLAN.md` is the source of truth for copy.)
