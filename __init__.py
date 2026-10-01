import bpy
from bpy.props import (
    StringProperty,
    IntProperty,
    FloatProperty,
    BoolProperty,
    EnumProperty,
    PointerProperty,
    CollectionProperty,
    FloatVectorProperty,
    IntVectorProperty,
)
from bpy.types import PropertyGroup

bl_info = {
    "name": "Wilds JCNS Editor",
    "author": "Dimcirui",
    "version": (0, 14, 1),
    "blender": (3, 6, 0),
    "location": "View3D > Sidebar > JCNS Editor | File > Import/Export",
    "description": (
        "Import, edit, and export RE Engine JCNS joint constraint files "
        "(MH Wilds v102 and RE9 v35 rebuilt, every other JCNS version "
        "editable in place). Each imported file creates a green collection "
        "with one Empty per constraint, each carrying its full list of "
        "driving sources."
    ),
    "category": "Animation",
}


# ---------------------------------------------------------------------------
# Constants shared across modules
# ---------------------------------------------------------------------------

AXIS_ITEMS = [
    ('X', "X", "骨骼局部 X 轴（或四元数 X 分量）"),
    ('Y', "Y", "骨骼局部 Y 轴（或四元数 Y 分量）"),
    ('Z', "Z", "骨骼局部 Z 轴（或四元数 Z 分量）"),
    ('W', "W", "四元数 W 分量（暂不支持生成驱动器）"),
]

# ConstraintSource_v2 bytes +24 / +25 (the .bt calls them UpdateTimingID and
# TransformIDSrc).
#   +24 is the curve mode: 0 / 1 are two-point (the kink is ignored; a straight
#       line from start to end), 2 / 3 three-point.  4 / 5 are unmodelled and
#       treated as three-point (modules.jcns_mapping.is_two_point).  In
#       three-point mode a kink strictly outside [start, end] disables the
#       source: the output is 0, not a clamped constant.
#   +25 is the read mode (below); it does not change the curve shape.
# The two bytes vary independently, so both stay raw editable numbers.


def _read_mode_items():
    from .modules_shim import ensure_path
    ensure_path()
    import jcns_source_read
    items = [(ident, "%d %s" % (value, name), desc, value)
             for value, ident, name, _q, desc in jcns_source_read.READ_MODES]
    default = jcns_source_read.read_mode_id(jcns_source_read.DEFAULT_READ_MODE)
    return items, default


# +25 ReadMode; the table lives in modules/jcns_source_read.py.
_READ_MODE_ITEMS, _READ_MODE_DEFAULT = _read_mode_items()


def _euler_order_items():
    from .modules_shim import ensure_path
    ensure_path()
    import jcns_source_read
    return [(name, "%d %s" % (value, name), "Blender 的 %s 顺序（%s 轴最先作用）" % (name, name[0]), value)
            for value, name in sorted(jcns_source_read.EULER_ORDER_NAMES.items())]


# +27 EulerOrder, Blender order names.
_EULER_ORDER_ITEMS = _euler_order_items()

# Source byte +28: how a segment of the mapping runs between its anchors.
INTERPOLATION_ITEMS = [
    ('LINEAR', "0 线性", "每段是直线"),
    ('CUBIC_IN', "1 缓入", "每段先慢后快，t³"),
    ('CUBIC_OUT', "2 缓出", "每段先快后慢，1−(1−t)³"),
    ('SMOOTHSTEP', "3 缓入缓出", "每段按三次平滑阶跃过渡，段首段尾斜率为 0"),
]
INTERPOLATION_TO_INT = {item[0]: i for i, item in enumerate(INTERPOLATION_ITEMS)}
INT_TO_INTERPOLATION = {i: ident for ident, i in INTERPOLATION_TO_INT.items()}

# Aim RotationType: how the roll around the aim axis is fixed.
AIM_TYPE_ITEMS = [
    ('WORLD_UP', "0 世界上方向", "上方向取世界 +Y，上方向向量无效"),
    ('UP_JOINT_POSITION', "1 辅助骨位置", "上方向取自己指向辅助骨的方向"),
    ('UP_JOINT_AXIS', "2 辅助骨轴", "上方向取辅助骨自己的一根局部轴，由「上方向」向量选（(0,1,0) 是 Y 轴，(0,0,1) 是 Z 轴）"),
    ('UP_DIRECTION', "3 指定上方向", "上方向取「上方向」向量给出的世界方向"),
    ('SHORTEST_ARC', "4 最短弧", "从静止姿态朝目标转最短弧，不约束翻滚"),
    ('SHORTEST_ARC_PARENT', "5 父骨最短弧", "从父骨朝向起朝目标转最短弧，丢掉静止姿态"),
]
AIM_TYPE_TO_INT = {item[0]: i for i, item in enumerate(AIM_TYPE_ITEMS)}
INT_TO_AIM_TYPE = {i: ident for ident, i in AIM_TYPE_TO_INT.items()}

# RotExpression byte[1]: whether the result lies on the rest pose.
ROT_REST_ITEMS = [
    ('REPLACE', "替换", "结果不含静止姿态（字节 0）"),
    ('ADD_REST', "叠在静止姿态上", "结果 = 静止姿态 · 值（字节 48）"),
]
ROT_REST_TO_INT = {'REPLACE': 0, 'ADD_REST': 48}
INT_TO_ROT_REST = {0: 'REPLACE', 48: 'ADD_REST'}

