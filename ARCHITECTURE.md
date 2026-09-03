# System architecture

Market data
→ feature engine
→ specialist AIs
→ interaction/combination learner
→ master 15-minute predictor
→ confidence calibration
→ risk engine
→ paper trader
→ journal/backtest
→ retraining loop

Whale AI remains independent and visible, while its outputs are shared with the master layer.
