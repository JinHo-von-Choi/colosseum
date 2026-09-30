# Changelog

## 3.0.0-beta.1 (2026-09-30)

### Added
- `workflows/debate.js`, run as `colosseum:debate`: the whole protocol as a workflow script with schema-validated turns. It builds the fact base, runs blind drafts in parallel, checks quotes, computes the vote baseline, runs a dissenter for homogeneous unanimous rosters, maps double cruxes, runs evidence rounds (prosecutor and adverse witness in parallel, then defender), asks the juror in both orders, computes verdicts with the argument-graph engine, applies the override rule, runs a premortem and writes the report.
- The workflow carries a JavaScript port of the vote, pooling, quote matching, verdict engine and checklist. `tests/test_js_parity.py` checks it against the Python scripts under Node.
- `colosseum:cli-proxy` agent that relays prompts to external AI CLIs, so CLI participants and CLI jurors work inside the workflow.
- Workflow mode in the skill: open the run, launch the workflow, show the report, recompute the verdicts with the Python engine as a cross-check, close the run. Script mode and manual mode remain as fallbacks.

### Verified
- A plugin workflow resolves as `colosseum:<name>` through the Workflow tool, `agentType: 'colosseum:participant'` resolves inside a workflow, and plugin hooks fire for workflow agents (their searches count against the run budget).
- End-to-end runs through the workflow completed with two evidence rounds, a logged conformity flip, order-swapped juror rulings and a matching Python cross-check.

### Not yet verified
- Accuracy against the vote-plus-verification baseline at matched cost (roadmap stage 3 gate).
- External CLI participants and a non-Claude juror (no CLI was available in the test environment).

## 3.0.0-alpha.1 (2026-09-30)

### Added
- Deterministic core in `skills/colosseum/scripts/` (standard library only): a phase state machine that refuses illegal transitions, extra rounds after a stable round and rounds past the cap; family-weighted vote and pooled probability; quote classification (exact, near by in-order word match with a number guard, unverified); argument-graph verdicts (grounded and preferred semantics, damped DF-QuAD); an evidence-quality checklist.
- `colosseum:participant` plugin agent with web tools only, no messaging or sub-agents, and a JSON turn format.
- Plugin hooks, active only during a Colosseum run: search and fetch budgets, fetch block in snippet mode, SendMessage block during blind drafts, a source ledger with result URLs, and a one-shot repair request for malformed participant turns.
- JSON inputs travel over heredoc stdin and are saved by the scripts, so the Moderator never writes into the plugin data directory.
- Unit tests and a GitHub Actions workflow.

### Fixed
- Verdict engine: an undercut without checked evidence no longer defeats a verified claim; evidence without an origin collapses to its URL host (or one shared cluster) instead of counting as independent; the no-evidence prior is combined by noisy-OR so weak evidence never scores below none; unverified quotes score 0.

### Changed
- SKILL.md is a 100-line launcher. The full protocol, JSON formats and report format moved to `references/`.
- `install.sh` links the whole skill directory, replacing the SKILL.md-only link from earlier versions.
- The skill description names fact-check requests explicitly, and the participant agent is described as internal. With the agent added, a fact-check prompt had stopped triggering the skill (0 of 3 eval runs, against 3 of 3 for 2.2.0); after the change it triggered in 3 of 3.

## 2.2.0 (2026-09-30)

### Changed
- Default roster is 3 participants. With no external CLI the roster is labeled "homogeneous", and Claude participants start their searches from different angles.
- Participants appear only as anonymous labels, reshuffled every round. Model names, personas and probabilities are hidden from peers and from the juror.
- CONFIDENCE is replaced by PROBABILITY, which is never shown to other participants and is no longer used to pick the Adverse Witness. The Adverse Witness is the participant whose draft differs most from both parties.
- Majority voting is no longer forbidden. A family-weighted vote and a log-odds pooled probability (P0) are recorded before any debate as the baseline.
- The final answer can depart from the baseline only when the minority's key quote is re-verified, the majority's rebuttal fails verification, and an independent juror agrees.
- Debate rounds: 1 by default, 3 at most. A round with no position change on new verified evidence ends the debate.
- The role switch is removed and replaced by a steelman gate before every attack.
- Concessions count only when backed by verified evidence or a named logical error. Other position changes are logged as CONFORMITY_FLIP.
- CONVERGENCE is a diagnostic only. URL-level INDEPENDENCE is replaced by origin-level diversity.
- The juror is a non-Claude CLI when one is available, and judges each issue twice with the sides in swapped order.
- The Devil's Advocate is replaced by a premortem that assumes the answer is wrong, followed by an underconfidence check.
- FinalScore is replaced by an evidence-quality checklist and a separate P_final marked UNCALIBRATED.
- CLI participants receive raw search snippets instead of moderator summaries.
- The skill description is rewritten to name its triggers and exclude simple lookups, summaries, translation and coding.

### Added
- Verbatim quotes (50 words or fewer) on every factual claim, checked against the fetched page and classified v / n / u.
- A labeled snippet-level mode when page fetching fails for environmental reasons.
- Blind-draft fields KEY_ASSUMPTIONS and CRUXES, and an issue map built from double cruxes with pre-committed searches.
- A creative-question path without an adversarial loop.
- Output sections for the vote baseline, the strongest opposing case and the source list.
- `evals/` suite for `claude plugin eval` with 24 cases: trigger, misconception accuracy and contested-question checks.

## 2.1.0 (2026-09-29)

### Changed
- Participants run as isolated Claude subagents launched in parallel, so blind drafts are genuinely independent. The Moderator no longer plays any participant.
- Participant roster defined for 0, 1, and 2+ available CLIs; failing CLIs are dropped and replaced.
- Roles (Prosecutor, Defender, Adverse Witness) are assigned per conflict for any number of participants.
- CONVERGENCE and INDEPENDENCE now have explicit formulas instead of moderator estimates.
- End-of-round rules have a fixed evaluation order (consensus, role switch, deadlock, exhaustion).
- FinalScore measures the reliability of the final answer; Accuracy, Evidence, and Independence are defined operationally.
- Retrial never exceeds the 5-round cap; independence retrial falls back to a fresh Adverse Witness when the role switch is already spent; evidence retrial is a search-only pass.
- Web search works with the built-in `WebSearch` tool or Brave Search MCP.
- Skill frontmatter follows the Agent Skills spec (`name`, `description`, `license`, `metadata`).
- Temperature is applied only where a CLI supports it; role stance is set through the prompt.

### Added
- CLI invocation templates using quoted heredocs and temporary files.
- Search delegation protocol for CLI participants.
- Session cap of 25 web searches with handling for rate limits.
- Shortcut exit for factual questions settled by the initial fact base.
- `.claude-plugin/marketplace.json` for installing directly from this repository.
- `LICENSE` and this changelog.

### Removed
- `gh copilot` from CLI detection.

## 2.0.0 (2026-04-04)

- Prime Directive against sycophancy.
- Blind draft protocol.
- Prosecutor / Defender / Adverse Witness roles and a conditional role switch.
- Devil's Advocate, optional 3-member jury, FinalScore, and automatic retrial.

## 1.0.0 (2026-03-17)

- Initial release: web-search-grounded multi-agent debate with up to 5 rounds.
