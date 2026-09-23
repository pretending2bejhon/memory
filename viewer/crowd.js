// Citizens: instanced body parts in outfits (C3). Walkers step on the beat, dancers fill the
// stages, one DJ per stage. Every pose is a function of the beat clock; nothing here is a note.
const peopleGroup=new THREE.Group();scene.add(peopleGroup);
// extras: the queues, seated patrons, vendors, bus stop waiters, terrace dancers and chiva riders society.js
// adds (C3.7). Tier 1 keeps the phone budget of 220 people (C13.1): 100 walkers, 88 dancers, 12 DJs, 20 others.
const CROWD_CAPS={3:{walkers:400,dancers:480,extras:88},2:{walkers:240,dancers:288,extras:53},1:{walkers:100,dancers:88,extras:20}};
// Chiva riders ride with their chiva; society.js reserves their share of each extras cap from the chiva ranks.
const riderReserve=typeof venueRiderReserve!=='undefined'?venueRiderReserve:{1:0,2:0,3:0};
const extrasCap=level=>Math.max(0,CROWD_CAPS[level].extras-riderReserve[level]);

// ------------------------------------------------------------------ outfits (C3.2, C3.3)
const pickFrom=(rnd,list,weights)=>{
  if(!weights)return list[Math.floor(rnd()*list.length)];
  let total=0;for(const w of weights)total+=w;let x=rnd()*total;
  for(let i=0;i<list.length;i++){x-=weights[i];if(x<=0)return list[i];}
  return list[list.length-1];
};
const SKIN=['#3a2118','#57351f','#6e452e','#86573a','#9d6947','#b37c56','#c49269','#d4a67f','#e2bb99','#efd2b8'];
const SKIN_WEIGHT=[4,7,11,15,17,16,12,9,6,3];
const HAIR=['#100b09','#1b130e','#2c1e15','#453021','#664630','#8f6d49','#c4a168'];
const HAIR_WEIGHT=[30,25,18,11,7,5,4];
const DYED=['#ff5fb8','#4fb4ff','#e8ecef','#5cf08e'];
const ARCHETYPE_WEIGHTS={
  core:[20,20,10,10,15,10,5,5,5,0],episodic:[10,10,10,5,20,5,10,10,20,0],semantic:[5,10,5,15,20,15,5,5,20,0],
  procedural:[20,45,0,5,10,10,0,10,0,0],prospective:[35,10,5,0,15,5,10,20,0,0],working:[15,20,5,25,15,10,0,10,0,0],
  jhon:[5,0,35,5,15,0,5,5,30,0],prasma:[5,15,0,10,20,40,0,10,0,0],branding:[30,10,10,15,15,10,5,5,0,0],
  onebrain:[10,20,0,5,10,45,0,10,0,0],reef:[15,0,10,5,10,0,45,10,5,0],inbox:[5,5,5,0,15,5,5,10,0,50]};
