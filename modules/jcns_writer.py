import struct
import os
import sys

from jcns_i18n import T
from jcns_schema import (
    HEADER, CONSTRAINT_INFO, SOURCE_V2, AIM, AIM_TARGET, MATERIAL,
    COMPLEX_MAPPING, OBJECT_SETTING, SKIN, SKIN_SOURCE, SKIN_SOURCE_INFO,
    CONE_DRIVER, CONE_DRIVER_INFO, source_struct, transform_axis_key,
    reconcile_section_table,
)
from jcns_parser import header_field_offset


# ConstraintInfo / ConstraintSource fields the in-place writer takes from the
# edited dicts.  Everything else — pointers, hashes, hash indices, counts — is
# re-packed from the original record, because in place the surrounding data
# (strings, source arrays, hash table) does not move.
INPLACE_CNS_FIELDS = ('Flags', 'TransformType', 'ReservedVec4', 'UnknownFloat2',
                      'UnknownByte72', 'PropertyHash', 'TailBytes')
INPLACE_SRC_FIELDS = ('CurveMode', 'ReadMode', 'source_axis', 'EulerOrder',
                      'UnknownUInt16_22', 'Interpolation', 'ComplexMappingFlag', 'ReservedWord30',
                      'from_start', 'from_kink', 'from_end',
                      'to_start', 'to_kink', 'to_end',
                      'ref_frame_x', 'ref_frame_y', 'ref_frame_z', 'ref_frame_w')


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

            The empty name is a real name: it stores murmur("") = 0x81F16F39.
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
            return c.get('ObjectHashIndex', 0) == 0xFFFFFFFF

        def _target_hash(c):
            """Hash to store in ObjectHash for a direct-hash (non-indexed) target.

            Normally the MurmurHash of ObjectName.  An RSZ object or property
            target (e.g. 'via.motion.Chain') derives ObjectHash from something else,
            so the parser records whether the two agreed in the original file.
            """
            name = c.get('ObjectName', '')
            if name and c.get('ObjectHashMatchesName', True):
                return hashUTF16(name) & 0xFFFFFFFF
            return c.get('ObjectHash', 0)


        # Rebuild hashes for all source and target bones (Range constraints)
        for c in p.constraints:
            for s in c.get('sources', []):
                _, s['SourceHashIndex'] = _get_or_add(s.get('SourceName', ''))

            # Only bone targets go into the hash table; BlendShape/property targets
            # use direct ObjectHash (TgtIdx=0xFFFFFFFF) and must not pollute the list.
            tgt = c.get('ObjectName', '')
            if tgt and not _is_direct_hash(c):
                _get_or_add(tgt)

        # Aim / RotExpression: every hash-list index is re-derived from the hash
        # it stands for (the parser resolves them, and edited entries carry only
        # hashes).  A negative index means "unused" (Aim's up-joint) and stays so.
        for ac in getattr(p, 'aim_constraints', []):
            for idx_key, hash_key in (('JointHashIndex', 'JointHash'),
                                      ('UnkJointHashIndex', 'UnkJointHash'),
                                      ('TargetHashIndex', 'TargetHash')):
                if ac.get(idx_key, -1) >= 0:
                    ac[idx_key] = _get_or_add_hash(ac[hash_key])

        # RotExpression's two index arrays point at the record's own inline
        # SourceJointHash / JointHash.
        for re in getattr(p, 'rot_expressions', []):
            for idx_key, hash_key in (('SrcJointHashIndex', 'SourceJointHash'),
                                      ('JntHashIndex', 'JointHash')):
                if re.get(idx_key, -1) >= 0:
                    re[idx_key] = _get_or_add_hash(re[hash_key])

        # Add Material constraint JointHash indices and update them
        for mc in getattr(p, 'material_cns', []):
            old_idx = mc.get('JointHashIndex', -1)
            if 0 <= old_idx < len(p.hash_list):
                mc['JointHashIndex'] = _get_or_add_hash(p.hash_list[old_idx])

        # SkinConstraint: the object and every source-info entry index the global
        # hash list (carried over verbatim otherwise — see Phase 8f).
        for sk in getattr(p, 'skin_constraints', []):
            sk['ObjectHashIndex'] = _get_or_add_hash(sk['ObjectHash'])
        for si in getattr(p, 'skin_source_infos', []):
            si['SourceHashIndex'] = _get_or_add_hash(si['SourceHash'])

        def _dep_key(c, tgt_h):
            """Object hash the dependency table files a constraint under.

            A bone / blendshape target is filed under its own hash.  A target with
            a property is filed under the hash of "object<sep>property": '.' for
            materials ('face.Blend_A', TransformType 7-10) and ':' for RSZ component
            properties ('via.motion.Chain:BlendRate', TransformType 11).
            """
            prop = c.get('PropertyName', '')
            if not prop:
                return tgt_h
            sep = ':' if c.get('TransformType') == 11 else '.'
            return hashUTF16(c.get('ObjectName', '') + sep + prop) & 0xFFFFFFFF

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

        # The header ends 16-aligned.  The blocks below follow it in this order: ConeDriver[] and their names, ConstraintInfo[], every
        # constraint's ConeDriverInfo[] (16-aligned each), ConstraintSource[].
        # Without ConeDrivers ConstraintInfo starts right at the header's end.
        HEADER_END     = hdr['HeaderEnd']
        SRC_SIZE       = SOURCE_V2.size(version)
        CNS_INFO_SIZE  = N * CONSTRAINT_INFO.size(version)
        axis_key       = transform_axis_key(version)

        # ── Phase 2b: ConeDriver table + names ──────────────────────────
        cones = getattr(p, 'cone_drivers', [])
        N_CONE = len(cones)
        CONE_START = HEADER_END
        cone_blob = bytearray()
        if N_CONE:
            names_at = CONE_START + N_CONE * CONE_DRIVER.size(version)
            name_blob = bytearray()
            recs = []
            for cd in cones:
                # names are 8-aligned
                name_blob.extend(b'\x00' * (_align(names_at + len(name_blob), 8) - (names_at + len(name_blob))))
                name_off = names_at + len(name_blob)
                name_blob.extend(cd['Name'].encode('utf-16le') + b'\x00\x00')
                sym = cd.get('SymmetryJointHash')
                rec = {k: v for k, v in cd.items() if CONE_DRIVER.has(k, version)}
                rec.update({
                    'Name_Offset': name_off,
                    'NameHash': hashUTF16(cd['Name']) & 0xFFFFFFFF,
                    'JointHashIndex': _get_or_add_hash(cd['JointHash']),
                    'ParentJointHashIndex': _get_or_add_hash(cd['ParentJointHash']),
                    'SymmetryJointHashIndex': -1 if sym is None else _get_or_add_hash(sym),
                    'Tail': bytes(cd.get('Tail', b'\x06\x06' + bytes(6))),
                })
                recs.append(rec)
            for rec in recs:
                cone_blob.extend(CONE_DRIVER.pack(rec, version))
            cone_blob.extend(name_blob)
        CNS_INFO_START = _align(CONE_START + len(cone_blob), 16)

        # ── Phase 2c: every constraint's ConeDriverInfo[] ───────────────
        cone_info_blob = bytearray()
        cone_info_at = []
        CONE_INFO_START = CNS_INFO_START + CNS_INFO_SIZE
        for c in p.constraints:
            infos = c.get('ConeDriverInfo') or []
            if not infos:
                cone_info_at.append(0)
                continue
            pos = CONE_INFO_START + len(cone_info_blob)
            cone_info_blob.extend(b'\x00' * (_align(pos, 16) - pos))
            cone_info_at.append(CONE_INFO_START + len(cone_info_blob))
            for ci in infos:
                if not 0 <= ci['ConeDriverIndex'] < N_CONE:
                    raise ValueError(T("core.writer.cone_index", c.get('ObjectName', ''),
                                       ci['ConeDriverIndex'], N_CONE))
                cone_info_blob.extend(CONE_DRIVER_INFO.pack(ci, version))

        # ConstraintSource_v2 section starts after that, 16-aligned.
        raw_src_start = CONE_INFO_START + len(cone_info_blob)
        SRC_START = _align(raw_src_start, 16)

        # ── Phase 3: build ConstraintSource_v2 blobs ───────────────────
        # Layout per constraint:
        #
        #     [Source_v2 #0][Source_v2 #1]…[name #0][name #1]…[pad to 8]
        #
        # The engine reads the structs as one contiguous array, so no name may sit
        # between them.
        src_blob      = bytearray()
        src_offsets   = []  # absolute offset of each constraint's Source_v2 array (0 = none)

        for c in p.constraints:
            srcs = c.get('sources', [])
            if not srcs:
                # SourceCount == 0 (e.g. BlendShape targets): SourceListOffset stays 0.
                src_offsets.append(0)
                continue

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

            # ComplexMappingInfo arrays follow the names, each 16-aligned.
            cm_blob = bytearray()
            cm_offsets = []
            cm_base = names_start + len(name_blob)
            for s in srcs:
                cm = s.get('ComplexMapping') or []
                if len(cm) != s.get('ComplexMappingInfoCount', 0):
                    raise ValueError(T("core.writer.complex_count", s.get('SourceName', ''),
                                       s.get('ComplexMappingInfoCount', 0), len(cm)))
                if not cm:
                    cm_offsets.append(0)
                    continue
                cm_blob.extend(b'\x00' * (_align(cm_base + len(cm_blob), 16) - (cm_base + len(cm_blob))))
                cm_offsets.append(cm_base + len(cm_blob))
                for r in cm:
                    cm_blob.extend(COMPLEX_MAPPING.pack(r, version))

            for s, abs_name, cm_off in zip(srcs, name_offsets, cm_offsets):
                rec = dict(_SOURCE_DEFAULTS)
                rec.update({k: v for k, v in s.items() if not k.startswith('_')})
                rec['SourceName_Offset'] = abs_name
                rec['ComplexMappingInfoOffset'] = cm_off
                # Byte +29 is 1 exactly when the source has ComplexMapping; a source
                # without one may also hold 2, so only a 1 is cleared.
                flag = rec['ComplexMappingFlag']
                rec['ComplexMappingFlag'] = 1 if cm_off else (0 if flag == 1 else flag)
                src_blob.extend(SOURCE_V2.pack(rec, version))

            src_blob.extend(name_blob)
            src_blob.extend(cm_blob)
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
                if (TGT_POOL_START + len(tgt_pool_blob)) % 2:
                    tgt_pool_blob.extend(b'\x00')

        for c in p.constraints:
            _pool(c.get('ObjectName', ''))
        # Property names ('Blend_A', 'BlendRate', ...) — the original PropertyOffset
        # points into the old file, so the string has to be re-emitted.
        for c in p.constraints:
            if c.get('PropertyName'):
                _pool(c['PropertyName'])

        rem = (TGT_POOL_START + len(tgt_pool_blob)) % 8
        if rem:
            tgt_pool_blob.extend(b'\x00' * (8 - rem))

        # ── Phase 5: build Dependency table + data ─────────────────────
        # 8 zero bytes precede the dependency table.
        DEP_PAD_SIZE   = 8
        DEP_TABLE_START = TGT_POOL_START + len(tgt_pool_blob) + DEP_PAD_SIZE

        # DependencyInfo = {uint64 Offset, uint64 SourceCount}, and at Offset
        # {hash ObjectHash; hash SourceHash[SourceCount]}: one entry per driven
        # object with all of its source hashes, not one per (target, source) pair.
        # The target hash comes from the name so renamed bones hash correctly.
        dep_order = []            # target hashes, in first-seen order
        dep_sources = {}          # target hash -> list of source hashes (unique, ordered)
        for c in p.constraints:
            tgt_name = c.get('ObjectName', '')
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
            # A cone-driven constraint depends on each cone's joint.
            for ci in c.get('ConeDriverInfo') or []:
                h = cones[ci['ConeDriverIndex']]['JointHash']
                if h not in bucket:
                    bucket.append(h)

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

        # ── Phase 5b: ObjectSettings (last thing in Section 0) ─────────
        # 16-byte records followed by the hashes they point at.
        obj_settings = getattr(p, 'object_settings', [])
        N_OBJSET = len(obj_settings)
        OBJSET_START = 0
        objset_blob = bytearray()
        if N_OBJSET:
            OBJSET_START = _align(DEP_DATA_START + len(dep_data_blob), 16)
            hashes_at = OBJSET_START + N_OBJSET * OBJECT_SETTING.size(version)
            for i, os_rec in enumerate(obj_settings):
                objset_blob.extend(OBJECT_SETTING.pack(dict(os_rec, HashOffset=hashes_at + 4 * i), version))
            for os_rec in obj_settings:
                objset_blob.extend(struct.pack('<I', os_rec['ObjectNameHash']))

        # ── Phase 6: build SectionTable ────────────────────────────────
        SEC_TABLE_START = (OBJSET_START + len(objset_blob) if N_OBJSET
                           else DEP_DATA_START + len(dep_data_blob))
        rem = SEC_TABLE_START % 4
        if rem:
            SEC_TABLE_START += (4 - rem)

        # The table must list every section that has records and none that is empty.
        orig_table      = getattr(p, 'section_order', None)
        if orig_table is None:
            orig_table = struct.unpack_from('<%dI' % hdr['SectionTableItemCount'], orig, hdr['SectionTableEntry'])
        orig_table      = list(orig_table)
        present = {sid for sid, has in (
            (0, bool(p.constraints)), (1, bool(getattr(p, 'rot_expressions', []))),
            (2, bool(getattr(p, 'skin_constraints', []))), (3, bool(getattr(p, 'aim_constraints', []))),
            (4, bool(getattr(p, 'material_cns', []))),
            (5, getattr(p, 'joint_export_graph', None) is not None)) if has}
        sec_table       = reconcile_section_table(orig_table, present)
        section_blob    = bytearray(struct.pack('<%dI' % len(sec_table), *sec_table))

        # ── Phase 7: build HashTable ────────────────────────────────────
        HASH_TABLE_START = _align(SEC_TABLE_START + len(section_blob), 16)
        hash_blob = bytearray()
        for h in new_hash_list:
            hash_blob.extend(struct.pack('<I', h))

        # ── Phase 8: build ConstraintInfo array ────────────────────────
        cns_info_blob = bytearray()
        group_counts = tail_group_counts(p.constraints)
        for i, c in enumerate(p.constraints):
            tgt_name    = c.get('ObjectName', '')
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
                'SourceListOffset':        src_v2_off,
                'ObjectNameOffset': tgt_name_off,
                'ObjectHashIndex':      tgt_idx,
                'ObjectHash':           tgt_h,
                'ConeDriverInfoOffset': cone_info_at[i],
                'ConeDriverInfoCount':  len(c.get('ConeDriverInfo') or []),
                'PropertyOffset':       (tgt_name_to_offset[c['PropertyName']]
                                         if c.get('PropertyName') else 0),
                # Derived from the source list, never copied: a stale count makes
                # the engine read past the constraint's own sources.
                'SourceCount_parent':   len(c.get('sources', [])),
                axis_key:               c.get('TransformAxis_parent', 0),
            })
            tail = bytearray(rec['TailBytes'])
            if len(tail) >= 4:
                tail[3] = group_counts[i]
            rec['TailBytes'] = bytes(tail)
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
        # Each Aim is an 80-byte record (pointer + body) and a 16-byte target block,
        # carried over with new pointers and remapped hash indices.
        aim_list = getattr(p, 'aim_constraints', [])
        N_AIM = len(aim_list)
        AIM_SECTION_START = 0
        aim_blob = bytearray()
        if N_AIM > 0:
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

        # ── Phase 8f: build SkinConstraint section ──────────────────────
        # Four tables, all carried over as parsed: the records, their weighted
        # source lists, the shared source-info table, and (v36+) the raw-hash
        # ReadJointTable.  Only the hash-list indices were remapped.
        skins = getattr(p, 'skin_constraints', [])
        skin_infos = getattr(p, 'skin_source_infos', [])
        read_joints = getattr(p, 'read_joint_table', [])
        N_SKIN = len(skins)
        SKIN_START = SKIN_INFO_START = READ_JOINT_START = 0
        skin_blob = bytearray()
        if N_SKIN:
            if N_AIM > 0:
                _prev_end = AIM_SECTION_START + len(aim_blob)
            elif jxg is not None:
                _prev_end = JXG_START + len(jxg_blob)
            elif N_MAT > 0:
                _prev_end = MAT_START + len(mat_blob)
            elif N_ROT > 0:
                _prev_end = ROT_INFO_START + len(rot_blob)
            else:
                _prev_end = HASH_TABLE_START + len(hash_blob)
            SKIN_START = _align(_prev_end, 16)
            lists_at = SKIN_START + N_SKIN * SKIN.size(version)
            lists = bytearray()
            recs = bytearray()
            for sk in skins:
                recs.extend(SKIN.pack(dict(sk, SourceListOffset=lists_at + len(lists),
                                           SourceCount=len(sk['sources'])), version))
                for src in sk['sources']:
                    lists.extend(SKIN_SOURCE.pack(src, version))
            skin_blob.extend(recs + lists)
            if skin_infos:
                SKIN_INFO_START = _align(SKIN_START + len(skin_blob), 16)
                skin_blob.extend(b'\x00' * (SKIN_INFO_START - SKIN_START - len(skin_blob)))
                for si in skin_infos:
                    skin_blob.extend(SKIN_SOURCE_INFO.pack(si, version))
            if read_joints:
                READ_JOINT_START = _align(SKIN_START + len(skin_blob), 16)
                skin_blob.extend(b'\x00' * (READ_JOINT_START - SKIN_START - len(skin_blob)))
                skin_blob.extend(struct.pack(f'<{len(read_joints)}I', *read_joints))

        # ── Phase 9: patch header ───────────────────────────────────────
        header = bytearray(orig[:HEADER_END])

        patch = {
            'DependencyTableEntry': DEP_TABLE_START,
            'SectionTableEntry':    SEC_TABLE_START,
            'HashListOffset':       HASH_TABLE_START,
            'ConstraintInfoEntry':  CNS_INFO_START,
            'ConeDriverTableEntry': CONE_START,
            'ConeDriverCount':      N_CONE,
            'HashCount':            len(new_hash_list),
            'ConstraintCount':      N,
            'DependencyCount':      M,
        }
        # ObjectSettingEntry: when the count is 0 it marks Section 0's end boundary
        obj_setting_count = N_OBJSET
        patch['ObjectSettingCount'] = N_OBJSET
        patch['ObjectSettingEntry'] = OBJSET_START if N_OBJSET else SEC_TABLE_START
        # Counts of every list the writer re-emits.  Copying them from the source
        # file would leave a stale count after an entry was added or deleted.
        patch['AimConstraintCount'] = N_AIM
        patch['RotExpressionInfoCount'] = N_ROT
        patch['RotExpressionMapCount'] = len(rot_map)
        patch['MaterialConstraintInfoCount'] = N_MAT
        patch['SectionCount'] = len(sec_table)
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
        patch['SkinConstraintCount'] = N_SKIN
        patch['SkinConstraintSourceCount'] = len(skin_infos) if N_SKIN else 0
        patch['ReadJointTableItemCount'] = len(read_joints) if N_SKIN else 0
        if N_SKIN:
            patch['SkinConstraintTableEntry'] = SKIN_START
            if skin_infos:
                patch['SkinConstraintSourceTableEntry'] = SKIN_INFO_START
            if read_joints:
                patch['ReadJointTableEntry'] = READ_JOINT_START
        HEADER.pack_into(header, hdr['DataEntry'], patch, version)

        # ── Phase 10: assemble ──────────────────────────────────────────
        out = bytearray()
        out.extend(header)                             # Tags + DataInfo header
        out.extend(cone_blob)                          # ConeDriver[] + names
        _pad_to(out, CNS_INFO_START)
        out.extend(cns_info_blob)                      # ConstraintInfo[]
        out.extend(cone_info_blob)                     # ConeDriverInfo[] per constraint
        _pad_to(out, SRC_START)
        out.extend(src_blob)                           # Source_v2 + source WStrings
        out.extend(tgt_pool_blob)                      # Target WString pool
        _pad_to(out, DEP_TABLE_START - DEP_PAD_SIZE)   # 8-byte padding before dep table
        out.extend(b'\x00' * DEP_PAD_SIZE)
        out.extend(dep_table_blob)                     # Dependency table
        out.extend(dep_data_blob)                      # Dependency hash pairs
        if N_OBJSET:
            _pad_to(out, OBJSET_START)
            out.extend(objset_blob)                    # ObjectSettings + their hashes
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
        if N_SKIN:
            _pad_to(out, SKIN_START)
            out.extend(skin_blob)                      # SkinConstraint tables

        with open(self.filepath, 'wb') as f:
            f.write(out)

        print(f'[JCNS] Written {len(out)} bytes → {self.filepath}')
        parts = [f'Cns={N}', f'Aim={N_AIM}', f'RotExpr={N_ROT}', f'Mat={N_MAT}',
                 f'Skin={N_SKIN}', f'ObjSet={N_OBJSET}',
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
            if 'TailBytes' in rec:
                rec['TailBytes'] = bytes(rec['TailBytes'])
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
    'ReservedVec4': (0.0, 0.0, 0.0, 1.0), 'UnknownFloat2': (0.0, 0.0),
    'UnknownByte72': 0, 'TailBytes': bytes(6),
}
_SOURCE_DEFAULTS = {
    'ComplexMappingInfoOffset': 0, 'SourceHashIndex': 0, 'ComplexMappingInfoCount': 0,
    'UnknownUInt16_22': 0, 'CurveMode': 3, 'ReadMode': 3, 'source_axis': 0,
    'EulerOrder': 0, 'Interpolation': 0, 'ComplexMappingFlag': 0, 'ReservedWord30': 0,
    'from_start': 0.0, 'from_kink': 0.0, 'from_end': 0.0,
    'to_start': 0.0, 'to_kink': 0.0, 'to_end': 0.0,
    'ref_frame_x': 0.0, 'ref_frame_y': 0.0, 'ref_frame_z': 0.0, 'ref_frame_w': 1.0,
}


