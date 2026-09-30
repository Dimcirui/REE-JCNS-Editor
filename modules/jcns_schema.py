"""
jcns_schema.py
--------------
Declarative, version-aware layouts for every JCNS record the editor touches.

Instead of reading `data[+47]` or patching `0xB8` by hand, each record is a list
of named fields in file order.  A field may carry a version predicate, which is
how one declaration covers every RE Engine release (the same idea as ReeLib's
`ReadWrite` models and the EFX editor's schema tables):

    CONSTRAINT_INFO = Struct('ConstraintInfo', [
        F('ConeDriverInfoOffset', 'Q'),
        ...
        F('ObjectHashIndex', 'I', since(35)),
        F('ObjectHash',      'I'),
        ...
    ])

    rec  = CONSTRAINT_INFO.read(data, off, version)   # -> dict
    blob = CONSTRAINT_INFO.pack(rec, version)          # -> bytes

Invariant (checked by tests/test_versions.py over the shipped corpus):
    pack(read(data, off, v), v) == data[off:off + size(v)]
so unknown bytes are fields too — they are named `Unk*` and carried verbatim.

Sources for the layouts, in order of trust:
  1. real files (v22 RE4, v29/v102 MH Wilds, v35 RE9, v36 Onimusha — see tests/)
  2. the per-version header table of RE_Engine_JCNS.bt 0.65.13 (written out by
     hand for every game)
  3. RE_Engine_JCNS.bt 0.65.14 (unified `if (Version >= N)` rewrite) and ReeLib's
     JcnsFile.cs.
Where 2 and 3 disagree the header check in JCNSParser refuses the file rather
than guess — see `check_header_layout()`.

Kept free of any `bpy` import.
"""

import struct


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
    19:  "RE2/RE3/RE7 光追版",
    21:  "MH Rise",
    22:  "RE4 / SF6",
    24:  "DD2",
    29:  "MH Wilds（TU4 之前）",
    35:  "RE9 / PRAGMATA / MH Stories 3",
    36:  "Onimusha: Way of the Sword",
    102: "MH Wilds（TU4 之后）",
}
SUPPORTED_VERSIONS = tuple(sorted(VERSION_GAMES))

# Versions whose layout has been checked against real files (every record
# round-trips and every stored hash matches its name).  Anything else is parsed
# from the templates alone; check_header_layout() is the guard.
VERIFIED_VERSIONS = frozenset({22, 29, 35, 36, 102})

# For Blender's file browser / drag-and-drop handler.
FILE_GLOB = ';'.join(f'*.jcns.{v}' for v in SUPPORTED_VERSIONS)
FILE_EXTENSIONS = ';'.join(f'.{v}' for v in SUPPORTED_VERSIONS)


# ── Header ("DataInfo" table at Tags.DataEntry, normally 0x50) ─────────────
# 0.65.13 wrote this out per version; 0.65.14 and ReeLib unified it.  The only
# disagreements are resolved as follows (2-of-3, then real files):
#   * v12 has SkinConstraintSource{Entry,Count}, not Aim  (0.65.13 + ReeLib)
#   * DependencyCount / DependencyTableEntry start at v21  (0.65.13 + ReeLib;
#     0.65.14 has the count from v16)
#   * no ReadJointTableItemCount before v36   (v29 files; ReeLib
#     reads one from v29 and mis-assigns every later count)

_has_skin_src = any_of(since(29), only(12))

HEADER = Struct('Header', [
    F('ConeDriverTableEntry',                'Q'),
    F('ConstraintInfoEntry',                 'Q'),
    F('ObjectSettingEntry',                  'Q'),
    F('RotExpressionInfoEntry',              'Q'),
    F('RotExpressionMapEntry',               'Q'),
    F('RotExpressionSourceHashIndicesEntry', 'Q', since(35)),
    F('RotExpressionHashIndicesEntry',       'Q', since(35)),
    F('SkinConstraintTableEntry',            'Q'),
    F('SkinConstraintSourceTableEntry',      'Q', _has_skin_src),
    F('AimConstraintTableEntry',             'Q', since(16)),
    F('MaterialConstraintInfoEntry',         'Q', since(22)),
    F('JointExportGraphInfoEntry',           'Q', since(29)),
    F('SectionTableEntry',                   'Q', since(16)),
    F('DependencyTableEntry',                'Q', since(21)),
    F('HashListOffset',                      'Q', since(35)),
    F('ReadJointTableEntry',                 'Q', since(36)),   # bt / REE-Lib: SkinConstraintHashTable*

    F('HashCount',                           'i', since(35)),
    F('ConeDriverCount',                     'H'),
    F('ConstraintCount',                     'H'),
    F('DependencyCount',                     'H', since(21)),
    F('ObjectSettingCount',                  'H'),
    F('RotExpressionInfoCount',              'H'),
    F('RotExpressionMapCount',               'H'),
    F('SkinConstraintCount',                 'H'),
    F('ReadJointTableItemCount',             'H', since(36)),
    F('SkinConstraintSourceCount',           'H', _has_skin_src),
    F('AimConstraintCount',                  'H', since(16)),
    F('MaterialConstraintInfoCount',         'H', since(22)),
    F('HeaderUnknownUInt16',                 'H', between(35, 102)),
    F('SectionCount',                        'B', since(29)),
], align=16)

