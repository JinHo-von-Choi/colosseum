# Colosseum

> Web-search-grounded adversarial review: independent blind drafts set a vote baseline, and only evidence with verified verbatim quotes can move the verdict.

Colosseum is a Claude Code skill for contested questions. Three independent agents, ideally from different model families, draft answers without seeing each other. Before any debate, Claude records a family-weighted vote and a pooled probability as the baseline. A short evidence round (1 by default, 3 at most) then attacks the claims that decide the answer. Every factual attack must carry a URL and a verbatim quote, and quotes are checked against the fetched page. The final answer can depart from the baseline only when verified evidence, a failed rebuttal and an independent juror all point the same way.

The main use is technical decision review: choosing between designs, libraries or ways of running a system, where the result is a decision record that links each conclusion to its claims, quotes and open counter-arguments. A person makes the final decision.

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

Colosseum uses the AI agent CLIs installed on the machine as participants from other model families: Codex, Gemini CLI, Kimi Code, MiniMax Code (mcode), Qwen Code, OpenCode, Hermes Agent, OpenClaw, Cursor CLI, Copilot CLI, Crush, Amp, Goose, llm, aichat, Ollama and the Claude Code CLI. `relay.py roster` builds the roster:

1. Agents the user names ("use codex and kimi") come first, in that order.
2. Remaining seats go to installed agents that answer a test prompt (`--probe`), by priority, one per model family.
3. By default at most two seats go to external agents; one stays with a Claude participant, which searches the web itself. With no external agent the roster is three Claude participants, labeled "homogeneous roster".
4. The Claude Code CLI joins only when named, since it is the same family as the built-in participants.
5. An unused agent from a family not in the roster becomes the juror.

Participants see each other only as anonymous labels (A, B, C, assigned in random order when the run starts). Model names and probabilities are never shown to peers or to the juror. Claude participants start their searches from different angles (supporting evidence, contrary evidence, primary sources), because same-family models tend to share the same mistakes.

### Rules that move the verdict

- Quote check: each cited quote is fetched and classified `v` (a contiguous span of the page), `n` (review required: a near match, or a verbatim span that drops a condition from its sentence) or `u` (not found). Only display differences are normalized; a changed sign, number, negation or comparison makes a quote `u`. `n` and `u` count for nothing. If page fetching fails, a quote counts at snippet level only when the returned snippet text contains it verbatim, and each evidence item records how it was obtained.
- Support: whether a quote supports a claim is judged separately for every claim that cites it.
- Concessions: a position may change only on eligible evidence (`v` or snippet level, support full or partial, not superseded) or a named logical error. Anything else is logged as a `CONFORMITY_FLIP` and does not count toward convergence.
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
| Forecast, estimate (experimental) | `colosseum:forecast` | Base rates, Delphi rounds with anonymous feedback, evidence-gated revisions, pooled forecast, published-forecast blend, forecast log |
| Diagnostic (experimental) | `colosseum:diagnose` | Competing hypotheses, diagnosticity matrix (explanatory only), pooled probabilities |
| Creative (experimental) | `colosseum:ideate` | Nominal group technique: silent generation, merge, blind ranking, Borda count |

Probability forecasts go into a forecast store (`colosseum.py forecast add | resolve | score | fit | import | export`), a local sqlite database written one transaction at a time. Scores use the stored probabilities as they are. Once 20 or more have resolved, `fit` suggests an extremizing factor; it is an in-sample, experimental value and every probability stays UNCALIBRATED.

### Decision records and what-if

For decision and technical questions, `colosseum.py adr` turns the debate result into a Markdown ADR and a JSON record: the recommendation and its conditions, up to three decisive evidence items, the strongest open counter-argument, next checks, the baseline versus the final answer, sensitivity to small policy changes, limits and versions. Every line comes from the structured result. The record stays `proposed` until the person deciding sets its status.

