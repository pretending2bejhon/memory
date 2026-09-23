# Viewer

The viewer is a full-screen night city built from the anonymous vault export. Taller buildings have setbacks, rooftop plant, facade ribs, window grids and illuminated storefronts. The Archive uses warm lantern light, Downtown uses violet, and the campuses use cool cyan and blue. Rain, pavement light pools, pedestrians and traffic give the street view movement.

## Controls

| Control | Behavior |
|---|---|
| Drag / scroll / right-drag | Orbit, zoom, pan |
| District chips | Focus and emphasize one district |
| Ride along / R | Enter a street-level ride in the selected district; defaults to Lantern avenue |
| Leave ride / Esc | Restore the previous overview position, lens and orbit settings |
| Timeline / Play | Scrub or play the 13 weekly building states |
| View | Traffic, people, rain, knowledge links, labels, glow, orbit and stars |
| Lights in View | Full, Soft or Calm; reduced motion forces Calm |
| Sound / M | Turn the room music on or off; the Sound chip sits beside View |
| Click a building | Inspect its anonymous type and state |

The ride uses a 62-degree lens and continuous arc-length travel around a closed boulevard. The camera stays on the route; its look-ahead shortens around obstructed turns. Knowledge links are an optional overlay, hidden by default. Traffic travels on streets, independently of those links. Streets and citizens are ambient scenery; the timeline still controls note buildings and their decay.

Reduced-motion preferences freeze ambient traffic, walking, rain, cranes, beacons and blinking lights. A ride moves only when explicitly started and uses a slower speed. The interface simplifies during a ride to a route label and a Leave ride button.

## Sound

Sound starts off. Click Sound to create and resume the audio context; `M` activates the same control. The preference is stored locally under `vc-sound`. A remembered on preference stays pending after a reload until a deliberate Sound gesture, so loading the page never starts audio by itself. Reduced-motion preferences do not disable sound.

Each district has a room: The Compass, The Archive, The Library, The Works, The Yards, Downtown, The Hills, Prasma Campus, Signal Row, The Dome, The Reef and The Gate. Isolating a district or riding through it selects its room. Overview, leaving a ride and clearing the isolated district select The Skyline. The Skyline uses Downtown's loop with a 1.2 kHz low-pass, reverb send 0.45 and gain 0.5. Room changes follow the owner's own DJ transitions, measured from his REEF SESSIONS 002 set: the switch starts on the next bar, the old room's kick and bass leave and a low-pass closes on it, the new room's hats and percussion fade in over one bar, a noise riser builds, the last beat before the drop cuts to silence, and the new kick and bass slam in at full on the next eight-bar phrase line (a bridge of four to eleven bars). Choosing another room mid-bridge takes over the bridge; going back to the old room brings its kick and bass straight back on the bar. A ride adds a gentle stereo pan that follows its camera heading.

