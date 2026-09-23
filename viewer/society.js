// Society is scenery: stages, venues, furniture and vehicles never feed cityMat (B2).
const TAU=Math.PI*2;
const districtLight=d=>col(styleOf(d).light);

// Small props share one material: aPart 0 matte body, 1 accent glow in the instance colour,
// 2 pale panel, 3 white lamp. Accent glow pulses on the kick through the rave uniforms.
function propGeometry(build){const g=new GB();build(g);return g.geometry();}
const propMat=new THREE.ShaderMaterial({fog:true,
  uniforms:THREE.UniformsUtils.merge([THREE.UniformsLib.fog,{uKey:{value:KEY}}]),
  vertexShader:`attribute float aPart;varying float vPart;varying vec3 vColor,vN;
    #include <fog_pars_vertex>
    void main(){vPart=aPart;vColor=instanceColor;vN=normalize(mat3(modelMatrix)*mat3(instanceMatrix)*normal);
      vec4 mvPosition=modelViewMatrix*instanceMatrix*vec4(position,1.0);gl_Position=projectionMatrix*mvPosition;
      #include <fog_vertex>
    }`,
  fragmentShader:`varying float vPart;varying vec3 vColor,vN;uniform vec3 uKey;uniform float uKick,uEnergy,uSourceIntensity,uCut;
    #include <fog_pars_fragment>
    void main(){float d=max(dot(normalize(vN),uKey),0.0);vec3 c=vec3(.035,.042,.052)*(.55+.45*d);
      if(vPart>.5&&vPart<1.5)c=vColor*(.55+.5*uKick*uEnergy*uSourceIntensity)*uCut;
      else if(vPart>1.5&&vPart<2.5)c=mix(vec3(.10,.12,.14),vColor,.25)*(.6+.4*d);
      else if(vPart>2.5)c=vec3(1.0,.93,.80)*1.2;
      gl_FragColor=vec4(c,1.0);
      #include <fog_fragment>
      #include <colorspace_fragment>
    }`});
function propMesh(geometry,count){
  const mesh=new THREE.InstancedMesh(geometry,propMat,count);mesh.frustumCulled=false;
  for(let i=0;i<count;i++)mesh.setColorAt(i,new THREE.Color(1,1,1));
  scene.add(mesh);return mesh;
}

// ------------------------------------------------------------------ stages (C4.2)
const stages=DATA.design.stages.map((s,i)=>{
  const center=W(s.x,s.y,s.z),dir=new THREE.Vector3(Math.cos(s.angle),0,-Math.sin(s.angle));
  // A deck puts its booth on the outer edge; a plaza puts it on the inner edge. The crowd faces it.
  const facing=s.kind==='deck'?dir.clone():dir.clone().negate();
  const booth=center.clone().addScaledVector(facing,s.r*.6);
  return {...s,index:i,center,facing,booth,right:new THREE.Vector3(-facing.z,0,facing.x),yaw:Math.atan2(-facing.x,-facing.z),color:districtLight(s.district)};
});
const stageGroup=new THREE.Group();scene.add(stageGroup);
const deckMat=new THREE.ShaderMaterial({fog:true,uniforms:{},
  vertexShader:`varying vec3 vColor;varying vec2 vTile;varying float vTop,vRim;
    #include <fog_pars_vertex>
    void main(){vColor=instanceColor;float r=length(instanceMatrix[0].xyz);vTile=position.xz*r/.2;
      vTop=step(.5,normal.y);vRim=position.y;
      vec4 mvPosition=modelViewMatrix*instanceMatrix*vec4(position,1.0);gl_Position=projectionMatrix*mvPosition;
      #include <fog_vertex>
    }`,
  fragmentShader:`varying vec3 vColor;varying vec2 vTile;varying float vTop,vRim;uniform float uBeat,uKick,uEnergy,uSourceIntensity,uCut;
    #include <fog_pars_fragment>
    float hash(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453);}
    void main(){vec3 c;
      if(vTop>.5){vec2 cell=floor(vTile),f=fract(vTile);float grout=step(.07,f.x)*step(.07,f.y)*step(f.x,.93)*step(f.y,.93);
        float b=floor(uBeat),ph=fract(uBeat),mode=mod(floor(uBeat/16.0),3.0),on;
        if(mode<.5)on=mod(cell.x+cell.y+b,2.0);
        else if(mode<1.5)on=1.0-smoothstep(0.0,1.6,abs(length(cell)-ph*9.0));
        else on=step(.7,hash(cell+b));
        float glow=on*(.3+.7*(1.0-ph))*grout;
        c=vec3(.010,.013,.018)+vColor*(glow*(.35+.25*uKick)*uEnergy*uSourceIntensity+.018*grout)*uCut;
      } else c=vec3(.02,.025,.032)+vColor*smoothstep(-.02,0.0,vRim)*.55*uCut;
      gl_FragColor=vec4(c,1.0);
      #include <fog_fragment>
      #include <colorspace_fragment>
    }`});
