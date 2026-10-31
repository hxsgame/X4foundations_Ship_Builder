# -*- coding: utf-8 -*-
"""
UP7 EVE 舰船制作工具 — 本地服务
===============================
功能：从现有 EVE 舰船 mod 的舰船作为模板，复制模型/挂载文件并改名，
生成新舰船全套可用的 X4 XML（ship/storage macro、wares、shipgroups、
t 名称、index 注册），直接写入目标 mod 目录。

运行：python server.py  → 浏览器打开 http://127.0.0.1:8765
"""
import http.server, json, os, re, shutil, socketserver, threading, time, statistics, glob
from x4_lookup import X4Lookup

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE, "builder_config.json")
INDEX_HTML = os.path.join(BASE, "index.html")

# 路径全部来自 builder_config.json（首次使用在「游戏解包」选项卡设置解包根，重启后生效）。
# 代码内不写死任何本机路径，便于分发。
def _cfg_load():
    try:
        return json.load(open(CONFIG_FILE, encoding="utf-8"))
    except Exception:
        return {}

_CFG0 = _cfg_load()
_ROOT0 = (_CFG0.get("root") or "").strip()
ROOT = os.path.normpath(_ROOT0) if (_ROOT0 and os.path.isdir(_ROOT0)) else ""   # X4 解包目录根
MOD_DIR = (_CFG0.get("target_mod") or "").strip() or \
          os.path.join(BASE, "_未设置目标mod")   # 未配置时指向不存在的占位目录，避免误写到工具目录
VANILLA_DIR = os.path.join(ROOT, "assets", "units") if ROOT else ""
BACKUP_ROOT = (_CFG0.get("backup_root") or "").strip() or \
              (os.path.join(ROOT, "_x4sb_backup") if ROOT else os.path.join(BASE, "_backup"))
LX = X4Lookup(ROOT or os.path.join(BASE, "_no_x4_data"))   # 提取/查找/清洗模块（x4_lookup.py）

# 种族代码 -> 派系名 / 显示名
RACE_FACTION = {"spl":"split","ter":"terran","par":"paranid","bor":"boron",
                "xen":"xenon","arg":"argon","ant":"antigone"}
RACE_LABEL  = {"spl":"Split","ter":"Terran","par":"Paranid",
               "bor":"Boron","xen":"Xenon","arg":"Argon"}
SIZE_LABEL  = {"l":"L 级","xl":"XL 级"}

# 可选派系（jobs/AI 归属），name 为游戏内官方中文名
# 来源：扫主 + extensions 各 mod 的 factions.xml，用 load_loc/lname 解析 {20203,xxx} t 引用
# （借鉴 x4_extract.py 名称查找方法；scan_factions3.py 复现）
FACTIONS = [
    {"id":"argon","name":"Argon联邦"},
    {"id":"antigone","name":"安提戈涅共和国"},
    {"id":"paranid","name":"Paranid神界"},
    {"id":"holyorder","name":"教皇圣教团"},
    {"id":"teladi","name":"Teladi公司"},
    {"id":"ministry","name":"财政部"},
    {"id":"split","name":"扎亚斯氏族"},
    {"id":"freesplit","name":"自由部族联盟"},
    {"id":"fallensplit","name":"陨落部族联盟"},
    {"id":"terran","name":"Terran保护国"},
    {"id":"boron","name":"Boron女王国"},
    {"id":"hatikvah","name":"希望之歌自由联盟"},
    {"id":"scaleplate","name":"鳞片公约组织"},
    {"id":"buccaneers","name":"公爵的海盗"},
    {"id":"alliance","name":"约言联盟"},
    {"id":"trinity","name":"三位一体国度"},
    {"id":"xenon","name":"Xenon"},
]
# jobs 任务类型 -> order
JOB_TASKS = [
    {"id":"patrol","name":"巡逻 Patrol","order":"Patrol"},
    {"id":"defend","name":"守卫 Defend","order":"Defend"},
    {"id":"attack","name":"攻击 Attack","order":"Attack"},
]
# jobs 写/读共用的任务白名单与 id 规则（原来散落在 write_jobs/ship_jobs 两处硬编码，改一处忘另一处即读写失联）
_JOB_TASK_IDS = set(t["id"] for t in JOB_TASKS)

def _job_prefix(mod):
    """jobs 条目 id 前缀动态适配目标 mod：目录名小写化、非法字符转下划线（XSD idname 安全：
    字母/下划线开头）。历史版本前缀写死 up7_，读取/去重正则同时兼容两种前缀，旧条目随下次保存自动迁移。"""
    p = re.sub(r"[^a-z0-9_]", "_", os.path.basename(mod or "").lower()).strip("_")
    if p and p[0].isdigit():
        p = "_" + p
    return p or "jobs"

def _job_jid(mac_name, fac, task, prefix="up7"):
    """jobs 条目 id 统一规则：<mod前缀>_<宏名>_<派系>_<任务>。write_jobs 生成 / ship_jobs 解析共用。"""
    return "%s_%s_%s_%s" % (prefix, mac_name, fac, task)

def jobs_skip_warn(jobs_cfg):
    """jobs 已启用但派系/任务未选全时返回警告列表，否则空。
    根治"勾了启用却静默没写→回填为空"：此前 write_jobs 内部静默跳过，UI 无任何提示。"""
    if not (jobs_cfg or {}).get("enabled"):
        return []
    facs = [f for f in (jobs_cfg.get("factions") or []) if f]
    if facs and (jobs_cfg.get("tasks") or []):
        return []
    miss = []
    if not facs: miss.append("派系")
    if not (jobs_cfg.get("tasks") or []): miss.append("任务")
    return ["⑥ AI 派系使用已勾选启用，但%s未选择——jobs 未写入，该船回填 AI 派系将为空" % "、".join(miss)]

# 舰船建造成本参考值（来源：原版 wares.xml 全部 L/XL ship ware 统计；price 为 average，
# 结构 (min, 中位, max)）
COST_REFS = {
    "l":  {"price": (1154890, 2780770, 9791150),  "time": (74, 180, 460)},
    "xl": {"price": (2432440, 10948470, 17540630), "time": (375, 527, 1094)},
}
# 建造材料可选列表（ware id → 中文名；前端显示"中文 · id"）
WARE_MATS = [
    {"id":"energycells","name":"能量电池"},
    {"id":"hullparts","name":"船体零件"},
    {"id":"ore","name":"矿石"},
    {"id":"silicon","name":"硅"},
    {"id":"weaponcomponents","name":"武器组件"},
    {"id":"shieldcomponents","name":"护盾组件"},
    {"id":"engineparts","name":"引擎零件"},
    {"id":"turretcomponents","name":"炮塔组件"},
    {"id":"smartchips","name":"智能芯片"},
    {"id":"advancedelectronics","name":"先进电子元件"},
    {"id":"claytronics","name":"克雷特罗尼克"},
    {"id":"antimattercells","name":"反物质电池"},
    {"id":"superconductors","name":"超导体"},
    # 2026-10-14 补：原版 7.x 新增/常规经济品（原配方高频使用但白名单缺失 → 前端误标"（自定义）"）
    {"id":"antimatterconverters","name":"反物质转换器"},
    {"id":"missilecomponents","name":"导弹部件"},
    {"id":"advancedcomposites","name":"先进复合材料"},
    {"id":"dronecomponents","name":"无人机组件"},
    {"id":"water","name":"水"},
]
# 默认预填的常用材料（原版舰船 100% 使用 energycells+hullparts）
DEFAULT_MATS = [
    {"ware":"energycells","amount":"1264"},
    {"ware":"hullparts","amount":"3336"},
]
# 建造方式 method 固定枚举（游戏定义；启动时扫描全部 wares.xml 扩充，供 method 输入筛选列表）
PROD_METHODS = [
    {"id":"default",    "name":"标准（默认）"},
    {"id":"closedloop", "name":"闭环（再生循环）"},
    {"id":"terran",     "name":"泰伦"},
    {"id":"xenon",      "name":"泽农"},
    {"id":"boron",      "name":"博隆"},
    {"id":"teladi",     "name":"特拉迪"},
    {"id":"recycling",  "name":"回收"},
    {"id":"paranid",    "name":"帕拉尼德"},
    {"id":"split",      "name":"分裂族"},
    {"id":"processing", "name":"加工"},
]
def _scan_prod_methods():
    """扫描解包根全部 wares.xml 的 <production method=>，把固定枚举外的值补进 PROD_METHODS。"""
    known = {m["id"] for m in PROD_METHODS}
    files = []
    p = os.path.join(ROOT, "libraries", "wares.xml")
    if os.path.isfile(p): files.append(p)
    ext = os.path.join(ROOT, "extensions")
    if os.path.isdir(ext):
        for dp, _, fns in os.walk(ext):
            for fn in fns:
                if fn.lower() == "wares.xml":
                    files.append(os.path.join(dp, fn))
    for fp in files:
        try:
            t = open(fp, encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        for mm in re.finditer(r'<production\b[^>]*\bmethod="([^"]+)"', t):
            v = mm.group(1)
            if v not in known:
                known.add(v)
                PROD_METHODS.append({"id": v, "name": v + " [译]"})
# 启动时执行一次扫描扩充
_scan_prod_methods()

# ---- 无名称物品的 ID 词根翻译（贴合游戏语境，兜底显示用）----
_ID_ZH = {
    "ship":"舰船","turret":"炮台","weapon":"武器","shield":"护盾","engine":"引擎",
    "missile":"导弹","bullet":"弹丸","software":"软件","macro":"宏","component":"组件",
    "unit":"无人机","deployable":"无人机","countermeasure":"干扰","ammunition":"弹药",
    "l":"L","xl":"XL","m":"M","s":"S","l1":"L1","l2":"L2","s1":"S1","s2":"S2",
    "arg":"Argon","bor":"Boron","tel":"Teladi","par":"Paranid","spl":"Split",
    "ter":"Terran","kha":"Kha'ak","xen":"Xenon","yon":"约言","ant":"安提戈涅",
    "ali":"约言","pio":"先驱者","hat":"希望之歌","sca":"鳞片公约","buc":"公爵海盗",
    "civ":"平民","vig":"活力","crz":"罪犯","duc":"公爵","hop":"圣教团","tri":"三位一体",
    "fal":"陨落","sav":"清道夫","kai":"凯特","dal":"Caldari","dam":"Amarr",
    "gal":"Gallente","min":"Minmatar","dga":"DGA",
    "heavy":"重型","light":"轻型","standard":"标准","prototype":"原型",
    "experimental":"实验","military":"军用","civil":"民用","police":"执法",
    "pirate":"海盗","miner":"采矿","fighter":"战斗机","frigate":"护卫舰",
    "destroyer":"驱逐舰","carrier":"航母","transport":"运输","freighter":"货船",
    "interceptor":"截击","scout":"侦察","drone":"无人机","thruster":"推进器",
    "storage":"货舱","cargo":"货舱","dock":"停靠","docking":"停靠",
    "beacon":"信标","satellite":"卫星","laser":"激光","beam":"光束","plasma":"等离子",
    "ion":"离子","pulse":"脉冲","cannon":"加农炮","gauss":"高斯","railgun":"磁轨炮",
    "flak":"高射炮","mine":"地雷","torpedo":"鱼雷","smart":"智能","remote":"远程",
    "marker":"标记","hull":"船体","armor":"装甲","repair":"维修","damage":"伤害",
    "range":"射程","speed":"速度","mass":"质量","power":"能量","cell":"电池",
    "energy":"能量","hullparts":"船体零件","weaponcomponents":"武器组件",
    "turretcomponents":"炮塔组件","shieldcomponents":"护盾组件","engineparts":"引擎零件",
    "electronics":"电子元件","superconductors":"超导体","claytronics":"克雷特罗尼克",
    "antimatter":"反物质","smartchips":"智能芯片","ore":"矿石","silicon":"硅",
    "advanced":"先进","cluster":"集束","some":"一些","item":"物品","mod":"mod",
    "projectile":"投射物","gatling":"加特林","rotary":"旋转","autocannon":"自动加农",
    "artillery":"火炮","kinetic":"动能","impact":"冲击","concussion":"震荡",
    "disruptor":"干扰","arc":"电弧","burst":"连射","shell":"炮弹","warhead":"弹头",
    "nano":"纳米","computronic":"计算元件","teladianium":"泰拉迪尼姆","magnetic":"磁性",
    "shieldgenerator":"护盾发生器","enginepart":"引擎零件","hullpart":"船体零件",
    "solar":"太阳能","bio":"生物","medical":"医疗","food":"食物","drink":"饮品",
    "herbal":"草药","spices":"香料","fuel":"燃料","plasma":"等离子","recycled":"再生",
    "metallic":"金属","chemical":"化学","compound":"化合物","organ":"器官",
    "mystery":"神秘","scrap":"废料","processors":"处理器","wafers":"晶圆",
    "ore":"矿石","water":"水","ice":"冰","nvidium":"恩维迪姆","microchip":"微芯片",
    "iron":"铁","lead":"铅","copper":"铜","steel":"钢","titanium":"钛","tungsten":"钨",
    "uranium":"铀","plutonium":"钚","deuterium":"氘","tritium":"氚","hydrogen":"氢",
    "helium":"氦","nickel":"镍","chromium":"铬","cobalt":"钴","zinc":"锌","tin":"锡",
    "silver":"银","gold":"金","platinum":"铂","aluminum":"铝","lithium":"锂",
    "fission":"裂变","fusion":"聚变","nuclear":"核","thermal":"热","cryo":"低温",
    "capacitor":"电容","emitter":"发射器","projector":"投射器","coil":"线圈",
    "barrel":"炮管","caliber":"口径","round":"弹药","slug":"弹丸","pellet":"霰弹",
    "shard":"碎片","debris":"残骸","particle":"粒子","quantum":"量子","tachyon":"快子",
    "neutron":"中子","proton":"质子","meson":"介子","photon":"光子","graviton":"引力子",
    "charge":"电荷","field":"场","alloy":"合金","composite":"复合","ceramic":"陶瓷",
    "carbon":"碳","nanite":"纳米机器人","micro":"微型","orbital":"轨道","module":"模块",
    "launcher":"发射器","ammo":"弹药","fuel":"燃料","booster":"助推器","array":"阵列",
    "magazine":"弹匣","chamber":"弹膛","compressed":"压缩","stabilized":"稳定",
    "refined":"精炼","raw":"原","salvage":"打捞","wreck":"残骸","container":"容器",
    "bay":"舱","drive":"驱动器","core":"核心","prime":"主","elite":"精英","max":"最大",
    "min":"最小","base":"基础","basic":"基础","ultra":"超","extreme":"极限",
}
_ID_SKIP = {"ship","turret","weapon","shield","engine","missile","bullet",
             "software","macro","component"}
def _zh_id(sid):
    """把无名称物品的 id 拆词按游戏语境翻译（类型前缀跳过、词根表内词替换、
    mk 大写、未知保留），返回中文大意（不代 [译] 标注，调用方自行加）。"""
    parts = [p for p in re.split(r"[\s_]+", sid or "") if p]
    out = []
    for p in parts:
        if p in _ID_SKIP:
            continue
        if p in _ID_ZH:
            out.append(_ID_ZH[p])
        elif re.fullmatch(r"mk\d+", p.lower()):
            out.append(p.upper())
        else:
            out.append(p)
    return "".join(out)

# 新舰船 ID 校验（对齐 X4 官方 XSD idname：字母/下划线开头，仅小写字母数字下划线）
def parse_id(sid):
    """不强制 ship_种族_尺寸 结构：游戏侧 race 由 storage makerrace / faction 承载，
    size 由 component class 承载，ware 无 group（原版大船即如此）；原版与各 mod 中
    大量非标准 id（units_arg_size_l_dest_a、argonmattgriffon 等）均正常加载。
    合法返回规范化 id，非法返回 None。"""
    return sid if re.match(r"^[a-z_][a-z0-9_]*$", sid) else None

def _race_code_of(cid):
    """从舰船 id 提取 race 段（与 parse_id 同一切分规则，含数字/下划线 race 均正确）；
    非 ship_ 结构时回退旧的 split 取段（保底不抛错）。"""
    m = re.match(r"^ship_([a-z0-9_]+?)_(l|xl)_", cid)
    if m:
        return m.group(1)
    parts = cid.split("_")
    return parts[1] if len(parts) > 1 else "arg"

def _rng(vals):
    """返回 [min, max, 中位]（保留 1 位小数）；空则 None。"""
    if not vals:
        return None
    v = sorted(vals)
    return [round(v[0],1), round(v[-1],1), round(statistics.median(v),1)]

def vanilla_stats():
    """扫描原版 X4 L/XL 舰船 macro，统计各属性数值范围（供界面显示参考）。
    单值字段返回 [min,max,中位]；多值字段（inertia/drag/storage）返回 {子字段:[min,max,中位],...}。"""
    st = {"l": {}, "xl": {}}
    for size in ("l", "xl"):
        d = os.path.join(VANILLA_DIR, "size_%s" % size, "macros")
        if not os.path.isdir(d):
            continue
        c = {"hull": [], "explosion_value": [], "explosion_shield": [], "people": [], "mass": [],
             "inertia": {"pitch":[], "yaw":[], "roll":[]},
             "drag": {"forward":[], "reverse":[], "horizontal":[], "vertical":[],
                      "pitch":[], "yaw":[], "roll":[]},
             "storage": {"missile":[], "unit":[], "deployable":[], "countermeasure":[]},
             "cargo": []}
        for fn in os.listdir(d):
            if not (fn.startswith("ship_") and fn.endswith("_macro.xml")):
                continue
            p = os.path.join(d, fn)
            txt = open(p, encoding="utf-8").read()
            m = re.search(r'<hull max="([\d.]+)"', txt)
            if m: c["hull"].append(float(m.group(1)))
            m = re.search(r'<explosiondamage value="([\d.]+)" shield="([\d.]+)"', txt)
            if m:
                c["explosion_value"].append(float(m.group(1)))
                c["explosion_shield"].append(float(m.group(2)))
            m = re.search(r'<people capacity="([\d.]+)"', txt)
            if m: c["people"].append(float(m.group(1)))
            m = re.search(r'<physics mass="([\d.]+)"', txt)
            if m: c["mass"].append(float(m.group(1)))
            m = re.search(r'<inertia pitch="([\d.]+)" yaw="([\d.]+)" roll="([\d.]+)"', txt)
            if m:
                c["inertia"]["pitch"].append(float(m.group(1)))
                c["inertia"]["yaw"].append(float(m.group(2)))
                c["inertia"]["roll"].append(float(m.group(3)))
            m = re.search(r'<drag forward="([\d.]+)" reverse="([\d.]+)" horizontal="([\d.]+)" vertical="([\d.]+)" pitch="([\d.]+)" yaw="([\d.]+)" roll="([\d.]+)"', txt)
            if m:
                for i, k in enumerate(("forward","reverse","horizontal","vertical","pitch","yaw","roll")):
                    c["drag"][k].append(float(m.group(i+1)))
            m = re.search(r'<storage missile="([\d.]+)" unit="([\d.]+)"(?: deployable="([\d.]+)")?(?: countermeasure="([\d.]+)")?', txt)
            if m:
                c["storage"]["missile"].append(float(m.group(1)))
                c["storage"]["unit"].append(float(m.group(2)))
                if m.group(3): c["storage"]["deployable"].append(float(m.group(3)))
                if m.group(4): c["storage"]["countermeasure"].append(float(m.group(4)))
            m = re.search(r'<macro ref="(storage_[^"]+)"', txt)
            if m:
                sp = os.path.join(d, m.group(1) + ".xml")
                if os.path.isfile(sp):
                    m2 = re.search(r'<cargo max="([\d.]+)"', open(sp, encoding="utf-8").read())
                    if m2: c["cargo"].append(float(m2.group(1)))
        out = {}
        for k, v in c.items():
            if isinstance(v, dict):
                r = {kk: _rng(vv) for kk, vv in v.items() if vv}
                if r: out[k] = r
            else:
                r = _rng(v)
                if r: out[k] = r
        st[size] = out
    return st

def mod_dirs():
    """扫描 X4 extensions 下所有 mod 目录（含 content.xml），供界面路径选择。"""
    exts = os.path.join(ROOT, "extensions") if ROOT else ""
    out = []
    if exts and os.path.isdir(exts):
        for name in sorted(os.listdir(exts)):
            p = os.path.join(exts, name)
            if os.path.isdir(p) and os.path.isfile(os.path.join(p, "content.xml")):
                out.append({"name": name, "path": p})
    return out

def load_config():
    try:
        return json.load(open(CONFIG_FILE, encoding="utf-8"))
    except Exception:
        return {}

def save_config(cfg):
    try:
        open(CONFIG_FILE, "w", encoding="utf-8").write(json.dumps(cfg, ensure_ascii=False))
    except Exception:
        pass

def pick_dir_dialog():
    """弹出 Windows 原生「选择文件夹」对话框（独立 PowerShell 进程，不依赖 python 的 tcl/tk）。
    返回绝对路径；用户取消返回 None。"""
    import subprocess
    code = ("Add-Type -AssemblyName System.Windows.Forms\n"
            "$d = New-Object System.Windows.Forms.FolderBrowserDialog\n"
            "$d.Description = '选择目标 mod 目录'\n"
            "$d.ShowNewFolderButton = $true\n"
            "$r = $d.ShowDialog()\n"
            "if ($r -eq [System.Windows.Forms.DialogResult]::OK) { $d.SelectedPath } else { '' }")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", code],
                             capture_output=True, text=True, timeout=600)
        lines = [ln.strip() for ln in (out.stdout or "").splitlines() if ln.strip()]
        p = lines[-1] if lines else ""
        return p if p and os.path.isdir(p) else None
    except Exception:
        return None

def dirtree(path="", want_files=False):
    """枚举 path 的直接子目录（浏览器内置目录树选择用，替代依赖交互窗口站的系统文件夹对话框）。
    want_files=True 时同时返回直接子文件（供「外部 py 工具」这类文件路径选择）。
    返回 {base, parent, dirs, files}；path 无效时回退默认 mod 目录。"""
    if path and os.path.isdir(path):
        base = os.path.abspath(path)
    else:
        base = MOD_DIR
    parent = os.path.dirname(base)
    try:
        dirs = [d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d))]
        dirs.sort()
    except Exception:
        dirs = []
    files = []
    if want_files:
        try:
            files = sorted(f for f in os.listdir(base) if os.path.isfile(os.path.join(base, f)))
        except Exception:
            files = []
    return {"ok": True, "base": base, "parent": parent,
            "dirs": [{"name": d, "full": os.path.join(base, d)} for d in dirs],
            "files": [{"name": f, "full": os.path.join(base, f)} for f in files]}

def _disable_jcs(dirpath):
    """把复制的 data 目录下所有 .jcs 几何文件改名为 .jcs.disabled（幂等，跳过已改）。
    实测：复制得到的 .jcs 会让游戏在生成该舰船时崩溃；加 .disabled 后引擎跳过加载即正常。
    仅处理新生成的副本，模板本体不动。返回改名数量。"""
    if not os.path.isdir(dirpath):
        return 0
    n = 0
    for r, _dirs, files in os.walk(dirpath):
        for f in files:
            if f.endswith(".jcs"):
                os.rename(os.path.join(r, f), os.path.join(r, f + ".disabled"))
                n += 1
    return n

def copy_to_moding(mod, rel_paths):
    """把本次涉及的文件按相对路径复制到 <mod>\\moding\\ 下，方便用户直接覆盖使用。"""
    base = os.path.join(mod, "moding")
    out = []
    for rp in rel_paths:
        src = os.path.join(mod, rp)
        if os.path.isfile(src):
            dst = os.path.join(base, rp)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            out.append(rp)
    return out

# ── 模型同步：EGO Blender 导出目录 → 目标 mod ──
def _sm_units_dir(export_root):
    """定位导出目录里的 assets/units（兼容用户直接选到 size_l 或 mod 根）。"""
    root = os.path.normpath(export_root)
    cand = []
    if os.path.basename(root).lower().startswith("size_"):
        cand.append(os.path.dirname(root))
    cand += [os.path.join(root, "assets", "units"), root]
    for d in cand:
        try:
            if os.path.isdir(d) and any(x.lower().startswith("size_") and os.path.isdir(os.path.join(d, x))
                                        for x in os.listdir(d)):
                return d
        except OSError:
            pass
    return ""

def _sm_find(root, name):
    """在目录里按名字大小写不敏感地找子项（文件或目录），找不到返回空串。"""
    if not root or not os.path.isdir(root):
        return ""
    low = name.lower()
    try:
        for x in os.listdir(root):
            if x.lower() == low:
                return os.path.join(root, x)
    except OSError:
        pass
    return ""

def _sm_read(path):
    with open(path, "rb") as f:
        return f.read().decode("utf-8-sig")

def _sm_write(path, txt):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(txt.encode("utf-8"))

def _sm_dec(b):
    """subprocess 输出解码：优先 utf-8，回落中文 Windows 的 gbk/mbcs。"""
    for enc in ("utf-8", "gbk", "mbcs"):
        try:
            return b.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return b.decode("utf-8", "replace")

def _sm_backup(mod, ship_id, paths):
    """把本次要改的目标路径备份到 <mod>/_shipmodel_backup/<时间戳>_<舰船id>/（保留结构）。
    同一舰船只保留最近 3 次操作目录。返回 (备份目录, 备份条目数, [失败项…])。"""
    bdir = os.path.join(mod, "_shipmodel_backup")
    dest = os.path.join(bdir, time.strftime("%Y%m%d-%H%M%S") + "_" + ship_id)
    n = 0
    errs = []
    for src in paths:
        if not src or not os.path.exists(src):
            continue
        rel = os.path.relpath(src, mod)
        dst = os.path.join(dest, rel)
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if os.path.isdir(src):
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
            n += 1
        except (OSError, shutil.Error) as e:
            errs.append("%s: %s" % (rel, e))
    if n:
        try:
            olds = sorted(x for x in os.listdir(bdir)
                          if x.endswith("_" + ship_id) and os.path.isdir(os.path.join(bdir, x)))
            for x in olds[:-3]:
                shutil.rmtree(os.path.join(bdir, x), ignore_errors=True)
        except OSError:
            pass
    return (dest if n else ""), n, errs

def _sm_extract_macro_conns(txt):
    """从 py 处理后的组件 XML 里分离“属于 macro 的连接点”。
    判定依据是结构而非位置：组件里 name= 的是硬点；ref= 且内含 <macro ref=> 的是功能连接（归 macro）。
    返回 (去掉这些连接的组件文本, [连接块文本...])。"""
    lines = txt.splitlines(keepends=True)
    blocks, drop, comments = [], set(), []
    i = 0
    while i < len(lines):
        ln = lines[i]
        if re.match(r'^[ \t]*<connection\b', ln):
            j, block = i, [ln]
            if not ln.rstrip().endswith("/>"):
                while j + 1 < len(lines):
                    j += 1
                    block.append(lines[j])
                    if re.match(r'^[ \t]*</connection>\s*$', lines[j]):
                        break
            b = "".join(block)
            if re.search(r'<macro\b[^>]*\bref=', b):
                blocks.append(b)
                drop.update(range(i, j + 1))
            i = j + 1
            continue
        if re.match(r'^[ \t]*<!--\s*New connections for specific node types\s*-->\s*$', ln):
            comments.append(i)
        i += 1
    if blocks:
        drop.update(comments)
    comp = "".join(l for k, l in enumerate(lines) if k not in drop)
    return comp, blocks

def _sm_macro_conn_map(macro_txt):
    """旧舰船宏里 ref → connection 属性值（替换时同名 ref 沿用旧值，避免 py 默认值写坏真实连接名）。"""
    out = {}
    for m in re.finditer(r'<connection\b[^>]*\bref="([^"]+)"[^>]*>(.*?)</connection>', macro_txt, re.S):
        mm = re.search(r'<macro\b[^>]*\bconnection="([^"]*)"', m.group(2))
        if mm:
            out[m.group(1)] = mm.group(1)
    return out

def _sm_reindent(block, indent, unit="\t"):
    """把 py 输出的连接块按目标宏的缩进风格重排（相对层级按块内最小缩进步长折算成 tab/空格）。"""
    lines = [l for l in block.splitlines() if l.strip()]
    if not lines:
        return ""
    ind = [len(l) - len(l.lstrip(" \t")) for l in lines]
    cut = min(ind)
    rel = [x - cut for x in ind]
    nz = [r for r in rel if r > 0]
    step = min(nz) if nz else 1
    out = []
    for l, r in zip(lines, rel):
        lvl = (r // step) if step > 1 else r
        l = re.sub(r'[ \t]+/>$', '/>', l)
        out.append(indent + unit * lvl + l[cut + lvl * step:] + "\n")
    return "".join(out)

def _sm_replace_macro_conns(macro_txt, blocks, oldmap):
    """用 py 生成的连接块替换舰船宏的 <connections> 内容；同名 ref 保留旧 connection 值。
    宏里没有 <connections> 时在 </macro> 前插入；返回 None 表示结构无法处理。"""
    nl = "\r\n" if "\r\n" in macro_txt else "\n"
    fixed = []
    for b in blocks:
        m = re.search(r'<connection\b[^>]*\bref="([^"]+)"[^>]*>', b)
        ref = m.group(1) if m else ""
        if ref in oldmap:
            b = re.sub(r'(<macro\b[^>]*\bconnection=")[^"]*(")',
                       lambda x: x.group(1) + oldmap[ref] + x.group(2), b, count=1)
        fixed.append(b)
    m = re.search(r'([ \t]*)<connections\s*/>', macro_txt)
    if m:
        ind = m.group(1)
        unit = "\t" if "\t" in ind else "    "
        body = "".join(_sm_reindent(b, ind + unit, unit) for b in fixed)
        new = ind + "<connections>" + nl + body + ind + "</connections>"
        return macro_txt[:m.start()] + new + macro_txt[m.end():]
    m = re.search(r'([ \t]*)<connections\s*>', macro_txt)
    if m:
        ind = m.group(1)
        unit = "\t" if "\t" in ind else "    "
        end = macro_txt.find("</connections>", m.end())
        if end < 0:
            return None
        body = "".join(_sm_reindent(b, ind + unit, unit) for b in fixed)
        head = macro_txt[:m.end()].rstrip(" \t\r\n")
        return head + nl + body + ind + macro_txt[end:]
    m = re.search(r'([ \t]*)</macro>', macro_txt)
    if m:
        ind = m.group(1)
        unit = "\t" if "\t" in ind else "    "
        body = "".join(_sm_reindent(b, ind + unit + unit, unit) for b in fixed)
        new = ind + unit + "<connections>" + nl + body + ind + unit + "</connections>" + nl
        return macro_txt[:m.start()] + new + macro_txt[m.start():]
    return None

def ship_model_sync(d):
    """EGO Blender 导出目录 → 目标 mod 的船模同步。
    流程：备份（保留 3 次）→ 清空 py 根 xml 并复制 → 运行 py → 分离 macro 连接点 →
    写入组件 xml / 宏 → 替换模型目录与 ani/dae → 生成 moding 可覆盖结构。"""
    import subprocess, sys
    steps = []
    def st(name, ok, detail=""):
        steps.append({"name": name, "ok": bool(ok), "detail": detail or ""})
        return bool(ok)
    ship_id = (d.get("ship_id") or "").strip()
    export_root = (d.get("export_root") or "").strip()
    py_path = (d.get("py_path") or "").strip()
    mod = (d.get("mod") or "").strip()
    overlay = (d.get("overlay") or "").strip()
    out = {"ok": False, "ship_id": ship_id, "steps": steps, "log": "", "files": []}
    if not ship_id:
        st("参数检查", False, "缺少舰船 id"); return out
    if not re.fullmatch(r'[A-Za-z0-9_.\-]+', ship_id):
        st("参数检查", False, "舰船 id 含非法字符: " + ship_id); return out
    if not mod or not os.path.isdir(mod):
        st("参数检查", False, "修改路径不存在: " + (mod or "(空)")); return out
    if not export_root or not os.path.isdir(export_root):
        st("参数检查", False, "资源路径不存在: " + (export_root or "(空)")); return out
    if not py_path or not os.path.isfile(py_path):
        st("参数检查", False, "外部 py 工具不存在: " + (py_path or "(空)")); return out
    if not overlay:
        overlay = os.path.join(mod, "moding")

    units = _sm_units_dir(export_root)
    if not units:
        st("定位导出目录", False, "资源路径下没有 assets/units: " + export_root); return out
    size = size_dir = src_ship = ""
    for sz in sorted(os.listdir(units)):
        if not (sz.lower().startswith("size_") and os.path.isdir(os.path.join(units, sz))):
            continue
        p = _sm_find(os.path.join(units, sz), ship_id + ".xml")
        if p:
            size, size_dir, src_ship = sz[5:].lower(), os.path.join(units, sz), p
            break
    if not src_ship:
        st("定位导出文件", False, "资源路径里没有 %s.xml（检查 assets/units/size_*）" % ship_id); return out
    st("定位导出文件", True, src_ship)

    tgt_size_dir = _sm_find(os.path.join(mod, "assets", "units"), "size_" + size)
    tgt_macro = _sm_find(os.path.join(tgt_size_dir, "macros") if tgt_size_dir else "", ship_id + "_macro.xml")
    if not tgt_macro:
        st("检查目标舰船", False, "目标 mod 没有 %s_macro.xml，请先在「舰船模块」新增该 id 舰船后再执行" % ship_id)
        return out
    target_ship_path = _sm_find(tgt_size_dir, os.path.basename(src_ship)) or \
        os.path.join(tgt_size_dir, os.path.basename(src_ship))
    st("检查目标舰船", True, tgt_macro)

    src_data = _sm_find(size_dir, ship_id + "_data")
    if not src_data:
        st("定位模型目录", False, "资源路径里没有 %s_data 文件夹" % ship_id); return out
    data_name = os.path.basename(src_data)
    tgt_data = _sm_find(tgt_size_dir, data_name) or os.path.join(tgt_size_dir, data_name)
    src_ani = _sm_find(size_dir, ship_id + "_data.ani")
    src_dae = _sm_find(size_dir, ship_id + "_data.dae")

    rel_size = os.path.join("assets", "units", "size_" + size)
    rel_ship = os.path.join(rel_size, os.path.basename(src_ship))
    rel_macro = os.path.join(rel_size, "macros", os.path.basename(tgt_macro))
    rel_data = os.path.join(rel_size, data_name)
    rel_ani = os.path.join(rel_size, os.path.basename(src_ani)) if src_ani else ""
    rel_dae = os.path.join(rel_size, os.path.basename(src_dae)) if src_dae else ""

    bk_paths = [os.path.join(mod, rel_ship), tgt_macro, tgt_data]
    if rel_ani:
        bk_paths.append(os.path.join(mod, rel_ani))
    if rel_dae:
        bk_paths.append(os.path.join(mod, rel_dae))
    bdir, bn, berrs = _sm_backup(mod, ship_id, bk_paths)
    if berrs:
        st("备份目标文件", False, "备份失败即中止（不写目标）: " + "；".join(berrs[:3])); return out
    st("备份目标文件", True, ("%d 项 → %s" % (bn, os.path.relpath(bdir, mod))) if bdir else "目标暂无同名文件（首次导入）")

    py_root = os.path.dirname(os.path.abspath(py_path))
    removed = []
    try:
        for f in list(os.listdir(py_root)):
            fp = os.path.join(py_root, f)
            if os.path.isfile(fp) and f.lower().endswith(".xml"):
                try:
                    os.remove(fp)
                except OSError:
                    os.chmod(fp, 0o666)  # 只读/权限兜底：先放权再删
                    os.remove(fp)
                removed.append(f)
        work = os.path.join(py_root, os.path.basename(src_ship))
        shutil.copy2(src_ship, work)
        st("准备 py 工作目录", True, "清空 %d 个 xml，复制 %s" % (len(removed), os.path.basename(work)))
    except OSError as e:
        st("准备 py 工作目录", False, str(e)); return out

    try:
        r = subprocess.run([sys.executable, os.path.abspath(py_path), "--dir", py_root],
                           cwd=py_root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=900)
        log = _sm_dec(r.stdout or b"")
        out["log"] = log
        if r.returncode != 0:
            st("运行 py 工具", False, "退出码 %s：%s" % (r.returncode, log[-800:])); return out
        if not os.path.isfile(work):
            st("运行 py 工具", False, "py 运行后没有输出 xml"); return out
        st("运行 py 工具", True, "退出码 0")
    except Exception as e:
        st("运行 py 工具", False, str(e)); return out

    try:
        comp_txt, blocks = _sm_extract_macro_conns(_sm_read(work))
    except Exception as e:
        st("分离 macro 连接点", False, str(e)); return out
    if not blocks:
        st("分离 macro 连接点", False, "py 输出里没有 ref+macro 形式的连接点（检查连接点命名）"); return out
    err = _xml_check(comp_txt)
    if err:
        st("分离 macro 连接点", False, "组件 xml 校验失败: " + err); return out
    mtxt = _sm_read(tgt_macro)
    new_mtxt = _sm_replace_macro_conns(mtxt, blocks, _sm_macro_conn_map(mtxt))
    if new_mtxt is None:
        st("分离 macro 连接点", False, "目标宏里没有 <connections> 容器"); return out
    err = _xml_check(new_mtxt)
    if err:
        st("分离 macro 连接点", False, "宏 xml 校验失败: " + err); return out
    st("分离 macro 连接点", True, "%d 条连接点归入舰船宏（同名 ref 沿用旧 connection 值）" % len(blocks))

    _sm_write(target_ship_path, comp_txt)
    st("写入舰船 xml", True, rel_ship)
    _sm_write(tgt_macro, new_mtxt)
    st("写入舰船宏", True, rel_macro)

    if os.path.normcase(os.path.abspath(src_data)) == os.path.normcase(os.path.abspath(tgt_data)):
        st("替换模型目录", True, "源与目标为同一目录，跳过")
    else:
        try:
            if os.path.isdir(tgt_data):
                shutil.rmtree(tgt_data)
            elif os.path.exists(tgt_data):
                os.remove(tgt_data)
            shutil.copytree(src_data, tgt_data)
            st("替换模型目录", True, rel_data)
        except (OSError, shutil.Error) as e:
            st("替换模型目录", False, str(e)); return out

    copied = [target_ship_path, tgt_macro]
    for src, rel, label in ((src_ani, rel_ani, ".ani"), (src_dae, rel_dae, ".dae")):
        if not src or not rel:
            st("复制 %s" % label, True, "导出目录没有该文件，跳过")
            continue
        dst = os.path.join(mod, rel)
        try:
            if os.path.normcase(os.path.abspath(src)) != os.path.normcase(os.path.abspath(dst)):
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
            copied.append(dst)
            st("复制 %s" % label, True, rel)
        except OSError as e:
            st("复制 %s" % label, False, str(e)); return out

    try:
        if os.path.normcase(os.path.abspath(overlay)) == os.path.normcase(os.path.abspath(mod)):
            st("生成 moding 覆盖结构", True, "导出路径等于目标 mod，跳过")
        else:
            stale = os.path.join(overlay, rel_data)
            if os.path.isdir(stale):
                shutil.rmtree(stale)
            for src in copied + [tgt_data]:
                rel = os.path.relpath(src, mod)
                dst = os.path.join(overlay, rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                if os.path.isdir(src):
                    shutil.copytree(src, dst)
                else:
                    shutil.copy2(src, dst)
            st("生成 moding 覆盖结构", True, overlay)
    except (OSError, shutil.Error) as e:
        st("生成 moding 覆盖结构", False, str(e)); return out

    out["ok"] = all(s["ok"] for s in steps)
    out["files"] = [os.path.join(overlay, os.path.relpath(x, mod)) for x in copied + [tgt_data]]
    _refresh_soft()   # 组件/宏被整体替换：t文本/全局资产/组件内容缓存失效，列表立即可见
    return out

# ── 组件装配（炮塔/护盾/引擎等）：ego xml 为模板 + 补丁 + data 复制 + macro 改名 + index 注册 ──
def component_assemble(d):
    """与 ship_model_sync 的区别：不跑外部 py（组件无硬点/镜像需求），
    xml 补丁仅 geometry 前缀 + container；macro 从原版/扩展复制并改 name/component。"""
    import xml.etree.ElementTree as ET
    steps = []
    def st(name, ok, detail=""):
        steps.append({"name": name, "ok": bool(ok), "detail": detail or ""})
        return bool(ok)
    comp_id = (d.get("component_id") or "").strip()
    export_root = (d.get("export_root") or "").strip()
    mod = (d.get("mod") or "").strip()
    out = {"ok": False, "component_id": comp_id, "steps": steps, "files": [], "warnings": []}
    if not comp_id:
        st("参数检查", False, "缺少组件 id"); return out
    if not re.fullmatch(r'[A-Za-z0-9_.\-]+', comp_id):
        st("参数检查", False, "组件 id 含非法字符: " + comp_id); return out
    if not mod or not os.path.isdir(mod):
        st("参数检查", False, "mod 路径不存在: " + (mod or "(空)")); return out
    if not export_root or not os.path.isdir(export_root):
        st("参数检查", False, "资源路径不存在: " + (export_root or "(空)")); return out

    assets = os.path.join(export_root, "assets")
    if not os.path.isdir(assets):
        assets = export_root
    src_xml = ""
    for dirpath, _, files in os.walk(assets):
        if (os.sep + "units" + os.sep) in (dirpath.lower() + os.sep):
            continue
        for f in files:
            if f.lower() == (comp_id + ".xml").lower():
                src_xml = os.path.join(dirpath, f); break
        if src_xml:
            break
    if not src_xml:
        st("定位导出文件", False, "资源路径里没有 %s.xml" % comp_id); return out
    rel_dir = os.path.relpath(os.path.dirname(src_xml), assets)
    st("定位导出文件", True, os.path.join("assets", rel_dir, comp_id + ".xml"))
    src_data = os.path.join(os.path.dirname(src_xml), comp_id + "_data")
    if not os.path.isdir(src_data):
        st("定位模型目录", False, "缺少 %s_data 目录" % comp_id); return out
    st("定位模型目录", True, src_data)

    dst_dir = os.path.join(mod, "assets", rel_dir)
    os.makedirs(dst_dir, exist_ok=True)
    os.makedirs(os.path.join(dst_dir, "macros"), exist_ok=True)

    # xml 补丁：geometry 直接改写为显式 mod 路径（数据必然复制进 mod，见下方复制步骤）。
    # 不用 assets\ 裸路径——实测该写法只在数据属于原版时可解析，mod 自有数据会被拒载 meshsource。
    # 与可用舰船（ship_par_xl_avatar_s 等）的 geometry 约定一致。
    mod_folder = os.path.basename(os.path.normpath(mod))
    geo_explicit = "extensions\\%s\\assets\\%s\\%s_data" % (mod_folder, rel_dir.replace("/", "\\"), comp_id)
    text = open(src_xml, encoding="utf-8").read()
    text = re.sub(r'geometry="[^"]*"', 'geometry="%s"' % geo_explicit, text)
    n_container = len(re.findall(r'<connection name="container" tags=""\s*/>', text))
    text = re.sub(r'<connection name="container" tags=""\s*/>',
                  '<connection name="container" tags="contents" value="0"/>', text)
    try:
        ET.fromstring(text)
    except Exception as e:
        st("组件 XML 校验", False, str(e)); return out
    dst_xml = os.path.join(dst_dir, comp_id + ".xml")
    with open(dst_xml, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    out["files"].append(dst_xml)
    st("组件 XML 补丁", True, "geometry 前缀已剥" + ("；container 已补" if n_container else ""))

    dst_data = os.path.join(dst_dir, comp_id + "_data")
    if os.path.isdir(dst_data):
        shutil.rmtree(dst_data)
    shutil.copytree(src_data, dst_data)
    # 注意：组件流不禁用 .jcs——原版组件 data 同样带激活 .jcs，ego 新导出的缓存是有效的；
    # 禁用仅舰船流保留（那边实测复制得到的 .jcs 会致崩溃）。
    out["files"].append(dst_data)
    src_ani = os.path.join(os.path.dirname(src_xml), comp_id + "_data.ani")
    if os.path.isfile(src_ani):
        shutil.copy2(src_ani, os.path.join(dst_dir, comp_id + "_data.ani"))
        out["files"].append(os.path.join(dst_dir, comp_id + "_data.ani"))
    n_files = sum(len(fs) for _, _, fs in os.walk(dst_data))
    st("模型数据复制", True, "%d 个文件%s" % (n_files, "（含 .ani）" if os.path.isfile(src_ani) else ""))

    # macro：剥 _x数字 后缀找原版宏，复制改名；找不到则告警不阻断
    base = re.sub(r'_x\d+$', '', comp_id)
    dst_macro = os.path.join(dst_dir, "macros", comp_id + "_macro.xml")
    macro_done = False
    if base != comp_id:
        roots = [os.path.join(mod, "assets"), os.path.join(ROOT, "assets")]
        roots += sorted(glob.glob(os.path.join(ROOT, "extensions", "*", "assets")))
        macro_src = ""
        for rdir in roots:
            for dirpath, _, files in os.walk(rdir):
                for f in files:
                    if f.lower() == (base + "_macro.xml").lower():
                        macro_src = os.path.join(dirpath, f); break
                if macro_src:
                    break
            if macro_src:
                break
        if macro_src:
            mtext = open(macro_src, encoding="utf-8").read()
            mtext = mtext.replace('name="%s_macro"' % base, 'name="%s_macro"' % comp_id)
            # 原版写法带空格（<component ref="x" />），字符串精确替换会静默失效 → 用正则（引号边界防止误配前缀同名 id）
            mtext = re.sub(r'(<component\s+ref=")%s(")' % re.escape(base),
                           r'\g<1>%s\g<2>' % comp_id, mtext, count=1)
            try:
                ET.fromstring(mtext)
                if '<component ref="%s"' % comp_id not in mtext:
                    st("宏生成", False, "component ref 替换后仍非 %s（原版格式异常）" % comp_id); return out
                with open(dst_macro, "w", encoding="utf-8", newline="") as f:
                    f.write(mtext)
                out["files"].append(dst_macro)
                macro_done = True
                st("宏生成", True, "模板: " + macro_src)
            except Exception as e:
                st("宏生成", False, str(e)); return out
        else:
            out["warnings"].append("未找到原版宏 %s_macro.xml，已跳过宏生成（需手工建宏）" % base)
            st("宏生成", True, "跳过：未找到 %s_macro.xml" % base)
    else:
        out["warnings"].append("组件 id 无 _x数字 后缀，按原样处理，未自动生成宏")
        st("宏生成", True, "跳过（id 无缩放后缀）")

    # index 注册：components.xml + macros.xml
    mod_folder = os.path.basename(os.path.normpath(mod))
    for idx_name, nm, rel_tail in [
        ("components.xml", comp_id, rel_dir.replace("/", "\\") + "\\" + comp_id),
        ("macros.xml", comp_id + "_macro", rel_dir.replace("/", "\\") + "\\macros\\" + comp_id + "_macro"),
    ]:
        if idx_name == "macros.xml" and not macro_done and not os.path.isfile(dst_macro):
            continue
        idx_path = os.path.join(mod, "index", idx_name)
        if not os.path.isfile(idx_path):
            out["warnings"].append("缺少 " + idx_path); continue
        tree = ET.parse(idx_path)
        ent = tree.getroot()
        if nm not in {e.get("name") for e in ent}:
            e = ET.SubElement(ent, "entry")
            e.set("name", nm)
            e.set("value", "extensions\\%s\\assets\\%s" % (mod_folder, rel_tail))
            tree.write(idx_path, encoding="UTF-8", xml_declaration=True, short_empty_elements=True)
    st("index 注册", True, "components.xml + macros.xml")

    # 图标：复用源组件的升级贴图（否则装配界面/百科显示错图标或不显示模型）。
    # 查找顺序：mod icons.xml 已有 upgrade_<base>_macro 条目 → 原版 icons.xml 同名条目 →
    # 约定贴图 upgrades\<base>_macro.tga（.tga/.gz 存在即用，引擎两者都认）。
    if base:
        icons_path = os.path.join(mod, "libraries", "icons.xml")
        new_icon_name = "upgrade_%s_macro" % comp_id
        base_icon_name = "upgrade_%s_macro" % base
        tex = None
        if os.path.isfile(icons_path):
            for e in ET.parse(icons_path).getroot().iter("icon"):
                if e.get("name") == new_icon_name:
                    tex = "exists"; break
                if e.get("name") == base_icon_name and e.get("texture"):
                    tex = e.get("texture")
        if not tex:
            van_icons = os.path.join(ROOT, "libraries", "icons.xml")
            if os.path.isfile(van_icons):
                for e in ET.parse(van_icons).getroot().iter("icon"):
                    if e.get("name") == base_icon_name and e.get("texture"):
                        tex = e.get("texture"); break
        if not tex:
            guess = "assets\\textures\\ui\\upgrades\\%s_macro.tga" % base
            if os.path.isfile(os.path.join(ROOT, guess)) or os.path.isfile(os.path.join(ROOT, guess + ".gz")) \
               or os.path.isfile(os.path.join(ROOT, guess.replace(".tga", ".gz"))):
                tex = guess
        if tex and tex != "exists":
            if not os.path.isfile(icons_path):
                out["warnings"].append("缺少 " + icons_path + "，未注册图标")
            else:
                tree = ET.parse(icons_path)
                iroot = tree.getroot()
                if new_icon_name not in {e.get("name") for e in iroot.iter("icon")}:
                    ie = ET.SubElement(iroot, "icon")
                    ie.set("name", new_icon_name)
                    ie.set("texture", tex)
                    ie.set("height", "256"); ie.set("width", "256")
                    tree.write(icons_path, encoding="UTF-8", xml_declaration=True, short_empty_elements=True)
                    st("图标注册", True, tex)
                else:
                    st("图标注册", True, "已存在")
        elif tex == "exists":
            st("图标注册", True, "已存在")
        else:
            out["warnings"].append("未找到源组件图标贴图（%s），装配界面/百科将无图标" % base_icon_name)
            st("图标注册", False, "无可用贴图")

    # 校验：组件里每个 geometry 目录在 mod/原版/扩展之一真实存在
    geo_roots = [mod, ROOT] + sorted(glob.glob(os.path.join(ROOT, "extensions", "*")))
    missing = []
    for src in ET.parse(dst_xml).getroot().iter("source"):
        g = src.get("geometry") or ""
        if not g:
            continue
        gd = g.replace("\\\\", "\\").replace("/", "\\")
        if not any(os.path.isdir(os.path.join(r, gd)) for r in geo_roots):
            missing.append(g)
    if missing:
        out["warnings"].append("geometry 目录缺失: " + "; ".join(missing))
        st("geometry 校验", False, "%d 处缺失" % len(missing))
    else:
        st("geometry 校验", True, "全部目录存在")

    out["ok"] = all(s["ok"] for s in steps)
    _refresh_soft()
    return out

# ── Dock 复用：原版 dock 组件 + 新 id + Blender 导出 waypoint xml ──
_DOCK_CLASSES = ("dockarea", "dockingbay", "pier", "dock")
_WP_TAGS = {"typenormal", "typedock", "dockpath", "entrypath", "exitpath",
            "start", "end", "blocklink", "closelink", "force",
            "sizeLevel0", "sizeLevel1",
            "speed_slow", "speed_normal", "speed_fast", "speed_faster",
            "dynamicmasstraffic"}

def _dock_scan_dirs():
    """原版 + 全部扩展里 dock 组件的两个常驻目录（structures/dock 与 props/SurfaceElements）。"""
    out = []
    bases = [(os.path.join(ROOT, "assets"), "原版")]
    for m in _ext_order():
        bases.append((os.path.join(ROOT, "extensions", m, "assets"), m))
    for base, src in bases:
        for sub in (os.path.join("structures", "dock"), os.path.join("props", "SurfaceElements")):
            d = os.path.join(base, sub)
            if os.path.isdir(d):
                out.append((base, d, src))
    return out

def dock_list():
    """dock 复用模板列表：全部原版/DLC/mod 的 dock 类组件，标注 waypoint 数与 macro 是否存在。"""
    items = []
    for base, d, src in _dock_scan_dirs():
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".xml") or fn.endswith("_macro.xml"):
                continue
            p = os.path.join(d, fn)
            try:
                t = _sm_read(p)
            except OSError:
                continue
            mc = re.search(r'<component\s+name="([^"]+)"\s+class="([^"]+)"', t)
            if not mc or mc.group(2) not in _DOCK_CLASSES:
                continue
            name = mc.group(1)
            wps = len(re.findall(r'<waypoint\b', t))
            mac = os.path.join(d, "macros", name + "_macro.xml")
            items.append({"name": name, "cls": mc.group(2), "waypoints": wps,
                          "macro": os.path.isfile(mac), "src": src, "path": p})
    items.sort(key=lambda x: (x["cls"], x["name"]))
    return {"ok": True, "items": items}

def _wp_parse(txt):
    """解析 Blender 导出的 dock 硬点 xml。返回 (wps, dockingbays, errs, warns)。
    wps = [{name,tags,v,links,group}]；dockingbays = [{name,group}]。
    导出的 XML 与游戏 dock 组件同构：<waypoints> 段 + <connections> 段两个并列根节点。
    waypoint 的 name 含 group 前缀（如 mt_dock_01-waypoint_01），group 属性单独给出；
    dockingbay 从 <connections> 段的 <connection name="..." group="..."/> 解析。
    命名/分组规则在 Blender 端保证；本函数仅保留必要校验（tags 词汇、links 存在、坐标数值）。"""
    wps, dockingbays, errs, warns = [], [], [], []
    if not re.search(r'<waypoints\b', txt):
        return wps, dockingbays, ["文件里没有 <waypoints> 根节点"], warns
    names = set()
    for m in re.finditer(r'<waypoint\b([^>]*?)(?:/>|>(.*?)</waypoint>)', txt, re.S):
        attrs, inner = m.group(1), m.group(2) or ""
        def attr(k):
            mm = re.search(r'\b%s="([^"]*)"' % k, attrs)
            return mm.group(1).strip() if mm else ""
        name = attr("name")
        if not name:
            errs.append("存在无名 waypoint"); continue
        if name in names:
            errs.append("waypoint 重名: " + name)
        names.add(name)
        group = attr("group")
        tags = attr("tags").split()
        bad = [t for t in tags if t not in _WP_TAGS]
        if bad:
            errs.append("%s: 非法 tags: %s" % (name, " ".join(bad)))
        if not tags:
            errs.append("%s: tags 为空" % name)
        vals = {}
        for k in ("x", "y", "z", "qx", "qy", "qz", "qw"):
            v = attr(k)
            try:
                vals[k] = float(v) if v else 0.0
            except ValueError:
                errs.append("%s: %s 不是数字: %r" % (name, k, v)); vals[k] = 0.0
        links = re.findall(r'<link\s+ref="([^"]*)"\s*/>', inner)
        wps.append({"name": name, "tags": tags, "v": vals, "links": links, "group": group})
    for w in wps:
        for lk in w["links"]:
            if lk not in names:
                errs.append("%s: link 目标不存在: %s" % (w["name"], lk))
    # dockingbay 条目：从 <connections> 段解析 <connection name="..." group="..."/>
    # Blender 导出的 <connections> 段只含 dockingbay 连接（与游戏 dock 组件同构）
    conn_match = re.search(r'<connections>(.*?)</connections>', txt, re.S)
    if conn_match:
        for m in re.finditer(r'<connection\b([^>]*?)/>', conn_match.group(1)):
            attrs = m.group(1)
            def attr2(k):
                mm = re.search(r'\b%s="([^"]*)"' % k, attrs)
                return mm.group(1).strip() if mm else ""
            nm = attr2("name")
            if nm:
                dockingbays.append({"name": nm, "group": attr2("group")})
    if not errs:
        if not any("typedock" in w["tags"] for w in wps):
            warns.append("没有任何 typedock 点（typedock 式泊位必需；纯 dockpath 的甲板跑道式 dock 无此标记属正常）")
        bs = sum(1 for w in wps if "blocklink" in w["tags"] and "start" in w["tags"])
        be = sum(1 for w in wps if "blocklink" in w["tags"] and "end" in w["tags"])
        if bs != be:
            warns.append("blocklink start(%d)/end(%d) 不成对" % (bs, be))
        if not any("sizeLevel1" in w["tags"] for w in wps):
            warns.append("没有 sizeLevel1 标记（typedock 式停靠路径需要；甲板跑道式 dock 可忽略）")
        # 路径断链提示（typenormal 无出边且非终点）；分组规则归 Blender 端，此处不校验 dockpath 缺 group
        for w in wps:
            t = w["tags"]
            if "typenormal" in t and not w["links"] and "end" not in t and "dynamicmasstraffic" not in t:
                warns.append("%s: typenormal 无出边 link 且非终点（无 end/dynamicmasstraffic），可能是断链" % w["name"])
    return wps, dockingbays, errs, warns

def _wp_render(wps, base_indent):
    """按 vanilla 风格渲染 <waypoints> 段；base_indent = 原文 <waypoints> 行的前导空白。"""
    i1, i2, i3 = base_indent + "\t", base_indent + "\t\t", base_indent + "\t\t\t"
    lines = [base_indent + "<waypoints>"]
    for w in wps:
        v = w["v"]
        a = ('%s<waypoint name="%s" tags="%s "%s x="%s" y="%s" z="%s" qx="%s" qy="%s" qz="%s" qw="%s"'
             % (i1, w["name"], " ".join(w["tags"]),
                ' group="%s"' % w["group"] if w.get("group") else "",
                _wp_num(v["x"]), _wp_num(v["y"]), _wp_num(v["z"]),
                _wp_num(v["qx"]), _wp_num(v["qy"]), _wp_num(v["qz"]), _wp_num(v["qw"])))
        if w["links"]:
            lines.append(a + ">")
            lines.append(i2 + "<links>")
            for lk in w["links"]:
                lines.append('%s<link ref="%s"/>' % (i3, lk))
            lines.append(i2 + "</links>")
            lines.append(i1 + "</waypoint>")
        else:
            lines.append(a + "/>")
    lines.append(base_indent + "</waypoints>")
    return "\n".join(lines)

def _wp_num(v):
    s = "%.7g" % v
    return "0" if s == "-0" else s

def _wp_replace(comp_txt, wps):
    """把组件文本里 <layer> 下的 <waypoints> 段（含自闭合）替换为 wps。
    注意 <connection> 里也可能有 <waypoints/>，必须锁定 layer 作用域，不能全局匹配。"""
    lm = re.search(r'^[ \t]*<layer>', comp_txt, re.M)
    if not lm:
        return None
    lend = comp_txt.find("</layer>", lm.end())
    scope_end = lend if lend > 0 else len(comp_txt)
    seg = comp_txt[lm.end():scope_end]
    m = re.search(r'^[ \t]*<waypoints\s*/>', seg, re.M) or \
        re.search(r'^[ \t]*<waypoints>.*?</waypoints>', seg, re.S | re.M)
    if m:
        indent = re.match(r'[ \t]*', m.group(0)).group(0)
        s, e = lm.end() + m.start(), lm.end() + m.end()
        return comp_txt[:s] + _wp_render(wps, indent) + comp_txt[e:]
    indent = re.match(r'[ \t]*', lm.group(0)).group(0) + "\t"
    return comp_txt[:lm.end()] + "\n" + _wp_render(wps, indent) + comp_txt[lm.end():]

def _db_set_group(comp_txt, name, group):
    """定位 <connection name="name"> 的开头标签，更新其 group 属性。
    group 为空则删除 group 属性；否则新增/覆盖。只动 group，不动 name/数量/其它属性。"""
    pattern = re.compile(r'(<connection\b[^>]*\bname="%s"[^>]*?)(>)' % re.escape(name), re.S)
    def repl(m):
        tag = re.sub(r'\s+group="[^"]*"', '', m.group(1))
        if group:
            tag += ' group="%s"' % group
        return tag + m.group(2)
    return pattern.sub(repl, comp_txt, count=1)

def dock_clone(d):
    """原版 dock 组件复制改名 + 可选替换 waypoint（Blender 导出 xml）+ macro 复制 + index 注册 + moding 结构。
    几何（_data）指向原版不动；写目标前备份（沿用 _shipmodel_backup 最近 3 次），备份失败即中止。"""
    steps = []
    def st(name, ok, detail=""):
        steps.append({"name": name, "ok": bool(ok), "detail": detail or ""})
        return bool(ok)
    tpl = (d.get("tpl") or "").strip()
    new_id = (d.get("new_id") or "").strip()
    wp_xml = (d.get("wp_xml") or "").strip()
    mod = (d.get("mod") or "").strip()
    overlay = (d.get("overlay") or "").strip()
    out = {"ok": False, "new_id": new_id, "steps": steps, "warnings": [], "files": []}
    if not new_id or not re.fullmatch(r'[A-Za-z0-9_.\-]+', new_id):
        st("参数检查", False, "新 id 为空或含非法字符"); return out
    if not mod or not os.path.isdir(mod):
        st("参数检查", False, "修改路径不存在: " + (mod or "(空)")); return out
    if not tpl or not os.path.isfile(tpl):
        st("参数检查", False, "模板组件不存在: " + (tpl or "(空)")); return out
    if not overlay:
        overlay = os.path.join(mod, "moding")

    try:
        ctxt = _sm_read(tpl)
    except OSError as e:
        st("读取模板", False, str(e)); return out
    mc = re.search(r'<component\s+name="([^"]+)"\s+class="([^"]+)"', ctxt)
    if not mc or mc.group(2) not in _DOCK_CLASSES:
        st("读取模板", False, "不是 dock 类组件（class 须为 %s）" % "/".join(_DOCK_CLASSES)); return out
    tpl_name = mc.group(1)
    st("读取模板", True, "%s（class=%s）" % (tpl_name, mc.group(2)))

    # 模板相对 assets 的位置（决定写入 mod 的目录结构）
    tpl_dir = os.path.dirname(tpl)
    rel_dir = None
    for base, _d, _s in _dock_scan_dirs():
        if os.path.normcase(os.path.abspath(tpl_dir)) == os.path.normcase(os.path.abspath(_d)):
            rel_dir = os.path.relpath(tpl_dir, base)
            break
    if rel_dir is None:
        st("定位模板", False, "模板不在已知 dock 目录（structures/dock 或 props/SurfaceElements）"); return out
    tpl_macro = os.path.join(tpl_dir, "macros", tpl_name + "_macro.xml")
    if not os.path.isfile(tpl_macro):
        st("定位模板宏", False, "缺少 " + tpl_name + "_macro.xml"); return out
    try:
        mtxt = _sm_read(tpl_macro)
    except OSError as e:
        st("定位模板宏", False, str(e)); return out
    st("定位模板宏", True, os.path.basename(tpl_macro))

    # waypoint：给了 xml 就解析校验并替换；没给则保留模板原样
    if wp_xml:
        if not os.path.isfile(wp_xml):
            st("读取 waypoint xml", False, "文件不存在: " + wp_xml); return out
        try:
            wtxt = _sm_read(wp_xml)
        except OSError as e:
            st("读取 waypoint xml", False, str(e)); return out
        wps, dockingbays, errs, warns = _wp_parse(wtxt)
        out["warnings"] = warns
        if errs:
            st("校验 waypoint xml", False, "；".join(errs[:5])); return out
        if not wps:
            st("校验 waypoint xml", False, "没有解析到任何 waypoint"); return out
        st("校验 waypoint xml", True, "%d waypoint + %d dockingbay 校验通过%s"
           % (len(wps), len(dockingbays), "（%d 条警告）" % len(warns) if warns else ""))
        # waypoint 组集 与 dockingbay 组集 必须相互对应（游戏靠它绑定路径↔泊位）。
        # 任一侧缺组都视为不对应，给出警告但不阻断输出。
        wp_groups = {w["group"] for w in wps if w["group"]}
        db_groups = {db["group"] for db in dockingbays if db["group"]}
        if (wp_groups or db_groups) and wp_groups != db_groups:
            out["warnings"].append(
                "waypoint 组（%s）与 dockingbay 组（%s）不一一对应，路径与泊位可能绑定错误（警告，不影响输出）"
                % ("、".join(sorted(wp_groups)[:5]) if wp_groups else "（空）",
                   "、".join(sorted(db_groups)[:5]) if db_groups else "（空）"))
        new_ctxt = _wp_replace(ctxt, wps)
        if new_ctxt is None:
            st("替换 waypoints", False, "模板里没有 <waypoints> 也没有 <layer> 可插入"); return out
        st("替换 waypoints", True, "模板原 %d 个 → 新 %d 个" % (len(re.findall(r'<waypoint\b', ctxt)), len(wps)))
        ctxt = new_ctxt
        # dockingbay：按名定位 connection，只更新 group（含删除），不动 name/数量
        updated_db = 0
        for db in dockingbays:
            before = ctxt
            ctxt = _db_set_group(ctxt, db["name"], db["group"])
            if ctxt != before:
                updated_db += 1
            else:
                out["warnings"].append("dockingbay %s 在模板 connection 中未找到，已跳过" % db["name"])
        if dockingbays:
            st("更新泊位 group", True, "%d/%d 个 dockingbay 的 group 已更新" % (updated_db, len(dockingbays)))
    else:
        st("替换 waypoints", True, "未提供 waypoint xml，保留模板原路径")

    # 改名：组件 name + 宏 name/component ref
    new_ctxt = re.sub(r'(<component\s+name=")%s(")' % re.escape(tpl_name),
                      r'\g<1>%s\g<2>' % new_id, ctxt, count=1)
    new_mtxt = re.sub(r'(<macro\s+name=")%s_macro(")' % re.escape(tpl_name),
                      r'\g<1>%s_macro\g<2>' % new_id, mtxt, count=1)
    new_mtxt = re.sub(r'(<component\s+ref=")%s(")' % re.escape(tpl_name),
                      r'\g<1>%s\g<2>' % new_id, new_mtxt, count=1)
    for txt, label in ((new_ctxt, "组件"), (new_mtxt, "宏")):
        err = _xml_check(txt)
        if err:
            st("校验%s xml" % label, False, err); return out
    st("改名并校验 xml", True, "%s / %s_macro" % (new_id, new_id))

    rel_comp = os.path.join("assets", rel_dir, new_id + ".xml")
    rel_macro = os.path.join("assets", rel_dir, "macros", new_id + "_macro.xml")
    tgt_comp = os.path.join(mod, rel_comp)
    tgt_macro = os.path.join(mod, rel_macro)

    bdir, _bn, berrs = _sm_backup(mod, new_id, [tgt_comp, tgt_macro])
    if berrs:
        st("备份目标文件", False, "备份失败即中止（不写目标）: " + "；".join(berrs[:3])); return out
    st("备份目标文件", True, bdir if os.path.isdir(bdir) else "目标暂无同名文件（首次导入）")

    _sm_write(tgt_comp, new_ctxt)
    _sm_write(tgt_macro, new_mtxt)
    st("写入组件与宏", True, "%s；%s" % (rel_comp, rel_macro))

    modi = _register_index(mod, [
        ("components", new_id, "assets\\%s\\%s" % (rel_dir.replace("/", "\\"), new_id)),
        ("macros", new_id + "_macro", "assets\\%s\\macros\\%s_macro" % (rel_dir.replace("/", "\\"), new_id)),
    ])
    if modi:
        st("注册 index", True, "；".join(modi))
    else:
        st("注册 index", False, "mod 下没有 index/components.xml 或 macros.xml"); return out

    try:
        if os.path.normcase(os.path.abspath(overlay)) == os.path.normcase(os.path.abspath(mod)):
            st("生成 moding 覆盖结构", True, "导出路径等于目标 mod，跳过")
        else:
            rels = [rel_comp, rel_macro] + [r for r in modi]
            copy_to_moding(mod, rels)
            # copy_to_moding 固定写 <mod>/moding；overlay 不同则再镜像一份
            if os.path.normcase(os.path.abspath(overlay)) != os.path.normcase(os.path.join(mod, "moding")):
                for rp in rels:
                    src = os.path.join(mod, rp)
                    if os.path.isfile(src):
                        dst = os.path.join(overlay, rp)
                        os.makedirs(os.path.dirname(dst), exist_ok=True)
                        shutil.copy2(src, dst)
            st("生成 moding 覆盖结构", True, overlay)
    except (OSError, shutil.Error) as e:
        st("生成 moding 覆盖结构", False, str(e)); return out

    out["ok"] = all(s["ok"] for s in steps)
    out["files"] = [os.path.join(overlay, rel_comp), os.path.join(overlay, rel_macro)]
    _refresh_soft()   # 新增 dock 组件/宏：宏清单等整体缓存失效，模板列表即时可见
    return out

def vanilla_enums():
    """枚举型属性的标准取值。
    icon：图标是全局 UI 体系 → 扫原版全部尺寸舰船 icon + 并入 EVE mod 用到的（保证可回填）；
    type：原版 L/XL 舰船类型；
    makerrace：原版 + 工具已知派系。"""
    en = {"icon": set(), "type": set(), "makerrace": set()}
    # icon：原版全部尺寸 + EVE mod
    for root in (VANILLA_DIR, os.path.join(MOD_DIR, "assets", "units")):
        if not os.path.isdir(root):
            continue
        for sz in os.listdir(root):
            d = os.path.join(root, sz, "macros")
            if not os.path.isdir(d):
                continue
            for fn in os.listdir(d):
                if not (fn.startswith("ship_") and fn.endswith("_macro.xml")):
                    continue
                m = re.search(r'icon="([^"]+)"', open(os.path.join(d, fn), encoding="utf-8").read())
                if m: en["icon"].add(m.group(1))
    # type：原版 L/XL（ship macro 的 <ship type>）
    for size in ("l", "xl"):
        d = os.path.join(VANILLA_DIR, "size_%s" % size, "macros")
        if not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            if not (fn.startswith("ship_") and fn.endswith("_macro.xml")):
                continue
            m = re.search(r'<ship type="([^"]+)"', open(os.path.join(d, fn), encoding="utf-8").read())
            if m: en["type"].add(m.group(1))
    # makerrace：模拟加载后，从原版 + 各扩展实际生效的 storage/ship macro 提取
    # （makerrace = 存储/装备制造商派系，写在 storage/ship macro 里，不是 ship 独有）
    for base in ([VANILLA_DIR] + [os.path.join(ROOT, "extensions", m, "assets", "units") for m in _ext_order()]):
        if not os.path.isdir(base):
            continue
        for sz in os.listdir(base):
            mac = os.path.join(base, sz, "macros")
            if not os.path.isdir(mac):
                continue
            for fn in os.listdir(mac):
                if not (fn.startswith(("storage_", "ship_")) and fn.endswith("_macro.xml")):
                    continue
                m = re.search(r'makerrace="([^"]+)"', open(os.path.join(mac, fn), encoding="utf-8").read())
                if m:
                    v = m.group(1).strip()
                    if re.fullmatch(r"[a-z]+", v):   # 过滤异常值（如 "argon teladi"）
                        en["makerrace"].add(v)
    # 固定枚举：purpose / thruster / secrecy（已从原版 L/XL 核实的标准取值）
    en["purpose"]   = sorted(["fight", "trade", "mine", "build", "auxiliary"])
    en["thruster"]  = sorted(["large", "extralarge"])
    en["secrecy"]   = sorted(["1", "2", "3"])
    # 显示名：中文优先（游戏标准译名 / 派系官方中文名），无则用 id
    cn_type = {"fight":"战斗", "trade":"贸易", "mine":"采矿", "build":"建造", "auxiliary":"辅助"}
    cn_thruster = {"large":"大型", "extralarge":"超大型"}
    cn_secrecy = {"1":"机密 1", "2":"机密 2", "3":"机密 3"}
    fac_by_id = {f["id"]: f["name"] for f in _FACTIONS_ALL}
    def lst(vals, cn):
        return [{"id": v, "name": cn.get(v, "") or v} for v in sorted(vals)]
    return {
        "icon": lst(en["icon"], {}),
        "type": lst(en["type"], cn_type),
        "makerrace": [{"id": v, "name": fac_by_id.get(RACE_FACTION.get(v, v), v)} for v in sorted(en["makerrace"])],
        "purpose": lst(en["purpose"], cn_type),
        "thruster": lst(en["thruster"], cn_thruster),
        "secrecy": lst(en["secrecy"], cn_secrecy),
    }

def _ext_order():
    """模拟扩展加载顺序：官方 DLC 在前，用户 mod 按字母序在后，后加载者覆盖先加载者。"""
    ex = os.path.join(ROOT, "extensions")
    mods = [d for d in os.listdir(ex) if os.path.isdir(os.path.join(ex, d))] if os.path.isdir(ex) else []
    official = sorted(d for d in mods if d.startswith("ego_dlc_"))
    others = sorted(d for d in mods if not d.startswith("ego_dlc_"))
    return official + others

# ---------- 统一扫描缓存框架（签名校验 + 按来源局部更新）----------
# 所有慢速扫描器统一走这里：结果按「来源」落盘，并记录该来源输入树的签名
# [文件数, 最大 mtime_ns, 总字节]。启动/首次访问时只重扫签名变化的来源，其余直接复用。
_CACHE_DIR = os.path.join(BASE, "cache")
_CACHE_VER = 2

def _sig_paths(paths, exts=(".xml",), only_dirs=None):
    """输入树签名：文件数 + 最大修改时间 + 总字节。目录递归统计（默认只看 .xml）。
    only_dirs：只统计文件名目录名命中的子树（如 {"macros"}），减少无关文件 stat。"""
    n = mt = sz = 0
    for p in paths:
        if not p:
            continue
        if os.path.isfile(p):
            try:
                st = os.stat(p)
            except OSError:
                continue
            n += 1
            mt = max(mt, st.st_mtime_ns)
            sz += st.st_size
        elif os.path.isdir(p):
            for r, _ds, fs in os.walk(p):
                if only_dirs and os.path.basename(r) not in only_dirs:
                    continue
                for f in fs:
                    if exts and not f.lower().endswith(exts):
                        continue
                    try:
                        st = os.stat(os.path.join(r, f))
                    except OSError:
                        continue
                    n += 1
                    mt = max(mt, st.st_mtime_ns)
                    sz += st.st_size
    return [n, mt, sz]

def _cache_load(name):
    try:
        with open(os.path.join(_CACHE_DIR, name), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) and d.get("ver") == _CACHE_VER else None
    except Exception:
        return None

def _cache_save(name, data):
    """原子写：先写 .tmp 再 replace，避免中断留下半截 JSON。"""
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        fp = os.path.join(_CACHE_DIR, name)
        tmp = fp + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, fp)
    except Exception:
        pass

def _cached_sources(name, sources, scan, exts=(".xml",), only_dirs=None):
    """按来源分片缓存。sources=[(src,[paths...])]，scan(src)->可 JSON 化结果。
    返回 ({src: data}, {src: sig}, 本次重扫的来源列表)。"""
    c = _cache_load(name) or {}
    old = c.get("items") or {}
    out, sigs, changed = {}, {}, []
    for src, paths in sources:
        sig = _sig_paths(paths, exts, only_dirs)
        e = old.get(src)
        if e and e.get("sig") == sig:
            out[src] = e.get("data")
        else:
            out[src] = scan(src)
            changed.append(src)
        sigs[src] = sig
    if changed or not c:
        _cache_save(name, {"ver": _CACHE_VER,
                           "items": {s: {"sig": sigs[s], "data": out[s]} for s in out}})
    return out, sigs, changed

def _cached_whole(name, paths, build, exts=(".xml",), only_dirs=None):
    """整体缓存（输入跨来源关联、无法按来源拆分时用）：签名一致直接返回，否则重建。"""
    sig = _sig_paths(paths, exts, only_dirs)
    c = _cache_load(name)
    if c and c.get("sig") == sig and "data" in c:
        return c["data"]
    data = build()
    _cache_save(name, {"ver": _CACHE_VER, "sig": sig, "data": data})
    return data

def _assets_roots():
    """原版 + 全部扩展的 assets 根目录（加载序：原版在前）。"""
    roots = [os.path.join(ROOT, "assets")]
    ext = os.path.join(ROOT, "extensions")
    if os.path.isdir(ext):
        for d in sorted(os.listdir(ext)):
            p = os.path.join(ext, d, "assets")
            if os.path.isdir(p):
                roots.append(p)
    return roots

_WARES_MAP = {}
_WARES_BY_SOURCE = {}
_WARES_DIRTY = True

def _build_wares_index():
    """一次性读全部 wares.xml（覆盖序：高优先 mod 在前，原版兜底）建 {ware_id: 匹配段} 索引。
    同名 ware 保留最先出现（最高优先）的定义。写入/删除 ware 后需置 _WARES_DIRTY=True 重建。
    同时按来源（原版/DLC/mod）独立建 _WARES_BY_SOURCE，供"忠实呈现"各来源自己的定义。"""
    global _WARES_MAP, _WARES_DIRTY, _WARES_BY_SOURCE
    _WARES_MAP = {}
    _WARES_BY_SOURCE = {}
    def _idx(_wp, _src):
        if not os.path.isfile(_wp):
            return
        try:
            txt = open(_wp, encoding="utf-8", errors="ignore").read()
        except Exception:
            return
        d = _WARES_BY_SOURCE.setdefault(_src, {})
        for _m in re.finditer(r'<ware id="([^"]+)"[^>]*>(.*?)</ware>', txt, re.S):
            _id = _m.group(1)
            if _id not in _WARES_MAP:      # 覆盖序索引：高优先（后加载 mod）在前
                _WARES_MAP[_id] = _m
            if _id not in d:               # 按来源独立索引：忠实呈现该来源自己的定义
                d[_id] = _m
    for m in reversed(_ext_order()):
        _idx(os.path.join(ROOT, "extensions", m, "libraries", "wares.xml"), m)
    _idx(os.path.join(ROOT, "libraries", "wares.xml"), "vanilla")
    _WARES_DIRTY = False

def _find_ware(eid):
    """覆盖序查某 ware（含 owner/成本/材料）。vro 等 mod 常只覆盖宏/组件、不覆盖 ware，故回退原版/DLC。
    返回整个 re match（group(1)=ware id，group(2)=ware 正文）；找不到返回 None。"""
    if _WARES_DIRTY:
        _build_wares_index()
    return _WARES_MAP.get(eid)

def _find_ware_in(source, eid):
    """忠实按来源查某 ware：只读该 source（原版/DLC/mod）自己 wares.xml 里的定义，
    有多少回填多少，不做跨来源覆盖拼接。返回整个 re match；找不到返回 None。"""
    if _WARES_DIRTY:
        _build_wares_index()
    return (_WARES_BY_SOURCE.get(source) or {}).get(eid)

def _is_diff_txt(t):
    """判定组件文本是否为 <diff> 补丁格式（容忍 BOM/XML 声明前缀——vro 的 diff 文件
    开头是 <?xml version="1.0"?>，直接 strip().startswith 会误判为完整组件）。
    必须定义在 ship_sources_all 之前：模块加载期 TEMPLATES=list_templates() 会走到这里。"""
    h = t[:300].lstrip("\ufeff").lstrip()
    if h.startswith("<diff"):
        return True
    if h.startswith("<?xml"):
        x = h.find("?>")
        return x >= 0 and h[x+2:].lstrip().startswith("<diff")
    return False

# diff 文件规范头（theqmann XML Patch Guide：带 xmlns:xsi 可避免游戏 Debug Log 报错）
DIFF_OPEN = '<diff xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
DIFF_HEADER = '<?xml version="1.0" encoding="utf-8"?>\n' + DIFF_OPEN + '\n'

def ship_sources_all():
    """扫描原版 + extensions 各 mod 的 assets/units/size_{l,xl} 舰船组件（class 含 ship，
    结构规则不靠文件名命名），返回 {(size, ship id): [按加载序的来源列表]}。
    同 id 多来源 = 游戏内重复 id（后加载者覆盖生效，列表末位为胜者）；
    供模板列表 [重复] 单列展示与按来源忠实读取（对齐装备页 equip_scan 双结构）。"""
    ships = {}
    sources = [("vanilla", os.path.join(ROOT, "assets", "units"))] + \
              [(m, os.path.join(ROOT, "extensions", m, "assets", "units")) for m in _ext_order()]
    for src, base in sources:
        for size in ("l", "xl"):
            d = os.path.join(base, "size_%s" % size)
            if not os.path.isdir(d):
                continue
            for fn in sorted(os.listdir(d)):
                if fn.endswith("_macro.xml"):   # 排除散落在 size 根目录的 macro 伪条目
                    continue
                p = os.path.join(d, fn)
                try:
                    head = open(p, encoding="utf-8").read(2000)
                except Exception:
                    continue
                cm = re.search(r'<component\b[^>]*class="([^"]*)"', head)
                if cm and "ship" in cm.group(1):
                    ships.setdefault((size, fn[:-4]), []).append(src)
                elif not cm and _is_diff_txt(head) and (size, fn[:-4]) in ships:
                    # <diff> 补丁文件头部无 <component> 标签（正则可能只命中文件尾注释里保留的旧内容）：
                    # 补丁必作用于已存在的 base 组件，继承同 id 早前来源的舰船判定
                    ships[(size, fn[:-4])].append(src)
    return ships

def _ship_unit_dir(src, size):
    """来源 src 的 units 目录：vanilla=解包根 assets，mod=extensions/<src>/assets。"""
    return os.path.join(ROOT, "assets", "units") if src == "vanilla" \
        else os.path.join(ROOT, "extensions", src, "assets", "units")

def _read_ship_comp_txt(comp, size, cid, src):
    """读舰船组件文本；若为 <diff> 补丁（如 vro 覆盖原版船改挂载点），按来源链定位被覆盖的
    base 组件（加载序中当前来源之前最近的完整组件）并应用补丁后返回合并文本，
    与游戏加载语义一致。非 diff 或找不到 base 时返回原文。"""
    txt = open(comp, encoding="utf-8", errors="ignore").read()
    if not _is_diff_txt(txt):
        return txt
    srcs = (ship_sources_all().get((size, cid)) or [])
    if src in srcs:
        for s in reversed(srcs[:srcs.index(src)]):
            bp = os.path.join(_ship_unit_dir(s, size), "size_%s" % size, cid + ".xml")
            if os.path.isfile(bp):
                bt = open(bp, encoding="utf-8", errors="ignore").read()
                if not _is_diff_txt(bt):
                    return _apply_diff_replaces(bt, txt)
    return txt

def _find_ship_macro_global(size, cid):
    """宏文件跨来源定位（模拟宏文件覆盖链）：按加载序取最后一个存在宏文件的来源。
    用于组件被 <diff> 补丁覆盖、自身无宏文件的 mod（如 vro 对原版船只改挂载点）——
    该场景游戏实际生效的宏就是原版那份。全链都无宏返回 None。"""
    found = None
    for src in ["vanilla"] + _ext_order():
        q = _find_ship_macro(os.path.join(_ship_unit_dir(src, size), "size_%s" % size), cid)
        if os.path.isfile(q):
            found = q
    return found

FAC_MAJOR = {"player","argon","antigone","alliance","paranid","holyorder","trinity","teladi",
              "ministry","split","freesplit","boron","terran","pioneers"}
FAC_MINOR = {"scaleplate","hatikvah","buccaneers","criminal","loanshark","scavenger","court","holyorderfanatic","fallsplit","fallensplit"}
FAC_SMALL = {"civilian","visitor","smuggler","outlaw","ownerless","yaki"}
FAC_ENEMY = {"xenon","khaak"}
FAC_CAT_NAME = {"player":"玩家","major":"主要阵营","minor":"次要派系","small":"小派系",
                "other":"其他派系","enemy":"敌对派系"}
FAC_CAT_ORDER = ["player","major","minor","small","other","enemy"]
def _fac_cat(fid):
    if fid in FAC_MAJOR: return "major"
    if fid in FAC_MINOR: return "minor"
    if fid in FAC_SMALL: return "small"
    if fid in FAC_ENEMY: return "enemy"
    return "other"

def _all_factions():
    """模拟加载后合并全部派系（原版 + 所有 mod，diff 覆盖语义），name 用官方中文名（经清洗）。
    按 玩家/主要/次要/小派系/其他/敌对 分类并排序。"""
    refs, order, srcs = {}, [], {}
    vanilla_p = os.path.join(ROOT, "libraries", "factions.xml")
    files = [vanilla_p] + \
            [os.path.join(ROOT, "extensions", d, "libraries", "factions.xml") for d in _ext_order()]
    for fp in files:
        if not os.path.isfile(fp):
            continue
        txt = open(fp, encoding="utf-8").read()
        src = "vanilla" if fp == vanilla_p else os.path.basename(os.path.dirname(os.path.dirname(fp)))
        for m in re.finditer(r'<faction\b(?=[^>]*\bid="([^"]+)")([^>]*)>', txt):
            fid, attrs = m.group(1), m.group(2)
            mm = re.search(r'name="([^"]+)"', attrs)
            if mm and fid not in refs:
                refs[fid] = mm.group(1); order.append(fid); srcs[fid] = src
    oi = {f: i for i, f in enumerate(order)}
    ci = {c: i for i, c in enumerate(FAC_CAT_ORDER)}
    out = [{"id": fid, "name": LX.lname(ref, fid, "zh") or (_zh_id(fid) + "[译]"),
            "source": srcs.get(fid, "vanilla"),
            "category": _fac_cat(fid), "cat_name": FAC_CAT_NAME[_fac_cat(fid)]}
           for fid, ref in refs.items()]
    out.sort(key=lambda x: (ci.get(x["category"], 99), oi.get(x["id"], 99)))
    return out

_FACTIONS_ALL = _all_factions()

def _ship_ware_candidates(cid, mac_path):
    """舰船 ware id 候选集合：macro 基名（去 _macro.xml）→ cid → cid_a → cid_b。
    原版舰船 ware id 与 cid 对应不统一，覆盖序匹配时依次尝试。"""
    cands = [cid, cid + "_a", cid + "_b"]
    if mac_path and os.path.isfile(mac_path):
        bn = os.path.basename(mac_path)
        if bn.endswith("_macro.xml"):
            cands.insert(0, bn[:-len("_macro.xml")])
    return cands

def _find_ship_macro(d, cid):
    """在 size_{l,xl}/macros 目录定位舰船 macro 文件。
    官方舰船 macro 文件名常为 component 名 + 变体后缀（如 ship_kha_l_destroyer_01.xml
    → ship_kha_l_destroyer_01_a_macro.xml），不能靠 cid+"_macro" 硬拼。
    查找顺序：精确名 → 同前缀以 _macro.xml 结尾的首个文件（取字母序最前）。"""
    mac_dir = os.path.join(d, "macros")
    cand = os.path.join(mac_dir, cid + "_macro.xml")
    if os.path.isfile(cand):
        return cand
    if os.path.isdir(mac_dir):
        for fn in sorted(os.listdir(mac_dir)):
            if fn.startswith(cid + "_") and fn.endswith("_macro.xml"):
                return os.path.join(mac_dir, fn)
    return cand

def _build_templates():
    """模拟 DLC/mod 加载后，扫描游戏实际生效的全部 L/XL 舰船（原版 + 所有扩展），
    构建模板清单；source 标注来源（vanilla 或 mod 目录名）。
    同时读出每艘舰船的 t 文本 id 与当前名称/描述，供"修改已有舰船"回填。"""
    tpls = []
    # 展开为逐来源条目序列（同 id 多来源相邻；_dup=多来源重复、_win=加载序胜者）
    _seq = [(size, cid, src, len(srcs) > 1, src == srcs[-1])
            for (size, cid), srcs in ship_sources_all().items() for src in srcs]
    for size, cid, src, _dup, _win in _seq:
        base = os.path.join(ROOT, "assets", "units") if src == "vanilla" else os.path.join(ROOT, "extensions", src, "assets", "units")
        d = os.path.join(base, "size_%s" % size)
        comp_path = os.path.join(d, cid + ".xml")
        mac_path = _find_ship_macro(d, cid)
        if not os.path.isfile(mac_path):
            # 该来源无自有宏（典型：组件被 <diff> 补丁覆盖的 mod，如 vro 只改原版船挂载点）
            # → 回退宏覆盖链（游戏实际生效的宏，即原版那份），保证胜者条目数据不空
            _mg = _find_ship_macro_global(size, cid)
            if _mg:
                mac_path = _mg
        props = {"hull":"", "storage":"", "cargo":"", "icon":"", "type":"",
                 "explosion":"", "people":"", "mass":"", "inertia":"",
                 "drag":"", "missile":"", "unit":"", "deployable":"",
                 "countermeasure":"", "makerrace":"",
                 "purpose":"", "thruster":"", "secrecy":""}
        stor = {}
        tids = [None, None, None]
        name_ref = base_ref = desc_ref = ""
        if os.path.isfile(mac_path):
            txt = open(mac_path, encoding="utf-8").read()
            m2 = re.search(r'<hull max="([^"]+)"', txt)
            if m2: props["hull"] = m2.group(1)
            m2 = re.search(r'<people capacity="([^"]+)"', txt)
            if m2: props["people"] = m2.group(1)
            m2 = re.search(r'<physics mass="([^"]+)"', txt)
            if m2: props["mass"] = m2.group(1)
            m2 = re.search(r'<explosiondamage value="([^"]+)" shield="([^"]+)"', txt)
            if m2: props["explosion"] = m2.group(1) + "/" + m2.group(2)
            m2 = re.search(r'<inertia pitch="([^"]+)" yaw="([^"]+)" roll="([^"]+)"', txt)
            if m2: props["inertia"] = "%s/%s/%s" % m2.groups()
            m2 = re.search(r'<drag forward="([^"]+)" reverse="([^"]+)" horizontal="([^"]+)" vertical="([^"]+)" pitch="([^"]+)" yaw="([^"]+)" roll="([^"]+)"', txt)
            if m2: props["drag"] = "/".join(m2.groups())
            m2 = re.search(r'icon="([^"]+)"', txt)
            if m2: props["icon"] = m2.group(1)
            m2 = re.search(r'<ship type="([^"]+)"', txt)
            if m2: props["type"] = m2.group(1)
            m2 = re.search(r'<storage missile="([^"]+)" unit="([^"]+)"(?: deployable="([^"]+)")?(?: countermeasure="([^"]+)")?', txt)
            if m2:
                props["missile"], props["unit"] = m2.group(1), m2.group(2)
                props["deployable"] = m2.group(3) or ""
                props["countermeasure"] = m2.group(4) or ""
            m2 = re.search(r'<component ref="([^"]+)"', txt)
            if m2: props["component"] = m2.group(1)
            m2 = re.search(r'<purpose primary="([^"]+)"', txt)
            if m2: props["purpose"] = m2.group(1)
            m2 = re.search(r'<thruster tags="([^"]+)"', txt)
            if m2: props["thruster"] = m2.group(1)
            m2 = re.search(r'<secrecy level="([^"]+)"', txt)
            if m2: props["secrecy"] = m2.group(1)
            # 建造成本（wares.xml 里该 ship 的 <ware id=...>）。原版舰船 ware id 与 cid 对应关系不统一：
            # 生成的新船 ware id = cid；原版多为 macro 名（去 _macro.xml，含 _a/_b 变体）或 cid+_a/_b。
            # 依次尝试 macro 基名 → cid → cid_a → cid_b。
            wm = None
            for _wid in _ship_ware_candidates(cid, mac_path):
                wm = _find_ware_in(src, _wid)   # 忠实该来源（生效 source）自己的 wares.xml
                if wm:
                    break
            if wm:
                    wb = wm.group(2)   # group(1)=ware id, group(2)=ware 正文
                    c = {"price_min":"", "price_avg":"", "price_max":"", "time":"", "materials":[]}
                    pm = re.search(r'<price min="([^"]*)" average="([^"]*)" max="([^"]*)"', wb)
                    if pm: c["price_min"], c["price_avg"], c["price_max"] = pm.group(1), pm.group(2), pm.group(3)
                    pt = re.search(r'<production\s+[^>]*time="([^"]*)"', wb)
                    if pt: c["time"] = pt.group(1)
                    # 读取全部建造方式（production method）段：每种方式一段资源
                    c["production"] = []
                    for p in re.finditer(r'<production\b[^>]*>(.*?)</production>', wb, re.S):
                        mth = re.search(r'\bmethod="([^"]*)"', p.group(0))
                        pt2 = re.search(r'\btime="([^"]*)"', p.group(0))
                        c["production"].append({
                            "method": mth.group(1) if mth else "default",
                            "time": pt2.group(1) if pt2 else "",
                            "materials": [{"ware":m.group(1), "amount":m.group(2)}
                                          for m in re.finditer(r'<ware\s+ware="([^"]*)"\s+amount="([^"]*)"', p.group(1))]
                        })
                    if c["production"]:
                        c["time"] = c["production"][0]["time"]
                    props["cost"] = c
            # t 文本引用：保留 {page,id} 完整串，供 LX.lname 递归展开 + 清洗（带 page 的全量表，跨 mod 正确）。
            # identification 属性顺序/存在性多样（有的无 basename、有的含 makerrace/icon），宽松分别提取。
            m2 = re.search(r"<identification[^>]*>", txt)
            if m2:
                idtag = m2.group(0)
                def _a(attr):
                    mm = re.search(r'%s="(\{[^"]*\})"' % attr, idtag)
                    return mm.group(1) if mm else ""
                name_ref, base_ref, desc_ref = _a("name"), _a("basename"), _a("description")
                tids = []
                for g in (name_ref, base_ref, desc_ref):
                    mm = re.search(r"\{(\d+),\s*(\d+)\}", g)
                    tids.append(int(mm.group(2)) if mm else None)
        # storage macro（正确路径：storage_{去ship_前缀}_macro）
        st_path = os.path.join(d, "macros", "storage_" + cid[5:] + "_macro.xml")
        stor_id = "storage_" + cid[5:] + "_macro"
        if not os.path.isfile(st_path):
            st_path = os.path.join(d, "macros", "storage_" + cid + "_macro.xml")
            stor_id = "storage_" + cid + "_macro"
        if os.path.isfile(st_path):
            txt = open(st_path, encoding="utf-8").read()
            m2 = re.search(r'<cargo max="([^"]+)"', txt)
            if m2: props["cargo"] = m2.group(1)
            m2 = re.search(r'makerrace="([^"]+)"', txt)
            if m2: props["makerrace"] = m2.group(1)
        # dockarea（从 macro connections 找 dockarea 引用）
        dock = ""
        if os.path.isfile(mac_path):
            m2 = re.search(r'<macro ref="(dockarea_[^"]+)"', open(mac_path, encoding="utf-8").read())
            if m2: dock = m2.group(1)
        _rc = cid.split("_")
        # race_code：优先 ship_<race>_<size>_<name> 文件名结构；非标准文件名回退到 storage 的 makerrace
        _race_code = (_rc[1] if len(_rc) >= 3 and _rc[0] == "ship"
                      else (props.get("makerrace") or (_rc[0] if len(_rc) == 1 else "")))
        tpls.append({
            "id": cid, "race_code": _race_code, "size": size, "source": src,
            "dup": _dup, "win": _win,
            "name": re.sub(r"^ship_[a-z0-9]+_(l|xl)_", "", cid) or cid.split("_")[-1],   # 兜底名去 ship_种族_尺寸_ 前缀（尾段数字 id 如 battleship_01 不再只显示 "01"）
            "race_label": RACE_LABEL.get(_race_code, _race_code),
            "size_label": SIZE_LABEL.get(size, size),
            "source_path": (ROOT if src == "vanilla" else os.path.join(ROOT, "extensions", src)),
            "props": props, "dockarea": dock, "storage_id": stor_id, "tids": tids,
            "name_zh": LX.lname(name_ref, "", "zh"),
            "name_en": LX.lname(name_ref, "", "en"),
            "desc_zh": LX.lname(desc_ref, "", "zh"),
            "desc_en": LX.lname(desc_ref, "", "en"),
        })
    return tpls

_TEMPLATES_CACHE = None
def _tpl_inputs():
    """舰船清单的全部输入：各来源 units/size_l|xl（组件+macros）、wares.xml、t 文本表。
    任一变化都会使缓存失效；签名一致则启动时零读取直接返回。"""
    paths = []
    for src in ["vanilla"] + _ext_order():
        base = os.path.join(ROOT, "assets", "units") if src == "vanilla" \
            else os.path.join(ROOT, "extensions", src, "assets", "units")
        paths += [os.path.join(base, "size_l"), os.path.join(base, "size_xl")]
        paths.append(os.path.join(ROOT, "libraries", "wares.xml") if src == "vanilla"
                     else os.path.join(ROOT, "extensions", src, "libraries", "wares.xml"))
        paths.append(os.path.join(ROOT, "t") if src == "vanilla"
                     else os.path.join(ROOT, "extensions", src, "t"))
    return paths

def list_templates():
    """舰船选项卡数据源：内存 + 磁盘双层缓存（签名校验，输入未变时启动零读取）。"""
    global _TEMPLATES_CACHE
    if _TEMPLATES_CACHE is None:
        _TEMPLATES_CACHE = _cached_whole("templates.json", _tpl_inputs(), _build_templates)
    return _TEMPLATES_CACHE
TEMPLATES = list_templates()

# ---------- 属性替换（新增与修改共用）----------
def _ins_before(mtxt, add, anchor="</properties>"):
    """在 anchor 前插入 add（带匹配缩进）；无 anchor 时原样返回。"""
    m = re.search(r'([ \t]*)' + re.escape(anchor), mtxt)
    if not m:
        return mtxt
    ind = m.group(1)
    return mtxt[:m.start()] + ind + add + "\n" + ind + anchor + mtxt[m.end():]

def _sub_or_ins(mtxt, pat, repl, add, ins_anchor="</properties>"):
    """目标标签存在则替换；缺失则插入标准标签（自制宏常缺标签，如 megathron 无 people/physics/purpose 等）。"""
    if re.search(pat, mtxt):
        return re.sub(pat, repl, mtxt, count=1)
    return _ins_before(mtxt, add, ins_anchor)

def _storage_apply(stxt, cargo, makerrace):
    """向 storage macro 写 cargo/makerrace：有则替换，缺失则插入标准标签。"""
    if cargo:
        stxt = _sub_or_ins(stxt, r'<cargo max="[^"]*"', '<cargo max="%s"'%cargo,
                           '<cargo max="%s"/>'%cargo)
    if makerrace:
        if re.search(r'makerrace="[^"]*"', stxt):
            stxt = re.sub(r'makerrace="[^"]*"', 'makerrace="%s"'%makerrace, stxt, count=1)
        elif re.search(r'<identification\b(?![^>]*\bmakerrace=)', stxt):
            stxt = re.sub(r'(<identification\b)', '\\1 makerrace="%s"'%makerrace, stxt, count=1)
        else:
            stxt = _ins_before(stxt, '<identification makerrace="%s"/>'%makerrace)
    return stxt

def _xml_check(txt):
    """写入前校验 XML 文本；非法返回错误描述（含行列），合法返回 None。防止把坏文件写进 mod 导致游戏加载失败。"""
    try:
        import xml.etree.ElementTree as _ET
        _ET.fromstring(txt)
        return None
    except Exception as e:
        return str(e)

def apply_props(mtxt, d):
    """将表单属性替换进 ship macro 文本。只改属性，不动结构；标签缺失时在 </properties> 前插入标准标签。返回新文本。"""
    if d.get("hull"):
        mtxt = _sub_or_ins(mtxt, r'<hull max="[^"]*"', '<hull max="%s"'%d["hull"],
                           '<hull max="%s"/>'%d["hull"])
    if d.get("explosion"):
        try:
            v,s = d["explosion"].split("/")
            # 注意：模式消费整个自闭合标签，替换串必须自带 />（否则截断标签导致 XML 非法）
            mtxt = _sub_or_ins(mtxt, r'<explosiondamage\b[^>]*?/>',
                               '<explosiondamage value="%s" shield="%s"/>'%(v,s),
                               '<explosiondamage value="%s" shield="%s"/>'%(v,s))
        except Exception: pass
    if d.get("people"):
        mtxt = _sub_or_ins(mtxt, r'<people\b[^>]*?/>', '<people capacity="%s"/>'%d["people"],
                           '<people capacity="%s"/>'%d["people"])
    if d.get("mass"):
        if re.search(r'<physics\b[^>]*?\bmass="[^"]*"', mtxt):
            mtxt = re.sub(r'(<physics\b[^>]*?\bmass=")[^"]*"', '\\g<1>%s"'%d["mass"], mtxt, count=1)
        elif re.search(r'<physics\b', mtxt):
            mtxt = re.sub(r'(<physics\b)', '\\1 mass="%s"'%d["mass"], mtxt, count=1)
    # inertia/drag：整标签替换（不依赖属性顺序）；子标签缺失时插到 </physics> 前；physics 块整体缺失时组装新块
    inertia_t = drag_t = None
    if d.get("inertia"):
        p = d["inertia"].split("/")
        if len(p)==3:
            inertia_t = '<inertia pitch="%s" yaw="%s" roll="%s"/>'%tuple(p)
    if d.get("drag"):
        p = d["drag"].split("/")
        if len(p)==7:
            drag_t = '<drag forward="%s" reverse="%s" horizontal="%s" vertical="%s" pitch="%s" yaw="%s" roll="%s"/>'%tuple(p)
    if not re.search(r'<physics\b', mtxt):
        if d.get("mass") or inertia_t or drag_t:
            inner = "".join(t for t in (inertia_t, drag_t) if t)
            blk = '<physics%s>%s</physics>' % ((' mass="%s"'%d["mass"]) if d.get("mass") else "", inner)
            mtxt = _ins_before(mtxt, blk)
    else:
        for t in (inertia_t, drag_t):
            if not t: continue
            pat = r'<inertia\b[^>]*?/>' if t.startswith("<inertia") else r'<drag\b[^>]*?/>'
            if re.search(pat, mtxt):
                mtxt = re.sub(pat, t, mtxt, count=1)
            elif "</physics>" in mtxt:
                mtxt = mtxt.replace("</physics>", t + "\n</physics>", 1)
            else:
                mtxt = _ins_before(mtxt, t)
    if d.get("storage"):
        parts = str(d["storage"]).split("/")
        def v(i):
            return parts[i].strip() if i < len(parts) else ""
        m0, m1, m2, m3 = v(0), v(1), v(2), v(3)
        tag = ""
        if m0: tag += ' missile="%s"' % m0
        if m1: tag += ' unit="%s"' % m1
        if m2: tag += ' deployable="%s"' % m2
        if m3: tag += ' countermeasure="%s"' % m3
        if tag:
            mtxt = _sub_or_ins(mtxt, r'<storage\b[^>]*?/>', '<storage%s/>' % tag, '<storage%s/>' % tag)
    if d.get("icon"):
        if re.search(r'icon="[^"]*"', mtxt):
            mtxt = re.sub(r'icon="[^"]*"', 'icon="%s"'%d["icon"], mtxt, count=1)
        elif re.search(r'<identification\b(?![^>]*\bicon=)', mtxt):
            mtxt = re.sub(r'(<identification\b)', '\\1 icon="%s"'%d["icon"], mtxt, count=1)
    if d.get("type"):
        mtxt = _sub_or_ins(mtxt, r'<ship type="[^"]*"', '<ship type="%s"'%d["type"],
                           '<ship type="%s"/>'%d["type"])
    if d.get("purpose"):
        mtxt = _sub_or_ins(mtxt, r'<purpose\b[^>]*?/>', '<purpose primary="%s"/>'%d["purpose"],
                           '<purpose primary="%s"/>'%d["purpose"])
    if d.get("thruster"):
        mtxt = _sub_or_ins(mtxt, r'<thruster\b[^>]*?/>', '<thruster tags="%s"/>'%d["thruster"],
                           '<thruster tags="%s"/>'%d["thruster"])
    if d.get("secrecy"):
        mtxt = _sub_or_ins(mtxt, r'<secrecy\b[^>]*?/>', '<secrecy level="%s"/>'%d["secrecy"],
                           '<secrecy level="%s"/>'%d["secrecy"])
    return mtxt

# ---------- 生成核心 ----------
def generate(d):
    """data: 用户表单。执行复制模型+改名+生成XML+更新注册。返回结果。"""
    new_id = (d.get("new_id") or "").strip().lower()
    if not parse_id(new_id):
        return {"ok": False, "error": "舰船ID非法：仅允许小写字母/数字/下划线，且以字母或下划线开头（X4 官方 XSD idname 规则），收到：%s" % (new_id or "（空）")}
    # 选模板（实时读磁盘，含最新新增的舰船）
    tlist = list_templates()
    tpl = next((t for t in tlist if t["id"] == d.get("template")
                and (not d.get("template_source") or t["source"] == d.get("template_source"))), None)
    if not tpl:
        return {"ok": False, "error": "请选择模板舰船"}
    if any(t["id"] == new_id for t in tlist):
        return {"ok": False, "error": "舰船ID已存在：%s（同 id 会覆盖已有宏与贴图别名，请换一个）" % new_id}
    size = tpl["size"]                       # 新船尺寸=模板尺寸（component class 承载，与 id 无关）
    name = re.sub(r"^ship_", "", new_id)     # 去掉可选的 ship_ 前缀，用于默认名称与 storage 派生
    faction = d.get("faction") or RACE_FACTION.get(tpl.get("race_code") or "", "argon")
    mod = d.get("target_mod") or MOD_DIR
    mod = os.path.normpath(mod)
    # 防误写原版：目标 mod 必须是 extensions 下的 mod 目录（前端选原版船时目标栏会显示原版根目录，须拦下）
    if not mod.startswith(os.path.normpath(os.path.join(ROOT, "extensions")) + os.sep):
        return {"ok": False, "error": "目标 mod 目录无效：%s（必须是 extensions 下的 mod，不能是原版目录）" % mod}
    if os.path.basename(mod).startswith("ego_dlc_"):
        return {"ok": False, "error": "目标 mod 不能是官方 DLC：%s（ego_dlc_* 只读，请选择你自己的 mod 目录）" % mod}
    rel = lambda *p: os.path.join(mod, *p)
    # 模板源目录：按模板来源（vanilla 或 mod 目录名）定位，模拟游戏从对应扩展读取
    src_base = os.path.join(ROOT, "assets") if tpl["source"] == "vanilla" else os.path.join(ROOT, "extensions", tpl["source"], "assets")

    size_dir = "size_" + size
    un = "units", size_dir            # src_base 已含 assets，这里不带 assets 前缀，避免 assets\assets 重复
    comp_name = new_id                    # ship_spl_xl_golem
    mac_name  = new_id + "_macro"
    stor_id   = "storage_" + name + "_macro"   # 对齐原版 storage_<去ship_前缀> 惯例，但不依赖强前缀（引擎只按 ref 精确引用）
    stor_name = stor_id.replace("_macro","")          # storage_spl_xl_golem

    created, modified = [], []
    # ---------- 1. 复制模型文件并改名 ----------
    # 1a. component ship_xxx.xml
    src_comp = os.path.join(src_base, *un, tpl["id"] + ".xml")
    if not os.path.isfile(src_comp):
        return {"ok": False, "error": "模板 component 缺失: %s" % src_comp}
    # diff 补丁型模板（如 vro 覆盖原版船）：必须合并 base 后再复制，
    # 否则新船组件是 <diff> 原文，游戏报 "key name diff is not recognized" 加载失败
    ctxt = _read_ship_comp_txt(src_comp, tpl["size"], tpl["id"], tpl["source"])
    # 改名 component name（必须，否则组件重名冲突）
    ctxt = ctxt.replace('name="%s"' % tpl["id"], 'name="%s"' % comp_name)
    mod_name = os.path.basename(mod)
    _geo_warns = []
    # 1b. data 目录先于组件写入复制：复制结果决定 geometry 改写。
    # 数据就绪 → geometry 指向新数据目录；缺失/复制失败 → 保持指向模板数据（共享），
    # 避免 geometry 悬空导致碰撞网格无效（玩家上船僵死的同类隐患）。
    src_data = os.path.join(src_base, *un, tpl["id"] + "_data")
    data_ready = False
    if os.path.isdir(src_data):
        dst_data = rel("assets", *un, comp_name + "_data")
        try:
            shutil.copytree(src_data, dst_data, dirs_exist_ok=True)
            _disable_jcs(dst_data)   # 复制得到的 .jcs 会令游戏崩溃，统一加 .disabled（实测结论）
            created.append(os.path.relpath(dst_data, mod))
            data_ready = True
        except (OSError, shutil.Error) as e:
            _geo_warns.append("模型数据目录复制失败（%s）：新船共享模板模型数据" % e)
    else:
        _geo_warns.append("模板模型数据目录 %s_data 不存在：新船共享模板模型数据（geometry 未改写）" % tpl["id"])
    if data_ready:
        # source 路径: 模板 id 目录 -> 新 id 目录
        ctxt = ctxt.replace("\\"+tpl["id"]+"_data", "\\"+comp_name+"_data")
        ctxt = ctxt.replace("/"+tpl["id"]+"_data", "/"+comp_name+"_data")
        # 几何路径归属：模板来自原版/DLC/其他 mod 时，<source geometry> 的 mod 段改为目标 mod（数据目录随目标走）
        if tpl["source"] == "vanilla":
            ctxt = re.sub(r'(geometry=")assets([/\\])',
                          lambda m: m.group(1) + "extensions" + m.group(2) + mod_name + m.group(2) + "assets" + m.group(2), ctxt)
        elif tpl["source"] != mod_name:
            ctxt = re.sub(r'(geometry="extensions[/\\])%s([/\\])' % re.escape(tpl["source"]),
                          r'\g<1>%s\g<2>' % mod_name, ctxt)
    # 挂载点 tags：按连接点写回新船 component（可选，按组/逐槽指定 tags）
    mtags = d.get("mount_tags") or []
    if mtags:
        ctxt, _ = write_mount_tags(ctxt, mtags)
    # material ref 保持模板 collection（共享材质），不替换
    dst_comp = rel("assets", *un, comp_name + ".xml")   # 写入带 assets 层（与 index 注册值及既有船布局一致）
    _err = _xml_check(ctxt)
    if _err:
        return {"ok": False, "error": "component XML 非法，拒绝写入（%s）：%s" % (os.path.basename(dst_comp), _err)}
    os.makedirs(os.path.dirname(dst_comp), exist_ok=True)
    open(dst_comp, "w", encoding="utf-8").write(ctxt)
    created.append(os.path.relpath(dst_comp, mod))

    # 1c. .ani 文件
    src_ani = os.path.join(src_base, *un, tpl["id"] + "_data.ani")
    if os.path.isfile(src_ani):
        dst_ani = rel("assets", *un, comp_name + "_data.ani")
        shutil.copy2(src_ani, dst_ani)
        created.append(os.path.relpath(dst_ani, mod))

    # 1d. dockarea（XL 舰船可能引用 dockarea）
    da_ok = False   # dockarea 组件+宏是否都已实际创建；否则不改宏引用、不注册（悬空注册会导致游戏崩溃）
    _da_warns = []
    if tpl["dockarea"]:
        da_name = tpl["dockarea"].replace("_macro","")  # dockarea_spl_xl_hel_01
        # 新 dockarea 名：把模板短名替换成新名（保留后缀_01）
        base = da_name.rsplit("_",1)[0]                # dockarea_spl_xl_hel
        suffix = da_name.rsplit("_",1)[1]              # 01
        new_da = base.rsplit("_",1)[0] + "_" + name + "_" + suffix  # dockarea_spl_xl_golem_01
        # 找 dockarea 组件与 macro：模板来源 → 原版 assets → 全部 extensions（含 DLC）依次搜索
        _da_roots = [src_base, os.path.join(ROOT, "assets")]
        _da_roots += sorted(glob.glob(os.path.join(ROOT, "extensions", "*", "assets")))
        def _da_find(rel_sub):
            for _r in _da_roots:
                _sd = os.path.join(_r, "structures", "dock", rel_sub) if rel_sub else os.path.join(_r, "structures", "dock")
                if not os.path.isdir(_sd):
                    continue
                for root,_,files in os.walk(_sd):
                    yield root, files
        da_comp = None
        for root, files in _da_find(""):
            if da_name+".xml" in files:
                da_comp = os.path.join(root, da_name+".xml"); break
        if da_comp:
            dat = open(da_comp, encoding="utf-8").read()
            dat = dat.replace('name="%s"' % da_name, 'name="%s"' % new_da)
            # geometry 共享原版数据：不改 _data 目录名、不改归属前缀、不复制数据目录。
            # 否则 geometry 会指向不存在的新名目录（如 DLC 模板时）→ 碰撞网格无效 → 玩家上船僵死。
            nd = rel("assets","structures","dock", new_da+".xml")
            os.makedirs(os.path.dirname(nd), exist_ok=True)
            open(nd,"w",encoding="utf-8").write(dat)
            created.append(os.path.relpath(nd, mod))
            # macro
            da_mac = None
            for root, files in _da_find("macros"):
                if da_name+"_macro.xml" in files:
                    da_mac = os.path.join(root, da_name+"_macro.xml"); break
            if da_mac:
                dt = open(da_mac, encoding="utf-8").read()
                dt = dt.replace('name="%s_macro"'%da_name, 'name="%s_macro"'%new_da)
                dt = dt.replace('ref="%s"'%da_name, 'ref="%s"'%new_da)
                nm = rel("assets","structures","dock","macros", new_da+"_macro.xml")
                os.makedirs(os.path.dirname(nm), exist_ok=True)
                open(nm,"w",encoding="utf-8").write(dt)
                created.append(os.path.relpath(nm, mod))
                da_ok = True
            else:
                _da_warns.append("模板 dockarea 宏 %s_macro 未找到源文件：已保留原 dockarea 引用（共享模板），未注册 %s" % (da_name, new_da))
        else:
            _da_warns.append("模板 dockarea 组件 %s 未找到源文件：已保留原 dockarea 引用（共享模板），未注册 %s" % (da_name, new_da))

    # ---------- 2. 生成 ship macro ----------
    # 宏文件名可能带变体后缀（如 ship_atf_xl_battleship_01_a_macro.xml），用 _find_ship_macro 定位
    src_mac = _find_ship_macro(os.path.join(src_base, *un), tpl["id"])
    if not os.path.isfile(src_mac):
        return {"ok":False,"error":"模板 macro 缺失: %s"%src_mac}
    mtxt = open(src_mac, encoding="utf-8").read()
    # 宏名 = 模板宏文件名去 .xml（兼容 _a 等变体后缀）；按 cid+"_macro" 硬拼会替换落空导致宏重名
    tpl_mac_name = os.path.basename(src_mac)[:-4]
    mtxt = mtxt.replace('name="%s"'%tpl_mac_name, 'name="%s"'%mac_name)
    mtxt = mtxt.replace('<component ref="%s"'%tpl["id"], '<component ref="%s"'%comp_name)
    # 属性替换（hull/爆炸/人员/质量/惯性/阻力/货舱/图标/类型）
    mtxt = apply_props(mtxt, d)
    # identification t ids（由 t 分配）：模板引用常为原版/DLC page（如 {20101,66601}），
    # 统一替换为新分配 t id（对齐装备流 _rep_ident 做法），否则游戏内沿用模板原名
    tids = allocate_tids(d)
    def _rep_ident(mm):
        tag = mm.group(0)
        tag = re.sub(r'\bname="\{[^"]*\}"', 'name="{7777771,%d}"' % tids[0], tag)
        tag = re.sub(r'\bbasename="\{[^"]*\}"', 'basename="{7777771,%d}"' % tids[1], tag)
        tag = re.sub(r'\bdescription="\{[^"]*\}"', 'description="{7777771,%d}"' % tids[2], tag)
        return tag
    mtxt = re.sub(r'<identification\b[^>]*>', _rep_ident, mtxt, count=1)
    # connections: storage 引用改名（先记模板 storage 宏实际名，供步骤 3 定位模板 storage 文件）
    m_st = re.search(r'<macro ref="(storage_[^"]+)"', mtxt)
    tpl_stor_name = m_st.group(1) if m_st else ""
    mtxt = re.sub(r'<macro ref="(storage_[^"]+)"', '<macro ref="%s"'%stor_id, mtxt)
    # connections: dockarea 引用改名（仅当新 dockarea 文件已实际生成；否则共享模板原引用）
    if tpl["dockarea"] and da_ok:
        da_base = tpl["dockarea"].replace("_macro","")
        n = da_base.rsplit("_",1)[0].rsplit("_",1)[0]+"_"+name+"_"+da_base.rsplit("_",1)[1]
        mtxt = re.sub(r'<macro ref="%s_macro"'%da_base, '<macro ref="%s_macro"'%n, mtxt)
    # macro connections 模块：启用时用编辑行整块替换 ship macro 的 connections 块
    mc = d.get("macro_connections") or {}
    if mc.get("enabled"):
        subst = {"{STORAGE}": stor_id}
        if tpl_stor_name:
            subst[tpl_stor_name] = stor_id          # 编辑行里的模板 storage 原名 → 新 storage 宏
        if tpl["dockarea"] and da_ok:
            subst["{DOCKAREA}"] = n + "_macro"
            subst[tpl["dockarea"].replace("_macro", "")] = n + "_macro"
            subst[tpl["dockarea"]] = n + "_macro"   # 兼容带/不带 _macro 两种写法
        comp_names = [c["name"] for c in ship_component_connections(tpl["id"], tpl["source"])]
        mtxt2, mc_err = _apply_macro_connections(mtxt, mc.get("rows") or [], comp_names, subst)
        if mc_err:
            return {"ok": False, "error": "macro connections：" + mc_err}
        mtxt = mtxt2
    dst_mac = rel("assets", *un, "macros", mac_name + ".xml")
    os.makedirs(os.path.dirname(dst_mac), exist_ok=True)
    if d.get("software"):
        mtxt = _apply_ship_software(mtxt, d["software"])
    _err = _xml_check(mtxt)
    if _err:
        return {"ok": False, "error": "macro XML 非法（多为模板文件原有坏标签，请检查 %s），拒绝写入：%s" % (tpl["id"]+"_macro.xml", _err)}
    open(dst_mac,"w",encoding="utf-8").write(mtxt)
    created.append(os.path.relpath(dst_mac, mod))

    # ---------- 3. 生成 storage macro ----------
    # 模板 storage 文件按 ship macro connections 里的实际 ref 定位（兼容 _a 等变体后缀）：
    # 先查 units\size_*\macros（mod 船/本工具写入位置），再查 props\storagemodules\macros（原版/DLC 位置）；
    # 都没有才走标准兜底
    src_st = ""
    if tpl_stor_name:
        for _cand in (os.path.join(src_base, *un, "macros", tpl_stor_name + ".xml"),
                      os.path.join(src_base, "props", "storagemodules", "macros", tpl_stor_name + ".xml")):
            if os.path.isfile(_cand):
                src_st = _cand
                break
    if src_st:
        stxt = open(src_st, encoding="utf-8").read()
        stxt = re.sub(r'<macro name="[^"]*"', '<macro name="%s"'%stor_id, stxt, count=1)
        stxt = _storage_apply(stxt, d.get("cargo"), d.get("makerrace"))
        dst_st = rel("assets", *un, "macros", stor_id + ".xml")
        _err = _xml_check(stxt)
        if _err:
            return {"ok": False, "error": "storage macro XML 非法，拒绝写入（%s）：%s" % (os.path.basename(dst_st), _err)}
        os.makedirs(os.path.dirname(dst_st), exist_ok=True)
        open(dst_st,"w",encoding="utf-8").write(stxt)
        created.append(os.path.relpath(dst_st, mod))
    else:
        # 模板没有独立 storage 文件：直接生成标准 storage macro
        stxt = ('<?xml version="1.0" ?>\n<macros>\n\t<macro name="%s" class="storage">\n'
                '\t\t<component ref="generic_storage"/>\n\t\t<properties>\n'
                '\t\t\t<identification makerrace="%s"/>\n'
                '\t\t\t<cargo max="%s" tags="container"/>\n\t\t\t<hull integrated="1"/>\n'
                '\t\t</properties>\n\t</macro>\n</macros>\n') % (stor_id, d.get("makerrace") or "argon",
                                                                  d.get("cargo") or "35000")
        dst_st = rel("assets", *un, "macros", stor_id + ".xml")
        os.makedirs(os.path.dirname(dst_st), exist_ok=True)
        open(dst_st,"w",encoding="utf-8").write(stxt)
        created.append(os.path.relpath(dst_st, mod))

    # ---------- 4. 更新注册文件 ----------
    upd = update_registry(mod, comp_name, mac_name, stor_id, new_da if (tpl["dockarea"] and da_ok) else None,
                          faction, size, name, d, tids)
    modified += upd.get("files", [])
    # 材质：合并模板 mod 的材质 collection 到目标 mod material_library，避免新船依赖模板 mod
    modified += merge_material_library(mod, src_comp, tpl["source"])
    # 材质参数调整（须在 collection 合并之后：本 mod 材质就地改值，外部材质追加 diff replace；
    # 改名则克隆副本并改写新船 component 引用）
    mtune_warns = []
    mtune = d.get("material_tuning") or {}
    if mtune.get("enabled"):
        mrels, mtune_warns = apply_material_tuning(mod, mtune, comp_path=dst_comp)
        modified += mrels
    # 舰船列表图标别名（ship_<id>_macro → 优先继承模板生效贴图，无则同 race_size 原版兜底）
    _sal = _ship_icon_alias(mod, new_id, tpl)
    if _sal:
        modified.append(_sal)
    moding = copy_to_moding(mod, created + modified)
    _refresh_soft()  # 舰船流不写装备/弹丸文件：轻量失效 t文本/wares索引/loadout/全局资产（免全量冷扫）
    return {"ok": True, "created": created, "modified": modified,
            "moding": moding, "moding_base": os.path.join(mod, "moding"),
            "warnings": verify_model_refs(mod, dst_comp) + jobs_skip_warn(d.get("jobs")) + mtune_warns + _geo_warns + _da_warns,
            "tids": tids, "new_da": new_da if (tpl["dockarea"] and da_ok) else None}

def verify_model_refs(mod, comp_path):
    """复制改名后只读抽查：component 引用的几何/材质等文件，在目标 mod（或原版 ROOT）中是否都存在。
    只收集缺失项返回 warning 列表，不阻断写入（抽查性质）。引用共享资源（原版/DLC/其他 mod）属正常，
    只要在 ROOT 或目标 mod 下能定位即视为完整。"""
    warns = []
    try:
        t = open(comp_path, encoding="utf-8").read()
    except Exception:
        return warns
    for m in re.finditer(r'<source\b[^>]*geometry="([^"]+)"', t):
        geo = m.group(1).replace("\\", "/")
        parts = [p for p in geo.split("/") if p]
        if not parts:
            continue
        if os.path.exists(os.path.join(mod, *parts)):
            continue                     # 目标 mod 内已复制改名，完整
        if os.path.exists(os.path.join(ROOT, *parts)):
            continue                     # 指向原版/DLC/其他 mod 共享资源，正常
        warns.append("模型几何引用缺失: %s" % geo)
    return warns

def merge_material_library(mod, tpl_comp_path, tpl_source):
    """新增舰船时，把模板船 component 引用的材质 collection 从模板 mod 合并进目标 mod 的
    material_library.xml（diff 追加；目标 mod 已有同名 collection 跳过，不覆盖）。
    材质引用格式 <material ref="collection.material"/>，取点号前段为 collection 名。
    返回修改的文件相对路径；无需合并则返回空。"""
    ctxt = open(tpl_comp_path, encoding="utf-8").read()
    colls = set()
    for m in re.finditer(r'<material\b[^>]*ref="([^"]+)"', ctxt):
        ref = m.group(1)
        if "." in ref:
            colls.add(ref.split(".", 1)[0])
    if not colls:
        return []
    tpl_ml = os.path.join(ROOT, "extensions", tpl_source, "libraries", "material_library.xml")
    if not os.path.isfile(tpl_ml):
        return []
    tml = open(tpl_ml, encoding="utf-8").read()
    blocks = []
    for coll in sorted(colls):
        m = re.search(r'<collection\s+name="%s"[^>]*>.*?</collection>' % re.escape(coll), tml, re.S)
        if m:
            blocks.append((coll, m.group(0)))
    if not blocks:
        return []
    mlp = os.path.join(mod, "libraries", "material_library.xml")
    to_add = blocks
    if os.path.isfile(mlp):
        txt = open(mlp, encoding="utf-8").read()
        existing = set(re.findall(r'<collection\s+name="([^"]+)"', txt))
        to_add = [(c, b) for c, b in blocks if c not in existing]
        if to_add:
            addtxt = "\n\t\t" + "\n\t\t".join(b for _, b in to_add)
            i = txt.rfind("</add>")
            if i >= 0:
                txt = txt[:i] + addtxt + txt[i:]
            else:
                txt = (DIFF_HEADER + '\t<add sel="//materiallibrary">\n'
                       + "\n\t\t".join(b for _, b in to_add) + '\n\t</add>\n</diff>')
            open(mlp, "w", encoding="utf-8").write(txt)
    else:
        os.makedirs(os.path.dirname(mlp), exist_ok=True)
        open(mlp, "w", encoding="utf-8").write(
            DIFF_HEADER + '\t<add sel="//materiallibrary">\n'
            + "\n\t\t".join(b for _, b in to_add) + '\n\t</add>\n</diff>')
    if to_add:
        return [os.path.relpath(mlp, mod)]
    return []

# ---------------- 船体材质参数（material_library.xml 读取/调整） ----------------
# 船体 PBR 着色器（p1/p2_complex_surface）常用 Float 参数白名单：(属性名, 中文名, 修改效果说明, 取值范围)
# 单一事实源：GET 按此筛列参数，POST 按此校验属性名；只处理材质中已存在的参数。
MAT_TUNABLE = [
    ("Smoothness", "光滑度", "越大表面越光滑、环境反射越清晰（抛光装甲/漆面感）；越小越粗糙，呈哑光漫反射。", "0~1"),
    ("Metallness", "金属度", "越大反射越偏金属（带环境染色的镜面高光）；越小越偏非金属涂层质感。", "0~1"),
    ("color_glowStr", "自发光强度", "发光贴图（舷窗/灯带）亮度倍数；调大灯带舷窗更亮，0 为不发光。", "0~10（1=原亮度，可>1）"),
    ("normalStr", "法线强度", "法线凹凸感倍数：调大表面刻线/接缝更立体，调小表面更平整。", "0~3（1=原始）"),
    ("environmentStr", "环境反射强度", "环境贴图在船身的反射量：调大太空/星云倒影更明显，调小更哑光。", "0~3（1=原始）"),
    ("diffuseStr", "基础色强度", "底色贴图亮度倍数：调大装甲颜色更亮更浅，调小更暗。", "0~2（1=原始）"),
    ("color_dirtStr", "污渍强度", "污渍/旧化层混合量：调大外观更陈旧脏污，0 为干净全新。", "0~1"),
    ("diffuse_paintStr", "涂装显色", "涂装层（玩家 paintmod 换色层）显色浓度：调大涂装颜色更鲜明。", "0~1"),
    ("diffuse_detailStr", "细节色强度", "近景细节底色叠加强度：凑近观察时表面纹理细节的明显程度。", "0~2（1=原始）"),
    ("normal_detailStr", "细节法线强度", "近景细节凹凸叠加强度：凑近时细微划痕/颗粒的立体感。", "0~2（1=原始）"),
    ("diffuse_detail_tiling", "细节色平铺", "细节色贴图 UV 重复次数：越大纹理越细密（只改密度不改亮度）。", "1~50（整数）"),
    ("diffuse_detail_tiling_v", "细节色平铺V", "细节色贴图纵向 UV 重复次数。", "1~50（整数）"),
    ("normal_detail_tiling", "细节法线平铺", "细节法线贴图 UV 重复次数：越大微凹凸越细密。", "1~50（整数）"),
    ("normal_detail_tiling_v", "细节法线平铺V", "细节法线贴图纵向 UV 重复次数。", "1~50（整数）"),
    ("color_dirt_tiling", "污渍平铺", "污渍贴图 UV 重复次数：越大污斑越小越碎。", "1~50（整数）"),
    ("color_dirt_tiling_v", "污渍平铺V", "污渍贴图纵向 UV 重复次数。", "1~50（整数）"),
]

def _ml_files_loadorder():
    """材质库文件加载序：原版两库 + 各扩展按加载序（模拟游戏合并顺序）。"""
    files = [os.path.join(ROOT, "libraries", "material_library.xml"),
             os.path.join(ROOT, "libraries", "material_library_1.xml")]
    for d in _ext_order():
        files.append(os.path.join(ROOT, "extensions", d, "libraries", "material_library.xml"))
    return [f for f in files if os.path.isfile(f)]

def _ml_src_label(fp):
    parts = fp.replace("\\", "/").split("/")
    if "extensions" in parts:
        return parts[parts.index("extensions") + 1]
    return "原版"

def _ml_find_material_span(txt, coll, mat):
    """在单个材质库文件文本中定位某 <material> 元素（含 <add> 包裹与整材质 <replace> 两种形态）。
    返回 (start, end, block)，找不到返回 None。"""
    cm = re.search(r'<collection\s+name="%s"[^>]*>.*?</collection>' % re.escape(coll), txt, re.S)
    if cm:
        mm = re.search(r'<material\s+name="%s"[^>]*>.*?</material>' % re.escape(mat), cm.group(0), re.S)
        if mm:
            return cm.start() + mm.start(), cm.start() + mm.end(), mm.group(0)
    rm = re.search(r'<replace\s+sel="[^"]*material\[@name=[\'\"]%s[\'\"]\]">\s*(<material\b.*?</material>)\s*</replace>'
                   % re.escape(mat), txt, re.S)
    if rm:
        return rm.start(1), rm.end(1), rm.group(1)
    return None

def _ml_parse_block(block):
    hm = re.search(r'<material\b([^>]*)>', block)
    attrs = hm.group(1) if hm else ""
    def _attr(k):
        am = re.search(r'\b%s="([^"]*)"' % k, attrs)
        return am.group(1) if am else ""
    props = {}
    for pm in re.finditer(r'<property\b([^>]*?)/>', block, re.S):
        pa = pm.group(1)
        nm = re.search(r'\bname="([^"]+)"', pa)
        tv = re.search(r'\btype="([^"]+)"', pa)
        vv = re.search(r'\bvalue="([^"]*)"', pa)
        if nm:
            props[nm.group(1)] = (tv.group(1) if tv else "", vv.group(1) if vv else "")
    return {"shader": _attr("shader"), "blendmode": _attr("blendmode"), "props": props}

def _ml_apply_replaces(txt, coll, mat, parsed):
    """对当前已解析材质应用本 diff 文件里的属性级 <replace>（@shader 与 property @value）。"""
    sel_coll = (r"collection\[@name=['\"]%s['\"]\]/material\[@name=['\"]%s['\"]\]"
                % (re.escape(coll), re.escape(mat)))
    pat = re.compile(
        r"<replace\s+sel=\"[^\"]*%s(/@\w+|/properties/property\[@name=['\"]([^'\"]+)['\"]\]/@value)\"[^>]*>\s*(.*?)\s*</replace>"
        % sel_coll, re.S)
    for rm in pat.finditer(txt):
        tail, pname, val = rm.group(1), rm.group(2), rm.group(3)
        if tail == "/@shader":
            parsed["shader"] = val
        elif pname and pname in parsed["props"]:
            parsed["props"][pname] = (parsed["props"][pname][0], val)

def _ml_resolve(ref):
    """按加载序解析 collection.material 的最终生效定义（扩展 add 新材质 + 属性级 replace 覆盖）。
    返回 (parsed, 来源标签, 材质原文块)；未找到返回 (None, "", None)。原文块供克隆副本使用。"""
    if "." not in ref:
        return None, "", None
    coll, mat = ref.split(".", 1)
    parsed, label, raw = None, "", None
    for fp in _ml_files_loadorder():
        txt = open(fp, encoding="utf-8", errors="ignore").read()
        span = _ml_find_material_span(txt, coll, mat)
        if span:
            parsed, label, raw = _ml_parse_block(span[2]), _ml_src_label(fp), span[2]
        if parsed is not None:
            _ml_apply_replaces(txt, coll, mat, parsed)
    return parsed, label, raw

def ship_materials(ship_id, source=None):
    """读某船 component 引用的 <material ref="collection.material"> 清单，并解析每个材质的可调参数当前值。"""
    tpl = next((t for t in list_templates() if t["id"] == ship_id
                and (not source or t["source"] == source)), None)
    empty = {"ship": ship_id, "materials": []}
    if not tpl:
        return empty
    size, src = tpl["size"], tpl["source"]
    base = os.path.join(ROOT, "assets", "units") if src == "vanilla" \
        else os.path.join(ROOT, "extensions", src, "assets", "units")
    comp = os.path.join(base, "size_%s" % size, ship_id + ".xml")
    if not os.path.isfile(comp):
        return empty
    ctxt = _read_ship_comp_txt(comp, size, ship_id, src)
    refs = []
    for mm in re.finditer(r'<material\b[^>]*\bref="([^"]+\.[^"]+)"', ctxt):
        if mm.group(1) not in refs:
            refs.append(mm.group(1))
    mats = []
    for ref in refs:
        parsed, label, _ = _ml_resolve(ref)
        if not parsed:
            mats.append({"ref": ref, "missing": True})
            continue
        params = [{"prop": n, "label": zh, "desc": desc, "range": rg,
                   "value": parsed["props"].get(n, ("", ""))[1]}
                  for n, zh, desc, rg in MAT_TUNABLE if n in parsed["props"]]
        mats.append({"ref": ref, "shader": parsed["shader"], "blendmode": parsed["blendmode"],
                     "source": label, "params": params})
    return {"ship": ship_id, "materials": mats}

def _ml_set_block_prop(block, ptype, p, v):
    """在单个 <material> 块文本内设置某 property 的 value：存在改值，缺失则在 </properties> 前插入。"""
    for tm in re.finditer(r'<property\b[^>]*?/>', block, re.S):
        tag = tm.group(0)
        if re.search(r'\bname="%s"' % re.escape(p), tag):
            if re.search(r'\bvalue="', tag):
                newtag = re.sub(r'\bvalue="[^"]*"', 'value="%s"' % v, tag, count=1)
            else:
                newtag = tag[:-2].rstrip() + ' value="%s" />' % v
            return block[:tm.start()] + newtag + block[tm.end():], True
    if "</properties>" in block:
        return block.replace("</properties>",
                             '\t\t\t\t<property type="%s" name="%s" value="%s" />\n\t\t\t</properties>'
                             % (ptype, p, v), 1), True
    return block, False

def _ml_reindent(block, base):
    """把材质块文本去掉原有公共缩进、改按 base 缩进，便于插入目标文件。"""
    lines = block.strip("\n").split("\n")
    ind = min((len(l) - len(l.lstrip())) for l in lines if l.strip())
    return "\n".join((base + l[ind:]) if l.strip() else "" for l in lines)

def _ml_insert_material(txt, coll, mat_block):
    """把 <material> 块插入材质库文本中名为 coll 的 collection；没有则新建 collection（在 //materiallibrary 的 add 块内）。
    返回新文本；无法插入（非 diff 结构等）返回 None。"""
    body = _ml_reindent(mat_block, "\t\t\t")
    cm = re.search(r'<collection\s+name="%s"[^>]*>.*?</collection>' % re.escape(coll), txt, re.S)
    if cm:
        pos = txt.rfind("</collection>", cm.start(), cm.end())
        return txt[:pos] + body + "\n\t\t" + txt[pos:]
    add = ('\t\t<collection name="%s">\n%s\n\t\t</collection>\n' % (coll, body))
    am = re.search(r'<add\s+sel="//materiallibrary"[^>]*>.*?</add>', txt, re.S)
    if am:
        pos = txt.rfind("</add>", am.start(), am.end())
        return txt[:pos] + add + "\t" + txt[pos:]
    block = '\t<add sel="//materiallibrary">\n%s\t</add>\n' % add
    if "</diff>" in txt:
        return txt.replace("</diff>", block + "</diff>", 1)
    if not txt.strip():
        return DIFF_HEADER + block + "</diff>\n"
    return None

def _ml_clone_material(txt, ref, newname, warns):
    """把 ref（collection.material）的生效定义克隆为同 collection 下的 newname，写入目标材质库文本。
    幂等：目标 mod 内已存在同名材质时视为已克隆，直接复用。返回 (新文本, 新ref 或 None)。"""
    coll, mat = ref.split(".", 1)
    new_ref = "%s.%s" % (coll, newname)
    if _ml_find_material_span(txt, coll, newname):
        return txt, new_ref                      # 本 mod 里已克隆过，直接复用
    if _ml_resolve(new_ref)[0]:
        warns.append("新材质名 %s 已存在于材质库（原版或其他 mod），克隆已跳过" % new_ref)
        return txt, None
    _, _, raw = _ml_resolve(ref)
    if not raw:
        # 回退：在目标材质库文本自身中找（仅定义于本 mod 的材质也能克隆）
        span = _ml_find_material_span(txt, coll, mat)
        if span:
            raw = span[2]
        else:
            warns.append("材质 %s 未找到定义，无法克隆" % ref)
            return txt, None
    clone = re.sub(r'(<material\s+name=")%s(")' % re.escape(mat), r'\g<1>%s\g<2>' % newname, raw, count=1)
    ntxt = _ml_insert_material(txt, coll, clone)
    if ntxt is None:
        warns.append("目标材质库非 diff 结构，无法插入克隆材质 %s" % new_ref)
        return txt, None
    return ntxt, new_ref

def apply_material_tuning(mod, tuning, comp_path=None, comp_backup=None, rename_mode="clone"):
    """把勾选的材质调整写入目标 mod。
    values 形态：{ref: {"rename": 新材质名(可选), "params": {prop: value}}}
    - rename（rename_mode="clone"，新增模式）：克隆该材质为新名副本（写入目标 mod 材质库），
      并把本船 component 中所有 ref 指向新名；原材质与其他共用它的船不受影响。
    - rename（rename_mode="replace"，修改模式）：就地重命名目标 mod 材质库里的材质定义，
      并扫描改写本 mod assets 下所有引用旧名的 XML（全部 component 一并更新）。
      外部材质（原版/其他 mod 定义）不支持 replace，会警告跳过。
    - params：材质直接定义于目标 mod → 就地改值/补插 property；属于原版/其他 mod → 在 <diff>
      追加属性级 <replace …/property[@name='p']/@value>（同 sel 幂等更新）。
    comp_path=本船 component 绝对路径（clone 模式改写引用用）；comp_backup=改写前备份回调。
    返回 (相对修改路径列表, 警告列表)。"""
    rels, warns = [], []
    if not isinstance(tuning, dict) or not tuning.get("enabled"):
        return rels, warns
    values = tuning.get("values") or {}
    if not values:
        return rels, warns
    allowed = {n for n, _, _, _ in MAT_TUNABLE}
    name_re = re.compile(r"^[A-Za-z0-9_]+$")
    mlp = os.path.join(mod, "libraries", "material_library.xml")
    txt = open(mlp, encoding="utf-8").read() if os.path.isfile(mlp) else ""
    changed = False
    # 第一遍：处理改名（克隆/替换），得到最终生效 ref -> params
    final = {}
    comp_rewrites = []
    for ref, spec in values.items():
        if "." not in ref or not isinstance(spec, dict):
            continue
        if "params" in spec or "rename" in spec:
            newname, params = (spec.get("rename") or "").strip(), (spec.get("params") or {})
        else:
            newname, params = "", spec                     # 兼容旧形态 {prop: value}
        if not isinstance(params, dict):
            params = {}
        if newname:
            coll, mat = ref.split(".", 1)
            if not name_re.match(newname):
                warns.append("新材质名 %s 含非法字符（仅允许字母/数字/下划线），已跳过 %s" % (newname, ref))
            elif newname == mat:
                warns.append("新材质名与原名称相同（%s），已跳过" % ref)
            elif rename_mode == "replace":
                # 修改模式：就地重命名本 mod 材质库中的定义，引用改写见函数尾部全 mod 扫描
                new_ref = "%s.%s" % (coll, newname)
                old_span = _ml_find_material_span(txt, coll, mat)
                new_span = _ml_find_material_span(txt, coll, newname)
                if new_span and not old_span:
                    comp_rewrites.append((ref, new_ref))   # 幂等：上次已改名，仍再扫引用
                    ref = new_ref
                elif not old_span:
                    warns.append("材质 %s 不定义于本 mod 材质库（外部材质），修改模式不支持重命名；"
                                 "如需独立外观请用「新增」模式克隆副本" % ref)
                elif _ml_resolve(new_ref)[0]:
                    warns.append("新材质名 %s 已存在于材质库（原版或其他 mod），重命名已跳过" % new_ref)
                else:
                    block = txt[old_span[0]:old_span[1]]
                    nb = re.sub(r'(<material\s+name=")%s(")' % re.escape(mat),
                                r'\g<1>%s\g<2>' % newname, block, count=1)
                    txt = txt[:old_span[0]] + nb + txt[old_span[1]:]
                    changed = True
                    comp_rewrites.append((ref, new_ref))
                    ref = new_ref                            # 参数作用于新名
            else:
                # 新增模式：克隆副本，仅本船换用
                txt, new_ref = _ml_clone_material(txt, ref, newname, warns)
                if new_ref:
                    changed = True
                    comp_rewrites.append((ref, new_ref))
                    ref = new_ref                            # 参数作用于副本
        final[ref] = params
    # 第二遍：写参数
    for ref, params in final.items():
        if not params or "." not in ref:
            continue
        coll, mat = ref.split(".", 1)
        span = _ml_find_material_span(txt, coll, mat)
        if span:
            parsed = _ml_parse_block(txt[span[0]:span[1]])   # 含刚克隆的副本
        else:
            parsed, _, _ = _ml_resolve(ref)                   # 外部/原版材质
        if not parsed:
            warns.append("材质 %s 未在材质库中找到定义，已跳过" % ref)
            continue
        for p, raw in params.items():
            v = ("" if raw is None else str(raw)).strip()
            if not v:
                continue
            if p not in allowed:
                warns.append("%s 的 %s 不在可调参数表，已跳过" % (ref, p))
                continue
            try:
                float(v)
            except ValueError:
                warns.append("%s 的 %s 值不是数字（%s），已跳过" % (ref, p, v))
                continue
            if span:
                block = txt[span[0]:span[1]]
                ptype = parsed["props"].get(p, ("Float", ""))[0] or "Float"
                nb, ok = _ml_set_block_prop(block, ptype, p, v)
                if not ok:
                    warns.append("%s 内无法写入 %s（缺少 properties 节点），已跳过" % (ref, p))
                    continue
                txt = txt[:span[0]] + nb + txt[span[1]:]
                changed = True
                span = _ml_find_material_span(txt, coll, mat)   # 偏移已变，重新定位
            else:
                if p not in parsed["props"]:
                    warns.append("%s 基础材质不含参数 %s，无法以 replace 新增，已跳过"
                                 "（可先填新材质名克隆副本，副本内可直接改值）" % (ref, p))
                    continue
                sel = ("/*/collection[@name='%s']/material[@name='%s']"
                       "/properties/property[@name='%s']/@value") % (coll, mat, p)
                line = '<replace sel="%s">%s</replace>' % (sel, v)
                pat = re.compile(r'<replace\s+sel="%s">\s*.*?\s*</replace>' % re.escape(sel), re.S)
                if pat.search(txt):
                    txt = pat.sub(line, txt, count=1)
                elif not txt.strip():
                    txt = DIFF_HEADER + "\t" + line + "\n</diff>\n"
                elif "</diff>" in txt:
                    txt = txt.replace("</diff>", "\t" + line + "\n</diff>", 1)
                else:
                    warns.append("目标材质库非 diff 结构，无法追加 replace：%s/%s" % (ref, p))
                    continue
                changed = True
    if changed:
        os.makedirs(os.path.dirname(mlp), exist_ok=True)
        open(mlp, "w", encoding="utf-8").write(txt)
        rels.append(os.path.relpath(mlp, mod))
    # 改写材质引用（材质名关联的 XML 一并修改）
    if comp_rewrites:
        def _rewrite(fp):
            ctxt = open(fp, encoding="utf-8", errors="ignore").read()
            n_all = 0
            for old_ref, new_ref in comp_rewrites:
                n = ctxt.count('ref="%s"' % old_ref)
                if n:
                    ctxt = ctxt.replace('ref="%s"' % old_ref, 'ref="%s"' % new_ref)
                    n_all += n
            if n_all:
                if comp_backup:
                    comp_backup(fp)
                open(fp, "w", encoding="utf-8").write(ctxt)
                rels.append(os.path.relpath(fp, mod))
            return n_all
        if rename_mode == "replace":
            # 修改模式：全 mod assets 扫描改写（所有共用该材质的 component 一并更新）
            assets_root = os.path.join(mod, "assets")
            total = 0
            if os.path.isdir(assets_root):
                for root, _, files in os.walk(assets_root):
                    for fn in files:
                        if fn.lower().endswith(".xml"):
                            total += _rewrite(os.path.join(root, fn))
            if not total:
                warns.append("本 mod 内未找到旧材质引用，引用未改写（材质已重命名）")
        else:
            # 新增模式：只改写本船 component
            if comp_path and os.path.isfile(comp_path):
                if not _rewrite(comp_path):
                    warns.append("本船 component 中未找到旧材质引用，引用未改写（材质副本已创建）")
            else:
                warns.append("未提供本船 component 路径，材质引用未改写（材质副本已创建）")
    return rels, warns

def edit(d):
    """修改一艘已有舰船的属性与名称/描述（写回原文件）。
    只改 ship macro 属性 + storage macro(cargo/makerrace) + t 文本；
    不碰 component/模型/挂载/注册结构。改前备份。"""
    cid = (d.get("id") or "").strip()
    tpl = next((t for t in list_templates() if t["id"] == cid
                and (not d.get("source") or t["source"] == d.get("source"))), None)
    if not tpl:
        return {"ok": False, "error": "舰船不存在: %s" % cid}
    size = tpl["size"]
    un = "units", "size_" + size      # src_base 已含 assets，不带 assets 前缀，避免 assets\assets 重复
    # 修改模式统一写回「该船所属 mod」（vanilla 已在下方拒绝）：
    # ship macro / storage / t 文本 / jobs / 建造成本 / 装配预设全部落在同一 mod，不再拆散到 target_mod
    mod = os.path.normpath(os.path.join(ROOT, "extensions", tpl["source"]))
    rel = lambda *p: os.path.join(mod, *p)
    modified = []
    # 被编辑舰船的实际生效来源目录（vanilla 或扩展）；修改即写回该处
    src_base = os.path.join(ROOT, "assets") if tpl["source"] == "vanilla" else os.path.join(ROOT, "extensions", tpl["source"], "assets")
    if tpl["source"] == "vanilla":
        return {"ok": False, "error": "不能直接修改原版舰船（会改动游戏本体文件）。请用「新增」模式基于它生成新舰船。"}
    if not os.path.isdir(src_base):
        return {"ok": False, "error": "来源目录不存在: %s（该 mod 未加载）" % src_base}
    bakdir = os.path.join(BACKUP_ROOT,
                          "bak_edit_%s" % time.strftime("%Y%m%d_%H%M%S"))
    os.makedirs(bakdir, exist_ok=True)
    def backup(p):
        if os.path.isfile(p):
            shutil.copy2(p, os.path.join(bakdir, os.path.basename(p)))

    # 1. ship macro：属性（宏文件名可能带变体后缀，用 _find_ship_macro 定位）
    mac_path = _find_ship_macro(os.path.join(src_base, *un), cid)
    if not os.path.isfile(mac_path):
        return {"ok": False, "error": "ship macro 缺失: %s" % mac_path}
    backup(mac_path)
    mtxt = apply_props(open(mac_path, encoding="utf-8").read(), d)
    if d.get("software"):
        mtxt = _apply_ship_software(mtxt, d["software"])
    # macro connections 模块：启用时用编辑行整块替换 connections（宏文件已备份）
    mc = d.get("macro_connections") or {}
    if mc.get("enabled"):
        m_st2 = re.search(r'<macro ref="(storage_[^"]+)"', mtxt)
        subst = {}
        if m_st2:
            subst["{STORAGE}"] = m_st2.group(1)
        m_da2 = re.search(r'<macro ref="(dockarea_[^"]+?_macro)"', mtxt)
        if m_da2:
            subst["{DOCKAREA}"] = m_da2.group(1)
        comp_names = [c["name"] for c in ship_component_connections(cid, tpl["source"])]
        mtxt2, mc_err = _apply_macro_connections(mtxt, mc.get("rows") or [], comp_names, subst)
        if mc_err:
            return {"ok": False, "error": "macro connections：" + mc_err}
        mtxt = mtxt2
    _err = _xml_check(mtxt)
    if _err:
        return {"ok": False, "error": "修改后的 macro XML 非法（多为文件原有坏标签），拒绝写入：%s" % _err}
    open(mac_path, "w", encoding="utf-8").write(mtxt)
    modified.append(os.path.relpath(mac_path, mod))

    # 2. storage macro：cargo / makerrace（从 ship macro connections 读实际 ref）
    stor_ref = None
    m2 = re.search(r'<macro ref="(storage_[^"]+)"', mtxt)
    if m2: stor_ref = m2.group(1)
    if stor_ref:
        st_path = os.path.join(src_base, *un, "macros", stor_ref + ".xml")
        if os.path.isfile(st_path):
            backup(st_path)
            stxt = open(st_path, encoding="utf-8").read()
            stxt = _storage_apply(stxt, d.get("cargo"), d.get("makerrace"))
            _err = _xml_check(stxt)
            if _err:
                return {"ok": False, "error": "修改后的 storage macro XML 非法，拒绝写入：%s" % _err}
            open(st_path, "w", encoding="utf-8").write(stxt)
            modified.append(os.path.relpath(st_path, mod))

    # 3. t 文本：更新已有 name/basename/description 条目（不新增、不改 id）
    if tpl["tids"] and tpl["tids"][0]:
        nid0, nid1, nid2 = tpl["tids"]
        name_zh = d.get("name_zh") or tpl.get("name_zh") or tpl.get("name") or cid.split("_")[-1].upper()
        name_en = d.get("name_en") or tpl.get("name_en") or tpl.get("name") or cid.split("_")[-1].upper()
        desc_zh = d.get("desc_zh") or tpl.get("desc_zh") or ("EVE舰船 %s" % name_zh)
        desc_en = d.get("desc_en") or tpl.get("desc_en") or ("EVE ship %s" % name_en)
        zh_p, en_p = _loc_files(os.path.dirname(src_base))
        for tp, n, desc in ((zh_p, name_zh, desc_zh), (en_p, name_en, desc_en)):
            if not tp: continue
            backup(tp)
            txt = open(tp, encoding="utf-8").read()
            for tid, text in ((nid0, n), (nid1, desc), (nid2, desc)):
                esc = (text.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;"))
                txt = re.sub(r'(<t id="%d">)[^<]*(</t>)' % tid,
                             lambda m: m.group(1) + esc + m.group(2), txt)
            open(tp, "w", encoding="utf-8").write(txt)
            modified.append(os.path.relpath(tp, mod))

    # 4. jobs：AI 派系主动使用（可选，修改模式也能补/更新）
    jobs_cfg = d.get("jobs") or {}
    if jobs_cfg.get("enabled") and tpl.get("tids") and tpl["tids"][0]:
        modified += write_jobs(mod, cid + "_macro", size, jobs_cfg, tpl["tids"][0])

    # 4.5 shipgroup：AI 调度候选分组（并入整船保存，可多分组）
    shipgroups_cfg = d.get("shipgroups") or {}
    if shipgroups_cfg.get("enabled") and (shipgroups_cfg.get("groups") or []):
        modified += shipgroup_save_all(mod, cid, shipgroups_cfg)

    # 5. 建造成本（wares.xml）：更新已有或追加
    if tpl.get("tids") and tpl["tids"][0]:
        rc = cid.split("_")[1]
        faction = RACE_FACTION.get(rc, "argon")
        wrel = write_ware(mod, cid, cid + "_macro", size, faction, d, tpl["tids"])
        if wrel:
            modified.append(wrel)

    # 6. 装配预设（loadout）：写入该船 ship macro 内联 default（默认/AI/船厂生成装配）
    modified += write_loadout(mod, cid + "_macro", d.get("loadout") or {}, size)

    # 7. 挂载点 tags：按连接点写回该船 component（可选，按组/逐槽指定 tags；改前备份）
    mtags = d.get("mount_tags") or []
    if mtags:
        comp_path = os.path.join(src_base, *un, cid + ".xml")
        if os.path.isfile(comp_path):
            backup(comp_path)
            ct = open(comp_path, encoding="utf-8", errors="ignore").read()
            nct, n = write_mount_tags(ct, mtags)
            if n:
                open(comp_path, "w", encoding="utf-8").write(nct)
                modified.append(os.path.relpath(comp_path, mod))

    # 8. 材质参数（material_library.xml）：改名=克隆副本并改写本船 component 引用；
    #    本 mod 材质就地改值，外部材质追加 diff replace（改前备份）
    mtune_warns = []
    mtune = d.get("material_tuning") or {}
    if mtune.get("enabled") and (mtune.get("values") or {}):
        mlp = rel("libraries", "material_library.xml")
        if os.path.isfile(mlp):
            backup(mlp)
        mrels, mtune_warns = apply_material_tuning(
            mod, mtune,
            comp_path=comp_path if os.path.isfile(comp_path) else None,
            comp_backup=backup,
            rename_mode="replace")   # 修改模式：就地重命名 + 全 mod 引用一并更新
        modified += mrels

    # 舰船列表图标别名（ship_<id>_macro → 同 race_size 原版贴图）
    _sal = _ship_icon_alias(mod, cid)
    if _sal:
        modified.append(_sal)
    moding = copy_to_moding(mod, modified)
    _refresh_soft()  # 舰船流不写装备/弹丸文件：轻量失效 t文本/wares索引/loadout/全局资产（免全量冷扫）
    return {"ok": True, "id": cid, "modified": modified, "moding": moding,
            "moding_base": os.path.join(mod, "moding"), "bakdir": bakdir,
            "warnings": jobs_skip_warn(d.get("jobs")) + mtune_warns}

def allocate_tids(d):
    """分配下一组 t id（name/basename/description）。
    扫描 mod 全部 XML 里 page 7777771 的引用 {7777771,N}，取最大+1，避免与 wares/macro 引用冲突。"""
    maxid = 700
    for root, _, files in os.walk(MOD_DIR):
        for fn in files:
            if fn.lower().endswith(".xml"):
                try:
                    txt = open(os.path.join(root, fn), encoding="utf-8").read()
                    for m in re.finditer(r"\{7777771,(\d+)\}", txt):
                        v = int(m.group(1))
                        if v > maxid:
                            maxid = v
                    for m in re.finditer(r'<t id="(\d+)"', txt):
                        v = int(m.group(1))
                        if v > maxid:
                            maxid = v
                except Exception:
                    pass
    return [maxid+1, maxid+2, maxid+3]

def write_jobs(mod, mac_name, size, jobs_cfg, name_tid):
    """为每艘船按「派系 × 任务」生成 jobs 条目，写入 mod/libraries/jobs.xml。
    启用且派系/任务选全时写入；未启用/未选全时清理该船已有 job（返回清理的文件或空）。"""
    factions = [f for f in (jobs_cfg.get("factions") or []) if f]
    tasks = jobs_cfg.get("tasks") or []
    jp = os.path.join(mod, "libraries", "jobs.xml")
    pfx = _job_prefix(mod)
    if not (jobs_cfg.get("enabled") and factions and tasks):
        # 关闭/清空时也清理该船旧 job 条目：否则取消 AI 使用后 jobs.xml 残留，
        # AI 仍按旧配额生成该船，且编辑回填读到旧条目造成「已启用」假象
        if os.path.isfile(jp):
            txt = open(jp, encoding="utf-8").read()
            # 兼容旧 up7_ 前缀与动态前缀，两种历史的条目都清
            new = re.sub(r'<job\s+id="(?:%s|up7)_%s_[^"]*"[^>]*>.*?</job>'
                         % (re.escape(pfx), re.escape(mac_name)), "", txt, flags=re.S)
            if new != txt:
                new = re.sub(r'[ \t]*\n\s*\n+', "\n", new)   # 清理删除后留下的空行（与启用路径同规则）
                open(jp, "w", encoding="utf-8").write(new)
                return [os.path.relpath(jp, mod)]
        return []
    order_map = {t["id"]: t["order"] for t in JOB_TASKS}
    sizename = "ship_%s" % size  # ship_l / ship_xl
    jobs_xml = ""
    for fac in factions:
        for task in tasks:
            order = order_map.get(task, "Patrol")
            jid = _job_jid(mac_name, fac, task, pfx)
            jobs_xml += ("\n" if jobs_xml else "") + (
                '\t\t<job id="%s" name="{7777771,%d}" startactive="true">\n'
                '\t\t\t<modifiers commandeerable="true"/>\n'
                '\t\t\t<orders>\n'
                '\t\t\t\t<order order="%s" default="true"><param name="range" value="class.zone"/></order>\n'
                '\t\t\t</orders>\n'
                '\t\t\t<category faction="%s" tags="[factionlogic, military]" size="%s"/>\n'
                '\t\t\t<quota galaxy="2" maxgalaxy="3"/>\n'
                '\t\t\t<location class="galaxy" macro="xu_ep2_universe_macro" faction="%s" '
                'relation="self" comparison="exact" matchextension="false"/>\n'
                '\t\t\t<environment buildatshipyard="true"/>\n'
                '\t\t\t<ship>\n'
                '\t\t\t\t<select faction="%s" tags="[military]" size="%s"/>\n'
                '\t\t\t\t<owner exact="%s" overridenpc="true"/>\n'
                '\t\t\t</ship>\n'
                '\t\t</job>') % (jid, name_tid, order, fac, sizename, fac, fac, sizename, fac)
    header = DIFF_HEADER + '\t<add sel="//jobs">\n'
    footer = '\n\t</add>\n</diff>'
    if os.path.isfile(jp):
        txt = open(jp, encoding="utf-8").read()
        # 去重：删除该船(mac_name)已有的旧 job 块，避免反复生成导致 jobs.xml 无谓膨胀。
        # 兼容旧 up7_ 前缀与动态前缀：旧条目清除后按新前缀重写，实现自动迁移。
        # 注意 job id 后还有 name 等属性，须用 [^>]*> 而非 >，否则匹配不到旧块（此前失效的根因）
        txt = re.sub(r'<job\s+id="(?:%s|up7)_%s_[^"]*"[^>]*>.*?</job>'
                     % (re.escape(pfx), re.escape(mac_name)), "", txt, flags=re.S)
        txt = re.sub(r'[ \t]*\n\s*\n+', "\n", txt)   # 清理删旧后留下的空行
        txt = re.sub(r'\n[ \t]{4,}(?=<job\b)', '\n\t\t', txt)   # 归位历史同行拼接/删旧残留的超长 tab 串（正常 2 tab 条目不受影响）
        i = txt.rfind("</add>")
        if i >= 0:
            txt = txt[:i].rstrip() + "\n" + jobs_xml + "\n\t" + txt[i:]
        else:
            txt = txt.rstrip() + "\n" + jobs_xml + "\n"
        open(jp, "w", encoding="utf-8").write(txt)
    else:
        os.makedirs(os.path.dirname(jp), exist_ok=True)
        open(jp, "w", encoding="utf-8").write(header + jobs_xml + footer)
    return [os.path.relpath(jp, mod)]

def ship_jobs(ship_id, source=None):
    """读该船所属 mod 现有 jobs.xml，返回该船（mac_name）已有的 AI 派系归属，
    供编辑模式回填 jobs 模块。jid 规则同 write_jobs：<mod前缀>_<mac_name>_<fac>_<task>，
    兼容历史 up7_ 前缀条目。source 指定且在该 id 来源链中时按该来源（[重复] 条目忠实读取），否则取胜者。"""
    for (size, cid), srcs in ship_sources_all().items():
        if cid != ship_id:
            continue
        src = source if (source and source in srcs) else srcs[-1]
        if src == "vanilla":
            break
        mod = os.path.join(ROOT, "extensions", src)
        jp = os.path.join(mod, "libraries", "jobs.xml")
        if not os.path.isfile(jp):
            break
        txt = open(jp, encoding="utf-8").read()
        mac = cid + "_macro"
        facs, tasks = set(), set()
        for m in re.finditer(r'<job\s+id="(?:%s|up7)_%s_([^"]*)"'
                             % (re.escape(_job_prefix(mod)), re.escape(mac)), txt):
            rest = m.group(1)                      # fac_task
            parts = rest.rsplit("_", 1)
            if len(parts) == 2 and parts[1] in _JOB_TASK_IDS:
                facs.add(parts[0]); tasks.add(parts[1])
        return {"ship": ship_id, "enabled": bool(facs and tasks), "factions": sorted(facs),
                "tasks": sorted(tasks), "exists": bool(facs)}
    return {"ship": ship_id, "enabled": False, "factions": [], "tasks": [], "exists": False}

def _shipgroups():
    """合并原版+各 mod shipgroups.xml 的视图 {group: {source, selects:[(macro,weight)]}}。
    后加载者覆盖同名 group（X4 文件级覆盖语义）。"""
    out = {}
    files = [("vanilla", os.path.join(ROOT, "libraries", "shipgroups.xml"))] +             [(m, os.path.join(ROOT, "extensions", m, "libraries", "shipgroups.xml")) for m in _ext_order()]
    for src, p in files:
        if not os.path.isfile(p):
            continue
        try:
            txt = open(p, encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        for m in re.finditer(r'<group\s+name="([^"]*)"[^>]*>(.*?)</group>', txt, re.S):
            body = m.group(2)
            sels = [(s.group(1), s.group(2)) for s in re.finditer(r'<select\s+macro="([^"]*)"\s+weight="([^"]*)"', body)]
            out[m.group(1)] = {"source": src, "selects": sels}
    return out

def ship_in_groups(ship_id):
    """该船当前所属的所有分组（合并视图）。匹配该船 macro，含 _a/_b 变体后缀。"""
    bases = {"%s_macro" % ship_id, "%s_a_macro" % ship_id, "%s_b_macro" % ship_id}
    out = []
    for gname, g in _shipgroups().items():
        for macro, weight in g["selects"]:
            if macro in bases:
                out.append({"group": gname, "source": g["source"], "weight": weight, "macro": macro})
    out.sort(key=lambda x: x["group"])
    return out

FAC_ZH = {"arg":"Argon","ter":"Terran","atf":"ATF","tel":"Teladi","par":"Paranid","holyorder":"圣教团",
           "trinity":"三位一体","split":"Split","freesplit":"自由部族联盟","bor":"Boron","xen":"Xenon","kha":"Kha'ak",
           "pir":"海盗","scaleplate":"鳞片公约组织","hatikvah":"希望之歌自由联盟","yaki":"Yaki","upi":"地球人(UPI)",
           "cov":"公民","player":"玩家","civilian":"平民","loan":"贷款","smuggler":"走私","scavenger":"拾荒",
           "buccaneer":"公爵的海盗","outlaw":"法外","ownerless":"无主","criminal":"犯罪","court":"王国"}
USAGE_ZH = {"builder":"建造","resupplier":"补给","trader_container":"货船","trader":"货船",
            "miner_solid":"采矿(固态)","miner_liquid":"采矿(液态)","miner":"采矿","battleship":"战列舰",
            "destroyer":"驱逐舰","carrier":"航母","police":"警察","scout":"侦察","interceptor":"拦截",
            "escort":"护航","military":"军事","transport":"运输","trader_generic":"通用货船",
            "stationbuilder":"空间站建造","miner_generic":"通用采矿","tourist":"观光","courier":"信使"}
SIZE_ZH = {"xl":"XL","l":"L","m":"M","s":"S"}
def _shipgroup_zh(name):
    """按 group 名结构（派系_用途_尺寸）拆解翻译，供下拉中文参考。未知词保留原文。"""
    szzh = ""
    base = name
    for sz in ("_xl","_l","_m","_s"):
        if name.endswith(sz):
            szzh = SIZE_ZH.get(sz[1:], sz[1:].upper())
            base = name[:len(name)-len(sz)]
            break
    fac = ""; usage = base
    for f in sorted(FAC_ZH, key=lambda x: -len(x)):
        if base.startswith(f + "_"):
            fac = FAC_ZH[f]
            usage = base[len(f)+1:]
            break
    usage_zh = " ".join(w for w in (USAGE_ZH.get(w, w) for w in usage.split("_")) if w)
    parts = [x for x in (fac, usage_zh, szzh) if x]
    return " ".join(parts) if parts else name

def shipgroup_all():
    """全部可用的分组（供加入时选择）。含中文翻译参考。"""
    return [{"name": n, "source": g["source"], "count": len(g["selects"]), "zh": _shipgroup_zh(n)}
            for n, g in sorted(_shipgroups().items())]

def shipgroup_save(d):
    """把当前船加入目标 mod 的 shipgroups.xml（diff 覆盖）。
    group 已存在(合并视图) → add select 到该 group；不存在 → 新建 group。返回修改文件列表。"""
    ship_id = (d.get("ship") or "").strip()
    group = (d.get("group") or "").strip()
    if not ship_id or not group:
        return {"ok": False, "error": "缺少船 id 或分组名"}
    weight = str(d.get("weight") or "").strip() or "100"
    mod = (d.get("target_mod") or MOD_DIR).strip()
    macro = "%s_macro" % ship_id
    existing = group in _shipgroups()
    if existing:
        block = '<select macro="%s" weight="%s"/>' % (macro, weight)
        entry = '\t<add sel="//groups/group[@name=\'%s\']">\n\t\t%s\n\t</add>' % (group, block)
    else:
        block = '<group name="%s">\n\t\t<select macro="%s" weight="%s"/>\n\t</group>' % (group, macro, weight)
        entry = '\t<add sel="//groups">\n\t\t%s\n\t</add>' % block
    header = DIFF_HEADER
    jp = os.path.join(mod, "libraries", "shipgroups.xml")
    if os.path.isfile(jp):
        txt = open(jp, encoding="utf-8").read()
        # 去重：移除该 mod 文件里所有含该船宏的旧 add 块（加入或新建均适用）
        for b in re.findall(r'<add\s+sel="//groups[^"]*"[^>]*>.*?</add>', txt, flags=re.S):
            if macro in b:
                txt = txt.replace(b, "")
        txt = re.sub(r'[ \t]*\n\s*\n+', "\n", txt)
        i = txt.rfind("</diff>")
        if i >= 0:
            txt = txt[:i] + entry + txt[i:]
        else:
            txt = txt.rstrip() + "\n" + entry + "\n"
        open(jp, "w", encoding="utf-8").write(txt)
    else:
        open(jp, "w", encoding="utf-8").write(header + entry + "\n</diff>")
    return {"ok": True, "modified": ["libraries\\shipgroups.xml"], "group": group, "macro": macro, "existing": existing}

def shipgroup_save_all(mod, ship_id, cfg):
    """批量：把 ship 加入 cfg 指定的多个分组（写入 mod/libraries/shipgroups.xml diff）。
    cfg={enabled, groups:[{group, weight}]}。返回修改文件相对路径列表。"""
    groups = cfg.get("groups") or []
    if not cfg.get("enabled") or not groups:
        return []
    ship_id = (ship_id or "").strip()
    if not ship_id:
        return []
    macro = "%s_macro" % ship_id
    allg = _shipgroups()
    entries = []
    for g in groups:
        group = (g.get("group") or "").strip()
        weight = str(g.get("weight") or "").strip() or "100"
        if not group:
            continue
        if group in allg:
            entries.append('\t<add sel="//groups/group[@name=\'%s\']">\n\t\t<select macro="%s" weight="%s"/>\n\t</add>'
                           % (group, macro, weight))
        else:
            entries.append('\t<add sel="//groups">\n\t\t<group name="%s">\n\t\t\t<select macro="%s" weight="%s"/>\n\t\t</group>\n\t</add>'
                           % (group, macro, weight))
    if not entries:
        return []
    body = "\n".join(entries)
    jp = os.path.join(mod, "libraries", "shipgroups.xml")
    if os.path.isfile(jp):
        txt = open(jp, encoding="utf-8").read()
        # 去重：移除该 mod 文件里所有含该船宏的旧 add 块
        for b in re.findall(r'<add\s+sel="//groups[^"]*"[^>]*>.*?</add>', txt, flags=re.S):
            if macro in b:
                txt = txt.replace(b, "")
        txt = re.sub(r'[ \t]*\n\s*\n+', "\n", txt)
        i = txt.rfind("</diff>")
        if i >= 0:
            txt = txt[:i] + body + "\n" + txt[i:]
        else:
            txt = txt.rstrip() + "\n" + body + "\n"
        open(jp, "w", encoding="utf-8").write(txt)
    else:
        header = DIFF_HEADER
        open(jp, "w", encoding="utf-8").write(header + body + "\n</diff>")
    return ["libraries\\shipgroups.xml"]

_LOADOUT_CACHE = None
_MACRO_REF_RE = re.compile(r'<component\s+ref="([^"]+)"')
_SIZE_WORDS = ("extralarge", "large", "medium", "small", "xs")
_COMPCACHE = {}
def _read_macro_ref(macfile):
    """从装备 macro 读它引用的 component id（结构规则：<component ref>）。"""
    m = _MACRO_REF_RE.search(open(macfile, encoding="utf-8").read())
    return m.group(1) if m else None
_GLOBAL_ASSETS = None
_GCOMPCACHE = {}
def _global_assets_roots():
    """所有资产树的根：原版 assets + 每个扩展的 assets（跨源组件查找用）。"""
    global _GLOBAL_ASSETS
    if _GLOBAL_ASSETS is None:
        roots = [os.path.join(ROOT, "assets")]
        ext = os.path.join(ROOT, "extensions")
        if os.path.isdir(ext):
            for d in sorted(os.listdir(ext)):
                p = os.path.join(ext, d, "assets")
                if os.path.isdir(p):
                    roots.append(p)
        _GLOBAL_ASSETS = roots
    return _GLOBAL_ASSETS

_DIR_INDEX = {}   # base -> {文件名: 完整路径} 索引；仅映射文件名→路径（内容无关），服务生命周期内每树只 os.walk 一次
def _dir_index(base):
    """资产树文件名索引：懒构建一次（os.walk 全树），之后 O(1) 查找。
    此前每个未命中 ref 都全盘 os.walk，原版 assets 数十万文件时单次即达数十秒~分钟级；
    建索引后首次构建一次，后续组件定位毫秒级。"""
    idx = _DIR_INDEX.get(base)
    if idx is None:
        idx = {}
        for r, _, fs in os.walk(base):
            for f in fs:
                idx.setdefault(f, os.path.join(r, f))   # 保留 walk 序首个命中，兼容原逐子树兜底语义
        _DIR_INDEX[base] = idx
    return idx

def _find_comp_global(ref):
    """全资产树查找组件 ref.xml（mod 宏引用原版/其他 mod 组件时本地找不到）。
    走 _dir_index 索引（不再逐 ref 全盘 os.walk）；isfile 校验防文件删除后索引指向僵尸路径。"""
    if ref in _GCOMPCACHE:
        return _GCOMPCACHE[ref]
    found = None
    fn = ref + ".xml"
    for base in _global_assets_roots():
        p = _dir_index(base).get(fn)
        if p and os.path.isfile(p):
            found = p
            break
    _GCOMPCACHE[ref] = found
    return found

def _equip_component(macfile, ref):
    """定位装备 component 文件：X4 惯例 component 在 macro 目录的上级（同 <类> 目录）。"""
    key = macfile + "|" + ref
    if key in _COMPCACHE:
        return _COMPCACHE[key]
    mac_dir = os.path.dirname(macfile)
    cand = os.path.join(os.path.dirname(mac_dir), ref + ".xml")
    if not os.path.isfile(cand):
        sub = os.path.dirname(mac_dir)           # 宏目录上级（同类目录）子树索引：一次构建，N 个宏共用
        idx = _dir_index(sub) if os.path.isdir(sub) else {}
        p = idx.get(ref + ".xml")
        cand = p if p and os.path.isfile(p) else None
    cand = cand if cand and os.path.isfile(cand) else None
    if cand is None:
        cand = _find_comp_global(ref)
    _COMPCACHE[key] = cand
    return cand
def _ref_source(ref):
    # ref 物品(component ref)来源 mod：从组件文件路径推。原版基础返回 vanilla。
    comp = _find_comp_global(ref)
    if not comp:
        return ""
    norm = comp.replace("/", "\\")
    m = re.search(r"\\extensions\\([^\\\\]+)\\\\", norm)
    return m.group(1) if m else "vanilla"

def _source_from_path(path):
    # 从组件文件路径推来源 mod；原版基础 assets 返回 vanilla。
    norm = path.replace("/", "\\")
    m = re.search(r"\\extensions\\([^\\]+)\\", norm)
    return m.group(1) if m else "vanilla"

def _ref_comp_source(comp, ref):
    # 引用模型组件来源：本地 comp 优先，本地缺时全资产树兜底（与引用链/几何一致）
    p = comp or (_find_comp_global(ref) if ref else None)
    return _source_from_path(p) if p else ""


def _read_comp_txt(comp):
    """读组件文件文本；若为 <diff> 补丁格式（如 vro 覆盖原版装备），应用补丁到被覆盖的
    base 组件后返回合并文本（与游戏加载语义一致）。找不到 base 时返回 diff 原文保底。"""
    txt = open(comp, encoding="utf-8", errors="ignore").read()
    if _is_diff_txt(txt):
        applied = _apply_diff_to_base(comp, txt)
        if applied:
            return applied
    return txt

def _comp_source_geometry(comp):
    """从组件文件读 <source geometry="..._data"/>，返回原文（游戏内 assets 相对路径），无则空。"""
    try:
        t = _read_comp_txt(comp)
    except Exception:
        return ""
    m = re.search(r'<source\s+geometry="([^"]+)"', t)
    return m.group(1) if m else ""

def _comp_geometry_id(comp):
    """从组件 <source geometry> 解析真实几何 id：去掉 _data 后缀、取路径最后一段。
    例 assets\\props\\...\\turret_arg_l_beam_01_mk1_data -> turret_arg_l_beam_01_mk1"""
    g = _comp_source_geometry(comp)
    if not g:
        return ""
    if g.endswith("_data"):
        g = g[:-len("_data")]
    g = g.split("\\")[-1]
    return g

def _comp_tags_sizes(comp, type_words):
    """读装备 component，只统计含类型词(engine/shield/turret/weapon)的 connection tags，
    返回 (尺寸集合, 类型词集合)。尺寸(tags)：large/extralarge/medium/small。"""
    txt = _read_comp_txt(comp)
    sizes, types = set(), set()
    for m in re.finditer(r'<connection\b([^>]*)>', txt):
        tm = re.search(r'tags="([^"]*)"', m.group(1))
        if not tm:
            continue
        ts = tm.group(1).split()
        hit = [t for t in type_words if t in ts]
        if not hit:
            continue
        types.update(hit)
        for s in _SIZE_WORDS:
            if s in ts:
                sizes.add(s)
    return sizes, types

def _mount_conn(comp, type_words):
    """读装备 component，返回其「挂载匹配连接」的 (name, tags)。该连接 tags 含类型词
    (engine/shield/turret/weapon/missile)，用于与船槽 connection tags 匹配（装备 tags ⊆ 槽 tags 可装）。
    找不到返回 (None, "")。"""
    try:
        ctxt = _read_comp_txt(comp)
    except Exception:
        return None, ""
    for m in re.finditer(r'<connection\b([^>]*)>', ctxt):
        tm = re.search(r'tags="([^"]*)"', m.group(1))
        if not tm:
            continue
        ts = tm.group(1).split()
        if any(t in ts for t in type_words):
            nm = re.search(r'name="([^"]*)"', m.group(1))
            return (nm.group(1) if nm else "?"), tm.group(1).strip()
    return None, ""

def _set_mount_tags(ctxt, tags, conn_name=""):
    """把组件里「挂载匹配连接」的 tags 替换为给定 tags。优先按 conn_name 精确定位；
    否则替换第一个含类型词的连接。tags 为空时原样返回。"""
    if not tags:
        return ctxt
    if conn_name:
        pat = re.compile(r'(<connection\s+name="%s"[^>]*?tags=")[^"]*(")' % re.escape(conn_name), re.S)
        m = pat.search(ctxt)
        if m:
            return ctxt[:m.start()] + m.group(1) + tags + m.group(2) + ctxt[m.end():]
    for m in re.finditer(r'<connection\b[^>]*>', ctxt):
        tm = re.search(r'tags="([^"]*)"', m.group(0))
        if tm and re.search(r'\b(turret|weapon|shield|missile|engine|missileturret)\b', tm.group(0)):
            seg = ctxt[m.start():m.end()]
            seg = seg.replace(tm.group(0), 'tags="%s"' % tags)
            return ctxt[:m.start()] + seg + ctxt[m.end():]
    return ctxt

def write_mount_tags(ctxt, items):
    """把舰船 component 里指定 connection 的 tags 设置为给定值（按挂载点 name 精确定位）。
    items=[{name, tags}]；tags 为空则删除该 connection 的 tags 属性。返回 (新文本, 变更数)。"""
    n = 0
    for it in items or []:
        name = (it.get("name") or "").strip()
        tags = (it.get("tags") or "").strip()
        if not name:
            continue
        pat = re.compile(r'<connection\s+name="%s"[^>]*>' % re.escape(name))
        m = pat.search(ctxt)
        if not m:
            continue
        seg = m.group(0)
        if tags:
            if re.search(r'\btags="[^"]*"', seg):
                newseg = re.sub(r'\btags="[^"]*"', 'tags="%s"' % tags, seg, count=1)
            else:
                newseg = seg[:-1] + ' tags="%s"' % tags + '>'
        else:
            if not re.search(r'\btags="[^"]*"', seg):
                continue
            newseg = re.sub(r'\btags="[^"]*"', '', seg, count=1)
        if newseg != seg:
            ctxt = ctxt[:m.start()] + newseg + ctxt[m.end():]
            n += 1
    return ctxt, n

_SOFTWARE_CACHE = None
def _software_inputs():
    """软件清单输入：原版 + 各来源的 wares.xml（签名校验用）。"""
    return [os.path.join(ROOT, "libraries", "wares.xml")] + \
           [os.path.join(ROOT, "extensions", m, "libraries", "wares.xml") for m in _ext_order()]

def _build_software_list():
    """汇总所有源（原版 wares + 各 mod wares）的 software_* 软件列表 [{id,name}]，含中文名。"""
    seen, out = {}, []
    vanilla_p = os.path.join(ROOT, "libraries", "wares.xml")
    def add(sid, name_ref, src):
        if sid in seen:
            return
        seen[sid] = 1
        out.append({"id": sid, "name": LX.ref_text(name_ref, "zh") if name_ref else (_zh_id(sid) + "[译]"), "source": src})
    roots = [vanilla_p] +             [os.path.join(ROOT, "extensions", m, "libraries", "wares.xml") for m in _ext_order()]
    for wp in roots:
        if not os.path.isfile(wp):
            continue
        t = open(wp, encoding="utf-8", errors="ignore").read()
        src = "vanilla" if wp == vanilla_p else os.path.basename(os.path.dirname(os.path.dirname(wp)))
        for w in re.finditer(r'<ware id="(software_[^"]+)"[^>]*>(.*?)</ware>', t, re.S):
            nm = re.search(r'name="(\{[^"]*\})"', w.group(0))
            add(w.group(1), nm.group(1) if nm else "", src)
    return sorted(out, key=lambda x: x["name"] or x["id"])

def _software_list():
    """软件选项卡数据源：内存 + 磁盘双层缓存（wares.xml 签名校验）。"""
    global _SOFTWARE_CACHE
    if _SOFTWARE_CACHE is None:
        _SOFTWARE_CACHE = _cached_whole("software.json", _software_inputs(), _build_software_list)
    return _SOFTWARE_CACHE

def _ship_software(mtxt):
    """读舰船宏 <software> 节点 → [{ware, default(bool)}]。无节点返回 []。"""
    out = []
    m = re.search(r'<software>.*?</software>', mtxt, re.S)
    if m:
        for s in re.finditer(r'<software\s+ware="([^"]+)"([^>]*)/>', m.group(0)):
            a = s.group(2)
            d = re.search(r'default="([^"]+)"', a)
            out.append({"ware": s.group(1), "default": bool(d and d.group(1) not in ("", "0"))})
    return out

def _apply_ship_software(mtxt, items):
    """替换/插入舰船 macro 的 <software> 节点。items=[{ware, default}]；空列表且节点存在则移除。"""
    if not items:
        return re.sub(r'\s*<software>.*?</software>', '', mtxt, count=1, flags=re.S)
    inner = "".join('\n        <software ware="%s" %s/>' % (
        it["ware"], 'default="1"' if it.get("default") else 'compatible="1"') for it in items)
    newblock = '<software>%s\n      </software>' % inner
    if re.search(r'<software>.*?</software>', mtxt, re.S):
        return re.sub(r'<software>.*?</software>', lambda m: newblock, mtxt, count=1, flags=re.S)
    return re.sub(r'</properties>', newblock + '\n    </properties>', mtxt, count=1)

def loadout_macros():
    """装配预设推进器（thruster）可选宏列表。engine/shield/turret/weapon 已改由前端复用
    /api/equiptemplates（与装备选项卡同源同款 eqOpt 渲染，含 [重复] 来源单列；按 L/XL
    适用尺寸过滤、引擎排除推进器类虚拟宏），本接口仅保留 equip_scan 未覆盖的推进器扫描：
    递归 props 下 thruster_gen_* 宏（不限于 Engines\\macros，mod 位置可能不同）。
    模拟加载：原版在前，mod 后加载，同名宏去重（后覆盖先）。"""
    global _LOADOUT_CACHE
    if _LOADOUT_CACHE is not None:
        return _LOADOUT_CACHE
    props_roots = [os.path.normpath(os.path.join(ROOT, "assets", "props"))] + \
                  [os.path.normpath(os.path.join(ROOT, "extensions", m, "assets", "props")) for m in _ext_order()]
    def hid(f):
        return f[:-len("_macro.xml")] if f.endswith("_macro.xml") else f[:-len(".xml")]
    seen = {}
    for props in props_roots:
        if os.path.isdir(props):
            for root, _, files in os.walk(props):
                for f in sorted(files):
                    if f.startswith("thruster_gen_") and f.endswith("_macro.xml") and "_video" not in f:
                        seen[hid(f)] = os.path.join(root, f)
    _LOADOUT_CACHE = {"thruster": [{"id": i, "name": LX.macro_display(p, i, "zh")} for i, p in sorted(seen.items())]}
    return _LOADOUT_CACHE

def component_slots(ship_id, source=None):
    """读某舰船 component 文件，返回装备连接点（按 engine/shield/turret/weapon 分类）+ 连接组列表。
    分组信息就在 connection 的 group 属性里（原样读出去重）；装备类型由 tags 区分。
    source 指定且在该 id 来源链中时按该来源（[重复] 条目忠实读取），否则取胜者。"""
    for (size, cid), srcs in ship_sources_all().items():
        if cid != ship_id:
            continue
        src = source if (source and source in srcs) else srcs[-1]
        base = os.path.join(ROOT, "assets", "units") if src == "vanilla" else os.path.join(ROOT, "extensions", src, "assets", "units")
        comp = os.path.join(base, "size_%s" % size, cid + ".xml")
        if not os.path.isfile(comp):
            return {"ship": ship_id, "connections": {"engine": [], "shield": [], "turret": [], "weapon": []}, "groups": []}
        txt = _read_ship_comp_txt(comp, size, cid, src)   # diff 补丁自动合并 base（游戏加载语义）
        cons = {"engine": [], "shield": [], "turret": [], "weapon": []}
        groups = []
        for m in re.finditer(r"<connection\b([^>]*)>", txt):
            attrs = m.group(1)
            nm = re.search(r'name="([^"]+)"', attrs)
            if not nm:
                continue
            name = nm.group(1)
            tm = re.search(r'tags="([^"]*)"', attrs)
            tagset = tm.group(1) if tm else ""
            gm = re.search(r'group="([^"]*)"', attrs)
            grp = ""
            if gm:
                for g in gm.group(1).split():
                    g = g.strip()
                    if g:
                        if g not in groups:
                            groups.append(g)
                        if not grp:
                            grp = g
            for kind in cons:
                if kind in tagset:
                    cons[kind].append({"name": name, "group": grp, "tags": tagset})
        for k in cons:
            cons[k] = sorted(cons[k], key=lambda x: x["name"])
        return {"ship": ship_id, "connections": cons, "groups": groups}
    return {"ship": ship_id, "connections": {"engine": [], "shield": [], "turret": [], "weapon": []}, "groups": []}

def _ld_attrs(attrs):
    """从 loadout 单个装备元素属性串提取 macro/path/optional。"""
    def g(k):
        m = re.search(k + r'="([^"]*)"', attrs)
        return m.group(1) if m else ""
    return {"macro": g("macro"), "path": g("path"), "optional": (g("optional") in ("1", "true", "True"))}

def ship_loadout(ship_id, source=None):
    """读舰船 ship macro 的默认装配 loadout，返回结构化条目。
    has_loadout=False 表示 macro 无 loadout（需从 component 全量挂载填充）。
    source 指定且在该 id 来源链中时按该来源（[重复] 条目忠实读取），否则取胜者。"""
    for (size, cid), srcs in ship_sources_all().items():
        if cid != ship_id:
            continue
        src = source if (source and source in srcs) else srcs[-1]
        base = os.path.join(ROOT, "assets", "units") if src == "vanilla" else os.path.join(ROOT, "extensions", src, "assets", "units")
        d = os.path.join(base, "size_%s" % size)
        mac = _find_ship_macro(d, cid)
        if not os.path.isfile(mac):
            _mg = _find_ship_macro_global(size, cid)   # 同 list_templates：无自有宏回退宏覆盖链
            if _mg:
                mac = _mg
        if not os.path.isfile(mac):
            return {"ship": ship_id, "has_loadout": False, "loadout": None}
        txt = open(mac, encoding="utf-8").read()
        m = re.search(r'<loadout\b[^>]*>(.*?)</loadout>', txt, re.S)
        if not m:
            return {"ship": ship_id, "has_loadout": False, "loadout": None}
        block = m.group(1)
        ld = {"engine": None, "shields": [], "weapons": [], "turrets": [], "thruster": None}
        e = re.search(r'<engine\b([^>]*?)/>', block)
        if e:
            ld["engine"] = _ld_attrs(e.group(1))
        for s in re.finditer(r'<shield\b([^>]*?)/>', block):
            ld["shields"].append(_ld_attrs(s.group(1)))
        for w in re.finditer(r'<weapon\b([^>]*?)/>', block):
            ld["weapons"].append(_ld_attrs(w.group(1)))
        for t in re.finditer(r'<turret\b([^>]*?)/>', block):
            a = _ld_attrs(t.group(1)); a["mode"] = "slot"; ld["turrets"].append(a)
        for t in re.finditer(r'<turrets\b([^>]*?)/>', block):
            a = _ld_attrs(t.group(1)); a["mode"] = "group"
            g2 = re.search(r'group="([^"]*)"', t.group(1)); ex = re.search(r'exact="([^"]*)"', t.group(1))
            a["group"] = g2.group(1) if g2 else ""
            a["exact"] = ex.group(1) if ex else "1"
            ld["turrets"].append(a)
        th = re.search(r'<thruster\b([^>]*?)/>', block)
        if th:
            ld["thruster"] = _ld_attrs(th.group(1))
        has = bool(ld["engine"] or ld["shields"] or ld["weapons"] or ld["turrets"] or ld["thruster"])
        return {"ship": ship_id, "has_loadout": has, "loadout": ld}
    return {"ship": ship_id, "has_loadout": False, "loadout": None}

def ship_connections_detail(ship_id, source=None):
    """读舰船组件 XML 的全部连接点（name/tags/group，Blender 导出基础依据）与 ship macro
    的 <connections> 块（对组件连接点的加工：ref 引用 + 内挂 macro）。
    返回 {ship, component:[{name,tags,group}], macro:[{ref,macro,connection}], macro_file}。
    macro ref 指向组件中不存在的连接点 = 悬空引用（游戏静默忽略，功能失效），前端标红提示。"""
    for (size, cid), srcs in ship_sources_all().items():
        if cid != ship_id:
            continue
        src = source if (source and source in srcs) else srcs[-1]
        base = os.path.join(ROOT, "assets", "units") if src == "vanilla" else os.path.join(ROOT, "extensions", src, "assets", "units")
        comp = os.path.join(base, "size_%s" % size, cid + ".xml")
        macro = []
        mac_path = ""
        if os.path.isfile(comp):
            txt = _read_ship_comp_txt(comp, size, cid, src)
            mac = _find_ship_macro(os.path.join(base, "size_%s" % size), cid)
            if not os.path.isfile(mac):
                _mg = _find_ship_macro_global(size, cid)
                if _mg:
                    mac = _mg
            if os.path.isfile(mac):
                mac_path = mac
                mtxt = open(mac, encoding="utf-8", errors="ignore").read()
                mb = re.search(r'<connections\b[^>]*>(.*?)</connections>', mtxt, re.S)
                if mb:
                    for cm in re.finditer(r'<connection\b([^>]*)>(.*?)</connection>|<connection\b([^>]*)/>', mb.group(1), re.S):
                        if cm.group(3) is not None:      # 自闭合：<connection ref="X"/>
                            rf = re.search(r'ref="([^"]*)"', cm.group(3))
                            if rf:
                                macro.append({"ref": rf.group(1), "macro": "", "connection": ""})
                            continue
                        attrs, inner = cm.group(1), cm.group(2)
                        rf = re.search(r'ref="([^"]*)"', attrs)
                        if not rf:
                            continue
                        row = {"ref": rf.group(1), "macro": "", "connection": ""}
                        mm = re.search(r'<macro\s+ref="([^"]*)"(?:\s+connection="([^"]*)")?', inner)
                        if mm:
                            row["macro"] = mm.group(1)
                            row["connection"] = mm.group(2) or ""
                        if row["macro"]:
                            # 入口合法性（valid）+ 原版建议值（suggest）：前端据此标红/自动补全
                            row["valid"], row["suggest"] = _macro_entry_info(row["macro"])
                        macro.append(row)
        return {"ship": ship_id, "component": ship_component_connections(ship_id, src), "macro": macro, "macro_file": mac_path, "catalog": macro_catalog()}
    return {"ship": ship_id, "component": [], "macro": [], "macro_file": "", "catalog": macro_catalog()}

def ship_component_connections(ship_id, source=None):
    """组件 XML 全部连接点（供 macro connections 校验/下拉）。返回 [{name,tags,group}]。"""
    for (size, cid), srcs in ship_sources_all().items():
        if cid != ship_id:
            continue
        src = source if (source and source in srcs) else srcs[-1]
        base = os.path.join(ROOT, "assets", "units") if src == "vanilla" else os.path.join(ROOT, "extensions", src, "assets", "units")
        comp = os.path.join(base, "size_%s" % size, cid + ".xml")
        if not os.path.isfile(comp):
            return []
        txt = _read_ship_comp_txt(comp, size, cid, src)
        out = []
        for m in re.finditer(r"<connection\b([^>]*?)/?>", txt):
            attrs = m.group(1)
            nm = re.search(r'\bname="([^"]+)"', attrs)
            if not nm:
                continue
            tm = re.search(r'tags="([^"]*)"', attrs)
            gm = re.search(r'group="([^"]*)"', attrs)
            out.append({"name": nm.group(1), "tags": (tm.group(1) if tm else "").strip(),
                        "group": gm.group(1) if gm else ""})
        return out
    return []

_MACRO_CATALOG = None
_MC_PREFIXES = ["dockarea_", "dock_", "bridge_", "launchtube_", "shipstorage_", "buildmodule_", "storage_"]

def _build_macro_catalog():
    """构建全游戏挂载类宏清单（扫原版 + 全部扩展 assets/**/macros/）。"""
    def _classify(n):
        for p in _MC_PREFIXES:
            if n.startswith(p):
                return p
        return None
    roots = [os.path.join(ROOT, "assets")]
    ext_root = os.path.join(ROOT, "extensions")
    if os.path.isdir(ext_root):
        for d in sorted(os.listdir(ext_root)):
            p = os.path.join(ext_root, d, "assets")
            if os.path.isdir(p):
                roots.append(p)
    files = []
    observed = {}      # 内挂宏 ref → {入口 connection: 出现次数}（原版/DLC/扩展舰船宏里的实际挂法）
    for r in roots:
        if not os.path.isdir(r):
            continue
        for base, _, fs in os.walk(r):
            if os.path.basename(base) != "macros":
                continue
            for f in fs:
                if not f.lower().endswith(".xml"):
                    continue
                n = f[:-4]
                if _classify(n):
                    files.append((n, os.path.join(base, f)))
                elif n.startswith("ship_"):
                    # 舰船宏：记录它把各挂载宏挂在哪个入口 connection（⑧-1 合法性判据与建议值来源）
                    try:
                        stxt = open(os.path.join(base, f), encoding="utf-8", errors="ignore").read()
                    except OSError:
                        continue
                    for mm in re.finditer(r'<macro\b([^>]*?)/?>', stxt):
                        a = mm.group(1)
                        rm = re.search(r'\bref="([^"]+)"', a)
                        if not rm or not _classify(rm.group(1)):
                            continue
                        cmm = re.search(r'\bconnection="([^"]+)"', a)
                        if not cmm:
                            continue
                        d = observed.setdefault(rm.group(1), {})
                        d[cmm.group(1)] = d.get(cmm.group(1), 0) + 1
    cat = {p: [] for p in _MC_PREFIXES}
    seen = set()
    for n, fp in files:
        if n in seen:
            continue
        seen.add(n)
        try:
            txt = open(fp, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        conns = list(dict.fromkeys(re.findall(r'<connection\b[^>]*\bname="([^"]+)"', txt)))
        if not conns:
            # 宏无自有 connections（如 bridge 类）：入口连接定义在其 component 文件里（宏文件同级的上一级目录）
            cm = re.search(r'<component\s+ref="([^"]+)"', txt)
            if cm:
                cfp = os.path.normpath(os.path.join(os.path.dirname(fp), "..", cm.group(1) + ".xml"))
                if os.path.isfile(cfp):
                    try:
                        ctxt = open(cfp, encoding="utf-8", errors="ignore").read()
                        # 白名单过滤：component 回退只留有语义的入口候选（con_* 功能点 / ShipConnection / ConnectionNN / object），
                        # 排除 ConnectionFor*（LOD/动画/贴花）、space/position/container 等几何噪音
                        conns = [c for c in dict.fromkeys(re.findall(r'<connection\b[^>]*\bname="([^"]+)"', ctxt))
                                 if c.startswith("con_") or c in ("ShipConnection", "object") or re.match(r"^Connection\d+$", c)]
                    except OSError:
                        pass
        cat[_classify(n)].append({"name": n, "conns": conns})
    for p in _MC_PREFIXES:
        for e in cat[p]:
            o = observed.get(e["name"])
            # 原版实测挂法：按出现次数降序（最常用入口在前，作为建议值）
            e["obs"] = sorted(o, key=lambda k: (-o[k], k)) if o else []
        cat[p].sort(key=lambda x: x["name"])
    return cat

def macro_catalog():
    """全游戏挂载类宏清单（⑧-1 macro 连接点下拉数据源）。
    返回 {前缀: [{name, conns:[...]}]}；内存 + 磁盘双层缓存，签名只覆盖各来源的
    assets/**/macros/（扫描输入），输入未变时启动零读取。_refresh_soft 失效。"""
    global _MACRO_CATALOG
    if _MACRO_CATALOG is None:
        _MACRO_CATALOG = _cached_whole("macro_catalog.json", _assets_roots(),
                                       _build_macro_catalog, only_dirs={"macros"})
    return _MACRO_CATALOG

def _macro_entry_info(name):
    """内挂宏的合法入口 connection 集合与建议值（⑧-1 connection 合法性判据）。
    判据来源：① 该宏自身 / 其 component 的连接点（catalog conns）；② 原版/DLC/扩展舰船宏里的实际挂法（obs）。
    经验：boron bridge 入口是 con_cockpit_01 而 argon 是 con_cockpit——同族不同名，必须按宏实测，不能凭惯例猜。
    返回 (valid 列表, 建议值)；两者皆空 = 无法判定，调用方应跳过校验。"""
    own, obs = [], []
    cat = macro_catalog()
    for p in _MC_PREFIXES:
        e = next((x for x in cat[p] if x["name"] == name), None)
        if e:
            own, obs = e.get("conns") or [], e.get("obs") or []
            break
    return list(dict.fromkeys(list(own) + list(obs))), (obs[0] if obs else "")

def _apply_macro_connections(mtxt, rows, comp_names, subst=None):
    """用编辑行整块替换 ship macro 的 <connections>...</connections> 块。
    rows=[{ref,macro,connection}]：macro 空 = 纯转发 <connection ref="X"/>；非空 = 挂载宏。
    comp_names=组件连接名集合，ref 不在其中 → (None, 错误) 拒绝（悬空引用游戏会静默忽略）。
    subst=占位符表（{STORAGE}/{DOCKAREA} → 生成流程实际宏名），对 ref/macro/connection 三处生效。
    返回 (新文本, None) 或 (None, 错误信息)；文本无 connections 块时在 </macro> 前插入。"""
    subst = subst or {}
    valid = set(comp_names or [])
    seen, rendered, bad = set(), [], []
    for r in (rows or []):
        ref = subst.get((r.get("ref") or "").strip(), (r.get("ref") or "").strip())
        if not ref or ref in seen:
            continue
        seen.add(ref)
        if valid and ref not in valid:
            bad.append(ref)
            continue
        mac = (r.get("macro") or "").strip()
        conn = (r.get("connection") or "").strip()
        for k, v in subst.items():
            mac = mac.replace(k, v)
            conn = conn.replace(k, v)
        if mac and not conn:
            return None, "连接点 %s：内挂宏 %s 缺少入口 connection（该宏从哪个 connection 进入）" % (ref, mac)
        if mac and conn:
            # 入口 connection 合法性：必须是该宏实测存在的入口（原版挂法 / 自身 component 连接点）
            _valid, _sug = _macro_entry_info(mac)
            if _valid and conn not in _valid:
                return None, ("连接点 %s：内挂宏 %s 的入口 connection \"%s\" 不存在——游戏会静默忽略该挂载，功能失效（如缺驾驶舱→不能指派船长/不能操作）。\n"
                              "该宏的合法入口：%s%s" % (ref, mac, conn, "、".join(_valid),
                              ("（建议 %s）" % _sug) if _sug else ""))
        if mac:
            rendered.append('\t\t\t<connection ref="%s">\n\t\t\t\t<macro ref="%s" connection="%s"/>\n\t\t\t</connection>' % (ref, mac, conn))
        else:
            rendered.append('\t\t\t<connection ref="%s"/>' % ref)
    if bad:
        return None, "以下连接点在本船组件（component）中不存在（悬空引用，游戏会静默忽略）：\n· " + "\n· ".join(bad)
    block = "<connections>\n" + ("\n".join(rendered) + "\n\t\t" if rendered else "") + "</connections>"
    if re.search(r'<connections\b[^>]*>.*?</connections>', mtxt, re.S):
        return re.sub(r'<connections\b[^>]*>.*?</connections>', lambda _: block, mtxt, count=1, flags=re.S), None
    i = mtxt.rfind("</macro>")
    if i < 0:
        return None, "macro 文件结构异常（找不到 </macro>）"
    return mtxt[:i] + "\t\t" + block + "\n" + mtxt[i:], None

def write_loadout(mod, mac_name, ld, size):
    """按装配预设生成 loadout，写入该船 ship macro 内联 <loadout id="default">
    （官方默认/AI/船厂生成装配机制；全局 loadouts.xml 仅被 MD ref 引用，不参与默认生成）。
    返回修改文件相对路径列表；未启用/无装备/找不到该船 macro 则返回空。"""
    engines = ld.get("engines") or (([{"macro": ld["engine"], "path": ld.get("engine_path"), "optional": False}]) if ld.get("engine") else [])
    ship_mac = os.path.join(mod, "assets", "units", "size_" + str(size), "macros", mac_name + ".xml")
    if not os.path.isfile(ship_mac):
        return []
    if not ld.get("enabled"):
        return []
    def cv(v): return (v or "").strip()
    # 只有实际选择了装备 macro 才算有装配（勾选启用时自动从 component 填充的挂载条目未选装备，不算）
    has_gear = (any(cv(e.get("macro")) for e in engines)
                or any(cv(x.get("macro")) for x in (ld.get("shields") or []))
                or any(cv(x.get("macro")) for x in (ld.get("turrets") or []))
                or any(cv(x.get("macro")) for x in (ld.get("weapons") or [])))
    if not has_gear:
        # 勾选启用 + 装备全留空 → 清空该船已有 default 预设（空 loadouts 块一并删）
        txt = open(ship_mac, encoding="utf-8").read()
        if '<loadout id="default">' not in txt:
            return []
        txt = re.sub(r'\s*<loadout id="default">.*?</loadout>', '', txt, count=1, flags=re.S)
        txt = re.sub(r'\s*<loadouts>\s*</loadouts>', '', txt, flags=re.S)
        open(ship_mac, "w", encoding="utf-8").write(txt)
        return [os.path.relpath(ship_mac, mod)]
    macros = []
    def mrow(tag, macro, path, opt):
        o = ' optional="1"' if opt else ""
        macros.append('\t\t\t\t\t<%s macro="%s" path="../%s"%s/>' % (tag, cv(macro), cv(path), o))
    for e in engines:
        if cv(e.get("macro")): mrow("engine", e["macro"], e.get("path") or "con_engine_01", e.get("optional"))
    # 护盾：有组 → 组批量 <shields group exact>（同组统一一种装备）；无组 → 逐插槽 <shield path>
    for s in ld.get("shields") or []:
        if not cv(s.get("macro")): continue
        if cv(s.get("group")):
            o = ' optional="1"' if s.get("optional") else ""
            macros.append('\t\t\t\t\t<shields macro="%s" path=".." group="%s" exact="%s"%s/>'
                          % (cv(s["macro"]), cv(s["group"]), cv(s.get("count")) or "1", o))
        else:
            mrow("shield", s["macro"], s.get("path") or "con_shield_01", s.get("optional"))
    # 炮台：有组 → 组批量 <turrets group exact>；无组 → 逐插槽 <turret path>
    for t in ld.get("turrets") or []:
        if not cv(t.get("macro")): continue
        if cv(t.get("group")):
            o = ' optional="1"' if t.get("optional") else ""
            macros.append('\t\t\t\t\t<turrets macro="%s" path=".." group="%s" exact="%s"%s/>'
                          % (cv(t["macro"]), cv(t["group"]), cv(t.get("count")) or "1", o))
        else:
            mrow("turret", t["macro"], t.get("path") or "con_turret_01", t.get("optional"))
    for w in ld.get("weapons") or []:
        if cv(w.get("macro")): mrow("weapon", w["macro"], w.get("path") or "con_weapon_01", w.get("optional"))
    if not macros: return []
    thr = ('\t\t\t\t\t<virtualmacros>\n\t\t\t\t\t\t<thruster macro="%s"/>\n\t\t\t\t\t</virtualmacros>\n'
           % cv(ld["thruster"])) if cv(ld.get("thruster")) else ""
    body = ('<loadout id="default">\n\t\t\t\t\t<macros>\n%s\n'
            '\t\t\t\t\t</macros>\n%s\t\t\t\t</loadout>') % ("\n".join(macros), thr)
    # 内联进该船 ship macro：已有 default 则替换；已有 <loadouts> 则追加；否则在 <macro> 后新增
    txt = open(ship_mac, encoding="utf-8").read()
    if '<loadout id="default">' in txt:
        m = re.search(r'<loadout id="default">.*?</loadout>', txt, re.S)
        txt = txt[:m.start()] + body + txt[m.end():]
    elif '<loadouts>' in txt:
        m = re.search(r'<loadouts>', txt)
        txt = txt[:m.end()] + '\n\t\t\t\t' + body + txt[m.end():]
    else:
        m = re.search(r'<macro[^>]*>', txt)
        if not m: return []
        txt = txt[:m.end()] + '\n\t\t<loadouts>\n\t\t\t' + body + '\n\t\t</loadouts>' + txt[m.end():]
    open(ship_mac, "w", encoding="utf-8").write(txt)
    return [os.path.relpath(ship_mac, mod)]

def write_ware(mod, cid, mac_name, size, faction, d, tids):
    """写某舰船的建造成本 wares 条目（libraries/wares.xml）。
    若该 ship 的 ware 已存在则整体替换，否则追加。返回相对路径或 None。
    供「新增」与「编辑已有舰船」共用，保证编辑保存成本也生效。"""
    cost = d.get("cost") or {}
    def cv(v): return (v or "").strip()
    pm, pa, px = cv(cost.get("price_min")), cv(cost.get("price_avg")), cv(cost.get("price_max"))
    if pm and pa and px:
        price = (int(pm), int(pa), int(px))
    else:
        price = (7367800,8668000,9968200) if size=="xl" else (3049154,3587240,4125326)
    pt = cv(cost.get("time")) or ("30" if size=="xl" else "150")
    prod_list = cost.get("production") or []
    if prod_list:
        prods = "\n".join(_prod_seg(m.get("method") or "default", m.get("time") or pt, m.get("materials") or [])
                          for m in prod_list)
    else:
        mats = cost.get("materials") or []
        if not mats:
            mats = ([{"ware":"energycells","amount":"3850"},{"ware":"hullparts","amount":"8000"}]
                    if size=="xl" else
                    [{"ware":"energycells","amount":"1264"},{"ware":"hullparts","amount":"3336"}])
        prods = _prod_seg("default", pt, mats)
    jobs_cfg = d.get("jobs") or {}
    job_factions = [f for f in (jobs_cfg.get("factions") or []) if f]
    owners = job_factions if job_factions else [faction]
    owner_xml = "\n".join('\t\t\t<owner faction="%s"/>' % f for f in owners)
    ware_xml = ('\t\t<ware id="%s" name="{7777771,%d}" description="{7777771,%d}" transport="ship" volume="1" tags="ship">\n'
        '\t\t\t<price min="%d" average="%d" max="%d"/>\n'
        '%s\n'
        '\t\t\t<component ref="%s" amount="1"/>\n'
        '\t\t\t<restriction licence="capitalship"/>\n'
        '%s\n\t\t</ware>') % (cid, tids[0], tids[1], *price, prods, mac_name, owner_xml)
    jp = os.path.join(mod, "libraries", "wares.xml")
    if not os.path.isfile(jp):
        return None
    txt = open(jp, encoding="utf-8").read()
    pat = re.compile(r'<ware\s+id="%s"[^>]*>.*?</ware>' % re.escape(cid), re.S)
    new = re.sub(pat, ware_xml, txt, count=1)
    if new != txt:
        open(jp, "w", encoding="utf-8").write(new)
        return os.path.relpath(jp, mod)
    i = txt.rfind("</add>")
    if i < 0:
        return None
    txt = txt[:i].rstrip() + "\n" + ware_xml + "\n\t\t" + txt[i:]
    open(jp, "w", encoding="utf-8").write(txt)
    return os.path.relpath(jp, mod)

def update_registry(mod, comp_name, mac_name, stor_id, new_da, faction, size, name, d, tids):
    """更新 wares / shipgroups / t / index 注册文件。返回修改的文件相对路径。"""
    modified = []
    nid  = comp_name
    name_en = d.get("name_en") or (name.upper())
    name_zh = d.get("name_zh") or name.title()
    desc_zh= d.get("desc_zh") or ("EVE舰船 %s" % name.title())
    desc_en= d.get("desc_en") or ("EVE ship %s" % name.title())
    group = "UP7_EVE_battleship_%s_01" % ("xl" if size=="xl" else "l")
    # 建造成本：界面可自定义（cost），留空按尺寸套默认档；已有该 ship 则替换，无则追加
    ware_rel = write_ware(mod, comp_name, mac_name, size, faction, d, tids)
    if ware_rel: modified.append(ware_rel)
    jobs_cfg = d.get("jobs") or {}

    def insert_add(path, text):
        """在 <add sel=...> 块末尾（</add> 前）插入新条目。"""
        if not os.path.isfile(path): return False
        txt = open(path, encoding="utf-8").read()
        i = txt.rfind("</add>")
        if i < 0: return False
        txt = txt[:i] + text + "\n\t\t" + txt[i:]
        open(path,"w",encoding="utf-8").write(txt)
        return True

    # jobs：AI 派系主动使用（派系 × 任务）
    if jobs_cfg.get("enabled"):
        modified += write_jobs(mod, mac_name, size, jobs_cfg, tids[0])

    # 装配预设：生成 loadout（写入该船 ship macro 内联 loadout id="default"，默认/AI/船厂生成生效）
    modified += write_loadout(mod, mac_name, d.get("loadout") or {}, size)

    # shipgroups
    sg_p = os.path.join(mod,"libraries","shipgroups.xml")
    sg_xml = '\n\t\t\t<select macro="%s" weight="20"/>' % mac_name
    # 插入到对应 group 的最后一个 </select> 之后、</group> 前
    if os.path.isfile(sg_p):
        txt = open(sg_p, encoding="utf-8").read()
        j = txt.find('group name="%s"' % group)
        if j < 0:
            # group 不存在则新建
            j2 = txt.rfind("</add>")
            newgrp = ('\n\t\t<group name="%s">\n\t\t\t<select macro="%s" weight="20"/>\n\t\t</group>') % (group, mac_name)
            txt = txt[:j2].rstrip() + newgrp + "\n\t\t" + txt[j2:]
        else:
            k = txt.find("</group>", j)
            txt = txt[:k].rstrip() + sg_xml + "\n\t\t" + txt[k:]
        open(sg_p,"w",encoding="utf-8").write(txt)
        modified.append(os.path.relpath(sg_p, mod))

    # t 名称（中文 + 英文）
    zh_p, en_p = _loc_files(mod)
    for tp, n, desc in ((zh_p, name_zh, desc_zh), (en_p, name_en, desc_en)):
        if not tp: continue
        txt = open(tp, encoding="utf-8").read()
        # 在 page id=7777771 块内 </page> 前插入
        j = txt.find('<page id="7777771"')
        if j < 0: continue
        k = txt.find("</page>", j)
        ins = ("\n\t\t\t<t id=\"%d\">%s</t>\n\t\t\t<t id=\"%d\">%s</t>\n\t\t\t<t id=\"%d\">%s</t>" %
               (tids[0],n, tids[1],desc, tids[2],desc))
        txt = txt[:k].rstrip() + ins + txt[k:]
        open(tp,"w",encoding="utf-8").write(txt)
        modified.append(os.path.relpath(tp, mod))

    # index/macros.xml（entry 路径按目标 mod 目录名动态拼接，不硬编码 UP7）
    im_p = os.path.join(mod,"index","macros.xml")
    modn = os.path.basename(mod)
    im_txt = '\n\t\t\t<entry name="%s" value="extensions\\%s\\assets\\units\\size_%s\\macros\\%s"/>' % (mac_name, modn, size, mac_name)
    im_txt += '\n\t\t\t<entry name="%s" value="extensions\\%s\\assets\\units\\size_%s\\macros\\%s"/>' % (stor_id, modn, size, stor_id)
    if new_da:
        im_txt += '\n\t\t\t<entry name="%s_macro" value="extensions\\%s\\assets\\structures\\dock\\macros\\%s_macro"/>' % (new_da, modn, new_da)
    if insert_add(im_p, im_txt): modified.append(os.path.relpath(im_p, mod))

    # index/components.xml
    ic_p = os.path.join(mod,"index","components.xml")
    ic_txt = '\n\t\t\t<entry name="%s" value="extensions\\%s\\assets\\units\\size_%s\\%s"/>' % (comp_name, modn, size, comp_name)
    if new_da:
        ic_txt += '\n\t\t\t<entry name="%s" value="extensions\\%s\\assets\\structures\\dock\\%s"/>' % (new_da, modn, new_da)
    if insert_add(ic_p, ic_txt): modified.append(os.path.relpath(ic_p, mod))

    return {"files": modified}

# ==================== 装备模块：炮台 / 主武器 / 护盾 / 导弹 ====================
EQUIP_CLASSES = {
    "shield":  {"label": "护盾",   "grp": "shields",  "tg": "equipment shield",  "lic": "generaluseequipment", "sizes": ["medium", "large", "extralarge"]},
    "turret":  {"label": "炮台",   "grp": "turrets",  "tg": "equipment turret",  "lic": "generaluseequipment", "sizes": ["medium", "large", "extralarge"]},
    "weapon":  {"label": "主武器", "grp": "weapons",  "tg": "equipment weapon",  "lic": "militaryequipment",  "sizes": ["medium", "large", "extralarge"]},
    "missile": {"label": "导弹",   "grp": "missiles", "tg": "equipment missile", "lic": "",                    "sizes": []},
    "bullet":  {"label": "弹丸", "grp": "", "tg": "equipment bullet", "lic": "", "sizes": []},
    "engine":  {"label": "引擎", "grp": "engines", "tg": "equipment engine", "lic": "generaluseequipment", "sizes": ["small", "medium", "large", "extralarge"]},
}
_EQ_SCAN_CACHE = None
_EQ_DUP_CACHE = None
_BULLET_DUP_CACHE = None
_EQ_SCAN_LOCK = threading.Lock()

def _eq_props_dir(source):
    return (os.path.normpath(os.path.join(ROOT, "assets", "props"))
            if source == "vanilla"
            else os.path.normpath(os.path.join(ROOT, "extensions", source, "assets", "props")))

def _eq_roots():
    roots, labels = [], []
    roots.append(_eq_props_dir("vanilla")); labels.append("vanilla")
    for m in _ext_order():
        roots.append(_eq_props_dir(m)); labels.append(m)
    return roots, labels

def _scan_props_dir(props, src, seen):
    """扫描单个来源 props 目录（SurfaceElements/Engines/WeaponSystems 的宏），按 component
    connection tags 结构规则分类写入 seen[(cls, hid, src)]。从 equip_scan 抽出，
    供全盘冷扫与增量刷新（eq_cache_refresh_source）共用同一分类规则。"""
    def put(cls, p, src):
        hid = os.path.basename(p)[:-len("_macro.xml")]
        ref = _read_macro_ref(p)
        comp = _equip_component(p, ref) if ref else None
        sizes, types = set(), set()
        virt = False
        if comp:
            sizes, types = _comp_tags_sizes(comp, (cls,))
        if not types and cls == "engine":
            # 推进器等虚拟组件宏（class=engine 但无实体 component 文件，如 <component virtual="1"/>）
            mtxt = open(p, encoding="utf-8", errors="ignore").read()
            if re.search(r'<macro\b[^>]*\bclass="engine"', mtxt) and re.search(r'<thrust\b', mtxt):
                types.add("engine")
                virt = True    # 虚拟宏标记：装配预设引擎下拉排除推进器类宏用（2026-10-14）
                m = re.search(r'_([xl]{2}|xs|s|m|l)_', hid)
                if m:
                    sizes.add({"xl": "extralarge", "l": "large", "m": "medium", "s": "small", "xs": "xs"}[m.group(1)])
        if not types:              # 只有 component 连接点确实含该类型词才算该 class（结构规则）
            return
        seen[(cls, hid, src)] = {"id": hid, "path": p, "cls": cls, "source": src, "sizes": sorted(sizes),
                              "ref": ref, "ref_source": _ref_comp_source(comp, ref),
                              **({"virtual": True} if virt else {})}
    sd = os.path.join(props, "SurfaceElements", "macros")
    if os.path.isdir(sd):
        for f in sorted(os.listdir(sd)):
            if f.endswith("_macro.xml") and "_video" not in f:
                put("shield", os.path.join(sd, f), src)
    ed = os.path.join(props, "Engines", "macros")
    if os.path.isdir(ed):
        for f in sorted(os.listdir(ed)):
            if f.endswith("_macro.xml") and "_video" not in f:
                put("engine", os.path.join(ed, f), src)
    wd = os.path.join(props, "WeaponSystems")
    if os.path.isdir(wd):
        for root, _, files in os.walk(wd):
            for f in sorted(files):
                if not f.endswith("_macro.xml") or "_video" in f:
                    continue
                p = os.path.join(root, f)
                ref = _read_macro_ref(p)
                if not ref:
                    continue
                comp = _equip_component(p, ref)
                if not comp:
                    continue
                sizes, types = _comp_tags_sizes(comp, ("turret", "weapon", "missile", "missileturret"))
                if "turret" in types or "missileturret" in types:
                    try:
                        mtc = re.search(r'<macro\b[^>]*\bclass="([^"]*)"', open(p, encoding="utf-8", errors="ignore").read())
                        sub = "mturret" if (mtc and mtc.group(1) == "missileturret") else "turret"
                    except Exception:
                        sub = "turret"
                    seen[("turret", os.path.basename(p)[:-len("_macro.xml")], src)] = \
                        {"id": os.path.basename(p)[:-len("_macro.xml")], "path": p, "cls": "turret", "source": src, "sizes": sorted(sizes), "ref": ref, "ref_source": _ref_comp_source(comp, ref), "subtype": sub}
                elif "weapon" in types:
                    try:
                        sub = "wlaunch" if '<ammunition' in open(p, encoding="utf-8", errors="ignore").read() else "weapon"
                    except Exception:
                        sub = "weapon"
                    seen[("weapon", os.path.basename(p)[:-len("_macro.xml")], src)] = \
                        {"id": os.path.basename(p)[:-len("_macro.xml")], "path": p, "cls": "weapon", "source": src, "sizes": sorted(sizes), "ref": ref, "ref_source": _ref_comp_source(comp, ref), "subtype": sub}
                elif "missile" in types:
                    seen[("missile", os.path.basename(p)[:-len("_macro.xml")], src)] = \
                        {"id": os.path.basename(p)[:-len("_macro.xml")], "path": p, "cls": "missile", "source": src, "sizes": sorted(sizes), "ref": ref, "ref_source": _ref_comp_source(comp, ref)}

def eq_cache_refresh_source(mod):
    """装备缓存增量维护：只重扫目标 mod 的 assets/props，替换该来源分片并重写签名，
    其余来源分片原样复用。工程自己新增/删除/修改装备后调用；缓存未构建时不动。"""
    global _EQ_SCAN_CACHE, _EQ_DUP_CACHE, _EQ_BY_SOURCE
    if _EQ_SCAN_CACHE is None:
        return
    src = os.path.basename(mod)
    with _EQ_SCAN_LOCK:
        if _EQ_SCAN_CACHE is None:
            return
        order = ["vanilla"] + _ext_order()
        if _EQ_BY_SOURCE is None:
            _EQ_BY_SOURCE = {}
        _EQ_BY_SOURCE[src] = _eq_scan_source(src)
        c = _cache_load("equip_scan.json") or {"ver": _CACHE_VER, "items": {}}
        items = c.get("items") or {}
        items[src] = {"sig": _sig_paths([os.path.join(mod, "assets", "props")]),
                      "data": _EQ_BY_SOURCE[src]}
        c["ver"], c["items"] = _CACHE_VER, items
        _cache_save("equip_scan.json", c)
        _EQ_SCAN_CACHE, _EQ_DUP_CACHE = _eq_merge(_EQ_BY_SOURCE, order)

_EQ_BY_SOURCE = None
def _eq_scan_source(src):
    """扫描单个来源 props 目录，返回可 JSON 化的 [[cls,hid,item],...]（保持扫描插入序）。"""
    seen = {}
    _scan_props_dir(_eq_props_dir(src), src, seen)
    return [[cls, hid, it] for (cls, hid, _s), it in seen.items()]

def _eq_merge(by_src, order):
    """按加载序合并各来源条目：同名后者覆盖（位置保留首次插入序），dup 按来源顺序累积。"""
    out, dup = {}, {}
    for src in order:
        for cls, hid, it in (by_src.get(src) or []):
            out.setdefault(cls, {})[hid] = it
            dup.setdefault(cls, {}).setdefault(hid, []).append(it)
    return out, dup

def equip_scan():
    """扫描 4 类装备（原版+扩展，后覆盖先）。每项 {id,path,cls,source,sizes}。
    尺寸/类别从 component connection tags 判定（结构规则）。
    缓存策略：按来源分片落盘 + 签名校验，只重扫变化的来源。"""
    global _EQ_SCAN_CACHE, _EQ_DUP_CACHE, _EQ_BY_SOURCE
    if _EQ_SCAN_CACHE is not None:
        return _EQ_SCAN_CACHE
    with _EQ_SCAN_LOCK:
        if _EQ_SCAN_CACHE is not None:          # 等待锁后他人已构建
            return _EQ_SCAN_CACHE
        order = ["vanilla"] + _ext_order()
        if _EQ_BY_SOURCE is None:
            _EQ_BY_SOURCE, _sigs, _chg = _cached_sources(
                "equip_scan.json", [(src, [_eq_props_dir(src)]) for src in order], _eq_scan_source)
        out, dup = _eq_merge(_EQ_BY_SOURCE, order)
        _EQ_SCAN_CACHE, _EQ_DUP_CACHE = out, dup
        return out

_BULLET_SCAN_CACHE = None
_BULLET_BY_SOURCE = None
def _bullet_fx_dir(src):
    """来源的 fx/weaponFx 根目录（vanilla = 原版）。"""
    base = ROOT if src == "vanilla" else os.path.join(ROOT, "extensions", src)
    return os.path.join(base, "assets", "fx", "weaponFx")

def _bullet_scan_fxdir(fx_root, src, seen):
    """扫描单个来源 fx/weaponFx/macros 下 class='bullet' 的弹丸宏写入 seen[(hid, src)]。
    从 bullet_scan 抽出，供全盘扫描与增量刷新（bullet_cache_refresh_source）共用。"""
    md = os.path.join(fx_root, "macros")
    if not os.path.isdir(md):
        return
    for f in sorted(os.listdir(md)):
        if not (f.startswith("bullet_") and f.endswith("_macro.xml")):
            continue
        p2 = os.path.join(md, f)
        try:
            t = open(p2, encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        if 'class="bullet"' not in t:
            continue
        hid = f[:-len("_macro.xml")]
        kind, size = _bullet_kind(hid)
        ref = _read_macro_ref(p2)
        geo = ""
        comp = None
        if ref:
            comp = _equip_component(p2, ref)
            if comp:
                try:
                    gm = re.search(r'<source\s+geometry="([^"]+)"',
                                   _read_comp_txt(comp))
                    if gm:
                        geo = gm.group(1)
                except Exception:
                    pass
        seen[(hid, src)] = {"id": hid, "path": p2, "cls": "bullet", "source": src,
                     "kind": kind, "size": size, "geometry": geo, "ref": ref, "ref_source": _ref_comp_source(comp, ref)}

def _bullet_scan_source(src):
    """扫描单个来源，返回可 JSON 化的条目列表（保持扫描插入序）。"""
    seen = {}
    _bullet_scan_fxdir(_bullet_fx_dir(src), src, seen)
    return [it for (_hid, _s), it in seen.items()]

def _bullet_merge(by_src, order):
    """按加载序合并各来源条目：同名后者覆盖，dup 按来源顺序累积。"""
    out, dup = {}, {}
    for src in order:
        for it in (by_src.get(src) or []):
            hid = it["id"]
            out[hid] = it
            dup.setdefault(hid, []).append(it)
    return out, dup

def bullet_cache_refresh_source(mod):
    """弹丸缓存增量维护：只重扫目标 mod 的 assets/fx/weaponFx，替换该来源分片并重写签名，
    其余来源分片原样复用。工程自己新增/删除/修改弹丸及特效文件后调用；缓存未构建时不动。"""
    global _BULLET_SCAN_CACHE, _BULLET_DUP_CACHE, _BULLET_BY_SOURCE
    if _BULLET_SCAN_CACHE is None:
        return
    src = os.path.basename(mod)
    data = _bullet_scan_source(src)
    if _BULLET_BY_SOURCE is None:
        _BULLET_BY_SOURCE = {}
    if _BULLET_BY_SOURCE.get(src) == data:
        return               # 该来源扫描结果无变化：跳过，避免重排与写盘
    _BULLET_BY_SOURCE[src] = data
    c = _cache_load("bullet_scan.json") or {"ver": _CACHE_VER, "items": {}}
    items = c.get("items") or {}
    items[src] = {"sig": _sig_paths([os.path.join(mod, "assets", "fx", "weaponFx")]),
                  "data": data}
    c["ver"], c["items"] = _CACHE_VER, items
    _cache_save("bullet_scan.json", c)
    _BULLET_SCAN_CACHE, _BULLET_DUP_CACHE = _bullet_merge(_BULLET_BY_SOURCE, ["vanilla"] + _ext_order())

def bullet_scan():
    """扫描所有 class='bullet' 弹丸宏（原版 + 各 mod 的 fx/weaponFx/macros）。
    返回 dict: hid -> {id,path,cls,source,kind,size,geometry}。弹种/尺寸从命名结构判定。
    缓存策略：按来源分片落盘 + 签名校验，只重扫变化的来源；输入未变时启动零扫描。"""
    global _BULLET_SCAN_CACHE, _BULLET_DUP_CACHE, _BULLET_BY_SOURCE
    if _BULLET_SCAN_CACHE is not None:
        return _BULLET_SCAN_CACHE
    order = ["vanilla"] + _ext_order()
    if _BULLET_BY_SOURCE is None:
        _BULLET_BY_SOURCE, _sigs, _chg = _cached_sources(
            "bullet_scan.json", [(src, [_bullet_fx_dir(src)]) for src in order], _bullet_scan_source)
    _BULLET_SCAN_CACHE, _BULLET_DUP_CACHE = _bullet_merge(_BULLET_BY_SOURCE, order)
    return _BULLET_SCAN_CACHE

def _bullet_kind(hid):
    """bullet_<race>[_turret]_<size>_<kind>...  → (kind, size)。
    跳过种族词/尺寸词/turret 标记，取真正弹种词做分组。"""
    name = hid.replace("bullet_", "", 1)
    toks = name.split("_")
    RACES = {"gen","arg","tel","par","xen","kha","bor","spl","ter","atf",
             "axe","dam","dga","pir","ylw","player","spacesuit","xrc",
             "scenario","waver","yacht"}
    SIZES = {"s","m","l","xl"}
    size = ""
    for t in toks:
        if t in SIZES:
            size = t
            break
    kind_toks = [t for t in toks if t not in RACES and t not in SIZES and t != "turret"]
    kind = kind_toks[0] if kind_toks else name
    return kind, size

def _eq_meta(cls, hid):
    parts = hid.split("_")
    race = size = mk = ""
    name = hid
    if cls in ("shield", "turret", "weapon") and len(parts) >= 4 and parts[0] == cls:
        race, size = parts[1], parts[2]
        name = "_".join(parts[3:])
    elif cls == "missile":
        name = hid.replace("missile_", "", 1)
    elif cls == "bullet":
        name = hid.replace("bullet_", "", 1)
    m = re.search(r'_mk(\d+)$', name)
    if m:
        mk = "mk" + m.group(1)
        name = name[:m.start()]
    return {"race": race, "size": size, "name": name, "mk": mk}

def equip_templates(cls, kind=""):
    """某 class 全部装备（新增模板下拉）：id + 中文名 + 尺寸/种族/mk/来源。
    bullet 可按弹种 kind 过滤（kind 为空返回全部）。"""
    if cls not in EQUIP_CLASSES:
        return []
    if cls == "bullet":
        its = [x for x in bullet_scan().values() if not kind or (x.get("kind") or "") == kind]
        dup = _BULLET_DUP_CACHE or {}
        outb = []
        for it in sorted(its, key=lambda x: (x.get("kind",""), x["id"])):
            dits = (dup.get(it["id"]) or [it])
            for _it in dits:
                if kind and (_it.get("kind") or "") != kind:
                    continue
                outb.append({"id": _it["id"], "name": LX.macro_display(_it["path"], _zh_id(_it["id"]) + "[译]", "zh"),
                             "cls": "bullet", "source": _it["source"],
                             "sizes": [_it["size"]] if _it.get("size") else [],
                             "kind": _it.get("kind", ""), "geometry": _it.get("geometry", ""), "mk": "",
                             "ref": _it.get("ref", ""), "ref_source": _it.get("ref_source", ""),
                             "dup": len(dits) > 1,
                             "source_path": (ROOT if _it["source"] == "vanilla" else os.path.join(ROOT, "extensions", _it["source"]))})
        return outb
    lst = []
    scan = equip_scan()
    dup = _EQ_DUP_CACHE or {}
    for hid, it in (scan.get(cls) or {}).items():
        its = (dup.get(cls) or {}).get(hid) or [it]
        for _it in its:
            meta = _eq_meta(cls, hid)
            lst.append({"id": hid, "name": LX.macro_display(_it["path"], _zh_id(hid) + "[译]", "zh"),
                        "cls": cls, "source": _it["source"], "sizes": _it["sizes"], "subtype": _it.get("subtype", ""),
                        "race": meta["race"], "mk": meta["mk"], "ref": _it.get("ref", ""), "ref_source": _it.get("ref_source", ""),
                        "dup": len(its) > 1,
                        # win=加载序胜者（游戏运行时实际生效的来源，磁盘缓存加载后 scan/dup 是不同对象，按 source+path 判等）
                        "win": (_it.get("source") == it.get("source") and _it.get("path") == it.get("path")),
                        "virtual": bool(_it.get("virtual")),
                        "source_path": (ROOT if _it["source"] == "vanilla" else os.path.join(ROOT, "extensions", _it["source"]))})
    return sorted(lst, key=lambda x: (x["id"], x["source"]))

def _read_equip_fields(cls, mtxt):
    f = {}
    def num(tag, name):
        m = re.search(r'<%s\b[^>]*%s="([^"]*)"' % (tag, name), mtxt)
        return m.group(1) if m else ""
    if cls == "engine":
        for k, tg, an in (("boost_duration","boost","duration"),("boost_recharge","boost","recharge"),
                          ("boost_thrust","boost","thrust"),("boost_acceleration","boost","acceleration"),
                          ("boost_attack","boost","attack"),("boost_release","boost","release"),
                          ("boost_coast","boost","coast"),
                          ("travel_charge","travel","charge"),("travel_thrust","travel","thrust"),
                          ("travel_attack","travel","attack"),("travel_release","travel","release"),
                          ("thrust_forward","thrust","forward"),("thrust_reverse","thrust","reverse"),
                          ("thrust_strafe","thrust","strafe"),("thrust_pitch","thrust","pitch"),
                          ("thrust_yaw","thrust","yaw"),("thrust_roll","thrust","roll"),
                          ("hull_max","hull","max"),("hull_threshold","hull","threshold"),
                          ("integrated","hull","integrated"),("glow_dynamic","glow","dynamic")):
            f[k] = num(tg, an)
        def _rref(tg):
            m = re.search(r'<%s\s+ref="([^"]*)"' % tg, mtxt)
            return m.group(1) if m else ""
        f["boosting_ref"] = _rref("boosting")
        f["traveling_ref"] = _rref("traveling")
        f["sound_detail"] = _rref("enginedetail")
        def _rpts(tg):
            m = re.search(r'<%s>(.*?)</%s>' % (tg, tg), mtxt, re.S)
            if not m:
                return ""
            return ";".join("%s:%s" % (p.group(1), p.group(2))
                            for p in re.finditer(r'<point\s+position="([^"]*)"\s+value="([^"]*)"', m.group(1)))
        f["decel_pts"] = _rpts("decelerationcurve")
        f["strafe_pts"] = _rpts("strafecurve")
    elif cls == "shield":
        f["hull"] = num("hull", "max"); f["hull_threshold"] = num("hull", "threshold")
        f["recharge_max"] = num("recharge", "max"); f["recharge_rate"] = num("recharge", "rate")
        f["recharge_delay"] = num("recharge", "delay"); f["disruption"] = num("recharge", "disruptionstability")
        f["integrated"] = num("hull", "integrated")
    elif cls == "turret":
        m = re.search(r'<bullet\s+class="([^"]*)"', mtxt)
        _fb = m.group(1) if m else ""
        if _fb.endswith("_macro"): _fb = _fb[:-6]
        f["bullet"] = _fb
        f["rot_speed"] = num("rotationspeed", "max"); f["rot_accel"] = num("rotationacceleration", "max")
        f["hull"] = num("hull", "max"); f["hull_threshold"] = num("hull", "threshold")
        f["integrated"] = num("hull", "integrated"); f["weapon_angle"] = num("weapon", "angle")
        # 导弹发射塔(missileturret)专用：弹药类别 + 弹药舱容量
        mm = re.search(r'<ammunition\s+tags="([^"]*)"', mtxt); f["ammo_tags"] = mm.group(1) if mm else ""
        f["storage"] = num("storage", "capacity")
    elif cls == "weapon":
        m = re.search(r'<bullet\s+class="([^"]*)"', mtxt)
        _fb = m.group(1) if m else ""
        if _fb.endswith("_macro"): _fb = _fb[:-6]
        f["bullet"] = _fb
        f["overheat"] = num("heat", "overheat"); f["cooldelay"] = num("heat", "cooldelay")
        f["overheatcd"] = num("heat", "overheatcooldelay"); f["coolrate"] = num("heat", "coolrate")
        f["reenable"] = num("heat", "reenable")
        f["rot_speed"] = num("rotationspeed", "max"); f["rot_accel"] = num("rotationacceleration", "max")
        f["hull"] = num("hull", "max"); f["integrated"] = num("hull", "integrated")
        f["weapon_angle"] = num("weapon", "angle"); f["hittable"] = num("hull", "hittable")
        f["weapon_shotangle"] = num("weapon", "shotangle")
        f["storage"] = num("storage", "capacity")
        mm = re.search(r'<ammunition\s+tags="([^"]*)"', mtxt); f["ammo_tags"] = mm.group(1) if mm else ""
        f["zoom_delay"] = num("zoom", "delay"); f["zoom_factor"] = num("zoom", "factor")
        f["zoom_time"] = num("zoom", "time")
    elif cls == "missile":
        m = re.search(r'<missile\b([^>]*)>', mtxt); a = m.group(1) if m else ""
        for k in ("amount", "barrelamount", "lifetime", "range", "guided", "retarget", "tags", "angle", "icon",
                  "timediff", "swarm", "targetable", "influencelist"):
            mm = re.search(r'%s="([^"]*)"' % k, a); f[k] = mm.group(1) if mm else ""
        f["ammo"] = num("ammunition", "value"); f["ammo_reload"] = num("ammunition", "reload")
        f["explosion"] = num("explosiondamage", "value"); f["explosion_shield"] = num("explosiondamage", "shield")
        f["explosion_shielddisruption"] = num("explosiondamage", "shielddisruption")
        f["explosion_hull"] = num("explosiondamage", "hull")
        f["reload"] = num("reload", "time"); f["hull"] = num("hull", "max")
        mm = re.search(r'<weapon\s+system="([^"]*)"', mtxt); f["weapon_system"] = mm.group(1) if mm else ""
        f["countermeasure"] = num("countermeasure", "resilience")
        f["lock_time"] = num("lock", "time"); f["lock_range"] = num("lock", "range")
        mm = re.search(r'<accfactors\b[^>]*reverse="([^"]*)"', mtxt); f["acc_reverse"] = mm.group(1) if mm else ""
        f["mass"] = num("physics", "mass")
        for axis in ("pitch", "yaw", "roll"):
            mm = re.search(r'<inertia\b[^>]*%s="([^"]*)"' % axis, mtxt); f["in_%s" % axis] = mm.group(1) if mm else ""
        for ax in ("forward", "reverse", "horizontal", "vertical", "pitch", "yaw", "roll"):
            mm = re.search(r'<drag\b[^>]*%s="([^"]*)"' % ax, mtxt); f["dr_%s" % ax] = mm.group(1) if mm else ""
    elif cls == "bullet":
        for t, a, k in (("bullet","speed","speed"),("bullet","lifetime","lifetime"),
                        ("bullet","amount","amount"),("bullet","barrelamount","barrelamount"),
                        ("bullet","delay","delay"),("bullet","icon","icon"),
                        ("bullet","angle","angle"),("bullet","maxhits","maxhits"),
                        ("bullet","ricochet","ricochet"),
                        ("ammunition","value","ammo_cap"),("ammunition","reload","ammo_reload"),
                        ("reload","rate","reload_rate"),("heat","value","heat"),
                        ("damage","value","damage"),("damage","shielddisruption","shielddisruption"),
                        ("damage","shield","damage_shield"),("damage","repair","repair"),
                        ("damage","hull","damage_hull"),
                        ("bullet","timediff","timediff"),("bullet","scale","scale"),
                        ("bullet","attach","attach"),("bullet","range","range"),
                        ("bullet","influencelist","influencelist"),
                        ("bullet","restitution","restitution"),("bullet","mass","bullet_mass"),
                        ("bullet","chargetime","chargetime"),("bullet","firewhenfullcharge","firewhenfullcharge"),
                        ("bullet","requirefullcharge","requirefullcharge"),("bullet","heatwhilecharging","heatwhilecharging"),
                        ("bullet","selfdestruct","selfdestruct"),("bullet","plannedselfdestruct","plannedselfdestruct"),
                        ("bullet","selfdestructmintime","selfdestructmintime"),("bullet","selfdestructtimediff","selfdestructtimediff"),
                        ("bullet","sticktime","sticktime"),
                        ("reload","time","reload_time"),("heat","initial","heat_initial"),
                        ("damage","delay","damage_delay"),("areadamage","shield","area_shield"),
                        ("multiplier","traveldrive","mult_traveldrive"),("multiplier","mining","mult_mining"),
                        ("multiplier","surfaceelement","mult_surface"),
                        ("areadamage","value","area_dmg"),("areadamage","lifetime","area_lifetime")):
            mm = re.search(r'<%s\b[^>]*%s="([^"]*)"' % (t, a), mtxt); f[k] = mm.group(1) if mm else ""
        dm = re.search(r'<damagecurves>(.*?)</damagecurves>', mtxt, re.S)
        f["dmgcurve_pts"] = (";".join("%s:%s" % (p.group(1), p.group(2))
                             for p in re.finditer(r'<point\s+position="([^"]*)"\s+value="([^"]*)"', dm.group(1)))) if dm else ""
        m = re.search(r'<weapon\s+system="([^"]*)"', mtxt); f["weapon_system"] = m.group(1) if m else ""
    return f

def _apply_equip_fields(cls, mtxt, f):
    """按 class 把字段写回 macro properties（空值删除属性）。
    setnum/setbul 只读闭包外层 mtxt 并返回新文本，外层统一再赋值，避免局部变量陷阱。"""
    def setnum(tag, name, key):
        if key not in f:
            return None
        v = (f.get(key) or "").strip()
        if not v:
            return re.sub(r'\s%s="[^"]*"' % name, "", mtxt, count=1)
        if not re.search(r'<%s\b[^>]*?%s="' % (tag, name), mtxt):
            # 属性不存在：插入新属性（兼容自闭合与开闭标签；标签不存在则不动）
            return re.sub(r'(<%s\b[^>]*?)\s*(/?>)' % tag,
                          lambda m: m.group(1) + ' %s="%s"' % (name, v) + m.group(2), mtxt, count=1)
        return re.sub(r'(<%s\b[^>]*?%s=")[^"]*(")' % (tag, name),
                      lambda m: m.group(1) + v + m.group(2), mtxt, count=1)
    def setbul(key):
        if key not in f:
            return None
        v = (f.get(key) or "").strip()
        if not v:
            return None
        cur = re.search(r'<bullet\s+class="([^"]*)"', mtxt)
        suf = ""
        if cur and cur.group(1).endswith("_macro") and not v.endswith("_macro"):
            suf = "_macro"
        return re.sub(r'(<bullet\s+class=")[^"]*(")', r'\g<1>%s\g<2>' % (v + suf), mtxt, count=1)
    def app(r):
        return r if r is not None else mtxt
    if cls == "engine":
        for k, tg, an in (("boost_duration","boost","duration"),("boost_recharge","boost","recharge"),
                          ("boost_thrust","boost","thrust"),("boost_acceleration","boost","acceleration"),
                          ("boost_attack","boost","attack"),("boost_release","boost","release"),
                          ("boost_coast","boost","coast"),
                          ("travel_charge","travel","charge"),("travel_thrust","travel","thrust"),
                          ("travel_attack","travel","attack"),("travel_release","travel","release"),
                          ("thrust_forward","thrust","forward"),("thrust_reverse","thrust","reverse"),
                          ("thrust_strafe","thrust","strafe"),("thrust_pitch","thrust","pitch"),
                          ("thrust_yaw","thrust","yaw"),("thrust_roll","thrust","roll"),
                          ("hull_max","hull","max"),("hull_threshold","hull","threshold"),
                          ("integrated","hull","integrated"),("glow_dynamic","glow","dynamic")):
            mtxt = app(setnum(tg, an, k))
        def setnamed(par, child, key):
            if key not in f:
                return mtxt
            v = (f.get(key) or "").strip()
            if v:
                cm = re.search(r'<%s\s+ref="[^"]*"' % child, mtxt)
                if cm:
                    return re.sub(r'(<%s\s+ref=")[^"]*(")' % child, r'\g<1>%s\g<2>' % v, mtxt, count=1)
                pm = re.search(r'<%s>(.*?)</%s>' % (par, par), mtxt, re.S)
                if pm:
                    ins = pm.start(1) + len(pm.group(1))
                    return mtxt[:ins] + '\n    <%s ref="%s" />' % (child, v) + mtxt[ins:]
                j = mtxt.rfind("</properties>")
                if j < 0:
                    return mtxt
                return mtxt[:j] + '  <%s>\n    <%s ref="%s" />\n  </%s>\n' % (par, child, v, par) + mtxt[j:]
            return re.sub(r'\s*<%s\s+ref="[^"]*"\s*/>' % child, "", mtxt)
        def setpts(block, key):
            if key not in f:
                return mtxt
            v = (f.get(key) or "").strip()
            if v:
                pts = "".join('<point position="%s" value="%s" />\n' % (p.split(":")[0], p.split(":")[1])
                              for p in v.split(";") if ":" in p)
                pm = re.search(r'<%s>.*?</%s>' % (block, block), mtxt, re.S)
                if pm:
                    return mtxt.replace(pm.group(0), '<%s>\n%s</%s>' % (block, pts, block), 1)
                j = mtxt.rfind("</properties>")
                if j < 0:
                    return mtxt
                return mtxt[:j] + '  <%s>\n%s</%s>\n' % (block, pts, block) + mtxt[j:]
            return re.sub(r'\s*<%s>.*?</%s>\s*' % (block, block), "", mtxt, flags=re.S)
        mtxt = app(setnamed("effects", "boosting", "boosting_ref"))
        mtxt = app(setnamed("effects", "traveling", "traveling_ref"))
        mtxt = app(setnamed("sounds", "enginedetail", "sound_detail"))
        mtxt = app(setpts("decelerationcurve", "decel_pts"))
        mtxt = app(setpts("strafecurve", "strafe_pts"))
    elif cls == "shield":
        for k, tg, an in (("hull","hull","max"),("hull_threshold","hull","threshold"),
                          ("integrated","hull","integrated"),
                          ("recharge_max","recharge","max"),("recharge_rate","recharge","rate"),
                          ("recharge_delay","recharge","delay"),("disruption","recharge","disruptionstability")):
            mtxt = app(setnum(tg, an, k))
    elif cls == "turret":
        mtxt = app(setbul("bullet"))
        for k, tg, an in (("rot_speed","rotationspeed","max"),("rot_accel","rotationacceleration","max"),
                          ("hull","hull","max"),
                          ("hull_threshold","hull","threshold"),("integrated","hull","integrated"),
                          ("weapon_angle","weapon","angle")):
            mtxt = app(setnum(tg, an, k))
        # 导弹发射塔(missileturret)专用：弹药类别 tags + 弹药舱容量（空值删除，普通炮塔无影响）
        if "ammo_tags" in f:
            v = (f.get("ammo_tags") or "").strip()
            amm = re.search(r'<ammunition\b[^>]*>', mtxt)
            if amm:
                if v:
                    if re.search(r'\btags="', amm.group(0)):
                        mtxt = re.sub(r'(<ammunition\b[^>]*?tags=")[^"]*(")', r'\g<1>%s\g<2>' % v, mtxt, count=1)
                    else:
                        mtxt = mtxt.replace(amm.group(0), amm.group(0)[:-1] + ' tags="%s">' % v, 1)
                else:
                    mtxt = re.sub(r'(<ammunition\b[^>]*?)\s+tags="[^"]*"', r'\g<1>', mtxt, count=1)
        mtxt = app(setnum("storage", "capacity", "storage"))
    elif cls == "weapon":
        mtxt = app(setbul("bullet"))
        for k, tg, an in (("overheat","heat","overheat"),("cooldelay","heat","cooldelay"),
                          ("overheatcd","heat","overheatcooldelay"),("coolrate","heat","coolrate"),
                          ("reenable","heat","reenable"),("rot_speed","rotationspeed","max"),
                          ("rot_accel","rotationacceleration","max"),("hull","hull","max"),
                          ("integrated","hull","integrated"),
                          ("weapon_angle","weapon","angle"),("weapon_shotangle","weapon","shotangle"),
                          ("hittable","hull","hittable"),("storage","storage","capacity"),
                          ("zoom_delay","zoom","delay"),("zoom_factor","zoom","factor"),
                          ("zoom_time","zoom","time")):
            mtxt = app(setnum(tg, an, k))
        # 发射类武器专用：弹药类别 tags（空值删除，普通武器无影响）
        if "ammo_tags" in f:
            v = (f.get("ammo_tags") or "").strip()
            amm = re.search(r'<ammunition\b[^>]*>', mtxt)
            if amm:
                if v:
                    if re.search(r'\btags="', amm.group(0)):
                        mtxt = re.sub(r'(<ammunition\b[^>]*?tags=")[^"]*(")', r'\g<1>%s\g<2>' % v, mtxt, count=1)
                    else:
                        mtxt = mtxt.replace(amm.group(0), amm.group(0)[:-1] + ' tags="%s">' % v, 1)
                else:
                    mtxt = re.sub(r'(<ammunition\b[^>]*?)\s+tags="[^"]*"', r'\g<1>', mtxt, count=1)
    elif cls == "missile":
        for k in ("amount","barrelamount","lifetime","range","guided","retarget","tags",
                  "timediff","swarm","targetable","influencelist"):
            if k in f:
                v = (f.get(k) or "").strip()
                if v:
                    mtxt = re.sub(r'(<missile\b[^>]*?%s=")[^"]*(")' % k,
                                  lambda m: m.group(1) + v + m.group(2), mtxt, count=1)
                else:
                    mtxt = re.sub(r'\s%s="[^"]*"' % k, "", mtxt, count=1)
        for k, tg, an in (("ammo","ammunition","value"),("ammo_reload","ammunition","reload"),
                          ("explosion","explosiondamage","value"),
                          ("explosion_shield","explosiondamage","shield"),
                          ("explosion_shielddisruption","explosiondamage","shielddisruption"),
                          ("explosion_hull","explosiondamage","hull"),
                          ("reload","reload","time"),("hull","hull","max"),
                          ("countermeasure","countermeasure","resilience"),("mass","physics","mass"),
                          ("lock_time","lock","time"),("lock_range","lock","range"),
                          ("acc_reverse","accfactors","reverse"),
                          ("angle","missile","angle"),("icon","missile","icon")):
            mtxt = app(setnum(tg, an, k))
        for axis in ("pitch","yaw","roll"):
            mtxt = app(setnum("inertia", axis, "in_"+axis))
        for ax in ("forward","reverse","horizontal","vertical","pitch","yaw","roll"):
            mtxt = app(setnum("drag", ax, "dr_"+ax))
        if "weapon_system" in f and (f.get("weapon_system") or "").strip():
            mtxt = re.sub(r'(<weapon\s+system=")[^"]*(")', r'\g<1>%s\g<2>' % (f.get("weapon_system") or "").strip(), mtxt, count=1)
    elif cls == "bullet":
        for k, tg, an in (("speed","bullet","speed"),("lifetime","bullet","lifetime"),
                          ("amount","bullet","amount"),("barrelamount","bullet","barrelamount"),
                          ("delay","bullet","delay"),("icon","bullet","icon"),
                          ("angle","bullet","angle"),("maxhits","bullet","maxhits"),
                          ("ricochet","bullet","ricochet"),
                          ("ammo_cap","ammunition","value"),("ammo_reload","ammunition","reload"),
                          ("reload_rate","reload","rate"),("heat","heat","value"),
                          ("damage","damage","value"),("shielddisruption","damage","shielddisruption"),
                          ("damage_shield","damage","shield"),("repair","damage","repair"),
                          ("damage_hull","damage","hull"),
                          ("timediff","bullet","timediff"),("scale","bullet","scale"),
                          ("attach","bullet","attach"),("range","bullet","range"),
                          ("influencelist","bullet","influencelist"),
                          ("restitution","bullet","restitution"),("bullet_mass","bullet","mass"),
                          ("chargetime","bullet","chargetime"),("firewhenfullcharge","bullet","firewhenfullcharge"),
                          ("requirefullcharge","bullet","requirefullcharge"),("heatwhilecharging","bullet","heatwhilecharging"),
                          ("selfdestruct","bullet","selfdestruct"),("plannedselfdestruct","bullet","plannedselfdestruct"),
                          ("selfdestructmintime","bullet","selfdestructmintime"),("selfdestructtimediff","bullet","selfdestructtimediff"),
                          ("sticktime","bullet","sticktime"),
                          ("heat_initial","heat","initial"),("damage_delay","damage","delay"),
                          ("area_shield","areadamage","shield"),
                          ("mult_traveldrive","multiplier","traveldrive"),("mult_mining","multiplier","mining"),
                          ("mult_surface","multiplier","surfaceelement"),
                          ("area_dmg","areadamage","value"),("area_lifetime","areadamage","lifetime")):
            mtxt = app(setnum(tg, an, k))
        # 装填时间模式 reload.time（与 reload.rate 互斥；仅当模板已有 time 时改写，避免双模式冲突）
        if (f.get("reload_time") or "").strip():
            mtxt = re.sub(r'(<reload\b[^>]*?time=")[^"]*(")',
                          lambda m: m.group(1) + f["reload_time"].strip() + m.group(2), mtxt, count=1)
        # damagecurves 伤害衰减曲线（霰弹类；模板有才改，空值整块删除）
        if "dmgcurve_pts" in f:
            v = (f.get("dmgcurve_pts") or "").strip()
            if v:
                pts = "".join('<point position="%s" value="%s" />\n' % (p.split(":")[0].strip(), p.split(":")[1].strip())
                              for p in v.split(";") if ":" in p)
                inner = '<time>\n%s</time>' % pts
                pm = re.search(r'<damagecurves>.*?</damagecurves>', mtxt, re.S)
                if pm:
                    mtxt = mtxt.replace(pm.group(0), '<damagecurves>\n%s</damagecurves>' % inner, 1)
            else:
                mtxt = re.sub(r'\s*<damagecurves>.*?</damagecurves>', "", mtxt, count=1, flags=re.S)
        if "weapon_system" in f and (f.get("weapon_system") or "").strip():
            mtxt = re.sub(r'(<weapon\s+system=")[^"]*(")', r'\g<1>%s\g<2>' % (f.get("weapon_system") or "").strip(), mtxt, count=1)
    return mtxt

def _loc_files(lang_root):
    """返回 (中文字典路径, 英文字典路径)，各至多一个。
    工具只有中英两种文本，只写两个锚点文件、其余语言文件一律不动：
    - 中文：0001-l086.xml（简体中文）。无则 None。
    - 英文：0001.xml（默认英文）；若无 0001.xml，则取 0001-l044.xml（美式英语）。再无则 None。"""
    tdir = os.path.join(lang_root, "t")
    if not os.path.isdir(tdir):
        return None, None
    fns = [f.lower() for f in os.listdir(tdir)]
    zh = en = None
    for f in fns:
        if not f.startswith("0001") or not f.endswith(".xml"):
            continue
        if f == "0001-l086.xml":
            zh = os.path.join(tdir, f)
        elif f == "0001.xml":
            en = os.path.join(tdir, f)
    if en is None and "0001-l044.xml" in fns:
        en = os.path.join(tdir, "0001-l044.xml")
    return zh, en

def _alloc_tids(mod):
    maxid = 700
    for root, _, files in os.walk(mod):
        for fn in files:
            if fn.lower().endswith(".xml"):
                try:
                    txt = open(os.path.join(root, fn), encoding="utf-8").read()
                    for m in re.finditer(r"\{7777771,(\d+)\}", txt):
                        v = int(m.group(1))
                        if v > maxid:
                            maxid = v
                    for m in re.finditer(r'<t id="(\d+)"', txt):
                        v = int(m.group(1))
                        if v > maxid:
                            maxid = v
                except Exception:
                    pass
    return [maxid+1, maxid+2]

def _prod_seg(method, time, mats):
    """生成单个 <production> 段（method/time/材料），配方名按 method 映射。"""
    primary = "\n".join('\t\t\t\t\t<ware ware="%s" amount="%s"/>' % (m["ware"], m["amount"])
                        for m in mats if m.get("ware"))
    nm = {"default": "101", "xenon": "601", "terran": "901"}.get(method or "default", "101")
    return ('\t\t\t<production time="%s" amount="1" method="%s" name="{20206,%s}">\n'
            '\t\t\t\t<primary>\n%s\n\t\t\t\t</primary>\n\t\t\t</production>') % (time, method, nm, primary)

def _tpl_icon_video(source, tpl_id):
    """从模板 ware 提取百科右侧动图 <icon video="...">。先按来源忠实查，无则覆盖序回退。无 icon 返回 ''。"""
    m = _find_ware_in(source, tpl_id) or _find_ware(tpl_id)
    if not m:
        return ""
    im = re.search(r'<icon\s+video="([^"]*)"', m.group(2))
    return im.group(1) if im else ""

# ---------- 装备列表图标（equipment list icon）---------
# 游戏机制（menu_ship_configuration.lua L5030/L5098）：舰船配置菜单取图标名
#   "upgrade_" .. macro（macro 含 _macro 后缀），经 libraries/icons.xml 的通配
#   <icon name="upgrade_*" texture="assets\textures\ui\upgrades\*.tga"/> 解析为贴图
#   ...\upgrades\<macro>.tga；宏名无同名贴图 → 落到 upgrade_notfound（列表缺图标）。
# 社区做法（vro / deadairfaction）：在 mod 的 libraries/icons.xml 里用 <diff><add sel="/icons">
# 显式登记 <icon name="upgrade_<宏>" texture="<任一有贴图的宏>"/>，把新宏指向模板贴图。
# 本工具：新增/修改装备自动按「模板贴图（无则同类原版回退）」写别名；删除时清别名。
_UPG_TEX_DIRS = None
_ICON_TEX_INDEX = None

def _upgrade_tex_dirs():
    r"""所有含装备图标贴图的目录：原版 assets\textures\ui\upgrades + 各扩展（两种布局）。"""
    global _UPG_TEX_DIRS
    if _UPG_TEX_DIRS is None:
        dirs = []
        v = os.path.join(ROOT, "assets", "textures", "ui", "upgrades")
        if os.path.isdir(v):
            dirs.append(v)
        ext = os.path.join(ROOT, "extensions")
        if os.path.isdir(ext):
            for m in sorted(os.listdir(ext)):
                for sub in (("assets", "fx", "gui", "textures", "upgrades"),
                            ("assets", "textures", "ui", "upgrades")):
                    d = os.path.join(ext, m, *sub)
                    if os.path.isdir(d):
                        dirs.append(d)
        _UPG_TEX_DIRS = dirs
    return _UPG_TEX_DIRS

def _icon_tex_index():
    """贴图 base 名（含尾部 _macro）→ 游戏内贴图路径（相对解包根，统一 .tga 扩展）。
    磁盘上贴图为 <名>.tga.gz(+.sig)，游戏内实际路径为 <名>.tga。原版目录优先（setdefault）。"""
    global _ICON_TEX_INDEX
    if _ICON_TEX_INDEX is None:
        ix = {}
        for d in _upgrade_tex_dirs():
            rel = os.path.relpath(d, ROOT)
            try:
                files = os.listdir(d)
            except Exception:
                continue
            for f in files:
                low = f.lower()
                if low.endswith(".sig"):
                    continue
                if low.endswith(".gz"):
                    f = f[:-3]
                base = f
                if not base:
                    continue
                for e in (".tga", ".dds", ".png", ".jpg"):   # 少数 mod 直接放 .dds/.tga
                    if base.lower().endswith(e):
                        base = base[:-len(e)]
                        break
                # 磁盘命名 <base>.gz（无图片扩展）；游戏内路径按通配 *.tga = <base>.tga
                ix.setdefault(base, os.path.join(rel, base + ".tga").replace("/", "\\"))
        _ICON_TEX_INDEX = ix
    return _ICON_TEX_INDEX

def _icon_texture_for(icon_macro):
    """给定「图标来源宏名」返回贴图路径；无同名贴图返回 ''。"""
    if not icon_macro:
        return ""
    n = icon_macro.strip()
    if n and not n.endswith("_macro"):
        n += "_macro"
    return _icon_tex_index().get(n, "")

def _class_fallback_icon(cls):
    """同类原版回退贴图：按 class 前缀取一个原版贴图（首选原版目录，其次任意来源）。"""
    pref = {"engine": "engine_", "shield": "shield_", "turret": "turret_",
            "weapon": "weapon_", "missile": "missile_"}.get(cls, "")
    if not pref:
        return ""
    ix = _icon_tex_index()
    keys = sorted(k for k in ix if k.startswith(pref))
    for k in keys:
        if not ix[k].lower().startswith("extensions\\"):
            return ix[k]
    return ix[keys[0]] if keys else ""

def _mod_icons_path(mod):
    return os.path.join(mod, "libraries", "icons.xml")

def _write_mod_icon(mod, icon_name, texture):
    """在 mod 的 libraries/icons.xml 登记/更新 <icon name texture>。文件/结构自动创建。
    返回修改文件相对路径；无 texture 或失败返回 None。"""
    if not icon_name or not texture:
        return None
    fp = _mod_icons_path(mod)
    os.makedirs(os.path.dirname(fp), exist_ok=True)
    if os.path.isfile(fp):
        t = open(fp, encoding="utf-8").read()
    else:
        t = ('<?xml version="1.0" encoding="UTF-8"?>\n'
             + DIFF_OPEN + '\n\t<!-- UP7 EVE 舰船制作工具自动维护：装备/舰船列表图标别名 -->\n'
             '\t<add sel="/icons">\n\t</add>\n</diff>\n')
    ent = '\t\t<icon name="%s" texture="%s" height="256" width="256"/>' % (icon_name, texture)
    pat = re.compile(r'<icon\s+name="%s"[^>]*/>' % re.escape(icon_name))
    if pat.search(t):
        t = pat.sub(lambda m: ent, t, count=1)     # lambda：贴图路径含反斜杠，避免 re.sub 解释
    else:
        i = t.rfind("</add>")
        if i < 0:
            return None
        t = t[:i].rstrip() + "\n" + ent + "\n\t" + t[i:]
    open(fp, "w", encoding="utf-8", newline="").write(t)
    return os.path.relpath(fp, mod)

def _remove_mod_icon(mod, icon_name):
    """删除 mod icons.xml 里某图标别名条目。返回修改文件相对路径；无变化返回 None。"""
    fp = _mod_icons_path(mod)
    if not (icon_name and os.path.isfile(fp)):
        return None
    t = open(fp, encoding="utf-8").read()
    nt = re.sub(r'[ \t]*<icon\s+name="%s"[^>]*/>[ \t]*\n' % re.escape(icon_name), '', t)
    nt = re.sub(r"\n(?:[ \t]+\n)+", "\n", nt)
    if nt != t:
        open(fp, "w", encoding="utf-8", newline="").write(nt)
        return os.path.relpath(fp, mod)
    return None

def _icon_alias_source(mod, eid):
    """读 mod icons.xml 里 upgrade_<eid>_macro 当前指向的贴图来源宏名（基名去扩展名）；无返回 ''。"""
    fp = _mod_icons_path(mod) if mod else ""
    if not (fp and os.path.isfile(fp)):
        return ""
    try:
        t = open(fp, encoding="utf-8", errors="ignore").read()
    except Exception:
        return ""
    m = re.search(r'<icon\s+name="upgrade_%s_macro"[^>]*\btexture="([^"]*)"' % re.escape(eid), t)
    if not m:
        return ""
    b = os.path.basename(m.group(1).replace("\\", "/"))
    if "." in b:
        b = b[:b.rfind(".")]
    if b.endswith("_macro"):      # 贴图名带 _macro 后缀，回填统一去后缀（与模板 id 风格一致）
        b = b[:-6]
    return b

def _equip_icon_alias(mod, cls, eid, icon_macro):
    """写该装备列表图标别名 upgrade_<宏>_macro → 贴图（icon_macro 优先，无同名贴图按 class 回退原版）。
    返回修改文件相对路径；无可用贴图返回 None。"""
    tex = _icon_texture_for(icon_macro) or _class_fallback_icon(cls)
    if not tex:
        return None
    return _write_mod_icon(mod, "upgrade_%s_macro" % eid, tex)

# ---------- 舰船列表图标（ship list icon）---------
_SHIP_TEX_DIRS = None
_SHIP_TEX_INDEX = None

def _ship_tex_dirs():
    r"""所有含舰船图标贴图的目录：原版 assets\textures\ui\ships + 各扩展的 ships 目录。"""
    global _SHIP_TEX_DIRS
    if _SHIP_TEX_DIRS is None:
        dirs = []
        v = os.path.join(ROOT, "assets", "textures", "ui", "ships")
        if os.path.isdir(v):
            dirs.append(v)
        ext = os.path.join(ROOT, "extensions")
        if os.path.isdir(ext):
            for m in sorted(os.listdir(ext)):
                for sub in (("assets", "fx", "gui", "textures", "ships"),
                            ("assets", "textures", "ui", "ships")):
                    d = os.path.join(ext, m, *sub)
                    if os.path.isdir(d):
                        dirs.append(d)
        _SHIP_TEX_DIRS = dirs
    return _SHIP_TEX_DIRS

def _ship_tex_index():
    """舰船贴图 base 名（含尾部 _macro）→ 游戏内贴图路径（相对解包根，统一 .tga 扩展）。"""
    global _SHIP_TEX_INDEX
    if _SHIP_TEX_INDEX is None:
        ix = {}
        for d in _ship_tex_dirs():
            rel = os.path.relpath(d, ROOT)
            try:
                files = os.listdir(d)
            except Exception:
                continue
            for f in files:
                low = f.lower()
                if low.endswith(".sig"):
                    continue
                if low.endswith(".gz"):
                    f = f[:-3]
                base = f
                if not base:
                    continue
                for e in (".tga", ".dds", ".png", ".jpg"):
                    if base.lower().endswith(e):
                        base = base[:-len(e)]
                        break
                ix.setdefault(base, os.path.join(rel, base + ".tga").replace("/", "\\"))
        _SHIP_TEX_INDEX = ix
    return _SHIP_TEX_INDEX

def _ship_icon_fallback(shipid):
    """按 ship_<race>_<size> 前缀回退原版贴图；偏好角色关键词，supercarrier 类优先 carrier。
    race 段与 parse_id 同宽（允许数字/下划线，如 up7），非贪婪切分保持一致语义。"""
    m = re.match(r"^ship_([a-z0-9_]+?)_(l|xl)_", shipid)
    if not m:
        return ""
    race, size = m.group(1), m.group(2)
    pref = "ship_%s_%s_" % (race, size)
    ix = _ship_tex_index()
    keys = sorted(k for k in ix if k.startswith(pref))
    if not keys:
        return ""
    # supercarrier 类（nyx/hel/revenant）优先 carrier 贴图
    sc_ids = ("nyx", "hel", "revenant", "avatar")
    is_sc = any(s in shipid for s in sc_ids)
    role_pref = "carrier" if is_sc else None
    # 角色关键词优先级
    role_order = ["carrier", "battleship", "destroyer", "resupplier", "builder",
                  "miner", "trans", "scout", "fighter", "corvette"]
    if role_pref and role_pref not in role_order:
        role_order.insert(0, role_pref)
    for role in role_order:
        for k in keys:
            if role in k and not ix[k].lower().startswith("extensions\\"):
                return ix[k]
    # 无角色匹配时取第一个原版贴图
    for k in keys:
        if not ix[k].lower().startswith("extensions\\"):
            return ix[k]
    return ix[keys[0]] if keys else ""

def _ship_icon_alias(mod, shipid, tpl=None):
    """写舰船列表图标别名 ship_<shipid>_macro → 贴图。
    优先继承模板舰船生效贴图（模型来自模板，贴图必然适配）：模板来源 mod icons.xml 的
    ship_<模板id>_macro 别名 → 贴图索引中模板宏名同名贴图 → 同 race_size 原版贴图兜底。
    返回修改文件相对路径；无可用贴图返回 None。"""
    tex = ""
    if tpl:
        tid = tpl["id"]
        cand = []
        if tpl.get("source") and tpl["source"] != "vanilla":
            cand.append(os.path.join(ROOT, "extensions", tpl["source"], "libraries", "icons.xml"))
        cand.append(_mod_icons_path(mod))
        for p in cand:
            if os.path.isfile(p):
                m = re.search(r'<icon\b[^>]*\bname="ship_%s_macro"[^>]*\btexture="([^"]+)"'
                              % re.escape(tid), open(p, encoding="utf-8", errors="ignore").read())
                if m:
                    tex = m.group(1)
                    break
        tex = tex or _ship_tex_index().get(tid, "")
    tex = tex or _ship_icon_fallback(shipid)
    if not tex:
        return None
    return _write_mod_icon(mod, "ship_%s_macro" % shipid, tex)

def _write_equip_ware(mod, cls, eid, mac_name, d, name_tid, desc_tid, macro_class=None, icon_video=""):
    """写某装备 wares.xml 条目（group/tags/licence 按 class）。返回相对路径或 None。"""
    cost = d.get("cost") or {}
    def cv(v): return (v or "").strip()
    pm, pa, px = cv(cost.get("price_min")), cv(cost.get("price_avg")), cv(cost.get("price_max"))
    if not (pm and pa and px):
        pm, pa, px = 1000, 1200, 1400
    pt = cv(cost.get("time")) or "10"
    prod_list = cost.get("production") or []
    if prod_list:
        prods = "\n".join(_prod_seg(m.get("method") or "default", m.get("time") or pt, m.get("materials") or [])
                          for m in prod_list)
    else:
        mats = cost.get("materials") or []
        if not mats:
            mats = [{"ware": "energycells", "amount": "20"},
                    {"ware": "turretcomponents", "amount": "5"}]
        prods = _prod_seg("default", pt, mats)
    lic = EQUIP_CLASSES[cls]["lic"]
    extra = ('\t\t<restriction licence="%s"/>' % lic) if lic else \
            '\t\t<container ref="sm_gen_pickup_equipment_01_macro"/>'
    if cls == "missile":
        # 导弹是弹药，作为发射塔的补给，不走装备贸易/蓝图系统：无 owner（对齐原版导弹 ware）
        owners = ""
    else:
        owner = d.get("owner") or RACE_FACTION.get(d.get("race") or "", "argon")
        owners = "\n".join('\t\t<owner faction="%s"/>' % o for o in str(owner).split(",") if o)
    tg = EQUIP_CLASSES[cls]["tg"]
    # 导弹发射器（macro class=missilelauncher）需 missilelauncher 标签，否则舰船挂点匹配失败
    if macro_class == "missilelauncher" and "missilelauncher" not in tg:
        tg = tg + " missilelauncher"
    icon_ln = ('\t\t\t<icon video="%s"/>\n' % icon_video) if icon_video else ""
    wx = ('\t\t<ware id="%s" name="{7777771,%d}" description="{7777771,%d}" group="%s" transport="equipment" volume="1" tags="%s">\n'
          '\t\t\t<price min="%d" average="%d" max="%d"/>\n'
          '%s\n'
          '\t\t\t<component ref="%s_macro"/>\n'
          '%s'
          '\t\t\t<use threshold="0"/>\n'
          '%s\n%s\n\t\t</ware>') % (eid, name_tid, desc_tid, EQUIP_CLASSES[cls]["grp"], tg,
                                    int(pm), int(pa), int(px), prods, eid, icon_ln, extra, owners)
    jp = os.path.join(mod, "libraries", "wares.xml")
    if not os.path.isfile(jp):
        return None
    txt = open(jp, encoding="utf-8").read()
    pat = re.compile(r'<ware\s+id="%s"[^>]*>.*?</ware>' % re.escape(eid), re.S)
    new = re.sub(pat, wx, txt, count=1)
    if new != txt:
        open(jp, "w", encoding="utf-8").write(new)
        return os.path.relpath(jp, mod)
    i = txt.rfind("</add>")
    if i < 0:
        return None
    txt = txt[:i].rstrip() + "\n" + wx + "\n\t\t" + txt[i:]
    open(jp, "w", encoding="utf-8").write(txt)
    return os.path.relpath(jp, mod)

def _rewrite_ident_tids(mtxt, name_tid, desc_tid, count=1):
    """把 macro identification 的 name/basename/shortname/description t 引用统一改到 7777771 专属页。
    新建与编辑保存共用：不改则加载仍读原版页，表现为"改名不生效"。"""
    def _rep(mm):
        tag = mm.group(0)
        tag = re.sub(r'\bname="\{[^"]*\}"', 'name="{7777771,%d}"' % name_tid, tag)
        tag = re.sub(r'\bbasename="\{[^"]*\}"', 'basename="{7777771,%d}"' % name_tid, tag)
        tag = re.sub(r'\bshortname="\{[^"]*\}"', 'shortname="{7777771,%d}"' % name_tid, tag)
        tag = re.sub(r'\bdescription="\{[^"]*\}"', 'description="{7777771,%d}"' % desc_tid, tag)
        return tag
    return re.sub(r'<identification\b[^>]*>', _rep, mtxt, count=count)

def _read_equip_tids(it):
    """读装备 macro identification name/description 的工具专属 t 引用 {7777771,id}。
    仅认 7777771 专属页，原版共享页引用不算，避免误改共享文本。返回 (name_tid, desc_tid)。"""
    try:
        mtxt = open(it["path"], encoding="utf-8", errors="ignore").read()
    except Exception:
        return (None, None)
    m = re.search(r"<identification\b([^>]*)>", mtxt)
    if not m:
        return (None, None)
    def tidof(attr):
        mm = re.search(r'%s="\{7777771\s*,\s*(\d+)\}"' % attr, m.group(1))
        return int(mm.group(1)) if mm else None
    return (tidof("name"), tidof("description"))

def _resolve_tids(it, mod):
    """修改模式复用已有专属 tid（只更新不新增条目）；无则分配新 id。"""
    nt, dt = _read_equip_tids(it)
    if nt is not None and dt is not None:
        return nt, dt
    a, b = _alloc_tids(mod)
    if nt is None:
        nt = a
    if dt is None:
        dt = b
    return nt, dt

def _write_equip_txt(mod, eid, d, name_tid, desc_tid):
    modi = []
    name_zh = d.get("name_zh") or (d.get("name_en") or eid).title()
    name_en = d.get("name_en") or eid
    desc_zh = d.get("desc_zh") or ("%s 装备" % name_zh)
    desc_en = d.get("desc_en") or ("%s equipment" % name_en)
    zh_p, en_p = _loc_files(mod)
    for tp, n, de in ((zh_p, name_zh, desc_zh), (en_p, name_en, desc_en)):
        if not tp:
            continue
        txt = open(tp, encoding="utf-8").read()
        j = txt.find('<page id="7777771"')
        if j < 0:
            continue
        k = txt.find("</page>", j)
        pg = txt[j:k]
        for tid, val in ((name_tid, n), (desc_tid, de)):
            # 用户文本必须 XML 转义（& < >），否则写入 t 文件成非法 XML；
            # 替换串用 lambda 绕开 re.sub 对反斜杠的解释（否则文本含 \ 时保存直接失败）
            val_esc = val.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            pat = r'<t id="%d">[^<]*</t>' % tid
            if re.search(pat, pg):
                pg = re.sub(pat, lambda m: '<t id="%d">%s</t>' % (tid, val_esc), pg)
            else:
                pg = pg.rstrip() + '\n\t\t\t<t id="%d">%s</t>' % (tid, val_esc)
        txt = txt[:j] + pg + txt[k:]
        open(tp, "w", encoding="utf-8").write(txt)
        modi.append(os.path.relpath(tp, mod))
    if modi:
        # 语言表缓存失效：新增/改名装备后，让回填能解析到新写的 t id
        try:
            LX._loc.clear()
        except Exception:
            pass
    return modi

def _register_index(mod, items):
    """把新资产追加注册到 mod/index/<kind>.xml（kind=macros/components）。
    items: [(kind, entry_name, relpath_without_ext)]，value 用反斜杠路径。"""
    modi = []
    for kind, name, rel in items:
        fp = os.path.join(mod, "index", kind + ".xml")
        if not os.path.isfile(fp):
            continue
        t = open(fp, encoding="utf-8").read()
        t = re.sub(r'<entry name="%s"[^>]*/>' % re.escape(name), '', t)
        t = re.sub(r"\n(?:[ \t]+\n)+", "\n", t)   # 收尾：压掉清旧条目留下的纯空白孤儿行
        i = t.rfind("</add>")
        if i < 0:
            continue
        val = "extensions\\%s\\%s" % (os.path.basename(mod), rel.replace("/", "\\"))
        t = t[:i].rstrip() + "\n\t\t\t" + '<entry name="%s" value="%s"/>' % (name, val) + t[i:]
        open(fp, "w", encoding="utf-8").write(t)
        try:
            modi.append(os.path.relpath(fp, mod))
        except ValueError:
            modi.append(fp)
    return modi

def _register_equip(mod, cls, eid, rel):
    """注册 index/macros.xml + components.xml。rel = 相对 props 的目录（如 WeaponSystems/standard）。"""
    modi = []
    mac_val = "extensions\\%s\\assets\\props\\%s\\macros\\%s_macro" % (os.path.basename(mod), rel.replace("/", "\\"), eid)
    comp_val = "extensions\\%s\\assets\\props\\%s\\%s" % (os.path.basename(mod), rel.replace("/", "\\"), eid)
    im = os.path.join(mod, "index", "macros.xml")
    ic = os.path.join(mod, "index", "components.xml")
    if os.path.isfile(im):
        t = open(im, encoding="utf-8").read()
        t = re.sub(r'<entry name="%s_macro"[^>]*/>' % re.escape(eid), '', t)
        t = re.sub(r"\n(?:[ \t]+\n)+", "\n", t)   # 收尾：压掉清旧条目留下的纯空白孤儿行
        i = t.rfind("</add>")
        if i >= 0:
            t = t[:i].rstrip() + '\n\t\t\t<entry name="%s_macro" value="%s"/>' % (eid, mac_val) + t[i:]
            open(im, "w", encoding="utf-8").write(t)
            modi.append(os.path.relpath(im, mod))
    if os.path.isfile(ic):
        t0 = open(ic, encoding="utf-8").read()
        t = re.sub(r'<entry name="%s"[^>]*/>' % re.escape(eid), '', t0)
        t = re.sub(r"\n(?:[ \t]+\n)+", "\n", t)   # 收尾：压掉清旧条目留下的纯空白孤儿行
        # 组件文件确实落盘才注册 components 条目（引用原版/DLC 模型且未填自定义 tags 时不落组件文件），避免悬空引用
        if os.path.isfile(os.path.join(mod, "assets", "props", rel, eid + ".xml")):
            i = t.rfind("</add>")
            if i >= 0:
                t = t[:i].rstrip() + '\n\t\t\t<entry name="%s" value="%s"/>' % (eid, comp_val) + t[i:]
        if t != t0:
            open(ic, "w", encoding="utf-8").write(t)
            modi.append(os.path.relpath(ic, mod))
    return modi

def _shield_visual(comp):
    """读护盾组件视觉：材质引用（material ref，hulltexture/fx/涂装等）+ 动画部件（animations）。
    返回 {materials:[{id,ref}（id 保留首个 ref）], anims:[{conn,anim,start,end}]}。"""
    mat, anims = {}, []
    try:
        ct = _read_comp_txt(comp)
    except Exception:
        return {"materials": [], "anims": []}
    for m in re.finditer(r'<material\s+id="(\d+)"\s+ref="([^"]*)"', ct):
        mat.setdefault(m.group(1), m.group(2))
    for cm in re.finditer(r'<connection\s+name="([^"]*)"\s+[^>]*?[^/]>(.*?)</connection>', ct, re.S):
        am = re.search(r'<animation\s+name="([^"]*)"\s+start="([^"]*)"\s+end="([^"]*)"', cm.group(2))
        if am:
            anims.append({"conn": cm.group(1), "anim": am.group(1), "start": am.group(2), "end": am.group(3)})
    return {"materials": [{"id": k, "ref": v} for k, v in mat.items()], "anims": anims}


def _apply_shield_visual(ctxt, vis):
    """把护盾组件视觉写回组件文本：material ref 按 id 全局替换；animation start/end 按 connection 定位替换。"""
    for it in (vis.get("materials") or []):
        mid = str(it.get("id") or "").strip()
        ref = (it.get("ref") or "").strip()
        if not mid:
            continue
        pat = r'(<material\s+id="%s"\s+ref=")[^"]*(")' % re.escape(mid)
        if ref:
            ctxt = re.sub(pat, r'\g<1>%s\g<2>' % ref, ctxt)
    for a in (vis.get("anims") or []):
        conn = (a.get("conn") or "").strip()
        if not conn:
            continue
        start, end = (a.get("start") or "").strip(), (a.get("end") or "").strip()
        if not start and not end:
            continue
        def _block(m):
            block = m.group(0)
            def _anim(m2):
                s2 = m2.group(0)
                if start:
                    s2 = re.sub(r'\bstart="[^"]*"', 'start="%s"' % start, s2, count=1)
                if end:
                    s2 = re.sub(r'\bend="[^"]*"', 'end="%s"' % end, s2, count=1)
                return s2
            return re.sub(r'<animation\b[^>]*>', _anim, block, count=1)
        ctxt = re.sub(r'<connection\s+name="%s"\s+[^>]*?[^/]>.*?</connection>' % re.escape(conn), _block, ctxt, flags=re.S)
    return ctxt


_MATREF_CACHE = None
def _build_material_refs():
    """扫描原版+DLC+mod props 装备组件（SurfaceElements/Engines/WeaponSystems 顶层 .xml）的 material ref，去重计数。"""
    refs = {}
    def walk(base):
        for sub in ("SurfaceElements", "Engines", "WeaponSystems"):
            d = os.path.join(base, sub)
            if not os.path.isdir(d):
                continue
            for fn in os.listdir(d):
                if not fn.endswith(".xml"):
                    continue
                p = os.path.join(d, fn)
                try:
                    c = open(p, encoding="utf-8", errors="ignore").read()
                except Exception:
                    continue
                for m in re.finditer(r'<material\s+id="\d+"\s+ref="([^"]*)"', c):
                    refs[m.group(1)] = refs.get(m.group(1), 0) + 1
    walk(os.path.join(ROOT, "assets", "props"))
    for m in _ext_order():
        walk(os.path.join(ROOT, "extensions", m, "assets", "props"))
    return sorted([{"ref": k, "count": v} for k, v in refs.items()], key=lambda x: -x["count"])

def _material_refs_all():
    """护盾材质引用「同类参考」数据源：内存 + 磁盘双层缓存（props 装备组件签名校验）。"""
    global _MATREF_CACHE
    if _MATREF_CACHE is None:
        roots = [os.path.join(ROOT, "assets", "props")] + \
                [os.path.join(ROOT, "extensions", m, "assets", "props") for m in _ext_order()]
        _MATREF_CACHE = _cached_whole("matrefs.json", roots, _build_material_refs,
                                      only_dirs={"SurfaceElements", "Engines", "WeaponSystems"})
    return _MATREF_CACHE


def equip_read(cls, eid, source="", mod=""):
    if cls not in EQUIP_CLASSES:
        return {"ok": False, "error": "未知装备类型"}
    if cls == "bullet":
        it = next((x for x in bullet_scan().values() if x["id"] == eid), None)
        if it and source:
            _bd = (_BULLET_DUP_CACHE or {}).get(eid) or []
            _bb = next((x for x in _bd if x["source"] == source), None)
            if _bb:
                it = _bb
    else:
        it = (equip_scan().get(cls) or {}).get(eid)
        if it and source:
            _ed = (_EQ_DUP_CACHE or {}).get(cls, {}).get(eid) or []
            _ee = next((x for x in _ed if x["source"] == source), None)
            if _ee:
                it = _ee
    if not it:
        return {"ok": False, "error": "未找到装备 %s" % eid}
    try:
        mtxt = open(it["path"], encoding="utf-8", errors="ignore").read()
    except Exception as e:
        return {"ok": False, "error": "读取失败: %s" % e}
    ident = {}
    m = re.search(r'<identification\b([^>]*)>', mtxt)
    if m:
        for k in ("name", "basename", "shortname", "makerrace", "mk"):
            mm = re.search(r'%s="([^"]*)"' % k, m.group(1))
            raw = mm.group(1) if mm else ""
            if k in ("name", "basename", "shortname") and "{" in raw:
                # name 可能是 t 文本引用 {page,id}，解析成英文文本，避免前端显示编码
                ident[k] = LX.lname(raw, "", "en") or raw
            else:
                ident[k] = raw
            if k == "name":
                ident["name_zh"] = LX.lname(raw, "", "zh") or ""
    fields = _read_equip_fields(cls, mtxt)
    # 从对应 ware 读成本
    cost = {"price_min": "", "price_avg": "", "price_max": "", "time": "", "materials": []}
    owner = ""
    wm = _find_ware_in(source, eid)   # 忠实该来源自己的 wares.xml（不做跨来源覆盖拼接）
    w = wm.group(2) if wm else None   # group(2)=ware 正文
    if w:
        pm = re.search(r'<price min="([^"]*)" average="([^"]*)" max="([^"]*)"', w)
        if pm:
            cost["price_min"], cost["price_avg"], cost["price_max"] = pm.group(1), pm.group(2), pm.group(3)
        pt = re.search(r'<production time="([^"]*)"', w)
        if pt:
            cost["time"] = pt.group(1)
        # 读取全部建造方式（production method）段：每种方式一段资源
        cost["production"] = []
        for p in re.finditer(r'<production\b[^>]*>(.*?)</production>', w, re.S):
            mth = re.search(r'\bmethod="([^"]*)"', p.group(0))
            pt2 = re.search(r'\btime="([^"]*)"', p.group(0))
            cost["production"].append({
                "method": mth.group(1) if mth else "default",
                "time": pt2.group(1) if pt2 else "",
                "materials": [{"ware": m.group(1), "amount": m.group(2)}
                              for m in re.finditer(r'<ware ware="([^"]*)" amount="([^"]*)"', p.group(1))]
            })
        if cost["production"]:
            cost["time"] = cost["production"][0]["time"]
        owner = ",".join(m.group(1) for m in re.finditer(r'<owner faction="([^"]+)"', w))
    model = ""
    # 引用模型 = 组件 <source geometry> 解析的真实几何 id；component ref 物品 id 单独返回
    ref = _read_macro_ref(it["path"])
    comp = _equip_component(it["path"], ref) if ref else None
    if not comp and ref:
        comp = _find_comp_global(ref)   # 组件可能在原版/其他 mod，跨资产树兜底
    conn_tags, conn_name = "", ""
    if comp:
        geo = _comp_geometry_id(comp)
        if not geo and cls == "shield":
            # 护盾宏可能 ref 虚拟组件(无模型)；回退用宏同名实体组件读几何（本地缺则跨资产树）
            _mac_name = os.path.basename(it["path"])[:-len("_macro.xml")]
            _scomp = os.path.join(os.path.dirname(os.path.dirname(it["path"])), _mac_name + ".xml")
            if not os.path.isfile(_scomp):
                _scomp = _find_comp_global(_mac_name)
            if _scomp and os.path.isfile(_scomp):
                comp = _scomp
                geo = _comp_geometry_id(_scomp)
        model = geo or ref or ""
        if cls != "bullet":
            conn_name, conn_tags = _mount_conn(comp, ("turret", "missileturret", "weapon", "shield", "missile", "engine"))
    elif ref:
        model = ref
    mc = re.search(r'<macro\b[^>]*\bclass="([^"]*)"', mtxt)
    mt_class = mc.group(1) if mc else ""
    trail_name, trail_type = "", ""
    explosion_ref = ""
    _ex = re.search(r'<explosion\s+ref="([^"]*)"', mtxt)
    if _ex:
        explosion_ref = _ex.group(1)
    if comp:
        try:
            _ct = _read_comp_txt(comp)
        except Exception:
            _ct = ""
        te = re.search(r'<trailemitters>(.*?)</trailemitters>', _ct, re.S)
        if te:
            em = re.search(r'<emitter\b([^>]*)>', te.group(1))
            if em:
                nm = re.search(r'\bname="([^"]*)"', em.group(1))
                tn = re.search(r'\btype="([^"]*)"', em.group(1))
                trail_name = nm.group(1) if nm else ""
                trail_type = tn.group(1) if tn else ""
    visual = {"materials": [], "anims": []}
    if cls == "shield" and comp and os.path.isfile(comp):
        visual = _shield_visual(comp)
    # 列表图标来源（本工具写入 icons.xml 的别名，供前端回填/编辑）；无别名时回填自身宏 id。
    # 百科动图：ware <icon video> 当前值。
    fields["icon_src"] = (_icon_alias_source(os.path.normpath(mod), eid) if mod else "") or eid
    _vid = ""
    if w:
        _vm = re.search(r'<icon\s+video="([^"]*)"', w)
        if _vm:
            _vid = _vm.group(1)
    fields["icon_video"] = _vid
    return {"ok": True, "cls": cls, "id": eid, "source": it["source"],
            "meta": _eq_meta(cls, eid), "ident": ident, "fields": fields, "cost": cost,
            "ref": ref, "model": model, "conn_tags": conn_tags, "conn_name": conn_name, "owner": owner,
            "trail_name": trail_name, "trail_type": trail_type, "explosion_ref": explosion_ref,
            "mt_class": mt_class, "visual": visual}

def _copy_dir_rename(src, dst, old, new):
    """递归复制 data 目录，并把目录内：子文件夹名、文件名、文件内容里所有 old→new 全部改名。
    顺序：先改内容（旧名仍可读），再改文件名/文件夹名；XML 解析失败时内容仍用文本替换兜底。"""
    shutil.copytree(src, dst, dirs_exist_ok=True)
    _disable_jcs(dst)   # 复制副本的 .jcs 会令游戏崩溃，统一加 .disabled（实测结论）
    for r, dirs, files in os.walk(dst, topdown=False):
        for f in files:
            fp = os.path.join(r, f)
            try:
                c = open(fp, "rb").read()
                if old.encode("utf-8") in c:
                    open(fp, "wb").write(c.replace(old.encode("utf-8"), new.encode("utf-8")))
            except Exception:
                pass
        for d in dirs:
            dp = os.path.join(r, d)
            if old in d:
                os.rename(dp, os.path.join(r, d.replace(old, new)))
        for f in files:
            fp = os.path.join(r, f)
            if old in f:
                os.rename(fp, os.path.join(r, f.replace(old, new)))
    return dst

# diff 操作块解析（属性顺序无关；兼容自闭合 <remove .../> 与带内容的 <add>/<replace>）
_DIFF_OP_RE = re.compile(
    r'<(add|replace|remove)\b([^>]*?)(?:/>|>(.*?)</\1\s*>)',
    re.S)

def _sel_target(sel):
    """从 sel XPath 提取末段元素名与 @name 谓词。返回 (elem, name or None)。
    支持 '.../connection[@name=\'X\']' 与 '.../connections' 两类；其余复杂 XPath 返回 None。"""
    last = sel.rstrip('/').rsplit('/', 1)[-1]
    m = re.match(r'^([\w:-]+)(?:\[@name=\'([^\']*)\'\])?$', last)
    if not m:
        return None, None
    return m.group(1), m.group(2)

def _node_re(elem, name=None):
    """构造匹配指定元素节点（带 name 谓词则精确定位）的正则。"""
    if name is not None:
        return (r'<%s\b[^>]*\bname="%s"[^>]*(?:/>|>.*?</%s\s*>)'
                % (re.escape(elem), re.escape(name), re.escape(elem)))
    return r'<%s\b[^>]*(?:/>|>.*?</%s\s*>)' % (re.escape(elem), re.escape(elem))

def _apply_diff_ops(base_txt, diff_txt):
    """把 <diff> 补丁的 add/replace/remove 指令按游戏语义合并到 base 文本。
    - replace sel：替换 sel 选中的唯一节点（按 @name 或元素名正则）
    - add sel + pos：默认 append 为 sel 节点的最后子节点；pos=prepend 为首个子节点；
      pos=before 作为前驱兄弟节点；type="@attr" 向 sel 节点追加属性
    - remove sel：删除选中节点（ws="after" 顺带清掉后续空白）
    sel 仅解析末段（元素名 + 可选 [@name='X']），复杂 XPath 跳过该条。
    装备组件与舰船组件（挂载点同为 connection）及库文件共用。"""
    for m in _DIFF_OP_RE.finditer(diff_txt):
        op, attrs, body = m.group(1), m.group(2), (m.group(3) or "")
        sm = re.search(r'\bsel="([^"]*)"', attrs)
        if not sm:
            continue
        sel = sm.group(1)
        elem, name = _sel_target(sel)
        if not elem:
            continue
        body = body.strip()
        if op == "replace":
            base_txt = re.sub(_node_re(elem, name), lambda _: body, base_txt, count=1, flags=re.S)
        elif op == "remove":
            pat = _node_re(elem, name)
            if re.search(r'\bws="after"', attrs):
                pat += r'[ \t]*(?:\r?\n)?'
            base_txt = re.sub(pat, '', base_txt, count=1, flags=re.S)
        elif op == "add":
            tm = re.search(r'\btype="(@[\w:-]+)"', attrs)
            pm = re.search(r'\bpos="(before|prepend)"', attrs)
            if tm:
                # 向目标节点开标签追加属性：name="value"
                attr = tm.group(1)[1:]
                def _addattr(mm, attr=attr, val=body):
                    tag = mm.group(0)
                    i = tag.find('>')
                    if tag[i-1] == '/':
                        return tag[:i-1].rstrip() + ' %s="%s"/>' % (attr, val)
                    return tag[:i].rstrip() + ' %s="%s">' % (attr, val) + tag[i+1:]
                base_txt = re.sub(_node_re(elem, name), _addattr, base_txt, count=1, flags=re.S)
            elif pm and pm.group(1) == "before":
                base_txt = re.sub(_node_re(elem, name), lambda mm: body + "\n" + mm.group(0),
                                  base_txt, count=1, flags=re.S)
            elif pm and pm.group(1) == "prepend":
                # 作为首子节点：插到开标签之后
                def _prepend(mm, body=body):
                    g = mm.group(0)
                    i = g.find('>')
                    return g[:i+1] + "\n" + body + g[i+1:]
                base_txt = re.sub(_node_re(elem, name), _prepend, base_txt, count=1, flags=re.S)
            else:
                # 默认 append 为末子节点：插到闭标签之前
                def _append(mm, body=body, elem=elem):
                    g = mm.group(0)
                    close = '</%s>' % elem
                    i = g.rfind(close)
                    if i < 0:
                        return g  # 自闭合容器无法 append，跳过
                    return g[:i].rstrip() + "\n" + body + "\n" + " " * 0 + g[i:]
                base_txt = re.sub(_node_re(elem, name), _append, base_txt, count=1, flags=re.S)
    return base_txt

# 兼容旧名（读取合并入口均改调 _apply_diff_ops 的全操作版）
_apply_diff_replaces = _apply_diff_ops

def _apply_diff_to_base(src_comp, diff_text):
    """模板组件是 diff 格式（对原版的补丁）时，定位原版 base 组件并应用 diff，返回完整组件文本。
    背景：vro 等 mod 的装备组件常以 <diff><replace sel="//.../connection[@name='X']"> 形式覆盖原版的连接 tags；
    若直接复制 diff 文件作为 mod 独立组件，游戏会报 "key name diff is not recognized" 加载失败。
    找不到 base 时返回 None。"""
    src_id = os.path.basename(src_comp)[:-4]
    base = _find_comp_global(src_id)
    if not base or not os.path.isfile(base):
        return None
    if os.path.normpath(base) == os.path.normpath(src_comp):
        return None   # 全局索引命中的就是 diff 文件自身（原版不在树中），无 base 可应用
    base_txt = open(base, encoding="utf-8", errors="ignore").read()
    if _is_diff_txt(base_txt):
        return None   # base 也是 diff（链式补丁），本函数只处理单层
    return _apply_diff_replaces(base_txt, diff_text)


# ── diff 离线校验（o3）────────────────────────────────────────────
def _diff_base_for(comp_path):
    """定位 diff 组件在加载序中的 base：加载序中当前来源之前的最近同名完整组件。
    与 _apply_diff_to_base 同语义，但返回 (base 路径, base 文本) 供校验/预览使用。"""
    src_id = os.path.basename(comp_path)[:-4]
    fn = src_id + ".xml"
    src_norm = os.path.normpath(comp_path)
    # 加载序 roots：vanilla → 官方DLC → 用户mod（_ext_order 序）
    roots = [os.path.join(ROOT, "assets")]
    for m in _ext_order():
        roots.append(os.path.join(ROOT, "extensions", m, "assets"))
    for base in roots:
        p = _dir_index(base).get(fn)
        if p and os.path.isfile(p) and os.path.normpath(p) != src_norm:
            txt = open(p, encoding="utf-8", errors="ignore").read()
            if not _is_diff_txt(txt):
                return p, txt
    return None, None


def validate_diff(diff_txt, base_txt):
    """离线校验 diff 补丁：XML 良构、sel 唯一性/存在性、合并结果良构。
    返回 {"ok": bool, "errors": [...], "warnings": [...]}"""
    import xml.etree.ElementTree as ET
    errors, warnings = [], []
    # 1. diff XML 良构
    try:
        diff_root = ET.fromstring(diff_txt)
    except ET.ParseError as e:
        errors.append("diff XML 解析失败: %s" % e)
        return {"ok": False, "errors": errors, "warnings": warnings}
    if diff_root.tag != "diff":
        warnings.append("diff 根节点不是 <diff>，而是 <%s>" % diff_root.tag)
    # 2. sel 唯一性 + 存在性 + XSD 枚举校验
    xsd_pos = {e for e in _xsd_schema("diff").get("pos", {}).get("enums", [])}
    xsd_type = _xsd_schema("diff").get("type", {})
    seen = set()
    for m in _DIFF_OP_RE.finditer(diff_txt):
        op, attrs = m.group(1), m.group(2)
        sm = re.search(r'\bsel="([^"]*)"', attrs)
        if not sm:
            errors.append("<%s> 缺少 sel 属性" % op)
            continue
        sel = sm.group(1)
        if sel in seen:
            errors.append("sel 重复: %s" % sel)
        seen.add(sel)
        elem, name = _sel_target(sel)
        if not elem:
            warnings.append("sel 无法解析末段元素（复杂 XPath）: %s" % sel)
            continue
        pat = _node_re(elem, name)
        if not re.search(pat, base_txt, flags=re.S):
            errors.append("sel 在 base 中无匹配: %s" % sel)
        # XSD 枚举校验：pos 值必须在 diff.xsd 定义的枚举内
        pm = re.search(r'\bpos="([^"]*)"', attrs)
        if pm and xsd_pos and pm.group(1) not in xsd_pos:
            errors.append("pos 值不在 XSD 枚举内: %s（允许: %s）" % (pm.group(1), ", ".join(sorted(xsd_pos))))
        # type 值必须是 @attr 格式（@ 开头）
        tm = re.search(r'\btype="([^"]*)"', attrs)
        if tm and not tm.group(1).startswith("@"):
            errors.append("type 值必须是 @attr 格式（@ 开头）: %s" % tm.group(1))
    # 3. 合并结果良构
    try:
        merged = _apply_diff_ops(base_txt, diff_txt)
        ET.fromstring(merged)
    except ET.ParseError as e:
        errors.append("合并后 XML 解析失败: %s" % e)
    except Exception as e:
        errors.append("合并过程异常: %s" % e)
    return {"ok": len(errors) == 0, "errors": errors, "warnings": warnings}


# ── XSD 动态解析（o4）──────────────────────────────────────────────
_XSD_CACHE = {}

def _xsd_schema(name):
    """解析指定 XSD 文件（优先原版 libraries/，extensions 中后加载者覆盖），
    提取 simpleType 的枚举值与 annotation 文档，返回 {type_name: {"enums":[...], "doc":"..."}}。
    结果缓存于 _XSD_CACHE，服务生命周期内只解析一次。"""
    if name in _XSD_CACHE:
        return _XSD_CACHE[name]
    import xml.etree.ElementTree as ET
    ns = {"xs": "http://www.w3.org/2001/XMLSchema"}
    result = {}
    # 加载序：原版 -> extensions（_ext_order 序），后加载者覆盖同名 type
    roots = [os.path.join(ROOT, "libraries", name + ".xsd")]
    for m in _ext_order():
        roots.append(os.path.join(ROOT, "extensions", m, "libraries", name + ".xsd"))
    for fp in roots:
        if not os.path.isfile(fp):
            continue
        try:
            tree = ET.parse(fp)
        except ET.ParseError:
            continue
        for st in tree.iter("{http://www.w3.org/2001/XMLSchema}simpleType"):
            tname = st.get("name")
            if not tname:
                continue
            doc = ""
            ann = st.find("xs:annotation/xs:documentation", ns)
            if ann is not None and ann.text:
                doc = ann.text.strip()
            enums = []
            for en in st.iter("{http://www.w3.org/2001/XMLSchema}enumeration"):
                v = en.get("value")
                if v is not None:
                    enums.append(v)
            result[tname] = {"enums": enums, "doc": doc}
    _XSD_CACHE[name] = result
    return result


def _all_xsd_schemas():
    """聚合原版+extensions 所有 libraries/*.xsd 的 type 定义，供 /api/schemas 返回。"""
    import xml.etree.ElementTree as ET
    ns = {"xs": "http://www.w3.org/2001/XMLSchema"}
    result = {}
    # 收集所有存在的 xsd 文件路径（按加载序）
    paths = [os.path.join(ROOT, "libraries", f)
             for f in os.listdir(os.path.join(ROOT, "libraries"))
             if f.endswith(".xsd")]
    for m in _ext_order():
        ext_lib = os.path.join(ROOT, "extensions", m, "libraries")
        if os.path.isdir(ext_lib):
            for f in os.listdir(ext_lib):
                if f.endswith(".xsd"):
                    paths.append(os.path.join(ext_lib, f))
    for fp in paths:
        try:
            tree = ET.parse(fp)
        except ET.ParseError:
            continue
        sf = os.path.basename(fp)[:-4]
        for st in tree.iter("{http://www.w3.org/2001/XMLSchema}simpleType"):
            tname = st.get("name")
            if not tname:
                continue
            enums = []
            for en in st.iter("{http://www.w3.org/2001/XMLSchema}enumeration"):
                v = en.get("value")
                if v is not None:
                    enums.append(v)
            if enums:
                result.setdefault(sf, {})[tname] = enums
    return result


def _copy_rename_asset(src_comp_dir, src_id, dst_comp_dir, new_id, conn_tags="", conn_name=""):
    """整套复制一个装备资产并彻底改名：component + _data 目录 + _data.ani。
    - 组件内容 src_id→new_id 全局替换（文本替换覆盖 text+attrib，天然无解析失败）
    - data 目录内子文件夹名/文件名/文件内容全部 src_id→new_id
    - 可选写入自定义挂载 tags
    返回 (created 绝对路径列表, 是否复制了自有组件)。"""
    created, copied = [], False
    src_comp = os.path.join(src_comp_dir, src_id + ".xml")
    if os.path.isfile(src_comp):
        ctxt = open(src_comp, encoding="utf-8", errors="ignore").read()
        # 模板组件是 diff 格式（如 vro 的补丁）时，不能直接复制——mod 独立组件必须是完整 <components>。
        # 应用 diff 到原版 base 组件，得到完整文本后再改名。
        if _is_diff_txt(ctxt):
            applied = _apply_diff_to_base(src_comp, ctxt)
            if applied:
                ctxt = applied
            else:
                return created, False   # 找不到 base 组件，放弃自有组件，回退复用原版 ref
        # data 目录先于组件写入复制：成功 → geometry 随全局改名指向新目录；
        # 缺失/失败 → geometry 回退指向模板数据目录（共享），避免悬空引用导致碰撞网格无效。
        src_data = os.path.join(src_comp_dir, src_id + "_data")
        data_ready = False
        if os.path.isdir(src_data):
            try:
                created.append(_copy_dir_rename(src_data, os.path.join(dst_comp_dir, new_id + "_data"), src_id, new_id))
                data_ready = True
            except (OSError, shutil.Error):
                pass
        if src_id in ctxt:
            ctxt = ctxt.replace(src_id, new_id)
            if not data_ready:
                ctxt = ctxt.replace(new_id + "_data", src_id + "_data")
        if data_ready:
            # 几何归属统一为目标 mod 显式路径：src 可能是其他 mod 的 extensions\ 路径或 assets\ 裸路径，
            # 全局改名后会指向 src 侧不存在的新名目录 / 引擎不解析的裸路径 → meshsource 拒载（x150 同类坑）。
            m = re.match(r'(.*?)[/\\]assets[/\\](.*)$', dst_comp_dir)
            if m:
                geo = "extensions\\%s\\assets\\%s\\%s_data" % (
                    os.path.basename(m.group(1)), m.group(2).replace("/", "\\"), new_id)
                ctxt = re.sub(r'geometry="[^"]*"', 'geometry="%s"' % geo, ctxt)
        if conn_tags:
            ctxt = _set_mount_tags(ctxt, conn_tags, conn_name)
        os.makedirs(dst_comp_dir, exist_ok=True)
        dp = os.path.join(dst_comp_dir, new_id + ".xml")
        open(dp, "w", encoding="utf-8").write(ctxt)
        created.append(dp); copied = True
        src_ani = os.path.join(src_comp_dir, src_id + "_data.ani")
        if os.path.isfile(src_ani):
            adp = os.path.join(dst_comp_dir, new_id + "_data.ani")
            shutil.copy2(src_ani, adp); created.append(adp)
    return created, copied

def _resolve_eq_ref(cls, ref):
    """引用模型按 component ref 物品 id 解析。scan 的 key 是宏 id，这里优先按宏 id、再按 ref 匹配。
    返回 (物品id, 承载该物品的宏项)；找不到返回 None。"""
    if not ref:
        return None
    s = equip_scan().get(cls) or {}
    if ref in s:
        return ref, s[ref]
    for hid, x in s.items():
        if x.get("ref") == ref:
            return ref, x
    return None

def equip_generate(d):
    cls = d.get("cls")
    if cls not in EQUIP_CLASSES:
        return {"ok": False, "error": "未知装备类型"}
    new_id = (d.get("new_id") or "").strip().lower()
    if not re.match(r'^[a-z][a-z0-9_]*$', new_id):
        return {"ok": False, "error": "装备 ID 格式错误，应用小写字母/数字/下划线，如 shield_arg_xl_01_mk1"}
    tpl_raw = (d.get("template") or "")
    _ti = tpl_raw.rfind("@@")
    tpl_id = tpl_raw[:_ti] if _ti > 0 else tpl_raw
    tpl_src = tpl_raw[_ti + 2:] if _ti > 0 else ""
    tpl = next((t for t in equip_templates(cls) if t["id"] == tpl_id and (not tpl_src or t["source"] == tpl_src)), None)
    if not tpl:
        return {"ok": False, "error": "请选择模板装备"}
    mod = os.path.normpath(d.get("target_mod") or MOD_DIR)
    # 模板源目录（按所选来源定位宏，多来源时读对应来源文件）
    src_mac = None
    if tpl_src:
        for _x in (_EQ_DUP_CACHE or {}).get(cls, {}).get(tpl_id, []):
            if _x["source"] == tpl_src:
                src_mac = _x["path"]; break
    if not src_mac:
        src_mac = (equip_scan().get(cls) or {}).get(tpl_id, {}).get("path")
    if not src_mac:
        return {"ok": False, "error": "模板文件缺失"}
    # 引用模型：可选复用同 class 其他装备的几何。
    # 引用 原版/DLC 模型 → 不复制文件，component ref 直接指向该组件；
    # 引用 mod 模型 → 复制该 mod 模型（component+data+ani）一套并改名成新 id。
    tpl_ref = _read_macro_ref(src_mac) or ""
    model_ref = (d.get("model_ref") or "").strip().lower() or tpl_ref or tpl["id"]
    _ti3 = model_ref.rfind("@@")
    if _ti3 > 0:
        model_ref = model_ref[:_ti3]
    resolved = _resolve_eq_ref(cls, model_ref)
    if resolved:
        model_ref, mref = resolved
    else:
        model_ref, mref = tpl["id"], tpl
    vanilla_ref = (mref["source"] == "vanilla") or mref["source"].startswith("ego_dlc_")
    comp_ref = model_ref if vanilla_ref else new_id
    # 目标目录基于「实际模型源」的 props 相对路径
    src_comp_dir = os.path.dirname(os.path.dirname(mref["path"]))
    rel = os.path.relpath(src_comp_dir, _eq_props_dir(mref["source"]))
    dst_comp_dir = os.path.join(mod, "assets", "props", rel)
    dst_mac_dir = os.path.join(dst_comp_dir, "macros")
    os.makedirs(dst_mac_dir, exist_ok=True)
    created, modified = [], []
    def wrel(p):
        return os.path.relpath(p, mod)
    # 1. 复制 component + data + ani 改名。
    #    引用原版/DLC 模型：默认不复制、component ref 直接指原组件；
    #    但若提供自定义挂载 tags(conn_tags)，复制一份组件改名 new_id 以写入 tags（geometry 指回原模型），component ref=new_id。
    #    引用 mod 模型：整套复制（组件+data+ani），组件改名并写入 conn_tags。
    conn_tags = (d.get("conn_tags") or "").strip()
    conn_name = (d.get("conn_name") or "").strip()
    if not vanilla_ref:
        src_id = model_ref            # component ref 物品 id（组件文件名），非宏 id
        cre, copied = _copy_rename_asset(src_comp_dir, src_id, dst_comp_dir, new_id, conn_tags, conn_name)
        created += [wrel(p) for p in cre]
        if not copied:
            comp_ref = model_ref   # 该装备无自有组件（复用官方/其他），回退直接指回，不复制
    elif conn_tags:
        # 原版/DLC 模型 + 自定义挂载 tags：复制模板组件改名（geometry 指回原模型 data），写 tags，component ref=new_id
        tpl_src_id = model_ref
        src_comp = os.path.join(src_comp_dir, tpl_src_id + ".xml")
        if os.path.isfile(src_comp):
            ctxt = _read_comp_txt(src_comp)
            ctxt = ctxt.replace('name="%s"' % tpl_src_id, 'name="%s"' % new_id)
            ctxt = _set_mount_tags(ctxt, conn_tags, conn_name)
            os.makedirs(dst_comp_dir, exist_ok=True)
            dp = os.path.join(dst_comp_dir, new_id + ".xml")
            open(dp, "w", encoding="utf-8").write(ctxt)
            created.append(wrel(dp))
            comp_ref = new_id
    # 1.5 护盾视觉（材质引用/动画部件）：写复制后的 new_id 组件
    vis = d.get("visual") or {}
    if cls == "shield" and vis and (vis.get("materials") or vis.get("anims")):
        _nc = os.path.join(dst_comp_dir, new_id + ".xml")
        if os.path.isfile(_nc):
            _c2 = open(_nc, encoding="utf-8", errors="ignore").read()
            _c2 = _apply_shield_visual(_c2, vis)
            open(_nc, "w", encoding="utf-8").write(_c2)
            created.append(wrel(_nc))
    # 2. 写 macro properties
    mtxt = open(src_mac, encoding="utf-8", errors="ignore").read()
    mtxt = mtxt.replace('name="%s_macro"' % tpl["id"], 'name="%s_macro"' % new_id)
    mtxt = re.sub(r'(<component\s+ref=")[^"]*(")', r'\g<1>%s\g<2>' % comp_ref, mtxt, count=1)
    fields = d.get("fields") or {}
    mtxt = _apply_equip_fields(cls, mtxt, fields)
    # 修正 identification 的 t 引用：模板 identification 常引用原版 page（如 20105），
    # 与工具写入 7777771 页的名称/描述不一致，百科无法正确显示。统一替换为新分配 t id。
    name_tid, desc_tid = _alloc_tids(mod)
    mtxt = _rewrite_ident_tids(mtxt, name_tid, desc_tid)
    mdp = os.path.join(dst_mac_dir, new_id + "_macro.xml")
    open(mdp, "w", encoding="utf-8").write(mtxt)
    created.append(wrel(mdp))
    # 3. t 文本
    modified += _write_equip_txt(mod, new_id, d, name_tid, desc_tid)
    # 4. ware
    mc_m = re.search(r'<macro\s+[^>]*\bclass="([^"]*)"', mtxt)
    wr = _write_equip_ware(mod, cls, new_id, new_id + "_macro", d, name_tid, desc_tid,
                           macro_class=mc_m.group(1) if mc_m else None,
                           icon_video=((fields.get("icon_video") or "").strip() or _tpl_icon_video(tpl_src, tpl_id)))
    if wr:
        modified.append(wr)
    # 4.6 列表图标别名（upgrade_<宏> → 贴图）：宏名无同名贴图会落到 upgrade_notfound（列表缺图标）。
    #     来源默认模板宏 id（前端 icon_src 可覆盖）；无同名贴图自动回退同类原版图标。
    _ial = _equip_icon_alias(mod, cls, new_id, (fields.get("icon_src") or "").strip() or tpl_id)
    if _ial:
        modified.append(_ial)
    # 5. index 注册
    modified += _register_equip(mod, cls, new_id, rel)
    copy_to_moding(mod, created + modified)
    # 把新装备并入扫描缓存，供同进程内立即编辑命中（source=目标 mod 名）
    equip_scan().setdefault(cls, {})[new_id] = {"id": new_id, "path": mdp, "cls": cls,
                                                "source": os.path.basename(mod), "sizes": tpl["sizes"]}
    # 复制改名后模型引用完整性抽查（只读，不阻断）
    dst_comp_p = os.path.join(dst_comp_dir, new_id + ".xml")
    # 尾焰：勾选"新增尾焰"才创建专属特效并让组件引用新 type
    if cls == "missile":
        _tf = d.get("fields") or {}
        if str(_tf.get("trail_new") or "").lower() in ("1", "true", "yes", "on"):
            tb = trail_build({"cls": cls, "id": new_id, "target_mod": mod,
                              "ref_type": (_tf.get("trail_ref_type") or "").strip(),
                              "new_type": (_tf.get("trail_new_type") or "").strip(),
                              "params": _tf.get("trail_params") or {}})
            if not tb.get("ok"):
                return {"ok": False, "error": tb.get("error")}
            for _c in tb.get("created") or []:
                if _c not in created:
                    created.append(_c)
    if cls == "missile":
        _tf = d.get("fields") or {}
        if str(_tf.get("explosion_new") or "").lower() in ("1", "true", "yes", "on"):
            eb = explosion_build({"eid": new_id, "target_mod": mod,
                                  "ref_type": (_tf.get("explosion_ref") or "").strip(),
                                  "new_type": (_tf.get("explosion_new_type") or "").strip(),
                                  "macro_path": mdp})
            if not eb.get("ok"):
                return {"ok": False, "error": eb.get("error")}
            for _c in eb.get("created") or []:
                if _c not in created:
                    created.append(_c)
    warns = verify_model_refs(mod, dst_comp_p) if os.path.isfile(dst_comp_p) else []
    eq_cache_refresh_source(mod)  # 装备缓存增量维护：仅重扫本 mod props 合并回缓存（免全盘冷扫）
    _refresh_soft()               # t文本+wares索引+组件内容缓存失效（中英文名回填即时）
    return {"ok": True, "id": new_id, "cls": cls, "created": created, "modified": modified,
            "moding": os.path.join(mod, "moding"), "warnings": warns}

def _backup_before_edit(path, tag):
    """装备/弹丸编辑写入前备份原文件，返回备份目录；失败返回空串（调用方据此中止写入）。
    历史事故：前端误发空值 → _apply_equip_fields 的「空值=删除属性」直接把磁盘属性删掉，且无备份不可恢复。
    备份区沿用舰船编辑的备份根，按 bak_<tag>_<时间戳> 分目录。"""
    if not path or not os.path.isfile(path):
        return ""
    try:
        bd = os.path.join(BACKUP_ROOT,
                          "bak_%s_%s" % (tag, time.strftime("%Y%m%d_%H%M%S")))
        os.makedirs(bd, exist_ok=True)
        shutil.copy2(path, os.path.join(bd, os.path.basename(path)))
        return bd
    except Exception:
        return ""

def equip_edit(d):
    cls = d.get("cls")
    if cls not in EQUIP_CLASSES:
        return {"ok": False, "error": "未知装备类型"}
    eid_raw = (d.get("pick") or "").strip().lower()
    _ti = eid_raw.rfind("@@")
    eid = eid_raw[:_ti] if _ti > 0 else eid_raw
    esrc = eid_raw[_ti + 2:] if _ti > 0 else ""
    it = (equip_scan().get(cls) or {}).get(eid)
    if it and esrc:
        for _x in (_EQ_DUP_CACHE or {}).get(cls, {}).get(eid, []):
            if _x["source"] == esrc:
                it = _x; break
    if not it:
        # 缓存可能不含（重启后编辑新增装备等）：遍历全部 props 源目录 + 目标 mod 现搜该 macro
        roots = list(zip(*_eq_roots()))
        tmod = os.path.normpath(d.get("target_mod") or MOD_DIR)
        roots.append((os.path.join(tmod, "assets", "props"), os.path.basename(tmod)))
        for pr, lbl in roots:
            for r, _, fs in os.walk(pr):
                if eid + "_macro.xml" in fs:
                    it = {"id": eid, "path": os.path.join(r, eid + "_macro.xml"), "cls": cls, "source": lbl, "sizes": []}
                    break
            if it:
                break
    if not it:
        return {"ok": False, "error": "未找到装备 %s" % eid}
    mod = os.path.normpath(d.get("target_mod") or MOD_DIR)
    if it["source"] != "vanilla":
        mod = os.path.normpath(os.path.join(ROOT, "extensions", it["source"]))
    src_mac = it["path"]
    mtxt = open(src_mac, encoding="utf-8", errors="ignore").read()
    mtxt = _apply_equip_fields(cls, mtxt, d.get("fields") or {})
    # identification t 引用统一到 7777771 专属页：编辑模式原来只写 t 文本/ware、不改 macro，
    # 重载读 macro 仍指原版页 → "改名不生效"。必须在写 macro 前解析并重写（与新建同一规则）。
    name_tid, desc_tid = _resolve_tids(it, mod)
    mtxt = _rewrite_ident_tids(mtxt, name_tid, desc_tid)
    if not _backup_before_edit(src_mac, "equip_" + cls):   # 先备份再覆盖（空值=删属性不可逆）
        return {"ok": False, "error": "备份失败，已中止写入: %s" % src_mac}
    open(src_mac, "w", encoding="utf-8").write(mtxt)
    try:
        modified = [os.path.relpath(src_mac, mod)]
    except ValueError:      # 跨盘（罕见）：改用绝对路径
        modified = [src_mac]
    # 自定义挂载 tags：写回该装备组件（与 macro 同级目录）
    conn_tags = (d.get("conn_tags") or "").strip()
    conn_name = (d.get("conn_name") or "").strip()
    if conn_tags:
        comp = os.path.join(os.path.dirname(os.path.dirname(src_mac)), eid + ".xml")
        if os.path.isfile(comp):
            ct = open(comp, encoding="utf-8", errors="ignore").read()
            nct = _set_mount_tags(ct, conn_tags, conn_name)
            if nct != ct and _backup_before_edit(comp, "equipcomp_" + cls):
                open(comp, "w", encoding="utf-8").write(nct)
                try:
                    modified.append(os.path.relpath(comp, mod))
                except ValueError:
                    modified.append(comp)
    # 护盾视觉（材质引用/动画部件）：写该装备组件
    vis = d.get("visual") or {}
    if cls == "shield" and vis and (vis.get("materials") or vis.get("anims")):
        _comp2 = os.path.join(os.path.dirname(os.path.dirname(src_mac)), eid + ".xml")
        if os.path.isfile(_comp2):
            _c2 = open(_comp2, encoding="utf-8", errors="ignore").read()
            _c2 = _apply_shield_visual(_c2, vis)
            if _backup_before_edit(_comp2, "equipcomp_" + cls):
                open(_comp2, "w", encoding="utf-8").write(_c2)
                try:
                    modified.append(os.path.relpath(_comp2, mod))
                except ValueError:
                    modified.append(_comp2)
    # 尾焰：勾选"新增尾焰"才创建专属特效并让组件引用新 type；不勾选不动拖影
    if cls == "missile":
        _tf = d.get("fields") or {}
        if str(_tf.get("trail_new") or "").lower() in ("1", "true", "yes", "on"):
            tb = trail_build({"cls": cls, "id": eid, "target_mod": mod,
                              "ref_type": (_tf.get("trail_ref_type") or "").strip(),
                              "new_type": (_tf.get("trail_new_type") or "").strip(),
                              "params": _tf.get("trail_params") or {}})
            if not tb.get("ok"):
                return {"ok": False, "error": tb.get("error")}
            for _c in tb.get("created") or []:
                if _c not in modified:
                    modified.append(_c)
    if cls == "missile":
        _tf = d.get("fields") or {}
        if str(_tf.get("explosion_new") or "").lower() in ("1", "true", "yes", "on"):
            eb = explosion_build({"eid": eid, "target_mod": mod,
                                  "ref_type": (_tf.get("explosion_ref") or "").strip(),
                                  "new_type": (_tf.get("explosion_new_type") or "").strip(),
                                  "macro_path": src_mac})
            if not eb.get("ok"):
                return {"ok": False, "error": eb.get("error")}
            for _c in eb.get("created") or []:
                if _c not in modified:
                    modified.append(_c)
    # name_tid/desc_tid 已在写 macro 前解析（见上方 identification 重写），此处直接复用
    modified += _write_equip_txt(mod, eid, d, name_tid, desc_tid)
    mc_m = re.search(r'<macro\s+[^>]*\bclass="([^"]*)"', mtxt)
    wr = _write_equip_ware(mod, cls, eid, eid + "_macro", d, name_tid, desc_tid,
                           macro_class=mc_m.group(1) if mc_m else None,
                           icon_video=(((d.get("fields") or {}).get("icon_video") or "").strip()
                                       or _tpl_icon_video(it["source"], eid)))
    if wr:
        modified.append(wr)
    # 列表图标别名：字段留空则沿用现有别名来源（无则自身宏 id）；无同名贴图回退同类原版图标。
    _ial = _equip_icon_alias(mod, cls, eid,
                             (((d.get("fields") or {}).get("icon_src") or "").strip()
                              or _icon_alias_source(mod, eid) or eid))
    if _ial:
        modified.append(_ial)
    try:
        rel = os.path.relpath(os.path.dirname(os.path.dirname(src_mac)), _eq_props_dir(it["source"]))
    except ValueError:      # 跨盘（罕见）：索引注册用空相对路径
        rel = ""
    modified += _register_equip(mod, cls, eid, rel)
    copy_to_moding(mod, modified)
    eq_cache_refresh_source(mod)  # 装备缓存增量维护：仅重扫本 mod props 合并回缓存（免全盘冷扫）
    _refresh_soft()               # t文本+wares索引+组件内容缓存失效
    return {"ok": True, "id": eid, "modified": modified, "moding": os.path.join(mod, "moding")}

def equip_kinds(cls):
    """某 class 的分类键（bullet=弹种 kind）。后台实时从扫描结果提取，随 mod 变化。"""
    if cls == "bullet":
        from collections import Counter
        c = Counter((x.get("kind") or "其他") for x in bullet_scan().values())
        return sorted([{"id": k, "count": n} for k, n in c.items()],
                      key=lambda x: (-x["count"], x["id"]))
    return []

def bullet_generate(d):
    """新增弹丸：复制模板弹丸宏，写字段到目标 mod 的 fx/weaponFx/macros。
    模型引用与装备五类统一：引用 原版/DLC 弹丸 → 不复制、component ref 直接指它；
    引用 mod 弹丸 → 复制其 component+data+ani 一套改名 new_id，component ref 指 new_id。
    弹丸不消耗 ware，不写 t 文本/ware/index。"""
    new_id = (d.get("new_id") or "").strip().lower()
    if not new_id.startswith("bullet_"):
        new_id = "bullet_" + new_id
    if not re.match(r'^[a-z][a-z0-9_]*$', new_id):
        return {"ok": False, "error": "弹丸 ID 格式错误，应用 bullet_弹种_名称 的小写字母/数字/下划线"}
    tpl_raw = (d.get("template") or "").strip().lower()
    _ti = tpl_raw.rfind("@@")
    tpl_id = tpl_raw[:_ti] if _ti > 0 else tpl_raw
    tpl_src = tpl_raw[_ti + 2:] if _ti > 0 else ""
    src = None
    if tpl_src:
        for _x in (_BULLET_DUP_CACHE or {}).get(tpl_id, []):
            if _x["source"] == tpl_src:
                src = _x; break
    if not src:
        src = next((x for x in bullet_scan().values() if x["id"] == tpl_id), None)
    if not src:
        return {"ok": False, "error": "请选择模板弹丸"}
    mod = os.path.normpath(d.get("target_mod") or MOD_DIR)
    # 引用模型（component ref）：默认=模板弹丸 id，可选同弹种其他弹丸模型
    model_ref = (d.get("model_ref") or "").strip().lower() or src.get("ref") or src["id"]
    _ti2 = model_ref.rfind("@@")
    if _ti2 > 0:
        model_ref = model_ref[:_ti2]
    mref = next((x for x in bullet_scan().values() if x["id"] == model_ref), None)
    if mref is None:
        mref = next((x for x in bullet_scan().values() if x.get("ref") == model_ref), None)
    if not mref:
        model_ref, mref = src["id"], src
    vanilla_ref = (mref["source"] == "vanilla") or mref["source"].startswith("ego_dlc_")
    comp_ref = model_ref if vanilla_ref else new_id
    created = []
    def wrel(p): return os.path.relpath(p, mod)
    # mod 引用：复制该弹丸 component + data + ani 一套，改名 new_id
    if not vanilla_ref:
        comp_dir = os.path.dirname(os.path.dirname(mref["path"]))   # .../assets/fx/weaponFx
        dst_comp_dir = os.path.join(mod, "assets", "fx", "weaponFx")
        cre, copied = _copy_rename_asset(comp_dir, model_ref, dst_comp_dir, new_id)  # 组件文件名=物品 id
        created += [wrel(p) for p in cre]
        if not copied:
            comp_ref = model_ref   # 该弹丸无自有组件（复用官方/其他），回退直接指回，不复制
    mtxt = open(src["path"], encoding="utf-8", errors="ignore").read()
    mtxt = mtxt.replace('name="%s_macro"' % src["id"], 'name="%s_macro"' % new_id)
    mtxt = re.sub(r'(<component\s+ref=")[^"]*(")', r'\g<1>%s\g<2>' % comp_ref, mtxt, count=1)
    mtxt = _apply_equip_fields("bullet", mtxt, d.get("fields") or {})
    dst_dir = os.path.join(mod, "assets", "fx", "weaponFx", "macros")
    os.makedirs(dst_dir, exist_ok=True)
    mdp = os.path.join(dst_dir, new_id + "_macro.xml")
    open(mdp, "w", encoding="utf-8").write(mtxt)
    created.append(wrel(mdp))
    # index 注册（macros + 若有新 component）：游戏经 index 索引识别新资产，必须注册，否则不生效
    modified = []
    idx = [("macros", new_id + "_macro", "assets/fx/weaponFx/macros/" + new_id + "_macro")]
    comp_path = os.path.join(mod, "assets", "fx", "weaponFx", new_id + ".xml")
    if os.path.isfile(comp_path):
        idx.append(("components", new_id, "assets/fx/weaponFx/" + new_id))
    modified += _register_index(mod, idx)
    copy_to_moding(mod, created + modified)
    # 复制改名后模型引用完整性抽查（只读，不阻断）
    bcp = os.path.join(mod, "assets", "fx", "weaponFx", new_id + ".xml")
    warns = verify_model_refs(mod, bcp) if os.path.isfile(bcp) else []
    bullet_cache_refresh_source(mod)  # 弹丸缓存增量维护：仅重扫本 mod fx/weaponFx 合并回缓存（免全盘冷扫）
    _refresh_soft()                   # t文本+wares索引+组件内容缓存失效
    return {"ok": True, "id": new_id, "created": created, "modified": modified, "moding": os.path.join(mod, "moding"), "warnings": warns}

def bullet_edit(d):
    """修改弹丸：读原宏，写字段回原文件（源为 mod 时写回该 mod）。"""
    eid_raw = (d.get("pick") or "").strip().lower()
    _ti = eid_raw.rfind("@@")
    eid = eid_raw[:_ti] if _ti > 0 else eid_raw
    esrc = eid_raw[_ti + 2:] if _ti > 0 else ""
    it = next((x for x in bullet_scan().values() if x["id"] == eid), None)
    if it and esrc:
        for _x in (_BULLET_DUP_CACHE or {}).get(eid, []):
            if _x["source"] == esrc:
                it = _x; break
    if not it:
        for m in os.listdir(os.path.join(ROOT, "extensions")):
            p = os.path.join(ROOT, "extensions", m, "assets", "fx", "weaponFx", "macros", eid + "_macro.xml")
            if os.path.isfile(p):
                it = {"id": eid, "path": p, "source": m}; break
        if not it:
            return {"ok": False, "error": "未找到弹丸 %s" % eid}
    mod = os.path.normpath(d.get("target_mod") or MOD_DIR)
    if it["source"] != "vanilla":
        mod = os.path.normpath(os.path.join(ROOT, "extensions", it["source"]))
    mtxt = open(it["path"], encoding="utf-8", errors="ignore").read()
    mtxt = _apply_equip_fields("bullet", mtxt, d.get("fields") or {})
    if not _backup_before_edit(it["path"], "bullet"):   # 先备份再覆盖（空值=删属性不可逆）
        return {"ok": False, "error": "备份失败，已中止写入: %s" % it["path"]}
    open(it["path"], "w", encoding="utf-8").write(mtxt)
    try:
        modified = [os.path.relpath(it["path"], mod)]
    except ValueError:
        modified = [it["path"]]
    copy_to_moding(mod, modified)
    bullet_cache_refresh_source(mod)  # 弹丸缓存增量维护：仅重扫本 mod fx/weaponFx 合并回缓存（免全盘冷扫）
    _refresh_soft()                   # t文本+wares索引+组件内容缓存失效
    return {"ok": True, "id": eid, "modified": modified, "moding": os.path.join(mod, "moding")}

def equip_tags(cls):
    """同类装备挂载连接 tags 词参考（去重 + 计数），供前端「同类参考」列表。
    只统计挂载匹配连接（含类型词）里的 tag；component/position/container/connection 是
    结构词（装备根挂载点必有，不参与匹配），标 struct=true 由前端决定展示（装备侧灰显，舰侧隐藏）。"""
    from collections import Counter
    TYPE = {"turret": ("turret", "missileturret"), "weapon": ("weapon",),
            "shield": ("shield",), "missile": ("missile",), "engine": ("engine",)}.get(cls, ())
    if not TYPE:
        return []
    STRUCT = ("component", "position", "container", "connection")
    c = Counter()
    for it in (equip_scan().get(cls) or {}).values():
        comp = os.path.join(os.path.dirname(os.path.dirname(it["path"])), it["id"] + ".xml")
        _, tags = _mount_conn(comp, TYPE)
        if tags:
            for w in tags.split():
                c[w] += 1
    return [{"id": w, "count": n, "struct": (w in STRUCT)} for w, n in c.most_common()]

def equip_refs():
    """参考值：按 class(+尺寸) 聚合原版装备价格 min/avg/max 中位数 + 常用材料，供前端提示。"""
    import statistics as st
    from collections import Counter
    scan = equip_scan()
    out = {}
    for cls, cfg in EQUIP_CLASSES.items():
        price = {}
        mats = Counter()
        for hid, it in (scan.get(cls) or {}).items():
            sk = "missile" if cls == "missile" else (",".join(it["sizes"]) or "?")
            w = _find_ware(hid)
            if not w:
                continue
            pm = re.search(r'<price min="([^"]*)" average="([^"]*)" max="([^"]*)"', w.group(0))
            if pm:
                price.setdefault(sk, []).append((float(pm.group(1)), float(pm.group(2)), float(pm.group(3))))
            for mm in re.finditer(r'<ware ware="([^"]*)" amount="([^"]*)"', w.group(0)):
                mats[mm.group(1)] += 1
        agg = {}
        for sk, arr in price.items():
            if not arr:
                continue
            agg[sk] = {"min": int(st.median(a[0] for a in arr)),
                       "avg": int(st.median(a[1] for a in arr)),
                       "max": int(st.median(a[2] for a in arr))}
        out[cls] = {"prices": agg, "materials": [w for w, c in mats.most_common(8)]}
    return out

def equip_numeric_refs(cls):
    """数值字段参考值：按尺寸(或 all)聚合原版同类装备的数值字段 min/中位/max，供前端字段下提示。"""
    import statistics as st
    scan = equip_scan().get(cls) or {}
    # 同名 id 被后加载 mod（如 VRO）覆盖时，scan 只留 winner；vanilla 版本在 dup 缓存里。
    # 合并两者并按 path 去重，否则被全覆盖的类（护盾）统计为空。
    items = list(scan.values())
    for _lst in ((_EQ_DUP_CACHE or {}).get(cls) or {}).values():
        items.extend(_lst)
    groups = {}
    seen = set()
    for it in items:
        if it.get("source") != "vanilla":
            continue
        _p = it.get("path") or ""
        if _p in seen:
            continue
        seen.add(_p)
        try:
            txt = open(it["path"], encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        f = _read_equip_fields(cls, txt)
        sk = "all" if cls == "missile" else (",".join(it["sizes"]) or "?")
        d = groups.setdefault(sk, {})
        for k, v in f.items():
            try:
                nv = float(v)
            except Exception:
                continue
            d.setdefault(k, []).append(nv)
    out = {}
    for sk, dd in groups.items():
        agg = {}
        for k, arr in dd.items():
            if len(arr) < 2:
                continue
            arr.sort()
            agg[k] = [int(arr[0]), int(st.median(arr)), int(arr[-1])]
        if agg:
            out[sk] = agg
    return out

def missile_users(missile_id):
    """返回能发射/装载指定导弹的发射塔，两类：
    fixed   = bullet class 直接指向该导弹宏的发射塔（固定发射）
    matched = ammunition tags 含该导弹自身类别词(如 lham)的发射塔（类别匹配可装载）"""
    scan = equip_scan().get("turret") or {}
    mid = missile_id + ("_macro" if not missile_id.endswith("_macro") else "")
    # 该导弹自身类别（<missile ... tags>）
    own_tags = set()
    for hid, it in (equip_scan().get("missile") or {}).items():
        if hid == missile_id:
            try:
                t = open(it["path"], encoding="utf-8", errors="ignore").read()
            except Exception:
                t = ""
            m = re.search(r'<missile\b[^>]*\btags="([^"]*)"', t)
            if m:
                own_tags = set(m.group(1).split())
            break
    fixed, matched = [], []
    for hid, it in scan.items():
        try:
            t = open(it["path"], encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        mc = re.search(r'<macro\b[^>]*\bclass="([^"]*)"', t)
        mt = mc.group(1) if mc else ""
        if re.search(r'<bullet\s+class="%s"' % re.escape(mid), t):
            fixed.append({"id": hid, "name": LX.macro_display(it["path"], _zh_id(hid) + "[译]", "zh"),
                          "source": it["source"], "mt_class": mt, "kind": "fixed"})
            continue
        am = re.search(r'<ammunition\b[^>]*\btags="([^"]*)"', t)
        if am and own_tags:
            at = set(am.group(1).split())
            if at and own_tags <= at:   # 导弹自身类别 ⊆ 发射塔弹药类别（发射塔弹药须覆盖导弹全部类别）
                matched.append({"id": hid, "name": LX.macro_display(it["path"], _zh_id(hid) + "[译]", "zh"),
                               "source": it["source"], "mt_class": mt, "kind": "matched"})
    return fixed + matched

_TRAIL_ZH = {
    "trail_lham": "重型突击导弹轨迹（L）", "trail_mham": "中型突击导弹轨迹", "trail_sham": "小型突击导弹轨迹",
    "trail_missile_npc_torpedo": "NPC 鱼雷轨迹", "trail_missile_player_dumbfire": "玩家无导导弹轨迹",
    "trail_missile_player_guided": "玩家制导导弹轨迹",
    "trail_missile_flagship_heavy_mk1": "旗舰重型导弹轨迹", "trail_missile_flagship_light_mk1": "旗舰轻型导弹轨迹",
}

def _trail_material_zh(name, dm):
    base = (os.path.basename(dm) if dm else name).lower()
    for key, zh in [("blue", "蓝"), ("white", "白"), ("yellow", "黄"), ("red", "红"),
                    ("pink", "粉"), ("smoke", "烟灰"), ("xenon", "异形绿"), ("vortex", "涡流")]:
        if key in base or key in name.lower():
            return zh + " · " + name
    return re.sub(r'_+', ' ', name).strip() + " [译]"

def trail_materials():
    """material_library 里所有 p1_trail 材质（尾焰颜色/样式），供颜色选择。"""
    base = os.path.join(ROOT, "libraries", "material_library.xml")
    out = []
    if not os.path.isfile(base):
        return out
    try:
        t = open(base, encoding="utf-8", errors="ignore").read()
    except Exception:
        return out
    for m in re.finditer(r'<material\s+name="([^"]+)"\s+shader="p1_trail"[^>]*>(.*?)</material>', t, re.S):
        name = m.group(1)
        body = m.group(2)
        dm = re.search(r'name="diffuse_map"\s+value="([^"]+)"', body)
        dmv = dm.group(1) if dm else ""
        out.append({"id": "trails." + name, "name": name, "diffuse": dmv, "zh": _trail_material_zh(name, dmv)})
    return out
def _trail_zh(k):
    return _TRAIL_ZH.get(k, re.sub(r'_+', ' ', k).strip() + " [译]")

def _set_trail_type(ct, tv):
    """把组件 trailemitters 里第一个 emitter 的 type 设为 tv（保留 name 等其他属性）。无 emitter 或 tv 空则不改。"""
    if not tv:
        return ct
    def rep(m):
        at = m.group(1)
        if re.search(r'\btype="', at):
            at2 = re.sub(r'\btype="[^"]*"', 'type="%s"' % tv, at, count=1)
        else:
            at2 = at.rstrip() + ' type="%s"' % tv
        return "<emitter" + at2 + ">"
    return re.sub(r'<emitter\b([^>]*)>', rep, ct, count=1)


def _trail_effect_files():
    fs = []
    b = os.path.join(ROOT, "libraries", "trail_effects.xml")
    if os.path.isfile(b):
        fs.append(b)
    ext = os.path.join(ROOT, "extensions")
    try:
        names = sorted(os.listdir(ext))
    except Exception:
        names = []
    for n in names:
        pp = os.path.join(ext, n, "libraries", "trail_effects.xml")
        if os.path.isfile(pp):
            fs.append(pp)
    return fs

def _explosion_zh(k):
    # 特效名通常无游戏文本条目，直接用贴合游戏语境的 id 翻译（无 [译]，由前端/列表兜底标）
    return _zh_id(k)

def _find_explosion_effect(ref_type):
    """在所有 effects.xml（原版 + extensions）里找 <effect name=ref_type> 块，返回 (block, 源路径)。"""
    srcs = [os.path.join(ROOT, "libraries", "effects.xml")]
    for m in sorted(os.listdir(os.path.join(ROOT, "extensions"))):
        fp = os.path.join(ROOT, "extensions", m, "libraries", "effects.xml")
        if os.path.isfile(fp):
            srcs.append(fp)
    for fp in srcs:
        try:
            t = open(fp, encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        m = re.search(r'(?s)<effect\s+name="' + re.escape(ref_type) + r'"[^>]*>(.*?)</effect>', t)
        if m:
            head = t[max(0, m.start()):m.start() + len('<effect name="' + ref_type + '"')]
            full = re.search(r'(?s)<effect\s+name="' + re.escape(ref_type) + r'"[^>]*?>.*?</effect>', t)
            return full.group(0) if full else ('<effect name="' + ref_type + '">' + m.group(1) + '</effect>'), fp
    return "", ""

def explosion_refs():
    """扫所有导弹宏 <explosion ref=...> 去重+计数，供同类参考。"""
    cnt = {}
    srcs = {}
    for it in (equip_scan().get("missile") or {}).values():
        try:
            mt = open(it["path"], encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        for mm in re.finditer(r'<explosion\s+ref="([^"]+)"', mt):
            r = mm.group(1)
            cnt[r] = cnt.get(r, 0) + 1
            srcs[r] = it["source"]
    out = []
    for r, c in sorted(cnt.items(), key=lambda x: -x[1]):
        out.append({"id": r, "count": c, "source": srcs.get(r, ""), "zh": _explosion_zh(r)})
    return out

def _explosion_ammo_items():
    """所有弹药类宏（导弹/弹丸/炸弹），供爆炸特效引用统计：{id,cls,source,path}。"""
    items = []
    for it in (equip_scan().get("missile") or {}).values():
        items.append({"id": it.get("id") or "", "cls": "missile", "source": it.get("source", ""), "path": it["path"]})
    for it in (bullet_scan() or {}).values():
        items.append({"id": it.get("id") or "", "cls": "bullet", "source": it.get("source", ""), "path": it["path"]})
    for base, src in [(os.path.join(ROOT, "assets", "fx", "weaponFx"), "vanilla")] + \
                     [(os.path.join(ROOT, "extensions", m, "assets", "fx", "weaponFx"), m) for m in _ext_order()]:
        md = os.path.join(base, "macros")
        if not os.path.isdir(md):
            continue
        for f in sorted(os.listdir(md)):
            if not (f.startswith("bomb_") and f.endswith("_macro.xml")):
                continue
            p = os.path.join(md, f)
            try:
                t = open(p, encoding="utf-8", errors="ignore").read()
            except Exception:
                continue
            if 'class="bomb"' not in t:
                continue
            items.append({"id": f[:-len("_macro.xml")], "cls": "bomb", "source": src, "path": p})
    return items

def _explosion_impact_patterns():
    """匹配特效引用：爆炸(<explosion ref>) 与弹丸击中(<impact ref>/<bigobjectimpact ref>)。"""
    return (r'<explosion\s+ref="([^"]+)"',
            r'<impact\s+ref="([^"]+)"',
            r'<bigobjectimpact\s+ref="([^"]+)"')

def explosion_users(ref):
    """给定特效 ref，返回引用它的弹药宏（导弹/弹丸/炸弹的爆炸或击中引用，去重）。"""
    if not ref:
        return []
    pat = re.compile(r'<(explosion|impact|bigobjectimpact)\b[^>]*\bref="' + re.escape(ref) + r'"')
    out, seen = [], set()
    for it in _explosion_ammo_items():
        try:
            mt = open(it["path"], encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        if not pat.search(mt):
            continue
        key = (it["id"], it["cls"], it["source"])
        if key in seen:
            continue
        seen.add(key)
        out.append({"id": it["id"], "cls": it["cls"], "source": it["source"], "name": it["id"]})
    return out


def explosion_effects():
    """爆炸/击中特效列表：导弹/炸弹的 explosion 特效 + 弹丸的 impact 击中特效（均被实际引用）。"""
    used = {}
    def bump(rid, kind):
        if rid not in used:
            used[rid] = [0, kind]
        used[rid][0] += 1
    for it in _explosion_ammo_items():
        try:
            mt = open(it["path"], encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        for mm in re.finditer(r'<explosion\s+ref="([^"]+)"', mt):
            bump(mm.group(1), "missile" if it["cls"] == "missile" else "bomb")
    for it in (bullet_scan() or {}).values():
        try:
            mt = open(it["path"], encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        for mm in re.finditer(r'<(?:bigobject)?impact\b[^>]*\bref="([^"]+)"', mt):
            bump(mm.group(1), "bullet")
    if not used:
        return []
    srcs = [os.path.join(ROOT, "libraries", "effects.xml")]
    for m in sorted(os.listdir(os.path.join(ROOT, "extensions"))):
        fp = os.path.join(ROOT, "extensions", m, "libraries", "effects.xml")
        if os.path.isfile(fp):
            srcs.append(fp)
    name_src = {}
    for fp in srcs:
        label = "vanilla"
        if os.path.relpath(fp, ROOT).lower().startswith(os.path.join("extensions", "")):
            label = os.path.basename(os.path.dirname(os.path.dirname(fp)))
        try:
            t = open(fp, encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        for m in re.finditer(r'<effect\s+name="([^"]+)"', t):
            n = m.group(1)
            if n in used:
                if n in name_src:
                    if label != "vanilla":
                        name_src[n] = label
                else:
                    name_src[n] = label
    _order = {"missile": 0, "bomb": 1, "bullet": 2}
    items = [{"id": k, "source": name_src.get(k, ""), "zh": _explosion_zh(k), "count": used.get(k, [0])[0], "kind": used.get(k, [0, ""])[1]} for k in used]
    items.sort(key=lambda x: (_order.get(x["kind"], 3), x["id"]))
    return items

def _set_explosion_ref(mtxt, new_ref):
    """把宏 <effects> 内首个 <explosion ref="X"/> 换成 new_ref；无则不换。"""
    return re.sub(r'<explosion\s+ref="[^"]*"', '<explosion ref="' + new_ref + '"', mtxt, count=1)

def explosion_build(d):
    eid = (d.get("eid") or "").strip()
    tmod = os.path.normpath(d.get("target_mod") or MOD_DIR)
    ref_type = (d.get("ref_type") or "").strip()
    new_type = (d.get("new_type") or "").strip()
    macp = d.get("macro_path") or ""
    if not (eid and new_type):
        return {"ok": False, "error": "缺少爆炸特效名/装备"}
    if not re.match(r'^[a-z0-9_]+$', new_type):
        return {"ok": False, "error": "特效名须为小写字母/数字/下划线"}
    # 1) 直接引用：new_type 已是原版/mod/目标mod 存在的特效 → 只改宏引用，不复制
    gblk, gsrc = _find_explosion_effect(new_type)
    dst0 = os.path.join(tmod, "libraries", "effects.xml")
    t_exists = False
    if os.path.isfile(dst0):
        try:
            if ('name="' + new_type + '"' in open(dst0, encoding="utf-8", errors="ignore").read()):
                t_exists = True
        except Exception:
            pass
    if gblk or t_exists:
        if macp and os.path.isfile(macp):
            mt = open(macp, encoding="utf-8", errors="ignore").read()
            nmt = _set_explosion_ref(mt, new_type)
            if nmt != mt:
                open(macp, "w", encoding="utf-8").write(nmt)
                try:
                    created = [os.path.relpath(macp, tmod)]
                except ValueError:
                    created = [macp]
                try:
                    copy_to_moding(mod=tmod, items=created)
                    bullet_cache_refresh_source(tmod)  # 弹丸缓存增量维护（免全盘冷扫）
                    _refresh_soft()                    # 材质/视觉参考等轻量失效
                except Exception:
                    pass
                return {"ok": True, "new_type": new_type, "created": created, "src": gsrc, "mode": "ref"}
            return {"ok": True, "new_type": new_type, "created": [], "src": gsrc, "mode": "ref"}
        return {"ok": False, "error": "找不到宏文件以写入爆炸引用"}
    # 2) 复制参考特效为新名（全新自定义名）
    if not ref_type:
        return {"ok": False, "error": "缺少参考爆炸特效（复制需选参考）"}
    blk, src = _find_explosion_effect(ref_type)
    if not blk:
        return {"ok": False, "error": "找不到参考爆炸特效 %s" % ref_type}
    refs = re.findall(r'<reference\s+effect="([^"]+)"', blk)
    new_ent = "ref_" + new_type
    new_blk = blk.replace('name="' + ref_type + '"', 'name="' + new_type + '"', 1)
    if refs:
        new_blk = re.sub(r'<reference\s+effect="' + re.escape(refs[0]) + r'"',
                         '<reference effect="' + new_ent + '"', new_blk, count=1)
    dst_dir = os.path.join(tmod, "libraries")
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, "effects.xml")
    ent_blk = ""
    if refs:
        ent_blk, _s = _find_explosion_effect(refs[0])
        ent_blk = ent_blk.replace('name="' + refs[0] + '"', 'name="' + new_ent + '"', 1)
    existing = ""
    if os.path.isfile(dst):
        existing = open(dst, encoding="utf-8", errors="ignore").read()
    body = new_blk
    if ent_blk:
        body += "\n" + ent_blk
    indent = "\n    "
    if not existing:
        newtxt = DIFF_HEADER + '  <add sel="//effects">' + indent + body.strip() + '\n  </add>\n</diff>\n'
    else:
        am = re.search(r'(?s)(<add sel="//effects"[^>]*>)(.*?)(</add>)', existing)
        if am:
            newtxt = existing[:am.start(2)] + "\n    " + body.strip() + "\n  " + existing[am.start(3):]
        else:
            # 兼容旧格式（裸 <diff>）与新格式（<diff xmlns:xsi=...>）：定位 diff 开标签后插入
            newtxt = re.sub(r'<diff\b[^>]*>',
                            lambda m: m.group(0) + '\n  <add sel="//effects">' + indent + body.strip() + '\n  </add>',
                            existing, count=1)
    open(dst, "w", encoding="utf-8").write(newtxt)
    created = [os.path.relpath(dst, tmod)]
    if macp and os.path.isfile(macp):
        mt = open(macp, encoding="utf-8", errors="ignore").read()
        nmt = _set_explosion_ref(mt, new_type)
        if nmt != mt:
            open(macp, "w", encoding="utf-8").write(nmt)
            try:
                created.append(os.path.relpath(macp, tmod))
            except ValueError:
                created.append(macp)
    else:
        return {"ok": False, "error": "找不到宏文件以写入爆炸引用"}
    try:
        copy_to_moding(mod=tmod, items=created)
        bullet_cache_refresh_source(tmod)  # 弹丸缓存增量维护（免全盘冷扫）
        _refresh_soft()                    # 材质/视觉参考等轻量失效
    except Exception:
        pass
    return {"ok": True, "new_type": new_type, "created": created, "src": src, "mode": "copy"}


def _bullet_effects_files():
    srcs = [os.path.join(ROOT, "libraries", "effects.xml")]
    for m in sorted(os.listdir(os.path.join(ROOT, "extensions"))):
        fp = os.path.join(ROOT, "extensions", m, "libraries", "effects.xml")
        if os.path.isfile(fp):
            srcs.append(fp)
    return srcs


def bullet_effect_list(tag):
    """被弹丸宏 <tag ref> 实际引用的特效列表（tag=impact/bigobjectimpact/launch，引用>0）。
    被引用即列出；特效定义在 effects.xml 时标注来源 mod，未注册特效（如炮塔/武器特效名）也一并列出，source 留空。"""
    used = {}
    for it in (bullet_scan() or {}).values():
        try:
            mt = open(it["path"], encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        for mm in re.finditer(r'<' + tag + r'\b[^>]*\bref="([^"]+)"', mt):
            used[mm.group(1)] = used.get(mm.group(1), 0) + 1
    if not used:
        return []
    name_src = {}
    for fp in _bullet_effects_files():
        label = "vanilla"
        rp = os.path.relpath(fp, ROOT).lower()
        if rp.startswith(os.path.join("extensions", "")):
            label = os.path.basename(os.path.dirname(os.path.dirname(fp)))
        try:
            t = open(fp, encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        for m in re.finditer(r'<effect\s+name="([^"]+)"', t):
            n = m.group(1)
            if n in used:
                if n in name_src:
                    if label != "vanilla":
                        name_src[n] = label
                else:
                    name_src[n] = label
    return [{"id": k, "source": name_src.get(k, ""), "count": used.get(k, 0)} for k in sorted(used)]


def bullet_effect_read(eid):
    """读弹丸宏当前 <effects> 的 impact/bigobjectimpact/launch 引用，供回填。"""
    out = {"impact": "", "bigobjectimpact": "", "launch": ""}
    if not eid:
        return out
    it = (bullet_scan() or {}).get(eid)
    if not it:
        return out
    try:
        mt = open(it["path"], encoding="utf-8", errors="ignore").read()
    except Exception:
        return out
    for tag in out:
        m = re.search(r'<' + tag + r'\b[^>]*\bref="([^"]+)"', mt)
        if m:
            out[tag] = m.group(1)
    return out


def _set_bullet_effect_ref(mt, tag, new_type):
    """把弹丸宏 <effects> 内首个 <tag ref="X"> 的 ref 换成 new_type（保留其他属性）。"""
    return re.sub(r'(<' + tag + r'\b[^>]*?\bref=")[^"]*(")', r'\g<1>' + new_type + r'\g<2>', mt, count=1)


def bullet_effect_build(d):
    """改弹丸宏 <tag ref>（tag=impact/bigobjectimpact/launch）。引用已存在特效直接改宏；
    全新名则复制参考特效为新名到目标 mod，再改宏。"""
    eid = (d.get("eid") or "").strip()
    tag = (d.get("tag") or "impact").strip()
    if tag not in ("impact", "bigobjectimpact", "launch"):
        return {"ok": False, "error": "无效特效类型 %s" % tag}
    tmod = os.path.normpath(d.get("target_mod") or MOD_DIR)
    ref_type = (d.get("ref_type") or "").strip()
    new_type = (d.get("new_type") or "").strip()
    macp = d.get("macro_path") or ""
    if not macp:
        it = (bullet_scan() or {}).get(eid)
        if it:
            macp = it["path"]
    if not (eid and new_type):
        return {"ok": False, "error": "缺少特效名/弹丸"}
    if not re.match(r'^[a-z0-9_]+$', new_type):
        return {"ok": False, "error": "特效名须为小写字母/数字/下划线"}
    # 1) 直接引用：new_type 已是存在的特效 → 只改宏引用，不复制
    gblk, gsrc = _find_explosion_effect(new_type)
    dst0 = os.path.join(tmod, "libraries", "effects.xml")
    t_exists = False
    if os.path.isfile(dst0):
        try:
            if ('name="' + new_type + '"' in open(dst0, encoding="utf-8", errors="ignore").read()):
                t_exists = True
        except Exception:
            pass
    if gblk or t_exists:
        if macp and os.path.isfile(macp):
            mt = open(macp, encoding="utf-8", errors="ignore").read()
            nmt = _set_bullet_effect_ref(mt, tag, new_type)
            if nmt != mt:
                open(macp, "w", encoding="utf-8").write(nmt)
                try:
                    created = [os.path.relpath(macp, tmod)]
                except ValueError:
                    created = [macp]
                try:
                    copy_to_moding(mod=tmod, items=created)
                    bullet_cache_refresh_source(tmod)  # 弹丸缓存增量维护（免全盘冷扫）
                    _refresh_soft()                    # 材质/视觉参考等轻量失效
                except Exception:
                    pass
                return {"ok": True, "new_type": new_type, "created": created, "src": gsrc, "mode": "ref"}
            return {"ok": True, "new_type": new_type, "created": [], "src": gsrc, "mode": "ref"}
        return {"ok": False, "error": "找不到宏文件以写入特效引用"}
    # 2) 复制参考特效为新名（全新自定义名）
    if not ref_type:
        return {"ok": False, "error": "缺少参考特效（复制需选参考）"}
    blk, src = _find_explosion_effect(ref_type)
    if not blk:
        return {"ok": False, "error": "找不到参考特效 %s" % ref_type}
    refs = re.findall(r'<reference\s+effect="([^"]+)"', blk)
    new_ent = "ref_" + new_type
    new_blk = blk.replace('name="' + ref_type + '"', 'name="' + new_type + '"', 1)
    if refs:
        new_blk = re.sub(r'<reference\s+effect="' + re.escape(refs[0]) + r'"',
                         '<reference effect="' + new_ent + '"', new_blk, count=1)
    dst_dir = os.path.join(tmod, "libraries")
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, "effects.xml")
    ent_blk = ""
    if refs:
        ent_blk, _s = _find_explosion_effect(refs[0])
        ent_blk = ent_blk.replace('name="' + refs[0] + '"', 'name="' + new_ent + '"', 1)
    existing = ""
    if os.path.isfile(dst):
        existing = open(dst, encoding="utf-8", errors="ignore").read()
    body = new_blk
    if ent_blk:
        body += "\n" + ent_blk
    indent = "\n    "
    if not existing:
        newtxt = DIFF_HEADER + '  <add sel="//effects">' + indent + body.strip() + '\n  </add>\n</diff>\n'
    else:
        am = re.search(r'(?s)(<add sel="//effects"[^>]*>)(.*?)(</add>)', existing)
        if am:
            newtxt = existing[:am.start(2)] + "\n    " + body.strip() + "\n  " + existing[am.start(3):]
        else:
            # 兼容旧格式（裸 <diff>）与新格式（<diff xmlns:xsi=...>）：定位 diff 开标签后插入
            newtxt = re.sub(r'<diff\b[^>]*>',
                            lambda m: m.group(0) + '\n  <add sel="//effects">' + indent + body.strip() + '\n  </add>',
                            existing, count=1)
    open(dst, "w", encoding="utf-8").write(newtxt)
    created = [os.path.relpath(dst, tmod)]
    if macp and os.path.isfile(macp):
        mt = open(macp, encoding="utf-8", errors="ignore").read()
        nmt = _set_bullet_effect_ref(mt, tag, new_type)
        if nmt != mt:
            open(macp, "w", encoding="utf-8").write(nmt)
            try:
                created.append(os.path.relpath(macp, tmod))
            except ValueError:
                created.append(macp)
    else:
        return {"ok": False, "error": "找不到宏文件以写入特效引用"}
    try:
        copy_to_moding(mod=tmod, items=created)
        bullet_cache_refresh_source(tmod)  # 弹丸缓存增量维护（免全盘冷扫）
        _refresh_soft()                    # 材质/视觉参考等轻量失效
    except Exception:
        pass
    return {"ok": True, "new_type": new_type, "created": created, "src": src, "mode": "copy"}



def _bullet_comp_for_id(eid):
    """弹丸组件文件路径（拖尾在组件里）。用宏 component ref 反查组件。"""
    it = (bullet_scan() or {}).get(eid)
    if not it or not it.get("ref"):
        return ""
    return _equip_component(it["path"], it["ref"])


def _bullet_mat_bare(ref):
    """材质完整引用 → 裸名（去掉 effects./p1effects./trails. 前缀）。"""
    for p in ("effects.", "p1effects.", "trails."):
        if ref.startswith(p):
            return ref[len(p):]
    return ref


def _bullet_mat_ref(bare):
    """弹丸拖尾材质裸名 → 完整引用。bullets_fx_* 用 effects 库；p1_* 用 p1effects 库。"""
    b = (bare or "").strip()
    if b.startswith("effects.") or b.startswith("p1effects.") or b.startswith("trails."):
        return b
    if b.startswith("p1_"):
        return "p1effects." + b
    return "effects." + b


def bullet_trail_materials():
    """material_library（原版 + 扩展）里可作弹丸飞行拖尾的材质：bullets_fx / p1_bullet / shockwave / trails。
    返回按 id 去重，原版优先。"""
    files = [os.path.join(ROOT, "libraries", "material_library.xml")]
    try:
        for m in sorted(os.listdir(os.path.join(ROOT, "extensions"))):
            fp = os.path.join(ROOT, "extensions", m, "libraries", "material_library.xml")
            if os.path.isfile(fp):
                files.append(fp)
    except Exception:
        pass
    by_id = {}
    for fp in files:
        src = "vanilla"
        rp = os.path.relpath(fp, ROOT).lower()
        if rp.startswith(os.path.join("extensions", "")):
            src = os.path.basename(os.path.dirname(os.path.dirname(fp)))
        try:
            t2 = open(fp, encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        for m in re.finditer(r'<material\s+name="([^"]+)"', t2):
            n = m.group(1)
            ln = n.lower()
            if ("bullets_fx" in ln or "p1_bullet" in ln
                    or "shockwave" in ln or ln.endswith("_bullet")):
                if n not in by_id or (src != "vanilla" and by_id[n] == "vanilla"):
                    by_id[n] = src
    return [{"id": k, "src": v} for k, v in by_id.items()]


def bullet_trail_read(eid):
    """读弹丸组件 shockwave part 的材质 ref + uv_animations v_offset（mapchannel 2/3）起止值。"""
    out = {"material": "", "uv2_start": "", "uv2_end": "", "uv3_start": "", "uv3_end": ""}
    if not eid:
        return out
    comp = _bullet_comp_for_id(eid)
    if not comp or not os.path.isfile(comp):
        return out
    try:
        t2 = _read_comp_txt(comp)
    except Exception:
        return out
    sh = re.search(r'(?s)<part\s+name="[^"]*shockwave[^"]*".*?</part>', t2)
    if not sh:
        return out
    b = sh.group(0)
    mm = re.search(r'<material\s+id="1"\s+ref="([^"]+)"', b)
    out["material"] = _bullet_mat_bare(mm.group(1)) if mm else ""

    def uv(mapc):
        u = re.search(r'<uv_animation\s+rotaroundcenter="1"\s+mapchannel="%d">(.*?)</uv_animation>' % mapc, b, re.S)
        if not u:
            return "", ""
        va = re.search(r'<uv_property\s+name="v_offset"[\s\S]*?<key\s+frame="1"\s+value="([^"]+)"\s*/>\s*<key\s+frame="[^"]+"\s+value="([^"]+)"', u.group(1))
        return (va.group(1), va.group(2)) if va else ("", "")
    out["uv2_start"], out["uv2_end"] = uv(2)
    out["uv3_start"], out["uv3_end"] = uv(3)
    return out


def bullet_trail_build(d):
    """改弹丸飞行拖尾：shockwave part 的材质 ref 与 uv_animation v_offset 起止值。
    目标 mod 无同名组件则复制原组件过去再改（拖尾在组件，非特效文件）。"""
    eid = (d.get("eid") or "").strip()
    tmod = os.path.normpath(d.get("target_mod") or MOD_DIR)
    material = (d.get("material") or "").strip()
    uv = {}
    for k in ("uv2_start", "uv2_end", "uv3_start", "uv3_end"):
        v = (d.get(k) or "").strip()
        if v:
            uv[k] = v
    if not eid:
        return {"ok": False, "error": "缺少弹丸"}
    if not material and not uv:
        return {"ok": False, "error": "没有可写入的修改"}
    if material and not re.match(r'^[a-zA-Z0-9_.]+$', material):
        return {"ok": False, "error": "材质名格式错误"}
    comp = _bullet_comp_for_id(eid)
    if not comp or not os.path.isfile(comp):
        return {"ok": False, "error": "未找到弹丸组件文件（拖尾在组件里）"}
    if material and not uv:
        try:
            srt = _read_comp_txt(comp)
            sh = re.search(r'(?s)<part\s+name="[^"]*shockwave[^"]*".*?</part>', srt)
            sm = re.search(r'<material\s+id="1"\s+ref="([^"]+)"', sh.group(0)) if sh else None
            if sm and _bullet_mat_bare(sm.group(1)) == material:
                return {"ok": True, "created": [], "unchanged": True, "material": material}
        except Exception:
            pass
    tgt = os.path.join(tmod, "assets", "fx", "weaponFx", eid + ".xml")
    if not os.path.isfile(tgt):
        os.makedirs(os.path.dirname(tgt), exist_ok=True)
        # diff 补丁型源组件先合并 base 再写入（直接复制 <diff> 原文游戏无法加载）
        open(tgt, "w", encoding="utf-8").write(_read_comp_txt(comp))
    t2 = open(tgt, encoding="utf-8", errors="ignore").read()
    nt = t2
    if material:
        full = _bullet_mat_ref(material)
        nt = re.sub(r'(?s)(<part\s+name="[^"]*shockwave[^"]*".*?</part>)',
                    lambda m: re.sub(r'(<material\s+id="1"\s+ref=")[^"]*(")', r'\g<1>' + full + r'\g<2>', m.group(1), count=1),
                    nt, count=1)
    for mapc in (2, 3):
        sk, ek = "uv%d_start" % mapc, "uv%d_end" % mapc
        if sk not in uv and ek not in uv:
            continue
        pat = re.compile(r'(<uv_animation\s+rotaroundcenter="1"\s+mapchannel="%d">.*?</uv_animation>)' % mapc, re.S)
        def rep(m):
            b = m.group(1)
            if sk in uv:
                b = re.sub(r'(<key\s+frame="1"\s+value=")[^"]*(")', r'\g<1>' + uv[sk] + r'\g<2>', b, count=1)
            if ek in uv:
                b = re.sub(r'(<key\s+frame="(?!1")[^"]*"\s+value=")[^"]*(")', r'\g<1>' + uv[ek] + r'\g<2>', b, count=1)
            return b
        nt = pat.sub(rep, nt, count=1)
    open(tgt, "w", encoding="utf-8", newline="").write(nt)
    created = [os.path.relpath(tgt, tmod)]
    try:
        copy_to_moding(mod=tmod, items=created)
        bullet_cache_refresh_source(tmod)  # 弹丸缓存增量维护（免全盘冷扫）
        _refresh_soft()                    # 材质/视觉参考等轻量失效
    except Exception:
        pass
    return {"ok": True, "created": created, "material": material, "uv": uv}
def bullet_beam_materials():
    """光束弹丸可用材质：material_library（原版+扩展）中含 beam / p2_bullet / fx_p2 的材质。"""
    files = [os.path.join(ROOT, "libraries", "material_library.xml")]
    try:
        for m in sorted(os.listdir(os.path.join(ROOT, "extensions"))):
            fp = os.path.join(ROOT, "extensions", m, "libraries", "material_library.xml")
            if os.path.isfile(fp):
                files.append(fp)
    except Exception:
        pass
    by_id = {}
    for fp in files:
        src = "vanilla"
        rp = os.path.relpath(fp, ROOT).lower()
        if rp.startswith(os.path.join("extensions", "")):
            src = os.path.basename(os.path.dirname(os.path.dirname(fp)))
        try:
            t2 = open(fp, encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        for m in re.finditer(r'<material\s+name="([^"]+)"', t2):
            n = m.group(1); ln = n.lower()
            if "beam" in ln or "p2_bullet" in ln or "fx_p2" in ln:
                if n not in by_id or (src != "vanilla" and by_id[n] == "vanilla"):
                    by_id[n] = src
    return [{"id": k, "src": v} for k, v in by_id.items()]


def bullet_vis_materials():
    """弹丸视觉材质全集（弹体/拖尾/光束）：bullets_fx / p1_bullet / shockwave / beam / fx_p2 / p2_bullet 合并去重。"""
    by_id = {}
    for m in (bullet_trail_materials() + bullet_beam_materials()):
        if m["id"] not in by_id or (m["src"] != "vanilla" and by_id[m["id"]] == "vanilla"):
            by_id[m["id"]] = m["src"]
    return [{"id": k, "src": v} for k, v in by_id.items()]


def _bullet_beam_ref(bare):
    """光束材质裸名 -> 完整引用。beam_fx -> p1effects 库；fx_p2 / p2_bullet -> p2fx 库。"""
    b = (bare or "").strip()
    for p in ("p1effects.", "p2fx.", "effects.", "trails."):
        if b.startswith(p):
            return b
    if b.startswith("fx_p2") or "p2_bullet" in b:
        return "p2fx." + b
    return "p1effects." + b


def _bullet_beam_part(t2):
    """在弹丸组件里定位主体光束 part（材质 ref 含 beam），返回 (part块, 材质完整ref)。"""
    for pm in re.finditer(r'(?s)<part\s+name="([^"]*)".*?</part>', t2):
        mm = re.search(r'<material\s+id="1"\s+ref="([^"]+)"', pm.group(0))
        if mm and "beam" in mm.group(1).lower():
            return pm.group(0), mm.group(1)
    return None, None


def bullet_beam_read(eid):
    """读光束弹丸组件：omni 灯光 RGB（光束颜色）+ 主体光束材质 + u_offset（mapchannel 2）起止。"""
    out = {"r": "", "g": "", "b": "", "material": "", "u2_start": "", "u2_end": ""}
    if not eid:
        return out
    comp = _bullet_comp_for_id(eid)
    if not comp or not os.path.isfile(comp):
        return out
    try:
        t2 = _read_comp_txt(comp)
    except Exception:
        return out
    om = re.search(r'<omni\b[^>]*\br="([0-9.]+)"[^>]*\bg="([0-9.]+)"[^>]*\bb="([0-9.]+)"', t2)
    if om:
        out["r"], out["g"], out["b"] = om.group(1), om.group(2), om.group(3)
    bp, mref = _bullet_beam_part(t2)
    if bp and mref:
        out["material"] = _bullet_mat_bare(mref)
        u = re.search(r'<uv_animation\s+rotaroundcenter="1"\s+mapchannel="2">(.*?)</uv_animation>', bp, re.S)
        if u:
            va = re.search(r'<uv_property\s+name="u_offset"[\s\S]*?<key\s+frame="1"\s+value="([^"]+)"\s*/>\s*<key\s+frame="[^"]+"\s+value="([^"]+)"', u.group(1))
            if va:
                out["u2_start"], out["u2_end"] = va.group(1), va.group(2)
    return out


def bullet_beam_build(d):
    """改光束弹丸视觉：omni 灯 RGB（颜色）+ 主体光束材质 + u_offset 滚动起止。
    目标 mod 无同名组件则复制再改；与当前一致不写。"""
    eid = (d.get("eid") or "").strip()
    tmod = os.path.normpath(d.get("target_mod") or MOD_DIR)
    r_, g_, b_ = (d.get("r") or "").strip(), (d.get("g") or "").strip(), (d.get("b") or "").strip()
    material = (d.get("material") or "").strip()
    u2s, u2e = (d.get("u2_start") or "").strip(), (d.get("u2_end") or "").strip()
    if not eid:
        return {"ok": False, "error": "缺少弹丸"}
    if not (r_ or g_ or b_ or material or u2s or u2e):
        return {"ok": False, "error": "没有可写入的修改"}
    if material and not re.match(r'^[a-zA-Z0-9_.]+$', material):
        return {"ok": False, "error": "材质名格式错误"}
    comp = _bullet_comp_for_id(eid)
    if not comp or not os.path.isfile(comp):
        return {"ok": False, "error": "未找到弹丸组件文件（光束在组件里）"}
    cur = bullet_beam_read(eid)
    def same(a, cv):
        return (not a) or (a == cv)
    if same(r_, cur["r"]) and same(g_, cur["g"]) and same(b_, cur["b"]) and same(material, cur["material"]) \
       and same(u2s, cur["u2_start"]) and same(u2e, cur["u2_end"]):
        return {"ok": True, "created": [], "unchanged": True}
    tgt = os.path.join(tmod, "assets", "fx", "weaponFx", eid + ".xml")
    if not os.path.isfile(tgt):
        os.makedirs(os.path.dirname(tgt), exist_ok=True)
        # diff 补丁型源组件先合并 base 再写入（直接复制 <diff> 原文游戏无法加载）
        open(tgt, "w", encoding="utf-8").write(_read_comp_txt(comp))
    t2 = open(tgt, encoding="utf-8", errors="ignore").read()
    nt = t2
    if r_:
        nt = re.sub(r'(<omni\b[^>]*\br=")[0-9.]+(")', r'\g<1>' + r_ + r'\g<2>', nt, count=1)
    if g_:
        nt = re.sub(r'(<omni\b[^>]*\bg=")[0-9.]+(")', r'\g<1>' + g_ + r'\g<2>', nt, count=1)
    if b_:
        nt = re.sub(r'(<omni\b[^>]*\bb=")[0-9.]+(")', r'\g<1>' + b_ + r'\g<2>', nt, count=1)
    if material:
        full = _bullet_beam_ref(material)
        def repl_beam(m):
            return re.sub(r'(<material\s+id="1"\s+ref=")[^"]*(")', r'\g<1>' + full + r'\g<2>', m.group(0), count=1) \
                if re.search(r'<material[^>]*ref="[^"]*beam', m.group(0)) else m.group(0)
        nt = re.sub(r'(?s)(<part\s+name="[^"]*".*?</part>)', repl_beam, nt)
    if u2s or u2e:
        def rep_u2(m):
            b = m.group(1)
            if u2s:
                b = re.sub(r'(<key\s+frame="1"\s+value=")[^"]*(")', r'\g<1>' + u2s + r'\g<2>', b, count=1)
            if u2e:
                b = re.sub(r'(<key\s+frame="(?!1")[^"]*"\s+value=")[^"]*(")', r'\g<1>' + u2e + r'\g<2>', b, count=1)
            return b
        nt = re.sub(r'(<uv_animation\s+rotaroundcenter="1"\s+mapchannel="2">.*?</uv_animation>)', rep_u2, nt, count=1)
    open(tgt, "w", encoding="utf-8", newline="").write(nt)
    created = [os.path.relpath(tgt, tmod)]
    try:
        copy_to_moding(mod=tmod, items=created)
        bullet_cache_refresh_source(tmod)  # 弹丸缓存增量维护（免全盘冷扫）
        _refresh_soft()                    # 材质/视觉参考等轻量失效
    except Exception:
        pass
    return {"ok": True, "created": created}
def _bullet_body_part(t2):
    """弹体 part：第一个有材质、且名称不含附加层词（shockwave/distortion/glow/core）的 part。
    返回 (part块, part名, 材质完整ref)。"""
    for pm in re.finditer(r'(?s)<part\s+name="([^"]*)".*?</part>', t2):
        mm = re.search(r'<material\s+id="1"\s+ref="([^"]+)"', pm.group(0))
        if mm:
            nm = pm.group(1).lower()
            if any(w in nm for w in ("shockwave", "distortion", "glow", "core")):
                continue
            return pm.group(0), pm.group(1), mm.group(1)
    return None, None, None


def bullet_vis_read(eid, comp_path=None):
    """读弹丸组件全部视觉层：弹体（主体材质）+ shockwave 拖尾 + omni 光点 + uv 滚动。
    comp_path 可指定组件文件路径（新增模式组件未落盘时读模板组件做同值守卫）。"""
    out = {"body_part": "", "body_material": "", "omni_r": "", "omni_g": "", "omni_b": "",
           "shock_material": "", "uv2s": "", "uv2e": "", "uv3s": "", "uv3e": "",
           "u2s": "", "u2e": ""}
    if not eid and not comp_path:
        return out
    comp = comp_path or _bullet_comp_for_id(eid)
    if not comp or not os.path.isfile(comp):
        return out
    try:
        t2 = _read_comp_txt(comp)
    except Exception:
        return out
    bp, bpn, bm = _bullet_body_part(t2)
    if bp:
        out["body_part"] = bpn
        out["body_material"] = _bullet_mat_bare(bm)
        u = re.search(r'<uv_animation\s+rotaroundcenter="1"\s+mapchannel="2">(.*?)</uv_animation>', bp, re.S)
        if u:
            va = re.search(r'<uv_property\s+name="u_offset"[\s\S]*?<key\s+frame="1"\s+value="([^"]+)"\s*/>\s*<key\s+frame="[^"]+"\s+value="([^"]+)"', u.group(1))
            if va:
                out["u2s"], out["u2e"] = va.group(1), va.group(2)
    om = re.search(r'<omni\b[^>]*\br="([0-9.]+)"[^>]*\bg="([0-9.]+)"[^>]*\bb="([0-9.]+)"', t2)
    if om:
        out["omni_r"], out["omni_g"], out["omni_b"] = om.group(1), om.group(2), om.group(3)
    sh = re.search(r'(?s)<part\s+name="[^"]*shockwave[^"]*".*?</part>', t2)
    if sh:
        b = sh.group(0)
        mm = re.search(r'<material\s+id="1"\s+ref="([^"]+)"', b)
        if mm:
            out["shock_material"] = _bullet_mat_bare(mm.group(1))
        def uv(mapc):
            u = re.search(r'<uv_animation\s+rotaroundcenter="1"\s+mapchannel="%d">(.*?)</uv_animation>' % mapc, b, re.S)
            if not u:
                return "", ""
            va = re.search(r'<uv_property\s+name="v_offset"[\s\S]*?<key\s+frame="1"\s+value="([^"]+)"\s*/>\s*<key\s+frame="[^"]+"\s+value="([^"]+)"', u.group(1))
            return (va.group(1), va.group(2)) if va else ("", "")
        out["uv2s"], out["uv2e"] = uv(2)
        out["uv3s"], out["uv3e"] = uv(3)
    # laser 标记已移除：Connection_Laser01 是所有弹丸的通用 muzzle 挂点（tags="laser"），非光束类型标识，无区分度
    return out


def bullet_vis_build(d):
    """写弹丸组件视觉层（并列层一起处理）：弹体材质 / shockwave 拖尾材质+v_offset / omni RGB / uv u_offset。
    目标 mod 无同名组件则复制再改；与当前一致不写；新增模式（new_id）由 generate 整体复制组件后在此应用各层。"""
    eid = (d.get("eid") or "").strip()
    tmod = os.path.normpath(d.get("target_mod") or MOD_DIR)
    body_material = (d.get("body_material") or "").strip()
    r_, g_, b_ = (d.get("omni_r") or "").strip(), (d.get("omni_g") or "").strip(), (d.get("omni_b") or "").strip()
    shock_material = (d.get("shock_material") or "").strip()
    uv = {}
    for k in ("uv2s", "uv2e", "uv3s", "uv3e", "u2s", "u2e"):
        v = (d.get(k) or "").strip()
        if v:
            uv[k] = v
    if not eid:
        return {"ok": False, "error": "缺少弹丸"}
    if not (body_material or r_ or g_ or b_ or shock_material or uv):
        return {"ok": False, "error": "没有可写入的修改"}
    for m in (body_material, shock_material):
        if m and not re.match(r'^[a-zA-Z0-9_.]+$', m):
            return {"ok": False, "error": "材质名格式错误"}
    comp = _bullet_comp_for_id(eid)
    tpl = (d.get("template") or "").strip()
    cur_src = comp if (comp and os.path.isfile(comp)) else (_bullet_comp_for_id(tpl) if tpl else None)
    if not cur_src:
        return {"ok": False, "error": "未找到弹丸组件文件（视觉在组件里，且未提供模板）"}
    cur = bullet_vis_read(eid, cur_src)
    def same(a, cv):
        return (not a) or (a == cv)
    if same(body_material, cur["body_material"]) and same(r_, cur["omni_r"]) and same(g_, cur["omni_g"]) \
       and same(b_, cur["omni_b"]) and same(shock_material, cur["shock_material"]) \
       and same(uv.get("uv2s"), cur["uv2s"]) and same(uv.get("uv2e"), cur["uv2e"]) \
       and same(uv.get("uv3s"), cur["uv3s"]) and same(uv.get("uv3e"), cur["uv3e"]) \
       and same(uv.get("u2s"), cur["u2s"]) and same(uv.get("u2e"), cur["u2e"]):
        return {"ok": True, "created": [], "unchanged": True}
    tgt = os.path.join(tmod, "assets", "fx", "weaponFx", eid + ".xml")
    extra_created = []
    if not os.path.isfile(tgt):
        if comp and os.path.isfile(comp):
            os.makedirs(os.path.dirname(tgt), exist_ok=True)
            # diff 补丁型源组件先合并 base 再写入（直接复制 <diff> 原文游戏无法加载）
            open(tgt, "w", encoding="utf-8").write(_read_comp_txt(comp))
        else:
            c2 = _bullet_comp_for_id(tpl)
            if not c2 or not os.path.isfile(c2):
                return {"ok": False, "error": "未找到模板组件文件"}
            dst_dir = os.path.join(tmod, "assets", "fx", "weaponFx")
            cre, copied = _copy_rename_asset(os.path.dirname(c2), tpl, dst_dir, eid)
            if not copied:
                return {"ok": False, "error": "模板组件复制失败"}
            extra_created = [os.path.relpath(p, tmod) for p in cre]
    t2 = open(tgt, encoding="utf-8", errors="ignore").read()
    nt = t2
    if body_material:
        full = _bullet_mat_ref(body_material)
        def repl(m):
            blk = m.group(0)
            nm = re.search(r'<part name="([^"]+)"', blk).group(1).lower()
            if any(w in nm for w in ("shockwave", "distortion", "glow", "core")):
                return blk
            return re.sub(r'(<material\s+id="1"\s+ref=")[^"]*(")', r'\g<1>' + full + r'\g<2>', blk, count=1)
        nt = re.sub(r'(?s)(<part\s+name="[^"]*".*?</part>)', repl, nt)
    if r_:
        nt = re.sub(r'(<omni\b[^>]*\br=")[0-9.]+(")', r'\g<1>' + r_ + r'\g<2>', nt, count=1)
    if g_:
        nt = re.sub(r'(<omni\b[^>]*\bg=")[0-9.]+(")', r'\g<1>' + g_ + r'\g<2>', nt, count=1)
    if b_:
        nt = re.sub(r'(<omni\b[^>]*\bb=")[0-9.]+(")', r'\g<1>' + b_ + r'\g<2>', nt, count=1)
    if shock_material:
        full = _bullet_mat_ref(shock_material)
        nt = re.sub(r'(?s)(<part\s+name="[^"]*shockwave[^"]*".*?</part>)',
                    lambda m: re.sub(r'(<material\s+id="1"\s+ref=")[^"]*(")', r'\g<1>' + full + r'\g<2>', m.group(1), count=1),
                    nt, count=1)
    for mapc, (sk, ek) in ((2, ("uv2s", "uv2e")), (3, ("uv3s", "uv3e"))):
        if sk not in uv and ek not in uv:
            continue
        pat = re.compile(r'(<uv_animation\s+rotaroundcenter="1"\s+mapchannel="%d">.*?</uv_animation>)' % mapc, re.S)
        def rep(m):
            b = m.group(1)
            if sk in uv:
                b = re.sub(r'(<key\s+frame="1"\s+value=")[^"]*(")', r'\g<1>' + uv[sk] + r'\g<2>', b, count=1)
            if ek in uv:
                b = re.sub(r'(<key\s+frame="(?!1")[^"]*"\s+value=")[^"]*(")', r'\g<1>' + uv[ek] + r'\g<2>', b, count=1)
            return b
        nt = pat.sub(rep, nt, count=1)
    if "u2s" in uv or "u2e" in uv:
        def rep_u2(m):
            b = m.group(1)
            if "u2s" in uv:
                b = re.sub(r'(<key\s+frame="1"\s+value=")[^"]*(")', r'\g<1>' + uv["u2s"] + r'\g<2>', b, count=1)
            if "u2e" in uv:
                b = re.sub(r'(<key\s+frame="(?!1")[^"]*"\s+value=")[^"]*(")', r'\g<1>' + uv["u2e"] + r'\g<2>', b, count=1)
            return b
        nt = re.sub(r'(<uv_animation\s+rotaroundcenter="1"\s+mapchannel="2">.*?</uv_animation>)', rep_u2, nt, count=1)
    open(tgt, "w", encoding="utf-8", newline="").write(nt)
    created = list(dict.fromkeys(extra_created + [os.path.relpath(tgt, tmod)]))
    try:
        copy_to_moding(mod=tmod, items=created)
        bullet_cache_refresh_source(tmod)  # 弹丸缓存增量维护（免全盘冷扫）
        _refresh_soft()                    # 材质/视觉参考等轻量失效
    except Exception:
        pass
    return {"ok": True, "created": created}


    """全局定位参考特效 <effect name=ref_type>...</effect> 完整块，返回 (块, 源文件)。"""
    for pp in _trail_effect_files():
        try:
            t = open(pp, encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        m = re.search(r'<effect\s+name="%s"[^>]*>.*?</effect>' % re.escape(ref_type), t, re.S)
        if m:
            return m.group(0), pp
    return None, None

def _eq_comp_for_id(cls, eid, mod):
    """定位装备组件文件：优先目标 mod assets/props 下，否则全资产树。"""
    base = os.path.join(mod, "assets", "props")
    if os.path.isdir(base):
        for r, _, fs in os.walk(base):
            if eid + ".xml" in fs:
                return os.path.join(r, eid + ".xml")
    return _find_comp_global(eid)

def _effect_attrs(blk):
    """从参考特效块解析各属性 dict + material。"""
    attrs = {}
    if not blk:
        return attrs
    m = re.match(r'<effect\b([^>]*)>', blk)
    if m:
        for k, v in re.findall(r'([a-z_]+)="([^"]*)"', m.group(1)):
            if k != "name":
                attrs[k] = v
    mm = re.search(r'<material\s+name="([^"]*)"', blk)
    if mm:
        attrs["material"] = mm.group(1)
    return attrs

_TRAIL_FIELDS = ["duration", "width", "taper", "fadestart", "timestep", "maxtimestep",
                 "timestepbase", "maxdistance", "initialvelocity", "decay"]

def trail_build(d):
    """根据参考特效新建专属特效：以参考特效属性为默认值，参数覆盖，写入目标 mod 并让组件引用新 type。不改共享特效。"""
    cls = d.get("cls")
    eid = (d.get("id") or "").strip().lower()
    mod = os.path.normpath(d.get("target_mod") or MOD_DIR)
    ref_type = (d.get("ref_type") or "").strip()
    new_type = (d.get("new_type") or "").strip().lower()
    if not ref_type or not eid or not new_type:
        return {"ok": False, "error": "缺少参考特效/装备ID/新特效名"}
    if not re.match(r'^[a-z][a-z0-9_]*$', new_type):
        return {"ok": False, "error": "新特效名格式错误，应用小写字母/数字/下划线"}
    blk, src = _find_trail_effect(ref_type)
    if not blk:
        return {"ok": False, "error": "参考特效 %s 未找到" % ref_type}
    lib_dir = os.path.join(mod, "libraries")
    os.makedirs(lib_dir, exist_ok=True)
    tgt = os.path.join(lib_dir, "trail_effects.xml")
    tgt_norm = os.path.normpath(tgt)
    update_mode = False
    for pp in _trail_effect_files():
        try:
            t = open(pp, encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        if re.search(r'<effect\s+name="%s"[ >]' % re.escape(new_type), t):
            if os.path.normpath(pp) == tgt_norm:
                update_mode = True        # 目标 mod 自有 → 更新参数
            else:
                return {"ok": False, "error": "特效名 %s 已被其他 mod 使用，请换名" % new_type}
    attrs = _effect_attrs(blk)
    p = d.get("params") or {}
    for k in _TRAIL_FIELDS:
        v = p.get(k)
        if v not in (None, ""):
            attrs[k] = str(v)
    material = (p.get("material") if p.get("material") else attrs.get("material", "trails.missile_torpedo"))
    nblk = '<effect name="%s"' % new_type
    for k in _TRAIL_FIELDS:
        if k in attrs:
            nblk += ' %s="%s"' % (k, attrs[k])
    nblk += '>\n\t\t\t<parameters>\n\t\t\t\t<material name="%s"/>\n\t\t\t</parameters>\n\t\t</effect>' % material
    created = []
    if update_mode:
        t = open(tgt, encoding="utf-8", errors="ignore").read()
        pat = re.compile(r'<effect\s+name="%s"[^>]*>.*?</effect>' % re.escape(new_type), re.S)
        n_t = pat.sub(lambda m: nblk, t, count=1)
        open(tgt, "w", encoding="utf-8", newline="").write(n_t)
        created.append(os.path.relpath(tgt, mod))
    elif not os.path.isfile(tgt):
        open(tgt, "w", encoding="utf-8", newline="").write(
            DIFF_HEADER + '\t<add sel="//effects">\n\t\t%s\n\t</add>\n</diff>\n' % nblk)
        created.append(os.path.relpath(tgt, mod))
    else:
        t = open(tgt, encoding="utf-8", errors="ignore").read()
        m = re.search(r'<add\s+sel="//effects">', t)
        if m:
            t = t[:m.end()] + "\n\t\t" + nblk + t[m.end():]
        else:
            t = t.replace("</diff>", '\t<add sel="//effects">\n\t\t%s\n\t</add>\n</diff>' % nblk, 1)
        open(tgt, "w", encoding="utf-8", newline="").write(t)
        created.append(os.path.relpath(tgt, mod))
    comp = _eq_comp_for_id(cls, eid, mod)
    if not comp or not os.path.isfile(comp):
        return {"ok": False, "error": "未找到装备组件文件，无法写入特效引用", "created": created}
    ct = open(comp, encoding="utf-8", errors="ignore").read()
    nct = _set_trail_type(ct, new_type)
    if nct != ct:
        open(comp, "w", encoding="utf-8").write(nct)
        try:
            created.append(os.path.relpath(comp, mod))
        except ValueError:
            created.append(comp)
    copy_to_moding(mod, created)
    bullet_cache_refresh_source(mod)  # 弹丸缓存增量维护（免全盘冷扫）
    _refresh_soft()
    return {"ok": True, "new_type": new_type, "created": created, "src": src}
def trail_refs():
    """扫描所有导弹组件里的 trailemitter type（去重+计数+中文名），供尾焰轨迹同类参考。"""
    from collections import Counter
    c = Counter()
    for it in (equip_scan().get("missile") or {}).values():
        try:
            t = open(it["path"], encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        ref = _read_macro_ref(it["path"])
        comp = _equip_component(it["path"], ref) if ref else None
        if not comp and ref:
            comp = _find_comp_global(ref)
        if not comp:
            continue
        try:
            _ct = _read_comp_txt(comp)
        except Exception:
            continue
        for em in re.finditer(r'<emitter\b[^>]*\btype="([^"]*)"', _ct):
            v = em.group(1).strip()
            if v:
                c[v] += 1
    return [{"id": k, "count": n, "zh": _trail_zh(k)} for k, n in c.most_common()]

def missile_tags_ref():
    """导弹自身类别 tags 词参考：聚合所有导弹宏 <missile ... tags>（去重+计数）。"""
    from collections import Counter
    c = Counter()
    for it in (equip_scan().get("missile") or {}).values():
        try:
            t = open(it["path"], encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        m = re.search(r'<missile\b[^>]*\btags="([^"]*)"', t)
        if m:
            for w in m.group(1).split():
                c[w] += 1
    return [{"id": w, "count": n} for w, n in c.most_common()]

def bullet_refs():
    # 弹丸数值参考：统计各弹种字段 min/中位/max；该弹种样本不足(<3)时回退全局范围
    import statistics as st
    NF = ["speed","lifetime","amount","barrelamount","delay","angle","maxhits","ricochet",
          "ammo_cap","ammo_reload","reload_rate","reload_time","heat","heat_initial",
          "damage","shielddisruption","damage_shield","repair","damage_hull","damage_delay",
          "timediff","scale","attach","range","area_dmg","area_lifetime","area_shield",
          "restitution","bullet_mass","chargetime","sticktime",
          "selfdestructmintime","selfdestructtimediff",
          "mult_traveldrive","mult_mining","mult_surface"]
    bykind = {}
    allv = {k: [] for k in NF}
    for it in bullet_scan().values():
        try:
            txt = open(it["path"], encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        f = _read_equip_fields("bullet", txt)
        kind = it.get("kind") or "?"
        d = bykind.setdefault(kind, {k: [] for k in NF})
        for k in NF:
            v = (f.get(k) or "").strip()
            if v and re.fullmatch(r"-?\d+(\.\d+)?", v):
                try:
                    fv = float(v); d[k].append(fv); allv[k].append(fv)
                except ValueError:
                    pass
    def _fmt(x):
        return int(x) if float(x).is_integer() else round(x, 2)
    def agg(arr):
        if not arr:
            return None
        return {"min": _fmt(min(arr)), "med": _fmt(st.median(arr)), "max": _fmt(max(arr))}
    out = {}
    for kind, d in bykind.items():
        if sum(len(v) for v in d.values()) == 0:
            continue
        out[kind] = {k: (agg(v) if len(v) >= 3 else agg(allv[k])) for k, v in d.items()}
    out["_all"] = {k: agg(allv[k]) for k in NF}
    return out

_BULLET_VIS_REFS = None
def _bullet_vis_inputs():
    """视觉参考输入：弹丸宏目录（按来源）+ props 组件树（弹丸组件都在这里）。
    只做签名 stat，不逐个解析组件路径（那样反而比扫描本身更慢）。"""
    return [_bullet_fx_dir(s) for s in ["vanilla"] + _ext_order()] + \
           [os.path.join(ROOT, "assets", "props")] + \
           [os.path.join(ROOT, "extensions", m, "assets", "props") for m in _ext_order()]

def _build_bullet_vis_refs():
    """构建弹丸视觉层参考值：全量统计 omni RGB / uv 滚动 u_offset / 拖尾 v_offset 的 min~中位~max，
    以及弹体/拖尾材质使用频率。"""
    import statistics as st
    stats = {k: [] for k in ["omni_r","omni_g","omni_b","u2s","u2e","uv2s","uv2e","uv3s","uv3e"]}
    body_mat, shock_mat = {}, {}
    for it in bullet_scan().values():
        comp = _bullet_comp_for_id(it["id"])
        if not comp or not os.path.isfile(comp):
            continue
        try:
            t2 = _read_comp_txt(comp)
        except Exception:
            continue
        om = re.search(r'<omni\b[^>]*\br="([0-9.]+)"[^>]*\bg="([0-9.]+)"[^>]*\bb="([0-9.]+)"', t2)
        if om:
            for i, k in enumerate(("omni_r","omni_g","omni_b")):
                v = om.group(i+1)
                if re.fullmatch(r"-?\d+(\.\d+)?", v):
                    try: stats[k].append(float(v))
                    except ValueError: pass
        bp, bpn, bm = _bullet_body_part(t2)
        if bm:
            bare = _bullet_mat_bare(bm)
            if bare: body_mat[bare] = body_mat.get(bare, 0) + 1
        if bp:
            u2 = re.search(r'<uv_animation\s+rotaroundcenter="1"\s+mapchannel="2">(.*?)</uv_animation>', bp, re.S)
            if u2:
                va = re.search(r'<uv_property\s+name="u_offset"[\s\S]*?<key\s+frame="1"\s+value="([^"]+)"\s*/>\s*<key\s+frame="[^"]+"\s+value="([^"]+)"', u2.group(1))
                if va:
                    for k, v in (("u2s", va.group(1)), ("u2e", va.group(2))):
                        if v and re.fullmatch(r"-?\d+(\.\d+)?", v):
                            try: stats[k].append(float(v))
                            except ValueError: pass
        sh = re.search(r'(?s)<part\s+name="[^"]*shockwave[^"]*".*?</part>', t2)
        if sh:
            b = sh.group(0)
            mm = re.search(r'<material\s+id="1"\s+ref="([^"]+)"', b)
            if mm:
                sm = _bullet_mat_bare(mm.group(1))
                if sm: shock_mat[sm] = shock_mat.get(sm, 0) + 1
            def uv(mapc):
                u = re.search(r'<uv_animation\s+rotaroundcenter="1"\s+mapchannel="%d">(.*?)</uv_animation>' % mapc, b, re.S)
                if not u: return ("", "")
                va = re.search(r'<uv_property\s+name="v_offset"[\s\S]*?<key\s+frame="1"\s+value="([^"]+)"\s*/>\s*<key\s+frame="[^"]+"\s+value="([^"]+)"', u.group(1))
                return (va.group(1), va.group(2)) if va else ("", "")
            for mapc, ks in ((2, ("uv2s","uv2e")), (3, ("uv3s","uv3e"))):
                s, e = uv(mapc)
                for k, v in zip(ks, (s, e)):
                    if v and re.fullmatch(r"-?\d+(\.\d+)?", v):
                        try: stats[k].append(float(v))
                        except ValueError: pass
    def _fmt(x): return int(x) if float(x).is_integer() else round(x, 2)
    def agg(arr):
        if not arr: return None
        return {"min": _fmt(min(arr)), "med": _fmt(st.median(arr)), "max": _fmt(max(arr))}
    return {
        "range": {k: agg(v) for k, v in stats.items()},
        # 用 list 而非 tuple：与磁盘缓存 JSON 回读的结构完全一致
        "body_materials": [[k, v] for k, v in sorted(body_mat.items(), key=lambda x: -x[1])[:15]],
        "shock_materials": [[k, v] for k, v in sorted(shock_mat.items(), key=lambda x: -x[1])[:10]],
    }

def bullet_vis_refs():
    """弹丸视觉层参考值（弹丸选项卡）：内存 + 磁盘双层缓存（弹丸宏+组件签名校验）。"""
    global _BULLET_VIS_REFS
    if _BULLET_VIS_REFS is None:
        _BULLET_VIS_REFS = _cached_whole("bullet_vis.json", _bullet_vis_inputs(),
                                         _build_bullet_vis_refs)
    return _BULLET_VIS_REFS

def _find_data_dir(comp_dir, eid, comp_path):
    """反查装备数据目录：优先按 <组件名>_data 约定；否则从组件文本里收集含 _data 的引用目录，
    取实际存在的那个。找不到返回 None。"""
    cand = os.path.join(comp_dir, eid + "_data")
    if os.path.isdir(cand):
        return cand
    try:
        t = open(comp_path, encoding="utf-8", errors="ignore").read()
        for m in re.finditer(r'([A-Za-z0-9_]+)_data', t):
            d = os.path.join(comp_dir, m.group(1) + "_data")
            if os.path.isdir(d):
                return d
    except Exception:
        pass
    return None

def equip_geometry(ref):
    # find component by component-ref item id, return its source geometry path
    if not ref:
        return ""
    comp = _find_comp_global(ref)
    return _comp_source_geometry(comp) if comp else ""


def equip_chain(cls, eid):
    """引用链自动发现：某装备 macro → component → 数据目录，
    武器/炮台额外沿 <bullet class> 找到其弹丸 macro → component → 数据目录。
    纯只读，不修改文件；用于补全关联模型/数据目录。"""
    if cls == "bullet":
        it = next((x for x in bullet_scan().values() if x["id"] == eid), None)
    else:
        it = (equip_scan().get(cls) or {}).get(eid)
    if not it:
        return {"ok": False, "error": "未找到 %s/%s" % (cls, eid)}
    mac = it["path"]
    out = {"ok": True, "cls": cls, "id": eid, "source": it["source"], "macro": mac}
    ref = _read_macro_ref(mac)
    out["ref"] = ref                    # macro 关联的物品 id（component ref 目标）
    comp = _equip_component(mac, ref) if ref else None
    if not comp and ref:
        comp = _find_comp_global(ref)   # 组件可能在原版/其他 mod，跨资产树兜底
    out["component"] = comp
    if comp:
        out["geometry"] = _comp_source_geometry(comp) or None
    if cls in ("weapon", "turret"):
        try:
            t = open(mac, encoding="utf-8", errors="ignore").read()
        except Exception:
            t = ""
        m = re.search(r'<bullet\s+class="([^"]+)"', t)
        b = m.group(1) if m else ""
        if b.endswith("_macro"):
            b = b[:-len("_macro")]
        if b:
            # 弹丸子链：优先从弹丸宏列表定位；无同名宏时直接按 ref 全局找组件（组件可独立存在）
            bit = next((x for x in bullet_scan().values() if x["id"] == b), None)
            if bit:
                bref = _read_macro_ref(bit["path"])
                bcomp = _equip_component(bit["path"], bref) if bref else None
                entry = {"id": b, "macro": bit["path"], "ref": bref}
            else:
                bref = b
                bcomp = None
                entry = {"id": b, "ref": bref}
            if not bcomp and bref:
                bcomp = _find_comp_global(bref)
            entry["component"] = bcomp
            entry["geometry"] = _comp_source_geometry(bcomp) if bcomp else None
            out["bullet"] = entry
    return out

# ---------- HTTP ----------
def delitem(d):
    """删除目标 mod 下某物品的文件（宏/组件/组件_data），并清除其注册条目。安全约束：
    1) 只允许删指定扩展 mod 下的文件，不触碰原版/其他 mod；
    2) 注册/索引文件（index/、libraries/wares.xml、t/ 语言）视为随物品维护，删除时一并清条目，不算外部引用；
    3) 删除前做全解包根反向引用检查——任何其他物品（宏/组件）引用该 id 即阻止，避免破坏游戏共用。"""
    iid = (d.get("id") or "").strip()
    tmod = (d.get("target_mod") or "").strip()
    if not iid:
        return {"ok": False, "error": "缺少物品 id"}
    if not tmod:
        return {"ok": False, "error": "缺少目标 mod"}
    if os.path.isabs(iid) or ".." in iid or "/" in iid or "\\" in iid:
        return {"ok": False, "error": "非法 id"}
    # target_mod 兼容两种形式：完整路径（与 generate/edit 一致）或 extensions 下的目录名
    if os.path.isabs(tmod):
        mdir = os.path.normpath(tmod)
    else:
        mdir = os.path.join(ROOT, "extensions", tmod)
    if not os.path.isdir(mdir):
        return {"ok": False, "error": "目标 mod 目录不存在: " + tmod}
    fn_macro = iid + "_macro.xml"; fn_comp = iid + ".xml"; fn_ani = iid + "_data.ani"; dir_data = iid + "_data"
    doomed = []
    for base, dirs, files in os.walk(mdir):
        for f in files:
            if f in (fn_macro, fn_comp, fn_ani):
                doomed.append(os.path.join(base, f))
        for dd in list(dirs):
            if dd == dir_data:
                doomed.append(os.path.join(base, dd))
    if not doomed:
        return {"ok": False, "error": "目标 mod 下未找到该物品文件（可能来自其他 mod，或不存在）"}
    doomed = list(dict.fromkeys(doomed))
    # 舰船：收集本船 component 引用的材质（collection.material），删除后用于孤儿材质清理
    kind = (d.get("kind") or "").strip()
    ship_mat_refs = set()
    if kind == "ship":
        for p in doomed:
            if not (os.path.isfile(p) and os.path.basename(p).lower() == fn_comp):
                continue
            try:
                ct = open(p, encoding="utf-8", errors="ignore").read()
            except Exception:
                continue
            for mm in re.finditer(r'<material\b[^>]*\bref="([^"]+)"', ct):
                ship_mat_refs.add(mm.group(1))
    # 附属件发现（如舰船的 storage_*/dockarea_* 专属件）：从待删文件的 ref= 引用中找出
    # "命名含物品核心名且文件在目标 mod 内"的候选；随后在反向引用扫描中一并校验，
    # 只有候选无任何外部引用（专属）才随物品一并删除，有外部引用则保留不动
    core = iid.split("_", 1)[1] if "_" in iid else iid   # ship_spl_xl_golem → spl_xl_golem
    _stem2path = {}
    for bp, _, ff in os.walk(mdir):
        for f in ff:
            if f.lower().endswith(".xml"):
                _stem2path.setdefault(f[:-4], os.path.join(bp, f))
    _cands = []                     # 附属件 base id（有序去重）
    for p in doomed:
        if not (os.path.isfile(p) and p.lower().endswith(".xml")):
            continue
        try:
            at = open(p, encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        for mm in re.finditer(r'\bref="([A-Za-z0-9_]+)"', at):
            nm = mm.group(1)
            base = nm[:-6] if nm.endswith("_macro") else nm
            if core not in base or base == iid or base in _cands:
                continue
            if _stem2path.get(base) or _stem2path.get(base + "_macro"):
                _cands.append(base)
    _candfiles_nc = set()           # 候选文件路径（normcase），扫描时与待删文件同等排除
    _candf2base = {}
    for c in _cands:
        for q in (_stem2path.get(c), _stem2path.get(c + "_macro")):
            if q:
                _candfiles_nc.add(os.path.normcase(q))
                _candf2base[os.path.normcase(q)] = c
    _cand_esc = [re.escape(c) for c in _cands]
    _candre = re.compile(r'(?:ref|class|name|effect|geometry)="[^"]*(' + "|".join(_cand_esc) + r')[^"]*"') if _cand_esc else None
    _cand_map = dict(zip(_cand_esc, _cands))
    _cand_ext = dict((c, False) for c in _cands)    # 候选是否被外部引用（非专属）
    _cand_main = dict((c, False) for c in _cands)   # 候选自身文件是否引用主物品
    # 注册/索引文件（随物品维护，不算外部引用）
    reg_files = set()
    idx = os.path.join(mdir, "index")
    if os.path.isdir(idx):
        for bp, _, ff in os.walk(idx):
            for f in ff:
                if f.lower().endswith(".xml"):
                    reg_files.add(os.path.join(bp, f))
    wf = os.path.join(mdir, "libraries", "wares.xml")
    if os.path.isfile(wf):
        reg_files.add(wf)
    # icons.xml 同为随物品维护的注册文件（upgrade_<物品>_macro / ship_<物品>_macro 别名条目，
    # 删除流程下方 _remove_mod_icon 一并清理），其 name 属性含物品 id，不排除会被误判为外部引用
    icf = os.path.join(mdir, "libraries", "icons.xml")
    if os.path.isfile(icf):
        reg_files.add(icf)
    # 反向引用检查：仅扫游戏会加载的路径（标准顶层目录 + extensions 各 mod 内部），
    # 跳过解包根下非游戏目录（如自定义备份目录）与 mod 内 moding 副本；排除待删文件和注册文件
    idre = r'(?:ref|class|name|effect|geometry)="[^"]*' + re.escape(iid) + r'[^"]*"'
    refs = []
    _scan_tops = {"assets", "libraries", "md", "t", "aiscripts", "index", "extensions"}
    for bp, bdirs, bfiles in os.walk(ROOT):
        rel = os.path.relpath(bp, ROOT)
        top = rel.split(os.sep)[0] if rel != "." else ""
        if top and top not in _scan_tops:
            bdirs[:] = []          # 剪枝：不进入非游戏加载顶层目录
            continue
        bdirs[:] = [dd for dd in bdirs if dd != "moding"]
        for f in bfiles:
            if not f.lower().endswith(".xml"):
                continue
            fp = os.path.join(bp, f)
            if fp in doomed or fp in reg_files:
                continue
            fnc = os.path.normcase(fp)
            if fnc in _candfiles_nc:
                # 候选文件自身：只记录它对主物品的引用；它对其他候选/待删文件的引用
                # 属删除集合内部，不算外部引用
                try:
                    t = open(fp, encoding="utf-8", errors="ignore").read()
                except Exception:
                    continue
                if re.search(idre, t):
                    _cand_main[_candf2base.get(fnc, "")] = True
                continue
            try:
                t = open(fp, encoding="utf-8", errors="ignore").read()
            except Exception:
                continue
            if _candre:
                for mm in _candre.finditer(t):
                    _cand_ext[_cand_map[mm.group(1)]] = True
            if re.search(idre, t):
                refs.append(os.path.relpath(fp, ROOT))
                if len(refs) >= 40:
                    break
        if len(refs) >= 40:
            break
    # 附属件定案：无外部引用（专属）才随物品删除；
    # 非专属（被外部保留）且其自身引用主物品 → 会留悬空引用，视为外部引用阻止删除
    subs = []
    for c in _cands:
        if _cand_ext[c]:
            if _cand_main.get(c):
                refs.append("附属件 " + c + " 被外部文件保留且其自身引用本物品")
        else:
            subs.append(c)
    for c in subs:
        for q in (_stem2path.get(c), _stem2path.get(c + "_macro")):
            if q:
                doomed.append(q)
    if subs:
        for bp, bdirs, _ff in os.walk(mdir):
            for dd in list(bdirs):
                if any(dd in (c + "_data", c + "_data.ani") for c in subs):
                    doomed.append(os.path.join(bp, dd))
        doomed = list(dict.fromkeys(doomed))
    if refs:
        return {"ok": False, "error": "该物品仍被其他物品引用，删除会破坏游戏共用", "refs": refs}
    # 收集该物品 t 文本 id（name/description 的 {page,tid}），用于清语言条目
    tids = set()
    def _collect_tids(text):
        for mm in re.finditer(r'(?:name|description)="\{(\d+),(\d+)\}"', text):
            tids.add((int(mm.group(1)), int(mm.group(2))))
    for p in doomed:
        if os.path.isfile(p):
            try:
                _collect_tids(open(p, encoding="utf-8", errors="ignore").read())
            except Exception:
                pass
    if os.path.isfile(wf):
        try:
            _wtxt = open(wf, encoding="utf-8", errors="ignore").read()
            _wb = re.search(r'<ware\s+id="' + re.escape(iid) + r'"[^>]*>.*?</ware>', _wtxt, re.S)
            if _wb:
                _collect_tids(_wb.group(0))  # 只收该物品自身 ware 块的 t 引用；禁止全表扫描（会殃及其他 ware 的文本条目）
        except Exception:
            pass
    removed = []
    import shutil
    for p in doomed:
        try:
            if os.path.isdir(p):
                shutil.rmtree(p)
            else:
                os.remove(p)
            removed.append(os.path.relpath(p, ROOT))
        except Exception as e:
            return {"ok": False, "error": "删除文件失败: " + str(e), "removed": removed}
    # 清除注册条目（flags：re.S 等，用于多行块匹配）
    def strip_entry(fp, pat, flags=0, label=""):
        try:
            t = open(fp, encoding="utf-8", errors="ignore").read()
        except Exception:
            return
        nt = re.sub(pat, "", t, flags=flags)
        nt = re.sub(r"\n(?:[ \t]+\n)+", "\n", nt)   # 收尾：压掉删条目留下的纯空白孤儿行
        if nt != t:
            try:
                open(fp, "w", encoding="utf-8", newline="").write(nt)
                removed.append(os.path.relpath(fp, ROOT) + ("（清除条目: " + label + "）" if label else "（清除条目）"))
            except Exception as e:
                removed.append(os.path.relpath(fp, ROOT) + ("（清条目失败 " + label + ": " + str(e) + "）" if label else "（清条目失败: " + str(e) + "）"))
    # 主物品 + 专属附属件 一并清除注册条目（index / wares；附属件通常无 ware，模式不中即跳过）
    for sid in [iid] + subs:
        strip_entry(os.path.join(mdir, "index", "macros.xml"), r'<entry\s+name="' + re.escape(sid) + r'_macro"[^>]*/>', label=sid + "_macro")
        strip_entry(os.path.join(mdir, "index", "components.xml"), r'<entry\s+name="' + re.escape(sid) + r'"[^>]*/>', label=sid)
        strip_entry(wf, r'<ware\s+id="' + re.escape(sid) + r'"[^>]*>.*?</ware>', re.S, label=sid)
        # 列表图标别名条目（upgrade_<物品>_macro）随物品清理
        _ric = _remove_mod_icon(mdir, "upgrade_%s_macro" % sid)
        if _ric:
            removed.append(_ric + "（清图标别名）")
        # 舰船图标别名（ship_<sid>_macro）也随物品清理
        _ric2 = _remove_mod_icon(mdir, "ship_%s_macro" % sid)
        if _ric2:
            removed.append(_ric2 + "（清舰船图标别名）")
    # mod 自有注册库中该物品的引用条目随物品清理（非外部引用，防残留孤儿）：
    # shipgroups.xml 的 <select macro="{iid}_macro"/>；jobs.xml 中 id 内嵌该物品宏名的整个 <job> 块。
    # ships.xml 无逐船引用机制（仅分组/pilot/drop 定义），无需清理。
    _mesc = re.escape(iid) + r'_macro'
    strip_entry(os.path.join(mdir, "libraries", "shipgroups.xml"), r'<select\b[^>]*\bmacro="' + _mesc + r'"[^>]*/>', label="shipgroups " + iid + "_macro")
    strip_entry(os.path.join(mdir, "libraries", "jobs.xml"), r'<job\b[^>]*\bid="[^"]*' + _mesc + r'[^"]*"[^>]*>.*?</job>', re.S, label="jobs " + iid + "_macro")
    # 清除该物品 t 语言条目（中文 + 英文）
    for tp in _loc_files(mdir):
        if not tp:
            continue
        try:
            t = open(tp, encoding="utf-8").read()
        except Exception:
            continue
        changed = False
        for page, tid in tids:
            j = t.find('<page id="%d"' % page)
            if j < 0:
                continue
            k = t.find("</page>", j)
            if k < 0:
                continue
            blk = t[j:k]
            nb = re.sub(r'<t\s+id="%d">[^<]*</t>' % tid, '', blk)
            if nb != blk:
                t = t[:j] + nb + t[k:]
                changed = True
        if changed:
            t = re.sub(r"\n(?:[ \t]+\n)+", "\n", t)   # 收尾：压掉清文本留下的纯空白孤儿行
            open(tp, "w", encoding="utf-8", newline="").write(t)
            removed.append(os.path.relpath(tp, mdir) + "（清文本条目）")
    # 孤儿材质清理（仅舰船）：删除本船 component 引用的、定义于本 mod material_library.xml 中、
    # 且删除后本 mod 内已无其他文件引用的材质定义块；空 collection 一并移除。
    # 原版/其他 mod 定义的材质不在本 mod material_library，自动跳过，不会误删。
    if ship_mat_refs:
        mlp = os.path.join(mdir, "libraries", "material_library.xml")
        ml_dooms = []
        try:
            mltxt = open(mlp, encoding="utf-8", errors="ignore").read()
        except Exception:
            mltxt = ""
        if mltxt:
            doomed_nc = {os.path.normcase(p) for p in doomed if os.path.isfile(p)}
            for ref in ship_mat_refs:
                if "." not in ref:
                    continue
                coll, mat = ref.split(".", 1)
                if not _ml_find_material_span(mltxt, coll, mat):
                    continue  # 外部材质（原版/其他 mod），不在本 mod 定义，跳过
                ref_re = re.compile(r'<material\b[^>]*\bref="' + re.escape(ref) + r'"')
                still_used = False
                # 扫描全部扩展 mod + 原版 assets：其他 mod 的 component 也可能引用本材质，
                # 有引用则保留不动，避免破坏跨 mod 共用
                scan_roots = [os.path.join(ROOT, "extensions")]
                for sr in scan_roots:
                    if not os.path.isdir(sr):
                        continue
                    for bp, _, ff in os.walk(sr):
                        for f in ff:
                            if not f.lower().endswith(".xml"):
                                continue
                            fp = os.path.join(bp, f)
                            if os.path.normcase(fp) == os.path.normcase(mlp):
                                continue
                            if os.path.normcase(fp) in doomed_nc:
                                continue
                            try:
                                if ref_re.search(open(fp, encoding="utf-8", errors="ignore").read()):
                                    still_used = True
                                    break
                            except Exception:
                                pass
                        if still_used:
                            break
                    if still_used:
                        break
                if not still_used:
                    ml_dooms.append((coll, mat))
            if ml_dooms:
                for coll, mat in ml_dooms:
                    span = _ml_find_material_span(mltxt, coll, mat)
                    if span:
                        mltxt = mltxt[:span[0]] + mltxt[span[1]:]
                mltxt = re.sub(r'<collection\s+name="[^"]*"[^>]*>\s*</collection>', "", mltxt)
                mltxt = re.sub(r"\n(?:[ \t]+\n)+", "\n", mltxt)
                try:
                    open(mlp, "w", encoding="utf-8", newline="").write(mltxt)
                    removed.append(os.path.relpath(mlp, ROOT) + "（清理孤儿材质 " + str(len(ml_dooms)) + " 项）")
                except Exception as e:
                    removed.append(os.path.relpath(mlp, ROOT) + "（清理孤儿材质失败: " + str(e) + "）")
    eq_cache_refresh_source(mdir)      # 删任意类型物品：装备/弹丸缓存都增量维护（免全盘冷扫）
    bullet_cache_refresh_source(mdir)
    _refresh_soft()
    return {"ok": True, "removed": removed}

def _refresh_soft():
    """轻量失效（不触发全盘冷扫）：t 文本表 + wares 索引置懒重建 + 各整体缓存（舰船/软件/
    宏清单/材质参考/loadout/全局资产/组件内容）。不清 equip/bullet 分片缓存——
    它们的新鲜度由 eq_cache_refresh_source/bullet_cache_refresh_source 按改动来源增量维护，
    避免下一个列表请求触发数十秒全盘冷扫。各整体缓存重建时仍会先比对磁盘签名。"""
    global _LOADOUT_CACHE, _GLOBAL_ASSETS, _BULLET_VIS_REFS, _MATREF_CACHE, _WARES_DIRTY
    global _MACRO_CATALOG, _TEMPLATES_CACHE, _SOFTWARE_CACHE
    _LOADOUT_CACHE = None
    _GLOBAL_ASSETS = None
    _BULLET_VIS_REFS = None
    _MATREF_CACHE = None   # 护盾材质参考
    _MACRO_CATALOG = None  # 挂载类宏清单（删除舰船后防已删宏残留）
    _TEMPLATES_CACHE = None  # 舰船清单（新增/删除/改名后重建）
    _SOFTWARE_CACHE = None   # 软件清单（wares 变更后重建）
    _COMPCACHE.clear()     # 组件文件内容缓存（防止删除/改文件后读到旧内容）
    _GCOMPCACHE.clear()
    _WARES_DIRTY = True    # wares owner/成本/材料索引改懒重建（_find_ware 触发）
    try:
        LX._loc.clear()    # t 文本表失效，下次 lname/macro_display 重建（含新写入的文本）
    except Exception:
        pass
    return True

def refresh_caches():
    """全量失效（仅 /api/refresh 手动刷新端点使用）：清空全部内存缓存 + cache/ 下磁盘缓存，
    下次列表请求全盘重扫。工程内新增/删除走各流增量维护（eq_cache_refresh_source /
    bullet_cache_refresh_source + _refresh_soft），无需全盘冷扫。"""
    global _EQ_SCAN_CACHE, _EQ_DUP_CACHE, _BULLET_SCAN_CACHE, _BULLET_DUP_CACHE
    global _EQ_BY_SOURCE, _BULLET_BY_SOURCE
    _refresh_soft()
    _DIR_INDEX.clear()     # 资产索引全量重建（新增/删除大量文件后由手动刷新兜底；日常增删不清，见 _dir_index）
    _EQ_SCAN_CACHE = None
    _EQ_DUP_CACHE = None
    _EQ_BY_SOURCE = None
    _BULLET_SCAN_CACHE = None
    _BULLET_DUP_CACHE = None
    _BULLET_BY_SOURCE = None
    try:                                   # 磁盘缓存同步失效（下次重启读新扫描）
        if os.path.isdir(_CACHE_DIR):
            for f in os.listdir(_CACHE_DIR):
                try:
                    os.remove(os.path.join(_CACHE_DIR, f))
                except OSError:
                    pass
        old = os.path.join(BASE, "equip_scan.cache.json")   # 旧版单文件缓存（已弃用，顺带清理）
        if os.path.exists(old):
            os.remove(old)
    except Exception:
        pass
    return True

class H(http.server.BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body.encode("utf-8"))))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))
    def do_GET(self):
        if self.path == "/api/templates":
            # 内存 + 磁盘双层缓存（输入签名校验）：未变时免扫描，新增/修改后签名不一致自动重建
            self._send(200, json.dumps(list_templates(), ensure_ascii=False), "application/json; charset=utf-8")
        elif self.path == "/api/stats":
            # 原版 L/XL 属性参考范围
            self._send(200, json.dumps(vanilla_stats(), ensure_ascii=False), "application/json; charset=utf-8")
        elif self.path == "/api/enums":
            # 枚举型属性的标准取值（icon/type/makerrace）
            self._send(200, json.dumps(vanilla_enums(), ensure_ascii=False), "application/json; charset=utf-8")
        elif self.path == "/api/factions":
            # 完整合并派系（原版 + 所有 mod）+ jobs 任务类型；合并失败回退手写常量
            self._send(200, json.dumps({"factions": _FACTIONS_ALL or FACTIONS,
                              "categories": [{"id": c, "name": FAC_CAT_NAME[c]} for c in FAC_CAT_ORDER],
                              "tasks": JOB_TASKS},
                                       ensure_ascii=False), "application/json; charset=utf-8")
        elif self.path == "/api/costrefs":
            # 建造成本参考值 + 材料下拉列表 + 建造方式(method)枚举
            self._send(200, json.dumps({"wares": WARE_MATS, "refs": COST_REFS, "default_mats": DEFAULT_MATS,
                                         "prod_methods": PROD_METHODS},
                                       ensure_ascii=False), "application/json; charset=utf-8")
        elif self.path.startswith("/api/component"):
            # 读某舰船 component 的装备连接点与连接组（供装配预设 path/组挂载下拉）
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            ship = (q.get("ship") or [""])[0]
            src = (q.get("source") or [""])[0] or None
            self._send(200, json.dumps(component_slots(ship, src), ensure_ascii=False), "application/json; charset=utf-8")
        elif self.path.startswith("/api/shipmaterials"):
            # 读某船 component 引用的材质及其 material_library 可调参数当前值（材质模块回填）
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            ship = (q.get("ship") or [""])[0]
            src = (q.get("source") or [""])[0] or None
            self._send(200, json.dumps(ship_materials(ship, src), ensure_ascii=False), "application/json; charset=utf-8")
        elif self.path.startswith("/api/shiploadout"):
            # 读某舰船 ship macro 的默认 loadout（用于回填；无则从 component 填充）
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            ship = (q.get("ship") or [""])[0]
            src = (q.get("source") or [""])[0] or None
            self._send(200, json.dumps(ship_loadout(ship, src), ensure_ascii=False), "application/json; charset=utf-8")
        elif self.path.startswith("/api/shipjobs"):
            # 读某舰船所属 mod 现有 jobs.xml，返回该船已有 AI 派系归属（编辑模式回填）
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            ship = (q.get("ship") or [""])[0]
            src = (q.get("source") or [""])[0] or None
            self._send(200, json.dumps(ship_jobs(ship, src), ensure_ascii=False), "application/json; charset=utf-8")
        elif self.path == "/api/shipgroups/all":
            self._send(200, json.dumps(shipgroup_all(), ensure_ascii=False), "application/json; charset=utf-8")
        elif self.path.startswith("/api/shipconnections"):
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            ship = (q.get("ship") or [""])[0]
            src = (q.get("source") or [""])[0]
            self._send(200, json.dumps(ship_connections_detail(ship, src or None), ensure_ascii=False), "application/json; charset=utf-8")
        elif self.path.startswith("/api/shipgroups"):
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            ship = (q.get("ship") or [""])[0]
            self._send(200, json.dumps(ship_in_groups(ship), ensure_ascii=False), "application/json; charset=utf-8")
        elif self.path == "/api/loadoutmacros":
            # 装配预设可选装备宏（engine/shield/weapon/turret/thruster）
            self._send(200, json.dumps(loadout_macros(), ensure_ascii=False), "application/json; charset=utf-8")
        elif self.path == "/api/softwarelist":
            self._send(200, json.dumps(_software_list(), ensure_ascii=False), "application/json; charset=utf-8")
        elif self.path.startswith("/api/shipsoftware"):
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            ship = (q.get("ship") or [""])[0]
            src = (q.get("source") or [""])[0] or None
            tpl = next((t for t in list_templates() if t["id"] == ship
                        and (not src or t["source"] == src)), None)
            sw = []
            if tpl:
                src_base = os.path.join(ROOT, "assets") if tpl["source"] == "vanilla" else os.path.join(ROOT, "extensions", tpl["source"], "assets")
                mp = _find_ship_macro(os.path.join(src_base, "units", "size_" + tpl["size"]), ship)
                if mp and os.path.isfile(mp):
                    sw = _ship_software(open(mp, encoding="utf-8", errors="ignore").read())
            self._send(200, json.dumps(sw, ensure_ascii=False), "application/json; charset=utf-8")
        elif self.path.startswith("/api/equipkinds"):
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            cls = (q.get("cls") or [""])[0]
            self._send(200, json.dumps(equip_kinds(cls), ensure_ascii=False), "application/json; charset=utf-8")
        elif self.path.startswith("/api/equiptemplates"):
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            cls = (q.get("cls") or [""])[0]; kind = (q.get("kind") or [""])[0]
            self._send(200, json.dumps(equip_templates(cls, kind), ensure_ascii=False), "application/json; charset=utf-8")
        elif self.path.startswith("/api/equipread"):
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            cls = (q.get("cls") or [""])[0]; eid = (q.get("id") or [""])[0]; src = (q.get("source") or [""])[0]
            self._send(200, json.dumps(equip_read(cls, eid, src, (q.get("mod") or [""])[0]), ensure_ascii=False), "application/json; charset=utf-8")
            return
        elif self.path.startswith("/api/shieldmatrefs"):
            self._send(200, json.dumps(_material_refs_all(), ensure_ascii=False), "application/json; charset=utf-8")
            return
        elif self.path.startswith("/api/equiptags"):
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            cls = (q.get("cls") or [""])[0]
            self._send(200, json.dumps(equip_tags(cls), ensure_ascii=False), "application/json; charset=utf-8")
        elif self.path.startswith("/api/bulletrefs"):
            self._send(200, json.dumps(bullet_refs(), ensure_ascii=False), "application/json; charset=utf-8")
        elif self.path.startswith("/api/bulleteffectlist"):
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            self._send(200, json.dumps(bullet_effect_list((q.get("tag") or [""])[0] or "impact"), ensure_ascii=False), "application/json; charset=utf-8")
        elif self.path.startswith("/api/bulleteffectread"):
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            self._send(200, json.dumps(bullet_effect_read((q.get("eid") or [""])[0]), ensure_ascii=False), "application/json; charset=utf-8")
        elif self.path.startswith("/api/bullettraillist"):
            self._send(200, json.dumps(bullet_trail_materials(), ensure_ascii=False), "application/json; charset=utf-8")
        elif self.path.startswith("/api/bullettrailread"):
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            self._send(200, json.dumps(bullet_trail_read((q.get("eid") or [""])[0]), ensure_ascii=False), "application/json; charset=utf-8")
        elif self.path.startswith("/api/bulletbeamlist"):
            self._send(200, json.dumps(bullet_beam_materials(), ensure_ascii=False), "application/json; charset=utf-8")
        elif self.path.startswith("/api/bulletbeamread"):
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            self._send(200, json.dumps(bullet_beam_read((q.get("eid") or [""])[0]), ensure_ascii=False), "application/json; charset=utf-8")
        elif self.path.startswith("/api/bulletvisread"):
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            self._send(200, json.dumps(bullet_vis_read((q.get("eid") or [""])[0]), ensure_ascii=False), "application/json; charset=utf-8")
        elif self.path.startswith("/api/bulletvislist"):
            self._send(200, json.dumps(bullet_vis_materials(), ensure_ascii=False), "application/json; charset=utf-8")
        elif self.path.startswith("/api/bulletvisrefs"):
            self._send(200, json.dumps(bullet_vis_refs(), ensure_ascii=False), "application/json; charset=utf-8")
        elif self.path.startswith("/api/equipnumrefs"):
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            cls = (q.get("cls") or [""])[0]
            self._send(200, json.dumps(equip_numeric_refs(cls), ensure_ascii=False), "application/json; charset=utf-8")
        elif self.path.startswith("/api/missileusers"):
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            mid = (q.get("id") or [""])[0]
            self._send(200, json.dumps(missile_users(mid), ensure_ascii=False), "application/json; charset=utf-8")
        elif self.path.startswith("/api/explosionusers"):
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            ref = (q.get("ref") or [""])[0]
            self._send(200, json.dumps(explosion_users(ref), ensure_ascii=False), "application/json; charset=utf-8")
        elif self.path.startswith("/api/missiletags"):
            self._send(200, json.dumps(missile_tags_ref(), ensure_ascii=False), "application/json; charset=utf-8")
        elif self.path.startswith("/api/trailrefs"):
            self._send(200, json.dumps(trail_refs(), ensure_ascii=False), "application/json; charset=utf-8")
        elif self.path.startswith("/api/explosionrefs"):
            self._send(200, json.dumps(explosion_refs(), ensure_ascii=False), "application/json; charset=utf-8")
        elif self.path.startswith("/api/explosioneffects"):
            self._send(200, json.dumps(explosion_effects(), ensure_ascii=False), "application/json; charset=utf-8")
        elif self.path.startswith("/api/trailmaterials"):
            self._send(200, json.dumps(trail_materials(), ensure_ascii=False), "application/json; charset=utf-8")
        elif self.path.startswith("/api/traileffect"):
            _q = self.path.split("?", 1)[1] if "?" in self.path else ""
            _t = (re.search(r'(?:^|&)type=([^&]+)', _q) or [None, ""])[1]
            import urllib.parse as _up
            _t = _up.unquote(_t)
            blk, src = _find_trail_effect(_t)
            if not blk:
                self._send(200, json.dumps({"ok": False, "error": "未找到特效 %s" % _t}, ensure_ascii=False), "application/json; charset=utf-8")
            else:
                a = _effect_attrs(blk); a["zh"] = _trail_zh(_t); a["source"] = src
                self._send(200, json.dumps({"ok": True, "type": _t, "attrs": a}, ensure_ascii=False), "application/json; charset=utf-8")
        elif self.path == "/api/equiprefs":
            # 装备参考值（价格/材料按 class+尺寸）
            self._send(200, json.dumps(equip_refs(), ensure_ascii=False), "application/json; charset=utf-8")
        elif self.path.startswith("/api/eqgeom"):
            # 按 component ref 物品 id 查该物品的几何模型路径（供前端几何栏联动）
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            ref = (q.get("ref") or [""])[0]
            self._send(200, json.dumps({"geometry": equip_geometry(ref)}, ensure_ascii=False), "application/json; charset=utf-8")
        elif self.path.startswith("/api/equipchain"):
            # 装备引用链自动发现（macro→component→data→bullet），只读
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            cls = (q.get("cls") or [""])[0]; eid = (q.get("id") or [""])[0]
            self._send(200, json.dumps(equip_chain(cls, eid), ensure_ascii=False), "application/json; charset=utf-8")
        elif self.path == "/api/moddirs":
            # X4 extensions 下的 mod 目录（路径选择）
            self._send(200, json.dumps(mod_dirs(), ensure_ascii=False), "application/json; charset=utf-8")
        elif self.path == "/api/docklist":
            # dock 复用模板列表（原版/DLC/mod 的 dock 类组件）
            self._send(200, json.dumps(dock_list(), ensure_ascii=False), "application/json; charset=utf-8")
        elif self.path == "/api/config":
            # 记住的目标 mod 路径
            self._send(200, json.dumps(load_config(), ensure_ascii=False), "application/json; charset=utf-8")
        elif self.path.startswith("/api/unpackscan"):
            # 游戏解包：基游戏 cat + 游戏 extensions（含松散 mod / 工坊 ws_*）+ Vortex 暂存区
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            self._send(200, json.dumps(unpack_scan((q.get("game") or [""])[0],
                                                   (q.get("staging") or [""])[0],
                                                   (q.get("workshop") or [""])[0]), ensure_ascii=False),
                       "application/json; charset=utf-8")
        elif self.path == "/api/unpackstatus":
            # 解包任务状态（log 截尾，proc 不外发）
            st = {k: v for k, v in _UNPACK.items() if k != "proc"}
            st["log"] = st["log"][-200:]
            self._send(200, json.dumps(st, ensure_ascii=False), "application/json; charset=utf-8")
        elif self.path.startswith("/api/diffvalidate"):
            # diff 离线校验：GET ?path=<diff 文件路径> 自动找 base 并校验
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            path = (q.get("path") or [""])[0]
            if not path or not os.path.isfile(path):
                self._send(200, json.dumps({"ok": False, "error": "文件不存在: %s" % path},
                                           ensure_ascii=False), "application/json; charset=utf-8")
            else:
                diff_txt = open(path, encoding="utf-8", errors="ignore").read()
                if not _is_diff_txt(diff_txt):
                    self._send(200, json.dumps({"ok": False, "error": "不是 <diff> 补丁文件"},
                                               ensure_ascii=False), "application/json; charset=utf-8")
                else:
                    base_path, base_txt = _diff_base_for(path)
                    if not base_txt:
                        self._send(200, json.dumps({"ok": False, "error": "找不到 base 组件"},
                                                   ensure_ascii=False), "application/json; charset=utf-8")
                    else:
                        r = validate_diff(diff_txt, base_txt)
                        r["diff"] = path
                        r["base"] = base_path
                        self._send(200, json.dumps(r, ensure_ascii=False), "application/json; charset=utf-8")
        elif self.path.startswith("/api/schemas"):
            # XSD 动态解析：GET ?name=<xsd 名（不含扩展名）> 返回该 schema 的枚举定义；
            # 无 name 参数时返回全部可用 schema 的枚举汇总
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            name = (q.get("name") or [""])[0]
            if name:
                r = _xsd_schema(name)
                self._send(200, json.dumps({"ok": True, "schema": name, "types": r},
                                           ensure_ascii=False), "application/json; charset=utf-8")
            else:
                r = _all_xsd_schemas()
                self._send(200, json.dumps({"ok": True, "schemas": r},
                                           ensure_ascii=False), "application/json; charset=utf-8")
        elif self.path.startswith("/api/difflist"):
            # diff 文件列表：扫描所有用户 mod 的 assets 目录，找出 <diff> 补丁文件
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            mod_filter = (q.get("mod") or [""])[0]
            out = []
            ex = os.path.join(ROOT, "extensions")
            mods = [d for d in os.listdir(ex) if os.path.isdir(os.path.join(ex, d))] if os.path.isdir(ex) else []
            for m in sorted(mods):
                if m.startswith("ego_dlc_"): continue
                if mod_filter and m != mod_filter: continue
                mroot = os.path.join(ex, m, "assets")
                if not os.path.isdir(mroot): continue
                for dirpath, _, files in os.walk(mroot):
                    for fn in files:
                        if not fn.endswith(".xml"): continue
                        p = os.path.join(dirpath, fn)
                        try:
                            txt = open(p, encoding="utf-8", errors="ignore").read(4096)
                        except Exception:
                            continue
                        if not _is_diff_txt(txt): continue
                        base_path, _ = _diff_base_for(p)
                        rel = os.path.relpath(p, mroot).replace("\\", "/")
                        out.append({
                            "id": fn[:-4], "path": p, "source": m, "rel": rel,
                            "base": os.path.basename(base_path)[:-4] if base_path else "",
                        })
            self._send(200, json.dumps(out, ensure_ascii=False), "application/json; charset=utf-8")
        elif self.path.startswith("/api/diffpreview"):
            # diff 合并预览：GET ?path=<diff 文件路径> 返回 base 与 patched 文本
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            path = (q.get("path") or [""])[0]
            if not path or not os.path.isfile(path):
                self._send(200, json.dumps({"ok": False, "error": "文件不存在: %s" % path},
                                           ensure_ascii=False), "application/json; charset=utf-8")
            else:
                diff_txt = open(path, encoding="utf-8", errors="ignore").read()
                if not _is_diff_txt(diff_txt):
                    self._send(200, json.dumps({"ok": False, "error": "不是 <diff> 补丁文件"},
                                               ensure_ascii=False), "application/json; charset=utf-8")
                else:
                    base_path, base_txt = _diff_base_for(path)
                    if not base_txt:
                        self._send(200, json.dumps({"ok": False, "error": "找不到 base 组件"},
                                                   ensure_ascii=False), "application/json; charset=utf-8")
                    else:
                        patched = _apply_diff_ops(base_txt, diff_txt)
                        self._send(200, json.dumps({
                            "ok": True, "diff": path, "base": base_path,
                            "base_txt": base_txt, "patched_txt": patched
                        }, ensure_ascii=False), "application/json; charset=utf-8")
        else:
            try:
                html = open(INDEX_HTML, encoding="utf-8").read()
            except Exception:
                html = "<h1>index.html 缺失</h1>"
            self._send(200, html)
    def do_POST(self):
        if self.path not in ("/api/generate", "/api/edit", "/api/config", "/api/pickdir", "/api/dirtree",
                             "/api/equipgenerate", "/api/equipedit",
                             "/api/bulletgenerate", "/api/bulletedit", "/api/refresh",
                             "/api/shipmodelsync", "/api/componentassemble", "/api/dockclone",
                             "/api/shipgroup/save", "/api/explosionbuild", "/api/trailnew",
                             "/api/bulleteffectbuild", "/api/bullettrailbuild", "/api/bulletbeambuild", "/api/bulletvisbuild",
                             "/api/delitem", "/api/diffvalidate",
                             "/api/unpack", "/api/unpackcancel"):
            self._send(404, "not found"); return
        ln = int(self.headers.get("Content-Length", 0))
        try:
            if self.path == "/api/generate":
                d = json.loads(self.rfile.read(ln).decode("utf-8"))
                r = generate(d)
            elif self.path == "/api/edit":
                d = json.loads(self.rfile.read(ln).decode("utf-8"))
                r = edit(d)
            elif self.path == "/api/equipgenerate":
                d = json.loads(self.rfile.read(ln).decode("utf-8"))
                r = equip_generate(d)
            elif self.path == "/api/equipedit":
                d = json.loads(self.rfile.read(ln).decode("utf-8"))
                r = equip_edit(d)
            elif self.path == "/api/bulletgenerate":
                d = json.loads(self.rfile.read(ln).decode("utf-8"))
                r = bullet_generate(d)
            elif self.path == "/api/bulletedit":
                d = json.loads(self.rfile.read(ln).decode("utf-8"))
                r = bullet_edit(d)
            elif self.path == "/api/shipmodelsync":
                # EGO Blender 导出目录 → 目标 mod：py 处理 + macro 连接点归位 + 模型/ani/dae 覆盖 + moding 结构
                d = json.loads(self.rfile.read(ln).decode("utf-8"))
                r = ship_model_sync(d)
            elif self.path == "/api/componentassemble":
                # 组件（炮塔等）装配：ego xml 模板 + 补丁 + data 复制 + macro 改名 + index 注册
                d = json.loads(self.rfile.read(ln).decode("utf-8"))
                r = component_assemble(d)
            elif self.path == "/api/dockclone":
                # 原版 dock 复用：组件/宏改名 + 可选替换 Blender 导出 waypoint + index 注册 + moding 结构
                d = json.loads(self.rfile.read(ln).decode("utf-8"))
                r = dock_clone(d)
            elif self.path == "/api/shipgroup/save":
                d = json.loads(self.rfile.read(ln).decode("utf-8"))
                r = shipgroup_save(d)
            elif self.path == "/api/explosionbuild":
                d = json.loads(self.rfile.read(ln).decode("utf-8"))
                r = explosion_build(d)
            elif self.path == "/api/trailnew":
                d = json.loads(self.rfile.read(ln).decode("utf-8"))
                r = trail_build(d)
            elif self.path == "/api/bulleteffectbuild":
                d = json.loads(self.rfile.read(ln).decode("utf-8"))
                r = bullet_effect_build(d)
            elif self.path == "/api/bullettrailbuild":
                d = json.loads(self.rfile.read(ln).decode("utf-8"))
                r = bullet_trail_build(d)
            elif self.path == "/api/bulletbeambuild":
                d = json.loads(self.rfile.read(ln).decode("utf-8"))
                r = bullet_beam_build(d)
            elif self.path == "/api/bulletvisbuild":
                d = json.loads(self.rfile.read(ln).decode("utf-8"))
                r = bullet_vis_build(d)
            elif self.path == "/api/delitem":
                d = json.loads(self.rfile.read(ln).decode("utf-8"))
                r = delitem(d)
            elif self.path == "/api/unpack":
                # 游戏解包：后台线程顺序跑 XRCatTool
                d = json.loads(self.rfile.read(ln).decode("utf-8"))
                r = unpack_run(d)
            elif self.path == "/api/unpackcancel":
                r = unpack_cancel()
            elif self.path == "/api/diffvalidate":
                # diff 离线校验：POST {"diff": "...", "base": "..."} 直接校验文本
                d = json.loads(self.rfile.read(ln).decode("utf-8"))
                diff_txt = d.get("diff", "")
                base_txt = d.get("base", "")
                if not diff_txt:
                    r = {"ok": False, "error": "缺少 diff 文本"}
                elif not base_txt:
                    r = {"ok": False, "error": "缺少 base 文本"}
                else:
                    r = validate_diff(diff_txt, base_txt)
            elif self.path == "/api/refresh":
                # 清空扫描缓存：运行中往 mod 新增物品后手动刷新列表
                refresh_caches()
                r = {"ok": True}
            elif self.path == "/api/config":
                d = json.loads(self.rfile.read(ln).decode("utf-8"))
                c = load_config(); c.update(d)
                save_config(c)
                r = {"ok": True, "config": c}
            elif self.path == "/api/dirtree":  # 目录树浏览（浏览器内交互，不依赖系统对话框）
                d = json.loads(self.rfile.read(ln).decode("utf-8"))
                r = dirtree(d.get("path") or "", bool(d.get("files")))
            else:  # /api/pickdir：弹出原生文件夹选择对话框
                d = json.loads(self.rfile.read(ln).decode("utf-8"))
                p = pick_dir_dialog()
                if p:
                    c = load_config(); c["target_mod"] = p; save_config(c)
                    r = {"ok": True, "path": p}
                else:
                    r = {"ok": False, "error": "未选择目录"}
        except Exception as e:
            import traceback; traceback.print_exc()
            r = {"ok": False, "error": "服务器错误: %s" % e}
        self._send(200, json.dumps(r, ensure_ascii=False), "application/json; charset=utf-8")
    def log_message(self, *a): pass

# ── 游戏解包（调用官方 XRCatTool，后台线程 + 状态轮询） ──
_UNPACK = {"running": False, "i": 0, "n": 0, "cur": "", "log": [], "done": False,
           "error": "", "cancel": False, "out": "", "mode": "", "proc": None}
# 轻量模式只解数据/文本类文件（xml/索引/库/t 文本/脚本），跳过模型贴图二进制
_LIGHT_INC = [r"\.xml$", r"\.txt$", r"\.csv$", r"\.json$", r"\.lua$", r"\.xsd$", r"\.dtd$", r"\.md$"]

def _find_xtool(game):
    r"""定位 XRCatTool.exe：优先游戏目录同级的 X Tools（steamapps\common\X Tools），再试常见安装位。"""
    cands = []
    gp = os.path.normpath(game) if game else ""
    if gp:
        cands.append(os.path.join(os.path.dirname(gp), "X Tools", "XRCatTool.exe"))
    cands.append(r"D:\Program Files (x86)\Steam\steamapps\common\X Tools\XRCatTool.exe")
    cands.append(r"C:\Program Files (x86)\Steam\steamapps\common\X Tools\XRCatTool.exe")
    for c in cands:
        if os.path.isfile(c):
            return c
    return ""

# mod 目录特征：有 content.xml 或任一游戏数据子目录才算 mod（用于排除 node_modules/dotnet 等杂物）
_MOD_MARKERS = ("content.xml", "assets", "index", "libraries", "md", "aiscripts", "t", "ui")
_MOD_CACHE = {}

def _looks_mod(path):
    try:
        return any(os.path.exists(os.path.join(path, m)) for m in _MOD_MARKERS)
    except Exception:
        return False

def _mod_root(d):
    """mod 目录可能是包了一层的（如 MyMod\\MyMod）；返回真正含游戏数据的根。"""
    if _looks_mod(d):
        return d
    try:
        for f in sorted(os.listdir(d)):
            c = os.path.join(d, f)
            if os.path.isdir(c) and _looks_mod(c):
                return c
    except Exception:
        pass
    return ""

def _ext_id(root):
    """读 content.xml 的 id（X4 扩展标识），用于把 Vortex 暂存区的长目录名还原成游戏里的扩展名。"""
    try:
        import re as _re
        t = open(os.path.join(root, "content.xml"), encoding="utf-8", errors="ignore").read(4000)
        m = _re.search(r'\bid="([^"]+)"', t)
        return m.group(1) if m else ""
    except Exception:
        return ""

def _mod_info(name, root, origin):
    """打包 mod：列 ext_*/subst_* cat；松散 mod：统计文件数/体积（供复制）。"""
    cats = []
    try:
        for f in sorted(os.listdir(root)):
            fl = f.lower()
            if fl.endswith(".cat") and "_sig" not in fl:
                cats.append({"name": f, "path": os.path.join(root, f),
                             "size": os.path.getsize(os.path.join(root, f))})
    except Exception:
        pass
    if cats:
        return {"name": name, "root": root, "origin": origin, "kind": "packed",
                "cats": cats, "has_subst": any(c["name"].startswith("subst_") for c in cats),
                "files": 0, "size": sum(c["size"] for c in cats)}
    n = 0
    total = 0
    try:
        for r, _ds, fs in os.walk(root):
            for f in fs:
                n += 1
                try:
                    total += os.path.getsize(os.path.join(r, f))
                except Exception:
                    pass
    except Exception:
        pass
    return {"name": name, "root": root, "origin": origin, "kind": "loose",
            "cats": [], "has_subst": False, "files": n, "size": total}

def unpack_scan(game, staging="", workshop=""):
    r"""扫描三大来源：基游戏 ##.cat；游戏 extensions（Vortex 部署 + Steam 创意工坊 ws_*，含松散 mod）；
    Vortex 暂存区 stagingPath（含未启用的 mod，按名字去重）。staging 可从 vortex.deployment.json 自动读取。"""
    game = os.path.normpath((game or "").strip().strip('"'))
    if not game or not os.path.isdir(game):
        return {"ok": False, "error": "游戏目录不存在: %s" % game}
    cats = []
    for n in range(1, 100):
        p = os.path.join(game, "%02d.cat" % n)
        if not os.path.isfile(p):
            break
        cats.append({"name": "%02d.cat" % n, "path": p, "size": os.path.getsize(p)})
    if not cats:
        return {"ok": False, "error": "未找到基游戏 cat（01.cat…）：%s" % game}
    ex = os.path.join(game, "extensions")
    exts, seen = [], set()
    if os.path.isdir(ex):
        for name in sorted(os.listdir(ex)):
            dd = os.path.join(ex, name)
            if not os.path.isdir(dd):
                continue
            root = _mod_root(dd) if _looks_mod(dd) else ""
            if not root:
                continue
            origin = "workshop" if name.lower().startswith("ws_") else "game"
            info = _mod_info(name, root, origin)
            info["key"] = "game|" + name
            exts.append(info)
            seen.add(name.lower())
            eid = _ext_id(root)
            if eid:
                seen.add(eid.lower())
    # Vortex 暂存区（自动：extensions\vortex.deployment.json 的 stagingPath）
    st = (staging or "").strip().strip('"')
    if not st:
        dep = os.path.join(ex, "vortex.deployment.json")
        if os.path.isfile(dep):
            try:
                st = (json.load(open(dep, encoding="utf-8", errors="ignore")).get("stagingPath") or "")
            except Exception:
                st = ""
    st = os.path.normpath(st) if st else ""
    if st and os.path.isdir(st):
        for name in sorted(os.listdir(st)):
            dd = os.path.join(st, name)
            if not os.path.isdir(dd) or name.lower() in seen:
                continue          # 已部署到游戏目录的同名 mod 不重复列出
            root = _mod_root(dd)
            if not root:
                continue
            eid = _ext_id(root)
            if eid and eid.lower() in seen:
                continue          # 暂存区目录名长（带版本号），靠 content.xml id 判重
            nm = eid or name
            info = _mod_info(nm, root, "staging")
            info["key"] = "staging|" + nm
            exts.append(info)
            seen.add(name.lower())
            if eid:
                seen.add(eid.lower())
    # 额外 workshop 内容目录（本机 X4 未使用；保留手动指定能力）
    ws = os.path.normpath(workshop.strip().strip('"')) if (workshop or "").strip() else ""
    if ws and os.path.isdir(ws):
        for wid in sorted(os.listdir(ws)):
            dd = os.path.join(ws, wid)
            if not os.path.isdir(dd):
                continue
            name = "ws_" + wid
            if name.lower() in seen:
                continue
            root = _mod_root(dd)
            if not root:
                continue
            info = _mod_info(name, root, "workshop")
            info["key"] = "workshop|" + wid
            exts.append(info)
            seen.add(name.lower())
    for e in exts:
        _MOD_CACHE[e["key"]] = e
    return {"ok": True, "xtool": _find_xtool(game), "staging": st,
            "base": {"name": "基游戏", "cats": cats}, "exts": exts}

def unpack_run(d):
    r"""后台顺序解包：基游戏→输出根；mod 的 ext_*→<out>\extensions\<名>；subst_*→输出根（覆盖基游戏文件，符合游戏语义）。"""
    if _UNPACK["running"]:
        return {"ok": False, "error": "已有解包任务进行中"}
    game = os.path.normpath((d.get("game") or "").strip().strip('"'))
    out = os.path.normpath((d.get("out") or "").strip().strip('"'))
    xtool = (d.get("xtool") or "").strip().strip('"') or _find_xtool(game)
    mode = "full" if d.get("mode") == "full" else "light"
    sources = d.get("sources") or []
    if not os.path.isfile(xtool):
        return {"ok": False, "error": "找不到 XRCatTool.exe: %s" % xtool}
    if not os.path.isdir(game):
        return {"ok": False, "error": "游戏目录不存在: %s" % game}
    if not out:
        return {"ok": False, "error": "请指定输出目录"}
    if os.path.normcase(out) == os.path.normcase(ROOT):
        return {"ok": False, "error": "输出目录不能是当前工程解包根（会覆盖在用数据）"}
    if os.path.normcase(out) == os.path.normcase(game) or os.path.normcase(out).startswith(os.path.normcase(game) + os.sep):
        return {"ok": False, "error": "输出目录不能在游戏安装目录内"}
    scan = unpack_scan(game, (d.get("staging") or "").strip().strip('"'),
                       (d.get("workshop") or "").strip().strip('"'))
    if not scan.get("ok"):
        return scan
    units = []
    want_base = any(s.get("type") == "base" for s in sources)
    want_exts = set(s.get("key") or (s.get("origin", "game") + "|" + (s.get("name") or ""))
                    for s in sources if s.get("type") == "ext")
    if want_base:
        units.append({"label": "基游戏", "cats": [c["path"] for c in scan["base"]["cats"]], "dst": out})
    for e in scan["exts"]:
        if e["key"] not in want_exts:
            continue
        dst = os.path.join(out, "extensions", e["name"])
        if e["kind"] == "loose":
            units.append({"label": "mod: %s（松散文件复制）" % e["name"], "cats": [],
                          "root": e["root"], "dst": dst, "copy": True})
            continue
        extcats = [c["path"] for c in e["cats"] if not c["name"].startswith("subst_")]
        if extcats:
            units.append({"label": "mod: " + e["name"], "cats": extcats,
                          "root": e["root"], "dst": dst})
        for c in e["cats"]:
            if c["name"].startswith("subst_"):
                units.append({"label": "mod: %s（subst 覆盖基游戏）" % e["name"],
                              "cats": [c["path"]], "dst": out})
    if not units:
        return {"ok": False, "error": "未勾选任何来源"}

    def copy_loose(src, dst):
        """松散 mod 复制：跟随符号链接复制真实内容；轻量模式只复制数据/文本文件。"""
        import re as _re
        pats = [_re.compile(p, _re.I) for p in _LIGHT_INC] if mode == "light" else None
        n = 0
        for root, _ds, fs in os.walk(src):
            rel = os.path.relpath(root, src)
            for f in fs:
                if pats and not any(p.search(f) for p in pats):
                    continue
                if _UNPACK["cancel"]:
                    return n
                s = os.path.join(root, f)
                d = os.path.join(dst, f) if rel == "." else os.path.join(dst, rel, f)
                try:
                    os.makedirs(os.path.dirname(d), exist_ok=True)
                    shutil.copy2(s, d)
                    n += 1
                except Exception:
                    pass
        return n

    def work():
        import subprocess
        _UNPACK.update(running=True, i=0, n=len(units), cur="", log=[], done=False,
                       error="", cancel=False, out=out, mode=mode, proc=None)
        try:
            for i, u in enumerate(units):
                if _UNPACK["cancel"]:
                    break
                _UNPACK["i"] = i
                _UNPACK["cur"] = u["label"]
                os.makedirs(u["dst"], exist_ok=True)   # XRCatTool 要求输出目录已存在
                if u.get("copy"):
                    n = copy_loose(u["root"], u["dst"])
                    if _UNPACK["cancel"]:
                        _UNPACK["log"].append("（已取消）")
                        break
                    _UNPACK["log"].append("OK %s（复制 %d 个文件）" % (u["label"], n))
                    _UNPACK["i"] = i + 1
                    continue
                cmd = [xtool, "-in"] + u["cats"] + ["-out", u["dst"]]
                if mode == "light":
                    cmd += ["-include"] + list(_LIGHT_INC)
                _UNPACK["log"].append("$ " + " ".join('"%s"' % x if " " in x else x for x in cmd))
                p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     text=True, encoding="utf-8", errors="ignore")
                _UNPACK["proc"] = p
                otxt = p.communicate()[0] or ""
                _UNPACK["proc"] = None
                for ln in otxt.splitlines():
                    if ln.strip():
                        _UNPACK["log"].append(ln.rstrip())
                if _UNPACK["cancel"]:
                    _UNPACK["log"].append("（已取消）")
                    break
                if p.returncode != 0:
                    _UNPACK["error"] = "%s 解包失败（退出码 %s）" % (u["label"], p.returncode)
                    break
                _UNPACK["log"].append("OK " + u["label"])
                _UNPACK["i"] = i + 1
        except Exception as e:
            _UNPACK["error"] = str(e)
        finally:
            _UNPACK["done"] = True
            _UNPACK["running"] = False
            _UNPACK["proc"] = None

    threading.Thread(target=work, daemon=True).start()
    return {"ok": True, "units": len(units), "mode": mode}

def unpack_cancel():
    _UNPACK["cancel"] = True
    p = _UNPACK.get("proc")
    if p:
        try:
            p.kill()
        except Exception:
            pass
    return {"ok": True}

def main():
    os.makedirs(os.path.dirname(BASE) if False else BASE, exist_ok=True)
    # 先绑定端口：若已被占用（重复双击 server.py），直接打开页面后退出，不做预热
    try:
        srv = socketserver.ThreadingTCPServer(("127.0.0.1", 8765), H)
    except OSError:
        print("8765 端口已被占用，服务可能已在运行；直接打开页面。")
        try:
            import webbrowser
            webbrowser.open("http://127.0.0.1:8765")
        except Exception:
            pass
        return
    print("="*60)
    print("UP7 EVE 舰船制作工具 已启动")
    print("浏览器打开:  http://127.0.0.1:8765")
    print("模板数: %d" % len(TEMPLATES))
    print("MOD 目录: %s" % MOD_DIR)
    print("="*60)
    # 预热 t 文本表与弹丸扫描（首次需全扫，提前构建避免首开 tab 慢）
    try:
        LX.load_loc_all("zh"); LX.load_loc_all("en")
        bullet_scan()
    except Exception:
        pass
    with srv as s:
        s.allow_reuse_address = True
        # 后台预热装备扫描与资产索引（首次冷扫数十秒，放后台避免阻塞监听；缓存热后选项卡秒开）
        def _warm():
            try:
                for _b in _global_assets_roots():
                    _dir_index(_b)      # 组件定位索引：预热后 /api/loadoutmacros、装配预设等毫秒级
                equip_scan()
            except Exception:
                pass
        threading.Thread(target=_warm, daemon=True).start()
        # 直接运行时自动打开浏览器：后台轮询，等端口真正开始监听再开，避免"拒绝连接"
        def _open_browser():
            import socket as _sk, webbrowser
            for _ in range(50):
                try:
                    with _sk.create_connection(("127.0.0.1", 8765), timeout=0.3):
                        break
                except Exception:
                    time.sleep(0.2)
            try:
                webbrowser.open("http://127.0.0.1:8765")
            except Exception:
                pass
        threading.Thread(target=_open_browser, daemon=True).start()
        s.serve_forever()

if __name__ == "__main__":
    main()
