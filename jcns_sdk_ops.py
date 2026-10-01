"""
Pose-driven constraint creation (the Set Driven Key workflow) on the Blender side:
the key list stored on the root, the panel, and the operators that record poses and
turn them into Ranges entries.

modules/jcns_sdk.py decides what a set of keys means; this file collects the poses and
rest transforms from the target armature the way jcns_capture does and lands the plan
on the file's entries.  A key keeps both bones' raw pose basis, so how it is read is
only decided when constraints are generated.
"""

import bpy
from bpy.types import Operator, Panel, PropertyGroup, UIList
from bpy.props import BoolProperty, EnumProperty, FloatVectorProperty

from .modules_shim import ensure_path

ensure_path()
import jcns_sdk as core  # noqa: E402  (modules/jcns_sdk.py)
import jcns_source_read as sr  # noqa: E402


class JCNSSDKKey(PropertyGroup):
    """The pose basis of both bones at one recorded key."""
    driver_loc: FloatVectorProperty(size=3, default=(0.0, 0.0, 0.0))
    driver_rot: FloatVectorProperty(size=4, default=(1.0, 0.0, 0.0, 0.0))
    driver_scale: FloatVectorProperty(size=3, default=(1.0, 1.0, 1.0))
    driven_loc: FloatVectorProperty(size=3, default=(0.0, 0.0, 0.0))
    driven_rot: FloatVectorProperty(size=4, default=(1.0, 0.0, 0.0, 0.0))
    driven_scale: FloatVectorProperty(size=3, default=(1.0, 1.0, 1.0))


def search_bones(self, context, edit_text):
    """Bone names of the target armature for the two bone fields; `self` is the root's properties."""
    arm = self.target_armature
    if arm is None or arm.type != 'ARMATURE':
        return []
    needle = edit_text.lower()
    return sorted(b.name for b in arm.data.bones if needle in b.name.lower())


# ---------------------------------------------------------------------------
# Reading and writing poses
# ---------------------------------------------------------------------------

def snapshot(pose_bone):
    """(location, quaternion, scale) of a pose bone's basis, whatever its rotation mode."""
    loc, rot, scale = pose_bone.matrix_basis.decompose()
    return tuple(loc), tuple(rot), tuple(scale)


def apply_pose(pose_bone, loc, rot, scale):
    from mathutils import Matrix, Quaternion, Vector
    pose_bone.matrix_basis = Matrix.LocRotScale(Vector(loc), Quaternion(rot), Vector(scale))


def _store(key, side, pose_bone):
    loc, rot, scale = snapshot(pose_bone)
    setattr(key, side + '_loc', loc)
    setattr(key, side + '_rot', rot)
    setattr(key, side + '_scale', scale)


def _pose_of(key, side):
    return core.Pose(tuple(getattr(key, side + '_loc')), tuple(getattr(key, side + '_rot')),
                     tuple(getattr(key, side + '_scale')))


def _rest_of(arm, name):
    from .jcns_operators import _rest_transform, mesh_rest_scale
    bone = arm.data.bones[name]
    rest, offset = _rest_transform(arm, name)
    parent_scale = mesh_rest_scale(bone.parent) if bone.parent is not None else (1.0, 1.0, 1.0)
    return core.BoneRest(rest, offset, mesh_rest_scale(bone), parent_scale)


# ---------------------------------------------------------------------------
# State shared by the panel and the operators
# ---------------------------------------------------------------------------

class _State:
    def __init__(self, root, rp, arm, driver, driven):
        self.root, self.rp, self.arm, self.driver, self.driven = root, rp, arm, driver, driven

    def keys(self):
        return [core.Key(_pose_of(k, 'driver'), _pose_of(k, 'driven')) for k in self.rp.sdk_keys]

    def bones(self):
        return self.arm.pose.bones[self.driver], self.arm.pose.bones[self.driven]


