"""
Merging Ranges entries on one channel into a single multi-source entry.

modules/jcns_merge.py decides whether a merge is expressible and what comes out;
this file carries it out on the Empties (sources, deleted entries, '[N]' names,
group counts, preview) and draws the two entry points: the Ranges editor's
sibling block and the channel list.

Entries are identified by their position in get_constraint_empties(), the same
order the plans are made in.
"""

import bpy
from bpy.types import Operator

from .modules_shim import ensure_path
from . import jcns_cm

ensure_path()
import jcns_merge as plan_mod  # noqa: E402


_COPY_SKIP = {'rna_type', 'cm_channel', 'cm_cache'}


# ---------------------------------------------------------------------------
# Describing entries to the plan module
# ---------------------------------------------------------------------------

def _describe(empty, with_sources=True):
    p = empty.jcns_cns_props
    d = {
        'target_bone': p.target_bone,
        'target_property': p.target_property,
        'property_hash': p.property_hash,
        'transform_type': p.transform_type,
        'target_axis': p.target_axis,
        'additive': bool(p.additive),
        'flags_other': p.flags_other,
        'reserved_vec4': (p.reserved_vec4_x, p.reserved_vec4_y, p.reserved_vec4_z, p.reserved_vec4_w),
        'unknown_float2': (p.unknown_float2_x, p.unknown_float2_y),
        'unknown_byte_72': p.unknown_byte_72,
        'unknown_byte_74': p.unknown_byte_74,
        'unknown_byte_75': p.unknown_byte_75,
        'reserved_tail': tuple(p.reserved_tail),
        'group_count': p.group_count,
        'cone_infos': len(p.cone_infos),
        'sources': [],
    }
    if with_sources:
        d['sources'] = [{'complex_mapping': bool(sp.complex_mapping_info_count or len(sp.cm_cache)
                                                 or jcns_cm.has_curve(sp))}
                        for sp in p.sources]
    return d


def _complex_ok(rp):
    from . import file_state
    from .modules_shim import get_kinds
    return get_kinds().complex_mapping_editable(file_state(rp))[0]


def _collect(root, rp):
    """(entry Empties in file order, their descriptions, whether curves can move)."""
    from . import get_constraint_empties
    ordered = get_constraint_empties(root)
    return ordered, [_describe(e) for e in ordered], _complex_ok(rp)


def _caps_reason(rp):
    """'' when this file lets entries be added and removed, else why not."""
    from .jcns_operators import _caps_for
    caps = _caps_for(rp, 'Ranges')
    if caps.can_add and caps.can_remove:
        return ''
    return caps.reason('remove') or caps.reason('add') or "这个文件不能增删约束"


def _label(empty):
    name = empty.name
    return name[:name.index(']') + 1] if name.startswith('[') and ']' in name else name


def _channel_text(entry):
    return "%s 的局部 %s 轴" % (entry['target_bone'] or '?', entry['target_axis'])


# ---------------------------------------------------------------------------
# Carrying a plan out
# ---------------------------------------------------------------------------

def _copy_props(src, dst, skip=_COPY_SKIP):
    for prop in src.bl_rna.properties:
        key = prop.identifier
        if key not in skip:
            setattr(dst, key, getattr(src, key))


def _copy_source(src, dst):
    """Copy one source, its ComplexMapping curve and the file's records for it."""
    _copy_props(src, dst)
    if jcns_cm.has_curve(src):
        jcns_cm.copy_keys(src, dst)
    for rec in src.cm_cache:
        _copy_props(rec, dst.cm_cache.add(), {'rna_type'})


def _absorb(keeper, donors):
    """Put the donors' sources, (Empty, source index) pairs in file order, ahead of
    the keeper's own."""
    cp = keeper.jcns_cns_props
    for at, (donor, k) in enumerate(donors):
        dst = cp.sources.add()
        _copy_source(donor.jcns_cns_props.sources[k], dst)
        cp.sources.move(len(cp.sources) - 1, at)
    cp.active_source_index = min(cp.active_source_index + len(donors), len(cp.sources) - 1)


def _delete(empty):
    anim = empty.animation_data
    action = anim.action if anim is not None else None
    bpy.data.objects.remove(empty, do_unlink=True)
    if action is not None and action.users == 0 and jcns_cm.ACTION_MARKER in action.keys():
        bpy.data.actions.remove(action)


