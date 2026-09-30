"""The workflow's JavaScript library must agree with the Python scripts.

Runs the colosseum-lib block of workflows/debate.js under Node on the same inputs the
Python modules see. Skipped when Node is not installed.
"""
import glob
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOW = os.path.join(ROOT, "workflows", "debate.js")
sys.path.insert(0, os.path.join(ROOT, "skills", "colosseum", "scripts"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import baseline as B  # noqa: E402
import metrics as M  # noqa: E402
import modes as MO  # noqa: E402
import quote_match as Q  # noqa: E402
import verdict_engine as V  # noqa: E402

NODE = shutil.which("node")

RUNNER = """
const fs = require('fs')
const input = JSON.parse(fs.readFileSync(0, 'utf8'))
const out = input.map(([fn, argsList]) => LIB[fn](...argsList))
process.stdout.write(JSON.stringify(out))
"""


def lib_source():
    with open(WORKFLOW, encoding="utf-8") as f:
        text = f.read()
    m = re.search(r"// ==== colosseum-lib begin ====(.*)// ==== colosseum-lib end ====", text, re.DOTALL)
    return m.group(1)


def run_js(calls):
    with tempfile.NamedTemporaryFile("w", suffix=".cjs", delete=False, encoding="utf-8") as f:
        f.write(lib_source() + RUNNER)
        path = f.name
    try:
        r = subprocess.run([NODE, path], input=json.dumps(calls), capture_output=True, text=True, check=True)
        return json.loads(r.stdout)
    finally:
        os.unlink(path)


def fixture(name):
    with open(os.path.join(ROOT, "tests", "fixtures", name), encoding="utf-8") as f:
        return json.load(f)


def random_graph(rng, n):
    rel = ["high", "medium", "low"]
    qs = ["v", "n", "snippet", "u"]
    sup = ["full", "partial", "none"]
    evidence = [{"id": "E%d" % i, "reliability": rng.choice(rel), "quote_status": rng.choice(qs),
                 "support": rng.choice(sup), "origin": "o%d" % rng.randrange(4)} for i in range(n)]
    claims = [{"id": "C%d" % i, "author": rng.choice("ABC"),
               "evidence": rng.sample([e["id"] for e in evidence], rng.randrange(0, 3))} for i in range(n)]
    relations = []
    for _ in range(n + 2):
        a, b = rng.sample([c["id"] for c in claims], 2)
        if rng.random() < 0.8:
            relations.append({"type": "attack", "subtype": rng.choice(["rebut", "undercut", "undermine"]), "from": a, "to": b})
        else:
            relations.append({"type": "support", "from": a, "to": b})
    conflicts = [{"a": "C0", "b": "C1"}, {"a": "C2", "b": "C3"}]
    final = [{"claim": c["id"], "weight": rng.choice([2, 3])} for c in claims[:3]]
    return {"evidence": evidence, "claims": claims, "relations": relations, "conflicts": conflicts, "final": final}


def comparable_verdict(v):
    return {"labels": v["labels"], "status": v["status"], "conflicts": [(c["verdict"], c["status"]) for c in v["conflicts"]],
            "strength": {k: round(x, 2) for k, x in v["strength"].items()},
            "preferred": v["preferred"], "stable": v["stable"]}


@unittest.skipUnless(NODE, "node is not installed")
class JsParity(unittest.TestCase):
    def test_verdicts_on_fixtures_and_random_graphs(self):
        rng = random.Random(7)
        docs = [fixture(n) for n in ("t1.json", "t2.json", "t3.json")] + [random_graph(rng, rng.randrange(4, 9)) for _ in range(40)]
        js = run_js([["verdict", [d]] for d in docs])
        for d, j in zip(docs, js):
            self.assertEqual(comparable_verdict(V.verdict(d)), comparable_verdict(j))

    def test_checklist(self):
        rng = random.Random(11)
        docs = [random_graph(rng, 6) for _ in range(20)]
        js = run_js([["checklist", [d]] for d in docs])
        for d, j in zip(docs, js):
            self.assertEqual(json.loads(json.dumps(M.checklist(d))), j)

    def test_quote_matching(self):
        d = fixture("quotes.json")
        cases = [c["quote"] for c in d["cases"]] + [
            "Resignations fell by 43% among workers who shifted from full-time office work to a hybrid schedule"]
        js = run_js([["matchQuote", [q, d["page"]]] for q in cases])
        for q, j in zip(cases, js):
            self.assertEqual(Q.match(q, d["page"])["status"], j["status"], q)
        page = "재택근무를 병행한 직원의 퇴사율은 33% 낮아졌고 성과 평가에는 차이가 없었다."
        self.assertEqual(run_js([["matchQuote", ["퇴사율은 33% 낮아졌고", page]]])[0]["status"], "v")

    def test_baseline(self):
        rng = random.Random(3)
        docs = []
        for _ in range(30):
            n = rng.randrange(2, 5)
            docs.append({"drafts": [{"label": "L%d" % i, "family": rng.choice(["claude", "gemini", "gpt"]),
                                     "position": rng.choice(["P1", "P2"]), "probability": round(rng.uniform(0.3, 0.95), 2)}
                                    for i in range(n)]})
        js = run_js([["baseline", [d]] for d in docs])
        for d, j in zip(docs, js):
            py = B.baseline(d)
            for key in ("baseline_vote", "tie", "p0", "roster", "unanimous", "skip_debate", "needs_dissenter"):
                self.assertEqual(py[key], j[key], key)


    def test_mode_aggregation(self):
        rng = random.Random(5)
        ballots = [[rng.sample(["I1", "I2", "I3", "I4", "I5", "I6"], rng.randrange(1, 6)) for _ in range(rng.randrange(2, 5))]
                   for _ in range(20)]
        js = run_js([["borda", [b]] for b in ballots])
        for b, j in zip(ballots, js):
            self.assertEqual(MO.borda(b), j)
        ests = [[{"label": "L%d" % i, "family": rng.choice("abc"), "value": round(rng.uniform(0, 1), 3)}
                 for i in range(rng.randrange(2, 6))] for _ in range(20)]
        js = run_js([["delphiFeedback", [e]] for e in ests] + [["familyMedian", [e]] for e in ests])
        for e, j in zip(ests, js[:20]):
            py = MO.delphi_feedback(e)
            self.assertAlmostEqual(py["median"], j["median"])
            self.assertEqual((py["above"], py["below"]), (j["above"], j["below"]))
        for e, j in zip(ests, js[20:]):
            self.assertAlmostEqual(MO.family_median(e), j)
        moves = [(0.4, 0.7, False), (0.4, 0.7, True), (0.5, 0.45, False), (100, 150, False, 100)]
        js = run_js([["limitMove", list(m)] for m in moves])
        for m, j in zip(moves, js):
            py = MO.limit_move(*m)
            self.assertAlmostEqual(py["value"], j["value"])
            self.assertEqual(py["capped"], j["capped"])

    def test_ach_and_pooling(self):
        rng = random.Random(9)
        hs = ["H1", "H2", "H3", "H0"]
        for _ in range(15):
            rows = [{"id": "E%d" % i, "quote_status": rng.choice(["v", "n", "snippet", "u"]),
                     "reliability": rng.choice(["high", "medium", "low"]),
                     "ratings": {h: rng.choice("CIN") for h in hs}} for i in range(rng.randrange(1, 7))]
            entries = [{"family": rng.choice("ab"), "dist": {h: round(rng.uniform(0, 1), 2) for h in hs}} for _ in range(3)]
            j_ach, j_pool = run_js([["ach", [hs, rows]], ["logLinearPool", [entries, hs]]])
            self.assertEqual(MO.ach(hs, rows), j_ach)
            py_pool = MO.log_linear_pool(entries, hs)
            for h in hs:
                self.assertAlmostEqual(py_pool[h], j_pool[h], places=2)


def workflow_files():
    return sorted(glob.glob(os.path.join(ROOT, "workflows", "*.js")))


@unittest.skipUnless(NODE, "node is not installed")
class WorkflowSyntax(unittest.TestCase):
    def test_scripts_parse(self):
        for path in workflow_files():
            with open(path, encoding="utf-8") as f:
                body = f.read().replace("export const meta", "const meta", 1)
            with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
                f.write("(async function () {\n" + body + "\n})\n")
                tmp = f.name
            try:
                r = subprocess.run([NODE, "--check", tmp], capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, path + r.stderr)
            finally:
                os.unlink(tmp)


class WorkflowStructure(unittest.TestCase):
    def test_meta_is_pure_literal_with_matching_phases(self):
        for path in workflow_files():
            with open(path, encoding="utf-8") as f:
                text = f.read()
            meta = text[text.index("export const meta"):text.index("\n}\n") + 2]
            self.assertNotIn("${", meta, path)
            self.assertIn("name: '%s'" % os.path.basename(path)[:-3], meta)
            titles = re.findall(r"title: '([^']+)'", meta)
            used = set(re.findall(r"phase\('([^']+)'\)", text))
            self.assertTrue(used <= set(titles), (path, used - set(titles)))

    def test_shared_blocks_are_identical(self):
        def blocks(path):
            with open(path, encoding="utf-8") as f:
                text = f.read()
            return [re.search(r"// ==== %s begin ====.*?// ==== %s end ====" % (n, n), text, re.DOTALL).group(0)
                    for n in ("colosseum-lib", "colosseum-runtime")]
        ref = blocks(WORKFLOW)
        for path in workflow_files():
            self.assertEqual(blocks(path), ref, "%s drifted; run python3 tools/sync_workflow_blocks.py" % path)


if __name__ == "__main__":
    unittest.main()
