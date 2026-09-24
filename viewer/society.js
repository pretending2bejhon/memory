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
    // The per-beat twinkle is a reactive amplitude: its depth follows the Lights level, the view and sound off (C12.2).
    vertexShader:`attribute float aSeed;uniform float uBeat,uEnergy,uSourceIntensity;varying float vOn;void main(){vOn=1.0-.45*min(1.0,uEnergy*uSourceIntensity)*(1.0-step(.5,fract(aSeed+floor(uBeat)*.37)));vec4 mv=modelViewMatrix*vec4(position,1.0);gl_Position=projectionMatrix*mv;gl_PointSize=clamp(60.0/-mv.z,1.5,6.0);}`,
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

// ------------------------------------------------------------------ venues (C4.3, C4.4, C4.6, C4.7)
// Names are invented common nouns (appendix G plus a few in the same spirit): no people, no brands.
const VENUE_NAMES={
  bar:['Bar Luciérnaga','Bar Sereno','La Terraza','Cantina Neón','La Última Ronda','Night Owl','The Late Shift','Salón Estéreo','Bar Aguacero','La Gotera','Bar Neblina','El Andén','La Azotea','Bar Tranvía','Last Call','Bar Candela','El Zaguán','Bar Relámpago','El Tocadiscos','El Farol'],
  club:['Warehouse 140','Sótano Catorce','Club Umbral','Onda Larga','Kilohercio','Estática','Fase','Frecuencia Baja','Sala Oscura','Club Voltaje','Galpón 12','Ruido Blanco','Club Eco','Onda Corta','Pulso Lento'],
  food:['Arepas 24H','Empanadas La Esquina','Parrilla Nocturna','Ramen Lluvia','Pizza al Paso','Asadero El Carbón','Fritanga La Ronda','Sancocho de Medianoche','Perros de la Noche','Arepas La Brasa','Chuzos El Fogón','Mazorcas Asadas','Buñuelos de Esquina','Patacón Nocturno','Salchipapas Luna','Tacos La Lluvia','Obleas La Ronda'],
  cafe:['Café Tinto','Tinto y Tinta','Late Café','Café Marea','Café Biblioteca','Café Niebla','Café Andén','Café Lluvia','Tinto 24H','Café Papel','Café Vela','Café Neón','Café Madrugada'],
  tienda:['Tienda La Esquina','Tienda Mi Barrio','Minimercado 24/7','Tienda El Parche','Tienda La Esquinita','Tienda El Refugio','Granero La Cuadra','Tienda La Ventana','Tienda El Mirador','Tienda Luna Llena','Tienda El Callejón','Tienda La Ceiba','Tienda El Surtido','Granero El Mercado'],
  record:['Discos Surco','Vinilo Nocturno','Crate Diggers','Discos Aguja','Discos Eco'],tattoo:['Tinta Neón','Tinta Negra','Piel y Tinta'],
  barber:['Barbería Fade','Corte Fino','Barbería La Navaja','Barbería Nocturna'],arcade:['Arcade 8 Bits','Recreativas','Arcade Pixel'],
  laundromat:['Lavandería 24h'],pharmacy:['Farmacia de Turno'],bookshop:['Librería Abierta','Libros de Noche','Librería El Margen'],
  bakery:['Panadería El Horno'],beachbar:['Marea Alta'],hotel:['Hotel Tránsito']};
// The single-venue districts take the names C4.6 gives them.
const SINGLE_NAMES={branding:'Discos Surco',onebrain:'Arcade 8 Bits',reef:'Marea Alta',inbox:'Hotel Tránsito',core:'Café Tinto'};
const VENUE_COLORS={bar:'#ff8a3d',club:'#ff3dd2',food:'#ffc83d',cafe:'#ffe2b0',tienda:'#ff5a3d',record:'#b26bff',tattoo:'#ff3d5a',barber:'#4fb4ff',arcade:'#39ff88',
  laundromat:'#5ee6ff',pharmacy:'#4dff9a',bookshop:'#ffd68a',bakery:'#ffb060',beachbar:'#3dffd8',hotel:'#f4f1ec'};
const VENUE_WORD={bar:'bar',club:'club',food:'food counter',cafe:'café',tienda:'tienda',record:'record store',tattoo:'tattoo studio',barber:'barber',arcade:'arcade',
  laundromat:'laundromat',pharmacy:'24h pharmacy',bookshop:'bookshop',bakery:'bakery',beachbar:'beach bar',hotel:'hotel'};
const GRAFFITI_WORDS=['VAULT','NOCHE','140','RECUERDA','BAILA','CITY'];
const VENUE_PLINTH=new Set(['box','shop','tower','slab','spire','sign','stepped']),VENUE_CANOPY=new Set(['box','shop','slab','sign']);
const venueNamesUsed=new Set(Object.values(SINGLE_NAMES)),venueDistrictsSeen=new Set();
const venueList=DATA.design.venues.map((v,i)=>{
  let name=SINGLE_NAMES[v.district]&&!venueDistrictsSeen.has(v.district)?SINGLE_NAMES[v.district]:null;
  venueDistrictsSeen.add(v.district);
  if(!name){const list=VENUE_NAMES[v.type]||VENUE_NAMES.bar;name=list.find(x=>!venueNamesUsed.has(x))||list[i%list.length];venueNamesUsed.add(name);}
  const host=byId.get(v.host),normal=new THREE.Vector3(v.face[0],0,-v.face[1]),z=plateauZ(v.district);
  // design.py puts the face at half the footprint. A hex pavilion's flat side sits further in; a round
  // wall (or a hex apex) curves away, so those storefronts are narrower.
  const across=v.face[0]?host.w:host.d,curved=host.kind==='cyl'||host.kind==='dome'||(host.kind==='hex'&&!v.face[0]);
  const inset=host.kind==='hex'&&v.face[0]?across*(.5-.433):0;
  const face=W(v.x,v.y,z).addScaledVector(normal,-inset);
  // Blocks, shops and towers stand on a pavement plinth 1.1 wide; the band sits just in front of it.
  // Box, shop, slab and sign kinds also carry a shop canopy ring 1.12 wide at 0.14 of their height; the band
  // clears it too, since design.py rounds the face position to the millimetre.
  const front=VENUE_CANOPY.has(host.kind)?across*.06+.01:VENUE_PLINTH.has(host.kind)?across*.05+.008:.012;
  return {...v,index:i,name,word:VENUE_WORD[v.type]||v.type,host,normal,right:new THREE.Vector3(-normal.z,0,normal.x),face,front,z,
    yaw:Math.atan2(normal.x,normal.z),width:curved?Math.min(v.length*.5,.42):Math.min(v.length*.86,.62),
    // Distance from the face to where a standing person clears the footprint check (0.57 overhang).
    stand:across*.07+inset+.1,color:new THREE.Color(VENUE_COLORS[v.type]||'#ffffff'),pulse:v.type==='bar'||v.type==='club'?1:0,
    open:0,present:false,state:'absent',grow:0,drawn:-1};
});
const venueByHost=new Map(venueList.map(v=>[v.host.id,v]));
// Each venue's neon sign also pools its colour in the puddles of the road in front of it (C11.3); the
// streaks follow the sign's state and dim with the rave cut like the sign itself.
for(const v of venueList){const p=v.face.clone().addScaledVector(v.normal,v.front+.018);v.glow=streetGlowSource(p,[v.color.r,v.color.g,v.color.b],1);}
streetGroup.traverse(o=>{if(o.material&&o.material.uniforms&&o.material.uniforms.uSigns)o.material.uniforms.uCut=rave.uniforms.uCut;});
const venueAttr=(count,size)=>new THREE.InstancedBufferAttribute(new Float32Array(count*size),size).setUsage(THREE.DynamicDrawUsage);
const venueUniforms={uTime:rave.uniforms.uTime,uKick:rave.uniforms.uKick,uEnergy:rave.uniforms.uEnergy,uSourceIntensity:rave.uniforms.uSourceIntensity,
  uCut:rave.uniforms.uCut,uFlash:rave.uniforms.uFlash,uColor:rave.uniforms.uColor};

