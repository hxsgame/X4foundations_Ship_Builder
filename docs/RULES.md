# EVE_Ship_Builder 铁律索引

> 最后更新：2026-11-12
> 定位：**规则 → 代码位置**的速查表。每条规则只写"必须怎样 + 违反的后果 + 由谁保证"，事故过程与排错记录见 [MAINTENANCE.md](MAINTENANCE.md)。
> 新增功能前先扫一遍 R1/R2/R5/R6/R8；改完后跑 R13 的验证清单。

---

## R1 geometry 归属（模型链）

| 项 | 内容 |
|---|---|
| 规则 | ① **原版 / DLC 资源 → 指向引用**，不复制数据；② **mod 自有资源 → 整套复制改名**；③ mod 自有 `_data` 的 geometry 必须写显式 `extensions\<mod名>\assets\...`，裸 `assets\...` 只允许原版数据 |
| 后果 | 写错 = 游戏报 `could not find a valid meshsource`，船/装备消失或模型不可见（x150 事故） |
| 代码 | `geo_owned(mod, rel, comp_id)` / `geo_rebase(geom, dst_owner, ...)`（server.py ~L3649-3682）；调用点：`component_assemble`、`_copy_rename_asset`、`generate`、dockarea 共享分支 |
| 附加 | 改舰船尺寸时 geometry 的 `size_l → size_xl` 必须同步改写（`geo_rebase(src_size, dst_size)`） |
| 校验 | `tests/test_geometry.py` |

## R2 .jcs 策略

| 项 | 内容 |
|---|---|
| 规则 | **舰船流禁用 .jcs**；`_copy_dir_rename` 通用复制禁用；**组件流（组件装配）保留** |
| 后果 | 舰船流带 jcs 会崩溃；组件流误删 jcs 会导致缓存/材质异常 |
| 代码 | `_disable_jcs(dirpath)`（~L396），三处调用点分别有注释说明 |
| 注意 | 三条策略不能"顺手统一"，改动先看注释与本节 |

## R3 命名与后缀约定

| 项 | 内容 |
|---|---|
| 规则 | 新 id 后缀走配置 `id_suffix`（分发默认 `_up`，本地 `_up7`），舰船/装备/Dock 三处共用；缩放组件后缀 `_x<N>`；舰船 id 前缀 `ship_`，存储 `storage_`；t 页 `7777771`；图标默认 `upgrade_<macro>_macro` |
| 代码 | `id_suffix` 读配置（`load_config`）；`_x\d+` 解析在组件装配/`_copy_rename_asset`；图标链 `_icon_texture_for` / `_ship_icon_alias` |
| 后果 | 命名规则散落会重演"改一处漏三处"；不要用命名推测游戏语义（R7） |

## R4 文本与语言文件

| 项 | 内容 |
|---|---|
| 规则 | 中文 `t/0001-l086.xml`；英文基础 `0001.xml`，缺失回退 `0001-l044.xml`；中文名**从游戏 t 查**，不手写翻译；编辑改名必须重写 macro 的 identification t 引用 |
| 代码 | `x4_lookup.X4Lookup.lname`；`_alloc_tids` / `_write_equip_txt`；`_rewrite_ident_tids(mtxt, name_tid, desc_tid)`（~L5277） |
| 后果 | 只改 t 文本不改 macro 引用 = "保存成功但重载旧名" |

## R5 注册链路（新增/删除必须成对）

| 项 | 内容 |
|---|---|
| 规则 | 新增：`index/macros.xml` + `index/components.xml`（`register_assets()`）、`libraries/wares.xml`、`libraries/shipgroups.xml`、`libraries/ships.xml`、`libraries/jobs.xml`、t 文本、图标；删除：`delitem` 按同一清单反查清理 + 反向引用检查 |
| 代码 | `register_assets(mod, items)`（~L5352）、`update_registry`、`_shipsxml_sync`、`shipgroup_save_all`、`write_jobs`、`write_ware`、`delitem`（~L7758） |
| 后果 | 漏注册 = 物品不显示 / 船不可用；多注册 = 重复定义报错 |
| 注意 | 路径分隔符统一；`UP7_EVE_battleship_{xl,l}_01` 是 `ships.xml` 按名引用的保留组，不可删（`_SG_RESERVED_GROUPS`） |

## R6 舰船升级组结构（2026-11-08 实锤）

| 项 | 内容 |
|---|---|
| 规则 | **任一挂载连接的兼容标签数必须严格小于该船的升级组数 n**（`max(n_comp) < n`）。兼容标签 = 连接 tags ∩ {standard, missile, mining, highpower, venture, boron, xenon, advanced}（共 8 个）。建议按原版给每个组配护盾/引擎 |
| 后果 | `n_comp > n` → 原版 `menu_ship_configuration.lua` 的 `setupGroupData()` 兼容缓冲越界 → 建造界面点炮塔**直接崩游戏**（dump 落在 `lua51_64.dll` 随机地址） |
| 代码 | **已自动校验（2026-11-12）**：`lint_ship_texts()`（纯文本核心）/ `ship_lint()`（读盘体检），server.py ~L4008 起；`GET /api/shiplint?ship=<id>` 只读体检；`generate` 写盘前发现 error 直接拒绝（`force=1` 强制），`edit` 只告警 |
| 备注 | 组数少的船（revelation 仅 3 组）最多带 2 个兼容标签；加标签前先数一遍。回归测试 `tests/test_shiplint.py` 覆盖 5 标签/3 组→error、删到 2 个→放行 |

