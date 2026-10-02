"""
Set-driven-key planning: from recorded poses of a driver bone and its driven bones to
Ranges constraints.  Pure Python, no bpy.

A key is one recording: the raw pose snapshot of every bone recorded in it, by bone name.
Nothing about how a pose is read is decided at record time; plan_keys() picks the driver
quantity and each driven bone's channels from how the poses differ between keys, then turns
every driven channel into one entry with one source that maps the driver value to the
channel value.  Two keys give a two-point mapping, three a three-point mapping, four or more
a ComplexMapping curve with one keyframe per key.

The key list always holds a start key, an end key and any number of keys between them; a
key's name comes from its position (key_name).  The list order is authoritative, the
generated mapping follows the driver readings, and order_warnings() reports where they differ.

Driver values are what jcns_capture.capture_source reads (rest pose included), channel
values what jcns_capture.capture_target would have to write, so the anchors can be
stored as they are.  Units are the file's: degrees, centimetres, scale as is.
"""
import math
from dataclasses import dataclass, field

import jcns_capture as cap
import jcns_complex
import jcns_mapping
import jcns_source_read as sr
from jcns_i18n import T
from jcns_merge import MAX_SOURCES

MAX_KEYS = 3                     # more distinct keys than this become a ComplexMapping curve

# Driver quantity by priority: (read mode, quantity).  Rotation is read as swing-twist, the
# engine's most common read.
_AUTO_READS = ((3, 'Rotation'), (0, 'Translation'), (2, 'Scale'))

# Smallest spread across the keys that counts as the driver moving / a channel moving.
DRIVER_MIN = {'Rotation': 1.0, 'Translation': 0.1, 'Scale': 1e-3}
CHANNEL_MIN = {'Rotation': 0.05, 'Translation': 0.005, 'Scale': 1e-4}
# Driver readings closer than this are the same reading.
SAME_DRIVE = {'Rotation': 0.01, 'Translation': 0.001, 'Scale': 1e-5}
REST_TOL = 1e-4                  # output at rest vs the value that leaves the bone at rest
# Keyframes closer than this in x read back as a step (jcns_cm.step_gap's floor).
CM_MIN_GAP = 0.03

UNITS = {'Rotation': "°", 'Translation': " cm", 'Scale': ""}
ROTATION_TYPES = (1, 4, 5, 6)    # TransformTypes whose three channels are independent
TANGENTS = ('LINEAR', 'SMOOTH')


def _target_name(quantity):
    return T({'Rotation': "sdk.label.rotation", 'Translation': "sdk.label.translation",
              'Scale': "sdk.label.scale"}[quantity])


def _axis_label(base, axis):
    return T("sdk.label.axis", base, 'XYZ'[axis])


@dataclass(frozen=True)
class Pose:
    """A pose bone's basis: location (m), rotation quaternion (w, x, y, z), scale ratio."""
    loc: tuple = (0.0, 0.0, 0.0)
    quat: tuple = (1.0, 0.0, 0.0, 0.0)
    scale: tuple = (1.0, 1.0, 1.0)


@dataclass
class Key:
    """One recording.  A bone with no entry in `poses` was not recorded in this key."""
    poses: dict = field(default_factory=dict)


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
    values: list                 # the reading of each key that recorded the driver, in list order

    def label(self):
        return drive_label(self.read_mode, self.axis)


@dataclass
class Constraint:
    """One Ranges entry with one source.  Anchors are ascending in the driver value; a
    ComplexMapping constraint has all-zero anchors and `keys` [(x, y, slope_in, slope_out)]."""
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
    driven: str = ""
    keys: tuple = ()

    @property
    def complex(self):
        return bool(self.keys)

    def source_label(self):
        return drive_label(self.read_mode, self.source_axis)

    def target_label(self):
        return _axis_label(_target_name(self.quantity), self.axis)

    def evaluate(self, x):
        if self.keys:
            return jcns_complex.evaluate(list(self.keys), x)
        return jcns_mapping.eval_piecewise(*self.from_anchors, *self.to_anchors, x,
                                           two_point=not self.three_point)


@dataclass
class Plan:
    ok: bool = False
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    constraints: list = field(default_factory=list)
    drive: Drive = None
    mode: str = ""               # 'two', 'three' or 'complex'
    key_count: int = 0           # distinct keys the mapping is built from

    def bones(self):
        """Driven bones that get constraints, in the order they were asked for."""
        out = []
        for c in self.constraints:
            if c.driven not in out:
                out.append(c.driven)
        return out


class _Reject(Exception):
    def __init__(self, *reasons):
        super().__init__(reasons[0])
        self.reasons = list(reasons)


