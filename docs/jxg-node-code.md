# JXG 节点的代码依据（Wilds exe）

`jntexprgraph.md` 第 11 节的结论来自这里：每个节点的字段偏移、关键函数 RVA 和判断依据，以后换补丁重读或有疑问时查。
RVA 只对 2026-10-31 的 MonsterHunterWilds.exe 有效，换补丁要重新定位（方法见 re-engine-live-probing skill 的 exe-analysis.md：
`find_vtables.py` 用类型哈希找虚表，5 秒；`dump_vtable.py` 反汇编被覆盖的槽）。

标记：**码** = 直接读指令；**原生** = 在本进程映射 exe 调用过函数核对；**推** = 从结构推出，没直接读到。

## 0. 公共部分

- 节点族共用的槽 0 = 14b7e8a80；147/180 个类型找到虚表，其余是抽象类或 C# 类。
- 虚表只到槽 24；更后面已经是下一张表。DebugGamePad 所在的小族每张表前多 3 项，表前第 −3 项是工厂。
- 族槽：7/8 get/setBool、9/10 Int、11/12 Float、13/14 Vec3、15/16 Vec4、17/18 Quat、19/20 get/setObject(slot, obj)、
  21 setExtraData(ptr, size)、22 执行类别、24 每帧更新、25/26 见下。默认实现 b46f210 返回 0，b4716b0 空函数。
- 对象 +0x20 = 首帧标志：构造时置 1，执行器调完槽 24（aa7cf4f `call [rax+0xC0]`）后在 aa7cf5b 清零。
- 四元数乘 b005890(out, a, b) 算的是 b⊗a（原生）。四元数在内存里是 x y z w。

## 1. 执行器（码）

| RVA | 作用 |
|---|---|
| a66c670 → aa7e110 | 每帧入口；两个调用点 a62996d、a6b1f59 传入的入口键都是 0 |
| aa7b170 | 初始化：ctx+0x40 = 图头[+0x32] & 1；节点 kind & 2 不实例化；随后 aa7b6a0(mask=−1) 把全部属性写进节点 |
| aa7de20 | 跑一张图：在入口表（图头 +0x18，项数图头 +0x2C，每项 u32 键、u16 起点、u16 个数）里按键查；清零执行计数；按根顺序调 aa7db90；带 0x6000 的根跳过 |
| aa7dcd0 | 沿一条执行连线执行目标；`cmp [node+0x18], 0x3e8` 限制每节点每次图运行 ≤ 1001 次 |
| aa7ce10 | 执行单个节点 |
| aa7cfd0 | 拉一条数据连线；执行流模式下只有 kind bit2 的源重算 |
| a9a28e0(this, 槽) | 取第一条匹配该出口槽的执行出口 |
| 跳表 E05F874 起 | 连线类型转换，按 目标类型 × 源类型 两级分发 |

执行类别（槽 22）：0 纯函数 92 个；1 有更新 41 个；2 惰性 9 个（槽 25 = 先拉掩码，槽 26 = 需要掩码）；
3 流程控制 5 个（仅 ctx+0x40 非 0 时尾调槽 25 `execute(this, edx = 进入的执行槽, r8 = ctx)`）。

执行出口：节点记录 +0x20 是表偏移（基址同 +0x08），+0x2B 是项数；每项 4 字节 `u16 目标（bit15 app，& 0x1FFF 序号）,
u8 目标执行入口槽, u8 本节点出口槽`。语料 113 个文件出口数全为 0、+0x32 全为 0（码 + 语料统计）。
kind bit0 在执行器里找不到读取点（推：无运行时作用）。没找到键非 0 的入口被触发的路径。

## 2. 流程控制与逻辑

