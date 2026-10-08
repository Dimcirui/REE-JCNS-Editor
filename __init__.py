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

from .modules_shim import T

bl_info = {
    "name": "REE JCNS Editor",
    "author": "Dimcirui",
    "version": (0, 16, 0),
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
    ('X', "X", T("props.axis.x")),
    ('Y', "Y", T("props.axis.y")),
    ('Z', "Z", T("props.axis.z")),
    ('W', "W", T("props.axis.w")),
]

# JointDriver_v2 bytes +24 / +25 (the .bt calls them UpdateTimingID and
# TransformIDSrc).
#   +24 is the curve mode: 0 / 1 are two-point (the kink is ignored; a straight
#       line from start to end), 2 / 3 three-point.  4 / 5 are unmodelled and
#       treated as three-point (modules.jcns_mapping.is_two_point).  In
#       three-point mode a kink strictly outside [start, end] disables the
#       source: the output is 0, not a clamped constant.
#   +25 is the read mode (below); it does not change the curve shape.
# The two bytes vary independently, so both stay raw editable numbers.


def _input_type_items():
    from .modules_shim import ensure_path
    ensure_path()
    import jcns_source_read
    items = [(ident, "%d %s" % (value, name), desc, value)
             for value, ident, name, _q, desc in jcns_source_read.INPUT_TYPES]
    default = jcns_source_read.input_type_id(jcns_source_read.DEFAULT_INPUT_TYPE)
    return items, default


# +25 InputType; the table lives in modules/jcns_source_read.py.
_INPUT_TYPE_ITEMS, _INPUT_TYPE_DEFAULT = _input_type_items()


def _rot_order_items():
    from .modules_shim import ensure_path
    ensure_path()
    import jcns_source_read
    return [(name, "%d %s" % (value, name), T("props.euler.order_desc", name, name[0]), value)
            for value, name in sorted(jcns_source_read.ROT_ORDER_NAMES.items())]


# +27 RotOrder, Blender order names.
_ROT_ORDER_ITEMS = _rot_order_items()

# Source byte +28: how a segment of the mapping runs between its anchors.
INTERPOLATION_ITEMS = [
    ('LINEAR', T("props.interp.linear"), T("props.interp.linear_desc")),
    ('SLOW', T("props.interp.slow"), T("props.interp.slow_desc")),
    ('FAST', T("props.interp.fast"), T("props.interp.fast_desc")),
    ('SMOOTH', T("props.interp.smooth"), T("props.interp.smooth_desc")),
]
INTERPOLATION_TO_INT = {item[0]: i for i, item in enumerate(INTERPOLATION_ITEMS)}
INT_TO_INTERPOLATION = {i: ident for ident, i in INTERPOLATION_TO_INT.items()}

# Aim WorldUpType: how the roll around the aim axis is fixed.
WORLD_UP_TYPE_ITEMS = [
    ('SCENE_UP', T("props.world_up_type.scene_up"), T("props.world_up_type.scene_up_desc")),
    ('OBJECT_UP', T("props.world_up_type.object_up"), T("props.world_up_type.object_up_desc")),
    ('OBJECT_ROTATION_UP', T("props.world_up_type.object_rotation_up"), T("props.world_up_type.object_rotation_up_desc")),
    ('VECTOR', T("props.world_up_type.vector"), T("props.world_up_type.vector_desc")),
    ('NONE', T("props.world_up_type.none"), T("props.world_up_type.none_desc")),
    ('NONE_MAYA_LIKE', T("props.world_up_type.none_maya_like"), T("props.world_up_type.none_maya_like_desc")),
]
WORLD_UP_TYPE_TO_INT = {item[0]: i for i, item in enumerate(WORLD_UP_TYPE_ITEMS)}

# MaterialConstraintData.ApplyMode, the Material record's byte 8
MAT_APPLY_MODE_ITEMS = [
    ('TRANS', T("props.mat_apply.trans"), T("props.mat_apply.trans_desc")),
    ('EULER', T("props.mat_apply.euler"), T("props.mat_apply.euler_desc")),
    ('SCALE', T("props.mat_apply.scale"), T("props.mat_apply.scale_desc")),
    ('ROT', T("props.mat_apply.rot"), T("props.mat_apply.rot_desc")),
]
MAT_APPLY_MODE_TO_INT = {item[0]: i for i, item in enumerate(MAT_APPLY_MODE_ITEMS)}
INT_TO_MAT_APPLY_MODE = {i: ident for ident, i in MAT_APPLY_MODE_TO_INT.items()}


def mat_name_hash(name):
    """'0x%08X' of the murmur3 of a UTF-16 material or parameter name."""
    from .modules_shim import ensure_path
    ensure_path()
    import os, sys
    hashing = os.path.join(os.path.dirname(__file__), "modules", "hashing")
    if hashing not in sys.path:
        sys.path.insert(0, hashing)
    from mmh3.pymmh3 import hashUTF16
    return "0x%08X" % (hashUTF16(name) & 0xFFFFFFFF)


def _sync_mat(self, name_attr, hash_attr):
    name = getattr(self, name_attr).strip()
    if name and getattr(self, hash_attr) != mat_name_hash(name):
        setattr(self, hash_attr, mat_name_hash(name))
    _sync_constraint_name(self)


def _update_mat_name(self, context):
    _sync_mat(self, 'mat_name', 'mat_name_hash')


def _update_mat_property(self, context):
    _sync_mat(self, 'mat_property', 'mat_property_hash')


def _unsync_mat(self, name_attr, hash_attr):
    # A hash typed in by hand no longer belongs to the name shown
    name = getattr(self, name_attr).strip()
    if name and getattr(self, hash_attr) != mat_name_hash(name):
        setattr(self, name_attr, "")
    _sync_constraint_name(self)


