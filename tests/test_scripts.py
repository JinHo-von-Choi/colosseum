"""Unit tests for the Colosseum scripts. Run: python3 -m unittest discover -s tests"""
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "colosseum", "scripts")
FIX = os.path.join(ROOT, "tests", "fixtures")
sys.path.insert(0, SCRIPTS)

import baseline as B  # noqa: E402
import graph as G  # noqa: E402
import metrics as M  # noqa: E402
import quote_match as Q  # noqa: E402
import turns as T  # noqa: E402
import verdict_engine as V  # noqa: E402


def fixture(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return json.load(f)


def ev(eid, rel="high", quote="v", support="full", **kw):
    e = {"id": eid, "reliability": rel, "quote_status": quote, "support": support}
    e.update(kw)
    return e


class VerdictEngineFixtures(unittest.TestCase):
    def test_t1_undercut_with_reinstatement(self):
        out = V.verdict(fixture("t1.json"))
        self.assertEqual(out["labels"], {"A1": "OUT", "A2": "IN", "B1": "IN", "C1": "IN"})
        self.assertEqual(out["conflicts"][0]["verdict"], "LOSER_REFUTED_WINNER_UNPROVEN")
        self.assertIn(["A2", "C1"], out["blocked_attacks"])

    def test_t2_symmetric_rebuttal_is_conditional(self):
        out = V.verdict(fixture("t2.json"))
        self.assertEqual(out["conflicts"][0]["verdict"], "CONDITIONAL")
        self.assertEqual(out["preferred"], [["A"], ["B"]])
        self.assertEqual(out["conflicts"][0]["lean"], 0.0)

    def test_t3_odd_cycle_is_unresolved(self):
        out = V.verdict(fixture("t3.json"))
        self.assertEqual(out["conflicts"][0]["verdict"], "UNRESOLVED")
        self.assertEqual(out["stable"], [])

    def test_deterministic(self):
        for name in ("t1.json", "t2.json", "t3.json"):
            a = V.verdict(fixture(name))
            b = V.verdict(copy.deepcopy(fixture(name)))
            self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))


class VerdictEngineDefects(unittest.TestCase):
    """Regression tests for the four defects found in the prototype."""

    def test_evidence_free_undercut_cannot_reject_verified_claim(self):
        doc = {"evidence": [ev("E1", origin="o1")],
               "claims": [{"id": "A", "evidence": ["E1"]}, {"id": "B"}, {"id": "U"}],
               "relations": [{"type": "attack", "subtype": "rebut", "from": "A", "to": "B"},
                             {"type": "attack", "subtype": "rebut", "from": "B", "to": "A"},
                             {"type": "attack", "subtype": "undercut", "from": "U", "to": "A"}],
               "conflicts": [{"a": "A", "b": "B"}]}
        out = V.verdict(doc)
        self.assertEqual(out["status"]["A"], "ACCEPTED")
        self.assertEqual(out["conflicts"][0]["verdict"], "A_WINS")
        self.assertIn(["U", "A"], out["demoted_undercuts"])

    def test_undercut_with_checked_evidence_still_defeats(self):
        doc = {"evidence": [ev("E1", origin="o1"), ev("E2", rel="low", origin="o2")],
               "claims": [{"id": "A", "evidence": ["E1"]}, {"id": "U", "evidence": ["E2"]}],
               "relations": [{"type": "attack", "subtype": "undercut", "from": "U", "to": "A"}]}
        self.assertEqual(V.verdict(doc)["status"]["A"], "REJECTED")

    def test_missing_origin_does_not_multiply_copies(self):
        copies = [ev("E%d" % i, rel="medium", url="https://www.wire.example/story-%d" % i) for i in range(3)]
        claim = {"id": "A", "evidence": ["E0", "E1", "E2"]}
        by_id = {e["id"]: e for e in copies}
        one = G.base_score({"id": "A", "evidence": ["E0"]}, by_id)
        self.assertAlmostEqual(G.base_score(claim, by_id), one)
        bare = [ev("E%d" % i, rel="medium") for i in range(3)]
        self.assertAlmostEqual(G.base_score(claim, {e["id"]: e for e in bare}), one)

    def test_distinct_origins_do_corroborate(self):
        srcs = [ev("E%d" % i, rel="medium", origin="o%d" % i) for i in range(3)]
        by_id = {e["id"]: e for e in srcs}
        self.assertGreater(G.base_score({"id": "A", "evidence": ["E0", "E1", "E2"]}, by_id),
                           G.base_score({"id": "A", "evidence": ["E0"]}, by_id))

    def test_weak_evidence_never_scores_below_none(self):
        weak = ev("E1", rel="low", quote="snippet", support="partial")
        self.assertGreaterEqual(G.base_score({"id": "A", "evidence": ["E1"]}, {"E1": weak}), G.NO_EVIDENCE_PRIOR)
        self.assertAlmostEqual(G.base_score({"id": "A"}, {}), G.NO_EVIDENCE_PRIOR)

    def test_unverified_quote_adds_nothing(self):
        u = ev("E1", quote="u")
        self.assertEqual(G.evidence_score(u), 0.0)
        self.assertAlmostEqual(G.base_score({"id": "A", "evidence": ["E1"]}, {"E1": u}), G.NO_EVIDENCE_PRIOR)