`colosseum.py whatif --exclude-evidence E3` (or `--unprove-claim <id>`) recomputes the verdicts on the fixed graph without calling a model, and lists which verdicts changed, which did not, and the relations through which each change spread.

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
| Run controller | `skills/colosseum/scripts/colosseum.py` | Phase state machine (illegal transitions and extra rounds are refused), run isolation, resume and restart, budgets, snippet-mode switch |
| Computation | `baseline.py`, `quote_match.py`, `graph.py`, `verdict_engine.py`, `metrics.py`, `modes.py`, `calibration.py`, `decision.py` | Vote and pooled probability, quote classification, evidence policy, argument-graph verdicts, evidence checklist, forecast store, decision records and what-if |
| Agent relay | `skills/colosseum/scripts/relay.py`, `agents.json` | Agent registry, detection and probing, roster selection, running an agent without a shell with a timeout and cleanup |
| Data contract | `skills/colosseum/references/contract.md` | Source, quote, claim, assessment and run records; version strings |
| Participant agent | `agents/participant.md` | `colosseum:participant`: web tools only, no messaging or sub-agents, JSON turn format |
| CLI relay agent | `agents/cli-proxy.md` | `colosseum:cli-proxy`: writes the prompt with the Write tool and runs `relay.py` |
| Hooks | `hooks/hooks.json` | Search and fetch budgets, fetch block in snippet mode, messaging block during blind drafts, source ledger, one-shot repair of malformed turns |

The verdict engine turns the debate into an argument graph. Each claim gets a base score from its eligible evidence (source reliability, quote check, support, freshness), combined by noisy-OR across independent origins, so syndicated copies count once. Repeated relations are counted once. Attacks become defeats unless the target is clearly stronger; an undercut defeats unconditionally only when it carries checked evidence. Grounded semantics then labels every claim accepted, rejected or undecided, preferred extensions give the branches of a conditional answer, and damped DF-QuAD strengths give the confidence. The same input always yields the same verdict and the same input hash.

Every hook is a no-op unless the current session has a running Colosseum run. Without Python or Bash the skill falls back to a manual mode that follows the same protocol and says so in the report.

## Requirements

