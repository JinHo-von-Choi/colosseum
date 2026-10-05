"""The computation contract: one evidence policy, relation and order invariance, and the
same results from Python and the workflows' JavaScript on the same data."""
import copy
import itertools
import json
import os
import random
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "skills", "colosseum", "scripts"))
sys.path.insert(0, HERE)

import baseline as B  # noqa: E402
import graph as G  # noqa: E402
import verdict_engine as V  # noqa: E402
from test_js_parity import random_graph, run_js  # noqa: E402
from workflow_harness import NODE, run_workflow  # noqa: E402

COMPARED = ("policy", "labels", "status", "base", "strength", "qbaf_converged", "defeats", "demoted_undercuts",
            "preferred", "stable", "conflicts")


def comparable(v):
    out = {k: v[k] for k in COMPARED}
    out["defeats"] = sorted(map(list, v["defeats"]))
    out["demoted_undercuts"] = sorted(map(list, v["demoted_undercuts"]))
    return json.loads(json.dumps(out))


def ev(eid, **kw):
    e = {"id": eid, "reliability": "high", "quote_status": "v", "support": "full"}
    e.update(kw)
    return e


class EvidencePolicy(unittest.TestCase):
    def test_one_rule_for_score_and_undercut(self):
        for bad in (dict(quote_status="n"), dict(quote_status="u"), dict(support="none"), dict(support="unknown"),
                    dict(freshness="superseded")):
            e = ev("E1", **bad)
            self.assertFalse(G.eligible(e), bad)
            self.assertEqual(G.evidence_score(e), 0.0, bad)
            self.assertFalse(G.has_checked_evidence({"evidence": ["E1"]}, {"E1": e}), bad)
        self.assertTrue(G.eligible(ev("E1", freshness="unknown")))
        self.assertLess(G.evidence_score(ev("E1", freshness="unknown")), G.evidence_score(ev("E1", freshness="fresh")))

    def test_superseded_evidence_cannot_carry_an_unconditional_undercut(self):
        doc = {"evidence": [ev("E1"), ev("E2", freshness="superseded")],
               "claims": [{"id": "A", "evidence": ["E1"]}, {"id": "B", "evidence": ["E2"]}],
               "relations": [{"type": "attack", "subtype": "undercut", "from": "B", "to": "A"}]}
        out = V.verdict(doc)
        self.assertEqual(out["status"]["A"], "ACCEPTED")
        self.assertEqual(out["demoted_undercuts"], [["B", "A"]])


class Invariance(unittest.TestCase):
    def docs(self):
        rng = random.Random(21)
        return [random_graph(rng, rng.randrange(4, 9)) for _ in range(30)]

    def test_duplicated_relations_change_nothing(self):
        for d in self.docs():
            dup = copy.deepcopy(d)
            dup["relations"] = dup["relations"] + copy.deepcopy(dup["relations"])
            self.assertEqual(comparable(V.verdict(d)), comparable(V.verdict(dup)))

    def test_list_order_changes_nothing(self):
        rng = random.Random(4)
        for d in self.docs():
            shuffled = copy.deepcopy(d)
            for k in ("evidence", "claims", "relations"):
                rng.shuffle(shuffled[k])
            a, b = comparable(V.verdict(d)), comparable(V.verdict(shuffled))
            self.assertEqual(a, b)

    def test_three_positions_do_not_use_a_binary_complement(self):
        drafts = [{"label": "A", "family": "c", "position": "P1", "probability": 0.6},
                  {"label": "B", "family": "g", "position": "P2", "probability": 0.6},
                  {"label": "C", "family": "o", "position": "P3", "probability": 0.6}]
        p = B.pooled_probability(drafts, "P1")
        # P1's own drafter says 0.6; the two others give it 0.4 / 2 = 0.2 each.
        self.assertLess(p, 0.4)
        out = B.baseline({"drafts": drafts})
        self.assertTrue(out["p0_method"].startswith("split"))
        two = B.baseline({"drafts": drafts[:2]})
        self.assertEqual(two["p0_method"], "binary")


