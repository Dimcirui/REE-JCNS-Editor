"""
build_ttype_rig.py -- xaihi test rig, round 9 (2026-09-30): what do TransformType
4 / 5 / 6 / 13 / 14 do to a bone, next to the measured 1 (Rotation)?

Type 13 alone is 20% of shipped constraints (helper HJ, cloth-offset, sleeve bones;
never on a bone that also has type 1), 14 is 1.6% (aprons, tentacles), 4 5.7% (twist
and deltoid bones), 6 only ThighRX / ThighRZ (always read as a rotation vector), 5 one
TopBank file.  All are "joint + angular" by their Flags bits.  Each type gets one test
bone written on all three axes with distinct gains, so the bone's recorded quaternion
can be matched against candidate compositions (Euler orders, pre- or post-multiplied
by rest, rotation vector, swing-twist).

  [08]-[10]  A.X/Y/Z  type 1   (control: rest * Rz * Ry * Rx, measured)
  [11]-[13]  B.X/Y/Z  type 13
  [14]-[16]  C.X/Y/Z  type 14
  [17]-[19]  D.X/Y/Z  type 4
  [20]-[22]  E.X/Y/Z  type 5
  [23]-[25]  F.X/Y/Z  type 6
  [26]-[28]  G.X/Y/Z  type 13 with Flags 48 (bit0 = 0: replace; 34% of shipped 13s)
  [29]       H.X      type 13, X only (does a single channel behave like type 1?)

Every entry: L_Thigh.X (ReadMode 3) through a two-point map, gains X 0.5, Y 0.8,
Z -0.9 (H: 0.5).  TestTgt rest is -2 deg X, which tells pre- from post-multiplying
once Y / Z turn.  Every joint-group count is 0.  The round-4 mesh is reused.
"""
import copy
import io
import contextlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'modules'))

from modules.jcns_parser import JCNSParser
from modules.jcns_writer import JCNSWriter, tail_group_counts

DIR = r"E:/Program/Steam/steamapps/common/MonsterHunterWilds/natives/STM/art/model/character/ch03/xaihi"
SRC = DIR + "/xaihi_constraint.jcns.102.orig_20260929"
DST = DIR + "/xaihi_constraint.jcns.102"

AXIS = {'X': 0, 'Y': 1, 'Z': 2}
T = 'TestTgt'
GAIN = {'X': 0.5, 'Y': 0.8, 'Z': -0.9}
# (bone, TransformType, Flags, axes)
BONES = [('A', 1, 49, 'XYZ'), ('B', 13, 49, 'XYZ'), ('C', 14, 49, 'XYZ'), ('D', 4, 49, 'XYZ'),
         ('E', 5, 49, 'XYZ'), ('F', 6, 49, 'XYZ'), ('G', 13, 48, 'XYZ'), ('H', 13, 49, 'X')]


def set_count(c, n):
    tail = bytearray(c['ParentTailBytes'])
    tail[3] = n
    c['ParentTailBytes'] = bytes(tail)


def main():
    p = JCNSParser(SRC)
    with contextlib.redirect_stdout(io.StringIO()):
        cons = p.parse()
    assert len(cons) == 8, len(cons)
    tmpl = cons[0]
    for c in cons:
        set_count(c, 0)
    for bone, tt, flags, axes in BONES:
        for ax in axes:
            c = copy.deepcopy(tmpl)
            c['ObjectName'] = T + bone
            c['TransformAxis_parent'] = c['target_axis'] = AXIS[ax]
            c['Flags'] = flags
            c['TransformType'] = tt
            set_count(c, 0)
            s = c['sources'][0]
            s['SourceName'] = 'L_Thigh'
            s['source_axis'] = 0
            s['ReadMode'] = 3
            s['CurveMode'] = 0
            s['EulerOrder'] = 0
            k = GAIN[ax]
            s['from_start'], s['from_kink'], s['from_end'] = -90.0, 0.0, 90.0
            s['to_start'], s['to_kink'], s['to_end'] = -90.0 * k, 0.0, 90.0 * k
            s['ComplexMapping'] = []
            s['ComplexMappingInfoCount'] = 0
            cons.append(c)
    assert cons is p.constraints
    assert tail_group_counts(cons) == [0] * len(cons)
    JCNSWriter(p, DST).build_lossless()
    q = JCNSParser(DST)
    with contextlib.redirect_stdout(io.StringIO()):
        back = q.parse()
    assert [c['ParentTailBytes'][3] for c in back] == [0] * len(back)
    for i, c in enumerate(back):
        s = c['sources'][0]
        print(f"[{i:02}] {c['ObjectName']:<14}.{'XYZW'[c['target_axis']]}  TT={c['TransformType']:<2} F={c['Flags']}"
              f"  <- {s['SourceName']}.{'XYZ'[s['source_axis']]}  to_end={s['to_end']:g}")


if __name__ == '__main__':
    main()
