"""
What a JCNS source reads off its bone, per the source's +25 byte, InputType.

Every rotation read works on the bone's whole rotation relative to its parent,
rest pose included (q = rest * Rz * Ry * Rx for a Blender XYZ Euler pose), and
every translation read on its whole position relative to the parent, rest offset
included:

  +25=0  position component (the rest offset plus the posed offset turned by rest)
  +25=1  Euler component, in the order +27 names (0: Blender XYZ, R = Rz * Ry * Rx)
  +25=2  scale component (the bone's rest scale at rest)
  +25=3  swing-twist about X with q = swing * twist: X is the twist angle, Y / Z
         are 2 * atan2(s_axis, s_w) of the swing
  +25=4  the same with q = twist * swing
  +25=5  rotation vector (axis * angle) component

Two more source fields shape the rotation reads:

  +27 (RotOrder)  the Euler order of +25=1, as a matrix product with
         the rightmost factor applied first: 0 Rz*Ry*Rx (Blender XYZ), 1 Rx*Rz*Ry
         (YZX), 2 Ry*Rx*Rz (ZXY), 3 Rx*Ry*Rz (ZYX).  +25 = 3/4/5 ignore it.
  ref_frame (+56, the reference frame)  +25 = 3/4/5 decompose f^-1 * q * f instead of
         q, so the twist axis is f * X and the rotation vector is read in f's
         axes.  +25=1 ignores it.

Only InputType 0-5 occur.  Pure Python, no bpy.  Quaternions are (w, x, y, z); angles are radians.
"""
import math

from jcns_i18n import T

# (value, identifier, name, quantity, description)
READ_MODES = (
    (0, 'POSITION', T("core.read_mode.0.name"), 'Translation', T("core.read_mode.0.desc")),
    (1, 'EULER', T("core.read_mode.1.name"), 'Rotation', T("core.read_mode.1.desc")),
    (2, 'SCALE', T("core.read_mode.2.name"), 'Scale', T("core.read_mode.2.desc")),
    (3, 'SWING_TWIST', T("core.read_mode.3.name"), 'Rotation', T("core.read_mode.3.desc")),
    (4, 'TWIST_SWING', T("core.read_mode.4.name"), 'Rotation', T("core.read_mode.4.desc")),
    (5, 'ROTATION_VECTOR', T("core.read_mode.5.name"), 'Rotation', T("core.read_mode.5.desc")),
)
_BY_VALUE = {m[0]: m for m in READ_MODES}
_BY_ID = {m[1]: m for m in READ_MODES}
DEFAULT_READ_MODE = 3

ROTATION_MODES = {1: 'euler', 3: 'swing_twist', 4: 'twist_swing', 5: 'rotvec'}


def read_mode_value(mode):
    """A InputType as its byte value, from the value itself or its identifier."""
    if isinstance(mode, str):
        return _BY_ID[mode][0] if mode in _BY_ID else DEFAULT_READ_MODE
    return int(mode)


def read_mode_id(value):
    """The identifier of a InputType byte; None for a value outside 0-5."""
    m = _BY_VALUE.get(int(value))
    return m[1] if m else None


def read_quantity(mode):
    """'Translation', 'Rotation' or 'Scale' for a InputType (value or identifier)."""
    m = _BY_VALUE.get(read_mode_value(mode))
    return m[3] if m else 'Rotation'


def qmul(a, b):
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return (aw * bw - ax * bx - ay * by - az * bz, aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx, aw * bz + ax * by - ay * bx + az * bw)


def _conj(q):
    return (q[0], -q[1], -q[2], -q[3])


def _pos_w(q):
    return q if q[0] >= 0.0 else (-q[0], -q[1], -q[2], -q[3])


def from_euler_xyz(euler):
    """Blender XYZ Euler (x applied first) -> quaternion, i.e. Rz * Ry * Rx."""
    q = (1.0, 0.0, 0.0, 0.0)
    for a in (2, 1, 0):
        h = euler[a] * 0.5
        r = [math.cos(h), 0.0, 0.0, 0.0]
        r[a + 1] = math.sin(h)
        q = qmul(q, r)
    return q