const NEON=['#ff3d9a','#39ff88','#29e6ff','#ffe03a','#ff8a1f','#b26bff'];
function dress(district,rnd,archetype,job){
  if(archetype===undefined)archetype=pickFrom(rnd,[1,2,3,4,5,6,7,8,9,10],ARCHETYPE_WEIGHTS[district]||ARCHETYPE_WEIGHTS.working);
  const skin=pickFrom(rnd,SKIN,SKIN_WEIGHT),hair=rnd()<.08?pickFrom(rnd,DYED):pickFrom(rnd,HAIR,HAIR_WEIGHT);
  const o={archetype,skin,hair,top:'#8a9099',sleeve:null,bottom:'#2b2f36',leg:null,acc:{},hairStyle:rnd()<.55?'short':rnd()<.8?'long':'none'};
  const acc=o.acc;
  switch(archetype){
    case 1:o.top=pickFrom(rnd,NEON);o.sleeve=skin;o.bottom=pickFrom(rnd,['#1a1a1a','#4d5a3a','#6e6450','#2b2f36']);
      if(rnd()<.5)acc.visor=pickFrom(rnd,NEON);if(rnd()<.7)acc.glow=pickFrom(rnd,NEON);if(rnd()<.15)acc.cap=pickFrom(rnd,['#111','#f2f2f2']);break;
    case 2:o.top=pickFrom(rnd,['#0d0d0f','#161618','#1f1f22']);o.bottom=pickFrom(rnd,['#0b0b0c','#18181a']);
      if(rnd()<.45)acc.bucket='#0e0e10';if(rnd()<.1)acc.visor='#6be7e1';break;
    case 3:o.top=pickFrom(rnd,['#ffd400','#1b4fd8','#e0242b','#f4f4f4','#0a8f3c','#ff7a00']);o.sleeve=rnd()<.6?skin:null;
      o.bottom=pickFrom(rnd,['#0e1f5c','#111111','#f2f2f2','#1b4fd8']);o.leg=skin;if(rnd()<.6)acc.chain='#e8c35a';if(rnd()<.55)acc.cap=pickFrom(rnd,['#111111','#f2f2f2','#e0242b','#1b4fd8']);break;
    case 4:{const metal=pickFrom(rnd,['#c0c6cc','#d4af37','#b3122e','#0b0b0b','#ff4fa0','#5a2bff']);o.top=metal;
      if(rnd()<.6){acc.skirt=metal;o.sleeve=skin;o.leg=skin;o.bottom=metal;}else o.bottom=pickFrom(rnd,['#0b0b0b','#c0c6cc','#2a2a2e']);break;}
    case 5:o.top=pickFrom(rnd,['#8a8f96','#1c1c1e','#f0f0f0','#ff6a2b','#2f6bff','#6b3fa0','#3f7d4f']);o.bottom=pickFrom(rnd,['#2a2a2e','#6d7078','#11151c']);if(rnd()<.2)acc.cap=pickFrom(rnd,['#111111','#ff6a2b']);break;
    case 6:o.top=pickFrom(rnd,['#1c2228','#232a31','#2a2f24']);o.bottom=pickFrom(rnd,['#15191d','#1f2429']);if(rnd()<.8)acc.strips='#dfe8ec';if(rnd()<.25)acc.backpack='#101418';break;
    case 7:o.top=pickFrom(rnd,['#ff8a3d','#23c4b0','#a55bff','#ff5fa2','#ffd24a','#4ad1ff']);o.sleeve=rnd()<.5?skin:null;o.bottom=pickFrom(rnd,['#f2e8d5','#7b4b94','#2a6f97','#c2462b']);
      if(rnd()<.45)acc.crown=pickFrom(rnd,['#ff6fa8','#ffd24a','#8cf29a']);if(o.hairStyle==='short'&&rnd()<.5)o.hairStyle='long';break;
    case 8:{if(!job)job=district==='prospective'&&rnd()<.6?'vis':pickFrom(rnd,['apron','bar','security']);
      if(job==='vis'){o.top='#d4f000';o.bottom='#1d2a44';acc.strips='#f4f4f4';}
      else if(job==='apron'){o.top=pickFrom(rnd,['#f1ece2','#d9d2c4']);o.bottom='#2f3440';acc.apron=pickFrom(rnd,['#f7f7f7','#7a4a2a']);}
      else {o.top='#0e0e10';o.bottom='#0e0e10';}break;}
    case 9:if(rnd()<.6){o.top=pickFrom(rnd,['#f3eee2','#e8e4d8','#d9e6f2']);o.sleeve=rnd()<.5?skin:null;}else o.top=pickFrom(rnd,['#6b3b2a','#4a3a5a','#7d6a4a']);
      o.bottom=pickFrom(rnd,['#bba98a','#5d5d5d','#2c3a4f']);if(rnd()<.45)acc.sombrero='#e7dcc2';break;
    case 10:o.top=pickFrom(rnd,['#8a8f96','#2f6bff','#f0f0f0','#3f7d4f','#b3122e']);o.bottom=pickFrom(rnd,['#2a2a2e','#6d7078','#bba98a']);
      if(rnd()<.8)acc.backpack=pickFrom(rnd,['#d9481c','#1d6fd8','#2b2b2b','#3f7d4f']);if(rnd()<.6)acc.suitcase=pickFrom(rnd,['#1d1d20','#6b3fa0','#c0c6cc']);break;
  }
  o.sleeve=o.sleeve||o.top;o.leg=o.leg||o.bottom;
  if(acc.cap||acc.bucket||acc.sombrero)o.hairStyle=o.hairStyle==='long'?'long':'none';
  return o;
}

// ------------------------------------------------------------------ geometry and materials (C3.1)
// Person space: feet at the origin, facing +z, 1 unit ~ 4.5 m. Limbs pivot at their joints.
const J={hipY:.13,hipX:.025,torsoY:.15,shoulderY:.27,shoulderX:.064,neckY:.285};
const box=(w,h,d,x=0,y=0,z=0)=>new THREE.BoxGeometry(w,h,d).translate(x,y,z);
const merge=(...list)=>{const out=new THREE.BufferGeometry(),pos=[],nor=[];
  for(const g of list){const n=g.index?g.toNonIndexed():g;pos.push(...n.attributes.position.array);nor.push(...n.attributes.normal.array);}
  out.setAttribute('position',new THREE.Float32BufferAttribute(pos,3));out.setAttribute('normal',new THREE.Float32BufferAttribute(nor,3));return out;};
const PART_GEOMETRY={
  torso:box(.1,.13,.062,0,.065,0),hips:box(.096,.042,.06,0,0,0),
  legA:box(.034,.13,.04,0,-.065,0),legB:box(.034,.13,.04,0,-.065,0),
  armA:box(.026,.125,.034,0,-.0625,0),armB:box(.026,.125,.034,0,-.0625,0),
  head:new THREE.IcosahedronGeometry(.037,0).translate(0,.04,0),
  hair:new THREE.SphereGeometry(.04,7,4,0,TAU,0,Math.PI/2).scale(1,.8,1).translate(0,.046,-.004),
};
const ACCESSORY_GEOMETRY={
  longHair:box(.072,.09,.022,0,.012,-.03),
  cap:merge(new THREE.SphereGeometry(.041,7,3,0,TAU,0,Math.PI/2).translate(0,.046,0),box(.05,.006,.042,0,.05,.034)),
  bucket:new THREE.CylinderGeometry(.036,.052,.034,9).translate(0,.074,0),
  sombrero:merge(new THREE.CylinderGeometry(.088,.088,.006,14).translate(0,.066,0),new THREE.CylinderGeometry(.012,.04,.045,10).translate(0,.09,0)),
  crown:new THREE.TorusGeometry(.04,.007,4,10).rotateX(Math.PI/2).translate(0,.066,0),
  visor:box(.076,.016,.012,0,.047,.033),
  backpack:box(.078,.088,.04,0,.07,-.052),chain:box(.052,.006,.006,0,.11,.033),
  apron:box(.086,.13,.006,0,.01,.034),strips:merge(box(.006,.12,.006,-.03,.065,.033),box(.006,.12,.006,.03,.065,.033)),
  skirt:new THREE.CylinderGeometry(.05,.078,.09,10).translate(0,-.045,0),
  glow:box(.011,.065,.011,0,-.135,.012),
  suitcase:merge(box(.07,.095,.036,.115,.05,.01),box(.008,.06,.008,.115,.125,.01)),
  // Held in the fist: the body at the hand, the neck further along the arm, so a raised arm lifts it upright.
  bottle:merge(new THREE.CylinderGeometry(.009,.009,.045,6).translate(0,-.13,.014),new THREE.CylinderGeometry(.006,.004,.02,6).translate(0,-.1625,.014)),
};
// Where each accessory hangs: the joint whose motion it follows.
const ACCESSORY_ATTACH={longHair:'head',cap:'head',bucket:'head',sombrero:'head',crown:'head',visor:'head',
  backpack:'torso',chain:'torso',apron:'torso',strips:'torso',skirt:'hips',glow:'arms',suitcase:'root',bottle:'armA'};
