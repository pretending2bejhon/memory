// Shared visual policy. Note windows and street lamps never enter this bus.
const lights = (() => {
  const settings=['Full','Soft','Calm'];
  let setting='Full', level=0, flashHead=0, flashSize=0;
  try { const saved=localStorage.getItem('vc-lights'); if(settings.includes(saved)) setting=saved; } catch {}
  if(reduced) setting='Calm';
  const flashes=new Float64Array(3);
  const api={
    get setting(){return setting;},
    get calm(){return reduced||setting==='Calm';},
    get intensity(){return level;},
    get amplitude(){return setting==='Full'?1:setting==='Soft'?.5:.2;},
    get modeFactor(){return state.ride<0?.6:1;},
    get cutFactor(){return api.calm?1:setting==='Soft'?.5:.15;},
    get strobes(){return !reduced&&setting==='Full';},
    get colorDuration(){return api.calm?60/140*4:0;},
    setSetting(value){
      if(!settings.includes(value)) throw new Error('Unknown Lights setting');
      setting=reduced?'Calm':value;
      document.getElementById('lights-setting').value=setting;
      try { localStorage.setItem('vc-lights',setting); } catch {}
    },
    // Large flashes use one common rolling budget, shared by all scenery.
    requestFlash(now=performance.now()){
      if(api.calm) return false;
      if(flashSize===3 && now-flashes[flashHead]<1000) return false;
      flashes[flashHead]=now;flashHead=(flashHead+1)%3;flashSize=Math.min(3,flashSize+1);
      return true;
    },
    // Beat modulation cannot itself create a threshold-sized excursion.
    pulse(value){return Math.min(.08,Math.max(0,value)*.08)*level;},
    update(dt){
      const target=api.amplitude*api.modeFactor;
      const duration=api.calm?60/140*4:.2;
      level+=Math.sign(target-level)*Math.min(Math.abs(target-level),Math.max(0,dt)/duration);
    }
  };
  const select=document.getElementById('lights-setting');
  select.value=setting;select.disabled=reduced;
  select.addEventListener('change',()=>api.setSetting(select.value));
  return api;
})();

// The tier governor (C13.2), on three-second rolling means kept without allocating a frame history.
// Every frame interval and work time is clamped to 100 ms first, so one long frame (a GC, the Sound
// start, a tab switch) cannot drop a tier by itself; the frame loop also holds the governor through load,
// the Sound start and a return from the background (hold).
// Drop: one tier when the mean frame interval passes 19 ms over 3 s.
// Climb: one tier after 10 s whose rolling 3 s mean frame WORK time (frame() itself, render call
// included, measured by the page loop) stays under 12 ms. Intervals cannot show headroom on a
// vsync-capped display (16.7 ms at 60 Hz), so a climb rule on intervals never fired and one stall pinned
// Tier 1 for good. The work time cannot see the GPU or a busy machine, so a climb also needs the frames
// to keep the display's pace (3 s mean interval under 18 ms) and to miss almost none (under 3 % of the
// window's intervals over 20 ms): a page still missing frames at its tier never climbs, even when the
// misses are too sparse to lift the mean (one in 16 frames at 33 ms is a 17.8 ms mean but a 33 ms p95,
// over the 22 ms budget of C13.3, and the 19 ms drop rule would never take it back).
// Backoff: a drop within 30 s of a climb means the climbed-into tier could not be held. It doubles the
// fast span the next climb needs (up to 80 s; back to 10 s once a climb holds for a minute), and after
// two such failures into one tier the page stops trying that tier for the session, so a GPU-bound page
// (its work time looks light while the GPU is the limit) cannot keep flipping the crowd and traffic
// counts on screen.
// The music comes first: the frame loop reports the audio clock's rate against the wall clock every two
// seconds while the sound plays. Below 0.95 the audio thread renders slower than real time (the music
// drags and cuts out), so the page gives it room: one tier down (at most every 3 s), and no climb until
// the clock has been healthy for 20 s.
// Without a work time (the QA feeds only intervals) the interval stands in for it: the work inside a
// frame never exceeds it. A tier change never touches the camera: crowd, traffic and bloom change at
// once, and entering or leaving Tier 1 (pixel ratio 1) resizes the canvas at the next idle moment
// (retune in the page).
const tier = (() => {
  const SPAN=3000,DROP_MS=19,CLIMB_MS=12,PACE_MS=18,SLOW_MS=20,SLOW_SHARE=.03,CLAMP_MS=100,STARVED=.95,CALM_MS=20000;
  const WAIT_MS=10000,WAIT_MAX=80000,HELD_MS=60000,FAILED_MS=30000;
  const times=new Float64Array(1024),values=new Float64Array(1024),works=new Float64Array(1024);
  let current=phone?1:3,head=0,count=0,sum=0,workSum=0,slow=0,clockMs=0,fastMs=0,changedAt=0;
  let climbedAt=-Infinity,climbWait=WAIT_MS,holdUntil=0,calmUntil=0,audioDropAt=-Infinity,audioRate=1;
  const failedClimbs=new Uint8Array(4);
  function apply(){
    crowd.applyTier(current);
    cars.mesh.count=vehicleCount();
    bloomSize();
    retune();
  }
  function reset(){head=0;count=0;sum=0;workSum=0;slow=0;fastMs=0;}
  function drop(){
    if(clockMs-climbedAt<FAILED_MS){climbWait=Math.min(climbWait*2,WAIT_MAX);failedClimbs[current]++;climbedAt=-Infinity;}
    current--;changedAt=clockMs;fastMs=0;apply();
  }
  const api={
    initial:phone?1:3,
    get current(){return current;},
    get meanMs(){return count?sum/count:0;},
    // The mean work time and the next climb's wait, each under both names the gates and probes read.
    get meanWorkMs(){return count?workSum/count:0;},
    get workMeanMs(){return count?workSum/count:0;},
    get slowShare(){return count?slow/count:0;},
    get settledForMs(){return clockMs-changedAt;},
    get climbNeedMs(){return climbWait;},
    get climbWaitMs(){return climbWait;},
    get holdUntil(){return holdUntil;},
    get audioRate(){return audioRate;},
    get failedClimbs(){return [failedClimbs[2],failedClimbs[3]];},
    // Real frames are ignored until performance.now() passes holdUntil; the window restarts.
    hold(ms){holdUntil=Math.max(holdUntil,performance.now()+ms);reset();},
    audio(rate){
      const now=performance.now();audioRate=rate;
      if(rate>=STARVED)return;
      calmUntil=now+CALM_MS;fastMs=0;
      if(current>1&&now-audioDropAt>=3000){audioDropAt=now;drop();}
    },
    update(ms,workMs=ms){
      ms=Math.min(ms,CLAMP_MS);workMs=Math.min(workMs,CLAMP_MS);
      clockMs+=ms;
      while(count && (clockMs-times[head]>SPAN || count===1024)){
        sum-=values[head];workSum-=works[head];if(values[head]>SLOW_MS)slow--;head=(head+1)%1024;count--;
      }
      const slot=(head+count)%1024;times[slot]=clockMs;values[slot]=ms;works[slot]=workMs;sum+=ms;workSum+=workMs;if(ms>SLOW_MS)slow++;count++;
      const mean=sum/count,workMean=workSum/count;
      fastMs=workMean<CLIMB_MS&&mean<PACE_MS&&slow<SLOW_SHARE*count?fastMs+ms:0;
      if(climbWait>WAIT_MS&&changedAt===climbedAt&&clockMs-changedAt>=HELD_MS)climbWait=WAIT_MS;
      if(clockMs-changedAt>=SPAN && clockMs-times[head]>=SPAN-100 && mean>DROP_MS && current>1){
        drop();
      } else if(fastMs>=climbWait && current<3 && !phone && performance.now()>=calmUntil && failedClimbs[current+1]<2){
        current++;changedAt=clockMs;climbedAt=clockMs;fastMs=0;apply();
      }
    },
    apply
  };
  return api;
})();

