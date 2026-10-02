"""
convert_jcns_v29_to_v102.py
----------------------------
Convert a .jcns.29 file (Monster Hunter Wilds before TU4) to .jcns.102 (after TU4).

The conversion itself is modules/jcns_upgrade.py; this is the command line around it.
A file with Multi or Aim sections also needs the ReadJointTable v102 added, which is
derived from the skeleton: pass the character's .mesh, or leave it out and the one
.mesh next to the file is used.

Usage:
    python convert_jcns_v29_to_v102.py <input.jcns.29> [-o output.jcns.102] [--mesh file.mesh]
"""
import argparse
import glob
import os
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, os.path.join(ROOT, 'modules'))
sys.path.insert(0, os.path.join(ROOT, 'tools'))

import jcns_upgrade                    # noqa: E402
import mesh_joints                     # noqa: E402
from jcns_parser import JCNSParser     # noqa: E402
from jcns_writer import JCNSWriter     # noqa: E402


def skeleton_from_mesh(path):
    """({joint hash: parent hash or None}, {joint hash: name}) of a .mesh file."""
    with open(path, 'rb') as f:
        joints = mesh_joints.read_joints(f.read())
    h = lambda name: jcns_upgrade.hashUTF16(name) & 0xFFFFFFFF
    parent = {h(j['name']): (h(joints[j['parent']]['name']) if j['parent'] >= 0 else None) for j in joints}
    return parent, {h(j['name']): j['name'] for j in joints}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('input', help='path to the .jcns.29 file')
    ap.add_argument('-o', '--out', help='output path (default: same name with .jcns.102)')
    ap.add_argument('--mesh', help='.mesh whose skeleton the ReadJointTable is derived from')
    args = ap.parse_args()

    parser = JCNSParser(args.input)
    parser.parse()
    if parser.version != 29:
        sys.exit(f'{args.input}: version {parser.version}, not 29')

    parent = names = None
    mesh = args.mesh
    if not mesh and parser.multi_constraints:
        found = glob.glob(os.path.join(os.path.dirname(os.path.abspath(args.input)), '*.mesh.*'))
        mesh = found[0] if len(found) == 1 else None
    if mesh:
        parent, names = skeleton_from_mesh(mesh)
        print(f'Skeleton from {mesh}')

    upgraded, problems = jcns_upgrade.upgrade(parser, 102, parent, names)
    if problems:
        sys.exit('\n'.join(problems) + '\n(pass --mesh)')

    out = args.out
    if not out:
        root = args.input[:-len('.jcns.29')] if args.input.endswith('.jcns.29') else args.input
        out = root + '.jcns.102'
    JCNSWriter(upgraded, out).build_lossless()
    print(f'Wrote {out}')


if __name__ == '__main__':
    main()
