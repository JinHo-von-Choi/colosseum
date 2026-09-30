"""Forecast log and calibration.

Every probability forecast Colosseum makes can be recorded; once the event resolves the
record is scored. With enough resolved forecasts the extremizing factor used for pooling
is fitted from the log instead of being guessed.

The log lives at <data>/forecasts.jsonl (shared across sessions, one JSON object per line).
"""
import json
import math
import os
import re

MIN_RESOLVED_FOR_FIT = 20
FIT_GRID = [round(0.8 + 0.05 * i, 2) for i in range(11)]  # 0.80 .. 1.30
CLIP = (0.02, 0.98)
_SAFE = re.compile(r"[^A-Za-z0-9_.:-]")


def log_path(data_root):
    return os.path.join(data_root, "forecasts.jsonl")


def load(data_root):
    p = log_path(data_root)
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _write_all(data_root, records):
    os.makedirs(data_root, exist_ok=True)
    tmp = log_path(data_root) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, log_path(data_root))


def add(data_root, record):
    for key in ("id", "question", "resolution_criteria", "resolve_by", "p_final", "p0"):
        if key not in record:
            raise ValueError("forecast record missing %s" % key)
    record = dict(record)
    record["id"] = _SAFE.sub("_", str(record["id"]))
    for key in ("p_final", "p0"):
        p = float(record[key])
        if not 0.0 < p < 1.0:
            raise ValueError("%s must be strictly between 0 and 1" % key)
    records = load(data_root)
    if any(r["id"] == record["id"] for r in records):
        raise ValueError("forecast %s already logged" % record["id"])
    record.setdefault("outcome", None)
    records.append(record)
    _write_all(data_root, records)
    return record


def resolve(data_root, forecast_id, outcome):
    if outcome not in (0, 1):
        raise ValueError("outcome must be 0 or 1")
    records = load(data_root)
    for r in records:
        if r["id"] == forecast_id:
            r["outcome"] = outcome
            _write_all(data_root, records)
            return r
    raise ValueError("no forecast with id %s" % forecast_id)


def _clip(p):
    return min(CLIP[1], max(CLIP[0], float(p)))


def _extremize(p, a):
    p = _clip(p)
    lo = a * math.log(p / (1 - p))
    return 1 / (1 + math.exp(-lo))


def score(records, key="p_final", a=1.0):
    done = [r for r in records if r.get("outcome") in (0, 1)]
    if not done:
        return {"resolved": 0}
    brier = sum((_extremize(r[key], a) - r["outcome"]) ** 2 for r in done) / len(done)
    logloss = -sum(math.log(_extremize(r[key], a)) if r["outcome"] else math.log(1 - _extremize(r[key], a))
                   for r in done) / len(done)
    bins = []
    for lo in (0.0, 0.2, 0.4, 0.6, 0.8):
        hi = lo + 0.2
        inside = [r for r in done if lo <= _extremize(r[key], a) < hi or (hi == 1.0 and _extremize(r[key], a) == 1.0)]
        if inside:
            bins.append({"range": [round(lo, 1), round(hi, 1)], "n": len(inside),
                         "mean_forecast": round(sum(_extremize(r[key], a) for r in inside) / len(inside), 3),
                         "observed": round(sum(r["outcome"] for r in inside) / len(inside), 3)})
    return {"resolved": len(done), "brier": round(brier, 4), "log_loss": round(logloss, 4), "bins": bins}


def fit_extremizing(records):
    """Extremizing factor for the pooled baseline P0 that minimizes log loss on resolved forecasts."""
    done = [r for r in records if r.get("outcome") in (0, 1)]
    if len(done) < MIN_RESOLVED_FOR_FIT:
        return {"a": 1.0, "fitted": False, "resolved": len(done),
                "note": "needs %d resolved forecasts; keeping a = 1.0" % MIN_RESOLVED_FOR_FIT}
    best = min(FIT_GRID, key=lambda a: (score(done, "p0", a)["log_loss"], abs(a - 1.0)))
    return {"a": best, "fitted": True, "resolved": len(done),
            "log_loss_at_1": score(done, "p0", 1.0)["log_loss"], "log_loss_at_fit": score(done, "p0", best)["log_loss"]}
