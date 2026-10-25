# X4 舰船/装备制作工具（EVE_Ship_Builder）

本地网页工具，从现有 X4 舰船 / 装备 mod 复制并改名，直接生成可用的舰船与装备全套 XML，写入目标 mod 目录。

运行环境：Windows + Python 3（仅标准库），无需安装任何第三方依赖。界面为单页 `index.html`，后端为 `server.py`（Python 自带 `http.server`）。

---

## 一、启动与访问

```
python server.py
浏览器打开 http://127.0.0.1:8765
```

- 端口固定 **8765**；改 `index.html` 不用重启，改 `server.py` 必须重启。
- 服务在 127.0.0.1 监听，仅本机可访问。
- 浏览器建议用 Ctrl+F5 强刷，避免缓存旧版 JS。

### 关键路径常量（server.py 顶部，可改）

| 常量 | 默认值 | 含义 |
|---|---|---|
| `ROOT` | `D:\Games\X4 exout` | X4 解包根目录 |
| `MOD_DIR` | `…\extensions\UP7_Real_EVE_Ships` | 默认目标 mod（写入位置） |
| `VANILLA_DIR` | `ROOT\assets\units` | 原版舰船宏/组件所在 |
| 端口 | `127.0.0.1:8765` | 本地服务端口 |

目标 mod 可在界面里改（含"系统文件夹选择"），选择结果存 `builder_config.json`，下次启动沿用。

### 重启服务流程（改 server.py 后）

```
Get-NetTCPConnection -LocalPort 8765 -State Listen → 记 OwningProcess
Stop-Process -Id <pid> -Force
Start-Process python -ArgumentList "server.py" -WorkingDirectory (Get-Location) -WindowStyle Hidden
Start-Sleep 8 → 再查 8765 监听确认
```

### 前端 JS 校验（改 index.html 后）

抽 `<script>` 内容写 `_c.js`，`node --check _c.js`，通过后删除。

---

## 二、目录结构

```
EVE_Ship_Builder/
├─ server.py         后端主程序（路由 + 舰船/装备生成逻辑，约 2600 行）
├─ index.html        前端单页（选项卡界面，约 1700 行）
├─ x4_lookup.py      X4 数据提取/名称解析/文本清洗（独立可复用，X4Lookup 类）
├─ builder_config.json  目标 mod 记忆
├─ README.md         本文档
├─ *_test.py         回归测试脚本（build/jobs/loadout/edit）
└─ tools/            历史一次性脚本归档（scan_* 数据提取、_* 调试/补丁脚本）
```

`scan_*.py`、`_*.py` 均为历史一次性脚本，与运行时无关，可归档到 `tools/`（见"优化建议"）。

---

## 三、核心数据流

### 舰船

**新增（generate）**：以某船为模板 → 复制其模型/挂载文件并改名 → 生成 ship macro、component、storage、wares、t 名称、index 注册、shipgroups、jobs → 写入目标 mod，并做一份 `moding` 副本供覆盖。改名时**材质引用名不改**（材质名写在模型文件里，新船沿用模板旧材质）。

**修改（edit）**：改目标 mod 里已有舰船 → 写回**该船所属 mod 目录**，目标 mod 栏自动跟随；改前备份原文件；支持挂载点 tags、装配预设、jobs、软件预装、建造成本等。

> 原版（含 DLC）船**不可直接修改**，只能作为模板走"新增"。

### 装备（炮台/主武器/护盾/导弹/弹丸）

- 弹丸、导弹是**弹药**选项卡的子选项卡；其余（炮台/主武器/护盾）为独立选项卡。
- **新增/修改**都读模板数据；新增时按目标类复制资源并改名。
- 引用链：`macro → component(component ref=) → source geometry(几何) → data(bullet)`，工具自动发现并回填完整路径。
- **模型链铁律**：五类装备统一——**原版和 DLC 资源指向引用**（复用原资源、不复制）；**mod 资源整套复制改名**。

---

## 四、选项卡功能总览

