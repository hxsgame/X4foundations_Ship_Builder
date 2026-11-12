# -*- coding: utf-8 -*-
"""shipgroup 读取 / 写入 / ships.xml 归属的回归测试。"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server


def _w(p, s):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w", encoding="utf-8").write(s)


class ShipgroupViewTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="x4sb_sg_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.addCleanup(setattr, server, "ROOT", server.ROOT)
        self.addCleanup(setattr, server, "_ext_order", server._ext_order)
        server.ROOT = self.tmp
        server._ext_order = lambda: ["extA"]

    def test_merge_add_and_append(self):
        """diff 追加要能读到；追加块里的畸形 <group> 不应被当成新分组。"""
        _w(os.path.join(self.tmp, "libraries", "shipgroups.xml"),
           '<groups>\n<group name="vanilla_g">\n'
           '<select macro="ship_a_macro" weight="100"/>\n'
           '</group>\n</groups>\n')
        _w(os.path.join(self.tmp, "extensions", "extA", "libraries", "shipgroups.xml"),
           server.DIFF_HEADER +
           '\t<add sel="//groups"><group name="new_g"><select macro="ship_b_macro" weight="30"/></group></add>\n'
           '\t<add sel="//groups/group[@name=\'vanilla_g\']"><select macro="ship_c_macro" weight="40"/></add>\n'
           '\t<add sel="//groups/group[@name=\'ghost_g\']"><group name="ghost_g">'
           '<select macro="ship_d_macro" weight="10"/></group></add>\n'
           '</diff>\n')
        g = server._shipgroups()
        self.assertEqual({m for m, _ in g["vanilla_g"]["selects"]},
                         {"ship_a_macro", "ship_c_macro"})
        self.assertEqual(g["new_g"]["source"], "extA")
        self.assertIn("ship_b_macro", {m for m, _ in g["new_g"]["selects"]})
        self.assertNotIn("ghost_g", g)

    def test_strip_is_precise(self):
        """只删本船 select；块内还有别的船就保留，删空才整块移除。"""
        txt = ('<diff>\n'
               '\t<add sel="//groups/group[@name=\'g\']">\n'
               '\t\t<select macro="ship_x_macro" weight="10"/>\n'
               '\t\t<select macro="ship_y_macro" weight="20"/>\n'
               '\t</add>\n'
               '\t<add sel="//groups/group[@name=\'h\']">\n'
               '\t\t<select macro="ship_x_macro" weight="10"/>\n'
               '\t</add>\n'
               '\t<add sel="//groups/group[@name=\'e\']">\n\t</add>\n'
               '</diff>\n')
        out = server._sg_clean_empty(server._sg_strip_ship(txt, "ship_x_macro"))
        self.assertIn("ship_y_macro", out)
        self.assertIn("group[@name='g']", out)
        self.assertNotIn("group[@name='h']", out)
        self.assertNotIn('<select macro="ship_x_macro"', out)
        self.assertNotIn("group[@name='e']", out)

    def test_clear_removes_only_this_ship(self):
        """关闭 ⑥-1 / 删除船：只清本船 select 与 ships 条目，别的船保留。"""
        mod = os.path.join(self.tmp, "mod")
        server.shipgroup_save_all(
            mod, "ship_test",
            {"enabled": True, "groups": [{"group": "g1", "weight": "50"}]},
            faction="paranid", size="xl")
        sjp = os.path.join(mod, "libraries", "shipgroups.xml")
        txt = open(sjp, encoding="utf-8").read().replace(
            "</diff>",
            '\t<add sel="//groups"><group name="g2">'
            '<select macro="other_macro" weight="10"/></group></add>\n</diff>\n')
        _w(sjp, txt)
        rel = server.shipgroup_clear(mod, "ship_test")
        self.assertIn("libraries\\shipgroups.xml", rel)
        sj = open(sjp, encoding="utf-8").read()
        self.assertNotIn("ship_test_macro", sj)
        self.assertIn("other_macro", sj)
        sx = open(os.path.join(mod, "libraries", "ships.xml"), encoding="utf-8").read()
        self.assertNotIn('"ship_test"', sx)

    def test_clear_keeps_reserved_eve_group(self):
        """UP7_EVE_* 命名组被 ships.xml 按名引用，清空最后一艘船时只留外壳不删组。"""
        mod = os.path.join(self.tmp, "mod")
        _w(os.path.join(mod, "libraries", "shipgroups.xml"),
           server.DIFF_HEADER +
           '\t<add sel="//groups"><group name="UP7_EVE_battleship_xl_01">'
           '<select macro="ship_test_macro" weight="20"/></group></add>\n</diff>\n')
        server.shipgroup_clear(mod, "ship_test")
        sj = open(os.path.join(mod, "libraries", "shipgroups.xml"), encoding="utf-8").read()
        self.assertIn('group name="UP7_EVE_battleship_xl_01"', sj)
        self.assertNotIn('select macro="ship_test_macro"', sj)

    def test_ships_xml_only_current_ship(self):
        """ships.xml 只动本船 id 的条目，其它船条目保持不变。"""
        mod = os.path.join(self.tmp, "mod")
        _w(os.path.join(mod, "libraries", "ships.xml"),
           server.DIFF_HEADER + '\t<add sel="//ships">\n'
           '\t\t<ship id="other" group="g0"><category tags="[military]" '
           'faction="[argon]" size="ship_l"/></ship>\n'
           '\t</add>\n</diff>\n')
        rel = server.shipgroup_save_all(
            mod, "ship_test",
            {"enabled": True, "groups": [{"group": "g1", "weight": "50"},
                                        {"group": "g2", "weight": "80"}]},
            faction="paranid", size="xl", extra_factions=["argon"])
        self.assertIn("libraries\\shipgroups.xml", rel)
        sx = open(os.path.join(mod, "libraries", "ships.xml"), encoding="utf-8").read()
        self.assertIn('<ship id="other" group="g0">', sx)
        self.assertIn('<ship id="ship_test" group="g1">', sx)
        self.assertIn('<ship id="ship_test__g2" group="g2">', sx)
        self.assertIn('faction="[paranid,argon]"', sx)
        self.assertIn('size="ship_xl"', sx)
        # 再次保存只留 g1：本船 g2 条目消失，其它船条目保留，shipgroups 不重复
        server.shipgroup_save_all(
            mod, "ship_test",
            {"enabled": True, "groups": [{"group": "g1", "weight": "60"}]},
            faction="paranid", size="xl")
        sx = open(os.path.join(mod, "libraries", "ships.xml"), encoding="utf-8").read()
        self.assertIn('<ship id="other" group="g0">', sx)
        self.assertIn('<ship id="ship_test" group="g1">', sx)
        self.assertNotIn('<ship id="ship_test__g2"', sx)
        sj = open(os.path.join(mod, "libraries", "shipgroups.xml"), encoding="utf-8").read()
        self.assertEqual(sj.count('macro="ship_test_macro"'), 1)


if __name__ == "__main__":
    unittest.main()
