# -*- coding: utf-8 -*-
"""组件装配冒烟：临时 export_root + 临时 mod，验证复制、geometry、宏与 index 注册。"""
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
</add>
</index>
"""

COMP_XML = """<?xml version="1.0" encoding="utf-8"?>
<components>
  <component name="test_comp_01_x1" class="turret">
    <source geometry="assets\\props\\WeaponSystems\\standard\\test_comp_01_x1_data" />
    <connections>
      <connection name="container" tags="" />
    </connections>
  </component>
</components>
"""

MACRO_XML = """<?xml version="1.0" encoding="utf-8"?>
<macros>
  <macro name="test_comp_01_macro" class="turret">
    <component ref="test_comp_01" />
  </macro>
</macros>
"""

ICONS_XML = """<?xml version="1.0" encoding="utf-8"?>
<icons>
  <icon name="upgrade_test_comp_01_macro" texture="assets\\textures\\ui\\upgrades\\test_comp_01_macro.tga"
        height="256" width="256" />
</icons>
"""


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


class ComponentAssembleSmokeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="x4sb_asm_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = os.path.join(self.tmp, "root")
        self.export_root = os.path.join(self.tmp, "export")
        self.mod = os.path.join(self.root, "extensions", "TestMod")
        self.rel = os.path.join("props", "WeaponSystems", "standard")

        _write(os.path.join(self.export_root, "assets", self.rel, "test_comp_01_x1.xml"), COMP_XML)
        _write(os.path.join(self.export_root, "assets", self.rel, "test_comp_01_x1_data", "mesh.xmf"), "mesh")
        for k in ("components", "macros"):
            _write(os.path.join(self.mod, "index", k + ".xml"), INDEX_TPL)
        _write(os.path.join(self.mod, "assets", self.rel, "test_comp_01_macro.xml"), MACRO_XML)
        _write(os.path.join(self.mod, "libraries", "icons.xml"), ICONS_XML)

        self._old_root = server.ROOT
        server.ROOT = self.root
        self.addCleanup(setattr, server, "ROOT", self._old_root)

    def test_assemble_creates_files_and_registers(self):
        out = server.component_assemble({
            "component_id": "test_comp_01_x1",
            "export_root": self.export_root,
            "mod": self.mod,
        })
        self.assertTrue(out["ok"], out)
        dst_dir = os.path.join(self.mod, "assets", self.rel)
        dst_xml = os.path.join(dst_dir, "test_comp_01_x1.xml")
        self.assertTrue(os.path.isfile(dst_xml))
        self.assertTrue(os.path.isdir(os.path.join(dst_dir, "test_comp_01_x1_data")))
        txt = open(dst_xml, encoding="utf-8").read()
        self.assertIn('geometry="extensions\\TestMod\\assets\\props\\WeaponSystems\\standard'
                      '\\test_comp_01_x1_data"', txt)
        self.assertIn('tags="contents"', txt)

        mac = open(os.path.join(dst_dir, "macros", "test_comp_01_x1_macro.xml"),
                   encoding="utf-8").read()
        self.assertIn('name="test_comp_01_x1_macro"', mac)
        self.assertIn('ref="test_comp_01_x1"', mac)

        comps = open(os.path.join(self.mod, "index", "components.xml"), encoding="utf-8").read()
        macros = open(os.path.join(self.mod, "index", "macros.xml"), encoding="utf-8").read()
        self.assertIn('name="test_comp_01_x1"', comps)
        self.assertIn('name="test_comp_01_x1_macro"', macros)
        self.assertIn("extensions\\TestMod\\assets\\props\\WeaponSystems\\standard", comps)

        icons = open(os.path.join(self.mod, "libraries", "icons.xml"), encoding="utf-8").read()
        self.assertIn('name="upgrade_test_comp_01_x1_macro"', icons)


if __name__ == "__main__":
    unittest.main()
