"""
analyze_parent_rig.py -- round 18 (build_parent_rig.py): a translation on a child of a scaled parent.

    python scripts/probes/analyze_parent_rig.py --data <round18_keep> --plan <round18_plan.json>
    python scripts/probes/analyze_parent_rig.py --self-test

For every child (K under E, J under G, I under F, baseline H under the unscaled Ear_SCL) and axis: the
slope of the recorded local position against the entry output (Out is in centimetres, positions in
metres, so an unscaled parent gives 0.01), and the same for the world offset to the parent taken in
the parent's frame.  The per-axis ratio to 0.01 is compared with 1 (written in the scaled local frame),
1/scale (written as a world length along the parent's axes) and scale.
"""
import argparse
import json
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation as Rot

from analyze_sections_rig import ang, load, pos_cols, quat_cols

OUT = {'K': 9, 'J': 12, 'I': 15, 'H': 18}
PARENT = {'K': 'E', 'J': 'G', 'I': 'F', 'H': None}
STRIDE = 3


def slope_through_zero(x, y):
    """Least-squares slope of y = s * x + c."""
    A = np.c_[x, np.ones(len(x))]
    sol = np.linalg.lstsq(A, y, rcond=None)[0]
    return float(sol[0]), float(np.abs(A @ sol - y).max())


def analyze(F, plan, stride=STRIDE):
    S, T, W = F['sweep'], F['trs'], F['world']
    sl = slice(None, None, stride)
    x = np.degrees(np.asarray(S['Out8'], float) / 0.5)
    if np.ptp(x) < 30:
        raise ValueError(f'input span {np.ptp(x):.1f} deg < 30')
    for i in range(9, 21):
        if np.abs(S[f'Out{i}']).max() < 1e-9:
            raise ValueError(f'Out{i} is all zero: the game still has another round loaded (restart it fully)')
    rests = plan['rests']
    res = dict(sanity=dict(frames=len(x), input_span_deg=float(np.ptp(x))), children={})
    for child, first in OUT.items():
        parent = PARENT[child]
        parent_name = 'Ear_SCL' if parent is None else 'TestTgt' + parent
        scale = np.array(rests[parent]['scale']) if parent else np.ones(3)
        local = np.stack([np.asarray(T[f'TestTgt{child}_p{a}'], float) for a in 'xyz'], axis=1)[sl]
        delta = local - np.array(rests[child]['position_m'])
        pc = pos_cols(W, f'e.TestTgt{child}')[sl]
        pp = pos_cols(W, 'e.Ear_SCL' if parent is None else f'e.TestTgt{parent}')[sl]
        rp = quat_cols(W, 'e.Ear_SCL' if parent is None else f'e.TestTgt{parent}')[sl]
        wd = rp.inv().apply(pc - pp)
        wd = wd - wd[np.argmin(np.abs(x[sl]))]
        entry = {}
        for k, a in enumerate('XYZ'):
            out = np.asarray(S[f'Out{first + k}'], float)[sl]
            s_loc, r_loc = slope_through_zero(out, delta[:, k])
            s_wld, r_wld = slope_through_zero(out, wd[:, k])
            entry[a] = dict(parent_scale=float(scale[k]), local_slope_over_0p01=s_loc / 0.01, local_resid_m=r_loc,
                            world_slope_over_0p01=s_wld / 0.01, world_resid_m=r_wld,
                            candidates={'1 (scaled local frame)': 1.0, '1/scale (world length)': 1.0 / scale[k],
                                        'scale': float(scale[k])})
        res['children'][f'{child} under {parent_name}'] = entry
    return res


def synthetic(truth, n=700):
    t = np.arange(n, dtype=float)
    x = np.radians(65) * np.sin(t / 41.0) - np.radians(25)
    xd = np.degrees(x)
    S, T, W = ({'Frame': t.copy()} for _ in range(3))
    S['Out8'] = 0.5 * x
    plan = {'rests': {}}
    scales = {'E': (1.4, 0.7, 1.8), 'G': (1.4, 0.7, 1.8), 'F': (1.4, -0.7, 1.8)}
    gains = (0.03, 0.05, -0.04)
    for c in 'ABCDEFGHIJK':
        plan['rests'][c] = dict(position_m=[0.0, -0.5955, 0.0134], scale=list(scales.get(c, (1, 1, 1))))
    ident = np.tile([0, 0, 0, 1.0], (n, 1))

    def setw(b, p, q=ident):
        for k, a in enumerate('xyz'):
            W[f'e.{b}_p{a}'] = p[:, k]
        for k, a in enumerate('xyzw'):
            W[f'e.{b}_q{a}'] = q[:, k]

    base = np.array([5.0, 3.0, 2.0])
    setw('Ear_SCL', np.tile(base, (n, 1)))
    for c, parent in (('K', 'E'), ('J', 'G'), ('I', 'F'), ('H', None)):
        sc = np.array(scales[parent]) if parent else np.ones(3)
        pp = np.tile(base, (n, 1))
        if parent:
            setw('TestTgt' + parent, pp)
        first = OUT[c]
        delta = np.zeros((n, 3))
        for k in range(3):
            out = gains[k] * xd
            S[f'Out{first + k}'] = out
            delta[:, k] = 0.01 * out * truth(sc[k])
        rest = np.array(plan['rests'][c]['position_m'])
        for k, a in enumerate('xyz'):
            T[f'TestTgt{c}_p{a}'] = rest[k] + delta[:, k]
        setw('TestTgt' + c, pp + (rest + delta) * sc)
    return dict(sweep=S, trs=T, world=W, skel={'Frame': t.copy()}), plan


def self_test():
    for name, truth in (('scaled local frame', lambda s: 1.0), ('world length', lambda s: 1.0 / s)):
        F, plan = synthetic(truth)
        res = analyze(F, plan)
        for child, entry in res['children'].items():
            for a in 'XYZ':
                e = entry[a]
                want = 1.0 if name.startswith('scaled') else 1.0 / e['parent_scale']
                assert abs(e['local_slope_over_0p01'] - want) < 1e-6, (name, child, a, e)
    print('self-test OK')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', type=Path)
    ap.add_argument('--plan', type=Path)
    ap.add_argument('--json', type=Path)
    ap.add_argument('--self-test', action='store_true')
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    res = analyze(load(a.data), json.loads(a.plan.read_text(encoding='utf-8')))
    text = json.dumps(res, indent=1, ensure_ascii=False)
    if a.json:
        a.json.write_text(text, encoding='utf-8')
    print(text)


if __name__ == '__main__':
    main()
