"""Colosseum run controller: phase state machine plus the computation commands.

  start        create a run for this session (refused while one is running)
  resume       continue the session's running or interrupted run from its checkpoint
  restart      stop the current run as interrupted and start a new one
  cancel       close the current run as cancelled
  fail         close the current run as failed, with a reason
  runs         list this session's runs
  status       print state and the next allowed phases
  advance      move to the next phase (illegal transitions are refused)
  round-result record how many positions changed on new verified evidence
  fetch-failed record a failed page fetch (3 distinct hosts switch to snippet mode)
  quote        classify a quote against saved page text (v / n / u)
  baseline     family-weighted vote and pooled probability from drafts.json
  verdict      deterministic verdicts from graph.json
  metrics      evidence-quality checklist from graph.json
  finish       close the run as completed
  forecast     forecast store: add (stdin JSON), resolve, list, score, fit, import, export
               (shared across sessions)

Every run keeps its files in sessions/<session>/runs/<run_id>/. Commands that read a
default input file read it from the current run only; --run reads a closed run explicitly.

Every command prints one JSON object. Exit code 0 on success, 2 on refusal or bad input.
"""
import argparse
import json
import os
import sys
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import baseline as B  # noqa: E402
import calibration as C  # noqa: E402
import graph as G  # noqa: E402
import metrics as M  # noqa: E402
import quote_match as Q  # noqa: E402
import state as S  # noqa: E402
import verdict_engine as V  # noqa: E402

TRANSITIONS = {
    "plan": ["fact_base"],
    "fact_base": ["drafts"],
    "drafts": ["baseline"],
    "baseline": ["issues", "verdict"],
    "issues": ["round", "verdict"],
    "round": ["round", "verdict"],
    "verdict": ["done"],
    "done": [],
}


class Refused(Exception):
    pass


def emit(obj, code=0):
    print(json.dumps(obj, indent=1, ensure_ascii=False))
    return code


def _running(args):
    st = S.load(args.session, args.data)
    if st and st.get("schema") != S.SCHEMA:
        raise Refused("checkpoint version %s is not supported; use restart" % st.get("schema"))
    if not S.is_running(st):
        raise Refused("no running Colosseum run for this session; call start first")
    return st


def _next_allowed(st):
    allowed = list(TRANSITIONS[st["phase"]])
    if "round" in allowed:
        last = st["history"][-1] if st["history"] else {}
        if st["round"] >= st["max_rounds"]:
            allowed.remove("round")
        elif st["phase"] == "round" and last.get("verified_changes", 1) == 0:
            allowed.remove("round")
        elif st["phase"] == "round" and last.get("open_issues", 1) == 0:
            allowed.remove("round")
    return allowed


def _question(a):
    """Question text from --question-file: plain text, or a JSON object {"question": "..."}.

    JSON is the form to use through a heredoc, since a JSON string cannot hold a raw newline
    and so can never contain the heredoc terminator line.
    """
    if not getattr(a, "question_file", None):
        return a.question or ""
    if a.question_file == "-":
        text = sys.stdin.read()
    else:
        with open(a.question_file, encoding="utf-8") as f:
            text = f.read()
    try:
        doc = json.loads(text)
    except ValueError:
        return text
    return doc["question"] if isinstance(doc, dict) and isinstance(doc.get("question"), str) else text


def _open_run(a):
    question = _question(a)
    budget = {"search": a.search_budget, "fetch": a.fetch_budget}
    st = S.new_state(a.session, question, a.stakes, a.max_rounds, budget, a.data, label=a.question or "")
    run = S.secure_dir(S.run_path(a.session, st["run_id"], a.data))
    S.save(a.session, st, a.data)
    S.archive(a.session, st, a.data)
    return st, run


def _close(a, st, status, **extra):
    st["status"] = status
    st["closed_at"] = S.now()
    st.update(extra)
    S.save(a.session, st, a.data)
    S.archive(a.session, st, a.data)


def _started(st, run):
    return {"ok": True, "run_id": st["run_id"], "run_dir": run, "question_sha256": st["question_sha256"],
            "phase": st["phase"], "files": {"drafts": os.path.join(run, "drafts.json"),
                                            "graph": os.path.join(run, "graph.json")},
            "next": _next_allowed(st)}


