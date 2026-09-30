# UI 框架

每个 section 的编辑方式都不同，所以框架只管三件事：**有哪些分区、能对它做什么、怎么在视口里看到效果**。
每个分区具体怎么编辑，留给它自己的编辑器面板。

## 分层

| 层 | 文件 | 内容 | 能否离线测 |
|---|---|---|---|
| 事实 | `modules/jcns_kinds.py` | `KINDS`（图标、是否有序、能否新建、用哪个预览后端）和 `capabilities(kind, FileState)`（能否编辑/增/删/换序 + 原因） | `tests/test_kinds.py` |
| 预览规划 | `modules/jcns_preview_plan.py` | Skin/Aim/RotExpr → 描述一个原生骨骼约束的 `ConstraintPlan`（含 warnings） | 同上 |
| 预览实现 | `jcns_preview.py` | `PreviewBackend` 接口、`DriverBackend`（Ranges）、`ConstraintBackend`、通用的 `jcns.preview_apply/clear` | `tests/test_bpy_ui.py` |
| 框架 UI | `jcns_ui.py` | 状态、文件、分区浏览器（图标标签页 + 条目列表 + ＋－▲▼）、预览面板 | 同上 |
| 各分区编辑器 | `jcns_editors.py` | 每种类型一组面板，只在当前条目是该类型时出现 | 同上 |

条目仍然是 Empty，`constraint_type` 存类型。列表的数据是 `Collection.objects`（`template_list` 要真正的 RNA 集合；
`Object.children` 是 Python 元组），`rp.entry_index` 用 get/set 读写活动物体，所以列表、视口、大纲三处自动同步，不需要 handler。
标签页 `rp.browser_kind` 只是过滤器；选中别的分区的条目时，浏览器给一个"切到该分区"的按钮（`prop_enum`）。

## 谁说了算

`capabilities()` 是唯一的规则来源：面板灰掉某个按钮，和对应 operator 的 poll / execute 用的是同一个函数
（`jcns_operators._caps_for`）。以前这些规则散在 `_sections_editable`、`_draw_version_note`、`_skin_table_locked`
和各 operator 里。

| | 重建版本（v35/v102） | 就地版本（v22/v29…） |
|---|---|---|
| Ranges | 全部可以 | 只能改数值：不能增删、换序、改骨骼名 |
| Skin / Aim / RotExpr | 可编辑，可增删，**不换序**（顺序含义未证实）；Skin/Aim 带读取骨表且没设骨架、RotExpr 映射非单一常量时不能增删 | 全部锁定，导出原样保留 |
| Material | 可编辑、可删，不能新建 | 只能改哈希/变换 ID |
| JXG | 可编辑、可删，不能新建 | 锁定 |

## 预览（"驱动器"的推广）

Ranges 的驱动器就是一种预览：按下"应用"，视口里的骨架动起来。其余分区只要能说成"这根骨跟着那根骨"，
就能用 Blender 原生骨骼约束表达。两者走同一套接口：

    Kind.preview → BACKENDS[id] → units（一组必须一起应用的条目） → apply / clear / refresh

- **unit**：Ranges 是同一 (骨骼, 变换, 轴) 通道上的所有约束（Blender 一个通道一个驱动器，且只有最后一条生效）；其余是单条。
- Ranges 驱动器按实测的引擎行为读源骨（2026-09-30，测试台第 6–8 轮）：目标旋转固定按 XYZ 欧拉合成（引擎是 静止·Rz·Ry·Rx，与文件里各轴的先后无关）。源骨读的是相对父骨的**完整**变换，静止姿态和静止偏移都算在内，`+25`（读取方式 ReadMode，源面板里的枚举）决定怎么分解：0 = 位置分量，1 = 欧拉分量（顺序由 +27 欧拉顺序决定），2 = 缩放，3 = 绕 X 的摆动-扭转（q = 摆动·扭转；X 取扭转角，Y/Z 取 2·atan2(s_轴, s_w)），4 = 同上但 q = 扭转·摆动，5 = 旋转向量分量；3/4/5 在源的参考系四元数（原 rest_quat）里分解。驱动器取源骨三个通道，`jcns_ch` 重建完整变换后按 `modules/jcns_source_read.py` 分解。条目按文件顺序求值，所以源骨的某个通道如果由本条或后面的条目驱动，就读静止值。目标旋转按变换类型合成（第 9 轮实测，与源读取方式一一对应）：1 = XYZ 欧拉，4 = 摆动·扭转，5 = 扭转·摆动，6 = 旋转向量，13/14 = 每根骨一个绕所写轴的旋转、骨上最后一条 13/14 胜出；非欧拉类型的骨头整骨成组预览。目标条目 Flags bit0 为 1 时值叠在静止姿态上，为 0 时替换静止姿态。静止旋转为单位的骨头两者没有区别；静止旋转非单位、又有 bit0=0 旋转通道的骨头，三个 rotation_euler 驱动器作为一组生成，每个都按整根骨求值（静止姿态的欧拉角里换掉被替换的通道，再叠上叠加通道），只有单轴静止、纯替换的情形实测过。平移 bit0 已实测（第 10 轮）：1 在父骨轴上叠加静止位置，0 只替换所写轴，未写轴保留静止偏移；预览用三个 location 驱动器一起把父骨轴增量换回 Blender 的静止局部基底，编辑、缓存重建和清除都整组处理。单位静止缩放下，bit0=0/1 都把输出写到对应缩放轴，未写轴保持 1；非单位静止缩放仍未测，当前不声称乘法和直接替换已被区分。驱动器直接使用表达式结果，移除默认 identity 键，避免接近 0/1 的小值被 F-Curve 吸附。
- 状态存在条目上的 `preview_on`（`preview_bone` 记录约束现在挂在哪根骨上，改了目标骨能清理旧的）。
- 编辑属性时 `update` 回调调 `jcns_preview.refresh()`；预览已开则跟着刷新，没开则零开销。改到没有有效预览的状态（例如瞄准轴变成斜的）会撤掉旧约束。

