from pathlib import Path

p = Path('app.py')
s = p.read_text()
if 'import re\n' not in s:
    s = s.replace('import math\n', 'import math\nimport re\n', 1)
compile(s, 'app.py', 'exec')
p.write_text(s)
print('Added missing import re to app.py')
