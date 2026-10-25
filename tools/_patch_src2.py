# -*- coding: utf-8 -*-
P = r"C:\Users\15536\Doubao\chats\2026-10-03\new-chat-1\EVE_Ship_Builder\server.py"
raw = open(P, "rb").read()
txt = raw.decode("utf-8").replace("\r\n", "\n")
def rep(old, new, name):
    global txt
    c = txt.count(old)
    assert c == 1, "%s count=%d" % (name, c)
    txt = txt.replace(old, new); print("OK", name)

# 1) factions 补 source
rep(
"""    refs, order = {}, []
    files = [os.path.join(ROOT, "libraries", "factions.xml")] + \\
            [os.path.join(ROOT, "extensions", d, "libraries", "factions.xml") for d in _ext_order()]
    for fp in files:
        if not os.path.isfile(fp):
            continue
        txt = open(fp, encoding="utf-8").read()
        for m in re.finditer(r'<faction\\b(?=[^>]*\\bid="([^"]+)")([^>]*)>', txt):
            fid, attrs = m.group(1), m.group(2)
            mm = re.search(r'name="([^"]+)"', attrs)
            if mm and fid not in refs:
                refs[fid] = mm.group(1); order.append(fid)
    oi = {f: i for i, f in enumerate(order)}
    ci = {c: i for i, c in enumerate(FAC_CAT_ORDER)}
    out = [{"id": fid, "name": LX.lname(ref, fid, "zh") or fid,
            "category": _fac_cat(fid), "cat_name": FAC_CAT_NAME[_fac_cat(fid)]}
           for fid, ref in refs.items()]""",
"""    refs, order, srcs = {}, [], {}
    vanilla_p = os.path.join(ROOT, "libraries", "factions.xml")
    files = [vanilla_p] + \\
            [os.path.join(ROOT, "extensions", d, "libraries", "factions.xml") for d in _ext_order()]
    for fp in files:
        if not os.path.isfile(fp):
            continue
        txt = open(fp, encoding="utf-8").read()
        src = "vanilla" if fp == vanilla_p else os.path.basename(os.path.dirname(os.path.dirname(fp)))
        for m in re.finditer(r'<faction\\b(?=[^>]*\\bid="([^"]+)")([^>]*)>', txt):
            fid, attrs = m.group(1), m.group(2)
            mm = re.search(r'name="([^"]+)"', attrs)
            if mm and fid not in refs:
                refs[fid] = mm.group(1); order.append(fid); srcs[fid] = src
    oi = {f: i for i, f in enumerate(order)}
    ci = {c: i for i, c in enumerate(FAC_CAT_ORDER)}
    out = [{"id": fid, "name": LX.lname(ref, fid, "zh") or fid,
            "source": srcs.get(fid, "vanilla"),
            "category": _fac_cat(fid), "cat_name": FAC_CAT_NAME[_fac_cat(fid)]}
           for fid, ref in refs.items()]""",
"factions 补 source")

# 2) software 补 source
rep(
"""def _software_list():
    \"\"\"汇总所有源（原版 wares + 各 mod wares）的 software_* 软件列表 [{id,name}]，含中文名。\"\"\"
    seen, out = {}, []
    def add(sid, name_ref):
        if sid in seen:
            return
        seen[sid] = 1
        out.append({"id": sid, "name": LX.ref_text(name_ref, "zh") if name_ref else sid})
    roots = [os.path.join(ROOT, "libraries", "wares.xml")] +             [os.path.join(ROOT, "extensions", m, "libraries", "wares.xml") for m in _ext_order()]
    for wp in roots:
        if not os.path.isfile(wp):
            continue
        t = open(wp, encoding="utf-8", errors="ignore").read()
        for w in re.finditer(r'<ware id="(software_[^"]+)"[^>]*>(.*?)</ware>', t, re.S):
            nm = re.search(r'name="(\\{[^"]*\\})"', w.group(0))
            add(w.group(1), nm.group(1) if nm else "")
    return sorted(out, key=lambda x: x["name"] or x["id"])""",
"""def _software_list():
    \"\"\"汇总所有源（原版 wares + 各 mod wares）的 software_* 软件列表 [{id,name,source}]，含中文名。\"\"\"
    seen, out = {}, []
    vanilla_p = os.path.join(ROOT, "libraries", "wares.xml")
    def add(sid, name_ref, src):
        if sid in seen:
            return
        seen[sid] = 1
        out.append({"id": sid, "name": LX.ref_text(name_ref, "zh") if name_ref else sid, "source": src})
    roots = [vanilla_p] +             [os.path.join(ROOT, "extensions", m, "libraries", "wares.xml") for m in _ext_order()]
    for wp in roots:
        if not os.path.isfile(wp):
            continue
        t = open(wp, encoding="utf-8", errors="ignore").read()
        src = "vanilla" if wp == vanilla_p else os.path.basename(os.path.dirname(os.path.dirname(wp)))
        for w in re.finditer(r'<ware id="(software_[^"]+)"[^>]*>(.*?)</ware>', t, re.S):
            nm = re.search(r'name="(\\{[^"]*\\})"', w.group(0))
            add(w.group(1), nm.group(1) if nm else "", src)
    return sorted(out, key=lambda x: x["name"] or x["id"])""",
"software 补 source")

body = txt if nl == "\n" else txt.replace("\n", "\r\n")
open(P, "w", encoding="utf-8", newline="").write(body)
print("written")
