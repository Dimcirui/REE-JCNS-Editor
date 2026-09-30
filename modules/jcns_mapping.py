"""
The three-point piecewise transfer function.

This is the only implementation of the curve: the driver-namespace function
jcns_drivers.jcns_ch, the UI read-outs and the curve preview all call
eval_piecewise, so a panel always reports what the driver produces.  No `bpy`
import.

Anchors are in the file's own units (degrees, centimetres; see driver_anchors):

    A = (from_start, to_start)   first endpoint
    B = (from_kink,  to_kink)    slope change
    C = (from_end,   to_end)     second endpoint

Segment 1 maps [A.x -> B.x] onto [A.y -> B.y], segment 2 [B.x -> C.x] onto
[B.y -> C.y]; both are strictly linear, and outside the range the output clamps
to the nearer segment's bound.

The per-source byte at +24 (`CurveMode`; RE_Engine_JCNS.bt misnames it
UpdateTiming) selects the shape:

    0, 1  two-point: the kink is ignored; straight line A -> C
    2, 3  three-point: the piecewise curve above
    4, 5  unknown; treated as three-point

Degenerate anchors:

    two-point    collapsing a segment changes nothing; all three `from` equal
                 -> flat 0.
    three-point  start == kink -> segment 2 governs, `to_start` ignored;
                 kink == end   -> segment 1 governs, `to_end` ignored;
                 all three equal -> step at the kink from `to_start` to
                 `to_end`, `to_kink` unused;
                 a descending `from` range equals the ascending one;
                 a kink strictly outside [start, end] kills the source: flat 0.
"""

from jcns_source_read import read_quantity, read_mode_value, euler_order_value  # noqa: F401


# +25 (ReadMode), see jcns_source_read.READ_MODES: 0 reads position, 2 scale,
# the rest are four decompositions of the rotation.


def source_quantity(read_mode):
    """'Translation', 'Rotation' or 'Scale' for a +25 ReadMode (value or
    identifier; None -> Rotation)."""
    if read_mode is None:
        return 'Rotation'
    return read_quantity(read_mode)


def source_quantity_of(source):
    """source_quantity() of a parser dict or a JCNSSourceProperties instance."""
    if isinstance(source, dict):
        v = source.get('ReadMode', source.get('read_mode'))
    else:
        v = getattr(source, 'read_mode', None)
    return source_quantity(v)


# Set by the Blender side, which knows the skeleton: source -> rest input or None.
_rest_resolver = None


def set_rest_resolver(fn):
    """Install (or, with None, remove) the lookup behind source_rest_input."""
    global _rest_resolver
    _rest_resolver = fn


def source_rest_input(source):
    """What the source reads with its bone at rest, in the file's units.

    The engine reads the bone's whole parent-relative transform, rest pose and
    offset included, so a bone with a rest rotation or offset does not read 0 at
    rest.  Taken from a dict's 'rest_input', else the installed resolver, else
    an identity rest: 1 for a scale, 0 otherwise.
    """
    if isinstance(source, dict) and source.get('rest_input') is not None:
        return float(source['rest_input'])
    if _rest_resolver is not None:
        try:
            v = _rest_resolver(source)
        except Exception:                 # a UI read-out must never raise
            v = None
        if v is not None:
            return float(v)
    return 1.0 if source_quantity_of(source) == 'Scale' else 0.0


# A jcns stores lengths in centimetres; mot/mesh data, and so a RE Mesh Editor
# armature imported 1:1, is in metres.
CM_PER_UNIT = 100.0

# Driver targets by transform type: which quantity the output is.
_TARGET_QUANTITY = {
    'Translation': 'Translation', 'Scale': 'Scale',
    'Rotation': 'Rotation', 'AxisRotation': 'Rotation', 'AxisRotation_14': 'Rotation',
    'SwingTwist': 'Rotation', 'TwistSwing': 'Rotation', 'RotationVector': 'Rotation',
}


def target_quantity(transform_type):
    """'Translation', 'Rotation', 'Scale' or None for a target transform type."""
    return _TARGET_QUANTITY.get(transform_type)


def quantity_unit(quantity):
    """Display suffix for values of a quantity in the file's own units."""
    return {'Rotation': "°", 'Translation': " cm"}.get(quantity, "")


def source_unit(source):
    """Display suffix for the source side of a mapping."""
    return quantity_unit(source_quantity_of(source))


