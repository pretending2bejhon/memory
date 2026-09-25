"""V7 gates (Lake and nature, SPEC-rave C9, C10, D V7) with a positive control for every gate.

Module for qa_world.py: the functions take the design dict or a qa_browser Engine and return
(report, checks) like qa_world's verify_* functions. Usage (browser parts need Python 3.11):

    python qa_nature.py data                  data gates only (no browser)
    python3.11 qa_nature.py all              data, browser and the S4 scene
    python3.11 qa_nature.py browser          browser gates only

Reports and scene evidence are written under renders/qa/ with the requested prefix.
Geometry here is written independently of design.py and nature.js (its own ellipse distance, its own
footprint, road and deck tests), so a placement bug cannot pass its own check.
"""
import argparse
import copy
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = next(p for p in (HERE, *HERE.parents) if (p / "data" / "layout.json").exists())
sys.path.insert(0, str(ROOT))
# In the scratch folder the gates read the V7 prototype page and data; merged into the tree, the real ones.
SCRATCH = (HERE / "city-design-v7.json").exists()
DESIGN = HERE / "city-design-v7.json" if SCRATCH else ROOT / "data" / "city-design.json"
URL = "http://127.0.0.1:8765/renders/snap/wip/v7_proto/viewer/" if SCRATCH else "http://127.0.0.1:8765/viewer/"
OUT = HERE / "qa-v7" if SCRATCH else ROOT / "renders" / "qa"

SPEC = {"dog": 24, "cat": 20, "pigeon": 150, "bat": 40, "capybara": 6, "iguana": 10, "heron": 2, "owl": 4,
        "robot": 8, "firefly": 400, "fish": 60, "jelly": 30, "boat": 3, "partyBoat": 1}
# The lake's people per tier (others, C3.7): crowd.js reserves their sum from each tier's extras cap.
PEOPLE = {"rider": {3: 10, 2: 6, 1: 3}, "stroller": {3: 6, 2: 4, 1: 1}, "folk": {3: 4, 2: 2, 1: 1}}
SIDEWALK, EDGE, SAND, BEACH = 0.13, 0.57, 1.4, 0.45
TRUNK = {"palm": 0.07, "tropical": 0.09}
CANOPY = {"palm": (0.86, 0.62), "tropical": (0.42, 0.78)}   # bottom as a fraction of height, radius
# The shore structures as nature.js draws them: the palapa's eave corners, its deck, the fire's ring of log seats and
# a hammock's cloth (half widths, layout units).
BAR_EAVE, BAR_DECK, FIRE_R, HAMMOCK_HALF = (0.64, 0.55), (0.5, 0.42), 0.45, 0.1


def tier_count(n, t):
    """C13.1: Tier 3 the spec count, Tier 2 60 %, Tier 1 40 % (at least one)."""
    return n if t == 3 or n <= 1 else max(1, round(n * (0.6 if t == 2 else 0.4)))


# ------------------------------------------------------------------ geometry (independent of the builders)
def shore_distance(lake, x, y):
    """Signed distance from (x, y) to the ellipse, negative inside: 64-step scan then Newton polish."""
    c, s = math.cos(lake["angle"]), math.sin(lake["angle"])
    dx, dy = x - lake["cx"], y - lake["cy"]
    u, v = dx * c + dy * s, -dx * s + dy * c
    a, b = lake["rx"], lake["ry"]
    d2 = lambda t: (a * math.cos(t) - u) ** 2 + (b * math.sin(t) - v) ** 2
    t = min((k * math.tau / 64 for k in range(64)), key=d2)
    for _ in range(20):
        ct, st = math.cos(t), math.sin(t)
        g = (a * ct - u) * (-a * st) + (b * st - v) * (b * ct)
        h = (a * st) ** 2 + (a * ct - u) * (-a * ct) + (b * ct) ** 2 + (b * st - v) * (-b * st)
        if abs(h) < 1e-12:
            break
        t -= g / h
    d = math.sqrt(d2(t))
    return -d if (u / a) ** 2 + (v / b) ** 2 < 1 else d


def seg_dist(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    k = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy or 1)))
    return math.hypot(px - ax - dx * k, py - ay - dy * k)


def polyline_dist(px, py, pts, closed=False):
    best = math.inf
    n = len(pts)
    for i in range(n if closed else n - 1):
        a, b = pts[i], pts[(i + 1) % n]
        best = min(best, seg_dist(px, py, a[0], a[1], b[0], b[1]))
    return best


def own_points(route):
    if not route.get("shared"):
        return route["points"], True
    cut, s, out = route["shared"][0]["from"], 0.0, [route["points"][0]]
    for a, b in zip(route["points"], route["points"][1:]):
        s += math.dist(a, b)
        if s > cut + 1e-3:
            break
        out.append(b)
    return out, False


def route_half(route):
    return route.get("width", 0.54 if route["district"] == "episodic" else 0.88) / 2


def is_spoke(bridge):
    """A Compass spoke (C6.1). The published design drops the derived key (roads.js rebuilds it the same way)."""
    return bridge.get("spoke", bridge["from"] == "core")


def reef_route_index(design):
    return next(i for i, r in enumerate(design["routes"]) if r["district"] == "reef")


# ------------------------------------------------------------------ data gate 1: the lake clears rings and bridges
def lake_clearance(design):
    """C9.1: the lake clears every other ring, avenue and link by 1.5 and every bridge by 1.0 (sidewalk edge to
    shore), touches the Reef ring, holds the pier over water and the island inside it (C9.4); the V7 sand strip
    (1.4 plus its 0.4 bank) also keeps 0.5 from every bridge and ring."""
    lake = design["lake"][0]
    reef = reef_route_index(design)
    ring_gap, ring_where = math.inf, None
    for i, r in enumerate(design["routes"]):
        if i == reef:
            continue
        pts, _ = own_points(r)
        for x, y in pts:
            g = shore_distance(lake, x, y) - route_half(r) - SIDEWALK
            if g < ring_gap:
                ring_gap, ring_where = g, [r["name"], r["district"], round(x, 2), round(y, 2)]
    for st in design["streets"]:
        for x, y in st["points"]:
            g = shore_distance(lake, x, y) - st["width"] / 2 - SIDEWALK
            if g < ring_gap:
                ring_gap, ring_where = g, [st["name"], "link", round(x, 2), round(y, 2)]
    bridge_gap, bridge_where = math.inf, None
    for b in design["bridges"]:
        for p in b["points"]:
            g = shore_distance(lake, p[0], p[1]) - EDGE
            if g < bridge_gap:
                bridge_gap, bridge_where = g, [b["name"], round(p[0], 2), round(p[1], 2)]
        for e in b["ends"]:
            for f in e["fillets"]:
                a0, a1 = math.radians(f["a0"]), math.radians(f["a1"])
                for k in range(21):
                    a = a0 + (a1 - a0) * k / 20
                    x, y = f["cx"] + (f["r"] - SIDEWALK) * math.cos(a), f["cy"] + (f["r"] - SIDEWALK) * math.sin(a)
                    g = shore_distance(lake, x, y)
                    if g < bridge_gap:
                        bridge_gap, bridge_where = g, [b["name"] + " fillet", round(x, 2), round(y, 2)]
    rr = design["routes"][reef]
    touch = min(shore_distance(lake, x, y) - route_half(rr) - SIDEWALK for x, y in rr["points"])
    pier, isle = lake["pier"], lake["island"]
    pier_len = math.hypot(pier["x1"] - pier["x0"], pier["y1"] - pier["y0"])
    over = [shore_distance(lake, pier["x0"] + (pier["x1"] - pier["x0"]) * k / 50, pier["y0"] + (pier["y1"] - pier["y0"]) * k / 50)
            for k in range(1, 51)]
    isle_gap = shore_distance(lake, isle["x"], isle["y"]) + isle["r"] + BEACH
    report = {"ringClearance": round(ring_gap, 3), "nearestRing": ring_where, "bridgeClearance": round(bridge_gap, 3),
              "nearestBridge": bridge_where, "reefTouch": round(touch, 3), "pierLength": round(pier_len, 3),
              "pierWidth": pier["width"], "pierMaxShoreGap": round(max(over), 3), "islandBeachInside": round(-isle_gap, 3),
              "sandToBridges": round(bridge_gap - SAND - 0.4, 3), "sandToRings": round(ring_gap - SAND - 0.4, 3),
              "axes": [lake["rx"], lake["ry"]]}
    checks = {"lake clears every other ring, avenue and link by 1.5": ring_gap >= 1.5,
              "lake clears every bridge by 1.0": bridge_gap >= 1.0,
              "lake is 9 by 6 and touches the Reef ring": lake["rx"] == 9 and lake["ry"] == 6 and abs(touch) <= 0.05,
              "pier 0.5 wide, 5 long, over water": abs(pier_len - 5) <= 0.01 and pier["width"] == 0.5 and max(over) <= 0.02,
              "island and its beach inside the lake": isle_gap <= -0.3 and isle["r"] == 2,
              "sand strip keeps 0.5 from bridges and rings": bridge_gap - SAND - 0.4 >= 0.5 and ring_gap - SAND - 0.4 >= 0.5}
    return report, checks


