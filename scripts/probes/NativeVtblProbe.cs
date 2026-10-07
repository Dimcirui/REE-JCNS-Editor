// Dumps native method RVAs for via.motion.JointConstraintsLayer / Constraint (entry points for static
// disassembly of the jcns evaluator) and finds a live JointConstraints component.  Runs once per hot-reload.
using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Runtime.InteropServices;
using REFrameworkNET;
using REFrameworkNET.Attributes;
using REFrameworkNET.Callbacks;

class NativeVtblProbe {
    const string OUT = @"E:\Program\Steam\steamapps\common\MonsterHunterWilds\reframework\data\";
    static readonly StringBuilder Log = new StringBuilder();
    static void L(string s) { API.LogInfo("[vtbl_probe] " + s); Log.AppendLine(s); }
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

    static bool s_doneG;
    static ulong Ptr(Method m) {
        try {
            var bx = typeof(Method).GetMethod("GetFunctionPtr").Invoke(m, null);
            return (ulong)(long)(IntPtr)typeof(System.Reflection.Pointer).GetMethod("GetPointerValue", System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance).Invoke(bx, null);
        } catch { return 0; }
    }
    [Callback(typeof(UpdateBehavior), CallbackType.Pre)]
    public static void OnUpdate() {
        if (s_doneG) return;
        s_doneG = true;
        try {
            var tdb = TDB.Get();
            ulong bas = (ulong)(long)System.Diagnostics.Process.GetCurrentProcess().MainModule.BaseAddress;
            var sb = new StringBuilder("type,signature,rva\n");
            foreach (var tn in new[] { "via.motion.JointConstraintsLayer", "via.motion.Constraint", "via.motion.JointConstraints",
                                       "via.motion.JointConstraintsResource", "via.motion.JointConstraintsResourceHolder", "via.motion.SecondaryAnimation" }) {
                var t = tdb.GetType(tn);
                if (t == null) { L("no type " + tn); continue; }
                foreach (var m in t.GetMethods()) {
                    ulong p = Ptr(m);
                    sb.AppendFormat("{0},\"{1}\",{2}\n", tn, m.GetMethodSignature(), p == 0 ? "0" : (p - bas).ToString("X"));
                }
            }
            File.WriteAllText(OUT + "cone_probe_g.csv", sb.ToString());

            // find a JointConstraints component on the player's equipment pieces
            var pm = API.GetManagedSingletonT<app.PlayerManager>();
            var tf = pm.getMasterPlayer().Object.Transform as IObject;
            var child = tf.Call("get_Child") as IObject;
            IObject jc = null; string where = null;
            for (int guard = 0; child != null && guard < 64 && jc == null; guard++) {
                var go = child.Call("get_GameObject") as IObject;
                var comps = go.Call("get_Components") as IObject;
                int n = Convert.ToInt32(comps.Call("get_Length"));
                for (int i = 0; i < n; i++) {
                    var c = comps.Call("GetValue", i) as IObject;
                    if (c != null && c.GetTypeDefinition().GetFullName() == "via.motion.JointConstraints") { jc = c; where = go.Call("get_Name") as string; break; }
                }
                child = child.Call("get_Next") as IObject;
            }
            if (jc == null) { L("no JointConstraints found"); return; }
            L("JointConstraints on " + where + " at 0x" + jc.GetAddress().ToString("X") + " vtbl rva " + ((ulong)Marshal.ReadInt64((IntPtr)(long)jc.GetAddress()) - bas).ToString("X"));
            var layer = jc.Call("get_Layer") as IObject;
            if (layer == null) { L("get_Layer null"); return; }
            ulong la = layer.GetAddress();
            ulong vt = (ulong)Marshal.ReadInt64((IntPtr)(long)la);
            L("layer type " + layer.GetTypeDefinition().GetFullName() + " at 0x" + la.ToString("X") + " vtbl rva " + (vt - bas).ToString("X"));
        } catch (Exception e) { L("ERROR " + e); }
        finally { File.WriteAllText(OUT + "cone_probe.txt", Log.ToString()); }
    }
}
