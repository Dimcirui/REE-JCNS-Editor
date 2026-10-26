# JointExprGraph（`.jntexprgraph.6`）格式

读写器在 `modules/jxg_format.py`，对 Wilds 原版 113 个文件 `write(read(x)) == x` 逐字节成立。
节点类型表和槽目录在 `modules/data/jxg_nodes.json`（`tools/build_jxg_nodes.py` 从 RSZ 类型表和语料生成），
槽名、校验和增删节点在 `modules/jxg_nodes.py`，测试 `tests/test_jxg.py`。
下面的布局都是这个读写器实现的规则；"含义"一栏里标 ? 的是从语料推出、没有实测的。

## 1. 它是什么

挂在 GameObject 上的组件 `via.motion.JointExprGraph`（和 `via.motion.JointConstraints` 平级），
`Layer` → `JointExprGraphLayer.v0_JointExprGraph` 引用这个资源，层上也有 BlendRate、Pause、UpdateTiming。jcns 不引用它。

内容是一张节点图：Get 类节点读骨，数学节点计算，Set 类节点写骨。和 jcns 的区别是可以任意连线，
有随时间变化的节点（SinWave、CyclicalAngle），还能挂游戏自己写的 C# 节点（`app.expr_node.*`）。

Wilds 里有 112 个，用途：

- 道具/饰品的循环转动、摆动（`it*`：CyclicalAngle 或 SinWave → JointSetRotation）。
- 裙子、夹克下摆按腿的姿态联动。原版裙甲的 pfb 实际挂的是通用 `Art/System/ExprGraphDefinition/Skirt.jntexprgraph`
  （一个 `app.SkirtNode`）加 C# 组件 `app.SkirtBatchProcessing`；各件的 `*_skirt_00/01` 有 14 对在全部 pfb 里没有引用。
  游戏里穿着 ch03_074_0015 时，图层加载的确实是 Skirt.jntexprgraph；`app.SkirtNode` 只有一个字段 `_BatchProcessing`
  和 `update()`，就是调用那个组件的挂钩。
- 怪物专用逻辑：图里只有一个 `app.expr_node.Em*` 节点。

### 从 jcns 里运行

图还有第二条加载路径：jcns 的 JXG 分区（section 5）存一条图的路径，它和其它分区一起排在 section table 里，
按表里的位置执行，相当于在 jcns 的求值顺序里插入一步。Wilds 有 12 个 jcns 带这个分区（鬼武者、PRAGMATA 没有），
全是怪物的 RS/RE/CS 层：

| jcns | 分区顺序 | 图里的节点 |
|---|---|---|
| ch90_070_0000_CS | Multi → JXG | Em0070_FangConstraint |
| ch90_078_0000_RS00 | Outputs → JXG | Em0078_RSExpr |
| ch90_155_0000_RS | JXG → Outputs | Em0155_TailConstraint |
| ch90_157_0000_RS / _02_RS | JXG | Em0157_DistanceConstraint / GillConstraint |
| ch90_160_0000_RS / 5000_RS | Outputs → JXG → Multi | Em0160_ThornConstraint |
| ch90_161_0000_RE | Outputs → JXG | Em0161_AimExpr |
| ch90_161_0000_RS（v102、v29） | Outputs → JXG | 138 个原生节点（MaEulerConstraint、KeyFrameCurve…） |
| ch90_163_0000_RE00 | JXG | Em0163_LegConstraint |
| ch91_164_5000_RS | Outputs → JXG | Em1164_TailConstraint |

这些图里除了 ch90_161_0000_RS（另有 2 个 pfb 直接挂），都没有任何 pfb 引用，只能经 jcns 加载。
jcns 的 4 个文件只有 JXG 一个分区、没有任何约束条目，纯粹是为了把一个 C# 约束排进这一层。
所以两条路的区别是时机：组件版按组件自己的 UpdateTiming 跑；jcns 版跟随这一层 jcns，
排在指定的分区之间（例如 ch90_160 先算 Outputs，再跑脚本，最后 Multi 读脚本的结果）。
引擎的分区调度对 id 5 有一个处理函数（见 engine-names.md 第 4 节），但这条路径没在游戏里实测过。

