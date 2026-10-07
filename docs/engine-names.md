# 引擎里的 jcns 名字

2026-10-02 从 MH Wilds 的 exe 和 REFramework 类型库里挖出来的类型名、枚举定义，以及它们和
我们解析字段的对应关系。枚举的名字和数值是引擎自己的，标 ✓ 的对应关系有实测或语料支持，
其余是推断。

插件里的解析键、Blender 属性、枚举标识和界面名已经按本文改成引擎名（2026-10-02，三个提交：
解析层 `refactor(codec)`、属性层 `refactor(ui)`、文案层 `docs(ui)`）。下面表里的"插件旧名"只作对照。

| 层 | 旧名 → 新名 |
|---|---|
| 结构 | ConstraintInfo → OutputData，ConstraintSource → JointDriver，Skin 分区 → Multi，ConeDriver 表 → ConeInput，ConeDriverInfo → ConeDriver，Ranges 分区 → Outputs，JointExportGraph → JointExprGraph |
| 条目字段 | Flags → AttrFlags（`additive` → `base_pose`，`flags_other` → `attr_flags_other`），TransformType → TransformElement（`transform_type` → `transform_element`），TransformAxis → Axis |
| 源字段 | CurveMode → AttrFlags（`three_point` → `mid_point`，`curve_mode_extra` → `attr_flags_other`），ReadMode → InputType（`read_mode` → `input_type`），EulerOrder → RotOrder（`euler_order` → `rot_order`），ComplexMappingFlag → CurveType（`complex_mapping_flag` → `curve_type`） |
| Aim | RotationType → WorldUpType（`aim_type` → `world_up_type`） |
| 锥形 | `cone_infos` → `cone_drivers`，`cone_index` → `cone_input_index`，`cone_drivers_json` → `cone_inputs_json` |
| 枚举标识 | 变换类型、读取方式（TRANS/ROT/SCALE/ROT_RPY/ROT_PYR/EXP_MAP）、插值（LINEAR/SLOW/FAST/SMOOTH）、WorldUpType（SCENE_UP…NONE_MAYA_LIKE）全部用引擎名 |

没有引擎名的保持原样：`ref_frame`、`from_*`/`to_*` 锚点、ComplexMapping、`UnknownByte72`（推断是 OutputMode，未实测）、`TailBytes`。

## 来源

- **native 枚举**：`scripts/probes/dump_native_enums.py` 静态反汇编 exe 里的枚举注册代码
  （`lea rcx, 类型名; mov edx, 成员数; call 注册函数`，之后逐个 `lea rdx, 名字; mov r8d, 数值`），
  不碰游戏。结果在 `docs/wilds_jcns_enums.json`，共 26 个枚举。
  ```
  python scripts/probes/dump_native_enums.py <exe> <out.json> [类型名正则]
  ```
- **托管类型**：REFramework MCP 的 `search_types` / `get_type`，有字段名和枚举成员名。
- **exe 反射字符串**：类型名清单，只用来找方向。

## 1. 运行时本体 `via.motion.JointExMultiRemapValue`

jcns 资源在运行时叫 `JointExMultiRemapValue`，资源类型是 `via.motion.JointConstraintsResource`。

### 分区：`ConstraintType`

| 值 | 引擎名 | 插件旧名 |
|---|---|---|
| 0 | Outputs | Ranges ✓ |
| 1 | RotExpression | RotExpression ✓ |
| 2 | Multi | Skin（引擎叫"多输入"） |
| 3 | Aim | Aim ✓ |
| 4 | Material | Material ✓ |
| 5 | JointExprGraph | JXG ✓ |
| 6 | Max | — |

和 section table 的编号一致（实测：不在表里的分区不执行）。

### 条目（ConstraintInfo）：`OutputData.*`

**`TransformElement` = TransformType ✓**

| 值 | 引擎名 | 插件旧名 |
|---|---|---|
| 0 | Trans | Translation |
| 1 | Rot | Rotation |
| 2 | Scale | Scale |
| 3 | Deform | BlendShape |
| 4 | RotRPY | SwingTwist |
| 5 | RotPYR | TwistSwing |
| 6 | ExpMap | RotationVector |
| 7 | Material | Material_Color |
| 8 | MaterialF4 | Material_4D |
| 9 | MaterialPosF4 | Material_3D |
| 10 | MaterialRotF4 | Material_2D |
| 11 | ComponentProperty | Scalar |
| 12 | UserValue | Unknown_12（`getOutputUserValue` 读的就是它） |
| 13 | Rot2 | AxisRotation |
| 14 | RotRPY2 | AxisRotation_14（实测和 13 同；按引擎是 RotRPY 的"2"版） |
| 15 | RotPYR2 | UnkRotation_15 |
| 16 | ExpMap2 | UnkRotation_16 |

