"""Round 10: translation/scale Flags bit0, using the unchanged round-4 mesh.

Out8 A.X: rotation control, L_Thigh.X * 0.5 (radians).
Out9..11 B.XYZ translation F17; Out12..14 C.XYZ translation F16.
Out15..17 D.XYZ scale F17; Out18..20 E.XYZ scale F16.
Out21 F.Y translation F17; Out22 G.Y translation F16.
Out23 H.Y scale F17; Out24 I.Y scale F16. J/K remain undriven.
Translation anchors: degrees * (0.03, 0.05, -0.04) cm.
Scale anchors: 1 + degrees * (0.002, 0.003, -0.004).
All test entries explicitly set EulerOrder/U32_2/+72/ParentFloat2=0,
Tail[1]=2, Tail[3]=0 and identity rest_quat. Other fields inherit original [00].
Writes a staging file; deployment must back up the active jcns first.
"""
import argparse
import contextlib
import copy
import io
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'modules'))
from modules.jcns_parser import JCNSParser
from modules.jcns_writer import JCNSWriter, tail_group_counts

RIG = Path('E:/Program/Steam/steamapps/common/MonsterHunterWilds/natives/STM/art/model/character/ch03/xaihi')
CASES = [('A', 1, 49, 'X'), ('B', 0, 17, 'XYZ'), ('C', 0, 16, 'XYZ'),
         ('D', 2, 17, 'XYZ'), ('E', 2, 16, 'XYZ'), ('F', 0, 17, 'Y'),
         ('G', 0, 16, 'Y'), ('H', 2, 17, 'Y'), ('I', 2, 16, 'Y')]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', type=Path, default=ROOT / 'scripts/probes/round10.jcns.102')
    args = ap.parse_args()
    p = JCNSParser(str(RIG / 'xaihi_constraint.jcns.102.orig_20260929'))
    with contextlib.redirect_stdout(io.StringIO()):
        cons = p.parse()
    assert len(cons) == 8
    template = copy.deepcopy(cons[0])
    for c in cons:
        tail = bytearray(c['ParentTailBytes']); tail[3] = 0
        c['ParentTailBytes'] = bytes(tail)
    for bone, tt, flags, axes in CASES:
        for axis in axes:
            i = 'XYZ'.index(axis)
            c = copy.deepcopy(template)
            c.update(ObjectName='TestTgt' + bone, TransformType=tt, Flags=flags,
                     TransformAxis_parent=i, target_axis=i,
                     ParentUInt8_72=0, ParentFloat2=(0.0, 0.0))
            tail = bytearray(c['ParentTailBytes']); tail[1] = 2; tail[3] = 0
            c['ParentTailBytes'] = bytes(tail)
            s = c['sources'][0]
            gain = 0.5 if tt == 1 else ((0.03, 0.05, -0.04) if tt == 0 else (0.002, 0.003, -0.004))[i]
            bias = 1.0 if tt == 2 else 0.0
            s.update(SourceName='L_Thigh', source_axis=0, ReadMode=3, CurveMode=0,
                     EulerOrder=0, UnknownUInt32_2=0, rest_quat_x=0.0,
                     rest_quat_y=0.0, rest_quat_z=0.0, rest_quat_w=1.0,
                     from_start=-90.0, from_kink=0.0, from_end=90.0,
                     to_start=bias-90*gain, to_kink=bias, to_end=bias+90*gain,
                     ComplexMapping=[], ComplexMappingInfoCount=0)
            cons.append(c)
    assert len(cons) == 25 and tail_group_counts(cons) == [0]*25
    JCNSWriter(p, str(args.output)).build_lossless()
    q = JCNSParser(str(args.output))
    with contextlib.redirect_stdout(io.StringIO()):
        back = q.parse()
    assert len(back) == 25 and tail_group_counts(back) == [0]*25
    for idx, (a, b) in enumerate(zip(cons, back)):
        assert (a['ObjectName'], a['TransformType'], a['Flags'], a['target_axis']) == (b['ObjectName'], b['TransformType'], b['Flags'], b['target_axis'])
        if idx >= 8:
            assert b['sources'][0]['UnknownUInt32_2'] == 0
        print(idx, b['ObjectName'], b['TransformType'], b['Flags'], b['target_axis'])


if __name__ == '__main__':
    main()
