// Keep the V4 route clearance helper for its independent static gate.
const rideBadge=$('ride-badge');
let shownLeg=-1;
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
  return grandTour.start();
}
function stopRide() {
  return grandTour.stop();
}
function setRideUI(active) {
  document.body.classList.toggle('riding',active);
  rideBadge.hidden=!active;
  $('ride').classList.toggle('on',active);
  $('ride').textContent=active?'Leave ride':'Ride along';
  $('ride').setAttribute('aria-pressed',String(active));
  shownLeg=-1;
  if(active)updateRide();
}
function updateRide() {
  if(state.ride<0||state.ride===shownLeg)return;
  const leg=roadNet.tour.legs[state.ride];if(!leg)return;
  shownLeg=state.ride;
  $('ride-route').textContent=styleOf(leg.from).name+' to '+styleOf(leg.to).name;
}
