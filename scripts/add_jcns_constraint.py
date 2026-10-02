"""
add_jcns_constraint.py
-----------------------
Append brand-new single-source Rotation constraints to a .jcns.102 file, for
authoring fresh engine-behaviour test cases (see .claude/skills/engine-behavior-sweep).

Works by deep-copying an existing constraint as a template (so all the
"unknown, preserved verbatim" auxiliary fields carry known-good real values)
and only overriding: ObjectName, TransformAxis_parent, and the single
source's SourceName/source_axis/from_*/to_* anchors. JCNSWriter re-derives
hashes/indices from the names on write, so no hash bookkeeping is needed here.

Usage: edit the NEW_CONSTRAINTS list below and run.
"""
import copy
import os
import shutil
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'modules'))

from modules.jcns_parser import JCNSParser
from modules.jcns_writer import JCNSWriter

AXIS = {'X': 0, 'Y': 1, 'Z': 2, 'W': 3}

JCNS_FILE = r"E:/Program/Steam/steamapps/common/MonsterHunterWilds/natives/STM/art/model/character/ch03/xaihi/xaihi_constraint.jcns.102"

# (target_bone, target_axis, source_bone, source_axis, (fs, fk, fe, ts, tk, te))
# Round 5: dedicated, animation-free rig (TestSrc/TestTgtA/B/C, all parented to COG,
# no skinning/physics/skinning weight, created solely for this test) driven live via
# reframework MCP (via.Joint.set_LocalRotation) instead of in-game CSV capture — see
# jcns-degenerate-segment-investigation memory. All three share the same source/axis
# so one sweep of TestSrc.X drives all three targets at once.
# Round 9 —— 从干净的 7 条基线(bak_8)重建，一次加全 A~I。
#
# 关键设计变更：**源骨骼一律用 L_Thigh(本体骨架上的真实骨头)，不再用 TestSrc。**
# （当时的理由"源必须在本体骨架上"已于 2026-09-30 实测推翻：装备骨当源能正常解析，
#  读的是它被约束驱动后的姿态。Round 8 真正的原因是测试骨不在骨架里；之后测试骨
#  "姿态对不上自己的约束"则是因为克隆条目照抄了 TailBytes[3] 关节组计数，
#  引擎把相邻条目并成一组写到组首的骨头上。现在的 jcns_writer 会自动推导这个字节。）
#
# 目标仍然全用 TestTgt*(干净骨头，无蒙皮/无物理/无动画)，所以输出是纯粹的约束结果。
# 所有条目共享同一个输入 x = L_Thigh.X，角色跑动时自然扫过大范围，一次采集同时验证
# 所有假设，不需要(也没法)人为控制源。
# ---------------------------------------------------------------------------
# Round 10：追加 3 条，把剩下的三个问题一次测完。
# 追加不会打乱已有条目的索引(0~16)，所以之前的分析结论仍然对得上。
# Out 槽位是**按条目**算的，跟目标骨是否重复无关(I1/I2 共用 TestTgtI 却各有各的 Out
# 值就是证据)，所以这三条直接复用已有骨头当目标，不用再建骨骼。
#   [17] = C 但只改 to_kink(0 -> 30)   → 非退化时 to_kink 到底有没有用
#   [18] = C 但只改 from_kink(0 -> 25) → 折点的 x 位置有没有用
#   [19] = 三点全塌缩但 to_kink=33≠0   → 全塌缩返回的是字面 0 还是 to_kink
# 对照组就是已有的 [09] TestTgtC：from=(-45,0,45) to=(-20,0,40)
ROUND10 = [
    ('TestTgtA', 'X', 'L_Thigh', 'X', (-45.0,  0.0, 45.0, -20.0, 30.0, 40.0)),
    ('TestTgtB', 'X', 'L_Thigh', 'X', (-45.0, 25.0, 45.0, -20.0,  0.0, 40.0)),
    ('TestTgtC', 'X', 'L_Thigh', 'X', ( 10.0, 10.0, 10.0,   5.0, 33.0,  7.0)),
]

