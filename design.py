"""Shared architecture and collision-cleared streets for Blender and the viewer.

Only the existing anonymous export is used. Run via viewer/build.py or directly.
"""
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PALETTE = {
    "core": "#e8f7ff", "episodic": "#ffb36b", "semantic": "#68baff",
    "procedural": "#b6ccdf", "prospective": "#ffc578", "working": "#df82ff",
    "jhon": "#ffdca3", "prasma": "#59e4e8", "branding": "#ff679b",
    "onebrain": "#9bbcff", "reef": "#62e2c0", "inbox": "#df82ff",
}


def architecture(n):
    seed = ((n["id"] * 1664525 + 1013904223) % 4294967296) / 4294967296
    jitter = 0.84 + seed * 0.34
    district = n["district"]
    t = n["type"]
    if n["created"] is None:
        return {"kind": "found", "w": 0.65, "d": 0.65, "h": 0.24, "rot": 0}
    mass = math.log2(1 + n["inbound"] + n["retrieval_count"])
    h = (2.5 + mass * 1.65) * jitter
    kind, w, d = "tower", 0.76, 0.76
    if district == "episodic":
        kind, w, d = "shop", 0.60, 0.66
        h = (2.2 + mass * 1.65 + (n["id"] % 7) * 0.16) * jitter
        if n["id"] % 9 == 0:
            kind, h = "tower", h * 1.45
    elif district == "working":
        kind = "slab" if n["id"] % 3 else "tower"
        h *= 1.85
        if mass > 3.8:
            kind, h = "spire", h * 1.12
    elif district == "core":
        kind, h, w, d = "spire", h * 2.3, 0.9, 0.9
    elif district == "semantic":
        kind = "stepped" if n["id"] % 3 else "cyl"
        h *= 1.25
    elif district == "procedural":
        kind = "saw" if t == "sop" else "cyl"
        w, d, h = 0.84, 0.64, h * 0.8
    elif district == "prospective":
        kind = "scaffold" if t in ("plan", "draft") else "tower"
    elif district == "prasma":
        kind, h = "hex" if n["id"] % 2 else "slab", h * 1.45
    elif district == "branding":
        kind, w, d, h = "sign", 0.88, 0.42, h * 1.35
    elif district == "onebrain":
        kind, w, d, h = "dome", 1.5, 1.5, 3.6
    elif district == "reef":
        kind, w, d, h = "dome", 0.86, 0.86, 1.7 + seed
    elif district == "jhon":
        kind, h = "gable" if n["id"] % 3 else "stepped", h * 0.72
    if t == "hub" and district not in ("core", "working"):
        kind, h = "plaza", 1.15
    return {"kind": kind, "w": w, "d": d, "h": round(min(h, 29), 3), "rot": 0}


def rounded_loop(cx, cy, rx, ry, radius=0.7):
    """Dense rounded rectangle, with both straights and arcs sampled <= .16 units."""
    points = []
    corners = [(cx+rx-radius, cy+ry-radius, 0), (cx-rx+radius, cy+ry-radius, 90),
               (cx-rx+radius, cy-ry+radius, 180), (cx+rx-radius, cy-ry+radius, 270)]
    for x, y, angle in corners:
        for j in range(13):
            a = math.radians(angle + j * 90 / 12)
            points.append([x+radius*math.cos(a), y+radius*math.sin(a)])
        end = points[-1]
        nx, ny, na = corners[(corners.index((x, y, angle))+1) % 4]
        start = [nx+radius*math.cos(math.radians(na)), ny+radius*math.sin(math.radians(na))]
        count = max(1, math.ceil(math.dist(end, start) / 0.16))
        for j in range(1, count):
            points.append([end[k]+(start[k]-end[k])*j/count for k in range(2)])
    return points


def footprint_clearance(point, node, form, pos):
    x, y = pos[str(node["id"])]
    # Includes facade fins and canopies, not just the main wall.
    dx = max(0, abs(point[0]-x)-form["w"]*0.57)
    dy = max(0, abs(point[1]-y)-form["d"]*0.57)
    return math.hypot(dx, dy)


