// Arc-length streets are shared with the Blender scene. Links remain a separate layer.
const phone = Math.min(window.innerWidth, window.innerHeight) < 720;
const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const routes = DATA.design.routes.map(r => {
  const points = r.points.map(p => W(p[0], p[1], r.z));
  const lengths = [0];
  for (let i = 1; i <= points.length; i++) lengths.push(lengths[i-1]+points[i-1].distanceTo(points[i%points.length]));
  return {...r, points, lengths, length:lengths.at(-1), width:r.district === 'episodic' ? .54 : .88};
});
function sampleRoute(route, distance, out = new THREE.Vector3(), offset = 0) {
  const s = ((distance % route.length)+route.length)%route.length;
  let lo=0, hi=route.points.length;
  while(lo+1<hi) { const mid=(lo+hi)>>1; if(route.lengths[mid]<=s) lo=mid; else hi=mid; }
  const a=route.points[lo], b=route.points[(lo+1)%route.points.length];
  out.lerpVectors(a,b,(s-route.lengths[lo])/(route.lengths[lo+1]-route.lengths[lo]));
  if(offset) { const dx=b.x-a.x,dz=b.z-a.z,l=Math.hypot(dx,dz); out.x+=dz/l*offset; out.z-=dx/l*offset; }
  return out;
}
const streetGroup = new THREE.Group(); scene.add(streetGroup);
function ribbon(route, width, offset, height, material) {
  const pos=[], uv=[], indices=[];
  for(let i=0;i<=route.points.length;i++) {
    const d=route.lengths[i];
    for(const side of [-1,1]) { const p=sampleRoute(route,d,new THREE.Vector3(),offset+side*width/2); pos.push(p.x,p.y+height,p.z); uv.push(side===-1?0:1,d); }
    if(i<route.points.length) { const j=i*2; indices.push(j,j+2,j+1,j+1,j+2,j+3); }
  }
  const geo=new THREE.BufferGeometry(); geo.setAttribute('position',new THREE.Float32BufferAttribute(pos,3)); geo.setAttribute('uv',new THREE.Float32BufferAttribute(uv,2)); geo.setIndex(indices); geo.computeVertexNormals();
  const mesh=new THREE.Mesh(geo,material); streetGroup.add(mesh); return mesh;
}
const wetStreet = color => new THREE.ShaderMaterial({
  side:THREE.DoubleSide,fog:true,
  uniforms:THREE.UniformsUtils.merge([THREE.UniformsLib.fog,{uGlow:{value:col(color)}}]),
  vertexShader:`varying vec2 vUV;
    #include <fog_pars_vertex>
    void main(){vUV=uv;vec4 mvPosition=modelViewMatrix*vec4(position,1.0);gl_Position=projectionMatrix*mvPosition;
    #include <fog_vertex>
    }`,
  fragmentShader:`varying vec2 vUV;uniform vec3 uGlow;
    #include <fog_pars_fragment>
    float noise(vec2 p){return fract(sin(dot(p,vec2(12.9898,78.233)))*43758.5453);}
    void main(){
      float grain=noise(floor(vUV*vec2(320.0,140.0)));
      float puddle=smoothstep(.2,.8,sin(vUV.y*3.1)*.5+.5);
      float streak=pow(abs(vUV.x-.5)*2.0,2.8)*puddle;
      vec3 c=vec3(.008,.015,.025)*( .8+.2*grain )+uGlow*streak*.11;
      c+=vec3(.026,.048,.057)*pow(max(0.0,1.0-abs(vUV.x-.43)*5.0),4.0)*puddle;
      gl_FragColor=vec4(c,1.0);
      #include <fog_fragment>
      #include <colorspace_fragment>
    }`
});
const sidewalkMat = new THREE.MeshBasicMaterial({color:col(hex('#263544')),side:THREE.DoubleSide});
const markingMat = new THREE.MeshBasicMaterial({color:col(hex('#b5b7a1')),side:THREE.DoubleSide,transparent:true,opacity:.38});
const dashMatrices=[];
for(const route of routes) {
  ribbon(route,route.width+.26,0,-.012,sidewalkMat);
  ribbon(route,route.width,0,.005,wetStreet(styleOf(route.district).light));
  for(const side of [-1,1]) ribbon(route,.018,side*(route.width/2+.025),.015,new THREE.MeshBasicMaterial({color:col(styleOf(route.district).light),transparent:true,opacity:.42,side:THREE.DoubleSide}));
  for(let d=0;d<route.length;d+=1.8) {
    const p=sampleRoute(route,d),q=sampleRoute(route,d+.35);
    dummy.rotation.set(-Math.PI/2,0,Math.atan2(q.x-p.x,q.z-p.z));dummy.position.copy(p);dummy.position.y+=.022;dummy.scale.set(1,1,1);dummy.updateMatrix();dashMatrices.push(dummy.matrix.clone());
  }
}
const dashes=new THREE.InstancedMesh(new THREE.PlaneGeometry(.025,.32),markingMat,dashMatrices.length);
dashMatrices.forEach((m,i)=>dashes.setMatrixAt(i,m));streetGroup.add(dashes);

