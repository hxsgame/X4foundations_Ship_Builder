# -*- coding: utf-8 -*-
"""R6 舰船结构校验（lint_ship_texts）单元测试。

覆盖：兼容标签越界（致命）、删标签后放行、组结构警告、macro 悬空引用、loadout 槽位缺失。
不依赖 X4 安装目录（纯文本函数）。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server  # noqa: E402


def _comp(conns):
    body = "\n".join('<connection name="%s" tags="%s"%s/>'
                     % (n, t, (' group="%s"' % g) if g else "")
                     for n, t, g in conns)
    return ('<?xml version="1.0"?>\n<components>\n'
            '<component name="ship_test" class="ship_xl">\n<connections>\n%s\n'
            '</connections>\n</component>\n</components>\n' % body)


BAD = _comp([
    ("con_t1", "turret extralarge standard advanced highpower missile boron", "left_g_01"),
    ("con_s1", "shield standard", "left_g_01"),
    ("con_t2", "turret large standard", "right_g_01"),
    ("con_e1", "engine standard", "eng_g_01"),
])

GOOD = _comp([
    ("con_t1", "turret extralarge standard advanced", "left_g_01"),
    ("con_s1", "shield standard", "left_g_01"),
    ("con_t2", "turret large standard", "right_g_01"),
    ("con_e1", "engine standard", "eng_g_01"),
])


class LintTest(unittest.TestCase):
    def test_compat_overflow_detected(self):
        """5 个兼容标签 vs 3 个升级组 → 致命错误（revelation 崩溃模型）。"""
        r = server.lint_ship_texts("ship_test", "xl", BAD)
        codes = [e["code"] for e in r["errors"]]
        self.assertIn("E_COMPAT_OVERFLOW", codes)
        self.assertFalse(r["ok"])
        self.assertEqual(r["stats"]["groups"], 3)
        self.assertEqual(r["stats"]["max_compat"], 5)

    def test_compat_ok_after_tag_removal(self):
        """删到 2 个兼容标签后 2 < 3，不再越界。"""
        r = server.lint_ship_texts("ship_test", "xl", GOOD)
        self.assertNotIn("E_COMPAT_OVERFLOW", [e["code"] for e in r["errors"]])
        self.assertTrue(r["ok"])
        self.assertEqual(r["stats"]["max_compat"], 2)

    def test_group_only_turret_warning(self):
        r = server.lint_ship_texts("ship_test", "xl", GOOD)
        msgs = [w["code"] for w in r["warnings"]]
        self.assertIn("W_GROUP_ONLY_TURRET", msgs)   # right_g_01 只有炮塔

    def test_engine_group_without_shield_warning(self):
        r = server.lint_ship_texts("ship_test", "xl", GOOD)
        self.assertIn("W_ENGINE_NO_SHIELD", [w["code"] for w in r["warnings"]])

    def test_dangling_macro_ref(self):
        mac = ('<macros><macro name="ship_test_macro"><connections>'
               '<connection ref="con_missing"/></connections></macro></macros>')
        r = server.lint_ship_texts("ship_test", "xl", GOOD, mac)
        self.assertIn("E_DANGLING_REF", [e["code"] for e in r["errors"]])
        self.assertFalse(r["ok"])

    def test_loadout_path_warning(self):
        mac = ('<macros><macro name="ship_test_macro"><connections>'
               '<connection ref="con_t1"/></connections>'
               '<loadout id="default"><turret macro="turret_x" path="../con_nope"/></loadout>'
               '</macro></macros>')
        r = server.lint_ship_texts("ship_test", "xl", GOOD, mac)
        self.assertIn("W_LOADOUT_PATH", [w["code"] for w in r["warnings"]])
        self.assertTrue(r["ok"])   # 槽位缺失只是警告，不阻断

    def test_geometry_size_mismatch_warning(self):
        txt = _comp([("con_e1", "engine standard", "eng_g_01")]).replace(
            "</component>",
            '<source geometry="extensions/up7/assets/units/size_l/con_e1_data/geo" '
            'index="0"/></component>')
        r = server.lint_ship_texts("ship_test", "xl", txt)
        self.assertIn("W_GEO_SIZE_MISMATCH", [w["code"] for w in r["warnings"]])


if __name__ == "__main__":
    unittest.main()
