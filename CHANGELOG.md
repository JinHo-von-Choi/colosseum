# Changelog

## 3.2.0-beta.1 (2026-10-05)

Stabilization release following the 2026-10-05 improvement plan (PR 00 to 05 and PR 07). The product focus narrows to technical decision review; forecast, diagnose and ideate stay experimental.

### Fixed
- Quote reversals were accepted as checked. The matcher (`quote-match/2`) now matches a contiguous span of the page and normalizes only display differences (whitespace, Unicode compatibility forms, quote marks, dash and minus variants, case, Markdown). Signs, numbers, units, negations and comparisons are kept, so a removed "not", -5.2% quoted as 5.2% or +5.2%, and "more than" quoted as "less than" are `u`. A verbatim quote that drops a condition from its sentence ("if ...", "...경우") is `n`.
- `n` now means "review required" and carries no weight. One eligibility rule (`v` or `snippet`, support full or partial, not superseded) drives scores, the undercut exception and the checklist (`evidence-policy/2`).
- A support assessment made for one claim was reused for every other claim citing the same quote. Page acquisition, quote checks and support assessments now have separate caches; support is keyed by claim id, claim text hash, quote, context hash and policy version.
- A search result marked `in_snippet` counted as verified even when its text did not contain the quote. Snippet level now requires the returned snippet text to contain the quote verbatim, and every evidence item records `full_page`, `snippet` or `unavailable`; the report counts them instead of naming one global mode.
- Two issues in one round produced the same claim ids, and defender rebuttals attached to the other issue's prosecutor claims. Claim ids now carry round, issue, role, participant and ordinal, and the fields are also stored on each claim.
- `start` reset only the state file, so a new question could read the previous run's drafts and graph. Every run now lives in `sessions/<session>/runs/<run_id>/`, default inputs come from the current run only, and a closed run is read only with `--run`.
- Concurrent forecast writes could be lost. The forecast log is now a sqlite store with unique forecast and event ids and one transaction per add or resolve; retries are idempotent and conflicting outcomes are errors.
- Forecast scores were computed on clipped and extremized values. Brier and log loss now use the stored `p_final`; calibration bins are half-open with a closed last bin.
- Delphi's "new evidence" check depended on participant order. The seen set is fixed at the start of each round and updated after all submissions.
- With three or more positions, P0 read a drafter's 1 - p as the probability of the target position. The complement is now split over the other positions, and `p0_method` says which rule was used.
- A prompt containing the heredoc terminator could escape the CLI template. CLIs now run through `scripts/relay.py` with a fixed argument list and the prompt on stdin.
- `install.sh` replaced links it did not create. It now stops on any existing file, directory, other link or broken link.
- Repeated relations lowered strengths; relations are now deduplicated. JavaScript validation now matches Python for numeric ids, empty status, unknown kinds and schema versions; URL hosts are compared in IDNA form in both languages.

### Added
- Run lifecycle: `resume` (from the checkpoint, optionally checked against the question hash), `restart`, `cancel`, `fail`, `runs`; statuses completed, failed, cancelled, interrupted; checkpoints of another version are refused. Budgets and the round cap are validated at start; negative round results are refused.
- `adr`: a decision record (Markdown ADR and JSON, `colosseum.decision/v1`) rendered only from structured results: recommendation and conditions, up to three decisive evidence items, the strongest open counter-argument, next checks, baseline versus final, sensitivity to small changes of the defeat margin and proof standard, limits and versions. The status is left to the person deciding.
- `whatif`: recompute the verdicts with one evidence item excluded or one claim unproven, without model calls, listing changed and unchanged verdicts and the relation path of each change.
- `forecast import | export | status` and `--event-id` for retries.
- `references/contract.md`: the source, quote, claim, assessment and run records and every version string.
- Tests: P0 reproductions paired with controls, a Node harness that runs whole workflows with a scripted `agent()`, full-output Python/JavaScript parity, relation and order invariance, an independent check of all 4,096 four-node graphs, relay byte preservation and timeout cleanup, audit-log redaction with synthetic secrets, installer conflicts, concurrent and crashing forecast writers. CI installs Node and fails instead of skipping the JavaScript checks when it is missing.

### Changed
- The source log keeps an event id, tool, success, latency when reported, redacted URLs and hashes. Raw text is kept only with `COLOSSEUM_DEBUG_LOG=1`, still redacted. Directories are 0700 and files 0600 on POSIX; without `fcntl` the scripts refuse to open a run.
- External CLIs are not added just because they are installed; the run plan names the providers first.
- forecast, diagnose and ideate are marked experimental in their metadata, reports and the skill.
- The README no longer advertises the official plugin directory until the listing is confirmed, and states the differences between plugin and manual installs and the tested platform (Linux).

### Not yet verified
- End-to-end runs on a real Claude Code host for the ten scenarios in the plan (PR 06): install, blind drafts, two issues with the same pair, single and total fetch failure, two malformed outputs, CLI timeout, damaged hook state, user cancel, resume, and restart with a new question. The harness tests replace `agent()` and do not prove host behavior.
- Comparison against a single strong model, a plain vote and claim-level verification at matched cost (PR 08).

## 3.1.0-beta.1 (2026-09-30)

### Added
- Question-type routing in the skill: factual and technical, decision, normative, forecast, estimate, diagnostic and creative questions each get their own procedure (`references/modes.md`).
- `colosseum:forecast` workflow: base rates, a published-forecast scan, blind first estimates, Delphi rounds with anonymous median and range feedback, revisions over 10 points capped unless backed by new checked evidence, family-weighted log-odds pooling, a 50/50 blend with a checked published forecast, premortem, and a forecast record.
- `colosseum:diagnose` workflow: blind hypotheses, consolidation with a catch-all hypothesis, a consistency matrix that drops non-diagnostic evidence, inconsistency scores used for explanation only, and pooled probability distributions.
- `colosseum:ideate` workflow: silent parallel generation, merging with sources kept, blind rankings and a Borda count.
- Decision mode (an antithesis plan built on the negated key assumptions, with switch signals) and normative mode (value premises become a conditional map) in `colosseum:debate`.
- Forecast log with `colosseum.py forecast add | resolve | list | score | fit`: Brier score, log loss, calibration bins, and an extremizing factor fitted by log loss once 20 forecasts have resolved.
- `scripts/modes.py` with the aggregation rules, ported into the shared workflow library and checked for parity.
- `tools/sync_workflow_blocks.py` keeps the shared library and runtime blocks identical across workflows; a test fails on drift.

### Verified
- Real runs of all three new workflows through the skill's routing: a creative question (15 ideas merged to 13, unanimous Borda winner), a probability forecast (Delphi stable after one revision round, record written to the log), and a diagnostic question (two hypotheses plus a catch-all, pooled probabilities).

### Not yet verified
- Whether each mode beats the plain debate procedure on its own kind of question (roadmap stage 4 gate).
- Calibration fitting on real resolved forecasts (the log has none yet).

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
