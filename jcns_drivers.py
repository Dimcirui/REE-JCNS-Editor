"""
Driver-namespace function backing the generated drivers.

Blender truncates `Driver.expression` at 255 characters, so the expression is
only a call, `jcns_ch("<channel key>", var, var_001, ...)`; the mapping lives in
_CHANNELS, and the real driver variables still declare the dependency on the
source bones for the depsgraph.  Values in _CHANNELS are already in driver
units (radians for rotation), so jcns_ch does no unit conversion.

Engine rules the reads follow:
  * a source with AttrFlags bit0 (BasePose) reads relative to its bone's rest pose;
    without it, the bone's whole parent-relative rotation or position, rest included;
    +25 picks the decomposition (modules/jcns_source_read.py).
  * entries run in file order within one frame, so a source channel written by
    this entry or a later one reads what the last earlier entry on it wrote, evaluated
    in this driver from that entry's own sources, or its rest value when none did.
  * a ConeDriver is one more summed term, read off its cone joint's rotation
    (jcns_source_read.cone_value, measured in Wilds round 20).

A bone's three rotation_euler drivers are built as one group, each evaluating the
whole bone (jcns_source_read.target_basis), when its rotation TransformElement is not
1 (4 / 5 / 6 compose by swing-twist, twist-swing and rotation vector; 13 / 14 hold
one rotation about the last written axis, and a joint group of 13s one Euler rotation
in its +74 order), or when a target entry with AttrFlags
bit0 = 0 lands on a bone with a rest rotation (it replaces the rest pose).
"""

import bpy

from .modules_shim import get_mapping, ensure_path

ensure_path()
import jcns_complex  # noqa: E402
import jcns_source_read  # noqa: E402


# key -> {'maps': [map, …], 'reads': [read, …], 'out': settings}, one map and read per
# source of the single constraint that owns the channel; `out` is how the entry combines
# them (output_settings).  A map is
# the three-point (fs, fk, fe, ts, tk, te, two_point, interpolation), ('CM', keys, (pre, post))
# for a ComplexMapping with its wrap modes, or ('SCALE', k) for CurveType 2 (output = reading
# * k), all already in the driver's units.  A read says which driver
# variables feed the source:
#   ('v',)                        one variable, used as is
#   ('n', key, specs, k, sub)     the hidden channel `key` (an earlier entry's write,
#                                 see below) from len(specs) variables, times k less sub
#   ('c', value)                  none; the source is not live yet, use value
#   ('sc', rest_scale, base)      one variable (pose scale), times the bone's rest scale,
#                                 less 1 when `base` (the source's BasePose bit)
#   ('rot', mode, axis, rest, order, frame, base, live)
#                                 the XYZ Euler channels (radians) `live` gives, the
#                                 others read 0; rest and frame are (w, x, y, z);
#                                 mode is a jcns_source_read.ROTATION_MODES value, order
#                                 the source's +27 RotOrder; `base` reads relative to rest
#   ('loc', axis, rest, offset, live)
#                                 the location channels (metres) `live` gives;
#                                 offset is the rest offset from the parent, metres
#                                 (zero for a BasePose source)
#   ('cone', rest, direction, matrix, angle, base_pose, self_parent, live)
#                                 a ConeDriver: the cone joint's XYZ Euler channels in
#                                 `live` (none when its ParentJoint is the joint itself);
#                                 its map is ('CONE', out_min, out_max, interpolation)
# An element of `live` is an axis, read from one variable, or a channel an earlier entry
# wrote: ('n', axis, key, specs) for one channel, ('g', keys, specs) for all three of a
# bone previewed as a group.  `specs` are the (bone, transform type, rotation mode) of
# the variables the hidden channel reads, in order.  Hidden keys never appear in a
# driver expression.
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
    if read[0] in ('rot', 'loc', 'cone'):
        return sum(1 if isinstance(e, int) else len(e[-1]) for e in read[-1])
    if read[0] == 'n':
        return len(read[2])
    return 1


def _live_channels(live, vals):
    """The three channels a 'rot' / 'loc' / 'cone' read sees, from its variables."""
    chans = [0.0, 0.0, 0.0]
    at = 0
    for e in live:
        if isinstance(e, int):
            chans[e] = vals[at]
            at += 1
            continue
        part = vals[at:at + len(e[-1])]
        at += len(e[-1])
        if e[0] == 'n':
            chans[e[1]] = jcns_ch(e[2], *part)
        else:
            chans = [jcns_ch(k, *part) for k in e[1]]
    return chans


