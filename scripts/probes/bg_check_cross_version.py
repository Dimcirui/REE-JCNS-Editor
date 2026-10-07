"""
bg_check_cross_version.py -- v35 <-> v102 export, in a background Blender.

    blender.exe --background --factory-startup --python scripts/probes/bg_check_cross_version.py -- \
        --addon-dir <checkout> --jcns <file.jcns.35 or .102> [--mesh <mesh>]

Imports the file, exports it as the other version, imports that and exports it back,
then compares every record with the original: what the conversion is meant to change
(AttrFlags bit 5, TailBytes[1], Multi tail bytes, ReadJointTable) is checked against the
rules in jcns_exporter.CONVERTIBLE_VERSIONS, everything else must be equal.
Prints "RESULT {json}".
"""
import argparse
import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile

import addon_utils
import bpy

RIG = "E:/Program/Steam/steamapps/common/MonsterHunterWilds/natives/STM/art/model/character/ch03/xaihi/"
ap = argparse.ArgumentParser()
ap.add_argument('--addon-dir', required=True)
ap.add_argument('--jcns', required=True)
ap.add_argument('--mesh', default=RIG + "xaihi_model.mesh.241111606")
args, _extra = ap.parse_known_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])

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
from jcns_parser import JCNSParser  # noqa: E402
from jcns_sections import multi_editable  # noqa: E402

quiet = io.StringIO()
with contextlib.redirect_stdout(quiet):
    bpy.ops.re_mesh.importfile(filepath=args.mesh, files=[{"name": os.path.basename(args.mesh)}],
                               directory=os.path.dirname(args.mesh))
arm = [o for o in bpy.data.objects if o.type == 'ARMATURE'][0]
tmp = tempfile.mkdtemp()


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


def export(root, version):
    path = os.path.join(tmp, '%s_%d.jcns.%d' % (root.name, version, version))
    log = io.StringIO()
    with contextlib.redirect_stdout(log):
        r = bpy.ops.jcns.export_file(filepath=path, target_version=str(version))
    return path, list(r), root.jcns_root_props.source_filepath


def parse(path):
    p = JCNSParser(path)
    with contextlib.redirect_stdout(io.StringIO()):
        cons = p.parse()
    return p, cons


SKIP = {'ConeDriverOffset', 'SourceListOffset', 'ObjectNameOffset', 'PropertyOffset', 'ParentSetOffset',
        'ObjectHashIndex', 'ConeDriverInfoOffset', '_rec', '_offset'}


def _plain(d):
    return {k: v for k, v in d.items() if k not in SKIP and not k.endswith('Offset') and not k.endswith('Index')}


def norm(c, drop):
    out = {k: v for k, v in _plain(c).items() if k not in drop}
    for k in ('sources', 'ConeDriver'):
        if k in out:
            out[k] = [_plain(s) for s in out[k]]
    return out


p0, c0 = parse(args.jcns)
v0 = p0.version
v1 = 35 if v0 == 102 else 102
res = {'from': v0, 'to': v1}
root = import_root(args.jcns)
path1, r1, src_after = export(root, v1)
res['export_1'] = r1
res['root_kept_source'] = os.path.normpath(src_after) == os.path.normpath(args.jcns)
p1, c1 = parse(path1)
res['version_1'] = p1.version
# rules on the converted file
res['bit5_on_v35'] = sum(1 for c in (c1 if v1 == 35 else []) if c['AttrFlags'] & 0x20)
res['tail1_values_1'] = sorted({bytes(c['TailBytes'])[1] for c in c1})
res['multi_tails_1'] = sorted({bytes(r['tail']).hex() for r in multi_editable(p1)[0]})
res['read_table_1'] = len(getattr(p1, 'read_joint_table', []) or [])
res['cones_1'] = len(p1.cone_inputs)
# everything else equal to the original
drop = {'AttrFlags', 'TailBytes'}
res['records'] = (len(c0), len(c1))
res['outputs_equal_1'] = [norm(a, drop) == norm(b, drop) for a, b in zip(c0, c1)].count(False)
res['cones_equal_1'] = [{k: v for k, v in a.items() if not k.endswith('Offset') and not k.endswith('Index')} ==
                        {k: v for k, v in b.items() if not k.endswith('Offset') and not k.endswith('Index')}
                        for a, b in zip(p0.cone_inputs, p1.cone_inputs)].count(False)
# and back (a v35 -> v102 export with Multi or Aim derives the ReadJointTable, so it
# needs the file's own skeleton as --mesh)
root2 = import_root(path1)
try:
    path2, r2, _ = export(root2, v0)
except RuntimeError as exc:
    res['export_2'] = 'refused: ' + str(exc)[:160]
    print('RESULT ' + json.dumps(res, ensure_ascii=False, default=str))
    sys.exit(0)
res['export_2'] = r2
p2, c2 = parse(path2)
res['outputs_equal_2'] = [norm(a, drop) == norm(b, drop) for a, b in zip(c0, c2)].count(False)
res['flags_back'] = [a['AttrFlags'] == b['AttrFlags'] for a, b in zip(c0, c2)].count(False)
res['tail1_back_changed'] = [bytes(a['TailBytes'])[1] != bytes(b['TailBytes'])[1] for a, b in zip(c0, c2)].count(True)
res['multi_back'] = [bytes(a['tail']) == bytes(b['tail']) for a, b in zip(multi_editable(p0)[0], multi_editable(p2)[0])].count(False)
print('RESULT ' + json.dumps(res, ensure_ascii=False, default=str))
