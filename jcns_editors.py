"""
jcns_editors.py
---------------
每种 section 各一组编辑器面板，没有通用表单。它们都挂在顶层「编辑」（jcns_ui.JCNS_PT_Edit）下面，
只在当前条目是这一类型时出现：

  JCNS_PT_Ed_<Kind>        这一类型的主面板（Ranges 的是「被驱动」，同级还有驱动、映射曲线等）
    JCNS_PT_Ed_<Kind>_<Sub>  按需要拆出来的子面板，原始字段一律默认折叠

预览不在这里：整个界面只有顶层「预览」一个入口。

新增编辑器：继承 _Editor，设 KIND，写 draw，注册进 _classes（父面板排在子面板前面）。
类型本身的事实在 modules/jcns_kinds.py，预览在 jcns_preview.py。

每个面板调 _begin()，它按 jcns_kinds.capabilities() 决定整块能否编辑并画出原因。
"""

from types import SimpleNamespace

import bpy
from bpy.types import Panel

from . import jcns_capture
from .modules_shim import get_targets as _targets, T
from .jcns_ui import (_mapping, _fmt, _field_row, _draw_raw_group, _active_source,
                      _multi_table_locked, _target_unit, _curve_icon, _swatch_icon,
                      _wrap_label, _kinds)


# ---------------------------------------------------------------------------
# 框架
# ---------------------------------------------------------------------------

def _begin(layout, context, banner=True):
    """Resolve the active entry and lay out its body.

    Returns None (after saying why) when the entry has no file, otherwise a
    namespace: obj, p (its properties), root, rp, caps, and `body`, a column that
    is disabled when the kind cannot be edited in this file.
    """
    from . import get_jcns_constraint, get_jcns_root_from_constraint, file_state
    obj, p = get_jcns_constraint(context)
    root, rp = get_jcns_root_from_constraint(obj)
    if rp is None:
        _wrap_label(layout, context, T("editors.no_root"), icon='ERROR', alert=True)
        return None
    kinds = _kinds()
    kind = kinds.kind_of(p.constraint_type)
    caps = kinds.capabilities(kind.id, file_state(rp))
    # 「编辑」面板已经为当前分区标签显示过它；只有活动条目属于另一个分区时才重复。
    if banner and caps.banner and rp.browser_kind != kind.id:
        layout.label(text=caps.banner, icon='LOCKED')
    body = layout.column()
    body.enabled = caps.can_edit
    return SimpleNamespace(obj=obj, p=p, root=root, rp=rp, caps=caps, kind=kind, body=body)


class _Editor:
    """Mixin for the editor panels of one kind."""
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = T("common.category")
    KIND = ''

    @classmethod
    def poll(cls, context):
        from . import get_jcns_constraint
        _, p = get_jcns_constraint(context)
        return p is not None and _kinds().kind_of(p.constraint_type).id == cls.KIND


class _EditorMain(_Editor):
    bl_parent_id = "JCNS_PT_edit"

    def draw_header(self, context):
        self.layout.label(text="", icon=_kinds().kind_of(self.KIND).icon)


class _Sub:
    """Mixin: a sub-panel that starts collapsed (raw fields and other rarely-touched data)."""
    bl_options = {'DEFAULT_CLOSED'}


# ---------------------------------------------------------------------------
# Ranges —— 映射曲线
# ---------------------------------------------------------------------------

_ANCHOR_NAMES = {'A': "editors.anchor.a", 'B': "editors.anchor.b", 'C': "editors.anchor.c"}


def _anchor_name(letter):
    return T(_ANCHOR_NAMES[letter]) if letter in _ANCHOR_NAMES else letter


def _warn_row(layout, text, button=None, op=None, icon='ERROR'):
    """One warning: the problem in red, the fix as a button on the same row."""
    row = layout.row(align=True)
    sub = row.row()
    sub.alert = True
    sub.label(text=text, icon=icon)
    if op:
        row.operator(op, text=button)


