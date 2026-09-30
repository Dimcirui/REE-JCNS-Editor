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

# ConstraintSource_v2 bytes +24 / +25.
#
# bt v0.65.13 exposed +25 as InterpolationID (Linear / FastInAndOut / …); v0.65.14
# renamed +24 to UpdateTimingID and +25 to TransformIDSrc, marking BOTH "Not sure".
#
# MEASURED IN-GAME 2026-08-21 (MHWilds, live capture against a purpose-built rig):
#
#   +24 is the CURVE MODE, not an update timing.
#       0, 1 -> two-point: the kink is ignored outright; the output is the
#              straight line (from_start,to_start) -> (from_end,to_end).
#       2, 3 -> three-point: the classic piecewise curve; the kink is honoured.
#       Within each pair the members were bit-identical across every geometry
#       tested, so the split is exactly bit 1 (0x02).  Evidence: sources with
#       identical geometry and identical +25, differing only in +24, produced an
#       exact straight line vs an exact piecewise curve, and changing to_kink
#       moved the output by 30 deg in three-point mode and by 0.00000 deg in
#       two-point mode.  See modules.jcns_mapping.is_two_point.
#
#   In three-point mode, a kink lying strictly outside the [start, end] span
#       kills the source outright — the output is a flat 0, not a clamped
#       constant.  Measured over three such geometries.  (3.1% of shipped sources
#       have an out-of-range kink, but 96% of those are two-point, where the kink
#       is ignored anyway; only 26 sources are actually affected.)
#
#   +25 shifts the sampled input quantity slightly but does NOT change the curve
#       shape (isolating it moved the output by ~15 deg while the shape held).
#
#   The constraint-level Flags bit 0 has NO effect on the curve (bit-identical).
#
# UNTESTED, and part of why both bytes stay raw editable numbers:
#   +24 == 4 / 5 (9 sources in the whole corpus).  is_two_point() sticks to the
#   values actually measured rather than extrapolating the bit-1 reading.
#
# Survey of 23031 constraint sources across 884 v102 files:
#     +24 ∈ {0: 1700, 1: 3137, 2: 1879, 3: 16306, 4: 2, 5: 7}
#     +25 ∈ {0: 1285, 1: 1455, 2: 373, 3: 19053, 4: 273, 5: 592}
# 21 distinct (+24, +25) combinations occur; the two bytes are NOT locked together.
UPDATE_TIMING_HINT = "bt 0.65.14 猜测为 0=MotionBegin 1=MotionEnd 2=ConstraintBegin 3=ConstraintEnd"


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

TRANSFORM_ITEMS = [
    ('Translation',    "Translation",    "ID=0: Translational constraint"),
    ('Rotation',       "Rotation",       "ID=1: Rotational constraint (most common)"),
    ('Scale',          "Scale",          "ID=2: Scale constraint"),
    ('BlendShape',     "BlendShape",     "ID=3: Blend-shape / morph target"),
    ('UnkCtrl_4',      "UnkCtrl_4",      "ID=4: Unknown control type"),
    ('UnkTopBank_5',   "UnkTopBank_5",   "ID=5: Unknown top-bank type"),
    ('Unknown_6',      "Unknown_6",      "ID=6: Undefined in bt template"),
    ('Material_Color', "Material_Color", "ID=7: Material color drive"),
    ('Material_4D',    "Material_4D",    "ID=8: Material 4D property drive"),
    ('Material_3D',    "Material_3D",    "ID=9: Material 3D property drive"),
    ('Material_2D',    "Material_2D",    "ID=10: Material 2D property drive"),
    ('Scalar',         "Scalar",         "ID=11: Scalar drive"),
    ('Unknown_12',     "Unknown_12",     "ID=12: Unknown"),
    ('UnkRotation_13', "UnkRotation_13", "ID=13: Unknown rotation variant"),
    ('UnkRotation_14', "UnkRotation_14", "ID=14: Unknown rotation variant"),
    ('UnkRotation_15', "UnkRotation_15", "ID=15: Unknown rotation variant"),
    ('UnkRotation_16', "UnkRotation_16", "ID=16: Unknown rotation variant"),
]

