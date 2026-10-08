"""
jcns_exporter.py
----------------
Export operator for RE Engine JCNS files (v22, v35, v36 and v102 rebuilt, other versions in place).

The source file is re-parsed (or a stub is built from what the import stored in the
root when it is missing), and JCNSWriter.build_lossless() writes the result.  Rebuilt
versions make every constraint from its Empty; in-place versions patch the record at
the Empty's position.
"""

import json
import os
import sys
import hashlib
import bpy
from bpy.props import StringProperty, BoolProperty, EnumProperty
from bpy.types import Operator
from bpy_extras.io_utils import ExportHelper

from .modules_shim import get_schema, ensure_path, T

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


def _build_stub_parser(root_props, version=None):
    """
    A parser-like object for a file whose source is gone: the generated file header, and
    the section order and hash list the import stored.  Everything else comes from the
    Empties, so all constraints are new.  `version` overrides the root's for a
    cross-version export (see CONVERTIBLE_VERSIONS).
    """
    from jcns_parser import read_header, write_mode
    from jcns_schema import file_header

    version = version or _root_version(root_props)
    orig = file_header(version, tuple(root_props.header_unknown_bytes))

    class _StubParser:
        pass

    parser = _StubParser()
    parser.constraints = []
    parser.hash_list = [h.hash & 0xFFFFFFFF for h in root_props.hash_list]
    parser.section_order = [0, 1, 2, 3, 4] if version == 22 else [s.value for s in root_props.section_order]
    parser.original_bytes = orig
    parser.filepath = root_props.source_filepath
    parser.header = read_header(orig, check_layout=False)
    parser.version = version
    parser.write_mode = 'rebuild' if version != _root_version(root_props) else root_write_mode(root_props)
    parser.is_stub = True
    parser.aim_constraints    = []
    parser.object_settings    = []
    parser.multi_constraints   = []
    parser.multi_source_infos  = []
    parser.read_joint_table    = []
    parser.cone_inputs       = []
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
    Rebuild parser.multi_* / aim_constraints / rot_expressions / cone_inputs (and,
    for the stub, object_settings) from Blender.  Returns refusals; empty == OK.

    Runs only for sections_cached roots in rebuild mode: in-place versions never
    re-emit these sections.
    """
    import json
    from . import section_empties, get_constraint_empties, WORLD_UP_TYPE_TO_INT
    _ensure_modules_path()
    import jcns_sections as X

    if not root_props.sections_cached or getattr(parser, 'write_mode', 'rebuild') != 'rebuild':
        return []

    def H(name):
        return _name_to_hash(name.strip())

    parser.conversion_notes = {}
    if parser.version < 35:
        # RE4 files carry none of these sections; a converted copy loses them.
        parser.conversion_notes.update({
            'multi': len(section_empties(root_obj, 'Multi')), 'aim': len(section_empties(root_obj, 'Aim')),
            'rot': len(section_empties(root_obj, 'RotExpression'))})
        parser.multi_constraints, parser.multi_source_infos, parser.read_joint_table = [], [], []
        parser.aim_constraints, parser.rot_expressions, parser.rot_expression_map = [], [], b''
        return _sync_cone_inputs(root_obj, root_props, parser, converted_from=getattr(parser, 'converted_from', 0))

    records = [{'object': H(o.jcns_cns_props.target_bone),
                'tail': bytes(o.jcns_cns_props.multi_tail),
                'sources': [{'hash': H(w.bone), 'weight': w.weight} for w in o.jcns_cns_props.multi_sources]}
               for o in section_empties(root_obj, 'Multi')]
    converted_from = getattr(parser, 'converted_from', 0)
    constant = root_props.file_constant
    if converted_from:
        constant = convert_file_constant(constant, converted_from, parser.version)
    meta = {'constant': constant,
            'read_joint_table': [it.hash & 0xFFFFFFFF for it in root_props.read_joint_table]}
    locked = json.loads(root_props.read_joint_signature_json) if root_props.read_joint_signature_json else []
    # The table also covers the Aim joints, so it is resolved against both.
    aim_joints = [H(o.jcns_cns_props.target_bone) for o in section_empties(root_obj, 'Aim')]
    parent, names = skeleton_of(root_props.target_armature)
    if converted_from and parser.version in (35, 36):
        table = []                       # v35 has no ReadJointTable, v36 ships it empty
    else:
        # A v102 copy of a v35 / v36 file derives the table it never had.
        pending = root_props.read_table_pending or converted_from in (35, 36)
        table, problems = X.resolve_read_joint_table(records, aim_joints, meta, locked, parent, names,
                                                     pending=pending)
        if problems:
            return problems
    parser.replaced_multi_tails = 0
    if converted_from:
        for r in records:
            tail = convert_multi_tail(r['tail'], parser.version, converted_from)
            parser.replaced_multi_tails += tail != bytes(r['tail'])
            r['tail'] = tail
    for w in X.multi_weight_warnings(records):
        print('[JCNS EXPORT] warning: ' + w)
    parser.multi_constraints, parser.multi_source_infos = X.multi_parser_form(records, meta)
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
            'target2': H(p.aim_target2_bone) if p.aim_target2_bone.strip() else None,
            'weight2': p.aim_weight2,
            'vectors': [tuple(p.aim_offset), tuple(p.aim_axis), tuple(p.aim_up_axis), tuple(p.aim_up_dir)],
            'world_up_type': WORLD_UP_TYPE_TO_INT[p.world_up_type], 'bytes': (0,) + tuple(p.aim_bytes),
        })
        if converted_from and aims[-1]['bytes'][2] == root_props.file_constant:
            aims[-1]['bytes'] = aims[-1]['bytes'][:2] + (constant,)
    parser.aim_constraints = X.aim_parser_form(aims)

    rots = [{'joint': H(o.jcns_cns_props.target_bone), 'source': H(o.jcns_cns_props.rot_source_bone),
             'rotation': tuple(o.jcns_cns_props.rot_rotation), 'scale': tuple(o.jcns_cns_props.rot_scale),
             'bytes': _rot_bytes(o.jcns_cns_props), 'floats': tuple(o.jcns_cns_props.rot_gains)}
            for o in section_empties(root_obj, 'RotExpression')]
    parser.rot_expressions, parser.rot_expression_map = X.rot_parser_form(
        rots, {'map_value': root_props.rot_map_value}, parser.version)
    return _sync_cone_inputs(root_obj, root_props, parser, converted_from)


def _sync_cone_inputs(root_obj, root_props, parser, converted_from):
    """The ConeInput table as edited on the root, converted when the file changes version, and
    (for the stub) the ObjectSettings.  Returns refusals; empty == OK."""
    import json
    from . import get_constraint_empties
    _ensure_modules_path()
    import jcns_sections as X

    # Bone names may be "0x%08X" hashes.
    parser.cone_inputs = []
    for i, ci in enumerate(root_props.cone_inputs):
        if not ci.joint.strip() or not ci.parent_joint.strip():
            return [T("io.export.cone_no_joint", i, ci.name)]
        sym = ci.symmetry_joint.strip()
        parser.cone_inputs.append({
            'Name': ci.name, 'Direction': tuple(ci.direction), 'Matrix': tuple(ci.matrix),
            'Translation': tuple(ci.translation), 'AngleRad': ci.angle,
            'UnknownUInt32': ci.unknown_uint32, 'Tail': bytes(ci.tail),
            'JointName': ci.joint.strip(), 'ParentJointName': ci.parent_joint.strip(),
            'JointHash': _name_to_hash(ci.joint.strip()), 'ParentJointHash': _name_to_hash(ci.parent_joint.strip()),
            'SymmetryJointHash': _name_to_hash(sym) if sym else None})
    n = len(parser.cone_inputs)
    for o in get_constraint_empties(root_obj):
        # index 255 is a reference to no cone (v22 files carry it)
        cds = o.jcns_cns_props.cone_drivers
        bad = [k.cone_input_index for k in cds if n <= k.cone_input_index != 255]
        if bad:
            return [T("io.export.cone_bad_index", o.name, bad[0], n)]
        if any(_hex_bytes(k.curve_data_hex, 12) is None for k in cds):
            return [T("io.export.cone_bad_curve_data", o.name)]

    parser.cone_index_map = None
    if converted_from and (converted_from < 35) != (parser.version < 35):
        parser.cone_inputs, parser.cone_index_map, lost = X.convert_cone_inputs(
            parser.cone_inputs, converted_from, parser.version)
        parser.conversion_notes['cone'] = n - len(parser.cone_inputs)
        parser.conversion_notes['symmetry'] = lost

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
    from . import MAT_APPLY_MODE_TO_INT

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
        raw[8]  = MAT_APPLY_MODE_TO_INT[p.mat_apply_mode]
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

    path = root_obj.jcns_root_props.jxg_path.strip()
    orig_jxg = getattr(parser, 'joint_export_graph', None) or {}
    parser.joint_export_graph = ({'path': path, '_orig_path': orig_jxg.get('_orig_path')}
                                 if path else None)
    if parser.version < 35 and getattr(parser, 'write_mode', 'rebuild') == 'rebuild':
        notes = getattr(parser, 'conversion_notes', {})
        notes['material'], notes['jxg'] = len(parser.material_cns), int(parser.joint_export_graph is not None)
        parser.material_cns, parser.joint_export_graph = [], None


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


def root_write_mode(rp):
    """'rebuild' or 'inplace' for a root: its version's mode, unless the file itself blocks the rebuild."""
    _ensure_modules_path()
    from jcns_parser import write_mode
    return 'inplace' if rp.rebuild_blocked else write_mode(_root_version(rp))


