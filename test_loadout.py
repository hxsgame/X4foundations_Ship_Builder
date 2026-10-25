import sys, os, tempfile, shutil
sys.path.insert(0, r"C:\Users\15536\Doubao\chats\2026-10-03\new-chat-1\EVE_Ship_Builder")
import server

tmp = tempfile.mkdtemp()
try:
    mod = os.path.join(tmp, "mod")
    os.makedirs(mod)
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
    files = server.write_loadout(mod, "ship_spl_xl_hel_macro", ld)
    print("modified:", files)
    p = os.path.join(mod, "libraries", "loadouts.xml")
    txt = open(p, encoding="utf-8").read()
    print("---- generated loadouts.xml ----")
    print(txt)
    # 第二次调用应插入（不重复新建），测已有文件插入
    ld2 = {"enabled": True, "engine": "engine_tel_xl_allround_01_mk1", "engine_path": "con_engine_01",
           "shields": [], "turrets": [], "weapons": [], "thruster": ""}
    server.write_loadout(mod, "ship_tel_xl_demo_macro", ld2)
    txt2 = open(p, encoding="utf-8").read()
    print("---- after 2nd insert, loadout count:", txt2.count("<loadout"))
    # 未启用时应返回空
    assert server.write_loadout(mod, "ship_x_macro", {"enabled": False}) == []
    # 空装配（无任何宏）应返回空
    assert server.write_loadout(mod, "ship_y_macro", {"enabled": True, "engine":"", "shields":[], "turrets":[], "weapons":[]}) == []
    print("ALL OK")
finally:
    shutil.rmtree(tmp)
