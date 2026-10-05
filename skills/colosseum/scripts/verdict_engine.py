"""Deterministic verdicts over an argument graph.

1. Base score of each claim from its evidence (graph.base_score).
2. Attacks become defeats. An undercut backed by checked evidence always defeats;
   every other attack (rebut, undermine, or an undercut without checked evidence)
   is blocked when the target's base score exceeds the attacker's by MARGIN.
3. Grounded labelling (IN / OUT / UNDEC) over the defeats.
4. Preferred and stable extensions over the UNDEC part, for conditional answers.
5. DF-QuAD strengths (damped), with a convergence flag.

Same input, same output: the result carries a hash of the canonical input.
Standard library only.
"""
import hashlib
import itertools
import json
import sys

try:
    from . import graph as G
except ImportError:
    import graph as G

MARGIN = 0.15
THETA = 0.5
MAX_UNDEC = 16


def build(doc):
    ev = {e["id"]: e for e in doc["evidence"]}
    nodes = {c["id"]: c for c in doc["claims"] if c.get("status", "active") == "active"}
    tau = {n: G.base_score(c, ev) for n, c in nodes.items()}
    relations = G.dedupe_relations(doc["relations"])
    att = [r for r in relations if r["type"] == "attack" and r["from"] in nodes and r["to"] in nodes]
    sup = [r for r in relations if r["type"] == "support" and r["from"] in nodes and r["to"] in nodes]
    defeats = set()
    demoted = []
    for r in att:
        a, b = r["from"], r["to"]
        unconditional = r["subtype"] == "undercut" and G.has_checked_evidence(nodes[a], ev)
        if r["subtype"] == "undercut" and not unconditional:
            demoted.append((a, b))
        if unconditional or not (tau[b] > tau[a] + MARGIN):
            defeats.add((a, b))
    return nodes, tau, defeats, att, sup, sorted(demoted)


def grounded(nodes, defeats):
    attackers = {n: {a for (a, b) in defeats if b == n} for n in nodes}
    lab = {}
    changed = True
    while changed:
        changed = False
        for n in sorted(nodes):
            if n in lab:
                continue
            if all(lab.get(a) == "OUT" for a in attackers[n]):
                lab[n] = "IN"
                changed = True
            elif any(lab.get(a) == "IN" for a in attackers[n]):
                lab[n] = "OUT"
                changed = True
    return {n: lab.get(n, "UNDEC") for n in nodes}


def preferred_and_stable(nodes, defeats, lab):
    grounded_in = {n for n, l in lab.items() if l == "IN"}
    undec = sorted(n for n, l in lab.items() if l == "UNDEC")
    if len(undec) > MAX_UNDEC:
        return None, None
    attackers = {n: {a for (a, b) in defeats if b == n} for n in nodes}

    def conflict_free(S):
        return not any((a, b) in defeats for a in S for b in S)

    def defended(S):
        return all(any((d, x) in defeats for d in S) for n in S for x in attackers[n])

    admissible = []
    for k in range(len(undec) + 1):
        for extra in itertools.combinations(undec, k):
            S = grounded_in | set(extra)
            if conflict_free(S) and defended(S):
                admissible.append(frozenset(S))
    preferred = [S for S in admissible if not any(S < T for T in admissible)]
    stable = [S for S in preferred if all(any((d, x) in defeats for d in S) for x in nodes if x not in S)]
    return sorted(sorted(S) for S in set(preferred)), sorted(sorted(S) for S in set(stable))


def dfquad(nodes, tau, att, sup, iters=500, damping=0.5, eps=1e-9):
    s = dict(tau)
    atk = {n: sorted(r["from"] for r in att if r["to"] == n) for n in nodes}
    spt = {n: sorted(r["from"] for r in sup if r["to"] == n) for n in nodes}

    def agg(vals):
        p = 1.0
        for v in vals:
            p *= 1.0 - v
        return 1.0 - p

    for _ in range(iters):
        new = {}
        for n in sorted(nodes):
            va, vs, v0 = agg(s[a] for a in atk[n]), agg(s[x] for x in spt[n]), tau[n]
            c = v0 - v0 * (va - vs) if va >= vs else v0 + (1 - v0) * (vs - va)
            new[n] = (1 - damping) * s[n] + damping * c
        delta = max((abs(new[n] - s[n]) for n in nodes), default=0.0)
        s = new
        if delta < eps:
            return s, True
    return s, False