def _root_version(rp):
    """JCNS version of a root; roots without source_version fall back to detected_game."""
    if rp.source_version:
        return rp.source_version
    return {'RE9': 35, 'ONIMUSHA': 36, 'RE4': 22}.get(rp.detected_game, 102)


# Versions an export can turn into each other: same layout but for the header
# (ReadJointTable from v36, HeaderUnknownUInt16 before v102) and these values, read off
# the corpora (RE9 v35, Onimusha v36, Wilds v102):
#   AttrFlags bit 5 (OutRot)  v35 never sets it; v36 / v102 set it on rotation targets
#                             (their export derives bits 4/5 anyway).
#   TailBytes[1]              v35 always 0; v36 / v102 mostly 2, and the Wilds evaluator skips
#                             an entry whose byte is below the object's level, so 0 -> 2.
#   Multi tail                v102 always 0000; v36 0001 (0101 twice); v35 0101 / 0201 /
#                             0100 / 0200.  Meaning unknown: the commonest maps to the
#                             commonest, and a tail the target never ships becomes its
#                             commonest, with a warning.
#   File constant             Multi tail[0], Multi source info and Aim +59: 0xFF in v35 /
#                             v36, 5 in v102 (0 and 11 too, which are kept).
#   ReadJointTable            v35 has none and v36 ships it empty; a v102 copy derives it.
# v22 (RE4) differs more: no hash table, no Multi / Aim / RotExpression / Material / JXG (a
# conversion drops them and says so), AttrFlags bits 4 / 5 never set, and its ConeInputs name
# their axes instead of carrying a Matrix (see jcns_sections.convert_cone_inputs).
CONVERTIBLE_VERSIONS = (22, 35, 36, 102)
# The highest TransformElement a v22 file ships (0 position .. 4 scale-like); the later ones are
# materials, component properties and named outputs.
MAX_TRANSFORM_ELEMENT_PRE35 = 4
_MULTI_TAILS = {35: (b'\x01\x01', {b'\x01\x01', b'\x02\x01', b'\x01\x00', b'\x02\x00'}),
                36: (b'\x00\x01', {b'\x00\x01', b'\x01\x01'}),
                102: (b'\x00\x00', {b'\x00\x00'})}


