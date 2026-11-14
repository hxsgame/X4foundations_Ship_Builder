# -*- coding: utf-8 -*-
"""数据源表 + 引用注册表（唯一事实源）
====================================
工程里"数据从哪来、谁在引用"只在本文件回答一次，其余文档/接口都引用它。

三层结构
--------
1. SOURCES：数据源表。每个外部/内部数据源一行（id → 路径模板、读写模式、是否可选）。
2. APIS：引用注册表。每个后端路由一行（路径 → 方法、匹配方式、引用的数据源 id）。
3. check()：运行时自检。把路径模板按当前配置展开，报告存在性 + 反向引用。

闭环约束（tests/test_data_sources.py 自动校验）
--------------------------------------------
- 前端 index.html 里所有 fetch("/api/...") 必须在 APIS 有登记；
- server.py 的真实路由（_GET_EXACT / _GET_PREFIX / do_POST 白名单）必须与 APIS 一一对应；
- 每个 API 至少引用一个数据源；
- 每个数据源至少被一个 API 引用（无孤儿源）；
- 路径模板里的 {VAR} 只能是 ENV_KEYS 中的键。

新增数据源类型 / 新增引用时
--------------------------
1. 在 SOURCES 加源（或改已有源）；
2. 在 APIS 给相关路由补 src；
3. `python data_sources.py` 自检 → `python data_sources.py --md` 重生成 docs/DATA_SOURCES.md；
4. `python -m unittest tests.test_data_sources`。
"""

import re

# 路径模板可用的变量（由 server.py 运行时传入；GAME/EXPORT_ROOT 为请求参数）
ENV_KEYS = ("BASE", "ROOT", "MOD_DIR", "BACKUP_ROOT", "CACHE_DIR",
            "XRCATTOOL", "GAME", "EXPORT_ROOT")

