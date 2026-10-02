"""
Display-language lookup for every user-visible string.

Text is fetched with ``T("area.key")`` from the tables in ``jcns_strings/``.  Blender's own
interface translation (``bpy.app.translations``) is not used: it matches by msgid across the
whole UI, so short labels would collide with built-in entries.

Which language is active:
  1. the choice saved in the user config directory (set by the language buttons), else
  2. ``JCNS_LANG`` in the environment (tests), else
  3. Blender's interface language: Chinese locales give ZH, everything else EN, else
  4. ZH when bpy is unavailable (offline tests).

Draw-time text follows a switch immediately.  Strings read at registration (property names,
tooltips, enum items, bl_label) are resolved when the add-on is loaded, so they follow a
switch after the add-on is reloaded or Blender restarts.

This module must not import bpy at module level: ``modules/`` is bpy-free and tested offline.
"""

import os

LANGS = ("EN", "ZH")
_LANG = None
_TABLE = None


def _lang_file():
    import bpy
    return os.path.join(bpy.utils.user_resource("CONFIG"), "jcns_editor_lang.txt")


def _blender_default():
    try:
        import bpy
        return "ZH" if bpy.app.translations.locale.lower().startswith("zh") else "EN"
    except Exception:
        return "ZH"


def _resolve():
    try:
        with open(_lang_file(), encoding="utf-8") as f:
            saved = f.read().strip()
        if saved in LANGS:
            return saved
    except Exception:
        pass
    forced = os.environ.get("JCNS_LANG", "").upper()
    if forced in LANGS:
        return forced
    return _blender_default()


def get_lang():
    global _LANG
    if _LANG is None:
        _LANG = _resolve()
    return _LANG


def set_lang(lang):
    """Switch for this session and remember it; a failed write only costs the next session."""
    global _LANG
    _LANG = lang if lang in LANGS else _blender_default()
    try:
        with open(_lang_file(), "w", encoding="utf-8") as f:
            f.write(_LANG)
    except Exception as ex:
        print("[JCNS] could not save the language choice: %s" % ex)


def _table():
    global _TABLE
    if _TABLE is None:
        import jcns_strings
        _TABLE = jcns_strings.load()
    return _TABLE


def T(key, *args):
    """Text for ``key`` in the active language, ``%``-formatted with ``args`` when given.
    An unknown key comes back as itself so a missing entry is visible on screen."""
    entry = _table().get(key)
    if entry is None:
        return key
    text = entry.get(get_lang()) or entry.get("EN") or key
    return text % args if args else text