# ------------------------------------------------------------------ data gate 2: trees and plants (C10.2, C4.1)
def trees_clearance(design, data, layout):
    """Every free-standing tree clears footprints by 0.2 (0.57 overhang), stays off carriageways, sidewalks and
    walking lanes, bridge decks, links and the pier, off stage decks and furniture, never overlaps another trunk,
    and its canopy clears any roof that reaches it. Lake trees stand on the sand, Hills palms in the Hills, landing
    palms at a spoke landing; balcony plants sit on a Hills house face."""
    trees = design["trees"]
    zs = {d: p["z"] for d, p in layout["districts"].items()}
    boxes = []
    for n in data["nodes"]:
        f = design["buildings"][str(n["id"])]
        x, y = layout["pos"][str(n["id"])]
        boxes.append((x, y, f["w"] * 0.57, f["d"] * 0.57, zs[n["district"]] + f["h"] * 1.08 + 0.14, n))
    furn_r = {"chair": 0.035, "table": 0.06, "bin": 0.04, "kiosk": 0.14, "cart": 0.12, "busstop": 0.16, "crate": 0.05}
    lake = design["lake"][0]
    pier = lake["pier"]
    routes = [(r, *own_points(r)) for r in design["routes"]]
    fails = {k: [] for k in ("footprint", "canopy", "road", "deck", "stage", "furniture", "overlap", "place")}
    free = [t for t in trees if t["kind"] in TRUNK]
    for i, t in enumerate(free):
        x, y, r = t["x"], t["y"], TRUNK[t["kind"]]
        cb, cr = CANOPY[t["kind"]]
        near = [b for b in boxes if abs(b[0] - x) < 3 and abs(b[1] - y) < 3]
        foot = min((math.hypot(max(0, abs(x - b[0]) - b[2]), max(0, abs(y - b[1]) - b[3])) for b in near), default=math.inf)
        if foot < r + 0.2:
            fails["footprint"].append([i, round(foot, 3)])
        for b in near:
            if b[4] > t["z"] + t["h"] * cb and math.hypot(max(0, abs(x - b[0]) - b[2]), max(0, abs(y - b[1]) - b[3])) < cr + 0.1:
                fails["canopy"].append([i, b[5]["id"]])
                break
        for route, pts, closed in routes:
            if min(abs(p[0] - x) + abs(p[1] - y) for p in pts[::8]) > 4:
                continue
            if polyline_dist(x, y, pts, closed) < route_half(route) + SIDEWALK + r + 0.02:
                fails["road"].append([i, route["name"], route["district"]])
        for b in design["bridges"]:
            if min(abs(p[0] - x) + abs(p[1] - y) for p in b["points"][::5]) < 6 and polyline_dist(x, y, b["points"]) < EDGE + r + 0.2:
                fails["deck"].append([i, b["name"]])
        for st in design["streets"]:
            if polyline_dist(x, y, st["points"]) < st["width"] / 2 + SIDEWALK + r + 0.2:
                fails["deck"].append([i, st["name"]])
        if seg_dist(x, y, pier["x0"], pier["y0"], pier["x1"], pier["y1"]) < pier["width"] / 2 + r + 0.2:
            fails["deck"].append([i, "pier"])
        for s in design["stages"]:
            if math.hypot(x - s["x"], y - s["y"]) < s["r"] + r + 0.3:
                fails["stage"].append([i, s["name"]])
        for f in design["furniture"]:
            if f["kind"] in furn_r and math.hypot(x - f["x"], y - f["y"]) < r + furn_r[f["kind"]]:
                fails["furniture"].append([i, f["kind"]])
        for j in range(i):
            o = free[j]
            if math.hypot(x - o["x"], y - o["y"]) < r + TRUNK[o["kind"]]:
                fails["overlap"].append([i, j])
        at = t.get("at")
        if at in ("lake", "hammock"):
            g = shore_distance(lake, x, y)
            reef = layout["districts"]["reef"]
            if not (0 <= g <= SAND) or math.hypot(x - reef["cx"], y - reef["cy"]) < reef["rx"] + 0.4 + 0.44 + 0.13:
                fails["place"].append([i, at, round(g, 3)])
        elif at == "hills":
            p = layout["districts"]["jhon"]
            if math.hypot(x - p["cx"], y - p["cy"]) > p["rx"]:
                fails["place"].append([i, at])
        elif at == "landing":
            ends = [e for b in design["bridges"] if is_spoke(b) for e in b["ends"]]
            if min(math.hypot(x - e["x"], y - e["y"]) for e in ends) > 3.0:
                fails["place"].append([i, at])
    nodes = {n["id"]: n for n in data["nodes"]}
    bad_balcony = []
    for t in trees:
        if t["kind"] != "balcony":
            continue
        n = nodes.get(t["host"])
        f = design["buildings"].get(str(t["host"]))
        if not n or n["district"] != "jhon" or not f:
            bad_balcony.append(t["host"])
            continue
        hx, hy = layout["pos"][str(t["host"])]
        on_x = abs(abs(t["x"] - hx) - f["w"] / 2) <= 0.08 and abs(t["y"] - hy) < 1e-3
        on_y = abs(abs(t["y"] - hy) - f["d"] / 2) <= 0.08 and abs(t["x"] - hx) < 1e-3
        if not (on_x or on_y) or not 0.2 <= t["f"] <= 0.6:
            bad_balcony.append(t["host"])
    counts = {}
    for t in trees:
        key = t["kind"] + "." + t.get("at", "?")
        counts[key] = counts.get(key, 0) + 1
    ends = sum(2 for b in design["bridges"] if is_spoke(b))
    report = {"counts": counts, "freeStanding": len(free), "failures": {k: v[:8] for k, v in fails.items()},
              "failureCounts": {k: len(v) for k, v in fails.items()}, "badBalconies": bad_balcony[:8],
              "spokeLandingEnds": ends, "shore": {k: v for k, v in lake["shore"].items() if k != "reef"}}
    checks = {"free-standing trees keep every C4.1 clearance": all(not v for k, v in fails.items() if k != "place"),
              "lake trees on the sand, Hills palms in the Hills, landing palms at a landing": not fails["place"],
              "balcony plants on Hills house faces": not bad_balcony and counts.get("balcony.hills", 0) >= 40,
              "wax palms in the Hills and at the spoke landings, tropical trees round the lake":
                  counts.get("palm.hills", 0) >= 24 and counts.get("palm.landing", 0) >= ends - 2 and
                  counts.get("tropical.lake", 0) + counts.get("palm.lake", 0) >= 20,
              "Reef rail opening recorded for roads.js": lake["shore"]["rail"]["route"] == reef_route_index(design)
                  and 0 < (lake["shore"]["rail"]["a1"] - lake["shore"]["rail"]["a0"]) < 180}
    return report, checks


def bar_samples(bar, half, step=0.05):
    """Points over the bar's rotated rectangle (local x along the counter, local z toward the water)."""
    c, s = math.cos(bar["rot"]), math.sin(bar["rot"])
    nx, nz = math.ceil(2 * half[0] / step), math.ceil(2 * half[1] / step)
    return [(bar["x"] - lx * c + lz * s, bar["y"] + lx * s + lz * c)
            for lx in (-half[0] + 2 * half[0] * i / nx for i in range(nx + 1))
            for lz in (-half[1] + 2 * half[1] * j / nz for j in range(nz + 1))]


def shore_clearance(design, data, layout):
    """C4.1 for the shore structures (C9.4): the beach bar over its whole eave rectangle, the bonfire's ring of log
    seats and each hammock's cloth stay 0.02 beyond every carriageway and sidewalk (the eaves hang only 0.4 above
    the ring), 0.2 from footprints, bridge decks, links and the pier, and off the stage decks; the bar's deck, the
    fire and the hammocks stand on the sand."""
    lake = design["lake"][0]
    shore, pier = lake["shore"], lake["pier"]
    zs = {d: p["z"] for d, p in layout["districts"].items()}
    boxes = []
    for n in data["nodes"]:
        f = design["buildings"][str(n["id"])]
        x, y = layout["pos"][str(n["id"])]
        boxes.append((x, y, f["w"] * 0.57, f["d"] * 0.57))
    routes = [(r, *own_points(r)) for r in design["routes"]]
    items = [("bar eaves", 0.0, bar_samples(shore["bar"], BAR_EAVE))]
    if shore.get("bonfire"):
        b = shore["bonfire"]
        items.append(("bonfire", 0.0, [(b["x"], b["y"])] + [(b["x"] + FIRE_R * math.cos(k * math.tau / 24), b["y"] + FIRE_R * math.sin(k * math.tau / 24)) for k in range(24)]))
    for k, (ax, ay, bx, by) in enumerate(shore.get("hammocks", [])):
        n = 20
        items.append(("hammock %d" % k, HAMMOCK_HALF, [(ax + (bx - ax) * i / n, ay + (by - ay) * i / n) for i in range(3, n - 2)]))
    fails, margins = [], {}
    for name, r, pts in items:
        worst = {}
        for x, y in pts:
            for route, rp, closed in routes:
                if min(abs(p[0] - x) + abs(p[1] - y) for p in rp[::8]) > 4:
                    continue
                g = polyline_dist(x, y, rp, closed) - route_half(route) - SIDEWALK - r
                worst["road"] = min(worst.get("road", math.inf), g)
            for bx_, by_, hw, hd in boxes:
                if abs(bx_ - x) < 3 and abs(by_ - y) < 3:
                    worst["footprint"] = min(worst.get("footprint", math.inf), math.hypot(max(0, abs(x - bx_) - hw), max(0, abs(y - by_) - hd)) - r)
            for b in design["bridges"]:
                worst["bridge"] = min(worst.get("bridge", math.inf), polyline_dist(x, y, b["points"]) - EDGE - r)
            for st in design["streets"]:
                worst["link"] = min(worst.get("link", math.inf), polyline_dist(x, y, st["points"]) - st["width"] / 2 - SIDEWALK - r)
            worst["pier"] = min(worst.get("pier", math.inf), seg_dist(x, y, pier["x0"], pier["y0"], pier["x1"], pier["y1"]) - pier["width"] / 2 - r)
            for s in design["stages"]:
                worst["stage"] = min(worst.get("stage", math.inf), math.hypot(x - s["x"], y - s["y"]) - s["r"] - r)
        need = {"road": 0.02, "footprint": 0.2, "bridge": 0.2, "link": 0.2, "pier": 0.2, "stage": 0.3}
        for k, v in worst.items():
            if v < need[k]:
                fails.append([name, k, round(v, 3)])
        margins[name] = {k: round(v, 3) for k, v in worst.items()}
    on_sand = [(x, y) for x, y in bar_samples(shore["bar"], BAR_DECK)]
    if shore.get("bonfire"):
        on_sand.append((shore["bonfire"]["x"], shore["bonfire"]["y"]))
    for ax, ay, bx, by in shore.get("hammocks", []):
        on_sand += [(ax, ay), (bx, by)]
    off_sand = [(round(x, 2), round(y, 2)) for x, y in on_sand if not 0 <= shore_distance(lake, x, y) <= SAND]
    report = {"margins": margins, "failures": fails[:12], "offSand": off_sand[:8]}
    checks = {"shore structures (bar eaves, bonfire, hammocks) keep every C4.1 clearance": not fails and bool(items),
              "the bar deck, the fire and the hammocks stand on the sand": not off_sand}
    return report, checks