# ── reference .mdf2 files (the root's mdf_refs) ─────────────────────────────
_catalog_memo = {}


def mdf_catalog(rp):
    """{material name: {'hash', 'params': {name: [hash, components]}}} of a root's
    reference files, from the cache refresh_mdf_catalog() keeps."""
    import json
    raw = rp.mdf_catalog_json if rp is not None else ""
    if not raw:
        return {}
    if raw not in _catalog_memo:
        _catalog_memo.clear()
        try:
            _catalog_memo[raw] = json.loads(raw)
        except ValueError:
            _catalog_memo[raw] = {}
    return _catalog_memo[raw]


def refresh_mdf_catalog(rp):
    """Re-read every reference file into the cache; a file that cannot be read keeps
    its error on the list row and adds nothing."""
    import json
    from .modules_shim import ensure_path
    ensure_path()
    import jcns_mdf
    per_file = []
    for ref in rp.mdf_refs:
        path = bpy.path.abspath(ref.filepath) if ref.filepath else ""
        if not path:
            ref.status = ""
            continue
        try:
            mats = jcns_mdf.read_file(path)
        except (OSError, jcns_mdf.MdfError) as exc:
            ref.status = str(exc)
            continue
        ref.status = ""
        ref.material_count = len(mats)
        per_file.append(mats)
    cat = jcns_mdf.catalog(per_file)
    rp.mdf_catalog_json = json.dumps(cat, ensure_ascii=False) if cat else ""


def resolve_material_names(root):
    """Fill blank material / parameter names of a root's Material entries from its
    reference files, matching the hashes.  -> number of names filled."""
    cat = mdf_catalog(root.jcns_root_props)
    if not cat:
        return 0
    by_hash = {int(e['hash']): name for name, e in cat.items()}
    filled = 0
    for o in section_empties(root, 'Material'):
        p = o.jcns_cns_props
        try:
            nh, ph = int(p.mat_name_hash, 16), int(p.mat_property_hash, 16)
        except ValueError:
            continue
        if not p.mat_name and nh in by_hash:
            p.mat_name = by_hash[nh]
            filled += 1
        # Shipped files sometimes name a material the model does not have while the
        # parameter is one of its own: look in the named material first, then in all.
        mat = cat.get(p.mat_name)
        if not p.mat_property:
            for m in ([mat] if mat is not None else []) + list(cat.values()):
                pname = next((n for n, (h, _c) in m['params'].items() if int(h) == ph), None)
                if pname:
                    p.mat_property = pname
                    filled += 1
                    break
    return filled


def material_mismatch(p, rp):
    """Why a Material entry's names are not in its root's reference files, or ''."""
    cat = mdf_catalog(rp)
    if not cat or not p.mat_name:
        return ''
    mat = cat.get(p.mat_name)
    if mat is None:
        return T("editors.mat.no_material")
    if p.mat_property and p.mat_property not in mat['params']:
        return T("editors.mat.no_param")
    return ''


def _update_mdf_ref(self, context):
    root = self.id_data
    rp = getattr(root, 'jcns_root_props', None)
    if rp is None:
        return
    refresh_mdf_catalog(rp)
    resolve_material_names(root)


def _search_mat_name(self, context, edit_text):
    _root, rp = get_jcns_root_from_constraint(self.id_data)
    needle = edit_text.lower()
    return sorted(n for n in mdf_catalog(rp) if needle in n.lower())


def _search_mat_property(self, context, edit_text):
    _root, rp = get_jcns_root_from_constraint(self.id_data)
    cat = mdf_catalog(rp)
    mats = [cat[self.mat_name]] if self.mat_name in cat else list(cat.values())
    needle = edit_text.lower()
    seen = {}
    for m in mats:
        for pname, (_h, n) in m['params'].items():
            if needle in pname.lower():
                seen.setdefault(pname, n)
    return [(pname, T("props.mat.components", n)) for pname, n in sorted(seen.items())]


def _update_mat_name_hash(self, context):
    _unsync_mat(self, 'mat_name', 'mat_name_hash')


def _update_mat_property_hash(self, context):
    _unsync_mat(self, 'mat_property', 'mat_property_hash')
INT_TO_WORLD_UP_TYPE = {i: ident for ident, i in WORLD_UP_TYPE_TO_INT.items()}

# RotExpression byte[1]: whether the result lies on the rest pose.
ROT_REST_ITEMS = [
    ('REPLACE', T("props.rot_rest.replace"), T("props.rot_rest.replace_desc")),
    ('ADD_REST', T("props.rot_rest.add_rest"), T("props.rot_rest.add_rest_desc")),
]
ROT_REST_TO_INT = {'REPLACE': 0, 'ADD_REST': 48}
INT_TO_ROT_REST = {0: 'REPLACE', 48: 'ADD_REST'}

TRANSFORM_ITEMS = [
    ('Trans',    "Trans",    T("props.transform.t0")),
    ('Rot',       "Rot",       T("props.transform.t1")),
    ('Scale',          "Scale",          T("props.transform.t2")),
    ('Deform',     "Deform",     T("props.transform.t3")),
    ('RotRPY',     "RotRPY",     T("props.transform.t4")),
    ('RotPYR',     "RotPYR",     T("props.transform.t5")),
    ('ExpMap', "ExpMap", T("props.transform.t6")),
    ('Material', "Material", T("props.transform.t7")),
    ('MaterialF4',    "MaterialF4",    T("props.transform.t8")),
    ('MaterialPosF4',    "MaterialPosF4",    T("props.transform.t9")),
    ('MaterialRotF4',    "MaterialRotF4",    T("props.transform.t10")),
    ('ComponentProperty',         "ComponentProperty",         T("props.transform.t11")),
    ('UserValue',     "UserValue",     T("props.transform.t12")),
    ('Rot2',   "Rot2",   T("props.transform.t13")),
    ('RotRPY2', "RotRPY2", T("props.transform.t14")),
    ('RotPYR2', "RotPYR2", T("props.transform.t15")),
    ('ExpMap2', "ExpMap2", T("props.transform.t16")),
]