// Collision bounds include the overhanging canopy and roof equipment.
const obstacles = nodes.map(n=>({n,minX:n.x-n.w*.57,maxX:n.x+n.w*.57,minZ:-n.y-n.d*.57,maxZ:-n.y+n.d*.57}));
const obstacleGrid=new Map();
for(const b of obstacles) for(let x=Math.floor((b.minX-.3)/2);x<=Math.floor((b.maxX+.3)/2);x++) for(let z=Math.floor((b.minZ-.3)/2);z<=Math.floor((b.maxZ+.3)/2);z++) {
  const key=x+','+z;if(!obstacleGrid.has(key))obstacleGrid.set(key,[]);obstacleGrid.get(key).push(b);
}
function pointBlocked(p, radius=.14, useTimeline=true) {
  return (obstacleGrid.get(Math.floor(p.x/2)+','+Math.floor(p.z/2))||[]).some(b=>(!useTimeline||b.n.state!=='absent') && p.y < plateauZ(b.n.district)+b.n.h*(useTimeline?b.n.rise:1)*1.08+.14 && p.y>plateauZ(b.n.district)-.1 && p.x>b.minX-radius&&p.x<b.maxX+radius&&p.z>b.minZ-radius&&p.z<b.maxZ+radius);
}
function clearSight(a,b) {
  const length=a.distanceTo(b),p=new THREE.Vector3();
  for(let s=.1;s<length;s+=.12) if(pointBlocked(p.lerpVectors(a,b,s/length),.08)) return false;
  return true;
}

