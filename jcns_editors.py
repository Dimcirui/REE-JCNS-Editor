"""
jcns_editors.py
---------------
每种 section 各一组编辑器面板，没有通用表单：

  主面板              JCNS_PT_Ed_<Kind>        只在当前条目是这一类型时出现
    子面板            JCNS_PT_Ed_<Kind>_<Sub>  按需要拆出来，原始字段一律默认折叠

新增编辑器：继承 _Editor，设 KIND，写 draw，注册进 _classes（父面板排在子面板前面）。
类型本身的事实在 modules/jcns_kinds.py，预览在 jcns_preview.py。

每个面板调 _begin()，它按 jcns_kinds.capabilities() 决定整块能否编辑并画出原因。
"""

from types import SimpleNamespace

import bpy
from bpy.types import Panel

from .jcns_ui import (_mapping, _fmt, _field_row, _draw_raw_group, _active_source,
                      _skin_table_locked, _target_unit, _curve_icon, _swatch_icon,
                      _cone_names, _wrap_label, _kinds)


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
    # The browser already shows this for its own tab; repeat it only when the
    # active entry belongs to another one.
    if banner and caps.banner and rp.browser_kind != kind.id:
        _wrap_label(layout, context, caps.banner,
                    icon='LOCKED' if not caps.can_edit else 'INFO')
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
    bl_order = 3

    def draw_header(self, context):
        self.layout.label(text="", icon=_kinds().kind_of(self.KIND).icon)


class _Sub:
    """Mixin: a sub-panel that starts collapsed (raw fields and other rarely-touched data)."""
    bl_options = {'DEFAULT_CLOSED'}


def draw_entry_preview(layout, context, c):
    """The per-entry Apply / Clear block, the same for every previewable kind."""
    from . import jcns_preview
    backend = jcns_preview.backend_of(c.kind.id)
    if backend is None:
        layout.label(text="这一类没有预览", icon='INFO')
        return
    for alert, text in backend.problems(c.obj):
        _wrap_label(layout, context, text, icon='ERROR' if alert else 'INFO', alert=alert)
    if backend.experimental:
        _wrap_label(layout, context, "这一类的预览效果可能与游戏里不同，只适合用来对照。", icon='INFO')
    has_arm = c.rp.target_armature is not None
    if not has_arm:
        _wrap_label(layout, context, "先在上面的「骨架」里设置目标骨架。", icon='ERROR', alert=True)
    col = layout.column(align=True)
    col.scale_y = 1.3
    col.enabled = has_arm
    op = col.operator("jcns.preview_apply",
                      text=("重新应用%s" if c.p.preview_on else "应用%s") % backend.noun,
                      icon='PLAY')
    op.scope = 'ENTRY'
    sub = col.row(align=True)
    sub.enabled = c.p.preview_on
    op = sub.operator("jcns.preview_clear", text="清除%s" % backend.noun, icon='X')
    op.scope = 'ENTRY'


class _PreviewSub(_Editor, _Sub):
    """A kind's preview sub-panel: subclasses only name their parent."""
    bl_label = "预览"
    bl_options = set()

    def draw_header(self, context):
        self.layout.label(text="", icon='HIDE_OFF')

    def draw(self, context):
        c = _begin(self.layout, context, banner=False)
        if c is not None:
            draw_entry_preview(self.layout, context, c)


# ---------------------------------------------------------------------------
# Ranges —— 映射曲线
# ---------------------------------------------------------------------------

