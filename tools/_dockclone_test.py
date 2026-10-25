# -*- coding: utf-8 -*-
"""dock_clone / dock_list 沙箱验证（临时目录，不动真实 mod）。"""
import importlib.util, json, os, shutil, sys, tempfile

BASE = r"C:\Users\15536\Doubao\chats\2026-10-03\new-chat-1\EVE_Ship_Builder"
sys.path.insert(0, BASE)
spec = importlib.util.spec_from_file_location("server", os.path.join(BASE, "server.py"))
srv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(srv)  # server.py 的 main 受 __main__ 保护

# 1) dock_list 真实扫描
r = srv.dock_list()
items = r["items"]
print("dock_list:", len(items), "个模板")
wp_items = [x for x in items if x["waypoints"] > 0 and x["src"] == "原版"]
print("原版含 waypoint:", len(wp_items))
tpl = next(x for x in items if x["name"] == "dockarea_arg_m_station_01_lowtech")
print("模板样例:", tpl["name"], tpl["cls"], tpl["waypoints"], tpl["macro"], tpl["src"])

# 2) 假 mod 结构
tmp = tempfile.mkdtemp(prefix="dockclone_")
mod = os.path.join(tmp, "mymod")
os.makedirs(os.path.join(mod, "index"))
for kind in ("components", "macros"):
    with open(os.path.join(mod, "index", kind + ".xml"), "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0"?>\n<diff>\n\t<add sel="//index/%s">\n\t</add>\n</diff>\n' % kind)

# 3) 假 waypoint xml（模拟 x4_wp_export.py 产出）
wp = os.path.join(tmp, "wp.xml")
with open(wp, "w", encoding="utf-8") as f:
    f.write("""<?xml version="1.0" encoding="utf-8"?>
<waypoints>
\t<waypoint name="wp_in" tags="typenormal sizeLevel1 speed_slow " x="0" y="50" z="300" qx="0" qy="0" qz="0" qw="-1">
\t\t<links>
\t\t\t<link ref="wp_dock"/>
\t\t</links>
\t</waypoint>
\t<waypoint name="wp_dock" tags="typedock end sizeLevel1 speed_slow " x="0" y="50" z="100" qx="0" qy="0" qz="0" qw="-1"/>
</waypoints>
""")

ov = os.path.join(tmp, "overlay")
out = srv.dock_clone({"tpl": tpl["path"], "new_id": "dockarea_eve_l_01", "wp_xml": wp, "mod": mod, "overlay": ov})
for s in out["steps"]:
    print(("OK " if s["ok"] else "XX ") + s["name"] + " -- " + s["detail"])
print("warnings:", out["warnings"])
assert out["ok"], "dock_clone 失败"

comp = open(os.path.join(mod, "assets", "structures", "dock", "dockarea_eve_l_01.xml"), encoding="utf-8").read()
assert '<component name="dockarea_eve_l_01"' in comp
assert 'name="wp_dock"' in comp and 'name="wp_in"' in comp
assert "XU_Waypoint" not in comp
assert srv._xml_check(comp) is None
mac = open(os.path.join(mod, "assets", "structures", "dock", "macros", "dockarea_eve_l_01_macro.xml"), encoding="utf-8").read()
assert 'macro name="dockarea_eve_l_01_macro"' in mac
assert 'component ref="dockarea_eve_l_01"' in mac
idx = open(os.path.join(mod, "index", "components.xml"), encoding="utf-8").read()
assert 'dockarea_eve_l_01' in idx
assert os.path.isfile(os.path.join(ov, "assets", "structures", "dock", "dockarea_eve_l_01.xml"))
assert 'dockarea_eve_l_01' in open(os.path.join(ov, "index", "components.xml"), encoding="utf-8").read()
print("组件/宏/index/overlay 全部命中")

# 4) 无 waypoint xml（保留模板）+ 二次运行走备份
out2 = srv.dock_clone({"tpl": tpl["path"], "new_id": "dockarea_eve_l_01", "wp_xml": "", "mod": mod, "overlay": ""})
assert out2["ok"], "二次运行失败: " + json.dumps(out2["steps"], ensure_ascii=False)
comp2 = open(os.path.join(mod, "assets", "structures", "dock", "dockarea_eve_l_01.xml"), encoding="utf-8").read()
assert "XU_Waypoint" in comp2, "应保留模板原 waypoint"
assert os.path.isdir(os.path.join(mod, "_shipmodel_backup"))
print("二次运行（保留模板 waypoint + 备份）通过")

# 5) 坏 waypoint（悬空 link / 非法 tag）必须中止且零写入
bad = os.path.join(tmp, "bad.xml")
open(bad, "w", encoding="utf-8").write('<waypoints><waypoint name="a" tags="typedock bogus " x="0" y="0" z="0" qx="0" qy="0" qz="0" qw="1"><links><link ref="ghost"/></links></waypoint></waypoints>')
out3 = srv.dock_clone({"tpl": tpl["path"], "new_id": "dockarea_eve_bad_01", "wp_xml": bad, "mod": mod, "overlay": ""})
assert not out3["ok"]
assert not os.path.exists(os.path.join(mod, "assets", "structures", "dock", "dockarea_eve_bad_01.xml"))
print("坏 waypoint 中止且零写入通过；错误:", out3["steps"][-1]["detail"])

shutil.rmtree(tmp, ignore_errors=True)
print("ALL PASS")