def cmd_start(a):
    with S.locked(a.session, a.data):
        old = S.load(a.session, a.data)
        if old and old.get("status") in ("running", "interrupted") and old.get("schema") == S.SCHEMA:
            if not a.force:
                raise Refused("run %s is %s for this session; use resume to continue it or restart to begin a new run"
                              % (old["run_id"], old["status"]))
            _close(a, old, "interrupted", stopped_by="start --force")
        st, run = _open_run(a)
    return emit(dict(_started(st, run), replaced=old["run_id"] if old and old.get("run_id") and a.force else None))


def cmd_restart(a):
    with S.locked(a.session, a.data):
        old = S.load(a.session, a.data)
        previous = None
        if old and old.get("schema") == S.SCHEMA and old.get("status") in ("running", "interrupted"):
            _close(a, old, "interrupted", stopped_by="restart")
            previous = old["run_id"]
        st, run = _open_run(a)
    return emit(dict(_started(st, run), previous=previous,
                     note="the new run starts empty; files of earlier runs stay in their own directories"))


def cmd_resume(a):
    with S.locked(a.session, a.data):
        st = S.load(a.session, a.data)
        if not st:
            raise Refused("nothing to resume; call start")
        if st.get("schema") != S.SCHEMA:
            raise Refused("checkpoint version %s is not supported; use restart" % st.get("schema"))
        if st.get("status") not in ("running", "interrupted"):
            raise Refused("run %s is %s; closed runs cannot be resumed, use start" % (st.get("run_id"), st.get("status")))
        if st.get("phase") not in S.PHASES or not os.path.isdir(S.run_path(a.session, st["run_id"], a.data)):
            raise Refused("checkpoint of run %s is damaged (phase %r); use restart" % (st.get("run_id"), st.get("phase")))
        if a.expect_question_sha and a.expect_question_sha != st.get("question_sha256"):
            raise Refused("run %s belongs to a different question; use restart" % st["run_id"])
        st["status"] = "running"
        st.setdefault("resumed", []).append(S.now())
        S.save(a.session, st, a.data)
    return emit({"ok": True, "run_id": st["run_id"], "phase": st["phase"], "round": st["round"],
                 "run_dir": S.run_path(a.session, st["run_id"], a.data), "next": _next_allowed(st)})


def cmd_cancel(a):
    with S.locked(a.session, a.data):
        st = _running(a)
        _close(a, st, "cancelled")
    return emit({"ok": True, "run_id": st["run_id"], "status": "cancelled"})


def cmd_fail(a):
    with S.locked(a.session, a.data):
        st = _running(a)
        _close(a, st, "failed", failure=a.reason)
    return emit({"ok": True, "run_id": st["run_id"], "status": "failed"})


def cmd_runs(a):
    base = os.path.join(S.session_dir(a.session, a.data), "runs")
    out = []
    for rid in sorted(os.listdir(base)) if os.path.isdir(base) else []:
        p = os.path.join(base, rid, "state.json")
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                st = json.load(f)
            out.append({k: st.get(k) for k in ("run_id", "status", "phase", "question_sha256", "started_at", "closed_at")})
    cur = S.load(a.session, a.data)
    return emit({"current": cur.get("run_id") if cur else None, "runs": out})


def cmd_status(a):
    st = S.load(a.session, a.data)
    if not st:
        return emit({"running": False})
    if st.get("schema") != S.SCHEMA:
        return emit({"running": False, "refused": "checkpoint version %s is not supported; use restart" % st.get("schema")})
    return emit({"running": S.is_running(st), "run_id": st["run_id"], "status": st["status"], "phase": st["phase"],
                 "round": st["round"], "max_rounds": st["max_rounds"], "used": st["used"], "budget": st["budget"],
                 "question_sha256": st["question_sha256"], "degraded": st["degraded"],
                 "next": _next_allowed(st) if S.is_running(st) else []})


