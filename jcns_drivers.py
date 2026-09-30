"""
Driver-namespace function backing the generated drivers.

Blender truncates `Driver.expression` at 255 characters, so the expression is
only a call, `jcns_ch("<channel key>", var, var_001, ...)`; the mapping lives in
_CHANNELS, and the real driver variables still declare the dependency on the
source bones for the depsgraph.  Values in _CHANNELS are already in driver
units (radians for rotation), so jcns_ch does no unit conversion.

Engine rules the reads follow:
  * a rotation source is read off the bone's whole parent-relative rotation, rest
    included, and a translation source off its whole position, rest offset
    included; +25 picks the decomposition (modules/jcns_source_read.py).
  * entries run in file order within one frame, so a source channel written by
    this entry or a later one reads its rest value and gets no variable.

A bone's three rotation_euler drivers are built as one group, each evaluating the
whole bone (jcns_source_read.target_basis), when its rotation TransformType is not
1 (4 / 5 / 6 compose by swing-twist, twist-swing and rotation vector; 13 / 14 hold
one rotation about the last written axis), or when a target entry with Flags
bit0 = 0 lands on a bone with a rest rotation (it replaces the rest pose).
"""

import bpy

from .modules_shim import get_mapping, ensure_path

ensure_path()
import jcns_complex  # noqa: E402
import jcns_source_read  # noqa: E402


# key -> {'maps': [map, …], 'reads': [read, …]}, one of each per source of the
# single constraint that owns the channel; their outputs are summed.  A map is
# either the three-point (fs, fk, fe, ts, tk, te, two_point, smooth) or ('CM', keys) for a
# ComplexMapping, both already in the driver's units.  A read says which driver
# variables feed the source:
#   ('v',)                        one variable, used as is
#   ('c', value)                  none; the source is not live yet, use value
#   ('sc', rest_scale)            one variable (pose scale), times the bone's rest scale
#   ('rot', mode, axis, rest, order, frame, live)
#                                 one variable per axis in `live` (XYZ Euler, radians,
#                                 the others read 0); rest and frame are (w, x, y, z);
#                                 mode is a jcns_source_read.ROTATION_MODES value and
#                                 order the source's +27 EulerOrder
#   ('loc', axis, rest, offset, live)
#                                 one variable per axis in `live` (location, metres);
#                                 offset is the rest offset from the parent, metres
_CHANNELS = {}

READ_VALUE = ('v',)


def _unit_scale(quantity):
    """File units -> driver units for one quantity (degrees -> radians, cm -> m)."""
    return get_mapping()._to_driver_units((1.0,), quantity)[0]


def source_read(s):
    """How the driver feeds one source dict; see _CHANNELS."""
    return s.get('read') or READ_VALUE


def read_width(read):
    """How many driver variables a read consumes."""
    if read[0] == 'c':
        return 0
    if read[0] in ('rot', 'loc'):
        return len(read[-1])
    return 1


def _read(read, vals):
    """The source value for one 'rot' / 'loc' read from its live channels."""
    chans = [0.0, 0.0, 0.0]
    for a, val in zip(read[-1], vals):
        chans[a] = val
    if read[0] == 'rot':
        _, mode, axis, rest, order, frame, _live = read
        return jcns_source_read.rotation(
            mode, jcns_source_read.pose_rotation(rest, chans), axis, order, frame)
    _, axis, rest, offset, _live = read
    return jcns_source_read.position(rest, offset, chans, axis)


def source_map(s, target_q):
    """The channel-table entry for one source dict (jcns_operators._sources_for_driver).

    Input side in the source's units (its +25), output side in the target's.
    """
    m = get_mapping()
    src_q = m.source_quantity(s.get('read_mode'))
    if s.get('cm'):
        return ('CM', tuple(jcns_complex.scaled(s['cm'], _unit_scale(src_q),
                                                _unit_scale(target_q))))
    vals = (s['from_start'], s['from_kink'], s['from_end'],
            s['to_start'],   s['to_kink'],   s['to_end'])
    return tuple(m.driver_anchors(vals, src_q, target_q)) + (m.is_two_point(s.get('curve_mode')),
                                                              bool(s.get('smooth')))


def channel_id(armature_name, bone, transform, axis):
    """Stable, human-readable key. Quotes are stripped so it is safe to embed."""
    parts = [str(p).replace('"', '').replace('\\', '') for p in
             (armature_name, bone, transform, axis)]
    return "|".join(parts)


def register_channel(key, maps, reads=None, post=1.0):
    """`post` converts the summed engine value into the Blender channel's space
    (1 / rest scale for a scale target; see jcns_operators.target_post_factor)."""
    maps = list(maps)
    _CHANNELS[key] = {'maps': maps, 'reads': list(reads or [READ_VALUE] * len(maps)),
                      'post': float(post)}


def channel_reads(key):
    ch = _CHANNELS.get(key)
    return ch['reads'] if ch else None


def clear_channels():
    _CHANNELS.clear()
    _GROUPS.clear()


# gid -> {'rest': (w, x, y, z), 'parts': [(axis, mode, replaces, maps, reads), ...]}
# for a bone whose rotation or location drivers are built together; parts are in
# file order of their live entries.  Location groups also carry 'offset', the
# parent-relative rest offset in metres.  The bone's channels are in _CHANNELS as
# {'group': gid, 'axis': a}.
_GROUPS = {}


