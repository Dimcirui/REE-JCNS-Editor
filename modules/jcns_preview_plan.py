"""
jcns_preview_plan.py
--------------------
Turn a Skin / Aim / RotExpression entry into a description of the native Blender
pose-bone constraint that shows what it does, so the result can be seen in the
viewport (the counterpart of the driver the Ranges section gets).

Pure data in, pure data out: the Blender side (jcns_preview.ConstraintBackend)
only has to create the constraint a plan describes.  That keeps the decisions -
which constraint, which axis, what to warn about - testable offline.

None of these is a claim about the engine.  The sections' semantics are
inferred, not measured (see docs/memory/jcns-section-semantics.md); a preview is a
way to *look at* the hypothesis and compare it with the game.  Each plan says
what it left out.
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

    sources: [(bone_name, weight), ...]
    """
    if not object_bone:
        return _no("没有对象骨骼")
    warnings = []
    targets = []
    for bone, w in sources:
        if not bone:
            warnings.append("有一条源骨骼没填，已忽略")
        elif bone == object_bone:
            warnings.append("源骨骼包含对象骨骼自己，已忽略")
        else:
            targets.append((bone, float(w)))
    if not targets:
        return _no("没有可用的源骨骼")
    total = sum(w for _, w in targets)
    if abs(total - 1.0) > 1e-3:
        warnings.append("权重和 %.3f（Blender 不会归一化）" % total)
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


def plan_aim(bone, target, vec1, influence, up_bone=''):
    """Aim `bone` at `target`: a Damped Track along the record's aim axis (Vec1).

    The up bone and the other vectors are not previewed; Vec1 being the aim axis
    is the strongest reading of the data (mostly +X) but is itself unmeasured.
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
    if up_bone:
        warnings.append("辅助骨骼（up）不参与预览")
    infl = min(1.0, max(0.0, float(influence)))
    if infl != influence:
        warnings.append("影响 %.2f 超出 0..1，预览按 %.0f 处理" % (influence, infl))
    return ConstraintPlan(
        True, warnings=warnings, bone=bone, name=CON_NAME['Aim'],
        con_type='DAMPED_TRACK', target=target,
        props={'track_axis': axis, 'influence': infl})


# ── RotExpression ───────────────────────────────────────────────────────────

def plan_rot(bone, source, coeffs):
    """Copy `source`'s local rotation onto `bone`, each Euler axis times its
    coefficient: a Transformation constraint mapping rotation to rotation.

    Whether the engine multiplies Euler angles (and in which axis order) is
    unmeasured; this is the plainest reading of "copy rotation by axis".
    """
    if not bone:
        return _no("没有被驱动的骨骼")
    if not source:
        return _no("没有源骨骼")
    if bone == source:
        return _no("被驱动的骨骼和源骨骼是同一根")
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
