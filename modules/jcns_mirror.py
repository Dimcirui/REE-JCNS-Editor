"""
Mirror a constraint mapping from one side of a rig to the other.

A mirrored pair relates as f_R(x) = out_sign * f_L(in_sign * x).  Both signs
come from the two bones' local frames: a reflection reverses handedness, so a
rotation of +t about world axis u becomes -t about M*u; if the other bone's
local axis is +M*u the mirrored angle is -t, if it is -M*u the negations cancel.
That per-axis sign (sigma) is a pseudovector sign, and each side applies it
according to its quantity:

  rotation      follows sigma
  translation   an ordinary vector, so -sigma
  scale, blend  neutral value 1.0, never negated

A source's reference frame (ref_frame) is a rotation in its local axes and reflects the same
way: its vector part is multiplied by sigma.  tests/test_mirror_math.py checks every read and
compose formula against this.

flags_cns bit 5 marks exactly the rotation/non-rotation distinction.  Some
shipped pairs are deliberately asymmetric, so an existing counterpart must not
be overwritten silently.  No `bpy` import.
"""

import re

from jcns_flags import is_angular as _is_angular_by_type
from jcns_mapping import source_quantity_of as _source_quantity_of

# Fallback when the armature is unavailable; other rigs may differ.
SIGMA_DEFAULT = {'X': +1, 'Y': -1, 'Z': -1, 'W': None}

OUTPUT_SIGN_BIT = 5


def output_sign_from_flags(flags):
    return +1 if (int(flags) >> OUTPUT_SIGN_BIT) & 1 else -1


def sigma_from_frames(left_cols, right_cols, tol=1e-3):
    """Per-axis mirror sign for one L/R bone pair.

    `left_cols` / `right_cols` are the two bones' three local axes in world
    space, as (x, y, z) triples.  Returns {'X': ±1, …} with None for an axis
    whose frames are not mirror-compatible.
    """
    def sub(a, b):
        return (a[0] - b[0], a[1] - b[1], a[2] - b[2])

    def add(a, b):
        return (a[0] + b[0], a[1] + b[1], a[2] + b[2])

    def length(v):
        return (v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) ** 0.5

    out = {}
    for i, ax in enumerate("XYZ"):
        u, v = left_cols[i], right_cols[i]
        m = (-u[0], u[1], u[2])            # reflect across the YZ plane
        if length(sub(v, m)) < tol:
            out[ax] = -1
        elif length(add(v, m)) < tol:
            out[ax] = +1
        else:
            out[ax] = None
    out['W'] = None
    return out


# Outputs with neutral value 1.0 (scale factors, blend weights): never negated.
UNSIGNED_OUTPUT_TYPES = frozenset({
    'Scale', 'Deform', 'ComponentProperty',
    'Material', 'MaterialF4', 'MaterialPosF4', 'MaterialRotF4',
})

def is_angular_output(transform_element, flags=None):
    """Whether the driven quantity is a rotation; flags bit 5 is the fallback
    for unknown transform types."""
    return _is_angular_by_type(transform_element, flags)


def _signed(sigma, quantity):
    """Mirror sign of one side (source or target) from its axis's sigma."""
    if quantity == 'Scale':
        return +1
    return -sigma if quantity == 'Translation' else sigma


def signs_for(source_axis, target_axis, flags, src_sigma=None, tgt_sigma=None,
              transform_element='Rot', mirror_in=True, mirror_out=True,
              source_quantity='Rotation'):
    """(in_sign, out_sign) for one source of one constraint.

    `src_sigma` / `tgt_sigma` are the per-axis dicts from sigma_from_frames() for
    the source and target bones; SIGMA_DEFAULT is used where they are missing.
    Returns (None, None) when either axis has no usable sign.

    `mirror_in` / `mirror_out` say whether the source / target side is
    reflected to a different bone at all.  A centre-line target driven from
    both thighs flips only its source.  A side that is not reflected keeps sign
    +1; SIGMA_DEFAULT describes a real mirror pair, not "unchanged".

    `source_quantity` is what the source reads (+25, see
    jcns_mapping.source_quantity).  Translation sources are mostly helper bones
    that do not share the main skeleton's frames, so they need measured sigma.
    """
    if mirror_in:
        if source_quantity == 'Scale':
            ss = +1
        else:
            ss = (src_sigma or SIGMA_DEFAULT).get(source_axis)
            if ss is None:
                return None, None
            ss = _signed(ss, source_quantity)
    else:
        ss = +1

    if not mirror_out:
        return ss, +1

    ts = (tgt_sigma or SIGMA_DEFAULT).get(target_axis)
    if ts is None:
        return None, None
    if transform_element in UNSIGNED_OUTPUT_TYPES:
        return ss, +1
    if is_angular_output(transform_element, flags):
        return ss, ts
    return ss, -ts


