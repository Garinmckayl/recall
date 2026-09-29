"""Re-voice the narration and align it PHRASE-BY-PHRASE to the timing the scenes were built on.
Sentences keep their natural delivery (tempo nudged within limits); pauses absorb the difference.
    python3 video/align_vo.py <voice_id>
"""
import base64, json, os, pathlib, re, subprocess, sys
import httpx

H = {"xi-api-key": os.environ["ELEVENLABS_API_KEY"]}
A = pathlib.Path(__file__).parent / "audio"
VOICE = sys.argv[1]
OLDV = "pNInz6obpgDQGcFmaJgB"
old = json.load(open(A / "vo_meta_adam.json"))
(A / "vo_raw").mkdir(exist_ok=True)
R_MIN, R_MAX = 0.82, 1.22

def dur(p):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)], capture_output=True, text=True).stdout)

def gen(text, speed=0.98):
    r = httpx.post(f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE}/with-timestamps?output_format=mp3_44100_192", headers=H, timeout=180,
        json={"text": text, "model_id": "eleven_multilingual_v2",
              "voice_settings": {"stability": 0.45, "similarity_boost": 0.8, "style": 0.3, "use_speaker_boost": True, "speed": speed}})
    r.raise_for_status(); d = r.json(); al = d["alignment"]
    words, cur, st, pe = [], "", None, 0
    for ch, s, e in zip(al["characters"], al["character_start_times_seconds"], al["character_end_times_seconds"]):
        if ch.isspace():
            if cur: words.append({"w": cur, "s": s0, "e": pe}); cur, st = "", None
        else:
            if st is None: st = s; s0 = s
            cur += ch; pe = e
    if cur: words.append({"w": cur, "s": s0, "e": pe})
    return base64.b64decode(d["audio_base64"]), words

def phrases(words):
    out, start = [], 0
    for i, w in enumerate(words):
        if re.search(r"[.?!:,;]$", w["w"]) or i == len(words) - 1:
            out.append((start, i)); start = i + 1
    return out

meta = {}
for name, o in old.items():
    if o["voice"] != OLDV:
        meta[name] = o; continue
    audio, nw = gen(o["text"]); raw = A / "vo_raw" / f"{name}.mp3"; raw.write_bytes(audio); rawd = dur(raw)
    ow = o["words"]; assert len(ow) == len(nw), (name, len(ow), len(nw))
    ph = phrases(ow); total = dur(A / "vo_adam" / f"{name}.mp3")
    inputs, chains, labels, newwords = ["-i", str(raw)], [], [], [None] * len(nw)
    for k, (a, b) in enumerate(ph):
        s_new, e_new = nw[a]["s"], nw[b]["e"]; s_old, e_old = ow[a]["s"], ow[b]["e"]
        r = min(max((e_new - s_new) / max(e_old - s_old, 0.05), R_MIN), R_MAX)
        prev_end = nw[a - 1]["e"] if a > 0 else 0.0
        cut0 = max((prev_end + s_new) / 2, s_new - 0.14) if a > 0 else max(0.0, s_new - 0.14)
        nxt = nw[b + 1]["s"] if b + 1 < len(nw) else rawd
        cut1 = min((e_new + nxt) / 2, e_new + 0.28)
        pre = s_new - cut0
        delay = max(s_old - pre / r, 0.0)
        chains.append(f"[0:a]atrim={cut0:.3f}:{cut1:.3f},asetpts=PTS-STARTPTS,atempo={r:.4f},afade=t=in:d=0.02,afade=t=out:st={max((cut1-cut0)/r-0.03,0):.3f}:d=0.03,"
                      f"adelay={int(delay*1000)}|{int(delay*1000)}[p{k}]")
        labels.append(f"[p{k}]")
        for i in range(a, b + 1):
            newwords[i] = {"w": nw[i]["w"], "s": round(delay + pre / r + (nw[i]["s"] - s_new) / r, 3), "e": round(delay + pre / r + (nw[i]["e"] - s_new) / r, 3)}
    fc = ";".join(chains) + ";" + "".join(labels) + f"amix=inputs={len(labels)}:normalize=0:duration=longest,apad=whole_dur={total:.3f},atrim=0:{total:.3f}[o]"
    out = A / "vo" / f"{name}.mp3"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", fc, "-map", "[o]", "-b:a", "192k", str(out)], check=True)
    dev = [abs(ow[i]["s"] - newwords[i]["s"]) for i in range(len(ow))]
    ov = max((newwords[b]["e"] - ow[b + 1]["s"]) for _, b in ph[:-1]) if len(ph) > 1 else 0
    print(f"{name:12s} raw {rawd:6.2f}s -> {dur(out):6.2f}s | phrases {len(ph)} | max word drift {max(dev):.2f}s  >0.2s: {sum(d > .2 for d in dev):2d}/{len(dev)}  worst phrase overflow {ov:+.2f}s")
    meta[name] = {"voice": VOICE, "text": o["text"], "duration": round(dur(out), 3), "words": newwords}
json.dump(meta, open(A / "vo_meta.json", "w"), indent=1)
