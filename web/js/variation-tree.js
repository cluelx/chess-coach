/* Horizontal chess variation tree. children[0] continues the current lane. */
window.VariationTree = function ({nodes, currentNodeId, onSelect}) {
  const host = document.createElement('div'); host.className = 'variation-tree';
  const collapsed = new Set(); let current = currentNodeId;
  function render() {
    host.replaceChildren();
    const roots = Object.keys(nodes).filter(id => !nodes[nodes[id].parentId]);
    const positions = new Map(), occupied = new Set();
    function free(id, lane, depth) {
      let n = nodes[id]; while(n) { if(occupied.has(`${n.ply}:${lane}`))return false; n=collapsed.has(n.id)?null:nodes[n.children[0]]; } return true;
    }
    function place(id,lane,depth) {
      const n=nodes[id]; if(!n)return;
      positions.set(id,{x:n.ply*80,y:lane*44,depth});occupied.add(`${n.ply}:${lane}`);
      if(collapsed.has(id))return;
      if(n.children[0])place(n.children[0],lane,depth);
      n.children.slice(1).forEach((child,i)=>{const sign=depth%2===0?1:-1;let offset=i+1;while(!free(child,lane+sign*offset,depth+1))offset++;place(child,lane+sign*offset,depth+1);});
    }
    // Assign ids without requiring callers to duplicate the Record key.
    for(const [id,n] of Object.entries(nodes))n.id=id;
    roots.forEach((id,i)=>place(id,i*4,0));
    const ys=[...positions.values()].map(p=>p.y), min=Math.min(0,...ys), max=Math.max(0,...ys);
    const canvas=document.createElement('div');canvas.className='variation-tree-canvas';canvas.style.width=(Math.max(0,...[...positions.values()].map(p=>p.x))+100)+'px';canvas.style.height=(max-min+100)+'px';
    const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('class','variation-tree-lines');canvas.append(svg);
    const ancestors=new Set();for(let id=current;nodes[id];id=nodes[id].parentId){if(ancestors.has(id))break;ancestors.add(id);}
    for(const [id,p]of positions){const n=nodes[id],parent=positions.get(n.parentId),main=nodes[n.parentId]?.children[0]===id;
      if(parent){const path=document.createElementNS(svg.namespaceURI,'path');const x=parent.x+64,y=parent.y-min+44,tx=p.x,ty=p.y-min+44;path.setAttribute('d',`M${x} ${y} H${x+8} V${ty} H${tx}`);if(!main)path.setAttribute('stroke-dasharray','4 3');svg.append(path);}
      const b=document.createElement('button');b.type='button';b.className='variation-tree-node'+(p.depth?' secondary':'')+(ancestors.has(id)?' path':'')+(id===current?' current':'')+(n.conceptMarks?.length?' concept-true':'');b.style.left=p.x+'px';b.style.top=(p.y-min+28)+'px';b.textContent=n.san;b.title=(n.conceptMarks||[]).join('；');b.onclick=()=>{current=id;render();onSelect(id);};canvas.append(b);
      if(n.children.length>1){const toggle=document.createElement('button');toggle.className='variation-tree-toggle';toggle.style.left=(p.x+50)+'px';toggle.style.top=(p.y-min+12)+'px';toggle.textContent=collapsed.has(id)?'+':'−';toggle.setAttribute('aria-label','折叠或展开 '+n.san+' 的后续');toggle.setAttribute('aria-expanded',String(!collapsed.has(id)));toggle.onclick=()=>{collapsed.has(id)?collapsed.delete(id):collapsed.add(id);render();};canvas.append(toggle);}
    }
    host.append(canvas);
  }
  render(); return host;
};