STAGE_NAMES = {
    "core": "Compass Main Stage", "episodic": "Archive Sound System", "semantic": "Listening Terrace",
    "procedural": "Works Warehouse", "prospective": "Site Rave", "working": "Downtown Club Floor",
    "jhon": "Block Party", "prasma": "Campus Terrace", "branding": "Arcade Stage",
    "onebrain": "Planetarium Deck", "reef": "Reef Island Stage", "inbox": "Welcome Stage",
}
# The overview camera sits south-west of the city, so a free sector facing it is preferred.
VIEW = (-0.375, -0.927)


def ring_outer(district, p):
    """Outer edge of a district's ring sidewalk: ring radius + half road + sidewalk."""
    return p["rx"] + (0.75 if district == "onebrain" else 0.4) + 0.44 + 0.13


_GRID = {}


def footprint_distance(x, y, data, buildings, layout):
    """Distance from a point to the nearest building footprint (0.57 overhang), within 6 units."""
    key = id(data)
    if key not in _GRID:
        grid = {}
        for n in data["nodes"]:
            bx, by = layout["pos"][str(n["id"])]
            grid.setdefault((math.floor(bx / 4), math.floor(by / 4)), []).append(n)
        _GRID.clear()
        _GRID[key] = grid
    grid, best = _GRID[key], math.inf
    gx, gy = math.floor(x / 4), math.floor(y / 4)
    for i in range(gx - 2, gx + 3):
        for j in range(gy - 2, gy + 3):
            for n in grid.get((i, j), ()):
                best = min(best, footprint_clearance((x, y), n, buildings[str(n["id"])], layout["pos"]))
    return best


def segment_distance(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    t = max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy or 1)))
    return math.hypot(px - ax - dx * t, py - ay - dy * t)


def deck_clear(x, y, r, district, layout, bridges, lake, taken):
    """A cantilevered deck keeps 0.5 from other districts, bridges, the lake and other decks."""
    for other, q in layout["districts"].items():
        if other == district:
            continue
        if q["shape"] == "disc":
            gap = math.hypot(x - q["cx"], y - q["cy"]) - ring_outer(other, q) - r
        else:
            dx = max(0, abs(x - q["cx"]) - q["rx"] - 0.4)
            dy = max(0, abs(y - q["cy"]) - q["ry"] - 0.4)
            gap = math.hypot(dx, dy) - r
        if gap < 0.5:
            return False
    for b in bridges:
        pts = b["points"]
        for (ax, ay), (bx, by) in zip(pts, pts[1:]):
            if segment_distance(x, y, ax, ay, bx, by) < r + b.get("halfWidth", 0.57) + 0.5:
                return False
    for w in lake:
        if (((x - w["cx"]) / (w["rx"] + r + 0.5)) ** 2 + ((y - w["cy"]) / (w["ry"] + r + 0.5)) ** 2) < 1:
            return False
    for s in taken:
        if math.hypot(x - s["x"], y - s["y"]) < r + s["r"] + 0.5:
            return False
    return True


