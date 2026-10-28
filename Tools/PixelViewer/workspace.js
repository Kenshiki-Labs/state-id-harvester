/* Presentation only: move existing controls, never recreate their state. */
let workspaceTab='inspect';
function openWorkspaceTab(name,focus=false){
  if(!document.getElementById('workspace-tabs'))return;
  workspaceTab=name;
  for(const button of document.querySelectorAll('[data-workspace-tab]')){
    const selected=button.dataset.workspaceTab===name;
    button.setAttribute('aria-selected',String(selected));button.tabIndex=selected?0:-1;
    if(selected&&focus)button.focus();
  }
  for(const panel of document.querySelectorAll('[data-workspace-panel]'))panel.hidden=panel.dataset.workspacePanel!==name;
}
function organizeWorkspace(){
  const retained=Array.from(document.querySelectorAll('input,select,button,a,output'));
  const header=document.querySelector('header'),oldNav=header.querySelector('nav'),main=document.querySelector('main');
  const shell=document.createElement('div');shell.id='workspace-shell';main.before(shell);shell.append(main);
  const aside=document.createElement('aside');aside.id='workspace-tools';aside.setAttribute('aria-label','Inspection tools');shell.append(aside);
  const tabs=document.createElement('nav');tabs.id='workspace-tabs';tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label','Workspace tasks');header.after(tabs);
  const panels={};
  for(const name of ['inspect','layers','measure','analyze','data']){
    const button=document.createElement('button');button.id='tab-'+name;button.textContent=name[0].toUpperCase()+name.slice(1);button.dataset.workspaceTab=name;button.setAttribute('role','tab');button.setAttribute('aria-controls','task-'+name);tabs.append(button);
    button.onclick=()=>openWorkspaceTab(name);
    button.onkeydown=e=>{const all=Array.from(tabs.children),i=all.indexOf(button);let j;if(e.key==='ArrowRight')j=(i+1)%all.length;else if(e.key==='ArrowLeft')j=(i+all.length-1)%all.length;else if(e.key==='Home')j=0;else if(e.key==='End')j=all.length-1;else return;e.preventDefault();openWorkspaceTab(all[j].dataset.workspaceTab,true)};
    const panel=document.createElement('div');panel.id='task-'+name;panel.dataset.workspacePanel=name;panel.setAttribute('role','tabpanel');panel.setAttribute('aria-labelledby',button.id);aside.append(panel);panels[name]=panel;
  }
  function section(parent,title,description){const s=document.createElement('section');s.className='tool-group';const h=document.createElement('h2');h.textContent=title;s.append(h);if(description){const p=document.createElement('p');p.textContent=description;s.append(p)}parent.append(s);return s}
  function move(id,dest,label=false){const el=document.getElementById(id);if(!el)return;dest.append(label?el.closest('label'):el)}
  function links(source,title){const found=Array.from(source.querySelectorAll('a'));if(!found.length)return;const s=section(panels.data,title);for(const a of found)s.append(a)}
  const scene=document.getElementById('boundary-visible').closest('section');
  const edgesPanel=document.getElementById('edges-panel'),topologyPanel=document.getElementById('topology-panel'),measurePanel=document.getElementById('measurements-panel'),workPanel=document.getElementById('working-panel');
  const inspect=section(panels.inspect,'Selected pixel','Hover either image. Click to pin; Escape resumes inspection.');
  for(const name of ['original','rectified']){
    const h=document.createElement('h3');h.textContent=name==='original'?'Original image':'Rectified image';inspect.append(h);
    const readout=document.createElement('div');readout.className='pixel-readout';readout.id='inspect-'+name;inspect.append(readout);
    const output=document.querySelector('#'+name+' output');const sync=()=>readout.textContent=output.textContent;new MutationObserver(sync).observe(output,{childList:true,characterData:true,subtree:true});sync();
  }
  const context=section(panels.inspect,'Working dataset',workPanel?'Clear interior is available for analysis. Amber border areas are excluded; violet marks the working shadow region.':'No working-interior dataset is loaded. The saved partition is not a shadow classification.');
  if(workPanel)move('working-summary',context);
  const base=section(panels.inspect,'Coordinate basis',measurements?'Measurements use the retained observed perimeter and nominal registration. Physical boundary accuracy remains unassessed.':'The saved nominal registration maps pixel and card coordinates. No perimeter measurement package is loaded.');
  base.classList.add('basis-note');
  const layerGroup=section(panels.layers,'Card and surroundings');
  if(workPanel){links(workPanel,'Interior working dataset');for(const id of ['working-boundary','working-overlay'])move(id,layerGroup,true);workPanel.hidden=true;}
  for(const id of ['boundary-visible','highlight-card','highlight-surroundings'])move(id,layerGroup,true);
  const rectlabel=document.getElementById('rectified-contour').closest('label');layerGroup.append(rectlabel);
  if(edges){const s=section(panels.layers,'Image transitions','Pink: inside the retained baseline mask. Blue: outside. Selected chains are yellow.');move('edges-visible',s,true)}
  if(topology){const s=section(panels.layers,'Connectivity');move('topology-mode',s,true)}
  links(scene,'Baseline boundary and scene');if(edges)links(edgesPanel,'Native image transitions');if(topology)links(topologyPanel,'Connectivity data');if(measurements)links(measurePanel,'Baseline measurements and models');
  const sceneData=section(panels.data,'Boundary processing');move('boundary-status',sceneData);
  const sceneAnalyze=section(panels.analyze,'Selected scene region');for(const id of ['select-card','select-surroundings','object-details'])move(id,sceneAnalyze);
  scene.hidden=true;
  if(edges){const s=section(panels.analyze,'Selected image transition');for(const id of ['edges-left','edges-bottom','edge-details'])move(id,s);const d=section(panels.data,'Transition inventory');move('edges-status',d)}edgesPanel.hidden=true;
  if(topology){const s=section(panels.analyze,'Connected feature','Choose a connectivity layer in Layers, then select a feature.');move('topology-id',s,true);move('topology-select',s);move('topology-details',s);const d=section(panels.data,'Connectivity inventory');move('topology-status',d)}topologyPanel.hidden=true;
  if(measurements){panels.measure.append(measurePanel);measurePanel.querySelector('h2').textContent='Distances and geometry';const p=measurePanel.querySelectorAll('p')[1];p.textContent='Dataset: retained baseline perimeter and registration. These measurements have not been recomputed from the working shadow correction.';document.getElementById('measure-model-details').textContent=document.getElementById('measure-model-details').textContent.replace('current perimeter and registration','retained baseline perimeter and registration');}
  else section(panels.measure,'Measurements unavailable','No measurement dataset was loaded in this session.');
  const reports=section(panels.analyze,'Compare hypotheses');for(const id of ['assembly-link','perimeter-link']){move(id,reports);const a=document.getElementById(id);a.target='_blank';a.rel='noopener'}
  links(oldNav,'Raster exports');oldNav.hidden=true;
  panels.data.append(document.getElementById('rectification-dataset'),document.getElementById('dataset'),document.querySelector('footer'));
  loadAnalysisInventory(panels.analyze,panels.data).catch(error=>{document.getElementById('error').textContent='Analysis inventory unavailable: '+error.message});
  loadPortraitRegions(panels.analyze).catch(error=>{document.getElementById('error').textContent='Portrait evidence unavailable: '+error.message});
  const legend=document.createElement('div');legend.id='active-layer-legend';legend.setAttribute('aria-label','Active image layers');tabs.after(legend);
  const quick=document.createElement('div');quick.id='quick-layer-controls';quick.setAttribute('role','group');quick.setAttribute('aria-label','Image overlay controls');legend.before(quick);
  for(const [id,text] of [['edges-visible','Pink / blue edges · original'],['measure-diagonals','Diagonals · rectified'],['measure-lines','Side lines / 3–4–5 · rectified'],['measure-radii','Corner radii · rectified']]){
    if((id==='edges-visible'&&!edges)||(id!=='edges-visible'&&!measurements))continue;
    const input=document.getElementById(id),label=input.closest('label');label.replaceChildren(input,document.createTextNode(' '+text));quick.append(label);
  }
  function updateLegend(){
    const definitions=[['working-boundary','Working perimeter','#ff914d'],['working-overlay','Excluded edge / shadow','#d4ad59'],['boundary-visible','Baseline contour','#ff914d'],['highlight-card','Card partition','#28e6b9'],['highlight-surroundings','Surroundings','#968cff'],['edges-visible','Interior / exterior edges','#e977f0'],['rectified-contour','Baseline rectified contour','#ff914d'],['measure-lines','Side lines / virtual corners','#65bfff'],['measure-radii','Corner radii','#ff914d'],['measure-diagonals','Diagonals','#76dfca']];
    legend.replaceChildren();const title=document.createElement('span');title.textContent='Visible';legend.append(title);
    for(const [id,label,color] of definitions){const input=document.getElementById(id);if(!input?.checked||input.disabled)continue;const chip=document.createElement('span');chip.className='layer-chip';chip.style.borderLeftColor=color;chip.textContent=label;legend.append(chip)}
    const mode=document.getElementById('topology-mode');if(topology&&mode.value!=='off'){const chip=document.createElement('span');chip.className='layer-chip';chip.textContent=mode.selectedOptions[0].text;legend.append(chip)}
    if(legend.children.length===1)legend.append(document.createTextNode('No overlays'));
  }
  document.addEventListener('change',updateLegend);updateLegend();
  for(const id of ['select-card','select-surroundings','topology-select','edges-left','edges-bottom'])document.getElementById(id)?.addEventListener('click',()=>openWorkspaceTab('analyze'));
  document.getElementById('measure-select').addEventListener('click',()=>openWorkspaceTab('measure'));
  for(const canvas of document.querySelectorAll('canvas'))canvas.addEventListener('pointerup',()=>{if(pinned)openWorkspaceTab(selectedEdge||selectedTopology?'analyze':'inspect')});
  document.addEventListener('click',e=>{const a=e.target.closest('a');if(a?.getAttribute('href')==='#dataset'){e.preventDefault();openWorkspaceTab('data')}});
  document.body.classList.add('organized');openWorkspaceTab('inspect');
  if(retained.some(node=>!node.isConnected))throw Error('Workspace lost an existing control');
  window.workspaceCapabilities={retainedControlCount:retained.length,allRetained:true};
}