# ---------------------------------------------------------------------------
# 一、数据源表
#   kind  file/dir/glob   → 真实路径（按 path 展开）
#         const/mem       → 代码内常量 / 运行时内存（无路径）
#         fs              → 任意文件系统路径（浏览/用户选择，路径来自请求）
#         request         → 路径来自请求参数，无固定模板
#   mode  r 只读 / rw 读写
#   optional  True = 环境未配置时不视为错误
# ---------------------------------------------------------------------------
SOURCES = {
    # —— 工程内（随工具分发）——
    "app.code": {
        "kind": "file", "path": "{BASE}/data_sources.py", "mode": "r", "optional": False,
        "desc": "本注册表 + server.py，自检接口的自省来源",
    },
    "app.index": {
        "kind": "file", "path": "{BASE}/index.html", "mode": "r", "optional": False,
        "desc": "前端单页，全部呈现数据的唯一入口（只经 /api/* 取数）",
    },
    "app.config": {
        "kind": "file", "path": "{BASE}/builder_config.json", "mode": "rw", "optional": True,
        "desc": "工具配置：解包根 root / 目标 mod / 备份根 / 导出路径",
    },
    "app.cache": {
        "kind": "dir", "path": "{CACHE_DIR}", "mode": "rw", "optional": True,
        "desc": "派生缓存（签名校验，可全删重建）：templates/equip_scan/bullet_*/software/macro_catalog/matrefs 等",
    },
    "app.backup": {
        "kind": "dir", "path": "{BACKUP_ROOT}", "mode": "rw", "optional": True,
        "desc": "覆盖写前的备份根（每文件 .bak 链）",
    },

    # —— X4 解包根（只读）——
    "x4.root": {
        "kind": "dir", "path": "{ROOT}", "mode": "r", "optional": True,
        "desc": "X4 解包根（builder_config.root），未配置时工具只能浏览、不能读数据",
    },
    "x4.assets": {
        "kind": "dir", "path": "{ROOT}/assets", "mode": "r", "optional": True,
        "desc": "原版资产树：units/props/fx/textures（组件、宏、模型、特效、图标）",
    },
    "x4.units": {
        "kind": "dir", "path": "{ROOT}/assets/units", "mode": "r", "optional": True,
        "desc": "原版舰船/组件/宏（size_l、size_xl、props 等）",
    },
    "x4.libraries": {
        "kind": "dir", "path": "{ROOT}/libraries", "mode": "r", "optional": True,
        "desc": "wares/effects/trail_effects/material_library/sound_library/factions/jobs/shipgroups/icons/*.xsd",
    },
    "x4.index": {
        "kind": "dir", "path": "{ROOT}/index", "mode": "r", "optional": True,
        "desc": "components.xml / macros.xml 全局索引（新增条目注册）",
    },
    "x4.t": {
        "kind": "dir", "path": "{ROOT}/t", "mode": "r", "optional": True,
        "desc": "本地化 0001-l086（中文）/0001-l044（英文），名称与描述解析",
    },
    "x4.extensions": {
        "kind": "dir", "path": "{ROOT}/extensions", "mode": "r", "optional": True,
        "desc": "各 mod 的 assets/libraries/index/t 覆盖层（含目标 mod 之外的来源）",
    },

    # —— 目标 mod（读写）——
    "mod.dir": {
        "kind": "dir", "path": "{MOD_DIR}", "mode": "rw", "optional": True,
        "desc": "目标 mod 根（builder_config.target_mod）",
    },
    "mod.assets": {
        "kind": "dir", "path": "{MOD_DIR}/assets", "mode": "rw", "optional": True,
        "desc": "目标 mod 资产（舰船/装备组件与宏、_data 几何）",
    },
    "mod.libraries": {
        "kind": "dir", "path": "{MOD_DIR}/libraries", "mode": "rw", "optional": True,
        "desc": "目标 mod wares/jobs/shipgroups/icons 等库文件",
    },
    "mod.index": {
        "kind": "dir", "path": "{MOD_DIR}/index", "mode": "rw", "optional": True,
        "desc": "目标 mod components.xml / macros.xml",
    },
    "mod.t": {
        "kind": "dir", "path": "{MOD_DIR}/t", "mode": "rw", "optional": True,
        "desc": "目标 mod 本地化 0001-l086（写入舰船/装备名称）",
    },
    "mod.content": {
        "kind": "file", "path": "{MOD_DIR}/content.xml", "mode": "r", "optional": True,
        "desc": "mod 扩展标识（id/name），moddirs 列表用",
    },

    # —— 解包工具链（只读）——
    "tool.xrcattool": {
        "kind": "file", "path": "{XRCATTOOL}", "mode": "r", "optional": True,
        "desc": "官方 XRCatTool.exe，解包时调用",
    },
    "game.cat": {
        "kind": "request", "path": "<请求参数 game>/*.cat", "mode": "r", "optional": True,
        "desc": "基游戏 ##.cat 索引（配对 .dat 为实际数据）",
    },
    "game.staging": {
        "kind": "request", "path": "<请求参数 game>/extensions/vortex.deployment.json", "mode": "r", "optional": True,
        "desc": "Vortex 暂存区路径（未启用 mod 的扫描来源）",
    },

    # —— 文件系统 ——
    "sys.fs": {
        "kind": "fs", "path": "<请求参数>", "mode": "r", "optional": True,
        "desc": "dirtree/pickdir/模型同步导出目录等用户选择路径",
    },

    # —— 代码内常量（硬编码枚举/参考值）——
    "const.factions": {
        "kind": "const", "path": "server.py FACTIONS", "mode": "r", "optional": False,
        "desc": "可选派系枚举（来自 factions.xml + t 中文名）",
    },
    "const.job_tasks": {
        "kind": "const", "path": "server.py JOB_TASKS", "mode": "r", "optional": False,
        "desc": "jobs 任务类型 → order 映射",
    },
    "const.ware_mats": {
        "kind": "const", "path": "server.py WARE_MATS", "mode": "r", "optional": False,
        "desc": "建造材料白名单（wares.xml 校验，缺失才标自定义）",
    },
    "const.prod_methods": {
        "kind": "const", "path": "server.py PROD_METHODS", "mode": "r", "optional": False,
        "desc": "建造方式固定枚举（启动时按 wares.xml 的 production method 扩充）",
    },
    "const.cost_refs": {
        "kind": "const", "path": "server.py COST_REFS", "mode": "r", "optional": False,
        "desc": "L/XL 造价参考值（原版 wares.xml 统计快照）",
    },
    "const.equip_classes": {
        "kind": "const", "path": "server.py EQUIP_CLASSES", "mode": "r", "optional": False,
        "desc": "装备分类规则（按连接 tags 结构，非命名）",
    },

    # —— 运行时内存 ——
    "mem.unpack_task": {
        "kind": "mem", "path": "server.py _UP", "mode": "rw", "optional": False,
        "desc": "解包任务进度/取消标志（进程内）",
    },
}