"2" 版（13–16）和 1/4/5/6 一一对应，具体差别没测。

**`AttrFlags` = Flags 字节 ✓**（语料里出现的值 0/1/5/9/13/16/17/48/49/53/57 都能拆成下面这些位）

| 位 | 引擎名 | 含义 |
|---|---|---|
| 1 | BasePose | bit0：1 = 叠加到静止姿态，0 = 替换 ✓ |
| 2 | World | 未见于语料 |
| 4 | ClampMin | 新：输出下限截断 |
| 8 | ClampMax | 新：输出上限截断 |
| 16 | OutJoint | bit4"驱动骨骼" ✓ |
| 32 | OutRot | bit5"角度量" ✓ |

**`OutputMode` = UnknownByte72（推断，语料取值 0–4 正好 5 种）**

| 值 | 引擎名 |
|---|---|
| 0 | Mode_Sum（多源求和 ✓ 实测） |
| 1 | Mode_Average |
| 2 | Mode_Mul |
| 3 | Mode_Min |
| 4 | Mode_Max |

语料：0 有 22539 条，1/4/2/3 共 300 条。

**其他**
- `Axis`：0 X / 1 Y / 2 Z / 3 W ✓
- `Interpolation`：0 Linear / 1 Slow / 2 Fast / 3 Smooth = 源 +28 ✓（实测：直线、三次缓入、三次缓出、smoothstep）
- `TangentType`（11 种）：0 Auto / 1 Spline / 2 Linear / 3 Fast / 4 Slow / 5 Flat / 6 Step / 7 StepNext / 8 Fixed / 9 Clamped / 10 Plateau。
  语料里 TailBytes[1] 取 0–8、以 2 为主，是候选。
- `PackFlags`：0 None / 1 InputPack

### 源（ConstraintSource）：`OutputData.JointDriverData.*`

**`InputType` = +25 ReadMode ✓（全部和实测一致）**

| 值 | 引擎名 | 插件旧名 |
|---|---|---|
| 0 | Trans | 位置 |
| 1 | Rot | XYZ 欧拉 |
| 2 | Scale | 缩放 |
| 3 | RotRPY | 摆动-扭转（一种乘序） |
| 4 | RotPYR | 摆动-扭转（另一种乘序） |
| 5 | ExpMap | 旋转向量 |

**`AttrFlags` = +24 CurveMode ✓**（语料取值 0/1/2/3/4/5，正好是三个位的组合）

| 位 | 引擎名 | 含义 |
|---|---|---|
| 1 | BasePose | 待测（见下） |
| 2 | MidPoint | bit1"三点曲线" ✓ |
| 4 | World | 新：按世界空间读（语料 4/5 共 23 条） |

`BasePose` 位：语料里 3（BasePose+MidPoint）占 64%，0 和 2 共 6000 多条。我们"读取含静止姿态"的
结论是在值为 3 的源上测的；bit0=0 时是否改为相对静止姿态读（exprgraph 的 `CoordSpace.LocalDiffBase`），
**还没测**，预览目前对所有源都按含静止姿态处理。

**`CurveType` = +29 ComplexMappingFlag ✓**：0 MinMax（锚点）/ 1 Function（ComplexMapping 曲线）/ 2 Scaling（新，语料里没见过）

**`RotOrder` = +27 EulerOrder ✓**：0 XYZ / 1 YZX / 2 ZXY / 3 ZYX / 4 YXZ / 5 XZY。
0–3 和实测一致；4、5 语料里没有，插件也还不支持。

### ComplexMapping 曲线：`detail.JointDriver*`

- `JointDriverTangentType`：同上 11 种
- `JointDriverInfinityType`：0 Const / 1 Linear / 2 Oscilate / 3 Cycle / 4 CycleRelative（曲线两端外推）

### 锥形：`ConeInputData` / `ConeDriverData`

- `ConeInputData.ConeAxis`（ConeDriver 表项）：0 X / 1 Y / 2 Z / 3 MinusX / 4 MinusY / 5 MinusZ / 6 Vector。
  RE9 的 ConeDriver 尾部恒为 `06 06 …`，6 = Vector，即按 Direction 向量取轴。
