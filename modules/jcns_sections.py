"""
jcns_sections.py
----------------
Editable forms of the non-range sections (SkinConstraint, Aim, RotExpression)
and the rules that regenerate their derived data.  Kept free of any `bpy`
import so the rules can be checked against the shipped corpus offline.

Editable form = what a person edits (bones as hashes, weights, vectors).
Parser form   = what JCNSParser produces and JCNSWriter consumes.

Derived data and the evidence for each rule (1103 shipped v102 files):

  SkinConstraint
    * the source-info table is the distinct source bones in first-use order,
      with no repeated hash                                      (90/90 files)
    * the record tail byte and the source-info u32 are one per-file constant,
      usually 5                                                  (90/90)
    * ReadJointTable (SkinConstraintHashTable in bt / REE-Lib, though Skin
      shares it with Aim) lists the joints whose world matrices the Skin and Aim sections read: every skin
      source, and the parent of every joint they write (a result computed in
      world space has to be brought back into its parent's space).  Written
      joints themselves are left out, and so is any joint that is an ancestor
      of another listed one — walking up from the deepest ones covers it.  The
      list is sorted by hierarchy depth.  Aim targets and up joints are not in
      it.  Set 42/42, depth order 42/42; ties within a depth follow first use
      in 23/42, the rest look like the authoring tool's container order, which
      cannot matter since no two entries are related.  It needs the skeleton
      (see derive_read_joint_table).  Only monster rigs carry one: player and NPC
      files with Skin or Aim sections leave it empty (0 of 65), so an empty
      table stays empty.
  Aim
    * no derived data besides the target block; an unused up-joint is -1
      (180/277); the 12 tail bytes and the target block's 8 tail bytes are
      always zero, but are carried rather than assumed
  RotExpression
    * the two hash-index arrays point at exactly the record's inline JointHash /
      SourceJointHash                                            (57/57)
    * the map holds one value per file; new entries repeat it
"""

import struct

from jcns_schema import ROT_EXPRESSION


# ── SkinConstraint ─────────────────────────────────────────────────────────

def skin_editable(parser):
    """(records, meta) from a parsed file.

    records: [{'object': hash, 'sources': [{'hash': h, 'weight': w}, ...]}, ...]
    meta:    {'constant': int, 'read_joint_table': [hash, ...]}
    """
    infos = parser.skin_source_infos
    records = []
    for sk in parser.skin_constraints:
        srcs = []
        for s in sk['sources']:
            ref = s['SourceRef']
            # v29+ index the source-info / source-hash table; before that the hash is inline
            h = infos[ref]['SourceHash'] if parser.version >= 29 else ref
            srcs.append({'hash': h, 'weight': s['Weight']})
        records.append({'object': sk['ObjectHash'], 'sources': srcs})
    constant = parser.skin_constraints[0]['Tail'][0] if parser.skin_constraints else 5
    return records, {'constant': constant, 'read_joint_table': list(parser.read_joint_table)}


def skin_parser_form(records, meta):
    """(skin_constraints, skin_source_infos) for JCNSWriter (v35+ layout).

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
    skins = [{
        'ObjectHash': r['object'], 'ObjectHashIndex': 0,
        'Tail': bytes([const, 0, 0]),
        'SourceCount': len(r['sources']),
        'sources': [{'SourceRef': index[s['hash']], 'Weight': float(s['weight'])} for s in r['sources']],
    } for r in records]
    infos = [{'SourceHash': h, 'SourceHashIndex': 0, 'UnknownUInt32': const} for h in order]
    return skins, infos


def read_joint_signature(records, aim_joints):
    """The structure a ReadJointTable depends on: skin objects and their
    source bones in order, and the Aim joints — everything except weights and
    the Aim's own settings."""
    return {'skin': [[r['object'], [s['hash'] for s in r['sources']]] for r in records],
            'aim': list(aim_joints)}