def _to_driver_units(values, quantity):
    import math
    if quantity == 'Rotation':
        return tuple(math.radians(v) for v in values)
    if quantity == 'Translation':
        return tuple(v / CM_PER_UNIT for v in values)
    return tuple(values)


def driver_anchors(values, source_quantity, target_quantity):
    """(fs, fk, fe, ts, tk, te) in a Blender driver's own units.

    The input side converts by the source's quantity, the output side by the
    target's, independently.  Rotations go to radians, translations to metres,
    scales stay as they are.
    """
    fs, fk, fe, ts, tk, te = values
    return (_to_driver_units((fs, fk, fe), source_quantity)
            + _to_driver_units((ts, tk, te), target_quantity))


def is_two_point(curve_mode):
    """Does this +24 CurveMode value select the two-point curve?

    Matches the known values 0 and 1 rather than testing bit 1, since 4 and 5
    are unknown.
    """
    return curve_mode in (0, 1)


def curve_mode_value(source):
    """The CurveMode byte of a source: the parser dict's `CurveMode` / `curve_mode`, or the
    Blender PropertyGroup's `three_point` (bit 1) plus `curve_mode_extra` (the other bits)."""
    if isinstance(source, dict):
        return source.get('CurveMode', source.get('curve_mode', 3))
    return (int(source.curve_mode_extra) & ~2) | (2 if source.three_point else 0)


def source_two_point(source):
    """Does this source use the two-point curve?"""
    return is_two_point(curve_mode_value(source))


INTERPOLATION_SMOOTHSTEP = 3


def source_smooth(source):
    """Does this source ease each segment (interpolation byte +28 = 3)?  Parser dicts carry it
    in the low byte of `UnknownUInt32_28`, the PropertyGroup in `interpolation`."""
    if isinstance(source, dict):
        return (int(source.get('UnknownUInt32_28', 0)) & 0xFF) == INTERPOLATION_SMOOTHSTEP
    return getattr(source, 'interpolation', 'LINEAR') == 'SMOOTHSTEP'


def is_folded(from_start, from_kink, from_end):
    """Does the polyline double back on itself along x?

    True when the kink lies strictly outside the [start, end] span (a '<' or
    '>' shape).  In three-point mode such a source outputs a flat 0; in
    two-point mode the kink is ignored.
    """
    lo, hi = (from_start, from_end) if from_start <= from_end else (from_end, from_start)
    return from_kink < lo - 1e-9 or from_kink > hi + 1e-9


def eval_piecewise(from_start, from_kink, from_end,
                   to_start, to_kink, to_end, x, two_point=False, smooth=False):
    """Output of the transfer function for a source value of `x`.

    `smooth` is the source's interpolation byte +28 = 3: each segment eases in and out
    (cubic smoothstep, measured on a two-point source) instead of running straight.
    """
    span1 = from_kink - from_start
    span2 = from_end - from_kink
    total = from_end - from_start

    def seg(x0, y0, x1, y1, span):
        if smooth:
            t = max(0.0, min(1.0, (x - x0) / span))
            return y0 + (y1 - y0) * t * t * (3.0 - 2.0 * t)
        k = (y1 - y0) / span
        lo, hi = min(y0, y1), max(y0, y1)
        return max(lo, min(hi, y0 + (x - x0) * k))

    if two_point:
        if abs(total) < 1e-9:
            return 0.0
        return seg(from_start, to_start, from_end, to_end, total)

    if is_folded(from_start, from_kink, from_end):
        return 0.0

    if abs(span1) < 1e-9 and abs(span2) < 1e-9:
        return to_start if x <= from_kink else to_end
    if abs(span2) < 1e-9:                      # only segment 1 is live
        return seg(from_start, to_start, from_kink, to_kink, span1)
    if abs(span1) < 1e-9:                      # only segment 2 is live
        return seg(from_kink, to_kink, from_end, to_end, span2)

    # Segment by which side of the kink `x` is on; a descending range flips it.
    on_first = (x <= from_kink) if from_start <= from_end else (x >= from_kink)
    if on_first:
        return seg(from_start, to_start, from_kink, to_kink, span1)
    return seg(from_kink, to_kink, from_end, to_end, span2)


def rest_position(from_start, from_kink, from_end):
    """Where input 0 sits relative to the MapFrom anchors: 'A', 'B', 'C',
    'inside' or 'outside'.  Callers shift the anchors by the rest input first."""
    if abs(from_start) < 1e-6:
        return 'A'
    if abs(from_end) < 1e-6:
        return 'C'
    if abs(from_kink) < 1e-6:
        return 'B'
    lo, hi = min(from_start, from_end), max(from_start, from_end)
    return 'inside' if lo < 0.0 < hi else 'outside'


