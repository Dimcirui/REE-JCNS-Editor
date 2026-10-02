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

from jcns_i18n import T


def _count_truncated_sources(parser):
    """Constraints whose declared SourceCount does not match the blocks actually read
    (a SourceCount running past EOF; exporting would drop the missing sources)."""
    return sum(1 for c in parser.constraints
               if len(c.get('sources', [])) != c.get('JointDriverCount', 0))


def _count_unread_cone_driver(parser):
    """Constraints whose ConeDriver list is not fully held by the parser."""
    return sum(1 for c in parser.constraints
               if c.get('ConeDriverCount', 0) != len(c.get('ConeDriver') or []))


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
        problems.append(T("core.validate.stub", parser.header.get('Version', '?')))
        return problems

    n = _count_truncated_sources(parser)
    if n:
        names = [c.get('ObjectName') or '?' for c in parser.constraints
                 if len(c.get('sources', [])) != c.get('JointDriverCount', 0)]
        problems.append(T("core.validate.truncated_sources", n, T("core.list_sep").join(names)))

    if in_place:
        return problems

    # The rebuild writer re-emits ConeDrivers and every ConeDriver list, but
    # only what the parser (or Blender) actually holds.
    n = _count_unread_cone_driver(parser)
    if n:
        problems.append(T("core.validate.unread_cone_driver", n))
    count = _header_count(parser, 'ConeInputCount')
    if count and len(getattr(parser, 'cone_inputs', [])) != count:
        problems.append(T("core.validate.cone_count", count,
                          len(getattr(parser, 'cone_inputs', []))))

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
    orig_n = parser.header.get('OutputCount', 0)

    cns = parser.constraints
    if len(cns) != orig_n or any('_rec' not in c for c in cns):
        problems.append(T("core.validate.inplace_count", v, orig_n, len(cns)))
        return problems

    for i, c in enumerate(cns):
        label = c.get('_orig_object_name') or f'#{i}'
        if c.get('ObjectName', '') != c.get('_orig_object_name', ''):
            problems.append(T("core.validate.inplace_object", v, label, c.get('ObjectName', '')))
        if c.get('PropertyName', '') != c.get('_orig_property_name', ''):
            problems.append(T("core.validate.inplace_property", v, label, c.get('PropertyName', '')))
        srcs = c.get('sources', [])
        if len(srcs) != c['_rec']['JointDriverCount'] or any('_rec' not in s for s in srcs):
            problems.append(T("core.validate.inplace_source_count", v, label))
            continue
        for s in srcs:
            if s.get('SourceName', '') != s.get('_orig_name', ''):
                problems.append(T("core.validate.inplace_source_name", v, label,
                                  s.get('_orig_name', ''), s.get('SourceName', '')))
            if s.get('ComplexMappingInfoCount', 0) != s['_rec'].get('ComplexMappingInfoCount', 0):
                problems.append(T("core.validate.inplace_complex_count", v, label))

    mats = getattr(parser, 'material_cns', [])
    orig_mats = parser.header.get('MaterialConstraintInfoCount', 0)
    if len(mats) != orig_mats or any('_offset' not in m for m in mats):
        problems.append(T("core.validate.inplace_mat_count", v, orig_mats, len(mats)))
    else:
        for i, m in enumerate(mats):
            if m.get('JointHash') != m.get('_orig_joint_hash'):
                problems.append(T("core.validate.inplace_mat_bone", v, i))

    jxg = getattr(parser, 'joint_export_graph', None)
    had_jxg = bool(parser.header.get('JointExprGraphInfoEntry', 0))
    if (jxg is not None) != had_jxg or (jxg and jxg.get('path') != jxg.get('_orig_path')):
        problems.append(T("core.validate.inplace_jxg", v))
    return problems


def format_problems(problems, filename=''):
    """Render check_exportable() output as a single multi-line string."""
    if filename:
        head = T("core.validate.problems_head_named", filename, len(problems))
    else:
        head = T("core.validate.problems_head", len(problems))
    return "\n".join([head] + [f"  * {p}" for p in problems])
