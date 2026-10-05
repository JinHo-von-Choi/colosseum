"""Argument graph format (colosseum.arggraph/v2): validation and evidence scoring.

A graph is a JSON object with four lists (see references/contract.md):

  evidence : {id, url, quote, reliability, quote_status, support, freshness?, origin?, ...}
  claims   : {id, author, text, kind?, evidence: [evidence ids], status?}
  relations: {id?, type: attack|support, subtype?: rebut|undercut|undermine, from, to}
  conflicts: {a, b}  (optional; pairs of claim ids to rule on)

One evidence record binds one quote to one claim: its support is the assessment of
that quote for that claim only. Graphs without "schema" are read as v1; the scoring
policy below applies to both.
"""
import json
from urllib.parse import urlsplit

SCHEMA = "colosseum.arggraph/v2"
POLICY_VERSION = "evidence-policy/2"

RELIABILITY = {"high": 0.9, "medium": 0.6, "low": 0.3}
# n means "review required" (near match, or a verbatim span that drops a qualifier);
# it carries no weight until a person upgrades it.
QUOTE = {"v": 1.0, "snippet": 0.5, "n": 0.0, "u": 0.0}
SUPPORT = {"full": 1.0, "partial": 0.5, "none": 0.0, "unknown": 0.0}
# unknown: nobody could tell how current the source is; it is never assumed fresh.
FRESHNESS = {"fresh": 1.0, "na": 1.0, "unknown": 0.75, "stale": 0.5, "superseded": 0.0}
CLAIM_STATUS = {"active", "withdrawn"}

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

    _require(doc.get("schema", SCHEMA) in ("colosseum.arggraph/v1", SCHEMA), "unknown graph schema %s" % doc.get("schema"))
    ev_ids = set()
    for e in doc["evidence"]:
        _require(isinstance(e, dict), "evidence must be an object")
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
        _require(isinstance(c, dict), "claim must be an object")
        cid = c.get("id")
        _require(isinstance(cid, str) and cid, "claim without id")
        _require(cid not in claim_ids, "duplicate claim id: %s" % cid)
        claim_ids.add(cid)
        _require(c.get("kind", "fact") in CLAIM_KINDS, "%s: kind must be one of %s" % (cid, sorted(CLAIM_KINDS)))
        _require(c.get("status", "active") in CLAIM_STATUS, "%s: status must be one of %s" % (cid, sorted(CLAIM_STATUS)))
        _require(isinstance(c.get("evidence", []), list), "%s: evidence must be a list" % cid)
        for eid in c.get("evidence", []):
            _require(eid in ev_ids, "%s cites unknown evidence %s" % (cid, eid))

    for r in doc["relations"]:
        _require(isinstance(r, dict), "relation must be an object")
        _require(r.get("type") in ("attack", "support"), "relation type must be attack or support")
        _require(r.get("from") in claim_ids and r.get("to") in claim_ids,
                 "relation %s -> %s references an unknown claim" % (r.get("from"), r.get("to")))
        _require(r["from"] != r["to"], "self-relation on %s" % r["from"])
        if r["type"] == "attack":
            _require(r.get("subtype") in SUBTYPES, "attack %s -> %s needs subtype in %s" % (r["from"], r["to"], sorted(SUBTYPES)))

    for cf in doc.get("conflicts", []):
        _require(isinstance(cf, dict), "conflict must be an object")
        _require(cf.get("a") in claim_ids and cf.get("b") in claim_ids, "conflict references an unknown claim")
    return doc


def load(path):
    with open(path, encoding="utf-8") as f:
        return validate(json.load(f))


def normalize_url(url):
    """Canonical URL: lowercase scheme and host, IDNA (punycode) host, no default port,
    no fragment, no trailing dot on the host. Mirrors normalizeUrl in the workflows.

    This is string canonicalization only; it says nothing about whether two pages are
    independent sources (that is origin_of's job, and a declared origin wins).
    """
    try:
        parts = urlsplit(str(url or "").strip())
        host = parts.hostname or ""
        port = parts.port
    except ValueError:
        return ""
    if parts.scheme.lower() not in ("http", "https") or not host:
        return ""
    host = host.rstrip(".")
    try:
        host = ".".join(label.encode("idna").decode("ascii") if not label.isascii() else label
                        for label in host.split("."))
    except UnicodeError:
        return ""
    scheme = parts.scheme.lower()
    netloc = host if port in (None, {"http": 80, "https": 443}[scheme]) else "%s:%d" % (host, port)
    path = parts.path or "/"
    return "%s://%s%s%s" % (scheme, netloc, path, "?" + parts.query if parts.query else "")


def origin_of(e):
    """Origin cluster of a piece of evidence.

    Uses the declared origin; otherwise the URL host; otherwise one shared unknown
    cluster. Copies of the same story must never count as independent sources, so
    a missing field collapses sources together instead of splitting them apart.
    """
    if e.get("origin"):
        return str(e["origin"])
    url = normalize_url(e.get("url"))
    host = url.split("://", 1)[1].split("/", 1)[0].split(":", 1)[0] if url else ""
    if host.startswith("www."):
        host = host[4:]
    return "host:" + host if host else "unknown"


def eligible(e):
    """Whether a piece of evidence can carry weight or count as checked.

    One rule for scoring and for the undercut exception: the quote was found verbatim
    (or in a snippet in snippet-level mode), the support assessment for this claim is
    full or partial, and the source is not superseded.
    """
    return (QUOTE[e["quote_status"]] > 0 and e["support"] in ("full", "partial")
            and e.get("freshness", "na") != "superseded")


def evidence_score(e):
    if not eligible(e):
        return 0.0
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
    """True if the claim cites at least one eligible piece of evidence."""
    return any(eligible(evidence_by_id[eid]) for eid in claim.get("evidence", []))


def relation_key(r):
    return (r["type"], r.get("subtype") or "", r["from"], r["to"])


def dedupe_relations(relations):
    """Drop repeated relations. Submitting the same attack twice must not change any result;
    an independent attack comes from a different claim and so has a different key."""
    seen, out = set(), []
    for r in relations:
        k = relation_key(r)
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out
