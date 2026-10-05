"""User-supplied materials: snapshots, deterministic quote checks, and use in the workflows."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "skills", "colosseum", "scripts")
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

import materials as MAT  # noqa: E402
import state as S  # noqa: E402
from workflow_harness import NODE, run_workflow  # noqa: E402

DESIGN = ("# Queue proposal\n\nThe current poller runs every 5 seconds and misses bursts.\n"
          "If traffic exceeds 200 requests per second, the poller drops events.\n"
          "The team has no on-call rotation for a broker.\n")


class _Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.run_dir = os.path.join(self.tmp, "run")
        os.mkdir(self.run_dir)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, rel, data):
        p = os.path.join(self.tmp, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(data if isinstance(data, bytes) else data.encode("utf-8"))
        return p

    def add(self, specs):
        return MAT.add(self.run_dir, specs, S.write_private, S.secure_dir)


class Snapshots(_Tmp):
    def test_files_directories_text_and_urls(self):
        doc = self.write("design.md", DESIGN)
        self.write("repo/src/app.py", "print('hi')\n")
        self.write("repo/logo.png", b"\x89PNG\x00\x00binary")
        self.write("repo/.git/config", "[core]\n")
        self.write("repo/node_modules/x.js", "x\n")
        out = self.add([{"path": doc}, {"path": os.path.join(self.tmp, "repo")},
                        {"text": "Budget is 2 engineers.", "title": "constraints"},
                        {"url": "https://example.org/rfc"}])
        kinds = [(m["id"], m["kind"], m["title"]) for m in out["materials"]]
        self.assertEqual(kinds, [("M1", "file", "design.md"), ("M2", "file", "src/app.py"),
                                 ("M3", "text", "constraints"), ("M4", "url", "https://example.org/rfc")])
        self.assertEqual([s["reason"] for s in out["skipped"]], ["not a text file"])
        with open(out["materials"][0]["path"], encoding="utf-8") as f:
            self.assertEqual(f.read(), DESIGN)
        self.assertEqual(len(out["materials"][0]["sha256"]), 64)
        self.assertNotIn("path", out["materials"][3])

    def test_large_files_are_truncated_and_errors_are_clear(self):
        big = self.write("big.txt", "a" * (MAT.MAX_FILE_BYTES + 10))
        out = self.add([{"path": big}])
        self.assertTrue(out["materials"][0]["truncated"])
        with self.assertRaises(MAT.MaterialError):
            self.add([{"path": os.path.join(self.tmp, "missing.md")}])
        with self.assertRaises(MAT.MaterialError):
            self.add([{"url": "file:///etc/passwd"}])
        with self.assertRaises(MAT.MaterialError):
            MAT.add(os.path.join(self.tmp, "run2"), [{"path": self.write("x.bin", b"\x00\x01")}],
                    S.write_private, S.secure_dir)


def ev(eid, quote, url="material:M1"):
    return {"id": eid, "url": url, "quote": quote, "reliability": "high", "quote_status": "v", "support": "full"}


class QuoteChecks(_Tmp):
    def test_material_quotes_are_checked_against_the_snapshot(self):
        doc_path = self.write("design.md", DESIGN)
        self.add([{"path": doc_path}])
        # The original changes after the snapshot; the check must use the snapshot.
        self.write("design.md", "rewritten")
        graph = {"evidence": [ev("E1", "The current poller runs every 5 seconds and misses bursts."),
                              ev("E2", "the poller drops events"),
                              ev("E3", "The team has an on-call rotation for a broker."),
                              ev("E4", "anything", url="material:M9"),
                              ev("E5", "web quote", url="https://example.org/x")],
                 "claims": [], "relations": []}
        doc, changes = MAT.check_graph(graph, self.run_dir)
        status = {e["id"]: e["quote_status"] for e in doc["evidence"]}
        self.assertEqual(status, {"E1": "v", "E2": "n", "E3": "u", "E4": "u", "E5": "v"})
        self.assertEqual({c["evidence"] for c in changes}, {"E2", "E3", "E4"})
        self.assertEqual(doc["evidence"][0]["acquisition"], "material")


class Cli(_Tmp):
    def cli(self, *args, stdin=None):
        env = dict(os.environ, COLOSSEUM_DATA=os.path.join(self.tmp, "data"))
        r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "colosseum.py")] + list(args),
                           capture_output=True, text=True, env=env, input=stdin)
        return r.returncode, json.loads(r.stdout)

    def test_add_then_verdict_rechecks_material_quotes(self):
        doc_path = self.write("design.md", DESIGN)
        s = ("--session", "s1")
        self.cli("start", *s)
        code, out = self.cli("materials", "add", *s, stdin=json.dumps({"materials": [{"path": doc_path}]}))
        self.assertEqual(code, 0, out)
        self.assertEqual(out["workflow_arg"][0]["id"], "M1")
        self.assertTrue(out["workflow_arg"][0]["path"].endswith(os.path.join("materials", "M1.txt")))
        graph = {"evidence": [ev("E1", "The team has an on-call rotation for a broker.")],
                 "claims": [{"id": "A", "evidence": ["E1"]}, {"id": "B"}],
                 "relations": [{"type": "attack", "subtype": "undercut", "from": "A", "to": "B"}]}
        code, out = self.cli("verdict", *s, "--file", "-", stdin=json.dumps(graph))
        self.assertEqual(out["material_checks"][0]["after"], "u")
        self.assertEqual(out["demoted_undercuts"], [["A", "B"]])
        self.assertEqual(self.cli("materials", "list", *s)[1]["materials"][0]["title"], "design.md")


@unittest.skipUnless(NODE, "node is not installed")
class WorkflowUse(unittest.TestCase):
    def test_debate_reads_materials_first_and_cites_them(self):
        from test_p0 import ClaimIds, debate_rules
        snap = "/runs/r1/materials/M1.txt"
        args = dict(ClaimIds.ARGS, materials=[{"id": "M1", "kind": "file", "title": "design.md", "path": snap}])
        rules = [
            {"label": "^material:M1$", "response": {"summary": "The poller drops events above 200 rps.",
                                                    "passages": [{"quote": "If traffic exceeds 200 requests per second, the poller drops events.", "locator": "line 4"}]}},
            {"label": "^A:draft$", "response": {"position": "no", "key_assumptions": [], "cruxes": [], "strongest_counter": "", "probability": 0.7,
                                                "claims": [{"text": "Bursts are lost", "kind": "fact", "url": "material:M1",
                                                            "quote": "The current poller runs every 5 seconds and misses bursts."}]}},
            {"label": "^read:M1$", "response": {"fetch_failed": False, "passage": "The current poller runs every 5 seconds and misses bursts.",
                                                "context": "The current poller runs every 5 seconds and misses bursts.",
                                                "reliability": "high", "origin": "material:M1", "support": "full"}},
        ] + debate_rules(1)
        out = run_workflow("debate", args, rules)
        self.assertNotIn("error", out, out.get("error"))
        labels = [c["label"] for c in out["calls"]]
        self.assertLess(labels.index("material:M1"), labels.index("fact-base"))
        draft_prompt = next(c["prompt"] for c in out["calls"] if c["label"] == "B:draft")
        self.assertIn("[사용자 자료]", draft_prompt)
        self.assertIn("drops events above 200 rps", draft_prompt)
        self.assertIn("material:M1", draft_prompt)
        e = next(e for e in out["result"]["graph"]["evidence"] if e["url"] == "material:M1")
        self.assertEqual((e["acquisition"], e["quote_status"], e["origin"]), ("material", "v", "material:M1"))
        self.assertFalse(any(c["label"].startswith("fetch:") and "material" in c["prompt"] for c in out["calls"]))
        self.assertEqual(out["result"]["data"]["materials"], [{"id": "M1", "title": "design.md", "kind": "file"}])

    def test_no_materials_means_no_materials_phase(self):
        from test_p0 import ClaimIds, debate_rules
        out = run_workflow("debate", ClaimIds.ARGS, debate_rules(1))
        self.assertFalse(any(c["phase"] == "Materials" for c in out["calls"]))


if __name__ == "__main__":
    unittest.main()