_ROUND9 = [
    # A: from_start==from_kink 退化（目前 3 轮实测都死的那个分支）
    ('TestTgtA', 'X', 'L_Thigh', 'X', (-45.0, -45.0, 0.0, -25.0, -25.0, 0.0)),
    # B: from_kink==from_end 退化（语料库主流、已知活的对照组）
    ('TestTgtB', 'X', 'L_Thigh', 'X', (0.0, 45.0, 45.0, 0.0, 30.0, 30.0)),
    # C: 两段都不退化的干净基线（验证整条链路 + 对照 eval_piecewise）
    ('TestTgtC', 'X', 'L_Thigh', 'X', (-45.0, 0.0, 45.0, -20.0, 0.0, 40.0)),
    # D: from_start==from_kink 退化 + **不一致的 to 对**（塌缩锚点上两个候选值矛盾，看引擎认哪个）
    ('TestTgtD', 'X', 'L_Thigh', 'X', (-45.0, -45.0, 0.0, -25.0, -70.0, 0.0)),
    # E: from_kink==from_end 退化 + 不一致 to 对（D 的对照组）
    ('TestTgtE', 'X', 'L_Thigh', 'X', (0.0, 45.0, 45.0, 0.0, 30.0, 75.0)),
    # F: 三个锚点全部重合成一个点（最极端退化）
    ('TestTgtF', 'X', 'L_Thigh', 'X', (0.0, 0.0, 0.0, -10.0, 0.0, 25.0)),
    # G: from 区间降序（C 的镜像），验证 eval_piecewise 的降序分支
    ('TestTgtG', 'X', 'L_Thigh', 'X', (45.0, 0.0, -45.0, 40.0, 0.0, -20.0)),
    # I1/I2: 两条独立 ConstraintInfo 抢同一个 (TestTgtI, X) 通道，数值正负相反。
    # 按 jcns-combine-rules，后面那条应该整条胜出、I1 被完全丢弃。
    ('TestTgtI', 'X', 'L_Thigh', 'X', (-45.0, 0.0, 45.0, -20.0, 0.0, 20.0)),   # I1，应被丢弃
    ('TestTgtI', 'X', 'L_Thigh', 'X', (-45.0, 0.0, 45.0, 20.0, 0.0, -20.0)),   # I2，应胜出
]

# H: 双源求和 —— TestTgtH.X 由两个独立源共同驱动。
# 所以用 L_Thigh + R_Thigh（跑动时两条腿相位相反，正好能把"求和"和"只取其一"区分开）。
_ROUND9_MULTI = [
    ('TestTgtH', 'X', [
        ('L_Thigh', 'X', (-45.0, 0.0, 45.0, -20.0, 0.0, 20.0)),
        ('R_Thigh', 'X', (-45.0, 0.0, 45.0, -20.0, 0.0, 20.0)),
    ]),
]

# ---------------------------------------------------------------------------
# Round 11：之前所有合成条目都深拷贝 constraints[0] 当模板，于是清一色继承了
# Flags=48 / ReadMode=1 / CurveMode=0 —— 而语料库统计(884 文件 / 23031 源)
# 显示 Flags bit0=1 占 86.5%，也就是**出货数据的主流配置我们一条都没测过**。
#
# 这一轮做因子对照：同一套几何(= [09] TestTgtC 的几何)，逐个改动那三个辅助字段，
# 看谁真正改变行为。第 6 个元素是覆盖字典：Flags 写到约束上，另两个写到源上。
#   [20] 主流配置基准    49 / 3 / 3
#   [21] = [20] 但 to_kink 0->30   → 主流配置下折点到底有没有用
#   [22] = [20] 但 Flags 49->48    → 单独隔离 Flags
#   [23] = [20] 但 ReadMode 3->1 → 单独隔离 ReadMode(疑似决定"源读什么量")
#   [24] = [20] 但 CurveMode 3->0   → 单独隔离 CurveMode
# 再跟已有的 [09](48/1/0，同几何)对比，就能看出两套配置整体差多少。
_MAIN = {'Flags': 49, 'ReadMode': 3, 'CurveMode': 3}
_GEO = (-45.0, 0.0, 45.0, -20.0, 0.0, 40.0)
_GEO_KINK = (-45.0, 0.0, 45.0, -20.0, 30.0, 40.0)   # 只改 to_kink

