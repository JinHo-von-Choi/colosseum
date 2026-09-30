# Colosseum eval suite

Runs with `claude plugin eval` (Claude Code v2.1.269 or later). Every case runs twice by default: once with the plugin and once without it (plain Claude Code with the same tools), and the report shows the difference Δ.

## Cases

| Group | Cases | What it checks | Graders |
|-------|-------|----------------|---------|
| `trig-pos-*` | 5 | The skill fires on debate, critical-analysis and fact-check requests | `tool_used: Skill` |
| `trig-neg-*` | 5 | The skill stays silent on lookups, summaries, translation, code and arithmetic | Skill and Agent never called |
| `acc-*` | 10 | Stable misconceptions with known answers | LLM judge against a gold answer, URL present, report format, baseline recorded |
| `con-*` | 4 | Contested questions without a single right answer | LLM judges for balance and no false consensus, URL present, opposing-case section |

Tags: `smoke` (all trigger cases, cheap), `trigger`, `negative`, `accuracy`, `factual`, `contested`, `decision`.

## Running

Cheap smoke run (trigger cases only, a few cents):

```bash
claude plugin eval . --tag smoke --runs 1 --ablation none
```

Full run with web access:

```bash
claude plugin eval . --allow-tools WebSearch WebFetch --judge-model sonnet -j 2 --max-cost-usd 60
```

Notes:

- A full debate case costs roughly $1 per run with Sonnet as the session model. With the default 3 runs and the no-plugin baseline arm, the 14 `acc-*` and `con-*` cases cost about $50 to $90.
- Do not grant `Bash` on machines without a sandbox backend (bubblewrap and socat on Linux): the run is refused. The skill computes the pooled probability by hand when Bash is unavailable.
- External AI CLIs usually fail inside the eval sandbox (temporary HOME, no credentials), so these runs measure the Claude-only roster.
- If the network blocks page fetches, the skill switches to its snippet-level verification mode and says so in the report.
- The default judge is haiku. Use `--judge-model sonnet` for the `llm` graders on the long Korean reports; haiku produced unreliable verdicts on them.

## Comparing versions

To measure a change against the previous protocol, run the suite on both versions and compare `aggregates` and `costUsd` in the JSON output:

```bash
git worktree add ../colosseum-v2.1 32c09e0
claude plugin eval ../colosseum-v2.1 --allow-tools WebSearch WebFetch --json v21.json
claude plugin eval . --allow-tools WebSearch WebFetch --json v22.json
```

Compare at matched cost. A version that scores higher only because it spent more tokens has not shown that its protocol is better.
