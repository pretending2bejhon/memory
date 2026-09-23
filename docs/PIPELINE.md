# Pipeline

The data export, layout, shared design, viewer and Blender stages run in order. Each one reads the previous one's output from `data/` and never touches the vault except the first. Export is an owner-run refresh step. Work on an existing export needs only files inside this repository.

```
vault (Obsidian)  ──export.py──►  data/vault-city.json  ──layout.py──►  data/layout.json
                                          │                                    │
                                          ├──────────── city.py (Blender) ◄────┤   renders, videos, glb
                                          └──────────── viewer/build.py ◄──────┘   private pages or dist/
```

## 1. `export.py`: the vault becomes numbers

Standard library only. Configure the vault path in `VAULT` and the folders in `ROOTS`.

What it walks: `00-core`, `10-memory`, `20-ventures`, `30-jhon`. What it skips: `30-jhon/life`, `95-data`, `99-archive`, `90-machinery`, `.obsidian`, any dotfolder, any file that is not `.md`.

For each note it reads the YAML front-matter keys `created`, `updated`, `type`, `domain`, `status`, `retrieval_count` and the `aliases` list, then counts `[[wikilinks]]` in the body. Front-matter parsing is deliberately minimal (scalars, inline lists, block lists); it does not need a YAML library.

Districts come from the folder:

| folder | district |
|---|---|
| `00-core` | `core` |
| `10-memory/<sub>` | `<sub>` (episodic, semantic, procedural, prospective, working) |
| `10-memory` (files at the top) | `inbox` |
| `20-ventures/<venture>` | `<venture>` |
| `30-jhon/*` except `life` | `jhon` |

The subfolder below that becomes `subdistrict`.

Weeks: week 0 is Monday 2026-06-29; `week = (date - week0) // 7`. A note created before week 0 gets a negative index and is clamped to 0 downstream. Notes without front-matter, or without a `created` key, get `created = null`.

Link resolution: each target is stripped of `|alias`, `#heading`, `^block` and any folder path, lower-cased, then matched against filename stems first and aliases second. Edges are unique directed pairs; self-links are dropped. The census printed at the end shows nodes, edges, unresolved targets, and counts per district and per week. In this vault about 980 targets exist nowhere (dangling links), which is why unique edges (2,304) are below the raw link count.

## 2. `layout.py`: the city plan

Standard library only. Deterministic (seeded per district name).

- **Episodic** is laid out as streets by week: the notes of each week line both sides of a street, long weeks wrap into several streets, streets stack in week order. The block is then transposed so the streets run across the city's short axis.
- **Every other district** gets a Fruchterman-Reingold force-directed layout on its intra-district edges, an overlap-removal pass with a minimum pitch of `0.95 * S`, then a scale to a disc.
- **Plateaus**: the core sits at the origin, the other discs are packed around it in a wide band by size, and the episodic block goes to the left. Plateau heights encode the tier: core 2.4, memory districts 1.0, jhon 0.75, ventures 0.55, episodic 0.35.

Output: `spacing`, `districts` (centre, shape, radii, height, count, episodic street rows), `pos` per node id, `bounds`.

## 3. Shared design and Blender

Run `python viewer/build.py` (or `python design.py`) before Blender to create `data/city-design.json`. `design.py` preserves anonymous note identities and positions, assigns taller district-specific architecture, and validates 15 rounded street loops against building footprints. `blender_design.py` models discrete windows, setbacks, roof equipment, sidewalks, lamps, citizens and cars.

### `city.py`: Blender

Pure `bpy` and `mathutils`, no add-ons. Always run headless with `-b`. Arguments come after `--`:

| mode | what it does | typical time |
|---|---|---|
| `--mode iter --iter N --week W` | Workbench still at 480x270 to `renders/iter_NN.png`, saves `city.blend`. Add `--out path` to render elsewhere without saving. | 5-8 s |
| `--mode final --samples S` | EEVEE 1920x1080 overview, 1440x900 street still, and editable `city.blend` with both cameras | Hardware dependent |
| `--mode timelapse` | 13 weekly states keyframed over 144 frames, Workbench 640x360, H.264 to `timelapse.mp4` | 95 s |
| `--mode turntable` | 144-frame orbit of the week-12 city to `turntable.mp4` | 140 s |
| `--mode glb` | Architecture and emissive meshes with baked vertex colors, including street scenery, Draco level 6 | Hardware dependent |
| `--mode calib` | Renders a white test scene per studio-light preset, used to calibrate exposure | |

How a frame is built: ground and district foundations, the shared street network with batched sidewalks and furniture, a detailed body object per note, discrete illuminated window meshes, and optional knowledge links. Object colors carry the note decay state. The final render hides knowledge links and includes practical lights along selected boulevards. The `.blend` file retains an overview camera and a separate Lantern avenue street camera.

Blender 5.2 specifics worth knowing: compositing uses `scene.compositing_node_group` with the shared `ShaderNodeMapRange` and `ShaderNodeMix` nodes; bloom is the Glare node with its `Type` socket set to `Bloom`; video output needs `image_settings.media_type = "VIDEO"` before `FFMPEG` can be selected; `Action.fcurves` no longer exists.

## 4. `viewer/build.py`: the interactive page

Reads the anonymous data and layout, generates the shared design, compacts nodes into arrays, and inlines the data and viewer source modules into `viewer/template.html`.