- `ConeInputData.AttrFlags`：0 None / 1 BasePose。对应尾部那个 `00|01` 字节。
- `ConeDriverData.CurveType`（ConeDriverInfo）：0 MinMax / 1 Function。
  Info 里那个 u8 取 0/2，和这两个值对不上，可能是另一个标志字节。

### Aim：`AimConstraintData.WorldUpType` = Aim RotationType ✓

| 值 | 引擎名 | 插件旧名 |
|---|---|---|
| 0 | SceneUp | WORLD_UP |
| 1 | ObjectUp | UP_JOINT_POSITION |
| 2 | ObjectRotationUp | UP_JOINT_AXIS |
| 3 | Vector | UP_DIRECTION |
| 4 | None | SHORTEST_ARC（实测：从静止姿态最短弧） |
| 5 | None_MayaLike | SHORTEST_ARC_PARENT（实测：不带静止姿态） |

### 其他

- `MaterialConstraintData.ApplyMode`：0 Trans / 1 Euler / 2 Scale / 3 Rot。就是 Material 记录的第 8 字节：
  语料里 `*_Pos`/`Shrink_Start` 参数全是 0，`Shrink_Scale` 是 2，RE9 有一条 3。
  同一记录的 NameHash / PropertyHash 是 mdf2 材质名、参数名的 murmur3 UTF-16（区分大小写）。
- `JointConstraintsResource.LegacyVersion`：0 Latest / 1 Legacy1

## 2. 托管原型 `via.motion.JointRemapValue`（Behavior）

字段和 jcns 几乎一一对应，可以看作 jcns 的可读版本：

- `RemapValueItem`：`OutJointName`、`OutTRS {Trans, Rot, Scale}`、`OutAxis {X, Y, Z}`、`OutRotOrder`、
  `Mode {Sum, Average}`、`BasePose`、`InJoints[]`、`OutputValue`；方法 `Calculate(float×5)`、`Update(Transform, bool)`。
- `InputJoint`：`JointName`、`Input {Trans, Rot, Scale, Cone}`、`InAxis`、`InRotOrder`、`BasePose`、`MidPoint`、
  `Offset (vec3)`、`ConeHalfAngle`、`InMin/InMid/InMax → OutMin/OutMid/OutMax`、`InputValue`、`OutputValue`。

锥形是和平移、旋转、缩放并列的第四种输入，参数是 `ConeHalfAngle` 和 `Offset`。

托管枚举的数值（2026-10-07 实测）：InputType 0 Trans / 1 Rot / 2 Scale / 3 Cone，Axis 0 X / 1 Y / 2 Z，
TRS 0 Trans / 1 Rot / 2 Scale，CalculateMode 0 Sum / 1 Average；`InRotOrder`/`OutRotOrder` 用 `via.math.RotationOrder`
（0 XYZ / 1 YZX / 2 ZXY / 3 ZYX / 4 YXZ / 5 XZY）。

### 锥形公式（2026-10-07，反汇编 + 实测 640/640，误差 ≤ 7e-7）

在游戏里手建 `RemapValueItem`/`InputJoint`、调 `Update(Transform, bool)`（`scripts/probes/ConeRemapProbe.cs`），
再对照 `Update` 的反汇编（RVA 0x7A7E8C0）。J = `JointName`，P = J 的父骨，G = P 的父骨：

- p̂ = J 当前局部位置的单位向量，也就是 P→J 这段骨在 P 空间里的方向。|p| ≤ 1.19e-7 时输入为 0（root、Hip 都是 0）。
- q_off = `Offset`（度）按 `InRotOrder` 组成的外旋欧拉：XYZ 先绕 X 再绕 Y 再绕 Z，即 Rz·Ry·Rx。
- 参考方向 c = G_world · [`BasePose` 时乘 P 的静止局部旋转] · q_off · p̂；当前方向 d = G_world · P_local · p̂。
  G 两边抵消，所以量的是 **P 的局部旋转把 J 这段骨摆离参考方向多少**。J 自己的旋转不参与；
  InAxis 对锥形不起作用；Input=Cone 时 InputValue 三个分量都写同一个值。
- 值 = 1 − (1 − c·d) / (1 − cos `ConeHalfAngle`)；若 (1 − cos H) ≤ (1 − c·d)，值为 0。范围 0..1：骨段正对参考方向时为 1，
  到锥面边缘时为 0。H = 360° 时恒为 0。
- 随后按 InMin/InMax → OutMin/OutMax 做线性映射并夹紧，`Calculate(v, inMin, inMax, outMin, outMax)` 同样如此
  （inMin = inMax 时返回 outMax）。`MidPoint` 打开时按 InMid 分两段映射。

