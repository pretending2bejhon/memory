# Rules

The same rules drive the Blender renders and the interactive viewer. They are implemented twice, in `city.py` and in `viewer/template.html`, and must be kept identical. `LOG.md` records the decay rules as they were written before the code.

## Time

- Week 0 is Monday 2026-06-29. Week 12 is 2026-09-21. Thirteen frames.
- A building appears on its created week (negative weeks clamp to 0). Notes without a date appear at week 0 as foundations.
- A knowledge link appears when both of its ends exist.
- In the viewer time is continuous: buildings rise over the 0.7 weeks before their created week and roads fade in over 0.4 weeks.

## Decay

Applied per building per frame. `t` is the frame week, dates are compared in days.

1. **Foundation.** No front-matter: a low plinth, never lit, present from week 0.
2. **Absent.** Created week greater than `t`: not built yet.
3. **Dark.** `status` is anything other than `active` (including missing): body pulled toward the background, no light.
4. **Lit.** Last touch is the later of created and updated. `retrieval_count` is an undated cumulative counter, so it counts as a touch only on the last frame (the export date), never earlier. With `age = t * 7 - last touch`:
   - `age <= 45` days: light 1.0, full.
   - `45 < age < 90`: light fades linearly from 1.0 to 0.15.
   - `age >= 90`: light 0.15, the faint shell.

In the current vault every `retrieval_count` is 0, so decay is entirely a function of dates and status.

## Visual design

The city uses blue-black ground (`#09131f`), deep atmospheric fog (`#030913`), and district-specific illumination. The Archive is amber, Downtown violet, the Library blue, Prasma cyan, Signal Row pink, and the Compass white. Building bodies stay desaturated so the illuminated windows remain legible. `design.py` owns the shared dimensions and palette; `viewer/template.html` adds shader-level facade color and window patterns.

## Form

`design.py:architecture` assigns a deterministic form, width, depth, height and rotation to each anonymous node. The baseline height is `2.5 + 1.65 * log2(1 + inbound + retrieval_count)`, with district multipliers and seeded variation. Downtown and the Compass form the tall skyline. Archive shophouses have narrow footprints to preserve their street corridors. Foundations remain low, and hubs outside the core/downtown remain plazas.

Both renderers consume `data/city-design.json`. Blender creates discrete window geometry, tiered bodies and roof equipment in `blender_design.py`; the viewer uses instanced forms with procedural window occupancy and facade mullions. Their detail geometry is renderer-specific; their dimensions, district identity and street plan are shared.

## Streets and life

The 15 navigable street loops are distinct from the knowledge-link overlay. Each route is validated against all nearby building footprints, including facade overhangs. Rounded corners and arc-length sampling keep vehicles and the camera on the same continuous road. Adjacent walking lanes are checked separately. Street lighting and citizens are ambient scenery, while the note buildings retain their timeline and decay rules.

Knowledge links retain their appearance weeks and can be enabled in the viewer. They are hidden in the default overview and final Blender render so the actual street network remains readable.
