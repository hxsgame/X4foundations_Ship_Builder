# -*- coding: utf-8 -*-
"""数据源表 / 引用注册表闭环校验。

约束来源见 data_sources.py 顶部说明；本文件只做"是否闭环"的断言：
路由 ↔ 注册表一一对应、前端无未注册调用、每个 API 有源、每个源有引用。
"""
import ast
import os
import re
import sys
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import data_sources as DS

SERVER = os.path.join(BASE, "server.py")
INDEX = os.path.join(BASE, "index.html")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _parse_routes():
    """从 server.py 解析真实路由：_GET_EXACT / _GET_PREFIX / do_POST 白名单。"""
    tree = ast.parse(_read(SERVER))
    exact, prefix, post = set(), [], set()
    for node in tree.body:
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1):
            continue
        tgt = node.targets[0]
        if not isinstance(tgt, ast.Name):
            continue
        if tgt.id == "_GET_EXACT" and isinstance(node.value, ast.Dict):
            exact = {k.value for k in node.value.keys if isinstance(k, ast.Constant)}
        elif tgt.id == "_GET_PREFIX" and isinstance(node.value, ast.Tuple):
            for elt in node.value.elts:
                if isinstance(elt, ast.Tuple) and elt.elts and isinstance(elt.elts[0], ast.Constant):
                    prefix.append(elt.elts[0].value)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "do_POST":
            for sub in ast.walk(node):
                if not isinstance(sub, ast.Compare):
                    continue
                for comp in sub.comparators:
                    if not isinstance(comp, ast.Tuple):
                        continue
                    vals = [e.value for e in comp.elts
                            if isinstance(e, ast.Constant) and isinstance(e.value, str)
                            and e.value.startswith("/api/")]
                    if len(vals) >= 5:      # POST 白名单 tuple
                        post.update(vals)
    return exact, prefix, post


def _by(method):
    return {p: m for p, m in DS.APIS.items() if method in (m.get("m") or "")}


class DataSourceRegistryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.get_exact, cls.get_prefix, cls.post = _parse_routes()

    # —— 1. 路由 ↔ 注册表 ——
    def test_get_exact_parity(self):
        reg = {p for p, m in _by("GET").items() if m.get("match") == "exact"}
        self.assertEqual(reg, self.get_exact)

    def test_get_prefix_parity_and_order(self):
        reg = [p for p, m in _by("GET").items() if m.get("match") == "prefix"]
        self.assertEqual(reg, self.get_prefix,
                         "前缀注册顺序必须与 server.py 一致，否则匹配结果会变")

    def test_post_parity(self):
        reg = set(_by("POST"))
        self.assertEqual(reg, self.post)

    # —— 2. 引用完整性 ——
    def test_every_api_declares_sources(self):
        for path, meta in DS.APIS.items():
            self.assertTrue(meta.get("src"), "%s 未声明数据源" % path)

    def test_sources_exist_and_no_orphan(self):
        refs = DS.api_refs()
        for path, meta in DS.APIS.items():
            for sid in meta.get("src") or []:
                self.assertIn(sid, DS.SOURCES, "%s 引用了未注册数据源 %s" % (path, sid))
        for sid in DS.SOURCES:
            self.assertTrue(refs.get(sid), "%s 无任何 API 引用（孤儿源）" % sid)

    def test_template_vars_known(self):
        for sid, meta in DS.SOURCES.items():
            for var in re.findall(r"\{([A-Z_]+)\}", meta.get("path") or ""):
                self.assertIn(var, DS.ENV_KEYS, "%s 使用了未定义变量 {%s}" % (sid, var))

    # —— 3. 前端无未注册调用 ——
    def test_frontend_fetches_registered(self):
        text = _read(INDEX)
        calls = set(re.findall(r"fetch\(\s*[\"'`](/api/[^\"'`?\s]*)", text))
        # index.html 唯一动态拼接：fetch("/api/"+ep)，ep ∈ 下面四个端点（已注册）
        calls.discard("/api/")
        self.assertTrue(calls, "未在 index.html 找到 fetch 调用？")
        for path in sorted(calls):
            hit, _meta = DS.match_api(path)
            self.assertIsNotNone(hit, "前端调用了未注册接口：%s" % path)
        for name in ("bulletedit", "bulletgenerate", "equipedit", "equipgenerate"):
            self.assertIn("/api/" + name, DS.APIS, "动态拼接端点未注册：%s" % name)

    # —— 4. 运行时自检 ——
    def test_check_clean_with_base_env(self):
        rep = DS.check({"BASE": BASE, "CACHE_DIR": os.path.join(BASE, "cache")})
        self.assertTrue(rep["ok"], "\n".join(rep["problems"]))
        self.assertEqual(len(rep["sources"]), len(DS.SOURCES))

    def test_optional_missing_is_warning_not_problem(self):
        """可选源已配置但路径写错：只进 warnings，不影响 ok。"""
        env = {"BASE": BASE, "CACHE_DIR": os.path.join(BASE, "cache"),
               "ROOT": r"Z:\__missing_root__", "MOD_DIR": r"Z:\__missing_mod__"}
        rep = DS.check(env)
        self.assertTrue(rep["ok"], "\n".join(rep["problems"]))
        warned = " ".join(rep["warnings"])
        for sid in ("x4.units", "x4.libraries", "mod.assets"):
            self.assertIn(sid, warned)
        self.assertTrue(all("不存在" in w for w in rep["warnings"]))

    def test_unconfigured_optional_source_is_silent(self):
        """变量没配（ROOT 为空）= 未启用，不进 warnings。"""
        rep = DS.check({"BASE": BASE, "CACHE_DIR": os.path.join(BASE, "cache")})
        self.assertTrue(rep["ok"], "\n".join(rep["problems"]))
        self.assertEqual(rep["warnings"], [])

    def test_required_missing_is_problem(self):
        """非可选源路径不存在：必须进 problems 并使 ok=False。"""
        rep = DS.check({"BASE": r"Z:\__no_such_base__"})
        self.assertFalse(rep["ok"])
        self.assertTrue(any("app.code" in p for p in rep["problems"]))

    def test_check_survives_non_str_env(self):
        """env 里混入 None/int/bytes 不得抛异常（配置文件脏数据防崩）。"""
        rep = DS.check({"BASE": 123, "ROOT": None, "MOD_DIR": 4.5, "CACHE_DIR": b"bytes"})
        self.assertIn("problems", rep)
        self.assertIn("warnings", rep)
        for row in rep["sources"]:
            self.assertIsInstance(row["resolved"], str)

    def test_markdown_export(self):
        md = DS.md()
        self.assertIn("## 一、数据源表", md)
        self.assertIn("## 二、引用注册表", md)
        for sid in DS.SOURCES:
            self.assertIn("`%s`" % sid, md)


if __name__ == "__main__":
    unittest.main()
