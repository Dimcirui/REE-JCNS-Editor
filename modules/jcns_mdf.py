"""
jcns_mdf.py
-----------
Material and parameter names from a .mdf2, for the Material section.

A Material record holds only two hashes: murmur3 of the UTF-16 material name and of
the parameter name.  An .mdf2 stores the same hashes next to the names it lists
(the material header's name hash, each property's "unicode" hash), so reading one
gives name <-> hash pairs that need no recomputation.

Layout as RE Mesh Editor reads it (file_re_mdf.py), keyed on the extension's version
(10 DMC5/RE2 ... 45 Wilds, 51 RE9).  Only names, hashes and component counts are read.
"""

import struct

HEADER_SIZE = 16
PROPERTY_SIZE = 24
MAGIC = 0x0046444D                     # b"MDF\0", little-endian


class MdfError(ValueError):
    pass


def _material_size(version):
    if version >= 51:
        return 108
    if version >= 31:
        return 100
    if version >= 19:
        return 80
    return 64


def _wstr(data, off):
    end = off
    while end + 1 < len(data) and data[end:end + 2] != b'\0\0':
        end += 2
    return data[off:end].decode('utf-16-le', errors='replace')


def version_of(path):
    """The mdf2 version from a path's numeric extension (".mdf2.45" -> 45)."""
    try:
        return int(str(path).rsplit('.', 1)[1])
    except (IndexError, ValueError):
        raise MdfError("no version extension: %s" % path)


def read(data, version):
    """[{'name', 'hash', 'params': [{'name', 'hash', 'count'}]}] in file order."""
    if len(data) < HEADER_SIZE:
        raise MdfError("file too short")
    magic, _ver, count = struct.unpack_from('<IHH', data, 0)
    if magic != MAGIC:
        raise MdfError("not an mdf2 file")
    size = _material_size(version)
    out = []
    for i in range(count):
        o = HEADER_SIZE + i * size
        name_off, name_hash, _block, n_props, _n_tex = struct.unpack_from('<QIiii', data, o)
        o += 24
        if version >= 19:
            o += 8                      # GPU buffer name / path counts
        if version >= 31:
            o += 4                      # bake texture array size
        o += 4                          # shader type
        o += 12 if version >= 31 else 4  # flags (+ flags B, shader LOD)
        if version >= 51:
            o += 8
        props_off = struct.unpack_from('<Q', data, o)[0]
        params = []
        for j in range(n_props):
            po = props_off + j * PROPERTY_SIZE
            p_name_off, p_hash, _ascii = struct.unpack_from('<QII', data, po)
            n = (struct.unpack_from('<H', data, po + 20)[0] if version >= 13
                 else struct.unpack_from('<i', data, po + 16)[0])
            params.append({'name': _wstr(data, p_name_off), 'hash': p_hash, 'count': n})
        out.append({'name': _wstr(data, name_off), 'hash': name_hash, 'params': params})
    return out


def read_file(path):
    with open(path, 'rb') as f:
        data = f.read()
    try:
        return read(data, version_of(path))
    except struct.error:
        raise MdfError("truncated or not this mdf2 version: %s" % path)


def catalog(materials_per_file):
    """Merge several files' materials: {material name: {'hash', 'params': {name: (hash, count)}}}.
    A material listed in more than one file keeps the union of its parameters."""
    out = {}
    for mats in materials_per_file:
        for m in mats:
            entry = out.setdefault(m['name'], {'hash': m['hash'], 'params': {}})
            for p in m['params']:
                entry['params'].setdefault(p['name'], (p['hash'], p['count']))
    return out


def names_by_hash(cat):
    """({material hash: name}, {(material name, parameter hash): parameter name})."""
    mats = {e['hash']: name for name, e in cat.items()}
    params = {(name, h): pname for name, e in cat.items() for pname, (h, _n) in e['params'].items()}
    return mats, params
