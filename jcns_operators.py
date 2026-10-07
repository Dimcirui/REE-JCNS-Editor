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
from .modules_shim import T


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


# TransformElement name -> (Blender data path, driver variables, quantity driven)
_AXIS_NAME = ['X', 'Y', 'Z', 'W']

_DRIVABLE = {
    'Trans':   ('location',        ['LOC_X', 'LOC_Y', 'LOC_Z'],     'Translation'),
    'Rot':     ('rotation_euler',  ['ROT_X', 'ROT_Y', 'ROT_Z'],     'Rotation'),
    'Scale':   ('scale',           ['SCALE_X', 'SCALE_Y', 'SCALE_Z'], 'Scale'),
    # The other rotation types drive the same Euler channels; how they compose is
    # jcns_source_read.TARGET_MODES, so a bone carrying one is previewed as a
    # group (see _needs_group).
    'RotRPY':  ('rotation_euler',  ['ROT_X', 'ROT_Y', 'ROT_Z'],     'Rotation'),
    'RotPYR':  ('rotation_euler',  ['ROT_X', 'ROT_Y', 'ROT_Z'],     'Rotation'),
    'ExpMap':  ('rotation_euler',  ['ROT_X', 'ROT_Y', 'ROT_Z'],     'Rotation'),
    'Rot2':    ('rotation_euler',  ['ROT_X', 'ROT_Y', 'ROT_Z'],     'Rotation'),
    'RotRPY2': ('rotation_euler',  ['ROT_X', 'ROT_Y', 'ROT_Z'],     'Rotation'),
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

# The pose-bone data path a quantity lives on (the key of _SOURCE_VARS).
QUANTITY_PATH = {'Translation': 'location', 'Rotation': 'rotation_euler', 'Scale': 'scale'}


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
            # Curve mode byte (bit 1 = three-point); see modules.jcns_mapping.is_two_point.
            'attr_flags': get_mapping().attr_flags_value(sp),
            # Interpolation byte +28: how each segment runs between its anchors.
            'interp': get_mapping().source_interpolation(sp),
            # +25 InputType, as its byte value: how the source bone is read
            # (modules/jcns_source_read.py).
            'input_type': get_mapping().input_type_value(sp.input_type),
            # +27 RotOrder and the ref_frame reference frame, both only used by
            # rotation reads (modules/jcns_source_read.py).
            'rot_order': get_mapping().rot_order_value(sp.rot_order),
            'frame': (sp.ref_frame_w, sp.ref_frame_x, sp.ref_frame_y, sp.ref_frame_z),
            # ComplexMapping keys, which replace the anchors when present.
            'cm': jcns_cm.keys(sp),
        })
    return out


# A source channel that is not live yet reads its rest value; see channel_sources.
_REST_VALUE = {'Translation': 0.0, 'Rotation': 0.0, 'Scale': 1.0}


def _missing_sources(members, armature_obj):
    """Source bones of a channel's live entry that the armature does not have."""
    if armature_obj is None:
        return []
    return [sp.source_bone for sp in members[-1].jcns_cns_props.sources
            if sp.source_bone and sp.source_bone not in armature_obj.data.bones]


_BONE_HASHES = {}


def _bone_by_hash(armature_obj):
    """{murmur hash: bone name} of an armature, cached on its bone names."""
    names = tuple(b.name for b in armature_obj.data.bones)
    hit = _BONE_HASHES.get(armature_obj.name)
    if hit is None or hit[0] != names:
        from .jcns_exporter import _name_to_hash
        hit = (names, {_name_to_hash(n): n for n in names})
        _BONE_HASHES[armature_obj.name] = hit
    return hit[1]


def _armature_bone(armature_obj, name):
    """The armature bone a table name means: the name itself, or a "0x%08X" hash /
    a name the armature spells differently, matched by hash.  None if absent."""
    if armature_obj is None or not name:
        return None
    if name in armature_obj.data.bones:
        return name
    from .jcns_exporter import _name_to_hash
    return _bone_by_hash(armature_obj).get(_name_to_hash(name))


def _cone_plan(members, armature_obj):
    """[(ConeDriver props, joint bone, ConeInput props, self_parent)] for the live
    entry's ConeDrivers, and the reason when one of them cannot be previewed.

    Index 255 is no cone and is left out.  The cone needs its joint in the armature
    and its ParentJoint to be the joint's parent there (or the joint itself)."""
    from . import get_jcns_root_from_constraint
    owner = members[-1]
    cds = [k for k in owner.jcns_cns_props.cone_drivers if k.cone_input_index != 255]
    if not cds:
        return [], None
    _, rp = get_jcns_root_from_constraint(owner)
    table = rp.cone_inputs if rp is not None else []
    plan = []
    for k in cds:
        if k.cone_input_index >= len(table):
            return plan, T("ops.driver.cone_unresolved", k.cone_input_index)
        if k.curve_type != 0:
            return plan, T("ops.driver.cone_curve")
        ci = table[k.cone_input_index]
        joint = _armature_bone(armature_obj, ci.joint.strip())
        parent = _armature_bone(armature_obj, ci.parent_joint.strip())
        if joint is None or parent is None:
            return plan, T("ops.driver.cone_unresolved", k.cone_input_index)
        bone = armature_obj.data.bones[joint]
        if parent != joint and (bone.parent is None or bone.parent.name != parent):
            return plan, T("ops.driver.cone_parent", ci.name, joint, parent)
        plan.append((k, joint, ci, parent == joint))
    return plan, None


def _previewable(members, armature_obj=None):
    """The live entry of a channel reads source bones the armature has, and cones it
    can resolve.  A missing source bone would feed the driver nothing; an entry with
    neither sources nor cones has nothing to preview."""
    p = members[-1].jcns_cns_props
    plan, why = _cone_plan(members, armature_obj)
    if why is not None:
        return False
    if not plan and not any(sp.source_bone for sp in p.sources):
        return False
    return not _missing_sources(members, armature_obj)