def _read(read, vals):
    """The source value for one 'rot' / 'loc' / 'cone' read from its variables."""
    chans = _live_channels(read[-1], vals)
    if read[0] == 'rot':
        _, mode, axis, rest, order, frame, base, _live = read
        return jcns_source_read.rotation(
            mode, jcns_source_read.read_rotation(rest, chans, base), axis, order, frame)
    if read[0] == 'cone':
        _, rest, direction, matrix, angle, base_pose, self_parent, _live = read
        q = (1.0, 0.0, 0.0, 0.0) if self_parent else jcns_source_read.pose_rotation(rest, chans)
        return jcns_source_read.cone_value(q, rest, direction, matrix, angle, base_pose)
    _, axis, rest, offset, _live = read
    return jcns_source_read.position(rest, offset, chans, axis)


def source_map(s, target_q):
    """The channel-table entry for one source dict (jcns_operators._sources_for_driver).

    Input side in the source's units (its +25), output side in the target's.
    """
    m = get_mapping()
    if s.get('cone'):
        k = s['cone']
        u = _unit_scale(target_q)
        return ('CONE', k['out_min'] * u, k['out_max'] * u, k['interp'])
    src_q = m.source_quantity(s.get('input_type'))
    if s.get('cm'):
        return ('CM', tuple(jcns_complex.scaled(s['cm'], _unit_scale(src_q),
                                                _unit_scale(target_q))),
                tuple(s.get('cm_wrap', (0, 0))))
    if s.get('scale_mapping'):
        return ('SCALE', s['from_start'] * _unit_scale(target_q) / _unit_scale(src_q))
    vals = (s['from_start'], s['from_kink'], s['from_end'],
            s['to_start'],   s['to_kink'],   s['to_end'])
    return tuple(m.driver_anchors(vals, src_q, target_q)) + (m.is_two_point(s.get('attr_flags')),
                                                              s.get('interp', 0))


def channel_id(armature_name, bone, transform, axis):
    """Stable, human-readable key. Quotes are stripped so it is safe to embed."""
    parts = [str(p).replace('"', '').replace('\\', '') for p in
             (armature_name, bone, transform, axis)]
    return "|".join(parts)


SUM_OUTPUT = (0, None, None, False, 1.0)


def output_settings(cns_props, target_q):
    """jcns_mapping.output_settings of the entry plus the driver units per file unit of
    its target quantity: the engine combines and clamps in degrees and centimetres, so the
    mapped values go back to file units for that (a product of radians is not one of
    degrees)."""
    u = _unit_scale(target_q) if target_q else 1.0
    return tuple(get_mapping().output_settings(cns_props)) + (u,)


def register_channel(key, maps, reads=None, post=1.0, out=SUM_OUTPUT):
    """`post` converts the entry's engine value into the Blender channel's space
    (1 / rest scale for a scale target; see jcns_operators.target_post_factor); `out`
    is output_settings()."""
    maps = list(maps)
    _CHANNELS[key] = {'maps': maps, 'reads': list(reads or [READ_VALUE] * len(maps)),
                      'post': float(post), 'out': tuple(out)}


def channel_reads(key):
    ch = _CHANNELS.get(key)
    return ch['reads'] if ch else None


def _nests(read):
    return read[0] == 'n' or (read[0] in ('rot', 'loc', 'cone')
                              and any(not isinstance(e, int) for e in read[-1]))


def channel_nests(key):
    """Channel `key` evaluates an earlier entry's write inside its driver."""
    ch = _CHANNELS.get(key)
    if ch is None:
        return False
    if 'group' in ch:
        g = _GROUPS.get(ch['group'])
        return bool(g) and any(_nests(r) for part in g['parts'] for r in part[4])
    return any(_nests(r) for r in ch['reads'])


def clear_channels():
    _CHANNELS.clear()
    _GROUPS.clear()


# gid -> {'rest': (w, x, y, z), 'parts': [(axis, mode, replaces, maps, reads, out[, rot2_group]), ...]}
# for a bone whose rotation or location drivers are built together; parts are in
# file order of their live entries.  Location groups also carry 'offset', the
# parent-relative rest offset in metres.  The bone's channels are in _CHANNELS as
# {'group': gid, 'axis': a}.
_GROUPS = {}


