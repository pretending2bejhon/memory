// Arc-length streets are shared with the Blender scene. Links remain a separate layer.
const phone = Math.min(window.innerWidth, window.innerHeight) < 720;
const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const routes = DATA.design.routes.map(r => {
  const points = r.points.map(p => W(p[0], p[1], r.z));
  const lengths = [0];
  for (let i = 1; i <= points.length; i++) lengths.push(lengths[i-1]+points[i-1].distanceTo(points[i%points.length]));
  // Unit side normal per segment, computed once, so sampling an offset lane allocates nothing.
  const sideX = new Float64Array(points.length), sideZ = new Float64Array(points.length);
  for (let i = 0; i < points.length; i++) { const a=points[i], b=points[(i+1)%points.length], dx=b.x-a.x, dz=b.z-a.z, l=Math.hypot(dx,dz); sideX[i]=dz/l; sideZ[i]=dx/l; }
  return {...r, points, lengths, sideX, sideZ, length:lengths.at(-1), width:r.district === 'episodic' ? .54 : .88};
});
function sampleRoute(route, distance, out = new THREE.Vector3(), offset = 0) {
  ROUTE_ARGS[0] = distance; ROUTE_ARGS[1] = offset;
  return sampleRouteArgs(route, out);
}
// The same sampling with the distance and the lane offset read from ROUTE_ARGS: a per-frame caller
// passes no double, so nothing is boxed when the optimizer does not inline the call.
const ROUTE_ARGS = new Float64Array(2);
function sampleRouteArgs(route, out) {
  const distance = ROUTE_ARGS[0], offset = ROUTE_ARGS[1];
  const s = ((distance % route.length)+route.length)%route.length;
  let lo=0, hi=route.points.length;
  while(lo+1<hi) { const mid=(lo+hi)>>1; if(route.lengths[mid]<=s) lo=mid; else hi=mid; }
  const a=route.points[lo], b=route.points[(lo+1)%route.points.length];
  out.lerpVectors(a,b,(s-route.lengths[lo])/(route.lengths[lo+1]-route.lengths[lo]));
  if(offset) { out.x+=route.sideX[lo]*offset; out.z-=route.sideZ[lo]*offset; }
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
// C11.3: puddles carry coloured streaks from nearby signs. Each road keeps a strip texture along its
// length with one row per kerb; a sign adds its colour to the bins beside it. The streaks are static:
// they change only when the timeline switches a sign on or off, and the rave cut dims them with the signs.
const GLOW_BIN=.1,glowSources=[],streetCut={value:1};
const routeGlow=routes.map(route=>{
  const bins=Math.max(8,Math.min(2048,Math.ceil(route.length/GLOW_BIN))),data=new Uint8Array(bins*2*4);
  const texture=new THREE.DataTexture(data,bins,2,THREE.RGBAFormat);
  texture.magFilter=texture.minFilter=THREE.LinearFilter;texture.wrapS=THREE.RepeatWrapping;texture.needsUpdate=true;
  return {bins,data,texture,acc:new Float32Array(bins*2*3)};
});
let glowDirty=true;
// Registers a sign at world point p with a linear colour; returns its id, or -1 when no road is near.
function streetGlowSource(p,color,weight){
  const taps=[];
  routes.forEach((route,ri)=>{
    const pts=route.points;let best=0,bd=Infinity;
    for(let i=0;i<pts.length;i++){const dx=pts[i].x-p.x,dz=pts[i].z-p.z,d=dx*dx+dz*dz;if(d<bd){bd=d;best=i;}}
    const a=pts[best],b=pts[(best+1)%pts.length],dx=b.x-a.x,dz=b.z-a.z,l=Math.hypot(dx,dz)||1;
    const lateral=((p.x-a.x)*dz-(p.z-a.z)*dx)/l,along=((p.x-a.x)*dx+(p.z-a.z)*dz)/l,reach=Math.abs(lateral)-route.width/2;
    if(reach>1.5)return;
    const G=routeGlow[ri],s=route.lengths[best]+along,w=weight*(1-Math.max(0,reach-.3)/1.2),row=lateral>0?1:0;
    for(let c=Math.floor((s-.4)/route.length*G.bins);c<=Math.ceil((s+.4)/route.length*G.bins);c++){
      const k=w*Math.max(0,1-Math.abs((c+.5)/G.bins*route.length-s)/.4);
      if(k>0)taps.push(ri,((c%G.bins)+G.bins)%G.bins,row,k);
    }
  });
  if(!taps.length)return -1;
  glowSources.push({taps,color,level:0});return glowSources.length-1;
}
function setStreetGlow(id,level){const s=glowSources[id];if(s&&s.level!==level){s.level=level;glowDirty=true;}}
function commitStreetGlow(){
  if(!glowDirty)return;glowDirty=false;
  for(const G of routeGlow)G.acc.fill(0);
  for(const s of glowSources){if(!s.level)continue;const t=s.taps;
    for(let i=0;i<t.length;i+=4){const G=routeGlow[t[i]],o=(t[i+2]*G.bins+t[i+1])*3,k=t[i+3]*s.level;G.acc[o]+=s.color[0]*k;G.acc[o+1]+=s.color[1]*k;G.acc[o+2]+=s.color[2]*k;}}
  // Stored at half scale, so two overlapping signs still fit a byte.
  for(const G of routeGlow){for(let j=0,n=G.bins*2;j<n;j++){G.data[j*4]=Math.min(255,G.acc[j*3]*127.5);G.data[j*4+1]=Math.min(255,G.acc[j*3+1]*127.5);G.data[j*4+2]=Math.min(255,G.acc[j*3+2]*127.5);G.data[j*4+3]=255;}
    G.texture.needsUpdate=true;}
}
const wetStreet = (color, route, glow) => new THREE.ShaderMaterial({
  side:THREE.DoubleSide,fog:true,
  uniforms:Object.assign(THREE.UniformsUtils.merge([THREE.UniformsLib.fog,{uGlow:{value:col(color)},uLen:{value:route.length},uWidth:{value:route.width}}]),{uSigns:{value:glow.texture},uCut:streetCut}),
  vertexShader:`varying vec2 vUV;
    #include <fog_pars_vertex>
    void main(){vUV=uv;vec4 mvPosition=modelViewMatrix*vec4(position,1.0);gl_Position=projectionMatrix*mvPosition;
    #include <fog_vertex>
    }`,
  fragmentShader:`varying vec2 vUV;uniform vec3 uGlow;uniform sampler2D uSigns;uniform float uLen,uWidth,uCut;
    #include <fog_pars_fragment>
    float noise(vec2 p){return fract(sin(dot(p,vec2(12.9898,78.233)))*43758.5453);}
    float smoothNoise(vec2 p){vec2 i=floor(p),f=fract(p);f=f*f*(3.0-2.0*f);return mix(mix(noise(i),noise(i+vec2(1.0,0.0)),f.x),mix(noise(i+vec2(0.0,1.0)),noise(i+1.0),f.x),f.y);}
    void main(){
      float grain=noise(floor(vUV*vec2(320.0,140.0)));
      float puddle=smoothstep(.2,.8,sin(vUV.y*3.1)*.5+.5);
      float streak=pow(abs(vUV.x-.5)*2.0,2.8)*puddle;
      vec3 c=vec3(.008,.015,.025)*( .8+.2*grain )+uGlow*streak*.11;
      c+=vec3(.026,.048,.057)*pow(max(0.0,1.0-abs(vUV.x-.43)*5.0),4.0)*puddle;
      // Sign light pooled in the puddles: strongest at its own kerb, broken into thin streaks across the road.
      float t=vUV.y/uLen,across=vUV.x*uWidth;
      vec3 near=texture2D(uSigns,vec2(t,.25)).rgb*2.0*exp(-across*2.2)+texture2D(uSigns,vec2(t,.75)).rgb*2.0*exp(-(uWidth-across)*2.2);
      float wet=smoothstep(.4,.62,smoothNoise(vec2(across,vUV.y)*2.3+7.1));
      float lines=vUV.y*30.0,rip=mix(.6,.3+.7*smoothNoise(vec2(lines,vUV.x*2.0)),1.0-smoothstep(.3,.7,fwidth(lines)));
      c+=near*(.25+.75*wet)*rip*.3*uCut;
      gl_FragColor=vec4(c,1.0);
      #include <fog_fragment>
      #include <colorspace_fragment>
    }`
});
// C11.3: sidewalks laid in square tiles (one material per road width), joints fading out with distance.
const sidewalkMats=new Map();
function sidewalkMat(width){
  if(!sidewalkMats.has(width))sidewalkMats.set(width,new THREE.ShaderMaterial({side:THREE.DoubleSide,fog:true,
    uniforms:THREE.UniformsUtils.merge([THREE.UniformsLib.fog,{uBase:{value:col(hex('#263544'))},uWidth:{value:width}}]),
    vertexShader:`varying vec2 vUV;
      #include <fog_pars_vertex>
      void main(){vUV=uv;vec4 mvPosition=modelViewMatrix*vec4(position,1.0);gl_Position=projectionMatrix*mvPosition;
      #include <fog_vertex>
      }`,
    fragmentShader:`varying vec2 vUV;uniform vec3 uBase;uniform float uWidth;
      #include <fog_pars_fragment>
      float tileHash(vec2 p){return fract(sin(dot(p,vec2(12.9898,78.233)))*43758.5453);}
      void main(){
        vec2 t=vec2((vUV.x-.5)*uWidth,vUV.y)/.065,fw=max(fwidth(t),vec2(1e-4)),g=abs(fract(t-.5)-.5)/fw;
        float far=smoothstep(.25,.6,max(fw.x,fw.y));
        float joint=(1.0-min(min(g.x,g.y),1.0))*(1.0-far);
        float shade=mix(.92+.12*tileHash(floor(t)),.98,far);
        gl_FragColor=vec4(uBase*shade*(1.0-.4*joint),1.0);
        #include <fog_fragment>
        #include <colorspace_fragment>
      }`}));
  return sidewalkMats.get(width);
}
// Flat, single-layer quads: one draw is enough (a transparent DoubleSide material otherwise draws twice
// and makes three.js re-resolve its program on every draw of every frame).
const markingMat = new THREE.MeshBasicMaterial({color:col(hex('#b5b7a1')),side:THREE.DoubleSide,forceSinglePass:true,transparent:true,opacity:.38});
const dashMatrices=[],arrowMatrices=[];
for(const [ri,route] of routes.entries()) {
  ribbon(route,route.width+.26,0,-.012,sidewalkMat(route.width+.26));
  ribbon(route,route.width,0,.005,wetStreet(styleOf(route.district).light,route,routeGlow[ri]));
  for(const side of [-1,1]) ribbon(route,.018,side*(route.width/2+.025),.015,new THREE.MeshBasicMaterial({color:col(styleOf(route.district).light),transparent:true,opacity:.42,side:THREE.DoubleSide,forceSinglePass:true}));
  for(let d=0;d<route.length;d+=1.8) {
    const p=sampleRoute(route,d),q=sampleRoute(route,d+.35);
    dummy.rotation.set(-Math.PI/2,0,Math.atan2(q.x-p.x,q.z-p.z));dummy.position.copy(p);dummy.position.y+=.022;dummy.scale.set(1,1,1);dummy.updateMatrix();dashMatrices.push(dummy.matrix.clone());
  }
  // C11.3: a lane arrow in each lane every 7.2 units, pointing the way that lane's traffic drives.
  // Traffic keeps to the right (society.js), so the lane driving forward along the road is the negative offset.
  const lane=route.district==='episodic'?.1:.14;
  for(let d=3.6;d<route.length-.5;d+=7.2) for(const dir of [1,-1]) {
    const p=sampleRoute(route,d,new THREE.Vector3(),-lane*dir),q=sampleRoute(route,d+.3*dir,new THREE.Vector3(),-lane*dir);
    dummy.rotation.set(0,Math.atan2(q.x-p.x,q.z-p.z),0);dummy.position.copy(p);dummy.position.y+=.021;dummy.scale.set(1,1,1);dummy.updateMatrix();arrowMatrices.push(dummy.matrix.clone());
  }
}
const dashes=new THREE.InstancedMesh(new THREE.PlaneGeometry(.025,.32),markingMat,dashMatrices.length);
dashMatrices.forEach((m,i)=>dashes.setMatrixAt(i,m));streetGroup.add(dashes);
const arrowGeometry=new THREE.BufferGeometry();
{const L=.3,w=.02,hw=.06,hl=.11,y=L/2-hl;
  arrowGeometry.setAttribute('position',new THREE.Float32BufferAttribute([-w,0,-L/2,w,0,-L/2,w,0,y, -w,0,-L/2,w,0,y,-w,0,y, -hw,0,y,hw,0,y,0,0,L/2],3));
  arrowGeometry.computeVertexNormals();}
const laneArrows=new THREE.InstancedMesh(arrowGeometry,markingMat,arrowMatrices.length);
arrowMatrices.forEach((m,i)=>laneArrows.setMatrixAt(i,m));streetGroup.add(laneArrows);

// Collision bounds include the overhanging canopy and roof equipment.
const obstacles = nodes.map(n=>({n,minX:n.x-n.w*.57,maxX:n.x+n.w*.57,minZ:-n.y-n.d*.57,maxZ:-n.y+n.d*.57}));
const obstacleGrid=new Map();
for(const b of obstacles) for(let x=Math.floor((b.minX-.3)/2);x<=Math.floor((b.maxX+.3)/2);x++) for(let z=Math.floor((b.minZ-.3)/2);z<=Math.floor((b.maxZ+.3)/2);z++) {
  const key=x*65536+z;if(!obstacleGrid.has(key))obstacleGrid.set(key,[]);obstacleGrid.get(key).push(b);
}
function pointBlocked(p, radius=.14, useTimeline=true) {
  const cells=obstacleGrid.get(Math.floor(p.x/2)*65536+Math.floor(p.z/2));
  if(!cells) return false;
  for(let i=0;i<cells.length;i++) {
    const b=cells[i];
    if((!useTimeline||b.n.state!=='absent') && p.y < plateauZ(b.n.district)+b.n.h*(useTimeline?b.n.rise:1)*1.08+.14 && p.y>plateauZ(b.n.district)-.1 && p.x>b.minX-radius&&p.x<b.maxX+radius&&p.z>b.minZ-radius&&p.z<b.maxZ+radius) return true;
  }
  return false;
}
const sightPoint=new THREE.Vector3();
function clearSight(a,b) {
  const length=a.distanceTo(b),p=sightPoint;
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
const pavementPools=new THREE.InstancedMesh(new THREE.PlaneGeometry(1.5,2.0),new THREE.MeshBasicMaterial({map:glowTexture,color:0xffffff,transparent:true,opacity:.48,blending:THREE.AdditiveBlending,depthWrite:false,side:THREE.DoubleSide,forceSinglePass:true}),lifeLamps.length);
lifeLamps.forEach((s,k)=>{dummy.position.copy(s.p);dummy.position.y+=.025;dummy.rotation.set(-Math.PI/2,0,0);dummy.scale.set(1,1,1);dummy.updateMatrix();pavementPools.setMatrixAt(k,dummy.matrix);pavementPools.setColorAt(k,col(styleOf(s.route.district).light));});streetGroup.add(pavementPools);
const boulevardLamps=instanced('lamp',lifeLamps.length);
lifeLamps.forEach((s,k)=>staticSet(boulevardLamps,k,s.p,[.85,1.05,.85],0,MATTE,styleOf(s.route.district).light,k*.13));
boulevardLamps.mesh.instanceMatrix.needsUpdate=true;
// Existing archive lamps were on the lane center. The new lights sit on sidewalks.
lamps.mesh.visible=false;

const hidden=new THREE.Matrix4().makeScale(.0001,.0001,.0001);
let validEdges=[];

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
// Each projecting sign pools a little of its district colour in the puddles below it (a dark panel with lit text).
const signPoint=new THREE.Vector3();
signs.forEach(s=>{signPoint.setFromMatrixPosition(s.matrix);s.glow=streetGlowSource(signPoint,lin(styleOf(s.n.district).light),.35);});
function updateSigns(){signs.forEach(s=>{s.batch.setMatrixAt(s.slot,s.n.state==='absent'?hidden:s.matrix);setStreetGlow(s.glow,s.n.state==='absent'?0:1);});signBatches.forEach(m=>m.instanceMatrix.needsUpdate=true);}

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
    for(let i=0;i<rainSeeds.length;i++) {const s=rainSeeds[i],y=(s[1]-(now*7)%24+24)%24;
      const k=i*6;rainPositions[k]=anchor.x+s[0];rainPositions[k+1]=y;rainPositions[k+2]=anchor.z+s[2];rainPositions[k+3]=anchor.x+s[0]-.045;rainPositions[k+4]=y+.32;rainPositions[k+5]=anchor.z+s[2]+.025;}rainGeo.attributes.position.needsUpdate=true;
  }
}
