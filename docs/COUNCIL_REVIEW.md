# Council evidence review — 2026-10-12

This follow-up incorporates the user's Claude review after PR #71.

1. Council contribution now scores the gated council action, including the
   knowledge safety veto. WAIT never counts as a losing trade. Only paired
   decisions support a contribution multiplier. Correct calls have decision
   utility +1, wrong calls -1, and WAIT zero; changes involving abstention and
   opposite-direction flips have separate counts. This is a decision-quality
   comparison, not fee-aware trade profit. The report identifies a council subdecision,
   not actual Master execution. Master adds strike geometry, contract probability,
   quotes, timing, and one-way LOCK state. Old snapshots cannot reproduce those
   complete trade decisions, so their accuracy is not asserted here.
2. New official result records save when the learner observed settlement.
   Council and terminal replay exclude outcomes not yet observed at capture.
   Older rows without that timestamp assume expiry plus 120 seconds. This is an
   explicit legacy timing assumption, not recovered proof of historical poll time.
3. Contribution evidence uses an exact two-sided paired decision sign test,
   family-wise 5% threshold divided by the number of compared specialists,
   at least ten discordant pairs, and at least 100 active markets. Influence
   requires evidence to persist across three distinct newly observed active
   markets. Repeated polls of unchanged evidence cannot advance the streak or
   move weights. Changes use a bounded EMA step of at most 0.05 per observation.
4. Quiet specialists are scored only when their adjusted vote participates.
   A lack of observed contribution is labeled LEARNING; it cannot establish
   redundancy. Existing rare-event specialists remain available.
5. Unanimity among a lone voter cannot earn the full confidence bonus. The
   bonus scales with effective voter count, reaching full strength with three
   comparably weighted voters. This measures vote coverage, not statistical
   independence of correlated technical indicators. Inactive bots do not dilute
   the vote or coverage denominator.
6. Standalone metrics use the adjusted votes the council actually receives,
   including adjustments across the abstention threshold. Positive reliability
   multipliers preserve sign; they can still turn a weak vote into abstention.
   These scores compare specialist votes with official settlement, not BTC
   movement from the original price. Those are different forecast questions.
7. This is a controlled ablation without the contribution multiplier in both
   arms, not a replay of that feedback layer. Confidence, specialist reliability,
   regime, and WAIT policy are reconstructed from earlier official evidence.
   The report and dashboard now state that scope. No trade-profit improvement
   is inferred from council accuracy.

Additional corrections: event status matching is case-insensitive, political
event weight is explicit at its unchanged previous fallback value of 0.75,
removed voters are omitted from feed-health checks, imports are outside the
replay loop, and the unused ticker variable was removed. The dashboard does not
announce an unqualified top contributor.

The replay still rebuilds historical state per snapshot. Retention is capped at
500 snapshots, so this follow-up addresses evidence correctness first. An
incremental rewrite remains an optimization, not a completed change. Existing
specialist priors, account balances, position limits, and LOCK semantics are
preserved. New contribution multipliers remain neutral until the new evidence
and stability requirements qualify them.
