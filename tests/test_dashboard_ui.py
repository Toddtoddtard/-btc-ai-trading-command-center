from dashboard_ui import directional_badge_html, fmt_money, fmt_pct


def test_formatters_keep_existing_display_contract():
    assert fmt_money(1234.5) == "$1,234.50"
    assert fmt_pct(-2.345, digits=1) == "-2.3%"
    assert fmt_money(float("nan")) == "N/A"


def test_direction_badges_keep_up_down_and_hold_semantics():
    assert "call-up" in directional_badge_html("LOCK UP")
    assert "call-down" in directional_badge_html("SCALP DOWN")
    assert "call-neutral" in directional_badge_html("HOLD")
    assert "compact" in directional_badge_html("UP", compact=True)
