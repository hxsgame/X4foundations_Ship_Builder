# EVE_Ship_Builder 工程维护文档

> 最后更新：2026-10-23
> 适用版本：当前主干（server.py + index.html 单文件架构）

---

## 1. 工程概览

| 项目 | 值 |
|---|---|
| 工程根目录 | `C:\Users\15536\Doubao\chats\2026-10-03\new-chat-1\EVE_Ship_Builder\` |
| 前端 | `index.html`（单文件，~5500 行，含全部 JS/CSS，原生 ES6） |
| 后端 | `server.py`（单文件，~6600 行，Python 3.9+ 原生 `http.server`） |
| 启动方式 | 双击 `启动服务.bat` 或 `python server.py`，浏览器访问 `http://127.0.0.1:8765` |
| X4 解包根 | `D:\Games\X4 exout` |
| 当前目标 Mod | `UP7_Real_EVE_Ships` |
| 持久化文件 | `builder_config.json`（自动保存表单状态，前端不回写） |
| 备份目录 | `jcs_backup/`（generate/edit 自动备份，delitem 不备份） |

### 架构

```
浏览器 (index.html)
    ↕ HTTP JSON API (port 8765)
server.py (Python 原生 HTTP)
    ↓
D:\Games\X4 exout\          ← 原版库 + extensions\
    └── extensions\
        └── UP7_Real_EVE_Ships\   ← 目标 mod，diff 补丁式修改
            ├── libraries\        ← shipgroups.xml, material_library.xml, jobs.xml...
            ├── assets\           ← 舰船 XML/模型
            ├── index\            ← macros.xml, components.xml
            └── moding\           ← 工作副本（generate/edit 时同步）
```

核心设计：X4 的 mod 是 diff 补丁机制（`<diff><add sel="...">`），server.py 负责解析原版 XML + 合并所有扩展的 diff，生成/修改/删除时写回目标 mod 的对应文件。

---

## 2. 关键模块

### 2.1 舰船选项卡（新增/修改）

| 卡片 | 功能 | 关键函数 |
|---|---|---|
| ① 基础信息 | 船体/质量/惯性/推进/存储 | `fill()`, `collect()` |
| ② 成本 | 最小/平均/最大成本 + 建造时间 | `loadCostRefs()` |
| ③ 视觉参考 | 从原版船复制视觉配置 | `showRefs()` |
| ④ 挂载点 | 武器/炮塔/护盾/引擎挂载 | `loadMounts()`, `renderMounts()` |
| ⑤ 外观与分类 | 图标/类型/制造商等枚举下拉 | `setSel()` |
| ⑤-1 材质参数 | material_library.xml 调优 | `loadShipMaterials()`, `renderMaterials()` |
| ⑥ AI 派系使用 | jobs（派系/任务勾选） | `loadShipJobs()` |
| ⑥-1 shipgroup 归属 | 加入/新建 shipgroup | `loadShipgroups()`, `addSgRow()` |
| ⑦ 建造成本 | 价格/时间/建造方式 | `loadCostRefs()` |
| ⑧ 挂载点 tags | 按组改 component 挂载 tags | `loadMounts()`, `mtRows()` |
| ⑧-1 macro 连接点 | 编辑 ship macro 的 connections | `loadShipConnections()`, `addMcRow()` |
| ⑨ 装配预设 | loadout 生成 | `autoLoadout()`, `loRows()` |
| 软件 | software 槽位行 | `addSwRow()` |

### 2.1a 属性写入管线（generate/edit 共用，server.py）

| 函数 | 职责 |
|---|---|
| `apply_props(mtxt, d)` | 表单属性 → ship macro。`_sub_or_ins`：目标标签**存在则替换、缺失则在 `</properties>` 前插入标准标签**（自制宏常缺 people/physics/purpose 等）。inertia/drag 整标签替换（不依赖属性顺序）；physics 块整体缺失时组装插入 |
| `_storage_apply(stxt, cargo, makerrace)` | cargo/makerrace → storage macro，同样"有则替换、缺失则插入"（`<cargo max>` / `<identification makerrace>`） |
| `_xml_check(txt)` | **写入前校验护栏**：generate（component/macro/storage）与 edit（macro/storage）全部写入点先验证 XML，非法拒绝写入并报行列号。坏文件进 mod → 游戏加载失败 → 船消失 |

