# Colosseum

[한국어](README.ko.md)

Colosseum is an agent skill that checks a contested question with several independent AI agents and keeps only the conclusions that survive verified evidence.

It runs in agent hosts that load skills, such as Claude Code and Antigravity. Installed as a Claude Code plugin it also gets workflows, hooks and dedicated participant agents; in other hosts it runs the same procedure through its scripts.

Use it to fact-check a claim, compare technical options (a library, an architecture, a way to run a system), or get a decision record you can attach to a design review. It is not meant for lookups, summaries, translation or writing code.

## How it works

1. Each participant drafts an answer without seeing the others.
2. Before any debate, Colosseum records a vote over the drafts and a pooled probability. This is the baseline.
3. Participants attack the claims that decide the answer. Every factual attack must cite a URL and a verbatim quote, and the quote is checked against the page.
4. A deterministic engine computes the verdict from the claims, the evidence and the attacks. The answer can depart from the baseline only when verified evidence, a failed rebuttal and an independent juror all agree.
5. The report shows the baseline, each round, every source with its check result, and the open questions. Ties are reported as conditional answers, never as consensus.

Participants can come from different model families. Colosseum finds the AI agent CLIs installed on your machine (Codex, Gemini CLI, Kimi Code, MiniMax Code, OpenCode, Hermes Agent, OpenClaw and others) and uses them next to the host's own model.

## Quick start

In Claude Code, install from this repository as a plugin marketplace:

```
/plugin marketplace add JinHo-von-Choi/colosseum
/plugin install colosseum@colosseum
```

Then ask a question with one of the trigger words:

```
colosseum: Should our team move from REST polling to a message queue?
```

```
팩트체크 해줘: 인간은 하루 물 8잔을 꼭 마셔야 한다
```

Trigger words: `colosseum`, `팩트체크`, `AI 토론`, `여러 AI에게 물어봐`, `비판적으로 분석`, `다양한 관점`.

To use specific agents, name them in the request: "colosseum, use codex and kimi: ...".

## What you get

- A report: blind-draft positions, the vote baseline (`BASELINE_VOTE`, `P0`), each round, conflict verdicts, the strongest case for the other side, conditional answers for open issues, the final answer with `P_final` marked UNCALIBRATED, sources with their quote check, and an evidence checklist.
- For decision and technical questions, a decision record (`decision.md` and `decision.json`) in the style of an ADR: recommendation and conditions, up to three decisive pieces of evidence, the strongest open counter-argument, next checks and limits.
- What-if answers without new model calls: "what changes if we drop source E3?" recomputes the verdict and shows what changed and why.

## Requirements

| Needed | For |
|--------|-----|
| An agent host that loads skills, with a web search tool | evidence |
| A page fetch tool | checking quotes against pages; without it, only search snippets are checked |
| Python 3.9 or later | the run controller and the verdict engine; without it the skill follows the protocol by hand and says so |
| Other AI agent CLIs (optional) | participants from other model families |

Tested on Linux. On systems without `fcntl` the scripts refuse to start a run.

## Documentation

| Guide | Contents |
|-------|----------|
| [Usage](docs/en/usage.md) | question types, reading the report, decision records, what-if, forecasts, resuming a run |
| [External agents](docs/en/agents.md) | supported agents, detection, roster rules, adding your own agent, privacy |
| [How it works](docs/en/how-it-works.md) | phases, quote checks, evidence rules, the verdict engine |
| [Reference](docs/en/reference.md) | commands, environment variables, data files and formats |
| [Development](docs/en/development.md) | tests, evals, project layout |

## Limits

- Claude Code is the tested host. Other hosts run the skill without workflows and hooks, so budgets and blind-draft isolation depend on the host following the skill's instructions.

- Quotes are checked against the text returned by the page fetch tool, which is itself produced by a model. A quote marked verified is strong evidence, not proof.
- External agents argue from the fact base and the quotes given to them; they do not search the web during the debate. Claude participants do.
- Each run is capped at 3 rounds, 25 searches and 15 page fetches.
- `forecast`, `diagnose` and `ideate` modes are experimental.
- Probabilities are not calibrated.

## Installing as a plain skill

For other hosts, or Claude Code without the plugin system:

```bash
git clone https://github.com/JinHo-von-Choi/colosseum
cd colosseum && ./install.sh
```

This links the skill into `~/.claude/skills/colosseum`. For another host, set the destination to that host's skills directory:

```bash
COLOSSEUM_INSTALL_DEST=<host skills directory>/colosseum ./install.sh
```

In this mode there are no hooks, workflows or plugin agents; the skill runs the same procedure through its scripts. `./install.sh --ref <tag>` pins a version. The installer never overwrites a file or link it did not create.

## License

[MIT](LICENSE)
