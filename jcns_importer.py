"""
jcns_importer.py
----------------
Import operator for RE Engine JCNS files (every version in jcns_schema).

Builds a collection JCNS_<filename> holding one root Empty (JCNSRootProperties)
and one child Empty per entry (JCNSConstraintProperties).
"""

import os
import sys
import bpy
from bpy.props import StringProperty, BoolProperty, EnumProperty
from bpy.types import Operator
from bpy_extras.io_utils import ImportHelper

from .modules_shim import get_schema, ensure_path

ensure_path()
import jcns_source_read  # noqa: E402
from . import jcns_cm

_SCHEMA = get_schema()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_modules_path():
    addon_dir = os.path.dirname(__file__)
    modules_dir = os.path.join(addon_dir, "modules")
    if modules_dir not in sys.path:
        sys.path.insert(0, modules_dir)


def _get_armature_items(self, context):
    items = [("NONE", "(None — skip hash resolution)", "", 'X', 0)]
    for i, obj in enumerate(context.scene.objects):
        if obj.type == 'ARMATURE':
            items.append((obj.name, obj.name, f"Use armature '{obj.name}'", 'ARMATURE_DATA', i + 1))
    return items


def _build_hash_dict(armature_obj):
    """{uint32_hash: bone_name} over UTF-8 and UTF-16 MurmurHash3 of each bone name
    and its lower-case form."""
    _ensure_modules_path()
    hashing_dir = os.path.join(os.path.dirname(__file__), "modules", "hashing")
    if hashing_dir not in sys.path:
        sys.path.insert(0, hashing_dir)
    try:
        from mmh3 import pymmh3
    except ImportError:
        return {}

    hash_dict = {}
    for bone in armature_obj.data.bones:
        name = bone.name
        for fn in (pymmh3.hashUTF8, pymmh3.hashUTF16):
            try:
                h = fn(name) & 0xFFFFFFFF
                hash_dict[h] = name
                h2 = fn(name.lower()) & 0xFFFFFFFF
                hash_dict[h2] = name
            except Exception:
                pass
    return hash_dict


def _hash_name(name):
    hashing_dir = os.path.join(os.path.dirname(__file__), "modules", "hashing")
    if hashing_dir not in sys.path:
        sys.path.insert(0, hashing_dir)
    from mmh3.pymmh3 import hashUTF16
    return hashUTF16(name) & 0xFFFFFFFF


def _strip_ext(filename):
    """Strip JCNS version suffixes: 'foo.jcns.102' → 'foo'."""
    for v in _SCHEMA.SUPPORTED_VERSIONS:
        if filename.endswith(f'.{v}'):
            filename = filename[:-len(f'.{v}')]
            break
    if filename.endswith('.jcns'):
        filename = filename[:-len('.jcns')]
    return filename


# ---------------------------------------------------------------------------
# Core import logic (also callable from operators without a file dialog)
# ---------------------------------------------------------------------------