def draw_mapping_warnings(layout, p, sp, m):
    """What is wrong with this mapping, each with the button that fixes it.

    Nothing is drawn for a healthy mapping: the curve and the live read-out say the rest.
    Anchors are stored A→B→C, but a falling range such as [-60,-15,0] rests at C, so the
    rest output comes from sampling, not from reading the numbers left to right.
    """
    d = m.plain_description(sp)
    col = layout.column(align=True)

    if d.get('folded_dead'):
        _warn_row(col, T("editors.warn.folded_dead"), T("editors.btn.sort_anchors"), "jcns.sort_anchors")
    if d.get('unreachable_anchor'):
        _warn_row(col, T("editors.warn.anchor_unreachable", _anchor_name(d['unreachable_anchor'])),
                  T("editors.btn.sort_anchors"), "jcns.sort_anchors")
    if d['inert']:
        col.label(text=T("editors.warn.inert"), icon='RADIOBUT_OFF')
        return
    if d['offset_at_rest']:
        text = T("editors.warn.rest_offset", _fmt(d['rest_output']), _target_unit(p.transform_element))
        if m.would_swapping_ends_help(sp):
            _warn_row(col, text, T("editors.btn.swap_ends"), "jcns.swap_mapto_ends")
        else:
            _warn_row(col, text)


def draw_curve(layout, p, sp):
    """画出折线。多源约束会把同通道的曲线叠在一起画，每个驱动一种颜色。"""
    from . import jcns_cm
    sources = list(p.sources) if len(p.sources) > 1 else [sp]
    plotted = []
    for s in sources:
        k = jcns_cm.keys(s)
        plotted.append({'cm': k} if k else s)
    icon = _curve_icon(plotted)
    if icon is None:
        return
    box = layout.box()
    box.label(text=T("editors.curve.title"), icon='FCURVE')
    row = box.row()
    row.alignment = 'CENTER'
    row.template_icon(icon_value=icon, scale=7.0)

    if len(sources) > 1:
        legend = box.column(align=True)
        for i, s in enumerate(sources):
            swatch = _swatch_icon(i)
            r = legend.row(align=True)
            if swatch is not None:
                r.label(text="", icon_value=swatch)
            r.label(text=T("editors.curve.legend", i, s.source_bone or "?", s.source_axis))


def _unit_title(name, unit):
    unit = unit.strip()
    return T("editors.unit_title", name, unit) if unit else name


def draw_anchors(layout, m, sp, c):
    """六个锚点数值，每个数值右边是「从当前姿态取值」按钮。"""
    src_ok, tgt_ok = jcns_capture.sides_readable(c, sp)
    col2 = layout.column(align=True)
    col2.separator()
    col2.prop(sp, "mid_point")
    col2.prop(sp, "interpolation")
    h = col2.row()
    h.label(text=_unit_title(T("editors.word.driver"), m.source_unit(sp)))
    h.label(text=T("editors.anchor.a"))
    h.label(text=T("editors.anchor.b"))
    h.label(text=T("editors.anchor.c"))
    rw = col2.row(align=True)
    rw.label(text="")
    for field in ("from_start", "from_kink", "from_end"):
        jcns_capture.anchor_cell(rw, sp, field, src_ok)

    h = col2.row()
    h.label(text=_unit_title(T("editors.word.output"), _target_unit(c.p.transform_element)))
    h.label(text="A′")
    h.label(text="B′")
    h.label(text="C′")
    rw = col2.row(align=True)
    rw.label(text="")
    for field in ("to_start", "to_kink", "to_end"):
        jcns_capture.anchor_cell(rw, sp, field, tgt_ok)


def draw_keyframes(layout, m, sp, cm_ok, reason):
    """这个驱动用关键帧曲线代替折线映射。"""
    from . import jcns_cm
    keys = jcns_cm.keys(sp) or []
    su = m.source_unit(sp)
    box = layout.box()
    box.label(text=T("editors.keys.title", len(keys)), icon='IPO_BEZIER')
    if not cm_ok:
        box.label(text=reason, icon='LOCKED')
    col = box.column(align=True)
    for x, y, s_in, s_out in keys[:12]:
        col.label(text=T("editors.keys.row", _fmt(x), su, _fmt(y), _fmt(s_in), _fmt(s_out)),
                  icon='KEYFRAME')
    if len(keys) > 12:
        col.label(text=T("editors.keys.more", len(keys)))
    if any(abs(getattr(sp, n)) > 1e-9 for n in ('from_start', 'from_kink', 'from_end',
                                                'to_start', 'to_kink', 'to_end')):
        _warn_row(box, T("editors.keys.anchors_nonzero"))
    row = box.row(align=True)
    row.operator("jcns.cm_edit", icon='GRAPH')
    sub = row.row(align=True)
    sub.enabled = cm_ok
    sub.operator("jcns.cm_normalize", icon='HANDLE_FREE')
    sub.operator("jcns.cm_remove", icon='X')


