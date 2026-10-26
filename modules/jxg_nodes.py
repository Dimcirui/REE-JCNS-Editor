"""
jxg_nodes.py
------------
What the add-on knows about JointExprGraph node types, and graph edits that keep
a graph dict from jxg_format writable.

The slot catalog (data/jxg_nodes.json, built by tools/build_jxg_nodes.py) lists
the slots shipped files use for each type.  Slot names below are only the ones
with a known meaning; `certain` is True where the node's code in the game was read
(docs/jntexprgraph.md), False where the name is inferred from use.

Managed nodes (`app.*`) are game C# classes.  Their parameters are opaque to the
add-on: edits keep their props, extra data and outputs exactly as read; only
links into and out of them can change.

No `bpy` import, so it stays testable without Blender.
"""

import json
import uuid

import jxg_format

_catalog = None


def catalog():
    """type name -> {'hash', and for corpus types 'kind', 'count', 'inputs', 'outputs'}."""
    global _catalog
    if _catalog is None:
        with open(jxg_format.NODES_PATH, encoding='utf-8') as f:
            _catalog = json.load(f)
    return _catalog


def is_managed(type_name):
    return not type_name.startswith('via.')


def short_name(type_name):
    return type_name.rsplit('.', 1)[-1]


def input_slots(type_name):
    """[(slot, value type, 'prop' | 'link' | 'both')] seen in shipped files; [] when unknown."""
    return [tuple(s) for s in catalog().get(type_name, {}).get('inputs', [])]


def output_slots(type_name):
    return [tuple(s) for s in catalog().get(type_name, {}).get('outputs', [])]


def creatable_types():
    """Native types the catalog has full slot information for."""
    return sorted(n for n, e in catalog().items() if 'kind' in e and not is_managed(n))


# ------------------------------------------------------------------ slot names

_JOINT_IN = {0: ('joint', True), 1: ('lod', True), 2: ('space', True), 3: ('rot_order', True),
             5: ('unit', True), 6: ('rot_unit', True)}
_JOINT_VALUE = {10: ('position', True), 11: ('rotation', True), 12: ('scale', True), 13: ('euler', True),
                20: ('x', True), 21: ('y', True), 22: ('z', True)}
_BINARY = ('FloatAddNode', 'FloatSubNode', 'FloatMulNode', 'FloatDivNode', 'FloatMinNode',
           'Vec3AddNode', 'Vec3SubNode', 'Vec3MulNode', 'QuatMulNode')
# app.expr_node.SkirtSubJointNode: its C# fields in declaration order are its slots
_SKIRT_SUB = {0: 'sel_parent_jnt', 1: 'L_MOT_jnt', 2: 'R_MOT_jnt', 3: 'L_MOT_jnt_upper_point',
              4: 'R_MOT_jnt_upper_point', 5: 'L_MOT_jnt_lower_point', 6: 'R_MOT_jnt_lower_point',
              7: 'keep_1_range', 8: 'leg_length', 9: 'cone_angle', 11: 'L_leg_vector_offset_angle',
              12: 'R_leg_vector_offset_angle', 13: 'compare_vector_limit_angle'}


# Input slots whose meaning the preview models (modules/jxg_eval.py); (name, certain)
_INPUTS = {
    'FloatValueNode': {0: ('value', True)},
    'Vec3ValueNode': {0: ('value', True)},
    'QuatValueNode': {0: ('value', True)},
    'CyclicalAngleNode': {1: ('period', True)},
    'SinWaveNode': {1: ('period', True), 2: ('low', True), 3: ('high', True)},
    'CosWaveNode': {1: ('period', True), 2: ('low', True), 3: ('high', True)},
    'SawToothWaveNode': {1: ('period', True), 2: ('start', True), 3: ('end', True)},
    'FloatMapNode': {0: ('input', True), 1: ('in_min', True), 2: ('in_max', True), 3: ('out_min', True),
                     4: ('out_max', True), 5: ('clamp', True)},
    'FloatSwitchNode': {0: ('condition', True), 1: ('if_false', True), 2: ('if_true', True)},
    'FloatEaseCurveNode': {0: ('start', True), 1: ('end', True), 2: ('t', True)},
    'FloatClampNode': {0: ('value', True), 1: ('minimum', True), 2: ('maximum', True)},
    'MaFloatRemapNode': {0: ('input', True), 1: ('in_points', True), 2: ('out_points', True),
                         3: ('interpolation', True), 4: ('use_mid', True)},
    'QuatSlerpNode': {0: ('a', True), 1: ('b', True), 2: ('t', True)},
    'FloatSumNode': {1: ('count', True)},
    'FloatMathCodeNode': {1: ('count', True)},
    'FloatAbsNode': {1: ('value', True)},
    'CosNode': {1: ('value', True), 2: ('degrees', True)},
    'Rad2DegNode': {1: ('value', True)},
    'KeyFrameCurveNode': {0: ('input', True)},
    'MaFloatMathNode': {0: ('operation', True), 2: ('a', True), 3: ('b', True)},
    'JointGetLocalCoordNode': {4: ('use_base', True)},
    'Vec3NormalizeNode': {0: ('value', True)},
    'QuatInverseNode': {0: ('value', True)},
    'Vec3TransformNode': {0: ('vector', True), 1: ('rotation', True)},
    'Vec3ToFloat3Node': {0: ('value', True)},
    'Float3ToVec3Node': {1: ('x', True), 2: ('y', True), 3: ('z', True)},
    'QuatToEulerFloat3Node': {3: ('rotation', True), 4: ('rot_order', True)},
}
_OUTPUTS = {
    'MaFloatMathNode': {1: ('result', True), 2: ('a', True), 3: ('b', True)},
    'Vec3ToFloat3Node': {1: ('x', True), 2: ('y', True), 3: ('z', True)},
    'QuatToEulerFloat3Node': {0: ('x', True), 1: ('y', True), 2: ('z', True)},
}


