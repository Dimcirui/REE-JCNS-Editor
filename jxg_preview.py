"""
jxg_preview.py
--------------
Play an expression graph on its armature: after each frame change and each edit,
read the evaluated pose, run the graph (modules/jxg_eval.py) and write the bones it
sets as pose bases.  Turning the preview off puts those bases back.

Space: RE Mesh Editor bakes the game's Y-up into the bones by +90 degrees about X
(RX) and leaves the armature object unrotated, so a bone's game local transform is
parent_pose^-1 @ pose (RX^-1 @ pose for a root bone) and the roots hang from the
owner RX^-1 @ object @ RX — the same mapping Wilds-Dynamics uses.

Time is (frame - frame_start) / fps seconds.  The time nodes accumulate: each frame
change forward by at most MAX_STEP advances their phase by speed * dt, so a speed that
changes speeds the turn up smoothly.  Going backwards or jumping further restarts them
at speed * t; an edit or a pose change without a frame change leaves them where they are.
"""

import json
import math

import bpy
from mathutils import Matrix, Quaternion, Vector

from .modules_shim import T, ensure_path

ensure_path()
import jxg_eval  # noqa: E402
import jxg_nodes  # noqa: E402

RX = Matrix.Rotation(math.pi / 2, 4, 'X')
RX_INV = RX.inverted()
_RESTORE = "jxg_preview_restore"          # tree idprop: {bone: matrix_basis as 16 floats}

# tree name -> last run's notes for the panel: (unsupported types, missing joint count, problem key)
notes = {}
_busy = False
MAX_STEP = 1.0                            # seconds; a longer frame step restarts the time nodes
_clock = {}                               # tree name -> {'t': last frame-change time, 'phases': {guid: phase}}
_hash_cache = {}


def _hashes(arm):
    """bone name hash (unsigned) -> bone name, cached per armature and bone count."""
    key = (arm.name, len(arm.data.bones))
    if key not in _hash_cache:
        from .jxg_editor import jxg_hash
        _hash_cache[key] = {jxg_hash(b.name) & 0xFFFFFFFF: b.name for b in arm.data.bones}
    return _hash_cache[key]


def _local_of(pb):
    return (pb.parent.matrix.inverted() @ pb.matrix) if pb.parent else RX_INV @ pb.matrix


def _rest_local(bone):
    return (bone.parent.matrix_local.inverted() @ bone.matrix_local) if bone.parent else RX_INV @ bone.matrix_local


def _pq(m):
    loc, rot, _scale = m.decompose()
    return tuple(loc), (rot.w, rot.x, rot.y, rot.z)


def skeleton_of(arm_eval, names):
    """A jxg_eval.Skeleton of the evaluated armature, keyed by bone name hash."""
    by_name = {n: h for h, n in names.items()}
    joints = {}
    for pb in arm_eval.pose.bones:
        h = by_name.get(pb.name)
        if h is None:
            continue
        parent = by_name.get(pb.parent.name) if pb.parent else None
        rpos, rq = _pq(_rest_local(pb.bone))
        pos, q = _pq(_local_of(pb))
        joints[h] = (parent, rpos, rq, pos, q)
    owner = RX_INV @ arm_eval.matrix_world @ RX
    return jxg_eval.Skeleton(joints, _pq(owner))


def scene_time(scene):
    fps = scene.render.fps / (scene.render.fps_base or 1.0)
    return (scene.frame_current + scene.frame_subframe - scene.frame_start) / (fps or 24.0)


def _basis_for(pb_orig, bone, pos, q, scale):
    L = Matrix.LocRotScale(Vector(pos), Quaternion(q), scale)
    return _rest_local(bone).inverted() @ L


def _same(a, b, eps=1e-6):
    return all(abs(a[i][j] - b[i][j]) < eps for i in range(4) for j in range(4))


def _step(tree, t, advance):
    """(phases, dt) for this run: playback advances by the frame step, anything else by 0."""
    clock = _clock.setdefault(tree.name, {'t': None, 'phases': {}})
    if not advance:
        return clock['phases'], 0.0
    last, clock['t'] = clock['t'], t
    if last is None or not 0.0 < t - last <= MAX_STEP:
        clock['phases'].clear()
        return clock['phases'], 0.0
    return clock['phases'], t - last