def draw_plain(layout, p, sp, m):
    """用文字描述这条映射，从静止姿态出发逐段讲。

    锚点按 A→B→C 存，但递减区间（如 [-60,-15,0]）的静止点在 C，所以不能照数值从左往右念。
    """
    d = m.plain_description(sp)
    box = layout.box()
    col = box.column(align=True)
    src = sp.source_bone or "驱动骨"
    tgt = p.target_bone or "目标骨"
    # Units per side: the source's by its +25, the output's by the target type.
    su = m.source_unit(sp)
    tu = _target_unit(p.transform_type)

    # '<' / '>' shaped anchors in three-point mode: the engine discards the whole
    # source, so the output is silently 0.
    if d.get('folded_dead'):
        warn = col.column(align=True)
        warn.alert = True
        warn.label(text="折点越出 [起点, 终点] 区间，引擎会整条丢弃", icon='ERROR')
        warn.label(text="锚点连成 < 或 > 形，同一输入对应两个输出 —— 输出恒为 0")
        warn.operator("jcns.sort_anchors", text="按源角度排序锚点",
                      icon='SORTSIZE')
        col.separator()

    if d.get('unreachable_anchor'):
        warn = col.column(align=True)
        warn.alert = True
        warn.label(text="锚点顺序折返，终点 %s 永远取不到"
                        % d['unreachable_anchor'], icon='ERROR')
        warn.label(text="改它不会有任何效果 —— 三个源角度需按大小排列")
        warn.operator("jcns.sort_anchors", text="按源角度排序锚点",
                      icon='SORTSIZE')
        col.separator()

    if d['inert']:
        col.label(text="此约束恒无输出（输出锚点全为 0）", icon='RADIOBUT_OFF')
        return

    head = col.row()
    head.alert = d['offset_at_rest']
    if d['offset_at_rest']:
        head.label(text="静止时 %s 已偏转 %s%s" % (tgt, _fmt(d['rest_output']), tu),
                   icon='ERROR')
    else:
        head.label(text="静止时 %s 不动" % tgt, icon='CHECKMARK')

    for leg in d['legs']:
        col.separator(factor=0.4)
        for (x0, x1, y0, y1, kind) in leg['steps']:
            if kind == 'dead':
                col.label(text="%s 局部 %s 轴 %s%s → %s%s：%s 不动"
                               % (src, sp.source_axis, _fmt(x0), su, _fmt(x1), su, tgt))
            else:
                col.label(text="%s 局部 %s 轴 %s%s → %s%s：%s 的局部 %s 轴 %s%s → %s%s"
                               % (src, sp.source_axis, _fmt(x0), su, _fmt(x1), su,
                                  tgt, p.target_axis, _fmt(y0), tu, _fmt(y1), tu))

    if d['offset_at_rest'] and m.would_swapping_ends_help(sp):
        col.separator()
        col.operator("jcns.swap_mapto_ends",
                     text="对调输出首尾（可修正）", icon='ARROW_LEFTRIGHT')

def draw_curve(layout, p, sp):
    """画出折线。多源约束会把同通道的曲线叠在一起画，每个驱动源一种颜色。"""
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
    box.label(text="曲线（横轴：源骨局部轴的值　纵轴：输出）", icon='FCURVE')
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

def draw_anchors(layout, m, sp):
    """三点映射的六个锚点数值。"""
    col2 = layout.column(align=True)
    col2.separator()
    col2.label(text="锚点数值（局部轴；角度为度，位移为厘米）", icon='PREFERENCES')
    h = col2.row()
    h.label(text={'Translation': "源局部位移：", 'Scale': "源局部缩放："}.get(
        m.source_quantity_of(sp), "源局部角："))
    h.label(text="起点 A")
    h.label(text="折点 B")
    h.label(text="终点 C")
    rw = col2.row(align=True)
    rw.label(text="")
    rw.prop(sp, "from_start", text="")
    rw.prop(sp, "from_kink",  text="")
    rw.prop(sp, "from_end",   text="")

    h = col2.row()
    h.label(text="输出：")
    h.label(text="A′")
    h.label(text="B′")
    h.label(text="C′")
    rw = col2.row(align=True)
    rw.label(text="")
    rw.prop(sp, "to_start", text="")
    rw.prop(sp, "to_kink",  text="")
    rw.prop(sp, "to_end",   text="")


