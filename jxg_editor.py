"""
jxg_editor.py
-------------
JointExprGraph (.jntexprgraph) in Blender's node editor: a custom node tree whose
nodes are the graph's nodes, one socket per slot, links as links.

Import builds a collection <file>.jntexprgraph holding a JXG_HEADER Empty that
points at the tree; the tree carries the file header.  Export turns the tree back
into a jxg_format graph dict (modules/jxg_nodes.py checks it) and writes it.

What the tree keeps so an untouched import writes back byte for byte:
  * node order: `file_index`; nodes added later go after, managed (C#) ones last;
  * the order of each node's props and links (`prop_order`, `link_meta`);
  * the root list, keyed by node guid;
  * managed nodes' props, extra data and outputs as read (`raw`): only their links
    come from the sockets.
"""

import json
import os
import uuid

import bpy
from bpy.props import (BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty, IntProperty,
                       PointerProperty, StringProperty)
from bpy.types import Menu, Node, NodeSocket, NodeTree, Operator, Panel
from bpy_extras.io_utils import ExportHelper, ImportHelper

from .modules_shim import T, ensure_path

ensure_path()
import jcns_names  # noqa: E402
import jxg_format  # noqa: E402
import jxg_nodes  # noqa: E402

TREE_ID = 'JCNS_JXG_Tree'
NODE_ID = 'JCNS_JXG_Node'
COLLECTION_TYPE = 'RE_JXG_COLLECTION'
FILE_GLOB = '*.jntexprgraph.*'
FILE_EXTENSIONS = '.6'


# ---------------------------------------------------------------------------
# Sockets
# ---------------------------------------------------------------------------

_COLORS = {
    'bool': (0.80, 0.65, 0.84, 1.0), 'int': (0.35, 0.55, 0.36, 1.0), 'float': (0.63, 0.63, 0.63, 1.0),
    'vec3': (0.39, 0.39, 0.78, 1.0), 'quat': (0.85, 0.55, 0.35, 1.0), 'any': (0.2, 0.2, 0.2, 1.0),
    'joint': (0.20, 0.70, 0.75, 1.0), 'enum': (0.35, 0.55, 0.36, 1.0),
}

# enum-like int slots of the Joint nodes: value -> string key
_ENUMS = {
    'space': ((0, "editors.jxg.enum.local"), (1, "editors.jxg.enum.global"), (2, "editors.jxg.enum.local_diff")),
    'rot_order': ((0, "editors.jxg.enum.rpy"), (1, "editors.jxg.enum.pyr"), (2, "editors.jxg.enum.expmap")),
    'unit': ((0, "editors.jxg.enum.cm"), (1, "editors.jxg.enum.m")),
    'rot_unit': ((0, "editors.jxg.enum.rad"), (1, "editors.jxg.enum.deg")),
}


class _JXGSocket:
    """Common to every JXG socket: the slot it stands for, and for inputs whether a constant feeds it."""
    slot: IntProperty()
    use_value: BoolProperty(name=T("editors.jxg.socket.use_value"),
                            description=T("editors.jxg.socket.use_value_tip"))
    vtype = 'any'

    @classmethod
    def draw_color_simple(cls):
        return _COLORS[cls.vtype]

    def draw(self, context, layout, node, text):
        if self.is_output or self.is_linked or not hasattr(self, 'value'):
            layout.label(text=text)
            return
        row = layout.row(align=True)
        if not node.managed:
            row.prop(self, "use_value", text="")
        sub = row.row(align=True)
        sub.enabled = self.use_value and not node.managed
        self.draw_value(sub, text)

    def draw_value(self, layout, text):
        layout.prop(self, "value", text=text)

    def export_value(self):
        return self.value


class JCNS_JXG_SocketFloat(_JXGSocket, NodeSocket):
    bl_idname = 'JCNS_JXG_SocketFloat'
    bl_label = "Float"   # ui-copy: internal
    vtype = 'float'
    value: FloatProperty()


class JCNS_JXG_SocketInt(_JXGSocket, NodeSocket):
    bl_idname = 'JCNS_JXG_SocketInt'
    bl_label = "Int"   # ui-copy: internal
    vtype = 'int'
    value: IntProperty()


class JCNS_JXG_SocketBool(_JXGSocket, NodeSocket):
    bl_idname = 'JCNS_JXG_SocketBool'
    bl_label = "Bool"   # ui-copy: internal
    vtype = 'bool'
    value: BoolProperty()


class JCNS_JXG_SocketVec3(_JXGSocket, NodeSocket):
    bl_idname = 'JCNS_JXG_SocketVec3'
    bl_label = "Vector"   # ui-copy: internal
    vtype = 'vec3'
    value: FloatVectorProperty(size=3)

    def draw_value(self, layout, text):
        layout.column(align=True).prop(self, "value", text=text)

    def export_value(self):
        return tuple(self.value)


class JCNS_JXG_SocketQuat(_JXGSocket, NodeSocket):
    bl_idname = 'JCNS_JXG_SocketQuat'
    bl_label = "Quaternion"   # ui-copy: internal
    vtype = 'quat'
    value: FloatVectorProperty(size=4)

    def draw_value(self, layout, text):
        layout.column(align=True).prop(self, "value", text=text)

    def export_value(self):
        return tuple(self.value)


class JCNS_JXG_SocketAny(_JXGSocket, NodeSocket):
    bl_idname = 'JCNS_JXG_SocketAny'
    bl_label = "Any"   # ui-copy: internal
    vtype = 'any'


def _bone_search(self, context, edit_text):
    arm = getattr(self.id_data, 'armature', None)
    if arm is None or arm.type != 'ARMATURE':
        return []
    t = edit_text.lower()
    return [b.name for b in arm.data.bones if t in b.name.lower()]


