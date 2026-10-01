"""
Constraint baking (the Set Driven Key workflow) on the Blender side:
the key list stored on the root, the panel, and the operators that record poses and
turn them into Ranges entries.

modules/jcns_sdk.py decides what a set of keys means and owns every rule about the key list;
this file collects the poses and rest transforms from the target armature the way
jcns_capture does and lands the plan on the file's entries.  Every list edit loads the
stored keys into core.Key objects, applies the pure function and stores the result back, so
the operators cannot drift from the rules the offline tests check.  A key keeps the raw pose
basis of each bone recorded in it, so how it is read is only decided when constraints are
generated.
"""

import bpy
from bpy.types import Operator, Panel, PropertyGroup, UIList
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty, FloatVectorProperty,
                       StringProperty)

from .modules_shim import ensure_path

ensure_path()
import jcns_sdk as core  # noqa: E402  (modules/jcns_sdk.py)
import jcns_source_read as sr  # noqa: E402


class JCNSSDKSnapshot(PropertyGroup):
    """The pose basis of one bone at one recorded key."""
    bone: StringProperty()
    loc: FloatVectorProperty(size=3, default=(0.0, 0.0, 0.0))
    rot: FloatVectorProperty(size=4, default=(1.0, 0.0, 0.0, 0.0))
    scale: FloatVectorProperty(size=3, default=(1.0, 1.0, 1.0))


class JCNSSDKKey(PropertyGroup):
    """One recording.  Its name comes from its place in the list, so none is stored."""
    snapshots: CollectionProperty(type=JCNSSDKSnapshot)


class JCNSSDKBone(PropertyGroup):
    """A driven bone; `name` is the bone's name."""
    name: StringProperty()


def search_bones(self, context, edit_text):
    """Bone names of the target armature for the driver field; `self` is the root's properties."""
    arm = self.target_armature
    if arm is None or arm.type != 'ARMATURE':
        return []
    needle = edit_text.lower()
    return sorted(b.name for b in arm.data.bones if needle in b.name.lower())


# ---------------------------------------------------------------------------
# Reading and writing poses and keys
# ---------------------------------------------------------------------------

def snapshot(pose_bone):
    """(location, quaternion, scale) of a pose bone's basis, whatever its rotation mode."""
    loc, rot, scale = pose_bone.matrix_basis.decompose()
    return tuple(loc), tuple(rot), tuple(scale)


def apply_pose(pose_bone, loc, rot, scale):
    from mathutils import Matrix, Quaternion, Vector
    pose_bone.matrix_basis = Matrix.LocRotScale(Vector(loc), Quaternion(rot), Vector(scale))


def pose_of(snap):
    return core.Pose(tuple(snap.loc), tuple(snap.rot), tuple(snap.scale))


def load_keys(rp):
    return [core.Key({s.bone: pose_of(s) for s in k.snapshots}) for k in rp.sdk_keys]


def store_keys(rp, keys, index=None):
    """Replace the stored keys with `keys`; `index` becomes the selected key (clamped)."""
    if index is None:
        index = rp.sdk_key_index
    rp.sdk_keys.clear()
    for key in keys:
        item = rp.sdk_keys.add()
        for bone, pose in key.poses.items():
            s = item.snapshots.add()
            s.bone, s.loc, s.rot, s.scale = bone, pose.loc, pose.quat, pose.scale
    rp.sdk_key_index = max(0, min(index, len(keys) - 1))


def ensure_keys(rp):
    """The list always holds the start and the end key."""
    keys = load_keys(rp)
    if core.ensure_ends(keys):
        store_keys(rp, keys)


def key_index(rp):
    return max(0, min(rp.sdk_key_index, len(rp.sdk_keys) - 1))


def driven_names(rp):
    return [b.name for b in rp.sdk_driven_bones]


def _rest_of(arm, name):
    from .jcns_operators import _rest_transform, mesh_rest_scale
    bone = arm.data.bones[name]
    rest, offset = _rest_transform(arm, name)
    parent_scale = mesh_rest_scale(bone.parent) if bone.parent is not None else (1.0, 1.0, 1.0)
    return core.BoneRest(rest, offset, mesh_rest_scale(bone), parent_scale)