def reference_semantics(nodes, attacks):
    """Textbook Dung semantics by brute force, independent of verdict_engine."""
    def cf(S):
        return not any((a, b) in attacks for a in S for b in S)

    def defends(S, x):
        return all(any((d, a) in attacks for d in S) for (a, b) in attacks if b == x)

    ground = set()
    while True:
        nxt = {x for x in nodes if defends(ground, x)}
        if nxt == ground:
            break
        ground = nxt
    subsets = [set(c) for k in range(len(nodes) + 1) for c in itertools.combinations(nodes, k)]
    adm = [S for S in subsets if cf(S) and all(defends(S, x) for x in S)]
    pref = [S for S in adm if not any(S < T for T in adm)]
    stable = [S for S in subsets if cf(S) and all(any((s, x) in attacks for s in S) for x in nodes if x not in S)]
    canon = lambda L: sorted(sorted(S) for S in L)
    return ground, canon(pref), canon(stable)


class Semantics4096(unittest.TestCase):
    def test_all_four_node_graphs_without_self_attacks(self):
        nodes = ["a", "b", "c", "d"]
        edges = [(x, y) for x in nodes for y in nodes if x != y]
        for mask in range(1 << len(edges)):
            attacks = {edges[i] for i in range(len(edges)) if mask >> i & 1}
            lab = V.grounded(nodes, attacks)
            pref, stable = V.preferred_and_stable(nodes, attacks, lab)
            ground, rpref, rstable = reference_semantics(nodes, attacks)
            self.assertEqual({n for n in nodes if lab[n] == "IN"}, ground, attacks)
            self.assertEqual(pref, rpref, attacks)
            self.assertEqual(stable, rstable, attacks)


INVALID = [
    {"evidence": [], "claims": [{"id": 1}], "relations": []},
    {"evidence": [], "claims": [{"id": ""}], "relations": []},
    {"evidence": [], "claims": [{"id": "A", "kind": "opinion"}], "relations": []},
    {"evidence": [], "claims": [{"id": "A", "status": ""}], "relations": []},
    {"evidence": [{"id": "E1", "reliability": "high", "quote_status": "x", "support": "full"}], "claims": [], "relations": []},
    {"evidence": [{"id": "E1", "reliability": "high", "quote_status": "v", "support": "full", "freshness": "old"}], "claims": [], "relations": []},
    {"evidence": [], "claims": [{"id": "A"}, {"id": "A"}], "relations": []},
    {"evidence": [], "claims": [{"id": "A"}], "relations": [{"type": "attack", "subtype": "rebut", "from": "A", "to": "A"}]},
    {"evidence": [], "claims": [{"id": "A"}, {"id": "B"}], "relations": [{"type": "attack", "from": "A", "to": "B"}]},
    {"evidence": [], "claims": [{"id": "A"}, {"id": "B"}], "relations": [{"type": "pushes", "from": "A", "to": "B"}]},
    {"evidence": [], "claims": [{"id": "A", "evidence": ["E9"]}], "relations": []},
    {"schema": "colosseum.arggraph/v9", "evidence": [], "claims": [], "relations": []},
    {"evidence": [], "claims": [{"id": "__proto__"}, {"id": "B"}], "relations": [{"type": "attack", "subtype": "rebut", "from": "toString", "to": "B"}]},
]
VALID = [
    {"evidence": [], "claims": [{"id": "A", "kind": "fact", "status": "withdrawn"}], "relations": []},
    {"schema": "colosseum.arggraph/v1", "evidence": [], "claims": [{"id": "A"}], "relations": []},
    {"evidence": [], "claims": [{"id": "é"}, {"id": "é"}], "relations": [{"type": "attack", "subtype": "rebut", "from": "é", "to": "é"}]},
]
URLS = ["https://www.Example.COM:443/a?b=1#frag", "http://example.com:80/", "https://example.com:8443/x",
        "https://例え.jp/path", "https://Bücher.example./a", "ftp://example.com/", "not a url", "",
        "https://user:pw@example.org/p?q=2"]