def cmd_advance(a):
    with S.locked(a.session, a.data):
        st = _running(a)
        allowed = _next_allowed(st)
        if a.to not in allowed:
            reason = "cannot move from %s to %s; allowed: %s" % (st["phase"], a.to, allowed or "none")
            if a.to == "round" and st["phase"] == "round":
                last = st["history"][-1] if st["history"] else {}
                if st["round"] >= st["max_rounds"]:
                    reason = "round cap reached (%d); go to verdict" % st["max_rounds"]
                elif last.get("open_issues") == 0:
                    reason = "no open issues left; go to verdict (exit reason: resolved)"
                elif last.get("verified_changes") == 0:
                    reason = "no position changed on new verified evidence; go to verdict (exit reason: stable)"
            raise Refused(reason)
        if a.to == "round":
            if st["phase"] == "round" and not (st["history"] and st["history"][-1].get("round") == st["round"]):
                raise Refused("record round-result for round %d first" % st["round"])
            st["round"] += 1
        st["phase"] = a.to
        if a.to == "done":
            _close(a, st, "completed")
        else:
            S.save(a.session, st, a.data)
    return emit({"ok": True, "phase": st["phase"], "round": st["round"], "next": _next_allowed(st)})


def cmd_round_result(a):
    with S.locked(a.session, a.data):
        st = _running(a)
        if st["phase"] != "round":
            raise Refused("round-result is only valid during a round")
        if min(a.verified_changes, a.open_issues, a.conformity_flips) < 0:
            raise Refused("round-result counts cannot be negative")
        entry = {"round": st["round"], "verified_changes": a.verified_changes, "open_issues": a.open_issues,
                 "conformity_flips": a.conformity_flips}
        st["history"] = [h for h in st["history"] if h.get("round") != st["round"]] + [entry]
        S.save(a.session, st, a.data)
    exit_reason = ("resolved" if a.open_issues == 0 else "stable" if a.verified_changes == 0
                   else "cap" if st["round"] >= st["max_rounds"] else None)
    return emit({"ok": True, "recorded": entry, "debate_over": exit_reason is not None,
                 "exit_reason": exit_reason, "next": _next_allowed(st)})


def cmd_fetch_failed(a):
    host = urlparse(a.url).hostname or a.url
    with S.locked(a.session, a.data):
        st = _running(a)
        if host not in st["fetch_failures"]:
            st["fetch_failures"].append(host)
        if len(st["fetch_failures"]) >= S.FETCH_FAILURES_FOR_DEGRADED:
            st["degraded"] = True
        S.save(a.session, st, a.data)
    return emit({"ok": True, "failed_hosts": st["fetch_failures"], "degraded": st["degraded"],
                 "note": "snippet-level mode: stop fetching, verify quotes against search snippets"
                 if st["degraded"] else None})


def cmd_quote(a):
    """Classify one quote. With --stdin, read {"id", "quote", "page"} and log the result in the run."""
    if a.stdin:
        req = json.load(sys.stdin)
        quote, page = req.get("quote", ""), req.get("page", "")
    else:
        quote = a.quote if a.quote is not None else open(a.quote_file, encoding="utf-8").read()
        page = open(a.page_file, encoding="utf-8", errors="replace").read()
    out = Q.match(quote, page)
    if a.stdin and a.session:
        out["id"] = req.get("id")
        with S.locked(a.session, a.data):
            _running(a)
            S.append_private(os.path.join(S.run_dir(a.session, a.data), "quotes.jsonl"),
                             json.dumps(dict(out, quote=quote), ensure_ascii=False) + "\n")
    return emit(out)


def _input(a, name):
    """Load the JSON input: stdin with --file -, an explicit --file, or the run directory copy.

    Input read from stdin or --file is saved into the current run's directory, so the
    moderator never writes into the plugin data directory with a file tool. Without
    --file the input comes from the current run (or the run named by --run) and nowhere
    else, so a new run never picks up an earlier run's file.
    """
    if a.file == "-":
        doc = json.load(sys.stdin)
    elif a.file:
        with open(a.file, encoding="utf-8") as f:
            doc = json.load(f)
    else:
        if a.run:
            d = S.run_path(a.session, a.run, a.data)
        else:
            _running(a)
            d = S.run_dir(a.session, a.data)
        p = os.path.join(d, name)
        if not os.path.exists(p):
            raise Refused("%s is not in run %s; pass it with --file -" % (name, os.path.basename(d)))
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    if a.session and not a.run:
        with S.locked(a.session, a.data):
            _running(a)
            S.write_json(os.path.join(S.run_dir(a.session, a.data), name), doc)
    return doc


