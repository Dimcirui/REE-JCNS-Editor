"""Round 19 analysis, for build_rot2_group_rig.py.  Run in reframework/data (or a
roundN_keep copy) after an F8/F9 capture.

For each test bone, builds candidate rotations from its entries' own outputs (Out<i>)
and ranks them against the recorded local quaternion.  The rest rotation is fitted per
candidate (rest = mean of q * cand^-1), so the round-18 mesh needs no known rest.
Candidates: an extrinsic Euler in each of the six RotOrders over the group's axes, and
a single rotation about each written axis alone ("last wins").
"""
import csv
import math

import numpy as np
from scipy.spatial.transform import Rotation as Rot

R = list(csv.DictReader(open('jcns_cm_rig_sweep.csv')))
f = open('jcns_cm_rig_skel.csv')
hdr = f.readline().strip().split(',')
rows = [l.strip().split(',') for l in f]
n = min(len(rows), len(R))
names = [hdr[k][:-3] for k in range(1, len(hdr), 4)]
out = {i: np.array([float(r['Out%d' % i]) for r in R[:n]]) for i in range(8, 22)}
ORDERS = ['xyz', 'yzx', 'zxy', 'zyx', 'yxz', 'xzy']     # via.math.RotationOrder 0..5, X first = 'xyz'


def bone(nm):
    b = 1 + 4 * names.index(nm)
    q = np.array([[float(rows[t][b + c]) for c in range(4)] for t in range(n)])
    return Rot.from_quat(q / np.linalg.norm(q, axis=1, keepdims=True))


def angle(a, b):
    d = (a.inv() * b).magnitude()
    return np.degrees(np.minimum(d, 2 * np.pi - d))


def fit(q, cand):
    rest = (q * cand.inv()).mean()
    return angle(q, rest * cand).max()


def candidates(vals):
    """vals: {axis letter: radians array}."""
    c = {}
    for k, o in enumerate(ORDERS):
        ang = np.vstack([vals.get(a.upper(), np.zeros(n)) for a in o]).T
        c['euler order %d (%s)' % (k, o.upper())] = Rot.from_euler(o, ang)
    for a, v in vals.items():
        c['%s alone' % a] = Rot.from_euler(a.lower(), v[:, None])
    return c


TESTS = [('TestTgtA', {'X': 8, 'Z': 9}, 'group, Tail0=2 -> order 2'),
         ('TestTgtB', {'X': 10, 'Z': 11}, 'group, Tail0=0 -> order 0'),
         ('TestTgtC', {'X': 12, 'Y': 13, 'Z': 14}, 'group, Tail0=5 -> order 5'),
         ('TestTgtD', {'X': 15, 'Y': 16, 'Z': 17}, 'group, Tail0=1 -> order 1'),
         ('TestTgtE', {'X': 18, 'Z': 19}, 'two groups -> Z alone'),
         ('TestTgtF', {'X': 20, 'Z': 21}, 'group, head Tail0=0, member 2')]

print('frames', n, ' input range (deg) %.1f..%.1f' % (math.degrees(out[8].min() / 0.5), math.degrees(out[8].max() / 0.5)))
for nm, idx, expect in TESTS:
    q = bone(nm)
    vals = {a: out[i] for a, i in idx.items()}
    res = sorted((fit(q, r), cname) for cname, r in candidates(vals).items())
    print('%-9s expect: %s' % (nm, expect))
    for e, s in res[:4]:
        print('      %-26s max %.4f deg' % (s, e))
