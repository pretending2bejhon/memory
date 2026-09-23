// The engine already computes the bridge start bar; the next phrase allows four bridge bars.
function nextDrop(startBar) { return Math.ceil((startBar + 4) / 8) * 8; }

function createBeat(audio) {
  'use strict';
  const BPM = 140, BEAT = 60 / BPM, BAR = BEAT * 4;
  const events = {beat: [], bar: [], phrase: [], bridge: [], riser: [], cut: [], drop: [], hit: []};
  const effects = {kick: 'pulse', clap: 'flash', hatC: 'sparkle', hatO: 'sparkle',
    stab: 'laser fan', pad: 'aurora', bass: 'grid floor'};
  const snapshot = {bar: 0, beat: 0, sixteenth: 0, phase: 0, barPhase: 0,
    phraseBar: 0, cycleBar: 0, totalBeats: 0, seconds: 0};
  const transition = {from: 'skyline', to: 'skyline', start: 0, riser: 0, cut: 0,
    drop: 0, bar: 0, dropBar: 0, bridgeBars: 0, stage: 'groove', source: 'silent',
    intensity: .5, active: false, serial: 0, emitted: 0};
  const silentSlots = Array.from({length: 16}, () => ({room: 'skyline', layer: '', time: 0,
    gain: .25, sequence: 0, released: true, source: 'silent', effect: '',
    audibleAt: 0, releasedAt: 0, frame: 0, lateMs: 0}));
  const startMs = performance.now();
  const diagnostics = {frame: 0, releasedHits: 0, audioHits: 0, silentHits: 0, lateHits: 0,
    maxHitLateMs: 0, ringDropped: 0, barSeconds: BAR, silentOriginMs: startMs,
    source: 'silent', sourceChanges: 0, phaseCorrectionSeconds: 0, correctionStartMs: startMs, audioErrorSeconds: 0, outputLatency: 0,
    outputTimestamp: false, lastFrameMs: 0, lastUpdateMs: startMs, frameGapMs: 0};
  let frameMs = startMs, lastMs = startMs, elapsed = 0, anchorMs = startMs, anchorSeconds = 0;
  let sound = false, correction = 0, correctionStart = startMs, previousBeat = -1, previousBar = -1;
  let silentEighth = -1, silentWrite = 0, room = audio.desired || 'skyline', desired = room;
  let audioStart = -Infinity, audioDrop = -Infinity, audioTo = '', outputNow = 0;
  const modulo = (value, divisor) => ((value % divisor) + divisor) % divisor;
  function emit(name, value) {
    const list = events[name];
    for (let i = 0; i < list.length; i++) list[i](value);
  }
  // getOutputTimestamp already describes the sample currently leaving the device.
  // Subtracting outputLatency again would delay the picture twice. Older engines use
  // currentTime minus their reported output latency as the fallback mapping.
  function audibleTime(atMs = performance.now()) {
    const ctx = audio.ctx;
    if (!ctx) return 0;
    const clock = audio.outputClock;
    diagnostics.outputLatency = clock.outputLatency;
    diagnostics.outputTimestamp = clock.timestamp;
    return clock.contextTime + (atMs - clock.performanceTime) / 1000;
  }
  function clockSeconds(atMs, audioTime) {
    if (!sound) return anchorSeconds + (atMs - anchorMs) / 1000;
    const blend = Math.min(1, Math.max(0, (atMs - correctionStart) / (BAR * 1000)));
    return audioTime - audio.origin + correction * (1 - blend);
  }
  function setSnapshot(seconds) {
    snapshot.seconds = seconds; snapshot.totalBeats = seconds / BEAT;
    const wholeBeat = Math.floor(snapshot.totalBeats);
    snapshot.bar = Math.floor(snapshot.totalBeats / 4);
    snapshot.beat = modulo(wholeBeat, 4); snapshot.sixteenth = modulo(Math.floor(snapshot.totalBeats * 4), 16);
    snapshot.phase = modulo(snapshot.totalBeats, 1); snapshot.barPhase = modulo(seconds / BAR, 1);
    snapshot.phraseBar = modulo(snapshot.bar, 8);
    snapshot.cycleBar = modulo(snapshot.bar, sound ? (audio.rooms[audio.room]?.cycleBars || 32) : 32);
  }
  function startSilentTransition(id) {
    desired = id;
    if (transition.active && transition.source === 'silent') {
      // Preserve the phrase line when the visitor retargets a silent bridge.
      if (id === transition.from) { transition.active = false; transition.stage = 'groove'; room = id; }
      else transition.to = id;
      return;
    }
    if (id === room) return;
    transition.from = room; transition.to = id; transition.bar = snapshot.bar + 1;
    transition.dropBar = nextDrop(transition.bar); transition.start = transition.bar * BAR;
    transition.drop = transition.dropBar * BAR; transition.riser = Math.max(transition.start, transition.drop - 4 * BAR);
    transition.cut = transition.drop - BEAT; transition.bridgeBars = transition.dropBar - transition.bar;
    transition.stage = 'pending'; transition.source = 'silent'; transition.intensity = .5;
    transition.active = true; transition.emitted = 0; transition.serial++;
  }
  function updateTransition() {
    const tr = audio.transition;
    if (sound && tr && (tr.start !== audioStart || tr.drop !== audioDrop || tr.to !== audioTo)) {
      const same = tr.start === audioStart && tr.drop === audioDrop;
      audioStart = tr.start; audioDrop = tr.drop; audioTo = tr.to;
      transition.from = tr.from; transition.to = tr.to; transition.bar = tr.bar;
      transition.dropBar = tr.dropBar; transition.bridgeBars = tr.bridgeBars;
      transition.start = tr.start; transition.drop = tr.drop;
      transition.riser = Math.max(tr.start, tr.drop - 4 * BAR); transition.cut = tr.drop - BEAT;
      transition.source = 'audio'; transition.intensity = 1; transition.active = true;
      if (!same) { transition.emitted = 0; transition.stage = 'pending'; transition.serial++; }
    }
    if (sound && !tr && transition.active && transition.source === 'audio' &&
        outputNow < transition.drop && audio.ctx.currentTime < transition.drop) {
      transition.active = false; transition.stage = 'groove'; room = audio.room;
    }
    if (!sound && audio.desired !== desired) startSilentTransition(audio.desired);
    if (!transition.active) return;
    const position = transition.source === 'audio' ? outputNow : elapsed;
    if (!(transition.emitted & 1) && position >= transition.start) {
      transition.emitted |= 1; transition.stage = 'bridge'; emit('bridge', transition);
    }
    if (!(transition.emitted & 2) && position >= transition.riser) {
      transition.emitted |= 2; transition.stage = 'riser'; emit('riser', transition);
    }
    if (!(transition.emitted & 4) && position >= transition.cut) {
      transition.emitted |= 4; transition.stage = 'cut'; emit('cut', transition);
    }
    if (!(transition.emitted & 8) && position >= transition.drop) {
      transition.emitted |= 8; transition.stage = 'drop'; room = transition.to; emit('drop', transition);
    }
    if (position >= transition.drop + BAR) { transition.active = false; transition.stage = 'groove'; }
  }
  function release(slot, audibleAt) {
    slot.effect = effects[slot.layer] || ''; slot.audibleAt = audibleAt;
    slot.releasedAt = frameMs; slot.frame = diagnostics.frame; slot.lateMs = Math.max(0, frameMs - audibleAt);
    diagnostics.releasedHits++;
    if (slot.source === 'audio') {
      diagnostics.audioHits++;
      diagnostics.maxHitLateMs = Math.max(diagnostics.maxHitLateMs, slot.lateMs);
      if (slot.lateMs > diagnostics.frameGapMs + 2) diagnostics.lateHits++;
    } else diagnostics.silentHits++;
    emit('hit', slot);
  }
  function audioHits() {
    const ring = audio.hitRing;
    // Layer query order is not time order. Scan the small scheduled lookahead rather
    // than block an earlier hit behind a later event from another layer.
    for (let i = ring.read; i < ring.written; i++) {
      const slot = ring.slots[i % ring.capacity];
      if (slot.sequence !== i || slot.released || slot.time > outputNow) continue;
      slot.released = true; release(slot, frameMs + (slot.time - outputNow) * 1000);
    }
    while (ring.read < ring.written && ring.slots[ring.read % ring.capacity].released) ring.read++;
    diagnostics.ringDropped = ring.dropped;
  }
  function silentHit(layer, seconds) {
    const slot = silentSlots[silentWrite++ % silentSlots.length];
    slot.room = room; slot.layer = layer; slot.time = seconds; slot.gain = .25; slot.sequence = silentWrite;
    release(slot, frameMs - (elapsed - seconds) * 1000);
  }
  function silentHits() {
    const eighth = Math.floor(elapsed / (BEAT * .5));
    if (eighth < silentEighth || eighth - silentEighth > 16) silentEighth = eighth - 1;
    for (let i = silentEighth + 1; i <= eighth; i++) {
      const seconds = i * BEAT * .5;
      if (i % 2) silentHit('hatC', seconds);
      else {
        silentHit('kick', seconds);
        if (modulo(i / 2, 4) === 1 || modulo(i / 2, 4) === 3) silentHit('clap', seconds);
      }
    }
    silentEighth = eighth;
  }
  function update(atMs = performance.now()) {
    frameMs = atMs; diagnostics.frame++; diagnostics.frameGapMs = Math.max(0, frameMs - lastMs);
    diagnostics.lastFrameMs = frameMs; diagnostics.lastUpdateMs = frameMs; lastMs = frameMs;
    const enabled = !!(audio.enabled && audio.ctx?.state === 'running');
    outputNow = enabled ? audibleTime(frameMs) : 0;
    if (enabled !== sound) {
      const current = sound ? elapsed + diagnostics.frameGapMs / 1000 : clockSeconds(frameMs, outputNow);
      if (enabled) {
        const target = outputNow - audio.origin;
        correction = modulo(current - target + BAR / 2, BAR) - BAR / 2;
        correctionStart = frameMs; transition.active = false; transition.stage = 'groove';
        audioStart = -Infinity; audioDrop = -Infinity; audioTo = ''; room = audio.room;
      } else {
        anchorSeconds = current; anchorMs = frameMs;
        if (transition.active && transition.source === 'audio') {
          const shift = current - audibleTime(frameMs);
          transition.start += shift; transition.riser += shift; transition.cut += shift; transition.drop += shift;
          transition.source = 'silent'; transition.intensity = .5;
        }
        // Reconcile any room request the audio scheduler has not started yet.
        desired = transition.active ? transition.to : room;
        silentEighth = Math.floor(current / (BEAT * .5));
        // Already scheduled notes stop being audible once Sound is disabled.
        for (let i = audio.hitRing.read; i < audio.hitRing.written; i++) audio.hitRing.slots[i % audio.hitRing.capacity].released = true;
        audio.hitRing.read = audio.hitRing.written;
      }
      sound = enabled; diagnostics.source = sound ? 'audio' : 'silent'; diagnostics.sourceChanges++;
      diagnostics.phaseCorrectionSeconds = correction; diagnostics.correctionStartMs = frameMs;
      previousBeat = -1; previousBar = -1;
    }
    elapsed = clockSeconds(frameMs, outputNow); setSnapshot(elapsed);
    diagnostics.audioErrorSeconds = sound ? elapsed - (outputNow - audio.origin) : 0;
    const wholeBeat = Math.floor(snapshot.totalBeats);
    if (wholeBeat !== previousBeat) { previousBeat = wholeBeat; emit('beat', snapshot); }
    if (snapshot.bar !== previousBar) {
      previousBar = snapshot.bar; emit('bar', snapshot);
      if (snapshot.phraseBar === 0) emit('phrase', snapshot);
    }
    updateTransition();
    if (sound) audioHits(); else silentHits();
    return snapshot;
  }
  return {update, now: () => snapshot, seconds: () => elapsed, audibleTime, nextDrop,
    get room() { return room; }, get sound() { return sound; }, transition, diagnostics,
    bpm: BPM, beatSeconds: BEAT, barSeconds: BAR,
    setRoom(id) { audio.setRoom(id); if (!sound) startSilentTransition(audio.desired); },
    on(name, fn) {
      if (!events[name]) throw new Error('Unknown beat event: ' + name);
      events[name].push(fn);
      return () => { const index = events[name].indexOf(fn); if (index >= 0) events[name].splice(index, 1); };
    }};
}