def _no_driver_reason(members, armature_obj=None):
    missing = _missing_sources(members, armature_obj)
    if missing:
        return T("ops.driver.source_missing", T("ui.sep.list").join(missing))
    _plan, why = _cone_plan(members, armature_obj)
    if why is not None:
        return why
    return T("ops.driver.none")


def _armature_of(root_obj):
    rp = getattr(root_obj, 'jcns_root_props', None)
    return rp.target_armature if rp is not None else None


# The preview drives rotation_euler, so it switches the bone to XYZ; the mode it
# had is kept here and put back when the bone's last rotation driver goes.
_PREV_ROT_MODE = 'jcns_prev_rotation_mode'


def _use_euler(pose_bone):
    if pose_bone.rotation_mode != 'XYZ':
        if _PREV_ROT_MODE not in pose_bone:
            pose_bone[_PREV_ROT_MODE] = pose_bone.rotation_mode
        pose_bone.rotation_mode = 'XYZ'


def _restore_rotation(armature_obj, pose_bone, axes):
    """Zero the cleared Euler axes (removing a driver leaves its last value) and,
    once no rotation driver is left on the bone, restore its rotation mode."""
    for a in axes:
        pose_bone.rotation_euler[a] = 0.0
    ad = armature_obj.animation_data
    path = 'pose.bones["%s"].rotation_euler' % pose_bone.name
    if ad is not None and any(fc.data_path == path for fc in ad.drivers):
        return
    mode = pose_bone.get(_PREV_ROT_MODE)
    if mode is not None:
        pose_bone.rotation_mode = mode
        del pose_bone[_PREV_ROT_MODE]


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
    return sr.rest_input(sp.input_type, axis, rest, tuple(v / per_cm for v in off),
                         order=sr.rot_order_value(sp.rot_order),
                         frame=(sp.ref_frame_w, sp.ref_frame_x, sp.ref_frame_y, sp.ref_frame_z),
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
        sid = s.get('input_type')
        q = mp.source_quantity(sid)
        path = QUANTITY_PATH[q]
        axis = min(s.get('axis_idx', 0), 2)
        live = tuple(a for a in range(3) if (s['bone'], path, a) not in later)
        mode = jcns_drivers.jcns_source_read.ROTATION_MODES.get(sid)
        if q == 'Rotation' and mode:
            rest, _off = _rest_transform(armature_obj, s['bone'])
            s['read'] = ('rot', mode, axis, rest, s['rot_order'], s['frame'], live)
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
    plan, why = _cone_plan([owner], armature_obj)
    if why is None:
        for k, joint, ci, self_parent in plan:
            rest, _off = _rest_transform(armature_obj, joint)
            live = () if self_parent else tuple(
                a for a in range(3) if (joint, 'rotation_euler', a) not in later)
            m = tuple(ci.matrix)
            sources.append({
                'bone': joint, 'axis_idx': 0, 'axis_name': 'X',
                'cone': {'out_min': k.out_min, 'out_max': k.out_max, 'interp': k.interpolation},
                'read': ('cone', rest, tuple(ci.direction), (m[0:3], m[4:7], m[8:11]),
                         ci.angle, ci.base_pose, self_parent, live)})
    return sources


def _apply_driver(armature_obj, target_bone_name, target_axis_idx,
                  sources, transform_element='Rot'):
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
        return False, T("ops.driver.no_driven_bone", target_bone_name)

    entry = _DRIVABLE.get(transform_element)
    if entry is None:
        return False, T("ops.driver.no_channel", transform_element)
    data_path, _, target_q = entry

    usable = [s for s in sources if s.get('bone')]
    if not usable:
        return False, T("ops.driver.not_set")

    # The engine composes q = rest * Rz * Ry * Rx whatever order the file writes the
    # axes in, which is Blender's XYZ Euler mode.
    if data_path == 'rotation_euler':
        _use_euler(pose_bone)

    # In the driver's own units, so the namespace function converts nothing.
    maps = [jcns_drivers.source_map(s, target_q) for s in usable]
    reads = [jcns_drivers.source_read(s) for s in usable]

    key = jcns_drivers.channel_id(armature_obj.name, target_bone_name,
                                  transform_element, _AXIS_NAME[target_axis_idx])
    jcns_drivers.register_channel(key, maps, reads, post=target_post_factor(
        armature_obj, target_bone_name, transform_element, target_axis_idx))

    expr = _install_driver(armature_obj, target_bone_name, data_path, target_axis_idx,
                           key, usable, reads)
    if len(expr) > 255:
        return False, ("channel key too long (%d chars) — rename the bone or "
                       "armature" % len(expr))

    print("[JCNS DRIVER] [%s] %d source(s) %s -> %s[%d]  expr=%s" % (
        transform_element, len(usable), ", ".join(s['bone'] for s in usable),
        target_bone_name, target_axis_idx, expr))
    return True, ""


def _install_driver(armature_obj, bone_name, data_path, index, key, sources, reads):
    """Create the jcns_ch driver on one pose-bone channel, with the variables the
    sources' reads ask for, in order.  -> the expression (callers check its length)."""
    from .modules_shim import get_mapping
    from .jcns_drivers import ensure_namespace
    ensure_namespace()
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
        if read[0] in ('rot', 'cone'):
            for a in read[-1]:
                add_var(s['bone'], _ROT_TYPE[a], 'XYZ')
            continue
        if read[0] == 'loc':
            for a in read[-1]:
                add_var(s['bone'], _LOC_TYPE[a])
            continue
        add_var(s['bone'], _SOURCE_VARS[get_mapping().source_quantity(
            s.get('input_type'))][min(s.get('axis_idx', 0), 2)])

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
            if b == bone and transform == 'Trans' and axis != 'W'
            and _previewable(members, _armature_of(root_obj))}


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
    parent = armature_obj.data.bones[bone].parent
    parent_scale = mesh_rest_scale(parent) if parent is not None else (1.0, 1.0, 1.0)
    jcns_drivers.register_group(gid, rest, parts, keys, offset=offset, parent_scale=parent_scale)
    return keys, all_sources, all_reads


