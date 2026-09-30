"""Rank round-10 position/scale candidates against frame-aligned TRS capture.

Usage: python scripts/probes/analyze_pos_scale_rig.py --data <round10_keep>
Position threshold is 0.0001 cm; scale threshold is 0.00001 (dimensionless).
The 0.002-degree rule only applies to the rotation control. J/K are undriven
rest controls. Never infer a conclusion from missing data or a tied candidate.
"""
import argparse
import csv
import json
import math
from pathlib import Path


def read(path):
    with path.open(newline='') as f:
        rows = list(csv.DictReader(f))
    by_frame = {r['Frame']: r for r in rows}
    if not rows or len(by_frame) != len(rows):
        raise ValueError(f'Empty or duplicate frames: {path}')
    return by_frame


def vec(row, bone, kind):
    v = tuple(float(row[f'TestTgt{bone}_{kind}{a}']) for a in 'xyz')
    if not all(math.isfinite(x) for x in v):
        raise ValueError(f'Missing/nonfinite {bone}.{kind}; check recorder getters')
    return tuple(x*100 for x in v) if kind == 'p' else v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', type=Path, required=True)
    ap.add_argument('--json', type=Path)
    args = ap.parse_args()
    sweep = read(args.data / 'jcns_cm_rig_sweep.csv')
    trs = read(args.data / 'jcns_cm_rig_trs.csv')
    skel = read(args.data / 'jcns_cm_rig_skel.csv')
    if sweep.keys() != trs.keys() or sweep.keys() != skel.keys():
        raise ValueError('Capture frame sets differ; do not pair by row index')
    frames = list(sweep)
    if len(frames) < 100:
        raise ValueError('Need at least 100 captured frames')
    inputs = [float(sweep[f]['Out8']) / 0.5 for f in frames]
    if max(inputs)-min(inputs) < math.radians(30):
        raise ValueError('Input sweep is too narrow (<30 degrees)')
    # Rotation control: rest X=-2 degrees plus Out8. Normalize 5-decimal CSV.
    control_error = 0.0
    for f in frames:
        q = [float(skel[f]['TestTgtA_q'+a]) for a in 'xyzw']
        norm = math.sqrt(sum(x*x for x in q))
        if not math.isfinite(norm) or norm == 0:
            raise ValueError('Invalid rotation control quaternion')
        q = [x/norm for x in q]
        angle = math.radians(-2) + float(sweep[f]['Out8'])
        expected = (math.sin(angle/2), 0, 0, math.cos(angle/2))
        # Chord distance avoids acos cancellation near identical quaternions.
        chord = min(math.sqrt(sum((a-sign*b)**2 for a,b in zip(q, expected))) for sign in (1,-1))
        control_error = max(control_error, math.degrees(4*math.asin(min(1, chord/2))))
    if control_error > 0.002:
        raise ValueError(f'Rotation control failed: {control_error:.6f} degrees')
    report = {'frames': len(frames), 'rotation_control_max_deg': control_error, 'cases': {}}
    cases = [('B','p',9,'xyz'), ('C','p',12,'xyz'), ('D','s',15,'xyz'),
             ('E','s',18,'xyz'), ('F','p',21,'y'), ('G','p',22,'y'),
             ('H','s',23,'y'), ('I','s',24,'y')]
    for bone, kind, base, axes in cases:
        errors = {}
        neutral = None
        for f in frames:
            r = trs[f]
            rest = vec(r, 'J', kind)
            if max(abs(a-b) for a,b in zip(rest, vec(r,'K',kind))) > 1e-5:
                raise ValueError('Undriven J/K disagree')
            if neutral is None:
                neutral = rest
            if max(abs(a-b) for a,b in zip(rest,neutral)) > 1e-5:
                raise ValueError('Undriven rest control is moving')
            actual = vec(r, bone, kind)
            raw = {a: float(sweep[f][f'Out{base+i}']) for i,a in enumerate(axes)}
            if not all(math.isfinite(x) for x in raw.values()):
                raise ValueError('Nonfinite output')
            for units, factor in [('raw',1.0), ('deg(raw)',180/math.pi)]:
                u = tuple(raw.get(a,0)*factor*(100 if kind == 'p' else 1) for a in 'xyz')
                candidates = {
                    'rest + output': tuple(rest[i]+u[i] for i in range(3)),
                    'replace written axes': tuple(u[i] if a in axes else rest[i] for i,a in enumerate('xyz')),
                    'replace whole vector (unwritten=0)': u,
                }
                if kind == 's':
                    candidates['rest * output (unwritten=1)'] = tuple(rest[i]*(u[i] if a in axes else 1) for i,a in enumerate('xyz'))
                    candidates['replace whole vector (unwritten=1)'] = tuple(u[i] if a in axes else 1 for i,a in enumerate('xyz'))
                else:
                    c, s = math.cos(math.radians(-2)), math.sin(math.radians(-2))
                    turned = (u[0], c*u[1]-s*u[2], s*u[1]+c*u[2])
                    candidates['rest + rest_rotation * output'] = tuple(rest[i]+turned[i] for i in range(3))
                    candidates['rest_rotation * output'] = turned
                for label, value in candidates.items():
                    name = units + ': ' + label
                    error = max(abs(a-b) for a,b in zip(actual,value))
                    errors[name] = max(errors.get(name,0),error)
        ranking = sorted(errors.items(), key=lambda x:x[1])
        threshold = 0.0001 if kind == 'p' else 0.00001
        passing = [name for name,error in ranking if error <= threshold]
        separated = len(passing) == 1 and ranking[1][1] >= max(threshold*10, ranking[0][1]*10)
        report['cases'][bone] = {'quantity':kind, 'threshold':threshold, 'rest':neutral,
                                 'passing':passing, 'ranking':ranking,
                                 'unique_match':separated}
        print(f'{bone} {kind}: threshold={threshold}; passing={passing}')
        for name,error in ranking[:5]:
            print(f'  {error:.8g} {name}')
    if args.json:
        args.json.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(f'Rotation control: {control_error:.6f} deg; frames={len(frames)}')


if __name__ == '__main__':
    main()
