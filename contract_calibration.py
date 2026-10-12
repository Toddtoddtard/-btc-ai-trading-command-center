"""Official-outcome, window-independent calibration of terminal probabilities.

One captured observation per market earns one vote. Each validation forecast
uses only markets that expired before it was captured. Unproven corrections
fall back to the contemporaneous Kalshi midpoint, without inventing an edge.
"""
import math

BASIS = "official_kalshi_terminal_probability_v1"
MIN_TRAIN = 100
MIN_VALIDATION = 100
LOOKBACK = 500
MIN_BRIER_EDGE = 0.002


def finite(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def observations(history):
    rows = []
    for row in history or []:
        market = finite(row.get("market_yes_probability"))
        raw = finite(row.get("raw_contract_probability_up"))
        if raw is None:
            # Older captures used this exact, unchanged terminal blend.
            raw = finite(row.get("contract_probability_up"))
        opened, expires = finite(row.get("opened_at")), finite(row.get("expires_at"))
        ticker = str(row.get("ticker") or "")
        if (not ticker or market is None or raw is None or opened is None
                or expires is None or opened >= expires
                or not 0 <= market <= 1 or not 0 <= raw <= 1
                or row.get("result") not in {"yes", "no"}):
            continue
        rows.append({"ticker": ticker, "opened": opened, "expires": expires,
                     "market": market, "raw": raw, "y": int(row["result"] == "yes")})
    unique = {}
    for row in sorted(rows, key=lambda r: (r["opened"], r["ticker"])):
        unique.setdefault(row["ticker"], row)
    return list(unique.values())


def coefficients(rows):
    # Ridge regression of a bounded residual around the executable market.
    a = c = 2.0
    b = d = e = 0.0
    for row in rows[-LOOKBACK:]:
        x, z, y = row["market"] - .5, row["raw"] - row["market"], row["y"] - .5
        a += x*x
        b += x*z
        c += z*z
        d += x*y
        e += z*y
    determinant = a*c-b*b
    return (max(.75, min(1.25, (d*c-e*b)/determinant)),
            max(0., min(1., (a*e-b*d)/determinant)))


def candidate(raw, market, slopes):
    return max(.01, min(.99, .5 + slopes[0]*(market-.5) + slopes[1]*(raw-market)))


def score(rows):
    n = len(rows)
    if not n:
        return {"samples": 0, "brier_edge": None, "accuracy_edge": None}
    return {"samples": n,
            "candidate_brier": sum(r[0] for r in rows)/n,
            "market_brier": sum(r[1] for r in rows)/n,
            "brier_edge": sum(r[1]-r[0] for r in rows)/n,
            "candidate_accuracy": sum(r[2] for r in rows)/n,
            "market_accuracy": sum(r[3] for r in rows)/n,
            "accuracy_edge": sum(r[2]-r[3] for r in rows)/n}


def fit(history, as_of=None):
    rows = observations(history)
    if as_of is not None:
        rows = [r for r in rows if r["expires"] <= float(as_of)]
    validation = []
    for index, row in enumerate(rows):
        prior = [r for r in rows[:index] if r["expires"] <= row["opened"]]
        if len(prior) < MIN_TRAIN:
            continue
        p = candidate(row["raw"], row["market"], coefficients(prior))
        y = row["y"]
        validation.append(((p-y)**2, (row["market"]-y)**2,
                           int((p >= .5) == bool(y)), int((row["market"] >= .5) == bool(y))))
    overall, recent = score(validation), score(validation[-100:])
    active = bool(overall["samples"] >= MIN_VALIDATION
                  and overall["brier_edge"] >= MIN_BRIER_EDGE
                  and overall["accuracy_edge"] >= 0
                  and recent["brier_edge"] >= 0 and recent["accuracy_edge"] >= 0)
    slopes = coefficients(rows)
    return {"version": 1, "basis": BASIS, "active": active,
            "training_markets": len(rows), "validation": overall, "recent_validation": recent,
            "market_slope": slopes[0], "residual_weight": slopes[1],
            "fitted_as_of": as_of, "paper_only": True,
            "reason": "Validated terminal correction" if active else "Terminal correction unproven; Kalshi midpoint fallback"}


def apply(view, state):
    """Keep raw evidence separate from the probability actually used for calls."""
    view = dict(view)
    raw, market = finite(view.get("probability_up")), finite(view.get("market_probability_up"))
    view["raw_probability_up"] = raw
    model = (state or {}).get("contract_calibration", {})
    active = bool(model.get("basis") == BASIS and model.get("active"))
    if raw is not None and market is not None:
        p = candidate(raw, market, (model["market_slope"], model["residual_weight"])) if active else market
        view.update(probability_up=p, edge_vs_market=p-market)
    view["calibrator_active"] = active
    view["probability_basis"] = BASIS if market is not None else "unvalidated_spot_model"
    return view
