"""
Declarative, version-aware layouts for every JCNS record the editor touches.

Each record is a list of named fields in file order; a field may carry a version
predicate, so one declaration covers every RE Engine release.

Invariant (checked by tests/test_versions.py):
    pack(read(data, off, v), v) == data[off:off + size(v)]
so unknown bytes are fields too, named `Unk*` and carried verbatim.  A version
outside VERIFIED_VERSIONS is guarded by check_header_layout().

No bpy import.
"""

import struct

from jcns_i18n import T


# ── Version predicates ─────────────────────────────────────────────────────

def since(v):
    return lambda ver: ver >= v


def before(v):
    return lambda ver: ver < v


def between(lo, hi):
    """lo <= ver < hi"""
    return lambda ver: lo <= ver < hi


def any_of(*preds):
    return lambda ver: any(p(ver) for p in preds)


def only(*versions):
    s = frozenset(versions)
    return lambda ver: ver in s


# ── Field / Struct ─────────────────────────────────────────────────────────

class F:
    """One field.  `fmt` is a struct format without byte order: 'B', 'H', 'I',
    'i', 'Q', 'f', '4f' (tuple), or 'Ns' (raw bytes)."""

    __slots__ = ('name', 'fmt', 'when', 'size', 'count')

    def __init__(self, name, fmt, when=None):
        self.name = name
        self.fmt = fmt
        self.when = when
        self.size = struct.calcsize('<' + fmt)
        # Multi-value numeric fields ('4f') unpack to a tuple; 's' stays bytes.
        self.count = 1 if fmt.endswith('s') else len(struct.unpack('<' + fmt, bytes(self.size)))

    def present(self, version):
        return self.when is None or self.when(version)

    def default(self):
        if self.fmt.endswith('s'):
            return bytes(self.size)
        return tuple([0] * self.count) if self.count > 1 else 0


class Struct:
    def __init__(self, name, fields, align=1):
        self.name = name
        self.fields = fields
        self.align = align
        self._cache = {}

    def layout(self, version):
        """[(field, offset)] for the fields present in `version`, and the size."""
        hit = self._cache.get(version)
        if hit is None:
            off, out = 0, []
            for f in self.fields:
                if f.present(version):
                    out.append((f, off))
                    off += f.size
            if self.align > 1 and off % self.align:
                off += self.align - off % self.align
            hit = (out, off)
            self._cache[version] = hit
        return hit

    def size(self, version):
        return self.layout(version)[1]

    def has(self, name, version):
        return any(f.name == name for f, _ in self.layout(version)[0])

    def offset_of(self, name, version):
        for f, off in self.layout(version)[0]:
            if f.name == name:
                return off
        raise KeyError(f"{self.name} v{version} has no field {name!r}")

    def fmt_of(self, name, version):
        for f, _ in self.layout(version)[0]:
            if f.name == name:
                return '<' + f.fmt
        raise KeyError(f"{self.name} v{version} has no field {name!r}")

    def read(self, data, base, version):
        fields, size = self.layout(version)
        if base < 0 or base + size > len(data):
            raise ValueError(f"{self.name} v{version} at 0x{base:X} runs past EOF "
                             f"(needs {size} bytes, file is {len(data)})")
        rec = {}
        for f, off in fields:
            vals = struct.unpack_from('<' + f.fmt, data, base + off)
            rec[f.name] = vals[0] if f.count == 1 else vals
        return rec

    def pack_into(self, buf, base, rec, version):
        """Write `rec` over buf[base:base+size]; fields missing from rec keep the
        bytes already in buf (so a partial dict patches only what it names)."""
        fields, _ = self.layout(version)
        for f, off in fields:
            if f.name not in rec:
                continue
            v = rec[f.name]
            if f.count == 1:
                struct.pack_into('<' + f.fmt, buf, base + off, v)
            else:
                struct.pack_into('<' + f.fmt, buf, base + off, *v)

    def pack(self, rec, version):
        """Serialize `rec`; absent fields are zero."""
        buf = bytearray(self.size(version))
        full = {f.name: f.default() for f, _ in self.layout(version)[0]}
        full.update({k: v for k, v in rec.items() if k in full})
        self.pack_into(buf, 0, full, version)
        return bytes(buf)


# ── Known versions ─────────────────────────────────────────────────────────

