"""Serve the draft render with HTTP range support (scrubbing works everywhere).  python3 -m uvicorn serve_preview:app --port 8500"""
import pathlib
from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse

R = pathlib.Path(__file__).parent / "renders"
REEL = pathlib.Path(__file__).parent / "reel"
app = FastAPI()

PAGE = """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Recall — demo video (final)</title>
<style>body{margin:0;background:#0d1117;color:#e6e6e6;font:16px/1.5 Inter,system-ui,sans-serif}
main{max-width:1180px;margin:0 auto;padding:24px 16px 48px}h1{font-size:22px;margin:0 0 4px}p{color:#9aa4b2;margin:4px 0 16px}
video{width:100%;border-radius:12px;background:#000;box-shadow:0 20px 60px rgba(0,0,0,.5)}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin:16px 0}button{background:#1b2431;color:#e6e6e6;border:1px solid #2a3547;border-radius:999px;padding:8px 14px;cursor:pointer;font:inherit}
button:hover{background:#243044}small{color:#7d8899}</style>
<main><h1>Recall — 3-minute demo video · FINAL</h1>
<p>Final render, 1080p, 2:56. <a style="color:#39b7ee" href="/final.mp4" download="recall-demo.mp4">Download the MP4 (97 MB)</a></p>
<video id=v controls playsinline preload=auto src="/final.mp4"></video>
<div class=chips>
<button data-t=0>Hook 0:00</button><button data-t=14>Why it matters 0:14</button><button data-t=43>Memory 0:43</button><button data-t=64>Hero 1:04</button>
<button data-t=80>Routine 1:20</button><button data-t=95>Trust 1:35</button><button data-t=107>Business 1:47</button><button data-t=132>Stack 2:12</button><button data-t=149>Outro 2:29</button></div>
<small>Sound on. Everything in the product scenes is the real app on the Ring sandbox; the phone story at the start and end is a labelled dramatization.</small></main>
<script>document.querySelectorAll('button').forEach(b=>b.onclick=()=>{v.currentTime=+b.dataset.t;v.play()})</script>"""

@app.get("/", response_class=HTMLResponse)
def index():
    return PAGE

@app.api_route("/final.mp4", methods=["GET", "HEAD"])
def final():
    return FileResponse(R / "recall-demo-final.mp4", media_type="video/mp4")


@app.api_route("/draft.mp4", methods=["GET", "HEAD"])
def draft():
    return FileResponse(R / "draft.mp4", media_type="video/mp4")


REEL_NOTES = {
    "attempt1": "Attempt 1 — asked for dusk + fixed security-camera look + a back garden. Result: same man in all 3 shots (seen from behind), photoreal, but bright midday sun, a cinematic look, and shot 3 is not a backyard.",
    "attempt2": "Attempt 2 — asked for twilight, a static high wide angle and a patio/fence/sliding-door backyard. Result: the man is excellent and consistent (face visible, blue sweater, khakis), but the model gave golden-hour autumn sun instead of dusk, still cinematic with foreground blur, and shot 3 is again a front view.",
    "hookdad": "PROCESSED for the video (this is what would actually be used for Dad): attempt 3, cleanest 4.7 s of each shot, slowed 10%, grayscale, softened with CCTV grain. Driveway / Front Door / Backyard.",
    "attempt4": "Attempt 4 — natural-gait prompt, seed 11 (rear view). Same man in all 3 shots, but Recall does NOT link the three shots as one person (scores 0.66 / 0.68 / 0.74 against the 0.70 threshold).",
    "attempt5": "Attempt 5 — natural-gait prompt, seed 23. Most natural walk (facing camera, face visible) but the clothing changes between shots, so it is not the same man (Recall scores 0.63 / 0.59).",
    "attempt6": "Attempt 6 — natural-gait prompt, side profile. Same dark jacket and trousers in all 3 shots; Recall links all three as one person with margin (0.84 / 0.90 / 0.90). Settings look like a street/lawn rather than driveway/porch/backyard.",
    "hookb": "PROCESSED version of attempt 6 for the video (this is what would be used): cleanest 5.3 s of each shot, slowed 10%, grayscale, light camera grain. Driveway / Front Door / Backyard.",
    "hookc": "PROCESSED from attempt 2 (RECOMMENDED): the walk you liked, trimmed BEFORE the face changes (shot 3 is cut at 4.4 s; the face morphs at ~5.0 s), normal speed, grayscale night-camera look with CCTV softness and grain. Recall links the three shots as one man (0.91 / 0.71 / 0.74; linking works in the order Recall ingests events, but the 0.71 is a thin margin).",
    "hookd": "ALTERNATIVE grade of attempt 2: dim, cool 'dusk' colour grade keeping the blue sweater. Looks moodier and more cinematic than CCTV; Recall links Driveway~Backyard (0.88) and Front~Backyard (0.71) but Driveway~Front is 0.69 (just under 0.70), so one of the three cameras could end up as a separate person.",
    "hookpreview": "HOOK PREVIEW (0:00–0:14, draft quality, with the current soundtrack): the new old-man footage in context — the first Recall screen and the three-camera answer. Full-quality render only after you approve.",
    "attempt3": "Attempt 3 — asks for the look real home cameras have at night: grayscale infrared night vision, grainy CCTV, static, everything in focus. (If this section is empty it is still generating.)",
}

@app.get("/reels", response_class=HTMLResponse)
def reels():
    files = sorted(p.name for p in REEL.glob("*.mp4"))
    groups = {}
    for f in files:
        groups.setdefault(f.split("_")[0], []).append(f)
    html = ["""<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>Recall — generated footage review</title>
<style>body{margin:0;background:#0d1117;color:#e6e6e6;font:16px/1.5 Inter,system-ui,sans-serif}main{max-width:1280px;margin:0 auto;padding:24px 16px 60px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:18px;margin:32px 0 4px}p{color:#9aa4b2;margin:4px 0 12px}.row{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
@media(max-width:900px){.row{grid-template-columns:1fr}}figure{margin:0}video{width:100%;border-radius:10px;background:#000}figcaption{color:#9aa4b2;font-size:14px;margin-top:4px}
.full video{max-width:100%}</style><main><h1>Generated footage for review (Amazon Nova Reel 1.1)</h1>
<p>AI-generated, 1280×720. Nothing here is used in the video until you approve it. Played muted; the files carry no meaningful sound.</p>"""]
    for g, fs in groups.items():
        html.append(f"<h2>{g}</h2><p>{REEL_NOTES.get(g, '')}</p>")
        shots = [f for f in fs if "shot_" in f]; full = [f for f in fs if "output" in f]
        html.append('<div class=row>' + "".join(f'<figure><video controls loop muted playsinline preload=metadata src="/reel/{f}"></video><figcaption>{f.replace("_"," ").replace(".mp4","")}</figcaption></figure>' for f in shots) + "</div>")
        if full:
            html.append(f'<h3 style="font-size:15px;margin:18px 0 6px">Full 18 s sequence</h3><div class=full><video controls loop muted playsinline preload=metadata src="/reel/{full[0]}"></video></div>')
    html.append("</main>")
    return "".join(html)

@app.api_route("/reel/{name}", methods=["GET", "HEAD"])
def reel_file(name: str):
    p = REEL / pathlib.Path(name).name
    if p.suffix != ".mp4" or not p.exists():
        from fastapi import HTTPException
        raise HTTPException(404)
    return FileResponse(p, media_type="video/mp4")
