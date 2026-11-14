# -*- coding: utf-8 -*-
"""server.py 静态完整性：调用了却从未定义/导入的名字（NameError 类死代码）。

背景：2026-11-14 全量路由探测发现 /api/traileffect 断连，根因是
_find_trail_effect 的 def 行丢失，函数体成了上一个函数的不可达尾段，
三处调用全部 NameError。本测试防止同类问题复发。
"""
import ast
import builtins
import os
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(BASE, "server.py")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _undefined_calls(tree):
    """模块内被调用、但既非定义也非导入也非内置的名字。"""
    defined = set(dir(builtins)) | {"__file__", "__name__", "__doc__"}
    called = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(n.name)
        elif isinstance(n, ast.arg):
            defined.add(n.arg)
        elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            defined.add(n.id)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                defined.add((a.asname or a.name).split(".")[0])
        elif isinstance(n, ast.ExceptHandler) and n.name:
            defined.add(n.name)
        elif isinstance(n, (ast.Global, ast.Nonlocal)):
            defined.update(n.names)
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
            called.add(n.func.id)
    return sorted(called - defined)


class ServerStaticNameTest(unittest.TestCase):
    def test_no_undefined_calls(self):
        bad = _undefined_calls(ast.parse(_read(SERVER)))
        self.assertEqual(bad, [], "调用了但未定义的名字：%s" % bad)

    def test_registered_handlers_exist(self):
        """_GET_EXACT / _GET_PREFIX 里引用的 handler 必须是已定义函数。"""
        tree = ast.parse(_read(SERVER))
        handlers = set()
        for node in tree.body:
            if not (isinstance(node, ast.Assign) and len(node.targets) == 1):
                continue
            tgt = node.targets[0]
            if not isinstance(tgt, ast.Name):
                continue
            if tgt.id == "_GET_EXACT" and isinstance(node.value, ast.Dict):
                handlers |= {v.id for v in node.value.values if isinstance(v, ast.Name)}
            elif tgt.id == "_GET_PREFIX" and isinstance(node.value, ast.Tuple):
                for elt in node.value.elts:
                    if (isinstance(elt, ast.Tuple) and len(elt.elts) >= 2
                            and isinstance(elt.elts[1], ast.Name)):
                        handlers.add(elt.elts[1].id)
        self.assertTrue(handlers)
        defined = {n.name for n in tree.body
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        missing = sorted(h for h in handlers if h not in defined)
        self.assertEqual(missing, [], "路由引用了未定义的 handler：%s" % missing)


if __name__ == "__main__":
    unittest.main()
