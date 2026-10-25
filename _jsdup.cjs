const {JSDOM, VirtualConsole} = require('jsdom');
const fs = require('fs');
const R = 'C:/Users/15536/Doubao/chats/2026-10-03/new-chat-1/EVE_Ship_Builder/_dup4.txt';
const F = 'C:/Users/15536/Doubao/chats/2026-10-03/new-chat-1/EVE_Ship_Builder/index.html';
fs.writeFileSync(R, 'start\n');
try {
  const html = fs.readFileSync(F, 'utf8');
  const vc = new VirtualConsole();
  vc.on('error', (...a)=>fs.appendFileSync(R, '[VC-ERR] '+a.join(' ')+'\n'));
  const dom = new JSDOM(html, {runScripts:'dangerously', url:'http://127.0.0.1:8765/', pretendToBeVisual:true, virtualConsole:vc});
  const w = dom.window;
  w.fetch = (u,o)=>fetch(new URL(u, 'http://127.0.0.1:8765/'), o);
  setTimeout(async ()=>{
    try {
      for (const cls of ['shield','engine']) {
        const t = await (await fetch('http://127.0.0.1:8765/api/equiptemplates?cls='+cls)).json();
        w.eval('EQ["'+cls+'"].tpl = '+JSON.stringify(t)+';');
        await w.eval('renderEquip("'+cls+'")');
        await w.eval('refreshEqSels("'+cls+'")');
        const pk = w.document.getElementById('eqpick-'+cls);
        const names = (pk._opts||[]).slice(0,30).map(o=>o.name);
        const hasDup = names.some(n=>n.indexOf('[重复]')>=0);
        fs.appendFileSync(R, cls+' eqpick项='+(pk._opts||[]).length+' 前30含[重复]='+hasDup+' 样例='+(names.slice(0,2).join(' || '))+'\n');
      }
      // 导弹：loadBulletTpl（kind=missile）
      const m = await (await fetch('http://127.0.0.1:8765/api/equiptemplates?cls=missile&kind=missile')).json();
      w.eval('EQ["missile"].tpl = '+JSON.stringify(m)+';');
      await w.eval('renderEquip("missile")');
      await w.eval('loadBulletTpl("missile","missile")');
      const pm = w.document.getElementById('eqpick-missile');
      const nm = (pm._opts||[]).slice(0,30).map(o=>o.name);
      fs.appendFileSync(R, 'missile eqpick项='+(pm._opts||[]).length+' 前30含[重复]='+nm.some(n=>n.indexOf('[重复]')>=0)+' 样例='+(nm.slice(0,2).join(' || '))+'\n');
    } catch(e){ fs.appendFileSync(R, 'STEP_ERR: '+e.message+'\n'+(e.stack||'').split('\n').slice(0,6).join('\n')+'\n'); }
    fs.appendFileSync(R, 'done\n');
    process.exit(0);
  }, 1800);
} catch(e){ fs.appendFileSync(R, 'CONSTRUCT_ERR: '+e.message+'\n'); process.exit(1); }