def draw_keyframes(layout, m, sp, cm_ok, reason):
    """ComplexMapping：这个驱动源用关键帧曲线代替三点映射。"""
    from . import jcns_cm
    keys = jcns_cm.keys(sp) or []
    su = m.source_unit(sp)
    box = layout.box()
    box.label(text="关键帧曲线（%d 帧，横轴：源的值%s　纵轴：输出）" % (len(keys), su),
              icon='IPO_BEZIER')
    if not cm_ok:
        box.label(text=reason, icon='LOCKED')
    col = box.column(align=True)
    for x, y, s_in, s_out in keys[:12]:
        col.label(text="%s%s → %s　　斜率 入 %s / 出 %s"
                       % (_fmt(x), su, _fmt(y), _fmt(s_in), _fmt(s_out)), icon='KEYFRAME')
    if len(keys) > 12:
        col.label(text="……共 %d 帧" % len(keys))
    if any(abs(getattr(sp, n)) > 1e-9 for n in ('from_start', 'from_kink', 'from_end',
                                                'to_start', 'to_kink', 'to_end')):
        box.label(text="三点映射锚点不为 0：带关键帧的源通常把锚点设为 0，两者同时存在时的效果未知",
                  icon='ERROR')
    row = box.row(align=True)
    row.operator("jcns.cm_edit", icon='GRAPH')
    sub = row.row(align=True)
    sub.enabled = cm_ok
    sub.operator("jcns.cm_normalize", icon='HANDLE_FREE')
    sub.operator("jcns.cm_remove", icon='X')
    box.label(text="手柄只有斜率写进文件，长度不影响游戏；「规范手柄」让曲线编辑器里的样子与游戏一致",
              icon='INFO')


def _draw_rules(layout, lines):
    """Rule lines from jcns_source_read: a tick for a measured rule, a question mark
    for an inferred one."""
    col = layout.column(align=True)
    for text, measured in lines:
        col.label(text=text, icon='CHECKMARK' if measured else 'QUESTION')


def _source_read_notes(c, p, sp):
    """What the engine reads off this source, and whether it reads it too early."""
    from . import jcns_operators
    from .jcns_drivers import jcns_source_read as sr
    lines = sr.read_rule(sp.read_mode, sr.euler_order_value(sp.euler_order),
                         abs(sp.ref_frame_w) >= 1.0 - 1e-9)
    if c.root is not None and sp.source_bone:
        later = jcns_operators._written_from(c.root, c.obj)
        q = _mapping().source_quantity(sp.read_mode)
        path = jcns_operators._DRIVABLE[q][0]
        axes = (0, 1, 2) if q != 'Scale' else ({'X': 0, 'Y': 1, 'Z': 2}.get(sp.source_axis, 0),)
        early = [a for a in axes if (sp.source_bone, path, a) in later]
        if early:
            lines.append(("源骨的 %s 轴由本条或后面的条目驱动：条目按文件顺序求值，引擎读到的是它未被约束的姿态"
                          % "/".join("XYZ"[a] for a in early), True))
    return lines


class JCNS_PT_Ed_Ranges(_EditorMain, Panel):
    """目标骨骼、通道，以及和别的约束抢同一通道时谁生效。"""
    bl_label  = "范围约束"
    bl_idname = "JCNS_PT_ed_ranges"
    KIND = 'Ranges'

    def draw(self, context):
        from . import sibling_constraints, get_constraint_empties
        c = _begin(self.layout, context)
        if c is None:
            return
        layout, obj, p = c.body, c.obj, c.p

        box = layout.box()
        box.label(text="目标", icon='OUTLINER_OB_ARMATURE')
        col = box.column(align=True)
        _field_row(col, "骨骼：", p, "target_bone")
        _field_row(col, "局部轴向：", p, "target_axis")
        _field_row(col, "变换：", p, "transform_type")
        from .jcns_drivers import jcns_source_read as sr
        from .jcns_exporter import _transform_int
        _draw_rules(box, sr.target_rule(_transform_int(p.transform_type), bool(p.cns_flags & 1)))

        # 导出按 [N] 前缀排列；同一通道上后写的那条覆盖前面的。
        sibs = sibling_constraints(obj)
        if sibs:
            ordered = get_constraint_empties(c.root) if c.root else []
            channel_members = [e for e in ordered if e is obj or e in sibs] if ordered else [obj]
            is_winner = bool(channel_members) and channel_members[-1] is obj
            sbox = layout.box()
            scol = sbox.column(align=True)
            scol.label(text="另有 %d 条约束也在驱动 %s 的局部 %s 轴"
                            % (len(sibs), p.target_bone or '?', p.target_axis),
                       icon='INFO')
            for s in sibs:
                scol.label(text="    " + s.name, icon='DOT')
            if is_winner:
                scol.label(text="本条在最后，实际生效的是它。", icon='CHECKMARK')
            else:
                row = scol.row()
                row.alert = True
                row.label(text="本条会被靠后的那条整条覆盖，不产生任何效果。",
                          icon='ERROR')
                scol.label(text="想让它生效，用列表右侧的 ▲▼ 把它移到最后。")