ROUND11 = [
    ('TestTgtD', 'X', 'L_Thigh', 'X', _GEO,      dict(_MAIN)),
    ('TestTgtE', 'X', 'L_Thigh', 'X', _GEO_KINK, dict(_MAIN)),
    ('TestTgtF', 'X', 'L_Thigh', 'X', _GEO,      dict(_MAIN, Flags=48)),
    ('TestTgtG', 'X', 'L_Thigh', 'X', _GEO,      dict(_MAIN, ReadMode=1)),
    ('TestTgtH', 'X', 'L_Thigh', 'X', _GEO,      dict(_MAIN, CurveMode=0)),
]

# ---------------------------------------------------------------------------
# Round 12：Round 11 只在一个几何上验证了"+24 是曲线模式开关"。这一轮系统补齐：
#   (a) +24 == 2 —— 出货组合 (2,1) 里的那个模式，从没测过
#   (b) 把 Round 9 的全部退化结论**在三点模式(+24=3)下重测**——之前那些全是在
#       +24=0(两点直线)下做的，而那种模式下一切本来就是直线，等于没测
#   (c) 降序区间、双源求和，同样在三点模式下重测
# 全部固定 +25=1，这样 Out0(+24=0,+25=1)的自校准 x 对所有条目都适用。
_M2 = {'ReadMode': 1, 'CurveMode': 2}   # 出货组合 (2,1)，未测模式
_M3 = {'ReadMode': 1, 'CurveMode': 3}   # 三点分段，已证实
_GEO_C = (-45.0, 0.0, 45.0, -20.0, 0.0, 40.0)

ROUND12 = [
    # (a) +24==2 是什么模式：跟 [09](直线) 和 [23](分段) 比
    ('TestTgtA', 'X', 'L_Thigh', 'X', _GEO_C,                              dict(_M2)),
    ('TestTgtB', 'X', 'L_Thigh', 'X', (-45.0, 0.0, 45.0, -20.0, 30.0, 40.0), dict(_M2)),  # 只改 to_kink
    # (b) 三点模式下的退化行为（与两点模式的结论逐条对照）
    ('TestTgtC', 'X', 'L_Thigh', 'X', (-45.0, -45.0, 0.0, -25.0, -25.0, 0.0), dict(_M3)),  # start==kink, to 一致
    ('TestTgtD', 'X', 'L_Thigh', 'X', (-45.0, -45.0, 0.0, -25.0, -70.0, 0.0), dict(_M3)),  # start==kink, to 矛盾
    ('TestTgtE', 'X', 'L_Thigh', 'X', (  0.0,  45.0, 45.0,   0.0,  30.0, 30.0), dict(_M3)),  # kink==end, to 一致
    ('TestTgtF', 'X', 'L_Thigh', 'X', (  0.0,  45.0, 45.0,   0.0,  30.0, 75.0), dict(_M3)),  # kink==end, to 矛盾
    ('TestTgtG', 'X', 'L_Thigh', 'X', (  0.0,   0.0,  0.0,   5.0,  33.0,  7.0), dict(_M3)),  # 三点全塌缩
    # (c) 降序区间（[23] 的镜像，同为三点模式）
    ('TestTgtI', 'X', 'L_Thigh', 'X', ( 45.0,  0.0, -45.0,  40.0,  0.0, -20.0), dict(_M3)),
]

# 双源求和在三点模式下重测
ROUND12_MULTI = [
    ('TestTgtH', 'X', [
        ('L_Thigh', 'X', (-45.0, 0.0, 45.0, -20.0, 0.0, 20.0)),
        ('R_Thigh', 'X', (-45.0, 0.0, 45.0, -20.0, 0.0, 20.0)),
    ], dict(_M3)),
]