def slot_name(type_name, side, slot):
    """(name, certain) for an input ('in') or output ('out') slot, or (None, False)."""
    short = short_name(type_name)
    if type_name.startswith('via.motion.exprgraph.Joint') or short == 'MaGetConstraintScaleNode':
        if side == 'in' and slot in _JOINT_IN:
            return _JOINT_IN[slot]
        if slot in _JOINT_VALUE:
            return _JOINT_VALUE[slot]
    if short in _BINARY:
        if side == 'in' and slot in (0, 1):
            return ('ab'[slot], True)
        if side == 'out' and slot == 0:
            return ('result', True)
    if short in ('SkirtSubJointNode', 'SkirtSubJointV2Node'):
        if side == 'in' and slot in _SKIRT_SUB:
            return (_SKIRT_SUB[slot], short == 'SkirtSubJointNode')
        if side == 'out' and slot == 10:
            return ('angle', False)
    table = (_INPUTS if side == 'in' else _OUTPUTS).get(short, {})
    if slot in table:
        return table[slot]
    if side == 'in' and slot >= 10 and short in ('FloatSumNode', 'FloatMathCodeNode'):
        return ('item', False)
    if side == 'out' and slot == 0 and len(output_slots(type_name)) == 1:
        return ('result', True)
    return (None, False)


# ------------------------------------------------------------------ graph edits

def new_graph():
    return dict(version=6, hash20=0, unk24=(0x595A, 1), guid=str(uuid.uuid4()), type_hash=0x47BEF355,
                unk5c=1, hash64=0, root_head=bytes(6), tail_hash=0, roots=[], nodes=[])


def new_node(type_name):
    """A node of a catalog type with no props and no links."""
    e = catalog().get(type_name)
    if not e or 'kind' not in e:
        raise KeyError('no slot information for %s' % type_name)
    return dict(type=type_name, app=is_managed(type_name), kind=e['kind'], k0=0, k3=0, f14=0, f18=0, f34=0,
                props=[], inputs=[], outputs=[tuple(o) for o in e['outputs']], guid=str(uuid.uuid4()))


def default_roots(nodes):
    """Nodes with no outputs, in index order — what 107 of 113 shipped files store.

    The other six store a longer evaluation list that also names math nodes, which
    cannot be rebuilt, so a read graph keeps its own list.
    """
    return [(i, 0x6000 if nd['kind'] == 3 else 0) for i, nd in enumerate(nodes) if not nd['outputs']]


def _remap(G, order):
    """Reorder G['nodes'] to `order` (old indices), fixing links and roots; dropped nodes vanish."""
    new_index = {old: new for new, old in enumerate(order)}
    nodes = [G['nodes'][i] for i in order]
    for nd in nodes:
        nd['inputs'] = [dict(l, src=new_index[l['src']]) for l in nd['inputs'] if l['src'] in new_index]
    G['roots'] = [(new_index[r], f) for r, f in G['roots'] if r in new_index]
    G['nodes'] = nodes


def remove_node(G, index):
    _remap(G, [i for i in range(len(G['nodes'])) if i != index])