def _draw_rules(layout, lines):
    """Rule lines from jcns_source_read: a tick for a known rule, a question mark
    for an inferred one."""
    col = layout.column(align=True)
    for text, measured in lines:
        col.label(text=text, icon='CHECKMARK' if measured else 'QUESTION')


def _early_read_axes(c, p, sp):
    """Axes of the driving bone that this entry or a later one drives: the engine
    evaluates entries in file order, so those are read before they are constrained."""
    from . import jcns_operators
    if c.root is None or not sp.source_bone:
        return []
    later = jcns_operators._written_from(c.root, c.obj)
    q = _mapping().source_quantity(sp.input_type)
    path = jcns_operators.QUANTITY_PATH[q]
    axes = (0, 1, 2) if q != 'Scale' else ({'X': 0, 'Y': 1, 'Z': 2}.get(sp.source_axis, 0),)
    return [a for a in axes if (sp.source_bone, path, a) in later]


class JCNS_PT_Ed_Ranges(_EditorMain, Panel):
    bl_label  = T("editors.word.driven")
    bl_description = T("editors.panel.driven_desc")
    bl_idname = "JCNS_PT_ed_ranges"
    KIND = 'Outputs'

    def draw(self, context):
        from . import sibling_constraints, get_constraint_empties, jcns_merge_ops
        c = _begin(self.layout, context)
        if c is None:
            return
        layout, obj, p = c.body, c.obj, c.p

        col = layout.column(align=True)
        _field_row(col, T("editors.field.bone"), p, "target_bone")
        _field_row(col, T("editors.field.local_axis"), p, "target_axis")
        _field_row(col, T("editors.field.transform"), p, "transform_element")
        from .jcns_exporter import _transform_int
        if p.target_property or _targets().has_property_name(_transform_int(p.transform_element)):
            _field_row(col, T("editors.field.property"), p, "target_property")
        _field_row(col, T("editors.field.base_pose"), p, "base_pose")

        # 导出按 [N] 前缀排列；同一通道上后写的那条覆盖前面的。
        sibs = sibling_constraints(obj)
        if sibs:
            ordered = get_constraint_empties(c.root) if c.root else []
            members = [e for e in ordered if e is obj or e in sibs] if ordered else [obj]
            jcns_merge_ops.draw_channel_merge(layout.box(), context, members, c.rp, obj)


class JCNS_PT_Ed_Ranges_Sources(_Editor, Panel):
    bl_label  = T("editors.panel.sources")
    bl_idname = "JCNS_PT_ed_ranges_sources"
    bl_parent_id = "JCNS_PT_edit"
    KIND = 'Outputs'

    def draw_header(self, context):
        from . import get_jcns_constraint, get_jcns_root_from_constraint
        from .jcns_operators import _caps_for
        _, rp = get_jcns_root_from_constraint(get_jcns_constraint(context)[0])
        row = self.layout.row(align=True)
        row.enabled = rp is not None and _caps_for(rp, 'Outputs').can_add   # sources come and go only where entries can
        row.operator("jcns.add_source", text="", icon='ADD')
        row.operator("jcns.remove_source", text="", icon='REMOVE')

    def draw(self, context):
        c = _begin(self.layout, context, banner=False)
        if c is None:
            return
        p = c.p
        if not len(p.sources):
            c.body.label(text=T("editors.sources.none"), icon='INFO')
            return
        # 只有一个驱动时不画列表：下面的详情已写出骨骼和轴。
        if len(p.sources) > 1:
            c.body.template_list("JCNS_UL_sources", "", p, "sources",
                                 p, "active_source_index",
                                 rows=min(len(p.sources), 6))
        sp = _active_source(p)
        col = c.body.column(align=True)
        if len(p.sources) > 1:
            col.label(text=T("editors.sources.item", p.active_source_index), icon='BONE_DATA')
        _field_row(col, T("editors.field.bone"), sp, "source_bone")
        _field_row(col, T("editors.field.local_axis"), sp, "source_axis")
        _field_row(col, T("editors.field.input_type"), sp, "input_type")
        row = col.row(align=True)
        row.active = sp.input_type == 'EULER'          # the other reads ignore it
        _field_row(row, T("editors.field.rot_order"), sp, "rot_order")
        row = col.row(align=True)
        row.active = sp.input_type in ('SWING_TWIST', 'TWIST_SWING', 'ROTATION_VECTOR')   # the other reads ignore it
        row.label(text=T("editors.field.ref_frame"))
        for axis in "xyzw":
            row.prop(sp, "ref_frame_" + axis, text=axis.upper())
        early = _early_read_axes(c, p, sp)
        if early:
            _warn_row(c.body, T("editors.sources.early_read", "/".join("XYZ"[a] for a in early)))


