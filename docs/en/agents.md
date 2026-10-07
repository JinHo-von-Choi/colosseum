# External agents

Participants from different model families make different mistakes, so Colosseum uses the AI agent CLIs installed on your machine next to the host's own model.

## Supported agents

| id | Tool | Run as |
|----|------|--------|
| `codex` | OpenAI Codex CLI | `codex exec --sandbox read-only --skip-git-repo-check -`, prompt on stdin |
| `gemini` | Gemini CLI | `gemini`, prompt on stdin |
| `kimi` | Kimi Code CLI | `kimi -p <prompt>` |
| `mcode` | MiniMax Code | `mcode exec <prompt>` |
| `qwen` | Qwen Code | `qwen`, prompt on stdin |
| `opencode` | OpenCode | `opencode run <prompt>` |
| `hermes` | Hermes Agent | `hermes -z <prompt>` |
| `openclaw` | OpenClaw | `openclaw agent --agent main --message <prompt>`; the gateway must be running |
| `cursor-agent` | Cursor CLI | `cursor-agent -p --output-format text <prompt>` |
| `copilot` | GitHub Copilot CLI | `copilot -p <prompt>` |
| `crush` | Crush | `crush run <prompt>` |
| `amp` | Amp | `amp -x <prompt>` |
| `goose` | Goose | `goose run --no-session -i -`, prompt on stdin |
| `llm` | llm | `llm`, prompt on stdin |
| `aichat` | aichat | `aichat`, prompt on stdin |
| `ollama` | Ollama | `ollama run <model>`, prompt on stdin; set the model in your agents file |
| `claude` | Claude Code CLI | `claude -p` with write tools disallowed |

The commands for `cursor-agent`, `copilot`, `crush`, `amp`, `goose`, `qwen` and `aichat` are marked unverified in the registry. Run a probe (below) before relying on them.

## Checking what is available

```bash
relay.py detect            # installed agents, in preference order
relay.py detect --probe    # also send a one-word test prompt to each
```

An agent counts as usable only if it is installed and answers the probe. Probe results are kept for 24 hours; `--refresh` probes again.

## How the roster is built

```bash
relay.py roster --size 3 --probe --prefer codex,kimi
```

1. Agents you name come first, in your order (`--prefer`). With `--only`, no other external agent is used.
2. Remaining seats go to usable agents by priority, one per model family.
3. At most two seats go to external agents, so one participant on the host's own model remains to search the web during the debate. `--max-cli` changes this.
4. The Claude Code CLI joins only when you name it, since in Claude Code it is the same family as the built-in participants.
5. An unused agent from a family not in the roster becomes the juror.
6. Labels A, B, C are assigned in random order.

The output lists the providers that will receive prompts (`transmission`) and warnings in `notes`.

## Your agents file

Create `agents.json` in the Colosseum data directory (see [Reference](reference.md#data-directory)), or point `COLOSSEUM_AGENTS_FILE` at another path. Entries are merged into the built-in registry.

```json
{
  "prefer": ["kimi", "codex"],
  "agents": {
    "opencode": {"family": "zhipu", "family_uncertain": false},
    "ollama": {"vars": {"model": "qwen3"}},
    "gemini": {"disabled": true},
    "my-agent": {
      "name": "My agent",
      "provider": "Mistral",
      "family": "mistral",
      "argv": ["my-agent", "--ask", "{prompt}"],
      "prompt": "arg"
    }
  }
}
```

| Field | Meaning |
|-------|---------|
| `argv` | Program and arguments. `{prompt}` is replaced by the prompt when `prompt` is `"arg"`; `{name}` is replaced by `vars.name`. A placeholder must be a whole argument. |
| `prompt` | `"stdin"` or `"arg"` |
| `family` | The model vendor. Agents of the same family share one vote. |
| `family_uncertain` | Set to `false` once `family` matches the model the agent really uses |
| `provider` | Shown to the user before prompts are sent |
| `vars` | Values for placeholders such as `{model}` or `{agent}` |
| `priority` | Lower runs first when no preference is given |
| `disabled` | `true` removes the agent |

`COLOSSEUM_AGENTS=codex,kimi` sets the preference order for one shell session.

Agents such as OpenCode, Hermes and OpenClaw can run any model. Set their `family` to the vendor of the model you configured. Otherwise two agents running the same model count as independent votes.

## Privacy and safety

- The question and the debate prompts go to each selected agent's model provider. Colosseum names them before the run. If the question contains source code, internal documents or personal data, it asks before adding external agents.
- Prompts never pass through a shell. They are sent on stdin, or as a single program argument for agents that need it.
- Each agent runs in an empty temporary directory, so a coding agent has no project to edit. Codex runs in its read-only sandbox; the Claude CLI runs with write tools disallowed.
- A timeout kills the agent and its child processes. The prompt file is deleted after the run.

`relay.py` is `skills/colosseum/scripts/relay.py` in the plugin.