| 节点 | RVA | 依据要点 |
|---|---|---|
| ExeFlowCtrlIf | d08ba40 | 条件存 +0x28（任意槽 bool）；真时走出口 0 |
| ExeFlowCtrlSequential | ae7e3a0 | 按文件顺序走全部出口，不看出口槽号 |
| ExeFlowCtrlCaseSwitch | d08bad0 | int 1 = N、int 2 = s；0 ≤ s < N 走 s+10，该出口没接线时 bool 为真才走 9；越界走 9 |
| ExeFlowCtrlForLoop | d08b930 | int 1/2 起止，序号存 +0x30（getInt 任意槽）；do-while，含两端；出口 0 体、11 结束；入口槽 12 置 Break 标志；没接出口 0 时序号 = 终点直接走 11 |
| ExeFlowCtrlBitFlagsSequential | ae7e400 | bt 掩码，出口 10+i；bt 对 32 取模，出口槽 < 10 会回绕（槽 9 对应 bit 31） |
| IntSwitchCase | ae7e4d0 / d08bee0 | 选择和个数只存 int8；个数 > 8 时 s = 8 读到默认值，s ≥ 9 读到对象外的数据 |
| MaFloatCondition | cfa1260 | 输出 1 = 条件 ? 槽 2 : 槽 3；输出 2/3 原样 |
| MaFloatChoice | 类别 2 | 先只拉槽 0，再只拉槽 k+1；k < 0 或 ≥ 8 输出 0 |
| MaFloatLogic | cfa1130，跳表 e0d0254 | 运算只存低 8 位（推：惯用槽 0）；NaN 时只有 != 为真 |
| FloatGreater / FloatLess | setter cf9f120 | 没有 float 输出 |
| BoolOperatorNode | — | 只覆盖 setBool；getBool 是默认 `xor eax, eax`（推：BoolAnd/Or 的基类，FloatOperatorNode 同理） |
| SquareWave | d08d750（setter cf9e7a0、更新 d08d590 与 SinWave 共用） | 默认周期 1、A 0、B 1；周期 ≤ 1.19e-7 输出 0；t ≤ 周期/2 输出 B |
| TriangleWave | d08d6b0 | 同上，A→B→A，u 夹到 0–1 |
| JointGetRotationEulerDegree | 更新 aee4da0 | 分解函数 b02a840 同基础版；空间存 +0x54，非 1/2 按局部；getQuat 默认全 0 |
| JointGetPositionCm | 更新 aee5500 | 空间存 +0x50；恒 × 100 |

## 3. 读写游戏状态

**ExprPropertyAccessNode**（虚表 e122c40）
- 额外数据解析 ae7e6f0（码）：+0 i64 类型表偏移（相对额外数据起点）、+8 i32 类型数；类型表项 16 字节：+0 i64 属性表偏移、
  +8 u32 组件类型哈希（b0cdf40 查）、+0xC u32 属性数；属性表项 8 字节：+0 u8 槽号、+4 u32 属性哈希（b07c050 比 [desc+8]）。
  类型数和属性数按 byte 存（≤ 255）；类型找不到整条跳过，属性找不到用静态空描述符 148c1a88。
- 槽查找 d08c8b0：按 byte 比较、取第一条匹配，所以 ≥ 256 的槽号永远找不到。
- setObject ae7e610：只认槽 0xFF，类型必须是 via.GameObject 或子类（全局 14958ec0；依据：注册点 18d7ff4 附近引用的属性名
  Transform/Components/Valid/Folder/TagValue）。连过槽 255 时 +0x4C = 1、对象在 +0x28，之后即使传空也不回退。
  没连时用 `[[this+0x10]]+0x10`（推：图所属组件的 GameObject）。
- 组件查找 b0a9370：沿 GameObject+0x18 → 组件+0x18 链比较类型指针（推：精确匹配、不认子类），每次读写都重查。
- 描述符：+0x18 低 5 位是种类，+0xC bit2 = 只读，setter = [+0x10] + (i32)[+0x3C]。
  种类 2 bool、7 int、0xB float、0xC double（getFloat 排除，读 0）——码；7/8 = s32/u32、0x10 值结构、0x11 引用——推。
  getVec3/4/Quat：种类 0x10 直接写 16 字节，0x11 且子类 1/2 取指针再拷贝；Vec3 的 w = 0；Quat 失败给单位。
  setVec3/4/Quat 共用 d08cd50，要求 (种类 & 0x1E) == 0x10。getVec3/4/Quat 不检查结构大小，超过 16 字节会写越界。
