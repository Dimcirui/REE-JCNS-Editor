STRINGS = {
    # ---- list separators (shared by the merge messages) ----
    "io.sep.clause": {"ZH": "；", "EN": "; "},
    "io.sep.list": {"ZH": "、", "EN": ", "},

    # ---- modules/jcns_merge.py: fields that must agree ----
    "io.merge.field.base_pose": {"ZH": "叠加", "EN": "Additive"},
    "io.merge.field.attr_flags_other": {"ZH": "其余标志位", "EN": "Other flags"},
    "io.merge.field.vec4": {"ZH": "Vec4", "EN": "Vec4"},
    "io.merge.field.float2": {"ZH": "Float2", "EN": "Float2"},
    "io.merge.field.unknown_byte_72": {"ZH": "未知字节 (+72)", "EN": "Unknown byte (+72)"},
    "io.merge.field.byte_74": {"ZH": "+74", "EN": "+74"},
    "io.merge.field.byte_75": {"ZH": "+75", "EN": "+75"},
    "io.merge.field.reserved_tail": {"ZH": "保留字节", "EN": "Reserved bytes"},

    # ---- modules/jcns_merge.py: why a merge is blocked ----
    "io.merge.only_one": {
        "ZH": "这个通道上只有一条约束",
        "EN": "This channel has only one constraint",
    },
    "io.merge.not_same_channel": {
        "ZH": "不在同一个通道上",
        "EN": "They are not on the same channel",
    },
    "io.merge.target_property": {
        "ZH": "目标是材质或形变属性，不支持合并",
        "EN": "The target is a material or morph property, which cannot be merged",
    },
    "io.merge.fields_differ": {"ZH": "%s不一致", "EN": "Fields differ: %s"},
    "io.merge.cone_drivers": {
        "ZH": "带 ConeDriver 输入，多源约束表达不了",
        "EN": "It has ConeDriver inputs, which a multi-source constraint cannot express",
    },
    "io.merge.no_sources": {"ZH": "有条目没有驱动", "EN": "An entry has no driver"},
    "io.merge.too_many_sources": {
        "ZH": "合并后驱动超过 %d 个",
        "EN": "The merged entry would have more than %d drivers",
    },
    "io.merge.complex_mapping": {
        "ZH": "含复杂映射曲线，这个文件不支持把它并入别的条目",
        "EN": "It has a complex mapping curve, which this file cannot move into another entry",
    },
    "io.merge.overlap": {"ZH": "合并计划互相重叠", "EN": "The merge plans overlap"},

    # ---- jcns_merge_ops.py ----
    "io.merge.no_add_remove": {
        "ZH": "这个文件不能增删约束",
        "EN": "This file does not allow adding or removing constraints",
    },
    "io.merge.channel_text": {"ZH": "%s 的局部 %s 轴", "EN": "%s, local %s axis"},
    "io.merge.channel_with_note": {"ZH": "%s（%s）", "EN": "%s (%s)"},
    "io.merge.more_suffix": {"ZH": "等", "EN": ", etc."},
    "io.merge.one.label": {"ZH": "合并本通道", "EN": "Merge This Channel"},
    "io.merge.one.tip": {
        "ZH": "把这个通道上的多条约束合并成一条，各驱动的输出相加",
        "EN": "Merge the constraints on this channel into one; the driver outputs add up",
    },
    "io.merge.root_not_found": {
        "ZH": "找不到所属的 JCNS 根节点。",
        "EN": "The JCNS root this entry belongs to was not found.",
    },
    "io.merge.not_in_ranges": {
        "ZH": "当前条目不在文件的 Outputs 列表里。",
        "EN": "The current entry is not in the file's Outputs list.",
    },
    "io.merge.cannot_merge": {"ZH": "不能合并：%s", "EN": "Cannot merge: %s"},
    "io.merge.one.done": {
        "ZH": "%s：%d 条合并成 1 条，共 %d 个驱动。",
        "EN": "%s: %d constraints merged into 1, %d drivers in total.",
    },
    "io.merge.all.label": {"ZH": "合并所有同通道约束", "EN": "Merge All Shared-Channel Constraints"},
    "io.merge.all.tip": {
        "ZH": "把文件里每个有多条约束的通道都合并成一条，各驱动的输出相加；不能合并的通道保持原样",
        "EN": "Merge every channel that has several constraints into one, adding up the driver outputs; channels that cannot be merged stay as they are",
    },
    "io.merge.all.dialog1": {
        "ZH": "每个共用通道合并成一条，各驱动输出相加。",
        "EN": "Each shared channel is merged into one entry; the driver outputs add up.",
    },
    "io.merge.all.dialog2": {
        "ZH": "结果可能与现在不同；不能合并的保持原样。",
        "EN": "The result may differ from the current one; channels that cannot be merged stay as they are.",
    },
    "io.merge.all.root_not_found": {"ZH": "找不到 JCNS 根节点。", "EN": "The JCNS root was not found."},
    "io.merge.all.none_shared": {
        "ZH": "没有哪个通道有多条约束。",
        "EN": "No channel has more than one constraint.",
    },
    "io.merge.all.skip_log": {"ZH": "%s：%s", "EN": "%s: %s"},
    "io.merge.all.none_mergeable": {
        "ZH": "没有可合并的通道；%d 个通道不能合并，原因见系统控制台。",
        "EN": "No channel can be merged; %d channels cannot be merged, see the system console for the reasons.",
    },
    "io.merge.all.done": {
        "ZH": "已合并 %d 个通道（%d 条约束并入 %d 条）",
        "EN": "Merged %d channels (%d constraints into %d)",
    },
    "io.merge.all.skipped": {
        "ZH": "；%d 个通道不能合并，保持原样：%s",
        "EN": "; %d channels cannot be merged and stay as they are: %s",
    },
    "io.merge.all.skipped_more": {
        "ZH": "等，其余见系统控制台",
        "EN": ", etc.; see the system console for the rest",
    },
    "io.merge.panel.shared": {
        "ZH": "与 %s 共用通道，只有最后一条生效",
        "EN": "Shares a channel with %s; only the last one takes effect",
    },
    "io.merge.panel.button": {"ZH": "合并", "EN": "Merge"},
    "io.merge.panel.shared_count": {
        "ZH": "%d 个通道有多条约束，只有最后一条生效",
        "EN": "%d channels have several constraints; only the last one takes effect",
    },
    "io.merge.warning.shared": {
        "ZH": "有 %d 个通道被多条约束共用，只有最后一条生效：%s。",
        "EN": "%d channels are shared by several constraints; only the last one takes effect: %s.",
    },
    "io.merge.warning.hint": {"ZH": "要叠加请先合并。", "EN": " To add them up, merge them first."},

    # ---- jcns_capture.py ----
    "io.capture.field_name": {"ZH": "锚点", "EN": "Anchor"},
    "io.capture.from_start": {"ZH": "From 起点", "EN": "From Start"},
    "io.capture.from_kink": {"ZH": "From 折点", "EN": "From Kink"},
    "io.capture.from_end": {"ZH": "From 终点", "EN": "From End"},
    "io.capture.to_start": {"ZH": "To 起点", "EN": "To Start"},
    "io.capture.to_kink": {"ZH": "To 折点", "EN": "To Kink"},
    "io.capture.to_end": {"ZH": "To 终点", "EN": "To End"},
    "io.capture.from_start.tip": {
        "ZH": "读取驱动当前的值，填入起点 A 的输入",
        "EN": "Read the driver's current value into the input of start A",
    },
    "io.capture.from_kink.tip": {
        "ZH": "读取驱动当前的值，填入折点 B 的输入",
        "EN": "Read the driver's current value into the input of kink B",
    },
    "io.capture.from_end.tip": {
        "ZH": "读取驱动当前的值，填入终点 C 的输入",
        "EN": "Read the driver's current value into the input of end C",
    },
    "io.capture.to_start.tip": {
        "ZH": "按被驱动当前姿态算出要写入的值，填入起点 A 的输出",
        "EN": "Compute the value to write from the driven bone's current pose and put it in the output of start A",
    },
    "io.capture.to_kink.tip": {
        "ZH": "按被驱动当前姿态算出要写入的值，填入折点 B 的输出",
        "EN": "Compute the value to write from the driven bone's current pose and put it in the output of kink B",
    },
    "io.capture.to_end.tip": {
        "ZH": "按被驱动当前姿态算出要写入的值，填入终点 C 的输出",
        "EN": "Compute the value to write from the driven bone's current pose and put it in the output of end C",
    },
    "io.capture.label": {"ZH": "从当前姿态取值", "EN": "Capture From Pose"},
    "io.capture.tip": {
        "ZH": "把骨骼当前姿态对应的值填进这个锚点",
        "EN": "Fill this anchor with the value of the bone's current pose",
    },
    "io.capture.tip_with_pose": {
        "ZH": "%s。先在骨架上摆好骨骼的姿态",
        "EN": "%s. Pose the bone on the armature first",
    },
    "io.capture.no_armature": {"ZH": "先设置目标骨架。", "EN": "Set the target armature first."},
    "io.capture.role_driver": {"ZH": "驱动", "EN": "driver"},
    "io.capture.role_driven": {"ZH": "被驱动", "EN": "driven bone"},
    "io.capture.role_not_set": {"ZH": "还没有设置%s。", "EN": "The %s is not set yet."},
    "io.capture.no_bone": {
        "ZH": "目标骨架「%s」里没有骨骼「%s」。",
        "EN": "The target armature “%s” has no bone “%s”.",
    },
    "io.capture.w_axis": {
        "ZH": "W 轴暂不支持取值。",
        "EN": "Capturing from the W axis is not supported yet.",
    },
    "io.capture.no_read_value": {
        "ZH": "这种读取方式没有可取的值。",
        "EN": "This read mode has no value to capture.",
    },
    "io.capture.no_pose_value": {
        "ZH": "变换类型「%s」没有骨骼姿态可取。",
        "EN": "Transform type “%s” has no bone pose to capture.",
    },
    "io.capture.undefined": {
        "ZH": "这个姿态下取不出值：父骨缩放为 0，或扭转角没有定义。",
        "EN": "No value can be captured in this pose: the parent bone's scale is 0 or the twist angle is undefined.",
    },
    "io.capture.warn_axis": {
        "ZH": "姿态不是纯绕 %s 轴的旋转，只取了绕该轴的转角，另有 %.1f° 这条约束表达不了。",
        "EN": "The pose is not a pure rotation about the %s axis; only the angle about that axis was captured, and a further %.1f° cannot be expressed by this constraint.",
    },
    "io.capture.warn_preview": {
        "ZH": "预览正在驱动被驱动骨骼，读到的是预览姿态；先清除预览再取值",
        "EN": "The preview is driving the driven bone, so the pose read is the preview pose; clear the preview before capturing",
    },
    "io.capture.captured": {"ZH": "已取 %s = %.2f%s", "EN": "Captured %s = %.2f%s"},
    "io.capture.done_with_warning": {"ZH": "%s。%s", "EN": "%s. %s"},
    "io.capture.done": {"ZH": "%s。", "EN": "%s."},
    "io.capture.readout_no_bone": {
        "ZH": "目标骨架里没有骨骼「%s」，读不到当前值",
        "EN": "The target armature has no bone “%s”, so the current value cannot be read",
    },
    "io.capture.readout": {
        "ZH": "当前读到 %.2f%s → 输出 %.2f%s",
        "EN": "Current reading %.2f%s → output %.2f%s",
    },
    "io.capture.readout_single": {
        "ZH": "（仅本驱动，各驱动输出相加）",
        "EN": " (this driver only; driver outputs add up)",
    },

    # ---- jcns_exporter.py ----
    "io.export.cone_not_cached": {
        "ZH": "这个文件有 %d 条 ConeInput，但当前根节点是旧版插件导入的，没有缓存它们；请重新导入后再导出。",
        "EN": "This file has %d ConeDrivers, but the current root was imported by an older version of the add-on and did not cache them; re-import the file and export again.",
    },
    "io.export.cone_bad_index": {
        "ZH": "约束「%s」引用了第 %d 个 ConeInput，但文件里只有 %d 个。",
        "EN": "Constraint “%s” refers to ConeInput %d, but the file has only %d.",
    },
    "io.export.tip": {
        "ZH": "把选中的 JCNS 集合导出为 .jcns 文件，版本与导入时相同",
        "EN": "Export the selected JCNS collection as a .jcns file, in the same version as when it was imported",
    },
    "io.export.clean_hashes.name": {"ZH": "清除冗余哈希", "EN": "Remove Unused Hashes"},
    "io.export.clean_hashes.tip": {
        "ZH": "删除已无约束引用的哈希。不勾选则保留原文件的全部哈希",
        "EN": "Delete hashes that no constraint refers to any more. When unchecked, all hashes of the original file are kept",
    },
    "io.export.no_root": {
        "ZH": "未检测到 JCNS 根节点，请先选中 JCNS 集合的根空物体。",
        "EN": "No JCNS root found; select the root Empty of a JCNS collection first.",
    },
    "io.export.no_entries": {
        "ZH": "没有找到任何条目，无内容可导出。",
        "EN": "No entries found; there is nothing to export.",
    },
    "io.export.reparse_failed": {
        "ZH": "重新解析源文件失败：%s",
        "EN": "Failed to parse the source file again: %s",
    },
    "io.export.source_missing_old": {
        "ZH": "源文件不存在：%s\n这个根节点是旧版插件导入的，请重新导入该文件。",
        "EN": "Source file does not exist: %s\nThis root was imported by an older version of the add-on; re-import the file.",
    },
    "io.export.source_missing_rebuild": {
        "ZH": "源文件缺失，按 Blender 里的数据重建文件头导出。",
        "EN": "The source file is missing; exporting with a file header rebuilt from the data in Blender.",
    },
    "io.export.old_no_data": {
        "ZH": "这个文件是旧版插件导入的，Blender 里没有重建所需的数据；请重新导入后再导出。",
        "EN": "This file was imported by an older version of the add-on, and Blender does not hold the data needed to rebuild it; re-import the file and export again.",
    },
    "io.export.write_failed": {"ZH": "写入失败：%s", "EN": "Write failed: %s"},
    "io.export.done_upgraded": {
        "ZH": "已导出「%s」（v%s → v%s）。",
        "EN": "Exported “%s” (v%s → v%s).",
    },
    "io.export.done_no_source": {
        "ZH": "已导出「%s」（源文件缺失，无法比对 MD5）。",
        "EN": "Exported “%s” (the source file is missing, so the MD5 cannot be compared).",
    },
    "io.export.done_same": {
        "ZH": "已导出「%s」—— 内容无变化（MD5 相同）。",
        "EN": "Exported “%s” — no change in content (same MD5).",
    },
    "io.export.done_changed": {
        "ZH": "已导出「%s」（MD5 %s… → %s…）",
        "EN": "Exported “%s” (MD5 %s… → %s…)",
    },

    # ---- jcns_importer.py ----
    "io.import.tip": {
        "ZH": "导入 RE Engine 的 JCNS 关节约束文件，每条约束生成一个空物体",
        "EN": "Import an RE Engine JCNS joint-constraint file; each constraint becomes an Empty",
    },
    "io.import.armature.name": {"ZH": "目标骨架", "EN": "Target Armature"},
    "io.import.armature.tip": {
        "ZH": "导入时用于把哈希还原成骨骼名的骨架",
        "EN": "The armature used to turn hashes back into bone names on import",
    },
    "io.import.resolve.name": {"ZH": "还原骨骼名", "EN": "Resolve Bone Names"},
    "io.import.resolve.tip": {
        "ZH": "用所选骨架把哈希还原成骨骼名",
        "EN": "Turn hashes back into bone names using the selected armature",
    },
    "io.import.parse_failed": {"ZH": "解析失败：%s", "EN": "Parse failed: %s"},
    "io.import.not_exportable": {
        "ZH": "无法导入 —— 这个文件含有写入器无法完整还原的结构，编辑了也没法导出：\n",
        "EN": "Cannot import — this file contains structures the writer cannot fully reproduce, so edits could not be exported:\n",
    },
    "io.import.upgrade_failed": {"ZH": "无法升级到 v%s：%s", "EN": "Cannot upgrade to v%s: %s"},
    "io.import.upgrade_not_exportable": {
        "ZH": "升级到 v%d 后无法完整还原：\n",
        "EN": "Cannot be fully reproduced after upgrading to v%d:\n",
    },
    "io.import.file_not_found": {"ZH": "找不到文件：%s", "EN": "File not found: %s"},
    "io.import.armature_none": {"ZH": "无", "EN": "None"},
    "io.import.summary": {
        "ZH": "已导入 %d 条约束 → 「%s」（骨架：%s）",
        "EN": "Imported %d constraints → “%s” (armature: %s)",
    },
    "io.import.summary_upgraded": {
        "ZH": "，已从 v%s 升级到 v%s",
        "EN": ", upgraded from v%s to v%s",
    },
    "io.import.summary_pending": {
        "ZH": "；导出前先设置目标骨架",
        "EN": "; set the target armature before exporting",
    },

    # ---- modules/jcns_upgrade.py ----
    "io.upgrade.no_step": {
        "ZH": "没有 v%s → v%s 的升级步骤。",
        "EN": "There is no upgrade step from v%s to v%s.",
    },
    "io.upgrade.v29_cone": {
        "ZH": "v29 文件不该有 ConeInput。",
        "EN": "A v29 file should not have ConeDrivers.",
    },
    "io.upgrade.need_skeleton": {
        "ZH": "升级到 v102 要重新算读取骨表，需要目标骨架。",
        "EN": "Upgrading to v102 requires re-deriving the ReadJointTable, which needs a target armature.",
    },
    "io.upgrade.missing_bones": {
        "ZH": "目标骨架里找不到这些骨骼，无法算读取骨表：%s",
        "EN": "These bones are not in the target armature, so the ReadJointTable cannot be derived: %s",
    },
    "io.new.label": {"ZH": "新建 JCNS", "EN": "New JCNS"},
    "io.new.tip": {
        "ZH": "新建一个空的 JCNS 集合，版本为所选游戏的最新版；之后可新增条目再导出",
        "EN": "Create an empty JCNS collection in the newest version of the chosen game; add entries, then export",
    },
    "io.new.game": {"ZH": "游戏", "EN": "Game"},
    "io.new.game_wilds": {"ZH": "怪物猎人荒野 (v102)", "EN": "Monster Hunter Wilds (v102)"},
    "io.new.game_requiem": {"ZH": "Resident Evil Requiem (v35)", "EN": "Resident Evil Requiem (v35)"},
    "io.new.done": {"ZH": "已新建「%s」（v%d）。", "EN": "Created “%s” (v%d)."},
    "io.export.done_new": {"ZH": "已导出「%s」。", "EN": "Exported “%s”."},
}
