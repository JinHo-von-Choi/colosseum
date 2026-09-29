# Colosseum

> Web-search-grounded adversarial debate between independent AI agents.

Colosseum is a Claude Code skill that puts a question in front of several independent agents. They draft positions blind, attack each other's factual claims with live web searches, concede when proven wrong, and converge on an answer. If they cannot agree within 5 rounds, Claude issues a forced, conditional verdict. The final answer is decided by argument quality and evidence, never by majority vote.

## How It Works

```
Phase 0  Parse the question (type, stakes, debate axis, participant roster)
Phase 1  Build a fact base with 2-3 web searches from opposing angles
Phase 2  Blind drafts: every participant declares a position without seeing the others
Phase 3  Adversarial loop (max 5 rounds): Prosecutor / Defender / Adverse Witness,
         every attack backed by a live search, one role switch allowed
Phase 4  Verdict: per-conflict rulings, Devil's Advocate challenge, FinalScore,
         optional retrial, synthesized answer
```

### Roles

| Role | Who | Job |
|------|-----|-----|
| Moderator | Claude (the session running the skill) | Runs the protocol, performs searches for CLI agents, records state, judges. Never argues a side. |
| Participants | External AI CLIs and/or Claude subagents | 3-4 independent agents that hold and defend positions |
| Devil's Advocate | A fresh Claude subagent | Attacks the draft final answer |
| Extra juror | A heterogeneous model | Added for high-stakes questions |

Each Claude participant runs as its own subagent with its own context, launched in parallel. Blind drafting is therefore real isolation, not one model role-playing four voices.

### Participant roster

| CLIs available | Roster |
|----------------|--------|
| 0 | 4 Claude subagents: Pragmatist, Skeptic, Idealist, Realist |
| 1 | That CLI + 2 Claude subagents (Skeptic, Realist) |
| 2 or more | Up to 3 CLIs (priority gemini > llm > aichat) + 1 Claude subagent (Skeptic) |

A CLI that fails authentication or times out twice is dropped and replaced by a Claude subagent.

### Round flow

Each round, the Moderator picks the most important open conflict and assigns roles for it:

- Defender: the participant whose claim is under attack
- Prosecutor: the participant most directly opposed to that claim
- Adverse Witness: a non-party participant who checks premises both sides share

After each round the Moderator records `CONVERGENCE` (share of conflicts resolved) and `INDEPENDENCE` (1 minus the share of cited URLs used by two or more participants), then applies these rules in order:

1. All conflicts resolved or CONVERGENCE ≥ 80 → stop (consensus)
2. Role switch unused and a trigger fires (INDEPENDENCE < 40, stalled convergence, or no successful fact-check) → swap Prosecutor and Defender, continue
3. Two consecutive rounds with zero concessions → stop (deadlock)
4. Round 5 finished → stop (exhausted)

### Verdict and scoring

```
FinalScore = 0.45 × Accuracy + 0.35 × Evidence + 0.20 × Independence
```

- Accuracy: share of factual claims in the final answer verified by search
- Evidence: average source reliability × claim alignment for the final answer
- Independence: INDEPENDENCE from the last round

Automatic retrial, each at most once:

- Independence < 60 → one extra debate round, only if rounds remain (the 5-round cap is never exceeded)
- Evidence < 55 → up to 3 extra verification searches by the Moderator (not a debate round)

A session is capped at 25 web searches. Claims that could not be checked are marked unverified and lower Accuracy.

## Requirements

- A web search tool, either of:
  - Claude Code's built-in `WebSearch`
  - [Brave Search MCP](https://github.com/brave/brave-search-mcp-server) (`brave_web_search`)
- Optional AI CLIs for true multi-model debate:

| CLI | Install | Invocation used |
|-----|---------|-----------------|
| [Gemini CLI](https://github.com/google-gemini/gemini-cli) | `npm install -g @google/gemini-cli` | `gemini -p "<prompt>"` |
| [llm](https://github.com/simonw/llm) | `pip install llm` | `llm < prompt.txt` |
| [aichat](https://github.com/sigoden/aichat) | `cargo install aichat` | `aichat "<prompt>"` |

Prompts are written to a temporary file through a quoted heredoc before being passed to a CLI, so question text is never interpreted by the shell. CLI agents cannot call search tools themselves; they list the queries they need and the Moderator runs them and returns the results unedited.

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

Manual (symlinks the skill into `~/.claude/skills`):

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
```

Examples:

```
colosseum: Is TypeScript worth adopting for a mid-size team?
```

```
비판적으로 분석: RAG vs fine-tuning, which is better for production LLM apps?
```

Purely factual questions that the Phase 1 searches settle outright (two or more agreeing sources, no contrary evidence) skip the debate and return a fact-base answer.

## Output Format

The skill reports in Korean. Structure:

```
=== COLOSSEUM ===

Question      : [question]
Participants  : [roster with model / perspective]
Rounds        : N/5  |  Exit reason: [consensus / deadlock / exhausted / no debate needed]

## Fact Base
## Round Summary        (round, conflict, roles, search result, concession)
## Conflict Verdicts    (A wins / B wins / partial / conditional)
## Consensus
## Unresolved (conditional answer)
## Final Answer
## Meta
- Web searches        : N (initial + debate + retrial) / cap 25
- Final CONVERGENCE / INDEPENDENCE
- Role switch         : unused / used in round N
- Jury                : base / extended (heterogeneous / same-model)
- Devil's Advocate    : [point] → accepted / rejected (reason)
- FinalScore          : N (Accuracy / Evidence / Independence)
- Retrial             : none / independence / evidence / not possible (rounds exhausted)
- Dropped participants
- Conditions under which this answer could be wrong
```

## Constraints

- Every factual attack must be backed by a live web search
- No majority voting; every conflict gets a ruling or an explicit conditional answer
- Deadlock is reported as deadlock, never disguised as consensus
- The Moderator never writes a participant's position
- Hard cap of 5 debate rounds and 1 role switch
- API keys and tokens are never printed or placed in prompts

## License

[MIT](LICENSE)
