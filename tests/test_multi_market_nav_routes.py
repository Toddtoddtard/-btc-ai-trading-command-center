from pathlib import Path


def test_market_page_files_exist():
    root = Path(__file__).resolve().parents[1]
    expected = [
        root / "pages" / "Gold_Command_Center.py",
        root / "pages" / "Gas_Prices_Command_Center.py",
        root / "pages" / "ZEC_Command_Center.py",
        root / "pages" / "WTI_Oil_Command_Center.py",
    ]
    missing = [str(path) for path in expected if not path.exists()]
    assert not missing, f"Missing Streamlit pages: {missing}"


def test_nav_uses_browser_routes_not_streamlit_page_validation():
    root = Path(__file__).resolve().parents[1]
    source = (root / "multi_market_nav.py").read_text(encoding="utf-8")
    assert "st.switch_page" not in source
    assert "st.page_link" not in source
    for route in [
        '"href": "/"',
        '"href": "/Gold_Command_Center"',
        '"href": "/Gas_Prices_Command_Center"',
        '"href": "/ZEC_Command_Center"',
        '"href": "/WTI_Oil_Command_Center"',
    ]:
        assert route in source
