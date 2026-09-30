"""Round 8 analysis, for build_axis_bits_rig.py.  Run in reframework/data after an
F8/F9 capture."""
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
out = {i: np.array([math.degrees(float(r['Out%d' % i])) for r in R[:n]]) for i in range(8, 69)}


def bone(nm):
    b = 1 + 4 * names.index(nm)
    q = np.array([[float(rows[t][b + c]) for c in range(4)] for t in range(n)])
    return Rot.from_quat(q)


def qa(rot):
    q = rot.as_quat()
    return np.where(q[:, 3:4] < 0, -q, q)


def twist_about(rot, a):
    q = qa(rot)
    t = np.zeros_like(q)
    t[:, a] = q[:, a]
    t[:, 3] = q[:, 3]
    t /= np.linalg.norm(t, axis=1, keepdims=True)
    return Rot.from_quat(t)


def decomps(rot):
    """name -> (3 components) for every decomposition tried."""
    d = {}
    for order in ('XYZ', 'XZY', 'YXZ', 'YZX', 'ZXY', 'ZYX', 'xyz', 'xzy', 'yxz', 'yzx', 'zxy', 'zyx'):
        e = rot.as_euler(order, degrees=True)
        d['euler ' + order] = [e[:, order.lower().index(c)] for c in 'xyz']
    for a in range(3):
        tw = twist_about(rot, a)
        for side in ('s*t', 't*s'):
            sw = rot * tw.inv() if side == 's*t' else tw.inv() * rot
            tq, sq = qa(tw), qa(sw)
            comps = []
            for c in range(3):
                src = tq if c == a else sq
                comps.append(np.degrees(2 * np.arctan2(src[:, c], src[:, 3])))
            d['swing-twist %s twist=%s' % (side, 'XYZ'[a])] = comps
    rv = np.degrees(rot.as_rotvec())
    d['rotvec'] = [rv[:, c] for c in range(3)]
    return d


A = bone('TestTgtA')
REST = Rot.from_euler('x', -2.0, degrees=True)
FRAMES = {'id': Rot.identity()}
for ax in 'xyz':
    for ang in (90, -90, 180):
        FRAMES['%s%+d' % (ax, ang)] = Rot.from_euler(ax, ang, degrees=True)
ROLL = Rot.from_quat([0.0, -math.sqrt(0.5), 0.0, math.sqrt(0.5)])
CAND = {}
for fname, fr in FRAMES.items():
    for tag, rot in (('conj ' + fname, fr.inv() * A * fr), ('L ' + fname, fr.inv() * A), ('R ' + fname, A * fr)):
        if fname == 'id' and not tag.startswith('conj'):
            continue
        for dn, comps in decomps(rot).items():
            CAND[(tag, dn)] = comps
for tag, rot in (('rq*A', ROLL * A), ('A*rq', A * ROLL), ('rq^-1*A', ROLL.inv() * A), ('A*rq^-1', A * ROLL.inv()),
                 ('rq^-1*A*rq', ROLL.inv() * A * ROLL), ('rq*A*rq^-1', ROLL * A * ROLL.inv()),
                 ('rest-rel', REST.inv() * A)):
    for dn, comps in decomps(rot).items():
        CAND[(tag, dn)] = comps


def best(y, k=3):
    """Closest candidates; at equal error (0.01 deg) the simplest reading wins:
    no frame, then no sign flip -- 180 deg frames only alias sign flips."""
    res = []
    for key, comps in CAND.items():
        for c in range(3):
            for sgn in (1, -1):
                e = np.abs(y - sgn * comps[c]).max()
                cost = (key[0] != 'conj id') * 2 + (sgn < 0)
                res.append((round(e, 2), cost, e, '%s%s | %s [%s]' % ('-' if sgn < 0 else '', key[0], key[1], 'XYZ'[c])))
    res.sort()
    return [(e, s) for _r, _c, e, s in res[:k]]


print('frames', n)
print('== 1. UnkByte2 readers (ReadMode x axis)')
i = 21
for unk2 in (1, 2, 3):
    for read in (1, 3, 4, 5):
        for ax in 'XYZ':
            b = best(out[i])
            print('[%d] +27=%d +25=%d %s  range %7.1f..%6.1f | %s' % (
                i, unk2, read, ax, out[i].min(), out[i].max(), ' ; '.join('%s %.3f' % (s, e) for e, s in b)))
            i += 1
print('== 3. rest_quat readers')
for read in (1, 3, 4, 5):
    for ax in 'XYZ':
        b = best(out[i])
        print('[%d] rq=90Y +25=%d %s range %7.1f..%6.1f | %s' % (
            i, read, ax, out[i].min(), out[i].max(), ' ; '.join('%s %.3f' % (s, e) for e, s in b)))
        i += 1


def fit(x, y):
    A_ = np.vstack([x, np.ones_like(x)]).T
    (s, c), *_ = np.linalg.lstsq(A_, y, rcond=None)
    return s, c, np.abs(y - (s * x + c)).max()


def bone_x(nm):
    q = qa(bone(nm))
    return np.degrees(2 * np.arctan2(q[:, 0], q[:, 3]))


print('== 2. Flags bit0 / CurveMode bit0 on the pose (bone X vs output; rest is -2 deg)')
for nm, o, lab in (('TestTgtB', 11, 'F48 CM0'), ('TestTgtC', 12, 'F49 CM0'), ('TestTgtD', 13, 'F48 CM1'), ('TestTgtE', 14, 'F49 CM1')):
    s, c, e = fit(out[o], bone_x(nm))
    print('  %s %s: bone X = %.4f * Out%d %+.3f  (res %.3f)   Out range %.1f..%.1f' % (nm, lab, s, o, c, e, out[o].min(), out[o].max()))
for nm, (o1, o2), lab in (('TestTgtF', (15, 16), 'F48 CM0'), ('TestTgtG', (17, 18), 'F49 CM1'), ('TestTgtH', (19, 20), 'F48 CM1')):
    y = bone_x(nm)
    for tag, x in (('first', out[o1]), ('second', out[o2]), ('sum', out[o1] + out[o2])):
        s, c, e = fit(x, y)
        print('  %s %s vs %-6s: slope %.4f icpt %+.3f res %.3f' % (nm, lab, tag, s, c, e))
