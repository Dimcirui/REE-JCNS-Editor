"""
corpus_fields.py -- value distributions of the Ranges raw fields over every shipped
.jcns.102, and a helper to see what predicts a field.

    python scripts/probes/corpus_fields.py            # the distribution table
    python scripts/probes/corpus_fields.py UnkField   # ... plus what predicts one field

The parsed corpus is cached in %TEMP%/jcns_v102_corpus.pkl (delete it after a parser
change).  Import it for ad-hoc questions:

    from corpus_fields import load, dist, rank, crosstab
    C, S = load()          # [(file, constraint)], [(file, constraint, index, source)]

This is how the 2026-09-30 inventory (modules/jcns_parser.py docstring,
jcns_editors.FIXED_RANGES_FIELDS) was made: a field that is 100% one value is fixed,
and for a live one, `rank` shows which feature explains it (UnkByte2 turned out to
follow the source bone at 94.5%, which is what pointed at a per-bone Euler order).
"""
import collections
import contextlib
import glob
import io
import os
import pickle
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'modules'))

EXTRACT = 'E:/Program/Steam/steamapps/common/MonsterHunterWilds/MHWILDS_EXTRACT'
CACHE = os.path.join(os.environ.get('TEMP', HERE), 'jcns_v102_corpus.pkl')


def load():
    if os.path.exists(CACHE):
        files = pickle.load(open(CACHE, 'rb'))
    else:
        import jcns_parser
        files = []
        for f in glob.glob(EXTRACT + '/**/*.jcns.102', recursive=True):
            p = jcns_parser.JCNSParser(f)
            with contextlib.redirect_stdout(io.StringIO()):
                cs = p.parse()
            if not isinstance(cs, list):
                continue
            keep = []
            for c in cs:
                d = {k: v for k, v in c.items() if not k.startswith('_') and k != 'ConeDriverInfo'}
                d['sources'] = [{k: v for k, v in s.items() if not k.startswith('_') and k != 'ComplexMapping'}
                                for s in c['sources']]
                keep.append(d)
            files.append((f.split('MHWILDS_EXTRACT')[1], keep))
        pickle.dump(files, open(CACHE, 'wb'))
    C = [(f, c) for f, cs in files for c in cs]
    S = [(f, c, i, s) for f, c in C for i, s in enumerate(c['sources'])]
    return C, S


def dist(label, vals, top=8):
    cnt = collections.Counter(vals)
    tot = sum(cnt.values())
    print('%-26s distinct %-5d %s' % (label, len(cnt), ', '.join(
        '%r:%.1f%%' % (k, 100 * v / tot) for k, v in cnt.most_common(top))))


def rank(label, rows, feats, top=6):
    """rows: [(value, row)]; feats: {name: row -> feature}.  Prints how often the
    feature's majority value is right (the baseline is the overall majority)."""
    base = collections.Counter(y for y, _ in rows).most_common(1)[0][1] / len(rows)
    res = []
    for name, fn in feats.items():
        by = collections.defaultdict(collections.Counter)
        for y, r in rows:
            by[fn(r)][y] += 1
        hit = sum(v.most_common(1)[0][1] for v in by.values()) / len(rows)
        res.append((hit, name, len(by)))
    res.sort(reverse=True)
    print('%s  (baseline %.1f%%)' % (label, 100 * base))
    for hit, name, n in res[:top]:
        print('   %-30s %.1f%%  (%d groups)' % (name, 100 * hit, n))


def crosstab(label, rows, fn, top=12):
    by = collections.defaultdict(collections.Counter)
    for y, r in rows:
        by[fn(r)][y] += 1
    print(label)
    for x, cnt in sorted(by.items(), key=lambda kv: -sum(kv[1].values()))[:top]:
        print('   %-28r %s' % (x, dict(cnt.most_common(6))))


SOURCE_FEATURES = {
    'ReadMode': lambda r: r[3]['ReadMode'],
    'CurveMode': lambda r: r[3]['CurveMode'],
    'source_axis': lambda r: r[3]['source_axis'],
    'source bone': lambda r: r[3].get('SourceName'),
    'TransformType': lambda r: r[1]['TransformType'],
    'Flags': lambda r: r[1]['Flags'],
    'file': lambda r: r[0],
}


def main():
    C, S = load()
    print('files %d  constraints %d  sources %d' % (len({f for f, _ in C}), len(C), len(S)))
    print('--- ConstraintInfo')
    for name, fn in (('PropertyName', lambda c: c['PropertyName']),
                     ('SourceCount', lambda c: c['SourceCount_parent']),
                     ('Flags', lambda c: c['Flags']), ('TransformType', lambda c: c['TransformType']),
                     ('ParentVec4', lambda c: c['ParentVec4']), ('ParentFloat2', lambda c: c['ParentFloat2']),
                     ('ParentUInt8_72', lambda c: c['ParentUInt8_72']),
                     ('TransformAxis', lambda c: c['TransformAxis_v35'])):
        dist(name, [fn(c) for _, c in C], 12)
    for k in range(6):
        dist('Tail[%d] (+%d)' % (k, 74 + k), [c['ParentTailBytes'][k] for _, c in C])
    print('--- Source')
    for name in ('ComplexMappingInfoCount', 'UnknownUInt16', 'CurveMode', 'ReadMode', 'source_axis', 'EulerOrder'):
        dist(name, [s[name] for _, _, _, s in S])
    for k in range(4):
        dist('+%d (UnknownUInt32_2 byte %d)' % (28 + k, k), [(s['UnknownUInt32_2'] >> (8 * k)) & 0xFF for *_, s in S])
    dist('rest_quat', [(s['rest_quat_x'], s['rest_quat_y'], s['rest_quat_z'], s['rest_quat_w']) for *_, s in S])
    if len(sys.argv) > 1:
        field = sys.argv[1]
        rows = [(s[field], r) for r in S for s in [r[3]] if field in s]
        if rows:
            rank('what predicts source field %s' % field,
                 rows, {k: v for k, v in SOURCE_FEATURES.items() if k != field})


if __name__ == '__main__':
    main()
