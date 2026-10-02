"""
jcns_exporter.py
----------------
Export operator for RE Engine JCNS files (v102 and v35 rebuilt, other versions in place).

The source file is re-parsed (or a stub is built from what the import stored in the
root when it is missing), and JCNSWriter.build_lossless() writes the result.  Rebuilt
versions make every constraint from its Empty; in-place versions patch the record at
the Empty's position.
"""

import os
import sys
import hashlib
import bpy
from bpy.props import StringProperty, BoolProperty
from bpy.types import Operator
from bpy_extras.io_utils import ExportHelper

from .modules_shim import get_schema, ensure_path

ensure_path()
import jcns_source_read  # noqa: E402
import jcns_targets  # noqa: E402

_SCHEMA = get_schema()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_modules_path():
    addon_dir = os.path.dirname(__file__)
    modules_dir = os.path.join(addon_dir, "modules")
    if modules_dir not in sys.path:
        sys.path.insert(0, modules_dir)


def _get_active_root(context):
    """(root_empty, root_props) to export — see __init__.get_export_root()."""
    from . import get_export_root
    return get_export_root(context)


def _build_stub_parser(root_props):
    """
    A parser-like object for a file whose source is gone: the generated file header, and
    the section order and hash list the import stored.  Everything else comes from the
    Empties, so all constraints are new.
    """
    from jcns_parser import read_header, write_mode
    from jcns_schema import file_header

    version = _root_version(root_props)
    orig = file_header(version, tuple(root_props.header_unknown_bytes))

    class _StubParser:
        pass

    parser = _StubParser()
    parser.constraints = []
    parser.hash_list = [h.hash & 0xFFFFFFFF for h in root_props.hash_list]
    parser.section_order = [s.value for s in root_props.section_order]
    parser.original_bytes = orig
    parser.filepath = root_props.source_filepath
    parser.header = read_header(orig, check_layout=False)
    parser.version = version
    parser.write_mode = write_mode(version)
    parser.is_stub = True
    parser.aim_constraints    = []
    parser.object_settings    = []
    parser.skin_constraints   = []
    parser.skin_source_infos  = []
    parser.read_joint_table    = []
    parser.cone_drivers       = []
    parser.rot_expressions    = []
    parser.rot_expression_map = b''
    parser.material_cns       = []
    parser.joint_export_graph = None
    return parser


def skeleton_of(arm):
    """({joint hash: parent hash or None}, {joint hash: name}) of an armature, or (None, None)."""
    if arm is None or arm.type != 'ARMATURE':
        return None, None
    H = lambda name: _name_to_hash(name.strip())
    bones = arm.data.bones
    return ({H(b.name): (H(b.parent.name) if b.parent else None) for b in bones},
            {H(b.name): b.name for b in bones})


