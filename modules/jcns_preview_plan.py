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

from jcns_i18n import T

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
        return _no(T("core.plan.skin_no_bone"))
    warnings = []
    targets = []
    for bone, w in sources:
        if not bone:
            warnings.append(T("core.plan.skin_source_empty"))
        elif bone == object_bone:
            warnings.append(T("core.plan.skin_source_self"))
        else:
            targets.append((bone, float(w)))
    if not targets:
        return _no(T("core.plan.skin_no_sources"))
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
        return _no(T("core.plan.aim_no_bone"))
    if not target:
        return _no(T("core.plan.aim_no_target"))
    if bone == target:
        return _no(T("core.plan.aim_same"))
    axis = aim_track_axis(vec1)
    if not axis:
        return _no(T("core.plan.aim_axis", *tuple(vec1)))
    warnings = []
    if rotation_type == 5:
        warnings.append(T("core.plan.aim_type5"))
    elif rotation_type != 4:
        warnings.append(T("core.plan.aim_type_other", rotation_type))
    if any(abs(c) > 1e-6 for c in offset):
        warnings.append(T("core.plan.aim_offset"))
    if up_bone:
        warnings.append(T("core.plan.aim_up"))
    infl = min(1.0, max(0.0, float(influence)))
    if infl != influence:
        warnings.append(T("core.plan.aim_infl_range", influence, infl))
    elif abs(infl - 1.0) > 1e-6:
        warnings.append(T("core.plan.aim_infl_degenerate"))
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
        return _no(T("core.plan.rot_no_bone"))
    if not source:
        return _no(T("core.plan.rot_no_source"))
    if bone == source:
        return _no(T("core.plan.rot_same"))
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
