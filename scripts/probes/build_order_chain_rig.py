"""
build_order_chain_rig.py -- xaihi test rig, round 6 (2026-09-30): two questions.

1. Composition order.  Round 4 showed X is applied first, q = rest * R(Y|Z) * R(X),
   but its Y and Z were too small to tell Y*Z from Z*Y.  A and B now drive Y and Z hard
   (up to ~80 deg), and C writes the same three axes as A in reverse file order, so a
   file-order rule would show up as A != C.
2. A source that is itself driven.  D is driven from L_Thigh; E reads D (entry after
   D), F reads D (entry before D, so a one-frame lag or the bind pose would show), G
   reads E (a chain of two), and H reads A.X while A also turns hard on Y and Z (what
   "the X of a multi-axis bone" means to the engine).

  [08] A.X <- L_Thigh.X * 0.5     [11] B.Y <- L_Thigh.X * 0.7
  [09] A.Y <- L_Thigh.X * 0.8     [12] B.Z <- L_Thigh.X * 0.6
  [10] A.Z <- L_Thigh.X * -0.9    [13] C.Z  -0.9  [14] C.Y  0.8  [15] C.X  0.5
  [16] F.X <- TestTgtD.X * 0.6    (before D)
  [17] D.X <- L_Thigh.X * 0.5
  [18] E.X <- TestTgtD.X * 0.6    (after D)
  [19] G.X <- TestTgtE.X * -0.7
  [20] H.X <- TestTgtA.X * 0.5

Every joint-group count is 0 (a valid layout, kept by the writer).  The round-4 mesh
(573 bones, TestTgtA..K under Ear_SCL) is reused as is.
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
# (target, axis, source, k)
ENTRIES = [
    (T + 'A', 'X', 'L_Thigh', 0.5),     # [08]
    (T + 'A', 'Y', 'L_Thigh', 0.8),     # [09]
    (T + 'A', 'Z', 'L_Thigh', -0.9),    # [10]
    (T + 'B', 'Y', 'L_Thigh', 0.7),     # [11]
    (T + 'B', 'Z', 'L_Thigh', 0.6),     # [12]
    (T + 'C', 'Z', 'L_Thigh', -0.9),    # [13]
    (T + 'C', 'Y', 'L_Thigh', 0.8),     # [14]
    (T + 'C', 'X', 'L_Thigh', 0.5),     # [15]
    (T + 'F', 'X', T + 'D', 0.6),       # [16]
    (T + 'D', 'X', 'L_Thigh', 0.5),     # [17]
    (T + 'E', 'X', T + 'D', 0.6),       # [18]
    (T + 'G', 'X', T + 'E', -0.7),      # [19]
    (T + 'H', 'X', T + 'A', 0.5),       # [20]
]


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
    for tgt, axis, src, k in ENTRIES:
        c = copy.deepcopy(tmpl)
        c['ObjectName'] = tgt
        c['TransformAxis_parent'] = c['target_axis'] = AXIS[axis]
        c['Flags'] = 49
        c['TransformType'] = 1
        set_count(c, 0)
        s = c['sources'][0]
        s['SourceName'] = src
        s['source_axis'] = 0
        s['ReadMode'] = 3
        s['CurveMode'] = 0            # two-point line
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
        k = s['to_end'] / s['from_end'] if s['from_end'] else 0
        print(f"[{i:02}] {c['ObjectName']:<14}.{'XYZW'[c['target_axis']]} <- {s['SourceName']}.{'XYZW'[s['source_axis']]}"
              f"  k={k:+.2f}  +25={s['ReadMode']}")


if __name__ == '__main__':
    main()
