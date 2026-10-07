"""Decision records and what-if recomputation over a fixed argument graph.

whatif(doc, exclude_evidence=..., unprove_claim=...)
    Recompute the verdicts with one piece of evidence removed, or one claim stripped of
    its evidence (unproven), without calling any model. Reports which claim statuses and
    conflict verdicts changed, which did not, and the defeats through which each change
    propagated. Only one change at a time.

sensitivity(doc)
    Recompute with the defeat margin and the proof standard nudged by +/-0.05. A conflict
    whose verdict moves is marked sensitive. No stability percentage is produced.

record(result, status)
    Build a decision record (colosseum.decision/v1) from a colosseum:debate result
    ({"data", "graph", "verdict"}): JSON plus a Markdown ADR rendered from that JSON only.
    The person deciding sets the status; the record never claims a decision was made.
"""
import copy
import json
import sys

try:
    from . import graph as G
    from . import verdict_engine as V
except ImportError:
    import graph as G
    import verdict_engine as V

SCHEMA = "colosseum.decision/v1"
STATUSES = ("proposed", "accepted", "rejected", "deferred", "needs-experiment")
UNSETTLED = {"CONDITIONAL", "UNRESOLVED", "NEITHER_ESTABLISHED", "LOSER_REFUTED_WINNER_UNPROVEN", "VALUE_CONDITIONAL"}
NUDGE = 0.05


def _apply(doc, exclude_evidence=None, unprove_claim=None):
    if bool(exclude_evidence) == bool(unprove_claim):
        raise ValueError("give exactly one of exclude_evidence or unprove_claim")
    new = copy.deepcopy(doc)
    ev_ids = {e["id"] for e in new["evidence"]}
    claim_ids = {c["id"] for c in new["claims"]}
    seeds = []
    if exclude_evidence:
        if exclude_evidence not in ev_ids:
            raise ValueError("unknown evidence %s" % exclude_evidence)
        for c in new["claims"]:
            if exclude_evidence in c.get("evidence", []):
                c["evidence"] = [e for e in c["evidence"] if e != exclude_evidence]
                seeds.append(c["id"])
    else:
        if unprove_claim not in claim_ids:
            raise ValueError("unknown claim %s" % unprove_claim)
        for c in new["claims"]:
            if c["id"] == unprove_claim:
                c["evidence"] = []
        seeds.append(unprove_claim)
    return new, seeds


def _paths(doc, seeds, targets):
    """Shortest relation path from a changed seed to each target claim."""
    out_edges = {}
    for r in G.dedupe_relations(doc["relations"]):
        out_edges.setdefault(r["from"], []).append((r["to"], r["type"] if r["type"] == "support" else r.get("subtype")))
    prev = {s: None for s in seeds}
    queue = list(seeds)
    while queue:
        n = queue.pop(0)
        for m, kind in sorted(out_edges.get(n, [])):
            if m not in prev:
                prev[m] = (n, kind)
                queue.append(m)
    paths = {}
    for t in targets:
        if t not in prev:
            paths[t] = None
            continue
        steps, cur = [], t
        while prev[cur] is not None:
            src, kind = prev[cur]
            steps.append("%s -%s-> %s" % (src, kind, cur))
            cur = src
        paths[t] = list(reversed(steps)) or ["%s (changed directly)" % t]
    return paths