VERSION_GAMES = {
    11:  "RE2 / DMC5",
    12:  "RE3",
    16:  "RE8",
    19:  T("core.schema.game_19"),
    21:  "MH Rise",
    22:  "RE4 / SF6",
    24:  "DD2",
    29:  T("core.schema.game_29"),
    35:  "RE9 / PRAGMATA / MH Stories 3",
    36:  "Onimusha: Way of the Sword",
    102: T("core.schema.game_102"),
}
SUPPORTED_VERSIONS = tuple(sorted(VERSION_GAMES))

# Versions whose layout round-trips real files with every stored hash matching
# its name.  The others are laid out from the templates alone.
VERIFIED_VERSIONS = frozenset({22, 29, 35, 36, 102})

# For Blender's file browser / drag-and-drop handler.
FILE_GLOB = ';'.join(f'*.jcns.{v}' for v in SUPPORTED_VERSIONS)
FILE_EXTENSIONS = ';'.join(f'.{v}' for v in SUPPORTED_VERSIONS)


# ── Header ("DataInfo" table at Tags.DataEntry, normally 0x50) ─────────────
# v12 has MultiConstraintSource{Entry,Count} and no Aim; Dependency fields start
# at v21; ReadJointTable fields start at v36.

_has_multi_src = any_of(since(29), only(12))

HEADER = Struct('Header', [
    F('ConeInputTableEntry',                'Q'),
    F('OutputEntry',                 'Q'),
    F('ObjectSettingEntry',                  'Q'),
    F('RotExpressionInfoEntry',              'Q'),
    F('RotExpressionMapEntry',               'Q'),
    F('RotExpressionSourceHashIndicesEntry', 'Q', since(35)),
    F('RotExpressionHashIndicesEntry',       'Q', since(35)),
    F('MultiConstraintTableEntry',            'Q'),
    F('MultiConstraintSourceTableEntry',      'Q', _has_multi_src),
    F('AimConstraintTableEntry',             'Q', since(16)),
    F('MaterialConstraintInfoEntry',         'Q', since(22)),
    F('JointExprGraphInfoEntry',           'Q', since(29)),
    F('SectionTableEntry',                   'Q', since(16)),
    F('DependencyTableEntry',                'Q', since(21)),
    F('HashListOffset',                      'Q', since(35)),
    F('ReadJointTableEntry',                 'Q', since(36)),

    F('HashCount',                           'i', since(35)),
    F('ConeInputCount',                     'H'),
    F('OutputCount',                     'H'),
    F('DependencyCount',                     'H', since(21)),
    F('ObjectSettingCount',                  'H'),
    F('RotExpressionInfoCount',              'H'),
    F('RotExpressionMapCount',               'H'),
    F('MultiConstraintCount',                 'H'),
    F('ReadJointTableItemCount',             'H', since(36)),
    F('MultiConstraintSourceCount',           'H', _has_multi_src),
    F('AimConstraintCount',                  'H', since(16)),
    F('MaterialConstraintInfoCount',         'H', since(22)),
    F('HeaderUnknownUInt16',                 'H', between(35, 102)),
    F('SectionCount',                        'B', since(29)),
    # Two flag bytes after SectionCount (0 or 1; not tied to any section) with a zero between.
    F('HeaderUnknownByte1',                  'B', since(29)),
    F('HeaderReserved',                      'B', since(29)),
    F('HeaderUnknownByte2',                  'B', since(29)),
], align=16)

HEADER_POINTERS = [f.name for f in HEADER.fields if f.fmt == 'Q']

# Every file's bytes [4:0x50] after the version: the magic, then the Tags block, whose
# last real entry points at the DataInfo table at 0x50.
_TAGS = struct.pack('<4s9Q', b'jcns', 0, 0x30, 0, 0x40, 1, 15, 0, 0x50, 0)


def file_header(version, unknown_bytes=(0, 0)):
    """The Tags block and a DataInfo table that is zero but for the two unknown flag bytes: the
    file header before the writer fills in pointers and counts."""
    head = bytearray(struct.pack('<I', version) + _TAGS + bytes(HEADER.size(version)))
    if HEADER.has('HeaderUnknownByte1', version):
        HEADER.pack_into(head, 0x50, {'HeaderUnknownByte1': unknown_bytes[0],
                                      'HeaderUnknownByte2': unknown_bytes[1]}, version)
    return bytes(head)


def check_header_layout(header, version, data_entry):
    """Return '' if the parsed header is self-consistent, else a reason.

    The data table begins right after the header (the ConeInput table comes
    first and, when empty, shares its offset with OutputData), so the
    header's computed end must equal ConeInputTableEntry.  A wrong field list
    for a version shifts that end.
    """
    end = data_entry + HEADER.size(version)
    cd = header.get('ConeInputTableEntry', 0)
    if cd != end:
        return T("core.schema.header_layout", version, end, cd)
    return ''


