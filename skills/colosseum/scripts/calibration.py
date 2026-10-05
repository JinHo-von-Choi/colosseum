"""Forecast store and calibration (colosseum.forecasts/v1).

Every probability forecast Colosseum makes can be recorded; once the event resolves the
record is scored. With enough resolved forecasts the extremizing factor used for pooling
is fitted from the store instead of being guessed. The fitted value stays experimental
and P_final stays UNCALIBRATED until a time-split evaluation exists.

The store is <data>/forecasts.sqlite3, shared across sessions. Every add and resolve is
one transaction with unique forecast and event ids:
  - adding the same record twice is a no-op; the same id with different content is an error
  - resolving twice with the same outcome is a no-op; a different outcome is an error
A forecasts.jsonl log from earlier versions is imported once with `forecast import`
(backed up, checked for row count, unique ids, resolutions and hash). Until then writes
are refused so the two stores never split. `forecast export` writes JSONL.

Network file systems are not supported.
"""
import hashlib
import json
import math
import os
import re
import shutil
import sqlite3
import time
import uuid

SCHEMA = "colosseum.forecasts/v1"
MIN_RESOLVED_FOR_FIT = 20
FIT_GRID = [round(0.8 + 0.05 * i, 2) for i in range(11)]  # 0.80 .. 1.30
LOG_LOSS_EPS = 1e-6  # only reached by p of exactly 0 or 1, which add() refuses
BINS = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0)]
REQUIRED = ("id", "question", "resolution_criteria", "resolve_by", "p_final", "p0")
_SAFE = re.compile(r"[^A-Za-z0-9_.:-]")


class ForecastError(ValueError):
    pass


def db_path(data_root):
    return os.path.join(data_root, "forecasts.sqlite3")


def legacy_path(data_root):
    return os.path.join(data_root, "forecasts.jsonl")


log_path = db_path


def _connect(data_root):
    os.makedirs(data_root, mode=0o700, exist_ok=True)
    path = db_path(data_root)
    if not os.path.exists(path):
        os.close(os.open(path, os.O_WRONLY | os.O_CREAT, 0o600))
    con = sqlite3.connect(path, timeout=60, isolation_level=None)
    con.execute("PRAGMA synchronous=FULL")
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("BEGIN IMMEDIATE")
    try:
        con.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        con.execute("CREATE TABLE IF NOT EXISTS forecasts (id TEXT PRIMARY KEY, record TEXT NOT NULL, "
                    "p_final REAL NOT NULL, p0 REAL NOT NULL, outcome INTEGER, created_at TEXT NOT NULL, "
                    "resolved_at TEXT)")
        con.execute("CREATE TABLE IF NOT EXISTS events (event_id TEXT PRIMARY KEY, forecast_id TEXT NOT NULL "
                    "REFERENCES forecasts(id), kind TEXT NOT NULL, payload TEXT NOT NULL, at TEXT NOT NULL)")
        con.execute("INSERT OR IGNORE INTO meta VALUES ('schema', ?)", (SCHEMA,))
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    found = con.execute("SELECT value FROM meta WHERE key='schema'").fetchone()[0]
    if found != SCHEMA:
        con.close()
        raise ForecastError("forecast store version %s is not supported" % found)
    return con


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


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
        try:
            p = float(record[key])
        except (TypeError, ValueError):
            raise ForecastError("%s must be a number" % key)
        if not 0.0 < p < 1.0:
            raise ForecastError("%s must be strictly between 0 and 1" % key)
        record[key] = p
    record.pop("outcome", None)
    return record


def _legacy_pending(con, data_root):
    p = legacy_path(data_root)
    if not os.path.exists(p):
        return False
    return con.execute("SELECT 1 FROM meta WHERE key=?", ("imported:" + _file_hash(p),)).fetchone() is None


def _require_no_legacy(con, data_root):
    if _legacy_pending(con, data_root):
        raise ForecastError("forecasts.jsonl from an earlier version has not been imported; run `forecast import` first")


def _tx(con):
    con.execute("BEGIN IMMEDIATE")


def _add(con, record, event_id, kind="add"):
    """Insert inside an open transaction. Returns (record, created)."""
    row = con.execute("SELECT record FROM forecasts WHERE id=?", (record["id"],)).fetchone()
    if row:
        if row[0] == _canonical(record):
            return record, False
        raise ForecastError("forecast %s already logged with different content" % record["id"])
    con.execute("INSERT INTO forecasts (id, record, p_final, p0, outcome, created_at) VALUES (?, ?, ?, ?, NULL, ?)",
                (record["id"], _canonical(record), record["p_final"], record["p0"], _now()))
    con.execute("INSERT INTO events VALUES (?, ?, ?, ?, ?)",
                (event_id or uuid.uuid4().hex, record["id"], kind, _canonical(record), _now()))
    return record, True


def _resolve(con, forecast_id, outcome, event_id, kind="resolve"):
    row = con.execute("SELECT outcome FROM forecasts WHERE id=?", (forecast_id,)).fetchone()
    if not row:
        raise ForecastError("no forecast with id %s" % forecast_id)
    if row[0] is not None:
        if row[0] == outcome:
            return False
        raise ForecastError("forecast %s is already resolved as %d; refusing %d" % (forecast_id, row[0], outcome))
    con.execute("UPDATE forecasts SET outcome=?, resolved_at=? WHERE id=?", (outcome, _now(), forecast_id))
    con.execute("INSERT INTO events VALUES (?, ?, ?, ?, ?)", (event_id or uuid.uuid4().hex, forecast_id, kind,
                                                              json.dumps({"outcome": outcome}), _now()))
    return True


