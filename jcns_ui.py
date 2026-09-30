"""
jcns_ui.py
----------
侧边栏（View3D > 侧栏 > JCNS 编辑器）的框架：状态、文件、分区浏览器。

每个 section 自己的编辑界面在 jcns_editors.py；哪些分区存在、各自能做什么由
modules/jcns_kinds.py 决定，预览（驱动器 / 骨骼约束）由 jcns_preview.py 负责。

面板按「你多久看一次」分层：

  JCNS_PT_Status            始终显示 —— 导入/导出、工作集合、骨架
  JCNS_PT_File              文件 —— 名称、版本
    JCNS_PT_FileInfo          文件级数据（ObjectSettings、ConeDriver 表、读取骨表）
  JCNS_PT_Browser           分区浏览器 —— 图标标签页 + 条目列表 + 增删换序
    JCNS_PT_BrowserPreview    当前分区的预览（驱动器 / 骨骼约束）
    JCNS_PT_BrowserChannels   Ranges：按被驱动的骨骼通道分组
  （jcns_editors.py）       当前条目的编辑器，每种类型各一组面板
"""

import os
import sys

import bpy
from bpy.types import Panel


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

def _mapping():
    """和驱动器共用同一套映射数学。"""
    modules_dir = os.path.join(os.path.dirname(__file__), "modules")
    if modules_dir not in sys.path:
        sys.path.insert(0, modules_dir)
    import jcns_mapping
    return jcns_mapping


def _curve():
    modules_dir = os.path.join(os.path.dirname(__file__), "modules")
    if modules_dir not in sys.path:
        sys.path.insert(0, modules_dir)
    import jcns_curve
    return jcns_curve


# 只画当前选中的约束，共用一个预览槽位，图像数据不会累积。
_preview_coll = None
_preview_key = None
CURVE_W, CURVE_H = 180, 110


def _curve_icon(sources):
    """当前映射的 icon_id；缓存键不变就不重新光栅化。"""
    global _preview_key
    if _preview_coll is None:
        return None
    c = _curve()
    key = c.cache_key(sources, CURVE_W, CURVE_H)
    prev = _preview_coll.get("mapping")
    if prev is None:
        prev = _preview_coll.new("mapping")
        _preview_key = None
    if key != _preview_key:
        pixels, _info = c.render(sources, CURVE_W, CURVE_H)
        prev.image_size = (CURVE_W, CURVE_H)
        prev.image_pixels_float = pixels
        _preview_key = key
    return prev.icon_id


def _swatch_icon(index):
    """icon_id for a flat colour square, one per palette slot, built once."""
    if _preview_coll is None:
        return None
    c = _curve()
    slot = index % len(c.PALETTE)
    name = "swatch%d" % slot
    prev = _preview_coll.get(name)
    if prev is None:
        prev = _preview_coll.new(name)
        prev.image_size = (8, 8)
        prev.image_pixels_float = c.swatch(c.PALETTE[slot], 8, 8)
    return prev.icon_id


def _active_source(p):
    if not len(p.sources):
        return None
    return p.sources[min(p.active_source_index, len(p.sources) - 1)]


def _fmt(v):
    """-15.0 -> -15，1.25 保留。"""
    return ("%+.0f" % v) if abs(v - round(v)) < 0.005 else ("%+.2f" % v)


def _field_row(layout, label, data, prop, icon='NONE', **kwargs):
    """一行「标签 | 取值」，按固定比例分栏，所有面板的主字段共用这套排版。

    一组共享一个概念的紧凑数值（向量分量、字节尾巴）走 _draw_raw_group()。
    """
    row = layout.row(align=True)
    split = row.split(factor=0.4)
    split.label(text=label, icon=icon)
    split.prop(data, prop, text="", **kwargs)
    return row


def _draw_raw_group(layout, title, icon, rows):
    """一组共享一个概念的紧凑数值，放在一个 box 里。

    `rows` 是若干 (data, [(prop, short_label), ...]) 对，每一对占一行。
    """
    box = layout.box()
    box.label(text=title, icon=icon)
    col = box.column(align=True)
    for data, props in rows:
        r = col.row(align=True)
        for prop, short_label in props:
            r.prop(data, prop, text=short_label)
    return box


def _skin_table_locked(rp):
    """A shipped ReadJointTable can only be re-derived with the skeleton."""
    return bool(rp and rp.read_joint_signature_json and rp.target_armature is None)