# ---------------------------------------------------------------------------
# 二、引用注册表（API → 数据源）
#   match: exact / prefix（与 server.py 的 _GET_EXACT / _GET_PREFIX 顺序一致）
#          static = 非 /api 静态兜底（前端单页），不参与路由比对
# ---------------------------------------------------------------------------
_SHIP_R = ["x4.units", "x4.assets", "x4.extensions", "mod.assets", "mod.index"]
_EQUIP_R = ["x4.assets", "x4.units", "x4.libraries", "x4.extensions", "mod.assets", "app.cache"]
_BULLET_R = ["x4.assets", "x4.libraries", "x4.extensions", "mod.assets", "app.cache"]
_BULLET_TPL = ["x4.assets", "x4.libraries", "x4.extensions", "mod.assets"]
_BULLET_W = ["x4.assets", "x4.libraries", "mod.assets", "mod.libraries", "app.backup"]

APIS = {
    "/": {"m": "GET", "match": "static", "src": ["app.index"],
          "desc": "前端单页（非 /api，静态兜底）"},

    # —— 舰船（GET）——
    "/api/templates": {"m": "GET", "match": "exact", "src": _SHIP_R + ["app.cache"],
                       "desc": "舰船模板列表（原版 + 各来源）"},
    "/api/stats": {"m": "GET", "match": "exact", "src": ["x4.assets", "x4.libraries", "x4.extensions"],
                   "desc": "资产统计（模型/材质/贴图计数）"},
    "/api/enums": {"m": "GET", "match": "exact",
                   "src": ["x4.assets", "x4.libraries", "x4.extensions", "const.equip_classes"],
                   "desc": "各类下拉枚举（尺寸/种族/挂载分类等）"},
    "/api/factions": {"m": "GET", "match": "exact",
                      "src": ["x4.libraries", "x4.extensions", "x4.t", "const.factions"],
                      "desc": "派系列表（factions.xml + 中文名）"},
    "/api/costrefs": {"m": "GET", "match": "exact", "src": ["const.cost_refs", "x4.libraries"],
                      "desc": "造价/工时参考值"},
    "/api/shipgroups/all": {"m": "GET", "match": "exact",
                            "src": ["x4.libraries", "x4.extensions", "mod.libraries"],
                            "desc": "全部升级组合并视图"},
    "/api/loadoutmacros": {"m": "GET", "match": "exact", "src": ["x4.units", "mod.assets"],
                           "desc": "内联 loadout 宏清单"},
    "/api/softwarelist": {"m": "GET", "match": "exact",
                          "src": ["x4.libraries", "x4.extensions", "app.cache", "const.ware_mats"],
                          "desc": "软件清单（wares.xml 扫描）"},
    "/api/equiprefs": {"m": "GET", "match": "exact", "src": _EQUIP_R,
                       "desc": "装备引用分组（同类参考）"},
    "/api/moddirs": {"m": "GET", "match": "exact", "src": ["x4.extensions", "mod.content"],
                     "desc": "extensions 下 mod 目录列表"},
    "/api/docklist": {"m": "GET", "match": "exact",
                      "src": ["x4.assets", "x4.extensions", "mod.assets"],
                      "desc": "可复用 dock 模板列表"},
    "/api/config": {"m": "GET+POST", "match": "exact",
                    "src": ["app.config", "x4.root", "mod.dir", "app.backup"],
                    "desc": "读/写工具配置（切换解包根、目标 mod、备份根）"},
    "/api/unpackstatus": {"m": "GET", "match": "exact", "src": ["mem.unpack_task"],
                          "desc": "解包任务进度"},
    "/api/shiplint": {"m": "GET", "match": "exact",
                      "src": ["x4.units", "x4.assets", "x4.index", "mod.assets"],
                      "desc": "舰船结构体检（R6 校验器）"},

    # —— 舰船（GET 前缀）——
    "/api/component": {"m": "GET", "match": "prefix", "src": _SHIP_R + ["app.cache"],
                       "desc": "舰船组件/挂载点读取"},
    "/api/shipmaterials": {"m": "GET", "match": "prefix",
                           "src": ["x4.assets", "x4.units", "x4.libraries", "x4.extensions", "mod.assets"],
                           "desc": "舰船材质引用"},
    "/api/shiploadout": {"m": "GET", "match": "prefix", "src": ["x4.units", "mod.assets", "x4.t"],
                         "desc": "舰船出厂 loadout 回填"},
    "/api/shipjobs": {"m": "GET", "match": "prefix",
                      "src": ["x4.units", "mod.libraries", "const.job_tasks"],
                      "desc": "舰船 jobs 回填"},
    "/api/shipconnections": {"m": "GET", "match": "prefix",
                             "src": ["x4.units", "x4.assets", "mod.assets"],
                             "desc": "挂载连接拓扑"},
    "/api/shipgroups": {"m": "GET", "match": "prefix",
                        "src": ["x4.libraries", "x4.extensions", "mod.libraries"],
                        "desc": "单船升级组"},
    "/api/shipsoftware": {"m": "GET", "match": "prefix",
                          "src": ["x4.libraries", "mod.libraries", "x4.t"],
                          "desc": "舰船软件回填"},

    # —— 装备 / 特效（GET 前缀）——
    "/api/equipkinds": {"m": "GET", "match": "prefix",
                        "src": ["x4.assets", "x4.extensions", "app.cache"],
                        "desc": "装备子类（weapon/turret/missile…）"},
    "/api/equiptemplates": {"m": "GET", "match": "prefix", "src": _EQUIP_R,
                            "desc": "装备模板列表"},
    "/api/equipread": {"m": "GET", "match": "prefix",
                       "src": ["x4.assets", "x4.units", "x4.extensions", "mod.assets", "x4.t"],
                       "desc": "装备详情读取（字段 + 引用回填）"},
    "/api/shieldmatrefs": {"m": "GET", "match": "prefix",
                           "src": ["x4.assets", "x4.libraries", "x4.extensions", "app.cache"],
                           "desc": "护盾材质引用"},
    "/api/equiptags": {"m": "GET", "match": "prefix",
                       "src": ["x4.assets", "x4.extensions", "const.equip_classes"],
                       "desc": "装备挂载标签枚举"},
    "/api/bulletrefs": {"m": "GET", "match": "prefix", "src": _BULLET_R,
                        "desc": "弹丸引用分组"},
    "/api/bulleteffectlist": {"m": "GET", "match": "prefix", "src": _BULLET_R,
                              "desc": "弹丸命中特效列表"},
    "/api/bulleteffectread": {"m": "GET", "match": "prefix", "src": _BULLET_TPL,
                              "desc": "命中特效详情"},
    "/api/bullettraillist": {"m": "GET", "match": "prefix", "src": _BULLET_R,
                             "desc": "弹道拖尾材质列表"},
    "/api/bullettrailread": {"m": "GET", "match": "prefix", "src": _BULLET_TPL,
                             "desc": "拖尾详情"},
    "/api/bulletbeamlist": {"m": "GET", "match": "prefix", "src": _BULLET_R,
                            "desc": "光束材质列表"},
    "/api/bulletbeamread": {"m": "GET", "match": "prefix", "src": _BULLET_TPL,
                            "desc": "光束详情"},
    "/api/bulletvisread": {"m": "GET", "match": "prefix", "src": _BULLET_TPL,
                           "desc": "弹丸视觉详情"},
    "/api/bulletvislist": {"m": "GET", "match": "prefix", "src": _BULLET_R,
                           "desc": "弹丸视觉材质列表"},
    "/api/bulletvisrefs": {"m": "GET", "match": "prefix", "src": _BULLET_R,
                           "desc": "弹丸视觉引用分组"},
    "/api/equipnumrefs": {"m": "GET", "match": "prefix", "src": _EQUIP_R,
                          "desc": "装备数值引用（伤害/转速等）"},
    "/api/missileusers": {"m": "GET", "match": "prefix",
                          "src": ["x4.units", "x4.assets", "x4.extensions"],
                          "desc": "使用该导弹的舰船/发射器"},
    "/api/explosionusers": {"m": "GET", "match": "prefix",
                            "src": ["x4.units", "x4.assets", "x4.libraries"],
                            "desc": "使用该爆炸特效的舰船"},
    "/api/missiletags": {"m": "GET", "match": "prefix", "src": ["x4.assets", "x4.libraries"],
                         "desc": "导弹兼容标签"},
    "/api/trailrefs": {"m": "GET", "match": "prefix", "src": ["x4.assets", "x4.libraries"],
                       "desc": "拖尾引用分组"},
    "/api/explosionrefs": {"m": "GET", "match": "prefix", "src": ["x4.assets", "x4.libraries"],
                           "desc": "爆炸引用分组"},
    "/api/explosioneffects": {"m": "GET", "match": "prefix", "src": ["x4.assets", "x4.libraries"],
                              "desc": "爆炸特效列表"},
    "/api/trailmaterials": {"m": "GET", "match": "prefix", "src": ["x4.libraries", "x4.assets"],
                            "desc": "拖尾材质列表"},
    "/api/traileffect": {"m": "GET", "match": "prefix", "src": ["x4.assets", "x4.libraries"],
                         "desc": "拖尾效果详情"},
    "/api/eqgeom": {"m": "GET", "match": "prefix",
                    "src": ["x4.assets", "x4.extensions", "mod.assets"],
                    "desc": "装备几何（模型路径/包围盒）"},
    "/api/equipchain": {"m": "GET", "match": "prefix",
                        "src": ["x4.assets", "x4.units", "x4.extensions", "mod.assets"],
                        "desc": "装备完整引用链（宏→组件→物品→模型）"},

    # —— 解包 / Diff / Schema（GET 前缀）——
    "/api/unpackscan": {"m": "GET", "match": "prefix",
                        "src": ["x4.root", "x4.extensions", "tool.xrcattool", "game.cat",
                                "game.staging", "sys.fs"],
                        "desc": "扫描可解包来源（基游戏/mod/创意工坊/暂存区）"},
    "/api/diffvalidate": {"m": "GET+POST", "match": "prefix",
                          "src": ["mod.assets", "x4.assets", "x4.units"],
                          "desc": "diff 补丁校验（GET 预览校验 / POST 落盘前校验）"},
    "/api/schemas": {"m": "GET", "match": "prefix", "src": ["x4.libraries", "x4.extensions"],
                     "desc": "XSD 类型定义聚合"},
    "/api/difflist": {"m": "GET", "match": "prefix", "src": ["mod.dir"],
                      "desc": "mod 内 diff 文件列表"},
    "/api/diffpreview": {"m": "GET", "match": "prefix",
                         "src": ["mod.dir", "x4.assets", "x4.units"],
                         "desc": "diff 应用预览（对比 base 组件）"},

    # —— 自检 ——
    "/api/sources": {"m": "GET", "match": "exact", "src": ["app.code", "app.config", "app.cache"],
                     "desc": "数据源表 + 引用注册表自检（存在性/反向引用/问题）"},

    # —— 写操作（POST）——
    "/api/generate": {"m": "POST", "match": "exact",
                      "src": ["x4.units", "x4.assets", "x4.index", "x4.libraries", "x4.t",
                              "mod.assets", "mod.index", "mod.libraries", "mod.t", "app.backup",
                              "const.factions", "const.job_tasks", "const.ware_mats", "const.prod_methods"],
                      "desc": "生成新舰船（全套 XML + 名称 + index）"},
    "/api/edit": {"m": "POST", "match": "exact",
                  "src": ["x4.units", "x4.libraries", "x4.t", "mod.assets", "mod.libraries",
                          "mod.index", "app.backup"],
                  "desc": "编辑已部署舰船"},
    "/api/equipgenerate": {"m": "POST", "match": "exact",
                           "src": ["x4.assets", "x4.units", "x4.libraries", "x4.index", "x4.t",
                                   "x4.extensions", "mod.assets", "mod.libraries", "mod.index",
                                   "mod.t", "app.backup"],
                           "desc": "生成装备（含 L/XL 跨尺寸复制）"},
    "/api/equipedit": {"m": "POST", "match": "exact",
                       "src": ["x4.assets", "x4.units", "x4.libraries", "x4.t", "mod.assets",
                               "mod.libraries", "mod.index", "app.backup"],
                       "desc": "编辑装备"},
    "/api/bulletgenerate": {"m": "POST", "match": "exact", "src": _BULLET_W,
                            "desc": "生成弹丸/弹药"},
    "/api/bulletedit": {"m": "POST", "match": "exact", "src": _BULLET_W,
                        "desc": "编辑弹丸/弹药"},
    "/api/shipmodelsync": {"m": "POST", "match": "exact",
                           "src": ["x4.assets", "mod.assets", "sys.fs"],
                           "desc": "从 Blender 导出目录同步舰船模型"},
    "/api/componentassemble": {"m": "POST", "match": "exact",
                               "src": ["x4.assets", "mod.assets", "app.backup"],
                               "desc": "组件装配（缩放复用 ego 导出）"},
    "/api/dockclone": {"m": "POST", "match": "exact",
                       "src": ["x4.assets", "mod.assets", "sys.fs"],
                       "desc": "dock 组件克隆"},
    "/api/explosionbuild": {"m": "POST", "match": "exact", "src": _BULLET_W,
                            "desc": "构建爆炸特效"},
    "/api/trailnew": {"m": "POST", "match": "exact", "src": _BULLET_W,
                      "desc": "新建拖尾材质"},
    "/api/bulleteffectbuild": {"m": "POST", "match": "exact", "src": _BULLET_W,
                               "desc": "构建命中特效"},
    "/api/bullettrailbuild": {"m": "POST", "match": "exact", "src": _BULLET_W,
                              "desc": "构建弹道拖尾"},
    "/api/bulletbeambuild": {"m": "POST", "match": "exact", "src": _BULLET_W,
                             "desc": "构建光束"},
    "/api/bulletvisbuild": {"m": "POST", "match": "exact", "src": _BULLET_W,
                            "desc": "构建弹丸视觉"},
    "/api/delitem": {"m": "POST", "match": "exact",
                     "src": ["mod.assets", "mod.libraries", "mod.index", "app.backup"],
                     "desc": "删除 mod 内条目"},
    "/api/unpack": {"m": "POST", "match": "exact",
                    "src": ["game.cat", "game.staging", "tool.xrcattool", "app.config", "sys.fs"],
                    "desc": "后台解包（cat/mod/暂存区）"},
    "/api/unpackcancel": {"m": "POST", "match": "exact", "src": ["mem.unpack_task"],
                          "desc": "取消解包"},
    "/api/refresh": {"m": "POST", "match": "exact", "src": ["app.cache"],
                     "desc": "清空派生缓存"},
    "/api/dirtree": {"m": "POST", "match": "exact", "src": ["sys.fs"],
                     "desc": "目录树浏览"},
    "/api/pickdir": {"m": "POST", "match": "exact", "src": ["sys.fs"],
                     "desc": "系统目录选择"},
}