同一件腰甲上 JointExprGraph 的 UpdateTiming 是 1，JointConstraints 是 3（`via.motion.ConstraintsUpdate`，
成员 PrevLateUpdate / AfterLateUpdate / ByBehavior / Last，数值对应还没取）。

### C# 节点

`app.*` 节点在托管类型库里，分两种基类：

- `via.userdata.exprgraph.ExprNode`：计算节点，用 `getFloat(槽)/setVec3(槽, …)` 这类按槽号的接口收发数据。
  SkirtSubJointNode 的字段按偏移排列正好就是它的槽：0 sel_parent_jnt、1/2 L/R_MOT_jnt、3/4 L/R_MOT_jnt_upper_point、
  5/6 L/R_MOT_jnt_lower_point、7 keep_1_range、8 leg_length、9 cone_angle、（10 输出）、11/12 L/R_leg_vector_offset_angle、
  13 compare_vector_limit_angle。
- `via.userdata.exprgraph.ExprBehaviorNode`：多了 `update()`、DeltaTime 等，自己读写骨（Em* Constraint、SkirtNode）。
  例：Em0161_ShoulderExpr 有 `_Joint`、`_ConeVector`、`_AngleRad`、`_Result[]`，是一组锥形输入。

两种基类都有 `get_NodeNameHash()`，节点 +0x34 那个偶尔非零的哈希大概就是它。
原生节点（`via.motion.exprgraph.*`、`via.userdata.exprgraph.*`）不在托管类型库里，槽名只能靠推断。

## 2. 文件头

| 偏移 | 类型 | 含义 |
|---|---|---|
| 0x00 | u32 | 版本 6 |
| 0x04 | char[4] | `jexg` |
| 0x08 | u64 | 0 |
| 0x10 | u64 | 图头偏移，恒为 0x30 |
| 0x18 | u64 | 尾段偏移 |
| 0x20 | u32 | 哈希（每个文件不同，含义未知） |
| 0x24 | u16, u16 | 0x595A, 1（恒定） |

## 3. 图头（0x30 起）

| 偏移 | 类型 | 含义 |
|---|---|---|
| +0x00 | GUID | 图的 GUID，尾段开头重复一次 |
| +0x10 | u64 | 根列表偏移 |
| +0x18 | u64 | 根列表头偏移 |
| +0x20 | u64 | 节点数组偏移 |
| +0x28 | u32 | 常量哈希，绝大多数为 0x47BEF355 |
| +0x2C | u16 | 空图为 0，其余为 1 |
| +0x2E | u16 | 原生节点数 |
| +0x30 | u32 | app（C#）节点数，排在原生节点之后 |
| +0x34 | u32 | 哈希（含义未知） |

**根列表**：u16 数组，列出图的出口节点（Set 类、带副作用的节点），求值从这里往回拉。
项的 bit15 表示 app 节点（低位是 app 块内的序号），0x6000 只出现在 DebugDraw2DTextNode 上，像是"仅调试"。
**根列表头**：6 字节 0，接 u16 根数。

## 4. 节点（每条 0x38 字节）

| 偏移 | 类型 | 含义 |
|---|---|---|
| +0x00 | u64 | 0（运行时指针位） |
| +0x08 | u32 | 输入连线起点 |
| +0x0C | u32 | 属性类型表偏移，无属性时为 0 |
| +0x10 | u32 | 属性数据偏移，无属性时为 0 |
| +0x14, +0x18 | u32 | 0 |
| +0x1C | u32 | 额外数据偏移，没有时为 0 |
| +0x20 | u32 | 输入连线终点 = 起点 + 6 × 连线数 |
| +0x24 | u32 | 节点序号 |
| +0x28 | u8 ×4 | 0, 连线数, 属性数, 0 |
| +0x2C | u16 | kind：纯数学节点 5，DebugDraw 3，其余 1 |
| +0x2E | u16 | 额外数据字节数 |
| +0x30 | u32 | 节点类型 = RSZ 类型哈希（`modules/data/jxg_node_types.json`） |
| +0x34 | u32 | 通常为 0；20 个节点上是一个哈希，Joint 节点上等于它读的骨的哈希 |

### 槽

每个节点类型有自己的输入槽号和输出槽号，两套编号互相独立。一个输入槽要么接线，要么是属性（常量）。