def pose_rotation(rest, euler):
    """The bone's whole parent-relative rotation for a Blender XYZ Euler pose."""
    return _pos_w(qmul(rest, from_euler_xyz(euler)))


# +27 RotOrder -> (i, j, k) with R = R_i * R_j * R_k (k applied first)
EULER_ORDERS = {0: (2, 1, 0), 1: (0, 2, 1), 2: (1, 0, 2), 3: (0, 1, 2)}
# The same orders as Blender names them (first-applied axis first)
EULER_ORDER_NAMES = {0: 'XYZ', 1: 'YZX', 2: 'ZXY', 3: 'ZYX'}


def euler_order_value(order):
    """A +27 RotOrder as its byte value, from the value or its Blender name."""
    if isinstance(order, str):
        for value, name in EULER_ORDER_NAMES.items():
            if name == order:
                return value
        return 0
    return int(order)


def _matrix(q):
    w, x, y, z = q
    return ((1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)),
            (2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)),
            (2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)))


def _euler(q, order):
    """Euler angles (x, y, z) of q for one +27 order."""
    i, j, k = EULER_ORDERS.get(order, EULER_ORDERS[0])
    m = _matrix(q)
    s = 1.0 if (j - i) % 3 == 1 else -1.0         # +1 for a cyclic order
    angles = [0.0, 0.0, 0.0]
    angles[j] = math.asin(max(-1.0, min(1.0, s * m[i][k])))
    angles[i] = math.atan2(-s * m[j][k], m[k][k])
    angles[k] = math.atan2(-s * m[i][j], m[i][i])
    return angles


def _swing_twist_x(q, twist_first):
    w, x = q[0], q[1]
    n = math.hypot(w, x)
    t = (1.0, 0.0, 0.0, 0.0) if n < 1e-12 else (w / n, x / n, 0.0, 0.0)
    s = qmul(q, _conj(t)) if twist_first else qmul(_conj(t), q)
    return _pos_w(t), _pos_w(s)


def rotation(mode, q, axis, order=0, frame=None):
    """Component `axis` (0-2) of whole rotation q as read by one rotation mode.

    `order` is the source's +27 RotOrder (used by 'euler' only); `frame` its
    ref_frame (w, x, y, z), the reference frame of the other modes.
    """
    q = _pos_w(q)
    if mode == 'euler':
        return _euler(q, order)[axis]
    if frame is not None and abs(frame[0]) < 1.0 - 1e-9:
        q = _pos_w(qmul(qmul(_conj(frame), q), frame))
    if mode in ('swing_twist', 'twist_swing'):
        t, s = _swing_twist_x(q, twist_first=(mode == 'swing_twist'))
        if axis == 0:
            return 2.0 * math.atan2(t[1], t[0])
        return 2.0 * math.atan2(s[axis + 1], s[0])
    if mode == 'rotvec':
        v = math.sqrt(q[1] ** 2 + q[2] ** 2 + q[3] ** 2)
        if v < 1e-12:
            return 0.0
        return 2.0 * math.atan2(v, q[0]) * q[axis + 1] / v
    raise ValueError(mode)


def override_basis(rest, replaced, added):
    """Blender pose basis (XYZ Euler, radians) of a bone whose rotation channels are
    written with AttrFlags bit0 = 0 (replace) and / or 1 (add).

    bit0 = 1 lays a value on the rest pose, rest * R(v); bit0 = 0 replaces the
    channel: take the rest pose's XYZ Euler angles, put each replaced channel's
    value in place of its angle, then lay the added channels on top,
    R(e') * R(v_add).  The mixed add/replace case follows this model.

    `replaced` / `added` map axis (0-2) -> value; returns the basis (x, y, z) such
    that rest * basis is that rotation.
    """
    e = list(_euler(rest, 0))
    for a, v in replaced.items():
        e[a] = v
    add = [0.0, 0.0, 0.0]
    for a, v in added.items():
        add[a] = v
    q = qmul(from_euler_xyz(e), from_euler_xyz(add))
    return tuple(_euler(_pos_w(qmul(_conj(rest), q)), 0))


