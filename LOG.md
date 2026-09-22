# vault-city LOG

Unattended build, 2026-09-21. Blender 5.2.1 LTS headless. All work inside C:\Users\jhona\code\vault-city.

## Census (export.py)

- nodes: 1246 (62 without front-matter, 71 more with front-matter but no `created`)
- edges: 2304 unique directed pairs between in-scope notes
- resolved wikilink occurrences (with multiplicity): ~3340; the rest (981) are dangling.
  Checked before building anything: every unresolved target was tested against every
  filename stem and alias in the whole vault (case-insensitive), against the date-prefix-stripped
  stem, hyphen/underscore/space variants, and substring matches. 981 targets exist nowhere in
  the vault (73 more exist only in out-of-scope folders). So the resolver is right and the
  vault simply carries ~1000 dangling links. The 3,000 figure matches occurrence count, not
  unique pairs. Edges in the JSON are unique pairs.
- retrieval_count: the key is present on 296 notes but every value is 0, so retrieval can
  never raise the glow in this dataset. The rule is still implemented.
- updated: 125 notes.
- per district: episodic 454, working 213, semantic 166, procedural 146, jhon 108, prasma 98,
  prospective 38, core 8, branding 5, onebrain 4, reef 4, inbox 2 (files directly in 10-memory).
- per created week: -1:1, 0:44, 1:59, 2:62, 3:25, 4:128, 5:142, 6:124, 7:198, 8:117, 9:81,
  10:60, 11:65, 12:7, null:133.

## Decay rules (written before coding them)

Frame date for week w = 2026-06-29 + 7w days (a Monday). Applied per building per frame:

1. No front-matter: foundation. A low plinth, body colour pulled 75% toward the night
   background, no light object, never changes. Present from week 0 (it has no created date).
2. created week > w: the building does not exist yet. Roads need both ends to exist.
3. status != active (including front-matter without a status): dark. Body pulled 70% toward
   background, no light object.
4. Otherwise the last touch is max(created date, updated date). retrieval_count is an undated
   cumulative counter, so it can only be trusted as a touch at the export date (week 12).
   For the week-12 frame, retrieval_count > 0 counts as a touch on 2026-09-21; for earlier
   frames it is ignored because we cannot place it in time.
   - age = frame date - last touch, in days.
   - age <= 45: light = 1.0 (full).
   - 45 < age < 90: light fades linearly from 1.0 to 0.15.
   - age >= 90: light = 0.15, the faint shell.
5. Window glow colour = signal #be95ff mixed toward highlight #d7afff by
   min(1, log2(1 + retrieval_count) / 5). Light intensity = light level; at 0.15 the light
   object colour is dim glow #958ba9 mixed 40% into the body colour.
6. Body colour = lerp(background #0f0a19, base #6c5f82, 0.35 + 0.65 * light).
7. Height = 0.5 + 0.85 * log2(1 + inbound + retrieval_count), scaled by type; hubs are clamped
   low (plaza) and grow in width instead of height.

Because every retrieval_count is 0 in this vault, the glow highlight never fires; decay is driven
entirely by created/updated dates and status.

## Iterations

### iter 01 - score 3/10
Blender run 8 s. Everything builds (1246 bodies, 1081 light objects, 13 road buckets) but the
composition fails: the bounding-sphere camera fit put the city in the middle third of the frame,
and the ground plane is small enough that its rectangle edge is visible against the background, so
it reads as a model on a table rather than a night city. Districts are legible as discs plus the
episodic block behind, which is right. Palette: the night background and dark violet bodies are
correct, but at this scale the window bands collapse into dots and decay is not readable at all.
Fog did not run: the compositor Map Range node id changed in 5.x (it is a shared shader node).
Next: fit the camera by projecting plateau outlines and binary-searching the distance, drop the
Track-To constraint for an explicit look-at matrix with a 1.5 degree roll, enlarge the ground to
+-400 units, use ShaderNodeMapRange and ShaderNodeMix for the depth fog toward deep.

### iter 02 - score 4/10
Camera fit and depth fog now work (compositor ok, dist 235, run 6 s), and the ground edge is gone.
But the frame is still mostly empty: from azimuth -118 the city's long axis (episodic block behind
the core) runs into the depth of the view, so the vertical extent limits the fit and the city
occupies about 40% of the width. Districts read as separate discs, which is good. The palette is
right in hue but everything is murky: window bands are one pixel at this scale, the road web
between districts renders as grey spaghetti converging on the core and dominates the ground, and
decay is still unreadable. Next: azimuth -155 / elevation 48 so the long axis runs across the
frame, thicker window bands and edge ring, roads thinner (0.02) and dimmer (mix 0.4), fog max 0.6.

