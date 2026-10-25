# -*- coding: utf-8 -*-
"""
X4 dock 硬点导出脚本（Blender 4.x，Text Editor 里直接 Run Script）。

与「智能组件放置器」addon v9.16.15 的航路导入/导出逻辑完全一致：

===================== 硬点命名与类型 =====================

1. 硬点分两类：``waypoint``（航路点）和 ``dockingbay``（泊位连接点）。
2. 物体名 = ``group + 连接符 + name``，连接符默认 ``---``（可在 addon 的
   wp_name_separator 中自定义，本脚本优先读取该设置）。
   - ``group`` 与 ``name`` 都不允许含连接符（与分隔符冲突）。
   - 物体名不含连接符 → 没有分组（group 为空）。
   - 导出时从左起第一个连接符截断：左边 = group，右边 = name。
   - 例（连接符为 ``---``）：``mt_dock_01---waypoint_01`` → group=mt_dock_01,
     name=waypoint_01；``waypoint_01`` → group=（空）, name=waypoint_01。
   - 旧文件兼容：waypoint 的 group/name 若含连接符，导出时自动替换为 ``_``；
     dockingbay 的 group/name 若含连接符，报错中止（需用户先在 XML 中改为 ``_``）。
3. 硬点类型由物体自定义属性 ``hardpoint_type``（值为 ``waypoint`` / ``dockingbay``）
   决定；若未设置，则按物体名自动识别（含 ``dockingbay`` → dockingbay，
   含 ``waypoint`` → waypoint）；仍识别不出则默认 ``waypoint``。
   新建物体只会是 waypoint；dockingbay 由导入 XML 生成，只改 group 不改名字/数量。

===================== waypoint 自定义属性 =====================

- ``tags``（字符串）：tags 全文，空格分隔。**只允许下列游戏词汇表**：
    类型(必选一):  typenormal / typedock / dockpath
    端点:          start / end
    分组:          blocklink（start/end 成对）/ closelink / force
    速度:          speed_slow / speed_normal / speed_fast / speed_faster
    尺寸:          sizeLevel1 / sizeLevel0
    其它:          dynamicmasstraffic
- ``links``（字符串，可省略）：出边目标物体名（带 group---前缀的 Blender 物体名），
  空格分隔；导出时自动映射回基础名。

===================== 坐标系 =====================

Blender Z-up → X4 Y-up，脚本自动换算 (x, z, -y)，比例 1:1 米。

===================== 导出范围 =====================

默认导出**全部硬点**（waypoint + dockingbay）；若选中了任一硬点，则只导出选中的。

===================== 合法性检查 =====================

- waypoint 组名集合 与 dockingbay 组名集合 必须相互对应；
  不对应时给出警告（不阻断 XML 输出）。

===================== 产出格式 =====================

单个 ``<waypoints>`` 根节点，内含：
- ``<waypoint name= tags= group? x y z qx qy qz qw>``（含 ``<links>``）——航路点；
- ``<dockingbay name= group?/>``——泊位连接点，只输出 name/group，
  供后续工具（EVE_Ship_Builder dock_clone）按名定位对应 connection 并更新 group。
"""
import bpy
from mathutils import Quaternion
from bpy_extras.io_utils import ExportHelper

# Blender Z-up → X4 Y-up 的坐标变换四元数（绕 X 轴 -90°）
_C = Quaternion((0.70710678, -0.70710678, 0.0, 0.0))  # (w, x, y, z)
_C_INV = _C.inverted()

# 连接符：group 与 name 之间的分隔。优先读 addon 的 wp_name_separator 设置，
# 未安装 addon 时回退到默认 "---"（与 addon 默认值一致）。
def _get_sep():
    try:
        s = bpy.context.scene.component_settings_fixed.wp_name_separator
        return s if s else "---"
    except Exception:
        return "---"


_SEP = _get_sep()

# 游戏 waypoint tags 词汇表（与 server.py 的 _WP_TAGS、addon 的 WP_TAG_VOCAB 保持一致）
WP_TAGS = {"typenormal", "typedock", "dockpath", "entrypath", "exitpath",
           "start", "end", "blocklink", "closelink", "force",
           "sizeLevel0", "sizeLevel1",
           "speed_slow", "speed_normal", "speed_fast", "speed_faster",
           "dynamicmasstraffic"}


def _detect_hp_type(obj):
    """硬点类型：自定义属性 hardpoint_type → 名称含 dockingbay/waypoint → waypoint。"""
    hp = str(obj.get("hardpoint_type") or "").strip().lower()
    if hp in ("dockingbay", "waypoint"):
        return hp
    nl = obj.name.lower()
    if "dockingbay" in nl:
        return "dockingbay"
    if "waypoint" in nl:
        return "waypoint"
    return "waypoint"


