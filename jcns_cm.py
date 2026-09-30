"""
jcns_cm.py
----------
A source's ComplexMapping as a native Blender F-Curve.

The F-Curve is the data: it lives in the constraint Empty's own Action, on a
custom property of that Empty (`obj["jcns_cm_<n>"]`), so it can be edited in the
Graph Editor.  The horizontal axis is the source value, the vertical one the
output, both in the file's own units (degrees / centimetres).  Each source
remembers its property name in `cm_channel`; the number comes from a counter that
never goes back, so removing a source never re-points another one's curve.

Equal x on neighbouring keys (a step) cannot live in an F-Curve: FCurve.update() and Graph Editor transforms merge keys less than 0.01
frame apart.  So the later key goes in step_gap() further right and comes back
onto the same x when read, and an edited step exports as a ramp 0.02 of a degree
(or centimetre) wide.  The flip side: two keys a user places closer than 0.03
read back as a step.

Keys are Bezier with FREE handles at key +- (segment dx, rise) / 3, which draws
exactly the cubic the engine evaluates (modules/jcns_complex.py).  Only a handle's
slope reaches the file, so a handle dragged to another length changes the
Graph Editor's picture but not the game; `normalize_handles` puts them back.

The records read from the file stay in `cm_cache`, and are written back verbatim
while the curve still matches them, so an untouched file exports byte for byte.

Nothing here writes ID data from draw() or poll(): read paths never create the
Action, slot, layer or channelbag.
"""

import bpy

from .modules_shim import ensure_path

ensure_path()
import jcns_complex  # noqa: E402

_LEGACY_ACTION_FCURVES = bpy.app.version < (4, 4, 0)
PREFIX = "jcns_cm_"
ACTION_MARKER = "~JCNS_CM"


# ---------------------------------------------------------------------------
# Action plumbing (4.4+ moved F-Curves into layers / strips / slots)
# ---------------------------------------------------------------------------

def _action(obj, create):
    ad = obj.animation_data
    if ad is None:
        if not create:
            return None
        ad = obj.animation_data_create()
    act = ad.action
    if act is None and create:
        act = bpy.data.actions.new("JCNS_CM::%s" % obj.name)
        act[ACTION_MARKER] = 1
        ad.action = act
    return act


def _fcurves(obj, create):
    """The collection holding obj's own F-Curves, or None when absent (read path)."""
    act = _action(obj, create)
    if act is None:
        return None
    if _LEGACY_ACTION_FCURVES:
        return act.fcurves
    ad = obj.animation_data
    slot = ad.action_slot
    if slot is None:
        slot = next((s for s in act.slots if s.target_id_type in ('OBJECT', 'UNSPECIFIED')), None)
        if slot is None:
            if not create:
                return None
            slot = act.slots.new(id_type='OBJECT', name=obj.name)
        if create:
            ad.action_slot = slot
    if act.layers:
        layer = act.layers[0]
    elif create:
        layer = act.layers.new(name="Layer")
    else:
        return None
    if layer.strips:
        strip = layer.strips[0]
    elif create:
        strip = layer.strips.new(type='KEYFRAME')
    else:
        return None
    bag = strip.channelbag(slot, ensure=create)
    return bag.fcurves if bag is not None else None


def _new_fcurve(fcs, data_path):
    if _LEGACY_ACTION_FCURVES:
        return fcs.new(data_path, index=0, action_group="ComplexMapping")
    return fcs.new(data_path, index=0, group_name="ComplexMapping")


def _data_path(sp):
    return '["%s"]' % sp.cm_channel


def fcurve(sp, create=False):
    """The source's F-Curve.  create=True allocates its channel when needed."""
    obj = sp.id_data
    if not sp.cm_channel:
        if not create:
            return None
        cp = obj.jcns_cns_props
        sp.cm_channel = "%s%d" % (PREFIX, cp.cm_next_id)
        cp.cm_next_id += 1
    if create and sp.cm_channel not in obj.keys():
        obj[sp.cm_channel] = 0.0
    fcs = _fcurves(obj, create)
    if fcs is None:
        return None
    fc = fcs.find(_data_path(sp), index=0)
    if fc is None and create:
        fc = _new_fcurve(fcs, _data_path(sp))
    return fc


def has_curve(sp):
    fc = fcurve(sp)
    return fc is not None and len(fc.keyframe_points) > 0


# ---------------------------------------------------------------------------
# Keys <-> F-Curve
# ---------------------------------------------------------------------------

def step_gap(x):
    """How far a step's second key sits from the first: past Blender's 0.01-frame
    merge distance, and well above float32 noise at x (2**-18 relative)."""
    return max(0.02, abs(x) * 2.0 ** -18)


def _split_steps(keys):
    out = []
    for k in keys:
        if out and k[0] < out[-1][0] + step_gap(out[-1][0]):
            k = (out[-1][0] + step_gap(out[-1][0]),) + tuple(k[1:])
        out.append(tuple(k))
    return out


def _join_steps(keys):
    out = []
    for k in keys:
        if out and k[0] - out[-1][0] < 1.5 * step_gap(out[-1][0]):
            k = (out[-1][0],) + tuple(k[1:])
        out.append(k)
    return out


def _handle_lengths(keys, i):
    """Horizontal handle reach on each side of key i: a third of the segment, or of
    the other one where this side has none (end key, or a step)."""
    x = keys[i][0]
    seg_in = x - keys[i - 1][0] if i > 0 else 0.0
    seg_out = keys[i + 1][0] - x if i + 1 < len(keys) else 0.0
    # A step's gap is too short to carry a slope through float handles, so it
    # counts as no segment; Blender clamps the longer handle when it draws.
    if seg_in < 1.5 * step_gap(x):
        seg_in = 0.0
    if seg_out < 1.5 * step_gap(x):
        seg_out = 0.0
    dx_in = seg_in if seg_in > 0 else (seg_out if seg_out > 0 else 1.0)
    dx_out = seg_out if seg_out > 0 else (seg_in if seg_in > 0 else 1.0)
    return dx_in / 3.0, dx_out / 3.0


