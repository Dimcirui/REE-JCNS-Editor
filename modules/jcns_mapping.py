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

Bit 1 (MidPoint) of the source's +24 AttrFlags selects the shape, as the engine's
remap does it:

    two-point    t = clamp01((x - A.x) / (C.x - A.x)), eased, then lerp A.y -> C.y;
                 A.x == C.x gives 0.
    three-point  the `from` anchors must be monotone (A <= B <= C, or all descending,
                 when the ends swap roles), else 0.  With low / high the smaller and
                 larger end: below low -> low's output; [low, B) eases low -> B;
                 [B, high) eases B -> high; at or above high -> high's output.  So
                 start == kink gives `to_start` below it and segment 2 above it, and
                 kink == end gives `to_end` from the kink on.  Each segment eases from
                 its lower `from` end, so a descending range runs the ease mirrored.
"""

from jcns_source_read import read_quantity, input_type_value, rot_order_value  # noqa: F401


# +25 (InputType), see jcns_source_read.INPUT_TYPES: 0 reads position, 2 scale,
# the rest are four decompositions of the rotation.


def source_quantity(input_type):
    """'Translation', 'Rotation' or 'Scale' for a +25 InputType (value or
    identifier; None -> Rotation)."""
    if input_type is None:
        return 'Rotation'
    return read_quantity(input_type)


def source_quantity_of(source):
    """source_quantity() of a parser dict or a JCNSSourceProperties instance."""
    if isinstance(source, dict):
        v = source.get('InputType', source.get('input_type'))
    else:
        v = getattr(source, 'input_type', None)
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
    'Trans': 'Translation', 'Scale': 'Scale',
    'Rot': 'Rotation', 'Rot2': 'Rotation', 'RotRPY2': 'Rotation',
    'RotRPY': 'Rotation', 'RotPYR': 'Rotation', 'ExpMap': 'Rotation',
}


def target_quantity(transform_element):
    """'Translation', 'Rotation', 'Scale' or None for a target transform type."""
    return _TARGET_QUANTITY.get(transform_element)


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


def is_two_point(attr_flags):
    """Does this +24 AttrFlags value select the two-point curve?

    Matches the known values 0 and 1 rather than testing bit 1, since 4 and 5
    are unknown.
    """
    return attr_flags in (0, 1)


def attr_flags_value(source):
    """The AttrFlags byte of a source: the parser dict's `AttrFlags` / `attr_flags`, or the
    Blender PropertyGroup's `mid_point` (bit 1) plus `attr_flags_other` (the other bits)."""
    if isinstance(source, dict):
        return source.get('AttrFlags', source.get('attr_flags', 3))
    return (int(source.attr_flags_other) & ~2) | (2 if source.mid_point else 0)


def source_two_point(source):
    """Does this source use the two-point curve?"""
    return is_two_point(attr_flags_value(source))


# Source byte +28, how a segment runs between its anchors (measured, rounds 15 and 16; the
# three-point form is per segment): 0 straight, 1 cubic ease in, 2 cubic ease out, 3 smoothstep.
EASING = {
    1: lambda t: t * t * t,
    2: lambda t: 1.0 - (1.0 - t) ** 3,
    3: lambda t: t * t * (3.0 - 2.0 * t),
}
_INTERPOLATION_IDS = {'LINEAR': 0, 'SLOW': 1, 'FAST': 2, 'SMOOTH': 3}


def source_interpolation(source):
    """The interpolation byte +28 of a source.  Parser dicts carry it in the low byte of
    `Interpolation`, the PropertyGroup in `interpolation`."""
    if isinstance(source, dict):
        return int(source.get('Interpolation', 0))
    return _INTERPOLATION_IDS.get(getattr(source, 'interpolation', 'LINEAR'), 0)


def is_folded(from_start, from_kink, from_end):
    """Are the `from` anchors not monotone (a '<' or '>' shape)?

    In three-point mode such a source outputs a flat 0; in two-point mode the kink
    is ignored.
    """
    return not (from_start <= from_kink <= from_end or from_start >= from_kink >= from_end)


def _ease(interp, t):
    t = 0.0 if t < 0.0 else (t if t < 1.0 else 1.0)
    f = EASING.get(interp)
    return f(t) if f else t


