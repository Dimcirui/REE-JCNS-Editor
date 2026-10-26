"""
build_jxg_nodes.py
------------------
Build modules/data/jxg_nodes.json: every JointExprGraph node type the game knows
(name and RSZ type hash, from an RSZ type dump), and for the types that appear in
a corpus of extracted .jntexprgraph files, what those files show about them:

  kind      the node header's kind word (constant per type in the corpus)
  inputs    [slot, value type, how it is fed]  — 'prop', 'link' or 'both'
  outputs   [slot, value type]                 — the declared outputs (constant per type)
  count     how many nodes of this type the corpus has

Slots a type has but no shipped file uses are not listed.

Example:
    python tools/build_jxg_nodes.py \\
        --rsz "E:/Data/MODTools/MHWS MOD/REasy/rszmhwilds.json" \\
        --corpus "E:/Program/Steam/steamapps/common/MonsterHunterWilds/MHWILDS_EXTRACT"

Not shipped with the add-on.
"""

import argparse
import collections
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, 'modules'))
OUT = os.path.join(REPO, 'modules', 'data', 'jxg_nodes.json')

# Graph node types are the RSZ types in these namespaces whose name ends in Node,
# plus the game's own app.expr_node.* classes and app.SkirtNode.
_NAMESPACES = ('via.motion.exprgraph.', 'via.userdata.exprgraph.', 'via.sound.exprgraph.', 'via.zivart.Expr')


def _is_node_type(name):
    if any(c in name for c in '[]<>`,'):
        return False
    if name.startswith('app.expr_node.') or name == 'app.SkirtNode':
        return True
    return name.startswith(_NAMESPACES) and name.endswith('Node')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--rsz', required=True)
    ap.add_argument('--corpus', required=True)
    args = ap.parse_args()

    with open(args.rsz, encoding='utf-8') as f:
        rsz = json.load(f)
    types = {v['name']: int(k, 16) for k, v in rsz.items()
             if isinstance(v, dict) and 'name' in v and _is_node_type(v['name'])}

    # jxg_format resolves names through the file this script writes; seed it first
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump({n: {'hash': '%08x' % h} for n, h in types.items()}, f)
    import jxg_format

    seen = collections.defaultdict(lambda: dict(count=0, kind=set(), inputs=collections.defaultdict(lambda: [set(), set()]),
                                                outputs=set()))
    files = glob.glob(os.path.join(args.corpus, '**', '*.jntexprgraph.*'), recursive=True)
    for path in files:
        with open(path, 'rb') as f:
            G = jxg_format.read(f.read())
        for nd in G['nodes']:
            s = seen[nd['type']]
            s['count'] += 1
            s['kind'].add(nd['kind'])
            s['outputs'].add(tuple(nd['outputs']))
            for slot, t, _ in nd['props']:
                s['inputs'][slot][0].add(t)
                s['inputs'][slot][1].add('prop')
            for l in nd['inputs']:
                s['inputs'][l['dst_slot']][0].add(l['dst_type'])
                s['inputs'][l['dst_slot']][1].add('link')

    out = {}
    for name in sorted(types):
        e = {'hash': '%08x' % types[name]}
        s = seen.get(name)
        if s:
            if len(s['kind']) != 1 or len(s['outputs']) != 1:
                sys.exit('%s: kind or outputs vary across the corpus' % name)
            inputs = []
            for slot in sorted(s['inputs']):
                ts, roles = s['inputs'][slot]
                if len(ts) != 1:
                    sys.exit('%s slot %d: several value types %s' % (name, slot, ts))
                inputs.append([slot, ts.pop(), 'both' if len(roles) == 2 else roles.pop()])
            e.update(kind=s['kind'].pop(), count=s['count'], inputs=inputs,
                     outputs=[list(o) for o in s['outputs'].pop()])
        out[name] = e
    unknown = sorted(set(seen) - set(types))
    if unknown:
        sys.exit('types in the corpus but not in the RSZ dump: %s' % unknown)
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write('{\n' + ',\n'.join('%s: %s' % (json.dumps(k), json.dumps(v)) for k, v in out.items()) + '\n}\n')
    print('%d node types, %d seen in %d files -> %s' % (len(out), len(seen), len(files), OUT))


if __name__ == '__main__':
    main()
