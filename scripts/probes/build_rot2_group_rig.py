"""
build_rot2_group_rig.py -- xaihi test rig, round 19 (2026-10-07): does a joint group of
Rot2 (TransformElement 13) entries compose one Euler rotation in TailBytes[0] order?

The native evaluator (docs/engine-names.md section 4) collects the axis values of one
joint group's Rot2 entries into a vec3 and turns it into a quaternion with
TailBytes[0] as the RotOrder.  Round 9 put every entry in its own group and saw
"last entry wins", which that reading also predicts.  Shipped files with a non-zero
TailBytes[0] on Rot2 are ch04 only (waist bones: X and Z in one group, order 2).

  [08]-[09]  A.X/Z    one group, Tail0 = 2 (ZXY)        the shipped waist case
  [10]-[11]  B.X/Z    one group, Tail0 = 0 (XYZ)        control for A
  [12]-[14]  C.X/Y/Z  one group, Tail0 = 5 (XZY)
  [15]-[17]  D.X/Y/Z  one group, Tail0 = 1 (YZX)
  [18]-[19]  E.X/Z    two groups, Tail0 = 2             expect Z alone (round 9 rule)
  [20]-[21]  F.X/Z    one group, head Tail0 = 0, member Tail0 = 2   whose byte counts?

Every entry: L_Thigh.X (InputType 3) through a two-point map, gains X 0.5, Y 0.8,
Z -0.9, AttrFlags 49 (bit0 = 1: laid on the rest pose).  The originals [00]-[07] get
group count 0 as in round 9.
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
# (bone, axes, grouped, tail0 per entry)
BONES = [('A', 'XZ', True, (2, 2)), ('B', 'XZ', True, (0, 0)), ('C', 'XYZ', True, (5, 5, 5)),
         ('D', 'XYZ', True, (1, 1, 1)), ('E', 'XZ', False, (2, 2)), ('F', 'XZ', True, (0, 2))]


def set_tail(c, i, v):
    tail = bytearray(c['TailBytes'])
    tail[i] = v
    c['TailBytes'] = bytes(tail)


def main():
    p = JCNSParser(SRC)
    with contextlib.redirect_stdout(io.StringIO()):
        cons = p.parse()
    assert len(cons) == 8, len(cons)
    tmpl = cons[0]
    for c in cons:
        set_tail(c, 3, 0)
    want = [0] * len(cons)
    for bone, axes, grouped, tail0 in BONES:
        for n, ax in enumerate(axes):
            c = copy.deepcopy(tmpl)
            c['ObjectName'] = T + bone
            c['Axis_parent'] = c['target_axis'] = AXIS[ax]
            c['AttrFlags'] = 49
            c['TransformElement'] = 13
            set_tail(c, 0, tail0[n])
            count = len(axes) - 1 if grouped and n == 0 else 0
            set_tail(c, 3, count)
            want.append(count)
            s = c['sources'][0]
            s['SourceName'] = 'L_Thigh'
            s['source_axis'] = 0
            s['InputType'] = 3
            s['AttrFlags'] = 0
            s['RotOrder'] = 0
            k = GAIN[ax]
            s['from_start'], s['from_kink'], s['from_end'] = -90.0, 0.0, 90.0
            s['to_start'], s['to_kink'], s['to_end'] = -90.0 * k, 0.0, 90.0 * k
            s['ComplexMapping'] = []
            s['ComplexMappingInfoCount'] = 0
            cons.append(c)
    assert cons is p.constraints
    assert tail_group_counts(cons) == want, tail_group_counts(cons)
    assert len(cons) < 80
    JCNSWriter(p, DST).build_lossless()
    q = JCNSParser(DST)
    with contextlib.redirect_stdout(io.StringIO()):
        back = q.parse()
    assert [c['TailBytes'][3] for c in back] == want
    for i, c in enumerate(back):
        s = c['sources'][0]
        tb = bytes(c['TailBytes'])
        print(f"[{i:02}] {c['ObjectName']:<14}.{'XYZW'[c['target_axis']]}  TT={c['TransformElement']:<2} F={c['AttrFlags']}"
              f"  tail0={tb[0]} tail1={tb[1]} group={tb[3]}  <- {s['SourceName']}.{'XYZ'[s['source_axis']]}  to_end={s['to_end']:g}")


if __name__ == '__main__':
    main()