def set_keys(sp, keys):
    """Replace the source's curve with `keys` [(x, y, slope_in, slope_out)]."""
    keys = _split_steps(sorted(keys, key=lambda k: k[0]))
    fc = fcurve(sp, create=True)
    kps = fc.keyframe_points
    while len(kps):
        kps.remove(kps[-1], fast=True)
    kps.add(len(keys))
    for i, (kp, (x, y, s_in, s_out)) in enumerate(zip(kps, keys)):
        hl, hr = _handle_lengths(keys, i)
        kp.co = (x, y)
        kp.interpolation = 'BEZIER'
        kp.handle_left_type = kp.handle_right_type = 'FREE'
        kp.handle_left = (x - hl, y - s_in * hl)
        kp.handle_right = (x + hr, y + s_out * hr)
    fc.extrapolation = 'CONSTANT'
    fc.update()


def keys(sp):
    """[(x, y, slope_in, slope_out)] read off the F-Curve, or None without one."""
    fc = fcurve(sp)
    if fc is None or not len(fc.keyframe_points):
        return None
    return keys_of(fc)


def keys_of(fc):
    out = []
    for kp in sorted(fc.keyframe_points, key=lambda k: k.co[0]):
        x, y = kp.co
        lx, ly = kp.handle_left
        rx, ry = kp.handle_right
        s_in = (y - ly) / (x - lx) if x - lx > 1e-9 else 0.0
        s_out = (ry - y) / (rx - x) if rx - x > 1e-9 else 0.0
        out.append((x, y, s_in, s_out))
    return _join_steps(out)


def normalize_handles(sp):
    """Put every handle back at a third of its segment, keeping its slope."""
    k = keys(sp)
    if k:
        set_keys(sp, k)


# ---------------------------------------------------------------------------
# File records
# ---------------------------------------------------------------------------

_REC_FIELDS = (('FromX', 'from_x'), ('ToX', 'to_x'), ('FromY', 'from_y'),
               ('ToY', 'to_y'), ('FromZ', 'from_z'), ('ToZ', 'to_z'),
               ('UnknownUInt32', 'flag'))


def _cache_records(sp):
    return [{f: getattr(c, a) for f, a in _REC_FIELDS} for c in sp.cm_cache]


def load(sp, records):
    """Import: keep the file's records and build the curve from them."""
    sp.cm_cache.clear()
    for r in records:
        c = sp.cm_cache.add()
        for f, a in _REC_FIELDS:
            setattr(c, a, r[f])
    if records:
        set_keys(sp, jcns_complex.keys_from_records(records))
    else:
        remove(sp, keep_cache=True)


def records(sp):
    """Export: the ComplexMappingInfo records the curve stands for."""
    k = keys(sp)
    if not k:
        return []
    cached = _cache_records(sp)
    # Loose tolerance: slopes come back through float handles.
    if cached and jcns_complex.same_keys(k, jcns_complex.keys_from_records(cached), tol=1e-3):
        return cached
    # Edited: re-derive, keeping the flag of a cached key on the same x.  The flag
    # does not change the result in game, so a new key gets 0.
    pool = list(cached)
    flags = []
    for x, *_ in k:
        hit = next((r for r in pool if abs(r['FromX'] - x) < 1e-6), None)
        if hit is not None:
            pool.remove(hit)
        flags.append(hit['UnknownUInt32'] if hit else 0)
    return jcns_complex.records_from_keys(k, flags)


def remove(sp, keep_cache=False):
    """Drop the source's curve (it goes back to its three-point mapping)."""
    obj = sp.id_data
    fcs = _fcurves(obj, False)
    if fcs is not None and sp.cm_channel:
        fc = fcs.find(_data_path(sp), index=0)
        if fc is not None:
            fcs.remove(fc)
    if sp.cm_channel and sp.cm_channel in obj.keys():
        del obj[sp.cm_channel]
    if not keep_cache:
        sp.cm_cache.clear()


def copy_keys(src_sp, dst_sp, transform=None):
    """Give dst_sp src_sp's curve, optionally through `transform(keys) -> keys`."""
    k = keys(src_sp)
    if not k:
        remove(dst_sp)
        return
    set_keys(dst_sp, transform(k) if transform else k)


# ---------------------------------------------------------------------------
# Keeping applied previews in step with Graph Editor edits
# ---------------------------------------------------------------------------

def _owners(act):
    return [o for o in bpy.data.objects
            if o.animation_data is not None and o.animation_data.action == act
            and getattr(o, 'jcns_cns_props', None) is not None
            and o.jcns_cns_props.is_jcns_constraint]


@bpy.app.handlers.persistent
def _on_depsgraph_update(scene, depsgraph):
    try:
        acts = [u.id.original for u in depsgraph.updates
                if isinstance(u.id, bpy.types.Action) and ACTION_MARKER in u.id.original.keys()]
        if not acts:
            return
        from .jcns_operators import refresh_channel_values
        for act in acts:
            for obj in _owners(act):
                if obj.jcns_cns_props.preview_on:
                    refresh_channel_values(obj)
    except Exception as exc:                                  # never break editing
        print("[JCNS] ComplexMapping refresh failed: %r" % exc)


def register():
    if _on_depsgraph_update not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_on_depsgraph_update)


def unregister():
    if _on_depsgraph_update in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_on_depsgraph_update)