def _remove_driven(rp, name):
    """Take a bone off the driven list; its snapshots go too unless it is the driver."""
    for i, b in enumerate(rp.sdk_driven_bones):
        if b.name == name:
            rp.sdk_driven_bones.remove(i)
            break
    rp.sdk_driven_index = max(0, min(rp.sdk_driven_index, len(rp.sdk_driven_bones) - 1))
    if name != rp.sdk_driver_bone:
        keys = load_keys(rp)
        core.forget_bone(keys, name)
        store_keys(rp, keys)


# ---------------------------------------------------------------------------
# State shared by the panel and the operators
# ---------------------------------------------------------------------------

class _State:
    def __init__(self, root, rp, arm, driver, driven, cm_ok, cm_reason):
        self.root, self.rp, self.arm, self.driver, self.driven = root, rp, arm, driver, driven
        self.cm_ok, self.cm_reason = cm_ok, cm_reason

    def keys(self):
        return load_keys(self.rp)

    def names(self):
        """The driver, then the driven bones."""
        return [self.driver] + self.driven

    def rests(self):
        return {n: _rest_of(self.arm, n) for n in self.names()}


def _state(context):
    """(_State, '') when keys can be recorded and read, else (None, why not)."""
    from . import file_state, get_export_root
    from .modules_shim import get_kinds
    root, rp = get_export_root(context)
    if rp is None:
        return None, ""
    arm = rp.target_armature
    if arm is None or arm.type != 'ARMATURE':
        return None, "先设置目标骨架。"
    driver, driven = rp.sdk_driver_bone, driven_names(rp)
    if not driver:
        return None, "先设置驱动。"
    if driver not in arm.pose.bones:
        return None, "目标骨架里没有驱动「%s」。" % driver
    if not driven:
        return None, "先添加被驱动。"
    for name in driven:
        if name not in arm.pose.bones:
            return None, "目标骨架里没有被驱动「%s」。" % name
    if driver in driven:
        return None, "「%s」既是驱动又是被驱动，先把它移出被驱动。" % driver
    cm_ok, cm_reason = get_kinds().complex_mapping_editable(file_state(rp))
    return _State(root, rp, arm, driver, driven, cm_ok, cm_reason), ""


def _previewed(st):
    """Names among the bones involved that a preview is driving, so their recorded poses would
    be the preview's rather than the user's."""
    names = set(st.names())
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
_TANGENT_ITEMS = [('LINEAR', "线性", "相邻关键帧之间走直线"),
                  ('SMOOTH', "平滑", "每个关键帧处的切线随前后趋势变化，曲线不会冲出相邻关键帧的取值范围")]


def make_plan(st, read_mode='AUTO', source_axis='AUTO', tangent='LINEAR'):
    """The plan for the recorded keys."""
    return core.plan_keys(
        st.keys(), st.driver, st.driven, st.rests(),
        read_mode=None if read_mode == 'AUTO' else read_mode,
        axis=None if source_axis == 'AUTO' else 'XYZ'.index(source_axis),
        tangent=tangent, complex_ok=st.cm_ok, complex_reason=st.cm_reason)


# ---------------------------------------------------------------------------
# Operators: bones
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


class _RootOperator(Operator):
    """Operators that edit the key list and need only the file."""
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        from . import get_export_root
        return get_export_root(context)[1] is not None


