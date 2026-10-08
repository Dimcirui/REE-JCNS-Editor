import struct
import os
import sys

from jcns_i18n import T
import jcns_schema as S
from jcns_schema import (
    HEADER, OUTPUT_DATA, AIM, AIM_TARGET, MATERIAL, ROT_EXPRESSION,
    COMPLEX_MAPPING, OBJECT_SETTING, MULTI, MULTI_SOURCE, MULTI_SOURCE_INFO,
    CONE_INPUT, CONE_DRIVER, cone_struct, pre35_to_neutral, pre35_lossy,
    SUPPORTED_VERSIONS, VERSION_GAMES, source_struct, output_axis_key,
    check_header_layout,
)

# Versions the writer can rebuild from scratch (add / delete / rename).  Every
# other version is written back in place: each record is re-packed at its
# original offset, so values can change but the file's structure cannot.
FULL_REBUILD_VERSIONS = frozenset({22, 35, 36, 102})

# Versions whose ConeInput table is read (v35+ layout, and v22's older one).
CONE_DRIVER_VERSIONS = frozenset({22})


# Header counts of the sections the pre-v35 rebuild does not write: their layouts before v35 are
# not verified, so a file that has one is written in place.
_UNWRITTEN_BEFORE_35 = ('AimConstraintCount', 'RotExpressionInfoCount', 'MultiConstraintCount',
                        'MaterialConstraintInfoCount')


