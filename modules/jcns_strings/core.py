"""Strings of the bpy-free modules: kinds, preview_plan, schema, parser, sections, writer, validate, source_read."""

# Shared head of every in-place edit refusal in jcns_validate.check_in_place_edits.
_INPLACE = {"ZH": "v%s 只支持就地修改数值：", "EN": "v%s supports in-place value edits only: "}


def _inplace(zh, en):
    return {"ZH": _INPLACE["ZH"] + zh, "EN": _INPLACE["EN"] + en}


STRINGS = {
    # ── shared ─────────────────────────────────────────────────────────────
    "core.list_sep": {"ZH": "、", "EN": ", "},

    # ── jcns_kinds: labels and one-line summaries ─────────────────────────
    "core.kinds.ranges.label": {"ZH": "范围约束", "EN": "Ranges"},
    "core.kinds.ranges.summary": {
        "ZH": "驱动的读数经折线映射，写到被驱动的一个通道",
        "EN": "A source's reading is mapped through a polyline and written to one channel of the target"},
    "core.kinds.skin.label": {"ZH": "Skin 蒙皮", "EN": "Skin"},
    "core.kinds.skin.summary": {
        "ZH": "按蒙皮权重把附件骨钉在变形后的皮肤上",
        "EN": "Pins an attachment bone to the deformed skin by skin weights"},
    "core.kinds.aim.label": {"ZH": "Aim 瞄准", "EN": "Aim"},
    "core.kinds.aim.summary": {
        "ZH": "look-at：让一根骨的轴指向另一根骨",
        "EN": "look-at: points one bone's axis at another bone"},
    "core.kinds.rotexpr.label": {"ZH": "RotExpr 旋转表达式", "EN": "RotExpr"},
    "core.kinds.rotexpr.summary": {
        "ZH": "按轴乘系数把驱动的旋转拷贝给被驱动",
        "EN": "Copies the source's rotation to the target, scaled per axis"},
    "core.kinds.material.label": {"ZH": "Material 材质", "EN": "Material"},
    "core.kinds.material.summary": {
        "ZH": "骨骼驱动材质属性（如 Water_* 骨驱动 Liquid* 材质）",
        "EN": "Bones drive material properties (e.g. Water_* bones drive Liquid* materials)"},
    "core.kinds.jxg.label": {"ZH": "JXG 导出图", "EN": "JXG graph"},
    "core.kinds.jxg.summary": {
        "ZH": "一条 JointExportGraph 资源路径",
        "EN": "A JointExportGraph resource path"},
    "core.kinds.unknown.label": {"ZH": "未知", "EN": "Unknown"},
    "core.kinds.unknown.summary": {"ZH": "导出时原样保留", "EN": "Kept as is on export"},

    # ── jcns_kinds: why an action is unavailable ──────────────────────────
    "core.kinds.cm_locked": {
        "ZH": "v%s 只能就地回写，曲线已锁定",
        "EN": "v%s is write-in-place only; the curve is locked"},
    "core.kinds.cm_old_import": {
        "ZH": "旧版插件导入，重新导入后才能编辑曲线",
        "EN": "Imported by an older add-on version; re-import to edit the curve"},
    "core.kinds.unknown_msg": {
        "ZH": "类型未知，导出时原样保留",
        "EN": "Unknown type; kept as is on export"},
    "core.kinds.ranges_values_only": {
        "ZH": "v%s 只能改数值，不能增删、换序或改骨骼名",
        "EN": "v%s allows value edits only: no add, delete, reorder or bone renames"},
    "core.kinds.inplace_locked": {
        "ZH": "v%s 只能就地回写，已锁定",
        "EN": "v%s is write-in-place only; locked"},
    "core.kinds.no_section_before_35": {
        "ZH": "v%s 的这个分区不能新建",
        "EN": "This section cannot be created in v%s"},
    "core.kinds.old_import": {
        "ZH": "旧版插件导入，重新导入后可编辑",
        "EN": "Imported by an older add-on version; re-import to edit"},
    "core.kinds.need_armature": {
        "ZH": "先设置目标骨架，才能增删条目",
        "EN": "Set the target armature first to add or delete entries"},
    "core.kinds.no_reorder": {"ZH": "这一类不提供换序", "EN": "This kind cannot be reordered"},
    "core.kinds.material_hash_only": {
        "ZH": "v%s 只能改哈希和变换 ID",
        "EN": "v%s allows editing hashes and transform IDs only"},
    "core.kinds.no_create": {"ZH": "暂不支持新建", "EN": "Creating new entries is not supported yet"},
    "core.kinds.jxg_locked": {
        "ZH": "v%s 就地回写，路径已锁定",
        "EN": "v%s is written in place; the path is locked"},
    "core.kinds.jxg_single": {"ZH": "JXG 每个文件只有一条", "EN": "A file has only one JXG entry"},

    # ── jcns_preview_plan ─────────────────────────────────────────────────
    "core.plan.skin_no_bone": {"ZH": "没有对象骨骼", "EN": "No target bone"},
    "core.plan.skin_source_empty": {
        "ZH": "有一条驱动没填，已忽略", "EN": "A source is empty and was ignored"},
    "core.plan.skin_source_self": {
        "ZH": "驱动里含被驱动自己，已忽略",
        "EN": "The sources include the target itself; ignored"},
    "core.plan.skin_no_sources": {"ZH": "没有可用的驱动", "EN": "No usable sources"},
    "core.plan.aim_no_bone": {"ZH": "没有被瞄准的骨骼", "EN": "No bone to aim"},
    "core.plan.aim_no_target": {"ZH": "没有瞄准目标", "EN": "No aim target"},
    "core.plan.aim_same": {
        "ZH": "被瞄准的骨骼和瞄准目标是同一根",
        "EN": "The aimed bone and the aim target are the same bone"},
    "core.plan.aim_axis": {
        "ZH": "瞄准轴 (%.2f, %.2f, %.2f) 不是坐标轴，Blender 的阻尼追踪表示不了",
        "EN": "Aim axis (%.2f, %.2f, %.2f) is not a coordinate axis; Blender's Damped Track cannot represent it"},
    "core.plan.aim_type5": {
        "ZH": "类型 5 从父骨朝向起最短弧（丢掉静止姿态），预览从静止姿态起，会差静止姿态",
        "EN": "Type 5 takes the shortest arc from the parent's orientation (rest pose dropped); the preview starts from the rest pose, so it differs by the rest pose"},
    "core.plan.aim_type_other": {
        "ZH": "类型 %d 的引擎行为还会固定绕瞄准轴的翻滚，预览只做最短弧，翻滚会不同",
        "EN": "Type %d also fixes the roll around the aim axis in the engine; the preview only does the shortest arc, so the roll differs"},
    "core.plan.aim_offset": {"ZH": "旋转偏移不参与预览", "EN": "The rotation offset is not previewed"},
    "core.plan.aim_up": {"ZH": "辅助骨骼（up）不参与预览", "EN": "The up bone is not previewed"},
    "core.plan.aim_infl_range": {
        "ZH": "影响 %.2f 超出 0..1，预览按 %.0f 处理",
        "EN": "Influence %.2f is outside 0..1; the preview uses %.0f"},
    "core.plan.aim_infl_degenerate": {
        "ZH": "影响不为 1 时引擎的结果退化，预览按影响直接混合",
        "EN": "With influence other than 1 the engine result degenerates; the preview blends by influence directly"},
    "core.plan.rot_no_bone": {"ZH": "没有被驱动的骨骼", "EN": "No target bone"},
    "core.plan.rot_no_source": {"ZH": "没有驱动", "EN": "No source"},
    "core.plan.rot_same": {
        "ZH": "被驱动和驱动是同一根", "EN": "The target and the source are the same bone"},

    # ── jcns_validate ─────────────────────────────────────────────────────
    "core.validate.stub": {
        "ZH": "v%s 只能在原文件上就地回写，但源文件已找不到。请找回源文件后再导出。",
        "EN": "v%s can only be written in place on the original file, but the source file cannot be found. Locate the source file and export again."},
    "core.validate.truncated_sources": {
        "ZH": "%d 条约束声明的驱动数量超过文件实际内容：%s。该文件本身已损坏（SourceCount 超出可用数据），导出会丢失缺失的驱动。",
        "EN": "%d constraints declare more sources than the file contains: %s. The file itself is damaged (SourceCount exceeds the available data); exporting would drop the missing sources."},
    "core.validate.unread_cone_info": {
        "ZH": "%d 条约束的 ConeDriverInfo 数量与读到的数据不符，重建会丢掉它们。",
        "EN": "%d constraints have a ConeDriverInfo count that does not match the data read; a rebuild would drop them."},
    "core.validate.cone_count": {
        "ZH": "文件含有 %d 条 ConeDriver，但只读到了 %d 条（只认 v35 起的布局，或源文件缺失而 Blender 里没有缓存），重建会丢掉它们。",
        "EN": "The file has %d ConeDrivers but only %d were read (only layouts from v35 are recognised, or the source file is missing and Blender holds no cache); a rebuild would drop them."},
    "core.validate.inplace_count": {
        "ZH": _INPLACE["ZH"] + "约束数量从 %d 变成了 %d（不能新增或删除约束）。",
        "EN": _INPLACE["EN"] + "the constraint count changed from %d to %d (constraints cannot be added or deleted)."},
    "core.validate.inplace_object": {
        "ZH": _INPLACE["ZH"] + "约束 %s 的被驱动骨骼被改成了 「%s」（不能改名）。",
        "EN": _INPLACE["EN"] + "the target bone of constraint %s was changed to \"%s\" (renaming is not allowed)."},
    "core.validate.inplace_property": {
        "ZH": _INPLACE["ZH"] + "约束 %s 的目标属性被改成了 「%s」（不能改名）。",
        "EN": _INPLACE["EN"] + "the target property of constraint %s was changed to \"%s\" (renaming is not allowed)."},
    "core.validate.inplace_source_count": {
        "ZH": _INPLACE["ZH"] + "约束 %s 的驱动数量变了（不能增删驱动）。",
        "EN": _INPLACE["EN"] + "the source count of constraint %s changed (sources cannot be added or deleted)."},
    "core.validate.inplace_source_name": {
        "ZH": _INPLACE["ZH"] + "约束 %s 的驱动「%s」被改成了「%s」（不能改名）。",
        "EN": _INPLACE["EN"] + "in constraint %s, source \"%s\" was changed to \"%s\" (renaming is not allowed)."},
    "core.validate.inplace_complex_count": {
        "ZH": _INPLACE["ZH"] + "约束 %s 的 ComplexMappingInfoCount 变了。",
        "EN": _INPLACE["EN"] + "the ComplexMappingInfoCount of constraint %s changed."},
    "core.validate.inplace_mat_count": {
        "ZH": _INPLACE["ZH"] + "材质约束数量从 %d 变成了 %d。",
        "EN": _INPLACE["EN"] + "the material constraint count changed from %d to %d."},
    "core.validate.inplace_mat_bone": {
        "ZH": _INPLACE["ZH"] + "材质约束 #%d 的骨骼被改了（不能改骨骼）。",
        "EN": _INPLACE["EN"] + "the bone of material constraint #%d was changed (bones cannot be changed)."},
    "core.validate.inplace_jxg": {
        "ZH": _INPLACE["ZH"] + "JointExportGraph 路径不能修改。",
        "EN": _INPLACE["EN"] + "the JointExportGraph path cannot be changed."},
    "core.validate.problems_head": {
        "ZH": "无法安全导出 —— 发现 %d 处不支持的结构：",
        "EN": "Cannot export safely: %d unsupported structure(s) found:"},
    "core.validate.problems_head_named": {
        "ZH": "无法安全导出「%s」 —— 发现 %d 处不支持的结构：",
        "EN": "Cannot export \"%s\" safely: %d unsupported structure(s) found:"},

    # ── jcns_sections ─────────────────────────────────────────────────────
    "core.sections.need_armature_pending": {
        "ZH": "先设置目标骨架，才能算读取骨表。",
        "EN": "Set the target armature first to derive the ReadJointTable."},
    "core.sections.need_armature_changed": {
        "ZH": "改动了 Skin 或 Aim 的骨骼，要先设置目标骨架，才能重算读取骨表。",
        "EN": "Skin or Aim bones were changed; set the target armature first to re-derive the ReadJointTable."},
    "core.sections.missing_joints": {
        "ZH": "目标骨架里找不到这些骨骼，无法重算读取骨表：%s",
        "EN": "These bones are not in the target armature, so the ReadJointTable cannot be re-derived: %s"},
    "core.sections.skin_weight_sum": {
        "ZH": "Skin #%d（%s）权重和为 %.3f",
        "EN": "Skin #%d (%s): weights sum to %.3f"},

    # ── jcns_parser / jcns_writer / jcns_schema ───────────────────────────
    "core.parser.bad_version": {
        "ZH": "不支持的 JCNS 版本：%s（支持 %s）",
        "EN": "Unsupported JCNS version: %s (supported: %s)"},
    "core.parser.not_jcns": {
        "ZH": "不是 JCNS 文件（缺少 'jcns' 魔数）",
        "EN": "Not a JCNS file (missing the 'jcns' magic)"},
    "core.writer.cone_index": {
        "ZH": "约束「%s」引用了第 %d 个 ConeDriver，但文件里只有 %d 个。",
        "EN": "Constraint \"%s\" refers to ConeDriver #%d, but the file has only %d."},
    "core.writer.complex_count": {
        "ZH": "驱动「%s」的 ComplexMappingInfoCount=%s，但只有 %d 条映射数据（复制来的驱动不会带上原数据）。请把它改回 0 或恢复原驱动。",
        "EN": "Source \"%s\" has ComplexMappingInfoCount=%s but only %d mapping entries (a copied source does not bring the original data). Set it back to 0 or restore the original source."},
    "core.schema.game_19": {"ZH": "RE2/RE3/RE7 光追版", "EN": "RE2/RE3/RE7 ray tracing edition"},
    "core.schema.game_29": {"ZH": "MH Wilds（TU4 之前）", "EN": "MH Wilds (before TU4)"},
    "core.schema.game_102": {"ZH": "MH Wilds（TU4 之后）", "EN": "MH Wilds (after TU4)"},
    "core.schema.header_layout": {
        "ZH": "v%s 文件头布局与文件不符：按模板算出的表头结尾是 0x%X，但 ConeDriverTableEntry 指向 0x%X",
        "EN": "v%s header layout does not match the file: the header end computed from the template is 0x%X, but ConeDriverTableEntry points to 0x%X"},

    # ── jcns_source_read: ReadMode table (property / enum text) ──────────
    "core.read_mode.0.name": {"ZH": "位置", "EN": "Position"},
    "core.read_mode.0.desc": {
        "ZH": "相对父骨的位置分量（厘米），含静止偏移；多用于面部滑杆骨和武器部件（约 10%）",
        "EN": "Position component relative to the parent bone (centimetres), rest offset included; mostly used by face slider bones and weapon parts (about 10%)"},
    "core.read_mode.1.name": {"ZH": "欧拉角", "EN": "Euler"},
    "core.read_mode.1.desc": {
        "ZH": "相对父骨完整旋转（含静止姿态）的欧拉分量，分解顺序由 +27 欧拉顺序决定（约 6%）",
        "EN": "Euler component of the full rotation relative to the parent bone (rest pose included); the decomposition order comes from the +27 Euler order (about 6%)"},
    "core.read_mode.2.name": {"ZH": "缩放", "EN": "Scale"},
    "core.read_mode.2.desc": {
        "ZH": "缩放分量，静止时等于骨骼的静止缩放（通常为 1）（约 5%）",
        "EN": "Scale component; at rest it equals the bone's rest scale (usually 1) (about 5%)"},
    "core.read_mode.3.name": {"ZH": "摆动·扭转", "EN": "Swing·Twist"},
    "core.read_mode.3.desc": {
        "ZH": "绕 X 的摆动-扭转分解，q = 摆动·扭转：X 取扭转角，Y/Z 取摆动，含静止姿态；最常用（约 77%）",
        "EN": "Swing-twist decomposition about X, q = swing·twist: X is the twist angle, Y/Z are the swing, rest pose included; the most common (about 77%)"},
    "core.read_mode.4.name": {"ZH": "扭转·摆动", "EN": "Twist·Swing"},
    "core.read_mode.4.desc": {
        "ZH": "同摆动·扭转，但 q = 扭转·摆动（先摆动）：X 与前者相同，Y/Z 不同（约 1%）",
        "EN": "Same as swing·twist, but q = twist·swing (swing applied first): X equals the former, Y/Z differ (about 1%)"},
    "core.read_mode.5.name": {"ZH": "旋转向量", "EN": "Rotation vector"},
    "core.read_mode.5.desc": {
        "ZH": "旋转向量（转轴×角度）的分量，含静止姿态；常用于读大腿、驱动 ThighTwist 一类（约 2%）",
        "EN": "Component of the rotation vector (axis×angle), rest pose included; often used to read the thigh and drive ThighTwist and the like (about 2%)"},

    # ── jcns_source_read: engine rules shown in the Advanced panels ──────
    "core.rule.t0_add": {
        "ZH": "叠加：位置 = 静止偏移 + 输出，沿父骨的轴",
        "EN": "Add: position = rest offset + output, along the parent bone's axes"},
    "core.rule.t0_replace": {
        "ZH": "替换：所写轴的位置 = 输出，其余轴保留静止偏移",
        "EN": "Replace: the written axis's position = output; other axes keep the rest offset"},
    "core.rule.t1_add": {
        "ZH": "叠加：静止姿态 · Rz·Ry·Rx（XYZ 欧拉，与文件里各轴先后无关）",
        "EN": "Add: rest pose · Rz·Ry·Rx (XYZ Euler; independent of the order of the axes in the file)"},
    "core.rule.t1_replace": {
        "ZH": "替换：静止姿态的 XYZ 欧拉角里换掉所写的轴，其余轴保留",
        "EN": "Replace: the written axes replace those of the rest pose's XYZ Euler angles; other axes are kept"},
    "core.rule.t2": {
        "ZH": "所写轴的缩放 = 输出，其余轴保留静止缩放；bit0 不起作用",
        "EN": "The written axis's scale = output; other axes keep the rest scale; bit0 has no effect"},
    "core.rule.t4_add": {
        "ZH": "叠加：静止姿态 · 摆动(Y,Z) · 扭转(X)",
        "EN": "Add: rest pose · swing (Y,Z) · twist (X)"},
    "core.rule.t4_replace": {
        "ZH": "替换：静止姿态按摆动·扭转分解，换掉所写的轴，其余轴保留",
        "EN": "Replace: the rest pose is decomposed as swing·twist, the written axes are replaced, other axes are kept"},
    "core.rule.t5_add": {
        "ZH": "叠加：静止姿态 · 扭转(X) · 摆动(Y,Z)",
        "EN": "Add: rest pose · twist (X) · swing (Y,Z)"},
    "core.rule.t5_replace": {
        "ZH": "替换：静止姿态按扭转·摆动分解，换掉所写的轴，其余轴保留",
        "EN": "Replace: the rest pose is decomposed as twist·swing, the written axes are replaced, other axes are kept"},
    "core.rule.t6_add": {
        "ZH": "叠加：静止姿态 · 旋转向量（转轴 × 角度）",
        "EN": "Add: rest pose · rotation vector (axis × angle)"},
    "core.rule.t6_replace": {
        "ZH": "替换：静止姿态按旋转向量分解，换掉所写的轴，其余轴保留",
        "EN": "Replace: the rest pose is decomposed as a rotation vector, the written axes are replaced, other axes are kept"},
    "core.rule.t13_add": {
        "ZH": "叠加：静止姿态 · 绕所写轴转「输出」角",
        "EN": "Add: rest pose · rotation about the written axis by the \"output\" angle"},
    "core.rule.t13_replace": {
        "ZH": "替换：丢掉整个静止旋转，只剩绕所写轴的「输出」角",
        "EN": "Replace: the whole rest rotation is dropped, leaving only the \"output\" angle about the written axis"},
    "core.rule.t13_single": {
        "ZH": "每根骨只有一个：骨上最后一条 13/14 整条胜出，与它写哪个轴无关",
        "EN": "One per bone: the last 13/14 entry on the bone wins entirely, whichever axis it writes"},
    "core.rule.t14_add": {
        "ZH": "与 13 相同：静止姿态 · 绕所写轴转「输出」角，骨上最后一条 13/14 生效",
        "EN": "Same as 13: rest pose · rotation about the written axis by the \"output\" angle; the last 13/14 entry on the bone applies"},
    "core.rule.t14_replace": {
        "ZH": "与 13 相同：丢掉整个静止旋转",
        "EN": "Same as 13: the whole rest rotation is dropped"},
    "core.rule.unknown_target": {
        "ZH": "形变 / 材质类目标：具体作用未知，没有预览",
        "EN": "Deform / material target: effect unknown; no preview"},
    "core.rule.read_0": {
        "ZH": "读相对父骨的位置分量（厘米），静止偏移算在内",
        "EN": "Reads the position component relative to the parent bone (centimetres), rest offset included"},
    "core.rule.read_1": {
        "ZH": "读相对父骨完整旋转的欧拉分量（顺序 %s），静止姿态算在内",
        "EN": "Reads the Euler component of the full rotation relative to the parent bone (order %s), rest pose included"},
    "core.rule.read_2": {
        "ZH": "读缩放分量，静止缩放算在内（静止时就是静止缩放）",
        "EN": "Reads the scale component, rest scale included (at rest it equals the rest scale)"},
    "core.rule.read_3": {
        "ZH": "读相对父骨完整旋转绕 X 的摆动·扭转分解：X = 扭转角，Y/Z = 摆动",
        "EN": "Reads the swing·twist decomposition about X of the full rotation relative to the parent bone: X = twist angle, Y/Z = swing"},
    "core.rule.read_4": {
        "ZH": "同摆动·扭转，但先摆动后扭转：X 相同，Y/Z 不同",
        "EN": "Same as swing·twist, but swing first, then twist: X is the same, Y/Z differ"},
    "core.rule.read_5": {
        "ZH": "读相对父骨完整旋转的旋转向量（转轴 × 角度）分量",
        "EN": "Reads the rotation vector (axis × angle) component of the full rotation relative to the parent bone"},
    "core.rule.read_unknown": {"ZH": "未知的读取方式 %r", "EN": "Unknown read mode %r"},
    "core.rule.read_frame": {
        "ZH": "按参考系四元数 f 分解 f^-1·q·f：扭转轴变成 f·X",
        "EN": "Decomposed as f^-1·q·f with the reference-frame quaternion f: the twist axis becomes f·X"},
}
