"""
analyze_small_rig.py -- round 16 (build_small_rig.py): the small Ranges questions.

    python scripts/probes/analyze_small_rig.py --data <round16_keep> --plan <round11_plan.json>
    python scripts/probes/analyze_small_rig.py --self-test

  interpolation  entries [09]-[11]: Out against a list of easing curves, per source byte +28
  bit0 mixed     D (type 4), G (type 6), B (type 5): X added (F49) + Y replaced (F48)
  unknown bytes  H translation, I scale with +72 / +74 / +75 changed: the usual rule still holds?
  +75            J and K: a translation and a rotation on one bone, +75 = 2 / 8 against 2 / 2
"""
import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation as Rot

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / 'modules'))
import jcns_source_read as R                                          # noqa: E402
from analyze_rules_rig import rot_seq, wxyz_to_rot                    # noqa: E402
from analyze_sections_rig import ang, load, quat_cols, report_rank    # noqa: E402

STRIDE = 3
EASINGS = {
    'linear': lambda t: t,
    'smoothstep 3t^2-2t^3': lambda t: t * t * (3 - 2 * t),
    'smootherstep': lambda t: t ** 3 * (t * (6 * t - 15) + 10),
    'quad in': lambda t: t * t,
    'quad out': lambda t: 1 - (1 - t) ** 2,
    'cubic in': lambda t: t ** 3,
    'cubic out': lambda t: 1 - (1 - t) ** 3,
    'sine in-out': lambda t: 0.5 - 0.5 * np.cos(np.pi * t),
    'sine in': lambda t: 1 - np.cos(np.pi * t / 2),
    'sine out': lambda t: np.sin(np.pi * t / 2),
    'quad in-out': lambda t: np.where(t < 0.5, 2 * t * t, 1 - 2 * (1 - t) ** 2),
    'cubic in-out': lambda t: np.where(t < 0.5, 4 * t ** 3, 1 - 4 * (1 - t) ** 3),
}


def seg_eval(x, x0, y0, x1, y1, ease):
    t = np.clip((x - x0) / (x1 - x0), 0.0, 1.0)
    return y0 + (y1 - y0) * ease(t)


def interpolation(x_deg, out_deg, frm, to, three_point):
    """Rank easing curves for one mapping (degrees)."""
    cands = {}
    for name, ease in EASINGS.items():
        if not three_point:
            cands[f'whole range: {name}'] = seg_eval(x_deg, frm[0], to[0], frm[2], to[2], ease)
        else:
            y1 = seg_eval(x_deg, frm[0], to[0], frm[1], to[1], ease)
            y2 = seg_eval(x_deg, frm[1], to[1], frm[2], to[2], ease)
            cands[f'per segment: {name}'] = np.where(x_deg <= frm[1], y1, y2)
            cands[f'whole range, kink ignored: {name}'] = seg_eval(x_deg, frm[0], to[0], frm[2], to[2], ease)
    return report_rank({k: float(np.abs(v - out_deg).max()) for k, v in cands.items()})


