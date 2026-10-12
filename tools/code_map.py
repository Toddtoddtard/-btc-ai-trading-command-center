"""Bounded source navigation, using only stdlib and never importing app code."""
import argparse
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def index(root):
    paths = sorted({p for folder in (root, root / 'pages', root / 'tests',
                                    root / 'tools', root / 'scripts')
                    for p in folder.glob('*.py') if not p.is_symlink()})
    modules = {p.relative_to(root).with_suffix('').as_posix().replace('/', '.'):
               p.relative_to(root).as_posix() for p in paths}
    records = {}
    for path in paths:
        name = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text(encoding='utf-8'), filename=name)
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and not node.level:
                imports.add(node.module or '')
                imports.update(f'{node.module}.{alias.name}' for alias in node.names)
        definitions = [(n.name, n.lineno, n.end_lineno) for n in tree.body
                       if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
        records[name] = {'imports': sorted({modules[m] for m in imports if m in modules}),
                         'definitions': definitions}
    return records


def show(title, rows, limit):
    print(f'{title} ({len(rows)}):')
    for row in rows[:limit]:
        print(f'  {row}')
    if not rows:
        print('  none')
    if len(rows) > limit:
        print(f'  ... {len(rows) - limit} omitted; narrow --symbol or raise --limit')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file', help='Exact repo-relative Python path, e.g. app.py')
    parser.add_argument('--symbol', default='', help='Top-level definition name substring')
    parser.add_argument('--limit', type=int, default=30, help='Maximum rows per section')
    args = parser.parse_args()
    if args.limit < 1:
        parser.error('--limit must be positive')
    records = index(ROOT)
    name = Path(args.file).as_posix()
    if name not in records:
        parser.error(f'No indexed Python file: {name}')
    record = records[name]
    print(f'{name} — current source; static direct imports only')
    show('Definitions', [f'{n}: {name}:{start}-{end}'
                         for n, start, end in record['definitions'] if args.symbol in n], args.limit)
    show('Imports', record['imports'], args.limit)
    show('Imported by', [p for p, r in records.items() if name in r['imports']], args.limit)
    print('Dynamic calls, workflow invocations and string references are not resolved.')


if __name__ == '__main__':
    main()