class JCNS_OT_SDKPickBone(Operator):
    """取姿态模式下选中的骨骼：驱动栏取活动骨并把其余选中骨加入被驱动，被驱动栏添加所有选中骨"""
    bl_idname = "jcns.sdk_pick_bone"
    bl_label  = "取选中骨"
    bl_options = {'REGISTER', 'UNDO'}

    role: EnumProperty(name="骨骼栏", items=[('DRIVER', "驱动", ""), ('DRIVEN', "被驱动", "")])

    @classmethod
    def poll(cls, context):
        from . import get_export_root
        root, rp = get_export_root(context)
        return rp is not None and rp.target_armature is not None

    def execute(self, context):
        from . import get_export_root
        root, rp = get_export_root(context)
        arm = rp.target_armature
        active = context.active_pose_bone
        if active is not None and active.id_data != arm:
            self.report({'ERROR'}, "活动骨不在目标骨架「%s」里。" % arm.name)
            return {'CANCELLED'}
        picked = [pb for pb in (context.selected_pose_bones or []) if pb.id_data == arm]
        if active is not None and active.name not in [pb.name for pb in picked]:
            picked.append(active)
        if not picked:
            self.report({'ERROR'}, "先进入姿态模式，选中骨骼。")
            return {'CANCELLED'}
        if self.role == 'DRIVER':
            if active is None:
                self.report({'ERROR'}, "先把驱动设为活动骨。")
                return {'CANCELLED'}
            rp.sdk_driver_bone = active.name
            if active.name in driven_names(rp):
                _remove_driven(rp, active.name)
        added = 0
        for pb in picked:
            if pb.name != rp.sdk_driver_bone and pb.name not in driven_names(rp):
                rp.sdk_driven_bones.add().name = pb.name
                rp.sdk_driven_index = len(rp.sdk_driven_bones) - 1
                added += 1
        if self.role == 'DRIVEN' and not added:
            self.report({'WARNING'}, "选中的骨骼已经在被驱动列表里，或就是驱动。")
            return {'CANCELLED'}
        return {'FINISHED'}


_bone_items = []


def _driven_candidates(self, context):
    """Bones of the target armature that are not the driver or already driven."""
    from . import get_export_root
    global _bone_items
    root, rp = get_export_root(context)
    arm = rp.target_armature if rp is not None else None
    taken = set(driven_names(rp)) | {rp.sdk_driver_bone} if rp is not None else set()
    names = sorted(b.name for b in arm.data.bones if b.name not in taken) if arm is not None else []
    _bone_items = [(n, n, "") for n in names] or [('', "没有可添加的骨骼", "")]
    return _bone_items


