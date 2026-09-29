"""Regenerate the narration in a new voice while preserving each clip's duration (scene timings are built on the old clips)."""
import base64, json, os, pathlib, subprocess, sys
import httpx

K = os.environ["ELEVENLABS_API_KEY"]; H = {"xi-api-key": K}
A = pathlib.Path(__file__).parent / "audio"
VOICE = sys.argv[1]
old = json.load(open(A / "vo_meta_adam.json"))
new = {}

def dur(p):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)], capture_output=True, text=True).stdout)

def tts(text, speed):
    r = httpx.post(f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE}/with-timestamps?output_format=mp3_44100_192", headers=H, timeout=180,
        json={"text": text, "model_id": "eleven_multilingual_v2",
              "voice_settings": {"stability": 0.45, "similarity_boost": 0.8, "style": 0.3, "use_speaker_boost": True, "speed": round(speed, 3)}})
    r.raise_for_status(); d = r.json(); al = d["alignment"]
    words, cur, st, pe = [], "", None, 0
    for ch, s, e in zip(al["characters"], al["character_start_times_seconds"], al["character_end_times_seconds"]):
        if ch.isspace():
            if cur: words.append({"w": cur, "s": round(st, 3), "e": round(pe, 3)}); cur, st = "", None
        else:
            if st is None: st = s
            cur += ch; pe = e
    if cur: words.append({"w": cur, "s": round(st, 3), "e": round(pe, 3)})
    return base64.b64decode(d["audio_base64"]), words

for name, o in old.items():
    if o["voice"] != "pNInz6obpgDQGcFmaJgB":      # keep Dad's voice (Bill) untouched
        new[name] = o; continue
    target = dur(A / "vo_adam" / f"{name}.mp3"); speed = 0.96
    for attempt in range(2):
        audio, words = tts(o["text"], speed)
        tmp = A / "vo" / f"{name}.tmp.mp3"; tmp.write_bytes(audio); d = dur(tmp)
        if abs(d / target - 1) < 0.03: break
        speed = min(max(speed * d / target, 0.75), 1.2)
    ratio = d / target                               # >1: new clip is longer -> speed up slightly to match exactly
    out = A / "vo" / f"{name}.mp3"
    if abs(ratio - 1) > 0.004:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(tmp), "-af", f"atempo={ratio:.5f}", "-b:a", "192k", str(out)], check=True)
    else:
        tmp.replace(out)
    tmp.unlink(missing_ok=True)
    words = [{"w": w["w"], "s": round(w["s"] / ratio, 3), "e": round(w["e"] / ratio, 3)} for w in words]
    new[name] = {"voice": VOICE, "text": o["text"], "duration": round(dur(out), 3), "words": words}
    # sync report: how far do words move relative to the clip the scenes were built on?
    ow = o["words"]; n = min(len(ow), len(words))
    dev = [abs(ow[i]["s"] - words[i]["s"]) for i in range(n)]
    print(f"{name:12s} target {target:6.2f}s got {dur(out):6.2f}s speed {speed:.2f} atempo {ratio:.3f} | words {len(ow)}/{len(words)} max drift {max(dev):.2f}s  >0.25s: {sum(d_ > 0.25 for d_ in dev)}")
json.dump(new, open(A / "vo_meta.json", "w"), indent=1)