class VerdictEngineOther(unittest.TestCase):
    def test_value_claims_are_conditional(self):
        doc = {"evidence": [], "claims": [{"id": "A", "kind": "value"}, {"id": "B", "kind": "fact"}],
               "relations": [], "conflicts": [{"a": "A", "b": "B"}]}
        self.assertEqual(V.verdict(doc)["conflicts"][0]["verdict"], "VALUE_CONDITIONAL")

    def test_high_stakes_theta(self):
        doc = {"evidence": [ev("E1", rel="medium", origin="o")],
               "claims": [{"id": "A", "evidence": ["E1"]}], "relations": []}
        self.assertEqual(V.verdict(doc, 0.5)["status"]["A"], "ACCEPTED")
        self.assertEqual(V.verdict(doc, 0.7)["status"]["A"], "IN_UNPROVEN")

    def test_validation_errors(self):
        with self.assertRaises(G.GraphError):
            G.validate({"evidence": [], "claims": [{"id": "A", "evidence": ["missing"]}], "relations": []})
        with self.assertRaises(G.GraphError):
            G.validate({"evidence": [], "claims": [{"id": "A"}, {"id": "B"}],
                        "relations": [{"type": "attack", "from": "A", "to": "B"}]})
        with self.assertRaises(G.GraphError):
            G.validate({"evidence": [ev("E1", quote="verified")], "claims": [], "relations": []})


class QuoteMatch(unittest.TestCase):
    def test_labeled_samples(self):
        d = fixture("quotes.json")
        misses = [(c, Q.match(c["quote"], d["page"])) for c in d["cases"]
                  if Q.match(c["quote"], d["page"])["status"] != c["expect"]]
        self.assertEqual(misses, [])

    def test_changed_number_is_not_near(self):
        page = "Resignations fell by 33% among workers who shifted to a hybrid schedule."
        r = Q.match("Resignations fell by 43% among workers who shifted to a hybrid schedule.", page)
        self.assertEqual(r["status"], "u")

    def test_korean(self):
        page = "재택근무를 병행한 직원의 퇴사율은 33% 낮아졌고 성과 평가에는 차이가 없었다."
        self.assertEqual(Q.match("퇴사율은 33% 낮아졌고 성과 평가에는 차이가 없었다", page)["status"], "v")