const decks=new THREE.InstancedMesh(new THREE.CylinderGeometry(1,1,.12,48,1,false).translate(0,-.06,0),deckMat,stages.length);
const pylons=propMesh(propGeometry(g=>g.prism(CIRC,0,1,1,.7,0,0)),stages.length);
const booths=propMesh(propGeometry(g=>{g.box(-.42,0,-.14,.42,.27,.14,{px:0,nx:0,py:2,ny:0,pz:0,nz:0});g.box(-.42,.2,.141,.42,.235,.15,1);g.box(-.3,.27,-.1,-.05,.29,.08,0);g.box(.05,.27,-.1,.3,.29,.08,0);}),stages.length);
const speakers=propMesh(propGeometry(g=>{g.box(-.11,0,-.1,.11,.46,.1,0);g.box(-.07,.28,.1,.07,.42,.105,2);g.box(-.05,.07,.1,.05,.2,.105,2);}),stages.length*4);
const trusses=propMesh(propGeometry(g=>{g.box(-.95,0,-.03,-.89,1.25,.03,0);g.box(.89,0,-.03,.95,1.25,.03,0);g.box(-.95,1.2,-.035,.95,1.26,.035,0);g.box(-.95,1.19,-.04,.95,1.2,.04,1);}),stages.length);
for(const mesh of [decks,pylons,booths,speakers,trusses]){mesh.frustumCulled=false;stageGroup.add(mesh);}
const wallGeometry=new THREE.PlaneGeometry(1,1);
wallGeometry.setAttribute('aMode',new THREE.InstancedBufferAttribute(new Float32Array(stages.map((s,i)=>i%4)),1));
wallGeometry.setAttribute('aCell',new THREE.InstancedBufferAttribute(new Float32Array(stages.map((s,i)=>i%7)),1));
let stageWalls=null,stageBeams=null;
const BEAMS_PER_STAGE=4,stageBeamYaw=new Float32Array(stages.length*BEAMS_PER_STAGE);
// String lights over the Archive sound system and the Hills block party.
const bulbStages=stages.filter(s=>s.district==='episodic'||s.district==='jhon');
const bulbPositions=[],bulbSeeds=[];
for(const s of bulbStages){
  const right=new THREE.Vector3(-s.facing.z,0,s.facing.x);
  for(let strand=0;strand<3;strand++){
    const along=(strand-1)*s.r*.5,a=s.center.clone().addScaledVector(s.facing,along).addScaledVector(right,-s.r*.95),b=s.center.clone().addScaledVector(s.facing,along).addScaledVector(right,s.r*.95);
    for(let k=0;k<=24;k++){const t=k/24,p=a.clone().lerp(b,t);p.y=s.z+1.05-Math.sin(t*Math.PI)*.28;bulbPositions.push(p.x,p.y,p.z);bulbSeeds.push((k*7+strand*3)%11/11);}
  }
}
const bulbGeometry=new THREE.BufferGeometry();bulbGeometry.setAttribute('position',new THREE.Float32BufferAttribute(bulbPositions,3));bulbGeometry.setAttribute('aSeed',new THREE.Float32BufferAttribute(bulbSeeds,1));
let bulbs=null;
// The Works gets a loading-bay door frame, the Yards hoardings, the Dome a wire dome.
const doorFrames=propMesh(propGeometry(g=>{g.box(-1.1,0,-.05,-.95,1.5,.05,0);g.box(.95,0,-.05,1.1,1.5,.05,0);g.box(-1.1,1.4,-.05,1.1,1.55,.05,0);g.box(-.95,1.36,.05,.95,1.4,.06,1);}),1);
const hoardings=propMesh(propGeometry(g=>{for(let k=0;k<5;k++)g.box(-.6+k*.24,0,-.02,-.6+k*.24+.24,.42,.02,k%2?2:1);}),2);
const domeWire=new THREE.LineSegments(new THREE.WireframeGeometry(new THREE.SphereGeometry(1,14,6,0,TAU,0,Math.PI/2)),new THREE.LineBasicMaterial({color:districtLight('onebrain'),transparent:true,opacity:.35,blending:THREE.AdditiveBlending,depthWrite:false}));
stageGroup.add(doorFrames,hoardings,domeWire);

