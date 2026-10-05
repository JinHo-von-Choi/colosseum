"""Relay one prompt to an allowlisted external AI CLI without a shell.

  relay.py mktemp
      print a new private directory (0700) for the prompt file
  relay.py run --cli gemini|llm|aichat --prompt-file <path> [--timeout 180] [--max-output 200000] [--cleanup]
      run the CLI with a fixed argument array and the prompt bytes on stdin

The prompt is never placed on a command line or in a shell string, so no character
sequence in it (heredoc terminators, $( ), quotes, newlines, NUL) can reach a shell.
On timeout the whole process group is killed. --cleanup removes the prompt file, and
its directory when relay.py created it. Prints one JSON object; exit code 0 when the
CLI ran and exited 0, 2 otherwise.
"""
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile

# Fixed argument arrays. Each CLI reads the prompt from stdin in non-interactive mode.
CLIS = {
    "gemini": ["gemini"],
    "llm": ["llm"],
    "aichat": ["aichat"],
}
DEFAULT_TIMEOUT = 180
MAX_TIMEOUT = 600
DEFAULT_MAX_OUTPUT = 200000
MARKER = ".colosseum-relay"


def emit(obj, code):
    print(json.dumps(obj, ensure_ascii=False))
    return code


def make_dir():
    d = tempfile.mkdtemp(prefix="colosseum-relay-")
    os.chmod(d, 0o700)
    open(os.path.join(d, MARKER), "w").close()
    return d


def cleanup(prompt_file):
    try:
        os.unlink(prompt_file)
    except OSError:
        pass
    d = os.path.dirname(os.path.abspath(prompt_file))
    if os.path.exists(os.path.join(d, MARKER)):
        shutil.rmtree(d, ignore_errors=True)


def run(cli, prompt_file, timeout=DEFAULT_TIMEOUT, max_output=DEFAULT_MAX_OUTPUT):
    if cli not in CLIS:
        return {"ok": False, "error": "unsupported CLI %r; allowed: %s" % (cli, sorted(CLIS))}
    if not 1 <= timeout <= MAX_TIMEOUT:
        return {"ok": False, "error": "timeout must be between 1 and %d seconds" % MAX_TIMEOUT}
    if not os.path.exists(os.path.join(os.path.dirname(os.path.abspath(prompt_file)), MARKER)):
        return {"ok": False, "error": "the prompt file must be inside a directory made by `relay.py mktemp`"}
    exe = shutil.which(CLIS[cli][0])
    if not exe:
        return {"ok": False, "error": "%s is not installed" % cli}
    with open(prompt_file, "rb") as f:
        prompt = f.read()
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        proc = subprocess.Popen([exe] + CLIS[cli][1:], stdin=subprocess.PIPE, stdout=out, stderr=err,
                                start_new_session=True, close_fds=True)

        def cancel(signum, _frame):
            # The relay itself is being stopped: take the CLI's process group with it.
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            raise SystemExit(128 + signum)

        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            signal.signal(sig, cancel)
        timed_out = False
        try:
            proc.communicate(prompt, timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
        except BrokenPipeError:
            proc.wait(timeout)
        finally:
            # Kill the whole group: the CLI's own children must not outlive the relay.
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            proc.wait()
        out.seek(0)
        data = out.read(max_output + 1)
        err.seek(0)
        err_data = err.read()[-2000:]
    return {"ok": not timed_out and proc.returncode == 0, "cli": cli, "exit_code": None if timed_out else proc.returncode,
            "timed_out": timed_out, "truncated": len(data) > max_output,
            "stdout": data[:max_output].decode("utf-8", errors="replace"),
            "stderr_tail": err_data.decode("utf-8", errors="replace"), "prompt_bytes": len(prompt)}


def main(argv):
    import argparse
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("mktemp")
    r = sub.add_parser("run")
    r.add_argument("--cli", required=True)
    r.add_argument("--prompt-file", required=True)
    r.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    r.add_argument("--max-output", type=int, default=DEFAULT_MAX_OUTPUT)
    r.add_argument("--cleanup", action="store_true")
    a = p.parse_args(argv)
    if a.cmd == "mktemp":
        return emit({"dir": make_dir()}, 0)
    out = {"ok": False, "error": "cancelled"}
    try:
        out = run(a.cli, a.prompt_file, a.timeout, a.max_output)
    except OSError as e:
        out = {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}
    finally:
        if a.cleanup:
            cleanup(a.prompt_file)
    return emit(out, 0 if out.get("ok") else 2)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
