"""
Set-driven-key planning: from poses of a driver bone and a driven bone to Ranges
constraints.  Pure Python, no bpy.

A key is the pair of raw pose snapshots of the two bones, recorded together.  Nothing
about how they are read is decided at record time; plan_keys() picks the driver quantity
and the driven channels from how the poses differ between keys, then turns each driven
channel into one entry whose single source maps the driver value to the channel value.

Driver values are what jcns_capture.capture_source reads (rest pose included), channel
values what jcns_capture.capture_target would have to write, so the anchors can be
stored as they are.  Units are the file's: degrees, centimetres, scale as is.
"""
import math
from dataclasses import dataclass, field

import jcns_capture as cap
import jcns_mapping
import jcns_source_read as sr
from jcns_merge import MAX_SOURCES

MAX_KEYS = 3

# Driver quantity by priority: (read mode, quantity).  Rotation is read as swing-twist, the
# engine's most common read.
_AUTO_READS = ((3, 'Rotation'), (0, 'Translation'), (2, 'Scale'))

# Smallest spread across the keys that counts as the driver moving / a channel moving.
DRIVER_MIN = {'Rotation': 1.0, 'Translation': 0.1, 'Scale': 1e-3}
CHANNEL_MIN = {'Rotation': 0.05, 'Translation': 0.005, 'Scale': 1e-4}
# Driver readings closer than this are the same reading.
SAME_DRIVE = {'Rotation': 0.01, 'Translation': 0.001, 'Scale': 1e-5}
REST_TOL = 1e-4                  # output at rest vs the value that leaves the bone at rest

UNITS = {'Rotation': "°", 'Translation': " cm", 'Scale': ""}
_TARGET_NAMES = {'Rotation': "旋转", 'Translation': "平移", 'Scale': "缩放"}
ROTATION_TYPES = (1, 4, 5, 6)    # TransformTypes whose three channels are independent


@dataclass(frozen=True)
class Pose:
    """A pose bone's basis: location (m), rotation quaternion (w, x, y, z), scale ratio."""
    loc: tuple = (0.0, 0.0, 0.0)
    quat: tuple = (1.0, 0.0, 0.0, 0.0)
    scale: tuple = (1.0, 1.0, 1.0)


@dataclass
class Key:
    driver: Pose
    driven: Pose


@dataclass
class BoneRest:
    """A bone's rest data as jcns_capture takes it; `parent_scale` only matters to targets."""
    rest: tuple = (1.0, 0.0, 0.0, 0.0)
    offset: tuple = (0.0, 0.0, 0.0)
    rest_scale: tuple = (1.0, 1.0, 1.0)
    parent_scale: tuple = (1.0, 1.0, 1.0)


@dataclass
class Drive:
    read_mode: int
    axis: int
    quantity: str
    values: list                 # the reading of each key, in key order

    def label(self):
        return drive_label(self.read_mode, self.axis)


@dataclass
class Constraint:
    """One Ranges entry with one source; anchors are ascending in the driver value."""
    transform_type: int
    axis: int
    additive: bool
    quantity: str
    read_mode: int
    source_axis: int
    euler_order: int
    three_point: bool
    from_anchors: tuple
    to_anchors: tuple

    def source_label(self):
        return drive_label(self.read_mode, self.source_axis)

    def target_label(self):
        return _TARGET_NAMES[self.quantity] + 'XYZ'[self.axis]


@dataclass
class Plan:
    ok: bool = False
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    constraints: list = field(default_factory=list)
    drive: Drive = None


class _Reject(Exception):
    pass


def drive_label(read_mode, axis):
    v = sr.read_mode_value(read_mode)
    if v in (3, 4):
        base = "扭转" if axis == 0 else "摆动"
    else:
        base = {0: "位置", 1: "欧拉", 2: "缩放", 5: "旋转向量"}.get(v, "读数")
    return base + 'XYZ'[axis]


def euler_of(pose):
    """The pose's rotation as a Blender XYZ Euler, radians."""
    n = math.sqrt(sum(c * c for c in pose.quat)) or 1.0
    return tuple(sr._euler(sr._pos_w(tuple(c / n for c in pose.quat)), 0))


def read_driver(pose, rest, read_mode, axis, order=0):
    return cap.capture_source(read_mode, axis, rest.rest, rest.offset, euler_of(pose), pose.loc,
                              pose.scale, order=order, rest_scale=rest.rest_scale)


def read_channel(pose, rest, transform_type, axis, additive=True):
    """jcns_capture.capture_target for a pose snapshot."""
    return cap.capture_target(transform_type, additive, axis, rest.rest, euler_of(pose), pose.loc,
                              pose.scale, rest.offset, rest.parent_scale, rest.rest_scale)