def data_gates(design=None):
    """Both data gates with their positive controls; returns {name: {report, checks, controls}}."""
    design = design or json.loads(DESIGN.read_text(encoding="utf-8"))
    data = json.loads((ROOT / "data/vault-city.json").read_text(encoding="utf-8"))
    layout = json.loads((ROOT / "data/layout.json").read_text(encoding="utf-8"))
    out = {}
    rep, chk = lake_clearance(design)
    # Positive controls: the same gate on known-bad lakes must go red.
    bad = copy.deepcopy(design)
    lk, pr = bad["lake"][0], layout["districts"]["prasma"]
    d = math.hypot(pr["cx"] - lk["cx"], pr["cy"] - lk["cy"])
    lk["cx"] += (pr["cx"] - lk["cx"]) / d * 6
    lk["cy"] += (pr["cy"] - lk["cy"]) / d * 6
    _, chk_ring = lake_clearance(bad)
    bad = copy.deepcopy(design)
    b13 = next(b for b in bad["bridges"] if {b["from"], b["to"]} == {"prasma", "reef"})
    mid = b13["points"][len(b13["points"]) // 2]
    lk = bad["lake"][0]
    d = math.hypot(mid[0] - lk["cx"], mid[1] - lk["cy"])
    lk["cx"] += (mid[0] - lk["cx"]) / d * 2.2
    lk["cy"] += (mid[1] - lk["cy"]) / d * 2.2
    _, chk_bridge = lake_clearance(bad)
    out["lake"] = {"report": rep, "checks": chk, "controls": {
        "lake moved 6 toward the neighboring ring fails the ring check": not chk_ring["lake clears every other ring, avenue and link by 1.5"],
        "lake moved 2.2 toward the neighboring bridge fails the bridge check": not chk_bridge["lake clears every bridge by 1.0"]}}
    rep, chk = trees_clearance(design, data, layout)
    bad = copy.deepcopy(design)
    palm = next(t for t in bad["trees"] if t.get("at") == "hills")
    host = next(n for n in data["nodes"] if n["district"] == "jhon" and n["created"] is not None)
    palm["x"], palm["y"] = layout["pos"][str(host["id"])]
    _, chk_foot = trees_clearance(bad, data, layout)
    bad = copy.deepcopy(design)
    tree = next(t for t in bad["trees"] if t.get("at") == "lake")
    ring = bad["routes"][reef_route_index(bad)]
    tree["x"], tree["y"] = ring["points"][40]
    _, chk_road = trees_clearance(bad, data, layout)
    out["trees"] = {"report": rep, "checks": chk, "controls": {
        "a Hills palm moved onto a house fails the clearance check": not chk_foot["free-standing trees keep every C4.1 clearance"],
        "a lake tree moved onto the Reef ring fails the clearance check": not chk_road["free-standing trees keep every C4.1 clearance"]}}
    rep, chk = shore_clearance(design, data, layout)
    key = "shore structures (bar eaves, bonfire, hammocks) keep every C4.1 clearance"
    # Positive controls: the bar where the first prototype put it (its eave over the Reef ring's walking lane), and
    # the bonfire moved onto the Reef ring's outer sidewalk, must both fail.
    bad = copy.deepcopy(design)
    bad["lake"][0]["shore"]["bar"].update({"x": 27.839, "y": -30.42, "rot": 1.843})
    _, chk_bar = shore_clearance(bad, data, layout)
    bad = copy.deepcopy(design)
    reef = layout["districts"]["reef"]
    fire = bad["lake"][0]["shore"]["bonfire"]
    d = math.hypot(fire["x"] - reef["cx"], fire["y"] - reef["cy"])
    fire["x"], fire["y"] = reef["cx"] + (fire["x"] - reef["cx"]) / d * 4.1, reef["cy"] + (fire["y"] - reef["cy"]) / d * 4.1
    _, chk_fire = shore_clearance(bad, data, layout)
    out["shore"] = {"report": rep, "checks": chk, "controls": {
        "the first prototype's bar (eave over the ring's walking lane) fails": not chk_bar[key],
        "a bonfire on the Reef ring's outer sidewalk fails": not chk_fire[key]}}
    return out


# ------------------------------------------------------------------ browser gates
def reload(engine):
    """Fresh page after a gate that bent the live state (a positive control)."""
    engine.goto(engine.page.url.split("#")[0])
    engine.ready()


def wait_frames(engine, n=3):
    engine.evaluate("(n) => new Promise(r => {let k=0;function f(){if(++k>=n)r();else requestAnimationFrame(f);}requestAnimationFrame(f);})", n)


CENSUS = """async () => {
  const v=window.__vc,N=v.nature,desc=Object.getOwnPropertyDescriptor(v.tier,'current'),out={};
  const frames=n=>new Promise(r=>{let k=0;function f(){if(++k>=n)r();else requestAnimationFrame(f);}requestAnimationFrame(f);});
  for(const t of [3,2,1]){Object.defineProperty(v.tier,'current',{get:()=>t,configurable:true});await frames(4);
    const people={rider:0,stroller:0,folk:0};v.crowd.people.forEach((p,i)=>{if(p.lake&&v.crowd.isVisible(i,p))people[p.lake]++;});
    out[t]={nature:N.census(),people,reserve:(v.crowd.lakeReserve||{})[t]??null};}
  Object.defineProperty(v.tier,'current',desc);await frames(3);return out;}"""


def census_checks(value):
    rows, ok = {}, True
    for t in ("3", "2", "1"):
        tier = int(t)
        nat, people = value[t]["nature"], value[t]["people"]
        for kind, n in SPEC.items():
            row = nat[kind]
            want = tier_count(n, tier)
            good = row["allocated"] == n and row["rendered"] == want and row["visible"] == want
            rows.setdefault(kind, {})[t] = {**row, "want": want, "pass": good}
            ok &= good
        for kind, per in PEOPLE.items():
            want = per[tier]
            rows.setdefault(kind, {})[t] = {"visible": people[kind], "want": want, "pass": people[kind] == want}
            ok &= people[kind] == want
        # crowd.js holds exactly the lake's share out of the tier's extras cap.
        reserve = sum(per[tier] for per in PEOPLE.values())
        rows.setdefault("reserve", {})[t] = {"crowd": value[t].get("reserve"), "want": reserve, "pass": value[t].get("reserve") == reserve}
        ok &= value[t].get("reserve") == reserve
    return rows, ok


def verify_census(engine):
    """Animal census per type and tier (C10.1, C13.1), read from the rendered instance buffers."""
    engine.evaluate("() => window.__vc.updateWeek(12)")
    value = engine.evaluate(CENSUS)
    rows, ok = census_checks(value)
    # Positive control: drop one rendered dog; the same comparison must fail.
    engine.evaluate("() => {const m=window.__vc.nature.meshes.dog;m.count=m.count-1;}")
    control = {"3": {"nature": engine.evaluate("() => window.__vc.nature.census()"), "people": value["3"]["people"]},
               "2": value["2"], "1": value["1"]}
    _, control_ok = census_checks(control)
    engine.evaluate("() => {const v=window.__vc;v.nature.applyTier(v.tier.current);}")
    return {"rows": rows}, {"animal census per type and tier": ok}, {"one dog removed fails the census": not control_ok}


SAMPLE_WATER = """(opts) => new Promise(resolve => {
  const v=window.__vc,N=v.nature,c=v.crowd,L=N.lake,arr=c.parts.hips.instanceMatrix.array,rows=[],boats=[];
  const ca=Math.cos(L.angle),sa=Math.sin(L.angle);
  const near=(x,z)=>{const dx=x-L.cx,dy=-z-L.cy,u=dx*ca+dy*sa,w=-dx*sa+dy*ca;return (u/(L.rx+3))**2+(w/(L.ry+3))**2<1;};
  const ring=v.routes.find(r=>r.district==='reef'),pos=new v.camera.position.constructor();
  const start=performance.now();let next=0,sample=0;
  // Two street dogs are walked onto the Reef ring inside the rail opening, so the bike meets them by the water.
  const ri=v.routes.indexOf(ring),rail=N.railOpening,s0=rail.s0-2;
  if(opts.bike)N.animals.dogs.filter((d,i)=>i<N.meshes.dog.count&&d.mode===1).slice(0,2).forEach((d,k)=>{
    d.route=ri;d.dist=rail.s0+1+k*1.5;d.dir=1;d.wait=0;d.cool=0;const lane=Math.abs(d.offset);
    v.sampleRoute(ring,d.dist,pos,lane);const out=Math.hypot(pos.x-N.plateaus.reef.cx,pos.z-N.plateaus.reef.cz);v.sampleRoute(ring,d.dist,pos,-lane);
    d.offset=Math.hypot(pos.x-N.plateaus.reef.cx,pos.z-N.plateaus.reef.cz)>out?-lane:lane;});
  // A scripted bike: round the Reef ring past them, along the wet sand, out along the pier and back (the C8 hook).
  function bike(t){if(!opts.bike)return;const s=s0+t*2.8;
    if(t<8){v.sampleRoute(ring,s,pos,.2);N.mover(0,pos.x,pos.y,pos.z,true);return;}
    const u=t-8,pr=L.pier;
    if(u<10){const du=pr.x0-L.cx,dv=pr.y0-L.cy,t0=Math.atan2((-du*sa+dv*ca)/L.ry,(du*ca+dv*sa)/L.rx),tt=t0+.35+u*.12,cu=Math.cos(tt),su=Math.sin(tt),nu=L.ry*cu,nv=L.rx*su,k=Math.hypot(nu,nv);
      const lu=L.rx*cu+nu/k*.35,lv=L.ry*su+nv/k*.35,x=L.cx+lu*ca-lv*sa,y=L.cy+lu*sa+lv*ca,h=N.surfaceAt(x,-y);if(h!=null)N.mover(0,x,h,-y,true);return;}
    const w=((u-10)*1.2)%10,f=w<5?w/5:2-w/5;N.mover(0,pr.x0+(pr.x1-pr.x0)*f,pr.z,-(pr.y0+(pr.y1-pr.y0)*f),true);}
  function tick(now){const t=(now-start)/1000;bike(t);
    if(t>=next){next+=opts.step;sample++;
      c.people.forEach((p,i)=>{if(!c.isVisible(i,p))return;const o=i*16;if(arr[o+15]!==1)return;const x=arr[o+12],z=arr[o+14];if(near(x,z))rows.push([sample,'person',i,x,arr[o+13],z,p.aboard?1:0]);});
      for(const kind of ['dog','cat','capybara'])N.positions(kind).forEach((q,i)=>{if(near(q[0],q[2]))rows.push([sample,kind,i,q[0],q[1],q[2],0]);});
      const b=N.animals.boats[3];boats.push([sample,b.x,b.z,b.yaw]);}
    if(t<opts.seconds)requestAnimationFrame(tick);else resolve({rows,boats,samples:sample});}
  requestAnimationFrame(tick);})"""


def water_violations(value, lake):
    """Positions inside the water, except on the pier or the island (with its beach). People aboard the party
    boat must stand on its deck (half 0.31 by 0.75) instead."""
    pier, isle = lake["pier"], lake["island"]
    boats = {row[0]: row for row in value["boats"]}
    bad, checked, aboard = [], 0, 0
    for sample, kind, i, x, y, z, on_boat in value["rows"]:
        lx, ly = x, -z
        checked += 1
        if on_boat:
            aboard += 1
            b = boats.get(sample)
            if b:
                dx, dz = x - b[1], z - b[2]
                c, s = math.cos(b[3]), math.sin(b[3])
                lx_, lz_ = c * dx - s * dz, s * dx + c * dz
                if abs(lx_) > 0.33 or abs(lz_) > 0.77:
                    bad.append([sample, "aboard off deck", i, round(lx_, 3), round(lz_, 3)])
            continue
        if shore_distance(lake, lx, ly) >= 0:
            continue
        if seg_dist(lx, ly, pier["x0"], pier["y0"], pier["x1"], pier["y1"]) <= pier["width"] / 2 + 0.02:
            continue
        if math.hypot(lx - isle["x"], ly - isle["y"]) <= isle["r"] + BEACH:
            continue
        bad.append([sample, kind, i, round(lx, 3), round(ly, 3)])
    return bad, checked, aboard


def verify_no_water_walkers(engine, lake, seconds=30):
    """Nothing walks on water (C9.5, C8.4): every citizen, dog, cat and capybara position near the lake, sampled
    at 4 Hz for 30 s while a scripted bike rides the Reef ring, the wet sand and the pier."""
    engine.evaluate("() => window.__vc.updateWeek(12)")
    value = engine.evaluate(SAMPLE_WATER, {"seconds": seconds, "step": 0.25, "bike": True})
    bad, checked, aboard = water_violations(value, lake)
    followed = engine.evaluate("() => ({...window.__vc.nature.diagnostics})")
    # Positive control: a capybara herded into the middle of the lake must be caught.
    engine.evaluate("""() => {const N=window.__vc.nature,c=N.animals.capybaras[0],L=N.lake;
      c.hx=c.x=c.tx=L.cx+5*Math.cos(L.angle);c.hy=c.y=c.ty=L.cy+5*Math.sin(L.angle);c.wait=99;}""")
    wait_frames(engine, 3)
    control = engine.evaluate(SAMPLE_WATER, {"seconds": 1.0, "step": 0.25, "bike": False})
    cbad, _, _ = water_violations(control, lake)
    reload(engine)
    report = {"samples": value["samples"], "positionsChecked": checked, "aboardChecked": aboard,
              "violations": bad[:12], "violationCount": len(bad), "diagnostics": followed}
    return (report, {"nothing walks on water (30 s, 4 Hz, people, dogs, cats, capybaras)": value["samples"] >= 100 and checked > 0 and not bad
                     and followed["dogFollows"] >= 1},
            {"a capybara placed in the lake is caught": any(r[1] == "capybara" for r in cbad)})


BEHAVIOUR = """(opts) => new Promise(resolve => {
  const v=window.__vc,N=v.nature,A=N.animals,BAR=v.beat.barSeconds,pos=new v.camera.position.constructor(),probe=new v.camera.position.constructor();
  const k=A.dogs.findIndex((d,i)=>i<N.meshes.dog.count&&d.mode===1&&d.cool<=0),d=A.dogs[k],r=v.routes[d.route],f=A.flocks[0];
  const s0=d.dist-3*d.dir,rows=[],start=performance.now();let t2=-1,t3=-1,t1=-1,maxLift=0,left=-1,landed=-1,bad=0,maxFollow=0;
  function tick(now){const t=(now-start)/1000;
    if(t<5){v.sampleRoute(r,s0+d.dir*2.8*t,pos,d.offset*.3);N.mover(14,pos.x,pos.y,pos.z,opts.bike);}
    if(t<.6)N.mover(15,f.x,f.y,f.z,false);else if(left<0)left=t;
    if(d.mode===2&&t2<0)t2=t;if(d.mode===3&&t3<0)t3=t;if(t3>=0&&d.mode===1&&t1<0)t1=t;
    if(d.mode>=2){probe.set(d.x,d.y+.05,d.z);if(v.pointBlocked(probe,.05,true)||N.surfaceAt(d.x,d.z)===null)bad++;}
    for(const i of f.members)if(i<N.meshes.pigeon.count)maxLift=Math.max(maxLift,A.pigeons[i].y-A.pigeons[i].gy);
    if(left>=0&&f.state===0&&landed<0)landed=t;
    if(t<14)requestAnimationFrame(tick);else resolve({dog:k,t2,t3,t1,bad,flockState:f.state,maxLift,left,landed,bar:BAR,
      grounded:f.members.every(i=>i>=N.meshes.pigeon.count||Math.abs(A.pigeons[i].y-A.pigeons[i].gy)<1e-6)});}
  requestAnimationFrame(tick);})"""


def verify_behaviours(engine):
    """C10.1 and C8.10 through the mover hook: a dog follows a passing bike for 2 s at most, never into a
    footprint or the water, then walks back and resumes its street; a plaza flock scatters from a person within
    1.5, circles, and lands again after 2 bars."""
    engine.evaluate("() => window.__vc.updateWeek(12)")
    value = engine.evaluate(BEHAVIOUR, {"bike": True})
    def dog_pass(row):
        return row["t2"] >= 0 and row["t3"] > row["t2"] and row["t3"] - row["t2"] <= 2.05 and row["t1"] > row["t3"] and row["bad"] == 0

    def flock_pass(row):
        two_bars = 2 * row["bar"]
        return row["maxLift"] > 0.5 and row["landed"] >= 0 and two_bars <= row["landed"] - row["left"] + 0.6 <= two_bars + 2.0 and row["grounded"]

    dog_ok, flock_ok = dog_pass(value), flock_pass(value)
    reload(engine)
    engine.wait(2)
    engine.evaluate("() => window.__vc.updateWeek(12)")
    control = engine.evaluate(BEHAVIOUR, {"bike": False})
    reload(engine)
    return (value, {"a dog follows a passing bike for 2 s at most and returns, never into a footprint or water": dog_ok,
                    "a flock scatters from a person within 1.5 and lands again after 2 bars": flock_ok},
            {"a walker instead of a bike fails the dog chase predicate": not dog_pass(control),
             "a flock that never lifts fails the scatter predicate": not flock_pass(dict(value, maxLift=0))})


CHASE = """(opts) => new Promise(resolve => {
  const v=window.__vc,N=v.nature,A=N.animals,desc=Object.getOwnPropertyDescriptor(v.tier,'current');
  Object.defineProperty(v.tier,'current',{get:()=>3,configurable:true});
  const probe=new v.camera.position.constructor(),pos=new v.camera.position.constructor();
  const roamers=A.dogs.filter((d,i)=>d.mode===1&&i<A.dogs.length),routeIds=[...new Set(roamers.map(d=>d.route))];
  // Seven passes at a time, one bike per mover slot: a parked roaming dog on a sidewalk, a bike riding by at the
  // given speed along the centre line or the dog's lane; the first pass of all is a tight Archive bend.
  const passes=[];for(let k=0;k<opts.trials;k++){const ri=k===0?0:routeIds[k%routeIds.length],r=v.routes[ri],lane=Math.min(r.width/2+.04,r.clearance-.12);
    const side=k===0?-1:((k>>1)%2?1:-1);passes.push({ri,r,dist:(k===0?24*3.71:k*3.71)%r.length,side,lane,bdir:k===0?-1:(k%2?1:-1),boff:opts.lane?side*lane*.6:0,k});}
  let round=0,start=0,active=[],bad=[],samples=0,followed=0,injected=0;
  function setup(){active=passes.slice(round*7,round*7+7).map((a,s)=>{const d=roamers[(round*7+s)%roamers.length];
      Object.assign(d,{mode:1,route:a.ri,dist:a.dist,offset:a.side*a.lane,wait:1e9,cool:0,trailN:0,dir:1});return Object.assign({},a,{d,slot:s,seen:false});});
    start=performance.now();}
  function tick(now){const t=(now-start)/1000;
    for(const a of active){if(t<3){v.sampleRoute(a.r,a.dist-a.bdir*3+a.bdir*opts.speed*t,pos,a.boff);N.mover(14+a.slot,pos.x,pos.y,pos.z,true);}
      const d=a.d;if(d.mode<2)continue;a.seen=true;samples++;
      // Positive control: one chasing dog is put on a building for one frame; the counter must catch it.
      if(opts.inject&&!injected&&d.mode===2){const n=v.nodes.find(n=>n.state!=='absent'&&n.district===a.r.district);if(n){d.x=n.x;d.z=-n.y;d.y=v.nature.plateaus[n.district].z;injected=1;}}
      probe.set(d.x,d.y+.05,d.z);if(v.pointBlocked(probe,.05,true)||N.surfaceAt(d.x,d.z)===null)bad.push([a.k,a.r.district,d.mode,+d.x.toFixed(2),+d.z.toFixed(2),+t.toFixed(2)]);}
    if(t<7){requestAnimationFrame(tick);return;}
    for(const a of active)if(a.seen)followed++;
    round++;if(round*7<passes.length){setup();requestAnimationFrame(tick);}
    else{Object.defineProperty(v.tier,'current',desc);resolve({passes:passes.length,followed,samples,badCount:bad.length,bad:bad.slice(0,12),injected});}}
  setup();requestAnimationFrame(tick);})"""


def verify_dog_chase(engine):
    """C8.10 at the bike's real speeds (C8.3): dogs chasing bikes at boost, 7 units/s, on the centre line and in the
    dog's own lane, 28 passes each across every dog route, the first a tight Archive bend: no chasing dog is
    ever inside a footprint or on the water."""
    engine.evaluate("() => window.__vc.updateWeek(12)")
    rows = {}
    for lane in (False, True):
        rows["lane" if lane else "centre"] = engine.evaluate(CHASE, {"trials": 28, "speed": 7.0, "lane": lane})
    ok = all(r["badCount"] == 0 and r["followed"] >= 20 for r in rows.values())
    reload(engine)
    engine.evaluate("() => window.__vc.updateWeek(12)")
    control = engine.evaluate(CHASE, {"trials": 7, "speed": 7.0, "lane": False, "inject": True})
    reload(engine)
    return ({"boost": rows, "control": {k: control[k] for k in ("injected", "badCount")}},
            {"dogs chasing a bike at boost never enter a footprint or the water (56 passes, a tight bend)": ok},
            {"a chasing dog put on a building for one frame is caught": control["injected"] == 1 and control["badCount"] > 0})


BIRDS = """() => {const A=window.__vc.nature.animals;
  return A.pigeons.map(p=>{const f=A.flocks[p.flock];return [p.flock,p.gx,p.gy,p.gz,p.rad,p.hgt,f.x,f.z,f.district];});}"""

# Ground and flight of each bird, from the page's own obstacle test and route polylines (not nature.js's helpers):
# [inside a footprint on the ground, gap to the nearest carriageway edge, circling path touches a building].
BIRD_GEOMETRY = """(birds) => {const v=window.__vc,probe=new v.camera.position.constructor(),segs=[];
  for(const r of v.routes){const pts=r.points,h=r.width/2;for(let i=0;i+1<pts.length;i++)segs.push([pts[i].x,pts[i].z,pts[i+1].x,pts[i+1].z,h]);}
  const road=(x,z)=>{let best=1e9;for(const s of segs){if(Math.min(Math.abs(s[0]-x),Math.abs(s[2]-x))>3||Math.min(Math.abs(s[1]-z),Math.abs(s[3]-z))>3)continue;
    const dx=s[2]-s[0],dz=s[3]-s[1],L=dx*dx+dz*dz||1,k=Math.max(0,Math.min(1,((x-s[0])*dx+(z-s[1])*dz)/L));best=Math.min(best,Math.hypot(x-s[0]-dx*k,z-s[1]-dz*k)-s[4]);}return best;};
  return birds.map(b=>{const [,gx,gy,gz,rad,hgt,fx,fz]=b;probe.set(gx,gy+.03,gz);const ground=v.pointBlocked(probe,.03,false);let flight=false;
    for(let k=0;k<24&&!flight;k++){const a=k/24*6.283185307;for(const lift of [.35,.7,1]){
      const x=gx+(fx+Math.cos(a)*rad-gx)*lift,z=gz+(fz+Math.sin(a)*rad-gz)*lift,y=gy+hgt*Math.sin(lift*Math.PI/2);
      if(v.pointBlocked(probe.set(x,y,z),.04,false)){flight=true;break;}}}
    return [ground?1:0,road(gx,gz),flight?1:0];});}"""


def flock_checks(birds, geometry):
    """C10.1 plaza flocks: at least 8 flocks in 8 districts, 10 to 20 birds each, every bird within 1.0 of its
    site, no two birds closer than 0.06 on the ground, sites at least 3 apart; on the ground no bird in a
    footprint or within 0.04 of a carriageway; the circling path clear of every building."""
    flocks = {}
    for b in birds:
        flocks.setdefault(b[0], []).append(b)
    sizes = {k: len(v) for k, v in flocks.items()}
    districts = {v[0][8] for v in flocks.values()}
    spread = max((math.hypot(b[1] - b[6], b[3] - b[7]) for b in birds), default=math.inf)
    closest = math.inf
    for group in flocks.values():
        for i in range(len(group)):
            for j in range(i):
                closest = min(closest, math.hypot(group[i][1] - group[j][1], group[i][3] - group[j][3]))
    sites = [(v[0][6], v[0][7]) for v in flocks.values()]
    site_gap = min((math.dist(a, b) for i, a in enumerate(sites) for b in sites[:i]), default=math.inf)
    ground = sum(g[0] for g in geometry)
    on_road = sum(1 for g in geometry if g[1] < 0.04)
    flight = sum(g[2] for g in geometry)
    report = {"flocks": len(flocks), "districts": sorted(districts), "sizes": sorted(sizes.values()),
              "maxSpread": round(spread, 3), "closestPair": round(closest, 4), "closestSites": round(site_gap, 2),
              "inFootprint": ground, "onCarriageway": on_road, "flightBlocked": flight,
              "minRoadGap": round(min((g[1] for g in geometry), default=math.inf), 3)}
    checks = {"pigeons in 8 or more plaza flocks of 10 to 20, spaced like birds":
                  len(flocks) >= 8 and len(districts) >= 8 and all(10 <= n <= 20 for n in sizes.values())
                  and spread <= 1.0 and closest >= 0.06 and site_gap >= 3.0,
              "pigeons on open ground, off the carriageway, circling clear of the buildings":
                  len(geometry) == len(birds) > 0 and ground == 0 and on_road == 0 and flight == 0}
    return report, checks


def verify_flocks(engine):
    """Pigeon flocks (C10.1): the placement read back from the page, judged by flock_checks."""
    birds = engine.evaluate(BIRDS)
    geometry = engine.evaluate(BIRD_GEOMETRY, birds)
    report, checks = flock_checks(birds, geometry)
    # Positive controls, each through the same predicates: the first prototype's single flock (all 150 birds at
    # one site), two birds on one spot, a bird on a carriageway and a bird on a roof's footprint.
    one = [[0, b[1], b[2], b[3], b[4], b[5], birds[0][6], birds[0][7], birds[0][8]] for b in birds]
    _, c_one = flock_checks(one, geometry)
    stacked = [list(b) for b in birds]
    stacked[1][1:4] = stacked[0][1:4]
    stacked[1][0] = stacked[0][0]
    _, c_stack = flock_checks(stacked, geometry)
    moved = [list(b) for b in birds]
    road_pt = engine.evaluate("() => {const p=window.__vc.routes[0].points[40];return [p.x,p.y,p.z];}")
    roof = engine.evaluate("() => {const v=window.__vc,n=v.nodes.find(n=>n.state!=='absent'&&n.district==='working');return [n.x,v.nature.plateaus.working.z,-n.y];}")
    moved[0][1:4] = road_pt
    moved[1][1:4] = roof
    _, c_moved = flock_checks(moved, engine.evaluate(BIRD_GEOMETRY, moved))
    key_a = "pigeons in 8 or more plaza flocks of 10 to 20, spaced like birds"
    key_b = "pigeons on open ground, off the carriageway, circling clear of the buildings"
    return report, checks, {"all 150 birds in one flock fails": not c_one[key_a],
                            "two birds on one spot fails": not c_stack[key_a],
                            "a bird on a carriageway and one on a footprint fail": not c_moved[key_b]}


BOATS = """(seconds) => new Promise(resolve => {
  const N=window.__vc.nature,rows=[],start=performance.now();let next=0;
  function tick(now){const t=(now-start)/1000;if(t>=next){next+=.2;
    N.animals.boats.forEach((b,k)=>{if(k<3&&k>=N.meshes.boat.count)return;rows.push(['boat',k,b.x,b.z,b.yaw,b.party?1:0]);});
    N.positions('fish').forEach((q,i)=>rows.push(['fish',i,q[0],q[2],q[1],0]));N.positions('jelly').forEach((q,i)=>rows.push(['jelly',i,q[0],q[2],q[1],0]));}
    if(t<seconds)requestAnimationFrame(tick);else resolve(rows);}
  requestAnimationFrame(tick);})"""


def boat_violations(rows, lake):
    pier, isle, bad = lake["pier"], lake["island"], []
    for kind, i, x, z, yaw_or_y, party in rows:
        if kind == "boat":
            hw, hl = (0.31, 0.75) if party else (0.09, 0.25)
            c, s = math.cos(yaw_or_y), math.sin(yaw_or_y)
            for sx, sz in ((hw, hl), (-hw, hl), (hw, -hl), (-hw, -hl)):
                px, pz = x + c * sx + s * sz, z - s * sx + c * sz
                lx, ly = px, -pz
                if shore_distance(lake, lx, ly) > -0.05 or math.hypot(lx - isle["x"], ly - isle["y"]) < isle["r"] + BEACH + 0.05 \
                        or seg_dist(lx, ly, pier["x0"], pier["y0"], pier["x1"], pier["y1"]) < pier["width"] / 2 + 0.05:
                    bad.append([kind, i, round(lx, 2), round(ly, 2)])
                    break
        elif yaw_or_y >= lake["z"] or shore_distance(lake, x, -z) > -0.05:
            bad.append([kind, i, round(x, 2), round(-z, 2), round(yaw_or_y, 3)])
    return bad


def verify_boats(engine, lake):
    """Boats keep to open water, clear of the island beach and the pier; fish and jellies stay under the surface."""
    rows = engine.evaluate(BOATS, 20)
    bad = boat_violations(rows, lake)
    depth_controls = {}
    for kind in ("fish", "jelly"):
        changed = [row[:] for row in rows]
        target = next((row for row in changed if row[0] == kind), None)
        if target:
            target[4] = lake["z"] + 0.1
        depth_controls[kind] = bool(target) and any(row[0] == kind for row in boat_violations(changed, lake))
    engine.evaluate("() => {const b=window.__vc.nature.animals.boats[3];b.cu=0;b.cv=3.5;b.a=.8;b.b=.8;}")
    wait_frames(engine, 2)
    cbad = boat_violations(engine.evaluate(BOATS, 3), lake)
    reload(engine)
    return ({"samples": len(rows), "violations": bad[:10], "violationCount": len(bad)},
            {"boats on open water, fish and jellies under the surface": len(rows) > 0 and not bad},
            {"the party boat pushed onto the pier line is caught": any(r[0] == "boat" for r in cbad),
             "a fish above the water is caught": depth_controls["fish"],
             "a jellyfish above the water is caught": depth_controls["jelly"]})


KICKS = """() => new Promise(resolve => {const v=window.__vc,N=v.nature,k=N.materials.water.uniforms.uKicks.value,hits=[];
  const off=v.beat.on('hit',h=>{if(h.layer==='kick'&&h.gain>0)hits.push(v.beat.diagnostics.lastFrameMs/1000);});
  setTimeout(()=>{off();const rings=Array.from(k).filter(x=>x>0).sort((a,b)=>a-b);
    resolve({hits:hits.slice(-8),rings,beat:v.beat.beatSeconds,match:rings.length>=6&&rings.every(r=>hits.some(h=>Math.abs(h-r)<1e-6))});},4000);})"""


def verify_kick_rings(engine):
    """C9.2: a ripple ring leaves the island stage on every kick (the last eight kicks are the eight live rings)."""
    value = engine.evaluate(KICKS)
    gaps = [b - a for a, b in zip(value["rings"], value["rings"][1:])]
    ok = value["match"] and all(abs(g - value["beat"]) < 0.05 for g in gaps)
    # Positive control: rings shifted by half a beat do not match the kicks.
    shifted = [r + value["beat"] / 2 for r in value["rings"]]
    control = bool(shifted) and all(any(abs(h - r) < 1e-6 for h in value["hits"]) for r in shifted)
    return value, {"a ripple ring leaves the island stage on every kick": ok}, {"rings off the kick times are rejected": not control}


def verify_materials(engine):
    """C9.2: one sky function feeds the dome and the lake; B2: no nature mesh uses cityMat; every nature
    material compiled at load (C13.3)."""
    value = engine.evaluate("""() => {const v=window.__vc,r=v.rave,N=v.nature,chunk=r.skyGLSL||'';
      const water=N.materials.water.fragmentShader,sky=r.sky.material.fragmentShader;let city=0,total=0,compiled=0;
      N.group.traverse(o=>{if(!o.material)return;total++;if(o.material===v.cityMat)city++;if(v.renderer.properties.get(o.material).programs?.size)compiled++;});
      // The predicates the checks use, run on the live shaders and, as positive controls, on sabotaged copies.
      const skyUses=src=>chunk.length>0&&src.includes(chunk)&&/raveSky\\(/.test(src.replace(chunk,''));
      const waterUses=src=>chunk.length>0&&src.includes(chunk)&&/raveSky\\(R\\)/.test(src);
      return {chunk:chunk.includes('vec3 raveSky('),skyUses:skyUses(sky),waterUses:waterUses(water),city,total,compiled,
        waterWithoutChunk:waterUses(water.replace(chunk,'')),waterWithoutReflection:waterUses(water.replace(/raveSky\\(R\\)/g,'vec3(0.1)')),
        skyWithoutCall:skyUses(sky.replace('gl_FragColor=vec4(raveSky(','gl_FragColor=vec4(('))};}""")
    def safe_materials(row):
        return row["city"] == 0 and row["total"] > 0 and row["compiled"] == row["total"]

    checks = {"the lake reflects the same sky function as the dome": value["chunk"] and value["skyUses"] and value["waterUses"],
              "no nature mesh uses cityMat, all compiled at load": safe_materials(value)}
    return value, checks, {"a water shader without the shared chunk is rejected": not value["waterWithoutChunk"],
                           "a water shader that never reflects through raveSky(R) is rejected": not value["waterWithoutReflection"],
                           "a dome shader that never calls raveSky is rejected": not value["skyWithoutCall"],
                           "a nature mesh using cityMat fails the material gate": not safe_materials(dict(value, city=1)),
                           "an uncompiled nature material fails the material gate": not safe_materials(dict(value, compiled=value["total"] - 1))}


VIEW = """() => {const v=window.__vc,N=v.nature,L=N.lake,cam=v.camera,p=new cam.position.constructor();cam.updateMatrixWorld();
  let seen=0,total=0;for(let i=-10;i<=10;i++)for(let j=-10;j<=10;j++){const u=i/10*L.rx,w=j/10*L.ry;if((u/L.rx)**2+(w/L.ry)**2>=1)continue;total++;
    const ca=Math.cos(L.angle),sa=Math.sin(L.angle),x=L.cx+u*ca-w*sa,y=L.cy+u*sa+w*ca;p.set(x,L.y,-y).project(cam);if(p.z<1&&Math.abs(p.x)<1&&Math.abs(p.y)<1)seen++;}
  p.set(L.island.x,L.island.z,-L.island.y).project(cam);return {lakeInView:seen/total,island:[p.x,p.y,p.z]};}"""


def view_pass(view):
    x, y, z = view["island"]
    return view["lakeInView"] >= 0.3 and abs(x) < 0.6 and abs(y) < 0.6 and z < 1


def sound_on(engine):
    """Sound on and running (C13.3 measures with sound on); a page freshly loaded by reload() starts silent."""
    import qa_world as q
    if not engine.evaluate("() => window.__vc.audio.enabled"):
        engine.click("#sound")
    q.wait_audio(engine)


SOUND_WATCH = """() => {const v=window.__vc,w=window.__qaNatureSound={samples:0,off:0,low:0,done:false};
  function tick(){if(w.done)return;w.samples++;if(!v.audio.enabled||!v.beat.sound)w.off++;if(v.rave.uniforms.uSourceIntensity.value<.999)w.low++;requestAnimationFrame(tick);}
  requestAnimationFrame(tick);}"""


def sound_throughout(watch):
    """Every frame of the trace had the sound on and the rave source at full intensity."""
    return watch["samples"] > 0 and watch["off"] == 0 and watch["low"] == 0


def verify_s4(engine, path):
    """S4 (C13.3): the Reef shore, fixed camera on the sand looking over the lake, week 12, sound on, 60 s.
    Also measures the nature layer's own draw calls and triangles by hiding it for a frame at the same camera."""
    import qa_world as q
    sound_on(engine)
    engine.evaluate("() => window.__vc.updateWeek(12)")
    q.set_mode(engine, "overview")
    cam = engine.evaluate("() => window.__vc.nature.cameraS4()")
    q.settle_room(engine)
    engine.wait(12)
    engine.evaluate("() => window.__vc.nature.cameraS4()")
    wait_frames(engine, 3)
    view = engine.evaluate(VIEW)
    engine.screenshot(path("s4.png"))
    layer = engine.evaluate("""() => new Promise(resolve => {const v=window.__vc,N=v.nature,info=v.renderer.info.render,out={};
      const frames=(n,f)=>{let k=0;function g(){if(++k>=n)f();else requestAnimationFrame(g);}requestAnimationFrame(g);};
      frames(3,()=>{out.with={calls:info.calls,tris:info.triangles};N.group.visible=false;
        frames(3,()=>{out.without={calls:info.calls,tris:info.triangles};N.group.visible=true;
          let extras=0,partsTris=0;v.crowd.people.forEach((p,i)=>{if(p.lake&&v.crowd.isVisible(i,p))extras++;});
          for(const m of Object.values(v.crowd.parts))partsTris+=(m.geometry.index?m.geometry.index.count:m.geometry.attributes.position.count)/3;
          out.lakePeople=extras;out.trisPerPerson=partsTris;out.tier=v.tier.current;frames(3,()=>resolve(out));});});})""")
    engine.evaluate(q.FRAME_TRACE)
    q.wait_probe(engine, "() => window.__qaWorldFrames.done", 75)
    trace = engine.evaluate("() => window.__qaWorldFrames")
    path("s4-frames.json").write_text(json.dumps(trace), encoding="utf-8")
    metrics = q.summarize_frames(trace)
    tier_ok = bool(metrics["tiers"]) and all(t is not None and t >= 2 for t in metrics["tiers"])
    # Positive controls: known-bad metrics fail the same budget; a camera turned away fails the view check.
    bad_metrics = dict(metrics, fps=40.0, maxDrawCalls=400, maxTriangles=2_000_000)
    engine.evaluate("""() => {const v=window.__vc,N=v.nature,L=N.lake;v.controls.target.set(v.camera.position.x*2-N.lake.island.x,v.camera.position.y,v.camera.position.z*2+N.lake.island.y);v.controls.update();}""")
    wait_frames(engine, 2)
    away = engine.evaluate(VIEW)
    report = {"camera": cam, "view": view, "metrics": metrics, "layer": layer,
              "layerCalls": layer["with"]["calls"] - layer["without"]["calls"],
              "layerTriangles": layer["with"]["tris"] - layer["without"]["tris"],
              "lakePeopleTriangles": layer["lakePeople"] * layer["trisPerPerson"]}
    checks = {"S4 looks over the lake at the island stage": view_pass(view),
              "S4 perf budget (55 fps, p95 22 ms, max 100 ms, 320 calls, 1.5 M triangles, sound on)": q.perf_pass(metrics),
              "S4 settled tier at least 2": tier_ok}
    controls = {"budget fails on 40 fps, 400 calls, 2 M triangles": not q.perf_pass(bad_metrics),
                "view check fails with the camera turned away": not view_pass(away)}
    return report, checks, controls


def verify_s4_flash(engine, path):
    """C12.3 at S4: the lake mirrors the sky, so a room transition seen over the water must stay at 3 area
    flash pairs per second or fewer, Lights Full, with the sound on throughout (the page visitors see: silent,
    the rave source runs at half intensity)."""
    import qa_world as q
    sound_on(engine)
    engine.evaluate("() => {window.__vc.lights.setSetting('Full');window.__vc.nature.cameraS4();}")
    q.settle_room(engine)
    engine.wait(2)
    engine.evaluate(SOUND_WATCH)
    engine.evaluate(q.LUMINANCE_TRACE)
    engine.evaluate("() => {const a=window.__vc.audio;a.setRoom(a.room==='reef'?'working':'reef');}")
    q.wait_probe(engine, "() => window.__qaWorldFlash.done", 45)
    trace = engine.evaluate("""() => {const q=window.__qaWorldFlash;return {times:Array.from(q.times.subarray(0,q.count)),
      frames:Array.from({length:q.count},(_,i)=>Array.from(q.values.subarray(i*64*36,(i+1)*64*36),v=>v/1000000))};}""")
    watch = engine.evaluate("() => {const w=window.__qaNatureSound;w.done=true;return {samples:w.samples,off:w.off,low:w.low};}")
    path("s4-luminance.json").write_text(json.dumps(trace, separators=(",", ":")), encoding="utf-8")
    summary = q.flash_summary(trace)
    summary["sound"] = watch
    # Positive controls: the same counter on a synthetic 4 Hz full-frame flash; the same sound predicate on a
    # trace that lost the sound for a few frames.
    times = [i * 1000 / 30 for i in range(901)]
    frames = [[0.05 if (i // 4) % 2 else 0.6] * (64 * 36) for i in range(901)]
    control = q.flash_summary({"times": times, "frames": frames})
    return summary, {"S4 area flashes 3 per second or fewer across a transition": summary["measuredTracePass"],
                     "S4 flash trace ran with the sound on throughout": sound_throughout(watch)}, \
        {"a synthetic 4 Hz flash fails the counter": not control["measuredTracePass"],
         "a trace with the sound off for 3 frames fails the sound check": not sound_throughout(dict(watch, off=3, low=3))}


REDUCED = """() => new Promise(resolve => {const N=window.__vc.nature,kinds=['dog','pigeon','bat','fish','jelly','boat','partyBoat','capybara'];
  // The governor may change the tier meanwhile, so both snapshots cover the instances drawn at the start.
  const n=Object.fromEntries(kinds.map(k=>[k,N.meshes[k].count]));
  const snap=()=>{const out=[];for(const k of kinds)out.push(Array.from(N.meshes[k].instanceMatrix.array.slice(0,n[k]*16)));out.push(N.materials.water.uniforms.uTime.value);return JSON.stringify(out);};
  const a=snap();setTimeout(()=>resolve({same:a===snap()}),1500);})"""


def verify_reduced(engine):
    """B9: with prefers-reduced-motion every ambient nature motion holds still (instance buffers and the water
    clock unchanged over 1.5 s)."""
    engine.page.emulate_media(reduced_motion="reduce")
    reload(engine)
    engine.wait(2)
    still = engine.evaluate(REDUCED)
    engine.page.emulate_media(reduced_motion="no-preference")
    reload(engine)
    engine.wait(2)
    moving = engine.evaluate(REDUCED)
    return ({"reduced": still, "normal": moving}, {"reduced motion freezes nature": still["same"]},
            {"normal motion changes the same buffers": not moving["same"]})


def shore_offset(lake, t, g):
    """Layout point at ellipse parameter t, g along the outward normal (the true distance to the shore is g)."""
    a, b, c, s = lake["rx"], lake["ry"], math.cos(lake["angle"]), math.sin(lake["angle"])
    nu, nv = b * math.cos(t), a * math.sin(t)
    k = math.hypot(nu, nv)
    u, v = a * math.cos(t) + nu / k * g, b * math.sin(t) + nv / k * g
    return lake["cx"] + u * c - v * s, lake["cy"] + u * s + v * c


def surface_points(design):
    """Probe points round the lake with the answer C8.4 and C9.5 expect, in layout coordinates: 'water' and 'bank'
    must block (surfaceAt null; isWater only on water), 'sand' is a walkable height, 'ring' is the Reef ring's own
    (undefined, the ring answers), 'mouth' is the first step off the ring inside the rail opening (walkable, at the
    sidewalk height: nothing between the ring and the sand), 'railed' is the first step off the ring outside the
    opening (never walkable: the rail runs there)."""
    lake = design["lake"][0]
    shore, pier, isle = lake["shore"], lake["pier"], lake["island"]
    reef, rail, sand = shore["reef"], shore["rail"], shore["sand"]
    off_ring = lambda x, y, m: math.hypot(x - reef["x"], y - reef["y"]) > reef["outer"] + m
    off_pier = lambda x, y: seg_dist(x, y, pier["x0"], pier["y0"], pier["x1"], pier["y1"]) > pier["width"] / 2 + 0.05
    pts = []
    for k in range(180):
        t = k * math.tau / 180
        for g in (sand + 0.08, sand + 0.3, sand + 0.52):
            x, y = shore_offset(lake, t, g)
            if off_ring(x, y, 0.02):
                pts.append(("bank", x, y))
        for g in (-0.03, -0.3, -1.5):
            x, y = shore_offset(lake, t, g)
            if off_pier(x, y) and math.hypot(x - isle["x"], y - isle["y"]) > isle["r"] + BEACH + 0.05:
                pts.append(("water", x, y))
        for g in (0.15, 0.7, 1.25):
            x, y = shore_offset(lake, t, g)
            if off_ring(x, y, 0.0) and off_pier(x, y):
                pts.append(("sand", x, y))
    span = (rail["a1"] - rail["a0"]) % 360
    for k in range(144):
        a = k * 2.5
        into = (a - rail["a0"]) % 360
        x, y = reef["x"] + (reef["outer"] - 0.03) * math.cos(math.radians(a)), reef["y"] + (reef["outer"] - 0.03) * math.sin(math.radians(a))
        if off_pier(x, y):
            pts.append(("ring", x, y))
        x, y = reef["x"] + (reef["outer"] + 0.02) * math.cos(math.radians(a)), reef["y"] + (reef["outer"] + 0.02) * math.sin(math.radians(a))
        if 1.0 <= into <= span - 1.0 and off_pier(x, y):
            pts.append(("mouth", x, y))
        elif span + 3.0 <= into <= 357.0:
            pts.append(("railed", x, y))
    return pts


SURFACE = """(opts) => {const N=window.__vc.nature,R=opts.reef;
  // The live surface, and the two broken ones the positive controls feed through the same predicate: the first
  // prototype's (the bank answers undefined, so nothing stops a walker at the sand's edge) and one that closes
  // the rail opening (a strip of blocked ground just off the ring).
  const live=(x,z)=>N.surfaceAt(x,z);
  const variants={live,bankOpen:(x,z)=>{const s=live(x,z);return s===null&&!N.isWater(x,z)?undefined:s;},
    railClosed:(x,z)=>{const s=live(x,z),r=Math.hypot(x-R.x,-z-R.y);return typeof s==='number'&&r>R.outer&&r<R.outer+.3?null:s;},
    waterStrip:(x,z)=>{const s=live(x,z),g=N.shoreGap(x,-z);return s===null&&g<0&&g>=-.06?N.sandHeight(x,-z,0):s;}};
  const f=variants[opts.variant];
  return opts.points.map(([x,y])=>{const s=f(x,-y);return [s===undefined?'u':s===null?'n':s,s===null,N.isWater(x,-y)];});}"""

EXPLORE_SHORE = """(opts) => {const v=window.__vc,N=v.nature,E=v.explore.surfaces,original=N.surfaceAt;
  if(opts.breakLake)N.surfaceAt=()=>undefined;
  try{return opts.points.map(([kind,x,y])=>{const h=E.surfaceAt(x,-y),district=h===null?null:E.zoneAt(x,-y,h).district;
    return [kind,h,district];});}
  finally{N.surfaceAt=original;}}"""


def explore_shore_checks(points, answers):
    bad = []
    for (kind, x, y), (_, height, district) in zip(points, answers):
        ok = height is None if kind in ("water", "bank") else isinstance(height, (int, float)) and district == "reef"
        if not ok:
            bad.append([kind, round(x, 2), round(y, 2), height, district])
    return {"samples": len(points), "failures": bad[:8], "failureCount": len(bad)}, len(points) > 0 and not bad


def surface_checks(points, answers, reef_z):
    bad = {}
    for (kind, x, y), (s, blocked, water) in zip(points, answers):
        if kind == "water":
            ok = s == "n" and blocked and water
        elif kind == "bank":
            ok = s == "n" and blocked and not water
        elif kind == "sand":
            ok = isinstance(s, (int, float)) and not blocked and not water
        elif kind == "ring":
            ok = s == "u"
        elif kind == "mouth":
            ok = isinstance(s, (int, float)) and abs(s - reef_z) <= 0.03
        else:
            ok = not isinstance(s, (int, float))
        if not ok:
            bad.setdefault(kind, []).append([round(x, 2), round(y, 2), s])
    counts = {}
    for kind, *_ in points:
        counts[kind] = counts.get(kind, 0) + 1
    passed = all(counts.get(k, 0) > 0 for k in ("water", "bank", "sand", "ring", "mouth", "railed")) and not bad
    return {"probes": counts, "failures": {k: v[:6] for k, v in bad.items()}, "failureCounts": {k: len(v) for k, v in bad.items()}}, passed


def verify_surface(engine, design):
    """C8.4 and C9.5 for explore.js: water and the sand's outer bank (which drops to the void) block movement,
    the sand is walkable, and the Reef rail opening joins the ring to the sand at the sidewalk height with no gap,
    while the ring edge outside the opening meets no walkable ground (the rail runs there)."""
    lake = design["lake"][0]
    reef = lake["shore"]["reef"]
    pts = surface_points(design)
    probe = {"points": [[x, y] for _, x, y in pts], "reef": reef}
    report, ok = surface_checks(pts, engine.evaluate(SURFACE, dict(probe, variant="live")), reef["z"])
    _, bank_ok = surface_checks(pts, engine.evaluate(SURFACE, dict(probe, variant="bankOpen")), reef["z"])
    _, rail_ok = surface_checks(pts, engine.evaluate(SURFACE, dict(probe, variant="railClosed")), reef["z"])
    _, strip_ok = surface_checks(pts, engine.evaluate(SURFACE, dict(probe, variant="waterStrip")), reef["z"])
    walk_points = [(kind, x, y) for kind, x, y in pts if kind in ("water", "bank", "sand", "mouth")]
    pier, isle = lake["pier"], lake["island"]
    walk_points.extend((("pier", (pier["x0"] + pier["x1"]) / 2, (pier["y0"] + pier["y1"]) / 2),
                        ("island", isle["x"], isle["y"])))
    live_walk = engine.evaluate(EXPLORE_SHORE, {"points": walk_points, "breakLake": False})
    bad_walk = engine.evaluate(EXPLORE_SHORE, {"points": walk_points, "breakLake": True})
    walk_report, walk_ok = explore_shore_checks(walk_points, live_walk)
    _, bad_walk_ok = explore_shore_checks(walk_points, bad_walk)
    report["exploreShore"] = walk_report
    return report, {"water and the sand's outer bank block, the sand walks, the rail opening joins ring and sand": ok,
                    "explore walks the shore, pier and island but never the lake or bank": walk_ok}, \
        {"a surface whose bank answers undefined (the first prototype) fails": not bank_ok,
         "a surface that closes the rail opening fails": not rail_ok,
         "a surface that walks 0.03 inside the waterline fails": not strip_ok,
         "explore without the lake surface cannot walk the shore": not bad_walk_ok}


SHORE_MESH = """(opts) => {const N=window.__vc.nature,R=opts.reef,g=N.shore.geometry,p=g.attributes.position.array,m=N.shore.matrixWorld.elements;
  let inside=0,minR=1e9;
  for(let i=0;i<p.length;i+=3){const x=m[0]*p[i]+m[4]*p[i+1]+m[8]*p[i+2]+m[12],y=m[1]*p[i]+m[5]*p[i+1]+m[9]*p[i+2]+m[13],z=m[2]*p[i]+m[6]*p[i+1]+m[10]*p[i+2]+m[14];
    if(y<=R.z+opts.rise)continue;const r=Math.hypot(x-R.x,-z-R.y);minR=Math.min(minR,r);if(r<R.outer+opts.grow)inside++;}
  return {inside,minR};}"""


def verify_shore_mesh(engine, design):
    """C4.1 on the drawn shore (the bar's palapa and eaves, the fire, the hammocks, the pier's rails and lamps): no
    vertex of the shore mesh more than 0.1 above the Reef ring stands over the ring's road or walking lanes."""
    reef = design["lake"][0]["shore"]["reef"]
    value = engine.evaluate(SHORE_MESH, {"reef": reef, "rise": 0.1, "grow": 0.0})
    # Positive control: the same count with the ring's edge 0.3 further out (as if the bar stood 0.3 nearer) finds
    # the eave corner.
    control = engine.evaluate(SHORE_MESH, {"reef": reef, "rise": 0.1, "grow": 0.3})
    return {"elevatedInsideRing": value["inside"], "nearestElevatedToReefCentre": round(value["minR"], 3),
            "ringOuterEdge": reef["outer"], "controlInside": control["inside"]}, \
        {"the drawn shore stays off the Reef ring's road and walking lanes": value["inside"] == 0 and value["minR"] > reef["outer"]}, \
        {"the same test with the ring 0.3 wider catches the bar's eave": control["inside"] > 0}


OVERVIEW = """(opts) => {const v=window.__vc,cam=v.camera,p=new cam.position.constructor();
  if(opts.reset){if(v.state.ride>=0)v.stopRide();v.setIsolate(null);v.placeCamera();}
  cam.updateMatrixWorld();
  return opts.rings.map(ring=>{let seen=0;for(const [x,y] of ring){p.set(x+opts.shift,opts.y,-y).project(cam);if(p.z<1&&Math.abs(p.x)<=1&&Math.abs(p.y)<=1)seen++;}return seen/ring.length;});}"""


def verify_overview(engine, design):
    """B4 with C9.1: the landing overview frames the notes' bounds and the lake. The whole waterline and at least
    90 % of the sand's outer edge are on screen."""
    lake = design["lake"][0]
    rings = [[shore_offset(lake, k * math.tau / 96, g) for k in range(96)] for g in (0.0, lake["shore"]["sand"])]
    seen = engine.evaluate(OVERVIEW, {"rings": rings, "y": lake["z"], "shift": 0, "reset": True})
    shifted = engine.evaluate(OVERVIEW, {"rings": rings, "y": lake["z"], "shift": 12, "reset": False})
    passes = lambda s: s[0] >= 1.0 and s[1] >= 0.9
    return {"waterlineInView": seen[0], "sandEdgeInView": seen[1], "shifted12": shifted}, \
        {"the landing overview shows the whole lake": passes(seen)}, \
        {"the same lake 12 units further east fails the framing check": not passes(shifted)}


def browser_gates(parts, url=URL, prefix="b-v7-fast"):
    from qa_browser import Engine
    OUT.mkdir(exist_ok=True)
    path = lambda name: OUT / (prefix + "-" + name)
    design = json.loads(DESIGN.read_text(encoding="utf-8"))
    lake = design["lake"][0]
    out = {}
    with Engine(width=1440, height=900, timeout=90) as engine:
        engine.goto(url)
        engine.ready()
        engine.wait(2)
        if "browser" in parts:
            for name, fn in (("overview", lambda: verify_overview(engine, design)), ("surface", lambda: verify_surface(engine, design)),
                             ("shoreMesh", lambda: verify_shore_mesh(engine, design)),
                             ("materials", lambda: verify_materials(engine)), ("kickRings", lambda: verify_kick_rings(engine)),
                             ("census", lambda: verify_census(engine)), ("flocks", lambda: verify_flocks(engine)),
                             ("water", lambda: verify_no_water_walkers(engine, lake)), ("boats", lambda: verify_boats(engine, lake)),
                             ("behaviours", lambda: verify_behaviours(engine)), ("dogChase", lambda: verify_dog_chase(engine))):
                print("V7 gate:", name, flush=True)
                rep, chk, ctl = fn()
                out[name] = {"report": rep, "checks": chk, "controls": ctl}
                engine.wait(1)
        if "s4" in parts:
            print("V7 gate: S4 scene, 60 s, sound on", flush=True)
            rep, chk, ctl = verify_s4(engine, path)
            out["s4"] = {"report": rep, "checks": chk, "controls": ctl}
            print("V7 gate: S4 flash, 30 s", flush=True)
            rep, chk, ctl = verify_s4_flash(engine, path)
            out["s4Flash"] = {"report": rep, "checks": chk, "controls": ctl}
        if "browser" in parts:
            print("V7 gate: reduced motion", flush=True)
            rep, chk, ctl = verify_reduced(engine)
            out["reduced"] = {"report": rep, "checks": chk, "controls": ctl}
        out["pageErrors"] = engine.errors[:10]
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("parts", nargs="*", help="data, browser, s4, or all")
    parser.add_argument("--url", default=URL)
    parser.add_argument("--prefix", default="b-v7-fast")
    args = parser.parse_args()
    parts = args.parts or ["data"]
    if "all" in parts:
        parts = ["data", "browser", "s4"]
    if any(part not in ("data", "browser", "s4") for part in parts):
        parser.error("parts must be data, browser, s4, or all")
    if not args.prefix or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for char in args.prefix):
        parser.error("--prefix must contain only letters, digits, hyphens or underscores")
    out = {}
    if "data" in parts:
        out.update(data_gates())
    if "browser" in parts or "s4" in parts:
        out.update(browser_gates(parts, args.url, args.prefix))
    OUT.mkdir(exist_ok=True)
    report_path = OUT / (args.prefix + "-nature-report.json")
    previous = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
    previous.update(out)
    report_path.write_text(json.dumps(previous, indent=1), encoding="utf-8")
    for name, part in out.items():
        if not isinstance(part, dict) or "checks" not in part:
            continue
        for label, ok in part["checks"].items():
            print(("PASS " if ok else "FAIL ") + name + ": " + label)
        for label, ok in part["controls"].items():
            print(("CONTROL OK   " if ok else "CONTROL FAIL ") + name + ": " + label)
    if out.get("pageErrors"):
        print("page errors:", out["pageErrors"])
    passed = not out.get("pageErrors") and all(
        all(part[key].values()) for part in out.values() if isinstance(part, dict) and "checks" in part
        for key in ("checks", "controls"))
    print("nature gates:", "PASS" if passed else "FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