def _state(context):
    """(_State, '') when keys can be recorded and read, else (None, why not)."""
    from . import get_export_root
    root, rp = get_export_root(context)
    if rp is None:
        return None, ""
    arm = rp.target_armature
    if arm is None or arm.type != 'ARMATURE':
        return None, "先在上面的「骨架」里设置目标骨架。"
    for role, name in (("驱动骨", rp.sdk_driver_bone), ("被驱动骨", rp.sdk_driven_bone)):
        if not name:
            return None, "先设置%s。" % role
        if name not in arm.pose.bones:
            return None, "目标骨架「%s」里没有%s「%s」。" % (arm.name, role, name)
    if rp.sdk_driver_bone == rp.sdk_driven_bone:
        return None, "驱动骨和被驱动骨不能是同一根骨骼。"
    return _State(root, rp, arm, rp.sdk_driver_bone, rp.sdk_driven_bone), ""


def _previewed(st):
    """Names among the two bones that a preview is driving, so their recorded poses would
    be the preview's rather than the user's."""
    names = {st.driver, st.driven}
    hit = set()
    anim = st.arm.animation_data
    if anim is not None:
        for fc in anim.drivers:
            if fc.data_path.startswith('pose.bones["') and 'jcns_ch' in fc.driver.expression:
                bone = fc.data_path[len('pose.bones["'):fc.data_path.find('"]')]
                if bone in names:
                    hit.add(bone)
    for e in st.root.children:
        p = getattr(e, 'jcns_cns_props', None)
        if p is not None and p.is_jcns_constraint and p.preview_on and (
                p.target_bone in names or p.preview_bone in names):
            hit.update(n for n in (p.target_bone, p.preview_bone) if n in names)
    return sorted(hit)


_READ_ITEMS = [('AUTO', "自动", "按各键之间变化最大的量选取：旋转，其次位置，其次缩放")] + [
    (ident, "%d %s" % (value, name), desc) for value, ident, name, _q, desc in sr.READ_MODES]
_AXIS_ITEMS = [('AUTO', "自动", "取变化最大的轴"), ('X', "X", ""), ('Y', "Y", ""), ('Z', "Z", "")]


def make_plan(st, read_mode='AUTO', source_axis='AUTO'):
    """The plan for the recorded keys, with the preview warning added."""
    plan = core.plan_keys(
        st.keys(), _rest_of(st.arm, st.driver), _rest_of(st.arm, st.driven),
        read_mode=None if read_mode == 'AUTO' else read_mode,
        axis=None if source_axis == 'AUTO' else 'XYZ'.index(source_axis))
    hit = _previewed(st)
    if hit:
        plan.warnings.append("「%s」上有预览在驱动，记录的姿态会被预览改写。先清除预览，再摆姿势记录"
                             % "」「".join(hit))
    return plan


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

class _SDKOperator(Operator):
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _state(context)[0] is not None

    def state(self, context):
        st, why = _state(context)
        if st is None:
            self.report({'ERROR'}, why or "找不到 JCNS 根节点。")
        return st


class JCNS_OT_SDKPickBone(Operator):
    """把姿态模式下的活动骨填进这个骨骼栏"""
    bl_idname = "jcns.sdk_pick_bone"
    bl_label  = "取选中骨"
    bl_options = {'REGISTER', 'UNDO'}

    role: EnumProperty(name="骨骼栏", items=[('DRIVER', "驱动骨", ""), ('DRIVEN', "被驱动骨", "")])

    @classmethod
    def poll(cls, context):
        from . import get_export_root
        root, rp = get_export_root(context)
        return rp is not None and rp.target_armature is not None

    def execute(self, context):
        from . import get_export_root
        root, rp = get_export_root(context)
        arm = rp.target_armature
        pb = context.active_pose_bone
        if pb is None:
            self.report({'ERROR'}, "先进入姿态模式，选中一根骨骼。")
            return {'CANCELLED'}
        if pb.id_data != arm:
            self.report({'ERROR'}, "活动骨不在目标骨架「%s」里。" % arm.name)
            return {'CANCELLED'}
        setattr(rp, 'sdk_driver_bone' if self.role == 'DRIVER' else 'sdk_driven_bone', pb.name)
        return {'FINISHED'}


