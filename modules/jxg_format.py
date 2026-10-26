"""
jxg_format.py
-------------
Reader and writer for JointExprGraph resources (`.jntexprgraph.6`, magic `jexg`).

A graph is a list of nodes.  Each node has a type, a set of input slots that hold
either a constant (a "property") or a link to another node's output slot, and a
declared list of output slots.  Slot ids are per node type; inputs and outputs are
separate id spaces.  docs/jntexprgraph.md has the byte layout and the slot catalog.

`write(read(b))` reproduces every vanilla Wilds file byte for byte, so the layout
rules in `write` (order of regions, alignment) are the engine's, not a guess.

No `bpy` import, so it stays testable without Blender.
"""

import json
import os
import struct
import uuid

VALUE_TYPES = {1: 'bool', 2: 'int', 3: 'float', 4: 'vec3', 6: 'quat', 0xFF: 'any'}
_TYPE_ID = {v: k for k, v in VALUE_TYPES.items()}
_VALUE_SIZE = {1: 4, 2: 4, 3: 4, 4: 12, 6: 16}

# Root list entries and link sources address app (C#) nodes as 0x8000 | index into
# the app block, which follows the native nodes.  0x6000 marks debug-only roots.
_APP_BIT = 0x8000
_ROOT_FLAGS = 0x6000

NODES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'jxg_nodes.json')
_types = None


def _type_table():
    global _types
    if _types is None:
        with open(NODES_PATH, encoding='utf-8') as f:
            by_name = {k: int(v['hash'], 16) for k, v in json.load(f).items()}
        _types = (by_name, {v: k for k, v in by_name.items()})
    return _types


def type_name(h):
    """Node type name for an RSZ type hash; unknown hashes come back as '?xxxxxxxx'."""
    return _type_table()[1].get(h, '?%08x' % h)


def type_hash(name):
    if name.startswith('?'):
        return int(name[1:], 16)
    return _type_table()[0][name]


def _vt(code):
    return VALUE_TYPES.get(code, code)     # unnamed codes stay ints so they round-trip


def _vt_id(t):
    return t if isinstance(t, int) else _TYPE_ID[t]


def _align(x, a):
    return (x + a - 1) // a * a


def _unpack_value(b, o, t):
    if t == 1:
        return bool(struct.unpack_from('<I', b, o)[0])
    if t == 2:
        return struct.unpack_from('<i', b, o)[0]
    if t == 3:
        return struct.unpack_from('<f', b, o)[0]
    if t == 4:
        return struct.unpack_from('<3f', b, o)
    if t == 6:
        return struct.unpack_from('<4f', b, o)
    raise ValueError('property value type %d' % t)


def _pack_value(t, v):
    if t == 1:
        return struct.pack('<I', int(v))
    if t == 2:
        return struct.pack('<i', v)
    if t == 3:
        return struct.pack('<f', v)
    if t == 4:
        return struct.pack('<3f', *v)
    if t == 6:
        return struct.pack('<4f', *v)
    raise ValueError('property value type %d' % t)


def _guid(b, o):
    return str(uuid.UUID(bytes_le=bytes(b[o:o + 16])))


