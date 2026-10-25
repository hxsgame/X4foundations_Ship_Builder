# X4 jobs.xml ↔ shipgroups.xml 调用机制（机制研究归档）

> 归档日期：2026-10-23
> 研究对象：X4 Foundations 4.x（含 DLC / 已装扩展）
> 依据：`D:\Games\X4 exout` 本地数据实证（951 条原版+DLC select × 452 个组名全量拟合）
> 适用：`UP7_Real_EVE_Ships` 等 mod 的舰船派发改造

---

## 1. 全链路一旦看清

```
jobs.xml                         shipgroups.xml
─────────                        ──────────────
<job id=...>
  <category faction=X tags=[..] size=ship_Y/>
  <quota galaxy=... />
  <location class=... macro=... faction=.../>
  <environment buildatshipyard=true/>
  <ship>
    <select faction=X tags=[..] size=ship_Y/>   ──命名约定解析──┐
    <owner exact=X overridenpc=true/>                          │
  </ship>                                                      ▼
  <orders><order order="Patrol"/></orders>              <group name="X角色尺寸">
                                                          <select macro=... weight=n/>
                                                        </group>
                                                               │ 按 weight 加权抽签
                                                               ▼
                                                        舰船 macro → 建造 → owner → orders
```

关键点：

1. **job 从不直接写组名**。`<select>` 只有 `faction` / `tags` / `size` 三个属性；951 条样本中 **0 条**使用 `group=` / `macro=` / `exact=`。
2. 引擎用「派系前缀 + tags 组合 + 尺寸字母」拼出组名，去 `shipgroups.xml` 找同名 `<group>`。
3. 找到组后，在组内 `<select macro=... weight=n>` 之间按 weight 加权随机抽一艘。
4. 抽到的 macro 即实际建造的舰船；`<owner exact>` 决定归属（`overridenpc="true"` 时强制覆盖）。
5. `buildatshipyard="true"` 表示该 job 的船由船厂真实建造（消耗资源、可见于船厂队列）；否则直接刷出。

---

## 2. 组名解析规则（拟合结论）

组名 = `{派系前缀}_{角色tag}_{尺寸字母}`，其中「角色tag」来自 `<select tags="[...]">`，`military` 常被丢弃。

拟合统计（951 条 select 对 332 个原版+DLC 组名）：

| 匹配策略 | 命中数 | 说明 |
|---|---|---|
| 精确全名（前缀 + 全部 tags + 尺寸） | 394 / 951 | 例：`[military]` → `spl_military_m` |
| 逐级丢弃首个 tag | 588 / 951 | 例：`[military, fighter]` → `arg_military_fighter_s` 不存在 → `arg_fighter_s` 存在 |
| tag 任意子集（不要求顺序/连续） | 645 / 951 | 覆盖大部分边缘写法 |

- **`military` 是否保留取决于派系**：argon/antigone/paranid/teladi 系的组名不含 military（`arg_destroyer_l`、`par_frigate_m`）；buc / ter / pio / spl / frf / cub / yak 系保留（`buc_military_m`、`ter_military_m`、`spl_military_m`、`yak_military_s`）。
- 因此写 job 时 `tags="[military, xxx]"` 是**安全写法**：引擎会先试带 military 的组名，失败后丢弃 military 再试 `xxx`。
- 引擎找不到任何匹配组时的兜底行为（静默失败 / 退回同尺寸任意船）**无法从数据证明**，因此改造 mod 时必须保证组名可解析。

---

## 3. 派系前缀实测表

从 15 个 shipgroups.xml（原版 + DLC + 已装扩展，共 454 组）中统计出的真实前缀：

| 派系 id | 组名前缀 | 证据 |
|---|---|---|
| argon | `arg` | `arg_destroyer_l`、`arg_fighter_s` |
| antigone | `ant` | `ant_destroyer_l` |
| boron | `bor` | VRO `bor_battleship_xl` |
| paranid | `par` | `par_destroyer_l` |
| holyorder | `hol` | `hol_builder_xl`、VRO `hol_battleship_xl` |
| holyorderfanatic | `hol` | 共用圣教团船 |
| teladi | `tel` | `tel_builder_xl`、VRO `tel_battleship_xl` |
| split | `spl` | `spl_military_m`、VRO `spl_battleship_xl` |
| freesplit | `frf` | `frf_military_m`、`frf_fighter_s` |
| court | `cub` | `cub_military_m` |
| trinity | `tri` | VRO `tri_battleship_xl` |
| terran | `ter` | `ter_destroyer_l`、`ter_military_m` |
| atf（泰拉特种部队） | `atf` | `atf_battleship_xl`、`atf_destroyer_l` |
| pioneers | `pio` | `pio_military_m` |
| xenon | `xen` | `xen` 系组 |
| khaak | `kha` | `kha` 系组 |
| yaki | `yak` | `yak_military_m` |
| buccaneers | `buc` | `buc_military_m` |
| scaleplate | `sca` | `sca` 系组 |
| loanshark | `loanshark` | `loanshark_pirate_l` |
| scavenger | `scavenger` | `scavenger` 系组 |
| 第三方派系 | `dal` / `dam` / `dga` / `dmi` / `kao` | deadairfaction* / timelines DLC |
| **player** | 无 | 原版没有任何 `player_*` 组 |
| **ministry** | 无（推测回落 `tel`） | 无 `min_*` 组，primaryrace=teladi |
| **hatikvah** | 无（推测回落 `arg`） | 无 `hat_*` 组，primaryrace=argon |
| **alliance** | 无（推测回落 `par`） | 无 `all_*` 组，primaryrace=paranid |
| **fallensplit** | 无（推测回落 `spl`） | 无 `fal_*` 组 |
| **criminal** | 无 | 隐藏派系，无 primaryrace |