def register_group(gid, rest, parts, keys, offset=None, parent_scale=None):
    """One bone's group; optional offset selects parent-axis translation.

    `keys` are the three driver channel keys; parts carry winning entries.
    """
    _GROUPS[gid] = {'rest': tuple(rest), 'parts': list(parts)}
    if offset is not None:
        _GROUPS[gid]['offset'] = tuple(offset)
        _GROUPS[gid]['parent_scale'] = tuple(parent_scale or (1.0, 1.0, 1.0))
    for a, key in enumerate(keys):
        _CHANNELS[key] = {'group': gid, 'axis': a}


def group_parts(gid):
    g = _GROUPS.get(gid)
    return g['parts'] if g else None


def _total(maps, reads, values, out=SUM_OUTPUT):
    """One entry's output from its sources, combined and post-processed by `out`
    (output_settings) -> (value, number of driver values consumed)."""
    mp = get_mapping()
    ev = mp.eval_piecewise
    mapped = []
    at = 0
    for m, read in zip(maps, reads):
        width = read_width(read)
        if at + width > len(values):
            break                  # driver built for another layout; Apply rebuilds it
        if read[0] == 'c':
            v = read[1]
        elif read[0] in ('rot', 'loc', 'cone'):
            v = _read(read, values[at:at + width])
        elif read[0] == 'n':
            v = jcns_ch(read[1], *values[at:at + width]) * read[3] - read[4]
        elif read[0] == 'sc':
            v = values[at] * read[1]       # Blender pose scale -> engine scale
            if len(read) > 2 and read[2]:
                v -= 1.0
        else:
            v = values[at]
        at += width
        if m[0] == 'CM':
            mapped.append(jcns_complex.evaluate(m[1], v, *(m[2] if len(m) > 2 else ())))
        elif m[0] == 'SCALE':
            mapped.append(v * m[1])
        elif m[0] == 'CONE':
            mapped.append(m[1] + (m[2] - m[1]) * jcns_source_read.cone_ease(m[3], v))
        else:
            mapped.append(ev(*m[:6], v, two_point=(len(m) > 6 and m[6]),
                             interp=(m[7] if len(m) > 7 else 0)))
    u = out[4]
    return mp.output_value([v / u for v in mapped], *out[:4]) * u, at


def _group_value(ch, values):
    g = _GROUPS.get(ch['group'])
    if g is None:
        return 0.0
    parts = []
    at = 0
    for part in g['parts']:
        axis, mode, replaces, maps, reads, out = part[:6]
        total, used = _total(maps, reads, values[at:], out)
        at += used
        parts.append((axis, mode, replaces, total) + tuple(part[6:]))
    if 'offset' in g:
        return jcns_source_read.translation_basis(
            g['rest'], g['offset'], [(p[0], p[2], p[3]) for p in parts],
            g.get('parent_scale', (1.0, 1.0, 1.0)))[ch['axis']]
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
    # Each source maps independently; the entry combines them by its OutputMode.  A
    # 6-long map entry (no two_point flag) is three-point.
    return _total(ch['maps'], ch['reads'], values, ch.get('out', SUM_OUTPUT))[0] * ch.get('post', 1.0)


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
        if not rp or not (rp.source_filepath or rp.source_version) or rp.target_armature is None:
            continue
        arm = rp.target_armature
        grouped = replacing_bones(arm, obj)
        for bone, chans in grouped.items():
            if register_bone_group(arm, obj, bone, chans):
                rebuilt += 1
        translations = {b for b, transform, axis in group_constraints_by_channel(obj)
                        if transform == 'Trans' and axis != 'W'}
        for bone in translations:
            if register_translation_group(arm, obj, bone, translation_channels(obj, bone)):
                rebuilt += 1
        for (bone, transform, axis), members in group_constraints_by_channel(obj).items():
            if bone in grouped and transform_path(transform) == 'rotation_euler':
                continue
            if bone in translations and transform == 'Trans':
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
                                                         {'X': 0, 'Y': 1, 'Z': 2}.get(axis, 3)),
                                 out=output_settings(members[-1].jcns_cns_props, target_q))
                rebuilt += 1
    return rebuilt


def ensure_namespace():
    """Put jcns_ch back: Blender resets driver_namespace whenever it reads a .blend."""
    if bpy.app.driver_namespace.get('jcns_ch') is not jcns_ch:
        bpy.app.driver_namespace['jcns_ch'] = jcns_ch