def _fmt(v, quantity):
    return "%.2f%s" % (v, UNITS[quantity])


def _spread(values):
    return max(values) - min(values)


# ---------------------------------------------------------------------------
# Detecting what moved
# ---------------------------------------------------------------------------

def _detect_drive(keys, rest, read_mode, axis, order):
    if read_mode is None:
        reads = _AUTO_READS
    else:
        mode = sr.read_mode_value(read_mode)
        if sr.read_mode_id(mode) is None:
            raise _Reject("读取方式 %r 不存在" % (read_mode,))
        reads = ((mode, sr.read_quantity(mode)),)
    axes = range(3) if axis is None else (axis,)
    for mode, quantity in reads:
        best = None
        for a in axes:
            values = [read_driver(k.driver, rest, mode, a, order) for k in keys]
            if best is None or _spread(values) > best[0] + 1e-12:
                best = (_spread(values), a, values)
        if best[0] > DRIVER_MIN[quantity]:
            return Drive(mode, best[1], quantity, best[2])
    if read_mode is None and axis is None:
        raise _Reject("驱动骨在各键之间没有变化")
    what = "按所选方式读" if read_mode is not None else "读"
    raise _Reject("%s驱动骨，各键之间没有变化；换一种读取方式或轴试试" % what)


def _detect_channels(keys, rest, rotation_type, warnings):
    """[(quantity, transform type, axis, values)] for every driven channel that differs between keys."""
    found = []
    for quantity, tt in (('Rotation', rotation_type), ('Translation', 0), ('Scale', 2)):
        for axis in range(3):
            label = _TARGET_NAMES[quantity] + 'XYZ'[axis]
            got = [read_channel(k.driven, rest, tt, axis) for k in keys]
            if any(g is None for g in got):
                warnings.append("被驱动骨的%s取不出值（父骨缩放为 0），已跳过" % label)
                continue
            if quantity == 'Rotation' and max(g[1] for g in got) > 0.5:
                warnings.append("被驱动骨的%s有 %.1f° 表达不了的旋转" % (label, max(g[1] for g in got)))
            values = [g[0] for g in got]
            if _spread(values) > CHANNEL_MIN[quantity]:
                found.append((quantity, tt, axis, values))
    return found


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------

def _dedupe(drive, channels):
    """Key indices in ascending driver order; keys with the same reading and the same
    channel values are one key, the same reading with different channel values is ambiguous."""
    same = SAME_DRIVE[drive.quantity]
    order = sorted(range(len(drive.values)), key=lambda i: drive.values[i])
    kept, notes = [], []
    for i in order:
        if kept and abs(drive.values[i] - drive.values[kept[-1]]) <= same:
            j = kept[-1]
            if any(abs(vals[i] - vals[j]) > CHANNEL_MIN[q] for q, _tt, _a, vals in channels):
                raise _Reject("键 %d 和键 %d 的驱动骨读数相同（%s），被驱动骨却不同，对应关系不明；"
                              "删掉其中一个键" % (min(i, j) + 1, max(i, j) + 1, _fmt(drive.values[i], drive.quantity)))
            notes.append("键 %d 和键 %d 两根骨的姿态相同，按一个键算" % (min(i, j) + 1, max(i, j) + 1))
            continue
        kept.append(i)
    return kept, notes


def _anchors(xs, ys):
    if len(xs) == 2:
        return (xs[0], (xs[0] + xs[1]) / 2.0, xs[1]), (ys[0], (ys[0] + ys[1]) / 2.0, ys[1])
    return tuple(xs), tuple(ys)


def _rest_warnings(plan, driver_rest, driven_rest, drive, order):
    x_rest = read_driver(Pose(), driver_rest, drive.read_mode, drive.axis, order)
    in_keys = any(abs(x_rest - v) <= CHANNEL_MIN[drive.quantity] for v in drive.values)
    off = []
    for c in plan.constraints:
        y = jcns_mapping.eval_piecewise(*c.from_anchors, *c.to_anchors, x_rest, two_point=not c.three_point)
        want = read_channel(Pose(), driven_rest, c.transform_type, c.axis, c.additive)[0]
        if abs(y - want) > REST_TOL:
            off.append("%s 输出 %s（应为 %s）" % (c.target_label(), _fmt(y, c.quantity), _fmt(want, c.quantity)))
    if not off:
        return
    if in_keys:
        plan.warnings.append("驱动骨在静止姿态的那个键里，被驱动骨却不在静止姿态，静止时%s" % "、".join(off))
    else:
        plan.warnings.append("静止姿态不在键里（驱动骨静止时读 %s），静止时%s。再记一个静止姿态的键"
                             % (_fmt(x_rest, drive.quantity), "、".join(off)))