| 选项卡 | 说明 |
|---|---|
| 舰船模块 | 模板选择、新增/修改、属性（名称/种族/尺寸/标识）、护盾/引擎等 |
| 炮台 turret | 新增/修改、tags、引用链、弹药宏（bullet class 输入筛选） |
| 主武器 weapon | 同上 |
| 护盾 shield | 同上 |
| 弹药 ammo | 子选项卡：**弹丸 bullet** / **导弹 missile** |
| 模型同步 | EGO Blender 导出目录 → 目标 mod：py 处理舰船 xml、macro 连接点归位、模型目录/ani/dae 覆盖、moding 可覆盖结构 |
| Dock 复用 | 原版/DLC dock 组件复制改名注册新 id + 用 Blender 导出的 waypoint xml 替换停靠路径（几何沿用原版） |

### 舰船模块子模块

- **属性与统计**：名称（t 文本）、种族、尺寸、护盾/引擎等，附原版 L/XL 参考范围（`/api/stats`）。
- **⑥ AI 派系使用（jobs）**：选择派系（多选）+ 任务类型 → 生成 jobs.xml（用游戏的**添加语法**，不覆盖原版避免 bug）。派系中文名从游戏 t 文本查，不手写。已存在则回填但不自动勾选。
- **⑦ 建造成本**：材料用物品下拉列表（现有舰船常用项默认填充），附参考值；留空则按尺寸套默认档。
- **⑧ 挂载点 tags（按组指定，写回 component）**：读 component 挂载点按连接组呈现，按组/槽指定 tags；tags 非空=替换/插入、空=删除。参考值复用装备选项卡 equip_tags（炮台→turret、主武器→weapon、护盾→shield；引擎无参考）。两种参考显示模式（live 常驻联动高亮 / lazy 行内聚焦生成）。**参考词为开关式**：点一次追加，已选（绿色）再点一次移除；按整词匹配，空格统一为单空格，删空后输入框为空串。
- **⑨ 装配预设（loadout）**：引擎/护盾/炮台/主武器/推进器，按"装备选项栏·组名·挂载点 id"排布；从 component 自动校验插槽并给出可选列表，分组信息原样重现；勾选启用+留空=**清空默认预设**。
- **软件预装**：舰船宏里 software 预装定义，附总开关。

---

## 五、游戏规则要点备忘（铁律）

1. **只认游戏 XML 结构规则，不认命名软规律**：
   - 挂载点 id = `<connection>` 的 `name` 属性；分组 = `group` 属性。
   - 不要自找 `con_` 之类命名规律；规则不确定就问用户。
2. **中文名从游戏 t 文本查，不自己乱翻译**（`x4_lookup.X4Lookup.lname` 展开 `{page,id}` 引用）。
3. **语言文件命名**：zh 用 `0001-l086.xml`；en 基础 `0001.xml` 缺失时回退 `0001-l044.xml`（mod 与原版同一套读取逻辑，仅路径不同）。
4. **模型链**（用户已确认，游戏基础部分一般不改）：
   - 舰船：模板复制改名，**材质引用名不改**。
   - 炮台/武器/护盾/导弹/弹丸：原版与 DLC → 指向引用；mod → 整套复制。
   - 物品几何路径 `<source geometry=…>` 要保留**完整路径**（含 assets 层、`_data` 后缀），否则换源（原版→DLC/mod）会错。
5. **装配预设**：
   - `<loadout>` 写在 ship macro 内联；可多份（多个 `<loadout id=…>`）。
   - `path="con_xxx"` 必须与 component 实际插槽名完全一致，否则装备装不上。
   - `optional="true"` 可选槽：AI/船厂生成可能随机不装；想必装则去掉 optional。
   - 归属派系无指定预设时按游戏默认机制处理（沿用模板/随机）。
6. **jobs 用游戏的添加语法**，不要覆盖/破坏原版内容。
7. **暂存**：前端有暂存功能，功能变化需同步更新暂存逻辑（用户曾因误操作丢数据，暂存是保底）。
8. **owner/制造派系**：用多选列表，默认值读原 owner；列表复用"派系选择"模块（分类排序，玩家/主要阵营靠前）。

