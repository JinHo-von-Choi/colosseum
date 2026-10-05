"""Regression tests for the P0 defects found in the 3.1.0-beta.1 review.

Each defect is reproduced next to a control that must keep working:
quote reversals accepted as checked, support assessments shared between claims,
snippet checks approved without matching text, claim id collisions between issues,
stale data from an earlier run, and lost forecast writes.
"""
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "skills", "colosseum", "scripts"))
sys.path.insert(0, HERE)

import graph as G  # noqa: E402
import quote_match as Q  # noqa: E402
import verdict_engine as V  # noqa: E402
from workflow_harness import NODE, run_runtime, run_workflow  # noqa: E402


def fixture(name):
    with open(os.path.join(HERE, "fixtures", name), encoding="utf-8") as f:
        return json.load(f)


class QuoteReversals(unittest.TestCase):
    def test_python(self):
        d = fixture("p0_quotes.json")
        for c in d["cases"]:
            r = Q.match(c["quote"], d["pages"][c["page"]])
            self.assertEqual(r["status"], c["expect"], (c, r))
            if c.get("reason_prefix"):
                self.assertTrue(r["reason"].startswith(c["reason_prefix"]), (c, r))

    def test_reversals_never_count_as_checked(self):
        d = fixture("p0_quotes.json")
        for c in d["cases"]:
            if c.get("control"):
                continue
            status = Q.match(c["quote"], d["pages"][c["page"]])["status"]
            e = {"id": "E1", "reliability": "high", "quote_status": status, "support": "full"}
            self.assertFalse(G.eligible(e), c)
            self.assertEqual(G.evidence_score(e), 0.0, c)

    @unittest.skipUnless(NODE, "node is not installed")
    def test_javascript_matches_python(self):
        d = fixture("p0_quotes.json")
        script = "return %s.map(([q, p]) => LIB.matchQuote(q, p))" % json.dumps(
            [[c["quote"], d["pages"][c["page"]]] for c in d["cases"]], ensure_ascii=False)
        out = run_runtime(script, {}, [])
        self.assertNotIn("error", out, out.get("error"))
        for c, j in zip(d["cases"], out["result"]):
            self.assertEqual(Q.match(c["quote"], d["pages"][c["page"]]), j, c)


PAGE = "The drug is not effective in adults. If the patient is over 65, the dose must be halved."
URL = "https://example.org/drug"


def fetch_rule(url, passage, support="full", failed=False):
    return {"label": "^fetch:", "prompt": url, "response": {
        "fetch_failed": failed, "passage": passage, "context": passage, "reliability": "high",
        "origin": "example", "freshness": "fresh", "support": support, "support_reason": "stub"}}


@unittest.skipUnless(NODE, "node is not installed")
class SupportCache(unittest.TestCase):
    RULES = [
        fetch_rule(URL, PAGE, support="full"),
        {"label": "^support:", "prompt": "주장: The drug works in adults", "response": {"support": "none", "support_reason": "opposite"}},
        {"label": "^support:", "response": {"support": "full", "support_reason": "same"}},
    ]

    def run_case(self, script):
        out = run_runtime(script, {"question": "q"}, self.RULES)
        self.assertNotIn("error", out, out.get("error"))
        return out

    def test_same_quote_for_opposite_claims_keeps_both_assessments(self):
        out = self.run_case("""
          const q = 'The drug is not effective in adults'
          const [a, b] = await checkClaims([
            { text: 'The drug does not work in adults', url: '%s', quote: q },
            { text: 'The drug works in adults', url: '%s', quote: q }], 'Verify', ['c1', 'c2'])
          return { a, b }""" % (URL, URL))
        a, b = out["result"]["a"], out["result"]["b"]
        self.assertEqual((a["quote_status"], a["support"]), ("v", "full"))
        self.assertEqual((b["quote_status"], b["support"]), ("v", "none"))
        self.assertNotEqual(a["id"], b["id"])
        self.assertEqual(sum(1 for c in out["calls"] if c["label"].startswith("fetch:")), 1)
        self.assertEqual(sum(1 for c in out["calls"] if c["label"].startswith("support:")), 1)

    def test_retry_reuses_and_changed_text_reassesses(self):
        out = self.run_case("""
          const q = 'The drug is not effective in adults'
          const e1 = await checkEvidence('%s', q, 'The drug does not work in adults', 'Verify', 'c1')
          const e2 = await checkEvidence('%s', q, 'The drug does not work in adults', 'Verify', 'c1')
          const e3 = await checkEvidence('%s', q, 'The drug works in adults', 'Verify', 'c1')
          return { same: e1 === e2, e1: e1.id, e3: e3.id, s3: e3.support }""" % (URL, URL, URL))
        r = out["result"]
        self.assertTrue(r["same"])
        self.assertNotEqual(r["e1"], r["e3"])
        self.assertEqual(r["s3"], "none")

    def test_dropped_condition_is_review_required(self):
        out = self.run_case("""
          return await checkEvidence('%s', 'the dose must be halved', 'Halve the dose for everyone', 'Verify', 'c1')""" % URL)
        e = out["result"]
        self.assertEqual(e["quote_status"], "n")
        self.assertIn("if", e["match"]["reason"])
        self.assertFalse(G.eligible(dict(e, support="full")))


