# 实机探测：xaihi 测试台

这里的脚本用来在 MH Wilds 里实测 JCNS 字段的含义：生成测试用的 jcns，在游戏里录制，
再分析录下的数据。到 2026-09-30 为止跑了 12 轮，已成立的结论写进插件代码和
`modules/jcns_parser.py` 的文档字符串。

## 测试台

- **位置**：`MonsterHunterWilds/natives/STM/art/model/character/ch03/xaihi/`，用户自建的 mod，
  挂在装备件 `ch03_017_0012` 上。
- **原版备份**：
  - `xaihi_model.mesh.241111606.orig_20260929`
  - `xaihi_constraint.jcns.102.orig_20260929`（8 条裙骨约束）
- **mesh**：573 根骨。`TestTgtA`…`TestTgtK` 挂在 `Ear_SCL` 下。
  - 第 4–10 轮都是绕 X 转 −2°，偏移 (0, −59.55, 1.34) cm。
  - 这个静止姿态正好用来区分"叠加 / 替换""左乘 / 右乘"。
  - 第 11 轮 B/C/D/G 改成多轴静止旋转，E/F/G 改成非单位静止缩放，详见下表。
- **每轮的 jcns**：都从 `.orig` 起建，保留原版 [00]–[07]，从 [08] 起是测试条目。
  - 当前游戏里的是第 11 轮，录制保存在 `reframework/data/round11_keep/`。
  - 之前各轮存为 `xaihi_constraint.jcns.102.roundN`。
- **录制脚本**：`reframework/autorun/jcns_cm_rig_sweep.lua`，副本 `jcns_cm_rig_sweep.lua` 在本目录。
  - F8 开始，F9 停止。
  - 输出上限 `OUT_SCAN_MAX = 80`，所以一轮的条目总数要少于 80。

## 一轮测试怎么做

1. **先查语料**：`python scripts/probes/corpus_fields.py [字段名]`。
   - 看这个字段在 1103 个原版 v102 文件里有哪些取值，以及跟什么相关（源骨、文件、读取方式……）。
   - 固定不变的字段不用测。跟着某个特征走的字段，就按那个特征设计测试。
2. **写生成脚本** `build_<主题>_rig.py`：照着现有的改，从 `.orig` 克隆 [00]。
   - 条目会继承 [00] 的所有隐藏字段。要测哪个字段就显式设置它，其余保持 [00] 的值：
     `EulerOrder=0`、`U32_2=0`、`Tail[1]=2`、`+72=0`、`ParentFloat2=0`。
   - 关节组计数（Tail[3]）一律写 0，并用 `tail_group_counts(cons) == [0]*n` 断言。
     克隆来的计数一旦错了，输出会写到别的骨头上。
   - 每条用不同的系数，这样看骨头姿态就能认出是哪一条在起作用。
   - 在脚本开头的文档字符串里写清每个 Out 索引对应哪条条目。
   - 运行前先备份当前的 jcns：`cp -n xaihi_constraint.jcns.102 xaihi_constraint.jcns.102.roundN`。
3. **用户重启游戏**：新的 jcns / mesh 要重启才生效。
   - F8 开始录，把大腿 X 轴从 −90° 扫到 40° 左右，然后按 F9。
4. **保存数据**：把 `reframework/data/jcns_cm_rig_s*.csv` 拷到 `data/roundN_keep/`。
5. **分析**：写 `analyze_<主题>_rig.py`，在数据目录里运行。
   - 用成对比较、候选排名的思路，参考 `analyze_axis_bits_rig.py` / `analyze_ttype_rig.py`：
     把每种候选公式都算出来，看哪个的误差最小。
   - 结论成立的标准是误差 ≤0.002°，而且明显好于第二名。
6. **写进代码**：
   - 纯公式放 `modules/jcns_source_read.py`。
   - 在 `tests/test_source_read.py` 里加一个读 `roundN_keep` 的 capture 检查。`tests/` 不进 git。
