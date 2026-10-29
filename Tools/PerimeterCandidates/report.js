'use strict';
(async()=>{
  const get=async p=>{const r=await fetch(p);if(!r.ok)throw Error(`${p}: ${r.status}`);return r.json();};
  const [manifest,data,relations]=await Promise.all([get('/perimeter/manifest.json'),get('/perimeter/candidates.json'),get('/perimeter/relationships.json')]);
  const img=new Image();img.src='/original.png';await img.decode();
  const canvas=document.getElementById('map'),ctx=canvas.getContext('2d');
  const candidates=data.candidates,side=document.getElementById('side'),choice=document.getElementById('candidate');
  let scale=1,ox=0,oy=0,drag=null;
  const colors=['#ffbf69','#74d8ff','#da96fa','#87e8a2'];
  function draw(){
    ctx.setTransform(1,0,0,1,0,0);ctx.fillStyle='#0d171b';ctx.fillRect(0,0,canvas.width,canvas.height);
    ctx.setTransform(scale,0,0,scale,ox,oy);ctx.drawImage(img,0,0);ctx.lineWidth=1/scale;
    const selected=choice.value===''?null:Number(choice.value);
    for(const c of candidates){
      if(side.value!=='all'&&c.sideIndex!==Number(side.value))continue;
      if(selected!==null&&c.candidateId!==selected)continue;
      ctx.strokeStyle=colors[c.sideIndex];ctx.fillStyle=colors[c.sideIndex];ctx.beginPath();
      c.points.forEach(([x,y],i)=>i?ctx.lineTo(x+.5,y+.5):ctx.moveTo(x+.5,y+.5));ctx.stroke();
      if(c.points.length===1){const [x,y]=c.points[0];ctx.fillRect(x,y,1,1);}
    }
    document.getElementById('info').textContent=JSON.stringify(selected===null?manifest.summary:candidates.find(c=>c.candidateId===selected)||{error:'Unknown candidate'},null,2);
  }
  function reset(){scale=Math.min(canvas.width/img.width,canvas.height/img.height);ox=(canvas.width-img.width*scale)/2;oy=(canvas.height-img.height*scale)/2;draw();}
  const pos=e=>{const r=canvas.getBoundingClientRect();return [(e.clientX-r.left)*canvas.width/r.width,(e.clientY-r.top)*canvas.height/r.height];};
  canvas.addEventListener('wheel',e=>{e.preventDefault();const [x,y]=pos(e),factor=Math.exp(-e.deltaY*.001);ox=x-(x-ox)*factor;oy=y-(y-oy)*factor;scale*=factor;draw();},{passive:false});
  canvas.addEventListener('pointerdown',e=>{drag=pos(e);canvas.setPointerCapture(e.pointerId);});
  canvas.addEventListener('pointermove',e=>{if(!drag)return;const p=pos(e);ox+=p[0]-drag[0];oy+=p[1]-drag[1];drag=p;draw();});
  canvas.addEventListener('pointerup',()=>drag=null);canvas.addEventListener('pointercancel',()=>drag=null);
  side.onchange=draw;choice.onchange=draw;document.getElementById('reset').onclick=reset;
  document.getElementById('relations').textContent=JSON.stringify(relations.summary,null,2);
  document.getElementById('status').textContent=`${candidates.length.toLocaleString()} discovered runs. No physical perimeter selected.`;reset();
})().catch(e=>{document.getElementById('status').textContent=e.message;console.error(e);});
