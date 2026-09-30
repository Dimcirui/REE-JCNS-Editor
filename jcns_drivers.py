"""
jcns_drivers.py
---------------
Driver-namespace function backing the generated drivers.

Blender hard-caps `Driver.expression` at 255 characters: assigning anything
longer silently truncates it, which produces an unbalanced-parenthesis
SyntaxError the moment the driver evaluates.  A single three-point mapping
already costs ~170 characters inline, so two sources on one channel overflow —
and shipped files contain channels with up to eight.

So the expression no longer carries the maths.  It reduces to a call:

    jcns_ch("Armature|L_Dress_HJ_01|Rotation|Z", var, var_001)

which stays well under the cap for any number of sources.  The anchors live in
_CHANNELS, keyed by channel, and the actual dependency on the source bones is
still declared through real driver variables so the depsgraph updates correctly.

Values in _CHANNELS are pre-converted to the driver's own units (radians for
rotation), so the function does no unit conversion.
"""

import bpy

from .modules_shim import get_mapping, ensure_path

ensure_path()
import jcns_complex  # noqa: E402


# key -> {'maps': [map, …]}, one map per source of the single constraint that
# owns the channel; their outputs are summed.  A map is either the three-point
# (fs, fk, fe, ts, tk, te, two_point) or ('CM', keys) for a ComplexMapping, both
# already in the driver's units.
_CHANNELS = {}


def _unit_scale(quantity):
    """File units -> driver units for one quantity (degrees -> radians, cm -> m)."""
    return get_mapping()._to_driver_units((1.0,), quantity)[0]


def source_map(s, target_q):
    """The channel-table entry for one source dict (jcns_operators._sources_for_driver).

    Input side in the source's units (its +25), output side in the target's.
    """
    m = get_mapping()
    src_q = m.source_quantity(s.get('src_transform_id'))
    if s.get('cm'):
        return ('CM', tuple(jcns_complex.scaled(s['cm'], _unit_scale(src_q),
                                                _unit_scale(target_q))))
    vals = (s['from_start'], s['from_kink'], s['from_end'],
            s['to_start'],   s['to_kink'],   s['to_end'])
    return tuple(m.driver_anchors(vals, src_q, target_q)) + (m.is_two_point(s.get('update_timing')),)


def channel_id(armature_name, bone, transform, axis):
    """Stable, human-readable key. Quotes are stripped so it is safe to embed."""
    parts = [str(p).replace('"', '').replace('\\', '') for p in
             (armature_name, bone, transform, axis)]
    return "|".join(parts)


def register_channel(key, maps):
    _CHANNELS[key] = {'maps': list(maps)}


def clear_channels():
    _CHANNELS.clear()


def jcns_ch(key, *values):
    """Evaluate one driven channel. Called from every generated driver."""
    ch = _CHANNELS.get(key)
    if ch is None:
        # Cache miss — the .blend was reloaded without the channels being rebuilt.
        # Deliberately do NOT touch bpy.data here: this runs during depsgraph
        # evaluation.  rebuild_all() is called from a load_post handler instead.
        return 0.0
    ev = get_mapping().eval_piecewise
    maps = ch['maps']
    # Each source maps independently and the outputs add up — verified in-game
    # against a two-source constraint swept over its whole input range.
    #
    # A map entry is (fs, fk, fe, ts, tk, te, two_point).  Entries registered by
    # an older build are 6-long; treat those as three-point, which is what the
    # shipped data uses in ~86% of sources.
    total = 0.0
    for i, v in enumerate(values):
        if i >= len(maps):
            break
        m = maps[i]
        if m[0] == 'CM':
            total += jcns_complex.evaluate(m[1], v)
        else:
            total += ev(*m[:6], v, two_point=(len(m) > 6 and m[6]))
    return total


def rebuild_all():
    """Recreate the channel table from the scene, without touching the drivers.

    Runs after a .blend load so drivers saved in the file keep working without
    the user having to press Apply again.
    """
    from . import group_constraints_by_channel
    from .jcns_operators import _sources_for_driver

    clear_channels()
    rebuilt = 0
    for obj in bpy.data.objects:
        rp = getattr(obj, 'jcns_root_props', None)
        if not rp or not rp.source_filepath or rp.target_armature is None:
            continue
        arm = rp.target_armature
        for (bone, transform, axis), members in group_constraints_by_channel(obj).items():
            m = get_mapping()
            target_q = m.target_quantity(transform)
            # Only the last constraint on a channel is live; see _apply_channel.
            maps = [source_map(s, target_q)
                    for s in _sources_for_driver(members[-1].jcns_cns_props) if s['bone']]
            if maps:
                register_channel(channel_id(arm.name, bone, transform, axis), maps)
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


def register():
    bpy.app.driver_namespace['jcns_ch'] = jcns_ch
    if _on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load)


def unregister():
    if _on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load)
    bpy.app.driver_namespace.pop('jcns_ch', None)
    clear_channels()
