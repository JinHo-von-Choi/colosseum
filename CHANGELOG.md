# Changelog

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