def read(data):
    """Parse a jexg file into a graph dict.

    graph:  version, guid, roots [(node index, flags)], nodes, and the raw header
            words (hash20, unk24, type_hash, unk5c, hash64, root_head, tail_hash).
    node:   type, app (bool), props [(slot, type, value)],
            inputs [{dst_slot, src, src_slot, dst_type, src_type}], outputs [(slot, type)],
            extra (bytes, optional), guid, and raw words kind, k0, k3, f14, f18, f34.
    """
    b = memoryview(data)
    u8 = lambda o: b[o]
    u16 = lambda o: struct.unpack_from('<H', b, o)[0]
    u32 = lambda o: struct.unpack_from('<I', b, o)[0]
    u64 = lambda o: struct.unpack_from('<Q', b, o)[0]
    if bytes(b[4:8]) != b'jexg':
        raise ValueError('not a jntexprgraph file')
    g, tail = u64(0x10), u64(0x18)
    G = dict(version=u32(0), hash20=u32(0x20), unk24=(u16(0x24), u16(0x26)), guid=_guid(b, g))
    off_roots, off_head, off_nodes = u64(g + 0x10), u64(g + 0x18), u64(g + 0x20)
    G['type_hash'], G['unk5c'] = u32(g + 0x28), u16(g + 0x2C)
    n_native, n_app = u16(g + 0x2E), u32(g + 0x30)
    G['hash64'] = u32(g + 0x34)

    def node_ref(v):
        return (v & 0x1FFF) + (n_native if v & _APP_BIT else 0)

    has_head = off_nodes > off_head
    n_roots = u16(off_head + 6) if has_head else 0
    G['root_head'] = bytes(b[off_head:off_head + 6]) if has_head else b''
    G['roots'] = [(node_ref(u16(off_roots + 2 * i)), u16(off_roots + 2 * i) & _ROOT_FLAGS) for i in range(n_roots)]

    nodes = []
    for i in range(n_native + n_app):
        o = off_nodes + 0x38 * i
        link0, ptype, pdata, f14, f18, extra = struct.unpack_from('<IIIIII', b, o + 8)
        k0, n_in, n_prop, k3 = b[o + 0x28:o + 0x2C]
        nd = dict(type=type_name(u32(o + 0x30)), app=i >= n_native, kind=u16(o + 0x2C),
                  k0=k0, k3=k3, f14=f14, f18=f18, f34=u32(o + 0x34))
        if u32(o + 0x24) != i:
            raise ValueError('node %d stores index %d' % (i, u32(o + 0x24)))
        props, po = [], pdata
        for j in range(n_prop):
            slot, t = u8(ptype + 3 * j), u8(ptype + 3 * j + 1)
            props.append((slot, _vt(t), _unpack_value(b, po, t)))
            po += _VALUE_SIZE[t]
        nd['props'] = props
        nd['inputs'] = []
        for j in range(n_in):
            src, dst_slot, src_slot, dst_t, src_t = struct.unpack_from('<HBBBB', b, link0 + 6 * j)
            nd['inputs'].append(dict(dst_slot=dst_slot, src=node_ref(src), src_slot=src_slot,
                                     dst_type=_vt(dst_t), src_type=_vt(src_t)))
        if extra:
            nd['extra'] = bytes(b[extra:extra + u16(o + 0x2E)])
        nodes.append(nd)

    # Tail: graph guid, then per node its editor guid and declared output slots.
    G['tail_hash'] = u32(tail + 0x18)
    ent = u64(tail + 0x10)
    for i, nd in enumerate(nodes):
        e = ent + 0x20 * i
        nd['guid'] = _guid(b, e)
        p, n = u64(e + 0x10), u64(e + 0x18)
        nd['outputs'] = [(u8(p + 2 * j), _vt(u8(p + 2 * j + 1))) for j in range(n)]
    G['nodes'] = nodes
    return G


