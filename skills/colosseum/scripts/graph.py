"""Argument graph format (colosseum.arggraph/v1): validation and evidence scoring.

A graph is a JSON object with four lists:

  evidence : {id, url, quote, reliability, quote_status, support, freshness?, origin?}
  claims   : {id, author, text, kind?, evidence: [evidence ids], status?}
  relations: {id?, type: attack|support, subtype?: rebut|undercut|undermine, from, to}
  conflicts: {a, b}  (optional; pairs of claim ids to rule on)
"""
import json
from urllib.parse import urlparse

RELIABILITY = {"high": 0.9, "medium": 0.6, "low": 0.3}
QUOTE = {"v": 1.0, "n": 0.8, "snippet": 0.5, "u": 0.0}
SUPPORT = {"full": 1.0, "partial": 0.5, "none": 0.0}
FRESHNESS = {"fresh": 1.0, "na": 1.0, "stale": 0.5, "superseded": 0.0}

CLAIM_KINDS = {"fact", "statistic", "causal", "forecast", "value", "recommendation"}
VALUE_KINDS = {"value", "recommendation"}
SUBTYPES = {"rebut", "undercut", "undermine"}

# Probability that a claim with no evidence at all is true. Evidence is combined
# with this prior by noisy-OR, so citing weak evidence never scores below citing none.
NO_EVIDENCE_PRIOR = 0.2


class GraphError(ValueError):
    pass


def _require(cond, msg):
    if not cond:
        raise GraphError(msg)


def validate(doc):
    """Raise GraphError on the first structural problem; return the doc unchanged."""
    _require(isinstance(doc, dict), "graph must be a JSON object")
    for key in ("evidence", "claims", "relations"):
        _require(isinstance(doc.get(key), list), "missing list: %s" % key)

    ev_ids = set()
    for e in doc["evidence"]:
        eid = e.get("id")
        _require(isinstance(eid, str) and eid, "evidence without id")
        _require(eid not in ev_ids, "duplicate evidence id: %s" % eid)
        ev_ids.add(eid)
        _require(e.get("reliability") in RELIABILITY, "%s: reliability must be one of %s" % (eid, sorted(RELIABILITY)))
        _require(e.get("quote_status") in QUOTE, "%s: quote_status must be one of %s" % (eid, sorted(QUOTE)))
        _require(e.get("support") in SUPPORT, "%s: support must be one of %s" % (eid, sorted(SUPPORT)))
        _require(e.get("freshness", "na") in FRESHNESS, "%s: freshness must be one of %s" % (eid, sorted(FRESHNESS)))

    claim_ids = set()
    for c in doc["claims"]:
        cid = c.get("id")
        _require(isinstance(cid, str) and cid, "claim without id")
        _require(cid not in claim_ids, "duplicate claim id: %s" % cid)
        claim_ids.add(cid)
        _require(c.get("kind", "fact") in CLAIM_KINDS, "%s: kind must be one of %s" % (cid, sorted(CLAIM_KINDS)))
        for eid in c.get("evidence", []):
            _require(eid in ev_ids, "%s cites unknown evidence %s" % (cid, eid))

    for r in doc["relations"]:
        _require(r.get("type") in ("attack", "support"), "relation type must be attack or support")
        _require(r.get("from") in claim_ids and r.get("to") in claim_ids,
                 "relation %s -> %s references an unknown claim" % (r.get("from"), r.get("to")))
        _require(r["from"] != r["to"], "self-relation on %s" % r["from"])
        if r["type"] == "attack":
            _require(r.get("subtype") in SUBTYPES, "attack %s -> %s needs subtype in %s" % (r["from"], r["to"], sorted(SUBTYPES)))

    for cf in doc.get("conflicts", []):
        _require(cf.get("a") in claim_ids and cf.get("b") in claim_ids, "conflict references an unknown claim")
    return doc


def load(path):
    with open(path, encoding="utf-8") as f:
        return validate(json.load(f))


def origin_of(e):
    """Origin cluster of a piece of evidence.

    Uses the declared origin; otherwise the URL host; otherwise one shared unknown
    cluster. Copies of the same story must never count as independent sources, so
    a missing field collapses sources together instead of splitting them apart.
    """
    if e.get("origin"):
        return str(e["origin"])
    host = urlparse(e.get("url") or "").hostname or ""
    if host.startswith("www."):
        host = host[4:]
    return "host:" + host if host else "unknown"


def evidence_score(e):
    return (RELIABILITY[e["reliability"]] * QUOTE[e["quote_status"]]
            * SUPPORT[e["support"]] * FRESHNESS[e.get("freshness", "na")])


def base_score(claim, evidence_by_id):
    """Noisy-OR of the no-evidence prior and the best evidence of each origin cluster."""
    best = {}
    for eid in claim.get("evidence", []):
        e = evidence_by_id[eid]
        g = origin_of(e)
        best[g] = max(best.get(g, 0.0), evidence_score(e))
    miss = 1.0 - NO_EVIDENCE_PRIOR
    for s in best.values():
        miss *= 1.0 - s
    return 1.0 - miss


def has_checked_evidence(claim, evidence_by_id):
    """True if the claim cites at least one quote that was found on the page or in a snippet."""
    return any(evidence_by_id[eid]["quote_status"] != "u" and evidence_by_id[eid]["support"] != "none"
               for eid in claim.get("evidence", []))
