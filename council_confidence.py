"""Bounded council-confidence corrections from independent official outcomes.

This estimates correctness of the council's own side, never a contract fair
price. Frozen formula confidence keeps successive fits from learning their own
previous correction. Validation predictions use only labels already observed.
"""
import math

from outcome_timing import outcome_available_at, timestamp

BASIS = 'official_council_confidence_bands_v1'
MIN_TRAIN = 100
MIN_VALIDATION = 100
MIN_BAND = 30
PRIOR = 20
MAX_CORRECTION = .15


def for_direction(confidence, base_score, direction):
    """Reliability belongs to a side; an opposite call gets its complement."""
    if abs(base_score) <= .03 or direction not in ('UP', 'DOWN'):
        return .5
    return confidence if (base_score > 0) == (direction == 'UP') else 1-confidence


def _band(confidence):
    return str(min(9, max(4, int(confidence*10))))


def _correction(bands, confidence):
    band = bands.get(_band(confidence), {})
    n = band.get('samples', 0)
    if n < MIN_BAND:
        return 0.
    return max(-MAX_CORRECTION, min(MAX_CORRECTION, band['residual_sum']/(n+PRIOR)))


def apply(confidence, state):
    model = (state or {}).get('council_confidence_calibration') or {}
    if not isinstance(model, dict) or model.get('basis') != BASIS or model.get('active') is not True:
        return confidence
    bands = model.get('bands')
    band = bands.get(_band(confidence)) if isinstance(bands, dict) else None
    if not isinstance(band, dict) or band.get('validated') is not True:
        return confidence
    try:
        if not (math.isfinite(band['samples']) and band['samples'] >= MIN_BAND
                and math.isfinite(band['residual_sum'])):
            return confidence
        correction = _correction(bands, confidence)
    except (KeyError, TypeError, ValueError):
        return confidence
    return min(.95, max(.40, confidence+correction))


def fit(records, as_of=None):
    rows = []
    for record, outcome in records:
        snap = record['snapshot']
        opened, expiry = timestamp(record.get('opened_at')), timestamp(record.get('expires_at'))
        score = timestamp(snap.get('master_base_score'))
        baseline = timestamp(snap.get('council_formula_confidence', snap.get('master_confidence')))
        available = outcome_available_at(outcome, expiry)
        if (opened is None or expiry is None or not opened < expiry
                or score is None or abs(score) <= .03 or baseline is None
                or not .4 <= baseline <= .95 or not math.isfinite(available)
                or (as_of is not None and available > as_of)):
            continue
        hit = int((score > 0) == (outcome['kalshi_result'] == 'yes'))
        rows.append(dict(opened=opened, available=available, baseline=baseline, hit=hit))
    rows.sort(key=lambda r: r['opened'])
    labels = sorted(rows, key=lambda r: r['available'])
    bands, cursor, losses, band_losses = {}, 0, [], {}

    def add(row):
        band = bands.setdefault(_band(row['baseline']), dict(samples=0, residual_sum=0.))
        band['samples'] += 1
        band['residual_sum'] += row['hit']-row['baseline']

    for row in rows:
        while cursor < len(labels) and labels[cursor]['available'] <= row['opened']:
            add(labels[cursor])
            cursor += 1
        if cursor >= MIN_TRAIN:
            p = min(.95, max(.4, row['baseline']+_correction(bands, row['baseline'])))
            loss = ((p-row['hit'])**2, (row['baseline']-row['hit'])**2)
            losses.append(loss)
            key = _band(row['baseline'])
            if bands.get(key, {}).get('samples', 0) >= MIN_BAND:
                band_losses.setdefault(key, []).append(loss)
    while cursor < len(labels):
        add(labels[cursor])
        cursor += 1

    def metrics(losses):
        n = len(losses)
        return dict(samples=n,
                    candidate_brier=sum(r[0] for r in losses)/n if n else None,
                    formula_brier=sum(r[1] for r in losses)/n if n else None,
                    brier_improvement=sum(r[1]-r[0] for r in losses)/n if n else None)

    validation, recent = metrics(losses), metrics(losses[-100:])
    for key, band in bands.items():
        evidence = band_losses.get(key, [])
        band['validation'] = metrics(evidence)
        band['recent_validation'] = metrics(evidence[-100:])
        band['validated'] = bool(len(evidence) >= MIN_BAND
                                 and band['validation']['brier_improvement'] >= .002
                                 and band['recent_validation']['brier_improvement'] >= 0)
    active = bool(len(losses) >= MIN_VALIDATION
                  and validation['brier_improvement'] >= .002
                  and recent['brier_improvement'] >= 0
                  and any(b['validated'] for b in bands.values()))
    return dict(basis=BASIS, active=active, training_markets=len(rows), bands=bands,
                validation=validation, recent_validation=recent,
                max_correction=MAX_CORRECTION, scope='council side correctness; not contract value',
                reason='Chronological confidence improvement passed' if active else
                'Confidence correction unproven; formula retained')
