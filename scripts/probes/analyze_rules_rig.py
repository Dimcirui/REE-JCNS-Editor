"""
analyze_rules_rig.py -- round 13 (build_rules_rig.py): the Ranges rules the panel marks as guesses.

    python scripts/probes/analyze_rules_rig.py --data <round13_keep> --plan <round11_plan.json>
    python scripts/probes/analyze_rules_rig.py --self-test

Each bone's recorded local quaternion is ranked against candidate formulas built from its own
entries' outputs (Out<i>, radians) and its rest pose; a verdict needs the runner-up to be >= 10x
worse and the winner within 0.002 degrees.  Candidates tie when the written channels cover the
whole rotation, which is why B, C, D, H write only some axes.

  B C D  bit0 = 0 on types 4 / 5 / 6 with X, Y written: is the whole rest dropped, or only the
         written channels replaced (in the type's own decomposition, or in Euler terms)?
  H      type 14, bit0 = 0: like type 13 (round 9: the whole rest is dropped)?
  G      type 1 X added + Y replaced on one bone (the panel models this with override_basis)
  I      type 1 X / Z with a type 4 Y on the same bone
  J K    UnknownFloat2 (-45, 0) and (-90, -90): any difference from control A?
  E F    a scale read by InputType 2: the rest scale, the pose scale, or their product?
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
import jcns_source_read as R            # noqa: E402

from analyze_sections_rig import ang, load, quat_cols, rests_from, report_rank   # noqa: E402

OUT = dict(A=8, B=(9, 10), C=(11, 12), D=(13, 14), G=(15, 16), H=17, I=(18, 19, 20), J=21, K=22,
           E=(23, 24, 25), F=(26, 27))
TYPE_MODE = {'B': 'swing_twist', 'C': 'twist_swing', 'D': 'rotvec'}
STRIDE = 3
TYPE_NUMBER = {'swing_twist': 4, 'twist_swing': 5, 'rotvec': 6}


def wxyz_to_rot(seq):
    a = np.array(seq)
    return Rot.from_quat(a[:, [1, 2, 3, 0]])


def rot_seq(f, *cols):
    """Rotation array from f(*values) -> wxyz, one call per (strided) frame."""
    return wxyz_to_rot([f(*v) for v in zip(*cols)])


def rank(actual, cands):
    return report_rank({k: float(ang(actual, v).max()) for k, v in cands.items()})


def analyze(F, rests, stride=STRIDE):
    S, K, T = F['sweep'], F['skel'], F['trs']
    sl = slice(None, None, stride)

    def out(i):
        v = np.asarray(S[f'Out{i}'], float)[sl]
        if not np.isfinite(v).all():
            raise ValueError(f'Out{i}: non-finite')
        return v

    def q(b):
        return quat_cols(K, f'TestTgt{b}')[sl]

    def rest(b):
        return tuple(rests[b])                      # wxyz

    res = {}
    x = np.asarray(S['Out8'], float) / 0.5
    span = float(np.degrees(np.ptp(x)))
    if span < 30:
        raise ValueError(f'input span {span:.1f} deg < 30')
    ctrl = float(ang(q('A'), wxyz_to_rot([rest('A')] * len(out(8))) * Rot.from_euler('x', out(8)[:, None])).max())
    res['sanity'] = dict(frames=len(x), input_span_deg=span, control_A_err_deg=ctrl)

    # B C D: bit0 = 0, types 4 / 5 / 6, X and Y written
    res['types_456_replace'] = {}
    for b, mode in TYPE_MODE.items():
        vx, vy = (out(i) for i in OUT[b])
        r = rest(b)
        rv = [R.rotation(mode, r, a) for a in range(3)]
        rq = wxyz_to_rot([r] * len(vx))
        euler = R._euler(r, 0)
        comp = lambda vx_, vy_, vz_: R.compose(mode, (vx_, vy_, vz_))
        z = np.zeros_like(vx)
        cands = {
            'drop_whole_rest': rot_seq(comp, vx, vy, z),
            'rest*comp': rq * rot_seq(comp, vx, vy, z),
            'comp*rest': rot_seq(comp, vx, vy, z) * rq,
            'replace_written_in_type_decomposition': rot_seq(comp, vx, vy, np.full_like(vx, rv[2])),
            'replace_written_in_euler': rot_seq(lambda a, b_: R.from_euler_xyz((a, b_, euler[2])), vx, vy),
        }
        res['types_456_replace'][f'{b} (type {R.TARGET_MODES and {"swing_twist": 4, "twist_swing": 5, "rotvec": 6}[mode]})'] = \
            rank(q(b), cands)

    # H: type 14, bit0 = 0, Y written
    vy = out(OUT['H'])
    r = rest('H')
    rq = wxyz_to_rot([r] * len(vy))
    axis = rot_seq(lambda v: R._axis_q(1, v), vy)
    e = R._euler(r, 0)
    res['type14_replace'] = rank(q('H'), {
        'drop_whole_rest': axis, 'rest*axis': rq * axis, 'axis*rest': axis * rq,
        'replace_Y_in_euler': rot_seq(lambda v: R.from_euler_xyz((e[0], v, e[2])), vy)})

    # G: X added (F49), Y replaced (F48) on a multi-axis rest
    vx, vy = (out(i) for i in OUT['G'])
    r = rest('G')
    rq = wxyz_to_rot([r] * len(vx))
    e = R._euler(r, 0)
    z = np.zeros_like(vx)

    def via_basis(rep, add):
        def f(a, b_):
            vals = {0: a, 1: b_}
            basis = R.override_basis(r, {k: vals[k] for k in rep}, {k: vals[k] for k in add})
            return R.qmul(r, R.from_euler_xyz(basis))
        return rot_seq(f, vx, vy)

    res['mixed_euler_add_replace'] = rank(q('G'), {
        'override_basis (X added, Y replaced)': via_basis({1}, {0}),
        'both added: rest*R(x,y,0)': rq * rot_seq(lambda a, b_: R.from_euler_xyz((a, b_, 0.0)), vx, vy),
        'both replaced: euler(x,y,rest z)': rot_seq(lambda a, b_: R.from_euler_xyz((a, b_, e[2])), vx, vy),
        'swapped roles (X replaced, Y added)': via_basis({0}, {1}),
        'drop whole rest: R(x,y,0)': rot_seq(lambda a, b_: R.from_euler_xyz((a, b_, 0.0)), vx, vy),
        'only X added (Y entry ignored)': rq * rot_seq(lambda a: R.from_euler_xyz((a, 0.0, 0.0)), vx),
        'only Y replaced (X entry ignored)': rot_seq(lambda b_: R.from_euler_xyz((e[0], b_, e[2])), vy)})

    # I: types 1, 4, 1 on one bone
    vx, vy, vz = (out(i) for i in OUT['I'])
    r = rest('I')
    rq = wxyz_to_rot([r] * len(vx))
    z = np.zeros_like(vx)
    eul = lambda a, b_, c: R.from_euler_xyz((a, b_, c))
    st = lambda a, b_, c: R.compose('swing_twist', (a, b_, c))
    res['mixed_types'] = rank(q('I'), {
        'last entry is type 1: rest*euler(x,0,z)': rq * rot_seq(eul, vx, z, vz),
        'all as euler: rest*euler(x,y,z)': rq * rot_seq(eul, vx, vy, vz),
        'all as swing-twist: rest*st(x,y,z)': rq * rot_seq(st, vx, vy, vz),
        'type 4 entry alone: rest*st(0,y,0)': rq * rot_seq(st, z, vy, z),
        'per channel: rest*euler(x,0,z)*st(0,y,0)': rq * rot_seq(eul, vx, z, vz) * rot_seq(st, z, vy, z),
        'per channel: rest*st(0,y,0)*euler(x,0,z)': rq * rot_seq(st, z, vy, z) * rot_seq(eul, vx, z, vz),
        'first entry is type 1 and takes the Y value too: rest*euler(x,y,z)': rq * rot_seq(eul, vx, vy, vz),
        'unchanged rest': rq})

    # J K: UnknownFloat2 against the control
    a_out = out(8)
    rq = wxyz_to_rot([rest('A')] * len(a_out))
    res['parent_float2'] = {}
    for b in 'JK':
        o = out(OUT[b])
        res['parent_float2'][b] = dict(
            out_vs_control_max_rad=float(np.abs(o - a_out).max()),
            pose_vs_rest_times_out_deg=float(ang(q(b), wxyz_to_rot([rest(b)] * len(o)) * Rot.from_euler('x', o[:, None])).max()),
            pose_vs_control_deg=float(ang(q(b), q('A')).max()))

    # E F: a scale read through InputType 2
    rs = {b: np.array([1.0, 1.0, 1.0]) for b in 'ABCDEFGHIJK'}
    rs['E'] = rs['F'] = np.array([1.4, 0.7, 1.8])
    reads = np.degrees(np.stack([out(i) for i in OUT['E']], axis=1))
    res['scale_source_static'] = dict(
        read_mean=reads.mean(axis=0).round(4).tolist(), read_std=reads.std(axis=0).round(6).tolist(),
        rest_scale=rs['E'].tolist(), pose_scale_if_unit=[1.0, 1.0, 1.0])
    driven = out(OUT['F'][0])                         # scale Y entry's output, the value written
    read = np.degrees(out(OUT['F'][1]))
    written = np.asarray(T['TestTgtF_sy'], float)[sl]
    ratio = read / driven
    res['scale_source_driven'] = dict(
        written_scale_vs_entry_output_max=float(np.abs(written - driven).max()),
        read_over_written_mean=float(ratio.mean()), read_over_written_spread=float(ratio.max() - ratio.min()),
        hypotheses={'absolute (ratio 1)': 1.0, 'x rest (0.7)': 0.7, '/ rest (1/0.7)': 1 / 0.7})
    return res


# ── self-test ───────────────────────────────────────────────────────────────

def synthetic(n=900, seed=5):
    t = np.arange(n, dtype=float)
    x = np.radians(65) * np.sin(t / 41.0) + np.radians(-25)
    rng = np.random.default_rng(seed)
    x = x + 0.05 * rng.normal(size=n).cumsum() / 30
    S, K, T = ({'Frame': t.copy()} for _ in range(3))
    gains = {'X': 0.5, 'Y': 0.8, 'Z': -0.9}
    rests = {b: np.array([1.0, 0, 0, 0]) for b in 'ABCDEFGHIJK'}

    def rest_of(eul):
        q = R.from_euler_xyz(eul)
        return np.array(q)

    for b in 'ABCDEFGHIJK':
        rests[b] = rest_of((math.radians(-2), 0, 0))
    for b in 'BCDG':
        rests[b] = rest_of(tuple(math.radians(v) for v in (-2, 17, -23)))

    def setq(b, rot):
        for a, col in zip('xyzw', rot.as_quat().T):
            K[f'TestTgt{b}_q{a}'] = col

    def o(i, v):
        S[f'Out{i}'] = v

    for i in range(0, 8):
        o(i, np.zeros(n))
    o(8, 0.5 * x)
    rot_of = lambda f, *c: wxyz_to_rot([f(*v) for v in zip(*c)])
    full = lambda b: wxyz_to_rot([rests[b]] * n)
    for b in 'ABCDEFGHIJK':
        setq(b, full(b))
    setq('A', full('A') * Rot.from_euler('x', (0.5 * x)[:, None]))
    # truth: bit0 = 0 replaces the written channels in the type's own decomposition
    for b, mode in TYPE_MODE.items():
        vx, vy = gains['X'] * x, gains['Y'] * x
        o(OUT[b][0], vx)
        o(OUT[b][1], vy)
        rz = R.rotation(mode, tuple(rests[b]), 2)
        setq(b, rot_of(lambda a, c: R.compose(mode, (a, c, rz)), vx, vy))
    # truth: type 14 F48 drops the whole rest
    vy = gains['Y'] * x
    o(OUT['H'], vy)
    setq('H', rot_of(lambda v: R._axis_q(1, v), vy))
    # truth: G follows override_basis (X added, Y replaced)
    vx, vy = gains['X'] * x, gains['Y'] * x
    o(OUT['G'][0], vx)
    o(OUT['G'][1], vy)

    def g_q(a, c):
        basis = R.override_basis(tuple(rests['G']), {1: c}, {0: a})
        return R.qmul(tuple(rests['G']), R.from_euler_xyz(basis))
    setq('G', rot_of(g_q, vx, vy))
    # truth: mixed types -> the last entry's type (1) decides, the type 4 entry is ignored
    vx, vy, vz = (gains[a] * x for a in 'XYZ')
    for i, v in zip(OUT['I'], (vx, vy, vz)):
        o(i, v)
    setq('I', full('I') * rot_of(lambda a, c: R.from_euler_xyz((a, 0.0, c)), vx, vz))
    # truth: UnknownFloat2 does nothing
    for b in 'JK':
        o(OUT[b], 0.5 * x)
        setq(b, full(b) * Rot.from_euler('x', (0.5 * x)[:, None]))
    # truth: a scale source reads the absolute scale
    for i, s in zip(OUT['E'], (1.4, 0.7, 1.8)):
        o(i, np.radians(np.full(n, s)))
    scale_y = 1.0 + 0.01 * np.degrees(x)
    o(OUT['F'][0], scale_y)
    o(OUT['F'][1], np.radians(scale_y))
    T['TestTgtF_sy'] = scale_y
    return dict(sweep=S, skel=K, trs=T, world={'Frame': t.copy()}), rests


def self_test():
    F, rests = synthetic()
    res = analyze(F, rests)
    assert res['sanity']['control_A_err_deg'] < 1e-3, res['sanity']
    for k, v in res['types_456_replace'].items():
        top = v['ranked'][0]
        assert top['candidate'] == 'replace_written_in_type_decomposition' and top['max_error'] < 1e-3 and v['clear'], (k, v['ranked'][:3])
    top = res['type14_replace']['ranked'][0]
    assert top['candidate'] == 'drop_whole_rest' and top['max_error'] < 1e-3
    top = res['mixed_euler_add_replace']['ranked'][0]
    assert top['candidate'].startswith('override_basis') and top['max_error'] < 1e-3, res['mixed_euler_add_replace']['ranked'][:3]
    top = res['mixed_types']['ranked'][0]
    assert top['candidate'].startswith('last entry is type 1') and top['max_error'] < 1e-3, res['mixed_types']['ranked'][:3]
    for b, v in res['parent_float2'].items():
        assert v['out_vs_control_max_rad'] < 1e-9 and v['pose_vs_control_deg'] < 1e-3
    assert np.allclose(res['scale_source_static']['read_mean'], [1.4, 0.7, 1.8], atol=1e-6)
    d = res['scale_source_driven']
    assert abs(d['read_over_written_mean'] - 1.0) < 1e-9 and d['written_scale_vs_entry_output_max'] < 1e-9
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
    rests = {b: np.array(v) for b, v in
             ((k, r['quaternion_wxyz']) for k, r in json.loads(a.plan.read_text(encoding='utf-8'))['rests'].items())}
    res = analyze(load(a.data), rests)
    text = json.dumps(res, indent=1, ensure_ascii=False)
    if a.json:
        a.json.write_text(text, encoding='utf-8')
    print(text)


if __name__ == '__main__':
    main()
