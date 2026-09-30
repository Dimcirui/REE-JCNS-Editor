"""
mesh_joints.py
--------------
Read just the skeleton out of an RE Engine .mesh file: joint names, parents,
and the mirror partner the engine itself records for every joint.

Only the bones section and the name table are touched, so this needs none of
the vertex/meshlet decoding a full mesh reader does.  Layout follows REasy's
`file_handlers/mesh/mesh_file.py` (seifhassine/REasy).

Header layouts come in three families, told apart by the internal version at
+4.  Each lists the offsets of the three fields read here:

    family   games                          name_count  bones  bone_idx  names
    A        RE7, DMC5, RE8, RE2/3/7 RT          +18      +48     +104    +120
    B        RE4, SF6                            +20     +104     +120    +144
    B2       DD2, Kunitsugami                    +20     +104     +120    +136
    C        Onimusha, MH Wilds, Pragmata, RE9   +20     +120     +136    +152

Bones section: joint_count i32, remap_count i32, 2 x i32, then four u64
offsets (hierarchy, local, world, inverse-bind matrices).  A hierarchy record
is 16 bytes: index, parent, sibling, child, symmetry (all i16), one u8, five
reserved.  A joint's name is names[bone_idx[joint]].

No `bpy` import, so it stays testable without Blender.
"""

import struct

MESH_MAGIC = 0x4853454D   # 'MESH'
MPLY_MAGIC = 0x594C504D   # 'MPLY', the meshlet variant — same header offsets

# (name_count, bones, bone_indices, name_offsets)
_LAYOUTS = {
    'A':  (18, 48, 104, 120),
    'B':  (20, 104, 120, 144),
    'B2': (20, 104, 120, 136),
    'C':  (20, 120, 136, 152),
}

# Internal version -> layout family, from REasy's MESH_VERSION_PAIRS.  The
# file-extension version is not needed: every internal version seen so far
# maps to one family.
_FAMILY = {
    352921600: 'A',                                   # RE7
    386270720: 'A', 21011200: 'A',                    # DMC5
    21041600: 'A', 21061800: 'A', 21091000: 'A',      # RE2/3/7 RT
    2020091500: 'A',                                  # RE8
    220822879: 'B',                                   # RE4
    220705151: 'B', 230403828: 'B',                   # SF6
    230517984: 'B2',                                  # DD2
    230727984: 'B2',                                  # Kunitsugami
    240704828: 'C', 240827123: 'C',                   # Onimusha, MH Wilds
    250203152: 'C', 250707828: 'C',                   # Pragmata
    250904410: 'C',                                   # RE9
}


class MeshJointError(ValueError):
    pass


def _u16(d, o):
    return struct.unpack_from('<H', d, o)[0]


def _i16(d, o):
    return struct.unpack_from('<h', d, o)[0]


def _i32(d, o):
    return struct.unpack_from('<i', d, o)[0]


def _u64(d, o):
    return struct.unpack_from('<Q', d, o)[0]


def _cstring(d, o):
    end = d.find(b'\0', o)
    if end < 0:
        raise MeshJointError("unterminated name at 0x%X" % o)
    return d[o:end].decode('utf-8')


def _read_with(data, family):
    n_off, b_off, i_off, s_off = _LAYOUTS[family]
    size = len(data)
    name_count = _u16(data, n_off)
    bones = _u64(data, b_off)
    if not bones:
        return []                     # a static mesh: no skeleton at all
    bone_idx = _u64(data, i_off)
    names_at = _u64(data, s_off)
    if not (0 < bones < size and 0 < bone_idx < size and 0 < names_at < size):
        raise MeshJointError("section offsets out of range")

    count = _i32(data, bones)
    hierarchy = _u64(data, bones + 16)
    if not (0 < count <= 4096) or hierarchy + 16 * count > size:
        raise MeshJointError("implausible joint count %d" % count)
    if bone_idx + 2 * count > size or names_at + 8 * name_count > size:
        raise MeshJointError("bone name table out of range")

    names = [_cstring(data, _u64(data, names_at + 8 * i))
             for i in range(name_count)]
    joints = []
    for j in range(count):
        rec = hierarchy + 16 * j
        ni = _u16(data, bone_idx + 2 * j)
        if ni >= len(names):
            raise MeshJointError("joint %d names entry %d of %d"
                                 % (j, ni, len(names)))
        joints.append({
            'name': names[ni],
            'index': _i16(data, rec),
            'parent': _i16(data, rec + 2),
            'symmetry': _i16(data, rec + 8),
        })
    for j, jt in enumerate(joints):
        if jt['index'] != j or not (-1 <= jt['symmetry'] < count):
            raise MeshJointError("hierarchy record %d is inconsistent" % j)
    return joints


def read_joints(data):
    """Joints of a mesh as dicts: name, index, parent, symmetry.

    An unknown internal version is tried against every layout and accepted
    only when exactly the hierarchy checks out, so a new game fails loudly
    instead of returning plausible garbage.
    """
    data = bytes(data)
    if len(data) < 160 or struct.unpack_from('<I', data, 0)[0] not in (
            MESH_MAGIC, MPLY_MAGIC):
        raise MeshJointError("not a .mesh file")
    version = struct.unpack_from('<I', data, 4)[0]
    family = _FAMILY.get(version)
    if family:
        return _read_with(data, family)
    found = []
    for fam in _LAYOUTS:
        try:
            found.append(_read_with(data, fam))
        except (MeshJointError, struct.error, UnicodeDecodeError):
            pass
    if len(found) != 1:
        raise MeshJointError("unknown mesh version %d" % version)
    return found[0]


def symmetry_map(joints):
    """name -> mirror partner's name, for joints whose partner is another joint.

    Centre-line joints point at themselves and are left out, so a lookup miss
    means "no partner recorded", never "partner is itself".
    """
    out = {}
    for jt in joints:
        s = jt['symmetry']
        if 0 <= s < len(joints) and s != jt['index']:
            out[jt['name']] = joints[s]['name']
    return out


def read_symmetry_file(path):
    with open(path, 'rb') as f:
        return symmetry_map(read_joints(f.read()))