def _bone_changed(self, context):
    if self.bone:
        self.value = jxg_hash(self.bone)


class JCNS_JXG_SocketJoint(_JXGSocket, NodeSocket):
    """A bone, stored as the murmur3 hash of its name; the name is only for display."""
    bl_idname = 'JCNS_JXG_SocketJoint'
    bl_label = "Joint"   # ui-copy: internal
    vtype = 'joint'
    value: IntProperty()
    bone: StringProperty(name=T("editors.jxg.socket.bone"), description=T("editors.jxg.socket.bone_tip"),
                         search=_bone_search, update=_bone_changed)

    def draw_value(self, layout, text):
        layout.prop(self, "bone", text=text, icon='BONE_DATA')
        if not self.bone:
            layout.label(text="%08X" % (self.value & 0xFFFFFFFF))


_enum_cache = {}       # Blender keeps pointers into dynamic enum items: they must stay alive


def _enum_items(self, context):
    key = (self.enum_kind, self.value)
    items = _enum_cache.get(key)
    if items is None:
        items = [(str(v), T(k), "") for v, k in _ENUMS.get(self.enum_kind, ())]
        if not any(int(i[0]) == self.value for i in items):
            items.append((str(self.value), str(self.value), ""))
        _enum_cache[key] = items
    return items


class JCNS_JXG_SocketEnum(_JXGSocket, NodeSocket):
    """An int slot whose values name choices (coordinate space, rotation order, units)."""
    bl_idname = 'JCNS_JXG_SocketEnum'
    bl_label = "Choice"   # ui-copy: internal
    vtype = 'enum'
    value: IntProperty()
    enum_kind: StringProperty()
    choice: EnumProperty(items=_enum_items,
                         get=lambda s: next((i for i, it in enumerate(_enum_items(s, None))
                                             if int(it[0]) == s.value), 0),
                         set=lambda s, i: setattr(s, 'value', int(_enum_items(s, None)[i][0])))

    def draw_value(self, layout, text):
        layout.prop(self, "choice", text=text)


SOCKET_CLASSES = (JCNS_JXG_SocketFloat, JCNS_JXG_SocketInt, JCNS_JXG_SocketBool, JCNS_JXG_SocketVec3,
                  JCNS_JXG_SocketQuat, JCNS_JXG_SocketAny, JCNS_JXG_SocketJoint, JCNS_JXG_SocketEnum)
_SOCKET_FOR = {'float': JCNS_JXG_SocketFloat, 'int': JCNS_JXG_SocketInt, 'bool': JCNS_JXG_SocketBool,
               'vec3': JCNS_JXG_SocketVec3, 'quat': JCNS_JXG_SocketQuat, 'any': JCNS_JXG_SocketAny}


def jxg_hash(name):
    """murmur3 of a bone name as the file stores it (signed, to fit an IntProperty)."""
    from .jcns_importer import _hash_name
    h = _hash_name(name)
    return h - (1 << 32) if h >= 1 << 31 else h


# ---------------------------------------------------------------------------
# Tree and node
# ---------------------------------------------------------------------------

def _armature_poll(self, obj):
    return obj.type == 'ARMATURE'


class JCNS_JXG_Tree(NodeTree):
    bl_idname = TREE_ID
    bl_label = T("editors.jxg.tree")
    bl_description = T("editors.jxg.tree_tip")
    bl_icon = 'NODETREE'

    armature: PointerProperty(name=T("editors.jxg.armature"), description=T("editors.jxg.armature_tip"),
                              type=bpy.types.Object, poll=_armature_poll)
    source_filepath: StringProperty(name=T("editors.jxg.source"), subtype='FILE_PATH')
    asset_path: StringProperty(name=T("editors.jxg.asset_path"))
    # the file header as read; new trees take jxg_nodes.new_graph()'s values
    header_json: StringProperty()
    # [[guid, flags], ...]; `roots_default` when it was "nodes without outputs, in order"
    roots_json: StringProperty(default="[]")
    roots_default: BoolProperty(default=True)
    next_index: IntProperty()


_CATEGORY_COLORS = {
    'get': (0.20, 0.35, 0.45), 'set': (0.45, 0.22, 0.22), 'time': (0.42, 0.36, 0.18),
    'math': (0.25, 0.25, 0.25), 'vector': (0.27, 0.25, 0.42), 'remap': (0.20, 0.38, 0.28),
    'managed': (0.30, 0.30, 0.30), 'other': (0.25, 0.25, 0.25),
}


def category(type_name):
    short = jxg_nodes.short_name(type_name)
    if jxg_nodes.is_managed(type_name):
        return 'managed'
    if short.startswith(('JointGet', 'MaGetConstraint')):
        return 'get'
    if short.startswith(('JointSet', 'ExprMeshSet', 'ExprZiva', 'DebugDraw')):
        return 'set'
    if short in ('CyclicalAngleNode', 'SinWaveNode', 'CosWaveNode', 'SawToothWaveNode'):
        return 'time'
    if short.startswith(('Vec3', 'Quat', 'Float3To', 'JointDecompose')):
        return 'vector'
    if short.startswith(('Ma', 'KeyFrame', 'FloatEase', 'FloatMap', 'JointDriver')):
        return 'remap'
    if short.startswith(('Float', 'Cos', 'Sin', 'Rad2Deg')):
        return 'math'
    return 'other'


def _node_copied(self, node):
    self.guid = str(uuid.uuid4())
    tree = self.id_data
    self.file_index = tree.next_index
    tree.next_index += 1