const EMISSIVE=new Set(['visor','glow','strips']);
const personUniforms={uKey:{value:KEY},uKick:{value:0},uEnergy:{value:1},uCut:{value:1}};
const personVertex=`attribute vec3 aTint;attribute float aLit;varying vec3 vColor,vN,vTint;varying float vLit;
  #include <fog_pars_vertex>
  void main(){vColor=instanceColor;vTint=aTint;vLit=aLit;vN=normalize(mat3(modelMatrix)*mat3(instanceMatrix)*normal);
    vec4 mvPosition=modelViewMatrix*instanceMatrix*vec4(position,1.0);gl_Position=projectionMatrix*mvPosition;
    #include <fog_vertex>
  }`;
const bodyMat=new THREE.ShaderMaterial({fog:true,uniforms:THREE.UniformsUtils.merge([THREE.UniformsLib.fog]),vertexShader:personVertex,
  fragmentShader:`uniform vec3 uKey;uniform float uKick,uEnergy,uCut;varying vec3 vColor,vN,vTint;varying float vLit;
    #include <fog_pars_fragment>
    void main(){vec3 n=normalize(vN);float d=max(dot(n,uKey),0.0),up=n.y*.5+.5;
      vec3 c=vColor*(.34+.46*d+.14*up)+vTint*vLit*(.10+.24*uKick*uEnergy)*uCut*(.55+.45*up);
      gl_FragColor=vec4(c,1.0);
      #include <fog_fragment>
      #include <colorspace_fragment>
    }`});
const glowMat=new THREE.ShaderMaterial({fog:true,uniforms:THREE.UniformsUtils.merge([THREE.UniformsLib.fog]),vertexShader:personVertex,
  fragmentShader:`uniform float uKick,uEnergy,uCut;varying vec3 vColor,vN,vTint;varying float vLit;
    #include <fog_pars_fragment>
    void main(){gl_FragColor=vec4(vColor*(1.05+.7*uKick*uEnergy)*uCut,1.0);
      #include <fog_fragment>
      #include <colorspace_fragment>
    }`});
for(const m of [bodyMat,glowMat])Object.assign(m.uniforms,personUniforms);

// ------------------------------------------------------------------ the population
const WALKERS=400;
const people=[],crowdRnd=mulberry(811);
const routeWeights=routes.map(r=>r.length),routeTotal=routeWeights.reduce((a,b)=>a+b,0);
// Weighted round-robin so any prefix of the walkers still covers every street.
const walkerRoutes=[];{const credit=routes.map(()=>0);
  for(let i=0;i<WALKERS;i++){let best=0;for(let r=0;r<routes.length;r++){credit[r]+=routeWeights[r]/routeTotal;if(credit[r]>credit[best])best=r;}credit[best]-=1;walkerRoutes.push(best);}}
// C3.4 from Run B: every eighth walker crosses a bridge (a roads.js walk path: ring sidewalk, fillet
// corner, bridge sidewalk, far corner, far ring sidewalk, and back), so each tier's prefix keeps its
// share; paths are dealt by length the same weighted way. The walkers' random draws are unchanged, so
// everyone else is dressed and placed exactly as before; a bridge walker's outfit follows its bridge's
// district through a separate stream.
const bridgeWalks=roadNet&&roadNet.walkPaths||[],bridgeRnd=mulberry(4027),walkPathOf=[];
{const total=bridgeWalks.reduce((a,p)=>a+p.length,0),credit=bridgeWalks.map(()=>0);
  for(let i=0;i<WALKERS;i++){if(!bridgeWalks.length||i%8!==3){walkPathOf.push(-1);continue;}
    let best=0;for(let k=0;k<bridgeWalks.length;k++){credit[k]+=bridgeWalks[k].length/total;if(credit[k]>credit[best])best=k;}credit[best]-=1;walkPathOf.push(best);}}
for(let i=0;i<WALKERS;i++){
  const route=routes[walkerRoutes[i]],relaxed=crowdRnd()<.3,stride=relaxed?.09+crowdRnd()*.03:.08+crowdRnd()*.03,path=walkPathOf[i]>=0?bridgeWalks[walkPathOf[i]]:null;
  const distance=crowdRnd()*(path||route).length,offset=crowdRnd()*2,scale=.9+crowdRnd()*.22,outfit=dress(route.district,crowdRnd);
  people.push({kind:0,district:path?path.district:route.district,route:walkerRoutes[i],path,distance,side:i%2?1:-1,relaxed,
    speed:stride*(relaxed?1.1667:2.3333),offset,scale,energy:1,style:'walk',outfit:path?dress(path.district,bridgeRnd):outfit});
}
const STYLE_BY_ROOM={core:'nod',episodic:'skank',semantic:'twostep',procedural:'stomp',prospective:'handsup',working:'pump',
  jhon:'baile',prasma:'tight',branding:'robot',onebrain:'glitch',reef:'wave',inbox:'nod'};
