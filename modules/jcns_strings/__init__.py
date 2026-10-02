"""
String tables, one module per area of the add-on.  Each defines

    STRINGS = {"area.key": {"ZH": "...", "EN": "..."}, ...}

and a key starts with the prefix its module owns (see _MODULES), so tables never collide.
"""

import importlib

# module name -> key prefix it owns
_MODULES = {
    "props": "props",
    "ui": "ui",
    "editors": "editors",
    "ops": "ops",
    "sdk": "sdk",
    "io": "io",
    "core": "core",
    "common": "common",
}


def load():
    merged = {}
    for name, prefix in _MODULES.items():
        table = importlib.import_module("%s.%s" % (__name__, name)).STRINGS
        for key, entry in table.items():
            if not key.startswith(prefix + "."):
                raise ValueError("%s.py: key %r must start with %r" % (name, key, prefix + "."))
            if key in merged:
                raise ValueError("duplicate string key %r" % key)
            merged[key] = entry
    return merged
