"""
jxg_eval.py
-----------
Evaluate a JointExprGraph (a jxg_format graph dict) against a skeleton at a time.

The graph runs its root nodes in list order; each pulls the nodes it reads, once
per evaluation.  A Set node writes its joint's local transform into the skeleton
at once, so a later read of that joint, or of a child in global space, sees it.

Joint values are game space: positions in metres (a node's CoordUnit picks metres
or centimetres for what it reads and writes), rotations as quaternions (w, x, y, z).

How each node computes was read off the game's own code (the node classes' vtables:
setInt/setFloat/... store a slot into a field, getFloat/update compute from the fields;
docs/jntexprgraph.md lists them).  What stays modelled here:
  * the time step: the engine advances its timers by the frame time; the preview by the
    timeline step (see `evaluate`), restarting at t mod period when there is no state;
  * a Joint node's LOD threshold (slot 1) is ignored, the node always runs, and a layer
    BlendRate below 1 (the engine slerps / lerps towards the result) is taken as 1;
  * a float linked into a bool slot reads true when it is not ~0.

Nodes outside the list below (C# nodes, Ziva, KeyFrameCurve, MaEulerConstraint,
JointDriverFloat...) output zeros; `Result.unsupported` names them.
"""

import math
import struct

from jcns_source_read import _euler, from_euler_order

ZERO3 = (0.0, 0.0, 0.0)
IDQ = (1.0, 0.0, 0.0, 0.0)
TAU = 2.0 * math.pi
EPS = 1.1920929e-07                     # FLT_EPSILON, the engine's "~0" in these nodes


# ------------------------------------------------------------------ quaternion math

def qmul(a, b):
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return (aw * bw - ax * bx - ay * by - az * bz,
            aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw)


def qconj(q):
    return (q[0], -q[1], -q[2], -q[3])


def qnorm(q):
    n = math.sqrt(sum(c * c for c in q)) or 1.0
    return tuple(c / n for c in q)


def qrot(q, v):
    return qmul(qmul(q, (0.0,) + tuple(v)), qconj(q))[1:]


def qaxis(axis, angle):
    s = math.sin(angle / 2.0)
    v = [0.0, 0.0, 0.0]
    v[axis] = s
    return (math.cos(angle / 2.0), v[0], v[1], v[2])


def qslerp(a, b, t):
    d = sum(x * y for x, y in zip(a, b))
    if d < 0:
        b, d = tuple(-c for c in b), -d
    if d > 0.9995:
        return qnorm(tuple(x + (y - x) * t for x, y in zip(a, b)))
    th = math.acos(d)
    s = math.sin(th)
    wa, wb = math.sin((1 - t) * th) / s, math.sin(t * th) / s
    return tuple(wa * x + wb * y for x, y in zip(a, b))


def compose(order, v):
    """A rotation from Euler angles (x, y, z, radians) in a RotOrder, as the engine's converter does
    (the same one JCNS joint groups use): 0 XYZ R = Rz*Ry*Rx, 1 YZX, 2 ZXY, 3 ZYX, 4 YXZ, 5 XZY."""
    return qnorm(from_euler_order(v, order))


def decompose(order, q):
    """Euler angles (x, y, z, radians) of `q` in a RotOrder."""
    return tuple(_euler(qnorm(q), order))


def _matrix(q):
    w, x, y, z = q
    return ((1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)),
            (2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)),
            (2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)))


# ------------------------------------------------------------------ skeleton

class Skeleton:
    """Joints by name hash: parent hash, rest local (pos, quat), current local (pos, quat).

    `origin` is the world transform the root joints hang from.  World transforms follow
    the parent chain and update when a joint is set.
    """

    def __init__(self, joints, origin=(ZERO3, IDQ)):
        self.parent = {h: j[0] for h, j in joints.items()}
        self.rest = {h: (tuple(j[1]), tuple(j[2])) for h, j in joints.items()}
        self.local = {h: (tuple(j[3]), tuple(j[4])) for h, j in joints.items()}
        self.origin = origin
        self._world = {}

    def __contains__(self, h):
        return h in self.local

    def world(self, h):
        if h not in self._world:
            p = self.parent.get(h)
            ppos, pq = self.world(p) if p in self.local else self.origin
            pos, q = self.local[h]
            self._world[h] = (tuple(a + b for a, b in zip(ppos, qrot(pq, pos))), qnorm(qmul(pq, q)))
        return self._world[h]

    def parent_world(self, h):
        p = self.parent.get(h)
        return self.world(p) if p in self.local else self.origin

    def set_local(self, h, pos=None, q=None):
        old_pos, old_q = self.local[h]
        self.local[h] = (tuple(pos) if pos is not None else old_pos, qnorm(q) if q is not None else old_q)
        self._world.clear()


