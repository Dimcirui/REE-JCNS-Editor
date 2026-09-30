"""Round 7 analysis, for build_src_id_rig.py.  Run in reframework/data after an
F8/F9 capture.  Each reader entry's output is the raw value the engine read off
TestTgtA; this ranks candidate decompositions of A's recorded quaternion against it."""
import csv
import math

import numpy as np
from scipy.spatial.transform import Rotation

R = list(csv.DictReader(open('jcns_cm_rig_sweep.csv')))
f = open('jcns_cm_rig_skel.csv')
hdr = f.readline().strip().split(',')
rows = [l.strip().split(',') for l in f]
n = min(len(rows), len(R))
names = [hdr[k][:-3] for k in range(1, len(hdr), 4)]
out = {i: np.array([math.degrees(float(r['Out%d' % i])) for r in R[:n]]) for i in range(8, 27)}
b = 1 + 4 * names.index('TestTgtA')
q = np.array([[float(rows[t][b + c]) for c in range(4)] for t in range(n)])   # x y z w
full = Rotation.from_quat(q)
rest = Rotation.from_euler('x', -2.0, degrees=True)        # A's rest, round 6
rel = rest.inv() * full
print('frames', n, ' A euler outputs X %.1f..%.1f Y %.1f..%.1f Z %.1f..%.1f' % tuple(
    v for i in (8, 9, 10) for v in (out[i].min(), out[i].max())))


def twist(rot, a):
    qq = rot.as_quat()
    qq = np.where(qq[:, 3:4] < 0, -qq, qq)
    return np.degrees(2 * np.arctan2(qq[:, a], qq[:, 3]))


def candidates(a):
    c = {}
    for tag, rot in (('full', full), ('rel', rel)):
        c['twist/' + tag] = twist(rot, a)
        for order in ('XYZ', 'XZY', 'YXZ', 'YZX', 'ZXY', 'ZYX', 'xyz', 'xzy', 'yxz', 'yzx', 'zxy', 'zyx'):
            e = rot.as_euler(order, degrees=True)
            c['euler %s/%s' % (order, tag)] = e[:, order.lower().index('xyz'[a])]
        qq = rot.as_quat()
        qq = np.where(qq[:, 3:4] < 0, -qq, qq)
        c['2asin(q)/' + tag] = np.degrees(2 * np.arcsin(np.clip(qq[:, a], -1, 1)))
        c['rotvec/' + tag] = np.degrees(rot.as_rotvec()[:, a])
        m = rot.as_matrix()
        # angle of the bone's other axes projected: e.g. X from the Y axis' tilt in YZ
        c['swing-proj/' + tag] = np.degrees(np.arctan2(m[:, (a + 2) % 3, (a + 1) % 3],
                                                       m[:, (a + 1) % 3, (a + 1) % 3]))
    c['A output (driven euler)'] = out[8 + a]
    return c


READS = [(sid, ax) for sid in (1, 3, 4, 5) for ax in range(3)]
for k, (sid, a) in enumerate(READS):
    y = out[11 + k]
    rank = []
    for name, x in candidates(a).items():
        d = y - x
        rank.append((np.abs(d - 0).max(), name))
    rank.sort()
    print('[%d] +25=%d %s  range %.1f..%.1f   best: %s' % (
        11 + k, sid, 'XYZ'[a], y.min(), y.max(),
        '; '.join('%s %.3f' % (nm, e) for e, nm in rank[:4])))
for k, lab in ((23, '+25=0 X'), (24, '+25=0 Y'), (25, '+25=0 Z'), (26, '+25=2 X')):
    y = out[k]
    print('[%d] %s  range %.4f..%.4f' % (k, lab, y.min(), y.max()))
