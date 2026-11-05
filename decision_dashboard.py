"""Clear forecast / worker action / executable economics presentation."""
import time
from datetime import datetime
from pro_trade_ticket import build_pro_trade_ticket
from scalp_exit_research import scorecard
from trade_assessment import finite
from dashboard_ui import metric_cards_html


def outlook_label(decision):
    action = str(decision.get('action') or 'WAIT')
    if action.startswith('LOCK '):
        return 'LOCKED OUTLOOK '+action.split()[-1]
    if action.endswith((' UP',' DOWN')):
        return 'OUTLOOK '+action.split()[-1]
    return 'OUTLOOK UNAVAILABLE'


def decision_status(decision, state):
    paper = state.get('background_paper') or {}
    p = paper.get('open_position')
    return dict(outlook=outlook_label(decision),
                paper_action=('HOLD '+str(p.get('strategy'))+' '+str(p.get('direction')) if p else 'WAIT'),
                reason=paper.get('last_message','Waiting for the persistent paper worker'),
                last_cycle_at=paper.get('last_cycle_at'))


def render_decision_assessment(decision, risk, state, futures, reference):
    import streamlit as st
    paper = state.get('background_paper') or {}
    view = decision_status(decision,state)
    st.markdown('#### Paper trading')
    age = None
    try:
        age = time.time()-datetime.fromisoformat(str(view['last_cycle_at']).replace('Z','+00:00')).timestamp()
    except (ValueError,TypeError):
        pass
    if age is None or age > 1200:
        st.warning('Paper worker state is stale or unavailable; this outlook is not confirmation of a new paper trade.')
    preview_risk = dict(risk)
    if (paper.get('gate') or {}).get('position_cap') is not None:
        preview_risk['position_pct'] = paper['gate']['position_cap']
    ticket = build_pro_trade_ticket(decision,preview_risk,paper,
             has_open_position=bool(paper.get('open_position')),lock_gate=paper.get('lock_gate'))
    assessment = ticket.get('assessment') or {}
    worker_assessment = paper.get('entry_assessment') or {}
    if decision.get('decision_id') and worker_assessment.get('decision_id') == decision['decision_id']:
        assessment = worker_assessment
    p=finite(assessment.get('selected_probability'))
    breakeven=finite(assessment.get('break_even_probability'))
    edge=finite(assessment.get('net_edge_per_contract'))
    st.markdown(metric_cards_html([
        ('Paper action — worker', view['paper_action']),
        ('Settlement estimate', f'{p:.1%}' if p is not None else 'Unavailable'),
        ('Break-even after fee', f'{breakeven:.1%}' if breakeven is not None else 'Unavailable'),
        ('Net settlement edge / contract', f'{edge*100:+.2f}¢' if edge is not None else 'Unavailable'),
    ]), unsafe_allow_html=True)
    st.caption(view['reason'])
    if worker_assessment.get('decision_id'):
        from display_time import eastern_time
        st.caption('Assessed worker decision ' + str(worker_assessment['decision_id']) +
                   ' • ' + eastern_time(worker_assessment.get('checked_at'), clock_only=True))
    if ticket['blockers']:
        st.caption('Entry preview: WAIT · approval checks have not passed. See details below.')
    with st.expander('Contract details and entry checks'):
        st.caption('Probability source: '+str(decision.get('contract_probability_source') or 'Unavailable')+
                   '. Preview includes rounded fees; only the persistent worker can fill after current depth, freshness, position and risk checks.')
        st.caption('Futures input: ' + ('Available' if futures.get('ok') else 'Unavailable'))
        if not futures.get('ok'):
            st.caption('Futures liquidity and derivatives abstain while their source is unavailable; zero is not a live reading.')
        st.caption('Signal strength and agreement are indicator scores, not probabilities of winning. Related price indicators share one corroboration family; every specialist remains available.')
        for blocker in ticket['blockers']:
            st.markdown('• ' + str(blocker))
        st.caption('A winning LOCK payout is a conditional scenario, not expected profit. A terminal settlement estimate is not an early-exit forecast.')
    research=scorecard(state)
    with st.expander('SCALP exit research — observed bid paths'):
        st.write(dict(official_markets=research['eligible_official_markets'],
                      censored_markets=research['censored_markets'],
                      target_hits=research['target_hits'],net_pnl=round(research['net_pnl'],3)))
        st.caption('Latest bid-path observation: '+research['last_observation_status'])
        st.caption(research['scope'])
        st.caption('Research cannot approve fills. New SCALP entries wait for a separately validated exit model; no threshold or settlement safeguard is relaxed.')
