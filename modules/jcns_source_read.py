"""
What a JCNS source reads off its bone, per the source's +25 byte, ReadMode.

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

  +27 (EulerOrder)  the Euler order of +25=1, as a matrix product with
         the rightmost factor applied first: 0 Rz*Ry*Rx (Blender XYZ), 1 Rx*Rz*Ry
         (YZX), 2 Ry*Rx*Rz (ZXY), 3 Rx*Ry*Rz (ZYX).  +25 = 3/4/5 ignore it.
  rest_quat (+56, the reference frame)  +25 = 3/4/5 decompose f^-1 * q * f instead of
         q, so the twist axis is f * X and the rotation vector is read in f's
         axes.  +25=1 ignores it.

Only ReadMode 0-5 occur.  Pure Python, no bpy.  Quaternions are (w, x, y, z); angles are radians.
"""
import math

# (value, identifier, name, quantity, description)
READ_MODES = (
    (0, 'POSITION', "位置", 'Translation',
     "相对父骨的位置分量（厘米），含静止偏移。多用于面部滑杆骨和武器部件。约 10% 的源"),
    (1, 'EULER', "欧拉角", 'Rotation',
     "相对父骨完整旋转（含静止姿态）的欧拉分量；分解顺序由 +27 欧拉顺序决定（0 = XYZ，最常见）。约 6% 的源"),
    (2, 'SCALE', "缩放", 'Scale',
     "缩放分量，静止为 1。约 5% 的源"),
    (3, 'SWING_TWIST', "摆动·扭转", 'Rotation',
     "绕 X 的摆动-扭转分解，q = 摆动·扭转（先扭转）。X 取扭转角，Y/Z 取摆动的 "
     "2·atan2(s_轴, s_w)。含静止姿态。最常用，约 77% 的源"),
    (4, 'TWIST_SWING', "扭转·摆动", 'Rotation',
     "同摆动·扭转，但 q = 扭转·摆动（先摆动）；X 与前者相同，Y/Z 不同。约 1% 的源"),
    (5, 'ROTATION_VECTOR', "旋转向量", 'Rotation',
     "旋转向量（转轴×角度）的分量，含静止姿态。常用于读大腿、驱动 ThighTwist 一类。约 2% 的源"),
)
_BY_VALUE = {m[0]: m for m in READ_MODES}
_BY_ID = {m[1]: m for m in READ_MODES}
DEFAULT_READ_MODE = 3

ROTATION_MODES = {1: 'euler', 3: 'swing_twist', 4: 'twist_swing', 5: 'rotvec'}


def read_mode_value(mode):
    """A ReadMode as its byte value, from the value itself or its identifier."""
    if isinstance(mode, str):
        return _BY_ID[mode][0] if mode in _BY_ID else DEFAULT_READ_MODE
    return int(mode)


def read_mode_id(value):
    """The identifier of a ReadMode byte; None for a value outside 0-5."""
    m = _BY_VALUE.get(int(value))
    return m[1] if m else None


def read_quantity(mode):
    """'Translation', 'Rotation' or 'Scale' for a ReadMode (value or identifier)."""
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


# +27 EulerOrder -> (i, j, k) with R = R_i * R_j * R_k (k applied first)
EULER_ORDERS = {0: (2, 1, 0), 1: (0, 2, 1), 2: (1, 0, 2), 3: (0, 1, 2)}
# The same orders as Blender names them (first-applied axis first)
EULER_ORDER_NAMES = {0: 'XYZ', 1: 'YZX', 2: 'ZXY', 3: 'ZYX'}


def euler_order_value(order):
    """A +27 EulerOrder as its byte value, from the value or its Blender name."""
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

    `order` is the source's +27 EulerOrder (used by 'euler' only); `frame` its
    rest_quat (w, x, y, z), the reference frame of the other modes.
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
    written with Flags bit0 = 0 (replace) and / or 1 (add).

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


# How a rotation target composes its three channel values, by TransformType.
# They mirror the source reads: 1 / 4 / 5 / 6 build the rotation the way ReadMode 1 / 3 / 4 / 5 take it
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
    entries.  Replacing (Flags bit0 = 0) drops the rest pose; adding lays the
    rotation on it.  An 'euler' bone goes through override_basis.  For the other
    modes the latest channel's mode and bit0 decide the whole bone (mixing modes
    on one bone is modelled this way, not measured).
    """
    if not parts:
        return (0.0, 0.0, 0.0)
    last = parts[-1]
    mode = last[1]
    if mode == 'euler':
        replaced = {a: v for a, m, r, v in parts if r}
        added = {a: v for a, m, r, v in parts if not r}
        return override_basis(rest, replaced, added)
    if mode == 'axis':
        q = _axis_q(last[0], last[3])
    else:
        v = [0.0, 0.0, 0.0]
        for a, m, r, val in parts:
            if m == mode:
                v[a] = val
        q = compose(mode, v)
    if not last[2]:
        q = qmul(rest, q)
    return tuple(_euler(_pos_w(qmul(_conj(rest), q)), 0))


def rest_input(mode, axis, rest, offset_cm, order=0, frame=None, scale=None):
    """What a source reads with its bone at rest, in the file's units (degrees,
    centimetres, or 1 for a scale).

    `mode` is a ReadMode value or identifier, `rest` the bone's parent-relative rest
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


