"""Plugin hook entry point. A no-op unless this session has a running Colosseum run.

  pre   (PreToolUse: WebSearch, WebFetch, SendMessage)
        counts searches and fetches against the run budget and denies calls past it;
        denies fetches once the run is in snippet-level mode;
        denies SendMessage while blind drafts are being written.
  post  (PostToolUse: WebSearch, WebFetch)
        appends one minimal audit record per call to sources.jsonl in the current run's
        directory: event id, tool, success, latency when reported, redacted URLs and
        hashes of the query and response. Raw query and response text are never kept.
  subagent-stop (SubagentStop: colosseum:participant)
        sends a malformed participant turn back once with the list of problems.

Any internal error exits 0 without output, so a hook bug never blocks the session.
"""
import hashlib
import json
import os
import re
import sys
import time
import uuid
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import state as S  # noqa: E402
import turns  # noqa: E402

SECRET_KEY = re.compile(r"(?i)(token|key|secret|passw|auth|sig|session|credential|cookie|code)")


def redact_url(url):
    """Drop user info and fragments, and replace credential-like query values."""
    try:
        p = urlsplit(str(url))
    except ValueError:
        return "REDACTED"
    host = p.hostname or ""
    if p.port:
        host += ":%d" % p.port
    query = urlencode([(k, "REDACTED" if SECRET_KEY.search(k) else v) for k, v in parse_qsl(p.query, keep_blank_values=True)])
    return urlunsplit((p.scheme, host, p.path, query, ""))


def digest(obj):
    raw = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def deny(reason):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                             "permissionDecision": "deny",
                                             "permissionDecisionReason": reason}}, ensure_ascii=False))


def pre(event):
    sid, tool = event.get("session_id"), event.get("tool_name", "")
    if not sid or not S.is_running(S.load(sid)):
        return
    with S.locked(sid):
        st = S.load(sid)
        if not S.is_running(st):
            return
        if tool == "SendMessage":
            if st["phase"] == "drafts":
                deny("Colosseum: participants may not message each other while blind drafts are being written.")
            return
        kind = "search" if tool == "WebSearch" or tool.endswith("brave_web_search") else "fetch" if tool == "WebFetch" else None
        if kind is None:
            return
        if kind == "fetch" and st.get("degraded"):
            deny("Colosseum: page fetching failed on %d hosts, so this run is in snippet-level mode. "
                 "Verify quotes against search snippets instead of fetching." % len(st["fetch_failures"]))
            return
        if st["used"][kind] >= st["budget"][kind]:
            deny("Colosseum: the %s budget for this run (%d) is spent. Mark the remaining claims as "
                 "'unchecked (budget)' and continue." % (kind, st["budget"][kind]))
            return
        st["used"][kind] += 1
        S.save(sid, st)


def post(event):
    sid = event.get("session_id")
    st = S.load(sid) if sid else None
    if not S.is_running(st):
        return
    resp = event.get("tool_response")
    tool_input = event.get("tool_input") or {}
    urls = []
    if isinstance(resp, dict):
        for block in resp.get("results") or []:
            for item in (block.get("content") if isinstance(block, dict) else None) or []:
                if isinstance(item, dict) and item.get("url"):
                    urls.append(redact_url(item["url"]))
    failed = resp is None or (isinstance(resp, dict) and bool(resp.get("error") or resp.get("is_error")))
    record = {
        "event_id": uuid.uuid4().hex,
        "ts": S.now(),
        "run_id": st["run_id"],
        "tool": event.get("tool_name"),
        "ok": not failed,
        "latency_s": resp.get("durationSeconds") if isinstance(resp, dict) else None,
        "url": redact_url(tool_input["url"]) if isinstance(tool_input, dict) and tool_input.get("url") else None,
        "query_sha256": digest(tool_input.get("query")) if isinstance(tool_input, dict) and tool_input.get("query") else None,
        "result_urls": urls,
        "response_sha256": digest(resp) if resp is not None else None,
    }
    with S.locked(sid):
        st = S.load(sid)
        if not S.is_running(st):
            return
        S.append_private(os.path.join(S.run_dir(sid), "sources.jsonl"), json.dumps(record, ensure_ascii=False) + "\n")


def subagent_stop(event):
    sid = event.get("session_id")
    if not sid or not S.is_running(S.load(sid)):
        return
    if event.get("stop_hook_active"):
        return  # one repair attempt only; the moderator handles whatever comes back
    found = turns.check(event.get("last_assistant_message", ""))
    if found:
        print(json.dumps({"decision": "block",
                          "reason": "Your turn is not valid Colosseum output. Fix these and reply again with one "
                                    "```json block: " + "; ".join(found)}, ensure_ascii=False))


def main(argv):
    try:
        event = json.load(sys.stdin)
        {"pre": pre, "post": post, "subagent-stop": subagent_stop}[argv[0]](event)
    except Exception:  # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
