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

**额外数据**：FloatEaseCurveNode 4 字节（u32 `via.curve.EaseType`）；KeyFrameCurveNode 是曲线关键帧；
FloatMathCodeNode 是一段栈式字节码。两者的格式见第 8 节。

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

**Joint 节点的公共槽**（从节点代码读出，见第 8 节）

| 槽 | 类型 | 含义 |
|---|---|---|
| 0 | int | 骨名哈希 |
| 1 | int | LOD 门槛（Set 节点）：对象的 LOD 级别（某组件 +0x4E4，和 jcns TailBytes[1] 比较的是同一个字段）≤ 此值时才执行，−1 总是执行 |
| 2 | int | 坐标空间：0 局部（相对父骨）/ 1 世界 / 2 相对基础姿态 |
| 3 | int | 欧拉顺序（旋转节点）：0 XYZ（R = Rz·Ry·Rx）/ 1 YZX / 2 ZXY / 3 ZYX / 4 YXZ / 5 XZY，和 jcns 的 RotOrder 是同一个转换函数 |
| 5 | int | 长度单位（位置节点）：0 厘米 / 非 0 米 |
| 6 | int | 角度单位（旋转节点）：1 度 / 其余弧度 |

| 槽（输入或输出） | 类型 | 含义 |
|---|---|---|
| 10 | vec3 | 位置 |
| 11 | quat | 旋转 |
| 12 | vec3 | 缩放 |
| 13 | vec3 | 欧拉角（按槽 3 的顺序、槽 6 的单位） |
| 20 / 21 / 22 | float | 上面那个量的 X / Y / Z 分量 |

- JointGetPositionNode：属性 0/2/5，输出 10、20–22。
- JointGetRotationNode：属性 0/2/3/6，输出 11、13、20–22。
- JointSetPositionNode：属性 0/1/2/5，输入 10 或 20–22。
- JointSetRotationNode：属性 0/1/2/3/6，输入 11、13 或 20–22。
- JointGetLocalCoordNode：属性 0、4（bool），输出 10/11/12。
- MaGetConstraintScaleNode：属性 0、2，输出 12、20–22。

**数学节点**：两元运算（FloatAdd/Sub/Mul/Div、Vec3Add/Sub/Mul、QuatMul）输入 0、1，输出 0；
没接线的输入用属性给常数（例：FloatDiv 的 1 号槽 = 180）。可变输入的节点用一个计数属性加连续槽号：
FloatSum（属性 1 = 个数，输入 11 起）、FloatMathCode（属性 1 = 个数，输入 10 起）、
ExprZivaMeshExtraParam（属性 0 = 个数，从 10 起"名字哈希 / 值"成对）。

## 8. 节点怎么算（从游戏代码读出）

原生节点没有名字可查（类型反射只注册按编号存取的 getFloat(int idx)/setFloat(int idx, …)，exe 里也没有插槽名），
但每个节点类型的计算代码都在 exe 里，读出来就是确切含义。

**定位**：每个类型的注册函数里有 `mov edx, <类型哈希>`，随后调用一个 `mov [rip+G], rcx; ret` 小函数存类型对象；
虚函数表槽 3 是 `mov rax, [rip+G]; ret`，表的槽 0 对所有节点相同。按这个关系能静态找到 147 个类型的虚函数表
（和游戏内存里实际读到的节点对象一致）。表的槽位约定：7/8 get/setBool、9/10 get/setInt、11/12 get/setFloat、
13/14 get/setVec3、17/18 get/setQuat，24 起是派生方法（时间节点和 Joint 节点的每帧更新在 24）。
setX 把某个槽号的值存进对象字段，getX / 更新函数用这些字段计算——两者对照就是每个槽的含义。

已读的节点（地址只对当前 exe 有效）：