function placeStages(){
  const m=new THREE.Matrix4(),q=new THREE.Quaternion(),e=new THREE.Euler(),v=new THREE.Vector3(),sc=new THREE.Vector3();
  const set=(mesh,i,pos,yaw,sx,sy,sz)=>{e.set(0,yaw,0);q.setFromEuler(e);sc.set(sx,sy,sz);m.compose(pos,q,sc);mesh.setMatrixAt(i,m);};
  stages.forEach((s,i)=>{
    const flat=s.kind==='plaza';
    set(decks,i,s.center,0,s.r,flat?.25:1,s.r);decks.setColorAt(i,s.color);
    v.copy(s.center);v.y=-.02;set(pylons,i,v,0,flat?0:.34,Math.max(.001,s.z-.14),flat?0:.34);
    set(booths,i,s.booth,s.yaw,1,1,1);booths.setColorAt(i,s.color);
    const right=new THREE.Vector3(-s.facing.z,0,s.facing.x);
    for(let k=0;k<4;k++){v.copy(s.booth).addScaledVector(right,(k<2?-1:1)*(.62+(k%2)*.26)).addScaledVector(s.facing,.05);
      set(speakers,i*4+k,v,s.yaw,1,s.district==='episodic'?1.5:1,1);speakers.setColorAt(i*4+k,s.color);}
    v.copy(s.booth).addScaledVector(s.facing,.34);set(trusses,i,v,s.yaw,1,1,1);trusses.setColorAt(i,s.color);
  });
  for(const mesh of [decks,pylons,booths,speakers,trusses]){mesh.instanceMatrix.needsUpdate=true;if(mesh.instanceColor)mesh.instanceColor.needsUpdate=true;}
  const works=stages.find(s=>s.district==='procedural');
  if(works){v.copy(works.booth).addScaledVector(works.facing,.5);set(doorFrames,0,v,works.yaw,1,1,1);doorFrames.setColorAt(0,works.color);}
  const yards=stages.find(s=>s.district==='prospective');
  if(yards){const right=new THREE.Vector3(-yards.facing.z,0,yards.facing.x);
    for(let k=0;k<2;k++){v.copy(yards.center).addScaledVector(right,(k?1:-1)*yards.r*.92);set(hoardings,k,v,yards.yaw+Math.PI/2,1,1,1);hoardings.setColorAt(k,yards.color);}}
  const dome=stages.find(s=>s.district==='onebrain');
  if(dome){domeWire.position.copy(dome.center);domeWire.scale.setScalar(dome.r*.96);}
  for(const mesh of [doorFrames,hoardings]){mesh.instanceMatrix.needsUpdate=true;mesh.instanceColor.needsUpdate=true;}
}
placeStages();

