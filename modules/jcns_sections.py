"""
Editable forms of the non-range sections (MultiConstraint, Aim, RotExpression)
and the rules that regenerate their derived data.  No bpy import.

Editable form = what a person edits (bones as hashes, weights, vectors).
Parser form   = what JCNSParser produces and JCNSWriter consumes.

Derived data:

  MultiConstraint
    * the source-info table is the distinct source bones in first-use order,
      with no repeated hash
    * the record's first tail byte and the source-info u32 are one per-file
      constant, usually 5
    * the other two tail bytes vary per record from v35 on, so each record has
      its own; a new record starts from the file's most common pair
    * ReadJointTable lists the joints whose world matrices the Multi and Aim
      sections read: every multi source, and the parent of every joint they
      write (a result computed in world space is brought back into its parent's
      space).  Written joints are left out, and so is any joint that is an
      ancestor of another listed one.  The list is sorted by hierarchy depth;
      order within a depth does not matter, since no two entries are related.
      Aim targets and up joints are not in it.  Deriving it needs the skeleton.
      A file without a table (player and NPC rigs) keeps none.
  Multi (measured, round 12): the target's position is the linear blend of its sources'
    skinning matrices with the weights divided by their sum; the rotation is the
    normalized sum of the weighted source rotations, each flipped to the running sum's
    hemisphere.  A file's section table has to list the section (2) for it to run.
  Aim
    * measured (rounds 12 and 14): local Vec1 points at the target and local Vec2 is the axis
      lined up with "up".  WorldUpType 0 takes up from world +Y (Vec3 has no effect), 3 from
      the world direction Vec3, 1 from the up joint's position, 2 from the up joint's own +Y
      axis (tested with Vec3 (0,1,0)), 4 is the shortest arc from the rest pose, 5 the
      shortest arc from the parent's orientation alone (the rest pose is dropped).
      Vec0 is an XYZ Euler offset in radians (Rz*Ry*Rx) multiplied on the right of the look-at result
      (round 17); with WorldUpType 2 the up reference is the up joint's local axis Vec3 selects.
      Influence other than 1 is degenerate: type 0 leaves the world rotation almost constant
      (rotated 180 deg between 0.25 and 2.0), types 1 and 4 match no blend model.  Every shipped
      record has 1.0.
    * no derived data besides the target block; an unused up-joint is -1; the
      record's 12 tail bytes and the target block's 8 tail bytes are always zero
  RotExpression
    * byte[1] = 0 replaces the rest pose, 48 gives rest * value.  Coefficients (1,1,1) copy
      the source rotation exactly; other coefficients scale each axis for small angles and
      deviate for large ones (single-axis results are pure rotations about that axis, angle
      unexplained)
    * the two hash-index arrays point at the record's inline JointHash /
      SourceJointHash
    * the map holds one value per entry, the same for all of them
"""

import json
import struct

from jcns_i18n import T
from jcns_schema import ROT_EXPRESSION


# ── MultiConstraint ─────────────────────────────────────────────────────────

def multi_editable(parser):
    """(records, meta) from a parsed file.

    records: [{'object': hash, 'tail': 2 bytes, 'sources': [{'hash': h, 'weight': w}, ...]}, ...]
    meta:    {'constant': int, 'read_joint_table': [hash, ...]}
    """
    infos = parser.multi_source_infos
    records = []
    for sk in parser.multi_constraints:
        srcs = []
        for s in sk['sources']:
            ref = s['SourceRef']
            # v29+ index the source-info / source-hash table; before that the hash is inline
            h = infos[ref]['SourceHash'] if parser.version >= 29 else ref
            srcs.append({'hash': h, 'weight': s['Weight']})
        records.append({'object': sk['ObjectHash'], 'tail': bytes(sk['Tail'][1:3]), 'sources': srcs})
    if parser.multi_constraints:
        constant = parser.multi_constraints[0]['Tail'][0]
    elif parser.aim_constraints:
        constant = parser.aim_constraints[0]['inline_body'][59]
    else:
        constant = file_constant_default(parser.version)
    return records, {'constant': constant, 'read_joint_table': list(parser.read_joint_table)}