class Result:
    def __init__(self):
        self.writes = {}              # hash -> (pos or None, quat or None), last write per channel wins
        self.unsupported = set()      # node types that evaluated to zeros
        self.missing_joints = set()   # hashes a node names that the skeleton lacks


# ------------------------------------------------------------------ values

_DEFAULT = {'float': 0.0, 'int': 0, 'bool': False, 'vec3': ZERO3, 'quat': IDQ, 'any': 0.0}


# A number reads as true when it is not ~0.  Reading a bone's pose off Blender's matrices
# leaves noise of ~1e-7 where the game has an exact 0, so an exact test would never be false.
BOOL_EPS = 1e-4


def convert(v, to):
    """A value as another slot type, as the engine's links between types do (modelled)."""
    if to in ('any', None):
        return v
    if isinstance(v, bool) or isinstance(v, (int, float)):
        f = float(v)
        return {'float': f, 'int': int(f), 'bool': abs(f) > BOOL_EPS, 'vec3': (f, f, f), 'quat': IDQ}.get(to, f)
    if len(v) == 3:
        return {'float': v[0], 'int': int(v[0]), 'bool': any(abs(c) > BOOL_EPS for c in v), 'vec3': tuple(v),
                'quat': compose(2, v)}.get(to, v)
    return {'quat': tuple(v), 'vec3': decompose(2, v), 'float': v[0], 'bool': True}.get(to, v)


def _unit(n):
    return 100.0 if n == 0 else 1.0          # CoordUnit 0 centimetres, 1 metres


def _angle_unit(n):
    return 180.0 / math.pi if n == 1 else 1.0   # RotUnit 0 radians, 1 degrees


def _ease(kind, t):
    """via.curve.EaseType (Robert Penner's set) at t in [0, 1]."""
    if kind == 0:
        return t
    family, mode = divmod(kind - 1, 3)            # mode 0 In, 1 Out, 2 InOut
    f = _EASE_IN[family] if family < len(_EASE_IN) else (lambda x: x)
    if mode == 0:
        return f(t)
    if mode == 1:
        return 1.0 - f(1.0 - t)
    return f(2 * t) / 2 if t < 0.5 else 1.0 - f(2 - 2 * t) / 2


def _back(x):
    c = 1.70158
    return (c + 1) * x ** 3 - c * x * x


def _elastic(x):
    if x <= 0.0 or x >= 1.0:
        return x
    return -(2 ** (10 * x - 10)) * math.sin((10 * x - 10.75) * TAU / 3)


def _bounce_out(x):
    n, d = 7.5625, 2.75
    if x < 1 / d:
        return n * x * x
    if x < 2 / d:
        x -= 1.5 / d
        return n * x * x + 0.75
    if x < 2.5 / d:
        x -= 2.25 / d
        return n * x * x + 0.9375
    x -= 2.625 / d
    return n * x * x + 0.984375


# In-curves of Sine, Quad, Cubic, Quart, Quint, Expo, Circ, Back, Elastic, Bounce (EaseType 1..30)
_EASE_IN = (lambda x: 1 - math.cos(x * math.pi / 2), lambda x: x * x, lambda x: x ** 3, lambda x: x ** 4,
            lambda x: x ** 5, lambda x: 0.0 if x <= 0 else 2 ** (10 * x - 10),
            lambda x: 1 - math.sqrt(max(0.0, 1 - x * x)), _back, _elastic, lambda x: 1 - _bounce_out(1 - x))


def _float_map(x, a, b, c, d, clamp):
    """FloatMap: c when the input range is empty; the input clamped to [a, b] when asked."""
    if a == b:
        return c
    if clamp:
        x = a if x < a else min(x, b)
    return (x - a) / (b - a) * (d - c) + c


# MaFloatRemap interpolation (slot 3)
_SEGMENT = {1: lambda t: t ** 3, 2: lambda t: 1 - (1 - t) ** 3, 3: lambda t: 3 * t * t - 2 * t ** 3}


