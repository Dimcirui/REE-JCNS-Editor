"""
jcns_kinds.py
-------------
What each kind of JCNS entry is, and what may be done to it.

The UI's tabs, + / - / up / down buttons, lock banner and preview availability
are driven from this table.  How a kind is edited or previewed lives in
jcns_editors.py and jcns_preview.py; this module only routes to them.

Kept free of `bpy` so the rules can be tested offline (tests/test_kinds.py).

`Kind.id` is the value stored in JCNSConstraintProperties.constraint_type.
"""

from dataclasses import dataclass

from jcns_i18n import T


# ── Kinds ───────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Kind:
    id: str               # constraint_type value
    label_fn: object      # () -> label shown in tabs / headers, in the active language
    icon: str             # Blender icon id
    tab: bool             # has a tab in the browser
    ordered: bool         # entry order is known to matter (up / down allowed)
    addable: bool         # a new entry can be created from the UI
    preview: str          # preview backend id, '' when the kind cannot be previewed
    confidence: str       # how well the engine behaviour is understood
    summary_fn: object    # () -> one line saying what the section is for

    @property
    def label(self):
        return self.label_fn()

    @property
    def summary(self):
        return self.summary_fn()


# `ordered` is true only for Ranges: several Ranges on one channel -> the last one
# wins.  Other sections keep file order on export but offer no reordering.
KINDS = (
    Kind('Outputs', lambda: T("core.kinds.outputs.label"), 'DRIVER', tab=True, ordered=True, addable=True,
         preview='driver', confidence="实机验证",  # ui-copy: internal
         summary_fn=lambda: T("core.kinds.outputs.summary")),
    Kind('Multi', lambda: T("core.kinds.multi.label"), 'MOD_VERTEX_WEIGHT', tab=True, ordered=False, addable=True,
         preview='constraint', confidence="高（统计推断）",  # ui-copy: internal
         summary_fn=lambda: T("core.kinds.multi.summary")),
    Kind('Aim', lambda: T("core.kinds.aim.label"), 'CON_TRACKTO', tab=True, ordered=False, addable=True,
         preview='constraint', confidence="主体高，字段中",  # ui-copy: internal
         summary_fn=lambda: T("core.kinds.aim.summary")),
    Kind('RotExpression', lambda: T("core.kinds.rotexpr.label"), 'DRIVER_ROTATIONAL_DIFFERENCE',
         tab=True, ordered=False, addable=True,
         preview='constraint', confidence="中高（统计推断）",  # ui-copy: internal
         summary_fn=lambda: T("core.kinds.rotexpr.summary")),
    Kind('Material', lambda: T("core.kinds.material.label"), 'MATERIAL', tab=True, ordered=False,
         addable=True,
         preview='', confidence="低",  # ui-copy: internal
         summary_fn=lambda: T("core.kinds.material.summary")),
    Kind('JointExprGraph', lambda: T("core.kinds.jxg.label"), 'FILE_FOLDER', tab=True, ordered=False,
         addable=False, preview='', confidence="低",  # ui-copy: internal
         summary_fn=lambda: T("core.kinds.jxg.summary")),
    # Anything the importer does not produce.  Exported untouched.
    Kind('Unknown', lambda: T("core.kinds.unknown.label"), 'QUESTION', tab=False, ordered=False,
         addable=False, preview='', confidence="未知",  # ui-copy: internal
         summary_fn=lambda: T("core.kinds.unknown.summary")),
)

_BY_ID = {k.id: k for k in KINDS}
TAB_KINDS = tuple(k for k in KINDS if k.tab)


def kind_of(constraint_type):
    """The Kind for a stored constraint_type.  '' is an old spelling of Ranges."""
    if not constraint_type:
        return _BY_ID['Outputs']
    return _BY_ID.get(constraint_type, _BY_ID['Unknown'])


# ── What may be done ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class FileState:
    """The facts about one JCNS file that decide what is editable."""
    version: int = 0
    rebuild: bool = True            # the exporter rebuilds this version (v35, v102)
    sections_cached: bool = True    # the importer stored Multi/Aim/RotExpr data in Blender
    has_armature: bool = False      # a target armature is set
    has_read_table: bool = False    # the file ships a ReadJointTable (needs the skeleton to re-derive)


@dataclass(frozen=True)
class Caps:
    """What the UI may offer for one kind in one file.

    `why` maps an action to the reason it is unavailable; an action that is
    allowed has no entry.  `banner` is the one-line summary shown above the list
    (empty when nothing is restricted).
    """
    can_edit: bool
    can_add: bool
    can_remove: bool
    can_move: bool
    banner: str = ''
    why: tuple = ()

    def reason(self, action):
        return dict(self.why).get(action, '')


def _caps(_edit, _add, _remove, _move, _banner='', **why):
    """Positional flags first; `why` keywords are action names (edit/add/remove/move)."""
    return Caps(_edit, _add, _remove, _move, _banner, tuple(why.items()))


def complex_mapping_editable(st):
    """(editable, reason) for ComplexMapping keyframes: they belong to a Ranges
    source but are rebuilt and cached like the non-Ranges sections."""
    if not st.rebuild:
        return False, T("core.kinds.cm_locked", st.version)
    if not st.sections_cached:
        return False, T("core.kinds.cm_old_import")
    return True, ''


def capabilities(kind_id, st):
    """Caps of a kind under the file state `st`."""
    k = kind_of(kind_id)
    v = st.version

    if k.id == 'Unknown':
        msg = T("core.kinds.unknown_msg")
        return _caps(False, False, False, False, msg,
                     edit=msg, add=msg, remove=msg, move=msg)

    if k.id == 'Outputs':
        if not st.rebuild:
            msg = T("core.kinds.ranges_values_only", v)
            return _caps(True, False, False, False, msg,
                         add=msg, remove=msg, move=msg)
        return _caps(True, True, True, True)

    if k.id in ('Multi', 'Aim', 'RotExpression'):
        if not st.rebuild:
            msg = T("core.kinds.inplace_locked", v)
            return _caps(False, False, False, False, msg,
                         edit=msg, add=msg, remove=msg, move=msg)
        if v < 35:
            # the rebuild writes no section but Ranges before v35; a file that has one is not rebuilt
            msg = T("core.kinds.no_section_before_35", v)
            return _caps(False, False, False, False, msg,
                         edit=msg, add=msg, remove=msg, move=msg)
        if not st.sections_cached:
            msg = T("core.kinds.old_import")
            return _caps(False, False, False, False, msg,
                         edit=msg, add=msg, remove=msg, move=msg)
        # Count changes need derived data re-computed on export.
        block = ''
        if k.id in ('Multi', 'Aim') and st.has_read_table and not st.has_armature:
            block = T("core.kinds.need_armature")
        move_why = T("core.kinds.no_reorder")
        why = {'move': move_why}
        if block:
            why.update(add=block, remove=block)
        return _caps(True, not block, not block, False, block, **why)

    if k.id == 'Material':
        if not st.rebuild:
            msg = T("core.kinds.material_hash_only", v)
            return _caps(True, False, False, False, msg,
                         add=msg, remove=msg, move=msg)
        return _caps(True, True, True, False, '', move=T("core.kinds.no_reorder"))

    if k.id == 'JointExprGraph':
        if not st.rebuild:
            msg = T("core.kinds.jxg_locked", v)
            return _caps(False, False, False, False, msg,
                         edit=msg, add=msg, remove=msg, move=msg)
        # one path on the root, not an entry list: nothing to add, remove or move
        return _caps(True, False, False, False, '')

    raise AssertionError(k.id)      # KINDS and this function must stay in step