class Baseline(unittest.TestCase):
    def drafts(self, *rows):
        return {"drafts": [{"label": l, "family": f, "position": p, "probability": pr} for l, f, p, pr in rows]}

    def test_same_family_counts_once(self):
        out = B.baseline(self.drafts(("A", "claude", "X", 0.7), ("B", "claude", "X", 0.7), ("C", "gemini", "Y", 0.7)))
        self.assertTrue(out["tie"])
        self.assertIsNone(out["baseline_vote"])

    def test_heterogeneous_majority(self):
        out = B.baseline(self.drafts(("A", "claude", "X", 0.8), ("B", "gemini", "X", 0.7), ("C", "gpt", "Y", 0.6)))
        self.assertEqual(out["baseline_vote"], "X")
        self.assertEqual(out["roster"], "heterogeneous")
        self.assertFalse(out["skip_debate"])

    def test_pooled_probability(self):
        out = B.baseline(self.drafts(("A", "c1", "X", 0.8), ("B", "c2", "X", 0.7), ("C", "c3", "Y", 0.65)))
        self.assertAlmostEqual(out["p0"], 0.631, places=3)

    def test_skip_and_dissenter_rules(self):
        het = B.baseline(self.drafts(("A", "claude", "X", 0.9), ("B", "gemini", "X", 0.85), ("C", "gpt", "X", 0.8)))
        self.assertTrue(het["skip_debate"])
        hom = B.baseline(self.drafts(("A", "claude", "X", 0.9), ("B", "claude", "X", 0.9), ("C", "claude", "X", 0.9)))
        self.assertFalse(hom["skip_debate"])
        self.assertTrue(hom["needs_dissenter"])
        doc = self.drafts(("A", "claude", "X", 0.9), ("B", "gemini", "X", 0.85), ("C", "gpt", "X", 0.8))
        doc["verified_counter"] = True
        self.assertFalse(B.baseline(doc)["skip_debate"])

    def test_extremizing_guard(self):
        out = B.baseline(self.drafts(("A", "claude", "X", 0.7), ("B", "claude", "X", 0.7)), a=1.3)
        self.assertEqual(out["extremizing"], 1.0)
        self.assertTrue(out["notes"])


class Metrics(unittest.TestCase):
    def test_checklist(self):
        doc = {"evidence": [ev("E1", origin="o1"), ev("E2", rel="medium", quote="snippet", origin="o2"),
                            ev("E3", rel="low", quote="u", origin="o3")],
               "claims": [{"id": "A", "author": "A", "evidence": ["E1", "E2"]},
                          {"id": "B", "author": "B", "evidence": ["E3"]},
                          {"id": "C", "author": "C", "evidence": ["E1"]},
                          {"id": "V", "author": "A", "kind": "value"}],
               "relations": [],
               "final": [{"claim": "A", "weight": 3}, {"claim": "B", "weight": 3}, {"claim": "C", "weight": 2},
                         {"claim": "V", "weight": 3}]}
        out = M.checklist(doc)
        self.assertEqual(out["verification"]["decisive"], {"quote_verified": 1, "snippet_only": 0, "total": 2})
        self.assertEqual(out["corroboration"]["per_decisive_claim"], {"A": 2, "B": 0})
        self.assertEqual(out["corroboration"]["below_target"], ["B"])
        self.assertEqual(out["unverified_quotes"], ["E3"])
        self.assertAlmostEqual(out["origin_diversity"], round(1 - 1 / 3, 3))


class Turns(unittest.TestCase):
    def test_valid_draft(self):
        msg = "```json\n" + json.dumps({
            "label": "A", "role": "draft", "position": "p",
            "claims": [{"text": "t", "kind": "fact", "url": "https://x", "quote": "a b c"}],
            "key_assumptions": ["k"], "cruxes": ["c"], "strongest_counter": "s", "probability": 0.7}) + "\n```"
        self.assertEqual(T.check(msg), [])

    def test_invalid_turns(self):
        self.assertEqual(T.check("no json here"), ["no JSON object found"])
        bad = {"label": "A", "role": "draft", "position": "p", "claims": [{"text": "t"}],
               "key_assumptions": [], "cruxes": [], "strongest_counter": "s", "probability": 1.2}
        found = T.check(json.dumps(bad))
        self.assertTrue(any("url" in f for f in found))
        self.assertTrue(any("probability" in f for f in found))
        pros = {"role": "prosecutor", "steelman": "One. Two. Three. Four.", "target_claim": "x",
                "attack": "y", "claims": []}
        self.assertTrue(any("steelman" in f for f in T.check(json.dumps(pros))))


