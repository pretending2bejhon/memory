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

// Three-second rolling mean without allocating a frame history on each frame.
const tier = (() => {
  const times=new Float64Array(1024),values=new Float64Array(1024);
  let current=phone?1:3,head=0,count=0,sum=0,clockMs=0,fastMs=0,changedAt=0;
  function apply(){
    const count=current===3?PEOPLE:current===2?Math.round(PEOPLE*.6):Math.min(220,PEOPLE);
    for(const mesh of personMeshes) mesh.count=count;
    cars.mesh.count=Math.min(current===3?CARS:current===2?Math.round(CARS*.6):70,Math.max(12,Math.round(24+validEdges.length/18)));
    resize();
  }
  const api={
    initial:phone?1:3,
    get current(){return current;},
    get meanMs(){return count?sum/count:0;},
    get settledForMs(){return clockMs-changedAt;},
    update(ms){
      clockMs+=ms;
      while(count && (clockMs-times[head]>3000 || count===1024)){
        sum-=values[head];head=(head+1)%1024;count--;
      }
      const slot=(head+count)%1024;times[slot]=clockMs;values[slot]=ms;sum+=ms;count++;
      fastMs=api.meanMs<12?fastMs+ms:0;
      if(clockMs-changedAt>=3000 && clockMs-times[head]>=2900 && api.meanMs>19 && current>1){
        current--;changedAt=clockMs;fastMs=0;apply();
      } else if(fastMs>=10000 && current<3 && !phone){
        current++;changedAt=clockMs;fastMs=0;apply();
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
