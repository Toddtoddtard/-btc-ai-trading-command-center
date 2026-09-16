import pytest

from pro_trade_ticket import build_pro_trade_ticket


def _decision(action="SCALP UP", **updates):
    decision = {
        "action": action,
        "yes_bid_dollars": 0.49,
        "yes_ask_dollars": 0.50,
        "no_bid_dollars": 0.50,
        "no_ask_dollars": 0.51,
        "scalp_projected_exit_price": 0.65,
    }
    decision.update(updates)
    return decision


def test_scalp_ticket_discloses_complete_fee_aware_economics():
    ticket = build_pro_trade_ticket(
        _decision(),
        {"approved": True, "position_pct": 0.08},
        {"cash": 500.0},
    )

    assert ticket["status"] == "READY"
    assert ticket["direction"] == "UP"
    assert ticket["allocation_pct"] == pytest.approx(0.02)
    assert ticket["contracts"] == 19
    assert ticket["entry_fee"] == pytest.approx(0.34)
    assert ticket["total_cost"] == pytest.approx(9.84)
    assert ticket["break_even_price"] == pytest.approx(0.54)
    assert ticket["take_profit_price"] == pytest.approx(0.525)
    assert ticket["emergency_stop_price"] == pytest.approx(0.35)
    assert ticket["projected_net_pnl"] > 0


def test_down_ticket_uses_no_side_quote():
    ticket = build_pro_trade_ticket(
        _decision("SCALP DOWN"),
        {"approved": True, "position_pct": 0.02},
        {"cash": 500.0},
    )

    assert ticket["side"] == "NO"
    assert ticket["entry_price"] == pytest.approx(0.51)
    assert ticket["current_bid"] == pytest.approx(0.50)


def test_hold_ticket_never_pretends_an_order_is_ready():
    ticket = build_pro_trade_ticket(
        _decision("HOLD"),
        {"approved": False, "position_pct": 0.0},
        {"cash": 500.0},
    )

    assert ticket["status"] == "WAIT"
    assert ticket["contracts"] == 0
    assert ticket["entry_price"] is None
    assert "waiting for a qualified call" in ticket["blockers"][0]


def test_lock_preview_is_settlement_based_and_not_risk_gate_labeled():
    ticket = build_pro_trade_ticket(
        _decision("LOCK UP", yes_ask_dollars=0.72),
        {"approved": False, "position_pct": 0.02},
        {"cash": 500.0},
    )

    assert ticket["status"] == "READY"
    assert ticket["projected_exit_price"] == 1.0
    assert ticket["take_profit_price"] is None
    assert "official Kalshi settlement" in ticket["protection"]


def test_open_position_blocks_an_additional_ticket():
    ticket = build_pro_trade_ticket(
        _decision(),
        {"approved": True, "position_pct": 0.02},
        {"cash": 500.0},
        has_open_position=True,
    )

    assert ticket["status"] == "WAIT"
    assert "one paper position is already open" in ticket["blockers"]
