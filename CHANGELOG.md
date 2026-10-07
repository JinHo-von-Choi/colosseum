# Changelog

[한국어](CHANGELOG.ko.md)

## 1.0.0 (2026-10-07)

First stable release. Version numbers restart here; the versions below were published under the earlier numbering.

- Reads the materials you point it at (files, directories, URLs, pasted text) before the debate, so participants argue about your case. Quotes from files are checked against a fixed snapshot.
- Blind drafts from independent agents, a vote baseline recorded before the debate, quote-checked evidence rounds and a deterministic verdict engine.
- Quote checks that catch changed numbers, signs, negations, comparisons and dropped conditions, with support judged per claim.
- Uses the AI agent CLIs installed on the machine (Codex, Gemini CLI, Kimi Code, MiniMax Code, OpenCode, Hermes Agent, OpenClaw and others) as participants from other model families. External agents choose their own search queries each turn and get the raw results. `--host-family` tells the roster which family the host's own model belongs to.
- Decision records (ADR Markdown and JSON) and what-if recomputation without model calls.
- Isolated runs with resume and restart, and a transactional forecast store.
- Quote checks count only word-for-word matches; a near match is `u`, not "needs review".
- The diagnostic and idea-generation workflows moved to `experimental/` and are no longer loaded; causal questions go through the debate.
- Runs in agent hosts that load skills; the Claude Code plugin adds workflows, hooks and dedicated agents.
- Documentation in English and Korean.

## Earlier numbering

### 3.3.0-beta.1 (2026-10-05)

#### Added
- Uses the AI agent CLIs installed on the machine as participants: Codex, Gemini CLI, Kimi Code, MiniMax Code, OpenCode, Hermes Agent, OpenClaw, llm, Ollama and the Claude Code CLI; others can be added in a settings file.
- `relay.py detect --probe` lists installed agents and checks that each one answers.
- `relay.py roster` puts agents named by the user first, then fills seats with one agent per model family, keeps one Claude participant for web search, and picks a juror from another family.
- An `agents.json` file in the data directory adds agents, changes their settings, disables them or sets a preference order. `COLOSSEUM_AGENTS` sets the order from the environment.

#### Changed
- External agents run in an empty temporary directory, in read-only mode where the tool has one. Agents that take the prompt as an argument receive it as a single argument, never through a shell.

### 3.2.0-beta.1 (2026-10-05)

#### Fixed
- Quotes with a removed negation, a changed sign or number, or a flipped comparison were accepted as near matches. They now fail the check. A verbatim quote that drops a condition from its sentence is marked "needs review".
- A support judgment made for one claim was reused for other claims citing the same quote. Support is now judged per claim.
- A search result could count as a snippet match without containing the quote. Snippet matches now require the snippet text to contain it.
- Two issues in one round could produce the same claim IDs.
- A new question could read the previous run's files. Each run now has its own directory.
- Concurrent forecast writes could be lost. Forecasts are stored in a transactional database.
- Forecast scores used clipped and transformed probabilities. They now use the stored values.
- In forecast rounds, whether a revision counted as backed by new evidence depended on participant order.
- With three or more positions, the pooled probability treated `1 - p` as the probability of the leading position.
- Repeated relations lowered claim strengths.
- `install.sh` could replace files and links it had not created.

#### Added
- Decision records (`decision.md`, `decision.json`) for decision and technical questions.
- What-if recomputation: drop one source or mark one claim unproven and see what changes, without new model calls.
- `resume`, `restart`, `cancel`, `fail` and `runs` commands.
- `forecast import`, `export` and `status`.

#### Changed
- "Near match" quotes no longer count as evidence.
- The source log keeps hashes and redacted URLs instead of raw responses.
- `forecast`, `diagnose` and `ideate` are marked experimental.

### 3.1.0-beta.1 (2026-09-30)

#### Added
- Procedures by question type: decision, normative, forecast, estimate, diagnostic and creative questions.
- `colosseum:forecast`, `colosseum:diagnose` and `colosseum:ideate` workflows.
- Forecast log with Brier score, log loss, calibration bins and a fitted pooling factor.

### 3.0.0-beta.1 (2026-09-30)

#### Added
- `colosseum:debate` workflow running the whole protocol with schema-checked participant turns.
- Order-swapped juror, override rule and premortem inside the workflow.
- `colosseum:cli-proxy` agent for external CLI participants.

### 3.0.0-alpha.1 (2026-09-30)

#### Added
- Run controller with a phase state machine, vote baseline, quote matching, argument-graph verdict engine and evidence checklist.
- `colosseum:participant` agent with web tools only.
- Hooks for search and fetch budgets, blind-draft messaging, a source log and repair of malformed turns.

#### Fixed
- An undercut without checked evidence could defeat a verified claim.
- Copies of one story counted as independent sources.
- Weak evidence could score below no evidence.

### 2.2.0 (2026-09-30)

#### Changed
- Three participants by default, anonymous labels, hidden probabilities.
- A family-weighted vote and pooled probability recorded before the debate as the baseline; the answer departs from it only on verified evidence.
- One debate round by default, three at most.
- Concessions count only with verified evidence or a named logical error.
- The juror rules twice with the sides swapped.

#### Added
- Verbatim quotes on every factual claim, checked against the page.
- Snippet-level checking when pages cannot be fetched.
- Eval suite for `claude plugin eval`.

### 2.1.0 (2026-09-29)

#### Changed
- Participants run as isolated parallel subagents.
- Roles assigned per conflict for any number of participants.

#### Added
- Plugin marketplace manifest, license and changelog.

### 2.0.0 (2026-04-04)

- Blind drafts, prosecutor, defender and adverse witness roles.

### 1.0.0 (2026-03-17)

- Web-search-grounded multi-agent debate.
