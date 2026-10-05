"""Run a workflow script, or its shared blocks, under Node with a scripted stand-in for agent().

The stand-in answers each agent() call from a list of rules matched on the call's label
(a regular expression) and, optionally, on a substring of its prompt. The first matching
rule wins; a rule with "times" stops matching after that many uses. Calls with no
matching rule return null, the same as a failed agent.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NODE = shutil.which("node")
if os.environ.get("COLOSSEUM_REQUIRE_NODE") == "1" and not NODE:
    raise RuntimeError("COLOSSEUM_REQUIRE_NODE=1 but node is not installed; the JavaScript checks would be skipped")

PRELUDE = r"""
const fs = require('fs')
const INPUT = JSON.parse(fs.readFileSync(0, 'utf8'))
const CALLS = []
const LOGS = []
const USED = INPUT.rules.map(() => 0)
async function agent(prompt, opts) {
  opts = opts || {}
  CALLS.push({ label: opts.label || '', phase: opts.phase || '', prompt })
  for (let i = 0; i < INPUT.rules.length; i++) {
    const r = INPUT.rules[i]
    if (r.times !== undefined && USED[i] >= r.times) continue
    if (!new RegExp(r.label).test(opts.label || '')) continue
    if (r.prompt && !prompt.includes(r.prompt)) continue
    USED[i]++
    return JSON.parse(JSON.stringify(r.response))
  }
  return null
}
async function parallel(fns) { return Promise.all(fns.map((f) => f())) }
async function pipeline(items, first, ...rest) {
  return Promise.all(items.map(async (x) => { let v = await first(x); for (const st of rest) v = await st(v, x); return v }))
}
function phase() {}
function log(m) { LOGS.push(String(m)) }
const args = INPUT.args
"""


def _block(text, name):
    m = re.search(r"// ==== %s begin ====.*?// ==== %s end ====" % (name, name), text, re.DOTALL)
    return m.group(0)


def _run(source, payload):
    with tempfile.NamedTemporaryFile("w", suffix=".cjs", delete=False, encoding="utf-8") as f:
        f.write(source)
        path = f.name
    try:
        r = subprocess.run([NODE, path], input=json.dumps(payload), capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            raise RuntimeError(r.stderr)
        return json.loads(r.stdout)
    finally:
        os.unlink(path)


def run_workflow(name, args, rules):
    """Run workflows/<name>.js end to end. Returns {"result", "calls", "logs"} or {"error", ...}."""
    with open(os.path.join(ROOT, "workflows", name + ".js"), encoding="utf-8") as f:
        body = f.read().replace("export const meta", "const meta", 1)
    source = PRELUDE + """
;(async () => {
  try {
    const result = await (async () => {
%s
    })()
    process.stdout.write(JSON.stringify({ result, calls: CALLS, logs: LOGS }))
  } catch (err) {
    process.stdout.write(JSON.stringify({ error: String(err && err.stack || err), calls: CALLS, logs: LOGS }))
  }
})()
""" % body
    return _run(source, {"args": args, "rules": rules})


def run_runtime(script, args, rules):
    """Run the lib and runtime blocks of debate.js, then `script` (the body of an async
    function whose return value is reported as "result")."""
    with open(os.path.join(ROOT, "workflows", "debate.js"), encoding="utf-8") as f:
        text = f.read()
    source = PRELUDE + "const A = args\n" + _block(text, "colosseum-lib") + "\n" + _block(text, "colosseum-runtime") + """
;(async () => {
  try {
    const result = await (async () => {
%s
    })()
    process.stdout.write(JSON.stringify({ result, calls: CALLS, logs: LOGS }))
  } catch (err) {
    process.stdout.write(JSON.stringify({ error: String(err && err.stack || err), calls: CALLS, logs: LOGS }))
  }
})()
""" % script
    return _run(source, {"args": args, "rules": rules})
