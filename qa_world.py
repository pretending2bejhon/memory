"""Phase-scoped world QA using the repository browser harness.

C13.3 scenes are measured only when the phase supplies them. C12.3 flashes use
mean luminance in sliding 21 by 12 windows, never a union of pixel events.
"""

import argparse
import hashlib
import json
import math
import re
import subprocess
import time
from pathlib import Path

from qa_browser import Engine
from qa_explore import V6_CHECK_NAMES, V6_S2_SPOT, V6_S3_SETUP, verify_explore

ROOT = Path(__file__).resolve().parent
# Run B is certified in implementation order: V6, V7, V5, V8.
PHASE_ORDER = {**{f"v{i}": i for i in range(5)}, "v6": 5, "v7": 6, "v5": 7, "v8": 8}
SCENES = (
    {"id": "S1", "scene": "overview", "fromPhase": 0, "name": "Overview at week 12"},
    {"id": "S2", "scene": "downtown_stage", "fromPhase": 2,
     "name": "Downtown stage, full crowd, fixed street camera"},
    {"id": "S3", "scene": "archive_ride", "fromPhase": 0,
     "name": "Existing Ride along on Lantern avenue, week 12"},
    {"id": "S4", "scene": "reef_shore", "fromPhase": 6, "name": "Reef shore, Run B V7"},
    {"id": "S5", "scene": "overview_transition", "fromPhase": 0,
     "name": "60 seconds through Downtown focus to Works focus"},
)
ROOM_IDS = ("core", "episodic", "semantic", "procedural", "prospective", "working",
            "jhon", "prasma", "branding", "onebrain", "reef", "inbox")

FRAME_TRACE = """() => {
  const v=window.__vc, rows=[], start=performance.now(); let last=start;
  const trace=window.__qaWorldFrames={done:false,rows,start};
  function tick(now) {
    rows.push([now-start,now-last,v.renderer.info.render.calls,
      v.renderer.info.render.triangles,v.tier?.current??null,
      Boolean(v.audio.enabled&&v.audio.ctx?.state==='running')]);
    last=now;
    if(now-start>=60000){trace.done=true;return;}
    requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
}"""

LUMINANCE_TRACE = """() => {
  const canvas=document.createElement('canvas');canvas.width=64;canvas.height=36;
  const ctx=canvas.getContext('2d',{willReadFrequently:true});
  const source=window.__vc.renderer.domElement,times=new Float64Array(901),
    values=new Uint32Array(901*64*36),linear=new Float64Array(256);
  for(let i=0;i<256;i++){const v=i/255;linear[i]=v<=.04045?v/12.92:Math.pow((v+.055)/1.055,2.4);}
  const start=performance.now();
  const trace=window.__qaWorldFlash={done:false,count:0,torn:0,
    times,values,start};let next=0;
  function tick(now){
    const elapsed=now-start;
    if(elapsed>=next&&elapsed<30000){
      ctx.drawImage(source,0,0,64,36);
      const pixels=ctx.getImageData(0,0,64,36).data,offset=trace.count*64*36;
      // A torn read of the WebGL canvas comes back with a block of exact black. The page never draws
      // (0,0,0) (its clear colour is #030913), so that read is taken again on the next frame, on the
      // same 30 Hz grid. A page that really went black would keep failing and break the 67 ms
      // coverage rule, so the retry cannot hide a flash.
      let torn=false;
      for(let i=0;i<64*36;i++)if(!(pixels[i*4]|pixels[i*4+1]|pixels[i*4+2])){torn=true;break;}
      if(torn)trace.torn++;
      else{
        for(let i=0;i<64*36;i++)trace.values[offset+i]=Math.round(1000000*(
          .2126*linear[pixels[i*4]]+.7152*linear[pixels[i*4+1]]+
          .0722*linear[pixels[i*4+2]]));
        trace.times[trace.count++]=elapsed;next+=1000/30;
      }
    }
    if(elapsed>=30000){trace.done=true;return;}
    requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
}"""


# The audible-time reference for the sync checks. It reads getOutputTimestamp() itself, every 2 ms and
# whenever a check asks, keeps only unclamped pairs and takes the median of contextTime -
# performanceTime / 1000 over the last second, starting again whenever the context is not running (a
# suspended context stops its clock and moves the line). One fresh pair is not a valid reference with
# the 0.1 s output buffer: Chrome renders the page in 0.1 s bursts and clamps the pair's context time to
# currentTime for most of each burst period, so the latest pair then sits up to hundreds of milliseconds
# below the line the device plays on. A pair whose context time trails the currentTime read just before
# it by four render quanta or more was not clamped; those pairs agree with each other to about 0.3 ms
# at both buffer sizes (measured), and with the 10 ms buffer every pair is one of them. The median, not
# the page's own upper envelope, keeps this reference independent of the page's estimator and robust
# to a stray pair either side. Pairs read in the first 150 ms plus one and a half buffers after the
# context starts running (the first bursts after a resume can read high) and stale pairs (performance
# time more than 0.5 s old, left from before a suspension) are not used. The check thresholds and
# sampling density are unchanged.
OUTPUT_LINE = """() => {
  if (window.__qaLine) return true;
  // A context already running when the reference is installed has long settled.
  const L = window.__qaLine = {at: new Float64Array(4096), off: new Float64Array(4096), head: 0, count: 0,
    running: window.__vc.audio.ctx?.state === 'running', since: -Infinity, samples: 0, restarts: 0,
    lastContext: -1, lastPerformance: -1, sorted: new Float64Array(4096)};
  L.sample = () => {
    const ctx = window.__vc.audio.ctx, now = performance.now();
    if (!ctx || ctx.state !== 'running') { L.running = false; return; }
    if (!L.running) { L.running = true; L.since = now; L.head = 0; L.count = 0; L.restarts++; }
    const rendered = ctx.currentTime, s = ctx.getOutputTimestamp?.();
    if (!(s?.performanceTime > 0) || !Number.isFinite(s.contextTime)) return;
    if (s.contextTime === L.lastContext && s.performanceTime === L.lastPerformance) return;
    L.lastContext = s.contextTime; L.lastPerformance = s.performanceTime;
    if (now - L.since < 150 + 1500 * (Number(ctx.baseLatency) || 0) || s.performanceTime < now - 500) return;
    if (rendered - s.contextTime < 4 * 128 / ctx.sampleRate) return;
    while (L.count && L.at[L.head] < now - 1000) { L.head = (L.head + 1) % 4096; L.count--; }
    if (L.count === 4096) { L.head = (L.head + 1) % 4096; L.count--; }
    const i = (L.head + L.count) % 4096;
    L.at[i] = now; L.off[i] = s.contextTime - s.performanceTime / 1000; L.count++; L.samples++;
  };
  // The context time heard at atMs, and how far one fresh pair would have put it (diagnostic only).
  L.audible = atMs => {
    L.sample();
    const ctx = window.__vc.audio.ctx, s = ctx?.getOutputTimestamp?.();
    if (!L.count) return {at: (ctx?.currentTime ?? 0) - (Number(ctx?.outputLatency) || Number(ctx?.baseLatency) || 0), rawErrorMs: 0};
    for (let k = 0, j = L.head; k < L.count; k++, j = (j + 1) % 4096) L.sorted[k] = L.off[j];
    const values = L.sorted.subarray(0, L.count).sort(), half = L.count >> 1;
    const line = L.count % 2 ? values[half] : (values[half - 1] + values[half]) / 2;
    const at = atMs / 1000 + line;
    const raw = s?.performanceTime > 0 ? s.contextTime + (atMs - s.performanceTime) / 1000 : at;
    return {at, rawErrorMs: (raw - at) * 1000};
  };
  L.timer = setInterval(L.sample, 2);
  return true;
}"""


