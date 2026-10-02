"""
analyze_sections_rig.py -- round 12 (build_sections_rig.py): what do Aim, RotExpression and
Multi do to a bone?

    python scripts/probes/analyze_sections_rig.py --data <round12_keep> --plan <round11_plan.json>
    python scripts/probes/analyze_sections_rig.py --self-test

Reads jcns_cm_rig_{sweep,skel,trs,world}.csv, aligned by Frame.  Nothing here assumes an
answer: every question is put as a set of candidate formulas, each predicting the bone's
recorded pose, ranked by the worst-frame error, and a verdict needs the runner-up to be
at least 10x worse.  Model-free numbers come first (a quantity the engine keeps constant
shows up as a constant in the bone's own frame).

  Aim      u = R^T * dir(aimed bone -> target): constant if Vec1 is the aim axis.  Then
           candidates: shortest arc from the rest pose, and a full look-at of
           (Vec1 -> direction, Vec2 -> up) for three up references.
  Multi     T.pos = sum_i alpha_i * p_i + sum_i R_i * c_i  (alpha free) fits the weights
           the engine used; the rotation is regressed on sum_i R_i C_i the same way.
  RotExpr  the source's rotation read as Euler angles / rotation vector / quaternion
           components, times the coefficients, composed with the rest pose or replacing it.
"""
import argparse
import itertools
import json
import math
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation as Rot

AXIS = {'X': 0, 'Y': 1, 'Z': 2}


# ── loading ─────────────────────────────────────────────────────────────────

def read_csv(path):
    with open(path, encoding='utf-8') as f:
        names = f.readline().strip().split(',')
    data = np.genfromtxt(path, delimiter=',', skip_header=1)
    if data.ndim != 2 or len(data) == 0:
        raise ValueError(f'empty capture: {path}')
    return {n: data[:, i] for i, n in enumerate(names)}


def load(data_dir):
    d = Path(data_dir)
    files = {k: read_csv(d / f'jcns_cm_rig_{k}.csv') for k in ('sweep', 'skel', 'trs', 'world')}
    frames = files['sweep']['Frame']
    for k, v in files.items():
        if not np.array_equal(v['Frame'], frames):
            raise ValueError(f'frame sets differ: {k}')
    if len(set(frames.tolist())) != len(frames):
        raise ValueError('duplicate frames')
    return files


def quat_cols(tab, prefix):
    q = np.stack([tab[f'{prefix}_q{a}'] for a in 'xyzw'], axis=1)
    if not np.isfinite(q).all():
        raise ValueError(f'{prefix}: missing or non-finite quaternion (recorder getter?)')
    return Rot.from_quat(q / np.linalg.norm(q, axis=1, keepdims=True))


def pos_cols(tab, prefix):
    p = np.stack([tab[f'{prefix}_p{a}'] for a in 'xyz'], axis=1)
    if not np.isfinite(p).all():
        raise ValueError(f'{prefix}: missing or non-finite position (recorder getter?)')
    return p


def ang(a, b):
    """Per-frame angle in degrees between two Rotation arrays."""
    return np.degrees((a.inv() * b).magnitude())


def unit(v):
    return v / np.linalg.norm(v, axis=-1, keepdims=True)


def report_rank(cands):
    """cands: {name: max error}.  -> ranked list and whether the winner is 10x clear."""
    ranked = sorted(cands.items(), key=lambda kv: kv[1])
    clear = len(ranked) < 2 or ranked[1][1] > 10 * max(ranked[0][1], 1e-9)
    return dict(ranked=[dict(candidate=k, max_error=float(v)) for k, v in ranked], clear=bool(clear))


# ── sanity ──────────────────────────────────────────────────────────────────

def sanity(F, rests):
    S, K, W = F['sweep'], F['skel'], F['world']
    x = S['Out8'] / 0.5
    span = float(np.degrees(np.ptp(x)))
    if span < 30:
        raise ValueError(f'input span {span:.1f} deg < 30')
    a = quat_cols(K, 'TestTgtA')
    ra = Rot.from_quat(rests['A'][[1, 2, 3, 0]])
    control = float(ang(a, ra * Rot.from_euler('x', S['Out8'][:, None])).max())
    # the world recorder: a bone that nothing drives must stay rigid under Ear_SCL
    ear_p, ear_q = pos_cols(W, 'e.Ear_SCL'), quat_cols(W, 'e.Ear_SCL')
    g_p, g_q = pos_cols(W, 'e.TestTgtG'), quat_cols(W, 'e.TestTgtG')
    rel_p = ear_q.inv().apply(g_p - ear_p)
    rel_q = ear_q.inv() * g_q
    return dict(frames=len(x), input_span_deg=span, control_A_err_deg=control,
                G_rel_pos_spread_m=float(np.ptp(rel_p, axis=0).max()),
                G_rel_rot_spread_deg=float(ang(rel_q, rel_q[0]).max()))


