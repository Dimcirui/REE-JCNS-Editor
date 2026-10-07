// ConeDriver probe: builds via.motion.JointRemapValue.RemapValueItem / InputJoint objects by hand,
// calls RemapValueItem.Update(Transform, bool) against the player skeleton and logs what the
// engine computes.  Runs once per hot-reload.
using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Runtime.InteropServices;
using REFrameworkNET;
using REFrameworkNET.Attributes;
using REFrameworkNET.Callbacks;

class ConeRemapProbe {
    const string OUT = @"E:\Program\Steam\steamapps\common\MonsterHunterWilds\reframework\data\";
    static readonly StringBuilder Log = new StringBuilder();
    static void L(string s) { API.LogInfo("[cone_probe] " + s); Log.AppendLine(s); }
    static bool s_done;

    static Method M(TypeDefinition t, string sig) {
        for (var p = t; p != null; p = p.ParentType)
            foreach (var m in p.GetMethods())
                if (m.GetMethodSignature() == sig) return m;
        throw new Exception("method not found: " + t.GetFullName() + "." + sig);
    }
    static Field F(TypeDefinition t, string name) {
        for (var p = t; p != null; p = p.ParentType)
            foreach (var f in p.GetFields()) if (f.GetName() == name) return f;
        throw new Exception("field not found: " + name);
    }
    static object Call(IObject o, Method m, params object[] a) {
        object r = null; o.HandleInvokeMember_Internal(m, a.Length == 0 ? null : a, ref r); return r;
    }
    static string EnumName(TypeDefinition et, long v) {
        var enumTd = TDB.Get().FindType("System.Enum");
        var bm = enumTd.FindMethod("InternalBoxEnum") ?? enumTd.FindMethod("boxEnum");
        var ret = bm.Invoke(null, new object[] { et.GetRuntimeType(), v });
        if (ret.Ptr == 0) return "?";
        var o = ManagedObject.ToManagedObject(ret.Ptr) as IObject;
        return o.Call("ToString()") as string;
    }
    static void DumpEnum(string type, int n) {
        var td = TDB.Get().GetType(type);
        var sb = new StringBuilder(type + ":");
        for (int i = 0; i < n; i++) sb.Append(" " + i + "=" + EnumName(td, i));
        L(sb.ToString());
    }

    // Raw primitive access inside objects this probe allocated itself (offsets from get_type).
    static void WF(IObject o, int off, float v) { Marshal.WriteInt32((IntPtr)(long)(o.GetAddress() + (ulong)off), BitConverter.SingleToInt32Bits(v)); }
    static float RF(IObject o, int off) { return BitConverter.Int32BitsToSingle(Marshal.ReadInt32((IntPtr)(long)(o.GetAddress() + (ulong)off))); }
    static void WI(IObject o, int off, int v) { Marshal.WriteInt32((IntPtr)(long)(o.GetAddress() + (ulong)off), v); }
    static int RI(IObject o, int off) { return Marshal.ReadInt32((IntPtr)(long)(o.GetAddress() + (ulong)off)); }
    static void WB(IObject o, int off, bool v) { Marshal.WriteByte((IntPtr)(long)(o.GetAddress() + (ulong)off), (byte)(v ? 1 : 0)); }

    static IObject New(string type) {
        var td = TDB.Get().GetType(type);
        var o = td.CreateInstance(0);
        if (o == null) throw new Exception("CreateInstance failed: " + type);
        try { Call(o, M(td, ".ctor()")); } catch (Exception e) { L("  no .ctor() for " + type + ": " + e.Message); }
        if (o is ManagedObject mo) mo.Globalize();
        return o;
    }

    // InputJoint offsets
    const int IJ_Offset = 0x10, IJ_InputValue = 0x20, IJ_InRotOrder = 0x38, IJ_InAxis = 0x3C, IJ_Input = 0x40,
              IJ_HalfAngle = 0x44, IJ_InMin = 0x48, IJ_InMid = 0x4C, IJ_InMax = 0x50, IJ_OutMin = 0x54,
              IJ_OutMid = 0x58, IJ_OutMax = 0x5C, IJ_OutputValue = 0x60, IJ_BasePose = 0x64, IJ_MidPoint = 0x65;
    // RemapValueItem offsets
    const int RI_TRS = 0x20, RI_RotOrder = 0x24, RI_Axis = 0x28, RI_Mode = 0x2C, RI_OutputValue = 0x30, RI_BasePose = 0x34;

    static TypeDefinition TIJ, TRI;
    static Method mUpdate, mCalc;

