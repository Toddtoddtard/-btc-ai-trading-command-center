from pathlib import Path
import re

p = Path('app.py')
s = p.read_text()

if 'single-file-r21-visual-dashboard' in s:
    print('R21 already applied')
    raise SystemExit(0)

pattern = re.compile(
    r'(dark_mode\s*=\s*st\.sidebar\.toggle\(.*?key="dashboard_dark_mode".*?\n\))',
    re.S,
)
m = pattern.search(s)
if not m:
    raise SystemExit('Dark mode toggle block not found')

theme = r'''

# ============================================================
# VISUAL APP SHELL — R21
# Keeps all trading/learning logic intact; changes presentation only.
# ============================================================
if dark_mode:
    st.markdown(
        """
        <style>
        :root {
            --cc-bg:#050b14;
            --cc-panel:#081525;
            --cc-panel2:#0b1a2d;
            --cc-border:#18324f;
            --cc-text:#f4f8ff;
            --cc-muted:#94a8c6;
            --cc-blue:#1687ff;
            --cc-green:#00e6b3;
            --cc-red:#ff4964;
        }

        html, body, [data-testid="stAppViewContainer"], .stApp {
            background: radial-gradient(circle at 65% -10%, #0b213b 0%, #050b14 38%, #030811 100%) !important;
            color: var(--cc-text) !important;
        }
        [data-testid="stHeader"] {background: rgba(3,8,17,.72) !important;}
        [data-testid="stToolbar"] {background: transparent !important;}
        .block-container {max-width: 1500px; padding-top: 1rem !important;}

        /* Sidebar */
        [data-testid="stSidebar"] {
            background: linear-gradient(180deg,#071321 0%,#06101c 100%) !important;
            border-right: 1px solid var(--cc-border) !important;
        }
        [data-testid="stSidebar"] > div:first-child {background: transparent !important;}
        [data-testid="stSidebar"] * {color: var(--cc-text);}
        [data-testid="stSidebar"] h2 {
            font-size: 1.45rem !important;
            letter-spacing: -.02em;
            margin-bottom: .7rem !important;
        }
        [data-testid="stSidebar"] label, [data-testid="stSidebar"] p {color:#d9e5f5 !important;}
        [data-testid="stSidebar"] [data-baseweb="slider"] {padding-top:.15rem;}
        [data-testid="stSidebar"] [role="switch"][aria-checked="true"] {background:var(--cc-blue) !important;}

        /* Tabs as compact navigation */
        [data-testid="stTabs"] [role="tablist"] {
            gap:.35rem !important;
            background:#071322 !important;
            border:1px solid var(--cc-border) !important;
            border-radius:12px !important;
            padding:.35rem !important;
            overflow-x:auto !important;
        }
        [data-testid="stTabs"] [role="tab"] {
            border-radius:8px !important;
            padding:.55rem .78rem !important;
            color:#9fb2ce !important;
            background:transparent !important;
        }
        [data-testid="stTabs"] [role="tab"][aria-selected="true"] {
            background:linear-gradient(180deg,#0f64c7,#0a4fa8) !important;
            color:#fff !important;
            box-shadow:0 0 0 1px rgba(72,159,255,.24) inset !important;
        }
        [data-baseweb="tab-highlight"] {display:none !important;}

        /* Cards / metrics */
        [data-testid="stMetric"] {
            background:linear-gradient(180deg,rgba(11,27,47,.96),rgba(7,20,35,.96)) !important;
            border:1px solid var(--cc-border) !important;
            border-radius:13px !important;
            padding:.85rem 1rem !important;
            box-shadow:0 10px 28px rgba(0,0,0,.18) !important;
        }
        [data-testid="stMetricLabel"] {color:var(--cc-muted) !important;}
        [data-testid="stMetricValue"] {color:var(--cc-text) !important; font-weight:750 !important;}
        [data-testid="stMetricDelta"] {font-weight:650 !important;}

        /* Dataframes/tables */
        [data-testid="stDataFrame"], [data-testid="stTable"] {
            background:#071321 !important;
            border:1px solid var(--cc-border) !important;
            border-radius:13px !important;
            overflow:hidden !important;
            box-shadow:0 10px 28px rgba(0,0,0,.16) !important;
        }
        [data-testid="stDataFrame"] * {color:#dbe7f7 !important;}
        [data-testid="stDataFrame"] canvas {filter:none !important;}

        /* Expanders, forms, inputs */
        [data-testid="stExpander"], [data-testid="stForm"] {
            background:rgba(8,21,37,.95) !important;
            border:1px solid var(--cc-border) !important;
            border-radius:12px !important;
        }
        [data-baseweb="select"] > div,
        [data-baseweb="input"] > div,
        input, textarea {
            background:#081626 !important;
            color:#f4f8ff !important;
            border-color:#274564 !important;
        }

        /* Alerts and banners */
        [data-testid="stAlert"] {
            background:#0a1a2d !important;
            border:1px solid #24466b !important;
            border-radius:12px !important;
            color:#eaf2ff !important;
        }
        .paper-banner {
            background:linear-gradient(90deg,rgba(0,230,179,.12),rgba(22,135,255,.08)) !important;
            border:1px solid rgba(0,230,179,.35) !important;
            color:#dffcf5 !important;
        }

        /* Typography */
        h1,h2,h3,h4 {color:#f7fbff !important; letter-spacing:-.018em;}
        p, li, span {text-rendering:optimizeLegibility;}
        hr {border-color:#17314d !important;}

        /* Buttons */
        .stButton > button, .stDownloadButton > button {
            background:linear-gradient(180deg,#0e5fbd,#0a4a98) !important;
            color:white !important;
            border:1px solid #237ad1 !important;
            border-radius:9px !important;
            box-shadow:none !important;
        }
        .stButton > button:hover, .stDownloadButton > button:hover {
            border-color:#50a5ff !important;
            transform:translateY(-1px);
        }

        /* Make the AI Council feel like the mockup */
        div[data-testid="stVerticalBlock"] > div:has(h3) {
            border-color:transparent;
        }

        /* Mobile/tablet fit */
        @media (max-width:900px) {
            .block-container {padding-left:.7rem !important; padding-right:.7rem !important;}
            [data-testid="stMetric"] {padding:.7rem .75rem !important;}
            [data-testid="stTabs"] [role="tab"] {white-space:nowrap !important;}
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
else:
    st.markdown(
        """
        <style>
        html, body, [data-testid="stAppViewContainer"], .stApp {background:#f4f7fb !important; color:#142033 !important;}
        [data-testid="stSidebar"] {background:#ffffff !important; border-right:1px solid #dfe7f0 !important;}
        [data-testid="stMetric"], [data-testid="stDataFrame"], [data-testid="stTable"], [data-testid="stExpander"] {
            background:#ffffff !important; border:1px solid #dfe7f0 !important; border-radius:12px !important;
        }
        [data-testid="stTabs"] [role="tablist"] {background:#fff !important; border:1px solid #dfe7f0 !important; border-radius:12px !important; padding:.3rem !important;}
        [data-testid="stTabs"] [role="tab"][aria-selected="true"] {background:#e9f3ff !important; color:#075eb5 !important; border-radius:8px !important;}
        </style>
        """,
        unsafe_allow_html=True,
    )
'''

s = s[:m.end()] + theme + s[m.end():]
s = s.replace('APP_VERSION = "2026.09.04-single-file-r20-friendly-ai-council"',
              'APP_VERSION = "2026.09.04-single-file-r21-visual-dashboard"', 1)

compile(s, 'app.py', 'exec')
p.write_text(s)
print('R21 visual dashboard patch applied successfully')
