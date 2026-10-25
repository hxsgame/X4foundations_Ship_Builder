# -*- coding: utf-8 -*-
import os, re
for name, root in (("VAN", r"D:\Games\X4 exout\assets\units"),
                   ("EVE", r"D:\Games\X4 exout\extensions\UP7_Real_EVE_Ships\assets\units")):
    p = set(); thr = set(); sec = set()
    for sz in ("l", "xl"):
        d = os.path.join(root, "size_%s" % sz, "macros")
        if not os.path.isdir(d): continue
        for fn in os.listdir(d):
            if not (fn.startswith("ship_") and fn.endswith("_macro.xml")): continue
            txt = open(os.path.join(d, fn), encoding="utf-8").read()
            m = re.search(r'<purpose primary="([^"]+)"', txt)
            if m: p.add(m.group(1))
            m = re.search(r'<thruster tags="([^"]+)"', txt)
            if m: thr.add(m.group(1))
            m = re.search(r'<secrecy level="([^"]+)"', txt)
            if m: sec.add(m.group(1))
    print(name, "purpose:", sorted(p), " thruster:", sorted(thr), " secrecy:", sorted(sec))