def section_count(header, version):
    """Number of uint32 entries in the section table (fixed before v29)."""
    if version >= 29:
        return header.get('SectionCount', 0)
    if version >= 22:
        return 5
    if version >= 16:
        return 4
    return 0


# Section ids in the section table: 0 Ranges, 1 RotExpression, 2 Multi, 3 Aim,
# 4 Material, 5 JointExportGraph.  The engine runs only the sections listed.
SECTION_APPEND_ORDER = (1, 3, 2, 0, 4, 5)


def reconcile_section_table(table, present):
    """Section table that lists exactly the sections in `present` (a set of ids).

    Entries already in `table` keep their order (ids this add-on does not know are
    kept too); missing ones are appended in SECTION_APPEND_ORDER.
    """
    known = set(SECTION_APPEND_ORDER)
    out = [s for s in table if s not in known or s in present]
    out += [s for s in SECTION_APPEND_ORDER if s in present and s not in out]
    return out


# ── OutputData (Section 0) ─────────────────────────────────────────────
# 80 bytes from v21, 64 at v16/v19, 56 at v11/v12.  Before v35 there is no
# hash-table index, the AttrFlags byte is an unnamed byte, and TransformAxis sits in
# the first byte block instead of the tail.

OUTPUT_DATA = Struct('OutputData', [
    F('ConeDriverOffset',  'Q'),
    F('SourceListOffset',         'Q'),              # -> JointDriver[SourceCount]
    F('ObjectNameOffset',  'Q'),
    F('PropertyOffset',        'Q', since(13)),
    F('ObjectHashIndex',       'I', since(35)),
    F('ObjectHash',            'I'),
    F('PropertyHash',          'I', since(13)),
    F('UnknownUInt32_v1',      'I', before(13)),
    F('ConeDriverCount',   'B'),
    F('JointDriverCount',    'B'),
    # v35+: AttrFlags, TransformElement
    F('AttrFlags',                 'B', since(35)),
    # pre-v35: Unk, TransformElement, Unk, TransformAxis, Unk, Unk
    F('UnkByte_Pre35_0',       'B', before(35)),
    F('TransformElement',         'B'),
    F('UnkByte_Pre35_2',       'B', before(35)),
    F('Axis_pre35',   'B', before(35)),
    F('UnkBytes_Pre35_4',      '2s', before(35)),
    F('ReservedVec4',            '4f'),
    F('UnknownFloat2',          '2f', since(21)),
    F('UnknownByte72',        'B', since(21)),
    F('Axis_v35',     'B', since(35)),
    F('UnkByte_Pre35_73',      'B', between(21, 35)),
    F('TailBytes',       '6s', since(21)),
])


def output_axis_key(version):
    return 'Axis_v35' if version >= 35 else 'Axis_pre35'


# ── OutputData before v35 <-> the neutral record ──────────────────────
# The editor holds every version as the v35+ record.  Before v35 the same bytes sit elsewhere:
#   AttrFlags              <- the first byte block's first byte
#   UnknownByte72      <- its third byte (the +72 byte itself is always 0)
#   TailBytes[0:2]     <- the +4 pair of the byte block
#   TailBytes[3]       <- the +73 byte (how many following entries join this one's joint group)
#   TailBytes[2,4,5]   <- the tail's own bytes 2, 4, 5 (its bytes 0, 1, 3 are always 0)
# Anything else is not carried: pre35_lossy() names it so the importer can refuse such a file.

def pre35_to_neutral(rec):
    """Neutral keys for a record read with a version before 35 (the raw keys stay)."""
    tail = bytearray(bytes(rec['UnkBytes_Pre35_4']) + bytes(rec['TailBytes'])[2:])
    tail[3] = rec['UnkByte_Pre35_73']
    return {'AttrFlags': rec['UnkByte_Pre35_0'], 'UnknownByte72': rec['UnkByte_Pre35_2'],
            'TailBytes': bytes(tail)}


def pre35_lossy(rec):
    """True when the record holds a byte the neutral form cannot carry."""
    tail = bytes(rec['TailBytes'])
    return bool(rec['UnknownByte72'] or tail[0] or tail[1] or tail[3])


