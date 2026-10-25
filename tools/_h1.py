# -*- coding: utf-8 -*-
P = r"C:\Users\15536\Doubao\chats\2026-10-03\new-chat-1\EVE_Ship_Builder\server.py"
raw = open(P, "rb").read()
nl = "\r\n" if b"\r\n" in raw else "\n"
txt = raw.decode("utf-8").replace("\r\n", "\n")
def rep(old, new, name):
    global txt
    c = txt.count(old)
    assert c == 1, "%s count=%d" % (name, c)
    txt = txt.replace(old, new); print("OK", name)

# 1) 新增全局组件查找（跨源引用回退），插在 _equip_component 定义前
rep(
"""def _equip_component(macfile, ref):""",
"""_GLOBAL_ASSETS = None
_GCOMPCACHE = {}
def _global_assets_roots():
    \"\"\"所有资产树的根：原版 assets + 每个扩展的 assets（跨源组件查找用）。\"\"\"
    global _GLOBAL_ASSETS
    if _GLOBAL_ASSETS is None:
        roots = [os.path.join(ROOT, "assets")]
        ext = os.path.join(ROOT, "extensions")
        if os.path.isdir(ext):
            for d in sorted(os.listdir(ext)):
                p = os.path.join(ext, d, "assets")
                if os.path.isdir(p):
                    roots.append(p)
        _GLOBAL_ASSETS = roots
    return _GLOBAL_ASSETS

def _find_comp_global(ref):
    \"\"\"全资产树查找组件 ref.xml（mod 宏引用原版/其他 mod 组件时本地找不到）。
    带缓存；仅在该组件本地定位失败时调用。\"\"\"
    if ref in _GCOMPCACHE:
        return _GCOMPCACHE[ref]
    found = None
    for base in _global_assets_roots():
        if found:
            break
        for r, _, fs in os.walk(base):
            if ref + ".xml" in fs:
                found = os.path.join(r, ref + ".xml")
                break
    _GCOMPCACHE[ref] = found
    return found

def _equip_component(macfile, ref):""",
"全局组件查找")

# 2) equip_read：组件定位失败时全局回退
rep(
"""    ref = _read_macro_ref(it["path"])
    comp = _equip_component(it["path"], ref) if ref else None
    conn_tags, conn_name = "", """",
"""    ref = _read_macro_ref(it["path"])
    comp = _equip_component(it["path"], ref) if ref else None
    if not comp and ref:
        comp = _find_comp_global(ref)
    conn_tags, conn_name = "", """",
"equip_read 全局回退")

# 3) equip_chain：主组件定位失败时全局回退
rep(
"""    ref = _read_macro_ref(mac)
    comp = _equip_component(mac, ref) if ref else None
    out["component"] = comp""",
"""    ref = _read_macro_ref(mac)
    comp = _equip_component(mac, ref) if ref else None
    if not comp and ref:
        comp = _find_comp_global(ref)
    out["component"] = comp""",
"equip_chain 主回退")

# 4) equip_chain：弹丸组件定位失败时全局回退
rep(
"""                bref = _read_macro_ref(bit["path"])
                bcomp = _equip_component(bit["path"], bref) if bref else None""",
"""                bref = _read_macro_ref(bit["path"])
                bcomp = _equip_component(bit["path"], bref) if bref else None
                if not bcomp and bref:
                    bcomp = _find_comp_global(bref)""",
"equip_chain 弹丸回退")

# 5) equip_generate：模板组件定位失败时全局回退
rep(
"""    tpl_ref = _read_macro_ref(src_mac) or ""
    tpl_geo = _comp_geometry_id(_equip_component(src_mac, tpl_ref)) if tpl_ref else """,",
"""    tpl_ref = _read_macro_ref(src_mac) or ""
    tpl_comp = _equip_component(src_mac, tpl_ref) if tpl_ref else None
    if not tpl_comp and tpl_ref:
        tpl_comp = _find_comp_global(tpl_ref)
    tpl_geo = _comp_geometry_id(tpl_comp) if tpl_comp else """,",
"equip_generate 模板回退")

body = txt if nl == "\n" else txt.replace("\n", "\r\n")
open(P, "w", encoding="utf-8", newline="").write(body)
print("written")
