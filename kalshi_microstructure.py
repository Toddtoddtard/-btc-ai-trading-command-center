"""Pure helpers for public Kalshi binary-market order-book features."""

from __future__ import annotations

import math


def _finite(value, default=None):
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except Exception:
        return default


def _levels(payload, side):
    book = (payload or {}).get("orderbook_fp") or (payload or {}).get("orderbook") or {}
    raw = book.get(f"{side}_dollars") or book.get(side) or []
    levels = []
    for row in raw:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        price = _finite(row[0])
        quantity = _finite(row[1], 0.0)
        if price is None or quantity <= 0:
            continue
        if price > 1.0:
            price /= 100.0
        if 0.0 <= price <= 1.0:
            levels.append((price, quantity))
    return sorted(levels, key=lambda item: item[0], reverse=True)


def orderbook_features(payload, depth=5):
    """Return executable quotes, spread, depth imbalance and microprice."""
    yes = _levels(payload, "yes")
    no = _levels(payload, "no")
    yes_bid = yes[0][0] if yes else None
    no_bid = no[0][0] if no else None
    yes_ask = 1.0 - no_bid if no_bid is not None else None
    no_ask = 1.0 - yes_bid if yes_bid is not None else None
    midpoint = (
        (yes_bid + yes_ask) / 2.0
        if yes_bid is not None and yes_ask is not None else None
    )
    spread = (
        max(0.0, yes_ask - yes_bid)
        if yes_bid is not None and yes_ask is not None else None
    )
    yes_depth = sum(quantity for _, quantity in yes[:depth])
    no_depth = sum(quantity for _, quantity in no[:depth])
    total_depth = yes_depth + no_depth
    depth_imbalance = (
        (yes_depth - no_depth) / total_depth if total_depth else 0.0
    )
    best_yes_size = yes[0][1] if yes else 0.0
    best_no_size = no[0][1] if no else 0.0
    best_total = best_yes_size + best_no_size
    microprice = midpoint
    if yes_bid is not None and yes_ask is not None and best_total:
        microprice = (
            yes_ask * best_yes_size + yes_bid * best_no_size
        ) / best_total
    top_imbalance = (
        (best_yes_size - best_no_size) / best_total if best_total else 0.0
    )
    weighted_yes = sum(quantity / (index + 1.0) for index, (_, quantity) in enumerate(yes[:depth]))
    weighted_no = sum(quantity / (index + 1.0) for index, (_, quantity) in enumerate(no[:depth]))
    weighted_total = weighted_yes + weighted_no
    weighted_depth_imbalance = (
        (weighted_yes - weighted_no) / weighted_total if weighted_total else 0.0
    )
    depth_concentration = (
        best_total / total_depth if total_depth else 0.0
    )
    return {
        "yes_bid": yes_bid,
        "yes_ask": yes_ask,
        "no_bid": no_bid,
        "no_ask": no_ask,
        "midpoint": midpoint,
        "spread": spread,
        "yes_depth_top5": yes_depth,
        "no_depth_top5": no_depth,
        "depth_imbalance": depth_imbalance,
        "top_level_imbalance": top_imbalance,
        "weighted_depth_imbalance": weighted_depth_imbalance,
        "depth_concentration": depth_concentration,
        "microprice": microprice,
        "microprice_edge": (
            microprice - midpoint
            if microprice is not None and midpoint is not None else 0.0
        ),
        # A YES ask consumes the best NO bid, and vice versa, in a binary book.
        "yes_bid_size": best_yes_size,
        "yes_ask_size": best_no_size,
        "no_bid_size": best_no_size,
        "no_ask_size": best_yes_size,
        "levels": len(yes) + len(no),
        "available": bool(yes or no),
    }
