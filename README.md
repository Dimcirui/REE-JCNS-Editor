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

## Supported Games

| JCNS version | Game | Export |
| --- | --- | --- |
| 102 | Monster Hunter Wilds (post-TU4) | ✅ Full rebuild |
| 36 | Onimusha: Way of the Sword | ✅ Full rebuild |
| 35 | Resident Evil Requiem / PRAGMATA / MH Stories 3 | ✅ Full rebuild |
| 29 | Monster Hunter Wilds (pre-TU4) | ⬆️ Imported as v102 |
| 24 | Dragon's Dogma 2 | ✏️ In place |
| 22 | RE4 / Street Fighter 6 | ✅ Full rebuild ³ |
| 21 | Monster Hunter Rise | ✏️ In place |
| 19 | RE2 / RE3 / RE7 ray-tracing updates | ✏️ In place |
| 16 | RE Village | ✏️ In place |
| 12 | RE3 | ✏️ In place |
| 11 | RE2 / Devil May Cry 5 | ✏️ In place |

**Full rebuild**: the whole file is regenerated.
³ v22 rebuilds Outputs, ConeInputs and ObjectSettings. A file that has Aim, RotExpression, Multi or Material
sections is written in place instead.
**Imported as v102**: an older file of a game that has a newer version is upgraded
on import and exported as that newer version. A file with Multi sections needs the
target armature to derive its ReadJointTable; export asks for it.
**v35 ⇄ v36 ⇄ v102**: Resident Evil Requiem, Onimusha and Wilds files can be exported as
each other (export dialog, *Export Version*). Bone names stay as they are, so they
must match the other game's skeleton. The conversion empties the ReadJointTable for v35
and v36 and derives it for v102 (a file with Multi or Aim needs its armature), clears
AttrFlags bit 5 for v35, sets the TailBytes[1] level byte to 0 for v35 and from 0 to 2
for v36 / v102, switches the file constant (Multi tail[0], Aim +59) between 0xFF (v35,
v36) and 5 (v102), and gives Multi records a tail the target ships (0101 for v35, 0001
for v36, 0000 for v102; their meaning is unknown, so export warns when it changes one).
**In place**: the original file is copied and each record is re-packed at its own
offset; export refuses structural edits and lists what changed. Everything the
in-place writer does not re-pack is kept byte for byte: ComplexMapping curves,
ConeInputs, Multi, Aim, RotExpression, ObjectSettings, the JointExprGraph path
and all hashes and names.

## Supported Sections

| ID | Section | Full rebuild (v102, v36, v35, v22) | In place |
| --- | --- | --- | --- |
| 0 | Range constraints and sources | ✅ Fully editable | ✏️ Values ² |
| 0 | ComplexMapping (keyframed curves) | ✅ Edited as F-Curves in the Graph Editor, previewed | Kept |
| 0 | ConeDrivers (v35) | ✅ Per-constraint cone inputs editable; cone table kept | Kept |
| 0 | Dependencies | ✅ Regenerated | Kept |
| 0 | ObjectSettings | Kept | Kept |
| 1 | RotExpression | ✅ Structurally editable | Kept |
| 2 | MultiConstraint | ✅ Structurally editable ¹ | Kept |
| 3 | Aim | ✅ Structurally editable ¹ | Kept |
| 4 | Material constraints | ✅ Editable (raw values) | ✏️ Hashes and transform ID |
| 5 | JointExprGraph | ✅ Path editable | Kept |

*Structurally editable*: entries can be added, deleted and re-pointed; counts,
hash-list indices and derived tables are regenerated on export. Raw fields whose
in-game meaning is still unknown are exposed as numbers.

² In place, a Range constraint's values can change (transform type, axis, flags,
the tail and unknown bytes, and each source's read mode, curve mode,
interpolation, anchors, reference frame and unknown bytes), but constraints and
sources cannot be added, deleted, renamed, re-pointed or reordered.

¹ Files that carry a ReadJointTable (SkinConstraintHashTable in the 010 template
and REE-Lib) need the target armature set before Multi or Aim bones change: the
table is re-derived from the skeleton's hierarchy.

## Installation

Blender 4.3 or newer: `Edit > Preferences > Get Extensions > ⌄ > Install from
Disk...` and pick the `-extension-vX.Y.Z.zip`. Blender 3.6 – 4.1: `Edit >
Preferences > Add-ons > Install...` and pick the plain `-vX.Y.Z.zip`.
Both are built with `python build_addon.py --all`.

## Language

The interface is available in English and Chinese. It follows Blender's interface
language until you press `English` / `中文` at the top of the JCNS panel; that choice
is remembered. Panel text switches immediately; property names, tooltips and panel
titles update after the add-on is reloaded or Blender is restarted.

## Credits

* [NSACloud](https://github.com/NSACloud) — reference for the overall structural
  design of the add-on
* [XenonBaruku](https://github.com/XenonBaruku) — RE JCNS 010 Editor template