def describe(source):
    """Diagnose one source mapping (parser dict or JCNSSourceProperties):
    output at rest and at each anchor, rest position, and dead/inert state."""
    def g(name):
        if isinstance(source, dict):
            return float(source.get(name, 0.0) or 0.0)
        return float(getattr(source, name, 0.0))

    fs, fk, fe = g('from_start'), g('from_kink'), g('from_end')
    ts, tk, te = g('to_start'), g('to_kink'), g('to_end')

    tp = source_two_point(source)
    sm = source_smooth(source)
    r = source_rest_input(source)
    at_rest = eval_piecewise(fs, fk, fe, ts, tk, te, r, two_point=tp, smooth=sm)
    return {
        'at_rest':    at_rest,
        'rest_input': r,
        'at_start':   eval_piecewise(fs, fk, fe, ts, tk, te, fs, two_point=tp, smooth=sm),
        'at_kink':    eval_piecewise(fs, fk, fe, ts, tk, te, fk, two_point=tp, smooth=sm),
        'at_end':     eval_piecewise(fs, fk, fe, ts, tk, te, fe, two_point=tp, smooth=sm),
        'rest_pos':   rest_position(fs - r, fk - r, fe - r),
        'two_point':  tp,
        'smooth':     sm,
        'folded_dead': (not tp) and is_folded(fs, fk, fe),
        # Deflected before anything moves; usually a hand-editing mistake.
        'offset_at_rest': abs(at_rest) > 1e-4,
        'inert': abs(ts) < 1e-9 and abs(tk) < 1e-9 and abs(te) < 1e-9,
        'from': (fs, fk, fe),
        'to':   (ts, tk, te),
    }


def describe_channel(sources):
    """Diagnose a driven channel from the sources of the constraint that owns it.

    Sources within one constraint are summed.  Pass only the live constraint's
    sources: where several constraints target one channel the engine keeps the
    last.
    """
    infos = [describe(s) for s in sources]
    at_rest = sum(i['at_rest'] for i in infos)
    return {
        'at_rest': at_rest,
        'offset_at_rest': abs(at_rest) > 1e-4,
        'n_sources': len(infos),
        'all_inert': bool(infos) and all(i['inert'] for i in infos),
        'sources': infos,
    }


def would_swapping_ends_help(source):
    """True when exchanging to_start and to_end removes a rest-pose deflection.

    Catches a descending MapFrom (e.g. [-60, -15, 0]) whose deflection was
    written into to_end, the anchor that holds at rest.
    """
    info = describe(source)
    if not info['offset_at_rest']:
        return False
    fs, fk, fe = info['from']
    ts, tk, te = info['to']
    swapped = {'from_start': fs, 'from_kink': fk, 'from_end': fe,
               'to_start': te, 'to_kink': tk, 'to_end': ts}
    return not describe(swapped)['offset_at_rest']