| 节点 | 槽 | 计算 |
|---|---|---|
| CyclicalAngle | 1 周期（秒） | 计时每帧加帧时间、满周期减周期；输出 2π × 计时 / 周期；周期 ≤ ε 时输出 0、计时不动 |
| SinWave / CosWave | 1 周期，2 A，3 B | A + (B − A)(1 + sin/cos(2π × 计时 / 周期)) / 2；周期 ≤ ε 输出 0，\|B − A\| ≤ ε 输出 B |
| SawToothWave | 1 周期，2 A，3 B | A + (B − A) × 计时 / 周期 |
| FloatSwitch | 0 条件，1 为假时，2 为真时 | 按条件只取一个输入 |
| FloatClamp | 0 值，1 最小，2 最大 | 值 < 最小取最小，否则 min(值, 最大) |
| FloatMap | 0 输入，1/2 输入下/上限，3/4 输出下/上限，5 钳制 | 下限 = 上限时取输出下限；钳制时把输入夹在 [下限, 上限]；然后线性映射 |
| FloatEaseCurve | 0 起点，1 终点，2 t（写入时夹到 0–1） | 起点 + (终点 − 起点) × ease(t)，ease 是额外数据里的 `via.curve.EaseType`（31 种 Penner 缓动：0 Linear、1 InSine、2 OutSine、3 InOutSine、4–6 Quad、7–9 Cubic … 28–30 Bounce），原版都是 3 |
| MaFloatRemap | 0 输入，1 输入三点，2 输出三点，3 插值，4 用中点 | ≤ 下点取输出下点，≥ 上点取输出上点；用中点时以中点分两段，否则一段；段内 t 夹到 0–1，插值 0 线性 / 1 t³ / 2 1−(1−t)³ / 3 3t²−2t³（同 jcns）；输入范围降序时两端连同输出一起对调；段宽 ≤ ε 时输出 0 |
| JointGetPosition | 见上表 | 空间 0 局部位置，1 世界位置，2 局部 − 基础姿态位置；单位 0 时 × 100 |
| JointSetPosition | 见上表 | 只写给了的分量，没给的保留当前值（按所选空间）；空间 2 写 基础姿态 + 值；单位 0 时输入 × 0.01 |
| JointGetRotation | 见上表 | 空间 2 为 基础姿态⁻¹ · 局部；欧拉角按槽 3 的顺序分解 |
| JointGetLocalCoord | 4 读基础姿态 | 输出局部位置 / 旋转 / 缩放；4 为真时取基础姿态，否则取当前；位置是米（不 × 100） |
| MaGetConstraintScale | 2 空间 | 输出缩放：0 局部，1 世界，2 局部 − 1 |
| LayerBlendRate | — | 输出所在图层的 BlendRate |
| FloatDiv | 0 A，1 B | B = 0 时输出 0 |
| FloatAbs / Rad2Deg | 1 值 | \|值\| / 值 × 57.2958 |
| Cos | 1 值，2 输入为度 | 2 非 0 时先把值从度换成弧度 |
| FloatSum | 1 个数，11 起各项 | 最多加 8 项 |
| MaFloatMath | 0 运算，2 A，3 B | 运算 0 加 1 减 2 乘 3 除（B = 0 得 0）4 取小 5 取大 6 乘方；输出 1 结果、2 A、3 B |
| Vec3Normalize | 0 向量 | 长度 < FLT_EPSILON 时原样输出 |
| Vec3Transform | 0 向量，1 旋转 | 用四元数旋转向量 |
| QuatMul | 0 A，1 B | B · A（引擎的 mul(a, b) 是 b · a） |
| QuatInverse | 0 四元数 | 真逆（不假定单位长度） |
| QuatSlerp | 0 A，1 B，2 t | t 夹到 0–1 后球面插值 |
| QuatToEulerFloat3 | 3 四元数，4 顺序 | 按顺序分解成三个分量（弧度）；顺序编号和 Joint 槽 3 同表，0–5 以外输出 0。实现不同（直接从四元数分解，Joint 节点先转矩阵），把两者从 exe 里拿出来跑 50 个随机四元数 × 6 种顺序，结果一致 |
| KeyFrameCurve | 0 输入 | 额外数据：u16 关键帧数、u8 前段外推、u8 后段外推、4 字节，随后每帧 28 字节，布局和 jcns Outputs 的 ComplexMapping 记录相同（FromX、ToX、FromY、ToY、FromZ、ToZ、u32），引擎用同一个求值函数 |
| FloatMathCode | 1 个数，10 起各输入（最多 8 个） | 额外数据是栈式字节码，见下 |
| JointSetRotation | 见上表 | 给四元数直接用；给欧拉向量按槽 3 合成；只给分量时其余分量取当前旋转按同一顺序分解的值（空间 2 取的是基础姿态⁻¹ 的分解）；空间 0 替换局部旋转，1 设世界旋转，2 写 基础姿态 · 结果 |

