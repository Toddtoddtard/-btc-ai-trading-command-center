"""Paired evidence and bounded, observation-driven contribution updates."""
import math

MIN_ACTIVE_MARKETS = 100
MIN_DISCORDANT_PAIRS = 10
FAMILY_ERROR_RATE = .05
REQUIRED_STREAK = 3


def paired_evidence(saves, harms, active_markets, comparisons):
    n, k = saves + harms, min(saves, harms)
    # Exact two-sided paired sign/binomial test. Correct for the whole ranked
    # family rather than searching fourteen bots for a lucky 90% z-score.
    p = min(1., 2*sum(math.comb(n, i) for i in range(k+1))/2**n) if n else 1.
    threshold = FAMILY_ERROR_RATE / max(1, comparisons)
    passed = active_markets >= MIN_ACTIVE_MARKETS and n >= MIN_DISCORDANT_PAIRS and p <= threshold
    return {'discordant_pairs': n, 'paired_p_value': p, 'family_p_threshold': threshold,
            'evidence_passed': passed}


def stable_update(row, previous, evidence_key):
    previous = previous or {}
    key = str(evidence_key)
    compatible = previous.get('candidate_verdict') == row['candidate_verdict']
    if not row['evidence_passed']:
        return {'evidence_streak': 0, 'stable_multiplier': 1., 'evidence_key': key}
    same = previous.get('evidence_key') == key and compatible
    streak = int(previous.get('evidence_streak', 0)) if same else (
        int(previous.get('evidence_streak', 0))+1 if compatible else 1)
    old = float(previous.get('stable_multiplier', 1.))
    target = max(.4, min(1.3, 1+2*row['contribution_score']))
    value = old if same else old + max(-.05, min(.05, .25*(target-old)))
    return {'evidence_streak': streak, 'stable_multiplier': value if streak >= REQUIRED_STREAK else 1.,
            'evidence_key': key}
