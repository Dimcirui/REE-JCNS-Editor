"""
RE Mesh Editor's RE9 bone axis correction, seen from the jcns side.

REME shows RE9 bones with rest = file @ C^-1 and keeps C on each bone as
``reAxisCorrection`` (row-major 3x3); only its exporter multiplies C back.  jcns
values live in the file's bone frames, so whatever is read off or written to a pose
bone goes through C here:

  file frame        = Blender frame @ C           (rest or posed, any space)
  file basis        = C^-1 @ Blender basis @ C
  file vector       = C^-1 @ Blender vector       (a location basis, a bone-local offset)

Like REME's exporter, a bone counts as corrected whenever it carries the property.
"""

from mathutils import Matrix, Quaternion, Vector

PROP = "reAxisCorrection"
_EPS = 1e-6


def correction(bone):
    """C of a bpy Bone as a 3x3 Matrix, or None when it has none (or it is identity)."""
    if bone is None:
        return None
    v = bone.get(PROP)
    if v is None:
        return None
    v = list(v)
    if len(v) != 9:
        return None
    c = Matrix((v[0:3], v[3:6], v[6:9]))
    if all(abs(c[i][j] - (i == j)) < _EPS for i in range(3) for j in range(3)):
        return None
    return c


def quat(bone):
    """C as a quaternion (w, x, y, z), or None."""
    c = correction(bone)
    if c is None:
        return None
    q = c.to_quaternion().normalized()
    return (q.w, q.x, q.y, q.z)


def file_matrix(bone, m):
    """A 4x4 frame of `bone` (its matrix_local, pose matrix or a world matrix of either)
    in the file's axes."""
    c = correction(bone)
    return m @ c.to_4x4() if c is not None else m


def rest_local(bone):
    """`bone`'s rest relative to its parent in the file's frames, 4x4; None for a root."""
    if bone is None or bone.parent is None:
        return None
    return (file_matrix(bone.parent, bone.parent.matrix_local).inverted()
            @ file_matrix(bone, bone.matrix_local))


def axis_map(bone):
    """For each file axis, the Blender bone axis it runs along (the largest component
    of C's column).  Exact for the axis-aligned C of the body bones; the thumbs and
    other tilted frames get the nearest axis."""
    c = correction(bone)
    if c is None:
        return (0, 1, 2)
    return tuple(max(range(3), key=lambda j: abs(c[j][i])) for i in range(3))


def to_file_basis(bone, loc, rot, scale):
    """A Blender pose basis (location, quaternion (w, x, y, z), scale) as the file
    reads it."""
    c = correction(bone)
    if c is None:
        return tuple(loc), tuple(rot), tuple(scale)
    cq = c.to_quaternion().normalized()
    q = cq.inverted() @ Quaternion(rot) @ cq
    v = c.inverted() @ Vector(loc)
    m = axis_map(bone)
    return tuple(v), (q.w, q.x, q.y, q.z), tuple(scale[m[i]] for i in range(3))


def to_blender_basis(bone, loc, rot, scale):
    """The inverse of to_file_basis."""
    c = correction(bone)
    if c is None:
        return tuple(loc), tuple(rot), tuple(scale)
    cq = c.to_quaternion().normalized()
    q = cq @ Quaternion(rot) @ cq.inverted()
    v = c @ Vector(loc)
    m = axis_map(bone)
    out = [1.0, 1.0, 1.0]
    for i in range(3):
        out[m[i]] = scale[i]
    return tuple(v), (q.w, q.x, q.y, q.z), tuple(out)