**铁律（explosiondamage 事故教训，2026-10-18）**：替换模式若消费整个自闭合标签（如 `<explosiondamage\b[^>]*?/>`），**替换串必须自带 `/>`**——漏掉会在"表单回填旧值再保存"时截断标签，XML 非法且单测难发现（测试文件常无该标签，只走了插入路径）。改动 apply_props 后必须跑**全字段替换+插入双路径回归测试**（12 组字段 × 解析器验证输出合法性）。

**排错捷径**：船在游戏里不显示 → 先查 `Documents\EgoSoft\X4\<steamid>\debuglog.txt` 搜 LIBXML2 错误，直接给出文件+行号；其次查 debuglog 中 "Error loading component macro"。

### 2.2 装备选项卡

6 类装备（weapon / shield / engine / thruster / turret / missile），每类独立选项卡，共用 `eq` 前缀函数（`eqOnTpl`, `eqOnPick`, `eqClear` 等）。

### 2.2a macro 连接点（⑧-1，ship macro connections）

**对应规则**（原版/DLC/VRO/UP7 实证）：
- component（模型工具/Blender 导出，基础依据）：`<connection name="X" tags="..." group="...">` 带 offset/parts；必含 `space`、`position`、`ConnectionForpart_main`；功能点命名 `con_cockpit` / `con_storage01` / `con_dockarea_*` / `con_dock_xs` / `con_shipstorage*` / `con_buildmodule` / `con_launchtube_*`。
- ship macro（加工）：`<connection ref="组件连接点名">` 引用组件连接点，内挂 `<macro ref="功能宏" connection="入口连接"/>` 挂载部件（bridge/storage/dockarea/dock/buildmodule/launchtube/shipstorage）；内挂宏留空 = 纯转发 `<connection ref="X"/>`。
- macro 变体（_a/_b）：同一组件、不同挂载组合。
- **悬空引用**：macro ref 指向组件中不存在的连接点 → 游戏静默忽略、功能失效（实测 megathron 的 cockpit/storage 均悬空）。前端标红 + 提交拦截。

**数据流**：GET `/api/shipconnections?ship=&source=` → `{component:[{name,tags,group}], macro:[{ref,macro,connection}], macro_file, catalog}`；提交走 collect().macro_connections `{enabled, rows}`。
**写入**：`_apply_macro_connections(mtxt, rows, comp_names, subst)` 整块替换 `<connections>` 块；ref 必须在组件连接名集合内；占位符 `{STORAGE}`/`{DOCKAREA}` 在 generate（新宏名）与 edit（现有宏名）分别代入；generate 还会把编辑行里的模板 storage/dockarea 原名映射到新宏名。

**宏清单 catalog**（`macro_catalog()`，进程内缓存，`_refresh_soft` 失效）：
- 扫原版+全部扩展 `assets/**/macros/`，按文件名前缀分 7 类：bridge / storage / dockarea / dock / launchtube / shipstorage / buildmodule（**dockarea_ 必须先于 dock_ 判断**），实测共 607 个宏。
- 每宏解析入口连接候选：优先宏自身 `<connections>`；无则回退读其 component 文件（宏文件同级上一级目录），component 回退结果按白名单过滤：`con_*` / `ShipConnection` / `object` / `ConnectionNN`，排除 ConnectionFor*（LOD/动画/贴花）等几何噪音。
- 前端内挂宏下拉：全量分类标注（`[bridge] 入口:con_cockpit · bridge_arg_l_01_macro`）+ `{STORAGE}`/`{DOCKAREA}` 占位符置顶 + 当前船已引用宏；入口 connection 下拉：选定宏后切为其自身连接候选 + 惯例预设。

**入口默认值**（`mcDefaultConn`）：`{STORAGE}`→ShipConnection、`{DOCKAREA}`→Connection01、**buildmodule_*→object**（入口定义在其 component `generic_buildmodule`，宏自身 conns 是 buildprocessorconnection_* 不能用）；其余按类别语义（cockpit/storage/dock/launch）在宏连接候选中挑，退回 ShipConnection/ConnectionNN/首个。