7. **验证预览**：在后台 Blender 里跑，不会碰用户开着的 Blender：
   ```
   blender.exe --background --factory-startup --python scripts/probes/bg_check_preview.py -- --addon-dir <本仓库绝对路径> --data <roundN_keep> --stride 1
   ```
   Blender 在 `E:/Program/Steam/steamapps/common/Blender/blender.exe`。界面代码的检查同样用后台 Blender 跑
   `tests/test_bpy_ui.py`。它需要 `samples/` 里的两个样例文件，那个目录现在不在仓库里，
   需要时从 `MHWILDS_EXTRACT/.../ch90/008/0000/` 取。
8. **收尾**：更新 `jcns_parser.py` 文档字符串里的字段说明、`docs/ui-framework.md` 和记忆，然后提交。

## 数据格式与坑

- **`jcns_cm_rig_sweep.csv`**：`Out<i>` = `getOutputUserValue(i)`，即第 i 条条目自己算出的值，单位是弧度，
  按条目顺序排列，不受分组和"谁胜出"影响。
- **`jcns_cm_rig_skel.csv`**：装备件 0012 全骨架的局部四元数，列名为 `<骨名>_qx/qy/qz/qw`。
  - **只有 5 位小数**，比较前要先归一化，否则会凭空多出约 0.4° 的误差。
  - 0012 里的 `L_Thigh` 是本体骨的副本，**录下来是不动的**。
    所以引擎的真实输入要从一条线性条目反推，比如 `x = Out8 / 0.5`。
- 用户的 Blender 经常开着别的工作（RE6 场景等），**不要切场景、也不要清预览**。只做两件事：
  1. 把代码复制到 `%APPDATA%/Blender Foundation/Blender/5.1/extensions/user_default/wilds_jcns_editor/`；
  2. 用户同意后，用 MCP 重新加载插件（`addon_disable` / `addon_enable`，并清掉 `sys.modules` 里的旧模块）。
- 后台 Blender 必须带 `--factory-startup`，否则用户装的其他插件会在启动时崩掉。
  RE Mesh Editor 要关掉 `showConsole`，否则 `wm.console_toggle` 在没有窗口时会崩。
- bash 的 heredoc 里混用引号时容易被截断。较长的补丁先写成 .py 文件再运行。
- **后台 Blender 的退出码不可信**：脚本里抛了 Python 异常，进程照样返回 0。判断通过与否要看输出里的
  `RESULT` / `Traceback` / 测试自己打印的 OK 行。
- **旧轮回归要把 jcns 和 mesh 都指定成那一轮的快照**（`--jcns`、`--mesh`），默认用的是游戏目录里的当前文件。
  RE Mesh Editor 按扩展名判断版本，`xaihi_model.mesh.241111606.before_round11_…` 这种带后缀的备份读不了；
  快照要用标准文件名存进 `roundN_keep/`（第 10、11 轮都已存好）。

## 十二轮结论一览

| 轮 | 脚本 | 结论 |
|---|---|---|
| 1–4 | `build_cm_rig.py`、`build_map_rig.py` | ComplexMapping 是 Hermite 曲线；测试骨"不响应"的原因是关节组计数（Tail[3]） |
| 5 | `build_preempt_rig.py` | 同一通道由文件里最后一条胜出，与是否成组无关 |
| 6 | `build_order_chain_rig.py` | 旋转按 静止·Rz·Ry·Rx 合成；条目按文件顺序、在同一帧内求值；+25=3 读的是含静止姿态的扭转角 |
| 7 | `build_src_id_rig.py` | +25 ReadMode：0 位置，1 欧拉，2 缩放，3 摆动·扭转，4 扭转·摆动，5 旋转向量 |
| 8 | `build_axis_bits_rig.py` | +27 = 欧拉顺序；Flags bit0 = 叠加 / 替换；rest_quat = 读取参考系；CurveMode bit0 无作用 |
| 9 | `build_ttype_rig.py` | 旋转类变换类型：1 欧拉，4 摆动·扭转，5 扭转·摆动，6 旋转向量，13/14 每根骨一个单轴旋转、最后一条胜出 |
| 10 | `build_pos_scale_rig.py` | 平移 bit0=1 按父骨轴叠加静止位置，bit0=0 仅替换所写轴；单位静止缩放下 bit0=0/1 相同，非单位缩放仍待测 |
| 11 | `build_combined_rig.py` | 多轴静止欧拉 bit0=0 仅替换所写轴；非单位缩放 bit0=0/1 都直接替换所写轴；13/14 与平移、缩放共存，前后顺序相同 |
| 12 | `build_sections_rig.py` | Aim / Skin / RotExpr 首次实测，见下 |

