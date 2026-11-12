# -*- coding: utf-8 -*-
"""缓存分组失效：lists/content/scan 三组互不越界。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server


class CacheGroupsTest(unittest.TestCase):
    def setUp(self):
        self._saved = {k: v for k, v in vars(server).items()
                       if k in ("_TEMPLATES_CACHE", "_COMPCACHE", "_EQ_SCAN_CACHE", "_WARES_DIRTY")}
        self._comp = dict(server._COMPCACHE)
        self.addCleanup(self._restore)

    def _restore(self):
        server._TEMPLATES_CACHE = self._saved["_TEMPLATES_CACHE"]
        server._EQ_SCAN_CACHE = self._saved["_EQ_SCAN_CACHE"]
        server._WARES_DIRTY = self._saved["_WARES_DIRTY"]
        server._COMPCACHE.clear()
        server._COMPCACHE.update(self._comp)

    def test_lists_and_content_do_not_touch_scan(self):
        server._TEMPLATES_CACHE = ["stale"]
        server._COMPCACHE["a"] = "x"
        server._EQ_SCAN_CACHE = {"k": 1}
        server._WARES_DIRTY = False
        server.invalidate_caches("lists", "content")
        self.assertIsNone(server._TEMPLATES_CACHE)
        self.assertEqual(server._COMPCACHE, {})
        self.assertTrue(server._WARES_DIRTY)
        self.assertEqual(server._EQ_SCAN_CACHE, {"k": 1})

    def test_scan_group_clears_scan_caches(self):
        server._EQ_SCAN_CACHE = {"k": 1}
        server.invalidate_caches("scan")
        self.assertIsNone(server._EQ_SCAN_CACHE)


if __name__ == "__main__":
    unittest.main()
