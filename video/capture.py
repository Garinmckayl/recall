"""Record the real Recall UI in a headed Chrome on a virtual 4K display (1080p layout at 2x density).

    python3 video/capture.py probe        # 12 s smoke take
Each take = a function below; output: video/capture/<name>.mp4 (H.264, 30 fps, 3840x2160).
"""
import asyncio, os, signal, subprocess, sys, time, pathlib
from playwright.async_api import async_playwright

BASE = os.getenv("RECALL_URL", "http://127.0.0.1:8400")
OUT = pathlib.Path(__file__).parent / "capture"; OUT.mkdir(exist_ok=True)
W, H, DSF, DISPLAY = 1920, 1080, 2, ":77"


class Screen:
    def __enter__(self):
        self.x = subprocess.Popen(["Xvfb", DISPLAY, "-screen", "0", f"{W*DSF}x{H*DSF}x24", "-nolisten", "tcp"],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1.5); os.environ["DISPLAY"] = DISPLAY
        return self

    def __exit__(self, *a):
        self.x.terminate()


def start_ffmpeg(name):
    path = OUT / f"{name}.mp4"
    p = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "warning", "-stats", "-f", "x11grab", "-framerate", "30", "-draw_mouse", "0",
                          "-video_size", f"{W*DSF}x{H*DSF}", "-i", DISPLAY, "-c:v", "libx264", "-preset", "ultrafast", "-crf", "14",
                          "-pix_fmt", "yuv420p", str(path)], stdin=subprocess.PIPE, stderr=open(OUT / f"{name}.ffmpeg.log", "wb"))
    return p, path


def stop_ffmpeg(p):
    p.stdin.write(b"q"); p.stdin.flush(); p.wait(timeout=60)


async def browser(pw):
    """Borderless Chrome (app + kiosk) so the recording is just the product, no tabs or address bar."""
    import tempfile
    ctx = await pw.chromium.launch_persistent_context(
        tempfile.mkdtemp(prefix="recall-cap-"), channel="chrome", headless=False, no_viewport=True, ignore_default_args=["--enable-automation"],
        args=[f"--app={BASE}/", "--kiosk", f"--window-size={W},{H}", "--window-position=0,0",
              f"--force-device-scale-factor={DSF}", "--autoplay-policy=no-user-gesture-required",
              "--hide-scrollbars", "--no-first-run", "--disable-infobars", "--disable-session-crashed-bubble"])
    pg = ctx.pages[0] if ctx.pages else await ctx.wait_for_event("page")
    return ctx, pg


async def ask(pg, q, wait=6000, type_delay=45):
    box = pg.get_by_placeholder("Ask about people, deliveries, or where someone was last seen…")
    await box.click(); await box.type(q, delay=type_delay); await pg.keyboard.press("Enter")
    await pg.wait_for_timeout(wait)


async def _ready(pg):
    await pg.wait_for_selector("#evList >> text=/./", timeout=15000)
    await pg.wait_for_timeout(800)


async def _smooth(pg, sel, block="center"):
    await pg.evaluate(f"document.querySelector('{sel}').scrollIntoView({{behavior:'smooth',block:'{block}'}})")


async def _chip(pg, cam):
    return pg.locator(f"#log button:has-text('{cam}')").first


async def t_hero(pg):
    """The hook + hero: the question, the answer, the path across three cameras, a box on Dad in each clip."""
    await _ready(pg)
    await ask(pg, "Where was Dad last seen?", wait=3800, type_delay=55)
    await _smooth(pg, "#path"); await pg.wait_for_timeout(3200)
    for cam in ("Front Door", "Driveway", "Backyard"):
        c = await _chip(pg, cam)
        if await c.count():
            await c.click(); await pg.wait_for_timeout(2300)
    await pg.wait_for_timeout(600)