def analyze(F, rests, plan_pos, stride=STRIDE):
    S, K, T = F['sweep'], F['skel'], F['trs']
    sl = slice(None, None, stride)
    out = lambda i: np.asarray(S[f'Out{i}'], float)[sl]
    q = lambda b: quat_cols(K, f'TestTgt{b}')[sl]
    rest = lambda b: tuple(rests[b])
    res = {}
    x = np.degrees(np.asarray(S['Out8'], float) / 0.5)
    span = float(np.ptp(x))
    if span < 30:
        raise ValueError(f'input span {span:.1f} deg < 30')
    a_out = out(8)
    ctrl = float(ang(q('A'), wxyz_to_rot([rest('A')] * len(a_out)) * Rot.from_euler('x', a_out[:, None])).max())
    res['sanity'] = dict(frames=len(x), input_span_deg=span, control_A_err_deg=ctrl)
    for i in range(9, 24):
        if np.abs(S[f'Out{i}']).max() < 1e-9:
            raise ValueError(f'Out{i} is all zero: the game still has another round loaded (restart it fully)')
    xs = x[sl]

    res['interpolation'] = {
        '+28=1 two-point': interpolation(xs, np.degrees(out(9)), (-90, 0, 90), (-45, 0, 45), False),
        '+28=2 two-point': interpolation(xs, np.degrees(out(10)), (-90, 0, 90), (-72, 0, 72), False),
        '+28=3 three-point': interpolation(xs, np.degrees(out(11)), (-90, -30, 90), (-45, -10, 45), True)}
    for k, v in res['interpolation'].items():
        v['ranked'] = v['ranked'][:5]

    def mixed(bone, mode, first):
        vx, vy = out(first), out(first + 1)
        r = rest(bone)
        rq = wxyz_to_rot([r] * len(vx))
        rv = [R.rotation(mode, r, a) for a in range(3)]
        comp = lambda a, b_, c: R.compose(mode, (a, b_, c))
        z = np.zeros_like(vx)
        return {
            'added X + replaced Y (target_basis model)': rot_seq(
                lambda a, b_: R.qmul(r, R.from_euler_xyz(R.target_basis(r, [(0, mode, False, a), (1, mode, True, b_)]))), vx, vy),
            'all added: rest*comp(x,y,0)': rq * rot_seq(comp, vx, vy, z),
            'all replaced in the decomposition': rot_seq(comp, vx, vy, np.full_like(vx, rv[2])),
            'drop the whole rest: comp(x,y,0)': rot_seq(comp, vx, vy, z),
            'swapped roles (X replaced, Y added)': rot_seq(
                lambda a, b_: R.qmul(r, R.from_euler_xyz(R.target_basis(r, [(0, mode, True, a), (1, mode, False, b_)]))), vx, vy),
            'rest decomposition + x on X, y replaces Y': rot_seq(
                lambda a, b_: comp(rv[0] + a, b_, rv[2]), vx, vy),
            'comp(replaced) then comp(x) on the right': rot_seq(
                lambda a, b_: R.qmul(comp(0.0, b_, rv[2]), comp(a, 0.0, 0.0)), vx, vy),
            'comp(x) on the left of comp(replaced)': rot_seq(
                lambda a, b_: R.qmul(comp(a, 0.0, 0.0), comp(0.0, b_, rv[2])), vx, vy),
        }
    res['bit0_mixed'] = {}
    for bone, tt, mode, first in (('D', 4, 'swing_twist', 12), ('B', 5, 'twist_swing', 16), ('G', 6, 'rotvec', 14)):
        c = mixed(bone, mode, first)
        res['bit0_mixed'][f'{bone} (type {tt})'] = report_rank({k: float(ang(q(bone), v).max()) for k, v in c.items()})
        res['bit0_mixed'][f'{bone} (type {tt})']['ranked'] = res['bit0_mixed'][f'{bone} (type {tt})']['ranked'][:4]

    pos = lambda b: np.stack([np.asarray(T[f'TestTgt{b}_p{a}'], float)[sl] for a in 'xyz'], axis=1)
    scl = lambda b: np.stack([np.asarray(T[f'TestTgt{b}_s{a}'], float)[sl] for a in 'xyz'], axis=1)
    # H: translation X on the parent axis, rest offset kept; slope of (position - rest) against Out
    ph = pos('H') - np.array(plan_pos['H'])
    slope = float(np.polyfit(out(18), ph[:, 0], 1)[0])
    res['unknown_bytes_translation'] = dict(
        slope_position_per_out=slope, x_resid_max=float(np.abs(ph[:, 0] - slope * out(18)).max()),
        yz_moved_max=float(np.abs(ph[:, 1:]).max()), pos_vs_control_shape='slope 0.01 is centimetres to metres')
    si = scl('I')
    res['unknown_bytes_scale'] = dict(
        sy_vs_out_max=float(np.abs(si[:, 1] - out(19)).max()),
        sx_sz_move_max=float(np.abs(si[:, [0, 2]] - 1.0).max()))

    pj, pk = pos('J'), pos('K')
    res['tail75_mixed_bone'] = dict(
        position_J_vs_K_max=float(np.abs(pj - pk).max()), rotation_J_vs_K_deg=float(ang(q('J'), q('K')).max()),
        out_translation_J_vs_K=float(np.abs(out(20) - out(22)).max()), out_rotation_J_vs_K=float(np.abs(out(21) - out(23)).max()),
        J_translation_slope=float(np.polyfit(out(20), (pj - np.array(plan_pos['J']))[:, 0], 1)[0]),
        J_rotation_vs_rest_times_out_deg=float(ang(q('J'), wxyz_to_rot([rest('J')] * len(a_out)) * Rot.from_euler('x', out(21)[:, None])).max()))
    return res


