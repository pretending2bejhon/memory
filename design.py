"""Shared architecture and collision-cleared streets for Blender and the viewer.

Runs the whole C4.1 placement order, deterministic and recomputed on every build: routes, the
Archive east rim road (C6.2), bridges (C6.1, C6.3), the Reef lake with its pier and island (C9.1,
C9.4), then stages, venues and furniture, and a trees hook for V7 (C10.2). It also emits the road
graph for traffic (C5.4) and the tour path (C6.6). Only the existing anonymous export is used.
When the bridges leave a district no stage slot (the Compass, whose three spokes take the only three
gaps between its neighbours), a deck slot is reserved there and the bridges are solved again around
it; `python design.py --report <path>` writes a side report with the reservation and every slot tried.

Accepted deviations from C6.3 (its rules cannot all hold on this layout; each is the smallest change
that keeps every C6.7 gate):
- Arch lift: 0.08 x span cannot sit under the 12 % grade limit, so the lift is capped: the largest
  lift that keeps the steepest grade at 11.5 % and the deck's vertical curvature at 0.14 per unit.
- Clipped smoothstep on the two diagonal spokes (clip 0.686 and 0.343): with a pure smoothstep the
  North-east spoke only fits inside 40 degrees by running on top of the Works ring.
- A 60 degree attach window on four near-touching pairs (Library to Signal Row, Works to Dome, Gate
  to Library, Prasma Campus to Reef), whose rings are 1.0 to 1.3 apart; every other bridge keeps 40.
- Radial stubs: each bridge is a straight radial stub, the searched cubic and another stub; the stubs
  carry the T-junction fillets.
- Six Archive rim links join the three inner avenues to the rim, so the road graph is one component.

The page data leaves out what the viewer rebuilds, the same way viewer/roads.js and qa_design.py do:
the graph's turn arcs from their fillets and the tour polyline from its graph steps (see publish()).
"""
import bisect
import heapq
import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "city-design.json"
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

# ------------------------------------------------------------------ Run B constants (C6, C9)
ROAD_HALF = 0.44              # ring carriageway half width: the rings' 0.88 road
SIDEWALK = 0.13               # ring sidewalk strip: the viewer draws width + .26
EDGE = ROAD_HALF + SIDEWALK   # 0.57, outer edge of a ring or bridge sidewalk
AV_HALF = 0.27                # Archive avenue half width: the 0.54 road
AV_EDGE = AV_HALF + SIDEWALK  # 0.40
FILLET_R = 0.9                # C6.3: fillet arcs of radius 0.9 or more
TURN_R = FILLET_R + ROAD_HALF  # centreline radius of a turn through a fillet
GRADE_MAX = 0.12              # C6.3
GRADE_LIFT = 0.115            # the arch lift is sized so the steepest grade stays at or under this
LIFT_RATIO = 0.08             # C6.3 arch lift ceiling, 0.08 x span
SEP_H, SEP_V = 0.5, 0.6       # C6.3: 0.5 horizontally or 0.6 vertically (an overpass)
FOOT_CLEAR = 0.20             # C6.3: the street check of build_design
MARGIN = 0.01                 # solver margin, so a 0.2-spaced polyline re-check still passes
PLAN_R_MIN = 0.95             # tightest plan radius on a bridge span: its inner carriageway edge stays at
                              # 0.51 or more, above the 0.43 of the Archive corners (0.7 centreline, 0.54 road)
VCURV_MAX = 0.14              # the arch lift never pushes the deck's vertical curvature past this (per unit,
                              # a crest radius of 7.1); a short span gets a small lift instead of a speed bump
EASE_MIN = 1.0                # a clipped smoothstep keeps at least this much vertical easing at each end
GRADE_SOLVE = GRADE_MAX - 0.002  # rounding room for the 0.2-spaced published polyline
ANGLE_WINDOW, ANGLE_STEP = 40, 5
# Fallback attach windows, tried only when a bridge has no candidate inside the C6.3 40 degrees.
WINDOWS = (40, 60, 75, 90)
HANDLES = (0.3, 0.4, 0.5, 0.6)
RIM_STEP = 1.0                # attach spacing along the straight Archive rim road
OWN_EXEMPT = 1.9              # a bridge meets its own ring inside this arc length of each end
JUNCTION_GAP = 1.0            # free ring between two junction fillets on one ring
RIM_CORNER = 1.5              # corner radius where the rim road meets the north and south rim links
SAMPLE = 0.1                  # C6.7 sampling step
LAKE_A, LAKE_B = 9.0, 6.0     # C9.1 semi-axes
LAKE_RING, LAKE_BRIDGE = 1.5, 1.0
LAKE_Z = 0.25                 # water level; V7 owns the water, this is only the placement datum
PIER_W, PIER_L, ISLAND_R = 0.5, 5.0, 2.0
# C6.1, in table order: (from, to, name). Only the Memory Causeway has a name in the spec.
BRIDGES = [
    ("core", "episodic", "Memory Causeway"), ("core", "jhon", "North-east spoke"),
    ("core", "prasma", "South-east spoke"), ("episodic", "prospective", "Archive to Yards ramp"),
    ("episodic", "branding", "Archive to Signal Row"), ("semantic", "branding", "Library to Signal Row ramp"),
    ("procedural", "onebrain", "Works to Dome ramp"), ("procedural", "jhon", "Works to Hills"),
    ("procedural", "prospective", "Works to Yards"), ("semantic", "prasma", "Library to Prasma Campus ramp"),
    ("inbox", "semantic", "Gate to Library"), ("working", "jhon", "Downtown to Hills"),
    ("working", "reef", "Downtown to Reef"), ("prasma", "reef", "Prasma Campus to Reef"),
]
# C6.6 reference order as bridge traversals (index into BRIDGES, destination).
TOUR = [(0, "episodic"), (3, "prospective"), (8, "procedural"), (6, "onebrain"), (6, "procedural"),
        (7, "jhon"), (11, "working"), (12, "reef"), (13, "prasma"), (9, "semantic"), (10, "inbox"),
        (10, "semantic"), (5, "branding"), (4, "episodic"), (0, "core")]


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


def segment_project(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy or 1)))
    return math.hypot(px - ax - dx * t, py - ay - dy * t), t


# ------------------------------------------------------------------ geometry helpers (Run B)
def arc_points(cx, cy, r, a0, a1, step=0.1):
    """Points on a circular arc from angle a0 to a1 in degrees, both ends included."""
    n = max(2, math.ceil(abs(math.radians(a1 - a0)) * r / step))
    return [[cx + r * math.cos(math.radians(a0 + (a1 - a0) * j / n)),
             cy + r * math.sin(math.radians(a0 + (a1 - a0) * j / n))] for j in range(n + 1)]


def line_points(a, b, step=0.16):
    """Points from a (excluded) to b (included)."""
    n = max(1, math.ceil(math.dist(a, b) / step))
    return [[a[0] + (b[0] - a[0]) * j / n, a[1] + (b[1] - a[1]) * j / n] for j in range(1, n + 1)]


def cumulative(points, closed):
    s = [0.0]
    for i in range(1, len(points)):
        s.append(s[-1] + math.dist(points[i - 1][:2], points[i][:2]))
    if closed:
        s.append(s[-1] + math.dist(points[-1][:2], points[0][:2]))
    return s


def project_polyline(points, x, y, closed=True):
    """(distance, arc length) of the closest point of a polyline to (x, y)."""
    best, s, n = (math.inf, 0.0), 0.0, len(points)
    for i in range(n if closed else n - 1):
        a, b = points[i], points[(i + 1) % n]
        d, t = segment_project(x, y, a[0], a[1], b[0], b[1])
        length = math.dist(a[:2], b[:2])
        if d < best[0]:
            best = (d, s + t * length)
        s += length
    return best


def polyline_at(points, cum, s, closed=True):
    """Point (x, y) and unit direction at arc length s."""
    total = cum[-1]
    if closed:
        s %= total
    s = max(0.0, min(total, s))
    i = max(0, min(len(cum) - 2, bisect.bisect_right(cum, s) - 1))
    a, b = points[i], points[(i + 1) % len(points)]
    length = cum[i + 1] - cum[i] or 1e-9
    t = (s - cum[i]) / length
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t,
            (b[0] - a[0]) / length, (b[1] - a[1]) / length)


def wrap_deg(a):
    return (a + 180) % 360 - 180


class FootGrid:
    """Building boxes with the viewer's 0.57 overhang, bucketed on a 1-unit grid within `reach`."""

    def __init__(self, data, layout, buildings, reach=1.0):
        self.reach, self.cells = reach, {}
        zs = {d: p["z"] for d, p in layout["districts"].items()}
        for n in data["nodes"]:
            f = buildings[str(n["id"])]
            x, y = layout["pos"][str(n["id"])]
            hw, hd = f["w"] * 0.57, f["d"] * 0.57
            base = zs[n["district"]]
            box = (x, y, hw, hd, base, base + f["h"] * 1.08 + 0.14)
            for i in range(math.floor(x - hw - reach), math.floor(x + hw + reach) + 1):
                for j in range(math.floor(y - hd - reach), math.floor(y + hd + reach) + 1):
                    self.cells.setdefault((i, j), []).append(box)

    def dist(self, x, y):
        best = self.reach
        for bx, by, hw, hd, _, _ in self.cells.get((math.floor(x), math.floor(y)), ()):
            best = min(best, math.hypot(max(0.0, abs(x - bx) - hw), max(0.0, abs(y - by) - hd)))
        return best

    def blocked(self, x, y, z, r):
        """The viewer's pointBlocked with every building at full height."""
        for bx, by, hw, hd, base, top in self.cells.get((math.floor(x), math.floor(y)), ()):
            if base - 0.1 < z < top and abs(x - bx) < hw + r and abs(y - by) < hd + r:
                return True
        return False


class SegGrid:
    """Road centreline segments with height and edge half width, bucketed within `reach`."""

    def __init__(self, reach=1.8, cell=2.0):
        self.reach, self.cell, self.cells, self.segs = reach, cell, {}, []

    def add(self, owner, a, b, za, zb, half):
        seg = (owner, a[0], a[1], b[0], b[1], za, zb, half)
        self.segs.append(seg)
        c, r = self.cell, self.reach
        for i in range(math.floor((min(a[0], b[0]) - r) / c), math.floor((max(a[0], b[0]) + r) / c) + 1):
            for j in range(math.floor((min(a[1], b[1]) - r) / c), math.floor((max(a[1], b[1]) + r) / c) + 1):
                self.cells.setdefault((i, j), []).append(seg)

    def add_polyline(self, owner, points, z, half, closed=False, every=1):
        pts = points[::every] if every > 1 else list(points)
        if closed:
            pts = pts + [pts[0]]
        elif pts[-1] is not points[-1]:
            pts.append(points[-1])
        for a, b in zip(pts, pts[1:]):
            za = a[2] if len(a) > 2 else z
            zb = b[2] if len(b) > 2 else z
            self.add(owner, a, b, za, zb, half)

    def near(self, x, y):
        """The segments bucketed in the cell holding (x, y), in insertion order. Read only."""
        return self.cells.get((math.floor(x / self.cell), math.floor(y / self.cell)), ())


