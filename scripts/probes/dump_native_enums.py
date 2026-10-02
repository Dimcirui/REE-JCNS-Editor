"""Dump native enums (names and values) from an RE Engine exe, statically.

The engine registers each native enum in code: lea rcx, <type name>; mov edx, <count>;
call <register>; then per member: mov edx, i; call; lea rdx, <name>; mov r8d, <value>;
call.  This finds the lea rcx xrefs to matching type-name strings and reads the members
back out of the disassembly.  Nothing touches the running game.

    python dump_native_enums.py <exe> <out.json> [type-name regex]

The register function's address is found as the commonest call target right after
those lea rcx instructions.  Needs pefile, capstone, numpy.
"""
import pefile, re, capstone, numpy as np, json, sys, collections
EXE=sys.argv[1]
pe=pefile.PE(EXE, fast_load=True)
data=open(EXE,'rb').read()
secs=[(s.Name.rstrip(b'\0').decode(),s.VirtualAddress,s.Misc_VirtualSize,s.PointerToRawData,s.SizeOfRawData) for s in pe.sections]
def rva2off(r):
    for n,va,vs,po,ps in secs:
        if va<=r<va+ps: return po+r-va
def off2rva(o):
    for n,va,vs,po,ps in secs:
        if po<=o<po+ps: return va+o-po
def cstr(r):
    o=rva2off(r)
    if o is None: return None
    e=data.find(b'\0',o,o+300); s=data[o:e]
    return s.decode('ascii') if e>o and all(32<=c<127 for c in s) else None
md=capstone.Cs(capstone.CS_ARCH_X86,capstone.CS_MODE_64)
# all enum type-name strings we care about
default = r'via\.motion\.(JointExMultiRemapValue|JointConstraintsResource|detail\.JointDriver|exprgraph|JointRemapValue)'
pat=re.compile(rb'(' + (sys.argv[3] if len(sys.argv) > 3 else default).encode() + rb'[\x20-\x7e]*)\x00')
names={}
for m in pat.finditer(data):
    names[off2rva(m.start())]=m.group(1).decode()
print(len(names),'type-name strings',file=sys.stderr)
# xrefs: vectorized over .data (code lives there)
n,va,vs,po,ps=[s for s in secs if s[0]=='.data'][0]
targets=np.array(sorted(names))
xrefs=[]
CH=1<<24
for c in range(0,ps,CH):
    seg=np.frombuffer(data[po+c:po+min(ps,c+CH+3)],dtype=np.uint8).astype(np.int64)
    d=seg[:-3]|(seg[1:-2]<<8)|(seg[2:-1]<<16)|(seg[3:]<<24)
    d=np.where(d>=2**31,d-2**32,d)
    t=va+c+np.arange(len(d))+4+d
    hit=np.nonzero(np.isin(t,targets))[0]
    for i in hit:
        # require lea rcx (48 8d 0d)
        if data[po+c+i-3:po+c+i]==b'\x48\x8d\x0d':
            xrefs.append((va+c+i-3,int(t[i])))
print(len(xrefs),'lea rcx xrefs',file=sys.stderr)
calls=collections.Counter()
for addr,tr in xrefs:
    o=rva2off(addr)
    for x in list(md.disasm(data[o:o+40],addr))[1:6]:
        if x.mnemonic=='call': calls[x.op_str]+=1; break
REG=int(calls.most_common(1)[0][0],16)
print('register fn',hex(REG),file=sys.stderr)
out={}
def rip(ins):
    m=re.search(r'\[rip ([+-]) 0x([0-9a-f]+)\]',ins.op_str)
    return ins.address+ins.size+int(m.group(2),16)*(1 if m.group(1)=='+' else -1) if m else None
for addr,tr in xrefs:
    tname=names[tr]
    o=rva2off(addr)
    ins=list(md.disasm(data[o:o+6000],addr))
    if len(ins)<5: continue
    # expect: lea rcx; mov edx,N; ...; call REG
    cnt=None; ok=False
    for j,x in enumerate(ins[1:6],1):
        if x.mnemonic=='mov' and x.op_str.startswith('edx,'):
            try: cnt=int(x.op_str.split(',')[1],0)
            except: pass
        if x.mnemonic=='call':
            ok = x.op_str==hex(REG); k=j; break
    if not ok: continue
    vals=[]; r8=None; rdx=None
    for x in ins[k+1:]:
        if x.mnemonic=='lea' and x.op_str.startswith('rdx,'):
            rdx=cstr(rip(x))
        elif x.mnemonic=='mov' and x.op_str.startswith('r8d,'):
            r8=int(x.op_str.split(',')[1],0)
        elif x.mnemonic=='mov' and x.op_str.startswith('r8,'):
            try: r8=int(x.op_str.split(',')[1],0)
            except: r8=x.op_str
        elif x.mnemonic=='xor' and x.op_str in ('r8d, r8d','r8, r8'):
            r8=0
        elif x.mnemonic=='call' and x.op_str!=hex(REG) and rdx is not None:
            vals.append((rdx,r8)); rdx=None; r8=None
            if cnt is not None and len(vals)>=cnt: break
        elif x.mnemonic=='call' and x.op_str==hex(REG): break
        elif x.mnemonic=='lea' and x.op_str.startswith('rcx,') and cstr(rip(x)) and '.' in (cstr(rip(x)) or ''): break
    out[tname]={'count':cnt,'values':vals}
json.dump(out,open(sys.argv[2],'w'),indent=1)
for k in sorted(out): print(k, out[k]['count'], out[k]['values'])
