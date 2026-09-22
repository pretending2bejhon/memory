# Vault City: local public build and procedural rooms

The interactive viewer and Blender scene now use a shared design generated from the existing anonymous data: 1,246 buildings, 12 districts and 15 navigable street loops. The scene has taller district-specific architecture, illuminated facades, roof equipment, street lamps, damp pavement, traffic and citizens. The browser includes up to 260 animated pedestrians and a street-level ride camera with restored overview state on exit.

The local publication build masks subdistrict names with generic block labels, uses English city names throughout the visible interface, and includes the owner's introduction, home link and social preview. Source belongs on the local `main` branch; `python viewer/build.py --public` generates the separate `dist/` publication. The default build preserves private folder metadata in the local viewer pages.

The browser now synthesizes twelve district rooms and the Skyline overview mix using Web Audio, with no samples or audio files. Sound requires a deliberate gesture, even when an on preference is remembered. One 140 BPM clock keeps district and ride changes aligned to the next bar, with a two-bar crossfade. The timeline's building density unmutes layers in a fixed order; building brightness controls the low-pass and reverb with 250 ms smoothing. Musical arrangements use 32-bar cycles, except The Yards at 16; Signal Row repeats a four-bar phrase.

## Current outputs

- `viewer/index.html` and `viewer/artifact.html`: generated private interactive city with inline procedural audio.
- `dist/index.html`, `dist/.nojekyll` and `dist/og.jpg`: generated masked public page, publication marker and 1200 by 630 social preview, prepared locally for the owner to deploy.
- `viewer/city-audio.js`: procedural voices, twelve room definitions, shared clock and timeline coupling.
- `city.blend`: editable architecture, lighting, street scenery and two cameras.
- `city.glb`: Draco-compressed architecture and neon meshes with baked vertex colors.
- `final.png`: 1920×1080 overview.
- `renders/street-level.png`: 1440×900 Blender street view.
- `renders/qa/`: browser screenshots and machine-readable city, public-page and audio verification reports.
- `LOG.md`: preserved visual design history and a twelve-room listening sheet with empty score cells.

## Verification

The earlier visual-build QA sampled 8,746 positions across every route, including raw/final camera clearance, look-ahead occlusion and both pedestrian lanes: zero detected collisions. It also exercised timeline changes, district focus, ride exit and a fresh mobile viewport with no page errors. Repeated street lights and signs are instanced; that measured overview used 156 render calls. These are the retained visual-build results, not a substitute for fresh phase evidence.

The existing `timelapse.mp4`, `turntable.mp4` and `contact.png` belong to the original visual iteration and were not regenerated for this refresh. `LOG.md` retains that earlier design history.

Fresh public-build, collision, browser and audio phase evidence belongs to [HANDOFF.md](HANDOFF.md), including each exact command, output and any remaining limitation. The final rulings in [docs/SPEC.md](docs/SPEC.md) require public source on `main`, English UI and procedural audio without audio files. The owner creates the repository, configures the remote, deploys and scores the listening sheet after the local handoff. This work does not publish anything or wait for listening scores.
