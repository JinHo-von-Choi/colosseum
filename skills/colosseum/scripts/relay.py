"""Find, choose and run external AI agent CLIs without a shell.

  relay.py list [--data DIR]
      every agent in the registry (agents.json plus the user file) and whether it is installed
  relay.py detect [--probe] [--refresh] [--data DIR]
      installed agents in preference order; --probe sends a one-word test prompt to each
      and keeps the result for 24 hours, so "usable" means installed, signed in and answering
  relay.py roster [--size 3] [--prefer codex,kimi] [--only ...] [--max-cli N] [--probe] [--seed N]
      a participant roster for the workflows: user-named agents first, then installed agents
      by priority, one per model family, the rest filled with Claude participants
  relay.py mktemp
      print a new private directory (0700) for the prompt file
  relay.py run --cli <id> --prompt-file <path> [--timeout 180] [--max-output 200000] [--cleanup]
      run one agent with its fixed argument array

The registry is skills/colosseum/scripts/agents.json. A user file at <data>/agents.json, or
the file named by $COLOSSEUM_AGENTS_FILE, can add agents, override fields, disable an agent
("disabled": true) and list preferred ids ("prefer"). $COLOSSEUM_AGENTS (comma separated)
also names preferred agents.

Prompts never pass through a shell. An agent marked "prompt": "stdin" gets the prompt bytes
on stdin. One marked "prompt": "arg" gets it as one argv element (the operating system
refuses NUL bytes and over-long arguments); a prompt that starts with "-" is prefixed with
a space so it cannot be read as an option. Every agent runs in an empty private working directory, so
a coding agent has no repository to edit. On timeout or cancellation the agent's whole
process group is killed. Prints one JSON object; exit code 0 on success, 2 otherwise.
"""
import hashlib
import json
import os
import random
import shutil
import signal
import string
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import state as S  # noqa: E402

REGISTRY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agents.json")
DEFAULT_TIMEOUT = 180
MAX_TIMEOUT = 600
DEFAULT_MAX_OUTPUT = 200000
PROBE_PROMPT = "Reply with exactly one word: OK"
PROBE_TTL = 24 * 3600
PROBE_TIMEOUT = 90
MARKER = ".colosseum-relay"
CLAUDE_FAMILY = "claude"


class RelayError(ValueError):
    pass


def emit(obj, code):
    print(json.dumps(obj, ensure_ascii=False))
    return code


# ---- registry ----

def user_file(data=None):
    return os.environ.get("COLOSSEUM_AGENTS_FILE") or os.path.join(S.data_root(data), "agents.json")


def load_registry(data=None):
    with open(REGISTRY, encoding="utf-8") as f:
        base = json.load(f)
    agents = {k: dict(v) for k, v in base["agents"].items()}
    prefer = list(base.get("prefer", []))
    path = user_file(data)
    source = None
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            user = json.load(f)
        if not isinstance(user, dict) or not isinstance(user.get("agents", {}), dict):
            raise RelayError("%s must be a JSON object with an \"agents\" object" % path)
        for aid, spec in user.get("agents", {}).items():
            if not isinstance(spec, dict):
                raise RelayError("%s: agent %s must be an object" % (path, aid))
            merged = dict(agents.get(aid, {}))
            merged.update(spec)
            if "vars" in spec and "vars" in agents.get(aid, {}):
                merged["vars"] = dict(agents[aid]["vars"], **spec["vars"])
            agents[aid] = merged
        prefer = list(user.get("prefer", [])) + [p for p in prefer if p not in user.get("prefer", [])]
        source = path
    env_prefer = [p.strip() for p in os.environ.get("COLOSSEUM_AGENTS", "").split(",") if p.strip()]
    prefer = env_prefer + [p for p in prefer if p not in env_prefer]
    for aid, spec in agents.items():
        validate_spec(aid, spec)
    return {"agents": agents, "prefer": prefer, "user_file": source}