@unittest.skipUnless(NODE, "node is not installed")
class PythonJavaScriptParity(unittest.TestCase):
    def test_full_verdict_output(self):
        rng = random.Random(13)
        docs = [random_graph(rng, rng.randrange(4, 9)) for _ in range(40)]
        for d in docs[:10]:
            d["relations"] += copy.deepcopy(d["relations"][:3])
            d["evidence"][0]["freshness"] = rng.choice(["unknown", "superseded", "stale"])
            d["evidence"][1]["support"] = "unknown"
        js = run_js([["verdict", [d]] for d in docs])
        for d, j in zip(docs, js):
            self.assertEqual(comparable(V.verdict(d)), comparable(j))

    def test_validation_errors_agree(self):
        script = [["verdict", [d]] for d in VALID]
        js = run_js(script)
        for d, j in zip(VALID, js):
            self.assertEqual(comparable(V.verdict(d)), comparable(j))
        for d in INVALID:
            with self.assertRaises(G.GraphError, msg=json.dumps(d)):
                V.verdict(d)
            with self.assertRaises(Exception, msg=json.dumps(d)):
                run_js([["verdict", [d]]])

    def test_url_normalization_and_origins(self):
        js = run_js([["normalizeUrl", [u]] for u in URLS] + [["originOf", [{"url": u}]] for u in URLS])
        for u, j in zip(URLS, js[:len(URLS)]):
            self.assertEqual(G.normalize_url(u), j, u)
        for u, j in zip(URLS, js[len(URLS):]):
            self.assertEqual(G.origin_of({"url": u}), j, u)
        self.assertEqual(G.origin_of({"url": URLS[3]}), "host:xn--r8jz45g.jp")

    def test_pooling_with_three_positions(self):
        rng = random.Random(8)
        docs = [{"drafts": [{"label": "L%d" % i, "family": rng.choice("abc"), "position": rng.choice(["P1", "P2", "P3"]),
                             "probability": round(rng.uniform(0.3, 0.95), 2)} for i in range(rng.randrange(2, 6))]}
                for _ in range(30)]
        js = run_js([["baseline", [d]] for d in docs])
        for d, j in zip(docs, js):
            py = B.baseline(d)
            for key in ("baseline_vote", "p0", "p0_method"):
                self.assertEqual(py[key], j[key], key)


@unittest.skipUnless(NODE, "node is not installed")
class DelphiOrder(unittest.TestCase):
    URL = "https://example.org/poll"
    QUOTE = "Support rose to 81 percent in September"

    def rules(self):
        claim = [{"text": "Support is high", "kind": "statistic", "url": self.URL, "quote": self.QUOTE}]
        return [
            {"label": "^fact-base$", "response": {"facts": []}},
            {"label": "^market-scan$", "response": {"found": False}},
            {"label": ":forecaster$", "response": {"base_rate": {"reference_class": "r", "value": "v"}, "estimate": 0.4,
                                                   "reason_higher": "h", "reason_lower": "l", "claims": []}},
            {"label": ":delphi$", "response": {"estimate": 0.8, "change_basis": "new poll", "claims": claim}},
            {"label": "^fetch:", "response": {"fetch_failed": False, "passage": self.QUOTE + ".", "context": self.QUOTE + ".",
                                              "reliability": "high", "origin": "poll", "support": "full"}},
            {"label": "^support:", "response": {"support": "full"}},
            {"label": ":premortem$", "response": {"causes": [], "underconfidence": "", "claims": []}},
            {"label": "^report$", "response": "REPORT"},
        ]

    def revisions(self, roster):
        args = {"question": "Will it pass?", "resolution_criteria": "c", "resolve_by": "2027-01-01", "rounds": 1,
                "roster": roster}
        out = run_workflow("forecast", args, self.rules())
        self.assertNotIn("error", out, out.get("error"))
        return {r["label"]: r["capped"] for r in out["result"]["data"]["revisions"]}

    def test_the_same_new_evidence_counts_for_everyone_in_the_round(self):
        roster = [{"label": "A", "family": "claude"}, {"label": "B", "family": "claude"}]
        first = self.revisions(roster)
        self.assertEqual(first, {"A": False, "B": False})
        self.assertEqual(self.revisions(list(reversed(roster))), first)


if __name__ == "__main__":
    unittest.main()