def plain_description(source, unit="°"):
    """Describe the mapping walking outward from the rest input in each
    direction, since the rest pose need not be anchor A.

    Returns a dict:
        rest_output   output while nothing is moving
        legs          [{'direction': +1/-1, 'steps': [(from, to, out0, out1, kind)]}]
                      kind is 'dead' (no response) or 'move'
        inert         True when the mapping can never produce output
    """
    def g(name):
        if isinstance(source, dict):
            return float(source.get(name, 0.0) or 0.0)
        return float(getattr(source, name, 0.0))

    fs, fk, fe = g('from_start'), g('from_kink'), g('from_end')
    ts, tk, te = g('to_start'), g('to_kink'), g('to_end')
    tp = source_two_point(source)
    sm = source_smooth(source)
    r = source_rest_input(source)

    at_rest = eval_piecewise(fs, fk, fe, ts, tk, te, r, two_point=tp, smooth=sm)
    inert = abs(ts) < 1e-9 and abs(tk) < 1e-9 and abs(te) < 1e-9

    # Sample eval_piecewise rather than joining sorted anchors: unordered
    # anchors can leave one unreachable, and only sampling reports what the
    # driver actually does.
    lo, hi = min(r, fs, fk, fe), max(r, fs, fk, fe)
    if hi - lo < 1e-9:
        return {'rest_output': at_rest, 'legs': [], 'inert': inert,
                'offset_at_rest': abs(at_rest) > 1e-4,
                'anchors_ordered': True, 'unreachable_anchor': None}

    n = 401
    step = (hi - lo) / (n - 1)
    pts = [(lo + i * step, eval_piecewise(fs, fk, fe, ts, tk, te, lo + i * step, two_point=tp, smooth=sm))
           for i in range(n)]

    # Merge samples into straight runs; a slope change starts a new run.
    runs = []
    i = 0
    while i < len(pts) - 1:
        x0, y0 = pts[i]
        j = i + 1
        slope = (pts[j][1] - y0) / (pts[j][0] - x0)
        while j < len(pts) - 1:
            nxt = (pts[j + 1][1] - y0) / (pts[j + 1][0] - x0)
            if abs(nxt - slope) > 1e-4 * max(1.0, abs(slope)):
                break
            slope = nxt
            j += 1
        runs.append((x0, pts[j][0], y0, pts[j][1]))
        i = j

    # Snap breakpoints from the nearest sample back onto the exact anchor.
    def snap(x):
        for a in (r, fs, fk, fe):
            if abs(x - a) <= step * 1.5:
                return a
        return x

    runs = [(snap(x0), snap(x1),
             eval_piecewise(fs, fk, fe, ts, tk, te, snap(x0), two_point=tp, smooth=sm),
             eval_piecewise(fs, fk, fe, ts, tk, te, snap(x1), two_point=tp, smooth=sm))
            for x0, x1, y0, y1 in runs]

    legs = []
    for direction in (+1, -1):
        steps = []
        ordered = runs if direction > 0 else list(reversed(runs))
        for x0, x1, y0, y1 in ordered:
            a, b = (x0, x1) if direction > 0 else (x1, x0)
            u, v = (y0, y1) if direction > 0 else (y1, y0)
            if (b <= r + 1e-6) if direction > 0 else (b >= r - 1e-6):
                continue                       # entirely on the other side
            a = max(a, r) if direction > 0 else min(a, r)
            if abs(b - a) < 1e-6:
                continue                       # zero-width run at a breakpoint
            u = eval_piecewise(fs, fk, fe, ts, tk, te, a, two_point=tp, smooth=sm)
            kind = 'dead' if abs(v - u) < 1e-4 else 'move'
            if steps and steps[-1][4] == kind == 'dead':
                steps[-1] = (steps[-1][0], b, steps[-1][2], v, 'dead')
            else:
                steps.append((a, b, u, v, kind))
        if steps:
            legs.append({'direction': direction, 'steps': steps})

    ordered_anchors = not is_folded(fs, fk, fe)
    folded_dead = (not tp) and not ordered_anchors

    # Anchor the function never reaches; not reported for a dead source.
    unreachable = None
    if not ordered_anchors and not folded_dead:
        for name, ax, ay in (('A', fs, ts), ('B', fk, tk), ('C', fe, te)):
            if abs(eval_piecewise(fs, fk, fe, ts, tk, te, ax, two_point=tp, smooth=sm) - ay) > 1e-4:
                unreachable = name
                break

    return {'rest_output': at_rest, 'legs': legs, 'inert': inert,
            'offset_at_rest': abs(at_rest) > 1e-4,
            'anchors_ordered': ordered_anchors,
            'two_point': tp,
            'smooth': sm,
            'folded_dead': folded_dead,
            'unreachable_anchor': unreachable}


def sample(source, n=48):
    """[(x, y), …] across the MapFrom span and 0, padded 8%, for plotting."""
    def g(name):
        if isinstance(source, dict):
            return float(source.get(name, 0.0) or 0.0)
        return float(getattr(source, name, 0.0))

    fs, fk, fe = g('from_start'), g('from_kink'), g('from_end')
    ts, tk, te = g('to_start'), g('to_kink'), g('to_end')
    tp = source_two_point(source)
    sm = source_smooth(source)

    lo, hi = min(fs, fe, 0.0), max(fs, fe, 0.0)
    if hi - lo < 1e-9:
        hi = lo + 1.0
    pad = (hi - lo) * 0.08
    lo, hi = lo - pad, hi + pad
    step = (hi - lo) / float(n - 1)
    return [(lo + i * step,
             eval_piecewise(fs, fk, fe, ts, tk, te, lo + i * step, two_point=tp, smooth=sm))
            for i in range(n)]
