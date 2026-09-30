# Changelog

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