def _sync_sections_to_parser(root_obj, root_props, parser):
    """
    Rebuild parser.skin_* / aim_constraints / rot_expressions / cone_drivers (and,
    for the stub, object_settings) from Blender.  Returns refusals; empty == OK.

    Runs only for sections_cached roots in rebuild mode: in-place versions never
    re-emit these sections.
    """
    import json
    from . import section_empties, get_constraint_empties, AIM_TYPE_TO_INT
    _ensure_modules_path()
    import jcns_sections as X

    if not root_props.sections_cached or getattr(parser, 'write_mode', 'rebuild') != 'rebuild':
        return []

    def H(name):
        return _name_to_hash(name.strip())

    records = [{'object': H(o.jcns_cns_props.target_bone),
                'tail': bytes(o.jcns_cns_props.skin_tail),
                'sources': [{'hash': H(w.bone), 'weight': w.weight} for w in o.jcns_cns_props.skin_sources]}
               for o in section_empties(root_obj, 'Skin')]
    meta = {'constant': root_props.file_constant,
            'read_joint_table': [it.hash & 0xFFFFFFFF for it in root_props.read_joint_table]}
    locked = json.loads(root_props.read_joint_signature_json) if root_props.read_joint_signature_json else []
    # The table also covers the Aim joints, so it is resolved against both.
    aim_joints = [H(o.jcns_cns_props.target_bone) for o in section_empties(root_obj, 'Aim')]
    parent, names = skeleton_of(root_props.target_armature)
    table, problems = X.resolve_read_joint_table(records, aim_joints, meta, locked, parent, names,
                                                 pending=root_props.read_table_pending)
    if problems:
        return problems
    for w in X.skin_weight_warnings(records):
        print('[JCNS EXPORT] warning: ' + w)
    parser.skin_constraints, parser.skin_source_infos = X.skin_parser_form(records, meta)
    if table != meta['read_joint_table']:
        print('[JCNS EXPORT] ReadJointTable re-derived from the armature: %d -> %d joint(s)'
              % (len(meta['read_joint_table']), len(table)))
    parser.read_joint_table = table

    aims = []
    for o in section_empties(root_obj, 'Aim'):
        p = o.jcns_cns_props
        aims.append({
            'joint': H(p.target_bone), 'target': H(p.aim_target_bone),
            'up': H(p.aim_up_bone) if p.aim_up_bone.strip() else None,
            'influence': p.aim_influence,
            'vectors': [tuple(p.aim_offset), tuple(p.aim_axis), tuple(p.aim_up_axis), tuple(p.aim_up_dir)],
            'rotation_type': AIM_TYPE_TO_INT[p.aim_type], 'bytes': tuple(p.aim_bytes),
        })
    parser.aim_constraints = X.aim_parser_form(aims)

    rots = [{'joint': H(o.jcns_cns_props.target_bone), 'source': H(o.jcns_cns_props.rot_source_bone),
             'rotation': tuple(o.jcns_cns_props.rot_rotation), 'scale': tuple(o.jcns_cns_props.rot_scale),
             'bytes': _rot_bytes(o.jcns_cns_props), 'floats': tuple(o.jcns_cns_props.rot_gains)}
            for o in section_empties(root_obj, 'RotExpression')]
    parser.rot_expressions, parser.rot_expression_map = X.rot_parser_form(
        rots, {'map_value': root_props.rot_map_value}, parser.version)

    # ConeDrivers are not editable; re-emitted from the import cache.
    n_cone = parser.header.get('ConeDriverCount', 0)
    if root_props.cone_drivers_json:
        parser.cone_drivers = [dict(cd, Direction=tuple(cd['Direction']), Matrix=tuple(cd['Matrix']),
                                    Tail=bytes.fromhex(cd['Tail']))
                               for cd in json.loads(root_props.cone_drivers_json)]
    elif n_cone:
        return [f"这个文件有 {n_cone} 条 ConeDriver，但当前根节点是旧版插件导入的，没有缓存它们；请重新导入后再导出。"]
    n = len(parser.cone_drivers)
    for o in get_constraint_empties(root_obj):
        bad = [k.cone_index for k in o.jcns_cns_props.cone_infos if k.cone_index >= n]
        if bad:
            return [f"约束「{o.name}」引用了第 {bad[0]} 个 ConeDriver，但文件里只有 {n} 个。"]

    # ObjectSettings are not editable; the stub gets them back from the root
    if getattr(parser, 'is_stub', False) and root_props.object_settings_json:
        parser.object_settings = [
            {'UnkBytes': bytes.fromhex(o['UnkBytes']), 'UnknownDWORD': o['UnknownDWORD'],
             'ObjectNameHash': o['ObjectNameHash']} for o in json.loads(root_props.object_settings_json)]
    return []