# ── Aim ─────────────────────────────────────────────────────────────────────

def frame_from(primary, secondary):
    """Rotation matrices whose columns are (primary, orth(secondary), cross), per frame."""
    a = unit(primary)
    b = secondary - np.sum(secondary * a, axis=-1, keepdims=True) * a
    b = unit(b)
    c = np.cross(a, b)
    return np.stack([a, b, c], axis=-1)


def shortest_arc(a, b):
    """Rotation taking unit vectors a to b."""
    axis = np.cross(a, b)
    s = np.linalg.norm(axis, axis=1)
    c = np.sum(a * b, axis=1)
    angle = np.arctan2(s, c)
    axis = axis / np.maximum(s, 1e-12)[:, None]
    return Rot.from_rotvec(axis * angle[:, None])


def analyze_aim(W, K, rests, bone, vec1, vec2, target, up_bone, shifts=(-2, -1, 0, 1, 2)):
    tag = f'e.TestTgt{bone}'
    P, R = pos_cols(W, tag), quat_cols(W, tag)
    ear_q = quat_cols(W, 'e.Ear_SCL')
    rest_local = Rot.from_quat(rests[bone][[1, 2, 3, 0]])
    local = quat_cols(K, f'TestTgt{bone}')
    moved = float(ang(local, local[0]).max())
    res = dict(bone=bone, local_rotation_range_deg=moved)
    best = None
    for src in ('b', 'e'):
        T = pos_cols(W, f'{src}.{target}')
        for k in shifts:
            Tk = np.roll(T, k, axis=0)
            d = unit(Tk - P)
            u = R.inv().apply(d)
            mean = unit(u.mean(axis=0, keepdims=True))[0]
            spread = float(np.degrees(np.arccos(np.clip(u @ mean, -1, 1))).max())
            if best is None or spread < best['max_spread_deg']:
                best = dict(source=src, shift=k, max_spread_deg=spread,
                            mean_local_axis=mean.tolist(), axis_vs_vec1_deg=float(
                                np.degrees(np.arccos(np.clip(mean @ np.array(vec1) / np.linalg.norm(vec1), -1, 1)))))
    res['aim_axis'] = best
    src, k = best['source'], best['shift']
    T = np.roll(pos_cols(W, f'{src}.{target}'), k, axis=0)
    d = unit(T - P)
    v1, v2 = np.array(vec1, float), np.array(vec2, float)
    L = frame_from(v1[None], v2[None])[0]                     # local frame (columns)
    ups = {'world_Y': np.tile([0.0, 1.0, 0.0], (len(d), 1)),
           'parent_Y': ear_q.apply([0.0, 1.0, 0.0])}
    if up_bone:
        U = pos_cols(W, f'{src}.{up_bone}')
        ups['up_bone'] = U - P
        Ur = quat_cols(W, f'{src}.{up_bone}')
        for k, a in enumerate('xyz'):
            unit_axis = np.eye(3)[k]
            ups[f'up_bone_axis_{a}'] = Ur.apply(unit_axis)
            ups[f'up_bone_axis_-{a}'] = -Ur.apply(unit_axis)
    errs = {}
    for name, up in ups.items():
        Wf = frame_from(d, up)
        pred = Rot.from_matrix(Wf @ L.T[None])
        errs['lookat_' + name] = float(ang(R, pred).max())
    rest_world = ear_q * rest_local
    arc = shortest_arc(unit(rest_world.apply(v1)), d)
    errs['shortest_arc_from_rest'] = float(ang(R, arc * rest_world).max())
    errs['unchanged_rest'] = float(ang(R, rest_world).max())
    res['candidates'] = report_rank(errs)
    # up axis, model-free: component of the up reference perpendicular to d, in the bone frame
    ups_local = {}
    for name, up in ups.items():
        w = up - np.sum(up * d, axis=1, keepdims=True) * d
        w = unit(w)
        vloc = R.inv().apply(w)
        m = unit(vloc.mean(axis=0, keepdims=True))[0]
        ups_local[name] = dict(mean=m.tolist(),
                               max_spread_deg=float(np.degrees(np.arccos(np.clip(vloc @ m, -1, 1))).max()))
    res['up_reference_constancy'] = ups_local
    return res


