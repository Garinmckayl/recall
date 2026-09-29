"""Amazon Bedrock: the load-bearing AWS layer of Recall.

  Amazon Nova Pro   -> perception: keyframes -> structured event record (multi-image Converse)
  Amazon Nova Lite  -> slot extraction + evidence-grounded narration
  Titan Embeddings  -> person re-identification (image crops) + fuzzy event retrieval (text)

Every call has a degraded path (OpenRouter chat / hashed bag-of-words embedding) so the
pipeline keeps running when Bedrock is unreachable; `engine_report()` says what actually ran.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import re
import threading
import time
from typing import Any, Optional

import httpx

import config

_client = None
_client_lock = threading.Lock()
_engines: dict[str, str] = {}


class AwsError(RuntimeError):
    pass


def _bedrock():
    global _client
    with _client_lock:
        if _client is None:
            import boto3
            from botocore.config import Config
            _client = boto3.client(
                "bedrock-runtime", region_name=config.AWS_REGION,
                config=Config(read_timeout=90, retries={"max_attempts": 4, "mode": "adaptive"}))
        return _client


def reset_client() -> None:
    global _client
    with _client_lock:
        _client = None


def available() -> bool:
    try:
        import boto3
        return boto3.Session().get_credentials() is not None
    except Exception:
        return False


def engine_report() -> dict:
    return dict(_engines)


def _mark(role: str, name: str) -> None:
    _engines[role] = name


# -- JSON helpers ---------------------------------------------------------------------

def parse_json(text: str) -> dict:
    """Pull the first JSON object out of a model reply (tolerates fences/prose)."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    start = text.find("{")
    if start < 0:
        raise AwsError(f"no JSON in reply: {text[:160]}")
    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    raise AwsError(f"unterminated JSON: {text[:160]}")


# -- Nova: converse -------------------------------------------------------------------

def _converse(model_id: str, system: str, content: list[dict], max_tokens: int, temperature: float = 0.0) -> str:
    kwargs: dict[str, Any] = {
        "modelId": model_id,
        "messages": [{"role": "user", "content": content}],
        "inferenceConfig": {"maxTokens": max_tokens, "temperature": temperature},
    }
    if system:
        kwargs["system"] = [{"text": system}]
    resp = _bedrock().converse(**kwargs)
    return resp["output"]["message"]["content"][0]["text"]


def _openrouter(model: str, system: str, user_text: str, images: list[bytes], max_tokens: int) -> str:
    content: list[dict] = [{"type": "text", "text": user_text}]
    for img in images:
        content.append({"type": "image_url",
                        "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(img).decode()}})
    msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": content}]
    r = httpx.post(f"{config.OPENROUTER_BASE}/chat/completions",
                   headers={"Authorization": f"Bearer {config.OPENROUTER_API_KEY}"},
                   json={"model": model, "max_tokens": max_tokens, "messages": msgs}, timeout=90.0)
    r.raise_for_status()
    return (r.json()["choices"][0]["message"].get("content") or "").strip()


def vision_json(system: str, prompt: str, images: list[bytes], max_tokens: int = 2500) -> dict:
    """Multi-image structured perception. Nova Pro first; OpenRouter vision model as fallback."""
    if available():
        try:
            content: list[dict] = [{"image": {"format": "jpeg", "source": {"bytes": b}}} for b in images]
            content.append({"text": prompt})
            text = _converse(config.NOVA_VISION_MODEL, system, content, max_tokens)
            out = parse_json(text)
            _mark("vision", f"Amazon Nova Pro ({config.NOVA_VISION_MODEL})")
            return out
        except Exception as e:
            _mark("vision_error", str(e)[:160])
    text = _openrouter(config.VISION_MODEL, system, prompt, images, max_tokens)
    _mark("vision", f"fallback: {config.VISION_MODEL}")
    return parse_json(text)


def text(system: str, user: str, max_tokens: int = 400, temperature: float = 0.2) -> str:
    if available():
        try:
            out = _converse(config.NOVA_TEXT_MODEL, system, [{"text": user}], max_tokens, temperature).strip()
            _mark("text", f"Amazon Nova Lite ({config.NOVA_TEXT_MODEL})")
            return out
        except Exception as e:
            _mark("text_error", str(e)[:160])
    out = _openrouter(config.NARRATOR_MODEL, system, user, [], max_tokens)
    _mark("text", f"fallback: {config.NARRATOR_MODEL}")
    return out


def text_json(system: str, user: str, max_tokens: int = 400) -> dict:
    return parse_json(text(system, user, max_tokens, temperature=0.0))


# -- Titan embeddings -----------------------------------------------------------------

def _unit(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def embed_image(jpeg: bytes) -> Optional[list[float]]:
    """Titan multimodal image embedding (384-d, unit norm). None if Bedrock is unavailable."""
    if not available():
        return None
    try:
        body = {"inputImage": base64.b64encode(jpeg).decode(),
                "embeddingConfig": {"outputEmbeddingLength": 384}}
        r = _bedrock().invoke_model(modelId=config.TITAN_IMAGE_EMBED, body=json.dumps(body))
        _mark("embed_image", config.TITAN_IMAGE_EMBED)
        return _unit(json.loads(r["body"].read())["embedding"])
    except Exception as e:
        _mark("embed_image_error", str(e)[:160])
        return None


def _hash_embed(s: str, dim: int = 256) -> list[float]:
    """Deterministic bag-of-words fallback so retrieval works offline / in tests."""
    v = [0.0] * dim
    for tok in re.findall(r"[a-z0-9]+", s.lower()):
        h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
        v[h % dim] += 1.0 if (h >> 8) & 1 else -1.0
    return _unit(v)


def embed_text(s: str) -> list[float]:
    """Titan Text v2 embedding (256-d, unit norm); hashed fallback."""
    if available():
        try:
            body = {"inputText": s[:2000], "dimensions": 256, "normalize": True}
            r = _bedrock().invoke_model(modelId=config.TITAN_TEXT_EMBED, body=json.dumps(body))
            _mark("embed_text", config.TITAN_TEXT_EMBED)
            return _unit(json.loads(r["body"].read())["embedding"])
        except Exception as e:
            _mark("embed_text_error", str(e)[:160])
    _mark("embed_text", "hashed-bow (offline fallback)")
    return _hash_embed(s)


def cosine(a: Optional[list[float]], b: Optional[list[float]]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b))
