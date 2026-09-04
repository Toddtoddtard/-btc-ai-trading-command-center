from pathlib import Path

p = Path('app.py')
s = p.read_text()

s = s.replace('APP_VERSION = "2026.09.04-single-file-r23-directional-call-badges"', 'APP_VERSION = "2026.09.04-single-file-r24-large-call-cards"')

old_css = '''    .direction-call.call-neutral {
        color:#c2d1e6; background:rgba(140,160,190,.11);
        border-color:rgba(140,160,190,.45);
    }
'''
new_css = '''    .direction-call.call-neutral {
        color:#c2d1e6; background:rgba(140,160,190,.11);
        border-color:rgba(140,160,190,.45);
    }
    .direction-card {
        width:100%; min-height:92px; box-sizing:border-box;
        display:flex; align-items:center; justify-content:center;
        padding:14px 16px; border-radius:13px;
        background:linear-gradient(180deg,rgba(11,27,47,.96),rgba(7,20,35,.96));
        border:1px solid #1687ff;
        box-shadow:0 10px 28px rgba(0,0,0,.18), 0 0 0 1px rgba(22,135,255,.10) inset;
    }
    .direction-card .direction-call {
        min-width:150px; padding:10px 18px; font-size:1.08rem;
    }
    .direction-card.verdict-card {
        width:min(100%, 330px); min-height:82px; justify-content:flex-start;
    }
    .direction-card.verdict-card .direction-call {
        min-width:165px;
    }
'''
if old_css not in s:
    raise SystemExit('base directional CSS anchor not found')
s = s.replace(old_css, new_css, 1)

old_call = '''        with d1:
            st.caption("Call")
            st.markdown(directional_badge_html(decision["action"]), unsafe_allow_html=True)
'''
new_call = '''        with d1:
            st.caption("Call")
            st.markdown(
                f'<div class="direction-card">{directional_badge_html(decision["action"])}</div>',
                unsafe_allow_html=True,
            )
'''
if old_call not in s:
    raise SystemExit('main call anchor not found')
s = s.replace(old_call, new_call, 1)

old_verdict = '''        st.markdown("### Council verdict")
        st.markdown(directional_badge_html(action), unsafe_allow_html=True)
        st.write(plain_call)
'''
new_verdict = '''        st.markdown("### Council verdict")
        st.markdown(
            f'<div class="direction-card verdict-card">{directional_badge_html(action)}</div>',
            unsafe_allow_html=True,
        )
        st.write(plain_call)
'''
if old_verdict not in s:
    raise SystemExit('verdict anchor not found')
s = s.replace(old_verdict, new_verdict, 1)

p.write_text(s)
print('Applied R24 large blue call cards; visual-only change.')
