// Procedural rooms. All events are scheduled on the audio clock, never the frame loop.
const cityAudio = (() => {
  'use strict';
  const BPM = 140, SIXTEENTH = 60 / BPM / 4, BAR = SIXTEENTH * 16;
  const EPS = 0.0001, SMOOTH = 0.25, LOOKAHEAD = 0.12;
  const thresholds = {kick: 0, hatC: .15, perc: .30, hatO: .45, stab: .60, clap: .75, pad: .90};
  const layerThresholds = {...thresholds, bass: .60, shaker: .15, woodblock: .30, clank: .30, blip: .30,
    arp: .30, bubble: .30, rim: .30, noise: .15, ride: .45, riser: .30};
  const swingable = new Set(['hatC', 'hatO', 'perc', 'rim', 'ride', 'bubble', 'shaker', 'woodblock', 'arp', 'blip', 'clank']);
  const beat = '9...9...9...9...', offbeat = '..7...7...7...7..';
  const every = (bars, digit = '5', offset = 0) => '.'.repeat(offset) + digit + '.'.repeat(bars * 16 - offset - 1);
  const rooms = {
    core: {
      id: 'core', root: 38, swing: .50, densityCap: .4, loopBars: 2, cycleBars: 32, withhold: 'hatO',
      voices: {
        kick: {pattern: beat, decay: .38, click: .025},
        hatO: {pattern: '..6.............', decay: .14, cutoff: 9000},
        perc: {pattern: every(2, '1', 16), pitches: [7], decay: .28},
        pad: {pattern: every(16, '8'), pitches: [0], sub: true, decay: BAR * 16, level: 1.5},
        riser: {pattern: every(16, '3'), decay: BAR * 16}
      }, fx: {lpf: 9000, delay: .08, reverb: .30, drive: .04, gain: .84}
    },
    episodic: {
      id: 'episodic', root: 41, swing: .58, loopBars: 4, cycleBars: 32, withhold: 'perc',
      voices: {
        kick: {pattern: beat, decay: .34, click: .05},
        hatC: {pattern: '5357535753575357', decay: .055, cutoff: 5900},
        hatO: {pattern: '..5...5...5...5..', decay: .23, cutoff: 5700},
        perc: {pattern: '9.5.9..5.9.5..9.', pitches: [0, 5], decay: .24, level: 1.15},
        stab: {pattern: '..........9.....', pitches: [0, 3, 7], decay: .44, lpf: 2400},
        bass: {pattern: '..5...5...5...5..', pitches: [-12], decay: .28},
        noise: {pattern: every(4, '9'), decay: BAR * 4, levelDb: -30}
      }, fx: {lpf: 2400, delay: .5, reverb: .35, drive: .08, gain: .72}
    },
    semantic: {
      id: 'semantic', root: 33, swing: .52, loopBars: 2, cycleBars: 32, withhold: 'bass',
      voices: {
        kick: {pattern: beat, decay: .44, click: .035, endPitch: 43},
        bass: {pattern: '..9...9...9...9.', pitches: [0], decay: .29},
        stab: {pattern: every(2, '8', 10), pitches: [0, 3, 7, 10, 14], decay: .8, lpf: 2700},
        ride: {pattern: offbeat, decay: .31, level: 1.3},
        hatC: {pattern: '4444444444444444', decay: .035, cutoff: 9800}
      }, fx: {lpf: 7000, delay: .23, reverb: .6, drive: .03, gain: .46}
    },
    procedural: {
      id: 'procedural', root: 40, swing: .50, loopBars: 4, cycleBars: 32, withhold: 'rim',
      voices: {
        kick: {pattern: beat, decay: .25, click: .23},
        hatC: {pattern: '5.3.5.3.5.3.5.3.', decay: .026, cutoff: 8500},
        rim: {pattern: '.7.9.7.9.7.9.7.9', decay: .034, cutoff: 2100, level: 1.8},
        perc: {pattern: '.'.repeat(48) + '9...9...97599759', pitches: [0, 3], decay: .075, level: 1.1, ratchet: 2},
        clank: {pattern: every(4, '8'), pitches: [12], decay: .18}
      }, fx: {lpf: 10500, delay: .04, reverb: .08, drive: .35, gain: .9}
    },
    prospective: {
      id: 'prospective', root: 43, swing: .54, loopBars: 4, cycleBars: 16, withhold: ['hatO', 'perc'],
      voices: {
        kick: {pattern: beat, decay: .29, click: .12},
        hatC: {pattern: '6357635763576357', decay: .038, cutoff: 7300},
        hatO: {pattern: offbeat, decay: .19},
        perc: {pattern: '9..6.7..9.5.7.5.', pitches: [0, 5, 10], decay: .13, level: 1.25},
        stab: {pattern: '...............9', pitches: [0, 5, 10], decay: .23},
        riser: {pattern: every(16, '7', 8 * 16), decay: BAR * 2}
      }, fx: {lpf: 8000, sweep: [1000, 8000], sweepBars: 8, delay: .2, reverb: .25, drive: .09, gain: .69}
    },
    working: {
      id: 'working', root: 41, swing: .56, loopBars: 4, cycleBars: 32, withhold: 'hatO',
      voices: {
        kick: {pattern: '9...9...9...9...', decay: .32},
        hatO: {pattern: '..7...7...7...7..', decay: .17},
        hatC: {pattern: '7595759575957595', decay: .035},
        perc: {pattern: '9..5.9.5..9.5.9.', pitches: [0, 5, 7], decay: .14},
        clap: {pattern: '....9.......9...', decay: .12, nudgeMs: 12},
        stab: {pattern: '..........9.....', pitches: [0, 3, 7], decay: .19},
        bass: {pattern: '..6...6...6...6..', pitches: [-12], decay: .19},
        pad: {pattern: '3' + '.'.repeat(63), pitches: [0, 3, 7], decay: BAR * 4}
      },
      fx: {lpf: 12000, delay: .16, reverb: .2, drive: .12, gain: 1}
    },
    jhon: {
      id: 'jhon', root: 36, swing: .60, loopBars: 4, cycleBars: 32, withhold: 'shaker',
      voices: {
        kick: {pattern: '7...7...7...7...', decay: .33, click: .04},
        perc: {pattern: '9.5.9.5..9.5.9.5', pitches: [0, 3, 7, 10], decay: .21, level: 1.4},
        shaker: {pattern: '5555555555555555', decay: .049, cutoff: 6200},
        woodblock: {pattern: '......9.......9.', decay: .035, cutoff: 1100},
        pad: {pattern: every(4, '6'), pitches: [0, 4, 7, 11], decay: BAR * 4, lpf: 1700}
      }, fx: {lpf: 8000, delay: .13, reverb: .3, drive: .055, gain: .86}
    },
    prasma: {
      id: 'prasma', root: 45, swing: .53, loopBars: 4, cycleBars: 32, withhold: 'stab',
      voices: {
        kick: {pattern: beat, decay: .21, click: .17},
        hatC: {pattern: '9393939393939393', decay: .021, cutoff: 10200, level: 1.3},
        hatO: {pattern: '..5...5...5...5..', decay: .07, cutoff: 10500},
        perc: {pattern: '9.9..9.9..9.9..9', pitches: [0, 12], decay: .060, level: 1.5},
        stab: {pattern: '....9...........', pitches: [0, 3, 7], decay: .090, lpf: 8600, level: 1.35}
      }, fx: {lpf: 14000, delay: .05, reverb: .12, gated: .11, drive: .07, gain: .85}
    },
    branding: {
      id: 'branding', root: 48, swing: .55, loopBars: 4, cycleBars: 32, withhold: 'blip',
      voices: {
        kick: {pattern: beat, decay: .26, click: .10},
        hatC: {pattern: '5.7.5.7.5.7.5.7.', decay: .032, cutoff: 8500},
        blip: {pattern: '9..9..9...9..9..', pitches: [0, 7, 10], decay: .13, level: 1.15},
        clap: {pattern: '....9.......9...', decay: .10},
        riser: {pattern: every(8, '5', 7 * 16), decay: BAR}
      }, fx: {lpf: 10000, delay: .24, reverb: .25, drive: .08, gain: .42}
    },
    onebrain: {
      id: 'onebrain', root: 38, swing: .51, loopBars: 4, cycleBars: 32, withhold: 'arp',
      voices: {
        kick: {pattern: beat, decay: .31, click: .075},
        hatC: {pattern: '4.5.4.5.4.5.4.5.', decay: .045, cutoff: 8200},
        arp: {pattern: '9.7.5.9.7.5.9.7.', pitches: [0, 3, 7, 12], decay: .26, crush: 8, level: 1.55},
        pad: {pattern: every(4, '7'), pitches: [0, 2, 7], decay: BAR * 4, lpf: 2100}
      }, fx: {lpf: 9000, delay: .5, feedback: .5, reverb: .35, drive: .045, gain: .68, width: .48}
    },
    reef: {
      id: 'reef', root: 31, swing: .55, loopBars: 4, cycleBars: 32, withhold: 'kickTop',
      voices: {
        kick: {pattern: beat, decay: .46, click: .045, endPitch: 39},
        hatC: {pattern: '3.3.3.3.3.3.3.3.', decay: .04, cutoff: 4200, level: .4},
        bubble: {pattern: '9...9...9.......', randomPerBar: [1, 3], pitches: [72, 96], decay: .14},
        pad: {pattern: every(4, '8'), pitches: [0, 3, 7], decay: BAR * 4, lpf: 1500, chorus: .4}
      }, fx: {lpf: 500, lfo: {frequency: .05, min: 500, max: 3000}, delay: .30, reverb: .6, drive: .025, gain: .54}
    },
    inbox: {
      id: 'inbox', root: 41, swing: .50, loopBars: 4, cycleBars: 32, withhold: null,
      voices: {
        kick: {pattern: '8...8...8...8...', decay: .39, click: .025},
        pad: {pattern: every(4, '8'), pitches: [0], sub: true, decay: BAR * 4, level: 1.6}
      }, fx: {lpf: 4000, delay: .06, reverb: .5, drive: .02, gain: .40}
    }
  };
  rooms.skyline = {...rooms.working, id: 'skyline', source: 'working',
    fx: {...rooms.working.fx, lpf: 1200, reverb: .45, gain: .5}};

  let ctx = null, analyser = null, compressor, clip, master, delaySend, reverbSend, feedback, reverbGate;
  let whiteNoise, seed = 0x9e3779b9, enabled = false, desired = 'skyline', active = null;
  let outgoing = null, transition = null, timer = null, origin = 0, nextStep = 0;
  let preferred = 'off', state = 'off', rideHeading = null, pending = null, serial = 0;
  const buses = [], listeners = new Set(), timeline = {}, crushCurves = new Map(), waveCurves = new Map();
  const diagnostics = {switches: [], scheduledSteps: 0, scheduledVoices: 0, droppedSteps: 0,
    bpm: BPM, timerMs: 25, lookaheadSeconds: LOOKAHEAD, sixteenthSeconds: SIXTEENTH};
  try { preferred = localStorage.getItem('vc-sound') === 'on' ? 'on' : 'off'; } catch (_) {}
  if (preferred === 'on') state = 'waiting';
  function notify() { for (const listener of listeners) listener(api); }
  function random() { seed ^= seed << 13; seed ^= seed >>> 17; seed ^= seed << 5; return (seed >>> 0) / 4294967296; }
  function frequency(midi) { return 440 * Math.pow(2, (midi - 69) / 12); }
  function clamp(value, lo, hi) { return Math.max(lo, Math.min(hi, value)); }
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
  function createContext() {
    const AudioConstructor = window.AudioContext || window.webkitAudioContext;
    if (!AudioConstructor) throw new Error('Web Audio is unavailable in this browser.');
    ctx = new AudioConstructor({latencyHint: 'interactive'});
    whiteNoise = ctx.createBuffer(1, ctx.sampleRate * 2, ctx.sampleRate);
    const noiseData = whiteNoise.getChannelData(0);
    for (let i = 0; i < noiseData.length; i++) noiseData[i] = random() * 2 - 1;
    const impulse = ctx.createBuffer(2, Math.ceil(ctx.sampleRate * 2.4), ctx.sampleRate);
    for (let channel = 0; channel < 2; channel++) {
      const values = impulse.getChannelData(channel);
      for (let i = 0; i < values.length; i++) values[i] = (random() * 2 - 1) * Math.pow(1 - i / values.length, 3.2) * .45;
    }
    compressor = ctx.createDynamicsCompressor();
    compressor.threshold.value = -15; compressor.knee.value = 15; compressor.ratio.value = 2;
    compressor.attack.value = .008; compressor.release.value = .12;
    clip = ctx.createWaveShaper(); clip.curve = curve(1.25); clip.oversample = '2x';
    master = gain(0); analyser = ctx.createAnalyser(); analyser.fftSize = 4096; analyser.smoothingTimeConstant = 0;
    compressor.connect(clip); clip.connect(master); master.connect(analyser); analyser.connect(ctx.destination);
    const delay = ctx.createDelay(2), delayTone = filter('lowpass', 5200); feedback = gain(.35);
    delay.delayTime.value = 60 / BPM * .75;
    delaySend = gain(1); delaySend.connect(delay); delay.connect(delayTone);
    delayTone.connect(feedback); feedback.connect(delay); delayTone.connect(compressor);
    const reverb = ctx.createConvolver(); reverb.buffer = impulse;
    reverbSend = gain(1); reverbGate = gain(1); reverbSend.connect(reverb); reverb.connect(reverbGate); reverbGate.connect(compressor);
    origin = ctx.currentTime + .04; nextStep = 0; diagnostics.epoch = origin; diagnostics.origin = origin;
    active = createBus(desired, 1); feedback.gain.value = active.spec.fx.feedback ?? .35; diagnostics.sampleRate = ctx.sampleRate;
  }
  function createBus(id, initialGain) {
    const spec = rooms[id], input = gain(), drive = ctx.createWaveShaper(), lowpass = filter('lowpass', spec.fx.lpf);
    const timelineLowpass = filter('lowpass', 12000), stats = timeline[spec.source || id];
    drive.curve = curve(1 + spec.fx.drive * 5); drive.oversample = '2x';
    const pan = ctx.createStereoPanner(), fader = gain(initialGain), level = gain(spec.fx.gain ?? 1);
    const dry = gain(.86), delay = gain(spec.fx.delay), reverb = gain(spec.fx.reverb);
    input.connect(drive); drive.connect(lowpass); lowpass.connect(timelineLowpass); timelineLowpass.connect(level); level.connect(pan); pan.connect(fader);
    fader.connect(dry); dry.connect(compressor); fader.connect(delay); delay.connect(delaySend);
    fader.connect(reverb); reverb.connect(reverbSend);
    const bus = {id, serial: serial++, spec, input, drive, lowpass, timelineLowpass, pan, fader, level, dry, delay, reverb,
      preFade: pan, postFade: fader, gain: fader, sources: new Set(), sidechain: {}, layers: {},
      density: 1, brightness: 1, cutoff: spec.fx.lpf, reverbAmount: spec.fx.reverb, voices: 0,
      startStep: null, bubbleBar: -1, bubbleSteps: [], modulation: []};
    bus.score = Object.entries(spec.voices).map(([name, voice]) => {
      const pattern = voice.pattern.padEnd(Math.ceil(voice.pattern.length / 16) * 16, '.');
      const prefix = new Uint16Array(pattern.length); let hits = 0, first = '.';
      for (let i = 0; i < pattern.length; i++) {
        prefix[i] = hits;
        if (pattern[i] !== '.' && pattern[i] !== '0') { hits++; if (first === '.') first = pattern[i]; }
      }
      return {name, voice, pattern, prefix, hits, first};
    });
    for (const name of Object.keys(spec.voices)) {
      const layer = gain(1); bus.layers[name] = layer;
      if (['pad', 'stab', 'bass'].includes(name)) {
        const duck = gain(1); layer.connect(duck); duck.connect(input); bus.sidechain[name] = duck;
      } else layer.connect(input);
    }
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
  function retire(bus) {
    if (!bus) return;
    for (const source of bus.sources) { try { source.stop(); } catch (_) {} }
    for (const node of [bus.input, bus.drive, bus.lowpass, bus.timelineLowpass, bus.level, bus.pan, bus.fader, bus.dry, bus.delay, bus.reverb,
      ...Object.values(bus.layers), ...Object.values(bus.sidechain), ...bus.modulation]) node.disconnect();
    const index = buses.indexOf(bus); if (index >= 0) buses.splice(index, 1);
  }
  function track(bus, source, time, duration, cleanup = []) {
    bus.sources.add(source); source.onended = () => {
      bus.sources.delete(source); source.disconnect(); for (const node of cleanup) node.disconnect();
    };
    source.start(time); source.stop(time + duration);
  }
  function envelope(time, amplitude, decay, attack = .002, sustain = 0) {
    const node = gain(EPS); node.gain.setValueAtTime(EPS, time);
    node.gain.linearRampToValueAtTime(Math.max(EPS, amplitude), time + attack);
    if (sustain > 0) node.gain.setValueAtTime(Math.max(EPS, amplitude), time + attack + sustain);
    node.gain.exponentialRampToValueAtTime(EPS, time + attack + sustain + decay);
    return node;
  }
  function tone(bus, destination, type, hz, time, amplitude, decay, options = {}) {
    const oscillator = ctx.createOscillator(), env = envelope(time, amplitude, decay, options.attack || .002, options.sustain || 0);
    oscillator.type = type; oscillator.frequency.setValueAtTime(hz, time);
    if (options.pitch) oscillator.frequency.exponentialRampToValueAtTime(options.pitch, time + Math.min(decay, options.pitchTime || .045));
    if (options.detune) oscillator.detune.value = options.detune;
    oscillator.connect(env); env.connect(destination); track(bus, oscillator, time, decay + (options.attack || .002) + (options.sustain || 0) + .04, [env]);
    return {oscillator, env};
  }
  function noise(bus, destination, time, amplitude, decay, type, cutoff, q = .7, attack = .001) {
    const source = ctx.createBufferSource(), band = filter(type, cutoff, q), env = envelope(time, amplitude, decay, attack);
    source.buffer = whiteNoise; source.connect(band); band.connect(env); env.connect(destination);
    track(bus, source, time, decay + attack + .03, [band, env]); return {source, band, env};
  }
  function duck(bus, time) {
    for (const node of Object.values(bus.sidechain)) {
      node.gain.setValueAtTime(1, time); node.gain.linearRampToValueAtTime(Math.pow(10, -6 / 20), time + .003);
      node.gain.exponentialRampToValueAtTime(1, time + .093);
    }
  }
  const synths = {
    kick(bus, v, time, velocity) {
      const target = bus.layers.kick, shaper = ctx.createWaveShaper(); shaper.curve = curve(2.1);
      const top = v.top ? filter('lowpass', v.top) : null;
      if (top) { shaper.connect(top); top.connect(target); } else shaper.connect(target);
      const body = tone(bus, shaper, 'sine', v.pitch || 155, time, .52 * velocity, v.decay || .32, {pitch: v.endPitch || 48, pitchTime: .045});
      body.oscillator.addEventListener('ended', () => { shaper.disconnect(); if (top) top.disconnect(); }, {once: true});
      noise(bus, shaper, time, (v.click ?? .13) * velocity, .012, 'highpass', 2500);
      duck(bus, time);
    },
    hatC(bus, v, time, velocity) { noise(bus, bus.layers[v.layer || 'hatC'], time, .085 * velocity, v.decay || .035, 'highpass', v.cutoff || 7600); },
    hatO(bus, v, time, velocity) { noise(bus, bus.layers.hatO, time, .085 * velocity, v.decay || .17, 'highpass', v.cutoff || 6500, .65, .003); },
    perc(bus, v, time, velocity, pitch) {
      const hz = frequency(bus.spec.root + pitch + (v.octave ?? 0));
      let target = bus.layers[v.layer || 'perc'], crush = null, stereo = null;
      if (bus.spec.fx.width) {
        stereo = ctx.createStereoPanner(); stereo.pan.value = Math.sin(pitch * .7) * bus.spec.fx.width;
        stereo.connect(target); target = stereo;
      }
      if (v.crush) {
        if (!crushCurves.has(v.crush)) {
          const shape = new Float32Array(65536), levels = Math.pow(2, v.crush) - 1;
          for (let i = 0; i < shape.length; i++) shape[i] = Math.round(i / (shape.length - 1) * levels) / levels * 2 - 1;
          crushCurves.set(v.crush, shape);
        }
        crush = ctx.createWaveShaper(); crush.curve = crushCurves.get(v.crush); crush.connect(target); target = crush;
      }
      const hit = tone(bus, target, 'triangle', hz * 1.7, time, .19 * velocity, v.decay || .14, {pitch: hz, pitchTime: .035});
      hit.oscillator.addEventListener('ended', () => { if (crush) crush.disconnect(); if (stereo) stereo.disconnect(); }, {once: true});
    },
    rim(bus, v, time, velocity) { noise(bus, bus.layers.rim, time, .27 * velocity, v.decay || .028, 'bandpass', v.cutoff || 1900, 7); },
    clap(bus, v, time, velocity) {
      for (let i = 0; i < 3; i++) noise(bus, bus.layers.clap, time + i * .012, (.12 - i * .015) * velocity, i === 2 ? v.decay || .12 : .011, 'bandpass', 1700, .8);
    },
    stab(bus, v, time, velocity) {
      const cutoff = filter('lowpass', v.lpf || 3800, .9), decay = v.decay || .19, pitches = v.pitches || [0, 3, 7];
      cutoff.frequency.setValueAtTime(v.lpf || 3800, time); cutoff.frequency.exponentialRampToValueAtTime(500, time + decay);
      cutoff.connect(bus.layers.stab);
      let last;
      for (const pitch of pitches) for (const detune of [-7, 7]) last = tone(bus, cutoff, 'sawtooth', frequency(bus.spec.root + pitch), time, .022 * velocity, decay, {detune});
      last.oscillator.addEventListener('ended', () => cutoff.disconnect(), {once: true});
    },
    bass(bus, v, time, velocity, pitch) { tone(bus, bus.layers.bass, 'sine', frequency(bus.spec.root + pitch), time, .25 * velocity, v.decay || .22, {attack: .005}); },
    pad(bus, v, time, velocity) {
      const decay = v.decay || BAR * 4, cutoff = filter('lowpass', v.lpf || 1400), pitches = v.pitches || [0, 3, 7];
      cutoff.connect(bus.layers.pad); cutoff.frequency.setValueAtTime(300, time);
      cutoff.frequency.linearRampToValueAtTime(v.lpf || 1400, time + decay * .4);
      cutoff.frequency.exponentialRampToValueAtTime(300, time + decay);
      let last;
      for (const pitch of pitches) for (const detune of [-5, 5]) {
        const attack = Math.min(1, decay * .2), sustain = Math.max(0, decay * .35 - attack);
        last = tone(bus, cutoff, v.sub ? 'sine' : 'triangle', frequency(bus.spec.root + pitch), time, .028 * velocity, decay * .65, {detune, attack, sustain});
        if (v.chorus) {
          const motion = ctx.createOscillator(), depth = gain(v.chorus * 12 * Math.sign(detune));
          motion.frequency.value = .27; motion.connect(depth); depth.connect(last.oscillator.detune);
          track(bus, motion, time, decay + .05, [depth]);
        }
      }
      last.oscillator.addEventListener('ended', () => cutoff.disconnect(), {once: true});
    },
    ride(bus, v, time, velocity) {
      const band = filter('bandpass', v.cutoff || 6900, 1.3); band.connect(bus.layers.ride);
      let last;
      for (const hz of [213, 317, 453, 617, 821, 1123]) last = tone(bus, band, 'square', hz * 4.2, time, .017 * velocity, v.decay || .22);
      last.oscillator.addEventListener('ended', () => band.disconnect(), {once: true});
    },
    riser(bus, v, time, velocity) {
      const duration = v.decay || BAR * 2, source = ctx.createBufferSource(), band = filter('highpass', 300), env = gain(EPS);
      source.buffer = whiteNoise; source.loop = true; source.connect(band); band.connect(env); env.connect(bus.layers.riser);
      band.frequency.setValueAtTime(300, time); band.frequency.exponentialRampToValueAtTime(9500, time + duration);
      env.gain.setValueAtTime(EPS, time); env.gain.exponentialRampToValueAtTime(.085 * velocity, time + duration - .02);
      env.gain.linearRampToValueAtTime(EPS, time + duration); track(bus, source, time, duration + .02, [band, env]);
    },
    bubble(bus, v, time, velocity) {
      const hz = frequency(72 + Math.floor(random() * 25));
      tone(bus, bus.layers.bubble, 'sine', hz * 1.4, time, .08 * velocity, v.decay || .11, {pitch: hz, pitchTime: .06});
    },
    blip(bus, v, time, velocity, pitch) {
      tone(bus, bus.layers.blip, 'square', frequency(bus.spec.root + pitch), time, .095 * velocity, v.decay || .13);
    },
    woodblock(bus, v, time, velocity) {
      const band = filter('bandpass', v.cutoff || 1100, 4); band.connect(bus.layers.woodblock);
      const hit = tone(bus, band, 'triangle', 870, time, .3 * velocity, v.decay || .035, {pitch: 610, pitchTime: .02});
      hit.oscillator.addEventListener('ended', () => band.disconnect(), {once: true});
    },
    clank(bus, v, time, velocity, pitch) {
      const band = filter('bandpass', 2700, 3); band.connect(bus.layers.clank);
      let last;
      for (const ratio of [1, 1.47, 2.09]) last = tone(bus, band, 'square', frequency(bus.spec.root + pitch) * ratio, time, .07 * velocity, v.decay || .18);
      last.oscillator.addEventListener('ended', () => band.disconnect(), {once: true});
    },
    noise(bus, v, time, velocity) {
      const source = ctx.createBufferSource(), band = filter('lowpass', 1800), env = gain(EPS), duration = v.decay || BAR * 4;
      source.buffer = whiteNoise; source.loop = true; source.connect(band); band.connect(env); env.connect(bus.layers.noise);
      const amplitude = Math.pow(10, (v.levelDb ?? -30) / 20) * Math.sqrt(3) * velocity;
      env.gain.setValueAtTime(EPS, time); env.gain.linearRampToValueAtTime(amplitude, time + .2);
      env.gain.setValueAtTime(amplitude, time + Math.max(.2, duration - .2)); env.gain.linearRampToValueAtTime(EPS, time + duration);
      track(bus, source, time, duration + .02, [band, env]);
    }
  };
  synths.shaker = (bus, voice, time, velocity) => synths.hatC(bus, {...voice, layer: 'shaker'}, time, velocity);
  synths.arp = (bus, voice, time, velocity, pitch) => synths.perc(bus, {...voice, layer: 'arp'}, time, velocity, pitch);
  function phase(spec, bar) {
    const cycle = bar % spec.cycleBars;
    if (spec.cycleBars === 16) return cycle < 4 ? 'establish' : cycle < 8 ? 'withhold' : cycle < 10 ? 'signal' : 'return';
    return cycle < 16 ? 'establish' : cycle < 20 ? 'withhold' : cycle < 22 ? 'signal' : 'return';
  }
  function scheduleBus(bus, step, time) {
    const spec = bus.spec, bar = Math.floor(step / 16), cyclePhase = phase(spec, bar), cycleBar = bar % spec.cycleBars;
    const entering = bus.startStep === null;
    if (entering) bus.startStep = step;
    if (spec.fx.sweep) {
      const progress = (step % (spec.fx.sweepBars * 16)) / (spec.fx.sweepBars * 16 - 1);
      bus.lowpass.frequency.setTargetAtTime(spec.fx.sweep[0] + progress * (spec.fx.sweep[1] - spec.fx.sweep[0]), time, SMOOTH);
    }
    if (bus.spec.id === 'reef' && bus.bubbleBar !== bar) {
      bus.bubbleBar = bar; bus.bubbleSteps = [];
      const count = 1 + Math.floor(random() * 3);
      while (bus.bubbleSteps.length < count) { const slot = Math.floor(random() * 16); if (!bus.bubbleSteps.includes(slot)) bus.bubbleSteps.push(slot); }
    }
    for (const score of bus.score) {
      const {name, voice, pattern} = score;
      const withheld = Array.isArray(spec.withhold) ? spec.withhold[0] : spec.withhold;
      if (cyclePhase === 'withhold' && withheld === name) continue;
      // In the signal stage the missing layer returns quietly for the second bar.
      // The Yards instead subtracts its roll while its two-bar riser announces the return.
      if (cyclePhase === 'signal' && Array.isArray(spec.withhold) && spec.withhold[1] === name) continue;
      if (cyclePhase === 'signal' && !Array.isArray(spec.withhold) && withheld === name && cycleBar % 2 === 0) continue;
      const loopSteps = spec.loopBars * 16, loopStep = step % loopSteps;
      const patternStep = pattern.length > loopSteps ? step : loopStep;
      const index = patternStep % pattern.length;
      let digit = name === 'bubble' ? (bus.bubbleSteps.includes(step % 16) ? '9' : '.') : pattern[index];
      let config = voice;
      // Reconstruct a sustained layer when entering between its written starts.
      if (entering && digit === '.' && (['pad', 'noise'].includes(name) || (name === 'riser' && spec.id === 'core'))) {
        digit = score.first;
        config = {...voice, decay: Math.max(.25, (pattern.length - index) * SIXTEENTH)};
      }
      if (name === 'kick' && spec.id === 'reef') config = {...voice, top: cyclePhase === 'withhold' ? 160 : rideHeading === null ? 500 : 3000};
      if (!digit || digit === '.' || digit === '0') continue;
      const voiceFn = synths[name]; if (!voiceFn) continue;
      const repetitions = Math.floor(patternStep / pattern.length);
      const pitches = voice.pitches || [0], pitch = pitches[(score.prefix[index] + repetitions * score.hits) % pitches.length];
      const swung = swingable.has(name) && step % 2 === 1;
      const when = time + (swung ? spec.swing * SIXTEENTH : 0) + (voice.nudgeMs || 0) / 1000;
      const signalVelocity = cyclePhase === 'signal' && !Array.isArray(spec.withhold) && withheld === name ? .55 : 1;
      const velocity = Number(digit) / 9 * (voice.level ?? 1) * signalVelocity;
      voiceFn(bus, config, when, velocity, pitch);
      if (voice.ratchet) for (let repeat = 1; repeat < voice.ratchet; repeat++) {
        voiceFn(bus, config, when + repeat * SIXTEENTH / 3, velocity * .66, pitch);
        diagnostics.scheduledVoices++; bus.voices++;
      }
      if (spec.fx.gated && bus === active && ['kick', 'stab'].includes(name)) {
        reverbGate.gain.cancelAndHoldAtTime(when);
        reverbGate.gain.linearRampToValueAtTime(1, when + .004);
        reverbGate.gain.setValueAtTime(1, when + spec.fx.gated);
        reverbGate.gain.linearRampToValueAtTime(.08, when + spec.fx.gated + .015);
      }
      diagnostics.scheduledVoices++; bus.voices++;
    }
  }
  function beginTransition(id, time) {
    if (!active || active.id === id) { pending = null; return; }
    outgoing = active; active = createBus(id, 0);
    follow(feedback.gain, active.spec.fx.feedback ?? .35, time);
    if (!active.spec.fx.gated) { reverbGate.gain.cancelAndHoldAtTime(time); follow(reverbGate.gain, 1, time); }
    const duration = BAR * 2, length = 129, fadeIn = new Float32Array(length), fadeOut = new Float32Array(length);
    for (let i = 0; i < length; i++) {
      fadeIn[i] = Math.sin(i / (length - 1) * Math.PI / 2); fadeOut[i] = Math.cos(i / (length - 1) * Math.PI / 2);
    }
    outgoing.fader.gain.setValueCurveAtTime(fadeOut, time, duration);
    active.fader.gain.setValueCurveAtTime(fadeIn, time, duration);
    transition = {from: outgoing.id, to: active.id, start: time, end: time + duration, curve: 'equal-power', bar: Math.round((time - origin) / BAR)};
    diagnostics.switches.push({...transition}); if (diagnostics.switches.length > 64) diagnostics.switches.shift();
    pending = null;
  }
  function scheduler() {
    if (!enabled || !ctx) return;
    if (transition && ctx.currentTime >= transition.end + .2) {
      retire(outgoing); outgoing = null; transition = null;
      if (desired !== active.id) pending = desired;
    }
    // A resumed or backgrounded tab catches up its transport without bursting old notes.
    while (origin + nextStep * SIXTEENTH < ctx.currentTime - .02) { nextStep++; diagnostics.droppedSteps++; }
    while (origin + nextStep * SIXTEENTH < ctx.currentTime + LOOKAHEAD) {
      const time = origin + nextStep * SIXTEENTH;
      if (nextStep % 16 === 0 && pending && !transition) beginTransition(pending, time);
      scheduleBus(active, nextStep, time);
      if (outgoing && transition && time < transition.end) scheduleBus(outgoing, nextStep, time);
      nextStep++; diagnostics.scheduledSteps++;
    }
  }
  function setRoom(id) {
    desired = Object.hasOwn(rooms, id) ? id : 'skyline';
    if (!ctx) return desired;
    pending = desired === active?.id ? null : desired;
    return desired;
  }
  async function toggle(event) {
    if (!event?.isTrusted || !['click', 'keydown', 'pointerup'].includes(event.type)) return enabled;
    if (state === 'starting') return enabled;
    if (enabled) {
      enabled = false; preferred = 'off'; state = 'off'; clearInterval(timer); timer = null;
      master.gain.cancelScheduledValues(ctx.currentTime); follow(master.gain, 0);
      setTimeout(() => { if (!enabled && ctx.state === 'running') ctx.suspend(); }, 300);
    } else {
      state = 'starting'; notify();
      try {
        if (!ctx) createContext();
        await ctx.resume(); enabled = true; preferred = 'on'; state = 'on';
        master.gain.cancelScheduledValues(ctx.currentTime); follow(master.gain, .8);
        scheduler(); timer = setInterval(scheduler, 25);
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
  const api = {
    get ctx() { return ctx; }, get room() { return active?.id || desired; }, get analyser() { return analyser; },
    get enabled() { return enabled; }, get preferred() { return preferred; }, get state() { return state; },
    get transition() { return transition; }, get buses() { return buses; },
    rooms, diagnostics, timeline, layerThresholds, setRoom, toggle, setTimeline, setRideHeading,
    subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener); }
  };
  return api;
})();