def drive_label(read_mode, axis):
    v = sr.read_mode_value(read_mode)
    if v in (3, 4):
        base = T("sdk.label.twist" if axis == 0 else "sdk.label.swing")
    else:
        base = T({0: "sdk.label.position", 1: "sdk.label.euler", 2: "sdk.label.scale",
                  5: "sdk.label.rotation_vector"}.get(v, "sdk.label.reading"))
    return _axis_label(base, axis)


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
# The key list: names, insertion, order, deletion
# ---------------------------------------------------------------------------

def key_name(index, count):
    """A key's name comes from its position: first = start, last = end, the rest numbered."""
    if index == 0:
        return T("sdk.key.start")
    if index == count - 1:
        return T("sdk.key.end")
    return T("sdk.key.middle", index)


def key_names(count):
    return [key_name(i, count) for i in range(count)]


def initial_keys():
    return [Key(), Key()]


def ensure_ends(keys):
    """Keep at least the start and end key; returns whether anything was added."""
    added = len(keys) < 2
    while len(keys) < 2:
        keys.append(Key())
    return added


def insert_key(keys):
    """A new key just before the end key, holding a copy of the end key's snapshots.
    Returns its index."""
    ensure_ends(keys)
    keys.insert(len(keys) - 1, Key(dict(keys[-1].poses)))
    return len(keys) - 2


def is_middle(index, count):
    return 0 < index < count - 1


def can_delete(index, count):
    """(ok, reason): only keys between the start and the end can go."""
    if not is_middle(index, count):
        return False, T("sdk.keys.cannot_delete_ends")
    return True, ""


def delete_key(keys, index):
    """Remove a middle key; returns the index to select afterwards (a middle key if any is left)."""
    ok, why = can_delete(index, len(keys))
    if not ok:
        raise ValueError(why)
    del keys[index]
    return min(index, len(keys) - 2)


def move_target(index, count, step):
    """Where a middle key lands when moved by `step` (+1 / -1), or None: the start and
    end key stay put, and nothing moves past them."""
    if step not in (-1, 1) or not is_middle(index, count) or not is_middle(index + step, count):
        return None
    return index + step


def move_key(keys, index, step):
    """Move a middle key one place; returns its new index, or None when it cannot move."""
    to = move_target(index, len(keys), step)
    if to is not None:
        keys[index], keys[to] = keys[to], keys[index]
    return to


def record(keys, index, bone, pose):
    keys[index].poses[bone] = pose


def forget_bone(keys, bone):
    """Drop a bone's snapshot from every key."""
    for k in keys:
        k.poses.pop(bone, None)


def order_warnings(entries, count, quantity):
    """Warnings for driver readings that disagree with the list order.

    `entries` is [(index in the key list, driver reading)] for the keys that recorded the
    driver.  A middle key should read between the start and the end key, and the keys should
    run from one end towards the other; generation sorts by reading either way.
    """
    names = key_names(count)
    by = dict(entries)
    tol = SAME_DRIVE[quantity]
    out, outside = [], set()
    if 0 in by and count - 1 in by:
        lo, hi = sorted((by[0], by[count - 1]))
        for i, v in entries:
            if is_middle(i, count) and not lo - tol <= v <= hi + tol:
                outside.add(i)
                out.append(T("sdk.warn.reading_outside", names[i], _fmt(v, quantity),
                             T("sdk.key.start"), _fmt(by[0], quantity),
                             T("sdk.key.end"), _fmt(by[count - 1], quantity)))
    rest = [(i, v) for i, v in entries if i not in outside]
    direction = 0
    if 0 in by and count - 1 in by and abs(by[count - 1] - by[0]) > tol:
        direction = 1 if by[count - 1] > by[0] else -1
    elif len(rest) > 1 and abs(rest[-1][1] - rest[0][1]) > tol:
        direction = 1 if rest[-1][1] > rest[0][1] else -1
    if direction:
        for (i, a), (j, b) in zip(rest, rest[1:]):
            if (b - a) * direction < -tol:
                out.append(T("sdk.warn.reading_reversed", names[j], _fmt(b, quantity),
                             names[i], _fmt(a, quantity)))
    if out:
        out.append(T("sdk.warn.order_mismatch"))
    return out


# ---------------------------------------------------------------------------
# Detecting what moved
# ---------------------------------------------------------------------------

