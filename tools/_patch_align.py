# -*- coding: utf-8 -*-
P = r"C:\Users\15536\Doubao\chats\2026-10-03\new-chat-1\EVE_Ship_Builder\index.html"
raw = open(P, "rb").read()
nl = "\r\n" if b"\r\n" in raw else "\n"
txt = raw.decode("utf-8").replace("\r\n", "\n")
def rep(old, new):
    global txt
    c = txt.count(old)
    assert c == 1, "count=%d for %r" % (c, old[:70])
    txt = txt.replace(old, new)

# A) 参数化 openMods / toggleMods / pickMod / pickSystemDir
rep(
"""function openMods(){
  let MODS = [];
  fetch("/api/moddirs").then(r=>r.json()).then(MODS=>{
    const box = document.getElementById("modlist");
    box.innerHTML = MODS.length
      ? MODS.map(m=>`<div class="moditem" onclick="pickMod('${m.path.replace(/'/g,"&apos;")}')">${m.name}<span>${m.path}</span></div>`).join("")
      : "<div class='moditem'>未找到 mod（检查 D:\\Games\\X4 exout\\extensions）</div>";
  }).catch(()=>{});
}
function toggleMods(){
  const box = document.getElementById("modlist");
  if (box.style.display === "none"){ openMods(); box.style.display = "block"; }
  else box.style.display = "none";
}
function pickMod(p){
  document.getElementById("target_mod").value = p;
  document.getElementById("modlist").style.display = "none";
  savePath(p);
}
async function pickSystemDir(){
  const st = document.getElementById("status");
  st.innerHTML = "正在打开系统文件夹选择对话框…";
  let r;
  try { r = await (await fetch("/api/pickdir", {method:"POST",
    headers:{"Content-Type":"application/json"}, body:"{}"})).json(); }
  catch(e){ st.innerHTML = '<span class="err">请求失败: ' + e + '</span>'; return; }
  if (r.ok){ document.getElementById("target_mod").value = r.path; st.innerHTML = ""; }
  else st.innerHTML = '<span class="err">' + (r.error||"未选择") + '</span>';
}""",
"""function openMods(listId="modlist", inputId="target_mod"){
  fetch("/api/moddirs").then(r=>r.json()).then(MODS=>{
    const box = document.getElementById(listId);
    box.innerHTML = MODS.length
      ? MODS.map(m=>`<div class="moditem" onclick="pickMod('${m.path.replace(/'/g,"&apos;")}','${inputId}','${listId}')">${m.name}<span>${m.path}</span></div>`).join("")
      : "<div class='moditem'>未找到 mod（检查 D:\\Games\\X4 exout\\extensions）</div>";
  }).catch(()=>{});
}
function toggleMods(listId="modlist", inputId="target_mod"){
  const box = document.getElementById(listId);
  if (box.style.display === "none"){ openMods(listId, inputId); box.style.display = "block"; }
  else box.style.display = "none";
}
function pickMod(p, inputId="target_mod", listId="modlist"){
  document.getElementById(inputId).value = p;
  document.getElementById(listId).style.display = "none";
  savePath(p);
}
async function pickSystemDir(inputId="target_mod", statusId="status"){
  const st = document.getElementById(statusId);
  st.innerHTML = "正在打开系统文件夹选择对话框…";
  let r;
  try { r = await (await fetch("/api/pickdir", {method:"POST",
    headers:{"Content-Type":"application/json"}, body:"{}"})).json(); }
  catch(e){ st.innerHTML = '<span class="err">请求失败: ' + e + '</span>'; return; }
  if (r.ok){ document.getElementById(inputId).value = r.path; st.innerHTML = ""; }
  else st.innerHTML = '<span class="err">' + (r.error||"未选择") + '</span>';
}"""
)

# B) renderEquip 目标 mod：加浏览/mod列表按钮 + eqmodlist 容器
rep(
"""      <div><label>目标 mod 目录</label><input id="eqmod-${cls}" value="${EQ.tmod||""}"></div>""",
"""      <div class="full"><label>目标 mod 目录（修改时自动跟随所选装备所属 mod）</label>
        <div style="display:flex;gap:8px">
          <input id="eqmod-${cls}" value="${EQ.tmod||""}" style="flex:1">
          <button class="btn-browse" onclick="pickSystemDir('eqmod-${cls}','eqstatus-${cls}')">浏览…</button>
          <button class="btn-browse" onclick="toggleMods('eqmodlist-${cls}','eqmod-${cls}')">mod列表</button>
        </div>
        <div id="eqmodlist-${cls}" style="display:none;margin-top:8px;border:1px solid #30363d;border-radius:6px;background:#0d1117;max-height:220px;overflow:auto"></div></div>"""
)