def _is_hardpoint(obj):
    return obj.get("hardpoint_type") is not None or obj.get("tags") is not None


def _collect_objects(context):
    sel = [o for o in context.selected_objects if _is_hardpoint(o)]
    if sel:
        return sel
    coll = context.collection
    if coll is None:
        return []
    return [o for o in coll.all_objects if _is_hardpoint(o)]


def _convert(obj):
    """返回 (x,y,z, qx,qy,qz,qw) X4 坐标系下的值。"""
    m = obj.matrix_world
    p = m.translation
    q = m.to_quaternion()
    x, y, z = p.x, p.z, -p.y
    qq = _C @ q @ _C_INV
    return x, y, z, qq.x, qq.y, qq.z, qq.w


def _fmt(v):
    s = "%.7g" % v
    return "0" if s in ("-0", "-0.0", "") else s


def _validate(wps):
    """游戏约束判定。wps 元组：(hp_type, name, group, tags_str, links_list)。
    waypoint 校验 tags/links；dockingbay 只校验 name/group 不含 ---；
    组对应检查为警告，不阻断输出。"""
    errs, warns = [], []
    wp_entries = [w for w in wps if w[0] == "waypoint"]
    db_entries = [w for w in wps if w[0] == "dockingbay"]

    # dockingbay：name/group 禁止含 ---（与连接符冲突），需用户处理
    for _t, name, group, _tags, _links in db_entries:
        if _SEP in name or _SEP in group:
            errs.append("dockingbay '%s' 的名称或组名含 '%s'（与连接符冲突），请先改为 '_' 后重新导出"
                        % (name, _SEP))

    names = [w[1] for w in wp_entries]
    name_set = set()
    for n in names:
        if n in name_set:
            errs.append("waypoint 重名: " + n)
        name_set.add(n)
    for _t, name, _g, tags_str, _links in wp_entries:
        tags = tags_str.split()
        if not tags:
            errs.append("%s: tags 为空（至少要有 typenormal/typedock/dockpath 之一）" % name)
            continue
        bad = [t for t in tags if t not in WP_TAGS]
        if bad:
            errs.append("%s: 非法 tags（词汇表外）: %s" % (name, " ".join(bad)))
    for _t, name, _g, _tags, links in wp_entries:
        for lk in links:
            if lk not in name_set:
                errs.append("%s: link 目标不存在: %s" % (name, lk))

    if not errs:
        all_tags = [t for w in wp_entries for t in w[3].split()]
        if "typedock" not in all_tags:
            warns.append("没有任何 typedock 点（typedock 式泊位必需；纯 dockpath 的甲板跑道式 dock 无此标记属正常）")
        bs = sum(1 for w in wp_entries if "blocklink" in w[3].split() and "start" in w[3].split())
        be = sum(1 for w in wp_entries if "blocklink" in w[3].split() and "end" in w[3].split())
        if bs != be:
            warns.append("blocklink start(%d)/end(%d) 不成对" % (bs, be))
        if "sizeLevel1" not in all_tags:
            warns.append("没有 sizeLevel1 标记（typedock 式停靠路径需要；甲板跑道式 dock 可忽略）")
        # 共享路径网（typedock 走廊式）waypoint 不写 group 完全合法；
        # 仅当本文件已存在分组（多泊位）时，才对缺组的 dockpath 给警告。
        any_group = any(w[2] for w in wp_entries)
        for _t, name, group, tags_str, links in wp_entries:
            ts = tags_str.split()
            if "typenormal" in ts and not links and "end" not in ts and "dynamicmasstraffic" not in ts:
                warns.append("%s: typenormal 无出边 link 且非终点（无 end/dynamicmasstraffic），可能是断链" % name)
            if any_group and not group and "dockpath" in ts and "typedock" not in ts:
                warns.append("%s: dockpath 缺 group（本文件已有分组，该点不绑定任何泊位）" % name)

        # 组对应检查：waypoint 组集 与 dockingbay 组集 必须一一对应，否则警告（不阻断）
        wp_groups = {w[2] for w in wp_entries if w[2]}
        db_groups = {w[2] for w in db_entries if w[2]}
        for g in sorted(wp_groups - db_groups):
            warns.append("waypoint 组 '%s' 没有对应的 dockingbay（路径不绑定任何泊位）" % g)
        for g in sorted(db_groups - wp_groups):
            warns.append("dockingbay 组 '%s' 没有对应的 waypoint（泊位没有路径可达）" % g)

    return errs, warns