def validate_spec(aid, spec):
    if not aid or any(c not in string.ascii_letters + string.digits + "-_." for c in aid):
        raise RelayError("agent id %r may use letters, digits, - _ . only" % aid)
    argv = spec.get("argv")
    if not isinstance(argv, list) or not argv or not all(isinstance(x, str) and x for x in argv):
        raise RelayError("agent %s needs a non-empty argv list of strings" % aid)
    if spec.get("prompt") not in ("stdin", "arg"):
        raise RelayError("agent %s: prompt must be \"stdin\" or \"arg\"" % aid)
    if "{" in argv[0]:
        raise RelayError("agent %s: the program name cannot be a placeholder" % aid)
    holders = [x for x in argv if x == "{prompt}"]
    if spec["prompt"] == "arg" and len(holders) != 1:
        raise RelayError("agent %s: argv needs exactly one \"{prompt}\" element" % aid)
    if spec["prompt"] == "stdin" and holders:
        raise RelayError("agent %s: a stdin agent cannot have \"{prompt}\" in argv" % aid)
    for x in argv:
        if "{" in x and not (x.startswith("{") and x.endswith("}") and x.count("{") == 1):
            raise RelayError("agent %s: placeholders must be whole arguments, got %r" % (aid, x))


def installed(spec):
    return shutil.which(spec["argv"][0])


def build_argv(aid, spec, prompt_text=None):
    """argv with vars filled in; {prompt} replaced only when prompt_text is given."""
    exe = installed(spec)
    if not exe:
        raise RelayError("%s is not installed (%s not on PATH)" % (aid, spec["argv"][0]))
    values = dict(spec.get("vars", {}))
    out = [exe]
    for x in spec["argv"][1:]:
        if x == "{prompt}":
            out.append(prompt_text if prompt_text is not None else x)
        elif x.startswith("{") and x.endswith("}"):
            key = x[1:-1]
            if not values.get(key):
                raise RelayError("%s needs vars.%s in %s" % (aid, key, "the user agents.json"))
            out.append(str(values[key]))
        else:
            out.append(x)
    return out


def describe(aid, spec):
    return {"id": aid, "name": spec.get("name", aid), "provider": spec.get("provider"), "family": spec.get("family", aid),
            "family_uncertain": bool(spec.get("family_uncertain")), "verified": bool(spec.get("verified")),
            "prompt": spec["prompt"], "disabled": bool(spec.get("disabled")),
            "installed": bool(installed(spec)), "priority": spec.get("priority", 50)}


# ---- running ----

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


def _prompt_arg(prompt):
    text = prompt.decode("utf-8", errors="replace")
    return " " + text if text.startswith("-") else text


