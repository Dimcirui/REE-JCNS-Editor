"""
jcns_mapping.py
---------------
The three-point piecewise transfer function, evaluated numerically.

This is the only implementation of the curve.  The Blender drivers call it
directly: the driver-namespace function jcns_drivers.jcns_ch evaluates each
source with eval_piecewise, and the UI read-outs and curve preview use the same
function, so a panel can never report a different number from what the driver
produces.

Kept free of `bpy` so it can be tested standalone.

Anchors, all in the file's own units — degrees for rotation, centimetres for
translation (see driver_anchors):

    A = (from_start, to_start)   first endpoint
    B = (from_kink,  to_kink)    slope change
    C = (from_end,   to_end)     second endpoint

Segment 1 maps [A.x -> B.x] onto [A.y -> B.y]; segment 2 maps [B.x -> C.x] onto
[B.y -> C.y].  Outside the covered range the output is clamped to the nearer
segment's bound.

TWO CURVE MODES (measured in-game 2026-08-21 against a purpose-built rig).  The
per-source byte at +24 — `CurveMode` in jcns_parser; RE_Engine_JCNS.bt calls it
UpdateTiming, a misnomer — selects the curve shape:

    +24 == 0, 1  ->  TWO-POINT: the kink is ignored entirely; the output is the
                     straight line A -> C.
    +24 == 2, 3  ->  THREE-POINT: the piecewise curve described above.

Within each pair the members were bit-identical across every geometry tested, so
the split is exactly bit 1 (0x02).

Proof: two sources with identical geometry and identical +25, differing only in
+24, produced respectively an exact straight line and an exact piecewise curve
(every binned sample matched its model to 0.01 deg, and local slopes were
constant to four decimals within each segment — so the segments are strictly
linear, not eased).  The constraint-level `Flags` bit 0 was independently shown
to have no effect.  The byte at +25 shifts the sampled input quantity slightly
but does NOT change the curve shape.

Degenerate anchors, measured separately in each mode:

    two-point    collapsing either segment changes nothing (it is a straight
                 line regardless); all three `from` equal -> flat 0.
    three-point  start == kink -> segment 2 governs, `to_start` ignored;
                 kink == end   -> segment 1 governs, `to_end` ignored;
                 all three equal -> steps at the kink between `to_start` and
                 `to_end`, and `to_kink` never appears.
                 A descending `from` range behaves exactly like the equivalent
                 ascending one.
                 A kink lying strictly OUTSIDE [start, end] kills the source:
                 the output is a flat 0, not a clamped constant.  Measured over
                 three such geometries, including a pair differing only in
                 `to_start` by 90 deg that produced identical flat zeros.

UNTESTED: +24 == 4 / 5 (9 sources in the whole corpus).
"""

from jcns_source_read import read_quantity, read_mode_value, euler_order_value  # noqa: F401


# +25 (ReadMode): how the engine reads the source bone -- measured in game
# 2026-09-30 for every value, see jcns_source_read.READ_MODES.  0 reads position,
# 2 scale, the rest are four decompositions of the rotation.


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
    offset included (measured 2026-09-30, see jcns_source_read), so a bone with a
    rest rotation or offset does not read 0 at rest.  This module has no skeleton:
    a dict may carry the value as 'rest_input', otherwise the resolver the Blender
    side installed is asked, and failing both an identity rest is assumed -- 1 for
    a scale, 0 otherwise.
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


# A jcns stores lengths in centimetres, as the earlier RE Engine titles did,
# while mot/mesh data — and so a RE Mesh Editor armature, imported 1:1 — is in
# metres.  Not measured in-game; inferred from the shipped MH Wilds files:
#   * sources: a +25=0 range over the animated amplitude of the bone it reads is
#     100 more often than anything else, and exactly 100 for pure control bones
#     (Spear 1 m -> 100, Shot 0.5 -> 50, MOT_Fat 0.1 -> 10, MOT_Wing_PT 0.01 -> 1);
#   * targets: 7148 of 8096 translation outputs peak between 1 and 100, which
#     is a helper bone's travel in centimetres and absurd in metres;
#   * the wing switches (MOT_Wing_PT keyed 0 / 0.01 m, output compared against a
#     display threshold of 1.0) only work when read in centimetres.
CM_PER_UNIT = 100.0