def mirror_triples(from_triple, to_triple, in_sign, out_sign):
    """Apply f_R(x) = out_sign * f_L(in_sign * x) to the stored anchors.

    Negating the input turns the MapFrom range around, so it is negated *and*
    reversed; MapTo is reversed alongside it to keep each output anchor paired
    with its own input anchor.  Only then does MapTo take its own sign.
    """
    fs, fk, fe = (float(v) for v in from_triple)
    ts, tk, te = (float(v) for v in to_triple)

    if in_sign < 0:
        fs, fk, fe = -fe, -fk, -fs
        ts, tk, te = te, tk, ts
    if out_sign < 0:
        ts, tk, te = -ts, -tk, -te

    return (fs, fk, fe), (ts, tk, te)


def mirror_source(source, source_axis, target_axis, flags,
                  src_sigma=None, tgt_sigma=None, transform_element='Rot',
                  mirror_in=True, mirror_out=True):
    """Mirror one source mapping. Returns (dict_of_anchors, in_sign, out_sign),
    or (None, None, None) when a sign is unusable; see signs_for()."""
    def g(name):
        if isinstance(source, dict):
            return float(source.get(name, 0.0) or 0.0)
        return float(getattr(source, name, 0.0))

    in_sign, out_sign = signs_for(source_axis, target_axis, flags,
                                  src_sigma, tgt_sigma, transform_element,
                                  mirror_in, mirror_out,
                                  _source_quantity_of(source))
    if in_sign is None:
        return None, None, None

    f, t = mirror_triples(
        (g('from_start'), g('from_kink'), g('from_end')),
        (g('to_start'), g('to_kink'), g('to_end')),
        in_sign, out_sign)
    return ({'from_start': f[0], 'from_kink': f[1], 'from_end': f[2],
             'to_start':   t[0], 'to_kink':   t[1], 'to_end':   t[2]},
            in_sign, out_sign)


# ---------------------------------------------------------------------------
# Bone-name side handling
# ---------------------------------------------------------------------------

# A standalone L/R token: 'hair_base_L_a_01' but never the L inside 'Colour'.
_SIDE_TOKEN = re.compile(r'(?<![A-Za-z])([LR])(?![A-Za-z])')


def token_swap(name):
    """Swap every standalone L/R token in a name.

    Covers mid-name markers such as 'hair_base_L_a_01_jnt_ctrl', which Blender's
    flip_name (start/end markers only) misses.
    """
    out, n = _SIDE_TOKEN.subn(lambda m: 'R' if m.group(1) == 'L' else 'L', name)
    return out if n else name


def counterpart(name, exists, flip_name):
    """Name of the bone on the other side, or None if it cannot be resolved.

    Name-driven, not position-driven: hair and cloth strands are named
    symmetrically but modelled asymmetrically, and coincident helper joints make
    the nearest mirrored bone ambiguous.
    """
    if not name:
        return None
    for candidate in (flip_name(name), token_swap(name)):
        if candidate and candidate != name and exists(candidate):
            return candidate
    return None


def side_from_position(x, deadzone=1e-4):
    """Side of a bone from its X position: L is +X, R is -X.

    Preferred over side_of(), since many sided bones carry no name marker.
    """
    if x > deadzone:
        return 'L'
    if x < -deadzone:
        return 'R'
    return None


def side_of(name, flip_name):
    """Side from the name alone — fallback when the bone is not in the armature."""
    if not name:
        return None
    other = flip_name(name)
    if other == name:
        other = token_swap(name)
    if other == name:
        return None
    for a, b in zip(name, other):
        if a != b:
            if a in 'Ll':
                return 'L'
            if a in 'Rr':
                return 'R'
            return None
    return None


def constraint_signature(target_bone, transform_element, target_axis, sources):
    """Identity used to decide whether a mirrored counterpart already exists.

    Includes the source bones because one bone axis can carry several
    constraints.
    """
    return (target_bone, transform_element, target_axis,
            tuple((s[0], s[1]) for s in sources))
