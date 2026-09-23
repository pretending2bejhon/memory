// Twelve rooms written in Strudel (viewer/rooms/*.strudel), played on one 140 BPM transport.
// Strudel makes every sound; this file owns the clock, the room buses, the crossfades and the
// timeline mix. Each Strudel layer plays on its own orbit, and every orbit is routed into its
// room bus instead of the speakers, so the fades and the timeline shape real samples and synths.
// Strudel is AGPL-3.0-or-later (https://codeberg.org/uzu/strudel); so is this page.
const cityAudio = (() => {
  'use strict';
  const STRUDEL_URL = 'https://cdn.jsdelivr.net/npm/@strudel/web@1.3.0/dist/index.mjs';
  const SAMPLE_CDN = 'https://strudel.b-cdn.net';
  const DIRT_SAMPLES = 'https://raw.githubusercontent.com/tidalcycles/dirt-samples/master/strudel.json';
  const BPM = 140, SIXTEENTH = 60 / BPM / 4, BAR = SIXTEENTH * 16, CPS = BPM / 60 / 4;
  const EPS = 0.0001, SMOOTH = 0.25, LOOKAHEAD = 0.12;
  const thresholds = {kick: 0, hatC: .15, perc: .30, hatO: .45, stab: .60, clap: .75, pad: .90};
  const layerThresholds = {...thresholds, bass: .60, shaker: .15, woodblock: .30, clank: .30, blip: .30,
    arp: .30, bubble: .30, rim: .30, noise: .15, ride: .45, riser: .30, vox: .45};
  const ducked = new Set(['pad', 'stab', 'bass']), sustained = new Set(['pad', 'noise']);
  // Room changes follow Jhon's own mixing, measured from his REEF SESSIONS 002 set: every change
  // is phrase-locked; the outgoing kick and bass leave, a bass-free bridge carries the new room's
  // hats and percussion while a riser builds and a low-pass closes on the old room, the last beat
  // cuts to silence, and the new kick and bass slam in at full on the 1 of an eight-bar phrase.
  const PHRASE = 8, MIN_BRIDGE = 4, BRIDGE_LPF = 1500, LOW_LAYERS = ['kick', 'bass'];
  const ROOM_CODE = __CITY_ROOMS__;
  // What the transport and the mix need per room; the music itself lives in ROOM_CODE.
  const rooms = {
    core: {title: 'The Compass', root: 38, cycleBars: 32, withhold: 'hatO', low: ['kick', 'bass', 'pad'],
      fx: {lpf: 9000, delay: .08, reverb: .30, drive: .04, gain: .56}},
    episodic: {title: 'The Archive', root: 41, cycleBars: 32, withhold: 'perc',
      fx: {lpf: 2400, delay: .5, reverb: .35, drive: .08, gain: .72}},
    semantic: {title: 'The Library', root: 33, cycleBars: 32, withhold: 'bass',
      fx: {lpf: 7000, delay: .23, reverb: .6, drive: .03, gain: .6}},
    procedural: {title: 'The Works', root: 40, cycleBars: 32, withhold: 'rim',
      fx: {lpf: 10500, delay: .04, reverb: .08, drive: .35, gain: .9}},
    prospective: {title: 'The Yards', root: 43, cycleBars: 16, withhold: ['hatO', 'perc'],
      fx: {lpf: 8000, sweep: [1000, 8000], sweepBars: 8, delay: .2, reverb: .25, drive: .09, gain: .64}},
    working: {title: 'Downtown', root: 41, cycleBars: 32, withhold: 'hatO',
      fx: {lpf: 12000, delay: .16, reverb: .2, drive: .12, gain: 1}},
    jhon: {title: 'The Hills', root: 36, cycleBars: 32, withhold: 'shaker',
      fx: {lpf: 8000, delay: .13, reverb: .3, drive: .055, gain: .76}},
    prasma: {title: 'Prasma Campus', root: 45, cycleBars: 32, withhold: 'stab',
      fx: {lpf: 14000, delay: .05, reverb: .12, gated: .11, drive: .07, gain: .85}},
    branding: {title: 'Signal Row', root: 48, cycleBars: 32, withhold: 'blip',
      fx: {lpf: 10000, delay: .24, reverb: .25, drive: .08, gain: .9}},
    onebrain: {title: 'The Dome', root: 38, cycleBars: 32, withhold: 'arp',
      fx: {lpf: 9000, delay: .5, feedback: .5, reverb: .35, drive: .045, gain: .62}},
    reef: {title: 'The Reef', root: 31, cycleBars: 32, withhold: 'hatC',
      fx: {lpf: 500, lfo: {frequency: .05, min: 500, max: 3000}, delay: .30, reverb: .6, drive: .025, gain: .7}},
    inbox: {title: 'The Gate', root: 41, cycleBars: 32, withhold: null, low: ['kick', 'pad'],
      fx: {lpf: 4000, delay: .06, reverb: .5, drive: .02, gain: .5}}
  };
  for (const [id, room] of Object.entries(rooms)) Object.assign(room, {id, code: ROOM_CODE[id] || '', layers: layerNames(ROOM_CODE[id] || '')});
  rooms.skyline = {...rooms.working, id: 'skyline', title: 'Skyline', source: 'working',
    fx: {...rooms.working.fx, lpf: 1200, reverb: .45, gain: .5}};

  let ctx = null, analyser = null, compressor, clip, master, cut, noiseBuffer, delaySend, reverbSend, feedback, reverbGate;
  let riser = null;
  const graveyard = [];
  let enabled = false, desired = 'skyline', active = null, S = null, controller = null, loading = null;
  let outgoing = null, transition = null, timer = null, origin = 0, nextStep = 0, nextOrbit = 1;
  let preferred = 'off', state = 'off', rideHeading = null, pending = null, serial = 0, startToken = 0;
  const buses = [], listeners = new Set(), timeline = {}, waveCurves = new Map();
  const compiled = new Map(), orbitTargets = new Map(), preloaded = new Map();
  // Sample the device clock on the existing scheduler, outside the render loop.
  const outputClock = {contextTime: 0, performanceTime: 0, outputLatency: 0, timestamp: false};
  function sampleOutputClock() {
    outputClock.outputLatency = Number(ctx.outputLatency) || Number(ctx.baseLatency) || 0;
    const stamp = typeof ctx.getOutputTimestamp === 'function' ? ctx.getOutputTimestamp() : null;
    outputClock.timestamp = !!(stamp && stamp.performanceTime > 0 && Number.isFinite(stamp.contextTime));
    outputClock.contextTime = outputClock.timestamp ? stamp.contextTime : ctx.currentTime - outputClock.outputLatency;
    outputClock.performanceTime = outputClock.timestamp ? stamp.performanceTime : performance.now();
  }
  // One stable slot per event: the renderer consumes this without creating event objects.
  const hitRing = {capacity: 512, written: 0, read: 0, dropped: 0,
    slots: Array.from({length: 512}, () => ({room: '', layer: '', time: 0, gain: 0,
      sequence: -1, released: true, source: 'audio', effect: '', audibleAt: 0,
      releasedAt: 0, frame: 0, lateMs: 0}))};
  function recordHit(bus, layer, time, value) {
    const sequence = hitRing.written++, slot = hitRing.slots[sequence % hitRing.capacity];
    if (!slot.released && sequence - hitRing.read >= hitRing.capacity) hitRing.dropped++;
    if (sequence - hitRing.read >= hitRing.capacity) hitRing.read = sequence - hitRing.capacity + 1;
    slot.room = bus.id; slot.layer = layer; slot.time = time; slot.sequence = sequence; slot.released = false;
    slot.gain = Number.isFinite(value.gain) ? value.gain : 1;
    if (bus.density < (layerThresholds[layer] ?? .30) ||
        (bus.lowMuted && bus.low.has(layer) && time < (bus.dropAt ?? Infinity))) slot.gain = 0;
  }
  const diagnostics = {switches: [], scheduledSteps: 0, scheduledVoices: 0, droppedSteps: 0, voiceErrors: 0,
    compileErrors: {}, bpm: BPM, timerMs: 25, lookaheadSeconds: LOOKAHEAD, sixteenthSeconds: SIXTEENTH,
    engine: 'strudel', strudel: STRUDEL_URL};
  try { preferred = localStorage.getItem('vc-sound') === 'on' ? 'on' : 'off'; } catch (_) {}
  if (preferred === 'on') state = 'waiting';
  function notify() { for (const listener of listeners) listener(api); }
  function clamp(value, lo, hi) { return Math.max(lo, Math.min(hi, value)); }
  // Layer names are the labels in a room file (`kick: ...`); `$:` labels are numbered, `_name:` is muted.
  function layerNames(code) {
    const names = []; let anonymous = 0;
    for (const match of code.matchAll(/^\s*([A-Za-z_$][\w$]*)\s*:(?!:)/gm)) {
      const name = match[1] === '$' ? '$' + (++anonymous) : match[1];
      if (!name.startsWith('_') && !names.includes(name)) names.push(name);
    }
    return names;
  }
  function curve(amount = 1.8, length = 2048) {
    const key = amount + ':' + length; if (waveCurves.has(key)) return waveCurves.get(key);
    const result = new Float32Array(length), normal = Math.tanh(amount);
    for (let i = 0; i < length; i++) result[i] = Math.tanh((i * 2 / (length - 1) - 1) * amount) / normal;
    waveCurves.set(key, result);
    return result;
  }
  function gain(value = 1) { const node = ctx.createGain(); node.gain.value = value; return node; }
  function filter(type, hz, q = .7) { const node = ctx.createBiquadFilter(); node.type = type; node.frequency.value = hz; node.Q.value = q; return node; }
  function follow(param, value, at = ctx.currentTime) { param.setTargetAtTime(value, at, SMOOTH); }
  function seeded(seed) { return () => { seed ^= seed << 13; seed ^= seed >>> 17; seed ^= seed << 5; return (seed >>> 0) / 4294967296; }; }
  function createContext() {
    const AudioConstructor = window.AudioContext || window.webkitAudioContext;
    if (!AudioConstructor) throw new Error('Web Audio is unavailable in this browser.');
    ctx = new AudioConstructor({latencyHint: 'interactive'});
    const random = seeded(0x9e3779b9);
    const impulse = ctx.createBuffer(2, Math.ceil(ctx.sampleRate * 2.4), ctx.sampleRate);
    for (let channel = 0; channel < 2; channel++) {
      const values = impulse.getChannelData(channel);
      for (let i = 0; i < values.length; i++) values[i] = (random() * 2 - 1) * Math.pow(1 - i / values.length, 3.2) * .45;
    }
    compressor = ctx.createDynamicsCompressor();
    compressor.threshold.value = -12; compressor.knee.value = 12; compressor.ratio.value = 3;
    compressor.attack.value = .006; compressor.release.value = .14;
    clip = ctx.createWaveShaper(); clip.curve = curve(1.25); clip.oversample = '2x';
    master = gain(0); analyser = ctx.createAnalyser(); analyser.fftSize = 4096; analyser.smoothingTimeConstant = 0;
    cut = gain(1);
    compressor.connect(clip); clip.connect(cut); cut.connect(master); master.connect(analyser); analyser.connect(ctx.destination);
    noiseBuffer = ctx.createBuffer(1, ctx.sampleRate * 2, ctx.sampleRate);
    const noiseData = noiseBuffer.getChannelData(0);
    for (let i = 0; i < noiseData.length; i++) noiseData[i] = random() * 2 - 1;
    const delay = ctx.createDelay(2), delayTone = filter('lowpass', 5200); feedback = gain(.35);
    delay.delayTime.value = 60 / BPM * .75;
    delaySend = gain(1); delaySend.connect(delay); delay.connect(delayTone);
    delayTone.connect(feedback); feedback.connect(delay); delayTone.connect(compressor);
    const reverb = ctx.createConvolver(); reverb.buffer = impulse;
    reverbSend = gain(1); reverbGate = gain(1); reverbSend.connect(reverb); reverb.connect(reverbGate); reverbGate.connect(compressor);
    origin = ctx.currentTime + .04; nextStep = 0; diagnostics.epoch = origin; diagnostics.origin = origin;
    active = createBus(desired, 1); feedback.gain.value = active.spec.fx.feedback ?? .35; diagnostics.sampleRate = ctx.sampleRate;
  }
  // Strudel loads on the first sound gesture, into the page's one AudioContext.
  function loadStrudel() {
    loading ??= (async () => {
      const started = performance.now();
      S = await import(STRUDEL_URL);
      S.setAudioContext(ctx);
      controller = S.getSuperdoughAudioController();
      const createOrbit = controller.getOrbit.bind(controller);
      controller.getOrbit = (number, channels) => {
        const fresh = controller.nodes[number] == null, orbit = createOrbit(number, channels);
        if (fresh) {
          orbit.output.disconnect();
          const target = orbitTargets.get(number); if (target) orbit.output.connect(target);
        }
        return orbit;
      };
      S.miniAllStrings();
      const quiet = promise => Promise.resolve(promise).catch(error => { diagnostics.loadWarning = String(error); });
      await Promise.all([
        quiet(S.loadWorklets()),
        quiet(S.registerSynthSounds()),
        quiet(S.samples(`${SAMPLE_CDN}/tidal-drum-machines.json`, `${SAMPLE_CDN}/tidal-drum-machines/machines/`, {prebake: true})),
        quiet(S.samples(DIRT_SAMPLES))
      ]);
      for (const id of Object.keys(ROOM_CODE)) compileRoom(id);
      diagnostics.loadMs = Math.round(performance.now() - started);
      await preload(active?.spec.source || active?.id || 'working');
      diagnostics.readyMs = Math.round(performance.now() - started);
      for (const id of Object.keys(ROOM_CODE)) preload(id);
      notify();
    })().catch(error => {
      diagnostics.error = String(error); loading = null;
      console.warn('Vault City sound could not load Strudel:', error);
    });
    return loading;
  }
  function compileRoom(id, code = ROOM_CODE[id]) {
    const layers = new Map(), P = S.Pattern.prototype, previous = P.p;
    let anonymous = 0;
    P.p = function (name) {
      const key = name === '$' ? '$' + (++anonymous) : String(name);
      if (!key.startsWith('_')) layers.set(key, this);
      return this;
    };
    try {
      const scope = {...S, setcpm() {}, setcps() {}, hush() {}, evaluate() {}};
      const names = Object.keys(scope).filter(name => /^[A-Za-z_$][\w$]*$/.test(name) && !['eval', 'arguments', 'default'].includes(name));
      const {output} = S.transpiler(code, {addReturn: false, emitMiniLocations: false, emitWidgets: false});
      Function(...names, '"use strict";' + output)(...names.map(name => scope[name]));
      compiled.set(id, layers); delete diagnostics.compileErrors[id];
    } catch (error) {
      diagnostics.compileErrors[id] = String(error);
      console.warn(`Vault City room "${id}" did not compile:`, error);
    } finally { P.p = previous; }
    return compiled.get(id);
  }
  // Fetch and decode every sample a room can play before its first bar needs it.
  function preload(id) {
    if (preloaded.has(id)) return preloaded.get(id);
    const layers = compiled.get(id), jobs = [], seen = new Set();
    if (layers) for (const pattern of layers.values()) {
      let haps = []; try { haps = pattern.queryArc(0, rooms[id]?.cycleBars || 32); } catch (_) {}
      for (const hap of haps) {
        const value = hap.value; if (!value || typeof value !== 'object' || !value.s) continue;
        const name = value.bank ? `${value.bank}_${value.s}` : value.s, sound = S.getSound(name);
        const key = name + ':' + (value.n ?? 0) + ':' + (value.note ?? '');
        if (seen.has(key) || sound?.data?.type !== 'sample') continue;
        seen.add(key); jobs.push(S.getSampleBuffer({...value, s: name}, sound.data.samples).catch(() => null));
      }
    }
    const job = Promise.race([Promise.all(jobs), new Promise(resolve => setTimeout(resolve, 6000))]);
    preloaded.set(id, job); return job;
  }
  function createBus(id, initialGain, lowMuted = false) {
    const spec = rooms[id], input = gain(), drive = ctx.createWaveShaper(), lowpass = filter('lowpass', spec.fx.lpf);
    const timelineLowpass = filter('lowpass', 12000), stats = timeline[spec.source || id];
    drive.curve = curve(1 + spec.fx.drive * 5); drive.oversample = '2x';
    const pan = ctx.createStereoPanner(), fader = gain(initialGain), level = gain(spec.fx.gain ?? 1);
    const dry = gain(.86), delay = gain(spec.fx.delay), reverb = gain(spec.fx.reverb);
    const djFilter = filter('lowpass', 20000);
    input.connect(drive); drive.connect(lowpass); lowpass.connect(djFilter); djFilter.connect(timelineLowpass); timelineLowpass.connect(level); level.connect(pan); pan.connect(fader);
    fader.connect(dry); dry.connect(compressor); fader.connect(delay); delay.connect(delaySend);
    fader.connect(reverb); reverb.connect(reverbSend);
    const bus = {id, serial: serial++, spec, input, drive, lowpass, djFilter, timelineLowpass, pan, fader, level, dry, delay, reverb,
      preFade: pan, postFade: fader, gain: fader, sources: new Set(), sidechain: {}, layers: {}, mutes: {}, orbits: {},
      low: new Set(spec.low || LOW_LAYERS), lowMuted,
      density: 1, brightness: 1, cutoff: spec.fx.lpf, reverbAmount: spec.fx.reverb, voices: 0,
      startStep: null, modulation: []};
    for (const name of spec.layers) ensureLayer(bus, name);
    if (rideHeading !== null) pan.pan.value = Math.sin(rideHeading) * .24;
    if (spec.fx.lfo) {
      const lfo = ctx.createOscillator(), depth = gain((spec.fx.lfo.max - spec.fx.lfo.min) / 2);
      lowpass.frequency.value = (spec.fx.lfo.max + spec.fx.lfo.min) / 2;
      lfo.frequency.value = spec.fx.lfo.frequency; lfo.connect(depth); depth.connect(lowpass.frequency); lfo.start();
      bus.modulation.push(lfo, depth); bus.sources.add(lfo);
    }
    if (stats) applyTimeline(bus, stats, true);
    buses.push(bus); return bus;
  }
  function ensureLayer(bus, name) {
    if (bus.layers[name]) return bus.layers[name];
    const layer = gain(1), mute = gain(bus.lowMuted && bus.low.has(name) ? 0 : 1);
    bus.layers[name] = layer; bus.mutes[name] = mute; layer.connect(mute);
    if (ducked.has(name)) {
      const duck = gain(1); mute.connect(duck); duck.connect(bus.input); bus.sidechain[name] = duck;
    } else mute.connect(bus.input);
    const orbit = nextOrbit++; bus.orbits[name] = orbit; orbitTargets.set(orbit, layer);
    if (bus.lowMuted && bus.low.has(name) && bus.dropAt > ctx.currentTime) {
      mute.gain.setValueAtTime(0, bus.dropAt - .005); mute.gain.linearRampToValueAtTime(1, bus.dropAt);
    }
    if (bus.timeline) layer.gain.value = bus.density >= (layerThresholds[name] ?? .30) ? 1 : 0;
    return layer;
  }
  function retire(bus) {
    if (!bus) return;
    for (const source of bus.sources) { try { source.stop(); } catch (_) {} }
    for (const orbit of Object.values(bus.orbits)) {
      orbitTargets.delete(orbit);
      if (controller?.nodes[orbit]) { controller.nodes[orbit].disconnect(); delete controller.nodes[orbit]; }
    }
    for (const node of [bus.input, bus.drive, bus.lowpass, bus.djFilter, bus.timelineLowpass, bus.level, bus.pan, bus.fader, bus.dry, bus.delay, bus.reverb,
      ...Object.values(bus.layers), ...Object.values(bus.mutes), ...Object.values(bus.sidechain), ...bus.modulation]) node.disconnect();
    const index = buses.indexOf(bus); if (index >= 0) buses.splice(index, 1);
  }
  function duck(bus, time) {
    for (const node of Object.values(bus.sidechain)) {
      node.gain.setValueAtTime(1, time); node.gain.linearRampToValueAtTime(Math.pow(10, -6 / 20), time + .003);
      node.gain.exponentialRampToValueAtTime(1, time + .093);
    }
  }
  function phase(spec, bar) {
    const cycle = bar % spec.cycleBars;
    if (spec.cycleBars === 16) return cycle < 4 ? 'establish' : cycle < 8 ? 'withhold' : cycle < 10 ? 'signal' : 'return';
    return cycle < 16 ? 'establish' : cycle < 20 ? 'withhold' : cycle < 22 ? 'signal' : 'return';
  }
  function play(bus, name, value, time, seconds, cycle) {
    if (!value || typeof value !== 'object' || time < ctx.currentTime) return;
    if (name === 'kick' && !(bus.lowMuted && time < (bus.dropAt ?? Infinity))) duck(bus, time);
    ensureLayer(bus, name);
    S.superdough({...value, orbit: bus.orbits[name]}, time, seconds, CPS, cycle)
      .catch(error => { diagnostics.voiceErrors++; diagnostics.lastVoiceError = String(error); });
    recordHit(bus, name, time, value);
    if (bus.spec.fx.gated && bus === active && (name === 'kick' || name === 'stab')) {
      reverbGate.gain.cancelAndHoldAtTime(time);
      reverbGate.gain.linearRampToValueAtTime(1, time + .004);
      reverbGate.gain.setValueAtTime(1, time + bus.spec.fx.gated);
      reverbGate.gain.linearRampToValueAtTime(.08, time + bus.spec.fx.gated + .015);
    }
    diagnostics.scheduledVoices++; bus.voices++;
  }
  function scheduleBus(bus, step, time) {
    const spec = bus.spec, layers = S && compiled.get(spec.source || spec.id);
    if (spec.fx.sweep) {
      const progress = (step % (spec.fx.sweepBars * 16)) / (spec.fx.sweepBars * 16 - 1);
      bus.lowpass.frequency.setTargetAtTime(spec.fx.sweep[0] + progress * (spec.fx.sweep[1] - spec.fx.sweep[0]), time, SMOOTH);
    }
    if (!layers) return;
    const bar = Math.floor(step / 16), cyclePhase = phase(spec, bar), cycleBar = bar % spec.cycleBars;
    const entering = bus.startStep === null;
    if (entering) bus.startStep = step;
    const withheld = Array.isArray(spec.withhold) ? spec.withhold[0] : spec.withhold;
    const begin = step / 16, end = (step + 1) / 16;
    for (const [name, pattern] of layers) {
      if (cyclePhase === 'withhold' && withheld === name) continue;
      // In the signal stage the missing layer returns quietly for the second bar.
      // The Yards instead subtracts its roll while its riser announces the return.
      if (cyclePhase === 'signal' && Array.isArray(spec.withhold) && spec.withhold[1] === name) continue;
      if (cyclePhase === 'signal' && !Array.isArray(spec.withhold) && withheld === name && cycleBar % 2 === 0) continue;
      const quiet = cyclePhase === 'signal' && !Array.isArray(spec.withhold) && withheld === name ? .55 : 1;
      let haps;
      try { haps = pattern.queryArc(begin, end); } catch (error) { diagnostics.voiceErrors++; diagnostics.lastVoiceError = String(error); continue; }
      for (const hap of haps) {
        const onset = Number(hap.whole?.begin ?? hap.part.begin), length = Number(hap.whole?.end ?? hap.part.end) - onset;
        let value = hap.value;
        if (quiet !== 1 && value && typeof value === 'object') value = {...value, gain: (value.gain ?? 1) * quiet};
        if (hap.hasOnset()) play(bus, name, value, origin + onset * BAR, length * BAR, onset);
        // Reconstruct a sustained layer when entering between its written starts.
        else if (entering && sustained.has(name) && onset + length - begin > .25) play(bus, name, value, time, (onset + length - begin) * BAR, begin);
      }
    }
  }
  const FADE_IN = Float32Array.from({length: 129}, (_, i) => Math.sin(i / 128 * Math.PI / 2));
  // Move every low layer (kick and bass, plus a room's sub drone) of a bus to `value` by time `at`.
  function lowTo(bus, value, at, ramp) {
    for (const name of bus.low) {
      const param = bus.mutes[name]?.gain; if (!param) continue;
      param.cancelScheduledValues(at - ramp); param.setValueAtTime(value ? 0 : 1, at - ramp); param.linearRampToValueAtTime(value, at);
    }
  }
  function startRiser(from, to) {
    const source = ctx.createBufferSource(), band = filter('highpass', 300, .9), level = gain(0);
    source.buffer = noiseBuffer; source.loop = true;
    source.connect(band); band.connect(level); level.connect(compressor); level.connect(reverbSend);
    band.frequency.setValueAtTime(300, from); band.frequency.exponentialRampToValueAtTime(9000, to);
    level.gain.setValueAtTime(EPS, from); level.gain.exponentialRampToValueAtTime(.09, to - .01); level.gain.linearRampToValueAtTime(0, to);
    source.start(from); source.stop(to + .02);
    source.onended = () => { source.disconnect(); band.disconnect(); level.disconnect(); };
    return {source, level};
  }
  // The last beat before the drop is silence, then everything returns on the 1.
  function cutBeat(drop) {
    const beat = BAR / 4, param = cut.gain;
    param.cancelScheduledValues(drop - beat - .005);
    param.setValueAtTime(1, drop - beat - .005); param.linearRampToValueAtTime(0, drop - beat);
    param.setValueAtTime(0, drop - .005); param.linearRampToValueAtTime(1, drop);
  }
  function enterBridge(id, time, drop) {
    const bus = createBus(id, 0, true); bus.dropAt = drop;
    follow(feedback.gain, bus.spec.fx.feedback ?? .35, time);
    if (!bus.spec.fx.gated) { reverbGate.gain.cancelAndHoldAtTime(time); follow(reverbGate.gain, 1, time); }
    // The new room's hats and percussion come in over one bar; its kick and bass wait for the drop.
    bus.fader.gain.setValueCurveAtTime(FADE_IN, time, BAR);
    lowTo(bus, 1, drop, .005);
    return bus;
  }
  function beginTransition(id, time) {
    if (!active || active.id === id) { pending = null; return; }
    const beat = BAR / 4, startBar = Math.round((time - origin) / BAR);
    const dropBar = nextDrop(startBar), drop = origin + dropBar * BAR;
    outgoing = active; active = enterBridge(id, time, drop);
    // The old room loses its kick and bass on the first beat, and a low-pass closes across the bridge.
    outgoing.lowMuted = true; lowTo(outgoing, 0, time + beat, beat);
    outgoing.djFilter.frequency.setValueAtTime(20000, time);
    outgoing.djFilter.frequency.exponentialRampToValueAtTime(BRIDGE_LPF, drop - beat);
    outgoing.fader.gain.setValueAtTime(1, drop - .005); outgoing.fader.gain.linearRampToValueAtTime(0, drop);
    riser = startRiser(Math.max(time, drop - 4 * BAR), drop - beat);
    cutBeat(drop);
    transition = {from: outgoing.id, to: active.id, start: time, drop, end: drop, bridgeBars: dropBar - startBar,
      curve: 'bridge-slam', bar: startBar, dropBar};
    diagnostics.switches.push({...transition}); if (diagnostics.switches.length > 64) diagnostics.switches.shift();
    pending = null;
  }
  // A different room chosen mid-bridge takes over the bridge; the drop stays on its phrase.
  function retarget(id, time) {
    const beat = BAR / 4, dropped = active;
    dropped.fader.gain.cancelAndHoldAtTime(time); dropped.fader.gain.linearRampToValueAtTime(0, time + beat);
    graveyard.push({bus: dropped, at: time + beat + .3});
    active = enterBridge(id, time, transition.drop);
    transition = {...transition, to: id, retargetedAt: time};
    diagnostics.switches.push({...transition}); pending = null;
  }
  // Going back to the old room mid-bridge brings its kick and bass straight back on the bar.
  function cancelTransition(time) {
    const beat = BAR / 4, back = outgoing, dropped = active;
    back.lowMuted = false;
    for (const name of back.low) {
      const param = back.mutes[name]?.gain; if (param) { param.cancelAndHoldAtTime(time); param.linearRampToValueAtTime(1, time + .005); }
    }
    back.djFilter.frequency.cancelAndHoldAtTime(time); back.djFilter.frequency.exponentialRampToValueAtTime(20000, time + beat);
    back.fader.gain.cancelAndHoldAtTime(time); back.fader.gain.setValueAtTime(1, time);
    dropped.fader.gain.cancelAndHoldAtTime(time); dropped.fader.gain.linearRampToValueAtTime(0, time + beat);
    graveyard.push({bus: dropped, at: time + beat + .3});
    cut.gain.cancelScheduledValues(time); cut.gain.setValueAtTime(1, time);
    if (riser) { riser.level.gain.cancelAndHoldAtTime(time); riser.level.gain.linearRampToValueAtTime(0, time + .05); riser = null; }
    diagnostics.switches.push({...transition, cancelledAt: time});
    active = back; outgoing = null; transition = null; pending = null;
  }
  function scheduler() {
    if (!enabled || !ctx) return;
    sampleOutputClock();
    const now = ctx.currentTime;
    for (let i = graveyard.length - 1; i >= 0; i--) if (now >= graveyard[i].at) { retire(graveyard[i].bus); graveyard.splice(i, 1); }
    if (transition && now >= transition.end + .3) {
      retire(outgoing); outgoing = null; active.lowMuted = false; transition = null; riser = null;
      if (desired !== active.id) pending = desired;
    }
    // A resumed or backgrounded tab catches up its transport without bursting old notes.
    while (origin + nextStep * SIXTEENTH < ctx.currentTime - .02) { nextStep++; diagnostics.droppedSteps++; }
    while (origin + nextStep * SIXTEENTH < ctx.currentTime + LOOKAHEAD) {
      const time = origin + nextStep * SIXTEENTH;
      if (nextStep % 16 === 0) {
        if (pending && !transition) beginTransition(pending, time);
        else if (transition && desired !== transition.to && time >= transition.start + 2 * BAR && transition.drop - time >= 2 * BAR) {
          if (desired === transition.from) cancelTransition(time); else if (Object.hasOwn(rooms, desired)) retarget(desired, time);
        }
      }
      scheduleBus(active, nextStep, time);
      if (outgoing && transition && time < transition.end) scheduleBus(outgoing, nextStep, time);
      for (const grave of graveyard) if (time < grave.at) scheduleBus(grave.bus, nextStep, time);
      nextStep++; diagnostics.scheduledSteps++;
    }
  }
  function setRoom(id) {
    desired = Object.hasOwn(rooms, id) ? id : 'skyline';
    if (!ctx) return desired;
    pending = desired === active?.id ? null : desired;
    if (S) preload(rooms[desired].source || desired);
    return desired;
  }
  async function toggle(event) {
    if (!event?.isTrusted || !['click', 'keydown', 'pointerup'].includes(event.type)) return enabled;
    if (state === 'starting') return enabled;
    if (enabled) {
      enabled = false; preferred = 'off'; state = 'off'; clearInterval(timer); timer = null; startToken++;
      master.gain.cancelScheduledValues(ctx.currentTime); follow(master.gain, 0);
      setTimeout(() => { if (!enabled && ctx.state === 'running') ctx.suspend(); }, 300);
    } else {
      state = 'starting'; notify();
      const token = ++startToken;
      try {
        if (!ctx) createContext();
        await ctx.resume(); enabled = true; preferred = 'on'; state = 'on';
        master.gain.cancelScheduledValues(ctx.currentTime); follow(master.gain, .8);
        scheduler(); timer = setInterval(scheduler, 25);
        loadStrudel().then(() => { if (token === startToken) notify(); });
      } catch (error) { enabled = false; state = 'error'; diagnostics.error = String(error); }
    }
    try { localStorage.setItem('vc-sound', preferred); } catch (_) {}
    notify(); return enabled;
  }
  function setRideHeading(heading) {
    rideHeading = Number.isFinite(heading) ? heading : null;
    if (ctx) for (const bus of buses) follow(bus.pan.pan, rideHeading === null ? 0 : Math.sin(rideHeading) * .24);
  }
  function applyTimeline(bus, stats, immediate = false) {
    const density = clamp(Number(stats.density) || 0, 0, 1), brightness = clamp(Number(stats.brightness) || 0, 0, 1);
    bus.density = density; bus.brightness = brightness; bus.timeline = {density, brightness};
    bus.cutoffTarget = 600 + brightness * 11400;
    bus.reverbTarget = bus.id === 'skyline' ? .45 : .15 + (1 - brightness) * .4;
    bus.timelineUpdatedAt = ctx.currentTime;
    const change = (param, value) => { if (immediate) param.value = value; else follow(param, value, bus.timelineUpdatedAt); };
    change(bus.timelineLowpass.frequency, bus.cutoffTarget); change(bus.reverb.gain, bus.reverbTarget);
    for (const [name, layer] of Object.entries(bus.layers)) change(layer.gain, density >= (layerThresholds[name] ?? .30) ? 1 : 0);
  }
  function setTimeline(stats) {
    Object.assign(timeline, stats);
    if (ctx) for (const bus of buses) {
      const value = timeline[bus.spec.source || bus.id]; if (value) applyTimeline(bus, value);
    }
  }
  // Console hooks for trying sounds live: cityAudio.code('working') gives strudel.cc-ready code,
  // cityAudio.setCode('working', code) swaps a room without reloading the page.
  function code(id) { return ROOM_CODE[rooms[id]?.source || id] ?? null; }
  function setCode(id, source) {
    id = rooms[id]?.source || id;
    if (!Object.hasOwn(ROOM_CODE, id)) throw new Error('No room called ' + id);
    if (!S) throw new Error('Turn the sound on first, so Strudel is loaded.');
    const layers = compileRoom(id, source);
    if (!layers || diagnostics.compileErrors[id]) throw new Error(diagnostics.compileErrors[id] || 'Did not compile');
    ROOM_CODE[id] = source; rooms[id].code = source; rooms[id].layers = [...layers.keys()];
    preloaded.delete(id); preload(id);
    return rooms[id].layers;
  }
  const api = {
    get ctx() { return ctx; }, get room() { return active?.id || desired; }, get analyser() { return analyser; },
    get enabled() { return enabled; }, get preferred() { return preferred; }, get state() { return state; },
    get origin() { return origin; }, get desired() { return desired; }, hitRing, nextDrop, outputClock,
    arrangementPhase(id, bar) { return phase(rooms[id] || rooms.skyline, bar); },
    get transition() { return transition; }, get buses() { return buses; }, get strudel() { return S; },
    get cut() { return cut; }, phrase: PHRASE, minBridge: MIN_BRIDGE,
    get ready() { return compiled.size > 0; },
    rooms, diagnostics, timeline, layerThresholds, setRoom, toggle, setTimeline, setRideHeading, code, setCode,
    subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener); }
  };
  return api;
})();