# ---------------------------------------------------------------------------
# 三、自检 / 导出
# ---------------------------------------------------------------------------
def resolve_path(pat, env):
    """展开路径模板；返回 (展开结果, 是否仍有未配置变量)。"""
    missing = []

    def sub(m):
        k = m.group(1)
        v = (env or {}).get(k)
        if v is None or v == "":
            missing.append(k)
            return ""
        return str(v)

    out = re.sub(r"\{([A-Z_]+)\}", sub, pat or "")
    return out, sorted(set(missing))


def _exists(kind, path):
    import glob as _glob
    import os
    if kind in ("const", "mem", "fs", "request"):
        return None
    if not path:
        return False
    if kind == "glob":
        return bool(_glob.glob(path))
    if kind == "file":
        return os.path.isfile(path)
    return os.path.isdir(path)


def api_refs():
    """源 id → 引用它的 API 列表（反向索引）。"""
    refs = {sid: [] for sid in SOURCES}
    for path, meta in APIS.items():
        for sid in meta.get("src") or []:
            refs.setdefault(sid, []).append(path)
    return refs


def check(env=None):
    """运行时自检：路径展开 + 存在性 + 反向引用 + 问题/告警清单。

    problems：非可选源不可用、未配置、孤儿源、引用不存在 → ok=False。
    warnings：可选源"变量已配置但路径不存在"（如 mod 还没建、解包目录选错）
               → 仅提示，不影响 ok。
    """
    env = env or {}
    refs = api_refs()
    problems = []
    warnings = []
    rows = []
    for sid, meta in SOURCES.items():
        resolved, missing = resolve_path(meta.get("path"), env)
        kind = meta.get("kind")
        exists = _exists(kind, resolved)
        unconfigured = bool(missing)
        if unconfigured and not meta.get("optional"):
            problems.append("%s：路径变量未配置 %s" % (sid, ",".join(missing)))
        if exists is False and not unconfigured:
            if meta.get("optional"):
                warnings.append("%s：已配置但路径不存在 %s" % (sid, resolved))
            else:
                problems.append("%s：路径不存在 %s" % (sid, resolved))
        if not refs.get(sid):
            problems.append("%s：无任何 API 引用（孤儿源）" % sid)
        rows.append({
            "id": sid, "kind": kind, "path": meta.get("path"),
            "resolved": resolved, "mode": meta.get("mode"),
            "optional": bool(meta.get("optional")), "exists": exists,
            "unconfigured": unconfigured, "apis": refs.get(sid) or [],
            "desc": meta.get("desc"),
        })
    for path, meta in APIS.items():
        src = meta.get("src") or []
        if not src:
            problems.append("%s：未声明数据源" % path)
        for sid in src:
            if sid not in SOURCES:
                problems.append("%s：引用了未注册的数据源 %s" % (path, sid))
    return {"ok": not problems, "problems": problems, "warnings": warnings,
            "sources": rows, "apis": APIS, "env_keys": list(ENV_KEYS)}


