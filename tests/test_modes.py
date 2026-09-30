"""Unit tests for the mode aggregation rules and the forecast log."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "colosseum", "scripts")
sys.path.insert(0, SCRIPTS)

import calibration as C  # noqa: E402
import modes as MO  # noqa: E402


class Borda(unittest.TestCase):
    def test_points_and_tie_break(self):
        out = MO.borda([["I1", "I2", "I3"], ["I2", "I1", "I3"], ["I2"]])
        self.assertEqual([r["id"] for r in out], ["I2", "I1", "I3"])
        self.assertEqual(out[0]["points"], 3 + 2 + 3)

    def test_duplicate_votes_in_a_ballot_count_once(self):
        out = MO.borda([["I1", "I1", "I2"]])
        self.assertEqual({r["id"]: r["points"] for r in out}, {"I1": 3, "I2": 1})

    def test_equal_points_break_on_voters(self):
        out = MO.borda([["I1", "I2"], ["I3"]])
        # I1: 2 points from 1 voter, I3: 2 points from 1 voter, I2: 1 point -> id order breaks the tie
        self.assertEqual([r["id"] for r in out], ["I1", "I3", "I2"])


class Delphi(unittest.TestCase):
    def test_feedback_is_anonymous_statistics(self):
        fb = MO.delphi_feedback([{"label": "A", "value": 0.2}, {"label": "B", "value": 0.5}, {"label": "C", "value": 0.7}])
        self.assertEqual(fb["median"], 0.5)
        self.assertEqual((fb["above"], fb["below"]), (["C"], ["A"]))

    def test_unsupported_large_move_is_capped(self):
        self.assertEqual(MO.limit_move(0.4, 0.8, False), {"value": 0.5, "capped": True})
        self.assertEqual(MO.limit_move(0.4, 0.8, True), {"value": 0.8, "capped": False})
        self.assertEqual(MO.limit_move(0.4, 0.45, False), {"value": 0.45, "capped": False})
        self.assertEqual(MO.limit_move(100, 50, False, scale=100)["value"], 90)

    def test_family_median(self):
        est = [{"family": "claude", "value": 10}, {"family": "claude", "value": 30}, {"family": "gemini", "value": 100}]
        self.assertEqual(MO.family_median(est), (20 + 100) / 2)


class Ach(unittest.TestCase):
    def test_non_diagnostic_evidence_is_dropped(self):
        rows = [
            {"id": "E1", "quote_status": "v", "reliability": "high", "ratings": {"H1": "C", "H2": "C"}},
            {"id": "E2", "quote_status": "v", "reliability": "high", "ratings": {"H1": "C", "H2": "I"}},
            {"id": "E3", "quote_status": "snippet", "reliability": "low", "ratings": {"H1": "I", "H2": "C"}},
        ]
        out = MO.ach(["H1", "H2"], rows)
        self.assertEqual(out["dropped"], ["E1"])
        self.assertEqual(out["least_inconsistent"], ["H1", "H2"])
        self.assertEqual(out["weak_inconsistencies"], {"H1": 1, "H2": 0})

    def test_pooling_is_coherent_and_family_weighted(self):
        hs = ["H1", "H2"]
        pooled = MO.log_linear_pool([{"family": "c", "dist": {"H1": 0.9, "H2": 0.1}},
                                     {"family": "c", "dist": {"H1": 0.9, "H2": 0.1}},
                                     {"family": "g", "dist": {"H1": 0.1, "H2": 0.9}}], hs)
        self.assertAlmostEqual(sum(pooled.values()), 1.0, places=2)
        self.assertAlmostEqual(pooled["H1"], 0.5, places=2)
        self.assertEqual(MO.coherent({"H1": 2, "H2": 0}, hs)["H2"] > 0, True)


class ForecastLog(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def rec(self, i, p, p0=None):
        return {"id": "f%d" % i, "question": "q%d" % i, "resolution_criteria": "c", "resolve_by": "2027-01-01",
                "p_final": p, "p0": p if p0 is None else p0}

    def test_add_resolve_score(self):
        C.add(self.root, self.rec(1, 0.8))
        C.add(self.root, self.rec(2, 0.3))
        with self.assertRaises(ValueError):
            C.add(self.root, self.rec(1, 0.5))
        C.resolve(self.root, "f1", 1)
        C.resolve(self.root, "f2", 0)
        s = C.score(C.load(self.root))
        self.assertEqual(s["resolved"], 2)
        self.assertAlmostEqual(s["brier"], ((0.8 - 1) ** 2 + 0.3 ** 2) / 2, places=4)

    def test_fit_needs_enough_resolved(self):
        C.add(self.root, self.rec(1, 0.7))
        C.resolve(self.root, "f1", 1)
        self.assertFalse(C.fit_extremizing(C.load(self.root))["fitted"])

    def test_fit_prefers_extremizing_for_underconfident_forecasts(self):
        # Forecasts that sit at 0.65 / 0.35 but always come true are underconfident.
        for i in range(30):
            C.add(self.root, self.rec(i, 0.65 if i % 2 else 0.35))
            C.resolve(self.root, "f%d" % i, 1 if i % 2 else 0)
        fit = C.fit_extremizing(C.load(self.root))
        self.assertTrue(fit["fitted"])
        self.assertGreater(fit["a"], 1.0)
        self.assertLess(fit["log_loss_at_fit"], fit["log_loss_at_1"])

    def test_invalid_records(self):
        with self.assertRaises(ValueError):
            C.add(self.root, {"id": "x"})
        with self.assertRaises(ValueError):
            C.add(self.root, self.rec(1, 1.0))

    def test_cli(self):
        env = dict(os.environ, COLOSSEUM_DATA=self.root)
        cli = [sys.executable, os.path.join(SCRIPTS, "colosseum.py")]
        r = subprocess.run(cli + ["forecast", "add"], input=json.dumps(self.rec(7, 0.6)), capture_output=True, text=True, env=env)
        self.assertEqual(json.loads(r.stdout)["logged"], "f7")
        r = subprocess.run(cli + ["forecast", "resolve", "--id", "f7", "--outcome", "1"], capture_output=True, text=True, env=env)
        self.assertEqual(json.loads(r.stdout)["resolved"]["outcome"], 1)
        r = subprocess.run(cli + ["forecast", "score"], capture_output=True, text=True, env=env)
        self.assertEqual(json.loads(r.stdout)["p_final"]["resolved"], 1)
        r = subprocess.run(cli + ["forecast", "add", "--file", "-"], input=json.dumps(self.rec(8, 0.4)), capture_output=True, text=True, env=env)
        self.assertEqual(json.loads(r.stdout)["logged"], "f8")
        r = subprocess.run(cli + ["forecast", "resolve", "--id", "nope", "--outcome", "1"], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
