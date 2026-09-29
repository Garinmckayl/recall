"""Jev — the System One decision layer, on the real TypeSafe Decisions API.

state (JSON) in -> typed probabilistic answers out:
  choice questions -> {choice, probabilities per label, confidence}
  score questions  -> {score: anchor index, legend, probabilities, confidence}

Model: typesafe/jev-1.13 via https://openrouter.ai/api/alpha/decisions.
If the endpoint/model is unavailable, every call transparently falls back to an
LLM constrained to the same typed question set; downstream never knows.
"""
from __future__ import annotations

import json
import base64
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

import config

DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions"


class JevError(RuntimeError):
    pass


@dataclass
class Decision:
    """One System One decision: typed answers + calibrated probabilities."""
    questions: dict[str, dict]                     # question name -> typed answer
    engine: str = "jev"
    latency_ms: int = 0
    usage: Optional[dict] = None

    def choice(self, name: str) -> str:
        return str(self.questions[name].get("choice", ""))

    def score01(self, name: str) -> float:
        """Score answers index into the anchor list; normalize to 0..1."""
        a = self.questions.get(name, {})
        if "score" not in a:
            return float(a.get("value", 0.0))
        anchors = a.get("legend", {})
        n = max(len(anchors) - 1, 1)
        return max(0.0, min(1.0, float(a["score"]) / n))

    def conf(self, name: str) -> float:
        return float(self.questions[name].get("confidence", 0.0))

    def probabilities(self, name: str) -> dict[str, float]:
        return {k: float(v) for k, v in self.questions[name].get("probabilities", {}).items()}


# ---------------------------------------------------------------------------
# Question sets — the System One interface of the whole system.
# ---------------------------------------------------------------------------

Q_FRAME = {
    "kind": {
        "type": "choice",
        "instructions": "What is the single dominant subject in the described camera frame?",
        "criteria": {
            "person": "a human being",
            "animal": "a pet or other animal",
            "package": "a delivered parcel, box, or mail",
            "vehicle": "a car, truck, or bike",
            "nothing": "empty scene or weather only",
        },
    },
    "identity": {
        "type": "choice",
        "instructions": ("Whose identity best fits the subject? Compare the frame description "
                          "against enrolled_residents (appearance references captured at "
                          "enrollment, like Ring face enrollment). A distinctive match — same "
                          "uniform, clothing colors, or build described in the reference — "
                          "counts as that resident even in a different pose or lighting. Use "
                          "the timeline for context. Only pick 'stranger' when the appearance "
                          "matches no enrolled resident at all."),
        "criteria": {
            "dad": "the resident 'Dad' (middle-aged man, bright blue shirt)",
            "mom": "the resident 'Mom' (middle-aged woman)",
            "dog": "the household dog",
            "courier": "a delivery worker carrying a package or in uniform",
            "stranger": "an unidentified person — appearance does not match any resident",
        },
    },
    "activity": {
        "type": "choice",
        "instructions": "What is the subject doing?",
        "criteria": {
            "arriving": "moving toward or entering the home",
            "leaving": "moving away from or exiting the home",
            "waiting": "stationary, lingering, or hovering",
            "delivering": "dropping off a package or mail",
            "wandering": "moving around casually",
            "idle": "nothing notable",
        },
    },
    "concern": {
        "type": "choice",
        "instructions": "How concerning is this frame for a household security agent?",
        "criteria": {
            "normal": ("routine: residents or enrolled people, couriers or visitors politely "
                       "at the door or mid-delivery, people greeting or embracing family "
                       "members, residents receiving packages, pets, weather"),
            "notable": "unusual but likely benign: unfamiliar person walking past, brief stop",
            "suspicious": ("possible threat: unidentified person lingering without purpose, "
                           "avoiding being seen, loitering repeatedly near entry points, tampering"),
            "emergency": "forced entry, violence, visible weapon, smoke or fire, injury",
        },
    },
    "concern_score": {
        "type": "score",
        "instructions": "Rate the concern on this scale.",
        "criteria": [
            "0.0 = fully routine, known person or harmless event",
            "0.5 = unusual, probably benign, worth logging",
            "1.0 = active emergency: break-in, violence, danger",
        ],
    },
}

Q_INTERVENE = {
    "act": {
        "type": "choice",
        "instructions": "Should the home agent intervene right now (notify the household)?",
        "criteria": {
            "yes": "Something needs attention or could become dangerous; disturb the household.",
            "no": "Routine, self-explanatory, or already resolved; do not disturb.",
        },
    },
    "urgency": {
        "type": "choice",
        "instructions": "If acting, how urgent is the notification?",
        "criteria": {"low": "fyi level", "medium": "soon", "high": "immediate attention", "critical": "emergency"},
    },
    "web_action": {
        "type": "choice",
        "instructions": "If acting, the single most useful web action to take.",
        "criteria": {
            "lookup_non_emergency_police": "possible prowler or intrusion",
            "lookup_local_locksmith": "locked out or lock damage",
            "lookup_nearest_open_pharmacy": "medical need",
            "none": "no web action needed",
        },
    },
    "routine": {
        "type": "choice",
        "instructions": ("Is the observation fully explained by routine household activity? "
                          "Be generous: a delivery or courier completing a drop-off, a resident "
                          "arriving or leaving, a pet roaming, a known vehicle are ALL routine."),
        "criteria": {
            "yes": "routine activity — do not alert the household",
            "no": "not explainable by routine activity",
        },
    },
}

