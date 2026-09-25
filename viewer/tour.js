// Grand Tour controller. Inline after explore.js and before the first frame.
// The existing bike, chase camera and trail draw the visitor. This module only supplies
// an arc-length position and a beat-clock deadline for each road leg.
const grandTour = (() => {
  const path = roadNet.tour, legs = path.legs, routes = DATA.design.routes;
  const BAR = beat.barSeconds, BEAT = beat.beatSeconds, TAU = Math.PI * 2;
  const MIN = .7, MAX = reduced ? 1.2 : 1.4;
  const HEAD_MIN = .75, HEAD_MAX = reduced ? 1.12 : 1.3;
  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
  const mod = (x, n) => ((x % n) + n) % n;
  const temporary = {point: new THREE.Vector3(), tangent: new THREE.Vector3()};
  const temporaryAhead = {point: new THREE.Vector3(), tangent: new THREE.Vector3()};
  const position = {x: 0, y: 0, z: 0, yaw: 0, s: 0, onDeck: false};
  const debug = {noSpeedControl: false, crossings: [], sourceReplans: 0,
    wrongDrops: 0, jointGap: 0, surfaceGaps: 0, firstMiss: null,
    sourceBandMisses: 0, minSpeed: Infinity, longestStop: 0, startFailure: null};
  let active = false, legIndex = -1, plan = null, q = 0, lastClock = 0;
  let requested = false, observedSerial = -1, cutSeen = false;
  let sourceChanges = beat.diagnostics.sourceChanges, waitingRoom = null;
  let waitingLoop = null;
  let pass = 0;

  function makeRoute(route, index) {
    const points = route.points, cum = new Float64Array(points.length + 1);
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    for (let i = 0; i < points.length; i++) {
      const a = points[i], b = points[(i + 1) % points.length];
      cum[i + 1] = cum[i] + Math.hypot(b[0] - a[0], b[1] - a[1]);
      minX = Math.min(minX, a[0]); maxX = Math.max(maxX, a[0]);
      minY = Math.min(minY, a[1]); maxY = Math.max(maxY, a[1]);
    }
    // A route with radius below 5 is the only slow road in the plan. The rectangular
    // avenue uses the usual 2.8 cruise even though it has no single radius.
    const p = DATA.plateaus[route.district];
    const small = p && p.shape === 'disc' && Math.max(maxX - minX, maxY - minY) / 2 < 5;
    return {index, district: route.district, points, cum, length: cum[points.length],
      z: route.z, cruise: small ? 1.8 : 2.8};
  }
  const rings = routes.map(makeRoute);

  function routeAt(r, s, out) {
    s = mod(s, r.length);
    const cum = r.cum, points = r.points;
    let lo = 0, hi = points.length;
    while (lo + 1 < hi) { const mid = (lo + hi) >> 1; if (cum[mid] <= s) lo = mid; else hi = mid; }
    const a = points[lo], b = points[(lo + 1) % points.length];
    const t = (s - cum[lo]) / Math.max(1e-9, cum[lo + 1] - cum[lo]);
    out.x = a[0] + (b[0] - a[0]) * t; out.y = r.z;
    out.z = -(a[1] + (b[1] - a[1]) * t);
    out.yaw = Math.atan2(b[0] - a[0], -(b[1] - a[1]));
    return out;
  }

  function nearestOnRoute(r, x, y) {
    const points = r.points;
    let best = Infinity, at = 0, tx = 0, ty = 0;
    for (let i = 0; i < points.length; i++) {
      const a = points[i], b = points[(i + 1) % points.length];
      const dx = b[0] - a[0], dy = b[1] - a[1];
      const len2 = dx * dx + dy * dy;
      const t = clamp(((x - a[0]) * dx + (y - a[1]) * dy) / Math.max(len2, 1e-12), 0, 1);
      const gap = Math.hypot(x - a[0] - t * dx, y - a[1] - t * dy);
      if (gap < best) { best = gap; at = r.cum[i] + Math.sqrt(len2) * t;
        const length = Math.sqrt(len2) || 1; tx = dx / length; ty = dy / length; }
    }
    return {gap: best, at, tx, ty};
  }

  function jointFor(k, fromS) {
    const leg = legs[k];
    let best = null;
    // A bridge fillet may continue well past the district boundary. Find the
    // first actual ring overlap rather than assuming it is 1.3 units in.
    for (let anchor = fromS + .1; anchor < leg.depart - .4; anchor += .1) {
      const p = path.sample(anchor, temporary), ahead = path.sample(anchor + .08, temporaryAhead);
      const ax = p.point.x, ay = -p.point.z;
      const dx = ahead.point.x - ax, dy = -ahead.point.z;
      for (const r of rings) {
        if (r.district !== leg.from) continue;
        const n = nearestOnRoute(r, ax, ay);
        const dot = (dx * n.tx + dy * n.ty) / Math.max(1e-9, Math.hypot(dx, dy));
        const score = n.gap + .001 * (anchor - fromS) + .0001 * (1 - Math.abs(dot));
        if (!best || score < best.score) best = {score, gap: n.gap, ring: r, ringS: n.at,
          direction: dot >= 0 ? 1 : -1, anchor};
      }
    }
    if (!best || best.gap > .01) throw new Error('Tour lap cannot join its route: ' + k + ', gap ' + best?.gap);
    debug.jointGap = Math.max(debug.jointGap, best.gap);
    return best;
  }

  // For a fixed number of extra laps, the cruise-time integral is distance divided
  // by 1.8 on a small ring, or by 2.8 on other roads and every bridge. The smallest
  // lap count with a phrase deadline inside the speed band wins.
  function choose(k, fromS, startAt, previousDrop) {
    const leg = legs[k], joint = jointFor(k, fromS), ringCruise = joint.ring.cruise;
    for (const [lo, hi] of [[HEAD_MIN, HEAD_MAX], [MIN, MAX]]) {
      for (let laps = 0; laps <= 8; laps++) {
        const lapDistance = laps * joint.ring.length;
        const deckAt = leg.depart - fromS + lapDistance;
        const distance = leg.land - fromS + lapDistance;
        const tauDeck = deckAt / ringCruise;
        const tau = tauDeck + (distance - deckAt) / 2.8;
        for (let phrases = 2; phrases <= 24; phrases++) {
          const dropBar = previousDrop + phrases * 8;
          const dropAt = dropBar * BAR;
          const duration = dropAt - startAt;
          if (duration <= 0 || dropBar - 8 < previousDrop + 8) continue;
          const factor = tau / duration;
          if (factor < lo || factor > hi) continue;
          const candidate = {k, leg, fromS, joint, laps, lapDistance, deckAt, distance,
            ringCruise, tauDeck, tau, factor, startAt, previousDrop,
            dropBar, dropAt, requestBar: dropBar - 8, cutAt: dropAt - BEAT};
          // If the bridge takes longer than a beat, the entire cut beat must be
          // between its depart point and its landing boundary.
          const deckSeconds = (distance - deckAt) / (2.8 * factor);
          if (deckSeconds > BEAT && qAt(candidate, candidate.cutAt) < deckAt - 1e-4) continue;
          candidate.deckSeconds = deckSeconds;
          return candidate;
        }
      }
    }
    throw new Error('No phrase and lap plan fits the tour speed band: ' + k);
  }

  function tauAt(p, distance) {
    return distance <= p.deckAt ? distance / p.ringCruise :
      p.tauDeck + (distance - p.deckAt) / 2.8;
  }
  function qAt(p, seconds) {
    const t = clamp((seconds - p.startAt) * p.factor, 0, p.tau);
    return t <= p.tauDeck ? t * p.ringCruise : p.deckAt + (t - p.tauDeck) * 2.8;
  }
  function sampleAt(p, distance, out = position) {
    const j = p.joint, before = j.anchor - p.fromS;
    if (distance < before || !p.laps) {
      const s = p.fromS + distance;
      const a = path.sample(s, temporary);
      out.x = a.point.x; out.y = a.point.y; out.z = a.point.z;
      out.yaw = Math.atan2(a.tangent.x, a.tangent.z); out.s = s;
    } else if (distance < before + p.lapDistance) {
      routeAt(j.ring, j.ringS + j.direction * (distance - before), out);
      if (j.direction < 0) out.yaw += Math.PI;
      out.s = j.anchor;
    } else {
      const s = j.anchor + distance - before - p.lapDistance;
      const a = path.sample(s, temporary);
      out.x = a.point.x; out.y = a.point.y; out.z = a.point.z;
      out.yaw = Math.atan2(a.tangent.x, a.tangent.z); out.s = s;
    }
    out.onDeck = distance >= p.deckAt;
    return out;
  }

  function nearestStart(district, from) {
    let best = null;
    for (let k = 0; k < legs.length; k++) {
      const leg = legs[k]; if (leg.from !== district) continue;
      const entry = k ? legs[k - 1].land : 0;
      const hi = Math.max(entry + 1, leg.depart - 1.6);
      for (let s = entry + 1; s <= hi; s += .25) {
        const a = path.sample(s, temporary);
        const dx = a.point.x - from.x, dz = a.point.z - from.z;
        const gap2 = dx * dx + dz * dz;
        if (!best || gap2 < best.gap2) best = {k, s, gap2};
      }
    }
    return best;
  }

  function setPlan(k, fromS, startAt, previousDrop) {
    plan = choose(k, fromS, startAt, previousDrop);
    legIndex = k; state.ride = k; q = 0; requested = false;
    observedSerial = beat.transition.serial; cutSeen = false; lastClock = beat.seconds();
  }

  function start(from) {
    if (active) return true;
    const district = from?.district || state.isolate || 'core';
    if (!explore.active) explore.enter(district);
    if (!explore.player.onBike) explore.toggleBike();
    const origin = from || explore.position;
    const near = nearestStart(district, origin);
    if (!near) { debug.startFailure = {reason:'no leg',district}; return false; }
    const wait = beat.room !== district || cityAudio.desired !== district;
    const joint = wait ? jointFor(near.k, near.s) : null;
    const a = wait ? routeAt(joint.ring, joint.ringS, position) : path.sample(near.s, temporary);
    const x = wait ? a.x : a.point.x, y = wait ? a.y : a.point.y, z = wait ? a.z : a.point.z;
    const yaw = wait ? a.yaw + (joint.direction < 0 ? Math.PI : 0) : Math.atan2(a.tangent.x, a.tangent.z);
    if (!explore.teleport(x, z, yaw, y)) {
      debug.startFailure = {reason:'no surface',district,leg:near.k,x,y,z,
        surface:explore.surfaceAt(x,z,y),ring:joint?.ring.index,ringS:joint?.ringS};
      return false;
    }
    debug.startFailure = null;
    explore.tourDriver = drive;
    active = true; state.ride = near.k; legIndex = near.k;
    sourceChanges = beat.diagnostics.sourceChanges;
    setRideUI(true);
    cityAudio.setRideHeading(explore.player.yaw);
    waitingRoom = wait ? district : null;
    waitingLoop = wait ? {joint, distance: 0, ready: false, previousDrop: 0} : null;
    if (cityAudio.desired !== district) beat.setRoom(district);
    const now = beat.seconds();
    if (!waitingRoom) setPlan(near.k, near.s, now, Math.floor(now / BAR / 8) * 8);
    else { plan = null; lastClock = now; }
    return true;
  }

  function stop() {
    if (!active) return;
    active = false; explore.tourDriver = null; state.ride = -1;
    setRideUI(false);
    plan = null; waitingRoom = null; waitingLoop = null; cityAudio.setRideHeading(null);
    explore.leave();
  }

  function tickRoom(now) {
    if (!waitingRoom) return;
    if (beat.room !== waitingRoom || cityAudio.desired !== waitingRoom ||
        (beat.transition.active && beat.transition.to !== waitingRoom)) return;
    const settledRoom = waitingRoom;
    waitingRoom = null;
    const previousDrop = beat.transition.to === settledRoom && beat.transition.dropBar <= beat.now().bar
      ? beat.transition.dropBar : Math.floor(now / BAR / 8) * 8;
    if (!plan) {
      waitingLoop.ready = true;
      waitingLoop.previousDrop = previousDrop;
      return;
    }
    // Rebase the remaining ride onto the new clock without freezing the bike.
    const remainingTau = plan.tau - tauAt(plan, q);
    let dropBar = Math.ceil((beat.now().bar + 8) / 8) * 8;
    let factor = 1;
    for (let i = 0; i < 24; i++, dropBar += 8) {
      factor = remainingTau / Math.max(.001, dropBar * BAR - now);
      if (factor <= MAX) break;
    }
    if (factor < MIN || factor > MAX) debug.sourceBandMisses++;
    plan.factor = clamp(factor, MIN, MAX);
    plan.previousDrop = previousDrop;
    plan.dropBar = dropBar;
    plan.dropAt = dropBar * BAR;
    plan.requestBar = dropBar - 8;
    plan.cutAt = plan.dropAt - BEAT;
    plan.startAt = now - tauAt(plan, q) / plan.factor;
    delete plan.actualStartBar;
    requested = false; observedSerial = beat.transition.serial; cutSeen = false;
  }

  function replanSource(now) {
    debug.sourceReplans++;
    if (plan) sampleAt(plan, q, position);
    const from = legs[legIndex].from;
    waitingRoom = from; requested = false;
    if (cityAudio.desired !== from) beat.setRoom(from);
    lastClock = now;
    if (plan) plan.startAt = now - tauAt(plan, q) / plan.factor;
  }

  function requestRoom() {
    if (requested || !plan || beat.now().bar < plan.requestBar) return;
    observedSerial = beat.transition.serial;
    beat.setRoom(plan.leg.to);
    requested = true;
    if (beat.transition.serial !== observedSerial && beat.transition.to === plan.leg.to)
      plan.actualStartBar = beat.transition.bar;
  }

  function checkDrop() {
    if (!requested || !plan || !beat.transition.active ||
        beat.transition.serial === observedSerial) return;
    observedSerial = beat.transition.serial;
    if (beat.transition.to !== plan.leg.to || beat.transition.dropBar !== plan.dropBar)
      debug.wrongDrops++;
    if (beat.transition.to === plan.leg.to) plan.actualStartBar = beat.transition.bar;
  }

  function recordCrossing(now, crossed) {
    const p = plan;
    const result = {pass, leg: legIndex, from: p.leg.from, to: p.leg.to,
      dropBar: p.dropBar, plannedAt: p.dropAt, crossedAt: crossed,
      errorSeconds: crossed - p.dropAt, laps: p.laps, factor: p.factor,
      roomAtCrossing: beat.room,
      cutOnDeck: cutSeen, deckSeconds: (p.distance - p.deckAt) / (2.8 * p.factor),
      grooveBars: (p.actualStartBar ?? -Infinity) - p.previousDrop,
      controller: !debug.noSpeedControl};
    debug.crossings.push(result);
    if (debug.crossings.length > 32) debug.crossings.shift();
    if (debug.noSpeedControl && Math.abs(result.errorSeconds) > BEAT && !debug.firstMiss)
      debug.firstMiss = result;
    const next = (legIndex + 1) % legs.length;
    if (!next) pass++;
    setPlan(next, next ? legs[next - 1].land : 0, p.dropAt, p.dropBar);
    requestRoom();
  }

  function placeBike(api, a, speed, dt, clockDelta) {
    const P = api.player, bike = api.bike;
    const oldX = P.x, oldZ = P.z, oldYaw = bike.heading;
    const ground = api.surfaceAt(a.x, a.z, a.y);
    if (ground === null) { debug.surfaceGaps++; stop(); return false; }
    P.x = a.x; P.y = ground; P.z = a.z;
    bike.x = P.x; bike.y = P.y; bike.z = P.z;
    bike.heading = a.yaw; bike.vAngle = a.yaw;
    const angle = Math.atan2(Math.sin(a.yaw - oldYaw), Math.cos(a.yaw - oldYaw));
    bike.yawRate = angle / Math.max(1e-3, clockDelta);
    bike.speed = speed;
    debug.minSpeed = Math.min(debug.minSpeed, speed);
    const lean = clamp(Math.atan(bike.speed * bike.yawRate / (9.81 / 4.5)),
      -35 * Math.PI / 180, 35 * Math.PI / 180);
    bike.lean += (lean - bike.lean) * (1 - Math.exp(-7 * dt));
    const half = .27 * 1.3 / 2;
    const front = api.surfaceAt(P.x + Math.sin(a.yaw) * half, P.z + Math.cos(a.yaw) * half, P.y);
    const rear = api.surfaceAt(P.x - Math.sin(a.yaw) * half, P.z - Math.cos(a.yaw) * half, P.y);
    const pitch = front !== null && rear !== null ? -Math.atan((front - rear) / (2 * half)) : 0;
    bike.pitch += (pitch - bike.pitch) * (1 - Math.exp(-12 * dt));
    bike.spin = (bike.spin + Math.hypot(P.x - oldX, P.z - oldZ) / (TAU * .055 * 1.3)) % 1000;
    P.yaw = a.yaw; P.speed = bike.speed; P.vx = (P.x - oldX) / Math.max(dt, 1e-3);
    P.vz = (P.z - oldZ) / Math.max(dt, 1e-3); P.onBike = true;
    cityAudio.setRideHeading(a.yaw);
    return true;
  }

  // Called from explore.update in place of its physics-bike step. Every position comes
  // from beat.seconds(), so a hidden tab catches up in one frame without a camera reset.
  function drive(dt, api) {
    if (!active) return;
    const now = beat.seconds();
    if (beat.diagnostics.sourceChanges !== sourceChanges) {
      sourceChanges = beat.diagnostics.sourceChanges;
      replanSource(now);
    }
    if (waitingRoom) tickRoom(now);
    const clockDelta = Math.max(0, now - lastClock);
    if (!plan) {
      const loop = waitingLoop, j = loop.joint;
      loop.distance += j.ring.cruise * clockDelta;
      const complete = loop.distance >= j.ring.length;
      if (complete) loop.distance %= j.ring.length;
      const a = routeAt(j.ring, j.ringS + j.direction * loop.distance, position);
      if (j.direction < 0) a.yaw += Math.PI;
      a.s = j.anchor; a.onDeck = false;
      if (!placeBike(api, a, j.ring.cruise, dt, clockDelta)) return;
      lastClock = now;
      if (complete && loop.ready) {
        setPlan(legIndex, j.anchor, now, loop.previousDrop);
        waitingLoop = null;
      }
      return;
    }
    requestRoom(); checkDrop();
    const cruise = q < plan.deckAt ? plan.ringCruise : 2.8;
    if (waitingRoom || debug.noSpeedControl) q = Math.min(plan.distance, q + cruise * clockDelta);
    else q = qAt(plan, now);
    lastClock = now;
    if (!cutSeen && now >= plan.cutAt && now <= plan.dropAt + .1) cutSeen = q >= plan.deckAt;
    const remaining = plan.tau - tauAt(plan, q);
    const secondsLeft = Math.max(.001, plan.dropAt - now);
    const factor = waitingRoom || debug.noSpeedControl ? 1 : clamp(remaining / secondsLeft, MIN, MAX);
    const a = sampleAt(plan, q, position);
    if (!placeBike(api, a, cruise * factor, dt, clockDelta)) return;
    if (q >= plan.distance - 1e-4) {
      recordCrossing(now, now);
    }
  }

  explore.tourHook = start;
  explore.tourExit = stopRide;
  return {start, stop, drive, debug, get active() { return active; },
    get leg() { return legIndex; }, get plan() { return plan; },
    get speed() { return explore.bike.speed; },
    bikePosition() { return explore.position; },
    positionAt(k, distance, out) { return sampleAt(plan && plan.k === k ? plan :
      choose(k, k ? legs[k - 1].land : 0, 0, 0), distance, out); }};
})();
