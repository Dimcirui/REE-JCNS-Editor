"""
build_mixed_rig.py -- xaihi test rig, round 15: which entry decides how a bone with mixed rotation
types is composed, and do the unknown ConstraintInfo / source bytes change anything?
Round-11 mesh, reused as is.  Every entry reads L_Thigh.X (ReadMode 3) through a two-point map
(-90..90 degrees, gains X 0.5, Y 0.8, Z -0.9), Flags 49, joint-group counts 0.

Round 13 measured a bone with (type 1, type 4, type 1) on X, Y, Z: composed as Euler, the type 4
entry's Y value used as the Euler Y.  The first and the last entry were both type 1, so "the first
decides", "the last decides" and "the majority decides" were not separated:

  [08]      A  type 1 X                                control
  [09-11]   B  X type 4, Y type 1, Z type 4       first 4  last 4  majority 4
  [12-14]   C  X type 4, Y type 4, Z type 1       first 4  last 1  majority 4
  [15-17]   D  X type 4, Y type 1, Z type 1       first 4  last 1  majority 1
  [18-20]   E  X type 1, Y type 4, Z type 4       first 1  last 4  majority 4
  [21-23]   F  X type 1, Y type 1, Z type 4       first 1  last 4  majority 1

The unknown bytes, each on a type 1 X entry like A (shipped values, never seen in a rig):

  [24]  G  +74 = 5, +75 = 8, +72 = 2, +28 = 3, +29 = 2   everything at once
  [25]  H  +74 = 5
  [26]  I  +75 = 8
  [27]  J  +72 = 2
  [28]  K  source +28 = 3
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

# (bone, TransformType, axis, extras) ; extras: tail74, tail75, byte72, src28
MIXED = {'B': (4, 1, 4), 'C': (4, 4, 1), 'D': (4, 1, 1), 'E': (1, 4, 4), 'F': (1, 1, 4)}
UNKNOWN = {'G': dict(tail74=5, tail75=8, byte72=2, src28=3 | (2 << 8)), 'H': dict(tail74=5),
           'I': dict(tail75=8), 'J': dict(byte72=2), 'K': dict(src28=3)}
ENTRIES = [('A', 1, 'X', {})]
for bone, types in MIXED.items():
    ENTRIES += [(bone, t, ax, {}) for t, ax in zip(types, 'XYZ')]
ENTRIES += [(bone, 1, 'X', ex) for bone, ex in UNKNOWN.items()]
FIRST_OUT = 8


def main(dst):
    p = JCNSParser(SRC)
    with contextlib.redirect_stdout(io.StringIO()):
        cons = p.parse()
    assert len(cons) == 8
    tmpl = copy.deepcopy(cons[0])
    for c in cons:
        t = bytearray(c['TailBytes'])
        t[3] = 0
        c['TailBytes'] = bytes(t)
    for bone, tt, axis, ex in ENTRIES:
        i = 'XYZ'.index(axis)
        c = copy.deepcopy(tmpl)
        c.update(ObjectName='TestTgt' + bone, TransformType=tt, Flags=49, TransformAxis_parent=i, target_axis=i,
                 UnknownByte72=ex.get('byte72', 0), UnknownFloat2=(0.0, 0.0))
        tail = bytearray(c['TailBytes'])
        tail[0], tail[1], tail[3] = ex.get('tail74', 0), ex.get('tail75', 2), 0
        c['TailBytes'] = bytes(tail)
        k = GAIN[axis]
        c['sources'][0].update(
            SourceName='L_Thigh', source_axis=0, ReadMode=3, CurveMode=0, EulerOrder=0,
            UnknownUInt32_28=ex.get('src28', 0), ref_frame_x=0.0, ref_frame_y=0.0, ref_frame_z=0.0, ref_frame_w=1.0,
            from_start=-90.0, from_kink=0.0, from_end=90.0, to_start=-90.0 * k, to_kink=0.0, to_end=90.0 * k,
            ComplexMapping=[], ComplexMappingInfoCount=0)
        cons.append(c)
    assert len(cons) == FIRST_OUT + len(ENTRIES) and tail_group_counts(cons) == [0] * len(cons)
    JCNSWriter(p, dst).build_lossless()
    return check(dst)


def check(dst):
    q = JCNSParser(dst)
    with contextlib.redirect_stdout(io.StringIO()):
        back = q.parse()
    assert len(back) == FIRST_OUT + len(ENTRIES) and [c['TailBytes'][3] for c in back] == [0] * len(back)
    for i, (c, (bone, tt, axis, ex)) in enumerate(zip(back[FIRST_OUT:], ENTRIES)):
        s = c['sources'][0]
        assert (c['ObjectName'], c['TransformType'], c['Flags'], 'XYZ'[c['target_axis']]) == \
            ('TestTgt' + bone, tt, 49, axis), i
        assert c['TailBytes'][0] == ex.get('tail74', 0) and c['TailBytes'][1] == ex.get('tail75', 2), i
        assert c['UnknownByte72'] == ex.get('byte72', 0), i
        assert s['UnknownUInt32_28'] == ex.get('src28', 0), (i, s['UnknownUInt32_28'])
        assert (s['SourceName'], s['ReadMode'], s['CurveMode'], s['EulerOrder']) == ('L_Thigh', 3, 0, 0)
        print(f"[{FIRST_OUT + i:02}] {c['ObjectName']:<11} TT={tt} .{axis} +74={c['TailBytes'][0]} +75={c['TailBytes'][1]}"
              f" +72={c['UnknownByte72']} src+28={s['UnknownUInt32_28']:#x}")
    return q


if __name__ == '__main__':
    if '--output' not in sys.argv:
        sys.exit("give --output <path>; this script never overwrites the game's jcns on its own")
    main(sys.argv[sys.argv.index('--output') + 1])
