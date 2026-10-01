"""
jcns_preview_plan.py
--------------------
Turn a Skin / Aim / RotExpression entry into a description of the native Blender
pose-bone constraint that previews it (the counterpart of the Ranges driver).

Pure data in, pure data out: jcns_preview.ConstraintBackend only creates the
constraint a plan describes, so the choice of constraint, axis and warnings is
testable offline.  These sections' semantics are inferred, so a plan is a
preview of that reading, not a claim about the engine; its warnings list what
it leaves out.
"""

import math
from dataclasses import dataclass, field

CON_NAME = {'Skin': "JCNS Skin", 'Aim': "JCNS Aim", 'RotExpression': "JCNS RotExpr"}


@dataclass
class ConstraintPlan:
    ok: bool
    reason: str = ''                 # why there is no preview (when not ok)
    warnings: list = field(default_factory=list)
    bone: str = ''                   # pose bone that owns the constraint
    name: str = ''                   # constraint name on that bone
    con_type: str = ''               # Blender constraint type id
    props: dict = field(default_factory=dict)      # plain values to set on it
    target: str = ''                 # subtarget of a single-target constraint
    targets: tuple = ()              # ((bone, weight), ...) for an ARMATURE constraint


def _no(reason):
    return ConstraintPlan(False, reason)


# ── Skin ────────────────────────────────────────────────────────────────────

def plan_skin(object_bone, sources):
    """Pin `object_bone` to the skin: an Armature constraint that blends the
    source bones' deformation by weight, which is what a skinned vertex does.
    Position matches the engine (linear blend, weights divided by their sum); the
    engine blends rotation as a normalized quaternion sum, Blender as a matrix sum.

    sources: [(bone_name, weight), ...]
    """
    if not object_bone:
        return _no("没有对象骨骼")
    warnings = []
    targets = []
    for bone, w in sources:
        if not bone:
            warnings.append("有一条驱动没填，已忽略")
        elif bone == object_bone:
            warnings.append("驱动里含被驱动自己，已忽略")
        else:
            targets.append((bone, float(w)))
    if not targets:
        return _no("没有可用的驱动")
    # The engine divides by the weight sum (measured, round 12), Blender's Armature
    # constraint does not.
    total = sum(w for _, w in targets)
    if total > 0:
        targets = [(b, w / total) for b, w in targets]
    return ConstraintPlan(
        True, warnings=warnings, bone=object_bone, name=CON_NAME['Skin'],
        con_type='ARMATURE', targets=tuple(targets),
        props={'use_deform_preserve_volume': False, 'use_bone_envelopes': False})


# ── Aim ─────────────────────────────────────────────────────────────────────

_AXES = ('X', 'Y', 'Z')


def aim_track_axis(vec):
    """'TRACK_X' / 'TRACK_NEGATIVE_Z' / ... for an axis-aligned vector, else ''."""
    n = math.sqrt(sum(c * c for c in vec))
    if n < 1e-6:
        return ''
    for i, c in enumerate(vec):
        if abs(c) >= 0.999 * n:
            return "TRACK_%s%s" % ('NEGATIVE_' if c < 0 else '', _AXES[i])
    return ''


def plan_aim(bone, target, vec1, influence, up_bone='', rotation_type=4, offset=(0.0, 0.0, 0.0)):
    """Aim `bone` at `target`: a Damped Track along the record's aim axis (Vec1).

    Damped Track is the shortest-arc turn from the rest pose, which is what
    RotationType 4 does.  Types 0-3 also fix the roll around the aim axis, and
    type 5 drops the rest pose, so the preview differs; the up bone is not previewed.
    """
    if not bone:
        return _no("没有被瞄准的骨骼")
    if not target:
        return _no("没有瞄准目标")
    if bone == target:
        return _no("被瞄准的骨骼和瞄准目标是同一根")
    axis = aim_track_axis(vec1)
    if not axis:
        return _no("瞄准轴 (%.2f, %.2f, %.2f) 不是坐标轴，Blender 的阻尼追踪表示不了"
                   % tuple(vec1))
    warnings = []
    if rotation_type == 5:
        warnings.append("类型 5 从父骨朝向起最短弧（丢掉静止姿态），预览从静止姿态起，会差静止姿态")
    elif rotation_type != 4:
        warnings.append("类型 %d 的引擎行为还会固定绕瞄准轴的翻滚，预览只做最短弧，翻滚会不同" % rotation_type)
    if any(abs(c) > 1e-6 for c in offset):
        warnings.append("旋转偏移不参与预览")
    if up_bone:
        warnings.append("辅助骨骼（up）不参与预览")
    infl = min(1.0, max(0.0, float(influence)))
    if infl != influence:
        warnings.append("影响 %.2f 超出 0..1，预览按 %.0f 处理" % (influence, infl))
    elif abs(infl - 1.0) > 1e-6:
        warnings.append("影响不为 1 时引擎的结果退化，预览按影响直接混合")
    return ConstraintPlan(
        True, warnings=warnings, bone=bone, name=CON_NAME['Aim'],
        con_type='DAMPED_TRACK', target=target,
        props={'track_axis': axis, 'influence': infl})


# ── RotExpression ───────────────────────────────────────────────────────────

def plan_rot(bone, source, coeffs):
    """Copy `source`'s local rotation onto `bone`, each Euler axis times its
    coefficient: a Transformation constraint mapping rotation to rotation.
    """
    if not bone:
        return _no("没有被驱动的骨骼")
    if not source:
        return _no("没有驱动")
    if bone == source:
        return _no("被驱动和驱动是同一根")
    props = {
        'map_from': 'ROTATION', 'map_to': 'ROTATION',
        'from_rotation_mode': 'AUTO', 'to_euler_order': 'AUTO',
        'mix_mode_rot': 'REPLACE',
        'owner_space': 'LOCAL', 'target_space': 'LOCAL',
        'use_motion_extrapolate': True,
    }
    for axis, k in zip('xyz', coeffs):
        props['map_to_%s_from' % axis] = axis.upper()
        props['from_min_%s_rot' % axis] = -math.pi
        props['from_max_%s_rot' % axis] = math.pi
        props['to_min_%s_rot' % axis] = -math.pi * k
        props['to_max_%s_rot' % axis] = math.pi * k
    return ConstraintPlan(
        True, bone=bone, name=CON_NAME['RotExpression'],
        con_type='TRANSFORM', target=source, props=props)
