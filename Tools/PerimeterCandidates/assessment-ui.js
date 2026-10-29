'use strict';
window.attachPathAssessment = async function(data, select, redraw) {
 const cfg=await(await fetch('/viewer-config.json')).json();
 if(!cfg.pathAssessmentAvailable)return null;
 const panel=document.getElementById('appearance');panel.hidden=false;
 document.getElementById('appearance-status').textContent='Loading path-linked color evidence…';
 const response=await fetch('/path-assessment.json');if(!response.ok)throw Error('Path assessment unavailable');
 const assessment=await response.json();
 const paths=new Map(assessment.paths.map(p=>[p.pathId,p]));
 const pairSelect=document.getElementById('comparison');
 let current=null;
 const format=x=>typeof x==='number'?Number(x.toPrecision(5)):x;
 function showPair(){
  const ref=current?.comparisons[Number(pairSelect.value)];
  const container=document.getElementById('band-table');container.replaceChildren();
  if(!ref){document.getElementById('hypothesis').textContent='No paired color comparison at this path.';return;}
  const c=assessment.comparisons[ref.comparisonId],h=c.hypothesis;
  document.getElementById('hypothesis').textContent=`${c.side}, native scan ${c.scanIndex}: ${h.status} — ${h.reason}. This is an appearance-continuation hypothesis, not physical-edge certification.`;
  const table=document.createElement('table');table.innerHTML='<thead><tr><th>Neighborhood</th><th>Mean color</th><th>RGB</th><th>Chromaticity</th><th>Intensity</th></tr></thead>';
  const body=document.createElement('tbody');
  for(const [role,name] of Object.entries(h.bandRoles||{})){
   const s=c.bands[name]?.statistics;if(!s?.meanRGB)continue;
   const tr=document.createElement('tr'),color=s.meanRGB.map(v=>Math.max(0,Math.min(255,Math.round(v))));
   const hex='#'+color.map(v=>v.toString(16).padStart(2,'0')).join('');
   const values=[role,hex,s.meanRGB.map(format).join(', '),s.meanChromaticity?.map(format).join(', ')||'undefined',format(s.meanChannelIntensity)];
   values.forEach((v,i)=>{const td=document.createElement('td');td.textContent=v;if(i===1){const swatch=document.createElement('span');swatch.style.cssText=`display:inline-block;width:20px;height:20px;margin-right:8px;background:${hex};border:1px solid white`;td.prepend(swatch);}tr.append(td);});body.append(tr);
  }
  table.append(body);container.append(table);
  document.getElementById('feature-details').textContent=JSON.stringify({features:h.features,intensity:h.intensity,betweenDarkerThanBoth:h.betweenDarkerThanBoth,pathLinks:c.pathLinks,comparisonEligible:c.comparisonEligible},null,2);
  const links=document.getElementById('alternative-paths');links.replaceChildren();
  const ids=new Set(Object.values(c.pathLinks).flat().map(x=>x.pathId));
  for(const id of ids){const button=document.createElement('button');button.textContent=`Inspect alternative path ${id}`;button.onclick=()=>{select.value=id;redraw();};links.append(button);}
 }
 function render(id){
  current=paths.get(id);pairSelect.replaceChildren();
  const coverage=document.getElementById('appearance-status');
  if(!current){coverage.textContent='No appearance assessment for this path.';return;}
  coverage.textContent=`Available evidence: ${current.classification.replaceAll('_',' ')}. Counts below are native locations within each side; side overlap is retained.`;
  const cov=document.getElementById('coverage-table');cov.replaceChildren();const table=document.createElement('table');table.innerHTML='<thead><tr><th>Side</th><th>Support</th><th>Opposition</th><th>Conflict</th><th>Mixed</th><th>Insufficient</th><th>Uncompared</th></tr></thead>';const tbody=document.createElement('tbody');for(const [side,s] of Object.entries(current.sides)){const tr=document.createElement('tr');for(const v of [side,...['support','opposition','conflicting','mixed','insufficient','uncompared'].map(k=>s.pixelCoverage[k])]){const td=document.createElement('td');td.textContent=typeof v==='number'?v.toLocaleString():v;tr.append(td);}tbody.append(tr);}table.append(tbody);cov.append(table);
  current.comparisons.forEach((r,i)=>{const c=assessment.comparisons[r.comparisonId],o=document.createElement('option');o.value=i;o.textContent=`${c.side} scan ${c.scanIndex}: ${r.outcome}`;pairSelect.append(o);});
  const meaningful=current.comparisons.findIndex(r=>r.outcome==='support'||r.outcome==='opposition'||r.outcome==='conflicting');
  if(meaningful>=0)pairSelect.value=meaningful;
  showPair();
 }
 pairSelect.onchange=showPair;
 const ranking=assessment.paths.map(p=>({id:p.pathId,score:Object.values(p.sides).reduce((n,s)=>n+(s.coverage.signedSupportScans||0),0)})).sort((a,b)=>b.score-a.score||a.id-b.id);
 document.getElementById('evidence-order').onclick=()=>{if(ranking.length){select.value=ranking[0].id;redraw();}};
 return {render,initialPathId:ranking[0]?.id};
};
