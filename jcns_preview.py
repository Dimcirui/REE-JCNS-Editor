"""
jcns_preview.py
---------------
Make an entry visible in the viewport.

Ranges entries get a Blender driver on the target bone (DriverBackend, wrapping
jcns_operators); Skin / Aim / RotExpression get a native pose-bone constraint
(ConstraintBackend, which creates what modules/jcns_preview_plan.py describes).
Both go through one interface and one pair of operators:

    Kind.preview   ->  BACKENDS[...]   ->  units of entries  ->  apply / clear

A *unit* is the set of entries that have to be applied together.  For Ranges that
is every constraint on one (bone, transform, axis) channel, because Blender allows
one driver per channel and only the last constraint on it is live; for the other
sections it is a single entry.

A new previewable section needs a `preview` id in modules/jcns_kinds.py and a
backend registered in BACKENDS.
"""

import bpy
from bpy.types import Operator
from bpy.props import EnumProperty, StringProperty

from .modules_shim import get_kinds, get_plan, T


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------

class PreviewBackend:
    id = ''
    experimental = False     # the section's semantics are inferred, not measured: the panel marks it

    def units(self, root, kind_id):
        """Every unit of this kind under `root`: a list of lists of entries."""
        raise NotImplementedError

    def unit_of(self, root, entry):
        raise NotImplementedError

    def apply(self, rp, unit):
        """Create or replace the preview for a unit.  -> (ok, message)"""
        raise NotImplementedError

    def clear(self, rp, unit):
        raise NotImplementedError

    def refresh(self, obj, structural):
        """An entry was edited; bring a preview that is already on up to date.

        `structural` is False when only numbers changed.  Must never raise into
        the edit.  -> True when something was refreshed.
        """
        raise NotImplementedError

    def problems(self, entry):
        """Reasons this entry cannot be previewed or will be previewed only in part:
        [(is_blocking, text), ...].  Shown in the preview panel under the selected-entry row."""
        return []

    @staticmethod
    def is_on(unit):
        return any(e.jcns_cns_props.preview_on for e in unit)


class DriverBackend(PreviewBackend):
    id = 'driver'

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
    plan = get_plan()
    if kind_id == 'Skin':
        return plan.plan_skin(p.target_bone, [(w.bone, w.weight) for w in p.skin_sources])
    if kind_id == 'Aim':
        from . import AIM_TYPE_TO_INT
        return plan.plan_aim(p.target_bone, p.aim_target_bone, tuple(p.aim_axis),
                             p.aim_influence, p.aim_up_bone, AIM_TYPE_TO_INT[p.aim_type], tuple(p.aim_offset))
    if kind_id == 'RotExpression':
        return plan.plan_rot(p.target_bone, p.rot_source_bone, tuple(p.rot_gains))
    return plan.ConstraintPlan(False, T("ui.preview.no_preview_kind"))


class ConstraintBackend(PreviewBackend):
    id = 'constraint'
    experimental = True

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
            return False, T("ui.preview.bone_missing", entry.name, plan.bone)
        wanted = ([plan.target] if plan.target else []) + [b for b, _ in plan.targets]
        missing = [b for b in wanted if b not in pose]
        if missing:
            return False, T("ui.preview.armature_missing_bones", entry.name, T("ui.sep.list").join(missing))

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
            msg += T("ui.preview.warn_suffix", T("ui.sep.semicolon").join(plan.warnings))
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
            # Edited into a state with no preview: drop the stale constraint.
            self.clear(rp, [obj])
            return False
        rp.target_armature.update_tag()
        return True


BACKENDS = {b.id: b for b in (DriverBackend(), ConstraintBackend())}


def backend_of(kind_id):
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
    ('ENTRY', T("ui.preview.scope.entry"), T("ui.preview.scope.entry_desc")),
    ('KIND', T("ui.preview.scope.kind"), T("ui.preview.scope.kind_desc")),
    ('FILE', T("ui.preview.scope.file"), T("ui.preview.scope.file_desc")),
]


def _resolve(context, scope, kind):
    """(root, rp, [(kind id, [units])]) for an operator call, or (None, None, error)."""
    from . import (get_export_root, get_jcns_constraint,
                   get_jcns_root_from_constraint)
    if scope == 'ENTRY':
        obj, p = get_jcns_constraint(context)
        if obj is None:
            return None, None, T("ui.preview.err_no_entry")
        root, rp = get_jcns_root_from_constraint(obj)
        kind_id = get_kinds().kind_of(p.constraint_type).id
        backend = backend_of(kind_id)
        if backend is None:
            return None, None, T("ui.preview.err_kind_no_preview", get_kinds().kind_of(kind_id).label)
        if root is None:
            return None, None, T("ui.preview.err_no_root_of")
        return root, rp, [(kind_id, [backend.unit_of(root, obj)])]

    root, rp = get_export_root(context)
    if root is None:
        return None, None, T("ui.preview.err_no_root")
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
        return None, None, T("ui.preview.err_section_no_preview")
    return root, rp, plan