---

## 六、后端接口速查（server.py 路由）

**GET**（读）：
`/api/templates` 舰船模板列表 · `/api/stats` 原版属性参考 · `/api/enums` 枚举 · `/api/factions` 派系+任务类型 · `/api/costrefs` 建造成本/材料 · `/api/component?ship=` 挂载点 · `/api/shiploadout?ship=` 预设 · `/api/shipjobs?ship=` jobs · `/api/loadoutmacros` 可选装备宏 · `/api/softwarelist` 软件 · `/api/shipsoftware?ship=` · `/api/equipkinds?cls=` · `/api/equiptemplates?cls=` · `/api/equipread?cls=&id=` · `/api/equiptags?cls=` · `/api/equiprefs` 装备参考 · `/api/equipchain?cls=&id=` 引用链 · `/api/moddirs` mod 目录 · `/api/config`

**POST**（写）：
`/api/generate` 舰船新增 · `/api/edit` 舰船修改 · `/api/equipgenerate` / `/api/equipedit` 装备新增/修改 · `/api/bulletgenerate` / `/api/bulletedit` 弹丸新增/修改 · `/api/config` · `/api/pickdir`（系统文件夹选择对话框） · `/api/dirtree` 浏览器内目录树（`files:true` 时附带文件列表） · `/api/shipmodelsync` 船模同步（入参 `ship_id / export_root / py_path / mod / overlay`；`overlay` 留空 = `<mod>\moding`） · `/api/dockclone` dock 复用生成（入参 `tpl / new_id / wp_xml / mod / overlay`；`wp_xml` 留空 = 保留模板原 waypoint）

**GET 补充**：`/api/docklist` dock 复用模板列表（原版/DLC/mod 全部 dock 类组件，含 class/waypoint 数/来源/宏是否存在） · `/api/unpackscan?game=` 扫描游戏目录的 cat 来源 · `/api/unpackstatus` 解包任务状态

**POST 补充**：`/api/unpack` 启动解包（入参 `game / out / xtool / mode / sources`，后台线程） · `/api/unpackcancel` 取消解包

### 游戏解包细节（2026-10-24）

1. 调官方 X Tools 的 `XRCatTool.exe`（CLI：`-in <cats...> -out <目录> [-include <正则...>]`，后面的 cat 覆盖前面的，与游戏加载顺序一致）。XRCatTool **要求输出目录已存在**（后端自动 makedirs）；无百分比输出，进度按「第 i/N 组」显示。
2. 来源扫描（三路合并，按扩展名去重）：① 基游戏 `##.cat`（01 起连续、缺号即停、排除 `_sig`）；② 游戏 `extensions\<名>`——**打包 mod**（有 `ext_*.cat`/`subst_*.cat`）和 **松散 mod**（无 cat，只有 assets/content.xml 等，如 `UP7_Real_EVE_Ships`）都纳入；`ws_*` 目录标为「创意工坊」；③ **Vortex 暂存区** `stagingPath`（自动读 `extensions\vortex.deployment.json`，实测 `d:\Vortex Mods\x4foundations`）——含未启用的 mod，目录名带版本号（如 `Argon Titan Battleship 2.01-974-...`），用 `content.xml` 的 `id` 还原成游戏扩展名后再按 id 去重。实测本机：基游戏 9 cat + 游戏目录 80 个（67 打包/13 松散）+ 创意工坊 4 + 暂存区 92 个（19 打包/73 松散）= 176 项。
3. 落盘规则：基游戏 → 输出根；mod 的 `ext_*` → `<out>\extensions\<名>`；`subst_*` → 输出根（游戏语义=覆盖基游戏文件）；**松散 mod → 复制整个目录到 `<out>\extensions\<名>`**（`shutil.copy2` 跟随符号链接复制真实内容；轻量模式只复制 xml/文本）。Vortex 用 `symlink_activator` 部署，游戏目录里 20 个松散 mod 的 569 个文件是符号链接，必须跟随复制，不能按链接建空文件。
4. 轻量模式 `-include \.xml$ \.txt$ \.csv$ \.json$ \.lua$ \.xsd$ \.dtd$ \.md$`：实测基游戏 9 cat 约 30 秒解出 6573 个文件（assets/units、index、libraries、t、maps、md 全齐），工具全部功能够用；完整模式 ~20GB（模型贴图，仅 Blender 拉原版模型时用）。
5. 安全：拒绝输出到当前工程解包根或游戏安装目录内；基游戏 cat 数据在配对 `.dat`（共约 18GB），cat 本体只是索引。
6. 「切换工程到此目录」= 写 `builder_config.json` 的 `root`，**重启服务后生效**（启动时 config.root 覆盖 ROOT/VANILLA_DIR 并重建 X4Lookup）。
7. XRCatTool 探测顺序：游戏目录同级的 `X Tools\XRCatTool.exe` → `D:\Program Files (x86)\Steam\...\X Tools` → `C:\...`。

