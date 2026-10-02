"""
Flag high-risk words in user-visible text (docs/UI_COPY_GUIDE.md).

    python tools/ui_copy_check.py [FILE...]

Scans the add-on's own modules (not scripts/, tests/, tools/): every string literal
that contains Chinese text or is passed as name= / description= / text= / a report
message, docstrings excluded except those of registered JCNS_* classes (Blender
shows them as tooltips).  A line carrying `# ui-copy: internal` is skipped:
its strings are never shown.  Prints file:line and the text for each hit; a hit
still needs a human decision.  Exits 1 when anything was flagged.

Each value of the string tables in modules/jcns_strings is scanned too, in both languages.

A second rule covers the panels' default view (docs/UI_COPY_GUIDE.md, principle 3):
text drawn by jcns_ui / jcns_editors / jcns_sdk_ops / jcns_merge_ops / jcns_capture
must not use internal vocabulary.  Classes whose name says Advanced / Raw / Reserved
are the 高级 panels and exempt; so is a line carrying `# ui-copy: advanced`.
Tooltips (description=, docstrings) are not checked by this rule.
"""
import ast
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'modules'))
import jcns_strings  # noqa: E402

# Text now lives in modules/jcns_strings; code refers to it by key.
TABLE = jcns_strings.load()

RISKY = re.compile('|'.join((
    '实测', '实机', '测试台', '验证', '确认', '语料', '样本', '原版', '推测', '推断',
    '原名', r'\bbt\b', '曾', '误判', r'第\s*\d+\s*轮', r'20\d\d-\d\d', '未测', '待测', '置信',
    '社区', '官方', r'\bfallback\b', r'\braw\b', r'\bcorpus\b', r'\bformerly\b', r'\bunk\w*',
    'Traceback', r'[A-Za-z]:[\\/]',
)), re.IGNORECASE)
# Internal vocabulary: allowed in 高级 panels and tooltips, not in what a panel draws by default.
INTERNAL = re.compile('|'.join((
    '三点映射', '两点映射', 'ComplexMapping', '关键帧（', r'\+\d\d\b', r'\bbit\d', r'\bFlags\b', '字节',
    '驱动源', '源骨骼', '驱动骨',
)))
DEFAULT_VIEW_FILES = {'jcns_ui.py', 'jcns_editors.py', 'jcns_sdk_ops.py', 'jcns_merge_ops.py',
                      'jcns_capture.py'}
ADVANCED_CLASS = re.compile(r'Advanced|_Raw|Reserved')
CJK = re.compile('[一-鿿]')
UI_KEYWORDS = {'name', 'description', 'text', 'bl_label', 'bl_description'}


# Blender shows the class docstring of a registered type as its tooltip.
_TOOLTIP_BASES = {'Operator', 'Panel', 'UIList', 'Menu'}


def _is_tooltip_class(node):
    return (isinstance(node, ast.ClassDef) and node.name.startswith('JCNS_')
            and any(getattr(b, 'id', getattr(b, 'attr', '')) in _TOOLTIP_BASES
                    or getattr(b, 'id', '').startswith('_') for b in node.bases))


def _docstring_nodes(tree):
    """Docstrings that are not shown to the user."""
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            b = node.body
            if (b and isinstance(b[0], ast.Expr) and isinstance(b[0].value, ast.Constant)
                    and not _is_tooltip_class(node)):
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


def _drawn_strings(tree):
    """(node, text) for each constant drawn as a panel's text: label(...) arguments and any
    text= keyword, outside the 高级 panels."""
    out = []

    def visit(node, advanced):
        if isinstance(node, ast.ClassDef) and ADVANCED_CLASS.search(node.name):
            advanced = True
        if isinstance(node, ast.Call) and not advanced:
            args = []
            if isinstance(node.func, ast.Attribute) and node.func.attr == 'label':
                args += node.args[:1]
            args += [kw.value for kw in node.keywords if kw.arg == 'text']
            for a in args:
                for c in ast.walk(a):
                    if isinstance(c, ast.Constant) and isinstance(c.value, str):
                        out.append(c)
        for child in ast.iter_child_nodes(node):
            visit(child, advanced)

    visit(tree, False)
    return out


def check(path):
    src = open(path, encoding='utf-8').read()
    tree = ast.parse(src, path)
    docs, ui = _docstring_nodes(tree), _ui_strings(tree)
    internal = {i + 1 for i, l in enumerate(src.split('\n')) if 'ui-copy: internal' in l}
    hits = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)) or id(node) in docs:
            continue
        if node.lineno in internal:
            continue
        s = node.value
        if s in TABLE:
            continue
        if not (CJK.search(s) or id(node) in ui):
            continue
        for m in RISKY.finditer(s):
            hits.append((node.lineno, m.group(0), s.strip().replace('\n', ' ')[:120]))
            break
    if os.path.basename(path) in DEFAULT_VIEW_FILES:
        advanced = {i + 1 for i, l in enumerate(src.split('\n')) if 'ui-copy: advanced' in l}
        for node in _drawn_strings(tree):
            if node.lineno in internal or node.lineno in advanced:
                continue
            text = TABLE[node.value]['ZH'] if node.value in TABLE else node.value
            m = INTERNAL.search(text)
            if m:
                hits.append((node.lineno, m.group(0), 'default view: ' + text.strip()[:100]))
    return hits


def check_tables():
    """Every ZH and EN value of the string tables against the risky-word list."""
    hits = []
    for key, entry in sorted(TABLE.items()):
        for lang, text in sorted(entry.items()):
            m = RISKY.search(text)
            # "unknown" / "Raw Fields" are the ordinary English for 未知 / 原始字段
            while m and lang == 'EN' and (m.group(0).lower().startswith('unk') or m.group(0).lower() == 'raw'):
                m = RISKY.search(text, m.end())
            if m:
                hits.append((key + '/' + lang, m.group(0), text.strip().replace('\n', ' ')[:120]))
    return hits


def main():
    files = sys.argv[1:] or sorted(glob.glob(os.path.join(ROOT, '*.py')) +
                                   glob.glob(os.path.join(ROOT, 'modules', '*.py')))
    total = 0
    if not sys.argv[1:]:
        for key, word, text in check_tables():
            total += 1
            print('%s  [%s]  %s' % (key, word, text))
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