def do_import(filepath, context, armature_obj=None):
    """
    Parse the JCNS file and build the collection hierarchy.
    Returns (root_empty, count, error_str).  error_str is '' on success.
    """
    from . import (
        AXIS_TO_INT, INT_TO_AXIS, TRANSFORM_TYPE_MAP,
        make_constraint_empty_name,
    )

    _ensure_modules_path()
    try:
        from jcns_parser import JCNSParser
        parser = JCNSParser(filepath)
        constraints = parser.parse()
    except Exception as exc:
        return None, 0, f"解析失败：{exc}"

    # A file the writer cannot reproduce could never be exported back: refuse it.
    from jcns_validate import check_exportable
    problems = check_exportable(parser)
    if problems:
        msg = ("无法导入 —— 这个文件含有写入器无法完整还原的结构，编辑了也没法导出：\n"
               + "\n".join(f"  * {p}" for p in problems))
        return None, 0, msg

    hash_dict = _build_hash_dict(armature_obj) if armature_obj else {}

    filename = _strip_ext(os.path.basename(filepath))
    coll_name = f"JCNS_{filename}"
    coll = bpy.data.collections.new(coll_name)
    coll.color_tag = 'COLOR_04'   # green
    context.scene.collection.children.link(coll)

    root = bpy.data.objects.new(coll_name, None)
    root.empty_display_type = 'PLAIN_AXES'
    root.empty_display_size = 0.2
    root.show_in_front = True
    coll.objects.link(root)

    root.jcns_root_props.source_filepath = filepath
    if armature_obj:
        root.jcns_root_props.target_armature = armature_obj

    # Drives the export extension and the writer mode.
    root.jcns_root_props.source_version = parser.version

    # Header and section table, cached for export when the source file is missing.
    import base64
    raw = parser.original_bytes
    root.jcns_root_props.cached_file_header = base64.b64encode(
        raw[:parser.header['HeaderEnd']]).decode('ascii')
    orig_sec_off = parser.header.get('SectionTableEntry', 0)
    sec_count = parser.header.get('SectionTableItemCount', 0)
    if orig_sec_off > 0 and orig_sec_off + sec_count * 4 <= len(raw):
        sec_data = raw[orig_sec_off : orig_sec_off + sec_count * 4]
    else:
        sec_data = b'\x00\x00\x00\x00'
    root.jcns_root_props.cached_section_table = base64.b64encode(sec_data).decode('ascii')

    root["jcns_source"] = filepath

    for idx, c in enumerate(constraints):
        file_sources = c.get('sources', [])
        target_bone_name_from_file = c.get('ObjectName', '')

        # The file's own name first, then the armature's hash lookup.
        target_bone = target_bone_name_from_file
        if not target_bone and hash_dict:
            tgt_hash = c.get('TargetHash', 0)
            target_bone = hash_dict.get(tgt_hash, '')

        tgt_ax_str = INT_TO_AXIS.get(min(c.get('target_axis', 0), 3), 'X')

        transform_int = c.get('TransformType', 1)
        transform_str = TRANSFORM_TYPE_MAP.get(transform_int, 'Unknown')

        first = file_sources[0] if file_sources else {}
        empty_name = make_constraint_empty_name(
            idx, first.get('SourceName', ''), target_bone, tgt_ax_str,
            INT_TO_AXIS.get(min(first.get('source_axis', 0), 3), 'X'),
            max(0, len(file_sources) - 1),
            len(c.get('ConeDriverInfo') or []),
        )

        obj = bpy.data.objects.new(empty_name, None)
        obj.empty_display_type = 'ARROWS'
        obj.empty_display_size = 0.05
        obj.parent = root
        coll.objects.link(obj)

        p = obj.jcns_cns_props
        p.is_jcns_constraint = True
        p.constraint_type = 'Ranges'
        p.target_bone    = target_bone
        p.transform_type = transform_str
        p.target_axis    = tgt_ax_str

        p.sources.clear()
        for s in file_sources:
            sp = p.sources.add()
            sp.source_bone = s.get('SourceName', '')
            sp.source_axis = INT_TO_AXIS.get(min(s.get('source_axis', 0), 3), 'X')
            sp.from_start  = s.get('from_start', 0.0)
            sp.from_kink   = s.get('from_kink',  0.0)
            sp.from_end    = s.get('from_end',   0.0)
            sp.to_start    = s.get('to_start',   0.0)
            sp.to_kink     = s.get('to_kink',    0.0)
            sp.to_end      = s.get('to_end',     0.0)
            sp.rest_quat_x = s.get('rest_quat_x', 0.0)
            sp.rest_quat_y = s.get('rest_quat_y', 0.0)
            sp.rest_quat_z = s.get('rest_quat_z', 0.0)
            sp.rest_quat_w = s.get('rest_quat_w', 1.0)
            sp.update_timing    = s.get('CurveMode', 3)
            mode = jcns_source_read.read_mode_id(s.get('ReadMode', 3))
            if mode is None:
                # The enum cannot hold an unknown mode.
                print("[JCNS] %s <- %s: ReadMode %r is unknown, read as SWING_TWIST"
                      % (c.get('ObjectName', '?'), s.get('SourceName', '?'), s.get('ReadMode')))
                mode = 'SWING_TWIST'
            sp.read_mode = mode
            order = jcns_source_read.EULER_ORDER_NAMES.get(s.get('EulerOrder', 0))
            if order is None:
                # The enum holds only orders 0-3.
                print("[JCNS] %s <- %s: EulerOrder %r is unknown, read as XYZ"
                      % (c.get('ObjectName', '?'), s.get('SourceName', '?'), s.get('EulerOrder')))
                order = 'XYZ'
            sp.euler_order = order
            sp.complex_mapping_info_count = s.get('ComplexMappingInfoCount', 0)
            sp.unknown_uint16   = s.get('UnknownUInt16', 0)
            sp.unknown_uint32_2 = s.get('UnknownUInt32_2', 0)
            if s.get('ComplexMapping'):
                jcns_cm.load(sp, s['ComplexMapping'])

        # cns_flags' update callback syncs the 8 bit properties.
        p.cns_flags = c.get('Flags', 0x30)
        vec4                    = c.get('ParentVec4', (0.0, 0.0, 0.0, 1.0))
        p.parent_vec4_x, p.parent_vec4_y, p.parent_vec4_z, p.parent_vec4_w = vec4
        f2                      = c.get('ParentFloat2', (0.0, 0.0))
        p.parent_float2_x, p.parent_float2_y = f2
        p.parent_uint8_72       = c.get('ParentUInt8_72', 0)
        ph                      = c.get('PropertyHash', 0) & 0xFFFFFFFF
        p.property_hash         = ph - (1 << 32) if ph >= (1 << 31) else ph
        for ci in c.get('ConeDriverInfo') or []:
            k = p.cone_infos.add()
            k.cone_index, k.value = ci['ConeDriverIndex'], ci['Value']
            k.rest = (ci['Rest0'],) + tuple(ci.get('Rest123', (0.0, 0.0, 0.0)))
            k.unk_byte0, k.unk_byte3 = ci['UnkByte0'], ci['UnkByte3']
        if len(p.cone_infos):
            # Rename: target_bone's update named it while the cone list was empty.
            from . import constraint_name_from_props
            obj.name = constraint_name_from_props(idx, p)
        tail = c.get('ParentTailBytes', b'\x00' * 6)
        p.parent_tail_0, p.parent_tail_1, p.parent_tail_2 = tail[0], tail[1], tail[2]
        p.parent_tail_3, p.parent_tail_4, p.parent_tail_5 = tail[3], tail[4], tail[5]


    # Non-Ranges sections store hashes only.  Resolve through the armature, then the
    # names this file's Ranges spell out, then the bundled dictionary, else show the
    # raw hash (the exporter reads a "0x1234ABCD" name back as that hash).
    import json
    from jcns_sections import skin_editable, read_joint_signature, aim_editable, rot_editable
    from jcns_names import name_of
    from . import section_empty_name
    names = {}
    for c in constraints:
        for nm in [c.get('ObjectName', '')] + [s_.get('SourceName', '') for s_ in c.get('sources', [])]:
            if nm:
                names[_hash_name(nm)] = nm
    names.update(hash_dict)

    def _nm(h):
        return names.get(h) or name_of(h) or f"0x{h:08X}"

    def _section_empty(kind, idx, display, size):
        obj = bpy.data.objects.new(f"[{kind}{idx:02d}]", None)
        obj.empty_display_type = display
        obj.empty_display_size = size
        obj.parent = root
        coll.objects.link(obj)
        p2 = obj.jcns_cns_props
        p2.is_jcns_constraint = True
        return obj, p2

    rp = root.jcns_root_props
    sk_recs, sk_meta = skin_editable(parser)
    for idx, r in enumerate(sk_recs):
        obj, p2 = _section_empty('Skin', idx, 'SINGLE_ARROW', 0.03)
        p2.constraint_type = 'Skin'
        p2.target_bone = _nm(r['object'])
        p2.skin_tail_hex = r['tail'].hex()
        for src in r['sources']:
            w = p2.skin_sources.add()
            w.bone, w.weight = _nm(src['hash']), src['weight']
        obj.name = section_empty_name('Skin', idx, p2)
    rp.skin_constant = sk_meta['constant']
    rp.read_joint_table_hex = b''.join(h.to_bytes(4, 'little') for h in sk_meta['read_joint_table']).hex()
    aim_recs = aim_editable(parser)
    rp.read_joint_signature_json = (json.dumps(read_joint_signature(sk_recs, [a['joint'] for a in aim_recs]))
                              if sk_meta['read_joint_table'] else '')

    for idx, a in enumerate(aim_recs):
        obj, p2 = _section_empty('Aim', idx, 'SPHERE', 0.03)
        p2.constraint_type = 'Aim'
        p2.target_bone = _nm(a['joint'])
        p2.aim_target_bone = _nm(a['target'])
        p2.aim_up_bone = _nm(a['up']) if a['up'] is not None else ''
        p2.aim_influence = a['influence']
        p2.aim_vec0, p2.aim_vec1, p2.aim_vec2, p2.aim_vec3 = a['vectors']
        p2.aim_rotation_type = a['rotation_type']
        p2.aim_bytes = a['bytes']
        p2.aim_tail_hex = a['tail'].hex()
        p2.aim_target_tail_hex = a['target_tail'].hex()
        obj.name = section_empty_name('Aim', idx, p2)

    rot_recs, rot_meta = rot_editable(parser)
    for idx, r in enumerate(rot_recs):
        obj, p2 = _section_empty('RotExpr', idx, 'CIRCLE', 0.03)
        p2.constraint_type = 'RotExpression'
        p2.target_bone = _nm(r['joint'])
        p2.rot_source_bone = _nm(r['source'])
        p2.rot_rotation, p2.rot_scale = r['rotation'], r['scale']
        p2.rot_bytes, p2.rot_floats = r['bytes'], r['floats']
        obj.name = section_empty_name('RotExpression', idx, p2)
    rp.rot_map_hex = bytes(rot_meta['map']).hex()

    rp.cone_drivers_json = json.dumps([{
        'Name': cd['Name'], 'Direction': list(cd['Direction']), 'Matrix': list(cd['Matrix']),
        'JointHash': cd['JointHash'], 'ParentJointHash': cd['ParentJointHash'],
        'SymmetryJointHash': cd['SymmetryJointHash'], 'AngleRad': cd['AngleRad'],
        'UnknownUInt32': cd['UnknownUInt32'], 'Tail': cd['Tail'].hex()}
        for cd in getattr(parser, 'cone_drivers', [])]) if getattr(parser, 'cone_drivers', []) else ''
    rp.object_settings_json = json.dumps([
        {'UnkBytes': o['UnkBytes'].hex(), 'UnknownDWORD': o['UnknownDWORD'],
         'ObjectNameHash': o['ObjectNameHash']} for o in parser.object_settings])
    rp.sections_cached = True

    for idx, mc in enumerate(parser.material_cns):
        jnt_name = _nm(mc['JointHash'])
        obj = bpy.data.objects.new(f"[Mat{idx:02d}] {jnt_name}", None)
        obj.empty_display_type = 'CUBE'
        obj.empty_display_size = 0.02
        obj.parent = root
        coll.objects.link(obj)
        p2 = obj.jcns_cns_props
        p2.is_jcns_constraint = True
        p2.constraint_type = 'Material'
        p2.target_bone = jnt_name
        import struct as _ms
        raw = mc['raw_body']        # 12 bytes: NameHash(4) + PropHash(4) + TransformID(1) + tail(3)
        p2.mat_name_hash        = f"0x{_ms.unpack_from('<I', raw, 0)[0]:08X}"
        p2.mat_property_hash    = f"0x{_ms.unpack_from('<I', raw, 4)[0]:08X}"
        p2.mat_transform_type_raw = raw[8]
        p2.mat_tail_0, p2.mat_tail_1, p2.mat_tail_2 = raw[9], raw[10], raw[11]

    if parser.joint_export_graph is not None:
        path = parser.joint_export_graph['path']
        obj = bpy.data.objects.new(f"[JXG] {path or '(empty)'}", None)
        obj.empty_display_type = 'IMAGE'
        obj.empty_display_size = 0.02
        obj.parent = root
        coll.objects.link(obj)
        p2 = obj.jcns_cns_props
        p2.is_jcns_constraint = True
        p2.constraint_type = 'JointExportGraph'
        p2.jxg_path = path

    # Every bone name the Ranges spell out: the choices offered for source_bone.
    all_bone_names = set()
    for c in constraints:
        tgt = c.get('ObjectName', '').strip()
        if tgt:
            all_bone_names.add(tgt)
        for s_ in c.get('sources', []):
            src = s_.get('SourceName', '').strip()
            if src:
                all_bone_names.add(src)
    root.jcns_root_props.available_bones_json = json.dumps(sorted(all_bone_names))

    return root, len(constraints), ''