### Dock 复用细节（2026-10-24）

1. 背景规则：waypoint 只在 dock **组件 xml** 的 `<layer><waypoints>` 段，macro 层不引用 waypoint 名；无人机机库（dock_xs）不用 waypoint（靠 Con_dockpos/Con_launchpos 连接点），船才用 waypoint 路径网。tags 词汇表固定（typenormal/typedock/start/end/blocklink/closelink/speed_*/sizeLevel1 等）。
2. waypoint 数据来源 = Blender 摆点后导出的 xml 片段（**统一走 Blender 插件面板导出**；早期为 `x4_wp_export.py` 独立脚本，已不维护）：物体名=waypoint 名，自定义属性 `tags`/`links`（空格分隔目标名），Blender Z-up → X4 Y-up 自动换算 (x, z, -y)，比例 1:1 米。**Blender 端导出前自带游戏约束判定**（词汇表在脚本头部注释，tags 白名单常量为 `WP_TAGS`，与 server.py `_WP_TAGS` 保持一致）：错误（重名/tags 空/非法 tag/悬空 link）阻止导出；警告（无 typedock、blocklink 不成对、缺 sizeLevel1、孤立 typenormal 断链嫌疑）可导出。注意：原版合法存在「无出边 link 的 typenormal 终点」（带 end / dynamicmasstraffic，共 11 处），故孤立点只警告且排除这两类。
3. 校验先行：waypoint xml 有非法 tags / 重名 / 悬空 link / 无 waypoint 即**零写入中止**；无 typedock、blocklink 不成对、缺 sizeLevel1 仅警告。
4. **替换锁定 `<layer>` 作用域**：组件的 `<connection>` 里也可能有 `<waypoints/>` 自闭合，全局匹配会错替换（已踩过）。
5. 几何不复制：组件 `<source geometry>` 保持指向原版 `_data`（模型链铁律：原版资源指向引用）；macro 复制改名、component ref 指向新 id；index/components.xml + macros.xml 注册；备份沿用 `_shipmodel_backup`（最近 3 次，失败即中止）；moding 生成可覆盖结构。
6. 目录树文件选择支持扩展名参数：`pickSystemDir(id, status, "file", "\\.xml$")`（默认仍 `.py`）。
7. 沙箱实测基线：dock_list 114 模板（原版含 waypoint 15 个）；生成组件/宏/index/overlay 全命中；二次运行走备份；坏 waypoint 中止零写入。回归脚本 `tools/_dockclone_test.py`（临时目录，不动真实 mod）。
8. **group 与 dockingbay（路径链↔泊位绑定，2026-10-25）**：deck 跑道式 dockarea 的 waypoint 带 `group="xxx"`，与同 group 的泊位连接（`<connection group="xxx" tags="dockingbay">`）绑定。Dock 复用**仅改 XML 不动模型**：`<layer><waypoints>` 段整体替换；dockingbay 连接**只改 group**（含删除），不动 name/数量/位置。
   - **Blender 端命名**（x4_wp_export.py 与组件放置器 addon 一致）：物体名 = `group + 连接符 + name`，连接符默认 `---`（addon 的 wp_name_separator 可自定义，独立脚本优先读取该设置）；物体名不含连接符即无分组。group 与 name 都禁止含连接符。导出时从左起第一个连接符截断：左=group、右=name。旧文件兼容：waypoint 的 group/name 含连接符自动替换为 `_`；dockingbay 含连接符报错中止（由用户先改 XML）。硬点类型由自定义属性 `hardpoint_type`（waypoint/dockingbay）或名称含 dockingbay/waypoint 自动判定，否则默认 waypoint。links 存物体名（带 group+连接符 前缀），导出时映射回基础名。**连接符仅用于 Blender 端物体名拆分，导出的 XML 已直接给出 name 与 group 两个独立属性，工具端（server.py）不涉及连接符。**
   - **合法性检查**：waypoint 组集 与 dockingbay 组集 必须相互对应，否则警告（不阻断输出）。
   - **导出 XML（2026-10-25 更新）**：`<waypoints>` + `<connections>` 两个并列段（与游戏 dock 组件同构）：`<waypoint name tags group? x…qw/>`（含 `<links>`，name 保留 group 前缀全名如 `mt_dock_01-waypoint_01`）+ `<connection name group?/>`（仅 name/group，对应组件里 `tags="dockingbay"` 的连接，供工具端按名定位改 group）。**导出统一走 Blender 插件面板；`x4_wp_export.py`（本目录，Blender Text Editor 旧脚本）不再维护。**
   - **后端**：`_wp_parse` 解析 `<waypoints>` 段 + `<connections>` 段（dockingbay = 自闭合 `<connection name group/>`），返回 (wps, dockingbays, errs, warns)，仅保留必要校验（tags 词汇、links 存在、坐标数值）；`dock_clone` 用 `_db_set_group` 按 dockingbay 的 name 定位 connection 并更新 group（空=删除，重写时属性顺序变为 `name tags group`，语义等价）；waypoint 组集与 dockingbay 组集不一致时警告。