这是托管原型的算法。native jcns 的 ConeInput（Direction、Matrix、Joint/ParentJoint 哈希、AngleRad）字段可能一一对应：
Direction ↔ p̂，Matrix ↔ q_off，AngleRad ↔ 半角。但 native 路径没有实测过，要做带锥形输入的 jcns 放进游戏验证。

## 3. 表达式图 `via.motion.exprgraph`（JXG）

- `RotComposeType`：0 RotRPY / 1 RotPYR / 2 ExpMap
- `CoordSpace`：0 Local / 1 Global / 2 LocalDiffBase
- `CoordUnit`：0 Centimeter / 1 Meter（jcns 平移是厘米 ✓）
- `RotUnit`：0 Rad / 1 Deg
- `RbfKernelType`：0 Linear / 1 Gaussian1 / 2 Gaussian2 / 3 ThinPlateSpline / 4 MultiQuadricBiharmonic / 5 InverseMultiQuadricBiharmonic
- `RbfDistanceType`：0 Euclidean / 1 Angle

节点（只有名字）：JointDriverNode、JointDriverFloatNode、JointDriverVec3Node、JointConeDriverNode、
JointConeInputNode、ConeInputNode、MaConeRemapNode、MaFloatRemapNode、ExpMapToQuatNode、QuatToExpMapNode、
ExprJointGetNode、ExprJointSetNode。

## 4. native 求值器（2026-10-07，静态反汇编，未实测）

入口：`JointConstraintsLayer.update()`（RVA C3D77F0）→ CE0E4F0 → 63820 → 分区调度 CE0E600。
求值时**直接读文件里的记录**：OutputData 步长 0x50，偏移就是 `jcns_schema.OUTPUT_DATA` 的文件偏移。
地址只对当前这版 exe 有效。

- **分区调度**：按文件的 section table 逐项分发。id 0 → Outputs（A623DA0），1 → A627460，2 → A6275C0，
  3 → A628410，4 → A629530，5 → A6299E0。不在表里的分区不执行，和第 12 轮实测一致。
  调度器把一个"级别"参数传给 id 0–3，id 4、5 拿不到。
- **Outputs 求值器 A623DA0**：
  - 先比较 `TailBytes[1]`（+0x4B）和传入的级别，**TailBytes[1] < 级别时整条跳过**。级别来自 GameObject 上某个组件的
    +0x4E4 字段（A623C40；先查一种组件，没有再查另一种），像 LOD 档位。语料里 TailBytes[1] 是 0–8，最多的是 2（15758 条）。
  - `TransformElement`（+0x2F）分 17 路 switch；源的 InputType 分 6 路；`UnknownByte72`（+0x48）分 5 路，
    对应 OutputMode Sum/Average/Mul/Min/Max。
  - **Rot2（13）**：沿关节组步进（每条 0x50），按各条的 Axis（+0x49）把值收进 vec3，再用 `TailBytes[0]`（+0x4A）
    作 **RotOrder** 转成四元数（和锥形 Offset 用的是同一个欧拉转换 B0E1050）。AttrFlags bit0 打开时再乘关节的静止局部旋转。
    **第 19 轮实测成立**：同组按组首的 TailBytes[0] 合成（误差 ≤0.0014°），分开成组时最后一条胜出。
    语料里 TailBytes[0] 非 0 的值是 1/2/5（YZX/ZXY/XZY），也出现在 Trans/Rot/Scale 等条目上。那些条目读不读它，还没查。
  - AttrFlags bit4（+0x2E & 0x10）为真时，先按 ObjectHashIndex（+0x20）查一次目标，查不到就跳过。

## 5. 还没解决的

- 锥形公式在托管原型上已经测定（见第 2 节）；native jcns 的 ConeInput 是否同一算法、字段怎么对应，还没验证。
- 源 AttrFlags 的 BasePose 位（bit0=0 的源）到底怎么读（求值器 A623DA0 里的 6 路 InputType switch 是下一步要读的地方）。
- TailBytes[1] 比较的级别是哪个组件的哪个量；TailBytes[0] 在 Rot2 以外的元素上有没有作用。
- ConeDriverInfo 里那个 0/2 字节。
- exe 里还有一组手写脚本的字段（`_ConeVector`、`_HalfAngleTbl`、`_ConeInputs`、`_ConeOutMax`、
  `ConeDriverCount`、`ConeDrivenCount`，和颚、鳍、尾的表放在一起），像某个怪物的专用约束脚本，所属类型没查到。