def plan_keys(keys, driver_rest, driven_rest, read_mode=None, axis=None, euler_order=0,
              rotation_type=1):
    """The constraints `keys` (a list of Key) describe.

    `read_mode` (ReadMode value or identifier) and `axis` (0-2) force the driver's read;
    None picks it from what moved.  Rotations are written as additive TransformType
    `rotation_type` (1, 4, 5 or 6), so a bone at rest produces 0.
    Rejected (plan.errors, no constraints): fewer than 2 keys, more than MAX_KEYS, no
    driver or no driven movement, equal driver readings with different driven poses.
    Warnings do not block: rest pose outside the keys or off the rest value, channels
    that could not be read.
    """
    plan = Plan()
    try:
        _plan(plan, list(keys), driver_rest, driven_rest, read_mode, axis, euler_order, rotation_type)
    except _Reject as exc:
        plan.errors.append(str(exc))
        plan.constraints = []
    plan.ok = not plan.errors and bool(plan.constraints)
    return plan


def _plan(plan, keys, driver_rest, driven_rest, read_mode, axis, order, rotation_type):
    if rotation_type not in ROTATION_TYPES:
        raise _Reject("旋转目标的变换类型只能是 %s" % "、".join(map(str, ROTATION_TYPES)))
    if len(keys) < 2:
        raise _Reject("至少需要 2 个键（现有 %d 个）" % len(keys))
    drive = _detect_drive(keys, driver_rest, read_mode, axis, order)
    plan.drive = drive
    channels = _detect_channels(keys, driven_rest, rotation_type, plan.warnings)
    if not channels:
        raise _Reject("被驱动骨在各键之间没有变化")
    kept, notes = _dedupe(drive, channels)
    plan.warnings += notes
    if len(kept) > MAX_KEYS:
        raise _Reject("最多 %d 个键，更多需用 ComplexMapping" % MAX_KEYS)
    xs = [drive.values[i] for i in kept]
    for quantity, tt, ch_axis, values in channels:
        from_a, to_a = _anchors(xs, [values[i] for i in kept])
        plan.constraints.append(Constraint(
            transform_type=tt, axis=ch_axis, additive=True, quantity=quantity,
            read_mode=drive.read_mode, source_axis=drive.axis, euler_order=order,
            three_point=len(kept) == 3, from_anchors=from_a, to_anchors=to_a))
    _rest_warnings(plan, driver_rest, driven_rest, drive, order)


def describe(plan, driver_bone, driven_bone):
    """Lines for the panel: what the plan generates, or why it cannot."""
    if plan.errors:
        return list(plan.errors)
    lines = ["将生成 %d 条：" % len(plan.constraints)]
    lines += ["%s %s → %s %s" % (driver_bone, c.source_label(), driven_bone, c.target_label())
              for c in plan.constraints]
    return lines


# ---------------------------------------------------------------------------
# Landing on an existing file
# ---------------------------------------------------------------------------

def can_append(existing, constraint):
    """(ok, reason): may `constraint`'s source join the existing entry on its channel?

    `existing` is a dict with `additive`, `cone_infos`, `n_sources`, `property_hash`.  A source
    only adds to the entry's sum, so the entry must mean the same thing: the same Flags
    bit0 (scale ignores it), no ConeDriver inputs, room for one more source.
    """
    if existing.get('property_hash'):
        return False, "目标是材质或形变属性"
    if existing.get('cone_infos'):
        return False, "已有约束带 ConeDriver 输入，多源表达不了"
    if existing.get('n_sources', 0) >= MAX_SOURCES:
        return False, "已有约束的驱动源已满 %d 个" % MAX_SOURCES
    if constraint.transform_type != 2 and bool(existing.get('additive')) != bool(constraint.additive):
        return False, "已有约束的「叠加」与新约束不同"
    return True, ""


def main_change(pose, rest, order=0):
    """One phrase for the biggest way a driver pose differs from the rest pose,
    e.g. "扭转X 47.2°"; "静止姿态" when nothing moved.  A scale shows its reading."""
    for mode, quantity in _AUTO_READS:
        best = None
        for a in range(3):
            now = read_driver(pose, rest, mode, a, order)
            delta = now - read_driver(Pose(), rest, mode, a, order)
            if quantity == 'Rotation':
                delta = (delta + 180.0) % 360.0 - 180.0
            if best is None or abs(delta) > abs(best[1]):
                best = (a, delta, now)
        if abs(best[1]) > DRIVER_MIN[quantity]:
            shown = best[2] if quantity == 'Scale' else best[1]
            text = {'Rotation': "%.1f°", 'Translation': "%.2f cm", 'Scale': "%.3f"}[quantity] % shown
            return "%s %s" % (drive_label(mode, best[0]), text)
    return "静止姿态"