TRANSFORM_ITEMS = [
    ('Translation',    "Translation",    "0：驱动骨骼位置"),
    ('Rotation',       "Rotation",       "1：欧拉旋转，静止姿态 · Rz·Ry·Rx"),
    ('Scale',          "Scale",          "2：驱动骨骼缩放"),
    ('BlendShape',     "BlendShape",     "3：驱动形变权重"),
    ('SwingTwist',     "SwingTwist",     "4：摆动·扭转旋转，X 为扭转、Y/Z 为摆动。常用于扭转骨、三角肌"),
    ('TwistSwing',     "TwistSwing",     "5：扭转·摆动旋转，与 4 相同但先摆动后扭转"),
    ('RotationVector', "RotationVector", "6：旋转向量，三个分量组成「转轴 × 角度」。常用于 ThighRX/RZ"),
    ('Material_Color', "Material_Color", "7：可能驱动材质颜色参数"),
    ('Material_4D',    "Material_4D",    "8：可能驱动材质四维参数"),
    ('Material_3D',    "Material_3D",    "9：可能驱动材质三维参数"),
    ('Material_2D',    "Material_2D",    "10：可能驱动材质二维参数"),
    ('Scalar',         "Scalar",         "11：可能驱动标量参数"),
    ('Unknown_12',     "Unknown_12",     "12：具体作用未知"),
    ('AxisRotation',   "AxisRotation",   "13：单轴旋转，绕所写的轴。每根骨只保留一个：骨上最后一条 13/14 条目生效，与它写哪个轴无关。常用于辅助骨、布料偏移骨（约 20% 的条目）"),
    ('AxisRotation_14', "AxisRotation_14", "14：与 13 行为相同，两者的区别未知。常用于围裙、触手"),
    ('UnkRotation_15', "UnkRotation_15", "15：具体作用未知"),
    ('UnkRotation_16', "UnkRotation_16", "16：具体作用未知"),
]

AXIS_TO_INT = {'X': 0, 'Y': 1, 'Z': 2, 'W': 3}
INT_TO_AXIS = {0: 'X', 1: 'Y', 2: 'Z', 3: 'W'}

TRANSFORM_TYPE_MAP = {
    0:  'Translation',
    1:  'Rotation',
    2:  'Scale',
    3:  'BlendShape',
    4:  'SwingTwist',
    5:  'TwistSwing',
    6:  'RotationVector',
    7:  'Material_Color',
    8:  'Material_4D',
    9:  'Material_3D',
    10: 'Material_2D',
    11: 'Scalar',
    12: 'Unknown_12',
    13: 'AxisRotation',
    14: 'AxisRotation_14',
    15: 'UnkRotation_15',
    16: 'UnkRotation_16',
}


# ---------------------------------------------------------------------------
# Update and search callbacks
# ---------------------------------------------------------------------------

def _update_additive(self, context):
    _refresh_flags_preview(self)


def flags_byte(p):
    """The ConstraintInfo Flags byte: bit 0 is the additive switch, the other bits
    are kept as read (bits 4 and 5 are rederived from the transform type on export)."""
    return (int(p.flags_other) & 0xFE) | int(bool(p.additive))


def _refresh_flags_preview(self):
    """bit0 decides whether a value replaces the rest pose, so an applied preview
    has to follow it."""
    try:
        from . import jcns_preview
        jcns_preview.refresh(self.id_data, structural=True)
    except Exception as exc:
        print("[JCNS] preview refresh after a flags edit skipped: %r" % exc)


def _refresh_preview_values(self, context):
    """Cheap path: only numbers changed, so a preview already in place can stay."""
    try:
        from . import jcns_preview
        jcns_preview.refresh(self.id_data, structural=False)
    except Exception as exc:
        print("[JCNS] preview value refresh skipped: %r" % exc)


def _sync_constraint_name(self):
    """Re-derive this Empty's name from its properties, keeping its '[N]' index.

    Renumbering is left to JCNS_OT_DeleteConstraint and JCNS_OT_MirrorConstraints.
    """
    obj = self.id_data
    if obj is None:
        return
    p = getattr(obj, 'jcns_cns_props', None)
    if p is None or not p.is_jcns_constraint:
        return
    # Section Empties keep their '[AimNN] …' prefix (see SECTION_PREFIX).
    # Material / JXG labels never change.
    if p.constraint_type in ('Skin', 'Aim', 'RotExpression'):
        obj.name = section_empty_name(p.constraint_type, section_index(obj), p)
        return
    if p.constraint_type not in ('Ranges', ''):
        return
    idx = 0
    if obj.name.startswith('['):
        try:
            idx = int(obj.name[1:obj.name.index(']')])
        except (ValueError, IndexError):
            pass
    obj.name = constraint_name_from_props(idx, p)


# Non-range section Empties are named "[<Prefix><NN>] <label>".  The exporter
# reads the entry order back out of the prefix, so keep it stable.
SECTION_PREFIX = {'Skin': 'Skin', 'Aim': 'Aim', 'RotExpression': 'RotExpr', 'Material': 'Mat'}


def section_index(obj):
    """NN of an Empty named '[<Prefix>NN] ...', or 9999."""
    name = obj.name
    if name.startswith('[') and ']' in name:
        digits = ''.join(ch for ch in name[1:name.index(']')] if ch.isdigit())
        if digits:
            return int(digits)
    return 9999


def section_empty_name(kind, idx, p):
    pre = SECTION_PREFIX.get(kind, kind)
    if kind == 'Skin':
        label = p.target_bone or '?'
    elif kind == 'Aim':
        label = f"{p.target_bone or '?'} → {p.aim_target_bone or '?'}"
    elif kind == 'RotExpression':
        label = f"{p.rot_source_bone or '?'} → {p.target_bone or '?'}"
    else:
        label = p.target_bone or '?'
    return f"[{pre}{idx:02d}] {label}"


def section_empties(root_empty, kind):
    """Section Empties of one kind under a root, in file order."""
    objs = [o for o in root_empty.children
            if getattr(o, 'jcns_cns_props', None) and o.jcns_cns_props.constraint_type == kind]
    return sorted(objs, key=section_index)


