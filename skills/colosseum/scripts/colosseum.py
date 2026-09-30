"""Colosseum run controller: phase state machine plus the computation commands.

  start        create a run for this session
  status       print state and the next allowed phases
  advance      move to the next phase (illegal transitions are refused)
  round-result record how many positions changed on new verified evidence
  fetch-failed record a failed page fetch (3 distinct hosts switch to snippet mode)
  quote        classify a quote against saved page text (v / n / u)
  baseline     family-weighted vote and pooled probability from drafts.json
  verdict      deterministic verdicts from graph.json
  metrics      evidence-quality checklist from graph.json
  finish       close the run

Every command prints one JSON object. Exit code 0 on success, 2 on refusal or bad input.
"""
import argparse
import json
import os
import sys
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import baseline as B  # noqa: E402
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


def cmd_start(a):
    with S.locked(a.session, a.data) as d:
        old = S.load(a.session, a.data)
        if S.is_running(old) and not a.force:
            raise Refused("a run is already in progress for this session (use --force to replace it)")
        budget = {"search": a.search_budget, "fetch": a.fetch_budget}
        st = S.new_state(a.session, a.question, a.stakes, a.max_rounds, budget)
        S.save(a.session, st, a.data)
    return emit({"ok": True, "run_dir": d, "phase": st["phase"],
                 "files": {"drafts": os.path.join(d, "drafts.json"), "graph": os.path.join(d, "graph.json")},
                 "next": _next_allowed(st)})


def cmd_status(a):
    st = S.load(a.session, a.data)
    if not st:
        return emit({"running": False})
    return emit({"running": S.is_running(st), "phase": st["phase"], "round": st["round"],
                 "max_rounds": st["max_rounds"], "used": st["used"], "budget": st["budget"],
                 "degraded": st["degraded"], "next": _next_allowed(st) if S.is_running(st) else []})


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
            st["status"] = "done"
        S.save(a.session, st, a.data)
    return emit({"ok": True, "phase": st["phase"], "round": st["round"], "next": _next_allowed(st)})


def cmd_round_result(a):
    with S.locked(a.session, a.data):
        st = _running(a)
        if st["phase"] != "round":
            raise Refused("round-result is only valid during a round")
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
        with S.locked(a.session, a.data) as d:
            with open(os.path.join(d, "quotes.jsonl"), "a", encoding="utf-8") as f:
                f.write(json.dumps(dict(out, quote=quote), ensure_ascii=False) + "\n")
    return emit(out)


def _input(a, name):
    """Load the JSON input: stdin with --file -, an explicit --file, or the run directory copy.

    Input read from stdin or --file is saved into the run directory, so the moderator
    never has to write into the plugin data directory with a file tool.
    """
    if a.file == "-":
        doc = json.load(sys.stdin)
    elif a.file:
        with open(a.file, encoding="utf-8") as f:
            doc = json.load(f)
    else:
        with open(os.path.join(S.run_dir(a.session, a.data), name), encoding="utf-8") as f:
            return json.load(f)
    if a.session:
        with S.locked(a.session, a.data) as d:
            with open(os.path.join(d, name), "w", encoding="utf-8") as f:
                json.dump(doc, f, indent=1, ensure_ascii=False)
    return doc


def _save(a, name, obj):
    if a.session:
        with open(os.path.join(S.run_dir(a.session, a.data), name), "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=1, ensure_ascii=False)


def cmd_baseline(a):
    out = B.baseline(_input(a, "drafts.json"), a.extremize)
    if a.session:
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
        st["status"] = "done"
        st["phase"] = "done"
        S.save(a.session, st, a.data)
    return emit({"ok": True, "used": st["used"]})


def parser():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data", help="data root (default: $CLAUDE_PLUGIN_DATA or ~/.claude/colosseum)")
    sub = p.add_subparsers(dest="cmd", required=True)

    def with_session(sp, required=True):
        sp.add_argument("--session", required=required, help="Claude Code session id")
        return sp

    sp = with_session(sub.add_parser("start"))
    sp.add_argument("--question", default="", help="optional label; never pass raw user text through the shell")
    sp.add_argument("--stakes", choices=["low", "medium", "high"], default="medium")
    sp.add_argument("--max-rounds", type=int, default=S.DEFAULT_MAX_ROUNDS)
    sp.add_argument("--search-budget", type=int, default=S.DEFAULT_BUDGET["search"])
    sp.add_argument("--fetch-budget", type=int, default=S.DEFAULT_BUDGET["fetch"])
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(fn=cmd_start)

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
        if name == "baseline":
            sp.add_argument("--extremize", type=float, default=1.0)
        if name == "verdict":
            sp.add_argument("--theta", type=float)
        sp.set_defaults(fn=fn)

    with_session(sub.add_parser("finish")).set_defaults(fn=cmd_finish)
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
    except (G.GraphError, ValueError, KeyError, OSError) as e:
        return emit({"ok": False, "error": "%s: %s" % (type(e).__name__, e)}, 2)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
