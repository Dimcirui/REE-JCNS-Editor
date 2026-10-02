"""
build_aim2_rig.py -- xaihi test rig, round 17: what Aim's influence, Vec0 and (type 2) Vec3 do, and how
RotExpression's gain maps the angle.  Round-11 mesh, reused as is.  Section table [1, 3, 0].

  Ranges   [08]  A.X  type 1 F49 <- L_Thigh.X (InputType 3) x0.5        input control
  Aim      all aimed at R_Hand, Vec1 (1,0,0), Vec2 (0,1,0), Vec3 (0,1,0), Vec0 0, bytes (1,0,5)
           B  type 0  influence 0.25
           C  type 0  influence 2.0
           D  type 4  influence 0.5
           E  type 2  up = L_Hand, Vec3 (0,0,1)            what does Vec3 do for type 2?
           F  type 2  up = L_Hand, Vec0 (0.1, 0.05, 0.02)  what does Vec0 do?
           G  type 1  up = L_Hand, influence 0.5
  RotExpr  source L_Thigh, bytes (0,0,0,0)
           H  (0.999, 1, 1)   a copy, or does the exact (1,1,1) copy stop being one?
           I  (0.5, 0, 0)     K  (1, 0, 0)     J  (2, 0, 0)    one axis at gains 0.5 / 1 / 2
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
TARGET, UP = 'R_Hand', 'L_Hand'
# (bone, type, up bone, vec0, vec3, influence)
AIMS = [('B', 0, None, (0, 0, 0), (0, 1, 0), 0.25), ('C', 0, None, (0, 0, 0), (0, 1, 0), 2.0),
        ('D', 4, None, (0, 0, 0), (0, 1, 0), 0.5), ('E', 2, UP, (0, 0, 0), (0, 0, 1), 1.0),
        ('F', 2, UP, (0.1, 0.05, 0.02), (0, 1, 0), 1.0), ('G', 1, UP, (0, 0, 0), (0, 1, 0), 0.5)]
ROT_SOURCE = 'L_Thigh'
ROTS = [('H', (0.999, 1.0, 1.0)), ('I', (0.5, 0.0, 0.0)), ('J', (2.0, 0.0, 0.0)), ('K', (1.0, 0.0, 0.0))]


def main(dst):
    p = JCNSParser(SRC)
    with contextlib.redirect_stdout(io.StringIO()):
        cons = p.parse()
    assert len(cons) == 8 and not p.aim_constraints
    for c in cons:
        set_count(c, 0)
    c = copy.deepcopy(cons[0])
    c['ObjectName'] = 'TestTgtA'
    c['Axis_parent'] = c['target_axis'] = 0
    c['AttrFlags'], c['TransformElement'] = 49, 1
    set_count(c, 0)
    c['sources'][0].update(SourceName='L_Thigh', source_axis=0, InputType=3, AttrFlags=0, RotOrder=0,
                           from_start=-90.0, from_kink=0.0, from_end=90.0, to_start=-45.0, to_kink=0.0, to_end=45.0,
                           ComplexMapping=[], ComplexMappingInfoCount=0)
    cons.append(c)
    assert tail_group_counts(cons) == [0] * len(cons)
    aims = [{'joint': H('TestTgt' + b), 'target': H(TARGET), 'up': H(up) if up else None, 'influence': inf,
             'vectors': [v0, (1, 0, 0), (0, 1, 0), v3], 'world_up_type': t, 'bytes': (1, 0, CONSTANT),
             'tail': bytes(12), 'target_tail': bytes(8)} for b, t, up, v0, v3, inf in AIMS]
    p.aim_constraints = X.aim_parser_form(aims)
    rots = [{'joint': H('TestTgt' + b), 'source': H(ROT_SOURCE), 'rotation': (0, 0, 0, 1), 'scale': (0, 0, 0, 1),
             'bytes': (0, 0, 0, 0), 'floats': g} for b, g in ROTS]
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
    q = JCNSParser(dst)
    with contextlib.redirect_stdout(io.StringIO()):
        back = q.parse()
    h = q.header
    table = list(struct.unpack_from('<%dI' % h['SectionTableItemCount'], q.original_bytes, h['SectionTableEntry']))
    assert table == SECTION_TABLE and len(back) == 9 and not q.multi_constraints
    names = {H(n): n for n in ['TestTgt' + c for c in 'ABCDEFGHIJK'] + [TARGET, UP, ROT_SOURCE]}
    got = X.aim_editable(q)
    assert len(got) == len(AIMS)
    for g, (b, t, up, v0, v3, inf) in zip(got, AIMS):
        assert names[g['joint']] == 'TestTgt' + b and names[g['target']] == TARGET and g['world_up_type'] == t
        assert (names[g['up']] if g['up'] else None) == up and abs(g['influence'] - inf) < 1e-6
        assert [tuple(round(x, 4) for x in v) for v in g['vectors']] == [v0, (1, 0, 0), (0, 1, 0), v3], g
        print('aim', b, t, up, g['vectors'][0], g['vectors'][3], g['influence'])
    got_rot, meta = X.rot_editable(q)
    assert meta['map'] == [CONSTANT] * len(ROTS)
    for g, (b, gains) in zip(got_rot, ROTS):
        assert names[g['joint']] == 'TestTgt' + b and g['bytes'] == (0, 0, 0, 0)
        assert tuple(round(f, 6) for f in g['floats']) == gains
        print('rot', b, gains)
    print('section table', table, 'bytes', os.path.getsize(dst))
    return q


if __name__ == '__main__':
    if '--output' not in sys.argv:
        sys.exit("give --output <path>; this script never overwrites the game's jcns on its own")
    main(sys.argv[sys.argv.index('--output') + 1])