def _refresh_preview(self, context):
    """Update for the fields the display name and the preview are built from:
    re-sync the Empty's name and rebuild an applied preview (no-op without one).
    """
    try:
        from . import jcns_preview
        jcns_preview.refresh(self.id_data, structural=True)
    except Exception as exc:                     # an edit must never hard-fail
        print("[JCNS] preview refresh skipped: %r" % exc)
    try:
        _sync_constraint_name(self)
    except Exception as exc:
        print("[JCNS] name refresh skipped: %r" % exc)


def _search_bone_names(context, edit_text):
    """Return bone names from available_bones_json that match edit_text (case-insensitive).

    Text not in the list is prepended, so a new bone name can be confirmed
    instead of being forced onto a partial match.
    """
    import json
    obj = context.active_object
    if obj is None:
        return []
    root_obj, root_props = get_jcns_root_from_constraint(obj)
    if root_props is None:
        return []
    try:
        names = json.loads(root_props.available_bones_json or '[]')
    except Exception:
        return []
    needle = edit_text.lower()
    matches = sorted(n for n in names if needle in n.lower())
    if edit_text and edit_text not in names:
        return [edit_text] + matches
    return matches


def _search_source_bone(self, context, edit_text):
    return _search_bone_names(context, edit_text)


def _search_target_bone(self, context, edit_text):
    return _search_bone_names(context, edit_text)


# ---------------------------------------------------------------------------
# Property Group: one ConstraintSource_v2 block
# ---------------------------------------------------------------------------

class JCNSCMKey(PropertyGroup):
    """One ComplexMappingInfo record (28 bytes), as read from the file.

    The source's F-Curve is the data (jcns_cm.py); these let an untouched curve
    export its original bytes (jcns_cm.records()).  FromX/ToX are a key,
    (FromY, ToY) / (FromZ, ToZ) its incoming / outgoing tangent as (dx, dy); the
    flag does not affect the curve.
    """
    from_x: FloatProperty(name="From X", default=0.0)
    to_x:   FloatProperty(name="To X",   default=0.0)
    from_y: FloatProperty(name="From Y", default=0.0)
    to_y:   FloatProperty(name="To Y",   default=0.0)
    from_z: FloatProperty(name="From Z", default=0.0)
    to_z:   FloatProperty(name="To Z",   default=0.0)
    flag:   IntProperty(name="Flag", description="具体作用未知，改动不影响曲线。常见值为 0、2、5、8",
                        default=0, min=0)


class JCNSConeInfo(PropertyGroup):
    """One ConeDriverInfo record (24 bytes, v24+): a cone this constraint reads.

    RE9 v35: Rest is (0,0,0,0), or (0,0,0,1) on scale targets; Value is what the
    target takes for that cone (bt: AngleDeg, but scale targets hold factors).
    """
    cone_index: IntProperty(name="ConeDriver", description="ConeDriver 表里的序号", default=0, min=0)
    value: FloatProperty(name="输出值", description="这个锥形对应的目标值：角度，缩放目标时为倍数", default=0.0)
    rest: FloatVectorProperty(name="Rest", size=4, default=(0.0, 0.0, 0.0, 0.0))
    unk_byte0: IntProperty(name="+20", default=0, min=0, max=255)
    unk_byte3: IntProperty(name="+23", default=0, min=0, max=255)


class JCNSIntItem(PropertyGroup):
    """One integer of a stored list."""
    value: IntProperty(name="值", default=0)


class JCNSHashItem(PropertyGroup):
    """A uint32 hash, held as a signed int, with the name it resolved to."""
    hash: IntProperty(name="哈希", description="按有符号整数显示", default=0)
    name: StringProperty(name="名称", default="")


class JCNSWeightedSource(PropertyGroup):
    """One source bone of a SkinConstraint record."""
    bone: StringProperty(name="骨骼", default="", update=_refresh_preview,
                         search=lambda self, context, text: _search_bone_names(context, text))
    weight: FloatProperty(name="权重", default=1.0, precision=4, update=_refresh_preview_values)