# ── Utilities ────────────────────────────────────────────────────────────

def tail_group_counts(constraints):
    """TailBytes[3] for every constraint: how many of the entries right after it
    the engine folds into its joint group.

    The engine writes a whole group to the *first* entry's target, whatever the others
    name, so a stale count makes neighbours land on the wrong bone.  Counts that
    already form valid groups (members share target, property and TransformType and
    carry 0) are kept; otherwise all are re-derived as the length of each run of
    consecutive entries sharing target, property, TransformType and Flags, minus one,
    and 0 on the rest.
    """
    def ident(c):
        return (c.get('ObjectName', ''), c.get('PropertyName', ''), c.get('TransformType'))

    def given(c):
        tb = c.get('TailBytes') or b''
        return tb[3] if len(tb) >= 4 else 0

    n = len(constraints)
    counts = [given(c) for c in constraints]
    valid = True
    i = 0
    while i < n and valid:
        k = counts[i]
        members = constraints[i + 1:i + 1 + k]
        valid = (len(members) == k
                 and all(ident(m) == ident(constraints[i]) and given(m) == 0 for m in members))
        i += k + 1
    if valid:
        return counts

    counts = []
    i = 0
    while i < n:
        key = ident(constraints[i]) + (constraints[i].get('Flags'),)
        j = i
        while j + 1 < n and ident(constraints[j + 1]) + (constraints[j + 1].get('Flags'),) == key:
            j += 1
        counts += [j - i] + [0] * (j - i)
        i = j + 1
    return counts


def _align(value, boundary):
    rem = value % boundary
    return value if rem == 0 else value + (boundary - rem)


def _pad_to(buf, target):
    if len(buf) < target:
        buf.extend(b'\x00' * (target - len(buf)))
