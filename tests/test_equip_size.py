# -*- coding: utf-8 -*-
"""装备跨尺寸（L↔XL）回归：
- 挂载连接 tags 尺寸词改写 / 补词
- ID / 宏名里的尺寸词替换
- 弹丸、引擎推进·超速·声音、炮塔伤害特效引用（目标资源不存在时保留原值并提示）
- equip_generate 落盘：组件 tags、macro 引用、缓存 sizes、ID 尺寸词提示
"""
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)
import server

TURRET_COMP = '''<?xml version="1.0" encoding="utf-8"?>
<components>
  <component name="{id}" class="turret">
    <source geometry="assets\\props\\WeaponSystems\\energy\\{id}_data"/>
    <connections>
      <connection name="con_turret_beam_l" tags="turret large standard component combat">
        <parts><part name="part_main" tags="turret"/></parts>
      </connection>
    </connections>
  </component>
</components>
'''

TURRET_MAC = '''<?xml version="1.0" encoding="utf-8"?>
<macros>
  <macro name="{id}_macro" class="turret">
    <component ref="{id}"/>
    <properties>
      <identification name="{{20101,1}}" mk="1"/>
      <hull max="1000"/>
      <rotationspeed max="90"/>
      <bullet class="{bullet}_macro"/>
      <sefx_damage_high ref="surfacemodule_damage_l_high"/>
      <sefx_damage_low ref="surfacemodule_damage_l_low"/>
    </properties>
  </macro>
</macros>
'''

BULLET_MAC = '''<?xml version="1.0" encoding="utf-8"?>
<macros>
  <macro name="{id}_macro" class="bullet">
    <component ref="{id}"/>
    <properties>
      <damage value="10"/>
    </properties>
  </macro>
</macros>
'''

ENGINE_COMP = '''<?xml version="1.0" encoding="utf-8"?>
<components>
  <component name="{id}" class="engine">
    <source geometry="assets\\props\\Engines\\{id}_data"/>
    <connections>
      <connection name="con_engine_01" tags="engine large">
        <parts><part name="part_main" tags="engine"/></parts>
      </connection>
    </connections>
  </component>
</components>
'''

ENGINE_MAC = '''<?xml version="1.0" encoding="utf-8"?>
<macros>
  <macro name="{id}_macro" class="engine">
    <component ref="{id}"/>
    <properties>
      <identification name="{{20101,2}}" mk="1"/>
      <boosting ref="gen_l_boosteffect_01"/>
      <traveling ref="gen_traveldrive_fx_l"/>
      <enginedetail ref="enginedetail_ship_l_01"/>
      <thrust forward="1000" reverse="500"/>
      <hull max="1000"/>
    </properties>
  </macro>
</macros>
'''

EFFECTS_XML = '''<?xml version="1.0" encoding="utf-8"?>
<effects>
  <effect name="gen_l_boosteffect_01"/>
  <effect name="gen_xl_boosteffect_01"/>
  <effect name="gen_traveldrive_fx_l"/>
  <effect name="gen_traveldrive_fx_xl"/>
  <effect name="surfacemodule_damage_l_high"/>
  <effect name="surfacemodule_damage_l_low"/>
</effects>
'''

SOUND_XML = '''<?xml version="1.0" encoding="utf-8"?>
<soundlibrary>
  <group id="enginedetail_ship_l_01"/>
  <group id="enginedetail_ship_xl_01"/>
</soundlibrary>
'''

INDEX_XML = '''<?xml version="1.0" encoding="utf-8"?>
<diff>
  <add sel="/{sel}">
  </add>
</diff>
'''

WARES_XML = '''<?xml version="1.0" encoding="utf-8"?>
<diff>
  <add sel="/wares">
  </add>
</diff>
'''

ICONS_XML = '''<?xml version="1.0" encoding="utf-8"?>
<diff>
  <add sel="/icons">
  </add>
</diff>
'''


class EquipSizeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="up7_eqsize_")
        self.root = os.path.join(self.tmp, "root")
        self.mod = os.path.join(self.root, "extensions", "up7_test")
        self._build_root()
        self._build_mod()
        self._saved = (server.ROOT, server.MOD_DIR)
        server.ROOT, server.MOD_DIR = self.root, self.mod
        for n in ("_EQ_SCAN_CACHE", "_EQ_DUP_CACHE", "_EQ_BY_SOURCE",
                  "_BULLET_SCAN_CACHE", "_BULLET_DUP_CACHE", "_BULLET_BY_SOURCE"):
            setattr(server, n, None)
        server._LIB_NAME_CACHE.clear()
        # 缓存文件读写隔离（避免测试污染真实 .cache）
        p1 = mock.patch("server._cache_load", return_value=None)
        p2 = mock.patch("server._cache_save")
        p1.start(); p2.start()
        self.addCleanup(p1.stop)
        self.addCleanup(p2.stop)

    def tearDown(self):
        server.ROOT, server.MOD_DIR = self._saved
        server._LIB_NAME_CACHE.clear()
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---------- fixtures ----------
    def _w(self, p, txt):
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(txt)

    def _build_root(self):
        pr = os.path.join(self.root, "assets", "props")
        wd = os.path.join(pr, "WeaponSystems", "energy")
        for tid, bullet in (("turret_test_l", "bullet_test_l_01"),
                            ("turret_test2_l", "bullet_test2_l_01")):
            self._w(os.path.join(wd, tid + ".xml"), TURRET_COMP.format(id=tid))
            self._w(os.path.join(wd, tid + "_data", "mesh.xmf"), "x")
            self._w(os.path.join(wd, "macros", tid + "_macro.xml"),
                    TURRET_MAC.format(id=tid, bullet=bullet))
        fx = os.path.join(self.root, "assets", "fx", "weaponFx", "macros")
        for bid in ("bullet_test_l_01", "bullet_test_xl_01", "bullet_test2_l_01"):
            self._w(os.path.join(fx, bid + "_macro.xml"), BULLET_MAC.format(id=bid))
        ed = os.path.join(pr, "Engines")
        self._w(os.path.join(ed, "engine_test_l.xml"), ENGINE_COMP.format(id="engine_test_l"))
        self._w(os.path.join(ed, "engine_test_l_data", "mesh.xmf"), "x")
        self._w(os.path.join(ed, "macros", "engine_test_l_macro.xml"),
                ENGINE_MAC.format(id="engine_test_l"))
        lib = os.path.join(self.root, "libraries")
        self._w(os.path.join(lib, "effects.xml"), EFFECTS_XML)
        self._w(os.path.join(lib, "sound_library.xml"), SOUND_XML)

    def _build_mod(self):
        self._w(os.path.join(self.mod, "index", "macros.xml"), INDEX_XML.format(sel="index"))
        self._w(os.path.join(self.mod, "index", "components.xml"), INDEX_XML.format(sel="index"))
        self._w(os.path.join(self.mod, "libraries", "wares.xml"), WARES_XML)
        self._w(os.path.join(self.mod, "libraries", "icons.xml"), ICONS_XML)

    def _read(self, *parts):
        with open(os.path.join(*parts), encoding="utf-8") as f:
            return f.read()

    # ---------- 纯函数 ----------
    def test_swap_size_token(self):
        self.assertEqual(server._swap_size_token("turret_par_l_beam", "xl"), "turret_par_xl_beam")
        self.assertEqual(server._swap_size_token("gen_traveldrive_fx_l", "xl"), "gen_traveldrive_fx_xl")
        self.assertEqual(server._swap_size_token("abc_def", "xl"), "abc_def")

    def test_eq_size_helpers(self):
        self.assertEqual(server._eq_size_tag("xl"), "extralarge")
        self.assertEqual(server._eq_size_tag("large"), "large")
        self.assertEqual(server._eq_size_tag("m"), "")
        self.assertEqual(server._eq_size_of_tags("turret extralarge standard"), "xl")
        self.assertEqual(server._eq_size_of_tags("shield medium component"), "")
        self.assertEqual(server._eq_size_of_name("engine_par_l_allround_01_mk1"), "l")
        self.assertEqual(server._eq_size_of_name("shield_arg_m_standard_01"), "")

    def test_resize_mount_tags_added(self):
        ctxt = '<component name="x"><connection name="con_x" tags="turret highpower"/></component>'
        out, st = server._resize_mount_tags(ctxt, "extralarge")
        self.assertEqual(st, "added")
        self.assertIn('tags="turret extralarge highpower"', out)
        out2, st2 = server._resize_mount_tags(ctxt, "extralarge")
        self.assertEqual(st, "added")
        self.assertEqual(server._resize_mount_tags(
            '<component name="x"/>', "extralarge")[1], "nomount")

    # ---------- 生成 ----------
    def test_generate_turret_l_to_xl(self):
        res = server.equip_generate({
            "cls": "turret", "template": "turret_test_l@@vanilla",
            "new_id": "turret_test_xl_01", "size": "xl", "target_mod": self.mod})
        self.assertTrue(res.get("ok"), res)
        self.assertEqual(res.get("size"), "xl")
        comp = self._read(self.mod, "assets", "props", "WeaponSystems", "energy",
                          "turret_test_xl_01.xml")
        self.assertIn('tags="turret extralarge standard component combat"', comp)
        mac = self._read(self.mod, "assets", "props", "WeaponSystems", "energy", "macros",
                         "turret_test_xl_01_macro.xml")
        self.assertIn('class="bullet_test_xl_01_macro"', mac)   # 有 XL 弹丸 → 自动换
        self.assertIn('ref="surfacemodule_damage_l_high"', mac)  # 无 XL 伤害特效 → 保留
        self.assertTrue(any("伤害特效" in w for w in res.get("warnings") or []),
                        res.get("warnings"))
        self.assertEqual(server.equip_scan()["turret"]["turret_test_xl_01"]["sizes"],
                         ["extralarge"])

    def test_generate_same_size_keeps_template(self):
        res = server.equip_generate({
            "cls": "turret", "template": "turret_test_l@@vanilla",
            "new_id": "turret_test_l_02", "target_mod": self.mod})
        self.assertTrue(res.get("ok"), res)
        self.assertEqual(res.get("size"), "l")
        # 原版模型 + 未填 tags + 未跨尺寸 → 不落组件文件，直接引用模板组件
        self.assertFalse(os.path.isfile(os.path.join(
            self.mod, "assets", "props", "WeaponSystems", "energy", "turret_test_l_02.xml")))
        mac = self._read(self.mod, "assets", "props", "WeaponSystems", "energy", "macros",
                         "turret_test_l_02_macro.xml")
        self.assertIn('<component ref="turret_test_l"/>', mac)

    def test_generate_invalid_size_rejected(self):
        res = server.equip_generate({
            "cls": "turret", "template": "turret_test_l@@vanilla",
            "new_id": "turret_test_m_01", "size": "m", "target_mod": self.mod})
        self.assertFalse(res.get("ok"))
        self.assertIn("尺寸", res.get("error") or "")

    def test_generate_bullet_missing_keeps_and_warns(self):
        res = server.equip_generate({
            "cls": "turret", "template": "turret_test2_l@@vanilla",
            "new_id": "turret_test2_xl_01", "size": "xl", "target_mod": self.mod})
        self.assertTrue(res.get("ok"), res)
        mac = self._read(self.mod, "assets", "props", "WeaponSystems", "energy", "macros",
                         "turret_test2_xl_01_macro.xml")
        self.assertIn('class="bullet_test2_l_01_macro"', mac)   # 无 XL 弹丸 → 保留
        self.assertTrue(any("bullet_test2_l_01_macro" in w for w in res.get("warnings") or []),
                        res.get("warnings"))

    def test_generate_id_size_mismatch_warns(self):
        res = server.equip_generate({
            "cls": "turret", "template": "turret_test_l@@vanilla",
            "new_id": "turret_test_l_02", "size": "xl", "target_mod": self.mod})
        self.assertTrue(res.get("ok"), res)
        self.assertTrue(any("ID 的尺寸词" in w for w in res.get("warnings") or []),
                        res.get("warnings"))

    def test_generate_prefilled_fields_still_swaps_bullet(self):
        # 前端会把模板值回填进 fields：与模板相同的值不算用户改动，仍应自动换尺寸
        res = server.equip_generate({
            "cls": "turret", "template": "turret_test_l@@vanilla",
            "new_id": "turret_test_xl_02", "size": "xl", "target_mod": self.mod,
            "fields": {"bullet": "bullet_test_l_01"}})
        self.assertTrue(res.get("ok"), res)
        mac = self._read(self.mod, "assets", "props", "WeaponSystems", "energy", "macros",
                         "turret_test_xl_02_macro.xml")
        self.assertIn('class="bullet_test_xl_01_macro"', mac)

    def test_generate_user_bullet_override_wins(self):
        # 用户显式换了别的弹丸：不覆盖
        res = server.equip_generate({
            "cls": "turret", "template": "turret_test_l@@vanilla",
            "new_id": "turret_test_xl_03", "size": "xl", "target_mod": self.mod,
            "fields": {"bullet": "bullet_test2_l_01"}})
        self.assertTrue(res.get("ok"), res)
        mac = self._read(self.mod, "assets", "props", "WeaponSystems", "energy", "macros",
                         "turret_test_xl_03_macro.xml")
        self.assertIn('class="bullet_test2_l_01_macro"', mac)

    def test_generate_engine_l_to_xl(self):
        res = server.equip_generate({
            "cls": "engine", "template": "engine_test_l@@vanilla",
            "new_id": "engine_test_xl_01", "size": "xl", "target_mod": self.mod})
        self.assertTrue(res.get("ok"), res)
        comp = self._read(self.mod, "assets", "props", "Engines", "engine_test_xl_01.xml")
        self.assertIn('tags="engine extralarge"', comp)
        mac = self._read(self.mod, "assets", "props", "Engines", "macros",
                         "engine_test_xl_01_macro.xml")
        self.assertIn('ref="gen_xl_boosteffect_01"', mac)
        self.assertIn('ref="gen_traveldrive_fx_xl"', mac)
        self.assertIn('ref="enginedetail_ship_xl_01"', mac)


if __name__ == "__main__":
    unittest.main()
