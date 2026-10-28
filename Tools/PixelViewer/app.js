'use strict';
const views = {}; let geometry, objectLayer, boundary, labelPixels, pinned = false;
let edges=null, selectedEdge=null, boundaryMask=null;
let topology=null, selectedTopology=null;
let rectification=null, activeRectification='saved', savedRectifiedImage;
function project(m, x, y) {
  const d = m[6]*x + m[7]*y + m[8];
  if (!Number.isFinite(d) || Math.abs(d)<1e-12) return null;
  return [(m[0]*x+m[1]*y+m[2])/d,(m[3]*x+m[4]*y+m[5])/d];
}
function linked(name, x, y) {
  if(activeRectification==='boundary')return project(rectification.manifest.transforms[name==='rectified'?'rectifiedToSource':'sourceToRectified'],x,y);
  if(name==='rectified') return project(geometry.cardMillimetersToSource,x/geometry.outputPixelsPerMillimeter,y/geometry.outputPixelsPerMillimeter);
  const p=project(geometry.sourceToCardMillimeters,x,y);
  return p && p.map(v=>v*geometry.outputPixelsPerMillimeter);
}
class View {
  constructor(name,img){
    this.name=name;this.img=img;this.el=document.getElementById(name);this.canvas=this.el.querySelector('canvas');this.ctx=this.canvas.getContext('2d');
    this.raster=document.createElement('canvas');this.raster.width=img.width;this.raster.height=img.height;
    this.pixels=this.raster.getContext('2d',{willReadFrequently:true,colorSpace:'srgb'});this.pixels.drawImage(img,0,0);
    this.point=null;this.scale=1;this.tx=0;this.ty=0;
    new ResizeObserver(()=>{this.canvas.width=this.canvas.clientWidth;this.canvas.height=this.canvas.clientHeight;this.fit()}).observe(this.canvas);
    this.el.querySelectorAll('button').forEach(b=>b.onclick=()=>{if(b.dataset.action==='fit')this.fit();else this.zoomAtPoint(b.dataset.action==='one'?1:24)});
    this.canvas.onwheel=e=>{e.preventDefault();const [x,y]=this.local(e);this.zoom(this.scale*Math.exp(-e.deltaY*.002),x,y)};
    this.canvas.onpointerdown=e=>{this.drag={x:e.clientX,y:e.clientY,tx:this.tx,ty:this.ty,moved:false};this.canvas.setPointerCapture(e.pointerId)};
    this.canvas.onpointermove=e=>{if(this.drag){const dx=e.clientX-this.drag.x,dy=e.clientY-this.drag.y;if(Math.hypot(dx,dy)>3)this.drag.moved=true;this.tx=this.drag.tx+dx;this.ty=this.drag.ty+dy;this.draw()}else if(!pinned)this.inspect(e)};
    this.canvas.onpointerup=e=>{if(this.drag&&!this.drag.moved){pinned=false;this.inspect(e);pinned=true;if(this.name==='original'&&this.point){selectAt(this.point);selectEdgeAt(this.point);selectTopologyAt(this.point)};status()}this.drag=null;this.canvas.releasePointerCapture(e.pointerId)};
    this.canvas.onpointercancel=()=>this.drag=null;
    this.canvas.onkeydown=e=>{if(['+','=','-','ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key)){e.preventDefault();if(e.key==='-'||e.key==='+'||e.key==='=')this.zoomAtPoint(this.scale*(e.key==='-'?.5:2));else{this.tx+=e.key==='ArrowLeft'?40:e.key==='ArrowRight'?-40:0;this.ty+=e.key==='ArrowUp'?40:e.key==='ArrowDown'?-40:0;this.draw()}}};
  }
  replaceImage(img){this.img=img;this.raster.width=img.width;this.raster.height=img.height;this.pixels.drawImage(img,0,0);this.fit()}
  local(e){const r=this.canvas.getBoundingClientRect();return[e.clientX-r.left,e.clientY-r.top]}
  fit(){this.scale=Math.min(this.canvas.width/this.img.width,this.canvas.height/this.img.height)*.94;this.tx=(this.canvas.width-this.img.width*this.scale)/2;this.ty=(this.canvas.height-this.img.height*this.scale)/2;this.draw()}
  zoom(s,x,y){s=Math.max(.025,Math.min(64,s));const ix=(x-this.tx)/this.scale,iy=(y-this.ty)/this.scale;this.scale=s;this.tx=x-ix*s;this.ty=y-iy*s;this.draw()}
  zoomAtPoint(s){const p=this.point||[this.img.width/2,this.img.height/2];this.scale=Math.max(.025,Math.min(64,s));this.tx=this.canvas.width/2-p[0]*this.scale;this.ty=this.canvas.height/2-p[1]*this.scale;this.draw()}
  inspect(e){if(!views.original||!views.rectified)return;const p=this.local(e);const x=Math.floor((p[0]-this.tx)/this.scale)+.5,y=Math.floor((p[1]-this.ty)/this.scale)+.5;this.setPoint([x,y]);const other=views[this.name==='original'?'rectified':'original'];other.setPoint(linked(this.name,x,y))}
  setPoint(p){this.point=p;const output=this.el.querySelector('output');if(!p||p[0]<0||p[1]<0||p[0]>=this.img.width||p[1]>=this.img.height){output.textContent='Outside this image — no pixel sample.';this.draw();return}
    const [x,y]=p,ix=Math.floor(x),iy=Math.floor(y),rgb=this.pixels.getImageData(ix,iy,1,1).data;
    const hex='#'+Array.from(rgb).slice(0,3).map(v=>v.toString(16).padStart(2,'0')).join('').toUpperCase();
    output.textContent=`Pixel [${ix}, ${iy}] · RGB ${rgb[0]}, ${rgb[1]}, ${rgb[2]} · ${hex}\nMapped position (${x.toFixed(3)}, ${y.toFixed(3)}) px`;
    output.style.whiteSpace='pre-line';if(this.name==='rectified'){const o=activeRectification==='boundary'?rectification.manifest.output:{pixelsPerMillimeter:geometry.outputPixelsPerMillimeter,originCardMillimeters:[0,0]};const cx=x/o.pixelsPerMillimeter+o.originCardMillimeters[0],cy=y/o.pixelsPerMillimeter+o.originCardMillimeters[1];output.textContent+=`\nNominal card (${cx.toFixed(3)}, ${cy.toFixed(3)}) mm · GIS (${cx.toFixed(3)}, ${(-cy).toFixed(3)}) mm`;}
    if(typeof workingSample==='function')output.textContent+=workingSample(this,x,y);
    this.draw();
  }
  draw(){const c=this.ctx;c.clearRect(0,0,this.canvas.width,this.canvas.height);c.imageSmoothingEnabled=this.scale<1;c.drawImage(this.img,this.tx,this.ty,this.img.width*this.scale,this.img.height*this.scale);
    if(this.name==='original'){drawObjects(this);drawEdges(this);drawTopology(this)}
    if(this.name==='rectified')drawMeasurements(this);
    if(this.name==='rectified'&&activeRectification==='boundary'&&document.getElementById('rectified-contour').checked){c.strokeStyle='#ff914d';c.lineWidth=2;c.stroke(objectPath(this,{geometry:rectification.contour}))}
    if(typeof drawWorkingArea==='function')drawWorkingArea(this);
    if(typeof drawPortraitRegion==='function')drawPortraitRegion(this);
    if(this.point){const x=this.tx+this.point[0]*this.scale,y=this.ty+this.point[1]*this.scale;c.strokeStyle='#ffdb66';c.lineWidth=1.5;c.beginPath();c.moveTo(x-13,y);c.lineTo(x+13,y);c.moveTo(x,y-13);c.lineTo(x,y+13);c.stroke();c.strokeRect(this.tx+Math.floor(this.point[0])*this.scale,this.ty+Math.floor(this.point[1])*this.scale,this.scale,this.scale)}
    this.el.querySelector('.zoom').textContent=`${Math.round(this.scale*100)}%`;
  }
}

function objectPath(view, object){
  const path=new Path2D();
  for(const ring of object.geometry.coordinates){ring.forEach(([x,y],i)=>{if(i===0)path.moveTo(view.tx+x*view.scale,view.ty+y*view.scale);else path.lineTo(view.tx+x*view.scale,view.ty+y*view.scale)});path.closePath()}
  return path;
}
function drawObjects(view){
  if(!objectLayer)return;
  const ctx=view.ctx;
  if(boundary&&document.getElementById('boundary-visible').checked){const path=objectPath(view,{geometry:boundary.geometry});ctx.strokeStyle='#ff914d';ctx.lineWidth=2;ctx.stroke(path)}
  for(const object of objectLayer.objects){
    const path=objectPath(view,object);
    if(document.getElementById('highlight-'+object.id).checked){ctx.fillStyle=object.id==='card'?'rgba(40,230,185,.22)':'rgba(150,140,255,.22)';ctx.fill(path,'evenodd')}
  }
}
function selectObject(id){
  if(!objectLayer)return;
  const o=objectLayer.objects.find(o=>o.id===id);
  document.getElementById('object-details').textContent=o?`${o.id} · parent: ${o.parentId} · ${o.geometry.type} · area: ${o.areaSquarePixels.toLocaleString(undefined,{maximumFractionDigits:2})} px² · assigned pixels: ${o.pixelCount.toLocaleString()} · bounds: ${o.bounds.map(v=>v.toFixed(2)).join(', ')} · adjacent: ${o.adjacentIds.join(', ')} · boundary: ${o.boundaryStatus}`:'Outside scene';
  for(const buttonId of ['card','surroundings'])document.getElementById('select-'+buttonId).setAttribute('aria-pressed',String(buttonId===id));
}
function selectAt([x,y]){
  const cs=objectLayer.coordinateSystem;
  if(x<0||y<0||x>=cs.width||y>=cs.height){selectObject(null);return}
  const label=labelPixels.getImageData(Math.floor(x),Math.floor(y),1,1).data[0];
  selectObject(objectLayer.objects.find(o=>o.label===label)?.id);
}
for(const id of ['highlight-card','highlight-surroundings','boundary-visible'])document.getElementById(id).onchange=()=>views.original?.draw();
for(const id of ['card','surroundings'])document.getElementById('select-'+id).onclick=()=>selectObject(id);

function clearBoundary(message){
  boundary=null;boundaryMask=null;
  const toggle=document.getElementById('boundary-visible');
  toggle.checked=false;toggle.disabled=true;
  document.getElementById('boundary-status').textContent=message;
  views.original?.draw();
}
const equalValues=(a,b)=>Array.isArray(a)&&a.length===b.length&&a.every((v,i)=>v===b[i]);
const isSHA256=value=>typeof value==='string'&&/^[a-f0-9]{64}$/.test(value);
async function sha256(bytes){
  return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))).map(b=>b.toString(16).padStart(2,'0')).join('');
}
function validateBoundaryManifest(value,m){
  const f=value.fidelity,p=value.parameters,cs=value.coordinateSystem;
  const size=[geometry.sourcePixelWidth,geometry.sourcePixelHeight];
  if(value.schemaVersion!==1||value.type!=='id_cadastral_boundary'||!isSHA256(value.boundaryId))throw Error('Boundary dataset schema mismatch');
  if(value.sourceHashes?.['front-original.heic']!==m.derivation.sourceSHA256||value.sourceHashes?.['browser-viewer/original.png']!==m.viewerDerivation.outputSHA256)throw Error('Boundary lineage mismatch');
  if(!f||f.workingExtent!=='full_frame'||f.resampled!==false||f.cropped!==false||
     !equalValues(f.sourceSize,size)||!equalValues(f.workingSize,size)||!equalValues(f.workingToSourceAffine,[1,0,0,0,1,0])||
     f.sourcePixelsAdmitted!==size[0]*size[1]||f.bgrRoundTripEqual!==true||
     !isSHA256(f.sourceRGBSHA256)||f.sourceRGBSHA256!==f.workingRGBSHA256||
     p?.workingResolution!=='native'||p.workingExtent!=='full_frame'||p.resampling!=='none')throw Error('Boundary native full-frame fidelity mismatch');
  if(cs?.type!=='image_pixels'||cs.origin!=='top_left_edge'||cs.xDirection!=='right'||cs.yDirection!=='down'||cs.width!==size[0]||cs.height!==size[1])throw Error('Boundary coordinate mismatch');
  if(value.verification?.polygonMaskRoundTrip!==true||value.verification?.geometryUnchanged!==true||!isSHA256(value.provenance?.candidateSHA256))throw Error('Boundary verification missing');
  for(const name of ['geometry','mask','assessments']){
    const artifact=value.artifacts?.[name];
    if(artifact?.path!==name+(name==='mask'?'.png':'.json')||!isSHA256(artifact.sha256))throw Error('Boundary artifact manifest invalid: '+name);
  }
  if(value.boundaryId!==value.artifacts.geometry.sha256)throw Error('Boundary identity mismatch');
}
function validateBoundaryGeometry(value,manifest){
  const rings=value?.coordinates,cs=manifest.coordinateSystem;
  if(value?.type!=='Polygon'||!Array.isArray(rings)||!rings.length||!rings.every(r=>Array.isArray(r)&&r.length>=4&&r.every(v=>Array.isArray(v)&&v.length===2&&v.every(Number.isFinite)&&v[0]>=0&&v[0]<=cs.width&&v[1]>=0&&v[1]<=cs.height)&&equalValues(r[0],r[r.length-1])))throw Error('Boundary polygon invalid');
  if(!Array.isArray(manifest.rings)||manifest.rings.length!==rings.length||!manifest.rings.every((ring,index)=>typeof ring.ringId==='string'&&ring.ringId.length>0&&ring.ringIndex===index&&ring.role===(index===0?'exterior':'interior')&&Number.isFinite(ring.lengthSourcePixels)&&ring.lengthSourcePixels>0)||new Set(manifest.rings.map(r=>r.ringId)).size!==rings.length)throw Error('Boundary ring metadata invalid');
  for(const [index,ring] of rings.entries()){
    let length=0;
    for(let i=1;i<ring.length;i++)length+=Math.hypot(ring[i][0]-ring[i-1][0],ring[i][1]-ring[i-1][1]);
    if(Math.abs(length-manifest.rings[index].lengthSourcePixels)>1e-9*Math.max(1,length))throw Error('Boundary ring length mismatch');
  }
}
async function loadBoundary(m){
  clearBoundary('Boundary dataset loading');
  try{
    const response=await fetch('/boundary-manifest.json');
    if(!response.ok)throw Error('Boundary manifest unavailable');
    const manifest=await response.json();
    validateBoundaryManifest(manifest,m);
    const entries=await Promise.all(['geometry','mask','assessments'].map(async name=>{
      const response=await fetch('/boundary-'+name+(name==='mask'?'.png':'.json'));
      if(!response.ok)throw Error('Boundary artifact unavailable: '+name);
      const bytes=await response.arrayBuffer();
      if(await sha256(bytes)!==manifest.artifacts[name].sha256)throw Error('Boundary artifact hash mismatch: '+name);
      return [name,bytes];
    }));
    const artifacts=Object.fromEntries(entries);
    const polygon=JSON.parse(new TextDecoder().decode(artifacts.geometry));
    const assessments=JSON.parse(new TextDecoder().decode(artifacts.assessments));
    validateBoundaryGeometry(polygon,manifest);
    if(assessments.schemaVersion!==1||assessments.boundaryId!==manifest.boundaryId||!Array.isArray(assessments.findings)||assessments.findings.length!==0)throw Error('Boundary assessments mismatch');
    boundary={manifest,geometry:polygon,assessments};
    const maskImage=await createImageBitmap(new Blob([artifacts.mask],{type:'image/png'}));
    try{
      if(maskImage.width!==geometry.sourcePixelWidth||maskImage.height!==geometry.sourcePixelHeight)throw Error('Boundary mask size mismatch');
      const canvas=document.createElement('canvas');canvas.width=maskImage.width;canvas.height=maskImage.height;
      const context=canvas.getContext('2d',{willReadFrequently:true});context.drawImage(maskImage,0,0);
      boundaryMask={width:canvas.width,height:canvas.height,pixels:context.getImageData(0,0,canvas.width,canvas.height).data};
    }finally{maskImage.close()}
    const toggle=document.getElementById('boundary-visible');toggle.disabled=false;toggle.checked=false;
    const findingsStatus=assessments.findings.length?`${assessments.findings.length.toLocaleString()} recorded findings`:'Unassessed · 0 recorded findings';
    const contacts=manifest.diagnostics?.seedBoundaryContactSamples;
    const seedStatus=Number.isInteger(contacts)&&contacts>=0?` · ${contacts.toLocaleString()} seed-boundary contacts`:'';
    document.getElementById('boundary-status').textContent=`Dataset v${manifest.schemaVersion} · ${manifest.fidelity.sourcePixelsAdmitted.toLocaleString()} native pixels · ${findingsStatus}${seedStatus}`;
  }catch(e){clearBoundary('Boundary unavailable: '+e.message)}
}


