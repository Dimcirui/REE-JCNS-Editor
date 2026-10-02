"""Language switch row for the panel header."""

import bpy
from bpy.props import EnumProperty
from bpy.types import Operator

from .modules_shim import T, get_lang, set_lang


def draw_language_toggle(layout):
    cur = get_lang()
    row = layout.row(align=True)
    row.operator("jcns.set_language", text="English", depress=(cur == "EN")).lang = "EN"
    row.operator("jcns.set_language", text="中文", depress=(cur == "ZH")).lang = "ZH"  # ui-copy: internal


class JCNS_OT_set_language(Operator):
    bl_idname = "jcns.set_language"
    bl_label = "Set Language"
    bl_options = {'INTERNAL'}

    lang: EnumProperty(items=[('EN', "English", ""), ('ZH', "中文", "")], options={'HIDDEN'})  # ui-copy: internal

    def execute(self, context):
        changed = self.lang != get_lang()
        set_lang(self.lang)
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                area.tag_redraw()
        if changed:
            self.report({'INFO'}, T("common.lang_reload_note"))
        return {'FINISHED'}


def register():
    bpy.utils.register_class(JCNS_OT_set_language)


def unregister():
    bpy.utils.unregister_class(JCNS_OT_set_language)
