# -*- coding: utf-8 -*-
import os, re
VAN = r"D:\Games\X4 exout\assets\units"
EVE = r"D:\Games\X4 exout\extensions\UP7_Real_EVE_Ships\assets\units"

def collect(root, sizes=("l","xl")):
    en = {"type":set(), "icon":set(), "makerrace":set()}
    n = 0
    for size in sizes:
        d = os.path.join(root,"size_%s"%size,"macros")
        if not os.path.isdir(d): continue
        for fn in os.listdir(d):
            if not (fn.startswith("ship_") and fn.endswith("_macro.xml")): continue
            n += 1
            txt = open(os.path.join(d,fn),encoding="utf-8").read()
            for k,pat in (("type",r'<ship type="([^"]+)"'),("icon",r'icon="([^"]+)"'),("makerrace",r'makerrace="([^"]+)"')):
                m = re.search(pat, txt)
                if m: en[k].add(m.group(1))
    return en, n

ven, nv = collect(VAN)
een, ne = collect(EVE)
print("原版 ship macro 数:", nv, " EVE ship macro 数:", ne)
print("\n=== type ===")
print("原版:", sorted(ven["type"]))
print("EVE :", sorted(een["type"]))
print("EVE有而原版无:", sorted(een["type"]-ven["type"]))
print("\n=== icon ===")
print("原版:", sorted(ven["icon"]))
print("EVE :", sorted(een["icon"]))
print("EVE有而原版无:", sorted(een["icon"]-ven["icon"]))
print("\n=== makerrace ===")
print("原版:", sorted(ven["makerrace"]))
print("EVE :", sorted(een["makerrace"]))
print("EVE有而原版无:", sorted(een["makerrace"]-ven["makerrace"]))
