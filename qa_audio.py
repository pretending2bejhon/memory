"""Audio QA with actual PCM, gesture policy, room routing and frame sampling.

The observer is a temporary AudioWorklet loaded from an in-memory Blob. It
records exact 20 ms windows on the audio thread and emits silence on its own
output, so the listening graph is unchanged. No audio files are generated.
"""

import argparse
import json
import math
import time
from itertools import combinations
from pathlib import Path

from qa_browser import Engine, measure_frames

ROOT = Path(__file__).resolve().parent
BAR_SECONDS = 4 * 60 / 140
ROOM_IDS = ("core", "episodic", "semantic", "procedural", "prospective", "working",
            "jhon", "prasma", "branding", "onebrain", "reef", "inbox")

CONTEXT_OBSERVER = """(() => {
  window.__qaContexts = [];
  const Native = window.AudioContext;
  if (Native) {
    class ObservedAudioContext extends Native {
      constructor(...args) { super(...args); window.__qaContexts.push(this); }
    }
    window.AudioContext = ObservedAudioContext;
    if (window.webkitAudioContext === Native) window.webkitAudioContext = ObservedAudioContext;
  }
})();"""

INSTALL_PROBE = """async () => {
  const audio = window.__vc.audio, ctx = audio.ctx;
  if (window.__qaProbe) await window.__qaProbe.destroy();
  const source = `class CityQAPCM extends AudioWorkletProcessor {
    constructor() { super(); this.size = Math.round(sampleRate * .020); this.n = 0;
      this.energy = Array(5).fill(0); this.peak = 0; this.start = 0; this.stopped = false;
      this.port.onmessage = event => { if (event.data === 'stop') {
        this.stopped = true; this.port.postMessage({type: 'stopped'});
      }};
    }
    process(inputs, outputs) {
      if (this.stopped) return false;
      const frames = outputs[0][0].length;
      for (const channel of outputs[0]) channel.fill(0);
      for (let i = 0; i < frames; i++) {
        if (this.n === 0) this.start = (currentFrame + i) / sampleRate;
        for (let k = 0; k < 5; k++) {
          const channels = inputs[k]; let energy = 0;
          for (const channel of channels) {
            const value = channel[i] || 0; energy += value * value;
            if (k === 0) this.peak = Math.max(this.peak, Math.abs(value));
          }
          this.energy[k] += channels.length ? energy / channels.length : 0;
        }
        if (++this.n === this.size) {
          this.port.postMessage({start: this.start,
            end: (currentFrame + i + 1) / sampleRate,
            rms: this.energy.map(value => Math.sqrt(value / this.n)), peak: this.peak});
          this.n = 0; this.energy.fill(0); this.peak = 0;
        }
      }
      return true;
    }
  }
  registerProcessor('city-qa-pcm', CityQAPCM);`;
  if (!window.__qaProbeRegistered) {
    const url = URL.createObjectURL(new Blob([source], {type: 'text/javascript'}));
    try { await ctx.audioWorklet.addModule(url); } finally { URL.revokeObjectURL(url); }
    window.__qaProbeRegistered = true;
  }
  const node = new AudioWorkletNode(ctx, 'city-qa-pcm', {
    numberOfInputs: 5, numberOfOutputs: 1, outputChannelCount: [1],
  });
  const connections = [];
  const probe = {node, bins: [], spectralWeight: 0, spectralMoment: 0,
    spectralSamples: 0, analyser: audio.analyser, started: ctx.currentTime};
  probe.connect = (source, input) => {source.connect(node, 0, input); connections.push([source, input]);};
  probe.connect(audio.analyser, 0); node.connect(ctx.destination);
  node.port.onmessage = event => probe.bins.push(event.data);
  const spectrum = new Float32Array(audio.analyser.frequencyBinCount);
  probe.timer = setInterval(() => {
    audio.analyser.getFloatFrequencyData(spectrum);
    for (let i = 1; i < spectrum.length; i++) {
      const magnitude = Number.isFinite(spectrum[i]) ? Math.pow(10, spectrum[i] / 20) : 0;
      probe.spectralWeight += magnitude;
      probe.spectralMoment += magnitude * i * ctx.sampleRate / audio.analyser.fftSize;
    }
    probe.spectralSamples++;
  }, 25);
  probe.destroy = () => new Promise(resolve => {
    clearInterval(probe.timer);
    node.port.onmessage = event => {
      if (event.data.type !== 'stopped') return;
      for (const [source, input] of connections) { try {source.disconnect(node, 0, input);} catch (_) {} }
      node.disconnect(); node.port.onmessage = null; node.port.close();
      delete window.__qaProbe; resolve({processorStopped: true});
    };
    node.port.postMessage('stop');
  });
  window.__qaProbe = probe;
  return {sampleRate: ctx.sampleRate, windowSamples: Math.round(ctx.sampleRate * .020), start: ctx.currentTime};
}"""

