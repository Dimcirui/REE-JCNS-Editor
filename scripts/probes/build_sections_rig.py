"""
build_sections_rig.py -- xaihi test rig, round 12: Aim / RotExpression / Skin, which no
round has put into the game yet.  Every round so far wrote Ranges only; xaihi's section
table is [0], so the other sections would not even run -- this script rewrites it to
[1, 3, 2, 0] (RotExpression, Aim, Skin, Ranges, the order of the one shipped file that
has all four).

Bones (round-11 mesh, reused as is).  Each target is written by exactly one entry:

  Ranges   [08]  A.X  type 1 F49 <- L_Thigh.X (ReadMode 3) x0.5        input control
  Aim      B  type 0  no up bone        (rest: multi-axis)
           C  type 1  up = L_Hand
           D  type 2  up = L_Hand
           H  type 3  no up bone
           I  type 4  no up bone
           all: aimed at R_Hand, Vec0 0, Vec1 (1,0,0), Vec2 (0,1,0), Vec3 (0,1,0),
           Influence 1, bytes (1,0,5) -- only the rotation type differs
  RotExpr  E  <- L_Thigh, coefficients (0.5, 0.8, -0.9), bytes (0,0,0,0)    (scaled rest)
           F  <- L_Thigh, same, bytes (0,48,0,0)   [the flag pair shipped in 5 records]
  Skin     J  L_Hand 0.5, R_Hand 0.3, Head 0.2          (weights sum to 1)
           K  L_Hand 0.5, R_Hand 0.25                   (weights sum to 0.75)
  G        not driven: a fixed bone, to check the recorded world coordinates

The body bones named above exist in xaihi's own skeleton too (constrained copies).
ReadJointTable is left empty, as in every shipped player / NPC file that has a Skin or Aim.
"""
import contextlib
import copy
import io
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'modules'))

import jcns_sections as X
from modules.jcns_parser import JCNSParser
from modules.jcns_writer import JCNSWriter, tail_group_counts

DIR = r"E:/Program/Steam/steamapps/common/MonsterHunterWilds/natives/STM/art/model/character/ch03/xaihi"
SRC = DIR + "/xaihi_constraint.jcns.102.orig_20260929"
DST = DIR + "/xaihi_constraint.jcns.102"

SECTION_TABLE = [1, 3, 2, 0]      # 0 Ranges, 1 RotExpression, 2 Skin, 3 Aim
CONSTANT = 5                      # the per-file constant shipped Skin / Aim records carry

AIM_TARGET = 'R_Hand'
AIM_UP = 'L_Hand'
AIMS = [('B', 0, None), ('C', 1, AIM_UP), ('D', 2, AIM_UP), ('H', 3, None), ('I', 4, None)]
ROTS = [('E', (0, 0, 0, 0)), ('F', (0, 48, 0, 0))]
ROT_SOURCE, ROT_GAINS = 'L_Thigh', (0.5, 0.8, -0.9)
SKINS = [('J', [('L_Hand', 0.5), ('R_Hand', 0.3), ('Head', 0.2)]),
         ('K', [('L_Hand', 0.5), ('R_Hand', 0.25)])]


def H(name):
    from mmh3.pymmh3 import hashUTF16
    return hashUTF16(name) & 0xFFFFFFFF


def set_count(c, n):
    tail = bytearray(c['TailBytes'])
    tail[3] = n
    c['TailBytes'] = bytes(tail)


def plan():
    """The expectation table the analysers read: one record per entry."""
    return {
        'ranges': [('A', 'X', ROT_SOURCE, 0.5)],
        'aim': [{'bone': 'TestTgt' + b, 'type': t, 'target': AIM_TARGET, 'up': up} for b, t, up in AIMS],
        'rot': [{'bone': 'TestTgt' + b, 'source': ROT_SOURCE, 'gains': ROT_GAINS, 'bytes': by} for b, by in ROTS],
        'skin': [{'bone': 'TestTgt' + b, 'sources': s} for b, s in SKINS],
    }


