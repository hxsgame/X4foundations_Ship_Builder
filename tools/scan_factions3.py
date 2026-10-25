import sys, re, json, os
sys.path.insert(0, r"C:\Users\15536\Doubao\chats\2026-10-03\new-chat")
import x4_extract as X

BASE = r"D:\Games\X4 exout"
factions_files = [os.path.join(BASE, "libraries", "factions.xml")]
for d in X.extension_dirs():
    p = os.path.join(BASE, "extensions", d, "libraries", "factions.xml")
    if os.path.exists(p):
        factions_files.append(p)

# 后加载者覆盖先加载者（diff 语义）
faction_ref = {}
for fp in factions_files:
    try:
        txt = open(fp, encoding="utf-8").read()
    except Exception:
        continue
    # 支持 <diff><add sel="//factions"> 内或直接 <faction>
    for m in re.finditer(r'<faction\b(?=[^>]*\bid="([^"]+)")([^>]*)>', txt):
        fid, attrs = m.group(1), m.group(2)
        mm = re.search(r'name="([^"]+)"', attrs)
        if mm:
            faction_ref[fid] = mm.group(1)

out = {}
for fid, ref in faction_ref.items():
    out[fid] = {
        "zh": X.lname(ref, fid, "zh"),
        "en": X.lname(ref, fid, "en"),
    }
print(json.dumps(out, ensure_ascii=False, indent=1))
