# 实机探测：xaihi 测试台

这里的脚本用来在 MH Wilds 里实测 JCNS 字段的含义：生成测试用的 jcns，在游戏里录制，
再分析录下的数据。到 2026-09-30 为止跑了 9 轮，结论都已经写进插件代码和
`modules/jcns_parser.py` 的文档字符串。

## 测试台

- **位置**：`MonsterHunterWilds/natives/STM/art/model/character/ch03/xaihi/`，用户自建的 mod，
  挂在装备件 `ch03_017_0012` 上。
- **原版备份**：
  - `xaihi_model.mesh.241111606.orig_20260929`
  - `xaihi_constraint.jcns.102.orig_20260929`（8 条裙骨约束）
- **mesh**：573 根骨。`TestTgtA`…`TestTgtK` 挂在 `Ear_SCL` 下。
  - 它们的静止姿态都是绕 X 转 −2°，偏移 (0, −59.55, 1.34) cm。
  - 这个静止姿态正好用来区分"叠加 / 替换""左乘 / 右乘"。
  - 从第 4 轮起 mesh 没再改过。
- **每轮的 jcns**：都从 `.orig` 起建，保留原版 [00]–[07]，从 [08] 起是测试条目。
  - 当前游戏里的是第 9 轮。
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
   blender.exe --background --factory-startup --python scripts/probes/bg_check_preview.py -- --data <roundN_keep>
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

## 九轮结论一览

| 轮 | 脚本 | 结论 |
|---|---|---|
| 1–4 | `build_cm_rig.py`、`build_map_rig.py` | ComplexMapping 是 Hermite 曲线；测试骨"不响应"的原因是关节组计数（Tail[3]） |
| 5 | `build_preempt_rig.py` | 同一通道由文件里最后一条胜出，与是否成组无关 |
| 6 | `build_order_chain_rig.py` | 旋转按 静止·Rz·Ry·Rx 合成；条目按文件顺序、在同一帧内求值；+25=3 读的是含静止姿态的扭转角 |
| 7 | `build_src_id_rig.py` | +25 ReadMode：0 位置，1 欧拉，2 缩放，3 摆动·扭转，4 扭转·摆动，5 旋转向量 |
| 8 | `build_axis_bits_rig.py` | +27 = 欧拉顺序；Flags bit0 = 叠加 / 替换；rest_quat = 读取参考系；CurveMode bit0 无作用 |
| 9 | `build_ttype_rig.py` | 旋转类变换类型：1 欧拉，4 摆动·扭转，5 扭转·摆动，6 旋转向量，13/14 每根骨一个单轴旋转、最后一条胜出 |

## 还没做的

1. **变换类型 1 的 bit0=0，在静止姿态有多轴分量时怎么替换**：
   - 预览现在只替换所写轴的欧拉分量；类型 13 的结果提示可能是整个静止姿态都丢掉。
   - 要测需要一根静止姿态绕 Y/Z 转过的测试骨，得改 mesh。
2. **平移、缩放的 bit0**：替换时会不会把静止偏移也丢掉？现有 mesh 就能测，测试骨有偏移。预览目前一律按叠加。
3. **镜像**：`jcns_mirror` 的符号规则只按欧拉角推导过，没考虑变换类型 4/5/6/13/14 和读取方式 3/4/5，
   需要核对，或者用实测验证。
4. **剩下的未知活字段**（都很少见）：Tail[0]（+74）、Tail[1]（+75，大多整份文件一个值）、+72、ParentFloat2、+28、+29=2。
   在"高级 / 原始字段"里按"隐藏固定字段"后，面板上剩下的就是这些。
5. **类型 13 与 14 的差别**：测试里两者完全一样。它们的共存规律（与平移、缩放同在一根骨上）还没查。
6. **非骨骼目标**：形变（类型 3）、材质（类型 7–12）和 CurveMode 4/5 都没测过，需要能看到材质参数的观测手段。
