import os, re, json
BASE = r"D:\Games\X4 exout\assets\props"
out = {"engine": [], "shield": [], "weapon": [], "turret": [], "thruster": []}

def size_ok(name, kinds):
    # kinds: 接受尺寸（如 {"l","xl"}）；宏名里含 _s_/_m_/_l_/_xl_/_xs_
    m = re.search(r"_(xs|s|m|l|xl)_", name)
    return m and m.group(1) in kinds

def clean(name):
    return name[:-len("_macro.xml")] if name.endswith("_macro.xml") else name[:-len(".xml")]

# engine / shield
for d, key in [(os.path.join(BASE,"Engines","macros"),"engine"),
               (os.path.join(BASE,"SurfaceElements","macros"),"shield")]:
    if os.path.isdir(d):
        for f in sorted(os.listdir(d)):
            if not f.endswith("_macro.xml"): continue
            if "_video" in f: continue
            if not f.startswith(key + "_"): continue
            if size_ok(f, {"l","xl"}) and not re.search(r"(tutorial|story|scenario)", f):
                out[key].append(clean(f))

# weapon / turret / thruster under WeaponSystems + others
for root, _, files in os.walk(os.path.join(BASE,"WeaponSystems")):
    for f in sorted(files):
        if not f.endswith("_macro.xml"): continue
        if "_video" in f: continue
        if re.search(r"(tutorial|story|scenario)", f): continue
        if f.startswith("weapon_") and size_ok(f, {"l","xl"}):
            out["weapon"].append(clean(f))
        elif f.startswith("turret_") and size_ok(f, {"l"}):
            out["turret"].append(clean(f))

# thruster: gen 通用系列（任何尺寸，非 video）
for root, _, files in os.walk(BASE):
    for f in sorted(files):
        if f.startswith("thruster_gen_") and f.endswith("_macro.xml") and "_video" not in f:
            out["thruster"].append(clean(f))

print("counts:", {k: len(v) for k, v in out.items()})
for k in out:
    print(f"== {k} ({len(out[k])})")
    print(", ".join(out[k][:60]))