const STYLE_ALTS={nod:['bounce','sway'],skank:['sway','bounce'],twostep:['sway','bounce'],stomp:['pump','bounce'],handsup:['pump','shuffle'],
  pump:['bounce','handsup'],baile:['bounce','sway'],tight:['twostep','robot'],robot:['glitch','bounce'],glitch:['robot','nod'],wave:['sway','nod'],sway:['nod','bounce']};
const stageSlots=stages.map(()=>[]);
// Food carts stand on the decks (society.js); nobody dances on a cart or its vendor.
const deckCarts=(typeof furnitureItems!=='undefined'?furnitureItems:[]).filter(f=>f.kind==='cart'&&f.stage!==undefined)
  .map(f=>({stage:f.stage,x:f.world.x,z:f.world.z,vx:f.world.x-Math.sin(f.yaw)*.14,vz:f.world.z-Math.cos(f.yaw)*.14}));
for(const s of stages){
  const slots=[],spacing=.17,carts=deckCarts.filter(c=>c.stage===s.index);
  for(let gx=-s.r;gx<=s.r;gx+=spacing)for(let gz=-s.r;gz<=s.r;gz+=spacing*.866){
    const ox=gx+(Math.round(gz/(spacing*.866))%2?spacing/2:0),x=s.center.x+ox,z=s.center.z+gz;
    if(Math.hypot(ox,gz)>s.r-.13)continue;
    const dx=x-s.booth.x,dz=z-s.booth.z;
    if(Math.hypot(dx,dz)<.5||dx*s.facing.x+dz*s.facing.z>-.2)continue;
    if(carts.some(c=>Math.hypot(x-c.x,z-c.z)<.26||Math.hypot(x-c.vx,z-c.vz)<.2))continue;
    // Front rows fill first, but loosely, so a thin crowd still spreads over the floor.
    slots.push({x:x+(crowdRnd()-.5)*.05,z:z+(crowdRnd()-.5)*.05,d:Math.hypot(dx,dz)*.55+crowdRnd()*s.r*.75});
  }
  slots.sort((a,b)=>a.d-b.d);
  for(const slot of slots.slice(0,s.capacity)){
    const style=crowdRnd()<.7?STYLE_BY_ROOM[s.district]:pickFrom(crowdRnd,STYLE_ALTS[STYLE_BY_ROOM[s.district]]);
    const p={kind:1,district:s.district,stage:s.index,x:slot.x,y:s.z,z:slot.z,yaw:Math.atan2(s.booth.x-slot.x,s.booth.z-slot.z)+(crowdRnd()-.5)*.5,
      offset:(crowdRnd()-.5)*.125,scale:.9+crowdRnd()*.22,energy:.6+crowdRnd()*.6,style,seed:crowdRnd(),outfit:dress(s.district,crowdRnd)};
    stageSlots[s.index].push(people.length);people.push(p);
  }
}
const djs=stages.map(s=>{const p=s.booth.clone().addScaledVector(s.facing,.2);
  const person={kind:2,district:s.district,stage:s.index,x:p.x,y:s.z,z:p.z,yaw:s.yaw,offset:0,scale:1.02,energy:1,style:'dj',seed:crowdRnd(),outfit:dress(s.district,crowdRnd,2)};
  people.push(person);return person;});
// V3 adds seated, vending, queueing and riding people through crowd.extras before this runs.
const extraPeople=(typeof venueExtras!=='undefined'?venueExtras:[]).map(e=>{const person={kind:3,offset:0,energy:1,seed:crowdRnd(),scale:.92+crowdRnd()*.18,...e,outfit:dress(e.district,crowdRnd,e.archetype,e.job)};
  if(e.bottle)person.outfit.acc.bottle=pickFrom(crowdRnd,['#2f5a1e','#5a3514','#c7d7c9']);
  // Terrace dancers take the room style like the stage crowd (C3.5): the room's own at 70 %, else an alternate.
  if(person.pose==='dance'&&!person.style){const room=STYLE_BY_ROOM[person.district]||'bounce';person.style=crowdRnd()<.7?room:pickFrom(crowdRnd,STYLE_ALTS[room]);}
  people.push(person);return person;});

