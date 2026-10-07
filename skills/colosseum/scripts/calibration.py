"""Forecast store and calibration.

Every probability forecast Colosseum makes can be recorded; once the event resolves the
record is scored. With enough resolved forecasts the extremizing factor used for pooling
is fitted from the store instead of being guessed. The fitted value stays experimental
and P_final stays UNCALIBRATED.

The store is <data>/forecasts.sqlite3, shared across sessions, one transaction per write:
  - adding the same record twice is a no-op; the same id with different content is an error
  - resolving twice with the same outcome is a no-op; a different outcome is an error
`forecast import` reads a forecasts.jsonl log from earlier versions; `forecast export`
writes one.
"""
import json
import math
import os
import re
import sqlite3
import time

MIN_RESOLVED_FOR_FIT = 20
FIT_GRID = [round(0.8 + 0.05 * i, 2) for i in range(11)]  # 0.80 .. 1.30
BINS = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0)]
REQUIRED = ("id", "question", "resolution_criteria", "resolve_by", "p_final", "p0")
_SAFE = re.compile(r"[^A-Za-z0-9_.:-]")


class ForecastError(ValueError):
    pass


def db_path(data_root):
    return os.path.join(data_root, "forecasts.sqlite3")


log_path = db_path


def _connect(data_root):
    os.makedirs(data_root, mode=0o700, exist_ok=True)
    con = sqlite3.connect(db_path(data_root), timeout=60)
    con.execute("CREATE TABLE IF NOT EXISTS forecasts (id TEXT PRIMARY KEY, record TEXT NOT NULL, "
                "outcome INTEGER, created_at TEXT NOT NULL)")
    return con


def _canonical(record):
    return json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def validate(record):
    if not isinstance(record, dict):
        raise ForecastError("forecast record must be a JSON object")
    for key in REQUIRED:
        if key not in record:
            raise ForecastError("forecast record missing %s" % key)
    record = dict(record)
    record["id"] = _SAFE.sub("_", str(record["id"]))
    for key in ("p_final", "p0"):
        p = float(record[key])
        if not 0.0 < p < 1.0:
            raise ForecastError("%s must be strictly between 0 and 1" % key)
        record[key] = p
    record.pop("outcome", None)
    return record


def _add(con, record):
    """Insert inside the caller's transaction. Returns True if the record is new."""
    created = con.execute("INSERT OR IGNORE INTO forecasts VALUES (?, ?, NULL, ?)",
                          (record["id"], _canonical(record), time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))).rowcount
    if not created and con.execute("SELECT record FROM forecasts WHERE id=?", (record["id"],)).fetchone()[0] != _canonical(record):
        raise ForecastError("forecast %s already logged with different content" % record["id"])
    return bool(created)


def _resolve(con, forecast_id, outcome):
    row = con.execute("SELECT outcome FROM forecasts WHERE id=?", (forecast_id,)).fetchone()
    if not row:
        raise ForecastError("no forecast with id %s" % forecast_id)
    if row[0] is not None and row[0] != outcome:
        raise ForecastError("forecast %s is already resolved as %d; refusing %d" % (forecast_id, row[0], outcome))
    con.execute("UPDATE forecasts SET outcome=? WHERE id=?", (outcome, forecast_id))
    return row[0] is None


def add(data_root, record):
    record = validate(record)
    con = _connect(data_root)
    try:
        with con:
            created = _add(con, record)
    finally:
        con.close()
    return dict(record, created=created)


def resolve(data_root, forecast_id, outcome):
    if outcome not in (0, 1):
        raise ForecastError("outcome must be 0 or 1")
    con = _connect(data_root)
    try:
        with con:
            changed = _resolve(con, forecast_id, outcome)
            record = con.execute("SELECT record FROM forecasts WHERE id=?", (forecast_id,)).fetchone()[0]
    finally:
        con.close()
    return dict(json.loads(record), outcome=outcome, changed=changed)


def load(data_root):
    if not os.path.exists(db_path(data_root)):
        return []
    con = _connect(data_root)
    try:
        rows = con.execute("SELECT record, outcome FROM forecasts ORDER BY created_at, id").fetchall()
    finally:
        con.close()
    return [dict(json.loads(r), outcome=o) for r, o in rows]


def import_jsonl(data_root, path=None):
    """Add every record of a forecasts.jsonl log in one transaction; known records are skipped."""
    path = path or os.path.join(data_root, "forecasts.jsonl")
    with open(path, encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    con = _connect(data_root)
    created = resolved = 0
    try:
        with con:
            for r in rows:
                created += _add(con, validate(r))
                if r.get("outcome") in (0, 1):
                    resolved += _resolve(con, validate(r)["id"], r["outcome"])
    finally:
        con.close()
    return {"ok": True, "rows": len(rows), "created": created, "resolved": resolved}


def export_jsonl(data_root):
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in load(data_root))


def _extremize(p, a):
    p = float(p)
    return 1 / (1 + math.exp(-a * math.log(p / (1 - p))))


def bin_index(p):
    """Half-open bins [0, .2), [.2, .4), ..., with the last bin closed: [.8, 1.0]."""
    return min(int(p * len(BINS)), len(BINS) - 1)


def score(records, key="p_final", a=1.0):
    """Brier score and log loss of the stored probabilities.

    With a = 1 the stored value is scored as is. Other a values are used only by
    fit_extremizing.
    """
    done = [r for r in records if r.get("outcome") in (0, 1)]
    if not done:
        return {"resolved": 0}
    probs = [(float(r[key]) if a == 1.0 else _extremize(r[key], a), r["outcome"]) for r in done]
    brier = sum((p - y) ** 2 for p, y in probs) / len(probs)
    logloss = -sum(math.log(p if y else 1 - p) for p, y in probs) / len(probs)
    groups = [[] for _ in BINS]
    for p, y in probs:
        groups[bin_index(p)].append((p, y))
    bins = [{"range": list(BINS[i]), "closed": "[]" if i == len(BINS) - 1 else "[)", "n": len(g),
             "mean_forecast": round(sum(p for p, _ in g) / len(g), 3),
             "observed": round(sum(y for _, y in g) / len(g), 3)} for i, g in enumerate(groups) if g]
    return {"resolved": len(done), "brier": round(brier, 4), "log_loss": round(logloss, 4), "bins": bins,
            "calibration": "UNCALIBRATED"}


def fit_extremizing(records):
    """Extremizing factor for the pooled baseline P0 that minimizes log loss on resolved
    forecasts. Experimental: it is fitted in-sample, not on a time split."""
    done = [r for r in records if r.get("outcome") in (0, 1)]
    if len(done) < MIN_RESOLVED_FOR_FIT:
        return {"a": 1.0, "fitted": False, "resolved": len(done), "experimental": True,
                "note": "needs %d resolved forecasts; keeping a = 1.0" % MIN_RESOLVED_FOR_FIT}
    best = min(FIT_GRID, key=lambda a: (score(done, "p0", a)["log_loss"], abs(a - 1.0)))
    return {"a": best, "fitted": True, "resolved": len(done), "experimental": True,
            "note": "in-sample fit; P_final stays UNCALIBRATED until a time-split evaluation",
            "log_loss_at_1": score(done, "p0", 1.0)["log_loss"], "log_loss_at_fit": score(done, "p0", best)["log_loss"]}