# ------------------------------------------------------------------ C6.2 the Archive east rim road
def archive_roads(layout, routes, data, buildings):
    """The rim road loop (sharing Memory boulevard's east side) and the rim links between avenues.

    The loop runs counterclockwise like every other route (the viewer puts lamps on the left of travel,
    so left must be the plateau side): from the fork J_S east along the south rim, north up the east rim
    road, west along the north rim to the fork J_N, then south on Memory boulevard's east side (the
    shared stretch, the boulevard's own asphalt) back to J_S.

    Returns (rim route, link streets, forks). A fork is a Y junction on an avenue side where a
    corner arc and a rim link both leave the same straight tangentially."""
    ep = layout["districts"]["episodic"]
    top, bot, r0 = ep["cy"] + ep["ry"] - 0.2, ep["cy"] - (ep["ry"] - 0.2), 0.7
    avenues = sorted((i for i, r in enumerate(routes) if r["district"] == "episodic"),
                     key=lambda i: min(p[0] for p in routes[i]["points"]))
    extent = {i: (min(p[0] for p in routes[i]["points"]), max(p[0] for p in routes[i]["points"]))
              for i in avenues}
    cums = {i: cumulative(routes[i]["points"], True) for i in avenues}

    def vertex_s(i, x, y):
        pts = routes[i]["points"]
        k = min(range(len(pts)), key=lambda j: math.dist(pts[j], (x, y)))
        assert math.dist(pts[k], (x, y)) < 1e-3, "fork is not a vertex of its avenue"
        return cums[i][k]

    boulevard = avenues[-1]
    xw = extent[boulevard][1]
    xe = ep["cx"] + ep["rx"] + 0.4
    pts = arc_points(xw + r0, bot + r0, r0, 180, 270)
    pts += line_points(pts[-1], [xe - RIM_CORNER, bot])
    pts += arc_points(xe - RIM_CORNER, bot + RIM_CORNER, RIM_CORNER, -90, 0)[1:]
    pts += line_points(pts[-1], [xe, top - RIM_CORNER])
    pts += arc_points(xe - RIM_CORNER, top - RIM_CORNER, RIM_CORNER, 0, 90)[1:]
    pts += line_points(pts[-1], [xw + r0, top])
    pts += arc_points(xw + r0, top - r0, r0, 90, 180)[1:]
    own_count = len(pts)
    pts += line_points(pts[-1], pts[0])[:-1]
    # Rounded once, here, so the shared stretch starts exactly at a published vertex (J_N).
    pts = [[round(x, 3), round(y, 3)] for x, y in pts]
    shared_from = cumulative(pts[:own_count], False)[-1]
    rim = {"name": "Archive east rim", "district": "episodic", "z": ep["z"] + 0.035, "points": pts,
           "kind": "rim", "width": 2 * ROAD_HALF, "sidewalk": SIDEWALK,
           "shared": [{"from": round(shared_from, 4), "to": round(cumulative(pts, True)[-1], 4),
                       "route": boulevard}]}
    j_north, j_south = (xw, top - r0), (xw, bot + r0)
    forks = [{"x": j_north[0], "y": j_north[1], "z": rim["z"], "at": [(boulevard, 0.0), ("rim", shared_from)]},
             {"x": j_south[0], "y": j_south[1], "z": rim["z"],
              "at": [(boulevard, vertex_s(boulevard, *j_south)), ("rim", 0.0)]}]
    streets = []
    for k in range(len(avenues) - 1):
        west, east = avenues[k], avenues[k + 1]
        xr, xl = extent[west][1], extent[east][0]
        for side, yy, sign in (("north", top, 1), ("south", bot, -1)):
            yc = yy - sign * r0
            link = arc_points(xr + r0, yc, r0, 180, 180 - sign * 90)
            link += line_points(link[-1], [xl - r0, yy])
            link += arc_points(xl - r0, yc, r0, 90 * sign, 0)[1:]
            a, b = (xr, yc), (xl, yc)
            fa = {"x": a[0], "y": a[1], "z": rim["z"], "at": [(west, vertex_s(west, *a))]}
            fb = {"x": b[0], "y": b[1], "z": rim["z"], "at": [(east, vertex_s(east, *b))]}
            forks += [fa, fb]
            streets.append({"name": f"Archive {side} link {k + 1}", "district": "episodic", "z": rim["z"],
                            "kind": "link", "width": 2 * AV_HALF, "sidewalk": SIDEWALK, "points": link,
                            "fork": [len(forks) - 2, len(forks) - 1]})
    for road in [rim] + streets:
        # Measured to the nearest footprint (the grid search reaches 8 units or more), not a bound.
        clear = [footprint_distance(p[0], p[1], data, buildings, layout) for p in road["points"]]
        if not math.isfinite(min(clear)):
            raise ValueError(f"No building within reach of {road['name']}: clearance is unmeasured")
        if min(clear) < FOOT_CLEAR:
            raise ValueError(f"Unsafe street: {road['name']} clearance={min(clear):.3f}")
        road["clearance"] = round(min(clear), 3)
        if road is rim:
            own = [c for c, s in zip(clear, cumulative(pts, False)) if s <= shared_from + 1e-6]
            road["clearanceOwn"] = round(min(own), 3)
        road["points"] = [[round(x, 3), round(y, 3)] for x, y in road["points"]]
    return rim, streets, forks


# ------------------------------------------------------------------ C6.1 and C6.3 bridges
def rng_edges(layout):
    """Relative neighbourhood graph on rim-to-rim gaps (the C6.1 derivation)."""
    D = layout["districts"]

    def gap(a, b):
        p, q = D[a], D[b]
        if p["shape"] == "rect":
            p, q = q, p
        if q["shape"] == "rect":
            dx = max(0, abs(p["cx"] - q["cx"]) - q["rx"])
            dy = max(0, abs(p["cy"] - q["cy"]) - q["ry"])
            return math.hypot(dx, dy) - p["rx"]
        return math.hypot(p["cx"] - q["cx"], p["cy"] - q["cy"]) - p["rx"] - q["rx"]
    keys, out = list(D), []
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            g = gap(a, b)
            if all(max(gap(a, c), gap(b, c)) >= g for c in keys if c not in (a, b)):
                out.append((a, b, round(g, 2)))
    return out


def ring_desc(district, layout, routes, rim_index):
    p = layout["districts"][district]
    if p["shape"] == "disc":
        ri = next(i for i, r in enumerate(routes) if r["district"] == district)
        return {"district": district, "kind": "disc", "cx": p["cx"], "cy": p["cy"],
                "R": p["rx"] + (0.75 if district == "onebrain" else 0.4), "z": p["z"] + 0.035, "route": ri}
    top, bot = p["cy"] + p["ry"] - 0.2, p["cy"] - (p["ry"] - 0.2)
    room = RIM_CORNER + TURN_R + 0.1
    return {"district": district, "kind": "line", "cx": p["cx"], "cy": p["cy"], "x": p["cx"] + p["rx"] + 0.4,
            "ylo": bot + room, "yhi": top - room, "z": p["z"] + 0.035, "route": rim_index}


def ring_offset(ring, x, y):
    """Signed horizontal distance from a ring centreline, positive on the void side."""
    if ring["kind"] == "disc":
        return math.hypot(x - ring["cx"], y - ring["cy"]) - ring["R"]
    return x - ring["x"]


def pinch_angle(ring, other, layout):
    """Direction from a district's centre to its rim point closest to the other district."""
    p, q = layout["districts"][ring["district"]], layout["districts"][other]
    if p["shape"] == "disc":
        if q["shape"] == "disc":
            tx, ty = q["cx"], q["cy"]
        else:
            tx = min(max(p["cx"], q["cx"] - q["rx"]), q["cx"] + q["rx"])
            ty = min(max(p["cy"], q["cy"] - q["ry"]), q["cy"] + q["ry"])
        return math.degrees(math.atan2(ty - p["cy"], tx - p["cx"]))
    tx = min(max(q["cx"], p["cx"] - p["rx"]), p["cx"] + p["rx"])
    ty = min(max(q["cy"], p["cy"] - p["ry"]), p["cy"] + p["ry"])
    return math.degrees(math.atan2(ty - p["cy"], tx - p["cx"]))