**缺失检查**（`renderMc` 内实现）：
- **component（舰船 XML）问题 → 仅提示不拦截**：①硬锚点缺失（space/position/主船体 part 连接）；②重名连接点（name 是全局查找键，重名会导致挂载歧义；原版零重复，Blender 导出器默认全局编号）；③macro 引用了但组件缺失的连接点（悬空引用归入此类）。措辞"需在 Blender 修复后重新导出，工具无法修改"。
- **功能连接点未挂载 → 补全行**：组件里有、macro 行里没有的功能点，自动在列表末尾生成补全行（ref 预填、内挂宏留空标红催填）；已有行内挂留空的功能 ref 同样标红。功能类别判定 `mcFuncClass`：shipstorage/dockarea/launchtube/buildmodule/cockpit/storage/dock（按 name+tags，**dockarea 先于 dock**）。
- **不属于本模块的连接点**（实测确认，勿加进补全逻辑）：`con_countermeasures_*`（诱饵发射器走 loadout，全游戏无 macro 挂载）、`con_playercontrol`（逻辑锚点，不挂宏）。
- **入口 connection 合法性（2026-10-19 新增，megathron 事故教训）**：内挂宏的入口名必须是"该宏实测存在的入口"。判据 = ① 原版/DLC/扩展舰船宏里的实际挂法（`obs`）+ ② 该宏自身/其 component 的连接点（`conns`）；两者都空 → 无法判定，跳过校验。**同族同名宏入口名不同**（boron bridge = `con_cockpit_01`，argon bridge = `con_cockpit`），不能凭惯例猜。写错 → 游戏静默忽略该挂载 → 功能失效（典型症状：不能指派船长、船不能操控、登船无舰桥），且 debuglog 会报 `no slot for that post (missing connection with controltag)`。
  - **数据流**：`macro_catalog()` 在同一次 `macros` 目录扫描中顺带收集 `ship_*_macro` 里的 `<macro ref=X connection=Y>` 实测挂法，写入 catalog 每条 `obs`；`_macro_entry_info(name)` 返回 `(valid, suggest)`，经 `/api/shipconnections` 逐行下发 `valid`/`suggest`。
  - **前端**：`mcEntryInfo()` 判定合法性 → 非法行标红 + 提示"应为 X"；`mcDefaultConn()` 优先取 `obs[0]`（实测值）自动补全入口，再退回类别语义/预设；`renderMc` 汇总非法项到提示区。
  - **后端**：`_apply_macro_connections` 对写出的 `connection` 做同一校验，非法拒绝写入。
- 提交拦截范围：悬空 ref、填了内挂宏但缺入口 connection、**内挂宏入口 connection 非法**；纯转发（内挂全空）允许。

### 2.3 通用交互

| 机制 | 说明 | 关键函数 |
|---|---|---|
| 模式切换 | 新增/修改，localStorage 记忆 | `modeSwitchEx()` |
| 暂存/回填 | 浏览器 localStorage 草稿 | `stashDraft()`, `unstashDraft()` |
| 下拉选择 | 自定义 ssel 组件（输入筛选+隐藏值） | `ssel()`, `sselSet()`, `sselGet()` |
| 生成/写入 | 把表单数据写入 mod 文件 | `doSave()` → `generate()`/`edit()` |
| 删除物品 | 删除舰船/装备，含反向引用检查 | `delItem()` → `delitem()` |

---

## 3. 材质系统（material_library.xml）

### 3.1 引用链

```
macro (.xml)
  ↓ <macro class="ship_xl" ...>
component (.xml)
  ↓ <material id="1" ref="collection.material" />
material_library.xml
  ↓ <collection name="xxx"><material name="yyy" ...>
```

### 3.2 改名语义（按模式区分）

| 模式 | 行为 | 说明 |
|---|---|---|
| 修改 | **替换** | 就地重命名原材质，同时更新全 mod 所有引用该材质的 component |
| 新增 | **克隆** | 克隆原材质为新副本，仅新船 component 换用新材质，原材质不动 |

### 3.3 删除时的孤儿清理