Q_INTENT = {
    "intent": {
        "type": "choice",
        "instructions": "Classify what the owner is asking about the event history.",
        "criteria": {
            "last_seen": "when/where a subject was most recently observed",
            "first_seen": "the first observation of a subject",
            "presence_window": "the full span between first and last sighting",
            "reconstruct": "explain a stretch of events / what happened",
            "list_events": "everything recorded",
        },
    },
    "subject": {
        "type": "choice",
        "instructions": "Which subject is the question about?",
        "criteria": {
            "dad": "the father / male resident",
            "mom": "the mother / female resident",
            "dog": "the pet",
            "courier": "a delivery person",
            "stranger": "an unidentified or unfamiliar person",
            "package": "a delivered item",
            "anyone": "everyone / no specific person",
        },
    },
    "output": {
        "type": "choice",
        "instructions": ("What does the owner want back? 'show me...' means they want the "
                          "camera footage at that moment."),
        "criteria": {
            "show_me": "show the moment in the video (jump to it)",
            "summary": "a short direct answer",
            "timeline": "a list of events",
            "narrative": "a reconstruction of what happened",
        },
    },
}

# -- Recall (v2): per-actor role, query operator, watch rules ---------------------

ROLES = {
    "delivery_driver": "delivers food, packages or mail: carries a parcel/food bag/box, approaches the door, hands it over or leaves it, then leaves promptly",
    "resident_family": "lives here or is close family: arrives/leaves like a household member, lets themselves in",
    "guest_visitor": "a friend or invited visitor who stays, is greeted, or is let in",
    "service_worker": "a technician, utility or repair worker, cleaner or contractor doing a job",
    "solicitor": "a salesperson, canvasser or flyer distributor going door to door with nothing to deliver",
    "passerby": "walks past the property without engaging with it",
    "suspicious": "lingers, peers into windows, tries handles, hides their face, or otherwise behaves like a prowler",
    "unknown": "not enough evidence to say",
}

Q_ROLE = {
    "role": {
        "type": "choice",
        "instructions": ("What is this person's most likely role in THIS event? Judge only from the "
                         "structured facts: what they carry, what they do, who they interact with, "
                         "the camera zone and time of day. Uniform alone is weak evidence; carrying a "
                         "delivery item and leaving right after handing it over is strong evidence."),
        "criteria": ROLES,
    },
    "concern": Q_FRAME["concern"],
    "concern_score": Q_FRAME["concern_score"],
}

Q_OPERATOR = {
    "operator": {
        "type": "choice",
        "instructions": "Which reasoning operator answers the owner's question about their home camera memory?",
        "criteria": {
            "identify_person": "which person is a given kind of person (e.g. 'which guy is the delivery guy', 'who is the stranger')",
            "find_events": "show/find a specific event or kind of event, optionally in a time window (e.g. 'show me the last pizza delivery', 'who knocked six days ago', 'when did the package arrive')",
            "last_seen": "where or when a specific person was last seen",
            "trajectory": "the path/movements/whole day of a person across cameras",
            "after_departure": "what happened, or whether anyone came, after a specific person left",
            "security_incident": "a threatening or dangerous event: a weapon, break-in, fight, forced entry",
            "watch_request": "asks to be notified in the future / keep watching for something",
            "describe_person": "what a person looks like, how often or when they visit",
            "routine_check": "whether a person's day is normal / matches their usual pattern, or when they usually come and go",
            "count": "how many times something happened",
            "other": "not about the camera memory",
        },
    },
    "ordinal": {
        "type": "choice",
        "instructions": "Which occurrence does the owner want?",
        "criteria": {"last": "the most recent one", "first": "the earliest one", "all": "every occurrence / no preference"},
    },
}

Q_RULE = {
    "rule_kind": {
        "type": "choice",
        "instructions": "What kind of standing watch rule does the owner want?",
        "criteria": {
            "person_arrives": "notify whenever a specific person is seen again ('tell me next time this person comes')",
            "person_departs_window": "notify if a specific person leaves during a time window ('tell me if Dad leaves after midnight')",
            "role_arrives": "notify whenever a kind of visitor (delivery, service worker...) arrives",
            "unknown_at_night": "notify when an unrecognized person appears at night",
        },
    },
}


