"""
analyze_aimrot_rig.py -- round 14 (build_aimrot_rig.py): Aim vectors / type / influence and
RotExpression's exact form.

    python scripts/probes/analyze_aimrot_rig.py --data <round14_keep> --plan <round11_plan.json>
    python scripts/probes/analyze_aimrot_rig.py --self-test

Every question is a ranked list of candidate formulas scored by the worst-frame error; a verdict
needs the runner-up to be >= 10x worse (see analyze_sections_rig.report_rank).

  Aim      aim axis: u = R^T dir(bone -> target) is constant when the engine points a local
           axis at the target; compared with Vec1.  Roll: for every reference direction (world
           and parent axes, the target bone's axes) and for Vec2 / Vec3 as the local up axis, a
           full look-at; plus the shortest arc from rest, and slerp toward either by Influence.
  RotExpr  coefficient (1,1,1): is the result the source rotation itself?  Single-axis
           coefficients: is the result a rotation about that axis only, and which reading of the
           source (Euler orders, rotation vector, per-component half angles, swing-twist) is its angle?
"""
import argparse
import itertools
import json
import math
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation as Rot

from analyze_sections_rig import (ang, frame_from, load, pos_cols, quat_cols, rests_from, report_rank,
                                  shortest_arc, unit)

SPEC = dict(
    target='R_Hand', source='L_Thigh',
    aim=[('B', 0, (0, 0, -1), (0, 1, 0), (0, 1, 0), 1.0), ('C', 0, (1, 0, 0), (0, 0, 1), (0, 1, 0), 1.0),
         ('D', 0, (1, 0, 0), (0, 1, 0), (0, 0, 1), 1.0), ('J', 3, (1, 0, 0), (0, 1, 0), (0, 0, 1), 1.0),
         ('K', 5, (1, 0, 0), (0, 1, 0), (0, 1, 0), 1.0), ('I', 0, (1, 0, 0), (0, 1, 0), (0, 1, 0), 0.5)],
    rot=[('E', (1, 1, 1)), ('F', (1, 0, 0)), ('G', (0, 1, 0)), ('H', (0, 0, 1))])


def slerp_to(rest, full, k):
    """Per-frame slerp from `rest` to `full` by fraction k (vectorized, shortest path)."""
    return rest * Rot.from_rotvec(k * (rest.inv() * full).as_rotvec())


def references(W):
    """Named world directions a roll could be taken from."""
    ear = quat_cols(W, 'e.Ear_SCL')
    refs = {}
    for k, a in enumerate('xyz'):
        e = np.eye(3)[k]
        refs[f'world_+{a}'] = np.tile(e, (len(ear), 1))
        refs[f'world_-{a}'] = np.tile(-e, (len(ear), 1))
        refs[f'parent_+{a}'] = ear.apply(e)
        refs[f'parent_-{a}'] = ear.apply(-e)
    return refs


def analyze_aim(W, rests, target, spec):
    bone, typ, v1, v2, v3, infl = spec
    tag = f'e.TestTgt{bone}'
    P, R = pos_cols(W, tag), quat_cols(W, tag)
    T = pos_cols(W, f'b.{target}')
    d = unit(T - P)
    u = R.inv().apply(d)
    mean = unit(u.mean(axis=0, keepdims=True))[0]
    res = dict(bone=bone, type=typ, vec1=v1, vec2=v2, vec3=v3, influence=infl,
               aim_axis=dict(mean_local=mean.tolist(),
                             max_spread_deg=float(np.degrees(np.arccos(np.clip(u @ mean, -1, 1))).max()),
                             vs_vec1_deg=float(np.degrees(np.arccos(np.clip(
                                 mean @ np.array(v1) / np.linalg.norm(v1), -1, 1))))))
    ear_q = quat_cols(W, 'e.Ear_SCL')
    rest_local = Rot.from_quat(rests[bone][[1, 2, 3, 0]])
    rest_world = ear_q * rest_local
    v1a = np.array(v1, float)
    refs = references(W)
    refs['target_bone_x'] = quat_cols(W, f'b.{target}').apply([1.0, 0, 0])
    refs['target_bone_y'] = quat_cols(W, f'b.{target}').apply([0, 1.0, 0])
    refs['target_bone_z'] = quat_cols(W, f'b.{target}').apply([0, 0, 1.0])
    refs['vec3_as_world_dir'] = np.tile(np.array(v3, float), (len(d), 1))
    errs, preds, valid = {}, {}, {}
    for sec_name, sec in (('vec2', v2), ('vec3', v3)):
        if np.linalg.norm(np.cross(v1a, sec)) < 1e-6:
            continue
        L = frame_from(v1a[None], np.array(sec, float)[None])[0]
        for rn, rv in refs.items():
            w = rv - np.sum(rv * d, axis=1, keepdims=True) * d
            ok = np.linalg.norm(w, axis=1) > 0.05          # the reference is undefined when it is parallel to d
            if ok.mean() < 0.9:
                continue
            pred = Rot.from_matrix(frame_from(d, rv) @ L.T[None])
            name = f'lookat(local up={sec_name}, ref={rn})'
            errs[name] = float(ang(R, pred)[ok].max())
            preds[name], valid[name] = pred, ok
    bases = {'rest_world': rest_world, 'parent_only': ear_q}
    for bn, B in bases.items():
        arc = shortest_arc(unit(B.apply(v1a)), d) * B
        errs[f'shortest_arc_from_{bn}'] = float(ang(R, arc).max())
        preds[f'shortest_arc_from_{bn}'] = arc
        valid[f'shortest_arc_from_{bn}'] = np.ones(len(d), bool)
    errs['unchanged_rest'] = float(ang(R, rest_world).max())
    if infl != 1.0:
        for name in list(preds):
            for bn, B in bases.items():
                ok = valid[name]
                errs[f'slerp({infl:g}) {bn}->{name}'] = float(ang(R, slerp_to(B, preds[name], infl))[ok].max())
    res['candidates'] = report_rank(errs)
    res['candidates']['ranked'] = res['candidates']['ranked'][:6]
    # model-free roll: which reference, projected perpendicular to the aim direction, is
    # constant in the bone's own frame (its local direction is the "up" axis the engine used)
    roll = []
    for rn, rv in refs.items():
        w = rv - np.sum(rv * d, axis=1, keepdims=True) * d
        ok = np.linalg.norm(w, axis=1) > 0.15
        if ok.sum() < 200:
            continue
        loc = Rot.from_quat(R.as_quat()[ok]).inv().apply(unit(w[ok]))
        m = unit(loc.mean(axis=0, keepdims=True))[0]
        roll.append((float(np.degrees(np.arccos(np.clip(loc @ m, -1, 1))).max()), rn, m.round(4).tolist()))
    roll.sort()
    res['roll_constant_refs'] = [dict(spread_deg=a, ref=b, local_dir=c) for a, b, c in roll[:3]]
    return res


