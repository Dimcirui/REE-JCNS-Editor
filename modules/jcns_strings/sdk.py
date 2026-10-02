STRINGS = {
    # ---- jcns_sdk_ops.py: state errors ----
    "sdk.state.no_armature": {
        "ZH": "先设置目标骨架。",
        "EN": "Set the target armature first.",
    },
    "sdk.state.no_driver": {
        "ZH": "先设置驱动。",
        "EN": "Set the driver first.",
    },
    "sdk.state.driver_missing": {
        "ZH": "目标骨架里没有驱动「%s」。",
        "EN": "The target armature has no driver bone \"%s\".",
    },
    "sdk.state.no_driven": {
        "ZH": "先添加被驱动。",
        "EN": "Add a driven bone first.",
    },
    "sdk.state.driven_missing": {
        "ZH": "目标骨架里没有被驱动「%s」。",
        "EN": "The target armature has no driven bone \"%s\".",
    },
    "sdk.state.driver_is_driven": {
        "ZH": "「%s」既是驱动又是被驱动，先把它移出被驱动。",
        "EN": "\"%s\" is both the driver and a driven bone; remove it from the driven list first.",
    },
    "sdk.state.no_root": {
        "ZH": "找不到 JCNS 根节点。",
        "EN": "JCNS root node not found.",
    },

    # ---- jcns_sdk_ops.py: enum items ----
    "sdk.item.auto": {
        "ZH": "自动",
        "EN": "Auto",
    },
    "sdk.item.read_auto_desc": {
        "ZH": "按各键之间变化最大的量选取：旋转，其次位置，其次缩放",
        "EN": "Pick the quantity that changes most between keys: rotation, then position, then scale",
    },
    "sdk.item.axis_auto_desc": {
        "ZH": "取变化最大的轴",
        "EN": "Use the axis that changes most",
    },
    "sdk.item.linear": {
        "ZH": "线性",
        "EN": "Linear",
    },
    "sdk.item.linear_desc": {
        "ZH": "相邻关键帧之间走直线",
        "EN": "Straight line between adjacent keyframes",
    },
    "sdk.item.smooth": {
        "ZH": "平滑",
        "EN": "Smooth",
    },
    "sdk.item.smooth_desc": {
        "ZH": "每个关键帧处的切线随前后趋势变化，曲线不会冲出相邻关键帧的取值范围",
        "EN": "The tangent at each keyframe follows the trend on both sides; the curve never leaves the value range of adjacent keyframes",
    },
    "sdk.item.no_bones": {
        "ZH": "没有可添加的骨骼",
        "EN": "No bones to add",
    },

    # ---- jcns_sdk_ops.py: operators ----
    "sdk.pick_bone.label": {
        "ZH": "取选中骨",
        "EN": "Pick Selected Bones",
    },
    "sdk.pick_bone.desc": {
        "ZH": "取姿态模式下选中的骨骼：驱动栏取活动骨并把其余选中骨加入被驱动，被驱动栏添加所有选中骨",
        "EN": "Take the bones selected in Pose Mode: the driver field takes the active bone and adds the other selected bones as driven, the driven list adds all selected bones",
    },
    "sdk.pick_bone.role": {
        "ZH": "骨骼栏",
        "EN": "Bone field",
    },
    "sdk.pick_bone.active_not_in_armature": {
        "ZH": "活动骨不在目标骨架「%s」里。",
        "EN": "The active bone is not in the target armature \"%s\".",
    },
    "sdk.pick_bone.none_selected": {
        "ZH": "先进入姿态模式，选中骨骼。",
        "EN": "Enter Pose Mode and select bones first.",
    },
    "sdk.pick_bone.no_active": {
        "ZH": "先把驱动设为活动骨。",
        "EN": "Make the driver the active bone first.",
    },
    "sdk.pick_bone.already_listed": {
        "ZH": "选中的骨骼已经在被驱动列表里，或就是驱动。",
        "EN": "The selected bones are already in the driven list, or are the driver.",
    },
    "sdk.bone": {
        "ZH": "骨骼",
        "EN": "Bone",
    },
    "sdk.driven_add.label": {
        "ZH": "添加被驱动",
        "EN": "Add Driven",
    },
    "sdk.driven_add.desc": {
        "ZH": "从目标骨架的骨骼里选一根，加入被驱动列表",
        "EN": "Pick a bone of the target armature and add it to the driven list",
    },
    "sdk.driven_remove.label": {
        "ZH": "移出被驱动",
        "EN": "Remove Driven",
    },
    "sdk.driven_remove.desc": {
        "ZH": "把列表里选中的骨骼移出被驱动，各键里它的记录一并删除",
        "EN": "Remove the selected bone from the driven list; its records in every key are deleted too",
    },
    "sdk.keys_init.label": {
        "ZH": "建立键Start 和键End",
        "EN": "Create Key Start and Key End",
    },
    "sdk.keys_init.desc": {
        "ZH": "建立键Start 和键End",
        "EN": "Create Key Start and Key End",
    },
    "sdk.key_add.label": {
        "ZH": "插入键",
        "EN": "Insert Key",
    },
    "sdk.key_add.desc": {
        "ZH": "在键End 前面插入一个新键，内容复制自键End",
        "EN": "Insert a new key before Key End, copying the content of Key End",
    },
    "sdk.key_remove.label": {
        "ZH": "删除键",
        "EN": "Delete Key",
    },
    "sdk.key_remove.desc": {
        "ZH": "删除选中的键，键Start 和键End 除外",
        "EN": "Delete the selected key; Key Start and Key End cannot be deleted",
    },
    "sdk.key_up.label": {
        "ZH": "上移键",
        "EN": "Move Key Up",
    },
    "sdk.key_up.desc": {
        "ZH": "把选中的中间键上移一位",
        "EN": "Move the selected middle key up by one",
    },
    "sdk.key_down.label": {
        "ZH": "下移键",
        "EN": "Move Key Down",
    },
    "sdk.key_down.desc": {
        "ZH": "把选中的中间键下移一位",
        "EN": "Move the selected middle key down by one",
    },
    "sdk.key_record.label": {
        "ZH": "记录",
        "EN": "Record",
    },
    "sdk.key_record.desc": {
        "ZH": "把骨骼现在的姿态记进选中的键。不指定骨骼时记录所有涉及的骨骼",
        "EN": "Record the bone's current pose into the selected key; with no bone given, records every bone involved",
    },
    "sdk.key_record.bone_desc": {
        "ZH": "只记录这一根骨骼。留空则记录全部",
        "EN": "Record only this bone; leave empty to record all",
    },
    "sdk.key_record.desc_bone": {
        "ZH": "记录「%s」现在的姿态",
        "EN": "Record the current pose of \"%s\"",
    },
    "sdk.key_record.desc_all": {
        "ZH": "把所有涉及的骨骼现在的姿态记进选中的键",
        "EN": "Record the current pose of every bone involved into the selected key",
    },
    "sdk.key_record.not_involved": {
        "ZH": "「%s」不是驱动，也不在被驱动列表里。",
        "EN": "\"%s\" is not the driver and is not in the driven list.",
    },
    "sdk.key_goto.label": {
        "ZH": "跳到此键",
        "EN": "Go to This Key",
    },
    "sdk.key_goto.desc": {
        "ZH": "把选中的键里已记录的骨骼摆回记录时的姿态",
        "EN": "Put the bones recorded in the selected key back to their recorded pose",
    },
    "sdk.key_goto.empty": {
        "ZH": "这个键里还没有记录任何骨骼。",
        "EN": "No bone is recorded in this key yet.",
    },
    "sdk.pose_reset.label": {
        "ZH": "回到静止姿态",
        "EN": "Back to Rest Pose",
    },
    "sdk.pose_reset.desc": {
        "ZH": "把驱动和所有被驱动的姿态清零，回到静止姿态",
        "EN": "Clear the pose of the driver and all driven bones, back to the rest pose",
    },
    "sdk.land.no_collection": {
        "ZH": "根节点不属于任何集合。",
        "EN": "The root node does not belong to any collection.",
    },
    "sdk.preview.no_armature": {
        "ZH": "没有目标骨架，预览未应用。",
        "EN": " No target armature; the preview was not applied.",
    },
    "sdk.preview.failed": {
        "ZH": "%d 个通道的预览未应用，详见系统控制台。",
        "EN": " The preview was not applied to %d channels; see the system console.",
    },
    "sdk.generate.label": {
        "ZH": "生成约束",
        "EN": "Generate Constraints",
    },
    "sdk.generate.desc": {
        "ZH": "按记录的键生成约束：驱动的读数映射到各被驱动变化了的通道",
        "EN": "Generate constraints from the recorded keys: the driver's reading is mapped to every channel of the driven bones that changed",
    },
    "sdk.generate.read_mode": {
        "ZH": "读取方式",
        "EN": "Read mode",
    },
    "sdk.generate.read_mode_desc": {
        "ZH": "从驱动读什么。自动时按各键之间的变化选取",
        "EN": "What to read from the driver; Auto picks by the change between keys",
    },
    "sdk.generate.source_axis": {
        "ZH": "读取轴",
        "EN": "Read axis",
    },
    "sdk.generate.source_axis_desc": {
        "ZH": "读驱动的哪个局部轴。自动时取变化最大的轴",
        "EN": "Which local axis of the driver to read; Auto uses the axis that changes most",
    },
    "sdk.generate.tangent": {
        "ZH": "曲线切线",
        "EN": "Curve tangent",
    },
    "sdk.generate.tangent_desc": {
        "ZH": "4 个及以上的键生成曲线时，关键点处的切线怎么取；少于 4 个键时不起作用",
        "EN": "How the tangent at key points is taken when 4 or more keys make a curve; no effect with fewer than 4 keys",
    },
    "sdk.generate.preview_after": {
        "ZH": "生成后预览",
        "EN": "Preview after generating",
    },
    "sdk.generate.preview_after_desc": {
        "ZH": "在骨架上预览生成的约束；没有目标骨架或应用失败时只在报告里提示",
        "EN": "Preview the generated constraints on the armature; without a target armature, or if applying fails, only the report says so",
    },
    "sdk.generate.append_sources": {
        "ZH": "追加到已有约束（求和）",
        "EN": "Append to existing constraints (sum)",
    },
    "sdk.generate.append_sources_desc": {
        "ZH": "通道上已有约束时，作为新的驱动加到最后一条里，输出相加；不能追加的仍新建，关闭则一律新建",
        "EN": "When the channel already has constraints, add it as a new driver to the last one and sum the outputs; constraints that cannot be appended are still created new; off always creates new",
    },
    "sdk.generate.created": {
        "ZH": "新建 %d 条，追加 %d 个驱动。",
        "EN": "Created %d constraint(s), appended %d driver(s).",
    },
    "sdk.generate.warnings_tail": {
        "ZH": "有 %d 条提示，见「烘焙约束」面板。",
        "EN": " %d notes; see the \"Bake Constraints\" panel.",
    },

    # ---- jcns_sdk_ops.py: panel ----
    "sdk.ul.driven_desc": {
        "ZH": "被驱动列表。",
        "EN": "Driven list.",
    },
    "sdk.ul.keys_desc": {
        "ZH": "记录的键，每行显示键名和驱动在这个键里的读数。",
        "EN": "Recorded keys; each row shows the key name and the driver's reading in that key.",
    },
    "sdk.ul.not_recorded": {
        "ZH": "未记录",
        "EN": "Not recorded",
    },
    "sdk.ul.key_row": {
        "ZH": "%s　%s",
        "EN": "%s  %s",
    },
    "sdk.panel.read_failed": {
        "ZH": "读取姿态时出错，详情请查看系统控制台。",
        "EN": "Error while reading poses; see the system console for details.",
    },
    "sdk.panel.label": {
        "ZH": "烘焙约束",
        "EN": "Bake Constraints",
    },
    "sdk.panel.cannot_add": {
        "ZH": "这个文件不能新增约束",
        "EN": "This file cannot add constraints",
    },
    "sdk.panel.driver": {
        "ZH": "驱动",
        "EN": "Driver",
    },
    "sdk.panel.driven": {
        "ZH": "被驱动",
        "EN": "Driven",
    },
    "sdk.panel.keys": {
        "ZH": "键",
        "EN": "Keys",
    },
    "sdk.panel.preview_driving": {
        "ZH": "预览正在驱动 %d 根骨",
        "EN": "Preview is driving %d bones",
    },
    "sdk.panel.clear_preview": {
        "ZH": "清除预览",
        "EN": "Clear Preview",
    },
    "sdk.panel.records_in_key": {
        "ZH": "%s 里的记录",
        "EN": "Records in %s",
    },
    "sdk.panel.record_all": {
        "ZH": "全部记录",
        "EN": "Record All",
    },

    # ---- modules/jcns_sdk.py: names and labels ----
    "sdk.key.start": {
        "ZH": "键Start",
        "EN": "Key Start",
    },
    "sdk.key.end": {
        "ZH": "键End",
        "EN": "Key End",
    },
    "sdk.key.middle": {
        "ZH": "键%d",
        "EN": "Key %d",
    },
    "sdk.list_sep": {
        "ZH": "、",
        "EN": ", ",
    },
    "sdk.label.axis": {
        "ZH": "%s%s",
        "EN": "%s %s",
    },
    "sdk.label.rotation": {
        "ZH": "旋转",
        "EN": "Rotation",
    },
    "sdk.label.translation": {
        "ZH": "平移",
        "EN": "Translation",
    },
    "sdk.label.scale": {
        "ZH": "缩放",
        "EN": "Scale",
    },
    "sdk.label.twist": {
        "ZH": "扭转",
        "EN": "Twist",
    },
    "sdk.label.swing": {
        "ZH": "摆动",
        "EN": "Swing",
    },
    "sdk.label.position": {
        "ZH": "位置",
        "EN": "Position",
    },
    "sdk.label.euler": {
        "ZH": "欧拉",
        "EN": "Euler",
    },
    "sdk.label.rotation_vector": {
        "ZH": "旋转向量",
        "EN": "Rotation vector",
    },
    "sdk.label.reading": {
        "ZH": "读数",
        "EN": "Reading",
    },
    "sdk.rest_pose": {
        "ZH": "静止姿态",
        "EN": "Rest pose",
    },

    # ---- modules/jcns_sdk.py: key list ----
    "sdk.keys.cannot_delete_ends": {
        "ZH": "键Start 和键End 不能删除",
        "EN": "Key Start and Key End cannot be deleted",
    },
    "sdk.warn.reading_outside": {
        "ZH": "%s 的读数 %s 不在%s（%s）和%s（%s）之间",
        "EN": "%s: reading %s is not between %s (%s) and %s (%s)",
    },
    "sdk.warn.reading_reversed": {
        "ZH": "%s 的读数 %s 与前面的%s（%s）顺序相反",
        "EN": "%s: reading %s runs against the earlier %s (%s)",
    },
    "sdk.warn.order_mismatch": {
        "ZH": "列表顺序与读数不一致，生成时按读数排序",
        "EN": "The list order does not match the readings; generating sorts by reading",
    },

    # ---- modules/jcns_sdk.py: planning ----
    "sdk.err.read_mode_unknown": {
        "ZH": "读取方式 %r 不存在",
        "EN": "Read mode %r does not exist",
    },
    "sdk.err.drive_flat": {
        "ZH": "驱动在各键之间没有变化",
        "EN": "The driver does not change between keys",
    },
    "sdk.err.drive_flat_mode": {
        "ZH": "按所选方式读驱动，各键之间没有变化；换一种读取方式或轴试试",
        "EN": "Reading the driver by the selected mode shows no change between keys; try another read mode or axis",
    },
    "sdk.err.drive_flat_any": {
        "ZH": "读驱动，各键之间没有变化；换一种读取方式或轴试试",
        "EN": "Reading the driver shows no change between keys; try another read mode or axis",
    },
    "sdk.warn.channel_unreadable": {
        "ZH": "被驱动「%s」的%s取不出值（父骨缩放为 0），已跳过",
        "EN": "Driven bone \"%s\": %s cannot be read (parent bone scale is 0); skipped",
    },
    "sdk.warn.rotation_unreachable": {
        "ZH": "被驱动「%s」的%s有 %.1f° 表达不了的旋转",
        "EN": "Driven bone \"%s\": %s has %.1f° of rotation that cannot be expressed",
    },
    "sdk.err.same_reading": {
        "ZH": "%s 和%s 的驱动读数相同（%s），被驱动却不同，对应关系不明；删掉其中一个键",
        "EN": "%s and %s have the same driver reading (%s) but different driven poses, so the mapping is ambiguous; delete one of the keys",
    },
    "sdk.note.same_pose": {
        "ZH": "%s 和%s 的姿态相同，按一个键算",
        "EN": "%s and %s have the same pose; counted as one key",
    },
    "sdk.warn.rest_output": {
        "ZH": "%s %s 输出 %s（应为 %s）",
        "EN": "%s %s outputs %s (should be %s)",
    },
    "sdk.warn.rest_off_in_keys": {
        "ZH": "驱动在静止姿态的那个键里，被驱动却不在静止姿态，静止时%s",
        "EN": "The driver is at rest in one key but the driven bones are not; at rest: %s",
    },
    "sdk.warn.rest_not_in_keys": {
        "ZH": "静止姿态不在键里（驱动静止时读 %s），静止时%s。再记一个静止姿态的键",
        "EN": "The rest pose is not in the keys (the driver reads %s at rest); at rest: %s. Record another key at the rest pose",
    },
    "sdk.err.rotation_type": {
        "ZH": "旋转目标的变换类型只能是 %s",
        "EN": "The transform type of a rotation target can only be %s",
    },
    "sdk.err.tangent": {
        "ZH": "曲线切线只能是线性或平滑",
        "EN": "The curve tangent can only be Linear or Smooth",
    },
    "sdk.err.no_driver": {
        "ZH": "先设置驱动",
        "EN": "Set the driver first",
    },
    "sdk.err.no_driven": {
        "ZH": "先添加被驱动",
        "EN": "Add a driven bone first",
    },
    "sdk.err.driver_is_driven": {
        "ZH": "「%s」既是驱动又是被驱动",
        "EN": "\"%s\" is both the driver and a driven bone",
    },
    "sdk.err.driven_duplicate": {
        "ZH": "被驱动「%s」重复",
        "EN": "Driven bone \"%s\" is listed twice",
    },
    "sdk.err.no_rest": {
        "ZH": "取不到「%s」的静止姿态",
        "EN": "Cannot get the rest pose of \"%s\"",
    },
    "sdk.err.too_few_keys": {
        "ZH": "至少需要 2 个键（现有 %d 个）",
        "EN": "At least 2 keys are needed (%d now)",
    },
    "sdk.warn.keys_without_driver": {
        "ZH": "%s 没有记录驱动「%s」，已忽略",
        "EN": "%s did not record the driver \"%s\"; ignored",
    },
    "sdk.err.too_few_driver_keys": {
        "ZH": "至少需要 2 个键记录了驱动（现有 %d 个）",
        "EN": "At least 2 keys must record the driver (%d now)",
    },
    "sdk.skip.no_pose": {
        "ZH": "没有记录姿态",
        "EN": "has no recorded pose",
    },
    "sdk.skip.missing_in": {
        "ZH": "在%s 里没有记录",
        "EN": "is not recorded in %s",
    },
    "sdk.skip.no_change": {
        "ZH": "在各键之间没有变化",
        "EN": "does not change between keys",
    },
    "sdk.err.driven_skip": {
        "ZH": "被驱动「%s」%s",
        "EN": "Driven bone \"%s\" %s",
    },
    "sdk.warn.driven_skip": {
        "ZH": "被驱动「%s」%s，已跳过",
        "EN": "Driven bone \"%s\" %s; skipped",
    },
    "sdk.err.curve_not_editable": {
        "ZH": "%d 个键要生成曲线，%s；最多 %d 个键",
        "EN": "%d keys would make a curve, but %s; at most %d keys are allowed",
    },
    "sdk.err.curve_not_editable_default": {
        "ZH": "这个文件不能编辑它",
        "EN": "this file cannot edit the curve",
    },
    "sdk.warn.step_gap": {
        "ZH": "%s 和%s 的读数只差 %s，曲线上会读成一个台阶",
        "EN": "The readings of %s and %s differ by only %s; the curve reads them as one step",
    },

    # ---- modules/jcns_sdk.py: plan description ----
    "sdk.mode.two": {
        "ZH": "两点映射",
        "EN": "two-point mapping",
    },
    "sdk.mode.three": {
        "ZH": "三点映射",
        "EN": "three-point mapping",
    },
    "sdk.mode.complex": {
        "ZH": "ComplexMapping 曲线，%d 个关键帧",
        "EN": "ComplexMapping curve, %d keyframes",
    },
    "sdk.describe.head": {
        "ZH": "将生成 %d 条（%s）：",
        "EN": "Will generate %d constraint(s) (%s):",
    },
    "sdk.describe.bone": {
        "ZH": "%s：%d 条",
        "EN": "%s: %d constraint(s)",
    },

    # ---- modules/jcns_sdk.py: appending to an existing entry ----
    "sdk.append.property_target": {
        "ZH": "目标是材质或形变属性",
        "EN": "The target is a material or deformation property",
    },
    "sdk.append.cone_driver": {
        "ZH": "已有约束带 ConeDriver 输入，多源表达不了",
        "EN": "The existing constraint has ConeDriver inputs, which multiple sources cannot express",
    },
    "sdk.append.sources_full": {
        "ZH": "已有约束的驱动已满 %d 个",
        "EN": "The existing constraint already has %d drivers",
    },
    "sdk.append.additive_differs": {
        "ZH": "已有约束的「叠加」与新约束不同",
        "EN": "The existing constraint's \"Additive\" differs from the new constraint's",
    },
    "sdk.append.no_complex": {
        "ZH": "这个文件不能编辑 ComplexMapping",
        "EN": "This file cannot edit ComplexMapping",
    },
}
