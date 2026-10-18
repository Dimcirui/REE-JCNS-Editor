"""
ComplexMapping: a source's keyframed transfer curve, used in place of the
three-point mapping (whose six anchors are then all zero).

  * each ComplexMappingInfo record is one key: FromX is the input, ToX the output;
  * (FromY, ToY) is the incoming tangent and (FromZ, ToZ) the outgoing one, as a
    (dx, dy) vector; segments are cubic Hermite on the slopes dy/dx;
  * the per-key UnknownUInt32 does not affect the result;
  * outside the keyed range each end continues by its wrap mode (the source's +22
    before the first key, +23 after the last): 0 holds the end value, 1 extends the
    end tangent, 2 ping-pongs, 3 repeats, 4 repeats with each cycle offset by the
    rise of the curve (the evaluator names them; only 0 occurs in the shipped files);
  * equal FromX on neighbouring keys make a step.

The shipped layout writes dx as the neighbouring segment length: FromY the one
before the key, FromZ the one after, the first key's FromY a placeholder 1 and
the last key's FromZ a copy of its FromY.  All-zero tangents mean flat tangents.

A Blender Bezier F-Curve with each handle at the key +- (segment dx, rise)/3 is
the same cubic.  No `bpy` import.
"""

import math

# A key: (x, y, slope_in, slope_out), in the file's own units (degrees /
# centimetres / scale factors).


def keys_from_records(records):
    """[(x, y, slope_in, slope_out)] from ComplexMappingInfo dicts."""
    out = []
    for r in records:
        fy, fz = r.get('FromY', 0.0), r.get('FromZ', 0.0)
        s_in = r.get('ToY', 0.0) / fy if fy else 0.0
        s_out = r.get('ToZ', 0.0) / fz if fz else 0.0
        out.append((r['FromX'], r['ToX'], s_in, s_out))
    return out


def records_from_keys(keys, flags=None):
    """ComplexMappingInfo dicts in the shipped layout (see the module docstring).

    `flags` supplies each key's UnknownUInt32; missing entries are 0.
    """
    n = len(keys)
    out = []
    for i, (x, y, s_in, s_out) in enumerate(keys):
        dx_in = x - keys[i - 1][0] if i > 0 else 1.0
        dx_out = keys[i + 1][0] - x if i + 1 < n else dx_in
        out.append({
            'FromX': x, 'ToX': y,
            'FromY': dx_in, 'ToY': s_in * dx_in,
            'FromZ': dx_out, 'ToZ': s_out * dx_out,
            'UnknownUInt32': flags[i] if flags is not None and i < len(flags) else 0,
        })
    return out


# Wrap modes of +22 / +23.
WRAP_CLAMP, WRAP_LINEAR, WRAP_PINGPONG, WRAP_REPEAT, WRAP_OFFSET = range(5)


def evaluate(keys, x, pre=WRAP_CLAMP, post=WRAP_CLAMP):
    """The engine's output for input x.  Keys must be sorted by x; `pre` / `post`
    are the wrap modes before the first and after the last key."""
    if not keys:
        return 0.0
    x0, x1 = keys[0][0], keys[-1][0]
    span = x1 - x0
    if (x < x0 or x > x1) and span > 0.0:
        mode = pre if x < x0 else post
        if mode == WRAP_LINEAR:
            if x < x0:
                return keys[0][1] + (x - x0) * keys[0][3]
            return keys[-1][1] + (x - x1) * keys[-1][2]
        if mode in (WRAP_PINGPONG, WRAP_REPEAT, WRAP_OFFSET):
            cycle = math.floor((x - x0) / span)
            u = x - x0 - cycle * span
            if mode == WRAP_PINGPONG and cycle % 2:
                u = span - u
            y = _inside(keys, x0 + u)
            if mode == WRAP_OFFSET:
                y += cycle * (keys[-1][1] - keys[0][1])
            return y
    if x < x0:
        return keys[0][1]
    if x >= x1:
        return keys[-1][1]
    return _inside(keys, x)


def _inside(keys, x):
    if x >= keys[-1][0]:
        return keys[-1][1]
    # Last segment starting at or before x: at a step the later key applies.
    for i in range(len(keys) - 2, -1, -1):
        x0, y0, _, m0 = keys[i]
        x1, y1, m1, _ = keys[i + 1]
        if x0 <= x and x1 > x0:
            if x > x1:
                continue
            dx = x1 - x0
            t = (x - x0) / dx
            t2, t3 = t * t, t * t * t
            return ((2 * t3 - 3 * t2 + 1) * y0 + (t3 - 2 * t2 + t) * dx * m0
                    + (-2 * t3 + 3 * t2) * y1 + (t3 - t2) * dx * m1)
    return keys[-1][1]


def scaled(keys, x_scale, y_scale):
    """Keys with input and output scaled (unit conversion); slopes follow."""
    k = y_scale / x_scale
    return [(x * x_scale, y * y_scale, a * k, b * k) for x, y, a, b in keys]


def mirrored(keys, in_sign, out_sign):
    """Keys of f_R(x) = out_sign * f_L(in_sign * x) — the ComplexMapping twin of
    jcns_mirror.mirror_triples."""
    out = [(in_sign * x, out_sign * y, out_sign * in_sign * a, out_sign * in_sign * b)
           for x, y, a, b in keys]
    if in_sign < 0:
        # reversed input: incoming and outgoing tangents swap
        out = [(x, y, b, a) for x, y, a, b in reversed(out)]
    return out


def from_mid_point(fs, fk, fe, ts, tk, te, two_point=False):
    """Keys drawing the same segments as a three-point mapping, sorted
    ascending in x."""
    pts = [(fs, ts), (fe, te)] if two_point else [(fs, ts), (fk, tk), (fe, te)]
    pts.sort(key=lambda p: p[0])
    keys = []
    for i, (x, y) in enumerate(pts):
        def slope(a, b):
            return (b[1] - a[1]) / (b[0] - a[0]) if b[0] != a[0] else 0.0
        s_in = slope(pts[i - 1], pts[i]) if i > 0 else (slope(pts[0], pts[1]) if len(pts) > 1 else 0.0)
        s_out = slope(pts[i], pts[i + 1]) if i + 1 < len(pts) else s_in
        keys.append((x, y, s_in, s_out))
    return keys


def same_keys(a, b, tol=1e-5):
    """Do two key lists match within a relative tolerance?"""
    if len(a) != len(b):
        return False
    for ka, kb in zip(a, b):
        for u, v in zip(ka, kb):
            if abs(u - v) > tol * max(1.0, abs(u), abs(v)):
                return False
    return True


def bounds(keys):
    """(x_min, x_max, y_min, y_max) covering the keys and their segments."""
    xs = [k[0] for k in keys] or [0.0]
    ys = [k[1] for k in keys] or [0.0]
    if len(keys) > 1:
        x0, x1 = xs[0], xs[-1]
        ys += [evaluate(keys, x0 + (x1 - x0) * i / 32.0) for i in range(33)]
    return min(xs), max(xs), min(ys), max(ys)
