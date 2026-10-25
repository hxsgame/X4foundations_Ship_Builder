# -*- coding: utf-8 -*-
import sys, os, shutil
sys.path.insert(0, r"C:\Users\15536\Doubao\chats\2026-10-03\new-chat-1\EVE_Ship_Builder")
import server
tmp = r"C:\Users\15536\Doubao\chats\2026-10-03\new-chat-1\EVE_Ship_Builder\_jobs_test_tmp"
shutil.rmtree(tmp, ignore_errors=True)
cfg = {"enabled": True, "factions": ["argon", "terran"], "tasks": ["patrol", "defend"]}
r = server.write_jobs(tmp, "ship_spl_xl_golem_macro", "xl", cfg, 905)
p = os.path.join(tmp, "libraries", "jobs.xml")
print("written:", r)
print(open(p, encoding="utf-8").read())
shutil.rmtree(tmp, ignore_errors=True)