def _detect_drive(poses, rest, read_mode, axis, order):
    if read_mode is None:
        reads = _AUTO_READS
    else:
        mode = sr.read_mode_value(read_mode)
        if sr.read_mode_id(mode) is None:
            raise _Reject(T("sdk.err.read_mode_unknown", read_mode))
        reads = ((mode, sr.read_quantity(mode)),)
    axes = range(3) if axis is None else (axis,)
    for mode, quantity in reads:
        best = None
        for a in axes:
            values = [read_driver(p, rest, mode, a, order) for p in poses]
            if best is None or _spread(values) > best[0] + 1e-12:
                best = (_spread(values), a, values)
        if best[0] > DRIVER_MIN[quantity]:
            return Drive(mode, best[1], quantity, best[2])
    if read_mode is None and axis is None:
        raise _Reject(T("sdk.err.drive_flat"))
    raise _Reject(T("sdk.err.drive_flat_mode" if read_mode is not None else "sdk.err.drive_flat_any"))


def _detect_channels(bone, poses, rest, rotation_type, warnings):
    """[(bone, quantity, transform type, axis, values)] for every channel of `bone` that
    differs between the keys."""
    found = []
    for quantity, tt in (('Rotation', rotation_type), ('Translation', 0), ('Scale', 2)):
        for axis in range(3):
            label = _axis_label(_target_name(quantity), axis)
            got = [read_channel(p, rest, tt, axis) for p in poses]
            if any(g is None for g in got):
                warnings.append(T("sdk.warn.channel_unreadable", bone, label))
                continue
            if quantity == 'Rotation' and max(g[1] for g in got) > 0.5:
                warnings.append(T("sdk.warn.rotation_unreachable", bone, label,
                                  max(g[1] for g in got)))
            values = [g[0] for g in got]
            if _spread(values) > CHANNEL_MIN[quantity]:
                found.append((bone, quantity, tt, axis, values))
    return found


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------

def _dedupe(drive, channels, names):
    """Positions in ascending driver order; keys with the same reading and the same channel
    values are one key, the same reading with different channel values is ambiguous."""
    same = SAME_DRIVE[drive.quantity]
    order = sorted(range(len(drive.values)), key=lambda i: drive.values[i])
    kept, notes = [], []
    for i in order:
        if kept and abs(drive.values[i] - drive.values[kept[-1]]) <= same:
            j = kept[-1]
            a, b = sorted((i, j))
            if any(abs(vals[i] - vals[j]) > CHANNEL_MIN[q] for _b, q, _tt, _a, vals in channels):
                raise _Reject(T("sdk.err.same_reading", names[a], names[b],
                                _fmt(drive.values[i], drive.quantity)))
            notes.append(T("sdk.note.same_pose", names[a], names[b]))
            continue
        kept.append(i)
    return kept, notes


def _anchors(xs, ys):
    if len(xs) == 2:
        return (xs[0], (xs[0] + xs[1]) / 2.0, xs[1]), (ys[0], (ys[0] + ys[1]) / 2.0, ys[1])
    return tuple(xs), tuple(ys)


def linear_tangents(xs, ys):
    """[(slope_in, slope_out)] that make every segment a straight line: each key takes the
    slopes of the segments on either side, the end keys the slope of their only segment."""
    d = [(ys[i + 1] - ys[i]) / (xs[i + 1] - xs[i]) for i in range(len(xs) - 1)]
    n = len(xs)
    return [(d[i - 1] if i > 0 else d[0], d[i] if i < n - 1 else d[n - 2]) for i in range(n)]


def _end_slope(h0, h1, d0, d1):
    m = ((2 * h0 + h1) * d0 - h0 * d1) / (h0 + h1)
    if m * d0 <= 0:
        return 0.0
    if d0 * d1 <= 0 and abs(m) > 3 * abs(d0):
        return 3 * d0
    return m


def smooth_tangents(xs, ys):
    """[(slope_in, slope_out)] of a monotone cubic through the points (PCHIP): flat where
    the data turns or stalls, never overshooting a segment's end values."""
    n = len(xs)
    h = [xs[i + 1] - xs[i] for i in range(n - 1)]
    d = [(ys[i + 1] - ys[i]) / h[i] for i in range(n - 1)]
    if n == 2:
        return [(d[0], d[0])] * 2
    m = [0.0] * n
    for i in range(1, n - 1):
        if d[i - 1] * d[i] > 0:
            w1, w2 = 2 * h[i] + h[i - 1], h[i] + 2 * h[i - 1]
            m[i] = (w1 + w2) / (w1 / d[i - 1] + w2 / d[i])
    m[0] = _end_slope(h[0], h[1], d[0], d[1])
    m[-1] = _end_slope(h[-1], h[-2], d[-1], d[-2])
    return [(s, s) for s in m]


