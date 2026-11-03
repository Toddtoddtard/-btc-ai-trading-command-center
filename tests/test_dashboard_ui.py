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


def test_technical_cards_escape_feed_values_without_script_modules():
    from dashboard_ui import metric_cards_html
    html = metric_cards_html([('Technical AI', '<script>alert(1)</script>'),
                              ('MACD histogram', '+1.25'), ('Missing', None)])
    assert '<script' not in html.lower()
    assert '&lt;script&gt;' in html
    assert '+1.25' in html and 'Unavailable' in html
    assert 'Technical AI' in html and 'grid-template-columns' in html
