"""
jcns_preview.py
---------------
Make an entry visible in the viewport.

Ranges entries get a Blender driver on the target bone.  The other sections have
nothing to drive, but most of them still say "this bone follows that one", which
Blender expresses as a native pose-bone constraint.  Both are the same idea from
the user's side (press Apply, see the rig move, press Clear), so both go through
one interface and one pair of operators:

    Kind.preview   ->  BACKENDS[...]   ->  units of entries  ->  apply / clear

A *unit* is the set of entries that have to be applied together.  For Ranges that
is every constraint on one (bone, transform, axis) channel, because Blender allows
one driver per channel and only the last constraint on it is live; for the other
sections it is a single entry.

Backends:
  DriverBackend      'driver'      Ranges; wraps the driver code in jcns_operators
  ConstraintBackend  'constraint'  Skin / Aim / RotExpression; the decisions are
                                   in modules/jcns_preview_plan.py, this side only
                                   creates what a plan describes

A new section that can be previewed needs: a `preview` id in modules/jcns_kinds.py
and either an existing backend or a new class registered in BACKENDS.
"""

import bpy
from bpy.types import Operator
from bpy.props import EnumProperty, StringProperty

from .modules_shim import get_kinds, get_plan


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------

class PreviewBackend:
    id = ''
    noun = ''                # what gets created: shown in reports and buttons
    experimental = False     # the section's semantics are inferred, not measured
    note = ''                # one line for the panel

    def units(self, root, kind_id):
        """Every unit of this kind under `root`: a list of lists of entries."""
        raise NotImplementedError

    def unit_of(self, root, entry):
        """The unit that `entry` belongs to."""
        raise NotImplementedError

    def apply(self, rp, unit):
        """Create or replace the preview for a unit.  -> (ok, message)"""
        raise NotImplementedError

    def clear(self, rp, unit):
        """Remove the preview for a unit."""
        raise NotImplementedError

    def refresh(self, obj, structural):
        """An entry was edited; bring a preview that is already on up to date.

        `structural` is False when only numbers changed.  Must never raise into
        the edit.  -> True when something was refreshed.
        """
        raise NotImplementedError

    def problems(self, entry):
        """Reasons this entry cannot be previewed or will be previewed only in part:
        [(is_blocking, text), ...].  Shown above the Apply button."""
        return []

    @staticmethod
    def is_on(unit):
        return any(e.jcns_cns_props.preview_on for e in unit)


class DriverBackend(PreviewBackend):
    id = 'driver'
    noun = "驱动器"
    note = "在目标骨骼的通道上生成驱动器；同一通道只有文件里最后一条生效"

    def units(self, root, kind_id):
        from . import group_constraints_by_channel
        return list(group_constraints_by_channel(root).values())

    def unit_of(self, root, entry):
        from . import group_constraints_by_channel, channel_key
        return group_constraints_by_channel(root).get(
            channel_key(entry.jcns_cns_props), [entry])

    def apply(self, rp, unit):
        from . import jcns_operators
        ok, err, label = jcns_operators._apply_channel(rp.target_armature, rp, unit)
        return ok, (label if ok else "%s — %s" % (label, err))

    def clear(self, rp, unit):
        from . import jcns_operators
        jcns_operators._clear_channel(rp.target_armature, unit)

    def refresh(self, obj, structural):
        from . import jcns_operators
        if structural:
            return jcns_operators.refresh_applied_driver(obj)
        return jcns_operators.refresh_channel_values(obj)


def _plan_for(kind_id, p):
    """The ConstraintPlan (modules/jcns_preview_plan.py) for one entry's data."""
    plan = get_plan()
    if kind_id == 'Skin':
        return plan.plan_skin(p.target_bone, [(w.bone, w.weight) for w in p.skin_sources])
    if kind_id == 'Aim':
        return plan.plan_aim(p.target_bone, p.aim_target_bone, tuple(p.aim_vec1),
                             p.aim_influence, p.aim_up_bone)
    if kind_id == 'RotExpression':
        return plan.plan_rot(p.target_bone, p.rot_source_bone, tuple(p.rot_floats))
    return plan.ConstraintPlan(False, "这一类没有预览")