def attach_points(ring, phi, window=ANGLE_WINDOW):
    """C6.3 attach candidates: (x, y, nx, ny, offset from the pinch direction in degrees)."""
    out = []
    if ring["kind"] == "disc":
        for k in range(-window // ANGLE_STEP, window // ANGLE_STEP + 1):
            th = math.radians(phi + k * ANGLE_STEP)
            out.append((ring["cx"] + ring["R"] * math.cos(th), ring["cy"] + ring["R"] * math.sin(th),
                        math.cos(th), math.sin(th), k * ANGLE_STEP))
        return out
    count = int((ring["yhi"] - ring["ylo"]) / RIM_STEP)
    for i in range(count + 1):
        y = ring["ylo"] + i * RIM_STEP
        off = wrap_deg(math.degrees(math.atan2(y - ring["cy"], ring["x"] - ring["cx"])) - phi)
        if abs(off) <= window:
            out.append((ring["x"], y, 1.0, 0.0, round(off, 2)))
    return out


_GL = [(0.5 - 0.4530899229693320, 0.1184634425280945), (0.5 - 0.2692346550528416, 0.2393143352496832),
       (0.5, 0.2844444444444444), (0.5 + 0.2692346550528416, 0.2393143352496832),
       (0.5 + 0.4530899229693320, 0.1184634425280945)]


def bez(P, t):
    u = 1 - t
    a, b, c, d = u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t
    return (a * P[0] + b * P[2] + c * P[4] + d * P[6], a * P[1] + b * P[3] + c * P[5] + d * P[7])


def bez_d(P, t):
    u = 1 - t
    a, b, c = 3 * u * u, 6 * u * t, 3 * t * t
    return (a * (P[2] - P[0]) + b * (P[4] - P[2]) + c * (P[6] - P[4]),
            a * (P[3] - P[1]) + b * (P[5] - P[3]) + c * (P[7] - P[5]))


# bez_d's three weights at each Gauss-Legendre node, computed once (the same operations bez_d does).
_GLD = [(3 * (1 - t) * (1 - t), 6 * (1 - t) * t, 3 * t * t, w) for t, w in _GL]


def bez_length(P):
    dx1, dx2, dx3 = P[2] - P[0], P[4] - P[2], P[6] - P[4]
    dy1, dy2, dy3 = P[3] - P[1], P[5] - P[3], P[7] - P[5]
    return sum(w * math.hypot(a * dx1 + b * dx2 + c * dx3, a * dy1 + b * dy2 + c * dy3) for a, b, c, w in _GLD)


def bez_min_radius(P, n=32, floor=0.0):
    """Smallest plan radius of a cubic, sampled; stops early once it drops under `floor`."""
    best = math.inf
    for i in range(n + 1):
        t = i / n
        dx, dy = bez_d(P, t)
        u = 1 - t
        ddx = 6 * u * (P[4] - 2 * P[2] + P[0]) + 6 * t * (P[6] - 2 * P[4] + P[2])
        ddy = 6 * u * (P[5] - 2 * P[3] + P[1]) + 6 * t * (P[7] - 2 * P[5] + P[3])
        speed = math.hypot(dx, dy)
        cross = abs(dx * ddy - dy * ddx)
        if cross > 1e-12:
            best = min(best, speed ** 3 / cross)
            if best < floor:
                return best
    return best


def bridge_sample(P, ta, tb, length, step=SAMPLE):
    """Uniform arc-length samples (spacing <= step) of stub + cubic + stub: xs, ys, s, left normals.
    ta and tb are the T points on the two rings; P runs from the end of stub A to the end of stub B."""
    n = max(40, int(length / 0.05) + 1)
    head = [(ta[0] + (P[0] - ta[0]) * j / 40, ta[1] + (P[1] - ta[1]) * j / 40) for j in range(40)]
    tail = [(P[6] + (tb[0] - P[6]) * j / 40, P[7] + (tb[1] - P[7]) * j / 40) for j in range(1, 41)]
    dense = head + [bez(P, i / n) for i in range(n + 1)] + tail
    n = len(dense) - 1
    cum = [0.0]
    for a, b in zip(dense, dense[1:]):
        cum.append(cum[-1] + math.dist(a, b))
    L = cum[-1]
    m = max(2, math.ceil(L / step))
    xs, ys, ss = [], [], []
    j = 0
    for k in range(m + 1):
        s = L * k / m
        while j < n - 1 and cum[j + 1] < s:
            j += 1
        t = (s - cum[j]) / ((cum[j + 1] - cum[j]) or 1e-12)
        xs.append(dense[j][0] + (dense[j + 1][0] - dense[j][0]) * t)
        ys.append(dense[j][1] + (dense[j + 1][1] - dense[j][1]) * t)
        ss.append(s)
    nx, ny = [], []
    for k in range(m + 1):
        a, b = max(0, k - 1), min(m, k + 1)
        dx, dy = xs[b] - xs[a], ys[b] - ys[a]
        length = math.hypot(dx, dy) or 1e-12
        nx.append(-dy / length)
        ny.append(dx / length)
    return xs, ys, ss, nx, ny


def ease_area(c):
    """Area under min(6u(1-u), c) on [0, 1] and the knee u1 where the smoothstep slope reaches c."""
    if c >= 1.5:
        return 1.0, 0.5
    u1 = (1 - math.sqrt(1 - 2 * c / 3)) / 2
    return 2 * (3 * u1 * u1 - 2 * u1 ** 3) + c * (1 - 2 * u1), u1


def ease(u, c):
    """Smoothstep (c = 1.5) or the smoothstep with its slope clipped at c, rescaled to end at 1.
    Both are C1 with zero slope at the ends; clipping lowers the steepest grade toward the mean."""
    if c >= 1.5:
        return u * u * (3 - 2 * u)
    area, u1 = ease_area(c)
    if u <= u1:
        return (3 * u * u - 2 * u ** 3) / area
    if u >= 1 - u1:
        v = 1 - u
        return 1 - (3 * v * v - 2 * v ** 3) / area
    return (3 * u1 * u1 - 2 * u1 ** 3 + c * (u - u1)) / area


def ease_slope(u, c):
    area, _ = ease_area(c)
    return min(6 * u * (1 - u), c) / area


def ease_for(dz, span, grade):
    """Largest clip c whose steepest grade stays at or under `grade`; None when even c = 0.05 fails."""
    if abs(dz) * 1.5 / span <= grade:
        return 1.5
    peak = lambda c: abs(dz) * c / ease_area(c)[0] / span
    if peak(0.05) > grade:
        return None
    lo, hi = 0.05, 1.5
    for _ in range(40):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if peak(mid) <= grade else (lo, mid)
    return lo


def deck_height(s, L, sa, sb, za, zb, lift, c=1.5):
    """C6.3: flat junction zones at ring height, the smoothstep between them plus a sin^2 arch lift."""
    if s <= sa:
        return za
    if s >= L - sb:
        return zb
    u = (s - sa) / (L - sa - sb)
    return za + (zb - za) * ease(u, c) + lift * math.sin(math.pi * u) ** 2


_US = [i / 100 for i in range(101)]
_ARCH = [math.pi * math.sin(2 * math.pi * u) for u in _US]
_BEND = [2 * math.pi * math.pi * math.cos(2 * math.pi * u) for u in _US]


def ease_bend(u, c):
    """Second derivative of ease(u, c) in u."""
    if c >= 1.5:
        return 6 - 12 * u
    area, u1 = ease_area(c)
    if u <= u1:
        return (6 - 12 * u) / area
    if u >= 1 - u1:
        return -(6 - 12 * (1 - u)) / area
    return 0.0


def vertical_curvature(dz, span, lift, c=1.5):
    """Largest |d2z/ds2| of the eased profile plus the sin^2 arch lift over a span."""
    return max(abs(dz * ease_bend(u, c) + lift * w) for u, w in zip(_US, _BEND)) / (span * span)


def arch_lift(dz, span, grade=GRADE_LIFT, c=1.5):
    """Largest lift up to LIFT_RATIO x span whose steepest grade stays at or under `grade` and whose
    vertical curvature stays at or under VCURV_MAX (or the lift-free profile's own, if that is higher)."""
    slope = [dz * ease_slope(u, c) for u in _US]
    bend_cap = max(VCURV_MAX, vertical_curvature(dz, span, 0.0, c))

    def ok(a):
        return (max(abs(g + a * w) for g, w in zip(slope, _ARCH)) / span <= grade
                and vertical_curvature(dz, span, a, c) <= bend_cap)
    hi = LIFT_RATIO * span
    if not ok(0):
        return 0.0
    if ok(hi):
        return hi
    lo = 0.0
    for _ in range(18):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if ok(mid) else (lo, mid)
    return lo


def fillets_at(ring, tx, ty, nx, ny, travel):
    """C6.3 T-junction fillets on a straight radial stub leaving the ring at (tx, ty) along (nx, ny).

    Each fillet is a FILLET_R arc tangent to the ring's carriageway edge and the stub's carriageway
    edge. travel is +1 at end A (the bridge runs along n) and -1 at end B; side +1 is the left of the
    A-to-B direction, so both ends label their fillets the same way."""
    d = TURN_R
    s_star = math.sqrt((ring["R"] + d) ** 2 - d * d) - ring["R"] if ring["kind"] == "disc" else d
    lx, ly = (-ny, nx) if travel > 0 else (ny, -nx)
    bx, by = tx + s_star * nx, ty + s_star * ny
    out = []
    for side in (1, -1):
        fx, fy = bx + side * d * lx, by + side * d * ly
        be = (bx + side * ROAD_HALF * lx, by + side * ROAD_HALF * ly)
        if ring["kind"] == "disc":
            ux, uy = fx - ring["cx"], fy - ring["cy"]
            ul = math.hypot(ux, uy)
            ux, uy = ux / ul, uy / ul
            rc = (ring["cx"] + ux * ring["R"], ring["cy"] + uy * ring["R"])
            re = (ring["cx"] + ux * (ring["R"] + ROAD_HALF), ring["cy"] + uy * (ring["R"] + ROAD_HALF))
        else:
            rc, re = (ring["x"], fy), (ring["x"] + ROAD_HALF, fy)
        a_ring = math.degrees(math.atan2(re[1] - fy, re[0] - fx))
        a_bridge = a_ring + wrap_deg(math.degrees(math.atan2(be[1] - fy, be[0] - fx)) - a_ring)
        out.append({"side": side, "cx": fx, "cy": fy, "r": FILLET_R, "a0": a_ring, "a1": a_bridge,
                    "ring": re, "bridge": be, "ringPoint": rc, "bridgePoint": (bx, by), "bridgeS": s_star,
                    "arc": arc_points(fx, fy, FILLET_R, a_ring, a_bridge, 0.1)})
    return out


def turn_arc(f):
    """Centreline of the turn through a published fillet: radius r + half the road, 0.1 steps."""
    return arc_points(f["cx"], f["cy"], f["r"] + ROAD_HALF, f["a0"], f["a1"], 0.1)


def junction_halfspan(ring):
    """Ring arc length from a T point to either fillet's ring tangency."""
    d = TURN_R
    if ring["kind"] == "disc":
        s_star = math.sqrt((ring["R"] + d) ** 2 - d * d) - ring["R"]
        return ring["R"] * math.atan2(d, ring["R"] + s_star)
    return d


class BridgeSolver:
    def __init__(self, data, layout, buildings, routes, streets, rim_index):
        self.data, self.layout, self.buildings, self.routes = data, layout, buildings, routes
        self.rim_index = rim_index
        self.feet = FootGrid(data, layout, buildings)
        self.grid = SegGrid()
        self.route_cum = [cumulative(r["points"], True) for r in routes]
        for i, r in enumerate(routes):
            half = r.get("width", 2 * AV_HALF if r["district"] == "episodic" else 2 * ROAD_HALF) / 2 + SIDEWALK
            pts = r["points"]
            if r.get("shared"):
                cut = r["shared"][0]["from"]
                pts = [p for p, s in zip(pts, self.route_cum[i]) if s <= cut + 1e-3]
                self.grid.add_polyline(("route", i), pts, r["z"], half, closed=False, every=2)
            else:
                self.grid.add_polyline(("route", i), pts, r["z"], half, closed=True, every=2)
        for k, st in enumerate(streets):
            self.grid.add_polyline(("street", k), st["points"], st["z"], AV_EDGE)
        self.spans = {}
        self.bridges = []
        self.plateaus = [(d, p["shape"] == "disc", p["cx"], p["cy"], p["rx"], p["ry"], p["rx"] ** 2)
                         for d, p in layout["districts"].items()]
        rim = routes[rim_index]
        ep = layout["districts"]["episodic"]
        # The rim road runs north up the east rim (counterclockwise), so s grows with y there.
        self.rim_bot = ep["cy"] - (ep["ry"] - 0.2) + RIM_CORNER
        self.rim_s0 = project_polyline(rim["points"], ep["cx"] + ep["rx"] + 0.4, self.rim_bot)[1]

    def route_s(self, ring, x, y):
        """Arc length of a T point on its ring route (analytic, for the junction spacing test)."""
        total = self.route_cum[ring["route"]][-1]
        if ring["kind"] == "disc":
            return (math.atan2(y - ring["cy"], x - ring["cx"]) % math.tau) / math.tau * total
        return self.rim_s0 + (y - self.rim_bot)

    def over_plateau(self, x, y):
        for d, disc, cx, cy, rx, ry, rx2 in self.plateaus:
            if disc:
                if (x - cx) ** 2 + (y - cy) ** 2 < rx2:
                    return d
            elif abs(x - cx) < rx and abs(y - cy) < ry:
                return d
        return None

    def span_free(self, route, lo, hi):
        total = self.route_cum[route][-1]
        for a, b in self.spans.get(route, ()):
            for shift in (-total, 0, total):
                if lo < b + shift + JUNCTION_GAP and hi > a + shift - JUNCTION_GAP:
                    return False
        return True

    def coarse_reject(self, A, B, P, L_est, za, zb, stubs, tier):
        """Certain rejections on a 0.5-spaced pass over the cubic, before any dense work.
        Tier 0 and 1: coming within the separation distance of another bridge rejects (a crossing).
        Tier 0 also rejects a deck that overlaps another road's paved band in plan (a stacked road)."""
        n = max(4, math.ceil((L_est - stubs[0] - stubs[1]) / 0.5))
        z_top = max(za, zb) + LIFT_RATIO * 0.5 * L_est
        span_len = L_est - stubs[0] - stubs[1]
        for i in range(n + 1):
            x, y = bez(P, i / n)
            if self.over_plateau(x, y):
                return "plateau"
            if self.feet.dist(x, y) < FOOT_CLEAR + MARGIN:
                return "footprint"
            s_est = stubs[0] + span_len * i / n
            for owner, ax, ay, bx, by, sza, szb, half in self.grid.near(x, y):
                dx, dy = bx - ax, by - ay
                t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy or 1)))
                d = math.hypot(x - ax - dx * t, y - ay - dy * t)
                if d >= EDGE + half + SEP_H + MARGIN:
                    continue
                if owner == ("route", A["route"]) and s_est < OWN_EXEMPT + 1.0:
                    continue
                if owner == ("route", B["route"]) and L_est - s_est < OWN_EXEMPT + 1.0:
                    continue
                if tier < 2 and owner[0] in ("bridge", "fillet"):
                    return "crossing"
                if tier == 0 and d < EDGE + half:
                    return "overlap"
                if z_top - (sza + (szb - sza) * t) < SEP_V + MARGIN:
                    return "separation"
        return None

    def evaluate(self, k, A, B, P, L_est, za, zb, clip, ta, tb, na, nb, stubs, spans, sample):
        """Dense C6.3 checks of one candidate. Returns the result dict, or the rejection reason.
        sample is bridge_sample(P, ta, tb, L_est), shared by both profile passes."""
        xs, ys, ss, nx, ny = sample
        L = ss[-1]
        fa, fb = fillets_at(A, ta[0], ta[1], na[0], na[1], 1), fillets_at(B, tb[0], tb[1], nb[0], nb[1], -1)
        sa, sb = stubs
        lv = L - sa - sb
        c = 1.5 if lv >= 1.0 and 1.5 * abs(zb - za) / lv <= GRADE_SOLVE else None
        if c is None and clip and lv >= 1.0:
            c = ease_for(zb - za, lv, GRADE_SOLVE)
            if c is not None and ease_area(c)[1] * lv < EASE_MIN:
                c = None
        if c is None:
            return "grade"
        # A fillet is valid only if the bridge never cuts back into its circle.
        lim = (TURN_R - 0.02) ** 2
        for f in fa + fb:
            fx, fy = f["cx"], f["cy"]
            for i in range(len(xs)):
                if (xs[i] - fx) ** 2 + (ys[i] - fy) ** 2 < lim:
                    return "fillet"
        lift = arch_lift(zb - za, lv, GRADE_LIFT, c)
        zs = [deck_height(s, L, sa, sb, za, zb, lift, c) for s in ss]
        steepest = max(abs(zs[i + 1] - zs[i]) / (ss[i + 1] - ss[i]) for i in range(len(ss) - 1))
        if steepest > GRADE_SOLVE:
            return "grade"
        # Plateaus, other rings, earlier bridges: 0.5 horizontally or 0.6 above (C6.3). An overpass
        # records its stretch on this bridge (from, to) and whether the deck overlaps the other road's
        # paved band in plan there (a stacked road: two walkable heights at one plan point).
        overpasses = {}
        for i in range(len(xs)):
            x, y, z, s = xs[i], ys[i], zs[i], ss[i]
            if self.over_plateau(x, y):
                return "plateau"
            for owner, ax, ay, bx, by, sza, szb, half in self.grid.near(x, y):
                dx, dy = bx - ax, by - ay
                t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy or 1)))
                d = math.hypot(x - ax - dx * t, y - ay - dy * t)
                if d >= EDGE + half + SEP_H + MARGIN:
                    continue
                if owner == ("route", A["route"]) and s < OWN_EXEMPT:
                    continue
                if owner == ("route", B["route"]) and L - s < OWN_EXEMPT:
                    continue
                dz_ = z - (sza + (szb - sza) * t)
                if dz_ >= SEP_V + MARGIN:
                    o = overpasses.setdefault(owner, {"clearance": 9.0, "from": s, "to": s, "overlap": False})
                    o["clearance"] = min(o["clearance"], round(dz_, 3))
                    o["from"], o["to"] = min(o["from"], s), max(o["to"], s)
                    o["overlap"] = o["overlap"] or d < EDGE + half
                    continue
                return "separation"
        for f, ring in [(f, A) for f in fa] + [(f, B) for f in fb]:
            for x, y in f["arc"]:
                for owner, ax, ay, bx, by, sza, szb, half in self.grid.near(x, y):
                    if owner == ("route", ring["route"]):
                        continue
                    d, t = segment_project(x, y, ax, ay, bx, by)
                    if d < half + SIDEWALK + SEP_H + MARGIN and ring["z"] - (sza + (szb - sza) * t) < SEP_V:
                        return "fillet-separation"
        # Footprints: the street check (0.20 from the centreline), then the ring-level QA points.
        # The walking lanes are tested on the sidewalk itself (0.48 out), where walkers go.
        clear = min(self.feet.dist(x, y) for x, y in zip(xs, ys))
        if clear < FOOT_CLEAR + MARGIN:
            return "footprint"
        lane = ROAD_HALF + 0.04
        for i in range(len(xs)):
            x, y, z = xs[i], ys[i], zs[i]
            if self.feet.blocked(x, y, z + 0.64, 0.14) or self.feet.blocked(x, y, z + 0.32, 0.14):
                return "camera"
            for side in (-1, 1):
                if self.feet.blocked(x + side * lane * nx[i], y + side * lane * ny[i], z + 0.18, 0.07):
                    return "lane"
        return {"xs": xs, "ys": ys, "zs": zs, "ss": ss, "nx": nx, "ny": ny, "L": L, "sa": sa, "sb": sb,
                "lift": lift, "clip": c, "grade": steepest, "fillets": (fa, fb), "spans": spans,
                "clear": clear, "overpasses": overpasses, "lv": lv}

    def candidates(self, A, B, pa, pb, stubs, need, lo, hi):
        """Stub + cubic candidates whose wider attach offset lies in (lo, hi]."""
        stub_a, stub_b = stubs
        zone = stub_a + stub_b
        out = []
        for ia, (tax, tay, anx, any_, aoff) in enumerate(pa):
            ax, ay = tax + stub_a * anx, tay + stub_a * any_
            for ib, (tbx, tby, bnx, bny, boff) in enumerate(pb):
                wide = max(abs(aoff), abs(boff))
                if not lo < wide <= hi + 1e-6:
                    continue
                bx, by = tbx + stub_b * bnx, tby + stub_b * bny
                span = math.hypot(bx - ax, by - ay)
                # Allow a ramp that swings back past its own stub, never a hairpin.
                if min((bx - ax) * anx + (by - ay) * any_, (ax - bx) * bnx + (ay - by) * bny) < -0.8 * span:
                    continue
                for ha in HANDLES:
                    for hb in HANDLES:
                        P = (ax, ay, ax + ha * span * anx, ay + ha * span * any_,
                             bx + hb * span * bnx, by + hb * span * bny, bx, by)
                        L = bez_length(P) + zone
                        if L >= need:
                            out.append((L, ia, ib, ha, hb, P, aoff, boff, span, (tax, tay), (tbx, tby),
                                        (anx, any_), (bnx, bny)))
        out.sort(key=lambda c: c[:5])
        return out

    def solve(self, k, a_key, b_key, name):
        A = ring_desc(a_key, self.layout, self.routes, self.rim_index)
        B = ring_desc(b_key, self.layout, self.routes, self.rim_index)
        za, zb = A["z"], B["z"]
        pa = attach_points(A, pinch_angle(A, b_key, self.layout), WINDOWS[-1])
        pb = attach_points(B, pinch_angle(B, a_key, self.layout), WINDOWS[-1])
        # Each end is a straight radial stub long enough to carry both fillets (the T-junction);
        # the span between the stub ends is the searched cubic.
        est = lambda ring: (math.sqrt((ring["R"] + TURN_R) ** 2 - TURN_R ** 2) - ring["R"]) if ring["kind"] == "disc" else TURN_R
        stubs = (round(est(A) + 0.1, 4), round(est(B) + 0.1, 4))
        zone = stubs[0] + stubs[1]
        need = abs(zb - za) / GRADE_MAX + zone
        strict = 1.5 * abs(zb - za) / GRADE_SOLVE + zone
        wa, wb = junction_halfspan(A), junction_halfspan(B)
        self.log = []
        # Order of preference. The attach window is outermost: it widens past the C6.3 40 degrees
        # (WINDOWS) only when nothing at all fits inside it. Inside a window, three tiers, each tried
        # in full before the next: tier 0 has no deck over another bridge and no deck overlapping
        # another road's paved band in plan (an overpass may still pass close by, 0.6 above); tier 1
        # lets a deck overlap a ring or link below it (a stacked road, two walkable heights at one plan
        # point, which the one-height surfaceAt of C8.4 cannot hold); tier 2 lets it cross another
        # bridge. Inside a tier the pure smoothstep is tried first, then the clipped one; inside a pass
        # the shortest candidate wins.
        memo, evals, plan_memo, samples = {}, {}, {}, {}
        prev = -1
        for window in WINDOWS:
            cands = self.candidates(A, B, pa, pb, stubs, need, prev, window)
            for tier in (0, 1, 2):
                for clip in (False, True):
                    self.stats = {"window": window, "pass": 2 if clip else 1, "tier": tier,
                                  "candidates": 0, "junction": 0, "curvature": 0, "plateau": 0,
                                  "footprint": 0, "crossing": 0, "overlap": 0, "separation": 0, "grade": 0,
                                  "fillet": 0, "fillet-separation": 0, "camera": 0, "lane": 0}
                    for L_est, ia, ib, ha, hb, P, aoff, boff, span, ta, tb, na, nb in cands:
                        if not clip and L_est < strict:
                            continue
                        if clip and L_est >= strict and 1.5 * abs(zb - za) / (L_est - zone) <= GRADE_SOLVE - 0.004:
                            continue  # pass 1 already judged this one with the exact smoothstep
                        self.stats["candidates"] += 1
                        sa_ = self.route_s(A, *ta)
                        sb_ = self.route_s(B, *tb)
                        spans = ((sa_ - wa, sa_ + wa), (sb_ - wb, sb_ + wb))
                        key = (window, ia, ib, ha, hb)
                        why = memo.get((tier, key))
                        if why is None:
                            # Plan-only rejections depend on neither the profile nor the tier, so
                            # pass 2 and the later tiers reuse them.
                            why = plan_memo.get(key)
                            if why is None:
                                if not self.span_free(A["route"], *spans[0]) or not self.span_free(B["route"], *spans[1]):
                                    why = "junction"
                                elif bez_min_radius(P, floor=PLAN_R_MIN) < PLAN_R_MIN:
                                    why = "curvature"
                                else:
                                    why = ""
                                plan_memo[key] = why
                            why = why or self.coarse_reject(A, B, P, L_est, za, zb, stubs, tier) or ""
                            memo[(tier, key)] = why
                        if why:
                            self.stats[why] += 1
                            continue
                        if (key, clip) not in evals:
                            if key not in samples:
                                samples[key] = bridge_sample(P, ta, tb, L_est)
                            evals[(key, clip)] = self.evaluate(k, A, B, P, L_est, za, zb, clip, ta, tb, na, nb,
                                                               stubs, spans, samples[key])
                        res = evals[(key, clip)]
                        if isinstance(res, str):
                            self.stats[res] += 1
                            continue
                        over = res["overpasses"]
                        if tier < 2 and any(o[0] in ("bridge", "fillet") for o in over):
                            self.stats["crossing"] += 1
                            continue
                        if tier == 0 and any(v["overlap"] for v in over.values()):
                            self.stats["overlap"] += 1
                            continue
                        res["window"], res["tier"] = window, tier
                        self.log.append(dict(self.stats))
                        return self.accept(k, A, B, name, P, res, aoff, boff, span, (ha, hb), stubs)
                    self.log.append(dict(self.stats))
            prev = window
        raise ValueError(f"No bridge fits between {a_key} and {b_key}: {self.log}")

    def accept(self, k, A, B, name, P, res, aoff, boff, span, handles, stubs):
        xs, ys, zs, ss = res["xs"], res["ys"], res["zs"], res["ss"]
        keep = list(range(0, len(xs), 2))
        if keep[-1] != len(xs) - 1:
            keep.append(len(xs) - 1)
        pts = [[round(xs[i], 3), round(ys[i], 3), round(zs[i], 4)] for i in keep]
        self.grid.add_polyline(("bridge", k), pts, 0, EDGE)
        fa, fb = res["fillets"]
        route_a, route_b = self.routes[A["route"]]["points"], self.routes[B["route"]]["points"]
        for f, ring, rp in [(f, A, route_a) for f in fa] + [(f, B, route_b) for f in fb]:
            self.grid.add_polyline(("fillet", k), [list(p) for p in f["arc"]], ring["z"], SIDEWALK)
            f["ringS"] = project_polyline(rp, *f["ringPoint"])[1]
        self.spans.setdefault(A["route"], []).append(res["spans"][0])
        self.spans.setdefault(B["route"], []).append(res["spans"][1])
        t_a = project_polyline(route_a, xs[0], ys[0])[1]
        t_b = project_polyline(route_b, xs[-1], ys[-1])[1]
        # Exact clearance for the record, every 0.1 sample (the solver's grid caps at 1.0).
        clear = res["clear"]
        if clear >= self.feet.reach:
            clear = min(footprint_distance(xs[i], ys[i], self.data, self.buildings, self.layout)
                        for i in range(len(xs)))
        L = res["L"]

        def land(ring, from_start):
            order = range(len(xs)) if from_start else range(len(xs) - 1, -1, -1)
            for i in order:
                if ring_offset(ring, xs[i], ys[i]) >= EDGE:
                    return round(ss[i] if from_start else L - ss[i], 3)
            return None

        def fillet(f, z):
            out = {"side": f["side"], "cx": round(f["cx"], 4), "cy": round(f["cy"], 4),
                   "r": f["r"], "a0": round(f["a0"], 3), "a1": round(f["a1"], 3),
                   "ring": [round(v, 4) for v in f["ring"]],
                   "bridge": [round(v, 4) for v in f["bridge"]],
                   "ringS": round(f["ringS"], 4), "bridgeS": round(f["bridgeS"], 4)}
            # The turn arc is rebuilt from the published (rounded) fillet, exactly as the viewer does.
            out["turn"] = [[x, y, z] for x, y in turn_arc(out)]
            return out

        def end(ring, fil, t_s, off, from_start, other):
            i = 0 if from_start else len(xs) - 1
            return {"district": ring["district"], "to": other, "route": ring["route"], "s": round(t_s, 4),
                    "x": round(xs[i], 4), "y": round(ys[i], 4), "z": round(ring["z"], 4),
                    "angle": off, "flat": round(res["sa"] if from_start else res["sb"], 4),
                    "land": land(ring, from_start),
                    "fillets": [fillet(f, round(ring["z"], 4)) for f in fil]}
        record = {"id": k, "name": name, "from": A["district"], "to": B["district"],
                  "spoke": A["district"] == "core", "length": round(L, 4), "chord": round(span, 4),
                  "width": 2 * ROAD_HALF, "sidewalk": SIDEWALK, "halfWidth": round(EDGE, 3),
                  "clearance": round(clear, 3), "maxGrade": round(res["grade"], 4), "lift": round(res["lift"], 4),
                  "vcurv": round(vertical_curvature(B["z"] - A["z"], res["lv"], res["lift"], res["clip"]), 4),
                  "window": res["window"], "tier": res["tier"],
                  "profile": {"kind": "smoothstep" if res["clip"] >= 1.5 else "clipped-smoothstep",
                              "clip": round(min(res["clip"], 1.5), 4)},
                  "search": self.log,
                  "handles": list(handles), "stubs": list(stubs),
                  "curve": [[round(P[j], 4), round(P[j + 1], 4)] for j in range(0, 8, 2)],
                  "split": round(L / 2, 4),
                  "overpasses": [{"kind": o[0], "index": o[1], "clearance": v["clearance"], "from": round(v["from"], 3),
                                  "to": round(v["to"], 3), "overlap": v["overlap"]}
                                 for o, v in sorted(res["overpasses"].items())],
                  "ends": [end(A, fa, t_a, aoff, True, B["district"]),
                           end(B, fb, t_b, boff, False, A["district"])],
                  "points": pts}
        self.bridges.append(record)
        return record


