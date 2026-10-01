"""
jcns_validate.py
----------------
Pre-export safety checks, also used to gate import.

The rebuild writer drops any structure it does not emit while the header's
pointer and count for it are copied from the source file, leaving a dangling
pointer that only breaks in-game.  check_exportable() turns that into a refusal.
The importer runs the same check on the fresh parse, so a file that could never
be exported back is not opened at all.

Kept free of any `bpy` import so it can be run from a plain Python test harness.
"""


def _count_truncated_sources(parser):
    """Constraints whose declared SourceCount does not match the blocks actually read
    (a SourceCount running past EOF; exporting would drop the missing sources)."""
    return sum(1 for c in parser.constraints
               if len(c.get('sources', [])) != c.get('SourceCount_parent', 0))


def _count_unread_cone_info(parser):
    """Constraints whose ConeDriverInfo list is not fully held by the parser."""
    return sum(1 for c in parser.constraints
               if c.get('ConeDriverInfoCount', 0) != len(c.get('ConeDriverInfo') or []))


def _header_count(parser, field):
    return getattr(parser, 'header', {}).get(field, 0)


def check_exportable(parser):
    """
    Return a list of human-readable problem descriptions.  Empty list == safe to export.

    The in-place writer keeps all bytes it does not re-pack, so the "section not
    reproduced" checks apply only to the rebuild writer (JCNSWriter.build_lossless).
    """
    problems = []
    in_place = getattr(parser, 'write_mode', 'rebuild') == 'inplace'

    if in_place and getattr(parser, 'is_stub', False):
        problems.append(
            f"v{parser.header.get('Version', '?')} 只能在原文件上就地回写，"
            "但源文件已找不到。请找回源文件后再导出。"
        )
        return problems

    n = _count_truncated_sources(parser)
    if n:
        names = [c.get('ObjectName') or '?' for c in parser.constraints
                 if len(c.get('sources', [])) != c.get('SourceCount_parent', 0)]
        problems.append(
            f"{n} 条约束声明的驱动源数量超过文件实际内容："
            f"{'、'.join(names)}。该文件本身已损坏（SourceCount 超出可用数据），"
            "导出会静默丢失缺失的驱动源。"
        )

    if in_place:
        return problems

    # The rebuild writer re-emits ConeDrivers and every ConeDriverInfo list, but
    # only what the parser (or Blender) actually holds.
    n = _count_unread_cone_info(parser)
    if n:
        problems.append(
            f"{n} 条约束的 ConeDriverInfo 数量与读到的数据不符，重建会丢掉它们。"
        )
    count = _header_count(parser, 'ConeDriverCount')
    if count and len(getattr(parser, 'cone_drivers', [])) != count:
        problems.append(
            f"文件含有 {count} 条 ConeDriver，但只读到了 {len(getattr(parser, 'cone_drivers', []))} 条"
            "（只认 v35 起的布局，或源文件缺失而 Blender 里没有缓存），重建会丢掉它们。"
        )

    # When the source file is missing, the stub parser has RotExpression / Aim /
    # SkinConstraint / ObjectSettings only if Blender cached them
    # (parser.sections_from_blender); otherwise a non-zero header count means the
    # section would be dropped.  ComplexMappingInfo is checked by the writer.
    if getattr(parser, 'is_stub', False):
        from_blender = getattr(parser, 'sections_from_blender', False)
        for field, label, attr in (
            ('RotExpressionInfoCount', "RotExpression 表", 'rot_expressions'),
            ('AimConstraintCount',     "Aim 约束表", 'aim_constraints'),
            ('SkinConstraintCount',    "SkinConstraint 表", 'skin_constraints'),
            ('ObjectSettingCount',     "ObjectSettings 表", 'object_settings'),
        ):
            count = _header_count(parser, field)
            if field == 'ObjectSettingCount' and len(getattr(parser, attr, [])) == count:
                continue
            if from_blender and field != 'ObjectSettingCount':
                continue
            if count:
                problems.append(
                    f"源文件缺失，只能用缓存的文件头导出；但原文件含有 {count} 条 "
                    f"{label} 记录（{field}），Blender 里没有缓存它们的内容，导出会"
                    "整段丢失且不会报错。请找回源文件后再导出。"
                )

    return problems


def check_in_place_edits(parser):
    """
    For in-place versions: the edits the writer cannot express without moving
    data.  Call after the exporter has patched parser.constraints.  Empty == OK.

    Only values change in place; the constraint list, each constraint's source
    list, every bone name and the material/JXG entries must match the original
    file one-to-one (the parser tags each record with its origin: `_rec`,
    `_orig_object_name`, `_orig_name`, `_offset`).
    """
    problems = []
    v = parser.header.get('Version', '?')
    head = f"v{v} 只支持就地修改数值"
    orig_n = parser.header.get('ConstraintCount', 0)

    cns = parser.constraints
    if len(cns) != orig_n or any('_rec' not in c for c in cns):
        problems.append(f"{head}：约束数量从 {orig_n} 变成了 {len(cns)}（不能新增或删除约束）。")
        return problems

    for i, c in enumerate(cns):
        label = c.get('_orig_object_name') or f'#{i}'
        if c.get('ObjectName', '') != c.get('_orig_object_name', ''):
            problems.append(f"{head}：约束 {label} 的目标骨骼被改成了 "
                            f"「{c.get('ObjectName', '')}」（不能改名）。")
        if c.get('PropertyName', '') != c.get('_orig_property_name', ''):
            problems.append(f"{head}：约束 {label} 的目标属性被改成了 "
                            f"「{c.get('PropertyName', '')}」（不能改名）。")
        srcs = c.get('sources', [])
        if len(srcs) != c['_rec']['SourceCount_parent'] or any('_rec' not in s for s in srcs):
            problems.append(f"{head}：约束 {label} 的驱动源数量变了（不能增删驱动源）。")
            continue
        for s in srcs:
            if s.get('SourceName', '') != s.get('_orig_name', ''):
                problems.append(f"{head}：约束 {label} 的驱动源「{s.get('_orig_name', '')}」"
                                f"被改成了「{s.get('SourceName', '')}」（不能改名）。")
            if s.get('ComplexMappingInfoCount', 0) != s['_rec'].get('ComplexMappingInfoCount', 0):
                problems.append(f"{head}：约束 {label} 的 ComplexMappingInfoCount 变了。")

    mats = getattr(parser, 'material_cns', [])
    orig_mats = parser.header.get('MaterialConstraintInfoCount', 0)
    if len(mats) != orig_mats or any('_offset' not in m for m in mats):
        problems.append(f"{head}：材质约束数量从 {orig_mats} 变成了 {len(mats)}。")
    else:
        for i, m in enumerate(mats):
            if m.get('JointHash') != m.get('_orig_joint_hash'):
                problems.append(f"{head}：材质约束 #{i} 的骨骼被改了（不能改骨骼）。")

    jxg = getattr(parser, 'joint_export_graph', None)
    had_jxg = bool(parser.header.get('JointExportGraphInfoEntry', 0))
    if (jxg is not None) != had_jxg or (jxg and jxg.get('path') != jxg.get('_orig_path')):
        problems.append(f"{head}：JointExportGraph 路径不能修改。")
    return problems


def format_problems(problems, filename=''):
    """Render check_exportable() output as a single multi-line string."""
    head = f"无法安全导出{'「' + filename + '」' if filename else ''} —— "
    head += f"发现 {len(problems)} 处不支持的结构："
    return "\n".join([head] + [f"  * {p}" for p in problems])
