# Colosseum

> Web-search-grounded adversarial debate between multiple AI agents.

Agents fact-check each other's claims using live web searches, concede when proven wrong, and reach consensus — or force a verdict after 5 rounds. Final answers are based on argument quality, not majority vote.

## How It Works

```
Phase 0  →  Parse question (type, stakes, debate axis)
Phase 1  →  Build fact base with 2–3 web searches from opposing angles
Phase 2  →  Each agent declares an initial position with evidence
Phase 3  →  Adversarial loop: agents attack claims with live searches;
             concede when shown wrong, hold when attacks fail
Phase 4  →  Claude arbitrates: per-conflict verdicts → synthesized final answer
```

Early exit when CONVERGENCE ≥ 80%. Deadlock or 5 rounds triggers forced synthesis with conditional verdicts.

### Single-agent mode (zero CLIs installed)

Claude runs four internal roles simultaneously:

| Role | Approach |
|------|----------|
| Pragmatist | Fastest viable answer, real-world constraints first |
| Skeptic | Attacks mainstream assumptions, seeks counterexamples |
| Idealist | Best-case scenario, ideal conditions assumed |
| Realist | Resource, time, and risk calculus |

Each role web-searches the others' claims through the same round loop.

## Requirements

- **Brave Search MCP** — required for all web searches during debate
- **One or more AI CLIs** — optional; enables true multi-agent mode

Supported CLIs:

| CLI | Install |
|-----|---------|
| [Gemini CLI](https://github.com/google-gemini/gemini-cli) | `npm install -g @google/gemini-cli` |
| [aichat](https://github.com/sigoden/aichat) | `cargo install aichat` |
| [llm](https://github.com/simonw/llm) | `pip install llm` |

## Installation

Via Claude Code plugin system:

```bash
/plugin install nirna/colosseum
```

Manual:

```bash
git clone https://github.com/nirna/colosseum
cd colosseum && ./install.sh
```

## Usage

Trigger the skill by including any of these phrases in your prompt:

```
colosseum
여러 AI에게 물어봐
AI 토론
비판적으로 분석
다양한 관점
```

Example:

```
colosseum: Is TypeScript worth adopting for a mid-size team?
```

```
비판적으로 분석: RAG vs fine-tuning, which is better for production LLM apps?
```

## Output Format

```
=== COLOSSEUM ===

Question     : [question]
Rounds       : N/5  |  Exit reason: [consensus / deadlock / exhausted]

## Fact Base
[Key facts gathered in Phase 1]

## Round Summary
| Round | Key Conflict | Web Search Result | Concession |
|-------|-------------|-------------------|------------|
| 1     | ...         | ...               | ...        |

## Conflict Verdicts
| Conflict | Agent A | Agent B | Evidence | Verdict |
|----------|---------|---------|----------|---------|
| #1       | ...     | ...     | [URL]    | A wins / draw |

## Consensus
- ...

## Unresolved (conditional answer)
- [If condition X]: A's position holds
- [If condition Y]: B's position holds

## Final Answer
[Evidence-based synthesized conclusion]

## Meta
- Total web searches  : N (initial N + debate N)
- Final convergence   : N%
- Conditions under which this answer could be wrong: ...
```

## Constraints

- Every factual attack must be backed by a live web search — no search, no claim
- Deadlock is reported as deadlock, not disguised as consensus
- Round cap is hard at 5; no extensions

## License

MIT