def write(G):
    """Serialise a graph dict from `read` (or one built the same way)."""
    nodes = G['nodes']
    n = len(nodes)
    n_native = sum(1 for nd in nodes if not nd['app'])
    if any(nd['app'] for nd in nodes[:n_native]):
        raise ValueError('app nodes must come after all native nodes')

    def node_ref(i):
        return i if i < n_native else _APP_BIT | (i - n_native)

    out = bytearray()

    def put(off, data):
        if len(out) < off + len(data):
            out.extend(bytes(off + len(data) - len(out)))
        out[off:off + len(data)] = data

    g = 0x30
    put(0, struct.pack('<I4sQQ', G['version'], b'jexg', 0, g))
    put(0x20, struct.pack('<IHHQ', G['hash20'], *G['unk24'], 0))
    put(g, uuid.UUID(G['guid']).bytes_le)
    off_roots = g + 0x38
    if n:
        off_head = _align(off_roots + 2 * len(G['roots']), 4)
        off_nodes = _align(off_head + 8, 8)
    else:
        off_head = off_nodes = off_roots
    put(g + 0x10, struct.pack('<QQQIHHII', off_roots, off_head, off_nodes, G['type_hash'], G['unk5c'],
                              n_native, n - n_native, G['hash64']))
    for i, (idx, flags) in enumerate(G['roots']):
        put(off_roots + 2 * i, struct.pack('<H', node_ref(idx) | flags))
    if n:
        put(off_head, bytes(G['root_head']).ljust(6, b'\0') + struct.pack('<H', len(G['roots'])))

    cur = off_nodes + 0x38 * n
    ptype = {}
    for i, nd in enumerate(nodes):
        if nd['props']:
            ptype[i] = cur
            for slot, t, _ in nd['props']:
                put(cur, bytes((slot, _vt_id(t), _vt_id(t))))
                cur += 3
    cur = _align(cur, 4)
    pdata = {}
    for i, nd in enumerate(nodes):
        if nd['props']:
            pdata[i] = cur
            for _, t, v in nd['props']:
                d = _pack_value(_vt_id(t), v)
                put(cur, d)
                cur += len(d)
    cur = _align(cur, 8)
    links = {}
    for i, nd in enumerate(nodes):
        links[i] = cur
        for l in nd['inputs']:
            put(cur, struct.pack('<HBBBB', node_ref(l['src']), l['dst_slot'], l['src_slot'],
                                 _vt_id(l['dst_type']), _vt_id(l['src_type'])))
            cur += 6
        if nd['inputs']:
            cur = _align(cur, 8)
    cur = _align(cur, 16)
    extra = {}
    for i, nd in enumerate(nodes):
        if nd.get('extra'):
            extra[i] = cur
            put(cur, nd['extra'])
            cur = _align(cur + len(nd['extra']), 16)
    tail = _align(cur, 16)

    for i, nd in enumerate(nodes):
        o = off_nodes + 0x38 * i
        put(o, struct.pack('<QIIIIII', 0, links[i], ptype.get(i, 0), pdata.get(i, 0),
                           nd.get('f14', 0), nd.get('f18', 0), extra.get(i, 0)))
        put(o + 0x20, struct.pack('<II4BHHII', links[i] + 6 * len(nd['inputs']), i,
                                  nd.get('k0', 0), len(nd['inputs']), len(nd['props']), nd.get('k3', 0),
                                  nd['kind'], len(nd.get('extra', b'')), type_hash(nd['type']), nd.get('f34', 0)))

    put(0x18, struct.pack('<Q', tail))
    ent = tail + 0x20
    put(tail, uuid.UUID(G['guid']).bytes_le + struct.pack('<QII', ent, G['tail_hash'], 0))
    cur = ent + 0x20 * n
    for i, nd in enumerate(nodes):
        cur = _align(cur, 4)
        put(ent + 0x20 * i, uuid.UUID(nd['guid']).bytes_le + struct.pack('<QQ', cur, len(nd['outputs'])))
        for slot, t in nd['outputs']:
            put(cur, bytes((slot, _vt_id(t))))
            cur += 2
    put(cur, b'')
    return bytes(out)


def describe(G, joint_name=None):
    """Readable listing; `joint_name(hash) -> str | None` names int props that look like hashes."""
    lines = []
    for i, nd in enumerate(G['nodes']):
        outs = ', '.join('%d:%s' % o for o in nd['outputs'])
        root = ' root' if any(r == i for r, _ in G['roots']) else ''
        lines.append('[%d] %s%s  -> (%s)' % (i, nd['type'].rsplit('.', 1)[-1], root, outs))
        for slot, t, v in nd['props']:
            if isinstance(v, float):
                v = round(v, 4)
            elif isinstance(v, tuple):
                v = tuple(round(x, 4) for x in v)
            elif t == 'int' and joint_name and abs(v) > 0xFFFF:
                v = joint_name(v & 0xFFFFFFFF) or '%08x' % (v & 0xFFFFFFFF)
            lines.append('    %3d = %s   (%s)' % (slot, v, t))
        for l in nd['inputs']:
            lines.append('    %3d <- [%d].%d   (%s)' % (l['dst_slot'], l['src'], l['src_slot'], l['dst_type']))
        if nd.get('extra'):
            lines.append('    extra ' + nd['extra'].hex(' '))
    return '\n'.join(lines)