AXIS_TO_INT = {'X': 0, 'Y': 1, 'Z': 2, 'W': 3}
INT_TO_AXIS = {0: 'X', 1: 'Y', 2: 'Z', 3: 'W'}

TRANSFORM_TYPE_MAP = {
    0:  'Translation',
    1:  'Rotation',
    2:  'Scale',
    3:  'BlendShape',
    4:  'UnkCtrl_4',
    5:  'UnkTopBank_5',
    6:  'Unknown_6',
    7:  'Material_Color',
    8:  'Material_4D',
    9:  'Material_3D',
    10: 'Material_2D',
    11: 'Scalar',
    12: 'Unknown_12',
    13: 'UnkRotation_13',
    14: 'UnkRotation_14',
    15: 'UnkRotation_15',
    16: 'UnkRotation_16',
}


# ---------------------------------------------------------------------------
# Search callback for source_bone (populated from hash_list at import time)
# ---------------------------------------------------------------------------

def _update_flags_from_bits(self, context):
    """Called when any flag_bit_N changes — repack into cns_flags."""
    self['cns_flags'] = sum(int(getattr(self, f'flag_bit_{i}')) << i for i in range(8))


def _update_bits_from_flags(self, context):
    """Called when cns_flags changes — unpack into flag_bit_N."""
    v = self.cns_flags & 0xFF
    for i in range(8):
        self[f'flag_bit_{i}'] = bool(v & (1 << i))


def _refresh_preview_values(self, context):
    """Cheap path: only numbers changed, so a preview already in place can stay."""
    try:
        from . import jcns_preview
        jcns_preview.refresh(self.id_data, structural=False)
    except Exception as exc:
        print("[JCNS] preview value refresh skipped: %r" % exc)


def _sync_constraint_name(self):
    """Re-derive this constraint's Empty name from its own current properties.

    Only touches this one Empty and keeps its existing '[N]' index — renumbering
    everyone is a separate, deliberate step (see JCNS_OT_DeleteConstraint and
    JCNS_OT_MirrorConstraints), not a side effect of editing a field.
    """
    obj = self.id_data
    if obj is None:
        return
    p = getattr(obj, 'jcns_cns_props', None)
    if p is None or not p.is_jcns_constraint:
        return
    # Section Empties keep their '[AimNN] …' style names: the exporter reads the
    # entry order back out of the prefix.  Material / JXG labels never change.
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
    """Keep an already-applied preview in step with the field being edited, and
    keep the Empty's name in sync.  Used by the fields (bone / axis / transform
    type, and each section's bones) that the display name and the preview are
    built from.

    Without the refresh the rig keeps showing what it showed when Apply was last
    pressed.  Does nothing when no preview is on, so it costs nothing while
    authoring.
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

    If the typed text is not already in the known list it is prepended as the
    first suggestion so the user can confirm a brand-new bone name by pressing
    Enter or clicking the first item, without being forced onto a partial match.
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

    Not the data: the source's F-Curve is (jcns_cm.py).  These are kept so an
    untouched curve exports its original bytes; see jcns_cm.records().
    FromX/ToX are a key, (FromY, ToY) / (FromZ, ToZ) its incoming / outgoing
    tangent as (dx, dy), and the flag does not change the result in game.
    """
    from_x: FloatProperty(name="From X", default=0.0)
    to_x:   FloatProperty(name="To X",   default=0.0)
    from_y: FloatProperty(name="From Y", default=0.0)
    to_y:   FloatProperty(name="To Y",   default=0.0)
    from_z: FloatProperty(name="From Z", default=0.0)
    to_z:   FloatProperty(name="To Z",   default=0.0)
    flag:   IntProperty(name="Flag", description="ComplexSrcMapping.UnknownUInt32 (0/8/5/2 seen)",
                        default=0, min=0)


