// Explore mode (C8, C3.8, C7.2): the visitor walks the city or rides a light cycle through it. This module
// owns input (keyboard, mouse, touch, gamepad), the player and the bike, the ground and collision read from
// the design data, the cameras, music by position, photo mode and the deep links. The avatar is a crowd
// person (crowd.avatar) whose matrices this module writes. Nothing here touches a note building, cityMat or
// window light (B1, B2): the only glows are the visitor's own, small, and never music-driven.
const explore = (() => {
  const D = DATA.design, GRAVITY = 9.81 / 4.5, BAR = beat.barSeconds, DEG = Math.PI / 180;
  const FOOT = {walk: .9, sprint: 1.6, radius: .07, stepUp: .12, stepDown: .3, jump: .72};
  // The kit is modelled at NPC size (C5.1, about .45 long); the visitor's bike is drawn 1.3 times larger so a rider fits.
  const BIKE = {top: 5, boost: 7, boostTime: 3, recharge: 6, accel: 2.4, boostAccel: 4.2, brake: 5, drag: .7, reverse: .8,
    radius: .11, nose: .26, stepUp: .2, stepDown: .3, maxLean: 35 * DEG, cruise: 2.8, wheel: .055, base: .27, scale: 1.3};
  const clamp = (v, a, b) => v < a ? a : v > b ? b : v;
  const wrapAngle = a => a - Math.round(a / TAU) * TAU;
  const damp = (k, dt) => 1 - Math.exp(-k * dt);
  const V3 = THREE.Vector3;
  const api = {active: false, frozen: false, pilot: null, tourHook: null, tourDriver: null, tourExit: null};

  // ------------------------------------------------------------------ ground (C8.4)
  // Walkable surfaces come from the design data, never from meshes: plateau tops, ring roads, avenues and
  // links, bridge decks and their junction fillets, stage decks, the pier and the island. Layout (x, y) is
  // world (x, -z). probe() fills `hit` with the surface nearest the given height, so an overpass and the
  // road under it never merge; surfaceAt() returns that height or null (void, water, inside a footprint).
  const K = {none: 0, plateau: 1, stage: 2, route: 3, street: 4, bridge: 5, pier: 6, fillet: 7, extra: 8, water: 9, building: 10, gangway: 11};
  const routeHalf = r => (r.width || (r.district === 'episodic' ? .54 : .88)) / 2 + .13;
  // A disc plateau's ring road is its own closed route at a steady radius. Most rings overlap the rim, but a
  // ring set further out (rim + 0.75) leaves a band between the slab and the inner curb: the plateau is
  // walkable out to that curb, so no kerb that looks walkable is an invisible wall.
  function ringOf(d, p) {
    let best = null, bestSpread = Infinity;
    D.routes.forEach(r => {
      if (r.district !== d || r.points.length < 8) return;
      let sum = 0, sq = 0;
      for (const q of r.points) { const l = Math.hypot(q[0] - p.cx, q[1] - p.cy); sum += l; sq += l * l; }
      const n = r.points.length, mean = sum / n, spread = Math.sqrt(Math.max(0, sq / n - mean * mean)) / mean;
      if (spread < .04 && spread < bestSpread) { bestSpread = spread; best = {radius: mean, half: routeHalf(r)}; }
    });
    return best;
  }
  const plates = Object.entries(DATA.plateaus).map(([d, p]) => {
    const disc = p.shape === 'disc', ring = disc ? ringOf(d, p) : null;
    return {d, disc, cx: p.cx, cy: p.cy, rx: p.rx, ry: p.ry, z: p.z,
      walk: ring ? Math.max(p.rx, ring.radius - ring.half + .02) : p.rx, foot: ring ? ring.radius + ring.half : p.rx + .97};
  });
  const decks = D.stages.map(s => ({d: s.district, x: s.x, y: s.y, r: s.r, z: s.z}));
  const lake = (D.lake || [])[0] || null;
  if (lake && lake.island) decks.push({d: 'reef', x: lake.island.x, y: lake.island.y, r: lake.island.r, z: lake.island.z});
  const SEG = 11, segList = [], filList = [], cells = new Map(), CELL = 2, extras = [];
  const cellKey = (i, j) => (i + 32768) * 65536 + (j + 32768);
  function indexBox(entry, ax, ay, bx, by) {
    for (let i = Math.floor(ax / CELL); i <= Math.floor(bx / CELL); i++) for (let j = Math.floor(ay / CELL); j <= Math.floor(by / CELL); j++) {
      const k = cellKey(i, j); let list = cells.get(k); if (!list) cells.set(k, list = []); list.push(entry); }
  }
  function addLine(points, closed, z, half, kind, owner) {
    const n = points.length; let s = 0;
    for (let i = 0; i < (closed ? n : n - 1); i++) {
      const a = points[i], b = points[(i + 1) % n], len = Math.hypot(b[0] - a[0], b[1] - a[1]);
      if (len < 1e-6) continue;
      const k = segList.length / SEG;
      segList.push(a[0], a[1], a.length > 2 ? a[2] : z, b[0], b[1], b.length > 2 ? b[2] : z, half, kind, owner, s, len);
      indexBox(k, Math.min(a[0], b[0]) - half, Math.min(a[1], b[1]) - half, Math.max(a[0], b[0]) + half, Math.max(a[1], b[1]) + half);
      s += len;
    }
  }
  D.routes.forEach((r, i) => addLine(r.points, true, r.z, routeHalf(r), K.route, i));
  (D.streets || []).forEach((s, i) => addLine(s.points, false, s.z, (s.width || .54) / 2 + .13, K.street, i));
  (D.bridges || []).forEach((b, i) => addLine(b.points, false, 0, b.halfWidth || .57, K.bridge, i));
  if (lake && lake.pier) addLine([[lake.pier.x0, lake.pier.y0], [lake.pier.x1, lake.pier.y1]], false, lake.pier.z, lake.pier.width / 2, K.pier, 0);
  // A cantilevered deck only touches its ring at one point (C4.2), so each gets a gangway 1.1 wide from the
  // deck across that touch point onto the ring; elsewhere the gap between them is a rail like any other edge.
  D.stages.forEach((st, i) => {
    const p = DATA.plateaus[st.district];
    if (st.kind !== 'deck' || !p) return;
    const dx = p.cx - st.x, dy = p.cy - st.y, l = Math.hypot(dx, dy) || 1, ux = dx / l, uy = dy / l;
    addLine([[st.x + ux * (st.r - .3), st.y + uy * (st.r - .3)], [st.x + ux * (st.r + .6), st.y + uy * (st.r + .6)]], false, st.z, .55, K.gangway, i);
  });
  // A junction fillet paves the corner between a ring edge and a bridge edge: the kite from the arc centre
  // through both tangent points to where the two edges meet, outside the sidewalk curb (radius r - 0.13).
  (D.bridges || []).forEach((b, bi) => b.ends.forEach(end => (end.fillets || []).forEach(f => {
    const [rx, ry] = f.ring, [bx, by] = f.bridge, ux = -(ry - f.cy), uy = rx - f.cx, wx = -(by - f.cy), wy = bx - f.cx;
    const den = ux * wy - uy * wx;
    if (Math.abs(den) < 1e-9) return;
    const t = ((bx - rx) * wy - (by - ry) * wx) / den, vx = rx + ux * t, vy = ry + uy * t;
    const k = filList.length / 10;
    filList.push(f.cx, f.cy, f.r - .13, rx, ry, vx, vy, bx, by, end.z);
    indexBox(-(k + 1), Math.min(rx, vx, bx, f.cx) - .01, Math.min(ry, vy, by, f.cy) - .01, Math.max(rx, vx, bx, f.cx) + .01, Math.max(ry, vy, by, f.cy) + .01);
  })));
  const SEGS = new Float64Array(segList), FILS = new Float64Array(filList);
  const hit = {h: 0, kind: 0, owner: -1, s: 0};
  // QA positive controls only: each switch breaks one feature so its gate can be shown to fail.
  const debug = {noCollide: false, noBridgeHalves: false, noBridges: false, noRingCurb: false, noCamFloor: false, photoAsIs: false, forceVeil: null};
  let pScore = 0, pNear = 0, pUse = false, pFound = false;
  function take(h, kind, owner, s) {
    const score = pUse ? Math.abs(h - pNear) : -h;
    if (score < pScore) { pScore = score; pFound = true; hit.h = h; hit.kind = kind; hit.owner = owner; hit.s = s; }
  }
  function rectSdf(p, x, y, grow) {
    const qx = Math.abs(x - p.cx) - (p.rx - 2.5), qy = Math.abs(y - p.cy) - (p.ry - 2.5);
    return Math.hypot(Math.max(qx, 0), Math.max(qy, 0)) + Math.min(Math.max(qx, qy), 0) - 2.5 - grow;
  }
  const side = (ax, ay, bx, by, x, y) => (bx - ax) * (y - ay) - (by - ay) * (x - ax);
  function inLake(x, y) {
    if (!lake) return false;
    const dx = x - lake.cx, dy = y - lake.cy, c = Math.cos(lake.angle), s = Math.sin(lake.angle);
    const u = (dx * c + dy * s) / lake.rx, v = (-dx * s + dy * c) / lake.ry;
    return u * u + v * v < 1;
  }
  function probe(x, wz, nearY) {
    const lx = x, ly = -wz;
    pUse = nearY !== undefined && nearY !== null; pNear = pUse ? nearY : 0; pScore = Infinity; pFound = false; hit.kind = K.none;
    for (let i = 0; i < plates.length; i++) {
      const p = plates[i];
      const w = debug.noRingCurb ? p.rx : p.walk;
      if (p.disc ? (lx - p.cx) * (lx - p.cx) + (ly - p.cy) * (ly - p.cy) <= w * w : rectSdf(p, lx, ly, 0) <= 0) take(p.z, K.plateau, i, 0);
    }
    for (let i = 0; i < decks.length; i++) {
      const s = decks[i];
      if ((lx - s.x) * (lx - s.x) + (ly - s.y) * (ly - s.y) <= s.r * s.r) take(s.z, K.stage, i, 0);
    }
    const list = cells.get(cellKey(Math.floor(lx / CELL), Math.floor(ly / CELL)));
    if (list) for (let n = 0; n < list.length; n++) {
      const e = list[n];
      if (e >= 0) {
        const o = e * SEG, kind = SEGS[o + 7];
        if (kind === K.bridge && debug.noBridges) continue;
        const ax = SEGS[o], ay = SEGS[o + 1], bx = SEGS[o + 3], by = SEGS[o + 4], len = SEGS[o + 10], half = SEGS[o + 6];
        const t = clamp(((lx - ax) * (bx - ax) + (ly - ay) * (by - ay)) / (len * len), 0, 1);
        const dx = lx - ax - (bx - ax) * t, dy = ly - ay - (by - ay) * t;
        if (dx * dx + dy * dy > half * half) continue;
        take(SEGS[o + 2] + (SEGS[o + 5] - SEGS[o + 2]) * t, kind, SEGS[o + 8], SEGS[o + 9] + len * t);
      } else {
        const o = (-e - 1) * 10, cx = FILS[o], cy = FILS[o + 1], rr = FILS[o + 2];
        if ((lx - cx) * (lx - cx) + (ly - cy) * (ly - cy) < rr * rr) continue;
        const rx = FILS[o + 3], ry = FILS[o + 4], vx = FILS[o + 5], vy = FILS[o + 6], bx = FILS[o + 7], by = FILS[o + 8];
        const s1 = side(cx, cy, rx, ry, lx, ly), s2 = side(rx, ry, vx, vy, lx, ly), s3 = side(vx, vy, bx, by, lx, ly), s4 = side(bx, by, cx, cy, lx, ly);
        if ((s1 >= 0 && s2 >= 0 && s3 >= 0 && s4 >= 0) || (s1 <= 0 && s2 <= 0 && s3 <= 0 && s4 <= 0)) take(FILS[o + 9], K.fillet, -e - 1, 0);
      }
    }
    for (let i = 0; i < extras.length; i++) { const h = extras[i](lx, ly); if (h !== null && h !== undefined) take(h, K.extra, i, 0); }
    // The lake answers for its sand, pier and island; null blocks water and the outer bank.
    const lakeHeight = nature.surfaceAt(lx, wz);
    if (lakeHeight === null) { hit.kind = K.water; return false; }
    if (lakeHeight !== undefined) take(lakeHeight, K.extra, -1, 0);
    if (!pFound) { if (inLake(lx, ly)) hit.kind = K.water; return false; }
    if (insideFootprint(x, wz, hit.h, 0)) { hit.kind = K.building; return false; }
    return true;
  }
  const surfaceAt = (x, z, nearY) => probe(x, z, nearY) ? hit.h : null;
  // Which district a point belongs to for the music (C8.6): the plateau, its ring and its stage deck, measured
  // as depth inside that footprint; on a bridge each half belongs to the district it leads to.
  const zone = {district: null, depth: 0};
  function zoneAt(x, wz, nearY) {
    zone.district = null; zone.depth = -Infinity;
    if (probe(x, wz, nearY) && hit.kind === K.bridge && !debug.noBridgeHalves) {
      const b = D.bridges[hit.owner], split = b.split || b.length / 2;
      zone.district = hit.s < split ? b.from : b.to; zone.depth = Math.abs(hit.s - split); return zone;
    }
    if (hit.kind === K.bridge || hit.kind === K.none || hit.kind === K.water) return zone;
    if (hit.kind === K.extra && nature.surfaceAt(x, wz) !== undefined) {
      zone.district = 'reef'; zone.depth = 1; return zone;
    }
    const lx = x, ly = -wz;
    for (let i = 0; i < plates.length; i++) {
      const p = plates[i], d = p.disc ? p.foot - Math.hypot(lx - p.cx, ly - p.cy) : -rectSdf(p, lx, ly, .97);
      if (d > zone.depth) { zone.depth = d; zone.district = p.d; }
    }
    for (let i = 0; i < decks.length; i++) {
      const s = decks[i], d = s.r - Math.hypot(lx - s.x, ly - s.y);
      if (d > zone.depth) { zone.depth = d; zone.district = s.d; }
    }
    return zone;
  }

  // ------------------------------------------------------------------ collision against footprints
  // The page's obstacle grid (city-life.js) holds every building box with its 0.57 overhang. Absent buildings
  // do not collide; a circle is pushed out of each box it touches, which slides it along the wall.
  const stageProps = stages.map(s => ({x: s.booth.x, z: s.booth.z, r: .46}));
  const boxTop = b => plateauZ(b.n.district) + b.n.h * b.n.rise * 1.08 + .14;
  function insideFootprint(x, z, y, radius) {
    const list = obstacleGrid.get(Math.floor(x / 2) * 65536 + Math.floor(z / 2));
    if (!list) return false;
    for (let i = 0; i < list.length; i++) {
      const b = list[i];
      if (b.n.state === 'absent' || y > boxTop(b) || y < plateauZ(b.n.district) - .1) continue;
      if (x > b.minX - radius && x < b.maxX + radius && z > b.minZ - radius && z < b.maxZ + radius) return true;
    }
    return false;
  }
  const at = {x: 0, z: 0};
  function pushOut(y, radius) {
    for (let pass = 0; pass < 2; pass++) {
      const list = obstacleGrid.get(Math.floor(at.x / 2) * 65536 + Math.floor(at.z / 2));
      if (list) for (let i = 0; i < list.length; i++) {
        const b = list[i];
        if (b.n.state === 'absent' || y + .02 > boxTop(b) || y < plateauZ(b.n.district) - .1) continue;
        const cx = clamp(at.x, b.minX, b.maxX), cz = clamp(at.z, b.minZ, b.maxZ), dx = at.x - cx, dz = at.z - cz, d2 = dx * dx + dz * dz;
        if (d2 >= radius * radius) continue;
        if (d2 > 1e-12) { const d = Math.sqrt(d2); at.x = cx + dx / d * radius; at.z = cz + dz / d * radius; }
        else {
          const l = at.x - b.minX, r = b.maxX - at.x, n = at.z - b.minZ, f = b.maxZ - at.z, m = Math.min(l, r, n, f);
          if (m === l) at.x = b.minX - radius; else if (m === r) at.x = b.maxX + radius; else if (m === n) at.z = b.minZ - radius; else at.z = b.maxZ + radius;
        }
      }
      for (let i = 0; i < stageProps.length; i++) {
        const s = stageProps[i], dx = at.x - s.x, dz = at.z - s.z, d2 = dx * dx + dz * dz, rr = s.r + radius;
        if (d2 < rr * rr && d2 > 1e-12 && Math.abs(stages[i].z - y) < .3) { const d = Math.sqrt(d2); at.x = s.x + dx / d * rr; at.z = s.z + dz / d * rr; }
      }
    }
  }
  // One sub-step: the target (after the push-out) must stand on a surface within the step limits, and so must
  // a probe point `reach` ahead in the direction of travel; otherwise the rail or the water stops it.
  function tryStep(nx, nz, y, radius, stepUp, stepDown, grounded, ax, az, reach) {
    at.x = nx; at.z = nz;
    if (!debug.noCollide) pushOut(y, radius);
    // debug.noCollide (QA positive control only) lets the visitor walk into footprints, never off the world.
    if (!probe(at.x, at.z, y) && !(debug.noCollide && hit.kind === K.building)) return NaN;
    const h = hit.h;
    if (!debug.noCollide) {
      if (h - y > stepUp || (grounded && y - h > stepDown)) return NaN;
      if (reach > 0) {
        const ahead = surfaceAt(at.x + ax * reach, at.z + az * reach, h);
        if (ahead === null || Math.abs(ahead - h) > stepUp) return NaN;
        if (insideFootprint(at.x + ax * reach * .6, at.z + az * reach * .6, h, .02)) return NaN;
      }
    }
    return h;
  }
  const step = {x: 0, z: 0, h: 0, frac: 0};
  function advance(dx, dz, y, radius, stepUp, stepDown, grounded, reach) {
    const len = Math.hypot(dx, dz), ax = len ? dx / len : 0, az = len ? dz / len : 0;
    let h = tryStep(P.x + dx, P.z + dz, y, radius, stepUp, stepDown, grounded, ax, az, reach);
    if (h === h) { step.x = at.x; step.z = at.z; step.h = h; step.frac = 1; return true; }
    // Slide: keep the longer axis component first, then the other, so rails and walls are followed.
    const xFirst = Math.abs(dx) >= Math.abs(dz);
    for (let pass = 0; pass < 2; pass++) {
      const useX = (pass === 0) === xFirst, sx = useX ? dx : 0, sz = useX ? 0 : dz, l = Math.abs(useX ? dx : dz);
      if (l < 1e-6) continue;
      h = tryStep(P.x + sx, P.z + sz, y, radius, stepUp, stepDown, grounded, useX ? Math.sign(dx) : 0, useX ? 0 : Math.sign(dz), reach);
      if (h === h) { step.x = at.x; step.z = at.z; step.h = h; step.frac = l / (len || 1); return true; }
    }
    step.frac = 0; return false;
  }

  // ------------------------------------------------------------------ the player, the avatar and the bike state
  const P = {x: 0, y: 0, z: 0, vx: 0, vz: 0, vy: 0, yaw: 0, grounded: true, onBike: false, dancing: false, danceStyle: 'nod',
    stride: 0, speed: 0};
  const bike = {present: false, heading: 0, vAngle: 0, speed: 0, yawRate: 0, lean: 0, pitch: 0, charge: 1, boosting: false,
    slide: false, spin: 0, derez: 0, derezDir: 0, x: 0, y: 0, z: 0};
  const av = crowd.avatar, J = crowd.joints, ATTACH = crowd.attach, parts = crowd.parts, accs = crowd.accessories;
  const pose = {dip: 0, jump: 0, sway: 0, twist: 0, lean: 0, nod: 0, aA: 0, bA: 0, aB: 0, bB: 0, lA: 0, lB: 0};
  const look = {x: 0, y: 0, z: 0, yaw: 0, roll: 0, pitch: 0, shrink: 1, lift: 0};
  const mRoot = new THREE.Matrix4(), mLocal = new THREE.Matrix4(), mRot = new THREE.Matrix4(), mTwist = new THREE.Matrix4(), mOut = new THREE.Matrix4();
  const mFlip = new THREE.Matrix4().makeRotationY(Math.PI);
  const qRoot = new THREE.Quaternion(), eRoot = new THREE.Euler(0, 0, 0, 'YXZ'), vRoot = new V3(), sRoot = new V3(), sPart = new V3();
  // `flip` turns the piece half round about its own joint first: the back stripe is the chest stripe turned.
  function limb(mesh, slot, jx, jy, jz, a, b, sx, sy, sz, twist, flip) {
    mLocal.makeRotationZ(b); mRot.makeRotationX(a); mLocal.multiply(mRot);
    if (flip) mLocal.multiply(mFlip);
    mLocal.scale(sPart.set(sx, sy, sz)); mLocal.setPosition(jx, jy, jz);
    if (twist) { mTwist.makeRotationY(twist); mLocal.premultiply(mTwist); }
    mOut.multiplyMatrices(mRoot, mLocal); mOut.toArray(mesh.instanceMatrix.array, slot * 16);
  }
  // The avatar's writer: the crowd's joint layout under a root that can roll and pitch with the bike.
  function writeAvatar(p) {
    const i = crowd.avatarIndex, s = p.scale * look.shrink, d = pose.dip, tw = pose.twist;
    vRoot.set(look.x + pose.sway * Math.cos(look.yaw), look.y + pose.jump + look.lift, look.z - pose.sway * Math.sin(look.yaw));
    eRoot.set(look.pitch, look.yaw, look.roll); qRoot.setFromEuler(eRoot);
    mRoot.compose(vRoot, qRoot, sRoot.set(s, s * (look.shrink < 1 ? .6 + .4 * look.shrink : 1), s));
    const legScale = (J.hipY - d) / J.hipY;
    limb(parts.legA, i, J.hipX, J.hipY - d, 0, pose.lA, 0, 1, legScale, 1, 0);
    limb(parts.legB, i, -J.hipX, J.hipY - d, 0, pose.lB, 0, 1, legScale, 1, 0);
    limb(parts.hips, i, 0, J.hipY + .01 - d, 0, 0, 0, 1, 1, 1, 0);
    limb(parts.torso, i, 0, J.torsoY - d, 0, pose.lean, 0, 1, 1, 1, tw);
    limb(parts.armA, i, J.shoulderX, J.shoulderY - d, 0, pose.aA, pose.bA, 1, 1, 1, tw);
    limb(parts.armB, i, -J.shoulderX, J.shoulderY - d, 0, pose.aB, pose.bB, 1, 1, 1, tw);
    limb(parts.head, i, 0, J.neckY - d, 0, pose.nod, 0, 1, 1, 1, tw);
    limb(parts.hair, i, 0, J.neckY - d, 0, pose.nod, 0, 1, 1, 1, tw);
    for (let k = 0; k < p.acc.length; k++) {
      const a = p.acc[k], mesh = accs[a.name], where = ATTACH[a.name];
      if (where === 'head') limb(mesh, a.slot, 0, J.neckY - d, 0, pose.nod, 0, 1, 1, 1, tw);
      else if (where === 'torso') limb(mesh, a.slot, 0, J.torsoY - d, 0, pose.lean, 0, 1, 1, 1, tw, a.back);
      else if (where === 'hips') limb(mesh, a.slot, 0, J.hipY + .03 - d, 0, 0, 0, 1, 1, 1, 0);
      else if (where === 'armA') limb(mesh, a.slot, J.shoulderX, J.shoulderY - d, 0, pose.aA, pose.bA, 1, 1, 1, tw);
      else if (where === 'arms') { limb(mesh, a.slot * 2, J.shoulderX, J.shoulderY - d, 0, pose.aA, pose.bA, 1, 1, 1, tw); limb(mesh, a.slot * 2 + 1, -J.shoulderX, J.shoulderY - d, 0, pose.aB, pose.bB, 1, 1, 1, tw); }
      else limb(mesh, a.slot, 0, 0, 0, 0, 0, 1, 1, 1, 0);
    }
  }
  // Outfits: index 0 is the page accent (teal jacket, #6be7e1 stripe); O deals new ones that keep the stripe.
  const TEAL = '#6be7e1', baseOutfit = av.outfit;
  let outfit = baseOutfit, outfitIndex = 0;
  const outfitDistricts = Object.keys(DATA.plateaus);
  function shuffleOutfit() {
    outfitIndex = (outfitIndex + 1) % 12;
    if (outfitIndex === 0) outfit = baseOutfit;
    else { const rnd = mulberry(9001 + outfitIndex * 131); outfit = crowd.dress(outfitDistricts[outfitIndex % outfitDistricts.length], rnd); outfit.acc.strips = TEAL; }
    if (!P.onBike) crowd.dressAvatar(outfit);
  }
  // On the bike the visitor wears the rider's dark suit with light lines in the accent (C7.2).
  const riderOf = o => ({archetype: 6, skin: o.skin, hair: o.hair, hairStyle: 'none', top: '#0c1117', sleeve: '#0c1117', bottom: '#0c1117', leg: '#0c1117',
    acc: {strips: TEAL, visor: TEAL, cap: '#0e141b'}});

  // ------------------------------------------------------------------ the light cycle (C7.2)
  // Procedural: a low long shell, two large wheels with glowing rims, light lines along the flanks. Two
  // instanced meshes (body, glow) sized for NPC riders too: roads.js can build its own with api.bikeKit.
  function mergeGeometries(list) {
    const pos = [], nor = [], wheel = [], tail = [];
    for (const [g, w, t] of list) {
      const n = g.index ? g.toNonIndexed() : g, count = n.attributes.position.count;
      pos.push(...n.attributes.position.array); nor.push(...n.attributes.normal.array);
      for (let i = 0; i < count; i++) { wheel.push(w); tail.push(t); }
    }
    const out = new THREE.BufferGeometry();
    out.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
    out.setAttribute('normal', new THREE.Float32BufferAttribute(nor, 3));
    out.setAttribute('aWheel', new THREE.Float32BufferAttribute(wheel, 1));
    out.setAttribute('aTail', new THREE.Float32BufferAttribute(tail, 1));
    return out;
  }
  function bikeKit() {
    const W0 = BIKE.wheel, zF = BIKE.base / 2, zR = -BIKE.base / 2;
    const shape = new THREE.Shape();
    [[-.215, .064], [-.222, .1], [-.17, .118], [-.07, .104], [.01, .128], [.12, .125], [.2, .098], [.228, .07], [.18, .05], [.06, .036], [-.08, .036], [-.18, .046]]
      .forEach(([u, v], i) => i ? shape.lineTo(u, v) : shape.moveTo(u, v));
    const shell = new THREE.ExtrudeGeometry(shape, {depth: .048, bevelEnabled: true, bevelThickness: .006, bevelSize: .005, bevelSegments: 1, curveSegments: 4});
    shell.translate(0, 0, -.024); shell.rotateY(-Math.PI / 2);
    const tyre = z => new THREE.TorusGeometry(W0 - .01, .011, 6, 22).rotateY(Math.PI / 2).translate(0, W0, z);
    const hub = z => new THREE.CylinderGeometry(.026, .026, .036, 12).rotateZ(Math.PI / 2).translate(0, W0, z);
    const rim = (z, x) => new THREE.TorusGeometry(W0 - .016, .0032, 4, 30).rotateY(Math.PI / 2).translate(x, W0, z);
    const strip = (x, u0, u1, v) => new THREE.BoxGeometry(.003, .005, u1 - u0).translate(x, v, (u0 + u1) / 2);
    const body = mergeGeometries([[shell, 0, 0], [tyre(zF), 0, 0], [tyre(zR), 0, 0], [hub(zF), 0, 0], [hub(zR), 0, 0]]);
    const glow = mergeGeometries([[rim(zF, .021), 1, 0], [rim(zF, -.021), 1, 0], [rim(zR, .021), 2, 0], [rim(zR, -.021), 2, 0],
      [strip(.031, -.2, .2, .082), 0, 0], [strip(-.031, -.2, .2, .082), 0, 0], [strip(.03, -.12, .1, .112), 0, 0], [strip(-.03, -.12, .1, .112), 0, 0],
      [new THREE.BoxGeometry(.034, .005, .004).translate(0, .094, -.224), 0, 1]]);
    return {body, glow};
  }
  const derezChunk = `
    float dzHash = fract(sin(dot(floor(vLocal * 90.0), vec3(12.9898, 78.233, 37.719))) * 43758.5453);
    float dzEdge = clamp(vLocal.y / 0.14, 0.0, 1.0) * 0.7 + dzHash * 0.3, dzLevel = uDerez * 1.2 - 0.1;
    if (dzEdge > dzLevel) discard;
    float dzBand = (1.0 - smoothstep(0.0, 0.07, dzLevel - dzEdge)) * step(uDerez, 0.999) * uBand;`;
  const bikeUniforms = {uKey: {value: KEY}, uDerez: {value: 0}, uBand: {value: reduced ? 0 : 1}, uSpin: {value: 0}, uAccent: {value: col(hex(TEAL))}};
  const bikeVertex = `attribute float aWheel; attribute float aTail; varying vec3 vLocal, vN, vColor, vWorld; varying float vWheel, vTail;
    #include <fog_pars_vertex>
    void main(){ vLocal = position; vWheel = aWheel; vTail = aTail;
      #ifdef USE_INSTANCING_COLOR
        vColor = instanceColor;
      #else
        vColor = vec3(1.0);
      #endif
      vec4 world = modelMatrix * instanceMatrix * vec4(position, 1.0); vWorld = world.xyz;
      vN = normalize(mat3(modelMatrix) * mat3(instanceMatrix) * normal);
      vec4 mvPosition = viewMatrix * world; gl_Position = projectionMatrix * mvPosition;
      #include <fog_vertex>
    }`;
  const bikeBodyMat = new THREE.ShaderMaterial({fog: true, uniforms: THREE.UniformsUtils.merge([THREE.UniformsLib.fog]), vertexShader: bikeVertex,
    fragmentShader: `uniform vec3 uKey, uAccent; uniform float uDerez, uBand; varying vec3 vLocal, vN, vColor, vWorld; varying float vWheel, vTail;
      #include <fog_pars_fragment>
      void main(){ ${derezChunk}
        vec3 n = normalize(vN), v = normalize(cameraPosition - vWorld);
        float d = max(dot(n, uKey), 0.0), fres = pow(1.0 - abs(dot(n, v)), 3.0), spec = pow(max(dot(reflect(-uKey, n), v), 0.0), 24.0);
        vec3 c = vec3(.018, .024, .032) * (.55 + .45 * d) + uAccent * fres * .12 + vec3(.5, .6, .7) * spec * .35;
        c = mix(c, uAccent * 1.6, dzBand);
        gl_FragColor = vec4(c, 1.0);
        #include <fog_fragment>
        #include <colorspace_fragment>
      }`});
  const bikeGlowMat = new THREE.ShaderMaterial({fog: true, uniforms: THREE.UniformsUtils.merge([THREE.UniformsLib.fog]), vertexShader: bikeVertex,
    fragmentShader: `uniform vec3 uAccent; uniform float uDerez, uBand, uSpin; varying vec3 vLocal, vN, vColor, vWorld; varying float vWheel, vTail;
      #include <fog_pars_fragment>
      void main(){ ${derezChunk}
        float dash = 1.0;
        if (vWheel > .5) { vec2 c = vec2(vWheel < 1.5 ? ${(BIKE.base / 2).toFixed(3)} : ${(-BIKE.base / 2).toFixed(3)}, ${BIKE.wheel.toFixed(3)});
          float a = atan(vLocal.y - c.y, vLocal.z - c.x) / 6.2831853; dash = .55 + .45 * step(.5, fract(a * 6.0 + uSpin)); }
        vec3 c = mix(uAccent * vColor, vec3(1.0, .25, .18), vTail) * 1.7 * dash;
        c = mix(c, uAccent * 2.2, dzBand);
        gl_FragColor = vec4(c, 1.0);
        #include <fog_fragment>
        #include <colorspace_fragment>
      }`});
  for (const m of [bikeBodyMat, bikeGlowMat]) Object.assign(m.uniforms, bikeUniforms);
  const kit = bikeKit();
  const bikeBody = new THREE.InstancedMesh(kit.body, bikeBodyMat, 1), bikeGlow = new THREE.InstancedMesh(kit.glow, bikeGlowMat, 1);
  for (const m of [bikeBody, bikeGlow]) { m.frustumCulled = false; m.visible = false; m.setColorAt(0, new THREE.Color(1, 1, 1)); scene.add(m); }
  const bikeDummy = new THREE.Object3D();

  // The light trail (C7.2): a ribbon 0.12 tall of the last 4 s, additive, coloured by the district the bike is
  // in at that moment. Samples live in a ring; each frame writes them oldest to newest, no allocation.
  const TRAIL_MAX = 96, TRAIL_SECONDS = 4;
  const trail = {n: 0, head: 0, last: -1, x: new Float32Array(TRAIL_MAX), y: new Float32Array(TRAIL_MAX), z: new Float32Array(TRAIL_MAX),
    r: new Float32Array(TRAIL_MAX), g: new Float32Array(TRAIL_MAX), b: new Float32Array(TRAIL_MAX), t: new Float32Array(TRAIL_MAX), clock: 0};
  const trailGeo = new THREE.BufferGeometry();
  const tPos = new Float32Array((TRAIL_MAX + 1) * 6), tCol = new Float32Array((TRAIL_MAX + 1) * 6), tAge = new Float32Array((TRAIL_MAX + 1) * 2), tEdge = new Float32Array((TRAIL_MAX + 1) * 2);
  for (let i = 0; i <= TRAIL_MAX; i++) { tEdge[i * 2] = 0; tEdge[i * 2 + 1] = 1; }
  const tIndex = [];
  for (let i = 0; i < TRAIL_MAX; i++) { const a = i * 2; tIndex.push(a, a + 2, a + 1, a + 1, a + 2, a + 3); }
  trailGeo.setIndex(tIndex);
  trailGeo.setAttribute('position', new THREE.BufferAttribute(tPos, 3).setUsage(THREE.DynamicDrawUsage));
  trailGeo.setAttribute('aColor', new THREE.BufferAttribute(tCol, 3).setUsage(THREE.DynamicDrawUsage));
  trailGeo.setAttribute('aAge', new THREE.BufferAttribute(tAge, 1).setUsage(THREE.DynamicDrawUsage));
  trailGeo.setAttribute('aEdge', new THREE.BufferAttribute(tEdge, 1));
  trailGeo.setDrawRange(0, 0);
  const trailAttrs = [trailGeo.attributes.position, trailGeo.attributes.aColor, trailGeo.attributes.aAge];
  const trailMesh = new THREE.Mesh(trailGeo, new THREE.ShaderMaterial({transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide,
    vertexShader: `attribute vec3 aColor; attribute float aAge, aEdge; varying vec3 vColor; varying float vAlpha, vEdge;
      void main(){ vColor = aColor; vEdge = aEdge; vAlpha = clamp(1.0 - aAge / ${TRAIL_SECONDS.toFixed(1)}, 0.0, 1.0);
        gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
    fragmentShader: `varying vec3 vColor; varying float vAlpha, vEdge;
      void main(){ float a = vAlpha * vAlpha * (.12 + .5 * vEdge * vEdge) + vAlpha * .5 * smoothstep(.88, 1.0, vEdge);
        gl_FragColor = vec4(vColor * a * .8, 1.0);
        #include <colorspace_fragment>
      }`}));
  trailMesh.frustumCulled = false; scene.add(trailMesh);
  const districtColor = Object.fromEntries(Object.keys(DATA.plateaus).map(d => [d, lin(styleOf(d).light)]));
  function trailReset() { trail.n = 0; trail.last = -1; trailGeo.setDrawRange(0, 0); }
  const rear = new V3();
  function trailUpdate(dt, riding) {
    trail.clock += dt;
    const every = TRAIL_SECONDS / (tier.current === 3 ? TRAIL_MAX : tier.current === 2 ? 58 : 38);
    rear.set(bike.x - Math.sin(bike.heading) * .27, bike.y, bike.z - Math.cos(bike.heading) * .27);
    while (trail.n && trail.clock - trail.t[(trail.head - trail.n + TRAIL_MAX) % TRAIL_MAX] > TRAIL_SECONDS) trail.n--;
    const moving = riding && Math.abs(bike.speed) > .15;
    if (moving && trail.clock - trail.last >= every) {
      const district = zoneAt(rear.x, rear.z, bike.y).district;
      const c = districtColor[district] || districtColor.core, k = trail.head;
      trail.x[k] = rear.x; trail.y[k] = rear.y; trail.z[k] = rear.z; trail.r[k] = c[0]; trail.g[k] = c[1]; trail.b[k] = c[2]; trail.t[k] = trail.clock;
      trail.head = (k + 1) % TRAIL_MAX; trail.n = Math.min(TRAIL_MAX, trail.n + 1); trail.last = trail.clock;
    }
    let v = 0;
    for (let j = trail.n; j > 0; j--) {
      const k = (trail.head - j + TRAIL_MAX) % TRAIL_MAX;
      writeTrail(v++, trail.x[k], trail.y[k], trail.z[k], trail.r[k], trail.g[k], trail.b[k], trail.clock - trail.t[k]);
    }
    if (moving && trail.n) { const k = (trail.head - 1 + TRAIL_MAX) % TRAIL_MAX; writeTrail(v++, rear.x, rear.y, rear.z, trail.r[k], trail.g[k], trail.b[k], 0); }
    trailGeo.setDrawRange(0, Math.max(0, v - 1) * 6);
    trailAttrs[0].needsUpdate = trailAttrs[1].needsUpdate = trailAttrs[2].needsUpdate = true;
  }
  function writeTrail(v, x, y, z, r, g, b, age) {
    const o = v * 6;
    tPos[o] = x; tPos[o + 1] = y + .012; tPos[o + 2] = z; tPos[o + 3] = x; tPos[o + 4] = y + .132; tPos[o + 5] = z;
    tCol[o] = tCol[o + 3] = r; tCol[o + 1] = tCol[o + 4] = g; tCol[o + 2] = tCol[o + 5] = b;
    tAge[v * 2] = tAge[v * 2 + 1] = age;
  }

  // The derez column: a short scanline pillar where something materialises or leaves, over one bar.
  const column = new THREE.Mesh(new THREE.CylinderGeometry(.16, .16, .7, 18, 1, true).translate(0, .35, 0), new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide,
    uniforms: {uColor: {value: col(hex(TEAL))}, uAmount: {value: 0}, uScan: {value: 0}},
    vertexShader: `varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
    fragmentShader: `uniform vec3 uColor; uniform float uAmount, uScan; varying vec2 vUv;
      void main(){ float lines = step(.55, fract(vUv.y * 38.0 - uScan)); float fade = (1.0 - vUv.y) * (1.0 - vUv.y);
        gl_FragColor = vec4(uColor * uAmount * fade * (.35 + .65 * lines) * .9, 1.0);
        #include <colorspace_fragment>
      }`}));
  column.visible = false; column.frustumCulled = false; scene.add(column);

  // Speed lines and a light chromatic fringe above 4 units/s, Tier 2 and up, never with reduced motion (C7.3).
  // The same pass dims the frame for the fast-travel fade, so that fade is in the canvas the flash gate reads.
  const fringe = new ShaderPass({uniforms: {tDiffuse: {value: null}, uAmount: {value: 0}, uTime: {value: 0}, uAspect: {value: 1}, uVeil: {value: 0}},
    vertexShader: `varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
    fragmentShader: `uniform sampler2D tDiffuse; uniform float uAmount, uTime, uAspect, uVeil; varying vec2 vUv;
      float h1(float n){ return fract(sin(n) * 43758.5453); }
      void main(){
        vec2 c = vUv - .5; float r = length(c * vec2(uAspect, 1.0));
        vec2 off = c * uAmount * .0055 * smoothstep(.2, .8, r);
        vec3 col = vec3(texture2D(tDiffuse, vUv + off).r, texture2D(tDiffuse, vUv).g, texture2D(tDiffuse, vUv - off).b);
        float a = atan(c.y, c.x), lane = floor(a * 46.0), seed = h1(lane * 7.13);
        float streak = step(.7, seed) * smoothstep(.3, .66, r) * pow(fract(r * 1.4 - uTime * (1.2 + seed) + seed * 5.0), 16.0);
        col += vec3(.55, .85, 1.0) * streak * uAmount * .2;
        gl_FragColor = vec4(col * (1.0 - uVeil), 1.0);
      }`});
  composer.insertPass(fringe, composer.passes.length - 1);
  // Compiled by compileWorld at load (enabled for that one render), off from the first frame on.
  requestAnimationFrame(() => { if (!api.active) fringe.enabled = false; });

  // ------------------------------------------------------------------ input (C8.2)
  const canvas = renderer.domElement;
  const keys = Object.create(null);
  const input = {mx: 0, my: 0, lookX: 0, lookY: 0, throttle: 0, brake: 0, steer: 0, fast: false, jumpHeld: false, dance: false, rise: 0};
  let mouseDX = 0, mouseDY = 0, wantJump = false, dragging = false, lastX = 0, lastY = 0, unlockedAt = -1e9;
  const HANDLED = new Set(['Space', 'Tab', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'KeyW', 'KeyA', 'KeyS', 'KeyD', 'KeyQ', 'KeyE', 'KeyV', 'KeyO', 'KeyP', 'KeyR', 'KeyF', 'KeyC', 'Escape']);
  window.addEventListener('keydown', e => {
    const tag = e.target && e.target.tagName;
    if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return;
    if (!api.active) {
      if (e.code === 'KeyF' && !e.repeat && !e.ctrlKey && !e.metaKey && !e.altKey) { e.preventDefault(); enter(); }
      return;
    }
    if (e.code === 'KeyM' || e.ctrlKey || e.metaKey || e.altKey) return;
    keys[e.code] = true; idle = 0;
    if (HANDLED.has(e.code)) e.preventDefault();
    if (e.repeat) return;
    switch (e.code) {
      case 'Escape': escape(); break;
      case 'KeyF': leave(); break;
      case 'KeyP': photo.active ? photo.leave() : photo.enter(); break;
      case 'Tab': if (!photo.active) { hud.toggleMap(); if (hud.mapOpen && document.pointerLockElement) document.exitPointerLock(); } break;
      case 'KeyE': if (!photo.active && !api.tourDriver) toggleBike(); break;
      case 'KeyV': if (!photo.active) view = (view + 1) % 2; break;
      case 'KeyO': if (!photo.active) shuffleOutfit(); break;
      case 'KeyR': if (!photo.active) startTour(); break;
      case 'KeyQ': if (!photo.active && !P.onBike && !onDanceFloor()) hud.toast('Dance on a stage deck'); break;
      case 'Space': if (!photo.active && !P.onBike) wantJump = true; break;
    }
  });
  window.addEventListener('keyup', e => { keys[e.code] = false; });
  window.addEventListener('blur', () => { for (const k in keys) keys[k] = false; });
  document.addEventListener('pointerlockchange', () => { if (!document.pointerLockElement) unlockedAt = performance.now(); });
  function escape() {
    if (document.pointerLockElement) { document.exitPointerLock(); return; }
    // The browser spends the first Esc on releasing a locked pointer; an Esc arriving with that release is not a second one.
    if (performance.now() - unlockedAt < 250) return;
    if (hud.mapOpen) { hud.toggleMap(false); return; }
    if (photo.active) { photo.leave(); return; }
    leave();
  }
  canvas.addEventListener('pointerdown', e => {
    if (!api.active) return;
    if (e.pointerType === 'touch') { enableTouch(true); return; }
    if (e.button !== 0) return;
    if (!document.pointerLockElement && canvas.requestPointerLock) { try { const r = canvas.requestPointerLock(); if (r && r.catch) r.catch(() => {}); } catch (_) {} }
    dragging = true; lastX = e.clientX; lastY = e.clientY;
  });
  window.addEventListener('pointermove', e => {
    if (!api.active || e.pointerType === 'touch') return;
    idle = 0;
    if (document.pointerLockElement === canvas) { mouseDX += e.movementX || 0; mouseDY += e.movementY || 0; }
    else if (dragging && (e.buttons & 1)) { mouseDX += e.clientX - lastX; mouseDY += e.clientY - lastY; lastX = e.clientX; lastY = e.clientY; }
  });
  window.addEventListener('pointerup', () => { dragging = false; });

  // Touch: a left virtual joystick (it appears under the thumb), drag on the right half to look, and buttons.
  const ui = document.createElement('div');
  ui.id = 'ex-touch'; ui.hidden = true;
  ui.innerHTML = '<div id="ex-pad"></div><div id="ex-stick" hidden><i></i></div><div id="ex-buttons">' +
    '<button type="button" data-a="bike">Bike</button><button type="button" data-a="fast">Sprint</button><button type="button" data-a="jump">Jump</button>' +
    '<button type="button" data-a="dance">Dance</button><button type="button" data-a="map">Map</button></div>';
  document.body.appendChild(ui);
  const padEl = ui.querySelector('#ex-pad'), stickEl = ui.querySelector('#ex-stick'), knobEl = stickEl.querySelector('i');
  const touch = {enabled: false, stickId: -1, sx: 0, sy: 0, ax: 0, ay: 0, lookId: -1, lx: 0, ly: 0, fast: false, jump: false, dance: false};
  const STICK = 46;
  padEl.addEventListener('pointerdown', e => {
    e.preventDefault(); idle = 0;
    try { padEl.setPointerCapture(e.pointerId); } catch (_) {}
    if (e.clientX < innerWidth * .5 && touch.stickId < 0) {
      touch.stickId = e.pointerId; touch.sx = e.clientX; touch.sy = e.clientY; touch.ax = touch.ay = 0;
      stickEl.hidden = false; stickEl.style.transform = `translate(${e.clientX}px,${e.clientY}px)`; knobEl.style.transform = '';
    } else if (touch.lookId < 0) { touch.lookId = e.pointerId; touch.lx = e.clientX; touch.ly = e.clientY; }
  });
  padEl.addEventListener('pointermove', e => {
    if (e.pointerId === touch.stickId) {
      let dx = e.clientX - touch.sx, dy = e.clientY - touch.sy; const l = Math.hypot(dx, dy);
      if (l > STICK) { dx *= STICK / l; dy *= STICK / l; }
      touch.ax = dx / STICK; touch.ay = -dy / STICK; knobEl.style.transform = `translate(${dx}px,${dy}px)`;
    } else if (e.pointerId === touch.lookId) { mouseDX += (e.clientX - touch.lx) * 1.5; mouseDY += (e.clientY - touch.ly) * 1.5; touch.lx = e.clientX; touch.ly = e.clientY; }
  });
  const touchEnd = e => {
    if (e.pointerId === touch.stickId) { touch.stickId = -1; touch.ax = touch.ay = 0; stickEl.hidden = true; }
    if (e.pointerId === touch.lookId) touch.lookId = -1;
  };
  padEl.addEventListener('pointerup', touchEnd); padEl.addEventListener('pointercancel', touchEnd);
  for (const b of ui.querySelectorAll('#ex-buttons button')) {
    const a = b.dataset.a;
    b.addEventListener('pointerdown', e => {
      e.preventDefault(); e.stopPropagation(); idle = 0;
      if (a === 'bike') toggleBike(); else if (a === 'map') hud.toggleMap();
      else if (a === 'jump') { touch.jump = true; if (!P.onBike) wantJump = true; }
      else touch[a] = true;
      b.classList.add('on');
    });
    const up = () => { if (a === 'jump' || a === 'fast' || a === 'dance') touch[a] = false; b.classList.remove('on'); };
    b.addEventListener('pointerup', up); b.addEventListener('pointercancel', up); b.addEventListener('pointerleave', up);
  }
  function enableTouch(on) {
    touch.enabled = on; ui.hidden = !(on && api.active);
    document.body.classList.toggle('ex-touching', on);
  }
  const touchPreferred = () => phone || (window.matchMedia && matchMedia('(pointer: coarse)').matches);

  // Gamepad (standard mapping): left stick move, right stick look, RT throttle, LT brake, A jump or slide,
  // X bike, Y dance, B leave; RB sprint or boost, Back map, Start photo.
  const padIn = {mx: 0, my: 0, lx: 0, ly: 0, rt: 0, lt: 0, a: false, y: false, rb: false, active: false};
  const padPrev = new Uint8Array(17);
  const dead = v => Math.abs(v) < .15 ? 0 : (v - Math.sign(v) * .15) / .85;
  const button = (g, i) => { const b = g.buttons[i]; return !b ? 0 : typeof b === 'object' ? (b.value || (b.pressed ? 1 : 0)) : +b; };
  // navigator.getGamepads() returns a new list on every call, so it is polled only while a pad is connected:
  // the browser announces a pad (after its first button press) and its removal with these two events.
  let padsPresent = false;
  function padCheck() {
    padsPresent = false; padPrev.fill(0);
    const list = navigator.getGamepads ? navigator.getGamepads() : null;
    for (let i = 0; list && i < list.length; i++) if (list[i] && list[i].connected !== false) padsPresent = true;
  }
  window.addEventListener('gamepadconnected', () => { padsPresent = true; });
  window.addEventListener('gamepaddisconnected', padCheck);
  function pollPad() {
    padIn.active = false; padIn.mx = padIn.my = padIn.lx = padIn.ly = padIn.rt = padIn.lt = 0; padIn.a = padIn.y = padIn.rb = false;
    if (!padsPresent || !navigator.getGamepads) return;
    const list = navigator.getGamepads();
    for (let i = 0; list && i < list.length; i++) {
      const g = list[i];
      if (!g || g.connected === false || g.mapping !== 'standard') continue;
      padIn.active = true;
      padIn.mx = dead(g.axes[0] || 0); padIn.my = -dead(g.axes[1] || 0); padIn.lx = dead(g.axes[2] || 0); padIn.ly = dead(g.axes[3] || 0);
      padIn.rt = button(g, 7); padIn.lt = button(g, 6); padIn.a = button(g, 0) > .5; padIn.y = button(g, 3) > .5; padIn.rb = button(g, 5) > .5;
      for (let b = 0; b < 17; b++) {
        const now = button(g, b) > .5 ? 1 : 0;
        if (now && !padPrev[b]) {
          idle = 0;
          if (b === 0 && !P.onBike && !photo.active) wantJump = true;
          else if (b === 1) escape();
          else if (b === 2 && !photo.active) toggleBike();
          else if (b === 8 && !photo.active) hud.toggleMap();
          else if (b === 9) photo.active ? photo.leave() : photo.enter();
        }
        padPrev[b] = now;
      }
      break;
    }
  }
  function gather(dt) {
    const k = keys;
    const mx = (k.KeyD || k.ArrowRight ? 1 : 0) - (k.KeyA || k.ArrowLeft ? 1 : 0) + touch.ax + padIn.mx;
    const my = (k.KeyW || k.ArrowUp ? 1 : 0) - (k.KeyS || k.ArrowDown ? 1 : 0) + touch.ay + padIn.my;
    input.mx = clamp(mx, -1, 1); input.my = clamp(my, -1, 1);
    input.fast = !!(k.ShiftLeft || k.ShiftRight || touch.fast || padIn.rb);
    input.jumpHeld = !!(k.Space || touch.jump || padIn.a);
    input.dance = !!(k.KeyQ || touch.dance || padIn.y);
    input.rise = (k.Space ? 1 : 0) - (k.KeyC || k.ControlLeft ? 1 : 0);
    input.throttle = Math.max(input.my > 0 ? input.my : 0, padIn.rt); input.brake = Math.max(input.my < 0 ? -input.my : 0, padIn.lt); input.steer = input.mx;
    input.lookX = mouseDX * .0026 + padIn.lx * 2.4 * dt; input.lookY = mouseDY * .0026 + padIn.ly * 1.8 * dt;
    mouseDX = mouseDY = 0;
    // QA scripts and the V5 tour drive the same controls through this hook.
    if (api.pilot) api.pilot(input, dt, api);
  }

  // ------------------------------------------------------------------ movement (C8.3)
  const onDanceFloor = () => { probe(P.x, P.z, P.y); return hit.kind === K.stage; };
  function danceStyleHere() { probe(P.x, P.z, P.y); return hit.kind === K.stage ? crowd.styleByRoom[decks[hit.owner].d] || 'bounce' : null; }
  let camYaw = 0, camPitch = -.12, view = 0, idle = 0;
  function updateFoot(dt) {
    const fx = Math.sin(camYaw), fz = Math.cos(camYaw), rx = -fz, rz = fx;
    let wx = fx * input.my + rx * input.mx, wz = fz * input.my + rz * input.mx;
    const wl = Math.hypot(wx, wz);
    if (wl > 1) { wx /= wl; wz /= wl; }
    const style = input.dance ? danceStyleHere() : null;
    P.dancing = !!style && wl < .1; if (style) P.danceStyle = style;
    const top = input.fast ? FOOT.sprint : FOOT.walk, k = damp(P.grounded ? 12 : 3, dt);
    P.vx += (wx * top - P.vx) * k; P.vz += (wz * top - P.vz) * k;
    if (wantJump && P.grounded && !P.dancing) { P.vy = FOOT.jump; P.grounded = false; }
    wantJump = false;
    const dist = Math.hypot(P.vx, P.vz) * dt, n = Math.max(1, Math.ceil(dist / .05));
    for (let i = 0; i < n; i++) {
      if (!advance(P.vx * dt / n, P.vz * dt / n, P.y, FOOT.radius, FOOT.stepUp, FOOT.stepDown, P.grounded, FOOT.radius)) { P.vx *= .5; P.vz *= .5; break; }
      P.x = step.x; P.z = step.z;
      if (P.grounded) P.y = step.h;
    }
    if (!P.grounded) {
      P.vy -= GRAVITY * dt; P.y += P.vy * dt;
      const ground = surfaceAt(P.x, P.z, P.y + FOOT.stepUp);
      if (ground !== null && P.y <= ground) { P.y = ground; P.vy = 0; P.grounded = true; }
      else if (ground === null && P.vy < 0) { P.vy = 0; P.grounded = true; P.y = surfaceAt(P.x, P.z, P.y) ?? P.y; }
    }
    P.speed = Math.hypot(P.vx, P.vz);
    if (view === 1) P.yaw = camYaw;
    else if (P.speed > .05) P.yaw += wrapAngle(Math.atan2(P.vx, P.vz) - P.yaw) * damp(12, dt);
    P.stride += P.speed * dt / .16;
  }
  function updateBike(dt) {
    const b = bike;
    if (input.fast && b.charge >= 1 && !b.boosting && b.speed > .5) b.boosting = true;
    if (b.boosting) { b.charge -= dt / BIKE.boostTime; if (!input.fast || b.charge <= 0) { b.boosting = false; b.charge = Math.max(0, b.charge); } }
    else b.charge = Math.min(1, b.charge + dt / BIKE.recharge);
    b.slide = input.jumpHeld && Math.abs(b.speed) > .6;
    const top = b.boosting ? BIKE.boost : BIKE.top, want = top * input.throttle;
    if (input.throttle > 0 && b.speed < want) b.speed = Math.min(want, b.speed + (b.boosting ? BIKE.boostAccel : BIKE.accel) * dt);
    else if (b.speed > top) b.speed = Math.max(top, b.speed - 2 * dt);
    if (input.brake > 0) b.speed = b.speed > 0 ? Math.max(0, b.speed - BIKE.brake * input.brake * dt) : Math.max(-BIKE.reverse, b.speed - 1.5 * input.brake * dt);
    if (input.throttle <= 0 && input.brake <= 0) b.speed -= Math.sign(b.speed) * Math.min(Math.abs(b.speed), BIKE.drag * dt);
    if (b.slide) b.speed -= Math.sign(b.speed) * Math.min(Math.abs(b.speed), 1.1 * dt);
    const v = Math.abs(b.speed), turn = clamp(v / 1.2, 0, 1) * 2.1 / (1 + .08 * v) * (b.slide ? 1.7 : 1);
    b.yawRate = -input.steer * turn * (b.speed < 0 ? -1 : 1);
    b.heading = wrapAngle(b.heading + b.yawRate * dt);
    b.vAngle += wrapAngle(b.heading - b.vAngle) * damp(b.slide ? 1.8 : 10, dt);
    const dx = Math.sin(b.vAngle) * b.speed * dt, dz = Math.cos(b.vAngle) * b.speed * dt, dist = Math.hypot(dx, dz), n = Math.max(1, Math.ceil(dist / .06));
    let moved = 0;
    for (let i = 0; i < n; i++) {
      if (!advance(dx / n, dz / n, P.y, BIKE.radius, BIKE.stepUp, BIKE.stepDown, true, BIKE.nose)) { b.speed *= .5; break; }
      if (step.frac < 1) {
        // Sliding along a wall or a rail: keep the part of the speed along it and turn the bike with it.
        b.speed *= .5 + .5 * step.frac;
        const ax = step.x - P.x, az = step.z - P.z;
        if (ax * ax + az * az > 1e-10) { const along = Math.atan2(ax, az) + (b.speed < 0 ? Math.PI : 0); b.heading += wrapAngle(along - b.heading) * .35; b.vAngle = b.heading; }
      }
      moved += Math.hypot(step.x - P.x, step.z - P.z);
      P.x = step.x; P.z = step.z; P.y = step.h;
    }
    const lean = clamp(Math.atan(v * b.yawRate / GRAVITY), -BIKE.maxLean, BIKE.maxLean);
    b.lean += (lean - b.lean) * damp(7, dt);
    const wb = BIKE.base * BIKE.scale / 2, hf = surfaceAt(P.x + Math.sin(b.heading) * wb, P.z + Math.cos(b.heading) * wb, P.y);
    const hr = surfaceAt(P.x - Math.sin(b.heading) * wb, P.z - Math.cos(b.heading) * wb, P.y);
    const pitch = hf !== null && hr !== null ? -Math.atan((hf - hr) / (2 * wb)) : 0;
    b.pitch += (pitch - b.pitch) * damp(12, dt);
    b.spin = (b.spin + moved / (TAU * BIKE.wheel * BIKE.scale)) % 1000;
    b.x = P.x; b.y = P.y; b.z = P.z; P.yaw = b.heading; P.speed = v; P.vx = dx / Math.max(dt, 1e-6); P.vz = dz / Math.max(dt, 1e-6);
  }
  function toggleBike() {
    if (!api.active || travel.active || api.tourDriver) return;
    if (P.onBike) {
      P.onBike = false; bike.derezDir = -1; bike.boosting = false; P.vx = P.vz = 0;
      // Step off to the right if there is ground there.
      const rx = -Math.cos(P.yaw) * .18, rz = Math.sin(P.yaw) * .18, h = surfaceAt(P.x + rx, P.z + rz, P.y);
      if (h !== null && Math.abs(h - P.y) < FOOT.stepUp && !insideFootprint(P.x + rx, P.z + rz, h, FOOT.radius)) { P.x += rx; P.z += rz; P.y = h; }
      crowd.dressAvatar(outfit);
      columnAt(bike.x, bike.y, bike.z);
    } else {
      P.onBike = true; P.dancing = false;
      Object.assign(bike, {present: true, heading: P.yaw, vAngle: P.yaw, speed: 0, yawRate: 0, lean: 0, pitch: 0, charge: 1, boosting: false, derez: 0, derezDir: 1, x: P.x, y: P.y, z: P.z});
      trailReset(); crowd.dressAvatar(riderOf(outfit)); columnAt(P.x, P.y, P.z);
    }
    touchLabels();
  }
  function touchLabels() {
    ui.querySelector('[data-a="fast"]').textContent = P.onBike ? 'Boost' : 'Sprint';
    ui.querySelector('[data-a="jump"]').textContent = P.onBike ? 'Slide' : 'Jump';
  }
  let columnT = -1;
  function columnAt(x, y, z) { column.position.set(x, y, z); column.updateMatrix(); columnT = 0; column.visible = true; }

  // Fast travel from the minimap: derez out for half a bar, move, rez in for half a bar (C8.7).
  const travel = {active: false, t: 0, stage: -1, moved: false, count: 0, veil: false, dim: 0};
  function fastTravel(i) {
    if (!api.active || travel.active || photo.active || !stages[i]) return false;
    // The screen dims and returns once over the bar: a large-area change, so it asks the rave-light limiter
    // for a flash slot and is skipped in Calm, with reduced motion or when the budget is spent (C12.1).
    Object.assign(travel, {active: true, t: 0, stage: i, moved: false, veil: lights.requestFlash()}); columnAt(P.x, P.y, P.z);
    return true;
  }
  function updateTravel(dt) {
    if (!travel.active) { look.shrink = Math.min(1, look.shrink + dt * 4); travel.dim = 0; return; }
    travel.t += dt / BAR;
    const t = travel.t;
    look.shrink = t < .5 ? 1 - t * 2 : Math.min(1, (t - .5) * 2);
    travel.dim = travel.veil ? Math.sin(Math.min(1, t) * Math.PI) * .7 : 0;
    if (t >= .5 && !travel.moved) { travel.moved = true; spawnAt(stages[travel.stage].district, travel.stage); columnAt(P.x, P.y, P.z); trailReset(); }
    if (t >= 1) { travel.active = false; travel.count++; look.shrink = 1; travel.dim = 0; }
  }
  // Explore starts on foot at a stage: on the crowd's side of the deck, facing the booth (C8.1).
  function spawnAt(district, stageIndex) {
    const s = stageIndex !== undefined ? stages[stageIndex] : stages.find(t => t.district === district) || stages.find(t => t.district === 'core') || stages[0];
    let x = s.center.x - s.facing.x * s.r * .55, z = s.center.z - s.facing.z * s.r * .55, y = surfaceAt(x, z, s.z);
    for (let k = 0; y === null && k < 10; k++) { x = s.center.x - s.facing.x * s.r * (.55 - k * .1); z = s.center.z - s.facing.z * s.r * (.55 - k * .1); y = surfaceAt(x, z, s.z); }
    P.x = x; P.z = z; P.y = y ?? s.z; P.vx = P.vz = P.vy = 0; P.grounded = true;
    P.yaw = Math.atan2(s.facing.x, s.facing.z); camYaw = P.yaw; camPitch = -.12;
    if (P.onBike) { Object.assign(bike, {heading: P.yaw, vAngle: P.yaw, speed: 0, x: P.x, y: P.y, z: P.z}); }
    chaseYaw = P.yaw; camDist = 1; room.candidate = null; room.held = 0; safeEye.set(P.x, P.y + .45, P.z);
  }

  // ------------------------------------------------------------------ cameras (C8.5, C7.3)
  const eye = new V3(), target = new V3(), pivot = new V3(), want = new V3(), safeEye = new V3(), probeEye = new V3();
  let chaseYaw = 0, lookOffset = 0, lookIdle = 0, camDist = 1, fov = 64;
  function pullIn(from, to, out) {
    let t = 1;
    for (; t > .12; t -= .11) { out.lerpVectors(from, to, t); if (clearSight(from, out) && !pointBlocked(out, .1)) break; }
    return Math.max(t, .12);
  }
  function updateCamera(dt) {
    const b = bike;
    if (P.onBike && view === 0) {
      lookOffset = clamp(lookOffset - input.lookX, -2.6, 2.6); camPitch = clamp(camPitch - input.lookY, -.5, .45);
      if (input.lookX) lookIdle = 0; else if ((lookIdle += dt) > 1) lookOffset *= 1 - damp(3, dt);
    } else { camYaw -= input.lookX; camPitch = clamp(camPitch - input.lookY, -1.2, 1.0); }
    if (view === 1) {
      const yaw = P.onBike ? b.heading + lookOffset : camYaw, cp = Math.cos(camPitch);
      eye.set(P.x + Math.sin(yaw) * .03, P.y + (P.onBike ? .23 : .36), P.z + Math.cos(yaw) * .03);
      target.set(eye.x + Math.sin(yaw) * cp, eye.y + Math.sin(camPitch), eye.z + Math.cos(yaw) * cp);
    } else if (P.onBike) {
      chaseYaw += wrapAngle(b.heading - chaseYaw) * damp(6, dt);
      const yaw = chaseYaw + lookOffset, fx = Math.sin(yaw), fz = Math.cos(yaw);
      pivot.set(P.x, P.y + .2, P.z);
      want.set(P.x - fx * .75, P.y + .32 + camPitch * .4, P.z - fz * .75);
      target.set(P.x + fx * 2.2, P.y + .12 + camPitch * .8, P.z + fz * 2.2);
    } else {
      // Over the shoulder, 0.9 behind and 0.45 up; a portrait screen sits a little further back to see around you.
      const cp = Math.cos(camPitch), fx = Math.sin(camYaw) * cp, fy = Math.sin(camPitch), fz = Math.cos(camYaw) * cp, back = camera.aspect < 1 ? 1.25 : .9;
      pivot.set(P.x - Math.cos(camYaw) * .1, P.y + .3, P.z + Math.sin(camYaw) * .1);
      want.set(pivot.x - fx * back, pivot.y + .15 - fy * back, pivot.z - fz * back);
      target.set(pivot.x + fx * 2, pivot.y + fy * 2, pivot.z + fz * 2);
    }
    if (view === 0) {
      // Pull in at once when the line of sight breaks, ease back out slowly.
      const t = pullIn(pivot, want, probeEye);
      camDist = t < camDist ? t : camDist + (t - camDist) * damp(2.5, dt);
      eye.lerpVectors(pivot, want, camDist);
      // The eye never goes under the ground: looking up from behind would put it below the slab or the deck.
      // It stays 0.1 above your feet and above the surface under it nearest your level (on an overpass the
      // deck, under one the road), whichever is higher.
      if (!debug.noCamFloor) {
        const g = surfaceAt(eye.x, eye.z, P.y + .3), floor = (g !== null && g > P.y ? g : P.y) + (P.onBike ? .32 : .1);
        if (eye.y < floor) eye.y = floor;
      }
    }
    // The camera never enters a footprint (C8.5 gate): hold the last safe eye instead.
    if (pointBlocked(eye, .06)) eye.copy(safeEye); else safeEye.copy(eye);
    camera.position.copy(eye); camera.lookAt(target);
    if (view === 1 && P.onBike && !reduced) camera.rotateZ(-b.lean * .35);
    const top = P.onBike && !reduced ? 64 + 14 * clamp((Math.abs(b.speed) - BIKE.cruise) / (BIKE.boost - BIKE.cruise), 0, 1) : 64;
    fov += (top - fov) * (dt > 0 ? damp(4, dt) : 1);
    if (Math.abs(camera.fov - fov) > .01) { camera.fov = fov; camera.updateProjectionMatrix(); }
    av.hidden = view === 1 || !api.active;
  }

  // ------------------------------------------------------------------ music follows position (C8.6)
  const room = {candidate: null, held: 0, last: {district: null, kind: 0, bridge: -1, s: 0, time: 0, x: 0, z: 0}, changes: 0};
  function followMusic(dt) {
    zoneAt(P.x, P.z, P.y);
    const d = zone.depth >= .8 ? zone.district : null;
    if (d !== room.candidate) { room.candidate = d; room.held = 0; return; }
    if (!d) return;
    room.held += dt;
    if (room.held >= .5 && cityAudio.desired !== d) {
      cityAudio.setRoom(d); room.changes++;
      probe(P.x, P.z, P.y);
      const L = room.last; L.district = d; L.kind = hit.kind; L.bridge = hit.kind === K.bridge ? hit.owner : -1; L.s = hit.s; L.time = performance.now(); L.x = P.x; L.z = P.z;
    }
  }

  // ------------------------------------------------------------------ the avatar's pose this frame
  function updatePose(dt, now) {
    const b = beat.now(), t = b.totalBeats;
    look.x = P.x; look.y = P.y; look.z = P.z; look.yaw = P.yaw; look.roll = 0; look.pitch = 0; look.lift = 0;
    if (P.onBike) {
      crowd.stillPose('stand', 0, pose);
      // The rider leans along the shell: the body pitches forward from the rear pegs, legs straight back,
      // arms reaching to the cowl, head up to see the road. The chase camera then sees over the rider.
      pose.lA = pose.lB = .12; pose.aA = pose.aB = -2.55; pose.bA = .18; pose.bB = -.18; pose.lean = -.05; pose.nod = -1.05;
      look.roll = -bike.lean; look.pitch = bike.pitch + 1.2; look.lift = .105;
      look.x -= Math.sin(P.yaw) * .21; look.z -= Math.cos(P.yaw) * .21;
      if (bike.slide) pose.twist = clamp(-bike.yawRate * .08, -.3, .3);
    } else if (P.dancing) crowd.stylePose(P.danceStyle, t, 1, .37, pose);
    else if (P.speed > .06) {
      crowd.walkPose(P.stride, false, pose);
      const k = clamp(P.speed / FOOT.walk, .4, 1.8);
      pose.aA *= k; pose.aB *= k; pose.lA *= Math.min(k, 1.3); pose.lB *= Math.min(k, 1.3); pose.lean = .02 + .06 * (k - 1);
    } else crowd.stillPose('stand', reduced ? 0 : t, pose);
    if (!P.grounded) { pose.aA = -2.2; pose.aB = -2.2; pose.bA = -.4; pose.bB = .4; pose.lA = -.5; pose.lB = .2; }
  }
  av.writer = writeAvatar;

  // ------------------------------------------------------------------ bike mesh and effects this frame
  const eBike = new THREE.Euler(0, 0, 0, 'YXZ');
  function updateBikeMesh(dt) {
    const b = bike;
    if (b.derezDir) {
      b.derez = clamp(b.derez + b.derezDir * dt / BAR, 0, 1);
      if (b.derez >= 1 && b.derezDir > 0) b.derezDir = 0;
      if (b.derez <= 0 && b.derezDir < 0) { b.derezDir = 0; b.present = false; }
    }
    bikeBody.visible = bikeGlow.visible = b.present;
    if (!b.present) return;
    bikeUniforms.uDerez.value = b.derez; bikeUniforms.uSpin.value = b.spin * 6 % 1;
    bikeDummy.position.set(b.x, b.y, b.z); eBike.set(b.pitch, b.heading, -b.lean); bikeDummy.rotation.copy(eBike); bikeDummy.scale.setScalar(BIKE.scale); bikeDummy.updateMatrix();
    bikeBody.setMatrixAt(0, bikeDummy.matrix); bikeGlow.setMatrixAt(0, bikeDummy.matrix);
    bikeBody.instanceMatrix.needsUpdate = bikeGlow.instanceMatrix.needsUpdate = true;
  }
  function updateColumn(dt) {
    if (columnT < 0) return;
    columnT += dt / BAR;
    const t = columnT;
    column.material.uniforms.uAmount.value = (t < .5 ? t * 2 : Math.max(0, 2 - t * 2)) * (reduced ? .5 : 1);
    column.material.uniforms.uScan.value = reduced ? 0 : t * 6;
    column.scale.set(1, .4 + .6 * Math.min(1, t * 2), 1); column.updateMatrix();
    if (t >= 1) { columnT = -1; column.visible = false; }
  }

  // ------------------------------------------------------------------ photo mode (C8.8)
  const photoBar = document.createElement('div');
  photoBar.id = 'ex-photo'; photoBar.className = 'glass'; photoBar.hidden = true;
  photoBar.innerHTML = '<span>Photo · WASD fly · Space and C up and down · Shift fast</span><button class="btn" type="button" id="ex-save">Save image</button><button class="btn" type="button" id="ex-photo-leave">Back</button>';
  document.body.appendChild(photoBar);
  const flyDir = new V3();
  const photo = {
    active: false, yaw: 0, pitch: 0, saved: 0,
    enter() {
      if (!api.active) enter(null);
      if (photo.active) return;
      // The shot starts from the over-the-shoulder view with you in it, also from #photo or first person.
      if (!debug.photoAsIs) {
        const was = view; view = 0; input.lookX = input.lookY = 0; updateCamera(0); view = was;
        updatePose(0, 0); crowd.showAvatar(true);
      }
      photo.active = true; api.frozen = true; document.body.classList.add('photo'); photoBar.hidden = false; photoBar.classList.remove('idle');
      camera.getWorldDirection(flyDir); photo.yaw = Math.atan2(flyDir.x, flyDir.z); photo.pitch = Math.asin(clamp(flyDir.y, -1, 1));
      hud.toggleMap(false); enableTouch(touch.enabled); fringe.enabled = false; idle = 0; camera.up.set(0, 1, 0);
    },
    leave() {
      if (!photo.active) return;
      photo.active = false; api.frozen = false; document.body.classList.remove('photo'); photoBar.hidden = true; enableTouch(touch.enabled);
      if (/^#photo/.test(location.hash)) history.replaceState(null, '', location.pathname + location.search);
    },
    update(dt) {
      photo.yaw -= input.lookX; photo.pitch = clamp(photo.pitch - input.lookY, -1.45, 1.45);
      const cp = Math.cos(photo.pitch), fx = Math.sin(photo.yaw) * cp, fy = Math.sin(photo.pitch), fz = Math.cos(photo.yaw) * cp;
      const rx = -Math.cos(photo.yaw), rz = Math.sin(photo.yaw), speed = (input.fast ? 3.6 : 1.2) * dt;
      const dx = (fx * input.my + rx * input.mx) * speed, dy = (fy * input.my + input.rise) * speed, dz = (fz * input.my + rz * input.mx) * speed;
      // The fly camera never enters a footprint: each axis moves only if the result is clear.
      probeEye.copy(camera.position);
      probeEye.x += dx; if (pointBlocked(probeEye, .08)) probeEye.x -= dx;
      probeEye.y += dy; if (pointBlocked(probeEye, .08)) probeEye.y -= dy;
      probeEye.z += dz; if (pointBlocked(probeEye, .08)) probeEye.z -= dz;
      const ground = surfaceAt(probeEye.x, probeEye.z, probeEye.y);
      probeEye.y = Math.min(140, Math.max(probeEye.y, (ground ?? 0) + .06));
      camera.position.copy(probeEye); target.set(probeEye.x + fx, probeEye.y + fy, probeEye.z + fz); camera.lookAt(target);
      idle += dt; if (photoBar.classList.contains('idle') !== idle > 2.5) photoBar.classList.toggle('idle', idle > 2.5);
    },
    // A PNG of the canvas at twice the CSS size, rendered once for the shot.
    capture(scale = 2) {
      const ratio = renderer.getPixelRatio(), [w, h] = stageSize();
      renderer.setPixelRatio(scale); composer.setPixelRatio(scale); renderer.setSize(w, h); composer.setSize(w, h);
      if (bloomOn) composer.render(); else renderer.render(scene, camera);
      const done = new Promise(resolve => canvas.toBlob(resolve, 'image/png'));
      const size = {width: canvas.width, height: canvas.height};
      renderer.setPixelRatio(ratio); composer.setPixelRatio(ratio); renderer.setSize(w, h); composer.setSize(w, h); bloomSize(); resize();
      return done.then(blob => ({blob, ...size}));
    },
    save() {
      return photo.capture(2).then(({blob, width, height}) => {
        if (!blob) return null;
        const a = document.createElement('a'), url = URL.createObjectURL(blob);
        a.href = url; a.download = 'vault-city.png'; document.body.appendChild(a); a.click(); a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 4000); photo.saved++;
        return {width, height, bytes: blob.size};
      });
    },
  };
  photoBar.querySelector('#ex-save').addEventListener('click', () => photo.save());
  photoBar.querySelector('#ex-photo-leave').addEventListener('click', () => photo.leave());
  photoBar.addEventListener('pointermove', () => { idle = 0; });

  // ------------------------------------------------------------------ enter, leave, tour hook, deep links
  const saved = {position: new V3(), target: new V3(), fov: 39, autoRotate: false};
  const buttonEl = document.getElementById('explore');
  let firstEntry = true, peopleWere = true;
  function enter(district) {
    if (api.active) return;
    if (state.ride >= 0) stopRide();
    const d = district || state.isolate || 'core';
    if (state.isolate !== null) setIsolate(null);
    select(-1); setHover(-1); focusGoal = null;
    // A playing timeline stops, and its button says so, as the slider does when it is dragged.
    if (state.playing) { state.playing = false; $('play').textContent = state.t >= LAST - 1e-3 ? 'Replay' : 'Play'; }
    saved.position.copy(camera.position); saved.target.copy(controls.target); saved.fov = camera.fov; saved.autoRotate = controls.autoRotate;
    controls.enabled = false; controls.autoRotate = false;
    api.active = true; state.explore = true; visitorMoved = true; peopleWere = peopleGroup.visible; peopleGroup.visible = true;
    P.onBike = false; bike.present = false; bike.derezDir = 0; trailReset(); outfit = outfitIndex ? outfit : baseOutfit; crowd.dressAvatar(outfit);
    view = 0; spawnAt(d); fov = camera.fov; padCheck();
    cityAudio.setRoom(d);
    document.body.classList.add('exploring');
    if (buttonEl) { buttonEl.classList.add('on'); buttonEl.textContent = 'Leave explore'; buttonEl.setAttribute('aria-pressed', 'true'); }
    const touchMode = touchPreferred();
    enableTouch(touchMode); hud.show(firstEntry, touchMode); firstEntry = false;
    if (document.activeElement && document.activeElement.blur) document.activeElement.blur();
  }
  // `reentering` is set when a new #explore link moves you: the hash that asked for it stays in the address.
  function leave(reentering) {
    if (!api.active) return;
    if (api.tourDriver) { api.tourExit(); return; }
    photo.leave();
    if (document.pointerLockElement) document.exitPointerLock();
    travel.active = false; travel.dim = 0; look.shrink = 1; columnT = -1; column.visible = false;
    P.onBike = false; bike.present = false; bike.derezDir = 0; bikeBody.visible = bikeGlow.visible = false; trailReset();
    av.hidden = true; crowd.notice.active = false; fringe.enabled = false;
    api.active = false; state.explore = false; peopleGroup.visible = peopleWere;
    controls.enabled = true; controls.autoRotate = saved.autoRotate;
    camera.up.set(0, 1, 0); camera.position.copy(saved.position); controls.target.copy(saved.target); camera.fov = saved.fov; camera.updateProjectionMatrix(); controls.update();
    cityAudio.setRoom('skyline');
    document.body.classList.remove('exploring');
    if (buttonEl) { buttonEl.classList.remove('on'); buttonEl.textContent = 'Explore'; buttonEl.setAttribute('aria-pressed', 'false'); }
    enableTouch(false); hud.hide();
    if (!reentering && /^#(explore|photo)/.test(location.hash)) history.replaceState(null, '', location.pathname + location.search);
  }
  if (buttonEl) buttonEl.addEventListener('click', () => api.active ? leave() : enter());
  // R starts the tour from here. V5 sets api.tourHook(from) to start the Grand Tour at this spot; until then
  // R leaves explore and rides along the circuit of the district you stand in.
  function startTour() {
    const from = {x: P.x, y: P.y, z: P.z, yaw: P.yaw, onBike: P.onBike, district: zoneAt(P.x, P.z, P.y).district || 'core'};
    if (api.tourHook) { api.tourHook(from); return; }
    leave(); setIsolate(from.district); startRide();
  }
  // Deep links (C8.9): #explore/<district-slug>, #ride, #ride/<district-slug>, #photo. Nothing else is read or written.
  const slug = name => name.toLowerCase().replace(/^the /, '').replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
  const SLUGS = Object.fromEntries(Object.keys(DATA.plateaus).map(d => [slug(styleOf(d).name), d]));
  function openHash(hash) {
    const m = /^#(explore|ride|photo)(?:\/([a-z0-9-]+))?$/.exec(hash || '');
    if (!m) return false;
    const d = m[2] ? SLUGS[m[2]] : null;
    if ((m[2] && !d) || (m[1] === 'photo' && m[2])) return false;
    if (m[1] === 'explore') { if (api.active) leave(true); enter(d); }
    else if (m[1] === 'photo') { if (!api.active) enter(null); photo.enter(); }
    else { if (api.active) leave(); if (state.ride >= 0) stopRide(); if (d) setIsolate(d); startRide(); }
    return true;
  }
  window.addEventListener('hashchange', () => openHash(location.hash));

  // ------------------------------------------------------------------ the frame (called before the crowd)
  const snapshot = {x: 0, y: 0, z: 0, yaw: 0, onBike: false, speed: 0, charge: 1, boosting: false, view: 0, dancing: false, grounded: true};
  function update(dt, now) {
    pollPad(); gather(dt);
    if (photo.active) { photo.update(dt); return; }
    updateTravel(dt);
    if (api.tourDriver) api.tourDriver(dt, api);
    else if (!travel.active || travel.t < .5 || travel.t > .55) { if (P.onBike) updateBike(dt); else updateFoot(dt); }
    // Never inside a footprint, even when the timeline or a teleport would put us there.
    if (!debug.noCollide && insideFootprint(P.x, P.z, P.y, 0)) { at.x = P.x; at.z = P.z; pushOut(P.y, FOOT.radius); P.x = at.x; P.z = at.z; }
    updatePose(dt, now);
    updateBikeMesh(dt); trailUpdate(dt, P.onBike && bike.present); updateColumn(dt);
    updateCamera(dt);
    if (!api.tourDriver) followMusic(dt);
    // The world notices you (C8.10): crowd.js turns heads and cheers from this; nature.js (V7) reads the same
    // object as explore.notice for dogs that follow the bike for up to 2 s and pigeons that scatter within 1.5.
    const n = crowd.notice; n.active = true; n.x = P.x; n.z = P.z; n.speed = P.onBike ? Math.abs(bike.speed) : P.speed; n.onBike = P.onBike;
    nature.mover(0, P.x, P.y, P.z, P.onBike);
    const amount = !reduced && tier.current >= 2 && P.onBike ? clamp((Math.abs(bike.speed) - 4) / 3, 0, 1) : 0;
    const dim = debug.forceVeil !== null ? debug.forceVeil : travel.dim;
    fringe.enabled = amount > .001 || dim > .001;
    if (fringe.enabled) { fringe.uniforms.uAmount.value = amount; fringe.uniforms.uTime.value = now; fringe.uniforms.uAspect.value = camera.aspect; fringe.uniforms.uVeil.value = dim; }
    hud.update(dt, api.position);
  }

  // ------------------------------------------------------------------ explore UI styles
  const style = document.createElement('style');
  style.textContent = `
  body.exploring .mark, body.exploring .chips, body.exploring .city-help, body.exploring .city-meta, body.exploring #labels, body.exploring #ride-badge, body.exploring #tip { display:none !important; }
  body.exploring .bar { top:calc(16px + env(safe-area-inset-top,0px)); bottom:auto; left:auto; right:16px; transform:none; width:auto; padding:7px; gap:7px; z-index:7; }
  body.exploring .bar .scrub, body.exploring .bar #play, body.exploring .bar #ride, body.exploring .bar .menu { display:none; }
  body.exploring.riding .bar #ride { display:inline-flex; }
  body.exploring.riding #ride-badge { display:flex !important; }
  body.photo > :not(#stage):not(#ex-photo):not(#ex-touch):not(script):not(style) { display:none !important; }
  body.photo #ex-buttons { display:none; }
  #ex-photo { position:fixed; left:50%; bottom:calc(20px + env(safe-area-inset-bottom,0px)); transform:translateX(-50%); display:flex; gap:10px; align-items:center; padding:8px 10px 8px 14px;
    font-size:9px; letter-spacing:.1em; text-transform:uppercase; color:var(--dim); transition:opacity .4s; z-index:7; }
  #ex-photo.idle { opacity:0; pointer-events:none; }
  #ex-touch { position:fixed; inset:0; z-index:3; pointer-events:none; }
  #ex-pad { position:absolute; inset:0; pointer-events:auto; touch-action:none; }
  #ex-stick { position:absolute; left:-52px; top:-52px; width:104px; height:104px; border-radius:50%; border:1px solid #6be7e155; background:#07121b66; pointer-events:none; }
  #ex-stick i { position:absolute; left:34px; top:34px; width:36px; height:36px; border-radius:50%; background:#6be7e1aa; box-shadow:0 0 14px #6be7e166; }
  #ex-buttons { position:absolute; right:16px; bottom:calc(20px + env(safe-area-inset-bottom,0px)); display:grid; grid-template-columns:repeat(2,64px); gap:10px; pointer-events:auto; }
  #ex-buttons button { height:52px; border-radius:26px; border:1px solid #6be7e155; background:#07121bcc; color:var(--text); font:500 9px var(--mono); letter-spacing:.1em;
    text-transform:uppercase; touch-action:none; -webkit-user-select:none; user-select:none; }
  #ex-buttons button.on { background:var(--signal); color:var(--night); }
  #ex-buttons button[data-a="map"] { grid-column:span 2; height:40px; }
  @media (max-width:720px) { body:not(.exploring) .bar { gap:4px; } body:not(.exploring) .bar .btn { padding:11px 5px; } #ride::before { display:none; } body.exploring.riding #ride-badge { display:none !important; } }
  @media (prefers-reduced-motion:reduce) { #ex-photo { transition:none; } }`;
  document.head.appendChild(style);

  // ------------------------------------------------------------------ DEBUG ONLY: plain bridge decks
  // Off by default and never built unless asked: roads.js (the V4 viewer) draws the real bridges, the pier and
  // the island. These flat ribbons exist so the scratch page can be looked at; explore itself reads only data.
  let debugDecks = null;
  debug.decks = on => {
    if (on && !debugDecks) {
      debugDecks = new THREE.Group();
      const mat = new THREE.MeshBasicMaterial({color: 0x1a2a38, side: THREE.DoubleSide}), edge = new THREE.LineBasicMaterial({color: 0x6be7e1});
      const strip = (pts, half, z) => {
        const pos = [], idx = [];
        pts.forEach((p, i) => {
          const a = pts[Math.max(0, i - 1)], b = pts[Math.min(pts.length - 1, i + 1)], dx = b[0] - a[0], dy = b[1] - a[1], l = Math.hypot(dx, dy) || 1, h = p.length > 2 ? p[2] : z;
          pos.push(p[0] - dy / l * half, h - .004, -(p[1] + dx / l * half), p[0] + dy / l * half, h - .004, -(p[1] - dx / l * half));
          if (i) idx.push(i * 2 - 2, i * 2, i * 2 - 1, i * 2 - 1, i * 2, i * 2 + 1);
        });
        const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3)); g.setIndex(idx);
        debugDecks.add(new THREE.Mesh(g, mat));
        const e = new THREE.BufferGeometry(); e.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3)); debugDecks.add(new THREE.Points(e, new THREE.PointsMaterial({color: 0x6be7e1, size: .03})));
      };
      for (const b of D.bridges || []) strip(b.points, b.halfWidth || .57, 0);
      if (lake) {
        strip([[lake.pier.x0, lake.pier.y0], [lake.pier.x1, lake.pier.y1]], lake.pier.width / 2, lake.pier.z);
        const disc = new THREE.Mesh(new THREE.CircleGeometry(lake.island.r, 40), mat); disc.rotation.x = -Math.PI / 2; disc.position.set(lake.island.x, lake.island.z - .02, -lake.island.y); debugDecks.add(disc);
      }
      scene.add(debugDecks);
    }
    if (debugDecks) debugDecks.visible = !!on;
  };

  // Accessors survive only through property descriptors (Object.assign would read each getter once).
  Object.defineProperties(api, Object.getOwnPropertyDescriptors({
    update, enter, leave, openHash, fastTravel, toggleBike, shuffleOutfit, startTour, photo, debug, trailReset,
    surfaces: {probe, surfaceAt, zoneAt, hit, zone, K, add: fn => extras.push(fn)},
    surfaceAt, design: D, plateaus: DATA.plateaus, notice: crowd.notice, room, travel, bike, player: P, input, touch, slugs: SLUGS,
    bikeKit: {body: kit.body, glow: kit.glow, bodyMaterial: bikeBodyMat, glowMaterial: bikeGlowMat, trail: trailMesh, fringe},
    get view() { return view; }, set view(v) { view = v ? 1 : 0; },
    get look() { return {yaw: camYaw, pitch: camPitch}; },
    setLook(yaw, pitch) { camYaw = yaw; if (pitch !== undefined) camPitch = pitch; chaseYaw = yaw; },
    // Places the visitor at a world point if it stands on a surface there; returns whether it moved.
    teleport(x, z, yaw, nearY) {
      const h = surfaceAt(x, z, nearY);
      if (h === null) return false;
      P.x = x; P.z = z; P.y = h; P.vx = P.vz = P.vy = 0; P.grounded = true;
      if (yaw !== undefined) { P.yaw = yaw; camYaw = yaw; chaseYaw = yaw; if (P.onBike) Object.assign(bike, {heading: yaw, vAngle: yaw}); }
      if (P.onBike) Object.assign(bike, {x, y: h, z}); trailReset(); room.candidate = null; room.held = 0;
      return true;
    },
    get position() {
      snapshot.x = P.x; snapshot.y = P.y; snapshot.z = P.z; snapshot.yaw = P.yaw; snapshot.onBike = P.onBike; snapshot.speed = P.onBike ? bike.speed : P.speed;
      snapshot.charge = bike.charge; snapshot.boosting = bike.boosting; snapshot.view = view; snapshot.dancing = P.dancing; snapshot.grounded = P.grounded;
      return snapshot;
    },
  }));
  return api;
})();