async def t_boxes(pg):
    """Evidence you can see: for each camera in the path, the clip plays with a box tracking Dad (video pane held in view)."""
    await _ready(pg)
    await ask(pg, "Where was Dad last seen?", wait=3200, type_delay=35)
    for cam in ("Driveway", "Front Door", "Backyard"):
        c = await _chip(pg, cam)
        if await c.count():
            await c.click()
            await pg.evaluate("document.querySelector('#vid').scrollIntoView({behavior:'instant',block:'center'})")
            await pg.wait_for_timeout(3600)


async def t_hero_old(pg):
    """Same beat as t_hero, recorded against the old-man hook database (RECALL_URL=http://127.0.0.1:8401)."""
    await t_hero(pg)


async def t_boxes_old(pg):
    await t_boxes(pg)


async def t_reason(pg):
    """How the answer was reached: reasoning steps, confidence, citations, the video with the tracking box."""
    await _ready(pg)
    await ask(pg, "Where was Dad last seen?", wait=3200, type_delay=35)
    how = pg.locator("#log >> text=How I got this").first
    if await how.count():
        await how.click(); await pg.wait_for_timeout(1500)
    await _smooth(pg, "#reasoning", "start"); await pg.wait_for_timeout(3500)
    await _smooth(pg, "#vid", "center"); await pg.wait_for_timeout(3500)


async def t_routine(pg):
    """Recall doesn't wait to be asked: the overdue check-in fires and lands as a live alert."""
    import httpx
    await _ready(pg)
    await pg.wait_for_timeout(1800)
    httpx.post(BASE + "/api/demo/checkin", json={"force": True}, timeout=30)
    await pg.wait_for_timeout(3800)
    link = pg.locator("text=Ask about this").first
    if await link.count():
        await link.click(); await pg.wait_for_timeout(4500)


async def t_trust(pg):
    """Owner control: 'Not them?' correction popover, People tab, and the unverified night-visitor flag."""
    await _ready(pg)
    card = pg.locator("#evList >> text=Dad").first
    if await card.count():
        await card.click(); await pg.wait_for_timeout(1500)
    nt = pg.locator("text=Not them?").first
    if await nt.count():
        await nt.click(); await pg.wait_for_timeout(2600); await pg.keyboard.press("Escape"); await pg.wait_for_timeout(600)
    await pg.locator("text=Suspicious behavior").first.click(timeout=4000)
    await pg.wait_for_timeout(3600)


async def t_people(pg):
    """Persistent memory: the people the home has learned, each linked across cameras and days."""
    await _ready(pg)
    await pg.locator("#pane-timeline").evaluate("e=>e")  # no-op, ensures DOM ready
    await pg.get_by_role("tab", name="People").click() if await pg.get_by_role("tab", name="People").count() else await pg.locator("text=People").first.click()
    await pg.wait_for_timeout(1500)
    await pg.evaluate("(()=>{const e=document.querySelector('#pane-people');e.scrollTo({top:e.scrollHeight,behavior:'smooth'})})()")
    await pg.wait_for_timeout(5000)


async def t_pipeline(pg):
    """A Ring event arrives through the signed webhook and is ingested live (adds one courier event: run last)."""
    await _ready(pg)
    await pg.locator("#demoBtn").click(); await pg.wait_for_timeout(1400)
    await pg.select_option("#emCam", label="Front Door") if await pg.locator("#emCam").count() else None
    await pg.select_option("#emKind", "doorbell") if await pg.locator("#emKind").count() else None
    await pg.select_option("#emClip", "31155.mp4") if await pg.locator("#emClip").count() else None
    await pg.wait_for_timeout(1000)
    await pg.locator("#emitForm button[type=submit], #emitForm button").first.click(); await pg.wait_for_timeout(1200)
    await pg.locator("#demoClose").click(); await pg.wait_for_timeout(9000)


async def main(name):
    with Screen():
        async with async_playwright() as pw:
            b, pg = await browser(pw)   # b is a context here
            await pg.goto(BASE + "/"); await pg.wait_for_timeout(1200)
            ff, path = start_ffmpeg(name); await asyncio.sleep(0.5)
            try:
                await globals()[name](pg)
            finally:
                stop_ffmpeg(ff); await b.close()
    print("wrote", path)

if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