// Soft light on damp pavement; the pool is a radial texture, not an opaque disc.
const glowCanvas=document.createElement('canvas');glowCanvas.width=glowCanvas.height=64;
const gc=glowCanvas.getContext('2d'),grad=gc.createRadialGradient(32,32,0,32,32,32);
grad.addColorStop(0,'rgba(255,255,255,.38)');grad.addColorStop(.3,'rgba(255,255,255,.13)');grad.addColorStop(1,'rgba(255,255,255,0)');gc.fillStyle=grad;gc.fillRect(0,0,64,64);
const glowTexture=new THREE.CanvasTexture(glowCanvas);
const lifeLamps=[];
for(const [ri,route] of routes.entries()) for(let d=1.5;d<route.length;d+=route.district==='episodic'?4.6:3.8) {
  const p=sampleRoute(route,d,new THREE.Vector3(),route.width/2+.07);
  if(pointBlocked(new THREE.Vector3(p.x,p.y+.7,p.z),.06,false)) continue;
  lifeLamps.push({p,route,d});

}
const pavementPools=new THREE.InstancedMesh(new THREE.PlaneGeometry(1.5,2.0),new THREE.MeshBasicMaterial({map:glowTexture,color:0xffffff,transparent:true,opacity:.48,blending:THREE.AdditiveBlending,depthWrite:false,side:THREE.DoubleSide}),lifeLamps.length);
lifeLamps.forEach((s,k)=>{dummy.position.copy(s.p);dummy.position.y+=.025;dummy.rotation.set(-Math.PI/2,0,0);dummy.scale.set(1,1,1);dummy.updateMatrix();pavementPools.setMatrixAt(k,dummy.matrix);pavementPools.setColorAt(k,col(styleOf(s.route.district).light));});streetGroup.add(pavementPools);
const boulevardLamps=instanced('lamp',lifeLamps.length);
lifeLamps.forEach((s,k)=>staticSet(boulevardLamps,k,s.p,[.85,1.05,.85],0,MATTE,styleOf(s.route.district).light,k*.13));
boulevardLamps.mesh.instanceMatrix.needsUpdate=true;
// Existing archive lamps were on the lane center. The new lights sit on sidewalks.
lamps.mesh.visible=false;

// Traffic stays on navigable streets, with two lanes and measured travel distance.
const CARS = phone?58:118;
const cars=instanced('car',CARS),carState=[],carRnd=mulberry(4242);
const hidden=new THREE.Matrix4().makeScale(.0001,.0001,.0001);
for(let k=0;k<CARS;k++) {
  const route=routes[k%routes.length];
  carState.push({route:k%routes.length,distance:carRnd()*route.length,dir:k%2?1:-1,speed:.75+carRnd()*.8,on:true,pos:new THREE.Vector3(),heading:new THREE.Vector3()});
  staticSet(cars,k,new THREE.Vector3(0,-50,0),[.15,.13,.34],0,hex(k%4===0?'#826850':'#3b5264'),WHITE,carRnd());
}
let validEdges=[];
function updateCars(dt) {
  const p=new THREE.Vector3(),q=new THREE.Vector3();
  for(let k=0;k<CARS;k++) {
    const c=carState[k],route=routes[c.route];c.distance+=dt*c.speed*c.dir;
    sampleRoute(route,c.distance,p,.12*c.dir);sampleRoute(route,c.distance+.2*c.dir,q,.12*c.dir);
    c.pos.copy(p);c.heading.subVectors(q,p).normalize();c.on=k<cars.mesh.count;
    dummy.position.copy(p);dummy.position.y+=.028;dummy.rotation.set(0,Math.atan2(c.heading.x,c.heading.z),0);dummy.scale.set(.15,.13,.34);dummy.updateMatrix();
    cars.mesh.setMatrixAt(k,c.on?dummy.matrix:hidden);
  }
  cars.mesh.instanceMatrix.needsUpdate=true;
}