class JCNS_JXG_Node(Node):
    """One graph node; its type decides its sockets."""
    bl_idname = NODE_ID
    bl_label = T("editors.jxg.node")

    type_name: StringProperty(name=T("editors.jxg.node_type"))
    managed: BoolProperty()
    kind: IntProperty()
    guid: StringProperty()
    name_hash: IntProperty()
    extra_hex: StringProperty()
    file_index: IntProperty(default=-1)
    prop_order: StringProperty()          # json [slot, ...]
    link_meta: StringProperty()           # json [[dst_slot, dst_type, src_type], ...]
    raw: StringProperty()                 # json: outputs, k0/k3/f14/f18, and props for managed nodes

    @classmethod
    def poll(cls, ntree):
        return ntree.bl_idname == TREE_ID

    def copy(self, node):
        _node_copied(self, node)

    def draw_label(self):
        return jxg_nodes.short_name(self.type_name) if self.type_name else T("editors.jxg.node")

    def draw_buttons(self, context, layout):
        if self.managed:
            layout.label(text=T("editors.jxg.managed_short"), icon='LOCKED')


def _slot_label(type_name, side, slot):
    name, certain = jxg_nodes.slot_name(type_name, side, slot)
    if name is None:
        return "#%d" % slot
    text = T("editors.jxg.slot." + name) if ("editors.jxg.slot." + name) in _known_slot_keys() else name
    return text if certain else text + "?"


_slot_keys = None


def _known_slot_keys():
    global _slot_keys
    if _slot_keys is None:
        import jcns_strings
        _slot_keys = {k for k in jcns_strings.load() if k.startswith("editors.jxg.slot.")}
    return _slot_keys


def _socket_class(type_name, slot, vtype):
    name, _ = jxg_nodes.slot_name(type_name, 'in', slot)
    if vtype == 'int' and name == 'joint':
        return JCNS_JXG_SocketJoint, None
    if vtype == 'int' and name in _ENUMS:
        return JCNS_JXG_SocketEnum, name
    return _SOCKET_FOR.get(vtype, JCNS_JXG_SocketAny), None


def build_sockets(node, inputs, outputs):
    """(Re)create the sockets: `inputs` [(slot, vtype)], `outputs` [(slot, vtype)], both by slot."""
    node.inputs.clear()
    node.outputs.clear()
    for slot, vtype in sorted(inputs):
        cls, enum_kind = _socket_class(node.type_name, slot, vtype)
        s = node.inputs.new(cls.bl_idname, _slot_label(node.type_name, 'in', slot), identifier="in_%d" % slot)
        s.slot = slot
        if enum_kind:
            s.enum_kind = enum_kind
    for slot, vtype in sorted(outputs):
        s = node.outputs.new(_SOCKET_FOR.get(vtype, JCNS_JXG_SocketAny).bl_idname,
                             _slot_label(node.type_name, 'out', slot), identifier="out_%d" % slot)
        s.slot = slot


def setup_node(node, type_name, outputs):
    """Fill a fresh node of `type_name` from the catalog (sockets, kind, colour, guid)."""
    node.type_name = type_name
    node.managed = jxg_nodes.is_managed(type_name)
    entry = jxg_nodes.catalog().get(type_name, {})
    node.kind = entry.get('kind', 1)
    node.guid = str(uuid.uuid4())
    node.raw = json.dumps({'outputs': [list(o) for o in outputs]})
    build_sockets(node, [(s, t) for s, t, _ in jxg_nodes.input_slots(type_name)], outputs)
    node.use_custom_color = True
    node.color = _CATEGORY_COLORS[category(type_name)]
    node.width = 200 if any(s.bl_idname == JCNS_JXG_SocketJoint.bl_idname for s in node.inputs) else 160


# ---------------------------------------------------------------------------
# Graph dict <-> tree
# ---------------------------------------------------------------------------

def _set_socket_value(sock, value):
    if isinstance(sock, JCNS_JXG_SocketJoint):
        sock.value = value
        name = jcns_names.name_of(value & 0xFFFFFFFF)
        if name:
            sock.bone = name               # dictionary names hash back to their key: value is unchanged
    else:
        sock.value = value
    sock.use_value = True


def graph_to_tree(G, name):
    tree = bpy.data.node_groups.new(name, TREE_ID)
    header = {k: (v.hex() if isinstance(v, bytes) else v) for k, v in G.items() if k not in ('nodes', 'roots')}
    tree.header_json = json.dumps(header)
    tree.roots_default = G['roots'] == jxg_nodes.default_roots(G['nodes'])
    tree.roots_json = json.dumps([[G['nodes'][r]['guid'], f] for r, f in G['roots']])
    made = []
    for i, nd in enumerate(G['nodes']):
        node = tree.nodes.new(NODE_ID)
        node.type_name = nd['type']
        node.managed = nd['app']
        node.kind = nd['kind']
        node.guid = nd['guid']
        node.name_hash = nd['f34'] - (1 << 32) if nd['f34'] >= 1 << 31 else nd['f34']
        node.extra_hex = nd.get('extra', b'').hex()
        node.file_index = i
        node.prop_order = json.dumps([s for s, _, _ in nd['props']])
        node.link_meta = json.dumps([[l['dst_slot'], l['dst_type'], l['src_type']] for l in nd['inputs']])
        raw = {'outputs': [list(o) for o in nd['outputs']], 'k0': nd['k0'], 'k3': nd['k3'],
               'f14': nd['f14'], 'f18': nd['f18']}
        if nd['app']:
            raw['props'] = [[s, t, list(v) if isinstance(v, tuple) else v] for s, t, v in nd['props']]
        node.raw = json.dumps(raw)
        ins = {s: t for s, t, _ in jxg_nodes.input_slots(nd['type'])}
        for s, t, _ in nd['props']:
            ins.setdefault(s, t)
        for l in nd['inputs']:
            ins.setdefault(l['dst_slot'], l['dst_type'])
        build_sockets(node, list(ins.items()), nd['outputs'])
        for s, t, v in nd['props']:
            _set_socket_value(node.inputs["in_%d" % s], v)
        node.use_custom_color = True
        node.color = _CATEGORY_COLORS[category(nd['type'])]
        node.width = 200 if any(s.bl_idname == JCNS_JXG_SocketJoint.bl_idname for s in node.inputs) else 160
        made.append(node)
    for nd, node in zip(G['nodes'], made):
        for l in nd['inputs']:
            src = made[l['src']].outputs.get("out_%d" % l['src_slot'])
            dst = node.inputs.get("in_%d" % l['dst_slot'])
            if src is not None and dst is not None:
                tree.links.new(src, dst)
    tree.next_index = len(made)
    layout_tree(tree)
    return tree


