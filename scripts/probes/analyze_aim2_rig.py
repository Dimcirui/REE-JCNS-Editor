"""
analyze_aim2_rig.py -- round 17 (build_aim2_rig.py): Aim influence / Vec0 / Vec3 (type 2) and the
RotExpression gain.

    python scripts/probes/analyze_aim2_rig.py --data <round17_keep> --plan <round11_plan.json>
    python scripts/probes/analyze_aim2_rig.py --self-test

Aim bones: the ranked candidates of analyze_aimrot_rig (look-at with every reference direction, shortest
arc, slerp toward either by the influence) and, for the influence bones, model-free numbers on how the
world rotation moves.  RotExpr: K (gain 1 on X) is the reference; I (0.5) and J (2) are compared with
the angle scaled, H (0.999, 1, 1) with a plain copy.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation as Rot

HERE = Path(__file__).resolve().parent
from analyze_aimrot_rig import analyze_aim                                     # noqa: E402
from analyze_sections_rig import ang, load, pos_cols, quat_cols               # noqa: E402

TARGET, UP = 'R_Hand', 'L_Hand'
AIMS = [('B', 0, None, (0, 0, 0), (0, 1, 0), 0.25), ('C', 0, None, (0, 0, 0), (0, 1, 0), 2.0),
        ('D', 4, None, (0, 0, 0), (0, 1, 0), 0.5), ('E', 2, UP, (0, 0, 0), (0, 0, 1), 1.0),
        ('F', 2, UP, (0.1, 0.05, 0.02), (0, 1, 0), 1.0), ('G', 1, UP, (0, 0, 0), (0, 1, 0), 0.5)]


def wrap(a):
    return (a + np.pi) % (2 * np.pi) - np.pi


def influence_stats(W, rests, bone, target):
    tag = f'e.TestTgt{bone}'
    P, R = pos_cols(W, tag), quat_cols(W, tag)
    ear = quat_cols(W, 'e.Ear_SCL')
    T = pos_cols(W, f'b.{target}')
    d = (T - P) / np.linalg.norm(T - P, axis=1, keepdims=True)
    v1 = np.array([1.0, 0, 0])
    aim_angle = np.degrees(np.arccos(np.clip(np.sum(R.apply(v1) * d, axis=1), -1, 1)))
    rest = Rot.from_quat(rests[bone][[1, 2, 3, 0]])
    rest_angle = np.degrees(np.arccos(np.clip(np.sum((ear * rest).apply(v1) * d, axis=1), -1, 1)))
    mean = R.mean()
    dev = (mean.inv() * R).as_rotvec()
    lin = np.c_[T, np.ones(len(T))]
    sol = np.linalg.lstsq(lin, dev, rcond=None)[0]
    return dict(bone=bone,
                world_rotation_range_from_first_deg=float(ang(R, R[0]).max()),
                parent_rotation_range_deg=float(ang(ear, ear[0]).max()),
                aim_axis_to_target_deg=[float(aim_angle.min()), float(np.median(aim_angle)), float(aim_angle.max())],
                rest_axis_to_target_deg=[float(rest_angle.min()), float(np.median(rest_angle)), float(rest_angle.max())],
                corr_aim_angle_with_rest_angle=float(np.corrcoef(aim_angle, rest_angle)[0, 1]),
                world_dev_vs_target_position_resid_deg=float(np.degrees(np.abs(lin @ sol - dev)).max()))


def rot_axis_angle(t, k):
    q = t.as_quat() * np.where(t.as_quat()[:, 3:4] < 0, -1, 1)
    return 2 * np.arctan2(q[:, k], q[:, 3]), float(np.abs(np.delete(q[:, :3], k, axis=1)).max())


def analyze_rot(F):
    S, K = F['sweep'], F['skel']
    q_src = Rot.from_quat(np.stack([S[f'L_Thigh_q{a}'] for a in 'xyzw'], axis=1))
    t = {b: quat_cols(K, f'TestTgt{b}') for b in 'HIJK'}
    res = dict(H_copy_error_deg=float(ang(t['H'], q_src).max()),
               H_copy_error_median_deg=float(np.median(ang(t['H'], q_src))))
    phi = {}
    for b in 'IJK':
        phi[b], off = rot_axis_angle(t[b], 0)
        res[f'{b}_off_axis_quat_component'] = off
    res['I_vs_half_of_K_deg'] = float(np.degrees(np.abs(wrap(phi['I'] - 0.5 * phi['K'])).max()))
    res['J_vs_double_of_K_deg'] = float(np.degrees(np.abs(wrap(phi['J'] - 2 * phi['K'])).max()))
    res['K_angle_range_deg'] = [float(np.degrees(phi['K'].min())), float(np.degrees(phi['K'].max()))]
    # quaternion-component scaling as the other reading of a "gain"
    q = t['K'].as_quat()
    for b, g in (('I', 0.5), ('J', 2.0)):
        v = q.copy()
        v[:, 0] *= g
        v /= np.linalg.norm(v, axis=1, keepdims=True)
        res[f'{b}_vs_scaled_quaternion_x_deg'] = float(ang(t[b], Rot.from_quat(v)).max())
    return res


def analyze(F, rests):
    S, K, W = F['sweep'], F['skel'], F['world']
    x = np.degrees(np.asarray(S['Out8'], float) / 0.5)
    if np.ptp(x) < 30:
        raise ValueError(f'input span {np.ptp(x):.1f} deg < 30')
    ctrl = float(ang(quat_cols(K, 'TestTgtA'), Rot.from_quat(rests['A'][[1, 2, 3, 0]]) * Rot.from_euler('x', np.asarray(S['Out8'])[:, None])).max())
    res = dict(sanity=dict(frames=len(x), input_span_deg=float(np.ptp(x)), control_A_err_deg=ctrl), aim={}, influence={})
    for spec in AIMS:
        b, t, up, v0, v3, infl = spec
        a = analyze_aim(W, rests, TARGET, (b, t, (1, 0, 0), (0, 1, 0), v3, infl), up=up)
        a['candidates']['ranked'] = a['candidates']['ranked'][:6]
        a['vec0'] = v0
        res['aim'][f'{b} (type {t}, influence {infl:g}, vec3 {v3}, vec0 {v0})'] = a
        if infl != 1.0:
            res['influence'][b] = influence_stats(W, rests, b, TARGET)
    res['rot'] = analyze_rot(F)
    return res


def synthetic(n=600):
    t = np.arange(n, dtype=float)
    S, K = ({'Frame': t.copy()} for _ in range(2))
    rng = np.random.default_rng(2)
    src = Rot.from_rotvec(np.cumsum(rng.normal(size=(n, 3)), axis=0) * 0.03)
    for a, col in zip('xyzw', src.as_quat().T):
        S[f'L_Thigh_q{a}'] = col

    def setq(b, r):
        for a, col in zip('xyzw', r.as_quat().T):
            K[f'TestTgt{b}_q{a}'] = col
    phi = 2 * np.arctan2(src.as_quat()[:, 0] * np.sign(src.as_quat()[:, 3:4] + 1e-30)[:, 0], np.abs(src.as_quat()[:, 3]))
    for b, g in (('K', 1.0), ('I', 0.5), ('J', 2.0)):
        setq(b, Rot.from_rotvec(np.c_[g * phi, 0 * phi, 0 * phi]))
    setq('H', src)
    return dict(sweep=S, skel=K)


def self_test():
    res = analyze_rot(synthetic())
    assert res['H_copy_error_deg'] < 1e-6 and res['I_vs_half_of_K_deg'] < 1e-6 and res['J_vs_double_of_K_deg'] < 1e-6, res
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
    rests = {k: np.array(r['quaternion_wxyz']) for k, r in json.loads(a.plan.read_text(encoding='utf-8'))['rests'].items()}
    res = analyze(load(a.data), rests)
    text = json.dumps(res, indent=1, ensure_ascii=False)
    if a.json:
        a.json.write_text(text, encoding='utf-8')
    print(text)


if __name__ == '__main__':
    main()
