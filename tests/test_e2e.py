# -*- coding: utf-8 -*-
"""端到端：generate 成功路径（真实落盘 + 注册），以及 generate→delitem 往返删除干净。"""
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server

INDEX_TPL = """<?xml version="1.0" encoding="utf-8"?>
<diff>
\t<add sel="/index">
\t</add>
</diff>
"""

WARES_TPL = """<?xml version="1.0" encoding="utf-8"?>
<diff>
\t<add sel="/wares">
\t</add>
</diff>
"""

COMP_TPL = """<?xml version="1.0" encoding="utf-8"?>
<components>
  <component name="test_tpl" class="ship_s">
    <source geometry="assets\\units\\size_s\\test_tpl_data" />
  </component>
</components>
"""

MACRO_TPL = """<?xml version="1.0" encoding="utf-8"?>
<macros>
  <macro name="test_tpl_macro" class="ship_s">
    <component ref="test_tpl" />
    <properties>
      <identification name="{20101,1}" basename="{20101,2}" description="{20101,3}"/>
      <hull max="1000"/>
    </properties>
    <connections>
      <connection name="con_storage_01" tags="storage">
        <macro ref="storage_test_tpl_macro" />
      </connection>
    </connections>
  </macro>
</macros>
"""

STORAGE_TPL = """<?xml version="1.0" encoding="utf-8"?>
<macros>
  <macro name="storage_test_tpl_macro" class="storage">
    <component ref="generic_storage" />
    <properties>
      <identification makerrace="argon"/>
      <cargo max="1000" tags="container"/>
    </properties>
  </macro>
</macros>
"""


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="x4sb_e2e_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = os.path.join(self.tmp, "root")
        self.mod = os.path.join(self.root, "extensions", "TestMod")
        self.units = os.path.join(self.root, "assets", "units", "size_s")

        _write(os.path.join(self.units, "test_tpl.xml"), COMP_TPL)
        _write(os.path.join(self.units, "test_tpl_data", "mesh.xmf"), "mesh")
        _write(os.path.join(self.units, "macros", "test_tpl_macro.xml"), MACRO_TPL)
        _write(os.path.join(self.units, "macros", "storage_test_tpl_macro.xml"), STORAGE_TPL)
        for kind in ("macros", "components"):
            _write(os.path.join(self.mod, "index", kind + ".xml"), INDEX_TPL)
        _write(os.path.join(self.mod, "libraries", "wares.xml"), WARES_TPL)

        self._old_root, self._old_mod = server.ROOT, server.MOD_DIR
        server.ROOT = self.root
        server.MOD_DIR = self.mod
        self.addCleanup(setattr, server, "ROOT", self._old_root)
        self.addCleanup(setattr, server, "MOD_DIR", self._old_mod)
        for name in ("_SHIP_TEX_INDEX", "_ICON_TEX_INDEX", "_UPG_TEX_DIRS"):
            self.addCleanup(setattr, server, name, None)

    def _tpl(self):
        return {"id": "test_tpl", "source": "vanilla", "size": "s",
                "race_code": "argon", "dockarea": None}

    def _generate(self, new_id="test_ship_01"):
        with mock.patch("server.list_templates", return_value=[self._tpl()]):
            return server.generate({"new_id": new_id, "template": "test_tpl",
                                    "target_mod": self.mod, "faction": "argon"})


class GenerateSuccessTest(_Base):
    def test_generate_creates_files_and_registers(self):
        out = self._generate()
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["warnings"], [])

        dst = os.path.join(self.mod, "assets", "units", "size_s")
        comp = os.path.join(dst, "test_ship_01.xml")
        macro = os.path.join(dst, "macros", "test_ship_01_macro.xml")
        stor = os.path.join(dst, "macros", "storage_test_ship_01_macro.xml")
        for p in (comp, macro, stor):
            self.assertTrue(os.path.isfile(p), p)
        self.assertTrue(os.path.isdir(os.path.join(dst, "test_ship_01_data")))

        ctxt = open(comp, encoding="utf-8").read()
        self.assertIn('name="test_ship_01"', ctxt)
        self.assertIn('geometry="extensions\\TestMod\\assets\\units\\size_s\\test_ship_01_data"', ctxt)

        mtxt = open(macro, encoding="utf-8").read()
        self.assertIn('name="test_ship_01_macro"', mtxt)
        self.assertIn('<component ref="test_ship_01"', mtxt)
        self.assertIn('<macro ref="storage_test_ship_01_macro"', mtxt)

        idx_macros = open(os.path.join(self.mod, "index", "macros.xml"), encoding="utf-8").read()
        idx_comps = open(os.path.join(self.mod, "index", "components.xml"), encoding="utf-8").read()
        self.assertIn('name="test_ship_01_macro"', idx_macros)
        self.assertIn('name="storage_test_ship_01_macro"', idx_macros)
        self.assertIn('name="test_ship_01"', idx_comps)

        wares = open(os.path.join(self.mod, "libraries", "wares.xml"), encoding="utf-8").read()
        self.assertIn('<ware id="test_ship_01"', wares)

        # created 中的文件应全部实际存在（回滚清单不准会误删/漏删）
        for rp in out["created"]:
            self.assertTrue(os.path.exists(os.path.join(self.mod, rp)), rp)


class GenerateDeleteRoundTripTest(_Base):
    def test_generate_then_delitem_removes_everything(self):
        out = self._generate()
        self.assertTrue(out["ok"], out)

        res = server.delitem({"id": "test_ship_01", "target_mod": self.mod, "kind": "ship"})
        self.assertTrue(res["ok"], res)

        dst = os.path.join(self.mod, "assets", "units", "size_s")
        for p in (os.path.join(dst, "test_ship_01.xml"),
                  os.path.join(dst, "test_ship_01_macro.xml"),
                  os.path.join(dst, "macros", "test_ship_01_macro.xml"),
                  os.path.join(dst, "macros", "storage_test_ship_01_macro.xml")):
            self.assertFalse(os.path.exists(p), p)
        self.assertFalse(os.path.isdir(os.path.join(dst, "test_ship_01_data")))

        idx_macros = open(os.path.join(self.mod, "index", "macros.xml"), encoding="utf-8").read()
        idx_comps = open(os.path.join(self.mod, "index", "components.xml"), encoding="utf-8").read()
        wares = open(os.path.join(self.mod, "libraries", "wares.xml"), encoding="utf-8").read()
        self.assertNotIn('name="test_ship_01', idx_macros)
        self.assertNotIn('name="test_ship_01"', idx_comps)
        self.assertNotIn('id="test_ship_01"', wares)


if __name__ == "__main__":
    unittest.main()