**属性类型表**：每个属性 3 字节 `(槽号, 类型, 类型)`，两个类型字节总相同。
**属性数据**：按类型表顺序紧排，长度随类型：

| 类型码 | 类型 | 字节 |
|---|---|---|
| 1 | bool | 4 |
| 2 | int（也用于枚举、骨名哈希） | 4 |
| 3 | float | 4 |
| 4 | vec3 | 12 |
| 6 | quat | 16（语料里只在连线上出现） |
| 0xFF | 任意（只在连线的目标类型上出现） | — |

**输入连线**（每条 6 字节）：`u16 源节点, u8 目标槽, u8 源输出槽, u8 目标类型, u8 源类型`。
源节点的 bit15 同样表示 app 节点。两个类型不同时引擎做转换（语料里有 float→vec3、float→bool）。

**额外数据**：FloatEaseCurveNode 4 字节（u32，缓动类型?）、KeyFrameCurveNode 120 字节（曲线关键帧）、
FloatMathCodeNode 是一段逆波兰字节码：`02 n 00` 读第 n 个输入，`01 <f32>` 压常数，`04 op` 二元运算
（01 加、03 乘；02/04 推测为减/除）。例：`02 01 00 02 00 00 04 01` = in0 + in1。

## 5. 尾段

| 偏移 | 类型 | 含义 |
|---|---|---|
| +0x00 | GUID | 同图 GUID |
| +0x10 | u64 | 节点表偏移（紧跟其后） |
| +0x18 | u32 | 哈希 |
| +0x1C | u32 | 0 |

节点表每节点 0x20 字节：`GUID, u64 输出表偏移, u64 输出数`。输出表每项 2 字节 `(槽号, 类型码)`，
列出该节点**声明**的全部输出（不管有没有被连）。

## 6. 排列与对齐

依次：文件头 → 图头 → 根列表（之后对齐 4）→ 根列表头（8 字节，之后对齐 8）→ 节点数组 →
所有属性类型表（按节点顺序）→ 对齐 4 → 所有属性数据 → 对齐 8 → 连线（每个有连线的节点之后对齐 8；
无连线节点的起止都指向当前位置）→ 对齐 16 → 额外数据（每段之后对齐 16）→ 对齐 16 → 尾段 →
节点表 → 输出表（每个节点的表起点对齐 4）。空图（0 节点）没有根列表头，两个偏移都指向根列表。

## 7. 常用节点

骨名用 murmur3（UTF-16LE）哈希存，插件的名字词典能翻。

**Joint 节点的公共槽**

| 槽 | 类型 | 含义 |
|---|---|---|
| 0 | int | 骨名哈希 |
| 1 | int | Set 节点才有，取值 −1/1/2/5/6/8，基本按文件恒定（旧裙子图 −1、物品 6、怪物 5、其余 2）；像 LOD 门槛? |
| 2 | int | CoordSpace?：0 Local / 1 Global / 2 LocalDiffBase |
| 3 | int | RotComposeType?：0 RotRPY / 1 RotPYR / 2 ExpMap |
| 5 | int | CoordUnit?：0 厘米 / 1 米 |
| 6 | int | RotUnit?：0 弧度 / 1 度 |

| 槽（输入或输出） | 类型 | 含义 |
|---|---|---|
| 10 | vec3 | 位置 |
| 11 | quat | 旋转 |
| 12 | vec3 | 缩放 |
| 13 | vec3 | 欧拉角 |
| 20 / 21 / 22 | float | 上面那个量的 X / Y / Z 分量 |

- JointGetPositionNode：属性 0/2/5，输出 10、20–22。
- JointGetRotationNode：属性 0/2/3/6，输出 11、13、20–22。
- JointSetPositionNode：属性 0/1/2/5，输入 10 或 20–22。
- JointSetRotationNode：属性 0/1/2/3/6，输入 11、13 或 20–22。
- JointGetLocalCoordNode：属性 0、4（bool），输出 10/11/12。

**数学节点**：两元运算（FloatAdd/Sub/Mul/Div、Vec3Add/Sub/Mul、QuatMul）输入 0、1，输出 0；
没接线的输入用属性给常数（例：FloatDiv 的 1 号槽 = 180）。可变输入的节点用一个计数属性加连续槽号：
FloatSum（属性 1 = 个数，输入 11 起）、FloatMathCode（属性 1 = 个数，输入 10 起）、
ExprZivaMeshExtraParam（属性 0 = 个数，从 10 起"名字哈希 / 值"成对）。