> 注意：`factions.xml` 的 `shortname` / `name` 在新版里是文本引用（`{20203,203}`），不能直接当组前缀用；上表来自组名实测。

---

## 4. 组内抽签与权重

```xml
<group name="arg_destroyer_l">
  <select macro="ship_arg_l_destroyer_01_a_macro" weight="100"/>
  <select macro="ship_arg_l_destroyer_02_a_macro" weight="50"/>
</group>
```

- `weight` 是相对权重，不是百分比；同组多条按比例随机。
- 一个 macro 可以同时出现在多个组（xr_shippack 就对多个现有组做了 diff 注入）。

---

## 5. 实证范式：原版 / 扩展怎么加「战列舰」

### 5.1 原版（Terran DLC）

```xml
<!-- ego_dlc_terran/libraries/shipgroups.xml -->
<group name="atf_battleship_xl">
  <select macro="ship_atf_xl_battleship_01_a_macro" weight="100"/>
</group>

<!-- ego_dlc_terran/libraries/jobs.xml -->
<category faction="terran" tags="[military, battleship, fleetphase_2]" size="ship_xl"/>
<ship>
  <select faction="terran" tags="[military, battleship, atf]" size="ship_xl"/>
```

→ `[military, battleship, atf]` 解析为 `atf_battleship_xl`：**military 被丢弃，atf 作为前缀 token**。

### 5.2 xr_shippack（新建约定名组）

```xml
<group name="arg_battleship_xl">
  <select macro="ship_xr_arg_xl_battleship_macro" weight="100"/>
</group>
```
```xml
<select faction="argon" tags="[military, battleship]" size="ship_xl"/>
```
→ 与 `arg_battleship_xl` 完美对应，这是「方案 A」的直接依据。

### 5.3 VRO（同一套命名）

VRO 也定义了 `bor_/arg_/ant_/par_/hol_/tel_/spl_battleship_xl`，说明这套命名是社区通行做法。

---

## 6. UP7_Real_EVE_Ships 原实现的三处断点

| 断点 | 现状 | 后果 |
|---|---|---|
| 组名不符约定 | `UP7_EVE_battleship_xl_01` / `_l_01`：前缀 `UP7` 不是派系前缀，结尾 `_01` 不是尺寸字母 | 任何 select 都拼不出该组名，**永不命中** |
| select tags 太窄 | 135 条 job 全部 `tags="[military]"`，size 仅 `ship_xl` / `ship_l` | 即使组名正确，也只能命中 `xxx_military_xl` 类组；而 argon/teladi 等系根本没有 |
| player 派系无组 | 3 条 player job 用 `faction="player"` | 原版 951 条 select 中 player 出现 0 次，无 `player_*` 组可解析 |
| 附加 | `xr_shippack` 等扩展已定义同名 `arg_battleship_xl` | 再定义会重复；应改用 diff 注入或换独立前缀 |

---

## 7. 改造结论（方案 A）

1. 按派系建约定名组：`{前缀}_battleship_{xl|l}`，每组装对应 EVE 船（`weight` 可调）。
2. job 的 `<select>` 改为 `tags="[military, battleship]"`（military 保留，引擎会自动回退）。
3. 组名与 job 的 `faction` 前缀必须一致；无独立前缀的派系（player/ministry/hatikvah/alliance/fallensplit/criminal）**同时建完整 id 与猜测短码两套组名**（如 `ministry_battleship_l` + `min_battleship_l`），两套内容相同，命中任一套即可。
4. `owner exact` 保持原派系，不影响归属。
5. 已存在的同名组（xr_shippack / VRO）不要重复 `<add>`：在 `content.xml` 用 `optional="true"` 依赖把本 mod 排到它们之后，再以 `<add sel="//groups/group[@name='...']">` 注入，可保留对方战舰且不产生重复定义报错。

> 相关维护记录见 `MAINTENANCE.md` 变更表。
