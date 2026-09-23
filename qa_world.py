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
        const d=b.diagnostics,ctx=v.audio.ctx,stamp=ctx?.getOutputTimestamp?.();
        const at=stamp?.performanceTime>0?
          stamp.contextTime+(d.lastFrameMs-stamp.performanceTime)/1000:
          (ctx?.currentTime??0)-(Number(ctx?.outputLatency)||Number(ctx?.baseLatency)||0);
        const expected=q.schedule[name];
        q.events.push({name,frame:d.frame,frameMs:d.lastFrameMs,frameGapMs:d.frameGapMs,
          expected,actual:q.source==='audio'?at:b.now().seconds,
          source:tr.source,serial:tr.serial});
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
              "V3 scene set unchanged": [s["id"] for s in SCENES if s["fromPhase"] <= 3] == ["S1", "S2", "S3", "S5"]}
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
