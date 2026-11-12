# -*- coding: utf-8 -*-
"""index 注册：_register_index / _register_equip 的路径、去重与落盘行为。"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server


INDEX_TPL = """<?xml version="1.0" encoding="utf-8"?>
<index>
<add sel="/index">
\t\t<entry name="existing" value="extensions\\Old\\assets\\x"/>
</add>
</index>
"""


def _read(p):
    return open(p, encoding="utf-8").read()


class RegisterIndexTest(unittest.TestCase):
    def setUp(self):
        self.mod = tempfile.mkdtemp(prefix="x4sb_mod_")
        self.addCleanup(shutil.rmtree, self.mod, True)
        os.makedirs(os.path.join(self.mod, "index"))
        for k in ("macros", "components"):
            with open(os.path.join(self.mod, "index", k + ".xml"), "w", encoding="utf-8") as f:
                f.write(INDEX_TPL)

    def test_register_index_adds_and_dedupes(self):
        items = [
            ("macros", "ship_test_macro", "units\\size_l\\macros\\ship_test_macro"),
            ("components", "ship_test", "units\\size_l\\ship_test"),
        ]
        modi = server.register_assets(self.mod, items)
        self.assertEqual(len(modi), 2)
        modn = os.path.basename(self.mod)
        mt = _read(os.path.join(self.mod, "index", "macros.xml"))
        ct = _read(os.path.join(self.mod, "index", "components.xml"))
        self.assertIn('<entry name="ship_test_macro" value="extensions\\%s\\assets\\units\\size_l'
                      '\\macros\\ship_test_macro"/>' % modn, mt)
        self.assertIn('<entry name="ship_test" value="extensions\\%s\\assets\\units\\size_l'
                      '\\ship_test"/>' % modn, ct)
        # 重复注册：同名条目只保留一条
        server.register_assets(self.mod, items)
        self.assertEqual(_read(os.path.join(self.mod, "index", "macros.xml")).count(
            'name="ship_test_macro"'), 1)
        self.assertEqual(_read(os.path.join(self.mod, "index", "components.xml")).count(
            'name="ship_test"'), 1)

    def test_register_assets_updates_existing_entry(self):
        server.register_assets(self.mod, [("macros", "existing", "units\\size_l\\macros\\new_place")])
        mt = _read(os.path.join(self.mod, "index", "macros.xml"))
        self.assertEqual(mt.count('name="existing"'), 1)
        self.assertIn("new_place", mt)
        self.assertNotIn("extensions\\Old\\assets\\x", mt)

    def test_register_index_skips_missing_file(self):
        modi = server.register_assets(self.mod, [("t", "x", "any\\x")])
        self.assertEqual(modi, [])


class RegisterEquipTest(unittest.TestCase):
    def setUp(self):
        self.mod = tempfile.mkdtemp(prefix="x4sb_mod_")
        self.addCleanup(shutil.rmtree, self.mod, True)
        os.makedirs(os.path.join(self.mod, "index"))
        for k in ("macros", "components"):
            with open(os.path.join(self.mod, "index", k + ".xml"), "w", encoding="utf-8") as f:
                f.write(INDEX_TPL)
        self.rel = "WeaponSystems\\standard"
        self.eid = "turret_test_01_mk1"

    def test_components_entry_only_when_file_exists(self):
        modi = server._register_equip(self.mod, "turret", self.eid, self.rel)
        self.assertEqual(modi, [os.path.join("index", "macros.xml")])
        ct = _read(os.path.join(self.mod, "index", "components.xml"))
        self.assertNotIn(self.eid, ct)
        # 组件文件落盘后再次注册，components 才追加
        d = os.path.join(self.mod, "assets", "props", self.rel)
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, self.eid + ".xml"), "w", encoding="utf-8").write("<components/>")
        server._register_equip(self.mod, "turret", self.eid, self.rel)
        ct = _read(os.path.join(self.mod, "index", "components.xml"))
        self.assertIn('name="%s"' % self.eid, ct)
        self.assertEqual(ct.count('name="%s"' % self.eid), 1)


if __name__ == "__main__":
    unittest.main()