def derive_read_joint_table(records, aim_joints, parent):
    """(table, missing) from the Skin records, the Aim joints and the skeleton.

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


def resolve_read_joint_table(records, aim_joints, meta, locked, parent=None, names=None):
    """(table, problems) to export with.

    A file without a table keeps none.  An unchanged structure keeps the shipped
    table verbatim, including its order.  A changed one is re-derived when the
    skeleton is available and refused when it is not.
    """
    orig = list(meta.get('read_joint_table') or [])
    if not orig or locked == read_joint_signature(records, aim_joints):
        return orig, []
    if parent is None:
        return orig, ["这个文件带读取骨表（ReadJointTable），它由 Skin/Aim 的骨骼按骨架层级推出；"
                      "改动了 Skin 对象、源骨骼或 Aim 骨骼，需要先在根节点设置目标骨架才能重算。"]
    table, missing = derive_read_joint_table(records, aim_joints, parent)
    if missing:
        label = lambda h: (names or {}).get(h, f"0x{h:08X}")
        return orig, ["重算读取骨表时目标骨架里找不到这些骨骼：%s"
                      % "、".join(label(h) for h in missing[:8])]
    return table, []


def skin_weight_warnings(records, names=None):
    """Records whose weights do not sum to 1 (6 of 1851 shipped ones sum to 0.9,
    so this warns rather than refuses)."""
    out = []
    for i, r in enumerate(records):
        w = sum(s['weight'] for s in r['sources'])
        if r['sources'] and abs(w - 1.0) > 1e-3:
            label = (names or {}).get(r['object'], f"0x{r['object']:08X}")
            out.append(f"Skin #{i}（{label}）权重和为 {w:.3f}")
    return out


# ── Aim ────────────────────────────────────────────────────────────────────

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
            'vectors': vecs,
            'rotation_type': body[56],
            'bytes': tuple(body[57:60]),
            'tail': bytes(body[60:72]),
            'target_tail': bytes(a['target_body'][4:12]),
        })
    return out


def aim_parser_form(records):
    out = []
    for r in records:
        body = bytearray(72)
        for k, v in enumerate(r['vectors']):
            struct.pack_into('<3f', body, 8 + 12 * k, *v)
        body[56] = r['rotation_type'] & 0xFF
        body[57:60] = bytes(b & 0xFF for b in r['bytes'])
        body[60:72] = r.get('tail', bytes(12))
        up = r.get('up')
        out.append({
            'JointHashIndex': 0, 'JointHash': r['joint'],
            'UnkJointHashIndex': 0 if up is not None else -1, 'UnkJointHash': up or 0,
            'TargetHashIndex': 0, 'TargetHash': r['target'],
            'inline_body': bytes(body),
            'target_body': struct.pack('<f', r['influence']) + r.get('target_tail', bytes(8)),
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
    return out, {'map': list(parser.rot_expression_map)}


def rot_parser_form(records, meta, version=102):
    old_map = meta.get('map', [])
    n = len(records)
    if len(old_map) == n:
        new_map = old_map
    elif len(set(old_map)) <= 1:
        new_map = [old_map[0] if old_map else 0] * n
    else:
        raise ValueError("RotExpressionMap 在这个文件里不是单一常量，无法为增删的条目推导，"
                         "RotExpression 的条目数不能改。")
    out = []
    for r in records:
        tail = bytes(b & 0xFF for b in r['bytes']) + struct.pack('<3f', *r['floats'])
        raw = ROT_EXPRESSION.pack({'Rotation': tuple(r['rotation']), 'Scale': tuple(r['scale']),
                                   'JointHash': r['joint'], 'SourceJointHash': r['source'],
                                   'Tail': tail}, version)
        out.append({'JointHash': r['joint'], 'SourceJointHash': r['source'],
                    'SrcJointHashIndex': 0, 'JntHashIndex': 0, 'info_raw': raw})
    return out, bytes(new_map)