def main(dst=DST):
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
    s = c['sources'][0]
    s.update(SourceName='L_Thigh', source_axis=0, ReadMode=3, CurveMode=0, EulerOrder=0,
             from_start=-90.0, from_kink=0.0, from_end=90.0, to_start=-45.0, to_kink=0.0, to_end=45.0,
             ComplexMapping=[], ComplexMappingInfoCount=0)
    cons.append(c)
    assert tail_group_counts(cons) == [0] * len(cons)

    aims = [{'joint': H('TestTgt' + b), 'target': H(AIM_TARGET), 'up': H(up) if up else None,
             'influence': 1.0, 'vectors': [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 1, 0)],
             'rotation_type': t, 'bytes': (1, 0, CONSTANT), 'tail': bytes(12), 'target_tail': bytes(8)}
            for b, t, up in AIMS]
    p.aim_constraints = X.aim_parser_form(aims)

    rots = [{'joint': H('TestTgt' + b), 'source': H(ROT_SOURCE), 'rotation': (0, 0, 0, 1),
             'scale': (0, 0, 0, 1), 'bytes': by, 'floats': ROT_GAINS} for b, by in ROTS]
    p.rot_expressions, p.rot_expression_map = X.rot_parser_form(rots, {'map': [CONSTANT]}, p.version)

    records = [{'object': H('TestTgt' + b), 'tail': bytes(2),
                'sources': [{'hash': H(n), 'weight': w} for n, w in srcs]} for b, srcs in SKINS]
    p.skin_constraints, p.skin_source_infos = X.skin_parser_form(records, {'constant': CONSTANT})
    p.read_joint_table = []

    # The writer copies the section table from original_bytes, `SectionTableItemCount` long.
    hdr = p.header
    orig = bytearray(p.original_bytes)
    off = hdr['SectionTableEntry']
    orig[off:off + 4 * len(SECTION_TABLE)] = struct.pack('<%dI' % len(SECTION_TABLE), *SECTION_TABLE)
    from modules.jcns_schema import HEADER
    HEADER.pack_into(orig, hdr['DataEntry'], {'SectionCount': len(SECTION_TABLE)}, p.version)
    p.original_bytes = bytes(orig)
    hdr['SectionTableItemCount'] = hdr['SectionCount'] = len(SECTION_TABLE)
    for key, n in (('RotExpressionInfoCount', len(rots)), ('RotExpressionMapCount', len(rots)),
                   ('AimConstraintCount', len(aims)), ('SkinConstraintCount', len(records))):
        hdr[key] = n

    JCNSWriter(p, dst).build_lossless()
    return check(dst)


def check(dst):
    """Parse the file back and diff it against plan()."""
    q = JCNSParser(dst)
    with contextlib.redirect_stdout(io.StringIO()):
        back = q.parse()
    h = q.header
    table = list(struct.unpack_from('<%dI' % h['SectionTableItemCount'], q.original_bytes, h['SectionTableEntry']))
    assert table == SECTION_TABLE, table
    assert h['SectionCount'] == len(SECTION_TABLE)
    assert [c['TailBytes'][3] for c in back] == [0] * len(back)
    names = {H(n): n for n in ['TestTgt' + c for c in 'ABCDEFGHIJK'] + [AIM_TARGET, AIM_UP, ROT_SOURCE,
                                                                        'R_Hand', 'L_Hand', 'Head']}
    want = plan()
    assert len(back) == 9 and back[8]['ObjectName'] == 'TestTgtA' and back[8]['sources'][0]['SourceName'] == 'L_Thigh'
    got_aim = X.aim_editable(q)
    assert len(got_aim) == len(want['aim'])
    for g, w in zip(got_aim, want['aim']):
        assert names[g['joint']] == w['bone'] and names[g['target']] == w['target'], g
        assert (names[g['up']] if g['up'] else None) == w['up']
        assert g['rotation_type'] == w['type'] and g['vectors'][1] == (1.0, 0.0, 0.0), g
    got_rot, meta = X.rot_editable(q)
    assert meta['map'] == [CONSTANT] * len(want['rot'])
    for g, w in zip(got_rot, want['rot']):
        assert names[g['joint']] == w['bone'] and names[g['source']] == w['source']
        assert g['bytes'] == w['bytes'] and tuple(round(f, 6) for f in g['floats']) == w['gains'], g
    got_skin, smeta = X.skin_editable(q)
    assert smeta['read_joint_table'] == [] and smeta['constant'] == CONSTANT
    for g, w in zip(got_skin, want['skin']):
        assert names[g['object']] == w['bone']
        assert [(names[s['hash']], round(s['weight'], 6)) for s in g['sources']] == w['sources'], g
    for i, c in enumerate(back):
        s = c['sources'][0]
        print(f"[{i:02}] {c['ObjectName']:<14}.{'XYZW'[c['target_axis']]} <- {s['SourceName']}")
    print('aim', [(names[a['joint']], a['rotation_type']) for a in got_aim])
    print('rot', [(names[a['joint']], a['bytes']) for a in got_rot])
    print('skin', [(names[a['object']], [names[s['hash']] for s in a['sources']]) for a in got_skin])
    print('section table', table, 'hashes', len(q.hash_list), 'bytes', os.path.getsize(dst))
    return q


if __name__ == '__main__':
    out = sys.argv[sys.argv.index('--output') + 1] if '--output' in sys.argv else None
    if out is None:
        sys.exit("give --output <path>; this script never overwrites the game's jcns on its own")
    main(out)
