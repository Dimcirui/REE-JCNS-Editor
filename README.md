# REE JCNS Editor

A Blender add-on for importing, editing and exporting RE Engine `.jcns` (joint
constraint) files.

A JCNS file drives targets from joint poses: each constraint reads one axis of a
source joint (or how far a joint has swung into a cone) and maps it through a
curve onto another joint, a blendshape, a material parameter, an RSZ property or
a named output. The add-on turns a file into a collection of Empties you can
inspect and edit, can apply the constraints to an armature as live Blender
drivers so you can pose the rig and watch them work, and writes the file back.

Newer versions are rebuilt from scratch, so constraints, sources and section
entries can be added, deleted and re-pointed. Older versions are written back in
place: every value can change, the file's structure cannot.

Project home: <https://github.com/Dimcirui/REE-JCNS-Editor>

## Supported Games

| JCNS version | Game | Export |
| --- | --- | --- |
| 102 | Monster Hunter Wilds (post-TU4) | ✅ Full rebuild |
| 36 | Onimusha: Way of the Sword | ✏️ In place |
| 35 | Resident Evil Requiem / PRAGMATA / MH Stories 3 | ✅ Full rebuild |
| 29 | Monster Hunter Wilds (pre-TU4) | ✏️ In place |
| 24 | Dragon's Dogma 2 | ✏️ In place |
| 22 | RE4 / Street Fighter 6 | ✏️ In place |
| 21 | Monster Hunter Rise | ✏️ In place |
| 19 | RE2 / RE3 / RE7 ray-tracing updates | ✏️ In place |
| 16 | RE Village | ✏️ In place |
| 12 | RE3 | ✏️ In place |
| 11 | RE2 / Devil May Cry 5 | ✏️ In place |

**Full rebuild**: the whole file is regenerated.
**In place**: the original file is copied and each record is re-packed at its own
offset; export refuses structural edits and lists what changed.

## Supported Sections

| ID | Section | Full rebuild (v102, v35) | In place | Live preview |
| --- | --- | --- | --- | --- |
| 0 | Range constraints and sources | ✅ Fully editable | ✏️ Values | ✅ Drivers, measured in game |
| 0 | ComplexMapping (keyframed curves) | ✅ Edited as F-Curves in the Graph Editor | Kept | ✅ Previewed |
| 0 | ConeDrivers (v35) | ✅ Per-constraint cone inputs editable; cone table kept | Kept | — |
| 0 | Dependencies | ✅ Regenerated | Kept | — |
| 0 | ObjectSettings | Kept | Kept | — |
| 1 | RotExpression | ✅ Structurally editable | Kept | ≈ Pose-bone constraint; exact for gain (1,1,1) |
| 2 | SkinConstraint | ✅ Structurally editable ¹ | Kept | ≈ Armature constraint; position exact, rotation approximate |
| 3 | Aim | ✅ Structurally editable ¹ | Kept | ≈ Damped Track; exact for RotationType 4 only |
| 4 | Material constraints | ✅ Editable (raw values) | ✏️ Values | — |
| 5 | JointExportGraph | ✅ Path editable | Kept | — |

A file that has only Skin, Aim, RotExpression or Material entries (no Ranges) can
be exported too. The section table is rewritten to list exactly the sections that
have entries, since the engine runs no other.

*Structurally editable*: entries can be added, deleted and re-pointed; counts,
hash-list indices, derived tables and the section table (the engine runs only the
sections it lists) are regenerated on export. Fields with a known meaning are
shown as switches, enums and named numbers in each section's panel; fields whose
meaning is still unknown, and fields that never change, sit in collapsed
sub-panels.

¹ Files that carry a ReadJointTable (SkinConstraintHashTable in the 010 template
and REE-Lib) need the target armature set before Skin or Aim bones change: the
table is re-derived from the skeleton's hierarchy.

## Live preview

*Ranges* entries become Blender drivers; *Skin*, *Aim* and *RotExpression* become
native pose-bone constraints. The Ranges rules (how a source is read, how a value
is composed onto the rest pose, add and replace, interpolation, scale and
translation in a scaled parent) were measured in game on a test rig, and every
panel line marks a measured rule with a check mark and an inferred one with a
question mark. The Skin / Aim / RotExpression previews are approximations of the
measured behaviour and say where they differ. Not supported in the preview:
negative rest scales, Aim influence other than 1, Aim rotation offset (Vec0).

## Installation

Blender 4.2 or newer: `Edit > Preferences > Get Extensions > ⌄ > Install from
Disk...` and pick the `-extension-vX.Y.Z.zip`. Blender 3.6 – 4.1: `Edit >
Preferences > Add-ons > Install...` and pick the plain `-vX.Y.Z.zip`.
Both are built with `python build_addon.py --all`.

## Credits

* [NSACloud](https://github.com/NSACloud) — reference for the overall structural
  design of the add-on
* [XenonBaruku](https://github.com/XenonBaruku) — RE JCNS 010 Editor template