// Walls, beams and bulbs share the rave uniforms, so they are built once rave-light exists.
function buildStageLights(){
  Object.assign(deckMat.uniforms,THREE.UniformsUtils.clone(THREE.UniformsLib.fog),{uBeat:rave.uniforms.uBeat,uKick:rave.uniforms.uKick,uEnergy:rave.uniforms.uEnergy,uSourceIntensity:rave.uniforms.uSourceIntensity,uCut:rave.uniforms.uCut});
  Object.assign(propMat.uniforms,{uKick:rave.uniforms.uKick,uEnergy:rave.uniforms.uEnergy,uSourceIntensity:rave.uniforms.uSourceIntensity,uCut:rave.uniforms.uCut});
  stageWalls=new THREE.InstancedMesh(wallGeometry,rave.screens.material,stages.length);stageWalls.frustumCulled=false;
  const m=new THREE.Matrix4(),q=new THREE.Quaternion(),e=new THREE.Euler(),v=new THREE.Vector3(),sc=new THREE.Vector3(1.6,.72,1);
  stages.forEach((s,i)=>{v.copy(s.booth).addScaledVector(s.facing,.36);v.y+=.72;e.set(0,s.yaw,0);q.setFromEuler(e);m.compose(v,q,sc);stageWalls.setMatrixAt(i,m);});
  stageGroup.add(stageWalls);
  stageBeams=new THREE.InstancedMesh(new THREE.CylinderGeometry(.006,.055,1,6,1,true).translate(0,.5,0),rave.lasers.material,stages.length*BEAMS_PER_STAGE);
  stageBeams.instanceMatrix.setUsage(THREE.DynamicDrawUsage);stageBeams.frustumCulled=false;stageGroup.add(stageBeams);
  bulbs=new THREE.Points(bulbGeometry,new THREE.ShaderMaterial({uniforms:rave.uniforms,transparent:true,depthWrite:false,blending:THREE.AdditiveBlending,
    vertexShader:`attribute float aSeed;uniform float uBeat;varying float vOn;void main(){vOn=.55+.45*step(.5,fract(aSeed+floor(uBeat)*.37));vec4 mv=modelViewMatrix*vec4(position,1.0);gl_Position=projectionMatrix*mv;gl_PointSize=clamp(60.0/-mv.z,1.5,6.0);}`,
    fragmentShader:`varying float vOn;uniform float uCut;void main(){float r=length(gl_PointCoord-.5);if(r>.5)discard;gl_FragColor=vec4(vec3(1.0,.78,.45)*vOn*uCut,1.0-r*2.0);
      #include <colorspace_fragment>
    }`}));
  bulbs.frustumCulled=false;stageGroup.add(bulbs);
}

// Two slow sky beams per stage in its district colour, so every party reads from the overview.
const skyBeamMat=new THREE.ShaderMaterial({transparent:true,blending:THREE.AdditiveBlending,depthWrite:false,side:THREE.DoubleSide,forceSinglePass:true,fog:true,
  uniforms:THREE.UniformsUtils.merge([THREE.UniformsLib.fog,{uEnergy:{value:1},uCut:{value:1},uKick:{value:0}}]),
  vertexShader:`varying float vHeight,vEdge;varying vec3 vColor;
    #include <fog_pars_vertex>
    void main(){vHeight=position.y;vEdge=uv.x;vColor=instanceColor;vec4 mvPosition=modelViewMatrix*instanceMatrix*vec4(position,1.0);gl_Position=projectionMatrix*mvPosition;
      #include <fog_vertex>
    }`,
  fragmentShader:`varying float vHeight,vEdge;varying vec3 vColor;uniform float uEnergy,uCut,uKick;
    #include <fog_pars_fragment>
    void main(){float edge=pow(max(0.0,sin(vEdge*3.14159265)),1.6);gl_FragColor=vec4(vColor,edge*pow(1.0-vHeight,1.4)*(.16+.05*uKick)*uEnergy*uCut);
      #include <fog_fragment>
      #include <colorspace_fragment>
    }`});
