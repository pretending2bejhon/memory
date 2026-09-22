# Data

The export and layout JSON files in `data/` hold numeric state, week indices and folder metadata. `data/city-design.json` is a generated design shared by the renderers. None contains note titles, filenames, file paths or note text. Source publication is intentional; the public page carries a stricter mask than the source data.

## Privacy rules

`export.py` never stores or prints a note title, filename, path, body or any text taken from a note. The only strings in the data are district and subdistrict folder names, the `type` and `status` values from front-matter, and dates reduced to week indices. Ids are positions in a sorted walk of the vault, so they carry no meaning outside this export.

`python viewer/build.py --public` replaces the subdistrict string table with generic labels numbered independently within each district: `block 1`, `block 2`, and so on. It writes the publication to `dist/`. District labels shown to readers come from the city style map, including `The Gate`; chip title attributes do not expose folder keys. Types and statuses remain as anonymous state vocabulary.

Without `--public`, the build preserves the original folder metadata in `viewer/index.html` and `viewer/artifact.html` for private inspection. Do not publish those default outputs. Do not alter the export merely to mask the page; masking belongs in the public build.

Before publishing, `dist/index.html` must contain no dated folder name, no Windows path, no vault root and no note path, and every published subdistrict label must match `block <n>`. The build must stay below 1 MB. `qa_public.py` runs these gates and the owner publishes only after they pass.

## `data/vault-city.json`

```json
{
  "week0": "2026-06-29",
  "weeks": 13,
  "nodes": [
    {
      "id": 0,
      "district": "core",
      "subdistrict": "meta",
      "created": 4,
      "updated": null,
      "type": "meta",
      "status": "active",
      "retrieval_count": 0,
      "inbound": 3,
      "outbound": 0
    }
  ],
  "edges": [[0, 17], [0, 42]]
}
```

| field | meaning |
|---|---|
| `id` | numeric id, unique, stable for one export |
| `district` | see the folder table in [PIPELINE.md](PIPELINE.md) |
| `subdistrict` | the subfolder under the district folder, or `""` |
| `created` | week index of the `created` date, may be negative for notes older than week 0, `null` when absent |
| `updated` | week index of the `updated` date or `null` |
| `type` | front-matter `type` (log, fact, sop, decision, plan, draft, hub, note, report, meta, ...) or `null` |
| `status` | front-matter `status` (active, draft, superseded, ...) or `null` |
| `retrieval_count` | integer, 0 when absent |
| `inbound`, `outbound` | number of unique resolved links into and out of the note |
| `edges` | `[source id, target id]` pairs, unique, no self-links |

## `data/layout.json`

```json
{
  "spacing": 1.25,
  "districts": {
    "episodic": { "shape": "rect", "rx": 28.2, "ry": 17.5, "z": 0.35, "n": 454, "cx": -73.1, "cy": 2.3,
                  "streets": [[-27.0, 0], [-24.0, 1]] },
    "working":  { "shape": "disc", "rx": 15.1, "ry": 15.1, "z": 1.0,  "n": 213, "cx": 23.2, "cy": 0.0 }
  },
  "pos": { "0": [1.2, -0.4] },
  "bounds": [-94.1, -42.7, 36.2, 42.5]
}
```

| field | meaning |
|---|---|
| `spacing` | building pitch `S` in world units |
| `districts[d].shape` | `disc` or `rect` |
| `rx`, `ry` | plateau half-extents |
| `z` | plateau height, the ground level of that district's buildings |
| `cx`, `cy` | plateau centre in the plan |
| `streets` | episodic only: `[offset along x, week]` per street row, used for lamp posts |
| `pos` | building centre per node id, plan coordinates (x right, y away from the camera) |
| `bounds` | plan bounding box with margin |

Coordinates: the plan is 2D with `z` up. Blender uses it directly. The viewer maps `(x, y, z)` to three.js `(x, z, -y)`.

## The viewer's compact form

`viewer/build.py` embeds compact arrays to keep the public page below the 1 MB gate:

```
districts, subs, types, statuses : string tables
nodes : [id, districtIdx, subIdx, created, updated, typeIdx, statusIdx, retrieval_count, inbound, outbound, x, y]
edges : [[a, b], ...]
plateaus, bounds, streets, week0, weeks
```