const PEOPLE=people.length;
const personParts={},accessoryMeshes={};
const skinColor=new THREE.Color();
function partMesh(geometry,material,count){
  const mesh=new THREE.InstancedMesh(geometry,material,count);mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);mesh.frustumCulled=false;
  geometry.setAttribute('aTint',new THREE.InstancedBufferAttribute(new Float32Array(count*3),3));
  geometry.setAttribute('aLit',new THREE.InstancedBufferAttribute(new Float32Array(count),1));
  peopleGroup.add(mesh);return mesh;
}
for(const [name,geometry] of Object.entries(PART_GEOMETRY))personParts[name]=partMesh(geometry,bodyMat,PEOPLE);
// Accessories hold only their wearers; person.acc maps accessory name to slot.
const wearers={};
for(const name of Object.keys(ACCESSORY_GEOMETRY))wearers[name]=[];
people.forEach((p,i)=>{p.acc=[];const o=p.outfit;
  const want=[];if(o.hairStyle==='long')want.push(['longHair',o.hair]);
  for(const [name,color] of Object.entries(o.acc))want.push([name,color]);
  for(const [name,color] of want){if(!wearers[name])continue;wearers[name].push(i);p.acc.push({name,slot:wearers[name].length-1,color});}
});
for(const [name,list] of Object.entries(wearers)){
  const count=Math.max(1,name==='glow'?list.length*2:list.length);
  accessoryMeshes[name]=partMesh(ACCESSORY_GEOMETRY[name],EMISSIVE.has(name)?glowMat:bodyMat,count);
}
const tintOf=p=>districtLight(p.district);
people.forEach((p,i)=>{
  const o=p.outfit,tint=tintOf(p),lit=p.kind===1||p.kind===2?1:p.kind===3?.45:.22;
  const paint=(name,color)=>{const m=personParts[name];m.setColorAt(i,skinColor.set(color));m.geometry.attributes.aTint.setXYZ(i,tint.r,tint.g,tint.b);m.geometry.attributes.aLit.setX(i,lit);};
  paint('torso',o.top);paint('hips',o.bottom);paint('legA',o.leg);paint('legB',o.leg);paint('armA',o.sleeve);paint('armB',o.sleeve);
  paint('head',o.skin);paint('hair',o.hairStyle==='none'?o.skin:o.hair);
  for(const a of p.acc){const mesh=accessoryMeshes[a.name],slots=a.name==='glow'?[a.slot*2,a.slot*2+1]:[a.slot];
    for(const k of slots){mesh.setColorAt(k,skinColor.set(a.color));mesh.geometry.attributes.aTint.setXYZ(k,tint.r,tint.g,tint.b);mesh.geometry.attributes.aLit.setX(k,lit);}}
});
const personMeshes=[...Object.values(personParts),...Object.values(accessoryMeshes)];
const arrays={};for(const [name,mesh] of Object.entries(personParts))arrays[name]=mesh.instanceMatrix.array;
for(const mesh of personMeshes){if(mesh.instanceColor)mesh.instanceColor.needsUpdate=true;mesh.geometry.attributes.aTint.needsUpdate=true;mesh.geometry.attributes.aLit.needsUpdate=true;}