class JCNSSourceProperties(PropertyGroup):
    """One driving source: one 72-byte ConstraintSource_v2 block."""

    source_bone: StringProperty(
        update=_refresh_preview,
        name="驱动骨骼",
        description="读取旋转的骨骼。可输入以搜索本文件哈希表中的骨骼名",
        default="",
        search=_search_source_bone,
        search_options={'SUGGESTION'},
    )
    source_axis: EnumProperty(
        update=_refresh_preview,
        name="源局部轴向",
        description="读取驱动骨骼的哪个局部轴。JCNS 的映射定义在骨骼自身的局部坐标系上，不是全局坐标系",
        items=AXIS_ITEMS,
        default='X',
    )

    # --- Three-point piecewise mapping ---
    from_start: FloatProperty(
        update=_refresh_preview_values,
        name="From 起点", description="起点 A 的输入，即源骨读数。单位随读取方式：度、厘米或倍数",
        default=0.0, precision=2, step=10,
    )
    from_kink: FloatProperty(
        update=_refresh_preview_values,
        name="From 折点", description="折点 B 的输入，两段斜率在这里分界。两点模式下忽略；落在起点与终点之外时整条源失效",
        default=0.0, precision=2, step=10,
    )
    from_end: FloatProperty(
        update=_refresh_preview_values,
        name="From 终点", description="终点 C 的输入",
        default=0.0, precision=2, step=10,
    )
    to_start: FloatProperty(
        update=_refresh_preview_values,
        name="To 起点", description="起点 A 的输出。单位随变换类型：度、厘米或倍数",
        default=0.0, precision=2, step=10,
    )
    to_kink: FloatProperty(
        update=_refresh_preview_values,
        name="To 折点", description="折点 B 的输出。两点模式下忽略",
        default=0.0, precision=2, step=10,
    )
    to_end: FloatProperty(
        update=_refresh_preview_values,
        name="To 终点", description="终点 C 的输出",
        default=0.0, precision=2, step=10,
    )

    # --- Reference frame (+56, stored as "ref_frame") ---
    # Not the bone's rest pose (the engine takes that from the skeleton): the frame
    # the swing-twist and rotation-vector reads decompose in, f^-1 * q * f.
    ref_frame_x: FloatProperty(name="参考系 X", default=0.0, precision=5,
                               update=_refresh_preview)
    ref_frame_y: FloatProperty(name="参考系 Y", default=0.0, precision=5,
                               update=_refresh_preview)
    ref_frame_z: FloatProperty(name="参考系 Z", default=0.0, precision=5,
                               update=_refresh_preview)
    ref_frame_w: FloatProperty(name="参考系 W", default=1.0, precision=5,
                               update=_refresh_preview)

    # --- Raw bytes ---
    # +24 and +25 default to 3, the most common value.
    three_point: BoolProperty(
        update=_refresh_preview_values,
        name="三点映射",
        description=(
            "映射曲线的形状（曲线模式的位1）。关：两点直线，忽略折点；开：三点折线，折点生效。"
            "三点模式下折点落在起点与终点之外时，整条源失效，输出恒为 0"
        ),
        default=True,
    )
    curve_mode_extra: IntProperty(
        name="曲线模式其余位",
        description="曲线模式去掉位1 的其余位：位0 不起作用（多与 Flags 位0 一致），位2 及以上只出现在材质目标上，含义未知",
        default=1, min=0, max=253,
    )
    read_mode: EnumProperty(
        update=_refresh_preview,
        name="读取方式 (+25)",
        description=(
            "从源骨读什么。读的是相对父骨的完整变换，静止姿态和静止偏移都算在内；"
            "这里决定取位置、缩放，还是旋转的哪一种分解"
        ),
        items=_READ_MODE_ITEMS,
        default=_READ_MODE_DEFAULT,
    )
    euler_order: EnumProperty(
        update=_refresh_preview,
        name="欧拉顺序 (+27)",
        description=(
            "读取方式为「欧拉角」时的分解顺序，其他读取方式忽略它。"
            "通常跟着源骨走：大腿、手多为 YZX，手指为 ZXY，翅膀为 ZYX，其余为 XYZ"
        ),
        items=_EULER_ORDER_ITEMS,
        default='XYZ',
    )
    complex_mapping_info_count: IntProperty(
        name="复杂映射数", description="复杂映射曲线的关键帧数，导出时按曲线重算",
        default=0, min=0, max=65535,
    )
    unknown_uint16_22: IntProperty(
        name="未知 UInt16 (+22)", description="具体作用未知。通常为 0",
        default=0, min=0, max=65535,
    )
    interpolation: EnumProperty(
        update=_refresh_preview_values,
        name="插值 (+28)",
        description="每段映射怎么过渡。线性：直线；缓入缓出：每段按三次平滑阶跃。"
                    "1 和 2 极少见，含义未知",
        items=INTERPOLATION_ITEMS, default='LINEAR',
    )
    complex_mapping_flag: IntProperty(
        name="复杂映射标记 (+29)", description="有复杂映射时为 1，导出时自动设置；没有复杂映射时也可能是 2（只见于材质目标）",
        default=0, min=0, max=255,
    )
    # ComplexMapping: the curve is an F-Curve on the constraint Empty, on the custom
    # property named here (jcns_cm.py); cm_cache holds the file's own records.
    cm_channel: StringProperty(default="")
    cm_cache: CollectionProperty(type=JCNSCMKey)


# ---------------------------------------------------------------------------
# Property Group: attached to each constraint Empty child object
# ---------------------------------------------------------------------------

