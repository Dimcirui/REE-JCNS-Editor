import csv, collections, math, struct
def h(x): return struct.unpack('<e', struct.pack('<e', x))[0]
rows = collections.defaultdict(list)
# Output of JcnsCurveProbe.cs (a REFramework.NET plugin; drop it in reframework/plugins/source/).
CSV = 'E:/Program/Steam/steamapps/common/MonsterHunterWilds/reframework/data/jcns_curve_probe.csv'
for r in csv.DictReader(open(CSV)):
    y = float(r['y'])
    if not math.isnan(y): rows[(r['curve'], r['variant'])].append((float(r['x']), y))
exec(open(__import__('os').path.join(__import__('os').path.dirname(__file__), 'curves.lua')).read().replace('local CURVES =', 'CURVES =').replace('{name=', 'dict(name=').replace(', file=', ', file=').replace('keys={', 'keys=[').replace('  }},', '  ]),').replace('    {', '    [').replace('},\n', '],\n').replace('--', '#').replace('CURVES = {', 'CURVES = [').rstrip().rstrip('}') + ']')
K = {c['name']: [[h(k[0]), k[1], h(k[2]), h(k[3]), h(k[4]), h(k[5]), k[6]] for k in c['keys']] for c in CURVES}
def seg(keys, x):
    for a, b in zip(keys, keys[1:]):
        if a[0] <= x < b[0]: return a, b
    return None
def m_lin(keys, x):
    s = seg(keys, x)
    if not s: return None
    a, b = s; return a[1] + (b[1]-a[1])*(x-a[0])/(b[0]-a[0])
def m_const(keys, x):
    s = seg(keys, x); return s[0][1] if s else None
def m_bez(scale, flat=False):
    def f(keys, x):
        s = seg(keys, x)
        if not s: return None
        a, b = s
        oy = 0 if flat else a[5]; iy = 0 if flat else b[3]
        ox = a[4] if a[4] else (b[0]-a[0]); ix = b[2] if b[2] else (b[0]-a[0])
        p = [(a[0], a[1]), (a[0]+ox/scale, a[1]+oy/scale), (b[0]-ix/scale, b[1]-iy/scale), (b[0], b[1])]
        B = lambda t, i: (1-t)**3*p[0][i]+3*(1-t)**2*t*p[1][i]+3*(1-t)*t*t*p[2][i]+t**3*p[3][i]
        lo, hi = 0., 1.
        for _ in range(60):
            m = (lo+hi)/2
            if B(m, 0) < x: lo = m
            else: hi = m
        return B((lo+hi)/2, 1)
    return f
def m_herm_slope(keys, x):   # cubic hermite, tangent slope = y/x of normal, param t in [0,1]
    s = seg(keys, x)
    if not s: return None
    a, b = s; d = b[0]-a[0]; t = (x-a[0])/d
    m0 = a[5]/a[4]*d if a[4] else 0; m1 = b[3]/b[2]*d if b[2] else 0
    return (2*t**3-3*t*t+1)*a[1] + (t**3-2*t*t+t)*m0 + (-2*t**3+3*t*t)*b[1] + (t**3-t*t)*m1
MODELS = {'linear': m_lin, 'const': m_const, 'bez/3': m_bez(3), 'bez/1': m_bez(1), 'flat': m_bez(3, True), 'hermslope': m_herm_slope}
for (name, var), pts in sorted(rows.items()):
    keys = K[name]
    inside = [(x, y) for x, y in pts if keys[0][0] <= x < keys[-1][0]]
    errs = {}
    for mn, mf in MODELS.items():
        e = [abs(y - mf(keys, x)) for x, y in inside if mf(keys, x) is not None]
        errs[mn] = max(e) if e else float('nan')
    best = min(errs, key=errs.get)
    rng = max(abs(k[1]) for k in keys) or 1
    left = [y for x, y in pts if x < keys[0][0]][:1]; right = [y for x, y in pts if x >= keys[-1][0]][-1:]
    print('%-8s %-15s best=%-9s err=%.3g (%.1f%% of range)  | %s | outside L=%s R=%s' % (name, var, best, errs[best], 100*errs[best]/rng,
          ' '.join('%s:%.2g' % (k, v) for k, v in errs.items()), left, right))
