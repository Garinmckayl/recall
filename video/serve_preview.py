"""Serve the draft render with HTTP range support (scrubbing works everywhere).  python3 -m uvicorn serve_preview:app --port 8500"""
import pathlib
from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse

R = pathlib.Path(__file__).parent / "renders"
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

@app.get("/final.mp4")
def final():
    return FileResponse(R / "recall-demo-final.mp4", media_type="video/mp4")


@app.get("/draft.mp4")
def draft():
    return FileResponse(R / "draft.mp4", media_type="video/mp4")
