"""Exact music-ducking envelope from the narration timeline: music sits DUCK_DB below the voice whenever the
narrator speaks (smooth fades), and returns to full level when nobody is speaking."""
import json, pathlib, wave
import numpy as np

SR = 48000

def intervals(timeline, pre=0.25, post=0.35, merge_gap=1.2):
    iv = sorted((v["start"] - pre, v["end"] + post) for v in timeline.values())
    out = [list(iv[0])]
    for a, b in iv[1:]:
        if a - out[-1][1] < merge_gap:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out

def make_envelope(timeline, path, dur=176.0, duck_db=-14.0, down=0.35, up=0.9):
    t = np.arange(int(dur * SR)) / SR
    duck = 10 ** (duck_db / 20)
    amount = np.zeros_like(t)
    for a, b in intervals(timeline):
        ramp_in = np.clip((t - (a - down)) / down, 0, 1)
        ramp_out = np.clip(((b + up) - t) / up, 0, 1)
        amount = np.maximum(amount, np.minimum(ramp_in, ramp_out))
    env = 1 - (1 - duck) * amount
    pcm = (np.clip(env, 0, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm.tobytes())
    return env
