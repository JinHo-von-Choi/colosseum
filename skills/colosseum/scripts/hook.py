"""Plugin hook entry point. A no-op unless this session has a running Colosseum run.

  pre   (PreToolUse: WebSearch, WebFetch, SendMessage)
        counts searches and fetches against the run budget and denies calls past it;
        denies fetches once the run is in snippet-level mode;
        denies SendMessage while blind drafts are being written.
  post  (PostToolUse: WebSearch, WebFetch)
        appends each call to sources.jsonl in the run directory.
  subagent-stop (SubagentStop: colosseum:participant)
        sends a malformed participant turn back once with the list of problems.

Any internal error exits 0 without output, so a hook bug never blocks the session.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import state as S  # noqa: E402
import turns  # noqa: E402

EXCERPT = 2000


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
    if not sid or not S.is_running(S.load(sid)):
        return
    resp = event.get("tool_response")
    urls = []
    if isinstance(resp, dict):
        for block in resp.get("results") or []:
            for item in (block.get("content") if isinstance(block, dict) else None) or []:
                if isinstance(item, dict) and item.get("url"):
                    urls.append(item["url"])
    record = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "tool": event.get("tool_name"),
        "agent_id": event.get("agent_id"),
        "input": event.get("tool_input"),
        "response_type": type(resp).__name__,
        "response_keys": sorted(resp) if isinstance(resp, dict) else None,
        "urls": urls,
        "response_excerpt": json.dumps(resp, ensure_ascii=False)[:EXCERPT],
    }
    with S.locked(sid) as d:
        with open(os.path.join(d, "sources.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


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
