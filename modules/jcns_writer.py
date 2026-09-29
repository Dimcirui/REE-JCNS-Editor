import struct
import os
import sys

from jcns_schema import (
    HEADER, CONSTRAINT_INFO, SOURCE_V2, AIM, AIM_TARGET, MATERIAL,
    source_struct, transform_axis_key,
)
from jcns_parser import header_field_offset


# ConstraintInfo / ConstraintSource fields the in-place writer takes from the
# edited dicts.  Everything else — pointers, hashes, hash indices, counts — is
# re-packed from the original record, because in place the surrounding data
# (strings, source arrays, hash table) does not move.
INPLACE_CNS_FIELDS = ('Flags', 'TransformType', 'ParentVec4', 'ParentFloat2',
                      'ParentUInt8_72', 'PropertyHash', 'ParentTailBytes')
INPLACE_SRC_FIELDS = ('UpdateTiming', 'SrcTransformID', 'source_axis', 'UnkByte2',
                      'UnknownUInt16', 'UnknownUInt32_2',
                      'from_start', 'from_kink', 'from_end',
                      'to_start', 'to_kink', 'to_end',
                      'rest_quat_x', 'rest_quat_y', 'rest_quat_z', 'rest_quat_w')


class JCNSWriter:
    def __init__(self, parser_obj, filepath):
        self.parser = parser_obj
        self.filepath = filepath

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_lossless(self, clean_hashes=False):
        """
        Write the parser's (edited) constraints back to self.filepath.

        v102 is fully rebuilt, supporting renamed bones, added/deleted
        constraints and sources, and changed values; only the Tags block and the
        static per-constraint fields are carried over from the original.

        Every other version is written in place (see _build_in_place): values
        change, structure does not.  clean_hashes has no effect there.
        """
        if getattr(self.parser, 'write_mode', 'rebuild') == 'inplace':
            return self._build_in_place()
        return self._build_full(clean_hashes)

    # ------------------------------------------------------------------
    # Internal rebuild
    # ------------------------------------------------------------------

    def _build_full(self, clean_hashes=False):
        p = self.parser
        orig = p.original_bytes

        # ── locate hashing module ──────────────────────────────────────
        hash_dir = os.path.join(os.path.dirname(__file__), 'hashing')
        if hash_dir not in sys.path:
            sys.path.insert(0, hash_dir)
        from mmh3.pymmh3 import hashUTF16  # noqa: F401 (runtime import)

        # ── Phase 1: build new hash list ────────────────────────────────
        if clean_hashes:
            new_hash_list = []
        else:
            new_hash_list = list(p.hash_list)

        def _get_or_add(name):
            """Return (hash32, index) for a bone name, adding to list if missing.

            The empty name is a real name here: 52 shipped v102 sources (the *_UVT
            files) have an empty name string and store murmur("") = 0x81F16F39.
            """
            h = hashUTF16(name) & 0xFFFFFFFF
            for i, v in enumerate(new_hash_list):
                if v == h:
                    return h, i
            idx = len(new_hash_list)
            new_hash_list.append(h)
            return h, idx

        def _get_or_add_hash(h):
            """Return index for a raw hash value (used for non-Range sections)."""
            for i, v in enumerate(new_hash_list):
                if v == h:
                    return i
            idx = len(new_hash_list)
            new_hash_list.append(h)
            return idx

        def _is_direct_hash(c):
            """True when target is identified by direct ObjectHash (TgtIdx=0xFFFFFFFF),
            e.g. BlendShape / property targets that don't live in the hash table."""
            return c.get('TargetHashIndex', 0) == 0xFFFFFFFF

        def _target_hash(c):
            """Hash to store in ObjectHash for a direct-hash (non-indexed) target.

            Normally this is the MurmurHash of ObjectName.  But ObjectName can be an
            RSZ object or property target (e.g. 'via.motion.Chain') whose ObjectHash is
            derived from something else — recomputing it there would corrupt the field,
            so the parser records whether the two agreed in the original file.
            """
            name = c.get('TargetBoneName', '')
            if name and c.get('ObjectHashMatchesName', True):
                return hashUTF16(name) & 0xFFFFFFFF
            return c.get('ObjectHash', 0)


        # Rebuild hashes for all source and target bones (Range constraints)
        for c in p.constraints:
            for s in c.get('sources', []):
                _, s['SourceHashIndex'] = _get_or_add(s.get('SourceName', ''))

            # Only bone targets go into the hash table; BlendShape/property targets
            # use direct ObjectHash (TgtIdx=0xFFFFFFFF) and must not pollute the list.
            tgt = c.get('TargetBoneName', '')
            if tgt and not _is_direct_hash(c):
                _get_or_add(tgt)

        # Add Aim constraint hashes and update their indices
        for ac in getattr(p, 'aim_constraints', []):
            for idx_key in ('JointHashIndex', 'UnkJointHashIndex', 'TargetHashIndex'):
                old_idx = ac.get(idx_key, -1)
                if 0 <= old_idx < len(p.hash_list):
                    ac[idx_key] = _get_or_add_hash(p.hash_list[old_idx])

        # Add RotExpression hash indices (two index arrays per entry) and update them
        for re in getattr(p, 'rot_expressions', []):
            for idx_key in ('SrcJointHashIndex', 'JntHashIndex'):
                old_idx = re.get(idx_key, -1)
                if 0 <= old_idx < len(p.hash_list):
                    re[idx_key] = _get_or_add_hash(p.hash_list[old_idx])

        # Add Material constraint JointHash indices and update them
        for mc in getattr(p, 'material_cns', []):
            old_idx = mc.get('JointHashIndex', -1)
            if 0 <= old_idx < len(p.hash_list):
                mc['JointHashIndex'] = _get_or_add_hash(p.hash_list[old_idx])

        def _dep_key(c, tgt_h):
            """Object hash the dependency table files a constraint under.

            A bone / blendshape target is filed under its own hash.  A target with
            a property is filed under the hash of "object<sep>property": '.' for
            materials ('face.Blend_A', TransformType 7-10) and ':' for RSZ component
            properties ('via.motion.Chain:BlendRate', TransformType 11).  Checked
            against every constraint in the shipped v102 corpus (22839).
            """
            prop = c.get('PropertyName', '')
            if not prop:
                return tgt_h
            sep = ':' if c.get('TransformType') == 11 else '.'
            return hashUTF16(c.get('TargetBoneName', '') + sep + prop) & 0xFFFFFFFF

        # ── Phase 2: layout constants ───────────────────────────────────
        N = len(p.constraints)

        version = struct.unpack_from('<I', orig, 0)[0]
        hdr = p.header
        if not hdr.get('DataEntry'):
            # A parser-like object without a parsed header (the cached-header stub,
            # scripts that assemble a skeleton): re-read it from the bytes.  The
            # skeleton's pointers are not final yet, so skip the layout check.
            from jcns_parser import read_header
            hdr = read_header(orig, check_layout=False)

        # ConstraintInfo starts right after the header, which ends 16-aligned.
        CNS_INFO_START = hdr['HeaderEnd']
        SRC_SIZE       = SOURCE_V2.size(version)
        CNS_INFO_SIZE  = N * CONSTRAINT_INFO.size(version)
        axis_key       = transform_axis_key(version)

        # ConstraintSource_v2 section starts right after ConstraintInfo,
        # padded to 16-byte boundary (80 is a multiple of 16, so no pad needed
        # for any N; still guard for correctness).
        raw_src_start = CNS_INFO_START + CNS_INFO_SIZE
        SRC_START = _align(raw_src_start, 16)

        # ── Phase 3: build ConstraintSource_v2 blobs ───────────────────
        # Layout per constraint (matches shipped multi-source files, e.g.
        # ch02_027_0002 where L_Foot/R_Foot sit at 0x140/0x188 with both name
        # strings pooled afterwards at 0x1D0/0x1DE):
        #
        #     [Source_v2 #0][Source_v2 #1]…[name #0][name #1]…[pad to 8]
        #
        # Writing each name directly after its own struct — as this code used to —
        # puts the string exactly where the engine expects Source_v2 #1, which
        # corrupts every constraint with SourceCount > 1.
        src_blob      = bytearray()
        src_offsets   = []  # absolute offset of each constraint's Source_v2 array (0 = none)

        for c in p.constraints:
            srcs = c.get('sources', [])
            if not srcs:
                # SourceCount == 0 (e.g. BlendShape targets): emit nothing and leave
                # OffsetSourceList null rather than inventing a phantom source block.
                src_offsets.append(0)
                continue

            # Align the array to a 16-byte boundary
            abs_base = SRC_START + len(src_blob)
            pad = _align(abs_base, 16) - abs_base
            src_blob.extend(b'\x00' * pad)
            abs_base += pad
            src_offsets.append(abs_base)

            # Name strings live after all the structs; compute their offsets first.
            names_start = abs_base + SRC_SIZE * len(srcs)
            name_blob = bytearray()
            name_offsets = []
            for s in srcs:
                name_offsets.append(names_start + len(name_blob))
                name_blob.extend(s.get('SourceName', '').encode('utf-16le') + b'\x00\x00')
                if len(name_blob) % 2:
                    name_blob.extend(b'\x00')

            for s, abs_name in zip(srcs, name_offsets):
                rec = dict(_SOURCE_DEFAULTS)
                rec.update({k: v for k, v in s.items() if not k.startswith('_')})
                rec['SourceName_Offset'] = abs_name
                src_blob.extend(SOURCE_V2.pack(rec, version))

            src_blob.extend(name_blob)
            rem = (SRC_START + len(src_blob)) % 8
            if rem:
                src_blob.extend(b'\x00' * (8 - rem))

        # ── Phase 4: build target WString pool ─────────────────────────
        TGT_POOL_START = SRC_START + len(src_blob)
        tgt_pool_blob       = bytearray()
        tgt_name_to_offset  = {}   # name → absolute file offset

        def _pool(name):
            if name not in tgt_name_to_offset:
                abs_off = TGT_POOL_START + len(tgt_pool_blob)
                tgt_name_to_offset[name] = abs_off
                wstr = name.encode('utf-16le') + b'\x00\x00'
                tgt_pool_blob.extend(wstr)
                # Pad to 2-byte alignment so the next string is word-aligned
                if (TGT_POOL_START + len(tgt_pool_blob)) % 2:
                    tgt_pool_blob.extend(b'\x00')

        for c in p.constraints:
            _pool(c.get('TargetBoneName', ''))
        # Property names ('Blend_A', 'BlendRate', ...) — the original PropertyOffset
        # points into the old file, so the string has to be re-emitted.
        for c in p.constraints:
            if c.get('PropertyName'):
                _pool(c['PropertyName'])

        # Pad pool to 8-byte boundary
        rem = (TGT_POOL_START + len(tgt_pool_blob)) % 8
        if rem:
            tgt_pool_blob.extend(b'\x00' * (8 - rem))

        # ── Phase 5: build Dependency table + data ─────────────────────
        # Original file has 8 bytes of zero padding before DependencyTableEntry.
        DEP_PAD_SIZE   = 8
        DEP_TABLE_START = TGT_POOL_START + len(tgt_pool_blob) + DEP_PAD_SIZE

        # bt: DependencyInfo = {uint64 Offset, uint64 SourceCount}, and at Offset
        #     {hash ObjectHash; hash SourceHash[SourceCount]}.
        # So one entry per driven object, carrying all of its source hashes — NOT one
        # entry per (target, source) pair.  Checked against 358 shipped files: 297 have
        # DependencyCount == number of distinct target objects (and real entries carry
        # SourceCount up to 6), while only 2 match the one-entry-per-pair reading.
        # Always derive target hash from the name so renamed bones get correct hashes.
        dep_order = []            # target hashes, in first-seen order
        dep_sources = {}          # target hash -> list of source hashes (unique, ordered)
        for c in p.constraints:
            tgt_name = c.get('TargetBoneName', '')
            if _is_direct_hash(c):
                tgt_h = _target_hash(c)
            else:
                tgt_h, _ = _get_or_add(tgt_name)
            tgt_h = _dep_key(c, tgt_h)
            if tgt_h not in dep_sources:
                dep_sources[tgt_h] = []
                dep_order.append(tgt_h)
            bucket = dep_sources[tgt_h]
            for s in c.get('sources', []):
                src_idx = s.get('SourceHashIndex', 0)
                src_h = new_hash_list[src_idx] if src_idx < len(new_hash_list) else 0
                if src_h not in bucket:
                    bucket.append(src_h)

        M = len(dep_order)
        DEP_DATA_START = DEP_TABLE_START + M * 16

        dep_table_blob = bytearray()
        dep_data_blob  = bytearray()
        for tgt_h in dep_order:
            srcs_h = dep_sources[tgt_h]
            data_offset = DEP_DATA_START + len(dep_data_blob)
            dep_table_blob.extend(struct.pack('<QQ', data_offset, len(srcs_h)))
            dep_data_blob.extend(struct.pack('<I', tgt_h))
            for h in srcs_h:
                dep_data_blob.extend(struct.pack('<I', h))

        # ── Phase 6: build SectionTable ────────────────────────────────
        SEC_TABLE_START = DEP_DATA_START + len(dep_data_blob)
        # Pad to 4-byte alignment
        rem = SEC_TABLE_START % 4
        if rem:
            SEC_TABLE_START += (4 - rem)

        sec_count       = hdr['SectionTableItemCount']
        orig_sec_off    = hdr['SectionTableEntry']
        section_blob    = bytearray()
        for i in range(sec_count):
            st = struct.unpack_from('<I', orig, orig_sec_off + i * 4)[0]
            section_blob.extend(struct.pack('<I', st))

        # ── Phase 7: build HashTable ────────────────────────────────────
        HASH_TABLE_START = _align(SEC_TABLE_START + len(section_blob), 16)
        hash_blob = bytearray()
        for h in new_hash_list:
            hash_blob.extend(struct.pack('<I', h))

        # ── Phase 8: build ConstraintInfo array ────────────────────────
        cns_info_blob = bytearray()
        for i, c in enumerate(p.constraints):
            tgt_name    = c.get('TargetBoneName', '')
            tgt_name_off = tgt_name_to_offset.get(tgt_name, 0)
            if _is_direct_hash(c):
                tgt_h   = _target_hash(c)
                tgt_idx = 0xFFFFFFFF
            else:
                tgt_h, tgt_idx = _get_or_add(tgt_name)
            src_v2_off   = src_offsets[i]

            rec = dict(_CNS_DEFAULTS)
            rec.update({k: v for k, v in c.items() if not k.startswith('_')})
            rec.update({
                'LimitsPointer':        src_v2_off,
                'TargetBoneNameOffset': tgt_name_off,
                'TargetHashIndex':      tgt_idx,
                'ObjectHash':           tgt_h,
                'PropertyOffset':       (tgt_name_to_offset[c['PropertyName']]
                                         if c.get('PropertyName') else 0),
                # Derived from the source list, never copied — a stale SourceCount is
                # exactly what made multi-source constraints read past their own data.
                'SourceCount_parent':   len(c.get('sources', [])),
                axis_key:               c.get('TransformAxis_parent', 0),
            })
            rec['ParentTailBytes'] = bytes(rec['ParentTailBytes'])
            cns_info_blob.extend(CONSTRAINT_INFO.pack(rec, version))

        # ── Phase 8b: build RotExpression section ───────────────────────
        rot_list = getattr(p, 'rot_expressions', [])
        N_ROT = len(rot_list)
        rot_map = getattr(p, 'rot_expression_map', b'')
        ROT_INFO_START = ROT_MAP_START = ROT_SRC_IDX_START = ROT_JNT_IDX_START = 0
        rot_blob = bytearray()
        if N_ROT > 0:
            ROT_INFO_START = _align(HASH_TABLE_START + len(hash_blob), 16)
            for re in rot_list:
                rot_blob.extend(re['info_raw'])           # 56 bytes verbatim
            ROT_MAP_START = ROT_INFO_START + len(rot_blob)
            rot_blob.extend(rot_map)
            # Align source-index table to 4 bytes
            pad = (4 - len(rot_blob) % 4) % 4
            rot_blob.extend(b'\x00' * pad)
            ROT_SRC_IDX_START = ROT_INFO_START + len(rot_blob)
            for re in rot_list:
                rot_blob.extend(struct.pack('<i', re.get('SrcJointHashIndex', -1)))
            ROT_JNT_IDX_START = ROT_INFO_START + len(rot_blob)
            for re in rot_list:
                rot_blob.extend(struct.pack('<i', re.get('JntHashIndex', -1)))

        # ── Phase 8c: build Material constraint section ──────────────────
        mat_list = getattr(p, 'material_cns', [])
        N_MAT = len(mat_list)
        MAT_START = 0
        mat_blob = bytearray()
        if N_MAT > 0:
            base_off = ROT_INFO_START + len(rot_blob) if N_ROT > 0 else HASH_TABLE_START + len(hash_blob)
            MAT_START = _align(base_off, 16)
            for mc in mat_list:
                mat_blob.extend(struct.pack('<i', mc['JointHashIndex']))  # 4 bytes (updated index)
                mat_blob.extend(mc['raw_body'])                            # 12 bytes verbatim

        # ── Phase 8d: build JointExportGraph section ─────────────────────
        jxg = getattr(p, 'joint_export_graph', None)
        JXG_START = 0
        jxg_blob = bytearray()
        if jxg is not None:
            base_off2 = MAT_START + len(mat_blob) if N_MAT > 0 else (
                        ROT_INFO_START + len(rot_blob) if N_ROT > 0 else HASH_TABLE_START + len(hash_blob))
            JXG_START = _align(base_off2, 8)
            path_wstr = jxg['path'].encode('utf-16le') + b'\x00\x00'
            path_abs = JXG_START + 8   # PathOffset uint64 is first, path data follows
            jxg_blob.extend(struct.pack('<Q', path_abs))
            jxg_blob.extend(path_wstr)
            rem = len(jxg_blob) % 8
            if rem:
                jxg_blob.extend(b'\x00' * (8 - rem))

        # ── Phase 8e: build Aim section ─────────────────────────────────
        # Aim constraints (read-only passthrough) are stored in parser.aim_constraints.
        # Each consists of a 80-byte inline block (offset+body) and a 16-byte target block.
        # We rebuild with corrected absolute offset pointers.
        aim_list = getattr(p, 'aim_constraints', [])
        N_AIM = len(aim_list)
        AIM_SECTION_START = 0
        aim_blob = bytearray()
        if N_AIM > 0:
            # Aim section comes after hash table + any preceding non-Range sections
            if jxg is not None:
                _prev_end = JXG_START + len(jxg_blob)
            elif N_MAT > 0:
                _prev_end = MAT_START + len(mat_blob)
            elif N_ROT > 0:
                _prev_end = ROT_INFO_START + len(rot_blob)
            else:
                _prev_end = HASH_TABLE_START + len(hash_blob)
            AIM_SECTION_START = _align(_prev_end, 16)
            aim_size, tgt_size = AIM.size(version), AIM_TARGET.size(version)
            aim_target_base = AIM_SECTION_START + N_AIM * aim_size
            for i, ac in enumerate(aim_list):
                # inline_body is the original record minus its pointer; the two
                # hash indices at its head were remapped in Phase 1, so pack them
                # over it rather than copying the stale ones.
                body = bytearray(struct.pack('<Q', aim_target_base + i * tgt_size)
                                 + ac['inline_body'])
                AIM.pack_into(body, 0, {'JointHashIndex':    ac['JointHashIndex'],
                                        'UnkJointHashIndex': ac['UnkJointHashIndex']}, version)
                aim_blob.extend(body)
            for ac in aim_list:
                aim_blob.extend(AIM_TARGET.pack({'TargetHashIndex': ac['TargetHashIndex'],
                                                 'Body': ac['target_body']}, version))

        # ── Phase 9: patch header ───────────────────────────────────────
        header = bytearray(orig[:CNS_INFO_START])

        patch = {
            'DependencyTableEntry': DEP_TABLE_START,
            'SectionTableEntry':    SEC_TABLE_START,
            'HashListOffset':       HASH_TABLE_START,
            'ConstraintInfoEntry':  CNS_INFO_START,
            'HashCount':            len(new_hash_list),
            'ConstraintCount':      N,
            'DependencyCount':      M,
        }
        # ObjectSettingEntry: when the count is 0 it marks Section 0's end boundary
        obj_setting_count = hdr['ObjectSettingCount']
        if obj_setting_count == 0:
            patch['ObjectSettingEntry'] = SEC_TABLE_START
        if N_AIM > 0:
            patch['AimConstraintTableEntry'] = AIM_SECTION_START
        if N_ROT > 0:
            patch.update({
                'RotExpressionInfoEntry':              ROT_INFO_START,
                'RotExpressionMapEntry':               ROT_MAP_START,
                'RotExpressionSourceHashIndicesEntry': ROT_SRC_IDX_START,
                'RotExpressionHashIndicesEntry':       ROT_JNT_IDX_START,
            })
        if N_MAT > 0:
            patch['MaterialConstraintInfoEntry'] = MAT_START
        if jxg is not None:
            patch['JointExportGraphInfoEntry'] = JXG_START
        HEADER.pack_into(header, hdr['DataEntry'], patch, version)

        # ── Phase 10: assemble ──────────────────────────────────────────
        out = bytearray()
        out.extend(header)                             # Tags + DataInfo header
        out.extend(cns_info_blob)                      # ConstraintInfo[]
        _pad_to(out, SRC_START)
        out.extend(src_blob)                           # Source_v2 + source WStrings
        out.extend(tgt_pool_blob)                      # Target WString pool
        _pad_to(out, DEP_TABLE_START - DEP_PAD_SIZE)   # 8-byte padding before dep table
        out.extend(b'\x00' * DEP_PAD_SIZE)
        out.extend(dep_table_blob)                     # Dependency table
        out.extend(dep_data_blob)                      # Dependency hash pairs
        _pad_to(out, SEC_TABLE_START)
        out.extend(section_blob)                       # SectionTable
        _pad_to(out, HASH_TABLE_START)
        out.extend(hash_blob)                          # HashTable
        if N_ROT > 0:
            _pad_to(out, ROT_INFO_START)
            out.extend(rot_blob)                       # RotExpression info + map + index arrays
        if N_MAT > 0:
            _pad_to(out, MAT_START)
            out.extend(mat_blob)                       # Material constraints
        if jxg is not None:
            _pad_to(out, JXG_START)
            out.extend(jxg_blob)                       # JointExportGraph
        if N_AIM > 0:
            _pad_to(out, AIM_SECTION_START)
            out.extend(aim_blob)                       # Aim section

        with open(self.filepath, 'wb') as f:
            f.write(out)

        print(f'[JCNS] Written {len(out)} bytes → {self.filepath}')
        parts = [f'Cns={N}', f'Aim={N_AIM}', f'RotExpr={N_ROT}', f'Mat={N_MAT}',
                 f'JXG={1 if jxg else 0}', f'Dep={M}', f'Hash={len(new_hash_list)}']
        print(f'  {", ".join(parts)}')
        print(f'  SecTbl=0x{SEC_TABLE_START:X} DepTbl=0x{DEP_TABLE_START:X} HashTbl=0x{HASH_TABLE_START:X}')
        if obj_setting_count == 0:
            print(f'  ObjSettingEntry → 0x{SEC_TABLE_START:X} (count=0, synced)')
        return True


    def _build_in_place(self):
        """
        Every version except v102: copy the original file and re-pack each
        ConstraintInfo / ConstraintSource / MatCnsInfo record at its original
        offset.  Pointers, hashes and hash indices come from the original record,
        so the file layout is untouched and every section this editor does not
        model (ConeDrivers, SkinConstraints, ObjectSettings, ComplexMapping ...)
        survives byte for byte.  Structural edits are refused beforehand by
        jcns_validate.check_in_place_edits().
        """
        from jcns_validate import check_in_place_edits, format_problems
        p = self.parser
        problems = check_in_place_edits(p)
        if problems:
            raise ValueError(format_problems(problems, os.path.basename(p.filepath)))

        v = p.version
        out = bytearray(p.original_bytes)
        axis_key = transform_axis_key(v)
        src_struct = source_struct(v)

        for c in p.constraints:
            rec = dict(c['_rec'])
            rec.update({k: c[k] for k in INPLACE_CNS_FIELDS if k in rec and k in c})
            rec[axis_key] = c.get('TransformAxis_parent', rec[axis_key])
            if 'ParentTailBytes' in rec:
                rec['ParentTailBytes'] = bytes(rec['ParentTailBytes'])
            CONSTRAINT_INFO.pack_into(out, c['ParentSetOffset'], rec, v)
            for s in c['sources']:
                srec = dict(s['_rec'])
                srec.update({k: s[k] for k in INPLACE_SRC_FIELDS if k in srec and k in s})
                src_struct.pack_into(out, s['_offset'], srec, v)

        for mc in p.material_cns:
            MATERIAL.pack_into(out, mc['_offset'], {'Body': bytes(mc['raw_body'])}, v)

        with open(self.filepath, 'wb') as f:
            f.write(out)
        n_src = sum(len(c['sources']) for c in p.constraints)
        print(f'[JCNS] Written {len(out)} bytes → {self.filepath} '
              f'(v{v} in place: Cns={len(p.constraints)}, Src={n_src}, Mat={len(p.material_cns)})')
        return True


