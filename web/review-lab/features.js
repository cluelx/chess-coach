/* Stable static witnesses: render only backend coordinates and typed relations. */
window.createReviewEvidence = (root = document, options = {}) => {
  const $=id=>root === document ? document.getElementById(id) : root.querySelector(`[data-evidence="${id}"]`), esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const pending=new Map(), cache=new Map();
  let board, payload=null, fen=null, color='white', caption='', translate, callback, token=0, selected=null, overlay=[], markers=[], square=null, names=[];
  let disposed=false;
  const active=()=>!disposed && (root===document || (root.isConnected && board?.fen===fen));
  const side=c=>c==='white'?'白方':'黑方';
  const labels={2:'综合位置优势（含子力差惩罚）',6:'安全渗透（当前已深入的棋子）',7:'中央兵与空间优势'};
  const title=r=>labels[r.id]||translate(r.name);
  function rule(){return payload?.rules.find(r=>String(r.id)===$('feature-rule').value);}
  function accepts(f){return $('feature-type').value==='all'?$('feature-aux').checked||f.highlight:$('feature-type').value===f.type;}
  function visible(){const r=rule();if(!r||r.visualization_status!=='ready')return[];return ['white','black'].filter(s=>$('feature-side').value==='both'||$('feature-side').value===s).flatMap(s=>r[s].features.filter(accepts));}
  function draw(){
    if(!board || !active())return;board.setMarks([]);board.setArrows([]);
    const ns='http://www.w3.org/2000/svg',point=s=>{let f=s.charCodeAt(0)-97,r=+s[1]-1;if(board.orientation!=='white'){f=7-f;r=7-r;}return[(f+.5)*12.5,(7-r+.5)*12.5];};
    const add=(tag,attrs)=>{const n=document.createElementNS(ns,tag);for(const[k,v]of Object.entries(attrs))n.setAttribute(k,v);board.arrowSvg.append(n);};
    for(const m of markers){const[x,y]=point(m.square),white=m.side==='white',stroke=white?'#1d66b8':'#bc6d09';add(white?'circle':'rect',white?{cx:x,cy:y,r:5.1,fill:'none',stroke,'stroke-width':.85}:{x:x-5.1,y:y-5.1,width:10.2,height:10.2,rx:1.1,fill:'none',stroke,'stroke-width':.85});}
    if(square){const[x,y]=point(square);add('circle',{cx:x,cy:y,r:3,fill:'none',stroke:'#8d3e98','stroke-width':.7});}
    for(const a of overlay){if(a.source===a.target)continue;const[x1,y1]=point(a.source),[x2,y2]=point(a.target),angle=Math.atan2(y2-y1,x2-x1),protect=a.type==='protect',stroke=protect?'#326cc1':'#bd3e49';add('line',{x1,y1,x2:x2-Math.cos(angle)*2.5,y2:y2-Math.sin(angle)*2.5,stroke,'stroke-width':1,'stroke-dasharray':protect?'2 1':'none'});add('polygon',{points:[[x2,y2],[x2-Math.cos(angle-.45)*2.5,y2-Math.sin(angle-.45)*2.5],[x2-Math.cos(angle+.45)*2.5,y2-Math.sin(angle+.45)*2.5]].map(p=>p.join(',')).join(' '),fill:stroke});}
    board.squares.forEach(n=>n.onclick=()=>inspectSquare(n.dataset.sq));
  }
  function use(features,allRelations=false){
    square=null;markers=features.flatMap(f=>f.squares.map(square=>({square,side:f.side})));
    const unique=new Map();for(const f of features)for(const r of f.relations)unique.set(JSON.stringify(r),r);
    overlay=allRelations?[...unique.values()]:[];draw();
  }
  function showFeature(id){
    if(!active())return;
    const r=rule(),f=['white','black'].flatMap(s=>r[s].features).find(f=>f.id===id);if(!f)return;
    selected=id;use([f],true);
    $('feature-detail').innerHTML=`<h3>${esc(side(f.side))} · ${esc(f.label)}</h3><p>坐标：${esc(f.squares.join('、')||'无')} · 特征分：${esc(f.score??'不单独计分')} · ${f.counted_in_feature_score?'计入该特征分':'辅助项目，不计入该特征分'}</p><pre>${esc(JSON.stringify(f.details,null,2))}</pre><pre>${esc(f.relation_text.join('\n')||'此项目没有直接攻防关系。')}</pre>`;
    $('feature-items').querySelectorAll('[data-feature-id]').forEach(b=>b.classList.toggle('is-selected',b.dataset.featureId===id));
    $('feature-board-status').textContent=`${caption} · ${side(f.side)}：${f.label} ${f.squares.join('、')}`;
  }
  function render(){
    if(!active())return;
    const r=rule();if(!r)return;selected=null;
    $('feature-rule').title=r.description||'';
    $('feature-status').title=r.description||'';
    let help=$('feature-rule-help');
    if(!help){help=document.createElement('details');help.dataset.evidence='feature-rule-help';help.id=root===document?'feature-rule-help':'';$('feature-scores').insertAdjacentElement('afterend',help);}
    help.replaceChildren();const heading=document.createElement('summary');heading.textContent='判定说明';const text=document.createElement('p');text.textContent=r.description||'当前数据暂未包含说明，请刷新后重试。';help.append(heading,text);
$('feature-detail').innerHTML='';
    const previousType=$('feature-type').value,types=new Map();if(r.visualization_status==='ready')for(const s of ['white','black'])for(const f of r[s].features)types.set(f.type,f.label);
    $('feature-type').innerHTML='<option value="all">全部类别</option>'+[...types].sort((a,b)=>a[0].localeCompare(b[0])).map(([type,label])=>`<option value="${esc(type)}">${esc(label)}</option>`).join('');$('feature-type').value=types.has(previousType)?previousType:'all';
    $('feature-status').textContent=r.visualization_status==='ready'?`#${r.id} · 双方静态特征已返回。原规则总判定：白方${r.matched.white?'成立':'不成立'}，黑方${r.matched.black?'成立':'不成立'}。`:`#${r.id} · ${r.reason}`;
    $('feature-scores').textContent=r.visualization_status==='ready'?`白方特征分 ${JSON.stringify(r.white.score)}；黑方特征分 ${JSON.stringify(r.black.score)}${r.white_minus_black!==undefined?`；白减黑 ${r.white_minus_black}`:''}`:'';
    if(r.visualization_status!=='ready'){$('feature-items').innerHTML='<p class="empty">尚未可视化：候选步/走法类，本轮暂不处理。这里没有用空清单冒充“没有特征”。</p>';use([]);}
    else{
      $('feature-items').innerHTML=['white','black'].filter(s=>$('feature-side').value==='both'||$('feature-side').value===s).map(s=>{const features=r[s].features.filter(accepts);return `<h3>${side(s)}项目 · ${features.length}项</h3><div class="feature-buttons">${features.map(f=>`<button class="secondary" data-feature-id="${f.id}">${esc(f.label)} · ${esc(f.squares.join(' ')||'无坐标')}${!f.counted_in_feature_score?'〔辅助〕':''}</button>`).join('')||'<span class="muted">当前没有此类特征。</span>'}</div>`;}).join('');
      $('feature-items').querySelectorAll('[data-feature-id]').forEach(b=>b.onclick=()=>showFeature(b.dataset.featureId));use(visible(),r.id===15);
    }
    const texts=r.visualization_status==='ready'?['white','black'].flatMap(s=>r[s].features.flatMap(f=>[`${side(s)} | ${f.type} | ${f.squares.join(',')} | ${f.label} | 特征分=${f.score??'null'} | 计分=${f.counted_in_feature_score}`,...f.relation_text])):[r.reason];
    $('feature-text').textContent=texts.join('\n');$('feature-raw').textContent=JSON.stringify($('feature-print-all').checked?payload:r,null,2);
    $('feature-board-status').textContent=`${caption} · #${r.id} ${title(r)}`;
  }
  function inspectSquare(target){
    if(!payload||!active())return;square=target;
    const features=rule()?.visualization_status==='ready'?['white','black'].flatMap(s=>rule()[s].features.filter(f=>f.squares.includes(target))):[];
    const texts=features.map(f=>`${side(f.side)}：${f.label}`);
    $('feature-square-info').textContent=`${target} · ${texts.join('；')||'不是当前概念的已返回目标'}`;
    const edges=features.flatMap(f=>f.relations.filter(r=>r.target===target||r.source===target));overlay=[...new Map(edges.map(e=>[JSON.stringify(e),e])).values()];draw();
  }
  async function request(position){
    if(options.payload?.fen===position)return options.payload;
    if(cache.has(position))return cache.get(position);
    if(!pending.has(position))pending.set(position,(async()=>{const r=await fetch('/api/static-features',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({fen:position})});const p=await r.json();if(!r.ok)throw Error(p.detail||'静态特征读取失败');cache.set(position,p);if(cache.size>12)cache.delete(cache.keys().next().value);return p;})().finally(()=>pending.delete(position)));
    return pending.get(position);
  }
  async function update(position,perspective,description){
    fen=position;color=perspective;caption=description;const current=++token;payload=null;selected=null;markers=[];overlay=[];square=null;
    board.setFen(position);draw();$('feature-status').textContent='正在读取21项静态特征…';$('feature-items').innerHTML='';$('feature-detail').innerHTML='';$('feature-raw').textContent='';$('feature-text').textContent='';$('feature-square-info').textContent='';$('feature-board-status').textContent=description;
    if(callback)callback(position,description);
    try{const p=await request(position);if(current!==token||!active())return;payload=p;console.log('[复盘静态特征返回]',p);render();}catch(e){if(current===token&&active())$('feature-status').textContent=e.message;}
  }
  return{
    init(b,library,tr,onShow){board=b;translate=tr;callback=onShow;names=library.map(r=>r.name);$('feature-rule').innerHTML=library.map((r,i)=> options.allowedNames && !options.allowedNames.includes(r.name) ? '' : `<option value="${i+1}">${i+1}. ${esc(labels[i+1]||tr(r.name))}${[8,14,17,18,23,24,25,28,30].includes(i+1)?'〔尚未可视化〕':''}</option>`).join('');$('feature-rule').value=options.allowedNames ? String(library.findIndex(r=>options.allowedNames.includes(r.name))+1) : '3';
      for(const id of ['feature-rule','feature-side','feature-type','feature-aux'])$(id).onchange=()=>{if(payload)render();};
      $('feature-print-all').onchange=()=>{if(payload)$('feature-raw').textContent=JSON.stringify($('feature-print-all').checked?payload:rule(),null,2);};
      $('feature-show').onclick=()=>{if(fen)update(fen,color,caption);};$('feature-show-all').onclick=()=>{if(payload){selected=null;use(visible());$('feature-detail').innerHTML='';}};
      $('feature-show-relations').onclick=()=>{if(payload)use(visible(),true);};
    },update,
    dispose(){disposed=true;token++;if(board){board.setMarks([]);board.setArrows([]);board.render();}},
    choose(name,position,perspective,description){const id=names.indexOf(name)+1;if(id)$('feature-rule').value=String(id);update(position,perspective,description);$('evidence-panel').scrollIntoView({block:'start',behavior:'smooth'});},
    show(){ $('evidence-panel').scrollIntoView({block:'start',behavior:'smooth'}); },
    redraw:draw,
    snapshot(){return payload?{version:payload.version,rule_id:rule()?.id,fen,color,caption,feature_id:selected,side:$('feature-side').value,type:$('feature-type').value,include_auxiliary:$('feature-aux').checked}:null;}
  };
};
window.ReviewEvidence = window.createReviewEvidence();