def _sync_non_range_to_parser(root_obj, parser):
    """
    Rebuild parser.material_cns / parser.joint_export_graph from the Material /
    JointExportGraph Empties.  Blender's copy is authoritative, so this works on the
    stub too and a deleted Empty is dropped from the export.
    """
    import struct

    hashing_dir = os.path.join(os.path.dirname(__file__), "modules", "hashing")
    if hashing_dir not in sys.path:
        sys.path.insert(0, hashing_dir)
    from mmh3.pymmh3 import hashUTF16

    def _ensure_hash(name, hash_list):
        """Index of name's hash in hash_list, appending if missing (see _name_to_hash)."""
        h = _name_to_hash(name)
        for i, v in enumerate(hash_list):
            if v == h:
                return i
        idx = len(hash_list)
        hash_list.append(h)
        return idx

    def _mat_index(obj):
        name = obj.name
        if name.startswith('[Mat') and ']' in name:
            try:
                return int(name[4:name.index(']')])
            except ValueError:
                pass
        return 9999

    mat_empties = sorted(
        (o for o in root_obj.children
         if getattr(o, 'jcns_cns_props', None)
         and o.jcns_cns_props.constraint_type == 'Material'),
        key=_mat_index)

    # In-place versions write each entry back over its original record, so carry
    # the original offset across by position.
    orig_mats = list(getattr(parser, 'material_cns', []))

    mat_entries = []
    for i, obj in enumerate(mat_empties):
        p = obj.jcns_cns_props
        bone_name = p.target_bone.strip()
        joint_idx = _ensure_hash(bone_name, parser.hash_list) if bone_name else 0

        raw = bytearray(12)
        try:
            struct.pack_into('<I', raw, 0, int(p.mat_name_hash,     16) & 0xFFFFFFFF)
        except (ValueError, TypeError):
            pass
        try:
            struct.pack_into('<I', raw, 4, int(p.mat_property_hash, 16) & 0xFFFFFFFF)
        except (ValueError, TypeError):
            pass
        raw[8]  = p.mat_transform_type_raw & 0xFF
        raw[9]  = p.mat_tail_0 & 0xFF
        raw[10] = p.mat_tail_1 & 0xFF
        raw[11] = p.mat_tail_2 & 0xFF

        entry = {
            'JointHashIndex': joint_idx,
            'JointHash':      parser.hash_list[joint_idx],
            'raw_body':       bytes(raw),
        }
        if i < len(orig_mats) and '_offset' in orig_mats[i]:
            entry['_offset'] = orig_mats[i]['_offset']
            entry['_orig_joint_hash'] = orig_mats[i]['_orig_joint_hash']
        mat_entries.append(entry)
    parser.material_cns = mat_entries

    jxg_obj = next((o for o in root_obj.children
                     if getattr(o, 'jcns_cns_props', None)
                     and o.jcns_cns_props.constraint_type == 'JointExportGraph'), None)
    orig_jxg = getattr(parser, 'joint_export_graph', None) or {}
    parser.joint_export_graph = ({'path': jxg_obj.jcns_cns_props.jxg_path,
                                  '_orig_path': orig_jxg.get('_orig_path')}
                                 if jxg_obj else None)


def format_problems_early(problems, filename):
    _ensure_modules_path()
    from jcns_validate import format_problems
    return format_problems(problems, filename)


def _name_to_hash(name):
    """MurmurHash3 of a bone name, or the value itself for a "0x%08X" placeholder."""
    import re
    if re.fullmatch(r'0x[0-9A-Fa-f]{8}', name):
        return int(name, 16)
    hashing_dir = os.path.join(os.path.dirname(__file__), "modules", "hashing")
    if hashing_dir not in sys.path:
        sys.path.insert(0, hashing_dir)
    from mmh3.pymmh3 import hashUTF16
    return hashUTF16(name) & 0xFFFFFFFF


def _root_version(rp):
    """JCNS version of a root; roots without source_version fall back to detected_game."""
    if rp.source_version:
        return rp.source_version
    return 35 if rp.detected_game == 'RE9' else 102


def _transform_int(transform_type, default=1):
    """TransformType byte of an enum identifier (the inverse of TRANSFORM_TYPE_MAP)."""
    from . import TRANSFORM_TYPE_MAP
    for value, name in TRANSFORM_TYPE_MAP.items():
        if name == transform_type:
            return value
    return default


def _make_default_constraint_dict(empty_obj):
    """
    Constraint dict for an Empty, with writer defaults for what the Empty does not
    hold; _patch_constraint_from_empty() fills in the rest.  Rebuilt versions build
    every constraint this way, so nothing is carried over from the source file.
    """
    from . import AXIS_TO_INT
    p = empty_obj.jcns_cns_props
    tgt_ax = AXIS_TO_INT.get(p.target_axis, 0)
    return {
        'ConeDriverInfoOffset':  0,
        'PropertyOffset':        0,
        'PropertyHash':          0,
        'ConeDriverInfoCount':   0,
        'ConeDriverInfo':        [],
        'Flags':                 0x30,
        'TransformType':         _transform_int(p.transform_type),
        'ReservedVec4':            (0.0, 0.0, 0.0, 1.0),
        'UnknownFloat2':          (0.0, 0.0),
        'UnknownByte72':        0,
        'TransformAxis_parent':  tgt_ax,
        'TailBytes':       b'\x00' * 6,
        'ObjectName':        '',
        'PropertyName':      '',
        'ObjectHashIndex':   0,
        'ObjectHash':        0,
        'sources':               [],
    }


