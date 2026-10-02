"""
build_axis_bits_rig.py -- xaihi test rig, round 8 (2026-09-30): three raw fields
every earlier round held fixed at the donor's value.

1. Source +27 RotOrder (0 in all rounds so far).  In shipped files it follows the
   source bone (Thigh / Hand 1, fingers 2, wings 3, most others 0), so it looks like
   an axis for the rotation decomposition.  Readers of TestTgtA (turning on all three
   axes, as in round 7) for RotOrder 1..3 x InputType 1/3/4/5 x source axis X/Y/Z.
2. AttrFlags bit0 and AttrFlags bit0 (1 and 0 in all rounds; they agree in 93.5% of
   shipped entries).  Singles on B..E (rest -2 deg X) show whether the value lands on
   the rest pose or replaces it; pairs on F..H show whether two writers of a channel
   still resolve to the last one.
3. Source ref_frame (identity in all rounds; shipped non-identity only as a 90 deg
   turn about Y, on two *_Roll_Val_HJ readers).  Readers of TestTgtA with that
   quaternion, InputType 1/3/4/5 x X/Y/Z.

  [08]-[10]  A.X/Y/Z <- L_Thigh.X * 0.5 / 0.8 / -0.9          (as rounds 6-7)
  [11]-[14]  B/C/D/E.X <- L_Thigh.X * 0.5, (AttrFlags, AttrFlags) = (48,0) (49,0) (48,1) (49,1)
  [15]-[20]  F/G/H.X, two writers each, k +0.3 then -0.6, with (48,0) (49,1) (48,1)
  [21]-[56]  RotOrder in 1..3 x InputType (1,3,4,5) x axis X/Y/Z, reading A
  [57]-[68]  ref_frame = 90 deg about Y, InputType (1,3,4,5) x axis X/Y/Z, reading A

Readers write TestTgtK.Z through an identity map; only their own outputs matter.
Every joint-group count is 0.  The round-4 mesh is reused.  Needs the recorder's
OUT_SCAN_MAX >= 69.
"""
import copy
import io
import contextlib
import math
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
H = math.sqrt(0.5)
ROLL_Y = (0.0, -H, 0.0, H)          # x, y, z, w -- the shipped non-identity value


def E(tgt, tax, src, sax, k, span=90.0, flags=49, curve=0, read=3, unk2=0, rest=(0.0, 0.0, 0.0, 1.0)):
    return dict(tgt=tgt, tax=tax, src=src, sax=sax, k=k, span=span, flags=flags, curve=curve,
                read=read, unk2=unk2, rest=rest)


ENTRIES = [
    E(T + 'A', 'X', 'L_Thigh', 'X', 0.5),
    E(T + 'A', 'Y', 'L_Thigh', 'X', 0.8),
    E(T + 'A', 'Z', 'L_Thigh', 'X', -0.9),
]
for bone, (fl, cm) in zip('BCDE', ((48, 0), (49, 0), (48, 1), (49, 1))):
    ENTRIES.append(E(T + bone, 'X', 'L_Thigh', 'X', 0.5, flags=fl, curve=cm))
for bone, (fl, cm) in zip('FGH', ((48, 0), (49, 1), (48, 1))):
    for k in (0.3, -0.6):
        ENTRIES.append(E(T + bone, 'X', 'L_Thigh', 'X', k, flags=fl, curve=cm))
for unk2 in (1, 2, 3):
    for read in (1, 3, 4, 5):
        for ax in 'XYZ':
            ENTRIES.append(E(T + 'K', 'Z', T + 'A', ax, 1.0, span=180.0, read=read, unk2=unk2))
for read in (1, 3, 4, 5):
    for ax in 'XYZ':
        ENTRIES.append(E(T + 'K', 'Z', T + 'A', ax, 1.0, span=180.0, read=read, rest=ROLL_Y))
assert len(ENTRIES) == 61


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
    for e in ENTRIES:
        c = copy.deepcopy(tmpl)
        c['ObjectName'] = e['tgt']
        c['Axis_parent'] = c['target_axis'] = AXIS[e['tax']]
        c['AttrFlags'] = e['flags']
        c['TransformElement'] = 1
        set_count(c, 0)
        s = c['sources'][0]
        s['SourceName'] = e['src']
        s['source_axis'] = AXIS[e['sax']]
        s['InputType'] = e['read']
        s['AttrFlags'] = e['curve']            # 0 and 1 are both two-point
        s['RotOrder'] = e['unk2']
        s['ref_frame_x'], s['ref_frame_y'], s['ref_frame_z'], s['ref_frame_w'] = e['rest']
        span, k = e['span'], e['k']
        s['from_start'], s['from_kink'], s['from_end'] = -span, 0.0, span
        s['to_start'], s['to_kink'], s['to_end'] = -span * k, 0.0, span * k
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
    for i, (c, e) in enumerate(zip(back[8:], ENTRIES), start=8):
        s = c['sources'][0]
        assert (s['RotOrder'], s['InputType'], s['AttrFlags'], c['AttrFlags']) == (e['unk2'], e['read'], e['curve'], e['flags'])
        assert abs(s['ref_frame_w'] - e['rest'][3]) < 1e-6
    for i, c in enumerate(back):
        s = c['sources'][0]
        print(f"[{i:02}] {c['ObjectName']:<14}.{'XYZW'[c['target_axis']]} <- {s['SourceName']}.{'XYZW'[s['source_axis']]}"
              f"  F={c['AttrFlags']} +24={s['AttrFlags']} +25={s['InputType']} +27={s['RotOrder']}"
              f" rq_w={s['ref_frame_w']:.3f} to_end={s['to_end']:g}")


if __name__ == '__main__':
    main()