HEADER_POINTERS = [f.name for f in HEADER.fields if f.fmt == 'Q']


def check_header_layout(header, version, data_entry):
    """Return '' if the parsed header is self-consistent, else a reason.

    The data table begins right after the header in every file seen (the
    ConeDriver table comes first and, when empty, shares its offset with
    ConstraintInfo), so the header's own computed end must equal
    ConeDriverTableEntry.  A wrong field list for a version shifts that end,
    which makes this a cheap, reliable detector for the unverified versions.
    """
    end = data_entry + HEADER.size(version)
    cd = header.get('ConeDriverTableEntry', 0)
    if cd != end:
        return (f"v{version} 文件头布局与文件不符：按模板算出的表头结尾是 0x{end:X}，"
                f"但 ConeDriverTableEntry 指向 0x{cd:X}")
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


# ── ConstraintInfo (Section 0) ─────────────────────────────────────────────
# 80 bytes from v21, 64 at v16/v19, 56 at v11/v12.  Keys match what the importer
# and exporter already use.  Before v35 there is no hash-table index, the byte
# the newer format uses for Flags is an unnamed byte, and TransformAxis sits in
# the first byte block instead of the tail.

CONSTRAINT_INFO = Struct('ConstraintInfo', [
    F('ConeDriverInfoOffset',  'Q'),
    F('SourceListOffset',         'Q'),              # -> ConstraintSource[SourceCount]
    F('ObjectNameOffset',  'Q'),
    F('PropertyOffset',        'Q', since(13)),
    F('ObjectHashIndex',       'I', since(35)),
    F('ObjectHash',            'I'),
    F('PropertyHash',          'I', since(13)),
    F('UnknownUInt32_v1',      'I', before(13)),
    F('ConeDriverInfoCount',   'B'),
    F('SourceCount_parent',    'B'),
    # v35+: Flags, TransformType
    F('Flags',                 'B', since(35)),
    # pre-v35: Unk, TransformType, Unk, TransformAxis, Unk, Unk
    F('UnkByte_Pre35_0',       'B', before(35)),
    F('TransformType',         'B'),
    F('UnkByte_Pre35_2',       'B', before(35)),
    F('TransformAxis_pre35',   'B', before(35)),
    F('UnkBytes_Pre35_4',      '2s', before(35)),
    F('ParentVec4',            '4f'),
    F('ParentFloat2',          '2f', since(21)),
    F('ParentUInt8_72',        'B', since(21)),
    F('TransformAxis_v35',     'B', since(35)),
    F('UnkByte_Pre35_73',      'B', between(21, 35)),
    F('ParentTailBytes',       '6s', since(21)),
])


def transform_axis_key(version):
    return 'TransformAxis_v35' if version >= 35 else 'TransformAxis_pre35'


# ── ConstraintSource ───────────────────────────────────────────────────────
# v2 (v13+): 72 bytes; +16 is a hash-table index from v35, a raw hash before.
# v1 (v11/v12): 64 bytes; the ranges come before the byte block.  The byte block
# itself (two bytes, axis, five bytes) matches v2's +24..+31, so it reuses the
# v2 names.

SOURCE_V2 = Struct('ConstraintSource_v2', [
    F('ComplexMappingInfoOffset', 'Q'),
    F('SourceName_Offset',        'Q'),
    F('SourceHashIndex',          'I', since(35)),
    F('SourceHash',               'I', before(35)),
    F('ComplexMappingInfoCount',  'H'),
    F('UnknownUInt16',            'H'),
    F('CurveMode',                'B'),
    F('ReadMode',                 'B'),
    F('source_axis',              'B'),
    F('UnkByte2',                 'B'),
    F('UnknownUInt32_2',          'I'),
    F('from_start',  'f'), F('from_kink', 'f'), F('from_end', 'f'),
    F('to_start',    'f'), F('to_kink',   'f'), F('to_end',   'f'),
    F('rest_quat_x', 'f'), F('rest_quat_y', 'f'),
    F('rest_quat_z', 'f'), F('rest_quat_w', 'f'),
])