async function loadRectification(){
  const response=await fetch('/viewer-config.json');
  if(!response.ok)throw Error('Viewer configuration unavailable');
  const config=await response.json();
  if(typeof config.rectificationAvailable!=='boolean')throw Error('Viewer configuration invalid');
  if(!config.rectificationAvailable)return;
  if(!boundary)throw Error('Rectification requires verified boundary');
  const r=await fetch('/rectification-manifest.json');if(!r.ok)throw Error('Rectification manifest unavailable');
  const manifest=await r.json();
  if(manifest.schemaVersion!==1||manifest.type!=='id_cadastral_rectification'||manifest.boundaryId!==boundary.manifest.boundaryId||JSON.stringify(Object.entries(manifest.sourceHashes).sort())!==JSON.stringify(Object.entries(boundary.manifest.sourceHashes).sort()))throw Error('Rectification lineage mismatch');
  const loaded={};
  for(const [name,route] of [['image','rectified.png'],['contour','contour.json']]){
    if(manifest.artifacts[name].path!==route)throw Error('Rectification artifact path invalid');
    const r=await fetch('/rectification-'+route);if(!r.ok)throw Error('Rectification artifact unavailable');
    const bytes=await r.arrayBuffer();if(await sha256(bytes)!==manifest.artifacts[name].sha256)throw Error('Rectification artifact hash mismatch');loaded[name]=bytes;
  }
  const img=new Image();img.src='/rectification-rectified.png';await img.decode();
  if(img.width!==manifest.output.width||img.height!==manifest.output.height)throw Error('Rectification dimensions mismatch');
  rectification={manifest,img,contour:JSON.parse(new TextDecoder().decode(loaded.contour))};
  const selector=document.getElementById('rectification-version');selector.add(new Option('Boundary rectification','boundary'));selector.disabled=false;
  selector.onchange=()=>switchRectification(selector.value);
  document.getElementById('rectified-contour').onchange=()=>views.rectified.draw();
  document.getElementById('rectification-dataset').hidden=false;
  document.getElementById('rectification-facts').textContent=`${img.width.toLocaleString()} × ${img.height.toLocaleString()} pixels · ${manifest.output.pixelsPerMillimeter} pixels/mm · source boundary ${manifest.boundaryId.slice(0,12)}`;
  document.getElementById('rectification-json').textContent=JSON.stringify(manifest,null,2);
}
function switchRectification(version){
  if(!['saved','boundary'].includes(version)||version==='boundary'&&!rectification)throw Error('Rectification version unavailable');
  activeRectification=version;
  const view=views.rectified,sourcePoint=views.original.point;
  view.replaceImage(version==='boundary'?rectification.img:savedRectifiedImage);
  const toggle=document.getElementById('rectified-contour');toggle.disabled=version!=='boundary';
  document.getElementById('rectified-title').textContent=version==='boundary'?'Boundary rectification':'Saved rectification';
  view.canvas?.setAttribute('aria-label',version==='boundary'?'Boundary rectification pixel inspector':'Saved rectification pixel inspector');
  view.setPoint(sourcePoint?linked('original',...sourcePoint):null);
}