def wait_probe(engine, expression, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = engine.evaluate(expression)
        if value:
            return value
        engine.wait(.25)
    raise RuntimeError("Timed out waiting for " + expression)


def flash_pairs(times, luminance):
    """Non-overlapping opposing 0.10 excursions, including gradual ramps."""
    if not luminance:
        return []
    low = high = extremum = luminance[0]
    direction = 0
    pending = False
    completed = []
    for stamp, value in zip(times[1:], luminance[1:]):
        if direction == 0:
            low, high = min(low, value), max(high, value)
            if value - low >= .10 and low < .80:
                direction, extremum, pending = 1, value, True
            elif high - value >= .10 and value < .80:
                direction, extremum, pending = -1, value, True
            continue
        opposite = ((direction == 1 and extremum - value >= .10 and value < .80)
                    or (direction == -1 and value - extremum >= .10 and extremum < .80))
        if opposite:
            if pending:
                completed.append(stamp)
            pending = not pending
            direction, extremum = -direction, value
        else:
            extremum = max(extremum, value) if direction == 1 else min(extremum, value)
    return completed


def rolling_max(stamps):
    left = result = 0
    for right, stamp in enumerate(stamps):
        while stamp - stamps[left] >= 1000:
            left += 1
        result = max(result, right - left + 1)
    return result


def area_traces(frames):
    """Summed-area tables keep the mandated 77 window means inexpensive."""
    windows = [(x, y) for y in range(0, 36 - 12 + 1, 4)
               for x in range(0, 64 - 21 + 1, 4)]
    traces = [[] for _ in windows]
    for frame in frames:
        integral = [0.0] * (65 * 37)
        for y in range(36):
            row_sum = 0.0
            for x in range(64):
                row_sum += frame[y * 64 + x]
                integral[(y + 1) * 65 + x + 1] = integral[y * 65 + x + 1] + row_sum
        for values, (x, y) in zip(traces, windows):
            values.append((integral[(y + 12) * 65 + x + 21]
                           - integral[y * 65 + x + 21]
                           - integral[(y + 12) * 65 + x]
                           + integral[y * 65 + x]) / (21 * 12))
    return windows, traces


def flash_summary(trace):
    times, frames = trace["times"], trace["frames"]
    windows, traces = area_traces(frames)
    maxima = [rolling_max(flash_pairs(times, values)) for values in traces]
    maximum = max(maxima, default=0)
    gaps = [b - a for a, b in zip(times, times[1:])]
    coverage = (len(times) >= 899 and times[-1] - times[0] >= 29900
                and max(gaps, default=math.inf) <= 67)
    peak = max((max(row) for row in frames), default=0)
    return {"resolution": [64, 36], "window": [21, 12], "step": 4,
            "windowCount": len(windows), "targetHz": 30, "seconds": 30,
            "samples": len(times), "maxSampleGapMs": max(gaps, default=None),
            "coveragePass": coverage, "maxAreaPairsPerSecond": maximum,
            "worstWindowOrigin": list(windows[maxima.index(maximum)]) if maxima else None,
            "peakLuminance": peak,
            "measuredTracePass": coverage and peak > 0 and maximum <= 3}


def summarize_frames(trace):
    rows = trace["rows"][1:]
    values = sorted(row[1] for row in rows)
    mean = sum(values) / len(values)
    tiers = list(dict.fromkeys(row[4] for row in rows))
    return {"seconds": trace["rows"][-1][0] / 1000, "samples": len(values),
            "fps": 1000 / mean, "meanMs": mean,
            "p95Ms": values[math.ceil(len(values) * .95) - 1], "maxMs": max(values),
            "maxDrawCalls": max(row[2] for row in rows),
            "maxTriangles": max(row[3] for row in rows), "tiers": tiers,
            "settledTier": rows[-1][4],
            "soundOnThroughout": all(row[5] for row in rows)}


def perf_pass(value):
    return (value["fps"] >= 55 and value["p95Ms"] <= 22 and value["maxMs"] <= 100
            and value["maxDrawCalls"] <= 320 and value["maxTriangles"] <= 1_500_000
            and value["soundOnThroughout"])


def set_mode(engine, mode):
    engine.evaluate("""() => {const v=window.__vc;if(v.explore?.active)v.explore.leave();if(v.state.ride>=0)v.stopRide();
      document.getElementById('reset-cam').click();v.setIsolate(null);}""")
    if mode == "focus":
        engine.evaluate("() => {window.__vc.setIsolate('working');window.__vc.flyTo('working');}")
    elif mode == "ride":
        engine.evaluate("() => {window.__vc.setIsolate('episodic');window.__vc.startRide();}")
    elif mode == "explore":
        engine.evaluate("() => window.__vc.explore.openHash('#explore/downtown')")


def wait_audio(engine):
    wait_probe(engine, """() => {const a=window.__vc.audio;return a.enabled&&
      a.ctx?.state==='running'&&a.ready&&a.diagnostics.scheduledVoices>0;}""", 60)


def settle_room(engine):
    wait_probe(engine, """() => {const a=window.__vc.audio;return !a.transition||
      a.ctx.currentTime>=a.transition.end;}""", 35)


def measure_scene(engine, scene, path, baseline, phase=0):
    key = scene["id"]
    name = ("Downtown stage, on-foot avatar" if key == "S2" and phase >= 5 else
            "Bike at boost on the Memory Causeway" if key == "S3" and phase >= 5 else
            "Grand Tour through a room drop" if key == "S5" and phase >= 7 else scene["name"])
    print("Measuring " + key + ": " + name + ", 60 seconds, sound on", flush=True)
    engine.evaluate("() => window.__vc.updateWeek(12)")
    set_mode(engine, "ride" if key == "S3" and phase < 5 else "overview")
    if key == "S5":
        if phase >= 7:
            engine.evaluate("() => window.__vc.startRide()")
        else:
            engine.evaluate("() => window.__vc.setIsolate('working')")
    if key == "S2" and phase >= 5:
        engine.evaluate("() => window.__vc.explore.openHash('#explore/downtown')")
        engine.evaluate(V6_S2_SPOT)
    elif key == "S2":
        engine.evaluate("""() => {
          const v=window.__vc, s=v.venues?.stages?.find(s=>s.district==='working');
          if(!s)throw new Error('Downtown stage unavailable');
          const x=s.x,z=s.z??-s.y,up=s.up??0;
          v.camera.position.set(x,up+.5,z+3);v.controls.target.set(x,up+.5,z);
          v.controls.update();
        }""")
    if key == "S3" and phase >= 5:
        setup = engine.evaluate(V6_S3_SETUP, False)
        if not setup["ok"] or not setup["onBike"]:
            raise RuntimeError("S3 bike could not enter the Memory Causeway")
    if key == "S4" and phase >= 6:
        engine.evaluate("() => window.__vc.nature.cameraS4()")
    settle_room(engine)
    engine.wait(12)
    if key == "S4" and phase >= 6:
        engine.evaluate("() => window.__vc.nature.cameraS4()")
    if key == "S3" and phase >= 5:
        wait_probe(engine, """() => {const e=window.__vc.explore,p=e.player;
          return e.bike.boosting&&e.surfaces.probe(p.x,p.z,p.y)&&
            e.surfaces.hit.kind===e.surfaces.K.bridge&&e.surfaces.hit.owner===0;}""", 20)
    engine.screenshot(path("world-" + key.lower() + ".png"))
    if key == "S3" and phase >= 5:
        engine.evaluate("() => {const q=window.__qaS3;q.boostDeckMs=0;q.deckMs=0;q.laps=0;}")
    s5_before = engine.evaluate("""() => {const v=window.__vc;return {active:v.tour.active,
      crossings:v.tour.debug.crossings.length,serial:v.beat.transition.serial,room:v.beat.room};}""") if key == "S5" and phase >= 7 else None
    engine.evaluate(FRAME_TRACE)
    if key == "S5" and phase < 7:
        engine.wait(2)
        engine.evaluate("() => window.__vc.setIsolate('procedural')")
    wait_probe(engine, "() => window.__qaWorldFrames.done", 75)
    trace = engine.evaluate("() => window.__qaWorldFrames")
    s3 = engine.evaluate("() => window.__qaS3") if key == "S3" and phase >= 5 else None
    s5_after = engine.evaluate("""() => {const v=window.__vc;return {active:v.tour.active,
      crossings:v.tour.debug.crossings.slice(),serial:v.beat.transition.serial,room:v.beat.room};}""") if s5_before else None
    if key in ("S2", "S3") and phase >= 5:
        engine.evaluate("() => {const e=window.__vc.explore;e.pilot=null;if(e.active)e.leave();delete window.__qaS3;}")
    path("world-" + key.lower() + "-frames.json").write_text(json.dumps(trace), encoding="utf-8")
    metrics = summarize_frames(trace)
    tiers = metrics["tiers"]
    tier_pass = bool(tiers) and all(tier is not None and tier >= 2 for tier in tiers)
    boost_pass = (s3["boostDeckMs"] >= 2000 and s3["deckMs"] >= 4000 and s3["laps"] >= 1) if s3 else None
    tour_pass = (s5_before["active"] and s5_after["active"] and
                 len(s5_after["crossings"]) > s5_before["crossings"] and
                 s5_after["serial"] > s5_before["serial"] and
                 all(row["roomAtCrossing"] == row["to"] for row in
                     s5_after["crossings"][s5_before["crossings"]:])) if s5_before else None
    return {**scene, "name": name, "available": True, "required": True, "measured": True,
            "tier": "legacy desktop, no tier API" if baseline else metrics["settledTier"],
            "metrics": metrics, "numericBudgetPass": perf_pass(metrics),
            "settledTierPass": tier_pass, "s3Telemetry": s3, "boostPass": boost_pass,
            "s5Telemetry": {"before": s5_before, "after": s5_after} if s5_before else None,
            "tourTransitionPass": tour_pass,
            "passed": perf_pass(metrics) and tier_pass and (boost_pass is not False) and (tour_pass is not False)}


def measure_heap(engine, path, phase=0):
    print("Measuring Heap: 5-minute Grand Tour" if phase >= 7 else
          "Measuring Heap: 5-minute focus, timeline and 60-second ride session", flush=True)
    set_mode(engine, "overview")
    session = engine.context.new_cdp_session(engine.page)
    session.send("Performance.enable")
    session.send("HeapProfiler.collectGarbage")
    def used():
        entries = session.send("Performance.getMetrics")["metrics"]
        return next(row["value"] for row in entries if row["name"] == "JSHeapUsedSize")
    start_heap = used()
    start = time.monotonic()
    rows = []
    if phase >= 7:
        engine.evaluate("() => window.__vc.startRide()")
        while time.monotonic() - start < 300:
            engine.wait(min(30, 300 - (time.monotonic() - start)))
            progress = engine.evaluate("""() => {const v=window.__vc;return {
              active:v.tour.active,leg:v.tour.leg,ride:v.state.ride,
              crossings:v.tour.debug.crossings.length,surfaceGaps:v.tour.debug.surfaceGaps};}""")
            rows.append({"action": "Grand Tour", "elapsed": time.monotonic() - start,
                         "heapBytes": used(), **progress})
    else:
        for room in ROOM_IDS:
            engine.evaluate("room => window.__vc.setIsolate(room)", room)
            engine.wait(12)
            rows.append({"action": "focus", "district": room, "elapsed": time.monotonic() - start,
                         "heapBytes": used()})
        set_mode(engine, "overview")
        engine.evaluate("() => window.__vc.updateWeek(0)")
        engine.click("#play")
        timeline = wait_probe(engine, """() => {const s=window.__vc.state;
          return !s.playing&&s.t>=12?{week:s.t,playing:s.playing}:false;}""", 35)
        rows.append({"action": "Play control, timeline 0 through 12", "elapsed": time.monotonic() - start,
                     "completed": timeline, "heapBytes": used()})
        set_mode(engine, "ride")
        engine.wait(60)
        rows.append({"action": "Archive ride 60 seconds", "elapsed": time.monotonic() - start,
                     "heapBytes": used()})
        set_mode(engine, "overview")
        while time.monotonic() - start < 300:
            engine.wait(min(30, 300 - (time.monotonic() - start)))
    session.send("HeapProfiler.collectGarbage")
    end_heap = used()
    result = {"measured": True, "seconds": time.monotonic() - start,
              "startBytes": start_heap, "endBytes": end_heap,
              "growthBytes": end_heap - start_heap, "garbageCollectedBeforeAndAfter": True,
              "actions": rows, "passed": end_heap - start_heap <= 40_000_000 and
              (phase < 7 or (bool(rows) and all(row["active"] and row["ride"] >= 0 and
               row["surfaceGaps"] == 0 for row in rows) and rows[-1]["crossings"] > 0))}
    path("world-heap.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    session.detach()
    if phase >= 7:
        engine.evaluate("() => window.__vc.stopRide()")
    return result


def measure_flash(engine, mode, setting, path, baseline=False):
    print("Measuring flash: " + mode + ", " + setting + ", 30 seconds", flush=True)
    set_mode(engine, mode)
    if not baseline:
        engine.evaluate("s => window.__vc.lights.setSetting(s)", setting)
    settle_room(engine)
    engine.wait(2)
    engine.evaluate(LUMINANCE_TRACE)
    if mode == "explore":
        # In explore the room follows position, so move to the Works stage.
        engine.evaluate("""() => {const e=window.__vc.explore;
          e.fastTravel(e.design.stages.findIndex(s=>s.district==='procedural'));}""")
    else:
        engine.evaluate("""() => {const a=window.__vc.audio;
          a.setRoom(a.room==='procedural'?'working':'procedural');}""")
    wait_probe(engine, "() => window.__qaWorldFlash.done", 45)
    trace = engine.evaluate("""() => {
      const q=window.__qaWorldFlash;
      return {done:q.done,start:q.start,torn:q.torn,times:Array.from(q.times.subarray(0,q.count)),
        frames:Array.from({length:q.count},(_,i)=>
          Array.from(q.values.subarray(i*64*36,(i+1)*64*36),value=>value/1000000))};
    }""")
    path("world-luminance-" + mode + "-" + setting.lower() + ".json").write_text(
        json.dumps(trace, separators=(",", ":")), encoding="utf-8")
    return {"mode": mode, "setting": setting, "tornReadsRetried": trace.get("torn", 0), **flash_summary(trace)}


def measure_foundations(engine, path):
    """Observe the live clock; no test clock or injected scheduled hit is used."""
    print("Measuring V0 clock, kick release and Sound switching", flush=True)
    engine.evaluate(OUTPUT_LINE)
    wait_probe(engine, "() => window.__vc.audio.ctx?.state !== 'running' || window.__qaLine.count > 0", 10)
    engine.evaluate("""() => {
      const v=window.__vc,b=v.beat;
      const q=window.__qaBeat={kicks:[],switches:[],frames:[],offs:[],active:true};
      q.offs.push(b.on('hit',h=>{
        if(h.source==='audio'&&h.layer==='kick'){
          const d=b.diagnostics,line=window.__qaLine.audible(d.lastFrameMs),audibleNow=line.at;
          q.kicks.push({time:h.time,audibleAt:h.audibleAt,
            measuredAudibleAt:d.lastFrameMs+(h.time-audibleNow)*1000,
            releasedAt:d.lastFrameMs,lateMs:h.lateMs,
            frame:h.frame,frameGapMs:d.frameGapMs,rawStampErrorMs:line.rawErrorMs});
        }
      }));
      let previous=null;
      function tick(){
        if(!q.active)return;
        const s=b.now(),d=b.diagnostics,audibleNow=window.__qaLine.audible(d.lastFrameMs).at;
        const row={seconds:s.seconds,
          frameMs:d.lastFrameMs,source:d.source,phase:s.phase,bar:s.bar,
          audioSeconds:audibleNow-v.audio.origin};
        if(previous&&previous.source!==row.source)q.switches.push({before:previous,after:row});
        previous=row;q.frames.push(row);requestAnimationFrame(tick);
      }
      requestAnimationFrame(tick);
    }""")
    engine.wait(12)
    engine.click("#sound")
    wait_probe(engine, "() => window.__vc.beat.diagnostics.source==='silent'", 5)
    engine.wait(2)
    silent_start = engine.evaluate("""() => {const b=window.__vc.beat;
      return {seconds:b.now().seconds,frameMs:b.diagnostics.lastFrameMs};}""")
    engine.wait(60)
    engine.wait(.1)
    silent_end = engine.evaluate("""() => {const b=window.__vc.beat;
      return {seconds:b.now().seconds,frameMs:b.diagnostics.lastFrameMs};}""")
    engine.click("#sound")
    wait_audio(engine)
    engine.wait(3)
    engine.click("#sound")
    engine.wait(2)
    engine.click("#sound")
    wait_audio(engine)
    engine.wait(3)
    value = engine.evaluate("""() => {
      const q=window.__qaBeat,b=window.__vc.beat,a=window.__vc.audio;
      q.active=false;for(const off of q.offs)off();
      clearInterval(window.__qaLine.timer);delete window.__qaLine;
      return {kicks:q.kicks,switches:q.switches,frames:q.frames,diagnostics:b.diagnostics,
        barSeconds:b.barSeconds,ringCapacity:a.hitRing.capacity,
        ringSlots:a.hitRing.slots.length,ringDropped:a.hitRing.dropped,
        nextDrop:Array.from({length:161},(_,i)=>{
          const bar=(i-16)/4;return {bar,beat:b.nextDrop(bar),audio:a.nextDrop(bar)};
        })};
    }""")
    drift = abs((silent_end["seconds"] - silent_start["seconds"]) * 1000
                - (silent_end["frameMs"] - silent_start["frameMs"]))
    value["silentClock"] = {"start": silent_start, "end": silent_end, "driftMs": drift}
    beat_seconds = 60 / 140
    discontinuities = []
    for before, after in zip(value["frames"], value["frames"][1:]):
        error = (after["seconds"] - before["seconds"]
                 - (after["frameMs"] - before["frameMs"]) / 1000)
        cyclic_error = abs((error + beat_seconds / 2) % beat_seconds - beat_seconds / 2)
        discontinuities.append(cyclic_error)
    value["maxPhaseDiscontinuitySeconds"] = max(discontinuities, default=math.inf)
    convergence = []
    for switch in value["switches"]:
        if switch["after"]["source"] != "audio":
            continue
        deadline = switch["after"]["frameMs"] + value["barSeconds"] * 1000
        frame = next((row for row in value["frames"] if row["frameMs"] >= deadline), None)
        if frame:
            error = abs((frame["seconds"] - frame["audioSeconds"] + value["barSeconds"] / 2)
                        % value["barSeconds"] - value["barSeconds"] / 2)
            convergence.append({"switchFrameMs": switch["after"]["frameMs"],
                                "sampleFrameMs": frame["frameMs"], "errorMs": error * 1000})
    value["sourceConvergence"] = convergence
    kicks = value["kicks"]
    checks = {
        "scheduled kick released within one frame": len(kicks) >= 16 and all(
            -.25 <= hit["releasedAt"] - hit["measuredAudibleAt"] <= hit["frameGapMs"] + .25
            for hit in kicks),
        "silent clock drift within 1 ms over 60 s": drift <= 1 and
            silent_end["frameMs"] - silent_start["frameMs"] >= 60000 and
            abs(value["barSeconds"] - 4 * 60 / 140) < 1e-9,
        "Sound phase discontinuity below a sixteenth": len(value["switches"]) >= 4 and
            value["maxPhaseDiscontinuitySeconds"] < beat_seconds / 4,
        "Sound error absorbed within one bar": len(convergence) >= 2 and
            all(row["errorMs"] <= 1 for row in convergence),
        "shared nextDrop arithmetic": all(row["beat"] == row["audio"] ==
            math.ceil((row["bar"] + 4) / 8) * 8 for row in value["nextDrop"]),
        "preallocated 512-slot hit ring without drops": value["ringCapacity"] == 512 and
            value["ringSlots"] == 512 and value["ringDropped"] == 0,
    }
    path("world-beat.json").write_text(json.dumps(value, indent=2), encoding="utf-8")
    value["frameCount"] = len(value.pop("frames"))
    return value, checks


def shader_light_dependencies(shader):
    """Conservative dependency closure for every mask/light assignment."""
    shader = re.sub(r"/\*.*?\*/|//[^\n]*", "", shader, flags=re.S)
    uniforms = set(re.findall(r"uniform\s+\w+\s+(\w+)", shader))
    dependencies = {}
    for statement in shader.split(";"):
        match = re.search(r"\b([A-Za-z_]\w*)\s*(?:[+*/-]?=)(?!=)(.*)$", statement, re.S)
        if match:
            name, expression = match.groups()
            dependencies.setdefault(name, set()).update(re.findall(r"\b[A-Za-z_]\w*\b", expression))
    for match in re.finditer(r"\b(?:float|vec[234]|mat[234]|bool|int)\s+(\w+)\s*\([^)]*\)\s*\{", shader):
        depth, end = 1, match.end()
        while end < len(shader) and depth:
            depth += (shader[end] == "{") - (shader[end] == "}")
            end += 1
        dependencies.setdefault(match.group(1), set()).update(
            re.findall(r"\b[A-Za-z_]\w*\b", shader[match.end():end]))
    result = {}
    for root in ("mask", "light"):
        pending, seen = [root], set()
        while pending:
            name = pending.pop()
            if name in seen:
                continue
            seen.add(name)
            pending.extend(dependencies.get(name, ()))
        result[root] = sorted(seen & uniforms)
    return result


def verify_city_shader(engine):
    original = subprocess.run(["git", "show", "e5bf9d3:viewer/template.html"], cwd=ROOT,
                              check=True, capture_output=True, text=True, encoding="utf-8").stdout
    material = original.split("const cityMat =", 1)[1].split("function instanced", 1)[0]
    baseline = material.split("fragmentShader: `", 1)[1].split("`", 1)[0]
    current = engine.evaluate("() => window.__vc.cityMat.fragmentShader")
    old, new = shader_light_dependencies(baseline), shader_light_dependencies(current)
    def assignments(shader):
        clean = re.sub(r"/\*.*?\*/|//[^\n]*", "", shader, flags=re.S)
        return [re.sub(r"\s+", "", match.group()) for match in
                re.finditer(r"\b(?:mask|light)\s*[+*/-]?=(?!=)[^;]+;", clean)]
    original_terms, current_terms = assignments(baseline), assignments(current)
    retained = iter(current_terms)
    protected_terms_intact = all(any(term == actual for actual in retained) for term in original_terms)
    return {"baselineCommit": "e5bf9d3", "baselineUniformDependencies": old,
            "currentUniformDependencies": new,
            "baselineLightTerms": original_terms, "currentLightTerms": current_terms,
            "protectedLightTermsIntact": protected_terms_intact,
            "baselineFragmentSHA256": hashlib.sha256(baseline.encode()).hexdigest(),
            "currentFragmentSHA256": hashlib.sha256(current.encode()).hexdigest(),
            "passed": protected_terms_intact and all(set(new[key]) <= set(old[key]) for key in old)}


def measure_transition(engine, path, sound):
    print("Measuring V1 full transition, sound " + ("on" if sound else "off"), flush=True)
    set_mode(engine, "overview")
    if bool(engine.evaluate("() => window.__vc.audio.enabled")) != sound:
        engine.click("#sound")
    if sound:
        wait_audio(engine)
    engine.evaluate("() => window.__vc.lights.setSetting('Full')")
    try:
        wait_probe(engine, """() => {const v=window.__vc,b=v.beat,a=v.audio;
          return !b.transition.active&&(b.sound?a.room===a.desired&&!a.transition:b.room===a.desired);}""", 40)
    except RuntimeError as error:
        state = engine.evaluate("""() => {const v=window.__vc;return {
          audioRoom:v.audio.room,desired:v.audio.desired,beatRoom:v.beat.room,
          sound:v.beat.sound,audioTransition:v.audio.transition,visualTransition:v.beat.transition};}""")
        raise RuntimeError(str(error) + "; observed state " + json.dumps(state)) from error
    engine.wait(.5)
    engine.evaluate("() => { if (window.__qaLine) clearInterval(window.__qaLine.timer); delete window.__qaLine; }")
    engine.evaluate(OUTPUT_LINE)
    wait_probe(engine, "() => window.__vc.audio.ctx?.state !== 'running' || window.__qaLine.count > 0", 10)
    engine.evaluate("""() => {
      const v=window.__vc,b=v.beat,r=v.rave;
      if(!r)throw new Error('Rave renderer unavailable');
      const q=window.__qaTransition={events:[],frames:[],buffers:[],changed:[],offs:[],
        active:true,done:false,checks:0,started:performance.now(),nodeCount:v.nodes.length,
        noteInstances:0,source:b.sound?'audio':'silent',schedule:null};
      const target=v.audio.room==='procedural'?'working':'procedural';
      function schedule(){
        if(q.schedule)return;
        const tr=b.sound?v.audio.transition:b.transition;
        if(tr&&tr.to===target)q.schedule={bridge:tr.start,riser:Math.max(tr.start,tr.drop-4*b.barSeconds),
          cut:tr.drop-b.beatSeconds,drop:tr.drop,target};
      }
      for(const [kind,set] of Object.entries(v.kinds)){
        q.noteInstances+=set.mesh.count;
        const arrays={instanceMatrix:set.mesh.instanceMatrix};
        if(set.mesh.instanceColor)arrays.instanceColor=set.mesh.instanceColor;
        for(const [name,attr] of Object.entries(set.mesh.geometry.attributes))
          if(attr.isInstancedBufferAttribute)arrays[name]=attr;
        for(const [name,attribute] of Object.entries(arrays)){
          const a=attribute.array,bytes=new Uint8Array(a.buffer,a.byteOffset,a.byteLength);
          q.buffers.push({name:kind+'/'+name,attribute,bytes:bytes.slice(),different:false});
        }
      }
      for(const name of ['bridge','riser','cut','drop'])q.offs.push(b.on(name,tr=>{
        schedule();
        const d=b.diagnostics,line=window.__qaLine.audible(d.lastFrameMs),at=line.at;
        const expected=q.schedule[name];
        q.events.push({name,frame:d.frame,frameMs:d.lastFrameMs,frameGapMs:d.frameGapMs,
          expected,actual:q.source==='audio'?at:b.now().seconds,
          source:tr.source,serial:tr.serial,rawStampErrorMs:line.rawErrorMs});
      }));
      b.setRoom(target);
      schedule();
      function tick(){
        if(!q.active)return;
        schedule();
        for(const entry of q.buffers){
          const a=entry.attribute.array,bytes=new Uint8Array(a.buffer,a.byteOffset,a.byteLength);
          if(bytes.length!==entry.bytes.length){entry.different=true;}
          else for(let i=0;i<bytes.length;i++)if(bytes[i]!==entry.bytes[i]){entry.different=true;break;}
        }
        q.checks++;
        const uniforms={};
        for(const [name,u] of Object.entries(r.uniforms)){
          const value=u.value;
          if(typeof value==='number')uniforms[name]=value;
          else if(value?.isColor)uniforms[name]=[value.r,value.g,value.b];
        }
        q.frames.push({frame:b.diagnostics.frame,frameMs:b.diagnostics.lastFrameMs,
          stage:r.transition.stage,uniforms});
        const drop=q.events.find(e=>e.name==='drop');
        if(drop&&b.diagnostics.lastFrameMs-drop.frameMs>=b.barSeconds*1000){
          q.active=false;q.done=true;for(const off of q.offs)off();return;
        }
        requestAnimationFrame(tick);
      }
      requestAnimationFrame(tick);
    }""")
    wait_probe(engine, "() => window.__qaTransition.done", 40)
    engine.evaluate("() => { clearInterval(window.__qaLine.timer); delete window.__qaLine; }")
    value = engine.evaluate("""() => {const q=window.__qaTransition;return {
      events:q.events,frames:q.frames,source:q.source,schedule:q.schedule,
      nodeCount:q.nodeCount,noteInstances:q.noteInstances,frameComparisons:q.checks,
      buffers:q.buffers.map(e=>({name:e.name,bytes:e.bytes.length,different:e.different})),
      changed:q.buffers.filter(e=>e.different).map(e=>e.name)};}""")
    names = [item["name"] for item in value["events"]]
    value["timingPass"] = names == ["bridge", "riser", "cut", "drop"] and all(
        -.25 <= (event["actual"] - event["expected"]) * 1000 <= event["frameGapMs"] + .25
        for event in value["events"])
    value["buffersPass"] = (value["nodeCount"] == value["noteInstances"] == 1246 and
                            value["frameComparisons"] >= 200 and not value["changed"])
    stages = {"bridge": 1, "riser": 2, "cut": 3, "drop": 4}
    rendered_steps = []
    for event in value["events"]:
        frame = next((row for row in value["frames"] if row["frame"] == event["frame"]), None)
        effective = max(stages[item["name"]] for item in value["events"]
                        if item["frame"] == event["frame"])
        uniforms = frame["uniforms"] if frame else {}
        rendered_steps.append({"name": event["name"], "frame": event["frame"],
                               "effectiveStage": effective, "uniforms": uniforms,
                               "passed": uniforms.get("uStage") == effective and
                               abs(uniforms.get("uCut", -1) - (.15 if effective == 3 else 1)) < 1e-6 and
                               abs(uniforms.get("uSourceIntensity", -1) - (1 if sound else .5)) < 1e-6})
    value["renderedSteps"] = rendered_steps
    value["renderPass"] = len(rendered_steps) == 4 and all(row["passed"] for row in rendered_steps)
    path("world-transition-" + ("on" if sound else "off") + ".json").write_text(
        json.dumps(value, indent=2), encoding="utf-8")
    value["frameCount"] = len(value["frames"])
    value.pop("frames")
    return value


RAVE_SNAPSHOT = """() => {
  const v=window.__vc,r=v.rave;
  if(!r)return null;
  const meshNames=['sky','lasers','searchlights','drones','fireworks','grid','screens','screenFrames'];
  const meshes={};
  for(const name of meshNames){
    const mesh=r[name],mat=mesh?.material;
    meshes[name]={exists:Boolean(mesh),inScene:Boolean(mesh&&v.scene.getObjectById(mesh.id)),
      type:mesh?.type,count:mesh?.isInstancedMesh?mesh.count:null,
      positionCount:mesh?.geometry?.attributes.position?.count??null,
      drawCount:mesh?.geometry?.drawRange.count??null,
      sharedCut:mat?.uniforms?.uCut===r.uniforms.uCut,
      compiled:Boolean(mat&&v.renderer.properties.get(mat).programs?.size)};
  }
  const glyphs={};
  for(const [name,points] of Object.entries(r.glyphs)){
    const values=ArrayBuffer.isView(points)?Array.from(points):points.flatMap(p=>Array.isArray(p)?p:[p.x,p.y,p.z]);
    let sum=0,weighted=0;for(let i=0;i<values.length;i++){sum+=values[i];weighted+=values[i]*(i+1);}
    glyphs[name]={count:values.length/3,finite:values.every(Number.isFinite),sum,weighted};
  }
  const tallest=v.nodes.filter(n=>n.district==='working').slice().sort((a,b)=>b.h-a.h);
  const signNodes=v.nodes.filter(n=>n.district==='branding'&&n.kind==='sign');
  const hosts=r.screenHosts.map(n=>typeof n==='number'?n:(n.id??n.host??n.node));
  const uniforms={};for(const [name,u] of Object.entries(r.uniforms)){
    const x=u.value;if(typeof x==='number')uniforms[name]=x;
    else if(x?.isColor)uniforms[name]=[x.r,x.g,x.b];
  }
  return {tier:v.tier.current,meshes,glyphs,patterns:r.patterns,screenHosts:hosts,
    expectedScreenHosts:[...tallest.slice(0,6),...signNodes].map(n=>n.id),uniforms,
    laserOrigins:r.laserOrigins.map(p=>({x:p.x,y:p.y,z:p.z})),
    expectedLaserHosts:[v.nodes.filter(n=>n.district==='core').sort((a,b)=>b.h-a.h)[0],...tallest.slice(0,3)]
      .map(n=>({id:n.id,x:n.x,z:-n.y}))};
}"""


def verify_rave_inventory(engine):
    value = engine.evaluate(RAVE_SNAPSHOT)
    if not value:
        return {"available": False}, {"all eight rave render layers exist and compile": False}
    meshes, current = value["meshes"], value["tier"]
    expected_lasers = {3: 14, 2: 10, 1: 6}[current]
    expected_drones = {3: 256, 2: 128, 1: 0}[current]
    origins, hosts = value["laserOrigins"], value["expectedLaserHosts"]
    origin_counts = [sum(abs(p["x"] - host["x"]) < .001 and abs(p["z"] - host["z"]) < .001
                         for p in origins) for host in hosts]
    glyphs = value["glyphs"]
    return value, {
        "all eight rave render layers exist and compile": all(
            row["exists"] and row["inScene"] and row["compiled"] for row in meshes.values()),
        "sky lasers grid and screens share rendered cut uniform": all(
            meshes[name]["sharedCut"] for name in ("sky", "lasers", "grid", "screens")),
        "laser and drone counts follow current tier": meshes["lasers"]["count"] == expected_lasers and
            meshes["drones"]["drawCount"] == expected_drones,
        "four searchlights at Tier 3": meshes["searchlights"]["count"] == 4 if current == 3 else
            0 < meshes["searchlights"]["count"] <= 4,
        "laser origins are Compass and three tallest Downtown roofs": len(origins) == 14 and
            origin_counts == [8, 2, 2, 2],
        "five laser patterns": set(value["patterns"]) == {
            "fan", "sweep", "scissor", "tunnel", "converge-up"},
        "twelve distinct 256-point drone glyphs": set(glyphs) == set(ROOM_IDS) and
            all(row["count"] == 256 and row["finite"] for row in glyphs.values()) and
            len({(round(row["sum"], 5), round(row["weighted"], 5)) for row in glyphs.values()}) == 12,
        "mounted screens cover six Downtown roofs and all Signal Row billboards":
            sorted(value["screenHosts"]) == sorted(value["expectedScreenHosts"]) and
            meshes["screens"]["count"] == len(value["expectedScreenHosts"]),
    }


def measure_rave_dynamics(engine, path):
    print("Measuring V1 Yards arrangement return and rendered kick ripples, 32 seconds", flush=True)
    if not engine.evaluate("() => window.__vc.audio.enabled"):
        engine.click("#sound")
    wait_audio(engine)
    engine.evaluate("() => {window.__vc.lights.setSetting('Full');window.__vc.beat.setRoom('prospective');}")
    wait_probe(engine, """() => {const v=window.__vc;return v.audio.room==='prospective'&&
      !v.audio.transition&&!v.beat.transition.active;}""", 40)
    engine.evaluate("""() => {
      const v=window.__vc,r=v.rave,b=v.beat,start=performance.now();
      const q=window.__qaRaveDynamics={done:false,kicks:[],shells:[],frames:0,
        history:r.diagnostics.shellHistory.filter(x=>x.room).map(x=>({...x})),
        gridShader:r.grid.material.fragmentShader,
        beforeLaser:Array.from(r.lasers.instanceMatrix.array),
        beforeSearch:Array.from(r.searchlights.instanceMatrix.array),
        beforeTime:r.uniforms.uTime.value};
      let eventCount=r.diagnostics.fireworkEvents;
      const off=b.on('hit',h=>{
        if(h.layer!=='kick'||h.gain<=0)return;
        const now=b.diagnostics.lastFrameMs/1000;
        const ripples=r.grid.material.uniforms.uRipples.value;
        q.kicks.push({room:h.room,gain:h.gain,time:now,
          ripples:ripples.filter(x=>Math.abs(x.z-now)<.000001).map(x=>x.toArray())});
      });
      function tick(){
        q.frames++;
        if(r.diagnostics.fireworkEvents!==eventCount){
          for(let i=eventCount;i<r.diagnostics.fireworkEvents;i++){
            const row=r.diagnostics.shellHistory[i%r.diagnostics.shellHistory.length];
            q.shells.push({...row,tier:v.tier.current,drawn:r.fireUniforms.uShells.value.map(x=>x.toArray()),
              clock:r.fireworks.material.uniforms.uClock.value,
              particleLimit:r.fireworks.material.uniforms.uParticleLimit.value,
              frameObserved:b.diagnostics.frame});
          }
          eventCount=r.diagnostics.fireworkEvents;
        }
        if(performance.now()-start>=32000){
          q.afterLaser=Array.from(r.lasers.instanceMatrix.array);
          q.afterSearch=Array.from(r.searchlights.instanceMatrix.array);q.afterTime=r.uniforms.uTime.value;
          q.done=true;off();return;
        }
        requestAnimationFrame(tick);
      }
      requestAnimationFrame(tick);
    }""")
    wait_probe(engine, "() => window.__qaRaveDynamics.done", 40)
    value = engine.evaluate("() => window.__qaRaveDynamics")
    shells = value["shells"]
    history = value["history"] + shells
    events = {(row["room"], row["bar"], row["at"]): row for row in history}.values()
    cycles = [(row["room"], row["cycle"]) for row in events]
    correct_returns = all(row["bar"] % (16 if row["room"] == "prospective" else 32) ==
                          (0 if row["room"] == "inbox" else 10 if row["room"] == "prospective" else 22)
                          for row in events)
    layout = json.loads((ROOT / "data" / "layout.json").read_text(encoding="utf-8"))
    design = json.loads((ROOT / "data" / "city-design.json").read_text(encoding="utf-8"))
    ripple_origins = True
    for row in value["kicks"]:
        district = "core" if row["room"] == "skyline" else row["room"]
        stage = next((s for s in design.get("stages", []) if s["district"] == district), None)
        plateau = layout["districts"][district]
        # Plateau centers use the same two-decimal serialization as viewer/build.py.
        x, z = (stage["x"], -stage["y"]) if stage else (round(plateau["cx"], 2), -round(plateau["cy"], 2))
        ripple_origins &= any(abs(ripple[0] - x) < .001 and abs(ripple[1] - z) < .001
                              for ripple in row["ripples"])
    value["rippleOriginReference"] = {"plateauSerializationDecimals": 2,
                                     "stageCoordinates": "generated design", "tolerance": .001}
    checks = {
        "fireworks follow arrangement return once per cycle": bool(shells) and correct_returns and
            len(cycles) == len(set(cycles)),
        "Yards return fires real tier-scaled shell uniforms": bool(shells) and all(
            row["room"] == "prospective" and row["bar"] % 16 == 10 and
            (3 <= row["shells"] <= 6 if row["tier"] == 3 else 2 <= row["shells"] <= 4) and
            sum(shell[3] > 0 for shell in row["drawn"]) == row["shells"] and
            row["frameObserved"] == row["frame"] and
            row["particleLimit"] == {3: 64, 2: 38, 1: 26}[row["tier"]]
            for row in shells),
        "every observed kick writes a rendered grid ripple": len(value["kicks"]) >= 32 and all(
            row["ripples"] and any(ripple[3] > 0 for ripple in row["ripples"]) for row in value["kicks"]),
        "kick ripples originate at active district center or existing stage": ripple_origins,
        "grid shader uses 20 unit speed and 1.5 second decay":
            bool(re.search(r"radius\s*=\s*age\s*\*\s*20(?:\.0)?", value["gridShader"])) and
            "step(age,1.5)" in value["gridShader"].replace(" ", "") and
            "1.0-age/1.5" in value["gridShader"].replace(" ", ""),
        "lasers and searchlights animate real instance matrices":
            value["beforeLaser"] != value["afterLaser"] and value["beforeSearch"] != value["afterSearch"] and
            value["afterTime"] > value["beforeTime"],
    }
    path("world-rave-dynamics.json").write_text(json.dumps(value, indent=2), encoding="utf-8")
    for name in ("beforeLaser", "afterLaser", "beforeSearch", "afterSearch", "gridShader"):
        value.pop(name)
    value["checks"] = checks
    return value, checks


OTHER_CAPS = {3: 88, 2: 53, 1: 20}
PEOPLE_BUDGET = {3: 400 + 480 + 12 + 88, 2: 240 + 288 + 12 + 53, 1: 220}


def verify_crowd(engine, path, phase=2):
    """V2 gates: census per tier, dancers follow the timeline formula, nobody inside a footprint,
    bounce minima locked to each dancer's own beat within a sixteenth. From V3 the census per tier also
    counts the others (C3.7) with the page switched to each tier the way the governor switches it (crowd
    caps, vehicle count, two rendered frames so riders follow their chivas): others within 88/53/20,
    some others at Tier 3, and walkers + dancers + DJs + others within the tier's people budget
    (C13.1: 220 at Tier 1)."""
    result = engine.evaluate("""() => {
      const v=window.__vc,c=v.crowd,caps={3:[400,480],2:[240,288],1:[100,108]},tiers={};
      for(const level of [3,2,1]){c.applyTier(level);const n=c.census();
        const cap=caps[level];tiers[level]={walkers:n.walkers,dancers:n.dancers,djs:n.djs,
          pass:n.walkers===cap[0]&&n.dancers<=cap[1]+12&&n.djs===12};}
      c.applyTier(v.tier.current);
      const formula=week=>{v.updateWeek(week);const stats=v.audio.timeline,n=c.census();let total=0;
        const targets=c.stages.map(s=>{const st=stats[s.district]||{density:0,brightness:0};const t=s.capacity*st.density*(.25+.75*st.brightness);total+=t;return t;});
        const scale=total>c.state.dancerCap?c.state.dancerCap/total:1;
        const rows=c.stages.map((s,i)=>({district:s.district,visible:n.perStage[i].visible,expected:Math.min(c.stageSlots[i].length,Math.round(targets[i]*scale))}));
        return {week,total:n.dancers,rows,pass:rows.every(r=>r.visible===r.expected)};};
      const week0=formula(0),week12=formula(12);
      return {tiers,week0,week12};
    }""")
    engine.wait(1.5)
    inside = engine.evaluate("""() => {
      const v=window.__vc,c=v.crowd,arr=c.parts.hips.instanceMatrix.array,p=new v.camera.position.constructor();let checked=0;const bad=[];
      c.people.forEach((person,i)=>{if(!c.isVisible(i,person))return;const o=i*16;if(arr[o+15]!==1)return;
        p.set(arr[o+12],arr[o+13]+.05,arr[o+14]);checked++;if(v.pointBlocked(p,.07,true))bad.push({i,kind:person.kind,district:person.district});});
      return {checked,inside:bad.length,sample:bad.slice(0,10)};
    }""")
    bounce = engine.evaluate("""() => new Promise(resolve => {
      const v=window.__vc,c=v.crowd,arr=c.parts.hips.instanceMatrix.array,st=c.stages.find(s=>s.district==='working');
      // Close to the camera, so the sampled dancers refresh every frame (no distance LOD).
      v.camera.position.set(st.center.x,st.center.y+1.2,st.center.z+3);v.controls.target.copy(st.center);v.controls.update();
      const picks=c.people.map((p,i)=>[p,i]).filter(([p,i])=>p.kind===1&&p.district==='working'&&c.isVisible(i,p)&&(p.style==='bounce'||p.style==='pump')).slice(0,6);
      const traces=picks.map(()=>[]);let frames=0;
      function tick(){const b=v.beat.now().totalBeats;picks.forEach(([p,i],k)=>traces[k].push([b+p.offset,arr[i*16+13]]));
        if(++frames<150)requestAnimationFrame(tick);else{
          const rows=picks.map(([p,i],k)=>{const t=traces[k],minima=[];
            for(let j=5;j<t.length-5;j++){let low=true,strict=false;for(let k=j-4;k<=j+4;k++){if(k===j)continue;if(t[k][1]<t[j][1])low=false;if(t[k][1]>t[j][1])strict=true;}
              if(low&&strict&&(!minima.length||t[j][0]-minima[minima.length-1]>.5))minima.push(t[j][0]);}
            const err=minima.map(m=>Math.abs(m-Math.round(m)));return {style:p.style,offset:p.offset,minima:minima.length,maxError:Math.max(0,...err)};});
          resolve({rows,pass:rows.length>0&&rows.every(r=>r.minima>=3&&r.maxError<=1/16&&Math.abs(r.offset)<=1/16)});}}
      requestAnimationFrame(tick);
    })""")
    others = None
    if phase >= 3:
        others = engine.evaluate("""() => new Promise(resolve => {
          const v=window.__vc,c=v.crowd,desc=Object.getOwnPropertyDescriptor(v.tier,'current'),levels=[3,2,1],rows={};let k=0;
          function next(){
            if(k===levels.length){Object.defineProperty(v.tier,'current',desc);c.applyTier(v.tier.current);v.updateWeek(12);resolve(rows);return;}
            const level=levels[k++];Object.defineProperty(v.tier,'current',{get:()=>level,configurable:true});c.applyTier(level);v.updateWeek(12);
            requestAnimationFrame(()=>requestAnimationFrame(()=>{const n=c.census();
              const riders=c.people.filter((p,i)=>p.kind===3&&p.pose==='ride'&&c.isVisible(i,p)).length;
              rows[level]={walkers:n.walkers,dancers:n.dancers,djs:n.djs,others:n.others,riders,total:n.walkers+n.dancers+n.djs+n.others};next();}));
          }
          next();
        })""")
        for level, row in others.items():
            level = int(level)
            row["othersCap"] = OTHER_CAPS[level]
            row["budget"] = PEOPLE_BUDGET[level]
            row["pass"] = (row["others"] <= OTHER_CAPS[level] and row["total"] <= PEOPLE_BUDGET[level] and
                           (level != 3 or row["others"] > 0))
    report = {"census": result, "inside": inside, "bounce": bounce, "others": others}
    path("world-crowd.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    checks = {"people census per tier": all(row["pass"] for row in result["tiers"].values()) and
                                        (others is None or (len(others) == 3 and all(row["pass"] for row in others.values()))),
              "dancers follow density and brightness": result["week0"]["pass"] and result["week12"]["pass"] and result["week12"]["total"] > result["week0"]["total"],
              "no person inside a footprint": inside["checked"] > 0 and inside["inside"] == 0,
              "bounce minima within a sixteenth": bounce["pass"]}
    return report, checks


VENUE_TARGET = 93
VEHICLE_ALLOCATION = {"compact": 24, "sedan": 28, "taxi": 26, "suv": 14, "van": 10, "bus": 6,
                      "truck": 10, "moto": 18, "delivery": 18, "chiva": 6}
VEHICLE_TIER_TOTAL = {3: 160, 2: 96, 1: 70}
VEHICLE_TIER_FACTOR = {3: 1.0, 2: 0.6, 1: 70 / 160}


def venue_targets():
    """C4.3 per-district venue targets exactly as design.py computes them (Python rounding)."""
    layout = json.loads((ROOT / "data" / "layout.json").read_text(encoding="utf-8"))
    return {district: max(1, min(24, round(p["n"] / 12))) for district, p in layout["districts"].items()}


def js_round(value):
    """Math.round, which the page's timeline rule uses."""
    return math.floor(value + 0.5)


def verify_society(engine, path):
    """V3 gates: venue census 93 +- 10 % with the per-district shortfall, every host a real note that is
    neither a plaza nor a foundation, venue state and rendered buffers follow the host through a timeline
    scrub (C4.4), and the vehicle census per type and tier (C5.2)."""
    venues = engine.evaluate("""() => {
      const v=window.__vc,ids=new Map(v.nodes.map(n=>[n.id,n])),seen=new Set(),rows=[];
      for(const x of v.venues.items){const n=x.host;
        rows.push({venue:x.index,district:x.district,host:n?n.id:null,kind:n?n.kind:null,created:n?n.created:null,
          real:!!n&&ids.get(n.id)===n,repeat:!!n&&seen.has(n.id)});if(n)seen.add(n.id);}
      return rows;
    }""")
    targets = venue_targets()
    placed = {}
    for row in venues:
        placed[row["district"]] = placed.get(row["district"], 0) + 1
    shortfall = {d: t - placed.get(d, 0) for d, t in sorted(targets.items()) if placed.get(d, 0) < t}
    census = {"total": len(venues), "target": VENUE_TARGET, "targetSum": sum(targets.values()),
              "perDistrict": {d: {"placed": placed.get(d, 0), "target": t} for d, t in sorted(targets.items())},
              "shortfall": shortfall}
    bad_hosts = [row for row in venues if not row["real"] or row["repeat"] or row["created"] is None
                 or row["kind"] in ("plaza", "found")]
    hosts = {"checked": len(venues), "bad": bad_hosts[:10], "badCount": len(bad_hosts)}
    # Walk weeks 0 to 12 in quarter weeks. The expected state comes from the host's rendered light
    # (its aLit attribute) and its rendered height (absent hosts are scaled to nothing). Patrons are
    # checked both ways: shown exactly when the venue is open or quiet enough for them, its host has
    # fully risen (rendered height) and their rank is inside the tier's extras cap.
    scrub = engine.evaluate("""() => {
      const v=window.__vc,V=v.venues,M=V.meshes,crowd=v.crowd,bad=[],counts={open:0,quiet:0,shut:0,absent:0};
      const scale=(mesh,i)=>{const a=mesh.instanceMatrix.array,o=i*16;return Math.hypot(a[o],a[o+1],a[o+2])+Math.hypot(a[o+4],a[o+5],a[o+6]);};
      const frontOpen=M.front.geometry.attributes.aOpen,terraces=new Map();
      for(const f of V.furniture)if(f.venue>=0){if(!terraces.has(f.venue))terraces.set(f.venue,[]);terraces.get(f.venue).push(f);}
      const patrons=new Map();crowd.people.forEach((p,i)=>{if(p.kind===3&&p.venue!==undefined){if(!patrons.has(p.venue))patrons.set(p.venue,[]);patrons.get(p.venue).push([i,p]);}});
      let samples=0;
      for(let step=0;step<=48;step++){const t=step/4;v.updateWeek(t);
        for(const x of V.items){samples++;const n=x.host,set=v.kinds[n.kind],lit=set.attrs.lit.getX(n.slot);
          const hostHeight=Math.hypot(...set.mesh.instanceMatrix.array.slice(n.slot*16+4,n.slot*16+7)),absent=hostHeight<.001;
          const grown=Math.min(1,hostHeight/n.h*1.5)>=1-1e-6;
          const want=absent?'absent':Math.abs(lit-.5)<1e-6?x.state:lit>=.5?'open':lit>=.15?'quiet':'shut';
          counts[want]++;
          const fail=reason=>bad.push({t,venue:x.index,host:n.id,want,got:x.state,lit,reason});
          if(x.state!==want){fail('state');continue;}
          const front=scale(M.front,x.index),awning=scale(M.awnings,x.index),sign=scale(x.signMesh,x.signSlot);
          const openWant=want==='open'?1:want==='quiet'?.4:0;
          if(want==='absent'){if(front>1e-6||awning>1e-6||sign>1e-6)fail('absent host shows a storefront, awning or sign');}
          else{if(front<1e-3||sign<1e-3)fail('present venue without storefront or sign');
            if(Math.abs(frontOpen.getX(x.index)-openWant)>1e-6||Math.abs(x.signMesh.geometry.attributes.aOpen.getX(x.signSlot)-openWant)>1e-6)fail('lit level');
            if((want==='shut')!==(awning<1e-6))fail('awning');}
          const terraceOn=want==='open'||want==='quiet';
          for(const f of terraces.get(x.index)||[])if((scale(f.mesh,f.slot)>1e-3)!==terraceOn){fail('terrace '+f.kind);break;}
          let seated=0;
          for(const [i,p] of patrons.get(x.index)||[]){const shown=crowd.isVisible(i,p);if(shown&&p.pose==='sit')seated++;
            const expect=terraceOn&&grown&&openWant>=(p.needs||0)&&(p.free===true||p.extraRank<crowd.state.extras);
            if(shown!==expect){fail((shown?'patron shown ':'patron missing ')+p.pose);break;}}
          // C4.4: a quiet venue has one or two patrons, whatever the page asks of them.
          if(want==='quiet'&&seated>2)fail('quiet venue with '+seated+' seated patrons');
        }}
      v.updateWeek(12);
      return {samples,weeks:49,counts,failures:bad.length,sample:bad.slice(0,8)};
    }""")
    vehicles = engine.evaluate("""(tiers) => new Promise(resolve => {
      const v=window.__vc,allocated={},rendered={},edges=v.edges.filter(e=>e.appear<=12).length;
      for(const [level,cap] of tiers){const per={};for(const c of v.carState)if(c.rank<cap)per[c.type]=(per[c.type]||0)+1;allocated[level]=per;}
      const desc=Object.getOwnPropertyDescriptor(v.tier,'current'),levels=[3,2,1];let k=0;
      function next(){
        if(k===levels.length){Object.defineProperty(v.tier,'current',desc);v.updateWeek(12);resolve({allocated,rendered,edgesAtWeek12:edges,cars:v.carState.length});return;}
        const level=levels[k++];Object.defineProperty(v.tier,'current',{get:()=>level,configurable:true});v.updateWeek(12);
        requestAnimationFrame(()=>requestAnimationFrame(()=>{const per={};let total=0;
          for(const c of v.carState){const a=c.mesh.instanceMatrix.array,o=c.slot*16;if(a[o+15]===1&&Math.hypot(a[o],a[o+1],a[o+2])>.5){per[c.type]=(per[c.type]||0)+1;total++;}}
          rendered[level]={per,total};next();}));
      }
      next();
    })""", [[level, cap] for level, cap in VEHICLE_TIER_TOTAL.items()])
    base = max(12, js_round(24 + vehicles["edgesAtWeek12"] / 18))
    tier_rows = {}
    for level, cap in VEHICLE_TIER_TOTAL.items():
        per = vehicles["allocated"][str(level)]
        total = sum(per.values())
        rows = {t: {"allocated": per.get(t, 0), "want": round(a * VEHICLE_TIER_FACTOR[level], 2)}
                for t, a in VEHICLE_ALLOCATION.items()}
        within = all(abs(r["allocated"] - r["want"]) <= 0.15 * r["want"] for r in rows.values())
        visible = vehicles["rendered"][str(level)]
        expected_visible = min(cap, js_round(base * VEHICLE_TIER_FACTOR[level]))
        tier_rows[level] = {"allocatedTotal": total, "cap": cap, "perType": rows, "perTypeWithin15": within,
                            "visible": visible["total"], "expectedVisible": expected_visible,
                            "visiblePerType": visible["per"],
                            "visibleWithinAllocation": all(visible["per"].get(t, 0) <= per.get(t, 0) for t in VEHICLE_ALLOCATION)}
    vehicle_pass = (vehicles["cars"] == VEHICLE_TIER_TOTAL[3] and
                    all(row["allocatedTotal"] == row["cap"] and row["visible"] == row["expectedVisible"] and
                        row["visibleWithinAllocation"] for row in tier_rows.values()) and
                    tier_rows[3]["perTypeWithin15"] and tier_rows[2]["perTypeWithin15"])
    report = {"census": census, "hosts": hosts, "scrub": scrub,
              "vehicles": {"timelineRuleAtWeek12": base, "edgesAtWeek12": vehicles["edgesAtWeek12"],
                           "cars": vehicles["cars"], "tiers": tier_rows}}
    path("world-society.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    checks = {"venue census 93 plus or minus 10 percent": abs(census["total"] - VENUE_TARGET) <= 0.1 * VENUE_TARGET,
              "venue hosts valid": hosts["checked"] > 0 and hosts["badCount"] == 0,
              "venue state follows host": scrub["samples"] == 49 * len(venues) and len(venues) > 0 and scrub["failures"] == 0,
              "vehicle census per type": vehicle_pass}
    return report, checks


def verify_rave_reduced(engine, path):
    """Compare actual motion buffers across a reduced-motion silent transition."""
    engine.evaluate("""() => {
      const v=window.__vc,r=v.rave,q=window.__qaRaveReduced={buffers:[],frames:[],done:false};
      for(const name of ['lasers','searchlights','drones','fireworks']){
        const mesh=r[name],attr=mesh.instanceMatrix??mesh.geometry.attributes.position;
        const a=attr.array;q.buffers.push({name,attr,bytes:new Uint8Array(a.buffer,a.byteOffset,a.byteLength).slice()});
      }
      let started=performance.now();
      v.beat.setRoom('procedural');
      function tick(){
        const u=r.uniforms,c=u.uColor.value;
        q.frames.push({time:performance.now()-started,cut:u.uCut.value,flash:u.uFlash.value,
          motionTime:u.uTime.value,color:[c.r,c.g,c.b],stage:u.uStage.value});
        if(performance.now()-started>=24000){q.done=true;return;}
        requestAnimationFrame(tick);
      }
      requestAnimationFrame(tick);
    }""")
    wait_probe(engine, "() => window.__qaRaveReduced.done", 30)
    value = engine.evaluate("""() => {const q=window.__qaRaveReduced;return {
      frames:q.frames,buffers:q.buffers.map(e=>{
        const a=e.attr.array,x=new Uint8Array(a.buffer,a.byteOffset,a.byteLength);
        return {name:e.name,bytes:x.length,identical:x.length===e.bytes.length&&x.every((v,i)=>v===e.bytes[i])};
      })};}""")
    rows = value["frames"]
    value["passed"] = (all(row["identical"] for row in value["buffers"]) and
                       all(row["cut"] == 1 and row["flash"] == 0 for row in rows) and
                       len({row["motionTime"] for row in rows}) == 1)
    color_changes = [(after["time"], max(abs(a - b) for a, b in zip(after["color"], before["color"])))
                     for before, after in zip(rows, rows[1:])]
    value["maximumFrameColorDelta"] = max((delta for _, delta in color_changes), default=0)
    active = [stamp for stamp, delta in color_changes if delta > 1e-7]
    value["colorChangeDurationMs"] = active[-1] - active[0] if len(active) > 1 else 0
    gaps = [after["time"] - before["time"] for before, after in zip(rows, rows[1:])]
    value["maximumSampleGapMs"] = max(gaps, default=0)
    value["colorPassed"] = bool(active) and (
        value["colorChangeDurationMs"] + value["maximumSampleGapMs"] >= 4 * 60 / 140 * 1000)
    path("world-reduced-motion.json").write_text(json.dumps(value, indent=2), encoding="utf-8")
    value["frameCount"] = len(value.pop("frames"))
    return value


def inspect_compilation(engine):
    return engine.evaluate("""() => {
      const v=window.__vc,materials=new Set(),uncompiled=[];
      if(!v.scene)return {verified:false,reason:'scene unavailable for material inspection'};
      v.scene.traverse(o=>{if(o.material){
        if(Array.isArray(o.material))for(const m of o.material)materials.add(m);
        else materials.add(o.material);
      }});
      for(const m of materials)if(!v.renderer.properties.get(m).programs?.size)
        uncompiled.push({type:m.type,name:m.name});
      return {verified:true,declared:v.compilation,materialCount:materials.size,
        programCount:v.renderer.info.programs.length,uncompiled};
    }""")


def verify_light_policy(engine):
    rows = []
    for mode in ("overview", "focus", "ride"):
        set_mode(engine, mode)
        for setting in ("Full", "Soft", "Calm"):
            engine.evaluate("s => window.__vc.lights.setSetting(s)", setting)
            engine.wait(2)
            value = engine.evaluate("""() => {const l=window.__vc.lights;return {
              intensity:l.intensity,amplitude:l.amplitude,modeFactor:l.modeFactor,
              cutFactor:l.cutFactor,strobes:l.strobes,colorDuration:l.colorDuration,
              pulse:l.pulse(1),stored:localStorage.getItem('vc-lights')};}""")
            rows.append({"mode": mode, "setting": setting, **value})
    engine.evaluate("() => window.__vc.lights.setSetting('Full')")
    engine.wait(1.1)
    limiter = engine.evaluate("""() => {
      const l=window.__vc.lights,now=performance.now(),results=[];
      for(let i=0;i<10;i++)results.push(l.requestFlash(now));
      l.setSetting('Calm');return {results,calmPulse:l.pulse(1),calmFlash:l.requestFlash(now+2000)};
    }""")
    factors = {"Full": 1, "Soft": .5, "Calm": .2}
    cuts = {"Full": .15, "Soft": .5, "Calm": 1}
    return {"settings": rows, **limiter}, {
        "overview and district focus reaction factor 0.6": all(
            abs(row["modeFactor"] - (1 if row["mode"] == "ride" else .6)) < .001
            for row in rows),
        "Full Soft Calm amplitudes and cut factors": all(
            abs(row["amplitude"] - factors[row["setting"]]) < .001 and
            abs(row["intensity"] - factors[row["setting"]] * row["modeFactor"]) < .001 and
            abs(row["cutFactor"] - cuts[row["setting"]]) < .001 for row in rows),
        "Lights setting remembered": all(row["stored"] == row["setting"] for row in rows),
        "Soft and Calm strobes off": all(row["strobes"] == (row["setting"] == "Full") for row in rows),
        "Calm colors take at least one bar": all(row["colorDuration"] >= 4 * 60 / 140
            for row in rows if row["setting"] == "Calm"),
        "kick pulses remain below general flash threshold": all(
            0 <= row["pulse"] < .10 for row in rows),
        "limiter at most 3 flashes in a second": sum(limiter["results"]) <= 3,
        "Calm disables flashes": not limiter["calmFlash"],
    }


def verify_reduced_motion(engine, url):
    engine.page.emulate_media(reduced_motion="reduce")
    engine.goto(url)
    engine.ready()
    engine.wait(2)
    return engine.evaluate("""() => {
      const l=window.__vc.lights;l.setSetting('Full');
      return {setting:l.setting,selectDisabled:document.getElementById('lights-setting').disabled,
        pulse:l.pulse(1),flash:l.requestFlash(performance.now()),cutFactor:l.cutFactor,
        colorDuration:l.colorDuration,strobes:l.strobes};
    }""")


def verify_phone(engine, url, path):
    engine.page.emulate_media(reduced_motion="no-preference")
    engine.page.set_viewport_size({"width": 375, "height": 844})
    engine.goto(url)
    engine.ready()
    engine.wait(2)
    result = engine.evaluate("""() => {const v=window.__vc;return {
      width:innerWidth,overflow:document.documentElement.scrollWidth>innerWidth,
      initialTier:v.tier.initial,currentTier:v.tier.current,pixelRatio:v.renderer.getPixelRatio(),
      peopleCapacity:v.people.length,vehicleCapacity:v.carState.length};}""")
    engine.screenshot(path("world-phone.png"))
    return result


def verify_governor(engine, url):
    """Drive the production governor with known frame spans after scene measurements."""
    engine.page.set_viewport_size({"width": 1440, "height": 900})
    engine.goto(url)
    engine.ready()
    return engine.evaluate("""() => {
      const t=window.__vc.tier,rows=[],initial=t.current,initialSettledMs=t.settledForMs;
      function raveCounts(){const r=window.__vc.rave;if(!r)return null;r.update(0);
        return {tier:t.current,lasers:r.lasers.count,drones:r.drones.geometry.drawRange.count,
          searchlights:r.searchlights.count};}
      const initialRave=raveCounts();
      function feed(count,ms){for(let i=0;i<count;i++){
        const before=t.current,settledBefore=t.settledForMs;t.update(ms);
        fastSpan=t.meanMs<12?fastSpan+ms:0;
        if(t.current!==before){rows.push({elapsed:elapsed+ms,before,after:t.current,
          mean:t.meanMs,sincePreviousChangeMs:settledBefore+ms,fastSpanMs:fastSpan,
          rave:raveCounts()});fastSpan=0;}
        elapsed+=ms;}}
      let elapsed=0,fastSpan=0;feed(300,20);const slow=t.current;feed(150,20);const floor=t.current;
      const recoveryStart=elapsed;feed(999,10);const beforeTenSeconds=t.current;
      feed(350,10);const recovered=t.current;
      return {initial,initialSettledMs,slow,floor,beforeTenSeconds,recovered,recoveryStart,initialRave,changes:rows};
    }""")


def verify_design_v4(design_path=None):
    """V4 design gates on data/city-design.json through qa_design.py (C6.7, the lake clearances, the
    C4.1 re-flow with zero stage, venue and furniture overlaps): every gate becomes a check named
    'design: <gate>'. Positive controls: python qa_design.py --control."""
    import qa_design
    page = json.loads(Path(design_path or ROOT / "data" / "city-design.json").read_text(encoding="utf-8"))
    layout = json.loads((ROOT / "data" / "layout.json").read_text(encoding="utf-8"))
    res = qa_design.run(qa_design.expand(page), layout, quiet=True)
    report = {name: {"pass": ok, "measured": measured} for name, (ok, measured) in res.items()}
    return report, {"design: " + name: ok for name, (ok, _) in res.items()}


ROADS_PROBE = """([ref, turnRef, tamper]) => {
  if (tamper) (0, eval)(tamper);
  const v = window.__vc, r = v.roads;
  if (!r) return {missing: true};
  let tourMax = 0, turnMax = 0, surfaceMiss = 0, surfaceMax = 0;
  const p = new v.camera.position.constructor();
  for (const [k, x, y, z] of ref) {
    r.tour.point(k, p);
    tourMax = Math.max(tourMax, Math.hypot(p.x - x, -p.z - y, p.y - z));
    const h = r.surfaceAtRoad(p.x, p.z, p.y);
    if (h === null) surfaceMiss++; else surfaceMax = Math.max(surfaceMax, Math.abs(h - p.y));
  }
  for (const [k, count, pts] of turnRef) {
    const t = r.graph.turns[k];
    if (!t || t.points.length !== count) { turnMax = Infinity; continue; }
    for (const [j, x, y, z] of pts) turnMax = Math.max(turnMax, Math.hypot(t.points[j][0] - x, t.points[j][1] - y, t.points[j][2] - z));
  }
  const districts = r.tour.entries.map(e => r.tour.sample(e.s + 0.05, {point: p.clone(), tangent: p.clone()}).district === e.district);
  const rim = v.routes.find(q => q.kind === 'rim');
  return {tourMax, turnMax, surfaceMiss, surfaceMax, samples: ref.length, tourLength: r.tour.length,
    count: r.tour.count, turns: r.graph.turns.length, districtsOk: districts.every(Boolean),
    rim: rim ? {open: rim.open, width: rim.width, clearance: rim.clearance, length: rim.length} : null};
}"""


def verify_roads(engine, tamper=None):
    """V4a: viewer/roads.js rebuilds the page data exactly as qa_design.py does (tour polyline and turn
    arcs, compared point by point), surfaceAtRoad finds the tour's road height, each tour entry samples
    as its district, and the Archive east rim road is drawn as its own open stretch at its own width and
    clearance. tamper is JavaScript run first (the positive control)."""
    import qa_design
    page = json.loads((ROOT / "data" / "city-design.json").read_text(encoding="utf-8"))
    full = qa_design.expand(page)
    pts = full["tour"]["points"]
    ref = [[k, *pts[k]] for k in range(0, len(pts), 3)]
    turn_ref = [[k, len(t["points"]), [[j, *t["points"][j]] for j in range(len(t["points"]))]]
                for k, t in enumerate(full["graph"]["turns"])]
    closed = pts + pts[:1]
    length = sum(math.dist(a[:2], b[:2]) for a, b in zip(closed, closed[1:]))
    rim = next(r for r in page["routes"] if r.get("kind") == "rim")
    own, total = [rim["points"][0]], 0.0
    for a, b in zip(rim["points"], rim["points"][1:]):
        total += math.dist(a, b)
        if total > rim["shared"][0]["from"] + 1e-4:
            break
        own.append(b)
    own_length = sum(math.dist(a, b) for a, b in zip(own, own[1:]))
    got = engine.evaluate(ROADS_PROBE, [ref, turn_ref, tamper])
    report = {**got, "pythonTourLength": length, "rimOwnLength": own_length}
    if got.get("missing"):
        return report, {name: False for name in ("roads.js rebuilds the tour and turn arcs from the page data",
                                                  "surfaceAtRoad finds the tour's road height",
                                                  "tour samples its entries' districts",
                                                  "rim road drawn as its own open stretch")}
    rim_row = got["rim"] or {}
    checks = {
        "roads.js rebuilds the tour and turn arcs from the page data":
            got["tourMax"] < 1e-6 and got["turnMax"] < 1e-6 and got["count"] == len(pts) and
            got["turns"] == len(full["graph"]["turns"]) and abs(got["tourLength"] - length) < 1e-6,
        "surfaceAtRoad finds the tour's road height": got["surfaceMiss"] == 0 and got["surfaceMax"] <= 0.02,
        "tour samples its entries' districts": got["districtsOk"],
        "rim road drawn as its own open stretch":
            rim_row.get("open") is True and rim_row.get("width") == rim["width"] and
            rim_row.get("clearance") == rim["clearanceOwn"] and abs(rim_row.get("length", 0) - own_length) < 1e-6,
    }
    return report, checks


BRIDGES_PROBE = r"""async ([tamper]) => {
  const v = window.__vc, r = v.roads, hyp = Math.hypot, RAD = Math.PI / 180;
  const frame = () => new Promise(res => requestAnimationFrame(() => requestAnimationFrame(res)));
  const wait = ms => new Promise(res => setTimeout(res, ms));
  if (!r || !r.deck || !r.rings) return {missing: true};
  if (tamper) (0, eval)(tamper);
  const out = {}, design = r.bridges, info = r.bridgeInfo, rings = r.rings;
  // Segment grids over layout polylines [x, y, (z)]: near(x, y) lists the segments of every cell within 1.2.
  function segGrid(list) {
    const cells = new Map(), segs = [];
    list.forEach((o, oi) => { const P = o.P, n = P.length, m = o.closed ? n : n - 1;
      for (let k = 0; k < m; k++) { const a = P[k], b = P[(k + 1) % n], id = segs.length; segs.push({a, b, o, k});
        for (let i = Math.floor((Math.min(a[0], b[0]) - 1.2) / 2); i <= Math.floor((Math.max(a[0], b[0]) + 1.2) / 2); i++)
          for (let j = Math.floor((Math.min(a[1], b[1]) - 1.2) / 2); j <= Math.floor((Math.max(a[1], b[1]) + 1.2) / 2); j++) {
            const c = i * 100000 + j; if (!cells.has(c)) cells.set(c, []); cells.get(c).push(id); } } });
    return {segs, near: (x, y) => cells.get(Math.floor(x / 2) * 100000 + Math.floor(y / 2)) || []};
  }
  // Distance from (x, y) to one segment, with the parameter along it.
  const D = {d: 0, t: 0};
  function segDist(a, b, x, y) { const dx = b[0] - a[0], dy = b[1] - a[1], l2 = dx * dx + dy * dy, t = l2 ? Math.max(0, Math.min(1, ((x - a[0]) * dx + (y - a[1]) * dy) / l2)) : 0;
    D.d = hyp(x - a[0] - dx * t, y - a[1] - dy * t); D.t = t; return D; }
  const cumOf = P => { const c = [0]; for (let i = 1; i < P.length; i++) c.push(c[i - 1] + hyp(P[i][0] - P[i - 1][0], P[i][1] - P[i - 1][1])); return c; };
  const inWedge = (f, x, y) => { const dx = x - f.cx, dy = y - f.cy; return {d: hyp(dx, dy), u: (((Math.atan2(dy, dx) / RAD - f.a0) % 360 + 540) % 360 - 180) / (f.a1 - f.a0)}; };
  const ringGrid = segGrid(rings.map(q => ({P: q.points, closed: true, q})));
  const bridgeGrid = segGrid(design.map((b, i) => ({P: b.points, closed: false, b, i, cum: cumOf(b.points)})));
  const ends = [];
  design.forEach((b, bi) => b.ends.forEach((e, k) => ends.push({b, bi, e, k})));

  // ---- A: every new material links and runs (three.js reports a failed compile only through diagnostics).
  const gl = v.renderer.getContext();
  v.renderer.compile(v.scene, v.camera);
  const mats = {deck: r.deck.material, links: r.links.material, rails: r.rails.material, pylons: r.pylons.material, cables: r.cables.material,
    underglow: r.underglow.material, lamps: r.bridgeLamps.material, pools: r.lampPools.material};
  out.programs = {};
  for (const [k, m] of Object.entries(mats)) { const p = v.renderer.properties.get(m).currentProgram;
    out.programs[k] = !p ? false : p.diagnostics ? p.diagnostics.runnable === true : gl.getProgramParameter(p.program, gl.LINK_STATUS) === true; }
  out.polygonOffset = r.deck.material.polygonOffset === true && r.deck.material.polygonOffsetUnits < 0 && r.deck.material.polygonOffsetFactor <= 0;

  // ---- B: every junction is paved without a gap. The paved union around each bridge end (the ring's road and
  // sidewalks, the stub out to just past the fillet tangency, the two fillet corners out to the curb's outer
  // edge) is sampled every 0.04; each sample needs a drawn triangle (the deck mesh or a street ribbon) over it
  // at its height.
  const streetGroup = r.lampPools.parent, tris = [], tgrid = new Map(), TC = .5;
  const side3 = (ax, ay, bx, by, px, py) => (bx - ax) * (py - ay) - (by - ay) * (px - ax);
  const linkBoxes = (r.streets || []).map(st => { const xs = st.points.map(q => q[0]), ys = st.points.map(q => q[1]); return [Math.min(...xs) - 1, Math.min(...ys) - 1, Math.max(...xs) + 1, Math.max(...ys) + 1]; });
  const nearEnd = (x, y) => ends.some(q => hyp(x - q.e.x, y - q.e.y) < 3.6) || linkBoxes.some(b => x > b[0] && x < b[2] && y > b[1] && y < b[3]);
  function addMesh(mesh) {
    mesh.updateMatrixWorld(true);
    const g = mesh.geometry, P = g.attributes.position.array, I = g.index ? g.index.array : null, n = I ? I.length : P.length / 3, M = mesh.matrixWorld.elements;
    const Wp = i => [M[0] * P[i * 3] + M[4] * P[i * 3 + 1] + M[8] * P[i * 3 + 2] + M[12], M[1] * P[i * 3] + M[5] * P[i * 3 + 1] + M[9] * P[i * 3 + 2] + M[13], M[2] * P[i * 3] + M[6] * P[i * 3 + 1] + M[10] * P[i * 3 + 2] + M[14]];
    for (let t = 0; t + 2 < n; t += 3) {
      const a = Wp(I ? I[t] : t), b = Wp(I ? I[t + 1] : t + 1), c = Wp(I ? I[t + 2] : t + 2);
      const tri = [a[0], -a[2], b[0], -b[2], c[0], -c[2], (a[1] + b[1] + c[1]) / 3];
      // A degenerate triangle covers nothing (it would pass every side test).
      if (Math.abs(side3(tri[0], tri[1], tri[2], tri[3], tri[4], tri[5])) < 1e-10) continue;
      if (!nearEnd(tri[0], tri[1]) && !nearEnd(tri[2], tri[3]) && !nearEnd(tri[4], tri[5])) continue;
      const id = tris.length; tris.push(tri);
      for (let i = Math.floor(Math.min(tri[0], tri[2], tri[4]) / TC); i <= Math.floor(Math.max(tri[0], tri[2], tri[4]) / TC); i++)
        for (let j = Math.floor(Math.min(tri[1], tri[3], tri[5]) / TC); j <= Math.floor(Math.max(tri[1], tri[3], tri[5]) / TC); j++) {
          const c2 = i * 100000 + j; if (!tgrid.has(c2)) tgrid.set(c2, []); tgrid.get(c2).push(id); }
    }
  }
  addMesh(r.deck);
  addMesh(r.links);
  streetGroup.children.forEach(o => { if (o.isMesh && !o.isInstancedMesh && o.geometry.attributes.position) addMesh(o); });
  function drawnAt(x, y, h) {
    for (const id of tgrid.get(Math.floor(x / TC) * 100000 + Math.floor(y / TC)) || []) { const t = tris[id]; if (Math.abs(t[6] - h) > .06) continue;
      const d1 = side3(t[0], t[1], t[2], t[3], x, y), d2 = side3(t[2], t[3], t[4], t[5], x, y), d3 = side3(t[4], t[5], t[0], t[1], x, y);
      if (!((d1 < 0 || d2 < 0 || d3 < 0) && (d1 > 0 || d2 > 0 || d3 > 0))) return true; }
    return false;
  }
  let gaps = 0, sampled = 0; const gapsBy = {};
  for (const {b, bi, e, k} of ends) {
    const P = b.points, n = P.length, a = k ? P[n - 1] : P[0], c = k ? P[n - 2] : P[1], l = hyp(c[0] - a[0], c[1] - a[1]), u = [(c[0] - a[0]) / l, (c[1] - a[1]) / l], t = [-u[1], u[0]];
    const bs = k ? info[bi].bsB : info[bi].bsA, L = info[bi].length, ring = rings[e.route], cum = cumOf(P);
    for (let al = -.7; al <= bs + .25; al += .04) for (let ac = -2.4; ac <= 2.4; ac += .04) {
      const x = a[0] + u[0] * al + t[0] * ac, y = a[1] + u[1] * al + t[1] * ac;
      let paved = false;
      for (const id of ringGrid.near(x, y)) { const s = ringGrid.segs[id]; if (s.o.q === ring && segDist(s.a, s.b, x, y).d <= ring.half - .02) { paved = true; break; } }
      if (!paved) for (let q = 0; q + 1 < n; q++) { const dd = segDist(P[q], P[q + 1], x, y); if (dd.d > .55) continue; const s = cum[q] + dd.t * (cum[q + 1] - cum[q]);
        if ((k ? L - s : s) <= bs + .25) { paved = true; break; } }
      if (!paved) for (const f of e.fillets) { const w = inWedge(f, x, y); if (w.u > .02 && w.u < .98 && w.d >= .79 && w.d <= 1.34) { paved = true; break; } }
      if (!paved) continue;
      sampled++;
      if (!drawnAt(x, y, e.z)) { gaps++; const key = b.name + (k ? ' B' : ' A'); gapsBy[key] = (gapsBy[key] || 0) + 1; }
    }
  }
  out.junctions = {sampled, gaps, gapsBy, triangles: tris.length};
  // The six Archive rim links: their carriageway and both sidewalks drawn every 0.1 along their length.
  let linkSamples = 0, linkGaps = 0;
  for (const st of r.streets || []) { const P = st.points, cum = cumOf(P);
    for (let s = 0, j = 0; s < cum[cum.length - 1]; s += .1) { while (cum[j + 1] < s) j++; const a = P[j], b = P[j + 1], ll = cum[j + 1] - cum[j], tt = (s - cum[j]) / ll;
      for (const m of [-.33, 0, .33]) { const x = a[0] + (b[0] - a[0]) * tt - (b[1] - a[1]) / ll * m, y = a[1] + (b[1] - a[1]) * tt + (b[0] - a[0]) / ll * m;
        linkSamples++; if (!drawnAt(x, y, st.z)) linkGaps++; } } }
  out.links = {count: (r.streets || []).length, samples: linkSamples, gaps: linkGaps};

  // ---- C: rails. Required every 0.1: the outer edge of every circular ring and of the rim road's own stretch
  // (2 clear of its forks), both edges of every bridge span and every fillet curb. Open: a bridge mouth between
  // its two fillet tangencies, a stage deck within 0.3, the pier's foot, the Reef shore within 1.7 of the lake.
  // Forbidden, every 0.05 along every rail: any ring, rim road or bridge carriageway, a paved fillet corner, a
  // stage deck.
  const segs = [], rgrid = new Map();
  for (const run of r.railRuns) for (let i = 0; i + 1 < run.points.length; i++) { const p = run.points[i], q = run.points[i + 1], id = segs.length; segs.push([p[0], p[1], q[0], q[1], p[2], q[2]]);
    for (let x = Math.floor(Math.min(p[0], q[0]) - .1); x <= Math.floor(Math.max(p[0], q[0]) + .1); x++)
      for (let y = Math.floor(Math.min(p[1], q[1]) - .1); y <= Math.floor(Math.max(p[1], q[1]) + .1); y++) { const c2 = x * 100000 + y; if (!rgrid.has(c2)) rgrid.set(c2, []); rgrid.get(c2).push(id); } }
  const railed = (x, y, h) => { for (const id of rgrid.get(Math.floor(x) * 100000 + Math.floor(y)) || []) { const s = segs[id], dd = segDist([s[0], s[1]], [s[2], s[3]], x, y);
      if (dd.d < .035 && Math.abs(s[4] + (s[5] - s[4]) * dd.t - h) < .06) return true; } return false; };
  const lake = r.lake, decks = v.stages.filter(s => s.kind === 'deck');
  const shoreGap = (x, y) => { let d = Infinity; const ca = Math.cos(lake.angle), sa = Math.sin(lake.angle);
    for (let i = 0; i < 360; i++) { const tt = i / 360 * 2 * Math.PI, uu = Math.cos(tt) * lake.rx, vv = Math.sin(tt) * lake.ry; d = Math.min(d, hyp(x - lake.cx - uu * ca + vv * sa, y - lake.cy - uu * sa - vv * ca)); } return d; };
  const openAt = (x, y, h, district) => {
    for (const s of decks) if (Math.abs(s.z - h) < .3 && hyp(x - s.x, y - s.y) - s.r < .3) return true;
    if (lake && lake.pier && hyp(x - lake.pier.x0, y - lake.pier.y0) < 1.0) return true;
    return district === 'reef' && lake && shoreGap(x, y) < 1.7;
  };
  let required = 0, missing = 0; const missingBy = {};
  const need = (x, y, h, label) => { required++; if (!railed(x, y, h)) { missing++; missingBy[label] = (missingBy[label] || 0) + 1; } };
  for (const ring of rings) {
    const mouths = ends.filter(q => q.e.route === ring.route).map(q => q.e.fillets.map(f => [f.cx + Math.cos(f.a0 * RAD) * f.r, f.cy + Math.sin(f.a0 * RAD) * f.r]));
    if (ring.disc) {
      const RR = ring.R + ring.half - .015, N = Math.ceil(2 * Math.PI * RR / .1);
      const spans = mouths.map(m => { const a0 = Math.atan2(m[0][1] - ring.cy, m[0][0] - ring.cx), a1 = Math.atan2(m[1][1] - ring.cy, m[1][0] - ring.cx);
        let lo = Math.min(a0, a1), hi = Math.max(a0, a1); if (hi - lo > Math.PI) [lo, hi] = [hi, lo + 2 * Math.PI]; return [lo, hi]; });
      for (let i = 0; i < N; i++) { const a = i / N * 2 * Math.PI, x = ring.cx + Math.cos(a) * RR, y = ring.cy + Math.sin(a) * RR, m = .05 / RR;
        if (spans.some(([lo, hi]) => [a, a + 2 * Math.PI, a - 2 * Math.PI].some(aa => aa > lo - m && aa < hi + m)) || openAt(x, y, ring.z, ring.district)) continue;
        need(x, y, ring.z, ring.district + ' rim'); }
    } else if (ring.own !== null) {
      const P = ring.points, cum = cumOf(P);
      const proj = p => { let best = Infinity, s = 0; for (let k = 0; k + 1 < P.length; k++) { const dd = segDist(P[k], P[k + 1], p[0], p[1]); if (dd.d < best) { best = dd.d; s = cum[k] + dd.t * (cum[k + 1] - cum[k]); } } return s; };
      const spans = mouths.map(m => m.map(proj).sort((x1, x2) => x1 - x2));
      for (let s = 2, j = 0; s < ring.own - 2; s += .1) { while (cum[j + 1] < s) j++; const a = P[j], b = P[j + 1], tt = (s - cum[j]) / (cum[j + 1] - cum[j]), ll = hyp(b[0] - a[0], b[1] - a[1]), o = ring.half - .015;
        const x = a[0] + (b[0] - a[0]) * tt + (b[1] - a[1]) / ll * o, y = a[1] + (b[1] - a[1]) * tt - (b[0] - a[0]) / ll * o;
        if (spans.some(([lo, hi]) => s > lo - .05 && s < hi + .05) || openAt(x, y, ring.z, ring.district)) continue;
        need(x, y, ring.z, 'rim road'); }
    }
  }
  // The Archive (a rounded rectangle with avenue loops and the rim road hanging over its rims): its plateau
  // outline and every non-circular loop's outer edge, wherever no other surface at its height covers them.
  const loops = rings.filter(q => !q.disc).map(q => ({q, g: segGrid([{P: q.points, closed: true}])}));
  const inLoop = (x, y, h, skip) => loops.some(({q, g}) => { if (q === skip || Math.abs(q.z - h) > .25) return false;
    let best = Infinity; for (const id of g.near(x, y)) { const s = g.segs[id]; best = Math.min(best, segDist(s.a, s.b, x, y).d); }
    if (best < q.half - .03) return true;
    let inside = false; const P = q.points; for (let i = 0, j = P.length - 1; i < P.length; j = i++) { const a = P[i], b = P[j]; if ((a[1] > y) !== (b[1] > y) && x < (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0]) inside = !inside; }
    return inside; });
  const linkList = (r.streets || []).map(st => ({P: st.points, z: st.z, half: st.width / 2, walk: st.width / 2 + st.sidewalk}));
  const linkDist = (k, x, y) => { let best = Infinity; for (let i = 0; i + 1 < k.P.length; i++) best = Math.min(best, segDist(k.P[i], k.P[i + 1], x, y).d); return best; };
  const inLink = (x, y, h, skip) => linkList.some(k => k !== skip && Math.abs(k.z - h) < .25 && linkDist(k, x, y) < k.walk - .03);
  const inMouth = (x, y, h) => ends.some(({b, e}) => { if (Math.abs(e.z - h) > .2) return false;
    if (e.fillets.some(f => { const w = inWedge(f, x, y); return w.u > -.02 && w.u < 1.02 && w.d >= .7 && w.d <= 1.4; })) return true;
    const P = b.points; for (let q = 0; q + 1 < P.length; q++) if (segDist(P[q], P[q + 1], x, y).d < .6 && hyp(x - e.x, y - e.y) < 1.6) return true; return false; });
  for (const [d, p] of Object.entries(r.plateaus)) { if (p.shape === 'disc') continue;
    const rr = 2.5, ax = p.rx - rr, ay = p.ry - rr, sdf = (x, y) => { const qx = Math.abs(x - p.cx) - ax, qy = Math.abs(y - p.cy) - ay; return hyp(Math.max(qx, 0), Math.max(qy, 0)) + Math.min(Math.max(qx, qy), 0) - rr; };
    const N = Math.ceil(2 * Math.PI * hyp(p.rx, p.ry) / .1);
    for (let i = 0; i < N; i++) { const a = i / N * 2 * Math.PI; let x = p.cx + Math.cos(a) * (p.rx + p.ry + 10), y = p.cy + Math.sin(a) * (p.rx + p.ry + 10);
      // March inward from outside along the ray to the outline (inset 0.015).
      let lo = 0, hi = 1; const ox = p.cx, oy = p.cy; for (let k = 0; k < 40; k++) { const m = (lo + hi) / 2; if (sdf(ox + (x - ox) * m, oy + (y - oy) * m) < -.015) lo = m; else hi = m; }
      x = ox + (x - ox) * lo; y = oy + (y - oy) * lo;
      if (inLoop(x, y, p.z, null) || inLink(x, y, p.z, null) || openAt(x, y, p.z, d) || inMouth(x, y, p.z)) continue;
      need(x, y, p.z, d + ' plateau outline'); }
    for (const {q} of loops) { const P = q.points, n = P.length, cum = cumOf(P.concat([P[0]])), total = cum[n], o = q.half - .015;
      for (let s = 0, j = 0; s < total; s += .1) { while (cum[j + 1] < s) j++; const a = P[j], b = P[(j + 1) % n], ll = hyp(b[0] - a[0], b[1] - a[1]) || 1, tt = (s - cum[j]) / ll;
        const x = a[0] + (b[0] - a[0]) * tt + (b[1] - a[1]) / ll * o, y = a[1] + (b[1] - a[1]) * tt - (b[0] - a[0]) / ll * o;
        if (sdf(x, y) < -.03 || inLoop(x, y, q.z, q) || inLink(x, y, q.z, null) || openAt(x, y, q.z, d) || inMouth(x, y, q.z)) continue;
        need(x, y, q.z, d + ' loop edge ' + q.route); } }
    // The rim links' outer edges, where they run along the rim between two avenues.
    for (const k of linkList) { const P = k.P, cum = cumOf(P), o = k.walk - .015;
      for (const sd of [-1, 1]) for (let s = 0, j = 0; s < cum[cum.length - 1]; s += .1) { while (cum[j + 1] < s) j++; const a = P[j], b = P[j + 1], ll = cum[j + 1] - cum[j], tt = (s - cum[j]) / ll;
        const x = a[0] + (b[0] - a[0]) * tt - (b[1] - a[1]) / ll * sd * o, y = a[1] + (b[1] - a[1]) * tt + (b[0] - a[0]) / ll * sd * o;
        if (sdf(x, y) < -.03 || inLoop(x, y, k.z, null) || inLink(x, y, k.z, k) || openAt(x, y, k.z, d) || inMouth(x, y, k.z)) continue;
        need(x, y, k.z, d + ' link edge'); } }
  }
  design.forEach((b, bi) => { const P = b.points, cum = cumOf(P), L = info[bi].length;
    for (const sd of [-1, 1]) for (let s = info[bi].bsA + .1, j = 0; s < L - info[bi].bsB - .1; s += .1) { while (cum[j + 1] < s) j++;
      const a = P[j], q = P[j + 1], ll = cum[j + 1] - cum[j], tt = (s - cum[j]) / ll, nx = -(q[1] - a[1]) / ll, ny = (q[0] - a[0]) / ll;
      need(a[0] + (q[0] - a[0]) * tt + nx * sd * .555, a[1] + (q[1] - a[1]) * tt + ny * sd * .555, a[2] + (q[2] - a[2]) * tt, b.name + ' edge'); }
    b.ends.forEach(e => e.fillets.forEach(f => { for (let u2 = .04; u2 < .96; u2 += .04) { const ang = (f.a0 + (f.a1 - f.a0) * u2) * RAD, x = f.cx + Math.cos(ang) * .785, y = f.cy + Math.sin(ang) * .785;
      if (!openAt(x, y, e.z, e.district)) need(x, y, e.z, b.name + ' corner'); } })); });
  let onRoad = 0, railPoints = 0; const onRoadBy = {};
  for (const run of r.railRuns) for (let i = 0; i + 1 < run.points.length; i++) { const p = run.points[i], q = run.points[i + 1], nn = Math.max(1, Math.ceil(hyp(q[0] - p[0], q[1] - p[1]) / .05));
    for (let j = 0; j < nn; j++) { const x = p[0] + (q[0] - p[0]) * j / nn, y = p[1] + (q[1] - p[1]) * j / nn, h = p[2] + (q[2] - p[2]) * j / nn; railPoints++;
      let bad = '';
      for (const id of ringGrid.near(x, y)) { const s = ringGrid.segs[id]; if (Math.abs(s.o.q.z - h) < .2 && segDist(s.a, s.b, x, y).d < s.o.q.roadHalf - .01) { bad = 'ring carriageway'; break; } }
      if (!bad) for (const id of bridgeGrid.near(x, y)) { const s = bridgeGrid.segs[id], dd = segDist(s.a, s.b, x, y); if (dd.d < .43 && Math.abs(s.a[2] + (s.b[2] - s.a[2]) * dd.t - h) < .2) { bad = 'bridge carriageway'; break; } }
      if (!bad) for (const {e} of ends) { if (Math.abs(e.z - h) > .2) continue; for (const f of e.fillets) { const w = inWedge(f, x, y); if (w.u > .02 && w.u < .98 && w.d > .91 && w.d < 1.34) bad = 'fillet corner'; } if (bad) break; }
      if (!bad && linkList.some(k => Math.abs(k.z - h) < .2 && linkDist(k, x, y) < k.half - .01)) bad = 'link carriageway';
      if (!bad) for (const s of decks) if (Math.abs(s.z - h) < .3 && hyp(x - s.x, y - s.y) < s.r - .05) { bad = 'stage deck'; break; }
      if (bad) { onRoad++; onRoadBy[bad] = (onRoadBy[bad] || 0) + 1; } } }
  const neonVertices = r.railRuns.reduce((acc, run) => acc + run.points.length * 6, 0);
  out.rails = {runs: r.railRuns.length, required, missing, missingBy, railPoints, onRoad, onRoadBy, meshVertices: r.rails.geometry.attributes.position.count, neonVertices};

  // ---- D: bridge walkers: a share at every tier, every walk path used at Tier 3, each path on a road surface
  // (surfaceAtRoad within 0.03), no step over 0.35 and never inside a footprint.
  const c = v.crowd, tiers = {};
  for (const level of [3, 2, 1]) { c.applyTier(level); let n = 0; const used = new Set();
    c.people.forEach((p, i) => { if (p.kind === 0 && p.path && c.isVisible(i, p)) { n++; used.add(p.path); } });
    tiers[level] = {bridgeWalkers: n, paths: used.size}; }
  c.applyTier(v.tier.current);
  let pathGap = 0, surfaceMiss = 0, surfaceMax = 0, blocked = 0, pathPoints = 0;
  for (const path of r.walkPaths) { const pts = path.points;
    for (let i = 0; i < pts.length; i++) { const p = pts[i]; pathPoints++;
      if (i) pathGap = Math.max(pathGap, pts[i - 1].distanceTo(p));
      const h = r.surfaceAtRoad(p.x, p.z, p.y); if (h === null) surfaceMiss++; else surfaceMax = Math.max(surfaceMax, Math.abs(h - p.y));
      const foot = p.clone(); foot.y += .18; if (v.pointBlocked(foot, .07, false)) blocked++; } }
  const walkers = c.people.filter(p => p.kind === 0 && p.path);
  out.walkers = {tiers, paths: r.walkPaths.length, pathGap, surfaceMiss, surfaceMax, blocked, pathPoints, total: walkers.length, styles: [...new Set(walkers.map(p => p.style))]};

  // ---- E: packets through the limiter, sound off (source 0.5) in the overview (0.6).
  const pk = r.packets, desc = Object.getOwnPropertyDescriptor(v.tier, 'current'), levels = {};
  const settle = async () => { await wait(2300); await frame(); return pk.level; };
  const before = pk.count;
  for (const setting of ['Full', 'Soft', 'Calm']) { v.lights.setSetting(setting); levels[setting] = await settle(); }
  v.lights.setSetting('Full'); await settle();
  const tierSlots = {};
  for (const level of [3, 2, 1]) { Object.defineProperty(v.tier, 'current', {get: () => level, configurable: true}); r.update(); tierSlots[level] = pk.slots; }
  Object.defineProperty(v.tier, 'current', desc); r.update();
  const dirOk = Object.entries(pk.table).every(([d, dir]) => design.every((b, i) => b.from === d ? dir[i] === 1 : b.to === d ? dir[i] === -1 : true));
  out.packets = {levels, kicks: pk.count - before, tierSlots, dirOk, room: pk.room, sound: v.beat.sound};

  // ---- F: bridge lamps (city-life.js's rule): on the left sidewalk of the from-to direction at 0.51 from the
  // centreline, on the deck surface, and drawn where the data says.
  let lampBad = 0; const arr = r.bridgeLamps.instanceMatrix.array;
  r.bridgeLampSpots.forEach((s, k) => { const P = design[s.bridge].points, x = s.p.x, y = -s.p.z; let best = Infinity, sideSign = 0;
    for (let q = 0; q + 1 < P.length; q++) { const dd = segDist(P[q], P[q + 1], x, y); if (dd.d < best) { best = dd.d; sideSign = side3(P[q][0], P[q][1], P[q + 1][0], P[q + 1][1], x, y) > 0 ? 1 : -1; } }
    const h = r.surfaceAtRoad(s.p.x, s.p.z, s.p.y), drawn = hyp(arr[k * 16 + 12] - s.p.x, arr[k * 16 + 13] - s.p.y, arr[k * 16 + 14] - s.p.z) < 1e-4;
    if (sideSign !== 1 || Math.abs(best - .51) > .012 || h === null || Math.abs(h - s.p.y) > .03 || !drawn) lampBad++; });
  out.lamps = {count: r.bridgeLampSpots.length, drawn: r.bridgeLamps.count, bad: lampBad};

  // ---- H (V4 fix, C11.3): a crosswalk at every junction, read from the drawn stripes (instance matrices:
  // column 0 the stripe's width across the traffic, column 1 its length along it, column 3 its centre).
  const cw = r.crosswalks, cwOut = {tees: 0, forks: 0, stripes: 0, bad: 0, badExamples: [], walkSamples: 0, walkUncovered: 0, uncoveredExamples: []};
  if (cw) {
    const CA = cw.mesh.instanceMatrix.array, shown = cw.mesh.count;
    const stripe = i => { const o = i * 16, w = hyp(CA[o], CA[o + 2]), l = hyp(CA[o + 4], CA[o + 6]);
      return {x: CA[o + 12], y: -CA[o + 14], h: CA[o + 13], w, len: l, ux: CA[o + 4] / (l || 1), uy: -CA[o + 6] / (l || 1), drawn: i < shown && w > 1e-3 && l > 1e-3}; };
    const bad = (why, x) => { cwOut.bad++; if (cwOut.badExamples.length < 8) cwOut.badExamples.push(Object.assign({why}, x)); };
    // A route's full centreline at arc length s (closed, as the fillets' ringS count it), right-hand normal.
    const ringCum = new Map();
    const ringAt = (ri, s) => { const P = rings[ri].points, n = P.length; if (!ringCum.has(ri)) { const c = [0]; for (let i = 1; i <= n; i++) c.push(c[i - 1] + hyp(P[i % n][0] - P[i - 1][0], P[i % n][1] - P[i - 1][1])); ringCum.set(ri, c); }
      const cum = ringCum.get(ri), total = cum[n]; s = ((s % total) + total) % total; let lo = 0; while (lo + 1 < n && cum[lo + 1] <= s) lo++;
      const a = P[lo], b = P[(lo + 1) % n], t = (s - cum[lo]) / ((cum[lo + 1] - cum[lo]) || 1e-9), l = hyp(b[0] - a[0], b[1] - a[1]) || 1;
      return {x: a[0] + (b[0] - a[0]) * t, y: a[1] + (b[1] - a[1]) * t, nx: (b[1] - a[1]) / l, ny: -(b[0] - a[0]) / l}; };
    // Distance to a road's centreline (a route's own stretch only, like the page draws it).
    const ownPoints = ri => { const R = rings[ri], Q = R.points; if (R.own === null) return {P: Q, closed: true};
      const out = [Q[0]]; let s = 0; for (let i = 1; i < Q.length; i++) { s += hyp(Q[i][0] - Q[i - 1][0], Q[i][1] - Q[i - 1][1]); if (s > R.own + 1e-4) break; out.push(Q[i]); } return {P: out, closed: false}; };
    const owns = rings.map((R, ri) => ownPoints(ri));
    const roadGap = (ri, x, y) => { const {P, closed} = owns[ri], n = P.length, m = closed ? n : n - 1; let best = Infinity;
      for (let i = 0; i < m; i++) best = Math.min(best, segDist(P[i], P[(i + 1) % n], x, y).d); return best; };
    const tees = cw.list.filter(q => q.kind === 'tee'), forks = cw.list.filter(q => q.kind === 'fork');
    const teeEnds = new Set(tees.map(q => q.bridge + ':' + q.end)), forkEnds = new Set(forks.map(q => (q.branch === 'rim' ? 'r' + q.route : 's' + q.street) + ':' + q.end));
    cwOut.tees = ends.every(({bi, k}) => teeEnds.has(bi + ':' + k)) ? tees.length : -tees.length;
    const forkNeed = (r.streets || []).length * 2 + rings.filter(q => q.own !== null).length * 2;
    cwOut.forks = forkEnds.size === forkNeed ? forks.length : -forks.length;
    for (const q of tees) { const e = design[q.bridge].ends[q.end], ring = rings[e.route];
      if (q.count < 4) bad('few stripes', {bridge: q.bridge, end: q.end});
      const S = []; for (let i = q.first; i < q.first + q.count; i++) S.push(stripe(i));
      for (const st of S) { cwOut.stripes++;
        const off = roadGap(e.route, st.x, st.y), curb = Math.min(...e.fillets.map(f => hyp(st.x - f.cx, st.y - f.cy) - f.r));
        const surf = r.surfaceAtRoad(st.x, -st.y, e.z);
        if (!st.drawn || off < ring.roadHalf || curb < 0 || surf === null || Math.abs(surf - e.z) > .02 || Math.abs(st.h - e.z - .021) > .005)
          bad('tee stripe', {bridge: q.bridge, end: q.end, off: +off.toFixed(3), curb: +curb.toFixed(3), surf}); }
      // The ring walkers' line over the mouth: every sample on the mouth's asphalt (0.06 outside the fillet curbs) is under a stripe band.
      const walk = ring.roadHalf + .04;
      for (let s = q.lo; s <= q.hi; s += .05) { const p = ringAt(e.route, s), x = p.x + p.nx * walk, y = p.y + p.ny * walk;
        if (Math.min(...e.fillets.map(f => hyp(x - f.cx, y - f.cy) - f.r)) < .06) continue;
        cwOut.walkSamples++;
        const under = S.some(st => st.drawn && Math.abs((x - st.x) * st.ux + (y - st.y) * st.uy) <= st.len / 2 + 1e-3 && Math.abs((x - st.x) * -st.uy + (y - st.y) * st.ux) <= cw.stripe.step / 2 + 1e-3);
        if (!under) { cwOut.walkUncovered++; if (cwOut.uncoveredExamples.length < 6) cwOut.uncoveredExamples.push({bridge: q.bridge, end: q.end, s: +s.toFixed(2)}); } } }
    for (const q of forks) { if (q.count < 4) bad('few stripes', {fork: q.street, end: q.end});
      const P = q.branch === 'rim' ? owns[q.route].P : r.streets[q.street].points;
      const lats = [];
      for (let i = q.first; i < q.first + q.count; i++) { const st = stripe(i); cwOut.stripes++;
        let best = Infinity, lat = 0; for (let k = 0; k + 1 < P.length; k++) { const dd = segDist(P[k], P[k + 1], st.x, st.y); if (dd.d < best) { best = dd.d;
          lat = side3(P[k][0], P[k][1], P[k + 1][0], P[k + 1][1], st.x, st.y) > 0 ? dd.d : -dd.d; } }
        lats.push(lat);
        let other = Infinity; rings.forEach((R, ri) => { if (q.branch === 'rim' && ri === q.route) return; other = Math.min(other, roadGap(ri, st.x, st.y) - R.roadHalf - .13); });
        const surf = r.surfaceAtRoad(st.x, -st.y, q.z);
        if (!st.drawn || best > q.half - .02 || other < 0 || surf === null || Math.abs(surf - q.z) > .02 || Math.abs(st.h - q.z - .021) > .005)
          bad('fork stripe', {branch: q.branch, street: q.street, end: q.end, centre: +best.toFixed(3), other: +other.toFixed(3)}); }
      const span = Math.max(...lats) - Math.min(...lats) + cw.stripe.width;
      if (span < 2 * q.half - .2) bad('fork span', {branch: q.branch, street: q.street, end: q.end, span: +span.toFixed(3)}); }
  }
  out.crosswalks = cwOut;

  // ---- G: the draw calls and triangles this step adds, in the overview at the current tier.
  const extra = [r.deck, r.links, r.rails, r.pylons, r.cables, r.underglow, r.bridgeLamps, r.lampPools].concat(r.crosswalks ? [r.crosswalks.mesh] : []);
  v.placeCamera(); await frame(); await frame();
  const read = () => ({calls: v.renderer.info.render.calls, tris: v.renderer.info.render.triangles});
  const withAll = read(); extra.forEach(o => { o.visible = false; }); await frame(); await frame(); const without = read(); extra.forEach(o => { o.visible = true; }); await frame();
  out.budget = {calls: withAll.calls - without.calls, triangles: withAll.tris - without.tris, total: withAll};
  return out;
}"""


def verify_bridges(engine, url, tamper=None):
    """V4b (C6.3 as drawn, C6.4, C6.5, C11.3 crosswalk tees, C3.4 on bridges), with sound off: every new
    material links; every bridge junction is paved without a gap (the ring band, stub and fillet corners
    sampled every 0.04, each sample under a drawn deck or street triangle at its height; the deck carries a
    polygon offset, so its coplanar overlap on a ring cannot z-fight); rails run along every ring and rim
    road edge, both edges of every bridge span and every fillet curb except the bridge mouths, stage decks,
    the pier's foot and the Reef shore, and never over a carriageway, a paved corner or a stage deck; bridge
    walkers exist at every tier, use all 28 walk paths at Tier 3, and their paths sit on a road surface
    (within 0.03, no step over 0.35) and never inside a footprint; packets follow the Lights limiter (0.3,
    0.15 and 0.06 for Full, Soft and Calm in the overview with sound off: Calm is 20 % of the amplitude,
    C12.2) and the tier (8, 5, 3 slots) and leave every bridge from the active room's end, and under reduced
    motion (B9, a second load) the setting is Calm and no packet runs; every bridge lamp stands on its
    bridge's left sidewalk at 0.51 and is drawn there; the step adds at most 25 draw calls and 150 k
    triangles; the six Archive rim links are drawn (carriageway and both sidewalks every 0.1); and (V4 fix,
    C11.3) a crosswalk stands at every one of the graph's 42 junctions: at each of the 28 tees across the
    bridge's mouth on the ring's walking band, every stripe on paved mouth asphalt (off the ring's
    carriageway and outside the fillet curbs), and every point of the ring walkers' line (0.04 outside the
    kerb) over the mouth asphalt (0.06 clear of the curbs), sampled every 0.05, under the zebra; at each of
    the 14 forks (the rim
    road's two ends, the rim links' twelve) across the branch, every stripe on the branch's carriageway and
    off every other road's carriageway and sidewalk, the stripes spanning the carriageway to within 0.1 of
    both kerbs. tamper is JavaScript run first (the positive controls,
    renders/snap/wip/tools/v4b_controls.py and renders/snap/wip/v4fix/controls.py)."""
    engine.page.set_viewport_size({"width": 1440, "height": 900})
    engine.goto(url)
    engine.ready()
    engine.wait(1.5)
    got = engine.evaluate(BRIDGES_PROBE, [tamper])
    names = BRIDGE_CHECKS
    if got.get("missing"):
        return got, {name: False for name in names}
    # Reduced motion (B9): the Lights setting is Calm and the packets are off (level 0, no kick recorded).
    engine.page.emulate_media(reduced_motion="reduce")
    engine.goto(url)
    engine.ready()
    engine.wait(3)
    got["reducedPackets"] = engine.evaluate("""() => { const v = window.__vc, p = v.roads.packets;
      return {calm: v.lights.calm, level: p.level, kicks: p.count}; }""")
    engine.page.emulate_media(reduced_motion="no-preference")
    j, rl, w, p, lm, b, lk = got["junctions"], got["rails"], got["walkers"], got["packets"], got["lamps"], got["budget"], got["links"]
    checks = {
        names[0]: all(got["programs"].values()),
        names[1]: j["sampled"] > 10000 and j["gaps"] == 0 and got["polygonOffset"],
        names[2]: rl["required"] > 5000 and rl["missing"] == 0 and rl["meshVertices"] >= rl["neonVertices"],
        names[3]: rl["railPoints"] > 5000 and rl["onRoad"] == 0,
        names[4]: (all(t["bridgeWalkers"] > 0 for t in w["tiers"].values()) and w["tiers"]["3"]["paths"] == w["paths"] == 28 and
                   w["pathGap"] <= 0.35 and w["surfaceMiss"] == 0 and w["surfaceMax"] <= 0.03 and w["blocked"] == 0 and w["styles"] == ["walk"]),
        names[5]: (abs(p["levels"]["Full"] - 0.3) < 1e-3 and abs(p["levels"]["Soft"] - 0.15) < 1e-3 and abs(p["levels"]["Calm"] - 0.06) < 1e-3 and
                   p["kicks"] > 0 and p["tierSlots"] == {"3": 8, "2": 5, "1": 3} and p["dirOk"] and not p["sound"] and
                   got["reducedPackets"]["calm"] and got["reducedPackets"]["level"] == 0 and got["reducedPackets"]["kicks"] == 0),
        names[6]: lm["count"] > 0 and lm["drawn"] == lm["count"] and lm["bad"] == 0,
        names[7]: b["calls"] <= 25 and b["triangles"] <= 150000,
        names[8]: lk["count"] == 6 and lk["samples"] > 1000 and lk["gaps"] == 0,
        names[9]: (got["crosswalks"]["tees"] == 28 and got["crosswalks"]["forks"] == 14 and got["crosswalks"]["bad"] == 0 and
                   got["crosswalks"]["stripes"] >= 42 * 4 and got["crosswalks"]["walkSamples"] > 500 and got["crosswalks"]["walkUncovered"] == 0),
    }
    return got, checks


BRIDGE_CHECKS = ("bridge scene materials link and run", "bridge junctions paved without gaps or z-fighting",
                 "rails guard every rim and bridge edge except the openings", "no rail over a road or stage deck",
                 "walkers cross bridges at every tier on road surfaces", "bridge light packets follow the Lights limiter and tier",
                 "bridge lamps follow the city lamp rule", "bridges add at most 25 draw calls and 150 k triangles",
                 "Archive rim links drawn along their length", "a crosswalk at every junction on its walkers' line")


# ---------------------------------------------------------------- V4c: graph traffic, light cycles, re-flow, decks
# Shared page helpers for the V4c probes: segment grids in layout coordinates (x, y = -world z) and the
# carriageway of every road the traffic drives (ring, avenue and rim road stretches, the rim links, the
# bridges and the paved fillet corners), each with its height.
CARRIAGEWAY_JS = r"""
  const hyp = Math.hypot, RAD = Math.PI / 180;
  function segGrid() {
    const cells = new Map(), segs = [];
    return {segs, add(s) { const id = segs.length; segs.push(s);
        for (let i = Math.floor((Math.min(s.ax, s.bx) - s.half - .1) / 2); i <= Math.floor((Math.max(s.ax, s.bx) + s.half + .1) / 2); i++)
          for (let j = Math.floor((Math.min(s.ay, s.by) - s.half - .1) / 2); j <= Math.floor((Math.max(s.ay, s.by) + s.half + .1) / 2); j++) {
            const c = i * 100000 + j; if (!cells.has(c)) cells.set(c, []); cells.get(c).push(id); } },
      near: (x, y) => cells.get(Math.floor(x / 2) * 100000 + Math.floor(y / 2)) || []};
  }
  function segDist(s, x, y) { const dx = s.bx - s.ax, dy = s.by - s.ay, l2 = dx * dx + dy * dy,
    t = l2 ? Math.max(0, Math.min(1, ((x - s.ax) * dx + (y - s.ay) * dy) / l2)) : 0; return [hyp(x - s.ax - dx * t, y - s.ay - dy * t), t]; }
  function carriageways(v) {
    const r = v.roads, grid = segGrid(), corners = [];
    // City streets as the page draws them: every route (the rim road only its own stretch, the boulevard
    // carries the shared one), at the carriageway half width.
    v.routes.forEach((route, ri) => { const P = route.points, n = P.length, m = route.open ? n - 1 : n;
      for (let k = 0; k < m; k++) { const a = P[k], b = P[(k + 1) % n];
        grid.add({kind: 'route', route: ri, bridge: -1, ax: a.x, ay: -a.z, bx: b.x, by: -b.z, za: a.y, zb: b.y, half: route.width / 2}); } });
    for (const st of r.streets) for (let k = 0; k + 1 < st.points.length; k++) { const a = st.points[k], b = st.points[k + 1];
      grid.add({kind: 'link', route: -1, bridge: -1, ax: a[0], ay: a[1], bx: b[0], by: b[1], za: st.z, zb: st.z, half: st.width / 2}); }
    r.bridges.forEach((b, bi) => { let u = 0; for (let k = 0; k + 1 < b.points.length; k++) { const p = b.points[k], q = b.points[k + 1], l = hyp(q[0] - p[0], q[1] - p[1]);
      grid.add({kind: 'bridge', route: -1, bridge: bi, ax: p[0], ay: p[1], bx: q[0], by: q[1], za: p[2], zb: q[2], half: b.width / 2, u0: u, len: l}); u += l; } });
    for (const b of r.bridges) for (const e of b.ends) for (const f of e.fillets) corners.push({cx: f.cx, cy: f.cy, r: f.r, reach: f.r + .44, a0: f.a0, a1: f.a1, z: e.z});
    // on(x, y, h): whether (x, y) lies on a carriageway whose surface is within 0.02 of h; ON.bridge and ON.u
    // name the bridge (and the arc length along it) when the point is on a bridge carriageway.
    const ON = {ok: false, bridge: -1, u: 0, d: 0};
    function on(x, y, h) {
      ON.ok = false; ON.bridge = -1; ON.u = 0; let bestBridge = Infinity;
      for (const id of grid.near(x, y)) { const s = grid.segs[id], [d, t] = segDist(s, x, y);
        if (d > s.half + 1e-3 || Math.abs(s.za + (s.zb - s.za) * t - h) > .02) continue;
        ON.ok = true; if (s.bridge >= 0 && d < bestBridge) { bestBridge = d; ON.bridge = s.bridge; ON.u = s.u0 + t * s.len; } }
      if (!ON.ok) for (const c of corners) { const dx = x - c.cx, dy = y - c.cy, d = hyp(dx, dy);
        if (d < c.r - 1e-3 || d > c.reach || Math.abs(c.z - h) > .02) continue;
        const u = (((Math.atan2(dy, dx) / RAD - c.a0) % 360 + 540) % 360 - 180) / (c.a1 - c.a0); if (u >= -1e-3 && u <= 1 + 1e-3) { ON.ok = true; break; } }
      return ON;
    }
    return {grid, corners, on};
  }
"""

TRAFFIC_PROBE = r"""([seconds, tamper]) => new Promise(resolve => {
  const v = window.__vc, r = v.roads, cars = v.cars;
  if (!r || !cars.traffic || !cars.cycles) { resolve({missing: true}); return; }
  // Tier 3 for the whole probe (V4 fix), so every one of the twelve riders is bound by the crossing rule
  // and the full vehicle count drives: the governor keeps running but the counts read Tier 3.
  const tierDesc = Object.getOwnPropertyDescriptor(v.tier, 'current');
  Object.defineProperty(v.tier, 'current', {get: () => 3, configurable: true}); v.tier.apply();
  if (tamper) (0, eval)(tamper);
""" + CARRIAGEWAY_JS + r"""
  v.updateWeek(12);
  const C = carriageways(v), info = r.bridgeInfo, cyc = cars.cycles;
  const runs = new Map(), traversed = new Map(), perBridge = new Array(info.length).fill(0), lastLane = new Map(), overtakes = new Set(), shownTicks = new Array(cyc.items.length).fill(0);
  let ticks = 0, samples = 0, off = 0, cycleSamples = 0, cycleOff = 0, visibleMin = Infinity, visibleMax = 0;
  // C5.4 spacing, from 2 s on (a tier change reveals parked vehicles where they stood): bumper gaps between
  // neighbours in one lane (track and direction), and any two shown vehicles in world space heading the
  // same way whose bodies overlap along the leader's heading while less than 0.08 apart across it (merges,
  // diverges, crossings, taxis rejoining). Pulled-in taxis stand at the kerb and are left out.
  let lanePairs = 0, laneMin = Infinity, worldPairs = 0, worldMin = Infinity; const spacingExamples = [];
  const offExamples = [], started = performance.now();
  // A run is a stretch of samples inside one bridge's span (between its two fillet tangencies); it counts
  // as a traversal when it starts within 0.5 of one end, ends within 0.5 of the other and never turns back.
  function track(id, bridge, u) {
    let run = runs.get(id);
    if (run && run.bridge !== bridge) { finish(id, run); run = null; }
    if (bridge < 0) { if (run) finish(id, run); runs.delete(id); return; }
    if (!run) { runs.set(id, {bridge, u0: u, u1: u, sign: 0, back: false}); return; }
    const du = u - run.u1; if (Math.abs(du) > 1e-4) { const s = Math.sign(du); if (run.sign && s !== run.sign) run.back = true; run.sign = run.sign || s; }
    run.u1 = u;
  }
  function finish(id, run) {
    const I = info[run.bridge], a = I.bsA + .5, b = I.length - I.bsB - .5;
    if (!run.back && ((run.u0 <= a && run.u1 >= b) || (run.u0 >= b && run.u1 <= a))) {
      if (!traversed.has(id)) traversed.set(id, []); traversed.get(id).push(run.bridge); perBridge[run.bridge]++; }
  }
  function sample(id, a, o, isCycle) {
    const x = a[o + 12], y = -a[o + 14], h = a[o + 13] - .006, q = C.on(x, y, h);
    if (isCycle) cycleSamples++; else samples++;
    if (!q.ok) { if (isCycle) cycleOff++; else off++; if (offExamples.length < 12) offExamples.push({id, x: +x.toFixed(3), y: +y.toFixed(3), h: +h.toFixed(3)}); }
    let bridge = -1, u = 0;
    if (q.ok && q.bridge >= 0) { const I = info[q.bridge]; if (q.u >= I.bsA - .05 && q.u <= I.length - I.bsB + .05) { bridge = q.bridge; u = q.u; } }
    track(id, bridge, u);
  }
  function spacing(t) {
    const lanes = new Map(), shown = [];
    for (let k = 0; k < v.carState.length; k++) { const c = v.carState[k], a = c.mesh.instanceMatrix.array, o = c.slot * 16;
      if (a[o + 15] !== 1 || hyp(a[o], a[o + 1], a[o + 2]) < .5 || c.pull > .35 || c.tk < 0) continue;
      shown.push([c, a[o + 12], a[o + 13], a[o + 14], a[o + 8], a[o + 10]]);
      const key = c.tk * 2 + (c.td > 0 ? 0 : 1); if (!lanes.has(key)) lanes.set(key, []); lanes.get(key).push(c); }
    for (const list of lanes.values()) { list.sort((p, q) => p.q - q.q);
      for (let i = 0; i + 1 < list.length; i++) { const g = list[i + 1].q - list[i].q - list[i].halfLen - list[i + 1].halfLen; lanePairs++; laneMin = Math.min(laneMin, g);
        if (g < -.05 && spacingExamples.length < 8) spacingExamples.push({t, lane: true, gap: +g.toFixed(3), a: list[i].type, b: list[i + 1].type}); } }
    for (let i = 0; i < shown.length; i++) for (let j = i + 1; j < shown.length; j++) { const A = shown[i], B = shown[j], dx = B[1] - A[1], dz = B[3] - A[3];
      if (Math.abs(dx) > 1.2 || Math.abs(dz) > 1.2 || Math.abs(B[2] - A[2]) > .1 || A[4] * B[4] + A[5] * B[5] < 0) continue;
      const hl = hyp(A[4], A[5]) || 1, along = Math.abs((dx * A[4] + dz * A[5]) / hl), across = Math.abs((dx * A[5] - dz * A[4]) / hl);
      if (across >= .08) continue; const over = along - A[0].halfLen - B[0].halfLen; worldPairs++; worldMin = Math.min(worldMin, over);
      if (over < -.05 && spacingExamples.length < 8) spacingExamples.push({t, lane: false, over: +over.toFixed(3), a: A[0].type, b: B[0].type, tracks: [r.traffic.tracks[A[0].tk].kind, r.traffic.tracks[B[0].tk].kind]}); }
  }
  function tick() {
    ticks++;
    const now = (performance.now() - started) / 1000; if (now >= 2) spacing(+now.toFixed(1));
    for (let k = 0; k < v.carState.length; k++) { const c = v.carState[k], a = c.mesh.instanceMatrix.array, o = c.slot * 16;
      if (a[o + 15] === 1 && hyp(a[o], a[o + 1], a[o + 2]) > .5) sample(k, a, o, false); }
    const A = cyc.mesh.instanceMatrix.array; let shown = 0;
    for (let k = 0; k < cyc.items.length; k++) { const o = k * 16; if (A[o + 15] !== 1) continue; shown++; shownTicks[k]++; sample(1000 + k, A, o, true);
      // An overtake: the cycle was behind a vehicle in the same lane at the previous sample and is ahead now.
      const c = cyc.items[k], key = c.tk * 2 + (c.td > 0 ? 0 : 1), prev = lastLane.get(k), now = new Map();
      for (let j = 0; j < v.carState.length; j++) { const w = v.carState[j]; if (!w.on || w.tk * 2 + (w.td > 0 ? 0 : 1) !== key) continue;
        now.set(j, w.q - c.q); if (prev && prev.key === key && prev.rel.has(j) && prev.rel.get(j) > 0 && w.q - c.q < 0) overtakes.add(k + ':' + j); }
      lastLane.set(k, {key, rel: now}); }
    visibleMin = Math.min(visibleMin, shown); visibleMax = Math.max(visibleMax, shown);
    if (performance.now() - started >= seconds * 1000) {
      clearInterval(timer); for (const [id, run] of runs) finish(id, run);
      Object.defineProperty(v.tier, 'current', tierDesc); v.tier.apply();
      const carIds = [...traversed.keys()].filter(id => id < 1000), cycleIds = [...traversed.keys()].filter(id => id >= 1000);
      const trailColors = cyc.items.map((c, k) => { const col = cyc.trail.geometry.attributes.aColor; const n = cyc.trailSamples * 2; return [col.getX(k * n), col.getY(k * n), col.getZ(k * n)]; });
      resolve({seconds, ticks, rateHz: ticks / ((performance.now() - started) / 1000), samples, off, cycleSamples, cycleOff, offExamples,
        vehiclesTraversing: carIds.length, traversals: carIds.reduce((s, id) => s + traversed.get(id).length, 0), perBridge,
        bridgesUsed: perBridge.filter(n => n > 0).length, cyclesTraversing: cycleIds.length, cycleTraversals: cycleIds.reduce((s, id) => s + traversed.get(id).length, 0),
        overtakes: overtakes.size, visibleMin, visibleMax, alwaysShown: shownTicks.map((n, k) => n === ticks ? k : -1).filter(k => k >= 0),
        alwaysShownTraversing: shownTicks.filter((n, k) => n === ticks && traversed.has(1000 + k)).length, perRider: cyc.items.map((c, k) => (traversed.get(1000 + k) || []).length), tier: v.tier.current, cycleTarget: cyc.tier[v.tier.current],
        trailColors, districts: cyc.items.map(c => c.district),
        spacing: {lanePairs, laneMin: +laneMin.toFixed(3), worldPairs, worldMin: +worldMin.toFixed(3), examples: spacingExamples},
        // Each shown rider's trail as drawn: the length of its foot line, sample to sample.
        trailLength: cyc.trailLength, trailLengths: cyc.items.map((c, k) => { if (!c.on) return null; const P = cyc.trail.geometry.attributes.position.array, b = k * cyc.trailSamples * 6;
          let len = 0; for (let j = 0; j + 1 < cyc.trailSamples; j++) len += hyp(P[b + (j + 1) * 6] - P[b + j * 6], P[b + (j + 1) * 6 + 1] - P[b + j * 6 + 1], P[b + (j + 1) * 6 + 2] - P[b + j * 6 + 2]);
          return +len.toFixed(3); }),
        // Each rider's home colour as the page shows it on the district's chip (sRGB 0 to 255), and each trail's colour in sRGB.
        chipColors: cyc.items.map(c => { const el = document.querySelector('.chip[data-d="' + c.district + '"]'), m = el && el.style.getPropertyValue('--c').match(/[0-9.]+/g); return m ? m.slice(0, 3).map(Number) : null; }),
        trailSrgb: trailColors.map(c => c.map(x => 255 * (x <= .0031308 ? 12.92 * x : 1.055 * Math.pow(x, 1 / 2.4) - .055)))});
    }
  }
  const timer = setInterval(tick, 100);
})"""

CYCLE_TIERS_PROBE = r"""() => new Promise(resolve => {
  const v = window.__vc, cyc = v.cars.cycles, desc = Object.getOwnPropertyDescriptor(v.tier, 'current'), levels = [3, 2, 1], out = {};
  let k = 0;
  function next() {
    if (k === levels.length) { Object.defineProperty(v.tier, 'current', desc); resolve(out); return; }
    const level = levels[k++]; Object.defineProperty(v.tier, 'current', {get: () => level, configurable: true});
    let frames = 0;
    (function wait() { if (++frames < 20) { requestAnimationFrame(wait); return; }
      const A = cyc.mesh.instanceMatrix.array, P = cyc.trail.geometry.attributes.position.array, n = cyc.trailSamples * 2; let shown = 0, trails = 0;
      for (let i = 0; i < cyc.items.length; i++) { if (A[i * 16 + 15] === 1) shown++;
        // A drawn trail: its samples do not all sit on one point.
        const b = i * n * 3; let span = 0; for (let j = 0; j < n; j++) span = Math.max(span, Math.hypot(P[b + j * 3] - P[b], P[b + j * 3 + 2] - P[b + 2]));
        if (span > .3) trails++; }
      out[level] = {shown, trails, want: cyc.tier[level]}; next(); })();
  }
  next();
})"""


def verify_traffic(engine, url, tamper=None, seconds=60):
    """V4c (C5.4, C7.6): graph traffic on a fresh page at week 12, held at Tier 3 for the whole probe (V4
    fix: the counts read Tier 3 whatever the governor does), sampled at 10 Hz for 60 s from the rendered
    instance matrices. 'traffic crosses bridges': at least 10 distinct vehicles cross a bridge end to end (a
    run inside one span from within 0.5 of one fillet tangency to within 0.5 of the other, never turning
    back) and every sampled vehicle position lies on a carriageway (a ring, avenue or rim road stretch, a
    rim link, a bridge or a paved fillet corner, inside its carriageway half width and within 0.02 of its
    surface height), with at least 90 % of the 600 ticks taken. 'NPC light cycles cruise the bridge
    network': 12, 7 and 4 riders with drawn trails at Tiers 3, 2 and 1 (Tier 2 is 60 % of the count,
    C13.1), all twelve riders shown for the whole 60 s and every one of them crosses a bridge end to end,
    riders overtake traffic, every rider sample lies on a carriageway, the twelve
    riders come from twelve districts and each trail is its home district's chip colour (within 0.6 of 255
    in sRGB; Downtown and the Gate share a colour). 'vehicles keep their spacing in lanes and at merges'
    (V4 fix, C5.4): from 2 s on, no two neighbours in one lane overlap bumper to bumper by more than 0.05
    and no two shown vehicles heading the same way overlap by more than 0.05 along the leader's heading
    while less than 0.08 apart across it (merges, diverges, taxis rejoining), over at least 20,000 lane
    pairs. 'NPC light-cycle trails keep their length' (V4 fix, C7.6): at the end, each of the twelve riders'
    trails as drawn (its foot line, sample to sample) is within 0.3 under and 0.01 over the published
    trailLength (5.46), whatever the frame rate (the samples no longer stretch on slow frames). tamper is
    JavaScript run first (the positive controls, renders/snap/wip/v4c/controls.py and
    renders/snap/wip/v4fix/controls.py)."""
    engine.page.set_viewport_size({"width": 1440, "height": 900})
    engine.goto(url)
    engine.ready()
    engine.wait(1)
    got = engine.evaluate(TRAFFIC_PROBE, [seconds, tamper])
    if got.get("missing"):
        return got, {name: False for name in TRAFFIC_CHECKS}
    got["cycleTiers"] = engine.evaluate(CYCLE_TIERS_PROBE)
    tiers = got["cycleTiers"]
    checks = {
        TRAFFIC_CHECKS[0]: (got["ticks"] >= 0.9 * seconds * 10 and got["samples"] > 0 and got["off"] == 0 and
                            got["vehiclesTraversing"] >= 10),
        TRAFFIC_CHECKS[1]: (all(tiers[str(level)]["shown"] == want and tiers[str(level)]["trails"] == want
                                for level, want in ((3, 12), (2, 7), (1, 4))) and
                            got["cycleSamples"] > 0 and got["cycleOff"] == 0 and
                            len(got["alwaysShown"]) == 12 and got["alwaysShownTraversing"] == 12 and got["overtakes"] > 0 and
                            len(set(got["districts"])) == 12 and all(got["chipColors"]) and
                            all(abs(a - b) <= 0.6 for c, h in zip(got["trailSrgb"], got["chipColors"]) for a, b in zip(c, h))),
        TRAFFIC_CHECKS[2]: (got["spacing"]["lanePairs"] >= 20000 and got["spacing"]["laneMin"] >= -0.05 and
                            got["spacing"]["worldMin"] >= -0.05),
        TRAFFIC_CHECKS[3]: (len([x for x in got["trailLengths"] if x is not None]) == 12 and
                            all(got["trailLength"] - 0.3 <= x <= got["trailLength"] + 0.01 for x in got["trailLengths"] if x is not None)),
    }
    return got, checks


TRAFFIC_CHECKS = ("traffic crosses bridges", "NPC light cycles cruise the bridge network",
                  "vehicles keep their spacing in lanes and at merges", "NPC light-cycle trails keep their length")


REFLOW_PROBE = r"""([tamper]) => {
  const v = window.__vc, r = v.roads, V = v.venues;
  if (!r || !V.meshes.stageDecks) return {missing: true};
  if (tamper) (0, eval)(tamper);
""" + CARRIAGEWAY_JS + r"""
  v.updateWeek(12);
  const decks = V.meshes.stageDecks.instanceMatrix.array, lake = r.lake, pier = lake && lake.pier, isl = lake && lake.island;
  // The lake's signed shore distance (720 samples, refined), as qa_design.py measures it.
  const ca = lake ? Math.cos(lake.angle) : 1, sa = lake ? Math.sin(lake.angle) : 0;
  function lakeGap(x, y) { if (!lake) return Infinity; const dx = x - lake.cx, dy = y - lake.cy, u = dx * ca + dy * sa, w = -dx * sa + dy * ca;
    const f = t => (lake.rx * Math.cos(t) - u) ** 2 + (lake.ry * Math.sin(t) - w) ** 2; let i0 = 0, b0 = Infinity;
    for (let i = 0; i < 720; i++) { const q = f(i * 2 * Math.PI / 720); if (q < b0) { b0 = q; i0 = i; } }
    let lo = (i0 - 1) * 2 * Math.PI / 720, hi = (i0 + 1) * 2 * Math.PI / 720;
    for (let k = 0; k < 30; k++) { const m1 = lo + (hi - lo) / 3, m2 = hi - (hi - lo) / 3; if (f(m1) < f(m2)) hi = m2; else lo = m1; }
    const d = Math.sqrt(f((lo + hi) / 2)); return (u / lake.rx) ** 2 + (w / lake.ry) ** 2 < 1 ? -d : d; }
  const S = (ax, ay, bx, by, half) => ({ax, ay, bx, by, half});
  const bridgeSegs = [], filletArcs = [], rimSegs = [];
  r.bridges.forEach(b => { for (let k = 0; k + 1 < b.points.length; k++) bridgeSegs.push(S(b.points[k][0], b.points[k][1], b.points[k + 1][0], b.points[k + 1][1], .57)); });
  for (const b of r.bridges) for (const e of b.ends) for (const f of e.fillets) { const n = Math.max(2, Math.ceil(Math.abs(f.a1 - f.a0) * RAD * f.r / .05));
    for (let j = 0; j <= n; j++) { const a = (f.a0 + (f.a1 - f.a0) * j / n) * RAD; filletArcs.push([f.cx + f.r * Math.cos(a), f.cy + f.r * Math.sin(a)]); } }
  v.routes.forEach(route => { if (route.kind !== 'rim') return; const P = route.points;
    for (let k = 0; k + 1 < P.length; k++) rimSegs.push(S(P[k].x, -P[k].z, P[k + 1].x, -P[k + 1].z, route.width / 2 + .13)); });
  for (const st of r.streets) for (let k = 0; k + 1 < st.points.length; k++) rimSegs.push(S(st.points[k][0], st.points[k][1], st.points[k + 1][0], st.points[k + 1][1], st.width / 2 + .13));
  const pierSeg = pier ? S(pier.x0, pier.y0, pier.x1, pier.y1, .25) : null;
  const minOver = (segs, x, y, r0) => { let m = Infinity; for (const s of segs) m = Math.min(m, segDist(s, x, y)[0] - s.half - r0); return m; };
  const arcGap = (x, y, r0) => { let m = Infinity; for (const p of filletArcs) m = Math.min(m, hyp(p[0] - x, p[1] - y) - .13 - r0); return m; };
  // Stage decks as rendered: the deck instance's centre and radius. Clearances as qa_design.py requires:
  // 0.5 from every bridge deck edge (0.57), fillet curb (0.13 round the fillet arc), the lake and the
  // pier (0.25) except the Reef's own island stage; from the rim road and links 0.5, the Archive's own 0.
  const stageRows = [];
  v.stages.forEach((s, i) => { const o = i * 16, x = decks[o + 12], y = -decks[o + 14], rad = hyp(decks[o], decks[o + 1], decks[o + 2]);
    const reef = s.district === 'reef', gaps = {bridge: minOver(bridgeSegs, x, y, rad), fillet: arcGap(x, y, rad),
      lake: reef ? Infinity : lakeGap(x, y) - rad, pier: reef || !pierSeg ? Infinity : minOver([pierSeg], x, y, rad),
      rim: minOver(rimSegs, x, y, rad) - (s.district === 'episodic' ? 0 : .5) + .5};
    const worst = Object.entries(gaps).reduce((a, b) => b[1] < a[1] ? b : a);
    stageRows.push({district: s.district, x: +x.toFixed(3), y: +y.toFixed(3), r: +rad.toFixed(3), worst: worst[0], clearance: +worst[1].toFixed(3), pass: worst[1] >= .5 - 1e-6}); });
  // Terraces (three depths by three positions across each terrace, as qa_design.py samples them, from the
  // rendered venue frame) and every drawn furniture item except the road's manholes, against the bridge
  // landings (deck edge 0.57, fillet curb 0.13), the pier (0.25), the rim road and links and the lake.
  const FR = {table: .06, chair: .035, crate: .05, cart: .12, bin: .04, kiosk: .14, busstop: .16};
  function hit(x, y, r0) {
    if (minOver(bridgeSegs, x, y, r0) < 0) return 'bridge';
    if (arcGap(x, y, r0) < 0) return 'fillet';
    if (pierSeg && minOver([pierSeg], x, y, r0) < 0) return 'pier';
    if (minOver(rimSegs, x, y, r0) < 0) return 'rim road or link';
    if (lake && lakeGap(x, y) < r0 && !(isl && hyp(x - isl.x, y - isl.y) <= isl.r - r0)) return 'lake';
    return null;
  }
  const terraceHits = [], furnitureHits = []; let terraceSamples = 0, furnitureDrawn = 0;
  for (const q of V.items) { if (!q.terrace) continue;
    for (const a of [.1, q.terrace * .5, q.terrace]) for (const bb of [-.35, 0, .35]) { terraceSamples++;
      const x = q.face.x + q.normal.x * a + q.right.x * bb * q.length, y = -(q.face.z + q.normal.z * a + q.right.z * bb * q.length), why = hit(x, y, 0);
      if (why) terraceHits.push({venue: q.index, why}); } }
  for (const f of V.furniture) { if (f.kind === 'manhole') continue; const A = f.mesh.instanceMatrix.array, o = f.slot * 16;
    if (hyp(A[o], A[o + 1], A[o + 2]) < 1e-3) continue; furnitureDrawn++;
    const why = hit(A[o + 12], -A[o + 14], FR[f.kind] ?? .1); if (why) furnitureHits.push({item: f.index, kind: f.kind, why}); }

  // The rest of C4.1 (V4 fix), on the same rendered positions. Every stage deck, terrace sample and drawn
  // furniture item keeps off every street's carriageway and both walking lanes: route.width / 2 + 0.11 from
  // the centreline (the lane 0.04 outside the kerb plus a walker's 0.07), the rim road's own stretch
  // included. Free-standing things (stage decks, carts, kiosks, bins, bus stops) clear every building
  // footprint (the 0.57 overhang, every node) by 0.2; a terrace sample stands on no footprint but its host's;
  // a terrace set (a venue's tables, chairs and crates) is the venue's, so only its terrace is checked there.
  // Nothing overlaps anything else: stage and stage, stage and item (a cart on its own stage deck excepted),
  // item and item (one venue's terrace set excepted), and no terrace sample lies on a stage deck.
  const laneGrid = segGrid();
  v.routes.forEach((route, ri) => { const P = route.points, n = P.length, m = route.open ? n - 1 : n;
    for (let k = 0; k < m; k++) { const a = P[k], b = P[(k + 1) % n]; laneGrid.add({ax: a.x, ay: -a.z, bx: b.x, by: -b.z, half: route.width / 2 + .11, route: ri}); } });
  const laneGap = (x, y, r0) => { let g = Infinity, who = -1; const seen = new Set();
    for (let i = Math.floor((x - r0 - .1) / 2); i <= Math.floor((x + r0 + .1) / 2); i++) for (let j = Math.floor((y - r0 - .1) / 2); j <= Math.floor((y + r0 + .1) / 2); j++)
      for (const id of laneGrid.near(i * 2 + 1, j * 2 + 1)) { if (seen.has(id)) continue; seen.add(id); const sg = laneGrid.segs[id], d = segDist(sg, x, y)[0] - sg.half - r0; if (d < g) { g = d; who = sg.route; } }
    return [g, who]; };
  const boxes = new Map();
  v.nodes.forEach(n => { const x0 = n.x - n.w * .57, x1 = n.x + n.w * .57, y0 = n.y - n.d * .57, y1 = n.y + n.d * .57;
    for (let i = Math.floor((x0 - 3) / 2); i <= Math.floor((x1 + 3) / 2); i++) for (let j = Math.floor((y0 - 3) / 2); j <= Math.floor((y1 + 3) / 2); j++) {
      const c = i * 100000 + j; if (!boxes.has(c)) boxes.set(c, []); boxes.get(c).push({n, x0, x1, y0, y1}); } });
  // The page carries building positions to 0.01 (design.py measures the unrounded ones), so a footprint
  // clearance read here may be up to 0.01 short of the one design.py guaranteed; qa_design.py checks the exact 0.2.
  const FOOT_TOL = .01;
  const footGap = (x, y, skip) => { let g = Infinity; for (const b of boxes.get(Math.floor(x / 2) * 100000 + Math.floor(y / 2)) || []) { if (b.n === skip) continue;
    g = Math.min(g, hyp(Math.max(0, b.x0 - x, x - b.x1), Math.max(0, b.y0 - y, y - b.y1))); } return g; };
  const laneHits = [], footHits = [], pairHits = [];
  const note = (list, row) => { list.push(row); };
  const stagesAt = v.stages.map((s, i) => { const o = i * 16; return {i, index: s.index, district: s.district, kind: s.kind, x: decks[o + 12], y: -decks[o + 14], r: hyp(decks[o], decks[o + 1], decks[o + 2])}; });
  for (const st of stagesAt) { const [lg, who] = laneGap(st.x, st.y, st.r); if (lg < -1e-3) note(laneHits, {stage: st.district, route: who, gap: +lg.toFixed(3)});
    const fg = footGap(st.x, st.y, null) - st.r; if (fg < .2 - FOOT_TOL) note(footHits, {stage: st.district, gap: +fg.toFixed(3)}); }
  for (let i = 0; i < stagesAt.length; i++) for (let j = i + 1; j < stagesAt.length; j++) { const a = stagesAt[i], b = stagesAt[j];
    if (hyp(a.x - b.x, a.y - b.y) < a.r + b.r - 1e-3) note(pairHits, {stages: [a.district, b.district]}); }
  let reflowSamples = 0;
  for (const q of V.items) { if (!q.terrace) continue;
    for (const a of [.1, q.terrace * .5, q.terrace]) for (const bb of [-.35, 0, .35]) { reflowSamples++;
      const x = q.face.x + q.normal.x * a + q.right.x * bb * q.length, y = -(q.face.z + q.normal.z * a + q.right.z * bb * q.length);
      const [lg, who] = laneGap(x, y, 0); if (lg < -1e-3) note(laneHits, {venue: q.index, route: who, gap: +lg.toFixed(3)});
      if (footGap(x, y, q.host) <= 0) note(footHits, {venue: q.index, terrace: true});
      for (const st of stagesAt) if (hyp(x - st.x, y - st.y) < st.r - 1e-3) note(pairHits, {venue: q.index, stage: st.district}); } }
  const drawn = [];
  for (const f of V.furniture) { if (f.kind === 'manhole') continue; const A = f.mesh.instanceMatrix.array, o = f.slot * 16;
    if (hyp(A[o], A[o + 1], A[o + 2]) < 1e-3) continue; drawn.push({f, x: A[o + 12], y: -A[o + 14], r: FR[f.kind] ?? .1}); }
  for (const d of drawn) { const f = d.f, [lg, who] = laneGap(d.x, d.y, d.r);
    if (lg < -1e-3) note(laneHits, {item: f.index, kind: f.kind, route: who, gap: +lg.toFixed(3)});
    if (!(f.venue >= 0)) { const fg = footGap(d.x, d.y, null) - d.r; if (fg < .2 - FOOT_TOL) note(footHits, {item: f.index, kind: f.kind, gap: +fg.toFixed(3)}); }
    for (const st of stagesAt) if (f.stage !== st.index && hyp(d.x - st.x, d.y - st.y) < st.r + d.r - 1e-3) note(pairHits, {item: f.index, kind: f.kind, stage: st.district}); }
  for (let i = 0; i < drawn.length; i++) for (let j = i + 1; j < drawn.length; j++) { const a = drawn[i], b = drawn[j];
    if (Math.abs(a.x - b.x) > .5 || Math.abs(a.y - b.y) > .5) continue;
    if (a.f.venue >= 0 && a.f.venue === b.f.venue) continue;
    if (hyp(a.x - b.x, a.y - b.y) < a.r + b.r - 1e-3) note(pairHits, {items: [a.f.index, b.f.index], kinds: [a.f.kind, b.f.kind]}); }
  return {stages: stageRows, stagesClear: stageRows.filter(s => s.pass).length, terraceSamples, terraceHits: terraceHits.slice(0, 10), terraceHitCount: terraceHits.length,
    furnitureDrawn, furnitureHits: furnitureHits.slice(0, 10), furnitureHitCount: furnitureHits.length,
    c41: {stages: stagesAt.length, terraceSamples: reflowSamples, items: drawn.length, laneHitCount: laneHits.length, laneHits: laneHits.slice(0, 10),
      footHitCount: footHits.length, footHits: footHits.slice(0, 10), pairHitCount: pairHits.length, pairHits: pairHits.slice(0, 10)}};
}"""


def verify_reflow(engine, tamper=None):
    """V4c (C4.1 as rendered): 'stages and venues re-flowed with zero overlaps' on the page at week 12. Every
    stage deck instance (its centre and radius) keeps qa_design.py's 0.5 from the bridge deck edges, the
    fillet curbs, the lake and the pier (the Reef's island stage excepted) and the rim road and links (the
    Archive's own stage 0); no venue terrace sample and no drawn furniture item (manholes are road decals)
    stands on a bridge landing, fillet, the pier, the rim road, a link or the lake. And (V4 fix) the rest of
    C4.1 on the same rendered positions: every stage deck, terrace sample and drawn furniture item stays off
    every street's carriageway and both walking lanes (route.width / 2 + 0.11 from the centreline, the rim
    road's own stretch included); stage decks and free-standing furniture clear every building footprint
    (0.57 overhang) by 0.2, a terrace sample stands on no footprint but its host's (terrace sets belong to
    their venue); and nothing overlaps anything else (a cart on its own stage and one venue's terrace set
    excepted). tamper is JavaScript run first (the positive controls, renders/snap/wip/v4fix/controls.py:
    a kiosk moved onto the Downtown ring, the Downtown stage deck pushed 1.2 into its ring road, a bin
    stacked on a cart, a stage deck set against a building)."""
    got = engine.evaluate(REFLOW_PROBE, [tamper])
    if got.get("missing"):
        return got, {REFLOW_CHECK: False}
    c = got["c41"]
    return got, {REFLOW_CHECK: len(got["stages"]) == 12 and got["stagesClear"] == 12 and got["terraceSamples"] > 0 and
                 got["terraceHitCount"] == 0 and got["furnitureDrawn"] > 400 and got["furnitureHitCount"] == 0 and
                 c["stages"] == 12 and c["terraceSamples"] > 400 and c["items"] > 400 and
                 c["laneHitCount"] == 0 and c["footHitCount"] == 0 and c["pairHitCount"] == 0}


REFLOW_CHECK = "stages and venues re-flowed with zero overlaps"


DECKS_PROBE = r"""([tamper]) => {
  const v = window.__vc, r = v.roads;
  if (!r || !r.bridgeRoutes) return {missing: true};
  if (tamper) (0, eval)(tamper);
  v.updateWeek(12);
  const V3 = v.camera.position.constructor, eye = new V3(), look = new V3();
  const failures = {deck: [], ride: [], walk: [], chase: []}; let samples = 0, turnSamples = 0;
  // The ring checks of qa_city.py on every bridge route (the deck centreline from tee to tee): the road
  // point 0.64 up and the ride pose's eye clear of every footprint by 0.14 with a clear sight line, both
  // walking lanes 0.18 up clear by 0.07; and a chase camera 0.75 behind and 0.32 above the deck looking at
  // the point 2.2 ahead at the same height, its eye clear by 0.14 with a clear sight line (C7.3).
  const chase = (route, d, name, bucket) => {
    v.sampleRoute(route, d - .75, eye); eye.y += .32; v.sampleRoute(route, d + 2.2, look); look.y += .32;
    if (v.pointBlocked(eye, .14, false) || !v.clearSight(eye, look)) bucket.push({route: name, d: +d.toFixed(2)}); };
  r.bridgeRoutes.forEach((route, i) => { const clearance = r.bridges[i].clearance;
    for (let d = 0; d < route.length; d += .10) { samples++;
      const raw = v.sampleRoute(route, d); raw.y += .64;
      if (v.pointBlocked(raw, .14, false)) failures.deck.push({route: route.name, d: +d.toFixed(2)});
      const p = v.poseOnRoute(route, d);
      if (v.pointBlocked(p.eye, .14, false) || !v.clearSight(p.eye, p.look)) failures.ride.push({route: route.name, d: +d.toFixed(2)});
      for (const side of [-1, 1]) { const foot = v.sampleRoute(route, d, undefined, Math.min(route.width / 2 + .04, clearance - .12) * side); foot.y += .18;
        if (v.pointBlocked(foot, .07, false)) failures.walk.push({route: route.name, d: +d.toFixed(2), side}); }
      chase(route, d, route.name, failures.chase); } });
  // The turn arcs through the junction fillets, which traffic and the tour drive: the road point and the
  // chase camera, every 0.1.
  const turnFail = [];
  r.graph.turns.forEach((t, k) => { const pts = t.points.map(q => new V3(q[0], q[2], -q[1])), lengths = [0];
    for (let i = 1; i < pts.length; i++) lengths.push(lengths[i - 1] + pts[i - 1].distanceTo(pts[i]));
    const route = {points: pts, lengths, length: lengths[lengths.length - 1], open: true};
    for (let d = 0; d < route.length; d += .10) { turnSamples++; const raw = v.sampleRoute(route, d); raw.y += .64;
      if (v.pointBlocked(raw, .14, false)) turnFail.push({turn: k, d: +d.toFixed(2), why: 'deck'});
      const before = turnFail.length; chase(route, d, 'turn ' + k, turnFail); if (turnFail.length > before) turnFail[turnFail.length - 1].why = 'chase'; } });
  return {bridges: r.bridgeRoutes.length, samples, turnSamples,
    deckFailures: failures.deck.length, rideFailures: failures.ride.length, walkFailures: failures.walk.length, chaseFailures: failures.chase.length,
    turnFailures: turnFail.length, examples: {deck: failures.deck.slice(0, 5), ride: failures.ride.slice(0, 5), walk: failures.walk.slice(0, 5),
      chase: failures.chase.slice(0, 5), turns: turnFail.slice(0, 5)}};
}"""


def verify_deck_clearance(engine, tamper=None):
    """V4c (C6.7 on the rendered page): every bridge's deck surface, both walking lanes, the ride pose and a
    chase camera path, sampled every 0.1 unit with qa_city.py's thresholds against the page's own footprint
    test (pointBlocked, which includes canopies and roof equipment), and the 56 fillet turn arcs' road
    points and chase camera. tamper is JavaScript run first (the positive controls)."""
    got = engine.evaluate(DECKS_PROBE, [tamper])
    if got.get("missing"):
        return got, {DECKS_CHECK: False}
    return got, {DECKS_CHECK: got["bridges"] == 14 and got["samples"] > 1000 and got["turnSamples"] > 500 and
                 got["deckFailures"] == 0 and got["rideFailures"] == 0 and got["walkFailures"] == 0 and
                 got["chaseFailures"] == 0 and got["turnFailures"] == 0}


DECKS_CHECK = "rendered bridge decks, walking lanes and chase camera clear every footprint"


GOVERNOR_WORK = """() => {
  const v = window.__vc, t = v.tier, log = [];
  // Look away from the overview first: no tier change below may move the camera.
  const eye = [v.controls.target.x + 7.5, v.controls.target.y + 3.25, v.controls.target.z - 5.5];
  v.camera.position.set(...eye);
  let elapsed = 0;
  function feed(ms, work, count, stop) {
    for (let i = 0; i < count; i++) {
      const before = t.current; t.update(ms, work); elapsed += ms;
      if (t.current !== before) { log.push({at: elapsed, before, after: t.current}); if (stop) return elapsed; }
    }
    return null;
  }
  feed(20, 20, 300);
  const low = t.current, heavyStart = elapsed;
  feed(16.7, 14, 1800);
  const heavyHeld = t.current === low;
  const fastStart = elapsed, climbAt = feed(16.7, 6, 1800, true), climbed = t.current;
  feed(20, 20, 300);
  const dropped = t.current, need = t.climbNeedMs ?? null;
  const fast2 = elapsed, climbAt2 = feed(16.7, 6, 3000, true), climbed2 = t.current;
  // A page that still misses frames at Tier 1 (33 ms intervals, 6 ms of work: a busy GPU or machine)
  // must not climb, however long its work stays short.
  feed(20, 20, 300);
  const missStart = t.current, missClimb = feed(33.3, 6, 1800, true), missHeld = t.current === missStart;
  const cam = v.camera.position, moved = Math.hypot(cam.x - eye[0], cam.y - eye[1], cam.z - eye[2]);
  return {low, heavyHeld, climbed, climbAfterMs: climbAt === null ? null : climbAt - fastStart,
    dropped, need, climbed2, climbAfter2Ms: climbAt2 === null ? null : climbAt2 - fast2,
    missStart, missHeld, missClimbAt: missClimb, changes: log.length, cameraMoved: moved, log};
}"""


GOVERNOR_PARTIAL = """() => {
  const v = window.__vc, t = v.tier, log = [];
  let elapsed = 0;
  function feed(count, work, pattern) {
    for (let i = 0; i < count; i++) {
      const ms = pattern && i % 16 === 15 ? 33.3 : 16.7, before = t.current; t.update(ms, work); elapsed += ms;
      if (t.current !== before) { log.push({at: +elapsed.toFixed(1), before, after: t.current}); return elapsed; }
    }
    return null;
  }
  // Down to Tier 2 with slow frames, then 60 s at 60 Hz that misses one vsync in 16 (a 17.8 ms mean, under
  // the 19 ms drop line, but a 33 ms p95) with 6 ms of work per frame: no climb. Then the same page at a
  // clean 60 Hz climbs 10 to 13.5 s later, so the hold came from the misses.
  for (let i = 0; i < 400 && t.current > 2; i++) { t.update(20, 20); elapsed += 20; }
  const start = t.current, partialStart = elapsed, partialAt = feed(3600, 6, 1), afterPartial = t.current, slowShare = t.slowShare ?? null;
  const cleanStart = elapsed, cleanAt = feed(1200, 6, 0), afterClean = t.current;
  return {start, afterPartial, partialClimbAt: partialAt === null ? null : partialAt - partialStart, slowShare,
    afterClean, cleanClimbAfterMs: cleanAt === null ? null : cleanAt - cleanStart, log};
}"""


def verify_governor_work(engine, url):
    """C13.2 as fixed in V4a, driven with known frame spans on a fresh page: at a 60 Hz vsync cap
    (16.7 ms intervals) 30 s of 14 ms work never climbs, 6 ms work climbs one tier 10 to 13.5 s after
    the work mean goes under 12 ms, a drop within 10 s of a climb doubles the next climb's wait, 60 s
    of short work at 33 ms intervals (a page still missing frames) never climbs, and none of the tier
    changes moves the camera. On a second fresh page (V4 fix): 60 s that misses one frame in 16 (mean
    17.8 ms, under the 19 ms drop line, p95 33 ms, over the C13.3 22 ms budget) never climbs from Tier 2,
    and the same page at a clean 60 Hz then climbs 10 to 13.5 s later (positive control: the page with
    the slow-share rule removed, renders/snap/wip/v4fix/controls.py, climbs during the misses)."""
    engine.page.set_viewport_size({"width": 1440, "height": 900})
    engine.goto(url)
    engine.ready()
    got = engine.evaluate(GOVERNOR_WORK)
    engine.goto(url)
    engine.ready()
    got["partial"] = partial = engine.evaluate(GOVERNOR_PARTIAL)
    checks = {
        "governor climbs on frame work time at a 60 Hz vsync cap":
            got["low"] == 1 and got["heavyHeld"] and got["climbed"] == 2 and
            got["climbAfterMs"] is not None and 10000 <= got["climbAfterMs"] <= 13500,
        "governor backs off after a climb that drops within 10 s":
            got["dropped"] == 1 and got["need"] == 20000 and got["climbed2"] == 2 and
            got["climbAfter2Ms"] is not None and got["climbAfter2Ms"] >= 20000,
        "governor never climbs while frames miss the display rate":
            got["missStart"] == 1 and got["missHeld"] and got["missClimbAt"] is None,
        "a governor tier change never moves the camera":
            got["changes"] >= 4 and got["cameraMoved"] < 1e-9,
        GOVERNOR_PARTIAL_CHECK:
            partial["start"] == 2 and partial["afterPartial"] == 2 and partial["partialClimbAt"] is None and
            partial["afterClean"] == 3 and partial["cleanClimbAfterMs"] is not None and
            10000 <= partial["cleanClimbAfterMs"] <= 13500,
    }
    return got, checks


GOVERNOR_PARTIAL_CHECK = "governor never climbs while one frame in 16 misses the display rate"


def self_test():
    times = list(range(0, 2000, 25))
    wave = [.05 if (stamp // 125) % 2 == 0 else .55 for stamp in times]
    safe = [.05 if (stamp // 200) % 2 == 0 else .55 for stamp in times]
    small_frames = [[value if pixel == 0 else .05 for pixel in range(64 * 36)] for value in wave]
    _, small_traces = area_traces(small_frames)
    large_frames = [[value] * (64 * 36) for value in wave]
    _, large_traces = area_traces(large_frames)
    checks = {"steady": not flash_pairs(times, [.25] * len(times)),
              "4 Hz detected": rolling_max(flash_pairs(times, wave)) == 4,
              "2.5 Hz within limit": rolling_max(flash_pairs(times, safe)) <= 3,
              "subthreshold": not flash_pairs(times, [.10 if (t // 125) % 2 == 0 else .18 for t in times]),
              "gradual opposing excursions": len(flash_pairs(list(range(9)), [.0,.05,.10,.15,.20,.15,.10,.05,.0])) == 1,
              "small highlights excluded by area": all(not flash_pairs(times, row) for row in small_traces),
              "large area flash detected": all(rolling_max(flash_pairs(times, row)) == 4 for row in large_traces),
              "77 specified windows": len(large_traces) == 77,
              "V0 scenes": [s["id"] for s in SCENES if s["fromPhase"] <= 0] == ["S1", "S3", "S5"],
              "V2 adds stage only": [s["id"] for s in SCENES if s["fromPhase"] <= 2] == ["S1", "S2", "S3", "S5"],
              "V3 scene set unchanged": [s["id"] for s in SCENES if s["fromPhase"] <= 3] == ["S1", "S2", "S3", "S5"],
              "V4 scene set unchanged": [s["id"] for s in SCENES if s["fromPhase"] <= 4] == ["S1", "S2", "S3", "S5"],
              "Run B implementation order": [PHASE_ORDER[p] for p in ("v6", "v7", "v5", "v8")] == [5, 6, 7, 8],
              "V6 scene set unchanged": [s["id"] for s in SCENES if s["fromPhase"] <= 5] == ["S1", "S2", "S3", "S5"],
              "V7 adds shore scene": [s["id"] for s in SCENES if s["fromPhase"] <= 6] == ["S1", "S2", "S3", "S4", "S5"]}
    print(json.dumps(checks, indent=2))
    return int(not all(checks.values()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8765/viewer/")
    parser.add_argument("--prefix", default="world")
    parser.add_argument("--phase", choices=tuple(PHASE_ORDER), default="v0")
    parser.add_argument("--baseline", action="store_true", help="Measure legacy page; absent V0 capabilities fail")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.prefix or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in args.prefix):
        parser.error("--prefix must contain only letters, digits, hyphens or underscores")
    phase = PHASE_ORDER[args.phase]
    output = ROOT / "renders" / "qa"
    output.mkdir(parents=True, exist_ok=True)
    path = lambda suffix: output / (args.prefix + "-" + suffix)
    report = {"url": args.url, "phase": args.phase, "baseline": args.baseline,
              "scope": "C13.3 phase-scoped scenes and C12.3 area flash windows",
              "sceneSet": [s["id"] for s in SCENES if s["fromPhase"] <= phase] + ["Heap"],
              "performance": [], "errors": [], "checks": {}}
    checks = report["checks"]
    try:
        with Engine() as eng:
            eng.goto(args.url)
            eng.ready()
            capabilities = report["capabilities"] = eng.evaluate("""() => {
              const v=window.__vc;return {beat:Boolean(v.beat),lights:Boolean(v.lights),
                tier:Boolean(v.tier),crowd:Boolean(v.crowd),venues:Boolean(v.venues),
                roads:Boolean(v.roads),explore:Boolean(v.explore),nature:Boolean(v.nature),
                initialTier:v.tier?.initial??null,compilation:v.compilation??null};}""")
            checks["V0 foundation APIs exist"] = all(capabilities[key] for key in ("beat", "lights", "tier", "crowd", "venues"))
            checks["desktop starts Tier 3"] = capabilities["initialTier"] == 3
            if not args.baseline:
                report["compilation"] = inspect_compilation(eng)
                compiled = report["compilation"]
                checks["all materials compiled at load"] = (compiled["verified"] and
                    bool(compiled["declared"]) and compiled["declared"]["complete"] and
                    not compiled["uncompiled"])
            eng.evaluate("() => window.__vc.updateWeek(12)")
            eng.click("#sound")
            wait_audio(eng)
            for scene in SCENES:
                if scene["fromPhase"] > phase:
                    report["performance"].append({**scene, "available": False, "required": False,
                                                   "measured": False, "status": "not present in this phase"})
                    continue
                item = measure_scene(eng, scene, path, args.baseline, phase)
                report["performance"].append(item)
                checks[scene["id"] + " numeric budgets"] = item["numericBudgetPass"]
                checks[scene["id"] + " settled tier at least 2"] = item["settledTierPass"]
                if scene["id"] == "S3" and phase >= 5:
                    checks["S3 bike boosted on the Memory Causeway"] = item["boostPass"]
                if scene["id"] == "S5" and phase >= 7:
                    checks["S5 Grand Tour crosses a room drop"] = item["tourTransitionPass"]
            report["heapSession"] = measure_heap(eng, path, phase)
            checks["five-minute session heap growth at most 40 MB"] = report["heapSession"]["passed"]
            report["flash"] = []
            if args.baseline:
                report["flash"].append(measure_flash(eng, "overview", "legacy", path, baseline=True))
                checks["legacy overview observed area flash trace"] = report["flash"][0]["measuredTracePass"]
                checks["all existing modes and Lights settings flash gate"] = False
            else:
                for mode in ("overview", "focus", "ride") + (("explore",) if phase >= 5 else ()):
                    for setting in ("Full", "Soft", "Calm"):
                        item = measure_flash(eng, mode, setting, path)
                        report["flash"].append(item)
                        checks["area flash " + mode + " " + setting] = item["measuredTracePass"]
                checks["all existing modes and Lights settings flash gate"] = len(report["flash"]) == (12 if phase >= 5 else 9) and all(item["measuredTracePass"] for item in report["flash"])
                report["foundations"], foundation_checks = measure_foundations(eng, path)
                checks.update(foundation_checks)
                if phase >= 1:
                    report["raveInventory"], rave_checks = verify_rave_inventory(eng)
                    checks.update(rave_checks)
                    report["cityShader"] = verify_city_shader(eng)
                    checks["cityMat light terms retain baseline uniform dependencies"] = report["cityShader"]["passed"]
                    report["transitions"] = []
                    report["transitions"].append(measure_transition(eng, path, True))
                    checks["window light invariant sound on"] = report["transitions"][0]["buffersPass"]
                    report["transitions"].append(measure_transition(eng, path, False))
                    checks["four-step transition within one frame"] = all(
                        row["timingPass"] and row["renderPass"] for row in report["transitions"])
                    checks["window light invariant sound off"] = report["transitions"][1]["buffersPass"]
                    report["raveDynamics"], dynamics_checks = measure_rave_dynamics(eng, path)
                    checks.update(dynamics_checks)
                if phase >= 2:
                    eng.evaluate("() => window.__vc.updateWeek(12)")
                    report["crowd"], crowd_checks = verify_crowd(eng, path, phase)
                    checks.update(crowd_checks)
                if phase >= 3:
                    eng.evaluate("() => window.__vc.updateWeek(12)")
                    report["society"], society_checks = verify_society(eng, path)
                    checks.update(society_checks)
                if phase >= 4:
                    report["design"], design_checks = verify_design_v4()
                    checks.update(design_checks)
                    eng.evaluate("() => window.__vc.updateWeek(12)")
                    report["roads"], roads_checks = verify_roads(eng)
                    checks.update(roads_checks)
                if phase >= 6:
                    # V7 (C9, C10): data gates (lake, trees, shore structures), the landing overview frames the lake,
                    # the lake surface for explore.js, the drawn shore off the ring, shared sky, kick rings, census, S4
                    # flash, flocks, water, boats, behaviours, dog chase at boost, reduced motion. The S4 flash runs
                    # before the gates that reload the page and turns the sound on itself, so its trace is the page
                    # with sound.
                    import qa_nature
                    design = json.loads((ROOT / "data" / "city-design.json").read_text(encoding="utf-8"))
                    report["nature"] = qa_nature.data_gates(design)
                    lake = design["lake"][0]
                    for name, fn in (("overview", lambda e: qa_nature.verify_overview(e, design)),
                                     ("surface", lambda e: qa_nature.verify_surface(e, design)),
                                     ("shoreMesh", lambda e: qa_nature.verify_shore_mesh(e, design)),
                                     ("materials", qa_nature.verify_materials), ("kickRings", qa_nature.verify_kick_rings),
                                     ("census", qa_nature.verify_census),
                                     ("s4", lambda e: qa_nature.verify_s4(e, path)),
                                     ("s4Flash", lambda e: qa_nature.verify_s4_flash(e, path)),
                                     ("flocks", qa_nature.verify_flocks),
                                     ("water", lambda e: qa_nature.verify_no_water_walkers(e, lake)),
                                     ("boats", lambda e: qa_nature.verify_boats(e, lake)),
                                     ("behaviours", qa_nature.verify_behaviours),
                                     ("dogChase", qa_nature.verify_dog_chase),
                                     ("reduced", qa_nature.verify_reduced)):
                        rep, chk, ctl = fn(eng)
                        report["nature"][name] = {"report": rep, "checks": chk, "controls": ctl}
                    for part in report["nature"].values():
                        checks.update(part["checks"])
                        checks.update({"positive control: " + k: v for k, v in part["controls"].items()})
                report["lightPolicy"], policy_checks = verify_light_policy(eng)
                checks.update(policy_checks)
                report["governor"] = verify_governor(eng, args.url)
                governor = report["governor"]
                checks["governor drops after sustained 19 ms and never below Tier 1"] = (
                    governor["initial"] == 3 and governor["slow"] == 1 and governor["floor"] == 1 and
                    all(row["sincePreviousChangeMs"] >= 3000
                        for row in governor["changes"] if row["after"] < row["before"]))
                checks["governor waits ten fast seconds before climbing"] = (
                    governor["beforeTenSeconds"] == 1 and governor["recovered"] >= 2 and
                    all(row["fastSpanMs"] >= 10000 for row in governor["changes"]
                        if row["after"] > row["before"]))
                if phase >= 4:
                    report["governorWork"], work_checks = verify_governor_work(eng, args.url)
                    checks.update(work_checks)
                    report["bridges"], bridge_checks = verify_bridges(eng, args.url)
                    checks.update(bridge_checks)
                    report["traffic"], traffic_checks = verify_traffic(eng, args.url)
                    checks.update(traffic_checks)
                    report["reflow"], reflow_checks = verify_reflow(eng)
                    checks.update(reflow_checks)
                    report["deckClearance"], deck_checks = verify_deck_clearance(eng)
                    checks.update(deck_checks)
                if phase >= 1:
                    tier_rows = [governor["initialRave"]] + [row["rave"] for row in governor["changes"]]
                    checks["rave instance counts apply all three governor tiers"] = (
                        all(row is not None for row in tier_rows) and
                        {row["tier"] for row in tier_rows} == {1, 2, 3} and
                        all(row["lasers"] == {3: 14, 2: 10, 1: 6}[row["tier"]] and
                            row["drones"] == {3: 256, 2: 128, 1: 0}[row["tier"]] for row in tier_rows))
                report["reducedMotion"] = verify_reduced_motion(eng, args.url)
                reduced = report["reducedMotion"]
                checks["reduced motion forces Calm without flashes blackout or strobes"] = (
                    reduced["setting"] == "Calm" and reduced["selectDisabled"] and
                    not reduced["flash"] and reduced["cutFactor"] == 1 and not reduced["strobes"] and
                    reduced["colorDuration"] >= 4 * 60 / 140)
                if phase >= 1:
                    report["raveReduced"] = verify_rave_reduced(eng, path)
                    checks["reduced rave geometry freezes without cut or flash"] = report["raveReduced"]["passed"]
                    checks["reduced room color changes take at least one bar"] = report["raveReduced"]["colorPassed"]
                report["phone"] = verify_phone(eng, args.url, path)
                phone = report["phone"]
                checks["375 px phone starts Tier 1 with pixel ratio 1"] = (
                    phone["width"] == 375 and not phone["overflow"] and phone["initialTier"] == 1 and
                    phone["currentTier"] == 1 and phone["pixelRatio"] == 1)
                if phase >= 5:
                    report["explore"], explore_checks = verify_explore(eng, args.url)
                    checks.update(explore_checks)
                if phase >= 7:
                    from qa_tour import verify_tour
                    report["tour"] = verify_tour(eng, args.url, args.prefix, output)
                    checks.update(report["tour"]["checks"])
                    checks.update(report["tour"]["positiveControls"])
            report["errors"] = list(eng.errors)
    except Exception as error:
        report["errors"].append(str(error))
    for name in ("scheduled kick released within one frame", "silent clock drift within 1 ms over 60 s",
                 "Sound phase discontinuity below a sixteenth", "Sound error absorbed within one bar",
                 "all materials compiled at load"):
        checks.setdefault(name, False)
    if phase >= 1:
        for name in ("four-step transition within one frame", "window light invariant sound on", "window light invariant sound off"):
            checks.setdefault(name, False)
    if phase >= 2:
        for name in ("people census per tier", "dancers follow density and brightness", "no person inside a footprint", "bounce minima within a sixteenth"):
            checks.setdefault(name, False)
    if phase >= 3:
        for name in ("venue census 93 plus or minus 10 percent", "venue hosts valid", "venue state follows host", "vehicle census per type"):
            checks.setdefault(name, False)
    if phase >= 4:
        for name in ("roads.js rebuilds the tour and turn arcs from the page data", "surfaceAtRoad finds the tour's road height",
                     "tour samples its entries' districts", "rim road drawn as its own open stretch",
                     "governor climbs on frame work time at a 60 Hz vsync cap",
                     "governor backs off after a climb that drops within 10 s",
                     "governor never climbs while frames miss the display rate",
                     "a governor tier change never moves the camera", GOVERNOR_PARTIAL_CHECK):
            checks.setdefault(name, False)
        for name in BRIDGE_CHECKS:
            checks.setdefault(name, False)
        for name in TRAFFIC_CHECKS + (REFLOW_CHECK, DECKS_CHECK):
            checks.setdefault(name, False)
        if not any(name.startswith("design: ") for name in checks):
            checks["design: qa_design gates ran"] = False
    if phase >= 5:
        checks.setdefault("S3 bike boosted on the Memory Causeway", False)
        for name in V6_CHECK_NAMES:
            checks.setdefault(name, False)
    if phase >= 6:
        checks.setdefault("V7 nature gates ran", "nature" in report)
    if phase >= 7:
        checks.setdefault("S5 Grand Tour crosses a room drop", False)
        for name in ("tour: every planned boundary crossed within one beat of its drop",
                     "tour: cut beat stays on every bridge deck longer than a beat",
                     "tour: at least eight bars of groove before every next transition",
                     "tour: all rooms and road surfaces remain valid",
                     "tour: sound remains on for the whole run", "tour: browser errors",
                     "tour: disabling speed control misses a drop by more than one beat"):
            checks.setdefault(name, False)
    page = ROOT / "dist" / "index.html"
    report["publicBytes"] = page.stat().st_size if page.exists() else None
    checks["public page at most 900 KB"] = report["publicBytes"] is not None and report["publicBytes"] <= 900_000
    checks["page and console errors"] = not report["errors"]
    report["failedChecks"] = [name for name, passed in checks.items() if not passed]
    report["passed"] = not report["failedChecks"]
    rendered = json.dumps(report, indent=2)
    path("world-report.json").write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return int(not report["passed"])


if __name__ == "__main__":
    raise SystemExit(main())