The source modules are `viewer/city-life.js`, `viewer/ride.js`, `viewer/city-audio.js`,
`viewer/beat.js`, `viewer/rave-light.js`, `viewer/crowd.js` and `viewer/society.js`. Each module is inlined through its own template placeholder. The audio module replaces the `__CITY_AUDIO__` placeholder in the same build pass. It schedules the Strudel room files and routes their samples and synths; the build emits no audio directory or audio files. Sound remains off until a deliberate activation of its control, including when an on preference was remembered.

The audio module plays twelve district rooms (Strudel code in `viewer/rooms/`) and the Skyline overview mix. All use the same 140 BPM audio clock. District focus and ride hooks request a switch that starts on the next bar and drops on the next eight-bar phrase. Musical arrangements cycle over 32 bars, except The Yards at 16; Signal Row's musical loop repeats every four bars. On each week update the renderer supplies district density and brightness, which control layer thresholds, low-pass cutoff and reverb with 250 ms smoothing. [VIEWER.md](VIEWER.md) documents the formulas and fixed layer order.

The beat module reads scheduled layer hits and the audible output clock without scheduling audio itself. The rave-light module builds the procedural sky, beams, drone glyphs, fireworks, grid and mounted screens, and drives their four-step room transition. Note-window light remains outside this system. All world and postprocessing materials compile before the page is ready. These visual layers add no image, model or font assets and require no additional external loads.

Without flags, `python viewer/build.py` preserves the private folder metadata and writes:

- `viewer/index.html`: a complete document you can open locally.
- `viewer/artifact.html`: the same private page as a fragment without `<html>`/`<head>`/`<body>`.

For publication, run `python viewer/build.py --public`. The public build replaces the `subs` string table with generic `block 1`, `block 2`, and later labels numbered independently within each district. Reader-facing district names use the style map, including The Gate; chips have no raw folder-key title attribute. It writes:

- `dist/index.html`: the complete masked page with title, description, home link and social preview metadata.
- `dist/.nojekyll`: the hosting marker.
- `dist/og.jpg`: a 1200 by 630 preview generated from `final.png`, below 200 KB.

Never hand-edit either generated viewer page or anything under `dist/`. Change the viewer sources and rebuild. The public page must pass the privacy grep gate and remain at or below 900,000 bytes before publication. `qa_public.py` runs the static gates; `qa_city.py`, `qa_audio.py` and `qa_world.py` run the browser gates.

The viewer needs a network connection for three.js (jsDelivr) and Rajdhani and IBM Plex fonts (Google Fonts). Strudel and its samples load after a Sound gesture from the existing audio sources documented in VIEWER.md. Geometry and visual textures are procedural.

## 5. `contact.py`

Builds `contact.png`, a grid of the iteration renders with their scores, in Consolas on the night background. Scores are hard-coded in `SCORES`; edit them if you run more iterations.

## 6. Owner refresh and deployment

The rulings are final: the repository is public, `main` holds the source, `gh-pages` holds the generated publication, the interface is English, and the room music is Strudel code in `viewer/rooms/`. The owner creates the repository, configures its `origin` remote, and deploys after reviewing the local handoff. Building and testing locally do not create a remote or publish the site.

To refresh from the owner's vault:

```bash
python export.py && python layout.py && python viewer/build.py --public
```

For changes to viewer sources against the existing export, only the final build command is needed. Re-render the still first if the preview image needs updating.

Start the local server and run the browser gates:

```bash
python -m http.server 8765 --bind 127.0.0.1
```

In another terminal run `python qa_public.py`, then the browser suites below. The local browser harness requires Python 3.11. Select the phase that the sources implement; `v0` is foundations, `v1` adds rave light, and Run A ends at `v3`.

```powershell
py -V:Astral/CPython3.11.15 qa_city.py --url http://127.0.0.1:8765/dist/ --prefix public
py -V:Astral/CPython3.11.15 qa_audio.py --phase p2 --url http://127.0.0.1:8765/dist/ --prefix public
py -V:Astral/CPython3.11.15 qa_world.py --phase v1 --url http://127.0.0.1:8765/dist/ --prefix public
```

Browser QA must report zero collisions and zero page errors, all 36 audio checks, and every world gate for the implemented phase. The public page must expose 1,246 nodes, and screenshots must include desktop and 375 px views in `renders/qa/`. World reports list the scenes measured, their settled tiers and the phase-scoped performance budgets; future scenes are not marked passed before they exist.

`python qa_audio.py` shares the browser harness with `python qa_city.py`. Audio gates cover autoplay prevention, context activation, signal level, the phrase-locked transition, frame rate with sound on and console errors. The full room check waits for each switch to settle, then samples for four seconds; all twelve rooms must be non-silent, and every pair must differ by at least 8 percent in spectral centroid or 2 dB in RMS. The Archive check scrubs weeks 0 through 12 and tests cutoff against measured brightness, which may rise or fall over chronological time. Run both suites after changing the engine or viewer hooks. Keep their fresh command output in the handoff; a successful build alone is not an audio check.

After the gates pass, the owner publishes:

```bash
bash tools/deploy.sh "message"
```

`tools/deploy.sh` uses `origin` and a temporary worktree to copy `dist/` onto `gh-pages`, commit the publication and push it. It requires `dist/index.html` and `dist/.nojekyll`. The published page URL is [jhonalbert.com/memory/](https://jhonalbert.com/memory/). The local implementation session does not run this script.

`LOG.md` records the design loop and its scores, followed by a twelve-room listening sheet. Its audio score column stays empty for the owner to fill after deployment. Keep appending to the log when iterating further.
