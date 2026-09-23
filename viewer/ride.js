// A route-mounted lens avoids the corner-cutting of a world-space chase camera.
const rideBadge=$('ride-badge');
let rideDistance=0,savedOverview=null;
const rideEye=new THREE.Vector3(),rideLook=new THREE.Vector3(),lastSafeEye=new THREE.Vector3();
const ridePose={eye:rideEye,look:rideLook};
function poseOnRoute(route,distance) {
  sampleRoute(route,distance,rideEye);rideEye.y+=.64;
  let ahead=3.4;
  do { sampleRoute(route,distance+ahead,rideLook);rideLook.y+=.86;ahead*=.65; }
  while(!clearSight(rideEye,rideLook)&&ahead>.18);
  // Covers a future edited footprint or height without flying through geometry.
  if(pointBlocked(rideEye,.14)) rideEye.copy(lastSafeEye);
  else lastSafeEye.copy(rideEye);
  return ridePose;
}
function startRide() {
  if(state.ride>=0)return;
  const ri=state.isolate?routes.findIndex(r=>r.district===state.isolate):0;
  state.ride=Math.max(0,ri);rideDistance=routes[state.ride].length*.28;
  cityAudio.setRoom(routes[state.ride].district);
  savedOverview={position:camera.position.clone(),target:controls.target.clone(),fov:camera.fov,autoRotate:controls.autoRotate};
  controls.enabled=false;controls.autoRotate=false;focusGoal=null;select(-1);setHover(-1);
  camera.fov=62;camera.updateProjectionMatrix();
  lastSafeEye.copy(sampleRoute(routes[state.ride],rideDistance));lastSafeEye.y+=.64;
  const pose=poseOnRoute(routes[state.ride],rideDistance);camera.position.copy(pose.eye);camera.lookAt(pose.look);
  document.body.classList.add('riding');rideBadge.hidden=false;$('ride-route').textContent=routes[state.ride].district==='episodic'?routes[state.ride].name:styleOf(routes[state.ride].district).name+' circuit';
  $('ride').classList.add('on');$('ride').textContent='Leave ride';$('ride').setAttribute('aria-pressed','true');
}
function stopRide() {
  if(state.ride<0)return;
  cityAudio.setRoom('skyline');cityAudio.setRideHeading(null);
  state.ride=-1;controls.enabled=true;rideBadge.hidden=true;document.body.classList.remove('riding');
  $('ride').classList.remove('on');$('ride').textContent='Ride along';$('ride').setAttribute('aria-pressed','false');
  if(savedOverview) {camera.position.copy(savedOverview.position);controls.target.copy(savedOverview.target);camera.fov=savedOverview.fov;controls.autoRotate=savedOverview.autoRotate;camera.updateProjectionMatrix();}
  controls.update();
}
function updateRide(dt) {
  const route=routes[state.ride];if(!route)return;
  rideDistance=(rideDistance+dt*(reduced?.55:1.15))%route.length;
  const pose=poseOnRoute(route,rideDistance);camera.position.copy(pose.eye);camera.lookAt(pose.look);
  cityAudio.setRideHeading(Math.atan2(pose.look.x-pose.eye.x,pose.look.z-pose.eye.z));
}
