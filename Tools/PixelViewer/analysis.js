/* Presentation of retained stages; never substitutes availability for an analysis result. */
async function loadAnalysisInventory(analyze,data){
  const response=await fetch('/analysis-inventory.json');
  if(!response.ok)throw Error('No analysis inventory');
  const inventory=await response.json();
  const names={rectification:'Boundary-derived registration',edges:'Native image transitions',topology:'Connected paths and enclosed faces',measurements:'Every-row and every-column measurements','measurement-models':'Diagonals, side geometry and corner radii',perimeter:'Competing perimeter candidates',assembly:'Assembled observed paths','path-assessment':'Path color and spatial evidence','working-area':'Interior and shadow working regions',materials:'Apple material observations',scores:'All 46 material score layers',separation:'Surface versus surroundings',regions:'Four native scene partitions','region-report':'Full-scene region comparison',temporal:'Timestamped handling evidence'};
  const routes={rectification:'/rectification-manifest.json',edges:'/edges-manifest.json',topology:'/topology-topology.json',measurements:'/measurements-manifest.json','measurement-models':'/measurement-models.json',perimeter:'/perimeter-report.html',assembly:'/assembly.html','path-assessment':'/path-assessment.json','working-area':'/working/manifest.json',materials:'/material-overlay.png',scores:'/materials/',separation:'/separation/index.html',regions:'/regions/manifest.json','region-report':'/region-report/report.html'};
  const summary=document.createElement('div');summary.id='analysis-summary';
  const count=Object.values(inventory.stages).filter(s=>s.state==='available').length;
  summary.textContent=`${count} analysis stages available · See Analyze for results and unavailable stages`;
  document.getElementById('workspace-tabs').after(summary);
  const section=document.createElement('section');section.className='tool-group';
  const heading=document.createElement('h2');heading.textContent='Analysis inventory';section.append(heading);
  for(const [key,title] of Object.entries(names)){
    const state=inventory.stages[key]||{state:'not-loaded',reason:'No package supplied for this session.'};
    const item=document.createElement('div');item.className='capability';
    const name=document.createElement('strong');name.textContent=title;item.append(name);
    const status=document.createElement('span');status.className=state.state==='available'?'available':'unavailable';
    status.textContent=state.state==='available'?'Available':state.state.replaceAll('-',' ');item.append(status);
    if(state.state==='available'&&routes[key]){
      const a=document.createElement('a');a.href=routes[key];a.textContent='Open result';a.target='_blank';a.rel='noopener';item.append(a);
    }
    if(state.reason){const reason=document.createElement('p');reason.textContent=state.reason;item.append(reason)}
    section.append(item);
  }
  analyze.prepend(section);
  if(inventory.runReceipt){const a=document.createElement('a');a.href='/analysis-run.json';a.textContent='Analysis execution receipt';a.target='_blank';a.rel='noopener';data.prepend(a)}
  window.analysisInventory=inventory;
}
