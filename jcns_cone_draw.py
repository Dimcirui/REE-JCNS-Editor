"""
Viewport drawing of the selected ConeInput of every JCNS root that has it switched on
(JCNSRootProperties.draw_cones), so a cone can be aimed by eye.

At the cone joint's head it draws:
  * the cone: its axis (the reference direction, ParentJoint * [rest] * Direction * X)
    and the circle and side lines of the half angle;
  * the joint's current direction (joint * Matrix * Y), coloured from red (cone value 0)
    to green (1).
Lengths follow the joint's bone length.  The geometry is the one
jcns_source_read.cone_value measures; Blender bone axes are the engine's.
"""

import math

import bpy
import gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Quaternion, Vector

from .modules_shim import ensure_path

ensure_path()
import jcns_source_read  # noqa: E402

_HANDLE = None
_SEGMENTS = 48
_CONE_COLOR = (0.35, 0.75, 1.0, 0.9)
_AXIS_COLOR = (1.0, 1.0, 1.0, 0.9)


def _rot(matrix):
    return matrix.to_3x3().normalized().to_quaternion()


def _cone_geometry(arm, ci):
    """(apex, reference dir, current dir, length, value) in world space, or None."""
    from .jcns_operators import _armature_bone, _rest_transform
    joint = _armature_bone(arm, ci.joint.strip())
    parent = _armature_bone(arm, ci.parent_joint.strip())
    if joint is None or parent is None:
        return None
    pj = arm.pose.bones[joint]
    pp = arm.pose.bones[parent]
    world = arm.matrix_world
    jq = _rot(world @ pj.matrix)
    pq = _rot(world @ pp.matrix)
    rest = Quaternion(_rest_transform(arm, joint)[0])       # as the preview reads it
    x, y, z, w = ci.direction
    ref_local = Quaternion((w, x, y, z)) @ Vector((1.0, 0.0, 0.0))
    if ci.base_pose:
        ref_local = rest @ ref_local
    m = ci.matrix
    cur_local = Vector((m[1], m[5], m[9]))
    ref = (pq @ ref_local).normalized()
    cur = (jq @ cur_local).normalized()
    rel = pq.inverted() @ jq if parent != joint else Quaternion()
    value = jcns_source_read.cone_value(
        (rel.w, rel.x, rel.y, rel.z), (rest.w, rest.x, rest.y, rest.z), tuple(ci.direction),
        (tuple(m[0:3]), tuple(m[4:7]), tuple(m[8:11])), ci.angle, ci.base_pose)
    apex = world @ pj.head
    length = max(pj.length * world.median_scale, 1e-3)
    return apex, ref, cur, length, value


def _cone_lines(apex, axis, half, length):
    """Line-list points of the cone around `axis`: the circle at the half angle and
    eight side lines from the apex."""
    side = axis.orthogonal().normalized()
    up = axis.cross(side).normalized()
    centre = apex + axis * (length * math.cos(half))
    r = length * math.sin(half)
    ring = [centre + (side * math.cos(t) + up * math.sin(t)) * r
            for t in (2 * math.pi * i / _SEGMENTS for i in range(_SEGMENTS))]
    pts = []
    for i in range(_SEGMENTS):
        pts += [ring[i], ring[(i + 1) % _SEGMENTS]]
    for i in range(0, _SEGMENTS, _SEGMENTS // 8):
        pts += [apex, ring[i]]
    return pts


def _cones_to_draw():
    for obj in bpy.data.objects:
        rp = getattr(obj, 'jcns_root_props', None)
        if rp is None or not rp.draw_cones or not len(rp.cone_inputs):
            continue
        arm = rp.target_armature
        if arm is None or arm.type != 'ARMATURE' or not arm.visible_get():
            continue
        yield arm, rp.cone_inputs[min(rp.active_cone_input_index, len(rp.cone_inputs) - 1)]


def _draw():
    try:
        items = [(ci, g) for arm, ci in _cones_to_draw() for g in [_cone_geometry(arm, ci)] if g is not None]
    except Exception as exc:                 # drawing must never break the viewport
        print("[JCNS] cone drawing skipped: %r" % exc)
        return
    if not items:
        return
    try:
        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        gpu.state.blend_set('ALPHA')
        for ci, (apex, ref, cur, length, value) in items:
            shader.bind()
            gpu.state.line_width_set(2.0)
            shader.uniform_float("color", _CONE_COLOR)
            batch_for_shader(shader, 'LINES', {"pos": _cone_lines(apex, ref, ci.angle, length)}).draw(shader)
            shader.uniform_float("color", _AXIS_COLOR)
            batch_for_shader(shader, 'LINES', {"pos": [apex, apex + ref * length * 1.2]}).draw(shader)
            v = min(max(value, 0.0), 1.0)
            shader.uniform_float("color", (1.0 - 0.8 * v, 0.2 + 0.7 * v, 0.2, 1.0))
            gpu.state.line_width_set(3.0)
            batch_for_shader(shader, 'LINES', {"pos": [apex, apex + cur * length]}).draw(shader)
    except Exception as exc:
        print("[JCNS] cone drawing skipped: %r" % exc)
    finally:
        gpu.state.line_width_set(1.0)
        gpu.state.blend_set('NONE')


def tag_redraw(_self=None, _context=None):
    for win in getattr(bpy.context.window_manager, 'windows', []):
        for area in win.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


def register():
    global _HANDLE
    if _HANDLE is None:
        _HANDLE = bpy.types.SpaceView3D.draw_handler_add(_draw, (), 'WINDOW', 'POST_VIEW')


def unregister():
    global _HANDLE
    if _HANDLE is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_HANDLE, 'WINDOW')
        _HANDLE = None