class NotClean(Exception):
    """A bridge of the district being reserved for left the 40 degree window or tier 0."""


def place_bridges(data, layout, buildings, routes, streets, rim_index, reserve=(), clean=None):
    """Solve the 14 bridges in C6.1 order. reserve: stage deck slots (district, x, y, r) every bridge
    keeps 0.5 from, like a ring. clean: a district whose bridges must all land inside the 40 degree
    window in tier 0, else NotClean is raised as soon as one does not (the slot search uses it)."""
    solver = BridgeSolver(data, layout, buildings, routes, streets, rim_index)
    for district, x, y, r in reserve:
        solver.grid.add(("stage", district), (x, y), (x + 1e-6, y), 100.0, 100.0, r)
    for k, (a, b, name) in enumerate(BRIDGES):
        rec = solver.solve(k, a, b, name)
        if clean in (a, b) and (rec["window"] > ANGLE_WINDOW or rec["tier"] > 0):
            raise NotClean(f"{name}: window {rec['window']}, tier {rec['tier']}")
    return solver.bridges


def stage_slots(district, layout, limit=12):
    """Deck slots for a district's stage that clear every other ring by 0.5 (C4.2), before any bridge.
    Ordered to leave the district's bridges their straightest lines: farthest (in angle) from the
    pinch directions of its C6.1 bridges first, then the widest ring gap, then the larger deck."""
    p = layout["districts"][district]
    if p["shape"] != "disc":
        return []
    ring = {"district": district, "kind": "disc"}
    pinches = [pinch_angle(ring, b if a == district else a, layout) for a, b, _ in BRIDGES if district in (a, b)]
    outer = ring_outer(district, p)
    r0 = max(1.2, min(2.4, 0.9 + 0.12 * p["rx"]))
    radii = [r0] + [round(r0 - 0.05 * k, 3) for k in range(1, 40) if r0 - 0.05 * k >= 1.2 - 1e-9]
    out = []
    for r in radii:
        for step in range(180):
            a = step * 2
            x = p["cx"] + math.cos(math.radians(a)) * (outer + r)
            y = p["cy"] + math.sin(math.radians(a)) * (outer + r)
            gap = min(math.hypot(x - q["cx"], y - q["cy"]) - ring_outer(o, q) - r
                      for o, q in layout["districts"].items() if o != district and q["shape"] == "disc")
            if gap < 0.5:
                continue
            spread = min(abs(wrap_deg(a - ph)) for ph in pinches) if pinches else 180
            out.append((-spread, -round(gap, 3), -r, a, x, y))
    out.sort()
    return [(district, x, y, -neg_r, a) for _, _, neg_r, a, x, y in out[:limit]]


