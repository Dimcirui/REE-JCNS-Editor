import struct
import os
import sys

import jcns_schema as S
from jcns_schema import (
    HEADER, CONSTRAINT_INFO, AIM, AIM_TARGET, MATERIAL, ROT_EXPRESSION,
    SUPPORTED_VERSIONS, VERSION_GAMES, source_struct, transform_axis_key,
    check_header_layout,
)

# Versions the writer can rebuild from scratch (add / delete / rename).  Every
# other version is written back in place: each record is re-packed at its
# original offset, so values can change but the file's structure cannot.
FULL_REBUILD_VERSIONS = frozenset({102})


def write_mode(version):
    return 'rebuild' if version in FULL_REBUILD_VERSIONS else 'inplace'


def _hash_utf16(name):
    """MurmurHash3 of a UTF-16LE bone name, as RE Engine computes it."""
    hashing_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'hashing')
    if hashing_dir not in sys.path:
        sys.path.insert(0, hashing_dir)
    from mmh3.pymmh3 import hashUTF16
    return hashUTF16(name) & 0xFFFFFFFF


def read_header(data, check_layout=True):
    """Parse Version + the DataInfo table.  Returns the header dict.

    Raises ValueError for an unknown version or, with check_layout, a header whose
    layout does not fit the file (see jcns_schema.check_header_layout).  Only skip
    the check for headers this add-on assembled itself, never for a file read in."""
    version = struct.unpack_from('<I', data, 0)[0]
    if version not in SUPPORTED_VERSIONS:
        raise ValueError(f"不支持的 JCNS 版本：{version}（支持 {list(SUPPORTED_VERSIONS)}）")
    if data[4:8] != b'jcns':
        raise ValueError("不是 JCNS 文件（缺少 'jcns' 魔数）")
    file_entry = struct.unpack_from('<Q', data, 32)[0]
    if file_entry + 8 > len(data):
        raise ValueError(f"FileEntry pointer 0x{file_entry:X} exceeds file size {len(data)}")
    data_entry = struct.unpack_from('<Q', data, file_entry)[0]

    header = HEADER.read(data, data_entry, version)
    problem = check_header_layout(header, version, data_entry) if check_layout else ''
    if problem:
        raise ValueError(problem)
    header['Version'] = version
    header['DataEntry'] = data_entry
    header['HeaderEnd'] = data_entry + HEADER.size(version)
    header['ConstraintSetsStart'] = header['ConstraintInfoEntry']
    header['ConstraintSetSize'] = CONSTRAINT_INFO.size(version)
    header['SectionTableItemCount'] = S.section_count(header, version)
    return header


def header_field_offset(header, name):
    """Absolute file offset of header field `name` (KeyError if absent in this version)."""
    return header['DataEntry'] + HEADER.offset_of(name, header['Version'])


