"""Round 6 analysis, for build_order_chain_rig.py.  Run in reframework/data after an
F8/F9 capture."""
import csv
import itertools
import math

R = list(csv.DictReader(open('jcns_cm_rig_sweep.csv')))
O = {i: [math.degrees(float(r['Out%d' % i])) for r in R] for i in range(21)}
f = open('jcns_cm_rig_skel.csv')
hdr = f.readline().strip().split(',')
rows = [l.strip().split(',') for l in f]
n = min(len(rows), len(R))
names = [hdr[k][:-3] for k in range(1, len(hdr), 4)]
print('frames', n)


def quat(nm, t):
    b = 1 + 4 * names.index(nm)
    x, y, z, w = (float(rows[t][b + c]) for c in range(4))
    return (w, x, y, z)


def mul(a, b):
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return (aw * bw - ax * bx - ay * by - az * bz, aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx, aw * bz + ax * by - ay * bx + az * bw)


def inv(q):
    return (q[0], -q[1], -q[2], -q[3])


def axis_q(axis, deg):
    h = math.radians(deg) / 2
    v = [0.0, 0.0, 0.0]
    v[axis] = math.sin(h)
    return (math.cos(h), *v)


def qangle(a, b):
    d = abs(sum(p * q for p, q in zip(a, b)))
    return math.degrees(2 * math.acos(min(1.0, d)))


# ---- 1. composition order --------------------------------------------------------
x = [O[8][t] / 0.5 for t in range(n)]
print('input x %.1f..%.1f' % (min(x), max(x)))
for bone, outs in (('A', {0: 8, 1: 9, 2: 10}), ('B', {1: 11, 2: 12}), ('C', {0: 15, 1: 14, 2: 13})):
    nm = 'TestTgt' + bone
    t0 = min(range(n), key=lambda t: abs(x[t]))          # frame nearest the rest pose
    res = []
    for perm in itertools.permutations(range(3)):
        # q = rest * R(perm[0]) * R(perm[1]) * R(perm[2]); perm[2] acts on the vector first
        def rot(t):
            m = (1.0, 0.0, 0.0, 0.0)
            for a in perm:
                m = mul(m, axis_q(a, O[outs[a]][t] if a in outs else 0.0))
            return m
        rest = mul(quat(nm, t0), inv(rot(t0)))
        err = max(qangle(quat(nm, t), mul(rest, rot(t))) for t in range(n))
        res.append((err, ''.join('XYZ'[a] for a in perm)))
    res.sort()
    print('%s: q = rest*R..*R..*R.. (right-most first)  ' % nm + '  '.join('%s %.3f' % (p, e) for e, p in res))
    print('    angle ranges', {('XYZ'[a]): (round(min(O[o]), 1), round(max(O[o]), 1)) for a, o in outs.items()})


# ---- 2. driven sources --------------------------------------------------------------
def fit(xs, ys):
    m = len(xs)
    mx, my = sum(xs) / m, sum(ys) / m
    sxx = sum((a - mx) ** 2 for a in xs) or 1e-12
    s = sum((a - mx) * (b - my) for a, b in zip(xs, ys)) / sxx
    return s, my - s * mx, max(abs(b - (my + s * (a - mx))) for a, b in zip(xs, ys))


def bone_x(nm):
    return [math.degrees(2 * math.atan2(quat(nm, t)[1], quat(nm, t)[0])) for t in range(n)]


def show(label, out, src, k):
    y = O[out][1:n]
    for tag, xs in (('same frame', src[1:n]), ('prev frame', src[0:n - 1])):
        s, b, e = fit(xs, y)
        print('  %-28s vs %-10s slope %+.4f (want %+.2f) icpt %+.3f  max res %.3f' % (label, tag, s, k, b, e))


print('D.X output Out17 range %.1f..%.1f' % (min(O[17]), max(O[17])))
for nm in ('TestTgtD', 'TestTgtE', 'TestTgtA'):
    s, b, e = fit(O[{'TestTgtD': 17, 'TestTgtE': 18, 'TestTgtA': 8}[nm]], bone_x(nm))
    print('  %s bone X vs its own output: slope %+.4f icpt %+.3f res %.3f' % (nm, s, b, e))
show('E [18] <- D, after D', 18, O[17], 0.6)
show('F [16] <- D, before D', 16, O[17], 0.6)
show('G [19] <- E', 19, O[18], -0.7)
show('H [20] <- A.X (A turns YZ)', 20, O[8], 0.5)
show('H [20] <- A bone X angle', 20, bone_x('TestTgtA'), 0.5)
for nm in ('TestTgtE', 'TestTgtF', 'TestTgtG', 'TestTgtH'):
    out = {'TestTgtE': 18, 'TestTgtF': 16, 'TestTgtG': 19, 'TestTgtH': 20}[nm]
    s, b, e = fit(O[out], bone_x(nm))
    print('  %s bone X vs Out%d: slope %+.4f icpt %+.3f res %.3f' % (nm, out, s, b, e))
