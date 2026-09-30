// jcns ComplexMapping probe: feeds shipped ComplexMapping keys to the engine's own
// via.AnimationCurve and samples evaluate(). Runs once per hot-reload.
using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Runtime.InteropServices;
using REFrameworkNET;
using REFrameworkNET.Attributes;
using REFrameworkNET.Callbacks;

class JcnsCurveProbe {
    const string OUT = @"E:\Program\Steam\steamapps\common\MonsterHunterWilds\reframework\data\";
    static readonly (string name, double[][] keys)[] CURVES = {
        ("fin8", new double[][]{ new double[]{-10.0,-144.0,0.9999999403953552,0.0,10.0,420.9510498046875,8}, new double[]{0.0,0.0,10.0,0.0,10.0,0.0,0}, new double[]{10.0,0.0,10.0,0.0,9.999999046325684,0.0,0} }),
        ("wing", new double[][]{ new double[]{0.0,0.0,0.0,0.0,0.0,0.0,0}, new double[]{0.0,1.0,0.0,0.0,0.0,0.0,0}, new double[]{10.100000381469727,1.0,0.0,0.0,0.0,0.0,0}, new double[]{10.100000381469727,0.0,0.0,0.0,0.0,0.0,0} }),
        ("flower0", new double[][]{ new double[]{-80.0,10.0,1.0,0.0,60.0,0.0,0}, new double[]{-20.0,0.0,60.0,-18.608495712280273,200.0,0.0,0}, new double[]{180.0,0.0,200.0,0.0,200.0,0.0,0} }),
        ("f8_f2", new double[][]{ new double[]{-80.0,50.0,0.9577687382698059,-0.2875395715236664,60.0,-68.18536376953125,8}, new double[]{-20.0,0.0,60.0,-50.0,200.0,0.0,2}, new double[]{180.0,0.0,200.0,0.0,200.0,0.0,0} }),
        ("lin2", new double[][]{ new double[]{-150.0,0.0,1.0,0.0,130.0,150.0,2}, new double[]{-20.0,150.0,130.0,150.0,200.0,0.0,2}, new double[]{180.0,150.0,200.0,0.0,200.0,0.0,0} }),
        ("step5", new double[][]{ new double[]{-150.0,0.0,1.0,0.0,23.737442016601562,0.0,5}, new double[]{-126.26255798339844,-4.028775691986084,23.737442016601562,0.0,30.262557983398438,0.0,5}, new double[]{-96.0,1.3358367681503296,30.262557983398438,0.0,34.0,0.0,5}, new double[]{-62.0,-0.9414693713188171,34.0,0.0,34.0,0.0,5}, new double[]{-28.0,0.784612238407135,34.0,0.0,28.0,0.0,5}, new double[]{0.0,0.0,28.0,0.0,180.0,0.0,5}, new double[]{180.0,0.0,180.0,0.0,180.0,0.0,0} }),
    };

    static readonly StringBuilder Log = new StringBuilder();
    static void L(string s) { API.LogInfo("[jcns_probe] " + s); Log.AppendLine(s); }

