"""Run state shared by the Colosseum CLI and the plugin hooks.

One run per Claude Code session, stored under
  <data>/sessions/<session_id>/state.json
where <data> is --data, $COLOSSEUM_DATA, $CLAUDE_PLUGIN_DATA, or ~/.claude/colosseum.
Writes are serialized with a file lock because parallel subagents trigger hooks
at the same time.
"""
import contextlib
import json
import os
import re
import time

try:
    import fcntl
except ImportError:  # Windows: hooks still work, just without the lock
    fcntl = None

PHASES = ["plan", "fact_base", "drafts", "baseline", "issues", "round", "verdict", "done"]
DEFAULT_BUDGET = {"search": 25, "fetch": 15}
DEFAULT_MAX_ROUNDS = 3
FETCH_FAILURES_FOR_DEGRADED = 3

_SAFE_ID = re.compile(r"[^A-Za-z0-9_.-]")


def data_root(explicit=None):
    for candidate in (explicit, os.environ.get("COLOSSEUM_DATA"), os.environ.get("CLAUDE_PLUGIN_DATA")):
        if candidate and "${" not in candidate:
            return candidate
    return os.path.join(os.path.expanduser("~"), ".claude", "colosseum")


def run_dir(session_id, data=None):
    sid = _SAFE_ID.sub("_", session_id or "")
    if not sid:
        raise ValueError("session id is required")
    return os.path.join(data_root(data), "sessions", sid)


def state_path(session_id, data=None):
    return os.path.join(run_dir(session_id, data), "state.json")


@contextlib.contextmanager
def locked(session_id, data=None):
    d = run_dir(session_id, data)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, ".lock"), "w") as lock:
        if fcntl:
            fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield d
        finally:
            if fcntl:
                fcntl.flock(lock, fcntl.LOCK_UN)


def load(session_id, data=None):
    p = state_path(session_id, data)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save(session_id, state, data=None):
    p = state_path(session_id, data)
    tmp = p + ".tmp"
    state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=1, ensure_ascii=False)
    os.replace(tmp, p)


def new_state(session_id, question, stakes="medium", max_rounds=DEFAULT_MAX_ROUNDS, budget=None):
    return {
        "schema": "colosseum.state/v1",
        "status": "running",
        "session_id": session_id,
        "question": question,
        "stakes": stakes,
        "phase": "plan",
        "round": 0,
        "max_rounds": max_rounds,
        "budget": dict(budget or DEFAULT_BUDGET),
        "used": {"search": 0, "fetch": 0},
        "fetch_failures": [],
        "degraded": False,
        "history": [],
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def is_running(state):
    return bool(state) and state.get("status") == "running"
