import sys, re, json
sys.path.insert(0, r"C:\Users\15536\Doubao\chats\2026-10-03\new-chat")
import x4_extract as X

factions_path = r"D:\Games\X4 exout\libraries\factions.xml"
txt = open(factions_path, encoding="utf-8").read()
out = {}
for m in re.finditer(r'<faction\b[^>]*id="([^"]+)"[^>]*name="([^"]+)"', txt):
    fid, name_ref = m.group(1), m.group(2)
    zh = X.lname(name_ref, fallback=fid, lang="zh")
    en = X.lname(name_ref, fallback=fid, lang="en")
    out[fid] = {"id": fid, "zh": zh, "en": en}
print(json.dumps(out, ensure_ascii=False, indent=1))