def run(tree, depsgraph=None, scene=None, advance=False):
    """Evaluate `tree` once and write its bones; returns the jxg_eval.Result or None.

    `advance`: this run is for a frame change, so the time nodes move on by the frame step."""
    arm = tree.armature
    if arm is None or arm.type != 'ARMATURE':
        notes[tree.name] = ((), 0, "ui.jxg.preview_no_armature")
        return None
    from .jxg_editor import tree_to_graph
    G = tree_to_graph(tree)
    if jxg_nodes.validate(G):
        notes[tree.name] = ((), 0, "ui.jxg.preview_invalid")
        return None
    depsgraph = depsgraph or bpy.context.evaluated_depsgraph_get()
    scene = scene or bpy.context.scene
    names = _hashes(arm)
    ev = arm.evaluated_get(depsgraph)
    skel = skeleton_of(ev, names)
    t = scene_time(scene)
    phases, dt = _step(tree, t, advance)
    res = jxg_eval.evaluate(G, skel, t, phases, dt)
    restore = json.loads(tree.get(_RESTORE, "{}"))
    added = False
    for h, (pos, q) in res.writes.items():
        name = names[h]
        pb, pe = arm.pose.bones[name], ev.pose.bones[name]
        cur_pos, cur_q = _pq(_local_of(pe))
        scale = _local_of(pe).to_scale()
        basis = _basis_for(pb, pb.bone, pos or cur_pos, q or cur_q, scale)
        if name not in restore:
            restore[name] = [v for row in pb.matrix_basis for v in row]
            added = True
        if not _same(basis, pb.matrix_basis):
            pb.matrix_basis = basis
    if added:                                # writing it every run would itself trigger an update
        tree[_RESTORE] = json.dumps(restore)
    notes[tree.name] = (tuple(sorted(res.unsupported)), len(res.missing_joints), "")
    return res


def restore(tree, keep_clock=False):
    """Put back the pose bases the preview overwrote; `keep_clock` keeps the time nodes' phases."""
    saved = json.loads(tree.get(_RESTORE, "{}"))
    arm = tree.armature
    if arm is not None and arm.type == 'ARMATURE':
        for name, flat in saved.items():
            pb = arm.pose.bones.get(name)
            if pb is not None:
                pb.matrix_basis = Matrix([flat[0:4], flat[4:8], flat[8:12], flat[12:16]])
    if _RESTORE in tree:
        del tree[_RESTORE]
    notes.pop(tree.name, None)
    if not keep_clock:
        _clock.pop(tree.name, None)


def _live_trees():
    from .jxg_editor import TREE_ID
    return [t for t in bpy.data.node_groups if t.bl_idname == TREE_ID and t.preview_on]


def run_all(scene=None, depsgraph=None, advance=False):
    global _busy
    if _busy:
        return
    _busy = True
    try:
        for tree in _live_trees():
            run(tree, depsgraph, scene, advance)
    finally:
        _busy = False


@bpy.app.handlers.persistent
def _on_frame(scene, depsgraph=None):
    run_all(scene, depsgraph, advance=True)


@bpy.app.handlers.persistent
def _on_depsgraph(scene, depsgraph):
    if _busy or not _live_trees():
        return
    run_all(scene, depsgraph)


# A saved file keeps the bones as they were before the preview, as JCNS previews do.
@bpy.app.handlers.persistent
def _on_save_pre(*_args):
    for tree in _live_trees():
        restore(tree, keep_clock=True)


@bpy.app.handlers.persistent
def _on_save_post(*_args):
    run_all()


def preview_changed(tree, context):
    if tree.preview_on:
        _clock.pop(tree.name, None)
        run(tree, advance=True)
    else:
        restore(tree)


_HANDLERS = ((bpy.app.handlers.frame_change_post, _on_frame), (bpy.app.handlers.depsgraph_update_post, _on_depsgraph),
             (bpy.app.handlers.save_pre, _on_save_pre), (bpy.app.handlers.save_post, _on_save_post))


def draw_preview(layout, tree):
    """The preview switch and what the last run could not do."""
    row = layout.row(align=True)
    row.prop(tree, "preview_on", text=T("ui.jxg.preview"), toggle=True,
             icon='PAUSE' if tree.preview_on else 'PLAY')
    if not tree.preview_on:
        return
    unsupported, missing, problem = notes.get(tree.name, ((), 0, ""))
    col = layout.column(align=True)
    if problem:
        col.label(text=T(problem), icon='ERROR')
        return
    col.label(text=T("ui.jxg.preview_hint"), icon='INFO')
    if unsupported:
        col.label(text=T("ui.jxg.preview_unsupported", ", ".join(s.replace('Node', '') for s in unsupported)),
                  icon='QUESTION')
    if missing:
        col.label(text=T("ui.jxg.preview_missing", missing), icon='BONE_DATA')


def register():
    for lst, fn in _HANDLERS:
        if fn not in lst:
            lst.append(fn)


def unregister():
    for lst, fn in _HANDLERS:
        if fn in lst:
            lst.remove(fn)