`delitem` 删除舰船时：
1. 从本船 component 收集 `<material ref="coll.mat">` 引用；
2. 对每个引用，检查是否在本 mod `material_library.xml` 中有定义；
3. **反向引用扫描全 `extensions/`**：只要还有任何其他 mod 的 component 引用该材质，就保留；
4. 无引用的材质定义块删除，空的 `<collection>` 一并清理。

> 注意：原版/其他 mod 定义的材质不在本 mod 材质库中，自动跳过，不会误删。

---

## 4. 删除物品（delitem）

### 4.1 删除范围

- 宏文件（`{id}_macro.xml`）
- 组件文件（`{id}.xml`）
- 动画文件（`{id}_data.ani`）
- `_data` 目录（模型/贴图）
- 注册文件清理：
  - `index/macros.xml`、`index/components.xml`
  - `libraries/wares.xml`（ware 条目）
  - `libraries/shipgroups.xml`（select 条目）
  - `libraries/jobs.xml`（job 条目）
  - `t/0001-l044.xml` 等语言文件（文本条目）

### 4.2 安全机制

1. **反向引用检查**：扫描全 `extensions/` + 原版 assets，任何其他文件引用该 id 即阻止删除；
2. **target_mod 路径兼容**：支持完整路径和 `extensions` 下目录名两种形式；
3. **id 格式**：`sselGet` 返回 `id@@source`，前端必须 `.split("@@")[0]` 提取纯 id 再传给后端。

### 4.3 已知问题

- `delitem` **不备份**（删除即真删，无法恢复）；
- `delitem` **不同步** `moding/` 目录（与 generate/edit 行为不一致）。

---

## 5. 模式切换与表单生命周期

### 5.1 modeSwitchEx 统一助手

```javascript
modeSwitchEx(key, newMode, clearSels, onApply)
```

- `key`：localStorage 键（如 `x4sb_mode`, `x4sb_eqmode_weapon`）
- `clearSels`：模式变化时要清空的 ssel 元素 id 列表
- `onApply(mode, changed)`：各选项卡自己的区块切换与表单清空/回填

**调用规则**：
1. 首次调用：恢复 localStorage 记忆的模式（不算切换、不清理）；
2. 之后调用：写回 localStorage；模式真正变化时清空 `clearSels`；
3. 恢复草稿等程序化场景：先 `modePreset(key, mode)` 同步登记，再调 `modeSwitchEx`，避免误判为切换而清空。

### 5.2 生命周期函数对照

| 函数 | 新增模式 | 修改模式 | 说明 |
|---|---|---|---|
| 入口 | `onTpl()` | `onPick()` | 下拉选择变化时调用 |
| 清空 | `clearShip()` | `clearShip()` | 清空所有表单字段 |
| 材质 | `loadShipMaterials()` | `loadShipMaterials()` | 异步读取材质参数 |
| shipgroup | `loadShipgroups()` | `loadShipgroups()` | 异步读取分组列表 |
| Jobs | — | `loadShipJobs()` | 新增模式不加载（新船无 jobs） |
| 挂载点 | `loadMounts()` | `loadMounts()` | 异步读取挂载点 |
| 装配预设 | `autoLoadout()` | `autoLoadout()` | 异步读取装备宏 |

> **重要**：修改任何生命周期函数时，必须同时检查新增和修改两条路径，确保行为一致。

---

## 6. 常见坑与注意事项

### 6.1 ssel 下拉组件

- `sselGet` 返回 `id@@source` 格式，需要 `.split("@@")[0]` 提取纯 id；
- `sselSet` 不会触发 `change` 事件，需要手动调用后续逻辑；
- 选项列表是引用传递，异步更新 `SG_OPTS` 后已创建的行不会自动刷新。

### 6.2 材质模块

- `loadShipMaterials` 有 `ML_SEQ` 序号守卫，防止旧响应覆盖新船；
- `ML_PENDING` 绑定 `CUR_SHIP`，草稿回填只在同船时生效；
- 改名时修改模式=替换，新增模式=克隆，后端逻辑完全不同。

### 6.3 路径处理

- 前端 `target_mod` 统一存完整路径（`D:\Games\X4 exout\extensions\UP7_Real_EVE_Ships`）；
- 后端 `generate`/`edit` 直接当完整路径用；
- 后端 `delitem` 兼容完整路径和目录名两种形式。

### 6.4 缓存刷新