const skyBeams=new THREE.InstancedMesh(new THREE.CylinderGeometry(.9,.07,1,10,1,true).translate(0,.5,0),skyBeamMat,stages.length*2);
skyBeams.instanceMatrix.setUsage(THREE.DynamicDrawUsage);skyBeams.frustumCulled=false;
stages.forEach((s,i)=>{skyBeams.setColorAt(i*2,s.color);skyBeams.setColorAt(i*2+1,s.color);});stageGroup.add(skyBeams);
buildStageLights();
const stageBeamDummy=new THREE.Object3D(),stageUp=new THREE.Vector3(0,1,0),stageDirection=new THREE.Vector3();
function updateStages(){
  if(!stageBeams)return;
  const b=beat.now(),t=reduced?0:b.totalBeats,level=tier.current===1?2:BEAMS_PER_STAGE;
  for(let i=0;i<stages.length;i++){
    const s=stages[i],right=s.right;
    for(let k=0;k<BEAMS_PER_STAGE;k++){
      const slot=i*BEAMS_PER_STAGE+k,x=-.6+k*.4;
      stageBeamDummy.position.copy(s.booth).addScaledVector(s.facing,.3).addScaledVector(right,x);stageBeamDummy.position.y=s.z+1.18;
      const sweep=Math.sin(t*Math.PI/4+k*1.3+i)*.7,dip=.95+.25*Math.sin(t*Math.PI/2+k);
      stageDirection.copy(s.facing).multiplyScalar(-Math.sin(dip)).addScaledVector(right,Math.sin(sweep)*.8).setY(-Math.cos(dip)*.9).normalize();
      stageBeamDummy.quaternion.setFromUnitVectors(stageUp,stageDirection);
      const on=k<level?1:0;stageBeamDummy.scale.set(on,2.6*on+.0001,on);stageBeamDummy.updateMatrix();stageBeams.setMatrixAt(slot,stageBeamDummy.matrix);
    }
  }
  stageBeams.instanceMatrix.needsUpdate=true;
  skyBeamMat.uniforms.uEnergy.value=rave.uniforms.uEnergy.value*rave.uniforms.uSourceIntensity.value;skyBeamMat.uniforms.uCut.value=rave.uniforms.uCut.value;skyBeamMat.uniforms.uKick.value=rave.uniforms.uKick.value;
  for(let i=0;i<stages.length;i++){const s=stages[i];
    for(let k=0;k<2;k++){const a=(k?1:-1)*(.22+.12*Math.sin(t*Math.PI/8+i*1.7+k));
      stageBeamDummy.position.copy(s.booth).addScaledVector(s.facing,.4);stageBeamDummy.position.y=s.z+1.3;
      stageDirection.copy(s.right).multiplyScalar(Math.sin(a)).addScaledVector(s.facing,.18).setY(Math.cos(a)).normalize();
      stageBeamDummy.quaternion.setFromUnitVectors(stageUp,stageDirection);stageBeamDummy.scale.set(1,26,1);stageBeamDummy.updateMatrix();skyBeams.setMatrixAt(i*2+k,stageBeamDummy.matrix);}
  }
  skyBeams.instanceMatrix.needsUpdate=true;
}

// ------------------------------------------------------------------ traffic (vehicle types arrive in V3)
const CARS = 118;
const cars=instanced('car',CARS),carState=[],carRnd=mulberry(4242);
for(let k=0;k<CARS;k++) {
  const route=routes[k%routes.length];
  carState.push({route:k%routes.length,distance:carRnd()*route.length,dir:k%2?1:-1,speed:.75+carRnd()*.8,on:true,pos:new THREE.Vector3(),heading:new THREE.Vector3()});
  staticSet(cars,k,new THREE.Vector3(0,-50,0),[.15,.13,.34],0,hex(k%4===0?'#826850':'#3b5264'),WHITE,carRnd());
}
const carPoint=new THREE.Vector3(),carAhead=new THREE.Vector3();
function updateCars(dt) {
  const p=carPoint,q=carAhead;
  for(let k=0;k<CARS;k++) {
    const c=carState[k],route=routes[c.route];c.distance+=dt*c.speed*c.dir;
    sampleRoute(route,c.distance,p,.12*c.dir);sampleRoute(route,c.distance+.2*c.dir,q,.12*c.dir);
    c.pos.copy(p);c.heading.subVectors(q,p).normalize();c.on=k<cars.mesh.count;
    dummy.position.copy(p);dummy.position.y+=.028;dummy.rotation.set(0,Math.atan2(c.heading.x,c.heading.z),0);dummy.scale.set(.15,.13,.34);dummy.updateMatrix();
    cars.mesh.setMatrixAt(k,c.on?dummy.matrix:hidden);
  }
  cars.mesh.instanceMatrix.needsUpdate=true;
}

const venues={items:[],stages:stages.map(s=>({district:s.district,name:s.name,kind:s.kind,x:s.center.x,z:s.center.z,up:s.center.y,r:s.r,capacity:s.capacity})),update(){}};
