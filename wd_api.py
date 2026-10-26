"""
wd_api.py
---------
Export a JCNS collection to file bytes in memory, for other add-ons.  Nothing is
written to disk and no Blender data changes; the field names it reads are listed in
docs/wd-interface.md.
"""

API_VERSION = 2
COLLECTION_TYPES = ("RE_JCNS_COLLECTION", "RE_JXG_COLLECTION")

# MH Wilds' version, the default target.
DEFAULT_VERSION = 102


class ExportError(Exception):
    """The export failed; the message is a list of problems for the user."""


def export_bytes(collection, version=None) -> bytes:
    """The file for `collection`: a .jcns in `version` (Wilds' when None), or for an expression
    graph collection (~TYPE RE_JXG_COLLECTION) its .jntexprgraph, `version` ignored.

    A root that can be rebuilt is built from its stored data alone; one written in place
    (versions other than 21 / 22 / 35 / 36 / 102, or a file the rebuild cannot reproduce)
    patches its source file, which must still exist.
    """
    if collection.get("~TYPE") == "RE_JXG_COLLECTION":
        from .jxg_editor import ExportRefused as JXGRefused, export_bytes as jxg_bytes, tree_of_collection
        _head, tree = tree_of_collection(collection)
        if tree is None:
            raise ExportError("%s: no expression graph in this collection" % collection.name)
        try:
            return jxg_bytes(tree)
        except JXGRefused as exc:
            raise ExportError(str(exc)) from None

    from . import get_jcns_root_from_collection
    from .jcns_exporter import (ExportRefused, build_export, _root_version, CONVERTIBLE_VERSIONS)

    root, rp = get_jcns_root_from_collection(collection)
    if root is None:
        raise ExportError("%s: no JCNS root Empty in this collection" % getattr(collection, 'name', collection))
    target = DEFAULT_VERSION if version is None else int(version)
    own = _root_version(rp)
    if target != own and not (own in CONVERTIBLE_VERSIONS and target in CONVERTIBLE_VERSIONS):
        raise ExportError("%s: v%d cannot be exported as v%d" % (collection.name, own, target))

    try:
        parser, _state, _warnings = build_export(root, target, use_source=False)
    except ExportRefused as exc:
        raise ExportError(str(exc)) from None

    from jcns_writer import JCNSWriter
    try:
        return JCNSWriter(parser, rp.source_filepath or collection.name).build_bytes()
    except Exception as exc:
        raise ExportError("%s: %s" % (collection.name, exc)) from exc
