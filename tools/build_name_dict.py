"""
build_name_dict.py
------------------
Build modules/data/joint_names.tsv.gz: every name RE Engine hashes in a .jcns,
keyed by that hash (MurmurHash3 of the name as UTF-16LE, seed 0xFFFFFFFF — the
same function the files use), so the add-on can show a name where a file only
stores the hash (Multi / Aim / RotExpression joints, Material joints, the
ReadJointTable, ...).

Names are collected from
  * .jcns files: constraint targets, sources, property names, ConeInput names
  * .mesh files: the name table (joints and materials)
  * .motlist / .mot files: bone header names
read from the vanilla paks of one game (MH Wilds here; needs its file list) and
from any number of already-extracted trees.

Only vanilla data belongs in the dictionary: pak_mods/ is never read, and paks
installed by a mod manager must be excluded by name (--skip-pak).

Example:
    python tools/build_name_dict.py \\
        --game "E:/Program/Steam/steamapps/common/MonsterHunterWilds" \\
        --filelist "E:/Data/MOD工具/RE9/REE PAK/ree-pak-tools/filelist/MHWs_STM_Release_MOD.list" \\
        --asset-lib "E:/Data/Github/Python/RE-Asset-Library-main" \\
        --skip-pak re_chunk_000.pak.sub_000.pak.patch_016.pak \\
        --skip-pak re_chunk_000.pak.sub_000.pak.patch_017.pak \\
        --extract "E:/.../RE4_EXTRACT" --extract "E:/.../requiem/EXTRACT"

Not shipped with the add-on (build_addon.py only packs the add-on sources).
"""

import argparse
import collections
import contextlib
import glob
import gzip
import io
import os
import re
import struct
import sys
import time
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(REPO, 'modules'), os.path.join(REPO, 'modules', 'hashing')]

import mesh_joints                                    # noqa: E402
from jcns_parser import JCNSParser                    # noqa: E402
from mmh3.pymmh3 import hashUTF16                     # noqa: E402

OUT = os.path.join(REPO, 'modules', 'data', 'joint_names.tsv.gz')
MOTION = re.compile(r'\.(motlist|mot)\.\d+$', re.I)
MESH = re.compile(r'\.mesh\.\d+$', re.I)
JCNS = re.compile(r'\.jcns\.\d+$', re.I)


# ── collecting ─────────────────────────────────────────────────────────────

class Names:
    """Names by source, in first-seen order; jcns names win a hash collision."""

    def __init__(self):
        self.by_source = collections.OrderedDict((k, []) for k in ('jcns', 'mesh', 'motion'))
        self._seen = set()

    def add(self, source, name):
        if name and name not in self._seen and '\0' not in name and '\n' not in name and '\t' not in name:
            self._seen.add(name)
            self.by_source[source].append(name)


def names_from_jcns(data, path, out):
    p = JCNSParser(path)
    p.filepath = path
    with contextlib.redirect_stdout(io.StringIO()):
        if data is None:
            p.parse()
        else:                                  # parse from memory
            tmp = path + '.tmp_names'
            with open(tmp, 'wb') as f:
                f.write(data)
            try:
                p.filepath = tmp
                p.parse()
            finally:
                os.remove(tmp)
    for c in p.constraints:
        out.add('jcns', c.get('ObjectName'))
        out.add('jcns', c.get('PropertyName'))
        for s in c.get('sources', []):
            out.add('jcns', s.get('SourceName'))
    for cd in getattr(p, 'cone_inputs', []):
        out.add('jcns', cd.get('Name'))


def names_from_mesh(data, out):
    try:
        joints = mesh_joints.read_joints(data)
    except (mesh_joints.MeshJointError, struct.error, UnicodeDecodeError):
        return
    for j in joints:
        out.add('mesh', j['name'])


def _wstr(d, o):
    e = o
    while e + 1 < len(d) and d[e:e + 2] != b'\0\0':
        e += 2
    return d[o:e].decode('utf-16-le', 'replace')


def names_from_motion(d, out):
    """Bone header names of every mot inside a motlist (or a bare mot)."""
    def mot(base):
        if d[base + 4:base + 8] != b'mot ':
            return
        hdr = struct.unpack_from('<Q', d, base + 16)[0]
        if not hdr:
            return
        arr, count = struct.unpack_from('<QQ', d, base + hdr)
        if not arr or count > 4096:
            return
        for i in range(count):
            name_off = struct.unpack_from('<Q', d, base + arr + 80 * i)[0]
            if name_off:
                out.add('motion', _wstr(d, base + name_off))

    try:
        if d[4:8] == b'mot ':
            mot(0)
        elif d[4:8] == b'mlst':
            n = struct.unpack_from('<I', d, 48 if struct.unpack_from('<I', d, 0)[0] < 1036 else 56)[0]
            ptrs = struct.unpack_from('<Q', d, 16)[0]
            for j in range(n):
                off = struct.unpack_from('<Q', d, ptrs + 8 * j)[0]
                if off and off + 8 <= len(d):
                    mot(off)
    except struct.error:
        pass


# ── pak reading ────────────────────────────────────────────────────────────