# ------------------------------------------------------------------ C9.1 and C9.4 the Reef lake
def ellipse_local(lake, x, y):
    c, s = math.cos(lake["angle"]), math.sin(lake["angle"])
    dx, dy = x - lake["cx"], y - lake["cy"]
    return dx * c + dy * s, -dx * s + dy * c


def ellipse_boundary(lake, n=360):
    c, s = math.cos(lake["angle"]), math.sin(lake["angle"])
    out = []
    for i in range(n):
        t = i * math.tau / n
        u, v = lake["rx"] * math.cos(t), lake["ry"] * math.sin(t)
        out.append((lake["cx"] + u * c - v * s, lake["cy"] + u * s + v * c))
    return out


def ellipse_gap(lake, x, y, boundary):
    """Distance from a point to the water, negative inside."""
    u, v = ellipse_local(lake, x, y)
    inside = (u / lake["rx"]) ** 2 + (v / lake["ry"]) ** 2 < 1
    if not inside and math.hypot(x - lake["cx"], y - lake["cy"]) > lake["rx"] + 4:
        return math.hypot(x - lake["cx"], y - lake["cy"]) - lake["rx"]
    d = min(math.hypot(x - bx, y - by) for bx, by in boundary)
    return -d if inside else d


def ellipse_gap_exact(lake, x, y):
    """Exact distance from a point to the shore (negative inside): the nearest of 256 shore samples,
    then a ternary refinement of the shore parameter around it."""
    u, v = ellipse_local(lake, x, y)
    a, b = lake["rx"], lake["ry"]
    f = lambda t: (a * math.cos(t) - u) ** 2 + (b * math.sin(t) - v) ** 2
    t0 = min((i * math.tau / 256 for i in range(256)), key=f)
    lo, hi = t0 - math.tau / 256, t0 + math.tau / 256
    for _ in range(40):
        m1, m2 = lo + (hi - lo) / 3, hi - (hi - lo) / 3
        lo, hi = (lo, m2) if f(m1) < f(m2) else (m1, hi)
    d = math.sqrt(f((lo + hi) / 2))
    return -d if (u / a) ** 2 + (v / b) ** 2 < 1 else d


def lake_clearances(lake, routes, streets, bridges, skip_route):
    """Measured shore gaps: to the nearest other ring, avenue or link outer sidewalk edge, and to the
    nearest bridge deck sidewalk edge or fillet sidewalk curb. Branch and bound on the lower bound
    (distance to the lake centre - rx), exact distance for every point that could still be the nearest."""
    rings, decks = [], []
    for i, r in enumerate(routes):
        if i != skip_route:
            rings += [(x, y, route_half(r) + SIDEWALK) for x, y in own_points(r)]
    for st in streets:
        rings += [(x, y, st["width"] / 2 + SIDEWALK) for x, y in st["points"]]
    for b in bridges:
        decks += [(p[0], p[1], EDGE) for p in b["points"]]
        for e in b["ends"]:
            for f in e["fillets"]:
                decks += [(x, y, 0.0) for x, y in arc_points(f["cx"], f["cy"], f["r"] - SIDEWALK, f["a0"], f["a1"], 0.05)]

    def measure(pts):
        best = math.inf
        for lb, x, y, off in sorted((math.hypot(x - lake["cx"], y - lake["cy"]) - lake["rx"] - off, x, y, off)
                                    for x, y, off in pts):
            if lb >= best:
                break
            best = min(best, ellipse_gap_exact(lake, x, y) - off)
        return best
    return measure(rings), measure(decks)


def place_lake(data, layout, routes, streets, bridges):
    reef = layout["districts"]["reef"]
    pos = [layout["pos"][str(n["id"])] for n in data["nodes"]]
    gx, gy = sum(p[0] for p in pos) / len(pos), sum(p[1] for p in pos) / len(pos)
    base = math.atan2(reef["cy"] - gy, reef["cx"] - gx)
    touch = ring_outer("reef", reef)
    reef_route = next(i for i, r in enumerate(routes) if r["district"] == "reef")
    tried = []
    for k in [0] + [s * j for j in range(1, 31) for s in (1, -1)]:
        a = base + math.radians(2 * k)
        ux, uy = math.cos(a), math.sin(a)
        lake = {"cx": reef["cx"] + ux * (touch + LAKE_B), "cy": reef["cy"] + uy * (touch + LAKE_B),
                "rx": LAKE_A, "ry": LAKE_B, "angle": a + math.pi / 2}
        boundary = ellipse_boundary(lake)
        near = min(math.hypot(bx - reef["cx"], by - reef["cy"]) for bx, by in boundary) - touch
        worst_ring, worst_bridge = math.inf, math.inf
        for i, r in enumerate(routes):
            if i == reef_route:
                continue
            half = r.get("width", 2 * AV_HALF if r["district"] == "episodic" else 2 * ROAD_HALF) / 2 + SIDEWALK
            for x, y in r["points"][::2]:
                if math.hypot(x - lake["cx"], y - lake["cy"]) < LAKE_A + LAKE_RING + half + 1:
                    worst_ring = min(worst_ring, ellipse_gap(lake, x, y, boundary) - half)
        for st in streets:
            for x, y in st["points"]:
                if math.hypot(x - lake["cx"], y - lake["cy"]) < LAKE_A + LAKE_RING + AV_EDGE + 1:
                    worst_ring = min(worst_ring, ellipse_gap(lake, x, y, boundary) - AV_EDGE)
        for b in bridges:
            pts = [p[:2] for p in b["points"]] + [xy for e in b["ends"] for f in e["fillets"]
                                                  for xy in (f["ring"], f["bridge"])]
            for x, y in pts:
                if math.hypot(x - lake["cx"], y - lake["cy"]) < LAKE_A + LAKE_BRIDGE + EDGE + 1:
                    worst_bridge = min(worst_bridge, ellipse_gap(lake, x, y, boundary) - EDGE)
        tried.append((2 * k, round(worst_ring, 3), round(worst_bridge, 3)))
        if worst_ring >= LAKE_RING and worst_bridge >= LAKE_BRIDGE:
            px0, py0 = reef["cx"] + ux * touch, reef["cy"] + uy * touch
            px1, py1 = reef["cx"] + ux * (touch + PIER_L), reef["cy"] + uy * (touch + PIER_L)
            ix, iy = reef["cx"] + ux * (touch + PIER_L + ISLAND_R), reef["cy"] + uy * (touch + PIER_L + ISLAND_R)
            for t in range(72):
                bx, by = ix + ISLAND_R * math.cos(t * math.tau / 72), iy + ISLAND_R * math.sin(t * math.tau / 72)
                if ellipse_gap(lake, bx, by, boundary) > -0.5:
                    raise ValueError("Reef island does not sit on the water")
            ring_z = reef["z"] + 0.035
            # The search above uses conservative bounds; the published gaps are measured.
            ring_gap, bridge_gap = lake_clearances(lake, routes, streets, bridges, reef_route)
            if ring_gap < LAKE_RING or bridge_gap < LAKE_BRIDGE:
                raise ValueError(f"Lake clearance check failed: rings {ring_gap:.3f}, bridges {bridge_gap:.3f}")
            out = {"cx": round(lake["cx"], 4), "cy": round(lake["cy"], 4), "rx": LAKE_A, "ry": LAKE_B,
                   "angle": round(lake["angle"], 6), "z": LAKE_Z, "shoreTouch": round(near, 4) + 0.0,
                   "ringClearance": round(ring_gap, 3), "bridgeClearance": round(bridge_gap, 3),
                   "nudgeDeg": 2 * k, "centroid": [round(gx, 3), round(gy, 3)],
                   "pier": {"x0": round(px0, 4), "y0": round(py0, 4), "x1": round(px1, 4), "y1": round(py1, 4),
                            "width": PIER_W, "length": PIER_L, "z": round(ring_z, 4)},
                   "island": {"x": round(ix, 4), "y": round(iy, 4), "r": ISLAND_R, "z": round(reef["z"] + 0.045, 4)}}
            return [out]
    raise ValueError(f"No lake placement clears rings and bridges: {tried[:6]}")


# ------------------------------------------------------------------ obstacles for the re-flow
class Obstacles:
    """Bridges (deck to the sidewalk edge), fillet sidewalks, the pier, rim links and the lake."""

    def __init__(self, bridges, lake, streets, reach=3.8):
        self.grid = SegGrid(reach=reach)
        for b in bridges:
            self.grid.add_polyline(("bridge", b["id"]), b["points"], 0, EDGE)
            for e in b["ends"]:
                for f in e["fillets"]:
                    arc = arc_points(f["cx"], f["cy"], f["r"], f["a0"], f["a1"], 0.1)
                    self.grid.add_polyline(("fillet", b["id"]), arc, e["z"], SIDEWALK)
        self.lake = lake[0] if lake else None
        if self.lake:
            p = self.lake["pier"]
            self.grid.add(("pier", 0), (p["x0"], p["y0"]), (p["x1"], p["y1"]), p["z"], p["z"], PIER_W / 2)
            self.boundary = ellipse_boundary(self.lake)
        for k, st in enumerate(streets):
            self.grid.add_polyline(("street", k), st["points"], st["z"], AV_EDGE)

    def gap(self, x, y, kinds=("bridge", "fillet", "pier", "street")):
        """Smallest gap from (x, y) to any obstacle edge; the lake counts from its shore."""
        best = math.inf
        for owner, ax, ay, bx, by, _, _, half in self.grid.near(x, y):
            if owner[0] in kinds:
                best = min(best, segment_distance(x, y, ax, ay, bx, by) - half)
        return best

    def water(self, x, y):
        if not self.lake:
            return math.inf
        return ellipse_gap(self.lake, x, y, self.boundary)


def deck_clear(x, y, r, district, layout, obst, taken, own_roads=()):
    """A stage keeps 0.5 from other districts, bridges, the lake, the pier and other decks."""
    for other, q in layout["districts"].items():
        if other == district:
            continue
        if q["shape"] == "disc":
            gap = math.hypot(x - q["cx"], y - q["cy"]) - ring_outer(other, q) - r
        else:
            dx = max(0, abs(x - q["cx"]) - q["rx"] - 0.4 - EDGE)
            dy = max(0, abs(y - q["cy"]) - q["ry"] - 0.4)
            gap = math.hypot(dx, dy) - r
        if gap < 0.5:
            return False
    if obst.gap(x, y) < r + 0.5:
        return False
    if obst.water(x, y) < r + 0.5:
        return False
    for pts, half in own_roads:
        if any(math.hypot(px - x, py - y) < r + half for px, py in pts):
            return False
    for s in taken:
        if math.hypot(x - s["x"], y - s["y"]) < r + s["r"] + 0.5:
            return False
    return True


class StageRoom(ValueError):
    def __init__(self, district):
        super().__init__(f"No stage fits in {district}")
        self.district = district


