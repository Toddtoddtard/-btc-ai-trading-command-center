import json
from pathlib import Path
import os
p=Path(os.environ.get('LEARNING_STATE_OUTPUT', '/tmp/learning_state.json'))
data=json.loads(p.read_text())
assert data.get('version') == 31
assert data.get('status', {}).get('worker_ok') is True
assert data.get('status', {}).get('shared_core') is True
assert data.get('status', {}).get('learning_version') == 31
assert data.get('status', {}).get('strict_expiry_grading') is True
assert data.get('status', {}).get('bot_intelligence_v4_ok') is True
assert data.get('status', {}).get('specialist_self_learning_v5') is True
assert data.get('status', {}).get('intelligence_version') in {6, 7, 9, 10}
assert data.get('status', {}).get('regime_tagged_specialist_history') is True
assert data.get('status', {}).get('current_regime') in {'HIGH_VOL', 'TREND_UP', 'TREND_DOWN', 'LOW_VOL_RANGE', 'RANGE'}
assert data.get('status', {}).get('specialist_knowledge_regime') == data.get('status', {}).get('current_regime') or data.get('specialist_knowledge_v5', {}).get('regime') == data.get('pending', {}).get('regime')
assert 'Kalshi Context AI' in data.get('specialists', {})
assert 'Cross-Market Research AI' in data.get('specialists', {})
assert 'Event AI' not in data.get('specialists', {})
assert 'rolling' in data
assert 'regimes' in data
assert 'confidence_model' in data
assert 'wait_policy' in data
assert 'validation' in data
assert 'champion_challenger' in data
assert data.get('champion_challenger', {}).get('minimum_samples') == 20
assert data.get('champion_challenger', {}).get('required_streak') == 3
assert 'prediction_snapshots' in data
assert 'wait_counterfactual' in data
assert data.get('status', {}).get('research_lab_ok') is True
mode=data.get('btc_execution_mode', {})
assert mode.get('name') == 'BALANCED_CALLS'
assert mode.get('paper_only') is True
assert mode.get('auto_scalping_enabled') is True
assert mode.get('earliest_lock_seconds') == 900
assert mode.get('confidence_floor') == 0.68
assert mode.get('maximum_entry_price') == 0.93
assert mode.get('maximum_lock_entry_price') == 0.93
assert mode.get('maximum_scalp_entry_price') == 0.75
assert data.get('status', {}).get('btc_execution_mode') == 'BALANCED_CALLS'
assert data.get('status', {}).get('auto_scalping_enabled') is True
assert data.get('status', {}).get('schedule_target_minutes') == 10.0
assert data.get('status', {}).get('schedule_late_after_minutes') == 20.0
assert data.get('status', {}).get('scheduler') == 'GitHub Actions best effort'
assert data.get('status', {}).get('continuous_lock_evaluation') is True
assert isinstance(data.get('lock_gate_history', []), list)
assert data.get('lock_gate_stats', {}).get('paper_only') is True
assert data.get('horizon_models', {}).get('paper_only') is True
assert data.get('status', {}).get('horizon_models_paper_only') is True
assert data.get('horizon_models', {}).get('version') == 2
assert data.get('horizon_models', {}).get('minimum_directional_accuracy') == 0.70
assert data.get('status', {}).get('higher_timeframes_requested') == 7
context=data.get('horizon_models', {}).get('latest_context', {})
assert len(context.get('features', {})) == 7
assert all(row.get('closed') is True for row in context.get('details', {}).values())
outlooks=data.get('next_market_outlooks', [])
assert len(outlooks) in {0, 3}
assert all(row.get('research_only') is True for row in outlooks)
assert all(row.get('executable') is False for row in outlooks)
assert isinstance(data.get('forward_outlook_stats', {}), dict)
assert data.get('research_lab', {}).get('paper_only') is True
assert data.get('research_lab', {}).get('affects_execution') is False
assert data.get('research_lab', {}).get('version') == 3
guarded=data.get('research_lab', {}).get('guarded_calibrator', {})
assert guarded.get('version') == 1
assert guarded.get('affects_execution') is False
assert len(data.get('research_lab', {}).get('policies', {})) == 8
league=data.get('research_lab', {}).get('strategy_league', {})
assert league.get('minimum_samples') == 100
assert league.get('required_streak') == 3
assert league.get('active_policy') == 'Current 75 / 5'
assert league.get('affects_execution') is False
teachers=data.get('research_lab', {}).get('external_teacher_lab', {})
assert teachers.get('paper_only') is True
assert teachers.get('affects_execution') is False
assert teachers.get('minimum_samples') == 100
assert teachers.get('required_streak') == 3
assert len(teachers.get('teachers', {})) == 5
assert data.get('specialist_accounting', {}).get('basis') == 'official_kalshi_directional_calls_v1'
assert data.get('bot_intelligence_v4', {}).get('label_basis') == 'official_kalshi_directional_calls_v1'
assert 'bot_intelligence_v4' in data
assert data.get('background_paper', {}).get('paper_only') is True
assert data.get('background_paper', {}).get('worker_ok') is True
multi=data.get('multi_asset_paper', {})
assert multi.get('version') == 2
assert multi.get('paper_only') is True
assert multi.get('real_money_execution') is False
assert multi.get('enabled') is True
assert set(multi.get('assets', {})) == {'gold', 'gas', 'zec', 'wti'}
assert all(row.get('enabled') is True for row in multi.get('assets', {}).values())
assert all(row.get('starting_cash') == 500.0 for row in multi.get('assets', {}).values())
assert all(row.get('risk_mode') in {'LEARNING', 'STANDARD', 'PROBATION'} for row in multi.get('assets', {}).values())
assert isinstance(data.get('bot_intelligence_v4', {}).get('ranking', []), list)
assert 'specialist_knowledge_v5' in data
assert isinstance(data.get('specialist_knowledge_v5', {}).get('bots', {}), dict)
assert data.get('audit_v6_scorecard', {}).get('baseline_total_samples') == 15
assert data.get('audit_v6_scorecard', {}).get('milestones') == [25, 50, 100, 250, 500, 1000]
before=int(data.get('status', {}).get('samples_before_run', 0))
after=int(data.get('status', {}).get('samples_after_run', 0))
assert after >= before, (before, after)
if data.get('status', {}).get('historical_specialist_v7_loaded'):
    historical = data.get('historical_specialist_knowledge_v7', {})
    assert historical.get('evaluated_windows', 0) >= 10000
    historical_version = historical.get('version')
    assert historical_version in {7, 9, 10}
    expected_intelligence_version = int(historical_version)
    assert data.get('status', {}).get('intelligence_version') == expected_intelligence_version
print('learning-state v3.1 + v4 + Specialist Intelligence validation passed; samples', before, '->', after)