class JCNSConstraintProperties(PropertyGroup):
    """On every entry Empty: one 80-byte ConstraintInfo block plus its sources."""

    # Marks an entry Empty; set at import and by Add Constraint.
    is_jcns_constraint: BoolProperty(default=False)

    sources: CollectionProperty(type=JCNSSourceProperties)
    active_source_index: IntProperty(default=0)
    # Next ComplexMapping channel number (jcns_cm.fcurve); never reused.
    cm_next_id: IntProperty(default=0)

    # --- Identity ---
    target_bone: StringProperty(
        update=_refresh_preview,
        name="目标骨骼",
        description="被驱动的骨骼。可输入以搜索本文件哈希表中的骨骼名",
        default="",
        search=_search_target_bone,
        search_options={'SUGGESTION'},
    )
    transform_type: EnumProperty(
        update=_refresh_preview,
        name="变换类型",
        description="约束驱动的是旋转、平移还是缩放等",
        items=TRANSFORM_ITEMS,
        default='Rotation',
    )

    # --- Axis (editable — exported back to file) ---
    target_axis: EnumProperty(
        update=_refresh_preview,
        name="目标局部轴向",
        description="驱动目标骨骼的哪个局部轴。JCNS 的映射定义在骨骼自身的局部坐标系上，不是全局坐标系",
        items=AXIS_ITEMS,
        default='X',
    )

    # --- ConstraintInfo fields (editable, exported) ---
    additive: BoolProperty(
        name="叠加",
        description="Flags 位0。开：值叠加在静止姿态上；关：替换所写的轴（旋转、平移），对缩放不起作用",
        default=True, update=_update_additive,
    )
    flags_other: IntProperty(
        name="其余标志位",
        description="Flags 去掉位0 的其余位：位4 驱动骨骼、位5 驱动量为旋转（v36/v102 导出时按变换类型重算），"
                    "位2、位3 只出现在形变和材质目标上，含义未知",
        default=0x30, min=0, max=254,
    )
    reserved_vec4_x: FloatProperty(name="Vec4 X", default=0.0, precision=5, description="固定为 0，请勿修改")
    reserved_vec4_y: FloatProperty(name="Vec4 Y", default=0.0, precision=5, description="固定为 0，请勿修改")
    reserved_vec4_z: FloatProperty(name="Vec4 Z", default=0.0, precision=5, description="固定为 0，请勿修改")
    reserved_vec4_w: FloatProperty(name="Vec4 W", default=1.0, precision=5, description="固定为 1，请勿修改")
    unknown_float2_x: FloatProperty(name="Float2 X", default=0.0, precision=5,
                                   description="具体作用未知。通常为 0")
    unknown_float2_y: FloatProperty(name="Float2 Y", default=0.0, precision=5,
                                   description="具体作用未知。通常为 0")
    unknown_byte_72: IntProperty(
        name="未知字节 (+72)", description="具体作用未知。通常为 0（约 99%）",
        default=0, min=0, max=255,
    )
    # Material / RSZ property targets (TransformType 7-11) name a property on the target.
    target_property: StringProperty(
        name="目标属性",
        description="被驱动的属性名，如材质参数名。只有材质、标量类变换用到，骨骼目标留空",
        default="",
    )
    # The two hashes below are overrides in a signed IntProperty (a uint32 above 2**31
    # is stored as its two's-complement negative); 0 derives the hash from the name.
    property_hash: IntProperty(
        name="属性哈希覆盖",
        description="按有符号整数显示。0 表示用目标属性名的哈希；只有属性名对不上哈希时才需要填",
        default=0,
    )
    object_hash: IntProperty(
        name="目标哈希覆盖",
        description="只用于形变、材质、标量和命名输出这类按哈希指定的目标。按有符号整数显示。"
                    "0 表示用目标名的哈希；只有目标名对不上哈希时才需要填",
        default=0,
    )
    # ConeDriverInfo[]: the cones this constraint reads (RE9 uses them heavily)
    cone_infos: CollectionProperty(type=JCNSConeInfo)
    active_cone_info_index: IntProperty(default=0)
    # +77 is the joint-group count (jcns_writer.tail_group_counts derives it); +74 and +75
    # are unknown, and +75 defaults to its most common value.
    unknown_byte_74: IntProperty(name="+74", default=0, min=0, max=255,
                                 description="具体作用未知。通常为 0（约 99%），跟着目标骨走")
    unknown_byte_75: IntProperty(name="+75", default=2, min=0, max=255,
                                 description="具体作用未知。通常为 2（约 69%），同一文件里同一变换类型一般只用一个值")
    group_count: IntProperty(
        name="关节组计数",
        description=(
            "紧跟在这条后面、与它同目标同变换同 Flags 的连续条目数（组首填 N，组员填 0）。"
            "引擎把整组输出都写到组首条目的目标骨上。导出时自动校验：整份文件分组合法就照写，否则全部重算"
        ),
        default=0, min=0, max=255)
    reserved_tail: IntVectorProperty(name="保留字节 +76 / +78 / +79", size=3, default=(0, 0, 0), min=0, max=255,
                                     description="固定为 0")

    # --- Material constraint-specific fields (populated at import, editable) ---
    mat_name_hash: StringProperty(
        name="MaterialNameHash",
        description="材质名的哈希，十六进制，例如 0x1A2B3C4D",
        default="0x00000000",
    )
    mat_property_hash: StringProperty(
        name="MaterialPropertyHash",
        description="材质属性名的哈希，十六进制",
        default="0x00000000",
    )
    mat_transform_type_raw: IntProperty(
        name="TransformationID",
        description="材质约束驱动的参数类型",
        default=0, min=0, max=255,
    )
    mat_tail_0: IntProperty(name="MatTail[0]", default=0, min=0, max=255)
    mat_tail_1: IntProperty(name="MatTail[1]", default=0, min=0, max=255)
    mat_tail_2: IntProperty(name="MatTail[2]", default=0, min=0, max=255)

    # --- JointExportGraph path (Type 5 empties only) ---
    jxg_path: StringProperty(
        name="路径",
        description="导出图（JointExportGraph）的路径",
        default="",
    )

    # --- SkinConstraint (target_bone is the skinned object) ---
    skin_sources: CollectionProperty(type=JCNSWeightedSource)
    active_skin_source_index: IntProperty(default=0)
    skin_tail: IntVectorProperty(
        name="尾部 2 字节", size=2, default=(0, 0), min=0, max=255,
        description="记录尾部第 2、3 字节（第 1 字节是每文件常量）。v102 固定为 0，RE9（v35）逐条不同；"
                    "新建条目取本文件最常见的值")

    # --- Aim (target_bone is the aimed joint) ---
    aim_target_bone: StringProperty(name="瞄准目标", default="", update=_refresh_preview,
                                    search=_search_target_bone)
    aim_up_bone: StringProperty(name="辅助骨骼", description="AimVectorPointJoint；留空表示不使用",
                                default="", update=_refresh_preview, search=_search_target_bone)
    aim_influence: FloatProperty(name="影响", default=1.0, update=_refresh_preview_values)
    aim_offset: FloatVectorProperty(name="旋转偏移", size=3, default=(0.0, 0.0, 0.0), subtype='EULER',
                                    description="XYZ 欧拉角（弧度，Rz·Ry·Rx）。瞄准结果再右乘这个旋转，"
                                                "等于让本地瞄准轴偏离目标；只有类型 2 用到",
                                    update=_refresh_preview)
    aim_axis: FloatVectorProperty(name="瞄准轴", size=3, default=(1.0, 0.0, 0.0),
                                  description="目标骨自己的局部轴，指向瞄准目标",
                                  update=_refresh_preview_values)
    aim_up_axis: FloatVectorProperty(name="上方向轴", size=3, default=(0.0, 1.0, 0.0),
                                     description="目标骨自己的局部轴，与「上」对齐")
    aim_up_dir: FloatVectorProperty(name="上方向", size=3, default=(0.0, 1.0, 0.0),
                                    description="类型 3 下是世界里的上方向；类型 2 下选辅助骨的哪根局部轴；类型 0 无效")
    aim_type: EnumProperty(name="类型", items=AIM_TYPE_ITEMS, default='WORLD_UP',
                           update=_refresh_preview)
    aim_bytes: IntVectorProperty(name="字节 +57..59", size=3, default=(1, 0, 5), min=0, max=255)

    # --- RotExpression (target_bone is the driven joint) ---
    rot_source_bone: StringProperty(name="源骨骼", default="", update=_refresh_preview,
                                    search=_search_target_bone)
    rot_rotation: FloatVectorProperty(name="Rotation", size=4, default=(0.0, 0.0, 0.0, 1.0))
    rot_scale: FloatVectorProperty(name="Scale", size=4, default=(0.0, 0.0, 0.0, 1.0))
    rot_rest_mode: EnumProperty(name="静止姿态", items=ROT_REST_ITEMS, default='REPLACE')
    rot_unknown_bytes: IntVectorProperty(name="未知字节 0 / 2 / 3", size=3, default=(0, 0, 0), min=0, max=255)
    rot_gains: FloatVectorProperty(name="系数", size=3, default=(1.0, 1.0, 1.0),
                                   description="每轴的系数。(1,1,1) 是精确拷贝；其他值小角度时每轴相乘，大角度偏离线性",
                                   update=_refresh_preview_values)

    # --- Section type (set at import, read-only in UI) ---
    constraint_type: StringProperty(
        name="Constraint Type",
        description="Section type from the JCNS file (e.g. 'Ranges', 'Aim', 'Skin'…)",
        default='Ranges',
    )

    # --- Driver state (runtime, not exported) ---
    preview_on: BoolProperty(
        name="已应用预览",
        description="此条目当前是否在骨架上生成了预览（Ranges 是驱动器，其余是原生骨骼约束）",
        default=False,
    )
    # The pose bone currently carrying this entry's preview constraint, so a
    # changed target bone can clean up after itself (constraint previews only).
    preview_bone: StringProperty(default="")


