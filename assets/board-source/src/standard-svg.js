import { umlProjection, edgeText } from './uml-model.js';
import { nodeTitle, nodeMembers } from './notation.js';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&apos;'}[c]));
const wrap=(s,limit)=>{const result=[];for(const line of String(s||'').split('\n')){let chunk='';for(const c of line){chunk+=c;if(chunk.length>=limit){result.push(chunk);chunk='';}}if(chunk)result.push(chunk);}return result;};
function text(s,x,y,width,cls='',anchor='middle') {return wrap(s,Math.max(8,Math.floor(width/8))).map((t,i)=>`<text class="${cls}" x="${x}" y="${y+i*19}" text-anchor="${anchor}" fill="#344763" font-size="13">${esc(t)}</text>`).join('');}
function element(item,body,focus=true){return `<g data-element="${esc(item.id)}" tabindex="${focus?0:-1}" role="${focus?'button':'presentation'}" aria-label="${esc(item.label||item.role)}" class="standard-element"><title>${esc(item.explanation||item.label)}</title>${body}</g>`;}
export function projectionSvg(model,projection){
 const by=new Map(projection.nodes.map(n=>[n.id,n]));
 function box(n){let x=n.position.x,y=n.position.y,p=n.parentId;while(p){const parent=by.get(p);x+=parent.position.x;y+=parent.position.y;p=parent.parentId;}return {x,y,w:n.width,h:n.height};}
 let body='',edgeLayer='',labelLayer='',maxX=0,maxY=0,minX=0,minY=0;
 const include=(x,y,w,h)=>{maxX=Math.max(maxX,x+w);maxY=Math.max(maxY,y+h);minX=Math.min(minX,x);minY=Math.min(minY,y);};
 for(const n of projection.nodes){const b=box(n);include(b.x,b.y,b.w,b.h);}
 for(const e of projection.edges){let sections=e.route?.sections;
  if(!sections){const a=box(by.get(e.source)),b=box(by.get(e.target));sections=[[{x:a.x+a.w/2,y:a.y+a.h},{x:b.x+b.w/2,y:b.y}]];}
  for(const points of sections)for(const p of points)include(p.x,p.y,0,0);
  const uncertain=['candidate','unresolved'].includes(e.status),dash=uncertain||['dependency','package-import','package-merge','return','implementation'].includes(e.role);
  const noArrow=['association','link','connector','assembly','delegation','communication'].includes(e.role),arrow=['inheritance','implementation'].includes(e.role)?'hollow':e.role==='extension'?'filled':'arrow';
  const d=sections.map(points=>points.map((p,i)=>`${i?'L':'M'}${p.x},${p.y}`).join(' ')).join(' ');
  edgeLayer+=element(e,`<path d="${d}" fill="none" stroke="${uncertain?'#b17b26':'#7894b6'}" stroke-width="1.6" ${dash?'stroke-dasharray="6 4"':''} ${noArrow?'':`marker-end="url(#${arrow})"`} ${['composition','aggregation'].includes(e.role)?`marker-start="url(#${e.role})"`:''}/><path d="${d}" fill="none" stroke="transparent" stroke-width="18"/>`,false);
  const label=edgeText(e)||'查看依据',last=sections[0],p=last[Math.floor(last.length/2)],r=e.route?.label||{x:p.x-65,y:p.y-30,width:130,height:28};include(r.x,r.y,r.width,r.height);
  labelLayer+=element(e,`<rect x="${r.x}" y="${r.y}" width="${r.width}" height="${r.height}" rx="4" fill="white" stroke="#e0e7f0"/>${text(label,r.x+r.width/2,r.y+18,r.width-8)}`);
 }
 const parents=projection.nodes.filter(n=>n.data?.container),leaves=projection.nodes.filter(n=>!n.data?.container);
 function node(n){const v=n.data.node,{x,y,w,h}=box(n),role=v.role,cx=x+w/2,cy=y+h/2;let shape='';const base='fill="white" stroke="#91a8ca" stroke-width="1.4"';
  if(role==='start')shape=`<circle cx="${cx}" cy="${cy}" r="12" fill="#243952"/>`;
  else if(role==='end')shape=`<circle cx="${cx}" cy="${cy}" r="14" ${base}/><circle cx="${cx}" cy="${cy}" r="9" fill="#243952"/>`;
  else if(['fork','join'].includes(role))shape=`<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="#243952"/>`;
  else if(['decision','choice','merge'].includes(role))shape=`<polygon points="${cx},${y} ${x+w},${cy} ${cx},${y+h} ${x},${cy}" ${base}/>`;
  else if(role==='actor')shape=`<circle cx="${cx}" cy="${y+13}" r="10" ${base}/><path d="M${cx},${y+23} v35 m-25,-22 h50 m-25,22 l-22,22 m22,-22 l22,22" stroke="#7894b6" fill="none"/>`;
  else if(role==='usecase')shape=`<ellipse cx="${cx}" cy="${cy}" rx="${w/2}" ry="${h/2}" ${base}/>`;
  else if(role==='port')shape=`<rect x="${x}" y="${y+15}" width="18" height="18" ${base}/><path d="M${x+18},${y+24} h22" stroke="#7894b6"/>`+(v.portKind==='required'?`<path d="M${x+50},${y+14} a10,10 0 0,0 0,20" fill="none" stroke="#7894b6"/>`:`<circle cx="${x+50}" cy="${y+24}" r="10" ${base}/>`);
  else if(role==='package'||role==='profile')shape=`<path d="M${x},${y+14} v-14 h${Math.min(w-10,100)} v14 h${w-Math.min(w-10,100)} v${h-14} h-${w} v-${h-14} Z" ${base}/>`;
  else if(['input','output'].includes(role))shape=`<polygon points="${x+18},${y} ${x+w},${y} ${x+w-18},${y+h} ${x},${y+h}" ${base}/>`;
  else if(role==='document')shape=`<path d="M${x},${y} h${w} v${h-12} q-${w/4},-16 -${w/2},0 q-${w/4},16 -${w/2},0 Z" ${base}/>`;
  else if(role==='database')shape=`<path d="M${x},${y+12} a${w/2},12 0 0,1 ${w},0 v${h-24} a${w/2},12 0 0,1 -${w},0 Z" ${base}/><ellipse cx="${cx}" cy="${y+12}" rx="${w/2}" ry="12" ${base}/>`;
  else shape=`<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${role==='state'?12:role==='action'?8:2}" fill="${n.data.container?'#f6f9fd':'white'}" stroke="#91a8ca" ${n.data.container?'stroke-dasharray="5 3"':''}/>`;
  if(role==='interaction')shape+=`<path d="M${x},${y+20} h35 l8,-8 v-12" fill="none" stroke="#91a8ca"/>`+text('ref',x+20,y+14,35);
  const symbolic=['start','end','fork','join','merge'].includes(role);if(!symbolic){const titleY=role==='actor'?y+97:role==='port'?y+h-3:role==='package'||role==='profile'||role==='interaction'?y+34:n.data.container?y+25:y+27;
   if(['stereotype','metaclass','profile','component','structured-class','interaction'].includes(role))shape+=text(`«${role==='structured-class'?'structuredClassifier':role==='interaction'?'interaction':role}»`,cx,titleY-13,w-20);
   shape+=text(nodeTitle(v),n.data.container?x+16:cx,titleY,n.data.container?Math.min(w-30,240):w-20,role==='object'?'object-title':'',n.data.container?'start':'middle');
   const members=nodeMembers(v);if(members.length){const startY=titleY+Math.max(1,Math.ceil(nodeTitle(v).length/Math.max(8,Math.floor((w-20)/8))))*19+8;shape+=`<line x1="${x+8}" x2="${x+w-8}" y1="${startY-8}" y2="${startY-8}" stroke="#bfcee0"/>`;let cursor=startY+10;for(const m of members){shape+=text(m,x+12,cursor,w-24,'','start');cursor+=wrap(m,Math.max(8,Math.floor((w-24)/8))).length*19;}}
  }
  if(role==='signal')shape+=text(model.timeUnit?'时间 / '+model.timeUnit:'逻辑顺序 · 非运行耗时',x+220,y+25,w-240,'','start');
  return element(v,shape);
 }
 body=parents.map(node).join('')+edgeLayer+leaves.map(node).join('')+labelLayer;
 return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${minX-30} ${minY-30} ${maxX-minX+60} ${maxY-minY+60}" width="${maxX-minX+60}" height="${maxY-minY+60}" font-family="system-ui,sans-serif"><style>.object-title{text-decoration:underline}.standard-element{cursor:pointer}.standard-element:focus{outline:none}.standard-element:focus>rect{stroke:#245cff;stroke-width:3}</style><defs><marker id="arrow" markerWidth="10" markerHeight="10" refX="9" refY="5" orient="auto"><path d="M0 0 L9 5 L0 10" fill="none" stroke="#7894b6"/></marker><marker id="hollow" markerWidth="13" markerHeight="12" refX="12" refY="6" orient="auto"><path d="M1 1 L12 6 L1 11 Z" fill="white" stroke="#7894b6"/></marker><marker id="filled" markerWidth="13" markerHeight="12" refX="12" refY="6" orient="auto"><path d="M1 1 L12 6 L1 11 Z" fill="#7894b6"/></marker>${['composition','aggregation'].map(r=>`<marker id="${r}" markerWidth="16" markerHeight="12" refX="1" refY="6" orient="auto-start-reverse"><path d="M1 6 L8 1 L15 6 L8 11 Z" fill="${r==='composition'?'#7894b6':'white'}" stroke="#7894b6"/></marker>`).join('')}</defs>${body}</svg>`;
}
export async function localStandardSvg(model){return projectionSvg(model,await umlProjection(model,'simple'));}
