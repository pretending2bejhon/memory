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
    }""" % json.dumps(room), 8)


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


def measure_crossfade(engine, target="working"):
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
      const outgoing = buses.find(b => b.id === t.from);
      const incoming = buses.find(b => b.id === t.to);
      if (!outgoing || !incoming) return false;
      const p = window.__qaProbe;
      p.connect(outgoing.preFade, 1); p.connect(outgoing.postFade, 2);
      p.connect(incoming.preFade, 3); p.connect(incoming.postFade, 4);
      return {...t, attachedAt: a.ctx.currentTime,
        epoch: a.diagnostics?.epoch ?? a.diagnostics?.origin ?? null};
    }""" % json.dumps(target), 3)
    current = engine.evaluate("window.__vc.audio.ctx.currentTime")
    engine.wait(max(0, transition["end"] - current) + .04)
    snapshot = engine.evaluate(SNAPSHOT_PROBE)
    cleanup = engine.evaluate("() => window.__qaProbe.destroy()")
    bins = [item for item in snapshot["bins"]
            if item["start"] >= transition["start"] and item["end"] <= transition["end"]]
    snapshot["bins"] = bins
    summary = summarize_pcm(snapshot)
    summary["probeCleanup"] = cleanup
    levels = []
    missing = []
    for item in bins:
        master, before_out, after_out, before_in, after_in = item["rms"]
        if before_out < 1e-9 or before_in < 1e-9:
            missing.append({"start": item["start"], "beforeOut": before_out, "beforeIn": before_in})
            continue
        outgoing = after_out / before_out
        incoming = after_in / before_in
        combined = math.sqrt(outgoing * outgoing + incoming * incoming)
        progress = ((item["start"] + item["end"]) / 2 - transition["start"]) / (transition["end"] - transition["start"])
        levels.append({"start": item["start"], "outgoingGain": outgoing,
                       "incomingGain": incoming, "combinedPowerDb": dbfs(combined),
                       "outgoingCurveError": abs(outgoing - math.cos(progress * math.pi / 2)),
                       "incomingCurveError": abs(incoming - math.sin(progress * math.pi / 2))})
    deltas = [abs(right["combinedPowerDb"] - left["combinedPowerDb"])
              for left, right in zip(levels, levels[1:])]
    epoch = transition.get("epoch")
    phase_error = None if epoch is None else abs((transition["start"] - epoch) / BAR_SECONDS - round((transition["start"] - epoch) / BAR_SECONDS))
    summary.update({"request": requested, "transition": transition,
        "transitionDurationSeconds": transition["end"] - transition["start"],
        "barPhaseError": phase_error,
        "measuredGainWindows": levels, "missingInputWindows": missing,
        "maxSwitchEnvelopeDeltaDb": max(deltas, default=9999),
        "maxEqualPowerCurveError": max((max(row["outgoingCurveError"], row["incomingCurveError"]) for row in levels), default=9999),
        "measurement": "Paired pre/post PCM energy measures the applied room gains. The 6 dB switch gate uses their combined equal-power envelope. Raw master RMS jumps from percussive attacks remain recorded separately."})
    return summary


