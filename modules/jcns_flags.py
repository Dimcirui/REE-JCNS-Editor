"""
Meaning of OutputData's `flags_cns` bits, and which follow from the
transform type.

    bit 4   the constraint drives a bone, not a material / blend weight
    bit 5   the driven quantity is angular
    bit 0   per-constraint, not derivable from the type; no effect on the curve

In v36 and v102 bits 4 and 5 are a pure function of the transform type, so the
exporter recomputes them; otherwise changing a transform type in the UI would
leave stale flags.  In v35 the rule does not hold (AxisRotation often has bit 5
clear), so those files keep their raw bits; older versions have no AttrFlags byte.
No `bpy` import.
"""

JOINT_BIT = 4

DERIVED_BITS_VERSIONS = frozenset({36, 102})
ANGULAR_BIT = 5

# transform type -> (drives a bone, quantity is angular)
TRANSFORM_FLAGS = {
    'Trans':    (True,  False),
    'Rot':       (True,  True),
    'Scale':          (True,  False),
    'Deform':     (False, False),
    'RotRPY':      (True,  True),
    'RotPYR':   (True,  True),
    'ExpMap':      (True,  True),
    'Material': (False, False),
    'MaterialF4':    (False, False),
    'MaterialPosF4':    (False, False),
    'MaterialRotF4':    (False, False),
    'ComponentProperty':         (False, False),
    'UserValue':     (False, False),
    'Rot2': (True,  True),
    'RotRPY2': (True,  True),
    # Assumed to follow their siblings; not seen in shipped files.
    'RotPYR2': (True,  True),
    'ExpMap2': (True,  True),
}


def expected_bits(transform_element):
    """(is_joint, is_angular) for a transform type, or None if unknown."""
    return TRANSFORM_FLAGS.get(transform_element)


def is_angular(transform_element, flags=None):
    """Whether the driven quantity is a rotation.

    The transform type wins, since that is what the user edits; bit 5 of
    `flags` is the fallback for unknown types.
    """
    known = TRANSFORM_FLAGS.get(transform_element)
    if known is not None:
        return known[1]
    if flags is not None:
        return bool((int(flags) >> ANGULAR_BIT) & 1)
    return False


def apply_derived_bits(flags, transform_element):
    """`flags` with bits 4 and 5 rewritten to match the transform type.

    Other bits are preserved; an unknown transform type leaves the flags alone.
    """
    known = TRANSFORM_FLAGS.get(transform_element)
    if known is None:
        return int(flags) & 0xFF
    joint, angular = known
    out = int(flags) & 0xFF
    for bit, on in ((JOINT_BIT, joint), (ANGULAR_BIT, angular)):
        out = (out | (1 << bit)) if on else (out & ~(1 << bit))
    return out & 0xFF


def describe_bits(flags):
    """Human-readable breakdown, for tooltips and diagnostics."""
    f = int(flags) & 0xFF
    return {
        'raw': f,
        'binary': format(f, '08b'),
        'drives_joint': bool(f >> JOINT_BIT & 1),
        'angular': bool(f >> ANGULAR_BIT & 1),
        'bit0': bool(f & 1),
    }