def place_stages(data, layout, buildings, routes, bridges, lake):
    """C4.2: one stage per district, a free plaza on the plateau or a deck outside its ring."""
    stages = []
    for district, p in layout["districts"].items():
        n = p["n"]
        r = max(1.2, min(2.4, 0.9 + 0.12 * p["rx"])) if p["shape"] == "disc" else 2.4
        best = None
        if p["shape"] == "disc":
            outer = ring_outer(district, p)
            inner = p["rx"] + (0.75 if district == "onebrain" else 0.4) - 0.44 - 0.13
            for step in range(180):
                a = step * math.tau / 180
                ux, uy = math.cos(a), math.sin(a)
                facing = ux * VIEW[0] + uy * VIEW[1]
                # Option 1: a free disc on the plateau touching the ring.
                cx, cy = p["cx"] + ux * (inner - r), p["cy"] + uy * (inner - r)
                if inner - r > 0.5 and footprint_distance(cx, cy, data, buildings, layout) >= r + 0.2:
                    score = 10 + facing
                    if not best or score > best[0]:
                        best = (score, cx, cy, a, "plaza", p["z"] + 0.02)
                # Option 2: a deck outside the ring in a free sector.
                dx, dy = p["cx"] + ux * (outer + r), p["cy"] + uy * (outer + r)
                if deck_clear(dx, dy, r, district, layout, bridges, lake, stages):
                    clearance = min(4.0, min(
                        (math.hypot(dx - q["cx"], dy - q["cy"]) - ring_outer(o, q) - r
                         if q["shape"] == "disc" else 4.0)
                        for o, q in layout["districts"].items() if o != district))
                    score = clearance + 1.5 * facing
                    if not best or (best[4] != "plaza" and score > best[0]):
                        best = (score, dx, dy, a, "deck", p["z"] + 0.045)
        else:
            # The Archive: a deck off the south or north end of one of its avenues.
            for route in routes:
                if route["district"] != district:
                    continue
                xs = [q[0] for q in route["points"]]
                cx = (min(xs) + max(xs)) / 2
                for sign in (-1, 1):
                    edge = p["cy"] + sign * p["ry"]
                    dx, dy = cx, edge + sign * (0.2 + r)
                    if not deck_clear(dx, dy, r, district, layout, bridges, lake, stages):
                        continue
                    score = -sign * 2 - abs(cx - (p["cx"] + p["rx"] * 0.35)) * 0.05
                    if not best or score > best[0]:
                        best = (score, dx, dy, math.atan2(sign, 0), "deck", p["z"] + 0.045)
        if not best:
            raise ValueError(f"No stage fits in {district}")
        _, x, y, a, kind, z = best
        stages.append({"district": district, "name": STAGE_NAMES[district], "kind": kind,
                       "x": round(x, 3), "y": round(y, 3), "z": round(z, 3), "r": round(r, 3),
                       "angle": round(a, 4), "capacity": min(80, round(10 * math.pi * r * r)), "n": n})
    return stages


VENUE_TYPES = ["bar", "club", "food", "cafe", "tienda", "record", "tattoo", "barber", "arcade", "other"]
VENUE_WEIGHTS = {
    "episodic": [20, 5, 25, 5, 25, 5, 5, 5, 0, 5], "working": [25, 30, 15, 10, 5, 0, 5, 0, 5, 5],
    "semantic": [10, 0, 15, 35, 5, 10, 0, 5, 0, 20], "procedural": [25, 35, 20, 5, 5, 5, 5, 0, 0, 0],
    "prospective": [20, 10, 50, 0, 20, 0, 0, 0, 0, 0], "jhon": [10, 0, 25, 10, 35, 0, 0, 10, 0, 10],
    "prasma": [15, 10, 20, 35, 0, 5, 0, 5, 10, 0],
}
VENUE_OTHER = {"episodic": "laundromat", "working": "pharmacy", "semantic": "bookshop", "jhon": "bakery"}
SINGLE_VENUE = {"branding": "record", "onebrain": "arcade", "reef": "beachbar", "inbox": "hotel", "core": "cafe"}


def seeded(seed):
    state = [seed & 0xFFFFFFFF]

    def rnd():
        state[0] = (state[0] * 1664525 + 1013904223) & 0xFFFFFFFF
        return state[0] / 4294967296
    return rnd


def route_points_by_district(routes):
    grid = {}
    for route in routes:
        half = 0.27 if route["district"] == "episodic" else 0.44
        for x, y in route["points"]:
            grid.setdefault((route["district"], math.floor(x / 2), math.floor(y / 2)), []).append((x, y, half))
    return grid