class JCNS_PT_Ed_Ranges_Mapping(_Editor, Panel):
    bl_label  = T("editors.panel.mapping")
    bl_idname = "JCNS_PT_ed_ranges_mapping"
    bl_parent_id = "JCNS_PT_edit"
    KIND = 'Outputs'

    @classmethod
    def poll(cls, context):
        from . import get_jcns_constraint
        if not super().poll(context):
            return False
        return _active_source(get_jcns_constraint(context)[1]) is not None

    def draw_header(self, context):
        self.layout.label(text="", icon='FCURVE')

    def draw(self, context):
        c = _begin(self.layout, context, banner=False)
        if c is None:
            return
        p = c.p
        sp = _active_source(p)
        m = _mapping()
        if len(p.sources) > 1:
            c.body.label(text=T("editors.mapping.driver_item", p.active_source_index,
                                sp.source_bone or '?', sp.source_axis), icon='BONE_DATA')
        from . import file_state, jcns_cm
        cm_ok, reason = _kinds().complex_mapping_editable(file_state(c.rp))
        jcns_capture.draw_readout(c.body, c, sp)
        if jcns_cm.has_curve(sp):
            draw_curve(c.body, p, sp)
            draw_keyframes(c.body, m, sp, cm_ok, reason)
            return
        draw_mapping_warnings(c.body, p, sp, m)
        draw_curve(c.body, p, sp)
        draw_anchors(c.body, m, sp, c)
        row = c.body.row()
        row.enabled = cm_ok
        row.operator("jcns.cm_create", icon='IPO_BEZIER')


class JCNS_PT_Ed_Ranges_Cones(_Editor, Panel):
    bl_label  = T("editors.panel.cones")
    bl_description = T("editors.panel.cones_desc")
    bl_idname = "JCNS_PT_ed_ranges_cones"
    bl_parent_id = "JCNS_PT_edit"
    KIND = 'Outputs'

    @classmethod
    def poll(cls, context):
        from . import get_jcns_constraint, get_jcns_root_from_constraint
        if not super().poll(context):
            return False
        obj, p = get_jcns_constraint(context)
        _, rp = get_jcns_root_from_constraint(obj)
        return bool(len(p.cone_drivers) or (rp and rp.cone_inputs_json))

    def draw(self, context):
        c = _begin(self.layout, context, banner=False)
        if c is None:
            return
        layout, p = c.body, c.p
        row = layout.row()
        row.template_list("JCNS_UL_cone_drivers", "", p, "cone_drivers", p, "active_cone_driver_index",
                          rows=min(max(len(p.cone_drivers), 2), 8))
        col = row.column(align=True)
        col.operator("jcns.cone_driver_add", text="", icon='ADD')
        col.operator("jcns.cone_driver_remove", text="", icon='REMOVE')
        if len(p.cone_drivers):
            k = p.cone_drivers[min(p.active_cone_driver_index, len(p.cone_drivers) - 1)]
            box = layout.box()
            box.prop(k, "value")
            box.row(align=True).prop(k, "rest", text="Rest")
            r = box.row(align=True)
            r.prop(k, "unk_byte0")
            r.prop(k, "unk_byte3")


class JCNS_PT_Ed_Ranges_Tools(_Editor, Panel):
    bl_label  = T("editors.panel.tools")
    bl_idname = "JCNS_PT_ed_ranges_tools"
    bl_parent_id = "JCNS_PT_edit"
    KIND = 'Outputs'

    def draw_header(self, context):
        self.layout.label(text="", icon='TOOL_SETTINGS')

    def draw(self, context):
        c = _begin(self.layout, context, banner=False)
        if c is None:
            return
        sub = self.layout.column(align=True)
        sub.enabled = c.caps.can_add          # mirroring and merging create or delete entries
        sub.operator("jcns.mirror_constraints", text=T("editors.tools.mirror"), icon='MOD_MIRROR')
        sub.operator("jcns.merge_all_channels", icon='AUTOMERGE_ON')


