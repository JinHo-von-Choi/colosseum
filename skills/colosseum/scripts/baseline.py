"""Vote baseline and pooled probability over blind drafts.

Input JSON:
  {"drafts": [{"label": "A", "family": "claude", "position": "P1", "probability": 0.8}, ...],
   "verified_counter": false}

`position` is the moderator's group id: drafts with the same meaning share an id.
`probability` is the drafter's probability that its own position is correct.

Each model family casts one vote, split equally among its members' positions when
the family is internally tied. Participants of one family share one unit of weight
in the pooled probability too, because same-family models make correlated errors.
"""
import json
import math
import sys
from collections import defaultdict

CLIP = (0.02, 0.98)
SKIP_MIN_PROBABILITY = 0.8
MAX_EXTREMIZE = 1.3


def _clip(p):
    return min(CLIP[1], max(CLIP[0], float(p)))


def _logit(p):
    return math.log(p / (1 - p))


def family_vote(drafts):
    by_family = defaultdict(list)
    for d in drafts:
        by_family[d["family"]].append(d["position"])
    tally = defaultdict(float)
    for fam, positions in by_family.items():
        counts = defaultdict(int)
        for pos in positions:
            counts[pos] += 1
        top = max(counts.values())
        winners = sorted(p for p, c in counts.items() if c == top)
        for p in winners:
            tally[p] += 1.0 / len(winners)
    ranked = sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))
    tie = len(ranked) > 1 and abs(ranked[0][1] - ranked[1][1]) < 1e-9
    return {"tally": {k: round(v, 3) for k, v in ranked},
            "winner": None if tie else ranked[0][0],
            "tie": tie,
            "families": len(by_family)}


def pooled_probability(drafts, position, a=1.0):
    """Weighted log-odds mean of each drafter's probability that `position` is correct."""
    fam_size = defaultdict(int)
    for d in drafts:
        fam_size[d["family"]] += 1
    total_w, acc = 0.0, 0.0
    for d in drafts:
        p = _clip(d["probability"])
        p_pos = p if d["position"] == position else 1 - p
        w = 1.0 / fam_size[d["family"]]
        acc += w * _logit(_clip(p_pos))
        total_w += w
    m = acc / total_w
    return 1 / (1 + math.exp(-a * m))


def baseline(doc, a=1.0):
    drafts = doc["drafts"]
    if not drafts:
        raise ValueError("no drafts")
    for d in drafts:
        for key in ("label", "family", "position", "probability"):
            if key not in d:
                raise ValueError("draft %s missing %s" % (d.get("label", "?"), key))
    vote = family_vote(drafts)
    notes = []
    same_side = len({d["position"] for d in drafts}) == 1
    if a > 1.0 and not (vote["families"] >= 2 and same_side):
        notes.append("extremizing needs 2+ families on the same side; a reset to 1.0")
        a = 1.0
    a = min(a, MAX_EXTREMIZE)
    target = vote["winner"] if vote["winner"] is not None else sorted(vote["tally"])[0]
    p0 = pooled_probability(drafts, target, a)
    homogeneous = vote["families"] < 2
    skip = (same_side and not homogeneous
            and all(float(d["probability"]) >= SKIP_MIN_PROBABILITY for d in drafts)
            and not doc.get("verified_counter", False))
    return {
        "baseline_vote": vote["winner"],
        "tie": vote["tie"],
        "tally": vote["tally"],
        "p0_position": target,
        "p0": round(p0, 3),
        "extremizing": a,
        "roster": "homogeneous" if homogeneous else "heterogeneous",
        "unanimous": same_side,
        "skip_debate": skip,
        "needs_dissenter": same_side and homogeneous,
        "notes": notes,
    }


def main(argv):
    import argparse
    p = argparse.ArgumentParser(description="Family-weighted vote and pooled probability over blind drafts.")
    p.add_argument("drafts", help="JSON file with a drafts list")
    p.add_argument("--extremize", type=float, default=1.0)
    a = p.parse_args(argv)
    try:
        with open(a.drafts, encoding="utf-8") as f:
            out = baseline(json.load(f), a.extremize)
    except (ValueError, KeyError) as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        return 2
    print(json.dumps(out, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