def _save(a, name, obj):
    if a.session and not a.run:
        st = S.load(a.session, a.data)
        if S.is_running(st):
            S.write_json(os.path.join(S.run_dir(a.session, a.data), name), obj)


def cmd_baseline(a):
    out = B.baseline(_input(a, "drafts.json"), a.extremize)
    if a.session and not a.run:
        with S.locked(a.session, a.data):
            st = S.load(a.session, a.data)
            if S.is_running(st) and st["phase"] == "drafts":
                st["phase"] = "baseline"
                S.save(a.session, st, a.data)
        _save(a, "baseline.json", out)
    return emit(out)


def cmd_verdict(a):
    doc = G.validate(_input(a, "graph.json"))
    theta = a.theta
    if theta is None:
        st = S.load(a.session, a.data) if a.session else None
        theta = 0.7 if st and st.get("stakes") == "high" else V.THETA
    out = V.verdict(doc, theta)
    _save(a, "verdict.json", out)
    return emit(out)


def cmd_metrics(a):
    doc = _input(a, "graph.json")
    st = S.load(a.session, a.data) if a.session else None
    out = M.checklist(doc, high_stakes=bool(st and st.get("stakes") == "high"))
    if st:
        out["budget"] = {"used": st["used"], "limit": st["budget"]}
        out["degraded"] = st["degraded"]
    return emit(out)


def cmd_finish(a):
    with S.locked(a.session, a.data):
        st = _running(a)
        st["phase"] = "done"
        _close(a, st, "completed")
    return emit({"ok": True, "run_id": st["run_id"], "status": "completed", "used": st["used"]})


def cmd_forecast(a):
    root = S.data_root(a.data)
    if a.action == "add":
        if a.file and a.file != "-":
            with open(a.file, encoding="utf-8") as f:
                rec = C.add(root, json.load(f), a.event_id)
        else:
            rec = C.add(root, json.load(sys.stdin), a.event_id)
        return emit({"ok": True, "logged": rec["id"], "created": rec["created"], "store": C.db_path(root)})
    if a.action == "resolve":
        if not a.id or a.outcome is None:
            raise ValueError("resolve needs --id and --outcome")
        return emit({"ok": True, "resolved": C.resolve(root, a.id, a.outcome, a.event_id)})
    if a.action == "import":
        return emit(C.import_jsonl(root, None if a.file in (None, "-") else a.file))
    if a.action == "export":
        text = C.export_jsonl(root)
        if a.file and a.file != "-":
            S.write_private(a.file, text)
            return emit({"ok": True, "exported": text.count("\n"), "file": a.file})
        sys.stdout.write(text)
        return 0
    if a.action == "status":
        return emit(C.status(root))
    records = C.load(root)
    if a.action == "list":
        return emit({"forecasts": [{k: r.get(k) for k in ("id", "question", "resolve_by", "p_final", "outcome")}
                                   for r in records]})
    if a.action == "score":
        return emit({"p_final": C.score(records, "p_final"), "p0": C.score(records, "p0")})
    return emit(C.fit_extremizing(records))


