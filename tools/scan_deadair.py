# -*- coding: utf-8 -*-
import os, re
KEYS = ("missile","unit","deployable","countermeasure")
mods = [os.path.join(r"D:\Games\X4 exout\extensions", n)
        for n in os.listdir(r"D:\Games\X4 exout\extensions")
        if n.startswith("deadairfaction")]
for m in mods:
    if not os.path.isdir(m): continue
    for size in ("l","xl"):
        d = os.path.join(m,"assets","units","size_%s"%size,"macros")
        if not os.path.isdir(d): continue
        cnt={k:0 for k in KEYS}; total=0; samples=[]
        for fn in os.listdir(d):
            if not (fn.startswith("ship_") and fn.endswith("_macro.xml")): continue
            txt=open(os.path.join(d,fn),encoding="utf-8").read()
            mt=re.search(r'<storage [^>]*>', txt)
            if not mt: continue
            total+=1; tag=mt.group(0)
            for k in KEYS:
                if re.search(r'%s="[^"]+"'%k, tag): cnt[k]+=1
            if len(samples)<2: samples.append((fn,tag))
        print("%-22s %s 有storage=%d  missile=%d unit=%d deploy=%d ctr=%d" % (
            os.path.basename(m), size, total, cnt["missile"], cnt["unit"], cnt["deployable"], cnt["countermeasure"]))
print()
# 官方 DLC
dlcs=[os.path.join(r"D:\Games\X4 exout\extensions",n) for n in os.listdir(r"D:\Games\X4 exout\extensions")
      if n.startswith("ego_dlc_")]
for m in dlcs:
    if not os.path.isdir(m): continue
    for size in ("l","xl"):
        d=os.path.join(m,"assets","units","size_%s"%size,"macros")
        if not os.path.isdir(d): continue
        cnt={k:0 for k in KEYS}; total=0
        for fn in os.listdir(d):
            if not (fn.startswith("ship_") and fn.endswith("_macro.xml")): continue
            txt=open(os.path.join(d,fn),encoding="utf-8").read()
            mt=re.search(r'<storage [^>]*>', txt)
            if not mt: continue
            total+=1; tag=mt.group(0)
            for k in KEYS:
                if re.search(r'%s="[^"]+"'%k, tag): cnt[k]+=1
        print("%-22s %s 有storage=%d missile=%d unit=%d deploy=%d ctr=%d" % (
            os.path.basename(m), size, total, cnt["missile"], cnt["unit"], cnt["deployable"], cnt["countermeasure"]))
