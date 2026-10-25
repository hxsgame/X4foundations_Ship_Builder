# -*- coding: utf-8 -*-
"""
X4 解包数据提取 / 查找 / 清洗模块（独立可复用）
================================================================
从 X4 解包目录读取游戏数据：
  - t 文本表（主 + 各扩展，后加载覆盖先，diff 覆盖语义）
  - {page,id} 引用解析与文本清洗（颜色/TTS 控制码、残余引用、
    括号注释段、行首种族词）
  - 装备宏（engine/shield/turret/weapon/thruster）显示名解析

用法：
    from x4_lookup import X4Lookup
    lx = X4Lookup(r"C:/X4_unpack")
    lx.lname("{20203,201}", "argon", "zh")   # -> 'Argon联邦'
    lx.macro_display(path, fallback, "zh")   # -> 装备显示名（中/英）
    lx.clean_text(t, "zh")                   # -> 清洗颜色/TTS 码后的文本
"""
import os
import re
import json
import xml.etree.ElementTree as ET

_CACHE_VER = 2


def _cache_dir():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")


def _sig_files(files):
    """t 文本表输入签名：文件数 + 最大 mtime_ns + 总字节。"""
    n = mt = sz = 0
    for p in files:
        try:
            st = os.stat(p)
        except OSError:
            continue
        n += 1
        mt = max(mt, st.st_mtime_ns)
        sz += st.st_size
    return [n, mt, sz]


