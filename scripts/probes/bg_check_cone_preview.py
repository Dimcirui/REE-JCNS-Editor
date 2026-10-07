"""
bg_check_cone_preview.py -- compare the add-on's ConeDriver preview with round 20's
capture (build_cone_rig.py), in a background Blender.

    blender.exe --background --factory-startup --python scripts/probes/bg_check_cone_preview.py -- \
        --addon-dir <checkout> --data <reframework/data/round20_keep> [--stride 5]

Imports the xaihi mesh and the capture's jcns, applies every preview, then per frame
poses L_Thigh to the recorded parent-relative rotation (Out16..18, XYZ Euler, rest
included) and compares each cone target's offset from rest along its parent's X with
the engine's value (Out8..15, metres on these translation targets).  Prints
"RESULT {json}"; the check passes at <= 1e-4 cm.
"""
import argparse
import contextlib
import csv
import importlib.util
import io
import json
import os
import sys

import addon_utils
import bpy
import mathutils

RIG = "E:/Program/Steam/steamapps/common/MonsterHunterWilds/natives/STM/art/model/character/ch03/xaihi/"
ap = argparse.ArgumentParser()
ap.add_argument('--data', required=True)
ap.add_argument('--jcns', default='')
ap.add_argument('--mesh', default=RIG + "xaihi_model.mesh.241111606")
ap.add_argument('--addon-dir', required=True)
ap.add_argument('--stride', type=int, default=5)
args = ap.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])
jcns = args.jcns or os.path.join(args.data, 'xaihi_constraint.jcns.102')

addons = os.path.join(os.environ['APPDATA'], 'Blender Foundation', 'Blender', '5.1', 'scripts', 'addons')
if addons not in sys.path:
    sys.path.append(addons)
addon_utils.enable('RE-Mesh-Editor', default_set=True, persistent=False)
bpy.context.preferences.addons['RE-Mesh-Editor'].preferences.showConsole = False
spec = importlib.util.spec_from_file_location('jcns_probe_addon', os.path.join(args.addon_dir, '__init__.py'),
                                              submodule_search_locations=[args.addon_dir])
addon = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = addon
spec.loader.exec_module(addon)
addon.register()

quiet = io.StringIO()
with contextlib.redirect_stdout(quiet):
    bpy.ops.re_mesh.importfile(filepath=args.mesh, files=[{"name": os.path.basename(args.mesh)}],
                               directory=os.path.dirname(args.mesh))
arm = [o for o in bpy.data.objects if o.type == 'ARMATURE'][0]
with contextlib.redirect_stdout(quiet):
    bpy.ops.jcns.import_file(filepath=jcns, target_armature_name=arm.name)
col = [c for c in bpy.data.collections if c.name.startswith('JCNS_')][0]
root = [o for o in col.objects if getattr(o, 'jcns_root_props', None) and o.jcns_root_props.source_filepath][0]
for o in bpy.context.view_layer.objects:
    o.select_set(False)
root.select_set(True)
bpy.context.view_layer.objects.active = root
log = io.StringIO()
with contextlib.redirect_stdout(log):
    applied = bpy.ops.jcns.preview_apply(scope='FILE')
skipped = [l for l in log.getvalue().splitlines() if 'SKIP' in l]

S = list(csv.DictReader(open(os.path.join(args.data, 'jcns_cm_rig_sweep.csv'))))
TARGETS = ['TestTgt' + c for c in 'ABCDEFGH']
thigh = arm.pose.bones['L_Thigh']
thigh.rotation_mode = 'XYZ'
tb = arm.data.bones['L_Thigh']
rest_q = (tb.parent.matrix_local.inverted() @ tb.matrix_local).to_quaternion()
rest_off = {b: (arm.data.bones[b].parent.matrix_local.inverted() @ arm.data.bones[b].matrix_local).translation.copy()
            for b in TARGETS}
scn = bpy.context.scene
err = {b: 0.0 for b in TARGETS}
for t in range(0, len(S), args.stride):
    e = mathutils.Euler([float(S[t]['Out%d' % i]) for i in (16, 17, 18)], 'XYZ')
    basis = rest_q.inverted() @ e.to_quaternion()
    thigh.rotation_euler = basis.to_euler('XYZ')
    arm.update_tag()
    scn.frame_set(t)
    ev = arm.evaluated_get(bpy.context.evaluated_depsgraph_get())
    for k, b in enumerate(TARGETS):
        p = ev.pose.bones[b]
        d = (p.parent.matrix.inverted() @ p.matrix).translation - rest_off[b]
        want = mathutils.Vector((float(S[t]['Out%d' % (8 + k)]), 0.0, 0.0))
        err[b] = max(err[b], (d - want).length * 100.0)

res = {'apply': list(applied), 'skipped': skipped, 'max_err_cm': {k: round(v, 6) for k, v in err.items()},
       'checked_frames': len(range(0, len(S), args.stride))}
res['passed'] = 'FINISHED' in applied and max(err.values()) <= 1e-4
print('RESULT ' + json.dumps(res, ensure_ascii=False))
if not res['passed']:
    raise RuntimeError('Cone preview check failed')
