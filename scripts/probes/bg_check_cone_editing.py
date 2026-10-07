"""
bg_check_cone_editing.py -- the ConeInput table editor end to end, in a background Blender.

    blender.exe --background --factory-startup --python scripts/probes/bg_check_cone_editing.py -- \
        --addon-dir <checkout> --with-cones <a .jcns.102 with cones> --without-cones <one without>

1. A file with cones imports and exports back byte for byte.
2. On a file without cones: add a ConeInput (joint L_Thigh; the parent fills itself),
   give entry [00] a ConeDriver, apply the preview, export, and parse the result back.
Prints "RESULT {json}".
"""
import argparse
import contextlib
import importlib.util
import io
import json
import math
import os
import sys
import tempfile

import addon_utils
import bpy

RIG = "E:/Program/Steam/steamapps/common/MonsterHunterWilds/natives/STM/art/model/character/ch03/xaihi/"
ap = argparse.ArgumentParser()
ap.add_argument('--addon-dir', required=True)
ap.add_argument('--with-cones', required=True)
ap.add_argument('--without-cones', required=True)
ap.add_argument('--mesh', default=RIG + "xaihi_model.mesh.241111606")
args = ap.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])

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
from jcns_parser import JCNSParser  # noqa: E402  (the add-on put modules/ on sys.path)

quiet = io.StringIO()
with contextlib.redirect_stdout(quiet):
    bpy.ops.re_mesh.importfile(filepath=args.mesh, files=[{"name": os.path.basename(args.mesh)}],
                               directory=os.path.dirname(args.mesh))
arm = [o for o in bpy.data.objects if o.type == 'ARMATURE'][0]
tmp = tempfile.mkdtemp()
res = {}


def import_root(path):
    before = set(bpy.data.collections)
    with contextlib.redirect_stdout(quiet):
        bpy.ops.jcns.import_file(filepath=path, target_armature_name=arm.name)
    col = [c for c in bpy.data.collections if c not in before and c.name.startswith('JCNS_')][0]
    root = [o for o in col.objects if getattr(o, 'jcns_root_props', None) and o.jcns_root_props.source_filepath][0]
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    root.select_set(True)
    bpy.context.view_layer.objects.active = root
    return root


def export(path):
    log = io.StringIO()
    with contextlib.redirect_stdout(log):
        r = bpy.ops.jcns.export_file(filepath=path)
    return list(r), log.getvalue()


def parse(path):
    p = JCNSParser(path)
    with contextlib.redirect_stdout(io.StringIO()):
        cons = p.parse()
    return p, cons


# 1. round trip
root = import_root(args.with_cones)
out1 = os.path.join(tmp, 'rt' + os.path.splitext(args.with_cones)[1])
r1, _ = export(out1)
res['roundtrip_export'] = r1
res['roundtrip_identical'] = open(out1, 'rb').read() == open(args.with_cones, 'rb').read()
res['roundtrip_cones'] = len(root.jcns_root_props.cone_inputs)

# 2. build a cone from the UI on a file without one
root = import_root(args.without_cones)
rp = root.jcns_root_props
assert not len(rp.cone_inputs)
res['add_cone'] = list(bpy.ops.jcns.cone_input_add())
ci = rp.cone_inputs[0]
ci.joint = 'L_Thigh'
res['parent_filled'] = ci.parent_joint
ci.direction_euler = (0.0, 0.0, math.radians(-90))
ci.angle = math.radians(60)
ci.base_pose = True
bpy.ops.jcns.cone_input_matrix(preset='MIRROR')
entry = [o for o in root.children if getattr(o, 'jcns_cns_props', None) and o.jcns_cns_props.constraint_type == 'Outputs'][0]
for o in bpy.context.view_layer.objects:
    o.select_set(False)
entry.select_set(True)
bpy.context.view_layer.objects.active = entry
res['add_driver'] = list(bpy.ops.jcns.cone_driver_add())
k = entry.jcns_cns_props.cone_drivers[0]
k.out_min, k.out_max, k.interpolation = 0.0, 30.0, 3
log = io.StringIO()
with contextlib.redirect_stdout(log):
    res['preview'] = list(bpy.ops.jcns.preview_apply(scope='FILE'))
res['preview_skips'] = [l for l in log.getvalue().splitlines() if 'SKIP' in l][:3]
root.select_set(True)
bpy.context.view_layer.objects.active = root
out2 = os.path.join(tmp, 'new' + os.path.splitext(args.without_cones)[1])
r2, log2 = export(out2)
res['new_export'] = r2
p, cons = parse(out2)
cd = p.cone_inputs[0] if p.cone_inputs else {}
res['new_cone'] = {k2: (round(v, 5) if isinstance(v, float) else [round(x, 5) for x in v] if isinstance(v, tuple) else
                        v.hex() if isinstance(v, bytes) else v)
                   for k2, v in cd.items() if k2 in ('Name', 'Direction', 'Matrix', 'AngleRad', 'Tail',
                                                    'JointHash', 'ParentJointHash')}
res['new_driver'] = cons[0].get('ConeDriver')
res['passed'] = (res['roundtrip_identical'] and res['parent_filled'] == 'Hip' and 'FINISHED' in r2
                 and len(p.cone_inputs) == 1 and len(cons[0].get('ConeDriver') or []) == 1
                 and abs(cd['AngleRad'] - math.radians(60)) < 1e-6 and cd['Tail'][3] == 1)
print('RESULT ' + json.dumps(res, ensure_ascii=False, default=str))
if not res['passed']:
    raise RuntimeError('cone editing check failed')
