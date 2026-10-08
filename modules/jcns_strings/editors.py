"""Strings of jcns_editors.py (per-section editor panels)."""

STRINGS = {
    # --- panel titles and tooltips -------------------------------------------------
    "editors.panel.driven_desc": {
        "ZH": "被驱动的骨骼、通道，以及和别的约束共用同一通道时谁生效。",
        "EN": "The driven bone and channel, and which constraint wins when several share the same channel.",
    },
    "editors.panel.sources": {"ZH": "驱动", "EN": "Drivers"},
    "editors.panel.mapping": {"ZH": "映射曲线", "EN": "Mapping Curve"},
    "editors.panel.cones": {"ZH": "ConeDriver 输入", "EN": "ConeDriver Inputs"},
    "editors.cones.no_table": {"ZH": "先在「ConeInput 表」面板里新建锥形", "EN": "Add a cone in the ConeInput Table panel first"},
    "editors.panel.cones_desc": {
        "ZH": "ConeDriver 输入：关节摆进某个锥形的程度驱动这条约束，与驱动并列。",
        "EN": "ConeDriver inputs: how far a joint swings into a cone drives this constraint, alongside the drivers.",
    },
    "editors.panel.tools": {"ZH": "工具", "EN": "Tools"},
    "editors.panel.advanced": {"ZH": "高级", "EN": "Advanced"},
    "editors.panel.advanced_desc": {
        "ZH": "引擎的处理规则，含义未知的字段，和取值固定、导出时原样写回的字段。",
        "EN": "How the engine processes this entry, fields of unknown meaning, and fields with fixed values written back unchanged on export.",
    },
    "editors.panel.multi": {"ZH": "Multi 蒙皮", "EN": "Multi"},
    "editors.panel.aim": {"ZH": "Aim 瞄准", "EN": "Aim"},
    "editors.panel.rotexpr": {"ZH": "RotExpr 旋转表达式", "EN": "RotExpr"},
    "editors.panel.material": {"ZH": "Material 材质", "EN": "Material"},
    "editors.panel.raw_fields": {"ZH": "原始字段", "EN": "Raw Fields"},
    "editors.panel.unrecognized": {"ZH": "未知类型", "EN": "Unknown Type"},

    # --- shared words ---------------------------------------------------------------
    "editors.word.driven": {"ZH": "被驱动", "EN": "Driven"},
    "editors.word.driver": {"ZH": "驱动", "EN": "Driver"},
    "editors.word.output": {"ZH": "输出", "EN": "Output"},
    "editors.anchor.a": {"ZH": "起点 A", "EN": "Start A"},
    "editors.anchor.b": {"ZH": "折点 B", "EN": "Kink B"},
    "editors.anchor.c": {"ZH": "终点 C", "EN": "End C"},
    "editors.unit_title": {"ZH": "%s（%s）", "EN": "%s (%s)"},

    # --- field row labels -----------------------------------------------------------
    "editors.field.bone": {"ZH": "骨骼：", "EN": "Bone:"},
    "editors.field.local_axis": {"ZH": "局部轴向：", "EN": "Local axis:"},
    "editors.field.channel": {"ZH": "分量：", "EN": "Channel:"},
    "editors.field.parameter": {"ZH": "参数：", "EN": "Parameter:"},
    "editors.target.bone": {"ZH": "骨骼：", "EN": "Bone:"},
    "editors.target.shape_key": {"ZH": "形态键：", "EN": "Shape key:"},
    "editors.target.material": {"ZH": "材质：", "EN": "Material:"},
    "editors.target.component": {"ZH": "组件：", "EN": "Component:"},
    "editors.target.user_value": {"ZH": "名称：", "EN": "Name:"},
    "editors.field.transform": {"ZH": "变换：", "EN": "Transform:"},
    "editors.field.property": {"ZH": "属性：", "EN": "Property:"},
    "editors.field.base_pose": {"ZH": "叠加：", "EN": "Additive:"},
    "editors.field.input_type": {"ZH": "读取方式：", "EN": "Read mode:"},
    "editors.field.rot_order": {"ZH": "欧拉顺序：", "EN": "Euler order:"},
    "editors.field.ref_frame": {"ZH": "参考系：", "EN": "Reference frame:"},
    "editors.field.driven": {"ZH": "被驱动：", "EN": "Driven:"},
    "editors.field.driver": {"ZH": "驱动：", "EN": "Driver:"},
    "editors.field.rest_pose": {"ZH": "静止姿态：", "EN": "Rest pose:"},
    "editors.field.aim_target": {"ZH": "瞄准目标：", "EN": "Aim target:"},
    "editors.field.type": {"ZH": "类型：", "EN": "Type:"},
    "editors.field.up_bone": {"ZH": "辅助骨骼：", "EN": "Helper bone:"},
    "editors.field.influence": {"ZH": "影响：", "EN": "Influence:"},
    "editors.field.aim_target2": {"ZH": "第二目标：", "EN": "Second target:"},
    "editors.field.aim_weight2": {"ZH": "第二目标权重：", "EN": "Second target weight:"},

    # --- framework ------------------------------------------------------------------
    "editors.no_root": {
        "ZH": "找不到所属的 JCNS 根节点。",
        "EN": "Could not find the JCNS root this belongs to.",
    },

    # --- Outputs: warnings -----------------------------------------------------------
    "editors.warn.folded_dead": {
        "ZH": "折点越界，输出恒为 0",
        "EN": "Kink is out of range; output is always 0",
    },
    "editors.btn.sort_anchors": {"ZH": "排序锚点", "EN": "Sort Anchors"},
    "editors.warn.anchor_unreachable": {
        "ZH": "锚点折返，%s 取不到",
        "EN": "Anchors fold back; %s is never reached",
    },
    "editors.warn.inert": {
        "ZH": "输出锚点全为 0，无输出",
        "EN": "All output anchors are 0; no output",
    },
    "editors.warn.rest_offset": {
        "ZH": "静止时已偏转 %s%s",
        "EN": "Already offset by %s%s at rest",
    },
    "editors.btn.swap_ends": {"ZH": "对调首尾", "EN": "Swap Ends"},

    # --- Outputs: curve and keyframes ------------------------------------------------
    "editors.curve.title": {
        "ZH": "曲线（横轴驱动，纵轴输出）",
        "EN": "Curve (x: driver, y: output)",
    },
    "editors.curve.legend": {
        "ZH": "%d  %s 局部 %s 轴",
        "EN": "%d  %s local %s axis",
    },
    "editors.keys.title": {"ZH": "曲线关键点 %d", "EN": "Curve keys %d"},
    "editors.keys.row": {
        "ZH": "%s%s → %s　　斜率 入 %s / 出 %s",
        "EN": "%s%s → %s    slope in %s / out %s",
    },
    "editors.keys.more": {"ZH": "……共 %d 个", "EN": "... %d in total"},
    "editors.keys.anchors_nonzero": {
        "ZH": "锚点不为 0，与曲线并存时效果未知",
        "EN": "Anchors are not 0; the effect together with the curve is unknown",
    },

    # --- Outputs: drivers ------------------------------------------------------------
    "editors.sources.none": {
        "ZH": "还没有驱动，无输出",
        "EN": "No drivers yet; no output",
    },
    "editors.sources.item": {"ZH": "驱动 %d", "EN": "Driver %d"},
    "editors.sources.early_read": {
        "ZH": "驱动的 %s 轴由本条或后面的条目驱动，读到的是静止值",
        "EN": "The driver's %s axis is driven by this or a later entry; the value read is the rest value",
    },
    "editors.mapping.driver_item": {"ZH": "驱动 %d：%s %s", "EN": "Driver %d: %s %s"},
    "editors.tools.mirror": {"ZH": "镜像到另一侧…", "EN": "Mirror to Other Side…"},

    # --- Outputs: advanced -----------------------------------------------------------
    "editors.adv.attr_flags_other": {"ZH": "曲线模式其余位", "EN": "Other curve-mode bits"},
    "editors.adv.attr_flags_other": {"ZH": "其余标志位", "EN": "Other flag bits"},
    "editors.adv.flags_note": {
        "ZH": "其余标志位：位4、位5 导出时按变换类型重算；位2、位3 只出现在形变和材质目标上",
        "EN": "Other flag bits: bits 4 and 5 are recalculated from the transform type on export; bits 2 and 3 only appear on deform and material targets",
    },
    "editors.adv.group_count": {
        "ZH": "关节组计数 +77：%d（导出时自动校验）",
        "EN": "Joint group count +77: %d (checked automatically on export)",
    },
    "editors.adv.hash_override": {
        "ZH": "哈希覆盖（0 表示按名字计算）",
        "EN": "Hash overrides (0 = computed from the name)",
    },
    "editors.adv.property_hash": {"ZH": "属性", "EN": "Property"},
    "editors.adv.object_hash": {"ZH": "目标", "EN": "Target"},
    "editors.adv.fixed_vec4": {"ZH": "固定为 (0,0,0,1)", "EN": "Fixed at (0,0,0,1)"},
    "editors.adv.fixed_zero": {"ZH": "固定为 0", "EN": "Fixed at 0"},
    "editors.adv.fields_unknown": {"ZH": "未知字段", "EN": "Unknown fields"},

    # --- Multi -----------------------------------------------------------------------
    "editors.multi.need_armature": {
        "ZH": "先设置目标骨架，才能增删驱动",
        "EN": "Set the target armature first to add or remove drivers",
    },
    "editors.multi.weight_sum": {"ZH": "权重和 %.3f", "EN": "Weight sum %.3f"},
    "editors.multi.normalize": {"ZH": "归一化", "EN": "Normalize"},
    "editors.multi.v102_zero": {"ZH": "v102 固定为 0", "EN": "Fixed at 0 in v102"},
    "editors.multi.tail": {"ZH": "尾部 2 字节", "EN": "Trailing 2 bytes"},

    # --- Aim ------------------------------------------------------------------------
    "editors.aim.need_armature": {
        "ZH": "先设置目标骨架，才能换被驱动",
        "EN": "Set the target armature first to change the driven bone",
    },
    "editors.aim.vectors": {"ZH": "向量", "EN": "Vectors"},
    "editors.aim.rule.scene_up": {
        "ZH": "本地瞄准轴指向目标，本地上方向轴对齐世界 +Y",
        "EN": "The local aim axis points at the target; the local up axis aligns with world +Y",
    },
    "editors.aim.rule.object_up": {
        "ZH": "本地瞄准轴指向目标，本地上方向轴对齐「自己指向辅助骨」的方向",
        "EN": "The local aim axis points at the target; the local up axis aligns with the direction from itself to the helper bone",
    },
    "editors.aim.rule.object_rotation_up": {
        "ZH": "本地瞄准轴指向目标，本地上方向轴对齐辅助骨的一根局部轴，由「上方向」向量选（(0,1,0) 是 Y 轴，(0,0,1) 是 Z 轴）",
        "EN": "The local aim axis points at the target; the local up axis aligns with one local axis of the helper bone, chosen by the up direction vector ((0,1,0) is the Y axis, (0,0,1) is the Z axis)",
    },
    "editors.aim.rule.vector": {
        "ZH": "本地瞄准轴指向目标，本地上方向轴对齐「上方向」向量给出的世界方向",
        "EN": "The local aim axis points at the target; the local up axis aligns with the world direction given by the up direction vector",
    },
    "editors.aim.rule.none": {
        "ZH": "从静止姿态朝目标转最短弧，不约束翻滚",
        "EN": "Rotates the shortest arc from the rest pose toward the target; roll is not constrained",
    },
    "editors.aim.rule.none_maya_like": {
        "ZH": "从父骨朝向起朝目标转最短弧，丢掉静止姿态",
        "EN": "Rotates the shortest arc from the parent bone's orientation toward the target; the rest pose is dropped",
    },

    # --- RotExpr --------------------------------------------------------------------
    "editors.rot.rule.replace": {
        "ZH": "结果是驱动旋转按系数缩放后的旋转，不含静止姿态；系数 (1,1,1) 时等于驱动的旋转",
        "EN": "The result is the driver's rotation scaled by the gains, without the rest pose; with gains (1,1,1) it equals the driver's rotation",
    },
    "editors.rot.rule.add_rest": {
        "ZH": "结果 = 静止姿态 · 驱动旋转按系数缩放后的旋转；系数 (1,1,1) 时是精确拷贝",
        "EN": "Result = rest pose · driver rotation scaled by the gains; with gains (1,1,1) it is an exact copy",
    },
    "editors.rot.rule.nonlinear": {
        "ZH": "系数不是 1 时只有小角度是每轴相乘，大角度偏离线性，精确公式未定",
        "EN": "With gains other than 1, only small angles multiply per axis; large angles deviate from linear and the exact formula is not settled",
    },
    "editors.rot.reserved": {
        "ZH": "保留字段（Rotation / Scale 恒为 0,0,0,1）",
        "EN": "Reserved fields (Rotation / Scale always 0,0,0,1)",
    },

    # --- Material -------------------------------------------------------------------
    "editors.mat.hashes_title": {"ZH": "哈希与变换 ID", "EN": "Hashes and transform ID"},
    "editors.mat.name_hash": {"ZH": "材质名哈希", "EN": "Material name hash"},
    "editors.mat.name": {"ZH": "材质名", "EN": "Material"},
    "editors.mat.property": {"ZH": "参数名", "EN": "Parameter"},
    "editors.mat.apply_mode": {"ZH": "写入方式", "EN": "Apply mode"},
    "editors.mat.no_material": {"ZH": "参考 mdf2 里没有这个材质，游戏里可能找不到它",
                                "EN": "The reference mdf2 files have no material by this name; the game may not find it"},
    "editors.mat.no_param": {"ZH": "这个材质在参考 mdf2 里没有这个参数",
                             "EN": "This material has no parameter by this name in the reference mdf2 files"},
    "editors.mat.untested": {"ZH": "材质名和参数名填模型 mdf2 里的原文；在游戏里的具体效果未知", "EN": "Use the names exactly as they appear in the model's mdf2; the in-game effect is not known"},
    "editors.mat.property_hash": {"ZH": "属性哈希", "EN": "Property hash"},
    "editors.mat.tail0": {"ZH": "尾0", "EN": "Tail 0"},
    "editors.mat.tail1": {"ZH": "尾1", "EN": "Tail 1"},
    "editors.mat.tail2": {"ZH": "尾2", "EN": "Tail 2"},

    # --- Unknown --------------------------------------------------------------------
    "editors.unrecognized.type": {"ZH": "类型：%s", "EN": "Type: %s"},
}