# Defaults for fields a newly created constraint / source has no value for.
_CNS_DEFAULTS = {
    'ConeDriverInfoOffset': 0, 'PropertyOffset': 0, 'PropertyHash': 0,
    'ConeDriverInfoCount': 0, 'Flags': 0x30, 'TransformType': 1,
    'ParentVec4': (0.0, 0.0, 0.0, 1.0), 'ParentFloat2': (0.0, 0.0),
    'ParentUInt8_72': 0, 'ParentTailBytes': bytes(6),
}
_SOURCE_DEFAULTS = {
    'ComplexMappingInfoOffset': 0, 'SourceHashIndex': 0, 'ComplexMappingInfoCount': 0,
    'UnknownUInt16': 0, 'UpdateTiming': 3, 'SrcTransformID': 3, 'source_axis': 0,
    'UnkByte2': 0, 'UnknownUInt32_2': 0,
    'from_start': 0.0, 'from_kink': 0.0, 'from_end': 0.0,
    'to_start': 0.0, 'to_kink': 0.0, 'to_end': 0.0,
    'rest_quat_x': 0.0, 'rest_quat_y': 0.0, 'rest_quat_z': 0.0, 'rest_quat_w': 1.0,
}


# ── Utilities ────────────────────────────────────────────────────────────

def _align(value, boundary):
    """Round value UP to the next multiple of boundary."""
    rem = value % boundary
    return value if rem == 0 else value + (boundary - rem)


def _pad_to(buf, target):
    """Extend bytearray buf with zeros until len(buf) == target."""
    if len(buf) < target:
        buf.extend(b'\x00' * (target - len(buf)))