AXIS_TO_INT = {'X': 0, 'Y': 1, 'Z': 2, 'W': 3}
INT_TO_AXIS = {0: 'X', 1: 'Y', 2: 'Z', 3: 'W'}

TRANSFORM_ELEMENT_MAP = {
    0:  'Trans',
    1:  'Rot',
    2:  'Scale',
    3:  'Deform',
    4:  'RotRPY',
    5:  'RotPYR',
    6:  'ExpMap',
    7:  'Material',
    8:  'MaterialF4',
    9:  'MaterialPosF4',
    10: 'MaterialRotF4',
    11: 'ComponentProperty',
    12: 'UserValue',
    13: 'Rot2',
    14: 'RotRPY2',
    15: 'RotPYR2',
    16: 'ExpMap2',
}


# ---------------------------------------------------------------------------
# Update and search callbacks
# ---------------------------------------------------------------------------

def _update_base_pose(self, context):
    _refresh_flags_preview(self)


def flags_byte(p):
    """The OutputData AttrFlags byte: bit 0 is the base_pose switch, the other bits
    are kept as read (bits 4 and 5 are rederived from the transform type on export)."""
    return (int(p.attr_flags_other) & 0xFE) | int(bool(p.base_pose))


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
    if p.constraint_type in ('Multi', 'Aim', 'RotExpression', 'Material'):
        obj.name = section_empty_name(p.constraint_type, section_index(obj), p)
        return
    if p.constraint_type not in ('Outputs', ''):
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
SECTION_PREFIX = {'Multi': 'Multi', 'Aim': 'Aim', 'RotExpression': 'RotExpr', 'Material': 'Mat'}


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
    if kind == 'Multi':
        label = p.target_bone or '?'
    elif kind == 'Aim':
        label = f"{p.target_bone or '?'} → {p.aim_target_bone or '?'}"
    elif kind == 'RotExpression':
        label = f"{p.rot_source_bone or '?'} → {p.target_bone or '?'}"
    elif kind == 'Material':
        label = f"{p.target_bone or '?'} → {p.mat_name or p.mat_name_hash}.{p.mat_property or p.mat_property_hash}"
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


def _output_kind(props):
    from .modules_shim import get_targets
    te = next((v for v, n in TRANSFORM_ELEMENT_MAP.items() if n == props.transform_element), 1)
    return get_targets().target_kind(te)


def _used_names(props, attr, kind):
    """Values of `attr` on this root's other Outputs entries whose target is of `kind`."""
    root, _rp = get_jcns_root_from_constraint(props.id_data)
    if root is None:
        return set()
    return {getattr(o.jcns_cns_props, attr) for o in get_constraint_empties(root)
            if o != props.id_data and _output_kind(o.jcns_cns_props) == kind} - {""}


def _matching(names, edit_text):
    needle = edit_text.lower()
    matches = sorted(n for n in names if needle in n.lower())
    if edit_text and edit_text not in names:
        return [edit_text] + matches
    return matches


def _search_output_target(self, context, edit_text):
    """Bones for joint targets, the reference mdf2 materials for material targets,
    and otherwise the names other entries of the same kind use."""
    kind = _output_kind(self)
    if kind == 'bone':
        return _search_bone_names(context, edit_text)
    names = _used_names(self, 'target_bone', kind)
    if kind == 'material':
        _root, rp = get_jcns_root_from_constraint(self.id_data)
        names |= set(mdf_catalog(rp))
    return _matching(names, edit_text)


def _search_output_property(self, context, edit_text):
    kind = _output_kind(self)
    names = _used_names(self, 'target_property', kind)
    if kind == 'material':
        _root, rp = get_jcns_root_from_constraint(self.id_data)
        cat = mdf_catalog(rp)
        for m in ([cat[self.target_bone]] if self.target_bone in cat else cat.values()):
            names |= set(m['params'])
    return _matching(names, edit_text)


# ---------------------------------------------------------------------------
# Property Group: one JointDriver_v2 block
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
    flag:   IntProperty(name="Flag", description=T("props.cm_key.flag_desc"),
                        default=0, min=0)


def _redraw_cones(self, context):
    from . import jcns_cone_draw
    jcns_cone_draw.tag_redraw()


def _refresh_cone_table(self, context):
    """A ConeInput edit changes the previewed entries that read this cone: re-apply them."""
    try:
        import re
        from . import jcns_operators
        m = re.search(r'cone_inputs\[(\d+)\]', self.path_from_id())
        jcns_operators.refresh_cone_users(self.id_data, int(m.group(1)) if m else None)
    except Exception as exc:                     # an edit must never hard-fail
        print("[JCNS] cone refresh skipped: %r" % exc)
    _redraw_cones(self, context)


def _cone_joint_update(self, context):
    """Picking the joint fills an empty parent joint with its parent in the armature,
    the only parent the preview follows."""
    rp = getattr(self.id_data, 'jcns_root_props', None)
    arm = rp.target_armature if rp is not None else None
    if not self.parent_joint.strip() and arm is not None and arm.type == 'ARMATURE':
        b = arm.data.bones.get(self.joint.strip())
        if b is not None and b.parent is not None:
            self.parent_joint = b.parent.name
    _refresh_cone_table(self, context)


