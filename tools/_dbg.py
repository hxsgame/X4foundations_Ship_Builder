# -*- coding: utf-8 -*-
import server, traceback
try:
    r = server.equip_chain("turret", "turret_par_xl_beam_long")
    b = r.get("bullet") or {}
    lines = ["OK bullet: %s" % b.get("id")]
    for k in ("macro","component","geometry"):
        if b.get(k): lines.append("   %s: %s" % (k, b[k]))
    open(r"C:\Users\15536\Doubao\chats\2026-10-03\new-chat-1\EVE_Ship_Builder\_e.txt","w",encoding="utf-8").write("\n".join(lines))
except Exception:
    open(r"C:\Users\15536\Doubao\chats\2026-10-03\new-chat-1\EVE_Ship_Builder\_e.txt","w",encoding="utf-8").write(traceback.format_exc())