class JCNS_PT_Ed_Ranges_Advanced(_Editor, _Sub, Panel):
    bl_label  = T("editors.panel.advanced")
    bl_description = T("editors.panel.advanced_desc")
    bl_idname = "JCNS_PT_ed_ranges_advanced"
    bl_parent_id = "JCNS_PT_edit"
    KIND = 'Outputs'

    def draw_header(self, context):
        self.layout.label(text="", icon='PREFERENCES')

    def draw(self, context):
        c = _begin(self.layout, context, banner=False)
        if c is None:
            return
        layout, p = c.body, c.p
        sp = _active_source(p)

        from .jcns_exporter import _transform_int
        from .jcns_drivers import jcns_source_read as sr
        lines = list(sr.target_rule(_transform_int(p.transform_element), p.base_pose))
        if sp is not None:
            lines += sr.read_rule(sp.input_type, sr.rot_order_value(sp.rot_order),
                                  abs(sp.ref_frame_w) >= 1.0 - 1e-9)
        _draw_rules(layout.box(), lines)

        if sp is not None:
            _draw_raw_group(layout, T("editors.word.driver"), 'PREFERENCES', [
                (sp, [("attr_flags_other", T("editors.adv.attr_flags_other"))]),
                (sp, [("unknown_uint16_22", "+22"), ("curve_type", "+29")]),
            ])
        box = _draw_raw_group(layout, T("editors.word.driven"), 'PREFERENCES', [
            (p, [("attr_flags_other", T("editors.adv.attr_flags_other"))]),
            (p, [("unknown_float2_x", "Float2 X"), ("unknown_float2_y", "Y")]),
            (p, [("unknown_byte_72", "+72"), ("unknown_byte_74", "+74"), ("unknown_byte_75", "+75")]),
        ])
        box.label(text=T("editors.adv.flags_note"), icon='INFO')
        info = box.column(align=True)
        info.label(text=T("editors.adv.group_count", p.group_count))
        _draw_raw_group(layout, T("editors.adv.hash_override"), 'PREFERENCES', [
            (p, [("property_hash", T("editors.adv.property_hash")), ("object_hash", T("editors.adv.object_hash"))]),
        ])
        _draw_raw_group(layout, T("editors.adv.fixed_vec4"), 'PREFERENCES', [
            (p, [("reserved_vec4_x", "X"), ("reserved_vec4_y", "Y"),
                 ("reserved_vec4_z", "Z"), ("reserved_vec4_w", "W")]),
        ])
        _draw_raw_group(layout, T("editors.adv.fixed_zero"), 'PREFERENCES',
                    [(p, [("reserved_tail", "+76 / +78 / +79")])])


# ---------------------------------------------------------------------------
# Multi —— 蒙皮权重
# ---------------------------------------------------------------------------

class JCNS_PT_Ed_Multi(_EditorMain, Panel):
    bl_label  = T("editors.panel.multi")
    bl_idname = "JCNS_PT_ed_multi"
    KIND = 'Multi'

    def draw(self, context):
        c = _begin(self.layout, context)
        if c is None:
            return
        p, rp = c.p, c.rp
        box = c.body.box()
        locked = _multi_table_locked(rp)
        _field_row(box.column(align=True), T("editors.field.driven"), p, "target_bone")
        if locked:
            box.label(text=T("editors.multi.need_armature"), icon='INFO')
        hdr = box.row(align=True)
        hdr.label(text=T("editors.word.driver"), icon='BONE_DATA')
        sub = hdr.row(align=True)
        sub.enabled = not locked
        sub.operator("jcns.multi_source_add", text="", icon='ADD')
        sub.operator("jcns.multi_source_remove", text="", icon='REMOVE')
        box.template_list("JCNS_UL_multi_sources", "", p, "multi_sources",
                          p, "active_multi_source_index",
                          rows=min(max(len(p.multi_sources), 2), 8))
        total = sum(w.weight for w in p.multi_sources)
        row = box.row(align=True)
        row.label(text=T("editors.multi.weight_sum", total),
                  icon='INFO' if p.multi_sources and abs(total - 1.0) > 1e-3 else 'CHECKMARK')
        row.operator("jcns.multi_normalize_weights", text=T("editors.multi.normalize"))