    static Method M(TypeDefinition t, string sig) {
        for (var p = t; p != null; p = p.ParentType)
            foreach (var m in p.GetMethods())
                if (m.GetMethodSignature() == sig) return m;
        throw new Exception("method not found: " + t.GetFullName() + "." + sig);
    }
    static Field F(TypeDefinition t, string name) {
        foreach (var f in t.GetFields()) if (f.GetName() == name) return f;
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

    static TypeDefinition KF, AC, CT;
    static Method mSetTime, mSetType, mSetInX, mSetInY, mSetOutX, mSetOutY, mGetTime, mGetType,
                  mGetInX, mGetInY, mGetOutX, mGetOutY, mAppend, mEval, mGetKey, mKeyCount, mClamp, mSetCount, mSetKey, mMinT, mMaxT;
    static string Mode = "set";
    static int Retries = 0, Unstable = 0;
    static readonly List<object> Keep = new List<object>();

    static uint H(double f) { return (uint)(ushort)BitConverter.HalfToInt16Bits((Half)(float)f); }
    // via.KeyFrame raw layout (read back from the engine's own setters):
    //   value f32 | time_type = half(time)<<16 | type | inNormal = half(x)<<16 | half(y) | outNormal likewise
    static IObject MakeKey(double[] k, int type) {
        var vt = KF.CreateValueType();
        Keep.Add(vt);
        var a = vt.GetAddress();
        F(KF, "value").SetDataBoxed(a, (float)k[1], true);
        F(KF, "time_type").SetDataBoxed(a, (H(k[0]) << 16) | (uint)(type & 0xFFFF), true);
        F(KF, "inNormal").SetDataBoxed(a, (H(k[2]) << 16) | H(k[3]), true);
        F(KF, "outNormal").SetDataBoxed(a, (H(k[4]) << 16) | H(k[5]), true);
        float t = Convert.ToSingle(Call(vt, mGetTime));
        if (Math.Abs(t - k[0]) > 0.1) throw new Exception("MakeKey self-check failed: time " + t + " != " + k[0]);
        return vt;
    }
    static float Eval(IObject c, float x) { return Convert.ToSingle(Call(c, mEval, x)); }

    // A curve counts only if every key reads back as written and evaluate() reproduces
    // each key's value at its time, twice.  Native calls with arguments drop them at random.
    static bool Verify(IObject c, double[][] keys, int force, out string why) {
        why = "";
        if (Convert.ToUInt32(Call(c, mKeyCount)) != keys.Length) { why = "count"; return false; }
        for (int i = 0; i < keys.Length; i++) {
            var b = Call(c, mGetKey, (uint)i) as IObject;
            uint tt = Convert.ToUInt32(F(KF, "time_type").GetDataBoxed(b.GetAddress(), true));
            uint want = (H(keys[i][0]) << 16) | (uint)((force < 0 ? (int)keys[i][6] : force) & 0xFFFF);
            uint inn = Convert.ToUInt32(F(KF, "inNormal").GetDataBoxed(b.GetAddress(), true));
            uint outn = Convert.ToUInt32(F(KF, "outNormal").GetDataBoxed(b.GetAddress(), true));
            float v = Convert.ToSingle(F(KF, "value").GetDataBoxed(b.GetAddress(), true));
            if (tt != want || inn != ((H(keys[i][2]) << 16) | H(keys[i][3])) || outn != ((H(keys[i][4]) << 16) | H(keys[i][5])) || v != (float)keys[i][1]) {
                why = "key " + i; return false;
            }
        }
        for (int i = 0; i < keys.Length; i++) {
            float t = (float)(double)(Half)(float)keys[i][0];
            // duplicate times: the value at a step is either side, so only check uniquely-timed keys
            bool dup = (i > 0 && keys[i - 1][0] == keys[i][0]) || (i + 1 < keys.Length && keys[i + 1][0] == keys[i][0]);
            float e1 = Eval(c, t), e2 = Eval(c, t);
            if (e1 != e2) { why = "eval unstable at " + t; return false; }
            if (!dup && Math.Abs(e1 - keys[i][1]) > 1e-4 * Math.Max(1, Math.Abs(keys[i][1]))) { why = "eval(" + t + ")=" + e1 + " != " + keys[i][1]; return false; }
        }
        return true;
    }

    static IObject Build(double[][] keys, int force) {
        string why = "";
        for (int attempt = 0; attempt < 20; attempt++) {
            var c = AC.CreateInstance(0) as IObject;
            Keep.Add(c);
            if (c is ManagedObject mo) mo.Globalize();
            Call(c, mSetCount, (uint)keys.Length);
            for (int i = 0; i < keys.Length; i++) Call(c, mSetKey, (uint)i, MakeKey(keys[i], force < 0 ? (int)keys[i][6] : force));
            if (Verify(c, keys, force, out why)) return c;
            Retries++;
        }
        L("  GAVE UP force=" + force + ": " + why);
        return null;
    }

    static bool s_done = false;

    [PluginEntryPoint]
    public static void Main() { s_done = false; }

    // Run on the game thread: from the entry point, native calls with arguments
    // dropped them ~17% of the time.
    [Callback(typeof(UpdateBehavior), CallbackType.Pre)]
    public static void OnUpdate() {
        if (s_done) return;
        s_done = true;
        L("thread " + Environment.CurrentManagedThreadId);
        try { Run(); } catch (Exception e) { L("ERROR " + e); }
        File.WriteAllText(OUT + "jcns_curve_probe.txt", Log.ToString());
    }

    static void Run() {
        var tdb = TDB.Get();
        KF = tdb.GetType("via.KeyFrame"); AC = tdb.GetType("via.AnimationCurve"); CT = tdb.GetType("via.CurveType");
        mSetTime = M(KF, "SetTime(System.Single)"); mSetType = M(KF, "SetCurveType(via.CurveType)");
        mSetInX = M(KF, "SetInNormalX(System.Single)"); mSetInY = M(KF, "SetInNormalY(System.Single)");
        mSetOutX = M(KF, "SetOutNormalX(System.Single)"); mSetOutY = M(KF, "SetOutNormalY(System.Single)");
        mGetTime = M(KF, "GetTime()"); mGetType = M(KF, "GetCurveType()");
        mGetInX = M(KF, "GetInNormalX()"); mGetInY = M(KF, "GetInNormalY()");
        mGetOutX = M(KF, "GetOutNormalX()"); mGetOutY = M(KF, "GetOutNormalY()");
        mAppend = M(AC, "appendKey(via.KeyFrame)"); mEval = M(AC, "evaluate(System.Single)");
        mGetKey = M(AC, "getKeys(System.UInt32)"); mKeyCount = M(AC, "getKeysCount()"); mClamp = M(AC, "get_EnableClamp()");
        mSetCount = M(AC, "setKeysCount(System.UInt32)"); mSetKey = M(AC, "setKeys(System.UInt32, via.KeyFrame)");
        mMinT = M(AC, "get_MinTime()"); mMaxT = M(AC, "get_MaxTime()");

        var types = new List<(int v, string n)>();
        for (int i = 0; i < 8; i++) {
            var n = EnumName(CT, i);
            L("via.CurveType " + i + " = " + n);
            if (!int.TryParse(n, out int dummy)) types.Add((i, n));
        }
        var ic = tdb.GetType("via.motion.InterpolationCurve");
        for (int i = 0; i < 8; i++) L("via.motion.InterpolationCurve " + i + " = " + EnumName(ic, i));

        var csv = new StringBuilder("curve,variant,x,y,y2,y3\n");
        foreach (var (name, keys) in CURVES) {
            double lo = keys[0][0], hi = keys[keys.Length - 1][0];
            var variants = new List<(string, int)> { ("orig", -1) };
            foreach (var t in types) variants.Add((t.n, t.v));
            foreach (var (vname, force) in variants) {
                var c = Build(keys, force);
                if (c == null) continue;
                {
                    uint n0 = Convert.ToUInt32(Call(c, mKeyCount));
                    var ts = new StringBuilder();
                    for (uint i = 0; i < n0; i++) ts.Append(Call(Call(c, mGetKey, i) as IObject, mGetTime) + " ");
                    L("curve " + name + "/" + vname + " keys=" + n0 + " minT=" + Call(c, mMinT) + " maxT=" + Call(c, mMaxT) + " times: " + ts);
                }
                if (vname == "orig") {
                    uint n = Convert.ToUInt32(Call(c, mKeyCount));
                    for (uint i = 0; i < n; i++) {
                        var kf = Call(c, mGetKey, i) as IObject;
                        L(string.Format("  key {0}: t={1} v={2} type={3} in=({4},{5}) out=({6},{7}) raw={8:X8} {9:X8} {10:X8}",
                            i, Call(kf, mGetTime), F(KF, "value").GetDataBoxed(kf.GetAddress(), true), Call(kf, mGetType),
                            Call(kf, mGetInX), Call(kf, mGetInY), Call(kf, mGetOutX), Call(kf, mGetOutY),
                            F(KF, "time_type").GetDataBoxed(kf.GetAddress(), true),
                            F(KF, "inNormal").GetDataBoxed(kf.GetAddress(), true),
                            F(KF, "outNormal").GetDataBoxed(kf.GetAddress(), true)));
                    }
                }
                const int N = 400;
                for (int s = 0; s <= N; s++) {
                    float x = (float)(lo - 20 + (hi - lo + 40) * s / N);
                    float y1 = Eval(c, x), y2 = Eval(c, x);
                    if (y1 != y2) Unstable++;
                    float y3 = Eval(c, x);
                    csv.AppendFormat("{0},{1},{2:R},{3:R},{4:R},{5:R}\n", name, vname, x, y1, y2, y3);
                }
            }
        }
        File.WriteAllText(OUT + "jcns_curve_probe.csv", csv.ToString());
        L("done, retries=" + Retries + " unstable samples=" + Unstable);
    }
}
