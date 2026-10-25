# -*- coding: utf-8 -*-
import os, re
keys = ("missile","unit","deployable","countermeasure")
for size in ("l","xl"):
    d = os.path.join(r"D:\Games\X4 exout\assets\units", "size_%s"%size, "macros")
    if not os.path.isdir(d): continue
    cnt = {k:0 for k in keys}; total = 0; sample = []
    for fn in os.listdir(d):
        if not (fn.startswith("ship_") and fn.endswith("_macro.xml")): continue
        txt = open(os.path.join(d,fn), encoding="utf-8").read()
        m = re.search(r'<storage [^>]*>', txt)
        if not m: continue
        total += 1
        tag = m.group(0)
        for k in keys:
            if re.search(r'%s="[^"]+"' % k, tag): cnt[k] += 1
        if len(sample) < 6: sample.append((fn, tag))
    print("SIZE", size, " 有 storage 的船数:", total)
    for k in keys: print("  %-12s %d 艘有" % (k, cnt[k]))
    print("  样例:")
    for fn, tag in sample: print("   ", fn, "->", tag)
    print()
