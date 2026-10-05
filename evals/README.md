# Colosseum evals

[한국어](README.ko.md)

Cases for `claude plugin eval` (Claude Code v2.1.269 or later). Each case runs with and without the plugin, and the report shows the difference.

| Group | Cases | Checks | Graders |
|-------|-------|--------|---------|
| `trig-pos-*` | 5 | The skill starts on debate, critique and fact-check requests | `tool_used: Skill` |
| `trig-neg-*` | 5 | It stays out of lookups, summaries, translation, code and arithmetic | Skill and Agent never called |
| `acc-*` | 10 | Common misconceptions with known answers | LLM judge against a gold answer, URL present, report format, baseline recorded |
| `con-*` | 4 | Contested questions | LLM judges for balance and no false consensus, URL present, opposing-case section |

Tags: `smoke` (all trigger cases), `trigger`, `negative`, `accuracy`, `factual`, `contested`, `decision`.

## Running

```bash
claude plugin eval . --tag smoke --runs 1 --ablation none
claude plugin eval . --allow-tools WebSearch WebFetch --judge-model sonnet -j 2 --max-cost-usd 60
```

- A full debate case costs about $1 per run with Sonnet. The 14 `acc-*` and `con-*` cases with 3 runs and the no-plugin arm cost about $50 to $90.
- Granting `Bash` needs a sandbox backend (bubblewrap and socat on Linux); without one the run is refused.
- External agent CLIs usually fail inside the eval sandbox (temporary HOME, no credentials), so evals measure a Claude-only roster.
- Use `--judge-model sonnet` for the LLM graders on long Korean reports.

## Comparing versions

Run the suite on both versions and compare `aggregates` and `costUsd` in the JSON output:

```bash
git worktree add ../colosseum-old <old-tag>
claude plugin eval ../colosseum-old --allow-tools WebSearch WebFetch --json old.json
claude plugin eval . --allow-tools WebSearch WebFetch --json new.json
```

Compare at matched cost. A version that scores higher only because it spent more is not better.