@unittest.skipUnless(NODE, "node is not installed")
class SnippetChecks(unittest.TestCase):
    def test_unrelated_snippet_is_not_checked(self):
        rules = [fetch_rule("https://a.example/", "", failed=True),
                 {"label": "^snippet:", "response": {"snippet": "An unrelated headline about adults", "reliability": "high", "origin": "a", "support": "full"}}]
        out = run_runtime("return await checkEvidence('https://a.example/', 'The drug is not effective in adults', 'claim', 'Verify', 'c1')", {}, rules)
        e = out["result"]
        self.assertEqual((e["acquisition"], e["quote_status"]), ("snippet", "u"))
        self.assertFalse(G.eligible({"quote_status": e["quote_status"], "support": "full"}))

    def test_snippet_with_the_quote_is_snippet_level_and_reported_as_mixed(self):
        rules = [fetch_rule("https://a.example/", "", failed=True),
                 fetch_rule("https://b.example/", PAGE),
                 {"label": "^snippet:", "response": {"snippet": "Study: The drug is not effective in adults.", "reliability": "medium", "origin": "a", "support": "full"}},
                 {"label": "^support:", "response": {"support": "full"}}]
        out = run_runtime("""
          const a = await checkEvidence('https://a.example/', 'The drug is not effective in adults', 'x', 'Verify', 'c1')
          const b = await checkEvidence('https://b.example/', 'The drug is not effective in adults', 'x', 'Verify', 'c2')
          return { a, b, summary: verificationSummary() }""", {}, rules)
        r = out["result"]
        self.assertEqual((r["a"]["acquisition"], r["a"]["quote_status"]), ("snippet", "snippet"))
        self.assertEqual((r["b"]["acquisition"], r["b"]["quote_status"]), ("full_page", "v"))
        self.assertEqual((r["summary"]["full_page"], r["summary"]["snippet"]), (1, 1))
        self.assertTrue(r["summary"]["label"].startswith("혼합"))