# The file constant is one byte shared by every Multi tail[0], every Multi source info
# and every Aim +59 of a file.
_FILE_CONSTANT_BY_VERSION = {35: 0xFF, 36: 0xFF}


def file_constant_default(version):
    return _FILE_CONSTANT_BY_VERSION.get(version, 5)


# Shipped v36 records all end 00 01; elsewhere a file with no record falls back to zero.
_MULTI_TAIL_BY_VERSION = {36: b'\x00\x01'}


def multi_default_tail(records, version=102):
    """Tail bytes for a new record: the file's most common, else the version's."""
    tails = [bytes(r['tail']) for r in records]
    return max(set(tails), key=tails.count) if tails else _MULTI_TAIL_BY_VERSION.get(version, bytes(2))


def multi_parser_form(records, meta):
    """(multi_constraints, multi_source_infos) for JCNSWriter (v35+ layout).

    Hash-list indices are placeholders: the writer remaps every one of them
    from the hash it stands for.
    """
    order = []
    index = {}
    for r in records:
        for s in r['sources']:
            if s['hash'] not in index:
                index[s['hash']] = len(order)
                order.append(s['hash'])
    const = meta.get('constant', 5) & 0xFF
    multis = [{
        'ObjectHash': r['object'], 'ObjectHashIndex': 0,
        'Tail': bytes([const]) + bytes(r['tail']),
        'SourceCount': len(r['sources']),
        'sources': [{'SourceRef': index[s['hash']], 'Weight': float(s['weight'])} for s in r['sources']],
    } for r in records]
    infos = [{'SourceHash': h, 'SourceHashIndex': 0, 'UnknownUInt32': const} for h in order]
    return multis, infos


def read_joint_signature(records, aim_joints):
    """The structure a ReadJointTable depends on: multi objects and their
    source bones in order, and the Aim joints — everything except weights and
    the Aim's own settings."""
    return {'multi': [[r['object'], [s['hash'] for s in r['sources']]] for r in records],
            'aim': list(aim_joints)}


def derive_read_joint_table(records, aim_joints, parent):
    """(table, missing) from the Multi records, the Aim joints and the skeleton.

    `parent` maps a joint hash to its parent's hash (None for a root).  Joints
    the skeleton does not know are returned in `missing`, and the table is then
    not trustworthy.  See the module docstring for the rule.
    """
    missing = []

    def up(h):
        if h not in parent:
            if h not in missing:
                missing.append(h)
            return None
        return parent[h]

    written = {r['object'] for r in records}
    wanted = [s['hash'] for r in records for s in r['sources']]
    wanted += [up(r['object']) for r in records]
    wanted += [up(j) for j in aim_joints]
    need = []
    for h in wanted:
        if h is not None and h not in written and h not in need:
            need.append(h)

    ancestors, depth = set(), {}
    for h in need:
        d, q = 0, up(h)
        while q is not None:
            ancestors.add(q)
            d += 1
            q = up(q)
        depth[h] = d
    return sorted((h for h in need if h not in ancestors), key=depth.get), missing


def resolve_read_joint_table(records, aim_joints, meta, locked, parent=None, names=None, pending=False):
    """(table, problems) to export with.

    A file without a table keeps none.  An unchanged structure keeps the shipped
    table verbatim, including its order.  A changed one is re-derived when the
    skeleton is available and refused when it is not.  `pending` is a file upgraded
    to a version that has a table the source never had: it is always derived.
    """
    orig = list(meta.get('read_joint_table') or [])
    if not pending and (not orig or locked == read_joint_signature(records, aim_joints)):
        return orig, []
    if parent is None:
        return orig, [T("core.sections.need_armature_pending") if pending
                      else T("core.sections.need_armature_changed")]
    table, missing = derive_read_joint_table(records, aim_joints, parent)
    if missing:
        label = lambda h: (names or {}).get(h, f"0x{h:08X}")
        return orig, [T("core.sections.missing_joints",
                        T("core.list_sep").join(label(h) for h in missing[:8]))]
    return table, []


