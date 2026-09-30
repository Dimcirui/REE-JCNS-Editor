"""
Ranges driver building and the entry editing operators.

The driver code is the Ranges preview backend; jcns_preview.py owns the apply /
clear operators for every section.  A Ranges entry's file order is its '[N]' name
prefix.
"""

import os
import sys
import bpy
from bpy.types import Operator
from bpy.props import StringProperty, BoolProperty, EnumProperty

from . import jcns_cm


# ---------------------------------------------------------------------------
# Module path helper
# ---------------------------------------------------------------------------

def _ensure_modules_path():
    addon_dir = os.path.dirname(__file__)
    modules_dir = os.path.join(addon_dir, "modules")
    if modules_dir not in sys.path:
        sys.path.insert(0, modules_dir)


# ---------------------------------------------------------------------------
# Driver math
# ---------------------------------------------------------------------------

_ROT_TYPE   = ['ROT_X',   'ROT_Y',   'ROT_Z']
_LOC_TYPE   = ['LOC_X',   'LOC_Y',   'LOC_Z']
_SCALE_TYPE = ['SCALE_X', 'SCALE_Y', 'SCALE_Z']


# TransformType name -> (Blender data path, driver variables, quantity driven)
_AXIS_NAME = ['X', 'Y', 'Z', 'W']

_DRIVABLE = {
    'Translation':     ('location',        ['LOC_X', 'LOC_Y', 'LOC_Z'],     'Translation'),
    'Rotation':        ('rotation_euler',  ['ROT_X', 'ROT_Y', 'ROT_Z'],     'Rotation'),
    'Scale':           ('scale',           ['SCALE_X', 'SCALE_Y', 'SCALE_Z'], 'Scale'),
    # The other rotation types drive the same Euler channels; how they compose is
    # jcns_source_read.TARGET_MODES, so a bone carrying one is previewed as a
    # group (see _needs_group).
    'SwingTwist':      ('rotation_euler',  ['ROT_X', 'ROT_Y', 'ROT_Z'],     'Rotation'),
    'TwistSwing':      ('rotation_euler',  ['ROT_X', 'ROT_Y', 'ROT_Z'],     'Rotation'),
    'RotationVector':  ('rotation_euler',  ['ROT_X', 'ROT_Y', 'ROT_Z'],     'Rotation'),
    'AxisRotation':    ('rotation_euler',  ['ROT_X', 'ROT_Y', 'ROT_Z'],     'Rotation'),
    'AxisRotation_14': ('rotation_euler',  ['ROT_X', 'ROT_Y', 'ROT_Z'],     'Rotation'),
}

# What a driver variable reads off a SOURCE bone.  That is set by the source's
# own +25 byte (modules.jcns_mapping.source_quantity), not by what the constraint
# drives: a thigh rotation routinely drives a helper bone's position or scale,
# and a facial slider's position drives an eyelid's rotation.
_SOURCE_VARS = {
    'Translation': ['LOC_X', 'LOC_Y', 'LOC_Z'],
    'Rotation':    ['ROT_X', 'ROT_Y', 'ROT_Z'],
    'Scale':       ['SCALE_X', 'SCALE_Y', 'SCALE_Z'],
}


def _sources_for_driver(cns_props):
    """Convert a constraint's JCNSSourceProperties collection into driver dicts."""
    from . import AXIS_TO_INT
    from .modules_shim import get_mapping
    out = []
    for sp in cns_props.sources:
        out.append({
            'bone':       sp.source_bone,
            'axis_idx':   AXIS_TO_INT.get(sp.source_axis, 0),
            'axis_name':  sp.source_axis,
            'from_start': sp.from_start, 'from_kink': sp.from_kink, 'from_end': sp.from_end,
            'to_start':   sp.to_start,   'to_kink':   sp.to_kink,   'to_end':   sp.to_end,
            # +24 selects the curve mode; see modules.jcns_mapping.is_two_point.
            'update_timing': sp.update_timing,
            # +25 ReadMode, as its byte value: how the source bone is read
            # (modules/jcns_source_read.py).
            'read_mode': get_mapping().read_mode_value(sp.read_mode),
            # +27 EulerOrder and the rest_quat reference frame, both only used by
            # rotation reads (modules/jcns_source_read.py).
            'euler_order': get_mapping().euler_order_value(sp.euler_order),
            'frame': (sp.rest_quat_w, sp.rest_quat_x, sp.rest_quat_y, sp.rest_quat_z),
            # ComplexMapping keys, which replace the anchors when present.
            'cm': jcns_cm.keys(sp),
        })
    return out


# A source channel that is not live yet reads its rest value; see channel_sources.
_REST_VALUE = {'Translation': 0.0, 'Rotation': 0.0, 'Scale': 1.0}


def mesh_rest_scale(bone):
    """Recover positive native rest scale omitted by Blender edit bones.

    RE Mesh Editor keeps the original row-vector local matrix as a bone property;
    without it, or for a mirrored or sheared matrix, the rest scale is unit.
    """
    from mathutils import Matrix
    import math
    raw = bone.get('reMeshLocalMatrix')
    if raw is None:
        return (1.0, 1.0, 1.0)
    m = Matrix(raw).transposed()
    if m.to_3x3().determinant() <= 0:
        return (1.0, 1.0, 1.0)
    scale = tuple(m.to_scale())
    if any(not math.isfinite(v) or v <= 0 for v in scale):
        return (1.0, 1.0, 1.0)
    axes = [m.to_3x3().col[i].normalized() for i in range(3)]
    if any(abs(axes[i].dot(axes[j])) > 1e-5 for i in range(3) for j in range(i)):
        return (1.0, 1.0, 1.0)
    return scale if max(abs(v-1) for v in scale) > 1e-5 else (1.0, 1.0, 1.0)


# Scale lives in two spaces.  The engine's scale is absolute (a written axis takes
# the value, an unwritten one keeps the rest scale), while Blender pose scale is a
# ratio to the rest scale: pose scale 1 is the rest scale.  So a scale target
# drives pose scale = engine value / rest scale, and a scale source reads
# pose scale * rest scale.

def _rest_scale_axis(armature_obj, bone_name, axis):
    b = armature_obj.data.bones.get(bone_name)
    return mesh_rest_scale(b)[axis] if b is not None else 1.0


def target_post_factor(armature_obj, bone_name, transform, axis):
    """What a target channel's engine value is multiplied by to give the Blender
    pose value: 1 / rest scale for a scale channel, 1 otherwise."""
    entry = _DRIVABLE.get(transform)
    if entry is None or entry[0] != 'scale' or not 0 <= axis <= 2:
        return 1.0
    return 1.0 / _rest_scale_axis(armature_obj, bone_name, axis)


def _written_from(root_obj, owner):
    """{(bone, data path, axis)} of every channel whose live writer is `owner` or an
    entry after it in the file.

    Entries run in file order within one frame, so when `owner` reads one of these
    channels the writer has not run yet and the bone is at its unconstrained pose.
    """
    from . import AXIS_TO_INT, get_constraint_empties, group_constraints_by_channel
    order = {e.name: i for i, e in enumerate(get_constraint_empties(root_obj))}
    here = order.get(owner.name, -1)
    out = set()
    for (bone, transform, axis), members in group_constraints_by_channel(root_obj).items():
        entry = _DRIVABLE.get(transform)
        if entry is None or axis == 'W':
            continue
        if order.get(members[-1].name, -1) >= here:
            out.add((bone, entry[0], AXIS_TO_INT.get(axis, 0)))
    return out