// C11.4: two runtime atlases, one for the neon names and one for the graffiti words. Each venue is a
// cell addressed by a per-instance offset; both are drawn once (again when the sign font arrives).
const SIGN_COLS=4,SIGN_ROWS=24,SIGN_CELLS=SIGN_COLS*SIGN_ROWS;
const signCanvases=[],signTextures=[];
function drawSignAtlas(a){
  const canvas=signCanvases[a],g=canvas.getContext('2d'),w=1024/SIGN_COLS,h=1024/SIGN_ROWS;
  g.fillStyle='#000';g.fillRect(0,0,1024,1024);g.fillStyle='#fff';g.textAlign='center';g.textBaseline='middle';
  for(let k=0;k<SIGN_CELLS;k++){const v=venueList[a*SIGN_CELLS+k];if(!v)break;const text=v.name.toUpperCase(),x=(k%SIGN_COLS)*w,y=Math.floor(k/SIGN_COLS)*h;
    let size=30;const font=s=>`600 ${s}px Rajdhani, 'Arial Narrow', sans-serif`;g.font=font(size);
    while(g.measureText(text).width>w-18&&size>13){size--;g.font=font(size);}
    g.fillText(text,x+w/2,y+h/2+1);}
}
for(let a=0;a*SIGN_CELLS<venueList.length;a++){
  const canvas=document.createElement('canvas');canvas.width=canvas.height=1024;signCanvases.push(canvas);drawSignAtlas(a);
  const texture=new THREE.CanvasTexture(canvas);texture.colorSpace=THREE.NoColorSpace;texture.minFilter=THREE.LinearFilter;texture.generateMipmaps=false;texture.anisotropy=4;
  signTextures.push(texture);
}
if(document.fonts&&document.fonts.load)document.fonts.load("600 30px Rajdhani").then(()=>{signCanvases.forEach((c,a)=>{drawSignAtlas(a);signTextures[a].needsUpdate=true;});}).catch(()=>{});
const tagCanvas=document.createElement('canvas');tagCanvas.width=512;tagCanvas.height=256;
{const g=tagCanvas.getContext('2d'),w=256,h=256/3;g.fillStyle='#000';g.fillRect(0,0,512,256);g.textAlign='center';g.textBaseline='middle';g.lineJoin='round';
  GRAFFITI_WORDS.forEach((word,k)=>{const x=(k%2)*w+w/2,y=Math.floor(k/2)*h+h/2;g.save();g.translate(x,y);g.rotate((k%3-1)*.07);
    let size=64;g.font=`italic 900 ${size}px sans-serif`;while(g.measureText(word).width>w-30&&size>20){size-=2;g.font=`italic 900 ${size}px sans-serif`;}
    g.lineWidth=7;g.strokeStyle='#777';g.strokeText(word,0,0);g.fillStyle='#fff';g.fillText(word,0,0);g.restore();});}
const tagTexture=new THREE.CanvasTexture(tagCanvas);tagTexture.colorSpace=THREE.NoColorSpace;tagTexture.minFilter=THREE.LinearFilter;tagTexture.generateMipmaps=false;
// Dark buildings spray the same curated words in their static decay dressing (C11.2); the atlas never changes.
cityMat.uniforms.uTags.value=tagTexture;

// The storefront band: glass with an interior glow and moving silhouettes when open, a roll-down
// shutter with graffiti when the host is dark. It pulses on the kick only through the rave uniforms,
// so the Lights setting, the cut and the limited drop flash govern it like every other scenery light.
const frontGeometry=new THREE.PlaneGeometry(1,1).translate(0,.5,0);
frontGeometry.setAttribute('aOpen',venueAttr(venueList.length,1));
frontGeometry.setAttribute('aVenue',new THREE.InstancedBufferAttribute(new Float32Array(venueList.map(v=>v.index*.618034%1)),1));
frontGeometry.setAttribute('aPulse',new THREE.InstancedBufferAttribute(new Float32Array(venueList.map(v=>v.pulse)),1));
const frontMat=new THREE.ShaderMaterial({fog:true,uniforms:Object.assign(THREE.UniformsUtils.clone(THREE.UniformsLib.fog),venueUniforms,{uTags:{value:tagTexture}}),
  vertexShader:`attribute float aOpen,aVenue,aPulse;varying vec2 vUV;varying vec3 vColor;varying float vOpen,vSeed,vPulse;
    #include <fog_pars_vertex>
    void main(){vUV=uv;vColor=instanceColor;vOpen=aOpen;vSeed=aVenue;vPulse=aPulse;vec4 mvPosition=modelViewMatrix*instanceMatrix*vec4(position,1.0);gl_Position=projectionMatrix*mvPosition;
      #include <fog_vertex>
    }`,
  fragmentShader:`varying vec2 vUV;varying vec3 vColor;varying float vOpen,vSeed,vPulse;uniform float uTime,uKick,uEnergy,uSourceIntensity,uCut,uFlash;uniform vec3 uColor;uniform sampler2D uTags;
    #include <fog_pars_fragment>
    float hash(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453);}
    float noise(vec2 p){vec2 i=floor(p),f=fract(p);f=f*f*(3.0-2.0*f);return mix(mix(hash(i),hash(i+vec2(1,0)),f.x),mix(hash(i+vec2(0,1)),hash(i+1.0),f.x),f.y);}
    void main(){vec3 c;
      if(vOpen<.05){
        float rib=.72+.28*step(.5,fract(vUV.y*18.0));c=vec3(.085,.09,.10)*rib*(.8+.2*vUV.y);
        float tag=smoothstep(.6,.68,noise(vUV*vec2(5.0,2.4)+vSeed*37.0))*step(vUV.y,.78);
        vec2 g=(vUV-vec2(.08,.18))/vec2(.84,.56);float word=0.0;
        if(g.x>0.0&&g.x<1.0&&g.y>0.0&&g.y<1.0){float cell=floor(vSeed*5.999);vec2 tile=vec2(mod(cell,2.0),floor(cell/2.0));
          word=texture2D(uTags,vec2((tile.x+g.x)/2.0,1.0-(tile.y+1.0-g.y)/3.0)).r;}
        vec3 ink=.5+.5*cos(6.2831*(vec3(0.0,.33,.67)+vSeed*3.0)),ink2=.5+.5*cos(6.2831*(vec3(0.0,.33,.67)+vSeed*3.0+.45));
        c=mix(c,ink*.26,tag*.8);c=mix(c,ink2*.34,word);
      } else {
        float x=vUV.x*3.2+uTime*(.10+.12*vSeed)*(vSeed>.5?1.0:-1.0),slot=floor(x),f=fract(x)-.5;
        float top=.5+.12*hash(vec2(slot,vSeed)),here=step(hash(vec2(slot,vSeed*9.0)),.3+.55*vOpen);
        float sil=(smoothstep(.2,.15,abs(f))*step(vUV.y,top)+1.0-smoothstep(.08,.1,length(vec2(f,(vUV.y-top-.1)*.8))))*here;
        // Only open bars and clubs pulse (C4.4). The kick stays under the beat cap of lights.pulse() (8 % in the
        // overview, C12.1) and the drop slam scales with the Lights level, the view and sound off like the sky.
        float drive=uEnergy*uSourceIntensity,pulse=vPulse*step(.99,vOpen)*min(uKick,1.0)*.1333*drive;
        vec3 glow=vColor*(.2+.6*vOpen)*(.72+.38*vUV.y)*(1.0+pulse)+uColor*uFlash*.5*vOpen*drive;
        float mullion=step(.035,fract(vUV.x*4.0))*step(.05,vUV.y)*step(vUV.y,.95);
        c=mix(vec3(.015,.018,.022),glow*(1.0-min(sil,1.0)*.85),mullion);
      }
      gl_FragColor=vec4(c*uCut,1.0);
      #include <fog_fragment>
      #include <colorspace_fragment>
    }`});
const storefronts=new THREE.InstancedMesh(frontGeometry,frontMat,venueList.length);storefronts.frustumCulled=false;
// The glass band stands 0.45 tall and the awning sits above the tallest person (0.42 x 1.12), so a queue,
// a bouncer or a patron under it never has its head inside the canvas.
const FRONT_H=.45,AWNING_Y=.52,AWNING_PITCH=.15,SIGN_Y=.63;
const awnings=propMesh(propGeometry(g=>{for(let k=0;k<6;k++)g.box(-.5+k/6,0,0,-.5+(k+1)/6,.012,.14,k%2?2:0);g.box(-.5,-.014,.135,.5,0,.14,2);}),venueList.length);
const signMeshes=signTextures.map((texture,a)=>{
  const list=venueList.slice(a*SIGN_CELLS,(a+1)*SIGN_CELLS),geometry=new THREE.PlaneGeometry(1,1);
  geometry.setAttribute('aCell',new THREE.InstancedBufferAttribute(new Float32Array(list.map((v,k)=>k)),1));
  geometry.setAttribute('aOpen',venueAttr(list.length,1));
  geometry.setAttribute('aPulse',new THREE.InstancedBufferAttribute(new Float32Array(list.map(v=>v.pulse)),1));
  const material=new THREE.ShaderMaterial({fog:true,side:THREE.DoubleSide,uniforms:Object.assign(THREE.UniformsUtils.clone(THREE.UniformsLib.fog),venueUniforms,{uAtlas:{value:texture}}),
    vertexShader:`attribute float aCell,aOpen,aPulse;varying vec2 vUV;varying vec3 vColor;varying float vOpen,vPulse;
      #include <fog_pars_vertex>
      void main(){vec2 cell=vec2(mod(aCell,${SIGN_COLS}.0),floor(aCell/${SIGN_COLS}.0));vUV=vec2((cell.x+uv.x)/${SIGN_COLS}.0,1.0-(cell.y+1.0-uv.y)/${SIGN_ROWS}.0);
        vColor=instanceColor;vOpen=aOpen;vPulse=aPulse;vec4 mvPosition=modelViewMatrix*instanceMatrix*vec4(position,1.0);gl_Position=projectionMatrix*mvPosition;
        #include <fog_vertex>
      }`,
    fragmentShader:`uniform sampler2D uAtlas;uniform float uKick,uEnergy,uSourceIntensity,uCut,uFlash;uniform vec3 uColor;varying vec2 vUV;varying vec3 vColor;varying float vOpen,vPulse;
      #include <fog_pars_fragment>
      void main(){if(!gl_FrontFacing){gl_FragColor=vec4(vec3(.015,.018,.022)*uCut,1.0);return;}float text=texture2D(uAtlas,vUV).r;
        // A shut venue's sign is off: the tube carries no light, so the name does not read (C4.4).
        float on=step(.05,vOpen),drive=uEnergy*uSourceIntensity,pulse=vPulse*step(.99,vOpen)*min(uKick,1.0)*.1333*drive;
        vec3 neon=vColor*(.4+.8*vOpen)*(1.0+pulse)+uColor*uFlash*.5*drive;
        vec3 c=mix(vec3(.012,.014,.018),neon,text*on)*uCut;
        gl_FragColor=vec4(c,1.0);
        #include <fog_fragment>
        #include <colorspace_fragment>
      }`});
  const mesh=new THREE.InstancedMesh(geometry,material,list.length);mesh.frustumCulled=false;list.forEach((v,k)=>{v.signMesh=mesh;v.signSlot=k;mesh.setColorAt(k,v.color);});
  return mesh;
});
const venueGroup=new THREE.Group();scene.add(venueGroup);venueGroup.add(storefronts,awnings,...signMeshes);
venueList.forEach(v=>{storefronts.setColorAt(v.index,v.color);awnings.setColorAt(v.index,v.color);});
const venueMatrix=new THREE.Matrix4(),venueQuat=new THREE.Quaternion(),venueEuler=new THREE.Euler(),venueScale=new THREE.Vector3(),venuePos=new THREE.Vector3();
function venueSet(mesh,i,pos,yaw,sx,sy,sz,pitch=0){venueEuler.set(pitch,yaw,0,'YXZ');venueQuat.setFromEuler(venueEuler);venueScale.set(sx,sy,sz);venueMatrix.compose(pos,venueQuat,venueScale);mesh.setMatrixAt(i,venueMatrix);}
function placeVenue(v){
  const g=v.grow,w=v.width;
  venuePos.copy(v.face).addScaledVector(v.normal,v.front);venuePos.y=v.z+.02;venueSet(storefronts,v.index,venuePos,v.yaw,w*g,FRONT_H*g,1);
  // Awnings over the open ones; a dark venue keeps only its shutter.
  const a=v.state==='shut'?0:g;venuePos.copy(v.face).addScaledVector(v.normal,v.front+.002);venuePos.y=v.z+AWNING_Y*g;venueSet(awnings,v.index,venuePos,v.yaw,w*1.06*a,a,a,AWNING_PITCH);
  venuePos.copy(v.face).addScaledVector(v.normal,v.front+.018);venuePos.y=v.z+SIGN_Y*g;const sw=Math.min(w,.56);venueSet(v.signMesh,v.signSlot,venuePos,v.yaw,sw*g,sw/5.2*g,1);
}