def match_api(path):
    """按 server.py 的匹配规则找注册项：精确优先，前缀按注册顺序。"""
    bare = (path or "").split("?", 1)[0]
    meta = APIS.get(bare)
    if meta and meta.get("match") in ("exact", "static"):
        return bare, meta
    for p, m in APIS.items():
        if m.get("match") == "prefix" and bare.startswith(p):
            return p, m
    return None, None


def md():
    """生成 docs/DATA_SOURCES.md 的正文（唯一事实源本文件，文档只是快照）。"""
    n_ge = sum(1 for m in APIS.values() if "GET" in (m.get("m") or "") and m.get("match") == "exact")
    n_gp = sum(1 for m in APIS.values() if "GET" in (m.get("m") or "") and m.get("match") == "prefix")
    n_p = sum(1 for m in APIS.values() if "POST" in (m.get("m") or ""))
    n_both = sum(1 for m in APIS.values() if "+" in (m.get("m") or ""))
    n_st = sum(1 for m in APIS.values() if m.get("match") == "static")
    lines = ["# 数据源表与引用注册表", "",
             "> 共 **%d 个数据源**、**%d 条引用**（GET 接口 %d：精确 %d / 前缀 %d；POST %d，其中 %d 条为 GET+POST 合并；静态页 %d）。"
             % (len(SOURCES), len(APIS), n_ge + n_gp, n_ge, n_gp, n_p, n_both, n_st),
             ">",
             "> 本文件由 `python data_sources.py --md` 生成，**勿手改**；",
             "> 唯一事实源是 `data_sources.py`（SOURCES / APIS）。", "",
             "## 一、数据源表（SOURCES）", "",
             "| id | 类型 | 路径模板 | 读写 | 可选 | 说明 |", "|---|---|---|---|---|---|"]
    for sid, meta in SOURCES.items():
        lines.append("| `%s` | %s | `%s` | %s | %s | %s |" % (
            sid, meta.get("kind"), meta.get("path"), meta.get("mode"),
            "是" if meta.get("optional") else "否", meta.get("desc")))
    lines += ["", "## 二、引用注册表（APIS）", "",
              "| 路由 | 方法 | 匹配 | 引用的数据源 | 说明 |", "|---|---|---|---|---|"]
    for path, meta in APIS.items():
        lines.append("| `%s` | %s | %s | %s | %s |" % (
            path, meta.get("m"), meta.get("match"),
            "、".join("`%s`" % s for s in (meta.get("src") or [])), meta.get("desc")))
    refs = api_refs()
    lines += ["", "## 三、反查：数据源 → 引用方", "",
              "| 数据源 | 被哪些 API 引用 |", "|---|---|"]
    for sid in SOURCES:
        lines.append("| `%s` | %s |" % (sid, "、".join("`%s`" % p for p in (refs.get(sid) or []))))
    lines += ["", "## 四、运行时可查", "",
              "- `GET /api/sources`：返回本表 + 当前配置下每个源展开后的真实路径、是否存在、被谁引用、`problems`（硬问题，决定 `ok`）与 `warnings`（可选源已配置但路径不存在，仅提示）。",
              "- `python data_sources.py`：启动前自检（`problems` 非空则退出码非 0；`warnings` 只打印）。", ""]
    return "\n".join(lines)


def _main():
    import os
    import sys
    if "--md" in sys.argv:
        print(md())
        return 0
    base = os.path.dirname(os.path.abspath(__file__))
    env = {"BASE": base, "CACHE_DIR": os.path.join(base, "cache")}
    rep = check(env)
    print("数据源 %d 个，API %d 个" % (len(SOURCES), len(APIS)))
    if rep["problems"]:
        print("问题 %d 条：" % len(rep["problems"]))
        for p in rep["problems"]:
            print("  -", p)
        return 1
    if rep["warnings"]:
        print("告警 %d 条（可选源已配置但路径不存在，不影响通过）：" % len(rep["warnings"]))
        for w in rep["warnings"]:
            print("  -", w)
    print("OK：引用闭环完整（无孤儿源、无未声明源的 API）")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
