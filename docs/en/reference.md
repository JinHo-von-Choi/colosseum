# Reference

The skill calls these scripts itself. Run them by hand to inspect a run, recompute a verdict, or manage forecasts and agents. Paths are relative to `skills/colosseum/scripts/`. Every command prints one JSON object and exits with 0 on success or 2 on refusal or bad input.

## colosseum.py

Global option: `--data DIR` sets the data directory.

### Runs

| Command | Purpose |
|---------|---------|
| `start --session S [--question-file -] [--stakes low\|medium\|high] [--max-rounds 1-3] [--search-budget N] [--fetch-budget N]` | Open a run. Refused while another run of the session is open. Pass the question as `{"question": "..."}` on stdin |
| `resume --session S` | Continue the open or interrupted run from its last phase |
| `restart --session S [--question-file -]` | Mark the current run interrupted and open a new one |
| `close --session S --status cancelled\|failed [--reason TEXT]`, `finish --session S` | Close the run as cancelled or failed, or as completed |
| `runs --session S` | List the session's runs |
| `materials add --session S [--file -]` | Snapshot materials into the run. Input: `{"materials": [{"path": ...} \| {"url": ...} \| {"text": ..., "title": ...}]}`. Output includes `workflow_arg` for the workflow's `materials` argument |
| `materials list --session S` | The run's materials |
| `status --session S` | Phase, round, budget use and allowed next phases |
| `advance --session S --to PHASE` | Move to the next phase: `fact_base`, `drafts`, `baseline`, `issues`, `round`, `verdict`, `done` |
| `round-result --session S --verified-changes N --open-issues N [--conformity-flips N]` | Record a round; decides whether another round is allowed |
| `fetch-failed --session S --url URL` | Record a failed fetch; three different hosts switch the run to snippet-level checking |

### Computation

These read their input from `--file PATH`, from stdin with `--file -`, or from the current run directory. `--run RUN_ID` reads a closed run of the session.

| Command | Input | Output |
|---------|-------|--------|
| `quote --stdin` | `{"id", "quote", "page"}` | `v`, `n` or `u` with the reason and the matched span |
| `baseline [--extremize A]` | `drafts.json` | vote, `P0`, whether to skip the debate or add a dissenter |
| `verdict [--theta T]` | `graph.json` | labels, statuses, strengths, conflict verdicts; `material_checks` lists material quotes whose status changed on the snapshot check |
| `metrics` | `graph.json` | evidence checklist |
| `whatif --exclude-evidence E \| --unprove-claim C` | `graph.json` | what changed and through which relations |
| `adr [--status S] [--out DIR]` | the debate workflow's result | `decision.md` and `decision.json` |

### Forecasts

| Command | Purpose |
|---------|---------|
| `forecast add [--file PATH]` | Save a forecast record (JSON on stdin by default). Repeating the same record is a no-op |
| `forecast resolve --id ID --outcome 0\|1` | Record the outcome. Repeating it is a no-op; a different outcome is an error |
| `forecast list`, `forecast score`, `forecast fit` | List, score (Brier, log loss, bins), fit the pooling factor |
| `forecast import [--file PATH]` | Add the records of a `forecasts.jsonl` file; known records are skipped |
| `forecast export [--file PATH]` | Write all records as JSON lines |

## relay.py

| Command | Purpose |
|---------|---------|
| `list` | Every agent in the registry and whether it is installed |
| `detect [--probe] [--refresh] [--brief]` | Installed agents in preference order; `--probe` tests that each one answers |
| `roster [--size 3] [--prefer a,b] [--only a,b] [--max-cli N] [--probe] [--seed N]` | Roster for a run |
| `mktemp` | A private directory for a prompt file |
| `run --cli ID --prompt-file PATH [--timeout 180] [--max-output 200000] [--cleanup]` | Send one prompt to one agent |

## Environment variables

| Variable | Effect |
|----------|--------|
| `COLOSSEUM_DATA` | Data directory |
| `COLOSSEUM_AGENTS` | Preferred agents, comma separated |
| `COLOSSEUM_AGENTS_FILE` | Path of the agents file |

## Data directory

The first that is set: `--data`, `COLOSSEUM_DATA`, the plugin data directory, `~/.claude/colosseum`.

```
<data>/
  agents.json                 your agent settings (optional)
  agents-probe.json           probe results
  forecasts.sqlite3           forecast store
  sessions/<session>/
    state.json                the current run's checkpoint
    runs/<run_id>/            everything one run produced
      materials.json          material list with SHA-256 of each snapshot
      materials/M1.txt        material snapshots
      drafts.json, graph.json, baseline.json, verdict.json, result.json
      decision.md, decision.json
      quotes.jsonl            quote checks
      sources.jsonl           searches and fetches
```

Directories are created with mode 0700 and files with 0600. The source log keeps an event ID, the tool, success, latency, URLs with credentials removed, and hashes of the query and response. Delete a run directory to remove its records.

## File formats

### drafts.json

```json
{
  "drafts": [
    {"label": "A", "family": "claude", "position": "P1", "probability": 0.78},
    {"label": "B", "family": "openai", "position": "P2", "probability": 0.60}
  ],
  "verified_counter": false
}
```

`position` groups drafts that mean the same thing. `probability` is the drafter's probability that its own position is right. `verified_counter` is true when a draft's strongest counter-argument is backed by eligible evidence.

### graph.json

```json
{
  "schema": "colosseum.arggraph/v2",
  "evidence": [
    {"id": "E1", "url": "https://...", "quote": "...", "reliability": "high",
     "quote_status": "v", "support": "full", "freshness": "fresh", "origin": "doi:10.1000/xyz"}
  ],
  "claims": [
    {"id": "r0.i-.draft.A.0", "author": "A", "text": "...", "kind": "fact", "evidence": ["E1"]}
  ],
  "relations": [
    {"type": "attack", "subtype": "rebut", "from": "r1.i1.pro.B.0", "to": "r0.i-.draft.A.0"}
  ],
  "conflicts": [{"a": "r0.i-.draft.A.0", "b": "r0.i-.draft.B.0"}],
  "final": [{"claim": "r0.i-.draft.A.0", "weight": 3}]
}
```

| Field | Values |
|-------|--------|
| `reliability` | `high` (primary sources, official documents, peer review), `medium` (major press, expert blogs), `low` |
| `quote_status` | `v`, `snippet`, `n`, `u` |
| `support` | `full`, `partial`, `none`, `unknown` (for this claim) |
| `freshness` | `fresh`, `stale`, `superseded`, `na` (not time-bound), `unknown` |
| `url` | The page URL, or `material:M1` for a file or pasted text the user supplied |
| `origin` | ID of the original source; copies share it. Empty means the URL host |
| `kind` | `fact`, `statistic`, `causal`, `forecast`, `value`, `recommendation` |
| `status` | `active` or `withdrawn` |
| `subtype` | `rebut` (attacks the conclusion), `undercut` (attacks the reasoning), `undermine` (attacks the evidence) |
| `final.weight` | 3 decides the answer, 2 supports it, 1 peripheral |

One evidence record binds one quote to one claim. If two claims cite the same quote, there are two records, each with its own support judgment. Claim IDs read `r<round>.i<issue>.<role>.<label>.<n>`. Graphs without `schema` are read as version 1 with the same fields.