- `_refresh_soft()`：清 t 文本表、wares 索引、组件内容缓存、材质/视觉参考缓存；
- `eq_cache_refresh_source()`：装备缓存增量维护；
- `bullet_cache_refresh_source()`：弹丸缓存增量维护。

---

## 7. 文件清单

```
EVE_Ship_Builder/
├── index.html              ← 前端单文件（全部 UI + JS）
├── server.py               ← 后端单文件（全部 API + X4 解析）
├── 启动服务.bat             ← 双击启动服务
├── builder_config.json     ← 表单状态持久化（自动生成）
├── jcs_backup/             ← generate/edit 自动备份
├── docs/                   ← 本文档目录
│   └── MAINTENANCE.md      ← 本文件
└── *.py                    ← 其他辅助脚本（test_*.py 等）
```

---

## 8. 快速排错清单

| 症状 | 检查点 |
|---|---|
| 删除报"未找到该物品文件" | 前端 id 是否带 `@@source`；target_mod 路径格式 |
| 切模式后表单残留旧数据 | `modeSwitchEx` 的 `clearSels` 是否包含对应下拉 |
| 材质列表闪回上一艘船 | `ML_SEQ` 守卫是否生效；`clearMaterials` 是否被调用 |
| 分组列表"无匹配" | `onTpl` 是否调用 `loadShipgroups`；`SG_OPTS` 是否为空 |
| 修改后材质参数没生效 | `ml_enable` 是否勾选；改名语义是否匹配模式（修改=替换/新增=克隆） |
| 服务启动失败 | 端口 8765 是否被占用；Python 版本是否 3.9+ |

---

## 9. 更新记录

