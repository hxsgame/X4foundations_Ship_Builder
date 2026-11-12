# -*- coding: utf-8 -*-
"""写入事务化：created 回滚与 generate 失败不留半成品。"""
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server


def _write(path, text="x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


class RollbackCreatedTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="x4sb_tx_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.mod = os.path.join(self.tmp, "extensions", "TestMod")

    def test_removes_files_and_dirs(self):
        f = os.path.join(self.mod, "assets", "units", "size_s", "ship.xml")
        d = os.path.join(self.mod, "assets", "units", "size_s", "ship_data", "mesh.xmf")
        _write(f)
        _write(d)
        server._rollback_created(self.mod, ["assets/units/size_s/ship_data",
                                            "assets/units/size_s/ship.xml"])
        self.assertFalse(os.path.exists(f))
        self.assertFalse(os.path.isdir(os.path.dirname(d)))

    def test_ignores_missing_and_absolute(self):
        p = os.path.join(self.mod, "a.xml")
        _write(p)
        server._rollback_created(self.mod, ["missing.xml", p])
        self.assertFalse(os.path.exists(p))


class GenerateRollbackTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="x4sb_gen_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = os.path.join(self.tmp, "root")
        self.mod = os.path.join(self.root, "extensions", "TestMod")
        self.units = os.path.join(self.root, "assets", "units", "size_s")
        _write(os.path.join(self.units, "test_tpl.xml"), "dummy")
        _write(os.path.join(self.units, "test_tpl_data", "mesh.xmf"))
        self._old_root = server.ROOT
        server.ROOT = self.root
        self.addCleanup(setattr, server, "ROOT", self._old_root)

    def test_missing_template_macro_rolls_back_created(self):
        tpl = {"id": "test_tpl", "source": "vanilla", "size": "s",
               "race_code": "argon", "dockarea": None}
        comp = ('<components><component name="test_tpl">'
                '<source geometry="assets\\units\\size_s\\test_tpl_data"/>'
                '</component></components>')
        with mock.patch("server.list_templates", return_value=[tpl]), \
                mock.patch("server._read_ship_comp_txt", return_value=comp), \
                mock.patch("server._find_ship_macro",
                           return_value=os.path.join(self.units, "no_macro.xml")):
            out = server.generate({"new_id": "test_ship_01", "template": "test_tpl",
                                   "target_mod": self.mod, "faction": "argon"})
        self.assertFalse(out["ok"], out)
        self.assertIn("模板 macro 缺失", out["error"])
        dst_dir = os.path.join(self.mod, "assets", "units", "size_s")
        self.assertFalse(os.path.isdir(os.path.join(dst_dir, "test_ship_01_data")))
        self.assertFalse(os.path.isfile(os.path.join(dst_dir, "test_ship_01.xml")))


if __name__ == "__main__":
    unittest.main()