def parser():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data", help="data root (default: $CLAUDE_PLUGIN_DATA or ~/.claude/colosseum)")
    sub = p.add_subparsers(dest="cmd", required=True)

    def with_session(sp, required=True):
        sp.add_argument("--session", required=required, help="Claude Code session id")
        return sp

    for name, fn in (("start", cmd_start), ("restart", cmd_restart)):
        sp = with_session(sub.add_parser(name))
        sp.add_argument("--question", default="", help="optional short label; never pass raw user text through the shell")
        sp.add_argument("--question-file", help="the question text, or - for stdin (hashed to tie inputs to the run)")
        sp.add_argument("--stakes", choices=["low", "medium", "high"], default="medium")
        sp.add_argument("--max-rounds", type=int, default=S.DEFAULT_MAX_ROUNDS)
        sp.add_argument("--search-budget", type=int, default=S.DEFAULT_BUDGET["search"])
        sp.add_argument("--fetch-budget", type=int, default=S.DEFAULT_BUDGET["fetch"])
        if name == "start":
            sp.add_argument("--force", action="store_true", help="same as restart")
        sp.set_defaults(fn=fn)

    sp = with_session(sub.add_parser("resume"))
    sp.add_argument("--expect-question-sha", help="refuse unless the run belongs to this question hash")
    sp.set_defaults(fn=cmd_resume)
    with_session(sub.add_parser("cancel")).set_defaults(fn=cmd_cancel)
    sp = with_session(sub.add_parser("fail"))
    sp.add_argument("--reason", required=True)
    sp.set_defaults(fn=cmd_fail)
    with_session(sub.add_parser("runs")).set_defaults(fn=cmd_runs)
    with_session(sub.add_parser("status")).set_defaults(fn=cmd_status)

    sp = with_session(sub.add_parser("advance"))
    sp.add_argument("--to", required=True, choices=S.PHASES)
    sp.set_defaults(fn=cmd_advance)

    sp = with_session(sub.add_parser("round-result"))
    sp.add_argument("--verified-changes", type=int, required=True)
    sp.add_argument("--open-issues", type=int, required=True)
    sp.add_argument("--conformity-flips", type=int, default=0)
    sp.set_defaults(fn=cmd_round_result)

    sp = with_session(sub.add_parser("fetch-failed"))
    sp.add_argument("--url", required=True)
    sp.set_defaults(fn=cmd_fetch_failed)

    sp = with_session(sub.add_parser("quote"), required=False)
    sp.add_argument("--stdin", action="store_true", help='read {"id", "quote", "page"} JSON from stdin')
    sp.add_argument("--quote")
    sp.add_argument("--quote-file")
    sp.add_argument("--page-file")
    sp.set_defaults(fn=cmd_quote)

    for name, fn in (("baseline", cmd_baseline), ("verdict", cmd_verdict), ("metrics", cmd_metrics)):
        sp = with_session(sub.add_parser(name), required=False)
        sp.add_argument("--file", help="input JSON file, or - for stdin (saved into the run directory)")
        sp.add_argument("--run", help="read the input from this run of the session instead of the current one")
        if name == "baseline":
            sp.add_argument("--extremize", type=float, default=1.0)
        if name == "verdict":
            sp.add_argument("--theta", type=float)
        sp.set_defaults(fn=fn)

    with_session(sub.add_parser("finish")).set_defaults(fn=cmd_finish)

    sp = sub.add_parser("forecast")
    sp.add_argument("action", choices=["add", "resolve", "list", "score", "fit", "status", "import", "export"])
    sp.add_argument("--id")
    sp.add_argument("--outcome", type=int, choices=[0, 1])
    sp.add_argument("--event-id", help="idempotency key for add or resolve retries")
    sp.add_argument("--file", help="add: record JSON path or - for stdin (default); import: JSONL path "
                                   "(default <data>/forecasts.jsonl); export: output path or - for stdout")
    sp.set_defaults(fn=cmd_forecast)
    return p


def main(argv):
    a = parser().parse_args(argv)
    if a.cmd in ("baseline", "verdict", "metrics") and not (a.file or a.session):
        return emit({"error": "give --session or --file"}, 2)
    if a.cmd == "quote" and not a.stdin and not (a.page_file and (a.quote is not None or a.quote_file)):
        return emit({"error": "give --stdin, or --page-file with --quote or --quote-file"}, 2)
    try:
        return a.fn(a)
    except Refused as e:
        return emit({"ok": False, "refused": str(e)}, 2)
    except (G.GraphError, S.StateError, ValueError, KeyError, OSError) as e:
        return emit({"ok": False, "error": "%s: %s" % (type(e).__name__, e)}, 2)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