## 第 10 轮：已录制并验证

- 生成：`build_pos_scale_rig.py --output <staging.jcns.102>`；分析：
  `python scripts/probes/analyze_pos_scale_rig.py --data <round10_keep> --json <report.json>`。
- 25 条条目，沿用原 mesh。Out8 / TestTgtA 是旋转控制；B/C 为三轴平移 F17/F16，
  D/E 为三轴缩放 F17/F16，F/G 为仅 Y 平移 F17/F16，H/I 为仅 Y 缩放 F17/F16。
  J/K 不驱动，记录静止位置和缩放基准。具体 Out 索引见生成脚本文档字符串。
- 录制器新增 `jcns_cm_rig_trs.csv`：每根 TestTgt 骨的 `px/py/pz/sx/sy/sz`，
  与 sweep/skel 同帧；缺少 getter 时记 NaN，分析必须拒绝。录制位置和 Out 平移值为米，
  文件映射锚点为厘米；分析器把位置误差转换成厘米，缩放无量纲。
- 三份 CSV 一起保存到 `reframework/data/round10_keep/`。分析按 Frame 对齐，拒绝空数据、
  重复帧、缺帧、非有限数据，以及不足 30° 的输入跨度。旋转控制要求 ≤0.002°；
  位置候选要求 ≤0.0001 cm，缩放候选要求 ≤0.00001，并检查候选区分度。
- 现有骨静止缩放为 1，所以某些“乘静止缩放 / 直接替换”公式等价。候选并列不能作为
  唯一结论；若要区分这些公式，还需非单位静止缩放测试。
- 部署前备份：游戏 xaihi 目录中的 `xaihi_constraint.jcns.102.before_round10_20260930_035314`；
  autorun 中的 `jcns_cm_rig_sweep.lua.before_round10_20260930_035314`；旧 CSV 存在
  `reframework/data/before_round10_20260930_035314/`。备份与部署均已校验 SHA-256。
- 本轮 2008 帧，反推输入覆盖 −90° 到 39.35°。旋转控制最大误差 0.000716°；
  平移公式对 Out 的最大误差 0.00005 cm，缩放 0.0000005。
  平移叠加候选的次优误差 ≥0.1548 cm；单轴替换 G 若丢掉整组静止位置则误差 1.34315 cm。
- 预览已按父骨轴平移公式实现，换成 Blender basis 时逆转静止旋转；三个 location 驱动器
  成组维护，支持缓存重建、编辑刷新和整组清除。缩放保持现有直接通道预览，只声明单位静止缩放实测范围。
- `bg_check_preview.py` 已支持 TRS、Frame 对齐、本仓库代码加载与 JSON 报告。后台 Blender
  对 2008 帧 / 11 根骨验证通过：位置 ≤0.0000287 cm，缩放 ≤0.000000644，旋转 ≤0.0007°。
  第 9 轮回归（每 10 帧采样，254 帧）仍 ≤0.0011°。驱动器生成时清掉默认 identity 键，
  避免 F-Curve 在接近 0/1 时把小值吸附到键值。
- 本地 capture 检查在 `tests/test_source_read.py`，生命周期检查在 `tests/test_translation_preview.py`；
  `tests/` 仍不进 git。完整分析和后台报告随录制保存在 `round10_keep/`。

## 已实测的欧拉替换规则

变换类型 1（欧拉旋转）的 bit0=0 只替换所写轴的静止欧拉分量，其余轴保留。
现有 `override_basis` 已按此实现，第 11 轮已直接验证 XYZ 静止欧拉 (-2°,17°,-23°)
下仅写 X、仅写 Y，以及全写 XYZ 的结果，最大误差 0.001026°。
类型 4/5/6/13/14 保留第 9 轮已测得的旋转合成规则。

