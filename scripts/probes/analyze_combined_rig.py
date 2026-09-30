"""Round 11 candidate ranking. Requires the deployed round11_plan.json and 3 CSVs.

Quaternions are normalized by scipy before comparison. Results need a unique
candidate within 0.002 degrees / 0.0001 cm / 0.00001 scale respectively.
An engine-rest mismatch invalidates the experiment instead of proving a formula.
"""
import argparse
import json
from pathlib import Path
import math
import numpy as np
from scipy.spatial.transform import Rotation as Rot
from analyze_pos_scale_rig import read, vec


def angle(a,b):
    return float(np.degrees((a.inv()*b).magnitude()).max())


def ranking(actual,candidates,tolerance,rotation=False):
    errors = [(angle(actual,v) if rotation else float(np.max(np.abs(actual-v))),k)
              for k,v in candidates.items()]
    errors.sort()
    passed=[k for e,k in errors if e <= tolerance]
    return dict(ranked=[dict(candidate=k,max_error=e) for e,k in errors],
        passing=passed,unique_match=len(passed)==1 and errors[1][0] > 10*max(tolerance,errors[0][0]))


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--data',type=Path,required=True)
    ap.add_argument('--plan',type=Path)
    ap.add_argument('--json',type=Path)
    args=ap.parse_args()
    plan=json.loads((args.plan or args.data/'round11_plan.json').read_text(encoding='utf-8'))
    assert plan['round']==11 and len(plan['entries'])==36
    S=read(args.data/'jcns_cm_rig_sweep.csv')
    Q=read(args.data/'jcns_cm_rig_skel.csv')
    T=read(args.data/'jcns_cm_rig_trs.csv')
    if S.keys()!=Q.keys() or S.keys()!=T.keys(): raise ValueError('Frame sets differ')
    frames=list(S)
    if len(frames)<100: raise ValueError('Need at least 100 frames')
    def out(i):
        result=np.array([float(S[f][f'Out{i}']) for f in frames])
        if not np.isfinite(result).all(): raise ValueError('Nonfinite output')
        return result
    inputs=out(8)/.5
    if np.ptp(inputs)<math.radians(30): raise ValueError('Input span <30 degrees')
    def quat(b):
        result=np.array([[float(Q[f][f'TestTgt{b}_q{a}']) for a in 'xyzw'] for f in frames])
        if not np.isfinite(result).all() or np.any(np.linalg.norm(result,axis=1)<.5):
            raise ValueError('Invalid quaternion')
        return Rot.from_quat(result)
    def trs(b,kind): return np.array([vec(T[f],b,kind) for f in frames])
    def rest(b):
        d=plan['rests'][b]
        w,x,y,z=d['quaternion_wxyz']
        return Rot.from_quat([x,y,z,w])
    def outputs(b,tt):
        values=np.zeros((len(frames),3)) if tt!=2 else np.ones((len(frames),3))
        for e in plan['entries']:
            if e['bone']==b and e['type']==tt:
                values[:,'XYZ'.index(e['axis'])]=out(e['out'])
        return values
    control=angle(quat('A'),rest('A')*Rot.from_euler('x',out(8)[:,None]))
    g=plan['rests']['G']
    baseline=dict(rotation_deg=angle(quat('G'),rest('G')),
        scale_error=float(np.max(np.abs(trs('G','s')-g['scale']))),
        position_cm=float(np.max(np.abs(trs('G','p')-np.array(g['position_m'])*100))))
    if control>.002 or baseline['rotation_deg']>.002 or baseline['scale_error']>.00001 or baseline['position_cm']>.0001:
        raise ValueError(f'Control/rest mismatch; check mesh loaded by game: control={control}, G={baseline}')
    result=dict(round=11,frames=len(frames),input_degrees=[float(np.degrees(inputs.min())),float(np.degrees(inputs.max()))],
        control_error_deg=control,baseline_G=baseline,rotation={},scale={},coexist={})
    for b in 'BCD':
        e=np.tile(plan['rests'][b]['euler_xyz_rad'],(len(frames),1))
        values=outputs(b,1)
        for entry in plan['entries']:
            if entry['bone']==b: e[:,'XYZ'.index(entry['axis'])]=out(entry['out'])
        candidates={'replace_written_rest_euler':Rot.from_euler('xyz',e),
            'replace_whole_rotation':Rot.from_euler('xyz',values),
            'rest_times_outputs':rest(b)*Rot.from_euler('xyz',values),
            'outputs_times_rest':Rot.from_euler('xyz',values)*rest(b),
            'unchanged_rest':rest(b)}
        result['rotation'][b]=ranking(quat(b),candidates,.002,True)
    for b in 'EF':
        v=outputs(b,2); scale=np.array(plan['rests'][b]['scale'])
        replaced=np.tile(scale,(len(frames),1)); replaced[:,1]=v[:,1]
        numeric_add=np.tile(scale,(len(frames),1)); numeric_add[:,1]+=v[:,1]
        result['scale'][b]=ranking(trs(b,'s'),{
            'replace_written_axis':replaced,'rest_times_output':scale*v,
            'replace_whole_vector':v,'rest_plus_output':numeric_add,
            'unchanged_rest':scale},.00001)
    for b,tt in [('H',13),('I',13),('J',14),('K',14)]:
        v=outputs(b,tt); r=Rot.from_euler('xyz',v); q=quat(b)
        p=np.array(plan['rests'][b]['position_m'])*100
        dp=outputs(b,0)*100 # Out/native position metres; ranking centimetres.
        s=outputs(b,2)
        result['coexist'][b]=dict(rotation=ranking(q,{
            'rest_times_rotation':rest(b)*r,'rotation_times_rest':r*rest(b),
            'rotation_without_rest':r,'rotation_ignored':rest(b)},.002,True),
            position=ranking(trs(b,'p'),{'rest_plus_parent_axis_output':p+dp,
                'rest_plus_rest_rotated_output':p+rest(b).apply(dp),
                'rest_plus_current_rotated_output':p+q.apply(dp),
                'position_output_only':dp,'position_ignored':p},.0001),
            scale=ranking(trs(b,'s'),{'scale_output':s,'scale_ignored':np.ones(3)},.00001))
    result['paired']={a+b:dict(rotation_deg=angle(quat(a),quat(b)),
        position_cm=float(np.max(np.abs(trs(a,'p')-trs(b,'p')))),
        scale_error=float(np.max(np.abs(trs(a,'s')-trs(b,'s'))))) for a,b in [('H','I'),('J','K'),('H','J'),('I','K')]}
    # D writes all axes, so per-axis and whole-rotation replacement coincide.
    # It is a composition control, while B/C distinguish the replacement rules.
    result['all_axes_control_passed']=result['rotation']['D']['ranked'][0]['max_error']<=.002
    ranks=[result['rotation'][b] for b in 'BC']+list(result['scale'].values())
    ranks += [r for b in result['coexist'].values() for r in b.values()]
    result['all_unique']=result['all_axes_control_passed'] and all(r['unique_match'] for r in ranks)
    text=json.dumps(result,indent=2)
    print(text)
    if args.json: args.json.write_text(text,encoding='utf-8')
    if not result['all_unique']: raise SystemExit('Unresolved/failed candidates: do not infer a conclusion')


if __name__=='__main__': main()