### 杂项修复（2026-10-25）

- Dock 复用选项卡：① dock 模板下拉只显示组件名（与装备/舰船一致，`id = name@@src`，`_dsp` 截断后只显示 `name`）；class/waypoint 数/来源/宏状态移到选择栏下方说明区（`dk-tpl-info`，选中时实时更新）；② 新 id 自动填充为模板名 + `_up7`（仅当字段为空或之前是自动填充值，用户手动编辑后不再覆盖；已含 `_up7` 不重复追加）。旧 localStorage 存的路径值自动迁移为 `name@@src` 格式。
- 装备选项卡：新增模式下建议 ID 追加 `_up7`（`eqid = 模板id + "_up7"`，已含 `_up7` 不重复追加）。
- 舰船选项卡：新增模式下建议 ID 追加 `_up7`（`new_id = ship_种族_尺寸_中段名_up7`，已含 `_up7` 不重复追加）。
- Dock 复用选项卡（续）：③ 选项卡移到「模型同步」之前；④ 新增「删除该 dock」——复用通用 `delItem` → `/api/delitem`（`kind="dock"` 走通用路径，跳过舰船专属材质清理）：按「② 新 id + ④ 修改路径」删目标 mod 内宏/组件 XML 并清 index/wares/icons/shipgroups/jobs/t 注册条目。**模型安全**：dock 复用不复制 `_data`，目标 mod 无 `<新id>_data` 目录可匹配；delitem 仅按文件名精确匹配、不追踪 `geometry=` 引用；附属件发现要求 `core`（id 去首段）是候选名子串，模板名更短永不入选；反向引用检查含 `geometry=`，模板仍被复用副本引用时删除被阻止。⑤ 游戏注册确认：`dock_clone` 本就调 `_register_index` 注册 index/components.xml + macros.xml 双条目，与舰船/装备同链路，无需新增。

### 杂项修复（2026-10-24）

