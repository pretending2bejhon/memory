// Low-poly citizens: instanced coats, heads and independently swinging limbs.
const peopleGroup=new THREE.Group();scene.add(peopleGroup);
const PEOPLE=260;
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
const personPoint=new THREE.Vector3(),personAhead=new THREE.Vector3(),personCheck=new THREE.Vector3();
const limbPoses=[['body',0,.195,0],['head',0,.305,0],['leftLeg',-.026,.065,1],['rightLeg',.026,.065,-1],['leftArm',-.067,.19,-1],['rightArm',.067,.19,1]];
const personMeshes=Object.values(personParts);
function updatePeople(dt,now) {
  if(!peopleGroup.visible) return;
  const p=personPoint,q=personAhead;
  for(let i=0;i<people.length;i++) {
    const person=people[i];
    const route=routes[person.route],offset=Math.min(route.width/2+.04,route.clearance-.12);
    person.distance+=dt*person.speed*person.side;
    sampleRoute(route,person.distance,p,offset*person.side);sampleRoute(route,person.distance+.15*person.side,q,offset*person.side);
    pRoot.position.copy(p);pRoot.position.y+=.045;pRoot.rotation.set(0,Math.atan2(q.x-p.x,q.z-p.z),0);pRoot.updateMatrix();
    const blocked=pointBlocked(personCheck.set(p.x,p.y+.18,p.z),.07);
    const gait=reduced?0:Math.sin(now*person.speed*18+person.phase)*.48;
    for(let j=0;j<limbPoses.length;j++) {
      const pose=limbPoses[j];
      pLimb.position.set(pose[1],pose[2],0);pLimb.rotation.set(pose[3]*gait,0,0);pLimb.updateMatrix();pMatrix.multiplyMatrices(pRoot.matrix,pLimb.matrix);personParts[pose[0]].setMatrixAt(i,blocked?hidden:pMatrix);
    }
  }
  for(const mesh of personMeshes) mesh.instanceMatrix.needsUpdate=true;
}


const crowd={people,parts:personParts,get count(){return personParts.body.count;}};
