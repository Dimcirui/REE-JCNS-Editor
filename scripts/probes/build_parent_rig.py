"""
build_parent_rig.py -- xaihi test rig, round 18 (mesh changes): a child of a scaled parent.
Run with   blender --background --factory-startup --python scripts/probes/build_parent_rig.py -- --output-dir <dir>
Starts from the round-11 mesh (the base in the game directory must be that one) and changes:

  F  rest scale (1.4, 0.7, 1.8) -> (1.4, -0.7, 1.8)        a negative scale on one axis
  E  <- child K        (scale (1.4, 0.7, 1.8), rest -2 deg X)
  G  <- child J        (scale (1.4, 0.7, 1.8), rest (-2, 17, -23): scale and a turned frame)
  F  <- child I        (the negative scale)
  H  stays under Ear_SCL: the unscaled baseline

The children keep their local matrices, so their world matrices (and inverses) are recomputed from the new
parents.  Only bone records and matrices of the bones named here change; everything else stays byte for byte.

Entries (jcns): [08] A.X type 1 F49 control; then type 0 F17 X, Y, Z (gains cm/deg 0.03, 0.05, -0.04)
  [09-11] K   [12-14] J   [15-17] I   [18-20] H
What is a translation written into when its parent is scaled: the parent's scaled local frame, or the
unscaled one?  The recorded local position of each child against the entry output gives the ratio per axis.
"""
import argparse
import contextlib
import copy
import hashlib
import importlib
import io
import json
import os
import struct
import sys
from pathlib import Path

from mathutils import Matrix, Vector

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'modules'))
sys.path.append(os.path.join(os.environ['APPDATA'], 'Blender Foundation/Blender/5.1/scripts/addons'))
from modules.jcns_parser import JCNSParser
from modules.jcns_writer import JCNSWriter, tail_group_counts

RIG = Path('E:/Program/Steam/steamapps/common/MonsterHunterWilds/natives/STM/art/model/character/ch03/xaihi')
NEW_F_SCALE = (1.4, -0.7, 1.8)
REPARENT = {'K': 'E', 'J': 'G', 'I': 'F'}          # child letter -> parent letter
POS_GAIN = {'X': 0.03, 'Y': 0.05, 'Z': -0.04}
CHILDREN_OUT = {'K': 9, 'J': 12, 'I': 15, 'H': 18}