- 装备「弹药宏 bullet class」回填误标「（自定义）」：equipread 返回纯 macro 名（无 `@@source`），而 ssel 选项 id 带 `@@source`，精确匹配落空。修复：`sselSet` 精确匹配失败时按去掉 `@@source` 的名字兜底匹配（只影响显示，`v.value` 保持原值，不影响提交）。
- 全量排查同类坑：选项带 `@@source` 的只有 `shipOpt`/`eqOpt` 两处；舰船模板/操作对象等回填值均来自 `sselGet`（本就走全 id），不受影响。唯一残留功能问题：炮台模板切换时 `eqSetBulletSource` 重建弹丸下拉，`keep` 是读取回填的纯 macro 名会被 `o.id===keep` 守卫丢弃——已改为 `_dsp` 去 @@ 名兜底，保住选择。所有提交路径本就 `split("@@")[0]`，纯名字/全 id 提交结果一致。
- 挂载 tags「同类参考」漏 `component`：`equip_tags()` 原本直接过滤 component/position/container/connection 结构词，导致装备侧参考列表与真实文件不一致（原版 139 个武器 138 个带 component）。修复：结构词保留并标 `struct:true`——装备选项卡里灰显（悬停提示「结构词：装备根挂载点，不参与匹配」），舰船挂载点参考列表隐藏（舰侧 slot 不该加）。TAG_ZH 补 `component=组件根挂载` 等翻译。

### 物品池统一同步（2026-10-24）

**问题**：新增/修改/删除物品后，其它引用该类物品清单的地方仍显示旧数据（模板下拉、模型同步舰船下拉、Dock 模板、装配预设、弹药宏、软件、参考数值）。

**根因（前端，非后端）**：后端写入后已调用 `_refresh_soft()` / `eq_cache_refresh_source()` 增量失效，接口返回的是新数据；但前端把各清单缓存在 JS 全局（`TP`、`EQ[cls].tpl/refs`、`LDOUT/EQLO`、`SOFTWARE_OPTS`、`DK_LIST`）并用 `ready` 标志「渲染一次不再重取」，生成成功时只刷新当前类的本页列表。

**修复**：
1. `invalidateItemLists(kind)`（index.html，紧跟 refreshTP）：统一失效——置脏 `MI_READY`/`DK_READY`、清 `EQLO`/`LDOUT`、重取 `TP`、已渲染装备类的 `tpl` + `eqBuildSels` + `equiprefs`、软件清单；弹药选项卡**只重建下拉选项池**（refetch `tpl`/`refs`/`kinds` + `eqBuildSels` + `updateBulletRefs` + 特效/材质建议），**严禁调用 `bkLoad`/`loadBulletTpl`**（二者结尾 `eqClear` 会清空用户刚保存的表单，见下节）；若当前正停在模型同步/Dock 复用页则立即重建。
2. `refreshTP()` 扩展为同时重建 4 个舰船下拉：`template` / `pick` / `refitem` / `mi-ship`（保留原选择）。
3. 所有写操作成功分支统一调用：舰船新增/修改→`"ship"`；装备/弹药保存→`cls`；删除→`kind`；Dock 复用→`"all"`。
4. 后端补齐：`ship_model_sync` 与 `dock_clone` 结束时调用 `_refresh_soft()`（此前只有舰船/装备生成与删除会失效）。
5. 删除物品后的「请点刷新数据」提示已移除（现在自动同步）。

### 数据丢失回归修复（2026-10-24，二次）

**现象 1**：改 `bullet_bor_l_beam_01_mk2_up7` 的伤害/护盾伤害并保存后，输入框变空值；磁盘上 `damage/@value`、`damage/@shield` 整条属性消失，`<heat/>`、`<bullet>` 的 `lifetime` 也被抹掉。

**根因（双因叠加）**：
1. `invalidateItemLists("bullet")` 调用了 `bkLoad("bullet")` → `loadBulletTpl` → `eqClear(cls,"all")`，把刚保存完的表单字段清空（上一轮「统一同步」引入的回归）。
2. 后端 `_apply_equip_fields` 的 `setnum` 语义是**空值 = 删除该属性**（`re.sub(r'\s字段="[^"]*"')`），于是空表单提交即物理删属性。写入逻辑本身正确（有值正确写入），问题在误发空值。