// This reader accepts only the two numeric NPY layouts in edge dataset v1.
function readEdgeNpy(buffer, descriptor, columns){
  const bytes=new Uint8Array(buffer), view=new DataView(buffer);
  if(bytes.length<10||bytes[0]!==147||String.fromCharCode(...bytes.slice(1,6))!=='NUMPY'||bytes[6]!==1||bytes[7]!==0)throw Error('Unsupported edge array format');
  const start=10+view.getUint16(8,true);
  if(start>bytes.length)throw Error('Truncated edge array header');
  const header=new TextDecoder().decode(bytes.slice(10,start));
  const match=header.match(/^\{'descr': '(<i[48])', 'fortran_order': False, 'shape': \((\d+),(?: (\d+))?\), \}\s*$/);
  if(!match||match[1]!==descriptor||(columns===2?match[3]!=='2':match[3]!==undefined))throw Error('Unsupported edge array layout');
  const count=Number(match[2])*columns, size=descriptor==='<i4'?4:8;
  if(!Number.isSafeInteger(count)||start+count*size!==bytes.length)throw Error('Edge array size mismatch');
  if(descriptor==='<i4')return new Int32Array(buffer,start,count);
  const result=new Float64Array(count);
  for(let i=0;i<count;i++){const value=view.getBigInt64(start+i*8,true);if(value<0n||value>BigInt(Number.MAX_SAFE_INTEGER))throw Error('Unsafe edge offset');result[i]=Number(value)}
  return result;
}
function edgeColor(x,y){
  if(!boundaryMask)throw Error('Verified boundary mask required for edge colors');
  const ix=Math.floor(x),iy=Math.floor(y);
  return ix>=0&&iy>=0&&ix<boundaryMask.width&&iy<boundaryMask.height&&boundaryMask.pixels[(iy*boundaryMask.width+ix)*4]>0?'#e977f0':'#65bfff';
}
function drawEdges(view){
  if(!edges||!document.getElementById('edges-visible').checked)return;
  const c=view.ctx;
  for(let i=0;i<edges.chains.length;i++){
    const start=edges.offsets[i],end=edges.offsets[i+1],selected=i===selectedEdge;
    c.lineWidth=selected?2:1;
    if(end-start===1){
      const x=edges.points[start*2]+.5,y=edges.points[start*2+1]+.5;
      c.fillStyle=selected?'#ffdb66':edgeColor(x,y);c.beginPath();c.arc(view.tx+x*view.scale,view.ty+y*view.scale,c.lineWidth/2,0,2*Math.PI);c.fill();
    }
    let currentColor=null;
    for(let j=start+1;j<end;j++){
      const x0=edges.points[(j-1)*2]+.5,y0=edges.points[(j-1)*2+1]+.5,x1=edges.points[j*2]+.5,y1=edges.points[j*2+1]+.5;
      const color=selected?'#ffdb66':edgeColor((x0+x1)/2,(y0+y1)/2);
      // Split stroke color only; the shared endpoint and every segment survive.
      if(color!==currentColor){if(currentColor!==null)c.stroke();currentColor=color;c.strokeStyle=color;c.beginPath();c.moveTo(view.tx+x0*view.scale,view.ty+y0*view.scale)}
      c.lineTo(view.tx+x1*view.scale,view.ty+y1*view.scale);
    }
    if(currentColor!==null)c.stroke();
  }
}
function selectEdgeAt(point){
  if(!edges||!document.getElementById('edges-visible').checked)return;
  let best=null,nearest=null,distance=8/views.original.scale;
  // Test every retained point; tolerance is a display hit target, not geometry.
  for(let i=0;i<edges.chains.length;i++)for(let j=edges.offsets[i];j<edges.offsets[i+1];j++){
    const d=Math.hypot(edges.points[j*2]+.5-point[0],edges.points[j*2+1]+.5-point[1]);
    if(d<distance){best=i;nearest=j;distance=d}
  }
  selectedEdge=best;
  const chain=best===null?null:edges.chains[best];
  document.getElementById('edge-details').textContent=chain?`${chain.chainId} · ${chain.pointCount.toLocaleString()} points · length ${chain.lengthSourcePixels.toFixed(2)} source px · bounds [${chain.bounds.minX}, ${chain.bounds.minY}]–[${chain.bounds.maxX}, ${chain.bounds.maxY}] · nearest pixel [${edges.points[nearest*2]}, ${edges.points[nearest*2+1]}]`:'No chain within 8 display pixels.';
  views.original.draw();
}
function visitEdgeDiagnostic(point,scale){
  pinned=true;views.original.setPoint(point);views.original.zoomAtPoint(scale);
  views.rectified.setPoint(linked('original',...point));status();
  views.original.canvas.scrollIntoView({block:'center'});
}
async function loadEdges(m){
  const response=await fetch('/viewer-config.json');if(!response.ok)throw Error('Viewer configuration unavailable');
  const config=await response.json();if(!config.edgesAvailable)return;
  document.getElementById('edges-panel').hidden=false;
  try{
    if(!boundaryMask)throw Error('Verified boundary mask required for edge colors');
    const response=await fetch('/edges-manifest.json');if(!response.ok)throw Error('Edge manifest unavailable');
    const manifest=await response.json(),cs=manifest.coordinateSystem;
    if(manifest.schemaVersion!==1||manifest.type!=='id_cadastral_edge_candidates'||manifest.sourceHashes?.['front-original.heic']!==m.derivation.sourceSHA256||manifest.sourceHashes?.['browser-viewer/original.png']!==m.viewerDerivation.outputSHA256)throw Error('Edge source lineage mismatch');
    if(cs?.type!=='image_pixel_indices'||cs.origin!=='top_left'||cs.xDirection!=='right'||cs.yDirection!=='down'||cs.width!==geometry.sourcePixelWidth||cs.height!==geometry.sourcePixelHeight||!equalValues(cs.pixelCenterOffset,[.5,.5]))throw Error('Edge coordinates invalid');
    const data={};
    for(const name of ['points.npy','offsets.npy','chains.json']){
      const response=await fetch('/edges-'+name);if(!response.ok)throw Error('Edge artifact unavailable: '+name);
      const bytes=await response.arrayBuffer();
      if(bytes.byteLength!==manifest.artifacts[name].bytes||await sha256(bytes)!==manifest.artifacts[name].sha256)throw Error('Edge artifact mismatch: '+name);
      data[name]=bytes;
    }
    const points=readEdgeNpy(data['points.npy'],'<i4',2),offsets=readEdgeNpy(data['offsets.npy'],'<i8',1),chains=JSON.parse(new TextDecoder().decode(data['chains.json']));
    if(!Array.isArray(chains)||offsets.length!==chains.length+1||offsets[0]!==0||offsets[offsets.length-1]!==points.length/2)throw Error('Edge chain offsets invalid');
    for(let i=0;i<chains.length;i++)if(offsets[i+1]<=offsets[i]||chains[i].chainId!=='edge-'+i||chains[i].pointCount!==offsets[i+1]-offsets[i])throw Error('Edge chain metadata invalid');
    for(let i=0;i<points.length;i+=2)if(points[i]<0||points[i]>=cs.width||points[i+1]<0||points[i+1]>=cs.height)throw Error('Edge point outside source');
    edges={manifest,points,offsets,chains};
    const toggle=document.getElementById('edges-visible');toggle.disabled=false;toggle.checked=false;toggle.onchange=()=>views.original.draw();
    document.getElementById('edges-status').textContent=`${chains.length.toLocaleString()} chains · ${(points.length/2).toLocaleString()} retained points · candidate transitions`;
    // Display bookmarks for the already registered baseline diagnostics only.
    if(m.derivation.sourceSHA256==='e1ac9a9636ffcce144b7b01b891f63586624d402fed4d33ef37505174bff45fe'){
      for(const [id,point,scale] of [['left',[570,4100],1],['bottom',[2400,4750],2]]){
        const button=document.getElementById('edges-'+id);button.disabled=false;button.onclick=()=>visitEdgeDiagnostic(point,scale);
      }
    }
    views.original.draw();
  }catch(error){edges=null;document.getElementById('edges-status').textContent='Edge candidates unavailable: '+error.message;throw error}
}