# C) eqOnPick 跟随目标 mod（读取成功后）
rep(
"""  const mdl = document.getElementById("blk-model-"+cls);
  if (mdl && r.model) sselSet(mdl, r.model);
  const ct = document.getElementById("eqctags-"+cls);
  if (ct) ct.value = r.conn_tags||"";
  eqOwnerSet(cls, r.owner||"");
  eqStatus(cls, `已读取 ${r.id}（源 ${r.source}）`);
}""",
"""  const mdl = document.getElementById("blk-model-"+cls);
  if (mdl && r.model) sselSet(mdl, r.model);
  const ct = document.getElementById("eqctags-"+cls);
  if (ct) ct.value = r.conn_tags||"";
  eqOwnerSet(cls, r.owner||"");
  const tpl = (EQ[cls].tpl||[]).find(x=>x.id===id);
  const tm = document.getElementById("eqmod-"+cls);
  if (tm && tpl && tpl.source_path) tm.value = tpl.source_path;
  eqStatus(cls, `已读取 ${r.id}（源 ${r.source}）`);
}"""
)

# D) eqSave 结果结构化（res-title/res-list）
rep(
"""    document.getElementById("eqresult-"+cls).innerHTML = r.ok
      ? `<pre style="color:#7ee787;white-space:pre-wrap">✓ ${mode==="edit"?"已修改":"已生成"} ${r.id||""}
创建: ${(r.created||[]).join("\\n")}${(r.modified||[]).length?("\\n修改: "+(r.modified||[]).join("\\n")):""}
副本: ${r.moding||""}</pre>`
      : `<pre style="color:#f85149">${r.error||"失败"}</pre>`;""",
"""    document.getElementById("eqresult-"+cls).innerHTML = r.ok
      ? `<div style="color:#7ee787;margin-bottom:6px">✓ ${mode==="edit"?"已修改":"已生成"} ${r.id||""}</div>`
        + `<div class="res-title">文件 (${(r.created||[]).length+(r.modified||[]).length})</div><div class="res-list">`
        + (r.created||[]).map(x=>`<div>+ ${x}</div>`).join("")
        + ((r.modified||[]).map(x=>`<div>~ ${x}</div>`).join(""))
        + `</div>${r.moding?`<div class="res-title">moding 副本</div><div class="res-list"><div>${r.moding}</div></div>`:""}`
      : `<span class="err">${r.error||"失败"}</span>`;"""
)

# E) 保存后刷新列表（数据互通）
rep(
"""async function loadCostRefs(){""",
"""async function refreshTP(){
  // 物品池变化后刷新舰船模板/修改列表（保留当前选择）
  try { TP = await (await fetch("/api/templates")).json(); } catch(e){ return; }
  const srcCN = x => x.source==="vanilla" ? "原版" : x.source;
  const opt = TP.map(x=>({id:x.id, name:(x.name_zh||x.name_en||x.name) + " [" + srcCN(x) + "]"}));
  const t = document.getElementById("template"), p = document.getElementById("pick");
  if (t){ const cur = sselGet(t); ssel(t, opt, ()=>onTpl()); if (cur) sselSet(t, cur); }
  if (p){ const cur = sselGet(p); ssel(p, opt, ()=>onPick()); if (cur) sselSet(p, cur); }
}
async function refreshEQ(cls){
  // 物品池变化后刷新装备模板/修改列表（保留当前选择）
  try { EQ[cls].tpl = await (await fetch("/api/equiptemplates?cls="+cls)).json(); } catch(e){ return; }
  const opt = EQ[cls].tpl.map(x=>({id:x.id, name:(x.name||x.id)+" ["+(x.sizes&&x.sizes[0]||"")+" · "+(x.mk||"")+"]"}));
  const t = document.getElementById("eqtpl-"+cls), p = document.getElementById("eqpick-"+cls);
  if (t){ const cur = sselGet(t); ssel(t, opt, ()=>eqOnTpl(cls)); if (cur) sselSet(t, cur); }
  if (p){ const cur = sselGet(p); ssel(p, opt, ()=>eqOnPick(cls)); if (cur) sselSet(p, cur); }
}
async function loadCostRefs(){"""
)

# 舰船 doSave 成功后刷新 TP
rep(
"""      st.innerHTML = '<span style="color:#3fb950">✔ 生成成功。新舰船 ' + body.new_id + '</span>';""",
"""      st.innerHTML = '<span style="color:#3fb950">✔ 生成成功。新舰船 ' + body.new_id + '</span>';
      refreshTP();""")
rep(
"""      st.innerHTML = '<span style="color:#3fb950">✔ 修改已保存：' + r.id + '</span>';""",
"""      st.innerHTML = '<span style="color:#3fb950">✔ 修改已保存：' + r.id + '</span>';
      refreshTP();""")

# 装备 eqSave 成功后刷新 EQ 列表
rep(
"""    document.getElementById("eqresult-"+cls).innerHTML = r.ok
      ? `<div style="color:#7ee787;margin-bottom:6px">✓ ${mode==="edit"?"已修改":"已生成"} ${r.id||""}</div>`""",
"""    if (r.ok) refreshEQ(cls);
    document.getElementById("eqresult-"+cls).innerHTML = r.ok
      ? `<div style="color:#7ee787;margin-bottom:6px">✓ ${mode==="edit"?"已修改":"已生成"} ${r.id||""}</div>`"""
)

body = txt if nl == "\n" else txt.replace("\n", "\r\n")
open(P, "w", encoding="utf-8", newline="").write(body)
print("OK index.html 拉齐+互通刷新完成")
