"""Round 9 analysis, for build_ttype_rig.py.  Run in reframework/data after an
F8/F9 capture.  For each test bone, builds candidate local rotations from its three
entries' outputs and ranks them against the recorded quaternion."""
import csv
import itertools
import math

import numpy as np
from scipy.spatial.transform import Rotation as Rot

R = list(csv.DictReader(open('jcns_cm_rig_sweep.csv')))
f = open('jcns_cm_rig_skel.csv')
hdr = f.readline().strip().split(',')
rows = [l.strip().split(',') for l in f]
n = min(len(rows), len(R))
names = [hdr[k][:-3] for k in range(1, len(hdr), 4)]
out = {i: np.radians([math.degrees(float(r['Out%d' % i])) for r in R[:n]]) for i in range(8, 30)}


def bone(nm):
    b = 1 + 4 * names.index(nm)
    return Rot.from_quat(np.array([[float(rows[t][b + c]) for c in range(4)] for t in range(n)]))


REST = Rot.from_euler('x', -2.0, degrees=True)
Z = np.zeros(n)


def comps(vx, vy, vz):
    """name -> Rotation built from the three channel values (radians)."""
    c = {}
    V = {'X': vx, 'Y': vy, 'Z': vz}
    for order in itertools.permutations('XYZ'):
        # product R_order[0] * R_order[1] * R_order[2]: scipy intrinsic string
        o = ''.join(order)
        c['R%s (matrix product)' % o] = Rot.from_euler(o, np.vstack([V[a] for a in o]).T)
    c['exp(rotvec)'] = Rot.from_rotvec(np.vstack([vx, vy, vz]).T)
    tx = Rot.from_quat(np.vstack([np.sin(vx / 2), Z, Z, np.cos(vx / 2)]).T)
    s = np.vstack([Z, np.tan(vy / 2), np.tan(vz / 2), np.ones(n)]).T
    s /= np.linalg.norm(s, axis=1, keepdims=True)
    sw = Rot.from_quat(s)
    c['swing*twist'] = sw * tx
    c['twist*swing'] = tx * sw
    return c


def angle(a, b):
    d = (a.inv() * b).magnitude()
    return np.degrees(np.minimum(d, 2 * np.pi - d))


def rank(nm, rot_of):
    q = bone(nm)
    res = []
    for cname, r in rot_of.items():
        for tag, full in (('rest*', REST * r), ('*rest', r * REST), ('(no rest)', r)):
            res.append((angle(q, full).max(), '%s %s' % (tag, cname)))
    res.sort()
    return res[:4]


print('frames', n)
for nm, base, lab in (('TestTgtA', 8, 'TT1'), ('TestTgtB', 11, 'TT13'), ('TestTgtC', 14, 'TT14'),
                      ('TestTgtD', 17, 'TT4'), ('TestTgtE', 20, 'TT5'), ('TestTgtF', 23, 'TT6'),
                      ('TestTgtG', 26, 'TT13 F48')):
    vx, vy, vz = out[base], out[base + 1], out[base + 2]
    r = rank(nm, comps(vx, vy, vz))
    print('%-9s %-9s outputs X %.1f..%.1f Y %.1f..%.1f Z %.1f..%.1f' % (
        nm, lab, *[math.degrees(v) for o in (vx, vy, vz) for v in (o.min(), o.max())]))
    for e, s in r:
        print('      %-40s max %.3f deg' % (s, e))
vx = out[29]
r = rank('TestTgtH', {'Rx': Rot.from_rotvec(np.vstack([vx, Z, Z]).T)})
print('TestTgtH  TT13 X only:', ' ; '.join('%s %.3f' % (s, e) for e, s in r))