| 日期 | 内容 |
|---|---|
| 2026-10-23 | **方案A：jobs↔shipgroups 接线改造**（正向机制研究归档见 [JOBS_SHIPGROUPS_MECHANISM.md](JOBS_SHIPGROUPS_MECHANISM.md)）。① `libraries/shipgroups.xml` 新增 52 个约定名组：26 个 job 派系 × 需要的尺寸（`{prefix}_battleship_xl` 装 6 艘 XL、`{prefix}_battleship_l` 装 12 艘 L，权重 30/20）；无独立前缀的派系（player/ministry/hatikvah/alliance/fallensplit/criminal）同时建「完整 id」与「猜测短码」两套组名提高命中率。② 与 VRO/XR_ShipPack 同名的 6 个 XL 组（bor/hol/par/spl/tel/tri）改用 `<add sel="//groups/group[@name='...']">` 注入，避免重复定义报错并保留对方战舰；`content.xml` 增加 `ws_1696862840`(VRO)、`xr_shippack` 可选依赖保证加载顺序。③ `libraries/jobs.xml` 135 条 `<select>` 的 tags 由 `[military]` 改为 `[military, battleship]`（military 保留以兼容 buc/ter/spl 系带 military 的组名）。④ 原 `UP7_EVE_battleship_xl_01`/`_l_01` 保留不删（已不可达）。备份：`D:\Games\X4 exout\UP7_Real_EVE_Ships_backup_20261023\`。验证：两侧 XML 校验通过、组名冲突 0、残留 `[military]` select 0 |
| 2026-10-22 | **⑧⑨ 同组不同尺寸分栏修复**：`g_bot_01` 等组混编 M 盾+L 炮塔时，旧代码只聚合为一个设置栏（无法分别设装备），修复后按「组+尺寸」拆栏。识别逻辑：`connSize()` 取挂载点名中的 `_es-`/`_s-`/`_m-`/`_l-`/`_xl-`/`_exl-`（前置必须是 `_`，交替最长优先），名字无则按 tags 兜底。涉及 `fillLoGroups`（分组键改为 group\|size）、`addLoGroup`/`addMtGroup` 标签显示尺寸、`autoLoadout`/`restoreLoadout` 回拆按尺寸逐条、`mtRows`/`loRows` 服务端零改动（原逐条输出 `<shields/turrets group exact>` 天然兼容同组多条）。实测 megathron：M 盾 4 个 / L 炮塔 1 个各一行，标签如「组:g_bot_01（M · 4个）」「组:g_bot_01（L · 1个）」 |
| 2026-10-19 | **⑧-1 新增「入口 connection 合法性」检测（megathron 事故教训）**：`bridge_bor_l_01_macro` 入口在 boron 族是 `con_cockpit_01`（argon 族才是 `con_cockpit`），写错 → 悬空挂载 → 游戏报 `no slot for that post (aipilot)` → 不能指派船长/不能操作/登船无舰桥/建造界面报缺必备升级。判据取「原版/DLC/扩展舰船宏实测挂法（新增 catalog `obs` 字段）+ 宏自身/component 连接点」；前端 `mcEntryInfo` 标红并提示应为值、`mcDefaultConn` 优先用实测值自动补全、非法行纳入提交拦截；后端 `_apply_macro_connections` 同校验拒绝写入 |
| 2026-10-19 | **megathron 修复**：`storage_bor_l_megathron_macro.xml` 补 `<component ref="generic_storage"/>`（缺失 → debuglog `Failed to create macro ... no template '' found`）、cargo 补 `tags="container"`、补 `<hull integrated="1"/>`、清除非标准 `capacity`/`volume`；`ship_bor_l_megathron_macro.xml` 的 storage 入口改 `ShipConnection`、bridge 入口改 `con_cockpit_01` |
| 2026-10-18 | **explosiondamage 吃 `/>` bug（用户挑战后实锤）**：apply_props 重写时 explosiondamage 替换模式消费整个自闭合标签、替换串却漏了 `/>`，重复保存即截断标签→XML 非法→macro 不加载→船消失（jcs_backup 链证明：该标签 2025-12 起一直存在且合法，22:58 保存首次跑替换路径时弄坏）。已修复替换串；回归测试 7 项（三轮连续保存、megathron 场景复现、12 组字段替换+插入全路径 XML 合法性）。**铁律：替换模式消费整标签时，替换串必须带完整闭合；新增全路径回归测试后再上线** |
| 2026-10-18 | **megathron 游戏内不显示排查**：debuglog 实锤 `ship_bor_l_megathron_macro.xml` 第 23 行 `<explosiondamage ...` 缺 `/>` 自闭合（根因见上一条，系 apply_props bug）。已修复文件，全 mod XML 体检通过。**新增 `_xml_check` 写入前校验护栏**（generate：component/macro/storage；edit：macro/storage），坏 XML 拒绝写入并报行列号。教训：排"船不显示"先看 `Documents\EgoSoft\X4\<id>\debuglog.txt` 搜 LIBXML2 错误，直接定位文件+行号 |
| 2026-10-18 | **apply_props 缺失兜底（重要）**：自制宏常缺标准标签（megathron 无 people/physics/inertia/drag/purpose/thruster/secrecy/ship type；其 storage macro 用非标准 `<capacity>` 而非 `<cargo max>`），原 replace-only 正则静默失败→字段保存后丢失。现 `_sub_or_ins`：有则替换、缺失则在 `</properties>` 前插标准标签；inertia/drag 改整标签替换（不依赖属性顺序）、physics 块整体缺失时组装插入；`_storage_apply` 统一 generate/edit 的 cargo/makerrace 写入（缺失时插 `<cargo max>`/`<identification makerrace>`）。22 项单测全过（含幂等、原版文件不破坏、读侧回读） |
| 2026-10-18 | ⑧-1 增强：宏清单全量扫描 catalog（607 宏/7 类，component 回退+白名单过滤）、入口下拉按所选宏切换、mcDefaultConn 语义默认值（buildmodule→object）、功能点补全行、component 缺失提示（硬锚点+悬空引用归 Blender 侧）、countermeasures/playercontrol 确认排除 |
| 2026-10-18 | 新增 ⑧-1 macro 连接点模块：组件/macro connections 对应规则研究、读取接口 /api/shipconnections、generate/edit 整块替换写入（悬空 ref 拦截 + {STORAGE}/{DOCKAREA} 占位符）、前端行编辑 UI（复用 ssel + PENDING 兜底 + MC_SEQ 竞态守卫） |
| 2026-10-17 | 初版。整合本次会话修复：材质竞态、模式切换重构、delitem 路径兼容、孤儿材质清理、新增模式 loadShipgroups 缺失、delItem id 格式修复 |
