"""
Re-express a parsed older file as a newer version, so it can be written with the
rebuild writer.  Import any version, export the game's latest: the upgrade is the
step between the two.

Only the Wilds step v29 -> v102 exists.  A step takes a parsed JCNSParser and returns
a parser-like object in the target layout (what jcns_exporter._build_stub_parser
builds), which JCNSWriter rebuilds.  No bpy import.

v29 -> v102 differences, measured on the shipped pairs of the same file:

  OutputData  gains a hash-table index and a AttrFlags byte.  AttrFlags bit 0 is the old
                  first byte block's first byte; bits 4/5 follow the transform type.
                  The old +2 byte becomes UnknownByte72; the +4 pair and the +73 byte
                  (the joint-group count) move into the tail.  A non-bone target is
                  named by raw hash (index 0xFFFFFFFF).
  Skin / Aim / RotExpression  hold the same data; v102 stores hash-table indices where
                  v29 stores raw hashes, and the file constant shows up in
                  the Skin tail, the Aim bytes and the source-info u32.
  ReadJointTable  new in v36; derived from the skeleton (jcns_sections).
"""

import os
import sys

import jcns_flags
import jcns_sections as X
from jcns_i18n import T
from jcns_parser import read_header
from jcns_schema import file_header


sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'hashing'))
from mmh3.pymmh3 import hashUTF16  # noqa: E402


class UpgradeError(ValueError):
    """The file uses something the step cannot carry across."""


UPGRADE_STEPS = {(29, 102)}

# v102 repeats one byte in the Skin tail, the Skin source-info u32 and the Aim bytes; it is 5 in
# every shipped file.
FILE_CONSTANT = 5

_EMPTY_SECTIONS = ('aim_constraints', 'object_settings', 'skin_constraints', 'skin_source_infos',
                   'read_joint_table', 'cone_inputs', 'rot_expressions', 'material_cns')


def can_upgrade(src_version, dst_version):
    return src_version == dst_version or (src_version, dst_version) in UPGRADE_STEPS


def latest_version(version):
    """The newest version `version` can be upgraded to; itself when it has no step."""
    while True:
        nxt = [dst for src, dst in UPGRADE_STEPS if src == version]
        if not nxt:
            return version
        version = max(nxt)


class _Upgraded:
    """Parser-like object JCNSWriter accepts."""


def upgrade(parser, dst_version=102, parent=None, names=None):
    """(parser-like in dst_version layout, problems).  `problems` is non-empty when
    the ReadJointTable has to be derived and cannot be (no skeleton, or it lacks a
    joint); the result then has no table."""
    src = parser.version
    if src == dst_version:
        return parser, []
    if (src, dst_version) not in UPGRADE_STEPS:
        raise UpgradeError(T("io.upgrade.no_step", src, dst_version))
    return _upgrade_29_to_102(parser, parent, names)


def _upgrade_29_to_102(p, parent, names):
    if p.cone_inputs:
        raise UpgradeError(T("io.upgrade.v29_cone"))
    const = FILE_CONSTANT

    out = _Upgraded()
    for k in _EMPTY_SECTIONS:
        setattr(out, k, [])
    out.joint_export_graph = p.joint_export_graph
    out.rot_expression_map = b''
    out.filepath = p.filepath
    out.version = 102
    out.write_mode = 'rebuild'
    unknown = (p.header.get('HeaderUnknownByte1', 0), p.header.get('HeaderUnknownByte2', 0))
    out.original_bytes = file_header(102, unknown)
    out.header = read_header(out.original_bytes, check_layout=False)
    out.section_order = list(p.section_order)
    out.hash_list = []
    out.object_settings = [dict(o) for o in p.object_settings]

    out.constraints = [_upgrade_constraint(c, const) for c in p.constraints]

    # Material joints are raw hashes in v29 and hash-list indices in v102.
    for m in p.material_cns:
        out.material_cns.append({'JointHashIndex': 0, 'JointHash': m['JointHash'],
                                 'raw_body': m['raw_body']})

    problems = []
    if p.skin_constraints:
        records, meta = X.skin_editable(p)
        meta['constant'] = const
        for r in records:
            r['tail'] = bytes(r['tail'])
        aim_joints = [a['joint'] for a in X.aim_editable(p)]
        table, problems = _read_joint_table(records, aim_joints, parent, names)
        meta['read_joint_table'] = table
        out.skin_constraints, out.skin_source_infos = X.skin_parser_form(records, meta)
        out.read_joint_table = table

    if p.aim_constraints:
        aims = X.aim_editable(p)
        for a in aims:
            a['bytes'] = (a['bytes'][0], a['bytes'][1], const)
        out.aim_constraints = X.aim_parser_form(aims)

    if p.rot_expressions:
        rots, meta = X.rot_editable(p)
        out.rot_expressions, out.rot_expression_map = X.rot_parser_form(rots, meta, 102)

    out.hash_list = _hash_order(out)
    for m in out.material_cns:
        m['JointHashIndex'] = out.hash_list.index(m['JointHash'])
    return out, problems


