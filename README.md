# Colosseum

> Web-search-grounded adversarial review: independent blind drafts set a vote baseline, and only evidence with verified verbatim quotes can move the verdict.

Colosseum is a Claude Code skill for contested questions. Three independent agents, ideally from different model families, draft answers without seeing each other. Before any debate, Claude records a family-weighted vote and a pooled probability as the baseline. A short evidence round (1 by default, 3 at most) then attacks the claims that decide the answer. Every factual attack must carry a URL and a verbatim quote, and quotes are checked against the fetched page. The final answer can depart from the baseline only when verified evidence, a failed rebuttal and an independent juror all point the same way.

The design follows the multi-agent debate literature: at matched compute, most of the gain attributed to debate comes from voting over independent samples, while the damage comes from conformity, sycophancy and correlated errors during the exchange. Colosseum therefore maximizes independence before interaction and demands verified evidence for every change during it.

## How It Works

```
Phase 0   Parse the question (type, stakes, as-of date, roster, budget)
Phase 1   Fact base: 3 searches from opposing angles, top pages fetched for quotes
Phase 2   Blind drafts: claims with URL + verbatim quote, key assumptions, cruxes, probability
Phase 2a  Baseline: family-weighted vote and log-odds pooled probability P0
Phase 2b  Issue map: double cruxes, pre-committed searches, value cruxes sent to conditional answers
Phase 3   Evidence rounds (default 1, max 3): steelman gate, quote-checked attacks, evidence-only concessions
Phase 4   Verdict: order-swapped juror rulings, override rule, premortem, evidence-quality checklist
```

### Participant roster

| CLIs available | Roster (3 participants) |
|----------------|-------------------------|
| 0 | 3 Claude subagents, labeled "homogeneous roster" |
| 1 | That CLI + 2 Claude subagents |
| 2 or more | 2 CLIs + 1 Claude subagent |

Participants see each other only as anonymous labels (A, B, C, reshuffled every round). Model names and probabilities are never shown to peers or to the juror. Claude participants start their searches from different angles (supporting evidence, contrary evidence, primary sources), because same-family models tend to share the same mistakes.

### Rules that move the verdict

- Quote check: each cited quote is fetched and classified `v` (exact), `n` (near), or `u` (not found). `u` quotes count for nothing. If page fetching fails for environmental reasons, the run switches to a labeled snippet-level mode instead of stopping.
- Concessions: a position may change only on `v`/`n` evidence or a named logical error. Anything else is logged as a `CONFORMITY_FLIP` and does not count toward convergence.
- Steelman gate: before attacking, the Prosecutor restates the Defender's claim in at most 3 sentences. If the Defender marks it as distorted, the attack is void.
- Stopping: a round in which no position changed on new verified evidence ends the debate.
- Override: the final answer may differ from the vote baseline only if the minority's key quote is re-verified, the majority's rebuttal fails verification, and a juror from a different model family (or a fresh juror, flagged as same-family) independently agrees.
- Juror: each open issue is judged twice with the two sides in swapped order. Disagreement between the two rulings is reported as "order-sensitive".

### Output

The report always includes the blind-draft positions, `BASELINE_VOTE`, `P0`, the per-round quote verification counts, the strongest case for the opposing position, conditional answers for unresolved issues, `P_final` (marked `UNCALIBRATED`), a source list, and an evidence-quality checklist (verification rate, source quality, independent origins per decisive claim). There is no single weighted score.

## Architecture

Three execution modes share one protocol, one data format and one verdict engine. The skill picks the first mode the environment supports.

Questions are routed by type before anything runs:

| Question type | Workflow | Procedure |
|---------------|----------|-----------|
| Factual, technical | `colosseum:debate` | Vote baseline, quote-verified evidence rounds, computed verdicts |
| Decision | `colosseum:debate` (decision mode) | Adds dialectical inquiry: the strongest plan built on the opposite assumptions, with switch signals |
| Normative | `colosseum:debate` (normative mode) | Rules only on empirical premises; value premises become a conditional map |
| Forecast, estimate | `colosseum:forecast` | Base rates, Delphi rounds with anonymous feedback, evidence-gated revisions, pooled forecast, published-forecast blend, forecast log |
| Diagnostic | `colosseum:diagnose` | Competing hypotheses, diagnosticity matrix (explanatory only), pooled probabilities |
| Creative | `colosseum:ideate` | Nominal group technique: silent generation, merge, blind ranking, Borda count |

Probability forecasts go into a forecast log (`colosseum.py forecast add | resolve | score | fit`). Once 20 or more have resolved, the extremizing factor used for pooling is fitted from the log instead of assumed.

| Mode | When | Who holds the flow |
|------|------|--------------------|
| Workflow | Plugin installed and the Workflow tool available (Claude Code v2.1.154 or later) | `workflows/debate.js`, run as `colosseum:debate`: schema-validated turns, JavaScript vote, quote matching and verdict engine |
| Script | Python and Bash available | The Moderator, with `colosseum.py` refusing illegal phase transitions and computing every number |
| Manual | Neither | The Moderator alone, following `references/protocol.md`; the report says so |

In workflow mode the skill opens a run (so the hooks enforce budgets), launches the workflow, shows its report, and recomputes the verdicts with the Python engine as a cross-check. The workflow's JavaScript library is tested for agreement with the Python scripts on the same inputs.