def translation_basis(rest, offset, parts):
    """Blender location basis for parent-axis translations.

    Parts are (axis, replaces, value) for winning channels in file order, in
    the same length units as offset.  Adding writes offset[axis] + value;
    replacing writes value on that axis alone; untouched axes keep offset.
    Blender's location basis is rest-rotated, so the parent-axis delta goes back
    through inverse rest; the engine's output is not rotated before adding.
    """
    delta = [0.0, 0.0, 0.0]
    for axis, replaces, value in parts:
        delta[axis] = value - offset[axis] if replaces else value
    p = qmul(qmul(_conj(rest), (0.0, *delta)), rest)
    return tuple(p[1:])


# Panel text for the engine rules.  Each line is (text, measured); measured =
# False marks a modelled rule, which the UI shows with a question mark.

_UNMEASURED_REPLACE = ("替换：丢掉静止旋转，只剩合成出的旋转", False)
_TARGET_RULES = {
    0: {True: [("叠加：位置 = 静止偏移 + 输出，沿父骨的轴", True)],
        False: [("替换：所写轴的位置 = 输出，其余轴保留静止偏移", True)]},
    1: {True: [("叠加：静止姿态 · Rz·Ry·Rx（XYZ 欧拉，与文件里各轴先后无关）", True)],
        False: [("替换：静止姿态的 XYZ 欧拉角里换掉所写的轴，其余轴保留", True)]},
    2: {None: [("所写轴的缩放 = 输出，其余轴保留静止缩放；bit0 不起作用", True)]},
    4: {True: [("叠加：静止姿态 · 摆动(Y,Z) · 扭转(X)", True)], False: [_UNMEASURED_REPLACE]},
    5: {True: [("叠加：静止姿态 · 扭转(X) · 摆动(Y,Z)", True)], False: [_UNMEASURED_REPLACE]},
    6: {True: [("叠加：静止姿态 · 旋转向量（转轴 × 角度）", True)], False: [_UNMEASURED_REPLACE]},
    13: {True: [("叠加：静止姿态 · 绕所写轴转「输出」角", True),
                ("每根骨只有一个：骨上最后一条 13/14 整条胜出，与它写哪个轴无关", True)],
         False: [("替换：丢掉整个静止旋转，只剩绕所写轴的「输出」角", True),
                 ("每根骨只有一个：骨上最后一条 13/14 整条胜出，与它写哪个轴无关", True)]},
    14: {True: [("与 13 相同：静止姿态 · 绕所写轴转「输出」角，骨上最后一条 13/14 生效", True)],
         False: [("与 13 相同：丢掉整个静止旋转", False)]},
}


def target_rule(transform_type, additive):
    """Lines saying how the engine applies an entry of this TransformType, with
    Flags bit0 = `additive`.  -> [(text, measured), ...]"""
    rules = _TARGET_RULES.get(int(transform_type))
    if rules is None:
        return [("形变 / 材质类目标：具体作用未知，没有预览", False)]
    return list(rules.get(None) or rules[bool(additive)])


def read_rule(read_mode, euler_order=0, frame_is_identity=True):
    """Lines saying what the engine reads off the source bone.  -> [(text, measured)]"""
    v = read_mode_value(read_mode)
    base = {
        0: "读相对父骨的位置分量（厘米），静止偏移算在内",
        1: "读相对父骨完整旋转的欧拉分量（顺序 %s），静止姿态算在内"
           % EULER_ORDER_NAMES.get(int(euler_order), 'XYZ'),
        2: "读缩放分量，静止缩放算在内（静止时就是静止缩放）",
        3: "读相对父骨完整旋转绕 X 的摆动·扭转分解：X = 扭转角，Y/Z = 摆动",
        4: "同摆动·扭转，但先摆动后扭转：X 相同，Y/Z 不同",
        5: "读相对父骨完整旋转的旋转向量（转轴 × 角度）分量",
    }.get(v)
    if base is None:
        return [("未知的读取方式 %r" % (read_mode,), False)]
    lines = [(base, True)]
    if v in (3, 4, 5) and not frame_is_identity:
        lines.append(("按参考系四元数 f 分解 f^-1·q·f：扭转轴变成 f·X", True))
    return lines