def eval_piecewise(from_start, from_kink, from_end,
                   to_start, to_kink, to_end, x, two_point=False, interp=0):
    """Output of the transfer function for a source value of `x`.

    `interp` is the source's interpolation byte +28: each segment runs straight (0) or
    follows an easing curve (see EASING).
    """
    if two_point:
        if from_start == from_end:
            return 0.0
        return (to_end - to_start) * _ease(interp, (x - from_start) / (from_end - from_start)) + to_start

    if from_start <= from_kink <= from_end:
        low, high, lo, hi = from_start, from_end, to_start, to_end
    elif from_start >= from_kink >= from_end:
        low, high, lo, hi = from_end, from_start, to_end, to_start
    else:
        return 0.0
    if x < low:
        return lo
    if x < from_kink:
        return (to_kink - lo) * _ease(interp, (x - low) / (from_kink - low)) + lo
    if x < high:
        return (hi - to_kink) * _ease(interp, (x - from_kink) / (high - from_kink)) + to_kink
    return hi


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
    sm = source_interpolation(source)
    r = source_rest_input(source)
    at_rest = eval_piecewise(fs, fk, fe, ts, tk, te, r, two_point=tp, interp=sm)
    return {
        'at_rest':    at_rest,
        'rest_input': r,
        'at_start':   eval_piecewise(fs, fk, fe, ts, tk, te, fs, two_point=tp, interp=sm),
        'at_kink':    eval_piecewise(fs, fk, fe, ts, tk, te, fk, two_point=tp, interp=sm),
        'at_end':     eval_piecewise(fs, fk, fe, ts, tk, te, fe, two_point=tp, interp=sm),
        'rest_pos':   rest_position(fs - r, fk - r, fe - r),
        'two_point':  tp,
        'interpolation': sm,
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
    sm = source_interpolation(source)
    r = source_rest_input(source)

    at_rest = eval_piecewise(fs, fk, fe, ts, tk, te, r, two_point=tp, interp=sm)
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
    pts = [(lo + i * step, eval_piecewise(fs, fk, fe, ts, tk, te, lo + i * step, two_point=tp, interp=sm))
           for i in range(n)]

    # Merge samples into straight runs; a slope change starts a new run.  An eased curve has
    # a new slope everywhere, so it is described per anchor-to-anchor stretch instead.
    runs = []
    if sm in EASING:
        marks = {lo, hi, r, fs, fe}
        if not tp and not is_folded(fs, fk, fe):
            marks.add(fk)
        marks = sorted(m for m in marks if lo - 1e-9 <= m <= hi + 1e-9)
        for x0, x1 in zip(marks, marks[1:]):
            if x1 - x0 > 1e-9:
                runs.append((x0, x1, 0.0, 0.0))
    i = 0 if sm not in EASING else len(pts)
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
             eval_piecewise(fs, fk, fe, ts, tk, te, snap(x0), two_point=tp, interp=sm),
             eval_piecewise(fs, fk, fe, ts, tk, te, snap(x1), two_point=tp, interp=sm))
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
            u = eval_piecewise(fs, fk, fe, ts, tk, te, a, two_point=tp, interp=sm)
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
            if abs(eval_piecewise(fs, fk, fe, ts, tk, te, ax, two_point=tp, interp=sm) - ay) > 1e-4:
                unreachable = name
                break

    return {'rest_output': at_rest, 'legs': legs, 'inert': inert,
            'offset_at_rest': abs(at_rest) > 1e-4,
            'anchors_ordered': ordered_anchors,
            'two_point': tp,
            'interpolation': sm,
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
    sm = source_interpolation(source)

    lo, hi = min(fs, fe, 0.0), max(fs, fe, 0.0)
    if hi - lo < 1e-9:
        hi = lo + 1.0
    pad = (hi - lo) * 0.08
    lo, hi = lo - pad, hi + pad
    step = (hi - lo) / float(n - 1)
    return [(lo + i * step,
             eval_piecewise(fs, fk, fe, ts, tk, te, lo + i * step, two_point=tp, interp=sm))
            for i in range(n)]
