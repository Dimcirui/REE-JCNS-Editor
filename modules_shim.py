"""
modules_shim.py
---------------
Single place that puts `modules/` on sys.path and hands back the pure-Python
helpers living there.  The getters cache the module so the driver-namespace
function reaches the evaluator without a path check on every evaluation.
"""

import os
import sys

_MODULES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "modules")
if _MODULES not in sys.path:
    sys.path.insert(0, _MODULES)

# modules/ is imported as top-level modules, which outlive a reinstall or reload of
# the add-on package: without this, new code runs on the old string table, mapping
# and so on until Blender restarts.  This file is imported once per package load.
_OWN = {os.path.splitext(n)[0] for n in os.listdir(_MODULES)
        if n.endswith(".py") or os.path.isdir(os.path.join(_MODULES, n))}
for _name in [m for m in sys.modules if m.split(".")[0] in _OWN]:
    del sys.modules[_name]

from jcns_i18n import T, get_lang, set_lang  # noqa: E402,F401
_mapping = None
_mirror = None
_flags = None
_kinds = None
_plan = None


def ensure_path():
    if _MODULES not in sys.path:
        sys.path.insert(0, _MODULES)


def get_mapping():
    global _mapping
    if _mapping is None:
        ensure_path()
        import jcns_mapping
        _mapping = jcns_mapping
    return _mapping


def get_mirror():
    global _mirror
    if _mirror is None:
        ensure_path()
        import jcns_mirror
        _mirror = jcns_mirror
    return _mirror


def get_schema():
    ensure_path()
    import jcns_schema
    return jcns_schema


def get_flags():
    global _flags
    if _flags is None:
        ensure_path()
        import jcns_flags
        _flags = jcns_flags
    return _flags


def get_kinds():
    global _kinds
    if _kinds is None:
        ensure_path()
        import jcns_kinds
        _kinds = jcns_kinds
    return _kinds


def get_targets():
    ensure_path()
    import jcns_targets
    return jcns_targets


def get_plan():
    global _plan
    if _plan is None:
        ensure_path()
        import jcns_preview_plan
        _plan = jcns_preview_plan
    return _plan