## R7 连接点与 macro 挂载

| 项 | 内容 |
|---|---|
| 规则 | 挂载点 id = `<connection name>`，分组 = `group`；**不要自找 `con_` 命名规律**；macro 内挂宏的入口 connection 必须是该宏实测存在的入口（原版/DLC 实际挂法 `obs` 优先）；悬空 ref 禁止提交 |
| 后果 | 入口写错 → 游戏静默忽略挂载 → 不能指派船长/不能操控/无舰桥（megathron 事故） |
| 代码 | `macro_catalog()`（收集 `obs`）、`_macro_entry_info()`、`_apply_macro_connections()`（~L4113，写入前同校验）、前端 `mcEntryInfo` / `mcDefaultConn` |
| 注意 | dockarea 必须先于 dock 判断；`con_countermeasures_*` / `con_playercontrol` 不挂宏，勿加进补全逻辑 |

## R8 写入安全

| 项 | 内容 |
|---|---|
| 规则 | ① 写前校验 XML（`_xml_check`），非法拒绝写入并报行列；② 属性写接口**空值 = 删除属性**，UI 批量回写必须做 `data-orig` 差异比对；③ 覆盖已有文件前必须备份，备份失败即中止；④ 写入走 `write_text()` 原子写与 `_txn` 事务，失败按 `created` 逆序回滚；⑤ **"刷新数据" ≠ "重置表单"**，刷新路径禁止调用 `eqClear`/`loadBulletTpl` 类清空函数 |
| 后果 | 违反②④ = 数据丢失（弹丸数值被抹）；违反⑤ = 保存后表单被清空 |
| 代码 | `_xml_check`（~L1965）、`write_text`（~L6140）、`_txn`（~L492）、`_backup_before_edit`（~L6125）、`_sm_backup`；替换自闭合标签时替换串必须自带 `/>` |

## R9 缓存

| 项 | 内容 |
|---|---|
| 规则 | 三层缓存：磁盘签名缓存（`_cached_whole`）、模块级全局（约 20 个）、按来源增量（`eq_cache_refresh_source` / `bullet_cache_refresh_source`）。**任何新增全局缓存变量都必须登记进 `CACHE_GROUPS`**；写操作后调 `_refresh_soft()` 或对应增量刷新 |
| 后果 | 漏登记 = "改了数据界面不变"；前端另有 `invalidateItemLists(kind)` 统一失效物品池 |
| 代码 | `CACHE_GROUPS` / `invalidate_caches` / `_refresh_soft` / `refresh_caches`（~L8083-8129） |

## R10 moding 副本 / overlay

| 项 | 内容 |
|---|---|
| 规则 | `generate` / `edit` / 装备生成写入后同步 `<mod>\moding` 工作副本；模型同步与 Dock 复用的 `overlay` 参数留空即 `<mod>\moding` |
| 后果 | 不同步 = 游戏读到的仍是旧文件（被旧进程或旧副本覆盖） |

## R11 材质

| 项 | 内容 |
|---|---|
| 规则 | 新增模式 = **克隆**材质到新 collection，修改模式 = **替换**引用；只增不改（不重命名/不删除已有材质、不动其他船）；前缀换名时同步改写材质内纹理目录段；模型同步后补齐 material_library 缺失材质 |
| 代码 | `apply_material_tuning`（~L2769）、`_ml_rename_ref_addonly`、`_ml_swap_tex_paths`、`align_materials_after_sync`（~L2642） |
| 校验 | `tests/test_materials.py` |

## R12 waypoint / dock

| 项 | 内容 |
|---|---|
| 规则 | waypoint 坐标属于**组件局部空间**（Blender 导出需减去挂点偏移）；`<layer><waypoints>` 段整体替换，锁定 layer 作用域；dockingbay 连接**只改 group**，不动 name/数量/位置；waypoint 组集与 dockingbay 组集需对应 |
| 代码 | `_wp_parse` / `_wp_render` / `_db_set_group` / `dock_clone`（~L1257） |
| 后果 | 用整船世界坐标 = 无人机/船停靠路径错位；全局匹配 `<waypoints/>` 会误替换 connection 内的自闭合节点 |

## R13 特效与弹药

| 项 | 内容 |
|---|---|
| 规则 | 特效统一走 `upsert_effect()` 写 effects.xml + `finish_write()` 收尾；弹丸四类：命中/大物体命中/发射、尾焰、爆炸、光束/视觉；引用链 `macro → component → geometry → bullet` |
| 代码 | `upsert_effect`（~L6740）、`finish_write`（~L6771）、`explosion_build`、`bullet_effect_build`、`trail_build`、`bullet_beam_build`、`bullet_vis_build` |
| 注意 | 收尾的 `copy_to_moding + 缓存刷新` 不允许再包 `try/except: pass` |

---

## 验证清单（每次改代码后）

1. `python -c "import ast; ast.parse(open('server.py',encoding='utf-8').read())"`
2. `.\run_tests.ps1`（unittest 63 项 + ast）
3. 改 index.html 后：`node --check` 抽取的 JS 块（或浏览器控制台无语法错误）
4. **结束 8765 旧进程再重启**，冒烟 `/api/templates`、`/api/config`
5. 涉及 X4 结构的改动：Vortex Deploy → 进游戏 → 看 `Documents\Egosoft\X4\<id>\debuglog.txt` 有无 LIBXML2 / `@Artists` / meshsource 报错