# ---------------------------------------------------------------------------
# Round 13:
#   (a) 把 Round 12 那批退化几何在 +24=2 下再做一遍，跟对应的 +24=3 条目逐帧比。
#       Round 12 只在一种非退化几何上证明了 2 和 3 一致；若退化情形也全为 0，
#       +24 就能彻底简化成"0=直线，非0=折线"。
#   (b) 同通道抢占(I1/I2)换个观测对象：之前用 TestTgt* 读不到骨头姿态(装备件上的
#       纯测试骨在 on_frame 时机读到的值跟自己的约束对不上——2026-09-30 查明是关节组
#       计数照抄造成的写入错位，不是读取时机)，但**真实裙骨的姿态是能正常读到的**。R_Dress_HJ_00 的 X 轴目前没人占，拿它做抢占实验。
#       两条数值正负相反，读骨头 X 就知道谁胜出。用 +24=0(直线)让预期值最简单。
_M2 = {'ReadMode': 1, 'CurveMode': 2}
_M0 = {'ReadMode': 1, 'CurveMode': 0}

ROUND13 = [
    # (a) +24=2 的退化组，几何与 Round 12 的 [27]~[31] 一一对应
    ('TestTgtA', 'X', 'L_Thigh', 'X', (-45.0, -45.0, 0.0, -25.0, -25.0, 0.0), dict(_M2)),
    ('TestTgtB', 'X', 'L_Thigh', 'X', (-45.0, -45.0, 0.0, -25.0, -70.0, 0.0), dict(_M2)),
    ('TestTgtC', 'X', 'L_Thigh', 'X', (  0.0,  45.0, 45.0,   0.0,  30.0, 30.0), dict(_M2)),
    ('TestTgtD', 'X', 'L_Thigh', 'X', (  0.0,  45.0, 45.0,   0.0,  30.0, 75.0), dict(_M2)),
    ('TestTgtE', 'X', 'L_Thigh', 'X', (  0.0,   0.0,  0.0,   5.0,  33.0,  7.0), dict(_M2)),
    # (b) 同通道抢占：两条抢 R_Dress_HJ_00.X，输出互为相反数
    ('R_Dress_HJ_00', 'X', 'L_Thigh', 'X', (-45.0, 0.0, 45.0, -20.0, 0.0,  20.0), dict(_M0)),  # 前者
    ('R_Dress_HJ_00', 'X', 'L_Thigh', 'X', (-45.0, 0.0, 45.0,  20.0, 0.0, -20.0), dict(_M0)),  # 后者
]

# ---------------------------------------------------------------------------
# Round 14：补两个真实存在但从没测过的缺口。
#   (A) +24 == 1 —— 出货数据 3137 例(13.6%)，唯一没测过的常见模式。
#       用 [09] 的 C 几何，直接跟 Out9(+24=0 精确直线) / Out23(+24=3 精确分段) 对比。
#   (B) 折点落在 [start, end] 区间之外 —— 出货 715 例(3.1%)。
#       模型预测："折点只是 x 轴上一把刀，哪段的定义域落在刀口错误一侧，
#       哪段就永远够不到自己、塌成常数 to_kink"。判据是那段独占的 to 端点从不出现。
#       B2/B3 只差 to_start(-10 vs 80)，若逐帧相同 → to_start 确实完全无效。
_M1 = {'ReadMode': 1, 'CurveMode': 1}
_M3 = {'ReadMode': 1, 'CurveMode': 3}

ROUND14 = [
    # (A) +24 == 1 是什么模式
    ('TestTgtA', 'X', 'L_Thigh', 'X', (-45.0, 0.0, 45.0, -20.0,  0.0, 40.0), dict(_M1)),
    ('TestTgtB', 'X', 'L_Thigh', 'X', (-45.0, 0.0, 45.0, -20.0, 30.0, 40.0), dict(_M1)),  # 只改 to_kink
    # (B1) 折点越过终点：刀口在 20，段二定义域 [0,20] 全在刀口左侧 → 预测恒 to_kink=10，to_end=50 不出现
    ('TestTgtC', 'X', 'L_Thigh', 'X', (-60.0, 20.0,  0.0, -30.0, 10.0, 50.0), dict(_M3)),
    # (B2) 折点落在起点之前：刀口在 -60，段一定义域 [-60,-30] 全在刀口右侧 → 预测 to_start=-10 不出现
    ('TestTgtD', 'X', 'L_Thigh', 'X', (-30.0, -60.0, 30.0, -10.0, 40.0, 20.0), dict(_M3)),
    # (B3) 与 B2 只差 to_start(-10 -> 80)：若与 B2 逐帧相同，to_start 完全无效
    ('TestTgtE', 'X', 'L_Thigh', 'X', (-30.0, -60.0, 30.0,  80.0, 40.0, 20.0), dict(_M3)),
]