def neutral_to_pre35(rec):
    """The version-before-35 fields for a neutral record."""
    tail = bytes(rec.get('TailBytes') or bytes(6))
    return {'UnkByte_Pre35_0': rec.get('AttrFlags', 0), 'UnkByte_Pre35_2': rec.get('UnknownByte72', 0),
            'UnkBytes_Pre35_4': tail[0:2], 'UnkByte_Pre35_73': tail[3],
            'UnknownByte72': 0, 'TailBytes': bytes([0, 0, tail[2], 0, tail[4], tail[5]])}


# ── JointDriver ───────────────────────────────────────────────────────
# v2 (v13+): 72 bytes; +16 is a hash-table index from v35, a raw hash before.
# v1 (v11/v12): 64 bytes; the ranges come before the byte block.  The byte block
# itself (two bytes, axis, five bytes) matches v2's +24..+31, so it reuses the
# v2 names.

JOINT_DRIVER_V2 = Struct('JointDriver_v2', [
    F('ComplexMappingInfoOffset', 'Q'),
    F('SourceName_Offset',        'Q'),
    F('SourceHashIndex',          'I', since(35)),
    F('SourceHash',               'I', before(35)),
    F('ComplexMappingInfoCount',  'H'),
    F('UnknownUInt16_22',            'H'),
    F('AttrFlags',                'B'),
    F('InputType',                 'B'),
    F('source_axis',              'B'),
    F('RotOrder',                 'B'),
    F('Interpolation',            'B'),               # +28: how each mapping segment runs
    F('CurveType',       'B'),               # +29: 1 exactly when the source has a ComplexMapping
    F('ReservedWord30',           'H'),               # +30: always 0
    F('from_start',  'f'), F('from_kink', 'f'), F('from_end', 'f'),
    F('to_start',    'f'), F('to_kink',   'f'), F('to_end',   'f'),
    F('ref_frame_x', 'f'), F('ref_frame_y', 'f'),
    F('ref_frame_z', 'f'), F('ref_frame_w', 'f'),
])

JOINT_DRIVER_V1 = Struct('JointDriver_v1', [
    F('SourceName_Offset',  'Q'),
    F('SourceHash',         'I'),
    F('from_start',  'f'), F('from_kink', 'f'), F('from_end', 'f'),
    F('to_start',    'f'), F('to_kink',   'f'), F('to_end',   'f'),
    F('AttrFlags',          'B'),
    F('InputType',           'B'),
    F('source_axis',        'B'),
    F('RotOrder',           'B'),
    F('Interpolation',      'B'),
    F('CurveType', 'B'),
    F('ReservedWord30',     'H'),
    F('ref_frame_x', 'f'), F('ref_frame_y', 'f'),
    F('ref_frame_z', 'f'), F('ref_frame_w', 'f'),
    F('UnknownDWORD_v1',    'I'),
])


def source_struct(version):
    return JOINT_DRIVER_V2 if version > 12 else JOINT_DRIVER_V1


def source_hash_key(version):
    return 'SourceHashIndex' if version >= 35 else 'SourceHash'


# ── Other sections ─────────────────────────────────────────────────────────

# Section 0 ConeDrivers (v35 layout).  A cone around a joint's direction:
# constraints read how far a joint has swung into it through their
# ConeDriver list, as an alternative to JointDriver ranges.  NameHash
# is murmur(Name), the joint fields are hash-list indices (SymmetryJoint -1 when
# unpaired), UnknownUInt32 is 0 and Tail is 06 06 00 {0,1} 00 00 00 00.
CONE_INPUT = Struct('ConeInput', [
    F('Name_Offset',            'Q'),
    F('Direction',              '4f'),
    F('Matrix',                 '12f'),          # matrix4x3
    F('NameHash',               'I'),
    F('JointHashIndex',         'i'),
    F('ParentJointHashIndex',   'i'),
    F('SymmetryJointHashIndex', 'i'),
    F('AngleRad',               'f'),
    F('UnknownUInt32',          'I'),
    F('Tail',                   '8s'),
])

# Before v35 a ConeInput names its joints by string and raw hash, not by hash-list index.
# v13-v23 carry a Translation vec4, v24+ the Matrix plus a symmetry joint.
CONE_INPUT_V1 = Struct('ConeInput_v1', [
    F('Name_Offset',            'Q'),
    F('JointName_Offset',       'Q'),
    F('ParentJointName_Offset', 'Q'),
    F('SymmetryJointName_Offset', 'Q', since(24)),
    F('Direction',              '4f'),
    F('Translation',            '4f', between(13, 24)),
    F('Matrix',                 '12f', since(24)),
    F('NameHash',               'I'),
    F('JointHash',              'I'),
    F('ParentJointHash',        'I'),
    F('SymmetryJointHash',      'I', since(24)),
    F('AngleRad',               'f'),
    F('UnknownUInt32',          'I', since(24)),
    F('Tail',                   '8s'),
])


