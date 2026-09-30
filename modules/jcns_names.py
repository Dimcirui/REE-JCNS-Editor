"""
jcns_names.py
-------------
Names for hashes a file stores without their string.

data/joint_names.tsv.gz maps a MurmurHash3 (UTF-16LE, seed 0xFFFFFFFF — what the
files store) to the joint, material or target name it came from, collected from
vanilla game data by tools/build_name_dict.py.  Every entry hashes back to its
own key, so a name taken from here exports as the very hash it replaced.

Loaded on first use.  No `bpy` import, so it stays testable without Blender.
"""

import gzip
import os

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'joint_names.tsv.gz')
_names = None


def _load():
    global _names
    if _names is None:
        _names = {}
        try:
            with gzip.open(PATH, 'rt', encoding='utf-8') as f:
                for line in f:
                    if line.startswith('#'):
                        continue
                    h, _, name = line.rstrip('\n').partition('\t')
                    if name:
                        _names[int(h, 16)] = name
        except OSError:
            pass                    # no dictionary: every lookup misses
    return _names


def name_of(h, default=None):
    """The name whose hash is `h`, or `default`."""
    return _load().get(h & 0xFFFFFFFF, default)


def size():
    return len(_load())