def convert_multi_tail(tail, version, from_version=None):
    """The source's commonest tail becomes the target's; another tail the target ships is kept."""
    common, shipped = _MULTI_TAILS[version]
    tail = bytes(tail)
    if from_version in _MULTI_TAILS and tail == _MULTI_TAILS[from_version][0]:
        return common
    return tail if tail in shipped else common


def convert_file_constant(constant, from_version, version):
    """The source version's usual constant becomes the target's; any other value is kept."""
    import jcns_sections as X
    if constant == X.file_constant_default(from_version):
        return X.file_constant_default(version)
    return constant


def convert_constraint(c, version, cone_index_map=None):
    """Outputs record values that differ between versions, for `version`.  With a `cone_index_map`
    (see jcns_sections.convert_cone_inputs) the ConeDriver list follows the converted cone table;
    returns how many ConeDriver entries went."""
    tail = bytearray(c.get('TailBytes') or bytes(6))
    if version < 35:
        c['AttrFlags'] = c['AttrFlags'] & ~0x30
        tail[1] = 0
    elif version == 35:
        c['AttrFlags'] = c['AttrFlags'] & ~0x20
        tail[1] = 0
    elif tail[1] == 0:
        tail[1] = 2
    c['TailBytes'] = bytes(tail)
    if cone_index_map is None:
        return 0
    import jcns_sections as X
    c['ConeDriver'], dropped = X.convert_cone_drivers(c.get('ConeDriver') or [], cone_index_map, version)
    c['ConeDriverCount'] = len(c['ConeDriver'])
    return dropped


