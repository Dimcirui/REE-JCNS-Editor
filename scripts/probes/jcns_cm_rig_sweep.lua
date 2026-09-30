-- jcns_cm_rig_sweep.lua  (2026-09-29 轮：ComplexMapping flag + 装备骨当源)
-- 复制自 REE-JCNS-Research/scripts/jcns_test_rig_sweep.lua，只改了说明、文件名和骨头列表。
-- 注意：旧说明里"源必须在本体骨架上"已撤回待实测，本轮 [13]-[15] 就是测它的。
--
-- xaihi_constraint.jcns.102 当前 16 条（由 RE-JCNS-Editor/scripts/probes/build_cm_rig.py 生成）：
--   [00]-[07] 原版裙骨约束
--   [08] A <- L_Thigh.X 恒等（输入基准）   [09] B CM flag1   [10] C CM flag2
--   [11] D CM flag0 平切线                 [12] E CM flag5 平切线
--   [13] F <- L_Dress_HJ_00.X   [14] G <- hair_base_L_a_03_jnt_ctrl.X   [15] H <- TestTgtA.X
--   第二轮：[16] I / [17] J / [18] K = 平切线 flag 1/2/8；A-D、I-K 刷了 0.1 权重，E-H 没刷
--   另写 jcns_cm_rig_skel.csv：0012 全骨架每根骨头的局部四元数
--   第三轮（build_map_rig.py）：[08]-[18] A..K.X = L_Thigh.X * k/12，[19] A.Y*-0.3 [20] B.Z*-0.6 [21] C.Y*-0.9
--
--   第 12 轮（build_sections_rig.py）：Aim / RotExpression / Skin；另写 jcns_cm_rig_world.csv（世界坐标）
--
-- 用法：放进 reframework/autorun。按 F8 开始记录，跑动、转向、蹲起、抬腿，
-- 让 L_Thigh 大范围摆动，二三十秒即可；按 F9 停止。输出 reframework/data/jcns_cm_rig_sweep.csv
-- 读的是 getOutputUserValue(i)，i = jcns 条目顺序。

local recording = false
local file_handle = nil
local frame_count = 0
local record_file_name = "jcns_cm_rig_sweep.csv"
local status_msg = "按 F8 开始记录"
local MAX_FRAMES = 5400 -- ~90 秒上限

local EQUIP_NAME = "ch03_017_0012"

-- 想额外记录姿态的骨头（源骨 + 目标骨），仅作旁证，主信号是 Out*
local SRC_BONES = { "L_Thigh", "R_Thigh" }
local TGT_BONES = {
    "TestTgtA", "TestTgtB", "TestTgtC", "TestTgtD",
    "TestTgtE", "TestTgtF", "TestTgtG", "TestTgtH",
    "TestTgtI", "TestTgtJ", "TestTgtK",
    "L_Dress_HJ_00", "hair_base_L_a_03_jnt_ctrl",
}

local joints = {}
local jc_layer = nil
local output_count = 0

-- 【重要，Round 9 实测】getOutputUserValue(i) 的索引空间 = **.jcns 里的约束条目顺序**
-- （本文件 17 条），而 get_OutputTargetCount()/getOutputTargetHashTbl(i) 的索引空间
-- = **唯一目标骨**（13 个）。两者不是一套索引！所以这里不能用 OutputTargetCount 当
-- 上界，也不能拿哈希表给列命名——一律读到 OUT_SCAN_MAX，列名只用序号，
-- 谁是谁回头按曲线拟合反推。
local OUT_SCAN_MAX = 80