## 第 11 轮：组合测试，已录制并验证

- 生成：后台 Blender 加 `--factory-startup --python scripts/probes/build_combined_rig.py -- --output-dir <staging>`。
  不重导出 mesh；只补丁 B/C/D/G 的静止旋转及 E/F/G 的静止缩放，更新对应 local/world/inverse
  矩阵，并检查矩阵一致性、叶骨条件和其他字节完全不变。生成的 `round11_plan.json` 保存
  实际 float32 静止姿态、每条 Out 索引、修改范围及文件 SHA-256。
- 原版语料：22839 条约束中，897 个同文件同名目标存在 13/14 与 0/2 共存；这只证明实际用途，
  不证明它们的求值规则。
- 共 44 条（原版 8 条 + 测试 36 条），录制器 Out 扫描上限 80 足够，仍录 sweep/skel/trs 三份 CSV。

| 骨 | 静止姿态 / 测试 | Out |
|---|---|---|
| A | 原版静止，类型 1 F49 X，输入控制 | 8 |
| B/C | XYZ 静止欧拉 (-2°,17°,-23°)，类型 1 F48 分别只写 X / Y | 9 / 10 |
| D | 同上，类型 1 F48 写 XYZ | 11–13 |
| E/F | 静止缩放 (1.4,0.7,1.8)，类型 2 分别 F17 / F16，只写 Y | 14 / 15 |
| G | 不驱动；多轴静止旋转 + 非单位静止缩放基准 | 无 |
| H/I | 类型 13 F49 Y 分别位于平移 XYZ、缩放 XYZ 的前 / 后 | 16–22 / 23–29 |
| J/K | 类型 14 F49 Y，其他同 H/I | 30–36 / 37–43 |

- 所有隐藏字段显式设置与第 10 轮相同，具体见生成脚本文档字符串。平移/缩放映射也沿用第 10 轮；
  13/14 的 Y 增益 0.6；欧拉替换 XYZ 增益 (0.5,0.8,-0.9)。E/F 不写 XZ，用来检查是否保留静止分量。
- 分析：`python scripts/probes/analyze_combined_rig.py --data <round11_keep> --json <analysis.json>`。
  必须把部署时的 plan 和 mesh/jcns/录制脚本快照一起存档。按 Frame 对齐且至少 100 帧 / 30° 输入跨度；
  先检查 A 控制和 G 的旋转、位置、缩放基准，再排名逐轴替换、整组替换、前后乘法等候选。
  共存逐项检查旋转/位置/缩放，并比较 H/I、J/K 和 13/14 的成对差异。候选并列不算唯一结论。
- RE Mesh Editor 将原始静止矩阵存为骨自定义属性；Blender 骨的静止矩阵不保留非单位缩放，网格就绑定在
  这个不带缩放的静止姿态上，所以 Blender 的 pose 缩放是**相对静止缩放的比值**：缩放目标驱动
  `引擎值 / 静止缩放`，缩放源读 `pose 缩放 × 静止缩放`，导入不改 pose（验收时改成这样；原先把绝对缩放直接写进 pose，
  会让带子骨或蒙皮的骨头在静止时就被缩放）。`bg_check_preview.py` 比较的是 `pose 缩放 × 静止缩放`。
  镜像和剪切矩阵不在本轮覆盖范围内。
- mesh 已改变时，旧轮预览回归应显式指定 `bg_check_preview.py --mesh <该轮的原 mesh 快照>`。
- 2026-09-30 部署：mesh/jcns/录制脚本的原文件旁均有 `.before_round11_20260930_044406` 备份，
  旧三份 CSV 在 `reframework/data/before_round11_20260930_044406/`；新 mesh/jcns/plan 和实际录制脚本
  快照在 `reframework/data/round11_setup_20260930_044406/`。备份、快照及部署已校验 SHA-256。
  后台导入和预览应用成功；合成数据检查通过分析器各项排名及单位换算，不属于游戏实测证据。

