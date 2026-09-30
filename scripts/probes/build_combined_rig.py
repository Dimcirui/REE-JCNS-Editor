"""Round 11 staging builder; run with Blender --background --factory-startup.

Only B/C/D/G rest rotation and E/F/G rest scale are changed in the mesh.
Six leaf bones' local/world/inverse matrices are patched; every other byte
must remain identical. This does not export or alter the live Blender scene.
Hidden fields: EulerOrder=0, UnknownUInt32_28=0, ReadMode=3, CurveMode=0,
identity ref_frame, UnknownByte72=0, UnknownFloat2=(0,0), Tail[1]=2,
Tail[3]=0; remaining fields inherit original constraint [00].
"""
import argparse
import contextlib
import copy
import hashlib
import importlib
import io
import json
import math
import os
from pathlib import Path
import struct
import sys
from mathutils import Matrix, Euler, Vector

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'modules'))
sys.path.append(os.path.join(os.environ['APPDATA'], 'Blender Foundation/Blender/5.1/scripts/addons'))
from modules.jcns_parser import JCNSParser
from modules.jcns_writer import JCNSWriter, tail_group_counts

RIG = Path('E:/Program/Steam/steamapps/common/MonsterHunterWilds/natives/STM/art/model/character/ch03/xaihi')
MULTI = (-2, 17, -23)
SCALE = (1.4, 0.7, 1.8)