def debate_rules(n_issues):
    page2 = "Trials found the drug effective in children under 12."
    issues = [{"question": "issue %d" % i, "kind": "empirical", "a_label": "A", "a_claim": i, "b_label": "B",
               "b_claim": i, "changes_answer": True} for i in range(n_issues)]

    def draft(position, text, quote, url):
        return {"position": position, "claims": [{"text": text + " %d" % i, "kind": "fact", "url": url, "quote": quote}
                                                 for i in range(n_issues)],
                "key_assumptions": [], "cruxes": [], "strongest_counter": "", "probability": 0.7}
    return [
        {"label": "^fact-base$", "response": {"facts": []}},
        {"label": "^A:draft$", "response": draft("no", "Not effective", "The drug is not effective in adults", URL)},
        {"label": "^B:draft$", "response": draft("yes", "Effective in children", "Trials found the drug effective in children under 12", "https://example.net/trial")},
        {"label": "^C:draft$", "response": draft("no", "No effect", "The drug is not effective in adults", URL)},
        fetch_rule(URL, PAGE),
        fetch_rule("https://example.net/trial", page2),
        {"label": "^support:", "response": {"support": "full"}},
        {"label": "^group-positions$", "response": {"groups": [{"id": "P1", "labels": ["A", "C"], "summary": "no"},
                                                                {"id": "P2", "labels": ["B"], "summary": "yes"}]}},
        {"label": "^issue-map$", "response": {"issues": issues}},
        {"label": "^B:prosecutor$", "response": {"steelman": "s", "attack_subtype": "rebut", "attack": "a", "position_update": "",
                                                 "claims": [{"text": "Children respond", "kind": "fact", "url": "https://example.net/trial",
                                                             "quote": "Trials found the drug effective in children under 12"}]}},
        {"label": "^C:adverse_witness$", "response": {"premise": "p", "verdict": "holds", "if_false": "", "claims": []}},
        {"label": "^A:defender$", "response": {"steelman_check": "faithful", "response": "rebut", "text": "t", "change_basis": "", "position": "no",
                                               "claims": [{"text": "Adults differ", "kind": "fact", "url": URL, "quote": "The drug is not effective in adults"}]}},
        {"label": "^juror:", "response": {"winner": "first", "reason": "r"}},
        {"label": ":premortem$", "response": {"causes": [], "underconfidence": "", "claims": []}},
        {"label": "^report$", "response": "REPORT"},
    ]


@unittest.skipUnless(NODE, "node is not installed")
class ClaimIds(unittest.TestCase):
    ARGS = {"question": "Is the drug effective?", "stakes": "high", "max_rounds": 1, "run_id": "run-test",
            "roster": [{"label": "A", "family": "claude"}, {"label": "B", "family": "claude"}, {"label": "C", "family": "claude"}]}

    def run_debate(self, n_issues):
        out = run_workflow("debate", self.ARGS, debate_rules(n_issues))
        self.assertNotIn("error", out, out.get("error"))
        return out["result"]

    def test_two_issues_with_the_same_pair_finish_without_collisions(self):
        for n in (2, 4):
            res = self.run_debate(n)
            ids = [c["id"] for c in res["graph"]["claims"]]
            self.assertEqual(len(ids), len(set(ids)), ids)
            self.assertEqual(res["report"], "REPORT")
            self.assertEqual(res["graph"]["run_id"], "run-test")
            pro = [c for c in res["graph"]["claims"] if c["role"] == "pro"]
            self.assertEqual(len(pro), min(n, 2))
            by_id = {c["id"]: c for c in res["graph"]["claims"]}
            rebuttals = [r for r in res["graph"]["relations"] if by_id[r["from"]]["role"] == "def"]
            self.assertTrue(rebuttals)
            for r in rebuttals:
                self.assertEqual(by_id[r["from"]]["issue"], by_id[r["to"]]["issue"], r)
            self.assertEqual(V.verdict(res["graph"])["status"], res["verdict"]["status"])

    def test_issue_order_changes_ids_but_not_verdicts(self):
        a = self.run_debate(2)
        rules = debate_rules(2)
        for r in rules:
            if r["label"] == "^issue-map$":
                r["response"]["issues"].reverse()
        out = run_workflow("debate", self.ARGS, rules)
        self.assertNotIn("error", out, out.get("error"))
        b = out["result"]
        status = lambda res: sorted(res["verdict"]["status"].values())
        self.assertEqual(status(a), status(b))


SCRIPTS = os.path.join(ROOT, "skills", "colosseum", "scripts")


class _Cli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = dict(os.environ, COLOSSEUM_DATA=self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def cli(self, *args, stdin=None):
        r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "colosseum.py")] + list(args),
                           capture_output=True, text=True, env=self.env, input=stdin)
        return r.returncode, json.loads(r.stdout)


