"""
jcns_source_read.py
-------------------
What a JCNS source reads off its bone, per the source's +25 byte, ReadMode.

Measured in game 2026-09-30 on the xaihi test rig (rounds 6-7): one bone turned
hard on all three axes, with a -2 deg rest rotation and a rest offset, was read
through identity mappings by every +25 and every axis; each formula below matched
the engine's own output to 0.002 deg / 0.0001 cm over 2100 frames.

Every rotation read works on the bone's whole rotation relative to its parent,
rest pose included (q = rest * Rz * Ry * Rx for a Blender XYZ Euler pose), and
every translation read on its whole position relative to the parent, rest offset
included:

  +25=0  position component (the rest offset plus the posed offset turned by rest)
  +25=1  XYZ Euler component (Blender's XYZ mode, R = Rz * Ry * Rx)
  +25=2  scale component (1 at rest; read by the driver as is)
  +25=3  swing-twist about X with q = swing * twist: X is the twist angle, Y / Z
         are 2 * atan2(s_axis, s_w) of the swing
  +25=4  the same with q = twist * swing
  +25=5  rotation vector (axis * angle) component

The byte is named ReadMode here (bt called it TransformIDSrc / InterpolationID).
Only 0-5 occur: 2114 shipped files (v29 and v102), 54308 sources.

Pure Python, no bpy.  Quaternions are (w, x, y, z); angles are radians.
"""
import math

# (value, identifier, name, quantity, description).  Shares are of the 54308
# shipped sources.
READ_MODES = (
    (0, 'POSITION', "位置", 'Translation',
     "相对父骨的位置分量（厘米），含静止偏移。多用于面部滑杆骨和武器部件。约 10% 的源"),
    (1, 'EULER_XYZ', "欧拉 XYZ", 'Rotation',
     "相对父骨完整旋转（含静止姿态）的 XYZ 欧拉分量，R = Rz·Ry·Rx。约 6% 的源"),
    (2, 'SCALE', "缩放", 'Scale',
     "缩放分量，静止为 1。约 5% 的源"),
    (3, 'SWING_TWIST', "摆动·扭转", 'Rotation',
     "绕 X 的摆动-扭转分解，q = 摆动·扭转（先扭转）。X 取扭转角，Y/Z 取摆动的 "
     "2·atan2(s_轴, s_w)。含静止姿态。最常用，约 77% 的源"),
    (4, 'TWIST_SWING', "扭转·摆动", 'Rotation',
     "同摆动·扭转，但 q = 扭转·摆动（先摆动）；X 与前者相同，Y/Z 不同。约 1% 的源"),
    (5, 'ROTATION_VECTOR', "旋转向量", 'Rotation',
     "旋转向量（转轴×角度）的分量，含静止姿态。原版几乎只读大腿、驱动 ThighTwist 一类。约 2% 的源"),
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


def _euler_xyz(q):
    w, x, y, z = q
    m20 = 2.0 * (x * z - w * y)
    m21 = 2.0 * (y * z + w * x)
    m22 = 1.0 - 2.0 * (x * x + y * y)
    m10 = 2.0 * (x * y + w * z)
    m00 = 1.0 - 2.0 * (y * y + z * z)
    return (math.atan2(m21, m22), math.asin(max(-1.0, min(1.0, -m20))), math.atan2(m10, m00))


def _swing_twist_x(q, twist_first):
    w, x = q[0], q[1]
    n = math.hypot(w, x)
    t = (1.0, 0.0, 0.0, 0.0) if n < 1e-12 else (w / n, x / n, 0.0, 0.0)
    s = qmul(q, _conj(t)) if twist_first else qmul(_conj(t), q)
    return _pos_w(t), _pos_w(s)


def rotation(mode, q, axis):
    """Component `axis` (0-2) of whole rotation q as read by one rotation mode."""
    q = _pos_w(q)
    if mode == 'euler':
        return _euler_xyz(q)[axis]
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


def position(rest, offset, loc, axis):
    """Component `axis` of the whole parent-relative position: offset + rest * loc."""
    p = qmul(qmul(rest, (0.0, loc[0], loc[1], loc[2])), _conj(rest))
    return offset[axis] + p[axis + 1]
