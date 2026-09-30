"""
jcns_exporter.py
----------------
Export operator for RE Engine JCNS files (v102 and v35 rebuilt, other versions in place).

Strategy:
  1. Detect the JCNS root Empty from the active object.
  2. Re-parse the original source file (structural skeleton, hash list, etc.).
  3. Gather constraint Empties from the collection, sorted by index prefix.
  4. For each constraint, patch the parsed dict with current Blender values.
  5. Call JCNSWriter.build_lossless() to write the output.
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


def _build_stub_parser(root_props, empties):
    """
    Reconstruct a minimal parser-like object from cached data when the source
    file is unavailable.  All constraints are treated as 'new' (n_orig = 0).
    """
    import base64, struct

    _ensure_modules_path()
    hashing_dir = os.path.join(os.path.dirname(__file__), "modules", "hashing")
    if hashing_dir not in sys.path:
        sys.path.insert(0, hashing_dir)
    from mmh3.pymmh3 import hashUTF16

    # Rebuild hash_list from all bone names referenced by current empties
    hash_list = []
    def _add_name(name):
        if not name:
            return
        h = hashUTF16(name) & 0xFFFFFFFF
        if h not in hash_list:
            hash_list.append(h)

    for empty in empties:
        p = empty.jcns_cns_props
        _add_name(p.target_bone)
        for s in p.sources:
            _add_name(s.source_bone)

    # Reconstruct original_bytes stub: header block + section table at its offset.
    # The cached header is the Tags block plus the whole DataInfo table, so the
    # real header reader works on it; check_exportable() then still sees e.g.
    # SkinConstraintCount / AimConstraintCount without the source file.
    from jcns_parser import read_header, write_mode
    tags = base64.b64decode(root_props.cached_file_header)
    sec_data = base64.b64decode(root_props.cached_section_table)
    try:
        header = read_header(tags)
    except (ValueError, struct.error):
        header = {}   # cached header from an older add-on version — counts unknown
    orig_sec_off = header.get('SectionTableEntry', 0)
    head_len = max(len(tags), header.get('HeaderEnd', 0))
    stub_size = max(head_len, orig_sec_off + len(sec_data)) if orig_sec_off > 0 else head_len
    stub = bytearray(stub_size)
    stub[:len(tags)] = tags
    if orig_sec_off > 0:
        stub[orig_sec_off : orig_sec_off + len(sec_data)] = sec_data

    class _StubParser:
        pass

    parser = _StubParser()
    parser.constraints = []       # n_orig = 0, all constraints built from empties
    parser.hash_list = hash_list
    parser.original_bytes = bytes(stub)
    parser.filepath = root_props.source_filepath
    parser.header = header
    parser.version = header.get('Version', 102)
    parser.write_mode = write_mode(parser.version)
    parser.is_stub = True
    # Non-Range sections are not cached — they will be absent from stub exports
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


def _sync_sections_to_parser(root_obj, root_props, parser):
    """
    Rebuild parser.skin_* / aim_constraints / rot_expressions (and, for the
    cached-header stub, object_settings) from the section Empties.  Returns a list
    of refusals; empty == OK.

    Only for roots whose importer cached the section data (sections_cached) and
    only in rebuild mode: in-place versions never re-emit these sections, and the
    Empties of an older import hold no data.
    """
    import json
    from . import section_empties, get_constraint_empties
    _ensure_modules_path()
    import jcns_sections as X

    if not root_props.sections_cached or getattr(parser, 'write_mode', 'rebuild') != 'rebuild':
        return []

    def H(name):
        return _name_to_hash(name.strip())

    # SkinConstraint
    def _tail(hexstr):
        try:
            raw = bytes.fromhex(hexstr.strip())
        except ValueError:
            return None
        return raw[:2].ljust(2, bytes(1)) if raw else None

    records = [{'object': H(o.jcns_cns_props.target_bone),
                'tail': _tail(o.jcns_cns_props.skin_tail_hex),
                'sources': [{'hash': H(w.bone), 'weight': w.weight} for w in o.jcns_cns_props.skin_sources]}
               for o in section_empties(root_obj, 'Skin')]
    table = bytes.fromhex(root_props.read_joint_table_hex or '')
    meta = {'constant': root_props.skin_constant, 'tail': X.skin_default_tail(records),
            'read_joint_table': [int.from_bytes(table[i:i + 4], 'little') for i in range(0, len(table), 4)]}
    locked = json.loads(root_props.read_joint_signature_json) if root_props.read_joint_signature_json else []
    # The table also covers the Aim joints, so it is resolved against both.
    aim_joints = [H(o.jcns_cns_props.target_bone) for o in section_empties(root_obj, 'Aim')]
    arm = root_props.target_armature
    parent = names = None
    if arm is not None and arm.type == 'ARMATURE':
        parent = {H(b.name): (H(b.parent.name) if b.parent else None) for b in arm.data.bones}
        names = {H(b.name): b.name for b in arm.data.bones}
    table, problems = X.resolve_read_joint_table(records, aim_joints, meta, locked, parent, names)
    if problems:
        return problems
    for w in X.skin_weight_warnings(records):
        print('[JCNS EXPORT] warning: ' + w)
    parser.skin_constraints, parser.skin_source_infos = X.skin_parser_form(records, meta)
    if table != meta['read_joint_table']:
        print('[JCNS EXPORT] ReadJointTable re-derived from the armature: %d -> %d joint(s)'
              % (len(meta['read_joint_table']), len(table)))
    parser.read_joint_table = table

    # Aim
    aims = []
    for o in section_empties(root_obj, 'Aim'):
        p = o.jcns_cns_props
        aims.append({
            'joint': H(p.target_bone), 'target': H(p.aim_target_bone),
            'up': H(p.aim_up_bone) if p.aim_up_bone.strip() else None,
            'influence': p.aim_influence,
            'vectors': [tuple(p.aim_vec0), tuple(p.aim_vec1), tuple(p.aim_vec2), tuple(p.aim_vec3)],
            'rotation_type': p.aim_rotation_type, 'bytes': tuple(p.aim_bytes),
            'tail': bytes.fromhex(p.aim_tail_hex or '00' * 12).ljust(12, b'\0')[:12],
            'target_tail': bytes.fromhex(p.aim_target_tail_hex or '00' * 8).ljust(8, b'\0')[:8],
        })
    parser.aim_constraints = X.aim_parser_form(aims)

    # RotExpression
    rots = [{'joint': H(o.jcns_cns_props.target_bone), 'source': H(o.jcns_cns_props.rot_source_bone),
             'rotation': tuple(o.jcns_cns_props.rot_rotation), 'scale': tuple(o.jcns_cns_props.rot_scale),
             'bytes': tuple(o.jcns_cns_props.rot_bytes), 'floats': tuple(o.jcns_cns_props.rot_floats)}
            for o in section_empties(root_obj, 'RotExpression')]
    try:
        parser.rot_expressions, parser.rot_expression_map = X.rot_parser_form(
            rots, {'map': list(bytes.fromhex(root_props.rot_map_hex or ''))}, parser.version)
    except ValueError as exc:
        return [str(exc)]

    # ConeDrivers: not editable yet, re-emitted from the import cache
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

    # ObjectSettings are not editable; the stub gets them back from the cache
    if getattr(parser, 'is_stub', False) and root_props.object_settings_json:
        parser.object_settings = [
            {'UnkBytes': bytes.fromhex(o['UnkBytes']), 'UnknownDWORD': o['UnknownDWORD'],
             'ObjectNameHash': o['ObjectNameHash']} for o in json.loads(root_props.object_settings_json)]
    parser.sections_from_blender = True
    return []


def _sync_non_range_to_parser(root_obj, parser):
    """
    Rebuild parser.material_cns / parser.joint_export_graph entirely from the
    cached properties on the Material / JointExportGraph child Empties.

    Blender's copy is authoritative: unlike RotExpression/Aim (which have no
    editable backing store and can only be reproduced by re-parsing the source
    file), every field the writer needs for Material and JXG already round-trips
    through jcns_cns_props. Rebuilding from scratch — rather than patching a
    pre-existing parser.material_cns entry by index — means this also works when
    exporting from the cached-header stub (no source file), and means deleting a
    Material/JXG Empty in Blender removes it from the export too.
    """
    import struct

    hashing_dir = os.path.join(os.path.dirname(__file__), "modules", "hashing")
    if hashing_dir not in sys.path:
        sys.path.insert(0, hashing_dir)
    from mmh3.pymmh3 import hashUTF16

    def _ensure_hash(name, hash_list):
        """Return index of name's MurmurHash3 in hash_list, appending if missing.

        A bone the importer could not resolve is shown as its raw hash
        ("0x1234ABCD"); that string is the hash itself, not a name to hash.
        """
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
    """JCNS version of a root, falling back to the pre-0.15 detected_game enum."""
    if rp.source_version:
        return rp.source_version
    return 35 if rp.detected_game == 'RE9' else 102


_TRANSFORM_STR_TO_INT = {
    'Translation': 0, 'Rotation': 1, 'Scale': 2, 'BlendShape': 3,
    'Material': 7, 'Unknown': 4,
}


def _make_default_constraint_dict(empty_obj):
    """
    Build a minimal constraint dict for a newly-added constraint Empty
    (one that has no corresponding entry in the original parsed file).
    All preserved/unknown fields are set to safe defaults that match what
    the writer expects; the editable fields will be overwritten immediately
    afterwards by _patch_constraint_from_empty().
    """
    from . import AXIS_TO_INT
    p = empty_obj.jcns_cns_props
    tgt_ax = AXIS_TO_INT.get(p.target_axis, 0)
    return {
        # ConstraintInfo preserved fields
        'ConeDriverInfoOffset':  0,
        'PropertyOffset':        0,
        'PropertyHash':          0,
        'ConeDriverInfoCount':   0,
        'ConeDriverInfo':        [],
        'Flags':                 0x30,
        'TransformType':         _TRANSFORM_STR_TO_INT.get(p.transform_type, 1),
        'ParentVec4':            (0.0, 0.0, 0.0, 1.0),
        'ParentFloat2':          (0.0, 0.0),
        'ParentUInt8_72':        0,
        'TransformAxis_parent':  tgt_ax,
        'ParentTailBytes':       b'\x00' * 6,
        'ObjectName':        '',
        # Sources are built entirely by _patch_constraint_from_empty()
        'sources':               [],
    }


def _patch_constraint_from_empty(parsed_c, empty_obj, hash_list, sections_cached=False, version=102):
    """
    Overwrite the editable fields in the parsed constraint dict with
    values from the Empty's JCNSConstraintProperties.

    Source bone: if changed, hash_list is searched for the MurmurHash3 value
    and SourceHashIndex is updated (or the hash is appended by the writer).

    Target bone: if changed, ObjectName is updated; the writer recomputes
    TargetHash and ObjectHashIndex from the name automatically.
    """
    from . import AXIS_TO_INT
    _ensure_modules_path()
    try:
        from hashing.mmh3.pymmh3 import hashUTF16
    except Exception:
        hashUTF16 = None
    p = empty_obj.jcns_cns_props

    # --- Target bone name (writer recomputes TargetHash/ObjectHashIndex from it) ---
    new_target_name = p.target_bone.strip()
    if new_target_name:
        parsed_c['ObjectName'] = new_target_name

    # --- Target axis lives in ConstraintInfo[+73], not in any source block ---
    parsed_c['TransformAxis_parent'] = AXIS_TO_INT.get(p.target_axis, 0)

    # --- Sources: rebuild the whole list from the UI collection ---
    # Rebuilding rather than patching in place means added/removed sources are
    # handled for free, and SourceCount can never disagree with the actual data.
    old_sources = parsed_c.get('sources', [])
    new_sources = []
    for i, sp in enumerate(p.sources):
        # Carry over opaque fields from the matching original source when there is one
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
        base['rest_quat_x']     = sp.rest_quat_x
        base['rest_quat_y']     = sp.rest_quat_y
        base['rest_quat_z']     = sp.rest_quat_z
        base['rest_quat_w']     = sp.rest_quat_w
        base['CurveMode']    = sp.update_timing
        base['ReadMode']        = jcns_source_read.read_mode_value(sp.read_mode)
        base['UnkByte2']        = sp.unk_byte2
        base['UnknownUInt16']   = sp.unknown_uint16
        base['UnknownUInt32_2'] = sp.unknown_uint32_2
        if sections_cached:
            # The F-Curve is the data; the count follows it.
            from . import jcns_cm
            base['ComplexMapping'] = jcns_cm.records(sp)
            base['ComplexMappingInfoCount'] = len(base['ComplexMapping'])
        else:
            base['ComplexMappingInfoCount'] = sp.complex_mapping_info_count
        new_sources.append(base)
    parsed_c['sources'] = new_sources


    # --- ConstraintInfo raw fields ---
    # Bits 4 and 5 are redundant with the transform type in v36 / v102 (every
    # shipped constraint), so there they are recomputed rather than trusted —
    # otherwise changing a constraint's transform type would silently leave the
    # flags describing the old one.  RE9's v35 does not follow the rule, so its
    # flags are written as they are.
    from .modules_shim import get_flags
    flags = get_flags()
    parsed_c['Flags'] = (flags.apply_derived_bits(p.cns_flags, p.transform_type)
                         if version in flags.DERIVED_BITS_VERSIONS else int(p.cns_flags) & 0xFF)
    parsed_c['ParentVec4']          = (p.parent_vec4_x, p.parent_vec4_y,
                                       p.parent_vec4_z, p.parent_vec4_w)
    parsed_c['ParentFloat2']        = (p.parent_float2_x, p.parent_float2_y)
    parsed_c['ParentUInt8_72']      = p.parent_uint8_72
    parsed_c['PropertyHash']        = p.property_hash & 0xFFFFFFFF
    parsed_c['ConeDriverInfo'] = [{
        'Rest0': k.rest[0], 'Rest123': tuple(k.rest[1:]), 'Value': k.value,
        'UnkByte0': k.unk_byte0, 'ConeDriverIndex': k.cone_index, 'UnkByte3': k.unk_byte3}
        for k in p.cone_infos]
    parsed_c['ConeDriverInfoCount'] = len(parsed_c['ConeDriverInfo'])
    parsed_c['ParentTailBytes']     = bytes([
        p.parent_tail_0, p.parent_tail_1, p.parent_tail_2,
        p.parent_tail_3, p.parent_tail_4, p.parent_tail_5,
    ])


# ---------------------------------------------------------------------------
# Export Operator
# ---------------------------------------------------------------------------

class JCNS_OT_ExportFile(Operator, ExportHelper):
    """Export the selected JCNS collection back to a .jcns.102 binary file"""
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
            # Auto-append the source file's own version suffix
            self.filename_ext = f".jcns.{_root_version(rp)}"

            if rp.source_filepath:
                self.filepath = bpy.path.abspath(rp.source_filepath)
        
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
        from . import get_constraint_empties

        root_obj, root_props = _get_active_root(context)
        if root_obj is None:
            self.report({'ERROR'}, "未检测到 JCNS 根节点，请先选中 JCNS 集合的根空物体。")
            return {'CANCELLED'}

        source_path = bpy.path.abspath(root_props.source_filepath)
        source_exists = os.path.isfile(source_path)

        empties = get_constraint_empties(root_obj)
        if not empties:
            self.report({'WARNING'}, "没有找到任何约束，无内容可导出。")
            return {'CANCELLED'}

        # --- Build parser: re-parse source if present, else use cached stub ---
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
            if not root_props.cached_file_header:
                self.report(
                    {'ERROR'},
                    f"源文件不存在，也没有缓存的文件头：{source_path}\n"
                    "请重新导入该文件以重建缓存。"
                )
                return {'CANCELLED'}
            self.report({'WARNING'}, "源文件缺失，将使用导入时缓存的文件头导出。")
            parser = _build_stub_parser(root_props, empties)

        # --- Skin / Aim / RotExpression from Blender (rebuild mode only) ---
        problems = _sync_sections_to_parser(root_obj, root_props, parser)
        if problems:
            msg = format_problems_early(problems, os.path.basename(source_path))
            print("[JCNS EXPORT] " + msg)
            self.report({'ERROR'}, msg.replace('\n', '  '))
            return {'CANCELLED'}

        # --- Refuse to write a file the writer cannot faithfully reproduce ---
        from jcns_validate import check_exportable, check_in_place_edits, format_problems
        problems = check_exportable(parser)
        if problems:
            msg = format_problems(problems, os.path.basename(source_path))
            print("[JCNS EXPORT] " + msg)
            self.report({'ERROR'}, msg.replace('\n', '  '))
            return {'CANCELLED'}

        n_orig = len(parser.constraints)
        n_curr = len(empties)

        # --- Build the final constraint list (one entry per Empty) ---
        final_constraints = []
        for i, empty in enumerate(empties):
            if i < n_orig:
                parsed_c = parser.constraints[i]
            else:
                parsed_c = _make_default_constraint_dict(empty)
                print(f"[JCNS EXPORT] New constraint [{i:02d}] '{empty.name}' — using defaults")
            _patch_constraint_from_empty(parsed_c, empty, parser.hash_list,
                                         root_props.sections_cached, parser.version)
            final_constraints.append(parsed_c)

        parser.constraints = final_constraints

        # Sync editable JXG / Material empty values back into parser
        _sync_non_range_to_parser(root_obj, parser)

        # In-place versions: values only — refuse structural edits up front, with
        # the full list, instead of as a one-line write failure.
        if parser.write_mode == 'inplace':
            problems = check_in_place_edits(parser)
            if problems:
                msg = format_problems(problems, os.path.basename(source_path))
                print("[JCNS EXPORT] " + msg)
                self.report({'ERROR'}, msg.replace('\n', '  '))
                return {'CANCELLED'}

        # --- MD5 before write (only if source file exists) ---
        md5_before = None
        if source_exists:
            with open(source_path, 'rb') as f:
                md5_before = hashlib.md5(f.read()).hexdigest()

        # --- Write ---
        out_path = self.filepath
        try:
            from jcns_writer import JCNSWriter
            writer = JCNSWriter(parser, out_path)
            writer.build_lossless(clean_hashes=self.clean_hashes)
        except Exception as exc:
            self.report({'ERROR'}, f"写入失败：{exc}")
            return {'CANCELLED'}

        # --- MD5 after write ---
        with open(out_path, 'rb') as f:
            md5_after = hashlib.md5(f.read()).hexdigest()

        if out_path != source_path:
            root_props.source_filepath = out_path

        basename = os.path.basename(out_path)
        if md5_before is None:
            self.report({'INFO'}, f"已导出「{basename}」（基于缓存文件头，无法比对 MD5）。")
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
