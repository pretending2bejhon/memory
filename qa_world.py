"""Phase-scoped world QA using the repository browser harness.

C13.3 scenes are measured only when the phase supplies them. C12.3 flashes use
mean luminance in sliding 21 by 12 windows, never a union of pixel events.
"""

import argparse
import json
import math
import time
from pathlib import Path

from qa_browser import Engine

ROOT = Path(__file__).resolve().parent
SCENES = (
    {"id": "S1", "scene": "overview", "fromPhase": 0, "name": "Overview at week 12"},
    {"id": "S2", "scene": "downtown_stage", "fromPhase": 2,
     "name": "Downtown stage, full crowd, fixed street camera"},
    {"id": "S3", "scene": "archive_ride", "fromPhase": 0,
     "name": "Existing Ride along on Lantern avenue, week 12"},
    {"id": "S4", "scene": "reef_shore", "fromPhase": 7, "name": "Reef shore, Run B V7"},
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
  const source=window.__vc.renderer.domElement,start=performance.now();
  const trace=window.__qaWorldFlash={done:false,times:[],frames:[],start};
  const linear=v=>v<=.04045?v/12.92:Math.pow((v+.055)/1.055,2.4);let next=0;
  function tick(now){
    const elapsed=now-start;
    if(elapsed>=next&&elapsed<30000){
      ctx.drawImage(source,0,0,64,36);
      const pixels=ctx.getImageData(0,0,64,36).data,values=new Array(64*36);
      for(let i=0;i<values.length;i++)values[i]=Math.round(1000000*(
        .2126*linear(pixels[i*4]/255)+.7152*linear(pixels[i*4+1]/255)+
        .0722*linear(pixels[i*4+2]/255)))/1000000;
      trace.times.push(elapsed);trace.frames.push(values);next+=1000/30;
    }
    if(elapsed>=30000){trace.done=true;return;}
    requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
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
    engine.evaluate("""() => {const v=window.__vc;if(v.state.ride>=0)v.stopRide();
      document.getElementById('reset-cam').click();v.setIsolate(null);}""")
    if mode == "focus":
        engine.evaluate("() => {window.__vc.setIsolate('working');window.__vc.flyTo('working');}")
    elif mode == "ride":
        engine.evaluate("() => {window.__vc.setIsolate('episodic');window.__vc.startRide();}")


def wait_audio(engine):
    wait_probe(engine, """() => {const a=window.__vc.audio;return a.enabled&&
      a.ctx?.state==='running'&&a.ready&&a.diagnostics.scheduledVoices>0;}""", 60)


def settle_room(engine):
    wait_probe(engine, """() => {const a=window.__vc.audio;return !a.transition||
      a.ctx.currentTime>=a.transition.end;}""", 35)


def measure_scene(engine, scene, path, baseline):
    key = scene["id"]
    print("Measuring " + key + ": " + scene["name"] + ", 60 seconds, sound on", flush=True)
    engine.evaluate("() => window.__vc.updateWeek(12)")
    set_mode(engine, "ride" if key == "S3" else "overview")
    if key == "S5":
        engine.evaluate("() => window.__vc.setIsolate('working')")
    if key == "S2":
        engine.evaluate("""() => {
          const v=window.__vc, s=v.venues?.stages?.find(s=>s.district==='working');
          if(!s)throw new Error('Downtown stage unavailable');
          const x=s.x,z=s.z??-s.y,up=s.up??0;
          v.camera.position.set(x,up+.5,z+3);v.controls.target.set(x,up+.5,z);
          v.controls.update();
        }""")
    settle_room(engine)
    engine.wait(12)
    engine.screenshot(path("world-" + key.lower() + ".png"))
    engine.evaluate(FRAME_TRACE)
    if key == "S5":
        engine.wait(2)
        engine.evaluate("() => window.__vc.setIsolate('procedural')")
    wait_probe(engine, "() => window.__qaWorldFrames.done", 75)
    trace = engine.evaluate("() => window.__qaWorldFrames")
    path("world-" + key.lower() + "-frames.json").write_text(json.dumps(trace), encoding="utf-8")
    metrics = summarize_frames(trace)
    tiers = metrics["tiers"]
    tier_pass = bool(tiers) and all(tier is not None and tier >= 2 for tier in tiers)
    return {**scene, "available": True, "required": True, "measured": True,
            "tier": "legacy desktop, no tier API" if baseline else metrics["settledTier"],
            "metrics": metrics, "numericBudgetPass": perf_pass(metrics),
            "settledTierPass": tier_pass, "passed": perf_pass(metrics) and tier_pass}


def measure_heap(engine, path):
    print("Measuring Heap: 5-minute focus, timeline and 60-second ride session", flush=True)
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
              "actions": rows, "passed": end_heap - start_heap <= 40_000_000}
    path("world-heap.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    session.detach()
    return result


def measure_flash(engine, mode, setting, path, baseline=False):
    print("Measuring flash: " + mode + ", " + setting + ", 30 seconds", flush=True)
    set_mode(engine, mode)
    if not baseline:
        engine.evaluate("s => window.__vc.lights.setSetting(s)", setting)
    settle_room(engine)
    engine.wait(2)
    engine.evaluate(LUMINANCE_TRACE)
    engine.evaluate("""() => {const a=window.__vc.audio;
      a.setRoom(a.room==='procedural'?'working':'procedural');}""")
    wait_probe(engine, "() => window.__qaWorldFlash.done", 45)
    trace = engine.evaluate("() => window.__qaWorldFlash")
    path("world-luminance-" + mode + "-" + setting.lower() + ".json").write_text(
        json.dumps(trace, separators=(",", ":")), encoding="utf-8")
    return {"mode": mode, "setting": setting, **flash_summary(trace)}


def measure_foundations(engine, path):
    """Observe the live clock; no test clock or injected scheduled hit is used."""
    print("Measuring V0 clock, kick release and Sound switching", flush=True)
    engine.evaluate("""() => {
      const v=window.__vc,b=v.beat;
      const q=window.__qaBeat={kicks:[],switches:[],frames:[],offs:[],active:true};
      q.offs.push(b.on('hit',h=>{
        if(h.source==='audio'&&h.layer==='kick'){
          const d=b.diagnostics,ctx=v.audio.ctx,stamp=ctx.getOutputTimestamp?.();
          const audibleNow=stamp?.performanceTime>0?
            stamp.contextTime+(d.lastFrameMs-stamp.performanceTime)/1000:
            ctx.currentTime-(Number(ctx.outputLatency)||Number(ctx.baseLatency)||0);
          q.kicks.push({time:h.time,audibleAt:h.audibleAt,
            measuredAudibleAt:d.lastFrameMs+(h.time-audibleNow)*1000,
            releasedAt:d.lastFrameMs,lateMs:h.lateMs,
            frame:h.frame,frameGapMs:d.frameGapMs});
        }
      }));
      let previous=null;
      function tick(){
        if(!q.active)return;
        const s=b.now(),d=b.diagnostics,ctx=v.audio.ctx,stamp=ctx?.getOutputTimestamp?.();
        const audibleNow=stamp?.performanceTime>0?
          stamp.contextTime+(d.lastFrameMs-stamp.performanceTime)/1000:
          (ctx?.currentTime??0)-(Number(ctx?.outputLatency)||Number(ctx?.baseLatency)||0);
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
      function feed(count,ms){for(let i=0;i<count;i++){
        const before=t.current,settledBefore=t.settledForMs;t.update(ms);
        fastSpan=t.meanMs<12?fastSpan+ms:0;
        if(t.current!==before){rows.push({elapsed:elapsed+ms,before,after:t.current,
          mean:t.meanMs,sincePreviousChangeMs:settledBefore+ms,fastSpanMs:fastSpan});fastSpan=0;}
        elapsed+=ms;}}
      let elapsed=0,fastSpan=0;feed(300,20);const slow=t.current;feed(150,20);const floor=t.current;
      const recoveryStart=elapsed;feed(999,10);const beforeTenSeconds=t.current;
      feed(350,10);const recovered=t.current;
      return {initial,initialSettledMs,slow,floor,beforeTenSeconds,recovered,recoveryStart,changes:rows};
    }""")


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
              "V2 adds stage only": [s["id"] for s in SCENES if s["fromPhase"] <= 2] == ["S1", "S2", "S3", "S5"]}
    print(json.dumps(checks, indent=2))
    return int(not all(checks.values()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8765/viewer/")
    parser.add_argument("--prefix", default="world")
    parser.add_argument("--phase", choices=("v0", "v1", "v2", "v3"), default="v0")
    parser.add_argument("--baseline", action="store_true", help="Measure legacy page; absent V0 capabilities fail")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.prefix or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in args.prefix):
        parser.error("--prefix must contain only letters, digits, hyphens or underscores")
    phase = int(args.phase[1])
    output = ROOT / "renders" / "qa"
    output.mkdir(parents=True, exist_ok=True)
    path = lambda suffix: output / (args.prefix + "-" + suffix)
    report = {"url": args.url, "phase": args.phase, "baseline": args.baseline,
              "scope": "C13.3 phase-scoped scenes and C12.3 area flash windows",
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
                item = measure_scene(eng, scene, path, args.baseline)
                report["performance"].append(item)
                checks[scene["id"] + " numeric budgets"] = item["numericBudgetPass"]
                checks[scene["id"] + " settled tier at least 2"] = item["settledTierPass"]
            report["heapSession"] = measure_heap(eng, path)
            checks["five-minute session heap growth at most 40 MB"] = report["heapSession"]["passed"]
            report["flash"] = []
            if args.baseline:
                report["flash"].append(measure_flash(eng, "overview", "legacy", path, baseline=True))
                checks["legacy overview observed area flash trace"] = report["flash"][0]["measuredTracePass"]
                checks["all existing modes and Lights settings flash gate"] = False
            else:
                for mode in ("overview", "focus", "ride"):
                    for setting in ("Full", "Soft", "Calm"):
                        item = measure_flash(eng, mode, setting, path)
                        report["flash"].append(item)
                        checks["area flash " + mode + " " + setting] = item["measuredTracePass"]
                checks["all existing modes and Lights settings flash gate"] = len(report["flash"]) == 9 and all(item["measuredTracePass"] for item in report["flash"])
                report["foundations"], foundation_checks = measure_foundations(eng, path)
                checks.update(foundation_checks)
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
                report["reducedMotion"] = verify_reduced_motion(eng, args.url)
                reduced = report["reducedMotion"]
                checks["reduced motion forces Calm without flashes blackout or strobes"] = (
                    reduced["setting"] == "Calm" and reduced["selectDisabled"] and
                    not reduced["flash"] and reduced["cutFactor"] == 1 and not reduced["strobes"] and
                    reduced["colorDuration"] >= 4 * 60 / 140)
                report["phone"] = verify_phone(eng, args.url, path)
                phone = report["phone"]
                checks["375 px phone starts Tier 1 with pixel ratio 1"] = (
                    phone["width"] == 375 and not phone["overflow"] and phone["initialTier"] == 1 and
                    phone["currentTier"] == 1 and phone["pixelRatio"] == 1)
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