| 分区 | 后端 | 对应 | 置信度 |
|---|---|---|---|
| Ranges | driver | 目标骨通道上的脚本驱动器（已实机验证） | 实测 |
| Skin | constraint | `ARMATURE` 约束，各源骨按权重混合（不归一化，和权重和≠1 时警告） | 语义高，**预览未验证** |
| Aim | constraint | `DAMPED_TRACK`，轴取 Vec1（必须是坐标轴，否则拒绝）；up 骨和其余向量不参与 | 语义中，**未验证** |
| RotExpr | constraint | `TRANSFORM` 约束，局部旋转→旋转，每轴 ×系数（`rot_floats`），REPLACE | 语义中高，**未验证** |
| Material / JXG | 无 | Blender 里没有对应物 | — |

这些预览是**拿来对照游戏的假设**，不是结论。已知疑点：Armature 约束对有父骨的骨骼可能把父级运动算两遍；
Transformation 约束按欧拉分量乘系数，引擎是否如此未测；预览约束和 Ranges 驱动器同时作用在同一根骨上时叠加方式与引擎不一定一致。

## 新增一种分区 / 预览

1. `modules/jcns_kinds.py`：加一条 `Kind`，在 `capabilities()` 里写规则，跑 `tests/test_kinds.py`。
2. `jcns_editors.py`：继承 `_EditorMain` 写主面板，需要的话加子面板（原始字段用 `_Sub` 默认折叠），加进 `_classes`（父在前）。
   面板开头调 `_begin()`，它按 `capabilities` 决定整块能否编辑并画出原因。
3. 要预览：复用 `constraint` 后端（在 `modules/jcns_preview_plan.py` 加一个 `plan_*`，在 `jcns_preview._plan_for` 接上），
   或者写新的 `PreviewBackend` 注册进 `BACKENDS`。
4. `jcns_ui.JCNS_UL_Entries.draw_item` 里想给行加状态图标就在那里加。
5. `tests/test_bpy_ui.py` 用带该类型条目的样本再跑一遍。

## 测试

    python tests/test_kinds.py          # 纯 Python
    python tests/test_bpy_ui.py         # 需要 bpy：pip install bpy（云端可用）

`test_bpy_ui.py` 在无界面的 Blender 里注册插件、导入样本，用会校验的假 `UILayout`（未知属性名、operator、图标、
枚举值都会抛错）画出每个面板，检查列表过滤/排序/活动条目、operator 的能力检查、各预览后端的应用/刷新/清除，
以及导出条目数不受预览影响。它**看不到排版**，只能保证代码能跑、引用的东西都存在。

## 待讨论：各分区的编辑器怎么做

现在每个分区的编辑器都是把原有界面**原样搬**进各自的面板（只把 Ranges 拆成子面板、原始字段折叠）。
下面这些是搬完之后值得重新设计的地方，按分区列出：

- **Ranges**：映射方式二选一显示（已做：有 ComplexMapping 的源在「映射曲线」里显示关键帧曲线，曲线本身是约束 Empty 上的
  F-Curve，在曲线编辑器里编辑，见 jcns_cm.py）；列表行应显示"被后面覆盖"（已做）和"静止时已偏转"；多源约束的编辑流程。
- **Skin**：权重和≠1 的处理（现在只警告）；源数超过 4 的提示；预览验证后是否默认归一化。
- **Aim**：`RotationType` 决定 up 骨和 `vec0` 是否有意义（1/2 必带 up 骨，0/3/4/5 从不带，`vec0` 只在 2 非零），
  应当放进主面板并据此显示/隐藏字段，而不是全放"原始字段"。
- **RotExpr**：`rot_floats` 大概是每轴系数，是真正要改的数据，现在藏在原始字段里；`rot_rotation`/`rot_scale` 是恒等四元数，
  `rot_scale` 这个名字有误导性。
- **Material**：哈希编辑对人不友好；项目里有 `hashUTF16`，可以做"输入名称→算哈希"（未确认材质名哈希用的是同一个函数）。
- **文件级数据**：ObjectSettings、ConeDriver 表、读取骨表目前只读展示；ObjectSettings 的含义还没研究过。
