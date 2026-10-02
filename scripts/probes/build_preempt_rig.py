"""
build_preempt_rig.py -- xaihi test rig, round 5 (2026-09-30): when several entries
write the same (bone, axis) channel, what does the bone end up with?

The August answer ("the last entry wins, whole") and Round 13's "no answer, the bone
never moves" were both measured on cloned entries whose joint-group byte was wrong,
so both are re-measured here with the byte set on purpose.

Every entry is L_Thigh.X * k with a unique k, so the bone's angle / input ratio
names the rule directly: last, first, sum, or largest.

  [00]-[07] original dress entries (their own [01]/[03] and [05]/[07] already share
            L/R_Dress_HJ_01.Z, non-adjacent)
  A.X  +0.20 [08] ... -0.50 [20]                     non-adjacent pair
  B.X  +0.30 [09], -0.60 [10]                        adjacent, grouped (count 1)
  C.X  +0.40 [11], -0.70 [12]                        adjacent, forced ungrouped (0, 0)
  D.X  +0.55 [24]                                    single writer, control
  E.X  +0.10 [13], +0.25 [18], -0.45 [23]            three non-adjacent writers
  F.X  -0.50 [14] ... +0.20 [22]                     A reversed: position vs magnitude
  G.X  +0.15 [15], G.Y -0.35 [16]                    grouped, different axes
  J.X  +0.20 [17] ... -0.40 [21], K.X between        interleaved with another bone
  K.X  +0.30 [19]                                    single writer
  H, I                                               no writer, zero control

The mesh from round 4 (573 bones, TestTgtA..K under Ear_SCL) is reused as is.
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
# (bone, axis, k, joint-group count)
ENTRIES = [
    ('A', 'X', +0.20, 0),   # [08]
    ('B', 'X', +0.30, 1),   # [09] group head
    ('B', 'X', -0.60, 0),   # [10] member
    ('C', 'X', +0.40, 0),   # [11] adjacent, not grouped
    ('C', 'X', -0.70, 0),   # [12]
    ('E', 'X', +0.10, 0),   # [13]
    ('F', 'X', -0.50, 0),   # [14]
    ('G', 'X', +0.15, 1),   # [15] group head
    ('G', 'Y', -0.35, 0),   # [16] member
    ('J', 'X', +0.20, 0),   # [17]
    ('E', 'X', +0.25, 0),   # [18]
    ('K', 'X', +0.30, 0),   # [19]
    ('A', 'X', -0.50, 0),   # [20]
    ('J', 'X', -0.40, 0),   # [21]
    ('F', 'X', +0.20, 0),   # [22]
    ('E', 'X', -0.45, 0),   # [23]
    ('D', 'X', +0.55, 0),   # [24]
]


def set_count(c, n):
    tail = bytearray(c['TailBytes'])
    tail[3] = n
    c['TailBytes'] = bytes(tail)


def main():
    p = JCNSParser(SRC)
    with contextlib.redirect_stdout(io.StringIO()):
        cons = p.parse()
    assert len(cons) == 8, len(cons)
    tmpl = cons[0]
    for c in cons:
        set_count(c, 0)          # what the writer derived for them in round 4
    for bone, axis, k, count in ENTRIES:
        c = copy.deepcopy(tmpl)
        c['ObjectName'] = 'TestTgt' + bone
        c['Axis_parent'] = c['target_axis'] = AXIS[axis]
        c['AttrFlags'] = 49
        c['TransformElement'] = 1
        set_count(c, count)
        s = c['sources'][0]
        s['SourceName'] = 'L_Thigh'
        s['source_axis'] = 0
        s['InputType'] = 3
        s['AttrFlags'] = 0            # two-point line
        s['from_start'], s['from_kink'], s['from_end'] = -90.0, 0.0, 90.0
        s['to_start'], s['to_kink'], s['to_end'] = -90.0 * k, 0.0, 90.0 * k
        s['ComplexMapping'] = []
        s['ComplexMappingInfoCount'] = 0
        cons.append(c)
    assert cons is p.constraints
    want = [c['TailBytes'][3] for c in cons]
    # The C pair is deliberately left ungrouped, which is still a valid layout, so the
    # writer must keep these counts rather than re-derive them.
    assert tail_group_counts(cons) == want
    JCNSWriter(p, DST).build_lossless()
    q = JCNSParser(DST)
    with contextlib.redirect_stdout(io.StringIO()):
        back = q.parse()
    assert [c['TailBytes'][3] for c in back] == want
    for i, c in enumerate(back):
        s = c['sources'][0]
        k = s['to_end'] / s['from_end'] if s['from_end'] else 0
        print(f"[{i:02}] {c['ObjectName']:<14}.{'XYZW'[c['target_axis']]} <- {s['SourceName']}.{'XYZW'[s['source_axis']]}"
              f"  k={k:+.2f}  group={c['TailBytes'][3]}  F={c['AttrFlags']}")


if __name__ == '__main__':
    main()
