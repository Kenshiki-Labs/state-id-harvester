const fs=require('fs'),vm=require('vm'),assert=require('assert');
const app=fs.readFileSync(require('path').join(__dirname,'app.js'),'utf8');
const elements={'topology-mode':{value:'component'},'topology-id':{},'topology-details':{}};
const context=vm.createContext({TextDecoder,Uint8Array,Float64Array,DataView,Number,Math,topology:null,selectedTopology:null,views:{original:{scale:1,draw(){}}},document:{getElementById:id=>elements[id]}});
vm.runInContext(app.slice(app.indexOf('function readTopologyNpy('),app.indexOf('async function loadTopology(')),context);
const a={path_points:[0,0,.5,.5,1,1],path_offsets:[0,3],path_components:[0],nodes:[0,0,1,1,4,4],degrees:[1,1,0],node_components:[0,0,1]};
context.topology={arrays:a,regions:{features:[{properties:{regionId:0,componentId:0},geometry:{coordinates:[[[0,0],[2,0],[2,2],[0,2],[0,0]],[[.5,.5],[1,.5],[1,1],[.5,1],[.5,.5]]]}}]}};
context.chooseTopology(0);assert.equal(context.selectedTopology,0);
const ops=[];context.drawTopology({tx:10,ty:20,scale:2,ctx:{beginPath(){},moveTo(x,y){ops.push(['move',x,y])},lineTo(x,y){ops.push(['line',x,y])},stroke(){}}});
assert.deepEqual(ops,[['move',11,21],['line',12,22],['line',13,23]]);
context.chooseTopology(1);assert.equal(context.selectedTopology,1);assert(elements['topology-details'].textContent.includes('1 isolated nodes'));
elements['topology-mode'].value='region';context.selectTopologyAt([2,2]);assert.equal(context.selectedTopology,0);
context.selectTopologyAt([1.25,1.25]);assert.equal(context.selectedTopology,null);
elements['topology-mode'].value='off';ops.length=0;context.drawTopology({});assert.equal(ops.length,0);
function npy(value){let h="{'descr': '<f8', 'fortran_order': False, 'shape': (1, 2), }";h+=' '.repeat((64-(10+h.length+1)%64)%64)+'\n';const b=new ArrayBuffer(10+h.length+16),u=new Uint8Array(b),v=new DataView(b);u.set([147,78,85,77,80,89,1,0]);v.setUint16(8,h.length,true);u.set(Buffer.from(h),10);v.setFloat64(10+h.length,value,true);v.setFloat64(18+h.length,.5,true);return b}
assert.deepEqual(Array.from(context.readTopologyNpy(npy(.5)).data),[.5,.5]);assert.throws(()=>context.readTopologyNpy(npy(NaN)),/numeric/);assert.throws(()=>context.readTopologyNpy(npy(.5).slice(0,-1)),/size/);
console.log('Topology renderer preserves intersection coordinates and every vertex, supports isolated components and face holes; off draws nothing; malformed arrays rejected');