SNAPSHOT_PROBE = """() => {
  const p = window.__qaProbe, audio = window.__vc.audio;
  return {bins: p.bins, room: audio.room, contextState: audio.ctx.state,
    sampleRate: audio.ctx.sampleRate, spectralSamples: p.spectralSamples,
    centroidHz: p.spectralWeight ? p.spectralMoment / p.spectralWeight : 0};
}"""


def audio_state(engine):
    return engine.evaluate("""() => ({
      contextState: window.__vc.audio.ctx?.state || null,
      contextCount: window.__qaContexts.length,
      allContextStates: window.__qaContexts.map(ctx => ctx.state),
      enabled: window.__vc.audio.enabled,
      room: window.__vc.audio.room,
      remembered: localStorage.getItem('vc-sound')
    })""")


def wait_until(engine, expression, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = engine.evaluate(expression)
        if result:
            return result
        engine.wait(.025)
    raise RuntimeError("Timed out waiting for " + expression)


def wait_room(engine, room):
    return wait_until(engine, """() => {
      const a = window.__vc.audio;
      return a.room === %s && (!a.transition || a.ctx.currentTime >= a.transition.end);
    }""" % json.dumps(room), 25)


def dbfs(rms):
    return 20 * math.log10(max(rms, 1e-12))


def summarize_pcm(snapshot, include_bins=True):
    bins = snapshot["bins"]
    rms = math.sqrt(sum(item["rms"][0] ** 2 for item in bins) / max(1, len(bins)))
    levels = [dbfs(item["rms"][0]) for item in bins]
    deltas = [abs(b - a) for a, b in zip(levels, levels[1:])]
    result = {
        "room": snapshot["room"], "contextState": snapshot["contextState"],
        "sampleRate": snapshot["sampleRate"], "windowMs": 20,
        "windowCount": len(bins), "rms": rms, "rmsDbfs": dbfs(rms),
        "centroidHz": snapshot["centroidHz"], "spectralSamples": snapshot["spectralSamples"],
        "peak": max((item["peak"] for item in bins), default=0),
        "maxRawAdjacentRmsDeltaDb": max(deltas, default=0),
        "rawAdjacentWindowsAbove6Db": sum(value > 6 for value in deltas),
    }
    if include_bins:
        result["pcmWindows"] = bins
    return result


def measure_audio(engine, seconds=4, include_bins=False):
    engine.evaluate(INSTALL_PROBE)
    engine.wait(seconds)
    result = summarize_pcm(engine.evaluate(SNAPSHOT_PROBE), include_bins)
    result["probeCleanup"] = engine.evaluate("() => window.__qaProbe.destroy()")
    return result


def measure_transition(engine, target="working"):
    """Jhon's transition, measured from his REEF SESSIONS 002 set: next-bar start, a bass-free bridge,
    a riser, a one-beat cut, and the new kick and bass slamming in on an eight-bar phrase line."""
    engine.evaluate(INSTALL_PROBE)
    requested = engine.evaluate("""target => {
      const a = window.__vc.audio;
      const request = {from: a.room, to: target, requestedAt: a.ctx.currentTime};
      a.setRoom(target); return request;
    }""", target)
    transition = wait_until(engine, """() => {
      const a = window.__vc.audio, t = a.transition;
      if (!t || t.to !== %s) return false;
      const buses = Array.from(a.buses);
      const outgoing = buses.find(b => b.id === t.from), incoming = buses.find(b => b.id === t.to);
      if (!outgoing || !incoming) return false;
      const p = window.__qaProbe;
      p.connect(outgoing.preFade, 1); p.connect(outgoing.postFade, 2);
      p.connect(incoming.preFade, 3); p.connect(incoming.postFade, 4);
      // Keep every mute branch awake so Chromium reports live AudioParam values.
      const keep = a.ctx.createConstantSource(); keep.offset.value = 1e-12;
      for (const bus of [outgoing, incoming]) for (const node of Object.values(bus.mutes)) keep.connect(node);
      keep.start(); window.__qaKeep = keep;
      return {...t, attachedAt: a.ctx.currentTime, low: {outgoing: [...outgoing.low], incoming: [...incoming.low]},
        epoch: a.diagnostics?.epoch ?? a.diagnostics?.origin ?? null, phrase: a.phrase, minBridge: a.minBridge};
    }""" % json.dumps(target), 3)
    samples = []
    while True:
        row = engine.evaluate("""() => {
          const a = window.__vc.audio, t = a.transition, buses = Array.from(a.buses);
          const o = buses.find(b => b.id === %s), i = buses.find(b => b.id === %s);
          const low = bus => bus ? Math.max(...[...bus.low].map(n => bus.mutes[n] ? bus.mutes[n].gain.value : 0)) : null;
          return {time: a.ctx.currentTime, outLow: low(o), inLow: low(i),
            outFader: o ? o.fader.gain.value : null, inFader: i ? i.fader.gain.value : null, cut: a.cut.gain.value};
        }""" % (json.dumps(transition["from"]), json.dumps(target)))
        samples.append(row)
        if row["time"] > transition["drop"] + .6:
            break
        engine.wait(.05)
    snapshot = engine.evaluate(SNAPSHOT_PROBE)
    cleanup = engine.evaluate("() => { window.__qaKeep.stop(); window.__qaKeep.disconnect(); return window.__qaProbe.destroy(); }")
    bins = snapshot["bins"]
    beat = BAR_SECONDS / 4
    start, drop = transition["start"], transition["drop"]
    fade = []
    for item in bins:
        if not (start <= item["start"] and item["end"] <= start + BAR_SECONDS):
            continue
        before_in, after_in = item["rms"][3], item["rms"][4]
        if before_in < 1e-9:
            continue
        progress = ((item["start"] + item["end"]) / 2 - start) / BAR_SECONDS
        fade.append(abs(after_in / before_in - math.sin(progress * math.pi / 2)))
    def level(lo, hi):
        rows = [item["rms"][0] for item in bins if lo <= item["start"] and item["end"] <= hi]
        return dbfs(math.sqrt(sum(value * value for value in rows) / len(rows))) if rows else None
    groove = level(drop - 3 * BAR_SECONDS, drop - BAR_SECONDS)
    cut_level = level(drop - beat + .03, drop - .03)
    after_drop = level(drop + .03, drop + beat)
    outgoing_after = max((item["rms"][2] for item in bins if drop + .05 <= item["start"] and item["end"] <= drop + BAR_SECONDS), default=None)
    epoch = transition.get("epoch")
    bars = lambda t: (t - epoch) / BAR_SECONDS
    start_error = abs(bars(start) - round(bars(start)))
    drop_error = abs(bars(drop) / transition["phrase"] - round(bars(drop) / transition["phrase"]))
    summary = summarize_pcm({**snapshot, "bins": [item for item in bins if start <= item["start"] and item["end"] <= drop + .5]})
    summary.update({"request": requested, "transition": transition, "probeCleanup": cleanup,
        "bridgeBars": (drop - start) / BAR_SECONDS, "startBarPhaseError": start_error, "dropPhrasePhaseError": drop_error,
        "maxIncomingFadeCurveError": max(fade, default=9999), "fadeWindows": len(fade),
        "grooveDbfs": groove, "cutDbfs": cut_level, "afterDropDbfs": after_drop,
        "outgoingPostFadeRmsAfterDrop": outgoing_after, "paramSamples": samples,
        "measurement": "Paired pre/post PCM energy measures the incoming fade-in over its first bar. AudioParam samples every 50 ms follow the kick and bass mutes of both rooms and the master cut. Master PCM compares the groove two bars before the drop with the cut beat and the first beat after it."})
    return summary


def measure_rooms(engine, report):
    """Capture room identities after the transition and shared effect tails."""
    engine.evaluate("() => window.__vc.updateWeek(12)")
    # The music lives in viewer/rooms/<id>.strudel and is expected to change by ear, so the
    # contract pins structure and the engine-side mix, never the patterns themselves.
    definitions = engine.evaluate("""() => Object.fromEntries(Object.entries(window.__vc.audio.rooms)
      .filter(([id]) => id !== 'skyline').map(([id, room]) => [id, {
        title: room.title, root: room.root, cycleBars: room.cycleBars, withhold: room.withhold,
        layers: room.layers, fx: room.fx, code: room.code
      }]))""")
    report["roomDefinitions"] = definitions
    report["checks"]["all twelve room definitions"] = set(definitions) == set(ROOM_IDS)
    expected_roots = dict(zip(ROOM_IDS, (38, 41, 33, 40, 43, 41, 36, 45, 48, 38, 31, 41)))
    report["checks"]["specified room roots"] = all(
        definitions.get(room, {}).get("root") == expected_roots[room] for room in ROOM_IDS)
    report["checks"]["specified room cycles"] = all(
        definitions.get(room, {}).get("cycleBars") == (16 if room == "prospective" else 32)
        for room in ROOM_IDS)
    engine_state = engine.evaluate("""() => {
      const a = window.__vc.audio;
      return {engine: a.diagnostics.engine, ready: a.ready, compileErrors: a.diagnostics.compileErrors,
        loadMs: a.diagnostics.loadMs ?? null, readyMs: a.diagnostics.readyMs ?? null};
    }""")
    report["engine"] = engine_state
    report["checks"]["every room is Strudel code that compiles"] = (
        engine_state["engine"] == "strudel" and engine_state["ready"] and not engine_state["compileErrors"]
        and all("setcpm(140/4)" in definitions.get(room, {}).get("code", "") for room in ROOM_IDS))
    report["checks"]["every room has a kick and at least three layers"] = all(
        "kick" in definitions.get(room, {}).get("layers", []) and len(definitions.get(room, {}).get("layers", [])) >= 3
        for room in ROOM_IDS)
    report["checks"]["every withheld layer exists in its room"] = all(
        all(name in definitions[room]["layers"] for name in
            ([] if definitions[room]["withhold"] is None else
             definitions[room]["withhold"] if isinstance(definitions[room]["withhold"], list) else [definitions[room]["withhold"]]))
        for room in ROOM_IDS if room in definitions)
    contracts = {
        "core": {"withhold": "hatO", "fx.lpf": 9000, "fx.reverb": .30},
        "episodic": {"withhold": "perc", "fx.delay": .5, "fx.reverb": .35},
        "semantic": {"withhold": "bass", "fx.lpf": 7000, "fx.reverb": .6},
        "procedural": {"withhold": "rim", "fx.drive": .35, "fx.reverb": .08},
        "prospective": {"withhold": ["hatO", "perc"], "fx.sweep": [1000, 8000], "fx.sweepBars": 8, "fx.reverb": .25},
        "working": {"withhold": "hatO", "fx.lpf": 12000, "fx.reverb": .2},
        "jhon": {"withhold": "shaker", "fx.lpf": 8000, "fx.reverb": .3},
        "prasma": {"withhold": "stab", "fx.gated": .11, "fx.lpf": 14000, "fx.reverb": .12},
        "branding": {"withhold": "blip", "fx.lpf": 10000, "fx.reverb": .25},
        "onebrain": {"withhold": "arp", "fx.delay": .5, "fx.feedback": .5, "fx.lpf": 9000, "fx.reverb": .35},
        "reef": {"withhold": "hatC", "fx.lfo.frequency": .05, "fx.lfo.min": 500, "fx.lfo.max": 3000, "fx.reverb": .6},
        "inbox": {"withhold": None, "fx.lpf": 4000, "fx.reverb": .5},
    }
    mismatches = []
    for room, expected in contracts.items():
        for field, value in expected.items():
            actual = definitions.get(room, {})
            for part in field.split("."):
                actual = actual.get(part) if isinstance(actual, dict) else None
            if actual != value:
                mismatches.append({"room": room, "field": field, "expected": value, "actual": actual})
    report["roomContract"] = {"assertions": sum(len(fields) for fields in contracts.values()), "mismatches": mismatches}
    report["checks"]["room mix effects and withhold match table"] = not mismatches
    measurements = {}
    for room in ROOM_IDS:
        print("Measuring room: " + room, flush=True)
        requested_at = engine.evaluate("""id => {
          const a = window.__vc.audio; a.setRoom(id); return a.ctx.currentTime;
        }""", room)
        # A switch can take up to twelve bars (20.6 seconds) to reach its phrase drop.
        # Preserve the requested four-second wait, then wait for the drop and let
        # the shared 2.4-second synthetic reverb clear before measuring identity.
        engine.wait(4)
        wait_room(engine, room)
        settled_at = engine.evaluate("window.__vc.audio.ctx.currentTime")
        engine.wait(2.4)
        capture_at = engine.evaluate("window.__vc.audio.ctx.currentTime")
        epoch = engine.evaluate("window.__vc.audio.diagnostics.epoch")
        capture_bar = math.floor((capture_at - epoch) / BAR_SECONDS)
        metrics = measure_audio(engine, seconds=4)
        metrics["frames"] = measure_frames(engine)
        metrics.update({"requestedAt": requested_at, "transitionSettledAt": settled_at,
                        "captureStartedAt": capture_at, "captureSeconds": 4,
                        "captureTransportBar": capture_bar,
                        "captureCycleBar": capture_bar % definitions[room]["cycleBars"],
                        "postTransitionTailWaitSeconds": 2.4})
        measurements[room] = metrics
        print(f"Measured {room}: {metrics['rmsDbfs']:.3f} dBFS; "
              f"{metrics['centroidHz']:.3f} Hz centroid; {metrics['frames']['fps']:.3f} fps", flush=True)
    report["rooms"] = measurements
    report["fingerprintMethod"] = "For each room: request it, wait four seconds, finish any remaining transition up to its drop, let the 2.4-second shared reverb tail clear, then record four seconds of actual PCM and averaged analyser spectrum. No outgoing room is included in the identity measurement."
    report["checks"]["every room audible above -40 dBFS"] = all(row["rmsDbfs"] > -40 and row["windowCount"] >= 190 for row in measurements.values())
    report["checks"]["every room context running"] = all(row["contextState"] == "running" for row in measurements.values())
    report["checks"]["every room above 55 fps"] = all(row["frames"]["fps"] > 55 for row in measurements.values())
    pairs = []
    for first, second in combinations(ROOM_IDS, 2):
        left, right = measurements[first], measurements[second]
        relative_centroid = abs(left["centroidHz"] - right["centroidHz"]) / max(1e-9, min(left["centroidHz"], right["centroidHz"]))
        rms_difference = abs(left["rmsDbfs"] - right["rmsDbfs"])
        pairs.append({"rooms": [first, second], "centroidDifferencePercent": 100 * relative_centroid,
                      "rmsDifferenceDb": rms_difference,
                      "passed": relative_centroid >= .08 or rms_difference >= 2})
    report["roomPairs"] = pairs
    report["checks"]["all 66 room pairs differ by 8 percent centroid or 2 dB RMS"] = len(pairs) == 66 and all(pair["passed"] for pair in pairs)
    voice_state = engine.evaluate("""() => ({voiceErrors: window.__vc.audio.diagnostics.voiceErrors,
      lastVoiceError: window.__vc.audio.diagnostics.lastVoiceError ?? null,
      scheduledVoices: window.__vc.audio.diagnostics.scheduledVoices})""")
    report["voices"] = voice_state
    report["checks"]["every Strudel voice scheduled without error"] = voice_state["voiceErrors"] == 0 and voice_state["scheduledVoices"] > 0


def measure_timeline(engine, report):
    engine.evaluate("() => window.__vc.audio.setRoom('episodic')")
    wait_room(engine, "episodic")
    engine.evaluate("""() => {
      const a = window.__vc.audio, bus = a.buses.find(bus => bus.id === 'episodic');
      // An inaudible -240 dB source keeps intermittent/silent branches active.
      // Otherwise Chromium can expose a stale AudioParam.value until the next
      // scheduled note wakes that graph branch, despite correct automation.
      const source = a.ctx.createConstantSource(); source.offset.value = 1e-12;
      for (const layer of Object.values(bus.layers)) source.connect(layer);
      source.start(); window.__qaTimelineSource = source;
    }""")
    engine.wait(1.25)
    rows = []
    for week in range(13):
        row = engine.evaluate("""week => {
          const v = window.__vc, a = v.audio;
          const bus = a.buses.find(bus => bus.id === 'episodic');
          const before = {cutoff: bus.timelineLowpass.frequency.value,
            reverb: bus.reverb.gain.value, time: a.ctx.currentTime};
          v.updateWeek(week);
          const district = v.nodes.filter(node => node.district === 'episodic');
          const existing = district.filter(node => node.state !== 'absent');
          const lit = existing.filter(node => node.light > .5);
          return {week, total: district.length, existing: existing.length, lit: lit.length,
            density: existing.length / district.length,
            brightness: existing.length ? lit.length / existing.length : 0,
            supplied: {...a.timeline.episodic}, busTimeline: {...bus.timeline},
            before, targetCutoff: bus.cutoffTarget, targetReverb: bus.reverbTarget,
            appliedAt: bus.timelineUpdatedAt ?? a.ctx.currentTime,
            samples: [{time: a.ctx.currentTime, cutoff: bus.timelineLowpass.frequency.value,
                       reverb: bus.reverb.gain.value}]};
        }""", week)
        for delay in (.125, .125, 1):
            engine.wait(delay)
            row["samples"].append(engine.evaluate("""() => {
              const a = window.__vc.audio, bus = a.buses.find(bus => bus.id === 'episodic');
              return {time: a.ctx.currentTime, cutoff: bus.timelineLowpass.frequency.value,
                      reverb: bus.reverb.gain.value};
            }"""))
        row["layerGains"] = engine.evaluate("""() => Object.fromEntries(Object.entries(
          window.__vc.audio.buses.find(bus => bus.id === 'episodic').layers)
          .map(([name, gain]) => [name, gain.gain.value]))""")
        row["parameterErrors"] = []
        for sample in row["samples"]:
            elapsed = max(0, sample["time"] - row["appliedAt"])
            expected_cutoff = row["targetCutoff"] + (row["before"]["cutoff"] - row["targetCutoff"]) * math.exp(-elapsed / .25)
            expected_reverb = row["targetReverb"] + (row["before"]["reverb"] - row["targetReverb"]) * math.exp(-elapsed / .25)
            row["parameterErrors"].append({"elapsedSeconds": elapsed,
                "cutoffErrorHz": abs(sample["cutoff"] - expected_cutoff),
                "reverbError": abs(sample["reverb"] - expected_reverb)})
        rows.append(row)
    report["archiveTimeline"] = rows
    exact_stats = all(
        row["supplied"][key] == row[key]
        for row in rows for key in ("total", "existing", "lit", "density", "brightness"))
    bus_stats = all(abs(row["busTimeline"][key] - row[key]) < 1e-9
                    for row in rows for key in ("density", "brightness"))
    report["checks"]["timeline aggregates match renderer states"] = exact_stats and bus_stats
    report["checks"]["timeline cutoff and reverb formulas"] = all(
        abs(row["targetCutoff"] - (600 + row["brightness"] * 11400)) < 1e-6
        and abs(row["targetReverb"] - (.15 + (1 - row["brightness"]) * .4)) < 1e-9
        for row in rows)
    ordered = sorted(rows, key=lambda row: row["brightness"])
    report["brightnessOrder"] = [{"week": row["week"], "brightness": row["brightness"], "cutoff": row["targetCutoff"]} for row in ordered]
    report["checks"]["cutoff increases monotonically with brightness"] = all(
        right["targetCutoff"] >= left["targetCutoff"] - 1e-6 for left, right in zip(ordered, ordered[1:]))
    report["timelineMethod"] = "Weeks 0 through 12 are measured in order. Monotonicity is checked against brightness, since elapsed weeks can fade existing buildings. Actual AudioParam values at immediate, 125 ms, 250 ms and 1.25 s offsets are compared with the 250 ms setTargetAtTime exponential, allowing only audio-quantum rounding. A temporary -240 dB ConstantSource keeps intermittent layer branches active so Chromium reports current gain values instead of dormant-node snapshots; it is removed afterward."
    report["checks"]["timeline parameters use 250 ms smoothing"] = all(
        error["cutoffErrorHz"] < 100 and error["reverbError"] < .005
        for row in rows for error in row["parameterErrors"])
    report["checks"]["timeline parameters never jump to new target"] = all(
        abs(row["samples"][0]["cutoff"] - row["before"]["cutoff"]) < 30 + abs(row["targetCutoff"] - row["before"]["cutoff"]) * .08
        and abs(row["samples"][0]["reverb"] - row["before"]["reverb"]) < .001 + abs(row["targetReverb"] - row["before"]["reverb"]) * .08
        for row in rows)
    thresholds = {"kick": 0, "hatC": .15, "perc": .30, "hatO": .45, "stab": .60, "clap": .75, "pad": .90,
                  "shaker": .15, "woodblock": .30, "clank": .30, "blip": .30, "arp": .30,
                  "bubble": .30, "rim": .30, "noise": .15, "ride": .45, "riser": .30, "bass": .60}
    report["checks"]["timeline layer threshold order"] = all(
        abs(value - int(row["density"] >= thresholds[name])) < .02
        for row in rows for name, value in row["layerGains"].items() if name in thresholds)
    engine.evaluate("() => window.__vc.updateWeek(12)")
    engine.evaluate("() => { window.__qaTimelineSource.stop(); window.__qaTimelineSource.disconnect(); delete window.__qaTimelineSource; }")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8765/viewer/")
    parser.add_argument("--prefix", default="")
    parser.add_argument("--phase", choices=("p1", "p2"), default="p2")
    args = parser.parse_args()
    if any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for character in args.prefix):
        parser.error("--prefix must contain only letters, digits, hyphens or underscores")
    output = ROOT / "renders" / "qa"
    output.mkdir(parents=True, exist_ok=True)
    destination = output / ((args.prefix + "-" if args.prefix else "") + "audio-report.json")
    report = {"phase": args.phase, "url": args.url, "checks": {}}
    try:
        with Engine(width=1440, height=900) as engine:
            engine.page.add_init_script(CONTEXT_OBSERVER)
            engine.goto(args.url)
            engine.ready()
            engine.wait(5)
            report["idleFiveSeconds"] = audio_state(engine)
            report["checks"]["no context before gesture"] = report["idleFiveSeconds"]["contextCount"] == 0 and report["idleFiveSeconds"]["contextState"] is None
            engine.click("#sound")
            engine.wait(.3)
            report["firstClick"] = audio_state(engine)
            report["checks"]["gesture starts context"] = report["firstClick"]["contextState"] == "running" and report["firstClick"]["contextCount"] == 1
            engine.page.keyboard.press("m")
            engine.wait(.3)
            report["keyboardOff"] = audio_state(engine)
            engine.page.keyboard.press("m")
            engine.wait(.3)
            report["keyboardOn"] = audio_state(engine)
            report["checks"]["keyboard and remembered choice"] = report["keyboardOff"]["enabled"] is False and report["keyboardOff"]["remembered"] == "off" and report["keyboardOn"]["enabled"] is True and report["keyboardOn"]["remembered"] == "on"
            engine.page.reload(wait_until="domcontentloaded")
            engine.ready()
            engine.wait(5)
            report["rememberedOnBeforeGesture"] = audio_state(engine)
            report["checks"]["remembered on still waits for gesture"] = report["rememberedOnBeforeGesture"]["contextCount"] == 0 and report["rememberedOnBeforeGesture"]["contextState"] is None and report["rememberedOnBeforeGesture"]["remembered"] == "on"
            engine.click("#sound")
            engine.wait(.5)
            report["skyline"] = measure_audio(engine)
            report["checks"]["skyline audible and running"] = report["skyline"]["rmsDbfs"] > -40 and report["skyline"]["contextState"] == "running"
            if args.phase == "p1":
                engine.evaluate("() => window.__vc.audio.setRoom('__qa_missing_room__')")
                engine.wait(.2)
                report["fallback"] = audio_state(engine)
                report["checks"]["unimplemented district falls back to skyline"] = report["fallback"]["room"] == "skyline"
                engine.click(".chip:first-child")
            report["transition"] = measure_transition(engine)
            fade = report["transition"]
            samples = fade["paramSamples"]
            beat = BAR_SECONDS / 4
            start, drop = fade["transition"]["start"], fade["transition"]["drop"]
            report["checks"]["transition starts at next bar"] = fade["transition"]["start"] >= fade["request"]["requestedAt"] and fade["transition"]["start"] - fade["request"]["requestedAt"] <= BAR_SECONDS + .12 and fade["startBarPhaseError"] < 1e-5
            report["checks"]["drop lands on an eight-bar phrase after a four to eleven bar bridge"] = fade["dropPhrasePhaseError"] < 1e-5 and 4 - 1e-6 <= fade["bridgeBars"] <= 11 + 1e-6
            report["checks"]["new room's upper layers fade in over one bar"] = fade["fadeWindows"] > 60 and fade["maxIncomingFadeCurveError"] < .05
            bridge = [row for row in samples if start + beat + .05 <= row["time"] <= drop - .05]
            before_drop = [row for row in samples if row["time"] <= drop - .05]
            after = [row for row in samples if row["time"] >= drop + .05 and row["inLow"] is not None]
            report["checks"]["kick and bass out through the bridge"] = len(bridge) > 20 and all(row["outLow"] is not None and row["outLow"] <= .01 for row in bridge) and all(row["inLow"] is not None and row["inLow"] <= .01 for row in before_drop)
            report["checks"]["new kick and bass slam in on the drop"] = len(after) > 3 and all(row["inLow"] >= .99 for row in after)
            report["checks"]["one-beat cut before the drop, 20 dB deep"] = fade["grooveDbfs"] is not None and fade["cutDbfs"] is not None and fade["grooveDbfs"] - fade["cutDbfs"] >= 20 and fade["afterDropDbfs"] is not None and fade["afterDropDbfs"] > fade["cutDbfs"] + 20
            report["checks"]["old room gone after the drop"] = fade["outgoingPostFadeRmsAfterDrop"] is not None and fade["outgoingPostFadeRmsAfterDrop"] < 1e-4
            report["checks"]["no clipping through the transition"] = fade["peak"] < 1
            report["working"] = measure_audio(engine)
            report["checks"]["working audible and running"] = report["working"]["rmsDbfs"] > -40 and report["working"]["contextState"] == "running"
            engine.click('.chip[data-d="working"]')
            engine.click("#ride")
            engine.wait(.2)
            report["ride"] = audio_state(engine)
            report["checks"]["ride routes to district room"] = report["ride"]["room"] == "working"
            engine.page.keyboard.press("Escape")
            wait_room(engine, "skyline")
            report["rideExit"] = audio_state(engine)
            report["checks"]["ride exit returns to skyline"] = report["rideExit"]["room"] == "skyline"
            engine.click(".chip:first-child")
            engine.evaluate("() => window.__vc.audio.setRoom('working')")
            wait_room(engine, "working")
            engine.wait(.5)
            report["frames"] = measure_frames(engine)
            report["checks"]["sound-on frame rate above 55 fps"] = report["frames"]["fps"] > 55
            if args.phase == "p2":
                measure_rooms(engine, report)
                measure_timeline(engine, report)
            report["errors"] = engine.errors
            report["checks"]["zero page and console errors"] = not engine.errors
    except Exception as error:
        report["fatalError"] = type(error).__name__ + ": " + str(error)
        report["checks"]["harness completed"] = False
        if "engine" in locals():
            report["errors"] = engine.errors
    report["failedChecks"] = [name for name, passed in report["checks"].items() if not passed]
    report["passed"] = not report["failedChecks"]
    destination.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    # Exact PCM evidence stays in the report; console output stays reviewable.
    compact = dict(report)
    if "transition" in compact:
        compact["transition"] = {key: value for key, value in report["transition"].items()
                                 if key not in ("pcmWindows", "paramSamples")}
    if "roomDefinitions" in compact:
        compact["roomDefinitions"] = {room: {key: value for key, value in definition.items()
            if key not in ("voices", "fx", "code", "layers")} for room, definition in report["roomDefinitions"].items()}
    if "archiveTimeline" in compact:
        compact["archiveTimeline"] = [{"week": row["week"], "existing": row["existing"],
            "lit": row["lit"], "density": row["density"], "brightness": row["brightness"],
            "targetCutoff": row["targetCutoff"], "targetReverb": row["targetReverb"],
            "maxCutoffSmoothingErrorHz": max(error["cutoffErrorHz"] for error in row["parameterErrors"]),
            "maxReverbSmoothingError": max(error["reverbError"] for error in row["parameterErrors"])}
            for row in report["archiveTimeline"]]
    print(json.dumps(compact, indent=2, allow_nan=False))
    print("Evidence: " + str(destination.relative_to(ROOT)))
    return int(not report["passed"])


if __name__ == "__main__":
    raise SystemExit(main())
