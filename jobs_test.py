# -*- coding: utf-8 -*-
import sys, os, shutil
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import server
tmp = os.path.join(BASE, "_jobs_test_tmp")
shutil.rmtree(tmp, ignore_errors=True)
cfg = {"enabled": True, "factions": ["argon", "terran"], "tasks": ["patrol", "defend"]}
r = server.write_jobs(tmp, "ship_spl_xl_golem_macro", "xl", cfg, 905)
p = os.path.join(tmp, "libraries", "jobs.xml")
print("written:", r)
print(open(p, encoding="utf-8").read())
shutil.rmtree(tmp, ignore_errors=True)
