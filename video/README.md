# Recall — demo-video source

The 3-minute demo video is generated from this folder. Generated media (audio, screen captures, renders, stock B-roll, the project's `assets/`) is git-ignored; everything needed to regenerate it is here.

| File | What it does |
|---|---|
| `PLAN.md` | The script: beat sheet, narration, sources shown on screen |
| `gen_audio.py` | ElevenLabs narration (with word timings), sound effects and the score |
| `align_vo.py` | Re-voice the narration and align it phrase-by-phrase to the timing the scenes were built on |
| `regen_vo.py` | (earlier approach: match whole-clip durations) |
| `capture.py` | Records the **real Recall UI** in headed Chrome on a virtual 4K display (1080p layout at 2× density) — one take per story beat |
| `mix.py` | Mixes narration + score (ducked under the voice) + SFX cues into the soundtrack, normalised to about −14 LUFS |
| `recall-demo/` | The [HyperFrames](https://hyperframes.heygen.com) project: `index.html` (timeline and soundtrack), `compositions/s01…s09` (scenes), `compositions/cues/*.json` (per-scene SFX cues), `STORYBOARD.md` (shared scene spec) |
| `serve_preview.py` | Serves a render with HTTP range support for review |

Regenerate (needs `ELEVENLABS_API_KEY`, ffmpeg, Chrome, Node 22+, and a seeded capture server):
```bash
python3 video/gen_audio.py vo sfx music            # narration, sound effects, score
RECALL_DATA_DIR=data_capture SERVER_URL=http://127.0.0.1:8400 python3 -m uvicorn server:app --port 8400   # then seed it
python3 video/capture.py t_hero                    # …and t_boxes, t_reason, t_routine, t_trust, t_people, t_pipeline
python3 video/mix.py
cd video/recall-demo && npx hyperframes render --quality delivery --output ../renders/recall-demo-final.mp4
```
The video labels its own footage: a short dramatization frames the story, and the product scenes run on the Ring **sandbox** with licensed stock footage.
