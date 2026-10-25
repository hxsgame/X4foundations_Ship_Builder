# -*- coding: utf-8 -*-
# group 支持回归测试（_wp_parse / _wp_render / 模板泊位 group 提取）。跑完可删。
import re, io, sys, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server

fails = []
def ck(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ((" | " + detail) if detail and not cond else ""))
    if not cond:
        fails.append(name)

# 1) 名字后缀 -g<组名> 拆解 + links 重映射 + group= 属性直读
xml = (u'<?xml version="1.0"?>\n<waypoints>\n'
       u'\t<waypoint name="wp_01-gmt_dock_01" tags="dockpath start " x="1" y="2" z="3" qx="0" qy="0" qz="0" qw="1">\n'
       u'\t\t<links>\n\t\t\t<link ref="wp_02-gmt_dock_01"/>\n\t\t</links>\n\t</waypoint>\n'
       u'\t<waypoint name="wp_02-gmt_dock_01" tags="dockpath end " x="4" y="5" z="6" qx="0" qy="0" qz="0" qw="1"/>\n'
       u'\t<waypoint name="solo_01" tags="dockpath " group="mt_dock_02" x="0" y="0" z="0" qx="0" qy="0" qz="0" qw="1"/>\n'
       u'</waypoints>\n')
wps, errs, warns = server._wp_parse(xml)
ck("后缀拆解无错误", not errs, "；".join(errs))
ck("后缀拆成组", [w["group"] for w in wps] == ["mt_dock_01", "mt_dock_01", "mt_dock_02"], str([w["group"] for w in wps]))
ck("名字去后缀", [w["name"] for w in wps] == ["wp_01", "wp_02", "solo_01"], str([w["name"] for w in wps]))
ck("links 重映射", wps[0]["links"] == ["wp_02"], str(wps[0]["links"]))
ck("全有组则无缺组警告", not any("缺 group" in x for x in warns), str(warns))

# 2) 渲染保留 group，且属性顺序与原版一致（name tags group x...）
out = server._wp_render(wps, "\t")
ck("渲染带 group 属性", 'group="mt_dock_01"' in out and 'group="mt_dock_02"' in out)
ck("属性顺序 name→tags→group→x", bool(re.search(r'name="wp_01" tags="dockpath start " group="mt_dock_01" x="1"', out)), out.splitlines()[1])
ck("渲染后名字无后缀", "-gmt_dock" not in out)

# 3) 部分缺 group → 警告
xml2 = xml.replace(u' group="mt_dock_02"', u'')
wps2, errs2, warns2 = server._wp_parse(xml2)
ck("部分缺组报警告", any("缺 group" in x for x in warns2), str(warns2))

# 4) 名字不是后缀的不误拆（mt_dock_01-waypoint_01 这种原版命名）
xml3 = u'<waypoints>\n\t<waypoint name="mt_dock_01-waypoint_01" tags="dockpath start " x="0" y="0" z="0" qx="0" qy="0" qz="0" qw="1"/>\n</waypoints>\n'
wps3, errs3, warns3 = server._wp_parse(xml3)
ck("原版命名不误拆", wps3 and wps3[0]["name"] == "mt_dock_01-waypoint_01" and wps3[0]["group"] == "", str(wps3))

# 5) 真实模板泊位连接的 group 提取（dock_clone 里的检查用的正则）
p = r"D:\Games\X4 exout\extensions\UP7_Real_EVE_Ships\assets\structures\dock\dockarea_spl_xl_hel_01.xml"
t = io.open(p, encoding="utf-8").read()
tg = set(re.findall(r'<connection\b[^>]*\bgroup="([^"]+)"', t))
ck("模板泊位 group 提取", {"mt_dock_01", "mt_dock_02", "mt_dock_03"} <= tg, str(tg))

print("RESULT:", "ALL PASS" if not fails else "FAIL %d" % len(fails))
sys.exit(1 if fails else 0)