class ConstraintBackend(PreviewBackend):
    id = 'constraint'
    noun = "骨骼约束"
    experimental = True
    note = "用原生骨骼约束预览。这几类的语义是统计推断、未实测，预览只是拿来对照游戏"

    def units(self, root, kind_id):
        from . import entries_of
        return [[e] for e in entries_of(root, kind_id)]

    def unit_of(self, root, entry):
        return [entry]

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _kind_id(entry):
        return get_kinds().kind_of(entry.jcns_cns_props.constraint_type).id

    @staticmethod
    def _remove(arm, bone_name, con_name):
        pb = arm.pose.bones.get(bone_name) if bone_name else None
        con = pb.constraints.get(con_name) if pb is not None else None
        if con is not None:
            pb.constraints.remove(con)

    # -- interface ----------------------------------------------------------

    def problems(self, entry):
        plan = _plan_for(self._kind_id(entry), entry.jcns_cns_props)
        if not plan.ok:
            return [(True, plan.reason)]
        return [(False, w) for w in plan.warnings]

    def apply(self, rp, unit):
        arm = rp.target_armature
        entry = unit[0]
        p = entry.jcns_cns_props
        plan = _plan_for(self._kind_id(entry), p)
        if not plan.ok:
            return False, "%s — %s" % (entry.name, plan.reason)
        pose = arm.pose.bones
        pb = pose.get(plan.bone)
        if pb is None:
            return False, "%s — 找不到骨骼「%s」" % (entry.name, plan.bone)
        wanted = ([plan.target] if plan.target else []) + [b for b, _ in plan.targets]
        missing = [b for b in wanted if b not in pose]
        if missing:
            return False, "%s — 骨架里没有：%s" % (entry.name, "、".join(missing))

        # The entry's bone may have been changed since the last apply.
        if p.preview_bone and p.preview_bone != plan.bone:
            self._remove(arm, p.preview_bone, plan.name)

        con = pb.constraints.get(plan.name)
        if con is not None and con.type != plan.con_type:
            pb.constraints.remove(con)
            con = None
        if con is None:
            con = pb.constraints.new(plan.con_type)
            con.name = plan.name
        for key, value in plan.props.items():
            setattr(con, key, value)
        if plan.con_type == 'ARMATURE':
            con.targets.clear()
            for bone, weight in plan.targets:
                t = con.targets.new()
                t.target = arm
                t.subtarget = bone
                t.weight = weight
        else:
            con.target = arm
            con.subtarget = plan.target

        p.preview_on = True
        p.preview_bone = plan.bone
        msg = "%s → %s" % (entry.name, plan.con_type)
        if plan.warnings:
            msg += "（" + "；".join(plan.warnings) + "）"
        return True, msg

    def clear(self, rp, unit):
        arm = rp.target_armature
        for entry in unit:
            p = entry.jcns_cns_props
            name = get_plan().CON_NAME.get(self._kind_id(entry))
            if name:
                self._remove(arm, p.preview_bone or p.target_bone, name)
            p.preview_on = False
            p.preview_bone = ''

    def refresh(self, obj, structural):
        from . import get_jcns_root_from_constraint
        p = obj.jcns_cns_props
        if not p.preview_on:
            return False
        root, rp = get_jcns_root_from_constraint(obj)
        if root is None or rp is None or rp.target_armature is None:
            return False
        ok, _msg = self.apply(rp, [obj])
        if not ok:
            # Edited into a state that has no preview (e.g. the aim axis is now
            # diagonal): drop the stale constraint rather than leave it lying.
            self.clear(rp, [obj])
            return False
        rp.target_armature.update_tag()
        return True


BACKENDS = {b.id: b for b in (DriverBackend(), ConstraintBackend())}


def backend_of(kind_id):
    """The backend that previews a kind, or None."""
    return BACKENDS.get(get_kinds().kind_of(kind_id).preview)


def refresh(obj, structural=True):
    """Property-update entry point: an entry was edited."""
    p = getattr(obj, 'jcns_cns_props', None)
    if p is None or not p.is_jcns_constraint or not p.preview_on:
        return False
    backend = backend_of(p.constraint_type)
    return bool(backend and backend.refresh(obj, structural))


def preview_counts(root, kind_id):
    """(entries with a preview on, entries) for one kind under a root."""
    from . import entries_of
    entries = entries_of(root, kind_id)
    return sum(1 for e in entries if e.jcns_cns_props.preview_on), len(entries)


