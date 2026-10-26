# REE JCNS Editor

A Blender add-on for importing, editing and exporting RE Engine `.jcns` (joint
constraint) and `.jntexprgraph` (expression graph) files.

A `.jcns` file makes bones, blendshapes and material parameters follow the pose
of other bones. Each constraint reads a value from a source bone (rotation,
position, scale, or how far it has swung into a cone), maps it through a curve,
and applies the result to a target.

- **Edit**: a file is imported as a collection of Empties, one per constraint.
- **Bake**: pose a driver bone and the bones it drives at a few keys, and the
  add-on generates the constraints from those poses (like Set Driven Key).
- **Preview**: the constraints can be applied to an armature as Blender drivers,
  so you can pose the rig and watch them work.
- **Export**: the file is written back. Newer versions have full editing support:
  constraints can be added, deleted and re-pointed. Older versions only support
  changing values. See [Supported Games](#supported-games).

Expression graphs are node graphs for the same job; see [Expression Graphs](#expression-graphs).

## Supported Games

| JCNS version | Game | Editing |
| --- | --- | --- |
| 29, 102 | Monster Hunter Wilds | ✅ Full |
| 36 | Onimusha: Way of the Sword | ✅ Full |
| 35 | Resident Evil Requiem / PRAGMATA / MH Stories 3 | ✅ Full, requiem preview not usable yet |
| 24 | Dragon's Dogma 2 | ✏️ Values only |
| 22 | RE4 Remake / Street Fighter 6 | ✅ Full |
| 21 | Monster Hunter Rise | ✅ Full |
| 19 | RE2 / RE3 / RE7 ray-tracing updates | ✏️ Values only |
| 16 | RE Village | ✏️ Values only |
| 12 | RE3 | ✏️ Values only |
| 11 | RE2 / Devil May Cry 5 | ✏️ Values only |

- **Full**: constraints can be added, deleted and re-pointed.
- **Values only**: values can change, but constraints cannot be added or deleted.

Games with Full support can be exported as each other with *Export Version* in the
export dialog; bone names must match the target game's skeleton. v29 files are
upgraded to v102 on import.

## Supported Sections

| Section | What it does | Full | Values only | Preview |
| --- | --- | --- | --- | --- |
| Outputs | Maps a source bone's reading through a curve onto one channel of a target | ✅ Editable | ✏️ Values | ✅ |
| Curves | Keyframed curve for an Outputs entry, edited as F-Curves in the Graph Editor | ✅ Editable | 🔒 Locked | ✅ |
| Cone inputs | Reads how far a bone has swung into a cone | ✅ Editable | 🔒 Locked | ✅ |
| Multi | Pins an attachment bone to the deformed skin by skin weights | ✅ Editable ¹ | 🔒 Locked | ✅ |
| Aim | Points one bone's axis at another bone | ✅ Editable ¹ | 🔒 Locked | ✅ |
| RotExpr | Copies a bone's rotation to another bone, scaled per axis | ✅ Editable | 🔒 Locked | ✅ |
| Material | Bones drive material properties | ✅ Editable | ✏️ Hashes and transform ID | — |
| JointExprGraph | Runs an expression graph at this point of the file's order | ✅ Path, opens the graph | 🔒 Locked | — |

Fields whose in-game meaning is unknown are shown as raw numbers. Dependencies are
regenerated on export and ObjectSettings are kept as they are.

¹ Changing Multi or Aim bones requires the target armature to be set first.

## Expression Graphs

A `.jntexprgraph` is a node graph: nodes read bones, do math or follow time, and
write bones. It can make things a `.jcns` cannot, such as parts that spin, sway or
switch on and off.

- **Edit**: a file imports as a "JCNS Expression Graph" tree in Blender's node
  editor. *Open Node Tree View* in the MHWs JCNS panel opens it in a new window.
  Add nodes with Shift+A and connect them; bone inputs take bone names.
- **Preview**: *Play Preview* drives the armature by the graph. It follows the
  timeline and posing, and turning it off puts the bones back.
- **Export**: the graph is checked, then written back. An unchanged import
  exports byte for byte.

| Version | Game | Editing |
| --- | --- | --- |
| 6 | Monster Hunter Wilds | ✅ Full |

- Nodes that are game scripts (C#) keep their parameters as read; only their links
  can change, and they are not previewed.
- Node types the shipped files never use cannot be added yet.
- Node behaviour in the preview follows the game's code for the common nodes;
  docs/jntexprgraph.md lists which ones.

## Installation

- Blender 4.3 or newer: `Edit > Preferences > Get Extensions > ⌄ > Install from Disk...`
  and pick the `-extension-vX.Y.Z.zip`.
- Blender 3.6 – 4.1: `Edit > Preferences > Add-ons > Install...` and pick the plain
  `-vX.Y.Z.zip`.

Both zips are built with `python build_addon.py --all`.

## Credits

* [NSACloud](https://github.com/NSACloud) — reference for the overall structural
  design of the add-on
* [XenonBaruku](https://github.com/XenonBaruku) — RE JCNS 010 Editor template