def _target_unit(transform_type):
    """Suffix for a constraint's output values: ° for angles, cm for positions."""
    from .modules_shim import get_flags
    if get_flags().is_angular(transform_type):
        return "°"
    return " cm" if transform_type == 'Translation' else ""


class JCNS_UL_Sources(bpy.types.UIList):
    """每行对应文件里的一个 ConstraintSource_v2 块。"""
    bl_idname = "JCNS_UL_sources"

    def draw_item(self, context, layout, data, item, icon, active_data, active_prop, index):
        info = _mapping().describe(item)
        row = layout.row(align=True)
        swatch = _swatch_icon(index)
        if swatch is not None:
            row.label(text="", icon_value=swatch)
        row.label(text=str(index), icon='DRIVER')
        row.prop(item, "source_bone", text="", emboss=False)
        row.label(text=item.source_axis)
        from . import jcns_cm
        if jcns_cm.has_curve(item):
            row.label(text="", icon='IPO_BEZIER')
        elif info['offset_at_rest']:
            row.label(text="%s%s" % (_fmt(info['at_rest']),
                                     _target_unit(getattr(data, 'transform_type', ''))),
                      icon='ERROR')


class JCNS_UL_SkinSources(bpy.types.UIList):
    """SkinConstraint 条目的源骨骼与权重。"""
    bl_idname = "JCNS_UL_skin_sources"

    def draw_item(self, context, layout, data, item, icon, active_data, active_prop, index):
        row = layout.row(align=True)
        row.prop(item, "bone", text="", emboss=False, icon='BONE_DATA')
        row.prop(item, "weight", text="")


_CONE_NAME_CACHE = {}


def _cone_names(rp):
    """ConeDriver names of a root, from its import cache (parsed once per string)."""
    raw = rp.cone_drivers_json if rp else ''
    if not raw:
        return []
    hit = _CONE_NAME_CACHE.get(raw)
    if hit is None:
        import json
        hit = [cd['Name'] for cd in json.loads(raw)]
        _CONE_NAME_CACHE.clear()
        _CONE_NAME_CACHE[raw] = hit
    return hit


class JCNS_UL_ConeInfos(bpy.types.UIList):
    """ConeDriverInfo：这条约束读取的锥形及其输出值。"""
    bl_idname = "JCNS_UL_cone_infos"

    def draw_item(self, context, layout, data, item, icon, active_data, active_prop, index):
        from . import get_jcns_root_from_constraint
        _, rp = get_jcns_root_from_constraint(context.active_object)
        names = _cone_names(rp)
        row = layout.row(align=True)
        row.prop(item, "cone_index", text="")
        label = names[item.cone_index] if item.cone_index < len(names) else "（不存在）"
        sub = row.row()
        sub.alert = item.cone_index >= len(names)
        sub.label(text=label, icon='CONE')
        row.prop(item, "value", text="")



def _kinds():
    from .modules_shim import get_kinds
    return get_kinds()


def _wrap_label(layout, context, text, icon='NONE', alert=False):
    """一段会按侧栏宽度折行的说明文字。

    UILayout.label 不换行，窄侧栏里长句子会被截断；中文字宽按两个英文字符算。
    """
    region = getattr(context, 'region', None)
    scale = context.preferences.system.ui_scale
    width = max((region.width if region else 260) - 44 * scale, 60)
    per_char = 7.0 * scale
    lines, cur, cur_w = [], '', 0.0
    for ch in text:
        w = per_char * (2 if ord(ch) > 0x2E7F else 1)
        if cur and cur_w + w > width:
            lines.append(cur)
            cur, cur_w = '', 0.0
        cur += ch
        cur_w += w
    if cur:
        lines.append(cur)
    col = layout.column(align=True)
    col.alert = alert
    col.scale_y = 0.85
    for i, line in enumerate(lines):
        col.label(text=line, icon=icon if i == 0 else 'BLANK1')
    return col


def _resolve_root(context):
    """(root, root_props) of the file the panels are about, or (None, None)."""
    from . import get_export_root
    return get_export_root(context)


# ---------------------------------------------------------------------------
# 常驻提示面板
# ---------------------------------------------------------------------------