function readTopologyNpy(buffer){
  const bytes=new Uint8Array(buffer),v=new DataView(buffer);
  if(bytes.length<10||bytes[0]!==147||String.fromCharCode(...bytes.slice(1,6))!=='NUMPY'||bytes[6]!==1||bytes[7]!==0)throw Error('Topology array format invalid');
  const start=10+v.getUint16(8,true),header=new TextDecoder().decode(bytes.slice(10,start));
  const match=header.match(/^\{'descr': '(<[if][48])', 'fortran_order': False, 'shape': \((\d+),(?: (\d+))?\), \}\s*$/);
  if(!match)throw Error('Topology array layout invalid');
  const columns=match[3]?Number(match[3]):1,count=Number(match[2])*columns,size=Number(match[1].slice(-1));
  if(!Number.isSafeInteger(count)||start+count*size!==bytes.length)throw Error('Topology array size invalid');
  const data=new Float64Array(count);
  for(let i=0;i<count;i++){
    const at=start+i*size,value=match[1]==='<f8'?v.getFloat64(at,true):match[1]==='<i4'?v.getInt32(at,true):match[1]==='<i8'?Number(v.getBigInt64(at,true)):NaN;
    if(!Number.isFinite(value)||(match[1][1]==='i'&&!Number.isSafeInteger(value)))throw Error('Topology numeric value invalid');data[i]=value;
  }
  return {data,rows:Number(match[2]),columns};
}
function topologyMode(){return document.getElementById('topology-mode').value}
function drawTopology(view){
  if(!topology)return;
  const mode=topologyMode(),c=view.ctx,a=topology.arrays;
  if(mode==='off')return;
  c.strokeStyle='#ffe082';c.fillStyle='#ffe082';c.lineWidth=2;
  if(mode==='endpoints'||mode==='junctions'){
    for(let i=0;i<a.degrees.length;i++)if(mode==='endpoints'?a.degrees[i]===1:a.degrees[i]>2){
      c.beginPath();c.arc(view.tx+(a.nodes[2*i]+.5)*view.scale,view.ty+(a.nodes[2*i+1]+.5)*view.scale,selectedTopology===i?5:2,0,2*Math.PI);c.fill();
    }
  }else if(selectedTopology!==null&&mode==='component'){
    for(let i=0;i<a.path_components.length;i++)if(a.path_components[i]===selectedTopology){
      c.beginPath();for(let j=a.path_offsets[i];j<a.path_offsets[i+1];j++){
        const x=view.tx+(a.path_points[2*j]+.5)*view.scale,y=view.ty+(a.path_points[2*j+1]+.5)*view.scale;
        if(j===a.path_offsets[i])c.moveTo(x,y);else c.lineTo(x,y);
      }c.stroke();
    }
    for(let i=0;i<a.degrees.length;i++)if(a.degrees[i]===0&&a.node_components[i]===selectedTopology){c.beginPath();c.arc(view.tx+(a.nodes[i*2]+.5)*view.scale,view.ty+(a.nodes[i*2+1]+.5)*view.scale,3,0,2*Math.PI);c.fill()}
  }else if(selectedTopology!==null&&mode==='region'){
    const feature=topology.regions.features.find(f=>f.properties.regionId===selectedTopology);
    if(feature)for(const ring of feature.geometry.coordinates){c.beginPath();ring.forEach(([x,y],i)=>{x=view.tx+(x+.5)*view.scale;y=view.ty+(y+.5)*view.scale;if(i===0)c.moveTo(x,y);else c.lineTo(x,y)});c.stroke()}
  }
}
function chooseTopology(id,center=false){
  const mode=topologyMode(),a=topology.arrays;let point=null,details;
  if(mode==='component'){
    const indices=[];for(let i=0;i<a.path_components.length;i++)if(a.path_components[i]===id)indices.push(i);
    const isolated=[];for(let i=0;i<a.degrees.length;i++)if(a.degrees[i]===0&&a.node_components[i]===id)isolated.push(i);
    if(!indices.length&&!isolated.length)throw Error('Component ID not present');
    let count=0;for(const i of indices)count+=a.path_offsets[i+1]-a.path_offsets[i];
    if(indices.length){const j=a.path_offsets[indices[0]];point=[a.path_points[j*2]+.5,a.path_points[j*2+1]+.5]}else{const j=isolated[0];point=[a.nodes[j*2]+.5,a.nodes[j*2+1]+.5]}
    details=`Component ${id} · ${indices.length.toLocaleString()} paths · ${count.toLocaleString()} retained path vertices · ${isolated.length} isolated nodes`;
  }else if(mode==='region'){
    const feature=topology.regions.features.find(f=>f.properties.regionId===id);if(!feature)throw Error('Enclosed face ID not present');
    point=feature.geometry.coordinates[0][0].map(v=>v+.5);details=`Enclosed face ${id} · ${JSON.stringify(feature.properties)} · geometric enclosure; material role unassigned`;
  }else{
    if(!Number.isInteger(id)||id<0||id>=a.degrees.length||(mode==='endpoints'?a.degrees[id]!==1:a.degrees[id]<=2))throw Error('Node ID not present in this layer');
    point=[a.nodes[id*2]+.5,a.nodes[id*2+1]+.5];details=`Node ${id} · degree ${a.degrees[id]} · component ${a.node_components[id]} · source center (${point.join(', ')})`;
  }
  selectedTopology=id;document.getElementById('topology-id').value=id;document.getElementById('topology-details').textContent=details;
  if(center)visitEdgeDiagnostic(point,views.original.scale);else views.original.draw();
}
function selectTopologyAt(point){
  if(!topology||topologyMode()==='off')return;
  const a=topology.arrays,mode=topologyMode();let best=null,distance=8/views.original.scale;
  if(mode==='region'){
    function inRing(ring){let inside=false;for(let i=0,j=ring.length-1;i<ring.length;j=i++){const x=point[0]-.5,y=point[1]-.5,[xi,yi]=ring[i],[xj,yj]=ring[j];if((yi>y)!==(yj>y)&&x<(xj-xi)*(y-yi)/(yj-yi)+xi)inside=!inside}return inside}
    for(const f of topology.regions.features)if(inRing(f.geometry.coordinates[0])&&!f.geometry.coordinates.slice(1).some(inRing)){best=f.properties.regionId;break}
  }else if(mode==='component'){
    for(let i=0;i<a.path_components.length;i++)for(let j=a.path_offsets[i];j<a.path_offsets[i+1];j++){
      const d=Math.hypot(a.path_points[j*2]+.5-point[0],a.path_points[j*2+1]+.5-point[1]);if(d<distance){distance=d;best=a.path_components[i]}
    }
    for(let i=0;i<a.degrees.length;i++)if(a.degrees[i]===0){const d=Math.hypot(a.nodes[i*2]+.5-point[0],a.nodes[i*2+1]+.5-point[1]);if(d<distance){distance=d;best=a.node_components[i]}}
  }else for(let i=0;i<a.degrees.length;i++)if(mode==='endpoints'?a.degrees[i]===1:a.degrees[i]>2){
    const d=Math.hypot(a.nodes[i*2]+.5-point[0],a.nodes[i*2+1]+.5-point[1]);if(d<distance){distance=d;best=i}
  }
  if(best!==null)chooseTopology(best);else{selectedTopology=null;document.getElementById('topology-details').textContent='No topology feature at this point.';views.original.draw()}
}
async function loadTopology(m){
  const response=await fetch('/viewer-config.json');if(!response.ok)throw Error('Viewer configuration unavailable');
  if(!(await response.json()).topologyAvailable)return;
  document.getElementById('topology-panel').hidden=false;
  const r=await fetch('/topology-manifest.json');if(!r.ok)throw Error('Topology manifest unavailable');
  const manifest=await r.json(),cs=manifest.coordinateSystem;
  if(manifest.schemaVersion!==1||manifest.type!=='id_cadastral_edge_topology'||manifest.sourceHashes?.['front-original.heic']!==m.derivation.sourceSHA256||manifest.sourceHashes?.['browser-viewer/original.png']!==m.viewerDerivation.outputSHA256)throw Error('Topology source lineage mismatch');
  if(cs?.type!=='image_pixel_indices'||cs.origin!=='top_left'||cs.xDirection!=='right'||cs.yDirection!=='down'||cs.width!==geometry.sourcePixelWidth||cs.height!==geometry.sourcePixelHeight||!equalValues(cs.pixelCenterOffset,[.5,.5]))throw Error('Topology coordinates invalid');
  const arrays={};let regions;
  for(const name of ['path_points.npy','path_offsets.npy','path_components.npy','nodes.npy','degrees.npy','node_components.npy','regions.geojson']){
    const r=await fetch('/topology-'+name);if(!r.ok)throw Error('Topology artifact unavailable: '+name);const b=await r.arrayBuffer();
    if(b.byteLength!==manifest.artifacts[name].bytes||await sha256(b)!==manifest.artifacts[name].sha256)throw Error('Topology artifact mismatch: '+name);
    if(name.endsWith('.npy'))arrays[name.slice(0,-4)]=readTopologyNpy(b).data;else regions=JSON.parse(new TextDecoder().decode(b));
  }
  if(arrays.path_offsets.length!==arrays.path_components.length+1||arrays.path_offsets[0]!==0||arrays.path_offsets[arrays.path_offsets.length-1]!==arrays.path_points.length/2||arrays.nodes.length!==arrays.degrees.length*2||arrays.node_components.length!==arrays.degrees.length)throw Error('Topology array relationship invalid');
  topology={manifest,arrays,regions};
  document.getElementById('topology-status').textContent=`${arrays.degrees.length.toLocaleString()} nodes · ${arrays.path_components.length.toLocaleString()} paths · ${regions.features.length.toLocaleString()} enclosed faces`;
  document.getElementById('topology-mode').onchange=()=>{selectedTopology=null;document.getElementById('topology-details').textContent='Click a feature or enter its ID. Gaps remain open.';views.original.draw()};
  document.getElementById('topology-select').onclick=()=>{try{const id=Number(document.getElementById('topology-id').value);if(topologyMode()==='off')throw Error('Choose a topology layer first');if(!Number.isInteger(id)||id<0)throw Error('Enter a nonnegative integer ID');chooseTopology(id,true)}catch(e){document.getElementById('topology-details').textContent=e.message}};
}

