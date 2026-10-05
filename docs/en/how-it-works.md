# How it works

## Phases

| Phase | What happens |
|-------|--------------|
| 0. Plan | Classify the question, set stakes and the reference date, build the roster |
| 0.5 Materials | Read the files, directories, URLs or text the user supplied; summaries and key passages go to every participant |
| 1. Fact base | Three searches from different angles (for, against, current state); key facts are kept with URL and quote |
| 2. Blind drafts | Each participant writes a position, claims with URL and quote, key assumptions, cruxes and a probability, without seeing the others |
| 2a. Baseline | Family-weighted vote and pooled probability `P0` |
| 2b. Issue map | Pairs of conflicting claims that decide the answer. Value disagreements go to conditional answers instead of debate |
| 3. Rounds | Per issue: a prosecutor attacks, an adverse witness tests a shared assumption, the defender answers. 1 round by default, 3 at most |
| 4. Verdict | Juror rulings in both orders, verdict engine, override rule, premortem, checklist, report |

Rounds stop early when an issue is settled or when a round changes no position on new verified evidence.

## Rules for participants

- Participants see each other only as anonymous labels. Model names and probabilities stay hidden.
- Before attacking, the prosecutor restates the defender's claim in at most three sentences. If the defender says it was distorted, the attack is void.
- A position may change only because of verified evidence or a named logical error. Any other change is logged as `CONFORMITY_FLIP` and does not count.
- With a single model family and a unanimous draft, a dissenter searches for the strongest counter-evidence before the debate is skipped.

## Quote checks

Every quote is fetched from its URL and compared with the page text.

- Only display differences are ignored: whitespace, Unicode compatibility forms, quote marks, dash and minus variants, letter case and Markdown.
- Signs, numbers, units, negations and comparison words are compared exactly.
- A verbatim quote whose sentence holds a condition the quote leaves out ("if", "unless", "only", "except", "경우", "-면") is marked `n`.
- If pages cannot be fetched, a quote counts at snippet level only when the returned search snippet contains it word for word.

Support is judged separately: does this quote, in its context, back this claim fully, partly, not at all, or is that unclear (`full`, `partial`, `none`, `unknown`)?

## Evidence weight

A piece of evidence counts only if its quote is `v` or `snippet`, its support is `full` or `partial`, and its source is not superseded. Its weight is the product of four factors:

| Factor | Values |
|--------|--------|
| Source reliability | high 0.9, medium 0.6, low 0.3 |
| Quote check | v 1.0, snippet 0.5, n 0, u 0 |
| Support | full 1.0, partial 0.5, none 0, unknown 0 |
| Freshness | fresh 1.0, not time-bound 1.0, unknown 0.75, stale 0.5, superseded 0 |

Copies of the same story count once: evidence is grouped by its original source (the same press release, paper or wire story), and only the best item of each group counts. A claim's base score combines a prior of 0.2 with its groups by noisy-OR, so weak evidence never scores below no evidence.

## Verdict engine

1. Each attack becomes a defeat unless the target's base score exceeds the attacker's by more than 0.15. An undercut (an attack on the reasoning) backed by eligible evidence always defeats. An undercut without such evidence is treated like any other attack.
2. Grounded semantics labels every claim accepted, rejected or undecided. Repeated relations count once.
3. Preferred extensions describe the coherent sides of an undecided conflict; they become the branches of a conditional answer.
4. Damped DF-QuAD gives each claim a strength. A claim is `ACCEPTED` when its strength reaches 0.5 (0.7 for high stakes).

Each conflict gets one verdict:

| Verdict | Meaning |
|---------|---------|
| `A_WINS`, `B_WINS` | One side accepted, the other not |
| `PARTIAL_BOTH_SURVIVE` | Both sides accepted |
| `CONDITIONAL` | Undecided, and each side belongs to a coherent position |
| `VALUE_CONDITIONAL` | The conflict turns on values, not facts |
| `LOSER_REFUTED_WINNER_UNPROVEN` | One side refuted, the other not proven |
| `UNRESOLVED`, `NEITHER_ESTABLISHED` | No verdict possible |

The same input always gives the same output, and the result carries a hash of the input.

## Override rule

The final answer departs from the vote baseline only when all three hold:

1. The minority's key quote is verified.
2. The majority's rebuttal fails.
3. A juror agrees in both orders of presentation. The juror is an agent from another model family when one is available; otherwise a fresh juror on the host's own model, labeled same-family.

## Probabilities

`P0` is the log-odds mean of the drafters' probabilities, with each model family weighted as one voter. With three or more positions, a drafter's `1 - p` is split evenly over the other positions. `P_final` keeps `P0` unless the answer was overridden. Neither is calibrated.

## Enforcement

With the plugin installed, hooks enforce these rules while a run is open:

- 25 searches and 15 page fetches per run
- no page fetches after the run switches to snippet-level checking
- no messages between participants during blind drafts
- one repair request for a malformed participant turn

The run controller refuses illegal phase changes and extra rounds.
