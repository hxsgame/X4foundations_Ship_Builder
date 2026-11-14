# 数据源表与引用注册表

> 本文件由 `python data_sources.py --md` 生成，**勿手改**；
> 唯一事实源是 `data_sources.py`（SOURCES / APIS）。

## 一、数据源表（SOURCES）

| id | 类型 | 路径模板 | 读写 | 可选 | 说明 |
|---|---|---|---|---|---|
| `app.code` | file | `{BASE}/data_sources.py` | r | 否 | 本注册表 + server.py，自检接口的自省来源 |
| `app.index` | file | `{BASE}/index.html` | r | 否 | 前端单页，全部呈现数据的唯一入口（只经 /api/* 取数） |
| `app.config` | file | `{BASE}/builder_config.json` | rw | 是 | 工具配置：解包根 root / 目标 mod / 备份根 / 导出路径 |
| `app.cache` | dir | `{CACHE_DIR}` | rw | 是 | 派生缓存（签名校验，可全删重建）：templates/equip_scan/bullet_*/software/macro_catalog/matrefs 等 |
| `app.backup` | dir | `{BACKUP_ROOT}` | rw | 是 | 覆盖写前的备份根（每文件 .bak 链） |
| `x4.root` | dir | `{ROOT}` | r | 是 | X4 解包根（builder_config.root），未配置时工具只能浏览、不能读数据 |
| `x4.assets` | dir | `{ROOT}/assets` | r | 是 | 原版资产树：units/props/fx/textures（组件、宏、模型、特效、图标） |
| `x4.units` | dir | `{ROOT}/assets/units` | r | 是 | 原版舰船/组件/宏（size_l、size_xl、props 等） |
| `x4.libraries` | dir | `{ROOT}/libraries` | r | 是 | wares/effects/trail_effects/material_library/sound_library/factions/jobs/shipgroups/icons/*.xsd |
| `x4.index` | dir | `{ROOT}/index` | r | 是 | components.xml / macros.xml 全局索引（新增条目注册） |
| `x4.t` | dir | `{ROOT}/t` | r | 是 | 本地化 0001-l086（中文）/0001-l044（英文），名称与描述解析 |
| `x4.extensions` | dir | `{ROOT}/extensions` | r | 是 | 各 mod 的 assets/libraries/index/t 覆盖层（含目标 mod 之外的来源） |
| `mod.dir` | dir | `{MOD_DIR}` | rw | 是 | 目标 mod 根（builder_config.target_mod） |
| `mod.assets` | dir | `{MOD_DIR}/assets` | rw | 是 | 目标 mod 资产（舰船/装备组件与宏、_data 几何） |
| `mod.libraries` | dir | `{MOD_DIR}/libraries` | rw | 是 | 目标 mod wares/jobs/shipgroups/icons 等库文件 |
| `mod.index` | dir | `{MOD_DIR}/index` | rw | 是 | 目标 mod components.xml / macros.xml |
| `mod.t` | dir | `{MOD_DIR}/t` | rw | 是 | 目标 mod 本地化 0001-l086（写入舰船/装备名称） |
| `mod.content` | file | `{MOD_DIR}/content.xml` | r | 是 | mod 扩展标识（id/name），moddirs 列表用 |
| `tool.xrcattool` | file | `{XRCATTOOL}` | r | 是 | 官方 XRCatTool.exe，解包时调用 |
| `game.cat` | request | `<请求参数 game>/*.cat` | r | 是 | 基游戏 ##.cat 索引（配对 .dat 为实际数据） |
| `game.staging` | request | `<请求参数 game>/extensions/vortex.deployment.json` | r | 是 | Vortex 暂存区路径（未启用 mod 的扫描来源） |
| `sys.fs` | fs | `<请求参数>` | r | 是 | dirtree/pickdir/模型同步导出目录等用户选择路径 |
| `const.factions` | const | `server.py FACTIONS` | r | 否 | 可选派系枚举（来自 factions.xml + t 中文名） |
| `const.job_tasks` | const | `server.py JOB_TASKS` | r | 否 | jobs 任务类型 → order 映射 |
| `const.ware_mats` | const | `server.py WARE_MATS` | r | 否 | 建造材料白名单（wares.xml 校验，缺失才标自定义） |
| `const.prod_methods` | const | `server.py PROD_METHODS` | r | 否 | 建造方式固定枚举（启动时按 wares.xml 的 production method 扩充） |
| `const.cost_refs` | const | `server.py COST_REFS` | r | 否 | L/XL 造价参考值（原版 wares.xml 统计快照） |
| `const.equip_classes` | const | `server.py EQUIP_CLASSES` | r | 否 | 装备分类规则（按连接 tags 结构，非命名） |
| `mem.unpack_task` | mem | `server.py _UP` | rw | 否 | 解包任务进度/取消标志（进程内） |

## 二、引用注册表（APIS）

| 路由 | 方法 | 匹配 | 引用的数据源 | 说明 |
|---|---|---|---|---|
| `/` | GET | static | `app.index` | 前端单页（非 /api，静态兜底） |
| `/api/templates` | GET | exact | `x4.units`、`x4.assets`、`x4.extensions`、`mod.assets`、`mod.index`、`app.cache` | 舰船模板列表（原版 + 各来源） |
| `/api/stats` | GET | exact | `x4.assets`、`x4.libraries`、`x4.extensions` | 资产统计（模型/材质/贴图计数） |
| `/api/enums` | GET | exact | `x4.assets`、`x4.libraries`、`x4.extensions`、`const.equip_classes` | 各类下拉枚举（尺寸/种族/挂载分类等） |
| `/api/factions` | GET | exact | `x4.libraries`、`x4.extensions`、`x4.t`、`const.factions` | 派系列表（factions.xml + 中文名） |
| `/api/costrefs` | GET | exact | `const.cost_refs`、`x4.libraries` | 造价/工时参考值 |
| `/api/shipgroups/all` | GET | exact | `x4.libraries`、`x4.extensions`、`mod.libraries` | 全部升级组合并视图 |
| `/api/loadoutmacros` | GET | exact | `x4.units`、`mod.assets` | 内联 loadout 宏清单 |
| `/api/softwarelist` | GET | exact | `x4.libraries`、`x4.extensions`、`app.cache`、`const.ware_mats` | 软件清单（wares.xml 扫描） |
| `/api/equiprefs` | GET | exact | `x4.assets`、`x4.units`、`x4.libraries`、`x4.extensions`、`mod.assets`、`app.cache` | 装备引用分组（同类参考） |
| `/api/moddirs` | GET | exact | `x4.extensions`、`mod.content` | extensions 下 mod 目录列表 |
| `/api/docklist` | GET | exact | `x4.assets`、`x4.extensions`、`mod.assets` | 可复用 dock 模板列表 |
| `/api/config` | GET+POST | exact | `app.config`、`x4.root`、`mod.dir`、`app.backup` | 读/写工具配置（切换解包根、目标 mod、备份根） |
| `/api/unpackstatus` | GET | exact | `mem.unpack_task` | 解包任务进度 |
| `/api/shiplint` | GET | exact | `x4.units`、`x4.assets`、`x4.index`、`mod.assets` | 舰船结构体检（R6 校验器） |
| `/api/component` | GET | prefix | `x4.units`、`x4.assets`、`x4.extensions`、`mod.assets`、`mod.index`、`app.cache` | 舰船组件/挂载点读取 |
| `/api/shipmaterials` | GET | prefix | `x4.assets`、`x4.units`、`x4.libraries`、`x4.extensions`、`mod.assets` | 舰船材质引用 |
| `/api/shiploadout` | GET | prefix | `x4.units`、`mod.assets`、`x4.t` | 舰船出厂 loadout 回填 |
| `/api/shipjobs` | GET | prefix | `x4.units`、`mod.libraries`、`const.job_tasks` | 舰船 jobs 回填 |
| `/api/shipconnections` | GET | prefix | `x4.units`、`x4.assets`、`mod.assets` | 挂载连接拓扑 |
| `/api/shipgroups` | GET | prefix | `x4.libraries`、`x4.extensions`、`mod.libraries` | 单船升级组 |
| `/api/shipsoftware` | GET | prefix | `x4.libraries`、`mod.libraries`、`x4.t` | 舰船软件回填 |
| `/api/equipkinds` | GET | prefix | `x4.assets`、`x4.extensions`、`app.cache` | 装备子类（weapon/turret/missile…） |
| `/api/equiptemplates` | GET | prefix | `x4.assets`、`x4.units`、`x4.libraries`、`x4.extensions`、`mod.assets`、`app.cache` | 装备模板列表 |
| `/api/equipread` | GET | prefix | `x4.assets`、`x4.units`、`x4.extensions`、`mod.assets`、`x4.t` | 装备详情读取（字段 + 引用回填） |
| `/api/shieldmatrefs` | GET | prefix | `x4.assets`、`x4.libraries`、`x4.extensions`、`app.cache` | 护盾材质引用 |
| `/api/equiptags` | GET | prefix | `x4.assets`、`x4.extensions`、`const.equip_classes` | 装备挂载标签枚举 |
| `/api/bulletrefs` | GET | prefix | `x4.assets`、`x4.libraries`、`x4.extensions`、`mod.assets`、`app.cache` | 弹丸引用分组 |
| `/api/bulleteffectlist` | GET | prefix | `x4.assets`、`x4.libraries`、`x4.extensions`、`mod.assets`、`app.cache` | 弹丸命中特效列表 |
| `/api/bulleteffectread` | GET | prefix | `x4.assets`、`x4.libraries`、`x4.extensions`、`mod.assets` | 命中特效详情 |
| `/api/bullettraillist` | GET | prefix | `x4.assets`、`x4.libraries`、`x4.extensions`、`mod.assets`、`app.cache` | 弹道拖尾材质列表 |
| `/api/bullettrailread` | GET | prefix | `x4.assets`、`x4.libraries`、`x4.extensions`、`mod.assets` | 拖尾详情 |
| `/api/bulletbeamlist` | GET | prefix | `x4.assets`、`x4.libraries`、`x4.extensions`、`mod.assets`、`app.cache` | 光束材质列表 |
| `/api/bulletbeamread` | GET | prefix | `x4.assets`、`x4.libraries`、`x4.extensions`、`mod.assets` | 光束详情 |
| `/api/bulletvisread` | GET | prefix | `x4.assets`、`x4.libraries`、`x4.extensions`、`mod.assets` | 弹丸视觉详情 |
| `/api/bulletvislist` | GET | prefix | `x4.assets`、`x4.libraries`、`x4.extensions`、`mod.assets`、`app.cache` | 弹丸视觉材质列表 |
| `/api/bulletvisrefs` | GET | prefix | `x4.assets`、`x4.libraries`、`x4.extensions`、`mod.assets`、`app.cache` | 弹丸视觉引用分组 |
| `/api/equipnumrefs` | GET | prefix | `x4.assets`、`x4.units`、`x4.libraries`、`x4.extensions`、`mod.assets`、`app.cache` | 装备数值引用（伤害/转速等） |
| `/api/missileusers` | GET | prefix | `x4.units`、`x4.assets`、`x4.extensions` | 使用该导弹的舰船/发射器 |
| `/api/explosionusers` | GET | prefix | `x4.units`、`x4.assets`、`x4.libraries` | 使用该爆炸特效的舰船 |
| `/api/missiletags` | GET | prefix | `x4.assets`、`x4.libraries` | 导弹兼容标签 |
| `/api/trailrefs` | GET | prefix | `x4.assets`、`x4.libraries` | 拖尾引用分组 |
| `/api/explosionrefs` | GET | prefix | `x4.assets`、`x4.libraries` | 爆炸引用分组 |
| `/api/explosioneffects` | GET | prefix | `x4.assets`、`x4.libraries` | 爆炸特效列表 |
| `/api/trailmaterials` | GET | prefix | `x4.libraries`、`x4.assets` | 拖尾材质列表 |
| `/api/traileffect` | GET | prefix | `x4.assets`、`x4.libraries` | 拖尾效果详情 |
| `/api/eqgeom` | GET | prefix | `x4.assets`、`x4.extensions`、`mod.assets` | 装备几何（模型路径/包围盒） |
| `/api/equipchain` | GET | prefix | `x4.assets`、`x4.units`、`x4.extensions`、`mod.assets` | 装备完整引用链（宏→组件→物品→模型） |
| `/api/unpackscan` | GET | prefix | `x4.root`、`x4.extensions`、`tool.xrcattool`、`game.cat`、`game.staging`、`sys.fs` | 扫描可解包来源（基游戏/mod/创意工坊/暂存区） |
| `/api/diffvalidate` | GET+POST | prefix | `mod.assets`、`x4.assets`、`x4.units` | diff 补丁校验（GET 预览校验 / POST 落盘前校验） |
| `/api/schemas` | GET | prefix | `x4.libraries`、`x4.extensions` | XSD 类型定义聚合 |
| `/api/difflist` | GET | prefix | `mod.dir` | mod 内 diff 文件列表 |
| `/api/diffpreview` | GET | prefix | `mod.dir`、`x4.assets`、`x4.units` | diff 应用预览（对比 base 组件） |
| `/api/sources` | GET | exact | `app.code`、`app.config`、`app.cache` | 数据源表 + 引用注册表自检（存在性/反向引用/问题） |
| `/api/generate` | POST | exact | `x4.units`、`x4.assets`、`x4.index`、`x4.libraries`、`x4.t`、`mod.assets`、`mod.index`、`mod.libraries`、`mod.t`、`app.backup`、`const.factions`、`const.job_tasks`、`const.ware_mats`、`const.prod_methods` | 生成新舰船（全套 XML + 名称 + index） |
| `/api/edit` | POST | exact | `x4.units`、`x4.libraries`、`x4.t`、`mod.assets`、`mod.libraries`、`mod.index`、`app.backup` | 编辑已部署舰船 |
| `/api/equipgenerate` | POST | exact | `x4.assets`、`x4.units`、`x4.libraries`、`x4.index`、`x4.t`、`x4.extensions`、`mod.assets`、`mod.libraries`、`mod.index`、`mod.t`、`app.backup` | 生成装备（含 L/XL 跨尺寸复制） |
| `/api/equipedit` | POST | exact | `x4.assets`、`x4.units`、`x4.libraries`、`x4.t`、`mod.assets`、`mod.libraries`、`mod.index`、`app.backup` | 编辑装备 |
| `/api/bulletgenerate` | POST | exact | `x4.assets`、`x4.libraries`、`mod.assets`、`mod.libraries`、`app.backup` | 生成弹丸/弹药 |
| `/api/bulletedit` | POST | exact | `x4.assets`、`x4.libraries`、`mod.assets`、`mod.libraries`、`app.backup` | 编辑弹丸/弹药 |
| `/api/shipmodelsync` | POST | exact | `x4.assets`、`mod.assets`、`sys.fs` | 从 Blender 导出目录同步舰船模型 |
| `/api/componentassemble` | POST | exact | `x4.assets`、`mod.assets`、`app.backup` | 组件装配（缩放复用 ego 导出） |
| `/api/dockclone` | POST | exact | `x4.assets`、`mod.assets`、`sys.fs` | dock 组件克隆 |
| `/api/explosionbuild` | POST | exact | `x4.assets`、`x4.libraries`、`mod.assets`、`mod.libraries`、`app.backup` | 构建爆炸特效 |
| `/api/trailnew` | POST | exact | `x4.assets`、`x4.libraries`、`mod.assets`、`mod.libraries`、`app.backup` | 新建拖尾材质 |
| `/api/bulleteffectbuild` | POST | exact | `x4.assets`、`x4.libraries`、`mod.assets`、`mod.libraries`、`app.backup` | 构建命中特效 |
| `/api/bullettrailbuild` | POST | exact | `x4.assets`、`x4.libraries`、`mod.assets`、`mod.libraries`、`app.backup` | 构建弹道拖尾 |
| `/api/bulletbeambuild` | POST | exact | `x4.assets`、`x4.libraries`、`mod.assets`、`mod.libraries`、`app.backup` | 构建光束 |
| `/api/bulletvisbuild` | POST | exact | `x4.assets`、`x4.libraries`、`mod.assets`、`mod.libraries`、`app.backup` | 构建弹丸视觉 |
| `/api/delitem` | POST | exact | `mod.assets`、`mod.libraries`、`mod.index`、`app.backup` | 删除 mod 内条目 |
| `/api/unpack` | POST | exact | `game.cat`、`game.staging`、`tool.xrcattool`、`app.config`、`sys.fs` | 后台解包（cat/mod/暂存区） |
| `/api/unpackcancel` | POST | exact | `mem.unpack_task` | 取消解包 |
| `/api/refresh` | POST | exact | `app.cache` | 清空派生缓存 |
| `/api/dirtree` | POST | exact | `sys.fs` | 目录树浏览 |
| `/api/pickdir` | POST | exact | `sys.fs` | 系统目录选择 |

## 三、反查：数据源 → 引用方

| 数据源 | 被哪些 API 引用 |
|---|---|
| `app.code` | `/api/sources` |
| `app.index` | `/` |
| `app.config` | `/api/config`、`/api/sources`、`/api/unpack` |
| `app.cache` | `/api/templates`、`/api/softwarelist`、`/api/equiprefs`、`/api/component`、`/api/equipkinds`、`/api/equiptemplates`、`/api/shieldmatrefs`、`/api/bulletrefs`、`/api/bulleteffectlist`、`/api/bullettraillist`、`/api/bulletbeamlist`、`/api/bulletvislist`、`/api/bulletvisrefs`、`/api/equipnumrefs`、`/api/sources`、`/api/refresh` |
| `app.backup` | `/api/config`、`/api/generate`、`/api/edit`、`/api/equipgenerate`、`/api/equipedit`、`/api/bulletgenerate`、`/api/bulletedit`、`/api/componentassemble`、`/api/explosionbuild`、`/api/trailnew`、`/api/bulleteffectbuild`、`/api/bullettrailbuild`、`/api/bulletbeambuild`、`/api/bulletvisbuild`、`/api/delitem` |
| `x4.root` | `/api/config`、`/api/unpackscan` |
| `x4.assets` | `/api/templates`、`/api/stats`、`/api/enums`、`/api/equiprefs`、`/api/docklist`、`/api/shiplint`、`/api/component`、`/api/shipmaterials`、`/api/shipconnections`、`/api/equipkinds`、`/api/equiptemplates`、`/api/equipread`、`/api/shieldmatrefs`、`/api/equiptags`、`/api/bulletrefs`、`/api/bulleteffectlist`、`/api/bulleteffectread`、`/api/bullettraillist`、`/api/bullettrailread`、`/api/bulletbeamlist`、`/api/bulletbeamread`、`/api/bulletvisread`、`/api/bulletvislist`、`/api/bulletvisrefs`、`/api/equipnumrefs`、`/api/missileusers`、`/api/explosionusers`、`/api/missiletags`、`/api/trailrefs`、`/api/explosionrefs`、`/api/explosioneffects`、`/api/trailmaterials`、`/api/traileffect`、`/api/eqgeom`、`/api/equipchain`、`/api/diffvalidate`、`/api/diffpreview`、`/api/generate`、`/api/equipgenerate`、`/api/equipedit`、`/api/bulletgenerate`、`/api/bulletedit`、`/api/shipmodelsync`、`/api/componentassemble`、`/api/dockclone`、`/api/explosionbuild`、`/api/trailnew`、`/api/bulleteffectbuild`、`/api/bullettrailbuild`、`/api/bulletbeambuild`、`/api/bulletvisbuild` |
| `x4.units` | `/api/templates`、`/api/loadoutmacros`、`/api/equiprefs`、`/api/shiplint`、`/api/component`、`/api/shipmaterials`、`/api/shiploadout`、`/api/shipjobs`、`/api/shipconnections`、`/api/equiptemplates`、`/api/equipread`、`/api/equipnumrefs`、`/api/missileusers`、`/api/explosionusers`、`/api/equipchain`、`/api/diffvalidate`、`/api/diffpreview`、`/api/generate`、`/api/edit`、`/api/equipgenerate`、`/api/equipedit` |
| `x4.libraries` | `/api/stats`、`/api/enums`、`/api/factions`、`/api/costrefs`、`/api/shipgroups/all`、`/api/softwarelist`、`/api/equiprefs`、`/api/shipmaterials`、`/api/shipgroups`、`/api/shipsoftware`、`/api/equiptemplates`、`/api/shieldmatrefs`、`/api/bulletrefs`、`/api/bulleteffectlist`、`/api/bulleteffectread`、`/api/bullettraillist`、`/api/bullettrailread`、`/api/bulletbeamlist`、`/api/bulletbeamread`、`/api/bulletvisread`、`/api/bulletvislist`、`/api/bulletvisrefs`、`/api/equipnumrefs`、`/api/explosionusers`、`/api/missiletags`、`/api/trailrefs`、`/api/explosionrefs`、`/api/explosioneffects`、`/api/trailmaterials`、`/api/traileffect`、`/api/schemas`、`/api/generate`、`/api/edit`、`/api/equipgenerate`、`/api/equipedit`、`/api/bulletgenerate`、`/api/bulletedit`、`/api/explosionbuild`、`/api/trailnew`、`/api/bulleteffectbuild`、`/api/bullettrailbuild`、`/api/bulletbeambuild`、`/api/bulletvisbuild` |
| `x4.index` | `/api/shiplint`、`/api/generate`、`/api/equipgenerate` |
| `x4.t` | `/api/factions`、`/api/shiploadout`、`/api/shipsoftware`、`/api/equipread`、`/api/generate`、`/api/edit`、`/api/equipgenerate`、`/api/equipedit` |
| `x4.extensions` | `/api/templates`、`/api/stats`、`/api/enums`、`/api/factions`、`/api/shipgroups/all`、`/api/softwarelist`、`/api/equiprefs`、`/api/moddirs`、`/api/docklist`、`/api/component`、`/api/shipmaterials`、`/api/shipgroups`、`/api/equipkinds`、`/api/equiptemplates`、`/api/equipread`、`/api/shieldmatrefs`、`/api/equiptags`、`/api/bulletrefs`、`/api/bulleteffectlist`、`/api/bulleteffectread`、`/api/bullettraillist`、`/api/bullettrailread`、`/api/bulletbeamlist`、`/api/bulletbeamread`、`/api/bulletvisread`、`/api/bulletvislist`、`/api/bulletvisrefs`、`/api/equipnumrefs`、`/api/missileusers`、`/api/eqgeom`、`/api/equipchain`、`/api/unpackscan`、`/api/schemas`、`/api/equipgenerate` |
| `mod.dir` | `/api/config`、`/api/difflist`、`/api/diffpreview` |
| `mod.assets` | `/api/templates`、`/api/loadoutmacros`、`/api/equiprefs`、`/api/docklist`、`/api/shiplint`、`/api/component`、`/api/shipmaterials`、`/api/shiploadout`、`/api/shipconnections`、`/api/equiptemplates`、`/api/equipread`、`/api/bulletrefs`、`/api/bulleteffectlist`、`/api/bulleteffectread`、`/api/bullettraillist`、`/api/bullettrailread`、`/api/bulletbeamlist`、`/api/bulletbeamread`、`/api/bulletvisread`、`/api/bulletvislist`、`/api/bulletvisrefs`、`/api/equipnumrefs`、`/api/eqgeom`、`/api/equipchain`、`/api/diffvalidate`、`/api/generate`、`/api/edit`、`/api/equipgenerate`、`/api/equipedit`、`/api/bulletgenerate`、`/api/bulletedit`、`/api/shipmodelsync`、`/api/componentassemble`、`/api/dockclone`、`/api/explosionbuild`、`/api/trailnew`、`/api/bulleteffectbuild`、`/api/bullettrailbuild`、`/api/bulletbeambuild`、`/api/bulletvisbuild`、`/api/delitem` |
| `mod.libraries` | `/api/shipgroups/all`、`/api/shipjobs`、`/api/shipgroups`、`/api/shipsoftware`、`/api/generate`、`/api/edit`、`/api/equipgenerate`、`/api/equipedit`、`/api/bulletgenerate`、`/api/bulletedit`、`/api/explosionbuild`、`/api/trailnew`、`/api/bulleteffectbuild`、`/api/bullettrailbuild`、`/api/bulletbeambuild`、`/api/bulletvisbuild`、`/api/delitem` |
| `mod.index` | `/api/templates`、`/api/component`、`/api/generate`、`/api/edit`、`/api/equipgenerate`、`/api/equipedit`、`/api/delitem` |
| `mod.t` | `/api/generate`、`/api/equipgenerate` |
| `mod.content` | `/api/moddirs` |
| `tool.xrcattool` | `/api/unpackscan`、`/api/unpack` |
| `game.cat` | `/api/unpackscan`、`/api/unpack` |
| `game.staging` | `/api/unpackscan`、`/api/unpack` |
| `sys.fs` | `/api/unpackscan`、`/api/shipmodelsync`、`/api/dockclone`、`/api/unpack`、`/api/dirtree`、`/api/pickdir` |
| `const.factions` | `/api/factions`、`/api/generate` |
| `const.job_tasks` | `/api/shipjobs`、`/api/generate` |
| `const.ware_mats` | `/api/softwarelist`、`/api/generate` |
| `const.prod_methods` | `/api/generate` |
| `const.cost_refs` | `/api/costrefs` |
| `const.equip_classes` | `/api/enums`、`/api/equiptags` |
| `mem.unpack_task` | `/api/unpackstatus`、`/api/unpackcancel` |

## 四、运行时可查

- `GET /api/sources`：返回本表 + 当前配置下每个源展开后的真实路径、是否存在、被谁引用、`problems`（硬问题，决定 `ok`）与 `warnings`（可选源已配置但路径不存在，仅提示）。
- `python data_sources.py`：启动前自检（`problems` 非空则退出码非 0；`warnings` 只打印）。
