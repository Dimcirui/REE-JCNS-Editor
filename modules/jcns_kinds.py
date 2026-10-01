"""
jcns_kinds.py
-------------
What each kind of JCNS entry is, and what may be done to it.

The UI's tabs, + / - / up / down buttons, lock banner and preview availability
are driven from this table.  How a kind is edited or previewed lives in
jcns_editors.py and jcns_preview.py; this module only routes to them.

Kept free of `bpy` so the rules can be tested offline (tests/test_kinds.py).

`Kind.id` is the value stored in JCNSConstraintProperties.constraint_type.
"""

from dataclasses import dataclass


# ── Kinds ───────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Kind:
    id: str               # constraint_type value
    label: str            # shown in tabs / headers
    icon: str             # Blender icon id
    tab: bool             # has a tab in the browser
    ordered: bool         # entry order is known to matter (up / down allowed)
    addable: bool         # a new entry can be created from the UI
    preview: str          # preview backend id, '' when the kind cannot be previewed
    confidence: str       # how well the engine behaviour is understood
    summary: str          # one line: what the section is for


# `ordered` is true only for Ranges: several Ranges on one channel -> the last one
# wins.  Other sections keep file order on export but offer no reordering.
KINDS = (
    Kind('Ranges', "范围约束", 'DRIVER', tab=True, ordered=True, addable=True,
         preview='driver', confidence="实机验证",  # ui-copy: internal
         summary="源骨骼姿态经三点折线映射，驱动目标骨骼的一个通道"),
    Kind('Skin', "Skin 蒙皮", 'MOD_VERTEX_WEIGHT', tab=True, ordered=False, addable=True,
         preview='constraint', confidence="高（统计推断）",  # ui-copy: internal
         summary="按蒙皮权重把附件骨钉在变形后的皮肤上"),
    Kind('Aim', "Aim 瞄准", 'CON_TRACKTO', tab=True, ordered=False, addable=True,
         preview='constraint', confidence="主体高，字段中",  # ui-copy: internal
         summary="look-at：让一根骨的轴指向另一根骨"),
    Kind('RotExpression', "RotExpr 旋转表达式", 'DRIVER_ROTATIONAL_DIFFERENCE',
         tab=True, ordered=False, addable=True,
         preview='constraint', confidence="中高（统计推断）",  # ui-copy: internal
         summary="按轴乘系数把源骨骼的旋转拷贝给目标骨骼"),
    Kind('Material', "Material 材质", 'MATERIAL', tab=True, ordered=False, addable=False,
         preview='', confidence="低",  # ui-copy: internal
         summary="骨骼驱动材质属性（如 Water_* 骨驱动 Liquid* 材质）"),
    Kind('JointExportGraph', "JXG 导出图", 'FILE_FOLDER', tab=True, ordered=False,
         addable=False, preview='', confidence="低",  # ui-copy: internal
         summary="一条 JointExportGraph 资源路径"),
    # Anything the importer does not produce.  Exported untouched.
    Kind('Unknown', "未知", 'QUESTION', tab=False, ordered=False, addable=False,
         preview='', confidence="未知", summary="导出时原样保留"),  # ui-copy: internal
)

_BY_ID = {k.id: k for k in KINDS}
TAB_KINDS = tuple(k for k in KINDS if k.tab)


def kind_of(constraint_type):
    """The Kind for a stored constraint_type.  '' is an old spelling of Ranges."""
    if not constraint_type:
        return _BY_ID['Ranges']
    return _BY_ID.get(constraint_type, _BY_ID['Unknown'])


# ── What may be done ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class FileState:
    """The facts about one JCNS file that decide what is editable."""
    version: int = 0
    rebuild: bool = True            # the exporter rebuilds this version (v35, v102)
    sections_cached: bool = True    # the importer stored Skin/Aim/RotExpr data in Blender
    has_armature: bool = False      # a target armature is set
    has_read_table: bool = False    # the file ships a ReadJointTable (needs the skeleton to re-derive)


@dataclass(frozen=True)
class Caps:
    """What the UI may offer for one kind in one file.

    `why` maps an action to the reason it is unavailable; an action that is
    allowed has no entry.  `banner` is the one-line summary shown above the list
    (empty when nothing is restricted).
    """
    can_edit: bool
    can_add: bool
    can_remove: bool
    can_move: bool
    banner: str = ''
    why: tuple = ()

    def reason(self, action):
        return dict(self.why).get(action, '')


def _caps(_edit, _add, _remove, _move, _banner='', **why):
    """Positional flags first; `why` keywords are action names (edit/add/remove/move)."""
    return Caps(_edit, _add, _remove, _move, _banner, tuple(why.items()))


def complex_mapping_editable(st):
    """(editable, reason) for ComplexMapping keyframes: they belong to a Ranges
    source but are rebuilt and cached like the non-Ranges sections."""
    if not st.rebuild:
        return False, f"v{st.version} 只能就地回写，这部分导出时原样保留"
    if not st.sections_cached:
        return False, "这个文件是旧版插件导入的，Blender 里没有这部分数据；重新导入后可编辑"
    return True, ''


def capabilities(kind_id, st):
    """Caps of a kind under the file state `st`."""
    k = kind_of(kind_id)
    v = st.version

    if k.id == 'Unknown':
        msg = "类型未知，导出时原样保留"
        return _caps(False, False, False, False, msg,
                     edit=msg, add=msg, remove=msg, move=msg)

    if k.id == 'Ranges':
        if not st.rebuild:
            msg = f"v{v} 只能就地修改数值：不能增删约束/驱动源、换顺序或改骨骼名"
            return _caps(True, False, False, False, msg,
                         add=msg, remove=msg, move=msg)
        return _caps(True, True, True, True)

    if k.id in ('Skin', 'Aim', 'RotExpression'):
        if not st.rebuild:
            msg = f"v{v} 只能就地回写，这部分导出时原样保留"
            return _caps(False, False, False, False, msg,
                         edit=msg, add=msg, remove=msg, move=msg)
        if not st.sections_cached:
            msg = "这个文件是旧版插件导入的，Blender 里没有这部分数据；重新导入后可编辑"
            return _caps(False, False, False, False, msg,
                         edit=msg, add=msg, remove=msg, move=msg)
        # Count changes need derived data re-computed on export.
        block = ''
        if k.id in ('Skin', 'Aim') and st.has_read_table and not st.has_armature:
            block = ("文件带读取骨表（ReadJointTable），增删条目后要按骨架重算它："
                     "请先设置目标骨架")
        move_why = "顺序在游戏里的含义未证实，不提供换序"
        why = {'move': move_why}
        if block:
            why.update(add=block, remove=block)
        return _caps(True, not block, not block, False, block, **why)

    if k.id == 'Material':
        if not st.rebuild:
            msg = f"v{v} 就地回写：只能改哈希和变换 ID，不能改骨骼或增删"
            return _caps(True, False, False, False, msg,
                         add=msg, remove=msg, move=msg)
        return _caps(True, False, True, False, '',
                     add="暂不支持新建 Material 条目",
                     move="顺序在游戏里的含义未证实，不提供换序")

    if k.id == 'JointExportGraph':
        if not st.rebuild:
            msg = f"v{v} 就地回写不改 JXG 路径，导出时原样保留"
            return _caps(False, False, False, False, msg,
                         edit=msg, add=msg, remove=msg, move=msg)
        return _caps(True, False, True, False, '',
                     add="暂不支持新建 JXG 条目",
                     move="JXG 每个文件只有一条")

    raise AssertionError(k.id)      # KINDS and this function must stay in step