class JCNS_OT_SDKKeyAdd(_SDKOperator):
    """把驱动骨和被驱动骨现在的姿态记成一个键"""
    bl_idname = "jcns.sdk_key_add"
    bl_label  = "记录当前姿态"

    def execute(self, context):
        st = self.state(context)
        if st is None:
            return {'CANCELLED'}
        key = st.rp.sdk_keys.add()
        driver, driven = st.bones()
        _store(key, 'driver', driver)
        _store(key, 'driven', driven)
        st.rp.sdk_key_index = len(st.rp.sdk_keys) - 1
        return {'FINISHED'}


class JCNS_OT_SDKKeyRemove(Operator):
    """删除列表里选中的键"""
    bl_idname = "jcns.sdk_key_remove"
    bl_label  = "删除"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        from . import get_export_root
        root, rp = get_export_root(context)
        return rp is not None and len(rp.sdk_keys) > 0

    def execute(self, context):
        from . import get_export_root
        root, rp = get_export_root(context)
        i = min(rp.sdk_key_index, len(rp.sdk_keys) - 1)
        rp.sdk_keys.remove(i)
        rp.sdk_key_index = max(0, min(i, len(rp.sdk_keys) - 1))
        return {'FINISHED'}


class JCNS_OT_SDKKeyGoto(_SDKOperator):
    """把驱动骨和被驱动骨摆成选中键的姿态"""
    bl_idname = "jcns.sdk_key_goto"
    bl_label  = "跳到此键"

    @classmethod
    def poll(cls, context):
        st = _state(context)[0]
        return st is not None and len(st.rp.sdk_keys) > 0

    def execute(self, context):
        st = self.state(context)
        if st is None:
            return {'CANCELLED'}
        key = st.rp.sdk_keys[min(st.rp.sdk_key_index, len(st.rp.sdk_keys) - 1)]
        for pb, side in zip(st.bones(), ('driver', 'driven')):
            apply_pose(pb, getattr(key, side + '_loc'), getattr(key, side + '_rot'),
                       getattr(key, side + '_scale'))
        return {'FINISHED'}


class JCNS_OT_SDKPoseReset(_SDKOperator):
    """把驱动骨和被驱动骨的姿态清零，回到静止姿态"""
    bl_idname = "jcns.sdk_pose_reset"
    bl_label  = "回到静止姿态"

    def execute(self, context):
        st = self.state(context)
        if st is None:
            return {'CANCELLED'}
        for pb in st.bones():
            apply_pose(pb, (0.0, 0.0, 0.0), (1.0, 0.0, 0.0, 0.0), (1.0, 1.0, 1.0))
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Landing a plan on the file
# ---------------------------------------------------------------------------

def _fill_source(sp, c, driver):
    from . import INT_TO_AXIS
    sp.source_bone = driver
    sp.source_axis = INT_TO_AXIS[c.source_axis]
    sp.read_mode = sr.read_mode_id(c.read_mode)
    sp.euler_order = sr.EULER_ORDER_NAMES[c.euler_order]
    sp.three_point = c.three_point
    for field, v in zip(('from_start', 'from_kink', 'from_end'), c.from_anchors):
        setattr(sp, field, round(v, 5) + 0.0)
    for field, v in zip(('to_start', 'to_kink', 'to_end'), c.to_anchors):
        setattr(sp, field, round(v, 5) + 0.0)


