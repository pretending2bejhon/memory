// Arc-length streets are shared with the Blender scene. Links remain a separate layer.
const phone = Math.min(window.innerWidth, window.innerHeight) < 720;
const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
// A route with a shared stretch (the Archive east rim road, C6.2, which runs back to its start on Memory
// boulevard's east side) is only its own stretch here: an open street that never draws or runs the
// boulevard's asphalt twice. It keeps its own width and the clearance of its own stretch.
const routes = DATA.design.routes.map(r => {
  let own = r.points;
  if (r.shared) { let s = 0; own = [r.points[0]];
    for (let i = 1; i < r.points.length; i++) { s += Math.hypot(r.points[i][0]-r.points[i-1][0], r.points[i][1]-r.points[i-1][1]); if (s > r.shared[0].from + 1e-4) break; own.push(r.points[i]); } }
  const open = Boolean(r.shared), points = own.map(p => W(p[0], p[1], r.z));
  const lengths = [0];
  for (let i = 1; i <= points.length - (open ? 1 : 0); i++) lengths.push(lengths[i-1]+points[i-1].distanceTo(points[i%points.length]));
  // Unit side normal per segment, computed once, so sampling an offset lane allocates nothing. An open
  // route's last entry (the closing segment it never drives) is never read.
  const sideX = new Float64Array(points.length), sideZ = new Float64Array(points.length);
  for (let i = 0; i < points.length; i++) { const a=points[i], b=points[(i+1)%points.length], dx=b.x-a.x, dz=b.z-a.z, l=Math.hypot(dx,dz)||1; sideX[i]=dz/l; sideZ[i]=dx/l; }
  return {...r, points, lengths, sideX, sideZ, length:lengths.at(-1), open, width:r.width ?? (r.district === 'episodic' ? .54 : .88),
    clearance:open ? r.clearanceOwn : r.clearance};
});
// An open route folds back at its ends, so anything moving along it turns round there.
function sampleRoute(route, distance, out = new THREE.Vector3(), offset = 0) {
  ROUTE_ARGS[0] = distance; ROUTE_ARGS[1] = offset;
  return sampleRouteArgs(route, out);
}
// The same sampling with the distance and the lane offset read from ROUTE_ARGS: a per-frame caller
// passes no double, so nothing is boxed when the optimizer does not inline the call.
const ROUTE_ARGS = new Float64Array(2);
function sampleRouteArgs(route, out) {
  const distance = ROUTE_ARGS[0], offset = ROUTE_ARGS[1];
  let s;
  if (route.open) { const L2 = 2*route.length, f = ((distance % L2)+L2)%L2; s = f > route.length ? L2-f : f; }
  else s = ((distance % route.length)+route.length)%route.length;
  let lo=0, hi=route.points.length-(route.open ? 1 : 0);
  while(lo+1<hi) { const mid=(lo+hi)>>1; if(route.lengths[mid]<=s) lo=mid; else hi=mid; }
  const a=route.points[lo], b=route.points[(lo+1)%route.points.length];
  out.lerpVectors(a,b,(s-route.lengths[lo])/(route.lengths[lo+1]-route.lengths[lo]));
  // A path built elsewhere (a bridge's lamp line, a walker's bridge path) has no side table: its normal
  // is computed here, as every route's was before the table.
  if(offset) { const sx=route.sideX;
    if(sx) { out.x+=sx[lo]*offset; out.z-=route.sideZ[lo]*offset; }
    else { const dx=b.x-a.x,dz=b.z-a.z,l=Math.hypot(dx,dz); out.x+=dz/l*offset; out.z-=dx/l*offset; } }
  return out;
}
const streetGroup = new THREE.Group(); scene.add(streetGroup);
// width and offset may vary along the road (functions of d); keep(d, offset) drops a segment.
function ribbon(route, width, offset, height, material, keep) {
  const pos=[], uv=[], indices=[], last=route.lengths.length-1;
  const widthAt=typeof width==='function'?width:()=>width, offsetAt=typeof offset==='function'?offset:()=>offset;
  for(let i=0;i<=last;i++) {
    const d=route.lengths[i],w=widthAt(d),o=offsetAt(d);
    for(const side of [-1,1]) { const p=sampleRoute(route,d,new THREE.Vector3(),o+side*w/2); pos.push(p.x,p.y+height,p.z); uv.push(side===-1?0:1,d); }
    const mid=i<last?(d+route.lengths[i+1])/2:0;
    if(i<last&&(!keep||keep(mid,offsetAt(mid)))) { const j=i*2; indices.push(j,j+2,j+1,j+1,j+2,j+3); }
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
    if(route.open&&best===pts.length-1)best--;
    const a=pts[best],b=pts[(best+1)%pts.length],dx=b.x-a.x,dz=b.z-a.z,l=Math.hypot(dx,dz)||1;
    const lateral=((p.x-a.x)*dz-(p.z-a.z)*dx)/l,along=((p.x-a.x)*dx+(p.z-a.z)*dz)/l,reach=Math.abs(lateral)-route.width/2;
    if(reach>1.5)return;
    const G=routeGlow[ri],s=route.lengths[best]+along,w=weight*(1-Math.max(0,reach-.3)/1.2),row=lateral>0?1:0;
    for(let c=Math.floor((s-.4)/route.length*G.bins);c<=Math.ceil((s+.4)/route.length*G.bins);c++){
      const k=w*Math.max(0,1-Math.abs((c+.5)/G.bins*route.length-s)/.4);
      if(k>0&&(!route.open||(c>=0&&c<G.bins)))taps.push(ri,((c%G.bins)+G.bins)%G.bins,row,k);
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
// Flat transparent decals render in one pass: three.js draws a transparent DoubleSide material twice
// (back then front) and flags it for a program lookup each time, which allocated about 16 MB/s of
// garbage from the street markings alone (V4a trace). A flat ribbon looks the same either way.
const markingMat = new THREE.MeshBasicMaterial({color:col(hex('#b5b7a1')),side:THREE.DoubleSide,transparent:true,opacity:.38,forceSinglePass:true});
// Junctions (C6.2 forks now, bridge tees next): an open route widens from the road it forks off to its
// own width over its first and last 1.2 units, sits 4 mm lower so the through road's surface wins
// where they overlap, and no road paints an edge line, dash or arrow, or stands a lamp, inside another
// road's carriageway.
const forkWidth=route=>route.open&&route.shared?routes[route.shared[0].route].width:route.width;
function drawnWidth(route,d){
  if(!route.open)return route.width;
  const e=Math.min(d,route.length-d),u=Math.min(1,Math.max(0,e/1.2)),k=u*u*(3-2*u),w0=forkWidth(route);
  return w0+(route.width-w0)*k;
}
const carriageGrid=new Map(),carriageSegs=[];
routes.forEach((route,ri)=>{const pts=route.points,n=pts.length-(route.open?1:0);
  for(let i=0;i<n;i++){const a=pts[i],b=pts[(i+1)%pts.length],k=carriageSegs.length;carriageSegs.push({ri,a,b,s0:route.lengths[i],s1:route.lengths[i+1]});
    for(let x=Math.floor((Math.min(a.x,b.x)-.6)/2);x<=Math.floor((Math.max(a.x,b.x)+.6)/2);x++)
      for(let z=Math.floor((Math.min(a.z,b.z)-.6)/2);z<=Math.floor((Math.max(a.z,b.z)+.6)/2);z++){const c=x*65536+z;if(!carriageGrid.has(c))carriageGrid.set(c,[]);carriageGrid.get(c).push(k);}}});
// Bridge tees and the Archive rim links (roads.js draws both). A bridge's mouth is its stub outside the
// ring's carriageway plus the two fillet corners out to the curb sidewalk's outer edge; a link is a fork,
// like the rim road: it leaves an avenue at the start of its corner and runs along the rim to the next
// avenue, so its whole carriageway counts. No road paints an edge line, dash or arrow, or stands a lamp,
// inside either; a ring keeps its centre dashes and lane arrows at a tee, since the mouth starts at its kerb.
const roadMouths=[],roadLinks=[];
for(const b of DATA.design.bridges||[]){const P=b.points,n=P.length;
  b.ends.forEach((e,k)=>{const a=k?P[n-1]:P[0],c=k?P[n-2]:P[1],l=Math.hypot(c[0]-a[0],c[1]-a[1])||1;
    roadMouths.push({x:a[0],y:a[1],z:e.z,ux:(c[0]-a[0])/l,uy:(c[1]-a[1])/l,s0:.44,s1:Math.max(...e.fillets.map(f=>f.bridgeS))+.05,half:.44,fillets:e.fillets});});}
for(const st of DATA.design.streets||[]){const P=st.points;
  roadLinks.push({P,z:st.z,half:st.width/2,x0:Math.min(...P.map(q=>q[0]))-.6,x1:Math.max(...P.map(q=>q[0]))+.6,y0:Math.min(...P.map(q=>q[1]))-.6,y1:Math.max(...P.map(q=>q[1]))+.6});}
function inRoadMouth(p,margin=0){
  const x=p.x,y=-p.z;
  for(const m of roadMouths){if(Math.abs(p.y-m.z)>.3)continue;const dx=x-m.x,dy=y-m.y;if(dx*dx+dy*dy>9)continue;
    const s=dx*m.ux+dy*m.uy,lat=Math.abs(dx*m.uy-dy*m.ux);
    if(s>=m.s0-margin&&s<=m.s1&&lat<m.half+margin)return true;
    for(const f of m.fillets){const fx=x-f.cx,fy=y-f.cy,d=Math.hypot(fx,fy);if(d<f.r-.13-margin||d>f.r+.44)continue;
      const span=f.a1-f.a0,rel=((Math.atan2(fy,fx)*180/Math.PI-f.a0)%360+540)%360-180;if(rel/span>0&&rel/span<1)return true;}}
  for(const k of roadLinks){if(Math.abs(p.y-k.z)>.3||x<k.x0||x>k.x1||y<k.y0||y>k.y1)continue;
    for(let i=0;i+1<k.P.length;i++){const a=k.P[i],b=k.P[i+1],dx=b[0]-a[0],dy=b[1]-a[1],l2=dx*dx+dy*dy,t=l2?Math.max(0,Math.min(1,((x-a[0])*dx+(y-a[1])*dy)/l2)):0;
      if(Math.hypot(x-a[0]-dx*t,y-a[1]-dy*t)<k.half+margin)return true;}}
  return false;
}
function inOtherCarriageway(p,own,margin=0){
  if(inRoadMouth(p,margin))return true;
  const cell=carriageGrid.get(Math.floor(p.x/2)*65536+Math.floor(p.z/2));if(!cell)return false;
  for(const k of cell){const g=carriageSegs[k];if(g.ri===own)continue;
    const dx=g.b.x-g.a.x,dz=g.b.z-g.a.z,l2=dx*dx+dz*dz,t=l2?Math.max(0,Math.min(1,((p.x-g.a.x)*dx+(p.z-g.a.z)*dz)/l2)):0;
    if(Math.hypot(p.x-g.a.x-dx*t,p.z-g.a.z-dz*t)<drawnWidth(routes[g.ri],g.s0+(g.s1-g.s0)*t)/2+margin)return true;}
  return false;
}
const clipPoint=new THREE.Vector3();
const dashMatrices=[],arrowMatrices=[];
for(const [ri,route] of routes.entries()) {
  const drop=route.open?-.004:0,w=d=>drawnWidth(route,d),clear=(d,o)=>!inOtherCarriageway(sampleRoute(route,d,clipPoint,o),ri,-.005);
  ribbon(route,d=>w(d)+.26,0,-.012+drop,sidewalkMat(route.width+.26));
  ribbon(route,w,0,.005+drop,wetStreet(styleOf(route.district).light,route,routeGlow[ri]));
  for(const side of [-1,1]) ribbon(route,.018,d=>side*(w(d)/2+.025),.015+drop,new THREE.MeshBasicMaterial({color:col(styleOf(route.district).light),transparent:true,opacity:.42,side:THREE.DoubleSide,forceSinglePass:true}),clear);
  for(let d=0;d<route.length;d+=1.8) {
    if(!clear(d,0)||!clear(d+.35,0))continue;
    const p=sampleRoute(route,d),q=sampleRoute(route,d+.35);
    dummy.rotation.set(-Math.PI/2,0,Math.atan2(q.x-p.x,q.z-p.z));dummy.position.copy(p);dummy.position.y+=.022;dummy.scale.set(1,1,1);dummy.updateMatrix();dashMatrices.push(dummy.matrix.clone());
  }
  // C11.3: a lane arrow in each lane every 7.2 units, pointing the way that lane's traffic drives.
  // Traffic keeps to the right (society.js), so the lane driving forward along the road is the negative offset.
  const lane=route.width<.6?.1:.14;
  for(let d=3.6;d<route.length-.5;d+=7.2) for(const dir of [1,-1]) {
    if(!clear(d,-lane*dir)||!clear(d+.3*dir,-lane*dir))continue;
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
  if(pointBlocked(new THREE.Vector3(p.x,p.y+.7,p.z),.06,false)||inOtherCarriageway(p,ri,.06)) continue;
  // At a fork the through road's lamp already lights the corner.
  if(route.open&&lifeLamps.some(l=>l.p.distanceTo(p)<1)) continue;
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
