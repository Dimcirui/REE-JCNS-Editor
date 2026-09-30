"""
Flag high-risk words in user-visible text (docs/UI_COPY_GUIDE.md).

    python tools/ui_copy_check.py [FILE...]

Scans the add-on's own modules (not scripts/, tests/, tools/): every string literal
that contains Chinese text or is passed as name= / description= / text= / a report
message, docstrings excluded.  Prints file:line and the text for each hit; a hit
still needs a human decision.  Exits 1 when anything was flagged.
"""
import ast
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

RISKY = re.compile('|'.join((
    '实测', '实机', '测试台', '验证', '确认', '语料', '样本', '原版文件', '全部原版', '推测', '推断',
    '原名', r'\bbt\b', '曾', '误判', r'第\s*\d+\s*轮', r'20\d\d-\d\d', '未测', '待测', '置信',
    '社区', '官方', r'\bfallback\b', r'\braw\b', r'\bcorpus\b', r'\bformerly\b', r'\bunk\w*',
    'Traceback', r'[A-Za-z]:[\\/]',
)), re.IGNORECASE)
CJK = re.compile('[一-鿿]')
UI_KEYWORDS = {'name', 'description', 'text', 'bl_label', 'bl_description'}


def _docstring_nodes(tree):
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            b = node.body
            if b and isinstance(b[0], ast.Expr) and isinstance(b[0].value, ast.Constant):
                out.add(id(b[0].value))
    return out


def _ui_strings(tree):
    """Constants passed where the UI shows them, even without Chinese text."""
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg in UI_KEYWORDS:
                    for c in ast.walk(kw.value):
                        if isinstance(c, ast.Constant) and isinstance(c.value, str):
                            out.add(id(c))
            if isinstance(node.func, ast.Attribute) and node.func.attr in ('report', 'label'):
                for a in node.args:
                    for c in ast.walk(a):
                        if isinstance(c, ast.Constant) and isinstance(c.value, str):
                            out.add(id(c))
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id in UI_KEYWORDS and isinstance(node.value, ast.Constant):
                    out.add(id(node.value))
    return out


def check(path):
    src = open(path, encoding='utf-8').read()
    tree = ast.parse(src, path)
    docs, ui = _docstring_nodes(tree), _ui_strings(tree)
    hits = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)) or id(node) in docs:
            continue
        s = node.value
        if not (CJK.search(s) or id(node) in ui):
            continue
        for m in RISKY.finditer(s):
            hits.append((node.lineno, m.group(0), s.strip().replace('\n', ' ')[:120]))
            break
    return hits


def main():
    files = sys.argv[1:] or sorted(glob.glob(os.path.join(ROOT, '*.py')) +
                                   glob.glob(os.path.join(ROOT, 'modules', '*.py')))
    total = 0
    for f in files:
        if os.path.basename(f) == 'build_addon.py':
            continue
        for line, word, text in check(f):
            total += 1
            print('%s:%d  [%s]  %s' % (os.path.relpath(f, ROOT), line, word, text))
    print('%d hit(s)' % total)
    return 1 if total else 0


if __name__ == '__main__':
    sys.exit(main())