def _carry_out(context, root, rp, ordered, entries, plans):
    """Apply every ok plan.  -> the surviving Empties, one per applied plan."""
    from . import get_constraint_empties, jcns_preview
    from .jcns_operators import _renumber_in_order

    result = plan_mod.apply_plans(entries, plans)
    if not result.applied:
        return []

    keepers = [ordered[p.keep] for p in result.applied]
    was_on = [any(ordered[i].jcns_cns_props.preview_on for i in p.indices) for p in result.applied]
    doomed = [ordered[i] for p in result.applied for i in p.remove]
    survivors = [(ordered[e['origin']], e['group_count']) for e in result.entries]

    # The preview is rebuilt below; with it off, editing the sources does not
    # trigger a driver rebuild per property.
    for k in keepers:
        k.jcns_cns_props.preview_on = False
    for p, keeper in zip(result.applied, keepers):
        _absorb(keeper, [(ordered[i], k) for i, k in p.sources if i != p.keep])
    for empty in doomed:
        _delete(empty)
    for empty, count in survivors:
        if empty.jcns_cns_props.group_count != count:
            empty.jcns_cns_props.group_count = count
    _renumber_in_order(get_constraint_empties(root))

    arm = rp.target_armature
    backend = jcns_preview.backend_of('Ranges')
    if arm is not None and backend is not None:
        for keeper, on in zip(keepers, was_on):
            if not on:
                continue
            unit = backend.unit_of(root, keeper)
            ok, msg = backend.apply(rp, unit)
            if not ok:
                backend.clear(rp, unit)
                print("[JCNS MERGE] preview not rebuilt: %s" % msg)
        arm.update_tag()
    return keepers


def _activate(context, empty):
    context.view_layer.objects.active = empty
    empty.select_set(True)


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

def _active_ranges_entry(context):
    from . import get_jcns_constraint, get_jcns_root_from_constraint
    obj, p = get_jcns_constraint(context)
    if obj is None or p.constraint_type not in ('Ranges', ''):
        return None, None, None
    root, rp = get_jcns_root_from_constraint(obj)
    return obj, root, rp


class JCNS_OT_MergeChannel(Operator):
    """把当前条目所在通道上的多条约束合并成一条多源约束。合并前只有最后一条生效，合并后各源输出相加，结果可能不同"""
    bl_idname = "jcns.merge_channel"
    bl_label  = "合并为多源约束"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj, root, rp = _active_ranges_entry(context)
        return rp is not None and not _caps_reason(rp)

    def execute(self, context):
        obj, root, rp = _active_ranges_entry(context)
        if root is None:
            self.report({'ERROR'}, "找不到所属的 JCNS 根节点。")
            return {'CANCELLED'}
        why = _caps_reason(rp)
        if why:
            self.report({'ERROR'}, why)
            return {'CANCELLED'}

        ordered, entries, complex_ok = _collect(root, rp)
        if obj not in ordered:
            self.report({'ERROR'}, "当前条目不在文件的 Ranges 列表里。")
            return {'CANCELLED'}
        plan = plan_mod.plan_merge(entries, plan_mod.channel_members(entries, ordered.index(obj)),
                                   complex_ok)
        if not plan.ok:
            self.report({'WARNING'}, "不能合并：" + plan.reason())
            return {'CANCELLED'}

        n = len(plan.indices)
        n_src = len(plan.sources)
        label = _channel_text(entries[plan.keep])
        keepers = _carry_out(context, root, rp, ordered, entries, [plan])
        _activate(context, keepers[0])
        self.report({'INFO'}, "%s：%d 条约束合并成 1 条，共 %d 个驱动源。" % (label, n, n_src))
        return {'FINISHED'}