class _CliCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = dict(os.environ, CLAUDE_PLUGIN_DATA=self.tmp.name)
        self.env.pop("COLOSSEUM_DATA", None)

    def tearDown(self):
        self.tmp.cleanup()

    def cli(self, *args, stdin=None):
        r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "colosseum.py")] + list(args),
                           capture_output=True, text=True, env=self.env, input=stdin)
        return r.returncode, json.loads(r.stdout)

    def hook(self, mode, event):
        r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "hook.py"), mode], input=json.dumps(event),
                           capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 0)
        return json.loads(r.stdout) if r.stdout.strip() else None


class StateMachineAndHooks(_CliCase):
    def test_phase_order_and_round_rules(self):
        s = ("--session", "s1")
        self.assertEqual(self.cli("start", *s, "--question", "q", "--max-rounds", "2")[0], 0)
        code, out = self.cli("advance", *s, "--to", "drafts")
        self.assertEqual(code, 2)
        for phase in ("fact_base", "drafts", "baseline", "issues", "round"):
            self.assertEqual(self.cli("advance", *s, "--to", phase)[0], 0, phase)
        code, out = self.cli("advance", *s, "--to", "round")
        self.assertEqual(code, 2)
        self.assertIn("round-result", out["refused"])
        code, out = self.cli("round-result", *s, "--verified-changes", "0", "--open-issues", "2")
        self.assertEqual(out["exit_reason"], "stable")
        code, out = self.cli("advance", *s, "--to", "round")
        self.assertIn("stable", out["refused"])
        self.assertEqual(self.cli("advance", *s, "--to", "verdict")[0], 0)
        self.assertEqual(self.cli("advance", *s, "--to", "done")[0], 0)

    def test_round_cap(self):
        s = ("--session", "s2")
        self.cli("start", *s, "--question", "q", "--max-rounds", "1")
        for phase in ("fact_base", "drafts", "baseline", "issues", "round"):
            self.cli("advance", *s, "--to", phase)
        self.cli("round-result", *s, "--verified-changes", "2", "--open-issues", "1")
        code, out = self.cli("advance", *s, "--to", "round")
        self.assertIn("cap", out["refused"])

    def test_hooks_noop_without_run(self):
        self.assertIsNone(self.hook("pre", {"session_id": "none", "tool_name": "WebSearch"}))
        self.assertIsNone(self.hook("subagent-stop", {"session_id": "none", "last_assistant_message": "x"}))

    def test_search_budget_and_ledger(self):
        run = self.cli("start", "--session", "s3", "--question", "q", "--search-budget", "2")[1]["run_dir"]
        e = {"session_id": "s3", "tool_name": "WebSearch", "tool_input": {"query": "x"}}
        self.assertIsNone(self.hook("pre", e))
        self.assertIsNone(self.hook("pre", e))
        out = self.hook("pre", e)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        real_shape = {"query": "x", "durationSeconds": 1.2, "searchCount": 1,
                      "results": [{"tool_use_id": "t1", "content": [{"title": "a", "url": "https://a.example/1"},
                                                                    {"title": "b", "url": "https://b.example/2"}]},
                                  "summary text"]}
        self.hook("post", dict(e, tool_response=real_shape))
        with open(os.path.join(run, "sources.jsonl")) as f:
            rec = json.loads(f.readline())
        self.assertEqual(rec["result_urls"], ["https://a.example/1", "https://b.example/2"])
        self.assertTrue(rec["ok"])
        self.assertNotIn("debug", rec)

    def test_snippet_mode_blocks_fetch(self):
        s = ("--session", "s4")
        self.cli("start", *s, "--question", "q")
        for host in ("a.example", "b.example", "a.example", "c.example"):
            code, out = self.cli("fetch-failed", *s, "--url", "https://%s/x" % host)
        self.assertTrue(out["degraded"])
        out = self.hook("pre", {"session_id": "s4", "tool_name": "WebFetch", "tool_input": {"url": "https://d"}})
        self.assertIn("snippet-level", out["hookSpecificOutput"]["permissionDecisionReason"])

    def test_sendmessage_blocked_during_drafts(self):
        s = ("--session", "s5")
        self.cli("start", *s, "--question", "q")
        self.cli("advance", *s, "--to", "fact_base")
        self.cli("advance", *s, "--to", "drafts")
        out = self.hook("pre", {"session_id": "s5", "tool_name": "SendMessage"})
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_subagent_stop_repairs_once(self):
        self.cli("start", "--session", "s6", "--question", "q")
        out = self.hook("subagent-stop", {"session_id": "s6", "last_assistant_message": "prose only"})
        self.assertEqual(out["decision"], "block")
        self.assertIsNone(self.hook("subagent-stop", {"session_id": "s6", "stop_hook_active": True,
                                                      "last_assistant_message": "prose only"}))

    def test_baseline_and_verdict_from_run_dir(self):
        s = ("--session", "s7")
        run = self.cli("start", *s, "--question", "q", "--stakes", "high")[1]["run_dir"]
        with open(os.path.join(run, "drafts.json"), "w") as f:
            json.dump({"drafts": [{"label": "A", "family": "c", "position": "X", "probability": 0.8}]}, f)
        with open(os.path.join(run, "graph.json"), "w") as f:
            json.dump(fixture("t2.json"), f)
        self.cli("advance", *s, "--to", "fact_base")
        self.cli("advance", *s, "--to", "drafts")
        code, out = self.cli("baseline", *s)
        self.assertEqual(out["baseline_vote"], "X")
        self.assertEqual(self.cli("status", *s)[1]["phase"], "baseline")
        code, out = self.cli("verdict", *s)
        self.assertEqual(out["theta"], 0.7)
        self.assertTrue(os.path.exists(os.path.join(run, "verdict.json")))


