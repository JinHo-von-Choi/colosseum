"""Decision records and single-change what-if recomputation."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "skills", "colosseum", "scripts")
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

import decision as D  # noqa: E402
import verdict_engine as V  # noqa: E402
from test_p0 import ClaimIds, debate_rules  # noqa: E402
from workflow_harness import NODE, run_workflow  # noqa: E402


def ev(eid, origin, **kw):
    e = {"id": eid, "reliability": "high", "quote_status": "v", "support": "full", "origin": origin,
         "url": "https://%s.example/" % origin, "quote": "quote " + eid}
    e.update(kw)
    return e


# A's claim stands on E1. B attacks it with a weaker claim; C (backed by E3) undercuts B.
GRAPH = {
    "evidence": [ev("E1", "a"), ev("E2", "b", reliability="low"), ev("E3", "c")],
    "claims": [{"id": "A", "author": "A", "text": "A holds", "evidence": ["E1"]},
               {"id": "B", "author": "B", "text": "B holds", "evidence": ["E2"]},
               {"id": "C", "author": "A", "text": "C undercuts B", "evidence": ["E3"]}],
    "relations": [{"type": "attack", "subtype": "rebut", "from": "B", "to": "A"},
                  {"type": "attack", "subtype": "undercut", "from": "C", "to": "B"}],
    "conflicts": [{"a": "A", "b": "B"}],
}


class WhatIf(unittest.TestCase):
    def test_excluding_the_undercut_evidence_propagates(self):
        before = V.verdict(GRAPH)
        out = D.whatif(GRAPH, exclude_evidence="E3")
        self.assertEqual(out["change"], {"exclude_evidence": "E3"})
        changed = {c["claim"]: c for c in out["claims_changed"]}
        self.assertIn("C", out["base_changed"])
        for claim, row in changed.items():
            self.assertEqual(row["before"], before["status"][claim])
            self.assertTrue(row["via"], claim)
        self.assertEqual(out["claims_unchanged"] + len(changed), 3)
        self.assertEqual(V.verdict(GRAPH), before, "the input graph must not be modified")

    def test_unproving_a_claim_and_errors(self):
        out = D.whatif(GRAPH, unprove_claim="A")
        self.assertEqual(out["base_changed"]["A"][1], 0.2)
        with self.assertRaises(ValueError):
            D.whatif(GRAPH, exclude_evidence="E9")
        with self.assertRaises(ValueError):
            D.whatif(GRAPH, exclude_evidence="E1", unprove_claim="A")
        with self.assertRaises(ValueError):
            D.whatif(GRAPH)

    def test_no_change_reports_nothing_changed(self):
        doc = dict(GRAPH, evidence=GRAPH["evidence"] + [ev("E4", "d", quote_status="u")],
                   claims=GRAPH["claims"][:2] + [dict(GRAPH["claims"][2], evidence=["E3", "E4"])])
        out = D.whatif(doc, exclude_evidence="E4")
        self.assertEqual((out["claims_changed"], out["conflicts_changed"]), ([], 0))

    def test_sensitivity_is_reported_without_a_percentage(self):
        s = D.sensitivity(GRAPH)
        self.assertIn("sensitive", s)
        self.assertNotIn("%", json.dumps(s))


@unittest.skipUnless(NODE, "node is not installed")
class DecisionRecord(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        out = run_workflow("debate", ClaimIds.ARGS, debate_rules(2))
        assert "error" not in out, out.get("error")
        cls.result = out["result"]

    def test_record_is_built_from_structured_data_only(self):
        rec = D.record(self.result)
        self.assertEqual(rec["schema"], D.SCHEMA)
        self.assertEqual(rec["status"], "proposed")
        self.assertLessEqual(len(rec["decisive_evidence"]), 3)
        for d in rec["decisive_evidence"]:
            self.assertTrue(all(e["eligible"] for e in d["evidence"]))
        self.assertIn("P_final is UNCALIBRATED", rec["limits"])
        self.assertTrue(any("homogeneous" in x for x in rec["limits"]))
        md = D.markdown(rec)
        known = {c["id"] for c in self.result["graph"]["claims"]} | {e["id"] for e in self.result["graph"]["evidence"]}
        import re
        for ref in re.findall(r"\b(r\d+\.i[-\d]+\.[a-z]+\.[A-Z]\.\d+|E\d+)\b", md):
            self.assertIn(ref, known)
        for section in ("## Recommendation", "## Decisive evidence", "## Strongest open counter-argument",
                        "## Next checks", "## Limits of this review", "## Versions"):
            self.assertIn(section, md)

    def test_cli_writes_markdown_and_json_into_the_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, COLOSSEUM_DATA=tmp)
            cli = [sys.executable, os.path.join(SCRIPTS, "colosseum.py")]
            start = json.loads(subprocess.run(cli + ["start", "--session", "s"], capture_output=True, text=True, env=env).stdout)
            r = subprocess.run(cli + ["adr", "--session", "s", "--file", "-", "--status", "deferred"],
                               input=json.dumps(self.result), capture_output=True, text=True, env=env)
            out = json.loads(r.stdout)
            self.assertEqual(out["files"]["markdown"], os.path.join(start["run_dir"], "decision.md"))
            with open(out["files"]["json"]) as f:
                self.assertEqual(json.load(f)["status"], "deferred")
            evid = self.result["graph"]["evidence"][0]["id"]
            r = subprocess.run(cli + ["whatif", "--session", "s", "--file", "-", "--exclude-evidence", evid],
                               input=json.dumps(self.result["graph"]), capture_output=True, text=True, env=env)
            self.assertEqual(json.loads(r.stdout)["change"], {"exclude_evidence": evid})


if __name__ == "__main__":
    unittest.main()
