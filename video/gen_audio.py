"""Generate the Recall video audio with ElevenLabs: narration (with word timings), SFX, and the score.
    python3 video/gen_audio.py vo | sfx | music
"""
import base64, json, os, sys, pathlib, time
import httpx

K = os.environ["ELEVENLABS_API_KEY"]; H = {"xi-api-key": K}
A = pathlib.Path(__file__).parent / "audio"
ADAM, BILL = "pNInz6obpgDQGcFmaJgB", "pqHfZKP75CvOlQylNhV4"

VO = {
 "v01_hook":   (ADAM, "It's eight-twenty. Your father is eighty-one. He lives alone. He's not answering."),
 "v02_answer": (ADAM, "Three cameras. One answer."),
 "v03_stats":  (ADAM, "Three out of four older adults want to stay in their own homes. One in four falls every year. And when it happens, minutes matter."),
 "v04_problem":(ADAM, "The cameras are already there. They saw everything. But when it matters, you're left scrubbing clips, hoping. Even Ring's own help page says video search can come back empty for specific people, and for searches phrased as questions."),
 "v05_memory": (ADAM, "Recall isn't security AI. It isn't video search. It isn't facial recognition. It's memory. Every Ring event becomes knowledge: who was there, what they did, where they went. Amazon Nova watches. Titan recognizes the same person across cameras, and across days."),
 "v06_hero":   (ADAM, "Not three matching videos. One reconstructed answer. Driveway. Front door. Back door. And then nothing. Every step is one click from proof: the exact clip, the exact second, the exact person."),
 "v07_routine":(ADAM, "And Recall doesn't wait to be asked. Mom is up by seven-thirty, six mornings out of six. This morning she isn't. Recall notices what didn't happen, and tells you first."),
 "v08_trust":  (ADAM, "You stay in control. Correct a mistake and Recall learns. Anything risky is flagged as unverified, and the clip is always the ground truth."),
 "v09_biz":    (ADAM, "This is bigger than one family. Three-quarters of older adults want to age at home. Home-care agencies, senior-living operators and insurers all need the same thing: to know someone is safe without a human watching a screen. Recall turns cameras that are already installed into a system of record, with proof in every answer."),
 "v10_stack":  (ADAM, "Built on Amazon Bedrock and Ring's APIs. Signed, idempotent webhooks. Human-in-the-loop safety. An MCP server, so Alexa plus and any agent can ask your home a question. Open source, and deployable in your own AWS account."),
 "v11_outro":  (ADAM, "Next time someone you love goes quiet... don't scrub. Ask."),
 "v12_dad":    (BILL, "Hey, son. Sorry. I was out back."),
}
SFX = {
 "phone_vibrate": ("smartphone vibrating on a wooden table, buzz buzz, close", 3.0),
 "heartbeat": ("slow deep human heartbeat, dull thump thump, close microphone, tense", 6.0),
 "typing": ("fast nervous laptop keyboard typing", 3.0),
 "riser": ("cinematic riser building tension, short", 3.0),
 "bass_hit": ("massive cinematic bass drop impact hit with sub boom and long tail", 3.0),
 "box_lock": ("short digital target lock-on blip, futuristic user interface", 1.0),
 "notify": ("smartphone notification ping, clean and clear", 1.5),
 "ping_stack": ("several rapid notification pings stacking on top of each other", 3.0),
 "needle_stop": ("record scratch abrupt stop", 1.5),
 "tape_scrub": ("fast video tape scrubbing whirring sound", 2.5),
 "data_stream": ("soft futuristic digital data stream whirring and processing", 3.5),
 "node_pop": ("soft bubble pop user interface", 0.8),
 "whoosh": ("smooth cinematic whoosh transition", 1.2),
 "tick": ("clean user interface checkmark tick", 0.6),
 "card_flip": ("paper card flip whoosh", 0.9),
 "phone_ring": ("old style electronic telephone ringing, two rings", 4.0),
 "room_tone": ("quiet night room tone with faint distant crickets", 8.0),
 "door_open": ("wooden back door opening slowly with a creak", 3.0),
 "sting_low": ("low ominous cinematic sting", 2.5),
 "clock_tick": ("soft clock ticking", 3.0),
 "lane_sweep": ("electric energy sweep whoosh rising, short", 1.5),
 "swoosh_in": ("fast swoosh in for graphic element", 0.8),
}
MUSIC = (
    'Warm, hopeful, emotional cinematic score for a documentary about family and caring for a parent, instrumental,'
    ' about 2 minutes 56 seconds, around 72 beats per minute. Soft felt piano and gentle strings with a warm, airy '
    'pad. It begins tender, quiet and slightly wistful, like a worried but loving thought. From about 0:40 it gentl'
    'y and optimistically builds: light arpeggiated piano, acoustic guitar, and strings swelling with reassurance. '
    'A confident, bright, uplifting and human peak from about 1:55 to 2:25. At about 2:30 it hushes to a single war'
    'm piano melody, intimate and emotional, then blossoms into a warm, resolved, hopeful final chord by 2:50 with '
    'a clean tail. No horror, no drones, no ominous or dark tension, no heartbeat, no trailer hits, no risers, no s'
    'ub-bass booms, no percussion until the build, no vocals.')