def land(context, st, plan, append):
    """Write the plan's constraints into the file.  -> (new entries, appended sources, last entry).

    A constraint whose channel already has an entry that can take another source
    (core.can_append) adds a source to the file's last entry on the channel when `append`;
    the others become new entries at the end of the file.
    """
    from . import (INT_TO_AXIS, TRANSFORM_TYPE_MAP, _sync_constraint_name,
                   group_constraints_by_channel, jcns_preview)
    from .jcns_operators import _clear_channel, new_constraint_empty

    created = appended = 0
    last = None
    was_previewed = []
    for c in plan.constraints:
        transform = TRANSFORM_TYPE_MAP[c.transform_type]
        axis = INT_TO_AXIS[c.axis]
        channel = (st.driven, transform, axis)
        members = group_constraints_by_channel(st.root).get(channel, [])
        if any(e.jcns_cns_props.preview_on for e in members) and channel not in was_previewed:
            was_previewed.append(channel)

        host = None
        if append and members:
            hp = members[-1].jcns_cns_props
            ok, _why = core.can_append({'additive': hp.additive, 'cone_infos': len(hp.cone_infos),
                                        'n_sources': len(hp.sources), 'property_hash': hp.property_hash}, c)
            host = members[-1] if ok else None
        if host is not None:
            p = host.jcns_cns_props
            # Filling a source field by field would rebuild the driver at every field.
            was_on, p.preview_on = p.preview_on, False
            _fill_source(p.sources.add(), c, st.driver)
            p.preview_on = was_on
            appended += 1
            last = host
        else:
            last = new_constraint_empty(st.root)
            if last is None:
                raise RuntimeError("根节点不属于任何集合。")
            p = last.jcns_cns_props
            p.target_bone, p.transform_type, p.target_axis = st.driven, transform, axis
            p.additive = c.additive
            _fill_source(p.sources[0], c, st.driver)
            created += 1
        _sync_constraint_name(p)

    for channel in was_previewed:
        members = group_constraints_by_channel(st.root).get(channel)
        if members:
            members[-1].jcns_cns_props.preview_on = True
            if not jcns_preview.refresh(members[-1], structural=True):
                _clear_channel(st.arm, members)
    st.arm.update_tag()
    return created, appended, last


def _plan_lines(layout, context, plan, st):
    from .jcns_ui import _wrap_label
    if plan.errors:
        for text in plan.errors:
            _wrap_label(layout, context, text, icon='INFO')
        return
    lines = core.describe(plan, st.driver, st.driven)
    _wrap_label(layout, context, lines[0], icon='CONSTRAINT')
    for line in lines[1:]:
        _wrap_label(layout, context, line, icon='BLANK1')
    for text in plan.warnings:
        _wrap_label(layout, context, text, icon='ERROR', alert=True)


class JCNS_OT_SDKGenerate(_SDKOperator):
    """按记录的键生成 Ranges 约束：驱动骨的读数映射到被驱动骨变化了的通道，静止姿态不在键里时会给出提示"""
    bl_idname = "jcns.sdk_generate"
    bl_label  = "生成约束"

    read_mode: EnumProperty(name="读取方式", items=_READ_ITEMS, default='AUTO',
                            description="从驱动骨读什么。自动时按各键之间的变化选取")
    source_axis: EnumProperty(name="读取轴", items=_AXIS_ITEMS, default='AUTO',
                              description="读驱动骨的哪个局部轴。自动时取变化最大的轴")
    append_sources: BoolProperty(
        name="追加为已有约束的新源（求和）", default=True,
        description="被驱动的通道上已有约束时，把驱动骨作为新的源加到最后一条里，各源输出相加；"
                    "不能追加的（叠加设置不同、带 ConeDriver 输入、源已满）仍新建。关闭则一律新建，"
                    "同通道只有最后一条生效")

    @classmethod
    def poll(cls, context):
        from .jcns_operators import _caps_for
        st = _state(context)[0]
        return st is not None and _caps_for(st.rp, 'Ranges').can_add

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=420)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "read_mode")
        layout.prop(self, "source_axis")
        layout.prop(self, "append_sources")
        st = _state(context)[0]
        if st is not None:
            _plan_lines(layout.box(), context, make_plan(st, self.read_mode, self.source_axis), st)

    def execute(self, context):
        st = self.state(context)
        if st is None:
            return {'CANCELLED'}
        plan = make_plan(st, self.read_mode, self.source_axis)
        if not plan.ok:
            self.report({'ERROR'}, plan.errors[0])
            return {'CANCELLED'}
        try:
            created, appended, last = land(context, st, plan, self.append_sources)
        except RuntimeError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        context.view_layer.objects.active = last
        last.select_set(True)
        msg = "新建 %d 条，追加 %d 个源。" % (created, appended)
        if plan.warnings:
            self.report({'WARNING'}, msg + "有 %d 条提示，见「摆姿势建约束」面板。" % len(plan.warnings))
        else:
            self.report({'INFO'}, msg)
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------

