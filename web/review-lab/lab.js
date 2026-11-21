/* Experimental policy changes only read saved evidence; no engine request is made here. */
const $ = id => document.getElementById(id);
const state = { game:null, result:null, translations:{}, motifs:[], comparisons:{}, chosen:new Set(), manual:false, line:null, frame:0, token:0 };
const board = new Board($('board'), {pieceBase:'/static/vendor/pieces/'});
const esc = x => String(x ?? '').replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const tr = name => state.translations[name] || name;
const deferredConcept = name => [8,14,17,18,23,24,25,28,30].includes(state.motifs.findIndex(m=>m.name===name)+1);
const cfg = () => ({rounds:+$('rounds').value, followup:+$('followup').value, start:+$('start-round').value, scheme:$('scheme').value});
async function api(path, options) { const r=await fetch(path,options); if(!r.ok) throw Error((await r.json()).detail || `HTTP ${r.status}`); return r.json(); }
function message(s){$('message').textContent=s;}
function current(){return state.game.moves[+$('ply').value-1];}
function groupFor(data, side){return data?.roots[side==='positive'?data.recommended:data.played];}
function selectedLines(data, side, scheme=cfg().scheme){const g=groupFor(data,side); return (g?.schemes[scheme] || []).map(id=>g.lines[id]);}
function mainLine(data, side){return selectedLines(data,side,'main')[0];}
function confirmed(line,name,perspective='own'){
  if(!line)return {hit:false,pending:false,rounds:[]};
  const c=cfg(), values=line.rounds.slice(0,c.rounds).map(r=>r[perspective].includes(name)), rounds=[];
  let pending=false;
  for(let i=0;i<Math.min(values.length,c.start);i++){
    const w=values.slice(i,i+c.followup+1);
    if(w.length===c.followup+1 && w.every(Boolean))rounds.push(i+1);
    else if(w.length<c.followup+1 && w.length && w.every(Boolean))pending=true;
  }
  return {hit:rounds.length>0,pending,rounds};
}
function conceptRows(data,perspective='own'){
  const pos=selectedLines(data,'positive'),neg=selectedLines(data,'negative');
  return state.motifs.map(m=>{
    const p=pos.map(l=>confirmed(l,m.name,perspective)),n=neg.map(l=>confirmed(l,m.name,perspective));
    const a=confirmed(mainLine(data,'positive'),m.name,perspective), b=confirmed(mainLine(data,'negative'),m.name,perspective);
    return {...m,positive:p.filter(x=>x.hit).length,negative:n.filter(x=>x.hit).length,pendingP:p.filter(x=>x.pending&&!x.hit).length,pendingN:n.filter(x=>x.pending&&!x.hit).length,
      totalP:pos.length,totalN:neg.length,stable:a.hit&&!b.hit&&!b.pending, adverse:b.hit&&!a.hit&&!a.pending,mainP:a,mainN:b,
      contrast:(pos.length?p.filter(x=>x.hit).length/pos.length:0)-(neg.length?n.filter(x=>x.hit).length/neg.length:0)};
  }).sort((a,b)=>Number(b.stable)-Number(a.stable)||b.contrast-a.contrast||b.delta-a.delta);
}
function qualifies(r,policy){
  if(policy==='stable')return r.stable;
  if(policy==='threshold'||policy==='legacy')return r.totalP>=2&&r.totalN>=2&&r.positive>=2&&r.positive/r.totalP>=.5&&(r.negative+r.pendingN)/r.totalN<=.25;
  return r.positive>0||r.stable;
}
function tactical(data){
  const c=cfg(), a=mainLine(data,'positive'),b=mainLine(data,'negative');
  const scan=line=>{
    if(!line)return {mate:false,gain:0,loss:0};
    const limit=c.rounds*2, events=line.checks.filter(e=>e.ply<=limit&&e.kind==='mate'), color=current().side;
    let gain=0,loss=0;
    for(const e of line.captures){
      const round=Math.ceil(e.ply/2),end=2*(round+c.followup);
      if(round>c.start||end>=line.material.length||end>limit)continue;
      const sign=e.side===color?1:-1;
      const baseline=Math.max(sign*line.material[0],sign*line.material[e.ply-1]);
      const delta=Math.min(...line.material.slice(e.ply,end+1).map(v=>sign*v))-baseline;
      if(sign===1)gain=Math.max(gain,delta);else loss=Math.max(loss,delta);
    }
    return {mate:events.some(e=>e.side===color),mated:events.some(e=>e.side!==color),gain,loss};
  };
  const p=scan(a),n=scan(b),out=[];
  if(p.mate&&n.mate)out.push('两种走法在双方最优样本线上都完成将杀，按现行约定视为将杀结果等价。');
  else if(p.mate)out.push('推荐着在双方最优样本线上完成将杀。');
  if(n.mated)out.push('实战着在双方最优样本线上被将杀。');
  if(p.gain>n.gain)out.push(`推荐着在双方最优样本线上净得子${p.gain}点，已按所选回合数验证。`);
  if(n.loss>p.loss)out.push(`实战着让对手在双方最优样本线上净得子${n.loss}点。`);
  return out;
}
function schemeMetrics(data,scheme){
  if(!data)return null;
  const groups=[...new Set([data.recommended,data.played])].map(k=>data.roots[k]);
  if(groups.some(g=>!g?.schemes[scheme]))return null;
  const keys=new Set([data.root_search]);let count=0;
  for(const g of groups)for(const id of new Set([...g.schemes.main,...g.schemes[scheme]])){count++;g.lines[id].searches.forEach(k=>keys.add(k));}
  const base=data.searches[data.root_search].history.length;
  const values=[...keys].map(k=>data.searches[k]).filter(s=>s&&s.history.length-base<cfg().rounds*2);
  return {seconds:values.reduce((s,v)=>s+v.seconds,0), nodes:values.reduce((s,v)=>s+Math.max(...v.rows.map(r=>r.nodes)),0),queries:values.length,count};
}
function renderBench(){
  let html='<div class="table-scroll"><table class="bench-table"><tr><th>深度 / 方案</th><th>冷搜索合计</th><th>查询 / 节点</th><th>推荐着</th></tr>';
  for(const d of state.game.depths){const data=state.comparisons[d];for(const scheme of ['main','3x2','old8','5x3']){
    const m=schemeMetrics(data,scheme);let best='—';if(data){const c=new Chess(current().fen);best=c.move(data.recommended,{sloppy:true})?.san||data.recommended;}
    html+=`<tr><td>D${d} / ${scheme}</td><td>${m?`${m.seconds.toFixed(1)}秒`:'待计算'}</td><td>${m?`${m.queries} / ${(m.nodes/1e6).toFixed(2)}M`:'—'}</td><td>${esc(best)}</td></tr>`;
  }}$('bench').innerHTML=html+'</table></div>';
}
function renderConcepts(){
  const data=state.result,c=cfg(), g=groupFor(data,'positive');
  if(!data||!g?.schemes[c.scheme]||!groupFor(data,'negative')?.schemes[c.scheme]){
    $('concepts').innerHTML='<div class="empty">所选方案尚未完成。已算好的主线可在下方查看；切换深度或其他方案可读取对应缓存。</div>';
    $('preview').textContent='该深度、局面的所选方案尚未齐备，不生成完整比较结论。';return;
  }
  const rows=conceptRows(data), other=conceptRows(data,'opponent');
  const policy=$('policy').value;
  if(!state.manual){let selected=rows.filter(r=>qualifies(r,policy)); if(policy==='legacy')selected=tactical(data).length?[]:selected.slice(0,3);state.chosen=new Set(selected.map(r=>r.name));}
  let html='<div class="table-scroll"><table class="concept-table"><thead><tr><th>纳入表述 / 我方概念</th><th>推荐命中</th><th>实战命中</th><th>主线与待验证</th></tr></thead><tbody>';
  for(const r of rows){if(!r.positive&&!r.negative&&!r.pendingP&&!r.pendingN&&!r.mainP.hit&&!r.mainN.hit)continue;
    html+=`<tr><td><label style="display:block"><input type="checkbox" data-name="${esc(r.name)}" ${state.chosen.has(r.name)?'checked':''}>${esc(tr(r.name))}</label><button class="secondary inspect-rule" data-rule="${esc(r.name)}">${deferredConcept(r.name)?'尚未可视化':'棋盘核查'}</button></td><td>${r.positive}/${r.totalP}</td><td>${r.negative}/${r.totalN}</td><td>${r.stable?'<span class="badge">推荐主线差异</span>':r.adverse?'<span class="badge warn">实战主线出现</span>':''}<br>主线：${r.mainP.rounds.join(',')||'无'} / ${r.mainN.rounds.join(',')||'无'}<br>待验证：${r.pendingP} / ${r.pendingN}</td></tr>`;
  }
  html+='</tbody></table></div><details><summary>对手视角概念（避免把对手的优势写成我方优点）</summary>';
  for(const r of other.filter(r=>r.positive||r.negative||r.mainP.hit||r.mainN.hit))html+=`<p>${esc(tr(r.name))}：推荐 ${r.positive}/${r.totalP}，实战 ${r.negative}/${r.totalN} ${r.adverse?'<span class="badge warn">实战最优主线中出现，推荐主线未确认</span>':''}</p>`;
  $('concepts').innerHTML=html+'</details>';
  $('concepts').querySelectorAll('[data-name]').forEach(el=>el.addEventListener('change',()=>{state.manual=true;el.checked?state.chosen.add(el.dataset.name):state.chosen.delete(el.dataset.name);renderPreview(rows,other);}));
  $('concepts').querySelectorAll('[data-rule]').forEach(el=>el.onclick=()=>ReviewEvidence.choose(el.dataset.rule,state.line?state.line.frames[state.frame]:current().fen,current().side,state.line?`变化第${state.frame}半回合 · ${state.line.san.slice(0,state.frame).join(' ')}`:'实战走子之前的局面'));
  renderPreview(rows,other);
}
function renderPreview(rows,other){
  const data=state.result,c=cfg(), parts=tactical(data);
  if(data.recommended===data.played)parts.push('该深度的推荐着与实战着相同，以下仅记录这步的概念证据，不能视为走法差异。');
  for(const r of rows.filter(r=>state.chosen.has(r.name))){
    const verdict=r.stable?'在双方最优主线中成立，实战主线未确认':`在已采样推荐分支中确认${r.positive}/${r.totalP}条，实战${r.negative}/${r.totalN}条`;
    parts.push(`${tr(r.name)}：${verdict}。`);
  }
  if($('policy').value!=='legacy')for(const r of other.filter(r=>r.adverse))parts.push(`实战着的负面证据：对手“${tr(r.name).replaceAll('我方','其方').replaceAll('对方','我方')}”，见双方最优主线。`);
  $('preview').textContent=parts.length?parts.join('\n'):'当前规则未选出已确认结论；可降低连续验证回合数，或手动勾选概念。';
  if(c.rounds<c.start+c.followup)$('preview').textContent+='\n注意：读取窗口不足以验证所有候选起点，待验证项不会当成不成立。';
}
function setFrame(line,n){state.line=line;state.frame=Math.max(0,Math.min(n,Math.min(line.san.length,cfg().rounds*2)));board.setFen(line.frames[state.frame]);const caption=`变化第 ${state.frame} / ${Math.min(line.san.length,cfg().rounds*2)} 半回合 · ${line.san.slice(0,state.frame).join(' ')}`;$('board-caption').textContent=caption;$('fen').textContent=line.frames[state.frame];document.querySelectorAll('.moves button').forEach(b=>b.classList.toggle('active',b.dataset.line===line._id&&+b.dataset.frame===state.frame));ReviewEvidence.update(line.frames[state.frame],current().side,caption);}
function renderLines(){
  const data=state.result;if(!data){$('lines').innerHTML='<div class="empty">这个局面尚未写入缓存。</div>';return;}
  let html='';const rendered={};
  for(const side of ['positive','negative']){
    const group=groupFor(data,side);if(!group)continue;
    const ids=[...new Set([...(group.schemes.main||[]),...(group.schemes[cfg().scheme]||[])])];
    html+=`<h3>${side==='positive'?'推荐着':'实战着'} · ${esc(side==='positive'?data.recommended:data.played)}${data.recommended===data.played?'（相同）':''}</h3>`;
    ids.forEach((id,index)=>{const line=group.lines[id],lid=`${side}-${index}`;line._id=lid;rendered[lid]=line;
      html+=`<details ${index===0?'open':''}><summary>${index===0?'最优主线':`候选分支${index}`} · ${esc(line.san.slice(0,4).join(' '))} · ${Math.min(line.san.length,cfg().rounds*2)}半回合 ${line.terminal?`· 终局 ${esc(line.outcome)}`:''}</summary><div class="moves"><button data-line="${lid}" data-frame="0">起点</button>`;
      line.san.slice(0,cfg().rounds*2).forEach((san,j)=>html+=`<button data-line="${lid}" data-frame="${j+1}">${j%2===0?`${Math.floor(j/2)+1}. `:''}${esc(san)}</button>`);
      html+='</div><div class="rounds">';
      for(const r of line.rounds.slice(0,cfg().rounds))html+=`<div class="round-evidence"><b>第${r.round}回合</b><br>${r.own.length?r.own.map(n=>`<button class="concept-evidence" data-evidence-rule="${esc(n)}" data-evidence-line="${lid}" data-evidence-frame="${r.round*2}">${esc(tr(n))}${deferredConcept(n)?'〔尚未可视化〕':''}</button>`).join(''):'本回合无我方概念'}</div>`;
      const records=line.searches.map(k=>data.searches[k]).filter(Boolean), min=Math.min(...records.flatMap(s=>s.rows.map(r=>r.depth)));
      html+=`</div><p class="muted">独立查询${records.length}次 · 最小实际深度${min} · 保存完整历史 · ${line.terminal?'终局提前停止':'后续逐手SinglePV重搜'}</p></details>`;
    });
  }
  $('lines').innerHTML=html;$('lines').querySelectorAll('[data-line]').forEach(btn=>btn.onclick=()=>setFrame(rendered[btn.dataset.line],+btn.dataset.frame));
  $('lines').querySelectorAll('[data-evidence-rule]').forEach(btn=>btn.onclick=()=>{const line=rendered[btn.dataset.evidenceLine];setFrame(line,+btn.dataset.evidenceFrame);ReviewEvidence.choose(btn.dataset.evidenceRule,line.frames[+btn.dataset.evidenceFrame],current().side,`变化第${btn.dataset.evidenceFrame}半回合 · ${line.san.slice(0,+btn.dataset.evidenceFrame).join(' ')} · ${tr(btn.dataset.evidenceRule)}`);});
}
async function loadSelection(preserve=false){
  const token=++state.token,ply=+$('ply').value,depth=+$('depth').value;
  if(!preserve){state.manual=false;state.chosen.clear();$('note').value='';state.line=null;state.result=null;state.comparisons={};$('preview').textContent='正在读取所选深度的缓存…';$('concepts').textContent='';$('lines').textContent='正在读取…';board.setFen(current().fen);$('fen').textContent=current().fen;$('board-caption').textContent='实战走子之前的局面';}
  $('position-title').textContent=`${current().move_no}${current().side==='white'?'.':'…'} ${current().san} · D${depth}`;
  if(!preserve)ReviewEvidence.update(current().fen,current().side,'实战走子之前的局面');
  const loaded=await Promise.all(state.game.depths.map(async d=>{try{return [d,await api(`/api/result/${ply}/${d}`)];}catch(e){if(!/尚未计算/.test(e.message))message(e.message);return [d,null];}}));
  if(token!==state.token)return;state.comparisons=Object.fromEntries(loaded);state.result=state.comparisons[depth];
  if(!preserve){const note=await api(`/api/notes/${ply}/${depth}`);if(token!==state.token)return;$('note').value=note.text||'';if(note.chosen&&JSON.stringify(note.config)===JSON.stringify(cfg())&&note.policy===$('policy').value){state.manual=true;state.chosen=new Set(note.chosen);}}
  $('raw').textContent=state.result?JSON.stringify(state.result,null,2):'尚未计算';renderBench();renderConcepts();renderLines();
}
async function poll(){try{
  const s=await api('/api/status'),done=s.results.filter(r=>r.complete).length;$('overall').textContent=`${done} / ${s.target} 个局面×深度已完整计算`;
  $('progress').innerHTML=state.game.depths.map(d=>{const p=s.progress.find(p=>p.depth===d),n=s.results.filter(r=>r.depth===d&&r.complete).length,searches=s.searches.find(x=>x.depth===d)?.count||0;const names={starting:'准备中',running:'计算中',complete:'已完成',paused:'已暂停',error:'发生错误',interrupted:'已中断'};return `<div class="progress-card"><strong>深度 ${d} · ${names[p?.status]||'未启动'}</strong><progress max="70" value="${n}"></progress>${n}/${state.game.moves.length} 局面 · ${searches}个搜索缓存<br>${esc(p?.message||'等待启动')}${p?.ply?` · 第${p.ply}半回合`:''}${p?.search_started&&p.status==='running'?`<br>当前单次搜索 ${Math.max(0,Math.floor(Date.now()/1000-p.search_started))} 秒 · MultiPV ${p.multipv}`:''}</div>`;}).join('');
  const stamp=JSON.stringify(s.results.filter(r=>r.ply===+$('ply').value));if(state.stamp!==stamp){state.stamp=stamp;await loadSelection(true);}
}catch(e){message(e.message);}setTimeout(poll,5000);}
async function boot(){try{
  const featureFen = new URLSearchParams(location.search).get('featureFen');
  if (featureFen) {
    const payload = await api('/api/static-features', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({fen:featureFen})});
    state.motifs=payload.rules.map(r=>({name:r.name}));
    const cn = ['子力优势','综合位置优势','永久弱格控制','兵形与通路兵','敌王掩护','安全渗透','中央兵与空间','强制手段','阵营安全','出子与王安全','王区弱格','弱兵压力','劣质轻子','得子与反击','被动防守','先进通路兵','安全走法','将军主动权','推进过深的兵','多种弱点','子力组合','同色弱格','隐藏子力优势','攻后争先','双重威胁','具体目标压力','棋子受困','制造威胁','王活跃度','钉住与穿透'];
    payload.rules.forEach((r,i)=>state.translations[r.name]=cn[i]);
    ReviewEvidence.init(board,state.motifs,tr,()=>{});
    document.querySelector('header').hidden=true;
    for(const selector of ['.status','.controls','#turning-point-shows']) {const n=document.querySelector(selector);if(n)n.closest('section').hidden=true;}
    for(const n of document.querySelectorAll('.results > section'))if(n.id!=='evidence-panel')n.hidden=true;
    $('position-title').textContent='当前概念局面';$('fen').textContent=featureFen;
    await ReviewEvidence.update(featureFen,'white','所选局面');return;
  }
  [state.game,state.library]=await Promise.all([api('/api/game'),api('/api/concepts')]);state.translations=state.library.translations;state.motifs=state.library.motifs;
  ReviewEvidence.init(board,state.motifs,tr,(_fen,caption)=>{$('board-caption').textContent='证据局面：'+caption;});
  $('game-title').textContent=`数据库复盘 #${state.game.review_id} · ${state.game.moves.length}半回合 · 4种深度 · 逐手重搜`;
  $('ply').innerHTML=state.game.moves.map(m=>`<option value="${m.ply}">${m.move_no}${m.side==='white'?'.':'…'} ${esc(m.san)}${m.turning?' ★ 转折点':''}</option>`).join('');
  $('turning-point-shows').innerHTML=state.game.moves.filter(m=>m.turning).map(m=>`<div class="turning-show"><span>${m.move_no}${m.side==='white'?'.':'…'} ${esc(m.san)}</span><button data-show-ply="${m.ply}" aria-label="显示 ${m.move_no}.${esc(m.san)} 的静态特征">显示</button></div>`).join('');
  $('turning-point-shows').querySelectorAll('[data-show-ply]').forEach(btn=>btn.onclick=async()=>{$('ply').value=btn.dataset.showPly;await loadSelection();ReviewEvidence.show();});
  $('ply').value=state.game.moves.filter(m=>m.turning).at(-1)?.ply||1;
  await loadSelection();poll();
}catch(e){message(e.message);}}
$('ply').onchange=()=>loadSelection().catch(e=>message(e.message));$('depth').onchange=$('ply').onchange;
for(const id of ['scheme','rounds','followup','start-round','policy'])$(id).addEventListener('change',()=>{state.manual=false;$('round-value').textContent=$('rounds').value;renderBench();renderConcepts();renderLines();if(state.line)setFrame(state.line,state.frame);});
$('rounds').oninput=()=>{$('round-value').textContent=$('rounds').value;};
$('start').onclick=async()=>{try{await api('/api/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({depths:state.game.depths})});message('已启动4个深度的计算。已有完整局面会跳过，已有逐手搜索会直接复用。');}catch(e){message(e.message);}};
$('pause').onclick=async()=>{try{const r=await api('/api/pause',{method:'POST'});message(r.message);}catch(e){message(e.message);}};
$('home').onclick=()=>{if(state.line)setFrame(state.line,0);};$('prev').onclick=()=>{if(state.line)setFrame(state.line,state.frame-1);};$('next').onclick=()=>{if(state.line)setFrame(state.line,state.frame+1);};$('flip').onclick=()=>{board.setOrientation(board.orientation==='white'?'black':'white');ReviewEvidence.redraw();};
$('save-note').onclick=async()=>{try{await api(`/api/notes/${$('ply').value}/${$('depth').value}`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({payload:{evidence:ReviewEvidence.snapshot(),text:$('note').value,chosen:[...state.chosen],config:cfg(),policy:$('policy').value,preview:$('preview').textContent,saved:new Date().toISOString()}})});message('勾选、规则和测试记录已保存到独立测试数据库。');}catch(e){message(e.message);}};
$('export').onclick=()=>{const blob=new Blob([JSON.stringify({game:state.game,ply:+$('ply').value,depth:+$('depth').value,config:cfg(),policy:$('policy').value,chosen:[...state.chosen],preview:$('preview').textContent,note:$('note').value,evidence:ReviewEvidence.snapshot(),comparisons:state.comparisons},null,2)],{type:'application/json'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=`review-lab-ply${$('ply').value}-D${$('depth').value}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);};
boot();