def _segment(x, a, b, c, d, kind):
    if b - a <= EPS:
        return 0.0
    t = min(1.0, max(0.0, (x - a) / (b - a)))
    return c + (d - c) * _SEGMENT.get(kind, lambda t: t)(t)


def _remap3(x, i, o, kind, use_mid):
    """MaFloatRemap: below the low point the low output, above the high point the high one,
    between them one segment, or two split at the mid point when `use_mid`.  A descending
    input range is turned round, outputs with it."""
    lo, mid, hi = i
    olo, omid, ohi = o
    if (mid if use_mid else hi) <= lo and not (use_mid and mid > hi):
        lo, hi, olo, ohi = hi, lo, ohi, olo
    if x <= lo:
        return olo
    if x >= hi:
        return ohi
    if use_mid:
        return _segment(x, lo, mid, olo, omid, kind) if x <= mid else _segment(x, mid, hi, omid, ohi, kind)
    return _segment(x, lo, hi, olo, ohi, kind)


# ------------------------------------------------------------------ evaluation

class _Eval:
    def __init__(self, G, skel, t, state=None, dt=0.0):
        self.G, self.skel, self.t = G, skel, t
        self.state, self.dt = state, dt
        self.cache = {}
        self.res = Result()

    def timer(self, i, period):
        """The node's time within its period, or None while the period is ~0 (then it holds).

        The engine adds the frame time each update and subtracts the period while the sum
        reaches it; without state the preview starts at t mod period."""
        if period <= EPS:
            return None
        if self.state is None:
            return math.fmod(self.t, period)
        key = self.G['nodes'][i]['guid']
        prev = self.state.get(key)
        value = math.fmod(self.t, period) if prev is None else math.fmod(prev + self.dt, period)
        self.state[key] = value
        return value

    def inp(self, i, slot, vtype):
        nd = self.G['nodes'][i]
        for l in nd['inputs']:
            if l['dst_slot'] == slot:
                outs = self.node(l['src'])
                return convert(outs.get(l['src_slot'], _DEFAULT.get(l['src_type'], 0.0)), vtype)
        for s, t, v in nd['props']:
            if s == slot:
                return convert(v, vtype) if t != 'int' or vtype != 'int' else v
        return _DEFAULT[vtype]

    def has(self, i, slot):
        nd = self.G['nodes'][i]
        return any(l['dst_slot'] == slot for l in nd['inputs']) or any(p[0] == slot for p in nd['props'])

    def joint(self, i):
        h = self.inp(i, 0, 'int') & 0xFFFFFFFF
        if h not in self.skel:
            self.res.missing_joints.add(h)
            return None
        return h

    def node(self, i):
        if i not in self.cache:
            self.cache[i] = {}                       # a loop reads zeros instead of recursing forever
            self.cache[i] = self.compute(i)
        return self.cache[i]

    # -- joints

    def _read(self, h, space):
        if space == 1:
            return self.skel.world(h)
        pos, q = self.skel.local[h]
        if space == 2:
            rpos, rq = self.skel.rest[h]
            return tuple(a - b for a, b in zip(pos, rpos)), qmul(qconj(rq), q)
        return pos, q

    def get_position(self, i):
        h = self.joint(i)
        if h is None:
            return {10: ZERO3, 20: 0.0, 21: 0.0, 22: 0.0}
        k = _unit(self.inp(i, 5, 'int'))
        p = tuple(c * k for c in self._read(h, self.inp(i, 2, 'int'))[0])
        return {10: p, 20: p[0], 21: p[1], 22: p[2]}

    def get_rotation(self, i):
        h = self.joint(i)
        if h is None:
            return {11: IDQ, 13: ZERO3, 20: 0.0, 21: 0.0, 22: 0.0}
        q = self._read(h, self.inp(i, 2, 'int'))[1]
        k = _angle_unit(self.inp(i, 6, 'int'))
        e = tuple(c * k for c in decompose(self.inp(i, 3, 'int'), q))
        return {11: q, 13: e, 20: e[0], 21: e[1], 22: e[2]}

    def set_position(self, i):
        h = self.joint(i)
        if h is None:
            return {}
        space, k = self.inp(i, 2, 'int'), _unit(self.inp(i, 5, 'int'))
        cur = list(self._read(h, space)[0])
        cur = [c * k for c in cur]
        if self.has(i, 10):
            cur = list(self.inp(i, 10, 'vec3'))
        for axis in range(3):
            if self.has(i, 20 + axis):
                cur[axis] = self.inp(i, 20 + axis, 'float')
        p = tuple(c / k for c in cur)
        if space == 1:
            ppos, pq = self.skel.parent_world(h)
            p = qrot(qconj(pq), tuple(a - b for a, b in zip(p, ppos)))
        elif space == 2:
            p = tuple(a + b for a, b in zip(self.skel.rest[h][0], p))
        self.skel.set_local(h, pos=p)
        self._record(h, pos=p)
        return {}

    def set_rotation(self, i):
        h = self.joint(i)
        if h is None:
            return {}
        space, order = self.inp(i, 2, 'int'), self.inp(i, 3, 'int')
        if self.has(i, 11):
            q = self.inp(i, 11, 'quat')
        else:
            # unfed components keep the joint's current angles in this space and order; for
            # LocalDiffBase the engine decomposes the inverse rest rotation, not the pose
            k = _angle_unit(self.inp(i, 6, 'int'))
            if self.has(i, 13):
                v = list(self.inp(i, 13, 'vec3'))
            else:
                cur = qconj(self.skel.rest[h][1]) if space == 2 else self._read(h, space)[1]
                v = [c * k for c in decompose(order, cur)]
                for axis in range(3):
                    if self.has(i, 20 + axis):
                        v[axis] = self.inp(i, 20 + axis, 'float')
            q = compose(order, [c / k for c in v])
        if space == 1:
            q = qmul(qconj(self.skel.parent_world(h)[1]), q)
        elif space == 2:
            q = qmul(self.skel.rest[h][1], q)
        self.skel.set_local(h, q=q)
        self._record(h, q=q)
        return {}

    def _record(self, h, pos=None, q=None):
        old = self.res.writes.get(h, (None, None))
        self.res.writes[h] = (pos if pos is not None else old[0], q if q is not None else old[1])

    def local_coord(self, i):
        h = self.joint(i)
        if h is None:
            return {10: ZERO3, 11: IDQ, 12: (1.0, 1.0, 1.0)}
        pos, q = self.skel.local[h]
        return {10: tuple(c * 100.0 for c in pos), 11: q, 12: (1.0, 1.0, 1.0)}

    def cyclic(self, i, wave):
        """CyclicalAngle (wave None): 2 pi * time / period.  Sin/Cos/SawToothWave (period, A, B):
        A + (B - A) * (1 + sin|cos(2 pi * time / period)) / 2, or A + (B - A) * time / period."""
        period = self.inp(i, 1, 'float')
        tm = self.timer(i, period)
        if tm is None:
            return 0.0
        frac = min(1.0, max(0.0, tm / period))
        if wave is None:
            return TAU * frac
        a, b = self.inp(i, 2, 'float'), self.inp(i, 3, 'float')
        if abs(b - a) <= EPS:
            return b
        if wave == 'saw':
            return a + (b - a) * frac
        return a + (b - a) * 0.5 * (1.0 + wave(TAU * frac))

    # -- everything else

    def compute(self, i):
        nd = self.G['nodes'][i]
        short = nd['type'].rsplit('.', 1)[-1]
        f = lambda s: self.inp(i, s, 'float')
        v3 = lambda s: self.inp(i, s, 'vec3')
        qq = lambda s: self.inp(i, s, 'quat')
        t = self.t
        if short == 'JointGetPositionNode':
            return self.get_position(i)
        if short == 'JointGetRotationNode':
            return self.get_rotation(i)
        if short == 'JointSetPositionNode':
            return self.set_position(i)
        if short == 'JointSetRotationNode':
            return self.set_rotation(i)
        if short == 'JointGetLocalCoordNode':
            return self.local_coord(i)
        simple = {
            'FloatValueNode': lambda: f(0),
            'FloatAddNode': lambda: f(0) + f(1),
            'FloatSubNode': lambda: f(0) - f(1),
            'FloatMulNode': lambda: f(0) * f(1),
            'FloatDivNode': lambda: f(0) / f(1) if f(1) else 0.0,
            'FloatMinNode': lambda: min(f(0), f(1)),
            'FloatAbsNode': lambda: abs(f(1)),
            'FloatClampNode': lambda: min(max(f(0), f(1)), f(2)),
            'CosNode': lambda: math.cos(f(1)),
            'Rad2DegNode': lambda: math.degrees(f(1)),
            'FloatSwitchNode': lambda: f(2) if self.inp(i, 0, 'bool') else f(1),
            'FloatMapNode': lambda: _float_map(f(0), f(1), f(2), f(3), f(4), self.inp(i, 5, 'bool')),
            'CyclicalAngleNode': lambda: self.cyclic(i, None),
            'SinWaveNode': lambda: self.cyclic(i, math.sin),
            'CosWaveNode': lambda: self.cyclic(i, math.cos),
            'SawToothWaveNode': lambda: self.cyclic(i, 'saw'),
            'Vec3ValueNode': lambda: v3(0),
            'Vec3AddNode': lambda: tuple(a + b for a, b in zip(v3(0), v3(1))),
            'Vec3SubNode': lambda: tuple(a - b for a, b in zip(v3(0), v3(1))),
            'Vec3MulNode': lambda: tuple(a * b for a, b in zip(v3(0), v3(1))),
            'Vec3NormalizeNode': lambda: _normalize(v3(0)),
            'Vec3TransformNode': lambda: qrot(qq(1), v3(0)),
            'Float3ToVec3Node': lambda: (f(1), f(2), f(3)),
            'QuatValueNode': lambda: qq(0),
            'QuatMulNode': lambda: qnorm(qmul(qq(0), qq(1))),
            'QuatInverseNode': lambda: qconj(qq(0)),
            'QuatSlerpNode': lambda: qslerp(qq(0), qq(1), f(2)),
        }
        if short in simple:
            return {0: simple[short]()}
        if short == 'FloatSumNode':
            return {0: sum(f(11 + k) for k in range(self.inp(i, 1, 'int')))}
        if short == 'Vec3ToFloat3Node':
            v = v3(0)
            return {1: v[0], 2: v[1], 3: v[2]}
        if short == 'QuatToEulerFloat3Node':
            e = decompose(self.inp(i, 4, 'int'), qq(3))
            return {0: e[0], 1: e[1], 2: e[2]}
        if short == 'FloatEaseCurveNode':
            kind = struct.unpack('<I', nd['extra'][:4])[0] if len(nd.get('extra', b'')) >= 4 else 0
            x = min(1.0, max(0.0, f(2)))
            return {0: f(0) + (f(1) - f(0)) * _ease(kind, x)}
        if short == 'MaFloatRemapNode':
            return {0: _remap3(f(0), v3(1), v3(2), self.inp(i, 3, 'int'), self.inp(i, 4, 'bool'))}
        if short == 'FloatMathCodeNode':
            return {0: _math_code(nd.get('extra', b''), lambda k: f(10 + k))}
        self.res.unsupported.add(short)
        return {s: _DEFAULT.get(t, 0.0) for s, t in nd['outputs']}


