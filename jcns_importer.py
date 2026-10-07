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

from .modules_shim import get_schema, ensure_path, T

ensure_path()
import jcns_source_read  # noqa: E402
import jcns_upgrade  # noqa: E402
import jcns_targets  # noqa: E402
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
        AXIS_TO_INT, INT_TO_AXIS, TRANSFORM_ELEMENT_MAP, INT_TO_WORLD_UP_TYPE, INT_TO_ROT_REST, INT_TO_INTERPOLATION,
        INT_TO_MAT_APPLY_MODE, make_constraint_empty_name,
    )

    _ensure_modules_path()
    try:
        from jcns_parser import JCNSParser, write_mode
        parser = JCNSParser(filepath)
        constraints = parser.parse()
    except Exception as exc:
        return None, 0, T("io.import.parse_failed", exc)

    # A file the writer cannot reproduce could never be exported back: refuse it.
    from jcns_validate import check_exportable
    problems = check_exportable(parser)
    if problems:
        msg = (T("io.import.not_exportable")
               + "\n".join(f"  * {p}" for p in problems))
        return None, 0, msg

    # An older version of a game's file is read as the game's latest: Blender holds the
    # upgraded data, and the source file is not exported from again.
    upgraded_from, read_table_pending = 0, False
    latest = jcns_upgrade.latest_version(parser.version)
    if latest != parser.version:
        from .jcns_exporter import skeleton_of
        parent, skeleton_names = skeleton_of(armature_obj)
        try:
            upgraded, upgrade_problems = jcns_upgrade.upgrade(parser, latest, parent, skeleton_names)
        except jcns_upgrade.UpgradeError as exc:
            return None, 0, T("io.import.upgrade_failed", latest, exc)
        problems = check_exportable(upgraded)
        if problems:
            return None, 0, (T("io.import.upgrade_not_exportable", latest)
                             + "\n".join(f"  * {p}" for p in problems))
        for line in upgrade_problems:
            print("[JCNS] " + line)
        upgraded_from, read_table_pending = parser.version, bool(upgrade_problems)
        parser = upgraded
        constraints = parser.constraints

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
    from . import jcns_sdk_ops
    jcns_sdk_ops.ensure_keys(root.jcns_root_props)
    if armature_obj:
        root.jcns_root_props.target_armature = armature_obj

    # Drives the export extension and the writer mode.
    root.jcns_root_props.source_version = parser.version
    root.jcns_root_props.upgraded_from = upgraded_from
    root.jcns_root_props.read_table_pending = read_table_pending
    root.jcns_root_props.rebuild_blocked = write_mode(parser.version) == 'rebuild' and parser.write_mode == 'inplace'

    # What an export without the source file needs besides the entries.
    root.jcns_root_props.header_unknown_bytes = (parser.header.get('HeaderUnknownByte1', 0),
                                                 parser.header.get('HeaderUnknownByte2', 0))
    for section in parser.section_order:
        root.jcns_root_props.section_order.add().value = section
    for h in parser.hash_list:
        root.jcns_root_props.hash_list.add().hash = jcns_targets.to_signed32(h)

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

        transform_int = c.get('TransformElement', 1)
        transform_str = TRANSFORM_ELEMENT_MAP.get(transform_int, 'Unknown')

        first = file_sources[0] if file_sources else {}
        empty_name = make_constraint_empty_name(
            idx, first.get('SourceName', ''), target_bone, tgt_ax_str,
            INT_TO_AXIS.get(min(first.get('source_axis', 0), 3), 'X'),
            max(0, len(file_sources) - 1),
            len(c.get('ConeDriver') or []),
        )

        obj = bpy.data.objects.new(empty_name, None)
        obj.empty_display_type = 'ARROWS'
        obj.empty_display_size = 0.05
        obj.parent = root
        coll.objects.link(obj)

        p = obj.jcns_cns_props
        p.is_jcns_constraint = True
        p.constraint_type = 'Outputs'
        p.target_bone    = target_bone
        p.transform_element = transform_str
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
            sp.ref_frame_x = s.get('ref_frame_x', 0.0)
            sp.ref_frame_y = s.get('ref_frame_y', 0.0)
            sp.ref_frame_z = s.get('ref_frame_z', 0.0)
            sp.ref_frame_w = s.get('ref_frame_w', 1.0)
            cm_value = s.get('AttrFlags', 3)
            sp.mid_point, sp.attr_flags_other = bool(cm_value & 2), cm_value & ~2
            mode = jcns_source_read.input_type_id(s.get('InputType', 3))
            if mode is None:
                # The enum cannot hold an unknown mode.
                print("[JCNS] %s <- %s: InputType %r is unknown, read as SWING_TWIST"
                      % (c.get('ObjectName', '?'), s.get('SourceName', '?'), s.get('InputType')))
                mode = 'ROT_RPY'
            sp.input_type = mode
            order = jcns_source_read.ROT_ORDER_NAMES.get(s.get('RotOrder', 0))
            if order is None:
                # The enum holds only orders 0-3.
                print("[JCNS] %s <- %s: RotOrder %r is unknown, read as XYZ"
                      % (c.get('ObjectName', '?'), s.get('SourceName', '?'), s.get('RotOrder')))
                order = 'XYZ'
            sp.rot_order = order
            sp.complex_mapping_info_count = s.get('ComplexMappingInfoCount', 0)
            sp.unknown_uint16_22   = s.get('UnknownUInt16_22', 0)
            interp = INT_TO_INTERPOLATION.get(s.get('Interpolation', 0))
            if interp is None:
                print("[JCNS] %s <- %s: interpolation byte %r is unknown, read as 0"
                      % (c.get('ObjectName', '?'), s.get('SourceName', '?'), s.get('Interpolation')))
                interp = 'LINEAR'
            sp.interpolation = interp
            sp.curve_type = s.get('CurveType', 0)
            if s.get('ComplexMapping'):
                jcns_cm.load(sp, s['ComplexMapping'])

        flags = c.get('AttrFlags', 0x30)
        p.base_pose, p.attr_flags_other = bool(flags & 1), flags & 0xFE
        vec4                    = c.get('ReservedVec4', (0.0, 0.0, 0.0, 1.0))
        p.reserved_vec4_x, p.reserved_vec4_y, p.reserved_vec4_z, p.reserved_vec4_w = vec4
        f2                      = c.get('UnknownFloat2', (0.0, 0.0))
        p.unknown_float2_x, p.unknown_float2_y = f2
        p.unknown_byte_72       = c.get('UnknownByte72', 0)
        p.target_property       = c.get('PropertyName', '')
        p.property_hash         = jcns_targets.property_hash_override(
            c.get('PropertyHash', 0) & 0xFFFFFFFF, p.target_property)
        if jcns_targets.is_direct_target(transform_int):
            p.object_hash       = jcns_targets.object_hash_override(
                c.get('ObjectHash', 0) & 0xFFFFFFFF, target_bone)
        for ci in c.get('ConeDriver') or []:
            k = p.cone_drivers.add()
            k.cone_input_index, k.out_min, k.out_max = ci['ConeInputIndex'], ci['OutMin'], ci['OutMax']
            k.interpolation, k.curve_type, k.reserved_byte = ci['Interpolation'], ci['CurveType'], ci['ReservedByte']
            k.curve_data_hex = bytes(ci.get('CurveData', bytes(12))).hex()
        if len(p.cone_drivers):
            # Rename: target_bone's update named it while the cone list was empty.
            from . import constraint_name_from_props
            obj.name = constraint_name_from_props(idx, p)
        tail = c.get('TailBytes', b'\x00' * 6)
        p.unknown_byte_74, p.unknown_byte_75, p.group_count = tail[0], tail[1], tail[3]
        p.reserved_tail = (tail[2], tail[4], tail[5])


    # Non-Ranges sections store hashes only.  Resolve through the armature, then the
    # names this file's Ranges spell out, then the bundled dictionary, else show the
    # raw hash (the exporter reads a "0x1234ABCD" name back as that hash).
    import json
    from jcns_sections import (multi_editable, read_joint_signature, aim_editable, rot_editable,
                               cone_inputs_to_json)
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
    sk_recs, sk_meta = multi_editable(parser)
    for idx, r in enumerate(sk_recs):
        obj, p2 = _section_empty('Multi', idx, 'SINGLE_ARROW', 0.03)
        p2.constraint_type = 'Multi'
        p2.target_bone = _nm(r['object'])
        p2.multi_tail = tuple(r['tail'])
        for src in r['sources']:
            w = p2.multi_sources.add()
            w.bone, w.weight = _nm(src['hash']), src['weight']
        obj.name = section_empty_name('Multi', idx, p2)
    rp.file_constant = sk_meta['constant']
    rp.read_joint_table.clear()
    for h in sk_meta['read_joint_table']:
        item = rp.read_joint_table.add()
        item.hash, item.name = jcns_targets.to_signed32(h), _nm(h)
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
        p2.aim_offset, p2.aim_axis, p2.aim_up_axis, p2.aim_up_dir = a['vectors']
        world_up_type = INT_TO_WORLD_UP_TYPE.get(a['world_up_type'])
        if world_up_type is None:
            print("[JCNS] Aim %d: WorldUpType %r is unknown, read as 0" % (idx, a['world_up_type']))
            world_up_type = 'SCENE_UP'
        p2.world_up_type = world_up_type
        p2.aim_bytes = a['bytes']
        obj.name = section_empty_name('Aim', idx, p2)

    rot_recs, rot_meta = rot_editable(parser)
    for idx, r in enumerate(rot_recs):
        obj, p2 = _section_empty('RotExpr', idx, 'CIRCLE', 0.03)
        p2.constraint_type = 'RotExpression'
        p2.target_bone = _nm(r['joint'])
        p2.rot_source_bone = _nm(r['source'])
        p2.rot_rotation, p2.rot_scale = r['rotation'], r['scale']
        rest_mode = INT_TO_ROT_REST.get(r['bytes'][1])
        if rest_mode is None:
            print("[JCNS] RotExpr %d: byte[1]=%r is unknown, read as 0" % (idx, r['bytes'][1]))
            rest_mode = 'REPLACE'
        p2.rot_rest_mode = rest_mode
        p2.rot_unknown_bytes = (r['bytes'][0], r['bytes'][2], r['bytes'][3])
        p2.rot_gains = r['floats']
        obj.name = section_empty_name('RotExpression', idx, p2)
    rp.rot_map_value = rot_meta['map_value']
    if not rot_meta['map_uniform']:
        print("[JCNS] RotExpressionMap holds different values, using the first (%d)" % rot_meta['map_value'])

    rp.cone_inputs_json = cone_inputs_to_json(parser.cone_inputs) if getattr(parser, 'cone_inputs', []) else ''
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
        raw = mc['raw_body']        # 12 bytes: NameHash(4) + PropHash(4) + ApplyMode(1) + tail(3)
        name_h, prop_h = _ms.unpack_from('<II', raw, 0)
        p2.mat_name_hash        = f"0x{name_h:08X}"
        p2.mat_property_hash    = f"0x{prop_h:08X}"
        # the names are only known when the dictionary has them
        p2.mat_name             = names.get(name_h) or name_of(name_h) or ""
        p2.mat_property         = names.get(prop_h) or name_of(prop_h) or ""
        apply_mode = INT_TO_MAT_APPLY_MODE.get(raw[8])
        if apply_mode is None:
            print("[JCNS] Material %d: ApplyMode %r is unknown, read as 0" % (idx, raw[8]))
        p2.mat_apply_mode = apply_mode or 'TRANS'
        p2.mat_tail_0, p2.mat_tail_1, p2.mat_tail_2 = raw[9], raw[10], raw[11]
        obj.name = section_empty_name('Material', idx, p2)

    rp.jxg_path = (parser.joint_export_graph or {}).get('path', '') or ''

    # A model folder keeps its .mdf2 next to the .jcns: take those as the Material
    # entries' references, which also fills in their names.
    if parser.material_cns:
        import glob as _glob
        for mdf in sorted(_glob.glob(os.path.join(_glob.escape(os.path.dirname(filepath)), '*.mdf2.*'))):
            rp.mdf_refs.add().filepath = mdf

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
    bl_idname = "jcns.import_file"
    bl_label  = "RE Engine JCNS (.jcns.*)"
    bl_description = T("io.import.tip")
    bl_options = {'REGISTER', 'UNDO'}

    filter_glob: StringProperty(
        default=_SCHEMA.FILE_GLOB,
        options={'HIDDEN'},
    )

    # EnumProperty: PointerProperty is invalid on Operators.
    target_armature_name: EnumProperty(
        name=T("io.import.armature.name"),
        description=T("io.import.armature.tip"),
        items=_get_armature_items,
    )

    resolve_hashes: BoolProperty(
        name=T("io.import.resolve.name"),
        description=T("io.import.resolve.tip"),
        default=True,
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "resolve_hashes")
        col = layout.column()
        col.enabled = self.resolve_hashes
        col.prop(self, "target_armature_name", icon='ARMATURE_DATA')

    def execute(self, context):
        filepath = self.filepath
        if not os.path.isfile(filepath):
            self.report({'ERROR'}, T("io.import.file_not_found", filepath))
            return {'CANCELLED'}

        armature_obj = None
        if self.resolve_hashes and self.target_armature_name != "NONE":
            armature_obj = context.scene.objects.get(self.target_armature_name)

        root, count, err = do_import(filepath, context, armature_obj)
        if err:
            self.report({'ERROR'}, err)
            return {'CANCELLED'}

        arm_label = armature_obj.name if armature_obj else T("io.import.armature_none")
        summary = T("io.import.summary", count, root.name, arm_label)
        rp = root.jcns_root_props
        if rp.upgraded_from:
            summary += T("io.import.summary_upgraded", rp.upgraded_from, rp.source_version)
            if rp.read_table_pending:
                summary += T("io.import.summary_pending")
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
# New (empty) file
# ---------------------------------------------------------------------------

