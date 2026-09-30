"""Validation of participant turns (the JSON object a participant returns)."""
import json
import re

MAX_QUOTE_WORDS = 50
MAX_STEELMAN_SENTENCES = 3
ROLES = {"draft", "prosecutor", "defender", "adverse_witness", "premortem", "dissenter"}
FACTUAL = {"fact", "statistic", "causal"}
REQUIRED = {
    "draft": ["position", "claims", "key_assumptions", "cruxes", "strongest_counter", "probability"],
    "prosecutor": ["steelman", "target_claim", "attack", "claims"],
    "defender": ["steelman_check", "response", "change_basis", "position"],
    "adverse_witness": ["premise", "verdict", "claims"],
    "premortem": ["causes", "underconfidence"],
    "dissenter": ["claims"],
}

_FENCE = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL)


def extract(message):
    """Return the JSON object from a participant message, or raise ValueError."""
    text = (message or "").strip()
    m = _FENCE.search(text)
    candidate = m.group(1) if m else text[text.find("{"): text.rfind("}") + 1]
    if not candidate:
        raise ValueError("no JSON object found")
    try:
        obj = json.loads(candidate)
    except json.JSONDecodeError as e:
        raise ValueError("invalid JSON: %s" % e)
    if not isinstance(obj, dict):
        raise ValueError("the turn must be a JSON object")
    return obj


def problems(turn):
    """List of human-readable problems; empty when the turn is valid."""
    out = []
    role = turn.get("role")
    if role not in ROLES:
        return ["role must be one of %s" % sorted(ROLES)]
    for key in REQUIRED[role]:
        if key not in turn or turn[key] in (None, ""):
            out.append("missing field: %s" % key)
    for i, c in enumerate(turn.get("claims") or []):
        if not isinstance(c, dict) or not c.get("text"):
            out.append("claims[%d] needs text" % i)
            continue
        if c.get("kind", "fact") in FACTUAL:
            if not c.get("url") or not c.get("quote"):
                out.append("claims[%d] is factual and needs both url and a verbatim quote" % i)
            elif len(str(c["quote"]).split()) > MAX_QUOTE_WORDS:
                out.append("claims[%d] quote is longer than %d words" % (i, MAX_QUOTE_WORDS))
    if role == "draft" and "probability" in turn:
        try:
            p = float(turn["probability"])
            if not 0.02 <= p <= 0.98:
                out.append("probability must be between 0.02 and 0.98")
        except (TypeError, ValueError):
            out.append("probability must be a number")
    if role == "prosecutor" and turn.get("steelman"):
        sentences = [s for s in re.split(r"(?<=[.!?。])\s+", str(turn["steelman"]).strip()) if s]
        if len(sentences) > MAX_STEELMAN_SENTENCES:
            out.append("steelman must be %d sentences or fewer" % MAX_STEELMAN_SENTENCES)
    if role == "defender" and turn.get("steelman_check") not in (None, "") and \
            not str(turn["steelman_check"]).startswith(("faithful", "distorted")):
        out.append("steelman_check must start with 'faithful' or 'distorted'")
    return out


def check(message):
    try:
        turn = extract(message)
    except ValueError as e:
        return [str(e)]
    return problems(turn)