**时间节点**：CyclicalAngleNode 属性 1（周期?）；SinWave/CosWave/SawToothWave 属性 1/2/3（周期? / 振幅? / 偏移?）。

## 8. 预览

`modules/jxg_eval.py` 在 Python 里求值一张图，`jxg_preview.py` 在每次换帧和编辑后读骨架、写回骨骼（关掉时还原）。
空间换算和 Wilds-Dynamics 相同：RE Mesh Editor 把游戏的 Y 向上绕 X 转 +90° 烘进骨骼（RX），骨的游戏局部变换是
父骨姿态⁻¹ · 姿态（根骨 RX⁻¹ · 姿态），根骨挂在 RX⁻¹ · 物体 · RX 上。时间 = (当前帧 − 起始帧) / 帧率。

以下按建模实现，没在游戏里核对，效果可能不同：

- CoordSpace 0 局部 = 相对父骨的完整变换，1 全局，2 相对静止姿态（静止 · 值、静止偏移 + 值）。
- Set 节点替换它写的量；没给的旋转分量按 0，没给的位置分量保留当前值。
- RotComposeType 0 RPY 合成 Ry·Rx·Rz（Z 先），1 PYR 合成 Rz·Ry·Rx（X 先），2 旋转向量。原版几乎都是单轴，不受顺序影响。
- CyclicalAngle：角度 = 速度 × 时间，取模 2π（皮带那张图里速度会被映射到 0 来停住，所以是速度不是周期）。
- Sin/Cos/SawToothWave（速度, 下限, 上限）；FloatEaseCurve（下限, 上限, t）；FloatSwitch（条件, 真, 假）；
  FloatMap（输入, 输入下限, 输入上限, 输出下限, 输出上限, 钳制）；MaFloatRemap（输入, 输入三点, 输出三点）；
  FloatMathCode 按逆波兰字节码求值（运算 1 加 2 减 3 乘 4 除，2/4 未见于原版）。
- 不预览、输出按 0：C# 节点、KeyFrameCurve、MaEulerConstraint、JointDriverFloat、JointDecomposeRotate、Ziva、材质节点、DebugDraw。

测试 `tests/test_jxg_eval.py`（纯 Python）和 `tests/test_jxg_bpy.py`（后台 Blender）。

## 9. 还没解决的

- Set 节点的 1 号属性；节点 +0x34 的哈希；文件头 +0x20、图头 +0x28/+0x34、尾段 +0x18 的哈希。
- 槽 2/3/5/6 的枚举对应只靠取值范围，没在游戏里验证。
- KeyFrameCurve 的 120 字节、EaseCurve 的类型码、FloatMathCode 的完整运算码表。
- 图的求值时机和 jcns 的先后。

## 附录：语料里出现的全部节点类型

输入槽包括属性和连线；输出槽取自尾段的声明。kind 见第 4 节。