def _real_source(link):
    """The JXG output a link comes from, following reroutes; None when it does not reach one."""
    sock = link.from_socket
    while sock.node.bl_idname == 'NodeReroute':
        if not sock.node.inputs[0].is_linked:
            return None
        sock = sock.node.inputs[0].links[0].from_socket
    return sock if sock.node.bl_idname == NODE_ID else None


def jxg_nodes_of(tree):
    """The tree's graph nodes in file order: read ones by index, added ones after, managed ones last."""
    nodes = [n for n in tree.nodes if n.bl_idname == NODE_ID]
    return sorted(nodes, key=lambda n: (n.managed, n.file_index if n.file_index >= 0 else 1 << 30))


def tree_to_graph(tree):
    """The jxg_format graph dict for `tree`."""
    header = json.loads(tree.header_json) if tree.header_json else {}
    G = jxg_nodes.new_graph()
    for k, v in header.items():
        G[k] = bytes.fromhex(v) if k == 'root_head' else (tuple(v) if k == 'unk24' else v)
    nodes = jxg_nodes_of(tree)
    index = {n.as_pointer(): i for i, n in enumerate(nodes)}
    out = []
    for n in nodes:
        raw = json.loads(n.raw) if n.raw else {}
        nd = dict(type=n.type_name, app=n.managed, kind=n.kind, guid=n.guid or str(uuid.uuid4()),
                  f34=n.name_hash & 0xFFFFFFFF, k0=raw.get('k0', 0), k3=raw.get('k3', 0),
                  f14=raw.get('f14', 0), f18=raw.get('f18', 0),
                  outputs=[tuple(o) for o in raw.get('outputs', [])])
        if n.extra_hex:
            nd['extra'] = bytes.fromhex(n.extra_hex)
        if n.managed and 'props' in raw:
            nd['props'] = [(s, t, tuple(v) if isinstance(v, list) else v) for s, t, v in raw['props']]
        else:
            order = json.loads(n.prop_order) if n.prop_order else []
            fed = {s.slot: s for s in n.inputs if not s.is_linked and getattr(s, 'use_value', False)
                   and hasattr(s, 'value')}
            slots = [s for s in order if s in fed] + sorted(s for s in fed if s not in order)
            nd['props'] = [(s, 'int' if fed[s].vtype in ('joint', 'enum') else fed[s].vtype,
                            fed[s].export_value()) for s in slots]
        meta = {m[0]: m for m in (json.loads(n.link_meta) if n.link_meta else [])}
        links = []
        for s in n.inputs:
            if not s.is_linked:
                continue
            src = _real_source(s.links[0])
            if src is None:
                continue
            src_type = 'any' if src.vtype in ('joint', 'enum') else src.vtype
            dst_type = 'int' if s.vtype in ('joint', 'enum') else s.vtype
            m = meta.get(s.slot)
            if m is not None and m[2] == src_type:
                dst_type = m[1]
            links.append(dict(dst_slot=s.slot, src=index[src.node.as_pointer()], src_slot=src.slot,
                              dst_type=dst_type, src_type=src_type))
        rank = {m: i for i, m in enumerate(meta)}
        nd['inputs'] = sorted(links, key=lambda l: (rank.get(l['dst_slot'], 1 << 20), l['dst_slot']))
        out.append(nd)
    G['nodes'] = out
    if tree.roots_default:
        G['roots'] = jxg_nodes.default_roots(out)
    else:
        by_guid = {nd['guid']: i for i, nd in enumerate(out)}
        roots = [(by_guid[g], f) for g, f in json.loads(tree.roots_json) if g in by_guid]
        listed = {r for r, _ in roots}
        roots += [r for r in jxg_nodes.default_roots(out) if r[0] not in listed]
        G['roots'] = roots
    return G


def layout_tree(tree):
    """Columns by distance from the graph's outputs (roots on the right)."""
    nodes = [n for n in tree.nodes if n.bl_idname == NODE_ID]
    consumers = {n.as_pointer(): [] for n in nodes}
    for link in tree.links:
        a, b = link.from_node, link.to_node
        if a.as_pointer() in consumers and b.as_pointer() in consumers:
            consumers[a.as_pointer()].append(b)
    depth = {}

    def depth_of(n, guard=0):
        key = n.as_pointer()
        if key not in depth:
            depth[key] = 0 if guard > 200 else max((depth_of(c, guard + 1) + 1 for c in consumers[key]), default=0)
        return depth[key]

    columns = {}
    for n in sorted(nodes, key=lambda n: n.file_index):
        columns.setdefault(depth_of(n), []).append(n)
    for col, members in columns.items():
        y = 0.0
        for n in members:
            n.location = (-col * (n.width + 80), y)
            y -= 60 + 24 * (len(n.inputs) + len(n.outputs))


