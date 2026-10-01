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
from .modules_shim import get_targets as _targets
from .jcns_ui import (_mapping, _fmt, _field_row, _draw_raw_group, _active_source,
                      _skin_table_locked, _target_unit, _curve_icon, _swatch_icon,
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
        _wrap_label(layout, context, "找不到所属的 JCNS 根节点。", icon='ERROR', alert=True)
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
    bl_category    = 'JCNS 编辑器'
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

_ANCHOR_NAMES = {'A': "起点 A", 'B': "折点 B", 'C': "终点 C"}


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
        _warn_row(col, "折点越界，输出恒为 0", "排序锚点", "jcns.sort_anchors")
    if d.get('unreachable_anchor'):
        _warn_row(col, "锚点折返，%s 取不到" % _ANCHOR_NAMES.get(d['unreachable_anchor'], d['unreachable_anchor']),
                  "排序锚点", "jcns.sort_anchors")
    if d['inert']:
        col.label(text="输出锚点全为 0，无输出", icon='RADIOBUT_OFF')
        return
    if d['offset_at_rest']:
        text = "静止时已偏转 %s%s" % (_fmt(d['rest_output']), _target_unit(p.transform_type))
        if m.would_swapping_ends_help(sp):
            _warn_row(col, text, "对调首尾", "jcns.swap_mapto_ends")
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
    box.label(text="曲线（横轴驱动，纵轴输出）", icon='FCURVE')
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
            r.label(text="%d  %s 局部 %s 轴"
                         % (i, s.source_bone or "?", s.source_axis))


def _unit_title(name, unit):
    unit = unit.strip()
    return "%s（%s）" % (name, unit) if unit else name


def draw_anchors(layout, m, sp, c):
    """六个锚点数值，每个数值右边是「从当前姿态取值」按钮。"""
    src_ok, tgt_ok = jcns_capture.sides_readable(c, sp)
    col2 = layout.column(align=True)
    col2.separator()
    col2.prop(sp, "three_point")
    col2.prop(sp, "interpolation")
    h = col2.row()
    h.label(text=_unit_title("驱动", m.source_unit(sp)))
    h.label(text="起点 A")
    h.label(text="折点 B")
    h.label(text="终点 C")
    rw = col2.row(align=True)
    rw.label(text="")
    for field in ("from_start", "from_kink", "from_end"):
        jcns_capture.anchor_cell(rw, sp, field, src_ok)

    h = col2.row()
    h.label(text=_unit_title("输出", _target_unit(c.p.transform_type)))
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
    box.label(text="曲线关键点 %d" % len(keys), icon='IPO_BEZIER')
    if not cm_ok:
        box.label(text=reason, icon='LOCKED')
    col = box.column(align=True)
    for x, y, s_in, s_out in keys[:12]:
        col.label(text="%s%s → %s　　斜率 入 %s / 出 %s"
                       % (_fmt(x), su, _fmt(y), _fmt(s_in), _fmt(s_out)), icon='KEYFRAME')
    if len(keys) > 12:
        col.label(text="……共 %d 个" % len(keys))
    if any(abs(getattr(sp, n)) > 1e-9 for n in ('from_start', 'from_kink', 'from_end',
                                                'to_start', 'to_kink', 'to_end')):
        _warn_row(box, "锚点不为 0，与曲线并存时效果未知")
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
    q = _mapping().source_quantity(sp.read_mode)
    path = jcns_operators._DRIVABLE[q][0]
    axes = (0, 1, 2) if q != 'Scale' else ({'X': 0, 'Y': 1, 'Z': 2}.get(sp.source_axis, 0),)
    return [a for a in axes if (sp.source_bone, path, a) in later]


class JCNS_PT_Ed_Ranges(_EditorMain, Panel):
    """被驱动的骨骼、通道，以及和别的约束共用同一通道时谁生效。"""
    bl_label  = "被驱动"
    bl_idname = "JCNS_PT_ed_ranges"
    KIND = 'Ranges'

    def draw(self, context):
        from . import sibling_constraints, get_constraint_empties, jcns_merge_ops
        c = _begin(self.layout, context)
        if c is None:
            return
        layout, obj, p = c.body, c.obj, c.p

        col = layout.column(align=True)
        _field_row(col, "骨骼：", p, "target_bone")
        _field_row(col, "局部轴向：", p, "target_axis")
        _field_row(col, "变换：", p, "transform_type")
        from .jcns_exporter import _transform_int
        if p.target_property or _targets().has_property_name(_transform_int(p.transform_type)):
            _field_row(col, "属性：", p, "target_property")
        _field_row(col, "叠加：", p, "additive")

        # 导出按 [N] 前缀排列；同一通道上后写的那条覆盖前面的。
        sibs = sibling_constraints(obj)
        if sibs:
            ordered = get_constraint_empties(c.root) if c.root else []
            members = [e for e in ordered if e is obj or e in sibs] if ordered else [obj]
            jcns_merge_ops.draw_channel_merge(layout.box(), context, members, c.rp, obj)


class JCNS_PT_Ed_Ranges_Sources(_Editor, Panel):
    bl_label  = "驱动"
    bl_idname = "JCNS_PT_ed_ranges_sources"
    bl_parent_id = "JCNS_PT_edit"
    KIND = 'Ranges'

    def draw_header(self, context):
        from . import get_jcns_constraint, get_jcns_root_from_constraint
        from .jcns_operators import _caps_for
        _, rp = get_jcns_root_from_constraint(get_jcns_constraint(context)[0])
        row = self.layout.row(align=True)
        row.enabled = rp is not None and _caps_for(rp, 'Ranges').can_add   # sources come and go only where entries can
        row.operator("jcns.add_source", text="", icon='ADD')
        row.operator("jcns.remove_source", text="", icon='REMOVE')

    def draw(self, context):
        c = _begin(self.layout, context, banner=False)
        if c is None:
            return
        p = c.p
        if not len(p.sources):
            c.body.label(text="还没有驱动，无输出", icon='INFO')
            return
        # 只有一个驱动时不画列表：下面的详情已写出骨骼和轴。
        if len(p.sources) > 1:
            c.body.template_list("JCNS_UL_sources", "", p, "sources",
                                 p, "active_source_index",
                                 rows=min(len(p.sources), 6))
        sp = _active_source(p)
        col = c.body.column(align=True)
        if len(p.sources) > 1:
            col.label(text="驱动 %d" % p.active_source_index, icon='BONE_DATA')
        _field_row(col, "骨骼：", sp, "source_bone")
        _field_row(col, "局部轴向：", sp, "source_axis")
        _field_row(col, "读取方式：", sp, "read_mode")
        row = col.row(align=True)
        row.active = sp.read_mode == 'EULER'          # the other reads ignore it
        _field_row(row, "欧拉顺序：", sp, "euler_order")
        row = col.row(align=True)
        row.active = sp.read_mode in ('SWING_TWIST', 'TWIST_SWING', 'ROTATION_VECTOR')   # the other reads ignore it
        row.label(text="参考系：")
        for axis in "xyzw":
            row.prop(sp, "ref_frame_" + axis, text=axis.upper())
        early = _early_read_axes(c, p, sp)
        if early:
            _warn_row(c.body, "驱动的 %s 轴由本条或后面的条目驱动，读到的是静止值"
                              % "/".join("XYZ"[a] for a in early))


class JCNS_PT_Ed_Ranges_Mapping(_Editor, Panel):
    bl_label  = "映射曲线"
    bl_idname = "JCNS_PT_ed_ranges_mapping"
    bl_parent_id = "JCNS_PT_edit"
    KIND = 'Ranges'

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
            c.body.label(text="驱动 %d：%s %s" % (p.active_source_index, sp.source_bone or '?',
                                                  sp.source_axis), icon='BONE_DATA')
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
    """ConeDriver 输入：关节摆进某个锥形的程度驱动这条约束，与驱动并列。"""
    bl_label  = "ConeDriver 输入"
    bl_idname = "JCNS_PT_ed_ranges_cones"
    bl_parent_id = "JCNS_PT_edit"
    KIND = 'Ranges'

    @classmethod
    def poll(cls, context):
        from . import get_jcns_constraint, get_jcns_root_from_constraint
        if not super().poll(context):
            return False
        obj, p = get_jcns_constraint(context)
        _, rp = get_jcns_root_from_constraint(obj)
        return bool(len(p.cone_infos) or (rp and rp.cone_drivers_json))

    def draw(self, context):
        c = _begin(self.layout, context, banner=False)
        if c is None:
            return
        layout, p = c.body, c.p
        row = layout.row()
        row.template_list("JCNS_UL_cone_infos", "", p, "cone_infos", p, "active_cone_info_index",
                          rows=min(max(len(p.cone_infos), 2), 8))
        col = row.column(align=True)
        col.operator("jcns.cone_info_add", text="", icon='ADD')
        col.operator("jcns.cone_info_remove", text="", icon='REMOVE')
        if len(p.cone_infos):
            k = p.cone_infos[min(p.active_cone_info_index, len(p.cone_infos) - 1)]
            box = layout.box()
            box.prop(k, "value")
            box.row(align=True).prop(k, "rest", text="Rest")
            r = box.row(align=True)
            r.prop(k, "unk_byte0")
            r.prop(k, "unk_byte3")


class JCNS_PT_Ed_Ranges_Tools(_Editor, Panel):
    bl_label  = "工具"
    bl_idname = "JCNS_PT_ed_ranges_tools"
    bl_parent_id = "JCNS_PT_edit"
    KIND = 'Ranges'

    def draw_header(self, context):
        self.layout.label(text="", icon='TOOL_SETTINGS')

    def draw(self, context):
        c = _begin(self.layout, context, banner=False)
        if c is None:
            return
        sub = self.layout.column(align=True)
        sub.enabled = c.caps.can_add          # mirroring and merging create or delete entries
        sub.operator("jcns.mirror_constraints", text="镜像到另一侧…", icon='MOD_MIRROR')
        sub.operator("jcns.merge_all_channels", icon='AUTOMERGE_ON')


class JCNS_PT_Ed_Ranges_Advanced(_Editor, _Sub, Panel):
    """引擎的处理规则，含义未知的字段，和取值固定、导出时原样写回的字段。"""
    bl_label  = "高级"
    bl_idname = "JCNS_PT_ed_ranges_advanced"
    bl_parent_id = "JCNS_PT_edit"
    KIND = 'Ranges'

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
        lines = list(sr.target_rule(_transform_int(p.transform_type), p.additive))
        if sp is not None:
            lines += sr.read_rule(sp.read_mode, sr.euler_order_value(sp.euler_order),
                                  abs(sp.ref_frame_w) >= 1.0 - 1e-9)
        _draw_rules(layout.box(), lines)

        if sp is not None:
            _draw_raw_group(layout, "驱动", 'PREFERENCES', [
                (sp, [("curve_mode_extra", "曲线模式其余位")]),
                (sp, [("unknown_uint16_22", "+22"), ("complex_mapping_flag", "+29")]),
            ])
        box = _draw_raw_group(layout, "被驱动", 'PREFERENCES', [
            (p, [("flags_other", "其余标志位")]),
            (p, [("unknown_float2_x", "Float2 X"), ("unknown_float2_y", "Y")]),
            (p, [("unknown_byte_72", "+72"), ("unknown_byte_74", "+74"), ("unknown_byte_75", "+75")]),
        ])
        box.label(text="其余标志位：位4、位5 导出时按变换类型重算；位2、位3 只出现在形变和材质目标上", icon='INFO')
        info = box.column(align=True)
        info.label(text="关节组计数 +77：%d（导出时自动校验）" % p.group_count)
        _draw_raw_group(layout, "哈希覆盖（0 表示按名字计算）", 'PREFERENCES', [
            (p, [("property_hash", "属性"), ("object_hash", "目标")]),
        ])
        _draw_raw_group(layout, "固定为 (0,0,0,1)", 'PREFERENCES', [
            (p, [("reserved_vec4_x", "X"), ("reserved_vec4_y", "Y"),
                 ("reserved_vec4_z", "Z"), ("reserved_vec4_w", "W")]),
        ])
        _draw_raw_group(layout, "固定为 0", 'PREFERENCES', [(p, [("reserved_tail", "+76 / +78 / +79")])])


# ---------------------------------------------------------------------------
# Skin —— 蒙皮权重
# ---------------------------------------------------------------------------

class JCNS_PT_Ed_Skin(_EditorMain, Panel):
    bl_label  = "Skin 蒙皮"
    bl_idname = "JCNS_PT_ed_skin"
    KIND = 'Skin'

    def draw(self, context):
        c = _begin(self.layout, context)
        if c is None:
            return
        p, rp = c.p, c.rp
        box = c.body.box()
        locked = _skin_table_locked(rp)
        _field_row(box.column(align=True), "被驱动：", p, "target_bone")
        if locked:
            box.label(text="先设置目标骨架，才能增删驱动", icon='INFO')
        hdr = box.row(align=True)
        hdr.label(text="驱动", icon='BONE_DATA')
        sub = hdr.row(align=True)
        sub.enabled = not locked
        sub.operator("jcns.skin_source_add", text="", icon='ADD')
        sub.operator("jcns.skin_source_remove", text="", icon='REMOVE')
        box.template_list("JCNS_UL_skin_sources", "", p, "skin_sources",
                          p, "active_skin_source_index",
                          rows=min(max(len(p.skin_sources), 2), 8))
        total = sum(w.weight for w in p.skin_sources)
        row = box.row(align=True)
        row.label(text="权重和 %.3f" % total,
                  icon='INFO' if p.skin_sources and abs(total - 1.0) > 1e-3 else 'CHECKMARK')
        row.operator("jcns.skin_normalize_weights", text="归一化")


class JCNS_PT_Ed_Skin_Reserved(_Editor, _Sub, Panel):
    bl_label  = "高级"
    bl_idname = "JCNS_PT_ed_skin_reserved"
    bl_parent_id = "JCNS_PT_ed_skin"
    KIND = 'Skin'

    def draw(self, context):
        c = _begin(self.layout, context, banner=False)
        if c is None:
            return
        _draw_raw_group(c.body, "v102 固定为 0", 'PREFERENCES', [(c.p, [("skin_tail", "尾部 2 字节")])])


# ---------------------------------------------------------------------------
# Aim —— 瞄准
# ---------------------------------------------------------------------------

class JCNS_PT_Ed_Aim(_EditorMain, Panel):
    bl_label  = "Aim 瞄准"
    bl_idname = "JCNS_PT_ed_aim"
    KIND = 'Aim'

    def draw(self, context):
        c = _begin(self.layout, context)
        if c is None:
            return
        p = c.p
        col = c.body.box().column(align=True)
        _field_row(col, "被驱动：", p, "target_bone")
        if _skin_table_locked(c.rp):
            col.label(text="先设置目标骨架，才能换被驱动", icon='INFO')
        _field_row(col, "瞄准目标：", p, "aim_target_bone")
        _field_row(col, "类型：", p, "aim_type")
        row = col.row(align=True)
        row.active = p.aim_type in ('UP_JOINT_POSITION', 'UP_JOINT_AXIS')
        _field_row(row, "辅助骨骼：", p, "aim_up_bone")
        _field_row(col, "影响：", p, "aim_influence")
        vec = c.body.box().column(align=True)
        vec.label(text="向量", icon='ORIENTATION_LOCAL')
        for name in ("aim_axis", "aim_up_axis"):
            vec.prop(p, name)
        row = vec.column(align=True)
        row.active = p.aim_type in ('UP_DIRECTION', 'UP_JOINT_AXIS')
        row.prop(p, "aim_up_dir")
        vec.prop(p, "aim_offset")


# 各类型怎样定翻滚。
_AIM_RULES = {
    'WORLD_UP': [("本地瞄准轴指向目标，本地上方向轴对齐世界 +Y", True)],
    'UP_JOINT_POSITION': [("本地瞄准轴指向目标，本地上方向轴对齐「自己指向辅助骨」的方向", True)],
    'UP_JOINT_AXIS': [("本地瞄准轴指向目标，本地上方向轴对齐辅助骨的一根局部轴，由「上方向」向量选（(0,1,0) 是 Y 轴，(0,0,1) 是 Z 轴）", True)],
    'UP_DIRECTION': [("本地瞄准轴指向目标，本地上方向轴对齐「上方向」向量给出的世界方向", True)],
    'SHORTEST_ARC': [("从静止姿态朝目标转最短弧，不约束翻滚", True)],
    'SHORTEST_ARC_PARENT': [("从父骨朝向起朝目标转最短弧，丢掉静止姿态", True)],
}


class JCNS_PT_Ed_Aim_Raw(_Editor, _Sub, Panel):
    bl_label  = "高级"
    bl_idname = "JCNS_PT_ed_aim_raw"
    bl_parent_id = "JCNS_PT_ed_aim"
    KIND = 'Aim'

    def draw(self, context):
        c = _begin(self.layout, context, banner=False)
        if c is None:
            return
        p = c.p
        _draw_rules(c.body.box(), _AIM_RULES[p.aim_type])
        _draw_raw_group(c.body, "未知字段", 'PREFERENCES', [
            (p, [("aim_bytes", "")]),
        ])


# ---------------------------------------------------------------------------
# RotExpression —— 旋转表达式
# ---------------------------------------------------------------------------

class JCNS_PT_Ed_RotExpr(_EditorMain, Panel):
    bl_label  = "RotExpr 旋转表达式"
    bl_idname = "JCNS_PT_ed_rotexpr"
    KIND = 'RotExpression'

    def draw(self, context):
        c = _begin(self.layout, context)
        if c is None:
            return
        col = c.body.box().column(align=True)
        _field_row(col, "被驱动：", c.p, "target_bone")
        _field_row(col, "驱动：", c.p, "rot_source_bone")
        _field_row(col, "静止姿态：", c.p, "rot_rest_mode")
        col.prop(c.p, "rot_gains")


_ROT_RULES = {
    'REPLACE': [("结果是驱动旋转按系数缩放后的旋转，不含静止姿态；系数 (1,1,1) 时等于驱动的旋转", True),
                ("系数不是 1 时只有小角度是每轴相乘，大角度偏离线性，精确公式未定", False)],
    'ADD_REST': [("结果 = 静止姿态 · 驱动旋转按系数缩放后的旋转；系数 (1,1,1) 时是精确拷贝", True),
                 ("系数不是 1 时只有小角度是每轴相乘，大角度偏离线性，精确公式未定", False)],
}


class JCNS_PT_Ed_RotExpr_Raw(_Editor, _Sub, Panel):
    bl_label  = "高级"
    bl_idname = "JCNS_PT_ed_rotexpr_raw"
    bl_parent_id = "JCNS_PT_ed_rotexpr"
    KIND = 'RotExpression'

    def draw(self, context):
        c = _begin(self.layout, context, banner=False)
        if c is None:
            return
        p = c.p
        _draw_rules(c.body.box(), _ROT_RULES[p.rot_rest_mode])
        _draw_raw_group(c.body, "未知字段", 'PREFERENCES', [(p, [("rot_unknown_bytes", "")])])
        _draw_raw_group(c.body, "保留字段（Rotation / Scale 恒为 0,0,0,1）", 'PREFERENCES', [
            (p, [("rot_rotation", "")]), (p, [("rot_scale", "")]),
        ])


# ---------------------------------------------------------------------------
# Material —— 材质
# ---------------------------------------------------------------------------

class JCNS_PT_Ed_Material(_EditorMain, Panel):
    bl_label  = "Material 材质"
    bl_idname = "JCNS_PT_ed_material"
    KIND = 'Material'

    def draw(self, context):
        c = _begin(self.layout, context)
        if c is None:
            return
        _field_row(c.body.box().column(align=True), "骨骼：", c.p, "target_bone", icon='BONE_DATA')


class JCNS_PT_Ed_Material_Raw(_Editor, _Sub, Panel):
    bl_label  = "原始字段"
    bl_idname = "JCNS_PT_ed_material_raw"
    bl_parent_id = "JCNS_PT_ed_material"
    KIND = 'Material'
    bl_options = set()          # the hashes are all there is to edit here

    def draw(self, context):
        c = _begin(self.layout, context, banner=False)
        if c is None:
            return
        p = c.p
        _draw_raw_group(c.body, "哈希与变换 ID", 'PREFERENCES', [
            (p, [("mat_name_hash", "材质名哈希"), ("mat_property_hash", "属性哈希")]),
            (p, [("mat_transform_type_raw", "变换ID"), ("mat_tail_0", "尾0"),
                 ("mat_tail_1", "尾1"), ("mat_tail_2", "尾2")]),
        ])


# ---------------------------------------------------------------------------
# JointExportGraph
# ---------------------------------------------------------------------------

class JCNS_PT_Ed_JXG(_EditorMain, Panel):
    bl_label  = "JXG 导出图"
    bl_idname = "JCNS_PT_ed_jxg"
    KIND = 'JointExportGraph'

    def draw(self, context):
        c = _begin(self.layout, context)
        if c is None:
            return
        _field_row(c.body.box().column(align=True), "路径：", c.p, "jxg_path", icon='FILE_FOLDER')


# ---------------------------------------------------------------------------
# Unknown —— 导入器不认识的类型
# ---------------------------------------------------------------------------

class JCNS_PT_Ed_Unknown(_EditorMain, Panel):
    bl_label  = "未知类型"
    bl_idname = "JCNS_PT_ed_unknown"
    KIND = 'Unknown'

    def draw(self, context):
        c = _begin(self.layout, context)
        if c is None:
            return
        self.layout.label(text="类型：%s" % (c.p.constraint_type or '?'), icon='ERROR')


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
    JCNS_PT_Ed_Skin,
    JCNS_PT_Ed_Skin_Reserved,
    JCNS_PT_Ed_Aim,
    JCNS_PT_Ed_Aim_Raw,
    JCNS_PT_Ed_RotExpr,
    JCNS_PT_Ed_RotExpr_Raw,
    JCNS_PT_Ed_Material,
    JCNS_PT_Ed_Material_Raw,
    JCNS_PT_Ed_JXG,
    JCNS_PT_Ed_Unknown,
]


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
