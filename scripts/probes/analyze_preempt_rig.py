"""Round 5 (same-channel preemption) analysis, for build_preempt_rig.py.
Run in reframework/data after an F8/F9 capture.  Result 2026-09-30: the last entry
in the file wins every shared channel, grouped or not."""
import csv, math
R = list(csv.DictReader(open('jcns_cm_rig_sweep.csv')))
O = {i: [math.degrees(float(r['Out%d' % i])) for r in R] for i in range(25)}
f = open('jcns_cm_rig_skel.csv'); hdr = f.readline().strip().split(',')
rows = [l.strip().split(',') for l in f]
n = min(len(rows), len(R))
names = [hdr[k][:-3] for k in range(1, len(hdr), 4)]
print('frames', n)

def ang(nm, c):
    b = 1 + 4 * names.index(nm)
    return [math.degrees(2 * math.atan2(float(rows[t][b + c]), float(rows[t][b + 3]))) for t in range(n)]

K = {8: .20, 9: .30, 10: -.60, 11: .40, 12: -.70, 13: .10, 14: -.50, 15: .15, 16: -.35,
     17: .20, 18: .25, 19: .30, 20: -.50, 21: -.40, 22: .20, 23: -.45, 24: .55}
xs = [[O[i][t] / k for t in range(n)] for i, k in K.items()]
x = [sum(c[t] for c in xs) / len(xs) for t in range(n)]
print('input x %.1f..%.1f   entries agree within %.4f deg' % (
    min(x), max(x), max(abs(c[t] - x[t]) for c in xs for t in range(n))))

def fit(y):
    mx, my = sum(x) / n, sum(y) / n
    sxx = sum((a - mx) ** 2 for a in x)
    s = sum((a - mx) * (b - my) for a, b in zip(x, y)) / sxx
    res = max(abs(b - (my + s * (a - mx))) for a, b in zip(x, y))
    return s, my - s * mx, res

PRED = {  # bone.axis -> writers' k in file order
    'A.X': [.20, -.50], 'B.X': [.30, -.60], 'C.X': [.40, -.70], 'D.X': [.55],
    'E.X': [.10, .25, -.45], 'F.X': [-.50, .20], 'G.X': [.15], 'G.Y': [-.35],
    'J.X': [.20, -.40], 'K.X': [.30], 'H.X': [], 'I.X': []}
for key, ks in PRED.items():
    b, a = key.split('.')
    s, c0, res = fit(ang('TestTgt' + b, 'XYZ'.index(a)))
    cand = {'last': ks[-1] if ks else 0, 'first': ks[0] if ks else 0, 'sum': sum(ks),
            'maxabs': max(ks, key=abs) if ks else 0}
    match = [m for m, v in cand.items() if abs(v - s) < .01]
    print('%-4s slope %+.4f  (res %.3f deg)  writers %s  -> %s' % (key, s, res, ks, match or '?'))
for b in 'ABCDEFGHIJK':
    print('TestTgt' + b, ' '.join('%s[%+.1f,%+.1f]' % (a, min(v), max(v))
          for a, v in ((a, ang('TestTgt' + b, i)) for i, a in enumerate('XYZ'))))
# the dress file's own shared channels: [01]/[03] on L_Dress_HJ_01.Z, [05]/[07] on R
for nm, pair in (('L_Dress_HJ_01', (1, 3)), ('R_Dress_HJ_01', (5, 7))):
    z = ang(nm, 2)
    for i in pair:
        o = O[i][:n]
        mo, mz = sum(o) / n, sum(z) / n
        cov = sum((p - mo) * (q - mz) for p, q in zip(o, z))
        r = cov / math.sqrt(sum((p - mo) ** 2 for p in o) * sum((q - mz) ** 2 for q in z) or 1)
        print('%s.Z vs Out%d: corr %+.3f, Out range %.1f..%.1f, bone range %.1f..%.1f' % (
            nm, i, r, min(o), max(o), min(z), max(z)))