class JCNS_PT_Ed_Ranges_Sources(_Editor, Panel):
    bl_label  = "驱动源"
    bl_idname = "JCNS_PT_ed_ranges_sources"
    bl_parent_id = "JCNS_PT_ed_ranges"
    KIND = 'Ranges'

    def draw_header(self, context):
        self.layout.label(text="", icon='BONE_DATA')

    def draw(self, context):
        c = _begin(self.layout, context, banner=False)
        if c is None:
            return
        p = c.p
        hdr = c.body.row(align=True)
        hdr.label(text="共 %d 个" % len(p.sources))
        sub = hdr.row(align=True)
        sub.enabled = c.caps.can_add          # sources are added/removed only where entries can be
        sub.operator("jcns.add_source", text="", icon='ADD')
        sub.operator("jcns.remove_source", text="", icon='REMOVE')

        if not len(p.sources):
            c.body.label(text="没有驱动源，此约束不会产生任何效果。", icon='INFO')
            return
        # 只有一个源时不画列表：下面的详情已写出骨骼和轴。
        if len(p.sources) > 1:
            c.body.template_list("JCNS_UL_sources", "", p, "sources",
                                 p, "active_source_index",
                                 rows=min(len(p.sources), 6))
        sp = _active_source(p)
        col = c.body.column(align=True)
        if len(p.sources) > 1:
            col.label(text="驱动源 %d" % p.active_source_index, icon='BONE_DATA')
        _field_row(col, "骨骼：", sp, "source_bone")
        _field_row(col, "局部轴向：", sp, "source_axis")
        _field_row(col, "读取方式：", sp, "read_mode")
        row = col.row(align=True)
        row.active = sp.read_mode == 'EULER'          # the other reads ignore it
        _field_row(row, "欧拉顺序：", sp, "euler_order")
        _draw_rules(c.body, _source_read_notes(c, p, sp))


class JCNS_PT_Ed_Ranges_Mapping(_Editor, Panel):
    bl_label  = "映射曲线"
    bl_idname = "JCNS_PT_ed_ranges_mapping"
    bl_parent_id = "JCNS_PT_ed_ranges"
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
            c.body.label(text="驱动源 %d：%s %s" % (p.active_source_index, sp.source_bone or '?',
                                                    sp.source_axis), icon='BONE_DATA')
        from . import file_state, jcns_cm
        cm_ok, reason = _kinds().complex_mapping_editable(file_state(c.rp))
        if jcns_cm.has_curve(sp):
            draw_curve(c.body, p, sp)
            draw_keyframes(c.body, m, sp, cm_ok, reason)
            return
        draw_plain(c.body, p, sp, m)
        draw_curve(c.body, p, sp)
        draw_anchors(c.body, m, sp)
        row = c.body.row()
        row.enabled = cm_ok
        row.operator("jcns.cm_create", icon='IPO_BEZIER')