class JCNS_PT_Ed_Multi_Reserved(_Editor, _Sub, Panel):
    bl_label  = T("editors.panel.advanced")
    bl_idname = "JCNS_PT_ed_multi_reserved"
    bl_parent_id = "JCNS_PT_ed_multi"
    KIND = 'Multi'

    def draw(self, context):
        c = _begin(self.layout, context, banner=False)
        if c is None:
            return
        _draw_raw_group(c.body, T("editors.multi.v102_zero"), 'PREFERENCES',
                    [(c.p, [("multi_tail", T("editors.multi.tail"))])])


# ---------------------------------------------------------------------------
# Aim —— 瞄准
# ---------------------------------------------------------------------------

class JCNS_PT_Ed_Aim(_EditorMain, Panel):
    bl_label  = T("editors.panel.aim")
    bl_idname = "JCNS_PT_ed_aim"
    KIND = 'Aim'

    def draw(self, context):
        c = _begin(self.layout, context)
        if c is None:
            return
        p = c.p
        col = c.body.box().column(align=True)
        _field_row(col, T("editors.field.driven"), p, "target_bone")
        if _multi_table_locked(c.rp):
            col.label(text=T("editors.aim.need_armature"), icon='INFO')
        _field_row(col, T("editors.field.aim_target"), p, "aim_target_bone")
        _field_row(col, T("editors.field.type"), p, "world_up_type")
        row = col.row(align=True)
        row.active = p.world_up_type in ('OBJECT_UP', 'OBJECT_ROTATION_UP')
        _field_row(row, T("editors.field.up_bone"), p, "aim_up_bone")
        _field_row(col, T("editors.field.influence"), p, "aim_influence")
        vec = c.body.box().column(align=True)
        vec.label(text=T("editors.aim.vectors"), icon='ORIENTATION_LOCAL')
        for name in ("aim_axis", "aim_up_axis"):
            vec.prop(p, name)
        row = vec.column(align=True)
        row.active = p.world_up_type in ('VECTOR', 'OBJECT_ROTATION_UP')
        row.prop(p, "aim_up_dir")
        vec.prop(p, "aim_offset")


# 各类型怎样定翻滚。
_AIM_RULES = {
    'SCENE_UP': [("editors.aim.rule.scene_up", True)],
    'OBJECT_UP': [("editors.aim.rule.object_up", True)],
    'OBJECT_ROTATION_UP': [("editors.aim.rule.object_rotation_up", True)],
    'VECTOR': [("editors.aim.rule.vector", True)],
    'NONE': [("editors.aim.rule.none", True)],
    'NONE_MAYA_LIKE': [("editors.aim.rule.none_maya_like", True)],
}


class JCNS_PT_Ed_Aim_Raw(_Editor, _Sub, Panel):
    bl_label  = T("editors.panel.advanced")
    bl_idname = "JCNS_PT_ed_aim_raw"
    bl_parent_id = "JCNS_PT_ed_aim"
    KIND = 'Aim'

    def draw(self, context):
        c = _begin(self.layout, context, banner=False)
        if c is None:
            return
        p = c.p
        _draw_rules(c.body.box(), [(T(k), measured) for k, measured in _AIM_RULES[p.world_up_type]])
        _draw_raw_group(c.body, T("editors.adv.fields_unknown"), 'PREFERENCES', [
            (p, [("aim_bytes", "")]),
        ])


# ---------------------------------------------------------------------------
# RotExpression —— 旋转表达式
# ---------------------------------------------------------------------------

class JCNS_PT_Ed_RotExpr(_EditorMain, Panel):
    bl_label  = T("editors.panel.rotexpr")
    bl_idname = "JCNS_PT_ed_rotexpr"
    KIND = 'RotExpression'

    def draw(self, context):
        c = _begin(self.layout, context)
        if c is None:
            return
        col = c.body.box().column(align=True)
        _field_row(col, T("editors.field.driven"), c.p, "target_bone")
        _field_row(col, T("editors.field.driver"), c.p, "rot_source_bone")
        _field_row(col, T("editors.field.rest_pose"), c.p, "rot_rest_mode")
        col.prop(c.p, "rot_gains")


_ROT_RULES = {
    'REPLACE': [("editors.rot.rule.replace", True),
                ("editors.rot.rule.nonlinear", False)],
    'ADD_REST': [("editors.rot.rule.add_rest", True),
                 ("editors.rot.rule.nonlinear", False)],
}


