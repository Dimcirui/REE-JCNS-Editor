# 给其他插件的接口

其他插件（比如按集合组织组件、做模拟的插件）读 JCNS 数据时用到的名字。这些名字是稳定接口：
改名或改语义时 `wd_api.API_VERSION` 加一，并记在文末的变更记录里。字段的含义见
[engine-names.md](engine-names.md) 和 README；这里只说它们在 Blender 里的位置和对应的文件字段。

接口版本：`API_VERSION = 1`。

## 集合

导入和"新建"各建一个根集合（绿色），上面有两个自定义属性：

| 属性 | 值 |
|---|---|
| `~TYPE` | `"RE_JCNS_COLLECTION"`，导入和新建都写，之后不改不删 |
| `~ASSETPATH` | 游戏内相对路径，去掉 `natives/<平台>/`，不带版本后缀，例 `Art/Model/Character/ch03/039/001/2/ch03_039_0012.jcns`。只在导入时写，文件路径里没有 `natives` 时不写；新建的集合没有 |

## 内存导出：`wd_api`

子模块 `<包名>.wd_api`（扩展形式 `bl_ext.<repo>.<包名>.wd_api`），插件启用后就在 `sys.modules` 里：

```python
API_VERSION = 1
COLLECTION_TYPES = ("RE_JCNS_COLLECTION",)

class ExportError(Exception): ...      # 消息是给用户看的问题列表

def export_bytes(collection, version=None) -> bytes:
    """version 为 None 时导出 v102（MH Wilds）。"""
```

- 结果和"导出"操作写出的文件逐字节相同（`tests/test_wd_api.py` 有验证）。
- 不写文件，也不改场景：选择、激活对象、模式、当前帧，以及根对象的 `source_filepath` 都保持原样。导出操作会改 `source_filepath`，这里不会。
- 能重建的根（v21 / 22 / 35 / 36 / 102，且导入时已存下分区数据）只用 Blender 里的数据，不读源文件。
  其他版本是原地写回，要读源文件，源文件不在了就抛 `ExportError`。
- 只读属性，不读对象的变换和骨骼姿态，播放动画不影响结果。
- 跨版本导出只限 21 / 22 / 35 / 36 / 102 之间。v35 / v36 导出成 v102 时如果要推导 ReadJointTable，
  需要根上设了 `target_armature`，否则抛 `ExportError`。

## 对象

所有数据都在根集合的对象上：一个根 Empty，其余条目 Empty 都以它为父对象。对象上没有单独的
TYPE 属性，按下面的属性组区分。

| 对象 | 怎么认 | 属性组 |
|---|---|---|
| 根 | `obj.jcns_root_props.source_filepath` 或 `.source_version` 非空 | `jcns_root_props` |
| 条目 | `obj.jcns_cns_props.is_jcns_constraint` 为真且 `obj.parent` 是根 | `jcns_cns_props` |

条目的种类看 `jcns_cns_props.constraint_type`：

| constraint_type | 文件里的分区 |
|---|---|
| `Outputs`（旧场景可能是空串） | OutputData（每条带若干 JointDriver） |
| `Multi` | MultiConstraint |
| `Aim` | AimConstraint |
| `RotExpression` | RotExpression |
| `Material` | MaterialConstraint |

条目的文件顺序是对象名开头的编号（`[03]`、`[Aim01]`、`[Mat00]`……）。

骨骼名字段可以是真名，也可以是 `0x%08X` 形式的哈希（导入时查不到名字的骨）；写进文件的是名字的
murmur3 UTF-16 哈希，或者这个哈希值本身。

### 根：`jcns_root_props`

| 字段 | 文件字段 |
|---|---|
| `source_version` | 文件版本 |
| `source_filepath` | 导入来源（只用来原地写回，内存导出不用它） |
| `target_armature` | 不进文件；推导 ReadJointTable 时用它的骨骼层级 |
| `section_order[].value` | SectionTable 的顺序 |
| `hash_list[].hash` | HashTable |
| `header_unknown_bytes` | 文件头两个未知字节 |
| `file_constant` | Multi tail[0]、Multi source info 和 Aim +59 共用的常数 |
| `read_joint_table[].hash` | ReadJointTable |
| `rot_map_value` | RotExpression map 的值 |
| `object_settings_json` | ObjectSettings（不可编辑，原样带回） |
| `cone_inputs[]` | ConeInput 表：`name`、`joint`、`parent_joint`、`symmetry_joint`、`direction`、`matrix`、`translation`、`angle`（AngleRad）、`unknown_uint32`、`tail` |
| `jxg_path` | JointExprGraph 路径，空串为没有 |
| `sections_cached`、`rebuild_blocked`、`upgraded_from`、`read_table_pending` | 导入时记下的状态，决定能否重建 |

