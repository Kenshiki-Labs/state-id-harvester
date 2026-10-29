/* Inspect existing retained crop footprints. Selection never edits their geometry. */
let portraitRegions=null,selectedPortrait=null,portraitOverlay=true;
async function loadPortraitRegions(panel){
 const config=await(await fetch('/portrait-config.json')).json();
 if(!config.available)return;
 const response=await fetch('/portraits/manifest.json');if(!response.ok)throw Error('Portrait package missing');
 const m=await response.json();
 if(m.sourceHashes['front-original.heic']!==boundary.manifest.sourceHashes['front-original.heic'])throw Error('Portrait source mismatch');
 portraitRegions=m;
 const section=document.createElement('section');section.className='tool-group';section.id='portrait-regions';
 const title=document.createElement('h2');title.textContent='Retained portrait regions';section.append(title);
 const note=document.createElement('p');note.textContent=m.interpretation;section.append(note);
 if(!m.candidates.length){const p=document.createElement('p');p.textContent='No retained crop is available. '+m.outcomes.map(o=>o.outcome).join(', ');section.append(p);panel.prepend(section);return}
 const select=document.createElement('select');select.id='portrait-region-select';select.setAttribute('aria-label','Retained portrait region');
 for(const [i,c] of m.candidates.entries()){const option=document.createElement('option');option.value=c.recordID;option.textContent=`${c.role==='printedPortrait'?'Primary printed portrait':`Face region ${i+1}`} · ${c.imagePixelWidth??c.savedDerivativePixelRect.width} × ${c.imagePixelHeight??c.savedDerivativePixelRect.height}`;select.append(option)}
 section.append(select);
 const image=document.createElement('img');image.id='retained-portrait-image';image.alt='Existing portrait crop retained by the SDK';image.style.cssText='display:block;max-width:100%;max-height:260px;object-fit:contain;margin:12px 0';section.append(image);
 const label=document.createElement('label');const toggle=document.createElement('input');toggle.type='checkbox';toggle.id='portrait-footprint-visible';toggle.checked=true;label.append(toggle,document.createTextNode(' Show retained footprint'));section.append(label);
 const button=document.createElement('button');button.textContent='Locate in original';button.id='portrait-locate';section.append(button);
 const facts=document.createElement('div');facts.id='portrait-region-measurements';section.append(facts);
 const download=document.createElement('a');download.href='/portraits/manifest.json';download.textContent='Region geometry, measurements and provenance';download.target='_blank';download.rel='noopener';section.append(download);
 const choose=()=>{selectedPortrait=m.candidates.find(c=>c.recordID===select.value);image.src='/portraits/'+selectedPortrait.image;const v=selectedPortrait.metrics;
 facts.textContent=`${v.uniqueEdgePixelCount.toLocaleString()} unique native edge pixels / ${v.sourcePixelCount.toLocaleString()} source pixels · ${(100*v.edgePixelFraction).toFixed(3)}% edge density. ${v.intersectingChainCount.toLocaleString()} intersecting chains. Interior segment length: ${v.interiorSegmentLengthSourcePixels.toFixed(1)} source px. Directions (source px): ${Object.entries(v.directionLengthsSourcePixels).map(([k,x])=>k.replaceAll('_',' ')+' '+x.toFixed(1)).join(' · ')}. Density uses native pixel centers, independent of display zoom.`;
 views.original.draw();views.rectified.draw();};
 select.onchange=choose;toggle.onchange=()=>{portraitOverlay=toggle.checked;views.original.draw();views.rectified.draw()};
 button.onclick=()=>{const ring=selectedPortrait.sourcePolygon.slice(0,4),point=ring.reduce((p,q)=>[p[0]+q[0]/4,p[1]+q[1]/4],[0,0]);pinned=true;views.original.setPoint(point);views.rectified.setPoint(linked('original',...point));const xs=ring.map(p=>p[0]),ys=ring.map(p=>p[1]);views.original.zoomAtPoint(.8*Math.min(views.original.canvas.width/(Math.max(...xs)-Math.min(...xs)),views.original.canvas.height/(Math.max(...ys)-Math.min(...ys))));status()};
 panel.prepend(section);choose();
}
function drawPortraitRegion(view){
 if(!selectedPortrait||!portraitOverlay)return;
 const ring=selectedPortrait.sourcePolygon.map(p=>view.name==='original'?p:linked('original',...p));
 if(ring.some(p=>!p))return;
 const path=objectPath(view,{geometry:{coordinates:[ring]}});view.ctx.strokeStyle='#fff06a';view.ctx.lineWidth=2;view.ctx.stroke(path);
}