class X4Lookup:
    def __init__(self, root):
        self.root = os.path.normpath(root)
        self._loc = {}
        self._ext = None

    # ---- 扩展加载顺序（官方 DLC 前，用户 mod 后，后覆盖先）----
    def ext_order(self):
        """模拟游戏扩展加载顺序：官方 DLC（ego_dlc_*）在前，用户 mod 字母序在后。"""
        if self._ext is not None:
            return self._ext
        ex = os.path.join(self.root, "extensions")
        mods = [d for d in os.listdir(ex) if os.path.isdir(os.path.join(ex, d))] if os.path.isdir(ex) else []
        official = sorted(d for d in mods if d.startswith("ego_dlc_"))
        others = sorted(d for d in mods if not d.startswith("ego_dlc_"))
        self._ext = official + others
        return self._ext

    # ---- t 文本表 {(page,id): text}（主 + 扩展，后加载覆盖先）----
    def load_loc_all(self, lang):
        """扫主 t + 各扩展 t，返回 {(page,id): 原文}；后加载者覆盖先加载者。
        优先用 ElementTree(C 解析)加速，避免正则解析大 t 文件造成首次加载慢。"""
        if lang in self._loc:
            return self._loc[lang]
        tf = "0001-l086.xml" if lang == "zh" else ("0001.xml" if lang == "en" else "0001-l086.xml")
        roots = [os.path.join(self.root, "t")] + \
                [os.path.join(self.root, "extensions", d, "t") for d in self.ext_order()]
        files = []
        for rt in roots:
            p = os.path.join(rt, tf)
            if lang == "en" and not os.path.isfile(p):
                # 解包常缺英文基础 t(0001.xml)；英文语言实际在 0001-l044.xml
                p = os.path.join(rt, "0001-l044.xml")
            if os.path.isfile(p):
                files.append(p)
        # 磁盘缓存：输入签名（各来源 t 文件数/最大 mtime/总字节）一致时直接读盘，免重解析 6MB XML
        sig = _sig_files(files)
        cname = "loc_%s.json" % lang
        try:
            with open(os.path.join(_cache_dir(), cname), encoding="utf-8") as f:
                dat = json.load(f)
            if dat.get("ver") == _CACHE_VER and dat.get("sig") == sig:
                table = {(int(pg), int(tid)): txt for pg, tid, txt in dat["data"]}
                self._loc[lang] = table
                return table
        except Exception:
            pass
        table = {}
        for p in files:
            try:
                for event, elem in ET.iterparse(p, events=("end",)):
                    if elem.tag == "page":
                        pg = int(elem.get("id"))
                        for t in elem.iter("t"):
                            table[(pg, int(t.get("id")))] = (t.text or "")
                        elem.clear()
            except Exception:
                # 非严格 XML 文件回退到原正则解析，保证兼容
                try:
                    txt = open(p, encoding="utf-8").read()
                    for mp in re.finditer(r'<page id="(\d+)"[^>]*>(.*?)</page>', txt, re.S):
                        page = int(mp.group(1))
                        for mt in re.finditer(r'<t id="(\d+)">([^<]*)</t>', mp.group(2)):
                            table[(page, int(mt.group(1)))] = mt.group(2)
                except Exception:
                    pass
        try:
            os.makedirs(_cache_dir(), exist_ok=True)
            fp = os.path.join(_cache_dir(), cname)
            with open(fp + ".tmp", "w", encoding="utf-8") as f:
                json.dump({"ver": _CACHE_VER, "sig": sig,
                           "data": [[pg, tid, txt] for (pg, tid), txt in table.items()]},
                          f, ensure_ascii=False)
            os.replace(fp + ".tmp", fp)
        except Exception:
            pass
        self._loc[lang] = table
        return table

    # ---- {page,id} 引用 → 原文 ----
    def ref_text(self, ref, lang="zh"):
        if not ref:
            return ""
        loc = self.load_loc_all(lang)
        m = re.match(r"\{(\d+)\s*,\s*(\d+)\}", ref)
        return loc.get((int(m.group(1)), int(m.group(2))), "") if m else ""

    # ---- 文本清洗（颜色/TTS 码、引用、括号注释、种族词）----
    def clean_text(self, t, lang="zh"):
        """清洗 X4 t 文本：
        - 移除颜色/TTS 控制码（\\033#RRGGBB#LM\\X、\\033X 等）
        - 移除残余 {page,id} 引用
        - 移除括号注释段（中文语境含英文的括号段、行首括号段）
        - 移除行首种族词（中文语境）与孤立反斜杠
        转义括号 \\( \\) 是字面括号，先占位保护再还原。"""
        if not t:
            return ""
        t = t.replace("\\(", "\x01").replace("\\)", "\x02")
        # 颜色/TTS 控制码：形式多样——
        #   开头为 ESC 字节 \x1b 或字面 \033；中间 #RRGGBB(#LM)；结束为 \\033X 或 \\X（整体备选）
        code = r"(?:\\033|\x1b)(?:#[0-9a-fA-F]{6,8})?(?:#[A-Za-z]+)?(?:\\033X|\\X)"
        t = re.sub(code, "", t)
        t = re.sub(r"(?:\\033|\x1b)[A-Za-z]*\\X?", "", t)
        t = re.sub(r"(?:\\033|\x1b)", "", t)
        t = re.sub(r"\{(\d+)\s*,\s*(\d+)\}", "", t)   # 残余引用（与 lname 展开正则一致，兼容带空格）
        if lang == "zh":
            # 中文语境：去掉含英文的括号段、行首括号段、行首种族词
            t = re.sub(r"\([^（）()]*[A-Za-z][^（）()]*\)", "", t)
            t = re.sub(r"^\s*\([^（）()]*\)\s*", "", t).strip()
            t = re.sub(r"^(Argon|ARG|Paranid|Split|Teladi|Terran|Boron|Xenon)\s+", "", t).strip()
        else:
            t = re.sub(r"^\([^()]*\)\s*", "", t).strip()
        t = re.sub(r"\\$", "", t)
        t = re.sub(r"\s+", " ", t).strip()
        t = t.replace("\x01", "(").replace("\x02", ")")
        return t

    # ---- 名称解析（递归展开引用 + 清洗）----
    def lname(self, ref, fallback="", lang="zh"):
        """解析名称属性（可含多个/嵌套引用，如 "(ARG Behemoth Main Battery){20202,103} {20105,3001}"）：
        递归展开 {page,id}（限 8 层防循环）→ 清洗 → 中文优先、其次英文，
        都空则取开头括号内可读文本。"""
        if not ref:
            return fallback
        loc = self.load_loc_all(lang)
        txt = ref
        for _ in range(8):
            m = re.search(r"\{(\d+)\s*,\s*(\d+)\}", txt)
            if not m:
                break
            v = loc.get((int(m.group(1)), int(m.group(2))))
            if v is None:
                txt = txt[:m.start()] + txt[m.end():]   # 未解析引用直接删
            else:
                txt = txt[:m.start()] + v + txt[m.end():]
        out = self.clean_text(txt, lang)
        if out:
            return out
        if lang != "en":
            en = self.lname(ref, "", "en")
            if en:
                return en
        head = re.split(r"\{", ref)[0].strip().strip("()").strip()
        return head or fallback

    # ---- 装备宏显示名（中文优先、其次英文、再则 name 开头可读文本）----
    def macro_display(self, path, fallback="", lang="zh"):
        """读装备宏的 name 属性（如 "(ARG L Engine Mk1){20202,103} {20111,5031}"），
        解析显示名：中文优先、其次英文、都无则取 name 开头括号内文本。"""
        try:
            txt = open(path, encoding="utf-8").read()
        except Exception:
            return fallback
        # 显示名在 <properties><identification name="{...}">（或宏根引用 name）。
        # 强制 name 含 {，避开根 <macro name="文件id"> 这类无引用的 name。
        m = re.search(r'name="([^"]*\{[^"]*)"', txt)
        if not m:
            return fallback
        name_attr = m.group(1)
        zh = self.lname(name_attr, "", "zh")
        if zh:
            return zh
        en = self.lname(name_attr, "", "en")
        if en:
            return en
        head = re.split(r"\{", name_attr)[0].strip().strip("()").strip()
        return head or fallback