def sha(b):
    return hashlib.sha256(b).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mesh', type=Path, default=RIG / 'xaihi_model.mesh.241111606')
    ap.add_argument('--output-dir', type=Path, required=True)
    args = ap.parse_args(sys.argv[sys.argv.index('--')+1:])
    args.output_dir.mkdir(parents=True, exist_ok=True)
    raw = args.mesh.read_bytes()
    module = importlib.import_module('RE-Mesh-Editor.modules.mesh.file_re_mesh')
    r = module.readREMesh(str(args.mesh))
    s = r.skeletonHeader
    names = [r.rawNameList[n] for n in r.boneNameRemapList]
    data = bytearray(raw)
    patched = []
    rests = {}
    for letter in 'ABCDEFGHIJK':
        name = 'TestTgt' + letter
        i = names.index(name)
        local = Matrix(s.localMatList[i].matrix).transposed()
        # Reject reuse of an already modified mesh: the base is round 4/10.
        assert max(abs(x-1) for x in local.to_scale()) < 1e-5
        assert max(abs(x-y) for x,y in zip(local.to_euler('XYZ'), (math.radians(-2),0,0))) < 1e-5
        if letter in 'BCDEFG':
            assert not any(b.boneParent == i for b in s.boneInfoList), name + ' has children'
            rot = Euler(tuple(math.radians(v) for v in MULTI), 'XYZ') if letter in 'BCDG' else local.to_euler('XYZ')
            scale = Vector(SCALE) if letter in 'EFG' else local.to_scale()
            local = Matrix.LocRotScale(local.translation, rot.to_quaternion(), scale)
            parent = s.boneInfoList[i].boneParent
            world = Matrix(s.worldMatList[parent].matrix).transposed() @ local
            for start, mat in ((s.boneLocalMatrixOffset,local),
                               (s.boneWorldMatrixOffset,world),
                               (s.boneInverseMatrixOffset,world.inverted())):
                offset = start + i*64
                assert 0 <= offset <= len(data)-64
                packed = struct.pack('<16f', *(v for row in mat.transposed() for v in row))
                data[offset:offset+64] = packed
                patched.append((offset,offset+64))
            # Store actual float32 local matrix values used in the file.
            offset = s.boneLocalMatrixOffset + i*64
            values = struct.unpack_from('<16f',data,offset)
            local = Matrix([values[j:j+4] for j in range(0,16,4)]).transposed()
        rests[letter] = dict(index=i, parent=s.boneInfoList[i].boneParent,
            position_m=list(local.translation), scale=list(local.to_scale()),
            euler_xyz_rad=list(local.to_euler('XYZ')),
            quaternion_wxyz=list(local.to_quaternion().normalized()))
    cursor = 0
    for start,end in sorted(patched):
        assert data[cursor:start] == raw[cursor:start]
        cursor = end
    assert data[cursor:] == raw[cursor:] and len(data) == len(raw)
    mesh_output = args.output_dir / 'xaihi_model.mesh.241111606'
    mesh_output.write_bytes(data)
    back = module.readREMesh(str(mesh_output)).skeletonHeader
    for letter in 'BCDEFG':
        i = rests[letter]['index']
        local = Matrix(back.localMatList[i].matrix).transposed()
        world = Matrix(back.worldMatList[i].matrix).transposed()
        parent = Matrix(back.worldMatList[back.boneInfoList[i].boneParent].matrix).transposed()
        inverse = Matrix(back.inverseMatList[i].matrix).transposed()
        assert max(abs(v) for row in world-parent@local for v in row) < 1e-5
        assert max(abs(v) for row in world@inverse-Matrix.Identity(4) for v in row) < 1e-5

    parser = JCNSParser(str(RIG/'xaihi_constraint.jcns.102.orig_20260929'))
    with contextlib.redirect_stdout(io.StringIO()):
        cons = parser.parse()
    assert len(cons) == 8
    template = copy.deepcopy(cons[0])
    for c in cons:
        tail = bytearray(c['TailBytes']); tail[3]=0
        c['TailBytes'] = bytes(tail)
    entries = []
    def add(letter,tt,flags,axes,gains=None):
        for axis in axes:
            i = 'XYZ'.index(axis)
            gain = (gains or {0:(.03,.05,-.04),1:(.5,.8,-.9),2:(.002,.003,-.004),13:(.6,.6,.6),14:(.6,.6,.6)}[tt])[i]
            bias = 1 if tt == 2 else 0
            c = copy.deepcopy(template)
            c.update(ObjectName='TestTgt'+letter,TransformType=tt,Flags=flags,
                TransformAxis_parent=i,target_axis=i,UnknownByte72=0,UnknownFloat2=(0.,0.))
            tail=bytearray(c['TailBytes']); tail[1]=2; tail[3]=0
            c['TailBytes']=bytes(tail)
            c['sources'][0].update(SourceName='L_Thigh',source_axis=0,ReadMode=3,CurveMode=0,
                EulerOrder=0,UnknownUInt32_28=0,ref_frame_x=0.,ref_frame_y=0.,ref_frame_z=0.,ref_frame_w=1.,
                from_start=-90.,from_kink=0.,from_end=90.,to_start=bias-90*gain,
                to_kink=bias,to_end=bias+90*gain,ComplexMapping=[],ComplexMappingInfoCount=0)
            entries.append(dict(out=len(cons),bone=letter,type=tt,flags=flags,axis=axis,gain=gain,bias=bias))
            cons.append(c)
    add('A',1,49,'X')
    add('B',1,48,'X'); add('C',1,48,'Y'); add('D',1,48,'XYZ')
    add('E',2,17,'Y'); add('F',2,16,'Y')
    for letter,tt,first in [('H',13,True),('I',13,False),('J',14,True),('K',14,False)]:
        if first: add(letter,tt,49,'Y')
        add(letter,0,17,'XYZ'); add(letter,2,17,'XYZ')
        if not first: add(letter,tt,49,'Y')
    assert len(cons)==44 and tail_group_counts(cons)==[0]*44
    jcns_output=args.output_dir/'xaihi_constraint.jcns.102'
    JCNSWriter(parser,str(jcns_output)).build_lossless()
    q=JCNSParser(str(jcns_output))
    with contextlib.redirect_stdout(io.StringIO()):
        decoded=q.parse()
    assert len(decoded)==44 and tail_group_counts(decoded)==[0]*44
    for e in entries:
        c=decoded[e['out']]; src=c['sources'][0]
        assert (c['ObjectName'],c['TransformType'],c['Flags'],c['target_axis']) == ('TestTgt'+e['bone'],e['type'],e['flags'],'XYZ'.index(e['axis']))
        assert src['EulerOrder']==src['UnknownUInt32_28']==src['CurveMode']==0 and src['ReadMode']==3
        assert c['UnknownByte72']==0 and tuple(c['UnknownFloat2'])==(0.,0.) and c['TailBytes'][1]==2
    manifest=dict(round=11,base_mesh_sha256=sha(raw),mesh_sha256=sha(data),
        jcns_sha256=sha(jcns_output.read_bytes()),matrix_ranges=patched,rests=rests,entries=entries,
        rotation_tolerance_deg=.002,position_tolerance_cm=.0001,scale_tolerance=.00001)
    (args.output_dir/'round11_plan.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print('ROUND11',json.dumps(dict(entries=len(cons),patched_bones=6,mesh_sha256=sha(data),jcns_sha256=manifest['jcns_sha256'])))
    for e in entries: print(e)


if __name__=='__main__':
    main()
