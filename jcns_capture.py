"""
Anchor capture on the Blender side: the eyedropper buttons beside the six Ranges
anchors and the live read-out on the mapping panel.

The maths lives in modules/jcns_capture.py (imported here as `core`, not to be confused
with this file); this file only collects the pose, rest transform and scale factors from
the target armature the same way the drivers do (jcns_operators.channel_sources,
register_translation_group) and writes the result into the source's anchor property, whose
update callback refreshes an applied preview.
"""

import bpy
from bpy.types import Operator
from bpy.props import EnumProperty

from .modules_shim import ensure_path, get_mapping

ensure_path()
import jcns_capture as core  # noqa: E402  (modules/jcns_capture.py)


# (property, name, description); the source side reads the driving bone, the target side
# takes the driven bone's pose.
_FIELD_ITEMS = [
    ('from_start', "From 起点", "读取驱动骨骼当前的值，填入起点 A 的输入"),
    ('from_kink',  "From 折点", "读取驱动骨骼当前的值，填入折点 B 的输入"),
    ('from_end',   "From 终点", "读取驱动骨骼当前的值，填入终点 C 的输入"),
    ('to_start',   "To 起点",   "按目标骨骼当前姿态算出要写入的值，填入起点 A 的输出"),
    ('to_kink',    "To 折点",   "按目标骨骼当前姿态算出要写入的值，填入折点 B 的输出"),
    ('to_end',     "To 终点",   "按目标骨骼当前姿态算出要写入的值，填入终点 C 的输出"),
]
_FIELD_NAME = {ident: name for ident, name, _desc in _FIELD_ITEMS}

FIELDS = tuple(ident for ident, _n, _d in _FIELD_ITEMS)


def _pose_of(pose_bone):
    """(XYZ Euler in radians, location, scale) of a pose bone, whatever its rotation mode."""
    if pose_bone.rotation_mode == 'XYZ':
        euler = tuple(pose_bone.rotation_euler)
    else:
        euler = tuple(pose_bone.matrix_basis.to_3x3().normalized().to_euler('XYZ'))
    return euler, tuple(pose_bone.location), tuple(pose_bone.scale)


def read_source(arm, sp):
    """What source `sp` reads off its bone in its current pose, in the file's units;
    None when the bone or axis cannot be read."""
    from . import AXIS_TO_INT
    from .jcns_operators import _rest_transform, mesh_rest_scale
    axis = AXIS_TO_INT.get(sp.source_axis, 0)
    pose_bone = arm.pose.bones.get(sp.source_bone)
    bone = arm.data.bones.get(sp.source_bone)
    if pose_bone is None or bone is None or axis > 2:
        return None
    rest, offset = _rest_transform(arm, sp.source_bone)
    euler, loc, scale = _pose_of(pose_bone)
    return core.capture_source(
        sp.read_mode, axis, rest, offset, euler, loc, scale,
        order=sp.euler_order,
        frame=(sp.ref_frame_w, sp.ref_frame_x, sp.ref_frame_y, sp.ref_frame_z),
        rest_scale=mesh_rest_scale(bone))


def read_target(arm, p):
    """(value, error) the entry `p` would write on its axis to hold its target bone in the
    current pose; None when there is no rule for it.  See jcns_capture.capture_target."""
    from . import AXIS_TO_INT
    from .jcns_exporter import _transform_int
    from .jcns_operators import _rest_transform, mesh_rest_scale
    axis = AXIS_TO_INT.get(p.target_axis, 0)
    pose_bone = arm.pose.bones.get(p.target_bone)
    bone = arm.data.bones.get(p.target_bone)
    if pose_bone is None or bone is None:
        return None
    rest, offset = _rest_transform(arm, p.target_bone)
    # The parent's rest scale, as register_translation_group takes it.
    parent_scale = mesh_rest_scale(bone.parent) if bone.parent is not None else (1.0, 1.0, 1.0)
    euler, loc, scale = _pose_of(pose_bone)
    return core.capture_target(_transform_int(p.transform_type), p.additive, axis, rest,
                               euler, loc, scale, offset, parent_scale, mesh_rest_scale(bone))


def _entry(context):
    """The active Ranges entry with a source, as a namespace (obj, p, sp, rp, arm); arm is
    None until the file has a target armature.  None when there is no such entry."""
    from types import SimpleNamespace
    from . import get_jcns_constraint, get_jcns_root_from_constraint
    obj, p = get_jcns_constraint(context)
    if obj is None or p.constraint_type not in ('Ranges', '') or not len(p.sources):
        return None
    _root, rp = get_jcns_root_from_constraint(obj)
    if rp is None:
        return None
    arm = rp.target_armature
    if arm is not None and arm.type != 'ARMATURE':
        arm = None
    sp = p.sources[min(p.active_source_index, len(p.sources) - 1)]
    return SimpleNamespace(obj=obj, p=p, sp=sp, rp=rp, arm=arm)