class JCNS_PT_Ed_Ranges_Cones(_Editor, Panel):
    """ConeDriver 输入：关节摆进某个锥形的程度驱动这条约束，与驱动源并列。"""
    bl_label  = "ConeDriver 输入"
    bl_idname = "JCNS_PT_ed_ranges_cones"
    bl_parent_id = "JCNS_PT_ed_ranges"
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
        names = _cone_names(c.rp)
        layout.label(text="文件共 %d 个 ConeDriver；本约束读取 %d 个" % (len(names), len(p.cone_infos)),
                     icon='INFO')
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
    bl_label  = "预览与工具"
    bl_idname = "JCNS_PT_ed_ranges_tools"
    bl_parent_id = "JCNS_PT_ed_ranges"
    KIND = 'Ranges'

    def draw_header(self, context):
        self.layout.label(text="", icon='HIDE_OFF')

    def draw(self, context):
        c = _begin(self.layout, context, banner=False)
        if c is None:
            return
        draw_entry_preview(self.layout, context, c)
        self.layout.separator()
        sub = self.layout.column()
        sub.enabled = c.caps.can_add          # mirroring creates entries
        sub.operator("jcns.mirror_constraints", text="镜像到另一侧…", icon='MOD_MIRROR')


# 游戏自带 v102 文件里取值固定的 Ranges 原始字段；「隐藏固定字段」只隐藏这些，
# 有例外取值的字段照常显示。
FIXED_RANGES_FIELDS = frozenset((
    'reserved_vec4_x', 'reserved_vec4_y', 'reserved_vec4_z', 'reserved_vec4_w',   # 恒为 (0,0,0,1)
    'parent_tail_2', 'parent_tail_4', 'parent_tail_5',                     # +76/+78/+79 恒为 0
    'flag_bit_1', 'flag_bit_6', 'flag_bit_7',                              # 从未置位
))