// ------------------------------------------------------------------ street furniture (C4.5)
const furnitureItems=DATA.design.furniture.map((f,i)=>{
  const item={...f,index:i,world:W(f.x,f.y,f.z),yaw:0};
  // Manholes sit in the carriageway, so they rise to the road surface (route z plus the ribbon).
  if(f.kind==='manhole')item.world.y+=.035+.007;
  return item;
});
{ // Chairs face their table, stage carts face the dance floor, street pieces face the nearest road.
  const tables=furnitureItems.filter(f=>f.kind==='table');
  for(const f of furnitureItems){
    if(f.kind==='table'){const v=venueList[f.venue];f.yaw=v?v.yaw:0;continue;}
    if(f.kind==='chair'){let best=null,bd=Infinity;for(const t of tables){if(t.venue!==f.venue)continue;const d=t.world.distanceToSquared(f.world);if(d<bd){bd=d;best=t;}}
      f.yaw=best?Math.atan2(best.world.x-f.world.x,best.world.z-f.world.z):0;continue;}
    const stage=f.kind==='cart'?stages.find(s=>s.district===f.district&&s.center.distanceTo(f.world)<s.r+.05):null;
    if(stage){f.stage=stage.index;f.yaw=Math.atan2(stage.center.x-f.world.x,stage.center.z-f.world.z);continue;}
    let best=null,bd=Infinity;
    for(const route of routes){if(route.district!==f.district)continue;for(let i=0;i<route.points.length;i+=2){const d=route.points[i].distanceToSquared(f.world);if(d<bd){bd=d;best=route.points[i];}}}
    f.yaw=best?Math.atan2(best.x-f.world.x,best.z-f.world.z):f.rot;
  }
}
const FURNITURE_GEOMETRY={
  table:propGeometry(g=>{g.prism(CIRC,.072,.078,.09,.09,2,2);g.box(-.005,0,-.005,.005,.072,.005,0);}),
  chair:propGeometry(g=>{g.box(-.024,.042,-.024,.024,.048,.024,2);g.box(-.024,.048,-.027,.024,.1,-.021,2);for(const x of [-.02,.02])for(const z of [-.02,.02])g.box(x-.003,0,z-.003,x+.003,.042,z+.003,2);}),
  crate:propGeometry(g=>{g.box(-.036,0,-.026,.036,.04,.026,2);g.box(-.036,.04,-.026,.036,.08,.026,2);}),
  cart:propGeometry(g=>{g.box(-.08,.05,-.045,.08,.15,.045,2);g.box(-.07,.15,-.035,.07,.19,.035,1);g.box(-.06,0,-.05,-.04,.05,.05,0);g.box(.04,0,-.05,.06,.05,.05,0);
    g.box(-.004,.19,-.004,.004,.5,.004,0);g.prism(ring(8,.5),.49,.56,.36,.05,[2,0,2,0,2,0,2,0],2);}),
  kiosk:propGeometry(g=>{g.box(-.09,0,-.07,.09,.2,.07,2);g.box(-.07,.09,.07,.07,.17,.076,1);g.box(-.1,.2,-.08,.1,.216,.08,0);}),
  bin:propGeometry(g=>{g.prism(CIRC,0,.08,.06,.06,0,0);}),
  busstop:propGeometry(g=>{g.box(-.12,.5,-.06,.12,.512,.06,0);g.box(-.1,.06,-.06,.1,.44,-.054,1);g.box(-.12,0,-.06,-.11,.5,-.05,0);g.box(.11,0,-.06,.12,.5,-.05,0);g.box(-.08,.08,-.04,.08,.09,-.01,2);}),
  manhole:propGeometry(g=>{g.prism(CIRC,0,.004,.16,.16,0,0);}),
};
const FURNITURE_COLORS={table:['#3a3f48','#d8262c'],chair:['#4a4f58','#e8e8e8'],crate:['#e6b800'],cart:['#ffcf33','#ff8a1f','#e63946','#39d353','#ff7ab6'],
  kiosk:['#2a9d8f','#e9c46a','#e76f51','#8ab17d','#6d597a'],bin:['#2b3440'],busstop:['#5ee6ff'],manhole:['#1a1d22']};
// Street furniture is not on B2's list of music-reactive light: its panels (bus-stop light boxes, kiosk
// fronts, cart counters) glow steadily and hold through the cut like the street lamps.
const furnitureMat=propMat.clone();furnitureMat.uniforms.uKick={value:0};furnitureMat.uniforms.uCut={value:1};
furnitureMat.uniforms.uEnergy={value:1};furnitureMat.uniforms.uSourceIntensity={value:1};
const furnitureMeshes={};
for(const [kind,geometry] of Object.entries(FURNITURE_GEOMETRY)){
  const list=furnitureItems.filter(f=>f.kind===kind);if(!list.length)continue;
  const mesh=propMesh(geometry,list.length);mesh.material=furnitureMat;venueGroup.add(mesh);
  list.forEach((f,k)=>{f.mesh=mesh;f.slot=k;const colors=FURNITURE_COLORS[kind];mesh.setColorAt(k,new THREE.Color(colors[f.variant%colors.length]));
    venueSet(mesh,k,f.world,f.yaw,1,1,1);});
  mesh.instanceMatrix.needsUpdate=true;mesh.instanceColor.needsUpdate=true;furnitureMeshes[kind]=mesh;
}
// Steam from manholes and food carts, and warm bulbs strung across the Archive avenues.
const steamSources=furnitureItems.filter(f=>f.kind==='manhole'||f.kind==='cart');
const steamPositions=[],steamSeeds=[];
for(const f of steamSources)for(let k=0;k<6;k++){steamPositions.push(f.world.x,f.world.y+(f.kind==='cart'?.19:.006),f.world.z);steamSeeds.push((f.index*.37+k/6)%1);}
const steamGeometry=new THREE.BufferGeometry();steamGeometry.setAttribute('position',new THREE.Float32BufferAttribute(steamPositions,3));steamGeometry.setAttribute('aSeed',new THREE.Float32BufferAttribute(steamSeeds,1));
const steam=new THREE.Points(steamGeometry,new THREE.ShaderMaterial({uniforms:{uTime:rave.uniforms.uTime},transparent:true,depthWrite:false,
  vertexShader:`attribute float aSeed;uniform float uTime;varying float vFade;void main(){float t=fract(uTime*.22+aSeed);vec3 p=position+vec3(sin(aSeed*40.0+uTime)*.03*t,t*.55,cos(aSeed*23.0)*.03*t);
    vFade=(1.0-t)*smoothstep(0.0,.15,t);vec4 mv=modelViewMatrix*vec4(p,1.0);gl_Position=projectionMatrix*mv;gl_PointSize=clamp((50.0+120.0*t)/-mv.z,1.0,26.0);}`,
  fragmentShader:`varying float vFade;void main(){float r=length(gl_PointCoord-.5);if(r>.5)discard;gl_FragColor=vec4(vec3(.55,.6,.66),vFade*.12*(1.0-r*2.0));
    #include <colorspace_fragment>
  }`}));