def _hash_order(f):
    """The hash list in the order the game's own tool fills it: each Range target then its
    sources, RotExpression source then joint, each Skin object then its sources, each Aim
    joint, up joint, target, and the Material joints last."""
    order = []

    def add(h):
        if h not in order:
            order.append(h)

    for c in f.constraints:
        if c['ObjectName'] and c['ObjectHashIndex'] != 0xFFFFFFFF:
            add(c['TargetHash'])
        for s in c['sources']:
            add(hashUTF16(s['SourceName']) & 0xFFFFFFFF)
    for r in f.rot_expressions:
        add(r['SourceJointHash'])
        add(r['JointHash'])
    infos = f.skin_source_infos
    for sk in f.skin_constraints:
        add(sk['ObjectHash'])
        for s in sk['sources']:
            add(infos[s['SourceRef']]['SourceHash'])
    for a in f.aim_constraints:
        add(a['JointHash'])
        if a['UnkJointHashIndex'] >= 0:
            add(a['UnkJointHash'])
        add(a['TargetHash'])
    for m in f.material_cns:
        add(m['JointHash'])
    return order


def _read_joint_table(records, aim_joints, parent, names):
    if parent is None:
        return [], [T("io.upgrade.need_skeleton")]
    table, missing = X.derive_read_joint_table(records, aim_joints, parent)
    if missing:
        label = lambda h: (names or {}).get(h, f"0x{h:08X}")
        return [], [T("io.upgrade.missing_bones", T("io.sep.list").join(label(h) for h in missing[:8]))]
    return table, []


def _upgrade_constraint(c, const):
    keep = ('ObjectName', 'PropertyName', 'ObjectHash', 'PropertyHash', 'ObjectHashMatchesName',
            'ReservedVec4', 'UnknownFloat2', 'TransformElement', 'ConeDriver',
            'sources', 'TargetHash')
    d = {k: c[k] for k in keep if k in c}
    d['sources'] = [_upgrade_source(s) for s in c['sources']]
    d['Axis_parent'] = d['target_axis'] = c['Axis_pre35']
    d['JointDriverCount'] = len(c['sources'])
    d['UnknownByte72'] = c['UnkByte_Pre35_2']
    name = TRANSFORM_TYPE_NAMES.get(c['TransformElement'])
    d['AttrFlags'] = jcns_flags.apply_derived_bits(c['UnkByte_Pre35_0'], name)
    # A target that is not a bone (blend shape, material, component property) is named by
    # its raw hash, not a hash-list index.
    expected = jcns_flags.expected_bits(name)
    d['ObjectHashIndex'] = 0xFFFFFFFF if expected and not expected[0] else 0
    # The old +4 pair and the +73 byte (how many following entries join this one's joint
    # group) land in the tail.
    tail = bytearray(c['UnkBytes_Pre35_4'] + c['TailBytes'][2:])
    tail[3] = c['UnkByte_Pre35_73']
    d['TailBytes'] = bytes(tail)
    return d


def _upgrade_source(s):
    d = {k: v for k, v in s.items() if not k.startswith('_') and k not in ('SourceHash', 'SourceName_Offset')}
    d['SourceHashIndex'] = 0
    return d


TRANSFORM_TYPE_NAMES = {
    0: 'Translation', 1: 'Rotation', 2: 'Scale', 3: 'BlendShape',
    4: 'SwingTwist', 5: 'TwistSwing', 6: 'RotationVector', 7: 'Material_Color',
    8: 'Material_4D', 9: 'Material_3D', 10: 'Material_2D', 11: 'Scalar',
    12: 'Unknown_12', 13: 'AxisRotation', 14: 'AxisRotation_14',
    15: 'UnkRotation_15', 16: 'UnkRotation_16',
}