// ------------------------------------------------------------------ poses (C3.4 to C3.6)
// One matrix writer: world = T(root) * Ry(yaw) * S(s) * T(joint) * Rz(b) * Rx(a) * S(part).
// The per-frame loop writes a person's parts through writePose: the person's frame goes into WP once
// (position, scale, the feet's and the upper body's yaw, the three heights, the leg stretch) and each part
// is chosen by an integer kind, so no call passes a number that would be boxed (C13.4). A part's matrix
// turns it by a about x and b about z at its joint (jx, jy, jz), scales it and turns the whole by the yaw.
const WP=new Float64Array(11),WP_X=0,WP_Z=1,WP_S=2,WP_CY=3,WP_SY=4,WP_CU=5,WP_SU=6,WP_LEG=7,WP_BODY=8,WP_GROUND=9,WP_LEGS=10;
const PART_LEG_A=0,PART_LEG_B=1,PART_HIPS=2,PART_TORSO=3,PART_ARM_A=4,PART_ARM_B=5,PART_HEAD=6,PART_HIP_ACC=7,PART_GROUND=8;
function writePose(array,index,kind){
  let py=WP[WP_BODY],cy=WP[WP_CU],sy=WP[WP_SU],jx=0,jy=0,a=0,b=0,syy=1;
  if(kind===PART_LEG_A||kind===PART_LEG_B){py=WP[WP_LEG];cy=WP[WP_CY];sy=WP[WP_SY];jx=kind===PART_LEG_A?J.hipX:-J.hipX;jy=J.hipY-pose.dip;a=kind===PART_LEG_A?pose.lA:pose.lB;syy=WP[WP_LEGS];}
  else if(kind===PART_HIPS){cy=WP[WP_CY];sy=WP[WP_SY];jy=J.hipY+.01;}
  else if(kind===PART_TORSO){jy=J.torsoY;a=pose.lean;}
  else if(kind===PART_ARM_A){jx=J.shoulderX;jy=J.shoulderY;a=pose.aA;b=pose.bA;}
  else if(kind===PART_ARM_B){jx=-J.shoulderX;jy=J.shoulderY;a=pose.aB;b=pose.bB;}
  else if(kind===PART_HEAD){jy=J.neckY;a=pose.nod;}
  else if(kind===PART_HIP_ACC){cy=WP[WP_CY];sy=WP[WP_SY];jy=J.hipY+.03;}
  else{py=WP[WP_GROUND];cy=WP[WP_CY];sy=WP[WP_SY];}
  const px=WP[WP_X],pz=WP[WP_Z],s=WP[WP_S],jz=0,sx=1,sz=1;
  const o=index*16,ca=Math.cos(a),sa=Math.sin(a),cb=Math.cos(b),sb=Math.sin(b);
  const m00=cy*cb,m01=-cy*sb*ca+sy*sa,m02=cy*sb*sa+sy*ca,m10=sb,m11=cb*ca,m12=-cb*sa,m20=-sy*cb,m21=sy*sb*ca+cy*sa,m22=-sy*sb*sa+cy*ca;
  const kx=s*sx,ky=s*syy,kz=s*sz;
  array[o]=m00*kx;array[o+1]=m10*kx;array[o+2]=m20*kx;array[o+3]=0;
  array[o+4]=m01*ky;array[o+5]=m11*ky;array[o+6]=m21*ky;array[o+7]=0;
  array[o+8]=m02*kz;array[o+9]=m12*kz;array[o+10]=m22*kz;array[o+11]=0;
  array[o+12]=px+s*(cy*jx+sy*jz);array[o+13]=py+s*jy;array[o+14]=pz+s*(-sy*jx+cy*jz);array[o+15]=1;
}
function hideIndex(array,index){const o=index*16;for(let k=0;k<16;k++)array[o+k]=0;}
const pose={dip:0,jump:0,sway:0,twist:0,lean:0,nod:0,aA:0,bA:0,aB:0,bB:0,lA:0,lB:0};
const ROBOT=[[-1.57,0,-1.57,0,0],[-1.57,0,0,-1.3,.35],[0,1.45,0,-1.45,0],[-3.0,-.1,0,-.2,-.3],[-1.57,1.2,-1.57,-1.2,0],[-.2,.25,-2.4,-.3,.3]];
function stylePose(style,t,e,seed,out){
  const TWO=Math.PI*2,p=((t%1)+1)%1,bi=Math.floor(t),beatWave=.5+.5*Math.cos(TWO*p);
  out.dip=0;out.jump=0;out.sway=0;out.twist=0;out.lean=0;out.nod=.12*e*beatWave;
  out.aA=-.35;out.bA=.12;out.aB=-.35;out.bB=-.12;out.lA=0;out.lB=0;
  switch(style){
    case 'nod':out.dip=.006*e*beatWave;out.nod=.28*e*beatWave;out.aA=-.25;out.aB=-.25;break;
    case 'bounce':out.dip=.016*e*beatWave;out.aA=out.aB=-.55-.3*e*beatWave;out.bA=.22;out.bB=-.22;break;
    case 'sway':out.sway=.018*e*Math.sin(Math.PI*t/2);out.twist=.18*e*Math.sin(Math.PI*t/2);out.dip=.006*e*beatWave;out.aA=-.4+.15*Math.sin(Math.PI*t/2);out.aB=-.4-.15*Math.sin(Math.PI*t/2);break;
    case 'skank':{const k=Math.max(0,Math.sin(Math.PI*t)),m=Math.max(0,-Math.sin(Math.PI*t));out.lA=-.8*e*k;out.lB=-.8*e*m;out.dip=.012*e*beatWave;
      out.aA=-1.0-.55*e*Math.sin(Math.PI*t);out.aB=-1.0+.55*e*Math.sin(Math.PI*t);out.bA=.35;out.bB=-.35;out.lean=.08;break;}
    case 'twostep':out.sway=.022*e*Math.sin(Math.PI*t);out.lA=-.35*e*Math.max(0,Math.sin(Math.PI*t));out.lB=-.35*e*Math.max(0,-Math.sin(Math.PI*t));
      out.aA=-.45+.35*Math.sin(Math.PI*t);out.aB=-.45-.35*Math.sin(Math.PI*t);out.dip=.008*e*beatWave;break;
    case 'tight':out.sway=.014*e*Math.sin(Math.PI*t);out.dip=.008*e*beatWave;out.aA=out.aB=-1.3;out.bA=-.55*(.5+.5*Math.cos(TWO*p));out.bB=-out.bA;out.nod=.2*e*beatWave;break;
    case 'stomp':out.dip=.02*e*beatWave;out.lA=-.25*e*Math.max(0,Math.sin(Math.PI*t));out.aA=-1.25-1.45*e*Math.pow(Math.max(0,Math.cos(TWO*(p-.5))),2);out.bA=-.1;out.aB=-.9;out.bB=-.2;out.nod=.35*e*beatWave;out.lean=.1;break;
    case 'pump':{const up=Math.pow(Math.max(0,Math.cos(TWO*(p-.5))),2),left=bi%2===0;out.dip=.018*e*beatWave;
      if(left){out.aA=-1.3-1.5*e*up;out.bA=-.12;out.aB=-.7;out.bB=-.2;}else{out.aB=-1.3-1.5*e*up;out.bB=.12;out.aA=-.7;out.bA=.2;}out.nod=.22*e*beatWave;break;}
    case 'handsup':out.aA=-2.75+.12*Math.sin(Math.PI*t);out.aB=-2.75-.12*Math.sin(Math.PI*t);out.bA=-.35;out.bB=.35;out.dip=.015*e*beatWave;
      out.jump=(bi%4===0||bi%4===2)?.035*e*Math.max(0,Math.sin(Math.PI*p)):0;break;
    case 'shuffle':out.lA=.55*e*Math.sin(TWO*t);out.lB=-out.lA;out.dip=.012*e*(.5+.5*Math.cos(2*TWO*p));out.aA=-.9+.4*Math.sin(TWO*t);out.aB=-.9-.4*Math.sin(TWO*t);break;
    case 'baile':out.sway=.026*e*Math.sin(Math.PI*t);out.twist=.38*e*Math.sin(Math.PI*t);out.dip=.014*e*beatWave;out.aA=-.7;out.aB=-.7;out.bA=.35+.2*Math.sin(Math.PI*t);out.bB=-.35+.2*Math.sin(Math.PI*t);break;
    case 'robot':case 'glitch':{let k=bi;if(style==='glitch'&&((bi*7+Math.floor(seed*13))%5===0))k=bi-1;
      const r=ROBOT[((k+Math.floor(seed*97))%ROBOT.length+ROBOT.length)%ROBOT.length],snap=Math.min(1,p*8);
      out.aA=r[0]*snap+(-.3)*(1-snap);out.bA=r[1]*snap;out.aB=r[2]*snap+(-.3)*(1-snap);out.bB=r[3]*snap;out.twist=r[4]*snap;out.nod=0;
      if(style==='glitch'&&p>.85)out.twist+=.05*Math.sin(t*90);break;}
    case 'wave':out.aA=-2.6+.25*Math.sin(Math.PI*t/4);out.aB=-2.6+.25*Math.sin(Math.PI*t/4+1);out.bA=-.35-.3*Math.sin(Math.PI*t/4);out.bB=.35-.3*Math.sin(Math.PI*t/4);
      out.sway=.016*e*Math.sin(Math.PI*t/4);out.dip=.005*e*beatWave;out.nod=.08;break;
    case 'dj':out.dip=.012*beatWave;out.nod=.32*beatWave;out.aA=-1.15;out.bA=.05;out.aB=-1.05+.12*Math.sin(Math.PI*t/2);out.bB=-.08;out.lean=.1;break;
  }
}
function walkPose(t,relaxed,out){
  const w=Math.sin(Math.PI*(relaxed?t/2:t));
  out.dip=.006*Math.abs(Math.cos(Math.PI*(relaxed?t/2:t)));out.jump=0;out.sway=0;out.twist=0;out.lean=.02;out.nod=0;
  out.lA=-.42*w;out.lB=.42*w;out.aA=.3*w;out.bA=.08;out.aB=-.3*w;out.bB=-.08;
}
function stillPose(kind,t,out){
  out.dip=0;out.jump=0;out.sway=0;out.twist=0;out.lean=0;out.nod=.05*Math.sin(Math.PI*t/2);out.aA=-.2;out.bA=.1;out.aB=-.2;out.bB=-.1;out.lA=0;out.lB=0;
  if(kind==='sit'){out.lA=out.lB=-1.45;out.dip=.075;out.aA=out.aB=-.9;}
  else if(kind==='vend'){out.aA=out.aB=-1.0;out.lean=.12;}
  else if(kind==='queue'){out.aA=-.15;out.aB=-.15;out.nod=.1*(.5+.5*Math.cos(Math.PI*2*t));}
  else if(kind==='ride'){out.dip=.012*(.5+.5*Math.cos(Math.PI*2*t));out.aA=-2.5;out.aB=-1.2;out.bA=-.3;}
}

