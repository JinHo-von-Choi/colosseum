# Colosseum

Web-search-grounded adversarial debate between multiple AI agents. Agents fact-check each other with live searches, reaching consensus or forcing synthesis after 5 rounds.

## How It Works

1. **Phase 0** — Parse the question (type, stakes, debate axis)
2. **Phase 1** — Build a fact base with 2-3 web searches from opposing angles
3. **Phase 2** — Each agent declares an initial position with evidence
4. **Phase 3** — Adversarial loop: agents attack each other's claims using live web searches; concede when proven wrong
5. **Phase 4** — Claude arbitrates: verdicts per conflict, synthesizes final answer

Consensus exits early (CONVERGENCE ≥ 80). Deadlock or 5 rounds triggers forced synthesis.

## Requirements

At least one of the following AI CLIs for multi-agent mode:
- [Gemini CLI](https://github.com/google-gemini/gemini-cli)
- [aichat](https://github.com/sigoden/aichat)
- [llm](https://github.com/simonw/llm)

Zero CLIs available → Claude runs 4-role single-agent mode (Pragmatist / Skeptic / Idealist / Realist).

Brave Search MCP server required for web searches.

## Installation

```bash
git clone https://github.com/nirna/colosseum
cd colosseum && ./install.sh
```

Or via Claude Code plugin system:

```bash
/plugin install nirna/colosseum
```

## Triggers

- `colosseum`
- `여러 AI에게 물어봐`
- `AI 토론`
- `비판적으로 분석`
- `다양한 관점`

## License

MIT