def _rest_transform(armature_obj, bone_name):
    """A bone's rest rotation (w, x, y, z) and offset (metres) relative to its parent.

    A bone without a parent counts as identity: its matrix is in armature space,
    which carries the importer's axis conversion rather than an engine transform.
    """
    b = armature_obj.data.bones.get(bone_name)
    if b is None or b.parent is None:
        return (1.0, 0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
    m = b.parent.matrix_local.inverted() @ b.matrix_local
    q = m.to_quaternion()
    return (q.w, q.x, q.y, q.z), tuple(m.translation)


def source_rest_input_of(sp):
    """jcns_mapping's rest resolver: what a JCNSSourceProperties reads with its bone
    at rest, in the file's units, from the target armature's rest pose.

    None when that cannot be known (no armature, bone missing, W axis), so the
    mapping module falls back to an identity rest.
    """
    from . import AXIS_TO_INT, get_jcns_root_from_constraint
    from . import jcns_drivers
    from .modules_shim import get_mapping
    obj = getattr(sp, 'id_data', None)
    if obj is None or getattr(obj, 'jcns_cns_props', None) is None or not sp.source_bone:
        return None
    _, rp = get_jcns_root_from_constraint(obj)
    arm = rp.target_armature if rp is not None else None
    if arm is None or arm.type != 'ARMATURE' or sp.source_bone not in arm.data.bones:
        return None
    axis = AXIS_TO_INT.get(sp.source_axis, 0)
    if axis > 2:
        return None
    rest, off = _rest_transform(arm, sp.source_bone)
    per_cm = get_mapping()._to_driver_units((1.0,), 'Translation')[0]   # metres per cm
    sr = jcns_drivers.jcns_source_read
    return sr.rest_input(sp.read_mode, axis, rest, tuple(v / per_cm for v in off),
                         order=sr.euler_order_value(sp.euler_order),
                         frame=(sp.rest_quat_w, sp.rest_quat_x, sp.rest_quat_y, sp.rest_quat_z),
                         scale=mesh_rest_scale(arm.data.bones[sp.source_bone]))


def channel_sources(armature_obj, root_obj, owner):
    """The source dicts of constraint Empty `owner`, each with the 'read' that tells
    the driver how to feed it (see jcns_drivers._CHANNELS).

    * rotation (+25 = 1/3/4/5) and translation (+25 = 0) sources read the bone's
      whole parent-relative transform, rest included (modules/jcns_source_read.py),
      so the driver takes all three channels and the rest goes into the table;
    * a channel written by this entry or a later one is read at its rest value;
    * scale (+25 = 2) keeps one variable, multiplied by the bone's rest scale.
    """
    from . import jcns_drivers
    from .modules_shim import get_mapping
    mp = get_mapping()
    sources = [s for s in _sources_for_driver(owner.jcns_cns_props) if s['bone']]
    later = _written_from(root_obj, owner) if root_obj is not None else set()
    for s in sources:
        sid = s.get('read_mode')
        q = mp.source_quantity(sid)
        path = _DRIVABLE[q][0]
        axis = min(s.get('axis_idx', 0), 2)
        live = tuple(a for a in range(3) if (s['bone'], path, a) not in later)
        mode = jcns_drivers.jcns_source_read.ROTATION_MODES.get(sid)
        if q == 'Rotation' and mode:
            rest, _off = _rest_transform(armature_obj, s['bone'])
            s['read'] = ('rot', mode, axis, rest, s['euler_order'], s['frame'], live)
        elif q == 'Translation' and sid == 0:
            rest, off = _rest_transform(armature_obj, s['bone'])
            s['read'] = ('loc', axis, rest, off, live)
        elif q == 'Scale':
            k = _rest_scale_axis(armature_obj, s['bone'], axis)
            s['read'] = ('c', k) if (s['bone'], path, axis) in later else ('sc', k)
        elif (s['bone'], path, axis) in later:
            s['read'] = ('c', _REST_VALUE[q])
        else:
            s['read'] = jcns_drivers.READ_VALUE
    return sources


def _apply_driver(armature_obj, target_bone_name, target_axis_idx,
                  sources, transform_type='Rotation'):
    """Install (or replace) the SCRIPTED driver for one channel of one pose bone.

    `sources` are the channel_sources dicts of a single constraint; their outputs
    are summed.  The anchors go to jcns_drivers.register_channel() and the
    expression is only a jcns_ch(...) call (see jcns_drivers).
    Returns (ok, error_str).
    """
    from . import jcns_drivers
    from .modules_shim import get_mapping

    pose_bone = armature_obj.pose.bones.get(target_bone_name)
    if pose_bone is None:
        return False, "找不到目标骨骼「%s」" % target_bone_name

    entry = _DRIVABLE.get(transform_type)
    if entry is None:
        return False, "变换类型「%s」在 Blender 中没有对应通道" % transform_type
    data_path, _, target_q = entry

    usable = [s for s in sources if s.get('bone')]
    if not usable:
        return False, "未设置驱动骨骼"

    # The engine composes q = rest * Rz * Ry * Rx whatever order the file writes the
    # axes in, which is Blender's XYZ Euler mode.
    if data_path == 'rotation_euler' and pose_bone.rotation_mode != 'XYZ':
        pose_bone.rotation_mode = 'XYZ'

    # In the driver's own units, so the namespace function converts nothing.
    maps = [jcns_drivers.source_map(s, target_q) for s in usable]
    reads = [jcns_drivers.source_read(s) for s in usable]

    key = jcns_drivers.channel_id(armature_obj.name, target_bone_name,
                                  transform_type, _AXIS_NAME[target_axis_idx])
    jcns_drivers.register_channel(key, maps, reads, post=target_post_factor(
        armature_obj, target_bone_name, transform_type, target_axis_idx))

    expr = _install_driver(armature_obj, target_bone_name, data_path, target_axis_idx,
                           key, usable, reads)
    if len(expr) > 255:
        return False, ("channel key too long (%d chars) — rename the bone or "
                       "armature" % len(expr))

    print("[JCNS DRIVER] [%s] %d source(s) %s -> %s[%d]  expr=%s" % (
        transform_type, len(usable), ", ".join(s['bone'] for s in usable),
        target_bone_name, target_axis_idx, expr))
    return True, ""


def _install_driver(armature_obj, bone_name, data_path, index, key, sources, reads):
    """Create the jcns_ch driver on one pose-bone channel, with the variables the
    sources' reads ask for, in order.  -> the expression (callers check its length)."""
    from .modules_shim import get_mapping
    pose_bone = armature_obj.pose.bones[bone_name]
    pose_bone.driver_remove(data_path, index)
    armature_obj.animation_data_create()
    fc = armature_obj.driver_add('pose.bones["%s"].%s' % (bone_name, data_path), index)
    # The namespace function already returns the final value. Blender's default
    # identity keyframes remap it again and snap values near 0/1 to those keys.
    fc.keyframe_points.clear()

    drv = fc.driver
    drv.type = 'SCRIPTED'
    while drv.variables:
        drv.variables.remove(drv.variables[0])

    names = []

    def add_var(bone, transform_type, rotation_mode='AUTO'):
        var = drv.variables.new()
        var.name = 'v%d' % len(names)
        names.append(var.name)
        var.type = 'TRANSFORMS'
        tgt = var.targets[0]
        tgt.id = armature_obj
        tgt.bone_target = bone
        tgt.transform_type = transform_type
        tgt.rotation_mode = rotation_mode
        tgt.transform_space = 'LOCAL_SPACE'

    for s, read in zip(sources, reads):
        if read[0] == 'c':
            continue
        if read[0] == 'rot':
            for a in read[-1]:
                add_var(s['bone'], _ROT_TYPE[a], 'XYZ')
            continue
        if read[0] == 'loc':
            for a in read[-1]:
                add_var(s['bone'], _LOC_TYPE[a])
            continue
        add_var(s['bone'], _SOURCE_VARS[get_mapping().source_quantity(
            s.get('read_mode'))][min(s.get('axis_idx', 0), 2)])

    expr = 'jcns_ch("%s"%s)' % (key, "".join("," + n for n in names))
    drv.expression = expr
    return expr


# ---------------------------------------------------------------------------
# Bones previewed as one group (see _needs_group, translation_channels)
# ---------------------------------------------------------------------------

_GROUP_TAG = 'Rot*'          # transform slot of a grouped driver's channel key
_LOCATION_GROUP_TAG = 'Loc*'


def translation_channels(root_obj, bone):
    """Winning parent-axis translation channels; evaluated together in Blender."""
    from . import AXIS_TO_INT, group_constraints_by_channel
    return {AXIS_TO_INT[axis]: members
            for (b, transform, axis), members in group_constraints_by_channel(root_obj).items()
            if b == bone and transform == 'Translation' and axis != 'W'}


def register_translation_group(armature_obj, root_obj, bone, chans):
    from . import jcns_drivers, get_constraint_empties
    order = {e.name: i for i, e in enumerate(get_constraint_empties(root_obj))}
    parts, all_sources, all_reads = [], [], []
    for axis in sorted(chans, key=lambda a: order.get(chans[a][-1].name, -1)):
        members = chans[axis]
        sources = channel_sources(armature_obj, root_obj, members[-1])
        if not sources or any(s['axis_name'] == 'W' for s in sources):
            return None
        reads = [jcns_drivers.source_read(s) for s in sources]
        parts.append((axis, 'location', _replaces(members),
                      [jcns_drivers.source_map(s, 'Translation') for s in sources], reads))
        all_sources += sources
        all_reads += reads
    rest, offset = _rest_transform(armature_obj, bone)
    gid = jcns_drivers.channel_id(armature_obj.name, bone, _LOCATION_GROUP_TAG, '')
    keys = [jcns_drivers.channel_id(armature_obj.name, bone, _LOCATION_GROUP_TAG, _AXIS_NAME[a])
            for a in range(3)]
    jcns_drivers.register_group(gid, rest, parts, keys, offset=offset)
    return keys, all_sources, all_reads


def _apply_translation_bone(armature_obj, root_obj, bone, chans):
    if armature_obj.pose.bones.get(bone) is None:
        return False, "找不到目标骨骼「%s」" % bone
    made = register_translation_group(armature_obj, root_obj, bone, chans)
    if made is None:
        return False, "没有驱动源或 W 轴暂不支持"
    keys, sources, reads = made
    for a, key in enumerate(keys):
        expr = _install_driver(armature_obj, bone, 'location', a, key, sources, reads)
        if len(expr) > 255:
            _drop_group_drivers(armature_obj, bone, 'location', _LOCATION_GROUP_TAG)
            return False, "这根骨的源太多，驱动器表达式超过 255 字符"
    for members in chans.values():
        for e in members:
            e.jcns_cns_props.preview_on = True
    return True, ""


def _replaces(members):
    """The live (last) entry of a channel writes with Flags bit0 = 0."""
    return not (members[-1].jcns_cns_props.cns_flags & 1)


def _target_mode(members):
    """How the live entry of a channel composes its bone's rotation
    (jcns_source_read.TARGET_MODES), from its TransformType."""
    from . import jcns_drivers
    from .jcns_exporter import _transform_int
    tt = _transform_int(members[-1].jcns_cns_props.transform_type)
    return jcns_drivers.jcns_source_read.TARGET_MODES.get(tt, 'euler')


def _rotation_channels(root_obj, bone):
    """{axis: members} for every rotation_euler channel of `bone`.  When two
    rotation types write one axis, the one whose live entry is later in the file
    is kept."""
    from . import AXIS_TO_INT, get_constraint_empties, group_constraints_by_channel
    order = {e.name: i for i, e in enumerate(get_constraint_empties(root_obj))}
    out = {}
    for (b, transform, axis), members in group_constraints_by_channel(root_obj).items():
        entry = _DRIVABLE.get(transform)
        if b == bone and axis != 'W' and entry is not None and entry[0] == 'rotation_euler':
            a = AXIS_TO_INT.get(axis, 0)
            if a not in out or order.get(members[-1].name, -1) > order.get(out[a][-1].name, -1):
                out[a] = members
    return out


def _needs_group(armature_obj, bone, chans):
    """A bone whose rotation cannot be one independent driver per Euler channel:
    a non-Euler rotation type (swing-twist, rotation vector, single axis), or an
    Euler channel replacing a rest rotation."""
    if any(_target_mode(m) != 'euler' for m in chans.values()):
        return True
    if not any(_replaces(m) for m in chans.values()):
        return False
    rest, _off = _rest_transform(armature_obj, bone)
    return abs(rest[0]) < 1.0 - 1e-9          # identity rest: replace == add


def replacing_bones(armature_obj, root_obj):
    """{bone: {axis: members}} of the bones whose rotation is previewed as a group
    (see _needs_group)."""
    from . import group_constraints_by_channel
    bones = {b for (b, t, a) in group_constraints_by_channel(root_obj)}
    out = {}
    for b in bones:
        chans = _rotation_channels(root_obj, b)
        if chans and _needs_group(armature_obj, b, chans):
            out[b] = chans
    return out


def register_bone_group(armature_obj, root_obj, bone, chans):
    """Put one bone's rotation group in the channel table.  -> (keys, sources,
    reads) for the drivers, or None when a channel cannot be previewed."""
    from . import jcns_drivers, get_constraint_empties
    order = {e.name: i for i, e in enumerate(get_constraint_empties(root_obj))}
    parts, all_sources, all_reads = [], [], []
    # File order of the live entries: for a single-axis type the last one wins.
    for axis in sorted(chans, key=lambda a: order.get(chans[a][-1].name, -1)):
        members = chans[axis]
        sources = channel_sources(armature_obj, root_obj, members[-1])
        if any(s['axis_name'] == 'W' for s in sources):
            return None
        reads = [jcns_drivers.source_read(s) for s in sources]
        parts.append((axis, _target_mode(members), _replaces(members),
                      [jcns_drivers.source_map(s, 'Rotation') for s in sources], reads))
        all_sources += sources
        all_reads += reads
    rest, _off = _rest_transform(armature_obj, bone)
    gid = jcns_drivers.channel_id(armature_obj.name, bone, _GROUP_TAG, '')
    keys = [jcns_drivers.channel_id(armature_obj.name, bone, _GROUP_TAG, _AXIS_NAME[a])
            for a in range(3)]
    jcns_drivers.register_group(gid, rest, parts, keys)
    return keys, all_sources, all_reads


def _apply_bone(armature_obj, root_obj, bone, chans):
    """Drive all three rotation_euler channels of `bone` as one group; see
    jcns_drivers.  -> (ok, error)"""
    pose_bone = armature_obj.pose.bones.get(bone)
    if pose_bone is None:
        return False, "找不到目标骨骼「%s」" % bone
    made = register_bone_group(armature_obj, root_obj, bone, chans)
    if made is None:
        return False, "W 轴暂不支持"
    keys, sources, reads = made
    pose_bone.rotation_mode = 'XYZ'
    for a, key in enumerate(keys):
        expr = _install_driver(armature_obj, bone, 'rotation_euler', a, key, sources, reads)
        if len(expr) > 255:
            _drop_group_drivers(armature_obj, bone)
            return False, "这根骨的源太多，驱动器表达式超过 255 字符（%d）" % len(expr)
    for members in chans.values():
        for e in members:
            e.jcns_cns_props.preview_on = True
    print("[JCNS DRIVER] [Rotation group] %s: %d channel(s) %s, %d replacing the rest pose" % (
        bone, len(chans), sorted({_target_mode(m) for m in chans.values()}),
        sum(_replaces(m) for m in chans.values())))
    return True, ""


def _group_driver_axes(armature_obj, bone, data_path='rotation_euler', group_tag=_GROUP_TAG):
    """Axes of the chosen bone data path that carry this group's drivers."""
    ad = armature_obj.animation_data
    if ad is None:
        return []
    path = 'pose.bones["%s"].%s' % (bone, data_path)
    tag = '|%s|' % group_tag
    return [fc.array_index for fc in ad.drivers
            if fc.data_path == path and tag in fc.driver.expression]


def _drop_group_drivers(armature_obj, bone, data_path='rotation_euler', group_tag=_GROUP_TAG):
    pose_bone = armature_obj.pose.bones.get(bone)
    for a in _group_driver_axes(armature_obj, bone, data_path, group_tag):
        try:
            pose_bone.driver_remove(data_path, a)
        except Exception:
            pass



# ---------------------------------------------------------------------------
# Context helpers
# ---------------------------------------------------------------------------

def _get_root_and_armature(context):
    """
    From the active object (root or constraint Empty), return:
      (root_empty, root_props, armature_obj)  or  (None, None, None) on failure.
    """
    from . import get_jcns_root, get_jcns_constraint, get_jcns_root_from_constraint

    obj, root_props = get_jcns_root(context)
    if obj is None:
        cns_obj, _ = get_jcns_constraint(context)
        if cns_obj:
            obj, root_props = get_jcns_root_from_constraint(cns_obj)

    if obj is None or root_props is None:
        return None, None, None

    armature_obj = root_props.target_armature
    if armature_obj is None or armature_obj.type != 'ARMATURE':
        return obj, root_props, None

    return obj, root_props, armature_obj


def _get_active_constraint_props(context):
    """Return jcns_cns_props of active object if it is a constraint Empty, else None."""
    from . import get_jcns_constraint
    _, props = get_jcns_constraint(context)
    return props


def _caps_for(root_props, kind_id):
    """What the UI may offer for a kind in this file (modules/jcns_kinds.py).

    Operators consult the same table as the panels, so a button that is greyed
    out for a reason cannot be bypassed by another route to the same operator.
    """
    from . import file_state
    from .modules_shim import get_kinds
    return get_kinds().capabilities(kind_id, file_state(root_props))


# ---------------------------------------------------------------------------
# Driver refresh (the Ranges preview backend)
# ---------------------------------------------------------------------------

def refresh_channel_values(obj):
    """Update an applied driver's anchors without rebuilding the driver.

    For value edits, which fire per mouse tick.  Structural edits (bone, axis,
    transform type) change the driver's variables and key and take the full path.
    """
    from . import (get_jcns_root_from_constraint, group_constraints_by_channel,
                   channel_key)
    from . import jcns_drivers

    p = getattr(obj, 'jcns_cns_props', None)
    if p is None or not p.is_jcns_constraint or p.constraint_type != 'Ranges':
        return False
    if not p.preview_on:
        return False
    root_obj, rp = get_jcns_root_from_constraint(obj)
    if root_obj is None or rp is None or rp.target_armature is None:
        return False
    members = group_constraints_by_channel(root_obj).get(channel_key(p))
    if not members:
        return False

    entry = _DRIVABLE.get(p.transform_type)
    if entry is None:
        return False
    target_q = entry[2]
    if (entry[0] == 'location' or
            (entry[0] == 'rotation_euler' and _group_driver_axes(rp.target_armature, p.target_bone))):
        # Grouped bone: every driver on it depends on this value; rebuild the group.
        ok, _err, _label = _apply_channel(rp.target_armature, rp, members)
        return ok

    # Only the last constraint on the channel is live — see _apply_channel.
    sources = channel_sources(rp.target_armature, root_obj, members[-1])
    if not sources:
        return False

    key = jcns_drivers.channel_id(rp.target_armature.name, p.target_bone,
                                  p.transform_type, p.target_axis)
    reads = [jcns_drivers.source_read(s) for s in sources]
    if reads != jcns_drivers.channel_reads(key):
        # The driver's variables no longer fit (a source's bone, axis or +25, or
        # its place in the file, changed): rebuild it rather than patch numbers.
        ok, _err, _label = _apply_channel(rp.target_armature, rp, members)
        return ok
    from . import AXIS_TO_INT
    jcns_drivers.register_channel(
        key, [jcns_drivers.source_map(s, target_q) for s in sources], reads,
        post=target_post_factor(rp.target_armature, p.target_bone, p.transform_type,
                                AXIS_TO_INT.get(p.target_axis, 0)))
    rp.target_armature.update_tag()
    return True



def refresh_applied_driver(obj):
    """Re-apply the driver for obj's channel if one is already on it.

    jcns_drivers._CHANNELS is filled at apply time, so an edit must re-register
    the channel.  Silent no-op when nothing is applied; must never interrupt editing.
    """
    from . import (get_jcns_root_from_constraint, group_constraints_by_channel,
                   channel_key, get_constraint_empties)

    # Called on a root: re-apply every previewed channel.
    rp = getattr(obj, 'jcns_root_props', None)
    if rp is not None and rp.source_filepath:
        if rp.target_armature is None:
            return False
        done = 0
        for key, members in group_constraints_by_channel(obj).items():
            if not any(e.jcns_cns_props.preview_on for e in members):
                continue
            try:
                ok, _e, _l = _apply_channel(rp.target_armature, rp, members)
                done += bool(ok)
            except Exception as exc:
                print("[JCNS] auto-refresh failed: %r" % exc)
        if done:
            rp.target_armature.update_tag()
        return bool(done)

    p = getattr(obj, 'jcns_cns_props', None)
    if p is None or not p.is_jcns_constraint or p.constraint_type != 'Ranges':
        return False
    if not p.preview_on:
        return False
    root_obj, root_props = get_jcns_root_from_constraint(obj)
    if root_obj is None or root_props is None or root_props.target_armature is None:
        return False
    members = group_constraints_by_channel(root_obj).get(channel_key(p))
    if not members:
        return False
    try:
        ok, _err, _label = _apply_channel(root_props.target_armature, root_props, members)
    except Exception as exc:                      # never break the UI over this
        print("[JCNS] auto-refresh failed: %r" % exc)
        return False
    if ok:
        root_props.target_armature.update_tag()
    return ok



def _apply_channel(armature_obj, root_props, members):
    """Apply the driver for one channel.

    `members` are constraint Empties with identical (bone, transform, axis), in
    file order.  Only the last one has any effect, and its sources are summed, so
    the driver is built from members[-1] alone.
    """
    from . import AXIS_TO_INT
    bone, transform, axis = _channel_of(members[0])

    from . import get_jcns_root_from_constraint
    winner = members[-1]
    root_obj, _ = get_jcns_root_from_constraint(winner)

    entry = _DRIVABLE.get(transform)
    if entry is not None and entry[0] == 'location' and bone and root_obj is not None:
        if axis == 'W':
            return False, "W 轴暂不支持", bone
        chans = translation_channels(root_obj, bone)
        ok, err = _apply_translation_bone(armature_obj, root_obj, bone, chans)
        return ok, err, "%s（整骨预览 %d 个平移通道）" % (bone, len(chans))
    if entry is not None and entry[0] == 'rotation_euler' and bone and root_obj is not None:
        chans = _rotation_channels(root_obj, bone)
        if _needs_group(armature_obj, bone, chans):
            ok, err = _apply_bone(armature_obj, root_obj, bone, chans)
            label = "%s（整骨预览 %d 个旋转通道）" % (bone, len(chans))
            return ok, err, label
        if _group_driver_axes(armature_obj, bone):
            # The bone was grouped before (a bit0 or rest change): take the group
            # down and bring its other previewed channels back one by one.
            _drop_group_drivers(armature_obj, bone)
            for a, other in chans.items():
                if other is not members and any(e.jcns_cns_props.preview_on for e in other):
                    _apply_channel(armature_obj, root_props, other)

    sources = channel_sources(armature_obj, root_obj, winner)

    label = "%s(%s) <- %d source(s)" % (bone or '???', axis, len(sources))
    if len(members) > 1:
        label += "，同通道 %d 条中最后一条生效" % len(members)

    if not sources:
        return False, "没有驱动源", label
    if axis == 'W' or any(s['axis_name'] == 'W' for s in sources):
        return False, "W 轴暂不支持", label
    if not bone:
        return False, "目标骨骼未解析", label

    ok, err = _apply_driver(
        armature_obj, bone, AXIS_TO_INT.get(axis, 0), sources,
        transform_type=transform,
    )
    if ok:
        for empty in members:
            empty.jcns_cns_props.preview_on = True
    return ok, err, label


def _channel_of(empty):
    from . import channel_key
    return channel_key(empty.jcns_cns_props)


def _clear_channel(armature_obj, members):
    """Remove the driver of one channel and mark its constraints as not previewed."""
    from . import AXIS_TO_INT, get_jcns_root_from_constraint
    bone, transform, axis = _channel_of(members[0])
    entry = _DRIVABLE.get(transform)
    pose_bone = armature_obj.pose.bones.get(bone)
    if (entry is not None and entry[0] == 'location' and pose_bone is not None
            and _group_driver_axes(armature_obj, bone, 'location', _LOCATION_GROUP_TAG)):
        _drop_group_drivers(armature_obj, bone, 'location', _LOCATION_GROUP_TAG)
        pose_bone.location = (0.0, 0.0, 0.0)
        root_obj, _ = get_jcns_root_from_constraint(members[0])
        if root_obj is not None:
            for other in translation_channels(root_obj, bone).values():
                for e in other:
                    e.jcns_cns_props.preview_on = False
    if (entry is not None and entry[0] == 'rotation_euler' and pose_bone is not None
            and _group_driver_axes(armature_obj, bone)):
        # A grouped bone comes down as a whole.
        _drop_group_drivers(armature_obj, bone)
        root_obj, _ = get_jcns_root_from_constraint(members[0])
        if root_obj is not None:
            for other in _rotation_channels(root_obj, bone).values():
                for e in other:
                    e.jcns_cns_props.preview_on = False
    if entry is not None and pose_bone is not None:
        try:
            pose_bone.driver_remove(entry[0], AXIS_TO_INT.get(axis, 0))
        except Exception:
            pass
        if entry[0] == 'scale' and axis != 'W':
            pose_bone.scale[AXIS_TO_INT.get(axis, 0)] = 1.0    # the rest scale, in Blender
    for e in members:
        e.jcns_cns_props.preview_on = False


# ---------------------------------------------------------------------------
# Duplicate-index bookkeeping
# ---------------------------------------------------------------------------
#
# Native Blender duplication copies the '[N]' name prefix, and Blender only
# appends '.001', so two Ranges Empties can share an index and their file order
# becomes arbitrary.  The depsgraph handler below renumbers collisions as soon
# as they appear.

def dedupe_constraint_indices(root_obj):
    """Give every duplicate '[N]' index directly under root_obj a free number.

    Touches only colliding or unparsable Empties.  Returns how many were renumbered.
    """
    from . import get_constraint_empties, constraint_name_from_props

    def parsed_index(obj):
        name = obj.name
        if name.startswith('['):
            try:
                return int(name[1:name.index(']')])
            except (ValueError, IndexError):
                pass
        return None

    empties = get_constraint_empties(root_obj)
    next_free = 0
    for obj in empties:
        idx = parsed_index(obj)
        if idx is not None:
            next_free = max(next_free, idx + 1)

    seen = set()
    fixed = 0
    for obj in empties:
        idx = parsed_index(obj)
        if idx is not None and idx not in seen:
            seen.add(idx)
            continue
        obj.name = constraint_name_from_props(next_free, obj.jcns_cns_props)
        seen.add(next_free)
        next_free += 1
        fixed += 1
    return fixed


@bpy.app.handlers.persistent
def _on_depsgraph_update_fix_duplicates(scene, depsgraph):
    try:
        from . import get_jcns_root_from_constraint
        roots = set()
        for update in depsgraph.updates:
            obj = update.id
            if not isinstance(obj, bpy.types.Object):
                continue
            props = getattr(obj, 'jcns_cns_props', None)
            if not (props and props.is_jcns_constraint):
                continue
            root_obj, _ = get_jcns_root_from_constraint(obj)
            if root_obj is not None:
                roots.add(root_obj)
        for root_obj in roots:
            dedupe_constraint_indices(root_obj)
    except Exception as exc:                     # a handler must never hard-fail
        print("[JCNS] duplicate-index fix skipped: %r" % exc)


# ---------------------------------------------------------------------------
# Operator: Add Constraint
# ---------------------------------------------------------------------------

class JCNS_OT_AddConstraint(Operator):
    """在当前 JCNS 集合里新增一条空白约束"""
    bl_idname = "jcns.add_constraint"
    bl_label  = "新增约束"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        from . import get_export_root
        obj, rp = get_export_root(context)
        return obj is not None and _caps_for(rp, 'Ranges').can_add

    def execute(self, context):
        from . import (get_export_root, get_constraint_empties,
                       make_constraint_empty_name)

        root_obj, root_props = get_export_root(context)
        existing = get_constraint_empties(root_obj)
        new_idx = len(existing)

        coll = None
        for c in root_obj.users_collection:
            coll = c
            break
        if coll is None:
            self.report({'ERROR'}, "根节点不属于任何集合。")
            return {'CANCELLED'}

        name = make_constraint_empty_name(new_idx, 'BoneName', '', 'X')
        obj = bpy.data.objects.new(name, None)
        obj.empty_display_type = 'ARROWS'
        obj.empty_display_size = 0.05
        obj.parent = root_obj
        coll.objects.link(obj)

        p = obj.jcns_cns_props
        p.is_jcns_constraint = True
        p.constraint_type = 'Ranges'
        p.target_bone = ''
        p.transform_type = 'Rotation'
        sp = p.sources.add()          # every new constraint starts with one source
        sp.source_bone = 'BoneName'


        context.view_layer.objects.active = obj
        obj.select_set(True)
        self.report({'INFO'}, f"已新增约束「{name}」。")
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Operator: Delete Constraint
# ---------------------------------------------------------------------------

class JCNS_OT_DeleteConstraint(Operator):
    """删除选中的约束，其余约束重新编号"""
    bl_idname = "jcns.delete_constraint"
    bl_label  = "删除约束"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        from . import get_jcns_constraint, get_jcns_root_from_constraint
        obj, p = get_jcns_constraint(context)
        if obj is None:
            return False
        _, rp = get_jcns_root_from_constraint(obj)
        return rp is not None and _caps_for(rp, p.constraint_type).can_remove

    def execute(self, context):
        from . import (get_jcns_constraint, get_jcns_root_from_constraint,
                       get_constraint_empties)

        cns_obj, cns_props = get_jcns_constraint(context)
        root_obj, root_props = get_jcns_root_from_constraint(cns_obj)
        kind = cns_props.constraint_type

        bpy.data.objects.remove(cns_obj, do_unlink=True)

        if root_obj:
            if kind in ('Skin', 'Aim', 'RotExpression'):
                _renumber_sections(root_obj, kind)
            else:
                _renumber_in_order(get_constraint_empties(root_obj))

        self.report({'INFO'}, "约束已删除，其余已重新编号。")
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Operator: Move Constraint
# ---------------------------------------------------------------------------

def _renumber_in_order(ordered):
    """Rewrite every Empty's '[N]' prefix to match its position in `ordered`.

    Two passes, because Blender appends '.001' to a taken name and two constraints
    on the same channel differ only by the prefix.
    """
    from . import constraint_name_from_props

    for i, empty in enumerate(ordered):
        empty.name = "__jcns_reorder_%d" % i
    for i, empty in enumerate(ordered):
        empty.name = constraint_name_from_props(i, empty.jcns_cns_props)


def _renumber_sections(root_obj, kind):
    """Close the gap in '[<Prefix>NN]' after a section entry was removed."""
    from . import section_empties, section_empty_name
    ordered = section_empties(root_obj, kind)
    for i, o in enumerate(ordered):
        o.name = "__jcns_reorder_%d" % i
    for i, o in enumerate(ordered):
        o.name = section_empty_name(kind, i, o.jcns_cns_props)


class JCNS_OT_MoveConstraint(Operator):
    """把选中的约束在文件里前移或后移一位。同一骨骼同一轴上有多条约束时只有最后一条生效"""
    bl_idname = "jcns.move_constraint"
    bl_label  = "移动约束"
    bl_options = {'REGISTER', 'UNDO'}

    direction: EnumProperty(
        name="方向",
        items=[('UP', "上移", "往文件前面挪一位"),
               ('DOWN', "下移", "往文件后面挪一位")],
        default='UP',
    )

    @classmethod
    def poll(cls, context):
        from . import get_jcns_constraint, get_jcns_root_from_constraint
        obj, p = get_jcns_constraint(context)
        if obj is None:
            return False
        _, rp = get_jcns_root_from_constraint(obj)
        return rp is not None and _caps_for(rp, p.constraint_type).can_move

    def execute(self, context):
        from . import (get_jcns_constraint, get_jcns_root_from_constraint,
                       get_constraint_empties)

        cns_obj, _ = get_jcns_constraint(context)
        root_obj, _ = get_jcns_root_from_constraint(cns_obj)
        if root_obj is None:
            self.report({'ERROR'}, "找不到所属的 JCNS 根节点。")
            return {'CANCELLED'}

        ordered = get_constraint_empties(root_obj)
        try:
            pos = ordered.index(cns_obj)
        except ValueError:
            # Aim / RotExpression / Material Empties are not part of the ordered
            # constraint list, so there is nothing to move them within.
            self.report({'ERROR'}, "该类型的约束不参与排序。")
            return {'CANCELLED'}

        new_pos = pos - 1 if self.direction == 'UP' else pos + 1
        if not (0 <= new_pos < len(ordered)):
            edge = "最前面" if self.direction == 'UP' else "最后面"
            self.report({'INFO'}, "已经在%s了。" % edge)
            return {'CANCELLED'}

        ordered[pos], ordered[new_pos] = ordered[new_pos], ordered[pos]
        _renumber_in_order(ordered)

        self.report({'INFO'}, "已移动到第 %d 位（共 %d 条）。" % (new_pos + 1, len(ordered)))
        return {'FINISHED'}


class JCNS_OT_AddSource(Operator):
    """给选中的约束再加一个驱动源。多个源的输出相加"""
    bl_idname = "jcns.add_source"
    bl_label  = "新增驱动源"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        from . import get_jcns_constraint
        obj, props = get_jcns_constraint(context)
        return obj is not None and props.constraint_type == 'Ranges'

    def execute(self, context):
        from . import get_jcns_constraint, constraint_name_from_props
        cns_obj, p = get_jcns_constraint(context)
        sp = p.sources.add()
        # Seed from the previous source so the new one is a usable starting point
        if len(p.sources) > 1:
            prev = p.sources[len(p.sources) - 2]
            for attr in ('source_axis', 'from_start', 'from_kink', 'from_end',
                         'to_start', 'to_kink', 'to_end', 'update_timing',
                         'read_mode', 'rest_quat_w'):
                setattr(sp, attr, getattr(prev, attr))
        p.active_source_index = len(p.sources) - 1
        idx = 0
        if cns_obj.name.startswith('['):
            try:
                idx = int(cns_obj.name[1:cns_obj.name.index(']')])
            except (ValueError, IndexError):
                pass
        cns_obj.name = constraint_name_from_props(idx, p)
        self.report({'INFO'}, "已新增第 %d 个驱动源。" % len(p.sources))
        return {'FINISHED'}


class JCNS_OT_RemoveSource(Operator):
    """删除当前约束里选中的驱动源"""
    bl_idname = "jcns.remove_source"
    bl_label  = "删除驱动源"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        from . import get_jcns_constraint
        obj, props = get_jcns_constraint(context)
        return obj is not None and len(props.sources) > 1

    def execute(self, context):
        from . import get_jcns_constraint, constraint_name_from_props
        cns_obj, p = get_jcns_constraint(context)
        i = min(p.active_source_index, len(p.sources) - 1)
        jcns_cm.remove(p.sources[i])
        p.sources.remove(i)
        p.active_source_index = max(0, min(i, len(p.sources) - 1))
        idx = 0
        if cns_obj.name.startswith('['):
            try:
                idx = int(cns_obj.name[1:cns_obj.name.index(']')])
            except (ValueError, IndexError):
                pass
        cns_obj.name = constraint_name_from_props(idx, p)
        self.report({'INFO'}, "已删除驱动源，剩余 %d 个。" % len(p.sources))
        return {'FINISHED'}



class JCNS_OT_SwapMapToEnds(Operator):
    """交换当前源的「To 起点」和「To 终点」。映射方向朝下时，静止姿态落在终点，交换后骨骼静止时不再偏转"""
    bl_idname = "jcns.swap_mapto_ends"
    bl_label  = "对调输出首尾"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        from . import get_jcns_constraint
        obj, props = get_jcns_constraint(context)
        return (obj is not None and props.constraint_type == 'Ranges'
                and len(props.sources) > 0)

    def execute(self, context):
        from . import get_jcns_constraint
        from .modules_shim import get_mapping
        _, p = get_jcns_constraint(context)
        sp = p.sources[min(p.active_source_index, len(p.sources) - 1)]
        before = get_mapping().describe(sp)['at_rest']
        sp.to_start, sp.to_end = sp.to_end, sp.to_start
        after = get_mapping().describe(sp)['at_rest']
        self.report({'INFO'},
                    "输出首尾已对调 —— 静止输出 %+.2f° → %+.2f°" % (before, after))
        return {'FINISHED'}



class JCNS_OT_MirrorConstraints(Operator):
    """把选中的约束镜像到骨架的另一侧。各轴符号按骨骼的局部坐标系决定，缩放和形变权重不取反。目标和驱动源是否换到对侧由两个开关分别控制，中线骨骼只需镜像另一方"""
    bl_idname = "jcns.mirror_constraints"
    bl_label  = "镜像到另一侧"
    bl_options = {'REGISTER', 'UNDO'}

    mirror_target: BoolProperty(
        name="镜像目标骨骼", default=True,
        description="把目标骨骼也翻转到对侧。关闭后目标骨骼保持不变——用于"
                    "目标是中线/共享骨骼（没有 L/R 配对），只有驱动来源需要"
                    "换到对侧的情况")
    mirror_source: BoolProperty(
        name="镜像驱动来源", default=True,
        description="把每个驱动来源骨骼也翻转到对侧。关闭后驱动来源保持不变"
                    "——用于来源是中线/共享骨骼，只有目标需要换到对侧的情况")
    overwrite: BoolProperty(
        name="覆盖已有数值", default=False,
        description="对侧已有同名约束时，用镜像结果覆盖它的数值。"
                    "约一成的左右配对本来就不对称，所以默认不覆盖")
    use_frames: BoolProperty(
        name="从骨架读取符号", default=True,
        description="按每对骨骼的局部坐标系决定各轴的符号。"
                    "关闭则使用默认符号（X:+1, Y:-1, Z:-1）")

    @classmethod
    def poll(cls, context):
        from . import get_jcns_constraint
        obj, props = get_jcns_constraint(context)
        return obj is not None and props.constraint_type == 'Ranges'

    def draw(self, context):
        layout = self.layout
        row = layout.row(align=True)
        row.prop(self, "mirror_target")
        row.prop(self, "mirror_source")
        layout.prop(self, "use_frames")
        layout.prop(self, "overwrite")
        col = layout.column(align=True)
        col.label(text="符号由骨骼坐标系与驱动量类型决定", icon='INFO')
        col.label(text="旋转与位移镜像方式相反，缩放不变号；来源按 +25 区分")
        if not (self.mirror_target or self.mirror_source):
            col.label(text="目标与来源至少要镜像一项", icon='ERROR')

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        from . import (get_jcns_constraint, get_jcns_root_from_constraint,
                       get_constraint_empties, constraint_name_from_props)
        from .modules_shim import get_mirror

        if not self.mirror_target and not self.mirror_source:
            self.report({'ERROR'}, "目标与来源至少要镜像一项。")
            return {'CANCELLED'}

        active, _ = get_jcns_constraint(context)
        root_obj, root_props = get_jcns_root_from_constraint(active)
        if root_obj is None:
            self.report({'ERROR'}, "找不到所属的 JCNS 根节点。")
            return {'CANCELLED'}

        # Work on the selection so several can be done at once, but the active
        # constraint is always included — that is what the panel button implies.
        targets = [o for o in context.selected_objects
                   if getattr(o, 'jcns_cns_props', None)
                   and o.jcns_cns_props.is_jcns_constraint
                   and o.jcns_cns_props.constraint_type == 'Ranges']
        if active not in targets:
            targets.append(active)

        mirror = get_mirror()
        flip = bpy.utils.flip_name
        arm = root_props.target_armature if root_props else None
        sigma_cache = {}

        def bone_exists(name):
            return arm is None or name in arm.data.bones

        def partner(name):
            return mirror.counterpart(name, bone_exists, flip)

        def sigma(name):
            if not self.use_frames or arm is None:
                return None
            if name in sigma_cache:
                return sigma_cache[name]
            b, mate = arm.data.bones.get(name), partner(name)
            v = None
            if b is not None and mate:
                r = arm.data.bones.get(mate)
                if r is not None:
                    L, R = b.matrix_local.to_3x3(), r.matrix_local.to_3x3()
                    v = mirror.sigma_from_frames(
                        [tuple(L.col[i]) for i in range(3)],
                        [tuple(R.col[i]) for i in range(3)])
            sigma_cache[name] = v
            return v

        existing = {}
        for e in get_constraint_empties(root_obj):
            p = e.jcns_cns_props
            existing.setdefault(mirror.constraint_signature(
                p.target_bone, p.transform_type, p.target_axis,
                [(s.source_bone, s.source_axis) for s in p.sources]), e)

        coll = next(iter(root_obj.users_collection), None)
        made = updated = kept = 0
        problems = []

        for e in targets:
            p = e.jcns_cns_props

            if self.mirror_target:
                new_tgt = partner(p.target_bone)
                if new_tgt is None:
                    problems.append("%s 没有对侧骨骼" % (p.target_bone or "?"))
                    continue
                tgt_sigma = sigma(p.target_bone)
            else:
                # Target is fixed (e.g. a centre-line bone) — keep it as-is,
                # no counterpart lookup and no sigma needed for that side.
                new_tgt = p.target_bone
                tgt_sigma = None

            new_sources, failed = [], None
            for sp in p.sources:
                if self.mirror_source:
                    mate = partner(sp.source_bone)
                    if mate is None:
                        failed = "%s 没有对侧骨骼" % sp.source_bone
                        break
                    src_sigma = sigma(sp.source_bone)
                else:
                    # Source is fixed, as for the target above.
                    mate = sp.source_bone
                    src_sigma = None
                vals, i_s, o_s = mirror.mirror_source(
                    sp, sp.source_axis, p.target_axis, p.cns_flags,
                    src_sigma, tgt_sigma, p.transform_type,
                    mirror_in=self.mirror_source, mirror_out=self.mirror_target)
                if vals is None:
                    failed = "%s 的 %s 轴无法确定镜像符号" % (sp.source_bone,
                                                             sp.source_axis)
                    break
                if self.mirror_source:
                    # The reference frame is a rotation in the source's local axes, so
                    # it reflects like any rotation: its vector part flips by sigma.
                    sg = src_sigma or mirror.SIGMA_DEFAULT
                    comps = (sp.rest_quat_x, sp.rest_quat_y, sp.rest_quat_z)
                    if any(abs(c) > 1e-9 and sg.get(a) is None for c, a in zip(comps, 'XYZ')):
                        failed = "%s 的参考系四元数无法镜像" % sp.source_bone
                        break
                    vals['_frame'] = tuple(c * (sg.get(a) or 1) for c, a in zip(comps, 'XYZ'))
                new_sources.append((mate, sp.source_axis, vals, sp, i_s, o_s))
            if failed:
                problems.append(failed)
                continue

            sig = mirror.constraint_signature(
                new_tgt, p.transform_type, p.target_axis,
                [(s[0], s[1]) for s in new_sources])

            dst = existing.get(sig)
            if dst is not None and not self.overwrite:
                kept += 1
                continue
            if dst is None:
                dst = bpy.data.objects.new("jcns_mirrored", None)
                dst.empty_display_type = 'ARROWS'
                dst.empty_display_size = 0.05
                dst.parent = root_obj
                coll.objects.link(dst)
                existing[sig] = dst
                made += 1
            else:
                updated += 1

            q = dst.jcns_cns_props
            q.is_jcns_constraint = True
            q.constraint_type = 'Ranges'
            q.target_bone = new_tgt
            q.target_axis = p.target_axis
            q.transform_type = p.transform_type
            q.cns_flags = p.cns_flags
            for old in q.sources:
                jcns_cm.remove(old)
            q.sources.clear()
            for bone, axis, vals, orig, i_s, o_s in new_sources:
                ns = q.sources.add()
                ns.source_bone = bone
                ns.source_axis = axis
                for k, v in vals.items():
                    if not k.startswith('_'):
                        setattr(ns, k, v)
                for attr in ('rest_quat_x', 'rest_quat_y', 'rest_quat_z',
                             'rest_quat_w', 'update_timing', 'read_mode',
                             'euler_order', 'unknown_uint16', 'unknown_uint32_2'):
                    setattr(ns, attr, getattr(orig, attr))
                if '_frame' in vals:
                    ns.rest_quat_x, ns.rest_quat_y, ns.rest_quat_z = vals['_frame']
                if jcns_cm.has_curve(orig):
                    jcns_cm.copy_keys(orig, ns, lambda k, i_s=i_s, o_s=o_s:
                                      jcns_cm.jcns_complex.mirrored(k, i_s, o_s))

        for i, empty in enumerate(get_constraint_empties(root_obj)):
            empty.name = constraint_name_from_props(i, empty.jcns_cns_props)

        parts = []
        if made:
            parts.append("新建 %d 条" % made)
        if updated:
            parts.append("更新 %d 条" % updated)
        if kept:
            parts.append("跳过 %d 条已存在的（可勾选覆盖）" % kept)
        msg = "镜像完成：" + ("，".join(parts) if parts else "无改动")
        if problems:
            msg += "；" + "，".join(problems[:2])
            self.report({'WARNING'}, msg)
        else:
            self.report({'INFO'}, msg)
        return {'FINISHED'}



class JCNS_OT_SortAnchors(Operator):
    """把三个锚点按输入重新排序，曲线形状不变。锚点折返时有一个锚点取不到，排序后三个都能生效"""
    bl_idname = "jcns.sort_anchors"
    bl_label  = "按源角度排序锚点"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        from . import get_jcns_constraint
        obj, props = get_jcns_constraint(context)
        return (obj is not None and props.constraint_type == 'Ranges'
                and len(props.sources) > 0)

    def execute(self, context):
        from . import get_jcns_constraint
        from .modules_shim import get_mapping
        _, p = get_jcns_constraint(context)
        sp = p.sources[min(p.active_source_index, len(p.sources) - 1)]

        pairs = sorted(((sp.from_start, sp.to_start),
                        (sp.from_kink,  sp.to_kink),
                        (sp.from_end,   sp.to_end)), key=lambda t: t[0])
        # keep the file's own direction: a descending MapFrom stays descending
        if sp.from_start > sp.from_end:
            pairs.reverse()
        (sp.from_start, sp.to_start), (sp.from_kink, sp.to_kink),             (sp.from_end, sp.to_end) = pairs

        d = get_mapping().plain_description(sp)
        self.report({'INFO'}, "锚点已排序：%s" % (
            "全部可用" if d['unreachable_anchor'] is None
            else "仍有锚点 %s 取不到" % d['unreachable_anchor']))
        return {'FINISHED'}



# ---------------------------------------------------------------------------
# Operators: non-range sections (SkinConstraint / Aim / RotExpression)
# ---------------------------------------------------------------------------

def _rebuild_root(context):
    """(root, root_props) when the active JCNS file is rebuilt on export (v35 / v102)
    and its importer cached the section data; (None, None) otherwise."""
    from . import get_export_root
    root, rp = get_export_root(context)
    if root is None or not rp.sections_cached:
        return None, None
    from .modules_shim import ensure_path
    ensure_path()
    from jcns_parser import write_mode
    from .jcns_exporter import _root_version
    return (root, rp) if write_mode(_root_version(rp)) == 'rebuild' else (None, None)


class JCNS_OT_AddSectionEntry(Operator):
    """在当前 JCNS 文件里新增一条 Skin / Aim / RotExpr 条目"""
    bl_idname = "jcns.add_section_entry"
    bl_label  = "新增条目"
    bl_options = {'REGISTER', 'UNDO'}

    kind: EnumProperty(items=[('Skin', "SkinConstraint", ""), ('Aim', "Aim", ""),
                              ('RotExpression', "RotExpression", "")])

    @classmethod
    def poll(cls, context):
        return _rebuild_root(context)[0] is not None

    def execute(self, context):
        from . import section_empties, section_empty_name
        root, rp = _rebuild_root(context)
        coll = next(iter(root.users_collection), None)
        if coll is None:
            self.report({'ERROR'}, "根节点不属于任何集合。")
            return {'CANCELLED'}
        caps = _caps_for(rp, self.kind)
        if not caps.can_add:
            self.report({'ERROR'}, caps.reason('add') or "不能新增这类条目。")
            return {'CANCELLED'}
        idx = len(section_empties(root, self.kind))
        display = {'Skin': 'SINGLE_ARROW', 'Aim': 'SPHERE', 'RotExpression': 'CIRCLE'}[self.kind]
        obj = bpy.data.objects.new("__jcns_new_section", None)
        obj.empty_display_type = display
        obj.empty_display_size = 0.03
        obj.parent = root
        coll.objects.link(obj)
        p = obj.jcns_cns_props
        p.is_jcns_constraint = True
        p.constraint_type = self.kind
        if self.kind == 'Skin':
            w = p.skin_sources.add()
            w.weight = 1.0
        obj.name = section_empty_name(self.kind, idx, p)
        for o in context.selected_objects:
            o.select_set(False)
        context.view_layer.objects.active = obj
        obj.select_set(True)
        self.report({'INFO'}, f"已新增「{obj.name}」。")
        return {'FINISHED'}


def _active_section(context, kind):
    from . import get_jcns_constraint
    obj, p = get_jcns_constraint(context)
    if obj is None or p.constraint_type != kind:
        return None, None
    return obj, p


class JCNS_OT_SkinSourceAdd(Operator):
    """给选中的 Skin 条目加一根源骨骼"""
    bl_idname = "jcns.skin_source_add"
    bl_label  = "新增源骨骼"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _active_section(context, 'Skin')[0] is not None

    def execute(self, context):
        _, p = _active_section(context, 'Skin')
        w = p.skin_sources.add()
        w.weight = 0.0
        p.active_skin_source_index = len(p.skin_sources) - 1
        return {'FINISHED'}


class JCNS_OT_SkinSourceRemove(Operator):
    """删除选中 Skin 条目里当前的源骨骼"""
    bl_idname = "jcns.skin_source_remove"
    bl_label  = "删除源骨骼"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj, p = _active_section(context, 'Skin')
        return obj is not None and len(p.skin_sources) > 0

    def execute(self, context):
        _, p = _active_section(context, 'Skin')
        i = min(p.active_skin_source_index, len(p.skin_sources) - 1)
        p.skin_sources.remove(i)
        p.active_skin_source_index = max(0, i - 1)
        return {'FINISHED'}


class JCNS_OT_SkinNormalizeWeights(Operator):
    """按比例缩放选中条目的权重，使总和为 1"""
    bl_idname = "jcns.skin_normalize_weights"
    bl_label  = "权重归一化"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj, p = _active_section(context, 'Skin')
        return obj is not None and sum(w.weight for w in p.skin_sources) > 0

    def execute(self, context):
        _, p = _active_section(context, 'Skin')
        total = sum(w.weight for w in p.skin_sources)
        for w in p.skin_sources:
            w.weight /= total
        return {'FINISHED'}


def _active_source_props(context):
    from . import get_jcns_constraint
    obj, p = get_jcns_constraint(context)
    if obj is None or p.constraint_type not in ('Ranges', '') or not len(p.sources):
        return None
    return p.sources[min(p.active_source_index, len(p.sources) - 1)]


def _cm_source(context):
    """(constraint Empty, active source) when its ComplexMapping may be edited, else (None, None)."""
    from . import get_jcns_constraint
    sp = _active_source_props(context)
    if sp is None or _rebuild_root(context)[0] is None:
        return None, None
    return get_jcns_constraint(context)[0], sp


class JCNS_OT_CMCreate(Operator):
    """把当前源的三点映射换成画出同样折线的关键帧曲线，可在曲线编辑器里编辑"""
    bl_idname = "jcns.cm_create"
    bl_label  = "改用关键帧曲线"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj, sp = _cm_source(context)
        return sp is not None and not jcns_cm.has_curve(sp)

    def execute(self, context):
        from .modules_shim import get_mapping
        obj, sp = _cm_source(context)
        m = get_mapping()
        keys = jcns_cm.jcns_complex.from_three_point(
            sp.from_start, sp.from_kink, sp.from_end, sp.to_start, sp.to_kink, sp.to_end,
            two_point=m.is_two_point(sp.update_timing))
        sp.cm_cache.clear()
        jcns_cm.set_keys(sp, keys)
        # Shipped keyframed sources carry all-zero anchors.
        for name in ('from_start', 'from_kink', 'from_end', 'to_start', 'to_kink', 'to_end'):
            setattr(sp, name, 0.0)
        refresh_applied_driver(obj)
        return {'FINISHED'}


class JCNS_OT_CMRemove(Operator):
    """删除当前源的关键帧曲线，改回三点映射（未设置的锚点为 0）"""
    bl_idname = "jcns.cm_remove"
    bl_label  = "改回三点映射"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj, sp = _cm_source(context)
        return sp is not None and jcns_cm.has_curve(sp)

    def execute(self, context):
        obj, sp = _cm_source(context)
        jcns_cm.remove(sp)
        refresh_applied_driver(obj)
        return {'FINISHED'}


class JCNS_OT_CMNormalize(Operator):
    """把当前曲线的每个手柄放回所在段长度的三分之一处，斜率不变。手柄长度不写入文件，不影响游戏"""
    bl_idname = "jcns.cm_normalize"
    bl_label  = "规范手柄"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj, sp = _cm_source(context)
        return sp is not None and jcns_cm.has_curve(sp)

    def execute(self, context):
        obj, sp = _cm_source(context)
        jcns_cm.normalize_handles(sp)
        return {'FINISHED'}


class JCNS_OT_CMEdit(Operator):
    """在曲线编辑器里打开当前源的关键帧曲线"""
    bl_idname = "jcns.cm_edit"
    bl_label  = "在曲线编辑器中编辑"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        sp = _active_source_props(context)
        return sp is not None and jcns_cm.has_curve(sp)

    def execute(self, context):
        from . import get_jcns_constraint
        obj = get_jcns_constraint(context)[0]
        sp = _active_source_props(context)
        target = jcns_cm.fcurve(sp)
        for o in context.selected_objects:
            o.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        fcs = jcns_cm._fcurves(obj, False) or []
        for fc in fcs:
            # RNA hands out a new wrapper per access, so compare paths, not identity
            mine = fc.data_path == target.data_path
            fc.select = mine
            fc.hide = False
            for kp in fc.keyframe_points:     # view_selected frames the selected keys
                kp.select_control_point = mine
        graphs = [a for a in context.screen.areas if a.type == 'GRAPH_EDITOR']
        if not graphs:
            self.report({'INFO'}, "已选中这条曲线；打开一个曲线编辑器（Graph Editor）即可编辑")
            return {'FINISHED'}
        for area in graphs:
            region = next((r for r in area.regions if r.type == 'WINDOW'), None)
            if region is None:
                continue
            area.spaces.active.dopesheet.show_only_selected = True
            with context.temp_override(area=area, region=region):
                bpy.ops.graph.view_selected()
        return {'FINISHED'}


def _active_cone_constraint(context):
    """Constraint props of the active Ranges constraint on a rebuilt root, or None."""
    from . import get_jcns_constraint
    obj, p = get_jcns_constraint(context)
    if obj is None or p.constraint_type != 'Ranges' or _rebuild_root(context)[0] is None:
        return None
    return p


class JCNS_OT_ConeInfoAdd(Operator):
    """给当前约束加一个它读取的锥形（ConeDriverInfo）"""
    bl_idname = "jcns.cone_info_add"
    bl_label  = "新增 ConeDriver 输入"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        p = _active_cone_constraint(context)
        return p is not None and bool(_rebuild_root(context)[1].cone_drivers_json)

    def execute(self, context):
        p = _active_cone_constraint(context)
        k = p.cone_infos.add()
        if len(p.cone_infos) > 1:
            prev = p.cone_infos[len(p.cone_infos) - 2]
            k.cone_index, k.rest = prev.cone_index, tuple(prev.rest)
        p.active_cone_info_index = len(p.cone_infos) - 1
        return {'FINISHED'}


class JCNS_OT_ConeInfoRemove(Operator):
    """删除当前约束里选中的锥形（ConeDriverInfo）"""
    bl_idname = "jcns.cone_info_remove"
    bl_label  = "删除 ConeDriver 输入"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        p = _active_cone_constraint(context)
        return p is not None and len(p.cone_infos) > 0

    def execute(self, context):
        p = _active_cone_constraint(context)
        i = min(p.active_cone_info_index, len(p.cone_infos) - 1)
        p.cone_infos.remove(i)
        p.active_cone_info_index = max(0, i - 1)
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

_classes = [
    JCNS_OT_AddConstraint,
    JCNS_OT_DeleteConstraint,
    JCNS_OT_MoveConstraint,
    JCNS_OT_AddSource,
    JCNS_OT_RemoveSource,
    JCNS_OT_SwapMapToEnds,
    JCNS_OT_SortAnchors,
    JCNS_OT_MirrorConstraints,
    JCNS_OT_AddSectionEntry,
    JCNS_OT_SkinSourceAdd,
    JCNS_OT_SkinSourceRemove,
    JCNS_OT_SkinNormalizeWeights,
    JCNS_OT_CMCreate,
    JCNS_OT_CMRemove,
    JCNS_OT_CMNormalize,
    JCNS_OT_CMEdit,
    JCNS_OT_ConeInfoAdd,
    JCNS_OT_ConeInfoRemove,
]


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)

    if _on_depsgraph_update_fix_duplicates not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_on_depsgraph_update_fix_duplicates)


def unregister():
    if _on_depsgraph_update_fix_duplicates in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_on_depsgraph_update_fix_duplicates)

    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