// Grammar state (C3.6): the whole city reacts to the active room's transition.
let freezeBeat=-1,dropBeat=-1e9,stabUntil=0;
beat.on('cut',()=>{freezeBeat=beat.now().totalBeats;});
beat.on('drop',()=>{freezeBeat=-1;dropBeat=beat.now().totalBeats;});
beat.on('hit',h=>{if(h.layer==='stab')stabUntil=beat.now().totalBeats+.5;});

const crowdState={walkers:CROWD_CAPS[phone?1:3].walkers,dancerCap:CROWD_CAPS[phone?1:3].dancers,extras:extrasCap(phone?1:3),stageVisible:stages.map(()=>0),stageTarget:stages.map(()=>0),frame:0};
const shown=new Uint8Array(PEOPLE);
const camWorld=new THREE.Vector3(),walkPoint=new THREE.Vector3(),walkAhead=new THREE.Vector3();
function isVisible(i,p){
  if(p.kind===0)return i<crowdState.walkers;
  if(p.kind===1){const list=stageSlots[p.stage];return p.rank<crowdState.stageVisible[p.stage];}
  // Kind 3: inside the tier cap (riders hold a reserved share), then either its own gate (riders follow
  // their chiva, street people their district's stage) or the venue state.
  if(p.kind===3)return (p.free===true||p.extraRank<crowdState.extras)&&(p.gate?p.gate():p.hidden!==true);
  return p.hidden!==true;
}
stageSlots.forEach(list=>list.forEach((index,rank)=>{people[index].rank=rank;}));
function setTimeline(stats){
  let total=0;
  stages.forEach((s,i)=>{const st=stats[s.district]||{density:0,brightness:0};crowdState.stageTarget[i]=s.capacity*st.density*(.25+.75*st.brightness);total+=crowdState.stageTarget[i];});
  const scale=total>crowdState.dancerCap?crowdState.dancerCap/total:1;
  stages.forEach((s,i)=>{crowdState.stageVisible[i]=Math.min(stageSlots[i].length,Math.round(crowdState.stageTarget[i]*scale));});
}
let lastStats=null;
function applyCrowdTier(level){const cap=CROWD_CAPS[level];crowdState.walkers=cap.walkers;crowdState.dancerCap=cap.dancers;crowdState.extras=extrasCap(level);if(lastStats)setTimeline(lastStats);}