// Low-poly citizens: instanced coats, heads and independently swinging limbs.
const peopleGroup=new THREE.Group();scene.add(peopleGroup);
const PEOPLE=phone?100:260;
const personParts={};
for(const [name,geo,color] of [
  ['body',new THREE.BoxGeometry(.10,.145,.065),'#538899'],
  ['head',new THREE.SphereGeometry(.038,7,5),'#c7a48f'],
  ['leftLeg',new THREE.BoxGeometry(.033,.13,.04),'#48586d'],
  ['rightLeg',new THREE.BoxGeometry(.033,.13,.04),'#48586d'],
  ['leftArm',new THREE.BoxGeometry(.026,.13,.036),'#668da0'],
  ['rightArm',new THREE.BoxGeometry(.026,.13,.036),'#668da0']]) {
  const mesh=new THREE.InstancedMesh(geo,new THREE.MeshBasicMaterial({color:col(hex(color))}),PEOPLE);mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);mesh.frustumCulled=false;personParts[name]=mesh;peopleGroup.add(mesh);
}
const crowdRnd=mulberry(811),people=[];
for(let i=0;i<PEOPLE;i++) {
  const route=routes[i%routes.length],side=i%2?1:-1;
  people.push({route:i%routes.length,distance:crowdRnd()*route.length,speed:.18+crowdRnd()*.16,side,phase:crowdRnd()*Math.PI*2});
  const coat=new THREE.Color(['#a9b7c3','#d98388','#5fbeb5','#8b80b7','#d9b573'][i%5]);
  for(const name of ['body','leftArm','rightArm']) personParts[name].setColorAt(i,coat);
}
const pRoot=new THREE.Object3D(),pLimb=new THREE.Object3D(),pMatrix=new THREE.Matrix4();
function updatePeople(dt,now) {
  if(!peopleGroup.visible) return;
  const p=new THREE.Vector3(),q=new THREE.Vector3();
  people.forEach((person,i)=>{
    const route=routes[person.route],offset=Math.min(route.width/2+.04,route.clearance-.12);
    person.distance+=dt*person.speed*person.side;
    sampleRoute(route,person.distance,p,offset*person.side);sampleRoute(route,person.distance+.15*person.side,q,offset*person.side);
    pRoot.position.copy(p);pRoot.position.y+=.045;pRoot.rotation.set(0,Math.atan2(q.x-p.x,q.z-p.z),0);pRoot.updateMatrix();
    const blocked=pointBlocked(new THREE.Vector3(p.x,p.y+.18,p.z),.07);
    const gait=reduced?0:Math.sin(now*person.speed*18+person.phase)*.48;
    for(const [name,x,y,swing] of [['body',0,.195,0],['head',0,.305,0],['leftLeg',-.026,.065,gait],['rightLeg',.026,.065,-gait],['leftArm',-.067,.19,-gait],['rightArm',.067,.19,gait]]) {
      pLimb.position.set(x,y,0);pLimb.rotation.set(swing,0,0);pLimb.updateMatrix();pMatrix.multiplyMatrices(pRoot.matrix,pLimb.matrix);personParts[name].setMatrixAt(i,blocked?hidden:pMatrix);
    }
  });
  Object.values(personParts).forEach(m=>m.instanceMatrix.needsUpdate=true);
}

// Projecting signs are actual street addresses and places, painted into local textures.
const signGroup=new THREE.Group();scene.add(signGroup);const signs=[],signMaterials=new Map();
const signWords={episodic:['MEMORY','NIGHT MARKET','ARCHIVE','24 / 7'],working:['DOWNTOWN','AFTER HOURS','WORKING'],semantic:['LIBRARY','OPEN LATE'],prasma:['PRASMA','STUDIO'],branding:['SIGNAL'],core:['COMPASS']};
for(const n of nodes.filter(n=>n.created!==null&&signWords[n.district]&&n.id%6===0&&n.h>2).slice(0,70)) {
  const canvas=document.createElement('canvas');canvas.width=256;canvas.height=128;const ctx=canvas.getContext('2d');
  const words=signWords[n.district],word=words[n.id%words.length],color=css(styleOf(n.district).light);
  ctx.fillStyle='#101c28';ctx.fillRect(0,0,256,128);ctx.strokeStyle=color;ctx.lineWidth=3;ctx.strokeRect(5,5,246,118);
  ctx.fillStyle=color;ctx.font='bold 27px sans-serif';ctx.textAlign='center';ctx.fillText(word,128,58);ctx.font='14px monospace';ctx.fillText(styleOf(n.district).name.toUpperCase()+' / OPEN LATE',128,94);
  const tex=new THREE.CanvasTexture(canvas);tex.colorSpace=THREE.SRGBColorSpace;tex.anisotropy=4;
  const key=n.district+word;
  if(!signMaterials.has(key))signMaterials.set(key,new THREE.MeshBasicMaterial({map:tex,side:THREE.DoubleSide}));else tex.dispose();
  const mesh=new THREE.Mesh(new THREE.PlaneGeometry(n.w*.94,n.w*.47),signMaterials.get(key));
  mesh.position.copy(W(n.x,n.y-n.d*.575,plateauZ(n.district)+Math.min(n.h*.48,2.3)));signs.push({n,mesh});
  for(const side of [-1,1]) {
    const sign=new THREE.Mesh(new THREE.PlaneGeometry(n.d*.88,n.d*.44),mesh.material);
    sign.position.copy(W(n.x+side*n.w*.525,n.y,plateauZ(n.district)+.82));sign.rotation.y=side*Math.PI/2;
    signs.push({n,mesh:sign});
  }
}

