"""
patch_jcns_anchor.py
---------------------
Surgical anchor-value patcher for in-game .jcns testing.

Locates one ConstraintSource by (source bone name, target axis, transform type)
inside a .jcns.102 file, overwrites one anchor field (from_start/from_kink/
from_end/to_start/to_kink/to_end), backs up the original next to it as
<name>.bak_<n>, and writes the patched file back to the SAME path (so it can
sit directly under a game's natives/ override folder for immediate testing).

Usage:
    python patch_jcns_anchor.py <jcns_file> --source-bone L_Thigh --target-axis Z \
        --field to_start --value 60

    # list constraints/sources in a file without changing anything:
    python patch_jcns_anchor.py <jcns_file> --list
"""
import argparse
import os
import shutil
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'modules'))

from modules.jcns_parser import JCNSParser
from modules.jcns_writer import JCNSWriter

AXIS_NAMES = ['X', 'Y', 'Z', 'W']
ANCHOR_FIELDS = ['from_start', 'from_kink', 'from_end', 'to_start', 'to_kink', 'to_end']


def _axis_str(v):
    if v is None:
        return '?'
    return AXIS_NAMES[v] if 0 <= v < len(AXIS_NAMES) else str(v)


def list_constraints(parser):
    for ci, c in enumerate(parser.constraints):
        print(f"[{ci}] target={c.get('TargetName')!r} TransformType={c.get('TransformType')} "
              f"target_axis={_axis_str(c.get('target_axis'))}")
        for si, s in enumerate(c.get('sources', [])):
            print(f"      src[{si}] {s.get('SourceName')!r} axis={_axis_str(s.get('source_axis'))} "
                  f"from=({s.get('from_start')}, {s.get('from_kink')}, {s.get('from_end')}) "
                  f"to=({s.get('to_start')}, {s.get('to_kink')}, {s.get('to_end')})")


def find_source(parser, source_bone, target_axis, transform_type):
    target_axis_idx = AXIS_NAMES.index(target_axis.upper()) if target_axis else None
    matches = []
    for c in parser.constraints:
        if transform_type is not None and c.get('TransformType') != transform_type:
            continue
        if target_axis_idx is not None and c.get('target_axis') != target_axis_idx:
            continue
        for s in c.get('sources', []):
            if source_bone and s.get('SourceName') != source_bone:
                continue
            matches.append((c, s))
    return matches


def backup(filepath):
    n = 1
    while True:
        cand = f"{filepath}.bak_{n}"
        if not os.path.exists(cand):
            shutil.copy2(filepath, cand)
            return cand
        n += 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('jcns_file')
    ap.add_argument('--list', action='store_true', help='list constraints/sources and exit')
    ap.add_argument('--source-bone', help='SourceName to match, e.g. L_Thigh')
    ap.add_argument('--target-axis', choices=AXIS_NAMES, help='target axis letter, e.g. Z')
    ap.add_argument('--transform-type', type=int, default=None,
                     help='filter by TransformType (1=Rotation, 0=Translation, 2=Scale)')
    ap.add_argument('--field', choices=ANCHOR_FIELDS, help='anchor field to overwrite')
    ap.add_argument('--value', type=float, help='new float value for --field')
    ap.add_argument('--out', help='output path (default: overwrite jcns_file in place, after backup)')
    args = ap.parse_args()

    parser = JCNSParser(args.jcns_file)
    parser.parse()

    if args.list:
        list_constraints(parser)
        return

    if not (args.source_bone and args.target_axis and args.field and args.value is not None):
        ap.error('--source-bone, --target-axis, --field and --value are all required unless --list is given')

    matches = find_source(parser, args.source_bone, args.target_axis, args.transform_type)
    if not matches:
        print('No matching source found. Run with --list to see what exists.')
        sys.exit(1)
    if len(matches) > 1:
        print(f'{len(matches)} sources matched — refine with --transform-type. Matches:')
        for c, s in matches:
            print(f"  {s.get('SourceName')} -> target_axis={_axis_str(c.get('target_axis'))} "
                  f"TransformType={c.get('TransformType')}")
        sys.exit(1)

    c, s = matches[0]
    old_value = s.get(args.field)
    print(f"Patching source {s.get('SourceName')!r} (target_axis={args.target_axis}, "
          f"TransformType={c.get('TransformType')}): {args.field} {old_value} -> {args.value}")
    s[args.field] = args.value

    out_path = args.out or args.jcns_file
    if out_path == args.jcns_file:
        bak = backup(args.jcns_file)
        print(f"Backed up original to {bak}")

    writer = JCNSWriter(parser, out_path)
    writer.build_lossless()
    print(f"Wrote patched file to {out_path}")


if __name__ == '__main__':
    main()