- 读写函数：1b1d0 / a4cea30 / a4ceb10 / a4cec00 / a4cec90。槽 24 是默认空函数（没有每帧更新）。

**FindGameObjectNode**（e122d10）
- 槽 24 覆盖成空函数 b029780；getObject（槽 19，ae7e960）不看槽号。
- 额外数据由 d08d060 原样拷到 +0x30：+0 u8 模式；1 = +8 GUID，b033430 查场景 GUID 表，全零返回 null；
  2 = +8 UTF-16 路径，381fd50 → b03e0f0 按 '/' 分段 wcsncmp 逐级递归，开头 '/' 跳过并置标志（推：绝对路径）。
- 缓存 +0x28（AddRef），缓存对象 +0x18 非 0 时直接返回（推：+0x18 是 Transform，销毁后清空）。
  搜索 `[[147ca238]+0x90]`，按名查加 `[147ca238]+0x328` 锁（推：SceneManager 的主场景）。

**DebugGamePadNode**（e0cc060）：工厂 cf9ee80 只分配 0x20 字节；getBool 3eed0 恒 false，setInt 6de0 直接 ret，getFloat 137400 恒 0。

**JointGetVelocityNode**（e12e550）：setInt d11e070 只认 0/2/5；getVec3 d11e0b0（任意槽，不查骨有效）；分量 aee61d0；
更新 aee6230：v = Δp × timer[+0x368] ÷ b007180（b007180 = timer[+0x34C] × GameObject+0x34 时间缩放，< 0 用场景缩放；
Transform+0xC0 bit0 再 × 2），计时器 147ca1f0。空间 2 没有单独分支（差分里基础姿态抵消）。无除零保护。

## 4. 网格

**ExprMeshSetBlendShapeNode**（e0e5750，更新 aee6a50）
- 条目 16 字节：+0 哈希、+4 权重、+8 u16 0xFFFF（不用）、+0xC 已给值标志；槽 0 ≥ 41 时清空。
- 组件类型 [1495a6f8]（与 Material 节点相同）；名字表 383bf40(组件) = 网格资源 +0x208 → +0x28，+0x1C 个数，+0x20 起 u32；
  权重表 b116df0 = 组件 +0x538 → +0x10，+0x20 起 float；提交 a77ced0。
- jcns 求值器 kind 3（Deform）也调 383bf40（调用点 a6254dc），用记录 +0x24 比 [+0x20+i*4]（a625fb4），写 值 × BlendRate（a625fd0）。
- 标志置位后不再清除；同哈希出现多次只写第一处。

**ExprMeshSetBlendShapeNormalizeNode**（e0e5840，更新 aee6c30）：K 存 +0x40（d11e810）；临时表 ≤ 40 条，N < 32 希尔排序，否则 d11e870。
权重相等时保留谁取决于排序交换顺序。

**ExprMeshSetMaterialNode**（e12e9a0，更新 aee64a0）
- 组 32 字节：+0 vec4、+0x10/+0x14 两个哈希、+0x1C 材质下标、+0x1D 参数下标、+0x1E 分量掩码；组数无上限。
- 查找 b03f250（材质）、a77b380（参数），找不到记 0xFF；缓存字段 +0x40 只见清零不见写入，实际每帧重查。
- 参数类型 a77b3b0：1 float（掩码 bit0 为 0 时读回不写，yzw 清零；写 a77b4e0）；4 float4（读 a77b980 补未给分量，写 a77b5f0）。
- 插值：BlendRate 在 节点 +0x28 → +0x94（与 JointSet* 同处）；原值 b0e9040（推：mdf2 默认值）。setter 跳表 d11e6e0 / e12ea68。
- 哈希核对：ch90_163 的 0x61d678c3 = ch90_163_0000_body_1001、0x3d41ce06 = AO_to_Cavity；鬼武者 26 个里 18 个在 mdf2 找到名字，全部一致。

## 5. 骨与旋转

