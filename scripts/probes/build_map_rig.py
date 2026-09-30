"""
build_map_rig.py -- xaihi test rig, round 3 (2026-09-30): where do writes to the
added test bones land?

Rounds 1-2 showed each entry's own output (getOutputUserValue) is right, but on the
joints only TestTgtA/D/G (indices 562/565/568) carried any output, several entries
shared values, and weights made no difference.  Here every entry gets a unique linear
scale of the same input, so any joint that moves can be traced to exactly one entry.

  [00]-[07] original dress entries
  [08]-[18] TestTgtA..K .X <- L_Thigh.X * k,  k = 1/12 .. 11/12
  [19] TestTgtA.Y <- L_Thigh.X * -0.3
  [20] TestTgtB.Z <- L_Thigh.X * -0.6
  [21] TestTgtC.Y <- L_Thigh.X * -0.9

Two-point mapping from=(-90,0,90) to=(-90k,0,90k), same hidden fields as rounds 1-2.
The mesh from round 2 (573 bones, TestTgtA..K under COG) is reused as is.
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
from modules.jcns_writer import JCNSWriter

DIR = r"E:/Program/Steam/steamapps/common/MonsterHunterWilds/natives/STM/art/model/character/ch03/xaihi"
SRC = DIR + "/xaihi_constraint.jcns.102.orig_20260929"
DST = DIR + "/xaihi_constraint.jcns.102"

AXIS = {'X': 0, 'Y': 1, 'Z': 2}
ENTRIES = [('TestTgt' + L, 'X', (i + 1) / 12.0) for i, L in enumerate('ABCDEFGHIJK')]
ENTRIES += [('TestTgtA', 'Y', -0.3), ('TestTgtB', 'Z', -0.6), ('TestTgtC', 'Y', -0.9)]
# Round 4: TestTgtA..K re-parented under Ear_SCL so they sit at indices 63-73 (the dress
# bones shift +11 as a side effect), and four idle, unweighted original leaf bones become
# targets too:
#   [22]-[25] L_ForeHead_LOD01 / R_ForeHead_LOD01 / L_EyeBagJ_A_LOD00 / R_EyeBagJ_A_LOD00 .X
ENTRIES += [('L_ForeHead_LOD01', 'X', -0.15), ('R_ForeHead_LOD01', 'X', -0.35),
            ('L_EyeBagJ_A_LOD00', 'X', -0.55), ('R_EyeBagJ_A_LOD00', 'X', -0.75)]


def main():
    p = JCNSParser(SRC)
    with contextlib.redirect_stdout(io.StringIO()):
        cons = p.parse()
    assert len(cons) == 8, len(cons)
    tmpl = cons[0]
    for tgt, axis, k in ENTRIES:
        c = copy.deepcopy(tmpl)
        c['ObjectName'] = tgt
        c['TransformAxis_parent'] = c['target_axis'] = AXIS[axis]
        c['Flags'] = 49
        c['TransformType'] = 1
        s = c['sources'][0]
        s['SourceName'] = 'L_Thigh'
        s['source_axis'] = 0
        s['ReadMode'] = 3
        s['CurveMode'] = 0            # two-point line
        s['from_start'], s['from_kink'], s['from_end'] = -90.0, 0.0, 90.0
        s['to_start'], s['to_kink'], s['to_end'] = -90.0 * k, 0.0, 90.0 * k
        s['ComplexMapping'] = []
        s['ComplexMappingInfoCount'] = 0
        cons.append(c)
    assert cons is p.constraints
    JCNSWriter(p, DST).build_lossless()
    q = JCNSParser(DST)
    with contextlib.redirect_stdout(io.StringIO()):
        back = q.parse()
    for i, c in enumerate(back):
        s = c['sources'][0]
        print(f"[{i:02}] {c['ObjectName']:<14}.{'XYZW'[c['target_axis']]} <- {s['SourceName']}.{'XYZW'[s['source_axis']]}"
              f" +24={s['CurveMode']} from=({s['from_start']:g},{s['from_end']:g}) to=({s['to_start']:g},{s['to_end']:g})")


if __name__ == '__main__':
    main()
