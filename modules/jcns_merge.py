"""
jcns_merge.py
-------------
Plans for folding Ranges entries that drive one channel into a single
multi-source entry.

The engine sums the sources inside one entry, but when several entries write the
same (target, transform, axis) channel only the last one in file order counts.
Merging therefore changes behaviour (last-wins becomes a sum) and is always a
user action; this module only decides whether a merge is expressible and what the
result looks like.  No bpy import; entries are plain dicts (see ENTRY_FIELDS).

The merged entry takes the position of the group's last member.  That entry is
the one the engine already lets win, so every other entry keeps its place relative
to the winner; putting the result earlier would change which values the entries
in between find when they read a bone the winner writes.

Entries carry the joint-group count of the file (`group_count`: how many of the
next entries the engine folds into this one's target bone).  Removing members can
leave a count pointing at the wrong entries, so apply_plans() re-derives the
counts of every group that lost a member.
"""

from dataclasses import dataclass, field

from jcns_i18n import T

MAX_SOURCES = 255           # SourceCount is a uint8

# What makes two entries the same channel.
CHANNEL_FIELDS = ('target_bone', 'target_property', 'transform_type', 'target_axis')

# Entry-level fields that must agree for a lossless merge: (key, label string key).
ENTRY_FIELDS = (
    ('additive', "io.merge.field.additive"),
    ('flags_other', "io.merge.field.flags_other"),
    ('reserved_vec4', "io.merge.field.vec4"),
    ('unknown_float2', "io.merge.field.float2"),
    ('unknown_byte_72', "io.merge.field.unknown_byte_72"),
    ('unknown_byte_74', "io.merge.field.byte_74"),
    ('unknown_byte_75', "io.merge.field.byte_75"),
    ('reserved_tail', "io.merge.field.reserved_tail"),
)


@dataclass
class Conflict:
    field: str
    text: str


@dataclass
class MergePlan:
    indices: tuple                      # member positions in the entry list, file order
    ok: bool
    conflicts: list = field(default_factory=list)
    keep: int = -1                      # the member that survives: the last one
    remove: tuple = ()
    sources: list = field(default_factory=list)   # [(entry index, source index)] in merged order
    entry: dict = field(default_factory=dict)     # the merged entry

    def reason(self):
        """One line naming what blocks the merge; empty when it can go ahead."""
        return T("io.sep.clause").join(c.text for c in self.conflicts)

    def fields(self):
        return [c.field for c in self.conflicts]


@dataclass
class MergeResult:
    entries: list                       # entries after the merge, each with its `origin`
    applied: list                       # the plans that were applied


def channel_key(entry):
    return tuple(entry.get(k, '') for k in CHANNEL_FIELDS)


def _same(a, b):
    if isinstance(a, (tuple, list)) or isinstance(b, (tuple, list)):
        a, b = tuple(a), tuple(b)
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    if isinstance(a, float) or isinstance(b, float):
        return abs(a - b) <= 1e-6
    return a == b


def contested(entries):
    """Index tuples of the entries sharing a channel, file order, for every channel
    with more than one entry; channels come out in order of their first entry."""
    by_key = {}
    for i, e in enumerate(entries):
        by_key.setdefault(channel_key(e), []).append(i)
    return [tuple(v) for v in by_key.values() if len(v) > 1]


def channel_members(entries, index):
    """Positions of every entry on the channel of entries[index], file order."""
    key = channel_key(entries[index])
    return tuple(i for i, e in enumerate(entries) if channel_key(e) == key)