class JCNSParser:
    """
    Parser for RE Engine JCNS files, every version in jcns_schema.VERSION_GAMES.

    Record layouts are declared in jcns_schema; nothing here reads a raw offset.
    The notes below describe the v102 layout (field names are the schema's) and
    the field statistics measured over the shipped Wilds corpus.  Older versions
    differ as described in jcns_schema: no hash-table indices before v35, an
    earlier TransformAxis and no Flags byte before v35, a 64/56-byte
    ConstraintInfo before v21/v13, and a 64-byte ConstraintSource_v1 before v13.

    80-byte ConstraintInfo block layout (parent, at 0xF0 + n*80):
      +0:   ConeDriverInfoOffset  uint64   bt: ConeDriverInfoList.Offset (0=none)
      +8:   OffsetSourceList      uint64   pointer to ConstraintSource_v2
      +16:  ObjectNameOffset      uint64   pointer to TARGET bone name (UTF-16LE)
      +24:  PropertyOffset        uint64   pointer to property name (0 usually)
      +32:  TargetHashIndex       uint32   index into hash_list → target bone hash
      +36:  ObjectHash            uint32   direct target bone hash (redundant with above)
      +40:  PropertyHash          uint32   property hash
      +44:  ConeDriverInfoCount   uint8    bt: ConeDriverInfoCount — 0 in every one of the
                                             19884 constraints surveyed; no shipped file uses
                                             ConeDrivers at all.
      +45:  SourceCount           uint8    number of ConstraintSource_v2 blocks; ~12% of
                                             constraints have more than 1 (up to 8 observed)
      +46:  Flags                 uint8    bt: flags_cns.  11 distinct values observed; bit4/bit5
                                             are deterministic functions of TransformType
                                             (bit4 "isJoint" set for types {0,1,2,4,5,6,13,14},
                                             bit5 "isAngular" for the rotation-ish subset
                                             {1,4,5,6,13,14}).  bit0 ("isAdd?" per bt) is the only
                                             bit that varies independently within one
                                             TransformType — see modules/jcns_flags.py.
                                             bits 1/6/7 never set in any observed file.
      +47:  TransformType         uint8    bt: TransformationID  0=Translation 1=Rotation 2=Scale …
      +48:  UnknownVector4D       vec4     [0,0,0,1] in every observed constraint
      +64:  UnknownFloat2         float[2] [0,0] in 99.6%; the rest look like angle limits
                                             (e.g. [-45,0], [-90,-90], [-20,-20])
      +72:  UnknownUInt8          uint8    0 in 98.5%; also seen {1,2,3,4}
      +73:  TransformAxis         uint8    bt: AxisID — target axis (may differ from src-specific).
                                             Unlike source_axis, this DOES take W (1.3%).
      +74:  UnknownUInt8 × 6      Not six free bytes: +76/+78/+79 are always 0 and +74 is 0 in
                                             98.8%, but +75 and +77 are two live enum-ish fields.
                                             +75 ∈ {0,1,2,3,4,5,8} (2 dominates at 70%),
                                             +77 ∈ {0,1,2,3,4} (0 dominates at 74%).
                                             Meaning unknown; preserved verbatim on write.

    72-byte ConstraintSource_v2 layout (pointed to by OffsetSourceList):
      +0:   ComplexMappingInfoOffset  uint64   bt: ComplexMappingInfoOffset (0=none)
      +8:   SourceNameOffset          uint64   pointer to SOURCE bone name (UTF-16LE)
      +16:  SourceHashIndex           uint32   index into hash_list → source bone hash
      +20:  ComplexMappingInfoCount   uint16   bt: ComplexMappingInfoCount.  Nonzero in 78 of
                                              23031 sources, taking values {3, 4, 7}.
      +22:  UnknownUInt16             uint16   0 in all but a single observed source (which has 1).
      +24:  UpdateTiming              uint8    bt(0.65.14): UpdateTimingID.  All six enum values
                                              occur: MotionBegin(7.4%) MotionEnd(13.6%)
                                              ConstraintBegin(8.2%) ConstraintEnd(70.8%)
                                              Last(2 sources) ByBehavior(7 sources).
                                              Appears to encode evaluation order — sources that are
                                              themselves constraint outputs tend to read at
                                              ConstraintEnd, raw animated bones earlier — rather
                                              than anything about how sources combine.
      +25:  SrcTransformID            uint8    MEANING UNCERTAIN — bt 0.65.13 called this
                                              InterpolationID, bt 0.65.14 renamed it to
                                              TransformIDSrc; the template author marks both
                                              "Not sure".  Observed {0,1,2,3,4,5}: mostly
                                              Src_Rotation_3 (82.7%), but value 5 is beyond the
                                              bt enum's last defined entry.  Among real bone
                                              rotation targets, the 70 sources tagged
                                              Src_Translation(0) carry From ranges shaped like the
                                              rotation ones (91% land on multiples of 5, same
                                              magnitude band), so the tag alone does not establish
                                              a distance-driven mechanism.  Treated as a raw byte.
      +26:  source_axis               uint8    bt: SourceAxis  0=X 1=Y 2=Z 3=W.  Only {X,Y,Z} ever
                                              observed here — sources never use W, though targets do.
      +27:  UnkByte2                  uint8    NOT constant: {0:79.3%, 1:14.8%, 2:5.6%, 3:0.3%}.
      +28:  UnknownUInt32_2      uint32   Really two live bytes; +30/+31 are always 0.
                                              +28 ∈ {0,1,2,3} (0 in 91.5%).
                                              +29 == 1 iff ComplexMappingInfoCount > 0 (exact
                                              match across all 78 cases), so it reads as that
                                              feature's enable flag; +29 == 2 occurs in 39 further
                                              sources with no complex mapping and is unexplained.
      +32:  from_start           float    Point A source angle (rest-side boundary)
      +36:  from_kink            float    Point B source angle (kink/折点 — slope changes here)
      +40:  from_end             float    Point C source angle (終点 — end of second segment)
      +44:  to_start             float    Point A output (= 0 for one-sided, = extreme for through-range like Back X)
      +48:  to_kink              float    Point B output — engine reads this.  NOT a dead field:
                                        nonzero in 14.8% of sources across 98 distinct values,
                                        so the mapping's middle anchor is genuinely used.
      +52:  to_end               float    Point C output (= actual maximum target output)
      +56:  rest_quat_x          float    Rest-pose quaternion X — 0.0 in every observed source
      +60:  rest_quat_y          float    Rest-pose quaternion Y — 0.0 except 2 sources (-0.7071)
      +64:  rest_quat_z          float    Rest-pose quaternion Z — 0.0 in every observed source
      +68:  rest_quat_w          float    Rest-pose quaternion W — 1.0 except the same 2 sources
                                        (0.7071); together those two encode a 90° rotation about Y
                                        rather than identity, so this is a real rest pose, not padding.
    Total: 72 bytes

    Field-frequency claims above were measured over 884 shipped .jcns.102 files
    (19884 constraints / 23031 sources).  Every non-constant field listed here is
    round-tripped verbatim by jcns_writer; the defaults it falls back to apply only to
    newly created constraints.

    JCNS axis convention (AxisID):
      0=X  1=Y  2=Z  3=W (quaternion component)
      bt 0.65.14 also defines UnknownAxis_4..8, none of which occur in the corpus.

    Mapping formula (correct 2-anchor interpretation):
      output = clamp(
          to_max + (source - from_max) * (to_min - to_max) / (from_min - from_max),
          min(to_min, to_max),
          max(to_min, to_max)
      )
      At source=from_max → output=to_max (anchor A)
      At source=from_min → output=to_min (anchor B)
      At source outside range → clamped to boundary → 0 at rest pose ✓
    """

    AXIS_NAMES = ['X', 'Y', 'Z', 'W']
    # No transform-type name table here on purpose: TRANSFORM_TYPE_MAP in __init__.py
    # is the single source of truth, and it covers all of bt 0.65.14's IDs 0-16.

    def __init__(self, filepath):
        self.filepath = filepath
        self.header = {}
        self.hash_list = []
        self.constraints = []

    @property
    def version(self):
        return self.header.get('Version', 102)

    @property
    def write_mode(self):
        return write_mode(self.version)

    def _read_wstring(self, data, offset):
        """Read a null-terminated UTF-16LE string from data at offset."""
        if offset == 0 or offset >= len(data):
            return ''
        end = offset
        while end + 1 < len(data) and data[end:end + 2] != b'\x00\x00':
            end += 2
        try:
            return data[offset:end].decode('utf-16le')
        except UnicodeDecodeError:
            return ''

    def _hash_at(self, index):
        return self.hash_list[index] if 0 <= index < len(self.hash_list) else 0

    def parse(self):
        with open(self.filepath, 'rb') as f:
            data = f.read()
        self.original_bytes = data
        self.aim_constraints    = []
        self.rot_expressions    = []
        self.rot_expression_map = b''
        self.material_cns       = []
        self.joint_export_graph = None
        self.header = read_header(data)
        print(f"Version: {self.version} ({VERSION_GAMES.get(self.version, '?')}), "
              f"write mode: {self.write_mode}")
        self._parse_hash_list(data)
        self._parse_constraints(data)
        self._parse_aim_constraints(data)
        self._parse_rot_expressions(data)
        self._parse_material_cns(data)
        self._parse_joint_export_graph(data)
        return self.constraints

    def _parse_hash_list(self, data):
        # The global hash table only exists from v35; older files store hashes inline.
        self.hash_list = []
        count = self.header.get('HashCount', 0)
        off = self.header.get('HashListOffset', 0)
        if count > 0 and off > 0:
            self.hash_list = list(struct.unpack_from(f'<{count}I', data, off))
        print(f"Hash list: {len(self.hash_list)} entries")

    def _parse_constraints(self, data):
        v = self.version
        count = self.header['ConstraintCount']
        base = self.header['ConstraintSetsStart']
        size = CONSTRAINT_INFO.size(v)
        src_struct = source_struct(v)
        src_size = src_struct.size(v)
        axis_key = transform_axis_key(v)

        self.constraints = []
        for idx in range(count):
            off = base + idx * size
            rec = CONSTRAINT_INFO.read(data, off, v)
            c = dict(rec)
            c['_rec'] = rec                       # original record, for in-place writes
            c['ParentSetOffset'] = off
            c['TransformAxis_parent'] = rec[axis_key]
            c['target_axis'] = rec[axis_key]
            c['TargetBoneName'] = self._read_wstring(data, rec['TargetBoneNameOffset'])
            c['_orig_target_name'] = c['TargetBoneName']
            # Property of the target (e.g. 'Blend_A' of material 'face'); empty for bones.
            c['PropertyName'] = (self._read_wstring(data, rec['PropertyOffset'])
                                 if rec.get('PropertyOffset') else '')

            # ObjectName can be an RSZ object or property target (e.g. 'via.motion.Chain'
            # with TransformType=11 and a non-zero PropertyHash) whose ObjectHash is not
            # the name's hash; record whether they agree while both are still original.
            c['ObjectHashMatchesName'] = bool(
                c['TargetBoneName'] and _hash_utf16(c['TargetBoneName']) == rec['ObjectHash'])
            if v >= 35 and 0 <= rec['TargetHashIndex'] < len(self.hash_list):
                c['TargetHash'] = self.hash_list[rec['TargetHashIndex']]
            else:
                c['TargetHash'] = rec['ObjectHash']

            # ConstraintSource[SourceCount] — consecutive records at LimitsPointer.
            # Multi-source constraints are common (~12% in Wilds).
            c['sources'] = []
            ptr = rec['LimitsPointer']
            if ptr:
                for k in range(rec['SourceCount_parent']):
                    s_off = ptr + k * src_size
                    if s_off + src_size > len(data):
                        break                     # truncated file; jcns_validate reports it
                    c['sources'].append(self._parse_source(data, s_off, src_struct))
            self.constraints.append(c)

        for i, c in enumerate(self.constraints):
            ta = self.AXIS_NAMES[min(c['target_axis'], 3)]
            head = (f"[{i:02d}] target={c['TargetBoneName'] or '?':<20} "
                    f"tgtAxis={ta}  hash32=0x{c['TargetHash']:08x}")
            if not c['sources']:
                print(head + "  (no sources)")
                continue
            print(f"{head}  << {len(c['sources'])} source(s)")
            for k, s in enumerate(c['sources']):
                sa = self.AXIS_NAMES[min(s['source_axis'], 3)]
                print(f"       src[{k}] {s['SourceName'] or '?':<16} axis={sa}  "
                      f"From=[{s['from_start']}, kink={s['from_kink']}, {s['from_end']}] "
                      f"To=[{s['to_start']}, kink={s['to_kink']}, {s['to_end']}]")

    def _parse_source(self, data, off, src_struct):
        v = self.version
        rec = src_struct.read(data, off, v)
        s = dict(rec)
        s['_rec'] = rec
        s['_offset'] = off
        s['SourceName'] = self._read_wstring(data, rec['SourceName_Offset'])
        s['_orig_name'] = s['SourceName']
        # v2-only fields, so downstream code sees the same keys for every version.
        s.setdefault('ComplexMappingInfoOffset', 0)
        s.setdefault('ComplexMappingInfoCount', 0)
        s.setdefault('UnknownUInt16', 0)
        if v >= 35:
            s['SourceHash'] = self._hash_at(rec['SourceHashIndex'])
        return s

    def _parse_rot_expressions(self, data):
        """Section 1.  From v35 two int32 hash-index arrays follow the info records."""
        v, h = self.version, self.header
        n = h.get('RotExpressionInfoCount', 0)
        m = h.get('RotExpressionMapCount', 0)
        self.rot_expressions = []
        if n == 0:
            return
        info_off = h['RotExpressionInfoEntry']
        src_idx_off = h.get('RotExpressionSourceHashIndicesEntry', 0)
        jnt_idx_off = h.get('RotExpressionHashIndicesEntry', 0)
        size = ROT_EXPRESSION.size(v)
        for i in range(n):
            base = info_off + i * size
            rec = ROT_EXPRESSION.read(data, base, v)
            self.rot_expressions.append({
                'JointHash':         rec['JointHash'],
                'SourceJointHash':   rec['SourceJointHash'],
                'SrcJointHashIndex': (struct.unpack_from('<i', data, src_idx_off + i * 4)[0]
                                      if src_idx_off else -1),
                'JntHashIndex':      (struct.unpack_from('<i', data, jnt_idx_off + i * 4)[0]
                                      if jnt_idx_off else -1),
                'info_raw':          bytes(data[base:base + size]),   # direct hashes, copied verbatim
            })
        map_off = h.get('RotExpressionMapEntry', 0)
        self.rot_expression_map = bytes(data[map_off:map_off + m]) if map_off and m else b''
        print(f"Parsed {n} RotExpression(s), map={m}")

    def _parse_material_cns(self, data):
        """Section 4 (v22+).  JointHash is a hash-table index from v35, a raw hash before."""
        v, h = self.version, self.header
        n = h.get('MaterialConstraintInfoCount', 0)
        off = h.get('MaterialConstraintInfoEntry', 0)
        self.material_cns = []
        if n == 0 or off == 0:
            return
        size = MATERIAL.size(v)
        for i in range(n):
            rec = MATERIAL.read(data, off + i * size, v)
            idx = rec.get('JointHashIndex', -1)
            self.material_cns.append({
                'JointHashIndex': idx,
                'JointHash':      self._hash_at(idx) if v >= 35 else rec['JointHash'],
                'raw_body':       rec['Body'],
                '_offset':        off + i * size,
            })
            self.material_cns[-1]['_orig_joint_hash'] = self.material_cns[-1]['JointHash']
        print(f"Parsed {n} MaterialConstraint(s)")

    def _parse_joint_export_graph(self, data):
        """Section 5 (v29+): zero or one entry, a single uint64 pointer to a path."""
        off = self.header.get('JointExportGraphInfoEntry', 0)
        self.joint_export_graph = None
        if off == 0:
            return
        path_ptr = struct.unpack_from('<Q', data, off)[0]
        path_str = self._read_wstring(data, path_ptr) if path_ptr else ''
        self.joint_export_graph = {'path': path_str, '_orig_path': path_str}
        print(f"Parsed JointExportGraph: '{path_str}'")

    def _parse_aim_constraints(self, data):
        """Section 3 (v16+): 80-byte record + the 16-byte target block it points to."""
        v, h = self.version, self.header
        count = h.get('AimConstraintCount', 0)
        offset = h.get('AimConstraintTableEntry', 0)
        self.aim_constraints = []
        if count == 0 or offset == 0:
            return
        size = AIM.size(v)
        for i in range(count):
            base = offset + i * size
            rec = AIM.read(data, base, v)
            tgt_ptr = rec['TargetInfoOffset']
            if 0 < tgt_ptr and tgt_ptr + AIM_TARGET.size(v) <= len(data):
                tgt = AIM_TARGET.read(data, tgt_ptr, v)
            else:
                tgt = {'TargetHashIndex': -1, 'TargetHash': 0, 'Body': bytes(12)}
            if v >= 35:
                joint = self._hash_at(rec['JointHashIndex'])
                unk = self._hash_at(rec['UnkJointHashIndex'])
                target = self._hash_at(tgt['TargetHashIndex'])
            else:
                joint, unk, target = rec['JointHash'], rec['UnkJointHash'], tgt['TargetHash']
            self.aim_constraints.append({
                'JointHashIndex':    rec.get('JointHashIndex', -1),
                'JointHash':         joint,
                'UnkJointHashIndex': rec.get('UnkJointHashIndex', -1),
                'UnkJointHash':      unk,
                'TargetHashIndex':   tgt.get('TargetHashIndex', -1),
                'TargetHash':        target,
                'inline_body':       bytes(data[base + 8:base + size]),   # everything after the pointer
                'target_body':       tgt['Body'],
            })
        print(f"Parsed {count} Aim constraint(s)")


if __name__ == '__main__':
    p = JCNSParser(sys.argv[1])
    cns = p.parse()
    print(f"\nTotal: {len(cns)} constraints")
