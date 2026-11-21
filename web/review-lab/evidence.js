/* Original-rule evidence. All diagnostics are local rules, never new engine searches. */
window.ReviewEvidence = (() => {
  const el=id=>document.getElementById(id);
  const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const side=c=>c==='white'?'白方':'黑方';
  let board, data, baseFen, baseCaption, displayedFen, token=0, relationToken=0, activeSquare, overlay=[], relationRows=[], callback, selectedCapture=null;
  async function post(path,body){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const out=await r.json();if(!r.ok)throw Error(out.detail||'读取证据失败');return out;}
  function tab(name){for(const key of ['relations','captures','conditions'])el('evidence-'+key).hidden=key!==name;document.querySelectorAll('[data-evidence-tab]').forEach(b=>b.classList.toggle('secondary',b.dataset.evidenceTab!==name));}
  function draw(){
    if(!board)return;
    board.setMarks(activeSquare?[activeSquare]:[]);board.setArrows([]);
    const ns='http://www.w3.org/2000/svg', xy=s=>{const f=s.charCodeAt(0)-97,r=+s[1]-1;return board.orientation==='white'?[(f+.5)*12.5,(7-r+.5)*12.5]:[(7-f+.5)*12.5,(r+.5)*12.5];};
    for(const a of overlay){if(a.from===a.to)continue;const [x1,y1]=xy(a.from),[x2,y2]=xy(a.to),angle=Math.atan2(y2-y1,x2-x1),len=Math.hypot(x2-x1,y2-y1),short=Math.min(3,len*.25),color=a.kind==='defend'?'#326cc1':a.kind==='move'?'#bf741b':'#bd3e49';
      const line=document.createElementNS(ns,'line');for(const [k,v] of Object.entries({x1,y1,x2:x2-Math.cos(angle)*short,y2:y2-Math.sin(angle)*short,stroke:color,'stroke-width':1.05,'stroke-linecap':'round'}))line.setAttribute(k,v);if(a.kind==='defend')line.setAttribute('stroke-dasharray','2 1');board.arrowSvg.append(line);
      const head=document.createElementNS(ns,'polygon');head.setAttribute('points',[[x2,y2],[x2-Math.cos(angle-.45)*2.5,y2-Math.sin(angle-.45)*2.5],[x2-Math.cos(angle+.45)*2.5,y2-Math.sin(angle+.45)*2.5]].map(p=>p.join(',')).join(' '));head.setAttribute('fill',color);board.arrowSvg.append(head);
    }
    board.squares.forEach(sq=>sq.onclick=()=>selectSquare(sq.dataset.sq));
  }
  async function showFen(fen,caption){
    const changed=displayedFen!==fen;displayedFen=fen;board.setFen(fen);el('fen').textContent=fen;
    const location=caption.startsWith(baseCaption||'')?caption:`${baseCaption} · ${caption}`;
    el('evidence-context').textContent=location+(fen===data?.fen?'':' · 这是规则执行中使用的局面；含试走或换行棋权的状态');
    if(callback)callback(fen,location);draw();
    if(!changed)return;
    const myToken=++relationToken;relationRows=[];
    try{const rows=fen===data?.fen?data.relations:await post('/api/evidence/relations',{fen});if(myToken!==relationToken)return;relationRows=rows;if(activeSquare)selectSquare(activeSquare,false);}catch(e){el('square-status').textContent=e.message;}
  }
  function selectSquare(square,replace=true){
    activeSquare=square;const row=relationRows.find(r=>r.square===square);if(!row){el('square-status').textContent='正在读取该局面的攻击关系…';draw();return;}
    const owner=row.owner,parts=[];
    for(const color of ['white','black']){const protect=owner===color;parts.push(`${side(color)}${protect?'保护':'攻击/控制'} ${row[color].length}：${row[color].join('、')||'无'}`);}
    el('square-status').textContent=`${square}（${row.piece}）· ${parts.join('；')}。计入被钉住的棋子，与原攻击查询一致。`;
    if(replace)overlay=['white','black'].flatMap(c=>row[c].map(from=>({from,to:square,kind:owner===c?'defend':'attack'})));
    draw();
  }
  function sourceLine(line){el('evidence-source').innerHTML=data.source.split('\n').map((s,i)=>`<span class="${i+1===line?'source-active':''}">${String(i+1).padStart(3)} ${esc(s)}</span>`).join('\n');}
  async function query(){
    const record=data?.records[+el('evidence-query').value];if(!record)return;
    overlay=[];activeSquare=record.target||record.source;
    if(record.kind==='attackers'){
      const c=new Chess(record.fen),piece=c.get(record.target),kind=piece&&((piece.color==='w')===(record.color==='white'))?'defend':'attack';
      overlay=record.sources.map(from=>({from,to:record.target,kind}));
      el('query-status').textContent=`原调用结果：${side(record.color)} ${record.sources.length}个棋子 → ${record.target}（${record.sources.join('、')||'无'}）${record.pinned.length?`；其中被钉住：${record.pinned.join('、')}`:''}。这是查询原始集合，后续是否过滤王或兵请查看判定过程。`;
    }else if(record.kind==='coverage'){
      const c=new Chess(record.fen),p=c.get(record.source);
      overlay=record.targets.map(to=>({from:record.source,to,kind:p&&c.get(to)?.color===p.color?'defend':'attack'}));
      el('query-status').textContent=`${record.source} 的几何控制范围：${record.targets.join('、')||'无'}。包含同方棋子占据的受保护格；不等同于合法落点。`;
    }else el('query-status').textContent=`${record.target} 被钉住：${record.value?'是':'否'}`;
    sourceLine(record.line);await showFen(record.fen,`${record.function} · 原代码第${record.line}行`);
  }
  function renderMaterial(){
    const m=data.material;el('evidence-material').innerHTML=`<p>${data.material_uses_rule_values?'原规则子力表':'本规则未定义完整子力表，以下使用1/3/3/5/9辅助表'} · 白方 ${m.white}，黑方 ${m.black}，${side(data.color)}差值 ${m.difference}（原始单位）</p><div class="table-scroll"><table class="concept-table"><tr><th>棋子</th><th>单价</th><th>白方数量 / 位置</th><th>黑方数量 / 位置</th></tr>${m.rows.map(r=>`<tr><td>${r.piece}</td><td>${r.value}</td><td>${r.white.length} / ${r.white.join(' ')||'无'}</td><td>${r.black.length} / ${r.black.join(' ')||'无'}</td></tr>`).join('')}</table></div>`;
  }
  function renderScores(){
    const scores=data.records.filter(r=>r.kind==='return'&&r.caller==='motif'&&r.function!=='motif'&&typeof r.value!=='boolean');
    el('evidence-scores').innerHTML=scores.length?`<details open><summary>原规则本次实际计算的分数</summary><div class="table-scroll"><table class="concept-table"><tr><th>计算函数 / 参数</th><th>原始得分</th></tr>${scores.map(r=>`<tr><td>${esc(r.function)}(${esc(Object.entries(r.arguments||{}).map(([k,v])=>`${k}=${typeof v==='boolean'&&['us','them','stm','opp','color','side','c','a','d','atk','dfn'].includes(k)?side(v?'white':'black'):JSON.stringify(v)}`).join(', '))})</td><td>${esc(JSON.stringify(r.value))}</td></tr>`).join('')}</table></div></details>`:'';
  }
  function renderCaptures(){
    const c=data.captures;el('capture-summary').innerHTML=`<p class="capture-total">${side(data.color)}最佳吃子得分 ${c.own.best} − ${side(data.color==='white'?'black':'white')}最佳吃子得分 ${c.opponent.best} = <strong>${c.difference}</strong> 点</p>`;
    el('capture-list').innerHTML=['own','opponent'].map(key=>`<h3>${key==='own'?'所选方':'对手'}归并后的候选吃子</h3>${c[key].candidates.length?`<div class="table-scroll"><table class="concept-table"><tr><th>棋步 / 棋盘证据</th><th>吃到及升变收益</th><th>出动子价值</th><th>静态净得分</th></tr>${c[key].candidates.map((r,i)=>`<tr><td><button class="secondary" data-capture-side="${key}" data-capture-index="${i}">${esc(r.san)} · ${r.source}→${r.target}${r.en_passant?'（吃过路兵）':''}${r.promotion?'（升变）':''}</button></td><td>${r.victim_value}</td><td>${r.attacker_value}</td><td>${r.gain}</td></tr>`).join('')}</table></div>`:'<p>没有合法吃子候选。</p>'}`).join('');
    el('capture-steps').innerHTML='';el('capture-list').querySelectorAll('[data-capture-side]').forEach(b=>b.onclick=async()=>{
      const r=c[b.dataset.captureSide].candidates[+b.dataset.captureIndex];selectedCapture=r;activeSquare=r.target;overlay=[...r.attackers.map(from=>({from,to:r.target,kind:'attack'})),...r.defenders.map(from=>({from,to:r.target,kind:'defend'})),{from:r.source,to:r.target,kind:'move'}];
      el('capture-steps').innerHTML=`<h3>${esc(r.san)}：原规则交换估算</h3><p>固定列表：进攻方 ${r.attackers.join('、')||'无'}；防守方 ${r.defenders.join('、')||'无'}。回溯最优停止交换后得分：${r.gain}。</p><div class="table-scroll"><table class="concept-table"><tr><th>轮次</th><th>估算吃子方</th><th>吃到价值</th><th>参与交换子价值</th><th>首吃方累计</th></tr>${r.steps.map((s,i)=>`<tr><td>${i+1}</td><td>${side(s.side)}</td><td>${s.taken}</td><td>${s.attacker}</td><td>${s.cumulative}</td></tr>`).join('')}</table></div><p class="muted">向前递推：${r.forward.join('，')}；停止交换回溯：${r.backed.join('，')}。这是按价值排序的估算，不是完整合法换子变化。</p>`;
      if(r.en_passant)el('capture-steps').insertAdjacentHTML('beforeend',`<p>吃过路兵：实际被吃的兵位于 ${r.target[0]}${+r.target[1]+(r.side==='white'?-1:1)}；原规则在落点 ${r.target} 查询交换关系。</p>`);
      if(r.promotion)el('capture-steps').insertAdjacentHTML('beforeend','<p>原规则对升变统一加8点，并将升变后棋子按后9点计入交换；这里保留了包括欠升变在内的原实现行为。</p>');
      await showFen(r.fen,`${side(r.side)}候选 ${r.san} · 吃子之前的计算局面`);
    });
  }
  function renderConditions(auto=true){
    const filter=el('condition-filter').value;
    const records=data.records.filter(r=>filter==='condition'?r.kind==='condition':filter==='score'?r.kind==='score':r.kind==='return'||r.function==='motif'&&r.kind==='condition');
    el('evidence-condition').innerHTML=records.map(r=>`<option value="${r.id}">${r.id+1} · ${esc(r.function)} L${r.line} · ${r.kind==='return'?`返回 ${esc(JSON.stringify(r.value))}`:esc(r.expression)}${r.kind==='condition'?` → ${r.value?'成立':'不成立'}`:''}</option>`).join('');
    if(!records.length)el('condition-detail').textContent='这次执行没有此类记录，可能已被前面的条件提前终止。';else if(auto)condition();else el('condition-detail').textContent='选择一条执行记录，即可查看当时的局面、变量与原代码。';
  }
  async function condition(){
    const r=data?.records[+el('evidence-condition').value];if(!r)return;
    sourceLine(r.line);const locals=r.locals||{};
    el('condition-detail').innerHTML=`<p><strong>${esc(r.function)} · L${r.line}</strong> ${esc(r.expression||'return')} ${r.value!==undefined?`→ ${esc(JSON.stringify(r.value))}`:''}</p><p class="muted">以下为该判断实际执行时的变量；sq、square、to等是格子编号（a1=0）。点任意棋盘格可单独查看关系。</p><pre>${esc(JSON.stringify(locals,null,2))}</pre>`;
    overlay=[];activeSquare=null;
    for(const k of ['sq','square','to','to_sq','fsq','target'])if(Number.isInteger(locals[k])&&locals[k]>=0&&locals[k]<64){activeSquare=String.fromCharCode(97+locals[k]%8)+(Math.floor(locals[k]/8)+1);break;}
    await showFen(r.fen,`${r.function} · 原代码第${r.line}行 · ${r.kind==='score'?'计分变化':'判定过程'}`);
    if(activeSquare)selectSquare(activeSquare);
  }
  async function inspect(fen,color,caption){
    baseFen=fen;baseCaption=caption;const myToken=++token;
    el('evidence-status').textContent='正在执行原规则并提取证据…';
    try{
      const r=await post('/api/evidence',{fen,color,rule:el('evidence-rule').value});if(myToken!==token)return;data=r;selectedCapture=null;
      el('evidence-status').textContent=`${r.matched?'本局面规则成立':'本局面规则不成立'} · 已核对与未插入观察逻辑的原规则结果一致${r.omitted?` · 记录过多，省略${r.omitted}条中间记录`:''}`;
      el('evidence-query').innerHTML=r.records.filter(x=>['attackers','coverage','pin'].includes(x.kind)).map(x=>`<option value="${x.id}">${esc(x.function)} L${x.line} · ${x.kind==='attackers'?`${side(x.color)}→${x.target}（${x.sources.length}）`:x.kind==='coverage'?`${x.source}控制范围（${x.targets.length}）`:`${x.target}钉住=${x.value}`}</option>`).join('');
      renderScores();renderMaterial();renderCaptures();renderConditions(false);sourceLine(0);
      // Rendering the condition selector must not silently move the board away from the requested frame.
      activeSquare=null;overlay=[];await showFen(r.fen,caption+` · ${side(color)}判断视角`);
      const first=r.records.find(x=>x.kind==='attackers'&&x.sources.length&&x.fen===r.fen);
      if(first){el('evidence-query').value=first.id;if(!el('evidence-relations').hidden)await query();}
      else el('query-status').textContent='本次规则在查询攻击关系之前已退出，或该规则未使用攻击查询；可点击棋盘任意格辅助检查。';
    }catch(e){if(myToken===token){data=null;overlay=[];activeSquare=null;draw();el('evidence-status').textContent=e.message;}}
  }
  return {
    init(b,library,translate,onShow){board=b;callback=onShow;el('evidence-rule').innerHTML=library.map(m=>`<option value="${esc(m.name)}">${esc(translate(m.name))}</option>`).join('');el('evidence-rule').value='pressure on the opponent weak pawns';
      for(const id of ['evidence-rule','evidence-color'])el(id).onchange=()=>{if(baseFen)inspect(baseFen,el('evidence-color').value,baseCaption);};
      document.querySelectorAll('[data-evidence-tab]').forEach(b=>b.onclick=()=>{tab(b.dataset.evidenceTab);if(b.dataset.evidenceTab==='relations')query();});
      el('evidence-query').onchange=query;el('condition-filter').onchange=()=>{if(data)renderConditions();};el('evidence-condition').onchange=condition;
      el('evidence-reset').onclick=()=>{if(baseFen)inspect(baseFen,el('evidence-color').value,baseCaption);};
    },
    update(fen,color,caption){el('evidence-color').value=color;return inspect(fen,color,caption);},
    choose(rule,fen,color,caption){el('evidence-rule').value=rule;el('evidence-color').value=color;tab('relations');el('evidence-panel').scrollIntoView({block:'start',behavior:'smooth'});return inspect(fen,color,caption);},
    redraw:draw,
    snapshot(){return data&&data.input_fen===baseFen&&data.rule===el('evidence-rule').value&&data.color===el('evidence-color').value?{rule:data.rule,color:data.color,matched:data.matched,base_fen:baseFen,displayed_fen:displayedFen,
      square:activeSquare,overlay,captures:data.captures.difference,material:data.material.difference,
      query:!el('evidence-relations').hidden?data.records[+el('evidence-query').value]:null,
      condition:!el('evidence-conditions').hidden?data.records[+el('evidence-condition').value]:null,
      capture:!el('evidence-captures').hidden?selectedCapture:null}:null;}
  };
})();