class JCNS_PT_Ed_Ranges_Advanced(_Editor, _Sub, Panel):
    """几乎每个文件都相同、或者含义尚未逆向出来的字段。"""
    bl_label  = "高级 / 原始字段"
    bl_idname = "JCNS_PT_ed_ranges_advanced"
    bl_parent_id = "JCNS_PT_ed_ranges"
    KIND = 'Ranges'

    def draw(self, context):
        c = _begin(self.layout, context, banner=False)
        if c is None:
            return
        layout, p = c.body, c.p
        sp = _active_source(p)

        wm = context.window_manager
        hide = wm.jcns_hide_fixed
        top = layout.row(align=True)
        top.prop(wm, "jcns_hide_fixed", toggle=True,
                 icon='HIDE_ON' if hide else 'HIDE_OFF')
        if hide:
            layout.label(text="已隐藏 %d 个取值固定的字段" % len(FIXED_RANGES_FIELDS),
                         icon='INFO')

        def keep(props):
            return [(a, t) for a, t in props if not (hide and a in FIXED_RANGES_FIELDS)]

        if sp is not None:
            _draw_raw_group(layout, "驱动源：参考系四元数", 'ORIENTATION_GIMBAL', [
                (sp, [("ref_frame_x", "X"), ("ref_frame_y", "Y"),
                     ("ref_frame_z", "Z"), ("ref_frame_w", "W")]),
            ])
            box = _draw_raw_group(layout, "驱动源：原始字节", 'PREFERENCES', [
                (sp, [("update_timing", "+24")]),
                (sp, [("unknown_uint16_22", "U16(+22)"), ("unknown_uint32_28", "U32(+28)"),
                     ("complex_mapping_info_count", "复杂映射数")]),
            ])
            box.label(text="+24 是曲线模式（0/1 两点、2/3 三点）；+25/+27 在「驱动源」里", icon='INFO')

        box = layout.box()
        box.label(text="ConstraintInfo 原始字段", icon='PREFERENCES')
        col = box.column(align=True)
        r = col.row(align=True)
        r.prop(p, "cns_flags", text="标志位")
        icon = 'TRIA_DOWN' if p.flags_expanded else 'TRIA_RIGHT'
        r.prop(p, "flags_expanded", text="", icon=icon, emboss=False)
        col.label(text="位4 / 位5 导出时会按变换类型重算，无需手动维护", icon='INFO')
        if p.flags_expanded:
            bits = col.column(align=True)
            for attr, desc in (
                ("flag_bit_0", "位0 —— 叠加：1 叠在静止姿态上，0 替换所写的轴；对缩放不起作用"),
                ("flag_bit_1", "位1"),
                ("flag_bit_2", "位2"),
                ("flag_bit_3", "位3"),
                ("flag_bit_4", "位4 —— 驱动骨骼（v36/v102 导出时按变换类型自动设置）"),
                ("flag_bit_5", "位5 —— 驱动量为旋转（v36/v102 导出时按变换类型自动设置）"),
                ("flag_bit_6", "位6"),
                ("flag_bit_7", "位7"),
            ):
                if hide and attr in FIXED_RANGES_FIELDS:
                    continue
                rb = bits.row(align=True)
                rb.prop(p, attr, text="")
                rb.label(text=desc)

        vec4 = keep([(a, a[-1].upper()) for a in
                     ("reserved_vec4_x", "reserved_vec4_y", "reserved_vec4_z", "reserved_vec4_w")])
        if vec4:
            _draw_raw_group(layout, "未知四维向量 [48..63]", 'PREFERENCES', [(p, vec4)])
        _draw_raw_group(layout, "杂项标量 [64..72]", 'PREFERENCES', [
            (p, [("unknown_float2_x", "X"), ("unknown_float2_y", "Y")]),
            (p, [("unknown_byte_72", "+72"), ("property_hash", "属性哈希")]),
        ])
        _draw_raw_group(layout, "尾部字节 [74..79]", 'PREFERENCES', [
            (p, keep([("parent_tail_0", "+74"), ("parent_tail_1", "+75"), ("parent_tail_2", "+76"),
                      ("parent_tail_3", "+77 组"), ("parent_tail_4", "+78"),
                      ("parent_tail_5", "+79")])),
        ])


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
        _field_row(box.column(align=True), "对象骨骼：", p, "target_bone")
        _field_row(box.column(align=True), "尾部字节：", p, "skin_tail_hex")
        if locked:
            box.label(text="文件带读取骨表：未设目标骨架时只能改权重", icon='INFO')
        elif rp.read_joint_signature_json:
            box.label(text="增删骨骼后，导出时按目标骨架重算读取骨表", icon='INFO')
        hdr = box.row(align=True)
        hdr.label(text="源骨骼（%d）" % len(p.skin_sources), icon='BONE_DATA')
        sub = hdr.row(align=True)
        sub.enabled = not locked
        sub.operator("jcns.skin_source_add", text="", icon='ADD')
        sub.operator("jcns.skin_source_remove", text="", icon='REMOVE')
        box.template_list("JCNS_UL_skin_sources", "", p, "skin_sources",
                          p, "active_skin_source_index",
                          rows=min(max(len(p.skin_sources), 2), 8))
        total = sum(w.weight for w in p.skin_sources)
        row = box.row(align=True)
        if p.skin_sources and abs(total - 1.0) > 1e-3:
            row.label(text="权重和 %.3f，引擎会除以权重和" % total, icon='INFO')
        else:
            row.label(text="权重和 %.3f" % total, icon='CHECKMARK')
        row.operator("jcns.skin_normalize_weights", text="归一化")


class JCNS_PT_Ed_Skin_Preview(_PreviewSub, Panel):
    bl_idname = "JCNS_PT_ed_skin_preview"
    bl_parent_id = "JCNS_PT_ed_skin"
    KIND = 'Skin'


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
        _field_row(col, "被瞄准的骨骼：", p, "target_bone")
        if _skin_table_locked(c.rp):
            col.label(text="文件带读取骨表：未设目标骨架时不能换被瞄准的骨骼", icon='INFO')
        _field_row(col, "瞄准目标：", p, "aim_target_bone")
        _field_row(col, "辅助骨骼：", p, "aim_up_bone")
        _field_row(col, "影响：", p, "aim_influence")


class JCNS_PT_Ed_Aim_Preview(_PreviewSub, Panel):
    bl_idname = "JCNS_PT_ed_aim_preview"
    bl_parent_id = "JCNS_PT_ed_aim"
    KIND = 'Aim'