def subject_question(names: dict[str, str]) -> dict:
    """Dynamic 'who is this about' question: known people by name + role classes + anaphora."""
    crit = {n: desc for n, desc in names.items()}
    crit.update({
        "role_delivery_driver": "a delivery person / courier / the delivery guy",
        "role_suspicious": "a suspicious person, prowler or someone threatening",
        "role_service_worker": "a technician, repair or utility worker",
        "role_guest_visitor": "a visitor or guest",
        "this_person": "the person from the previous answer ('this person', 'him', 'her', 'them')",
        "anyone": "no specific person, or everyone",
    })
    return {"subject": {"type": "choice",
                        "instructions": "Who or what kind of person is the owner asking about?",
                        "criteria": crit}}


# LLM-fallback system prompt is defined below; schemas are built per-call.

_SYSTEM_FALLBACK = (
    "You are a System One decision engine. For each question, choose one option and "
    "output ONLY compact JSON: {\"<question>\": {\"choice\": \"<option>\" | \"score\": <int>, "
    "\"confidence\": <0..1>}, ...}. No prose."
)


class JevClient:
    def __init__(self) -> None:
        self._client = httpx.Client(
            headers={"Authorization": f"Bearer {config.OPENROUTER_API_KEY}"},
            timeout=45.0,
        )
        self._jev_ok: Optional[bool] = None  # None = untested

    # -- public ---------------------------------------------------------------

    def ask(
        self,
        questions: dict[str, dict],
        state: dict | str,
        images: Optional[list[bytes]] = None,
    ) -> Decision:
        """State in -> typed probabilistic answers out."""
        if self._jev_ok is not False:
            try:
                return self._ask_jev(questions, state)
            except JevError:
                self._jev_ok = False  # stop retrying; surface engine in UI
        return self._ask_llm(questions, state, images)

    # -- real Jev: Decisions API ---------------------------------------------

    def _ask_jev(self, questions: dict[str, dict], state: dict | str) -> Decision:
        t0 = time.monotonic()
        body = {"model": config.JEV_MODEL, "state": state, "questions": questions}
        try:
            resp = self._client.post(DECISIONS_URL, json=body)
        except httpx.HTTPError as e:
            raise JevError(f"transport: {e}") from e
        if resp.status_code != 200:
            raise JevError(f"decisions -> HTTP {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        answers = data.get("answers")
        if not isinstance(answers, dict):
            raise JevError(f"no answers: {str(data)[:200]}")
        return Decision(
            questions=answers,
            engine="jev",
            latency_ms=int((time.monotonic() - t0) * 1000),
            usage=data.get("usage"),
        )

    # -- fallback: LLM with the same questions ---------------------------------

    def _ask_llm(self, questions: dict[str, dict], state: dict | str, images: list[bytes]) -> Decision:
        t0 = time.monotonic()
        qdesc = "\n".join(
            f"- {name} ({q['type']}): {q['instructions']} Options: {json.dumps(q.get('criteria', {}))}"
            for name, q in questions.items()
        )
        content: list[dict] = [{
            "type": "text",
            "text": f"State:\n{json.dumps(state) if not isinstance(state, str) else state}\n\nQuestions:\n{qdesc}",
        }]
        for img in images or []:
            content.append({
                "type": "image_url",
                "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(img).decode()},
            })
        try:
            resp = self._client.post(
                f"{config.OPENROUTER_BASE}/chat/completions",
                json={
                    "model": config.DECISION_MODEL,
                    "max_tokens": 800,
                    "messages": [
                        {"role": "system", "content": _SYSTEM_FALLBACK},
                        {"role": "user", "content": content},
                    ],
                },
            )
            resp.raise_for_status()
            text = resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            raise JevError(f"fallback LLM: {e}") from e
        import re
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            raise JevError(f"fallback: no JSON: {text[:200]}")
        raw = json.loads(m.group(0))
        answers: dict[str, dict] = {}
        for name, q in questions.items():
            a = raw.get(name, {})
            if "choice" in a:
                answers[name] = {"type": "choice", "choice": a["choice"],
                                 "confidence": float(a.get("confidence", 0.6)), "probabilities": {}}
            elif "score" in a:
                idx = max(0, len(q.get("criteria", [])) - 1)
                answers[name] = {"type": "score", "score": float(a["score"]), "legend": {}, "probabilities": {},
                                 "confidence": float(a.get("confidence", 0.6))}
                if idx:
                    answers[name]["score"] = min(float(a["score"]), idx)
            else:
                first = next(iter(q.get("criteria", {}).keys()), "none")
                answers[name] = {"type": "choice", "choice": first, "confidence": 0.0, "probabilities": {}}
        return Decision(
            questions=answers,
            engine=f"llm-fallback:{config.DECISION_MODEL}",
            latency_ms=int((time.monotonic() - t0) * 1000),
        )

    @property
    def engine_name(self) -> str:
        return "jev (TypeSafe)" if self._jev_ok is not False else f"llm-fallback:{config.DECISION_MODEL}"


_client: Optional[JevClient] = None


def client() -> JevClient:
    global _client
    if _client is None:
        _client = JevClient()
    return _client
