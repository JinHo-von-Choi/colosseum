"""Evidence-quality checklist for the final answer.

Input: an argument graph (see graph.py) with an extra list

  "final": [{"claim": "A1", "weight": 3}, ...]

naming the factual claims kept in the final answer. Weight 3 marks a claim that
decides the answer, 2 a supporting fact, 1 a peripheral detail.

No single weighted score is produced; each component is reported on its own.
"""
import json
import sys
from collections import defaultdict

try:
    from . import graph as G
except ImportError:
    import graph as G

CORROBORATION_TARGET = 2


def _checked(e, level):
    ok = {"v"} if level == "quote" else {"v", "snippet"}
    return e["quote_status"] in ok and G.eligible(e)


def checklist(doc, high_stakes=False):
    G.validate(doc)
    ev = {e["id"]: e for e in doc["evidence"]}
    claims = {c["id"]: c for c in doc["claims"]}
    final = doc.get("final", [])
    for f in final:
        if f["claim"] not in claims:
            raise G.GraphError("final references unknown claim %s" % f["claim"])

    target = CORROBORATION_TARGET + (1 if high_stakes else 0)
    rows = {"decisive": [0, 0, 0], "supporting": [0, 0, 0]}  # quote-verified, snippet-only, total
    corroboration, unverified, review, quality = {}, [], [], defaultdict(int)
    for f in final:
        c = claims[f["claim"]]
        if c.get("kind", "fact") in G.VALUE_KINDS:
            continue
        cited = [ev[eid] for eid in c.get("evidence", [])]
        bucket = "decisive" if f.get("weight", 1) >= 3 else "supporting"
        rows[bucket][2] += 1
        if any(_checked(e, "quote") for e in cited):
            rows[bucket][0] += 1
        elif any(_checked(e, "snippet") for e in cited):
            rows[bucket][1] += 1
        for e in cited:
            quality[e["reliability"]] += 1
            if e["quote_status"] == "u":
                unverified.append(e["id"])
            elif e["quote_status"] == "n":
                review.append(e["id"])
        if bucket == "decisive":
            origins = {G.origin_of(e) for e in cited if _checked(e, "snippet")}
            corroboration[c["id"]] = len(origins)

    cited_by = defaultdict(set)
    for c in doc["claims"]:
        for eid in c.get("evidence", []):
            cited_by[G.origin_of(ev[eid])].add(c.get("author", "?"))
    shared = sum(1 for authors in cited_by.values() if len(authors) >= 2)
    diversity = round(1 - shared / len(cited_by), 3) if cited_by else None

    def rate(r):
        return {"quote_verified": r[0], "snippet_only": r[1], "total": r[2]}

    return {
        "verification": {"decisive": rate(rows["decisive"]), "supporting": rate(rows["supporting"])},
        "source_quality": {k: quality.get(k, 0) for k in ("high", "medium", "low")},
        "corroboration": {"target": target, "per_decisive_claim": corroboration,
                          "below_target": sorted(k for k, v in corroboration.items() if v < target)},
        "origin_diversity": diversity,
        "unverified_quotes": sorted(set(unverified)),
        "review_required": sorted(set(review)),
    }


def main(argv):
    import argparse
    p = argparse.ArgumentParser(description="Evidence-quality checklist for a Colosseum final answer.")
    p.add_argument("graph")
    p.add_argument("--high-stakes", action="store_true")
    a = p.parse_args(argv)
    try:
        with open(a.graph, encoding="utf-8") as f:
            out = checklist(json.load(f), a.high_stakes)
    except (G.GraphError, ValueError, KeyError) as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        return 2
    print(json.dumps(out, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