def _conversion_losses(notes):
    """What a conversion dropped or could not carry, as one line ('' when nothing)."""
    keys = (('multi', "io.export.lost.multi"), ('aim', "io.export.lost.aim"), ('rot', "io.export.lost.rot"),
            ('material', "io.export.lost.material"), ('jxg', "io.export.lost.jxg"),
            ('cone', "io.export.lost.cone"), ('cone_driver', "io.export.lost.cone_driver"),
            ('symmetry', "io.export.lost.symmetry"), ('empty', "io.export.lost.empty"))
    return T("io.export.lost.sep").join(T(key, notes[k]) for k, key in keys if notes.get(k))


def _hex_bytes(text, size):
    """`size` bytes from a hex string (spaces allowed), or None when it is not that."""
    try:
        b = bytes.fromhex(text.replace(' ', ''))
    except ValueError:
        return None
    return b if len(b) == size else None


def _transform_int(transform_element, default=1):
    """TransformElement byte of an enum identifier (the inverse of TRANSFORM_ELEMENT_MAP)."""
    from . import TRANSFORM_ELEMENT_MAP
    for value, name in TRANSFORM_ELEMENT_MAP.items():
        if name == transform_element:
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
        'ConeDriverOffset':  0,
        'PropertyOffset':        0,
        'PropertyHash':          0,
        'ConeDriverCount':   0,
        'ConeDriver':        [],
        'AttrFlags':                 0x30,
        'TransformElement':         _transform_int(p.transform_element),
        'ReservedVec4':            (0.0, 0.0, 0.0, 1.0),
        'UnknownFloat2':          (0.0, 0.0),
        'UnknownByte72':        0,
        'Axis_parent':  tgt_ax,
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

    # Target axis lives in OutputData[+73], not in any source block.
    parsed_c['Axis_parent'] = AXIS_TO_INT.get(p.target_axis, 0)
    parsed_c['TransformElement'] = _transform_int(p.transform_element,
                                               parsed_c.get('TransformElement', 1))

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
        base['AttrFlags']    = (sp.attr_flags_other & ~2) | (2 if sp.mid_point else 0)
        base['InputType']        = jcns_source_read.input_type_value(sp.input_type)
        base['RotOrder']      = jcns_source_read.rot_order_value(sp.rot_order)
        base['UnknownUInt16_22']   = sp.unknown_uint16_22
        base['Interpolation'] = INTERPOLATION_TO_INT[sp.interpolation]
        base['CurveType'] = sp.curve_type
        if sections_cached:
            # The F-Curve is the data; the count follows it.
            from . import jcns_cm
            base['ComplexMapping'] = jcns_cm.records(sp)
            base['ComplexMappingInfoCount'] = len(base['ComplexMapping'])
        else:
            base['ComplexMappingInfoCount'] = sp.complex_mapping_info_count
        new_sources.append(base)
    parsed_c['sources'] = new_sources


    # In DERIVED_BITS_VERSIONS (v36, v102) AttrFlags bits 4 and 5 follow the transform
    # type and are recomputed; v35 does not follow the rule and is written as is.
    from .modules_shim import get_flags
    flags = get_flags()
    parsed_c['AttrFlags'] = (flags.apply_derived_bits(flags_byte(p), p.transform_element)
                         if version in flags.DERIVED_BITS_VERSIONS else flags_byte(p))
    parsed_c['ReservedVec4']          = (p.reserved_vec4_x, p.reserved_vec4_y,
                                       p.reserved_vec4_z, p.reserved_vec4_w)
    parsed_c['UnknownFloat2']        = (p.unknown_float2_x, p.unknown_float2_y)
    parsed_c['UnknownByte72']      = p.unknown_byte_72
    prop = p.target_property.strip()
    parsed_c['PropertyName']        = prop
    parsed_c['PropertyHash']        = jcns_targets.property_hash(prop, p.property_hash)
    if jcns_targets.is_direct_target(parsed_c['TransformElement']):
        parsed_c['ObjectHashIndex'] = 0xFFFFFFFF
        parsed_c['ObjectHash']      = jcns_targets.object_hash(parsed_c['ObjectName'], p.object_hash)
        parsed_c['ObjectHashMatchesName'] = not p.object_hash
    else:
        parsed_c['ObjectHashIndex'] = 0
    parsed_c['ConeDriver'] = [{
        'CurveData': _hex_bytes(k.curve_data_hex, 12), 'OutMin': k.out_min, 'OutMax': k.out_max,
        'Interpolation': k.interpolation, 'ConeInputIndex': k.cone_input_index,
        'CurveType': k.curve_type, 'ReservedByte': k.reserved_byte,
        'Curve': json.loads(k.curve_json) if k.curve_json else None}
        for k in p.cone_drivers]
    parsed_c['ConeDriverCount'] = len(parsed_c['ConeDriver'])
    parsed_c['TailBytes']     = bytes([
        p.unknown_byte_74, p.unknown_byte_75, p.reserved_tail[0],
        p.group_count, p.reserved_tail[1], p.reserved_tail[2],
    ])