def vanilla_paks(game, skip):
    names = [n for n in os.listdir(game) if n.startswith('re_chunk_000.pak') and n.endswith('.pak') and n not in skip]

    def key(n):
        sub = re.search(r'sub_(\d+)', n)
        patch = re.search(r'patch_(\d+)\.pak$', n)
        return (int(sub.group(1)) + 1 if sub else 0, int(patch.group(1)) if patch else 0)
    return [os.path.join(game, n) for n in sorted(names, key=key)]


def read_from_paks(game, filelist, asset_lib, skip, out):
    sys.path.insert(0, asset_lib)
    import zstandard
    from modules.pak.file_re_pak import ReadPakTOC
    from modules.encryption.re_pak_encryption import decryptResource

    paths = [l.strip() for l in open(filelist, encoding='utf-8', errors='replace')
             if MESH.search(l.strip()) or MOTION.search(l.strip()) or JCNS.search(l.strip())]
    paths = [p for p in paths if '/streaming/' not in p.lower()]
    want = {(hashUTF16(p.lower()) & 0xFFFFFFFF, hashUTF16(p.upper()) & 0xFFFFFFFF): p for p in paths}
    where = {}
    for pak in vanilla_paks(game, skip):
        with contextlib.redirect_stdout(io.StringIO()):
            entries = ReadPakTOC(pak)
        for e in entries:
            k = (e.hashNameLower, e.hashNameUpper)
            if k in want:
                where[k] = (pak, e)                 # later paks override earlier ones
    print(f'{len(where)} of {len(paths)} listed jcns/mesh/motion files present in the paks')

    dz = zstandard.ZstdDecompressor()
    handles = {}
    tmp_dir = os.path.join(HERE, '_names_tmp')
    os.makedirs(tmp_dir, exist_ok=True)
    try:
        for k, (pak, e) in where.items():
            rel = want[k]
            f = handles.get(pak) or handles.setdefault(pak, open(pak, 'rb'))
            f.seek(e.offset)
            d = f.read(e.compressedSize if e.compressedSize else e.decompressedSize)
            try:
                if e.encryptionType > 0:
                    d = bytes(decryptResource(d))
                if e.compressionType == 1:
                    d = zlib.decompress(d, wbits=-zlib.MAX_WBITS)
                elif e.compressionType == 2:
                    d = dz.decompress(d, max_output_size=max(e.decompressedSize, 1) + 16)
            except Exception:
                continue
            if JCNS.search(rel):
                try:
                    names_from_jcns(d, os.path.join(tmp_dir, 'x' + rel[rel.rindex('.'):]), out)
                except Exception:
                    pass
            elif MESH.search(rel):
                names_from_mesh(d, out)
            else:
                names_from_motion(d, out)
    finally:
        for f in handles.values():
            f.close()
        for x in os.listdir(tmp_dir):
            os.remove(os.path.join(tmp_dir, x))
        os.rmdir(tmp_dir)


def read_from_tree(root, out):
    n = 0
    for f in glob.glob(os.path.join(root, '**', '*.*'), recursive=True):
        low = f.lower()
        if os.sep + 'streaming' + os.sep in low or os.sep + 'pak_mods' + os.sep in low:
            continue
        try:
            if JCNS.search(f):
                names_from_jcns(None, f, out)
            elif MESH.search(f):
                names_from_mesh(open(f, 'rb').read(), out)
            elif MOTION.search(f):
                names_from_motion(open(f, 'rb').read(), out)
            else:
                continue
            n += 1
        except Exception:
            pass
    print(f'{n} files read under {root}')


# ── writing ────────────────────────────────────────────────────────────────

def write(out, path):
    rows, hashes = [], {}
    collisions = 0
    for source, names in out.by_source.items():
        for name in names:
            h = hashUTF16(name) & 0xFFFFFFFF
            if h in hashes:
                collisions += 1
                continue                         # the earlier source wins
            hashes[h] = name
    for h in sorted(hashes):
        rows.append(f'{h:08x}\t{hashes[h]}\n')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with gzip.open(path, 'wt', encoding='utf-8', compresslevel=9) as f:
        f.write('# RE Engine joint / material / target names, keyed by murmur3(UTF-16LE, seed 0xFFFFFFFF)\n')
        f.write('# generated by tools/build_name_dict.py — do not edit by hand\n')
        f.writelines(rows)
    print({k: len(v) for k, v in out.by_source.items()},
          f'-> {len(hashes)} hashes, {collisions} collisions, {os.path.getsize(path) / 1024:.0f} KB')


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--game', help='game folder holding the re_chunk_000 paks')
    ap.add_argument('--filelist', help='REE PAK file list for that game')
    ap.add_argument('--asset-lib', help='RE-Asset-Library checkout (its modules/pak reads the paks)')
    ap.add_argument('--skip-pak', action='append', default=[], help='pak file name to ignore (mod-manager paks)')
    ap.add_argument('--extract', action='append', default=[], help='extracted tree to scan as well')
    ap.add_argument('--out', default=OUT)
    a = ap.parse_args()
    t0 = time.time()
    out = Names()
    if a.game:
        if not (a.filelist and a.asset_lib):
            ap.error('--game needs --filelist and --asset-lib')
        read_from_paks(a.game, a.filelist, a.asset_lib, set(a.skip_pak), out)
    for root in a.extract:
        read_from_tree(root, out)
    write(out, a.out)
    print(f'done in {time.time() - t0:.0f}s')


if __name__ == '__main__':
    main()
