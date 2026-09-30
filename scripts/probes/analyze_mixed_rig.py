"""
analyze_mixed_rig.py -- round 15 (build_mixed_rig.py).

    python scripts/probes/analyze_mixed_rig.py --data <round15_keep> --plan <round11_plan.json>
    python scripts/probes/analyze_mixed_rig.py --self-test

B..F: a bone with entries of type 1 (Euler) and type 4 (swing-twist) on X, Y, Z.  Each bone's
recorded rotation is ranked between "all Euler" (rest * R(x, y, z)) and "all swing-twist"; the
winner says which type composed the whole bone, and the hypotheses (first entry decides, last
entry decides, majority, Euler if any entry is Euler) are then checked against all five bones plus
round 13's (1, 4, 1) bone, which came out Euler.
G..K: a type 1 X entry with an unknown byte changed, compared with control A.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation as Rot

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / 'modules'))
import jcns_source_read as R                                   # noqa: E402
from analyze_rules_rig import rot_seq, wxyz_to_rot            # noqa: E402
from analyze_sections_rig import ang, load, quat_cols, report_rank   # noqa: E402

MIXED = {'B': (4, 1, 4), 'C': (4, 4, 1), 'D': (4, 1, 1), 'E': (1, 4, 4), 'F': (1, 1, 4)}
MIXED_OUT = {'B': 9, 'C': 12, 'D': 15, 'E': 18, 'F': 21}
UNKNOWN_OUT = {'G': 24, 'H': 25, 'I': 26, 'J': 27, 'K': 28}
KNOWN = {(1, 4, 1): 'euler'}                                    # round 13
HYPOTHESES = {
    'first entry decides': lambda t: 'euler' if t[0] == 1 else 'swing_twist',
    'last entry decides': lambda t: 'euler' if t[-1] == 1 else 'swing_twist',
    'majority decides': lambda t: 'euler' if t.count(1) > t.count(4) else 'swing_twist',
    'Euler if any entry is Euler': lambda t: 'euler' if 1 in t else 'swing_twist',
    'swing-twist if any entry is type 4': lambda t: 'swing_twist' if 4 in t else 'euler',
}
STRIDE = 3


def analyze(F, rests, stride=STRIDE):
    S, K = F['sweep'], F['skel']
    sl = slice(None, None, stride)
    out = lambda i: np.asarray(S[f'Out{i}'], float)[sl]
    q = lambda b: quat_cols(K, f'TestTgt{b}')[sl]
    rest = lambda b: tuple(rests[b])
    res = {}
    x = np.asarray(S['Out8'], float) / 0.5
    span = float(np.degrees(np.ptp(x)))
    if span < 30:
        raise ValueError(f'input span {span:.1f} deg < 30')
    a_out = out(8)
    a_rq = wxyz_to_rot([rest('A')] * len(a_out))
    ctrl = float(ang(q('A'), a_rq * Rot.from_euler('x', a_out[:, None])).max())
    res['sanity'] = dict(frames=len(x), input_span_deg=span, control_A_err_deg=ctrl)
    for i in range(9, 29):
        if np.abs(S[f'Out{i}']).max() < 1e-9:
            raise ValueError(f'Out{i} is all zero: the game still has another round loaded (restart it fully)')

    verdict = {}
    res['mixed_types'] = {}
    for b, types in MIXED.items():
        vx, vy, vz = (out(MIXED_OUT[b] + k) for k in range(3))
        rq = wxyz_to_rot([rest(b)] * len(vx))
        cands = {
            'euler': rq * rot_seq(lambda a, c, d: R.from_euler_xyz((a, c, d)), vx, vy, vz),
            'swing_twist': rq * rot_seq(lambda a, c, d: R.compose('swing_twist', (a, c, d)), vx, vy, vz),
        }
        rk = report_rank({k: float(ang(q(b), v).max()) for k, v in cands.items()})
        res['mixed_types'][f'{b} {types}'] = rk
        verdict[types] = rk['ranked'][0]['candidate'] if rk['clear'] and rk['ranked'][0]['max_error'] < 0.002 else None
    verdict.update(KNOWN)
    res['consistent_hypotheses'] = [name for name, f in HYPOTHESES.items()
                                    if all(w is not None and f(t) == w for t, w in verdict.items())]
    res['bone_outcomes'] = {str(t): w for t, w in verdict.items()}

    res['unknown_bytes'] = {}
    for b, i in UNKNOWN_OUT.items():
        o = out(i)
        res['unknown_bytes'][b] = dict(
            out_vs_control_max_rad=float(np.abs(o - a_out).max()),
            pose_vs_control_deg=float(ang(q(b), q('A')).max()),
            pose_vs_rest_times_out_deg=float(ang(q(b), wxyz_to_rot([rest(b)] * len(o)) * Rot.from_euler('x', o[:, None])).max()))
    return res


def synthetic(truth, n=800, seed=9):
    t = np.arange(n, dtype=float)
    x = np.radians(65) * np.sin(t / 41.0) - np.radians(25)
    S, K, T = ({'Frame': t.copy()} for _ in range(3))
    rests = {b: np.array(R.from_euler_xyz((np.radians(-2), 0, 0))) for b in 'ABCDEFGHIJK'}
    gains = (0.5, 0.8, -0.9)

    def setq(b, rot):
        for a, col in zip('xyzw', rot.as_quat().T):
            K[f'TestTgt{b}_q{a}'] = col

    full = lambda b: wxyz_to_rot([rests[b]] * n)
    for i in range(0, 8):
        S[f'Out{i}'] = np.zeros(n)
    S['Out8'] = 0.5 * x
    for b in 'ABCDEFGHIJK':
        setq(b, full(b))
    setq('A', full('A') * Rot.from_euler('x', (0.5 * x)[:, None]))
    for b, types in MIXED.items():
        v = [g * x for g in gains]
        for k in range(3):
            S[f'Out{MIXED_OUT[b] + k}'] = v[k]
        mode = truth(types)
        comp = (lambda a, c, d: R.from_euler_xyz((a, c, d))) if mode == 'euler' else \
            (lambda a, c, d: R.compose('swing_twist', (a, c, d)))
        setq(b, full(b) * rot_seq(comp, *v))
    for b, i in UNKNOWN_OUT.items():
        S[f'Out{i}'] = 0.5 * x
        setq(b, full(b) * Rot.from_euler('x', (0.5 * x)[:, None]))
    return dict(sweep=S, skel=K, trs=T, world={'Frame': t.copy()}), rests


def self_test():
    for name, f in HYPOTHESES.items():
        if name.startswith('swing-twist if any'):
            continue                                            # already excluded by round 13
        F, rests = synthetic(f)
        res = analyze(F, rests)
        assert res['sanity']['control_A_err_deg'] < 1e-3
        assert res['consistent_hypotheses'] == [name], (name, res['consistent_hypotheses'], res['bone_outcomes'])
        for b, v in res['unknown_bytes'].items():
            assert v['pose_vs_control_deg'] < 1e-3
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
    rests = {k: np.array(r['quaternion_wxyz']) for k, r in
             json.loads(a.plan.read_text(encoding='utf-8'))['rests'].items()}
    res = analyze(load(a.data), rests)
    text = json.dumps(res, indent=1, ensure_ascii=False)
    if a.json:
        a.json.write_text(text, encoding='utf-8')
    print(text)


if __name__ == '__main__':
    main()