- A web search tool, either of:
  - Claude Code's built-in `WebSearch`
  - [Brave Search MCP](https://github.com/brave/brave-search-mcp-server) (`brave_web_search`)
- `WebFetch` for quote verification (optional; without it the run is labeled snippet-level)
- Python 3.9 or later for the scripts (optional; without it the skill runs in manual mode)
- Optional AI agent CLIs for a heterogeneous roster. Any of these that is installed and signed in can join:

| id | Tool | How Colosseum runs it |
|----|------|-----------------------|
| `codex` | OpenAI Codex CLI | `codex exec --sandbox read-only -`, prompt on stdin |
| `gemini` | Gemini CLI | `gemini`, prompt on stdin |
| `kimi` | Kimi Code CLI | `kimi -p <prompt>` |
| `mcode` | MiniMax Code | `mcode exec <prompt>` |
| `qwen` | Qwen Code | `qwen`, prompt on stdin |
| `opencode` | OpenCode | `opencode run <prompt>` |
| `hermes` | Hermes Agent (Nous Research) | `hermes -z <prompt>` |
| `openclaw` | OpenClaw | `openclaw agent --agent main --message <prompt>` (gateway running) |
| `cursor-agent`, `copilot`, `crush`, `amp`, `goose` | Cursor CLI, Copilot CLI, Crush, Amp, Goose | their non-interactive modes; not yet checked against their docs, so run `detect --probe` first |
| `llm`, `aichat`, `ollama` | general model CLIs | prompt on stdin; `ollama` needs a model name in the user file |
| `claude` | Claude Code CLI | `claude -p` with write tools disallowed |

The list lives in `skills/colosseum/scripts/agents.json`. A user file at `<data>/agents.json` (or `$COLOSSEUM_AGENTS_FILE`) adds agents, overrides any field, disables agents and sets a preference order; `$COLOSSEUM_AGENTS=codex,kimi` sets the order for one shell. For agents that can run any model (OpenCode, Hermes, OpenClaw and others), set `family` to the model's vendor so the family-weighted vote stays correct; until then the roster marks the family as a guess.

```bash
python3 skills/colosseum/scripts/relay.py detect --probe     # what is installed and answering
python3 skills/colosseum/scripts/relay.py roster --prefer codex,kimi
```

Agents run through `scripts/relay.py` with a fixed argument list and never through a shell. The prompt reaches the agent on stdin, or as one argument for agents that only take it that way (no NUL bytes, 100,000 bytes at most, a leading "-" is padded with a space). Each agent starts in an empty private directory, so a coding agent has no repository to change, and read-only modes are used where the tool has one. The relay enforces a timeout (the agent's whole process group is killed), caps the output and deletes the prompt afterwards.

Data disclosure: when external agents are used, the question and the debate prompts are sent to those agents' model providers. The roster lists them (`transmission`) and the run plan names them before anything is sent, and questions that contain repository code, internal documents or personal data need the user's approval. Search queries go to the configured search tool.

Local records: each run keeps its files under `<data>/sessions/<session>/runs/<run_id>/` (directories 0700, files 0600 on POSIX). The source log stores an event id, the tool, success, latency when reported, URLs with credentials removed, and hashes of the query and response. Raw query and response text is kept only with `COLOSSEUM_DEBUG_LOG=1`, and is redacted there too; delete a run's directory to remove its records.

## Installation

From this repository as a plugin marketplace:

```bash
/plugin marketplace add JinHo-von-Choi/colosseum
/plugin install colosseum@colosseum
```

Manual install, which links the skill directory into `~/.claude/skills`:

```bash
git clone https://github.com/JinHo-von-Choi/colosseum
cd colosseum && ./install.sh               # or ./install.sh --ref <tag or commit> to pin a version
```

`install.sh` never overwrites anything it did not create: an existing file, directory, link to another place or broken link at the destination stops it with a message and nothing changes. To roll back, run `./install.sh --ref <earlier tag or commit>`.

| | Plugin install | Manual install |
|---|---|---|
| Workflows (`colosseum:debate` and the modes) | yes | no (script or manual mode) |
| Hooks (budgets, blind-draft messaging block, source log, turn repair) | yes | no |
| `colosseum:participant`, `colosseum:cli-proxy` agents | yes | no (general-purpose agents) |
| Without Python | manual mode only | manual mode only |

Tested on Linux only. macOS and Windows are not listed as supported until they are tested; on platforms without `fcntl` the scripts refuse to open a run.

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

Node 18 or later is needed for the JavaScript checks. Locally they are skipped without Node; with `COLOSSEUM_REQUIRE_NODE=1` (as in CI) a missing Node fails the run instead.

- `test_p0.py`: the defects found in the 3.1.0-beta.1 review, each next to a control: quote reversals, shared support assessments, snippet approvals, claim id collisions, stale runs, lost forecast writes. Each of these tests fails on 3.1.0-beta.1.
- `test_contract.py`: one evidence policy, relation and list-order invariance, all 4,096 four-node graphs against an independent implementation of grounded, preferred and stable semantics, full Python/JavaScript output parity, validation errors, URL and origin parity, Delphi order independence.
- `test_boundaries.py`: the CLI relay (terminators, command substitution, quotes, newlines, NUL and 1 MB prompts arrive byte for byte with no shell; timeouts kill child processes), audit-log redaction with synthetic secrets, installer conflicts.
- `test_decision.py`: decision records and what-if recomputation.
- `test_agents.py`: the agent registry and user overrides, detection and probing with fake agents, roster selection, argument-mode prompts.
- `test_scripts.py`, `test_js_parity.py`, `test_modes.py`: the verdict engine, quote samples, baseline, checklist, turn validation, state machine, hooks, mode aggregation and the forecast store.

`tests/workflow_harness.py` runs a whole workflow under Node with a scripted `agent()`. It checks the orchestration logic, not the behavior of a real Claude Code host.

## Evaluation

The `evals/` suite runs with `claude plugin eval` (Claude Code v2.1.269 or later) and compares the plugin against plain Claude Code with the same tools. See [evals/README.md](evals/README.md).

## Constraints

- Every factual attack must carry a live search result, a URL and a verbatim quote
- Unverified and review-required quotes carry no weight
- The vote baseline is always reported; overriding it requires verified evidence
- Deadlock is reported as a conditional answer, never disguised as consensus
- The Moderator never writes a participant's position
- At most 3 debate rounds, 25 searches and 15 page fetches per session
- API keys and tokens are never printed or placed in prompts

## License

[MIT](LICENSE)