- 2352 帧，反推输入 -90° 到 39.454°，A 控制误差 0.000707°；G 静止旋转误差 0.000197°、
  缩放误差 4.77e-8，证明游戏加载了多轴旋转和非单位缩放的新 mesh。
- B/C 的逐轴欧拉替换误差分别 0.001010° / 0.001026°，次优候选 2.0008° / 17.1935°。
  D 写满 XYZ，逐轴与整组替换等价，只作合成控制，误差 0.000999°。
- E/F 的 bit0=1/0 结果相同：写 Y 后为 `(1.4, Out, 1.8)`。直接替换最大误差 5e-7；
  乘静止缩放的次优候选误差 0.335509，明确排除乘法和数值加法。
- H/I/J/K 均匹配静止旋转·Ry，旋转误差 0.001005°；平移在父骨轴叠加，误差 0.0000543 cm；
  缩放写入输出，误差 5e-7。H/I 和 J/K 前后顺序的录制 TRS 完全一致；13/14 成对角差
  ≤0.001146°（5 位小数录制精度内），位置/缩放一致。本轮只覆盖 F49 的单 Y 旋转及 F17 平移/缩放。
- 全 2352 帧、11 骨后台预览通过：旋转 ≤0.0011°，位置 ≤0.0000337 cm，缩放 ≤7.64e-7。
  本地 `tests/test_round11_preview.py` 验证清除/重应用、静止缩放恢复和已有姿态/动画的保护。
  `tests/test_source_read.py` 的本轮 2352 帧纯公式检查最大误差 0.001027°；
  第 10 轮后台回归（201 个采样帧）通过。
  三份 CSV、部署快照、分析和预览报告均存于 `reframework/data/round11_keep/`。

## 第 12 轮：Aim / Skin / RotExpr

- 生成：`build_sections_rig.py --output <jcns>`；分析：`analyze_sections_rig.py --data <round12_keep> --plan <round11_plan.json>`
  （`--self-test` 用合成数据自检）。mesh 沿用第 11 轮。数据、部署的 jcns/mesh/录制器、分析结果都在 `round12_keep/`。
- **xaihi 原 jcns 的 section table 是 [0]，不在表里的分区引擎不执行**；脚本改成 [1,3,2,0]（0 Ranges / 1 RotExpr / 2 Skin / 3 Aim /
  4 Material / 5 JXG，语料 1103 个文件的表与分区存在性一一对应）。编辑器导出目前不会补表。
- 录制器新增 `jcns_cm_rig_world.csv`：`b.` 本体骨、`e.` 装备件骨的世界位置和旋转。`b.X` 与 `e.X` 对手、头、大腿完全一致。
  3181 帧，输入跨度 138°，对照 A 误差 0.0007°，不驱动的 G 在 Ear_SCL 下的相对位姿漂移 0.26 mm / 0.0002°。
- **Aim**（Vec0 0、Vec1 (1,0,0)、Vec2=Vec3 (0,1,0)，瞄 R_Hand）：五种类型都以本地 +X 指向目标（偏差 ≤0.0035°）。
  翻滚：类型 0 与 3 取世界 +Y（残差 0.004°，次优 ≥179°）；类型 1 取 up 骨（L_Hand）的位置方向（0.0026°）；
  类型 2 取 up 骨自己的 +Y 轴（0.005°，该轴在 D 本地系下恒定 0.0°）；类型 4 从静止姿态的最短弧（0.025°，无翻滚约束）。
  类型 0 与 3 在这组向量下无法区分；Vec1 只测了 (1,0,0)，所以“Vec1 就是瞄准轴”还没被证明。
- **Skin**（J 三源 0.5/0.3/0.2，K 两源 0.5/0.25）：位置 = 各源蒙皮矩阵的线性混合，有效权重 = 权重除以权重和
  （K 拟合出 0.66667/0.33333，与名义权重 0.5/0.25 的残差 345 m）。旋转 = 各源 R_i·X_i 的四元数加权和再归一化，每个四元数先翻到
  “累计和”的半球（J 0.0001°，K 0.0002°；翻到第一个的半球、w≥0、不翻都不行）。