steam.frustumCulled=false;venueGroup.add(steam);
const archiveBulbs=[],archiveSeeds=[];
for(const route of routes.filter(r=>r.district==='episodic'))for(let d=1.2;d<route.length;d+=2.4){
  const a=sampleRoute(route,d,new THREE.Vector3(),-.46),b=sampleRoute(route,d,new THREE.Vector3(),.46);
  // Only across the straights: the avenue keeps its heading from half a unit before to half after.
  const p0=sampleRoute(route,d-.6,new THREE.Vector3()),p1=sampleRoute(route,d-.4,new THREE.Vector3()),q0=sampleRoute(route,d+.4,new THREE.Vector3()),q1=sampleRoute(route,d+.6,new THREE.Vector3());
  const tx=p1.x-p0.x,tz=p1.z-p0.z,ux=q1.x-q0.x,uz=q1.z-q0.z;if((tx*ux+tz*uz)/(Math.hypot(tx,tz)*Math.hypot(ux,uz)||1)<.999)continue;
  for(let k=0;k<=8;k++){const t=k/8,p=a.clone().lerp(b,t);p.y=route.points[0].y+1.03-Math.sin(t*Math.PI)*.1;archiveBulbs.push(p.x,p.y,p.z);archiveSeeds.push((k*5+Math.floor(d))%9/9);}
}
const archiveBulbGeometry=new THREE.BufferGeometry();archiveBulbGeometry.setAttribute('position',new THREE.Float32BufferAttribute(archiveBulbs,3));archiveBulbGeometry.setAttribute('aSeed',new THREE.Float32BufferAttribute(archiveSeeds,1));
const streetBulbs=new THREE.Points(archiveBulbGeometry,bulbs.material);streetBulbs.frustumCulled=false;venueGroup.add(streetBulbs);

// ------------------------------------------------------------------ vehicles (C5.1 to C5.3)
const VEHICLE_ALLOCATION={compact:24,sedan:28,taxi:26,suv:14,van:10,bus:6,truck:10,moto:18,delivery:18,chiva:6};
// Half widths from the C5.1 table, for kerbside stops and for passing a stopped taxi.
const VEHICLE_HALF={compact:.07,sedan:.075,taxi:.075,suv:.08,van:.08,bus:.1,truck:.09,moto:.025,delivery:.03,chiva:.1};
const VEHICLE_TYPES=Object.keys(VEHICLE_ALLOCATION);
const CARS=Object.values(VEHICLE_ALLOCATION).reduce((a,b)=>a+b,0);
const VEHICLE_TIER_CAP={3:CARS,2:Math.round(CARS*.6),1:70};
const DISTRICT_VEHICLES={episodic:['moto','delivery','taxi','chiva','compact'],working:['taxi','sedan','suv','bus','chiva'],prospective:['truck','van'],
  procedural:['truck','moto','van'],jhon:['compact','moto','delivery']};
const OTHER_VEHICLES=['sedan','compact','taxi','moto','bus'];
const VEHICLE_PAINT={compact:['#c9ccd1','#1c1f24','#8a1c1c','#23395d','#e9e9e9','#5b5f66','#2f4f3f'],sedan:['#c9ccd1','#15171b','#6e1a1a','#1d2f4f','#e9e9e9','#474b52'],
  taxi:['#f4c20d'],suv:['#15171b','#2b2f36','#e9e9e9','#3b1f1f'],van:['#e9e9e9','#c9ccd1','#23395d'],bus:['#d62828','#1d3557','#2a9d8f'],truck:['#e9e9e9','#1d6fd8','#c9ccd1'],
  moto:['#15171b','#b3122e','#1d6fd8'],delivery:['#15171b','#2b2f36'],chiva:['#e8392f','#1f6fd1','#f2c230','#2aa64a']};
const VEHICLE_TRIM={compact:['#15171b'],sedan:['#15171b'],taxi:['#15171b'],suv:['#15171b'],van:['#15171b'],bus:['#f4f1ec'],truck:['#f4f1ec','#dfe3e8'],
  moto:['#f4f1ec','#ffd400','#e63946'],delivery:['#ff7a1a','#e63946','#ffd400'],chiva:['#ffd060','#ff5fa2','#5ee6ff','#8cff6a']};
// Parts: 0 paint, 1 string lights (chiva), 2 trim, 3 dark glass, 4 roof or route sign, 5 headlight, 6 taillight, 7 lit interior, 8 rubber.
// Overall boxes match the C5.1 table: wheels sit inside the body width, and a two-wheeler's rider is part of its height.
function vehicleGeometry(type){
  const g=new GB(),wheel=(x,z,r=.022)=>g.box(x-.012,0,z-r,x+.012,r*2,z+r,8);
  const inset=hw=>hw-.012;
  const carLamps=(hw,y,front,back)=>{g.box(-hw,y,front,-hw+.028,y+.018,front+.004,5);g.box(hw-.028,y,front,hw,y+.018,front+.004,5);g.box(-hw,y,back-.004,-hw+.028,y+.018,back,6);g.box(hw-.028,y,back-.004,hw,y+.018,back,6);};
  const car=(hw,l,body,top,cab0,cab1)=>{g.box(-hw,.02,-l,hw,body,l,0);g.box(-hw+.01,body,cab0,hw-.01,top,cab1,{px:3,nx:3,py:0,ny:0,pz:3,nz:3});
    for(const x of [-inset(hw),inset(hw)])for(const z of [-l*.62,l*.62])wheel(x,z);carLamps(hw,body-.024,l,-l);};
  const twoWheeler=(delivery)=>{
    wheel(0,-.066,.02);wheel(0,.066,.02);g.box(-.014,.02,-.086,.014,.05,.086,0);g.box(-.025,.05,.052,.025,.056,.06,2);
    g.box(-.01,.034,.086,.01,.05,.09,5);g.box(-.008,.034,-.09,.008,.047,-.086,6);
    g.box(-.016,.05,-.032,.016,.084,.008,8);g.box(-.013,.084,-.026,.013,.1,0,2);
    if(delivery)g.box(-.03,.05,-.09,.03,.12,-.036,2);};
  switch(type){
    case 'compact':car(.07,.15,.07,.12,-.08,.07);break;
    case 'sedan':car(.075,.18,.065,.12,-.09,.08);break;
    case 'taxi':car(.075,.18,.065,.12,-.09,.08);g.box(-.028,.12,-.02,.028,.138,.02,4);break;
    case 'suv':car(.08,.18,.08,.15,-.13,.1);break;
    case 'van':g.box(-.079,.02,-.2,.079,.18,.2,0);g.box(-.07,.1,.2,.07,.16,.203,3);g.box(-.08,.11,-.12,.08,.16,.12,3);for(const x of [-inset(.08),inset(.08)])for(const z of [-.13,.13])wheel(x,z);carLamps(.079,.05,.203,-.203);break;
    case 'bus':g.box(-.098,.025,-.4,.098,.22,.4,0);for(const s of [-1,1])g.box(s>0?.098:-.1,.12,-.36,s>0?.1:-.098,.19,.34,7);g.box(-.09,.1,.4,.09,.18,.403,3);g.box(-.07,.186,.4,.07,.21,.404,4);
      for(const x of [-inset(.098),inset(.098)])for(const z of [-.27,.28])wheel(x,z,.028);carLamps(.098,.05,.403,-.403);break;
    case 'truck':g.box(-.09,.02,.14,.09,.17,.275,0);g.box(-.08,.11,.275,.08,.16,.278,3);g.box(-.09,.03,-.275,.09,.22,.13,2);for(const x of [-inset(.09),inset(.09)])for(const z of [-.2,.2])wheel(x,z,.026);carLamps(.09,.05,.278,-.278);break;
    case 'moto':twoWheeler(false);break;
    case 'delivery':twoWheeler(true);break;
    case 'chiva':g.box(-.096,.03,-.35,.096,.1,.35,0);g.box(-.096,.1,-.33,.096,.22,.3,{px:2,nx:2,py:0,ny:0,pz:2,nz:2});g.box(-.08,.13,.3,.08,.2,.304,3);
      for(const s of [-1,1]){for(let k=0;k<6;k++){const z=-.3+k*.105;g.box(s>0?.096:-.098,.135,z,s>0?.098:-.096,.2,z+.07,3);}
        g.box(s>0?.09:-.096,.235,-.33,s>0?.096:-.09,.25,.31,0);for(let k=0;k<12;k++){const z=-.32+k*.056;g.box(s*.094-.006,.25,z-.006,s*.094+.006,.26,z+.006,1);}}
      g.box(-.096,.22,-.34,.096,.235,.31,0);g.box(-.097,.1,-.35,.097,.112,.35,1);for(const x of [-inset(.096),inset(.096)])for(const z of [-.24,.24])wheel(x,z,.026);carLamps(.096,.05,.353,-.353);break;
  }
  return g.geometry();
}
// Its own material, never cityMat (B2): the chiva's string lights move with the music.
const vehicleMat=new THREE.ShaderMaterial({fog:true,uniforms:Object.assign(THREE.UniformsUtils.clone(THREE.UniformsLib.fog),{uKey:{value:KEY},uKick:rave.uniforms.uKick,
    uEnergy:rave.uniforms.uEnergy,uSourceIntensity:rave.uniforms.uSourceIntensity,uCut:rave.uniforms.uCut,uFlash:rave.uniforms.uFlash,uColor:rave.uniforms.uColor,uBeat:rave.uniforms.uBeat}),
  vertexShader:`attribute float aPart,aBrake;attribute vec3 aTrim;varying float vPart,vBrake,vZ;varying vec3 vColor,vTrim,vN,vWorld;
    #include <fog_pars_vertex>
    void main(){vPart=aPart;vBrake=aBrake;vTrim=aTrim;vZ=position.z;vColor=instanceColor;vN=normalize(mat3(modelMatrix)*mat3(instanceMatrix)*normal);vec4 world=modelMatrix*instanceMatrix*vec4(position,1.0);vWorld=world.xyz;
      vec4 mvPosition=viewMatrix*world;gl_Position=projectionMatrix*mvPosition;
      #include <fog_vertex>
    }`,
  fragmentShader:`uniform vec3 uKey,uColor;uniform float uKick,uEnergy,uSourceIntensity,uCut,uFlash,uBeat;varying float vPart,vBrake,vZ;varying vec3 vColor,vTrim,vN,vWorld;
    #include <fog_pars_fragment>
    void main(){vec3 n=normalize(vN);float d=max(dot(n,uKey),0.0),fres=pow(1.0-abs(dot(n,normalize(cameraPosition-vWorld))),3.0),drive=uEnergy*uSourceIntensity;vec3 c;
      if(vPart<.5)c=vColor*(.3+.5*d)+vec3(.06,.08,.11)*fres+uColor*.06*fres;
      else if(vPart<1.5){float chase=step(.5,fract(vZ*9.0+floor(uBeat)*.5));
        // The chase moves light along the rail (its mean holds); the kick stays under the lights.pulse() cap and
        // the drop colour scales with the Lights level, the view and sound off (C12.1, C12.2).
        c=mix(vTrim,uColor,min(uFlash,1.0)*.8*drive)*(.6+.45*chase*drive)*(1.0+.1333*min(uKick,1.0)*drive)*uCut*1.3;}
      else if(vPart<2.5)c=vTrim*(.3+.55*d)+vec3(.04,.05,.06)*fres;
      else if(vPart<3.5)c=vec3(.02,.03,.045)+vec3(.12,.16,.2)*fres;
      else if(vPart<4.5)c=vec3(1.0,.93,.62)*1.1;
      else if(vPart<5.5)c=vec3(1.0,.96,.84)*1.5;
      else if(vPart<6.5)c=vec3(1.0,.1,.05)*(.7+1.6*vBrake);
      else if(vPart<7.5)c=vec3(1.0,.84,.55)*.85;
      else c=vec3(.018,.02,.024);
      gl_FragColor=vec4(c,1.0);
      #include <fog_fragment>
      #include <colorspace_fragment>
    }`});