### iter 03 - score 4/10
Azimuth -155 spreads the city diagonally but the frame is still only ~56% used: probing the
projection showed the fit is limited by the nearest plateau touching the bottom edge (ndc y
-0.94..0.47) because the aim point sits at the plan centroid and perspective pushes the near
districts down. Rendering is still too dark to read decay; the road web is dimmer, which helps.
Districts read, the palette is right but muddy. Two structural changes next instead of camera
nudging: (1) re-plan the city as a wide band (episodic block transposed so streets stack along x,
placed to the left of the core; the force-directed discs packed to the right in a band), since a
16:9 architectural frame wants a skyline wider than deep; (2) after fitting the distance, shift the
aim point so the projected extents are centred, then refit. Also fog max 0.5, plateau slabs a
little lighter, window bands 0.22 tall every 0.5 so a lit block averages to violet at 3 px per
unit. Also fixed a non-deterministic layout seed (Python string hash randomisation).

### iter 04 - score 6/10
The wide plan plus centred aim point works: projected extents are now x +-0.94, y +-0.81, the city
fills the frame from the episodic slab in the front-left to the venture discs at the back-right,
and the twelve plateaus read as separate places with the core disc in the middle. Palette is on
target: night background, matte violet-grey bodies, violet window bands averaging to a lavender
glow per block, deep fog at the far edge. Decay is faintly visible as dimmer street rows at one
end of the episodic block. What is wrong: the ~1,200 cross-district roads render as a violet hair
bundle between the episodic slab and the discs and dominate the middle of the frame; the ground
grid is invisible at 3 px per unit; the core district is too small to read as the compass hero.
Next: split roads into intra-district (width 0.02, mix 0.45) and inter-district (width 0.012, mix
0.18), widen the grid hairlines to 0.12, and decide the core treatment from the data.

### iter 05 - score 6/10
(First attempt of this iteration ran with only the core-plateau change because a text replacement
in city.py failed to match; re-applied and re-rendered as the same iteration.) Splitting roads into
intra-district (0.02 wide, mix 0.45) and inter-district (0.012, mix 0.18) removed the hair bundle;
the middle of the frame is calm and the plateaus read as islands. Composition is right: episodic
slab front-left, discs back-right, core in the middle. Palette is right in hue. Wrong: the ground
reads as pure black so the plateaus float and the hairline grid is invisible; the core is still a
small dark disc, its bone lights do not register; the episodic slab reads as a tablet of text-like
dots because log footprints are 0.36 units at 3 px per unit. Decay: dimmer rows exist at the old
end of the episodic block but only a careful eye finds them. Next: measure actual pixel values in
the PNG (ground, plateau top, lit block) and calibrate: push fog start back, raise the grid, and
make the core plateau rim bone-tinted and brighter.

### iter 06 - score 7/10
Calibrated the lighting with a white test scene: the Default studio light renders a white
horizontal face at 0.34 linear and camera-facing faces at 0.085, which is why every render so far
was mud. paint.sl is neutral and the most uniform (0.74 horizontal, 0.40 vertical), so the render
now uses paint.sl with exposure log2(1/0.74). Measured on the PNG: near ground (16,11,27) against
the palette night (15,10,25), so the background now matches; the grid hairlines are visible; the
plateaus, buildings and faint inter-district roads all read, and the core disc with its bone-lit
towers sits in the middle. What is wrong: the districts read as grey-lavender texture rather than
violet-lit; window bands are only on vertical faces, which the high camera barely sees, so the
"one violet light" is missing; the plateau slabs are too bright and compete with the buildings;
the grid is a touch heavy. Decay is now visible in the episodic block as dimmer old streets.
Next: put the bevel edge (chamfer ring) on the light object so lit roofs read violet from above,
plateau slab mix 0.26 -> 0.19, grid half-width 0.06 -> 0.045, fog max 0.55, and a wider body
brightness range (0.3 + 0.7 * light) for more contrast between full and faded.

