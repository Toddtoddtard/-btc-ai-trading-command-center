#!/usr/bin/env python3
from pathlib import Path

p = Path('app.py')
text = p.read_text()

import_anchor = 'import streamlit.components.v1 as components\n'
if 'from access_control import require_owner_approval' not in text:
    if import_anchor not in text:
        raise SystemExit('streamlit import anchor missing')
    text = text.replace(import_anchor, import_anchor + 'from access_control import require_owner_approval\n', 1)

config_anchor = 'st.set_page_config(\n'
if 'require_owner_approval()' not in text:
    idx = text.find(config_anchor)
    if idx == -1:
        raise SystemExit('page config anchor missing')
    # place gate immediately after the set_page_config(...) block
    end = text.find('\n)\n', idx)
    if end == -1:
        raise SystemExit('page config close missing')
    end += 3
    text = text[:end] + '\n\nrequire_owner_approval()\n' + text[end:]

text = text.replace('APP_VERSION = "2026.09.04-r37-reliability-v31"', 'APP_VERSION = "2026.09.04-r38-private-access"')

if 'from access_control import require_owner_approval' not in text or 'require_owner_approval()' not in text:
    raise SystemExit('access gate patch failed')

p.write_text(text)
print('private access gate applied')