def multi_weight_warnings(records, names=None):
    """Records whose weights do not sum to 1.  Shipped records can sum to 0.9,
    so this warns rather than refuses."""
    out = []
    for i, r in enumerate(records):
        w = sum(s['weight'] for s in r['sources'])
        if r['sources'] and abs(w - 1.0) > 1e-3:
            label = (names or {}).get(r['object'], f"0x{r['object']:08X}")
            out.append(T("core.sections.multi_weight_sum", i, label, w))
    return out


# ── Aim ────────────────────────────────────────────────────────────────────

def aim_default_bytes(records, constant):
    """Bytes +58..59 for a new record: the file's most common, else 0 and the file constant."""
    pairs = [tuple(r) for r in records]
    return max(set(pairs), key=pairs.count) if pairs else (0, constant & 0xFF)


def aim_editable(parser):
    out = []
    for a in parser.aim_constraints:
        body = a['inline_body']                   # 2 hash indices + 64-byte body
        vecs = [struct.unpack_from('<3f', body, 8 + 12 * k) for k in range(4)]
        out.append({
            'joint': a['JointHash'],
            # v35+ mark an unused up-joint with index -1; older files store the hash inline
            'up': (a['UnkJointHash'] if (a['UnkJointHashIndex'] >= 0 if parser.version >= 35
                                         else a['UnkJointHash']) else None),
            'target': a['TargetHash'],
            'influence': struct.unpack_from('<f', a['target_body'], 0)[0],
            # byte +57 (bytes[0]) is the target count; aim_parser_form derives it
            'target2': a.get('Target2Hash'),
            'weight2': (struct.unpack_from('<f', a['target_body'], 8)[0]
                        if a.get('Target2Hash') is not None else 0.0),
            'vectors': vecs,
            'world_up_type': body[56],
            'bytes': tuple(body[57:60]),
        })
    return out


def aim_parser_form(records):
    out = []
    for r in records:
        body = bytearray(72)
        for k, v in enumerate(r['vectors']):
            struct.pack_into('<3f', body, 8 + 12 * k, *v)
        body[56] = r['world_up_type'] & 0xFF
        body[57:60] = bytes(b & 0xFF for b in r['bytes'])
        t2 = r.get('target2')
        body[57] = 1 if t2 is None else 2
        up = r.get('up')
        out.append({
            'JointHashIndex': 0, 'JointHash': r['joint'],
            'UnkJointHashIndex': 0 if up is not None else -1, 'UnkJointHash': up or 0,
            'TargetHashIndex': 0, 'TargetHash': r['target'],
            'Target2HashIndex': -1 if t2 is None else 0, 'Target2Hash': t2,
            'inline_body': bytes(body),
            'target_body': struct.pack('<f', r['influence']) + (
                bytes(8) if t2 is None else struct.pack('<If', 0, r.get('weight2', 0.0))),
        })
    return out


# ── RotExpression ──────────────────────────────────────────────────────────

def rot_editable(parser):
    out = []
    for r in parser.rot_expressions:
        rec = ROT_EXPRESSION.read(r['info_raw'], 0, parser.version)
        tail = rec['Tail']
        out.append({
            'joint': rec['JointHash'], 'source': rec['SourceJointHash'],
            'rotation': rec['Rotation'], 'scale': rec['Scale'],
            'bytes': tuple(tail[:4]), 'floats': struct.unpack_from('<3f', tail, 4),
        })
    values = list(parser.rot_expression_map)
    return out, {'map_value': values[0] if values else 0, 'map_uniform': len(set(values)) <= 1}


def rot_parser_form(records, meta, version=102):
    new_map = [meta['map_value'] & 0xFF] * len(records)
    out = []
    for r in records:
        tail = bytes(b & 0xFF for b in r['bytes']) + struct.pack('<3f', *r['floats'])
        raw = ROT_EXPRESSION.pack({'Rotation': tuple(r['rotation']), 'Scale': tuple(r['scale']),
                                   'JointHash': r['joint'], 'SourceJointHash': r['source'],
                                   'Tail': tail}, version)
        out.append({'JointHash': r['joint'], 'SourceJointHash': r['source'],
                    'SrcJointHashIndex': 0, 'JntHashIndex': 0, 'info_raw': raw})
    return out, bytes(new_map)