# ── RotExpression ───────────────────────────────────────────────────────────

def readings(q):
    """name -> (n, 3) angle triple the source could be read as (radians)."""
    out = {}
    qq = q.as_quat() * np.where(q.as_quat()[:, 3:4] < 0, -1, 1)[:, :1]
    for seq in [''.join(p) for p in itertools.permutations('xyz')] + [''.join(p) for p in itertools.permutations('XYZ')]:
        a = q.as_euler(seq)
        v = np.zeros_like(a)
        for k, ax in enumerate(seq.lower()):
            v[:, 'xyz'.index(ax)] = a[:, k]
        out[f'euler_{seq}'] = v
    out['rotvec'] = q.as_rotvec()
    out['half_angle_atan(q_k/w)'] = 2 * np.arctan2(qq[:, :3], qq[:, 3:4])
    out['asin(q_k)*2'] = 2 * np.arcsin(np.clip(qq[:, :3], -1, 1))
    out['q_k*2'] = 2 * qq[:, :3]
    # swing-twist about X as the ReadMode 3 / 4 definitions
    for mode, first in (('swing_twist', True), ('twist_swing', False)):
        x, w = qq[:, 0], qq[:, 3]
        n = np.hypot(x, w)
        t = Rot.from_quat(np.stack([x / n, 0 * x, 0 * x, w / n], axis=1))
        s = (q * t.inv()) if first else (t.inv() * q)
        sq = s.as_quat() * np.where(s.as_quat()[:, 3:4] < 0, -1, 1)
        out[mode] = np.stack([2 * np.arctan2(x / n, w / n), 2 * np.arctan2(sq[:, 1], sq[:, 3]),
                              2 * np.arctan2(sq[:, 2], sq[:, 3])], axis=1)
    return out


def wrap(a):
    return (a + np.pi) % (2 * np.pi) - np.pi


def analyze_rot(F, rests, bone, gains, source):
    S, K = F['sweep'], F['skel']
    q_src = Rot.from_quat(np.stack([S[f'{source}_q{a}'] for a in 'xyzw'], axis=1))
    t = quat_cols(K, f'TestTgt{bone}')
    res = dict(bone=bone, gains=gains, local_rotation_range_deg=float(ang(t, t[0]).max()))
    if tuple(gains) == (1, 1, 1):
        res['copy_error_deg'] = float(ang(t, q_src).max())
        res['copy_error_median_deg'] = float(np.median(ang(t, q_src)))
        return res
    k = [i for i, g in enumerate(gains) if g][0]
    tq = t.as_quat() * np.where(t.as_quat()[:, 3:4] < 0, -1, 1)
    axis_angle = 2 * np.arctan2(tq[:, k], tq[:, 3])
    off = np.delete(tq[:, :3], k, axis=1)
    res['axis'] = 'xyz'[k]
    res['off_axis_max_quat_component'] = float(np.abs(off).max())
    errs = {name: float(np.degrees(np.abs(wrap(axis_angle - r[:, k])).max())) for name, r in readings(q_src).items()}
    res['reading_candidates'] = report_rank(errs)
    res['reading_candidates']['ranked'] = res['reading_candidates']['ranked'][:6]
    res['angle_range_deg'] = [float(np.degrees(axis_angle.min())), float(np.degrees(axis_angle.max()))]
    return res