# ---------------------------------------------------------------------------
# Property Group: attached to the root Empty of each JCNS collection
# ---------------------------------------------------------------------------

from .jcns_sdk_ops import JCNSSDKBone, JCNSSDKKey, JCNSSDKSnapshot, search_bones


def _armature_poll(self, obj):
    return obj.type == 'ARMATURE'


# ---------------------------------------------------------------------------
# Browser state: which section tab is showing, and which entry is active
# ---------------------------------------------------------------------------
#
# Entries are Empties, so "the active entry" is just the active object.  The
# browser's list is a UI list over the root's Collection.objects (template_list
# needs a real RNA collection; Object.children is a Python tuple), and its active
# index reads and writes the active object, which keeps the list, the viewport
# and the Outliner in step without any handler.

def entry_collection(root_empty):
    """The Collection whose .objects holds a root's entries."""
    return next(iter(root_empty.users_collection), None)


def is_entry_of(obj, root_empty):
    p = getattr(obj, 'jcns_cns_props', None)
    return bool(p and p.is_jcns_constraint and obj.parent == root_empty)


def entry_sort_key(obj):
    """File order: the number in the '[N]' / '[AimNN]' name prefix."""
    return section_index(obj)


def entries_of(root_empty, kind_id=None):
    """A root's entries in file order, optionally only one kind's."""
    from .modules_shim import get_kinds
    coll = entry_collection(root_empty)
    if coll is None:
        return []
    kinds = get_kinds()
    out = [o for o in coll.objects
           if is_entry_of(o, root_empty)
           and (kind_id is None
                or kinds.kind_of(o.jcns_cns_props.constraint_type).id == kind_id)]
    return sorted(out, key=entry_sort_key)


def entry_counts(root_empty):
    """{kind id: number of entries} for a root."""
    from .modules_shim import get_kinds
    kinds = get_kinds()
    counts = {}
    for o in entries_of(root_empty):
        k = kinds.kind_of(o.jcns_cns_props.constraint_type).id
        counts[k] = counts.get(k, 0) + 1
    return counts


def file_state(rp):
    """The kinds module's FileState for a root's properties."""
    from .modules_shim import get_kinds, ensure_path
    ensure_path()
    from jcns_parser import write_mode
    from .jcns_exporter import _root_version
    v = _root_version(rp)
    return get_kinds().FileState(
        version=v,
        rebuild=write_mode(v) == 'rebuild',
        sections_cached=bool(rp.sections_cached),
        has_armature=rp.target_armature is not None,
        has_read_table=bool(rp.read_joint_signature_json),
    )


def _entry_index_get(self):
    coll = entry_collection(self.id_data)
    act = bpy.context.view_layer.objects.active
    if coll is None or act is None:
        return -1
    for i, o in enumerate(coll.objects):
        if o == act:
            return i
    return -1


def _entry_index_set(self, value):
    coll = entry_collection(self.id_data)
    if coll is None or not 0 <= value < len(coll.objects):
        return
    obj = coll.objects[value]
    ctx = bpy.context
    try:
        for o in list(ctx.selected_objects):
            o.select_set(False)
        obj.select_set(True)
        ctx.view_layer.objects.active = obj
    except RuntimeError:                     # hidden or excluded from the view layer
        pass


def _browser_kind_items():
    from .modules_shim import get_kinds
    return [(k.id, k.label, k.summary, k.icon, i)
            for i, k in enumerate(get_kinds().TAB_KINDS)]


