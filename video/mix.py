"""Mix the Recall video soundtrack: ElevenLabs narration + score (ducked under the voice) + SFX cues.
    python3 video/mix.py            -> video/recall-demo/assets/audio/mix.wav  (176 s, stereo 48k, -14 LUFS)
Cues: video/recall-demo/compositions/cues/*.json = [{"t": seconds, "sfx": "bass_hit", "gain": 1.0, "dur": 1.5, "fade": 0.2}]
"""
import glob, json, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).parent
A = ROOT / "audio"; P = ROOT / "recall-demo"
DUR = 176.0
MUSIC_GAIN, VO_GAIN, SFX_GAIN = 0.62, 1.0, 0.30

tl = json.load(open(P / "vo_timeline.json"))
cues = []
for f in sorted(glob.glob(str(P / "compositions/cues/*.json"))):
    cues += json.load(open(f))
cues.sort(key=lambda c: c["t"])

inputs, chains, vo_labels, sfx_labels = [], [], [], []
def add(path):
    inputs.extend(["-i", str(path)]); return len(inputs) // 2 - 1

m = add(A / "music.mp3")
chains.append(f"[{m}:a]atrim=0:{DUR},asetpts=PTS-STARTPTS,volume={MUSIC_GAIN},aformat=sample_rates=48000:channel_layouts=stereo[music]")
for k, v in tl.items():
    i = add(A / "vo" / f"{k}.mp3"); ms = int(v["start"] * 1000)
    chains.append(f"[{i}:a]aformat=sample_rates=48000:channel_layouts=stereo,volume={VO_GAIN},adelay={ms}|{ms}[vo_{k}]")
    vo_labels.append(f"[vo_{k}]")
chains.append("".join(vo_labels) + f"amix=inputs={len(vo_labels)}:normalize=0:duration=longest,apad=whole_dur={DUR}[vo]")
chains.append("[vo]asplit=3[vo_out][vo_sc][vo_sc2]")
chains.append("[music][vo_sc]sidechaincompress=threshold=0.02:ratio=9:attack=15:release=450:makeup=1[music_d]")
for n, c in enumerate(cues):
    f = A / "sfx" / f"{c['sfx']}.mp3"
    if not f.exists():
        print("missing sfx", c["sfx"]); continue
    i = add(f); ms = int(max(c["t"], 0) * 1000); g = c.get("gain", 1.0) * 0.5
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
print("wrote", out, f"({len(cues)} sfx cues)")
r = subprocess.run(["ffmpeg", "-i", str(out), "-af", "loudnorm=print_format=summary", "-f", "null", "-"], capture_output=True, text=True)
print([l for l in r.stderr.splitlines() if "Input Integrated" in l or "Input True Peak" in l])