def pack(mat):
    return struct.pack('<16f', *(v for row in mat.transposed() for v in row))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mesh', type=Path, default=RIG / 'xaihi_model.mesh.241111606')
    ap.add_argument('--output-dir', type=Path, required=True)
    args = ap.parse_args(sys.argv[sys.argv.index('--') + 1:])
    args.output_dir.mkdir(parents=True, exist_ok=True)
    raw = args.mesh.read_bytes()
    module = importlib.import_module('RE-Mesh-Editor.modules.mesh.file_re_mesh')
    r = module.readREMesh(str(args.mesh))
    s = r.skeletonHeader
    names = [r.rawNameList[n] for n in r.boneNameRemapList]
    idx = {c: names.index('TestTgt' + c) for c in 'ABCDEFGHIJK'}
    ear = names.index('Ear_SCL')
    data = bytearray(raw)
    patched = []

    local = {c: Matrix(s.localMatList[i].matrix).transposed() for c, i in idx.items()}
    world = {c: Matrix(s.worldMatList[i].matrix).transposed() for c, i in idx.items()}
    # the base must be round 11: F has the (1.4, 0.7, 1.8) scale, every bone sits under Ear_SCL
    assert max(abs(a - b) for a, b in zip(local['F'].to_scale(), (1.4, 0.7, 1.8))) < 1e-5, 'not the round-11 mesh'
    assert all(s.boneInfoList[i].boneParent == ear for i in idx.values())
    ear_world = Matrix(s.worldMatList[ear].matrix).transposed()

    # 1. F: negative Y scale
    sc = Matrix.Diagonal(Vector(NEW_F_SCALE + (1.0,)))
    lt = Matrix.Translation(local['F'].translation) @ local['F'].to_quaternion().to_matrix().to_4x4() @ sc
    local['F'] = lt
    world['F'] = ear_world @ lt

    # 2. reparent: children keep their local matrices
    parent_of = {c: 'ear' for c in idx}
    for child, parent in REPARENT.items():
        parent_of[child] = parent
        world[child] = world[parent] @ local[child]
    wrote = {}
    for c, i in idx.items():
        if c in 'F':
            wrote[i] = (local[c], world[c], world[c].inverted())
        elif c in REPARENT:
            wrote[i] = (None, world[c], world[c].inverted())
    for i, (lm, wm, im) in wrote.items():
        for start, mat in ((s.boneLocalMatrixOffset, lm), (s.boneWorldMatrixOffset, wm), (s.boneInverseMatrixOffset, im)):
            if mat is None:
                continue
            off = start + i * 64
            data[off:off + 64] = pack(mat)
            patched.append((off, off + 64))

    # 3. bone records: parent / sibling / child
    def rec(i):
        return list(struct.unpack_from('<Hhhhhhhh', raw, s.boneHeaderOffset + i * 16))

    recs = {i: rec(i) for i in idx.values()}
    remaining = [c for c in 'ABCDEFGH']
    for k, c in enumerate(remaining):
        recs[idx[c]][2] = idx[remaining[k + 1]] if k + 1 < len(remaining) else -1     # sibling chain under Ear_SCL
    for child, parent in REPARENT.items():
        recs[idx[child]][1] = idx[parent]
        recs[idx[child]][2] = -1
        recs[idx[parent]][3] = idx[child]
    for i, fields in recs.items():
        off = s.boneHeaderOffset + i * 16
        data[off:off + 16] = struct.pack('<Hhhhhhhh', *fields)
        patched.append((off, off + 16))

    cursor = 0
    for start, end in sorted(set(patched)):
        assert data[cursor:start] == raw[cursor:start]
        cursor = end
    assert data[cursor:] == raw[cursor:] and len(data) == len(raw)
    mesh_out = args.output_dir / 'xaihi_model.mesh.241111606'
    mesh_out.write_bytes(data)

    # read it back and check the hierarchy and the matrices
    back = module.readREMesh(str(mesh_out)).skeletonHeader
    plan = {}
    for c, i in idx.items():
        b = back.boneInfoList[i]
        lm = Matrix(back.localMatList[i].matrix).transposed()
        wm = Matrix(back.worldMatList[i].matrix).transposed()
        pi = b.boneParent
        pw = Matrix(back.worldMatList[pi].matrix).transposed()
        im = Matrix(back.inverseMatList[i].matrix).transposed()
        assert max(abs(v) for row in wm - pw @ lm for v in row) < 1e-4, c
        assert max(abs(v) for row in wm @ im - Matrix.Identity(4) for v in row) < 1e-4, c
        plan[c] = dict(index=i, parent=pi, parent_name=names[pi], position_m=list(lm.translation),
                       scale=list(lm.to_scale()), quaternion_wxyz=list(lm.to_quaternion().normalized()),
                       sibling=b.boneSibling, child=b.boneChild)
    for child, parent in REPARENT.items():
        assert plan[child]['parent'] == idx[parent] and plan[parent]['child'] == idx[child]
    plan['F']['scale'] = list(NEW_F_SCALE)      # Matrix.to_scale() cannot tell which single axis is negative
    (args.output_dir / 'round18_plan.json').write_text(json.dumps(
        dict(round=18, rests=plan, mesh_sha256=hashlib.sha256(data).hexdigest(), base_mesh_sha256=hashlib.sha256(raw).hexdigest()),
        indent=1), encoding='utf-8')

    # jcns: control + translations on the three children and the baseline H
    src = RIG / 'xaihi_constraint.jcns.102.orig_20260929'
    parser = JCNSParser(str(src))
    with contextlib.redirect_stdout(io.StringIO()):
        cons = parser.parse()
    assert len(cons) == 8
    tmpl = copy.deepcopy(cons[0])
    for c in cons:
        t = bytearray(c['TailBytes'])
        t[3] = 0
        c['TailBytes'] = bytes(t)

    def add(letter, tt, flags, axis, gain):
        i = 'XYZ'.index(axis)
        c = copy.deepcopy(tmpl)
        c.update(ObjectName='TestTgt' + letter, TransformType=tt, Flags=flags, TransformAxis_parent=i, target_axis=i,
                 UnknownByte72=0, UnknownFloat2=(0.0, 0.0))
        t = bytearray(c['TailBytes'])
        t[0], t[1], t[3] = 0, 2, 0
        c['TailBytes'] = bytes(t)
        bias = 0.0
        c['sources'][0].update(SourceName='L_Thigh', source_axis=0, ReadMode=3, CurveMode=0, EulerOrder=0,
                               UnknownUInt32_28=0, ref_frame_x=0.0, ref_frame_y=0.0, ref_frame_z=0.0, ref_frame_w=1.0,
                               from_start=-90.0, from_kink=0.0, from_end=90.0, to_start=-90 * gain, to_kink=0.0,
                               to_end=90 * gain, ComplexMapping=[], ComplexMappingInfoCount=0)
        cons.append(c)

    add('A', 1, 49, 'X', 0.5)
    for letter in 'KJIH':
        for axis in 'XYZ':
            add(letter, 0, 17, axis, POS_GAIN[axis])
    assert len(cons) == 8 + 13 and tail_group_counts(cons) == [0] * len(cons)
    jcns_out = args.output_dir / 'xaihi_constraint.jcns.102'
    JCNSWriter(parser, str(jcns_out)).build_lossless()
    print('RESULT', json.dumps({c: (plan[c]['parent_name'], [round(v, 3) for v in plan[c]['scale']]) for c in 'EFGHIJK'}))


if __name__ == '__main__':
    main()
