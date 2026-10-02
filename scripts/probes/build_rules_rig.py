"""
build_rules_rig.py -- xaihi test rig, round 13: the Ranges rules the panel still marks as guesses.
Round-11 mesh, reused as is.  Every entry reads L_Thigh.X (InputType 3) through a two-point map
(-90..90 degrees, gains X 0.5, Y 0.8, Z -0.9) unless it says otherwise.  Every joint-group count is 0.

  [08]     A  type 1 F49 X                     input control
  [09-10]  B  type 4 F48 X, Y                  bit0 = 0 on swing-twist, Z not written
  [11-12]  C  type 5 F48 X, Y                  ... twist-swing
  [13-14]  D  type 6 F48 X, Y                  ... rotation vector      (B, C, D rest (-2, 17, -23))
  [15-16]  G  type 1 F49 X, then F48 Y         add and replace mixed on one bone (rest (-2, 17, -23))
  [17]     H  type 14 F48 Y                    does 14 drop the rest like 13 (round 9)?
  [18-20]  I  type 1 F49 X, type 4 F49 Y, type 1 F49 Z     two rotation types on one bone
  [21]     J  type 1 F49 X, UnknownFloat2 (-45, 0)          the float's effect, against A
  [22]     K  type 1 F49 X, UnknownFloat2 (-90, -90)
  [23-25]  E  rotation X / Y / Z <- E.scale X / Y / Z, InputType 2, identity map 0..3
           (E's static scale is (1.4, 0.7, 1.8): is that what a scale source reads?)
  [26]     F  type 2 F17 Y <- L_Thigh.X, scale 1 +- 0.9 (a moving scale)
  [27]     F  rotation X <- F.scale Y, InputType 2, identity map 0..3  (after [26], same frame)

Outputs of rotation entries are radians, so a reader's output of a scale of 1.4 is 1.4 degrees.
"""
import contextlib
import copy
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'modules'))

from modules.jcns_parser import JCNSParser
from modules.jcns_writer import JCNSWriter, tail_group_counts

DIR = r"E:/Program/Steam/steamapps/common/MonsterHunterWilds/natives/STM/art/model/character/ch03/xaihi"
SRC = DIR + "/xaihi_constraint.jcns.102.orig_20260929"

GAIN = {'X': 0.5, 'Y': 0.8, 'Z': -0.9}
# (bone, TransformElement, AttrFlags, axis, UnknownFloat2, source) ; source = None for L_Thigh.X,
# else (bone, source_axis, InputType, (from), (to)); a scale driver sets its own gain.
ENTRIES = [
    ('A', 1, 49, 'X', (0, 0), None),
    ('B', 4, 48, 'X', (0, 0), None), ('B', 4, 48, 'Y', (0, 0), None),
    ('C', 5, 48, 'X', (0, 0), None), ('C', 5, 48, 'Y', (0, 0), None),
    ('D', 6, 48, 'X', (0, 0), None), ('D', 6, 48, 'Y', (0, 0), None),
    ('G', 1, 49, 'X', (0, 0), None), ('G', 1, 48, 'Y', (0, 0), None),
    ('H', 14, 48, 'Y', (0, 0), None),
    ('I', 1, 49, 'X', (0, 0), None), ('I', 4, 49, 'Y', (0, 0), None), ('I', 1, 49, 'Z', (0, 0), None),
    ('J', 1, 49, 'X', (-45.0, 0.0), None),
    ('K', 1, 49, 'X', (-90.0, -90.0), None),
    ('E', 1, 49, 'X', (0, 0), ('E', 0, 2)), ('E', 1, 49, 'Y', (0, 0), ('E', 1, 2)),
    ('E', 1, 49, 'Z', (0, 0), ('E', 2, 2)),
    ('F', 2, 17, 'Y', (0, 0), 'scale'),
    ('F', 1, 49, 'X', (0, 0), ('F', 1, 2)),
]
FIRST_OUT = 8


def set_count(c, n):
    tail = bytearray(c['TailBytes'])
    tail[3] = n
    c['TailBytes'] = bytes(tail)


