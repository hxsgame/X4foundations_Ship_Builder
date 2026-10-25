import sys, re, json
sys.path.insert(0, r"C:\Users\15536\Doubao\chats\2026-10-03\new-chat")
import x4_extract as X
txt = open(r"D:\Games\X4 exout\libraries\factions.xml", encoding="utf-8").read()
keep = {"argon","antigone","paranid","holyorder","teladi","ministry","split","freesplit",
        "fallensplit","terran","boron","hatikvah","scaleplate","buccaneers","alliance","trinity","xenon"}
out = {}
for m in re.finditer(r'<faction\b[^>]*?id="([^"]+)"[^>]*?(name|shortname)="([^"]+)"', txt):
    pass
# 改为整块解析
for m in re.finditer(r'<faction\b(?=[^>]*\bid="([^"]+)")([^>]*)>', txt):
    fid = m.group(1)
    if fid not in keep: continue
    attrs = m.group(2)
    def get(k):
        mm = re.search(k + r'="([^"]*)"', attrs)
        return mm.group(1) if mm else None
    out[fid] = {
        "name_zh": X.lname(get("name") or "", fid, "zh"),
        "short_zh": X.lname(get("shortname") or "", "", "zh"),
        "prefix_zh": X.lname(get("prefixname") or "", "", "zh"),
        "home_zh": X.lname(get("homespacename") or "", "", "zh"),
        "short_en": X.lname(get("shortname") or "", "", "en"),
    }
print(json.dumps(out, ensure_ascii=False, indent=1))
