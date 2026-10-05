"""Run state shared by the Colosseum CLI and the plugin hooks.

Layout under <data> (--data, $COLOSSEUM_DATA, $CLAUDE_PLUGIN_DATA, or ~/.claude/colosseum):

  sessions/<session_id>/state.json           the session's current run (checkpoint)
  sessions/<session_id>/runs/<run_id>/       every artifact of that run, and the final
                                             state.json once the run is closed

A new run never reads another run's files: default inputs resolve to the current run's
directory only. Writes are serialized with a file lock because parallel subagents trigger
hooks at the same time. On POSIX, directories are created 0700 and files 0600.
"""
import contextlib
import hashlib
import json
import os
import re
import time

try:
    import fcntl
except ImportError:  # no advisory locks on this platform
    fcntl = None

SCHEMA = "colosseum.state/v2"
PHASES = ["plan", "fact_base", "drafts", "baseline", "issues", "round", "verdict", "done"]
STATUSES = ("running", "completed", "failed", "cancelled", "interrupted")
CLOSED = ("completed", "failed", "cancelled")
DEFAULT_BUDGET = {"search": 25, "fetch": 15}
MAX_BUDGET = {"search": 25, "fetch": 15}
DEFAULT_MAX_ROUNDS = 3
MAX_ROUNDS = 3
FETCH_FAILURES_FOR_DEGRADED = 3

_SAFE_ID = re.compile(r"[^A-Za-z0-9_.-]")


class StateError(ValueError):
    pass


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def data_root(explicit=None):
    for candidate in (explicit, os.environ.get("COLOSSEUM_DATA"), os.environ.get("CLAUDE_PLUGIN_DATA")):
        if candidate and "${" not in candidate:
            return candidate
    return os.path.join(os.path.expanduser("~"), ".claude", "colosseum")


def secure_dir(path):
    os.makedirs(path, mode=0o700, exist_ok=True)
    if os.name == "posix":
        os.chmod(path, 0o700)
    return path


def write_private(path, text):
    """Atomic write with mode 0600."""
    tmp = "%s.%d.tmp" % (path, os.getpid())
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def append_private(path, line):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as f:
        f.write(line)


def write_json(path, obj):
    write_private(path, json.dumps(obj, indent=1, ensure_ascii=False))


def _safe(value, what):
    sid = _SAFE_ID.sub("_", value or "")
    if not sid or sid in (".", ".."):
        raise StateError("%s is required" % what)
    return sid


def session_dir(session_id, data=None):
    return os.path.join(data_root(data), "sessions", _safe(session_id, "session id"))


def state_path(session_id, data=None):
    return os.path.join(session_dir(session_id, data), "state.json")


def run_path(session_id, run_id, data=None):
    return os.path.join(session_dir(session_id, data), "runs", _safe(run_id, "run id"))


def run_dir(session_id, data=None, run_id=None):
    """Directory of the given run, or of the session's current run."""
    if run_id is None:
        st = load(session_id, data)
        if not st or st.get("schema") != SCHEMA or not st.get("run_id"):
            raise StateError("no current run for this session; call start first")
        run_id = st["run_id"]
    return run_path(session_id, run_id, data)


@contextlib.contextmanager
def locked(session_id, data=None):
    if fcntl is None:
        raise StateError("file locking is not available on this platform; Colosseum runs are not supported here")
    d = secure_dir(session_dir(session_id, data))
    fd = os.open(os.path.join(d, ".lock"), os.O_WRONLY | os.O_CREAT, 0o600)
    with os.fdopen(fd, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield d
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def load(session_id, data=None):
    p = state_path(session_id, data)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save(session_id, state, data=None):
    state["updated_at"] = now()
    write_json(state_path(session_id, data), state)


def archive(session_id, state, data=None):
    """Copy the run's state into its own directory (done whenever a run closes or stops)."""
    d = secure_dir(run_path(session_id, state["run_id"], data))
    write_json(os.path.join(d, "state.json"), state)


def question_hash(question):
    return hashlib.sha256((question or "").encode("utf-8")).hexdigest()[:16]


def new_run_id(session_id, question, data=None):
    base = "%s-%s" % (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()), question_hash(question)[:8])
    run_id, n = base, 1
    while os.path.exists(run_path(session_id, run_id, data)):
        n += 1
        run_id = "%s-%d" % (base, n)
    return run_id


def new_state(session_id, question, stakes="medium", max_rounds=DEFAULT_MAX_ROUNDS, budget=None, data=None,
              label=""):
    budget = dict(budget or DEFAULT_BUDGET)
    for k, cap in MAX_BUDGET.items():
        if not 0 <= int(budget.get(k, cap)) <= cap:
            raise StateError("%s budget must be between 0 and %d" % (k, cap))
    if not 1 <= int(max_rounds) <= MAX_ROUNDS:
        raise StateError("max rounds must be between 1 and %d" % MAX_ROUNDS)
    run_id = new_run_id(session_id, question, data)
    return {
        "schema": SCHEMA,
        "run_id": run_id,
        "status": "running",
        "session_id": session_id,
        "question_sha256": question_hash(question),
        "label": label,
        "stakes": stakes,
        "phase": "plan",
        "round": 0,
        "max_rounds": int(max_rounds),
        "budget": budget,
        "used": {"search": 0, "fetch": 0},
        "fetch_failures": [],
        "degraded": False,
        "history": [],
        "started_at": now(),
    }


def is_running(state):
    return bool(state) and state.get("schema") == SCHEMA and state.get("status") == "running"