const vehicleGroup=new THREE.Group();scene.add(vehicleGroup);
const vehicleRnd=mulberry(4242),carState=[];
{ // Each road gets vehicles in proportion to its length (largest remainder); its district picks the
  // types. Roads take turns so no district drains a shared type first; a type left over after its
  // districts fill spreads over the rest.
  const budget={...VEHICLE_ALLOCATION},total=routes.reduce((s,r)=>s+r.length,0);
  const exact=routes.map(r=>CARS*r.length/total),perRoute=exact.map(Math.floor);
  const spare=CARS-perRoute.reduce((a,b)=>a+b,0);
  exact.map((x,i)=>[x-perRoute[i],i]).sort((a,b)=>b[0]-a[0]).slice(0,spare).forEach(([,i])=>{perRoute[i]++;});
  const cursor=routes.map(()=>0),rows=routes.map(()=>[]);
  for(let placed=0;placed<CARS;){
    for(let ri=0;ri<routes.length&&placed<CARS;ri++){
      if(rows[ri].length>=perRoute[ri])continue;
      const list=DISTRICT_VEHICLES[routes[ri].district]||OTHER_VEHICLES;let type=null;
      for(let j=0;j<list.length;j++){const t=list[(cursor[ri]+j)%list.length];if(budget[t]>0){type=t;cursor[ri]=(cursor[ri]+j+1)%list.length;break;}}
      if(!type)type=VEHICLE_TYPES.reduce((a,b)=>budget[a]>=budget[b]?a:b);
      budget[type]--;rows[ri].push(type);placed++;
    }
  }
  rows.forEach((list,ri)=>{const route=routes[ri],archive=route.district==='episodic';
    list.forEach((type,k)=>{
      const two=type==='moto'||type==='delivery';
      const speed=type==='chiva'?.5:type==='bus'?.55+vehicleRnd()*.2:type==='truck'||type==='van'?.6+vehicleRnd()*.4:two?1+vehicleRnd()*.7:.75+vehicleRnd()*.75;
      // A pulled-in taxi's outer side stops at the kerb: the Archive carriageway is 0.54 wide (0.10 lane plus
      // 0.095 plus a 0.075 half width reaches 0.27), a ring 0.88 (0.12 plus 0.22 plus 0.075 leaves 0.025).
      carState.push({type,route:ri,district:route.district,distance:(k+vehicleRnd()*.6)/list.length*route.length,dir:k%2?1:-1,speed,cruise:speed,target:speed,
        lane:(archive?.1:.12)+(two?.04:0),pullBy:archive?.095:.22,half:VEHICLE_HALF[type],dodge:0,pull:0,mode:0,timer:type==='taxi'?1+vehicleRnd()*5:4+vehicleRnd()*12,goal:0,brake:0,on:true,drawn:false,
        pos:new THREE.Vector3(),heading:new THREE.Vector3(),yaw:0,rank:0});
    });});
  // Stratified ranks: any prefix holds each type in proportion, so a tier keeps 60 % of each type.
  const keys=[];
  VEHICLE_TYPES.forEach((type,ti)=>{const list=carState.map((c,i)=>i).filter(i=>carState[i].type===type);
    for(let i=list.length-1;i>0;i--){const j=Math.floor(vehicleRnd()*(i+1));[list[i],list[j]]=[list[j],list[i]];}
    list.forEach((index,j)=>keys.push([(j+.5)/list.length,ti,index]));});
  keys.sort((a,b)=>a[0]-b[0]||a[1]-b[1]).forEach((key,rank)=>{carState[key[2]].rank=rank;});
}
const vehicleMeshes={};
for(const type of VEHICLE_TYPES){
  const list=carState.filter(c=>c.type===type),geometry=vehicleGeometry(type);
  geometry.setAttribute('aTrim',new THREE.InstancedBufferAttribute(new Float32Array(list.length*3),3));
  geometry.setAttribute('aBrake',venueAttr(list.length,1));
  const mesh=new THREE.InstancedMesh(geometry,vehicleMat,list.length);mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);mesh.frustumCulled=false;
  list.forEach((c,k)=>{c.mesh=mesh;c.slot=k;const paint=VEHICLE_PAINT[type],trim=VEHICLE_TRIM[type];mesh.setColorAt(k,new THREE.Color(paint[Math.floor(vehicleRnd()*paint.length)]));
    const t=new THREE.Color(trim[Math.floor(vehicleRnd()*trim.length)]);geometry.attributes.aTrim.setXYZ(k,t.r,t.g,t.b);});
  for(let i=0;i<mesh.instanceMatrix.array.length;i++)mesh.instanceMatrix.array[i]=0;
  vehicleMeshes[type]=mesh;vehicleGroup.add(mesh);
}
let visibleVehicles=CARS;
// Today's timeline rule (24 plus one per 18 visible links, 152 at week 12), scaled by the tier.
function vehicleCount(){
  const level=tier.current,factor=level===3?1:level===2?.6:VEHICLE_TIER_CAP[1]/CARS;
  return Math.min(VEHICLE_TIER_CAP[level],Math.round(Math.max(12,Math.round(24+validEdges.length/18))*factor));
}
function vehicleCensus(level=tier.current){
  const allocated={},visible={};for(const t of VEHICLE_TYPES){allocated[t]=0;visible[t]=0;}
  for(const c of carState){if(c.rank<VEHICLE_TIER_CAP[level])allocated[c.type]++;if(c.rank<visibleVehicles&&vehicleGroup.visible)visible[c.type]++;}
  return {tier:level,cap:VEHICLE_TIER_CAP[level],allocated,visible,visibleTotal:Object.values(visible).reduce((a,b)=>a+b,0),target:VEHICLE_ALLOCATION};
}
const cars={types:vehicleMeshes,allocation:VEHICLE_ALLOCATION,tierCap:VEHICLE_TIER_CAP,group:vehicleGroup,target:vehicleCount,census:vehicleCensus,
  mesh:{get visible(){return vehicleGroup.visible;},set visible(v){vehicleGroup.visible=v;},
    get count(){return visibleVehicles;},set count(v){visibleVehicles=Math.max(0,Math.min(CARS,v));}}};
