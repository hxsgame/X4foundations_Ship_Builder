import re, collections
p = r"D:\Games\X4 exout\libraries\wares.xml"
txt = open(p, encoding="utf-8").read()
wares = re.findall(r'<ware id="ship_[a-z0-9]+_(l|xl)_[^"]*"[^>]*>(.*?)</ware>', txt, re.S)
price_data = collections.defaultdict(list); time_data = collections.defaultdict(list)
mat = collections.Counter()
for size, body in wares:
    pr = re.search(r'<price min="(\d+)" average="(\d+)" max="(\d+)"', body)
    if pr: price_data[size].append(tuple(map(int, pr.groups())))
    pt = re.search(r'<production[^>]*time="(\d+)"', body)
    if pt: time_data[size].append(int(pt.group(1)))
    prim = re.search(r'<primary>(.*?)</primary>', body, re.S)
    if prim:
        for m in re.findall(r'<ware ware="(\w+)" amount="(\d+)"\s*/>', prim.group(1)):
            mat[(size, m[0])] += int(m[1])
for size in ("l","xl"):
    pd = [x for x in price_data[size] if x[0]>0]
    print("==", size, "n=", len(pd))
    if pd:
        mn=[x[0] for x in pd]; av=[x[1] for x in pd]; mx=[x[2] for x in pd]
        print("  price min %d~%d  avg %d~%d  max %d~%d"%(min(mn),max(mn),min(av),max(av),min(mx),max(mx)))
        print("  price examples:", sorted(pd,key=lambda x:x[0])[:3], "...", sorted(pd,key=lambda x:x[0])[-3:])
    if time_data[size]:
        print("  time min %d max %d  examples:%s"%(min(time_data[size]),max(time_data[size]),sorted(set(time_data[size]))[:12]))
    print("  materials:", mat.most_common(12))