# (detected_game id, JCNS version, string key of its name)
NEW_FILE_GAMES = (
    ('MHW_WILDS', 102, "io.new.game_wilds"),
    ('RE9', 35, "io.new.game_requiem"),
)
_NEW_NAME = {'MHW_WILDS': "wilds", 'RE9': "requiem"}


def do_new(context, game, armature_obj=None):
    """An empty JCNS collection with its root Empty, in the newest version of `game`.
    Nothing is read from a file: the export builds the file header from the root."""
    version = {g: v for g, v, _ in NEW_FILE_GAMES}[game]
    coll = bpy.data.collections.new(f"JCNS_new_{_NEW_NAME[game]}")
    coll.color_tag = 'COLOR_04'   # green, like an import
    context.scene.collection.children.link(coll)

    root = bpy.data.objects.new(coll.name, None)
    root.empty_display_type = 'PLAIN_AXES'
    root.empty_display_size = 0.2
    root.show_in_front = True
    coll.objects.link(root)

    rp = root.jcns_root_props
    from . import jcns_sdk_ops
    jcns_sdk_ops.ensure_keys(rp)
    if armature_obj:
        rp.target_armature = armature_obj
    rp.source_version = version
    rp.detected_game = game
    rp.sections_cached = True
    return root


def _armature_for_new(context):
    """The active armature, else the scene's only one."""
    obj = context.active_object
    if obj is not None and obj.type == 'ARMATURE':
        return obj
    armatures = [o for o in context.scene.objects if o.type == 'ARMATURE']
    return armatures[0] if len(armatures) == 1 else None


class JCNS_OT_NewFile(Operator):
    bl_idname = "jcns.new_file"
    bl_label  = T("io.new.label")
    bl_description = T("io.new.tip")
    bl_options = {'REGISTER', 'UNDO'}

    game: EnumProperty(
        name=T("io.new.game"),
        items=[(g, T(key), "") for g, _, key in NEW_FILE_GAMES],
        default='MHW_WILDS',
    )

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=320)

    def draw(self, context):
        self.layout.prop(self, "game")

    def execute(self, context):
        root = do_new(context, self.game, _armature_for_new(context))
        bpy.ops.object.select_all(action='DESELECT')
        root.select_set(True)
        context.view_layer.objects.active = root
        context.scene.jcns_active_collection = root.users_collection[0]
        self.report({'INFO'}, T("io.new.done", root.name, root.jcns_root_props.source_version))
        return {'FINISHED'}


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

_classes = [JCNS_OT_ImportFile, JCNS_OT_NewFile]


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
