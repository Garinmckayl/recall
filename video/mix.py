"""Mix the Recall video soundtrack: ElevenLabs narration + score (ducked under the voice) + SFX cues.
    python3 video/mix.py            -> video/recall-demo/assets/audio/mix.wav  (176 s, stereo 48k, -14 LUFS)
Cues: video/recall-demo/compositions/cues/*.json = [{"t": seconds, "sfx": "bass_hit", "gain": 1.0, "dur": 1.5, "fade": 0.2}]
"""
import glob, json, pathlib, subprocess, sys
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from envelope import make_envelope

ROOT = pathlib.Path(__file__).parent
A = ROOT / "audio"; P = ROOT / "recall-demo"
DUR = 176.0
MUSIC_GAIN, VO_GAIN, SFX_GAIN = 0.24, 1.0, 0.16   # music alone ~ voice level; ducked 14 dB under speech

tl = json.load(open(P / "vo_timeline.json"))
cues = []
for f in sorted(glob.glob(str(P / "compositions/cues/*.json"))):
    cues += json.load(open(f))
cues.sort(key=lambda c: c["t"])

# Effects are a subtle layer for a warm, human story: drop the ominous/harsh ones, soften the rest.
# name -> (file to use, relative level) ; None = drop the cue
SFX_MAP = {
    "bass_hit": ("soft_hit", 0.9), "sting_low": None, "riser": None, "ping_stack": None, "tape_scrub": None, "needle_stop": None,
    "heartbeat": ("heartbeat", 0.30), "clock_tick": ("clock_tick", 0.5), "data_stream": ("data_stream", 0.5),
    "whoosh": ("whoosh", 0.55), "swoosh_in": ("swoosh_in", 0.55), "lane_sweep": ("lane_sweep", 0.5), "tick": ("tick", 0.6),
    "node_pop": ("node_pop", 0.6), "card_flip": ("card_flip", 0.6), "box_lock": ("box_lock", 0.6), "typing": ("typing", 0.7),
    "notify": ("notify", 0.7), "phone_vibrate": ("phone_vibrate", 0.7), "phone_ring": ("phone_ring", 0.7),
    "room_tone": ("room_tone", 0.5), "door_open": ("door_open", 0.7),
}

inputs, chains, vo_labels, sfx_labels = [], [], [], []
def add(path):
    inputs.extend(["-i", str(path)]); return len(inputs) // 2 - 1

m = add(A / "music.mp3")
make_envelope(tl, ROOT / "audio" / "music_duck.wav", DUR)
e = add(ROOT / "audio" / "music_duck.wav")
chains.append(f"[{m}:a]atrim=0:{DUR},asetpts=PTS-STARTPTS,volume={MUSIC_GAIN},aformat=sample_rates=48000:channel_layouts=stereo[music_raw]")
chains.append(f"[{e}:a]aformat=sample_rates=48000:channel_layouts=stereo[duck_env]")
chains.append("[music_raw][duck_env]amultiply[music_d]")
for k, v in tl.items():
    i = add(A / "vo" / f"{k}.mp3"); ms = int(v["start"] * 1000)
    chains.append(f"[{i}:a]aformat=sample_rates=48000:channel_layouts=stereo,volume={VO_GAIN},adelay={ms}|{ms}[vo_{k}]")
    vo_labels.append(f"[vo_{k}]")
chains.append("".join(vo_labels) + f"amix=inputs={len(vo_labels)}:normalize=0:duration=longest,apad=whole_dur={DUR}[vo]")
chains.append("[vo]asplit=2[vo_out][vo_sc2]")
for n, c in enumerate(cues):
    fname, scale = SFX_MAP.get(c["sfx"], (c["sfx"], 1.0)) or (None, 0)
    if fname is None:
        continue
    f = A / "sfx" / f"{fname}.mp3"
    if not f.exists():
        print("missing sfx", fname); continue
    i = add(f); ms = int(max(c["t"], 0) * 1000); g = c.get("gain", 1.0) * 0.5 * scale
    trim = f"atrim=0:{c['dur']}," if c.get("dur") else ""
    fade = c.get("fade", 0.08)
    d = c.get("dur")
    afade = f",afade=t=out:st={max(d - fade, 0)}:d={fade}" if d else ""
    chains.append(f"[{i}:a]{trim}aformat=sample_rates=48000:channel_layouts=stereo,volume={g}{afade},adelay={ms}|{ms}[sx{n}]")
    sfx_labels.append(f"[sx{n}]")
if sfx_labels:
    # one SFX bus: softened highs, gentle compression on the peaks, and ducked under the narration
    chains.append("".join(sfx_labels) + f"amix=inputs={len(sfx_labels)}:normalize=0:duration=longest,volume={SFX_GAIN / 0.5},"
                  "highpass=f=45,lowpass=f=8500,acompressor=threshold=0.125:ratio=3.5:attack=4:release=140:makeup=1[sfxbus]")
    chains.append("[sfxbus][vo_sc2]sidechaincompress=threshold=0.02:ratio=3.2:attack=10:release=320:makeup=1[sfx_d]")
    mix_in, n_in = "[music_d][vo_out][sfx_d]", 3
else:
    mix_in, n_in = "[music_d][vo_out]", 2
chains.append(f"{mix_in}amix=inputs={n_in}:normalize=0:duration=longest,atrim=0:{DUR},"
              f"loudnorm=I=-14:TP=-1.5:LRA=9,aformat=sample_rates=48000:channel_layouts=stereo[out]")
out = P / "assets/audio/mix.wav"; out.parent.mkdir(parents=True, exist_ok=True)
cmd = ["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(chains), "-map", "[out]", "-t", str(DUR), "-c:a", "pcm_s16le", str(out)]
subprocess.run(cmd, check=True)
print("wrote", out, f"({len(cues)} sfx cues, {sum(1 for c in cues if SFX_MAP.get(c['sfx'], (1,1)) is not None)} kept)")
r = subprocess.run(["ffmpeg", "-i", str(out), "-af", "loudnorm=print_format=summary", "-f", "null", "-"], capture_output=True, text=True)
print([l for l in r.stderr.splitlines() if "Input Integrated" in l or "Input True Peak" in l])
