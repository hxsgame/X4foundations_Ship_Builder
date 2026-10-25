# -*- coding: utf-8 -*-
import os, re
r = r"D:\Games\X4 exout\assets\units"
s = set()
for sz in os.listdir(r):
    d = os.path.join(r, sz, "macros")
    if not os.path.isdir(d): continue
    for fn in os.listdir(d):
        if fn.startswith("ship_") and fn.endswith("_macro.xml"):
            m = re.search(r'icon="([^"]+)"', open(os.path.join(d, fn), encoding="utf-8").read())
            if m: s.add(m.group(1))
print("icon 全集数:", len(s))
print(sorted(s))