-- 第二轮：另记 0012 整副骨架每根骨头的 LocalEulerAngle.X，找写错位的输出落到了哪根骨头上
local skel_file_name = "jcns_cm_rig_skel.csv"
local skel_handle = nil
local all_joints = {}
-- Round 10: parent-relative translation (metres) and scale, alongside rotations.
-- Missing getters stay NaN; they must never masquerade as a zero/unit pose.
local trs_handle = nil
local trs_file_name = "jcns_cm_rig_trs.csv"
local trs_joints = {}
-- Round 12: world position / rotation, for Aim / Skin / RotExpression targets and their
-- sources.  "b." = the body's joint (what find_joint_anywhere returns), "e." = the
-- equipment piece's own joint of that name; a getter that is missing gives NaN.
local world_handle = nil
local world_file_name = "jcns_cm_rig_world.csv"
local world_joints = {}
local root_transform = nil
local WORLD_BODY = { "L_Thigh", "R_Thigh", "L_Hand", "R_Hand", "Head" }
local WORLD_EQUIP = { "Ear_SCL", "L_Thigh", "L_Hand", "R_Hand", "Head" }

local function try(fn, default)
    local ok, v = pcall(fn)
    if ok then return v end
    return default
end

local function as_number(v)
    if v == nil then return nil end
    if type(v) == "number" then return v end
    local ok, s = pcall(function() return v:call("ToString()") end)
    if ok and s then return tonumber(s) end
    return nil
end

local function get_GameObjectComponent(go, type_name)
    return go and go:call("getComponent(System.Type)", sdk.typeof(type_name))
end

local function find_joint_anywhere(root_tr, name)
    local j = root_tr:call("getJointByName", name)
    if j then return j end
    local child = root_tr:call("get_Child")
    while child do
        j = child:call("getJointByName", name)
        if j then return j end
        child = child:call("get_Next")
    end
    return nil
end