def _rot_bytes(p):
    """A RotExpression record's four bytes: byte[1] is the rest-pose mode."""
    from . import ROT_REST_TO_INT
    ub = p.rot_unknown_bytes
    return (ub[0], ROT_REST_TO_INT[p.rot_rest_mode], ub[1], ub[2])


def _patch_constraint_from_empty(parsed_c, empty_obj, hash_list, sections_cached=False, version=102):
    """
    Overwrite the editable fields of a parsed constraint dict from the Empty.

    SourceHashIndex points at the source name's hash in hash_list, or keeps its old
    value when absent (the writer appends it).  The writer recomputes the hash-table
    index of a bone target from ObjectName; a direct target (see jcns_targets) is
    flagged here with ObjectHashIndex = 0xFFFFFFFF.
    """
    from . import AXIS_TO_INT, INTERPOLATION_TO_INT, flags_byte
    _ensure_modules_path()
    try:
        from hashing.mmh3.pymmh3 import hashUTF16
    except Exception:
        hashUTF16 = None
    p = empty_obj.jcns_cns_props

    new_target_name = p.target_bone.strip()
    if new_target_name:
        parsed_c['ObjectName'] = new_target_name

    # Target axis lives in ConstraintInfo[+73], not in any source block.
    parsed_c['TransformAxis_parent'] = AXIS_TO_INT.get(p.target_axis, 0)
    parsed_c['TransformType'] = _transform_int(p.transform_type,
                                               parsed_c.get('TransformType', 1))

    # Sources are rebuilt whole, so SourceCount always matches the data; opaque
    # fields are carried over from the original source at the same index.
    old_sources = parsed_c.get('sources', [])
    new_sources = []
    for i, sp in enumerate(p.sources):
        base = dict(old_sources[i]) if i < len(old_sources) else {'ComplexMappingInfoOffset': 0}
        name = sp.source_bone.strip()
        base['SourceName'] = name
        base.setdefault('SourceHashIndex', 0)
        if name and hashUTF16 is not None:
            h = hashUTF16(name) & 0xFFFFFFFF
            found = next((j for j, hv in enumerate(hash_list) if hv == h), None)
            if found is not None:
                base['SourceHashIndex'] = found   # else: writer appends the new hash
        base['source_axis']     = AXIS_TO_INT.get(sp.source_axis, 0)
        base['from_start']      = sp.from_start
        base['from_kink']       = sp.from_kink
        base['from_end']        = sp.from_end
        base['to_start']        = sp.to_start
        base['to_kink']         = sp.to_kink
        base['to_end']          = sp.to_end
        base['ref_frame_x']     = sp.ref_frame_x
        base['ref_frame_y']     = sp.ref_frame_y
        base['ref_frame_z']     = sp.ref_frame_z
        base['ref_frame_w']     = sp.ref_frame_w
        base['CurveMode']    = (sp.curve_mode_extra & ~2) | (2 if sp.three_point else 0)
        base['ReadMode']        = jcns_source_read.read_mode_value(sp.read_mode)
        base['EulerOrder']      = jcns_source_read.euler_order_value(sp.euler_order)
        base['UnknownUInt16_22']   = sp.unknown_uint16_22
        base['Interpolation'] = INTERPOLATION_TO_INT[sp.interpolation]
        base['ComplexMappingFlag'] = sp.complex_mapping_flag
        if sections_cached:
            # The F-Curve is the data; the count follows it.
            from . import jcns_cm
            base['ComplexMapping'] = jcns_cm.records(sp)
            base['ComplexMappingInfoCount'] = len(base['ComplexMapping'])
        else:
            base['ComplexMappingInfoCount'] = sp.complex_mapping_info_count
        new_sources.append(base)
    parsed_c['sources'] = new_sources


    # In DERIVED_BITS_VERSIONS (v36, v102) Flags bits 4 and 5 follow the transform
    # type and are recomputed; v35 does not follow the rule and is written as is.
    from .modules_shim import get_flags
    flags = get_flags()
    parsed_c['Flags'] = (flags.apply_derived_bits(flags_byte(p), p.transform_type)
                         if version in flags.DERIVED_BITS_VERSIONS else flags_byte(p))
    parsed_c['ReservedVec4']          = (p.reserved_vec4_x, p.reserved_vec4_y,
                                       p.reserved_vec4_z, p.reserved_vec4_w)
    parsed_c['UnknownFloat2']        = (p.unknown_float2_x, p.unknown_float2_y)
    parsed_c['UnknownByte72']      = p.unknown_byte_72
    prop = p.target_property.strip()
    parsed_c['PropertyName']        = prop
    parsed_c['PropertyHash']        = jcns_targets.property_hash(prop, p.property_hash)
    if jcns_targets.is_direct_target(parsed_c['TransformType']):
        parsed_c['ObjectHashIndex'] = 0xFFFFFFFF
        parsed_c['ObjectHash']      = jcns_targets.object_hash(parsed_c['ObjectName'], p.object_hash)
        parsed_c['ObjectHashMatchesName'] = not p.object_hash
    else:
        parsed_c['ObjectHashIndex'] = 0
    parsed_c['ConeDriverInfo'] = [{
        'Rest0': k.rest[0], 'Rest123': tuple(k.rest[1:]), 'Value': k.value,
        'UnkByte0': k.unk_byte0, 'ConeDriverIndex': k.cone_index, 'UnkByte3': k.unk_byte3}
        for k in p.cone_infos]
    parsed_c['ConeDriverInfoCount'] = len(parsed_c['ConeDriverInfo'])
    parsed_c['TailBytes']     = bytes([
        p.unknown_byte_74, p.unknown_byte_75, p.reserved_tail[0],
        p.group_count, p.reserved_tail[1], p.reserved_tail[2],
    ])


