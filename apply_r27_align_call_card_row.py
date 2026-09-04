from pathlib import Path

p = Path('app.py')
s = p.read_text()

s = s.replace('APP_VERSION = "2026.09.04-single-file-r26-call-content-align"', 'APP_VERSION = "2026.09.04-single-file-r27-call-card-row-align"')
s = s.replace('APP_VERSION = "2026.09.04-single-file-r25-unified-council-style"', 'APP_VERSION = "2026.09.04-single-file-r27-call-card-row-align"')

# The Call column has a Streamlit caption above its custom card while the metric cards
# include their labels inside the cards. Pull the ENTIRE Call card upward so its blue
# outer border aligns with the Master score / Confidence / Consensus / Risk cards.
anchor = '''    .direction-card .direction-call {
        min-width:150px; padding:10px 18px; font-size:1.08rem;
    }
'''
addition = '''    .direction-card .direction-call {
        min-width:150px; padding:10px 18px; font-size:1.08rem;
    }
    /* Align the whole primary Call card with the neighboring metric-card row. */
    .primary-call-card {
        transform: translateY(-27px);
        margin-bottom: -27px;
    }
'''
if anchor not in s:
    raise SystemExit('direction-card CSS anchor not found')
s = s.replace(anchor, addition, 1)

old = '''f'<div class="direction-card">{directional_badge_html(decision["action"])}</div>' '''
new = '''f'<div class="direction-card primary-call-card">{directional_badge_html(decision["action"])}</div>' '''
if old not in s:
    # tolerate formatting without trailing space
    old = '''f'<div class="direction-card">{directional_badge_html(decision["action"])}</div>', '''
    new = '''f'<div class="direction-card primary-call-card">{directional_badge_html(decision["action"])}</div>', '''
if old not in s:
    raise SystemExit('primary call markup anchor not found')
s = s.replace(old, new, 1)

p.write_text(s)
print('Applied R27: moved entire primary Call card up to align with Master score row.')