def add(data_root, record, event_id=None):
    record = validate(record)
    con = _connect(data_root)
    try:
        _tx(con)
        try:
            _require_no_legacy(con, data_root)
            rec, created = _add(con, record, event_id)
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
    finally:
        con.close()
    return dict(rec, created=created)


def resolve(data_root, forecast_id, outcome, event_id=None):
    if outcome not in (0, 1):
        raise ForecastError("outcome must be 0 or 1")
    con = _connect(data_root)
    try:
        _tx(con)
        try:
            _require_no_legacy(con, data_root)
            changed = _resolve(con, forecast_id, outcome, event_id)
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        row = con.execute("SELECT record, outcome FROM forecasts WHERE id=?", (forecast_id,)).fetchone()
    finally:
        con.close()
    return dict(json.loads(row[0]), outcome=row[1], changed=changed)


def load(data_root):
    if not os.path.exists(db_path(data_root)):
        return []
    con = _connect(data_root)
    try:
        rows = con.execute("SELECT record, outcome FROM forecasts ORDER BY created_at, id").fetchall()
    finally:
        con.close()
    return [dict(json.loads(r), outcome=o) for r, o in rows]


def status(data_root):
    con = _connect(data_root)
    try:
        n, done = con.execute("SELECT COUNT(*), COUNT(outcome) FROM forecasts").fetchone()
        pending = _legacy_pending(con, data_root)
    finally:
        con.close()
    return {"schema": SCHEMA, "store": db_path(data_root), "forecasts": n, "resolved": done,
            "legacy_jsonl_pending": pending}


def _file_hash(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def import_jsonl(data_root, path=None):
    """Import a forecasts.jsonl log once, inside one transaction, and verify the result."""
    path = path or legacy_path(data_root)
    digest = _file_hash(path)
    rows = []
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except ValueError as e:
                    raise ForecastError("line %d is not valid JSON: %s" % (n, e))
    resolved = {}
    records = {}
    for r in rows:
        rec = validate(r)
        if rec["id"] in records and _canonical(records[rec["id"]]) != _canonical(rec):
            raise ForecastError("the log holds two different records for %s" % rec["id"])
        records[rec["id"]] = rec
        if r.get("outcome") in (0, 1):
            if resolved.get(rec["id"], r["outcome"]) != r["outcome"]:
                raise ForecastError("the log resolves %s both ways" % rec["id"])
            resolved[rec["id"]] = r["outcome"]
    backup = "%s.bak-%s" % (path, digest[:12])
    if not os.path.exists(backup):
        shutil.copy2(path, backup)
    con = _connect(data_root)
    try:
        _tx(con)
        try:
            if con.execute("SELECT 1 FROM meta WHERE key=?", ("imported:" + digest,)).fetchone():
                con.execute("ROLLBACK")
                return {"ok": True, "already_imported": True, "sha256": digest}
            created = 0
            for fid, rec in records.items():
                created += _add(con, rec, "import:%s:%s" % (digest[:12], fid), kind="import")[1]
                if fid in resolved:
                    _resolve(con, fid, resolved[fid], "import:%s:%s:outcome" % (digest[:12], fid), kind="import")
            ids = set(records)
            found = con.execute("SELECT id, outcome FROM forecasts").fetchall()
            found_ids = {i for i, _ in found}
            if not ids <= found_ids or any(o != resolved.get(i) for i, o in found if i in resolved):
                raise ForecastError("import verification failed")
            con.execute("INSERT INTO meta VALUES (?, ?)", ("imported:" + digest, _now()))
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
    finally:
        con.close()
    return {"ok": True, "sha256": digest, "backup": backup, "rows": len(rows), "unique_ids": len(records),
            "resolved": len(resolved), "created": created}


def export_jsonl(data_root):
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in load(data_root))


def _extremize(p, a):
    p = min(1 - LOG_LOSS_EPS, max(LOG_LOSS_EPS, float(p)))
    return 1 / (1 + math.exp(-a * math.log(p / (1 - p))))


def bin_index(p):
    """Half-open bins [0, .2), [.2, .4), ..., with the last bin closed: [.8, 1.0]."""
    for i, (lo, hi) in enumerate(BINS):
        if lo <= p < hi or (i == len(BINS) - 1 and p == hi):
            return i
    raise ForecastError("probability %r is outside [0, 1]" % p)


def score(records, key="p_final", a=1.0):
    """Brier score and log loss of the stored probabilities.

    With a = 1 the stored value is scored as is (no clipping). Log loss treats a
    probability of exactly 0 or 1 with LOG_LOSS_EPS. Other a values are used only
    by fit_extremizing.
    """
    done = [r for r in records if r.get("outcome") in (0, 1)]
    if not done:
        return {"resolved": 0}
    probs = [(float(r[key]) if a == 1.0 else _extremize(r[key], a), r["outcome"]) for r in done]
    brier = sum((p - y) ** 2 for p, y in probs) / len(probs)
    logloss = -sum(math.log(max(LOG_LOSS_EPS, p if y else 1 - p)) for p, y in probs) / len(probs)
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
