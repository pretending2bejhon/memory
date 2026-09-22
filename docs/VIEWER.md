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
| Sound / M | Turn procedural sound on or off; the Sound chip sits beside View |
| Click a building | Inspect its anonymous type and state |

The ride uses a 62-degree lens and continuous arc-length travel around a closed boulevard. The camera stays on the route; its look-ahead shortens around obstructed turns. Knowledge links are an optional overlay, hidden by default. Traffic travels on streets, independently of those links. Streets and citizens are ambient scenery; the timeline still controls note buildings and their decay.

Reduced-motion preferences freeze ambient traffic, walking, rain, cranes, beacons and blinking lights. A ride moves only when explicitly started and uses a slower speed. The interface simplifies during a ride to a route label and a Leave ride button.

## Sound

Sound starts off. Click Sound to create and resume the audio context; `M` activates the same control. The preference is stored locally under `vc-sound`. A remembered on preference stays pending after a reload until a deliberate Sound gesture, so loading the page never starts audio by itself. Reduced-motion preferences do not disable sound.

Each district has a room: The Compass, The Archive, The Library, The Works, The Yards, Downtown, The Hills, Prasma Campus, Signal Row, The Dome, The Reef and The Gate. Isolating a district or riding through it selects its room. Overview, leaving a ride and clearing the isolated district select The Skyline. The Skyline uses Downtown's loop with a 1.2 kHz low-pass, reverb send 0.45 and gain 0.5. Room changes begin on the next bar boundary and use an equal-power crossfade over two bars. A ride adds a gentle stereo pan that follows its camera heading.

The engine synthesizes its voices with Web Audio. It uses one 140 BPM clock, a 25 ms scheduler timer and 120 ms lookahead on a sixteenth grid. Pattern digits specify velocity and dots specify rests. Hats and percussion carry swing, while the kick stays on the grid. Audio scheduling never runs from the render frame loop.

The voice set includes kick, closed and open hats, tuned percussion, rim, clap, stab, bass, pad, ride, a noise riser and bubble blips. A dotted-eighth delay and synthetic 2.4-second noise-decay reverb feed the lightly compressed and soft-clipped master. Kick envelopes duck pad, stab and bass by 6 dB with a 90 ms release. Sound requires no samples, audio files, audio libraries or additional network loads.

Rooms use a 32-bar arrangement: establish for 16 bars, withhold the named layer for 4, signal the return for 2, then restore the groove for 10. The Yards uses a shorter 16-bar cycle. Signal Row repeats a four-bar musical loop inside its 32-bar arrangement. Every room's root, swing, pattern, pitched voices, decays and effects are declared in the room objects in `viewer/city-audio.js`.

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
- `viewer/city-life.js`: streets, instanced traffic/citizens, signs, wet pavement and atmosphere.
- `viewer/ride.js`: ride camera, sightline checks and saved overview state.
- `viewer/city-audio.js`: procedural voices, audio-clock scheduler, room routing, crossfades and Sound preference.
- `viewer/build.py`: regenerates `data/city-design.json`, then inlines data and JavaScript. Its default private build writes `viewer/index.html` and `viewer/artifact.html`; `--public` writes the masked page and publication assets to `dist/`.

Run `python viewer/build.py` after editing for private local inspection, or `python viewer/build.py --public` to prepare publication. Do not hand-edit `viewer/index.html`, `viewer/artifact.html`, or any file in `dist/`. The public build replaces subdistrict metadata with per-district block labels and displays city names, including The Gate, without folder-key tooltips. Its English interface includes the page title, the owner's introduction and home link, and social preview metadata.

The builder replaces `__CITY_AUDIO__` in the template with `city-audio.js`, just as it inlines street life and the ride camera. All procedural audio code remains inside the generated page.

The viewer uses three.js 0.170 from jsDelivr and fonts from Google Fonts; it needs network access to those resources. These are the only external runtime loads.

## Verification

`qa_city.py` uses a project-local browser harness directly, without reading the vault or relying on a vault-owned browser wrapper. Start `python -m http.server 8765 --bind 127.0.0.1`, then run `python qa_city.py`. Screenshots and machine-readable results go to `renders/qa/`. Run the same harness against `/dist/` with `--url`; it must report 1,246 nodes and zero page errors, with desktop and 375 px screenshots.

The checks sample every route at 0.1-unit intervals for raw camera clearance, final camera clearance, look-ahead occlusion, and both walking lanes. They also exercise entering/exiting rides, district focus, timeline changes, and a fresh mobile page. `window.__vc` exposes the scene state and route helpers for inspection.

`python qa_audio.py` reuses the city QA browser harness. Its gates verify no running audio context after five seconds without a click, a running context after Sound is clicked, analyser RMS above -40 dBFS, no crossfade discontinuity above 6 dB in a 20 ms window, frame rate above 55 fps with sound on, and zero console errors. Run `python qa_city.py` alongside it to retain the collision and page-error gates. Each run writes its measured output to `renders/qa/<prefix>-audio-report.json`.

The twelve-room gate selects each room, waits for the scheduled bar boundary and two-bar crossfade to settle, then samples its analyser for four seconds. Every room must be non-silent, and every pair must differ by at least 8 percent in spectral centroid or 2 dB in RMS. The Archive timeline check scrubs weeks 0 through 12 and verifies that cutoff follows measured brightness monotonically. This compares cutoff with brightness, rather than requiring chronological weeks to get steadily brighter: dates, status and decay can lower brightness as time advances.

[LOG.md](../LOG.md) contains twelve listening prompts with empty score cells. The owner scores the rooms after deployment; collecting those subjective scores is not part of the local automated gate.

`window.__vc.audio` exposes `ctx`, `setRoom`, `room`, `analyser` and `rooms` for inspection. The context is absent before the first Sound gesture; selecting a room through the API does not bypass that gesture requirement.
