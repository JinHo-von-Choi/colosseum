"""Agent registry, detection, probing, roster selection and argument-mode relaying."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "colosseum", "scripts")
RELAY = os.path.join(SCRIPTS, "relay.py")
sys.path.insert(0, SCRIPTS)

import relay as R  # noqa: E402

# Records argv, stdin, cwd and the working directory's contents, then answers OK.
RECORDER = """#!/usr/bin/env python3
import json, os, sys
data = sys.stdin.buffer.read()
with open(os.environ["CAPTURE"], "a") as f:
    f.write(json.dumps({"argv": sys.argv[1:], "stdin": data.decode("utf-8", "replace"), "cwd": os.getcwd(),
                        "listing": os.listdir(".")}) + "\\n")
print("OK")
"""
FAILING = "#!/usr/bin/env python3\nimport sys\nsys.stderr.write('not signed in')\nsys.exit(1)\n"


@unittest.skipUnless(os.name == "posix", "POSIX only")
class AgentRelay(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.bin = os.path.join(self.tmp, "bin")
        os.mkdir(self.bin)
        os.symlink(sys.executable, os.path.join(self.bin, "python3"))
        self.capture = os.path.join(self.tmp, "capture")
        self.data = os.path.join(self.tmp, "data")
        os.mkdir(self.data)
        self.env = dict(os.environ, PATH=self.bin, CAPTURE=self.capture, COLOSSEUM_DATA=self.data)
        for k in ("COLOSSEUM_AGENTS", "COLOSSEUM_AGENTS_FILE"):
            self.env.pop(k, None)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def fake(self, name, body=RECORDER):
        p = os.path.join(self.bin, name)
        with open(p, "w") as f:
            f.write(body)
        os.chmod(p, 0o755)

    def user_file(self, doc):
        with open(os.path.join(self.data, "agents.json"), "w") as f:
            json.dump(doc, f)

    def relay(self, *args):
        r = subprocess.run([sys.executable, RELAY] + list(args), capture_output=True, text=True, env=self.env, timeout=120)
        return r.returncode, json.loads(r.stdout) if r.stdout.strip().startswith("{") else r.stdout

    def send(self, cli, text):
        d = self.relay("mktemp")[1]["dir"]
        p = os.path.join(d, "prompt.txt")
        with open(p, "wb") as f:
            f.write(text if isinstance(text, bytes) else text.encode("utf-8"))
        return self.relay("run", "--cli", cli, "--prompt-file", p, "--cleanup")

    def captured(self):
        with open(self.capture) as f:
            return [json.loads(line) for line in f]

    def test_arg_mode_passes_the_prompt_as_one_argument(self):
        self.fake("opencode")
        prompts = ["line\nCOLOSSEUM_EOF\n$(touch pwned) `id` 'q' \"dq\" ; rm -rf /", "-rf --help", "한국어 프롬프트"]
        for text in prompts:
            code, out = self.send("opencode", text)
            self.assertEqual(code, 0, out)
        rows = self.captured()
        self.assertEqual([r["argv"] for r in rows], [["run", prompts[0]], ["run", " -rf --help"], ["run", prompts[2]]])
        self.assertEqual({r["stdin"] for r in rows}, {""})
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "pwned")))
        self.assertEqual(rows[0]["listing"], [], "the agent must start in an empty directory")
        self.assertNotEqual(rows[0]["cwd"], ROOT)

    def test_arg_mode_refuses_nul_and_oversized_prompts(self):
        self.fake("kimi")
        code, out = self.send("kimi", b"a\x00b")
        self.assertIn("NUL", out["error"])
        code, out = self.send("kimi", "x" * (R.MAX_ARG_PROMPT + 1))
        self.assertIn("at most", out["error"])
        self.assertFalse(os.path.exists(self.capture))

    def test_stdin_agents_and_templates(self):
        self.fake("codex")
        self.fake("openclaw")
        self.send("codex", "hello")
        self.send("openclaw", "hello")
        rows = self.captured()
        self.assertEqual(rows[0]["argv"], ["exec", "--sandbox", "read-only", "--skip-git-repo-check", "-"])
        self.assertEqual(rows[0]["stdin"], "hello")
        self.assertEqual(rows[1]["argv"], ["agent", "--agent", "main", "--message", "hello"])

    def test_missing_variable_is_reported_before_running(self):
        self.fake("ollama")
        code, out = self.send("ollama", "hi")
        self.assertIn("vars.model", out["error"])
        self.user_file({"agents": {"ollama": {"vars": {"model": "qwen3"}}}})
        self.send("ollama", "hi")
        self.assertEqual(self.captured()[0]["argv"], ["run", "qwen3"])

    def test_user_file_adds_overrides_disables_and_prefers(self):
        self.fake("myagent")
        self.fake("opencode")
        self.fake("gemini")
        self.fake("kimi")
        self.user_file({"prefer": ["kimi"], "agents": {
            "myagent": {"argv": ["myagent", "--ask", "{prompt}"], "prompt": "arg", "family": "mistral", "priority": 1},
            "opencode": {"family": "zhipu", "family_uncertain": False},
            "gemini": {"disabled": True}}})
        code, out = self.relay("detect")
        ids = [r["id"] for r in out["agents"]]
        self.assertEqual(ids, ["kimi", "myagent", "opencode"])
        self.assertEqual(next(r for r in out["agents"] if r["id"] == "opencode")["family"], "zhipu")
        code, out = self.send("gemini", "x")
        self.assertIn("disabled", out["error"])
        self.send("myagent", "x")
        self.assertEqual(self.captured()[0]["argv"], ["--ask", "x"])
        self.env["COLOSSEUM_AGENTS"] = "opencode"
        code, out = self.relay("detect")
        self.assertEqual(out["agents"][0]["id"], "opencode")

    def test_bad_user_specs_are_refused(self):
        for spec in ({"argv": ["x", "--q={prompt}"], "prompt": "arg"}, {"argv": ["x"], "prompt": "arg"},
                     {"argv": ["{prompt}"], "prompt": "arg"}, {"argv": ["x", "{prompt}"], "prompt": "stdin"},
                     {"argv": [], "prompt": "stdin"}, {"argv": ["x"], "prompt": "file"}):
            self.user_file({"agents": {"bad": spec}})
            code, out = self.relay("list")
            self.assertEqual(code, 2, spec)

    def test_probe_marks_usable_agents_and_is_cached(self):
        self.fake("codex")
        self.fake("kimi")
        self.fake("gemini", FAILING)
        code, out = self.relay("detect", "--probe")
        usable = {r["id"]: r["usable"] for r in out["agents"]}
        self.assertEqual(usable, {"codex": True, "kimi": True, "gemini": False})
        self.assertIn("not signed in", next(r for r in out["agents"] if r["id"] == "gemini")["probe"]["reason"])
        calls = len(self.captured())
        self.relay("detect", "--probe")
        self.assertEqual(len(self.captured()), calls, "a fresh probe result must be reused")
        self.relay("detect", "--probe", "--refresh")
        self.assertGreater(len(self.captured()), calls)
        code, out = self.relay("roster", "--probe", "--seed", "1")
        self.assertEqual(sorted(m.get("cli") for m in out["roster"] if m.get("cli")), ["codex", "kimi"])

    def test_brief_detect_output(self):
        self.fake("hermes")
        r = subprocess.run([sys.executable, RELAY, "detect", "--brief"], capture_output=True, text=True, env=self.env)
        self.assertEqual(r.stdout.strip(), "AGENT hermes family=hermes")


def row(aid, family, priority=10, **kw):
    r = {"id": aid, "name": aid, "provider": aid, "family": family, "family_uncertain": False, "verified": True,
         "prompt": "stdin", "disabled": False, "installed": True, "priority": priority}
    r.update(kw)
    return r


DETECTED = {"agents": [row("codex", "openai"), row("gemini", "google"), row("qwen", "alibaba"),
                       row("opencode", "opencode", family_uncertain=True), row("claude", "claude"),
                       row("dup", "openai")]}


class Roster(unittest.TestCase):
    def test_defaults_take_distinct_families_and_keep_one_claude_seat(self):
        out = R.roster(DETECTED, seed=0)
        clis = [m.get("cli") for m in out["roster"]]
        self.assertEqual(sorted(c for c in clis if c), ["codex", "gemini"])
        self.assertEqual(clis.count(None), 1)
        self.assertEqual(out["cli_juror"], "qwen")
        self.assertFalse(out["homogeneous"])
        self.assertEqual(sorted(m["label"] for m in out["roster"]), ["A", "B", "C"])

    def test_user_named_agents_come_first(self):
        out = R.roster(DETECTED, prefer=["opencode", "dup", "missing"], seed=0)
        self.assertEqual(sorted(m.get("cli") for m in out["roster"] if m.get("cli")), ["dup", "opencode"])
        self.assertEqual(out["unavailable"], ["missing"])
        self.assertTrue(any("family" in n for n in out["notes"]))

    def test_claude_cli_only_when_named_and_only_limits_the_pool(self):
        self.assertNotIn("claude", [m.get("cli") for m in R.roster(DETECTED, size=5, max_cli=4)["roster"]])
        out = R.roster(DETECTED, only=["claude"], seed=0)
        self.assertEqual([m.get("cli") for m in out["roster"] if m.get("cli")], ["claude"])
        out = R.roster(DETECTED, only=["gemini", "qwen", "codex"], max_cli=3, seed=0)
        self.assertEqual(sorted(m["cli"] for m in out["roster"]), ["codex", "gemini", "qwen"])

    def test_unusable_agents_and_empty_detection(self):
        det = {"agents": [row("codex", "openai", usable=False), row("gemini", "google")]}
        out = R.roster(det, seed=0)
        self.assertEqual([m.get("cli") for m in out["roster"] if m.get("cli")], ["gemini"])
        empty = R.roster({"agents": []}, seed=0)
        self.assertTrue(empty["homogeneous"])
        self.assertIsNone(empty["cli_juror"])
        with self.assertRaises(R.RelayError):
            R.roster(DETECTED, size=1)

    def test_label_order_follows_the_seed(self):
        a = R.roster(DETECTED, seed=3)["roster"]
        self.assertEqual(a, R.roster(DETECTED, seed=3)["roster"])


class Registry(unittest.TestCase):
    def test_builtin_registry_is_valid(self):
        with open(R.REGISTRY, encoding="utf-8") as f:
            doc = json.load(f)
        for aid, spec in doc["agents"].items():
            R.validate_spec(aid, spec)
        for aid in ("opencode", "mcode", "kimi", "hermes", "openclaw", "codex", "gemini", "claude"):
            self.assertIn(aid, doc["agents"])


if __name__ == "__main__":
    unittest.main()