# ---------------------------------------------------------------------------
# Export Operator
# ---------------------------------------------------------------------------

class JCNS_OT_ExportFile(Operator, ExportHelper):
    bl_idname = "jcns.export_file"
    bl_label  = "RE Engine JCNS (.jcns.*)"
    bl_description = T("io.export.tip")
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ""
    filter_glob: StringProperty(
        default=_SCHEMA.FILE_GLOB,
        options={'HIDDEN'},
    )
    clean_hashes: BoolProperty(
        name=T("io.export.clean_hashes.name"),
        description=T("io.export.clean_hashes.tip"),
        default=False
    )
    target_version: EnumProperty(
        name=T("io.export.version.name"),
        description=T("io.export.version.tip"),
        items=[('SOURCE', T("io.export.version.same"), ""),
               ('102', T("io.export.version.v102"), ""),
               ('35', T("io.export.version.v35"), ""),
               ('36', T("io.export.version.v36"), ""),
               ('22', T("io.export.version.v22"), "")],
        default='SOURCE',
        options={'SKIP_SAVE'},          # every export starts from the file's own version
    )

    @classmethod
    def poll(cls, context):
        obj, _ = _get_active_root(context)
        return obj is not None

    def _version(self, rp):
        v = _root_version(rp)
        if v in CONVERTIBLE_VERSIONS and self.target_version != 'SOURCE':
            return int(self.target_version)
        return v

    def draw(self, context):
        _root, rp = _get_active_root(context)
        self.layout.prop(self, "clean_hashes")
        if rp is not None and _root_version(rp) in CONVERTIBLE_VERSIONS:
            self.layout.prop(self, "target_version")
            if self._version(rp) != _root_version(rp):
                self.layout.label(text=T("io.export.version.note"), icon='INFO')

    def invoke(self, context, event):
        root, rp = _get_active_root(context)
        if rp:
            self.filename_ext = f".jcns.{self._version(rp)}"
            if not rp.source_filepath:
                self.filepath = root.name

            if rp.source_filepath:
                path = bpy.path.abspath(rp.source_filepath)
                if rp.upgraded_from and path.endswith(f".jcns.{rp.upgraded_from}"):
                    path = path[:-len(f".{rp.upgraded_from}")] + f".{_root_version(rp)}"
                self.filepath = path
        
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def check(self, context):
        change_ext = False
        _root, rp = _get_active_root(context)
        if rp is not None:
            want = f".jcns.{self._version(rp)}"
            if want != self.filename_ext:
                import re
                self.filepath = re.sub(r'\.jcns\.\d+$', want, self.filepath)
                self.filename_ext = want
                change_ext = True
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
            self.report({'ERROR'}, T("io.export.no_root"))
            return {'CANCELLED'}

        source_path = bpy.path.abspath(root_props.source_filepath)
        is_new = not root_props.source_filepath      # made with New JCNS, never saved
        # An upgraded file is exported from Blender's data: its source is an older version.
        upgraded = bool(root_props.upgraded_from)
        # A cross-version export is built from Blender's data too, in the other version.
        version = self._version(root_props)
        converted_from = _root_version(root_props) if version != _root_version(root_props) else 0
        if converted_from and not root_props.sections_cached:
            self.report({'ERROR'}, T("io.export.old_no_data"))
            return {'CANCELLED'}
        source_exists = os.path.isfile(source_path) and not upgraded and not converted_from

        empties = get_constraint_empties(root_obj)
        # Files made only of Multi / Aim / RotExpression / Material entries have no Ranges.
        if not empties and not entries_of(root_obj):
            self.report({'WARNING'}, T("io.export.no_entries"))
            return {'CANCELLED'}

        _ensure_modules_path()
        if source_exists:
            try:
                from jcns_parser import JCNSParser
                parser = JCNSParser(source_path)
                parser.parse()
            except Exception as exc:
                self.report({'ERROR'}, T("io.export.reparse_failed", exc))
                return {'CANCELLED'}
        else:
            if not root_props.source_version:
                self.report({'ERROR'}, T("io.export.source_missing_old", source_path))
                return {'CANCELLED'}
            if not upgraded and not is_new and not converted_from:
                self.report({'WARNING'}, T("io.export.source_missing_rebuild"))
            parser = _build_stub_parser(root_props, version)
            parser.converted_from = converted_from

        if parser.write_mode == 'rebuild' and not root_props.sections_cached:
            self.report({'ERROR'}, T("io.export.old_no_data"))
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
            if converted_from:
                notes = parser.conversion_notes
                had_cones = bool(parsed_c['ConeDriver'])
                notes['cone_driver'] = notes.get('cone_driver', 0) + convert_constraint(
                    parsed_c, parser.version, getattr(parser, 'cone_index_map', None))
                if had_cones and not parsed_c['ConeDriver'] and not parsed_c['sources']:
                    notes['empty'] = notes.get('empty', 0) + 1       # nothing is left to drive it
                    continue
                if parser.version < 35 and parsed_c['TransformElement'] > MAX_TRANSFORM_ELEMENT_PRE35:
                    notes['target'] = notes.get('target', 0) + 1
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
            self.report({'ERROR'}, T("io.export.write_failed", exc))
            return {'CANCELLED'}

        with open(out_path, 'rb') as f:
            md5_after = hashlib.md5(f.read()).hexdigest()

        # A converted copy is another version's file: the root keeps pointing at its own.
        if out_path != source_path and not converted_from:
            root_props.source_filepath = out_path

        basename = os.path.basename(out_path)
        if converted_from:
            # Every shipped v102 tail is 0000; the other versions' tails vary.
            n_tails = getattr(parser, 'replaced_multi_tails', 0) if parser.version != 102 else 0
            notes = getattr(parser, 'conversion_notes', {})
            lost = _conversion_losses(notes)
            if notes.get('target'):
                self.report({'WARNING'}, T("io.export.converted_target", basename, notes['target']))
            if lost:
                self.report({'WARNING'}, T("io.export.converted_lost", basename, converted_from, parser.version, lost))
            elif n_tails:
                self.report({'WARNING'}, T("io.export.converted_multi", basename, converted_from, parser.version,
                                           n_tails, convert_multi_tail(b'', parser.version).hex()))
            else:
                self.report({'INFO'}, T("io.export.done_upgraded", basename, converted_from, parser.version))
        elif upgraded:
            self.report({'INFO'}, T("io.export.done_upgraded", basename, root_props.upgraded_from, parser.version))
        elif is_new:
            self.report({'INFO'}, T("io.export.done_new", basename))
        elif md5_before is None:
            self.report({'INFO'}, T("io.export.done_no_source", basename))
        elif md5_before == md5_after:
            self.report({'INFO'}, T("io.export.done_same", basename))
        else:
            self.report(
                {'INFO'},
                T("io.export.done_changed", basename, md5_before[:8], md5_after[:8])
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