class JCNS_PT_Ed_Aim_Vectors(_Editor, _Sub, Panel):
    bl_label  = "向量"
    bl_idname = "JCNS_PT_ed_aim_vectors"
    bl_parent_id = "JCNS_PT_ed_aim"
    KIND = 'Aim'

    def draw(self, context):
        c = _begin(self.layout, context, banner=False)
        if c is None:
            return
        p = c.p
        c.body.label(text="Vec1：本地瞄准轴（指向目标）；Vec2：本地对齐上方向的轴", icon='INFO')
        c.body.label(text="类型 0：上方向取世界 +Y，Vec3 无效；3：上方向取 Vec3 给出的世界方向")
        c.body.label(text="类型 1：取辅助骨的位置方向；2：取辅助骨自己的 +Y 轴（Vec3=(0,1,0) 时）")
        c.body.label(text="类型 4：从静止姿态最短弧；5：从父骨朝向最短弧，丢掉静止姿态")
        c.body.label(text="影响不为 1 时的行为和 Vec0 的作用未知")
        col = c.body.column(align=True)
        for name in ("aim_vec0", "aim_vec1", "aim_vec2", "aim_vec3"):
            col.row(align=True).prop(p, name, text="")


class JCNS_PT_Ed_Aim_Raw(_Editor, _Sub, Panel):
    bl_label  = "原始字段"
    bl_idname = "JCNS_PT_ed_aim_raw"
    bl_parent_id = "JCNS_PT_ed_aim"
    KIND = 'Aim'

    def draw(self, context):
        c = _begin(self.layout, context, banner=False)
        if c is None:
            return
        p = c.p
        _draw_raw_group(c.body, "原始字段", 'PREFERENCES', [
            (p, [("aim_rotation_type", "RotationType")]),
            (p, [("aim_bytes", "")]),
            (p, [("aim_tail_hex", "尾部")]), (p, [("aim_target_tail_hex", "目标块尾部")]),
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
        _field_row(col, "被驱动的骨骼：", c.p, "target_bone")
        _field_row(col, "源骨骼：", c.p, "rot_source_bone")


class JCNS_PT_Ed_RotExpr_Preview(_PreviewSub, Panel):
    bl_idname = "JCNS_PT_ed_rotexpr_preview"
    bl_parent_id = "JCNS_PT_ed_rotexpr"
    KIND = 'RotExpression'


class JCNS_PT_Ed_RotExpr_Raw(_Editor, _Sub, Panel):
    bl_label  = "原始字段"
    bl_idname = "JCNS_PT_ed_rotexpr_raw"
    bl_parent_id = "JCNS_PT_ed_rotexpr"
    KIND = 'RotExpression'

    def draw(self, context):
        c = _begin(self.layout, context, banner=False)
        if c is None:
            return
        p = c.p
        _draw_raw_group(c.body, "Rotation/Scale 通常为 0,0,0,1", 'PREFERENCES', [
            (p, [("rot_rotation", "")]), (p, [("rot_scale", "")]),
            (p, [("rot_bytes", "")]), (p, [("rot_floats", "")]),
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
        box = c.body.box()
        box.label(text="关联骨骼", icon='BONE_DATA')
        _field_row(box.column(align=True), "骨骼：", c.p, "target_bone")


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
        _draw_raw_group(c.body, "原始字段", 'PREFERENCES', [
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
        col = c.body.box().column(align=True)
        col.label(text="JointExportGraph 路径", icon='FILE_FOLDER')
        col.prop(c.p, "jxg_path", text="路径")


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
        self.layout.label(text="导出时会原样保留。")


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
    JCNS_PT_Ed_Skin_Preview,
    JCNS_PT_Ed_Aim,
    JCNS_PT_Ed_Aim_Preview,
    JCNS_PT_Ed_Aim_Vectors,
    JCNS_PT_Ed_Aim_Raw,
    JCNS_PT_Ed_RotExpr,
    JCNS_PT_Ed_RotExpr_Preview,
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