class JCNS_UL_SDKKeys(UIList):
    """记录的键，每行显示驱动骨相对静止姿态的主要变化。"""
    bl_idname = "JCNS_UL_sdk_keys"

    def draw_item(self, context, layout, data, item, icon, active_data, active_prop, index):
        text = ""
        st = _state(context)[0]
        if st is not None:
            text = core.main_change(_pose_of(item, 'driver'), _rest_of(st.arm, st.driver))
        row = layout.row(align=True)
        row.label(text="键 %d" % (index + 1), icon='KEYFRAME')
        row.label(text=text)


_plan_failed = False


def _panel_plan(st):
    """make_plan for a redraw: a failure is reported once on the console and shown as an error."""
    global _plan_failed
    try:
        return make_plan(st)
    except Exception as exc:
        if not _plan_failed:
            _plan_failed = True
            print("[JCNS] pose-driven plan failed: %r" % exc)
        plan = core.Plan()
        plan.errors.append("读取姿态时出错，详情请查看系统控制台。")
        return plan


class JCNS_PT_SDK(Panel):
    bl_label    = "摆姿势建约束"
    bl_idname   = "JCNS_PT_sdk"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = 'JCNS 编辑器'
    bl_order       = 4

    @classmethod
    def poll(cls, context):
        from .jcns_ui import _resolve_root
        return _resolve_root(context)[0] is not None

    def draw(self, context):
        from .jcns_operators import _caps_for
        from .jcns_ui import _wrap_label, _resolve_root
        root, rp = _resolve_root(context)
        layout = self.layout
        caps = _caps_for(rp, 'Ranges')
        if not caps.can_add:
            _wrap_label(layout, context, caps.reason('add') or "这个文件不能新增约束。", icon='LOCKED')
        body = layout.column()
        body.enabled = caps.can_add

        for label, prop, role in (("驱动骨", 'sdk_driver_bone', 'DRIVER'),
                                  ("被驱动骨", 'sdk_driven_bone', 'DRIVEN')):
            row = body.row(align=True)
            split = row.split(factor=0.3)
            split.label(text=label)
            cell = split.row(align=True)
            cell.prop(rp, prop, text="", icon='BONE_DATA')
            cell.operator("jcns.sdk_pick_bone", text="取选中骨", icon='EYEDROPPER').role = role

        st, why = _state(context)
        if st is None:
            if why:
                _wrap_label(body, context, why, icon='INFO')
            return

        body.label(text="键 · %d 个" % len(rp.sdk_keys), icon='KEYFRAME')
        row = body.row()
        row.template_list("JCNS_UL_sdk_keys", "", rp, "sdk_keys", rp, "sdk_key_index",
                          rows=3 if len(rp.sdk_keys) < 3 else 4, maxrows=4)
        body.operator("jcns.sdk_key_add", icon='KEYFRAME_HLT')
        row = body.row(align=True)
        row.operator("jcns.sdk_key_remove", icon='X')
        row.operator("jcns.sdk_key_goto", icon='POSE_HLT')
        body.operator("jcns.sdk_pose_reset", icon='LOOP_BACK')

        box = body.box()
        _plan_lines(box, context, _panel_plan(st), st)
        body.operator("jcns.sdk_generate", icon='CONSTRAINT')


_classes = [
    JCNS_OT_SDKPickBone,
    JCNS_OT_SDKKeyAdd,
    JCNS_OT_SDKKeyRemove,
    JCNS_OT_SDKKeyGoto,
    JCNS_OT_SDKPoseReset,
    JCNS_OT_SDKGenerate,
    JCNS_UL_SDKKeys,
    JCNS_PT_SDK,
]


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
