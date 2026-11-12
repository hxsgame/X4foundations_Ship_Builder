# -*- coding: utf-8 -*-
"""geometry 解析规则回归：组件 <source geometry> → 几何 id。"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server


class GeometryReadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="x4sb_geo_")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _write(self, name, text):
        p = os.path.join(self.tmp, name)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        return p

    def test_geometry_id_from_assets_path(self):
        p = self._write(
            "a.xml",
            '<components><component name="x"><source geometry="assets\\props\\WeaponSystems\\standard'
            '\\turret_arg_l_beam_01_mk1_data" /></component></components>')
        self.assertEqual(
            server._comp_source_geometry(p),
            "assets\\props\\WeaponSystems\\standard\\turret_arg_l_beam_01_mk1_data")
        self.assertEqual(server._comp_geometry_id(p), "turret_arg_l_beam_01_mk1")

    def test_geometry_id_from_extensions_path(self):
        p = self._write(
            "b.xml",
            '<components><component name="x"><source geometry="extensions\\UP7_Real_EVE_Ships\\assets'
            '\\props\\x\\engine_arg_l_01_data"/></component></components>')
        self.assertEqual(server._comp_geometry_id(p), "engine_arg_l_01")

    def test_geometry_missing(self):
        p = self._write("c.xml", '<components><component name="x"></component></components>')
        self.assertEqual(server._comp_source_geometry(p), "")
        self.assertEqual(server._comp_geometry_id(p), "")


class GeometryOwnershipTest(unittest.TestCase):
    """目标 mod 自有数据目录 / 跨来源改归属的唯一规则实现。"""

    def test_geo_owned(self):
        self.assertEqual(
            server.geo_owned(r"D:\x\extensions\UP7", r"props\WeaponSystems\standard", "turret_x"),
            r"extensions\UP7\assets\props\WeaponSystems\standard\turret_x_data")
        self.assertEqual(
            server.geo_owned("/x/extensions/UP7/", "props/A/B", "shield_x"),
            r"extensions\UP7\assets\props\A\B\shield_x_data")

    def test_geo_rebase_from_assets(self):
        self.assertEqual(
            server.geo_rebase(r"assets\props\x\old_data", "UP7", "old", "new"),
            r"extensions\UP7\assets\props\x\new_data")

    def test_geo_rebase_from_other_mod(self):
        self.assertEqual(
            server.geo_rebase(r"extensions\Other\assets\props\x\old_data", "UP7", "old", "new"),
            r"extensions\UP7\assets\props\x\new_data")

    def test_geo_rebase_keeps_unrelated_id(self):
        self.assertEqual(
            server.geo_rebase(r"extensions\Other\assets\props\x\keep_data", "UP7", "old", "new"),
            r"extensions\UP7\assets\props\x\keep_data")

    def test_geo_rebase_forward_slashes(self):
        self.assertEqual(
            server.geo_rebase("assets/props/x/old_data", "UP7", "old", "new"),
            r"extensions\UP7\assets\props\x\new_data")

    def test_geo_rebase_size_change(self):
        # L 模板生成 XL 船：数据已复制到 size_xl，几何路径的 size_l 段必须一起改
        self.assertEqual(
            server.geo_rebase(r"assets\units\size_l\ship_bor_l_old_data", "UP7",
                              "ship_bor_l_old", "ship_bor_xl_new", "l", "xl"),
            r"extensions\UP7\assets\units\size_xl\ship_bor_xl_new_data")
        # 尺寸不变时路径保持原样
        self.assertEqual(
            server.geo_rebase(r"assets\units\size_l\old_data", "UP7", "old", "new", "l", "l"),
            r"extensions\UP7\assets\units\size_l\new_data")


if __name__ == "__main__":
    unittest.main()