def whatif(doc, exclude_evidence=None, unprove_claim=None, theta=V.THETA):
    G.validate(doc)
    before = V.verdict(doc, theta)
    new, seeds = _apply(doc, exclude_evidence, unprove_claim)
    after = V.verdict(new, theta)
    changed_claims = sorted(n for n in before["status"] if before["status"][n] != after["status"].get(n))
    moved_base = sorted(n for n in before["base"] if before["base"][n] != after["base"].get(n))
    paths = _paths(doc, seeds, changed_claims)
    d_before = {tuple(d) for d in before["defeats"]}
    d_after = {tuple(d) for d in after["defeats"]}
    conflicts = []
    for b, a in zip(before["conflicts"], after["conflicts"]):
        conflicts.append({"a": b["a"], "b": b["b"], "before": b["verdict"], "after": a["verdict"],
                          "changed": b["verdict"] != a["verdict"]})
    return {
        "change": {"exclude_evidence": exclude_evidence} if exclude_evidence else {"unprove_claim": unprove_claim},
        "policy": G.POLICY_VERSION,
        "note": "recomputed on the fixed graph; this is a dependency check, not a prediction about the world",
        "base_changed": {n: [before["base"][n], after["base"].get(n)] for n in moved_base},
        "claims_changed": [{"claim": n, "before": before["status"][n], "after": after["status"].get(n),
                            "strength": [before["strength"][n], after["strength"].get(n)], "via": paths[n]}
                           for n in changed_claims],
        "claims_unchanged": len(before["status"]) - len(changed_claims),
        "defeats_added": sorted(map(list, d_after - d_before)),
        "defeats_removed": sorted(map(list, d_before - d_after)),
        "conflicts": conflicts,
        "conflicts_changed": sum(c["changed"] for c in conflicts),
    }


def sensitivity(doc, theta=V.THETA):
    base = V.verdict(doc, theta)
    variants = {"margin-": (theta, V.MARGIN - NUDGE), "margin+": (theta, V.MARGIN + NUDGE),
                "theta-": (theta - NUDGE, V.MARGIN), "theta+": (theta + NUDGE, V.MARGIN)}
    moved = {}
    for name, (t, m) in variants.items():
        v = V.verdict(doc, t, m)
        for k, (c0, c1) in enumerate(zip(base["conflicts"], v["conflicts"])):
            if c0["verdict"] != c1["verdict"]:
                moved.setdefault(k, []).append("%s: %s" % (name, c1["verdict"]))
    return {"sensitive": bool(moved),
            "conflicts": [{"a": c["a"], "b": c["b"], "verdict": c["verdict"], "moves_under": moved.get(k, [])}
                          for k, c in enumerate(base["conflicts"])]}


def _evidence_view(e):
    return {"id": e["id"], "url": e.get("url"), "quote": e.get("quote"), "check": e["quote_status"],
            "acquisition": e.get("acquisition"), "support": e["support"], "reliability": e["reliability"],
            "eligible": G.eligible(e)}