### iter 07 - score 7/10
Moving the chamfer ring onto the light object adds a violet rim on each lit roof, but at 3 px per
unit the effect is marginal; the districts still read as grey-lavender texture on lavender slabs.
Darker plateaus (0.19) and the thinner grid helped calm the ground. Composition unchanged and
right. The real issue is tonal: body roofs render at their full albedo (#6c5f82) because the
exposure was calibrated so horizontal faces land on their object colour, so a roof is as bright as
a window. A night render lights albedo dimly; the base colour stays #6c5f82 as albedo but the
bodies should render at roughly half of it, leaving the signal/highlight lights as the only bright
thing. Next: body gain 0.55 on building bodies, plateau mix 0.14, light objects at
lerp(signal, highlight, 0.5) when full, intra-district roads mix 0.35. Not repeating: further
rim/band geometry tweaks (two iterations show they do not read at this scale).

### iter 08 - score 8/10
Rendering bodies at 55% of their albedo was the change that made the picture: the buildings are
now dark matte masses and only the signal/highlight lights are bright, so every district reads as
violet points on a dark slab and the whole frame finally says "dark, calm, one violet light".
The core disc sits in the middle with its bone-lit towers; the episodic slab in the front-left
reads as streets by week with visibly dimmer old streets (decay is now legible at a glance in
that block, less so inside the discs where full and faded buildings are interleaved). Palette is
on target (measured ground (16,11,27)). What is wrong: the plateaus carry a wide empty rim around
their buildings, so districts look like plates with scattered dots instead of dense blocks; the
inter-district road fan between the slab and the discs is still the busiest area of the frame.
Next: tighten the plateau margin (rmax + 0.9 S), pack the force-directed discs denser (0.70 of
sqrt(n)), thin the inter-district roads a little more (mix 0.14). Time budget means one or two
more iterations before the final phase.

### iter 09 - score 8/10
Tighter plateau rims and denser force-directed discs make each district read as a block of
violet points rather than a plate with a scatter; the twelve places are legible, the core sits in
the middle, the episodic slab reads as streets by week with the old streets visibly dimmer, and
the palette is on target. Still not a 9: the inter-district road fan between the slab and the
discs remains the busiest region of the frame, the slab's log rows still look like lines of text
at 3 px per unit, and inside the discs full and faded buildings interleave so decay is only
legible in the episodic block. The loop stops here (9 of 20 iterations) because the remaining
time budget is needed for the final EEVEE render, the two videos, the GLB and the contact sheet.

## Loop summary
Scores: 3, 4, 4, 6, 6, 7, 7, 8, 8. Every Blender iteration ran in 5-8 s. The three changes that
helped most: (1) the lighting calibration with a white test scene (paint.sl + exposure so the
ground lands on #0f0a19), (2) the wide plan plus centred camera fit, (3) rendering bodies at
half albedo so only the lights are bright. Changes that did not help and were not repeated: rim
and window-band geometry tweaks at this scale.

## Final phase
- final.png: first EEVEE pass over-exposed (emission strength 6 plus bloom turned the lights
  white and the emissive roads dominated). Fixed with emission 1.25, a separate faint road
  material (0.45), sun 3.2, world 0.6, bloom threshold 0.6 / strength 0.3. Re-rendered at 256
  samples in well under a minute of the 15 allowed.
- timelapse.mp4: Blender 5.2 needs image_settings.media_type = "VIDEO" before FFMPEG can be
  selected; 144 frames rendered in 93 s.
- turntable.mp4: Action.fcurves no longer exists in 5.x (layered actions); the interpolation loop
  was dropped because there is one keyframe per frame anyway. 144 frames in 139 s.
- city.glb: single mesh, per-corner colour attribute, Draco level 6, 284 KB.
- contact.png: Pillow, Consolas (Cascadia Mono not installed), night background, #f1eef7 text.
- Not verified from renders: the encoded videos themselves (no decoder here); stills of weeks 4,
  8 and 12 confirm growth and dimming frame by frame.

## Listening sheet

Twelve procedural rooms share one 140 BPM clock. Listen after each switch has crossed the bar boundary and completed its two-bar fade. Score each room from 1 to 10 after the owner deploys; the empty cells are intentional. Automated measurements and implementation choices are recorded in [HANDOFF.md](HANDOFF.md).

| Room | What to listen for | Score |
|---|---|---|
| The Compass | A firm kick, one offbeat hat, sparse percussion and a low ceremonial drone. | |
| The Archive | A shuffled two-pitch roll and a warm delayed stab that dull as the district fades. | |
| The Library | Round kick, offbeat sub, spacious minor-ninth stabs and distant ride accents. | |
| The Works | Dry metallic rim repetition, hard kick transients and a ratcheting fourth-bar fill. | |
| The Yards | A stab just before the downbeat, rising filter tension and a compact 16-bar return. | |
| Downtown | Dense accented hats, a three-pitch tom roll and claps sitting slightly behind the beat. | |
| The Hills | The widest swing, a warm four-pitch roll, woodblock and a soft major-seventh pad. | |
| Prasma Campus | Precise hat accents, short pitched percussion and a bright, quickly gated stab. | |
| Signal Row | A playful three-note blip phrase repeating every four bars above the clap. | |
| The Dome | A rising four-note arpeggio, grainy percussion and a long dotted-eighth echo. | |
| The Reef | Soft underwater hats, high bubbles and a slowly moving, spacious pad filter. | |
| The Gate | A stripped kick and low drone with room to hear the reverb tail. | |
