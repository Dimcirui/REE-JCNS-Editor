"""
build_src_id_rig.py -- xaihi test rig, round 7 (2026-09-30): what does each source
+25 (ReadMode) read off a bone?

Round 6 showed +25=3 reads the twist angle of the bone's whole parent-relative
rotation.  Here one controlled source, TestTgtA, turns hard on all three axes
(driven from L_Thigh as in round 6; rest -2 deg X), and every other +25 reads it
through an identity mapping, so each entry's own output (getOutputUserValue) is the
raw value the engine read.  The capture has A's quaternion to test decompositions
against.

  [08]-[10] A.X/Y/Z <- L_Thigh.X * 0.5 / 0.8 / -0.9        (+25=3, as round 6)
  [11]-[22] +25 in (1, 3, 4, 5) x source axis X/Y/Z, reading TestTgtA
  [23]-[25] +25=0 (translation) X/Y/Z of TestTgtA          rest offset in or out?
  [26]      +25=2 (scale) X of TestTgtA                    1 or 0 at rest?

Readers sit on B..K .X then B..G .Y, identity map (-180, 0, 180) -> (-180, 0, 180),
two-point.  Every joint-group count is 0.  The round-4 mesh is reused.
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
READERS = [(T + b, 'X') for b in 'BCDEFGHIJK'] + [(T + b, 'Y') for b in 'BCDEFG']

# (target, target axis, source, source axis, +25, from/to span)
ENTRIES = [
    (T + 'A', 'X', 'L_Thigh', 'X', 3, (90, 45)),
    (T + 'A', 'Y', 'L_Thigh', 'X', 3, (90, 72)),
    (T + 'A', 'Z', 'L_Thigh', 'X', 3, (90, -81)),
]
reads = [(sid, ax) for sid in (1, 3, 4, 5) for ax in 'XYZ']
reads += [(0, ax) for ax in 'XYZ'] + [(2, 'X')]
for (tgt, tax), (sid, sax) in zip(READERS, reads):
    ENTRIES.append((tgt, tax, T + 'A', sax, sid, (180, 180)))
assert len(ENTRIES) == 3 + 16


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
        set_count(c, 0)
    for tgt, tax, src, sax, sid, (span_from, span_to) in ENTRIES:
        c = copy.deepcopy(tmpl)
        c['ObjectName'] = tgt
        c['TransformAxis_parent'] = c['target_axis'] = AXIS[tax]
        c['Flags'] = 49
        c['TransformType'] = 1
        set_count(c, 0)
        s = c['sources'][0]
        s['SourceName'] = src
        s['source_axis'] = AXIS[sax]
        s['ReadMode'] = sid
        s['CurveMode'] = 0            # two-point line
        s['from_start'], s['from_kink'], s['from_end'] = -span_from, 0.0, span_from
        s['to_start'], s['to_kink'], s['to_end'] = -span_to, 0.0, span_to
        s['ComplexMapping'] = []
        s['ComplexMappingInfoCount'] = 0
        cons.append(c)
    assert cons is p.constraints
    assert tail_group_counts(cons) == [0] * len(cons)
    JCNSWriter(p, DST).build_lossless()
    q = JCNSParser(DST)
    with contextlib.redirect_stdout(io.StringIO()):
        back = q.parse()
    assert [c['TailBytes'][3] for c in back] == [0] * len(back)
    for i, c in enumerate(back):
        s = c['sources'][0]
        print(f"[{i:02}] {c['ObjectName']:<14}.{'XYZW'[c['target_axis']]} <- {s['SourceName']}.{'XYZW'[s['source_axis']]}"
              f"  +25={s['ReadMode']}  from=({s['from_start']:g},{s['from_end']:g}) to=({s['to_start']:g},{s['to_end']:g})")


if __name__ == '__main__':
    main()
