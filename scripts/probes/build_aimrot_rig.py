"""
build_aimrot_rig.py -- xaihi test rig, round 14: what the Aim vectors / type / influence do,
and the exact form of RotExpression's non-linearity (round 12: per-axis gains are right for
small angles, off by up to 8.6 deg for large ones).

  Ranges   [08]  A.X  type 1 F49 <- L_Thigh.X (ReadMode 3) x0.5        input control
  Aim      all aimed at R_Hand, no up bone, Vec0 0, bytes (1,0,5); one change per bone
           B  type 0  Vec1 (0,0,-1)             is Vec1 the aim axis?
           C  type 0  Vec2 (0,0,1)              which local axis gets "up"?
           D  type 0  Vec3 (0,0,1)              what does Vec3 do?
           J  type 3  Vec3 (0,0,1)              same as D: how do types 0 and 3 differ?
           K  type 5  default vectors           type 5
           I  type 0  Influence 0.5             how is influence applied?
           default vectors: Vec1 (1,0,0), Vec2 (0,1,0), Vec3 (0,1,0), Influence 1
  RotExpr  source L_Thigh, bytes (0,0,0,0) (the result does not include the rest pose)
           E  coefficients (1,1,1)     a copy?
           F  (1,0,0)   G  (0,1,0)   H  (0,0,1)     one axis at a time
Skin is left out, so the section table is [1, 3, 0].
"""
import contextlib
import copy
import io
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'modules'))

import jcns_sections as X
from build_sections_rig import CONSTANT, H, SRC, set_count
from modules.jcns_parser import JCNSParser
from modules.jcns_schema import HEADER
from modules.jcns_writer import JCNSWriter, tail_group_counts

SECTION_TABLE = [1, 3, 0]
AIM_TARGET = 'R_Hand'
V = dict(v1=(1, 0, 0), v2=(0, 1, 0), v3=(0, 1, 0))
# (bone, type, vec1, vec2, vec3, influence)
AIMS = [('B', 0, (0, 0, -1), V['v2'], V['v3'], 1.0),
        ('C', 0, V['v1'], (0, 0, 1), V['v3'], 1.0),
        ('D', 0, V['v1'], V['v2'], (0, 0, 1), 1.0),
        ('J', 3, V['v1'], V['v2'], (0, 0, 1), 1.0),
        ('K', 5, V['v1'], V['v2'], V['v3'], 1.0),
        ('I', 0, V['v1'], V['v2'], V['v3'], 0.5)]
ROT_SOURCE = 'L_Thigh'
ROTS = [('E', (1.0, 1.0, 1.0)), ('F', (1.0, 0.0, 0.0)), ('G', (0.0, 1.0, 0.0)), ('H', (0.0, 0.0, 1.0))]


def plan():
    return {'aim': [dict(bone='TestTgt' + b, type=t, vec1=v1, vec2=v2, vec3=v3, influence=inf)
                    for b, t, v1, v2, v3, inf in AIMS],
            'rot': [dict(bone='TestTgt' + b, gains=g) for b, g in ROTS]}


def main(dst):
    p = JCNSParser(SRC)
    with contextlib.redirect_stdout(io.StringIO()):
        cons = p.parse()
    assert len(cons) == 8 and not p.aim_constraints and not p.skin_constraints
    for c in cons:
        set_count(c, 0)
    c = copy.deepcopy(cons[0])
    c['ObjectName'] = 'TestTgtA'
    c['TransformAxis_parent'] = c['target_axis'] = 0
    c['Flags'], c['TransformType'] = 49, 1
    set_count(c, 0)
    c['sources'][0].update(SourceName='L_Thigh', source_axis=0, ReadMode=3, CurveMode=0, EulerOrder=0,
                           from_start=-90.0, from_kink=0.0, from_end=90.0,
                           to_start=-45.0, to_kink=0.0, to_end=45.0,
                           ComplexMapping=[], ComplexMappingInfoCount=0)
    cons.append(c)
    assert tail_group_counts(cons) == [0] * len(cons)

    aims = [{'joint': H('TestTgt' + b), 'target': H(AIM_TARGET), 'up': None, 'influence': inf,
             'vectors': [(0, 0, 0), v1, v2, v3], 'rotation_type': t, 'bytes': (1, 0, CONSTANT),
             'tail': bytes(12), 'target_tail': bytes(8)} for b, t, v1, v2, v3, inf in AIMS]
    p.aim_constraints = X.aim_parser_form(aims)
    rots = [{'joint': H('TestTgt' + b), 'source': H(ROT_SOURCE), 'rotation': (0, 0, 0, 1),
             'scale': (0, 0, 0, 1), 'bytes': (0, 0, 0, 0), 'floats': g} for b, g in ROTS]
    p.rot_expressions, p.rot_expression_map = X.rot_parser_form(rots, {'map': [CONSTANT]}, p.version)

    hdr = p.header
    orig = bytearray(p.original_bytes)
    off = hdr['SectionTableEntry']
    orig[off:off + 4 * len(SECTION_TABLE)] = struct.pack('<%dI' % len(SECTION_TABLE), *SECTION_TABLE)
    HEADER.pack_into(orig, hdr['DataEntry'], {'SectionCount': len(SECTION_TABLE)}, p.version)
    p.original_bytes = bytes(orig)
    hdr['SectionTableItemCount'] = hdr['SectionCount'] = len(SECTION_TABLE)
    JCNSWriter(p, dst).build_lossless()
    return check(dst)


def check(dst):
    """Parse back and diff against plan()."""
    q = JCNSParser(dst)
    with contextlib.redirect_stdout(io.StringIO()):
        back = q.parse()
    h = q.header
    table = list(struct.unpack_from('<%dI' % h['SectionTableItemCount'], q.original_bytes, h['SectionTableEntry']))
    assert table == SECTION_TABLE and h['SectionCount'] == 3, table
    assert len(back) == 9 and [c['ParentTailBytes'][3] for c in back] == [0] * 9
    assert not q.skin_constraints
    names = {H(n): n for n in ['TestTgt' + c for c in 'ABCDEFGHIJK'] + [AIM_TARGET, ROT_SOURCE]}
    want = plan()
    got = X.aim_editable(q)
    assert len(got) == len(want['aim'])
    for g, w in zip(got, want['aim']):
        assert names[g['joint']] == w['bone'] and names[g['target']] == AIM_TARGET
        assert g['up'] is None and g['rotation_type'] == w['type']
        assert [tuple(round(x) for x in v) for v in g['vectors'][1:]] == [w['vec1'], w['vec2'], w['vec3']], g
        assert abs(g['influence'] - w['influence']) < 1e-6
    got_rot, meta = X.rot_editable(q)
    assert meta['map'] == [CONSTANT] * len(ROTS)
    for g, w in zip(got_rot, want['rot']):
        assert names[g['joint']] == w['bone'] and names[g['source']] == ROT_SOURCE and g['bytes'] == (0, 0, 0, 0)
        assert tuple(round(f, 6) for f in g['floats']) == w['gains'], g
    for a in got:
        print('aim', names[a['joint']], a['rotation_type'], [tuple(round(x) for x in v) for v in a['vectors'][1:]],
              a['influence'])
    for a in got_rot:
        print('rot', names[a['joint']], tuple(round(f, 3) for f in a['floats']))
    print('section table', table, 'bytes', os.path.getsize(dst))
    return q


if __name__ == '__main__':
    if '--output' not in sys.argv:
        sys.exit("give --output <path>; this script never overwrites the game's jcns on its own")
    main(sys.argv[sys.argv.index('--output') + 1])