class StdinInputs(_CliCase):
    def test_stdin_baseline_advances_and_saves(self):
        s = ("--session", "s8")
        run = self.cli("start", *s)[1]["run_dir"]
        self.cli("advance", *s, "--to", "fact_base")
        self.cli("advance", *s, "--to", "drafts")
        drafts = {"drafts": [{"label": "A", "family": "claude", "position": "X", "probability": 0.8},
                             {"label": "B", "family": "gemini", "position": "X", "probability": 0.9}]}
        code, out = self.cli("baseline", *s, "--file", "-", stdin=json.dumps(drafts))
        self.assertEqual(code, 0)
        self.assertEqual(self.cli("status", *s)[1]["phase"], "baseline")
        self.assertTrue(os.path.exists(os.path.join(run, "drafts.json")))
        self.assertEqual(self.cli("advance", *s, "--to", "verdict")[0], 0)
        code, out = self.cli("verdict", *s, "--file", "-", stdin=json.dumps(fixture("t2.json")))
        self.assertEqual(out["conflicts"][0]["verdict"], "CONDITIONAL")
        code, out = self.cli("metrics", *s)
        self.assertIn("verification", out)

    def test_stdin_quote_is_logged(self):
        run = self.cli("start", "--session", "s9")[1]["run_dir"]
        req = {"id": "E1", "quote": "fell by 33%", "page": "Resignations fell by 33% overall."}
        code, out = self.cli("quote", "--session", "s9", "--stdin", stdin=json.dumps(req))
        self.assertEqual(out["status"], "v")
        with open(os.path.join(run, "quotes.jsonl")) as f:
            self.assertEqual(json.loads(f.readline())["id"], "E1")


if __name__ == "__main__":
    unittest.main()