NEW_CONSTRAINTS = ROUND14
MULTI_SOURCE_CONSTRAINTS = []


def backup(filepath):
    n = 1
    while True:
        cand = f"{filepath}.bak_{n}"
        if not os.path.exists(cand):
            shutil.copy2(filepath, cand)
            return cand
        n += 1


def main():
    parser = JCNSParser(JCNS_FILE)
    parser.parse()

    template = parser.constraints[0]
    src_template = template['sources'][0]

    for entry in NEW_CONSTRAINTS:
        tgt_bone, tgt_axis, src_bone, src_axis, anchors = entry[:5]
        overrides = entry[5] if len(entry) > 5 else {}

        c = copy.deepcopy(template)
        c['ObjectName'] = tgt_bone
        c['TransformAxis_parent'] = AXIS[tgt_axis]
        c['target_axis'] = AXIS[tgt_axis]
        c['TransformType'] = 1  # Rotation

        s = copy.deepcopy(src_template)
        s['SourceName'] = src_bone
        s['source_axis'] = AXIS[src_axis]
        fs, fk, fe, ts, tk, te = anchors
        s['from_start'], s['from_kink'], s['from_end'] = fs, fk, fe
        s['to_start'], s['to_kink'], s['to_end'] = ts, tk, te

        # Flags 属于约束本体，ReadMode / CurveMode 属于源。
        if 'Flags' in overrides:
            c['Flags'] = overrides['Flags']
        for k in ('ReadMode', 'CurveMode'):
            if k in overrides:
                s[k] = overrides[k]
        c['sources'] = [s]

        parser.constraints.append(c)
        extra = ''
        if overrides:
            extra = '  [' + ' '.join(f"{k}={v}" for k, v in sorted(overrides.items())) + ']'
        print(f"Added: {tgt_bone}.{tgt_axis} <- {src_bone}.{src_axis}  "
              f"from=({fs},{fk},{fe}) to=({ts},{tk},{te}){extra}")

    for entry in MULTI_SOURCE_CONSTRAINTS:
        tgt_bone, tgt_axis, sources = entry[:3]
        overrides = entry[3] if len(entry) > 3 else {}
        c = copy.deepcopy(template)
        c['ObjectName'] = tgt_bone
        c['TransformAxis_parent'] = AXIS[tgt_axis]
        c['target_axis'] = AXIS[tgt_axis]
        c['TransformType'] = 1  # Rotation

        src_list = []
        for src_bone, src_axis, anchors in sources:
            s = copy.deepcopy(src_template)
            s['SourceName'] = src_bone
            s['source_axis'] = AXIS[src_axis]
            fs, fk, fe, ts, tk, te = anchors
            s['from_start'], s['from_kink'], s['from_end'] = fs, fk, fe
            s['to_start'], s['to_kink'], s['to_end'] = ts, tk, te
            for k in ('ReadMode', 'CurveMode'):
                if k in overrides:
                    s[k] = overrides[k]
            src_list.append(s)
            print(f"Added (multi-source): {tgt_bone}.{tgt_axis} <- {src_bone}.{src_axis}  "
                  f"from=({fs},{fk},{fe}) to=({ts},{tk},{te})")
        if 'Flags' in overrides:
            c['Flags'] = overrides['Flags']
        c['sources'] = src_list
        parser.constraints.append(c)

    bak = backup(JCNS_FILE)
    print(f"Backed up original to {bak}")

    writer = JCNSWriter(parser, JCNS_FILE)
    writer.build_lossless()
    print(f"Wrote {len(parser.constraints)} constraints to {JCNS_FILE}")


if __name__ == '__main__':
    main()