The music is written in [Strudel](https://strudel.cc/), the JavaScript port of TidalCycles. Each room is one file in `viewer/rooms/<room>.strudel`, plain Strudel code that pastes into strudel.cc and back. One Strudel cycle is one bar. `viewer/city-audio.js` keeps its own 140 BPM transport, a 25 ms scheduler timer and 120 ms lookahead on a sixteenth grid: each step it queries every layer's pattern for events in that sixteenth and hands them to Strudel's sound engine (superdough) at their exact audio-clock time. Swing, velocity, pitch and per-sound effects live in the room code. Audio scheduling never runs from the render frame loop.

Each labelled line in a room file is a layer (`kick:`, `hatC:`, `pad:`), and each layer plays on its own Strudel orbit. `kick` and `bass` (plus the sub drone `pad` in The Compass and The Gate) are the room's low layers: transitions mute and slam exactly those. The engine routes every orbit into that layer's gain inside the room bus instead of the speakers, so transitions, the timeline mix and the kick sidechain act on real drum-machine samples and synths. A dotted-eighth delay and synthetic 2.4-second reverb feed the compressed and soft-clipped master. Kick hits duck pad, stab and bass by 6 dB with a 90 ms release. Strudel (`@strudel/web` 1.3.0 from jsdelivr), the tidal-drum-machines samples (strudel.b-cdn.net) and the TidalCycles Dirt-Samples (GitHub) load on the first Sound gesture, never before it; every sample a room uses is fetched and decoded before its first bar needs it.

Rooms use a 32-bar arrangement: establish for 16 bars, withhold the named layer for 4, signal the return for 2, then restore the groove for 10. The Yards uses a shorter 16-bar cycle. Signal Row repeats a four-bar musical loop inside its 32-bar arrangement. The music of every room is in its `.strudel` file; its root, arrangement cycle, withheld layer and bus effects are declared in the room table in `viewer/city-audio.js`. With sound on, `cityAudio.code(id)` returns a room's code and `cityAudio.setCode(id, code)` recompiles and swaps it live.

## Sound follows the timeline

Every `updateWeek(t)` uses the same node states already calculated for the buildings to compute two values independently for each district:

- Density is the number of existing buildings divided by that district's total buildings.
- Brightness is the number of existing buildings whose light is above 0.5 divided by the number of existing buildings.

The engine unmutes layers in a fixed order as density crosses these thresholds. A layer is available only if the room defines it.

| Layer | Minimum density |
|---|---|
| Kick | Always |
| Closed hat | 0.15 |
| Percussion | 0.30 |
| Open hat | 0.45 |
| Stab | 0.60 |
| Clap | 0.75 |
| Pad | 0.90 |

The room's timeline low-pass target is `600 + brightness * 11400` Hz, and its reverb-send target is `0.15 + (1 - brightness) * 0.4`. Parameter changes use `setTargetAtTime` with 250 ms smoothing. A brighter district opens the filter and becomes less distant; a faded district grows duller and more reverberant. The week Play control drives these changes through the same update path as manual scrubbing.

## Sources and build

- `design.py`: deterministic building dimensions/forms and clearance-checked routes shared with Blender.
- `viewer/template.html`: interface, materials, geometry, timeline and interaction.
- `viewer/city-life.js`: streets, signs, wet pavement and atmosphere.
- `viewer/crowd.js`: instanced citizens.
- `viewer/society.js`: instanced traffic and society.
- `viewer/beat.js`: the shared drop function, audible visual clock and preallocated hit-ring reader.
- `viewer/rave-light.js`: procedural sky, lasers, searchlights, drone glyphs, fireworks, grid floor and mounted screens, plus the common light limiter, Lights setting and adaptive quality governor.
- `viewer/ride.js`: ride camera, sightline checks and saved overview state.
- `viewer/city-audio.js`: audio-clock scheduler, Strudel loading and compilation, orbit routing, room buses, transitions and Sound preference.
- `viewer/rooms/*.strudel`: the twelve rooms as Strudel code.
- `viewer/build.py`: regenerates `data/city-design.json`, then inlines data and JavaScript. Its default private build writes `viewer/index.html` and `viewer/artifact.html`; `--public` writes the masked page and publication assets to `dist/`.

Run `python viewer/build.py` after editing for private local inspection, or `python viewer/build.py --public` to prepare publication. Do not hand-edit `viewer/index.html`, `viewer/artifact.html`, or any file in `dist/`. The public build replaces subdistrict metadata with per-district block labels and displays city names, including The Gate, without folder-key tooltips. Its English interface includes the page title, the owner's introduction and home link, and social preview metadata.

The builder replaces `__CITY_AUDIO__` in the template with `city-audio.js`, just as it inlines street life and the ride camera, then replaces `__CITY_ROOMS__` with the room files as a JSON map.

The viewer uses three.js 0.170 from jsDelivr and fonts from Google Fonts; it needs network access to those resources. Sound additionally loads Strudel and its samples from the sources listed above, only after a deliberate gesture. No new external sources are added for visual scenery.

## Verification

`qa_city.py` uses a project-local browser harness directly, without reading the vault or relying on a vault-owned browser wrapper. Start `python -m http.server 8765 --bind 127.0.0.1`, then run `py -V:Astral/CPython3.11.15 qa_city.py --prefix local`. The browser harness requires this Python 3.11 runtime. Screenshots and machine-readable results go to `renders/qa/`. Run the same harness against `/dist/` with `--url`; it must report 1,246 nodes and zero page errors, with desktop and 375 px screenshots.

The checks sample every route at 0.1-unit intervals for raw camera clearance, final camera clearance, look-ahead occlusion, and both walking lanes. They also exercise entering/exiting rides, district focus, timeline changes, and a fresh mobile page. `window.__vc` exposes the scene state and route helpers for inspection.

`python qa_audio.py` reuses the city QA browser harness. Its gates verify no running audio context after five seconds without a click, a running context after Sound is clicked, analyser RMS above -40 dBFS, the transition grammar (next-bar start, drop on an eight-bar phrase after a four to eleven bar bridge, one-bar equal-power fade-in of the new room's upper layers, kick and bass muted through the bridge and at full after the drop, a cut beat at least 20 dB below the groove, the old room silent after the drop, no clipping), frame rate above 55 fps with sound on, and zero console errors. Run `python qa_city.py` alongside it to retain the collision and page-error gates. Each run writes its measured output to `renders/qa/<prefix>-audio-report.json`.

The twelve-room gate selects each room, waits for the transition to reach its drop, then samples its analyser for four seconds. Every room must be non-silent, and every pair must differ by at least 8 percent in spectral centroid or 2 dB in RMS. The Archive timeline check scrubs weeks 0 through 12 and verifies that cutoff follows measured brightness monotonically. This compares cutoff with brightness, rather than requiring chronological weeks to get steadily brighter: dates, status and decay can lower brightness as time advances.

[LOG.md](../LOG.md) contains twelve listening prompts with empty score cells. The owner scores the rooms after deployment; collecting those subjective scores is not part of the local automated gate.

`window.__vc.audio` exposes `ctx`, `setRoom`, `room`, `analyser` and `rooms` for inspection. The context is absent before the first Sound gesture; selecting a room through the API does not bypass that gesture requirement.

## Visual foundations

The visual beat bus follows the audible audio clock when Sound is on and free-runs at 140 BPM when it is off. Audio scheduling remains independent of rendering. Source changes absorb the phase error over one bar. Windows and street lamps never subscribe to this bus.

Lights offers Full, Soft and Calm in View, defaults to Full and remembers the choice under `vc-lights`. Full uses each effect's specified amplitude. Soft halves reactive amplitudes, dims a transition cut to 50 percent and disables strobes. Calm uses 20 percent amplitude, disables flashes, blackout and strobes, and takes at least one bar for colour changes. Overview and district focus apply an additional 0.6 factor; a ride applies 1.0. Reduced motion forces Calm and freezes ambient movement. The shared limiter caps beat pulses below the general-flash threshold and limits large flashes to three in any second.

Desktop starts at Tier 3 and phones at Tier 1. A three-second mean above 19 ms drops one tier. Ten seconds below 12 ms restores one tier, with phones remaining at Tier 1. All materials, including hidden scenery and postprocessing, compile before the loading screen leaves.

`qa_world.py --phase v0` measures the scenes available in that phase: week-12 overview, the existing Lantern avenue ride, and an overview focus transition. A five-minute scripted session visits every district, plays the timeline and rides for 60 seconds to measure heap growth. From V2 it also measures the Downtown stage. Future bridge, bike and lake scenes are explicitly deferred to their Run B phases. Each scene reports the governor's settled tier; desktop may settle at Tier 2 but not Tier 1. Flash checks use means over 21 by 12 cells, moved in four-cell steps over a 64 by 36 relative-luminance trace, across each existing mode and Lights setting.

The world budgets apply from V0: at least 55 fps, p95 frame time at most 22 ms, no frame above 100 ms after load, at most 320 draw calls and 1.5 million triangles, at most 40 MB heap growth in the scripted session, and at most 900,000 bytes for the public page. Run the browser suites with the Python 3.11 launcher above; the complete audio command includes `qa_audio.py --phase p2`, and the world command includes the current `--phase v<n>`. All existing city gates and all 36 audio checks stay binding.

## Rave light

The sky uses the active room's colour, an accent 150 degrees around the hue wheel and the night base. Kicks lift the horizon, hats sparkle the stars, and pad and stab energy light the aurora. A low cloud deck carries the drop flash. These effects use the shared limiter and the selected Lights amplitude.

At Tier 3, eight lasers rise from the Compass spire and six from the three tallest Downtown towers. Fan, sweep, scissor, tunnel and converge-up patterns change on bars and phrases. Four broad searchlights sweep from the Works and Yards over two bars. The 256-point swarm above the Compass morphs into a procedural district glyph at the arrangement-cycle boundary. Tier 2 uses ten lasers and 128 drones; Tier 1 uses six lasers and no drones.

With Sound on, Tier 3 fireworks launch three to six shells over the active district on its arrangement's first return bar: bar 22 of a 32-bar cycle, or bar 10 of the Yards' 16-bar cycle. The Gate uses cycle bar 0. Lower tiers reduce the particles and shells. This happens at most once per cycle and is distinct from a room-transition drop; the silent clock has no arrangement.

The four light-transition steps use the engine's times. At bridge start, sky and lasers desaturate over two bars while beams narrow and rise. The riser starts at the later of bridge start and four bars before the drop; beams converge and the horizon rises on beats. On a four-bar bridge these two starts coincide. The final beat dims reactive light to 15 percent in Full, 50 percent in Soft, and leaves it undimmed in Calm. The drop changes to the new room colour, fans the lasers, flashes the clouds and launches a grid ripple. With Sound off, the same grammar runs at half intensity on the silent clock. Stages, crowds and storefronts join this grammar in the phases that introduce them.

The floor shader draws unit grid lines with stronger lines every eight units. Kick ripples travel at 20 units per second and fade over 1.5 seconds. Before stages arrive, their source is the active district centre; overview uses the Compass. Framed screens mount on the six tallest Downtown crowns and roofs and on Signal Row billboards. Spectrum bars, waveform rings, kaleidoscopes and curated scrolling lines stay on separate panels, clear of the note-window signal.

`qa_world.py --phase v1` adds transition timing within one rendered frame and byte comparisons of note-building instance buffers across complete transitions with Sound on and off. The shader check preserves the existing sources of every window-mask and light term. City, audio, flash, memory and performance gates remain required.