def _cone_euler_get(self):
    from mathutils import Quaternion
    x, y, z, w = self.direction
    return tuple(Quaternion((w, x, y, z)).to_euler('XYZ'))


def _cone_euler_set(self, value):
    from mathutils import Euler
    q = Euler(value, 'XYZ').to_quaternion()
    self.direction = (q.x, q.y, q.z, q.w)


def _cone_base_pose_get(self):
    return bool(self.tail[3] & 1)


def _cone_base_pose_set(self, value):
    t = list(self.tail)
    t[3] = (t[3] & ~1) | int(bool(value))
    self.tail = t


class JCNSConeInput(PropertyGroup):
    """One ConeInput record of the root's table (jcns_schema.CONE_INPUT): a cone that
    ConeDrivers point at by index.  See jcns_source_read.cone_value for what it measures."""
    name: StringProperty(name=T("props.cone_input.name"), default="Cone_cdr", update=_refresh_cone_table)
    joint: StringProperty(name=T("props.cone_input.joint"), description=T("props.cone_input.joint_desc"),
                          default="", update=_cone_joint_update,
                          search=lambda self, context, text: _search_bone_names(context, text))
    parent_joint: StringProperty(name=T("props.cone_input.parent"), description=T("props.cone_input.parent_desc"),
                                 default="", update=_refresh_cone_table,
                                 search=lambda self, context, text: _search_bone_names(context, text))
    symmetry_joint: StringProperty(name=T("props.cone_input.symmetry"), description=T("props.cone_input.symmetry_desc"),
                                   default="", update=_refresh_cone_table,
                                   search=lambda self, context, text: _search_bone_names(context, text))
    # Stored as the file's quaternion (x, y, z, w); the panel edits it as an Euler.
    direction: FloatVectorProperty(size=4, default=(0.0, 0.0, 0.0, 1.0), update=_refresh_cone_table)
    direction_euler: FloatVectorProperty(name=T("props.cone_input.direction"),
                                         description=T("props.cone_input.direction_desc"),
                                         size=3, subtype='EULER', get=_cone_euler_get, set=_cone_euler_set,
                                         update=_refresh_cone_table)
    angle: FloatProperty(name=T("props.cone_input.angle"), description=T("props.cone_input.angle_desc"),
                         default=0.785398, min=0.0, subtype='ANGLE', update=_refresh_cone_table)
    matrix: FloatVectorProperty(name="Matrix", description=T("props.cone_input.matrix_desc"), size=12,
                                default=(1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0),
                                update=_refresh_cone_table)
    translation: FloatVectorProperty(size=4, default=(0.0, 0.0, 0.0, 0.0))     # v13-v23 only
    tail: IntVectorProperty(size=8, default=(6, 6, 0, 0, 0, 0, 0, 0), min=0, max=255)
    base_pose: BoolProperty(name=T("props.cone_input.base_pose"), description=T("props.cone_input.base_pose_desc"),
                            get=_cone_base_pose_get, set=_cone_base_pose_set, update=_refresh_cone_table)
    unknown_uint32: IntProperty(default=0, min=0)


class JCNSConeDriver(PropertyGroup):
    """One ConeDriver record (24 bytes, v24+; 12 before): a cone this constraint reads.
    See jcns_schema.CONE_DRIVER for what each field does."""
    cone_input_index: IntProperty(name="ConeInput", description=T("props.cone.index_desc"),
                                  default=0, min=0, max=255, update=_refresh_preview)
    out_min: FloatProperty(name=T("props.cone.out_min"), description=T("props.cone.out_min_desc"), default=0.0,
                           update=_refresh_preview_values)
    out_max: FloatProperty(name=T("props.cone.out_max"), description=T("props.cone.out_max_desc"), default=0.0,
                           update=_refresh_preview_values)
    interpolation: IntProperty(name=T("props.cone.interpolation"), description=T("props.cone.interpolation_desc"),
                               default=0, min=0, max=255, update=_refresh_preview_values)
    curve_type: IntProperty(name=T("props.cone.curve_type"), description=T("props.cone.curve_type_desc"),
                            default=0, min=0, max=255, update=_refresh_preview)
    curve_data_hex: StringProperty(name=T("props.cone.curve_data"), description=T("props.cone.curve_data_desc"),
                                   default="00" * 12)
    reserved_byte: IntProperty(name="+23", default=0, min=0, max=255)


class JCNSIntItem(PropertyGroup):
    """One integer of a stored list."""
    value: IntProperty(name=T("props.int_item.value"), default=0)


class JCNSHashItem(PropertyGroup):
    """A uint32 hash, held as a signed int, with the name it resolved to."""
    hash: IntProperty(name=T("props.hash_item.hash"), description=T("props.hash_item.hash_desc"), default=0)
    name: StringProperty(name=T("props.hash_item.name"), default="")


class JCNSWeightedSource(PropertyGroup):
    """One source bone of a MultiConstraint record."""
    bone: StringProperty(name=T("props.weighted.bone"), default="", update=_refresh_preview,
                         search=lambda self, context, text: _search_bone_names(context, text))
    weight: FloatProperty(name=T("props.weighted.weight"), default=1.0, precision=4, update=_refresh_preview_values)