# ---------------------------------------------------------------------------
# Export Operator
# ---------------------------------------------------------------------------

class JCNS_OT_ExportFile(Operator, ExportHelper):
    """把选中的 JCNS 集合导出为 .jcns 文件，版本与导入时相同"""
    bl_idname = "jcns.export_file"
    bl_label  = "RE Engine JCNS (.jcns.*)"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ""
    filter_glob: StringProperty(
        default=_SCHEMA.FILE_GLOB,
        options={'HIDDEN'},
    )
    clean_hashes: BoolProperty(
        name="清除冗余哈希",
        description="删除已无约束引用的哈希。不勾选则保留原文件的全部哈希",
        default=False
    )

    @classmethod
    def poll(cls, context):
        obj, _ = _get_active_root(context)
        return obj is not None

    def invoke(self, context, event):
        _, rp = _get_active_root(context)
        if rp:
            self.filename_ext = f".jcns.{_root_version(rp)}"

            if rp.source_filepath:
                path = bpy.path.abspath(rp.source_filepath)
                if rp.upgraded_from and path.endswith(f".jcns.{rp.upgraded_from}"):
                    path = path[:-len(f".{rp.upgraded_from}")] + f".{_root_version(rp)}"
                self.filepath = path
        
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def check(self, context):
        change_ext = False
        filepath = self.filepath
        if filepath != "":
            ext = self.filename_ext
            if not filepath.lower().endswith(ext.lower()):
                if filepath.lower().endswith(".jcns"):
                    self.filepath = filepath + ext.replace(".jcns", "")
                else:
                    self.filepath = filepath + ext
                change_ext = True
        return change_ext

    def execute(self, context):
        from . import get_constraint_empties, entries_of

        root_obj, root_props = _get_active_root(context)
        if root_obj is None:
            self.report({'ERROR'}, "未检测到 JCNS 根节点，请先选中 JCNS 集合的根空物体。")
            return {'CANCELLED'}

        source_path = bpy.path.abspath(root_props.source_filepath)
        # An upgraded file is exported from Blender's data: its source is an older version.
        upgraded = bool(root_props.upgraded_from)
        source_exists = os.path.isfile(source_path) and not upgraded

        empties = get_constraint_empties(root_obj)
        # Files made only of Skin / Aim / RotExpression / Material entries have no Ranges.
        if not empties and not entries_of(root_obj):
            self.report({'WARNING'}, "没有找到任何条目，无内容可导出。")
            return {'CANCELLED'}

        _ensure_modules_path()
        if source_exists:
            try:
                from jcns_parser import JCNSParser
                parser = JCNSParser(source_path)
                parser.parse()
            except Exception as exc:
                self.report({'ERROR'}, f"重新解析源文件失败：{exc}")
                return {'CANCELLED'}
        else:
            if not root_props.source_version:
                self.report({'ERROR'}, f"源文件不存在：{source_path}\n这个根节点是旧版插件导入的，请重新导入该文件。")
                return {'CANCELLED'}
            if not upgraded:
                self.report({'WARNING'}, "源文件缺失，按 Blender 里的数据重建文件头导出。")
            parser = _build_stub_parser(root_props)

        if parser.write_mode == 'rebuild' and not root_props.sections_cached:
            self.report({'ERROR'}, "这个文件是旧版插件导入的，Blender 里没有重建所需的数据；请重新导入后再导出。")
            return {'CANCELLED'}

        problems = _sync_sections_to_parser(root_obj, root_props, parser)
        if problems:
            msg = format_problems_early(problems, os.path.basename(source_path))
            print("[JCNS EXPORT] " + msg)
            self.report({'ERROR'}, msg.replace('\n', '  '))
            return {'CANCELLED'}

        from jcns_validate import check_exportable, check_in_place_edits, format_problems
        problems = check_exportable(parser)
        if problems:
            msg = format_problems(problems, os.path.basename(source_path))
            print("[JCNS EXPORT] " + msg)
            self.report({'ERROR'}, msg.replace('\n', '  '))
            return {'CANCELLED'}

        from . import jcns_merge_ops
        shared = jcns_merge_ops.shared_channel_warning(empties, root_props)
        if shared:
            print("[JCNS EXPORT] " + shared)
            self.report({'WARNING'}, shared)

        final_constraints = []
        for i, empty in enumerate(empties):
            if parser.write_mode == 'rebuild':
                parsed_c = _make_default_constraint_dict(empty)
            else:
                # In place, each entry rides on the record at its position.
                parsed_c = (parser.constraints[i] if i < len(parser.constraints)
                            else _make_default_constraint_dict(empty))
            _patch_constraint_from_empty(parsed_c, empty, parser.hash_list,
                                         root_props.sections_cached, parser.version)
            final_constraints.append(parsed_c)

        parser.constraints = final_constraints

        _sync_non_range_to_parser(root_obj, parser)

        # In-place versions change values only; report every structural edit at once.
        if parser.write_mode == 'inplace':
            problems = check_in_place_edits(parser)
            if problems:
                msg = format_problems(problems, os.path.basename(source_path))
                print("[JCNS EXPORT] " + msg)
                self.report({'ERROR'}, msg.replace('\n', '  '))
                return {'CANCELLED'}

        md5_before = None
        if source_exists:
            with open(source_path, 'rb') as f:
                md5_before = hashlib.md5(f.read()).hexdigest()

        out_path = self.filepath
        try:
            from jcns_writer import JCNSWriter
            writer = JCNSWriter(parser, out_path)
            writer.build_lossless(clean_hashes=self.clean_hashes)
        except Exception as exc:
            self.report({'ERROR'}, f"写入失败：{exc}")
            return {'CANCELLED'}

        with open(out_path, 'rb') as f:
            md5_after = hashlib.md5(f.read()).hexdigest()

        if out_path != source_path:
            root_props.source_filepath = out_path

        basename = os.path.basename(out_path)
        if upgraded:
            self.report({'INFO'}, f"已导出「{basename}」（v{root_props.upgraded_from} → v{parser.version}）。")
        elif md5_before is None:
            self.report({'INFO'}, f"已导出「{basename}」（源文件缺失，无法比对 MD5）。")
        elif md5_before == md5_after:
            self.report({'INFO'}, f"已导出「{basename}」—— 内容无变化（MD5 相同）。")
        else:
            self.report(
                {'INFO'},
                f"已导出「{basename}」（MD5 {md5_before[:8]}… → {md5_after[:8]}…）"
            )
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Menu hook
# ---------------------------------------------------------------------------

def _menu_export(self, context):
    obj, _ = _get_active_root(context)
    if obj is not None:
        self.layout.operator(JCNS_OT_ExportFile.bl_idname, text="RE Engine JCNS (.jcns.*)")


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

_classes = [JCNS_OT_ExportFile]


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_file_export.append(_menu_export)


def unregister():
    bpy.types.TOPBAR_MT_file_export.remove(_menu_export)
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