- **RotExpr**（E 字节 (0,0,0,0)，F 字节 (0,48,0,0)，系数 (0.5,0.8,−0.9)，源 L_Thigh）：F = 静止·E（误差 0.0017°），
  E 不含静止姿态。输出是源旋转的函数，无滞后（k=0 最小）。小角度时每轴 ×系数（源 |θ|≈4° 时比值 0.795/−0.895）；
  角度大时偏离线性，最好的候选是“四元数向量部 ×系数、w 重算”（最大 8.6°，中位 1.2°），旋转向量 ×系数 12.9°，
  各种欧拉顺序 ≥19°。精确形式**未定**，需要单轴系数的测试。

## 还没做的

按价值排序。「现有测试台」表示第 11 轮的 mesh 和录制脚本够用，只需要写新的生成脚本；「改 mesh」表示要先改测试骨。
面板上带 `QUESTION` 图标的规则都属于这里的待测项。

**一、影响现有功能的正确性**

1. **Skin / Aim / RotExpr 三个分区从没进游戏实测过**（现有测试台）。预览用 Blender 原生约束模拟，
   面板上标着"效果可能与游戏里不同"。它们在原版里很常见，也是 Ranges 之外用户最常编辑的部分：
   - Skin：各源骨按权重混合，权重和不为 1 时怎样算？
   - Aim：Vec1 是瞄准轴吗？辅助骨（up 骨）和 Vec2/Vec3 起什么作用？
   - RotExpr：是不是按轴乘系数的旋转拷贝？与 Ranges 写同一根骨时谁先谁后？
2. **镜像规则**（现有测试台）：`jcns_mirror` 的符号只按欧拉角推导过，没考虑读取方式 3/4/5（扭转角、摆动分量）、
   变换类型 4/5/6/13/14，也没考虑参考系四元数和欧拉顺序。做法：用镜像工具生成左右成对的条目，在游戏里看两侧是否对称。
3. **面板上还标着推断的规则**（现有测试台）：
   - 类型 4/5/6 在 bit0=0 时怎样替换（预览按"丢掉整个静止旋转"处理）。
   - 类型 14 在 bit0=0 时是否与 13 相同。
   - 同一根骨上欧拉通道叠加与替换混用（预览按 `override_basis` 的模型）。
   - 同一根骨上混用不同的旋转类型（预览按最后一条的类型处理；原版里没见过）。
4. **缩放作为源**（现有测试台）：ReadMode 2 读非单位静止缩放骨（第 11 轮的 E/F/G）。预览按"pose 缩放 × 静止缩放"读取，
   这是从目标侧的实测结论推出来的，还没有直接测过。
5. **父骨带缩放时的子骨**（改 mesh）：父骨静止缩放不为 1 时，子骨的平移目标是在缩放后的父空间里，还是未缩放的父空间里？
   负缩放和剪切矩阵也没覆盖。

**二、尚未知道含义的字段**（都较少见）

6. ParentFloat2：旋转目标上的 (-45,0)、(-90,-90) 这类值像是限制或阻尼，可以在现有测试台上直接设值试。
7. Tail[0]（+74）、Tail[1]（+75，大多整份文件只用一个值）、+72、+28、+29=2。
   在"高级 / 原始字段"里按"隐藏固定字段"后，面板上剩下的就是这些。
8. 带关键帧的源同时有非零三点锚点时的效果（面板上提示"效果未知"）。原版里没有这种组合，优先级低。

**三、需要新的观测手段**

9. 非骨骼目标：形变（类型 3）、材质（类型 7–12）和 CurveMode 4/5。需要能在游戏里读出材质参数或形变权重。
10. 类型 13 与 14 的区别：到目前为止所有测试里两者完全一样，可能要找原版里两者行为不同的用例才能区分。

**不需要进游戏的**

- 缩放比值写法对网格变形的影响，可以只在 Blender 里确认：找一根带子骨或蒙皮、静止缩放不为 1 的骨头，
  看静止时是否没有变形。xaihi 原版里没有这样的骨头，需要别的 mesh（解包目录里的 mesh 缺 streaming 文件，要重新解包）。
