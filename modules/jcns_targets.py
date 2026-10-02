"""
How a constraint's target is named: which TransformTypes name it by hash alone, and
the name-derived hashes the Blender side stores only when they disagree with the name.

An override of 0 means "derive it from the name"; the exporter writes the derived
hash then.  No `bpy` import.
"""

import os
import sys

# Targets that are not in the hash table (ObjectHashIndex = 0xFFFFFFFF): blend shapes,
# material and RSZ property targets, named outputs.  Bone targets are always indexed.
DIRECT_TARGET_TYPES = frozenset({3, 7, 8, 9, 10, 11, 12})

# Types that carry a PropertyName (material parameter, RSZ component property).
PROPERTY_TYPES = frozenset({7, 8, 9, 10, 11})


def is_direct_target(transform_element):
    """Whether a TransformElement byte names its target by ObjectHash instead of a hash-table index."""
    return transform_element in DIRECT_TARGET_TYPES


def has_property_name(transform_element):
    return transform_element in PROPERTY_TYPES


def name_hash(name):
    """The uint32 hash the engine files a name under (MurmurHash3 of its UTF-16LE form)."""
    hashing_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'hashing')
    if hashing_dir not in sys.path:
        sys.path.insert(0, hashing_dir)
    from mmh3.pymmh3 import hashUTF16
    return hashUTF16(name) & 0xFFFFFFFF


def to_signed32(value):
    value &= 0xFFFFFFFF
    return value - (1 << 32) if value >= (1 << 31) else value


def property_hash(prop_name, override=0):
    """PropertyHash to write: the override when set, else the property name's hash, else 0."""
    if override:
        return override & 0xFFFFFFFF
    return name_hash(prop_name) if prop_name else 0


def object_hash(target_name, override=0):
    """ObjectHash of a direct target: the override when set, else the target name's hash."""
    if override:
        return override & 0xFFFFFFFF
    return name_hash(target_name)


def property_hash_override(stored, prop_name):
    """The signed override that makes property_hash() return `stored`, 0 when the name already gives it.

    A stored 0 next to a named property has no override (0 means "derive").
    """
    return 0 if stored == property_hash(prop_name) else to_signed32(stored)


def object_hash_override(stored, target_name):
    return 0 if stored == object_hash(target_name) else to_signed32(stored)