Set 节点都会乘图层的 BlendRate：小于 1 时位置线性插值、旋转球面插值到结果。

**FloatMathCode 字节码**：

| 码 | 参数 | 作用 |
|---|---|---|
| 01 | f32 | 压常数 |
| 02 | u16 n | 压第 n 个输入（n ≤ 7） |
| 03 | u8 | 一元运算作用于栈顶：2 取负 |
| 04 | u8 | 二元运算 栈顶 ○ 次顶（后压的在左）：1 加 2 减 3 乘 4 除（除数 0 得 0）5 取余 |
| 05 | u16 函数号, u8 参数数 | 1 个参数：deg2rad rad2deg sin cos tan acos asin atan floor ceil round abs sign ln log10 log2 exp sqrt；2 个：atan2 pow min max；3 个：clamp(x, 下, 上) lerp(a, b, t)（参数从栈顶起依次取） |

结果是栈里剩下的唯一一个值，否则为 0。例：`02 01 00 02 00 00 04 01` 先压 in1 再压 in0，得 in0 + in1。
ch90_161 里一对镜像程序的符号正好相反，印证了"后压的在左"。

**帧时间**：时间节点每帧加的是真实秒数。更新函数取一个全局计时对象的 +0x34C（本帧相当于 60 fps 下的帧数，
实测 1.0998）除以 +0x368（基准帧率 60），即本帧秒数（同一对象 +0x358 = 0.01833 秒），再乘所属对象的
时间缩放（对象 +0x34，小于 0 时用全局缩放）；对象的某个标志 bit0 打开时再乘 2（隔帧更新）。

**连线的类型转换**（执行器按 目标类型 × 源类型 两级分发，调源节点的 getX、目标节点的 setX）：
到 bool 时 float / int 是 != 0（精确比较）、vec3 是任一分量 != 0、quat 是不等于单位四元数；
bool 或 float 到 vec3 是 (x, x, x)。

## 9. 预览

`modules/jxg_eval.py` 按上表求值，`jxg_preview.py` 在每次换帧和编辑后读骨架、写回骨骼（关掉时还原）。
空间换算和 Wilds-Dynamics 相同：RE Mesh Editor 把游戏的 Y 向上绕 X 转 +90° 烘进骨骼（RX），骨的游戏局部变换是
父骨姿态⁻¹ · 姿态（根骨 RX⁻¹ · 姿态），根骨挂在 RX⁻¹ · 物体 · RX 上。时间 = (当前帧 − 起始帧) / 帧率。

和引擎不同的地方：

- 计时：播放时按时间轴步长累加；往回拖或一次跳超过 1 秒时从 时间 mod 周期 重新起步；不换帧的改动不推进时间。
  引擎是按帧时间累加的。注意周期一变，角度会按新的比例跳一下——引擎也是这样（它累加的是时间不是角度）。
- LOD 门槛不模拟（节点总是执行），BlendRate 按 1。
- 连到布尔槽：引擎是精确的 != 0；预览允许 1e-4 的误差，因为从 Blender 矩阵读出的姿态在本该是 0 的地方有 1e-7 量级的残差。
- LayerBlendRate 输出 1；MaGetConstraintScale 输出 1（空间 2 输出 0），因为预览的骨架不带缩放。
- 不预览、输出按 0：C# 节点、MaEulerConstraint、JointDriverFloat、JointDecomposeRotate、Ziva、材质节点、DebugDraw。
  MaEulerConstraint（只在怪物上）和 JointDriverFloat（每个驱动 9 个槽，只在 Ziva 上）的代码读过，没有移植。

测试 `tests/test_jxg_eval.py`（纯 Python）和 `tests/test_jxg_bpy.py`（后台 Blender）。

## 10. 还没解决的

- 节点 +0x34 的哈希；文件头 +0x20、图头 +0x28/+0x34、尾段 +0x18 的哈希。
- "隔帧更新"标志由什么决定。
- 其余节点的代码（读法同第 8 节）：JointDecomposeRotate，以及语料里没出现的速度、锥形、RBF、属性读写等节点。

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
