// Explore HUD (C8.7): a minimap with fast travel, the room line, the speed on the bike and a hint card on
// first entry. Every text comes from the room files, the curated stage names, numbers or this file (B6).
const hud = (() => {
  const D = DATA.design;
  // Stage copy is curated here; design data supplies map coordinates only.
  const stageLabels = {
    episodic: 'Archive Sound System', core: 'Compass Main Stage', inbox: 'Welcome Stage',
    procedural: 'Works Warehouse', prospective: 'Site Rave', semantic: 'Listening Terrace',
    working: 'Downtown Club Floor', branding: 'Arcade Stage', onebrain: 'Planetarium Deck',
    prasma: 'Campus Terrace', reef: 'Reef Island Stage', jhon: 'Block Party',
  };
  const css = document.createElement('style');
  css.textContent = `
  #hud { position:fixed; inset:0; pointer-events:none; z-index:6; font:10px/1.4 var(--mono); color:var(--text); }
  #hud-map { position:absolute; left:16px; top:calc(16px + env(safe-area-inset-top,0px)); border:1px solid var(--line); border-radius:4px;
    background:rgba(3,9,19,.74); pointer-events:auto; cursor:crosshair; touch-action:none; }
  #hud.big #hud-map { left:50%; top:50%; transform:translate(-50%,-50%); box-shadow:0 20px 80px #000a; background:rgba(3,9,19,.93); }
  #hud.big #hud-hint { display:none; }
  #hud-map-note { position:absolute; left:50%; bottom:calc(24px + env(safe-area-inset-bottom,0px)); transform:translateX(-50%); display:none;
    padding:7px 12px; letter-spacing:.12em; text-transform:uppercase; color:var(--dim); }
  #hud.big #hud-map-note { display:block; }
  #hud-room { position:absolute; left:50%; top:calc(18px + env(safe-area-inset-top,0px)); transform:translateX(-50%); max-width:calc(100% - 560px);
    padding:9px 14px; letter-spacing:.14em; text-transform:uppercase; color:var(--hi); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  #hud-room b { font-weight:500; color:var(--text); }
  #hud-speed { position:absolute; left:50%; bottom:calc(26px + env(safe-area-inset-bottom,0px)); transform:translateX(-50%); display:flex; align-items:baseline; gap:6px;
    padding:8px 14px; color:var(--dim); letter-spacing:.12em; text-transform:uppercase; }
  #hud-speed b { font:600 26px/1 'Rajdhani',var(--sans); color:var(--text); min-width:44px; text-align:right; font-variant-numeric:tabular-nums; }
  #hud-speed i { display:block; width:64px; height:3px; margin-left:8px; background:#6be7e126; align-self:center; }
  #hud-speed s { display:block; height:100%; width:100%; background:var(--signal); box-shadow:0 0 8px var(--signal); transform-origin:left; }
  #hud-speed.boost s { background:#bdfcf3; }
  #hud-hint { position:absolute; left:50%; bottom:calc(92px + env(safe-area-inset-bottom,0px)); transform:translateX(-50%); width:min(560px,calc(100% - 32px));
    padding:12px 16px; color:var(--dim); font-size:11px; line-height:1.8; text-align:center; transition:opacity .6s; }
  #hud-hint b { color:var(--hi); font-weight:500; }
  #hud-hint.fade { opacity:0; }
  #hud-toast { position:absolute; left:50%; top:calc(64px + env(safe-area-inset-top,0px)); transform:translateX(-50%); padding:7px 12px; color:var(--hi);
    letter-spacing:.1em; text-transform:uppercase; }
  @media (max-width:720px) {
    #hud-room { top:calc(112px + env(safe-area-inset-top,0px)); left:16px; transform:none; max-width:calc(100% - 32px); font-size:9px; padding:7px 10px; }
    #hud-speed { top:calc(150px + env(safe-area-inset-top,0px)); bottom:auto; left:16px; transform:none; padding:6px 10px; }
    #hud-speed b { font-size:20px; min-width:34px; }
    #hud-toast { top:calc(196px + env(safe-area-inset-top,0px)); left:16px; transform:none; }
    #hud-hint { bottom:calc(250px + env(safe-area-inset-bottom,0px)); font-size:10px; }
  }
  @media (prefers-reduced-motion:reduce) { #hud-hint { transition:none; } }`;
  document.head.appendChild(css);
  const root = document.createElement('div');
  root.id = 'hud'; root.hidden = true;
  root.innerHTML = '<canvas id="hud-map" role="img" aria-label="City map. Click a stage to travel there."></canvas>' +
    '<div id="hud-map-note" class="glass">Click a stage to travel there · Tab closes the map</div>' +
    '<div id="hud-room" class="glass" role="status" aria-live="polite"></div>' +
    '<div id="hud-speed" class="glass" hidden><b id="hud-kmh">0</b><span>km/h</span><i><s id="hud-boost"></s></i></div>' +
    '<div id="hud-hint" class="glass" role="note" hidden></div><div id="hud-toast" class="glass" role="status" hidden></div>';
  document.body.appendChild(root);
  const map = root.querySelector('#hud-map'), ctx = map.getContext('2d');
  const roomEl = root.querySelector('#hud-room'), speedEl = root.querySelector('#hud-speed'), kmhEl = root.querySelector('#hud-kmh');
  const boostEl = root.querySelector('#hud-boost'), hintEl = root.querySelector('#hud-hint'), toastEl = root.querySelector('#hud-toast');

  // ------------------------------------------------------------------ map projection (layout x east, y north)
  let x0 = DATA.bounds[0], y0 = DATA.bounds[1], x1 = DATA.bounds[2], y1 = DATA.bounds[3];
  const lake = (D.lake || [])[0];
  if (lake) { x1 = Math.max(x1, lake.cx + lake.rx); y0 = Math.min(y0, lake.cy - lake.rx); x0 = Math.min(x0, lake.cx - lake.rx); }
  x0 -= 3; y0 -= 3; x1 += 3; y1 += 3;
  const aspect = (x1 - x0) / (y1 - y0);
  let big = false, cssW = 0, cssH = 0, scale = 1, dpr = 1, staticKey = '', hover = -1, ticks = 0;
  // QA positive control only: draw the map without venue ticks.
  const debug = {noTicks: false};
  // The map is redrawn only when what it shows moved: half a pixel of travel, a degree of turn, the room, the
  // hovered stage, the map size or a new layout.
  const drawn = {x: NaN, z: NaN, yaw: NaN, room: '', hover: -2, key: ''};
  const staticLayer = document.createElement('canvas'), sctx = staticLayer.getContext('2d');
  const px = x => (x - x0) * scale, py = y => (y1 - y) * scale;
  const hexOf = c => '#' + c.map(v => Math.round(v * 255).toString(16).padStart(2, '0')).join('');
  const tone = Object.fromEntries(Object.keys(DATA.plateaus).map(d => [d, hexOf(styleOf(d).light)]));
  function layout() {
    const small = innerWidth < 720 ? 128 : 220;
    cssW = big ? Math.min(innerWidth * .9, (innerHeight - 140) * .9 * aspect, 1100) : small;
    cssH = cssW / aspect; scale = cssW / (x1 - x0); dpr = Math.min(2, devicePixelRatio || 1);
    map.style.width = cssW + 'px'; map.style.height = cssH + 'px';
    map.width = Math.round(cssW * dpr); map.height = Math.round(cssH * dpr);
    const key = map.width + 'x' + map.height;
    if (key !== staticKey) { staticKey = key; drawStatic(); }
    drawn.key = '';   // setting the canvas size clears it
  }
  function path(points, close) {
    sctx.beginPath();
    points.forEach((p, i) => i ? sctx.lineTo(px(p[0]), py(p[1])) : sctx.moveTo(px(p[0]), py(p[1])));
    if (close) sctx.closePath();
  }
  // Everything that never moves is drawn once per map size into its own canvas.
  function drawStatic() {
    staticLayer.width = map.width; staticLayer.height = map.height;
    sctx.setTransform(dpr, 0, 0, dpr, 0, 0); sctx.clearRect(0, 0, cssW, cssH);
    const k = Math.max(.6, scale);
    if (lake) {
      sctx.save(); sctx.translate(px(lake.cx), py(lake.cy)); sctx.rotate(-lake.angle);
      sctx.beginPath(); sctx.ellipse(0, 0, lake.rx * scale, lake.ry * scale, 0, 0, TAU);
      sctx.fillStyle = 'rgba(94,230,216,.13)'; sctx.fill(); sctx.strokeStyle = 'rgba(94,230,216,.4)'; sctx.lineWidth = 1; sctx.stroke(); sctx.restore();
    }
    for (const [d, p] of Object.entries(DATA.plateaus)) {
      sctx.beginPath();
      if (p.shape === 'disc') sctx.arc(px(p.cx), py(p.cy), p.rx * scale, 0, TAU);
      else if (sctx.roundRect) sctx.roundRect(px(p.cx - p.rx), py(p.cy + p.ry), 2 * p.rx * scale, 2 * p.ry * scale, 2.5 * scale);
      else sctx.rect(px(p.cx - p.rx), py(p.cy + p.ry), 2 * p.rx * scale, 2 * p.ry * scale);
      sctx.fillStyle = tone[d] + '26'; sctx.fill(); sctx.strokeStyle = tone[d] + 'aa'; sctx.lineWidth = 1; sctx.stroke();
    }
    sctx.lineCap = 'round'; sctx.lineJoin = 'round';
    for (const r of D.routes) { path(r.points, true); sctx.strokeStyle = tone[r.district] + '55'; sctx.lineWidth = Math.max(.8, (r.width || .88) * k * .9); sctx.stroke(); }
    for (const s of D.streets || []) { path(s.points, false); sctx.strokeStyle = tone[s.district] + '44'; sctx.lineWidth = Math.max(.6, .54 * k); sctx.stroke(); }
    for (const b of D.bridges || []) {
      const a = b.points[0], z = b.points[b.points.length - 1];
      const g = sctx.createLinearGradient(px(a[0]), py(a[1]), px(z[0]), py(z[1]));
      g.addColorStop(0, tone[b.from]); g.addColorStop(1, tone[b.to]);
      path(b.points, false); sctx.strokeStyle = g; sctx.lineWidth = Math.max(1.4, 1.14 * k); sctx.stroke();
    }
    if (lake && lake.pier) { path([[lake.pier.x0, lake.pier.y0], [lake.pier.x1, lake.pier.y1]], false); sctx.strokeStyle = '#5ee6d8'; sctx.lineWidth = Math.max(1, .5 * k); sctx.stroke(); }
    // Venues are ticks on their host's face, in their sign colour. venues.items keeps the layout point (x, y)
    // and the outward world normal (world z is layout -y); its `face` is the world position, not a direction.
    sctx.lineWidth = Math.max(1, .25 * k);
    const len = Math.max(3 / scale, .8);
    ticks = 0;
    if (!debug.noTicks) for (const v of venues.items) {
      const dx = v.normal.x, dy = -v.normal.z, x = px(v.x), y = py(v.y), x2 = px(v.x + dx * len), y2 = py(v.y + dy * len);
      if (!(x === x && y === y && x2 === x2 && y2 === y2)) continue;
      sctx.beginPath(); sctx.moveTo(x, y); sctx.lineTo(x2, y2);
      sctx.strokeStyle = '#' + v.color.getHexString(); sctx.stroke(); ticks++;
    }
  }
  const stageRadius = () => big ? 6 : 3.2;
  function draw(me) {
    ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.clearRect(0, 0, map.width, map.height);
    ctx.drawImage(staticLayer, 0, 0);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const r = stageRadius(), room = cityAudio.desired;
    for (let i = 0; i < D.stages.length; i++) {
      const s = D.stages[i];
      ctx.beginPath(); ctx.arc(px(s.x), py(s.y), r + (i === hover ? 2 : 0), 0, TAU);
      ctx.fillStyle = tone[s.district]; ctx.fill();
      ctx.lineWidth = s.district === room ? 2 : 1; ctx.strokeStyle = i === hover || s.district === room ? '#ffffff' : '#030913'; ctx.stroke();
    }
    if (big && hover >= 0) {
      const s = D.stages[hover];
      ctx.font = "500 11px 'IBM Plex Mono', monospace"; ctx.fillStyle = '#e8f6f9'; ctx.textAlign = 'center';
      ctx.fillText((stageLabels[s.district] || 'Stage').toUpperCase(), px(s.x), py(s.y) - r - 8);
    }
    // You: an arrow along your heading (world z is layout -y).
    const size = big ? 10 : 8;
    ctx.save(); ctx.translate(px(me.x), py(-me.z)); ctx.rotate(Math.PI - me.yaw);
    ctx.beginPath(); ctx.moveTo(0, -size); ctx.lineTo(size * .62, size * .7); ctx.lineTo(0, size * .35); ctx.lineTo(-size * .62, size * .7); ctx.closePath();
    ctx.fillStyle = '#6be7e1'; ctx.fill(); ctx.lineWidth = 1.5; ctx.strokeStyle = '#ffffff'; ctx.stroke(); ctx.restore();
  }
  function stageAt(clientX, clientY) {
    const rect = map.getBoundingClientRect(), x = clientX - rect.left, y = clientY - rect.top;
    let best = -1, bestD = (stageRadius() + (big ? 10 : 7)) ** 2;
    D.stages.forEach((s, i) => { const d = (px(s.x) - x) ** 2 + (py(s.y) - y) ** 2; if (d < bestD) { bestD = d; best = i; } });
    return best;
  }
  map.addEventListener('pointermove', e => { hover = stageAt(e.clientX, e.clientY); map.title = hover >= 0 ? stageLabels[D.stages[hover].district] || 'Stage' : ''; });
  map.addEventListener('pointerleave', () => { hover = -1; });
  map.addEventListener('click', e => {
    const i = stageAt(e.clientX, e.clientY);
    if (i >= 0) { if (explore.fastTravel(i) && big) toggleMap(false); }
    else if (!big) toggleMap(true);
  });
  function toggleMap(force) {
    big = force === undefined ? !big : !!force;
    root.classList.toggle('big', big); layout();
  }

  // ------------------------------------------------------------------ room line, speed, hint, toast
  // The room line is the room's title plus the style phrase after the last separator of its file's first line.
  function roomLine(id) {
    const r = cityAudio.rooms[id];
    if (!r || id === 'skyline') return '<b>Skyline</b>';
    const first = (r.code || '').split('\n')[0].replace(/^\/\/\s*/, '').split('·');
    const style = first.length > 1 ? first[first.length - 1].trim() : '';
    return '<b>' + r.title + '</b>' + (style ? ', ' + style : '');
  }
  let roomShown = '', kmhShown = -1, boostShown = -1, hintTimer = 0, toastTimer = 0, frame = 0;
  function mapChanged(s, room) {
    const k = Math.max(scale, .01);
    if (Math.abs(s.x - drawn.x) * k < .5 && Math.abs(s.z - drawn.z) * k < .5 && Math.abs(s.yaw - drawn.yaw) < .017 && room === drawn.room && hover === drawn.hover && staticKey === drawn.key) return false;
    drawn.x = s.x; drawn.z = s.z; drawn.yaw = s.yaw; drawn.room = room; drawn.hover = hover; drawn.key = staticKey;
    return true;
  }
  const HINT_DESK = '<b>WASD</b> move · <b>click</b> to look with the mouse · <b>Shift</b> sprint or boost · <b>Space</b> jump or slide<br>' +
    '<b>E</b> light cycle · <b>V</b> view · <b>Q</b> dance on a stage · <b>O</b> outfit · <b>P</b> photo · <b>Tab</b> map · <b>Esc</b> leave';
  const HINT_TOUCH = 'Left thumb moves, drag on the right to look.<br><b>Bike</b> summons the light cycle, <b>Map</b> travels to any stage.';
  function show(first, touchMode) {
    root.hidden = false; toggleMap(false); roomShown = ''; kmhShown = -1; boostShown = -1;
    if (first) { hintEl.innerHTML = touchMode ? HINT_TOUCH : HINT_DESK; hintEl.hidden = false; hintEl.classList.remove('fade'); hintTimer = 6; }
  }
  function hide() { root.hidden = true; hintEl.hidden = true; toastEl.hidden = true; hintTimer = toastTimer = 0; big = false; root.classList.remove('big'); }
  function toast(text, seconds = 2.5) { toastEl.textContent = text; toastEl.hidden = false; toastTimer = seconds; }
  function update(dt, s) {
    if (root.hidden) return;
    const room = cityAudio.desired;
    if (room !== roomShown) { roomShown = room; roomEl.innerHTML = roomLine(room); }
    if (speedEl.hidden === s.onBike) speedEl.hidden = !s.onBike;
    if (s.onBike) {
      const kmh = Math.round(Math.abs(s.speed) * 4.5 * 3.6);
      if (kmh !== kmhShown) { kmhShown = kmh; kmhEl.textContent = kmh; }
      const charge = Math.round(s.charge * 100);
      if (charge !== boostShown) { boostShown = charge; boostEl.style.transform = 'scaleX(' + (charge / 100) + ')'; }
      if (speedEl.classList.contains('boost') !== s.boosting) speedEl.classList.toggle('boost', s.boosting);
    }
    if (hintTimer > 0) { hintTimer -= dt; if (hintTimer <= .6) hintEl.classList.add('fade'); if (hintTimer <= 0) hintEl.hidden = true; }
    if (toastTimer > 0) { toastTimer -= dt; if (toastTimer <= 0) toastEl.hidden = true; }
    // Phones redraw the map at most every other frame.
    if ((tier.current > 1 || big || (frame++ & 1) === 0) && mapChanged(s, room)) draw(s);
  }
  window.addEventListener('resize', () => { if (!root.hidden) layout(); });
  return {
    root, show, hide, update, toast, toggleMap, roomLine,
    get mapOpen() { return big; },
    get hintVisible() { return !hintEl.hidden; },
    debug,
    // QA: venue ticks drawn on the static layer, the layer itself, and a redraw after a debug switch.
    get ticks() { return ticks; }, staticLayer, redraw() { staticKey = ''; layout(); },
    // QA: where stage i is drawn on screen right now.
    stagePoint(i) { const rect = map.getBoundingClientRect(), s = D.stages[i]; return {x: rect.left + px(s.x), y: rect.top + py(s.y)}; },
  };
})();