| Part | Path | Role |
|------|------|------|
| Mode workflows | `workflows/forecast.js`, `diagnose.js`, `ideate.js` | Delphi forecasting, ACH-lite diagnosis, nominal group technique |
| Debate workflow | `workflows/debate.js` | Fact base, blind drafts, quote checks, baseline, dissenter, issue map, evidence rounds, order-swapped juror, verdict engine, override rule, premortem, report |
| Launcher skill | `skills/colosseum/SKILL.md` | Core rules and the phase-by-phase command table (about 100 lines) |
| References | `skills/colosseum/references/` | Full protocol and prompts, JSON formats, report format |
| Run controller | `skills/colosseum/scripts/colosseum.py` | Phase state machine (illegal transitions and extra rounds are refused), budgets, snippet-mode switch |
| Computation | `baseline.py`, `quote_match.py`, `verdict_engine.py`, `metrics.py`, `modes.py`, `calibration.py` | Vote and pooled probability, quote classification, argument-graph verdicts, evidence checklist |
| Participant agent | `agents/participant.md` | `colosseum:participant`: web tools only, no messaging or sub-agents, JSON turn format |
| CLI relay agent | `agents/cli-proxy.md` | `colosseum:cli-proxy`: Bash only, relays a prompt to gemini, llm or aichat through a quoted heredoc |
| Hooks | `hooks/hooks.json` | Search and fetch budgets, fetch block in snippet mode, messaging block during blind drafts, source ledger, one-shot repair of malformed turns |

The verdict engine turns the debate into an argument graph. Each claim gets a base score from its evidence (source reliability, quote check, support, freshness), combined by noisy-OR across independent origins, so syndicated copies count once. Attacks become defeats unless the target is clearly stronger; an undercut defeats unconditionally only when it carries checked evidence. Grounded semantics then labels every claim accepted, rejected or undecided, preferred extensions give the branches of a conditional answer, and damped DF-QuAD strengths give the confidence. The same input always yields the same verdict and the same input hash.

Every hook is a no-op unless the current session has a running Colosseum run. Without Python or Bash the skill falls back to a manual mode that follows the same protocol and says so in the report.

## Requirements

- A web search tool, either of:
  - Claude Code's built-in `WebSearch`
  - [Brave Search MCP](https://github.com/brave/brave-search-mcp-server) (`brave_web_search`)
- `WebFetch` for quote verification (optional; without it the run is labeled snippet-level)
- Python 3.9 or later for the scripts (optional; without it the skill runs in manual mode)
- Optional AI CLIs for a heterogeneous roster:

| CLI | Install | Invocation used |
|-----|---------|-----------------|
| [Gemini CLI](https://github.com/google-gemini/gemini-cli) | `npm install -g @google/gemini-cli` | `gemini -p "<prompt>"` |
| [llm](https://github.com/simonw/llm) | `pip install llm` | `llm < prompt.txt` |
| [aichat](https://github.com/sigoden/aichat) | `cargo install aichat` | `aichat "<prompt>"` |

Data disclosure: when external CLIs are used, the question and the debate prompts are sent to those CLIs' model providers. Search queries go to the configured search tool. Prompts are written to a temporary file through a quoted heredoc before being passed to a CLI, so question text is never interpreted by the shell.

## Installation

From this repository as a plugin marketplace:

```bash
/plugin marketplace add JinHo-von-Choi/colosseum
/plugin install colosseum@colosseum
```

Via the official plugin directory:

```bash
/plugin install colosseum@claude-plugins-official
```

Manual (symlinks the skill directory into `~/.claude/skills`; hooks and the participant agent need the plugin install):

```bash
git clone https://github.com/JinHo-von-Choi/colosseum
cd colosseum && ./install.sh
```

## Usage

Include any of these phrases in your prompt:

```
colosseum
여러 AI에게 물어봐
AI 토론
비판적으로 분석
다양한 관점
팩트체크
```

Examples:

```
colosseum: Is TypeScript worth adopting for a mid-size team?
```

```
팩트체크 해줘: 인간은 하루 물 8잔을 꼭 마셔야 한다
```

Simple lookups, summaries, translations and coding tasks are intentionally out of scope and should not trigger the skill.

## Tests

```bash
python3 -m unittest discover -s tests
```

Node is needed for the JavaScript parity tests; they are skipped without it. The unit tests cover the verdict engine (including regression tests for evidence-free undercuts, uncollapsed syndicated copies, non-monotonic scores and credited unverified quotes), 20 labeled quote-matching samples, the vote and pooling rules, the checklist, turn validation, the phase state machine and the hooks. The parity tests run the workflow's JavaScript library against the Python scripts on 43 argument graphs, 20 checklists, the quote samples and 30 baselines, and check that the workflow script parses.

## Evaluation

The `evals/` suite runs with `claude plugin eval` (Claude Code v2.1.269 or later) and compares the plugin against plain Claude Code with the same tools. See [evals/README.md](evals/README.md).

## Constraints

- Every factual attack must carry a live search result, a URL and a verbatim quote
- Unverified quotes carry no weight
- The vote baseline is always reported; overriding it requires verified evidence
- Deadlock is reported as a conditional answer, never disguised as consensus
- The Moderator never writes a participant's position
- At most 3 debate rounds, 25 searches and 15 page fetches per session
- API keys and tokens are never printed or placed in prompts

## License

[MIT](LICENSE)