// Traffic keeps to the right, as on Colombian streets: a positive lane offset (sampleRoute's (dz, -dx))
// is the left of the direction of travel, so a car driving with dir d sits on side -d. Taxis pull in at
// open venues on their own side of their own road.
const venueStops=routes.map(()=>[]);
for(const v of venueList){let best=null;
  routes.forEach((route,ri)=>{if(route.district!==v.district)return;const pts=route.points;for(let i=0;i<pts.length;i++){const d=pts[i].distanceToSquared(v.face);if(!best||d<best.d)best={d,ri,i};}});
  if(!best||best.d>2.2)continue;
  const pts=routes[best.ri].points,a=pts[best.i],b=pts[(best.i+1)%pts.length],dx=b.x-a.x,dz=b.z-a.z,l=Math.hypot(dx,dz)||1;
  // A positive lane offset points along (dz, -dx), the same frame sampleRoute uses.
  const side=Math.sign((v.face.x-a.x)*dz/l-(v.face.z-a.z)*dx/l)||1;
  venueStops[best.ri].push({s:routes[best.ri].lengths[best.i],side,venue:v});
}
const carPoint=new THREE.Vector3(),carAhead=new THREE.Vector3();
const STOP_LOOK=.9,STOP_DECEL=.9,CAR_ACCEL=.7,CAR_BRAKE=1.4;
// On the narrow Archive avenues a stopped taxi fills the kerb half of its lane, so traffic behind it
// swings toward the centre line to pass (C5.3). Stopped taxis are listed per road without allocating.
const BLOCK_MAX=32,blockS=routes.map(()=>new Float32Array(BLOCK_MAX)),blockDir=routes.map(()=>new Int8Array(BLOCK_MAX)),blockCar=routes.map(()=>new Int16Array(BLOCK_MAX)),blockCount=new Int16Array(routes.length);
const vehicleList=Object.values(vehicleMeshes);
// Traffic budget: every car keeps driving, but one outside the frustum rewrites its matrix only every
// eighth frame (staggered); a car that was just switched on is always written at once.
let carFrame=0;
const trafficState={written:0,culled:0};cars.budget=trafficState;
function updateCars(dt){
  const bar=beat.barSeconds,frameIndex=carFrame++;
  let written=0,culled=0;
  blockCount.fill(0);
  for(let k=0;k<carState.length;k++){const c=carState[k];if(c.type!=='taxi'||!c.on||c.pull<.35)continue;const r=c.route;
    if(routes[r].district!=='episodic'||blockCount[r]>=BLOCK_MAX)continue;const n=blockCount[r]++,L=routes[r].length;
    blockS[r][n]=((c.distance%L)+L)%L;blockDir[r][n]=c.dir;blockCar[r][n]=k;}
  for(let k=0;k<carState.length;k++){
    const c=carState[k],route=routes[c.route],arr=c.mesh.instanceMatrix.array,o=c.slot*16;
    if(c.rank>=visibleVehicles){if(c.on){for(let j=0;j<16;j++)arr[o+j]=0;c.on=false;c.mode=0;c.pull=0;c.speed=c.cruise;}c.drawn=false;continue;}
    c.on=true;c.timer-=dt;
    let target=c.cruise;
    if(c.mode===0){
      if(c.timer<=0&&c.type==='taxi'){
        const s=((c.distance%route.length)+route.length)%route.length,stops=venueStops[c.route];
        for(let i=0;i<stops.length;i++){const stop=stops[i];if(stop.side!==-c.dir||stop.venue.state!=='open')continue;
          const ahead=(((stop.s-s)*c.dir)%route.length+route.length)%route.length;
          if(ahead>.3&&ahead<STOP_LOOK){c.mode=1;c.goal=c.distance+ahead*c.dir;break;}}
        if(c.mode===0)c.timer=.25;
      } else if(c.timer<=0&&c.type!=='chiva'){c.mode=4;c.timer=.8+vehicleRnd()*1.4;c.target=c.cruise*(.3+.3*vehicleRnd());}
    }
    if(c.mode===1){const left=(c.goal-c.distance)*c.dir;target=Math.min(c.cruise,Math.sqrt(2*STOP_DECEL*Math.max(0,left)));c.pull=Math.min(1,Math.max(c.pull,1-left/STOP_LOOK));
      if(left<=.015||(c.speed<.03&&left<.06)){c.mode=2;c.timer=2*bar;c.speed=0;target=0;}}
    else if(c.mode===2){target=0;c.pull=1;if(c.timer<=0)c.mode=3;}
    else if(c.mode===3){c.pull=Math.max(0,1-c.speed/c.cruise);if(c.speed>=c.cruise*.98){c.mode=0;c.pull=0;c.timer=12+vehicleRnd()*8;}}
    else if(c.mode===4){target=c.target;if(c.timer<=0){c.mode=0;c.timer=6+vehicleRnd()*10;}}
    c.speed=c.speed<target?Math.min(target,c.speed+CAR_ACCEL*dt):Math.max(target,c.speed-CAR_BRAKE*dt);
    c.brake=c.mode===2||c.speed>target+.01?1:0;
    c.distance+=dt*c.speed*c.dir;
    let pass=0;
    if(blockCount[c.route]&&c.pull<.05){const L=route.length,s=((c.distance%L)+L)%L,n=blockCount[c.route];
      for(let i=0;i<n;i++){if(blockDir[c.route][i]!==c.dir||blockCar[c.route][i]===k)continue;
        const ahead=(((blockS[c.route][i]-s)*c.dir)%L+L)%L;if(ahead<.95||ahead>L-.5){pass=1;break;}}}
    c.dodge+=Math.sign(pass-c.dodge)*Math.min(Math.abs(pass-c.dodge),dt*2.2);
    const lateral=c.lane+c.pull*c.pullBy-c.dodge*(c.lane-Math.min(c.lane,.11-c.half)),lane=-lateral*c.dir;
    if(c.drawn&&((k+frameIndex)&7)){
      const px=c.pos.x,py=c.pos.y+.1,pz=c.pos.z;let outside=false;
      for(let q=0;q<24;q+=4)if(viewPlanes[q]*px+viewPlanes[q+1]*py+viewPlanes[q+2]*pz+viewPlanes[q+3]<-.6){outside=true;break;}
      if(outside){culled++;continue;}
    }
    ROUTE_ARGS[0]=c.distance;ROUTE_ARGS[1]=lane;sampleRouteArgs(route,carPoint);
    ROUTE_ARGS[0]=c.distance+.2*c.dir;ROUTE_ARGS[1]=lane;sampleRouteArgs(route,carAhead);
    c.pos.copy(carPoint);c.heading.subVectors(carAhead,carPoint).normalize();c.yaw=Math.atan2(c.heading.x,c.heading.z);
    const cy=Math.cos(c.yaw),sy=Math.sin(c.yaw);
    arr[o]=cy;arr[o+1]=0;arr[o+2]=-sy;arr[o+3]=0;arr[o+4]=0;arr[o+5]=1;arr[o+6]=0;arr[o+7]=0;arr[o+8]=sy;arr[o+9]=0;arr[o+10]=cy;arr[o+11]=0;
    arr[o+12]=carPoint.x;arr[o+13]=carPoint.y+.006;arr[o+14]=carPoint.z;arr[o+15]=1;
    c.mesh.geometry.attributes.aBrake.array[c.slot]=c.brake;c.drawn=true;written++;
  }
  for(let i=0;i<vehicleList.length;i++){const mesh=vehicleList[i];mesh.instanceMatrix.needsUpdate=true;mesh.geometry.attributes.aBrake.needsUpdate=true;}
  trafficState.written=written;trafficState.culled=culled;
}

