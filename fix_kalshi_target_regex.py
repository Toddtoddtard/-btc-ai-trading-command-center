from pathlib import Path

for name in ('app.py','learner.py'):
    p=Path(name)
    s=p.read_text()
    s=s.replace(r'r"Target\\s*Price\\s*:\\s*\\$?([0-9][0-9,]*(?:\\.[0-9]+)?)"', r'r"Target\s*Price\s*:\s*\$?([0-9][0-9,]*(?:\.[0-9]+)?)"')
    s=s.replace(r'/Target\\s*Price\\s*:\\s*\\$?([0-9][0-9,]*(?:\\.[0-9]+)?)/i', r'/Target\s*Price\s*:\s*\$?([0-9][0-9,]*(?:\.[0-9]+)?)/i')
    if name == 'app.py':
        s=s.replace('APP_VERSION = "2026.09.04-r31-kalshi-timer-server-seeded"','APP_VERSION = "2026.09.04-r32-kalshi-target-restored"')
    compile(s,name,'exec')
    p.write_text(s)
print('Fixed Kalshi Target Price regex in app, browser chart, and learner.')