def claim_status(label, strength, converged, theta):
    if label == "OUT":
        return "REJECTED"
    if label == "UNDEC":
        return "UNDECIDED"
    if not converged:
        return "IN_UNPROVEN"
    return "ACCEPTED" if strength >= theta else "IN_UNPROVEN"


def rule(doc, a, b, nodes, st, pref):
    kinds = {nodes[x].get("kind", "fact") for x in (a, b) if x in nodes}
    if kinds & G.VALUE_KINDS:
        return "VALUE_CONDITIONAL"
    sa, sb = st.get(a, "WITHDRAWN"), st.get(b, "WITHDRAWN")
    if sa == "ACCEPTED" and sb != "ACCEPTED":
        return "A_WINS"
    if sb == "ACCEPTED" and sa != "ACCEPTED":
        return "B_WINS"
    if sa == sb == "ACCEPTED":
        return "PARTIAL_BOTH_SURVIVE"
    if "UNDECIDED" in (sa, sb):
        credulous = lambda x: pref is not None and any(x in S for S in pref)
        return "CONDITIONAL" if credulous(a) and credulous(b) else "UNRESOLVED"
    if {sa, sb} == {"REJECTED", "IN_UNPROVEN"}:
        return "LOSER_REFUTED_WINNER_UNPROVEN"
    return "NEITHER_ESTABLISHED"


def verdict(doc, theta=THETA):
    G.validate(doc)
    nodes, tau, defeats, att, sup, demoted = build(doc)
    lab = grounded(nodes, defeats)
    pref, stable = preferred_and_stable(nodes, defeats, lab)
    strength, converged = dfquad(nodes, tau, att, sup)
    st = {n: claim_status(lab[n], strength[n], converged, theta) for n in nodes}
    canonical = json.dumps(doc, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    out = {
        "input_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16],
        "policy": G.POLICY_VERSION,
        "theta": theta,
        "labels": dict(sorted(lab.items())),
        "status": dict(sorted(st.items())),
        "base": {k: round(tau[k], 3) for k in sorted(tau)},
        "strength": {k: round(strength[k], 3) for k in sorted(strength)},
        "qbaf_converged": converged,
        "defeats": [list(d) for d in sorted(defeats)],
        "blocked_attacks": sorted([r["from"], r["to"]] for r in att if (r["from"], r["to"]) not in defeats),
        "demoted_undercuts": [list(d) for d in demoted],
        "preferred": pref,
        "stable": stable,
        "why": {n: sorted(a for (a, b) in defeats if b == n and lab[a] == ("IN" if lab[n] == "OUT" else "UNDEC"))
                for n in sorted(nodes) if lab[n] != "IN"},
        "conflicts": [],
    }
    for cf in doc.get("conflicts", []):
        a, b = cf["a"], cf["b"]
        lean = round(strength[a] - strength[b], 3) if a in nodes and b in nodes else None
        out["conflicts"].append({"a": a, "b": b, "verdict": rule(doc, a, b, nodes, st, pref),
                                 "status": [st.get(a, "WITHDRAWN"), st.get(b, "WITHDRAWN")], "lean": lean})
    return out


def main(argv):
    import argparse
    p = argparse.ArgumentParser(description="Compute verdicts for a Colosseum argument graph.")
    p.add_argument("graph")
    p.add_argument("--theta", type=float, default=THETA, help="proof standard on strength (0.7 for high stakes)")
    args = p.parse_args(argv)
    try:
        doc = G.load(args.graph)
    except (G.GraphError, ValueError) as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        return 2
    print(json.dumps(verdict(doc, args.theta), indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