def sanity(F, rests):
    S, K = F['sweep'], F['skel']
    x = S['Out8'] / 0.5
    span = float(np.degrees(np.ptp(x)))
    if span < 30:
        raise ValueError(f'input span {span:.1f} deg < 30')
    a = quat_cols(K, 'TestTgtA')
    ra = Rot.from_quat(rests['A'][[1, 2, 3, 0]])
    return dict(frames=len(x), input_span_deg=span,
                control_A_err_deg=float(ang(a, ra * Rot.from_euler('x', S['Out8'][:, None])).max()))


def run(F, rests):
    out = dict(sanity=sanity(F, rests), aim={}, rot={})
    if out['sanity']['control_A_err_deg'] > 0.002:
        out['warning'] = 'control A off: the jcns or mesh in the game is not this round'
    for spec in SPEC['aim']:
        out['aim'][f'{spec[0]}(type {spec[1]})'] = analyze_aim(F['world'], rests, SPEC['target'], spec)
    for b, g in SPEC['rot']:
        out['rot'][f'{b}{tuple(g)}'] = analyze_rot(F, rests, b, g, SPEC['source'])
    return out


# ── self-test ───────────────────────────────────────────────────────────────

def synthetic(n=500, seed=3):
    rng = np.random.default_rng(seed)
    t = np.arange(n, dtype=float)

    def smooth(scale, k):
        x = rng.normal(size=(n, k)).cumsum(axis=0)
        return scale * x / np.abs(x).max()

    W, K, S = ({'Frame': t.copy()} for _ in range(3))

    def put(tab, prefix, p, q):
        for a, c in zip('xyz', p.T):
            tab[f'{prefix}_p{a}'] = c
        for a, c in zip('xyzw', q.as_quat().T):
            tab[f'{prefix}_q{a}'] = c

    ear_q, ear_p = Rot.from_rotvec(smooth(0.4, 3)), smooth(0.3, 3) + [0, 1.5, 0]
    put(W, 'e.Ear_SCL', ear_p, ear_q)
    rest = Rot.from_euler('x', -0.0349)
    rests = {b: rest.as_quat()[[3, 0, 1, 2]] for b in 'ABCDEFGHIJK'}
    base_p = ear_p + ear_q.apply([0, -0.5955, 0.0134])
    hand_p, hand_q = smooth(1.0, 3) + rng.normal(size=3), Rot.from_rotvec(smooth(1.5, 3))
    put(W, 'b.R_Hand', hand_p, hand_q)
    x = np.radians(60) * np.sin(t / 37.0)
    S['Out8'] = 0.5 * x
    put(K, 'TestTgtA', np.zeros((n, 3)), rest * Rot.from_euler('x', (0.5 * x)[:, None]))
    d = unit(hand_p - base_p)
    for b, typ, v1, v2, v3, infl in SPEC['aim']:
        L = frame_from(np.array([v1], float), np.array([v2], float))[0]
        Rw = Rot.from_matrix(frame_from(d, np.tile([0, 1.0, 0], (n, 1))) @ L.T[None])   # truth: world +Y, Vec2
        if infl != 1.0:
            Rw = slerp_to(ear_q * rest, Rw, infl)
        put(W, f'e.TestTgt{b}', base_p, Rw)
    src_q = Rot.from_rotvec(smooth(1.6, 3))
    for a, c in zip('xyzw', src_q.as_quat().T):
        S[f'L_Thigh_q{a}'] = c
    for b, g in SPEC['rot']:
        pred = Rot.from_euler('xyz', src_q.as_euler('xyz') * np.array(g))     # truth: Euler XYZ x gains
        put(K, f'TestTgt{b}', np.zeros((n, 3)), pred)
    return dict(sweep=S, skel=K, trs={'Frame': t.copy()}, world=W), rests


def self_test():
    F, rests = synthetic()
    res = run(F, rests)
    assert res['sanity']['control_A_err_deg'] < 1e-3
    for k, v in res['aim'].items():
        top = v['candidates']['ranked'][0]
        assert top['max_error'] < 2e-3, (k, top)
        if k.startswith('I'):
            assert top['candidate'].startswith('slerp(0.5)') and 'ref=world_+y' in top['candidate'], (k, top)
            continue
        assert v['aim_axis']['max_spread_deg'] < 1e-3 and v['aim_axis']['vs_vec1_deg'] < 1e-3, (k, v['aim_axis'])
        assert 'ref=world_+y' in top['candidate'], (k, top)
        assert v['roll_constant_refs'][0]['spread_deg'] < 1e-3, (k, v['roll_constant_refs'])
    for k, v in res['rot'].items():
        if 'copy_error_deg' in v:
            continue
        top = v['reading_candidates']['ranked'][0]
        assert top['max_error'] < 1e-2 and top['candidate'] == 'euler_xyz', (k, top)
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
    rests = rests_from(json.loads(a.plan.read_text(encoding='utf-8')))
    res = run(load(a.data), rests)
    text = json.dumps(res, indent=1, ensure_ascii=False)
    if a.json:
        a.json.write_text(text, encoding='utf-8')
    print(text)


if __name__ == '__main__':
    main()