def write_mode(version, header=None, lossless=True):
    """'rebuild' or 'inplace'.  Before v35 the file itself decides too: pass its header and
    whether the neutral constraint form holds all its bytes."""
    if version not in FULL_REBUILD_VERSIONS:
        return 'inplace'
    if version < 35 and (not lossless or any((header or {}).get(k, 0) for k in _UNWRITTEN_BEFORE_35)):
        return 'inplace'
    return 'rebuild'


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
        raise ValueError(T("core.parser.bad_version", version, list(SUPPORTED_VERSIONS)))
    if data[4:8] != b'jcns':
        raise ValueError(T("core.parser.not_jcns"))
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
    header['ConstraintSetsStart'] = header['OutputEntry']
    header['ConstraintSetSize'] = OUTPUT_DATA.size(version)
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
    earlier TransformAxis and no AttrFlags byte before v35, a 64/56-byte
    OutputData before v21/v13, and a 64-byte JointDriver_v1 before v13.

    Statistics are over the 1103 shipped Wilds .jcns.102 files (22839 constraints,
    26053 sources), recounted 2026-09-30; "measured" means tested in game on the
    xaihi rig (see scripts/probes).  Every field is round-tripped verbatim by
    jcns_writer except the ones it derives (offsets, counts, hash indices, AttrFlags
    bit4/5, the joint-group byte); its defaults apply only to new constraints.

    80-byte OutputData block layout (parent, at 0xF0 + n*80):
      +0:   ConeDriverOffset  uint64   bt: ConeDriverInfoList.Offset (0=none)
      +8:   OffsetSourceList      uint64   pointer to JointDriver_v2
      +16:  ObjectNameOffset      uint64   pointer to TARGET bone name (UTF-16LE)
      +24:  PropertyOffset        uint64   pointer to property name; set in 5.9%, all on
                                             non-joint targets (Blend_A.., UV_Tile_Offset, ...)
      +32:  ObjectHashIndex       uint32   index into hash_list -> target bone hash
      +36:  ObjectHash            uint32   direct target bone hash (redundant with above)
      +40:  PropertyHash          uint32   hash of the property name; 0 when there is none
      +44:  ConeDriverCount   uint8    0 in every Wilds constraint; RE9 (v35) uses
                                             ConeDrivers heavily (1466 of 2349, see CONE_INPUT).
      +45:  SourceCount           uint8    1 in 89.3%, up to 8; 0 in 19 (BlendShape targets
                                             mostly).  Sources sum (measured).
      +46:  AttrFlags                 uint8    bt: flags_cns.  11 values (49 35%, 17 35%, 48 11%,
                                             16 9%, 1 8%, 0 3%, 9/5/13/53/57 rare).
                                             bit4 "isJoint" / bit5 "isAngular" follow
                                             TransformElement (see jcns_flags; derived on export).
                                             bit0 (1 in 78%) = base_pose (measured, round 8):
                                             1 lays the value onto the rest pose (rest * R(v)),
                                             0 replaces it (a -2 deg rest vanished).  Either
                                             way the last writer of a channel still wins, and
                                             the entry's output value is unchanged.
                                             Translation (round 10): 1 adds in parent axes,
                                             0 replaces only written position components;
                                             unwritten components keep their rest offset.
                                             Euler bit0=0 replaces only written rest-Euler
                                             components, including multi-axis rest (round 11).
                                             Scale: bit0=0/1 both directly replace written
                                             axes; unwritten axes keep rest scale, including
                                             non-unit (1.4,0.7,1.8), measured round 11. Agrees
                                             with bit0 of its sources' AttrFlags in 93.5%, but
                                             that bit does nothing.  bit2/bit3: only on
                                             BlendShape / material targets.  bits 1/6/7: never.
      +47:  TransformElement         uint8    bt: TransformationID.  15 values.  Measured: 0
                                             Translation, 2 Scale, and the rotations, which
                                             mirror the source ReadModes (round 9):
                                             1 Euler rest*Rz*Ry*Rx, 4 swing*twist, 5 twist*swing,
                                             6 rotation vector; 13 / 14 one rotation about the
                                             written axis per bone, the bone's last 13/14 entry
                                             winning whatever its axis (13 is 20% of all
                                             constraints; 14 behaved identically).  3 and 7-12
                                             drive blend shapes / materials, unmeasured.
      +48:  ReservedVec4          vec4     (0,0,0,1) in every constraint.
      +64:  UnknownFloat2         float[2] (0,0) in 99.7%.  BlendShape targets mostly (0,1);
                                             11 rotation targets carry pairs like (-45,0),
                                             (-90,-90), (0,2), (-2,2) that do not match their
                                             mapping ranges, so not an obvious clamp.
                                             Unmeasured.
      +72:  UnknownByte72          uint8    0 in 98.7%, else 1-4; follows the target bone (99.6%).  Unmeasured.
      +73:  TransformAxis         uint8    bt: AxisID, the target axis; equals target_axis in
                                             every entry.  Takes W (1.1%), sources never do.
      +74:  TailBytes[0..5]        6 bytes  +74: 0 in 98.9% (else 5/2/1).  The RotOrder a joint group of Rot2 (13)
                                             entries composes its axes in, read off the group's
                                             first entry (round 19); no effect on 0/1/2 (rounds 15-16).
                                             +75: 2 in 69%, also 5/0/1/3/6/8; one value per file
                                             in 940 of 971 files (mixed files split translation 2
                                             / rotation 8 on one bone).  The native evaluator skips the entry when
                                             it is below a per-object level (looks like LOD; disassembly only).
                                             +76, +78, +79: always 0.
                                             +77: joint-group count -- the N entries right after
                                             this one (same target, property, TransformElement and
                                             AttrFlags) are written to THIS entry's target (measured;
                                             see jcns_writer.tail_group_counts, which derives it).

    72-byte JointDriver_v2 layout (pointed to by OffsetSourceList):
      +0:   ComplexMappingInfoOffset  uint64   bt: ComplexMappingInfoOffset (0=none)
      +8:   SourceNameOffset          uint64   pointer to SOURCE bone name (UTF-16LE)
      +16:  SourceHashIndex           uint32   index into hash_list -> source bone hash
      +20:  ComplexMappingInfoCount   uint16   records in the ComplexMapping curve; nonzero in 78
                                              sources ({3, 4, 7}).  The curve is a cubic Hermite
                                              (measured, see jcns_complex).
      +22:  UnknownUInt16_22             uint16   0 in every source but one (flower_ziva, 1).
      +24:  AttrFlags                 uint8    bt: UpdateTiming (wrong).  bit 1 selects the curve:
                                              {0,1} two-point (kink ignored), {2,3} three-point
                                              (measured).  bit 0 does nothing -- not to the curve,
                                              not to the pose (measured); AttrFlags bit0 is the
                                              base_pose switch it usually mirrors.  3 64%, 0 13%, 1 12%,
                                              2 10%; 4/5 only in 34 sources on material targets,
                                              unmeasured.
      +25:  InputType                  uint8    How the source bone is read (bt: TransformIDSrc /
                                              InterpolationID, both marked "Not sure").  Measured
                                              for every value, off the bone's whole
                                              parent-relative transform, rest included:
                                              0 position, 1 Euler (order: +27), 2 scale, 3 swing-twist
                                              about X (q = swing*twist), 4 the same with
                                              q = twist*swing, 5 rotation vector.  Only 0-5 occur
                                              (2114 files); see jcns_source_read.INPUT_TYPES.
      +26:  source_axis               uint8    bt: SourceAxis  0=X 1=Y 2=Z.  Sources never use W.
      +27:  RotOrder                uint8    (was UnkByte2) the Euler order of InputType 1
                                              (measured, round 8): 0 Rz*Ry*Rx (Blender XYZ),
                                              1 Rx*Rz*Ry (YZX), 2 Ry*Rx*Rz (ZXY), 3 Rx*Ry*Rz (ZYX).
                                              InputType 3/4/5 ignore it.  0 82%, 1 13%, 2 5%,
                                              3 0.3%; it follows the source bone (94.5%
                                              predictable from it): Thigh / Hand mostly 1, finger
                                              F1 bones and capes 2, wings 3, nearly all others 0,
                                              always 0 for InputType 0/2 -- a per-bone rotation
                                              order, stored even where the read ignores it.
      +28:  Interpolation              uint8    how each mapping segment runs between its anchors
                                              (measured, rounds 15 and 16; per segment also on a
                                              three-point map): 0 straight, 1 cubic ease in (t^3),
                                              2 cubic ease out (1-(1-t)^3), 3 smoothstep (3t^2-2t^3).
                                              0 92%, 3 8%, 1 / 2 rare, mostly on non-joint targets
                                              and InputType 1/4.
      +29:  CurveType         uint8    1 exactly when ComplexMappingInfoCount > 0 (derived on write); 2 in
                                              90 further sources, all material 2D/3D targets with
                                              InputType 1 and AttrFlags 1/5.  +29 = 2 on a rotation
                                              entry gave an output of -90 * input, unclamped, and
                                              overrode +28 = 3 (round 15); no meaning for bones.
      +30:  ReservedWord30             uint16   always 0
      +32:  from_start / from_kink / from_end   float   input anchors A, B, C
      +44:  to_start / to_kink / to_end         float   output anchors A, B, C; the curve
                                              through them is in jcns_mapping (measured: linear
                                              between anchors; an out-of-range kink in
                                              three-point mode kills the source).
      +56:  ref_frame_x/y/z/w         float    (0,0,0,1) in every source but two: ch90_021's
                                              Chest -> Chest_Roll_Val_HJ and Spine0 ->
                                              Spine_Roll_Val_HJ, both a 90 deg turn about Y
                                              (0,-0.7071,0,0.7071), InputType 3.  Not the bone's
                                              rest pose (the engine takes that from the skeleton)
                                              but the frame f the rotation is read in: InputType
                                              3/4/5 decompose f^-1 * q * f, so that value moves the
                                              twist axis from X to Z (measured, round 8); InputType
                                              1 ignores it.
    Total: 72 bytes

    JCNS axis convention (AxisID):
      0=X  1=Y  2=Z  3=W (quaternion component)
      bt 0.65.14 also defines UnknownAxis_4..8, none of which occur in the corpus.
    """

    AXIS_NAMES = ['X', 'Y', 'Z', 'W']
    # No transform-type name table here on purpose: TRANSFORM_ELEMENT_MAP in __init__.py
    # is the single source of truth, and it covers all of bt 0.65.14's IDs 0-16.

    def __init__(self, filepath):
        self.filepath = filepath
        self.header = {}
        self.hash_list = []
        self.constraints = []
        self._lossy = False

    @property
    def version(self):
        return self.header.get('Version', 102)

    @property
    def write_mode(self):
        return write_mode(self.version, self.header, not self._lossy)

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
        self.object_settings    = []
        self.multi_constraints   = []
        self.multi_source_infos  = []
        self.read_joint_table    = []
        self.cone_inputs       = []
        self.header = read_header(data)
        self.section_order = self._read_section_order(data)
        print(f"Version: {self.version} ({VERSION_GAMES.get(self.version, '?')}), "
              f"write mode: {self.write_mode}")
        self._parse_hash_list(data)
        self._parse_cone_drivers(data)
        self._parse_constraints(data)
        self._parse_aim_constraints(data)
        self._parse_rot_expressions(data)
        self._parse_material_cns(data)
        self._parse_joint_export_graph(data)
        self._parse_object_settings(data)
        self._parse_multi_constraints(data)
        return self.constraints

    def _read_section_order(self, data):
        """SectionTable: the section ids in the order the engine runs them ([] when the file has none)."""
        n, off = self.header['SectionTableItemCount'], self.header.get('SectionTableEntry', 0)
        if not n or not off or off + 4 * n > len(data):
            return []
        return list(struct.unpack_from(f'<{n}I', data, off))

    def _parse_cone_drivers(self, data):
        """Section 0 ConeInput table (v35 layout, and v22's; other versions stay in place)."""
        self.cone_inputs = []
        n = self.header.get('ConeInputCount', 0)
        base = self.header.get('ConeInputTableEntry', 0)
        if not n or not base or not (self.version >= 35 or self.version in CONE_DRIVER_VERSIONS):
            return
        layout = cone_struct(self.version)
        size = layout.size(self.version)
        for i in range(n):
            rec = layout.read(data, base + i * size, self.version)
            cd = dict(rec)
            cd['Name'] = self._read_wstring(data, rec['Name_Offset'])
            if self.version >= 35:
                cd['JointHash'] = self._hash_at(rec['JointHashIndex'])
                cd['ParentJointHash'] = self._hash_at(rec['ParentJointHashIndex'])
                cd['SymmetryJointHash'] = (self._hash_at(rec['SymmetryJointHashIndex'])
                                           if rec['SymmetryJointHashIndex'] >= 0 else None)
            else:
                cd['JointName'] = self._read_wstring(data, rec['JointName_Offset'])
                cd['ParentJointName'] = self._read_wstring(data, rec['ParentJointName_Offset'])
                cd['SymmetryJointHash'] = None
            self.cone_inputs.append(cd)
        print(f"Parsed {n} ConeInput(s)")

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
        count = self.header['OutputCount']
        base = self.header['ConstraintSetsStart']
        size = OUTPUT_DATA.size(v)
        src_struct = source_struct(v)
        src_size = src_struct.size(v)
        axis_key = output_axis_key(v)

        self.constraints = []
        for idx in range(count):
            off = base + idx * size
            rec = OUTPUT_DATA.read(data, off, v)
            c = dict(rec)
            c['_rec'] = rec                       # original record, for in-place writes
            c['ParentSetOffset'] = off
            c['Axis_parent'] = rec[axis_key]
            c['target_axis'] = rec[axis_key]
            c['ObjectName'] = self._read_wstring(data, rec['ObjectNameOffset'])
            c['_orig_object_name'] = c['ObjectName']
            # Property of the target (e.g. 'Blend_A' of material 'face'); empty for bones.
            c['PropertyName'] = (self._read_wstring(data, rec['PropertyOffset'])
                                 if rec.get('PropertyOffset') else '')
            c['_orig_property_name'] = c['PropertyName']

            # ObjectName can be an RSZ object or property target (e.g. 'via.motion.Chain'
            # with TransformElement=11 and a non-zero PropertyHash) whose ObjectHash is not
            # the name's hash; record whether they agree while both are still original.
            c['ObjectHashMatchesName'] = bool(
                c['ObjectName'] and _hash_utf16(c['ObjectName']) == rec['ObjectHash'])
            if v >= 35 and 0 <= rec['ObjectHashIndex'] < len(self.hash_list):
                c['TargetHash'] = self.hash_list[rec['ObjectHashIndex']]
            else:
                c['TargetHash'] = rec['ObjectHash']

            # ConeDriver[ConeDriverCount]: which cones drive this constraint.
            c['ConeDriver'] = []
            n_cone, cone_at = rec['ConeDriverCount'], rec['ConeDriverOffset']
            if n_cone and cone_at:
                size_ci = CONE_DRIVER.size(v)
                c['ConeDriver'] = [CONE_DRIVER.read(data, cone_at + k * size_ci, v)
                                       for k in range(n_cone)]
                # CurveType 1 (Function): CurveData is {uint64 offset, uint32 count} of a
                # curve in ComplexMapping records, stored right after this ConeDriver array.
                size_cm = COMPLEX_MAPPING.size(v)
                for cd in c['ConeDriver']:
                    if cd.get('CurveType') == 1 and cd.get('CurveData'):
                        off, n = struct.unpack_from('<QI', cd['CurveData'])
                        if off and 0 < n and off + n * size_cm <= len(data):
                            cd['Curve'] = [COMPLEX_MAPPING.read(data, off + k * size_cm, v) for k in range(n)]

            # JointDriver[SourceCount] — consecutive records at SourceListOffset.
            # Multi-source constraints are common (~12% in Wilds).
            c['sources'] = []
            ptr = rec['SourceListOffset']
            if ptr:
                for k in range(rec['JointDriverCount']):
                    s_off = ptr + k * src_size
                    if s_off + src_size > len(data):
                        break                     # truncated file; jcns_validate reports it
                    c['sources'].append(self._parse_source(data, s_off, src_struct))
            if 21 <= v < 35 and self.write_mode == 'rebuild':
                # held as the v35+ record; the raw keys stay for jcns_validate
                c['_pre35_lossy'] = pre35_lossy(rec)
                c.update(pre35_to_neutral(rec))
            self.constraints.append(c)

        if any(c.get('_pre35_lossy') for c in self.constraints):
            # a byte the v35+ record cannot hold: this file is written in place instead
            self._lossy = True
            return self._parse_constraints(data)

        for i, c in enumerate(self.constraints):
            ta = self.AXIS_NAMES[min(c['target_axis'], 3)]
            head = (f"[{i:02d}] target={c['ObjectName'] or '?':<20} "
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
        s.setdefault('UnknownUInt16_22', 0)
        if v >= 35:
            s['SourceHash'] = self._hash_at(rec['SourceHashIndex'])
        # ComplexMappingInfo[count]; the bt template aligns the pointer up to 16
        # before reading, and every shipped pointer is already aligned.
        s['ComplexMapping'] = []
        n, cm_off = s['ComplexMappingInfoCount'], s['ComplexMappingInfoOffset']
        if n and cm_off:
            cm_off += (-cm_off) % 16
            size = COMPLEX_MAPPING.size(v)
            s['ComplexMapping'] = [COMPLEX_MAPPING.read(data, cm_off + k * size, v) for k in range(n)]
        return s

    def _parse_object_settings(self, data):
        """Section 0 ObjectSettings: 16-byte records, each pointing at one hash."""
        v, h = self.version, self.header
        n = h.get('ObjectSettingCount', 0)
        self.object_settings = []
        base = h.get('ObjectSettingEntry', 0)
        if not n or not base:
            return
        size = OBJECT_SETTING.size(v)
        for i in range(n):
            rec = OBJECT_SETTING.read(data, base + i * size, v)
            rec['ObjectNameHash'] = struct.unpack_from('<I', data, rec['HashOffset'])[0]
            self.object_settings.append(rec)
        print(f"Parsed {n} ObjectSetting(s)")

    def _parse_multi_constraints(self, data):
        """Section 2: MultiConstraint records, their weighted source lists, and (v29+)
        the shared source table; from v36 also the ReadJointTable (raw hashes;
        MultiConstraintHashTable in bt / REE-Lib), which Multi shares with Aim."""
        v, h = self.version, self.header
        n = h.get('MultiConstraintCount', 0)
        self.multi_constraints, self.multi_source_infos, self.read_joint_table = [], [], []
        if not n:
            return
        base, size = h['MultiConstraintTableEntry'], MULTI.size(v)
        src_size = MULTI_SOURCE.size(v)
        for i in range(n):
            rec = MULTI.read(data, base + i * size, v)
            rec['ObjectHash'] = (self._hash_at(rec['ObjectHashIndex']) if v >= 35
                                 else rec['ObjectHash'])
            rec['sources'] = [MULTI_SOURCE.read(data, rec['SourceListOffset'] + k * src_size, v)
                              for k in range(rec['SourceCount'])]
            self.multi_constraints.append(rec)

        ns = h.get('MultiConstraintSourceCount', 0)
        info_base = h.get('MultiConstraintSourceTableEntry', 0)
        if ns and info_base and MULTI_SOURCE_INFO.size(v):
            isz = MULTI_SOURCE_INFO.size(v)
            for i in range(ns):
                rec = MULTI_SOURCE_INFO.read(data, info_base + i * isz, v)
                if v >= 35:
                    rec['SourceHash'] = self._hash_at(rec['SourceHashIndex'])
                self.multi_source_infos.append(rec)

        k = h.get('ReadJointTableItemCount', 0)
        if k and h.get('ReadJointTableEntry'):
            self.read_joint_table = list(struct.unpack_from(
                f'<{k}I', data, h['ReadJointTableEntry']))
        print(f"Parsed {n} MultiConstraint(s), {len(self.multi_source_infos)} source info, "
              f"{len(self.read_joint_table)} read joint(s)")

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
        off = self.header.get('JointExprGraphInfoEntry', 0)
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
            # Byte +57 counts the targets; a second one fills the block's last
            # 8 bytes as (hash index or hash, weight).
            t2_idx, t2 = -1, None
            if rec['Body'][49] >= 2:
                if v >= 35:
                    t2_idx = struct.unpack_from('<i', tgt['Body'], 4)[0]
                    t2 = self._hash_at(t2_idx)
                else:
                    t2 = struct.unpack_from('<I', tgt['Body'], 4)[0]
            self.aim_constraints.append({
                'JointHashIndex':    rec.get('JointHashIndex', -1),
                'JointHash':         joint,
                'UnkJointHashIndex': rec.get('UnkJointHashIndex', -1),
                'UnkJointHash':      unk,
                'TargetHashIndex':   tgt.get('TargetHashIndex', -1),
                'TargetHash':        target,
                'Target2HashIndex':  t2_idx,
                'Target2Hash':       t2,
                'inline_body':       bytes(data[base + 8:base + size]),   # everything after the pointer
                'target_body':       tgt['Body'],
            })
        print(f"Parsed {count} Aim constraint(s)")


if __name__ == '__main__':
    p = JCNSParser(sys.argv[1])
    cns = p.parse()
    print(f"\nTotal: {len(cns)} constraints")