def record(result, status="proposed", theta=None):
    if status not in STATUSES:
        raise ValueError("status must be one of %s" % ", ".join(STATUSES))
    data, doc = result.get("data") or {}, result.get("graph")
    if not doc:
        raise ValueError("the input needs the workflow result's graph")
    G.validate(doc)
    theta = theta if theta is not None else (0.7 if data.get("stakes") == "high" else V.THETA)
    v = V.verdict(doc, theta)
    ev = {e["id"]: e for e in doc["evidence"]}
    claims = {c["id"]: c for c in doc["claims"]}
    position_of = {d["label"]: d.get("position_group") for d in data.get("drafts", [])}
    final_pos = data.get("final_position")

    final = sorted(doc.get("final", []), key=lambda f: (-f.get("weight", 1), -v["strength"].get(f["claim"], 0), f["claim"]))
    # Copies of one source count once, here as in the scores.
    decisive, used = [], set()
    for f in final:
        c = claims[f["claim"]]
        fresh = [ev[e] for e in c.get("evidence", []) if G.eligible(ev[e]) and G.origin_of(ev[e]) not in used]
        good = [_evidence_view(e) for e in fresh]
        if good and v["status"].get(c["id"]) in ("ACCEPTED", "IN_UNPROVEN"):
            used.update(G.origin_of(e) for e in fresh)
            decisive.append({"claim": c["id"], "text": c.get("text"), "status": v["status"][c["id"]],
                             "strength": v["strength"][c["id"]], "evidence": good})
        if len(decisive) == 3:
            break

    counters = []
    for cf in v["conflicts"]:
        if cf["verdict"] in UNSETTLED:
            for side in (cf["a"], cf["b"]):
                c = claims.get(side)
                if c and position_of.get(c.get("author")) != final_pos and side in v["strength"]:
                    counters.append((v["strength"][side], side, cf["verdict"]))
    if not counters:
        for n, s in v["strength"].items():
            c = claims[n]
            if position_of.get(c.get("author"), final_pos) != final_pos and v["status"][n] != "REJECTED":
                counters.append((s, n, v["status"][n]))
    strongest = None
    if counters:
        s, n, why = max(counters)
        strongest = {"claim": n, "text": claims[n].get("text"), "strength": s, "state": why,
                     "evidence": [_evidence_view(ev[e]) for e in claims[n].get("evidence", [])]}

    review = sorted({e["id"] for e in doc["evidence"] if e["quote_status"] == "n"})
    unverified = sorted({e["id"] for e in doc["evidence"] if e["quote_status"] == "u"})
    checklist = data.get("checklist") or {}
    next_checks = []
    for eid in review:
        next_checks.append("%s: quote needs review against the source (%s)" % (eid, ev[eid].get("url")))
    for cid in (checklist.get("corroboration") or {}).get("below_target", []):
        next_checks.append("%s: find an independent second source" % cid)
    for cf in v["conflicts"]:
        if cf["verdict"] in UNSETTLED:
            next_checks.append("conflict %s vs %s is %s: settle it with new evidence or state the condition"
                               % (cf["a"], cf["b"], cf["verdict"]))

    verification = data.get("verification") or {}
    limits = []
    if data.get("roster_kind") == "동종 명단" or (data.get("baseline") or {}).get("roster") == "homogeneous":
        limits.append("homogeneous roster: participants share one model family and may share errors")
    if verification.get("snippet"):
        limits.append("%d evidence item(s) were checked against search snippets only" % verification["snippet"])
    if review:
        limits.append("%d quote(s) need review and carry no weight" % len(review))
    if unverified:
        limits.append("%d quote(s) were not found and carry no weight" % len(unverified))
    limits.append("P_final is UNCALIBRATED")
    sens = sensitivity(doc, theta)
    if sens["sensitive"]:
        limits.append("sensitive: a conflict verdict moves when the defeat margin or proof standard is nudged by 0.05")

    baseline = data.get("baseline") or {}
    rec = {
        "schema": SCHEMA,
        "status": status,
        "run_id": doc.get("run_id") or result.get("run_id"),
        "question": data.get("question"),
        "as_of": data.get("as_of"),
        "mode": data.get("mode"),
        "recommendation": {"position": final_pos, "summary": data.get("final_position_summary"),
                           "conditions": [i["question"] for i in data.get("issues", [])
                                          if (i.get("engine") or {}).get("verdict") in UNSETTLED]
                           + list(data.get("value_issues", []))},
        "baseline": {"vote": baseline.get("baseline_vote"), "p0": baseline.get("p0"),
                     "p0_method": baseline.get("p0_method"), "final_differs": bool(data.get("overrides")),
                     "p_final": data.get("p_final"), "calibration": "UNCALIBRATED"},
        "decisive_evidence": decisive,
        "strongest_open_counter": strongest,
        "next_checks": next_checks,
        "limits": limits,
        "sensitivity": sens,
        "conflicts": [{"a": c["a"], "b": c["b"], "verdict": c["verdict"]} for c in v["conflicts"]],
        "versions": {"graph": doc.get("schema", "colosseum.arggraph/v1"), "policy": G.POLICY_VERSION,
                     "matcher": doc.get("matcher"), "theta": theta, "input_sha256": v["input_sha256"]},
    }
    return rec


def _q(text):
    return (text or "").replace("\n", " ").strip()