**JointSetLocalCoordNode**（e12e2f0，更新 aee5da0，LOD 判定 aee44a0，构造 d11df10 默认缩放 1）：r ≥ 1 直接写（旋转不归一化）；
0 < r < 1 位置缩放线性、旋转 slerp（短路径）；r ≤ 0 不写。

**JointComposeRotateNode**（e12e6f0）：d11e1b0 → cf4b0f0（核心 b1148d0）/ cf4b340（指数映射）；构造 d11e0f0。
摆动接近 180°（cos φ < −0.9999）时固定成绕 Z 180°。度数时 getQuat 原地把存的角度 × π/180（码；推：常数输入或多个下游时重复换算）。
原生：200 组随机输入误差 ≤ 2e-7。

**JointDecomposeRotateNode**（e12e620，更新 187b80 → 187c60，核心 b0d90c0 / cf4b210；构造 b491e10）：
u = ref*·q·ref；方式 0：X' = u·X，b = −2·atan2(X'.z, 1+X'.x)，c = 2·atan2(X'.y, 1+X'.x)，a = 扭转角包到 [−π, π]；
方式 1 = −G(u*)；方式 2 对数映射，不翻 w 符号。X' ≈ −X 走特殊分支，纯 180° 输出全 0。原生：往返误差 ≤ 1e-6。
语料：ch90_150_0000 / 5000 各 1 个（输入接 JointGetRotation，度，方式 0，下游 DriverFloat 用 20、22）。

**ExpMapToQuat**（e12e880，构造 d11e3a0）：与 Compose 方式 2 同一函数 cf4b340；槽 14 setVec3 只有 ret。
**QuatToExpMap**（e12e7b0，构造 d11e260）：getVec3 是默认实现。

**JointDriverFloatNode**（e12ecf0，更新 aee7230，合并跳表 e12ef08，setter cfd40 / e12eee8）
- 新驱动器是 2 个全零关键点；少于 2 个关键点结果 0；x 降序时 b12c810 原地反转（永久）；不单调结果 0。
- 原生：降序 (6,0),(0,1) 输入 3 → 0.5；插值 0–4 在 t = 0.5 得 0.5 / 0.125 / 0.875 / 0.5 / 0.5；两驱动器 1 和 3 时合并 0–5 得 4 / 2 / 3 / 1 / 3 / 1。
- 语料 ch90_150/152 共 16 个：单驱动器、线性，有降序输入范围；属性顺序 int、bool、float 正好是中点生效需要的顺序。

**JointDriverVec3Node**（e12edd0，更新 aee7500，跳表 e12ef4c，vec3 setter d11fb80 / e12ef1c）：
没有输入的驱动器被跳过但仍计入个数（影响平均除数和"第一个"）；三轴都已给后再给分量被忽略。

## 6. 锥形与 RBF

**锥形求值**（cf49ea0 初始化 Cone 结构 0x50 字节）：+0 qOff、+0x10 v1 参考、+0x20 v2 当前、+0x30 v3 椭圆轴、+0x40 半角、
+0x44 椭圆比 k（≤ 1.19e-7 关闭）、+0x48/49 主轴 / 椭圆轴内部码、+0x4A/4B Vector 标志、+0x4C 参考是否乘 qOff（节点里恒 0）。
轴枚举 0–5 经 cf4b500 转成内部码 1/2/3/5/6/7（bit2 = 负轴），6 = Vector 另设标志。取四元数某轴 a5d9e40。

- cf49ed0(cone, qA, qB)：q = qB⊗qOff；ref = q·e、cur = qA·e（负轴两边同取反）；Vector 时 ref = (+0x4C ? q : qB)·v1、cur = qA·v2；
  归一化（长度 < 1.19e-7 不归一化）；椭圆修正 cf4a810：d̂ = ref，a = 椭圆轴，n = normalize(d̂×a)，m = n×d̂，cur 在 m 上的分量 ÷ k 再归一化；
  θ = acos(d̂·ĉ)，θ < A 取 1 − θ/A 否则 0；dot ≥ 1 或 ≤ −1 直接返回 1（cf4a1fc 先置 1，cf4a2a0、cf4a2b2 带着它退出）；A ≤ 0 返回 0。
  原生：6 轴各 20 组 ≤ 2.7e-7，向量模式 ≤ 2.5e-7，椭圆 ≤ 3e-7。