function compileWorld(){
  // Hidden toggles must not compile their first shader during a ride or cut.
  const hiddenObjects=[],materials=new Set();
  scene.traverse(object=>{
    if(!object.visible){hiddenObjects.push(object);object.visible=true;}
    if(object.material){
      if(Array.isArray(object.material)) for(const material of object.material) materials.add(material);
      else materials.add(object.material);
    }
  });
  renderer.compile(scene,camera);
  for(const object of hiddenObjects) object.visible=false;
  // Warm the postprocessing shaders as well as the world materials.
  composer.render();
  let compiledMaterialCount=0;
  for(const material of materials) if(renderer.properties.get(material).programs?.size) compiledMaterialCount++;
  return {complete:compiledMaterialCount===materials.size,materialCount:materials.size,compiledMaterialCount,programCount:renderer.info.programs.length};
}

// The rave is scenery. None of these uniforms or buffers belongs to a note.
const rave = (() => {
  const BAR=beat.barSeconds, BEAT=beat.beatSeconds, TAU=Math.PI*2;
  const roomIds=['core','episodic','semantic','procedural','prospective','working','jhon','prasma','branding','onebrain','reef','inbox'];
  const palettes={},hsl={h:0,s:0,l:0};
  for(const id of roomIds){
    const color=col(styleOf(id).light);color.getHSL(hsl);
    const accent=new THREE.Color().setHSL((hsl.h+150/360)%1,Math.max(.35,hsl.s),Math.max(.24,hsl.l));
    palettes[id]={color,accent};
  }
  palettes.skyline=palettes.working;
  const spectrum=new Float32Array(16),wave=new Float32Array(32),frequencyBytes=new Uint8Array(2048),waveBytes=new Uint8Array(4096);
  const bandLo=new Uint16Array(16),bandHi=new Uint16Array(16);let analyserFrame=0;
  for(let i=0;i<16;i++){bandLo[i]=Math.floor(Math.pow(i/16,2)*700);bandHi[i]=Math.max(bandLo[i]+1,Math.floor(Math.pow((i+1)/16,2)*700));}
  const ripples=Array.from({length:16},()=>new THREE.Vector4(0,0,-100,0));
  const uniforms={uTime:{value:0},uClock:{value:0},uBeat:{value:0},uColor:{value:palettes.working.color.clone()},
    uAccent:{value:palettes.working.accent.clone()},uNight:{value:col(DEEP)},uEnergy:{value:0},uSourceIntensity:{value:.5},
    uKick:{value:0},uHat:{value:0},uPad:{value:0},uStab:{value:0},uBass:{value:0},uFlash:{value:0},uClap:{value:0},
    uCut:{value:1},uDesaturate:{value:0},uRiser:{value:0},uStage:{value:0},uRipples:{value:ripples},
    uSpectrum:{value:spectrum},uWave:{value:wave},uMorph:{value:1}};
  const transition={stage:'groove',source:'silent',serial:0,appliedAt:0,frame:0,bridge:0,riser:0,cut:0,drop:0};
  const eventRing=Array.from({length:64},()=>({name:'',source:'',serial:0,time:0,appliedAt:0,frame:0}));
  const shellHistory=Array.from({length:32},()=>({room:'',bar:0,cycle:0,shells:0,at:0,frame:0}));
  const diagnostics={eventRing,eventCount:0,shellHistory,fireworkEvents:0,lastFireworkBar:-1,lastFireworkRoom:'',
    screenAtlasCount:1,screenAtlasSize:1024,rippleSpeed:20,rippleLifetime:1.5,lastUpdateFrame:0};
  let rippleHead=0,paletteRoom='skyline',colorStart=0,lastBar=-Infinity,lastCycle=-Infinity,lastCycleRoom='',motion=0;
  let kick=0,hat=0,pad=0,stab=0,bass=0,flash=0,clap=0,fanUntil=0,morphStart=-100;
  const fromColor=uniforms.uColor.value.clone(),fromAccent=uniforms.uAccent.value.clone();
  const targetColor=uniforms.uColor.value.clone(),targetAccent=uniforms.uAccent.value.clone();
  const patterns=['fan','sweep','scissor','tunnel','converge-up'];
  const clockNow=()=>beat.diagnostics.lastFrameMs/1000;
  function selectPalette(id){
    id=palettes[id]?id:'skyline';if(id===paletteRoom)return;
    paletteRoom=id;colorStart=clockNow();fromColor.copy(uniforms.uColor.value);fromAccent.copy(uniforms.uAccent.value);
    targetColor.copy(palettes[id].color);targetAccent.copy(palettes[id].accent);
    if(!lights.calm){uniforms.uColor.value.copy(targetColor);uniforms.uAccent.value.copy(targetAccent);}
  }
  function ripple(id,gain){
    if(reduced)return;
    const d=id==='skyline'?'core':id,p=DATA.plateaus[d]||DATA.plateaus.core;
    const stages=DATA.design.stages;let x=p.cx,z=-p.cy;
    for(let i=0;i<stages.length;i++)if(stages[i].district===d){x=stages[i].x;z=-stages[i].y;break;}
    ripples[rippleHead].set(x,z,clockNow(),Math.min(1,gain));rippleHead=(rippleHead+1)%ripples.length;
  }
  function applyTransition(name,tr){
    transition.stage=name;transition.source=tr.source;transition.serial=tr.serial;
    transition.appliedAt=beat.diagnostics.lastFrameMs;transition.frame=beat.diagnostics.frame;transition[name]=tr[name==='bridge'?'start':name];
    const row=eventRing[diagnostics.eventCount++%eventRing.length];
    row.name=name;row.source=tr.source;row.serial=tr.serial;row.time=transition[name];row.appliedAt=transition.appliedAt;row.frame=transition.frame;
    uniforms.uStage.value=name==='bridge'?1:name==='riser'?2:name==='cut'?3:4;
    uniforms.uCut.value=name==='cut'?lights.cutFactor:1;
    if(name==='drop'){
      selectPalette(tr.to);fanUntil=clockNow()+BAR;
      if(lights.requestFlash(beat.diagnostics.lastFrameMs))flash=1;
      ripple(tr.to,1);
    }
  }
  beat.on('bridge',tr=>applyTransition('bridge',tr));beat.on('riser',tr=>applyTransition('riser',tr));
  beat.on('cut',tr=>applyTransition('cut',tr));beat.on('drop',tr=>applyTransition('drop',tr));
  beat.on('hit',hit=>{
    if(hit.gain<=0||reduced)return;
    const value=Math.min(1,hit.gain);
    if(hit.layer==='kick'){kick=Math.max(kick,value);ripple(hit.room,value);}
    else if(hit.layer==='hatC'||hit.layer==='hatO')hat=Math.max(hat,value);
    else if(hit.layer==='pad')pad=Math.max(pad,value);
    else if(hit.layer==='stab'){stab=Math.max(stab,value);fanUntil=clockNow()+BEAT*.5;}
    else if(hit.layer==='bass')bass=Math.max(bass,value);
    // Claps flash the small panels through the same limiter as the cloud flash.
    else if(hit.layer==='clap'&&lights.strobes&&lights.requestFlash(beat.diagnostics.lastFrameMs))clap=Math.max(clap,value);
  });

  const sky=new THREE.Mesh(new THREE.SphereGeometry(1800,32,16),new THREE.ShaderMaterial({
    side:THREE.BackSide,depthWrite:false,fog:false,uniforms,
    vertexShader:`varying vec3 vDirection;void main(){vDirection=normalize(position);gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0);}`,
    fragmentShader:`varying vec3 vDirection;uniform float uTime,uEnergy,uSourceIntensity,uKick,uPad,uStab,uFlash,uCut,uDesaturate,uRiser;
      uniform vec3 uColor,uAccent,uNight;
      float hash(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453);}
      float noise(vec2 p){vec2 i=floor(p),f=fract(p);f=f*f*(3.0-2.0*f);return mix(mix(hash(i),hash(i+vec2(1,0)),f.x),mix(hash(i+vec2(0,1)),hash(i+1.0),f.x),f.y);}
      void main(){vec3 d=normalize(vDirection);float h=max(0.0,d.y);
        vec3 paint=mix(uColor,uNight*3.0,uDesaturate*.88),accent=mix(uAccent,uNight*2.0,uDesaturate*.88);
        float horizon=exp(-h*9.0),ceiling=smoothstep(-.04,.14,d.y);
        vec2 cloudUV=d.xz/(.22+h)*2.8+vec2(uTime*.007,-uTime*.004);
        float cloud=noise(cloudUV)*.65+noise(cloudUV*2.1)*.35;
        float deck=smoothstep(.43,.78,cloud)*exp(-pow((h-.17)*5.0,2.0));
        float az=atan(d.z,d.x),ribbon=sin(az*5.0+sin(az*2.0+uTime*.033)*2.0+uTime*.012);
        float aurora=exp(-pow((h-.29-ribbon*.10)*17.0,2.0))*(.4+.6*noise(vec2(az*6.0,h*11.0+uTime*.04)));
        vec3 base=mix(uNight,vec3(.005,.009,.021),smoothstep(0.0,.75,h));
        vec3 glow=paint*horizon*(.075+uKick*.07+uRiser*.03)+paint*deck*(.065+uFlash*.12);
        glow+=accent*aurora*(.05+uPad*.06+uStab*.04);
        vec3 c=(base+glow*uEnergy*uSourceIntensity)*uCut*ceiling+uNight*(1.0-ceiling);
        gl_FragColor=vec4(c,1.0);
        #include <colorspace_fragment>
      }`
  }));sky.renderOrder=-20;sky.frustumCulled=false;scene.add(sky);
  const starRandom=mulberry(99),starPositions=new Float32Array(700*3),starSeeds=new Float32Array(700);
  for(let i=0;i<700;i++){
    const a=starRandom()*TAU,e=.06+Math.pow(starRandom(),1.6)*1.3;
    starPositions[i*3]=1700*Math.cos(e)*Math.cos(a);starPositions[i*3+1]=1700*Math.sin(e);starPositions[i*3+2]=1700*Math.cos(e)*Math.sin(a);starSeeds[i]=starRandom();
  }
  const starGeometry=new THREE.BufferGeometry();starGeometry.setAttribute('position',new THREE.BufferAttribute(starPositions,3));starGeometry.setAttribute('aSeed',new THREE.BufferAttribute(starSeeds,1));
  const starField=new THREE.Points(starGeometry,new THREE.ShaderMaterial({uniforms,transparent:true,depthWrite:false,
    vertexShader:`attribute float aSeed;varying float vSeed;void main(){vSeed=aSeed;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0);gl_PointSize=1.2+aSeed*1.4;}`,
    fragmentShader:`varying float vSeed;uniform float uHat,uEnergy,uSourceIntensity,uCut;uniform vec3 uAccent;void main(){float d=length(gl_PointCoord-.5);if(d>.5)discard;gl_FragColor=vec4(mix(vec3(.34,.47,.65),uAccent,.25),(.32+uHat*uEnergy*uSourceIntensity*.45)*uCut*(1.0-d*2.0));
      #include <colorspace_fragment>
    }`
  }));starField.frustumCulled=false;scene.add(starField);

  const grid=new THREE.Mesh(new THREE.PlaneGeometry(1600,1600),new THREE.ShaderMaterial({uniforms,
    vertexShader:`varying vec3 vWorld;void main(){vec4 p=modelMatrix*vec4(position,1.0);vWorld=p.xyz;gl_Position=projectionMatrix*viewMatrix*p;}`,
    fragmentShader:`varying vec3 vWorld;uniform vec3 uColor,uNight;uniform float uClock,uEnergy,uSourceIntensity,uCut,uBass;uniform vec4 uRipples[16];
      float line(vec2 p){vec2 w=max(fwidth(p),vec2(.001));vec2 g=abs(fract(p-.5)-.5)/w;return 1.0-min(min(g.x,g.y),1.0);}
      void main(){vec2 p=vWorld.xz;float minor=line(p),major=line(p/8.0),rings=0.0;
        for(int i=0;i<16;i++){float age=uClock-uRipples[i].z;float radius=age*20.0;float on=step(0.0,age)*step(age,1.5);float ring=exp(-pow((length(p-uRipples[i].xy)-radius)*1.7,2.0));rings+=ring*on*(1.0-age/1.5)*uRipples[i].w;}
        vec3 c=uNight*.65+uColor*((minor*.028+major*.075)*(.35+uEnergy)+rings*(.2+uBass*.04)*uEnergy*uSourceIntensity)*uCut;
        gl_FragColor=vec4(c,1.0);
        #include <colorspace_fragment>
      }`
  }));grid.rotation.x=-Math.PI/2;grid.position.y=-.02;grid.frustumCulled=false;scene.add(grid);
  // The grid floor's shader did not link until 'active' (a reserved word in GLSL ES 3.00) was renamed,
  // so the floor has never been seen. Lit, it changes the whole ground; it stays hidden until the owner
  // has looked at it (grid.visible=true shows it). Its ripple uniforms keep updating either way.
  grid.visible=false;

  const core=DATA.plateaus.core,coreNodes=nodes.filter(n=>n.district==='core').sort((a,b)=>b.h-a.h),towers=nodes.filter(n=>n.district==='working').sort((a,b)=>b.h-a.h);
  const laserHosts=[],laserOrigins=[];
  for(let i=0;i<14;i++){laserHosts.push(i<8?coreNodes[0]:towers[Math.floor((i-8)/2)]);laserOrigins.push(new THREE.Vector3());}
  const beamVertex=`varying vec2 vUV;varying float vHeight;
    #include <fog_pars_vertex>
    void main(){vUV=uv;vHeight=position.y;vec4 mvPosition=modelViewMatrix*instanceMatrix*vec4(position,1.0);gl_Position=projectionMatrix*mvPosition;
      #include <fog_vertex>
    }`;
  const beamMaterial=new THREE.ShaderMaterial({uniforms,transparent:true,blending:THREE.AdditiveBlending,depthWrite:false,side:THREE.DoubleSide,forceSinglePass:true,fog:true,
    vertexShader:beamVertex,fragmentShader:`varying vec2 vUV;varying float vHeight;uniform vec3 uColor,uNight;uniform float uEnergy,uSourceIntensity,uCut,uDesaturate,uStab,uRiser;
      #include <fog_pars_fragment>
      void main(){float edge=pow(max(0.0,sin(vUV.x*3.14159265)),.45),fade=pow(1.0-vHeight,.7);vec3 c=mix(uColor,uNight*4.0,uDesaturate*.8)*(.48+uStab*.28+uRiser*.12);
        gl_FragColor=vec4(c,edge*fade*.70*uEnergy*uSourceIntensity*uCut);
        #include <fog_fragment>
        #include <colorspace_fragment>
      }`
  });
  Object.assign(beamMaterial.uniforms,THREE.UniformsUtils.clone(THREE.UniformsLib.fog));
  const lasers=new THREE.InstancedMesh(new THREE.CylinderGeometry(.011,.065,1,5,1,true).translate(0,.5,0),beamMaterial,14);
  lasers.instanceMatrix.setUsage(THREE.DynamicDrawUsage);lasers.frustumCulled=false;scene.add(lasers);
  const searchMaterial=new THREE.ShaderMaterial({uniforms,transparent:true,blending:THREE.AdditiveBlending,depthWrite:false,side:THREE.DoubleSide,forceSinglePass:true,fog:true,
    vertexShader:beamVertex,fragmentShader:`varying vec2 vUV;varying float vHeight;uniform vec3 uAccent;uniform float uEnergy,uSourceIntensity,uCut;
      #include <fog_pars_fragment>
      void main(){float edge=pow(max(0.0,sin(vUV.x*3.14159265)),1.3);gl_FragColor=vec4(uAccent*.65,edge*pow(1.0-vHeight,1.2)*.10*uEnergy*uSourceIntensity*uCut);
        #include <fog_fragment>
        #include <colorspace_fragment>
      }`
  });
  const searchlights=new THREE.InstancedMesh(new THREE.CylinderGeometry(1.7,.05,1,10,1,true).translate(0,.5,0),searchMaterial,4);
  searchlights.instanceMatrix.setUsage(THREE.DynamicDrawUsage);searchlights.frustumCulled=false;scene.add(searchlights);
  const beamDummy=new THREE.Object3D(),up=new THREE.Vector3(0,1,0),direction=new THREE.Vector3();

  // Normalized strokes are resampled once into one equal-sized point set per glyph.
  const glyphStrokes={
    core:[[[0,1],[.18,.18],[1,0],[.18,-.18],[0,-1],[-.18,-.18],[-1,0],[-.18,.18],[0,1]],[[0,-1],[0,1]],[[-1,0],[1,0]]],
    episodic:[Array.from({length:150},(_,i)=>{const a=i/149*TAU*2.6,r=.1+i/149*.85;return [Math.cos(a)*r,Math.sin(a)*r];})],
    semantic:[[[-.95,.55],[-.12,.3],[0,.15],[.12,.3],[.95,.55],[.95,-.6],[.12,-.85],[0,-1],[-.12,-.85],[-.95,-.6],[-.95,.55]],[[0,.15],[0,-1]]],
    procedural:[Array.from({length:49},(_,i)=>{const a=i/48*TAU,r=i%4<2?1:.76;return [Math.cos(a)*r,Math.sin(a)*r];}),Array.from({length:33},(_,i)=>[Math.cos(i/32*TAU)*.32,Math.sin(i/32*TAU)*.32])],
    prospective:[[[-.45,-1],[-.45,.7],[.85,.7],[.85,.85],[-.85,.85],[-.85,.7],[-.45,.7]],[[.55,.7],[.55,-.15],[.4,-.27]],[[ -.8,-1],[-.1,-1]]],
    working:[[[-1,-.8],[-1,.15],[-.62,.15],[-.62,-.8],[-.35,-.8],[-.35,.85],[0,.85],[0,-.8],[.26,-.8],[.26,.4],[.64,.4],[.64,-.8],[.9,-.8],[.9,-.05]]],
    jhon:[[[-1,-.05],[0,.95],[1,-.05],[.78,-.05],[.78,-.9],[.17,-.9],[.17,-.35],[-.17,-.35],[-.17,-.9],[-.78,-.9],[-.78,-.05],[-1,-.05]]],
    prasma:[Array.from({length:7},(_,i)=>[Math.cos(i/6*TAU),Math.sin(i/6*TAU)]),Array.from({length:7},(_,i)=>[Math.cos(i/6*TAU)*.5,Math.sin(i/6*TAU)*.5])],
    branding:[[[-.85,-.9],[-.85,-.35],[-.55,-.35],[-.55,-.9]],[[-.15,-.9],[-.15,.25],[.15,.25],[.15,-.9]],[[.55,-.9],[.55,.95],[.85,.95],[.85,-.9]]],
    onebrain:[Array.from({length:49},(_,i)=>{const a=i/48*TAU;return [Math.cos(a),Math.sin(a)*.54];}),Array.from({length:33},(_,i)=>[Math.cos(i/32*TAU)*.3,Math.sin(i/32*TAU)*.3])],
    reef:[Array.from({length:65},(_,i)=>{const x=i/64*2-1;return [x,Math.sin(x*5)*.4];}),Array.from({length:65},(_,i)=>{const x=i/64*2-1;return [x,Math.sin(x*5+1)*.4-.35];})],
    inbox:[[[-.8,-1],[-.8,.25],[-.7,.6],[-.4,.86],[0,1],[.4,.86],[.7,.6],[.8,.25],[.8,-1]],[[ -.45,-1],[-.45,.18],[-.32,.45],[0,.58],[.32,.45],[.45,.18],[.45,-1]]]
  };
  const glyphs={};
  for(const id of roomIds){
    const segments=[],strokes=glyphStrokes[id];let total=0;
    for(const stroke of strokes)for(let i=1;i<stroke.length;i++){const a=stroke[i-1],b=stroke[i],length=Math.hypot(b[0]-a[0],b[1]-a[1]);segments.push({a,b,start:total,length});total+=length;}
    const points=new Float32Array(256*3);let segment=0;
    for(let i=0;i<256;i++){const distance=(i+.5)/256*total;while(segment<segments.length-1&&distance>=segments[segment].start+segments[segment].length)segment++;
      const s=segments[segment],t=(distance-s.start)/s.length;points[i*3]=(s.a[0]+(s.b[0]-s.a[0])*t)*7;points[i*3+1]=(s.a[1]+(s.b[1]-s.a[1])*t)*6;points[i*3+2]=0;}
    glyphs[id]=points;
  }
  const droneFrom=new Float32Array(glyphs.core),droneTo=new Float32Array(glyphs.core),droneSeeds=new Float32Array(256),droneOrder=new Uint16Array(256);
  for(let i=0;i<256;i++)droneSeeds[i]=i*.61803398875%1;
  for(let i=0;i<128;i++){droneOrder[i]=i*2;droneOrder[128+i]=i*2+1;}
  const droneGeometry=new THREE.BufferGeometry();droneGeometry.setAttribute('position',new THREE.BufferAttribute(droneFrom,3).setUsage(THREE.DynamicDrawUsage));
  droneGeometry.setIndex(new THREE.BufferAttribute(droneOrder,1));
  droneGeometry.setAttribute('aTarget',new THREE.BufferAttribute(droneTo,3).setUsage(THREE.DynamicDrawUsage));droneGeometry.setAttribute('aSeed',new THREE.BufferAttribute(droneSeeds,1));
  const drones=new THREE.Points(droneGeometry,new THREE.ShaderMaterial({uniforms,transparent:true,depthWrite:false,blending:THREE.AdditiveBlending,
    vertexShader:`attribute vec3 aTarget;attribute float aSeed;uniform float uMorph,uTime;varying float vSeed;
      void main(){vSeed=aSeed;vec3 p=mix(position,aTarget,smoothstep(0.0,1.0,uMorph));p+=vec3(sin(uTime*.21+aSeed*41.0),cos(uTime*.17+aSeed*33.0),sin(uTime*.13+aSeed*29.0))*.22;
        vec4 mv=modelViewMatrix*vec4(p,1.0);gl_Position=projectionMatrix*mv;gl_PointSize=clamp(120.0/-mv.z,1.4,4.5);}`,
    fragmentShader:`varying float vSeed;uniform vec3 uColor,uAccent;uniform float uEnergy,uCut;void main(){float r=length(gl_PointCoord-.5);if(r>.5)discard;gl_FragColor=vec4(mix(uColor,uAccent,vSeed*.4),(.45+uEnergy*.4)*uCut*(1.0-r*2.0));
      #include <colorspace_fragment>
    }`
  }));drones.position.set(core.cx,core.z+34,-core.cy);drones.rotation.y=.4;drones.frustumCulled=false;scene.add(drones);
  function morphGlyph(id){
    if(reduced)return;const target=glyphs[id]||glyphs.working,mix=uniforms.uMorph.value;
    for(let i=0;i<droneFrom.length;i++){droneFrom[i]+= (droneTo[i]-droneFrom[i])*mix;droneTo[i]=target[i];}
    droneGeometry.attributes.position.needsUpdate=true;droneGeometry.attributes.aTarget.needsUpdate=true;morphStart=clockNow();
  }

  const shellOrigins=Array.from({length:6},()=>new THREE.Vector4(0,0,0,-100)),shellColors=Array.from({length:6},()=>new THREE.Color());
  const shellDirections=new Float32Array(384*3),shellIds=new Float32Array(384),particleIds=new Float32Array(384);
  for(let shell=0;shell<6;shell++)for(let i=0;i<64;i++){
    const k=shell*64+i,y=1-2*(i+.5)/64,r=Math.sqrt(1-y*y),a=i*2.399963229728653;
    shellDirections[k*3]=Math.cos(a)*r;shellDirections[k*3+1]=y;shellDirections[k*3+2]=Math.sin(a)*r;shellIds[k]=shell;particleIds[k]=i;
  }
  const fireGeometry=new THREE.BufferGeometry();fireGeometry.setAttribute('position',new THREE.BufferAttribute(shellDirections,3));fireGeometry.setAttribute('aShell',new THREE.BufferAttribute(shellIds,1));fireGeometry.setAttribute('aParticle',new THREE.BufferAttribute(particleIds,1));
  const fireUniforms=Object.assign({},uniforms,{uShells:{value:shellOrigins},uShellColors:{value:shellColors},uParticleLimit:{value:64}});
  const fireworks=new THREE.Points(fireGeometry,new THREE.ShaderMaterial({uniforms:fireUniforms,transparent:true,blending:THREE.AdditiveBlending,depthWrite:false,
    vertexShader:`attribute float aShell,aParticle;uniform vec4 uShells[6];uniform vec3 uShellColors[6];uniform float uClock,uParticleLimit;varying vec3 vColor;varying float vFade;
      void main(){int shell=int(aShell);vec4 origin=uShells[shell];float age=uClock-origin.w;float burst=max(0.0,age-.7);vec3 p=origin.xyz;p.y+=min(age,.7)*16.0;
        p+=position*burst*5.2;p.y-=burst*burst*2.7;vFade=step(0.0,age)*step(age,2.7)*max(0.0,1.0-burst/2.0)*step(aParticle,uParticleLimit-1.0);
        if(age<.7&&aParticle>.5)vFade=0.0;vColor=uShellColors[shell];vec4 mv=viewMatrix*vec4(p,1.0);gl_Position=projectionMatrix*mv;gl_PointSize=clamp(160.0/-mv.z,1.3,5.0);}`,
    fragmentShader:`varying vec3 vColor;varying float vFade;uniform float uEnergy,uCut;void main(){float r=length(gl_PointCoord-.5);if(r>.5||vFade<=0.0)discard;gl_FragColor=vec4(vColor,vFade*(1.0-r*2.0)*uEnergy*uCut);
      #include <colorspace_fragment>
    }`
  }));fireworks.frustumCulled=false;scene.add(fireworks);
  const lastFireCycle={};for(const id of roomIds)lastFireCycle[id]=-Infinity;lastFireCycle.skyline=-Infinity;
  function launchShells(id,bar){
    if(!beat.sound||lights.calm||reduced)return;
    const spec=cityAudio.rooms[id]||cityAudio.rooms.skyline,cycle=Math.floor(bar/spec.cycleBars),cycleBar=((bar%spec.cycleBars)+spec.cycleBars)%spec.cycleBars;
    const returnBar=spec.withhold===null?0:spec.cycleBars===16?10:22;
    if(cycleBar!==returnBar||lastFireCycle[id]===cycle)return;
    if(spec.withhold!==null&&cityAudio.arrangementPhase(id,bar)!=='return')return;
    lastFireCycle[id]=cycle;const baseCount=3+((cycle+roomIds.indexOf(id)+4)%4),count=tier.current===3?baseCount:tier.current===2?Math.max(2,Math.round(baseCount*.6)):2;
    const district=id==='skyline'?'working':id,p=DATA.plateaus[district];
    for(let i=0;i<6;i++){
      if(i<count){const a=i/count*TAU+.3*cycle;shellOrigins[i].set(p.cx+Math.cos(a)*3,p.z+2,-p.cy+Math.sin(a)*3,clockNow()+i*.11);shellColors[i].copy(i%2?palettes[id].accent:palettes[id].color);}
      else shellOrigins[i].w=-100;
    }
    const row=shellHistory[diagnostics.fireworkEvents++%shellHistory.length];row.room=id;row.bar=bar;row.cycle=cycle;row.shells=count;row.at=beat.diagnostics.lastFrameMs;row.frame=beat.diagnostics.frame;
    diagnostics.lastFireworkBar=bar;diagnostics.lastFireworkRoom=id;
  }

  // One procedural atlas, shared by every new screen; no canvas is painted per frame.
  const screenLines=['TONIGHT','OPEN LATE','140 BPM','NO SLEEP TILL SUNRISE','BIENVENIDOS','ABIERTO 24H','SOUND SYSTEM'];
  for(let i=0;i<=12;i++)screenLines.push('WEEK '+i);
  const atlas=document.createElement('canvas');atlas.width=atlas.height=1024;
  const context=atlas.getContext('2d');context.fillStyle='#000';context.fillRect(0,0,1024,1024);context.textAlign='center';context.textBaseline='middle';
  for(let i=0;i<screenLines.length;i++){
    const x=(i%4)*256,y=Math.floor(i/4)*128;context.fillStyle='#fff';context.font=(screenLines[i].length>15?'bold 17px':'bold 26px')+' monospace';context.fillText(screenLines[i],x+128,y+64);
    context.fillStyle='#557780';context.fillRect(x+20,y+102,216,2);
  }
  const atlasTexture=new THREE.CanvasTexture(atlas);atlasTexture.minFilter=THREE.LinearFilter;atlasTexture.magFilter=THREE.LinearFilter;atlasTexture.generateMipmaps=false;
  const screenHosts=towers.slice(0,6).concat(nodes.filter(n=>n.district==='branding'&&n.kind==='sign'));
  const screenModes=new Float32Array(screenHosts.length),screenCells=new Float32Array(screenHosts.length);
  for(let i=0;i<screenHosts.length;i++){screenModes[i]=i%4;screenCells[i]=i%7;}
  const screenGeometry=new THREE.PlaneGeometry(1,1);screenGeometry.setAttribute('aMode',new THREE.InstancedBufferAttribute(screenModes,1));screenGeometry.setAttribute('aCell',new THREE.InstancedBufferAttribute(screenCells,1));
  const screenUniforms=Object.assign({},uniforms,{uAtlas:{value:atlasTexture},uWeek:{value:12}});
  const screens=new THREE.InstancedMesh(screenGeometry,new THREE.ShaderMaterial({uniforms:screenUniforms,side:THREE.DoubleSide,forceSinglePass:true,
    vertexShader:`attribute float aMode,aCell;varying vec2 vUV;varying float vMode,vCell;void main(){vUV=uv;vMode=aMode;vCell=aCell;gl_Position=projectionMatrix*modelViewMatrix*instanceMatrix*vec4(position,1.0);}`,
    fragmentShader:`varying vec2 vUV;varying float vMode,vCell;uniform vec3 uColor,uAccent;uniform float uTime,uEnergy,uSourceIntensity,uCut,uHat,uClap,uBeat,uWeek;uniform float uSpectrum[16],uWave[32];uniform sampler2D uAtlas;
      void main(){if(!gl_FrontFacing){gl_FragColor=vec4(vec3(.012,.015,.02)*uCut,1.0);return;}vec2 uv=vUV,p=uv-.5;float figure=0.0;vec3 paint=uColor;
        if(vMode<.5){int bin=int(min(15.0,floor(uv.x*16.0)));float height=.10+uSpectrum[bin]*.77;figure=step(uv.y,height)*step(.13,fract(uv.x*16.0));paint=mix(uColor,uAccent,uv.y);}
        else if(vMode<1.5){float angle=atan(p.y,p.x)/6.2831853+.5;int bin=int(min(31.0,floor(angle*32.0)));float radius=.26+uWave[bin]*.075;figure=1.0-smoothstep(.012,.030,abs(length(p)-radius));figure+=.18*(1.0-smoothstep(.03,.045,abs(length(p)-.38)));}
        else if(vMode<2.5){float a=atan(p.y,p.x),r=length(p);float fold=abs(mod(a+uTime*.12,.785398)-.392699);figure=pow(max(0.0,sin(r*37.0+fold*18.0-uBeat*.5)),10.0)*(.4+uSpectrum[3]*.6);paint=mix(uColor,uAccent,sin(a*4.0)*.5+.5);}
        else{float cell=mod(floor(uBeat/16.0)+vCell,8.0);if(cell>6.5)cell=7.0+uWeek;vec2 tile=vec2(mod(cell,4.0),floor(cell/4.0));vec2 textUV=vec2(fract(uv.x+uTime*.028),uv.y);figure=texture2D(uAtlas,vec2((tile.x+textUV.x)/4.0,1.0-(tile.y+1.0-textUV.y)/8.0)).r;}
        float pixels=.82+.18*step(.28,fract(uv.x*96.0))*step(.28,fract(uv.y*48.0));vec3 c=vec3(.002,.006,.010)+paint*figure*pixels*.92*uEnergy*uSourceIntensity;c+=(uAccent*uHat*.015+uColor*uClap*.4)*uEnergy*uSourceIntensity;
        gl_FragColor=vec4(c*uCut,1.0);
        #include <colorspace_fragment>
      }`
  }),screenHosts.length);screens.instanceMatrix.setUsage(THREE.DynamicDrawUsage);screens.frustumCulled=false;scene.add(screens);
  const frameGeometry=new GB();frameGeometry.box(-.54,-.54,-.035,.54,-.48,.035,8);frameGeometry.box(-.54,.48,-.035,.54,.54,.035,8);frameGeometry.box(-.54,-.48,-.035,-.48,.48,.035,8);frameGeometry.box(.48,-.48,-.035,.54,.48,.035,8);
  const screenFrames=new THREE.InstancedMesh(frameGeometry.geometry(),new THREE.MeshBasicMaterial({color:0x16232c}),screenHosts.length);
  screenFrames.instanceMatrix=screens.instanceMatrix;screenFrames.frustumCulled=false;scene.add(screenFrames);

  function update(dt){
    const snapshot=beat.now(),now=clockNow(),tr=beat.transition,position=tr.source==='audio'?beat.audibleTime(beat.diagnostics.lastFrameMs):snapshot.seconds;
    diagnostics.lastUpdateFrame=beat.diagnostics.frame;motion+=reduced?0:Math.min(Math.max(dt,0),.1);
    if(!tr.active){transition.stage='groove';uniforms.uStage.value=0;selectPalette(beat.room);}
    uniforms.uTime.value=motion;uniforms.uClock.value=now;uniforms.uBeat.value=reduced?0:snapshot.totalBeats;
    uniforms.uSourceIntensity.value=beat.sound?1:.5;uniforms.uEnergy.value=lights.intensity;
    uniforms.uCut.value=tr.active&&tr.stage==='cut'?lights.cutFactor:1;
    const desaturate=tr.active&&position>=tr.start&&position<tr.drop?Math.min(1,Math.max(0,(position-tr.start)/(BAR*2))):0;
    if(lights.calm)uniforms.uDesaturate.value+=Math.sign(desaturate-uniforms.uDesaturate.value)*Math.min(Math.abs(desaturate-uniforms.uDesaturate.value),Math.max(0,dt)/BAR);
    else uniforms.uDesaturate.value=desaturate;
    uniforms.uRiser.value=!reduced&&tr.active&&position>=tr.riser&&position<tr.cut?Math.min(1,(Math.floor((position-tr.riser)/BEAT)+1)/16):0;
    if(lights.calm){const progress=Math.min(1,Math.max(0,(now-colorStart)/BAR));uniforms.uColor.value.lerpColors(fromColor,targetColor,progress);uniforms.uAccent.value.lerpColors(fromAccent,targetAccent,progress);}
    else{uniforms.uColor.value.copy(targetColor);uniforms.uAccent.value.copy(targetAccent);}
    const fade=Math.exp(-Math.max(dt,0)*8);kick*=fade;hat*=Math.exp(-Math.max(dt,0)*12);pad*=Math.exp(-Math.max(dt,0)*.8);stab*=Math.exp(-Math.max(dt,0)*3);bass*=Math.exp(-Math.max(dt,0)*4);flash*=Math.exp(-Math.max(dt,0)*5);clap*=Math.exp(-Math.max(dt,0)*18);
    uniforms.uKick.value=reduced?0:kick;uniforms.uHat.value=reduced?0:hat;
    uniforms.uPad.value=pad;uniforms.uStab.value=stab;uniforms.uBass.value=bass;uniforms.uFlash.value=lights.calm?0:flash;uniforms.uClap.value=lights.strobes?clap:0;
    const analyser=cityAudio.analyser;
    if(reduced){for(let i=0;i<32;i++){wave[i]=0;if(i<16)spectrum[i]=.08;}}
    else if(beat.sound&&analyser){
      // The 4096-point FFT runs on this thread: the screens' spectrum refreshes every other frame.
      if((analyserFrame++&1)===0){
        analyser.getByteFrequencyData(frequencyBytes);
        for(let i=0;i<16;i++){const lo=bandLo[i],hi=bandHi[i];let sum=0;for(let j=lo;j<hi;j++)sum+=frequencyBytes[j];spectrum[i]=sum/(hi-lo)/255;}
      }
      analyser.getByteTimeDomainData(waveBytes);
      for(let i=0;i<32;i++)wave[i]=(waveBytes[i*128]-128)/128;
    }else for(let i=0;i<32;i++){wave[i]=reduced?0:Math.sin(i*.5+snapshot.totalBeats)*.2;if(i<16)spectrum[i]=reduced?.08:.08+.18*Math.pow(Math.sin(i*.71+snapshot.totalBeats*.8),2);}
    lasers.count=tier.current===3?14:tier.current===2?10:6;searchlights.count=tier.current===3?4:2;droneGeometry.setDrawRange(0,tier.current===3?256:tier.current===2?128:0);fireUniforms.uParticleLimit.value=tier.current===3?64:tier.current===2?38:26;
    const pattern=reduced?0:now<fanUntil?0:((Math.floor(snapshot.bar/8)+((snapshot.bar%8)+8)%8)%patterns.length+patterns.length)%patterns.length;
    for(let i=0;i<14;i++){
      const host=laserHosts[i],origin=laserOrigins[i],local=i<8?i:(i-8)%2;origin.set(host.x,plateauZ(host.district)+host.h*(host.rise??1)+.13,-host.y);
      let angle=i<8?local/8*TAU:(i-8)*.84,tilt=.58,length=i<8?44:31;
      const clock=reduced?0:motion;
      if(pattern===0){angle+=Math.sin(clock*.27)*.22;tilt=.46+local*.028;}
      else if(pattern===1){angle+=snapshot.barPhase*TAU*.45;tilt=.45+Math.sin(clock*.4+i)*.09;}
      else if(pattern===2){angle+=(i%2?1:-1)*snapshot.barPhase*1.2;tilt=.68;}
      else if(pattern===3){angle+=clock*.10;tilt=.86;}
      else{angle+=clock*.03;tilt=.11+local*.012;}
      const narrow=reduced?0:uniforms.uDesaturate.value;tilt*=1-narrow*.85;if(!reduced&&uniforms.uRiser.value>0)tilt=.075+local*.006;
      direction.set(Math.cos(angle)*Math.sin(tilt),Math.cos(tilt),Math.sin(angle)*Math.sin(tilt));beamDummy.position.copy(origin);beamDummy.quaternion.setFromUnitVectors(up,direction);
      const visible=host.state!=='absent';beamDummy.scale.set(visible?1-narrow*.6:0,visible?length:0,visible?1-narrow*.6:0);beamDummy.updateMatrix();lasers.setMatrixAt(i,beamDummy.matrix);
    }
    lasers.instanceMatrix.needsUpdate=true;
    for(let i=0;i<4;i++){
      const p=DATA.plateaus[i%2?'prospective':'procedural'],a=(reduced?0:snapshot.totalBeats/8*TAU)+i*Math.PI/2;
      beamDummy.position.set(p.cx+(i<2?-1:1)*Math.min(3,p.rx*.4),p.z+1.5,-p.cy);direction.set(Math.cos(a)*.48,1,Math.sin(a)*.48).normalize();beamDummy.quaternion.setFromUnitVectors(up,direction);beamDummy.scale.set(1,28,1);beamDummy.updateMatrix();searchlights.setMatrixAt(i,beamDummy.matrix);
    }
    searchlights.instanceMatrix.needsUpdate=true;
    const arrangementBar=beat.sound?Math.floor((beat.audibleTime(beat.diagnostics.lastFrameMs)-cityAudio.origin)/BAR):snapshot.bar;
    if(arrangementBar!==lastBar){
      lastBar=arrangementBar;const room=beat.sound?cityAudio.room:beat.room,spec=cityAudio.rooms[room]||cityAudio.rooms.skyline,cycle=Math.floor(arrangementBar/(beat.sound?spec.cycleBars:32));
      const cycleBar=((arrangementBar%(beat.sound?spec.cycleBars:32))+(beat.sound?spec.cycleBars:32))%(beat.sound?spec.cycleBars:32);
      if(cycleBar===0&&(cycle!==lastCycle||room!==lastCycleRoom)){morphGlyph(room==='skyline'?'working':room);lastCycle=cycle;lastCycleRoom=room;}
      launchShells(room,arrangementBar);
    }
    uniforms.uMorph.value=reduced?1:Math.min(1,Math.max(0,(now-morphStart)/(BAR*2)));
    screenUniforms.uWeek.value=Math.floor(state.t);
    for(let i=0;i<screenHosts.length;i++){
      const host=screenHosts[i],p=DATA.plateaus[host.district],height=host.h*(host.rise??1),size=host.state==='absent'?0:1;
      beamDummy.position.set(host.x,plateauZ(host.district)+height+.4,-host.y);beamDummy.rotation.set(0,Math.atan2(p.cx-host.x,host.y-p.cy),0);beamDummy.scale.set(host.w*1.7*size,.66*size,1);beamDummy.updateMatrix();screens.setMatrixAt(i,beamDummy.matrix);
    }
    screens.instanceMatrix.needsUpdate=true;
  }
  return {update,sky,stars:starField,lasers,searchlights,drones,fireworks,grid,screens,screenFrames,screenHosts,
    laserOrigins,laserHosts,glyphs,patterns,uniforms,transition,diagnostics,screenLines,atlas,shellOrigins,shellColors,fireUniforms,screenUniforms};
})();
const stars=rave.stars;