def vo():
    (A/"vo").mkdir(parents=True, exist_ok=True)
    meta = {}
    for name, (voice, text) in VO.items():
        r = httpx.post(f"https://api.elevenlabs.io/v1/text-to-speech/{voice}/with-timestamps?output_format=mp3_44100_192", headers=H, timeout=180,
            json={"text": text, "model_id": "eleven_multilingual_v2",
                  "voice_settings": {"stability": 0.42, "similarity_boost": 0.8, "style": 0.35, "use_speaker_boost": True, "speed": 0.96}})
        r.raise_for_status(); d = r.json()
        (A/"vo"/f"{name}.mp3").write_bytes(base64.b64decode(d["audio_base64"]))
        al = d["alignment"]; ends = al["character_end_times_seconds"]
        # word-level timings from character alignment
        words, cur, start = [], "", None
        for ch, s, e in zip(al["characters"], al["character_start_times_seconds"], ends):
            if ch.isspace():
                if cur: words.append({"w": cur, "s": round(start, 3), "e": round(pe, 3)}); cur, start = "", None
            else:
                if start is None: start = s
                cur += ch; pe = e
        if cur: words.append({"w": cur, "s": round(start, 3), "e": round(pe, 3)})
        meta[name] = {"voice": voice, "text": text, "duration": round(ends[-1], 3), "words": words}
        print(name, meta[name]["duration"], "s")
    (A/"vo_meta.json").write_text(json.dumps(meta, indent=1))

def sfx():
    (A/"sfx").mkdir(parents=True, exist_ok=True)
    for name, (prompt, dur) in SFX.items():
        p = A/"sfx"/f"{name}.mp3"
        if p.exists(): continue
        r = httpx.post("https://api.elevenlabs.io/v1/sound-generation?output_format=mp3_44100_128", headers=H, timeout=120,
                       json={"text": prompt, "duration_seconds": dur, "prompt_influence": 0.5})
        if r.status_code != 200: print(name, "FAILED", r.status_code, r.text[:100]); continue
        p.write_bytes(r.content); print(name, len(r.content))

def music():
    r = httpx.post("https://api.elevenlabs.io/v1/music?output_format=mp3_44100_192", headers=H, timeout=600,
                   json={"prompt": MUSIC, "music_length_ms": 176000, "force_instrumental": True})
    print("music", r.status_code, len(r.content), r.text[:200] if r.status_code != 200 else "")
    if r.status_code == 200: (A/"music.mp3").write_bytes(r.content)

if __name__ == "__main__":
    for step in sys.argv[1:]: globals()[step]()
