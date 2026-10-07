"""Aggregation rules for the question-type modes. The workflows carry a JavaScript port
of these functions (colosseum-lib); tests/test_js_parity.py keeps the two in agreement.

  delphi_feedback    forecast mode: anonymous median and spread between Delphi rounds
  limit_move         forecast mode: cap a revision that is not backed by new checked evidence
  family_median      estimate mode: median of per-family medians
"""
import math
from collections import defaultdict

MAX_UNSUPPORTED_MOVE = 0.10


def _median(xs):
    s = sorted(xs)
    n = len(s)
    if not n:
        return None
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def delphi_feedback(estimates):
    """estimates: list of {label, value}. Anonymous statistics fed back between rounds."""
    values = [float(e["value"]) for e in estimates]
    med = _median(values)
    return {"median": med, "low": min(values), "high": max(values),
            "above": sorted(e["label"] for e in estimates if float(e["value"]) > med),
            "below": sorted(e["label"] for e in estimates if float(e["value"]) < med)}


def limit_move(previous, proposed, has_new_evidence, scale=1.0):
    """A revision larger than MAX_UNSUPPORTED_MOVE x scale needs new checked evidence."""
    cap = MAX_UNSUPPORTED_MOVE * scale
    delta = float(proposed) - float(previous)
    if has_new_evidence or abs(delta) <= cap:
        return {"value": float(proposed), "capped": False}
    return {"value": float(previous) + math.copysign(cap, delta), "capped": True}


def family_median(estimates):
    """estimates: list of {family, value}. Each family contributes its own median once."""
    by_family = defaultdict(list)
    for e in estimates:
        by_family[e["family"]].append(float(e["value"]))
    return _median([_median(v) for v in by_family.values()])
