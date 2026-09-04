from pathlib import Path

p = Path('app.py')
s = p.read_text()

s = s.replace('APP_VERSION = "2026.09.04-single-file-r25-unified-council-style"', 'APP_VERSION = "2026.09.04-single-file-r26-raised-direction-cards"')

old = '''    .direction-card .direction-call {
        min-width:150px; padding:10px 18px; font-size:1.08rem;
    }
'''
new = '''    .direction-card .direction-call {
        min-width:150px; padding:10px 18px; font-size:1.08rem;
        transform:translateY(-5px);
    }
'''
if old not in s:
    raise SystemExit('direction card badge CSS anchor not found')
s = s.replace(old, new, 1)

p.write_text(s)
print('Applied R26: raised directional badges 5px inside blue cards.')