// ------------------------------------------------------------------ posters (C4.1 flat decals, C11.4 atlas)
// One 1024 px atlas of twelve posters: the curated billboard lines of appendix G over abstract art, one
// sheet that carries the timeline's week number, and four art-only sheets, pasted on the bus-stop panels
// and the kiosk sides. Paper, not light: no music reaches them.
const POSTER_LINES=['TONIGHT','OPEN LATE','140 BPM','NO SLEEP TILL SUNRISE','BIENVENIDOS','ABIERTO 24H','SOUND SYSTEM',null,'','','',''];
const POSTER_COLS=4,POSTER_ROWS=3,POSTER_CELLS=POSTER_COLS*POSTER_ROWS,POSTER_W=1024/POSTER_COLS,POSTER_H=1024/POSTER_ROWS;
const POSTER_INKS=[['#ff3d9a','#1a0b2e','#ffe03a'],['#29e6ff','#0b1a2e','#ff8a1f'],['#39ff88','#0e1a12','#f4f1ec'],['#ffe03a','#2a1204','#ff3d5a'],['#b26bff','#12081f','#5ee6ff'],['#ff8a1f','#1d0d05','#f4f1ec']];
const posterCanvas=document.createElement('canvas');posterCanvas.width=posterCanvas.height=1024;
function drawPoster(k,week){
  const g=posterCanvas.getContext('2d'),x0=(k%POSTER_COLS)*POSTER_W,y0=Math.floor(k/POSTER_COLS)*POSTER_H,rnd=mulberry(700+k);
  const [ink,paper,accent]=POSTER_INKS[k%POSTER_INKS.length],W0=POSTER_W,H0=POSTER_H;
  g.save();g.beginPath();g.rect(x0,y0,W0,H0);g.clip();g.translate(x0,y0);
  g.fillStyle=paper;g.fillRect(0,0,W0,H0);
  const art=(k+Math.floor(k/4))%4;
  if(art===0){g.lineWidth=5;for(let r=112;r>8;r-=14){g.strokeStyle=r%28?ink:accent;g.beginPath();g.arc(W0/2,128,r,0,TAU);g.stroke();}}
  else if(art===1){for(let i=0;i<14;i++){const h=24+rnd()*150;g.fillStyle=i%3?ink:accent;g.fillRect(14+i*16.5,226-h,11,h);}}
  else if(art===2){g.fillStyle=ink;g.beginPath();g.moveTo(W0/2,22);g.lineTo(W0-20,222);g.lineTo(20,222);g.closePath();g.fill();g.fillStyle=accent;g.beginPath();g.arc(W0/2,150,42,0,TAU);g.fill();}
  else{g.lineWidth=7;for(let i=0;i<9;i++){g.strokeStyle=i%2?ink:accent;g.beginPath();for(let x=0;x<=W0;x+=8)g.lineTo(x,38+i*22+Math.sin(x/28+i*1.7)*14);g.stroke();}}
  const line=k===7?'WEEK '+week:POSTER_LINES[k];
  g.fillStyle=accent;g.fillRect(14,H0-22,W0-28,6);
  if(line){
    const words=line.split(' '),rows=[];let size=58;const font=s=>`700 ${s}px Rajdhani, 'Arial Narrow', sans-serif`;
    for(;size>=24;size-=2){g.font=font(size);rows.length=0;let row='';
      for(const w of words){const next=row?row+' '+w:w;if(g.measureText(next).width<=W0-30)row=next;else{if(row)rows.push(row);row=w;}}
      rows.push(row);if(rows.length*size*.92<=H0-262&&rows.every(r=>g.measureText(r).width<=W0-30))break;}
    g.textAlign='center';g.textBaseline='middle';g.fillStyle='#f4f1ec';
    rows.forEach((r,i)=>g.fillText(r,W0/2,248+(i+.5)*size*.92));
  }
  g.restore();
}
function drawPosters(week){for(let k=0;k<POSTER_CELLS;k++)drawPoster(k,week);}
drawPosters(0);
const posterTexture=new THREE.CanvasTexture(posterCanvas);posterTexture.colorSpace=THREE.SRGBColorSpace;posterTexture.anisotropy=4;
let posterWeek=0;
if(document.fonts&&document.fonts.load)document.fonts.load("700 30px Rajdhani").then(()=>{drawPosters(posterWeek);posterTexture.needsUpdate=true;}).catch(()=>{});
const posterSlots=[];
{ // Both faces of every bus-stop panel and both sides of every kiosk. The storefront bands fill their
  // host faces (0.64 to 0.9 long), so no wall beside a storefront has room for a sheet.
  const at=(f,x,y,z)=>{const p=f.world.clone(),c=Math.cos(f.yaw),s=Math.sin(f.yaw);p.x+=c*x+s*z;p.z+=-s*x+c*z;p.y+=y;return p;};
  for(const f of furnitureItems){
    if(f.kind==='busstop'){posterSlots.push({at:at(f,0,.25,-.0525),yaw:f.yaw,w:.15,h:.2},{at:at(f,0,.25,-.0615),yaw:f.yaw+Math.PI,w:.15,h:.2});}
    else if(f.kind==='kiosk'){posterSlots.push({at:at(f,.0915,.105,0),yaw:f.yaw+Math.PI/2,w:.09,h:.12},{at:at(f,-.0915,.105,0),yaw:f.yaw-Math.PI/2,w:.09,h:.12});}
  }
}
const posterGeometry=new THREE.PlaneGeometry(1,1);
posterGeometry.setAttribute('aCell',new THREE.InstancedBufferAttribute(new Float32Array(posterSlots.map((s,i)=>(i*5+3)%POSTER_CELLS)),1));
const posterMat=new THREE.ShaderMaterial({fog:true,uniforms:Object.assign(THREE.UniformsUtils.clone(THREE.UniformsLib.fog),{uPosters:{value:posterTexture},uKey:{value:KEY}}),
  vertexShader:`attribute float aCell;uniform vec3 uKey;varying vec2 vUV,vRaw;varying float vShade,vSeed;
    #include <fog_pars_vertex>
    void main(){vec2 cell=vec2(mod(aCell,${POSTER_COLS}.0),floor(aCell/${POSTER_COLS}.0));vUV=vec2((cell.x+uv.x)/${POSTER_COLS}.0,1.0-(cell.y+1.0-uv.y)/${POSTER_ROWS}.0);vRaw=uv;
      vSeed=fract(aCell*.37+instanceMatrix[3].x*1.3+instanceMatrix[3].z*.7);
      vec3 n=normalize(mat3(modelMatrix)*mat3(instanceMatrix)*vec3(0.0,0.0,1.0));vShade=.65+.35*max(dot(n,uKey),0.0);
      vec4 mvPosition=modelViewMatrix*instanceMatrix*vec4(position,1.0);gl_Position=projectionMatrix*mvPosition;
      #include <fog_vertex>
    }`,
  fragmentShader:`uniform sampler2D uPosters;varying vec2 vUV,vRaw;varying float vShade,vSeed;
    #include <fog_pars_fragment>
    float hash(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453);}
    void main(){
      // Weathered paper: some sheets have a torn lower corner; the ink is faded and lit only by the street.
      if(vSeed>.55&&vRaw.x+vRaw.y*1.4<.08+.2*fract(vSeed*7.0))discard;
      vec3 c=texture2D(uPosters,vUV).rgb*.3*vShade*(.86+.14*hash(floor(vRaw*vec2(20.0,26.0))+vSeed));
      gl_FragColor=vec4(c,1.0);
      #include <fog_fragment>
      #include <colorspace_fragment>
    }`});
const posters=new THREE.InstancedMesh(posterGeometry,posterMat,posterSlots.length);posters.frustumCulled=false;venueGroup.add(posters);
posterSlots.forEach((s,i)=>venueSet(posters,i,s.at,s.yaw,s.w,s.h,1));
posters.instanceMatrix.needsUpdate=true;

