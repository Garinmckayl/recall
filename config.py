"""Jev HomeGuard configuration."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE = "https://openrouter.ai/api/v1"

# System One decision model (TypeSafe Jev). Falls back to DECISION_MODEL until
# the slug is provisioned on the key.
JEV_MODEL = os.getenv("JEV_MODEL", "typesafe/jev-latest")
VISION_MODEL = os.getenv("VISION_MODEL", "openai/gpt-4o-mini")
DECISION_MODEL = os.getenv("DECISION_MODEL", "openai/gpt-4o-mini")
NARRATOR_MODEL = os.getenv("NARRATOR_MODEL", "openai/gpt-4o-mini")

# Frame sampling
FRAME_INTERVAL_SEC = 4.0        # one frame every N seconds of footage
FRAME_MAX_WIDTH = 768           # downscale before sending to vision model

# Demo time-scale: the 72s synthetic clip maps onto a full day (wall clock).
# Real footage: set DAY_SECONDS = 86400.
DAY_SECONDS = 31
START_HOUR = 6                  # clip second 0 == 06:00 (night scene lands after midnight)

# UNDERSTAND thresholds
ANOMALY_TRIGGER = 0.62          # jev anomaly probability that fires ACT
CONFIDENCE_FLOOR = 0.45         # below this, identity stays "unknown-*"
NIGHT_START_HOUR = 20           # "after dark" for the demo narrative
SAME_SUBJECT_WINDOW = 20.0      # clip-seconds: same-category sightings within this = same subject

# ACT channels
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "jev-home-guard-demo")
ACTION_WEBHOOK_URL = os.getenv("ACTION_WEBHOOK_URL", "")
EXA_API_KEY = os.getenv("EXA_API_KEY", "")

# AWS Builder mini challenge (Bedrock narration; optional)
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
BEDROCK_MODEL = os.getenv("BEDROCK_MODEL", "us.amazon.nova-lite-v1:0")

# Paths
MEDIA_DIR = ROOT / "media"
DATA_DIR = Path(os.getenv("RECALL_DATA_DIR", str(ROOT / "data")))
EVENTS_PATH = DATA_DIR / "events.jsonl"
WORLD_PATH = DATA_DIR / "world.json"

# Known residents (demo scale: no auth, no billing, hard-coded household)
HOUSEHOLD = ["Dad", "Mom"]


# ---------------------------------------------------------------------------
# Recall (v2) — persistent visual memory over Ring events
# ---------------------------------------------------------------------------

# Ring Partner API. With RING_ACCESS_TOKEN set the client talks to the real
# platform; without it, to the local sandbox that mirrors the same endpoints.
RING_API_BASE = os.getenv("RING_API_BASE", "")
RING_ACCESS_TOKEN = os.getenv("RING_ACCESS_TOKEN", "")
RING_HMAC_KEY = os.getenv("RING_HMAC_KEY", "sandbox-hmac-key")
SERVER_URL = os.getenv("SERVER_URL", "http://127.0.0.1:8000")

# AWS models (Bedrock). Vision + reasoning on Nova, re-identification on Titan.
NOVA_VISION_MODEL = os.getenv("NOVA_VISION_MODEL", "us.amazon.nova-pro-v1:0")
NOVA_TEXT_MODEL = os.getenv("NOVA_TEXT_MODEL", "us.amazon.nova-lite-v1:0")
TITAN_IMAGE_EMBED = os.getenv("TITAN_IMAGE_EMBED", "amazon.titan-embed-image-v1")
TITAN_TEXT_EMBED = os.getenv("TITAN_TEXT_EMBED", "amazon.titan-embed-text-v2:0")

# Perception
KEYFRAMES_PER_EVENT = int(os.getenv("KEYFRAMES_PER_EVENT", "6"))
KEYFRAME_MAX_WIDTH = 896

# Re-identification thresholds (tuned on staged footage; see identity.py)
REID_MATCH = float(os.getenv("REID_MATCH", "0.70"))
REID_MAX_EXEMPLARS = 6

# Memory store
DB_PATH = DATA_DIR / "recall.db"
CLIPS_DIR = DATA_DIR / "clips"
THUMBS_DIR = DATA_DIR / "thumbs"
SANDBOX_DIR = DATA_DIR / "ring_sandbox"
DEMO_CLIPS_DIR = ROOT / "demo_clips"
STATIC_DIR = ROOT / "static"

# Role aggregation: shrink toward "unknown" so one event never yields certainty
ROLE_PRIOR_MASS = 0.5
# A person is a "trajectory" session while consecutive sightings are within this gap
SESSION_GAP_SEC = 45 * 60

# Public-deploy safety: destructive demo endpoints need this token when it is set (unset = open, for local use)
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")