def markdown(rec):
    """Render the record as a Markdown ADR. Every line comes from the record."""
    r = rec["recommendation"]
    lines = ["# %s" % (_q(rec["question"]) or "Decision record"), "",
             "- Status: %s (set by the person deciding)" % rec["status"],
             "- Date: %s" % (rec.get("as_of") or "unspecified"),
             "- Run: %s" % (rec.get("run_id") or "unknown"), "",
             "## Recommendation", "",
             "%s%s" % (_q(r.get("summary")) or "(no summary)", " [%s]" % r["position"] if r.get("position") else "")]
    if r["conditions"]:
        lines += ["", "Applies only if these open conditions hold:", ""] + ["- %s" % _q(c) for c in r["conditions"]]
    lines += ["", "## Decisive evidence", ""]
    if rec["decisive_evidence"]:
        for d in rec["decisive_evidence"]:
            lines.append("- %s (%s, strength %.3f): %s" % (d["claim"], d["status"], d["strength"], _q(d["text"])))
            for e in d["evidence"]:
                lines.append("  - %s [%s, %s, support %s]: \"%s\" %s" % (e["id"], e["check"], e.get("acquisition") or "-",
                                                                     e["support"], _q(e["quote"]), e.get("url") or ""))
    else:
        lines.append("- None: no claim of the recommendation rests on eligible evidence.")
    lines += ["", "## Strongest open counter-argument", ""]
    s = rec["strongest_open_counter"]
    if s:
        lines.append("- %s (%s, strength %.3f): %s" % (s["claim"], s["state"], s["strength"], _q(s["text"])))
        for e in s["evidence"]:
            lines.append("  - %s [%s, support %s]: \"%s\" %s" % (e["id"], e["check"], e["support"], _q(e["quote"]), e.get("url") or ""))
    else:
        lines.append("- None recorded.")
    lines += ["", "## Next checks", ""] + (["- %s" % _q(c) for c in rec["next_checks"]] or ["- None."])
    b = rec["baseline"]
    lines += ["", "## Baseline and final", "",
              "- Vote baseline: %s, P0 %s (%s)" % (b["vote"], b["p0"], b.get("p0_method") or "binary"),
              "- Final %s the baseline; P_final %s, %s" % ("departs from" if b["final_differs"] else "keeps",
                                                           b["p_final"], b["calibration"])]
    lines += ["", "## Conflicts", ""] + ["- %s vs %s: %s%s" % (c["a"], c["b"], c["verdict"],
                                                              " (sensitive)" if any(x["a"] == c["a"] and x["b"] == c["b"] and x["moves_under"]
                                                                                    for x in rec["sensitivity"]["conflicts"]) else "")
                                         for c in rec["conflicts"]]
    lines += ["", "## Limits of this review", ""] + ["- %s" % _q(x) for x in rec["limits"]]
    v = rec["versions"]
    lines += ["", "## Versions", "", "- graph %s, policy %s, matcher %s, theta %s, input %s" % (
        v["graph"], v["policy"], v.get("matcher") or "-", v["theta"], v["input_sha256"])]
    return "\n".join(lines) + "\n"


def main(argv):
    import argparse
    p = argparse.ArgumentParser(description="What-if recomputation and decision records.")
    sub = p.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("whatif")
    w.add_argument("graph")
    g = w.add_mutually_exclusive_group(required=True)
    g.add_argument("--exclude-evidence")
    g.add_argument("--unprove-claim")
    r = sub.add_parser("record")
    r.add_argument("result")
    r.add_argument("--status", default="proposed", choices=STATUSES)
    r.add_argument("--markdown", action="store_true")
    a = p.parse_args(argv)
    try:
        if a.cmd == "whatif":
            with open(a.graph, encoding="utf-8") as f:
                out = whatif(json.load(f), a.exclude_evidence, a.unprove_claim)
        else:
            with open(a.result, encoding="utf-8") as f:
                out = record(json.load(f), a.status)
            if a.markdown:
                sys.stdout.write(markdown(out))
                return 0
    except (G.GraphError, ValueError, KeyError) as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        return 2
    print(json.dumps(out, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
