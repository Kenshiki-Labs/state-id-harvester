'use strict';
(async()=>{
const fetchJSON=async p=>{const r=await fetch(p);if(!r.ok)throw Error(`Load failed: ${r.status}`);return r.json();};
const data=await fetchJSON('/assembly/assembly.json'),img=new Image();img.src='/original.png';await img.decode();
const canvas=document.getElementById('map'),ctx=canvas.getContext('2d'),select=document.getElementById('path');
const sideNames=['top','right','bottom','left'];
for(const p of data.paths){const o=document.createElement('option');o.value=p.pathId;o.textContent=`Path ${p.pathId} · ${p.lengthSourcePixels.toFixed(1)} px · ${p.closed?'closed':'open'} · ${p.sideIndices.map(i=>sideNames[i]).join(', ')}`;select.append(o);}
let scale=1,ox=0,oy=0,drag=null,appearance=null;
function draw(){
 const p=data.paths[Number(select.value)];ctx.setTransform(1,0,0,1,0,0);ctx.clearRect(0,0,canvas.width,canvas.height);ctx.setTransform(scale,0,0,scale,ox,oy);ctx.imageSmoothingEnabled=false;ctx.drawImage(img,0,0);
 if(!p)return;ctx.lineWidth=2/scale;ctx.strokeStyle='#ffb257';ctx.beginPath();p.points.forEach(([x,y],i)=>i?ctx.lineTo(x+.5,y+.5):ctx.moveTo(x+.5,y+.5));ctx.stroke();
 const nodes=p.nodeIds.map(id=>data.nodes[id]);
 for(const n of nodes){ctx.strokeStyle=n.kind==='open_end'?'#ff6677':'#65d5ff';ctx.beginPath();ctx.arc(n.point[0]+.5,n.point[1]+.5,6/scale,0,Math.PI*2);ctx.stroke();}
 document.getElementById('description').textContent=`${p.points.length.toLocaleString()} retained vertices · ${p.lengthSourcePixels.toFixed(2)} source pixels of observed path. ${p.closed?'Closed geometry.':'Open geometry; no connection is assumed beyond its ends.'} Length order is for browsing, not confidence.`;
 const controls=document.getElementById('branches');controls.replaceChildren();
 for(const n of nodes.filter(n=>n.kind==='branch'))for(const id of n.incidentPathIds.filter(id=>id!==p.pathId)){const b=document.createElement('button');b.textContent=`Branch ${n.nodeId} → path ${id}`;b.onclick=()=>{select.value=id;draw();};controls.append(b);}
 if(appearance)appearance.render(p.pathId);
 document.getElementById('details').textContent=JSON.stringify({pathId:p.pathId,candidateIds:p.candidateIds,componentId:p.componentId,endpoints:nodes},null,2);
}
function reset(){const q=data.prior.corners,pad=data.prior.corridorWidthPixels;const xs=q.map(p=>p[0]),ys=q.map(p=>p[1]),xmin=Math.min(...xs)-pad,xmax=Math.max(...xs)+pad,ymin=Math.min(...ys)-pad,ymax=Math.max(...ys)+pad;scale=Math.min(canvas.width/(xmax-xmin),canvas.height/(ymax-ymin));ox=(canvas.width-(xmax-xmin)*scale)/2-xmin*scale;oy=(canvas.height-(ymax-ymin)*scale)/2-ymin*scale;draw();}
const pos=e=>{const r=canvas.getBoundingClientRect();return[(e.clientX-r.left)*canvas.width/r.width,(e.clientY-r.top)*canvas.height/r.height];};
canvas.onwheel=e=>{e.preventDefault();const [x,y]=pos(e),f=Math.exp(-e.deltaY*.001);ox=x-(x-ox)*f;oy=y-(y-oy)*f;scale*=f;draw();};
canvas.onpointerdown=e=>{drag=pos(e);canvas.setPointerCapture(e.pointerId);};canvas.onpointermove=e=>{if(!drag)return;const p=pos(e);ox+=p[0]-drag[0];oy+=p[1]-drag[1];drag=p;draw();};canvas.onpointerup=()=>drag=null;canvas.onpointercancel=()=>drag=null;
select.onchange=draw;document.getElementById('reset').onclick=reset;
document.getElementById('status').textContent=`${data.summary.pathCount.toLocaleString()} maximal observed paths · ${data.summary.branchCount} branches · ${data.summary.openEndCount.toLocaleString()} open ends · ${data.summary.closedPathCount} closed paths. No physical perimeter selected.`;reset();
 appearance=await window.attachPathAssessment(data,select,draw);if(appearance){if(appearance.initialPathId!==undefined)select.value=appearance.initialPathId;draw();}
})().catch(e=>{document.getElementById('status').textContent=e.message;console.error(e);});