**修复**：弹药选项卡的刷新改为非破坏性——只重取下拉池并 `eqBuildSels`，保留用户选择与字段值；任何「刷新列表」路径都不许再碰 `bkLoad`/`loadBulletTpl`。

**现象 2（经用户确认：是本人有意删除，非 bug）**：`ship_bor_l_megathron` 组件里 7 个 shield 连接点的 `tags` 从 `large shield hittable standard advanced` 变成 `large shield standard advanced`（`up7con_shield_l-001~007` 去掉了 `hittable`）。备份 `bak_edit_20261024_213425` 与现文件逐行 diff 仅这 7 行，确认无其它改动。

**同源风险（已加固）**：`mtRows()` 原本无条件把 UI 里所有挂载行的 tags 整串写回；当页面展示的 tags 不完整/陈旧（如 `_COMPCACHE` 未随模型同步失效）时，会把磁盘上用户没碰过的词覆盖掉。已改：`addMtGroup`/`addMtSlot` 生成的 tags 输入框带 `data-orig`（渲染时的原值），`mtRows()` 只提交**与 `data-orig` 不同的行**；`ship_model_sync` 结束时补 `_refresh_soft()` 清 `_COMPCACHE`。

**新增保护**：装备/弹丸编辑此前**完全没有备份**（舰船编辑有 `bak_edit_<时间戳>`）。已新增 `_backup_before_edit(path, tag)`：`equip_edit` / `bullet_edit` 在覆盖 macro（以及被改的装备组件）前，先复制到 `UP7_Real_EVE_Ships_jcs_backup_20261004\bak_<tag>_<时间戳>\`。已用一次等价保存实测：生成 `bak_bullet_20261024_222411`，内容为写前快照。

**教训**：
- 「刷新数据」与「重置表单」必须分离，刷新路径禁止调用会 `eqClear` 的函数。
- 属性写入接口的「空值=删除属性」语义意味着前端任何一次误发空串都会造成不可逆数据丢失；批量回写 UI 值时必须做 `data-orig` 差异比对。
- 任何覆盖宏/组件的写操作都必须先备份，备份失败即中止（舰船侧已有此铁律，装备侧本次补齐）。

### 模型同步细节（2026-10-23）

1. 目标校验先行：导出目录必须有 `assets/units/size_*/<id>.xml` 与 `<id>_data`，目标 mod 必须有 `assets/units/size_*/macros/<id>_macro.xml`，否则**不写任何文件**直接中止（提示先新增该 id 舰船）。
2. 备份：写目标前把 xml / 宏 / `_data` / ani / dae 复制到 `<mod>\_shipmodel_backup\<时间戳>_<id>\`（保留原结构），同舰船只留**最近 3 次**。**任何一项备份失败即中止**，不允许在无备份状态下改目标文件（`_sm_backup` 返回 3 元组 `(目录, 数量, 失败项)`）。
3. py 工作目录 = 所选 py 的所在目录：先删除该目录根部所有 `.xml`（只读文件先 `chmod 0o666` 兜底），再复制导出 xml 过去，执行 `python <py> --dir <目录>`，超时 900s，退出码非 0 即中止。
4. 连接点分离按**结构**判定：组件里 `ref=` 且内含 `<macro ref=>` 的 `<connection>` 归 macro（连同 py 的 `New connections…` 注释一起剪切），`name=` 的硬点留在组件。
5. 宏替换时**同名 ref 沿用旧 `connection` 值**（py 内置默认如 `con_cockpit` 会写坏真实连接名 `con_cockpit_01`），新 ref 才用 py 值；缩进按宏原有 tab 风格重排（相对层级折算成 tab）。
6. 覆盖结构 = `<overlay>/assets/units/size_*/…`，复制组件 xml、宏、`_data` 目录、ani/dae；复制前先删 `<overlay>` 里旧的 `_data` 目录，保证可直接整体覆盖。
7. **启动方式（重要）**：服务必须从真实终端启动（`启动服务.bat` 或前台 `python server.py`）。若从受限沙箱后台拉起，会对 `D:\Games` 的写/删抛 `WinError 5 拒绝访问`，备份也会静默失败——已改为备份失败即中止。
8. 实测基线（2026-10-23，megathron 真实同步）：12 步全绿；组件保留 282 个 `name=` 硬点、`ref=` 连接点残留 0；宏 6 条连接点全部沿用旧 `connection` 值；`moding` 结构与目标逐字节一致；备份 `_shipmodel_backup\<时间戳>_ship_bor_l_megathron\` 5 项。

---

## 七、测试脚本（回归用）

| 脚本 | 用途 |
|---|---|
| `build_test.py` | 舰船新增生成链路 |
| `jobs_test.py` | jobs 生成回归 |
| `test_edit.py` | 舰船修改回归 |
| `test_loadout.py` | 装配预设写入回归 |

`scan_*.py`：派系/枚举/材料/存储/图标/loadout 等一次性提取，留作溯源与复用参考。

---

## 八、优化建议（待办）

**已落地**：
- ✅ 扫描缓存刷新：顶部"刷新数据"按钮 + `/api/refresh` 清空 `_EQ_SCAN_CACHE/_LOADOUT_CACHE/_GLOBAL_ASSETS`，运行中往 mod 加物品后无需重启服务即可看到。
- ✅ 模型引用完整性抽查：`verify_model_refs()` 在舰船/装备/弹丸生成后只读校验 component 几何引用是否在目标 mod 或原版 ROOT 中存在，缺失以黄色 warnings 展示（不阻断写入）。
- ✅ 历史脚本归档：`scan_*.py`、`_*.py` 移到 `tools/`。

**保留待办**：
1. **路由可维护性**：do_GET/do_POST 是长 if/elif 链（30+ 分支）。本地工具可用，但可改路由表/装饰器，并把每分支内联的 `urlparse` 提到函数顶部。
2. **端口占用提示**：8765 被占时启动会静默失败，main 里可加端口检测与提示。

---

## 九、发布与配置分离

**两套配置，互不污染**：

| 类型 | 文件 | 是否入库 / 入包 | 说明 |
|---|---|---|---|
| 本地个人配置 | `builder_config.json` | 否（gitignore、不入包） | `root` / `target_mod` / `backup_root`，含本机路径，仅本机有效 |
| 分发默认值 | 无文件 | — | 代码兜底：`ROOT=""`、`MOD_DIR=<工具目录>/_未设置目标mod`、`BACKUP_ROOT=<工具目录>/_backup`；用户在「游戏解包」选项卡填解包根后生成自己的配置 |

**打包（唯一入口，勿手工压缩整个目录）**：

```powershell
.\build_release.ps1                                  # 输出到 dist/，版本号默认当天日期
.\build_release.ps1 -Version 20261025 -OutDir "指定目录"
```

- 白名单 5 个文件：`server.py`、`x4_lookup.py`、`index.html`、`release\启动工具.bat`、`release\使用说明.txt`
- 内置两道校验：禁止文件（配置/备份脚本）混入即中止；包内文本命中本机路径特征（如 `X4 exout`、`UP7_Real_EVE_Ships`）即中止
- 发布模板放在 `release/` 目录（入库），重新出包不需要再手写启动器与说明

**编码约定**：`启动工具.bat` 存 GBK（cmd 中文不乱码）；`build_release.ps1` 与 `使用说明.txt` 存 UTF-8 BOM（PowerShell 5.1 解析中文必需）。修改后务必保留编码，否则会报语法错。

**新 id 后缀（`id_suffix`）**：舰船/装备/Dock 三处「新 id 自动填充」共用一个后缀配置。代码默认 `_up`（分发包行为），本地 `builder_config.json` 设 `"id_suffix": "_up7"` 覆盖；前端启动时经 `/api/config` 读取，未配置则用默认值。

