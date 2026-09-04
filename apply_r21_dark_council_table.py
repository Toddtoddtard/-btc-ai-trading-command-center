from pathlib import Path

p = Path('app.py')
s = p.read_text()

old = '        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)\n'
new = '''        council_df = pd.DataFrame(rows)\n        if dark_mode:\n            # Streamlit's native dataframe canvas stays light even when our custom\n            # dashboard dark-mode toggle is enabled, so render the council table\n            # as a responsive HTML table in dark mode. Light mode keeps the native table.\n            table_html = council_df.to_html(index=False, border=0, classes="ai-council-table")\n            st.markdown(\n                """\n                <style>\n                .ai-council-wrap {\n                    width: 100%; overflow-x: auto; border: 1px solid #263447;\n                    border-radius: 12px; background: #0b1220;\n                }\n                .ai-council-table {\n                    width: 100%; border-collapse: collapse; color: #e8eef8;\n                    background: #0b1220; font-size: 0.93rem; margin: 0;\n                }\n                .ai-council-table thead th {\n                    position: sticky; top: 0; z-index: 1; text-align: left;\n                    color: #b8cff7; background: #111c2e; font-weight: 700;\n                    border-bottom: 1px solid #2b3b52; padding: 10px 12px;\n                    white-space: nowrap;\n                }\n                .ai-council-table tbody td {\n                    color: #e7edf7; background: #0b1220;\n                    border-bottom: 1px solid #1e2b3d; padding: 9px 12px;\n                    vertical-align: middle; white-space: nowrap;\n                }\n                .ai-council-table tbody tr:nth-child(even) td {background: #0f1828;}\n                .ai-council-table tbody tr:hover td {background: #15243a;}\n                .ai-council-table td:last-child {white-space: normal; min-width: 260px;}\n                </style>\n                """,\n                unsafe_allow_html=True,\n            )\n            st.markdown(\n                f'<div class="ai-council-wrap">{table_html}</div>',\n                unsafe_allow_html=True,\n            )\n        else:\n            st.dataframe(council_df, use_container_width=True, hide_index=True)\n'''

if old not in s:
    raise SystemExit('AI Council dataframe insertion point not found')

s = s.replace(old, new, 1)
s = s.replace('APP_VERSION = "2026.09.04-single-file-r20-friendly-ai-council"',
              'APP_VERSION = "2026.09.04-single-file-r21-dark-council-table"', 1)

compile(s, 'app.py', 'exec')
p.write_text(s)
print('R21 dark-mode AI Council table patch applied successfully')