let measurements=null,measurementSelection=null;
async function loadMeasurements(){
  const cfg=await(await fetch('/viewer-config.json')).json();document.getElementById('perimeter-link').hidden=!cfg.perimeterAvailable;document.getElementById('assembly-link').hidden=!cfg.assemblyAvailable;if(!cfg.measurementsAvailable)return;
  const raw=await(await fetch('/measurements-manifest.json')).arrayBuffer();const m=JSON.parse(new TextDecoder().decode(raw));
  if(m.boundaryId!==boundary.manifest.boundaryId||m.type!=='id_cadastral_scanline_measurements'||m.grids.rectified.width!==rectification.img.width||m.grids.rectified.height!==rectification.img.height)throw Error('Measurement registration mismatch');
  const data={};
  for(const axis of ['x','y']){data[axis]={};for(const key of ['scans','offsets','intervals']){
    const name=`rectified-${axis}-${key}.npy`,r=await fetch('/measurements-'+name);if(!r.ok)throw Error('Missing measurement array');const bytes=await r.arrayBuffer();
    if(await sha256(bytes)!==m.artifacts[name].sha256)throw Error('Measurement hash mismatch');data[axis][key]=readTopologyNpy(bytes).data;
  }}
  const d=await(await fetch('/measurements-diagonals.json')).arrayBuffer();if(await sha256(d)!==m.artifacts['diagonals.json'].sha256)throw Error('Diagonal hash mismatch');
  let models=null;if(cfg.measurementModelsAvailable){models=await(await fetch('/measurement-models.json')).json();if(models.measurementManifestSHA256!==await sha256(raw))throw Error('Model identity mismatch');}
  measurements={manifest:m,data,diagonals:JSON.parse(new TextDecoder().decode(d)),models};
  document.getElementById('measurements-panel').hidden=false;
  document.getElementById('measurements-status').textContent=`Every source row/column and every rectified row/column measured at pixel centers and pixel edges. Rectified lattice: ${m.grids.rectified.width} × ${m.grids.rectified.height}. No smoothing or new fit in the measurement dataset.`;
  document.getElementById('measure-select').onclick=()=>{try{showMeasurement()}catch(e){document.getElementById('measure-details').textContent=e.message}};
  document.getElementById('measure-clear').onclick=()=>{measurementSelection=null;views.rectified.draw()};
  for(const id of ['measure-lines','measure-radii','measure-diagonals'])document.getElementById(id).onchange=()=>{if(activeRectification!=='boundary'){document.getElementById('rectification-version').value='boundary';switchRectification('boundary')}views.rectified.draw()};
  if(models)document.getElementById('measure-model-details').textContent=`Corner radii TL/TR/BR/BL: ${models.cornerRadii.map(v=>v.radiusMillimeters.toFixed(3)+' mm (RMS '+v.rmsMillimeters.toFixed(3)+')').join(' · ')}. Conditional on current perimeter and registration. 3–4–5 maximum deviation: ${Math.max(...models.rightAngle345Checks.map(v=>Math.abs(v.residualFrom5Millimeters))).toExponential(2)} mm. This checks the existing registered frame.`;
}
function showMeasurement(){
  const axis=document.getElementById('measure-axis').value,index=Number(document.getElementById('measure-index').value),edge=document.getElementById('measure-position').value==='edge';
  const n=measurements.manifest.grids.rectified[axis==='x'?'height':'width'];
  if(!Number.isInteger(index)||index<0||index>n-(edge?0:1))throw Error('Index outside measured lattice');
  const row=index*2+(edge?0:1),a=measurements.data[axis],s=a.scans.slice(row*7,row*7+7);
  measurementSelection={axis,row,pieces:a.intervals.slice(a.offsets[row]*11,a.offsets[row+1]*11)};
  const labels=['no perimeter intersection','single interval','multiple intervals','tangent contact','boundary overlap'];
  document.getElementById('measure-details').textContent=`${axis.toUpperCase()} at ${s[0]} px · ${labels[s[1]]} · ${s[2]} interval(s) · outer span ${s[3].toFixed(3)} px / ${s[5].toFixed(4)} mm · occupied length ${s[4].toFixed(3)} px / ${s[6].toFixed(4)} mm. Physical perimeter unresolved.`;
  document.getElementById('rectification-version').value='boundary';switchRectification('boundary');views.rectified.draw();views.rectified.canvas.scrollIntoView({block:'center'});
}
function drawMeasurements(view){
  if(!measurements||activeRectification!=='boundary')return;
  const c=view.ctx;
  const line=(a,b,color)=>{c.strokeStyle=color;c.lineWidth=2;c.beginPath();c.moveTo(view.tx+a[0]*view.scale,view.ty+a[1]*view.scale);c.lineTo(view.tx+b[0]*view.scale,view.ty+b[1]*view.scale);c.stroke()};
  if(measurementSelection){const p=measurementSelection.pieces;for(let i=0;i<p.length;i+=11)line([p[i],p[i+1]],[p[i+2],p[i+3]],'#ffdb66')}
  if(document.getElementById('measure-diagonals').checked)for(const d of measurements.diagonals.diagonals)for(const p of d.intersections)line(p.slice(0,2),p.slice(2,4),'#76dfca');
  const m=measurements.models;if(!m)return;
  const corners=m.virtualSourceCorners.map(p=>project(rectification.manifest.transforms.sourceToRectified,...p));
  if(document.getElementById('measure-lines').checked)for(let i=0;i<4;i++){
    const a=corners[i],b=corners[(i+1)%4],d=[(b[0]-a[0])*.15,(b[1]-a[1])*.15];line([a[0]-d[0],a[1]-d[1]],[b[0]+d[0],b[1]+d[1]],'#65bfff');
  }
  if(document.getElementById('measure-radii').checked){
    const o=rectification.manifest.output,scale=o.pixelsPerMillimeter,origin=o.originCardMillimeters;
    const centers=m.cornerRadii.map((r,i)=>{const v=r.radiusMillimeters;return [[v,v],[85.6-v,v],[85.6-v,53.98-v],[v,53.98-v]][i]});
    for(let i=0;i<4;i++){const r=m.cornerRadii[i].radiusMillimeters,center=centers[i];c.strokeStyle='#ff914d';c.lineWidth=2;c.beginPath();const start=[Math.PI,1.5*Math.PI,0,.5*Math.PI][i];c.arc(view.tx+(center[0]-origin[0])*scale*view.scale,view.ty+(center[1]-origin[1])*scale*view.scale,r*scale*view.scale,start,start+Math.PI/2);c.stroke()}
  }
}

