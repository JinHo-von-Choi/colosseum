# Usage

## Asking a question

Start the request with a trigger word (`colosseum`, `팩트체크`, `AI 토론`, `여러 AI에게 물어봐`, `비판적으로 분석`, `다양한 관점`) and state the question. Colosseum picks a procedure from the question type:

| Question type | Example | Procedure |
|---------------|---------|-----------|
| Factual, technical | "Does PostgreSQL's SERIALIZABLE level prevent write skew?" | Debate with quote-checked evidence |
| Decision | "Should we replace polling with a message queue?" | Debate plus the strongest alternative plan and the signals that would favor it |
| Normative | "Should code review be mandatory for hotfixes?" | Rules on the factual premises; value premises become "if you weigh X over Y, then A" |
| Forecast, estimate (experimental) | "Will X ship before June 2027?" | Independent estimates, anonymous feedback rounds, pooled forecast |
| Diagnostic (experimental) | "Why did our p99 latency double last week?" | Competing hypotheses and an evidence matrix |
| Creative (experimental) | "Name ideas for an internal CLI" | Silent generation, merge, blind ranking |

Better questions get better reviews:

- For decisions, list the options (including "keep the current approach") and the constraints that rule options out.
- Give the date the answer should hold for ("as of 2026-10") when facts change over time.
- For forecasts, state how the question resolves and by when. Colosseum asks if these are missing.

## Choosing participants

By default the roster has three participants. Installed AI agent CLIs from other model families take up to two seats; the host's own model fills the rest. You can steer this in the request:

| You write | Result |
|-----------|--------|
| "use codex and kimi" | those agents first, in that order |
| "only gemini" | gemini and Claude, no other external agent |
| "no external agents" | three participants on the host's own model |

Before anything is sent to an external agent, Colosseum names the providers that will receive the question. See [External agents](agents.md).

## Reading the report

| Section | What to look for |
|---------|------------------|
| Baseline | `BASELINE_VOTE` and `P0`: the answer before any debate. The final answer either keeps it or says why it departs from it. |
| Rounds | Which claims were attacked, the quote check results, and whether position changes were backed by evidence. A change without evidence is logged as `CONFORMITY_FLIP`. |
| Conflict verdicts | The engine's verdict per issue and the juror's ruling in both orders. "Order-sensitive" means the juror changed its mind when the sides were swapped. |
| Unresolved issues | Conditional answers: "if X holds, A; otherwise B". |
| Final answer | Every factual claim carries a source ID. `P_final` is marked UNCALIBRATED. |
| Sources | For each quote: how the page was obtained, the check result and the reason, and whether the quote supports the claim. |
| Checklist | Share of claims backed by verified quotes, source quality, independent sources per decisive claim. There is no single score. |

Quote check results:

| Mark | Meaning | Counts as evidence |
|------|---------|--------------------|
| `v` | The quote appears word for word on the page, and no condition in its sentence was cut off | yes |
| `snippet` | The page could not be fetched; the quote appears word for word in a search snippet | yes, with half weight |
| `n` | Needs review: a near match, or a verbatim quote that drops an "if", "only", "except" or similar from its sentence | no |
| `u` | Not found. Changed numbers, signs, negations or comparisons ("more than" to "less than") always give `u` | no |

A quote also needs a support judgment of `full` or `partial` for the claim it backs. The same quote is judged separately for every claim that cites it.

## Decision records

For decision and technical questions the skill writes `decision.md` (an ADR) and `decision.json` into the run directory. The record contains:

- the recommendation and the conditions it depends on
- up to three decisive pieces of evidence, with quotes and check results
- the strongest counter-argument that was not refuted
- next checks: quotes that need review, claims with only one independent source, unresolved conflicts
- the baseline and how the final answer relates to it
- verdicts that flip when the scoring margins move slightly, marked "sensitive"
- the limits of the review and the versions used

The status starts as `proposed`. You decide. To record the decision:

```bash
colosseum.py adr --session <id> --run <run_id> --status accepted
```

Statuses: `proposed`, `accepted`, `rejected`, `deferred`, `needs-experiment`.

## What-if

Ask "what if we drop source E3?" or "what if claim r1.i1.pro.B.0 is unproven?". Colosseum recomputes the verdict on the same graph without calling any model and lists the claims and conflicts that changed, the ones that did not, and the attack or support path each change followed. One change at a time.

```bash
colosseum.py whatif --session <id> --run <run_id> --exclude-evidence E3
colosseum.py whatif --session <id> --run <run_id> --unprove-claim r1.i1.pro.B.0
```

This shows how the conclusion depends on its evidence. It does not predict anything about the world.

## Forecasts (experimental)

Probability forecasts are saved in a local store shared across sessions. When the event resolves, record the outcome and score the record:

```bash
colosseum.py forecast list
colosseum.py forecast resolve --id <forecast_id> --outcome 1
colosseum.py forecast score
```

`score` reports the Brier score, log loss and calibration bins. After 20 resolved forecasts, `forecast fit` suggests an extremizing factor for pooling; treat it as a rough in-sample estimate.

## Interrupted runs

A run keeps its progress on disk. If the session stops in the middle, ask Colosseum to continue: it resumes from the last completed phase. A new question always starts a new run, and files from earlier runs are never mixed into it.

```bash
colosseum.py runs --session <id>        # list runs
colosseum.py resume --session <id>      # continue the current run
colosseum.py restart --session <id>     # stop it and start a new run
```

`colosseum.py` is `skills/colosseum/scripts/colosseum.py` in the plugin. All commands are listed in the [Reference](reference.md).
