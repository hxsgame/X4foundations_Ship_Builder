# -*- coding: utf-8 -*-
"""特效写入收敛：upsert_effect 的新建 / 追加 / 同名替换。"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server


class UpsertEffectTest(unittest.TestCase):
    def setUp(self):
        self.mod = tempfile.mkdtemp(prefix="x4sb_fx_")
        self.addCleanup(shutil.rmtree, self.mod, True)

    def _read(self):
        return open(os.path.join(self.mod, "libraries", "effects.xml"), encoding="utf-8").read()

    def test_create_and_append(self):
        p1 = server.upsert_effect(self.mod, '<effect name="a"><parameters/></effect>')
        self.assertEqual(p1, os.path.join("libraries", "effects.xml"))
        t = self._read()
        self.assertIn('<add sel="//effects">', t)
        self.assertIn('name="a"', t)
        server.upsert_effect(self.mod, '<effect name="b"><parameters/></effect>')
        t = self._read()
        self.assertIn('name="a"', t)
        self.assertIn('name="b"', t)

    def test_update_same_name(self):
        server.upsert_effect(self.mod, '<effect name="a" width="1"><parameters/></effect>')
        server.upsert_effect(self.mod, '<effect name="a" width="2"><parameters/></effect>',
                             name="a")
        t = self._read()
        self.assertEqual(t.count('name="a"'), 1)
        self.assertIn('width="2"', t)

    def test_custom_filename(self):
        p = server.upsert_effect(self.mod, '<effect name="tr"/>', "trail_effects.xml")
        self.assertEqual(p, os.path.join("libraries", "trail_effects.xml"))
        self.assertTrue(os.path.isfile(os.path.join(self.mod, "libraries", "trail_effects.xml")))


if __name__ == "__main__":
    unittest.main()