class JCNS_PT_Ed_RotExpr_Raw(_Editor, _Sub, Panel):
    bl_label  = T("editors.panel.advanced")
    bl_idname = "JCNS_PT_ed_rotexpr_raw"
    bl_parent_id = "JCNS_PT_ed_rotexpr"
    KIND = 'RotExpression'

    def draw(self, context):
        c = _begin(self.layout, context, banner=False)
        if c is None:
            return
        p = c.p
        _draw_rules(c.body.box(), [(T(k), measured) for k, measured in _ROT_RULES[p.rot_rest_mode]])
        _draw_raw_group(c.body, T("editors.adv.fields_unknown"), 'PREFERENCES',
                    [(p, [("rot_unknown_bytes", "")])])
        _draw_raw_group(c.body, T("editors.rot.reserved"), 'PREFERENCES', [
            (p, [("rot_rotation", "")]), (p, [("rot_scale", "")]),
        ])


# ---------------------------------------------------------------------------
# Material —— 材质
# ---------------------------------------------------------------------------

class JCNS_PT_Ed_Material(_EditorMain, Panel):
    bl_label  = T("editors.panel.material")
    bl_idname = "JCNS_PT_ed_material"
    KIND = 'Material'

    def draw(self, context):
        c = _begin(self.layout, context)
        if c is None:
            return
        col = c.body.box().column(align=True)
        _field_row(col, T("editors.field.bone"), c.p, "target_bone", icon='BONE_DATA')
        _field_row(col, T("editors.mat.name"), c.p, "mat_name", icon='MATERIAL')
        _field_row(col, T("editors.mat.property"), c.p, "mat_property", icon='PROPERTIES')
        _field_row(col, T("editors.mat.apply_mode"), c.p, "mat_apply_mode")
        _wrap_label(c.body, context, T("editors.mat.untested"), icon='QUESTION')


class JCNS_PT_Ed_Material_Raw(_Editor, _Sub, Panel):
    bl_label  = T("editors.panel.raw_fields")
    bl_idname = "JCNS_PT_ed_material_raw"
    bl_parent_id = "JCNS_PT_ed_material"
    KIND = 'Material'
    bl_options = set()          # the hashes are all there is to edit here

    def draw(self, context):
        c = _begin(self.layout, context, banner=False)
        if c is None:
            return
        p = c.p
        _draw_raw_group(c.body, T("editors.mat.hashes_title"), 'PREFERENCES', [
            (p, [("mat_name_hash", T("editors.mat.name_hash")),
                 ("mat_property_hash", T("editors.mat.property_hash"))]),
            (p, [("mat_tail_0", T("editors.mat.tail0")),
                 ("mat_tail_1", T("editors.mat.tail1")),
                 ("mat_tail_2", T("editors.mat.tail2"))]),
        ])


# ---------------------------------------------------------------------------
# Unknown —— 导入器不认识的类型
# ---------------------------------------------------------------------------

class JCNS_PT_Ed_Unknown(_EditorMain, Panel):
    bl_label  = T("editors.panel.unrecognized")
    bl_idname = "JCNS_PT_ed_unknown"
    KIND = 'Unknown'

    def draw(self, context):
        c = _begin(self.layout, context)
        if c is None:
            return
        self.layout.label(text=T("editors.unrecognized.type", c.p.constraint_type or '?'), icon='ERROR')


# ---------------------------------------------------------------------------
# 注册（父面板必须先于子面板）
# ---------------------------------------------------------------------------

_classes = [
    JCNS_PT_Ed_Ranges,
    JCNS_PT_Ed_Ranges_Sources,
    JCNS_PT_Ed_Ranges_Mapping,
    JCNS_PT_Ed_Ranges_Cones,
    JCNS_PT_Ed_Ranges_Tools,
    JCNS_PT_Ed_Ranges_Advanced,
    JCNS_PT_Ed_Multi,
    JCNS_PT_Ed_Multi_Reserved,
    JCNS_PT_Ed_Aim,
    JCNS_PT_Ed_Aim_Raw,
    JCNS_PT_Ed_RotExpr,
    JCNS_PT_Ed_RotExpr_Raw,
    JCNS_PT_Ed_Material,
    JCNS_PT_Ed_Material_Raw,
    JCNS_PT_Ed_Unknown,
]


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