// ------------------------------------------------------------------ people the society adds (C3.4, C3.7)
// Riders dance on the chiva roofs, vendors work the carts, a bouncer and a short queue wait at club
// doors, people wait at bus stops, a few dance on bar terraces and neighbours sit at the tables. The
// caps are 88 at Tier 3, 53 at Tier 2 and 20 at Tier 1, so a phone keeps its 220 people (C13.1). Riders
// ride only while their chiva is on the road, three to every visible chiva at every tier: their share of
// each cap is reserved from the chiva ranks. The rest carry a stratified rank so a lower tier keeps the mix.
const EXTRA_CAP=88;
const venueExtras=[],venueRiderReserve={1:0,2:0,3:0};
{
  const groups={vend:[],queue:[],wait:[],dance:[],sit:[]},riders=[];
  // Each gate reads a stage index resolved here, so the per-frame visibility test allocates nothing (C13.4).
  const stageIndex=d=>{const s=stages.find(x=>x.district===d);return s?s.index:-1;};
  // A district's street people appear once its stage has a crowd (C3.7: week 0 is nearly empty).
  const awake=d=>{const si=stageIndex(d);return si<0?()=>false:()=>crowd.state.stageVisible[si]>0;};
  // Venues that are open at the end of the timeline come first (the host's light, a number).
  const finalOpen=v=>{const st=lightState(v.host,LAST);return st[0]==='lit'?(st[1]>=.5?2:1):0;};
  const chivas=carState.map((c,index)=>({c,index})).filter(x=>x.c.type==='chiva').sort((a,b)=>a.c.rank-b.c.rank);
  for(const {c,index} of chivas)for(let k=0;k<3;k++){const lz=-.2+k*.2,lx=k%2?.045:-.045,turn=k%2?1.3:-1.3;
    riders.push({pose:'ride',style:k%2?'handsup':'bounce',energy:.8,district:c.district,x:0,y:0,z:0,yaw:0,vehicle:index,free:true,extraRank:-1,
      gate:()=>vehicleGroup.visible&&c.on,
      follow(p,out){const cy=Math.cos(c.yaw),sy=Math.sin(c.yaw);out.set(c.pos.x+cy*lx+sy*lz,c.pos.y+.241,c.pos.z-sy*lx+cy*lz);p.yawNow=c.yaw+turn;}});}
  for(const level of [1,2,3])venueRiderReserve[level]=3*chivas.filter(x=>x.c.rank<VEHICLE_TIER_CAP[level]).length;
  const carts=furnitureItems.filter(f=>f.kind==='cart').sort((a,b)=>(b.stage!==undefined)-(a.stage!==undefined)||a.index-b.index).slice(0,12);
  for(const f of carts){const back=new THREE.Vector3(Math.sin(f.yaw),0,Math.cos(f.yaw)),p=f.world.clone().addScaledVector(back,-.14);
    groups.vend.push({pose:'vend',archetype:8,job:'apron',district:f.district,x:p.x,y:f.world.y,z:p.z,yaw:f.yaw,cart:f.index,gate:awake(f.district)});}
  const clubs=venueList.filter(v=>v.type==='club').sort((a,b)=>finalOpen(b)-finalOpen(a)||(b.district==='working')-(a.district==='working')||a.index-b.index).slice(0,3);
  for(const v of clubs){
    // The bouncer stands beside the door; three people queue along the face and step up once a bar.
    const bouncer=v.face.clone().addScaledVector(v.normal,v.stand).addScaledVector(v.right,-.2);
    groups.queue.push({pose:'queue',archetype:8,job:'security',district:v.district,x:bouncer.x,y:v.z,z:bouncer.z,yaw:v.yaw,venue:v.index,needs:.5});
    const along=Math.atan2(-v.right.x,-v.right.z);
    for(let k=0;k<3;k++){
      groups.queue.push({pose:'queue',district:v.district,x:0,y:v.z,z:0,yaw:along,venue:v.index,needs:.5,
        follow(p,out){const b=reduced?0:beat.now().totalBeats/4,bar=Math.floor(b),step=THREE.MathUtils.smoothstep(Math.min(1,(b-bar)*4),0,1);
          const slot=((k-bar)%3+3)%3,from=slot===2?3:slot+1,at=from+(slot-from)*step;
          out.copy(v.face).addScaledVector(v.normal,v.stand).addScaledVector(v.right,-.08+at*.11);out.y=v.z;p.yawNow=along;}});
    }
  }
  // One waiter at each of eight bus stops, taken district by district.
  const stopsBy=new Map();for(const f of furnitureItems)if(f.kind==='busstop'){if(!stopsBy.has(f.district))stopsBy.set(f.district,[]);stopsBy.get(f.district).push(f);}
  const stopLists=[...stopsBy.values()];
  for(let round=0;groups.wait.length<8&&round<8;round++)for(const list of stopLists){if(groups.wait.length>=8)break;const f=list[round];if(!f)continue;
    const front=new THREE.Vector3(Math.sin(f.yaw),0,Math.cos(f.yaw)),p=f.world.clone().addScaledVector(front,.02);
    groups.wait.push({pose:'queue',district:f.district,x:p.x,y:f.world.y,z:p.z,yaw:f.yaw,gate:awake(f.district)});}
  // C3.4: two people dance on each of three open bar terraces, on free spots between the tables.
  const clubSet=new Set(clubs.map(v=>v.index)),terraceBy=new Map();
  for(const f of furnitureItems)if(f.venue>=0&&(f.kind==='table'||f.kind==='chair')){if(!terraceBy.has(f.venue))terraceBy.set(f.venue,[]);terraceBy.get(f.venue).push(f);}
  const probe=new THREE.Vector3();
  const dancing=venueList.filter(v=>(v.type==='bar'||v.type==='club')&&v.terrace>0&&!clubSet.has(v.index)).sort((a,b)=>finalOpen(b)-finalOpen(a)||a.index-b.index);
  for(const v of dancing){if(groups.dance.length>=6)break;const set=terraceBy.get(v.index)||[],spots=[];
    for(let a=v.stand+.02;a<=v.terrace+.06&&spots.length<2;a+=.05)for(const b of [.3,-.3,.2,-.2,.1,-.1,0]){if(spots.length>=2)break;
      const along=b*v.length;probe.copy(v.face).addScaledVector(v.normal,a).addScaledVector(v.right,along);probe.y=v.z+.05;
      if(set.some(f=>Math.hypot(f.world.x-probe.x,f.world.z-probe.z)<(f.kind==='table'?.15:.1)))continue;
      if(spots.some(s=>Math.hypot(s.x-probe.x,s.z-probe.z)<.16))continue;
      if(pointBlocked(probe,.07,false))continue;
      spots.push({x:probe.x,z:probe.z});}
    if(spots.length<2)continue;
    spots.forEach((s,k)=>{const o=spots[1-k];groups.dance.push({pose:'dance',district:v.district,x:s.x,y:v.z,z:s.z,yaw:Math.atan2(o.x-s.x,o.z-s.z),venue:v.index,needs:.5,energy:.75+.25*k});});}
  // Seated patrons fill a few terraces well: the first chair while the venue is quiet (one patron),
  // two more once it is open (C4.4), open-at-the-end venues first, district by district.
  const seatBudget=EXTRA_CAP-venueRiderReserve[3]-groups.vend.length-groups.queue.length-groups.wait.length-groups.dance.length;
  const byVenue=new Map();for(const f of furnitureItems)if(f.kind==='chair'){if(!byVenue.has(f.venue))byVenue.set(f.venue,[]);byVenue.get(f.venue).push(f);}
  const tables=furnitureItems.filter(f=>f.kind==='table'),dancedAt=new Set(groups.dance.map(e=>e.venue));
  const seatVenues=[...byVenue.keys()].filter(vi=>!dancedAt.has(vi)).sort((a,b)=>finalOpen(venueList[b])-finalOpen(venueList[a])||a-b);
  const seatOrder=[],seatByDistrict=new Map();for(const vi of seatVenues){const d=venueList[vi].district;if(!seatByDistrict.has(d))seatByDistrict.set(d,[]);seatByDistrict.get(d).push(vi);}
  const seatLists=[...seatByDistrict.values()];for(let round=0;seatOrder.length<seatVenues.length;round++)for(const list of seatLists)if(list[round]!==undefined)seatOrder.push(list[round]);
  for(const vi of seatOrder){if(groups.sit.length>=seatBudget)break;const v=venueList[vi],chairs=byVenue.get(vi);
    for(let k=0;k<Math.min(3,chairs.length)&&groups.sit.length<seatBudget;k++){const f=chairs[k];
      const table=tables.find(t=>t.venue===vi&&t.world.distanceTo(f.world)<.12);
      groups.sit.push({pose:'sit',archetype:v.type==='tienda'?9:undefined,bottle:true,district:f.district,x:f.world.x,y:f.world.y,z:f.world.z,
        yaw:table?Math.atan2(table.world.x-f.world.x,table.world.z-f.world.z):f.yaw,venue:vi,needs:k===0?.05:.5});}}
  const keys=[];
  Object.values(groups).forEach((list,gi)=>list.forEach((e,j)=>keys.push([(j+.5)/list.length,gi,e])));
  keys.sort((a,b)=>a[0]-b[0]||a[1]-b[1]).slice(0,EXTRA_CAP-venueRiderReserve[3]).forEach((key,rank)=>{key[2].extraRank=rank;venueExtras.push(key[2]);});
  venueExtras.push(...riders);
}

// C4.4: a venue follows its host note. Lit 0.5 or more: open and full. Lit but fainter: open and
// quiet. Dark: shuttered. Absent: not there at all. Terrace sets and patrons follow their venue.
const VENUE_MESHES=[storefronts,awnings,...signMeshes];
const VENUE_STATE_CODE={absent:0,shut:1,quiet:2,open:3};
function updateVenues(){
  const frontOpen=storefronts.geometry.attributes.aOpen;let moved=false;
  for(let i=0;i<venueList.length;i++){
    const v=venueList[i],n=v.host;
    v.present=n.state!=='absent';
    v.state=!v.present?'absent':n.state==='lit'?(n.light>=.5?'open':'quiet'):'shut';
    v.open=v.state==='open'?1:v.state==='quiet'?.4:0;
    v.grow=v.present?Math.min(1,(n.rise??1)*1.5):0;
    setStreetGlow(v.glow,v.present&&v.open>0?(.4+.8*v.open)*v.grow:0);
    const key=VENUE_STATE_CODE[v.state]*32+(v.grow*20|0);if(key===v.drawn)continue;v.drawn=key;moved=true;
    frontOpen.setX(v.index,v.open);v.signMesh.geometry.attributes.aOpen.setX(v.signSlot,v.open);v.signMesh.geometry.attributes.aOpen.needsUpdate=true;
    placeVenue(v);
    v.furnitureOn=v.open>0&&v.grow>=1;
  }
  if(moved){
    frontOpen.needsUpdate=true;
    for(let i=0;i<VENUE_MESHES.length;i++)VENUE_MESHES[i].instanceMatrix.needsUpdate=true;
    for(let i=0;i<furnitureItems.length;i++){const f=furnitureItems[i];if(f.venue<0)continue;const s=venueList[f.venue].furnitureOn?1:0;venueSet(f.mesh,f.slot,f.world,f.yaw,s,s,s);f.mesh.instanceMatrix.needsUpdate=true;}
  }
  const extras=crowd.extras;
  for(let i=0;i<extras.length;i++){const p=extras[i];if(p.venue===undefined)continue;const v=venueList[p.venue];p.hidden=!(v.furnitureOn&&v.present&&v.open>0&&v.open>=(p.needs||0));}
  // The week poster carries the timeline's week number (appendix G: a number, B6); redrawn only when it changes.
  const week=Math.floor(state.t);if(week!==posterWeek){posterWeek=week;drawPoster(7,week);posterTexture.needsUpdate=true;}
}
for(const m of [storefronts,awnings,...signMeshes])m.instanceColor.needsUpdate=true;
function venueOf(n){return n?venueByHost.get(n.id)||null:null;}
const venues={items:venueList,furniture:furnitureItems,byHost:venueByHost,of:venueOf,update:updateVenues,extras:venueExtras,riderReserve:venueRiderReserve,
  names:VENUE_NAMES,graffiti:GRAFFITI_WORDS,posterLines:POSTER_LINES,atlases:{signs:signCanvases,tags:[tagCanvas],posters:[posterCanvas]},stops:venueStops,
  materials:{front:frontMat,signs:signMeshes.map(m=>m.material),vehicle:vehicleMat,posters:posterMat,furniture:furnitureMat},
  // Read-only handles for QA (C4.4 gate): the storefront, awning, sign and poster instance buffers.
  meshes:{front:storefronts,awnings,signs:signMeshes,posters},
  stages:stages.map(s=>({district:s.district,name:s.name,kind:s.kind,x:s.center.x,z:s.center.z,up:s.center.y,r:s.r,capacity:s.capacity})),
  census(){const perDistrict={},count=s=>venueList.filter(v=>v.state===s).length;for(const v of venueList)perDistrict[v.district]=(perDistrict[v.district]||0)+1;
    return {total:venueList.length,perDistrict,open:count('open'),quiet:count('quiet'),shut:count('shut'),absent:count('absent'),
      terraces:venueList.filter(v=>v.terrace>0).length,posters:posterSlots.length,furniture:Object.fromEntries(Object.entries(furnitureMeshes).map(([k,m])=>[k,m.count]))};}};