class JCNS_PT_Status(Panel):
    bl_label    = "MHWs JCNS"
    bl_idname   = "JCNS_PT_status"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = 'JCNS 编辑器'
    bl_order       = 0

    def draw(self, context):
        layout = self.layout

        row = layout.row(align=True)
        row.operator("jcns.import_file", text="导入 JCNS", icon='IMPORT')
        row.operator("jcns.export_file", text="导出 JCNS", icon='EXPORT')

        _field_row(layout, "工作集合：", context.scene, "jcns_active_collection",
                   icon='OUTLINER_COLLECTION')

        root, rp = _resolve_root(context)
        if root is not None:
            _field_row(layout, "骨架：", rp, "target_armature", icon='ARMATURE_DATA')
        else:
            col = layout.column(align=True)
            col.label(text="还没有 JCNS 文件", icon='INFO')
            col.label(text="先导入 .jcns 文件，或选中生成的空物体。")


# ---------------------------------------------------------------------------
# 文件
# ---------------------------------------------------------------------------

def _draw_version_note(layout, rp):
    from .modules_shim import get_schema
    from .jcns_exporter import _root_version
    schema = get_schema()
    v = _root_version(rp)
    col = layout.column(align=True)
    col.label(text=f"v{v} · {schema.VERSION_GAMES.get(v, '未知游戏')}", icon='INFO')
    if v not in schema.VERIFIED_VERSIONS:
        col.label(text="这个版本的支持不完整，导出前请备份原文件", icon='ERROR')


class JCNS_PT_File(Panel):
    bl_label    = "JCNS 文件"
    bl_idname   = "JCNS_PT_file"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = 'JCNS 编辑器'
    bl_order       = 1

    @classmethod
    def poll(cls, context):
        return _resolve_root(context)[0] is not None

    def draw(self, context):
        root, rp = _resolve_root(context)
        box = self.layout.box()
        box.label(text=rp.source_filepath.replace('\\', '/').split('/')[-1] or root.name,
                  icon='FILE')
        _draw_version_note(box, rp)


class JCNS_PT_FileInfo(Panel):
    """不属于任何一条条目、只随文件带着走的数据。"""
    bl_label    = "文件级数据"
    bl_idname   = "JCNS_PT_file_info"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = 'JCNS 编辑器'
    bl_parent_id   = "JCNS_PT_file"
    bl_options     = {'DEFAULT_CLOSED'}

    def draw(self, context):
        import json
        root, rp = _resolve_root(context)
        col = self.layout.column(align=True)
        try:
            n_obj = len(json.loads(rp.object_settings_json)) if rp.object_settings_json else 0
        except ValueError:
            n_obj = 0
        col.label(text="ObjectSettings：%d 条（原样保留）" % n_obj, icon='OBJECT_DATA')
        col.label(text="ConeDriver 表：%d 个" % len(_cone_names(rp)), icon='CONE')
        if rp.read_joint_signature_json:
            col.label(text="读取骨表：有，由 Skin/Aim 的骨骼按骨架层级推出", icon='BONE_DATA')
        else:
            col.label(text="读取骨表：无", icon='BONE_DATA')


# ---------------------------------------------------------------------------
# 分区浏览器
# ---------------------------------------------------------------------------

# 列表和行绘制在同一次重绘里：filter_items 先算好、draw_item 再读。
_SHADOWED = set()        # names of Ranges entries a later entry on the same channel overrides


class JCNS_UL_Entries(bpy.types.UIList):
    """当前分区的条目，按文件顺序排；数据是 Collection.objects，按类型过滤。"""
    bl_idname = "JCNS_UL_entries"

    def filter_items(self, context, data, propname):
        from . import (get_jcns_root_from_collection, is_entry_of, entry_sort_key,
                       group_constraints_by_channel)
        objs = getattr(data, propname)
        n = len(objs)
        flags = [0] * n
        root, rp = get_jcns_root_from_collection(data)
        _SHADOWED.clear()
        if rp is None:
            return flags, []

        kinds = _kinds()
        kind_id = rp.browser_kind
        needle = self.filter_name.lower()
        keyed = []
        for i, o in enumerate(objs):
            if not is_entry_of(o, root):
                continue
            if kinds.kind_of(o.jcns_cns_props.constraint_type).id != kind_id:
                continue
            if needle and needle not in o.name.lower():
                continue
            flags[i] = self.bitflag_filter_item
            keyed.append((entry_sort_key(o), i))
        keyed.sort()

        if kind_id == 'Ranges':
            for members in group_constraints_by_channel(root).values():
                for e in members[:-1]:
                    _SHADOWED.add(e.name)

        order = [0] * n
        visible = [i for _, i in keyed]
        rest = [i for i in range(n) if not flags[i]]
        for pos, i in enumerate(visible + rest):
            order[i] = pos
        return flags, order

    def draw_item(self, context, layout, data, item, icon, active_data, active_prop, index):
        p = item.jcns_cns_props
        kind = _kinds().kind_of(p.constraint_type)
        row = layout.row(align=True)
        row.label(text=item.name, icon=kind.icon)
        if item.name in _SHADOWED:
            sub = row.row()
            sub.alert = True
            sub.label(text="", icon='ERROR')
        if p.preview_on:
            row.label(text="", icon='HIDE_OFF')