def place_stages(data, layout, buildings, routes, bridges, lake, obst):
    """C4.2: one stage per district, a free plaza on the plateau or a deck outside its ring.
    The Reef stage stands on the lake island (C9.4).

    angle: a plaza's and a deck's angle is the direction from the district centre to the stage. The
    viewer puts the booth at +angle on a deck and at -angle otherwise, so the booth always sits on the
    side away from where the crowd walks in. The island follows the plaza rule: its angle points from
    the island to the pier landing (toward the Reef), so the booth stands on the far side of the island
    and the crowd fills the floor between the pier and the booth."""
    stages = []
    if lake:
        isl, pier = lake[0]["island"], lake[0]["pier"]
        reef = layout["districts"]["reef"]
        stages.append({"district": "reef", "name": STAGE_NAMES["reef"], "kind": "island",
                       "x": isl["x"], "y": isl["y"], "z": isl["z"], "r": isl["r"],
                       "angle": round(math.atan2(pier["y1"] - isl["y"], pier["x1"] - isl["x"]) % math.tau, 4),
                       "capacity": min(80, round(10 * math.pi * isl["r"] ** 2)), "n": reef["n"]})
    rim_roads = [(r["points"], EDGE) for r in routes if r.get("kind") == "rim"]
    for district, p in layout["districts"].items():
        if any(s["district"] == district for s in stages):
            continue
        n = p["n"]
        r0 = max(1.2, min(2.4, 0.9 + 0.12 * p["rx"])) if p["shape"] == "disc" else 2.4
        best = None
        # C4.2 allows a deck radius of 1.2 to 2.4: when the sized deck finds no free sector (the
        # Compass, boxed in by three spokes and three neighbour rings), step down toward 1.2.
        radii = [r0] + [round(r0 - 0.05 * k, 3) for k in range(1, 40) if r0 - 0.05 * k >= 1.2 - 1e-9]
        for r in radii if p["shape"] == "disc" else [r0]:
            outer = ring_outer(district, p)
            inner = p["rx"] + (0.75 if district == "onebrain" else 0.4) - 0.44 - 0.13
            for step in range(180 if p["shape"] == "disc" else 0):
                a = step * math.tau / 180
                ux, uy = math.cos(a), math.sin(a)
                facing = ux * VIEW[0] + uy * VIEW[1]
                # Option 1: a free disc on the plateau touching the ring, clear of any bridge overhead.
                cx, cy = p["cx"] + ux * (inner - r), p["cy"] + uy * (inner - r)
                if (inner - r > 0.5 and footprint_distance(cx, cy, data, buildings, layout) >= r + 0.2
                        and obst.gap(cx, cy, ("bridge", "fillet")) >= r + 0.5):
                    score = 10 + facing
                    if not best or score > best[0]:
                        best = (score, cx, cy, a, "plaza", p["z"] + 0.02)
                # Option 2: a deck outside the ring in a free sector.
                dx, dy = p["cx"] + ux * (outer + r), p["cy"] + uy * (outer + r)
                if deck_clear(dx, dy, r, district, layout, obst, stages):
                    clearance = min(4.0, min(
                        (math.hypot(dx - q["cx"], dy - q["cy"]) - ring_outer(o, q) - r
                         if q["shape"] == "disc" else 4.0)
                        for o, q in layout["districts"].items() if o != district))
                    score = clearance + 1.5 * facing
                    if not best or (best[4] != "plaza" and score > best[0]):
                        best = (score, dx, dy, a, "deck", p["z"] + 0.045)
            if best:
                break
        if p["shape"] != "disc":
            # The Archive: a deck off the south or north end of one of its four avenues.
            for route in routes:
                if route["district"] != district or route.get("kind") == "rim":
                    continue
                xs = [q[0] for q in route["points"]]
                cx = (min(xs) + max(xs)) / 2
                for sign in (-1, 1):
                    edge = p["cy"] + sign * p["ry"]
                    dx, dy = cx, edge + sign * (0.2 + r)
                    if not deck_clear(dx, dy, r, district, layout, obst, stages, rim_roads):
                        continue
                    score = -sign * 2 - abs(cx - (p["cx"] + p["rx"] * 0.35)) * 0.05
                    if not best or score > best[0]:
                        best = (score, dx, dy, math.atan2(sign, 0), "deck", p["z"] + 0.045)
        if not best:
            raise StageRoom(district)
        _, x, y, a, kind, z = best
        stages.append({"district": district, "name": STAGE_NAMES[district], "kind": kind,
                       "x": round(x, 3), "y": round(y, 3), "z": round(z, 3), "r": round(r, 3),
                       "angle": round(a, 4), "capacity": min(80, round(10 * math.pi * r * r)), "n": n})
    order = list(layout["districts"])
    stages.sort(key=lambda s: order.index(s["district"]))
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


def route_half(route):
    return route.get("width", 2 * AV_HALF if route["district"] == "episodic" else 2 * ROAD_HALF) / 2


def own_points(route):
    """A route's points without the stretch it shares with another route."""
    if not route.get("shared"):
        return route["points"]
    cut = route["shared"][0]["from"]
    cum = cumulative(route["points"], True)
    return [p for p, s in zip(route["points"], cum) if s <= cut + 1e-3]


def route_points_by_district(routes):
    grid = {}
    for route in routes:
        half = route_half(route)
        for x, y in own_points(route):
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


def place_venues(data, layout, buildings, routes, stages, obst):
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
        # C4.3 type weights as quotas: largest remainder over the chosen hosts, then a seeded shuffle,
        # so even a small district matches its table (a random draw per venue missed it badly).
        kinds = []
        if district in SINGLE_VENUE:
            kinds = [SINGLE_VENUE[district]] * len(chosen)
        elif chosen:
            weights = VENUE_WEIGHTS[district]
            exact = [w * len(chosen) / sum(weights) for w in weights]
            quota = [math.floor(x) for x in exact]
            order = sorted(range(len(weights)), key=lambda i: (-(exact[i] - quota[i]), i))
            for i in order[:len(chosen) - sum(quota)]:
                quota[i] += 1
            for name, count in zip(VENUE_TYPES, quota):
                kinds += [VENUE_OTHER.get(district, "bar") if name == "other" else name] * count
            for i in range(len(kinds) - 1, 0, -1):
                j = int(rnd() * (i + 1))
                kinds[i], kinds[j] = kinds[j], kinds[i]
        for v, kind in zip(chosen, kinds):
            # A terrace only where the free strip in front of the face is 0.25 deep or more,
            # and never over a bridge landing, a fillet, the pier or the water.
            terrace = 0.0
            if v["gap"] >= 0.25:
                depth = min(0.5, v["gap"] - 0.04)
                ok = True
                for a in (0.1, depth * 0.5, depth):
                    for b in (-0.35, 0, 0.35):
                        tx = v["x"] + v["face"][0] * a + (-v["face"][1]) * b * v["length"]
                        ty = v["y"] + v["face"][1] * a + v["face"][0] * b * v["length"]
                        if obst.gap(tx, ty) < 0.02 or obst.water(tx, ty) < 0.02:
                            ok = False
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


def on_plateau(x, y, p, margin=0.05):
    if p["shape"] == "disc":
        return math.hypot(x - p["cx"], y - p["cy"]) <= p["rx"] - margin
    return abs(x - p["cx"]) <= p["rx"] - margin and abs(y - p["cy"]) <= p["ry"] - margin