class JCNSSourceProperties(PropertyGroup):
    """One driving source: one 72-byte JointDriver_v2 block."""

    source_bone: StringProperty(
        update=_refresh_preview,
        name=T("props.common.driver"),
        description=T("props.source.bone_desc"),
        default="",
        search=_search_source_bone,
        search_options={'SUGGESTION'},
    )
    source_axis: EnumProperty(
        update=_refresh_preview,
        name=T("props.source.axis"),
        description=T("props.source.axis_desc"),
        items=AXIS_ITEMS,
        default='X',
    )

    # --- Three-point piecewise mapping ---
    from_start: FloatProperty(
        update=_refresh_preview_values,
        name=T("props.source.from_start"), description=T("props.source.from_start_desc"),
        default=0.0, precision=2, step=10,
    )
    from_kink: FloatProperty(
        update=_refresh_preview_values,
        name=T("props.source.from_kink"), description=T("props.source.from_kink_desc"),
        default=0.0, precision=2, step=10,
    )
    from_end: FloatProperty(
        update=_refresh_preview_values,
        name=T("props.source.from_end"), description=T("props.source.from_end_desc"),
        default=0.0, precision=2, step=10,
    )
    to_start: FloatProperty(
        update=_refresh_preview_values,
        name=T("props.source.to_start"), description=T("props.source.to_start_desc"),
        default=0.0, precision=2, step=10,
    )
    to_kink: FloatProperty(
        update=_refresh_preview_values,
        name=T("props.source.to_kink"), description=T("props.source.to_kink_desc"),
        default=0.0, precision=2, step=10,
    )
    to_end: FloatProperty(
        update=_refresh_preview_values,
        name=T("props.source.to_end"), description=T("props.source.to_end_desc"),
        default=0.0, precision=2, step=10,
    )

    # --- Reference frame (+56, stored as "ref_frame") ---
    # Not the bone's rest pose (the engine takes that from the skeleton): the frame
    # the swing-twist and rotation-vector reads decompose in, f^-1 * q * f.
    ref_frame_x: FloatProperty(name=T("props.source.ref_frame_x"), default=0.0, precision=5,
                               update=_refresh_preview)
    ref_frame_y: FloatProperty(name=T("props.source.ref_frame_y"), default=0.0, precision=5,
                               update=_refresh_preview)
    ref_frame_z: FloatProperty(name=T("props.source.ref_frame_z"), default=0.0, precision=5,
                               update=_refresh_preview)
    ref_frame_w: FloatProperty(name=T("props.source.ref_frame_w"), default=1.0, precision=5,
                               update=_refresh_preview)

    # --- Raw bytes ---
    # +24 and +25 default to 3, the most common value.
    mid_point: BoolProperty(
        update=_refresh_preview_values,
        name=T("props.source.mid_point"),
        description=T("props.source.mid_point_desc"),
        default=True,
    )
    attr_flags_other: IntProperty(
        name=T("props.source.attr_flags_other"),
        description=T("props.source.attr_flags_other_desc"),
        default=1, min=0, max=253,
    )
    input_type: EnumProperty(
        update=_refresh_preview,
        name=T("props.source.input_type"),
        description=T("props.source.input_type_desc"),
        items=_INPUT_TYPE_ITEMS,
        default=_INPUT_TYPE_DEFAULT,
    )
    rot_order: EnumProperty(
        update=_refresh_preview,
        name=T("props.source.rot_order"),
        description=T("props.source.rot_order_desc"),
        items=_ROT_ORDER_ITEMS,
        default='XYZ',
    )
    complex_mapping_info_count: IntProperty(
        name=T("props.source.cm_count"), description=T("props.source.cm_count_desc"),
        default=0, min=0, max=65535,
    )
    unknown_uint16_22: IntProperty(
        name=T("props.source.unknown_uint16_22"), description=T("props.common.unknown_usually_0"),
        default=0, min=0, max=65535,
    )
    interpolation: EnumProperty(
        update=_refresh_preview_values,
        name=T("props.source.interpolation"),
        description=T("props.source.interpolation_desc"),
        items=INTERPOLATION_ITEMS, default='LINEAR',
    )
    curve_type: IntProperty(
        name=T("props.source.cm_flag"), description=T("props.source.cm_flag_desc"),
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
    """On every entry Empty: one 80-byte OutputData block plus its sources."""

    # Marks an entry Empty; set at import and by Add Constraint.
    is_jcns_constraint: BoolProperty(default=False)

    sources: CollectionProperty(type=JCNSSourceProperties)
    active_source_index: IntProperty(default=0)
    # Next ComplexMapping channel number (jcns_cm.fcurve); never reused.
    cm_next_id: IntProperty(default=0)

    # --- Identity ---
    target_bone: StringProperty(
        update=_refresh_preview,
        name=T("props.cns.target_bone"),
        description=T("props.cns.target_bone_desc"),
        default="",
        search=_search_output_target,
        search_options={'SUGGESTION'},
    )
    transform_element: EnumProperty(
        update=_refresh_preview,
        name=T("props.cns.transform_element"),
        description=T("props.cns.transform_element_desc"),
        items=TRANSFORM_ITEMS,
        default='Rot',
    )

    # --- Axis (editable — exported back to file) ---
    target_axis: EnumProperty(
        update=_refresh_preview,
        name=T("props.cns.target_axis"),
        description=T("props.cns.target_axis_desc"),
        items=AXIS_ITEMS,
        default='X',
    )

    # --- OutputData fields (editable, exported) ---
    base_pose: BoolProperty(
        name=T("props.cns.base_pose"),
        description=T("props.cns.base_pose_desc"),
        default=True, update=_update_base_pose,
    )
    attr_flags_other: IntProperty(
        name=T("props.cns.attr_flags_other"),
        description=T("props.cns.attr_flags_other_desc"),
        default=0x30, min=0, max=254,
    )
    reserved_vec4_x: FloatProperty(name="Vec4 X", default=0.0, precision=5, description=T("props.cns.vec4_zero_desc"))
    reserved_vec4_y: FloatProperty(name="Vec4 Y", default=0.0, precision=5, description=T("props.cns.vec4_zero_desc"))
    reserved_vec4_z: FloatProperty(name="Vec4 Z", default=0.0, precision=5, description=T("props.cns.vec4_zero_desc"))
    reserved_vec4_w: FloatProperty(name="Vec4 W", default=1.0, precision=5, description=T("props.cns.vec4_one_desc"))
    unknown_float2_x: FloatProperty(name="Float2 X", default=0.0, precision=5,
                                   description=T("props.common.unknown_usually_0"))
    unknown_float2_y: FloatProperty(name="Float2 Y", default=0.0, precision=5,
                                   description=T("props.common.unknown_usually_0"))
    unknown_byte_72: IntProperty(
        name=T("props.cns.unknown_byte_72"), description=T("props.cns.unknown_byte_72_desc"),
        default=0, min=0, max=255,
    )
    # Material / RSZ property targets (TransformElement 7-11) name a property on the target.
    target_property: StringProperty(
        name=T("props.cns.target_property"),
        description=T("props.cns.target_property_desc"),
        default="",
        search=_search_output_property,
        search_options={'SUGGESTION'},
    )
    # The two hashes below are overrides in a signed IntProperty (a uint32 above 2**31
    # is stored as its two's-complement negative); 0 derives the hash from the name.
    property_hash: IntProperty(
        name=T("props.cns.property_hash"),
        description=T("props.cns.property_hash_desc"),
        default=0,
    )
    object_hash: IntProperty(
        name=T("props.cns.object_hash"),
        description=T("props.cns.object_hash_desc"),
        default=0,
    )
    # ConeDriver[]: the cones this constraint reads (RE9 uses them heavily)
    cone_drivers: CollectionProperty(type=JCNSConeDriver)
    active_cone_driver_index: IntProperty(default=0)
    # +77 is the joint-group count (jcns_writer.tail_group_counts derives it); +74 and +75
    # are unknown, and +75 defaults to its most common value.
    unknown_byte_74: IntProperty(name="+74", default=0, min=0, max=255,
                                 description=T("props.cns.unknown_byte_74_desc"))
    unknown_byte_75: IntProperty(name="+75", default=2, min=0, max=255,
                                 description=T("props.cns.unknown_byte_75_desc"))
    group_count: IntProperty(
        name=T("props.cns.group_count"),
        description=T("props.cns.group_count_desc"),
        default=0, min=0, max=255)
    reserved_tail: IntVectorProperty(name=T("props.cns.reserved_tail"), size=3, default=(0, 0, 0), min=0, max=255,
                                     description=T("props.cns.reserved_tail_desc"))

    # --- Material constraint (MaterialConstraintData) ---
    # The file holds only the two hashes (murmur3 of the UTF-16 mdf2 material and
    # parameter names); a name, when known, is what they were computed from.
    mat_name: StringProperty(
        name=T("props.cns.mat_name"), description=T("props.cns.mat_name_desc"),
        default="", update=_update_mat_name,
        search=_search_mat_name, search_options={'SUGGESTION', 'SORT'},
    )
    mat_property: StringProperty(
        name=T("props.cns.mat_property"), description=T("props.cns.mat_property_desc"),
        default="", update=_update_mat_property,
        search=_search_mat_property, search_options={'SUGGESTION', 'SORT'},
    )
    mat_name_hash: StringProperty(
        name="MaterialNameHash",
        description=T("props.cns.mat_name_hash_desc"),
        default="0x00000000", update=_update_mat_name_hash,
    )
    mat_property_hash: StringProperty(
        name="MaterialPropertyHash",
        description=T("props.cns.mat_property_hash_desc"),
        default="0x00000000", update=_update_mat_property_hash,
    )
    mat_apply_mode: EnumProperty(
        name=T("props.cns.mat_apply_mode"), description=T("props.cns.mat_apply_mode_desc"),
        items=MAT_APPLY_MODE_ITEMS, default='TRANS',
    )
    mat_tail_0: IntProperty(name="MatTail[0]", default=0, min=0, max=255)
    mat_tail_1: IntProperty(name="MatTail[1]", default=0, min=0, max=255)
    mat_tail_2: IntProperty(name="MatTail[2]", default=0, min=0, max=255)

    # --- MultiConstraint (target_bone is the skinned object) ---
    multi_sources: CollectionProperty(type=JCNSWeightedSource)
    active_multi_source_index: IntProperty(default=0)
    multi_tail: IntVectorProperty(
        name=T("props.cns.multi_tail"), size=2, default=(0, 0), min=0, max=255,
        description=T("props.cns.multi_tail_desc"))

    # --- Aim (target_bone is the aimed joint) ---
    aim_target_bone: StringProperty(name=T("props.cns.aim_target_bone"), default="", update=_refresh_preview,
                                    search=_search_target_bone)
    aim_up_bone: StringProperty(name=T("props.cns.aim_up_bone"), description=T("props.cns.aim_up_bone_desc"),
                                default="", update=_refresh_preview, search=_search_target_bone)
    aim_influence: FloatProperty(name=T("props.cns.aim_influence"), default=1.0, update=_refresh_preview_values)
    aim_target2_bone: StringProperty(name=T("props.cns.aim_target2_bone"), description=T("props.cns.aim_target2_bone_desc"),
                                     default="", update=_refresh_preview, search=_search_target_bone)
    aim_weight2: FloatProperty(name=T("props.cns.aim_weight2"), default=0.5)
    aim_offset: FloatVectorProperty(name=T("props.cns.aim_offset"), size=3, default=(0.0, 0.0, 0.0), subtype='EULER',
                                    description=T("props.cns.aim_offset_desc"),
                                    update=_refresh_preview)
    aim_axis: FloatVectorProperty(name=T("props.cns.aim_axis"), size=3, default=(1.0, 0.0, 0.0),
                                  description=T("props.cns.aim_axis_desc"),
                                  update=_refresh_preview_values)
    aim_up_axis: FloatVectorProperty(name=T("props.cns.aim_up_axis"), size=3, default=(0.0, 1.0, 0.0),
                                     description=T("props.cns.aim_up_axis_desc"))
    aim_up_dir: FloatVectorProperty(name=T("props.cns.aim_up_dir"), size=3, default=(0.0, 1.0, 0.0),
                                    description=T("props.cns.aim_up_dir_desc"))
    world_up_type: EnumProperty(name=T("props.cns.world_up_type"), items=WORLD_UP_TYPE_ITEMS, default='SCENE_UP',
                           update=_refresh_preview)
    aim_bytes: IntVectorProperty(name=T("props.cns.aim_bytes"), size=2, default=(0, 5), min=0, max=255)

    # --- RotExpression (target_bone is the driven joint) ---
    rot_source_bone: StringProperty(name=T("props.common.driver"), default="", update=_refresh_preview,
                                    search=_search_target_bone)
    rot_rotation: FloatVectorProperty(name="Rotation", size=4, default=(0.0, 0.0, 0.0, 1.0))
    rot_scale: FloatVectorProperty(name="Scale", size=4, default=(0.0, 0.0, 0.0, 1.0))
    rot_rest_mode: EnumProperty(name=T("props.cns.rot_rest_mode"), items=ROT_REST_ITEMS, default='REPLACE')
    rot_unknown_bytes: IntVectorProperty(name=T("props.cns.rot_unknown_bytes"), size=3, default=(0, 0, 0), min=0, max=255)
    rot_gains: FloatVectorProperty(name=T("props.cns.rot_gains"), size=3, default=(1.0, 1.0, 1.0),
                                   description=T("props.cns.rot_gains_desc"),
                                   update=_refresh_preview_values)

    # --- Section type (set at import, read-only in UI) ---
    constraint_type: StringProperty(
        name="Constraint Type",
        description="Section type from the JCNS file (e.g. 'Outputs', 'Aim', 'Multi'…)",
        default='Outputs',
    )

    # --- Driver state (runtime, not exported) ---
    preview_on: BoolProperty(
        name=T("props.cns.preview_on"),
        description=T("props.cns.preview_on_desc"),
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
    from .jcns_exporter import _root_version, root_write_mode
    v = _root_version(rp)
    return get_kinds().FileState(
        version=v,
        rebuild=root_write_mode(rp) == 'rebuild',
        sections_cached=bool(rp.sections_cached),
        has_armature=rp.target_armature is not None,
        has_read_table=bool(rp.read_joint_signature_json) or rp.read_table_pending,
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


class JCNSMdfRef(PropertyGroup):
    """A reference .mdf2 whose material and parameter names the Material entries pick from."""
    filepath: StringProperty(name=T("props.mdf_ref.filepath"), description=T("props.mdf_ref.filepath_desc"),
                             subtype='FILE_PATH', default="", update=_update_mdf_ref)
    status: StringProperty(default="")           # why the file could not be read
    material_count: IntProperty(default=0)


class JCNSRootProperties(PropertyGroup):
    """On the root Empty of a JCNS collection (one root plus N entry Empties)."""
    # Constraint baking (jcns_sdk_ops.py)
    sdk_driver_bone: StringProperty(
        name=T("props.common.driver"), description=T("props.root.sdk_driver_bone_desc"),
        default="", search=search_bones, search_options={'SUGGESTION'},
    )
    sdk_driven_bones: CollectionProperty(type=JCNSSDKBone)
    sdk_driven_index: IntProperty(default=0)
    sdk_keys: CollectionProperty(type=JCNSSDKKey)
    sdk_key_index: IntProperty(default=0)
    # Reference .mdf2 files for the Material entries, and what they hold
    mdf_refs: CollectionProperty(type=JCNSMdfRef)
    mdf_ref_index: IntProperty(default=0)
    mdf_catalog_json: StringProperty(default="")
    # JointExprGraph (section 5): one path per file; empty = no JXG section
    jxg_path: StringProperty(
        name=T("props.root.jxg_path"), description=T("props.root.jxg_path_desc"), default="",
    )
    source_filepath: StringProperty(
        name=T("props.root.source_filepath"),
        description=T("props.root.source_filepath_desc"),
        subtype='FILE_PATH',
        default="",
    )
    target_armature: PointerProperty(
        name=T("props.root.target_armature"),
        description=T("props.root.target_armature_desc"),
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
        name=T("props.root.header_unknown_bytes"), size=2, default=(0, 0), min=0, max=255,
        description=T("props.root.header_unknown_bytes_desc"))
    hash_list: CollectionProperty(type=JCNSHashItem)
    # Combining is fixed engine behaviour, so there is no setting for it: sources
    # in one constraint are summed; of several constraints on one channel the
    # last in file order wins.
    source_version: IntProperty(
        name=T("props.root.source_version"),
        description="Version number of the imported file (the .jcns.<N> suffix); 0 = imported by an older add-on",
        default=0,
    )
    # Set by importers that store Multi / Aim / RotExpression / ComplexMapping in
    # Blender.  When False, the exporter takes those sections from the re-parsed
    # source file, since the Empties hold no data.
    sections_cached: BoolProperty(default=False)
    # Browser state (UI only)
    browser_kind: EnumProperty(
        name=T("props.root.browser_kind"), description=T("props.root.browser_kind_desc"),
        items=_browser_kind_items(), default='Outputs',
    )
    browser_view: EnumProperty(
        name=T("props.root.browser_view"), description=T("props.root.browser_view_desc"),
        items=[('ENTRY', T("props.root.view_entry"), T("props.root.view_entry_desc")),
               ('BONE', T("props.root.view_bone"), T("props.root.view_bone_desc"))],
        default='ENTRY',
    )
    entry_index: IntProperty(
        name=T("props.root.entry_index"), description=T("props.root.entry_index_desc"),
        get=_entry_index_get, set=_entry_index_set,
    )
    file_constant: IntProperty(default=5)
    # ReadJointTable: the joints Multi and Aim read, in file order (see jcns_sections).
    read_joint_table: CollectionProperty(type=JCNSHashItem)
    read_joint_index: IntProperty(default=0)
    read_joint_signature_json: StringProperty(default="")
    # The file was upgraded from this version on import (0 = it was not); the source file is
    # no longer what gets exported.
    upgraded_from: IntProperty(default=0)
    # The upgraded version has a ReadJointTable the source never had: derived on export.
    read_table_pending: BoolProperty(default=False)
    # The version is rebuilt, but this file has a section or byte the rebuild does not carry, so it
    # is written in place (see jcns_parser.write_mode).
    rebuild_blocked: BoolProperty(default=False)
    # The RotExpressionMap value shared by every RotExpression entry.
    rot_map_value: IntProperty(
        name=T("props.root.rot_map_value"), default=0, min=0, max=255,
        description=T("props.root.rot_map_value_desc"))
    object_settings_json: StringProperty(default="")
    # The ConeInput table ConeDrivers index into; editable when the file is rebuilt.
    cone_inputs: CollectionProperty(type=JCNSConeInput)
    active_cone_input_index: IntProperty(default=0, update=_redraw_cones)
    draw_cones: BoolProperty(name=T("props.root.draw_cones"), description=T("props.root.draw_cones_desc"),
                             default=False, update=_redraw_cones)
    # Read only when source_version is 0 (see jcns_exporter._root_version).
    detected_game: EnumProperty(
        name=T("props.root.detected_game"),
        description="Game this JCNS file belongs to (detected at import)",
        items=[
            ('MHW_WILDS', T("props.root.game_wilds"), T("props.root.game_wilds_desc")),
            ('RE9',       T("props.root.game_re9"), "Resident Evil 9 / PRAGMATA"),
        ],
        default='MHW_WILDS',
    )


# ---------------------------------------------------------------------------
# Helpers: classify active object
# ---------------------------------------------------------------------------

def is_jcns_root_props(props):
    """A root Empty has a source path, or (a file made in Blender, not saved yet) a version."""
    return bool(props and (props.source_filepath or props.source_version))


def get_jcns_root(context):
    """Return (obj, jcns_root_props) if active object is a JCNS root Empty, else (None, None)."""
    obj = context.active_object
    if obj is None:
        return None, None
    props = getattr(obj, 'jcns_root_props', None)
    if is_jcns_root_props(props):
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
        if is_jcns_root_props(root_props):
            return parent, root_props

    # Fallback: flat collection search (legacy imports without parent-child hierarchy)
    for coll in constraint_empty.users_collection:
        for obj in coll.objects:
            if obj == constraint_empty:
                continue
            root_props = getattr(obj, 'jcns_root_props', None)
            if is_jcns_root_props(root_props):
                return obj, root_props
    return None, None


def get_jcns_root_from_collection(collection):
    """The JCNS root Empty inside a Collection (one per import), or (None, None)."""
    if collection is None:
        return None, None
    for obj in collection.objects:
        root_props = getattr(obj, 'jcns_root_props', None)
        if is_jcns_root_props(root_props):
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
        return p and (p.constraint_type == 'Outputs' or p.constraint_type == '')

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

    Several OutputData blocks can drive the same channel, and Blender allows
    one driver per F-Curve channel, so constraints sharing a key are built as a
    single driver.
    """
    return (cns_props.target_bone, cns_props.transform_element, cns_props.target_axis)


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
        len(props.cone_drivers),
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

from . import jcns_lang
from . import jcns_operators
from . import jcns_importer
from . import jcns_exporter
from . import jcns_ui
from . import jcns_editors
from . import jcns_drivers
from . import jcns_preview
from . import jcns_capture
from . import jcns_cone_draw
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
    JCNSConeInput,
    JCNSConeDriver,
    JCNSWeightedSource,
    JCNSSourceProperties,
    JCNSConstraintProperties,
    JCNSSDKSnapshot,
    JCNSSDKKey,
    JCNSSDKBone,
    JCNSMdfRef,
    JCNSRootProperties,
]


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)

    bpy.types.Object.jcns_root_props = PointerProperty(type=JCNSRootProperties)
    bpy.types.Object.jcns_cns_props  = PointerProperty(type=JCNSConstraintProperties)
    bpy.types.Scene.jcns_active_collection = PointerProperty(
        type=bpy.types.Collection,
        name=T("props.scene.active_collection"),
        description=T("props.scene.active_collection_desc"),
        poll=_poll_jcns_collection,
    )

    jcns_lang.register()
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
    jcns_cone_draw.register()


def unregister():
    jcns_cone_draw.unregister()
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
    jcns_lang.unregister()

    del bpy.types.Scene.jcns_active_collection
    del bpy.types.Object.jcns_cns_props
    del bpy.types.Object.jcns_root_props

    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