# ---------------------------------------------------------------------------
# Collection and header
# ---------------------------------------------------------------------------

def strip_version(filename):
    base, ext = os.path.splitext(filename)
    return base if ext[1:].isdigit() else filename


def game_asset_path(filepath):
    """'.../natives/STM/Art/x.jntexprgraph.6' -> 'Art/x.jntexprgraph', or '' outside natives."""
    parts = filepath.replace('\\', '/').split('/')
    lower = [p.lower() for p in parts]
    if 'natives' not in lower:
        return ''
    i = len(lower) - 1 - lower[::-1].index('natives')
    rest = parts[i + 2:]
    if not rest:
        return ''
    rest[-1] = strip_version(rest[-1])
    return '/'.join(rest)


def header_name(coll):
    return "JXG_HEADER %s" % coll.name


def tree_of_collection(coll):
    for obj in getattr(coll, 'objects', ()):
        tree = getattr(obj, 'jcns_jxg_tree', None)
        if tree is not None:
            return obj, tree
    return None, None


def collection_of_tree(tree):
    for obj in bpy.data.objects:
        if getattr(obj, 'jcns_jxg_tree', None) == tree and obj.users_collection:
            return obj, obj.users_collection[0]
    return None, None


def _new_collection(context, name, armature_obj):
    from .jcns_importer import _group_collection
    coll = bpy.data.collections.new(name)
    coll.color_tag = 'COLOR_04'   # green, as JCNS collections
    coll["~TYPE"] = COLLECTION_TYPE
    (_group_collection(armature_obj) or context.scene.collection).children.link(coll)
    return coll


def _attach(context, tree, coll_name, armature_obj, asset_path=''):
    coll = _new_collection(context, coll_name, armature_obj)
    if asset_path:
        coll["~ASSETPATH"] = asset_path
    head = bpy.data.objects.new(header_name(coll), None)
    head.empty_display_type = 'PLAIN_AXES'
    head.empty_display_size = 0.1
    head.jcns_jxg_tree = tree
    coll.objects.link(head)
    return head


def do_import(filepath, context, armature_obj=None):
    """Read a .jntexprgraph and build its collection and tree; returns the tree."""
    with open(filepath, 'rb') as f:
        G = jxg_format.read(f.read())
    name = strip_version(os.path.basename(filepath))
    tree = graph_to_tree(G, name)
    tree.source_filepath = filepath
    tree.asset_path = game_asset_path(filepath)
    if armature_obj is not None:
        tree.armature = armature_obj
    _attach(context, tree, name, armature_obj, tree.asset_path)
    return tree


def do_new(context, armature_obj=None):
    tree = bpy.data.node_groups.new("new.jntexprgraph", TREE_ID)
    header = jxg_nodes.new_graph()
    tree.header_json = json.dumps({k: (v.hex() if isinstance(v, bytes) else v) for k, v in header.items()
                                   if k not in ('nodes', 'roots')})
    if armature_obj is not None:
        tree.armature = armature_obj
    _attach(context, tree, tree.name, armature_obj)
    return tree


class ExportRefused(Exception):
    pass


def export_bytes(tree):
    """File bytes for `tree`; ExportRefused lists the problems when the graph is not writable."""
    G = tree_to_graph(tree)
    problems = jxg_nodes.validate(G)
    if problems:
        raise ExportRefused(describe_problems(G, problems))
    return jxg_format.write(G)


def describe_problems(G, problems, limit=8):
    lines = []
    for code, i, detail in problems[:limit]:
        where = "[%d] %s" % (i, jxg_nodes.short_name(G['nodes'][i]['type'])) if i is not None else ""
        lines.append(T("io.jxg.problem." + code, where))
    if len(problems) > limit:
        lines.append(T("io.jxg.problem_more", len(problems) - limit))
    return "\n".join(lines)


def show_tree(context, tree):
    """Point every node editor in the window at `tree`; False when none is open."""
    shown = False
    for area in context.window.screen.areas if context.window else ():
        if area.type == 'NODE_EDITOR':
            space = area.spaces.active
            space.tree_type = TREE_ID
            space.node_tree = tree
            shown = True
    return shown


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

def _active_tree(context):
    space = getattr(context, 'space_data', None)
    if space is not None and getattr(space, 'tree_type', None) == TREE_ID and space.edit_tree is not None:
        return space.edit_tree
    tree = tree_of_collection(getattr(context.scene, 'jcns_active_collection', None))[1]
    if tree is not None:
        return tree
    obj = context.active_object
    return getattr(obj, 'jcns_jxg_tree', None) if obj is not None else None


def _make_working(context, tree):
    """Make the tree's collection the scene's working collection, as a JCNS import does."""
    _head, coll = collection_of_tree(tree)
    if coll is not None:
        context.scene.jcns_active_collection = coll


def open_tree_window(context, tree):
    """A new window holding one node editor on `tree`; False when Blender gives no window.

    screen.area_dupli opens the duplicated area alone in a new window, which is then
    turned into a node editor; the area it copies is left as it was.
    """
    wm = context.window_manager
    window = context.window or (wm.windows[0] if wm.windows else None)
    if window is None:
        return False
    area = context.area if context.area is not None else max(window.screen.areas, key=lambda a: a.width * a.height)
    region = next((r for r in area.regions if r.type == 'WINDOW'), None)
    before = {w.as_pointer() for w in wm.windows}
    with context.temp_override(window=window, area=area, region=region):
        bpy.ops.screen.area_dupli('INVOKE_DEFAULT')
    new = [w for w in wm.windows if w.as_pointer() not in before]
    if not new:
        return False
    target = new[0].screen.areas[0]
    target.ui_type = TREE_ID
    target.spaces.active.node_tree = tree
    region = next((r for r in target.regions if r.type == 'WINDOW'), None)
    try:
        with context.temp_override(window=new[0], area=target, region=region):
            bpy.ops.node.view_all()
    except RuntimeError:
        pass                                 # framing is a nicety; the window is already right
    return True