| 节点 | 个数 | kind | 输入槽 | 输出槽 |
|---|---|---|---|---|
| `via.motion.exprgraph.JointSetRotationNode` | 664 | 1 | 0:int, 1:int, 2:int, 3:int, 6:int, 11:quat, 13:vec3, 20:float, 21:float, 22:float | — |
| `via.motion.exprgraph.JointGetPositionNode` | 539 | 1 | 0:int, 2:int, 5:int | 10:vec3, 20:float, 21:float, 22:float |
| `app.expr_node.SkirtSubJointNode` | 245 | 1 | 0:vec3, 1:vec3, 2:vec3, 3:vec3, 4:vec3, 5:vec3, 6:vec3, 7:float, 8:float, 9:float, 11:float, 12:float, 13:float | 10:float |
| `via.motion.exprgraph.JointSetPositionNode` | 176 | 1 | 0:int, 1:int, 2:int, 5:int, 10:vec3, 20:float, 21:float, 22:float | — |
| `via.userdata.exprgraph.FloatValueNode` | 95 | 1 | 0:float | 0:float |
| `via.userdata.exprgraph.CyclicalAngleNode` | 92 | 1 | 1:float | 0:float |
| `via.motion.exprgraph.FloatEaseCurveNode` | 91 | 1 | 0:float, 1:float, 2:float ；额外数据 4 字节 | 0:float |
| `via.userdata.exprgraph.FloatDivNode` | 91 | 5 | 0:float, 1:float | 0:float |
| `via.motion.exprgraph.JointGetRotationNode` | 86 | 1 | 0:int, 2:int, 3:int, 6:int | 11:quat, 13:vec3, 20:float, 21:float, 22:float |
| `via.userdata.exprgraph.FloatMulNode` | 85 | 5 | 0:float, 1:float | 0:float |
| `via.userdata.exprgraph.SinWaveNode` | 67 | 1 | 1:float, 2:float, 3:float | 0:float |
| `via.motion.exprgraph.MaFloatRemapNode` | 60 | 5 | 0:float, 1:vec3, 2:vec3, 3:int, 4:bool | 0:float |
| `app.expr_node.SkirtSubJointV2Node` | 42 | 1 | 0:vec3, 1:vec3, 2:vec3, 3:vec3, 4:vec3, 5:vec3, 6:vec3, 7:float, 8:float, 9:float, 11:float, 12:float, 13:float | 10:float |
| `via.motion.exprgraph.JointGetLocalCoordNode` | 42 | 1 | 0:int, 4:bool | 10:vec3, 11:quat, 12:vec3 |
| `via.userdata.exprgraph.Vec3MulNode` | 37 | 5 | 0:vec3, 1:vec3 | 0:vec3 |
| `via.userdata.exprgraph.Vec3AddNode` | 36 | 5 | 0:vec3, 1:vec3 | 0:vec3 |
| `via.userdata.exprgraph.Vec3NormalizeNode` | 34 | 5 | 0:vec3 | 0:vec3 |
| `via.userdata.exprgraph.Vec3TransformNode` | 34 | 5 | 0:vec3, 1:quat | 0:vec3 |
| `via.userdata.exprgraph.Vec3ValueNode` | 34 | 1 | 0:vec3 | 0:vec3 |
| `via.motion.exprgraph.MaEulerConstraintNode` | 22 | 5 | 4:quat, 5:int, 6:int, 7:int, 8:int, 11:float, 12:float, 13:float | 0:vec3, 1:float, 2:float, 3:float |
| `via.motion.exprgraph.JointDriverFloatNode` | 16 | 1 | 1:int, 2:int, 10:float, 11:float, 12:float, 13:float, 14:float, 15:int, 16:bool | 0:float |
| `via.userdata.exprgraph.CosWaveNode` | 13 | 1 | 1:float, 2:float, 3:float | 0:float |
| `via.userdata.exprgraph.FloatAddNode` | 9 | 5 | 0:float, 1:float | 0:float |
| `via.userdata.exprgraph.FloatMathCodeNode` | 8 | 5 | 1:int, 10:float, 11:float, 12:float, 13:float, 14:float, 15:float, 16:float, 17:float ；额外数据 8/42/59 字节 | 0:float |
| `via.userdata.exprgraph.QuatMulNode` | 8 | 5 | 0:quat, 1:quat | 0:quat |
| `via.motion.exprgraph.KeyFrameCurveNode` | 6 | 1 | 0:float ；额外数据 120 字节 | 0:float |
| `via.userdata.exprgraph.QuatToEulerFloat3Node` | 6 | 5 | 3:quat, 4:int | 0:float, 1:float, 2:float |
| `via.userdata.exprgraph.Rad2DegNode` | 6 | 5 | 1:float | 0:float |
| `via.userdata.exprgraph.Vec3ToFloat3Node` | 6 | 5 | 0:vec3 | 1:float, 2:float, 3:float |
| `via.userdata.exprgraph.Float3ToVec3Node` | 4 | 5 | 1:float, 2:float, 3:float | 0:vec3 |
| `via.userdata.exprgraph.FloatSubNode` | 4 | 5 | 0:float, 1:float | 0:float |
| `via.userdata.exprgraph.FloatSumNode` | 4 | 5 | 1:int, 11:float, 12:float | 0:float |
| `via.userdata.exprgraph.FloatSwitchNode` | 4 | 5 | 0:bool, 1:float, 2:float | 0:float |
| `via.userdata.exprgraph.QuatSlerpNode` | 4 | 5 | 0:quat, 1:quat, 2:float | 0:quat |
| `via.zivart.ExprZivaMeshExtraParamNode` | 4 | 1 | 0:int, 10:int, 11:float, 12:int, 13:float, 14:int, 15:float, 16:int, 17:float, 18:int, 19:float | — |
| `via.userdata.exprgraph.CosNode` | 3 | 5 | 1:float, 2:int | 0:float |
| `via.userdata.exprgraph.DebugDraw2DTextNode` | 3 | 3 | 0:any, 1:float, 2:float, 3:int, 4:float | — |
| `app.SkirtNode` | 2 | 1 | — | — |
| `app.expr_node.Em0161_ShoulderExpr` | 2 | 1 | 8:float, 9:bool | 0:float, 1:float, 2:float, 3:float, 4:float, 5:float, 6:float, 7:float |
| `app.expr_node.MotDiffQuatNode` | 2 | 1 | 0:int | 0:quat |
| `via.motion.exprgraph.JointDecomposeRotateNode` | 2 | 1 | 6:int, 11:quat, 100:int | 112:vec3, 20:float, 21:float, 22:float |
| `via.userdata.exprgraph.FloatMapNode` | 2 | 1 | 0:float, 1:float, 2:float, 3:float, 4:float, 5:bool | 0:float |
| `via.userdata.exprgraph.MaFloatMathNode` | 2 | 5 | 0:int, 2:float, 3:float | 1:float, 2:float, 3:float |
| `via.userdata.exprgraph.QuatInverseNode` | 2 | 5 | 0:quat | 0:quat |
| `via.userdata.exprgraph.QuatValueNode` | 2 | 1 | 0:quat | 0:quat |
| `via.userdata.exprgraph.Vec3SubNode` | 2 | 5 | 0:vec3, 1:vec3 | 0:vec3 |
| `app.expr_node.Em0070_FangConstraint` | 1 | 1 | — | — |
| `app.expr_node.Em0077_DistanceConstraint` | 1 | 1 | — | — |
| `app.expr_node.Em0077_ThornConstraint` | 1 | 1 | — | — |
| `app.expr_node.Em0078_DistanceExpr` | 1 | 1 | 0:float | — |
| `app.expr_node.Em0078_RSExpr` | 1 | 1 | — | — |
| `app.expr_node.Em0155_TailConstraint` | 1 | 1 | — | — |
| `app.expr_node.Em0157_DistanceConstraint` | 1 | 1 | — | — |
| `app.expr_node.Em0157_GillConstraint` | 1 | 1 | — | — |
| `app.expr_node.Em0160_ThornConstraint` | 1 | 1 | — | — |
| `app.expr_node.Em0161_AimExpr` | 1 | 1 | — | — |
| `app.expr_node.Em0161_DistanceExpr` | 1 | 1 | — | — |
| `app.expr_node.Em0163_LegConstraint` | 1 | 1 | — | — |
| `app.expr_node.Em1164_TailConstraint` | 1 | 1 | — | — |
| `via.motion.exprgraph.ExprMeshSetMaterialNode` | 1 | 1 | 0:int, 10:int, 11:int, 13:float | 12:5, 13:float, 14:float, 15:float, 16:float, 22:5, 23:float, 24:float, 25:float, 26:float … |
| `via.motion.exprgraph.JointExprGraphLayerBlendRateNode` | 1 | 1 | — | 0:float |
| `via.motion.exprgraph.MaGetConstraintScaleNode` | 1 | 1 | 0:int, 2:int | 12:vec3, 20:float, 21:float, 22:float |
| `via.userdata.exprgraph.FloatAbsNode` | 1 | 1 | 1:float | 0:float |
| `via.userdata.exprgraph.FloatClampNode` | 1 | 5 | 0:float, 1:float, 2:float | 0:float |
| `via.userdata.exprgraph.FloatMinNode` | 1 | 1 | 0:float, 1:float | 0:float |
| `via.userdata.exprgraph.SawToothWaveNode` | 1 | 1 | 1:float, 2:float, 3:float | 0:float |