### Outputs 条目：`jcns_cns_props`

| 字段 | 文件字段（OutputData） |
|---|---|
| `target_bone` | ObjectName（目标骨或对象名） |
| `target_property`、`property_hash` | PropertyName、PropertyHash |
| `object_hash` | 直接目标的 ObjectHash |
| `transform_element` | TransformElement |
| `target_axis` | Axis（+73） |
| `base_pose`、`use_clamp_min`、`use_clamp_max`、`attr_flags_other` | AttrFlags 的 bit0、bit2、bit3 和其余位（v36 / v102 的 bit4/5 导出时按 transform_element 重算） |
| `output_ref_x/y/z/w` | OutputRef |
| `clamp_min`、`clamp_max` | Clamp |
| `output_mode` | OutputMode |
| `unknown_byte_74`、`lod_threshold`、`group_count`、`reserved_tail[0..2]` | TailBytes[0]、[1]、[3]、[2] / [4] / [5] |
| `cone_drivers[]` | ConeDriver：`cone_input_index`、`out_min`、`out_max`、`interpolation`、`curve_type`、`curve_data_hex`（CurveData 12 字节）、`curve_json`、`reserved_byte` |
| `sources[]` | JointDriver，见下表 |

`sources[]`（JointDriver）：

| 字段 | 文件字段 |
|---|---|
| `source_bone` | SourceName / SourceHashIndex |
| `source_axis` | 源轴 |
| `from_start`、`from_kink`、`from_end`、`to_start`、`to_kink`、`to_end` | 三点映射 |
| `ref_frame_x/y/z/w` | 读取参考系四元数 |
| `base_pose`、`mid_point`、`attr_flags_other` | AttrFlags 的 bit0、bit1 和其余位 |
| `input_type` | InputType（+25） |
| `rot_order` | RotOrder（+27） |
| `curve_pre_wrap`、`curve_post_wrap`、`interpolation`、`curve_type` | CurvePreWrap、CurvePostWrap、Interpolation、CurveType |
| `cm_channel` | ComplexMapping 曲线：条目对象动作里这个自定义属性通道的 F-Curve 关键帧就是数据（见下） |

### 其他条目

| 种类 | 字段 → 文件字段 |
|---|---|
| Multi | `target_bone` → 目标骨；`multi_sources[]`（`bone`、`weight`）→ 源骨和权重；`multi_tail` → tail[1..2] |
| Aim | `target_bone` → joint；`aim_target_bone`、`aim_target2_bone`、`aim_weight2`、`aim_up_bone`、`aim_influence`；`aim_offset`、`aim_axis`、`aim_up_axis`、`aim_up_dir` → 四个向量；`world_up_type` → WorldUpType；`aim_bytes` → 其余字节 |
| RotExpression | `target_bone` → joint；`rot_source_bone` → source；`rot_rotation`、`rot_scale`、`rot_gains`；`rot_rest_mode` → byte[1]；`rot_unknown_bytes` → byte[0] / [2] / [3] |
| Material | `target_bone` → JointHash；`mat_name_hash`、`mat_property_hash`（十六进制串）→ NameHash、PropertyHash；`mat_apply_mode` → 字节 8；`mat_tail_0..2` → 字节 9..11 |

## 不在集合对象属性上的数据

- ComplexMapping 曲线存在条目对象的动作（`animation_data.action`）里，不在属性组上。改关键帧时
  depsgraph 报的是动作的更新，不一定是对象的更新。
- `target_armature` 指向集合外的骨架；只有需要推导 ReadJointTable 时（v35 / v36 升级或导出成 v102，
  以及 `read_table_pending` 为真）才读它的骨骼层级。

## 变更记录

- v1（2026-10-23）：首版。