local function resolve()
    local pm = sdk.get_managed_singleton("app.PlayerManager")
    if not pm then status_msg = "没有 PlayerManager"; return false end
    local mp = pm:call("getMasterPlayer")
    if not mp then status_msg = "没有 MasterPlayer"; return false end
    local obj = mp:call("get_Object")
    if not obj then status_msg = "没有 Object"; return false end
    local root_tr = obj:call("get_Transform")
    if not root_tr then status_msg = "没有 Transform"; return false end
    root_transform = root_tr

    joints = {}
    for _, n in ipairs(SRC_BONES) do joints[n] = find_joint_anywhere(root_tr, n) end
    for _, n in ipairs(TGT_BONES) do joints[n] = find_joint_anywhere(root_tr, n) end
    if not joints["L_Thigh"] then status_msg = "找不到 L_Thigh"; return false end

    -- 定位装备件上的 JointConstraints layer，并建立 骨骼哈希 -> 名字 的映射
    jc_layer = nil
    local hash2name = {}
    local child = root_tr:call("get_Child")
    while child do
        local cgo = child:call("get_GameObject")
        local nm = cgo and try(function() return cgo:call("get_Name()") end, nil)
        if nm == EQUIP_NAME then
            local arr = try(function() return child:call("get_Joints") end, nil)
            if arr then
                local n = try(function() return arr:get_size() end, 0) or 0
                all_joints = {}
                for i = 0, n - 1 do
                    local j = try(function() return arr:get_element(i) end, nil)
                    if j then
                        table.insert(all_joints, { name = try(function() return j:call("get_Name") end, "?") or "?", joint = j })
                        local jn = try(function() return j:call("get_Name") end, nil)
                        local jh = as_number(try(function() return j:call("get_NameHash") end, nil))
                        if jn and jh then hash2name[jh & 0xFFFFFFFF] = jn end
                    end
                end
            end
            local jc = get_GameObjectComponent(cgo, "via.motion.JointConstraints")
            if jc then
                jc_layer = try(function() return jc:call("getLayer", 0) end, nil)
                if jc_layer then
                    output_count = try(function() return jc_layer:call("get_OutputTargetCount") end, 0) or 0
                end
            end
            break
        end
        child = child:call("get_Next")
    end
    if not jc_layer then status_msg = "找不到 " .. EQUIP_NAME .. " 的 JointConstraints layer"; return false end

    status_msg = string.format("就位：OutputTargetCount=%d，扫描 %d 个输出槽，全骨架 %d 根",
        output_count, OUT_SCAN_MAX, #all_joints)
    return true
end

local function start_recording()
    if recording then return end
    if not resolve() then return end
    file_handle = io.open(record_file_name, "w")
    if not file_handle then status_msg = "无法创建 " .. record_file_name; return end

    local header = "Frame"
    for _, n in ipairs(SRC_BONES) do
        header = header .. string.format(",%s_qx,%s_qy,%s_qz,%s_qw,%s_EulX,%s_EulY,%s_EulZ",
            n, n, n, n, n, n, n)
    end
    for i = 0, OUT_SCAN_MAX - 1 do
        header = header .. string.format(",Out%d", i)
    end
    for _, n in ipairs(TGT_BONES) do
        header = header .. string.format(",%s_EulX", n)
    end
    file_handle:write(header .. "\n")

    skel_handle = io.open(skel_file_name, "w")
    if skel_handle then
        local names = {}
        for _, e in ipairs(all_joints) do
            for _, c in ipairs({ "qx", "qy", "qz", "qw" }) do table.insert(names, e.name .. "_" .. c) end
        end
        skel_handle:write("Frame," .. table.concat(names, ",") .. "\n")
    end

    trs_handle = io.open(trs_file_name, "w")
    if not trs_handle then
        if file_handle then file_handle:close(); file_handle = nil end
        if skel_handle then skel_handle:close(); skel_handle = nil end
        status_msg = "无法创建 " .. trs_file_name
        return
    end
    trs_joints = {}
    local trs_names = { "Frame" }
    for _, e in ipairs(all_joints) do
        if string.match(e.name, "^TestTgt[A-K]$") then
            table.insert(trs_joints, e)
            for _, c in ipairs({ "px", "py", "pz", "sx", "sy", "sz" }) do
                table.insert(trs_names, e.name .. "_" .. c)
            end
        end
    end
    trs_handle:write(table.concat(trs_names, ",") .. "\n")

    world_handle = io.open(world_file_name, "w")
    if not world_handle then status_msg = "无法创建 " .. world_file_name; return end
    world_joints = {}
    local by_name = {}
    for _, e in ipairs(all_joints) do by_name[e.name] = e.joint end
    for _, n in ipairs(WORLD_BODY) do
        local bj = joints[n] or find_joint_anywhere(root_transform, n)
        if bj then table.insert(world_joints, { name = "b." .. n, joint = bj }) end
    end
    for _, n in ipairs(WORLD_EQUIP) do
        if by_name[n] then table.insert(world_joints, { name = "e." .. n, joint = by_name[n] }) end
    end
    for _, e in ipairs(all_joints) do
        if string.match(e.name, "^TestTgt[A-K]$") then
            table.insert(world_joints, { name = "e." .. e.name, joint = e.joint })
        end
    end
    local wnames = { "Frame" }
    for _, e in ipairs(world_joints) do
        for _, c in ipairs({ "px", "py", "pz", "qx", "qy", "qz", "qw" }) do
            table.insert(wnames, e.name .. "_" .. c)
        end
    end
    world_handle:write(table.concat(wnames, ",") .. "\n")
    local probe = world_joints[#world_joints]
    local wp = probe and try(function() return probe.joint:call("get_Position") end, nil)
    local wq = probe and try(function() return probe.joint:call("get_Rotation") end, nil)
    recording = true
    frame_count = 0
    status_msg = string.format("记录中…（世界坐标 %d 根骨，get_Position=%s get_Rotation=%s）",
        #world_joints, tostring(wp ~= nil), tostring(wq ~= nil))
end

local function stop_recording()
    if not recording then return end
    recording = false
    if file_handle then file_handle:close(); file_handle = nil end
    if skel_handle then skel_handle:close(); skel_handle = nil end
    if trs_handle then trs_handle:close(); trs_handle = nil end
    if world_handle then world_handle:close(); world_handle = nil end
    status_msg = string.format("完成，%d 帧 → %s", frame_count, record_file_name)
end

re.on_draw_ui(function()
    if imgui.tree_node("JCNS CM 测试台记录器") then
        imgui.text("状态: " .. status_msg)
        if recording then imgui.text("已记录帧数: " .. frame_count) end
        if not recording then
            if imgui.button("开始记录 (或按 F8)") then start_recording() end
        else
            if imgui.button("停止 (或按 F9)") then stop_recording() end
        end
        imgui.tree_pop()
    end
end)

-- 【读取时机，Round 10】
-- 装备件上的 JointConstraints 是 UpdateTiming=1，在 UpdateMotion **之后**才应用，
-- 所以在 UpdateMotion 里读目标骨永远读到应用前的绑定姿势(恒 0)——整个调查早期
-- "目标骨零响应"的假象就是这么来的。改到 re.on_frame（一帧的最后、渲染时触发）读，
-- 这样才能看到约束真正写进骨头的结果，才能判定"同通道多条约束谁胜出"。
re.on_frame(function()
    pcall(function()
        if reframework:is_key_down(119) and not recording then
            start_recording()
        elseif reframework:is_key_down(120) and recording then
            stop_recording()
        end
    end)

    if not recording then return end

    local row = tostring(frame_count)

    for _, n in ipairs(SRC_BONES) do
        local j = joints[n]
        local q = j and try(function() return j:call("get_LocalRotation") end, nil)
        local e = j and try(function() return j:call("get_LocalEulerAngle") end, nil)
        if q and e then
            row = row .. string.format(",%.6f,%.6f,%.6f,%.6f,%.4f,%.4f,%.4f",
                q.x, q.y, q.z, q.w,
                e.x * 180.0 / math.pi, e.y * 180.0 / math.pi, e.z * 180.0 / math.pi)
        else
            row = row .. ",0,0,0,1,0,0,0"
        end
    end

    for i = 0, OUT_SCAN_MAX - 1 do
        local v = as_number(try(function() return jc_layer:call("getOutputUserValue", i) end, nil)) or 0
        row = row .. string.format(",%.6f", v)
    end

    for _, n in ipairs(TGT_BONES) do
        local j = joints[n]
        local e = j and try(function() return j:call("get_LocalEulerAngle") end, nil)
        row = row .. string.format(",%.4f", e and (e.x * 180.0 / math.pi) or 0)
    end

    file_handle:write(row .. "\n")
    if skel_handle then
        local vals = { tostring(frame_count) }
        for _, e in ipairs(all_joints) do
            local q = try(function() return e.joint:call("get_LocalRotation") end, nil)
            table.insert(vals, q and string.format("%.5f,%.5f,%.5f,%.5f", q.x, q.y, q.z, q.w) or "nan,nan,nan,nan")
        end
        skel_handle:write(table.concat(vals, ",") .. "\n")
    end
    if trs_handle then
        local vals = { tostring(frame_count) }
        for _, e in ipairs(trs_joints) do
            local p = try(function() return e.joint:call("get_LocalPosition") end, nil)
            local s = try(function() return e.joint:call("get_LocalScale") end, nil)
            table.insert(vals, p and string.format("%.7f,%.7f,%.7f", p.x, p.y, p.z) or "nan,nan,nan")
            table.insert(vals, s and string.format("%.7f,%.7f,%.7f", s.x, s.y, s.z) or "nan,nan,nan")
        end
        trs_handle:write(table.concat(vals, ",") .. "\n")
    end
    if world_handle then
        local vals = { tostring(frame_count) }
        for _, e in ipairs(world_joints) do
            local p = try(function() return e.joint:call("get_Position") end, nil)
            local q = try(function() return e.joint:call("get_Rotation") end, nil)
            table.insert(vals, p and string.format("%.6f,%.6f,%.6f", p.x, p.y, p.z) or "nan,nan,nan")
            table.insert(vals, q and string.format("%.6f,%.6f,%.6f,%.6f", q.x, q.y, q.z, q.w) or "nan,nan,nan,nan")
        end
        world_handle:write(table.concat(vals, ",") .. "\n")
    end
    frame_count = frame_count + 1
    if frame_count >= MAX_FRAMES then stop_recording() end
end)
