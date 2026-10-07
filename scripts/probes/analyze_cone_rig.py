"""Round 20 analysis, for build_cone_rig.py.  Run in reframework/data (or a
roundN_keep copy) after an F8/F9 capture.

Out8..Out15 are the cone values (MinMax 0..1, linear) -- recorded in metres on these
translation targets, so x100.  Out16..18 are L_Thigh's XYZ Euler (rest included), so
L = Rz * Ry * Rx is the joint's rotation in its parent (Hip) frame.

Model checked (fitted on A/B/C/G with a free axis rotation, validated on D/E/F/H):
    current   = L * Matrix * e_Y          (Matrix: the 3x3 part of the 4x3 field)
    reference = Direction * e_X           (Direction is a quaternion x, y, z, w)
    theta     = angle(current, reference)
    value     = 1 - theta / AngleRad   if theta < AngleRad, else 0
The managed JointRemapValue's (cos t - cos H) / (1 - cos H) is printed for comparison.
"""
import csv
import math
import os
import sys

import numpy as np
from scipy.spatial.transform import Rotation as Rot

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_cone_rig import CONES  # noqa: E402

R = list(csv.DictReader(open('jcns_cm_rig_sweep.csv')))
n = len(R)
out = {i: np.array([float(r['Out%d' % i]) for r in R]) for i in range(8, 19)}
L = Rot.from_euler('xyz', np.vstack([out[16], out[17], out[18]]).T)

print('frames', n, ' L_Thigh euler ranges (deg):',
      ' '.join('%.0f..%.0f' % (math.degrees(out[i].min()), math.degrees(out[i].max())) for i in (16, 17, 18)))
for k, (bone, d, deg, bp, mat) in enumerate(CONES):
    v = out[8 + k] * 100.0
    H = math.radians(deg)
    M = np.array(mat).reshape(3, 4)[:, :3]
    cur = L.apply(np.tile(M @ np.array([0.0, 1.0, 0.0]), (n, 1)))
    ref = Rot.from_quat(d).apply([1.0, 0.0, 0.0])
    t = np.arccos(np.clip(cur @ ref, -1, 1))
    lin = np.where(t < H, 1 - t / H, 0.0)
    cosf = np.clip((np.cos(t) - math.cos(H)) / (1 - math.cos(H)), 0, 1)
    print('%s cone %d  value %.3f..%.3f  theta %.1f..%.1f deg  linear err %.5f  cos-form err %.5f' % (
        bone, k, v.min(), v.max(), math.degrees(t.min()), math.degrees(t.max()),
        np.abs(lin - v).max(), np.abs(cosf - v).max()))