class JCNS_OT_MergeAllChannels(Operator):
    """把文件里每个有多条约束的通道都合并成一条多源约束。合并前每个通道只有最后一条生效，合并后各源输出相加，结果可能不同；不能合并的通道保持原样"""
    bl_idname = "jcns.merge_all_channels"
    bl_label  = "合并所有同通道约束"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        from . import get_export_root
        root, rp = get_export_root(context)
        return rp is not None and not _caps_reason(rp)

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=360)

    def draw(self, context):
        col = self.layout.column(align=True)
        col.label(text="每个通道合并成一条约束，各源输出相加。")
        col.label(text="合并前只有靠后的一条生效，结果可能与现在不同。")
        col.label(text="不能合并的通道保持原样。")

    def execute(self, context):
        from . import get_export_root
        root, rp = get_export_root(context)
        if root is None:
            self.report({'ERROR'}, "找不到 JCNS 根节点。")
            return {'CANCELLED'}
        why = _caps_reason(rp)
        if why:
            self.report({'ERROR'}, why)
            return {'CANCELLED'}

        ordered, entries, complex_ok = _collect(root, rp)
        plans = plan_mod.plan_all(entries, complex_ok)
        if not plans:
            self.report({'INFO'}, "没有哪个通道有多条约束。")
            return {'CANCELLED'}
        skipped = [p for p in plans if not p.ok]
        for p in skipped:
            print("[JCNS MERGE SKIP] %s：%s" % (_channel_text(entries[p.keep]), p.reason()))
        ok_plans = [p for p in plans if p.ok]
        if not ok_plans:
            self.report({'WARNING'}, "没有可合并的通道；%d 个通道不能合并，原因见系统控制台。" % len(skipped))
            return {'CANCELLED'}

        n_entries = sum(len(p.indices) for p in ok_plans)
        keepers = _carry_out(context, root, rp, ordered, entries, ok_plans)
        if context.view_layer.objects.active is None:
            _activate(context, keepers[0])
        msg = "已合并 %d 个通道（%d 条约束并入 %d 条）" % (len(ok_plans), n_entries, len(ok_plans))
        if skipped:
            msg += "；%d 个通道不能合并，保持原样：%s" % (
                len(skipped), "；".join("%s（%s）" % (_channel_text(entries[p.keep]), p.reason())
                                       for p in skipped[:2]))
            if len(skipped) > 2:
                msg += "等，其余见系统控制台"
        self.report({'WARNING' if skipped else 'INFO'}, msg)
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Panel pieces
# ---------------------------------------------------------------------------

def draw_channel_merge(layout, context, members, rp):
    """The merge button for the Ranges editor's sibling block.

    `members` are the Empties on the active entry's channel, in file order.
    """
    from .jcns_ui import _wrap_label
    entries = [_describe(e) for e in members]
    complex_ok = _complex_ok(rp)
    plan = plan_mod.plan_merge(entries, range(len(entries)), complex_ok)
    layout.separator()
    why = _caps_reason(rp)
    if why:
        _wrap_label(layout, context, why, icon='LOCKED')
        return
    _wrap_label(layout, context, "合并后各源输出相加，不再是靠后一条覆盖，结果可能与现在不同。", icon='INFO')
    if not plan.ok:
        _wrap_label(layout, context, "不能合并：" + plan.reason(), icon='ERROR', alert=True)
    row = layout.row()
    row.enabled = plan.ok
    row.operator("jcns.merge_channel", icon='AUTOMERGE_ON')


def draw_merge_all(layout, context, groups, rp):
    """File-level entry point, for the channel list.  `groups` is
    group_constraints_by_channel(root)."""
    from .jcns_ui import _wrap_label
    n = sum(1 for members in groups.values() if len(members) > 1)
    if not n:
        return
    box = layout.box()
    _wrap_label(box, context, "%d 个通道有多条约束，游戏里每个通道只有最后一条生效。" % n, icon='INFO')
    why = _caps_reason(rp)
    if why:
        _wrap_label(box, context, why, icon='LOCKED')
        return
    box.operator("jcns.merge_all_channels", icon='AUTOMERGE_ON')


# ---------------------------------------------------------------------------
# Export check
# ---------------------------------------------------------------------------

def shared_channel_warning(empties, rp):
    """One line for the export report when several entries write one channel, or ''."""
    entries = [_describe(e, with_sources=False) for e in empties]
    shared = plan_mod.contested(entries)
    if not shared:
        return ''
    shown = "；".join("%s（%s）" % (_channel_text(entries[g[0]]), "、".join(_label(empties[i]) for i in g))
                     for g in shared[:3])
    if len(shared) > 3:
        shown += "等"
    text = "有 %d 个通道被多条约束共用，游戏里每个通道只有最后一条生效：%s。" % (len(shared), shown)
    return text if _caps_reason(rp) else text + "需要各条叠加时，先合并为多源约束。"


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

_classes = [JCNS_OT_MergeChannel, JCNS_OT_MergeAllChannels]


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