def main(dst):
    p = JCNSParser(SRC)
    with contextlib.redirect_stdout(io.StringIO()):
        cons = p.parse()
    assert len(cons) == 8
    tmpl = copy.deepcopy(cons[0])
    for c in cons:
        set_count(c, 0)
    for bone, tt, flags, axis, pf2, src in ENTRIES:
        i = 'XYZ'.index(axis)
        c = copy.deepcopy(tmpl)
        c.update(ObjectName='TestTgt' + bone, TransformElement=tt, AttrFlags=flags, Axis_parent=i,
                 target_axis=i, UnknownByte72=0, UnknownFloat2=tuple(pf2))
        tail = bytearray(c['TailBytes'])
        tail[1], tail[3] = 2, 0
        c['TailBytes'] = bytes(tail)
        s = c['sources'][0]
        common = dict(AttrFlags=0, RotOrder=0, Interpolation=0, ref_frame_x=0.0, ref_frame_y=0.0,
                      ref_frame_z=0.0, ref_frame_w=1.0, ComplexMapping=[], ComplexMappingInfoCount=0)
        if src is None:
            k = GAIN[axis]
            s.update(SourceName='L_Thigh', source_axis=0, InputType=3, from_start=-90.0, from_kink=0.0,
                     from_end=90.0, to_start=-90.0 * k, to_kink=0.0, to_end=90.0 * k, **common)
        elif src == 'scale':
            s.update(SourceName='L_Thigh', source_axis=0, InputType=3, from_start=-90.0, from_kink=0.0,
                     from_end=90.0, to_start=1.0 - 0.9, to_kink=1.0, to_end=1.0 + 0.9, **common)
        else:
            name, ax, mode = src
            s.update(SourceName='TestTgt' + name, source_axis=ax, InputType=mode, from_start=0.0, from_kink=1.0,
                     from_end=3.0, to_start=0.0, to_kink=1.0, to_end=3.0, **common)
        cons.append(c)
    assert cons is p.constraints and len(cons) == FIRST_OUT + len(ENTRIES)
    assert tail_group_counts(cons) == [0] * len(cons)
    JCNSWriter(p, dst).build_lossless()
    return check(dst)


def check(dst):
    q = JCNSParser(dst)
    with contextlib.redirect_stdout(io.StringIO()):
        back = q.parse()
    assert len(back) == FIRST_OUT + len(ENTRIES)
    assert [c['TailBytes'][3] for c in back] == [0] * len(back)
    assert list(q.aim_constraints) == [] and not q.skin_constraints and not q.rot_expressions
    for i, (c, (bone, tt, flags, axis, pf2, src)) in enumerate(zip(back[FIRST_OUT:], ENTRIES)):
        s = c['sources'][0]
        assert (c['ObjectName'], c['TransformElement'], c['AttrFlags'], 'XYZ'[c['target_axis']]) == \
            ('TestTgt' + bone, tt, flags, axis), (i, c['ObjectName'])
        assert tuple(round(v, 4) for v in c['UnknownFloat2']) == tuple(pf2), (i, c['UnknownFloat2'])
        if isinstance(src, tuple):
            assert (s['SourceName'], s['source_axis'], s['InputType']) == ('TestTgt' + src[0], src[1], src[2])
        else:
            assert (s['SourceName'], s['source_axis'], s['InputType']) == ('L_Thigh', 0, 3)
        assert s['RotOrder'] == 0 and s['Interpolation'] == 0 and s['AttrFlags'] == 0
        print(f"[{FIRST_OUT + i:02}] {c['ObjectName']:<11} TT={tt:<2} F={flags} .{axis} pf2={pf2} <- {s['SourceName']}.{s['source_axis']} rm{s['InputType']}")
    return q


if __name__ == '__main__':
    if '--output' not in sys.argv:
        sys.exit("give --output <path>; this script never overwrites the game's jcns on its own")
    main(sys.argv[sys.argv.index('--output') + 1])
