"""
build_cm_rig.py -- xaihi test rig, 2026-09-29 round: ComplexMapping flag semantics +
whether a source that exists only on the equipment skeleton resolves.

Starts from the original 8-entry xaihi_constraint.jcns.102 (backed up as
.orig_20260929) and appends entries [08]..[15]; getOutputUserValue(i) is indexed by
entry order, so the originals keep 0..7.  Targets TestTgtA..H were added to
xaihi_model.mesh under COG (no weights) in the same round.

  [08] A <- L_Thigh.X   identity three-point          input reference / positive control
  [09] B <- L_Thigh.X   CM (-60,-45)->(60,45) flag 1  line-consistent tangents
  [10] C <- L_Thigh.X   same, flag 2                   line (clip Linear) or step (CurveType Constant)?
  [11] D <- L_Thigh.X   same keys, flat tangents, 0    Hermite S-curve or line?
  [12] E <- L_Thigh.X   same as D, flag 5
  [13] F <- L_Dress_HJ_00.X             identity      equipment-only source, constraint-driven
  [14] G <- hair_base_L_a_03_jnt_ctrl.X identity      equipment-only source, chain physics
  [15] H <- TestTgtA.X                  identity      new bone as source (the round-8 case)

Round 2 (same day) adds, with TestTgtI..K appended to the mesh:
  [16] I <- L_Thigh.X   flat tangents, flag 1   does flag 1 ignore tangents (line) or not?
  [17] J <- L_Thigh.X   flat tangents, flag 2
  [18] K <- L_Thigh.X   flat tangents, flag 8
and gives A-D and I-K one shadow-mesh vertex at weight 0.1 (E-H stay unweighted) to
see whether writes to unweighted test bones are what lands on the wrong joint.

Hidden fields follow the rotation settings earlier rounds proved live
(AttrFlags 49, InputType 3 = rotation, AttrFlags 3 = three-point).
"""
import copy
import io
import contextlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'modules'))

from modules.jcns_parser import JCNSParser
from modules.jcns_writer import JCNSWriter

DIR = r"E:/Program/Steam/steamapps/common/MonsterHunterWilds/natives/STM/art/model/character/ch03/xaihi"
SRC = DIR + "/xaihi_constraint.jcns.102.orig_20260929"
DST = DIR + "/xaihi_constraint.jcns.102"

IDENTITY = (-90.0, 0.0, 90.0, -90.0, 0.0, 90.0)


def cm_keys(flag, flat):
    """Two keys (-60,-45) -> (60,45), in the shipped layout: FromY/FromZ are the
    neighbouring segment lengths (first in_dx = 1 placeholder, last out_dx copies in_dx),
    ToY/ToZ the tangent rise.  The last key carries flag 0 as in shipped data."""
    dx, dy = 120.0, 90.0
    s = 0.0 if flat else dy / dx
    return [
        dict(FromX=-60.0, ToX=-45.0, FromY=1.0, ToY=s * 1.0, FromZ=dx, ToZ=s * dx, UnknownUInt32=flag),
        dict(FromX=60.0, ToX=45.0, FromY=dx, ToY=s * dx, FromZ=dx, ToZ=s * dx, UnknownUInt32=0),
    ]


ENTRIES = [
    ('TestTgtA', 'L_Thigh', IDENTITY, None),
    ('TestTgtB', 'L_Thigh', None, cm_keys(1, flat=False)),
    ('TestTgtC', 'L_Thigh', None, cm_keys(2, flat=False)),
    ('TestTgtD', 'L_Thigh', None, cm_keys(0, flat=True)),
    ('TestTgtE', 'L_Thigh', None, cm_keys(5, flat=True)),
    ('TestTgtF', 'L_Dress_HJ_00', IDENTITY, None),
    ('TestTgtG', 'hair_base_L_a_03_jnt_ctrl', IDENTITY, None),
    ('TestTgtH', 'TestTgtA', IDENTITY, None),
    ('TestTgtI', 'L_Thigh', None, cm_keys(1, flat=True)),
    ('TestTgtJ', 'L_Thigh', None, cm_keys(2, flat=True)),
    ('TestTgtK', 'L_Thigh', None, cm_keys(8, flat=True)),
]


def main():
    p = JCNSParser(SRC)
    with contextlib.redirect_stdout(io.StringIO()):
        cons = p.parse()
    assert len(cons) == 8, len(cons)
    tmpl = cons[0]
    for tgt, src, geo, cm in ENTRIES:
        c = copy.deepcopy(tmpl)
        c['ObjectName'] = tgt
        c['Axis_parent'] = c['target_axis'] = 0
        c['AttrFlags'] = 49
        c['TransformElement'] = 1
        s = c['sources'][0]
        s['SourceName'] = src
        s['source_axis'] = 0
        s['InputType'] = 3
        s['AttrFlags'] = 3
        if cm is None:
            (s['from_start'], s['from_kink'], s['from_end'],
             s['to_start'], s['to_kink'], s['to_end']) = geo
            s['ComplexMapping'] = []
            s['ComplexMappingInfoCount'] = 0
        else:
            for k in ('from_start', 'from_kink', 'from_end', 'to_start', 'to_kink', 'to_end'):
                s[k] = 0.0
            s['ComplexMapping'] = cm
            s['ComplexMappingInfoCount'] = len(cm)
        cons.append(c)
    assert cons is p.constraints
    JCNSWriter(p, DST).build_lossless()
    # read back
    q = JCNSParser(DST)
    with contextlib.redirect_stdout(io.StringIO()):
        back = q.parse()
    for i, c in enumerate(back):
        s = c['sources'][0]
        cm = s.get('ComplexMapping') or []
        print(f"[{i:02}] {c['ObjectName']:<14} <- {s['SourceName']:<26} F{c['AttrFlags']} +24={s['AttrFlags']} +25={s['InputType']}"
              f" from=({s['from_start']:g},{s['from_kink']:g},{s['from_end']:g}) to=({s['to_start']:g},{s['to_kink']:g},{s['to_end']:g})"
              + (" CM " + " ".join(f"[{r['FromX']:g},{r['ToX']:g} in({r['FromY']:g},{r['ToY']:g}) out({r['FromZ']:g},{r['ToZ']:g}) f{r['UnknownUInt32']}]" for r in cm) if cm else ""))


if __name__ == '__main__':
    main()