def measure_rooms(engine, report):
    """Capture room identities after the transition and shared effect tails."""
    engine.evaluate("() => window.__vc.updateWeek(12)")
    definitions = engine.evaluate("""() => Object.fromEntries(Object.entries(window.__vc.audio.rooms)
      .filter(([id]) => id !== 'skyline').map(([id, room]) => [id, {
        root: room.root, swing: room.swing, loopBars: room.loopBars,
        cycleBars: room.cycleBars, withhold: room.withhold, densityCap: room.densityCap,
        voices: room.voices, fx: room.fx
      }]))""")
    report["roomDefinitions"] = definitions
    report["checks"]["all twelve room definitions"] = set(definitions) == set(ROOM_IDS)
    expected_roots = dict(zip(ROOM_IDS, (38, 41, 33, 40, 43, 41, 36, 45, 48, 38, 31, 41)))
    expected_swings = dict(zip(ROOM_IDS, (.50, .58, .52, .50, .54, .56, .60, .53, .55, .51, .55, .50)))
    report["checks"]["specified room roots and swing"] = all(
        definitions.get(room, {}).get("root") == expected_roots[room]
        and definitions.get(room, {}).get("swing") == expected_swings[room]
        for room in ROOM_IDS)
    report["checks"]["specified room cycles and Signal Row loop"] = all(
        definitions.get(room, {}).get("cycleBars") == (16 if room == "prospective" else 32)
        for room in ROOM_IDS) and definitions.get("branding", {}).get("loopBars") == 4
    contracts = {
        "core": {"withhold": "hatO", "densityCap": .4, "voices.kick.pattern": "9...9...9...9...", "voices.perc.pitches": [7], "voices.pad.sub": True, "fx.lpf": 9000, "fx.reverb": .30},
        "episodic": {"withhold": "perc", "voices.perc.pattern": "9.5.9..5.9.5..9.", "voices.perc.pitches": [0, 5], "voices.stab.pitches": [0, 3, 7], "voices.stab.lpf": 2400, "voices.noise.levelDb": -30, "fx.delay": .5, "fx.reverb": .35},
        "semantic": {"withhold": "bass", "voices.bass.pattern": "..9...9...9...9.", "voices.stab.pitches": [0, 3, 7, 10, 14], "voices.ride.pattern": "..7...7...7...7..", "voices.hatC.pattern": "4444444444444444", "fx.lpf": 7000, "fx.reverb": .6},
        "procedural": {"withhold": "rim", "voices.rim.pattern": ".7.9.7.9.7.9.7.9", "voices.perc.pitches": [0, 3], "voices.clank.pitches": [12], "fx.drive": .35, "fx.reverb": .08},
        "prospective": {"withhold": ["hatO", "perc"], "voices.stab.pattern": "...............9", "fx.sweep": [1000, 8000], "fx.sweepBars": 8, "fx.reverb": .25},
        "working": {"withhold": "hatO", "voices.hatC.pattern": "7595759575957595", "voices.perc.pattern": "9..5.9.5..9.5.9.", "voices.perc.pitches": [0, 5, 7], "voices.clap.pattern": "....9.......9...", "voices.clap.nudgeMs": 12, "voices.stab.pattern": "..........9.....", "fx.lpf": 12000, "fx.reverb": .2},
        "jhon": {"withhold": "shaker", "voices.perc.pattern": "9.5.9.5..9.5.9.5", "voices.perc.pitches": [0, 3, 7, 10], "voices.shaker.pattern": "5555555555555555", "voices.woodblock.pattern": "......9.......9.", "voices.kick.pattern": "7...7...7...7...", "voices.pad.pitches": [0, 4, 7, 11], "fx.lpf": 8000, "fx.reverb": .3},
        "prasma": {"withhold": "stab", "voices.hatC.pattern": "9393939393939393", "voices.perc.pattern": "9.9..9.9..9.9..9", "voices.perc.pitches": [0, 12], "voices.perc.decay": .060, "voices.stab.pattern": "....9...........", "voices.stab.decay": .090, "fx.lpf": 14000, "fx.reverb": .12},
        "branding": {"withhold": "blip", "voices.blip.pattern": "9..9..9...9..9..", "voices.blip.pitches": [0, 7, 10], "voices.clap.pattern": "....9.......9...", "fx.lpf": 10000, "fx.reverb": .25},
        "onebrain": {"withhold": "arp", "voices.arp.pattern": "9.7.5.9.7.5.9.7.", "voices.arp.pitches": [0, 3, 7, 12], "voices.arp.crush": 8, "voices.pad.pitches": [0, 2, 7], "fx.delay": .5, "fx.feedback": .5, "fx.lpf": 9000, "fx.reverb": .35},
        "reef": {"withhold": "kickTop", "voices.bubble.randomPerBar": [1, 3], "voices.bubble.pitches": [72, 96], "voices.pad.pitches": [0, 3, 7], "voices.pad.chorus": .4, "fx.lfo.frequency": .05, "fx.lfo.min": 500, "fx.lfo.max": 3000, "fx.reverb": .6},
        "inbox": {"withhold": None, "voices.kick.pattern": "8...8...8...8...", "voices.pad.sub": True, "voices.pad.pitches": [0], "fx.lpf": 4000, "fx.reverb": .5},
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
    report["checks"]["explicit patterns pitches effects and withhold match table"] = not mismatches
    compass_hat = definitions.get("core", {}).get("voices", {}).get("hatO", {}).get("pattern", "")
    report["checks"]["Compass offbeat hat velocity six"] = bool(compass_hat) and {char for char in compass_hat if char != "."} == {"6"} and all(index % 4 == 2 for index, char in enumerate(compass_hat) if char != ".")
    period_contracts = (("core", "perc", 32), ("core", "riser", 256),
                        ("semantic", "stab", 32), ("procedural", "clank", 64),
                        ("prospective", "riser", 256), ("branding", "riser", 128))
    report["checks"]["specified infrequent voice periods"] = all(
        len(definitions.get(room, {}).get("voices", {}).get(voice, {}).get("pattern", "")) == period
        for room, voice, period in period_contracts)
    works_roll = definitions.get("procedural", {}).get("voices", {}).get("perc", {}).get("pattern", "")
    report["checks"]["Works ratchet is withheld until bar four"] = len(works_roll) in (63, 64) and works_roll[:48] == "." * 48 and any(char.isdigit() for char in works_roll[48:])
    measurements = {}
    for room in ROOM_IDS:
        print("Measuring room: " + room, flush=True)
        requested_at = engine.evaluate("""id => {
          const a = window.__vc.audio; a.setRoom(id); return a.ctx.currentTime;
        }""", room)
        # A bar-boundary switch can take 5.14 seconds including its two-bar fade.
        # Preserve the requested four-second wait, then finish that fade and let
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
    report["fingerprintMethod"] = "For each room: request it, wait four seconds, finish any remaining two-bar crossfade, let the 2.4-second shared reverb tail clear, then record four seconds of actual PCM and averaged analyser spectrum. No outgoing room is included in the identity measurement."
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
            report["crossfade"] = measure_crossfade(engine)
            fade = report["crossfade"]
            report["checks"]["crossfade starts at next bar"] = fade["transition"]["start"] >= fade["request"]["requestedAt"] and fade["transition"]["start"] - fade["request"]["requestedAt"] <= BAR_SECONDS + .12 and fade["barPhaseError"] is not None and fade["barPhaseError"] < 1e-5
            report["checks"]["two-bar equal-power crossfade"] = abs(fade["transitionDurationSeconds"] - 2 * BAR_SECONDS) < .001 and fade["maxEqualPowerCurveError"] < .04
            report["checks"]["switch envelope below 6 dB per 20 ms"] = len(fade["measuredGainWindows"]) > 150 and len(fade["missingInputWindows"]) <= 2 and fade["maxSwitchEnvelopeDeltaDb"] <= 6
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
    if "crossfade" in compact:
        compact["crossfade"] = {key: value for key, value in report["crossfade"].items()
                                if key not in ("pcmWindows", "measuredGainWindows")}
    if "roomDefinitions" in compact:
        compact["roomDefinitions"] = {room: {key: value for key, value in definition.items()
            if key not in ("voices", "fx")} for room, definition in report["roomDefinitions"].items()}
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