    static IObject s_item, s_ij, s_tf;
    static string Q4(IObject q) {
        var t = q.GetTypeDefinition();
        return F(t, "x").GetDataBoxed(q.GetAddress(), true) + ";" + F(t, "y").GetDataBoxed(q.GetAddress(), true) + ";" +
               F(t, "z").GetDataBoxed(q.GetAddress(), true) + ";" + F(t, "w").GetDataBoxed(q.GetAddress(), true);
    }
    static string V3(IObject v) {
        var t = v.GetTypeDefinition();
        return F(t, "x").GetDataBoxed(v.GetAddress(), true) + ";" + F(t, "y").GetDataBoxed(v.GetAddress(), true) + ";" + F(t, "z").GetDataBoxed(v.GetAddress(), true);
    }
    static float Cone(float half, float[] off, int order, bool bp) {
        WI(s_ij, IJ_Input, 3); WI(s_ij, IJ_InAxis, 0); WF(s_ij, IJ_HalfAngle, half); WI(s_ij, IJ_InRotOrder, order);
        WF(s_ij, IJ_Offset, off[0]); WF(s_ij, IJ_Offset + 4, off[1]); WF(s_ij, IJ_Offset + 8, off[2]);
        WB(s_ij, IJ_BasePose, bp); WB(s_ij, IJ_MidPoint, false);
        WF(s_ij, IJ_InputValue, float.NaN);
        Call(s_item, mUpdate, s_tf, false);
        return RF(s_ij, IJ_InputValue);
    }
    static bool s_done2;
    [Callback(typeof(UpdateBehavior), CallbackType.Pre)]
    public static void OnUpdate() {
        if (s_done2) return;
        s_done2 = true;
        try {
            var tdb = TDB.Get();
            TIJ = tdb.GetType("via.motion.JointRemapValue.InputJoint");
            TRI = tdb.GetType("via.motion.JointRemapValue.RemapValueItem");
            mUpdate = M(TRI, "Update(via.Transform, System.Boolean)");
            var pm = API.GetManagedSingletonT<app.PlayerManager>();
            s_tf = pm.getMasterPlayer().Object.Transform as IObject;
            s_item = New("via.motion.JointRemapValue.RemapValueItem");
            s_ij = New("via.motion.JointRemapValue.InputJoint");
            var list = New("System.Collections.Generic.List`1<via.motion.JointRemapValue.InputJoint>");
            list.Call("Add", s_ij);
            F(TRI, "InJoints").SetDataBoxed(s_item.GetAddress(), list, false);
            F(TRI, "OutJointName").SetDataBoxed(s_item.GetAddress(), VM.CreateString("__cone_probe_none__"), false);
            WF(s_ij, IJ_InMin, 0); WF(s_ij, IJ_InMid, 0.5f); WF(s_ij, IJ_InMax, 1);
            WF(s_ij, IJ_OutMin, 0); WF(s_ij, IJ_OutMid, 0.5f); WF(s_ij, IJ_OutMax, 1);

            var joints = s_tf.Call("get_Joints") as IObject;
            int n = Convert.ToInt32(joints.Call("get_Length"));
            var byName = new Dictionary<string, IObject>();
            for (int i = 0; i < n; i++) { var j = joints.Call("GetValue", i) as IObject; byName[j.Call("get_Name") as string] = j; }

            var offs = new float[][] { new float[]{0,0,0}, new float[]{30,0,0}, new float[]{0,30,0}, new float[]{0,0,30}, new float[]{20,-40,60}, new float[]{-50,25,10} };
            var sb = new StringBuilder("joint,J_lpos,J_blpos,P_lq,P_blq,P_wq,G_wq,half,ox,oy,oz,order,bp,v\n");
            foreach (var nm in new[] { "L_Thigh", "R_Thigh", "L_Knee", "Head", "L_Hand", "L_UpperArm", "L_Forearm", "Spine_1", "Neck_1", "L_IndexF2" }) {
                if (!byName.ContainsKey(nm)) { L("missing " + nm); continue; }
                var J = byName[nm]; var P = J.Call("get_Parent") as IObject; var G = P.Call("get_Parent") as IObject;
                F(TIJ, "JointName").SetDataBoxed(s_ij.GetAddress(), VM.CreateString(nm), false);
                string pre = string.Join(",", nm, V3(J.Call("get_LocalPosition") as IObject), V3(J.Call("get_BaseLocalPosition") as IObject),
                    Q4(P.Call("get_LocalRotation") as IObject), Q4(P.Call("get_BaseLocalRotation") as IObject), Q4(P.Call("get_Rotation") as IObject),
                    G == null ? "0;0;0;1" : Q4(G.Call("get_Rotation") as IObject));
                foreach (var h in new float[] { 180, 60 })
                    foreach (var o in offs)
                        for (int ord = 0; ord < 6; ord++) {
                            if (ord > 0 && o[0] * o[1] + o[1] * o[2] + o[0] * o[2] == 0) continue;
                            foreach (bool bp in new[] { false, true })
                                sb.AppendFormat("{0},{1},{2},{3},{4},{5},{6},{7},{8:R}\n", pre, h, o[0], o[1], o[2], ord, bp ? 1 : 0, "", Cone(h, o, ord, bp)).Replace(",,", ",");
                        }
            }
            File.WriteAllText(OUT + "cone_probe_f.csv", sb.ToString());
            L("done");
        } catch (Exception e) { L("ERROR " + e); }
        File.WriteAllText(OUT + "cone_probe.txt", Log.ToString());
    }
}