# How a rotation target composes its three channel values, by TransformElement.
# They mirror the source reads: 1 / 4 / 5 / 6 build the rotation the way InputType 1 / 3 / 4 / 5 take it
# apart.  13 and 14 hold a single rotation about the written axis per bone -- the
# last such entry on the bone wins, whatever its axis.
TARGET_MODES = {1: 'euler', 4: 'swing_twist', 5: 'twist_swing', 6: 'rotvec',
                13: 'axis', 14: 'axis'}


def _axis_q(axis, v):
    h = v * 0.5
    r = [math.cos(h), 0.0, 0.0, 0.0]
    r[axis + 1] = math.sin(h)
    return tuple(r)


def compose(mode, v):
    """The rotation a target mode builds from channel values v = (x, y, z)."""
    if mode == 'euler':
        return from_euler_xyz(v)
    if mode in ('swing_twist', 'twist_swing'):
        t = _axis_q(0, v[0])
        s = (1.0, 0.0, math.tan(v[1] * 0.5), math.tan(v[2] * 0.5))
        n = math.sqrt(sum(c * c for c in s))
        s = tuple(c / n for c in s)
        return qmul(s, t) if mode == 'swing_twist' else qmul(t, s)
    if mode == 'rotvec':
        ang = math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)
        if ang < 1e-12:
            return (1.0, 0.0, 0.0, 0.0)
        k = math.sin(ang * 0.5) / ang
        return (math.cos(ang * 0.5), v[0] * k, v[1] * k, v[2] * k)
    raise ValueError(mode)


def target_basis(rest, parts):
    """Blender pose basis (XYZ Euler) of a rotation target from its live channels.

    `parts` are (axis, mode, replaces, value) in file order of their winning
    entries.  The last entry's mode decides how the whole bone is composed, and every
    entry's value is used in it whatever its own mode (an Euler bone takes the Y value
    of a type 4 entry as its Euler Y).

    Added channels (AttrFlags bit0 = 1) lay their composed rotation on the rest pose,
    q1 = rest * compose(added).  Replaced channels (bit0 = 0) then take that rotation apart
    in the mode's own decomposition, put each value in place of its component and compose
    again; with no added channel q1 is the rest pose.  This matches bones that mix
    add and replace on types 1, 4, 5 and 6 (rounds 13 and 16) and pure replace on all four.
    Axis rotations (13 / 14) hold one rotation and replacing drops the whole rest.
    """
    if not parts:
        return (0.0, 0.0, 0.0)
    last = parts[-1]
    mode = last[1]
    if mode == 'axis':
        q = _axis_q(last[0], last[3])
        if not last[2]:
            q = qmul(rest, q)
        return tuple(_euler(_pos_w(qmul(_conj(rest), q)), 0))
    replaced = {a: v for a, m, r, v in parts if r}
    added = {a: v for a, m, r, v in parts if not r}
    q = rest
    if added:
        add = [0.0, 0.0, 0.0]
        for a, v in added.items():
            add[a] = v
        q = qmul(rest, compose(mode, add))
    if replaced:
        c = [rotation(mode, q, a) for a in range(3)]
        for a, v in replaced.items():
            c[a] = v
        q = compose(mode, c)
    return tuple(_euler(_pos_w(qmul(_conj(rest), q)), 0))


def rest_input(mode, axis, rest, offset_cm, order=0, frame=None, scale=None):
    """What a source reads with its bone at rest, in the file's units (degrees,
    centimetres, or 1 for a scale).

    `mode` is a InputType value or identifier, `rest` the bone's parent-relative rest
    rotation (w, x, y, z), `offset_cm` its rest offset from the parent; `order` and
    `frame` as for rotation(); `scale` its rest scale (default 1).
    """
    value = read_mode_value(mode)
    q = read_quantity(value)
    if q == 'Scale':
        return float(scale[axis]) if scale is not None else 1.0
    if q == 'Translation':
        return float(offset_cm[axis])
    return math.degrees(rotation(ROTATION_MODES.get(value, 'swing_twist'), rest, axis,
                                 order, frame))