# ── ConeInput across versions ───────────────────────────────────────────────

# Tail[0] and Tail[1] of a ConeInput are ConeAxis values (0 X, 1 Y, 2 Z, 3 -X, 4 -Y, 5 -Z,
# 6 Vector).  Before v35 they name the measured axis and the reference axis directly (RE4:
# Y or -Y, and X) and there is no Matrix; v35 files write 6 and let Matrix say which axis it is.
# The flag byte sits at Tail[2] before v35 and at Tail[3] from v35.
CONE_AXIS_X, CONE_AXIS_VECTOR = 0, 6
IDENTITY_MATRIX = (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0)


def _swap_flag_byte(tail):
    t = bytearray(bytes(tail).ljust(8, b'\x00')[:8])
    t[2], t[3] = t[3], t[2]
    return t


_AXIS_ENUM = {(1, 0, 0): 0, (0, 1, 0): 1, (0, 0, 1): 2, (-1, 0, 0): 3, (0, -1, 0): 4, (0, 0, -1): 5}


def _axis_enum(vec):
    """The ConeAxis value of a unit coordinate-axis vector, else None."""
    ints = tuple(round(x) for x in vec)
    return _AXIS_ENUM.get(ints) if all(abs(x - i) < 1e-4 for x, i in zip(vec, ints)) else None


def _matrix_axes(matrix):
    """(measured axis, reference axis) a Vector cone's Matrix stands for, as ConeAxis values, None
    for one it cannot name.  The measured axis is the Matrix's Y image (its column 1); the
    reference axis counts only when it is X, where the fixed X axis and the Matrix's row 0 agree."""
    m = tuple(matrix)
    measured = _axis_enum((m[1], m[5], m[9]))
    reference = _axis_enum(m[0:3])
    return measured, (CONE_AXIS_X if reference == CONE_AXIS_X else None)


def convert_cone_inputs(cones, from_version, version):
    """The ConeInput table of a file in another version, as (cones, index map, lost).

    The index map sends an old ConeInputIndex to its new one, or to None when the cone cannot
    be written in `version`.  `lost` counts symmetry joints dropped by a version without them.
    Cones between two versions on the same side of 35 are returned unchanged."""
    out, index_map, lost = [], {}, 0
    for i, cd in enumerate(cones):
        cd = dict(cd)
        tail = bytes(cd.get('Tail') or bytes(8))
        if from_version < 35 <= version:
            cd['Matrix'] = IDENTITY_MATRIX
            cd['Tail'] = bytes(_swap_flag_byte(tail))
            cd['SymmetryJointHash'] = None
            cd['UnknownUInt32'] = 0
        elif version < 35 <= from_version:
            measured, reference = tail[0], tail[1]
            if CONE_AXIS_VECTOR in (measured, reference):
                m_axis, r_axis = _matrix_axes(cd['Matrix'])
                measured = m_axis if measured == CONE_AXIS_VECTOR else measured
                reference = r_axis if reference == CONE_AXIS_VECTOR else reference
                if measured is None or reference is None:
                    index_map[i] = None
                    continue
            lost += cd.get('SymmetryJointHash') is not None
            cd['Tail'] = bytes(_swap_flag_byte(bytes([measured, reference]) + tail[2:]))
            cd['Translation'] = (0.0, 0.0, 0.0, 0.0)
            cd['SymmetryJointHash'] = None
        index_map[i] = len(out)
        out.append(cd)
    return out, index_map, lost


def convert_cone_drivers(drivers, index_map, version):
    """A constraint's ConeDriver list for the converted table, as (drivers, dropped).  An entry
    whose cone was dropped goes, and so does a Function curve where `version` has no CurveData."""
    out, dropped = [], 0
    for d in drivers:
        idx = d['ConeInputIndex']
        new = idx if idx == 255 else index_map.get(idx)
        if new is None or (version < 24 and (d.get('CurveType') or d.get('Curve'))):
            dropped += 1
            continue
        out.append(dict(d, ConeInputIndex=new))
    return out, dropped
