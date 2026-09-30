"""
build_small_rig.py -- xaihi test rig, round 16: the small Ranges questions left open.  Round-11 mesh,
reused as is.  Every entry reads L_Thigh.X (ReadMode 3), joint-group counts 0, all tail / unknown bytes at
their usual values (+75 = 2, the rest 0) unless the line says otherwise.  Default map: -90..90 degrees
to gain * degrees, gains X 0.5, Y 0.8, Z -0.9 (translation cm: 0.03, 0.05, -0.04; scale 1 +- 0.003 * deg).

  [08]     A  type 1 F49 X                              control
  [09-11]  F  X, Y, Z: two-point map, source byte +28 = 1 / 2; three-point map (-90,-30,90 -> -45,-10,45) with +28 = 3
                        what do interpolation bytes 1 and 2 do, and does 3 ease each segment of a three-point map?
  [12-13]  D  type 4: X F49 (add), Y F48 (replace)      (rest (-2,17,-23))
  [14-15]  G  type 6: X F49, Y F48
  [16-17]  B  type 5: X F49, Y F48                      bit0 mixed on a non-Euler type
  [18]     H  type 0 F17 X, +72 = 2, +74 = 5, +75 = 8   do the unknown bytes matter on a translation?
  [19]     I  type 2 F17 Y, +72 = 2, +74 = 5, +75 = 8   ... on a scale?
  [20-21]  J  type 0 F17 X (+75 = 2) then type 1 F49 X (+75 = 8)    one bone, a translation and a rotation
  [22-23]  K  the same with +75 = 2 on both                          (shipped mixed files split 2 / 8)
"""
import contextlib
import copy
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'modules'))

from modules.jcns_parser import JCNSParser
from modules.jcns_writer import JCNSWriter, tail_group_counts

DIR = r"E:/Program/Steam/steamapps/common/MonsterHunterWilds/natives/STM/art/model/character/ch03/xaihi"
SRC = DIR + "/xaihi_constraint.jcns.102.orig_20260929"
FIRST_OUT = 8
ROT_GAIN = {'X': 0.5, 'Y': 0.8, 'Z': -0.9}
POS_GAIN = {'X': 0.03, 'Y': 0.05, 'Z': -0.04}
SCALE_GAIN = {'X': 0.003, 'Y': 0.003, 'Z': 0.003}


def anchors(tt, axis):
    if tt == 0:
        g = POS_GAIN[axis]
        return (-90.0, 0.0, 90.0), (-90 * g, 0.0, 90 * g)
    if tt == 2:
        g = SCALE_GAIN[axis]
        return (-90.0, 0.0, 90.0), (1 - 90 * g, 1.0, 1 + 90 * g)
    g = ROT_GAIN[axis]
    return (-90.0, 0.0, 90.0), (-90 * g, 0.0, 90 * g)


def E(bone, tt, flags, axis, **kw):
    return dict(bone=bone, tt=tt, flags=flags, axis=axis, **kw)


ENTRIES = [
    E('A', 1, 49, 'X'),
    E('F', 1, 49, 'X', src28=1, curve=0), E('F', 1, 49, 'Y', src28=2, curve=0),
    E('F', 1, 49, 'Z', src28=3, curve=3, frm=(-90.0, -30.0, 90.0), to=(-45.0, -10.0, 45.0)),
    E('D', 4, 49, 'X'), E('D', 4, 48, 'Y'),
    E('G', 6, 49, 'X'), E('G', 6, 48, 'Y'),
    E('B', 5, 49, 'X'), E('B', 5, 48, 'Y'),
    E('H', 0, 17, 'X', b72=2, b74=5, b75=8),
    E('I', 2, 17, 'Y', b72=2, b74=5, b75=8),
    E('J', 0, 17, 'X', b75=2), E('J', 1, 49, 'X', b75=8),
    E('K', 0, 17, 'X', b75=2), E('K', 1, 49, 'X', b75=2),
]


def main(dst):
    p = JCNSParser(SRC)
    with contextlib.redirect_stdout(io.StringIO()):
        cons = p.parse()
    assert len(cons) == 8
    tmpl = copy.deepcopy(cons[0])
    for c in cons:
        t = bytearray(c['TailBytes'])
        t[3] = 0
        c['TailBytes'] = bytes(t)
    for e in ENTRIES:
        i = 'XYZ'.index(e['axis'])
        frm, to = anchors(e['tt'], e['axis'])
        frm, to = e.get('frm', frm), e.get('to', to)
        c = copy.deepcopy(tmpl)
        c.update(ObjectName='TestTgt' + e['bone'], TransformType=e['tt'], Flags=e['flags'],
                 TransformAxis_parent=i, target_axis=i, UnknownByte72=e.get('b72', 0), UnknownFloat2=(0.0, 0.0))
        tail = bytearray(c['TailBytes'])
        tail[0], tail[1], tail[3] = e.get('b74', 0), e.get('b75', 2), 0
        c['TailBytes'] = bytes(tail)
        c['sources'][0].update(
            SourceName='L_Thigh', source_axis=0, ReadMode=3, CurveMode=e.get('curve', 0), EulerOrder=0,
            Interpolation=e.get('src28', 0), ref_frame_x=0.0, ref_frame_y=0.0, ref_frame_z=0.0, ref_frame_w=1.0,
            from_start=frm[0], from_kink=frm[1], from_end=frm[2], to_start=to[0], to_kink=to[1], to_end=to[2],
            ComplexMapping=[], ComplexMappingInfoCount=0)
        cons.append(c)
    assert len(cons) == FIRST_OUT + len(ENTRIES) and tail_group_counts(cons) == [0] * len(cons)
    JCNSWriter(p, dst).build_lossless()
    return check(dst)


def check(dst):
    q = JCNSParser(dst)
    with contextlib.redirect_stdout(io.StringIO()):
        back = q.parse()
    assert len(back) == FIRST_OUT + len(ENTRIES) and [c['TailBytes'][3] for c in back] == [0] * len(back)
    for i, (c, e) in enumerate(zip(back[FIRST_OUT:], ENTRIES)):
        s = c['sources'][0]
        assert (c['ObjectName'], c['TransformType'], c['Flags'], 'XYZ'[c['target_axis']]) == \
            ('TestTgt' + e['bone'], e['tt'], e['flags'], e['axis']), i
        assert (c['TailBytes'][0], c['TailBytes'][1], c['UnknownByte72']) == (e.get('b74', 0), e.get('b75', 2), e.get('b72', 0)), i
        assert s['Interpolation'] == e.get('src28', 0) and s['CurveMode'] == e.get('curve', 0), i
        print(f"[{FIRST_OUT + i:02}] {c['ObjectName']:<11} TT={e['tt']} F={e['flags']} .{e['axis']} curve={s['CurveMode']} "
              f"src+28={s['Interpolation']} +72/74/75={c['UnknownByte72']}/{c['TailBytes'][0]}/{c['TailBytes'][1]}"
              f" map {s['from_start']:g},{s['from_kink']:g},{s['from_end']:g} -> {s['to_start']:.3g},{s['to_kink']:.3g},{s['to_end']:.3g}")
    return q


if __name__ == '__main__':
    if '--output' not in sys.argv:
        sys.exit("give --output <path>; this script never overwrites the game's jcns on its own")
    main(sys.argv[sys.argv.index('--output') + 1])
