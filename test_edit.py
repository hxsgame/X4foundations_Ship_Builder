# -*- coding: utf-8 -*-
import json, urllib.request, sys

def api(path, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request("http://127.0.0.1:8765"+path, data=data,
                                 headers={"Content-Type":"application/json"})
    return json.loads(urllib.request.urlopen(req).read().decode("utf-8"))

# 1. 列表
tpls = api("/api/templates")
print("TPL_COUNT=%d" % len(tpls))
for t in tpls:
    print("  %-28s size=%s zh=%-10s en=%-10s tids=%s cargo=%s hull=%s" % (
        t["id"], t["size"], t["name_zh"], t["name_en"], t["tids"], t["props"]["cargo"], t["props"]["hull"]))
print("---")

# 2. 编辑 golem：改中文名（修复 ???）+ hull
edit_body = {"id":"ship_spl_xl_golem", "name_zh":"石像鬼", "name_en":"GOLEM",
             "desc_zh":"EVE 巨型舰船 石像鬼", "desc_en":"EVE capital ship Golem",
             "hull":"9000000", "cargo":"88000"}
r = api("/api/edit", edit_body)
print("EDIT_OK=%s modified=%d" % (r.get("ok"), len(r.get("modified",[]))))
for f in r.get("modified",[]): print("  ~ " + f)
print("  bakdir=" + r.get("bakdir",""))

# 3. 重读列表验证写回
tpls2 = {t["id"]:t for t in api("/api/templates")}
g = tpls2.get("ship_spl_xl_golem")
print("--- RELOAD")
print("  name_zh=%s hull=%s cargo=%s" % (g["name_zh"], g["props"]["hull"], g["props"]["cargo"]))
