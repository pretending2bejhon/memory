# Vault City

A second brain rendered as a living cyberpunk night city.

Live: [jhonalbert.com/memory/](https://jhonalbert.com/memory/). The owner publishes this route after the local build and gates pass.

Tall illuminated districts, rain on dark streets, walking citizens, and a street-level ride through the Archive and around the city. The editable Blender scene includes an overview camera and a second camera on Lantern avenue.

Every note in an Obsidian vault becomes a building. Every `[[wikilink]]` becomes a road. The vault's folders become districts, each with its own architecture and colour. Time runs from the week the vault started to today, thirteen weekly frames, so you can watch the city grow and watch old streets go dark when nobody touches their notes any more.

The project has two halves that share the same data and the same rules:

- **An offline render pipeline** in Blender (`export.py`, `layout.py`, `city.py`): a still, a time-lapse, a turntable, a contact sheet of the design iterations and a compressed GLB of the city.
- **An interactive viewer** in the browser (`viewer/`): the same city in three.js, with a timeline scrubber, district focus, street traffic, walking citizens, rain, a collision-checked street-level ride, and procedural sound.

The export stores numbers and folder metadata, with no note titles, filenames, paths or note text. The public build masks subdistrict names with per-district `block 1`, `block 2`, and later labels, and uses the city's display names in its interface. The source is intended for a public repository on `main`; the published page is generated separately in `dist/`. See [docs/DATA.md](docs/DATA.md).

## Purpose

A personal knowledge base is easy to write into and hard to see. Graph views show links but not time, and they treat a note written yesterday the same as one abandoned in July. Vault City makes three things visible at once:

1. **Shape.** How much of the vault lives where, and how the districts relate. Districts are folders; their size, height and position come from the notes and links inside them.
2. **Time.** When each note was created, played back week by week. Buildings rise on their created week; roads appear when both ends exist.
3. **Decay.** Whether a note is still alive. A building's light is full if the note was created, updated or retrieved in the last 45 days, fades to a faint shell after 90 days, and goes dark if the note is no longer active. Foundations without front-matter never light.

## Quick start

Requirements: Python 3.10+ (standard library for export and layout; Pillow for the contact sheet and public preview), Blender 5.2 for renders, any modern browser for the viewer.

```bash
python export.py            # reads the vault, writes data/vault-city.json, prints a census
python layout.py            # computes the city plan, writes data/layout.json
python viewer/build.py      # generates shared architecture/streets and inlines the viewer
```

Open `viewer/index.html` in a browser (it loads three.js from a CDN, so it needs a network connection). If you want a local server, `.claude/launch.json` starts one on port 8765:

```bash
python -m http.server 8765 --bind 127.0.0.1
```

The default build is private: it preserves folder metadata in the local viewer. To refresh the public city, the owner runs:

```bash
python export.py && python layout.py && python viewer/build.py --public
```

This writes `dist/index.html`, `dist/.nojekyll`, and `dist/og.jpg`. Run the privacy, size and browser gates below, then publish from the owner's configured checkout:

```bash
bash tools/deploy.sh "message"
```

Only the owner creates the public repository, configures `origin`, and deploys. The local handoff does none of those actions. The rulings behind this build: public source on `main`, an English interface, and procedural sound with no audio files.

To render with Blender (headless, never opens the GUI):

```bash
"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" -b --python city.py -- --mode iter --iter 1 --week 12
```

Modes: `iter` (quick Workbench still), `final` (EEVEE still with bloom), `timelapse`, `turntable`, `glb`. See [docs/PIPELINE.md](docs/PIPELINE.md).

Click Sound beside View, or press `M`, to turn sound on. It starts off and requires a deliberate gesture even when the browser remembers an on preference. Each of the twelve districts has its own room, and overview plays Downtown's distant Skyline mix. Room changes crossfade on the shared 140 BPM clock. Scrubbing time adds voices as buildings appear and changes the filter and reverb as their lights fade. Every sound is synthesized in the browser, with no audio files. See [docs/VIEWER.md](docs/VIEWER.md) for controls and audio verification, and [LOG.md](LOG.md) for the owner's listening sheet.

## What is in the repository

| path | what it is |
|---|---|
| `export.py` | Walks the vault, resolves wikilinks, writes anonymous nodes and edges |
| `layout.py` | Force-directed layout per district, streets by week for the episodic district, plateau placement |
| `city.py`, `blender_design.py` | Blender scene, detailed architecture, street furniture, renders and GLB export |
| `design.py` | Shared building dimensions and clear boulevard routes |
| `contact.py` | Contact sheet of the design iterations with their scores (Pillow) |
| `viewer/template.html`, `viewer/city-life.js`, `viewer/ride.js` | Interactive city, street life and ride camera |
| `viewer/city-audio.js` | Procedural sound engine, room definitions and Sound control |
| `qa_city.py`, `qa_audio.py` | Shared browser harness for city geometry, interaction, sound and performance gates |
| `viewer/build.py` | Compacts data into private local pages by default; `--public` creates the masked publication in `dist/` |
| `data/vault-city.json` | Anonymous nodes and edges, numeric state and folder metadata |
| `data/layout.json` | Positions and plateaus |
| `final.png`, `timelapse.mp4`, `turntable.mp4`, `contact.png`, `city.glb`, `city.blend` | Render outputs |
| `renders/iter_NN.png` | The nine design iterations |
| `LOG.md` | The build log: rules written before code, design iterations and scores, and the twelve-room listening sheet |
| `SUMMARY.md` | Final numbers and what helped |
| `tools/deploy.sh` | Publishes `dist/` through a temporary `gh-pages` worktree when the owner runs it |

## Documentation

- [docs/PIPELINE.md](docs/PIPELINE.md): how the pipeline runs end to end, every script and mode.
- [docs/DATA.md](docs/DATA.md): the JSON schemas and the privacy rules.
- [docs/RULES.md](docs/RULES.md): the visual grammar, the decay rules and the district styles.
- [docs/VIEWER.md](docs/VIEWER.md): the interactive viewer, controls and how the code is organised.

## Numbers from the current vault

1,246 notes, 2,304 unique links between them, 13 weekly frames from 2026-06-29 to 2026-09-21, 12 districts. The current visual build includes 15 street loops and up to 260 animated pedestrians. See [docs/VIEWER.md](docs/VIEWER.md) for controls and verification.
