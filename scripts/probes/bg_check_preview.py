"""
bg_check_preview.py -- compare the add-on's Blender preview with an in-game capture,
in a background Blender that leaves the user's open session alone.

    blender.exe --background --factory-startup --python scripts/probes/bg_check_preview.py -- \
        --jcns <file.jcns.102> --data <reframework/data/roundN_keep> [--x-out 8 --x-gain 0.5]

Imports the xaihi rig mesh and the given jcns, applies every preview, then for every
captured frame (default stride 10) drives L_Thigh's X to the engine's input -- recovered as
Out<x-out> / <x-gain>, i.e. from an entry that maps L_Thigh.X linearly -- and compares
each TestTgt* bone's parent-relative rotation with the recorded quaternion.  Prints
one line "RESULT {json}" with the worst error per bone. If the TRS sidecar is
present, also compares position (metres converted to cm) and scale. --addon-dir
loads a checkout in this background process without modifying the installed copy.

Why these flags: without --factory-startup other installed add-ons crash Blender's
background start; RE Mesh Editor is enabled with its console toggle off, because
wm.console_toggle crashes without a window.
"""
import argparse
import contextlib
import csv
import io
import importlib.util
import json
import math
import os
import sys

import addon_utils
import bpy
import mathutils

RIG = "E:/Program/Steam/steamapps/common/MonsterHunterWilds/natives/STM/art/model/character/ch03/xaihi/"
MESH = "xaihi_model.mesh.241111606"

ap = argparse.ArgumentParser()
ap.add_argument('--jcns', default=RIG + "xaihi_constraint.jcns.102")
ap.add_argument('--mesh', default=RIG + MESH, help='use the mesh snapshot matching this capture')
ap.add_argument('--data', required=True)
ap.add_argument('--x-out', type=int, default=8)
ap.add_argument('--x-gain', type=float, default=0.5)
ap.add_argument('--export', default='', help='also export the file here (round-trip check)')
ap.add_argument('--addon-dir', default='', help='load this checkout instead of the installed add-on')
ap.add_argument('--stride', type=int, default=10)
ap.add_argument('--report-json', default='')
args = ap.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])

addons = os.path.join(os.environ['APPDATA'], 'Blender Foundation', 'Blender', '5.1', 'scripts', 'addons')
if addons not in sys.path:
    sys.path.append(addons)
addon_utils.enable('RE-Mesh-Editor', default_set=True, persistent=False)
if args.addon_dir:
    spec = importlib.util.spec_from_file_location('jcns_probe_addon',
        os.path.join(args.addon_dir, '__init__.py'), submodule_search_locations=[args.addon_dir])
    addon = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = addon
    spec.loader.exec_module(addon)
    addon.register()
else:
    addon_utils.enable('bl_ext.user_default.wilds_jcns_editor', default_set=True, persistent=False)
bpy.context.preferences.addons['RE-Mesh-Editor'].preferences.showConsole = False

quiet = io.StringIO()
with contextlib.redirect_stdout(quiet):
    bpy.ops.re_mesh.importfile(filepath=args.mesh, files=[{"name": os.path.basename(args.mesh)}], directory=os.path.dirname(args.mesh))
arm = [o for o in bpy.data.objects if o.type == 'ARMATURE'][0]
with contextlib.redirect_stdout(quiet):
    bpy.ops.jcns.import_file(filepath=args.jcns, target_armature_name=arm.name)
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
f = open(os.path.join(args.data, 'jcns_cm_rig_skel.csv'))
hdr = f.readline().strip().split(',')
names = [hdr[k][:-3] for k in range(1, len(hdr), 4)]
rows = [l.strip().split(',') for l in f]
if args.stride < 1 or len(S) != len(rows) or not rows:
    raise ValueError('Invalid stride or mismatched/empty capture')
if any(s['Frame'] != r[0] for s, r in zip(S, rows)):
    raise ValueError('Sweep/skel frame alignment differs')
trs_path = os.path.join(args.data, 'jcns_cm_rig_trs.csv')
trs = None
if os.path.isfile(trs_path):
    with open(trs_path) as f:
        trs = list(csv.DictReader(f))
    if len(trs) != len(S) or any(a['Frame'] != b['Frame'] for a,b in zip(S,trs)):
        raise ValueError('Sweep/TRS frame alignment differs')


def recorded(r, nm):
    b = 1 + 4 * names.index(nm)
    x, y, z, w = (float(r[b + c]) for c in range(4))
    return mathutils.Quaternion((w, x, y, z)).normalized()     # the CSV has 5 decimals


bones = [b.name for b in arm.pose.bones if b.name.startswith('TestTgt') and b.name in names]
thigh = arm.pose.bones['L_Thigh']
thigh.rotation_mode = 'XYZ'
scn = bpy.context.scene
err = {b: 0.0 for b in bones}
pos_err = {b: 0.0 for b in bones}
scale_err = {b: 0.0 for b in bones}
for t in range(0, len(S), args.stride):
    thigh.rotation_euler = (float(S[t]['Out%d' % args.x_out]) / args.x_gain, 0.0, 0.0)
    arm.update_tag()
    scn.frame_set(t)
    evaluated_arm = arm.evaluated_get(bpy.context.evaluated_depsgraph_get())
    for b in bones:
        p = evaluated_arm.pose.bones[b]
        dq = recorded(rows[t], b).rotation_difference((p.parent.matrix.inverted() @ p.matrix).to_quaternion())
        err[b] = max(err[b], math.degrees(2 * math.atan2(math.sqrt(dq.x ** 2 + dq.y ** 2 + dq.z ** 2), abs(dq.w))))
        if trs is not None:
            matrix = p.parent.matrix.inverted() @ p.matrix
            for kind, value, errors, factor in (('p',matrix.translation,pos_err,100),
                                               ('s',matrix.to_scale(),scale_err,1)):
                want = [float(trs[t][b+'_'+kind+a]) for a in 'xyz']
                if not all(math.isfinite(v) for v in want):
                    raise ValueError('Missing/nonfinite TRS capture: '+b)
                errors[b] = max(errors[b],max(abs(a-v)*factor for a,v in zip(want,value)))

res = {'apply': list(applied), 'skipped': skipped, 'max_err_deg': {k: round(v, 4) for k, v in err.items()}}
res['checked_frames'] = len(range(0,len(S),args.stride))
if trs is not None:
    res['max_position_err_cm'] = pos_err
    res['max_scale_err'] = scale_err
res['passed'] = ('FINISHED' in applied and not skipped and max(err.values()) <= 0.002
                 and (trs is None or (max(pos_err.values()) <= 0.0001 and max(scale_err.values()) <= 0.00001)))
if args.export:
    with contextlib.redirect_stdout(quiet):
        res['export'] = list(bpy.ops.jcns.export_file(filepath=args.export))
print('RESULT ' + json.dumps(res, ensure_ascii=False))
if args.report_json:
    with open(args.report_json,'w',encoding='utf-8') as f:
        json.dump(res,f,ensure_ascii=False,indent=2)
if not res['passed']:
    raise RuntimeError('Preview validation failed')