- cf4aca0(cone, pTarget, pJoint, qB)：cur = normalize(pTarget − pJoint)，重合返回 0；负轴只有 ref 取反。原生 ≤ 5.6e-7。
- jcns Outputs 求值器 a623bc0 在 a623f06 调 cf49ed0、a623eb1 调 cf4aca0；用到记录 +0x58 AngleRad、+0x4C Joint、+0x50 Parent、
  +0x63 bit0 BasePose，**+0x54 ≠ −1 时走位置版**。推：jcns Matrix 三行 = v1/v2/v3，尾字节 06 06 = 两轴都是 Vector，
  构建时 +0x4C 置 1；UnknownUInt32 可能是 k。jcns 构建 Cone 结构的代码没追到（ce0fa20 只做默认初始化）。

**ConeInputNode**（e12ea90，构造 d11eed0，Cone 在 +0x20）：qA +0x70、qB +0x80、轴 +0x68/+0x6A、椭圆轴 +0x69/+0x6B
（与主轴同轴时 k 清 0）、半角 +0x60（度转弧度）、k +0x64（写 1 存 0）、槽 104 存 +0x90 但不读。
依据 d11ef30、d11efd0、d11f090（跳表 e12eea8）、d11f010、getFloat aee6e60（NaN 返回 1，经 _dtest）。

**JointConeInputNode**（e12eb50，构造 d11f140，Cone 在 +0x40）：骨 +0x30（b6e4df0 只认槽 0）、欧拉顺序 +0x98（默认 2）、
参考骨 +0x90（默认 −1 = 父骨）、目标骨 +0x94、BasePose +0x9C（qB ⊗ 关节信息表 [idx·0x40+0x10]，推：静止局部旋转）、+0x9D 见 docs。
欧拉转四元数 b0e1f40（原生：6 种顺序同 Joint 槽 3）；世界旋转 b005690，世界位置 b028ba0 → 1c450。
依据 d11f190、d11f1b0、d11f2c0、d11f300、getFloat aee6ee0。槽 13 的效果取决于写入那一刻主轴是不是 Vector。

**JointConeDriverNode**（e12ec20，不是 Joint 子类）：条目数组 +0x28、数 +0x30，条目 16 字节（输入、插值、OutMin、OutMax）；
输出 +0x38；更新 d11f500，跳表 e12eec0 / e12eed4；NaN 输入按 1；合并方式 > 4 输出 0。
**MaConeRemapNode**（e0e5bb0，更新 d120650）：NaN 输入得 OutMax；插值存 u8。

**MaRadialBasisFunctionNode**（e12f130）：解析 aee87c0（槽 21，保留指向原数据的指针 +0x148；≤ 16 字节整段忽略）；
有效标志 +0x140，槽 0/1 的个数与额外数据不符时清掉且不再置回；槽号无越界检查。头部 +0 u32 不读、+0xD 不读（推：AllowNegative）。
距离 aee9ea0；核 aeea030（跳表 e12f1f8，> 5 输出 0）；更新 aee9850（无效时跳过、输出保持上一帧）；余弦插值 b07f040。
吸附：Rᵢ ≥ ε 且 dᵢ < Rᵢ 时 t = dᵢ/Rᵢ；t ≤ Eᵢ 直接输出目标并返回；否则 wᵢ = 1 − [Eᵢ + (1−Eᵢ)(1 − cos πu)/2]，
u = (t−Eᵢ)/(1−Eᵢ)，取 wᵢ 最大的姿势与结果混合（Eᵢ > 0 时内圈边界处有跳变，代码如此）。
仿射项开关打开时权重每行 O+I+1 个，但更新读第 P 到 P+I 行，越界读到空指针（推：发布数据从不打开，或引擎 bug）。
RBF 只读了代码、没原生跑（解析和更新依赖分配器与运行时对象）。