def add_node(G, node, as_root=None):
    """Append `node`, keeping managed nodes after native ones; returns its index."""
    G['nodes'].append(node)
    normalize_order(G)
    i = next(k for k, nd in enumerate(G['nodes']) if nd is node)
    if as_root is None:
        as_root = not node['outputs']
    if as_root:
        G['roots'].append((i, 0x6000 if node['kind'] == 3 else 0))
    return i


def normalize_order(G):
    """Native nodes first, then managed ones, each keeping its relative order (the writer needs this)."""
    n = G['nodes']
    order = [i for i in range(len(n)) if not n[i]['app']] + [i for i in range(len(n)) if n[i]['app']]
    if order != list(range(len(n))):
        _remap(G, order)


def connect(G, src, src_slot, dst, dst_slot):
    """Link output `src_slot` of node `src` to input `dst_slot` of node `dst`, replacing what fed it."""
    out_t = dict(G['nodes'][src]['outputs']).get(src_slot)
    if out_t is None:
        raise ValueError('node %d has no output slot %d' % (src, src_slot))
    nd = G['nodes'][dst]
    in_t = dict((s, t) for s, t, _ in input_slots(nd['type'])).get(dst_slot, out_t)
    nd['props'] = [p for p in nd['props'] if p[0] != dst_slot]
    nd['inputs'] = [l for l in nd['inputs'] if l['dst_slot'] != dst_slot]
    nd['inputs'].append(dict(dst_slot=dst_slot, src=src, src_slot=src_slot, dst_type=in_t, src_type=out_t))


def set_prop(G, index, slot, value_type, value):
    """Give input `slot` a constant, replacing a link into it.  Refused on managed nodes."""
    nd = G['nodes'][index]
    if nd['app']:
        raise ValueError('managed node parameters are kept as read')
    nd['inputs'] = [l for l in nd['inputs'] if l['dst_slot'] != slot]
    props = [p for p in nd['props'] if p[0] != slot]
    props.append((slot, value_type, value))
    nd['props'] = props


# ------------------------------------------------------------------ checks

def validate(G):
    """Problems that would make a written graph wrong: [(code, node index or None, detail)].

    Codes: 'order' managed node before a native one; 'link_src' link from a missing node
    or itself; 'link_slot' link from a slot the source does not declare; 'link_type' source
    type differs from the declared output type; 'double' an input slot fed twice;
    'in_type' value type differs from what shipped files use on that slot; 'root' bad
    root entry; 'cycle' a node depends on itself; 'unknown_type' type not in the catalog.
    """
    problems = []
    nodes = G['nodes']
    n = len(nodes)
    seen_app = False
    for i, nd in enumerate(nodes):
        if nd['app']:
            seen_app = True
        elif seen_app:
            problems.append(('order', i, None))
        if nd['type'] not in catalog():
            problems.append(('unknown_type', i, nd['type']))
        expect = {s: t for s, t, _ in input_slots(nd['type'])}
        fed = [p[0] for p in nd['props']] + [l['dst_slot'] for l in nd['inputs']]
        for s in {s for s in fed if fed.count(s) > 1}:
            problems.append(('double', i, s))
        for s, t, _ in nd['props']:
            if s in expect and expect[s] != t:
                problems.append(('in_type', i, (s, t, expect[s])))
        for l in nd['inputs']:
            if not 0 <= l['src'] < n or l['src'] == i:
                problems.append(('link_src', i, l['src']))
                continue
            outs = dict(nodes[l['src']]['outputs'])
            if l['src_slot'] not in outs:
                problems.append(('link_slot', i, (l['src'], l['src_slot'])))
            elif outs[l['src_slot']] != l['src_type']:
                problems.append(('link_type', i, (l['src'], l['src_slot'], l['src_type'], outs[l['src_slot']])))
            s = l['dst_slot']
            if s in expect and expect[s] != l['dst_type'] and l['dst_type'] != 'any':
                problems.append(('in_type', i, (s, l['dst_type'], expect[s])))
    roots = [r for r, _ in G['roots']]
    for r in roots:
        if not 0 <= r < n or roots.count(r) > 1:
            problems.append(('root', r if 0 <= r < n else None, r))
    # cycles: depth-first over link sources
    state = [0] * n
    for start in range(n):
        if state[start]:
            continue
        stack = [(start, iter(nodes[start]['inputs']))]
        state[start] = 1
        while stack:
            i, it = stack[-1]
            l = next(it, None)
            if l is None:
                state[i] = 2
                stack.pop()
                continue
            s = l['src']
            if not 0 <= s < n:
                continue
            if state[s] == 1:
                problems.append(('cycle', i, s))
            elif state[s] == 0:
                state[s] = 1
                stack.append((s, iter(nodes[s]['inputs'])))
    return problems