const signBatches=[];
for(const material of signMaterials.values()) {
  const entries=signs.filter(s=>s.mesh.material===material);
  const mesh=new THREE.InstancedMesh(new THREE.PlaneGeometry(1,1),material,entries.length);
  entries.forEach((entry,i)=>{const source=entry.mesh;source.scale.set(source.geometry.parameters.width,source.geometry.parameters.height,1);source.updateMatrix();entry.matrix=source.matrix.clone();entry.slot=i;entry.batch=mesh;mesh.setMatrixAt(i,entry.matrix);source.geometry.dispose();});
  mesh.frustumCulled=false;signGroup.add(mesh);signBatches.push(mesh);
}
function updateSigns(){signs.forEach(s=>s.batch.setMatrixAt(s.slot,s.n.state==='absent'?hidden:s.matrix));signBatches.forEach(m=>m.instanceMatrix.needsUpdate=true);}

// Distant silhouettes give the inhabited city a horizon and a sense of scale.
const horizon=new THREE.Group();scene.add(horizon);const horizonRnd=mulberry(98);
const skylineMat=new THREE.MeshBasicMaterial({color:col(hex('#142235'))});
const horizonTowers=new THREE.InstancedMesh(new THREE.BoxGeometry(1,1,1),skylineMat,110);horizon.add(horizonTowers);
for(let i=0;i<110;i++) {
  const angle=i/110*Math.PI*2,radius=105+horizonRnd()*48;
  const h=5+horizonRnd()*26,w=1.8+horizonRnd()*3;
  dummy.position.set(center.x+Math.cos(angle)*radius,h/2,center.z+Math.sin(angle)*radius);dummy.rotation.set(0,0,0);dummy.scale.set(w,h,w);dummy.updateMatrix();horizonTowers.setMatrixAt(i,dummy.matrix);
}

// Fine, local rain. Reduced-motion preference keeps the atmospheric scene still.
const rainCount=phone?450:1200,rainRnd=mulberry(919),rainPositions=new Float32Array(rainCount*6),rainSeeds=[];
for(let i=0;i<rainCount;i++)rainSeeds.push([rainRnd()*46-23,rainRnd()*24,rainRnd()*46-23]);
const rainGeo=new THREE.BufferGeometry();rainGeo.setAttribute('position',new THREE.BufferAttribute(rainPositions,3).setUsage(THREE.DynamicDrawUsage));
const rain=new THREE.LineSegments(rainGeo,new THREE.LineBasicMaterial({color:col(hex('#7fb2c8')),transparent:true,opacity:.18,depthWrite:false}));rain.frustumCulled=false;rain.visible=!reduced;scene.add(rain);
function updateAtmosphere(now) {
  horizon.visible=state.ride>=0;
  rain.material.opacity=state.ride>=0?.2:.045;
  if(rain.visible) {
    const anchor=state.ride>=0?camera.position:controls.target;
    rainSeeds.forEach((s,i)=>{const y=(s[1]-(now*7)%24+24)%24;
      rainPositions.set([anchor.x+s[0],y,anchor.z+s[2],anchor.x+s[0]-.045,y+.32,anchor.z+s[2]+.025],i*6);});rainGeo.attributes.position.needsUpdate=true;
  }
}
