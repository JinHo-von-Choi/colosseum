# Development

## Layout

| Path | Contents |
|------|----------|
| `skills/colosseum/SKILL.md` | The skill: rules, routing, commands per phase |
| `skills/colosseum/references/` | Protocol, prompts, formats and report layout the skill loads while it runs |
| `skills/colosseum/scripts/` | Run controller, verdict engine, quote matcher, forecast store, agent relay and registry (Python standard library only) |
| `workflows/` | `debate.js` and `forecast.js` for the Workflow tool |
| `experimental/` | Unmaintained workflows, not loaded by the plugin |
| `agents/` | `participant` (web tools only) and `cli-proxy` (runs external agents) |
| `hooks/hooks.json` | Budget, messaging and turn-format hooks |
| `tests/` | Unit, parity, boundary and workflow tests |
| `evals/` | Cases for `claude plugin eval` |

The workflows cannot import files, so each one carries the same `colosseum-lib` and `colosseum-runtime` blocks. Edit them in `workflows/debate.js` and copy them to the others:

```bash
python3 tools/sync_workflow_blocks.py
```

A test fails if the copies differ.

## When to add defensive code

Add a check, fallback or guard only when one of these holds:

- a test reproduces the failure it prevents, or
- it sits on a named trust boundary: user input, external agent output, web content, the file system, the shell.

Validate once at that boundary and trust the data inside. Do not guard states that an earlier step already rules out. Experimental features get the smallest version that works. Heuristic word lists grow only with real failing examples. Tests check what users see, not internal structure.

## Tests

```bash
python3 -m unittest discover -s tests
```

Node 18 or later runs the JavaScript checks; without Node they are skipped. Set `COLOSSEUM_REQUIRE_NODE=1` to make a missing Node an error, as CI does.

| File | Covers |
|------|--------|
| `test_scripts.py` | Verdict engine, quote samples, baseline, checklist, turn format, state machine, hooks |
| `test_p0.py` | Quote reversals, per-claim support, snippet checks, claim IDs, run isolation, forecast store under concurrency |
| `test_contract.py` | Evidence rules, invariance to duplicate relations and list order, all 4,096 four-node graphs against a reference implementation, Python and JavaScript parity |
| `test_js_parity.py` | The workflows' JavaScript library against the Python scripts |
| `test_boundaries.py` | Agent relay, log redaction, installer |
| `test_agents.py` | Agent registry, detection, probing, roster |
| `test_decision.py` | Decision records and what-if |
| `test_materials.py` | Material snapshots, material quote checks, materials in the debate workflow |
| `test_modes.py` | Mode aggregation and forecast scoring |

`tests/workflow_harness.py` runs a whole workflow under Node with a scripted `agent()`. Use it to test orchestration without model calls.

## Evals

```bash
claude plugin eval . --tag smoke --runs 1 --ablation none          # trigger cases only
claude plugin eval . --allow-tools WebSearch WebFetch --judge-model sonnet -j 2 --max-cost-usd 60
```

| Group | Cases | Checks |
|-------|-------|--------|
| `trig-pos-*` | 5 | The skill starts on debate, critique and fact-check requests |
| `trig-neg-*` | 5 | It stays out of lookups, summaries, translation, code and arithmetic |
| `acc-*` | 10 | Common misconceptions with known answers |
| `con-*` | 4 | Contested questions: balance, no false consensus |

A full debate case costs about $1 per run with Sonnet. External agent CLIs usually fail inside the eval sandbox, so evals measure a Claude-only roster. Compare versions at matched cost.
