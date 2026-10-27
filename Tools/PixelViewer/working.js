let workingArea=null;
async function loadWorkingArea(){
  const cfg=await(await fetch('/viewer-config.json')).json();
  if(!cfg.workingAreaAvailable)return;
  const m=await(await fetch('/working/manifest.json')).json();
  if(m.type!=='id_cadastral_interior_working_area'||m.boundaryId!==boundary.manifest.boundaryId||m.sourceHashes['front-original.heic']!==boundary.manifest.sourceHashes['front-original.heic'])throw Error('Working-area lineage mismatch');
  async function bytes(name){const r=await fetch('/working/'+name);if(!r.ok)throw Error('Working-area artifact unavailable');const b=await r.arrayBuffer();if(await sha256(b)!==m.artifacts[name].sha256)throw Error('Working-area hash mismatch');return b}
  async function image(name){return createImageBitmap(new Blob([await bytes(name)],{type:'image/png'}))}
  const geoms=JSON.parse(new TextDecoder().decode(await bytes('working-geometry.json')));
  const labels=await image('source-labels.png');const c=document.createElement('canvas');c.width=labels.width;c.height=labels.height;const cx=c.getContext('2d',{willReadFrequently:true});cx.drawImage(labels,0,0);
  workingArea={manifest:m,geoms,labels:cx,original:await image('source-overlay.png'),rectified:await image('rectified-overlay.png')};
  const panel=document.createElement('section');panel.id='working-panel';panel.style.cssText='padding:12px 20px;background:#17352e;border-bottom:1px solid #47705c';
  panel.innerHTML='<strong>Interior workspace</strong> · <span id="working-summary"></span><br><label><input id="working-overlay" type="checkbox" checked> Show edge exclusion (amber) and shadow (violet)</label> · <label><input id="working-boundary" type="checkbox" checked> Working perimeter</label> · <a href="/working/interior.tif" download>Interior GeoTIFF mask</a> · <a href="/working/manifest.json" target="_blank">Dataset JSON</a><div>Clear card interior is available for analysis. Border areas are excluded; the existing nominal coordinate mapping is retained.</div>';
  document.querySelector('header').after(panel);
  const s=m.summary;document.getElementById('working-summary').textContent=`${s.interiorPixelCount.toLocaleString()} native interior pixels · ${s.supportedColumnCount.toLocaleString()} bottom columns separated`;
  for(const id of ['working-overlay','working-boundary'])document.getElementById(id).onchange=()=>{views.original.draw();views.rectified.draw()};
  document.getElementById('boundary-visible').checked=false;
  document.getElementById('rectification-version').value='boundary';switchRectification('boundary');
  document.getElementById('rectified-contour').checked=false;
  if(edges)document.getElementById('edges-visible').checked=true;
  if(measurements){
    document.getElementById('measure-lines').checked=true;
    document.getElementById('measure-diagonals').checked=true;
  }
  views.original.draw();views.rectified.draw();
}
function workingSample(view,x,y){
  if(!workingArea)return '';
  const p=view.name==='original'?[x,y]:linked('rectified',x,y);
  const ix=Math.floor(p[0]),iy=Math.floor(p[1]),c=workingArea.labels.canvas;
  if(ix<0||iy<0||ix>=c.width||iy>=c.height)return '\nOutside working scene';
  const label=workingArea.labels.getImageData(ix,iy,1,1).data[0];
  return '\n'+['Surroundings','Interior · eligible for analysis','Edge area · excluded from interior analysis','Shadow · working region'][label];
}
function drawWorkingArea(view){
  if(!workingArea)return;
  const c=view.ctx;
  if(document.getElementById('working-overlay').checked&&(view.name==='original'||activeRectification==='boundary')){
    const im=workingArea[view.name];c.drawImage(im,view.tx,view.ty,im.width*view.scale,im.height*view.scale);
  }
  if(document.getElementById('working-boundary').checked){
    c.strokeStyle='#ff914d';c.lineWidth=1.5;
    for(const f of workingArea.geoms.features){const rings=f.geometry.coordinates.map(r=>r.map(p=>view.name==='original'?p:linked('original',...p)));c.stroke(objectPath(view,{geometry:{coordinates:rings}}))}
  }
}