function updatePeople(dt,now){
  if(!peopleGroup.visible)return;
  const frameIndex=crowdState.frame++,b=beat.now(),live=!reduced;
  const tr=beat.transition,stage=tr.active?tr.stage:'groove';
  camWorld.copy(camera.position);
  for(let i=0;i<PEOPLE;i++){
    const p=people[i],visible=isVisible(i,p);
    if(!visible){
      if(shown[i]){shown[i]=0;for(const name in arrays)hideIndex(arrays[name],i);
        for(const a of p.acc){const arr=accessoryMeshes[a.name].instanceMatrix.array;if(a.name==='glow'){hideIndex(arr,a.slot*2);hideIndex(arr,a.slot*2+1);}else hideIndex(arr,a.slot);}}
      continue;
    }
    // Walkers keep walking every frame; far people refresh their pose less often.
    let px,py,pz,yaw;
    if(p.kind===0){
      // A bridge walk path already runs on its walking line; a ring walker keeps to its side's lane.
      const route=p.path||routes[p.route],offset=p.path?0:Math.min(route.width/2+.04,route.clearance-.12);
      p.distance+=live?dt*p.speed*p.side:0;
      sampleRoute(route,p.distance,walkPoint,offset*p.side);
      const far=walkPoint.distanceToSquared(camWorld);
      if(shown[i]&&far>2025&&(i+frameIndex)%(far>8100?6:3))continue;
      sampleRoute(route,p.distance+.15*p.side,walkAhead,offset*p.side);
      px=walkPoint.x;py=walkPoint.y+.006;pz=walkPoint.z;yaw=Math.atan2(walkAhead.x-walkPoint.x,walkAhead.z-walkPoint.z);
    } else {
      px=p.x;py=p.y+.002;pz=p.z;yaw=p.yaw;
      if(p.follow){p.follow(p,walkPoint);px=walkPoint.x;py=walkPoint.y;pz=walkPoint.z;yaw=p.yawNow;}
      const dx=px-camWorld.x,dz=pz-camWorld.z,far=dx*dx+dz*dz;
      if(shown[i]&&!p.follow&&far>2025&&(i+frameIndex)%(far>8100?6:3))continue;
    }
    shown[i]=1;
    const t=b.totalBeats+p.offset;
    if(!live){stillPose(p.kind===3?p.pose:'stand',0,pose);if(p.kind===0)walkPose(0,false,pose);}
    else if(p.kind===0)walkPose(t,p.relaxed,pose);
    else if(p.kind===3&&p.pose!=='ride'&&p.pose!=='dance'){stillPose(p.pose,t,pose);
      // Seated patrons raise the bottle for one bar on the drop.
      if(p.pose==='sit'){const since=b.totalBeats-dropBeat;if(since>=0&&since<4){pose.aA=-2.75;pose.bA=.12;pose.nod=-.15;}}}
    else{
      let e=p.energy,tt=t;
      if(stage==='bridge')e*=.5;
      if(stage==='cut'&&freezeBeat>=0)tt=freezeBeat+p.offset;
      stylePose(p.style,tt,e,p.seed,pose);
      if(stage==='bridge')pose.nod-=.32;
      const crowdMember=p.kind===1||p.kind===3;
      if(stage==='riser'&&crowdMember){const ph=((tt%1)+1)%1,close=.45*(.5+.5*Math.cos(Math.PI*2*ph));pose.aA=-2.85;pose.aB=-2.85;pose.bA=close;pose.bB=-close;pose.nod=-.25;}
      const since=b.totalBeats-dropBeat;
      if(since>=0&&since<4){if(since<1)pose.jump=.08*Math.sin(Math.PI*since);
        if(crowdMember){pose.aA=-2.8;pose.bA=-.3;pose.aB=-2.8;pose.bB=.3;}else pose.aB=-2.9;}
      if(p.style==='handsup'&&b.totalBeats<stabUntil)pose.jump=Math.max(pose.jump,.03);
    }
    const s=p.scale,cy=Math.cos(yaw),sy=Math.sin(yaw),cu=Math.cos(yaw+pose.twist),su=Math.sin(yaw+pose.twist);
    px+=pose.sway*cy;pz-=pose.sway*sy;
    const lift=pose.jump,body=py+lift-pose.dip*s,legScale=(J.hipY-pose.dip)/J.hipY;
    WP[WP_X]=px;WP[WP_Z]=pz;WP[WP_S]=s;WP[WP_CY]=cy;WP[WP_SY]=sy;WP[WP_CU]=cu;WP[WP_SU]=su;WP[WP_LEG]=py+lift;WP[WP_BODY]=body;WP[WP_GROUND]=py;WP[WP_LEGS]=legScale;
    writePose(arrays.legA,i,PART_LEG_A);
    writePose(arrays.legB,i,PART_LEG_B);
    writePose(arrays.hips,i,PART_HIPS);
    writePose(arrays.torso,i,PART_TORSO);
    writePose(arrays.armA,i,PART_ARM_A);
    writePose(arrays.armB,i,PART_ARM_B);
    writePose(arrays.head,i,PART_HEAD);
    writePose(arrays.hair,i,PART_HEAD);
    for(let k=0;k<p.acc.length;k++){
      const a=p.acc[k],arr=accessoryMeshes[a.name].instanceMatrix.array,at=ACCESSORY_ATTACH[a.name];
      if(at==='head')writePose(arr,a.slot,PART_HEAD);
      else if(at==='torso')writePose(arr,a.slot,PART_TORSO);
      else if(at==='hips')writePose(arr,a.slot,PART_HIP_ACC);
      else if(at==='armA')writePose(arr,a.slot,PART_ARM_A);
      else if(at==='arms'){writePose(arr,a.slot*2,PART_ARM_A);writePose(arr,a.slot*2+1,PART_ARM_B);}
      else writePose(arr,a.slot,PART_GROUND);
    }
  }
  for(const mesh of personMeshes)mesh.instanceMatrix.needsUpdate=true;
  personUniforms.uKick.value=rave.uniforms.uKick.value;personUniforms.uEnergy.value=rave.uniforms.uEnergy.value*rave.uniforms.uSourceIntensity.value;personUniforms.uCut.value=rave.uniforms.uCut.value;
}
for(const mesh of personMeshes)for(let i=0;i<mesh.count;i++)hideIndex(mesh.instanceMatrix.array,i);

function census(){
  let walkers=0,dancers=0,djCount=0,others=0;
  people.forEach((p,i)=>{if(!isVisible(i,p))return;if(p.kind===0)walkers++;else if(p.kind===1)dancers++;else if(p.kind===2)djCount++;else others++;});
  return {walkers,dancers,djs:djCount,others,perStage:stages.map((s,i)=>({district:s.district,visible:crowdState.stageVisible[i],capacity:s.capacity,target:crowdState.stageTarget[i]}))};
}
const crowd={people,parts:personParts,accessories:accessoryMeshes,stages,stageSlots,djs,extras:extraPeople,caps:CROWD_CAPS,riderReserve,state:crowdState,census,
  setTimeline(stats){lastStats=stats;setTimeline(stats);},applyTier:applyCrowdTier,isVisible,
  get count(){return census();}};
