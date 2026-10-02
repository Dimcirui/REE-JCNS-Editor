"""
Anchor capture: the value a Ranges anchor should hold so that a bone left in its
current pose produces that pose.  Pure Python, no bpy.

Source side (capture_source) is the read the drivers make, taken from a pose:
jcns_source_read.rotation / position on the bone's whole parent-relative transform,
rest included, the same calls as jcns_drivers._read.

Target side (capture_target) is the inverse of the target composition,
jcns_source_read.target_basis / translation_basis and the scale rule: the value one
entry would have to write on one axis for the bone to land in the given pose.  It
assumes the entry's own TransformElement decides how the bone is composed and, for a
bone driven by several entries, takes the other axes from the pose as they are.

Inputs are plain Blender pose data: XYZ Euler in radians, location and offsets in
metres, scale as the pose ratio.  Results are in the file's units (degrees,
centimetres, scale as is).  Quaternions are (w, x, y, z).

What cannot be recovered, by design:
  * a rotation read keeps only the asked component (InputType 3 drops the swing on Y/Z
    from its X value, and so on), so a read does not identify the pose;
  * angles come back in (-180, 180] (rotation vectors and swing-twist components
    wrap there), so a written value beyond that returns its equivalent;
  * a TransformElement 13 / 14 entry holds one rotation about its own axis, so a pose
    that is not a pure turn about that axis comes back with the rest as `error`.
"""
import math

import jcns_complex
import jcns_mapping
import jcns_source_read as sr

# TransformElement values capture_target can take a value for; the others drive no
# bone channel (blend shapes, materials, unknown) or have no defined composition.
CAPTURABLE_TARGETS = (0, 1, 2, 4, 5, 6, 13, 14)
_IDENTITY = (1.0, 0.0, 0.0, 0.0)


def _file_per_driver(quantity):
    """File units per driver unit: degrees per radian, centimetres per metre."""
    return 1.0 / jcns_mapping._to_driver_units((1.0,), quantity)[0]


def target_capturable(transform_element):
    """Does a target of this TransformElement value have a capture rule?"""
    return int(transform_element) in CAPTURABLE_TARGETS


def capture_source(input_type, axis, rest, offset, pose_euler, pose_loc, pose_scale,
                   order=0, frame=None, rest_scale=(1.0, 1.0, 1.0)):
    """What a source with this InputType reads off its bone in the given pose.

    `rest` and `offset` are the bone's rest rotation and offset from its parent (metres);
    `order` and `frame` are the source's +27 RotOrder and ref_frame, as for
    jcns_source_read.rotation; `rest_scale` is the bone's rest scale.  Every rotation
    axis of the pose counts, including the ones an applied preview would leave unread.
    -> degrees, centimetres or a scale; None for an axis beyond Z or an unknown InputType.
    """
    if not 0 <= axis <= 2:
        return None
    value = sr.input_type_value(input_type)
    quantity = sr.read_quantity(value)
    if quantity == 'Scale':
        return pose_scale[axis] * rest_scale[axis]
    if quantity == 'Translation':
        return sr.position(rest, offset, pose_loc, axis) * _file_per_driver(quantity)
    mode = sr.ROTATION_MODES.get(value)
    if mode is None:
        return None
    q = sr.pose_rotation(rest, pose_euler)
    return sr.rotation(mode, q, axis, sr.rot_order_value(order), frame) * _file_per_driver(quantity)


def _twist(q, axis):
    """(angle, error) of q = swing * twist about `axis`: the twist angle and the swing's angle."""
    w, c = q[0], q[axis + 1]
    n = math.hypot(w, c)
    if n < 1e-12:
        return None
    return 2.0 * math.atan2(c, w), 2.0 * math.acos(min(1.0, n))


def capture_target(transform_element, base_pose, axis, rest, pose_euler, pose_loc, pose_scale,
                   offset=(0.0, 0.0, 0.0), parent_scale=(1.0, 1.0, 1.0),
                   rest_scale=(1.0, 1.0, 1.0)):
    """The value a target entry (TransformElement value, AttrFlags bit0 = `base_pose`) writes on
    `axis` to bring its bone to the given pose.

    `rest` / `offset` are the bone's rest rotation and offset from its parent (metres),
    `parent_scale` the parent's rest scale, `rest_scale` the bone's own.
    -> (value, error) in degrees, centimetres or a scale, or None when there is no rule
    (axis beyond Z, a TransformElement outside CAPTURABLE_TARGETS, a zero parent scale, a
    pose that leaves the twist undefined).  `error` is the angle in degrees of the pose's
    rotation that this entry's single rotation cannot express; it is 0 except for
    TransformElement 13 / 14.
    """
    tt = int(transform_element)
    if not 0 <= axis <= 2 or tt not in CAPTURABLE_TARGETS:
        return None
    if tt == 0:
        # translation_basis: delta = (value - offset if replacing else value) * parent_scale,
        # location = rest^-1 * delta
        if abs(parent_scale[axis]) < 1e-12:
            return None
        delta = sr.position(rest, (0.0, 0.0, 0.0), pose_loc, axis) / parent_scale[axis]
        if not base_pose:
            delta += offset[axis]
        return delta * _file_per_driver('Translation'), 0.0
    if tt == 2:
        return pose_scale[axis] * rest_scale[axis], 0.0

    mode = sr.TARGET_MODES[tt]
    deg = _file_per_driver('Rotation')
    if mode == 'euler' and base_pose:
        return pose_euler[axis] * deg, 0.0
    # Adding lays the value on the rest pose, so the pose's basis is the added rotation;
    # replacing decomposes the whole rotation, rest * basis.
    q = sr.pose_rotation(_IDENTITY if base_pose else rest, pose_euler)
    if mode == 'axis':
        t = _twist(q, axis)
        if t is None:
            return None
        return t[0] * deg, t[1] * deg
    return sr.rotation(mode, q, axis) * deg, 0.0


def mapped_output(anchors, x, two_point=False, interp=0, cm_keys=None):
    """The output of one source's mapping for the source value x, in file units.

    `anchors` is (from_start, from_kink, from_end, to_start, to_kink, to_end);
    `cm_keys` (jcns_cm.keys) replaces them when the source has a ComplexMapping.
    """
    if cm_keys:
        return jcns_complex.evaluate(cm_keys, x)
    return jcns_mapping.eval_piecewise(*anchors, x, two_point=two_point, interp=interp)
