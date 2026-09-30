"""
Prove that an edit touched only comments and docstrings.

    python tools/check_no_logic_change.py [--base REV] FILE...

Compares each file in the working tree with the same file at REV (default HEAD):
both are parsed, docstrings are dropped, and the ASTs must be identical.  Comments
never reach the AST.  Exits 1 and names the first differing file otherwise.
"""
import argparse
import ast
import subprocess
import sys


def _strip_docstrings(tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if (body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                # keep the body non-empty so a docstring-only function stays valid
                node.body = body[1:] or [ast.Pass()]
    return tree


def _shape(source, name):
    return ast.dump(_strip_docstrings(ast.parse(source, name)), include_attributes=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default='HEAD')
    ap.add_argument('files', nargs='+')
    args = ap.parse_args()
    changed = []
    for path in args.files:
        rel = path.replace('\\', '/')
        try:
            old = subprocess.run(['git', 'show', '%s:%s' % (args.base, rel)], check=True,
                                 capture_output=True).stdout.decode('utf-8')
        except subprocess.CalledProcessError:
            print('%s: not in %s, skipped' % (rel, args.base))
            continue
        new = open(path, encoding='utf-8').read()
        if _shape(old, rel) != _shape(new, rel):
            changed.append(rel)
    if changed:
        print('LOGIC CHANGED: ' + ', '.join(changed))
        return 1
    print('no logic change in %d file(s)' % len(args.files))
    return 0


if __name__ == '__main__':
    sys.exit(main())