class _PreviewOperator(Operator):
    bl_options = {'REGISTER', 'UNDO'}

    scope: EnumProperty(name=T("ui.preview.prop_scope"), items=_SCOPES, default='ENTRY')
    kind: StringProperty(name=T("ui.preview.prop_kind"), default="", options={'SKIP_SAVE'})

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
            self.report({'ERROR'}, T("ui.preview.err_no_armature"))
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
            msg = T("ui.preview.done_apply", done, entries)
            if skipped:
                msg += T("ui.preview.done_skipped", skipped)
                if skipped == 1:
                    msg += T("ui.preview.done_skipped_one", messages[0])
            self.report({'WARNING' if skipped and not done else 'INFO'}, msg)
        else:
            self.report({'INFO'}, T("ui.preview.done_clear", done, entries))
        return {'FINISHED'}


class JCNS_OT_PreviewApply(_PreviewOperator):
    bl_idname = "jcns.preview_apply"
    bl_label  = T("ui.preview.op_apply_label")
    bl_description = T("ui.preview.op_apply_desc")

    @classmethod
    def description(cls, context, properties):
        return {'ENTRY': T("ui.preview.op_apply_entry"), 'KIND': T("ui.preview.op_apply_kind"),
                'FILE': T("ui.preview.op_apply_file")}.get(properties.scope, cls.bl_description)

    def execute(self, context):
        return self._run(context, 'apply')


class JCNS_OT_PreviewClear(_PreviewOperator):
    bl_idname = "jcns.preview_clear"
    bl_label  = T("ui.preview.op_clear_label")
    bl_description = T("ui.preview.op_clear_desc")

    @classmethod
    def description(cls, context, properties):
        return {'ENTRY': T("ui.preview.op_clear_entry"), 'KIND': T("ui.preview.op_clear_kind"),
                'FILE': T("ui.preview.op_clear_file")}.get(properties.scope, cls.bl_description)

    def execute(self, context):
        return self._run(context, 'clear')


# ---------------------------------------------------------------------------
# Completing the target armature
# ---------------------------------------------------------------------------
#
# A mesh stores only the bones it skins to, and the importer hangs a bone whose
# parent is missing on the nearest ancestor it has.  RE9's body mesh lacks
# L_Arm_Upper / L_Arm_Lower, so L_Elbow_Down sits under L_Arm_Clavicle: its
# parent-relative rest is then not the engine's, and a replacing translation
# moves it by the whole forearm.  The character's other meshes (e.g. the jacket)
# carry those bones; their armatures fill the gaps.

_MATCH_TOL = 1e-4      # metres: shared bones must sit at the same place to be one skeleton


def referenced_bones(root):
    """Every target and source bone the root's entries name."""
    from . import get_constraint_empties
    out = set()
    for e in get_constraint_empties(root):
        p = e.jcns_cns_props
        if p.target_bone:
            out.add(p.target_bone)
        out.update(sp.source_bone for sp in p.sources if sp.source_bone)
    return out


def _world_bone(obj, b):
    return obj.matrix_world @ b.matrix_local


def skeleton_donors(arm):
    """Other armatures in the scene that are the same skeleton as `arm`: every
    bone they share sits at the same world position."""
    out = []
    for o in bpy.context.scene.objects:
        if o.type != 'ARMATURE' or o is arm:
            continue
        shared = [n for n in o.data.bones.keys() if n in arm.data.bones]
        if shared and all(
                (_world_bone(o, o.data.bones[n]).translation
                 - _world_bone(arm, arm.data.bones[n]).translation).length < _MATCH_TOL
                for n in shared):
            out.append(o)
    return out


_gap_cache = {}