def nearest_route(grid, district, x, y):
    best, gx, gy = None, math.floor(x / 2), math.floor(y / 2)
    for i in range(gx - 1, gx + 2):
        for j in range(gy - 1, gy + 2):
            for px, py, half in grid.get((district, i, j), ()):
                dist = math.hypot(px - x, py - y)
                if not best or dist < best[0]:
                    best = (dist, px, py, half)
    return best


def place_venues(data, layout, buildings, routes, stages):
    """C4.3: ground-floor venues on buildings whose face is within 0.7 of a ring sidewalk."""
    grid = route_points_by_district(routes)
    by_district = {}
    for n in data["nodes"]:
        form = buildings[str(n["id"])]
        if n["created"] is None or form["kind"] in ("plaza", "found"):
            continue
        bx, by = layout["pos"][str(n["id"])]
        best = None
        for nx, ny, half, length in ((1, 0, form["w"] / 2, form["d"]), (-1, 0, form["w"] / 2, form["d"]),
                                     (0, 1, form["d"] / 2, form["w"]), (0, -1, form["d"] / 2, form["w"])):
            fx, fy = bx + nx * half, by + ny * half
            # Any part of the face counts: sample along it and keep its closest point to the road.
            for t in (-0.45, -0.2, 0, 0.2, 0.45):
                sx, sy = fx - ny * t * length, fy + nx * t * length
                near = nearest_route(grid, n["district"], sx, sy)
                if not near:
                    continue
                dist, px, py, road = near
                if dist < 1e-6 or ((px - sx) * nx + (py - sy) * ny) / dist < 0.55:
                    continue
                gap = dist - road - 0.13
                if 0 <= gap <= 0.7 and (not best or gap < best["gap"]):
                    best = {"face": [nx, ny], "x": fx, "y": fy, "gap": gap, "length": length}
        if best:
            best["host"] = n["id"]
            by_district.setdefault(n["district"], []).append(best)
    venues = []
    for district, p in layout["districts"].items():
        target = max(1, min(24, round(p["n"] / 12)))
        rnd = seeded(sum(map(ord, district)) * 7919)
        pool = sorted(by_district.get(district, []), key=lambda v: (v["host"] * 2654435761) % 4294967296)
        chosen = []
        for v in pool:
            if len(chosen) >= target:
                break
            if all(math.hypot(v["x"] - c["x"], v["y"] - c["y"]) > 0.8 for c in chosen):
                chosen.append(v)
        for v in chosen:
            if district in SINGLE_VENUE:
                kind = SINGLE_VENUE[district]
            else:
                weights = VENUE_WEIGHTS[district]
                x, total, kind = rnd() * sum(weights), 0, "bar"
                for name, weight in zip(VENUE_TYPES, weights):
                    total += weight
                    if x <= total and weight:
                        kind = VENUE_OTHER.get(district, "bar") if name == "other" else name
                        break
            # A terrace only where the free strip in front of the face is 0.25 deep or more.
            terrace = 0.0
            if v["gap"] >= 0.25:
                depth = min(0.5, v["gap"] - 0.04)
                ok = True
                for a in (0.1, depth * 0.5, depth):
                    for b in (-0.35, 0, 0.35):
                        tx = v["x"] + v["face"][0] * a + (-v["face"][1]) * b * v["length"]
                        ty = v["y"] + v["face"][1] * a + v["face"][0] * b * v["length"]
                        for n2 in data["nodes"]:
                            if n2["id"] == v["host"]:
                                continue
                            qx, qy = layout["pos"][str(n2["id"])]
                            if (abs(qx - tx) < 2 and abs(qy - ty) < 2 and
                                    footprint_clearance((tx, ty), n2, buildings[str(n2["id"])], layout["pos"]) < 0.02):
                                ok = False
                terrace = round(depth, 3) if ok else 0.0
            venues.append({"district": district, "host": v["host"], "type": kind, "face": v["face"],
                           "x": round(v["x"], 3), "y": round(v["y"], 3), "length": round(v["length"], 3),
                           "gap": round(v["gap"], 3), "terrace": terrace})
    return venues


