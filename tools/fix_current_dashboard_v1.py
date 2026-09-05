from pathlib import Path

p = Path("app.py")
s = p.read_text(encoding="utf-8")
original = s

old = '''                journal_view = journal_df.copy()
                _journal_actions = journal_view["action"].astype(str).str.upper().str.strip()
                _journal_resolved = pd.to_numeric(journal_view["resolved"], errors="coerce").fillna(0).astype(int)
                journal_view.loc[_journal_actions.isin(["HOLD", "WAIT"]), "correct"] = "NO TRADE"
                journal_view.loc[_journal_resolved != 1, "correct"] = "OPEN"'''
new = '''                journal_view = journal_df.copy()
                _journal_actions = journal_view["action"].astype(str).str.upper().str.strip()
                _journal_resolved = pd.to_numeric(journal_view["resolved"], errors="coerce").fillna(0).astype(int)
                # Keep database/analytics correctness numeric. Only the dark-mode
                # display copy becomes object dtype so pandas can safely render
                # textual states such as NO TRADE and OPEN.
                journal_view["correct"] = journal_view["correct"].astype(object)
                journal_view.loc[_journal_actions.isin(["HOLD", "WAIT"]), "correct"] = "NO TRADE"
                journal_view.loc[_journal_resolved != 1, "correct"] = "OPEN"'''

if old not in s:
    raise SystemExit("journal display anchor not found")
s = s.replace(old, new, 1)

p.write_text(s, encoding="utf-8")
print("Fixed prediction journal display dtype crash")
