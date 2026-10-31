# 组件缩放导出 —— 交给 Blender 插件对话的需求书

> 交接文档。X4 侧（XML 接线、校验、日志验收）由 EVE_Ship_Builder 对话负责；
> 本文只定义 **Blender 侧必须产出什么、什么不能变、验收标准**，不规定实现方式。

## 0. 前提结论（已实测，勿再推翻）

- X4 引擎 **没有实例级缩放**：组件挂点的 `<offset>` 只有 `<position>` / `<quaternion>`；
  全库 `scale="` 只出现在 `bullet` / `effect` / `particle`（特效参数，与网格无关）。
- 网格是二进制 `XUMF`（`.xmf` 文件头 `XUMF`），无法文本改坐标。
- 因此"炮塔放大 1.5 倍"的唯一实现路径 = **Blender 侧产出已缩放的模型资产**，X4 侧只做改名接线。

## 1. 输入 / 输出契约

输入：源组件 id（如 `turret_arg_l_beam_01_mk1`）、缩放倍数 `k`（如 1.5）、目标新 id（如 `turret_arg_l_beam_01_mk1_x150`）

输出（目录结构沿用 ego Blender Tools 导出习惯）：

```
assets/props/WeaponSystems/<类别>/<新id>.xml          ← 组件 XML
assets/props/WeaponSystems/<类别>/<新id>_data/        ← 模型数据
    <part>-lod0.xmf … -lod3.xmf
    <part>-collision.xmf（及 -collision1.xmf，若源有）
    <part>-mesh.jcs / <part>-hull.jcs（可选，按既有同步规则处理）
    （可不需要 .sig：mod 目录加载不校签）
    _data.ani（源有才导）
```

## 2. 必须按 k 同比缩放的项（漏任何一项都会在游戏里出问题）

1. 网格顶点（全部 LOD、全部 part、含碰撞网格）
2. **所有 connection 的 `<offset><position>`** —— 含 `con_laser_01/02`（炮口）、`con_aimtarget_01`、
   各 `ConnectionNN` 的装配偏移
3. `part` 的 `<size>` / `<size_raw>` 的 `max` / `center`
4. `<pivot><offset><position>`（对象原点偏移）
5. 动画中**与位移相关**的量（纯旋转角度、`restrictions` 上下限**不变**）

## 3. 必须原样保留的项

- 连接点 **名称**（`con_laser_01` 等被引擎按名字引用）、`parent` 层级、`tags`
- 材质 id / `ref`（复用原材质，不复制贴图）
- UV、LOD 数量、`restrictions type="rotation_x/y"` 的角度限制
- 动画帧号与动画名称（`turret_active`、`gun_firing` 等）

## 4. 验收标准（Blender 侧自测，X4 侧复核）

- [ ] 炮塔绕 Y 轴旋转（`detail_xl_rotator`）与俯仰（`detail_xl_gun`）时 **枢轴不漂移**、转动中心仍在原位
- [ ] `con_laser_01/02` 正好落在放大后的炮管口（否则弹丸从炮管内部射出）
- [ ] `<size>` 与实际模型包围盒一致（影响选择框与剔除）
- [ ] 导出的组件 XML 通过 XML 校验；所有 `geometry` 路径指向 **实际存在的目录**
      （本项目刚踩过：geometry 指向不存在的 `_data` → `collisionMeshFile ... is invalid` → 玩家上船僵死）
- [ ] 源组件文件不被覆盖；新 id 与源 id 不同名

## 5. 命名约定

- 倍数写进 id：`k=1.5` → 后缀 `_x150`（避免小数点）；`k=2` → `_x200`；具体后缀可由用户覆盖
- 组件 id、`_data` 目录名、内部 part 文件名不动（只改外层 id）

## 6. X4 侧（本对话负责，Blender 侧不用管）

- 新 macro：`<macro name="<新id>_macro" class="turret">`，`<component ref="<新id>"/>`；
  `<bullet>` / `<rotationspeed>` / `weapon angle` / `identification` 沿用原宏，仅改 name
- `index/components.xml` + `index/macros.xml` 注册（value 用**不带 .xml** 的路径）
- 若要能在装备站购买：`libraries/wares.xml` 加 `<ware>`（size 标签须与挂点 `tags` 匹配）
- 舰船挂点接线：`con_turret_*` 的 tags 与炮塔尺寸一致；默认装配 or 装备购买二选一
- 上线验证：启动日志 grep 无 `Could not find file` / `collisionMeshFile ... is invalid` / 悬空宏

## 7. 交给 Blender 对话的最小任务清单

1. **确认 ego Blender Tools 是否按世界变换导出**（object scale ≠ 1 时网格与子对象是否被正确烘焙）；
   若忽略 scale → 增加"apply scale 后再导出"前置步骤，或导出时烘焙
2. 让现有组件插件（`X4_blender42_add_components_fixed_addon.py`）写回的 connection offset
   **支持一个全局倍数 k**（现在是按世界坐标算的，缩放后需同比）
3. 产出一份 3~5 步的"缩放导出"操作说明（面向用户）
4. 用 `turret_arg_l_beam_01_mk1` × 1.5 做一次端到端测试用例，产物按 §1 目录结构交付

## 8b. 硬约束：material id 顺序必须与所用 _data 同源（2026-10-30 实测）

- 实测对象：`turret_par_l_plasma_01_mk1` ×1.5（ego 导出 vs 另一插件导出）
- 两份 XML 的几何缩放都正确，但 **lod 内 `<material id>` 的编号顺序不同**：
  - ego 导出：`part_socket` id1=`paranid.paranid_p1_hullpattern_01`, id2=`generic.generic_p1_hulltexture`（与**原版**一致）
  - 另一插件导出：id1/id2 相反；`detail_m_socket` 五个材质整体顺序也不同（按 Blender 材质槽顺序排列）
- `.xmf` 里存的是**面→material id 的索引**，所以 XML 的 id→ref 映射必须与生成该 `.xmf` 的那一方一致。
  → **跨源混用（ego 的 `_data` + 插件自写的材质表）= 贴图/材质错乱**（不崩溃，但外观错）。
- 结论：若要"`_data` 用 ego、XML 由插件一步产出"，插件的材质表必须**直接沿用 ego XML（或原版 XML）的 id 顺序**，不得按 Blender 材质槽重新编号。
- 另：ego 导出缺 `container tags="contents" value="0"`、少 2 处 `size_raw`、`<layer/>` 为空；这些需后处理补上（不影响几何）。

## 8. 需要 Blender 侧回答、我再定接线的问题

- 缩放基准：以组件局部原点 `(0,0,0)` 等比缩放，还是以安装面/枢轴点为基准？（决定挂点高度是否跟着变）
- 动画 `.ani` 里是否含位移关键帧（若有，需按 k 乘，纯角度不动）
