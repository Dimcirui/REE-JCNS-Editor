"""
build_cone_rig.py -- xaihi test rig, round 20 (2026-10-07): does Wilds evaluate
ConeInput / ConeDriver, and with what formula?

Shipped Wilds files never use cones, but the native evaluator has the code
(docs/engine-names.md section 4): per ConeInput an angle between an axis of the
joint's current rotation and the same axis of parent * [rest] * cone orientation,
then 1 - angle / AngleRad.  Cones follow RE9's v35 convention: Direction is a
quaternion (x, y, z, w), Matrix identity, Tail 06 06 00 {BasePose}.

Every cone has Joint L_Thigh, Parent Hip.  Each cone-only entry drives
TestTgt<A..H>.X (translation) with one ConeDriver: MinMax, linear, OutMin 0,
OutMax 1, so Out<i> is the cone value itself.

  [08] A  cone 0  Direction identity        AngleRad 90 deg
  [09] B  cone 1  Direction Rz(-90)         90 deg   (RE9 L_Arm_HandDown's value)
  [10] C  cone 2  Direction Ry(+90)         90 deg
  [11] D  cone 3  Direction Rx(45)          90 deg   (a twist about X: does X count?)
  [12] E  cone 4  Direction identity        45 deg
  [13] F  cone 5  Direction identity        90 deg   BasePose bit set
  [14] G  cone 6  Direction Ry(20)*Rz(-30)  120 deg
  [15] H  cone 7  Direction identity        90 deg   Matrix diag(1,-1,-1)
  [16]-[18] TestTgtJ.X/Y/Z  type 1 <- L_Thigh euler X/Y/Z (InputType 1, XYZ), gain 1:
            the joint's local rotation, rest included, to fit the cone formula against.
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
sys.path.insert(0, os.path.join(HERE, "..", "..", "modules", "hashing"))
from mmh3.pymmh3 import hashUTF16

DIR = r"E:/Program/Steam/steamapps/common/MonsterHunterWilds/natives/STM/art/model/character/ch03/xaihi"
SRC = DIR + "/xaihi_constraint.jcns.102.orig_20260929"
DST = DIR + "/xaihi_constraint.jcns.102"

IDENT = (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0)
MIRROR = (1.0, 0.0, 0.0, 0.0, 0.0, -1.0, 0.0, 0.0, 0.0, 0.0, -1.0, 0.0)


def q_axis(axis, deg):
    h = math.radians(deg) / 2
    v = [0.0, 0.0, 0.0]
    v[axis] = math.sin(h)
    return (v[0], v[1], v[2], math.cos(h))       # x, y, z, w


def q_mul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
            aw * bw - ax * bx - ay * by - az * bz)


ID_Q = (0.0, 0.0, 0.0, 1.0)
# (test bone, Direction quaternion, AngleRad degrees, BasePose, Matrix)
CONES = [('A', ID_Q, 90, 0, IDENT),
         ('B', q_axis(2, -90), 90, 0, IDENT),
         ('C', q_axis(1, 90), 90, 0, IDENT),
         ('D', q_axis(0, 45), 90, 0, IDENT),
         ('E', ID_Q, 45, 0, IDENT),
         ('F', ID_Q, 90, 1, IDENT),
         ('G', q_mul(q_axis(1, 20), q_axis(2, -30)), 120, 0, IDENT),
         ('H', ID_Q, 90, 0, MIRROR)]


def set_tail(c, i, v):
    tail = bytearray(c['TailBytes'])
    tail[i] = v
    c['TailBytes'] = bytes(tail)


def main():
    p = JCNSParser(SRC)
    with contextlib.redirect_stdout(io.StringIO()):
        cons = p.parse()
    assert len(cons) == 8, len(cons)
    assert not p.cone_inputs
    tmpl = cons[0]
    for c in cons:
        set_tail(c, 3, 0)
    thigh, hip = hashUTF16('L_Thigh') & 0xFFFFFFFF, hashUTF16('Hip') & 0xFFFFFFFF
    for k, (bone, direction, deg, bp, matrix) in enumerate(CONES):
        p.cone_inputs.append({
            'Name': 'TestCone%s_cdr' % bone, 'Direction': direction, 'Matrix': matrix,
            'JointHash': thigh, 'ParentJointHash': hip, 'SymmetryJointHash': None,
            'AngleRad': math.radians(deg), 'UnknownUInt32': 0,
            'Tail': bytes([6, 6, 0, bp, 0, 0, 0, 0])})
        c = copy.deepcopy(tmpl)
        c['ObjectName'] = 'TestTgt' + bone
        c['Axis_parent'] = c['target_axis'] = 0
        c['TransformElement'] = 0
        c['AttrFlags'] = 17
        c['sources'] = []
        c['ConeDriver'] = [{'CurveData': bytes(12), 'OutMin': 0.0, 'OutMax': 1.0, 'Interpolation': 0,
                            'ConeInputIndex': k, 'CurveType': 0, 'ReservedByte': 0}]
        cons.append(c)
    for ax in range(3):
        c = copy.deepcopy(tmpl)
        c['ObjectName'] = 'TestTgtJ'
        c['Axis_parent'] = c['target_axis'] = ax
        c['TransformElement'] = 1
        c['AttrFlags'] = 49
        c['sources'] = [c['sources'][0]]
        s = c['sources'][0]
        s['SourceName'] = 'L_Thigh'
        s['source_axis'] = ax
        s['InputType'] = 1
        s['AttrFlags'] = 0
        s['RotOrder'] = 0
        s['from_start'], s['from_kink'], s['from_end'] = -180.0, 0.0, 180.0
        s['to_start'], s['to_kink'], s['to_end'] = -180.0, 0.0, 180.0
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
    assert len(q.cone_inputs) == len(CONES)
    for k, cd in enumerate(q.cone_inputs):
        print('cone %d %-16s dir=%s ang=%.1f tail=%s joint=%d parent=%d' % (
            k, cd['Name'], tuple(round(x, 4) for x in cd['Direction']), math.degrees(cd['AngleRad']),
            bytes(cd['Tail']).hex(), cd['JointHashIndex'], cd['ParentJointHashIndex']))
    for i, c in enumerate(back):
        srcs = ', '.join('%s.%s' % (s['SourceName'], 'XYZ'[s['source_axis']]) for s in c['sources'])
        cones = [d['ConeInputIndex'] for d in c.get('ConeDriver') or []]
        print(f"[{i:02}] {c['ObjectName']:<14}.{'XYZW'[c['target_axis']]}  TT={c['TransformElement']:<2} F={c['AttrFlags']}"
              f"  <- {srcs or '-'} cones={cones}")


if __name__ == '__main__':
    main()