class JCNS_PT_Browser(Panel):
    bl_label    = "分区"
    bl_idname   = "JCNS_PT_browser"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = 'JCNS 编辑器'
    bl_order       = 2

    @classmethod
    def poll(cls, context):
        return _resolve_root(context)[0] is not None

    def draw(self, context):
        from . import (entry_collection, entry_counts, file_state,
                       get_jcns_constraint)
        layout = self.layout
        root, rp = _resolve_root(context)
        kinds = _kinds()
        kind = kinds.kind_of(rp.browser_kind)
        caps = kinds.capabilities(kind.id, file_state(rp))

        row = layout.row(align=True)
        row.scale_y = 1.25
        row.prop(rp, "browser_kind", expand=True, icon_only=True)

        n = entry_counts(root).get(kind.id, 0)
        layout.label(text="%s · %d 条" % (kind.label, n), icon=kind.icon)
        if caps.banner:
            _wrap_label(layout, context, caps.banner,
                        icon='LOCKED' if not caps.can_edit else 'INFO')

        # 选中的条目不在当前分区时，编辑器仍会显示它；这里给一个跳过去的按钮。
        obj, p = get_jcns_constraint(context)
        active_kind = kinds.kind_of(p.constraint_type) if p is not None else None
        if active_kind is not None and active_kind.id != kind.id and active_kind.tab:
            layout.prop_enum(rp, "browser_kind", active_kind.id,
                             text="选中的是 %s，切到该分区" % active_kind.label,
                             icon=active_kind.icon)

        coll = entry_collection(root)
        row = layout.row()
        row.template_list("JCNS_UL_entries", "", coll, "objects", rp, "entry_index",
                          rows=3 if n < 3 else min(n, 8), maxrows=12)
        side = row.column(align=True)
        on_kind = active_kind is not None and active_kind.id == kind.id
        if kind.addable:
            sub = side.column(align=True)
            sub.enabled = caps.can_add
            if kind.id == 'Ranges':
                sub.operator("jcns.add_constraint", text="", icon='ADD')
            else:
                sub.operator("jcns.add_section_entry", text="", icon='ADD').kind = kind.id
        sub = side.column(align=True)
        sub.enabled = caps.can_remove and on_kind
        sub.operator("jcns.delete_constraint", text="", icon='REMOVE')
        if kind.ordered:
            side.separator()
            sub = side.column(align=True)
            sub.enabled = caps.can_move and on_kind
            sub.operator("jcns.move_constraint", text="", icon='TRIA_UP').direction = 'UP'
            sub.operator("jcns.move_constraint", text="", icon='TRIA_DOWN').direction = 'DOWN'


class JCNS_PT_BrowserPreview(Panel):
    """当前分区能不能在视口里看到效果：Ranges 是驱动器，其余是骨骼约束。"""
    bl_label    = "预览"
    bl_idname   = "JCNS_PT_browser_preview"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = 'JCNS 编辑器'
    bl_parent_id   = "JCNS_PT_browser"

    @classmethod
    def poll(cls, context):
        root, rp = _resolve_root(context)
        return root is not None and bool(_kinds().kind_of(rp.browser_kind).preview)

    def draw_header(self, context):
        self.layout.label(text="", icon='HIDE_OFF')

    def draw(self, context):
        from . import jcns_preview
        layout = self.layout
        root, rp = _resolve_root(context)
        kind = _kinds().kind_of(rp.browser_kind)
        backend = jcns_preview.backend_of(kind.id)
        on, total = jcns_preview.preview_counts(root, kind.id)

        layout.label(text="%s：已应用 %d / %d" % (backend.noun, on, total),
                     icon='CHECKMARK' if total and on == total else 'BLANK1')
        _wrap_label(layout, context, backend.note,
                    icon='ERROR' if backend.experimental else 'INFO')
        has_arm = rp.target_armature is not None
        if not has_arm:
            _wrap_label(layout, context, "先在上面的「骨架」里设置目标骨架。",
                        icon='ERROR', alert=True)

        col = layout.column(align=True)
        col.enabled = has_arm
        row = col.row(align=True)
        op = row.operator("jcns.preview_apply", text="应用本分区", icon='PLAY')
        op.scope, op.kind = 'KIND', kind.id
        op = row.operator("jcns.preview_clear", text="清除本分区", icon='X')
        op.scope, op.kind = 'KIND', kind.id
        row = col.row(align=True)
        op = row.operator("jcns.preview_apply", text="应用全部分区")
        op.scope = 'FILE'
        op = row.operator("jcns.preview_clear", text="清除全部分区")
        op.scope = 'FILE'