def position(rest, offset, loc, axis):
    """Component `axis` of the whole parent-relative position: offset + rest * loc."""
    p = qmul(qmul(rest, (0.0, loc[0], loc[1], loc[2])), _conj(rest))
    return offset[axis] + p[axis + 1]


def translation_basis(rest, offset, parts, parent_scale=(1.0, 1.0, 1.0)):
    """Blender location basis for parent-axis translations.

    Parts are (axis, replaces, value) for winning channels in file order, in
    the same length units as offset.  Adding writes offset[axis] + value;
    replacing writes value on that axis alone; untouched axes keep offset.
    Blender's location basis is rest-rotated, so the parent-axis delta goes back
    through inverse rest; the engine's output is not rotated before adding.
    The value is written in the parent's own local frame, which a scaled parent stretches
    (round 18), and Blender's parent space has no rest scale: the delta is multiplied by
    `parent_scale` (the parent's rest scale) on each axis.
    """
    delta = [0.0, 0.0, 0.0]
    for axis, replaces, value in parts:
        delta[axis] = (value - offset[axis] if replaces else value) * parent_scale[axis]
    p = qmul(qmul(_conj(rest), (0.0, *delta)), rest)
    return tuple(p[1:])


# Panel text for the engine rules.  Each line is (text, measured); measured =
# False marks a modelled rule, which the UI shows with a question mark.

# Built per call so a language switch shows at once.
def _target_rules():
    return {
        0: {True: [(T("core.rule.t0_add"), True)],
            False: [(T("core.rule.t0_replace"), True)]},
        1: {True: [(T("core.rule.t1_add"), True)],
            False: [(T("core.rule.t1_replace"), True)]},
        2: {None: [(T("core.rule.t2"), True)]},
        4: {True: [(T("core.rule.t4_add"), True)],
            False: [(T("core.rule.t4_replace"), True)]},
        5: {True: [(T("core.rule.t5_add"), True)],
            False: [(T("core.rule.t5_replace"), True)]},
        6: {True: [(T("core.rule.t6_add"), True)],
            False: [(T("core.rule.t6_replace"), True)]},
        13: {True: [(T("core.rule.t13_add"), True),
                    (T("core.rule.t13_single"), True)],
             False: [(T("core.rule.t13_replace"), True),
                     (T("core.rule.t13_single"), True)]},
        14: {True: [(T("core.rule.t14_add"), True)],
             False: [(T("core.rule.t14_replace"), True)]},
    }


def target_rule(transform_type, additive):
    """Lines saying how the engine applies an entry of this TransformElement, with
    AttrFlags bit0 = `additive`.  -> [(text, measured), ...]"""
    rules = _target_rules().get(int(transform_type))
    if rules is None:
        return [(T("core.rule.unknown_target"), False)]
    return list(rules.get(None) or rules[bool(additive)])


def read_rule(read_mode, euler_order=0, frame_is_identity=True):
    """Lines saying what the engine reads off the source bone.  -> [(text, measured)]"""
    v = read_mode_value(read_mode)
    base = {
        0: T("core.rule.read_0"),
        1: T("core.rule.read_1", EULER_ORDER_NAMES.get(int(euler_order), 'XYZ')),
        2: T("core.rule.read_2"),
        3: T("core.rule.read_3"),
        4: T("core.rule.read_4"),
        5: T("core.rule.read_5"),
    }.get(v)
    if base is None:
        return [(T("core.rule.read_unknown", read_mode), False)]
    lines = [(base, True)]
    if v in (3, 4, 5) and not frame_is_identity:
        lines.append((T("core.rule.read_frame"), True))
    return lines