# ── Multi ────────────────────────────────────────────────────────────────────

def analyze_multi(W, K, rests, bone, sources):
    tag = f'e.TestTgt{bone}'
    out = {}
    T, TR = pos_cols(W, tag), quat_cols(W, tag)
    n = len(T)
    nominal = np.array([w for _, w in sources])
    for src in ('b', 'e'):
        P = [pos_cols(W, f'{src}.{name}') for name, _ in sources]
        Rm = [quat_cols(W, f'{src}.{name}').as_matrix() for name, _ in sources]
        ns = len(sources)
        rows = []
        for k in range(3):                                 # output component
            block = np.zeros((n, 4 * ns))
            for i in range(ns):
                block[:, i] = P[i][:, k]
                block[:, ns + 3 * i:ns + 3 * i + 3] = Rm[i][:, k, :]
            rows.append(block)
        A = np.concatenate(rows)                           # (3n, ns + 3 ns)
        y = np.concatenate([T[:, k] for k in range(3)])
        sol, *_ = np.linalg.lstsq(A, y, rcond=None)
        resid = A @ sol - y
        entry = dict(alpha=sol[:ns].tolist(), nominal=nominal.tolist(),
                     normalized=(nominal / nominal.sum()).tolist(),
                     pos_max_resid_m=float(np.abs(resid).max()), condition=float(np.linalg.cond(A)))
        # alpha fixed to nominal / normalized: refit only c
        for label, al in (('nominal', nominal), ('normalized', nominal / nominal.sum())):
            yy = y - np.concatenate([sum(al[i] * P[i][:, k] for i in range(ns)) for k in range(3)])
            Ac = A[:, ns:]
            s2, *_ = np.linalg.lstsq(Ac, yy, rcond=None)
            entry[f'pos_max_resid_alpha_{label}_m'] = float(np.abs(Ac @ s2 - yy).max())
        # rotation: R_T[k,m] = sum_i sum_l R_i[k,l] C_i[l,m]
        Y = TR.as_matrix()
        rot_rows, rot_y = [], []
        for k in range(3):
            for m in range(3):
                blk = np.concatenate([Rm[i][:, k, :] for i in range(ns)], axis=1)   # (n, 3 ns)
                rot_rows.append(blk)
                rot_y.append(Y[:, k, m])
        # the unknown for column m is C[:, m] per source; solve the three columns separately
        C = np.zeros((ns, 3, 3))
        worst = 0.0
        for m in range(3):
            Am = np.concatenate([np.concatenate([Rm[i][:, k, :] for i in range(ns)], axis=1) for k in range(3)])
            ym = np.concatenate([Y[:, k, m] for k in range(3)])
            sm, *_ = np.linalg.lstsq(Am, ym, rcond=None)
            worst = max(worst, float(np.abs(Am @ sm - ym).max()))
            for i in range(ns):
                C[i, :, m] = sm[3 * i:3 * i + 3]
        entry['rot_matrix_max_resid'] = worst
        entry['rot_blend_singular_values'] = [np.linalg.svd(C[i], compute_uv=False).tolist() for i in range(ns)]
        rest = Rot.from_quat(rests[bone][[1, 2, 3, 0]])
        ear_q = quat_cols(W, 'e.Ear_SCL')
        entry['rot_vs_unchanged_rest_deg'] = float(ang(TR, ear_q * rest).max())
        for i, (name, _) in enumerate(sources):
            entry[f'rot_vs_source_{name}_relative_spread_deg'] = float(
                ang(Rot.from_matrix(Rm[i]).inv() * TR, (Rot.from_matrix(Rm[i]).inv() * TR)[0]).max())
        entry['rot_nlerp_running_max_err_deg'] = multi_rotation_nlerp(
            [quat_cols(W, f'{src}.{name}') for name, _ in sources], nominal / nominal.sum(), TR)
        out[src] = entry
    return dict(bone=bone, sources=[s for s, _ in sources], by_source_set=out)