class JCNS_PT_BrowserChannels(Panel):
    """按驱动的骨骼通道分组列出约束，能看出同一个轴上有几条约束、哪一条生效"""
    bl_label    = "被驱动的骨骼"
    bl_idname   = "JCNS_PT_browser_channels"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = 'JCNS 编辑器'
    bl_parent_id   = "JCNS_PT_browser"
    bl_options     = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        root, rp = _resolve_root(context)
        return root is not None and rp.browser_kind == 'Ranges'

    def draw(self, context):
        from . import group_constraints_by_channel
        layout = self.layout
        obj, rp = _resolve_root(context)
        m = _mapping()

        groups = group_constraints_by_channel(obj)
        if not groups:
            layout.label(text="没有 Ranges 类型的约束。", icon='INFO')
            return

        by_bone = {}
        for (bone, transform, axis), members in groups.items():
            by_bone.setdefault(bone or '???', []).append((transform, axis, members))

        active = context.active_object
        total = sum(len(mm) for v in by_bone.values() for _, _, mm in v)
        layout.label(text="%d 根骨骼 · %d 个通道 · %d 条约束"
                          % (len(by_bone), len(groups), total))
        from . import jcns_merge_ops
        jcns_merge_ops.draw_merge_all(layout, context, groups, rp)

        for bone in sorted(by_bone):
            box = layout.box()
            col = box.column(align=True)
            col.label(text=bone, icon='BONE_DATA')

            for transform, axis, members in sorted(by_bone[bone],
                                                   key=lambda x: (x[0], x[1])):
                # Only the last constraint on the channel actually drives it.
                sources = list(members[-1].jcns_cns_props.sources)
                info = m.describe_channel(sources)

                row = col.row(align=True)
                row.alert = info['offset_at_rest']
                applied = any(e.jcns_cns_props.preview_on for e in members)
                icon = ('ERROR' if info['offset_at_rest']
                        else 'DRIVER' if applied else 'BLANK1')
                srcs = "、".join(sorted({sp.source_bone + " " + sp.source_axis
                                        for sp in sources if sp.source_bone})) or "（无）"
                suffix = ""
                if info['offset_at_rest']:
                    suffix = "   静止 %s%s" % (_fmt(info['at_rest']), _target_unit(transform))
                elif info['all_inert']:
                    suffix = "   （无输出）"
                row.label(text="局部 %s 轴 ← %s%s" % (axis, srcs, suffix), icon=icon)

                if len(members) > 1:
                    col.label(text="        %d 条约束合并到此通道" % len(members),
                              icon='DOT')
                for e in members:
                    sub = col.row(align=True)
                    sub.active = (e is active)
                    op = sub.operator("object.select_pattern", text="    " + e.name,
                                      emboss=False)
                    op.pattern = e.name
                    op.extend = False


# ---------------------------------------------------------------------------
# 注册
# ---------------------------------------------------------------------------

_classes = [
    JCNS_UL_Sources,
    JCNS_UL_SkinSources,
    JCNS_UL_ConeInfos,
    JCNS_UL_Entries,
    JCNS_PT_Status,
    JCNS_PT_File,
    JCNS_PT_FileInfo,
    JCNS_PT_Browser,
    JCNS_PT_BrowserPreview,
    JCNS_PT_BrowserChannels,
]


def register():
    global _preview_coll
    import bpy.utils.previews
    _preview_coll = bpy.utils.previews.new()
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    global _preview_coll, _preview_key
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
    if _preview_coll is not None:
        bpy.utils.previews.remove(_preview_coll)
        _preview_coll = None
    _preview_key = None