@bpy.app.handlers.persistent
def _on_load(_dummy):
    ensure_namespace()
    try:
        n = rebuild_all()
        if n:
            print("[JCNS] rebuilt %d driver channel(s) after file load" % n)
    except Exception as exc:                                  # never break loading
        print("[JCNS] channel rebuild failed: %r" % exc)


# Blender runs a Python driver only in a file it trusts; otherwise it shows the
# "disabled auto-execution" dialog and the driver stays dead.  A saved file therefore
# carries none: they come off before the save and go back right after it, so the
# previews live on in the open session and are applied again after the file is opened.
_STRIPPED = []      # (object name, driver snapshot) of drivers taken off, not yet put back
_FLAGGED = []       # names of entries whose preview_on was cleared for the save
_TARGET_PROPS = ('id', 'data_path', 'bone_target', 'transform_type', 'rotation_mode',
                 'transform_space')


def _jcns_drivers():
    for obj in bpy.data.objects:
        if obj.animation_data is None:
            continue
        for fc in list(obj.animation_data.drivers):
            if fc.driver.type == 'SCRIPTED' and fc.driver.expression.startswith('jcns_ch('):
                yield obj, fc


def _snapshot(fc):
    d = fc.driver
    return {'path': fc.data_path, 'index': fc.array_index, 'mute': fc.mute,
            'use_self': d.use_self, 'expression': d.expression,
            'variables': [(v.name, v.type, [{k: getattr(t, k) for k in _TARGET_PROPS}
                                            for t in v.targets]) for v in d.variables]}


def _put_back(obj, snap):
    obj.animation_data_create()
    obj.driver_remove(snap['path'], snap['index'])
    fc = obj.driver_add(snap['path'], snap['index'])
    fc.keyframe_points.clear()
    fc.mute = snap['mute']
    d = fc.driver
    d.type = 'SCRIPTED'
    d.use_self = snap['use_self']
    while d.variables:
        d.variables.remove(d.variables[0])
    for name, vtype, targets in snap['variables']:
        v = d.variables.new()
        v.name, v.type = name, vtype
        for t, props in zip(v.targets, targets):
            for k, val in props.items():
                setattr(t, k, val)
    d.expression = snap['expression']


@bpy.app.handlers.persistent
def _on_save_pre(*_args):
    try:
        for obj, fc in list(_jcns_drivers()):
            _STRIPPED.append((obj.name, _snapshot(fc)))
            obj.animation_data.drivers.remove(fc)
        from . import jcns_preview
        for obj in bpy.data.objects:
            p = getattr(obj, 'jcns_cns_props', None)
            if p is None or not p.is_jcns_constraint or not p.preview_on:
                continue
            backend = jcns_preview.backend_of(p.constraint_type)
            if backend is not None and backend.id == 'driver':
                p.preview_on = False
                _FLAGGED.append(obj.name)
    except Exception as exc:                                  # never break saving
        print("[JCNS] taking drivers off before save failed: %r" % exc)


@bpy.app.handlers.persistent
def _on_save_post(*_args):
    try:
        for name, snap in _STRIPPED:
            obj = bpy.data.objects.get(name)
            if obj is not None:
                _put_back(obj, snap)
        for name in _FLAGGED:
            obj = bpy.data.objects.get(name)
            if obj is not None:
                obj.jcns_cns_props.preview_on = True
    except Exception as exc:
        print("[JCNS] putting drivers back after save failed: %r" % exc)
    finally:
        _STRIPPED.clear()
        _FLAGGED.clear()


def transform_path(transform):
    """The pose-bone data path a TransformElement drives, or None."""
    from .jcns_operators import _DRIVABLE
    entry = _DRIVABLE.get(transform)
    return entry[0] if entry else None


def register():
    from .jcns_operators import source_rest_input_of
    ensure_namespace()
    get_mapping().set_rest_resolver(source_rest_input_of)
    if _on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load)
    if _on_save_pre not in bpy.app.handlers.save_pre:
        bpy.app.handlers.save_pre.append(_on_save_pre)
    if _on_save_post not in bpy.app.handlers.save_post:
        bpy.app.handlers.save_post.append(_on_save_post)


def unregister():
    if _on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load)
    if _on_save_pre in bpy.app.handlers.save_pre:
        bpy.app.handlers.save_pre.remove(_on_save_pre)
    if _on_save_post in bpy.app.handlers.save_post:
        bpy.app.handlers.save_post.remove(_on_save_post)
    bpy.app.driver_namespace.pop('jcns_ch', None)
    get_mapping().set_rest_resolver(None)
    clear_channels()