def execute(argv, stdin_bytes, cwd, timeout, max_output):
    env = dict(os.environ, NO_COLOR="1")
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(argv, stdin=subprocess.PIPE if stdin_bytes is not None else subprocess.DEVNULL,
                                stdout=out, stderr=err, cwd=cwd, env=env, start_new_session=True, close_fds=True)

        def cancel(signum, _frame):
            # The relay itself is being stopped: take the agent's process group with it.
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            raise SystemExit(128 + signum)

        previous = {sig: signal.signal(sig, cancel) for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)}
        timed_out = False
        try:
            proc.communicate(stdin_bytes, timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
        except BrokenPipeError:
            proc.wait(timeout)
        finally:
            # Kill the whole group: the agent's own children must not outlive the relay.
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            proc.wait()
            for sig, handler in previous.items():
                signal.signal(sig, handler)
        out.seek(0)
        data = out.read(max_output + 1)
        err.seek(0)
        err_data = err.read()[-2000:]
    return {"ok": not timed_out and proc.returncode == 0, "exit_code": None if timed_out else proc.returncode,
            "timed_out": timed_out, "truncated": len(data) > max_output,
            "stdout": data[:max_output].decode("utf-8", errors="replace"),
            "stderr_tail": err_data.decode("utf-8", errors="replace")}


def run(cli, prompt_file, timeout=DEFAULT_TIMEOUT, max_output=DEFAULT_MAX_OUTPUT, data=None, registry=None):
    reg = registry or load_registry(data)
    spec = reg["agents"].get(cli)
    if spec is None:
        return {"ok": False, "error": "unknown agent %r; known: %s" % (cli, ", ".join(sorted(reg["agents"])))}
    if spec.get("disabled"):
        return {"ok": False, "error": "agent %s is disabled in %s" % (cli, reg.get("user_file"))}
    if not 1 <= timeout <= MAX_TIMEOUT:
        return {"ok": False, "error": "timeout must be between 1 and %d seconds" % MAX_TIMEOUT}
    d = os.path.dirname(os.path.abspath(prompt_file))
    if not os.path.exists(os.path.join(d, MARKER)):
        return {"ok": False, "error": "the prompt file must be inside a directory made by `relay.py mktemp`"}
    with open(prompt_file, "rb") as f:
        prompt = f.read()
    try:
        if spec["prompt"] == "arg":
            argv, stdin_bytes = build_argv(cli, spec, _prompt_arg(prompt)), None
        else:
            argv, stdin_bytes = build_argv(cli, spec), prompt
    except RelayError as e:
        return {"ok": False, "cli": cli, "error": str(e)}
    work = os.path.join(d, "work")
    os.makedirs(work, mode=0o700, exist_ok=True)
    out = execute(argv, stdin_bytes, work, timeout, max_output)
    out.update(cli=cli, family=spec.get("family", cli), prompt_bytes=len(prompt))
    return out


# ---- detection and probing ----

def _probe_key(aid, spec):
    raw = json.dumps([installed(spec), spec["argv"], spec.get("vars", {}), spec["prompt"]], sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def probe_path(data=None):
    return os.path.join(S.data_root(data), "agents-probe.json")


def probe(aid, spec, timeout=PROBE_TIMEOUT, data=None, registry=None):
    d = make_dir()
    try:
        p = os.path.join(d, "prompt.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write(PROBE_PROMPT)
        start = time.time()
        out = run(aid, p, timeout, 4000, data, registry)
        usable = bool(out.get("ok")) and "ok" in out.get("stdout", "").lower()
        reason = None if usable else (out.get("error") or ("timeout" if out.get("timed_out") else
                                                           "exit %s: %s" % (out.get("exit_code"), out.get("stderr_tail", "")[-300:])))
        return {"usable": usable, "reason": reason, "seconds": round(time.time() - start, 1)}
    finally:
        shutil.rmtree(d, ignore_errors=True)


def detect(data=None, do_probe=False, refresh=False, registry=None):
    reg = registry or load_registry(data)
    cache = {}
    cpath = probe_path(data)
    if do_probe and not refresh and os.path.exists(cpath):
        try:
            with open(cpath, encoding="utf-8") as f:
                cache = json.load(f)
        except ValueError:
            cache = {}
    now = time.time()
    rows = []
    for aid, spec in reg["agents"].items():
        row = describe(aid, spec)
        if not row["installed"] or row["disabled"]:
            continue
        if do_probe:
            key = _probe_key(aid, spec)
            hit = cache.get(aid)
            if hit and hit.get("key") == key and now - hit.get("at", 0) < PROBE_TTL:
                result = hit["result"]
            else:
                result = probe(aid, spec, data=data, registry=reg)
                cache[aid] = {"key": key, "at": now, "result": result}
            row["usable"] = result["usable"]
            row["probe"] = result
        rows.append(row)
    if do_probe:
        S.secure_dir(S.data_root(data))
        S.write_json(cpath, cache)
    order = {aid: i for i, aid in enumerate(reg["prefer"])}
    rows.sort(key=lambda r: (order.get(r["id"], len(order)), r["priority"], r["id"]))
    return {"agents": rows, "prefer": reg["prefer"], "user_file": reg["user_file"], "probed": do_probe}


# ---- roster ----

def roster(detected, size=3, prefer=None, only=None, max_cli=None, seed=None):
    """Pick external agents for a roster of `size` and fill the rest with Claude participants.

    Agents the user names come first, in the user's order; then installed agents by
    priority. Only one agent per model family is taken unless the user named more, and
    the Claude CLI is taken only when named, since the built-in participants are Claude.
    At least one Claude participant stays unless max_cli says otherwise: it is the one
    that can search the web during the debate.
    """
    if not 2 <= size <= 5:
        raise RelayError("roster size must be between 2 and 5")
    max_cli = size - 1 if max_cli is None else max(0, min(size, max_cli))
    rows = [r for r in detected["agents"] if r.get("usable", True)]
    by_id = {r["id"]: r for r in rows}
    named = list(only or prefer or [])
    unavailable = [n for n in named if n not in by_id]
    if only:
        pool = [by_id[n] for n in only if n in by_id]
    else:
        rest = [r for r in rows if r["id"] not in named and r["family"] != CLAUDE_FAMILY]
        pool = [by_id[n] for n in named if n in by_id] + rest
    chosen, families = [], set()
    for r in pool:
        if len(chosen) >= max_cli:
            break
        explicit = r["id"] in named
        if r["family"] in families and not explicit:
            continue
        if r["family"] == CLAUDE_FAMILY and not explicit:
            continue
        chosen.append(r)
        families.add(r["family"])
    juror = next((r for r in rows if r not in chosen and r["family"] != CLAUDE_FAMILY and r["family"] not in families), None)
    if juror is None:
        juror = next((r for r in rows if r not in chosen and r["family"] != CLAUDE_FAMILY), None)
    seats = [{"family": r["family"], "cli": r["id"], "name": r["name"]} for r in chosen]
    seats += [{"family": CLAUDE_FAMILY} for _ in range(size - len(seats))]
    labels = list(string.ascii_uppercase[:size])
    random.Random(seed).shuffle(labels)
    members = [dict(s, label=l) for s, l in zip(seats, labels)]
    members.sort(key=lambda m: m["label"])
    fams = {m["family"] for m in members}
    notes = []
    for r in chosen + ([juror] if juror else []):
        if r["family_uncertain"]:
            notes.append("%s: the model depends on its own configuration; family %r is a guess. Set \"family\" in the user agents.json" % (r["id"], r["family"]))
        if not r["verified"]:
            notes.append("%s: invocation not checked against its documentation; run `relay.py detect --probe` first" % r["id"])
    if unavailable:
        notes.append("not available: %s" % ", ".join(unavailable))
    return {
        "roster": members,
        "cli_juror": juror["id"] if juror else None,
        "homogeneous": len(fams) < 2,
        "families": sorted(fams),
        "transmission": [{"agent": r["id"], "provider": r["provider"]} for r in chosen + ([juror] if juror else [])],
        "unavailable": unavailable,
        "notes": notes,
    }


def main(argv):
    import argparse
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data", help="data root (default: $COLOSSEUM_DATA, $CLAUDE_PLUGIN_DATA or ~/.claude/colosseum)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    d = sub.add_parser("detect")
    d.add_argument("--probe", action="store_true")
    d.add_argument("--refresh", action="store_true")
    d.add_argument("--brief", action="store_true", help="one line per agent, for the skill's environment check")
    r = sub.add_parser("roster")
    r.add_argument("--size", type=int, default=3)
    r.add_argument("--prefer", help="comma-separated agent ids the user asked for, in order")
    r.add_argument("--only", help="comma-separated agent ids; use these and no other external agent")
    r.add_argument("--max-cli", type=int)
    r.add_argument("--probe", action="store_true")
    r.add_argument("--seed", type=int)
    sub.add_parser("mktemp")
    x = sub.add_parser("run")
    x.add_argument("--cli", required=True)
    x.add_argument("--prompt-file", required=True)
    x.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    x.add_argument("--max-output", type=int, default=DEFAULT_MAX_OUTPUT)
    x.add_argument("--cleanup", action="store_true")
    a = p.parse_args(argv)
    split = lambda s: [t.strip() for t in (s or "").split(",") if t.strip()]
    try:
        if a.cmd == "mktemp":
            return emit({"dir": make_dir()}, 0)
        if a.cmd == "list":
            reg = load_registry(a.data)
            return emit({"agents": [describe(k, v) for k, v in sorted(reg["agents"].items())],
                         "prefer": reg["prefer"], "user_file": reg["user_file"] or user_file(a.data)}, 0)
        if a.cmd == "detect":
            out = detect(a.data, a.probe, a.refresh)
            if a.brief:
                for row in out["agents"]:
                    print("AGENT %s family=%s%s" % (row["id"], row["family"],
                                                     "" if "usable" not in row else " usable=%s" % row["usable"]))
                return 0
            return emit(out, 0)
        if a.cmd == "roster":
            det = detect(a.data, a.probe)
            return emit(roster(det, a.size, split(a.prefer), split(a.only), a.max_cli, a.seed), 0)
    except (RelayError, OSError, ValueError) as e:
        return emit({"ok": False, "error": "%s: %s" % (type(e).__name__, e)}, 2)
    out = {"ok": False, "error": "cancelled"}
    try:
        out = run(a.cli, a.prompt_file, a.timeout, a.max_output, a.data)
    except (RelayError, OSError, ValueError) as e:
        out = {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}
    finally:
        if a.cleanup:
            cleanup(a.prompt_file)
    return emit(out, 0 if out.get("ok") else 2)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