class JCNSRootProperties(PropertyGroup):
    """On the root Empty of a JCNS collection (one root plus N entry Empties)."""
    # Pose-driven constraint creation (jcns_sdk_ops.py)
    sdk_driver_bone: StringProperty(
        name="驱动骨", description="摆姿势建约束里被读取的骨骼",
        default="", search=search_bones, search_options={'SUGGESTION'},
    )
    sdk_driven_bones: CollectionProperty(type=JCNSSDKBone)
    sdk_driven_index: IntProperty(default=0)
    sdk_keys: CollectionProperty(type=JCNSSDKKey)
    sdk_key_index: IntProperty(default=0)
    source_filepath: StringProperty(
        name="源文件",
        description="原始 .jcns 文件的绝对路径",
        subtype='FILE_PATH',
        default="",
    )
    target_armature: PointerProperty(
        name="目标骨架",
        description="约束要作用到的骨架",
        type=bpy.types.Object,
        poll=_armature_poll,
    )
    available_bones_json: StringProperty(
        name="Available Bones (JSON)",
        description="JSON list of bone names present in this file's hash_list (set at import, used for source_bone autocomplete)",
        default="[]",
    )
    # Kept so a file can be exported without its source: the section ids in file order
    # (the order the engine runs them in) and the hash list with its redundant entries.
    section_order: CollectionProperty(type=JCNSIntItem)
    header_unknown_bytes: IntVectorProperty(
        name="文件头未知字节", size=2, default=(0, 0), min=0, max=255,
        description="文件头里 SectionCount 之后的两个标志字节，取值 0 或 1，具体作用未知")
    hash_list: CollectionProperty(type=JCNSHashItem)
    # Combining is fixed engine behaviour, so there is no setting for it: sources
    # in one constraint are summed; of several constraints on one channel the
    # last in file order wins.
    source_version: IntProperty(
        name="JCNS 版本",
        description="Version number of the imported file (the .jcns.<N> suffix); 0 = imported by an older add-on",
        default=0,
    )
    # Set by importers that store Skin / Aim / RotExpression / ComplexMapping in
    # Blender.  When False, the exporter takes those sections from the re-parsed
    # source file, since the Empties hold no data.
    sections_cached: BoolProperty(default=False)
    # Browser state (UI only)
    browser_kind: EnumProperty(
        name="分区", description="在列表里显示哪一类条目",
        items=_browser_kind_items(), default='Ranges',
    )
    entry_index: IntProperty(
        name="条目", description="列表里当前条目的序号；读写的是当前活动物体",
        get=_entry_index_get, set=_entry_index_set,
    )
    file_constant: IntProperty(default=5)
    # ReadJointTable: the joints Skin and Aim read, in file order (see jcns_sections).
    read_joint_table: CollectionProperty(type=JCNSHashItem)
    read_joint_index: IntProperty(default=0)
    read_joint_signature_json: StringProperty(default="")
    # The RotExpressionMap value shared by every RotExpression entry.
    rot_map_value: IntProperty(
        name="RotExpr 映射值", default=0, min=0, max=255,
        description="每条 RotExpr 条目共用的映射常量；新增条目沿用它。具体作用未知")
    object_settings_json: StringProperty(default="")
    # ConeDriver table (v35+), cached so a rebuild can re-emit it
    cone_drivers_json: StringProperty(default="")
    # Read only when source_version is 0 (see jcns_exporter._root_version).
    detected_game: EnumProperty(
        name="游戏",
        description="Game this JCNS file belongs to (detected at import)",
        items=[
            ('MHW_WILDS', "怪物猎人荒野 (v102)", "Monster Hunter Wilds TU4 之后"),
            ('RE9',       "生化危机9 / PRAGMATA (v35)", "Resident Evil 9 / PRAGMATA"),
        ],
        default='MHW_WILDS',
    )


# ---------------------------------------------------------------------------
# Helpers: classify active object
# ---------------------------------------------------------------------------

def get_jcns_root(context):
    """Return (obj, jcns_root_props) if active object is a JCNS root Empty, else (None, None)."""
    obj = context.active_object
    if obj is None:
        return None, None
    props = getattr(obj, 'jcns_root_props', None)
    if props and props.source_filepath:
        return obj, props
    return None, None


def get_jcns_constraint(context):
    """Return (obj, jcns_cns_props) if active object is a JCNS constraint Empty, else (None, None)."""
    obj = context.active_object
    if obj is None:
        return None, None
    props = getattr(obj, 'jcns_cns_props', None)
    if props and props.is_jcns_constraint:
        return obj, props
    return None, None


def get_jcns_root_from_constraint(constraint_empty):
    """Walk up to the parent Empty to find the root, with collection fallback for legacy files."""
    parent = constraint_empty.parent
    if parent is not None:
        root_props = getattr(parent, 'jcns_root_props', None)
        if root_props and root_props.source_filepath:
            return parent, root_props

    # Fallback: flat collection search (legacy imports without parent-child hierarchy)
    for coll in constraint_empty.users_collection:
        for obj in coll.objects:
            if obj == constraint_empty:
                continue
            root_props = getattr(obj, 'jcns_root_props', None)
            if root_props and root_props.source_filepath:
                return obj, root_props
    return None, None


def get_jcns_root_from_collection(collection):
    """The JCNS root Empty inside a Collection (one per import), or (None, None)."""
    if collection is None:
        return None, None
    for obj in collection.objects:
        root_props = getattr(obj, 'jcns_root_props', None)
        if root_props and root_props.source_filepath:
            return obj, root_props
    return None, None


def get_export_root(context):
    """(root, root_props) that operators like export should act on.

    The scene's jcns_active_collection wins when set; otherwise the selected
    JCNS object decides.
    """
    coll = getattr(context.scene, 'jcns_active_collection', None)
    if coll is not None:
        root, root_props = get_jcns_root_from_collection(coll)
        if root is not None:
            return root, root_props

    root, root_props = get_jcns_root(context)
    if root is not None:
        return root, root_props
    cns_obj, _ = get_jcns_constraint(context)
    if cns_obj is not None:
        return get_jcns_root_from_constraint(cns_obj)
    return None, None