class RunIsolation(_Cli):
    S = ("--session", "s1")
    DRAFTS = {"drafts": [{"label": "A", "family": "claude", "position": "X", "probability": 0.8},
                         {"label": "B", "family": "gemini", "position": "X", "probability": 0.9}]}

    def complete_old_run(self):
        code, old = self.cli("start", *self.S, "--question-file", "-", stdin="Old question")
        self.assertEqual(code, 0)
        for phase in ("fact_base", "drafts"):
            self.cli("advance", *self.S, "--to", phase)
        self.assertEqual(self.cli("baseline", *self.S, "--file", "-", stdin=json.dumps(self.DRAFTS))[0], 0)
        self.cli("advance", *self.S, "--to", "verdict")
        self.assertEqual(self.cli("verdict", *self.S, "--file", "-", stdin=json.dumps(fixture("t2.json")))[0], 0)
        self.assertEqual(self.cli("finish", *self.S)[1]["status"], "completed")
        return old

    def test_new_question_never_reads_the_old_runs_files(self):
        old = self.complete_old_run()
        code, new = self.cli("start", *self.S, "--question-file", "-", stdin="New question")
        self.assertEqual(code, 0)
        self.assertNotEqual(old["run_id"], new["run_id"])
        self.assertNotEqual(old["question_sha256"], new["question_sha256"])
        for cmd in ("baseline", "verdict", "metrics"):
            code, out = self.cli(cmd, *self.S)
            self.assertEqual(code, 2, (cmd, out))
            self.assertIn("not in run", out["refused"])
        code, out = self.cli("baseline", *self.S, "--run", old["run_id"])
        self.assertEqual((code, out["baseline_vote"]), (0, "X"))
        self.assertEqual(self.cli("status", *self.S)[1]["phase"], "plan")

    def test_start_refuses_while_running_and_restart_isolates(self):
        code, first = self.cli("start", *self.S, "--question-file", "-", stdin="Q")
        code, out = self.cli("start", *self.S, "--question-file", "-", stdin="Q")
        self.assertEqual(code, 2)
        self.assertIn("resume", out["refused"])
        code, second = self.cli("restart", *self.S, "--question-file", "-", stdin="Q")
        self.assertEqual((code, second["previous"]), (0, first["run_id"]))
        runs = {r["run_id"]: r["status"] for r in self.cli("runs", *self.S)[1]["runs"]}
        self.assertEqual(runs, {first["run_id"]: "interrupted", second["run_id"]: "running"})

    def test_resume_continues_from_the_checkpoint(self):
        code, run = self.cli("start", *self.S, "--question-file", "-", stdin="Q")
        for phase in ("fact_base", "drafts"):
            self.cli("advance", *self.S, "--to", phase)
        # The moderator process dies here; the checkpoint is what is on disk.
        code, out = self.cli("resume", *self.S, "--expect-question-sha", run["question_sha256"])
        self.assertEqual((code, out["run_id"], out["phase"]), (0, run["run_id"], "drafts"))
        code, out = self.cli("resume", *self.S, "--expect-question-sha", "0" * 16)
        self.assertEqual(code, 2)
        self.cli("cancel", *self.S)
        code, out = self.cli("resume", *self.S)
        self.assertIn("cancelled", out["refused"])

    def test_wrong_checkpoint_version_is_refused(self):
        sdir = os.path.join(self.tmp.name, "sessions", "s1")
        os.makedirs(sdir)
        with open(os.path.join(sdir, "state.json"), "w") as f:
            json.dump({"schema": "colosseum.state/v1", "status": "running", "phase": "round"}, f)
        code, out = self.cli("resume", *self.S)
        self.assertEqual(code, 2)
        self.assertIn("not supported", out["refused"])
        self.assertEqual(self.cli("advance", *self.S, "--to", "verdict")[0], 2)
        code, out = self.cli("restart", *self.S)
        self.assertEqual(code, 0)

    def test_limits_and_permissions(self):
        self.assertEqual(self.cli("start", *self.S, "--search-budget", "26")[0], 2)
        self.assertEqual(self.cli("start", *self.S, "--max-rounds", "4")[0], 2)
        code, run = self.cli("start", *self.S)
        self.cli("advance", *self.S, "--to", "fact_base")
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(os.stat(run["run_dir"]).st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.tmp.name, "sessions", "s1", "state.json")).st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
