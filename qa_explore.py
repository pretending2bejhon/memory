"""V6 Explore gates (spec D, V6 row, plus the S2 on-foot scene of C13.3).

Usage (Python 3.11, repo harness):
  py -V:Astral/CPython3.11.15 qa_explore.py [gate ...] [--no-controls] [--url=URL] [--prefix=NAME]
Gates: random, camfloor, causeway, fasttravel, minimap, photo, deeplinks, touch, gamepad, extras, silentdance,
walkable, modes, perf, s3mode.
Every gate runs once as written and once with its positive control (a deliberately broken input or feature),
and the report records that the control went red. Reports and shots go to renders/qa/.

qa_world imports verify_explore and the S2 setup from this module. The cumulative V6 gates run after
verify_phone, while the standalone command also proves each gate's positive control.
"""
import json
import math
import random
import struct
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE
sys.path.insert(0, str(ROOT))
from qa_browser import Engine

URL = 'http://127.0.0.1:8765/viewer/'
PREFIX = 'b-v6'
SHOTS = ROOT / 'renders' / 'qa' / (PREFIX + '-explore-shots')


# === qa_world block begin: patch_qa_world_v6.py pastes everything down to the end marker into qa_world.py ===
# V6 Explore gates (C8, C3.8, C7.2). Each takes the Engine (verify_v6_touch takes its browser) and the page url and
# returns a dict with "passed". Every gate that loads the page leaves it freshly loaded at 1440x900 with reduced
# motion off and outside explore (v6_restore), so the checks that run after it read the page they expect (B10).

# In-page helpers: an independent footprint test (the city-life.js rule: w and d times 0.57 around each note,
# absent notes excluded), a frame sampler and a polyline pilot that drives explore through its input hook.
V6_PRELUDE = r"""() => {
  if (window.__qa) return true;
  const v = window.__vc, e = v.explore;
  // Plan-view boxes, strict (no radius): a point strictly inside a present note's box is inside a footprint.
  const boxes = v.nodes.map(n => ({n, x0: n.x - n.w * .57, x1: n.x + n.w * .57, z0: -n.y - n.d * .57, z1: -n.y + n.d * .57}));
  window.__qa = {
    boxes,
    insideAt(x, z) {
      for (const b of boxes) if (b.n.state !== 'absent' && x > b.x0 && x < b.x1 && z > b.z0 && z < b.z1) return {id: b.n.id, district: b.n.district};
      return null;
    },
    // The camera is under the ground when it is less than 0.05 above your feet or above the surface under it
    // nearest your level (an overpass deck, or the road under it).
    cameraLow() {
      const c = v.camera.position, p = e.player, g = e.surfaceAt(c.x, c.z, p.y + .3), floor = g !== null && g > p.y ? g : p.y;
      return c.y < floor + .05 ? [+c.x.toFixed(3), +c.y.toFixed(3), +c.z.toFixed(3), +floor.toFixed(3)] : null;
    },
    // Whether the avatar's torso is drawn (a non-zero scale in its instance matrix).
    avatarDrawn() { const a = v.crowd.parts.torso.instanceMatrix.array, o = v.crowd.avatarIndex * 16; return Math.hypot(a[o], a[o + 1], a[o + 2]) > 1e-4; },
    frames: [], sampling: false,
    sample(fn) { const q = window.__qa; q.frames = []; q.sampling = true;
      const tick = () => { if (!q.sampling) return; try { q.frames.push(fn()); } catch (err) { q.frames.push({error: String(err)}); } requestAnimationFrame(tick); };
      requestAnimationFrame(tick); },
    stop() { window.__qa.sampling = false; return window.__qa.frames; },
    follow(points, opts) {
      let idx = 0;
      e.pilot = input => {
        const p = e.player;
        let best = idx, bd = Infinity;
        for (let i = idx; i < Math.min(points.length, idx + 60); i++) { const q = points[i], d = (q[0] - p.x) ** 2 + (-q[1] - p.z) ** 2; if (d < bd) { bd = d; best = i; } }
        idx = best;
        const t = points[Math.min(points.length - 1, idx + (opts.ahead || 6))];
        const want = Math.atan2(t[0] - p.x, -t[1] - p.z), heading = e.bike.heading;
        let diff = want - heading; diff -= Math.round(diff / (2 * Math.PI)) * 2 * Math.PI;
        input.steer = Math.max(-1, Math.min(1, -diff * 3)); input.mx = input.steer;
        input.throttle = idx >= points.length - 3 ? 0 : 1; input.my = input.throttle; input.brake = 0; input.fast = !!opts.boost;
      };
    },
  };
  return true;
}"""

# S2, V6 column (C13.3): the on-foot visitor 3 units along the Downtown ring from the stage junction, facing the stage.
V6_S2_SPOT = """() => { const v = window.__vc, e = v.explore, s = e.design.stages.find(s => s.district === 'working');
  const route = v.routes.find(r => r.district === 'working'), sx = s.x, sz = -s.y;
  let best = 0, bd = Infinity; const p = new (v.camera.position.constructor)();
  for (let d = 0; d < route.length; d += .05) { v.sampleRoute(route, d, p); const q = (p.x - sx) ** 2 + (p.z - sz) ** 2; if (q < bd) { bd = q; best = d; } }
  v.sampleRoute(route, best + 3, p);
  const yaw = Math.atan2(sx - p.x, sz - p.z), ok = e.teleport(p.x, p.z, yaw, p.y); e.setLook(yaw, -.08);
  return {ok, x: p.x, z: p.z, yaw, junction: best}; }"""

# The S3 pilot repeats a real boosted crossing so a 60-second performance trace keeps the bike on the
# Memory Causeway. The control leaves the same pilot in place but disables boost.
V6_S3_SETUP = """(noBoost=false) => {
  const v=window.__vc,e=v.explore,b=e.design.bridges[0],points=b.points;
  e.openHash('#explore/compass');e.toggleBike();
  const a=points[2],c=points[5],yaw=Math.atan2(c[0]-a[0],-c[1]+a[1]);
  const q=window.__qaS3={bridge:b.name,boostDeckMs:0,deckMs:0,laps:0,noBoost};
  let idx=2;
  function reset(){idx=2;if(e.teleport(a[0],-a[1],yaw,a[2]))q.laps++;e.bike.speed=0;}
  reset();e.setLook(yaw,-.08);
  e.pilot=(input,dt)=>{
    const p=e.player;
    if(p.x<points[points.length-4][0]+.2)reset();
    let best=idx,dist=Infinity;
    for(let i=idx;i<Math.min(points.length,idx+60);i++){
      const t=points[i],d=(t[0]-p.x)**2+(-t[1]-p.z)**2;
      if(d<dist){dist=d;best=i;}
    }
    idx=best;
    const t=points[Math.min(points.length-1,idx+6)],want=Math.atan2(t[0]-p.x,-t[1]-p.z);
    let diff=want-e.bike.heading;diff-=Math.round(diff/(2*Math.PI))*2*Math.PI;
    input.steer=Math.max(-1,Math.min(1,-diff*3));input.mx=input.steer;
    input.throttle=1;input.my=1;input.brake=0;input.fast=!noBoost;
    if(e.surfaces.probe(p.x,p.z,p.y)&&e.surfaces.hit.kind===e.surfaces.K.bridge&&e.surfaces.hit.owner===0){
      q.deckMs+=dt*1000;if(e.bike.boosting)q.boostDeckMs+=dt*1000;
    }
  };
  return {ok:q.laps===1,onBike:e.player.onBike,bridge:q.bridge};
}"""

V6_CHECK_NAMES = (
    "explore: random input never enters a footprint or the ground", "explore: over-the-shoulder camera stays above the ground",
    "explore: Memory Causeway continuous at boost, room turns on the far half", "explore: minimap fast travel",
    "explore: minimap venue ticks drawn", "explore: photo mode freezes the world and hides the UI", "explore: deep links",
    "explore: 375 px touch controls", "explore: standard gamepad, polled only while connected",
    "explore: keys, heads, cheers, R hook, absent buildings, reduced motion", "explore: low-energy dancing with sound off",
    "explore: ring curbs and bridge ends walkable",
    "explore: play button, re-entry hash, photo framing")


def v6_ev(page, expression, arg=None):
    return page.evaluate(expression, arg, isolated_context=False)