def register_group(gid, rest, parts, keys, offset=None):
    """One bone's group; optional offset selects parent-axis translation.

    `keys` are the three driver channel keys; parts carry winning entries.
    """
    _GROUPS[gid] = {'rest': tuple(rest), 'parts': list(parts)}
    if offset is not None:
        _GROUPS[gid]['offset'] = tuple(offset)
    for a, key in enumerate(keys):
        _CHANNELS[key] = {'group': gid, 'axis': a}


def group_parts(gid):
    g = _GROUPS.get(gid)
    return g['parts'] if g else None


def _total(maps, reads, values):
    """Sum of one channel's sources -> (total, number of values consumed)."""
    ev = get_mapping().eval_piecewise
    total = 0.0
    at = 0
    for m, read in zip(maps, reads):
        width = read_width(read)
        if at + width > len(values):
            break                  # driver built for another layout; Apply rebuilds it
        if read[0] == 'c':
            v = read[1]
        elif read[0] in ('rot', 'loc'):
            v = _read(read, values[at:at + width])
        elif read[0] == 'sc':
            v = values[at] * read[1]       # Blender pose scale -> engine scale
        else:
            v = values[at]
        at += width
        if m[0] == 'CM':
            total += jcns_complex.evaluate(m[1], v)
        else:
            total += ev(*m[:6], v, two_point=(len(m) > 6 and m[6]), smooth=(len(m) > 7 and m[7]))
    return total, at


def _group_value(ch, values):
    g = _GROUPS.get(ch['group'])
    if g is None:
        return 0.0
    parts = []
    at = 0
    for axis, mode, replaces, maps, reads in g['parts']:
        total, used = _total(maps, reads, values[at:])
        at += used
        parts.append((axis, mode, replaces, total))
    if 'offset' in g:
        return jcns_source_read.translation_basis(
            g['rest'], g['offset'], [(a, rep, val) for a, mode, rep, val in parts])[ch['axis']]
    return jcns_source_read.target_basis(g['rest'], parts)[ch['axis']]


def jcns_ch(key, *values):
    """Evaluate one driven channel. Called from every generated driver."""
    ch = _CHANNELS.get(key)
    if ch is None:
        # Channels not rebuilt yet.  This runs during depsgraph evaluation, so it
        # must not touch bpy.data; rebuild_all() runs from load_post instead.
        return 0.0
    if 'group' in ch:
        return _group_value(ch, values)
    # Each source maps independently and the outputs are summed.  A 6-long map
    # entry (no two_point flag) is three-point.
    return _total(ch['maps'], ch['reads'], values)[0] * ch.get('post', 1.0)


def rebuild_all():
    """Recreate the channel table from the scene, without touching the drivers.

    Runs after a .blend load so drivers saved in the file work without Apply.
    """
    from . import group_constraints_by_channel
    from .jcns_operators import (channel_sources, replacing_bones, register_bone_group,
                                 translation_channels, register_translation_group)

    clear_channels()
    rebuilt = 0
    for obj in bpy.data.objects:
        rp = getattr(obj, 'jcns_root_props', None)
        if not rp or not rp.source_filepath or rp.target_armature is None:
            continue
        arm = rp.target_armature
        grouped = replacing_bones(arm, obj)
        for bone, chans in grouped.items():
            if register_bone_group(arm, obj, bone, chans):
                rebuilt += 1
        translations = {b for b, transform, axis in group_constraints_by_channel(obj)
                        if transform == 'Translation' and axis != 'W'}
        for bone in translations:
            if register_translation_group(arm, obj, bone, translation_channels(obj, bone)):
                rebuilt += 1
        for (bone, transform, axis), members in group_constraints_by_channel(obj).items():
            if bone in grouped and transform_path(transform) == 'rotation_euler':
                continue
            if bone in translations and transform == 'Translation':
                continue
            m = get_mapping()
            target_q = m.target_quantity(transform)
            # Only the last constraint on a channel is live; see _apply_channel.
            sources = channel_sources(arm, obj, members[-1])
            if sources:
                from .jcns_operators import target_post_factor
                register_channel(channel_id(arm.name, bone, transform, axis),
                                 [source_map(s, target_q) for s in sources],
                                 [source_read(s) for s in sources],
                                 post=target_post_factor(arm, bone, transform,
                                                         {'X': 0, 'Y': 1, 'Z': 2}.get(axis, 3)))
                rebuilt += 1
    return rebuilt


@bpy.app.handlers.persistent
def _on_load(_dummy):
    try:
        n = rebuild_all()
        if n:
            print("[JCNS] rebuilt %d driver channel(s) after file load" % n)
    except Exception as exc:                                  # never break loading
        print("[JCNS] channel rebuild failed: %r" % exc)


def transform_path(transform):
    """The pose-bone data path a TransformType drives, or None."""
    from .jcns_operators import _DRIVABLE
    entry = _DRIVABLE.get(transform)
    return entry[0] if entry else None


def register():
    from .jcns_operators import source_rest_input_of
    bpy.app.driver_namespace['jcns_ch'] = jcns_ch
    get_mapping().set_rest_resolver(source_rest_input_of)
    if _on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load)


def unregister():
    if _on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load)
    bpy.app.driver_namespace.pop('jcns_ch', None)
    get_mapping().set_rest_resolver(None)
    clear_channels()