def _apply_translation_bone(armature_obj, root_obj, bone, chans):
    if armature_obj.pose.bones.get(bone) is None:
        return False, T("ops.driver.no_driven_bone", bone)
    made = register_translation_group(armature_obj, root_obj, bone, chans)
    if made is None:
        return False, T("ops.driver.none_or_w")
    keys, sources, reads = made
    for a, key in enumerate(keys):
        expr = _install_driver(armature_obj, bone, 'location', a, key, sources, reads)
        if len(expr) > 255:
            _drop_group_drivers(armature_obj, bone, 'location', _LOCATION_GROUP_TAG)
            return False, T("ops.driver.too_long")
    for members in chans.values():
        for e in members:
            e.jcns_cns_props.preview_on = True
    return True, ""


def _replaces(members):
    """The live (last) entry of a channel writes with AttrFlags bit0 = 0."""
    return not members[-1].jcns_cns_props.base_pose


def _target_mode(members):
    """How the live entry of a channel composes its bone's rotation
    (jcns_source_read.TARGET_MODES), from its TransformElement."""
    from . import jcns_drivers
    from .jcns_exporter import _transform_int
    tt = _transform_int(members[-1].jcns_cns_props.transform_element)
    return jcns_drivers.jcns_source_read.TARGET_MODES.get(tt, 'euler')


def _rotation_channels(root_obj, bone):
    """{axis: members} for every previewable rotation_euler channel of `bone`.
    When two rotation types write one axis, the one whose live entry is later in
    the file is kept; a cone-only winner drops the axis."""
    from . import AXIS_TO_INT, get_constraint_empties, group_constraints_by_channel
    order = {e.name: i for i, e in enumerate(get_constraint_empties(root_obj))}
    out = {}
    for (b, transform, axis), members in group_constraints_by_channel(root_obj).items():
        entry = _DRIVABLE.get(transform)
        if b == bone and axis != 'W' and entry is not None and entry[0] == 'rotation_euler':
            a = AXIS_TO_INT.get(axis, 0)
            if a not in out or order.get(members[-1].name, -1) > order.get(out[a][-1].name, -1):
                out[a] = members
    arm = _armature_of(root_obj)
    return {a: m for a, m in out.items() if _previewable(m, arm)}


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


def _rot2_groups(empties):
    """{entry name: (group start, RotOrder)} for the Rot2 (13) entries: the joint
    group each sits in (+77 counts) and that group's TailBytes[0], which the engine
    uses as the Euler order of the whole group."""
    from .jcns_exporter import _transform_int
    out = {}
    i = 0
    while i < len(empties):
        head = empties[i].jcns_cns_props
        k = max(0, head.group_count)
        for e in empties[i:i + k + 1]:
            if _transform_int(e.jcns_cns_props.transform_element) == 13:
                out[e.name] = (i, head.unknown_byte_74)
        i += k + 1
    return out


