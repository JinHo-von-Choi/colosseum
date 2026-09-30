"""Aggregation rules for the question-type modes. The workflows carry a JavaScript port
of these functions (colosseum-lib); tests/test_js_parity.py keeps the two in agreement.

  borda              creative mode: rank aggregation over independent ballots
  delphi_feedback    forecast mode: anonymous median and spread between Delphi rounds
  limit_move         forecast mode: cap a revision that is not backed by new checked evidence
  family_median      estimate mode: median of per-family medians
  ach                diagnostic mode: drop non-diagnostic evidence, score inconsistency
  coherent           diagnostic mode: renormalize a probability distribution over hypotheses
  log_linear_pool    diagnostic mode: family-weighted geometric pooling of distributions
"""
import math
from collections import defaultdict

MAX_UNSUPPORTED_MOVE = 0.10
ACH_WEIGHT = {"v": 1.0, "n": 0.8, "snippet": 0.5, "u": 0.0}
RELIABILITY = {"high": 0.9, "medium": 0.6, "low": 0.3}
FLOOR = 0.01


def borda(ballots):
    """ballots: list of ranked idea-id lists (best first). Points: K for first, down to 1."""
    k = max((len(b) for b in ballots), default=0)
    points, voters = defaultdict(float), defaultdict(int)
    for ballot in ballots:
        seen = set()
        for rank, idea in enumerate(ballot):
            if idea in seen:
                continue
            seen.add(idea)
            points[idea] += k - rank
            voters[idea] += 1
    order = sorted(points, key=lambda i: (-points[i], -voters[i], i))
    return [{"id": i, "points": points[i], "voters": voters[i]} for i in order]


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


def ach(hypotheses, rows):
    """rows: [{id, quote_status, reliability, ratings: {hypothesis: C|I|N}}].

    Evidence rated the same way against every hypothesis cannot tell them apart and is
    dropped. Each hypothesis is scored by the weighted count of inconsistent evidence;
    the matrix explains the ranking but does not produce the probabilities.
    """
    kept, dropped = [], []
    for r in rows:
        ratings = [r["ratings"].get(h, "N") for h in hypotheses]
        (dropped if len(set(ratings)) == 1 else kept).append(r)
    score = {}
    fragile = {}
    for h in hypotheses:
        s, weak = 0.0, 0
        for r in kept:
            if r["ratings"].get(h) == "I":
                w = ACH_WEIGHT[r["quote_status"]] * RELIABILITY[r["reliability"]]
                s += w
                if r["quote_status"] in ("snippet", "u") or r["reliability"] == "low":
                    weak += 1
        score[h] = round(s, 3)
        fragile[h] = weak
    order = sorted(hypotheses, key=lambda h: (score[h], h))
    return {"diagnostic": [r["id"] for r in kept], "dropped": [r["id"] for r in dropped],
            "inconsistency": score, "weak_inconsistencies": fragile, "least_inconsistent": order}


def coherent(dist, hypotheses):
    """Floor every hypothesis at FLOOR and renormalize so the probabilities sum to 1."""
    raw = {h: max(FLOOR, float(dist.get(h, 0.0))) for h in hypotheses}
    total = sum(raw.values())
    return {h: raw[h] / total for h in hypotheses}


def log_linear_pool(entries, hypotheses):
    """entries: [{family, dist}]. Family-weighted geometric mean of coherent distributions."""
    fam_size = defaultdict(int)
    for e in entries:
        fam_size[e["family"]] += 1
    logs = {h: 0.0 for h in hypotheses}
    total_w = 0.0
    for e in entries:
        w = 1.0 / fam_size[e["family"]]
        d = coherent(e["dist"], hypotheses)
        for h in hypotheses:
            logs[h] += w * math.log(d[h])
        total_w += w
    raw = {h: math.exp(logs[h] / total_w) for h in hypotheses}
    z = sum(raw.values())
    return {h: round(raw[h] / z, 3) for h in hypotheses}