class JCNSConeInfo(PropertyGroup):
    """One ConeDriverInfo record (24 bytes, v24+): a cone this constraint reads.

    RE9 v35: Rest is (0,0,0,0), or (0,0,0,1) on scale targets; Value is what the
    target takes for that cone (bt: AngleDeg, but scale targets hold factors).
    """
    cone_index: IntProperty(name="ConeDriver", description="ConeDriver 表里的序号", default=0, min=0)
    value: FloatProperty(name="输出值", description="bt: AngleDeg —— 这个锥形对应的目标值", default=0.0)
    rest: FloatVectorProperty(name="Rest", size=4, default=(0.0, 0.0, 0.0, 0.0))
    unk_byte0: IntProperty(name="+20", default=0, min=0, max=255)
    unk_byte3: IntProperty(name="+23", default=0, min=0, max=255)


class JCNSWeightedSource(PropertyGroup):
    """One source bone of a SkinConstraint record."""
    bone: StringProperty(name="骨骼", default="", update=_refresh_preview,
                         search=lambda self, context, text: _search_bone_names(context, text))
    weight: FloatProperty(name="权重", default=1.0, precision=4, update=_refresh_preview_values)


class JCNSSourceProperties(PropertyGroup):
    """
    One driving source of a constraint — maps 1:1 onto a 72-byte
    ConstraintSource_v2 block in the file.

    A constraint has SourceCount of these (about 12% of constraints in shipped
    files have more than one; up to 8 have been observed).
    """

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
        name="From 起点", description="MapFrom 点A — 第一段起始锚点（源角度，单位度）",
        default=0.0, precision=2, step=10,
    )
    from_kink: FloatProperty(
        update=_refresh_preview_values,
        name="From 折点", description="MapFrom 点B — 两段斜率的分界折点（源角度，单位度）",
        default=0.0, precision=2, step=10,
    )
    from_end: FloatProperty(
        update=_refresh_preview_values,
        name="From 终点", description="MapFrom 点C — 第二段终止锚点，源骨骼最大偏转角（单位度）",
        default=0.0, precision=2, step=10,
    )
    to_start: FloatProperty(
        update=_refresh_preview_values,
        name="To 起点", description="MapTo 点A — 对应 from_start 的输出值",
        default=0.0, precision=2, step=10,
    )
    to_kink: FloatProperty(
        update=_refresh_preview_values,
        name="To 折点", description="MapTo 点B — 折点处的输出值（引擎读取此值）",
        default=0.0, precision=2, step=10,
    )
    to_end: FloatProperty(
        update=_refresh_preview_values,
        name="To 终点", description="MapTo 点C — 目标骨骼最大输出旋转量（单位度）",
        default=0.0, precision=2, step=10,
    )

    # --- Reference frame (+56, stored as "rest_quat") ---
    # Not the bone's rest pose (the engine takes that from the skeleton): it is the
    # frame the swing-twist and rotation-vector reads decompose in, f^-1 * q * f
    # (measured 2026-09-30, round 8).  Identity in all but two shipped sources.
    rest_quat_x: FloatProperty(name="参考系 X", default=0.0, precision=5,
                               update=_refresh_preview)
    rest_quat_y: FloatProperty(name="参考系 Y", default=0.0, precision=5,
                               update=_refresh_preview)
    rest_quat_z: FloatProperty(name="参考系 Z", default=0.0, precision=5,
                               update=_refresh_preview)
    rest_quat_w: FloatProperty(name="参考系 W", default=1.0, precision=5,
                               update=_refresh_preview)

    # --- Raw bytes ---
    # +24 and +25 both default to 3, the most common value in shipped files.
    update_timing: IntProperty(
        update=_refresh_preview_values,
        name="曲线模式 (+24)",
        description=(
            "ConstraintSource_v2 byte +24 — 实测(2026-08-21)是曲线模式开关，不是更新时机。"
            "0 和 1 = 两点直线：忽略折点，直接从 (from_start,to_start) 连到 (from_end,to_end)。"
            "2 和 3 = 三点分段折线，折点生效。每一对内部实测逐位相同，即 bit 1 (0x02) 决定模式。"
            "三点模式下若折点落在 [start, end] 区间之外，整条源失效、输出恒 0。"
            "（bt 0.65.14 曾把它读作 UpdateTimingID：" + UPDATE_TIMING_HINT + "，那是误判）"
        ),
        default=3, min=0, max=255,
    )
    read_mode: EnumProperty(
        update=_refresh_preview,
        name="读取方式 (+25)",
        description=(
            "ConstraintSource_v2 byte +25（bt 叫 TransformIDSrc / InterpolationID）："
            "引擎怎样读源骨。一律读相对父骨的完整变换，静止姿态和静止偏移都算在内，"
            "这里只决定取位置、缩放，还是旋转的哪种分解。2026-09-30 实机逐个测定"
        ),
        items=_READ_MODE_ITEMS,
        default=_READ_MODE_DEFAULT,
    )
    euler_order: EnumProperty(
        update=_refresh_preview,
        name="欧拉顺序 (+27)",
        description=(
            "ConstraintSource_v2 byte +27（原 UnkByte2）：读取方式为「欧拉角」时的分解顺序，"
            "其他读取方式忽略它（2026-09-30 实测）。原版里跟着源骨走：大腿/手多为 1，手指 2，"
            "翅膀 3，其余几乎都是 0"
        ),
        items=_EULER_ORDER_ITEMS,
        default='XYZ',
    )
    complex_mapping_info_count: IntProperty(
        name="复杂映射数", description="bt: ComplexMappingInfoCount",
        default=0, min=0, max=65535,
    )
    unknown_uint16: IntProperty(
        name="未知 UInt16", description="ConstraintSource_v2 偏移 +22",
        default=0, min=0, max=65535,
    )
    unknown_uint32_2: IntProperty(
        name="未知 UInt32 (+28)", description="ConstraintSource_v2 偏移 +28",
        default=0, min=0,
    )
    # ComplexMapping: the curve is an F-Curve on the constraint Empty, on the custom
    # property named here (jcns_cm.py); cm_cache holds the file's own records.
    cm_channel: StringProperty(default="")
    cm_cache: CollectionProperty(type=JCNSCMKey)