# ---------------------------------------------------------------------------
# Import Operator
# ---------------------------------------------------------------------------

class JCNS_OT_ImportFile(Operator, ImportHelper):
    """导入 RE Engine 的 JCNS 关节约束文件，每条约束生成一个空物体"""
    bl_idname = "jcns.import_file"
    bl_label  = "RE Engine JCNS (.jcns.*)"
    bl_options = {'REGISTER', 'UNDO'}

    filter_glob: StringProperty(
        default=_SCHEMA.FILE_GLOB,
        options={'HIDDEN'},
    )

    # EnumProperty: PointerProperty is invalid on Operators.
    target_armature_name: EnumProperty(
        name="目标骨架",
        description="导入时用于把哈希还原成骨骼名的骨架",
        items=_get_armature_items,
    )

    resolve_hashes: BoolProperty(
        name="解析目标骨骼名",
        description="尝试用所选骨架把 TargetHash 还原成骨骼名",
        default=True,
    )

    def draw(self, context):
        layout = self.layout
        layout.label(text="JCNS 导入选项", icon='SETTINGS')
        layout.separator()
        layout.prop(self, "resolve_hashes")
        col = layout.column()
        col.enabled = self.resolve_hashes
        col.prop(self, "target_armature_name", icon='ARMATURE_DATA')

    def execute(self, context):
        filepath = self.filepath
        if not os.path.isfile(filepath):
            self.report({'ERROR'}, f"找不到文件：{filepath}")
            return {'CANCELLED'}

        armature_obj = None
        if self.resolve_hashes and self.target_armature_name != "NONE":
            armature_obj = context.scene.objects.get(self.target_armature_name)

        root, count, err = do_import(filepath, context, armature_obj)
        if err:
            self.report({'ERROR'}, err)
            return {'CANCELLED'}

        arm_label = armature_obj.name if armature_obj else "无"
        summary = f"已导入 {count} 条约束 → 「{root.name}」（骨架：{arm_label}）"
        self.report({'INFO'}, summary)
        # Make its collection the working collection so export works without a selection.
        bpy.ops.object.select_all(action='DESELECT')
        root.select_set(True)
        context.view_layer.objects.active = root
        if root.users_collection:
            context.scene.jcns_active_collection = root.users_collection[0]
        return {'FINISHED'}

    def invoke(self, context, event):
        for obj in context.scene.objects:
            if obj.type == 'ARMATURE':
                self.target_armature_name = obj.name
                break
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


# ---------------------------------------------------------------------------
# Drag-and-drop file handler (Blender 4.1+)
# ---------------------------------------------------------------------------

class JCNS_FH_ImportFile(bpy.types.FileHandler):
    bl_idname = "JCNS_FH_import_file"
    bl_label = "RE Engine JCNS"
    bl_import_operator = "jcns.import_file"
    bl_file_extensions = _SCHEMA.FILE_EXTENSIONS

    @classmethod
    def poll_drop(cls, context):
        return context.area and context.area.type in {'VIEW_3D', 'OUTLINER'}


# ---------------------------------------------------------------------------
# Menu hook
# ---------------------------------------------------------------------------

def _menu_import(self, context):
    self.layout.operator(JCNS_OT_ImportFile.bl_idname, text="RE Engine JCNS (.jcns.*)")


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

_classes = [JCNS_OT_ImportFile]


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_file_import.append(_menu_import)
    if bpy.app.version >= (4, 1, 0):
        bpy.utils.register_class(JCNS_FH_ImportFile)


def unregister():
    if bpy.app.version >= (4, 1, 0):
        bpy.utils.unregister_class(JCNS_FH_ImportFile)
    bpy.types.TOPBAR_MT_file_import.remove(_menu_import)
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