def build_xml(objs):
    """解析全部硬点并生成 XML。返回 (xml_text, wps)。"""
    # 第一遍：解析每个硬点的导出名、组名与类型。
    # 规则：物体名从左起第一个 --- 截断，左边 group、右边 name；不含 --- 即无分组。
    name_map = {}   # 物体名 → 导出基础名（links 重映射）
    resolved = []   # (obj, hp_type, export_name, group)
    for o in objs:
        hp_type = _detect_hp_type(o)
        if _SEP in o.name:
            group_raw, base_raw = o.name.split(_SEP, 1)
        else:
            group_raw, base_raw = "", o.name
        # 旧文件兼容：waypoint 的 group/name 含 --- 自动替换为 _；
        # dockingbay 保持原样，由 _validate 报错让用户处理。
        if hp_type == "waypoint":
            group = group_raw.replace(_SEP, "_")
            base = base_raw.replace(_SEP, "_")
        else:
            group, base = group_raw, base_raw
        name_map[o.name] = base
        resolved.append((o, hp_type, base, group))

    wps = []
    for o, hp_type, export_name, group in resolved:
        tags_str = str(o.get("tags") or "").strip()
        links_str = str(o.get("links") or "")
        # links 里存的是 Blender 物体名（带 group---前缀），导出时映射回基础名
        links_list = [name_map.get(ln, ln.split(_SEP, 1)[1] if _SEP in ln else ln)
                      for ln in links_str.split() if ln]
        wps.append((hp_type, export_name, group, tags_str, links_list))

    lines = ['<?xml version="1.0" encoding="utf-8"?>', "<waypoints>"]
    # waypoint：完整属性输出
    for o, hp_type, name, group in resolved:
        if hp_type != "waypoint":
            continue
        tags_str = str(o.get("tags") or "").strip()
        links_list = [name_map.get(ln, ln.split(_SEP, 1)[1] if _SEP in ln else ln)
                      for ln in str(o.get("links") or "").split() if ln]
        group_attr = ' group="%s"' % group if group else ""
        x, y, z, qx, qy, qz, qw = (_fmt(v) for v in _convert(o))
        if links_list:
            lines.append('\t<waypoint name="%s" tags="%s"%s x="%s" y="%s" z="%s" '
                         'qx="%s" qy="%s" qz="%s" qw="%s">' % (name, tags_str, group_attr, x, y, z, qx, qy, qz, qw))
            lines.append("\t\t<links>")
            for lk in links_list:
                lines.append('\t\t\t<link ref="%s"/>' % lk)
            lines.append("\t\t</links>")
            lines.append("\t</waypoint>")
        else:
            lines.append('\t<waypoint name="%s" tags="%s"%s x="%s" y="%s" z="%s" '
                         'qx="%s" qy="%s" qz="%s" qw="%s"/>' % (name, tags_str, group_attr, x, y, z, qx, qy, qz, qw))
    # dockingbay：只输出 name/group，供后续工具定位 connection 更新 group
    for o, hp_type, name, group in resolved:
        if hp_type != "dockingbay":
            continue
        group_attr = ' group="%s"' % group if group else ""
        lines.append('\t<dockingbay name="%s"%s/>' % (name, group_attr))
    lines.append("</waypoints>")
    return "\n".join(lines) + "\n", wps


class X4ExportWaypoints(bpy.types.Operator, ExportHelper):
    bl_idname = "x4.export_waypoints"
    bl_label = "导出 X4 dock 硬点"
    filename_ext = ".xml"

    def execute(self, context):
        objs = _collect_objects(context)
        if not objs:
            self.report({"ERROR"}, "没有可导出的硬点（选中或集合内需有带 hardpoint_type/tags 的物体）")
            return {"CANCELLED"}
        txt, wps = build_xml(objs)
        errs, warns = _validate(wps)
        for w in warns:
            self.report({"WARNING"}, w)
        if errs:
            for e in errs:
                self.report({"ERROR"}, e)
            return {"CANCELLED"}
        with open(self.filepath, "w", encoding="utf-8") as f:
            f.write(txt)
        n_wp = sum(1 for w in wps if w[0] == "waypoint")
        n_db = sum(1 for w in wps if w[0] == "dockingbay")
        self.report({"INFO"}, "已导出 %d waypoint + %d dockingbay（%d 条警告）→ %s"
                    % (n_wp, n_db, len(warns), self.filepath))
        return {"FINISHED"}


bpy.utils.register_class(X4ExportWaypoints)
bpy.ops.x4.export_waypoints("INVOKE_DEFAULT")