function status(){document.getElementById('status').textContent=pinned?'Point pinned · Escape to resume hover':'Ready · Hover either image to inspect linked pixels'}
document.addEventListener('keydown',e=>{if(e.key==='Escape'){pinned=false;status()}});
(async()=>{try{const r=await fetch('/manifest.json');if(!r.ok)throw Error('Manifest unavailable');const m=await r.json();geometry=m.derivation.id1Geometry;
  const gr=await fetch('/geotiff-manifest.json');if(!gr.ok)throw Error('GeoTIFF manifest unavailable');const gm=await gr.json();if(gm.output.sha256!==m.geoTIFFDisplay.sourceSHA256)throw Error('GeoTIFF display provenance mismatch');document.getElementById('geotiff-json').textContent=JSON.stringify(gm,null,2);document.getElementById('dataset-facts').textContent=`${gm.output.width.toLocaleString()} × ${gm.output.height.toLocaleString()} pixels · ${(gm.output.bytes/1e6).toFixed(2)} MB · RGBA · ${gm.output.compression} lossless · ${1/geometry.outputPixelsPerMillimeter} mm/pixel`;
  const objectsResponse=await fetch('/objects.json');if(!objectsResponse.ok)throw Error('Object layer unavailable');objectLayer=await objectsResponse.json();if(objectLayer.sourceSHA256!==m.derivation.sourceSHA256)throw Error('Object lineage mismatch');const mask=new Image();mask.src='/objects-mask.png';await mask.decode();if(mask.width!==geometry.sourcePixelWidth||mask.height!==geometry.sourcePixelHeight)throw Error('Object mask dimensions mismatch');const maskCanvas=document.createElement('canvas');maskCanvas.width=mask.width;maskCanvas.height=mask.height;labelPixels=maskCanvas.getContext('2d',{willReadFrequently:true});labelPixels.drawImage(mask,0,0);
  await loadBoundary(m);
  for(const name of ['original','rectified']){const img=new Image();img.src=name==='original'?'/original.png':'/geotiff.png';await img.decode();const w=name==='original'?geometry.sourcePixelWidth:m.derivation.outputPixelWidth,h=name==='original'?geometry.sourcePixelHeight:m.derivation.outputPixelHeight;if(img.width!==w||img.height!==h)throw Error(`${name}: dimensions do not match geometry`);views[name]=new View(name,img);if(name==='rectified')savedRectifiedImage=img}await loadRectification();await loadEdges(m);await loadTopology(m);await loadMeasurements();await loadWorkingArea();organizeWorkspace();status();
}catch(e){clearBoundary('Boundary unavailable');document.getElementById('status').textContent='';document.getElementById('error').textContent=`Cannot inspect: ${e.message}`}})();