def complex_keys(xs, ys, tangent='LINEAR'):
    """ComplexMapping keys [(x, y, slope_in, slope_out)] for ascending xs."""
    slopes = (smooth_tangents if tangent == 'SMOOTH' else linear_tangents)(xs, ys)
    return [(x, y, a, b) for x, y, (a, b) in zip(xs, ys, slopes)]


def _rest_warnings(plan, driver_rest, rests, drive, order):
    x_rest = read_driver(Pose(), driver_rest, drive.read_mode, drive.axis, order)
    in_keys = any(abs(x_rest - v) <= CHANNEL_MIN[drive.quantity] for v in drive.values)
    off = []
    for c in plan.constraints:
        y = c.evaluate(x_rest)
        want = read_channel(Pose(), rests[c.driven], c.transform_type, c.axis, c.additive)[0]
        if abs(y - want) > REST_TOL:
            off.append(T("sdk.warn.rest_output", c.driven, c.target_label(), _fmt(y, c.quantity),
                         _fmt(want, c.quantity)))
    if not off:
        return
    if in_keys:
        plan.warnings.append(T("sdk.warn.rest_off_in_keys", T("sdk.list_sep").join(off)))
    else:
        plan.warnings.append(T("sdk.warn.rest_not_in_keys", _fmt(x_rest, drive.quantity),
                               T("sdk.list_sep").join(off)))


def plan_keys(keys, driver, driven, rests, read_mode=None, axis=None, euler_order=0,
              rotation_type=1, tangent='LINEAR', complex_ok=True, complex_reason=""):
    """The constraints `keys` (a list of Key, start key first, end key last) describe.

    `driver` is the driver bone's name, `driven` the list of driven bone names, `rests` maps
    each of them to its BoneRest.  `read_mode` (InputType value or identifier) and `axis`
    (0-2) force the driver's read; None picks it from what moved.  Rotations are written as
    additive TransformElement `rotation_type` (1, 4, 5 or 6), so a bone at rest produces 0.
    `tangent` ('LINEAR' or 'SMOOTH') shapes a ComplexMapping curve.  `complex_ok` says
    whether the file can hold one, `complex_reason` why not.

    Rejected (plan.errors, no constraints): no driver or driven bone, a bone listed twice,
    fewer than 2 keys with the driver recorded, no driver movement, nothing moving in any
    driven bone, equal driver readings with different driven poses, more than MAX_KEYS
    distinct keys in a file without ComplexMapping.
    Warnings do not block: keys ignored for lacking the driver, driven bones skipped for
    lacking a snapshot in some key or for not moving, list order against readings, rest pose
    outside the keys or off the rest value, channels that could not be read.
    """
    plan = Plan()
    try:
        _plan(plan, list(keys), driver, list(driven), rests, read_mode, axis, euler_order,
              rotation_type, tangent, complex_ok, complex_reason)
    except _Reject as exc:
        plan.errors += exc.reasons
        plan.constraints = []
        plan.mode = ""
    plan.ok = not plan.errors and bool(plan.constraints)
    return plan


