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
    stages = []
    venues = []
    furniture = []
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