# Driver targets by transform type: which quantity the output is.
_TARGET_QUANTITY = {
    'Translation': 'Translation', 'Scale': 'Scale',
    'Rotation': 'Rotation', 'UnkRotation_13': 'Rotation',
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

    The input side follows what the SOURCE is, the output side what the TARGET
    is — they are independent: a thigh rotation driving a helper bone's position
    has degrees on one side and centimetres on the other.  Rotations go to
    radians, translations to Blender units (metres), scales stay as they are.
    """
    fs, fk, fe, ts, tk, te = values
    return (_to_driver_units((fs, fk, fe), source_quantity)
            + _to_driver_units((ts, tk, te), target_quantity))


def is_two_point(update_timing):
    """Does this source use the two-point (straight line A -> C) curve mode?

    The per-source byte at +24 (`CurveMode`; RE_Engine_JCNS.bt names it
    UpdateTiming) is the curve-mode selector.

    Measured: 0 and 1 are two-point, 2 and 3 are three-point.  That split is
    exactly bit 1 (0x02), which is probably the real encoding, but 4 and 5 (9
    sources in the whole corpus) were never measured, so this sticks to the
    values actually observed rather than extrapolating the bit reading.
    """
    return update_timing in (0, 1)


def source_two_point(source):
    """Curve mode of a source, read from whichever field name it exposes.

    Parser dicts carry it as `CurveMode`; the Blender PropertyGroup keeps the
    older name `update_timing` so existing .blend files still load.
    """
    if isinstance(source, dict):
        v = source.get('CurveMode', source.get('update_timing'))
    else:
        v = getattr(source, 'update_timing', None)
    return is_two_point(v)


def is_folded(from_start, from_kink, from_end):
    """Does the polyline double back on itself along x?

    True when the kink lies strictly outside the [start, end] span, so the two
    segments overlap in x and the same input maps to two different outputs —
    a '<' or '>' shape rather than a '^' or 'v'.  In three-point mode the engine
    refuses such a source outright and its output is a flat 0; in two-point mode
    the kink is ignored, so the shape is harmless.
    """
    lo, hi = (from_start, from_end) if from_start <= from_end else (from_end, from_start)
    return from_kink < lo - 1e-9 or from_kink > hi + 1e-9


def eval_piecewise(from_start, from_kink, from_end,
                   to_start, to_kink, to_end, x, two_point=False):
    """Output of the transfer function for a source value of `x`.

    `two_point=True` selects the +24 in (0, 1) curve mode (straight line A -> C).
    """
    span1 = from_kink - from_start
    span2 = from_end - from_kink
    total = from_end - from_start

    def seg(x0, y0, x1, y1, span):
        k = (y1 - y0) / span
        lo, hi = min(y0, y1), max(y0, y1)
        return max(lo, min(hi, y0 + (x - x0) * k))

    if two_point:
        if abs(total) < 1e-9:
            return 0.0
        return seg(from_start, to_start, from_end, to_end, total)

    # Three-point mode.  A kink strictly outside the [start, end] span kills the
    # whole source — measured over three such geometries (kink past the end, kink
    # before the start, and the same with a wildly different to_start), all of
    # which produced a flat 0 while neighbouring slots evaluated normally.
    if is_folded(from_start, from_kink, from_end):
        return 0.0

    # Degenerate handling below was measured in-game (Round 12) and matches the
    # original heuristics, except for the fully-collapsed case which steps
    # between to_start and to_end.
    if abs(span1) < 1e-9 and abs(span2) < 1e-9:
        # Measured: x <= kink -> to_start, x > kink -> to_end.  to_kink never
        # appears (a probe with to=(5, 33, 7) only ever produced 5 and 7).
        return to_start if x <= from_kink else to_end
    if abs(span2) < 1e-9:                      # only segment 1 is live
        return seg(from_start, to_start, from_kink, to_kink, span1)
    if abs(span1) < 1e-9:                      # only segment 2 is live
        return seg(from_kink, to_kink, from_end, to_end, span2)

    # Pick the segment by which side of the kink `x` falls on, honouring a
    # descending MapFrom range (from_start > from_end) just like the driver does.
    on_first = (x <= from_kink) if from_start <= from_end else (x >= from_kink)
    if on_first:
        return seg(from_start, to_start, from_kink, to_kink, span1)
    return seg(from_kink, to_kink, from_end, to_end, span2)


def rest_position(from_start, from_kink, from_end):
    """Where the rest pose (source == 0) sits relative to the MapFrom anchors.

    Returned as one of 'A', 'B', 'C', 'inside', 'outside'.  This matters because
    whichever anchor the rest pose coincides with is the one whose MapTo value
    the bone will be holding when nothing is moving.
    """
    if abs(from_start) < 1e-6:
        return 'A'
    if abs(from_end) < 1e-6:
        return 'C'
    if abs(from_kink) < 1e-6:
        return 'B'
    lo, hi = min(from_start, from_end), max(from_start, from_end)
    return 'inside' if lo < 0.0 < hi else 'outside'


def describe(source):
    """
    Diagnose one source mapping.

    `source` is anything exposing from_start/from_kink/from_end/to_start/
    to_kink/to_end — a parser dict or a JCNSSourceProperties instance.

    Returns a dict with the output at the three anchors plus at rest, where the
    rest pose sits, and whether the constraint does anything at all.
    """
    def g(name):
        if isinstance(source, dict):
            return float(source.get(name, 0.0) or 0.0)
        return float(getattr(source, name, 0.0))

    fs, fk, fe = g('from_start'), g('from_kink'), g('from_end')
    ts, tk, te = g('to_start'), g('to_kink'), g('to_end')

    tp = source_two_point(source)
    r = source_rest_input(source)
    at_rest = eval_piecewise(fs, fk, fe, ts, tk, te, r, two_point=tp)
    return {
        'at_rest':    at_rest,
        'rest_input': r,
        'at_start':   eval_piecewise(fs, fk, fe, ts, tk, te, fs, two_point=tp),
        'at_kink':    eval_piecewise(fs, fk, fe, ts, tk, te, fk, two_point=tp),
        'at_end':     eval_piecewise(fs, fk, fe, ts, tk, te, fe, two_point=tp),
        'rest_pos':   rest_position(fs - r, fk - r, fe - r),
        'two_point':  tp,
        # '<' / '>' shape in three-point mode: the engine discards the whole
        # source and its output is a flat 0.  Harmless in two-point mode.
        'folded_dead': (not tp) and is_folded(fs, fk, fe),
        # A non-zero output at rest means the bone is deflected before anything
        # has moved.  Legitimate for some setups, but almost always a mistake
        # when editing by hand, so the UI flags it.
        'offset_at_rest': abs(at_rest) > 1e-4,
        # All three MapTo anchors zero: the constraint can never produce output.
        'inert': abs(ts) < 1e-9 and abs(tk) < 1e-9 and abs(te) < 1e-9,
        'from': (fs, fk, fe),
        'to':   (ts, tk, te),
    }


def describe_channel(sources):
    """Diagnose a driven channel from the sources of the constraint that owns it.

    A single source can look harmless while the total is still deflected at rest,
    so the per-source read-out is not sufficient on its own.

    Pass only the live constraint's sources: where several constraints target one
    channel the engine keeps the last and drops the rest, so folding all of them
    in here would report a rest deflection that never actually happens.
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

    The common authoring slip: MapFrom runs downwards (e.g. [-60, -15, 0]) so the
    rest pose coincides with anchor C, but the intended deflection was written
    into to_end — the anchor that applies while the rig is idle — instead of
    to_start.  Swapping the two puts it back on the moving end.
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
    """Describe the mapping the way it is actually reasoned about.

    The file stores three anchors in its own order (A -> B -> C), but the rest
    pose does not have to be anchor A — for a descending range like
    [-60, -15, 0] it sits on anchor C, so reading the numbers left to right
    describes the motion backwards.

    This walks outward from the rest pose instead, in each direction the source
    bone can actually travel, and reports what the target does over each leg.

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
    # The source's value at rest; see source_rest_input.
    r = source_rest_input(source)

    at_rest = eval_piecewise(fs, fk, fe, ts, tk, te, r, two_point=tp)
    inert = abs(ts) < 1e-9 and abs(tk) < 1e-9 and abs(te) < 1e-9

    # The three anchors do not have to be ordered, and when they double back
    # (say [-120, 0, -30]) one of them becomes unreachable: the transfer
    # function picks a segment by which side of the kink the input is on, so a
    # segment lying on the same side as its neighbour is never evaluated.
    #
    # Describing the curve by sorting the anchors and joining the dots would
    # therefore report behaviour the rig does not have.  Sample the real
    # function instead and read the shape back off it, so this can only ever
    # describe what eval_piecewise — and hence the driver — actually does.
    lo, hi = min(r, fs, fk, fe), max(r, fs, fk, fe)
    if hi - lo < 1e-9:
        return {'rest_output': at_rest, 'legs': [], 'inert': inert,
                'offset_at_rest': abs(at_rest) > 1e-4,
                'anchors_ordered': True, 'unreachable_anchor': None}

    n = 401
    step = (hi - lo) / (n - 1)
    pts = [(lo + i * step, eval_piecewise(fs, fk, fe, ts, tk, te, lo + i * step, two_point=tp))
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

    # Sampling puts a breakpoint on the nearest sample rather than exactly on
    # the anchor, so 25 would be reported as 24.9.  Snap back to the real value.
    def snap(x):
        for a in (r, fs, fk, fe):
            if abs(x - a) <= step * 1.5:
                return a
        return x

    runs = [(snap(x0), snap(x1),
             eval_piecewise(fs, fk, fe, ts, tk, te, snap(x0), two_point=tp),
             eval_piecewise(fs, fk, fe, ts, tk, te, snap(x1), two_point=tp))
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
            u = eval_piecewise(fs, fk, fe, ts, tk, te, a, two_point=tp)
            kind = 'dead' if abs(v - u) < 1e-4 else 'move'
            if steps and steps[-1][4] == kind == 'dead':
                steps[-1] = (steps[-1][0], b, steps[-1][2], v, 'dead')
            else:
                steps.append((a, b, u, v, kind))
        if steps:
            legs.append({'direction': direction, 'steps': steps})

    # A '<' / '>' shape — the kink outside the [start, end] span — makes the two
    # segments overlap in x, so the same input would map to two outputs.  In
    # three-point mode the engine throws the whole source away and outputs a flat
    # 0; in two-point mode the kink is ignored, so the shape is harmless.
    ordered_anchors = not is_folded(fs, fk, fe)
    folded_dead = (not tp) and not ordered_anchors

    # Which anchor, if any, the function never reaches.  Pointless to report when
    # the source is dead outright — "anchor A unreachable" would bury the lede.
    unreachable = None
    if not ordered_anchors and not folded_dead:
        for name, ax, ay in (('A', fs, ts), ('B', fk, tk), ('C', fe, te)):
            if abs(eval_piecewise(fs, fk, fe, ts, tk, te, ax, two_point=tp) - ay) > 1e-4:
                unreachable = name
                break

    return {'rest_output': at_rest, 'legs': legs, 'inert': inert,
            'offset_at_rest': abs(at_rest) > 1e-4,
            'anchors_ordered': ordered_anchors,
            'two_point': tp,
            'folded_dead': folded_dead,
            'unreachable_anchor': unreachable}


def sample(source, n=48):
    """Sample the curve across its MapFrom span; returns [(x, y), …] for plotting."""
    def g(name):
        if isinstance(source, dict):
            return float(source.get(name, 0.0) or 0.0)
        return float(getattr(source, name, 0.0))

    fs, fk, fe = g('from_start'), g('from_kink'), g('from_end')
    ts, tk, te = g('to_start'), g('to_kink'), g('to_end')
    tp = source_two_point(source)

    lo, hi = min(fs, fe, 0.0), max(fs, fe, 0.0)
    if hi - lo < 1e-9:
        hi = lo + 1.0
    pad = (hi - lo) * 0.08
    lo, hi = lo - pad, hi + pad
    step = (hi - lo) / float(n - 1)
    return [(lo + i * step,
             eval_piecewise(fs, fk, fe, ts, tk, te, lo + i * step, two_point=tp))
            for i in range(n)]