def get_constraint_empties(root_empty):
    """Range Empties under the root, sorted by their '[N]' prefix.

    Falls back to a flat collection search for imports without parenting.
    """
    def _is_range(obj):
        p = getattr(obj, 'jcns_cns_props', None)
        return p and (p.constraint_type == 'Ranges' or p.constraint_type == '')

    empties = []
    for obj in root_empty.children:
        if _is_range(obj):
            empties.append(obj)

    # Fallback: flat collection search (legacy imports without parent-child hierarchy)
    if not empties:
        for coll in root_empty.users_collection:
            for obj in coll.objects:
                if obj == root_empty:
                    continue
                if _is_range(obj):
                    empties.append(obj)

    def _sort_key(obj):
        name = obj.name
        if name.startswith('['):
            try:
                return int(name[1:name.index(']')])
            except (ValueError, IndexError):
                pass
        return 9999

    return sorted(empties, key=_sort_key)


def channel_key(cns_props):
    """The Blender F-Curve channel a constraint drives: (bone, transform, axis).

    Several ConstraintInfo blocks can drive the same channel, and Blender allows
    one driver per F-Curve channel, so constraints sharing a key are built as a
    single driver.
    """
    return (cns_props.target_bone, cns_props.transform_type, cns_props.target_axis)


def group_constraints_by_channel(root_empty):
    """Return {channel_key: [constraint Empty, …]} preserving constraint order."""
    groups = {}
    for empty in get_constraint_empties(root_empty):
        groups.setdefault(channel_key(empty.jcns_cns_props), []).append(empty)
    return groups


def sibling_constraints(constraint_empty):
    """Other constraint Empties fighting for the same channel as this one."""
    root_obj, _ = get_jcns_root_from_constraint(constraint_empty)
    if root_obj is None:
        return []
    key = channel_key(constraint_empty.jcns_cns_props)
    return [e for e in group_constraints_by_channel(root_obj).get(key, [])
            if e is not constraint_empty]


def make_constraint_empty_name(idx, source_bone, target_bone, target_axis,
                               source_axis='X', extra_sources=0, cones=0):
    """Canonical display name for a constraint Empty.

    extra_sources > 0 appends '(+N)'; a constraint driven only by ConeDrivers
    shows 'Cone×N' in place of the source.
    """
    src_ax = source_axis if isinstance(source_axis, str) else INT_TO_AXIS.get(source_axis, 'X')
    tgt_ax = target_axis if isinstance(target_axis, str) else INT_TO_AXIS.get(target_axis, 'X')
    tgt = f"{target_bone or '???'} {tgt_ax}"
    if not source_bone and cones:
        return f"[{idx:02d}] Cone×{cones} → {tgt}"
    suffix = f" (+{extra_sources})" if extra_sources > 0 else ""
    return f"[{idx:02d}] {source_bone or '???'} {src_ax}{suffix} → {tgt}"


def constraint_name_from_props(idx, props):
    """Build the Empty name straight from a JCNSConstraintProperties instance."""
    srcs = props.sources
    first = srcs[0] if len(srcs) else None
    return make_constraint_empty_name(
        idx,
        first.source_bone if first else '',
        props.target_bone,
        props.target_axis,
        first.source_axis if first else 'X',
        max(0, len(srcs) - 1),
        len(props.cone_infos),
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

from . import jcns_operators
from . import jcns_importer
from . import jcns_exporter
from . import jcns_ui
from . import jcns_editors
from . import jcns_drivers
from . import jcns_preview
from . import jcns_capture
from . import jcns_cm
from . import jcns_merge_ops
from . import jcns_sdk_ops

def _poll_jcns_collection(self, collection):
    """Restrict the active-collection picker to collections that hold a JCNS root."""
    root, _ = get_jcns_root_from_collection(collection)
    return root is not None


_classes = [
    JCNSCMKey,                  # groups must register before the groups that reference them
    JCNSIntItem,
    JCNSHashItem,
    JCNSConeInfo,
    JCNSWeightedSource,
    JCNSSourceProperties,
    JCNSConstraintProperties,
    JCNSSDKSnapshot,
    JCNSSDKKey,
    JCNSSDKBone,
    JCNSRootProperties,
]


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)

    bpy.types.Object.jcns_root_props = PointerProperty(type=JCNSRootProperties)
    bpy.types.Object.jcns_cns_props  = PointerProperty(type=JCNSConstraintProperties)
    bpy.types.Scene.jcns_active_collection = PointerProperty(
        type=bpy.types.Collection,
        name="工作集合",
        description="导出等操作默认作用的 JCNS 集合。留空则改用当前选中的物体",
        poll=_poll_jcns_collection,
    )

    jcns_operators.register()
    jcns_preview.register()
    jcns_capture.register()
    jcns_importer.register()
    jcns_exporter.register()
    jcns_ui.register()
    jcns_editors.register()
    jcns_drivers.register()
    jcns_cm.register()
    jcns_merge_ops.register()
    jcns_sdk_ops.register()


def unregister():
    jcns_sdk_ops.unregister()
    jcns_merge_ops.unregister()
    jcns_cm.unregister()
    jcns_drivers.unregister()
    jcns_editors.unregister()
    jcns_ui.unregister()
    jcns_exporter.unregister()
    jcns_importer.unregister()
    jcns_capture.unregister()
    jcns_preview.unregister()
    jcns_operators.unregister()

    del bpy.types.Scene.jcns_active_collection
    del bpy.types.Object.jcns_cns_props
    del bpy.types.Object.jcns_root_props

    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