def multi_rotation_nlerp(Rs, w, T, seeds=8):
    """Fit T = normalize(sum_i w_i q_i X_i) with each q_i X_i flipped toward the running
    sum, X_i unknown constant rotations; -> worst-frame error in degrees."""
    from scipy.optimize import least_squares
    n = len(Rs)
    idx = np.arange(0, len(T), max(1, len(T) // 600))
    Rs = [r[idx] for r in Rs]
    T = T[idx]

    def model(p):
        acc = None
        for i in range(n):
            q = (Rs[i] * Rot.from_rotvec(p[3 * i:3 * i + 3])).as_quat()
            if acc is None:
                acc = w[i] * q
            else:
                acc = acc + w[i] * q * np.sign(np.sum(q * acc, axis=1, keepdims=True) + 1e-12)
        return Rot.from_quat(acc / np.linalg.norm(acc, axis=1, keepdims=True))

    best = None
    start = np.concatenate([(Rs[i][0].inv() * T[0]).as_rotvec() for i in range(n)])
    for seed in range(seeds):
        p0 = start if seed == 0 else np.random.default_rng(seed).normal(size=3 * n)
        sol = least_squares(lambda p: ang(T, model(p)), p0, loss='soft_l1', max_nfev=300)
        e = float(ang(T, model(sol.x)).max())
        best = e if best is None else min(best, e)
    return best


# ── RotExpression ───────────────────────────────────────────────────────────

def reads(q, q_ref):
    """The source quantities a coefficient vector could multiply."""
    rel = q_ref.inv() * q
    out = {}
    for label, r in (('raw', q), ('rest_relative', rel)):
        out[f'{label}_euler_xyz'] = r.as_euler('xyz')
        out[f'{label}_rotvec'] = r.as_rotvec()
        qq = r.as_quat()
        out[f'{label}_quat_xyz'] = qq[:, :3] * np.sign(qq[:, 3:4] + 1e-30)
    return out


def analyze_rot(F, rests, bone, source, gains, source_rest_name='L_Thigh'):
    S, K = F['sweep'], F['skel']
    q_src = Rot.from_quat(np.stack([S[f'{source}_q{a}'] for a in 'xyzw'], axis=1))
    q_ref = quat_cols(K, source_rest_name)
    ref_spread = float(ang(q_ref, q_ref[0]).max())
    target = quat_cols(K, f'TestTgt{bone}')
    rest = Rot.from_quat(rests[bone][[1, 2, 3, 0]])
    g = np.array(gains)
    errs = {}
    for name, quant in reads(q_src, q_ref[0]).items():
        if name.endswith('quat_xyz'):
            vals = quant * g
            w = np.sqrt(np.clip(1 - np.sum(vals ** 2, axis=1), 0, None))
            rot = Rot.from_quat(np.concatenate([vals, w[:, None]], axis=1))
            for kind, pred in (('replace', rot), ('rest_times', rest * rot), ('times_rest', rot * rest)):
                errs[f'{name}|{kind}'] = float(ang(target, pred).max())
            continue
        vals = quant * g
        if 'euler' in name:
            for order in ('xyz', 'XYZ', 'zyx'):
                rot = Rot.from_euler(order, vals if order != 'zyx' else vals[:, ::-1])
                for kind, pred in (('replace', rot), ('rest_times', rest * rot), ('times_rest', rot * rest)):
                    errs[f'{name}|{order}|{kind}'] = float(ang(target, pred).max())
        else:
            rot = Rot.from_rotvec(vals)
            for kind, pred in (('replace', rot), ('rest_times', rest * rot), ('times_rest', rot * rest)):
                errs[f'{name}|{kind}'] = float(ang(target, pred).max())
    res = report_rank(errs)
    res['top5'] = res['ranked'][:5]
    del res['ranked']
    res.update(bone=bone, local_rotation_range_deg=float(ang(target, target[0]).max()),
               source_reference_static_spread_deg=ref_spread)
    return res


# ── driver ──────────────────────────────────────────────────────────────────

SPEC = dict(
    aim=[('B', 0, None), ('C', 1, 'L_Hand'), ('D', 2, 'L_Hand'), ('H', 3, None), ('I', 4, None)],
    target='R_Hand', vec1=(1, 0, 0), vec2=(0, 1, 0),
    rot=[('E', (0, 0, 0, 0)), ('F', (0, 48, 0, 0))], rot_source='L_Thigh', rot_gains=(0.5, 0.8, -0.9),
    multi=[('J', [('L_Hand', 0.5), ('R_Hand', 0.3), ('Head', 0.2)]), ('K', [('L_Hand', 0.5), ('R_Hand', 0.25)])])


def rests_from(plan):
    return {b: np.array(v['quaternion_wxyz']) for b, v in plan['rests'].items()}


def run(F, rests):
    out = dict(sanity=sanity(F, rests), aim={}, rot={}, multi={})
    if out['sanity']['control_A_err_deg'] > 0.002:
        out['warning'] = 'control A off: the jcns or mesh in the game is not this round'
    W, K = F['world'], F['skel']
    for b, t, up in SPEC['aim']:
        out['aim'][f'{b}(type {t})'] = analyze_aim(W, K, rests, b, SPEC['vec1'], SPEC['vec2'],
                                                   SPEC['target'], up)
    for b, by in SPEC['rot']:
        out['rot'][f'{b}(bytes {by})'] = analyze_rot(F, rests, b, SPEC['rot_source'], SPEC['rot_gains'])
    ent = {b: q for b, q in zip('EF', [out['rot'][k] for k in out['rot']])}
    E, Fq = quat_cols(K, 'TestTgtE'), quat_cols(K, 'TestTgtF')
    out['rot_E_vs_F_max_deg'] = float(ang(E, Fq).max())
    rest_e = Rot.from_quat(rests['E'][[1, 2, 3, 0]])
    out['rot_F_equals_rest_times_E_max_deg'] = float(ang(Fq, rest_e * E).max())   # F = rest * E exactly?
    for b, srcs in SPEC['multi']:
        out['multi'][b] = analyze_multi(W, K, rests, b, srcs)
    return out


# ── self-test: synthetic captures with known answers ───────────────────────

def synthetic(n=600, seed=1, aim_model='lookat_world_Y', multi_alpha=(0.5, 0.3, 0.2), rot_model='euler'):
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    names = {}

    def put(tab, prefix, p, q):
        for a, col in zip('xyz', p.T):
            tab[f'{prefix}_p{a}'] = col
        for a, col in zip('xyzw', q.as_quat().T):
            tab[f'{prefix}_q{a}'] = col

    def smooth(scale, k):
        x = rng.normal(size=(n, k)).cumsum(axis=0)
        return scale * x / np.abs(x).max()

    W, K, S = {'Frame': t.astype(float)}, {'Frame': t.astype(float)}, {'Frame': t.astype(float)}
    ear_q = Rot.from_rotvec(smooth(0.4, 3))
    ear_p = smooth(0.3, 3) + [0, 1.5, 0]
    put(W, 'e.Ear_SCL', ear_p, ear_q)
    rests = {b: np.array(Rot.from_euler('x', -0.0349).as_quat()[[3, 0, 1, 2]]) for b in 'ABCDEFGHIJK'}
    rest_local = Rot.from_quat(rests['A'][[1, 2, 3, 0]])
    off = np.array([0.0, -0.5955, 0.0134])
    base_p = ear_p + ear_q.apply(off)
    # body bones
    bones = {}
    for name in ('L_Hand', 'R_Hand', 'Head', 'L_Thigh', 'R_Thigh'):
        bones[name] = (smooth(1.0, 3) + rng.normal(size=3), Rot.from_rotvec(smooth(1.5, 3)))
        put(W, 'b.' + name, *bones[name])
        put(W, 'e.' + name, *bones[name])
    # G static, A control
    put(W, 'e.TestTgtG', base_p, ear_q * rest_local)
    x = np.radians(60) * np.sin(t / 37.0)
    S['Out8'] = 0.5 * x
    put(K, 'TestTgtA', np.zeros((n, 3)), Rot.from_quat(rests['A'][[1, 2, 3, 0]]) * Rot.from_euler('x', (0.5 * x)[:, None]))
    put(W, 'e.TestTgtA', base_p, ear_q * rest_local * Rot.from_euler('x', (0.5 * x)[:, None]))
    # aim bones
    T = bones['R_Hand'][0]
    d = unit(T - base_p)
    L = frame_from(np.array([[1.0, 0, 0]]), np.array([[0, 1.0, 0]]))[0]
    for b, typ, up in SPEC['aim']:
        if typ == 2:
            up_axis = bones['L_Hand'][1].apply([0, 1.0, 0])
            Rw = Rot.from_matrix(frame_from(d, up_axis) @ L.T[None])
        elif aim_model == 'lookat_world_Y':
            Rw = Rot.from_matrix(frame_from(d, np.tile([0, 1.0, 0], (n, 1))) @ L.T[None])
        else:
            rw = ear_q * rest_local
            Rw = shortest_arc(unit(rw.apply([1.0, 0, 0])), d) * rw
        put(W, f'e.TestTgt{b}', base_p, Rw)
        put(K, f'TestTgt{b}', np.zeros((n, 3)), ear_q.inv() * Rw)
    # multi: target pinned with known per-source offsets
    a = np.array(multi_alpha)
    for b, srcs in SPEC['multi']:
        al = np.array([w for _, w in srcs]) if b != 'J' else a
        pos = np.zeros((n, 3))
        rot_acc = np.zeros((n, 3, 3))
        for i, (nm, _) in enumerate(srcs):
            p_i, r_i = bones[nm]
            c = np.array([0.1 * (i + 1), -0.2, 0.05 * i])
            pos += al[i] * (r_i.apply(c) + p_i)
            rot_acc += al[i] * r_i.as_matrix()
        acc, xs = None, [Rot.from_rotvec([0.3 * (i + 1), 0.2, -0.1]) for i in range(len(srcs))]
        for i, (nm, _) in enumerate(srcs):
            qq = (bones[nm][1] * xs[i]).as_quat()
            acc = al[i] * qq if acc is None else acc + al[i] * qq * np.sign(np.sum(qq * acc, axis=1, keepdims=True))
        put(W, f'e.TestTgt{b}', pos, Rot.from_quat(acc / np.linalg.norm(acc, axis=1, keepdims=True)))
        put(K, f'TestTgt{b}', np.zeros((n, 3)), Rot.from_quat(np.tile([0, 0, 0, 1.0], (n, 1))))
    # rot expression
    src_q = bones['L_Thigh'][1]
    for k, (prefix, val) in enumerate((('L_Thigh', src_q),)):
        for ax, col in zip('xyzw', val.as_quat().T):
            S[f'{prefix}_q{ax}'] = col
    src_rest = Rot.from_rotvec([0.1, 0.05, -0.08])
    put(K, 'L_Thigh', np.zeros((n, 3)), Rot.from_quat(np.tile(src_rest.as_quat(), (n, 1))))
    rel = src_rest.inv() * src_q
    g = np.array(SPEC['rot_gains'])
    if rot_model == 'euler':
        pred = rest_local * Rot.from_euler('xyz', rel.as_euler('xyz') * g)
    else:
        pred = Rot.from_rotvec(src_q.as_rotvec() * g)
    for b, _ in SPEC['rot']:
        put(K, f'TestTgt{b}', np.zeros((n, 3)), pred)
    return dict(sweep=S, skel=K, trs={'Frame': t.astype(float)}, world=W), rests


def self_test():
    for aim_model, rot_model in (('lookat_world_Y', 'euler'), ('arc', 'rotvec')):
        F, rests = synthetic(aim_model=aim_model, rot_model=rot_model)
        res = run(F, rests)
        assert res['sanity']['control_A_err_deg'] < 1e-3, res['sanity']
        want = 'lookat_world_Y' if aim_model == 'lookat_world_Y' else 'shortest_arc_from_rest'
        for k, v in res['aim'].items():
            best = v['candidates']['ranked'][0]['candidate']
            if k.startswith('D'):
                assert best == 'lookat_up_bone_axis_y' and v['candidates']['ranked'][0]['max_error'] < 1e-3, (k, v['candidates'])
                continue
            assert best == want or best == 'lookat_' + want.split('_', 1)[-1] or want in best, (k, best)
            assert v['aim_axis']['max_spread_deg'] < 1e-3 or aim_model == 'lookat_world_Y', (k, v['aim_axis'])
        for k, v in res['rot'].items():
            top = v['top5'][0]
            want_rot = 'rest_relative_euler_xyz|xyz|rest_times' if rot_model == 'euler' else 'raw_rotvec|replace'
            assert top['candidate'] == want_rot and top['max_error'] < 1e-3, (k, v['top5'])
        s = res['multi']['J']['by_source_set']['e']
        assert np.allclose(s['alpha'], [0.5, 0.3, 0.2], atol=1e-6), s['alpha']
        assert s['pos_max_resid_m'] < 1e-8
        assert s['rot_nlerp_running_max_err_deg'] < 0.1, s['rot_nlerp_running_max_err_deg']
        s = res['multi']['K']['by_source_set']['e']
        assert np.allclose(s['alpha'], [0.5, 0.25], atol=1e-6), s['alpha']
        assert s['pos_max_resid_alpha_nominal_m'] < 1e-8 and s['pos_max_resid_alpha_normalized_m'] > 1e-4
        print('self-test OK:', aim_model, rot_model)


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
    res = run(load(a.data), rests_from(plan))
    text = json.dumps(res, indent=1, ensure_ascii=False)
    if a.json:
        a.json.write_text(text, encoding='utf-8')
    print(text)


if __name__ == '__main__':
    main()