# ---------------------------------------------------------------------------
# Property Group: attached to each constraint Empty child object
# ---------------------------------------------------------------------------

class JCNSConstraintProperties(PropertyGroup):
    """
    Stored on every per-constraint child Empty inside a JCNS collection.
    Maps onto one 80-byte ConstraintInfo block plus its list of sources.
    """

    # Explicit marker — set at import / Add Constraint.  Previously the addon
    # detected constraint Empties by 'source_bone is non-empty', which stopped
    # working once sources moved into their own collection.
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

    # --- ConstraintInfo raw fields (editable, exported) ---
    # flags_cns: editable int + 8 bit checkboxes (bidirectional sync via update callbacks)
    cns_flags: IntProperty(
        name="标志位", description="bt: flags_cns。位4（驱动骨骼）与位5（驱动量为旋转）在导出时会按变换类型自动重算；位0 保留你的设置",
        default=0x31, min=0, max=255, update=_update_bits_from_flags,
    )
    flags_expanded: BoolProperty(name="展开标志位", default=False)
    flag_bit_0: BoolProperty(name="Bit0 — isAdd?",  default=True,  update=_update_flags_from_bits)
    flag_bit_1: BoolProperty(name="Bit1",            default=False, update=_update_flags_from_bits)
    flag_bit_2: BoolProperty(name="Bit2",            default=False, update=_update_flags_from_bits)
    flag_bit_3: BoolProperty(name="Bit3",            default=False, update=_update_flags_from_bits)
    flag_bit_4: BoolProperty(name="Bit4 — isJoint?",default=True,  update=_update_flags_from_bits)
    flag_bit_5: BoolProperty(name="Bit5",            default=True,  update=_update_flags_from_bits)
    flag_bit_6: BoolProperty(name="Bit6",            default=False, update=_update_flags_from_bits)
    flag_bit_7: BoolProperty(name="Bit7",            default=False, update=_update_flags_from_bits)
    parent_vec4_x: FloatProperty(name="Vec4 X", default=0.0, precision=5)
    parent_vec4_y: FloatProperty(name="Vec4 Y", default=0.0, precision=5)
    parent_vec4_z: FloatProperty(name="Vec4 Z", default=0.0, precision=5)
    parent_vec4_w: FloatProperty(name="Vec4 W", default=1.0, precision=5)
    parent_float2_x: FloatProperty(name="Float2 X", default=0.0, precision=5)
    parent_float2_y: FloatProperty(name="Float2 Y", default=0.0, precision=5)
    parent_uint8_72: IntProperty(
        name="UnknownUInt8 (+72)", description="ConstraintInfo byte at offset +72",
        default=0, min=0, max=255,
    )
    # A uint32 hash in a signed IntProperty: values >= 2**31 are stored as their
    # two's-complement negative (importer), and masked back on export.
    property_hash: IntProperty(
        name="PropertyHash", description="bt: PropertyHash — usually 0 (uint32, shown signed)",
        default=0,
    )
    # ConeDriverInfo[]: the cones this constraint reads (RE9 uses them heavily)
    cone_infos: CollectionProperty(type=JCNSConeInfo)
    active_cone_info_index: IntProperty(default=0)
    # Of these six, only [1] (+75) and [3] (+77) ever hold anything: [2]/[4]/[5]
    # are zero in all 19884 shipped constraints and [0] in 98.8% of them.
    # [1]=2 is both the corpus mode (70%) and what the verified hand-authored
    # file uses.  [3] is the joint-group count (jcns_writer.tail_group_counts).
    parent_tail_0: IntProperty(name="Tail[0]", default=0, min=0, max=255)
    parent_tail_1: IntProperty(name="Tail[1]", default=2, min=0, max=255)
    parent_tail_2: IntProperty(name="Tail[2]", default=0, min=0, max=255)
    parent_tail_3: IntProperty(
        name="关节组计数 (Tail[3])",
        description=(
            "紧跟在这条后面、与它同目标同变换同 Flags 的连续条目数（组首填 N，组员填 0）。"
            "引擎把整组输出都写到组首条目的目标骨上，数错了结果会落到别的骨头上"
            "（2026-09-30 实测）。导出时自动校验：整份文件构成合法分组就照写，否则全部重算"
        ),
        default=0, min=0, max=255)
    parent_tail_4: IntProperty(name="Tail[4]", default=0, min=0, max=255)
    parent_tail_5: IntProperty(name="Tail[5]", default=0, min=0, max=255)

    # --- Material constraint-specific fields (populated at import, editable) ---
    mat_name_hash: StringProperty(
        name="MaterialNameHash",
        description="Direct hash of the material name (hex uint32, e.g. 0x1A2B3C4D)",
        default="0x00000000",
    )
    mat_property_hash: StringProperty(
        name="MaterialPropertyHash",
        description="Direct hash of the material property (hex uint32)",
        default="0x00000000",
    )
    mat_transform_type_raw: IntProperty(
        name="TransformationID",
        description="Material TransformationID byte",
        default=0, min=0, max=255,
    )
    mat_tail_0: IntProperty(name="MatTail[0]", default=0, min=0, max=255)
    mat_tail_1: IntProperty(name="MatTail[1]", default=0, min=0, max=255)
    mat_tail_2: IntProperty(name="MatTail[2]", default=0, min=0, max=255)

    # --- JointExportGraph path (Type 5 empties only) ---
    jxg_path: StringProperty(
        name="路径",
        description="JointExportGraph 路径字符串（文件中为 UTF-16LE）",
        default="",
    )

    # --- SkinConstraint (target_bone is the skinned object) ---
    skin_sources: CollectionProperty(type=JCNSWeightedSource)
    active_skin_source_index: IntProperty(default=0)
    skin_tail_hex: StringProperty(
        name="尾部 2 字节", default="",
        description="记录尾部第 2、3 字节（第 1 字节是每文件常量）。v102 恒为 0000，RE9 v35 逐条不同；"
                    "留空则用本文件最常见的值")

    # --- Aim (target_bone is the aimed joint) ---
    aim_target_bone: StringProperty(name="瞄准目标", default="", update=_refresh_preview,
                                    search=_search_target_bone)
    aim_up_bone: StringProperty(name="辅助骨骼", description="AimVectorPointJoint；留空表示不使用",
                                default="", update=_refresh_preview, search=_search_target_bone)
    aim_influence: FloatProperty(name="影响", default=1.0, update=_refresh_preview_values)
    aim_vec0: FloatVectorProperty(name="Vec0", size=3, default=(0.0, 0.0, 0.0))
    aim_vec1: FloatVectorProperty(name="Vec1", size=3, default=(1.0, 0.0, 0.0),
                                  update=_refresh_preview_values)
    aim_vec2: FloatVectorProperty(name="Vec2", size=3, default=(0.0, 1.0, 0.0))
    aim_vec3: FloatVectorProperty(name="Vec3", size=3, default=(0.0, 1.0, 0.0))
    aim_rotation_type: IntProperty(name="RotationType", default=0, min=0, max=255)
    aim_bytes: IntVectorProperty(name="字节 +57..59", size=3, default=(1, 0, 5), min=0, max=255)
    aim_tail_hex: StringProperty(name="尾部 12 字节", default="00" * 12)
    aim_target_tail_hex: StringProperty(name="目标块尾部 8 字节", default="00" * 8)

    # --- RotExpression (target_bone is the driven joint) ---
    rot_source_bone: StringProperty(name="源骨骼", default="", update=_refresh_preview,
                                    search=_search_target_bone)
    rot_rotation: FloatVectorProperty(name="Rotation", size=4, default=(0.0, 0.0, 0.0, 1.0))
    rot_scale: FloatVectorProperty(name="Scale", size=4, default=(0.0, 0.0, 0.0, 1.0))
    rot_bytes: IntVectorProperty(name="字节", size=4, default=(0, 0, 0, 0), min=0, max=255)
    rot_floats: FloatVectorProperty(name="尾部浮点", size=3, default=(1.0, 1.0, 1.0),
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
    try:
        rot_map = bytes.fromhex(rp.rot_map_hex or '')
    except ValueError:
        rot_map = b''
    return get_kinds().FileState(
        version=v,
        rebuild=write_mode(v) == 'rebuild',
        sections_cached=bool(rp.sections_cached),
        has_armature=rp.target_armature is not None,
        has_read_table=bool(rp.read_joint_signature_json),
        rot_map_uniform=len(set(rot_map)) <= 1,
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
    """
    Stored on the root Empty of a JCNS collection.
    The collection contains one root Empty + N per-constraint Empties.
    """
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
    cached_file_header: StringProperty(
        name="Cached File Header",
        description="Base64 of the source file's Tags block + DataInfo header — allows export without the source file present",
        default="",
    )
    cached_section_table: StringProperty(
        name="Cached Section Table",
        description="Base64 of section table data from source file",
        default="",
    )
    # There used to be a `source_combine` enum here (SUM/MAX/MIN/AVERAGE/FIRST)
    # because the engine's folding rule was unknown.  It is known now, measured
    # in-game by sweeping synthetic driver bones across their whole input range:
    #
    #   several sources in ONE constraint  -> each maps independently, outputs SUM
    #   several constraints on ONE channel -> the LAST in file order wins outright
    #
    # Both are fixed behaviour, so there is nothing left for the user to choose,
    # and leaving the enum in place would only invite mis-configuration.
    source_version: IntProperty(
        name="JCNS 版本",
        description="Version number of the imported file (the .jcns.<N> suffix); 0 = imported by an older add-on",
        default=0,
    )
    # Set by importers that store Skin / Aim / RotExpression / ComplexMapping in
    # Blender.  Files imported before that keep exporting those sections from the
    # re-parsed source file, since their Empties hold no data.
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
    skin_constant: IntProperty(default=5)
    read_joint_table_hex: StringProperty(default="")
    read_joint_signature_json: StringProperty(default="")
    rot_map_hex: StringProperty(default="")
    object_settings_json: StringProperty(default="")
    # ConeDriver table (v35+), cached so a rebuild can re-emit it
    cone_drivers_json: StringProperty(default="")
    # Superseded by source_version; kept so files imported by 0.14 still export
    # with the right suffix.
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
    """Find the JCNS root Empty inside a Collection, or (None, None).

    Each import creates exactly one root per collection, so a plain scan is
    enough — no parent/child walk needed here since we start from the
    collection itself.
    """
    if collection is None:
        return None, None
    for obj in collection.objects:
        root_props = getattr(obj, 'jcns_root_props', None)
        if root_props and root_props.source_filepath:
            return obj, root_props
    return None, None


def get_export_root(context):
    """(root, root_props) that operators like export should act on.

    The scene's "工作集合" (active collection) wins when set, so export is
    reachable from anywhere in the scene without hunting down the right
    Empty first. With nothing set, falls back to whatever JCNS object is
    currently selected — the previous, only, behaviour.
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
    """
    Return an ordered list of constraint Empty objects under the root.
    Prefers direct children (parent-child hierarchy); falls back to flat
    collection search for legacy imports.
    Sorted by the numeric prefix '[N]' in their names.
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

    JCNS happily stores several ConstraintInfo blocks that drive the same bone on
    the same axis, and the engine evidently folds them together.  Blender allows
    exactly one driver per F-Curve channel, so constraints sharing a key have to
    be merged into a single driver — applying them one by one just means the last
    one silently replaces all the others.
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
    """
    Generate the canonical display name for a constraint Empty.

    extra_sources > 0 appends '(+N)' so multi-source constraints are visible in
    the Outliner without opening the panel.  A constraint driven only by
    ConeDrivers shows 'Cone×N' where the source would be.
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
from . import jcns_cm

def _poll_jcns_collection(self, collection):
    """Restrict the active-collection picker to collections that hold a JCNS root."""
    root, _ = get_jcns_root_from_collection(collection)
    return root is not None


_classes = [
    JCNSCMKey,                  # groups must register before the groups that reference them
    JCNSConeInfo,
    JCNSWeightedSource,
    JCNSSourceProperties,
    JCNSConstraintProperties,
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
    jcns_importer.register()
    jcns_exporter.register()
    jcns_ui.register()
    jcns_editors.register()
    jcns_drivers.register()
    jcns_cm.register()


def unregister():
    jcns_cm.unregister()
    jcns_drivers.unregister()
    jcns_editors.unregister()
    jcns_ui.unregister()
    jcns_exporter.unregister()
    jcns_importer.unregister()
    jcns_preview.unregister()
    jcns_operators.unregister()

    del bpy.types.Scene.jcns_active_collection
    del bpy.types.Object.jcns_cns_props
    del bpy.types.Object.jcns_root_props

    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