def v6_wait(page, expression, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if v6_ev(page, expression):
            return True
        page.wait_for_timeout(100)
    return False


def v6_open_page(eng, url, hash_=''):
    # A hash-only change is a same-document navigation; blank first so every gate starts from a fresh load.
    eng.page.goto('about:blank')
    eng.goto(url + hash_)
    eng.ready()
    eng.wait(1.5)
    v6_ev(eng.page, V6_PRELUDE)


def v6_restore(eng, url):
    """Leave the page as the checks after a V6 gate expect it: 1440x900, reduced motion off, a fresh load outside explore."""
    eng.page.emulate_media(reduced_motion='no-preference')
    eng.page.set_viewport_size({'width': 1440, 'height': 900})
    eng.page.goto('about:blank')
    eng.goto(url)
    eng.ready()
    eng.wait(1)


def v6_beat_seconds(eng):
    return v6_ev(eng.page, '() => window.__vc.beat.beatSeconds')


def v6_restores(gate):
    def run(eng, url, *args, **kwargs):
        try:
            return gate(eng, url, *args, **kwargs)
        finally:
            v6_restore(eng, url)
    run.__name__, run.__doc__, run.__wrapped__ = gate.__name__, gate.__doc__, gate
    return run


# ------------------------------------------------------------------ gate 1: 20 s of random input in Downtown
@v6_restores
def verify_v6_random_downtown(eng, url, control=False, seconds=20, seed=6):
    """C8.4 and C8.5: random keys and mouse look (with large vertical drags) for 20 s; the avatar and the camera
    never enter a footprint and the camera never goes under the ground."""
    v6_open_page(eng, url, '#explore/downtown')
    page = eng.page
    v6_ev(page, """() => { const v = window.__vc, e = v.explore, q = window.__qa;
      q.sample(() => { const p = e.player, c = v.camera.position;
        return {x: p.x, y: p.y, z: p.z, bike: p.onBike, pitch: e.look.pitch, avatar: q.insideAt(p.x, p.z, p.y),
          camera: v.pointBlocked(c, 0) ? [c.x, c.y, c.z] : null, low: e.view === 0 && !e.photo.active ? q.cameraLow() : null}; }); }""")
    if control:
        # Positive control: collision and the camera floor off, the camera looking up, and a pilot that walks
        # straight into the nearest lit building.
        v6_ev(page, """() => { const v = window.__vc, e = v.explore, p = e.player; e.debug.noCollide = true; e.debug.noCamFloor = true;
          let best = null, bd = 1e9; for (const n of v.nodes) { if (n.state === 'absent' || n.district !== 'working') continue;
            const d = (n.x - p.x) ** 2 + (-n.y - p.z) ** 2; if (d < bd) { bd = d; best = n; } }
          const yaw = Math.atan2(best.x - p.x, -best.y - p.z); e.setLook(yaw, .9);
          if (p.onBike) e.toggleBike();
          e.pilot = input => { input.my = 1; input.mx = 0; input.throttle = 1; input.steer = 0; input.lookX = 0; input.lookY = 0; }; }""")
        eng.wait(min(seconds, 8))
    else:
        rnd = random.Random(seed)
        keys = ['KeyW', 'KeyA', 'KeyS', 'KeyD', 'ShiftLeft']
        held = set()
        box = page.locator('canvas').first.bounding_box()
        cx, cy = box['x'] + box['width'] / 2, box['y'] + box['height'] / 2
        end = time.monotonic() + seconds
        bike_at, bike_off = None, False
        while time.monotonic() < end:
            for k in keys:
                want = rnd.random() < (.55 if k == 'KeyW' else .25)
                if want and k not in held:
                    page.keyboard.down(k); held.add(k)
                elif not want and k in held:
                    page.keyboard.up(k); held.discard(k)
            if rnd.random() < .12:
                page.keyboard.press('Space')
            left = end - time.monotonic()
            if (bike_at is None and left < seconds * .45) or (bike_at is not None and not bike_off and left < seconds * .12):
                # About 55 % of the run on foot, then the bike, then back on foot for the last seconds.
                page.keyboard.press('KeyE')
                if bike_at is None:
                    bike_at = left
                else:
                    bike_off = True
            if rnd.random() < .5:
                # Two drags in five are large vertical ones, to look far up and far down.
                dy = rnd.uniform(-260, 260) if rnd.random() < .4 else rnd.uniform(-40, 40)
                page.mouse.move(cx, cy); page.mouse.down()
                page.mouse.move(cx + rnd.uniform(-160, 160), cy + dy, steps=4); page.mouse.up()
            page.wait_for_timeout(250)
        for k in held:
            page.keyboard.up(k)
    frames = v6_ev(page, '() => window.__qa.stop()')
    avatar_hits = [f for f in frames if f.get('avatar')]
    camera_hits = [f for f in frames if f.get('camera')]
    low = [f for f in frames if f.get('low')]
    errors = [f for f in frames if f.get('error')]
    path = sum(math.hypot(b['x'] - a['x'], b['z'] - a['z']) for a, b in zip(frames, frames[1:]))
    pitches = [f['pitch'] for f in frames if 'pitch' in f]
    passed = bool(frames) and not avatar_hits and not camera_hits and not low and not errors and path > 3
    return {'passed': passed, 'control': control, 'frames': len(frames), 'pathUnits': round(path, 2),
            'bikeFrames': sum(1 for f in frames if f.get('bike')), 'pitchRange': [round(min(pitches), 2), round(max(pitches), 2)] if pitches else None,
            'avatarInsideFrames': len(avatar_hits), 'cameraInsideFrames': len(camera_hits), 'cameraBelowGroundFrames': len(low),
            'firstAvatarHit': avatar_hits[0] if avatar_hits else None, 'firstCameraHit': camera_hits[0] if camera_hits else None,
            'firstLow': low[0] if low else None, 'errors': errors[:3], 'pageErrors': eng.errors[:5]}


# ------------------------------------------------------------------ gate 2: the camera stays above the ground
@v6_restores
def verify_v6_camera_floor(eng, url, control=False, shots=None):
    """C8.5: looking from level to fully up, on a desktop and a portrait phone screen, on the Downtown deck and on the
    Memory Causeway deck, the over-the-shoulder camera stays at least 0.05 above the ground under it."""
    rows = []
    for width, height in ((1440, 900), (390, 844)):
        eng.page.set_viewport_size({'width': width, 'height': height})
        v6_open_page(eng, url, '#explore/downtown')
        page = eng.page
        if control:
            v6_ev(page, '() => { window.__vc.explore.debug.noCamFloor = true; }')
        for spot in ('downtown', 'causeway'):
            if spot == 'causeway':
                v6_ev(page, """() => { const e = window.__vc.explore, b = e.design.bridges[0], i = Math.floor(b.points.length / 2), a = b.points[i], c = b.points[i + 3];
                  e.teleport(a[0], -a[1], Math.atan2(c[0] - a[0], -c[1] + a[1]), a[2]); }""")
            yaw = v6_ev(page, '() => window.__vc.explore.look.yaw')
            for pitch in (0, .3, .45, .6, .75, .9, 1.0):
                v6_ev(page, '([y, p]) => window.__vc.explore.setLook(y, p)', [yaw, pitch])
                eng.wait(.6)
                row = v6_ev(page, """() => { const v = window.__vc, e = v.explore, q = window.__qa, c = v.camera.position, p = e.player;
                  return {camY: +c.y.toFixed(3), playerY: +p.y.toFixed(3), low: q.cameraLow(), aspect: +v.camera.aspect.toFixed(2)}; }""")
                rows.append({'size': f'{width}x{height}', 'spot': spot, 'pitch': pitch, **row})
                if shots and spot == 'downtown' and pitch == 1.0:
                    eng.screenshot(shots / f"cam-look-up-{width}{'-control' if control else ''}.png")
    low = [r for r in rows if r['low']]
    return {'passed': bool(rows) and not low, 'control': control, 'samples': len(rows), 'belowGround': len(low),
            'firstLow': low[0] if low else None, 'rows': rows, 'pageErrors': eng.errors[:5]}


# ------------------------------------------------------------------ gate 3: the Memory Causeway at boost
@v6_restores
def verify_v6_causeway(eng, url, control=None):
    """C8.3, C8.4, C8.6: boost across the Memory Causeway; the deck is continuous under the bike the whole way and
    the room turns to the Archive while the bike is on the far half."""
    v6_open_page(eng, url, '#explore/compass')
    page = eng.page
    if control == 'halves':
        v6_ev(page, '() => { window.__vc.explore.debug.noBridgeHalves = true; }')
    if control == 'decks':
        v6_ev(page, '() => { window.__vc.explore.debug.noBridges = true; }')
    start = v6_ev(page, """() => { const e = window.__vc.explore, b = e.design.bridges[0];
      e.toggleBike();
      const a = b.points[2], c = b.points[5], yaw = Math.atan2(c[0] - a[0], -c[1] + a[1]);
      const ok = e.teleport(a[0], -a[1], yaw, a[2]);
      return {ok, name: b.name, from: b.from, to: b.to, length: b.length, split: b.split}; }""")
    eng.wait(v6_beat_seconds(eng) * 4 + .3)   # the bike materialises over one bar
    v6_ev(page, """() => { const v = window.__vc, e = v.explore, q = window.__qa, S = e.surfaces, b = e.design.bridges[0];
      q.follow(b.points, {boost: true, ahead: 6});
      q.sample(() => { const p = e.player, ok = S.probe(p.x, p.z, p.y), h = S.hit;
        return {t: performance.now(), x: p.x, y: p.y, z: p.z, surface: ok ? h.h : null, kind: h.kind, owner: h.owner, s: h.s,
          speed: e.bike.speed, boosting: e.bike.boosting, room: v.audio.desired, onBike: p.onBike, inside: q.insideAt(p.x, p.z, p.y)}; }); }""")
    v6_wait(page, """() => { const f = window.__qa.frames, last = f[f.length - 1]; return last && (last.x < -38.2 || f.length > 900); }""", 20)
    eng.wait(.3)
    frames = v6_ev(page, '() => { window.__vc.explore.pilot = null; return window.__qa.stop(); }')
    K_BRIDGE = 5
    length, split = start['length'], start['split']
    on_bridge = [f for f in frames if f['kind'] == K_BRIDGE and f['owner'] == 0]
    max_s = max((f['s'] for f in on_bridge), default=0)
    reached = max_s >= length - 1.2 or any(f['x'] < -38.2 for f in frames)
    gaps = [f for f in frames if f['surface'] is None]
    # Continuity on the paved way (ring, junction fillets, deck): no height change steeper than the 12 % grade
    # limit plus 0.02. Stepping between a road and its plateau is the 0.035 kerb and may not exceed 0.04.
    paved, jumps = (3, 5, 7), []
    for a, b in zip(frames, frames[1:]):
        run, rise = math.hypot(b['x'] - a['x'], b['z'] - a['z']), abs(b['y'] - a['y'])
        limit = .12 * run + .02 if a['kind'] in paved and b['kind'] in paved else .04
        if rise > limit:
            jumps.append({'from': a['y'], 'to': b['y'], 'run': round(run, 3), 'x': b['x'], 'kinds': [a['kind'], b['kind']]})
    off_deck = [f for f in on_bridge if f['surface'] is not None and abs(f['y'] - f['surface']) > .011]
    switch = next((f for f in frames if f['room'] == 'episodic'), None)
    switched_far_half = bool(switch and switch['kind'] == K_BRIDGE and switch['owner'] == 0 and split < switch['s'] < length)
    top_speed = max((f['speed'] for f in frames), default=0)
    boost_frames = [f for f in frames if f['boosting']]
    boost_seconds = (boost_frames[-1]['t'] - boost_frames[0]['t']) / 1000 if len(boost_frames) > 1 else 0
    inside = [f for f in frames if f['inside']]
    passed = (start['ok'] and reached and not gaps and not jumps and not off_deck and switched_far_half
              and top_speed >= 6.9 and boost_seconds >= 2 and not inside)
    return {'passed': passed, 'control': control, 'bridge': start, 'frames': len(frames), 'reachedFarEnd': reached,
            'maxBridgeS': round(max_s, 2), 'surfaceGaps': len(gaps), 'heightJumps': jumps[:3], 'offDeckFrames': len(off_deck),
            'roomSwitch': switch and {k: switch[k] for k in ('kind', 'owner', 's', 'x')},
            'switchedOnFarHalf': switched_far_half, 'topSpeed': round(top_speed, 2), 'boostSeconds': round(boost_seconds, 2),
            'insideFrames': len(inside), 'seconds': round((frames[-1]['t'] - frames[0]['t']) / 1000, 2) if frames else 0,
            'pageErrors': eng.errors[:5]}


# ------------------------------------------------------------------ gate 4: minimap fast travel
# A point inside the map that is at least the dot radius plus 8 px from every stage dot.
V6_EMPTY_MAP_POINT = """() => { const h = window.__vc.hud, r = document.getElementById('hud-map').getBoundingClientRect(), n = window.__vc.explore.design.stages.length;
  const clear = h.mapOpen ? 14 : 11.2, dots = Array.from({length: n}, (_, i) => h.stagePoint(i));
  for (let y = r.top + 6; y < r.bottom - 6; y += 3) for (let x = r.left + 6; x < r.right - 6; x += 3)
    if (dots.every(d => Math.hypot(d.x - x, d.y - y) >= clear)) return {x, y, map: [r.left, r.top, r.right, r.bottom], nearest: Math.min(...dots.map(d => Math.hypot(d.x - x, d.y - y)))};
  return null; }"""


@v6_restores
def verify_v6_fast_travel(eng, url, control=False, big_map=False):
    """C8.7: clicking a stage on the minimap travels there through the derez effect (one bar); a click on the map
    away from every stage does not travel."""
    v6_open_page(eng, url, '#explore/compass')
    page = eng.page
    info = v6_ev(page, """() => { const e = window.__vc.explore, i = e.design.stages.findIndex(s => s.district === 'working');
      return {index: i, stage: e.design.stages[i], before: {x: e.player.x, z: e.player.z}}; }""")
    if big_map:
        page.keyboard.press('Tab'); eng.wait(.4)
    point = v6_ev(page, '(i) => window.__vc.hud.stagePoint(i)', info['index'])
    if control:
        point = v6_ev(page, V6_EMPTY_MAP_POINT)   # inside the map, away from every stage dot
    v6_ev(page, """() => { const e = window.__vc.explore, q = window.__qa;
      q.sample(() => ({shrink: e.travel.active ? 1 : 0, t: e.travel.t, x: e.player.x, z: e.player.z})); }""")
    page.mouse.click(point['x'], point['y'])
    eng.wait(v6_beat_seconds(eng) * 4 + 1.2)
    frames = v6_ev(page, '() => window.__qa.stop()')
    after = v6_ev(page, """(i) => { const v = window.__vc, e = v.explore, s = e.design.stages[i], p = e.player, S = e.surfaces;
      S.probe(p.x, p.z, p.y);
      return {x: p.x, z: p.z, onStage: S.hit.kind === 2 && S.hit.owner === i, distance: Math.hypot(p.x - s.x, p.z + s.y),
        travels: e.travel.count, room: v.audio.desired, mapOpen: v.hud.mapOpen}; }""", info['index'])
    travelling = [f for f in frames if f['shrink']]
    passed = after['onStage'] and after['travels'] == 1 and len(travelling) > 10 and after['room'] == 'working'
    return {'passed': passed, 'bigMap': big_map, 'control': control, 'clicked': point, 'target': info['stage']['name'],
            'after': after, 'travelFrames': len(travelling), 'pageErrors': eng.errors[:5]}


# ------------------------------------------------------------------ gate 5: venue ticks on the map
V6_TICK_PIXELS = """(control) => { const h = window.__vc.hud, c = h.staticLayer;
  const grab = () => c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
  // Chrome moves a canvas that is read back from GPU to CPU raster, which anti-aliases differently: read it twice
  // first so both measured draws are rastered the same way.
  h.redraw(); grab(); h.redraw(); grab();
  h.debug.noTicks = true; h.redraw(); const without = grab();
  h.debug.noTicks = !!control; h.redraw(); const withTicks = grab(), ticks = h.ticks;
  // Two draws of the same layer differ a little (GPU canvas rounding, amplified in faint pixels once getImageData
  // un-premultiplies them): compare premultiplied values and count a pixel only when a channel moves by more than 8.
  let changed = 0;
  for (let i = 0; i < without.length; i += 4) { const a0 = without[i + 3] / 255, a1 = withTicks[i + 3] / 255;
    if (Math.abs(without[i + 3] - withTicks[i + 3]) > 8 || Math.abs(without[i] * a0 - withTicks[i] * a1) > 8 || Math.abs(without[i + 1] * a0 - withTicks[i + 1] * a1) > 8
      || Math.abs(without[i + 2] * a0 - withTicks[i + 2] * a1) > 8) changed++; }
  h.debug.noTicks = false; h.redraw();
  return {ticks, venues: window.__vc.venues.items.length, changedPixels: changed, big: h.mapOpen, size: [c.width, c.height]}; }"""


@v6_restores
def verify_v6_minimap(eng, url, control=False, shots=None):
    """C8.7: every venue is a tick on the small and the big map (pixels that change when the ticks are drawn)."""
    v6_open_page(eng, url, '#explore/archive')
    page = eng.page
    small = v6_ev(page, V6_TICK_PIXELS, control)
    page.keyboard.press('Tab'); eng.wait(.4)
    big = v6_ev(page, V6_TICK_PIXELS, control)
    if shots and not control:
        eng.screenshot(shots / 'map-big.png')
    passed = all(m['venues'] > 0 and m['ticks'] == m['venues'] and m['changedPixels'] >= m['venues'] for m in (small, big)) and big['big']
    return {'passed': passed, 'control': control, 'small': small, 'big': big, 'pageErrors': eng.errors[:5]}


# ------------------------------------------------------------------ gate 6: photo mode
V6_VISIBLE_UI = r"""() => {
  const out = [];
  const effective = el => { let o = 1; for (let n = el; n && n.nodeType === 1; n = n.parentElement) { const s = getComputedStyle(n);
    if (s.display === 'none' || s.visibility === 'hidden') return 0; o *= parseFloat(s.opacity); } return o; };
  for (const el of document.body.querySelectorAll('*')) {
    if (el.closest('#stage') || el.tagName === 'SCRIPT' || el.tagName === 'STYLE') continue;
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1 || r.right < 0 || r.bottom < 0 || r.left > innerWidth || r.top > innerHeight) continue;
    const s = getComputedStyle(el), paints = (el.childNodes.length && [...el.childNodes].some(c => c.nodeType === 3 && c.textContent.trim())) ||
      el.tagName === 'CANVAS' || el.tagName === 'BUTTON' || el.tagName === 'INPUT' || s.backgroundColor !== 'rgba(0, 0, 0, 0)' || parseFloat(s.borderTopWidth) > 0;
    if (!paints) continue;
    const o = effective(el);
    if (o > .01) out.push({id: el.id, cls: el.className && String(el.className), tag: el.tagName, opacity: +o.toFixed(2), text: (el.textContent || '').trim().slice(0, 30)});
  }
  return out;
}"""


@v6_restores
def verify_v6_photo(eng, url, control=False):
    """C8.8: people, vehicles, sky and lasers freeze while the music clock runs; every UI element hides; the shot
    starts behind you with you in it; the fly camera never enters a footprint; Save image downloads a PNG at twice
    the canvas CSS size."""
    v6_open_page(eng, url, '#explore/downtown')
    page = eng.page
    before_ui = v6_ev(page, V6_VISIBLE_UI)
    page.keyboard.press('KeyP')
    eng.wait(.5)
    if control:
        # Positive control: photo mode runs but the page never hides its UI (the body class is dropped).
        v6_ev(page, "() => { document.body.classList.remove('photo'); }")
    shot = """() => { const v = window.__vc, q = window.__qa, sum = a => { let t = 0; for (let i = 0; i < a.length; i += 7) t += a[i] * (i % 13 + 1); return t; };
      const c = v.camera.position, p = v.explore.player;
      return {people: sum(v.crowd.parts.torso.instanceMatrix.array), cars: v.cars.types ? Object.values(v.cars.types).reduce((t, m) => t + sum(m.instanceMatrix.array), 0) : 0,
        sky: v.rave.uniforms.uTime.value, lasers: sum(v.rave.lasers.instanceMatrix.array), beats: v.beat.now().totalBeats, frozen: v.explore.frozen, photo: v.explore.photo.active,
        cameraToYou: Math.hypot(c.x - p.x, c.y - p.y, c.z - p.z), youDrawn: q.avatarDrawn()}; }"""
    a = v6_ev(page, shot)
    # Fly forward and up for 1.5 s: the camera moves, never into a footprint.
    v6_ev(page, """() => { const v = window.__vc, q = window.__qa; q.sample(() => { const c = v.camera.position; return {x: c.x, y: c.y, z: c.z, blocked: v.pointBlocked(c, 0)}; }); }""")
    page.keyboard.down('KeyW'); eng.wait(1.5); page.keyboard.up('KeyW')
    fly = v6_ev(page, '() => window.__qa.stop()')
    eng.wait(2.8)   # the photo bar fades after 2.5 s without input
    b = v6_ev(page, shot)
    ui = v6_ev(page, V6_VISIBLE_UI)
    download = None
    try:
        page.mouse.move(10, 10)
        eng.wait(.3)
        with page.expect_download(timeout=15000) as info:
            page.click('#ex-save')
        d = info.value
        raw = Path(d.path()).read_bytes()
        width, height = struct.unpack('>II', raw[16:24]) if raw[:8] == b'\x89PNG\r\n\x1a\n' else (0, 0)
        css = v6_ev(page, '() => ({w: window.__vc.renderer.domElement.clientWidth, h: window.__vc.renderer.domElement.clientHeight})')
        download = {'name': d.suggested_filename, 'png': raw[:8] == b'\x89PNG\r\n\x1a\n', 'width': width, 'height': height,
                    'bytes': len(raw), 'twiceCss': width == 2 * css['w'] and height == 2 * css['h']}
    except Exception as error:
        download = {'error': str(error)}
    frozen = a['people'] == b['people'] and a['cars'] == b['cars'] and a['sky'] == b['sky'] and a['lasers'] == b['lasers']
    moved = math.hypot(fly[-1]['x'] - fly[0]['x'], fly[-1]['z'] - fly[0]['z']) if len(fly) > 1 else 0
    passed = (a['photo'] and a['frozen'] and frozen and b['beats'] > a['beats'] + 4 and not ui and len(before_ui) > 3
              and a['youDrawn'] and a['cameraToYou'] < 2.5
              and moved > .5 and not any(f['blocked'] for f in fly) and bool(download.get('png')) and download.get('twiceCss')
              and download.get('name') == 'vault-city.png')
    return {'passed': passed, 'control': control, 'uiBefore': len(before_ui), 'uiVisibleInPhoto': ui[:6], 'frozen': frozen,
            'musicBeatsAdvanced': round(b['beats'] - a['beats'], 2), 'startCameraToYou': round(a['cameraToYou'], 3), 'youDrawn': a['youDrawn'],
            'flyMoved': round(moved, 2), 'flyBlockedFrames': sum(1 for f in fly if f['blocked']), 'download': download, 'pageErrors': eng.errors[:5]}


# ------------------------------------------------------------------ gate 7: deep links
V6_DEEP_LINKS = {
    '#explore/downtown': """() => { const v = window.__vc, e = v.explore, s = e.design.stages.find(s => s.district === 'working');
        return e.active && !e.photo.active && v.state.ride < 0 && v.audio.desired === 'working' && Math.hypot(e.player.x - s.x, e.player.z + s.y) < s.r
          && location.hash === '#explore/downtown'; }""",
    '#explore/prasma-campus': """() => { const v = window.__vc, e = v.explore; return e.active && v.audio.desired === 'prasma'; }""",
    '#ride': """() => { const v = window.__vc; return v.state.ride >= 0 && !v.explore.active; }""",
    '#ride/archive': """() => { const v = window.__vc; return v.state.ride >= 0 && v.routes[v.state.ride].district === 'episodic' && !v.explore.active; }""",
    '#photo': """() => { const v = window.__vc, e = v.explore, c = v.camera.position, p = e.player;
        return e.active && e.photo.active && e.frozen && document.body.classList.contains('photo')
          && Math.hypot(c.x - p.x, c.y - p.y, c.z - p.z) < 2.5 && window.__qa.avatarDrawn(); }""",
}
V6_ANY_MODE = """() => { const v = window.__vc; return v.explore.active || v.state.ride >= 0 || v.explore.photo.active; }"""


@v6_restores
def verify_v6_deep_links(eng, url, control=False):
    """C8.9: #explore/<district-slug>, #ride, #ride/<district-slug> and #photo each open their mode (#photo behind
    you, with you in the shot); nothing else does."""
    results = {}
    links = {'#explore/nowhere': V6_ANY_MODE, '#flyover': V6_ANY_MODE, '#photo/downtown': V6_ANY_MODE} if control else V6_DEEP_LINKS
    for hash_, check in links.items():
        v6_open_page(eng, url, hash_)
        results[hash_] = bool(v6_ev(eng.page, check))
    return {'passed': all(results.values()), 'control': control, 'links': results, 'pageErrors': eng.errors[:5]}


# ------------------------------------------------------------------ gate 8: touch joystick at 375 px
def verify_v6_touch(browser, url, control=False, shots=None):
    """C8.2: at 375 px the Explore button, the joystick and the buttons fit; a left-thumb drag moves the avatar forward."""
    ctx = browser.new_context(viewport={'width': 375, 'height': 812}, device_scale_factor=2, has_touch=True, is_mobile=True)
    page = ctx.new_page()
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    try:
        page.goto(url, wait_until='domcontentloaded')
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline and not v6_ev(page, 'Boolean(window.__vc)'):
            page.wait_for_timeout(100)
        page.wait_for_timeout(1500)
        page.tap('#explore')
        page.wait_for_timeout(800)
        layout = v6_ev(page, """() => { const q = s => { const el = document.querySelector(s); if (!el) return null; const r = el.getBoundingClientRect();
            return {left: r.left, right: r.right, top: r.top, bottom: r.bottom, shown: getComputedStyle(el).display !== 'none' && !el.closest('[hidden]')}; };
          return {active: window.__vc.explore.active, tier: window.__vc.tier.current, overflow: document.documentElement.scrollWidth > innerWidth,
            buttons: q('#ex-buttons'), pad: q('#ex-pad'), map: q('#hud-map'), room: q('#hud-room'), bar: q('.bar')}; }""")
        start = v6_ev(page, '() => { const e = window.__vc.explore; return {x: e.player.x, z: e.player.z, yaw: e.look.yaw}; }')
        cdp = ctx.new_cdp_session(page)
        x0, y0 = (300, 560) if control else (80, 560)
        cdp.send('Input.dispatchTouchEvent', {'type': 'touchStart', 'touchPoints': [{'x': x0, 'y': y0, 'id': 1}]})
        for k in range(1, 9):
            cdp.send('Input.dispatchTouchEvent', {'type': 'touchMove', 'touchPoints': [{'x': x0, 'y': y0 - k * 7, 'id': 1}]})
            page.wait_for_timeout(16)
        page.wait_for_timeout(1500)
        mid = v6_ev(page, '() => { const e = window.__vc.explore; return {x: e.player.x, z: e.player.z}; }')
        cdp.send('Input.dispatchTouchEvent', {'type': 'touchEnd', 'touchPoints': []})
        page.wait_for_timeout(300)
        dx, dz = mid['x'] - start['x'], mid['z'] - start['z']
        dist = math.hypot(dx, dz)
        forward = (dx * math.sin(start['yaw']) + dz * math.cos(start['yaw'])) / dist if dist > 1e-6 else 0
        page.tap('#ex-buttons [data-a="bike"]')
        page.wait_for_timeout(400)
        on_bike = v6_ev(page, '() => window.__vc.explore.player.onBike')
        if shots:
            page.screenshot(path=str(shots / ('touch-375' + ('-control' if control else '') + '.png')))
        # The Leave button in the top bar must still take a tap above the touch layer.
        page.tap('#explore', timeout=5000)
        page.wait_for_timeout(400)
        left = v6_ev(page, '() => !window.__vc.explore.active')
        fits = all(layout[k] and layout[k]['shown'] and layout[k]['left'] >= 0 and layout[k]['right'] <= 375 for k in ('buttons', 'map', 'room', 'bar'))
        passed = layout['active'] and not layout['overflow'] and fits and dist > .4 and forward > .8 and on_bike and left
        return {'passed': passed, 'control': control, 'layout': layout, 'moved': round(dist, 3), 'forwardCosine': round(forward, 3),
                'bikeButton': on_bike, 'leaveTap': left, 'pageErrors': errors[:5]}
    finally:
        ctx.close()


# ------------------------------------------------------------------ gate 9: a mocked gamepad
@v6_restores
def verify_v6_gamepad(eng, url, control=False):
    """C8.2 and C13.4: a standard-mapping gamepad drives the avatar (left stick), summons the bike (X) and throttles
    it (RT); navigator.getGamepads (a new list per call) is polled only between gamepadconnected and a disconnect."""
    v6_open_page(eng, url, '#explore/downtown')
    page = eng.page
    mapping = '' if control else 'standard'
    # No pad yet: count the calls explore makes for one second (it must make none).
    v6_ev(page, """(mapping) => { const buttons = Array.from({length: 17}, () => ({pressed: false, value: 0}));
      const pad = {id: 'qa mock pad', index: 0, connected: true, mapping, axes: [0, 0, 0, 0], buttons, timestamp: 0};
      window.__qaPad = pad; window.__qaPadCalls = 0; window.__qaPadList = [];
      Object.defineProperty(navigator, 'getGamepads', {value: () => { window.__qaPadCalls++; return window.__qaPadList; }, configurable: true}); }""", mapping)
    eng.wait(1)
    idle_calls = v6_ev(page, '() => window.__qaPadCalls')
    # The pad arrives: the browser announces it, then the left stick pushes forward.
    v6_ev(page, "() => { window.__qaPadList = [window.__qaPad]; window.__qaPad.axes[1] = -1; window.dispatchEvent(new Event('gamepadconnected')); window.__qaPadCalls = 0; }")
    start = v6_ev(page, '() => { const e = window.__vc.explore; return {x: e.player.x, z: e.player.z, yaw: e.look.yaw}; }')
    eng.wait(1.5)
    mid = v6_ev(page, '() => { const e = window.__vc.explore; return {x: e.player.x, z: e.player.z, calls: window.__qaPadCalls}; }')
    v6_ev(page, "() => { const p = window.__qaPad; p.axes[1] = 0; p.buttons[2] = {pressed: true, value: 1}; }")
    eng.wait(.2)
    v6_ev(page, "() => { const p = window.__qaPad; p.buttons[2] = {pressed: false, value: 0}; p.buttons[7] = {pressed: true, value: 1}; }")
    eng.wait(v6_beat_seconds(eng) * 4 + .8)
    bike = v6_ev(page, '() => { const e = window.__vc.explore; return {onBike: e.player.onBike, speed: e.bike.speed}; }')
    # The pad leaves: polling stops again.
    v6_ev(page, "() => { const p = window.__qaPad; p.buttons[7] = {pressed: false, value: 0}; p.connected = false; window.__qaPadList = [null]; window.dispatchEvent(new Event('gamepaddisconnected')); }")
    eng.wait(.2)
    v6_ev(page, '() => { window.__qaPadCalls = 0; }')
    eng.wait(1)
    after_calls = v6_ev(page, '() => window.__qaPadCalls')
    dx, dz = mid['x'] - start['x'], mid['z'] - start['z']
    dist = math.hypot(dx, dz)
    forward = (dx * math.sin(start['yaw']) + dz * math.cos(start['yaw'])) / dist if dist > 1e-6 else 0
    polled = mid['calls'] > 30
    passed = dist > .4 and forward > .8 and bike['onBike'] and bike['speed'] > 1 and idle_calls == 0 and polled and after_calls == 0
    return {'passed': passed, 'control': control, 'mapping': mapping, 'callsWithoutPad': idle_calls, 'callsWhileConnected': mid['calls'],
            'callsAfterDisconnect': after_calls, 'moved': round(dist, 3), 'forwardCosine': round(forward, 3), 'bike': bike, 'pageErrors': eng.errors[:5]}


# ------------------------------------------------------------------ gate 10: keys, the world noticing you, reduced motion
@v6_restores
def verify_v6_extras(eng, url, control=False):
    """C8.1 (Esc leaves, arrow-key timeline shortcuts off, F toggles), C8.6 (leaving returns to the Skyline),
    C8.10 (heads turn within 1.5, dancers cheer as a fast bike passes), R hook, B9 (reduced motion)."""
    out = {}
    v6_open_page(eng, url)
    page = eng.page
    page.keyboard.press('KeyF'); eng.wait(.6)
    out['fEnters'] = v6_ev(page, '() => window.__vc.explore.active')
    week = v6_ev(page, '() => window.__vc.state.t')
    page.keyboard.press('ArrowLeft'); page.keyboard.press('ArrowLeft'); eng.wait(.3)
    out['arrowsLeaveTimeline'] = v6_ev(page, '() => window.__vc.state.t') == week
    page.keyboard.press('Tab'); eng.wait(.2)
    page.keyboard.press('Escape'); eng.wait(.3)
    out['escClosesMapFirst'] = v6_ev(page, '() => window.__vc.explore.active && !window.__vc.hud.mapOpen')
    page.keyboard.press('Escape'); eng.wait(.5)
    out['escLeaves'] = v6_ev(page, '() => !window.__vc.explore.active')
    out['skylineAfterLeave'] = v6_ev(page, "() => window.__vc.audio.desired === 'skyline' && !document.body.classList.contains('exploring')")
    # Heads turn: stand among the Downtown dancers and compare head and torso yaw of the people within 1.5.
    v6_ev(page, "() => window.__vc.explore.openHash('#explore/downtown')")
    eng.wait(1.2)
    page.keyboard.down('KeyW'); eng.wait(.7); page.keyboard.up('KeyW'); eng.wait(.4)
    # The control measures dancers 2 to 3.4 away, who must not be turned: it shows the check can read zero.
    turned = v6_ev(page, """(control) => { const v = window.__vc, e = v.explore, c = v.crowd, p = e.player, r0 = control ? 2 : .2, r1 = control ? 3.4 : 1.4;
      const yawOf = (arr, i) => Math.atan2(arr[i * 16 + 8], arr[i * 16 + 10]);
      let near = 0, turned = 0;
      c.people.forEach((q, i) => { if (q.kind !== 1 || !c.isVisible(i, q)) return;
        const d = Math.hypot(q.x - p.x, q.z - p.z); if (d > r1 || d < r0) return; near++;
        const a = yawOf(c.parts.head.instanceMatrix.array, i) - yawOf(c.parts.torso.instanceMatrix.array, i);
        if (Math.abs(a - Math.round(a / (2 * Math.PI)) * 2 * Math.PI) > .08) turned++; });
      return {near, turned}; }""", control)
    out['headsTurn'] = turned
    # Cheer: ride past the Downtown dance floor fast, count dancers whose cheer beat was set.
    v6_ev(page, """() => { const e = window.__vc.explore; e.toggleBike(); }""")
    eng.wait(v6_beat_seconds(eng) * 4 + .2)
    cheer = v6_ev(page, """(control) => new Promise(done => { const v = window.__vc, e = v.explore, s = e.design.stages.find(s => s.district === 'working');
      const x0 = s.x - 1.5, z0 = -s.y;
      e.teleport(x0, z0 + .2, Math.PI / 2, s.z);
      Object.assign(e.bike, {speed: control ? 2 : 5.5});
      e.pilot = input => { input.throttle = control ? 0 : 1; input.steer = 0; input.fast = false; if (control) e.bike.speed = 2; };
      setTimeout(() => { e.pilot = null; const n = v.crowd.people.filter(q => q.kind === 1 && q.cheerAt !== undefined).length; done({cheered: n, speedAtEnd: e.bike.speed}); }, 700); })""", control)
    out['cheer'] = cheer
    # R hook: with no tour installed, R leaves explore for Ride along on the district you stand in.
    page.keyboard.press('KeyE'); eng.wait(.2)
    page.keyboard.press('KeyR'); eng.wait(.6)
    out['rHook'] = v6_ev(page, "() => { const v = window.__vc; return !v.explore.active && v.state.ride >= 0 && v.routes[v.state.ride].district === 'working'; }")
    # Absent buildings do not collide (C8.4): at week 0 a later note's footprint is open ground, a week-0 note's is not.
    absent = v6_ev(page, """() => { const v = window.__vc, e = v.explore; v.updateWeek(0);
      const later = v.nodes.find(n => n.state === 'absent'), early = v.nodes.find(n => n.state !== 'absent' && n.created !== null);
      if (!later || !early) return {laterOpen: false, reason: 'no absent or no present note at week 0'};
      const zl = later.district, ze = early.district;
      const yl = e.surfaceAt(later.x + later.w, -later.y, 5), ye = e.surfaceAt(early.x + early.w, -early.y, 5);
      const r = {laterDistrict: zl, earlyDistrict: ze, laterOpen: e.surfaceAt(later.x, -later.y, yl ?? 1) !== null, earlyBlocked: e.surfaceAt(early.x, -early.y, ye ?? 1) === null};
      v.updateWeek(12); r.laterBlockedAtWeek12 = e.surfaceAt(later.x, -later.y, yl ?? 1) === null; return r; }""")
    out['absentBuildings'] = absent
    # Reduced motion: explore works, no speed lines or FOV kick. v6_restore reloads without it afterwards.
    eng.page.emulate_media(reduced_motion='reduce')
    v6_open_page(eng, url, '#explore/compass')
    rm = v6_ev(page, """() => new Promise(done => { const v = window.__vc, e = v.explore, b = e.design.bridges[0]; e.toggleBike();
      const a = b.points[2], c = b.points[5]; e.teleport(a[0], -a[1], Math.atan2(c[0] - a[0], -c[1] + a[1]), a[2]); window.__qa.follow(b.points, {boost: true});
      setTimeout(() => { e.pilot = null; done({speed: e.bike.speed, fov: v.camera.fov, fringe: e.bikeKit.fringe.enabled, reduced: matchMedia('(prefers-reduced-motion: reduce)').matches}); }, 3500); })""")
    out['reducedMotion'] = rm
    passed = (out['fEnters'] and out['arrowsLeaveTimeline'] and out['escClosesMapFirst'] and out['escLeaves'] and out['skylineAfterLeave']
              and turned['near'] > 0 and turned['turned'] > 0 and cheer['cheered'] > 0 and out['rHook'] and absent.get('laterOpen') and absent.get('earlyBlocked') and absent.get('laterBlockedAtWeek12')
              and rm['reduced'] and rm['speed'] > 4 and abs(rm['fov'] - 64) < .5 and not rm['fringe'])
    return {'passed': passed, 'control': control, **out, 'pageErrors': eng.errors[:5]}


# ------------------------------------------------------------------ sound-off dance gate with a zero-energy control
@v6_restores
def verify_v6_silent_dance(eng, url, control=False):
    """Stage dancers keep a small beat pose with Sound off. Zeroing the silent scale must fail."""
    v6_open_page(eng, url)
    page = eng.page
    v6_ev(page, '() => window.__vc.updateWeek(12)')
    if control:
        v6_ev(page, '() => { window.__vc.crowd.debug.silentDanceScale = 0; }')
    eng.wait(.5)
    indices = v6_ev(page, """() => {const c=window.__vc.crowd,a=c.parts.head.instanceMatrix.array,out=[];
      for(let i=0;i<c.people.length&&out.length<24;i++){const p=c.people[i],o=i*16;
        if(p.kind===1&&p.style==='bounce'&&c.isVisible(i,p)&&Math.hypot(a[o],a[o+1],a[o+2])>1e-4)out.push(i);}
      return out;}""")
    lo, hi = [float('inf')] * len(indices), [float('-inf')] * len(indices)
    start = time.monotonic()
    while time.monotonic() - start < 1.8:
        ys = v6_ev(page, """(ids) => {const a=window.__vc.crowd.parts.head.instanceMatrix.array;
          return ids.map(i=>a[i*16+13]);}""", indices)
        for k, y in enumerate(ys):
            lo[k], hi[k] = min(lo[k], y), max(hi[k], y)
        eng.wait(.1)
    state = v6_ev(page, """(ids) => {const v=window.__vc,c=v.crowd;
      return {soundOff:!v.audio.enabled,reduced:matchMedia('(prefers-reduced-motion: reduce)').matches,
        ratio:ids.length?c.dancerEnergy(c.people[ids[0]])/c.people[ids[0]].energy:null};}""", indices)
    motion = {**state, 'count': len(indices), 'motion': max([0] + [b - a for a, b in zip(lo, hi)])}
    return {'passed': motion['soundOff'] and not motion['reduced'] and motion['count'] > 0
            and motion['ratio'] is not None and .45 <= motion['ratio'] <= .55 and motion['motion'] >= .001,
            'control': control, 'motion': motion, 'pageErrors': eng.errors[:5]}


# ------------------------------------------------------------------ gate 11: ring curbs and bridge ends
V6_WALKABLE = """() => { const v = window.__vc, e = v.explore, D = e.design, S = e.surfaces;
  const out = {districts: [], bridgeEnds: []};
  for (const [d, p] of Object.entries(e.plateaus)) {
    if (p.shape !== 'disc') continue;
    let ring = null, spread = Infinity;
    for (const r of D.routes) { if (r.district !== d || r.points.length < 8) continue;
      const l = r.points.map(q => Math.hypot(q[0] - p.cx, q[1] - p.cy)), m = l.reduce((a, b) => a + b, 0) / l.length;
      const s = Math.sqrt(l.reduce((a, b) => a + (b - m) ** 2, 0) / l.length) / m; if (s < spread) { spread = s; ring = {r, radius: m}; } }
    if (!ring || spread > .04) { out.districts.push({d, ring: false}); continue; }
    // March from the ring's centre line to 0.3 inside the rim at 24 angles: the ground may be a road, a fillet,
    // a stage deck, a gangway, the plateau or a building, never the void or water.
    const angles = []; let voids = 0;
    for (let k = 0; k < 24; k++) { const a = k / 24 * Math.PI * 2; let y = ring.r.z, bad = null;
      for (let rr = ring.radius; rr >= p.rx - .3; rr -= .02) { const lx = p.cx + Math.cos(a) * rr, ly = p.cy + Math.sin(a) * rr;
        const ok = S.probe(lx, -ly, y), kind = S.hit.kind; if (ok) y = S.hit.h; else if (kind !== S.K.building) { bad = {rr: +rr.toFixed(3), kind}; break; } }
      if (bad) { voids++; angles.push({a: +a.toFixed(3), ...bad}); } }
    out.districts.push({d, rim: p.rx, ringRadius: +ring.radius.toFixed(3), voidAngles: voids, first: angles[0] || null});
  }
  // Each bridge end, continued 0.1 to 1.5 past its last point along its direction, lands on ground (or a building).
  for (const b of D.bridges || []) for (const [i, j] of [[b.points.length - 1, b.points.length - 2], [0, 1]]) {
    const a = b.points[i], c = b.points[j], dx = a[0] - c[0], dy = a[1] - c[1], l = Math.hypot(dx, dy) || 1; let y = a[2], bad = null;
    for (let t = .1; t <= 1.5001; t += .1) { const lx = a[0] + dx / l * t, ly = a[1] + dy / l * t, ok = S.probe(lx, -ly, y), kind = S.hit.kind;
      if (ok) y = S.hit.h; else if (kind === S.K.building) break; else { bad = {t: +t.toFixed(2), kind}; break; } }
    out.bridgeEnds.push({bridge: b.name, end: i ? 'last' : 'first', bad});
  }
  return out; }"""


@v6_restores
def verify_v6_walkable(eng, url, control=False):
    """C8.4: every disc plateau is walkable from its ring's inner curb (no invisible wall at a visible kerb, the Dome's
    ring sits at rim + 0.75), and every bridge end lands on ground; plus a real walk onto the Dome plateau."""
    v6_open_page(eng, url, '#explore/compass')
    page = eng.page
    if control:
        v6_ev(page, '() => { window.__vc.explore.debug.noRingCurb = true; }')
    sweep = v6_ev(page, V6_WALKABLE)
    # The real walk: on the disc plateau whose ring sits furthest out (the Dome), from the ring at the angle with the
    # most open ground, walk toward the centre for 3 s.
    widest = max((d for d in sweep['districts'] if d.get('ringRadius')), key=lambda d: d['ringRadius'] - d['rim'])
    walk = v6_ev(page, """(d) => new Promise(done => { const v = window.__vc, e = v.explore, S = e.surfaces, p = e.plateaus[d], D = e.design;
      let r = null, radius = 0, spread = Infinity;
      for (const q of D.routes) { if (q.district !== d || q.points.length < 8) continue;
        const l = q.points.map(t => Math.hypot(t[0] - p.cx, t[1] - p.cy)), m = l.reduce((a, b) => a + b, 0) / l.length;
        const s = Math.sqrt(l.reduce((a, b) => a + (b - m) ** 2, 0) / l.length) / m; if (s < spread) { spread = s; r = q; radius = m; } }
      let best = 0, open = -1;
      for (let k = 0; k < 36; k++) { const a = k / 36 * Math.PI * 2; let n = 0;
        for (let rr = radius; rr > 0; rr -= .05) { if (S.probe(p.cx + Math.cos(a) * rr, -(p.cy + Math.sin(a) * rr), p.z + .1) || S.hit.kind !== S.K.building) n++; else break; }
        if (n > open) { open = n; best = a; } }
      const x = p.cx + Math.cos(best) * radius, z = -(p.cy + Math.sin(best) * radius), yaw = Math.atan2(p.cx - x, -p.cy - z);
      const ok = e.teleport(x, z, yaw, r.z); e.setLook(yaw, -.1); let minR = Infinity;
      e.pilot = input => { input.my = 1; input.mx = 0; input.lookX = 0; input.lookY = 0; const q = e.player; minR = Math.min(minR, Math.hypot(q.x - p.cx, -q.z - p.cy)); };
      setTimeout(() => { e.pilot = null; const q = e.player; S.probe(q.x, q.z, q.y);
        done({district: d, ok, rim: p.rx, ring: +radius.toFixed(3), minRadius: +minR.toFixed(3), endKind: S.hit.kind, reachedPlateau: S.hit.kind === S.K.plateau || minR < p.rx - .3}); }, 3000); })""", widest['d'])
    bad_d = [d for d in sweep['districts'] if d.get('ring') is False or d.get('voidAngles')]
    bad_b = [b for b in sweep['bridgeEnds'] if b['bad']]
    passed = bool(sweep['districts']) and not bad_d and not bad_b and walk['ok'] and walk['reachedPlateau']
    return {'passed': passed, 'control': control, 'districts': sweep['districts'], 'badDistricts': [d['d'] for d in bad_d],
            'badBridgeEnds': bad_b[:6], 'bridgeEnds': len(sweep['bridgeEnds']), 'domeWalk': walk, 'pageErrors': eng.errors[:5]}


# ------------------------------------------------------------------ gate 12: play button, re-entry hash, photo framing
@v6_restores
def verify_v6_modes(eng, url, control=False):
    """C8.1 and C8.9: entering explore stops a playing timeline and its button says so; a new #explore link while
    exploring keeps its hash; #photo and photo from first person start behind you with you in the shot."""
    out = {}
    v6_open_page(eng, url)
    page = eng.page
    v6_ev(page, '() => window.__vc.updateWeek(0)')
    page.click('#play'); eng.wait(.3)
    out['playing'] = v6_ev(page, "() => [window.__vc.state.playing, document.getElementById('play').textContent]")
    page.keyboard.press('KeyF'); eng.wait(.4)
    if control:
        # Positive control: the label left as the old code left it.
        v6_ev(page, "() => { document.getElementById('play').textContent = 'Pause'; }")
    label = "() => { const s = window.__vc.state, t = document.getElementById('play').textContent; return {playing: s.playing, label: t, agrees: (t === 'Pause') === s.playing}; }"
    out['inExplore'] = v6_ev(page, label)
    page.keyboard.press('KeyF'); eng.wait(.4)
    out['afterLeave'] = v6_ev(page, label)
    play_ok = out['playing'][0] and out['inExplore']['agrees'] and not out['inExplore']['playing'] and out['afterLeave']['agrees']
    # A second #explore link while exploring moves you and keeps its hash.
    v6_ev(page, "() => { location.hash = '#explore/downtown'; }"); eng.wait(1)
    if control:
        v6_ev(page, "() => { const e = window.__vc.explore; location.hash = '#explore/archive'; }"); eng.wait(.1)
        v6_ev(page, "() => { const e = window.__vc.explore; e.leave(); e.enter('episodic'); }")   # the old leave-then-enter
    else:
        v6_ev(page, "() => { location.hash = '#explore/archive'; }")
    eng.wait(1.5)
    out['reentry'] = v6_ev(page, "() => ({hash: location.hash, active: window.__vc.explore.active, room: window.__vc.audio.desired})")
    hash_ok = out['reentry']['hash'] == '#explore/archive' and out['reentry']['active'] and out['reentry']['room'] == 'episodic'
    framing = """() => { const v = window.__vc, e = v.explore, c = v.camera.position, p = e.player;
      return {photo: e.photo.active, cameraToYou: +Math.hypot(c.x - p.x, c.y - p.y, c.z - p.z).toFixed(3), youDrawn: window.__qa.avatarDrawn()}; }"""
    # #photo from a fresh load.
    if control:
        v6_open_page(eng, url)
        v6_ev(page, "() => { window.__vc.explore.debug.photoAsIs = true; window.__vc.explore.openHash('#photo'); }")
    else:
        v6_open_page(eng, url, '#photo')
    eng.wait(.5)
    out['photoLink'] = v6_ev(page, framing)
    # Photo from first person.
    v6_open_page(eng, url, '#explore/downtown')
    if control:
        v6_ev(page, '() => { window.__vc.explore.debug.photoAsIs = true; }')
    page.keyboard.press('KeyV'); eng.wait(.4)
    page.keyboard.press('KeyP'); eng.wait(.5)
    out['photoFirstPerson'] = v6_ev(page, framing)
    frame_ok = all(f['photo'] and f['youDrawn'] and .3 < f['cameraToYou'] < 2.5 for f in (out['photoLink'], out['photoFirstPerson']))
    out['parts'] = {'playButton': play_ok, 'reentryHash': hash_ok, 'photoFraming': frame_ok}
    return {'passed': play_ok and hash_ok and frame_ok, 'control': control, **out, 'pageErrors': eng.errors[:5]}


# ------------------------------------------------------------------ all of the above, for qa_world --phase v6 and up
def verify_explore(eng, url, controls=False, shots=None):
    """Runs every V6 gate on the engine (touch on its own context from eng.browser); returns (report, checks). With
    controls, each gate also runs its positive control, which must fail. Leaves a fresh 1440x900 page (B10)."""
    v6_restore(eng, url)
    gates = (
        ('explore: random input never enters a footprint or the ground', lambda c: verify_v6_random_downtown(eng, url, control=c)),
        ('explore: over-the-shoulder camera stays above the ground', lambda c: verify_v6_camera_floor(eng, url, control=c, shots=shots)),
        ('explore: Memory Causeway continuous at boost, room turns on the far half', lambda c: verify_v6_causeway(eng, url, control='halves' if c else None)),
        ('explore: minimap fast travel', lambda c: verify_v6_fast_travel(eng, url, control=c)),
        ('explore: minimap venue ticks drawn', lambda c: verify_v6_minimap(eng, url, control=c, shots=shots)),
        ('explore: photo mode freezes the world and hides the UI', lambda c: verify_v6_photo(eng, url, control=c)),
        ('explore: deep links', lambda c: verify_v6_deep_links(eng, url, control=c)),
        ('explore: 375 px touch controls', lambda c: verify_v6_touch(eng.browser, url, control=c, shots=shots)),
        ('explore: standard gamepad, polled only while connected', lambda c: verify_v6_gamepad(eng, url, control=c)),
        ('explore: keys, heads, cheers, R hook, absent buildings, reduced motion', lambda c: verify_v6_extras(eng, url, control=c)),
        ('explore: low-energy dancing with sound off', lambda c: verify_v6_silent_dance(eng, url, control=c)),
        ('explore: ring curbs and bridge ends walkable', lambda c: verify_v6_walkable(eng, url, control=c)),
        ('explore: play button, re-entry hash, photo framing', lambda c: verify_v6_modes(eng, url, control=c)),
    )
    report, checks = {}, {}
    for name, gate in gates:
        item = {'run': gate(False)}
        checks[name] = bool(item['run']['passed'])
        if controls:
            item['control'] = gate(True)
            checks[name + ' (positive control goes red)'] = not item['control']['passed']
        report[name] = item
    return report, checks
# === qa_world block end ===


# Short names for the scratch scripts (shots_v6.py, flash_v6.py, ab_perf.py, perf_probe.py).
ev, wait_probe, open_page, beat_seconds, PRELUDE, S2_SPOT = v6_ev, v6_wait, v6_open_page, v6_beat_seconds, V6_PRELUDE, V6_S2_SPOT


# ------------------------------------------------------------------ S2 on foot (C13.3, V6 column), standalone
FRAME_TRACE = """(seconds) => {
  const v=window.__vc, rows=[], start=performance.now(); let last=start;
  const trace=window.__qaWorldFrames={done:false,rows,start};
  function tick(now) {
    rows.push([now-start,now-last,v.renderer.info.render.calls,v.renderer.info.render.triangles,v.tier?.current??null,
      Boolean(v.audio.enabled&&v.audio.ctx?.state==='running')]);
    last=now;
    if(now-start>=seconds*1000){trace.done=true;return;}
    requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
}"""


def summarize_frames(trace):
    """Same summary as qa_world.summarize_frames."""
    rows = trace['rows'][1:]
    values = sorted(row[1] for row in rows)
    mean = sum(values) / len(values)
    return {'seconds': trace['rows'][-1][0] / 1000, 'samples': len(values), 'fps': 1000 / mean, 'meanMs': mean,
            'p95Ms': values[math.ceil(len(values) * .95) - 1], 'maxMs': max(values),
            'maxDrawCalls': max(row[2] for row in rows), 'maxTriangles': max(row[3] for row in rows),
            'tiers': list(dict.fromkeys(row[4] for row in rows)), 'settledTier': rows[-1][4],
            'soundOnThroughout': all(row[5] for row in rows)}


def perf_pass(value):
    """Same budgets as qa_world.perf_pass (C13.3)."""
    return (value['fps'] >= 55 and value['p95Ms'] <= 22 and value['maxMs'] <= 100
            and value['maxDrawCalls'] <= 320 and value['maxTriangles'] <= 1_500_000 and value['soundOnThroughout'])


def measure_v6_s2(eng, url, control=False, seconds=60):
    """S2, V6 column: the on-foot avatar at the Downtown stage spot, over-the-shoulder camera, sound on, week 12."""
    eng.page.goto('about:blank')
    eng.goto(url)
    eng.ready()
    eng.wait(1.5)
    eng.click('#sound')
    wait_probe(eng.page, """() => {const a=window.__vc.audio;return a.enabled&&a.ctx?.state==='running'&&a.ready&&a.diagnostics.scheduledVoices>0;}""", 60)
    ev(eng.page, "() => { window.__vc.updateWeek(12); window.__vc.explore.openHash('#explore/downtown'); }")
    spot = ev(eng.page, S2_SPOT)
    wait_probe(eng.page, """() => {const a=window.__vc.audio;return !a.transition||a.ctx.currentTime>=a.transition.end;}""", 35)
    eng.wait(12 if not control else 3)
    eng.screenshot(SHOTS / ('s2-foot' + ('-control' if control else '') + '.png'))
    if control:
        ev(eng.page, "() => { (function burn(){ const t = performance.now(); while (performance.now() - t < 30) {} requestAnimationFrame(burn); })(); }")
    ev(eng.page, FRAME_TRACE, seconds)
    wait_probe(eng.page, '() => window.__qaWorldFrames.done', seconds + 20)
    trace = ev(eng.page, '() => window.__qaWorldFrames')
    (ROOT / 'renders' / 'qa' / (PREFIX + '-s2' + ('-control' if control else '') + '-frames.json')).write_text(json.dumps(trace), encoding='utf-8')
    metrics = summarize_frames(trace)
    tier_pass = bool(metrics['tiers']) and all(t is not None and t >= 2 for t in metrics['tiers'])
    ev(eng.page, '() => { const e = window.__vc.explore; if (e.active) e.leave(); }')
    return {'passed': perf_pass(metrics) and tier_pass and spot['ok'], 'control': control, 'spot': spot, 'metrics': metrics,
            'numericBudgetPass': perf_pass(metrics), 'settledTierPass': tier_pass, 'pageErrors': eng.errors[:5]}


# ------------------------------------------------------------------ S3 setup and positive control for the V6 performance scene
@v6_restores
def verify_v6_s3_mode(eng, url, control=False):
    v6_open_page(eng, url)
    setup = v6_ev(eng.page, V6_S3_SETUP, control)
    eng.wait(v6_beat_seconds(eng) * 4 + 9)
    telemetry = v6_ev(eng.page, "() => window.__qaS3")
    return {'passed': (setup['ok'] and setup['onBike'] and telemetry['deckMs'] >= 4000
                       and telemetry['boostDeckMs'] >= 2000 and telemetry['laps'] >= 1),
            'setup': setup, 'telemetry': telemetry, 'pageErrors': eng.errors[:5]}


# ------------------------------------------------------------------ runner
GATES = ['random', 'camfloor', 'causeway', 'fasttravel', 'minimap', 'photo', 'deeplinks', 'touch', 'gamepad', 'extras', 'silentdance', 'walkable', 'modes', 'perf', 's3mode']


def run(names, controls=True, url=URL, prefix=PREFIX):
    global PREFIX, SHOTS
    if not prefix or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in prefix):
        raise SystemExit('--prefix must contain only letters, digits, hyphens or underscores')
    PREFIX = prefix
    output = ROOT / 'renders' / 'qa'
    output.mkdir(parents=True, exist_ok=True)
    SHOTS = output / (PREFIX + '-explore-shots')
    SHOTS.mkdir(parents=True, exist_ok=True)
    report = {'url': url, 'started': time.strftime('%Y-%m-%d %H:%M:%S'), 'gates': {}}
    path = output / (PREFIX + '-explore-report.json')
    with Engine(width=1440, height=900, timeout=90) as eng:
        def fresh():
            eng.errors.clear()
        for name in names:
            print('gate', name, flush=True)
            fresh()
            if name == 'random':
                item = {'run': verify_v6_random_downtown(eng, url)}
                if controls: fresh(); item['control'] = verify_v6_random_downtown(eng, url, control=True)
            elif name == 'camfloor':
                item = {'run': verify_v6_camera_floor(eng, url, shots=SHOTS)}
                if controls: fresh(); item['control'] = verify_v6_camera_floor(eng, url, control=True, shots=SHOTS)
            elif name == 'causeway':
                item = {'run': verify_v6_causeway(eng, url)}
                if controls:
                    fresh(); item['controlHalves'] = verify_v6_causeway(eng, url, control='halves')
                    fresh(); item['controlDecks'] = verify_v6_causeway(eng, url, control='decks')
            elif name == 'fasttravel':
                item = {'run': verify_v6_fast_travel(eng, url)}
                fresh(); item['runBigMap'] = verify_v6_fast_travel(eng, url, big_map=True)
                if controls:
                    fresh(); item['control'] = verify_v6_fast_travel(eng, url, control=True)
                    fresh(); item['controlBigMap'] = verify_v6_fast_travel(eng, url, control=True, big_map=True)
            elif name == 'minimap':
                item = {'run': verify_v6_minimap(eng, url, shots=SHOTS)}
                if controls: fresh(); item['control'] = verify_v6_minimap(eng, url, control=True)
            elif name == 'photo':
                item = {'run': verify_v6_photo(eng, url)}
                if controls: fresh(); item['control'] = verify_v6_photo(eng, url, control=True)
            elif name == 'deeplinks':
                item = {'run': verify_v6_deep_links(eng, url)}
                if controls: fresh(); item['control'] = verify_v6_deep_links(eng, url, control=True)
            elif name == 'touch':
                item = {'run': verify_v6_touch(eng.browser, url, shots=SHOTS)}
                if controls: item['control'] = verify_v6_touch(eng.browser, url, control=True, shots=SHOTS)
            elif name == 'gamepad':
                item = {'run': verify_v6_gamepad(eng, url)}
                if controls: fresh(); item['control'] = verify_v6_gamepad(eng, url, control=True)
            elif name == 'extras':
                item = {'run': verify_v6_extras(eng, url)}
                if controls: fresh(); item['control'] = verify_v6_extras(eng, url, control=True)
            elif name == 'silentdance':
                item = {'run': verify_v6_silent_dance(eng, url)}
                if controls: fresh(); item['control'] = verify_v6_silent_dance(eng, url, control=True)
            elif name == 'walkable':
                item = {'run': verify_v6_walkable(eng, url)}
                if controls: fresh(); item['control'] = verify_v6_walkable(eng, url, control=True)
            elif name == 'modes':
                item = {'run': verify_v6_modes(eng, url)}
                if controls: fresh(); item['control'] = verify_v6_modes(eng, url, control=True)
            elif name == 'perf':
                item = {'run': measure_v6_s2(eng, url)}
                if controls: fresh(); item['control'] = measure_v6_s2(eng, url, control=True, seconds=15)
            elif name == 's3mode':
                item = {'run': verify_v6_s3_mode(eng, url)}
                if controls: fresh(); item['control'] = verify_v6_s3_mode(eng, url, control=True)
            else:
                raise SystemExit('unknown gate ' + name)
            controls_red = all(not v['passed'] for k, v in item.items() if k.startswith('control'))
            item['passed'] = all(v['passed'] for k, v in item.items() if k.startswith('run'))
            item['controlsWentRed'] = controls_red if any(k.startswith('control') for k in item) else None
            item['finished'] = time.strftime('%Y-%m-%d %H:%M:%S')
            report['gates'][name] = item
            print(' ', name, 'PASS' if item['passed'] else 'FAIL', '| controls red:', item['controlsWentRed'], flush=True)
            path.write_text(json.dumps(report, indent=1), encoding='utf-8')
    report['finished'] = time.strftime('%Y-%m-%d %H:%M:%S')
    report['failedGates'] = [name for name, item in report['gates'].items()
                             if not item['passed'] or (controls and item['controlsWentRed'] is not True)]
    report['passed'] = not report['failedGates']
    path.write_text(json.dumps(report, indent=1), encoding='utf-8')
    print(json.dumps({'passed': report['passed'], 'failedGates': report['failedGates'],
                      'report': str(path.relative_to(ROOT))}), flush=True)
    return report


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    url = next((a.split('=', 1)[1] for a in sys.argv[1:] if a.startswith('--url=')), URL)
    prefix = next((a.split('=', 1)[1] for a in sys.argv[1:] if a.startswith('--prefix=')), PREFIX)
    report = run(args or GATES, controls='--no-controls' not in sys.argv, url=url, prefix=prefix)
    raise SystemExit(0 if report['passed'] else 1)