def register_bone_group(armature_obj, root_obj, bone, chans):
    """Put one bone's rotation group in the channel table.  -> (keys, sources,
    reads) for the drivers, or None when a channel cannot be previewed."""
    from . import jcns_drivers, get_constraint_empties
    empties = get_constraint_empties(root_obj)
    order = {e.name: i for i, e in enumerate(empties)}
    rot2 = _rot2_groups(empties)
    parts, all_sources, all_reads = [], [], []
    # File order of the live entries: for a single-axis type the last one wins.
    for axis in sorted(chans, key=lambda a: order.get(chans[a][-1].name, -1)):
        members = chans[axis]
        sources = channel_sources(armature_obj, root_obj, members[-1])
        if any(s['axis_name'] == 'W' for s in sources):
            return None
        reads = [jcns_drivers.source_read(s) for s in sources]
        parts.append((axis, _target_mode(members), _replaces(members),
                      [jcns_drivers.source_map(s, 'Rotation') for s in sources], reads,
                      rot2.get(members[-1].name)))
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
        return False, T("ops.driver.no_driven_bone", bone)
    made = register_bone_group(armature_obj, root_obj, bone, chans)
    if made is None:
        return False, T("ops.driver.w_unsupported")
    keys, sources, reads = made
    _use_euler(pose_bone)
    for a, key in enumerate(keys):
        expr = _install_driver(armature_obj, bone, 'rotation_euler', a, key, sources, reads)
        if len(expr) > 255:
            _drop_group_drivers(armature_obj, bone)
            return False, T("ops.driver.too_long_n", len(expr))
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
    if p is None or not p.is_jcns_constraint or p.constraint_type != 'Outputs':
        return False
    if not p.preview_on:
        return False
    root_obj, rp = get_jcns_root_from_constraint(obj)
    if root_obj is None or rp is None or rp.target_armature is None:
        return False
    members = group_constraints_by_channel(root_obj).get(channel_key(p))
    if not members:
        return False

    entry = _DRIVABLE.get(p.transform_element)
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
                                  p.transform_element, p.target_axis)
    reads = [jcns_drivers.source_read(s) for s in sources]
    if reads != jcns_drivers.channel_reads(key):
        # The driver's variables no longer fit (a source's bone, axis or +25, or
        # its place in the file, changed): rebuild it rather than patch numbers.
        ok, _err, _label = _apply_channel(rp.target_armature, rp, members)
        return ok
    from . import AXIS_TO_INT
    jcns_drivers.register_channel(
        key, [jcns_drivers.source_map(s, target_q) for s in sources], reads,
        post=target_post_factor(rp.target_armature, p.target_bone, p.transform_element,
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
    if rp is not None and (rp.source_filepath or rp.source_version):
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
    if p is None or not p.is_jcns_constraint or p.constraint_type != 'Outputs':
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

    if not _previewable(members, armature_obj):
        return False, _no_driver_reason(members, armature_obj), "%s(%s)" % (bone or '???', axis)

    entry = _DRIVABLE.get(transform)
    if entry is not None and entry[0] == 'location' and bone and root_obj is not None:
        if axis == 'W':
            return False, T("ops.driver.w_unsupported"), bone
        chans = translation_channels(root_obj, bone)
        ok, err = _apply_translation_bone(armature_obj, root_obj, bone, chans)
        return ok, err, T("ops.driver.label_loc_group", bone, len(chans))
    if entry is not None and entry[0] == 'rotation_euler' and bone and root_obj is not None:
        chans = _rotation_channels(root_obj, bone)
        if _needs_group(armature_obj, bone, chans):
            ok, err = _apply_bone(armature_obj, root_obj, bone, chans)
            label = T("ops.driver.label_rot_group", bone, len(chans))
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
        label += T("ops.driver.label_last_wins", len(members))

    if not sources:
        return False, _no_driver_reason(members, armature_obj), label
    if axis == 'W' or any(s['axis_name'] == 'W' for s in sources):
        return False, T("ops.driver.w_unsupported"), label
    if not bone:
        return False, T("ops.driver.driven_unresolved"), label

    ok, err = _apply_driver(
        armature_obj, bone, AXIS_TO_INT.get(axis, 0), sources,
        transform_element=transform,
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
        _restore_rotation(armature_obj, pose_bone, range(3))
        root_obj, _ = get_jcns_root_from_constraint(members[0])
        if root_obj is not None:
            for other in _rotation_channels(root_obj, bone).values():
                for e in other:
                    e.jcns_cns_props.preview_on = False
    if entry is not None and pose_bone is not None:
        a = AXIS_TO_INT.get(axis, 0)
        try:
            pose_bone.driver_remove(entry[0], a)
        except Exception:
            pass
        # Removing a driver leaves its last value on the channel; put the rest back.
        if axis != 'W':
            if entry[0] == 'scale':
                pose_bone.scale[a] = 1.0    # the rest scale, in Blender
            elif entry[0] == 'location':
                pose_bone.location[a] = 0.0
            elif entry[0] == 'rotation_euler':
                _restore_rotation(armature_obj, pose_bone, (a,))
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

def new_constraint_empty(root_obj):
    """A blank Ranges entry at the end of the file: one source, named '[NN] ...'.
    -> the Empty, or None when the root is in no collection."""
    from . import get_constraint_empties, make_constraint_empty_name

    coll = next(iter(root_obj.users_collection), None)
    if coll is None:
        return None

    name = make_constraint_empty_name(len(get_constraint_empties(root_obj)), 'BoneName', '', 'X')
    obj = bpy.data.objects.new(name, None)
    obj.empty_display_type = 'ARROWS'
    obj.empty_display_size = 0.05
    obj.parent = root_obj
    coll.objects.link(obj)

    p = obj.jcns_cns_props
    p.is_jcns_constraint = True
    p.constraint_type = 'Outputs'
    p.target_bone = ''
    p.transform_element = 'Rot'
    sp = p.sources.add()          # every new constraint starts with one source
    sp.source_bone = 'BoneName'
    return obj


class JCNS_OT_AddConstraint(Operator):
    bl_idname = "jcns.add_constraint"
    bl_label  = T("ops.label.add_constraint")
    bl_description = T("ops.desc.add_constraint")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        from . import get_export_root
        obj, rp = get_export_root(context)
        return obj is not None and _caps_for(rp, 'Outputs').can_add

    def execute(self, context):
        from . import get_export_root

        root_obj, root_props = get_export_root(context)
        obj = new_constraint_empty(root_obj)
        if obj is None:
            self.report({'ERROR'}, T("ops.err.root_no_collection"))
            return {'CANCELLED'}

        context.view_layer.objects.active = obj
        obj.select_set(True)
        self.report({'INFO'}, T("ops.add_constraint.added", obj.name))
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Operator: Delete Constraint
# ---------------------------------------------------------------------------

class JCNS_OT_DeleteConstraint(Operator):
    bl_idname = "jcns.delete_constraint"
    bl_label  = T("ops.label.delete_constraint")
    bl_description = T("ops.desc.delete_constraint")
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
            if kind in ('Multi', 'Aim', 'RotExpression'):
                _renumber_sections(root_obj, kind)
            else:
                _renumber_in_order(get_constraint_empties(root_obj))

        self.report({'INFO'}, T("ops.delete_constraint.done"))
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
    bl_idname = "jcns.move_constraint"
    bl_label  = T("ops.label.move_constraint")
    bl_description = T("ops.desc.move_constraint")
    bl_options = {'REGISTER', 'UNDO'}

    direction: EnumProperty(
        name=T("ops.move.direction"),
        items=[('UP', T("ops.move.up"), T("ops.move.up_desc")),
               ('DOWN', T("ops.move.down"), T("ops.move.down_desc"))],
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
            self.report({'ERROR'}, T("ops.err.no_root"))
            return {'CANCELLED'}

        ordered = get_constraint_empties(root_obj)
        try:
            pos = ordered.index(cns_obj)
        except ValueError:
            # Aim / RotExpression / Material Empties are not part of the ordered
            # constraint list, so there is nothing to move them within.
            self.report({'ERROR'}, T("ops.move.not_ordered"))
            return {'CANCELLED'}

        new_pos = pos - 1 if self.direction == 'UP' else pos + 1
        if not (0 <= new_pos < len(ordered)):
            self.report({'INFO'}, T("ops.move.at_top") if self.direction == 'UP' else T("ops.move.at_bottom"))
            return {'CANCELLED'}

        ordered[pos], ordered[new_pos] = ordered[new_pos], ordered[pos]
        _renumber_in_order(ordered)

        self.report({'INFO'}, T("ops.move.done", new_pos + 1, len(ordered)))
        return {'FINISHED'}


class JCNS_OT_AddSource(Operator):
    bl_idname = "jcns.add_source"
    bl_label  = T("ops.label.add_source")
    bl_description = T("ops.desc.add_source")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        from . import get_jcns_constraint
        obj, props = get_jcns_constraint(context)
        return obj is not None and props.constraint_type == 'Outputs'

    def execute(self, context):
        from . import get_jcns_constraint, constraint_name_from_props
        cns_obj, p = get_jcns_constraint(context)
        sp = p.sources.add()
        # Seed from the previous source so the new one is a usable starting point
        if len(p.sources) > 1:
            prev = p.sources[len(p.sources) - 2]
            for attr in ('source_axis', 'from_start', 'from_kink', 'from_end',
                         'to_start', 'to_kink', 'to_end', 'mid_point', 'attr_flags_other', 'interpolation',
                         'input_type', 'ref_frame_w'):
                setattr(sp, attr, getattr(prev, attr))
        p.active_source_index = len(p.sources) - 1
        idx = 0
        if cns_obj.name.startswith('['):
            try:
                idx = int(cns_obj.name[1:cns_obj.name.index(']')])
            except (ValueError, IndexError):
                pass
        cns_obj.name = constraint_name_from_props(idx, p)
        self.report({'INFO'}, T("ops.add_source.done", len(p.sources)))
        return {'FINISHED'}


class JCNS_OT_RemoveSource(Operator):
    bl_idname = "jcns.remove_source"
    bl_label  = T("ops.label.remove_source")
    bl_description = T("ops.desc.remove_source")
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
        self.report({'INFO'}, T("ops.remove_source.done", len(p.sources)))
        return {'FINISHED'}



class JCNS_OT_SwapMapToEnds(Operator):
    bl_idname = "jcns.swap_mapto_ends"
    bl_label  = T("ops.label.swap_mapto_ends")
    bl_description = T("ops.desc.swap_mapto_ends")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        from . import get_jcns_constraint
        obj, props = get_jcns_constraint(context)
        return (obj is not None and props.constraint_type == 'Outputs'
                and len(props.sources) > 0)

    def execute(self, context):
        from . import get_jcns_constraint
        from .modules_shim import get_mapping
        _, p = get_jcns_constraint(context)
        sp = p.sources[min(p.active_source_index, len(p.sources) - 1)]
        before = get_mapping().describe(sp)['at_rest']
        sp.to_start, sp.to_end = sp.to_end, sp.to_start
        after = get_mapping().describe(sp)['at_rest']
        self.report({'INFO'}, T("ops.swap_mapto_ends.done", before, after))
        return {'FINISHED'}



class JCNS_OT_MirrorConstraints(Operator):
    bl_idname = "jcns.mirror_constraints"
    bl_label  = T("ops.label.mirror_constraints")
    bl_description = T("ops.desc.mirror_constraints")
    bl_options = {'REGISTER', 'UNDO'}

    mirror_target: BoolProperty(
        name=T("ops.mirror.target"), default=True,
        description=T("ops.mirror.target_desc"))
    mirror_source: BoolProperty(
        name=T("ops.mirror.source"), default=True,
        description=T("ops.mirror.source_desc"))
    overwrite: BoolProperty(
        name=T("ops.mirror.overwrite"), default=False,
        description=T("ops.mirror.overwrite_desc"))
    use_frames: BoolProperty(
        name=T("ops.mirror.use_frames"), default=True,
        description=T("ops.mirror.use_frames_desc"))

    @classmethod
    def poll(cls, context):
        from . import get_jcns_constraint
        obj, props = get_jcns_constraint(context)
        return obj is not None and props.constraint_type == 'Outputs'

    def draw(self, context):
        layout = self.layout
        row = layout.row(align=True)
        row.prop(self, "mirror_target")
        row.prop(self, "mirror_source")
        layout.prop(self, "use_frames")
        layout.prop(self, "overwrite")
        if not (self.mirror_target or self.mirror_source):
            layout.label(text=T("ops.mirror.need_one"), icon='ERROR')

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        from . import (get_jcns_constraint, get_jcns_root_from_constraint,
                       get_constraint_empties, constraint_name_from_props, flags_byte)
        from .modules_shim import get_mirror

        if not self.mirror_target and not self.mirror_source:
            self.report({'ERROR'}, T("ops.mirror.need_one_report"))
            return {'CANCELLED'}

        active, _ = get_jcns_constraint(context)
        root_obj, root_props = get_jcns_root_from_constraint(active)
        if root_obj is None:
            self.report({'ERROR'}, T("ops.err.no_root"))
            return {'CANCELLED'}

        # Work on the selection so several can be done at once, but the active
        # constraint is always included — that is what the panel button implies.
        targets = [o for o in context.selected_objects
                   if getattr(o, 'jcns_cns_props', None)
                   and o.jcns_cns_props.is_jcns_constraint
                   and o.jcns_cns_props.constraint_type == 'Outputs']
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
                p.target_bone, p.transform_element, p.target_axis,
                [(s.source_bone, s.source_axis) for s in p.sources]), e)

        coll = next(iter(root_obj.users_collection), None)
        made = updated = kept = 0
        problems = []

        for e in targets:
            p = e.jcns_cns_props

            if self.mirror_target:
                new_tgt = partner(p.target_bone)
                if new_tgt is None:
                    problems.append(T("ops.mirror.no_counterpart", (p.target_bone or "?")))
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
                        failed = T("ops.mirror.no_counterpart", sp.source_bone)
                        break
                    src_sigma = sigma(sp.source_bone)
                else:
                    # Source is fixed, as for the target above.
                    mate = sp.source_bone
                    src_sigma = None
                vals, i_s, o_s = mirror.mirror_source(
                    sp, sp.source_axis, p.target_axis, flags_byte(p),
                    src_sigma, tgt_sigma, p.transform_element,
                    mirror_in=self.mirror_source, mirror_out=self.mirror_target)
                if vals is None:
                    failed = T("ops.mirror.no_sign", sp.source_bone, sp.source_axis)
                    break
                if self.mirror_source:
                    # The reference frame is a rotation in the source's local axes, so
                    # it reflects like any rotation: its vector part flips by sigma.
                    sg = src_sigma or mirror.SIGMA_DEFAULT
                    comps = (sp.ref_frame_x, sp.ref_frame_y, sp.ref_frame_z)
                    if any(abs(c) > 1e-9 and sg.get(a) is None for c, a in zip(comps, 'XYZ')):
                        failed = T("ops.mirror.no_frame", sp.source_bone)
                        break
                    vals['_frame'] = tuple(c * (sg.get(a) or 1) for c, a in zip(comps, 'XYZ'))
                new_sources.append((mate, sp.source_axis, vals, sp, i_s, o_s))
            if failed:
                problems.append(failed)
                continue

            sig = mirror.constraint_signature(
                new_tgt, p.transform_element, p.target_axis,
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
            q.constraint_type = 'Outputs'
            q.target_bone = new_tgt
            q.target_axis = p.target_axis
            q.transform_element = p.transform_element
            q.base_pose, q.attr_flags_other = p.base_pose, p.attr_flags_other
            q.target_property, q.property_hash = p.target_property, p.property_hash
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
                for attr in ('ref_frame_x', 'ref_frame_y', 'ref_frame_z',
                             'ref_frame_w', 'mid_point', 'attr_flags_other', 'input_type',
                             'rot_order', 'unknown_uint16_22', 'interpolation', 'curve_type'):
                    setattr(ns, attr, getattr(orig, attr))
                if '_frame' in vals:
                    ns.ref_frame_x, ns.ref_frame_y, ns.ref_frame_z = vals['_frame']
                if jcns_cm.has_curve(orig):
                    jcns_cm.copy_keys(orig, ns, lambda k, i_s=i_s, o_s=o_s:
                                      jcns_cm.jcns_complex.mirrored(k, i_s, o_s))

        for i, empty in enumerate(get_constraint_empties(root_obj)):
            empty.name = constraint_name_from_props(i, empty.jcns_cns_props)

        parts = []
        if made:
            parts.append(T("ops.mirror.part_new", made))
        if updated:
            parts.append(T("ops.mirror.part_updated", updated))
        if kept:
            parts.append(T("ops.mirror.part_kept", kept))
        msg = T("ops.mirror.done", T("ops.mirror.sep").join(parts) if parts else T("ops.mirror.no_change"))
        if problems:
            msg = T("ops.mirror.with_problems", msg, T("ops.mirror.sep").join(problems[:2]))
            self.report({'WARNING'}, msg)
        else:
            self.report({'INFO'}, msg)
        return {'FINISHED'}



class JCNS_OT_SortAnchors(Operator):
    bl_idname = "jcns.sort_anchors"
    bl_label  = T("ops.label.sort_anchors")
    bl_description = T("ops.desc.sort_anchors")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        from . import get_jcns_constraint
        obj, props = get_jcns_constraint(context)
        return (obj is not None and props.constraint_type == 'Outputs'
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
        self.report({'INFO'}, T("ops.sort_anchors.done_all") if d['unreachable_anchor'] is None
                    else T("ops.sort_anchors.done_unreachable", d['unreachable_anchor']))
        return {'FINISHED'}



# ---------------------------------------------------------------------------
# Operators: non-range sections (MultiConstraint / Aim / RotExpression)
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
    from .jcns_exporter import root_write_mode
    return (root, rp) if root_write_mode(rp) == 'rebuild' else (None, None)


class JCNS_OT_AddSectionEntry(Operator):
    bl_idname = "jcns.add_section_entry"
    bl_label  = T("ops.label.add_section_entry")
    bl_description = T("ops.desc.add_section_entry")
    bl_options = {'REGISTER', 'UNDO'}

    kind: EnumProperty(items=[('Multi', "MultiConstraint", ""), ('Aim', "Aim", ""),
                              ('RotExpression', "RotExpression", ""), ('Material', "Material", "")])

    @classmethod
    def poll(cls, context):
        return _rebuild_root(context)[0] is not None

    def execute(self, context):
        from . import section_empties, section_empty_name
        root, rp = _rebuild_root(context)
        coll = next(iter(root.users_collection), None)
        if coll is None:
            self.report({'ERROR'}, T("ops.err.root_no_collection"))
            return {'CANCELLED'}
        caps = _caps_for(rp, self.kind)
        if not caps.can_add:
            self.report({'ERROR'}, caps.reason('add') or T("ops.section.cannot_add"))
            return {'CANCELLED'}
        idx = len(section_empties(root, self.kind))
        display = {'Multi': 'SINGLE_ARROW', 'Aim': 'SPHERE', 'RotExpression': 'CIRCLE',
                   'Material': 'CUBE'}[self.kind]
        obj = bpy.data.objects.new("__jcns_new_section", None)
        obj.empty_display_type = display
        obj.empty_display_size = 0.03
        obj.parent = root
        coll.objects.link(obj)
        p = obj.jcns_cns_props
        p.is_jcns_constraint = True
        p.constraint_type = self.kind
        if self.kind == 'Multi':
            w = p.multi_sources.add()
            w.weight = 1.0
            from .modules_shim import ensure_path
            ensure_path()
            import jcns_sections
            p.multi_tail = tuple(jcns_sections.multi_default_tail(
                [{'tail': tuple(o.jcns_cns_props.multi_tail)} for o in section_empties(root, 'Multi') if o is not obj]))
        elif self.kind == 'Material':
            p.mat_tail_1 = 1                     # 00 01 00, what most shipped records carry
        obj.name = section_empty_name(self.kind, idx, p)
        for o in context.selected_objects:
            o.select_set(False)
        context.view_layer.objects.active = obj
        obj.select_set(True)
        self.report({'INFO'}, T("ops.section.added", obj.name))
        return {'FINISHED'}


class JCNS_OT_MdfRefAdd(Operator):
    bl_idname = "jcns.mdf_ref_add"
    bl_label  = T("ops.label.mdf_ref_add")
    bl_description = T("ops.desc.mdf_ref_add")
    bl_options = {'REGISTER', 'UNDO'}

    filepath: StringProperty(subtype='FILE_PATH')
    filter_glob: StringProperty(default="*.mdf2.*", options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        from . import get_export_root
        return get_export_root(context)[0] is not None

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        from . import get_export_root, refresh_mdf_catalog, resolve_material_names
        root, rp = get_export_root(context)
        ref = rp.mdf_refs.add()
        ref.filepath = self.filepath            # its update reads the file and resolves names
        rp.mdf_ref_index = len(rp.mdf_refs) - 1
        if ref.status:
            self.report({'WARNING'}, T("ops.mdf.unreadable", ref.status))
            return {'FINISHED'}
        self.report({'INFO'}, T("ops.mdf.added", ref.material_count))
        return {'FINISHED'}


class JCNS_OT_MdfRefRemove(Operator):
    bl_idname = "jcns.mdf_ref_remove"
    bl_label  = T("ops.label.mdf_ref_remove")
    bl_description = T("ops.desc.mdf_ref_remove")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        from . import get_export_root
        _root, rp = get_export_root(context)
        return rp is not None and len(rp.mdf_refs) > 0

    def execute(self, context):
        from . import get_export_root, refresh_mdf_catalog
        _root, rp = get_export_root(context)
        i = min(rp.mdf_ref_index, len(rp.mdf_refs) - 1)
        rp.mdf_refs.remove(i)
        rp.mdf_ref_index = max(0, i - 1)
        refresh_mdf_catalog(rp)                 # names already filled in stay
        return {'FINISHED'}


def _active_section(context, kind):
    from . import get_jcns_constraint
    obj, p = get_jcns_constraint(context)
    if obj is None or p.constraint_type != kind:
        return None, None
    return obj, p


class JCNS_OT_MultiSourceAdd(Operator):
    bl_idname = "jcns.multi_source_add"
    bl_label  = T("ops.label.add_source")
    bl_description = T("ops.desc.multi_source_add")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _active_section(context, 'Multi')[0] is not None

    def execute(self, context):
        _, p = _active_section(context, 'Multi')
        w = p.multi_sources.add()
        w.weight = 0.0
        p.active_multi_source_index = len(p.multi_sources) - 1
        return {'FINISHED'}


class JCNS_OT_MultiSourceRemove(Operator):
    bl_idname = "jcns.multi_source_remove"
    bl_label  = T("ops.label.remove_source")
    bl_description = T("ops.desc.multi_source_remove")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj, p = _active_section(context, 'Multi')
        return obj is not None and len(p.multi_sources) > 0

    def execute(self, context):
        _, p = _active_section(context, 'Multi')
        i = min(p.active_multi_source_index, len(p.multi_sources) - 1)
        p.multi_sources.remove(i)
        p.active_multi_source_index = max(0, i - 1)
        return {'FINISHED'}


class JCNS_OT_MultiNormalizeWeights(Operator):
    bl_idname = "jcns.multi_normalize_weights"
    bl_label  = T("ops.label.multi_normalize_weights")
    bl_description = T("ops.desc.multi_normalize_weights")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj, p = _active_section(context, 'Multi')
        return obj is not None and sum(w.weight for w in p.multi_sources) > 0

    def execute(self, context):
        _, p = _active_section(context, 'Multi')
        total = sum(w.weight for w in p.multi_sources)
        for w in p.multi_sources:
            w.weight /= total
        return {'FINISHED'}


def _active_source_props(context):
    from . import get_jcns_constraint
    obj, p = get_jcns_constraint(context)
    if obj is None or p.constraint_type not in ('Outputs', '') or not len(p.sources):
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
    bl_idname = "jcns.cm_create"
    bl_label  = T("ops.label.cm_create")
    bl_description = T("ops.desc.cm_create")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj, sp = _cm_source(context)
        return sp is not None and not jcns_cm.has_curve(sp)

    def execute(self, context):
        from .modules_shim import get_mapping
        obj, sp = _cm_source(context)
        m = get_mapping()
        keys = jcns_cm.jcns_complex.from_mid_point(
            sp.from_start, sp.from_kink, sp.from_end, sp.to_start, sp.to_kink, sp.to_end,
            two_point=m.is_two_point(m.attr_flags_value(sp)), interp=m.source_interpolation(sp))
        sp.cm_cache.clear()
        jcns_cm.set_keys(sp, keys)
        # Shipped keyframed sources carry all-zero anchors.
        for name in ('from_start', 'from_kink', 'from_end', 'to_start', 'to_kink', 'to_end'):
            setattr(sp, name, 0.0)
        refresh_applied_driver(obj)
        return {'FINISHED'}


class JCNS_OT_CMRemove(Operator):
    bl_idname = "jcns.cm_remove"
    bl_label  = T("ops.label.cm_remove")
    bl_description = T("ops.desc.cm_remove")
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
    bl_idname = "jcns.cm_normalize"
    bl_label  = T("ops.label.cm_normalize")
    bl_description = T("ops.desc.cm_normalize")
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
    bl_idname = "jcns.cm_edit"
    bl_label  = T("ops.label.cm_edit")
    bl_description = T("ops.desc.cm_edit")
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
            self.report({'INFO'}, T("ops.cm_edit.selected"))
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
    if obj is None or p.constraint_type != 'Outputs' or _rebuild_root(context)[0] is None:
        return None
    return p


class JCNS_OT_ConeDriverAdd(Operator):
    bl_idname = "jcns.cone_driver_add"
    bl_label  = T("ops.label.cone_driver_add")
    bl_description = T("ops.desc.cone_driver_add")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        p = _active_cone_constraint(context)
        return p is not None and len(_rebuild_root(context)[1].cone_inputs) > 0

    def execute(self, context):
        p = _active_cone_constraint(context)
        k = p.cone_drivers.add()
        if len(p.cone_drivers) > 1:
            prev = p.cone_drivers[len(p.cone_drivers) - 2]
            k.cone_input_index, k.out_min, k.out_max = prev.cone_input_index, prev.out_min, prev.out_max
            k.interpolation, k.curve_type = prev.interpolation, prev.curve_type
        p.active_cone_driver_index = len(p.cone_drivers) - 1
        return {'FINISHED'}


class JCNS_OT_ConeDriverRemove(Operator):
    bl_idname = "jcns.cone_driver_remove"
    bl_label  = T("ops.label.cone_driver_remove")
    bl_description = T("ops.desc.cone_driver_remove")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        p = _active_cone_constraint(context)
        return p is not None and len(p.cone_drivers) > 0

    def execute(self, context):
        p = _active_cone_constraint(context)
        i = min(p.active_cone_driver_index, len(p.cone_drivers) - 1)
        p.cone_drivers.remove(i)
        p.active_cone_driver_index = max(0, i - 1)
        return {'FINISHED'}


_CONE_MATRICES = {
    'IDENTITY': (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0),
    'MIRROR':   (1.0, 0.0, 0.0, 0.0, 0.0, -1.0, 0.0, 0.0, 0.0, 0.0, -1.0, 0.0),
}


def _active_cone_input(context):
    """(root props, ConeInput props) of the active rebuilt file's selected ConeInput."""
    rp = _rebuild_root(context)[1]
    if rp is None or not len(rp.cone_inputs):
        return rp, None
    return rp, rp.cone_inputs[min(rp.active_cone_input_index, len(rp.cone_inputs) - 1)]


class JCNS_OT_ConeInputAdd(Operator):
    bl_idname = "jcns.cone_input_add"
    bl_label  = T("ops.label.cone_input_add")
    bl_description = T("ops.desc.cone_input_add")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _rebuild_root(context)[1] is not None

    def execute(self, context):
        rp = _rebuild_root(context)[1]
        ci = rp.cone_inputs.add()
        ci.name = "Cone%02d_cdr" % (len(rp.cone_inputs) - 1)
        rp.active_cone_input_index = len(rp.cone_inputs) - 1
        return {'FINISHED'}


class JCNS_OT_ConeInputRemove(Operator):
    bl_idname = "jcns.cone_input_remove"
    bl_label  = T("ops.label.cone_input_remove")
    bl_description = T("ops.desc.cone_input_remove")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _active_cone_input(context)[1] is not None

    def execute(self, context):
        from . import get_export_root, get_constraint_empties
        root, _ = get_export_root(context)
        rp = _rebuild_root(context)[1]
        i = min(rp.active_cone_input_index, len(rp.cone_inputs) - 1)
        rp.cone_inputs.remove(i)
        rp.active_cone_input_index = max(0, i - 1)
        # ConeDrivers point at the table by index: the removed cone becomes "no cone"
        # (255), later ones move down by one.
        cut = 0
        for e in get_constraint_empties(root):
            for k in e.jcns_cns_props.cone_drivers:
                if k.cone_input_index == i:
                    k.cone_input_index = 255
                    cut += 1
                elif i < k.cone_input_index != 255:
                    k.cone_input_index -= 1
        if cut:
            self.report({'WARNING'}, T("ops.cone_input.removed_refs", cut))
        refresh_applied_driver(root)
        return {'FINISHED'}


class JCNS_OT_ConeInputMatrix(Operator):
    bl_idname = "jcns.cone_input_matrix"
    bl_label  = T("ops.label.cone_input_matrix")
    bl_description = T("ops.desc.cone_input_matrix")
    bl_options = {'REGISTER', 'UNDO'}

    preset: bpy.props.EnumProperty(items=[
        ('IDENTITY', T("ops.cone_input.matrix_identity"), ""),
        ('MIRROR', T("ops.cone_input.matrix_mirror"), ""),
    ])

    @classmethod
    def poll(cls, context):
        return _active_cone_input(context)[1] is not None

    def execute(self, context):
        _active_cone_input(context)[1].matrix = _CONE_MATRICES[self.preset]
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
    JCNS_OT_MdfRefAdd,
    JCNS_OT_MdfRefRemove,
    JCNS_OT_MultiSourceAdd,
    JCNS_OT_MultiSourceRemove,
    JCNS_OT_MultiNormalizeWeights,
    JCNS_OT_CMCreate,
    JCNS_OT_CMRemove,
    JCNS_OT_CMNormalize,
    JCNS_OT_CMEdit,
    JCNS_OT_ConeDriverAdd,
    JCNS_OT_ConeDriverRemove,
    JCNS_OT_ConeInputAdd,
    JCNS_OT_ConeInputRemove,
    JCNS_OT_ConeInputMatrix,
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
