"""Check the cone formula read from RemapValueItem.Update's disassembly against ConeRemapProbe.cs output.

    python analyze_cone_remap.py <cone_probe_f.csv>

Only the extr/ab rows should match (extrinsic euler offset, q_G * q_P order).
"""
import csv, math, sys, numpy as np, itertools
from scipy.spatial.transform import Rotation as R
rows=list(csv.DictReader(open(sys.argv[1])))
P=lambda s: np.array([float(x) for x in s.split(';')])
ORD=['XYZ','YZX','ZXY','ZYX','YXZ','XZY']   # via.math.RotationOrder names
def offq(o, ordn, variant):
    name=ORD[ordn]
    seq = name if variant=='intr' else name.lower()
    seq2 = name[::-1] if variant=='intr_rev' else None
    if variant=='intr_rev': return R.from_euler(seq2, [o['XYZ'.index(c)] for c in seq2], degrees=True)
    return R.from_euler(seq, [o['XYZ'.index(c.upper())] for c in seq], degrees=True)
def pred(r, variant, mulorder, posfield):
    p=P(r[posfield]); p/=np.linalg.norm(p)
    o=[float(r['ox']),float(r['oy']),float(r['oz'])]
    qo=offq(o,int(r['order']),variant)
    G=R.from_quat(P(r['G_wq'])); Pl=R.from_quat(P(r['P_lq'])); Pb=R.from_quat(P(r['P_blq']))
    m=(lambda a,b:a*b) if mulorder=='ab' else (lambda a,b:b*a)
    ref = m(m(G,Pb),qo) if r['bp']=='1' else m(G,qo)
    cur = m(G,Pl)
    c=ref.apply(p); d=cur.apply(p)
    dot=float(np.clip(c@d,-1,1)); H=math.radians(float(r['half']))
    den=1-math.cos(H); num=1-dot
    return 1-num/den if den>num else 0.0
for variant,mo,pf in itertools.product(['intr','extr','intr_rev'],['ab','ba'],['J_lpos','J_blpos']):
    e=np.array([abs(pred(r,variant,mo,pf)-float(r['v'])) for r in rows])
    print('%-9s %s %s  max %.2e  mean %.2e  n>1e-3: %d/%d'%(variant,mo,pf,e.max(),e.mean(),(e>1e-3).sum(),len(e)))
print('--- offset 0 only, per joint')
z=[r for r in rows if r['ox']=='0' and r['oy']=='0' and r['oz']=='0']
for mo in ['ab','ba']:
    for r in z[::4]:
        print(mo, r['joint'], r['half'], r['bp'], 'pred %.5f eng %s'%(pred(r,'intr',mo,'J_lpos'), r['v']))