def _armature_items(self, context):
    items = [("NONE", T("io.import.armature_none"), "")]
    items += [(o.name, o.name, "") for o in context.scene.objects if o.type == 'ARMATURE']
    return items


class JCNS_OT_ImportJXG(Operator, ImportHelper):
    bl_idname = "jcns.import_jxg"
    bl_label = "RE Engine JointExprGraph (.jntexprgraph.*)"
    bl_description = T("io.jxg.import_tip")
    bl_options = {'REGISTER', 'UNDO'}

    filter_glob: StringProperty(default=FILE_GLOB, options={'HIDDEN'})
    target_armature_name: EnumProperty(name=T("io.import.armature.name"),
                                       description=T("io.jxg.armature_tip"), items=_armature_items)

    def invoke(self, context, event):
        obj = context.active_object
        if obj is None or obj.type != 'ARMATURE':
            obj = next((o for o in context.scene.objects if o.type == 'ARMATURE'), None)
        if obj is not None:
            self.target_armature_name = obj.name
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        if not os.path.isfile(self.filepath):
            self.report({'ERROR'}, T("io.import.file_not_found", self.filepath))
            return {'CANCELLED'}
        arm = context.scene.objects.get(self.target_armature_name) if self.target_armature_name != "NONE" else None
        try:
            tree = do_import(self.filepath, context, arm)
        except (ValueError, KeyError, IndexError) as ex:
            self.report({'ERROR'}, T("io.jxg.read_failed", str(ex)))
            return {'CANCELLED'}
        _make_working(context, tree)
        n = sum(1 for nd in tree.nodes if nd.bl_idname == NODE_ID)
        managed = sum(1 for nd in tree.nodes if nd.bl_idname == NODE_ID and nd.managed)
        msg = T("io.jxg.imported", tree.name, n)
        if managed:
            msg += T("io.jxg.imported_managed", managed)
        if not show_tree(context, tree):
            msg += T("io.jxg.open_hint")
        self.report({'INFO'}, msg)
        return {'FINISHED'}


class JCNS_OT_NewJXG(Operator):
    bl_idname = "jcns.new_jxg"
    bl_label = T("io.jxg.new_label")
    bl_description = T("io.jxg.new_tip")
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        from .jcns_importer import _armature_for_new
        tree = do_new(context, _armature_for_new(context))
        _make_working(context, tree)
        msg = T("io.jxg.new_done", tree.name)
        if not show_tree(context, tree):
            msg += T("io.jxg.open_hint")
        self.report({'INFO'}, msg)
        return {'FINISHED'}


