"""
Check the string tables against the code that uses them.

    python tools/i18n_check.py [--baseline DIR]

Errors (exit 1):
  - a table fails to load (key outside its module's prefix, duplicate key)
  - an entry lacks ZH or EN, or its EN text contains Chinese
  - ZH and EN use different % placeholders
  - T("key") names a key that is not in any table
  - T("key", a, b) passes a different number of arguments than the placeholders
  - Chinese text still sits in a string literal of the add-on's own modules
    (docstrings, comments and lines marked `# ui-copy: internal` are skipped)
Warnings: T() with a computed key; keys no code refers to (a key counts as referred to when
its text appears as a string literal anywhere, so tables of keys are fine).

With --baseline DIR (a copy of the sources from before the conversion) it also checks that
every Chinese literal found there still appears in some ZH value, so the default language
reads exactly as before.
"""
import ast
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'modules'))

CJK = re.compile('[一-鿿]')
PLACEHOLDER = re.compile(r'%(?:\([^)]*\))?[-+# 0]*\d*(?:\.\d+)?[sdifgxXr]')
SKIP_DIRS = ('jcns_strings',)


def sources(base):
    files = glob.glob(os.path.join(base, '*.py')) + glob.glob(os.path.join(base, 'modules', '*.py'))
    return sorted(f for f in files
                  if os.path.basename(f) not in ('build_addon.py',))


def docstring_ids(tree):
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            b = node.body
            if b and isinstance(b[0], ast.Expr) and isinstance(getattr(b[0], 'value', None), ast.Constant):
                out.add(id(b[0].value))
    return out


def literals(path):
    """(lineno, text) of every non-docstring string literal that is not marked internal."""
    src = open(path, encoding='utf-8').read()
    lines = src.splitlines()
    tree = ast.parse(src)
    skip = docstring_ids(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip:
            line = lines[node.lineno - 1] if node.lineno <= len(lines) else ''
            if 'ui-copy: internal' in line:
                continue
            yield node.lineno, node.value


def t_calls(path):
    tree = ast.parse(open(path, encoding='utf-8').read())
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'T'
                and node.args and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            yield node.lineno, node.args[0].value, len(node.args) - 1, any(
                isinstance(a, ast.Starred) for a in node.args[1:])
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'T'):
            yield node.lineno, None, 0, False


def main(argv):
    baseline = argv[argv.index('--baseline') + 1] if '--baseline' in argv else None
    errors, warnings = [], []
    import jcns_strings
    try:
        table = jcns_strings.load()
    except ValueError as ex:
        print('table load failed: %s' % ex)
        return 1

    for key, entry in sorted(table.items()):
        zh, en = entry.get('ZH'), entry.get('EN')
        if not zh or not en:
            errors.append('%s: missing %s' % (key, 'ZH' if not zh else 'EN'))
            continue
        if CJK.search(en):
            errors.append('%s: EN contains Chinese' % key)
        if sorted(PLACEHOLDER.findall(zh)) != sorted(PLACEHOLDER.findall(en)):
            errors.append('%s: placeholders differ (ZH %s / EN %s)' % (
                key, PLACEHOLDER.findall(zh), PLACEHOLDER.findall(en)))

    used = set()
    for path in sources(ROOT):
        rel = os.path.relpath(path, ROOT)
        for lineno, key, nargs, starred in t_calls(path):
            if key is None:
                warnings.append('%s:%d: T() with a non-literal key' % (rel, lineno))
                continue
            used.add(key)
            entry = table.get(key)
            if entry is None:
                errors.append('%s:%d: unknown key %s' % (rel, lineno, key))
                continue
            if not starred and nargs != len(PLACEHOLDER.findall(entry['ZH'])):
                errors.append('%s:%d: %s takes %d placeholder(s), call passes %d' % (
                    rel, lineno, key, len(PLACEHOLDER.findall(entry['ZH'])), nargs))
        for lineno, text in literals(path):
            if text in table:
                used.add(text)
            if CJK.search(text):
                errors.append('%s:%d: Chinese literal left in code: %s' % (rel, lineno, text[:40]))
    # keys referenced indirectly (T(var)) are not seen; list only as warnings
    for key in sorted(set(table) - used):
        warnings.append('unused key %s' % key)

    if baseline:
        zh_all = '\n'.join(e['ZH'] for e in table.values())
        for path in sources(baseline):
            rel = os.path.relpath(path, baseline)
            for lineno, text in literals(path):
                if CJK.search(text) and text not in zh_all:
                    # f-string fragments and %-formatted pieces are matched piecewise
                    pieces = [p for p in re.split(r'%[-+# 0]*\d*(?:\.\d+)?[sdifgxXr]|\{[^}]*\}', text)
                              if CJK.search(p)]
                    if not all(p in zh_all for p in pieces):
                        warnings.append('baseline %s:%d: not found in ZH tables: %s' % (
                            rel, lineno, text[:50]))

    for w in warnings:
        print('warning:', w)
    for e in errors:
        print('error:', e)
    print('%d keys, %d errors, %d warnings' % (len(table), len(errors), len(warnings)))
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
