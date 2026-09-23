// Traffic stays on navigable streets, with two lanes and measured travel distance.
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


const venues={items:[],update(){}};