def cone_struct(version):
    return CONE_INPUT if version >= 35 else CONE_INPUT_V1


# OutputData.ConeDriverOffset -> ConeDriver[ConeDriverCount].  Read off Wilds' native
# evaluator (docs/engine-names.md section 4): with CurveType 0 (MinMax) the entry takes
# OutMin + (OutMax - OutMin) * f(cone value), f picked by Interpolation (0 linear, 1-3
# polynomial eases), and an entry's cones combine by its OutputMode.  ConeInputIndex 255
# is no cone.  CurveData is only read with CurveType 1 (Function) and is 0 in every
# shipped file.  v22's OutMin / OutMax pair with OutputMode Min / Max as expected.
CONE_DRIVER = Struct('ConeDriver', [
    F('CurveData',       '12s', since(24)),
    F('OutMin',          'f'),                   # 1 on scale targets
    F('OutMax',          'f'),
    F('Interpolation',   'B'),                   # RE9 0 / 2, RE4 v22 3
    F('ConeInputIndex',  'B'),
    F('CurveType',       'B'),                   # 0 in every shipped file
    F('ReservedByte',    'B'),                   # always 0
])


AIM = Struct('ConstraintAim', [
    F('TargetInfoOffset',   'Q'),
    F('JointHashIndex',     'i', since(35)),
    F('UnkJointHashIndex',  'i', since(35)),
    F('JointHash',          'I', before(35)),
    F('UnkJointHash',       'I', before(35)),
    F('Body',               '64s'),               # 4 vec3 + WorldUpType + TargetCount + 14 bytes
])

AIM_TARGET = Struct('AimTargetInfo', [
    F('TargetHashIndex',    'i', since(35)),
    F('TargetHash',         'I', before(35)),
    F('Body',               '12s'),               # Weight, then a second (target, weight) or 8 zero bytes
])

MATERIAL = Struct('MatCnsInfo', [
    F('JointHashIndex',     'i', since(35)),
    F('JointHash',          'I', before(35)),
    F('Body',               '12s'),               # NameHash, PropertyHash, TransformID, 3 bytes
])

ROT_EXPRESSION = Struct('RotExpressionInfo', [
    F('Rotation',           '4f'),
    F('Scale',              '4f'),
    F('JointHash',          'I'),
    F('SourceJointHash',    'I'),
    F('Tail',               '16s'),
])

DEPENDENCY = Struct('DependencyInfo', [
    F('Offset',             'Q'),
    F('SourceCount',        'Q'),
])

# ComplexMappingInfo[ComplexMappingInfoCount], pointed to by a JointDriver_v2,
# placed 16-aligned right after the source's name strings.
COMPLEX_MAPPING = Struct('ComplexSrcMapping', [
    F('FromX', 'f'), F('ToX', 'f'),
    F('FromY', 'f'), F('ToY', 'f'),
    F('FromZ', 'f'), F('ToZ', 'f'),
    F('UnknownUInt32', 'I'),
])

# Section 0 ObjectSettings: 16-byte record + the hash its first field points to.
OBJECT_SETTING = Struct('ObjectSettings', [
    F('HashOffset',    'Q'),
    F('UnkBytes',      '4s'),
    F('UnknownDWORD',  'I'),
])

# Section 2.  One MultiConstraint per skinned object:
#   SourceListOffset -> MultiSource[SourceCount]  (8 bytes each)
# From v35 a MultiSource names a MultiSourceInfo (hash-table index + u32); v29-v34
# index a plain hash array instead; before v29 the hash is inline.
MULTI = Struct('MultiConstraint', [
    F('SourceListOffset', 'Q'),
    F('ObjectHashIndex',  'i', since(35)),
    F('ObjectHash',       'I', before(35)),
    F('SourceCount',      'B'),
    F('Tail',             '3s'),
])

MULTI_SOURCE = Struct('MultiSource', [
    F('SourceRef', 'I'),        # MultiSourceInfo index (v35+) / source-hash-array index (v29+) / hash
    F('Weight',    'f'),
])

MULTI_SOURCE_INFO = Struct('MultiSourceInfo', [
    F('SourceHashIndex', 'i', since(35)),
    F('UnknownUInt32',   'I', since(35)),
    F('SourceHash',      'I', between(29, 35)),
])
