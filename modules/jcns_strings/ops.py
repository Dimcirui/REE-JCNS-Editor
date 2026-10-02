STRINGS = {
    "ops.label.add_constraint": {
        "ZH": "新增约束",
        "EN": "Add Constraint",
    },
    "ops.desc.add_constraint": {
        "ZH": "在当前 JCNS 集合里新增一条空白约束",
        "EN": "Add a blank constraint to the current JCNS collection",
    },
    "ops.label.delete_constraint": {
        "ZH": "删除约束",
        "EN": "Delete Constraint",
    },
    "ops.desc.delete_constraint": {
        "ZH": "删除选中的约束，其余约束重新编号",
        "EN": "Delete the selected constraint and renumber the rest",
    },
    "ops.label.move_constraint": {
        "ZH": "移动约束",
        "EN": "Move Constraint",
    },
    "ops.desc.move_constraint": {
        "ZH": "把选中的约束在文件里前移或后移一位，同一通道上最后一条生效",
        "EN": "Move the selected constraint one place up or down in the file; the last one on a channel is the live one",
    },
    "ops.label.add_source": {
        "ZH": "新增驱动",
        "EN": "Add Driver",
    },
    "ops.desc.add_source": {
        "ZH": "给选中的约束再加一个驱动，各驱动的输出相加",
        "EN": "Add another driver to the selected constraint; the outputs of all drivers are summed",
    },
    "ops.label.remove_source": {
        "ZH": "删除驱动",
        "EN": "Delete Driver",
    },
    "ops.desc.remove_source": {
        "ZH": "删除当前约束里选中的驱动",
        "EN": "Delete the selected driver of the current constraint",
    },
    "ops.label.swap_mapto_ends": {
        "ZH": "对调输出首尾",
        "EN": "Swap Output Ends",
    },
    "ops.desc.swap_mapto_ends": {
        "ZH": "交换当前驱动的「To 起点」和「To 终点」，让骨骼静止时不再偏转",
        "EN": "Swap the To Start and To End of the current driver so the bone no longer deflects at rest",
    },
    "ops.label.mirror_constraints": {
        "ZH": "镜像到另一侧",
        "EN": "Mirror to Other Side",
    },
    "ops.desc.mirror_constraints": {
        "ZH": "把选中的约束镜像到骨架的另一侧，被驱动和驱动可以分别决定是否换到对侧",
        "EN": "Mirror the selected constraints to the other side of the rig; the driven bone and the drivers can each be switched to the opposite side or not",
    },
    "ops.label.sort_anchors": {
        "ZH": "排序锚点",
        "EN": "Sort Anchors",
    },
    "ops.desc.sort_anchors": {
        "ZH": "把三个锚点按输入重新排序，曲线形状不变",
        "EN": "Re-sort the three anchors by input; the curve shape does not change",
    },
    "ops.label.add_section_entry": {
        "ZH": "新增条目",
        "EN": "Add Entry",
    },
    "ops.desc.add_section_entry": {
        "ZH": "在当前 JCNS 文件里新增一条 Skin / Aim / RotExpr 条目",
        "EN": "Add a Skin / Aim / RotExpr entry to the current JCNS file",
    },
    "ops.desc.skin_source_add": {
        "ZH": "给选中的 Skin 条目加一个驱动",
        "EN": "Add a driver to the selected Skin entry",
    },
    "ops.desc.skin_source_remove": {
        "ZH": "删除选中 Skin 条目里当前的驱动",
        "EN": "Delete the current driver of the selected Skin entry",
    },
    "ops.label.skin_normalize_weights": {
        "ZH": "权重归一化",
        "EN": "Normalize Weights",
    },
    "ops.desc.skin_normalize_weights": {
        "ZH": "按比例缩放选中条目的权重，使总和为 1",
        "EN": "Scale the weights of the selected entry proportionally so they sum to 1",
    },
    "ops.label.cm_create": {
        "ZH": "改用曲线",
        "EN": "Use Curve",
    },
    "ops.desc.cm_create": {
        "ZH": "把当前驱动的折线映射换成画出同样折线的曲线，可在曲线编辑器里编辑",
        "EN": "Replace the current driver's polyline mapping with a curve that draws the same polyline, editable in the Graph Editor",
    },
    "ops.label.cm_remove": {
        "ZH": "改回折线",
        "EN": "Back to Polyline",
    },
    "ops.desc.cm_remove": {
        "ZH": "删除当前驱动的曲线，改回折线映射（未设置的锚点为 0）",
        "EN": "Delete the current driver's curve and go back to the polyline mapping (unset anchors are 0)",
    },
    "ops.label.cm_normalize": {
        "ZH": "规范手柄",
        "EN": "Normalize Handles",
    },
    "ops.desc.cm_normalize": {
        "ZH": "把每个手柄放回所在段长度的三分之一处，斜率不变，不影响游戏里的结果",
        "EN": "Move each handle back to one third of its segment length; slopes are unchanged and the result in game is not affected",
    },
    "ops.label.cm_edit": {
        "ZH": "在曲线编辑器中编辑",
        "EN": "Edit in Graph Editor",
    },
    "ops.desc.cm_edit": {
        "ZH": "在曲线编辑器里打开当前驱动的曲线",
        "EN": "Open the current driver's curve in the Graph Editor",
    },
    "ops.label.cone_info_add": {
        "ZH": "新增 ConeDriver 输入",
        "EN": "Add ConeDriver Input",
    },
    "ops.desc.cone_info_add": {
        "ZH": "给当前约束加一个它读取的锥形",
        "EN": "Add a cone for the current constraint to read",
    },
    "ops.label.cone_info_remove": {
        "ZH": "删除 ConeDriver 输入",
        "EN": "Delete ConeDriver Input",
    },
    "ops.desc.cone_info_remove": {
        "ZH": "删除当前约束里选中的锥形",
        "EN": "Delete the selected cone of the current constraint",
    },
    "ops.add_constraint.added": {
        "ZH": "已新增约束「%s」。",
        "EN": "Added constraint \"%s\".",
    },
    "ops.err.root_no_collection": {
        "ZH": "根节点不属于任何集合。",
        "EN": "The root node is not in any collection.",
    },
    "ops.delete_constraint.done": {
        "ZH": "约束已删除，其余已重新编号。",
        "EN": "Constraint deleted; the rest were renumbered.",
    },
    "ops.move.direction": {
        "ZH": "方向",
        "EN": "Direction",
    },
    "ops.move.up": {
        "ZH": "上移",
        "EN": "Move Up",
    },
    "ops.move.up_desc": {
        "ZH": "往文件前面挪一位",
        "EN": "Move one place toward the start of the file",
    },
    "ops.move.down": {
        "ZH": "下移",
        "EN": "Move Down",
    },
    "ops.move.down_desc": {
        "ZH": "往文件后面挪一位",
        "EN": "Move one place toward the end of the file",
    },
    "ops.err.no_root": {
        "ZH": "找不到所属的 JCNS 根节点。",
        "EN": "Cannot find the JCNS root this belongs to.",
    },
    "ops.move.not_ordered": {
        "ZH": "该类型的约束不参与排序。",
        "EN": "This kind of constraint is not part of the ordering.",
    },
    "ops.move.at_top": {
        "ZH": "已经在最前面了。",
        "EN": "Already at the top.",
    },
    "ops.move.at_bottom": {
        "ZH": "已经在最后面了。",
        "EN": "Already at the bottom.",
    },
    "ops.move.done": {
        "ZH": "已移动到第 %d 位（共 %d 条）。",
        "EN": "Moved to position %d of %d.",
    },
    "ops.add_source.done": {
        "ZH": "已新增第 %d 个驱动。",
        "EN": "Added driver %d.",
    },
    "ops.remove_source.done": {
        "ZH": "已删除驱动，剩余 %d 个。",
        "EN": "Driver deleted; %d left.",
    },
    "ops.swap_mapto_ends.done": {
        "ZH": "输出首尾已对调：静止输出 %+.2f° → %+.2f°",
        "EN": "Output ends swapped: rest output %+.2f° → %+.2f°",
    },
    "ops.mirror.target": {
        "ZH": "镜像被驱动",
        "EN": "Mirror Driven",
    },
    "ops.mirror.target_desc": {
        "ZH": "把被驱动的骨骼换到对侧；被驱动是中线骨骼时关闭",
        "EN": "Swap the driven bone to the opposite side; turn off when the driven bone is a centre-line bone",
    },
    "ops.mirror.source": {
        "ZH": "镜像驱动",
        "EN": "Mirror Drivers",
    },
    "ops.mirror.source_desc": {
        "ZH": "把每个驱动的骨骼换到对侧；驱动是中线骨骼时关闭",
        "EN": "Swap each driver's bone to the opposite side; turn off when the drivers are centre-line bones",
    },
    "ops.mirror.overwrite": {
        "ZH": "覆盖已有数值",
        "EN": "Overwrite Existing Values",
    },
    "ops.mirror.overwrite_desc": {
        "ZH": "对侧已有同名约束时覆盖它的数值，默认不覆盖",
        "EN": "Overwrite the values of an existing constraint of the same name on the opposite side; off by default",
    },
    "ops.mirror.use_frames": {
        "ZH": "从骨架读取符号",
        "EN": "Read Signs from Rig",
    },
    "ops.mirror.use_frames_desc": {
        "ZH": "按每对骨骼的局部坐标系决定各轴符号；关闭时用默认符号（X:+1, Y:-1, Z:-1）",
        "EN": "Decide each axis sign from the local axes of every bone pair; when off, the default signs are used (X:+1, Y:-1, Z:-1)",
    },
    "ops.mirror.need_one": {
        "ZH": "被驱动和驱动至少镜像一项",
        "EN": "Mirror at least one of the driven bone and the drivers",
    },
    "ops.mirror.need_one_report": {
        "ZH": "被驱动和驱动至少镜像一项。",
        "EN": "Mirror at least one of the driven bone and the drivers.",
    },
    "ops.mirror.no_counterpart": {
        "ZH": "%s 没有对侧骨骼",
        "EN": "%s has no opposite-side bone",
    },
    "ops.mirror.no_sign": {
        "ZH": "%s 的 %s 轴无法确定镜像符号",
        "EN": "Cannot determine the mirror sign for %s (axis %s)",
    },
    "ops.mirror.no_frame": {
        "ZH": "%s 的参考系四元数无法镜像",
        "EN": "The reference-frame quaternion of %s cannot be mirrored",
    },
    "ops.mirror.part_new": {
        "ZH": "新建 %d 条",
        "EN": "%d created",
    },
    "ops.mirror.part_updated": {
        "ZH": "更新 %d 条",
        "EN": "%d updated",
    },
    "ops.mirror.part_kept": {
        "ZH": "跳过 %d 条已存在的（可勾选覆盖）",
        "EN": "%d existing skipped (tick Overwrite to replace)",
    },
    "ops.mirror.sep": {
        "ZH": "，",
        "EN": ", ",
    },
    "ops.mirror.done": {
        "ZH": "镜像完成：%s",
        "EN": "Mirror done: %s",
    },
    "ops.mirror.no_change": {
        "ZH": "无改动",
        "EN": "no changes",
    },
    "ops.mirror.with_problems": {
        "ZH": "%s；%s",
        "EN": "%s; %s",
    },
    "ops.sort_anchors.done_all": {
        "ZH": "锚点已排序：全部可用",
        "EN": "Anchors sorted: all reachable",
    },
    "ops.sort_anchors.done_unreachable": {
        "ZH": "锚点已排序：仍有锚点 %s 取不到",
        "EN": "Anchors sorted: anchor %s is still unreachable",
    },
    "ops.section.cannot_add": {
        "ZH": "不能新增这类条目。",
        "EN": "This kind of entry cannot be added.",
    },
    "ops.section.added": {
        "ZH": "已新增「%s」。",
        "EN": "Added \"%s\".",
    },
    "ops.cm_edit.selected": {
        "ZH": "已选中这条曲线，在曲线编辑器里编辑",
        "EN": "Curve selected; edit it in the Graph Editor",
    },
    "ops.driver.no_driven_bone": {
        "ZH": "找不到被驱动骨骼「%s」",
        "EN": "Driven bone \"%s\" not found",
    },
    "ops.driver.no_channel": {
        "ZH": "变换类型「%s」在 Blender 中没有对应通道",
        "EN": "Transform type \"%s\" has no matching channel in Blender",
    },
    "ops.driver.not_set": {
        "ZH": "未设置驱动",
        "EN": "No driver set",
    },
    "ops.driver.none_or_w": {
        "ZH": "没有驱动，或 W 轴暂不支持",
        "EN": "No driver, or the W axis is not supported yet",
    },
    "ops.driver.too_long": {
        "ZH": "这根骨的驱动太多，驱动器表达式超过 255 字符",
        "EN": "This bone has too many drivers; the driver expression exceeds 255 characters",
    },
    "ops.driver.too_long_n": {
        "ZH": "这根骨的驱动太多，驱动器表达式超过 255 字符（%d）",
        "EN": "This bone has too many drivers; the driver expression exceeds 255 characters (%d)",
    },
    "ops.driver.w_unsupported": {
        "ZH": "W 轴暂不支持",
        "EN": "The W axis is not supported yet",
    },
    "ops.driver.label_loc_group": {
        "ZH": "%s（整骨预览 %d 个平移通道）",
        "EN": "%s (whole-bone preview, %d translation channels)",
    },
    "ops.driver.label_rot_group": {
        "ZH": "%s（整骨预览 %d 个旋转通道）",
        "EN": "%s (whole-bone preview, %d rotation channels)",
    },
    "ops.driver.label_last_wins": {
        "ZH": "，同通道 %d 条中最后一条生效",
        "EN": ", the last of %d entries on this channel is live",
    },
    "ops.driver.source_missing": {
        "ZH": "源骨骼不在骨架里：%s",
        "EN": "Source bones not in the armature: %s",
    },
    "ops.driver.cone_only": {
        "ZH": "只由 ConeDriver 驱动，暂不预览，骨骼保持静止姿态",
        "EN": "Driven only by ConeDrivers, which are not previewed yet; the bone stays at rest",
    },
    "ops.driver.none": {
        "ZH": "没有驱动",
        "EN": "No driver",
    },
    "ops.driver.driven_unresolved": {
        "ZH": "被驱动骨骼未解析",
        "EN": "Driven bone not resolved",
    },
}