def fillable_gaps(root, arm):
    """Bones the entries name that `arm` lacks and another armature of the same
    skeleton in the scene has, sorted.  Cached on the scene's armatures, for the panel."""
    arms = tuple(sorted((o.name, len(o.data.bones)) for o in bpy.context.scene.objects
                        if o.type == 'ARMATURE'))
    key = (root.name, arm.name, arms)
    if key not in _gap_cache:
        missing = referenced_bones(root) - set(arm.data.bones.keys())
        have = set()
        if missing:
            for o in skeleton_donors(arm):
                have.update(n for n in missing if n in o.data.bones)
        _gap_cache.clear()
        _gap_cache[key] = sorted(have)
    return _gap_cache[key]


def skeleton_plan(arm, donors, wanted):
    """-> (add {bone: (donor, parent)}, reparent {bone: parent}).

    Each bone's parent comes from the armature where its chain is longest.  Bones
    are added for the missing `wanted` bones and for every missing ancestor of a
    bone that is kept; an existing bone is only moved under bones inserted above
    its current parent, never to an unrelated one.
    """
    def depth(b):
        d = 0
        while b.parent is not None:
            d, b = d + 1, b.parent
        return d

    best = {}                                   # bone -> (depth, armature, parent)
    for o in [arm] + donors:
        for b in o.data.bones:
            d = depth(b)
            if b.name not in best or d > best[b.name][0]:
                best[b.name] = (d, o, b.parent.name if b.parent else None)

    def chain(name):
        out, p = [], best[name][2]
        while p is not None:
            out.append(p)
            p = best[p][2] if p in best else None
        return out

    have = set(arm.data.bones.keys())
    add = {}
    for name in have | {n for n in wanted if n in best}:
        if name not in have and name not in add:
            add[name] = (best[name][1], best[name][2])
        for p in chain(name):
            if p in have:
                break
            if p not in add and p in best:
                add[p] = (best[p][1], best[p][2])

    reparent = {}
    for name in have:
        want = best[name][2]
        cur = arm.data.bones[name].parent
        if want is None or (cur is not None and cur.name == want):
            continue
        if cur is None or cur.name in chain(name):
            reparent[name] = want
    return add, reparent


def complete_skeleton(arm, donors, wanted):
    """Add and reparent bones per skeleton_plan.  Needs the armature active in
    Object mode.  -> (added, reparented)"""
    add, reparent = skeleton_plan(arm, donors, wanted)
    if not add and not reparent:
        return 0, 0
    inv = arm.matrix_world.inverted()
    bpy.ops.object.mode_set(mode='EDIT')
    try:
        eb = arm.data.edit_bones
        for name, (donor, _parent) in add.items():
            b = donor.data.bones[name]
            e = eb.new(name)
            e.length = b.length
            e.matrix = inv @ _world_bone(donor, b)
            e.length = b.length                 # the matrix setter keeps head and roll only
            e.use_deform = False                # no vertex group on this mesh
        for name, (_donor, parent) in add.items():
            eb[name].parent = eb.get(parent) if parent else None
        for name, parent in reparent.items():
            eb[name].use_connect = False
            eb[name].parent = eb[parent]
    finally:
        bpy.ops.object.mode_set(mode='OBJECT')
    for name, (donor, _parent) in add.items():
        for k, v in donor.data.bones[name].items():
            arm.data.bones[name][k] = v
    return len(add), len(reparent)


class JCNS_OT_CompleteSkeleton(Operator):
    bl_idname = "jcns.complete_skeleton"
    bl_label  = T("ui.preview.complete")
    bl_description = T("ui.preview.complete_desc")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        from . import get_export_root
        _root, rp = get_export_root(context)
        return rp is not None and rp.target_armature is not None

    def execute(self, context):
        from . import get_export_root
        root, rp = get_export_root(context)
        arm = rp.target_armature
        if any(preview_counts(root, k.id)[0] for k in previewable_kinds()):
            self.report({'WARNING'}, T("ui.preview.complete_clear_first"))
            return {'CANCELLED'}
        donors = skeleton_donors(arm)
        if not donors:
            self.report({'WARNING'}, T("ui.preview.complete_nothing"))
            return {'CANCELLED'}

        prev_active, prev_mode = context.view_layer.objects.active, context.mode
        if prev_mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        context.view_layer.objects.active = arm
        try:
            added, moved = complete_skeleton(arm, donors, referenced_bones(root))
        finally:
            context.view_layer.objects.active = prev_active
        if not added and not moved:
            self.report({'WARNING'}, T("ui.preview.complete_nothing"))
            return {'CANCELLED'}
        self.report({'INFO'}, T("ui.preview.complete_done", added, moved))
        return {'FINISHED'}


_classes = [JCNS_OT_PreviewApply, JCNS_OT_PreviewClear, JCNS_OT_CompleteSkeleton]


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
