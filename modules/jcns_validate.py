"""
jcns_validate.py
----------------
Pre-export safety checks — also used to gate import.

The writer rebuilds a JCNS file from scratch: it emits ConstraintInfo, one
ConstraintSource_v2 per constraint (with its ComplexMappingInfo), the string
pools, the dependency table, ObjectSettings, the section table, the hash table,
and the RotExpression / Material / JXG / Aim / SkinConstraint sections.  Anything it does *not* emit is silently dropped from the output while
the corresponding header pointer and count are copied verbatim from the source
file — leaving a dangling pointer into unrelated data.

That failure mode is invisible: the file writes fine, MD5 changes, and the
breakage only shows up in-game.  check_exportable() turns it into a loud refusal.

This is an editor, not a viewer: the importer runs the same check on the fresh
parse and refuses to even open a file that could never be exported back, rather
than let the user edit for a while before finding out it was pointless.

Kept free of any `bpy` import so it can be run from a plain Python test harness.
"""


# Structures the writer cannot currently reproduce.  Each entry is
# (human-readable name, callable(parser) -> count of offending items).
def _count_truncated_sources(parser):
    """Constraints whose declared SourceCount does not match the blocks actually read.

    Multi-source constraints are fully supported, but a file can declare a
    SourceCount that runs past EOF (hand-edited files do this), in which case the
    parser reads fewer blocks than claimed and exporting would silently drop them.
    """
    return sum(1 for c in parser.constraints
               if len(c.get('sources', [])) != c.get('SourceCount_parent', 0))


def _count_cone_driver_info(parser):
    return sum(1 for c in parser.constraints
               if c.get('ConeDriverInfoCount', 0) or c.get('ConeDriverInfoOffset', 0))


def _header_count(parser, field):
    return getattr(parser, 'header', {}).get(field, 0)


def check_exportable(parser):
    """
    Return a list of human-readable problem descriptions.  Empty list == safe to export.

    Every check here corresponds to a structure that is present in the source file
    but would be lost or corrupted by JCNSWriter.build_lossless().  The in-place
    writer (every version but v102) keeps all bytes it does not re-pack, so the
    "section not reproduced" checks only apply to the rebuild writer.
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
        names = [c.get('TargetBoneName') or '?' for c in parser.constraints
                 if len(c.get('sources', [])) != c.get('SourceCount_parent', 0)]
        problems.append(
            f"{n} 条约束声明的驱动源数量超过文件实际内容："
            f"{'、'.join(names)}。该文件本身已损坏（SourceCount 超出可用数据），"
            "导出会静默丢失缺失的驱动源。"
        )

    if in_place:
        return problems

    n = _count_cone_driver_info(parser)
    if n:
        problems.append(
            f"{n} 条约束引用了 ConeDriverInfo。写入器只会照抄原来的绝对偏移，"
            "却不会搬运它指向的数据。"
        )

    for field, label in (
        ('ConeDriverCount',           "ConeDriver 表"),
    ):
        count = _header_count(parser, field)
        if count:
            problems.append(
                f"文件含有 {count} 条 {label} 记录（{field}）。写入器不会输出这个段落，"
                "却会原样复制它的头部指针 —— 导出的文件会指向无关数据。"
            )

    # RotExpression / Aim / SkinConstraint / ObjectSettings are only reproduced from
    # a freshly re-parsed source file — nothing in Blender caches their content
    # (at most a read-only display Empty), so the stub builder used when the source
    # file is missing leaves them empty. That is correct for a file that never had
    # any, but silent data loss for one that did.  (ComplexMappingInfo is caught by
    # the writer: its count survives in Blender, its data does not.)
    if getattr(parser, 'is_stub', False):
        for field, label in (
            ('RotExpressionInfoCount', "RotExpression 表"),
            ('AimConstraintCount',     "Aim 约束表"),
            ('SkinConstraintCount',    "SkinConstraint 表"),
            ('ObjectSettingCount',     "ObjectSettings 表"),
        ):
            count = _header_count(parser, field)
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
    `_orig_target_name`, `_orig_name`, `_offset`).
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
        label = c.get('_orig_target_name') or f'#{i}'
        if c.get('TargetBoneName', '') != c.get('_orig_target_name', ''):
            problems.append(f"{head}：约束 {label} 的目标骨骼被改成了 "
                            f"「{c.get('TargetBoneName', '')}」（不能改名）。")
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
