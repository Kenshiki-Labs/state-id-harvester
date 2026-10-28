const fs=require('fs'),vm=require('vm'),assert=require('assert');
const app=fs.readFileSync(require('path').join(__dirname,'app.js'),'utf8');
const context=vm.createContext({TextDecoder,Uint8Array,Int32Array,Float64Array,DataView,BigInt,Number,edges:null,selectedEdge:null,boundaryMask:{width:20,height:20,pixels:new Uint8Array(1600).fill(255)},document:{getElementById:()=>({checked:true})}});
vm.runInContext(app.slice(app.indexOf('function readEdgeNpy('),app.indexOf('async function loadEdges(')),context);
function npy(descr,shape,values){
 let h=`{'descr': '${descr}', 'fortran_order': False, 'shape': (${shape}), }`;
 h+=' '.repeat((64-(10+h.length+1)%64)%64)+'\n';
 const size=descr==='<i4'?4:8,b=new ArrayBuffer(10+h.length+values.length*size),v=new DataView(b),u=new Uint8Array(b);
 u.set([147,78,85,77,80,89,1,0]);v.setUint16(8,h.length,true);u.set(Buffer.from(h),10);
 values.forEach((n,i)=>size===4?v.setInt32(10+h.length+i*size,n,true):v.setBigInt64(10+h.length+i*size,BigInt(n),true));return b;
}
assert.deepEqual(Array.from(context.readEdgeNpy(npy('<i4','2, 2',[0,1,2,3]),'<i4',2)),[0,1,2,3]);
assert.deepEqual(Array.from(context.readEdgeNpy(npy('<i8','3,',[0,2,4]),'<i8',1)),[0,2,4]);
assert.throws(()=>context.readEdgeNpy(npy('<i8','1,',[9007199254740992n]),'<i8',1),/Unsafe/);
assert.throws(()=>context.readEdgeNpy(npy('<i4','2, 2',[0,1,2,3]).slice(0,-1),'<i4',2),/size mismatch/);
assert.throws(()=>context.readEdgeNpy(npy('<i4','4,',[0,1,2,3]),'<i4',2),/layout/);
const operations=[];
context.edges={points:[0,1,2,3,4,5],offsets:[0,3],chains:[{}]};
context.drawEdges({tx:10,ty:20,scale:2,ctx:{beginPath(){},moveTo(x,y){operations.push(['move',x,y])},lineTo(x,y){operations.push(['line',x,y])},stroke(){}}});
assert.deepEqual(operations,[['move',11,23],['line',15,27],['line',19,31]]);
console.log('Edge NPY admission rejects malformed numeric arrays; rendering preserves every vertex at pixel centers');

const shortOperations=[];
context.edges={points:[3,4,10,11,11,12],offsets:[0,1,3],chains:[{},{}]};
context.drawEdges({tx:0,ty:0,scale:2,ctx:{beginPath(){},arc(x,y,r){shortOperations.push(['dot',x,y,r])},fill(){},moveTo(x,y){shortOperations.push(['move',x,y])},lineTo(x,y){shortOperations.push(['line',x,y])},stroke(){}}});
assert.deepEqual(shortOperations,[['dot',7,9,.5],['move',21,23],['line',23,25]]);
console.log('Singleton and two-point chains remain visible without dropping or moving points');

const colors=[],vertices=[];
context.boundaryMask={width:4,height:1,pixels:new Uint8Array([255,0,0,255,255,0,0,255,0,0,0,255,0,0,0,255])};
context.edges={points:[0,0,1,0,2,0,3,0],offsets:[0,4],chains:[{}]};
context.drawEdges({tx:0,ty:0,scale:1,ctx:{beginPath(){},moveTo(x,y){vertices.push(['move',x,y])},lineTo(x,y){vertices.push(['line',x,y])},stroke(){colors.push(this.strokeStyle)}}});
assert.deepEqual(colors,['#e977f0','#65bfff']);
assert.deepEqual(vertices,[['move',.5,.5],['line',1.5,.5],['move',1.5,.5],['line',2.5,.5],['line',3.5,.5]]);
assert(!app.includes('toggle.checked=true'));
console.log('Mask-color split preserves all three segments and defaults all overlays off');

context.boundaryMask=null;assert.throws(()=>context.edgeColor(0,0),/Verified boundary mask/);
