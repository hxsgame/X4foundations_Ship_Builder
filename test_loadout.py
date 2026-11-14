import sys, os, tempfile, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server

tmp = tempfile.mkdtemp()
try:
    mod = os.path.join(tmp, "mod")
    mac_dir = os.path.join(mod, "assets", "units", "size_xl", "macros")
    os.makedirs(mac_dir)

    def mk_macro(name):
        p = os.path.join(mac_dir, name + ".xml")
        with open(p, "w", encoding="utf-8") as f:
            f.write('<macros>\n\t<macro name="%s" class="ship_xl">\n\t</macro>\n</macros>' % name)
        return p

    ld = {
        "enabled": True,
        "engine": "engine_arg_l_allround_01_mk1",
        "engine_path": "con_engine_01",
        "shields": [{"macro":"shield_arg_l_standard_01_mk1","path":"con_shield_01","optional":True},
                    {"macro":"shield_arg_l_standard_01_mk2","path":"con_shield_002","optional":True}],
        "turrets": [{"macro":"turret_arg_l_laser_01_mk1","path":"con_turret_01","optional":True}],
        "weapons": [],
        "thruster": "thruster_gen_l_allround_01_mk1",
    }
    p = mk_macro("ship_spl_xl_hel_macro")
    files = server.write_loadout(mod, "ship_spl_xl_hel_macro", ld, "xl")
    print("modified:", files)
    txt = open(p, encoding="utf-8").read()
    print("---- generated inline loadout ----")
    print(txt)
    assert files and '<loadout id="default">' in txt
    assert '<engine macro="engine_arg_l_allround_01_mk1"' in txt
    assert '<thruster macro="thruster_gen_l_allround_01_mk1"' in txt
    # 必须嵌在 <macro> 元素内，不能挂在 <macros> 顶层
    assert txt.index('<loadouts>') > txt.index('<macro name="ship_spl_xl_hel_macro"')
    assert txt.index('<loadout id="default">') < txt.index('</macro>')

    # 第二艘船：独立写入，预设不串船
    p2 = mk_macro("ship_tel_xl_demo_macro")
    ld2 = {"enabled": True, "engine": "engine_tel_xl_allround_01_mk1", "engine_path": "con_engine_01",
           "shields": [], "turrets": [], "weapons": [], "thruster": ""}
    assert server.write_loadout(mod, "ship_tel_xl_demo_macro", ld2, "xl")
    assert '<loadout id="default">' in open(p2, encoding="utf-8").read()
    assert open(p, encoding="utf-8").read().count('<loadout id="default">') == 1
    print("---- 两船各 1 个 default 预设 OK ----")

    # 未启用：不写
    assert server.write_loadout(mod, "ship_spl_xl_hel_macro", {"enabled": False}, "xl") == []
    # 启用但装备全空：清空已有 default，并返回被修改文件
    assert server.write_loadout(mod, "ship_spl_xl_hel_macro", {"enabled": True, "engines": []}, "xl")
    assert '<loadout id="default">' not in open(p, encoding="utf-8").read()
    # 船 macro 不存在：返回空
    assert server.write_loadout(mod, "ship_missing_macro", ld, "xl") == []
    print("ALL OK")
finally:
    shutil.rmtree(tmp)
