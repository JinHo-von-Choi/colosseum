"""External boundaries: the CLI relay, the audit log and the manual installer."""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "colosseum", "scripts")
RELAY = os.path.join(SCRIPTS, "relay.py")

# Fake CLI: copies stdin to a capture file and echoes a fixed answer.
FAKE_ECHO = """#!/usr/bin/env python3
import os, sys
data = sys.stdin.buffer.read()
open(os.environ["CAPTURE"], "wb").write(data)
sys.stdout.write('{"answer": "ok"}')
"""
# Fake CLI that starts a child and hangs, to test timeouts.
FAKE_HANG = """#!/usr/bin/env python3
import os, subprocess, sys, time
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
open(os.environ["CAPTURE"], "w").write(str(child.pid))
time.sleep(600)
"""

PAYLOADS = [
    "line one\nCOLOSSEUM_EOF\nrm -rf / ; touch pwned\n",
    "$(touch pwned) `touch pwned` ${HOME}",
    "'single' \"double\" \\back\\slash",
    "multi\nline\r\nwindows\n",
    "nul\x00inside",
    "x" * 1_000_000,
]


def alive(pid):
    """True if pid runs. A zombie (killed, waiting to be reaped by init) does not count."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:
        with open("/proc/%d/stat" % pid) as f:
            return f.read().split(") ", 1)[1][0] != "Z"
    except OSError:
        return True


@unittest.skipUnless(os.name == "posix", "POSIX only")
class Relay(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.bin = os.path.join(self.tmp, "bin")
        os.mkdir(self.bin)
        self.capture = os.path.join(self.tmp, "capture")
        self.env = dict(os.environ, PATH=self.bin + os.pathsep + os.environ["PATH"], CAPTURE=self.capture)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def fake(self, name, body):
        p = os.path.join(self.bin, name)
        with open(p, "w") as f:
            f.write(body)
        os.chmod(p, 0o755)

    def relay(self, *args):
        r = subprocess.run([sys.executable, RELAY] + list(args), capture_output=True, text=True, env=self.env,
                           cwd=self.tmp, timeout=60)
        return r.returncode, json.loads(r.stdout)

    def prompt_file(self, data):
        d = self.relay("mktemp")[1]["dir"]
        p = os.path.join(d, "prompt.txt")
        with open(p, "wb") as f:
            f.write(data)
        return d, p

    def test_bytes_arrive_unchanged_and_no_shell_runs(self):
        self.fake("gemini", FAKE_ECHO)
        for text in PAYLOADS:
            data = text.encode("utf-8")
            d, p = self.prompt_file(data)
            code, out = self.relay("run", "--cli", "gemini", "--prompt-file", p, "--cleanup")
            self.assertEqual(code, 0, out)
            self.assertEqual(out["stdout"], '{"answer": "ok"}')
            with open(self.capture, "rb") as f:
                self.assertEqual(f.read(), data)
            self.assertFalse(os.path.exists(d), "prompt directory was not cleaned up")
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "pwned")))

    def test_unsupported_or_missing_cli_fails_before_running(self):
        d, p = self.prompt_file(b"x")
        code, out = self.relay("run", "--cli", "bash", "--prompt-file", p)
        self.assertEqual(code, 2)
        self.assertIn("unsupported", out["error"])
        code, out = self.relay("run", "--cli", "aichat", "--prompt-file", p)
        self.assertIn("not installed", out["error"])

    def test_prompt_must_come_from_a_relay_directory(self):
        self.fake("llm", FAKE_ECHO)
        stray = os.path.join(self.tmp, "secret.txt")
        with open(stray, "w") as f:
            f.write("do not send")
        code, out = self.relay("run", "--cli", "llm", "--prompt-file", stray)
        self.assertEqual(code, 2)
        self.assertFalse(os.path.exists(self.capture))

    def test_timeout_kills_the_cli_and_its_children(self):
        self.fake("llm", FAKE_HANG)
        d, p = self.prompt_file(b"x")
        start = time.time()
        code, out = self.relay("run", "--cli", "llm", "--prompt-file", p, "--timeout", "2", "--cleanup")
        self.assertLess(time.time() - start, 30)
        self.assertTrue(out["timed_out"])
        self.assertEqual(code, 2)
        with open(self.capture) as f:
            child = int(f.read())
        time.sleep(0.2)
        self.assertFalse(alive(child), "the CLI's child process survived the timeout")
        self.assertFalse(os.path.exists(d))

    def test_output_is_capped(self):
        self.fake("gemini", "#!/usr/bin/env python3\nimport sys\nsys.stdin.read()\nsys.stdout.write('y' * 5000)\n")
        d, p = self.prompt_file(b"x")
        code, out = self.relay("run", "--cli", "gemini", "--prompt-file", p, "--max-output", "100", "--cleanup")
        self.assertTrue(out["truncated"])
        self.assertEqual(len(out["stdout"]), 100)


class AuditLog(unittest.TestCase):
    SECRET = "sk-SYNTHETICSECRET123456"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = dict(os.environ, COLOSSEUM_DATA=self.tmp.name)
        self.env.pop("COLOSSEUM_DEBUG_LOG", None)

    def tearDown(self):
        self.tmp.cleanup()

    def run_post(self, env):
        r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "colosseum.py"), "start", "--session", "s"],
                           capture_output=True, text=True, env=env)
        run_dir = json.loads(r.stdout)["run_dir"]
        event = {"session_id": "s", "tool_name": "WebFetch",
                 "tool_input": {"url": "https://user:pw@api.example/x?api_key=%s&q=1#frag" % self.SECRET,
                                "prompt": "Authorization: Bearer %s" % self.SECRET},
                 "tool_response": {"error": "401 for token=%s" % self.SECRET}}
        subprocess.run([sys.executable, os.path.join(SCRIPTS, "hook.py"), "post"], input=json.dumps(event),
                       capture_output=True, text=True, env=env)
        path = os.path.join(run_dir, "sources.jsonl")
        with open(path) as f:
            return path, f.read()

    def test_default_log_holds_no_secrets_or_raw_text(self):
        path, text = self.run_post(self.env)
        self.assertNotIn(self.SECRET, text)
        self.assertNotIn("pw@", text)
        rec = json.loads(text)
        self.assertFalse(rec["ok"])
        self.assertNotIn("debug", rec)
        self.assertEqual(rec["url"], "https://api.example/x?api_key=REDACTED&q=1")
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)

    def test_debug_log_is_opt_in_and_still_redacted(self):
        path, text = self.run_post(dict(self.env, COLOSSEUM_DEBUG_LOG="1"))
        self.assertIn("debug", json.loads(text))
        self.assertNotIn(self.SECRET, text)


@unittest.skipUnless(shutil.which("bash") and shutil.which("git"), "bash and git are needed")
class Installer(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.dest = os.path.join(self.home, ".claude", "skills", "colosseum")
        self.src = os.path.join(ROOT, "skills", "colosseum")

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    @staticmethod
    def write(path, text):
        with open(path, "w") as f:
            f.write(text)

    def install(self):
        env = dict(os.environ, HOME=self.home)
        env.pop("COLOSSEUM_INSTALL_DEST", None)
        return subprocess.run(["bash", os.path.join(ROOT, "install.sh")], capture_output=True, text=True, env=env)

    def test_fresh_install_and_rerun(self):
        self.assertEqual(self.install().returncode, 0)
        self.assertEqual(os.readlink(self.dest), self.src)
        r = self.install()
        self.assertEqual(r.returncode, 0)
        self.assertIn("already installed", r.stdout)

    def test_old_skill_md_only_install_is_migrated(self):
        os.makedirs(self.dest)
        os.symlink(os.path.join(self.src, "SKILL.md"), os.path.join(self.dest, "SKILL.md"))
        self.assertEqual(self.install().returncode, 0)
        self.assertEqual(os.readlink(self.dest), self.src)

    def test_conflicts_are_preserved(self):
        os.makedirs(os.path.dirname(self.dest))
        cases = {
            "file": lambda: self.write(self.dest, "mine"),
            "directory": lambda: os.makedirs(os.path.join(self.dest, "notes")),
            "other link": lambda: os.symlink(self.home, self.dest),
            "broken link": lambda: os.symlink(os.path.join(self.home, "missing"), self.dest),
        }
        for name, make in cases.items():
            make()
            before = os.readlink(self.dest) if os.path.islink(self.dest) else None
            r = self.install()
            self.assertEqual(r.returncode, 1, name)
            self.assertIn("conflict", r.stderr, name)
            self.assertTrue(os.path.lexists(self.dest), name)
            if before is not None:
                self.assertEqual(os.readlink(self.dest), before, name)
            if os.path.islink(self.dest) or os.path.isfile(self.dest):
                os.unlink(self.dest)
            else:
                shutil.rmtree(self.dest)


if __name__ == "__main__":
    unittest.main()
