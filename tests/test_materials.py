# -*- coding: utf-8 -*-
"""材质前缀换名 / 同步后材质库对齐的回归测试。"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server


def _mat(name, smooth="0.2"):
    return ('\t\t\t<material name="%s" shader="P1_complex_surface.fx" blendmode="NONE" preview="none">\n'
            '\t\t\t\t<properties>\n'
            '\t\t\t\t\t<property type="Float" name="Smoothness" value="%s" />\n'
            '\t\t\t\t</properties>\n'
            '\t\t\t</material>\n' % (name, smooth))


def _mat_tex(name, folder="megathron"):
    return ('\t\t\t<material name="%s" shader="P1_complex_surface.fx" blendmode="NONE" preview="none">\n'
            '\t\t\t\t<properties>\n'
            '\t\t\t\t\t<property type="BitMap" name="diffuse_map" '
            'value="extensions\\UP7_Real_EVE_Ships\\assets\\textures\\%s\\a_a.dds"/>\n'
            '\t\t\t\t</properties>\n'
            '\t\t\t</material>\n' % (name, folder))


def _lib(*mats, coll="megathron"):
    return (server.DIFF_HEADER +
            '\t<add sel="//materiallibrary">\n'
            '\t\t<collection name="%s">\n%s\t\t</collection>\n'
            '\t</add>\n</diff>\n' % (coll, "".join(_mat(m, v) for m, v in mats)))


def _comp(refs):
    return ('<components><component name="ship_x" class="ship_l">\n'
            '  <connections><connection name="ConnectionForpart_main"><parts><part name="part_main">\n'
            '    <lods><lod index="0"><materials>\n%s'
            '    </materials></lod></lods>\n'
            '  </part></parts></connection></connections>\n'
            '</component></components>\n' %
            "".join('      <material id="%d" ref="%s" />\n' % (i + 1, r) for i, r in enumerate(refs)))


class MaterialPrefixTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="x4sb_mat_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.lib = os.path.join(self.tmp, "libraries", "material_library.xml")
        os.makedirs(os.path.dirname(self.lib))
        # 只让材质解析读取测试库，避免命中本机游戏目录
        self._old = server._ml_files_loadorder
        server._ml_files_loadorder = lambda: [self.lib]
        self.addCleanup(setattr, server, "_ml_files_loadorder", self._old)

    def _write(self, path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def test_prefix_clone_only_this_ship(self):
        self._write(self.lib, _lib(("evemate_a", "0.2"), ("evemate_b", "0.3")))
        comp = os.path.join(self.tmp, "assets", "units", "size_l", "ship_x.xml")
        self._write(comp, _comp(["megathron.evemate_a", "megathron.evemate_b"]))
        tuning = {"enabled": True, "prefix": "revelation",
                  "values": {"megathron.evemate_a": {"params": {"Smoothness": "0.8"}},
                             "megathron.evemate_b": {}}}
        rels, warns = server.apply_material_tuning(self.tmp, tuning, comp_path=comp)
        self.assertEqual(warns, [])
        libtxt = open(self.lib, encoding="utf-8").read()
        # 新 collection 建立、旧 collection 原样保留（只增不改）
        self.assertIn('<collection name="revelation">', libtxt)
        self.assertIn('<collection name="megathron">', libtxt)
        self.assertIn('<material name="evemate_a"', libtxt)
        # 本船引用全部换前缀，参数写到新材质
        ctxt = open(comp, encoding="utf-8").read()
        self.assertNotIn('ref="megathron.evemate_a"', ctxt)
        self.assertIn('ref="revelation.evemate_a"', ctxt)
        self.assertIn('ref="revelation.evemate_b"', ctxt)
        self.assertIn('name="Smoothness" value="0.8"', libtxt)
        self.assertTrue(any("material_library.xml" in r for r in rels))

    def test_prefix_existing_is_reused(self):
        self._write(self.lib, _lib(("evemate_a", "0.2"), coll="megathron") +
                    _lib(("evemate_a", "0.9"), coll="revelation"))
        comp = os.path.join(self.tmp, "assets", "units", "size_l", "ship_x.xml")
        self._write(comp, _comp(["megathron.evemate_a"]))
        tuning = {"enabled": True, "prefix": "revelation",
                  "values": {"megathron.evemate_a": {}}}
        rels, warns = server.apply_material_tuning(self.tmp, tuning, comp_path=comp)
        self.assertEqual(warns, [])
        libtxt = open(self.lib, encoding="utf-8").read()
        self.assertEqual(libtxt.count('<material name="evemate_a"'), 2)   # 未重复新增
        self.assertIn('ref="revelation.evemate_a"', open(comp, encoding="utf-8").read())

    def test_prefix_rewrites_texture_paths(self):
        """克隆时材质内的 \\旧前缀\\ 纹理目录段要同步换成 \\新前缀\\。"""
        self._write(self.lib, server.DIFF_HEADER +
                    '\t<add sel="//materiallibrary">\n'
                    '\t\t<collection name="megathron">\n%s\t\t</collection>\n'
                    '\t</add>\n</diff>\n' % _mat_tex("evemate_a"))
        comp = os.path.join(self.tmp, "assets", "units", "size_l", "ship_x.xml")
        self._write(comp, _comp(["megathron.evemate_a"]))
        server.apply_material_tuning(
            self.tmp, {"enabled": True, "prefix": "revelation",
                       "values": {"megathron.evemate_a": {}}}, comp_path=comp)
        libtxt = open(self.lib, encoding="utf-8").read()
        self.assertIn(r'textures\revelation\a_a.dds', libtxt)
        self.assertEqual(libtxt.count(r'textures\megathron\a_a.dds'), 1)   # 旧材质原样保留

    def test_prefix_repairs_existing_clone_texture_paths(self):
        """旧版本已克隆但路径没改的材质：再次应用前缀时只修路径段。"""
        self._write(self.lib, server.DIFF_HEADER +
                    '\t<add sel="//materiallibrary">\n'
                    '\t\t<collection name="megathron">\n%s\t\t</collection>\n'
                    '\t\t<collection name="revelation">\n%s\t\t</collection>\n'
                    '\t</add>\n</diff>\n'
                    % (_mat_tex("evemate_a", "megathron"), _mat_tex("evemate_a", "megathron")))
        comp = os.path.join(self.tmp, "assets", "units", "size_l", "ship_x.xml")
        self._write(comp, _comp(["megathron.evemate_a"]))
        server.apply_material_tuning(
            self.tmp, {"enabled": True, "prefix": "revelation",
                       "values": {"megathron.evemate_a": {}}}, comp_path=comp)
        libtxt = open(self.lib, encoding="utf-8").read()
        self.assertEqual(libtxt.count(r'textures\megathron\a_a.dds'), 1)
        self.assertEqual(libtxt.count(r'textures\revelation\a_a.dds'), 1)
        self.assertEqual(libtxt.count('<material name="evemate_a"'), 2)

    def test_prefix_repairs_when_ref_already_new(self):
        """本船已是新前缀（ref == new_ref）时也要修复旧克隆的纹理目录。"""
        self._write(self.lib, server.DIFF_HEADER +
                    '\t<add sel="//materiallibrary">\n'
                    '\t\t<collection name="megathron">\n%s\t\t</collection>\n'
                    '\t\t<collection name="revelation">\n%s\t\t</collection>\n'
                    '\t</add>\n</diff>\n'
                    % (_mat_tex("evemate_a", "megathron"), _mat_tex("evemate_a", "megathron")))
        comp = os.path.join(self.tmp, "assets", "units", "size_l", "ship_x.xml")
        self._write(comp, _comp(["revelation.evemate_a"]))
        server.apply_material_tuning(
            self.tmp, {"enabled": True, "prefix": "revelation",
                       "values": {"revelation.evemate_a": {}}}, comp_path=comp)
        libtxt = open(self.lib, encoding="utf-8").read()
        self.assertEqual(libtxt.count(r'textures\megathron\a_a.dds'), 1)
        self.assertEqual(libtxt.count(r'textures\revelation\a_a.dds'), 1)


class MaterialFormatTest(unittest.TestCase):
    """材质库写入后的缩进格式（新建 collection / 追加材质 / 补插属性）。"""

    RAW = ('<material name="evemate_x" shader="P1_complex_surface.fx" blendmode="NONE" preview="none">\n'
           '\t\t\t\t<properties>\n'
           '\t\t\t\t\t<property type="Float" name="Smoothness" value="0.8"/>\n'
           '\t\t\t\t</properties>\n'
           '\t\t\t</material>')

    def _head(self):
        return (server.DIFF_HEADER +
                '\t<add sel="//materiallibrary">\n'
                '\t\t<collection name="megathron">\n'
                '\t\t\t<material name="evemate_a" shader="P1_complex_surface.fx" blendmode="NONE" preview="none">\n'
                '\t\t\t\t<properties>\n'
                '\t\t\t\t\t<property type="Float" name="Smoothness" value="0.2"/>\n'
                '\t\t\t\t</properties>\n'
                '\t\t\t</material>\n'
                '\t\t</collection>\n'
                '\t</add>\n</diff>\n')

    def _assert_clean(self, txt):
        for l in txt.split("\n"):
            if "<collection" in l:
                self.assertRegex(l, r'^\s*<collection', "collection 未独占一行: %r" % l)
            if "<material" in l:
                self.assertRegex(l, r'^\s*<material', "material 未独占一行: %r" % l)

    def _has(self, lines, prefix):
        return any(l.startswith(prefix) for l in lines)

    def test_new_collection_indent(self):
        txt = server._ml_insert_material(self._head(), "revelation", self.RAW)
        lines = txt.split("\n")
        self.assertTrue(self._has(lines, '\t\t<collection name="revelation">'))
        self.assertTrue(self._has(lines, '\t\t\t<material name="evemate_x"'))
        self.assertTrue(self._has(lines, '\t\t\t\t<properties>'))
        self.assertTrue(self._has(lines, '\t\t\t\t\t<property type="Float" name="Smoothness" value="0.8"/>'))
        self.assertTrue(self._has(lines, '\t\t</collection>'))
        self.assertTrue(self._has(lines, '\t</add>'))
        self._assert_clean(txt)

    def test_existing_collection_indent(self):
        txt = server._ml_insert_material(self._head(), "megathron", self.RAW)
        lines = txt.split("\n")
        self.assertTrue(self._has(lines, '\t\t\t<material name="evemate_x"'))
        self.assertTrue(self._has(lines, '\t\t\t\t<properties>'))
        self.assertTrue(self._has(lines, '\t\t\t\t\t<property type="Float" name="Smoothness" value="0.8"/>'))
        self.assertTrue(self._has(lines, '\t\t</collection>'))
        self._assert_clean(txt)

    def test_add_end_shares_line(self):
        head = (server.DIFF_HEADER +
                '\t<add sel="//materiallibrary">\n'
                '\t\t<collection name="megathron">\n'
                '\t\t\t<material name="evemate_a" shader="P1_complex_surface.fx" blendmode="NONE" preview="none">\n'
                '\t\t\t\t<properties>\n'
                '\t\t\t\t</properties>\n'
                '\t\t\t</material>\n'
                '\t\t</collection></add>\n</diff>\n')
        txt = server._ml_insert_material(head, "revelation", self.RAW)
        self.assertIn('\n\t\t<collection name="revelation">', txt)
        self._assert_clean(txt)

    def test_insert_collection_block(self):
        coll = ('<collection name="revelation">\n'
                '    <material name="a" shader="P1_complex_surface.fx" blendmode="NONE" preview="none">\n'
                '        <properties>\n'
                '            <property type="Float" name="Smoothness" value="0.5"/>\n'
                '        </properties>\n'
                '    </material>\n'
                '</collection>')
        txt = server._ml_insert_collection(self._head(), coll)
        txt = server._ml_insert_collection(txt, coll.replace('revelation', 'revelation2'))
        lines = txt.split("\n")
        self.assertTrue(self._has(lines, '\t\t<collection name="revelation">'))
        self.assertTrue(self._has(lines, '\t\t<collection name="revelation2">'))
        self.assertTrue(self._has(lines, '\t\t\t<material name="a"'))
        self.assertTrue(self._has(lines, '\t\t\t\t<properties>'))
        self.assertTrue(self._has(lines, '\t\t\t\t\t<property type="Float" name="Smoothness" value="0.5"/>'))
        self._assert_clean(txt)

    def test_set_block_prop_indent(self):
        blk = ('\t\t\t<material name="evemate_a" shader="P1_complex_surface.fx" blendmode="NONE" preview="none">\n'
               '\t\t\t\t<properties>\n'
               '\t\t\t\t\t<property type="Float" name="Smoothness" value="0.2"/>\n'
               '\t\t\t\t</properties>\n'
               '\t\t\t</material>')
        nb, ok = server._ml_set_block_prop(blk, "Float", "Metallness", "1.0")
        self.assertTrue(ok)
        lines = nb.split("\n")
        self.assertTrue(self._has(lines, '\t\t\t\t\t<property type="Float" name="Metallness" value="1.0" />'))
        self.assertTrue(self._has(lines, '\t\t\t\t</properties>'))


class MaterialAlignTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="x4sb_align_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.lib = os.path.join(self.tmp, "libraries", "material_library.xml")
        os.makedirs(os.path.dirname(self.lib))
        self._old = server._ml_files_loadorder
        server._ml_files_loadorder = lambda: [self.lib]
        self.addCleanup(setattr, server, "_ml_files_loadorder", self._old)
        self.comp = os.path.join(self.tmp, "assets", "units", "size_l", "ship_x.xml")

    def _write(self, path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def test_align_adds_missing_keeps_existing(self):
        self._write(self.lib, _lib(("evemate_a", "0.2"), ("evemate_b", "0.3")))
        self._write(self.comp, _comp(["megathron.evemate_a", "megathron.evemate_c"]))
        res = server.align_materials_after_sync(self.tmp, self.comp, _comp(["megathron.evemate_a"]))
        self.assertTrue(res["ok"])
        self.assertEqual(res["added"], ["megathron.evemate_c"])
        libtxt = open(self.lib, encoding="utf-8").read()
        self.assertIn('<material name="evemate_c"', libtxt)
        self.assertIn('<material name="evemate_b"', libtxt)   # 不删除已有材质
        # 克隆数据来自新船 xml 中第一个已存在的 evemate_a
        self.assertEqual(libtxt.count('name="Smoothness" value="0.2"'), 2)

    def test_align_all_exist_no_change(self):
        self._write(self.lib, _lib(("evemate_a", "0.2")))
        before = open(self.lib, encoding="utf-8").read()
        self._write(self.comp, _comp(["megathron.evemate_a"]))
        res = server.align_materials_after_sync(self.tmp, self.comp, "")
        self.assertEqual(res["added"], [])
        self.assertEqual(open(self.lib, encoding="utf-8").read(), before)

    def test_align_falls_back_to_old_ship(self):
        self._write(self.lib, _lib(("evemate_a", "0.7"), coll="megathron"))
        self._write(self.comp, _comp(["revelation.evemate_a"]))
        res = server.align_materials_after_sync(self.tmp, self.comp, _comp(["megathron.evemate_a"]))
        self.assertEqual(res["added"], ["revelation.evemate_a"])
        libtxt = open(self.lib, encoding="utf-8").read()
        self.assertIn('<collection name="revelation">', libtxt)
        self.assertIn('name="Smoothness" value="0.7"', libtxt)


if __name__ == "__main__":
    unittest.main()