def _normalize(v):
    n = math.sqrt(sum(c * c for c in v))
    return tuple(c / n for c in v) if n > 1e-12 else ZERO3


def _math_code(code, var):
    """FloatMathCodeNode's reverse-Polish program: 02 n 00 reads input n, 01 <f32> pushes
    a constant, 04 op applies a binary operator (1 add, 2 sub, 3 mul, 4 div)."""
    stack, k = [], 0
    try:
        while k < len(code):
            op = code[k]
            if op == 1:
                stack.append(struct.unpack_from('<f', code, k + 1)[0])
                k += 5
            elif op == 2:
                stack.append(var(code[k + 1] | code[k + 2] << 8))
                k += 3
            elif op == 4:
                b, a = stack.pop(), stack.pop()
                stack.append({1: a + b, 2: a - b, 3: a * b, 4: a / b if b else 0.0}.get(code[k + 1], 0.0))
                k += 2
            else:
                break
    except (IndexError, struct.error):
        pass
    return stack[-1] if stack else 0.0


def evaluate(G, skel, t, state=None, dt=0.0):
    """Run the graph's roots in order at time `t` (seconds); the skeleton is updated in place.

    `state` (a dict, node guid -> phase) makes the time nodes advance by `dt` seconds from
    where the last call left them; the caller keeps it between frames.
    """
    ev = _Eval(G, skel, t, state, dt)
    for r, _flags in G['roots']:
        if 0 <= r < len(G['nodes']):
            ev.node(r)
    return ev.res