def plan_merge(entries, indices, complex_ok=True):
    """Plan for merging the entries at `indices` into one.

    `complex_ok` says whether ComplexMapping curves can be moved between entries
    in this file; a source that has one blocks the merge otherwise.
    """
    idx = tuple(sorted(set(indices)))
    plan = MergePlan(indices=idx, ok=False)
    if len(idx) < 2:
        plan.conflicts.append(Conflict('members', T("io.merge.only_one")))
        return plan
    members = [entries[i] for i in idx]
    first = members[0]

    for k in CHANNEL_FIELDS:
        if any(not _same(m.get(k), first.get(k)) for m in members[1:]):
            plan.conflicts.append(Conflict(k, T("io.merge.not_same_channel")))
            break

    if any(m.get('target_property') or m.get('property_hash', 0) for m in members):
        plan.conflicts.append(Conflict('target_property', T("io.merge.target_property")))

    differing = [T(label) for key, label in ENTRY_FIELDS
                 if any(not _same(m.get(key), first.get(key)) for m in members[1:])]
    if differing:
        plan.conflicts.append(Conflict('entry_fields', T("io.merge.fields_differ", T("io.sep.list").join(differing))))

    if any(m.get('cone_infos') for m in members):
        plan.conflicts.append(Conflict('cone_infos', T("io.merge.cone_infos")))

    if any(not m.get('sources') for m in members):
        plan.conflicts.append(Conflict('sources', T("io.merge.no_sources")))
    elif sum(len(m['sources']) for m in members) > MAX_SOURCES:
        plan.conflicts.append(Conflict('sources', T("io.merge.too_many_sources", MAX_SOURCES)))

    if not complex_ok and any(s.get('complex_mapping') for m in members for s in m.get('sources', ())):
        plan.conflicts.append(Conflict('complex_mapping', T("io.merge.complex_mapping")))

    plan.keep = idx[-1]
    plan.remove = idx[:-1]
    plan.sources = [(i, k) for i in idx for k in range(len(entries[i].get('sources', ())))]
    plan.entry = dict(entries[plan.keep])
    plan.entry['sources'] = [entries[i]['sources'][k] for i, k in plan.sources]
    plan.ok = not plan.conflicts
    return plan


def plan_all(entries, complex_ok=True):
    """A plan for every channel that has more than one entry."""
    return [plan_merge(entries, idx, complex_ok) for idx in contested(entries)]


def group_spans(entries):
    """[(leader, [members])] covering every entry, or None when the stored counts
    are not valid groups (the writer then re-derives all of them itself).

    A group is a leader with count N and the N entries after it, which share its
    target, property and transform type and carry count 0.
    """
    def ident(e):
        return (e.get('target_bone'), e.get('target_property', ''), e.get('transform_type'))

    spans, i, n = [], 0, len(entries)
    while i < n:
        k = entries[i].get('group_count', 0)
        members = list(range(i + 1, i + 1 + k))
        if i + 1 + k > n or any(ident(entries[m]) != ident(entries[i])
                                or entries[m].get('group_count', 0) for m in members):
            return None
        spans.append((i, members))
        i += k + 1
    return spans


def apply_plans(entries, plans):
    """Entries after carrying out every plan that is ok.

    Each surviving entry has `origin` (its position in `entries`).  A merged entry
    keeps the last member's fields and gets every member's sources in order.
    `group_count` is re-derived for every group that lost a member: its first
    surviving entry leads and counts the others.
    """
    applied = [p for p in plans if p.ok]
    seen = set()
    for p in applied:
        if seen & set(p.indices):
            raise ValueError(T("io.merge.overlap"))
        seen |= set(p.indices)

    removed = {i for p in applied for i in p.remove}
    merged = {p.keep: p for p in applied}
    counts = [e.get('group_count', 0) for e in entries]
    spans = group_spans(entries)
    if spans is not None:
        for leader, members in spans:
            alive = [i for i in [leader] + members if i not in removed]
            for n, i in enumerate(alive):
                counts[i] = len(alive) - 1 if n == 0 else 0

    out = []
    for i, e in enumerate(entries):
        if i in removed:
            continue
        e = dict(merged[i].entry) if i in merged else dict(e)
        e['group_count'] = counts[i]
        e['origin'] = i
        out.append(e)
    return MergeResult(out, applied)