def synthetic(n=900):
    t = np.arange(n, dtype=float)
    x = np.radians(65) * np.sin(t / 41.0) - np.radians(25)
    S, K, T = ({'Frame': t.copy()} for _ in range(3))
    rests = {b: np.array(R.from_euler_xyz((math.radians(-2), 0, 0))) for b in 'ABCDEFGHIJK'}
    for b in 'BDG':
        rests[b] = np.array(R.from_euler_xyz(tuple(math.radians(v) for v in (-2, 17, -23))))
    plan_pos = {b: np.array([0.0, -0.5955, 0.0134]) for b in 'ABCDEFGHIJK'}
    xd = np.degrees(x)
    for i in range(0, 8):
        S[f'Out{i}'] = np.zeros(n)
    S['Out8'] = 0.5 * x

    def setq(b, rot):
        for a, col in zip('xyzw', rot.as_quat().T):
            K[f'TestTgt{b}_q{a}'] = col

    def setp(b, p, s=None):
        for k, a in enumerate('xyz'):
            T[f'TestTgt{b}_p{a}'] = p[:, k]
            T[f'TestTgt{b}_s{a}'] = (s if s is not None else np.ones((n, 3)))[:, k]

    full = lambda b: wxyz_to_rot([rests[b]] * n)
    for b in 'ABCDEFGHIJK':
        setq(b, full(b))
        setp(b, np.tile(plan_pos[b], (n, 1)))
    setq('A', full('A') * Rot.from_euler('x', (0.5 * x)[:, None]))
    S['Out9'] = np.radians(seg_eval(xd, -90, -45, 90, 45, EASINGS['sine in-out']))      # truth for +28=1
    S['Out10'] = np.radians(seg_eval(xd, -90, -72, 90, 72, EASINGS['quad in']))         # truth for +28=2
    y1 = seg_eval(xd, -90, -45, -30, -10, EASINGS['smoothstep 3t^2-2t^3'])
    y2 = seg_eval(xd, -30, -10, 90, 45, EASINGS['smoothstep 3t^2-2t^3'])
    S['Out11'] = np.radians(np.where(xd <= -30, y1, y2))                                  # truth for +28=3 three-point
    for bone, mode, first in (('D', 'swing_twist', 12), ('B', 'twist_swing', 16), ('G', 'rotvec', 14)):
        vx, vy = 0.5 * x, 0.8 * x
        S[f'Out{first}'], S[f'Out{first + 1}'] = vx, vy
        r = tuple(rests[bone])
        rv = [R.rotation(mode, r, a) for a in range(3)]
        setq(bone, wxyz_to_rot([R.qmul(r, R.from_euler_xyz(R.target_basis(
            r, [(0, mode, False, a), (1, mode, True, b_)]))) for a, b_ in zip(vx, vy)]))     # truth: the target_basis model
    S['Out18'] = 0.03 * xd
    p = np.tile(plan_pos['H'], (n, 1))
    p[:, 0] += 0.01 * S['Out18']
    setp('H', p)
    S['Out19'] = 1 + 0.003 * xd
    s = np.ones((n, 3))
    s[:, 1] = S['Out19']
    setp('I', np.tile(plan_pos['I'], (n, 1)), s)
    for b in 'JK':
        S['Out20' if b == 'J' else 'Out22'] = 0.03 * xd
        S['Out21' if b == 'J' else 'Out23'] = 0.5 * x
        p = np.tile(plan_pos[b], (n, 1))
        p[:, 0] += 0.01 * 0.03 * xd
        setp(b, p)
        setq(b, full(b) * Rot.from_euler('x', (0.5 * x)[:, None]))
    return dict(sweep=S, skel=K, trs=T, world={'Frame': t.copy()}), rests, plan_pos


def self_test():
    F, rests, plan_pos = synthetic()
    res = analyze(F, rests, plan_pos)
    assert res['sanity']['control_A_err_deg'] < 1e-3
    assert res['interpolation']['+28=1 two-point']['ranked'][0]['candidate'] == 'whole range: sine in-out'
    assert res['interpolation']['+28=2 two-point']['ranked'][0]['candidate'] == 'whole range: quad in'
    assert res['interpolation']['+28=3 three-point']['ranked'][0]['candidate'] == 'per segment: smoothstep 3t^2-2t^3'
    for k, v in res['bit0_mixed'].items():
        assert v['ranked'][0]['candidate'] == 'comp(replaced) then comp(x) on the right' or \
            v['ranked'][0]['candidate'].startswith('added X + replaced Y'), (k, v['ranked'][:3])
        assert v['ranked'][0]['max_error'] < 1e-3, (k, v['ranked'][:3])
    assert abs(res['unknown_bytes_translation']['slope_position_per_out'] - 0.01) < 1e-9
    assert res['unknown_bytes_scale']['sy_vs_out_max'] < 1e-9
    assert res['tail75_mixed_bone']['position_J_vs_K_max'] < 1e-9
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
    plan = json.loads(a.plan.read_text(encoding='utf-8'))
    rests = {k: np.array(r['quaternion_wxyz']) for k, r in plan['rests'].items()}
    plan_pos = {k: np.array(r['position_m']) for k, r in plan['rests'].items()}
    res = analyze(load(a.data), rests, plan_pos)
    text = json.dumps(res, indent=1, ensure_ascii=False)
    if a.json:
        a.json.write_text(text, encoding='utf-8')
    print(text)


if __name__ == '__main__':
    main()