def _plan(plan, keys, driver, driven, rests, read_mode, axis, order, rotation_type, tangent,
          complex_ok, complex_reason):
    if rotation_type not in ROTATION_TYPES:
        raise _Reject(T("sdk.err.rotation_type", T("sdk.list_sep").join(map(str, ROTATION_TYPES))))
    if tangent not in TANGENTS:
        raise _Reject(T("sdk.err.tangent"))
    if not driver:
        raise _Reject(T("sdk.err.no_driver"))
    if not driven:
        raise _Reject(T("sdk.err.no_driven"))
    if driver in driven:
        raise _Reject(T("sdk.err.driver_is_driven", driver))
    for b in driven:
        if driven.count(b) > 1:
            raise _Reject(T("sdk.err.driven_duplicate", b))
    for b in [driver] + driven:
        if b not in rests:
            raise _Reject(T("sdk.err.no_rest", b))
    if len(keys) < 2:
        raise _Reject(T("sdk.err.too_few_keys", len(keys)))

    names = key_names(len(keys))
    kept = [i for i, k in enumerate(keys) if driver in k.poses]
    if len(kept) < len(keys):
        plan.warnings.append(T("sdk.warn.keys_without_driver",
                               T("sdk.list_sep").join(names[i] for i in range(len(keys)) if i not in kept),
                               driver))
    if len(kept) < 2:
        raise _Reject(T("sdk.err.too_few_driver_keys", len(kept)))

    drive = _detect_drive([keys[i].poses[driver] for i in kept], rests[driver], read_mode, axis, order)
    plan.drive = drive
    plan.warnings += order_warnings(list(zip(kept, drive.values)), len(keys), drive.quantity)

    channels, skips = [], []
    for b in driven:
        missing = [names[i] for i in kept if b not in keys[i].poses]
        if len(missing) == len(kept):
            skips.append((b, T("sdk.skip.no_pose")))
        elif missing:
            skips.append((b, T("sdk.skip.missing_in", T("sdk.list_sep").join(missing))))
        else:
            found = _detect_channels(b, [keys[i].poses[b] for i in kept], rests[b], rotation_type,
                                     plan.warnings)
            if not found:
                skips.append((b, T("sdk.skip.no_change")))
            channels += found
    if not channels:
        raise _Reject(*[T("sdk.err.driven_skip", *s) for s in skips])
    plan.warnings += [T("sdk.warn.driven_skip", *s) for s in skips]

    pos, notes = _dedupe(drive, channels, [names[i] for i in kept])
    plan.warnings += notes
    xs = [drive.values[p] for p in pos]
    plan.key_count = len(pos)
    if len(pos) > MAX_KEYS:
        if not complex_ok:
            raise _Reject(T("sdk.err.curve_not_editable", len(pos),
                            complex_reason or T("sdk.err.curve_not_editable_default"), MAX_KEYS))
        plan.mode = 'complex'
        for a, b in zip(pos, pos[1:]):
            if drive.values[b] - drive.values[a] < CM_MIN_GAP:
                plan.warnings.append(T("sdk.warn.step_gap", names[kept[a]], names[kept[b]],
                                       _fmt(drive.values[b] - drive.values[a], drive.quantity)))
    else:
        plan.mode = 'two' if len(pos) == 2 else 'three'
    for bone, quantity, tt, ch_axis, values in channels:
        ys = [values[p] for p in pos]
        if plan.mode == 'complex':
            from_a = to_a = (0.0, 0.0, 0.0)
            cm = tuple(complex_keys(xs, ys, tangent))
        else:
            from_a, to_a = _anchors(xs, ys)
            cm = ()
        plan.constraints.append(Constraint(
            transform_type=tt, axis=ch_axis, additive=True, quantity=quantity,
            read_mode=drive.read_mode, source_axis=drive.axis, euler_order=order,
            three_point=plan.mode != 'two', from_anchors=from_a, to_anchors=to_a,
            driven=bone, keys=cm))
    _rest_warnings(plan, rests[driver], rests, drive, order)


def describe_rows(plan, driver_bone):
    """[(kind, text)] for the panel: what the plan generates, or why it cannot.
    kind is 'error', 'head', 'bone' or 'line'."""
    if plan.errors:
        return [('error', t) for t in plan.errors]
    how = (T("sdk.mode.complex", plan.key_count) if plan.mode == 'complex'
           else T("sdk.mode." + plan.mode))
    rows = [('head', T("sdk.describe.head", len(plan.constraints), how))]
    for bone in plan.bones():
        mine = [c for c in plan.constraints if c.driven == bone]
        rows.append(('bone', T("sdk.describe.bone", bone, len(mine))))
        rows += [('line', "%s %s → %s %s" % (driver_bone, c.source_label(), bone, c.target_label()))
                 for c in mine]
    return rows


def describe(plan, driver_bone):
    return [text for _kind, text in describe_rows(plan, driver_bone)]


# ---------------------------------------------------------------------------
# Landing on an existing file
# ---------------------------------------------------------------------------

def can_append(existing, constraint, complex_ok=True):
    """(ok, reason): may `constraint`'s source join the existing entry on its channel?

    `existing` is a dict with `additive`, `cone_infos`, `n_sources`, `target_property`.  A source
    only adds to the entry's sum, so the entry must mean the same thing: the same AttrFlags
    bit0 (scale ignores it), no ConeDriver inputs, room for one more source.  A ComplexMapping
    source also needs a file that can hold ComplexMapping.
    """
    if existing.get('target_property') or existing.get('property_hash'):
        return False, T("sdk.append.property_target")
    if existing.get('cone_infos'):
        return False, T("sdk.append.cone_driver")
    if existing.get('n_sources', 0) >= MAX_SOURCES:
        return False, T("sdk.append.sources_full", MAX_SOURCES)
    if constraint.transform_type != 2 and bool(existing.get('additive')) != bool(constraint.additive):
        return False, T("sdk.append.additive_differs")
    if constraint.complex and not complex_ok:
        return False, T("sdk.append.no_complex")
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
    return T("sdk.rest_pose")
