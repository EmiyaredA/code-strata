// Geometry only. Semantic IDs, edges and evidence are never synthesized here.
const rect=n=>({x:n.position.x,y:n.position.y,width:n.width,height:n.height});
const intersects=(a,b,p=0)=>a.x<b.x+b.width+p&&a.x+a.width>b.x-p&&a.y<b.y+b.height+p&&a.y+a.height>b.y-p;
function absolute(nodes){const by=new Map(nodes.map(n=>[n.id,n]));return nodes.map(n=>{let r=rect(n),p=n.parentId;while(p){const parent=by.get(p);r.x+=parent.position.x;r.y+=parent.position.y;p=parent.parentId;}return {...r,id:n.id,container:n.data?.container};});}
function projected(n,position,size,extra={}){return {id:n.id,type:'uml',position,width:size.width,height:size.height,style:{...size},data:{node:n,...extra}};}
function segments(points){return points.slice(1).map((p,i)=>[points[i],p]);}
function hits(a,b,r){return a.x===b.x?a.x>r.x&&a.x<r.x+r.width&&Math.max(a.y,b.y)>r.y&&Math.min(a.y,b.y)<r.y+r.height:a.y>r.y&&a.y<r.y+r.height&&Math.max(a.x,b.x)>r.x&&Math.min(a.x,b.x)<r.x+r.width;}
// Sparse orthogonal visibility grid. Parent boundaries are not obstacles.
export function orthogonalRoute(a,b,obstacles){
 const start={x:a.x+a.width/2,y:a.y+a.height+12},end={x:b.x+b.width/2,y:b.y-12};
 const boxes=obstacles.map(r=>({...r,x:r.x-10,y:r.y-10,width:r.width+20,height:r.height+20}));
 const xs=[...new Set([start.x,end.x,...boxes.flatMap(r=>[r.x-4,r.x+r.width+4])])].sort((a,b)=>a-b);
 const ys=[...new Set([start.y,end.y,...boxes.flatMap(r=>[r.y-4,r.y+r.height+4])])].sort((a,b)=>a-b);
 const key=(x,y)=>y*xs.length+x, coords=k=>({x:xs[k%xs.length],y:ys[Math.floor(k/xs.length)]});
 const first=key(xs.indexOf(start.x),ys.indexOf(start.y)),last=key(xs.indexOf(end.x),ys.indexOf(end.y));
 const cost=new Map([[first,0]]),prev=new Map(),open=new Set([first]);let budget=20000;
 while(open.size&&budget--){let current,score=Infinity;for(const k of open){const p=coords(k),s=cost.get(k)+Math.abs(p.x-end.x)+Math.abs(p.y-end.y);if(s<score){score=s;current=k;}}
  if(current===last){const path=[];let k=last;while(k!==undefined){path.unshift(coords(k));k=prev.get(k);}const compact=path.filter((p,i)=>!i||i===path.length-1||path[i-1].x!==path[i+1].x&&path[i-1].y!==path[i+1].y);return [{x:start.x,y:a.y+a.height},...compact,{x:end.x,y:b.y}];}
  open.delete(current);const x=current%xs.length,y=Math.floor(current/xs.length),p=coords(current);
  for(const [nx,ny] of [[x-1,y],[x+1,y],[x,y-1],[x,y+1]]){if(nx<0||ny<0||nx>=xs.length||ny>=ys.length)continue;const next=key(nx,ny),q=coords(next);if(boxes.some(r=>hits(p,q,r)))continue;const d=cost.get(current)+Math.abs(q.x-p.x)+Math.abs(q.y-p.y)+1;if(d<(cost.get(next)??Infinity)){cost.set(next,d);prev.set(next,current);open.add(next);}}
 }
 throw new Error('正交路由超过预算，请缩小流程范围');
}
function routeAll(projection){const boxes=absolute(projection.nodes),by=new Map(boxes.map(n=>[n.id,n]));return {...projection,edges:projection.edges.map(e=>({...e,sourceHandle:'bottom',targetHandle:'top',route:{sections:[orthogonalRoute(by.get(e.source),by.get(e.target),boxes.filter(n=>!n.container))]}}))};}
export function swimlaneProjection(model,size){
 const lanes=model.nodes.filter(n=>n.role==='lane').sort((a,b)=>(a.order??model.nodes.indexOf(a))-(b.order??model.nodes.indexOf(b)));
 const items=model.nodes.filter(n=>n.role!=='lane'),out=new Map(items.map(n=>[n.id,[]]));model.edges.forEach(e=>out.get(e.source)?.push(e.target));
 const visited=new Set(),active=new Set(),forward=[];
 function visit(id){if(visited.has(id))return;visited.add(id);active.add(id);for(const target of out.get(id)||[]){if(!active.has(target)){forward.push([id,target]);visit(target);}}active.delete(id);}
 items.forEach(n=>visit(n.id));const ranks=new Map(items.map(n=>[n.id,0]));
 for(let i=0;i<items.length;i++){let changed=false;for(const [a,b] of forward)if(ranks.get(b)<=ranks.get(a)){ranks.set(b,ranks.get(a)+1);changed=true;}if(!changed)break;}
 const width=Math.max(270,...model.nodes.map(n=>size(n).width+64)),header=Math.max(...lanes.map(n=>size(n).height))+28;
 const rows=new Map();items.forEach(n=>{const rank=ranks.get(n.id);if(!rows.has(rank))rows.set(rank,[]);rows.get(rank).push(n);});let y=header;const placements=new Map();
 for(const [,row] of [...rows].sort((a,b)=>a[0]-b[0])){let height=0;for(const lane of lanes){let dy=0;for(const n of row.filter(n=>n.parentId===lane.id)){placements.set(n.id,{x:(width-size(n).width)/2,y:y+dy});dy+=size(n).height+30;}height=Math.max(height,dy);}y+=height+65;}
 const nodes=lanes.map((n,i)=>projected(n,{x:i*width,y:0},{width,height:y+30},{container:true,headerHeight:header-28,headerWidth:width}));
 for(const n of items){const s=size(n);nodes.push({...projected(n,placements.get(n.id),s),parentId:n.parentId,extent:'parent'});}
 return routeAll({nodes,edges:model.edges});
}
export function communicationProjection(model,size){
 const order=new Map();for(const e of [...model.edges].sort((a,b)=>a.order-b.order))for(const id of [e.source,e.target])if(!order.has(id))order.set(id,order.size);
 const nodes=[...model.nodes].sort((a,b)=>(order.get(a.id)??1000)-(order.get(b.id)??1000)).map((n,i)=>{const col=i%3,row=Math.floor(i/3);return projected(n,{x:col*360+(row%2?90:0),y:row*250},size(n));});
 return routeAll({nodes,edges:model.edges.map(e=>({...e,communication:true}))});
}
export function timingProjection(model,size){
 const signals=model.nodes.filter(n=>n.role==='signal'),events=model.nodes.filter(n=>n.role==='state-event');
 const values=[...new Set(events.map(n=>model.timeUnit?n.time:n.order))].sort((a,b)=>a-b),max=Math.max(...values),min=Math.min(...values);
 const cell=Math.max(240,...events.map(n=>size(n).width+30));const minGap=values.length>1?Math.min(...values.slice(1).map((v,i)=>v-values[i])):1;
 const span=Math.max(cell*2,(max-min)/minGap*cell);if(span>200000)throw new Error('时间跨度超过画布预算，请缩小时间范围');const x=value=>220+(max===min?0:(value-min)/(max-min)*span);
 const nodes=[];let y=0;for(const signal of signals){const members=events.filter(n=>n.parentId===signal.id),height=Math.max(170,...members.map(n=>size(n).height+80));nodes.push(projected(signal,{x:0,y},{width:span+cell+250,height},{container:true,headerWidth:205,headerHeight:size(signal).height,timing:true}));
  for(const n of members)nodes.push({...projected(n,{x:x(model.timeUnit?n.time:n.order),y:45},size(n)),parentId:signal.id,extent:'parent'});y+=height+40;}
 for(const n of model.nodes.filter(n=>n.role==='note')){nodes.push(projected(n,{x:0,y},size(n)));y+=size(n).height+30;}
 const boxes=absolute(nodes),by=new Map(boxes.map(n=>[n.id,n]));
 const edges=model.edges.map(e=>{const a=by.get(e.source),b=by.get(e.target),start={x:a.x+a.width,y:a.y+a.height/2},end={x:b.x,y:b.y+b.height/2};return {...e,sourceHandle:'right',targetHandle:'left',route:{sections:[[start,{x:(start.x+end.x)/2,y:start.y},{x:(start.x+end.x)/2,y:end.y},end]]}};});
 return {nodes,edges};
}
// Labels are placed once above all edge paths; no later edge can cover text.
export function finishProjection(projection,model,measured={}){
 const boxes=absolute(projection.nodes).filter(n=>!n.container),labels=[],allSegments=projection.edges.flatMap(e=>(e.route?.sections||[]).flatMap(segments).map(s=>({id:e.id,s})));
 return {...projection,edges:projection.edges.map(e=>{const text=[e.guard,e.label,e.communication?String(e.order):''].filter(Boolean).join(' ');if(!text||!e.route?.sections?.length)return e;
  const width=measured.labels?.get(e.id)?.width||Math.min(240,Math.max(50,text.length*8+12)),height=measured.labels?.get(e.id)?.height||32;
  const spans=e.route.sections.flatMap(segments).sort((a,b)=>(Math.abs(b[1].x-b[0].x)+Math.abs(b[1].y-b[0].y))-(Math.abs(a[1].x-a[0].x)+Math.abs(a[1].y-a[0].y)));
  let chosen=null;
  for(const [a,b] of spans){for(const t of [.5,.3,.7]){for(const offset of [0,-height-8,height+8,-2*height-16,2*height+16]){const candidate={x:a.x+(b.x-a.x)*t-width/2+(a.x===b.x?offset:0),y:a.y+(b.y-a.y)*t-height/2+(a.y===b.y?offset:0),width,height};if(!boxes.some(n=>intersects(candidate,n,6))&&!labels.some(n=>intersects(candidate,n,8))&&!allSegments.some(({id,s:[p,q]})=>id!==e.id&&hits(p,q,candidate))){chosen=candidate;break;}}if(chosen)break;}if(chosen)break;}
  if(!chosen){const old=e.route.label;chosen=old?{...old,width,height}:{x:spans[0][0].x,y:spans[0][0].y-height-12,width,height};while(labels.some(n=>intersects(chosen,n,8))||boxes.some(n=>intersects(chosen,n,6)))chosen.y-=height+12;}
  labels.push(chosen);return {...e,route:{...e.route,label:chosen}};
 })};
}

export function compositeProjection(projection){
 const by=new Map(projection.nodes.map(n=>[n.id,n])),counts=new Map();
 for(const n of projection.nodes){if(n.data.node.role!=='port'||!n.parentId)continue;n.extent=undefined;const parent=by.get(n.parentId),side=n.data.node.side||'right',key=n.parentId+side,index=counts.get(key)||0;counts.set(key,index+1);const peers=projection.nodes.filter(p=>p.parentId===n.parentId&&p.data.node.role==='port'&&(p.data.node.side||'right')===side).length;
 const t=(index+1)/(peers+1);n.position={x:side==='left'?-n.width/2:side==='right'?parent.width-n.width/2:parent.width*t-n.width/2,y:side==='top'?-n.height/2:side==='bottom'?parent.height-n.height/2:Math.max(parent.data.headerHeight+20,parent.height*t)-n.height/2};
 }
 return routeAll(projection);
}