class JCNS_OT_CaptureAnchor(Operator):
    """把骨骼当前姿态对应的值填进这个锚点"""
    bl_idname = "jcns.capture_anchor"
    bl_label  = "从当前姿态取值"
    bl_options = {'REGISTER', 'UNDO'}

    field: EnumProperty(name="锚点", items=_FIELD_ITEMS)

    @classmethod
    def description(cls, context, properties):
        for ident, _name, desc in _FIELD_ITEMS:
            if ident == properties.field:
                return desc + "。先在骨架上摆好骨骼的姿态"
        return cls.__doc__

    @classmethod
    def poll(cls, context):
        from .jcns_operators import _caps_for
        st = _entry(context)
        return st is not None and st.arm is not None and _caps_for(st.rp, 'Ranges').can_edit

    def execute(self, context):
        from .jcns_exporter import _transform_int
        from .jcns_ui import _target_unit
        st = _entry(context)
        if st is None or st.arm is None:
            self.report({'ERROR'}, "先在「骨架」里设置目标骨架。")
            return {'CANCELLED'}
        source_side = self.field.startswith('from_')
        if source_side:
            role, bone, axis = "驱动骨骼", st.sp.source_bone, st.sp.source_axis
        else:
            role, bone, axis = "目标骨骼", st.p.target_bone, st.p.target_axis
        if not bone:
            self.report({'ERROR'}, "还没有设置%s。" % role)
            return {'CANCELLED'}
        if bone not in st.arm.pose.bones:
            self.report({'ERROR'}, "目标骨架「%s」里没有骨骼「%s」。" % (st.arm.name, bone))
            return {'CANCELLED'}
        if axis == 'W':
            self.report({'ERROR'}, "W 轴暂不支持取值。")
            return {'CANCELLED'}

        warning = ""
        if source_side:
            value = read_source(st.arm, st.sp)
            unit = get_mapping().source_unit(st.sp)
            if value is None:
                self.report({'ERROR'}, "这种读取方式没有可取的值。")
                return {'CANCELLED'}
        else:
            if not core.target_capturable(_transform_int(st.p.transform_type)):
                self.report({'ERROR'}, "变换类型「%s」没有骨骼姿态可取。" % st.p.transform_type)
                return {'CANCELLED'}
            got = read_target(st.arm, st.p)
            if got is None:
                self.report({'ERROR'}, "这个姿态下取不出值：父骨缩放为 0，或扭转角没有定义。")
                return {'CANCELLED'}
            value, error = got
            unit = _target_unit(st.p.transform_type)
            if error > 0.5:
                warning = ("姿态不是纯绕 %s 轴的旋转，只取了绕该轴的转角，另有 %.1f° 这条约束表达不了。"
                           % (axis, error))
            elif st.p.preview_on:
                warning = "本条的预览正在驱动目标骨骼，读到的是预览姿态。先清除预览，再摆姿态取值。"

        # Assigning runs the property's update, which refreshes an applied preview.
        setattr(st.sp, self.field, round(value, 5) + 0.0)
        text = "已取 %s = %.2f%s" % (_FIELD_NAME[self.field], value, unit)
        if warning:
            self.report({'WARNING'}, "%s。%s" % (text, warning))
        else:
            self.report({'INFO'}, text + "。")
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Panel helpers (called from jcns_editors)
# ---------------------------------------------------------------------------

def sides_readable(c, sp):
    """(source, target) flags: can the eyedropper buttons of each side read a bone?"""
    arm = c.rp.target_armature
    if arm is None or arm.type != 'ARMATURE':
        return False, False
    poses = arm.pose.bones
    source_ok = bool(sp.source_bone) and sp.source_bone in poses and sp.source_axis != 'W'
    target_ok = bool(c.p.target_bone) and c.p.target_bone in poses and c.p.target_axis != 'W'
    return source_ok, target_ok


def anchor_cell(row, sp, field, enabled=True):
    """An anchor's number field with its eyedropper button on the right."""
    cell = row.row(align=True)
    cell.prop(sp, field, text="")
    btn = cell.row(align=True)
    btn.enabled = enabled
    op = btn.operator("jcns.capture_anchor", text="", icon='EYEDROPPER')
    op.field = field


_readout_failed = False


def draw_readout(layout, c, sp):
    """One label: what the source bone reads right now and what the mapping makes of it.
    Runs on every redraw, so it only reads a pose and evaluates the curve; it says nothing
    when there is no armature and never raises."""
    global _readout_failed
    try:
        _draw_readout(layout, c, sp)
    except Exception as exc:
        if not _readout_failed:
            _readout_failed = True
            print("[JCNS] live read-out skipped: %r" % exc)


def _draw_readout(layout, c, sp):
    from . import jcns_cm
    from .jcns_ui import _target_unit
    arm = c.rp.target_armature
    if arm is None or arm.type != 'ARMATURE' or not sp.source_bone or sp.source_axis == 'W':
        return
    if sp.source_bone not in arm.pose.bones:
        layout.label(text="目标骨架里没有骨骼「%s」，读不到当前值" % sp.source_bone, icon='INFO')
        return
    x = read_source(arm, sp)
    if x is None:
        return
    m = get_mapping()
    anchors = (sp.from_start, sp.from_kink, sp.from_end, sp.to_start, sp.to_kink, sp.to_end)
    y = core.mapped_output(anchors, x, m.source_two_point(sp), m.source_interpolation(sp),
                           jcns_cm.keys(sp))
    text = "当前读到 %.2f%s → 输出 %.2f%s" % (x, m.source_unit(sp), y, _target_unit(c.p.transform_type))
    if len(c.p.sources) > 1:
        text += "（仅本源，各源输出相加）"
    layout.label(text=text, icon='EYEDROPPER')


_classes = [JCNS_OT_CaptureAnchor]


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