def place_furniture(data, layout, buildings, routes, stages, venues):
    """C4.5: terrace sets, carts on the stage decks and free spots near the roads, manholes."""
    items, taken = [], []

    def free(x, y, r, district):
        if footprint_distance(x, y, data, buildings, layout) < r + 0.2:
            return False
        for route in routes:
            if route["district"] != district:
                continue
            half = 0.27 if district == "episodic" else 0.44
            lane = min(half + 0.04, route["clearance"] - 0.12)
            for px, py in route["points"][::2]:
                d = math.hypot(px - x, py - y)
                if d < half + r + 0.02 or abs(d - lane) < r + 0.08:
                    return False
        return all(math.hypot(x - tx, y - ty) > r + tr + 0.05 for tx, ty, tr in taken)

    def add(kind, x, y, z, rot, district, variant=0, venue=-1, r=0.1):
        items.append({"kind": kind, "x": round(x, 3), "y": round(y, 3), "z": round(z, 3), "rot": round(rot, 3),
                      "district": district, "variant": variant, "venue": venue})
        taken.append((x, y, r))

    zs = {d: p["z"] for d, p in layout["districts"].items()}
    for i, v in enumerate(venues):
        if not v["terrace"]:
            continue
        nx, ny = v["face"]
        tx, ty = -ny, nx
        depth = v["terrace"]
        count = max(1, min(3, int(v["length"] * 0.8 / 0.3)))
        for k in range(count):
            b = (k - (count - 1) / 2) * 0.3
            cx = v["x"] + nx * (0.06 + depth * 0.5) + tx * b
            cy = v["y"] + ny * (0.06 + depth * 0.5) + ty * b
            rot = math.atan2(nx, ny)
            add("table", cx, cy, zs[v["district"]], rot, v["district"], 1 if v["type"] == "tienda" else 0, i, 0.06)
            for side in (-1, 1):
                add("chair", cx + tx * side * 0.085, cy + ty * side * 0.085, zs[v["district"]], rot + side * math.pi / 2,
                    v["district"], 1 if v["type"] == "tienda" else 0, i, 0.035)
        if v["type"] == "tienda":
            add("crate", v["x"] + nx * 0.08 + tx * (count * 0.15 + 0.08), v["y"] + ny * 0.08 + ty * (count * 0.15 + 0.08),
                zs[v["district"]], 0, v["district"], 0, i, 0.05)
    for s in stages:
        for k, side in enumerate((-1, 1)):
            a = s["angle"] + side * (1.9 if s["kind"] == "deck" else 1.2)
            x, y = s["x"] + math.cos(a) * (s["r"] - 0.22), s["y"] + math.sin(a) * (s["r"] - 0.22)
            add("cart", x, y, s["z"], math.atan2(math.cos(a), math.sin(a)) + math.pi, s["district"],
                (len(items) + k) % 5, -1, 0.12)
    target = 3 * len(venues)
    rnd = seeded(20260922)
    kinds = ["bin", "kiosk", "cart", "busstop", "bin"]
    radius = {"bin": 0.04, "kiosk": 0.14, "cart": 0.12, "busstop": 0.16}
    placed = sum(1 for it in items if it["kind"] in ("cart", "table", "crate"))
    for route in routes:
        half = 0.27 if route["district"] == "episodic" else 0.44
        pts = route["points"]
        p = layout["districts"][route["district"]]
        for j in range(0, len(pts), 9):
            if placed >= target:
                break
            (ax, ay), (bx, by) = pts[j], pts[(j + 1) % len(pts)]
            dx, dy = bx - ax, by - ay
            length = math.hypot(dx, dy) or 1
            nx, ny = -dy / length, dx / length
            for sign in (-1, 1):
                ox, oy = nx * sign, ny * sign
                if p["shape"] == "disc":
                    inside = ((ax + ox - p["cx"]) ** 2 + (ay + oy - p["cy"]) ** 2 <
                              (ax - p["cx"]) ** 2 + (ay - p["cy"]) ** 2)
                    if not inside:
                        continue
                for off in (half + 0.13 + 0.25, half + 0.13 + 0.45):
                    x, y = ax + ox * off, ay + oy * off
                    kind = kinds[int(rnd() * 5)]
                    r = radius[kind]
                    if free(x, y, r, route["district"]):
                        add(kind, x, y, p["z"], math.atan2(-ox, -oy), route["district"], int(rnd() * 5), -1, r)
                        placed += 1
                        break
    for route in routes:
        pts = route["points"]
        for j in range(3, len(pts), max(40, len(pts) // 3)):
            x, y = pts[j]
            items.append({"kind": "manhole", "x": round(x, 3), "y": round(y, 3), "z": round(route["z"] - 0.035, 3),
                          "rot": 0, "district": route["district"], "variant": 0, "venue": -1})
    return items


def build_design(data, layout):
    buildings = {str(n["id"]): architecture(n) for n in data["nodes"]}
    routes = []
    ep = layout["districts"]["episodic"]
    for i, (left, right) in enumerate(((3, 9), (-9, -3), (15, 21), (-21, -15))):
        routes.append({"name": ["Lantern avenue", "Archive night market", "Memory boulevard", "West archive"][i],
                       "district": "episodic", "z": ep["z"] + 0.035,
                       "points": rounded_loop(ep["cx"]+(left+right)/2, ep["cy"], (right-left)/2, ep["ry"]-0.2)})
    for district, p in layout["districts"].items():
        if p["shape"] != "disc":
            continue
        radius = p["rx"] + (0.75 if district == "onebrain" else 0.4)
        count = max(160, math.ceil(2*math.pi*radius/0.16))
        points = [[p["cx"]+radius*math.cos(i*math.tau/count),
                   p["cy"]+radius*math.sin(i*math.tau/count)] for i in range(count)]
        routes.append({"name": "District circuit", "district": district, "z": p["z"]+0.035, "points": points})
    for route in routes:
        xs, ys = zip(*route["points"])
        bounds = (min(xs)-2, min(ys)-2, max(xs)+2, max(ys)+2)
        nearby = [n for n in data["nodes"] if bounds[0] <= layout["pos"][str(n["id"])][0] <= bounds[2]
                  and bounds[1] <= layout["pos"][str(n["id"])][1] <= bounds[3]]
        clearance = min(footprint_clearance(p, n, buildings[str(n["id"])], layout["pos"])
                        for p in route["points"] for n in nearby)
        # Half a car is .10; a .14 camera sphere fits inside this corridor.
        if clearance < 0.20:
            raise ValueError(f"Unsafe street: {route['name']} clearance={clearance:.3f}")
        route["clearance"] = round(clearance, 3)
        route["points"] = [[round(x, 4), round(y, 4)] for x, y in route["points"]]
    # Ordered placement slots: later layers must consume earlier reservations.
    bridges = []
    lake = []
    stages = place_stages(data, layout, buildings, routes, bridges, lake)
    venues = place_venues(data, layout, buildings, routes, stages)
    furniture = place_furniture(data, layout, buildings, routes, stages, venues)
    trees = []
    return {"palette": PALETTE, "buildings": buildings, "routes": routes,
            "bridges": bridges, "lake": lake, "stages": stages, "venues": venues,
            "furniture": furniture, "trees": trees}


def main():
    data = json.loads((ROOT / "data/vault-city.json").read_text(encoding="utf-8"))
    layout = json.loads((ROOT / "data/layout.json").read_text(encoding="utf-8"))
    result = build_design(data, layout)
    (ROOT / "data/city-design.json").write_text(json.dumps(result, separators=(",", ":")), encoding="utf-8")
    print(f"Designed {len(result['buildings'])} buildings and {len(result['routes'])} clear street loops")
    return result


if __name__ == "__main__":
    main()