SOURCE_V1 = Struct('ConstraintSource_v1', [
    F('SourceName_Offset',  'Q'),
    F('SourceHash',         'I'),
    F('from_start',  'f'), F('from_kink', 'f'), F('from_end', 'f'),
    F('to_start',    'f'), F('to_kink',   'f'), F('to_end',   'f'),
    F('CurveMode',          'B'),
    F('ReadMode',           'B'),
    F('source_axis',        'B'),
    F('UnkByte2',           'B'),
    F('UnknownUInt32_2',    'I'),
    F('rest_quat_x', 'f'), F('rest_quat_y', 'f'),
    F('rest_quat_z', 'f'), F('rest_quat_w', 'f'),
    F('UnknownDWORD_v1',    'I'),
])


def source_struct(version):
    return SOURCE_V2 if version > 12 else SOURCE_V1


def source_hash_key(version):
    return 'SourceHashIndex' if version >= 35 else 'SourceHash'


# ── Other sections ─────────────────────────────────────────────────────────

# Section 0 ConeDrivers (v35 layout; bt ConeDriver_v2).  A cone around a joint's
# direction: constraints read how far a joint has swung into it through their
# ConeDriverInfo list, as an alternative to ConstraintSource ranges.  RE9 v35:
# 614 records in 10 of 12 files.  NameHash is murmur(Name) (614/614), the joint
# fields are hash-list indices (SymmetryJoint -1 when unpaired), UnknownUInt32
# is 0 and Tail is 06 06 00 {0,1} 00 00 00 00 in every one.
CONE_DRIVER = Struct('ConeDriver', [
    F('Name_Offset',            'Q'),
    F('Direction',              '4f'),
    F('Matrix',                 '12f'),          # matrix4x3 (ReeLib reads a 4x4 here)
    F('NameHash',               'I'),
    F('JointHashIndex',         'i'),
    F('ParentJointHashIndex',   'i'),
    F('SymmetryJointHashIndex', 'i'),
    F('AngleRad',               'f'),
    F('UnknownUInt32',          'I'),
    F('Tail',                   '8s'),
])

# ConstraintInfo.ConeDriverInfoOffset -> ConeDriverInfo[ConeDriverInfoCount].
# Rest is (0,0,0,0), or (0,0,0,1) on scale targets whose neutral value is 1
# (588 of 10512 in RE9); Value is what the target takes for that cone — bt calls
# it AngleDeg, but on scale targets it holds factors like 1.002 or 3.5.
CONE_DRIVER_INFO = Struct('ConeDriverInfo', [
    F('Rest0',           'f'),
    F('Rest123',         '3f', since(24)),
    F('Value',           'f'),
    F('UnkByte0',        'B'),                   # 0, or 2 in 30 of 10512
    F('ConeDriverIndex', 'H'),
    F('UnkByte3',        'B'),                   # always 0
])


AIM = Struct('ConstraintAim', [
    F('TargetInfoOffset',   'Q'),
    F('JointHashIndex',     'i', since(35)),
    F('UnkJointHashIndex',  'i', since(35)),      # bt: AimVectorPointJointHash
    F('JointHash',          'I', before(35)),
    F('UnkJointHash',       'I', before(35)),
    F('Body',               '64s'),               # 4 vec3 + RotationType + 15 bytes
])

AIM_TARGET = Struct('AimTargetInfo', [
    F('TargetHashIndex',    'i', since(35)),
    F('TargetHash',         'I', before(35)),
    F('Body',               '12s'),               # Influence + UnknownQWORD
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

# ComplexMappingInfo[ComplexMappingInfoCount], pointed to by a ConstraintSource_v2.
# Shipped files always place it 16-aligned right after the source's name strings.
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

# Section 2.  One ConstraintSkin per skinned object:
#   SourceListOffset -> SkinSource[SourceCount]  (8 bytes each)
# From v35 a SkinSource names a SkinSourceInfo (hash-table index + u32); v29-v34
# index a plain hash array instead; before v29 the hash is inline.
SKIN = Struct('ConstraintSkin', [
    F('SourceListOffset', 'Q'),
    F('ObjectHashIndex',  'i', since(35)),
    F('ObjectHash',       'I', before(35)),
    F('SourceCount',      'B'),
    F('Tail',             '3s'),
])

SKIN_SOURCE = Struct('SkinSource', [
    F('SourceRef', 'I'),        # SkinSourceInfo index (v35+) / source-hash-array index (v29+) / hash
    F('Weight',    'f'),
])

SKIN_SOURCE_INFO = Struct('ConstraintSkinSrcInfo', [
    F('SourceHashIndex', 'i', since(35)),
    F('UnknownUInt32',   'I', since(35)),
    F('SourceHash',      'I', between(29, 35)),
])