def place_furniture(data, layout, buildings, routes, stages, venues, obst):
    """C4.5: terrace sets, carts on the stage decks and free spots near the roads, manholes."""
    items, taken = [], []
    own = [own_points(r) for r in routes]

    def free(x, y, r, district):
        if footprint_distance(x, y, data, buildings, layout) < r + 0.2:
            return False
        for i, route in enumerate(routes):
            if route["district"] != district:
                continue
            half = route_half(route)
            lane = min(half + 0.04, route.get("clearanceOwn", route["clearance"]) - 0.12)
            for px, py in own[i][::2]:
                d = math.hypot(px - x, py - y)
                if d < half + r + 0.02 or abs(d - lane) < r + 0.08:
                    return False
        if obst.gap(x, y) < r + 0.02 or obst.water(x, y) < r + 0.05:
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
    for ri, route in enumerate(routes):
        half = route_half(route)
        pts = own[ri]
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
                    if on_plateau(x, y, p) and free(x, y, r, route["district"]):
                        add(kind, x, y, p["z"], math.atan2(-ox, -oy), route["district"], int(rnd() * 5), -1, r)
                        placed += 1
                        break
    for ri, route in enumerate(routes):
        pts = own[ri]
        for j in range(3, len(pts), max(40, len(pts) // 3)):
            x, y = pts[j]
            items.append({"kind": "manhole", "x": round(x, 3), "y": round(y, 3), "z": round(route["z"] - 0.035, 3),
                          "rot": 0, "district": route["district"], "variant": 0, "venue": -1})
    return items


def place_trees(data, layout, buildings, routes, bridges, lake, stages, venues, furniture):
    """C10.2 hook: wax palms, lake trees and balcony plants arrive in V7."""
    return []


# ------------------------------------------------------------------ C5.4 road graph and C6.6 tour
def build_graph(routes, streets, forks, bridges):
    nodes, edges, turns = [], [], []
    stops = {i: [] for i in range(len(routes))}
    cums = [cumulative(r["points"], True) for r in routes]
    rim_index = next(i for i, r in enumerate(routes) if r.get("kind") == "rim")

    def add_node(x, y, z, kind, district):
        nodes.append({"id": len(nodes), "kind": kind, "x": round(x, 4), "y": round(y, 4), "z": round(z, 4),
                      "district": district, "ports": [], "moves": []})
        return len(nodes) - 1

    fork_node = []
    for f in forks:
        nid = add_node(f["x"], f["y"], f["z"], "fork", "episodic")
        fork_node.append(nid)
        for ri, s in f["at"]:
            stops[rim_index if ri == "rim" else ri].append((s, nid))
    for b in bridges:
        for e in b["ends"]:
            e["node"] = add_node(e["x"], e["y"], e["z"], "tee", e["district"])
            stops[e["route"]].append((e["s"], e["node"]))
    for ri, r in enumerate(routes):
        total = cums[ri][-1]
        st = sorted(stops[ri])
        if not st:
            st = [(0.0, add_node(r["points"][0][0], r["points"][0][1], r["z"], "loop", r["district"]))]
        kind = {"rim": "rim"}.get(r.get("kind"), "avenue" if r["district"] == "episodic" else "ring")
        for k in range(len(st)):
            s0, a = st[k]
            s1, b = st[(k + 1) % len(st)]
            if k == len(st) - 1:
                s1 += total
            if any(s0 >= sh["from"] - 1e-3 and s1 <= sh["to"] + 1e-3 for sh in r.get("shared", ())):
                continue
            edges.append({"id": len(edges), "a": a, "b": b, "kind": kind, "route": ri, "s0": round(s0, 4),
                          "s1": round(s1, 4), "length": round(s1 - s0, 4), "district": r["district"]})
    for k, st in enumerate(streets):
        a, b = fork_node[st["fork"][0]], fork_node[st["fork"][1]]
        st["nodes"] = [a, b]
        edges.append({"id": len(edges), "a": a, "b": b, "kind": "link", "street": k,
                      "length": round(cumulative(st["points"], False)[-1], 4), "district": "episodic"})
    for b in bridges:
        edges.append({"id": len(edges), "a": b["ends"][0]["node"], "b": b["ends"][1]["node"], "kind": "bridge",
                      "bridge": b["id"], "length": b["length"], "district": None, "from": b["from"], "to": b["to"],
                      "split": b["split"]})
        b["edge"] = len(edges) - 1

    def polyline(e):
        """Centreline of an edge as [x, y, z] from end a to end b."""
        if e["kind"] == "bridge":
            return [list(p) for p in bridges[e["bridge"]]["points"]]
        if e["kind"] == "link":
            st = streets[e["street"]]
            return [[x, y, st["z"]] for x, y in st["points"]]
        r = routes[e["route"]]
        return route_slice(r["points"], cums[e["route"]], e["s0"], e["s1"], r["z"])

    def leave_dir(e, end):
        pts = polyline(e)
        if end == 1:
            pts = pts[::-1]
        a = pts[0]
        for q in pts[1:]:
            if math.dist(a[:2], q[:2]) > 0.04:
                length = math.dist(a[:2], q[:2])
                return (q[0] - a[0]) / length, (q[1] - a[1]) / length
        return 1.0, 0.0

    for e in edges:
        for end, nid in ((0, e["a"]), (1, e["b"])):
            nodes[nid]["ports"].append([e["id"], end])
    # T junction turns through each fillet (C5.4: any vehicle can turn either way).
    turn_of = {}
    for b in bridges:
        for ei, end in enumerate(b["ends"]):
            total = cums[end["route"]][-1]
            for f in end["fillets"]:
                delta = ((f["ringS"] - end["s"] + total / 2) % total) - total / 2
                turns.append({"id": len(turns), "node": end["node"], "bridge": b["id"], "end": ei,
                              "side": f["side"], "ringSide": 1 if delta > 0 else -1,
                              "trimRing": round(abs(delta), 4), "trimBridge": f["bridgeS"],
                              "length": round(cumulative(f["turn"], False)[-1], 4), "points": f["turn"]})
                turn_of[(end["node"], 1 if delta > 0 else -1)] = len(turns) - 1
    for node in nodes:
        dirs = {tuple(p): leave_dir(edges[p[0]], p[1]) for p in node["ports"]}
        for pin in node["ports"]:
            ax, ay = dirs[tuple(pin)]
            for pout in node["ports"]:
                if pin == pout:
                    continue
                bx, by = dirs[tuple(pout)]
                if -ax * bx - ay * by < -0.17:
                    continue
                ein, eout = edges[pin[0]], edges[pout[0]]
                turn, tdir = -1, 0
                if (ein["kind"] == "bridge") != (eout["kind"] == "bridge"):
                    if ein["kind"] == "bridge":
                        ring_side = 1 if pout[1] == 0 else -1
                        tdir = -1
                    else:
                        ring_side = -1 if pin[1] == 1 else 1
                        tdir = 1
                    turn = turn_of[(node["id"], ring_side)]
                node["moves"].append([pin[0], pin[1], pout[0], pout[1], turn, tdir])
    return {"nodes": nodes, "edges": edges, "turns": turns}, polyline


def route_slice(points, cum, s0, s1, z):
    """Route centreline between arc lengths s0 < s1 (s1 may pass the loop end), as [x, y, z]."""
    total = cum[-1]
    out = []
    x, y, _, _ = polyline_at(points, cum, s0)
    out.append([x, y, z])
    k = bisect.bisect_right(cum, s0 % total)
    base = s0 - (s0 % total)
    while True:
        if k >= len(points):
            k, base = 0, base + total
        s = base + cum[k]
        if s >= s1 - 1e-9:
            break
        out.append([points[k][0], points[k][1], z])
        k += 1
    x, y, _, _ = polyline_at(points, cum, s1)
    out.append([x, y, z])
    return out


def cut(points, lo, hi):
    """The part of an [x, y, z] polyline between arc lengths lo and hi."""
    cum = cumulative(points, False)
    lo, hi = max(0.0, lo), min(cum[-1], hi)

    def at(s):
        i = max(0, min(len(cum) - 2, bisect.bisect_right(cum, s) - 1))
        t = (s - cum[i]) / ((cum[i + 1] - cum[i]) or 1e-12)
        return [points[i][j] + (points[i + 1][j] - points[i][j]) * t for j in range(3)]
    out = [at(lo)]
    out += [list(points[i]) for i in range(len(points)) if lo + 1e-9 < cum[i] < hi - 1e-9]
    out.append(at(hi))
    return out


def plan_tour(graph, polyline, routes, bridges, layout):
    nodes, edges, turns = graph["nodes"], graph["edges"], graph["turns"]
    moves = {}
    for node in nodes:
        for m in node["moves"]:
            moves.setdefault((m[0], m[1]), []).append(m)
    boulevard = max((i for i, r in enumerate(routes) if r["district"] == "episodic" and r.get("kind") != "rim"),
                    key=lambda i: min(p[0] for p in routes[i]["points"]))
    xmin = min(p[0] for p in routes[boulevard]["points"])
    west_side = next(e for e in edges if e.get("route") == boulevard and
                     abs(nodes[e["a"]]["x"] - xmin) < 1e-3 and abs(nodes[e["b"]]["x"] - xmin) < 1e-3)

    def search(start, goal_edge, goal_end, district, must=None):
        best = {}
        heap = [(0.0, 0, start, must is None, None)]
        counter = 1
        while heap:
            cost, _, state, flag, back = heapq.heappop(heap)
            key = (state, flag)
            if key in best:
                continue
            best[key] = back
            if state == (goal_edge, goal_end) and flag:
                path, k = [], key
                while best[k] is not None:
                    prev_key, step = best[k]
                    path.append(step)
                    k = prev_key
                return path[::-1]
            for m in moves.get(state, ()):
                e = edges[m[2]]
                if e["id"] != goal_edge and e["district"] != district:
                    continue
                nstate = (m[2], 1 - m[3])
                nflag = flag or (must is not None and m[2] == must)
                step = {"edge": m[2], "from": m[3], "turn": m[4], "tdir": m[5]}
                extra = turns[m[4]]["length"] if m[4] >= 0 else 0
                heapq.heappush(heap, (cost + e["length"] + extra, counter, nstate, nflag, (key, step)))
                counter += 1
        raise ValueError(f"No tour path in {district}")

    legs = [(bridges[k]["edge"], dest) for k, dest in TOUR]
    steps = []
    first_archive = True
    for i, (edge_id, dest) in enumerate(legs):
        prev_edge, here = legs[i - 1]
        e_prev = edges[prev_edge]
        arrive_end = 1 if nodes[e_prev["b"]]["district"] == here else 0
        e_next = edges[edge_id]
        leave_end = 0 if nodes[e_next["a"]]["district"] == here else 1
        must = None
        if here == "episodic" and first_archive:
            must, first_archive = west_side["id"], False
        steps += search((prev_edge, arrive_end), edge_id, 1 - leave_end, here, must)
    # Build the polyline: trimmed edges joined by fillet turns.
    pieces = []
    for i, st in enumerate(steps):
        e = edges[st["edge"]]
        nxt = steps[(i + 1) % len(steps)]
        if st["turn"] >= 0:
            t = turns[st["turn"]]
            pts = [list(p) for p in t["points"]]
            pieces.append({"kind": "turn", "turn": t["id"], "points": pts if st["tdir"] > 0 else pts[::-1],
                           "district": nodes[t["node"]]["district"]})
        trim0 = 0.0
        if st["turn"] >= 0:
            trim0 = turns[st["turn"]]["trimBridge" if e["kind"] == "bridge" else "trimRing"]
        trim1 = 0.0
        if nxt["turn"] >= 0:
            trim1 = turns[nxt["turn"]]["trimBridge" if e["kind"] == "bridge" else "trimRing"]
        pts = polyline(e)
        if st["from"] == 1:
            pts = pts[::-1]
        length = cumulative(pts, False)[-1]
        pieces.append({"kind": e["kind"], "edge": e["id"], "points": cut(pts, trim0, length - trim1),
                       "district": e["district"], "trim0": trim0})
    dense, owner = [], []
    for pi, pc in enumerate(pieces):
        for p in pc["points"]:
            if dense and math.dist(dense[-1][:2], p[:2]) < 1e-6:
                continue
            dense.append(p)
            owner.append(pi)
    if math.dist(dense[-1][:2], dense[0][:2]) < 1e-6:
        dense.pop()
        owner.pop()
    cum = cumulative(dense, False)
    total = cum[-1] + math.dist(dense[-1][:2], dense[0][:2])
    route_of = {}
    for d, p in layout["districts"].items():
        route_of[d] = next(i for i, r in enumerate(routes) if r["district"] == d and
                           (p["shape"] == "disc" or r.get("kind") == "rim"))

    def near_ring(district, x, y):
        return project_polyline(routes[route_of[district]]["points"], x, y)[0]

    n = len(dense)

    def s_at(i):
        return cum[i % n] + total * (i // n)

    def cross(i0, district, outward, limit=600):
        """First crossing of a district ring's outer sidewalk edge, scanning forward from i0 (wraps)."""
        prev = None
        for i in range(i0, i0 + limit):
            d = near_ring(district, *dense[i % n][:2])
            if prev is not None and ((outward and prev[1] < EDGE <= d) or (not outward and prev[1] > EDGE >= d)):
                t = (EDGE - prev[1]) / (d - prev[1])
                return s_at(prev[0]) + t * (s_at(i) - s_at(prev[0]))
            prev = (i, d)
        raise ValueError(f"tour never crosses the {district} ring edge")

    raw = []
    bridge_pieces = [pi for pi, pc in enumerate(pieces) if pc["kind"] == "bridge"]
    for n_leg, pi in enumerate(bridge_pieces):
        b = bridges[edges[pieces[pi]["edge"]]["bridge"]]
        start_i = owner.index(pi)
        dest = TOUR[n_leg][1]
        origin = b["from"] if dest == b["to"] else b["to"]
        i = start_i - 1
        while owner[i % n] == pi - 1 and pieces[pi - 1]["kind"] == "turn":
            i -= 1
        raw.append({"bridge": b["id"], "from": origin, "to": dest, "depart": cross(i, origin, True),
                    "mid": cum[start_i] + b["length"] / 2 - pieces[pi]["trim0"], "land": cross(start_i, dest, False)})
    # The walk starts where it lands back in the Compass, so every district entry is a positive s.
    # s0 is published rounded, and the polyline below starts at the rounded value, so the viewer's
    # rebuild (viewer/roads.js) lands on exactly the same points.
    s0 = round(raw[-1]["land"] % total, 4)
    covered_unique = sum(edges[e]["length"] for e in {st["edge"] for st in steps
                                                       if edges[st["edge"]].get("route") == boulevard})
    perimeter = cumulative(routes[boulevard]["points"], True)[-1]
    # The tour polyline: uniform spacing of about 0.25 on the closed walk, starting at s0. Every
    # distance below is measured on this polyline. The page leaves the points out: the viewer rebuilds
    # them from the steps, s0 and the count (tour_points() is the reference rebuild).
    m = math.ceil(total / 0.25)
    out = []
    for k in range(m):
        s = (s0 + total * k / m) % total
        j = max(0, min(n - 1, bisect.bisect_right(cum, s) - 1))
        a, b2 = dense[j], dense[(j + 1) % n]
        seg = (cum[j + 1] if j + 1 < n else total) - cum[j]
        t = (s - cum[j]) / (seg or 1e-12)
        out.append([a[q] + (b2[q] - a[q]) * t for q in range(3)])
    ocum = cumulative(out, True)
    olen = ocum[-1]
    on = len(out)

    def s_out(i):
        return ocum[i % on] + olen * (i // on)

    def cross_out(expect, district, outward):
        i0 = max(0, int(((expect - 2.0) % total) / total * on))
        prev = None
        for i in range(i0, i0 + on):
            d = near_ring(district, *out[i % on][:2])
            if prev is not None and ((outward and prev[1] < EDGE <= d) or (not outward and prev[1] > EDGE >= d)):
                t = (EDGE - prev[1]) / (d - prev[1])
                return s_out(prev[0]) + t * (s_out(i) - s_out(prev[0]))
            prev = (i, d)
        raise ValueError(f"tour never crosses the {district} ring edge")

    rot = lambda v: (v - s0) % total
    legs_out, entries = [], [{"district": "core", "s": 0.0, "bridge": None}]
    for k, leg in enumerate(raw):
        land = olen if k == len(raw) - 1 else cross_out(rot(leg["land"]), leg["to"], False)
        depart = cross_out(rot(leg["depart"]), leg["from"], True)
        mid = rot(leg["mid"]) * olen / total
        legs_out.append({"bridge": leg["bridge"], "from": leg["from"], "to": leg["to"],
                         "depart": round(depart, 3), "mid": round(mid, 3), "land": round(land, 3)})
        if k < len(raw) - 1:
            entries.append({"district": leg["to"], "s": round(land, 3), "bridge": leg["bridge"]})
    spans = [{"district": en["district"], "from": en["s"],
              "to": entries[i + 1]["s"] if i + 1 < len(entries) else round(olen, 3)}
             for i, en in enumerate(entries)]
    return {"length": round(olen, 3), "start": "core", "spacing": round(round(olen, 3) / m, 5), "points": out,
            "s0": s0, "count": m,
            "steps": [[st["edge"], st["from"], st["turn"], st["tdir"]] for st in steps],
            "legs": legs_out, "entries": entries, "spans": spans,
            "districts": len({en["district"] for en in entries}),
            "archiveAvenue": {"route": boulevard, "perimeter": round(perimeter, 3),
                              "covered": round(covered_unique, 3), "fraction": round(covered_unique / perimeter, 3)}}


def build_design(data, layout, timings=None):
    timings = {} if timings is None else timings
    t0 = time.perf_counter()
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
        # The exact minimum of footprint_clearance over every point and nearby building, with a
        # bound that skips a building once one axis alone is already farther than the best so far.
        boxes = [(*layout["pos"][str(n["id"])], buildings[str(n["id"])]["w"] * 0.57,
                  buildings[str(n["id"])]["d"] * 0.57) for n in nearby]
        clearance = math.inf
        for px, py in route["points"]:
            for bx, by, hw, hd in boxes:
                dx = abs(px - bx) - hw
                if dx >= clearance:
                    continue
                dy = abs(py - by) - hd
                if dy >= clearance:
                    continue
                d = math.hypot(max(0, dx), max(0, dy))
                if d < clearance:
                    clearance = d
        # Half a car is .10; a .14 camera sphere fits inside this corridor.
        if clearance < 0.20:
            raise ValueError(f"Unsafe street: {route['name']} clearance={clearance:.3f}")
        route["clearance"] = round(clearance, 3)
        # Three decimals (half a millimetre at 4.5 m per unit) keep the page small; every later layer
        # places against these rounded points, so the page and the placement agree exactly.
        route["points"] = [[round(x, 3), round(y, 3)] for x, y in route["points"]]
    # C6.2: the Archive east rim road joins Memory boulevard; rim links join the other avenues.
    rim, streets, forks = archive_roads(layout, routes, data, buildings)
    routes.append(rim)
    rim_index = len(routes) - 1
    timings["routes"] = time.perf_counter() - t0
    # Ordered placement slots: later layers must consume earlier reservations.
    t0 = time.perf_counter()
    bridges = place_bridges(data, layout, buildings, routes, streets, rim_index)
    timings["bridges"] = time.perf_counter() - t0
    reserve, attempts = [], []
    while True:
        t0 = time.perf_counter()
        lake = place_lake(data, layout, routes, streets, bridges)
        timings["lake"] = time.perf_counter() - t0
        t0 = time.perf_counter()
        obst = Obstacles(bridges, lake, streets)
        try:
            stages = place_stages(data, layout, buildings, routes, bridges, lake, obst)
            timings["stages"] = time.perf_counter() - t0
            break
        except StageRoom as err:
            # C4.2 needs a stage in every district. When the bridges fill every free sector of a
            # district (the Compass: three spokes in the only three gaps between its neighbours),
            # reserve a deck slot there and solve the bridges again around it. The first slot that
            # keeps the district's bridges clean (40 degree window, tier 0) wins; otherwise the first
            # slot that fits at all.
            if any(r[0] == err.district for r in reserve):
                raise
            t0 = time.perf_counter()
            chosen, fallback = None, None
            for district, x, y, r, a in stage_slots(err.district, layout):
                slot = (district, round(x, 4), round(y, 4), r)
                try:
                    bridges = place_bridges(data, layout, buildings, routes, streets, rim_index,
                                            reserve + [slot], clean=district)
                    chosen = slot
                    attempts.append({"district": district, "angle": a, "r": r, "result": "clean"})
                    break
                except NotClean as nc:
                    attempts.append({"district": district, "angle": a, "r": r, "result": str(nc)})
                    fallback = fallback or slot
                except ValueError as ve:
                    attempts.append({"district": district, "angle": a, "r": r, "result": str(ve)[:80]})
            if chosen is None:
                if fallback is None:
                    raise
                chosen = fallback
                bridges = place_bridges(data, layout, buildings, routes, streets, rim_index, reserve + [chosen])
            reserve.append(chosen)
            timings["reserve"] = timings.get("reserve", 0.0) + time.perf_counter() - t0
    timings["reservations"] = {"slots": [list(r) for r in reserve], "attempts": attempts}
    t0 = time.perf_counter()
    venues = place_venues(data, layout, buildings, routes, stages, obst)
    timings["venues"] = time.perf_counter() - t0
    t0 = time.perf_counter()
    furniture = place_furniture(data, layout, buildings, routes, stages, venues, obst)
    trees = place_trees(data, layout, buildings, routes, bridges, lake, stages, venues, furniture)
    timings["furniture"] = time.perf_counter() - t0
    t0 = time.perf_counter()
    graph, polyline = build_graph(routes, streets, forks, bridges)
    tour = plan_tour(graph, polyline, routes, bridges, layout)
    timings["graph+tour"] = time.perf_counter() - t0
    for st in streets:
        st.pop("fork", None)
    # The solver log goes to the side report; the fillets' turn arcs live once, in graph.turns.
    search = {}
    for b in bridges:
        search[b["name"]] = b.pop("search")
        for e in b["ends"]:
            for f in e["fillets"]:
                f.pop("turn", None)
    timings["search"] = search
    return {"palette": PALETTE, "buildings": buildings, "routes": routes, "streets": streets,
            "bridges": bridges, "lake": lake, "stages": stages, "venues": venues,
            "furniture": furniture, "trees": trees, "graph": graph, "tour": tour}


# ------------------------------------------------------------------ page data (C13.3 page budget)
# The page data leaves out what the viewer rebuilds from the rest; viewer/roads.js rebuilds it into
# exactly the shape build_design returns (expand() here is the reference), and main() refuses to write
# page data that does not rebuild the design exactly.
#   graph.nodes[k]: id = k; ports = every edge end at the node, in edge order.
#   graph.edges[k]: id = k; a bridge edge's from, to and split are its bridge's.
#   bridges[i]: spoke = (from is the Compass); halfWidth = width / 2 + sidewalk.
#   tour: spacing = length / count; districts = distinct entry districts; spans run from one entry to
#     the next (the last one to length).
#   graph.turns[k]: id = k; node = its bridge end's node; points = turn_arc of its fillet at the end's
#     height; length = the arc length of those points.
#   bridges[i].ends[j].fillets[k]: ring and bridge = (cx, cy) + r (cos, sin) of a0 and a1.
#   tour.points: the steps' edges and turn arcs joined, resampled from s0 in count equal steps.
def publish(design):
    out = dict(design)
    out["bridges"] = [{**{k: v for k, v in b.items() if k not in ("spoke", "halfWidth")},
                       "ends": [{**e, "fillets": [{k: v for k, v in f.items() if k not in ("ring", "bridge")}
                                                  for f in e["fillets"]]} for e in b["ends"]]}
                      for b in design["bridges"]]
    g = design["graph"]
    out["graph"] = {"nodes": [{k: v for k, v in n.items() if k not in ("id", "ports")} for n in g["nodes"]],
                    "edges": [{k: v for k, v in e.items() if k not in ("id", "from", "to", "split")}
                              for e in g["edges"]],
                    "turns": [{k: v for k, v in t.items() if k not in ("id", "node", "points", "length")}
                              for t in g["turns"]]}
    out["tour"] = {k: v for k, v in design["tour"].items()
                   if k not in ("points", "spans", "spacing", "districts")}
    return out


def fillet_of(design, bridge, end, side):
    return next(f for f in design["bridges"][bridge]["ends"][end]["fillets"] if f["side"] == side)


def turn_points(design, t):
    """Rebuild one graph turn arc from its published fillet."""
    z = design["bridges"][t["bridge"]]["ends"][t["end"]]["z"]
    return [[x, y, z] for x, y in turn_arc(fillet_of(design, t["bridge"], t["end"], t["side"]))]


def edge_points(design, e, cums):
    """Centreline of a graph edge as [x, y, z] from its a end to its b end."""
    if e["kind"] == "bridge":
        return [list(p) for p in design["bridges"][e["bridge"]]["points"]]
    if e["kind"] == "link":
        st = design["streets"][e["street"]]
        return [[x, y, st["z"]] for x, y in st["points"]]
    r = design["routes"][e["route"]]
    if e["route"] not in cums:
        cums[e["route"]] = cumulative(r["points"], True)
    return route_slice(r["points"], cums[e["route"]], e["s0"], e["s1"], r["z"])


def tour_points(design):
    """The tour polyline rebuilt from its graph steps (design must carry the turn points)."""
    g, tour = design["graph"], design["tour"]
    edges, turns, steps = g["edges"], g["turns"], tour["steps"]
    cums, dense = {}, []

    def add(points):
        for p in points:
            if not dense or math.dist(dense[-1][:2], p[:2]) >= 1e-6:
                dense.append(p)
    for i, (edge, frm, turn, tdir) in enumerate(steps):
        e, nxt = edges[edge], steps[(i + 1) % len(steps)]
        key = "trimBridge" if e["kind"] == "bridge" else "trimRing"
        if turn >= 0:
            pts = [list(p) for p in turns[turn]["points"]]
            add(pts if tdir > 0 else pts[::-1])
        trim0 = turns[turn][key] if turn >= 0 else 0.0
        trim1 = turns[nxt[2]][key] if nxt[2] >= 0 else 0.0
        pts = edge_points(design, e, cums)
        if frm == 1:
            pts = pts[::-1]
        add(cut(pts, trim0, cumulative(pts, False)[-1] - trim1))
    if math.dist(dense[-1][:2], dense[0][:2]) < 1e-6:
        dense.pop()
    n, cum = len(dense), cumulative(dense, False)
    total = cum[-1] + math.dist(dense[-1][:2], dense[0][:2])
    out, m, s0 = [], tour["count"], tour["s0"]
    for k in range(m):
        s = (s0 + total * k / m) % total
        j = max(0, min(n - 1, bisect.bisect_right(cum, s) - 1))
        a, b = dense[j], dense[(j + 1) % n]
        seg = (cum[j + 1] if j + 1 < n else total) - cum[j]
        t = (s - cum[j]) / (seg or 1e-12)
        out.append([a[q] + (b[q] - a[q]) * t for q in range(3)])
    return out


def expand(page):
    """The design rebuilt from the page data (the reference for viewer/roads.js)."""
    d = dict(page)
    d["bridges"] = [{**b, "spoke": b["from"] == "core", "halfWidth": round(b["width"] / 2 + b["sidewalk"], 3),
                     "ends": [{**e, "fillets": [
        {**f, "ring": [round(f["cx"] + f["r"] * math.cos(math.radians(f["a0"])), 4),
                       round(f["cy"] + f["r"] * math.sin(math.radians(f["a0"])), 4)],
         "bridge": [round(f["cx"] + f["r"] * math.cos(math.radians(f["a1"])), 4),
                    round(f["cy"] + f["r"] * math.sin(math.radians(f["a1"])), 4)]}
        for f in e["fillets"]]} for e in b["ends"]]} for b in page["bridges"]]
    g = page["graph"]
    nodes = [{"id": k, **n, "ports": []} for k, n in enumerate(g["nodes"])]
    edges = [{"id": k, **e, **({"from": d["bridges"][e["bridge"]]["from"], "to": d["bridges"][e["bridge"]]["to"],
                                "split": d["bridges"][e["bridge"]]["split"]} if e["kind"] == "bridge" else {})}
             for k, e in enumerate(g["edges"])]
    for e in edges:
        nodes[e["a"]]["ports"].append([e["id"], 0])
        nodes[e["b"]]["ports"].append([e["id"], 1])
    turns = []
    for k, t in enumerate(g["turns"]):
        pts = turn_points(d, t)
        turns.append({"id": k, "node": d["bridges"][t["bridge"]]["ends"][t["end"]]["node"], **t,
                      "length": round(cumulative(pts, False)[-1], 4), "points": pts})
    d["graph"] = {"nodes": nodes, "edges": edges, "turns": turns}
    tour = page["tour"]
    entries = tour["entries"]
    d["tour"] = {**tour, "points": None,
                 "spacing": round(tour["length"] / tour["count"], 5),
                 "spans": [{"district": en["district"], "from": en["s"],
                            "to": entries[i + 1]["s"] if i + 1 < len(entries) else tour["length"]}
                           for i, en in enumerate(entries)],
                 "districts": len({en["district"] for en in entries})}
    d["tour"]["points"] = tour_points(d)
    return d


def check_rebuild(design, page):
    """The page data must rebuild the design exactly: every graph field, turn arc and tour point."""
    full = expand(json.loads(json.dumps(page)))
    g, h = design["graph"], full["graph"]
    for name in ("nodes", "edges"):
        if json.dumps(g[name], sort_keys=True) != json.dumps(h[name], sort_keys=True):
            raise ValueError(f"graph {name} do not rebuild")
    for key in ("spans", "spacing", "districts", "length", "entries", "legs", "steps", "s0", "count"):
        if json.dumps(design["tour"][key]) != json.dumps(full["tour"][key]):
            raise ValueError(f"tour {key} does not rebuild")
    for b, c in zip(design["bridges"], full["bridges"]):
        if b["spoke"] != c["spoke"] or b["halfWidth"] != c["halfWidth"]:
            raise ValueError(f"bridge {b['id']} does not rebuild")
    worst = 0.0
    for t, u in zip(g["turns"], h["turns"]):
        if {k: v for k, v in t.items() if k != "points"} != {k: v for k, v in u.items() if k != "points"}:
            raise ValueError(f"turn {t['id']} does not rebuild: {u}")
        if len(t["points"]) != len(u["points"]):
            raise ValueError(f"turn {t['id']} rebuilds {len(u['points'])} points, not {len(t['points'])}")
        worst = max([worst] + [math.dist(p, q) for p, q in zip(t["points"], u["points"])])
    for b, c in zip(design["bridges"], full["bridges"]):
        for e, f in zip(b["ends"], c["ends"]):
            for x, y in zip(e["fillets"], f["fillets"]):
                worst = max(worst, math.dist(x["ring"], y["ring"]) - 2e-4, math.dist(x["bridge"], y["bridge"]) - 2e-4)
    a, b = design["tour"]["points"], full["tour"]["points"]
    if len(a) != len(b):
        raise ValueError(f"tour rebuilds {len(b)} points, not {len(a)}")
    worst = max([worst] + [math.dist(p, q) for p, q in zip(a, b)])
    if worst > 1e-9:
        raise ValueError(f"page data does not rebuild the design: {worst:.2e}")
    return worst


def main(out=OUT, report=None):
    data = json.loads((ROOT / "data/vault-city.json").read_text(encoding="utf-8"))
    layout = json.loads((ROOT / "data/layout.json").read_text(encoding="utf-8"))
    timings = {}
    t0 = time.perf_counter()
    result = build_design(data, layout, timings)
    page = publish(result)
    check_rebuild(result, page)
    total = time.perf_counter() - t0
    search = timings.pop("search")
    reservations = timings.pop("reservations")
    text = json.dumps(page, separators=(",", ":"))
    Path(out).write_text(text, encoding="utf-8")
    if report:
        side = {"seconds": round(total, 3), "phases": {k: round(v, 3) for k, v in timings.items()},
                "bytes": {k: len(json.dumps(v, separators=(",", ":"))) for k, v in page.items()},
                "rng": rng_edges(layout), "reservations": reservations, "search": search}
        Path(report).write_text(json.dumps(side, indent=1), encoding="utf-8")
    print(f"Designed {len(page['buildings'])} buildings, {len(page['routes'])} street loops, "
          f"{len(page['bridges'])} bridges, {len(page['stages'])} stages, {len(page['venues'])} venues, "
          f"{len(page['furniture'])} furniture items in {total:.2f} s ({len(text)} bytes)")
    return page


if __name__ == "__main__":
    args = sys.argv[1:]
    main(report=args[args.index("--report") + 1] if "--report" in args else None)