def previewable_kinds():
    return [k for k in get_kinds().KINDS if k.preview]


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

_SCOPES = [
    ('ENTRY', "当前条目", "只处理当前选中的条目（Ranges 会连同同一通道上的其它条目）"),
    ('KIND', "本分区", "处理当前分区里的全部条目"),
    ('FILE', "全部分区", "处理文件里所有能预览的分区"),
]


def _resolve(context, scope, kind):
    """(root, rp, [(kind id, [units])]) for an operator call, or (None, None, error)."""
    from . import (get_export_root, get_jcns_constraint,
                   get_jcns_root_from_constraint)
    if scope == 'ENTRY':
        obj, p = get_jcns_constraint(context)
        if obj is None:
            return None, None, "没有选中条目"
        root, rp = get_jcns_root_from_constraint(obj)
        kind_id = get_kinds().kind_of(p.constraint_type).id
        backend = backend_of(kind_id)
        if backend is None:
            return None, None, "「%s」没有预览" % get_kinds().kind_of(kind_id).label
        if root is None:
            return None, None, "找不到所属的 JCNS 根节点"
        return root, rp, [(kind_id, [backend.unit_of(root, obj)])]

    root, rp = get_export_root(context)
    if root is None:
        return None, None, "找不到 JCNS 根节点"
    if scope == 'KIND':
        kind_ids = [kind or rp.browser_kind]
    else:
        kind_ids = [k.id for k in previewable_kinds()]
    plan = []
    for kid in kind_ids:
        backend = backend_of(kid)
        if backend is not None:
            plan.append((kid, backend.units(root, kid)))
    if not plan:
        return None, None, "这一分区没有预览"
    return root, rp, plan


class _PreviewOperator(Operator):
    bl_options = {'REGISTER', 'UNDO'}

    scope: EnumProperty(name="范围", items=_SCOPES, default='ENTRY')
    kind: StringProperty(name="分区", default="", options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        from . import get_export_root, get_jcns_constraint, get_jcns_root_from_constraint
        obj, _ = get_jcns_constraint(context)
        if obj is not None:
            _, rp = get_jcns_root_from_constraint(obj)
        else:
            _, rp = get_export_root(context)
        return rp is not None and rp.target_armature is not None

    def _run(self, context, action):
        root, rp, plan = _resolve(context, self.scope, self.kind)
        if root is None:
            self.report({'WARNING'}, plan)
            return {'CANCELLED'}
        if rp.target_armature is None:
            self.report({'ERROR'}, "未设置目标骨架。")
            return {'CANCELLED'}

        done = skipped = entries = 0
        messages = []
        for kind_id, units in plan:
            backend = backend_of(kind_id)
            for unit in units:
                if action == 'apply':
                    ok, msg = backend.apply(rp, unit)
                    if ok:
                        done += 1
                        entries += len(unit)
                        print("[JCNS PREVIEW OK  ] %s" % msg)
                    else:
                        skipped += 1
                        messages.append(msg)
                        print("[JCNS PREVIEW SKIP] %s" % msg)
                else:
                    if backend.is_on(unit):
                        backend.clear(rp, unit)
                        done += 1
                        entries += len(unit)
        rp.target_armature.update_tag()

        if action == 'apply':
            msg = "已应用 %d 个预览，覆盖 %d 条条目" % (done, entries)
            if skipped:
                msg += "；跳过 %d 个，详见系统控制台" % skipped
                if skipped == 1:
                    msg += "（%s）" % messages[0]
            self.report({'WARNING' if skipped and not done else 'INFO'}, msg)
        else:
            self.report({'INFO'}, "已清除 %d 个预览，覆盖 %d 条条目" % (done, entries))
        return {'FINISHED'}


class JCNS_OT_PreviewApply(_PreviewOperator):
    """在骨架上生成预览（Ranges 是驱动器，其余是原生骨骼约束）"""
    bl_idname = "jcns.preview_apply"
    bl_label  = "应用预览"

    def execute(self, context):
        return self._run(context, 'apply')


class JCNS_OT_PreviewClear(_PreviewOperator):
    """清除预览"""
    bl_idname = "jcns.preview_clear"
    bl_label  = "清除预览"

    def execute(self, context):
        return self._run(context, 'clear')


_classes = [JCNS_OT_PreviewApply, JCNS_OT_PreviewClear]


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