class JCNS_OT_ExportJXG(Operator, ExportHelper):
    bl_idname = "jcns.export_jxg"
    bl_label = T("io.jxg.export_label")
    bl_description = T("io.jxg.export_tip")
    filename_ext = ".6"
    filter_glob: StringProperty(default=FILE_GLOB, options={'HIDDEN'})
    tree_name: StringProperty(options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return _active_tree(context) is not None

    def invoke(self, context, event):
        tree = _active_tree(context)
        self.tree_name = tree.name
        base = tree.source_filepath or os.path.join(os.path.dirname(bpy.data.filepath) or os.path.expanduser("~"),
                                                    tree.name)
        self.filepath = base if base.endswith('.6') else strip_version(base) + '.6'
        return super().invoke(context, event)

    def execute(self, context):
        tree = bpy.data.node_groups.get(self.tree_name) or _active_tree(context)
        try:
            data = export_bytes(tree)
        except ExportRefused as ex:
            self.report({'ERROR'}, T("io.jxg.refused", str(ex)))
            return {'CANCELLED'}
        with open(self.filepath, 'wb') as f:
            f.write(data)
        self.report({'INFO'}, T("io.jxg.exported", self.filepath, len(tree_to_graph(tree)['nodes'])))
        return {'FINISHED'}


class JCNS_OT_ShowJXG(Operator):
    bl_idname = "jcns.show_jxg"
    bl_label = T("io.jxg.show_label")
    bl_description = T("io.jxg.show_tip")

    tree_name: StringProperty(options={'HIDDEN'})

    def execute(self, context):
        tree = bpy.data.node_groups.get(self.tree_name)
        if tree is None:
            return {'CANCELLED'}
        if not show_tree(context, tree):
            self.report({'WARNING'}, T("io.jxg.no_node_editor"))
        return {'FINISHED'}


class JCNS_OT_JXGWindow(Operator):
    bl_idname = "jcns.jxg_window"
    bl_label = T("io.jxg.window_label")
    bl_description = T("io.jxg.window_tip")

    tree_name: StringProperty(options={'HIDDEN'})

    def execute(self, context):
        tree = bpy.data.node_groups.get(self.tree_name) or _active_tree(context)
        if tree is None:
            return {'CANCELLED'}
        if not open_tree_window(context, tree):
            self.report({'WARNING'}, T("io.jxg.window_failed"))
            return {'CANCELLED'}
        return {'FINISHED'}


def find_tree_for_path(asset_path):
    want = asset_path.replace('\\', '/').lower()
    for tree in bpy.data.node_groups:
        if tree.bl_idname == TREE_ID and tree.asset_path.lower() == want:
            return tree
    return None


def natives_file_for(jcns_filepath, asset_path):
    """The .jntexprgraph a jcns names, found from the jcns's own location, or ''.

    The game root is where the jcns path enters natives/<platform>/, or failing that
    where it enters the asset path's first folder (an extract without natives/); both
    the root itself and its natives/STM/ are tried.
    """
    asset = asset_path.replace('\\', '/').strip('/')
    if not asset or not jcns_filepath:
        return ''
    parts = jcns_filepath.replace('\\', '/').split('/')
    lower = [p.lower() for p in parts]
    roots = []
    if 'natives' in lower:
        i = len(lower) - 1 - lower[::-1].index('natives')
        roots.append('/'.join(parts[:i + 2]))
    first = asset.split('/')[0].lower()
    if first in lower[:-1]:
        i = lower.index(first)
        roots += ['/'.join(parts[:i]), '/'.join(parts[:i]) + '/natives/STM']
    for root in roots:
        for cand in (root + '/' + asset + '.6', root + '/' + asset):
            if os.path.isfile(cand):
                return cand
    return ''


class JCNS_OT_OpenJXGPath(Operator):
    """Show the graph a jcns's JXG section names: an imported one, else import it from the jcns's natives tree."""
    bl_idname = "jcns.open_jxg_path"
    bl_label = T("io.jxg.open_path_label")
    bl_description = T("io.jxg.open_path_tip")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        from . import get_export_root
        _, rp = get_export_root(context)
        return rp is not None and bool(rp.jxg_path.strip())

    def execute(self, context):
        from . import get_export_root
        _, rp = get_export_root(context)
        path = rp.jxg_path.strip()
        tree = find_tree_for_path(path)
        if tree is None:
            src = natives_file_for(rp.source_filepath, path)
            if not src:
                self.report({'WARNING'}, T("io.jxg.path_not_found", path))
                return {'CANCELLED'}
            tree = do_import(src, context, rp.target_armature)
        if not show_tree(context, tree) and not open_tree_window(context, tree):
            self.report({'WARNING'}, T("io.jxg.window_failed"))
        return {'FINISHED'}


class JCNS_OT_AddJXGNode(Operator):
    bl_idname = "jcns.add_jxg_node"
    bl_label = T("editors.jxg.add_node")
    bl_description = T("editors.jxg.add_node_tip")
    bl_options = {'REGISTER', 'UNDO'}

    type_name: StringProperty(options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        space = context.space_data
        return space is not None and getattr(space, 'tree_type', None) == TREE_ID and space.edit_tree is not None

    def invoke(self, context, event):
        tree = context.space_data.edit_tree
        for n in tree.nodes:
            n.select = False
        node = tree.nodes.new(NODE_ID)
        setup_node(node, self.type_name, jxg_nodes.output_slots(self.type_name))
        node.file_index = tree.next_index
        tree.next_index += 1
        node.location = context.space_data.cursor_location
        node.select = True
        tree.nodes.active = node
        bpy.ops.node.translate_attach_remove_on_cancel('INVOKE_DEFAULT')
        return {'FINISHED'}

    def execute(self, context):
        tree = context.space_data.edit_tree
        node = tree.nodes.new(NODE_ID)
        setup_node(node, self.type_name, jxg_nodes.output_slots(self.type_name))
        node.file_index = tree.next_index
        tree.next_index += 1
        return {'FINISHED'}


class JCNS_OT_SelectJXGNode(Operator):
    bl_idname = "jcns.select_jxg_node"
    bl_label = T("editors.jxg.select_node")
    bl_description = T("editors.jxg.select_node_tip")
    bl_options = {'INTERNAL'}

    guid: StringProperty(options={'HIDDEN'})

    def execute(self, context):
        tree = _active_tree(context)
        if tree is None:
            return {'CANCELLED'}
        for n in tree.nodes:
            n.select = getattr(n, 'guid', None) == self.guid
            if n.select:
                tree.nodes.active = n
        return {'FINISHED'}


class JCNS_OT_LayoutJXG(Operator):
    bl_idname = "jcns.layout_jxg"
    bl_label = T("editors.jxg.layout")
    bl_description = T("editors.jxg.layout_tip")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _active_tree(context) is not None

    def execute(self, context):
        layout_tree(_active_tree(context))
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Add menu
# ---------------------------------------------------------------------------

_MENU_CATEGORIES = ('get', 'set', 'time', 'math', 'vector', 'remap', 'other')


def _menu_class(cat):
    def draw(self, context):
        for name in jxg_nodes.creatable_types():
            if category(name) == cat:
                self.layout.operator(JCNS_OT_AddJXGNode.bl_idname,
                                     text=jxg_nodes.short_name(name)).type_name = name
    return type("JCNS_MT_jxg_add_" + cat, (Menu,), dict(
        bl_idname="JCNS_MT_jxg_add_" + cat, bl_label=T("editors.jxg.cat." + cat), draw=draw))


_ADD_MENUS = [_menu_class(c) for c in _MENU_CATEGORIES]


def _draw_add_menu(self, context):
    space = context.space_data
    if getattr(space, 'tree_type', None) != TREE_ID:
        return
    layout = self.layout
    for m in _ADD_MENUS:
        layout.menu(m.bl_idname)


# ---------------------------------------------------------------------------
# Node editor sidebar
# ---------------------------------------------------------------------------

class _JXGPanel:
    bl_space_type = 'NODE_EDITOR'
    bl_region_type = 'UI'
    bl_category = T("common.category")

    @classmethod
    def poll(cls, context):
        space = context.space_data
        return getattr(space, 'tree_type', None) == TREE_ID and space.edit_tree is not None


class JCNS_PT_jxg_file(_JXGPanel, Panel):
    bl_label = T("ui.jxg.file")
    bl_idname = "JCNS_PT_jxg_file"
    bl_order = 0

    def draw(self, context):
        layout = self.layout
        tree = context.space_data.edit_tree
        layout.label(text=tree.asset_path or os.path.basename(tree.source_filepath) or tree.name, icon='FILE')
        layout.prop(tree, "armature", icon='ARMATURE_DATA')
        row = layout.row(align=True)
        row.operator(JCNS_OT_ExportJXG.bl_idname, icon='EXPORT')
        row.operator(JCNS_OT_LayoutJXG.bl_idname, text="", icon='GRID')
        nodes = [n for n in tree.nodes if n.bl_idname == NODE_ID]
        managed = sum(1 for n in nodes if n.managed)
        layout.label(text=T("ui.jxg.counts", len(nodes), managed) if managed
                     else T("ui.jxg.count", len(nodes)), icon='NODETREE')
        G = tree_to_graph(tree)
        problems = jxg_nodes.validate(G)
        if not problems:
            layout.label(text=T("ui.jxg.valid"), icon='CHECKMARK')
            return
        box = layout.box()
        box.label(text=T("ui.jxg.problems", len(problems)), icon='ERROR')
        for code, i, _ in problems[:10]:
            where = "[%d] %s" % (i, jxg_nodes.short_name(G['nodes'][i]['type'])) if i is not None else ""
            text = T("io.jxg.problem." + code, where)
            if i is not None:
                box.operator(JCNS_OT_SelectJXGNode.bl_idname, text=text,
                             emboss=False).guid = G['nodes'][i]['guid']
            else:
                box.label(text=text)


class JCNS_PT_jxg_node(_JXGPanel, Panel):
    bl_label = T("ui.jxg.node")
    bl_idname = "JCNS_PT_jxg_node"
    bl_order = 1

    @classmethod
    def poll(cls, context):
        if not _JXGPanel.poll.__func__(cls, context):
            return False
        node = context.space_data.edit_tree.nodes.active
        return node is not None and node.bl_idname == NODE_ID

    def draw(self, context):
        layout = self.layout
        node = context.space_data.edit_tree.nodes.active
        layout.label(text=jxg_nodes.short_name(node.type_name), icon='NODE')
        if node.managed:
            col = layout.column(align=True)
            col.label(text=T("ui.jxg.managed"), icon='LOCKED')
            col.label(text=T("ui.jxg.managed_keep"))


class JCNS_PT_jxg_node_advanced(_JXGPanel, Panel):
    bl_label = T("ui.jxg.advanced")
    bl_idname = "JCNS_PT_jxg_node_advanced"
    bl_parent_id = "JCNS_PT_jxg_node"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        node = context.space_data.edit_tree.nodes.active
        if node is None or node.bl_idname != NODE_ID:
            return
        col = layout.column(align=True)
        col.label(text=node.type_name)                          # ui-copy: advanced
        col.label(text="kind %d · #%d" % (node.kind, node.file_index))  # ui-copy: advanced
        col.label(text="guid %s" % node.guid)                   # ui-copy: advanced
        if node.name_hash:
            col.label(text="NodeNameHash %08X" % (node.name_hash & 0xFFFFFFFF))  # ui-copy: advanced
        if node.extra_hex:
            col.label(text="extra %s" % node.extra_hex[:48])    # ui-copy: advanced


# ---------------------------------------------------------------------------
# Drag-and-drop, menus, registration
# ---------------------------------------------------------------------------

class JCNS_FH_ImportJXG(bpy.types.FileHandler):
    bl_idname = "JCNS_FH_import_jxg"
    bl_label = "RE Engine JointExprGraph"
    bl_import_operator = "jcns.import_jxg"
    bl_file_extensions = FILE_EXTENSIONS

    @classmethod
    def poll_drop(cls, context):
        return context.area and context.area.type in {'VIEW_3D', 'OUTLINER', 'NODE_EDITOR'}


def _menu_import(self, context):
    self.layout.operator(JCNS_OT_ImportJXG.bl_idname, text="RE Engine JointExprGraph (.jntexprgraph.*)")


def _menu_export(self, context):
    self.layout.operator(JCNS_OT_ExportJXG.bl_idname, text="RE Engine JointExprGraph (.jntexprgraph.*)")


def _tree_poll(self, tree):
    return tree.bl_idname == TREE_ID


_classes = list(SOCKET_CLASSES) + [
    JCNS_JXG_Tree, JCNS_JXG_Node,
    JCNS_OT_ImportJXG, JCNS_OT_NewJXG, JCNS_OT_ExportJXG, JCNS_OT_ShowJXG, JCNS_OT_JXGWindow, JCNS_OT_OpenJXGPath,
    JCNS_OT_AddJXGNode, JCNS_OT_SelectJXGNode, JCNS_OT_LayoutJXG,
] + _ADD_MENUS + [JCNS_PT_jxg_file, JCNS_PT_jxg_node, JCNS_PT_jxg_node_advanced]


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.Object.jcns_jxg_tree = PointerProperty(type=bpy.types.NodeTree, poll=_tree_poll)
    bpy.types.NODE_MT_add.append(_draw_add_menu)
    bpy.types.TOPBAR_MT_file_import.append(_menu_import)
    bpy.types.TOPBAR_MT_file_export.append(_menu_export)
    if bpy.app.version >= (4, 1, 0):
        bpy.utils.register_class(JCNS_FH_ImportJXG)


def unregister():
    if bpy.app.version >= (4, 1, 0):
        bpy.utils.unregister_class(JCNS_FH_ImportJXG)
    bpy.types.TOPBAR_MT_file_export.remove(_menu_export)
    bpy.types.TOPBAR_MT_file_import.remove(_menu_import)
    bpy.types.NODE_MT_add.remove(_draw_add_menu)
    del bpy.types.Object.jcns_jxg_tree
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
