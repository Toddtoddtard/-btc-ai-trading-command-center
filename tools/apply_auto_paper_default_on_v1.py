from pathlib import Path

p = Path("app.py")
s = p.read_text(encoding="utf-8")

# New databases should begin with automatic PAPER trading enabled.
s = s.replace(
    "enabled INTEGER NOT NULL DEFAULT 0,",
    "enabled INTEGER NOT NULL DEFAULT 1,",
    1,
)
s = s.replace(
    "VALUES(1,0,'NONE',NULL,NULL,NULL,NULL,NULL,0,'Auto paper trading ready.')",
    "VALUES(1,1,'NONE',NULL,NULL,NULL,NULL,NULL,0,'AUTO PAPER TRADING enabled by default.')",
    1,
)

old = '''db_auto_state = get_auto_state()
if "auto_paper_enabled" not in st.session_state:
    st.session_state.auto_paper_enabled = bool(db_auto_state["enabled"])
auto_paper_enabled = st.sidebar.toggle('''
new = '''db_auto_state = get_auto_state()
if "auto_paper_enabled" not in st.session_state:
    # Every newly loaded browser session starts AUTO PAPER ON by default.
    # The toggle remains fully user-controlled after load, so it can still be
    # switched OFF at any time. This changes PAPER simulation only.
    st.session_state.auto_paper_enabled = True
auto_paper_enabled = st.sidebar.toggle('''

if old not in s:
    if 'st.session_state.auto_paper_enabled = True' in s:
        print("AUTO PAPER default-on behavior already installed")
        raise SystemExit(0)
    raise SystemExit("AUTO PAPER session anchor not found")

s = s.replace(old, new, 1)
p.write_text(s, encoding="utf-8")
print("Installed AUTO PAPER default ON behavior")