class JCNS_OT_SDKDrivenAdd(Operator):
    """从目标骨架的骨骼里选一根，加入被驱动列表"""
    bl_idname = "jcns.sdk_driven_add"
    bl_label  = "添加被驱动"
    bl_options = {'REGISTER', 'UNDO'}
    bl_property = "bone"

    bone: EnumProperty(name="骨骼", items=_driven_candidates)

    @classmethod
    def poll(cls, context):
        from . import get_export_root
        root, rp = get_export_root(context)
        return rp is not None and rp.target_armature is not None

    def invoke(self, context, event):
        context.window_manager.invoke_search_popup(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        from . import get_export_root
        root, rp = get_export_root(context)
        if not self.bone:
            return {'CANCELLED'}
        rp.sdk_driven_bones.add().name = self.bone
        rp.sdk_driven_index = len(rp.sdk_driven_bones) - 1
        return {'FINISHED'}


class JCNS_OT_SDKDrivenRemove(Operator):
    """把列表里选中的骨骼移出被驱动，各键里它的记录一并删除"""
    bl_idname = "jcns.sdk_driven_remove"
    bl_label  = "移出被驱动"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        from . import get_export_root
        root, rp = get_export_root(context)
        return rp is not None and len(rp.sdk_driven_bones) > 0

    def execute(self, context):
        from . import get_export_root
        root, rp = get_export_root(context)
        i = max(0, min(rp.sdk_driven_index, len(rp.sdk_driven_bones) - 1))
        _remove_driven(rp, rp.sdk_driven_bones[i].name)
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Operators: keys
# ---------------------------------------------------------------------------

class JCNS_OT_SDKKeysInit(_RootOperator):
    """建立键Start 和键End"""
    bl_idname = "jcns.sdk_keys_init"
    bl_label  = "建立键Start 和键End"

    def execute(self, context):
        from . import get_export_root
        ensure_keys(get_export_root(context)[1])
        return {'FINISHED'}


class JCNS_OT_SDKKeyAdd(_RootOperator):
    """在键End 前面插入一个新键，内容复制自键End"""
    bl_idname = "jcns.sdk_key_add"
    bl_label  = "插入键"

    def execute(self, context):
        from . import get_export_root
        rp = get_export_root(context)[1]
        keys = load_keys(rp)
        store_keys(rp, keys, core.insert_key(keys))
        return {'FINISHED'}


class JCNS_OT_SDKKeyRemove(_RootOperator):
    """删除选中的键，键Start 和键End 除外"""
    bl_idname = "jcns.sdk_key_remove"
    bl_label  = "删除键"

    @classmethod
    def poll(cls, context):
        from . import get_export_root
        rp = get_export_root(context)[1]
        return rp is not None and core.can_delete(key_index(rp), len(rp.sdk_keys))[0]

    def execute(self, context):
        from . import get_export_root
        rp = get_export_root(context)[1]
        keys = load_keys(rp)
        store_keys(rp, keys, core.delete_key(keys, key_index(rp)))
        return {'FINISHED'}


class _KeyMove(_RootOperator):
    STEP = 0

    @classmethod
    def poll(cls, context):
        from . import get_export_root
        rp = get_export_root(context)[1]
        return rp is not None and core.move_target(key_index(rp), len(rp.sdk_keys), cls.STEP) is not None

    def execute(self, context):
        from . import get_export_root
        rp = get_export_root(context)[1]
        keys = load_keys(rp)
        new = core.move_key(keys, key_index(rp), self.STEP)
        if new is None:
            return {'CANCELLED'}
        store_keys(rp, keys, new)
        return {'FINISHED'}


class JCNS_OT_SDKKeyUp(_KeyMove):
    """把选中的中间键上移一位"""
    bl_idname = "jcns.sdk_key_up"
    bl_label  = "上移键"
    STEP = -1


class JCNS_OT_SDKKeyDown(_KeyMove):
    """把选中的中间键下移一位"""
    bl_idname = "jcns.sdk_key_down"
    bl_label  = "下移键"
    STEP = 1


class JCNS_OT_SDKKeyRecord(_SDKOperator):
    """把骨骼现在的姿态记进选中的键。不指定骨骼时记录所有涉及的骨骼"""
    bl_idname = "jcns.sdk_key_record"
    bl_label  = "记录"

    bone: StringProperty(name="骨骼", default="", options={'SKIP_SAVE'},
                        description="只记录这一根骨骼。留空则记录全部")

    @classmethod
    def description(cls, context, properties):
        return ("记录「%s」现在的姿态" % properties.bone if properties.bone
                else "把所有涉及的骨骼现在的姿态记进选中的键")

    def execute(self, context):
        st = self.state(context)
        if st is None:
            return {'CANCELLED'}
        if self.bone and self.bone not in st.names():
            self.report({'ERROR'}, "「%s」不是驱动，也不在被驱动列表里。" % self.bone)
            return {'CANCELLED'}
        ensure_keys(st.rp)
        keys, i = st.keys(), key_index(st.rp)
        for name in ([self.bone] if self.bone else st.names()):
            loc, rot, scale = snapshot(st.arm.pose.bones[name])
            core.record(keys, i, name, core.Pose(loc, rot, scale))
        store_keys(st.rp, keys, i)
        return {'FINISHED'}


class JCNS_OT_SDKKeyGoto(_SDKOperator):
    """把选中的键里已记录的骨骼摆回记录时的姿态"""
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
        key = st.keys()[key_index(st.rp)]
        todo = [n for n in st.names() if n in key.poses]
        if not todo:
            self.report({'ERROR'}, "这个键里还没有记录任何骨骼。")
            return {'CANCELLED'}
        for name in todo:
            p = key.poses[name]
            apply_pose(st.arm.pose.bones[name], p.loc, p.quat, p.scale)
        return {'FINISHED'}


class JCNS_OT_SDKPoseReset(_SDKOperator):
    """把驱动和所有被驱动的姿态清零，回到静止姿态"""
    bl_idname = "jcns.sdk_pose_reset"
    bl_label  = "回到静止姿态"

    def execute(self, context):
        st = self.state(context)
        if st is None:
            return {'CANCELLED'}
        for name in st.names():
            apply_pose(st.arm.pose.bones[name], (0.0, 0.0, 0.0), (1.0, 0.0, 0.0, 0.0), (1.0, 1.0, 1.0))
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Landing a plan on the file
# ---------------------------------------------------------------------------

def _fill_source(sp, c, driver):
    from . import INT_TO_AXIS, jcns_cm
    sp.source_bone = driver
    sp.source_axis = INT_TO_AXIS[c.source_axis]
    sp.read_mode = sr.read_mode_id(c.read_mode)
    sp.euler_order = sr.EULER_ORDER_NAMES[c.euler_order]
    sp.three_point = c.three_point
    for field, v in zip(('from_start', 'from_kink', 'from_end'), c.from_anchors):
        setattr(sp, field, round(v, 5) + 0.0)
    for field, v in zip(('to_start', 'to_kink', 'to_end'), c.to_anchors):
        setattr(sp, field, round(v, 5) + 0.0)
    if c.complex:
        # As for any keyframed source: the curve holds the mapping, the anchors stay zero,
        # the record count and flag are what an imported curve carries.
        sp.cm_cache.clear()
        jcns_cm.set_keys(sp, list(c.keys))
        sp.complex_mapping_info_count = len(c.keys)
        sp.complex_mapping_flag = 1


def land(context, st, plan, append, touched=None):
    """Write the plan's constraints into the file.  -> (new entries, appended sources, last entry).

    A constraint whose channel already has an entry that can take another source
    (core.can_append) adds a source to the file's last entry on the channel when `append`;
    the others become new entries at the end of the file.  `touched`, when given, collects
    the (bone, transform, axis) of every channel that got a new entry or source.
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
        channel = (c.driven, transform, axis)
        if touched is not None and channel not in touched:
            touched.append(channel)
        members = group_constraints_by_channel(st.root).get(channel, [])
        if any(e.jcns_cns_props.preview_on for e in members) and channel not in was_previewed:
            was_previewed.append(channel)

        host = None
        if append and members:
            hp = members[-1].jcns_cns_props
            ok, _why = core.can_append({'additive': hp.additive, 'cone_infos': len(hp.cone_infos),
                                        'n_sources': len(hp.sources), 'target_property': hp.target_property,
                                        'property_hash': hp.property_hash}, c, complex_ok=st.cm_ok)
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
            p.target_bone, p.transform_type, p.target_axis = c.driven, transform, axis
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


def preview_channels(st, channels):
    """Apply the Ranges preview to the channels `land` touched.  -> '' or one sentence for the report.

    A missing armature or a channel that cannot be previewed is not an error: generating
    is the point, the preview is a convenience.
    """
    from . import group_constraints_by_channel, jcns_preview
    arm = st.rp.target_armature
    if arm is None:
        return "没有目标骨架，预览未应用。"
    backend = jcns_preview.backend_of('Ranges')
    groups = group_constraints_by_channel(st.root)
    failed = 0
    for channel in channels:
        unit = groups.get(channel)
        if not unit:
            continue
        try:
            ok, msg = backend.apply(st.rp, unit)
        except Exception as exc:
            ok, msg = False, repr(exc)
        if not ok:
            failed += 1
            print("[JCNS BAKE] preview skipped: %s" % msg)
    arm.update_tag()
    return "%d 个通道的预览未应用，详见系统控制台。" % failed if failed else ""


def _plan_lines(layout, context, plan, st):
    """One row per constraint, or the reasons there is none; then the warnings."""
    from .jcns_ui import _wrap_label
    for kind, text in core.describe_rows(plan, st.driver):
        if kind == 'error':
            _wrap_label(layout, context, text, icon='ERROR', alert=True)
        elif kind == 'line':
            _wrap_label(layout, context, text, icon='CONSTRAINT')
    if plan.errors:
        return
    for text in plan.warnings:
        _wrap_label(layout, context, text, icon='ERROR', alert=True)


class JCNS_OT_SDKGenerate(_SDKOperator):
    """按记录的键生成约束：驱动的读数映射到各被驱动变化了的通道"""
    bl_idname = "jcns.sdk_generate"
    bl_label  = "生成约束"

    read_mode: EnumProperty(name="读取方式", items=_READ_ITEMS, default='AUTO',
                            description="从驱动读什么。自动时按各键之间的变化选取")
    source_axis: EnumProperty(name="读取轴", items=_AXIS_ITEMS, default='AUTO',
                              description="读驱动的哪个局部轴。自动时取变化最大的轴")
    tangent: EnumProperty(name="曲线切线", items=_TANGENT_ITEMS, default='LINEAR',
                          description="4 个及以上的键生成曲线时，关键点处的切线怎么取；少于 4 个键时不起作用")
    preview_after: BoolProperty(
        name="生成后预览", default=True,
        description="在骨架上预览生成的约束；没有目标骨架或应用失败时只在报告里提示")
    append_sources: BoolProperty(
        name="追加到已有约束（求和）", default=True,
        description="通道上已有约束时，作为新的驱动加到最后一条里，输出相加；不能追加的仍新建，关闭则一律新建")

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
        st = _state(context)[0]
        if st is not None and sum(1 for k in st.keys() if st.driver in k.poses) > core.MAX_KEYS:
            layout.prop(self, "tangent")
        layout.prop(self, "append_sources")
        layout.prop(self, "preview_after")
        if st is not None:
            _plan_lines(layout.box(), context, make_plan(st, self.read_mode, self.source_axis, self.tangent), st)

    def execute(self, context):
        st = self.state(context)
        if st is None:
            return {'CANCELLED'}
        plan = make_plan(st, self.read_mode, self.source_axis, self.tangent)
        if not plan.ok:
            self.report({'ERROR'}, plan.errors[0])
            return {'CANCELLED'}
        touched = []
        try:
            created, appended, last = land(context, st, plan, self.append_sources, touched)
        except RuntimeError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        context.view_layer.objects.active = last
        last.select_set(True)
        msg = "新建 %d 条，追加 %d 个驱动。" % (created, appended)
        if self.preview_after:
            note = preview_channels(st, touched)
            if note:
                msg += note
        if plan.warnings:
            self.report({'WARNING'}, msg + "有 %d 条提示，见「烘焙约束」面板。" % len(plan.warnings))
        else:
            self.report({'INFO'}, msg)
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------

class JCNS_UL_SDKDriven(UIList):
    """被驱动列表。"""
    bl_idname = "JCNS_UL_sdk_driven"

    def draw_item(self, context, layout, data, item, icon, active_data, active_prop, index):
        layout.label(text=item.name, icon='BONE_DATA')


class JCNS_UL_SDKKeys(UIList):
    """记录的键，每行显示键名和驱动在这个键里的读数。"""
    bl_idname = "JCNS_UL_sdk_keys"

    def draw_item(self, context, layout, data, item, icon, active_data, active_prop, index):
        text = "未记录"
        st = _state(context)[0]
        if st is not None:
            snap = next((s for s in item.snapshots if s.bone == st.driver), None)
            if snap is not None:
                text = core.main_change(pose_of(snap), _rest_of(st.arm, st.driver))
        row = layout.row(align=True)
        row.label(text="%s　%s" % (core.key_name(index, len(data.sdk_keys)), text), icon='KEYFRAME')


_plan_failed = False


def _panel_plan(st):
    """make_plan for a redraw: a failure is reported once on the console and shown as an error."""
    global _plan_failed
    try:
        return make_plan(st)
    except Exception as exc:
        if not _plan_failed:
            _plan_failed = True
            print("[JCNS] bake plan failed: %r" % exc)
        plan = core.Plan()
        plan.errors.append("读取姿态时出错，详情请查看系统控制台。")
        return plan


class JCNS_PT_SDK(Panel):
    bl_label    = "烘焙约束"
    bl_idname   = "JCNS_PT_sdk"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = 'JCNS 编辑器'
    bl_order    = 1

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
            layout.label(text=caps.reason('add') or "这个文件不能新增约束", icon='LOCKED')
        body = layout.column()
        body.enabled = caps.can_add

        row = body.row(align=True)
        split = row.split(factor=0.3)
        split.label(text="驱动")
        cell = split.row(align=True)
        cell.prop(rp, 'sdk_driver_bone', text="", icon='BONE_DATA')
        cell.operator("jcns.sdk_pick_bone", text="", icon='EYEDROPPER').role = 'DRIVER'

        body.label(text="被驱动", icon='BONE_DATA')
        row = body.row()
        row.template_list("JCNS_UL_sdk_driven", "", rp, "sdk_driven_bones", rp, "sdk_driven_index",
                          rows=2, maxrows=4)
        col = row.column(align=True)
        col.operator("jcns.sdk_driven_add", text="", icon='ADD')
        col.operator("jcns.sdk_pick_bone", text="", icon='EYEDROPPER').role = 'DRIVEN'
        col.operator("jcns.sdk_driven_remove", text="", icon='REMOVE')

        st, why = _state(context)
        if st is None:
            if why:
                _wrap_label(body, context, why, icon='INFO')
            return

        if len(rp.sdk_keys) < 2:
            body.operator("jcns.sdk_keys_init", icon='KEYFRAME')
            return
        body.label(text="键", icon='KEYFRAME')
        row = body.row()
        row.template_list("JCNS_UL_sdk_keys", "", rp, "sdk_keys", rp, "sdk_key_index",
                          rows=4, maxrows=6)
        col = row.column(align=True)
        col.operator("jcns.sdk_key_add", text="", icon='ADD')
        col.operator("jcns.sdk_key_remove", text="", icon='REMOVE')
        col.separator()
        col.operator("jcns.sdk_key_up", text="", icon='TRIA_UP')
        col.operator("jcns.sdk_key_down", text="", icon='TRIA_DOWN')

        hit = _previewed(st)
        if hit:
            row = body.row(align=True)
            sub = row.row()
            sub.alert = True
            sub.label(text="预览正在驱动 %d 根骨" % len(hit), icon='ERROR')
            row.operator("jcns.preview_clear", text="清除预览").scope = 'FILE'

        index = key_index(rp)
        box = body.box()
        box.label(text="%s 里的记录" % core.key_name(index, len(rp.sdk_keys)), icon='KEYFRAME')
        have = {s.bone for s in rp.sdk_keys[index].snapshots}
        for name in st.names():
            row = box.row(align=True)
            row.label(text=name, icon='BONE_DATA')
            row.label(text="", icon='CHECKMARK' if name in have else 'RADIOBUT_OFF')
            row.operator("jcns.sdk_key_record", text="", icon='REC').bone = name
        row = body.row(align=True)
        row.operator("jcns.sdk_key_record", text="全部记录", icon='KEYFRAME_HLT').bone = ""
        row.operator("jcns.sdk_key_goto", icon='POSE_HLT')
        body.operator("jcns.sdk_pose_reset", icon='LOOP_BACK')

        box = body.box()
        _plan_lines(box, context, _panel_plan(st), st)
        body.operator("jcns.sdk_generate", icon='CONSTRAINT')


_classes = [
    JCNS_OT_SDKPickBone,
    JCNS_OT_SDKDrivenAdd,
    JCNS_OT_SDKDrivenRemove,
    JCNS_OT_SDKKeysInit,
    JCNS_OT_SDKKeyAdd,
    JCNS_OT_SDKKeyRemove,
    JCNS_OT_SDKKeyUp,
    JCNS_OT_SDKKeyDown,
    JCNS_OT_SDKKeyRecord,
    JCNS_OT_SDKKeyGoto,
    JCNS_OT_SDKPoseReset,
    JCNS_OT_SDKGenerate,
    JCNS_UL_SDKDriven,
    JCNS_UL_SDKKeys,
    JCNS_PT_SDK,
]


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
